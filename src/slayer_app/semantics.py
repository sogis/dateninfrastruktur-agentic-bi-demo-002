"""Small public expression compiler; all analytical work belongs to SLayer."""

from __future__ import annotations

from . import config
import ast
import json
import io
import math
import re
import tokenize
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from functools import cmp_to_key
from collections.abc import Mapping

from slayer.core.query import SlayerQuery
from slayer.engine.syntax import parse_expr
from .contracts import (
    AnalysisError,
    AnalysisRequest,
    AggregateNode,
    ConstantNode,
    BinaryNode,
    PeriodNode,
)


def fail(code, message, **details):
    raise AnalysisError(code, message, details)


def native_ref(parts):
    node = ast.Name(id=parts[0], ctx=ast.Load())
    for part in parts[1:]:
        node = ast.Attribute(value=node, attr=part, ctx=ast.Load())
    return node


def call(name, *args, **kwargs):
    return ast.Call(
        func=native_ref((name,)),
        args=list(args),
        keywords=[ast.keyword(arg=k, value=v) for k, v in kwargs.items()],
    )


def render(node):
    text = ast.unparse(ast.fix_missing_locations(node))
    original = ast.dump(ast.parse(text, mode="eval"))
    # SLayer 1.4.1 scans raw formula text for OVER( even inside literals.
    # Encode only such string tokens; both Python AST and the native parser
    # still receive exactly the original value. No native validator is patched.
    tokens = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.STRING:
            value = ast.literal_eval(token.string)
            if re.search(r"\bover\s*\(", value, re.IGNORECASE):
                encoded = "'" + "".join("\\U%08x" % ord(c) for c in value) + "'"
                token = token._replace(string=encoded)
        tokens.append(token)
    text = tokenize.untokenize(tokens)
    if ast.dump(ast.parse(text, mode="eval")) != original:
        fail("E_INTERNAL", "Literalserialisierung hat den Ausdruck verändert.")
    parse_expr(text)
    return text


def sequence(items):
    return ast.List(elts=list(items), ctx=ast.Load())


def operation(op, left, right):
    return ast.BinOp(left=left, op=op(), right=right)


def shift(node, years):
    return call("time_shift", node, ast.Constant(-years), ast.Constant("year"))


def units(left, right, sign=-1):
    result = dict(left)
    for key, exponent in right:
        result[key] = result.get(key, 0) + exponent * sign
    return tuple(sorted((k, v) for k, v in result.items() if v))


def format_unit(unit):
    numerator = []
    denominator = []
    for name, exponent in unit:
        target = numerator if exponent > 0 else denominator
        power = abs(exponent)
        target.append(name + (f"^{power}" if power != 1 else ""))
    top = "*".join(numerator) or "1"
    bottom = "*".join(denominator)
    if len(denominator) > 1:
        bottom = "(" + bottom + ")"
    return top + "/" + bottom if denominator else top if numerator else "dimensionless"


def output_kind(expr, metrics):
    """Representation follows declared native types and public operators."""
    if isinstance(expr, AggregateNode):
        if expr.temporal_reduce == "mean_annual_totals":
            return "float"
        metric = metrics[expr.metric]
        if (metric.get("db_type") or "").upper().startswith("DECIMAL"):
            return "decimal"
        return "integer" if metric["type"] == "INT" else "float"
    if isinstance(expr, ConstantNode):
        return "integer" if type(expr.value) is int else "float"
    if isinstance(expr, PeriodNode):
        return (
            "float"
            if expr.op == "relative_change"
            else output_kind(expr.value, metrics)
        )
    if expr.op == "divide":
        return "float"
    kinds = (output_kind(expr.left, metrics), output_kind(expr.right, metrics))
    return (
        "decimal" if "decimal" in kinds else "float" if "float" in kinds else "integer"
    )


@dataclass(frozen=True)
class ExprInfo:
    unit: tuple
    grain: frozenset
    metrics: frozenset
    required_years: tuple
    is_constant: bool
    nature: str


@dataclass(frozen=True)
class ResultCheck:
    kind: str
    aliases: tuple = ()
    expected: int | None = None
    outputs: tuple = ()
    expressions: tuple = ()


@dataclass(frozen=True)
class CompiledExpression:
    node: ast.expr
    info: ExprInfo
    checks: tuple = ()


@dataclass(frozen=True)
class CompiledAnalysis:
    native_query: SlayerQuery
    output_manifest: tuple
    result_checks: tuple
    display_years: tuple
    native_years: tuple
    year_result_key: str | None
    remove_year: bool
    request: AnalysisRequest
    policy_notes: tuple
    dimension_keys: tuple = ()
    output_kinds: tuple = ()


@dataclass
class CompileContext:
    request: AnalysisRequest
    root: str
    grain: tuple
    years: tuple
    yearly: bool
    internal_year: bool
    measures: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


class SemanticCompiler:
    def __init__(self, catalog):
        self.catalog = catalog

    def _model_meta(self, model_id):
        return self.catalog.models[model_id].meta["analytics"]

    def _metric(self, metric_id):
        metric = self.catalog.metrics.get(metric_id)
        if metric is None:
            # Known unavailable model IDs cannot be bypassed with alternate suffixes.
            model_id = metric_id.split(".")[0]
            if model_id in self.catalog.models:
                self._available(model_id)
            fail("E_UNKNOWN_METRIC", "Unbekannte Kennzahl.")
        self._available(metric["model_id"])
        return metric

    def _available(self, model_id):
        status = self.catalog.quality["source_status"].get(model_id, {})
        if status.get("status", "ready") != "ready":
            reasons = status.get("status_reasons", status.get("reasons", []))
            fail(
                "E_MODEL_UNAVAILABLE",
                "Diese Quelle ist nicht freigegeben.",
                model_id=model_id,
                quality_code=(
                    reasons[0].get("code")
                    if reasons and isinstance(reasons[0], Mapping)
                    else status.get("quality_code", "UNAVAILABLE")
                ),
            )

    def _path(self, item, ctx):
        paths = item["native_paths"]
        if ctx.root not in paths:
            fail("E_INCOMPATIBLE_POPULATION", "Keine gemeinsame freigegebene Wurzel.")
        return native_ref(paths[ctx.root])

    def _dimension(self, dimension_id):
        if dimension_id not in self.catalog.dimensions:
            fail("E_UNKNOWN_DIMENSION", "Unbekannte Dimension.")
        return self.catalog.dimensions[dimension_id]

    def _validate_request(self, request):
        p = request.period
        if not 1900 <= p.from_year <= p.to_year <= 2100:
            fail("E_INVALID_REQUEST", "Ungültiger Jahresbereich.")
        if p.to_year - p.from_year >= 10:
            fail("E_QUERY_TOO_COMPLEX", "Höchstens zehn sichtbare Jahre.")
        if not 1 <= request.limit <= 1000:
            fail("E_INVALID_REQUEST", "Ungültiges Ergebnislimit.")
        if (
            not 1 <= len(request.outputs) <= config.MAX_OUTPUTS
            or len(request.group_by) > config.MAX_DIMENSIONS
        ):
            fail("E_QUERY_TOO_COMPLEX", "Output- oder Dimensionsbudget überschritten.")
        ids = [o.id for o in request.outputs]
        if len(set(ids)) != len(ids) or len(set(request.group_by)) != len(
            request.group_by
        ):
            fail("E_INVALID_REQUEST", "Doppelte IDs.")
        if any(
            not re.fullmatch("[a-z][a-z0-9_]{0,39}", x) or x in request.group_by
            for x in ids
        ):
            fail("E_INVALID_REQUEST", "Ungültige Output-ID.")
        if any(s.field not in ids + request.group_by for s in request.order_by):
            fail("E_INVALID_REQUEST", "Sortierfeld wird nicht ausgegeben.")
        count, predicates, periods, means = 0, len(request.filters), False, False

        def walk(expr, depth=1, in_period=False):
            nonlocal count, predicates, periods, means
            count += 1
            if depth > config.MAX_DEPTH or count > config.MAX_NODES:
                fail("E_QUERY_TOO_COMPLEX", "Ausdrucksbudget überschritten.")
            if isinstance(expr, AggregateNode):
                predicates += len(expr.where)
                means |= expr.temporal_reduce != "none"
                if in_period and expr.temporal_reduce != "none":
                    fail(
                        "E_UNSUPPORTED_TEMPORAL_COMPOSITION",
                        "Jahresmittel und Zeitvergleich sind nicht kombinierbar.",
                    )
            elif isinstance(expr, BinaryNode):
                if not 0 < expr.scale <= 1_000_000 or (
                    expr.op != "divide" and expr.scale != 1
                ):
                    fail("E_INVALID_REQUEST", "Ungültige Skalierung.")
                walk(expr.left, depth + 1, in_period)
                walk(expr.right, depth + 1, in_period)
            elif isinstance(expr, PeriodNode):
                periods = True
                if in_period:
                    fail(
                        "E_UNSUPPORTED_TEMPORAL_COMPOSITION",
                        "Verschachtelte Zeitoperatoren sind nicht freigegeben.",
                    )
                if expr.op == "fixed_year":
                    if (
                        expr.years is not None
                        or expr.year is None
                        or not 1900 <= expr.year <= 2100
                    ):
                        fail(
                            "E_INVALID_REQUEST",
                            "fixed_year benötigt genau ein Basisjahr.",
                        )
                    if p.from_year != p.to_year:
                        fail(
                            "E_UNSUPPORTED_FIXED_BASE_SERIES",
                            "Fixes Basisjahr nur bei einem sichtbaren Jahr.",
                        )
                elif (
                    expr.year is not None
                    or expr.years is None
                    or not 1 <= expr.years <= 10
                ):
                    fail(
                        "E_INVALID_REQUEST",
                        "Zeitvergleich benötigt ein bis zehn Jahre Abstand.",
                    )
                walk(expr.value, depth + 1, True)

        for output in request.outputs:
            walk(output.expr)
        if predicates > config.MAX_PREDICATES:
            fail("E_QUERY_TOO_COMPLEX", "Prädikatbudget überschritten.")
        if periods and means:
            fail(
                "E_UNSUPPORTED_TEMPORAL_COMPOSITION",
                "Jahresmittel und Zeitvergleich benötigen verschiedene Zeitebenen.",
            )
        if periods and "year" not in request.group_by and p.from_year != p.to_year:
            fail(
                "E_GRAIN_MISMATCH",
                "Zeitvergleich benötigt eine Jahresserie oder ein sichtbares Jahr.",
            )
        if means and "year" in request.group_by:
            fail(
                "E_UNSUPPORTED_TEMPORAL_COMPOSITION",
                "Jahresmittel gibt kein einzelnes Jahr aus.",
            )
        return periods

    def _predicate_ast(self, predicate, ctx, *, owner=None):
        d = self._dimension(predicate.field)
        if owner is None and (d["scope"] != "shared" or predicate.field == "year"):
            fail(
                "E_GLOBAL_FILTER_NOT_SHARED",
                "Globale Filter erlauben nur gemeinsame Raumdimensionen.",
            )
        if owner is not None and (d["scope"] != "fact" or d["owner"] != owner):
            fail(
                "E_CROSS_CLASSIFICATION_UNAVAILABLE",
                "Lokaler Filter gehört nicht zu diesem Fakt.",
            )
        n = len(predicate.values)
        op = predicate.op
        required = 0 if op in ("is_null", "not_null") else 2 if op == "between" else 1
        if (op in ("in", "not_in") and not 1 <= n <= 100) or (
            op not in ("in", "not_in") and n != required
        ):
            fail("E_INVALID_REQUEST", "Ungültige Anzahl Filterwerte.")
        expected = {
            "integer": int,
            "int": int,
            "string": str,
            "boolean": bool,
            "number": (int, float),
        }.get(d["value_type"])
        for v in predicate.values:
            if (
                v is None
                or expected is None
                or (
                    type(v) not in expected
                    if isinstance(expected, tuple)
                    else type(v) is not expected
                )
            ):
                fail("E_INVALID_REQUEST", "Filterwert hat nicht den Typ des Codes.")
            if isinstance(v, str) and len(v) > 256:
                fail("E_QUERY_TOO_COMPLEX", "Filterwert zu lang.")
        ref = self._path(d, ctx)
        if op == "between":
            if predicate.values[0] > predicate.values[1]:
                fail("E_INVALID_REQUEST", "Ungeordneter Wertebereich.")
            return ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Compare(
                        left=ref,
                        ops=[ast.GtE()],
                        comparators=[ast.Constant(predicate.values[0])],
                    ),
                    ast.Compare(
                        left=ref,
                        ops=[ast.LtE()],
                        comparators=[ast.Constant(predicate.values[1])],
                    ),
                ],
            )
        ops = {
            "eq": ast.Eq,
            "ne": ast.NotEq,
            "lt": ast.Lt,
            "le": ast.LtE,
            "gt": ast.Gt,
            "ge": ast.GtE,
            "in": ast.In,
            "not_in": ast.NotIn,
            "is_null": ast.Is,
            "not_null": ast.IsNot,
        }
        value = (
            ast.Constant(None)
            if n == 0
            else ast.Tuple(
                elts=[ast.Constant(v) for v in predicate.values], ctx=ast.Load()
            )
            if op in ("in", "not_in")
            else ast.Constant(predicate.values[0])
        )
        return ast.Compare(left=ref, ops=[ops[op]()], comparators=[value])

    def _grain_nodes(self, grain, ctx, *, annual=False):
        return [
            native_ref(("report_year",))
            if annual
            else call("year", native_ref(("period_start",)))
            if d == "year"
            else self._path(self._dimension(d), ctx)
            for d in grain
        ]

    def _compile_aggregate(self, expr, ctx, *, role):
        m = self._metric(expr.metric)
        meta = self._model_meta(m["model_id"])
        if meta["period_kind"] != "year":
            fail("E_UNSUPPORTED_PERIOD", "Quelle verwendet keine Jahresperioden.")
        grain = tuple(expr.grain) if expr.grain is not None else ctx.grain
        if len(set(grain)) != len(grain) or not set(grain) <= set(ctx.grain):
            fail("E_GRAIN_MISMATCH", "Blattgrain ist kein Teil des Ausgabegrains.")
        if ctx.internal_year and "year" not in grain:
            grain += ("year",)
        elif ctx.yearly and expr.grain is not None and "year" not in grain:
            fail("E_GRAIN_MISMATCH", "Explizites Jahresgrain muss year enthalten.")
        if set(grain) < set(ctx.grain) and role != "denominator":
            fail(
                "E_REFERENCE_ONLY_DENOMINATOR",
                "Gröberes Grain ist nur als Divisionsnenner zulässig.",
            )
        if any(d not in m["dimensions"] for d in grain):
            fail(
                "E_CROSS_CLASSIFICATION_UNAVAILABLE",
                "Kennzahl ist nach dieser Dimension nicht beobachtet.",
            )
        if expr.op not in m["allowed_aggregations"]:
            fail("E_AGGREGATION_NOT_ALLOWED", "Aggregation ist nicht freigegeben.")
        fixed = {
            p.field
            for p in expr.where + ctx.request.filters
            if p.op == "eq" or (p.op == "in" and len(p.values) == 1)
        }
        varying = set(m["dimensions"]) - set(grain) - fixed - {"year"}
        if expr.op == "sum" and varying - set(m["additive_over"]):
            fail(
                "E_NON_ADDITIVE_DIMENSION",
                "Summe über diese Dimension ist nicht freigegeben.",
            )
        mean = expr.temporal_reduce == "mean_annual_totals"
        if mean and expr.op != "sum":
            fail("E_AGGREGATION_NOT_ALLOWED", "Jahresmittel benötigt Jahressummen.")
        if (
            len(ctx.years) > 1
            and "year" not in grain
            and not mean
            and m["temporal_kind"] == "stock"
        ):
            fail(
                "E_TIME_AGGREGATION_NOT_ALLOWED",
                "Bestände verschiedener Jahre dürfen nicht summiert werden.",
            )
        if (
            len(ctx.years) > 1
            and "year" not in grain
            and not mean
            and "year" not in m["additive_over"]
        ):
            fail("E_TIME_AGGREGATION_NOT_ALLOWED", "Jahressumme ist nicht freigegeben.")
        value = self._path(m, ctx)
        predicates = [
            self._predicate_ast(p, ctx, owner=m["model_id"]) for p in expr.where
        ]
        if predicates:
            value = call(
                "iif",
                predicates[0]
                if len(predicates) == 1
                else ast.BoolOp(op=ast.And(), values=predicates),
                value,
                ast.Constant(None),
            )
        kwargs = {}
        if expr.grain is not None:
            kwargs["partition_by"] = sequence(self._grain_nodes(grain, ctx))
        checks = []
        if mean:
            annual = tuple(d for d in grain if d != "year") + ("year",)
            inner = call(
                expr.op,
                value,
                partition_by=sequence(
                    self._grain_nodes(annual, ctx, annual=False)[:-1]
                    + [native_ref(("report_year",))]
                ),
            )
            node = call("avg", inner)
            checks.append(
                ResultCheck(
                    "MISSING_YEAR_COVERAGE",
                    expected=len(ctx.years),
                    expressions=(call("count", inner),),
                )
            )
        else:
            node = call(expr.op, value, **kwargs)
        shared = tuple(
            d for d in grain if d == "year" or self._dimension(d)["scope"] == "shared"
        )
        partition = sequence(self._grain_nodes(shared, ctx))
        source_path = (
            () if m["model_id"] == ctx.root else tuple(m["native_paths"][ctx.root][:-1])
        )
        key = meta["cell_key"]
        root_meta = self._model_meta(ctx.root)
        checks.append(
            ResultCheck(
                "MISSING_SOURCE_COVERAGE",
                expressions=(
                    call(
                        "count_distinct",
                        native_ref(source_path + (key,)),
                        partition_by=partition,
                    ),
                    call(
                        "count_distinct",
                        native_ref((root_meta["cell_key"],)),
                        partition_by=partition,
                    ),
                ),
            )
        )
        return CompiledExpression(
            node,
            ExprInfo(
                ((m["unit"], 1),),
                frozenset(grain),
                frozenset((expr.metric,)),
                ctx.years,
                False,
                "aggregated",
            ),
            tuple(checks),
        )

    def _compile_binary(self, expr, ctx):
        if expr.op == "multiply" and (
            isinstance(expr.left, ConstantNode) == isinstance(expr.right, ConstantNode)
        ):
            fail(
                "E_UNSUPPORTED_PRODUCT",
                "Ein Produkt benötigt genau einen unmittelbaren konstanten Faktor.",
            )
        if expr.op == "divide":
            r = expr.right
            if not isinstance(r, (AggregateNode, ConstantNode)) and not (
                isinstance(r, PeriodNode)
                and r.op in ("shift", "fixed_year")
                and isinstance(r.value, AggregateNode)
            ):
                fail(
                    "E_UNSUPPORTED_DENOMINATOR", "Dieser Nenner ist nicht freigegeben."
                )
            if isinstance(r, ConstantNode) and r.value == 0:
                fail("E_ZERO_CONSTANT_DENOMINATOR", "Konstanter Nenner ist null.")
        a = self._compile_expr(expr.left, ctx, role="value")
        b = self._compile_expr(
            expr.right, ctx, role="denominator" if expr.op == "divide" else "value"
        )
        if expr.op in ("add", "subtract"):
            if a.info.unit != b.info.unit:
                fail(
                    "E_UNIT_MISMATCH",
                    "Addition und Subtraktion benötigen gleiche Einheiten.",
                )
            if a.info.grain != b.info.grain:
                fail(
                    "E_GRAIN_MISMATCH",
                    "Addition und Subtraktion benötigen gleiches Grain.",
                )
        if (
            expr.op == "divide"
            and not a.info.is_constant
            and not b.info.is_constant
            and not b.info.grain <= a.info.grain
        ):
            fail("E_GRAIN_MISMATCH", "Nennergrain ist nicht kompatibel.")
        unit = (
            units(a.info.unit, b.info.unit)
            if expr.op == "divide" and not b.info.is_constant
            else b.info.unit
            if a.info.is_constant
            else a.info.unit
        )
        checks = a.checks + b.checks
        if expr.op == "divide":
            node = operation(
                ast.Div,
                operation(ast.Mult, ast.Constant(expr.scale), a.node),
                call("nullif", b.node, ast.Constant(0)),
            )
            checks += (ResultCheck("DENOMINATOR", expressions=(b.node,)),)
        else:
            node = operation(
                {"add": ast.Add, "subtract": ast.Sub, "multiply": ast.Mult}[expr.op],
                a.node,
                b.node,
            )
        info = ExprInfo(
            unit,
            a.info.grain | b.info.grain,
            a.info.metrics | b.info.metrics,
            tuple(sorted(set(a.info.required_years + b.info.required_years))),
            a.info.is_constant and b.info.is_constant,
            "calculated",
        )
        return CompiledExpression(node, info, checks)

    def _compile_period(self, expr, ctx, *, role):
        value = self._compile_expr(expr.value, ctx, role=role)
        years = ctx.years[0] - expr.year if expr.op == "fixed_year" else expr.years
        previous = shift(value.node, years)
        shifted_checks = tuple(
            replace(c, expressions=tuple(shift(n, years) for n in c.expressions))
            for c in value.checks
        )
        checks = shifted_checks + (
            ResultCheck("MISSING_BASE_PERIOD", expressions=(previous,)),
        )
        if expr.op in ("shift", "fixed_year"):
            node = previous
        else:
            checks = value.checks + checks
            if expr.op == "absolute_change":
                node = operation(ast.Sub, value.node, previous)
            else:
                node = operation(
                    ast.Sub,
                    operation(
                        ast.Div, value.node, call("nullif", previous, ast.Constant(0))
                    ),
                    ast.Constant(1),
                )
                checks += (ResultCheck("DENOMINATOR", expressions=(previous,)),)
        required = tuple(
            sorted(
                set(ctx.years)
                | {y - years for y in ctx.years}
                | set(value.info.required_years)
            )
        )
        unit = () if expr.op == "relative_change" else value.info.unit
        return CompiledExpression(
            node,
            replace(
                value.info, unit=unit, required_years=required, nature="calculated"
            ),
            checks,
        )

    def _compile_expr(self, expr, ctx, *, role="value"):
        if isinstance(expr, AggregateNode):
            return self._compile_aggregate(expr, ctx, role=role)
        if isinstance(expr, BinaryNode):
            return self._compile_binary(expr, ctx)
        if isinstance(expr, PeriodNode):
            return self._compile_period(expr, ctx, role=role)
        return CompiledExpression(
            ast.Constant(expr.value),
            ExprInfo((), frozenset(), frozenset(), (), True, "calculated"),
        )

    def _add_check(self, kind, expressions, ctx, *, outputs, expected=None):
        key = (kind, expected, tuple(ast.dump(n) for n in expressions))
        if key in ctx.checks:
            old = ctx.checks[key]
            ctx.checks[key] = replace(
                old, outputs=tuple(sorted(set(old.outputs + outputs)))
            )
            return ctx.checks[key]
        if len(ctx.checks) >= config.MAX_CHECKS:
            fail("E_QUERY_TOO_COMPLEX", "Zu viele interne Prüfungen.")
        aliases = []
        for n in expressions:
            alias = "h" + str(
                sum(len(c.aliases) for c in ctx.checks.values()) + len(aliases)
            )
            aliases.append(alias)
            ctx.measures.append({"name": alias, "formula": render(n)})
        c = ResultCheck(kind, tuple(aliases), expected, outputs, expressions)
        ctx.checks[key] = c
        return c

    def compile(self, request):
        periods = self._validate_request(request)
        metrics = []
        leaves = []

        def collect(e):
            if isinstance(e, AggregateNode):
                metrics.append(self._metric(e.metric))
                leaves.append(e)
            elif isinstance(e, BinaryNode):
                collect(e.left)
                collect(e.right)
            elif isinstance(e, PeriodNode):
                collect(e.value)

        for o in request.outputs:
            collect(o.expr)
        if not metrics:
            fail("E_INVALID_REQUEST", "Ein Analyseoutput muss Daten verwenden.")
        metadata = [self._model_meta(m["model_id"]) for m in metrics]
        if (
            len({(m["domain"], m["root_model"], m["population"]) for m in metadata})
            != 1
        ):
            fail(
                "E_INCOMPATIBLE_POPULATION",
                "Quellen haben unvereinbare Grundgesamtheiten.",
            )
        years = tuple(range(request.period.from_year, request.period.to_year + 1))
        for metric in metrics:
            status = self.catalog.quality["source_status"][metric["model_id"]]
            if not set(years) <= set(status["available_years"]):
                fail(
                    "E_PERIOD_UNAVAILABLE",
                    "Mindestens ein sichtbares Jahr ist nicht vorhanden.",
                    model_id=metric["model_id"],
                )
        for d in request.group_by:
            self._dimension(d)
        internal = periods and "year" not in request.group_by
        ctx = CompileContext(
            request,
            metadata[0]["root_model"],
            tuple(request.group_by) + (("year",) if internal else ()),
            years,
            periods or "year" in request.group_by,
            internal,
        )
        filters = [render(self._predicate_ast(p, ctx)) for p in request.filters]
        manifests = []
        all_years = set(years)
        for i, output in enumerate(request.outputs):
            value = self._compile_expr(output.expr, ctx)
            if value.info.is_constant:
                fail(
                    "E_INVALID_REQUEST",
                    "Konstanten sind kein eigenständiges Analyseoutput.",
                )
            for check in value.checks:
                self._add_check(
                    check.kind,
                    check.expressions,
                    ctx,
                    outputs=(output.id,),
                    expected=check.expected,
                )
            ctx.measures.append({"name": "m" + str(i), "formula": render(value.node)})
            all_years.update(value.info.required_years)
            source_ids = sorted(
                {self.catalog.metrics[x]["model_id"] for x in value.info.metrics}
            )
            definitions = [
                self.catalog.metrics[x]["label"] for x in sorted(value.info.metrics)
            ]
            manifests.append(
                dict(
                    id=output.id,
                    label=("Berechnet: " if value.info.nature == "calculated" else "")
                    + " / ".join(definitions),
                    nature=value.info.nature,
                    unit=format_unit(value.info.unit),
                    scale=output.expr.scale
                    if isinstance(output.expr, BinaryNode)
                    else 1,
                    grain=list(request.group_by),
                    canonical_expression=render(value.node),
                    sources=source_ids,
                    reference_dates={
                        s: {
                            str(y): self._model_meta(s)
                            .get("reference_dates", {})
                            .get(str(y))
                            for y in value.info.required_years
                        }
                        for s in source_ids
                    },
                    format="percent"
                    if isinstance(output.expr, PeriodNode)
                    and output.expr.op == "relative_change"
                    else None,
                )
            )
        if (
            len(all_years - set(years)) > 10
            or max(all_years) - min(all_years) + 1 > len(years) + 10
            or len(ctx.measures) > config.MAX_MEASURES
        ):
            fail(
                "E_QUERY_TOO_COMPLEX",
                "Internes Jahres- oder Measurebudget überschritten.",
            )
        sources = sorted({m["model_id"] for m in metrics})
        stocks = [
            s for s in sources if self._model_meta(s).get("temporal_kind") == "stock"
        ]
        for source in stocks:
            for year in years:
                if (
                    self._model_meta(source).get("reference_dates", {}).get(str(year))
                    is None
                ):
                    ctx.notes.append(
                        dict(
                            code="SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN",
                            source=source,
                            message=f"Berichtsjahr {year}; konkreter Beobachtungsstichtag nicht dokumentiert.",
                        )
                    )
        if len(stocks) > 1:
            for y in years:
                dates = [
                    self._model_meta(s).get("reference_dates", {}).get(str(y))
                    for s in stocks
                ]
                if None in dates and request.period.require_same_reference_date:
                    fail(
                        "E_REFERENCE_DATE_UNKNOWN",
                        "Ein Bestandsstichtag ist unbekannt.",
                    )
                if (
                    None not in dates
                    and len(set(dates)) > 1
                    and request.period.require_same_reference_date
                ):
                    fail(
                        "E_REFERENCE_DATE_MISMATCH",
                        "Bestandsstichtage unterscheiden sich.",
                    )
                if None not in dates and len(set(dates)) > 1:
                    ctx.notes.append(
                        dict(
                            code="REFERENCE_DATE_MISMATCH",
                            message="Bestandsstichtage unterscheiden sich.",
                        )
                    )
        for m in metrics:
            if m["model_id"] == "vehicles":
                complete = set(
                    self.catalog.quality["source_status"]["vehicles"][
                        "complete_values"
                    ].get("vehicles.category", ())
                )
                selected = [e for e in leaves if e.metric == m["id"]]
                known = all(
                    e.where
                    and all(
                        p.field == "vehicles.category"
                        and p.op in ("eq", "in")
                        and set(p.values) <= complete
                        for p in e.where
                    )
                    for e in selected
                )
                if known and not set(request.group_by) & {
                    "vehicles.category",
                    "vehicles.group",
                }:
                    continue
                ctx.notes.append(
                    dict(
                        code="COVERAGE_UNKNOWN",
                        source="vehicles",
                        message="Summe vorhandener Beobachtungen; keine vollständige Gemeinde-Arten-Kreuztabelle.",
                    )
                )
            if m["temporal_kind"] == "flow" and stocks:
                ctx.notes.append(
                    dict(
                        code="FLOW_STOCK_RATIO",
                        source=m["model_id"],
                        message="Jahresfluss und Jahresbestand; nominale Geldwerte.",
                    )
                )
        dimensions = [
            render(self._path(self._dimension(d), ctx))
            for d in request.group_by
            if d != "year"
        ]
        query = dict(
            source_model=ctx.root,
            dimensions=dimensions,
            measures=ctx.measures,
            to_many_handling="error",
            limit=config.MAX_ROWS + 1,
        )
        if ctx.yearly:
            query["time_dimensions"] = [
                dict(
                    dimension="period_start",
                    granularity="year",
                    date_range=[f"{min(all_years)}-01-01", f"{max(all_years)}-12-31"],
                )
            ]
        else:
            filters += [
                render(
                    ast.Compare(
                        left=native_ref(("report_year",)),
                        ops=[ast.In()],
                        comparators=[
                            ast.Tuple(
                                elts=[ast.Constant(y) for y in years], ctx=ast.Load()
                            )
                        ],
                    )
                )
            ]
        query["filters"] = filters
        native = SlayerQuery.model_validate(query)
        return CompiledAnalysis(
            native,
            tuple(manifests),
            tuple(ctx.checks.values()),
            years,
            tuple(range(min(all_years), max(all_years) + 1)),
            ctx.root + ".period_start" if ctx.yearly else None,
            internal,
            request,
            tuple({json.dumps(n, sort_keys=True): n for n in ctx.notes}.values()),
            tuple(
                zip(
                    [d for d in request.group_by if d != "year"],
                    [ctx.root + "." + d for d in dimensions],
                )
            ),
            tuple(output_kind(o.expr, self.catalog.metrics) for o in request.outputs),
        )

    def check_native_response(self, compiled, response):
        if response.warnings:
            fail(
                "E_NATIVE_PLAN_UNSUPPORTED",
                "Der native Plan enthält nicht freigegebene Warnungen.",
            )
        if response.population != compiled.native_query.source_model:
            fail("E_NATIVE_PLAN_UNSUPPORTED", "Unerwartete native Population.")
        expected = (
            {
                compiled.native_query.source_model + ".m" + str(i)
                for i in range(len(compiled.output_manifest))
            }
            | {
                compiled.native_query.source_model + "." + a
                for c in compiled.result_checks
                for a in c.aliases
            }
            | {k for _, k in compiled.dimension_keys}
        )
        if compiled.year_result_key:
            expected.add(compiled.year_result_key)
        if expected != set(response.columns):
            fail("E_ENGINE_FAILURE", "Native Ergebnisspalten stimmen nicht überein.")

    def finalize(self, compiled, response):
        self.check_native_response(compiled, response)
        if len(response.data) > config.MAX_ROWS:
            fail("E_RESULT_TOO_LARGE", "Mehr als 10000 interne Ergebniszeilen.")
        rows = []
        statuses = []
        for raw in response.data:
            root_counts = [
                raw[compiled.native_query.source_model + "." + check.aliases[1]]
                for check in compiled.result_checks
                if check.kind == "MISSING_SOURCE_COVERAGE"
            ]
            if (
                not compiled.request.group_by
                and root_counts
                and all(value == 0 for value in root_counts)
            ):
                continue
            yr = None
            if compiled.year_result_key:
                v = raw[compiled.year_result_key]
                yr = v.year if isinstance(v, (date, datetime)) else int(str(v)[:4])
                if yr not in compiled.display_years:
                    continue
            row = {d: raw[k] for d, k in compiled.dimension_keys}
            if "year" in compiled.request.group_by:
                row["year"] = yr
            row_key = dict(row)
            problems = {}
            # Prefer an actual failed inner division, then the most specific
            # coverage cause. A wholly absent comparison period has neither a
            # source nor a root count; this is a missing base, not a source gap.
            priorities = {
                "ZERO_DENOMINATOR": 0,
                "MISSING_YEAR_COVERAGE": 1,
                "MISSING_SOURCE_COVERAGE": 2,
                "MISSING_BASE_PERIOD": 3,
                "MISSING_DENOMINATOR": 4,
            }
            problem_priorities = {}
            for check in compiled.result_checks:
                vals = [
                    raw[compiled.native_query.source_model + "." + a]
                    for a in check.aliases
                ]
                code = None
                if check.kind == "MISSING_SOURCE_COVERAGE":
                    if not all(value is None for value in vals) and (
                        vals[0] is None or vals[1] is None or vals[0] != vals[1]
                    ):
                        code = check.kind
                elif (
                    check.kind == "MISSING_YEAR_COVERAGE" and vals[0] != check.expected
                ):
                    code = check.kind
                elif check.kind == "DENOMINATOR":
                    if vals[0] == 0:
                        code = "ZERO_DENOMINATOR"
                    elif vals[0] is None:
                        code = "MISSING_DENOMINATOR"
                elif check.kind == "MISSING_BASE_PERIOD" and vals[0] is None:
                    code = check.kind
                if code:
                    for output in check.outputs:
                        if priorities[code] < problem_priorities.get(output, 99):
                            problems[output] = code
                            problem_priorities[output] = priorities[code]
            for i, output in enumerate(compiled.output_manifest):
                value = raw[compiled.native_query.source_model + ".m" + str(i)]
                if value is None:
                    problems.setdefault(output["id"], "NO_MATCHING_OBSERVATIONS")
                if output["id"] in problems:
                    value = None
                    statuses.append(
                        dict(
                            row_key=row_key,
                            output=output["id"],
                            code=problems[output["id"]],
                        )
                    )
                elif isinstance(value, (float, Decimal)) and not math.isfinite(value):
                    fail(
                        "E_ENGINE_FAILURE",
                        "Nicht endliches Ergebnis.",
                        quality_code="NON_FINITE_RESULT",
                    )
                if isinstance(value, Decimal):
                    value = (
                        format(value, ".2f")
                        if compiled.output_kinds[i] == "decimal"
                        else float(value)
                    )
                elif isinstance(value, (date, datetime)):
                    value = value.isoformat()
                row[output["id"]] = value
            rows.append(row)
        specs = list(compiled.request.order_by)
        kinds = dict(
            zip([o["id"] for o in compiled.output_manifest], compiled.output_kinds)
        )

        def compare(a, b):
            for key, desc in [(s.field, s.direction == "desc") for s in specs] + [
                (d, False) for d in compiled.request.group_by
            ]:
                av, bv = a[key], b[key]
                if av is None or bv is None:
                    delta = (av is None) - (bv is None)
                    if delta:
                        return delta
                    continue
                # Money is serialized only after its exact native calculation.
                if kinds.get(key) == "decimal":
                    av, bv = Decimal(av), Decimal(bv)
                delta = (av > bv) - (av < bv)
                if delta:
                    return -delta if desc else delta
            return 0

        rows.sort(key=cmp_to_key(compare))
        matched = len(rows)
        rows = rows[: compiled.request.limit]
        visible_keys = [{d: r[d] for d in compiled.request.group_by} for r in rows]
        statuses = [s for s in statuses if s["row_key"] in visible_keys]
        columns = []
        kinds = dict(
            zip([o["id"] for o in compiled.output_manifest], compiled.output_kinds)
        )
        for key in list(compiled.request.group_by) + [
            o["id"] for o in compiled.output_manifest
        ]:
            if key in kinds:
                kind = kinds[key]
            elif key == "year":
                kind = "integer"
            else:
                kind = {
                    "integer": "integer",
                    "string": "string",
                    "number": "float",
                    "boolean": "boolean",
                }[self.catalog.dimensions[key]["value_type"]]
            columns.append(
                dict(
                    id=key,
                    kind=kind,
                    nullable=not rows or any(r[key] is None for r in rows),
                )
            )
        notes = list(compiled.policy_notes)
        if not rows:
            notes.append(
                dict(code="NO_MATCHING_DATA", message="Keine passenden Daten.")
            )
        data = dict(
            rows=rows,
            columns=columns,
            outputs=list(compiled.output_manifest),
            notices=notes,
            cell_status=statuses,
            visible_period=dict(
                from_year=compiled.request.period.from_year,
                to_year=compiled.request.period.to_year,
            ),
            truncated=matched > len(rows),
            matched_rows=matched,
            provenance=dict(
                source_snapshots=[
                    dict(
                        source_id=self._model_meta(s)["source_id"],
                        sha256=self.catalog.sources[self._model_meta(s)["source_id"]][
                            "sha256"
                        ],
                    )
                    for s in sorted(
                        {s for o in compiled.output_manifest for s in o["sources"]}
                    )
                ],
                slayer_version="1.4.1",
                semantic_contract=config.SEMANTIC_CONTRACT,
            ),
        )
        if (
            len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
            > config.PUBLIC_BYTES
        ):
            fail("E_RESULT_TOO_LARGE", "Öffentliche Ergebnishülle ist zu gross.")
        return data
