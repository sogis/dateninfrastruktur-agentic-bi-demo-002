"""Checked native models, source provenance and small public discovery views."""

from __future__ import annotations

import hashlib
import json
import keyword
from datetime import date
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Any

from .config import SEMANTIC_CONTRACT

import duckdb
import yaml
from slayer.core.models import DatasourceConfig, SlayerModel
from slayer.storage.yaml_storage import YAMLStorage
from sqlalchemy.engine import URL

from .contracts import AnalysisError


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def catalog_digest(
    models: Mapping[str, dict], sources: dict, schema: dict, quality: dict
) -> str:
    payload = dict(
        models=models,
        sources=sources,
        schema=schema,
        quality=quality,
        semantic_contract=SEMANTIC_CONTRACT,
    )
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


@dataclass(frozen=True)
class CatalogSnapshot:
    catalog_version: str
    bundle_dir: Path
    database_path: Path
    models: Mapping[str, SlayerModel]
    metrics: Mapping[str, dict]
    dimensions: Mapping[str, dict]
    roots: Mapping[str, dict]
    sources: Mapping[str, dict]
    quality: Mapping[str, Any]
    allowed_model_ids: tuple[str, ...]


def _read_models(models_dir: Path) -> tuple[dict, dict]:
    raw, models = {}, {}
    for path in sorted(models_dir.glob("*.yaml")):
        definition = yaml.safe_load(path.read_text())
        model = SlayerModel.model_validate(definition)
        if model.name in models or path.stem != model.name:
            raise ValueError("Duplicate or mismatched model identity")
        if (
            model.sql
            or model.source_queries
            or model.query_variables
            or model.sql_table != model.name
            or model.data_source != "pilot"
        ):
            raise ValueError("Only authored physical pilot models are allowed")
        if any(c.sql is not None and c.sql != c.name for c in model.columns):
            raise ValueError("Public metrics must refer to physical base columns")
        for name in (model.name, *(c.name for c in model.columns)):
            if not name.isidentifier() or keyword.iskeyword(name):
                raise ValueError("Unsafe native identifier")
        analytics = (model.meta or {}).get("analytics", {})
        required = {
            "source_id",
            "domain",
            "root_model",
            "population",
            "period_kind",
            "cell_key",
            "temporal_kind",
            "reference_dates",
            "coverage",
            "required",
            "label",
        }
        if not required <= analytics.keys():
            raise ValueError("Incomplete analytics metadata")
        if not all(
            isinstance(analytics[k], str)
            for k in required - {"required", "reference_dates"}
        ):
            raise ValueError("Invalid analytics metadata type")
        if type(analytics["required"]) is not bool or not isinstance(
            analytics["reference_dates"], dict
        ):
            raise ValueError("Invalid analytics metadata type")
        if analytics["period_kind"] not in ("year", "month") or analytics[
            "temporal_kind"
        ] not in ("stock", "flow"):
            raise ValueError("Invalid period metadata")
        if analytics["coverage"] != "unknown" or analytics.get(
            "status", "ready"
        ) not in ("ready", "quarantined", "unavailable"):
            raise ValueError("Invalid status or coverage metadata")
        for year, value in analytics["reference_dates"].items():
            if not isinstance(year, str) or len(year) != 4 or not year.isdigit():
                raise ValueError("Invalid reference year")
            if value is not None and (
                not isinstance(value, str)
                or date.fromisoformat(value).year != int(year)
            ):
                raise ValueError("Invalid reference date")
        if analytics["cell_key"] not in {c.name for c in model.columns}:
            raise ValueError("Missing physical cell key")
        raw[model.name], models[model.name] = definition, model
    if (
        not {"municipalities", "population", "vehicles", "years", "staff", "revenue"}
        <= models.keys()
    ):
        raise ValueError("Required model is missing")
    return raw, models


def _indexes(models: dict, sources: dict, quality: dict):
    roots, metrics, dimensions = {}, {}, {}
    graph = {name: [] for name in models}
    for name, model in models.items():
        a = model.meta["analytics"]
        if a["source_id"] not in sources:
            raise ValueError("Unknown source")
        root = a["root_model"]
        if root not in models:
            raise ValueError("Unknown root")
        if name == root:
            roots[name] = dict(
                model_id=name,
                domain=a["domain"],
                population=a["population"],
                cell_key=a["cell_key"],
                year_column="report_year",
                period_column="period_start",
            )
        columns = {c.name for c in model.columns}
        for join in model.joins:
            target = join.target_model
            if target not in models:
                raise ValueError("Unknown join target")
            if join.cardinality != "many_to_one":
                raise ValueError("Only explicit many-to-one edges are allowed")
            other = {c.name for c in models[target].columns}
            if any(
                left not in columns or right not in other
                for left, right in join.join_pairs
            ):
                raise ValueError("Unknown join column")
            graph[name].append((target, target))
            graph[target].append((name, name))
    paths = {}
    for root in roots:
        queue = deque([(root, (), frozenset({root}))])
        reached = {}
        while queue:
            name, path, visited = queue.popleft()
            if name in reached:
                raise ValueError("Ambiguous native join path")
            reached[name] = path
            for target, segment in graph[name]:
                if target not in visited:
                    queue.append((target, (*path, segment), visited | {target}))
        paths[root] = reached
    for name, model in models.items():
        ma = model.meta["analytics"]
        root = ma["root_model"]
        if name not in paths[root] and ma.get("status") not in (
            "quarantined",
            "unavailable",
        ):
            raise ValueError("Model has no path to its root")
        if (
            ma["domain"] != roots[root]["domain"]
            or ma["population"] != roots[root]["population"]
        ):
            raise ValueError("Incompatible root metadata")
        for col in model.columns:
            ca = (col.meta or {}).get("analytics", {})
            native_paths = {
                r: (*p[name], col.name) for r, p in paths.items() if name in p
            }
            if "metric_id" in ca:
                key = ca["metric_id"]
                if key in metrics or not key.startswith(name + "."):
                    raise ValueError("Duplicate or mismatched metric identity")
                if not all(
                    isinstance(ca.get(k), list)
                    and all(isinstance(x, str) for x in ca[k])
                    for k in ("dimensions", "additive_over", "allowed_aggregations")
                ):
                    raise ValueError("Invalid metric metadata")
                if not all(
                    isinstance(ca.get(k), str) and ca[k]
                    for k in ("metric_id", "unit", "temporal_kind")
                ):
                    raise ValueError("Invalid metric metadata type")
                if ca["temporal_kind"] not in ("stock", "flow") or not set(
                    ca["allowed_aggregations"]
                ) <= {"sum", "min", "max"}:
                    raise ValueError("Unsupported metric policy")
                if set(ca["additive_over"]) - set(ca["dimensions"]) or len(
                    ca["dimensions"]
                ) != len(set(ca["dimensions"])):
                    raise ValueError("Invalid additive dimensions")
                if ca["allowed_aggregations"] != col.allowed_aggregations:
                    raise ValueError("Native and analytics aggregation policy differ")
                metrics[key] = dict(
                    ca,
                    id=key,
                    model_id=name,
                    source_id=ma["source_id"],
                    column=col.name,
                    native_paths=native_paths,
                    label=col.label or key,
                    description=col.description or "",
                    root_model=root,
                    domain=ma["domain"],
                    population=ma["population"],
                    period_kind=ma["period_kind"],
                    db_type=col.db_type,
                    type=col.type.value,
                )
            if "dimension_id" in ca:
                key = ca["dimension_id"]
                if key in dimensions:
                    if key != "year":
                        raise ValueError("Duplicate dimension identity")
                    if (
                        ca.get("scope") != "shared"
                        or ca.get("owner") is not None
                        or ca.get("value_type") != "integer"
                        or col.name != "report_year"
                    ):
                        raise ValueError("Conflicting common year dimension")
                    dimensions[key]["native_paths"].update(native_paths)
                    continue
                if ca.get("scope") not in ("shared", "fact") or ca.get(
                    "value_type"
                ) not in ("string", "integer", "number", "boolean"):
                    raise ValueError("Invalid dimension metadata")
                if (
                    ca["scope"] == "fact"
                    and ca.get("owner") != name
                    or ca["scope"] == "shared"
                    and ca.get("owner") is not None
                ):
                    raise ValueError("Invalid dimension ownership")
                if ca.get("label_column") and ca["label_column"] not in {
                    c.name for c in model.columns
                }:
                    raise ValueError("Unknown label column")
                dimensions[key] = dict(
                    ca,
                    id=key,
                    model_id=name,
                    column=col.name,
                    native_paths=native_paths,
                    label=col.label or key,
                )
    for metric in metrics.values():
        if not set(metric["dimensions"]) <= dimensions.keys():
            raise ValueError("Unknown metric dimension")
    return metrics, dimensions, roots


def load_catalog(bundle_dir: Path) -> CatalogSnapshot:
    try:
        bundle_dir = bundle_dir.resolve()
        manifest = json.loads((bundle_dir / "bundle.json").read_text())
        if (
            manifest["manifest_version"] != 1
            or manifest["semantic_contract"] != SEMANTIC_CONTRACT
        ):
            raise ValueError("Unsupported bundle version")
        actual_files = {
            str(p.relative_to(bundle_dir))
            for p in bundle_dir.rglob("*")
            if p.is_file() and p != bundle_dir / "bundle.json"
        }
        if (
            set(manifest["files"]) != actual_files
            or not {"pilot.duckdb", "sources.json", "schema.json", "quality.json"}
            <= actual_files
        ):
            raise ValueError("Incomplete bundle checksum index")
        for relative, digest in manifest["files"].items():
            path = (bundle_dir / relative).resolve()
            if not path.is_relative_to(bundle_dir) or file_hash(path) != digest:
                raise ValueError("Bundle checksum mismatch")
        sources_doc = json.loads((bundle_dir / "sources.json").read_text())
        schema = json.loads((bundle_dir / "schema.json").read_text())
        quality = json.loads((bundle_dir / "quality.json").read_text())
        sources = {s["alias"]: s for s in sources_doc["sources"]}
        if len(sources) != len(sources_doc["sources"]) or any(
            s["path"] != f"raw/{alias}.parquet" for alias, s in sources.items()
        ):
            raise ValueError("Invalid fixed source paths")
        raw, models = _read_models(bundle_dir / "models")
        version = catalog_digest(raw, sources_doc, schema, quality)
        if version != manifest["catalog_version"] or manifest["bundle_id"] != version:
            raise ValueError("Bundle identity mismatch")
        metrics, dimensions, roots = _indexes(models, sources, quality)
        allowed = tuple(
            name
            for name in models
            if quality["source_status"][name]["status"] == "ready"
        )
        for name in allowed:
            physical = {c["name"] for c in schema["tables"][name]["columns"]}
            if not {c.name for c in models[name].columns} <= physical:
                raise ValueError("Missing model column")
        return CatalogSnapshot(
            version,
            bundle_dir,
            bundle_dir / "pilot.duckdb",
            _freeze(models),
            _freeze(metrics),
            _freeze(dimensions),
            _freeze(roots),
            _freeze(sources),
            _freeze(quality),
            allowed,
        )
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(
            "E_NOT_READY",
            "Das Datenbundle ist strukturell ungültig.",
            {"quality_code": "BUNDLE_INVALID", "exception_class": type(exc).__name__},
        ) from exc


async def make_storage(catalog: CatalogSnapshot, work_dir: Path) -> YAMLStorage:
    work_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = work_dir / "duckdb-tmp"
    temp_dir.mkdir(exist_ok=True)
    storage = YAMLStorage(base_dir=str(work_dir / "storage"))
    url = URL.create(
        "duckdb",
        database=str(catalog.database_path),
        query={
            "access_mode": "READ_ONLY",
            "threads": "1",
            "memory_limit": "256MB",
            "temp_directory": str(temp_dir),
            "enable_external_access": "false",
            "autoload_known_extensions": "false",
            "autoinstall_known_extensions": "false",
            "allow_unsigned_extensions": "false",
        },
    )
    await storage.save_datasource(
        DatasourceConfig(
            name="pilot",
            type="duckdb",
            database=str(catalog.database_path),
            connection_string=url.render_as_string(hide_password=False),
        )
    )
    # Targets precede their facts so native save-time edge validation sees its peers.
    pending = set(catalog.allowed_model_ids)
    while pending:
        ready = sorted(
            n
            for n in pending
            if all(j.target_model not in pending for j in catalog.models[n].joins)
        )
        if not ready:
            raise AnalysisError(
                "E_NOT_READY", "Zyklische Modellbeziehungen sind nicht freigegeben."
            )
        for name in ready:
            await storage.save_model(catalog.models[name])
            pending.remove(name)
    return storage


def check_data(catalog: CatalogSnapshot) -> dict:
    """Fixed physical-table checks shared by authoring and startup validation."""
    violations, warnings, statuses = [], [], {}
    sources = catalog.sources
    for alias, source in sources.items():
        path = catalog.bundle_dir / source["path"]
        if not path.is_file() or file_hash(path) != source["sha256"]:
            violations.append(
                dict(source_id=alias, code="SOURCE_HASH_MISMATCH", count=1)
            )
    config = {
        "threads": "1",
        "enable_external_access": "false",
        "autoload_known_extensions": "false",
        "autoinstall_known_extensions": "false",
        "allow_unsigned_extensions": "false",
    }
    with duckdb.connect(
        str(catalog.database_path), read_only=True, config=config
    ) as con:
        tables = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        if any(kind != "BASE TABLE" for kind in tables.values()):
            violations.append(
                dict(source_id="bundle", code="NON_PHYSICAL_TABLE", count=1)
            )
        for name, model in catalog.models.items():
            a = model.meta["analytics"]
            status = dict(
                status="ready",
                status_reasons=[],
                row_count=0,
                key_count=0,
                available_years=[],
                values={},
                complete_values={},
                coverage={},
            )
            if name == "population_sex_nationality":
                # Read the expressly retained evidence separately; the query datasource stays offline.
                source = catalog.bundle_dir / sources[a["source_id"]]["path"]
                with duckdb.connect() as evidence:
                    rows = evidence.execute(
                        "SELECT BFS_Nr,count(*) FROM read_parquet(?) GROUP BY BFS_Nr HAVING count(*)>1",
                        [str(source)],
                    ).fetchall()
                    status.update(
                        row_count=evidence.execute(
                            "SELECT count(*) FROM read_parquet(?)", [str(source)]
                        ).fetchall()[0][0],
                        key_count=evidence.execute(
                            "SELECT count(DISTINCT BFS_Nr) FROM read_parquet(?)",
                            [str(source)],
                        ).fetchall()[0][0],
                        available_years=[2025],
                    )
                if rows:
                    status.update(
                        status="quarantined",
                        status_reasons=[
                            dict(
                                code="DUPLICATE_KEY",
                                key=2525,
                                duplicate_rows=sum(r[1] for r in rows),
                            )
                        ],
                    )
                else:
                    status.update(
                        status="unavailable", status_reasons=[dict(code="NOT_RELEASED")]
                    )
                statuses[name] = status
                continue
            if name not in tables:
                status.update(
                    status="unavailable", status_reasons=[dict(code="MISSING_TABLE")]
                )
                violations.append(dict(source_id=name, code="MISSING_TABLE", count=1))
                statuses[name] = status
                continue
            actual = {r[0]: r[1] for r in con.execute(f'DESCRIBE "{name}"').fetchall()}
            keys = [c.name for c in model.columns if c.primary_key]
            errors = []
            for col in model.columns:
                if col.name not in actual:
                    errors.append(dict(code="MISSING_COLUMN", column=col.name, count=1))
                elif col.db_type and actual[col.name].replace(
                    " ", ""
                ) != col.db_type.replace(" ", ""):
                    errors.append(
                        dict(code="COLUMN_TYPE_MISMATCH", column=col.name, count=1)
                    )
                elif (
                    col.type.value == "INT"
                    and "INT" not in actual[col.name]
                    or col.type.value == "DATE"
                    and actual.get(col.name) != "DATE"
                    or col.type.value == "TEXT"
                    and actual.get(col.name) != "VARCHAR"
                ):
                    errors.append(
                        dict(code="COLUMN_TYPE_MISMATCH", column=col.name, count=1)
                    )
            if errors:
                status.update(status="unavailable", status_reasons=errors)
                violations.extend(dict(source_id=name, **e) for e in errors)
                statuses[name] = status
                continue
            count = con.execute(f'SELECT count(*) FROM "{name}"').fetchall()[0][0]
            keycols = ",".join(keys)
            distinct = con.execute(
                f'SELECT count(*) FROM (SELECT DISTINCT {keycols} FROM "{name}")'
            ).fetchall()[0][0]
            status.update(row_count=count, key_count=distinct)
            if count == 0:
                errors.append(dict(code="EMPTY_SOURCE", count=1))
            if count != distinct:
                errors.append(dict(code="DUPLICATE_KEY", count=count - distinct))
            nullkeys = con.execute(
                f'SELECT count(*) FROM "{name}" WHERE '
                + " OR ".join(k + " IS NULL" for k in keys)
            ).fetchall()[0][0]
            if nullkeys:
                errors.append(dict(code="NULL_KEY", count=nullkeys))
            for col in model.columns:
                if "metric_id" not in (col.meta or {}).get("analytics", {}):
                    continue
                bad = con.execute(
                    f'SELECT count(*) FROM "{name}" WHERE "{col.name}" IS NULL OR "{col.name}"<0'
                ).fetchall()[0][0]
                if bad:
                    errors.append(
                        dict(code="INVALID_REQUIRED_METRIC", column=col.name, count=bad)
                    )
            if "report_year" in actual:
                status["available_years"] = [
                    r[0]
                    for r in con.execute(
                        f'SELECT DISTINCT report_year FROM "{name}" ORDER BY 1'
                    ).fetchall()
                ]
            if "period_start" in actual and a["period_kind"] == "year":
                bad = con.execute(
                    f'SELECT count(*) FROM "{name}" WHERE period_start IS NULL OR period_start<>make_date(report_year,1,1)'
                ).fetchall()[0][0]
                if bad:
                    errors.append(dict(code="INVALID_ANNUAL_BUCKET", count=bad))
            if a["cell_key"] == "cell_id":
                bad = con.execute(
                    f"SELECT count(*) FROM \"{name}\" WHERE cell_id IS NULL OR cell_id<>concat(geo_version,'|',report_year,'|',municipality_id)"
                ).fetchall()[0][0]
                if bad:
                    errors.append(dict(code="INVALID_CELL_KEY", count=bad))
            for join in model.joins:
                condition = " AND ".join(
                    f'f."{left}"=p."{right}"' for left, right in join.join_pairs
                )
                bad = con.execute(
                    f'SELECT count(*) FROM "{name}" f WHERE NOT EXISTS(SELECT 1 FROM "{join.target_model}" p WHERE {condition})'
                ).fetchall()[0][0]
                if bad:
                    errors.append(
                        dict(code="ORPHAN_KEY", target=join.target_model, count=bad)
                    )
            if a.get("status") == "unavailable":
                status.update(
                    status="unavailable", status_reasons=[dict(code=a["status_reason"])]
                )
            for col in model.columns:
                da = (col.meta or {}).get("analytics", {})
                if "dimension_id" not in da:
                    continue
                label = da.get("label_column") or col.name
                invalid = con.execute(
                    f'SELECT count(*) FROM "{name}" WHERE "{col.name}" IS NULL OR "{label}" IS NULL'
                ).fetchall()[0][0]
                if invalid:
                    errors.append(
                        dict(
                            code="INVALID_DIMENSION_VALUE",
                            column=col.name,
                            count=invalid,
                        )
                    )
                conflicts = con.execute(
                    f'SELECT count(*) FROM (SELECT "{col.name}" FROM "{name}" GROUP BY "{col.name}" HAVING count(DISTINCT "{label}")>1)'
                ).fetchall()[0][0]
                if conflicts:
                    errors.append(
                        dict(
                            code="DIMENSION_LABEL_CONFLICT",
                            column=col.name,
                            count=conflicts,
                        )
                    )
                vals = con.execute(
                    f'SELECT DISTINCT "{col.name}","{label}" FROM "{name}" ORDER BY 1 LIMIT 201'
                ).fetchall()
                if len(vals) <= 200:
                    status["values"][da["dimension_id"]] = [
                        dict(code=r[0], label=str(r[1])) for r in vals
                    ]
            if name in ("vehicles", "heating", "building_category"):
                missing = con.execute(
                    f'SELECT count(*) FROM population p WHERE NOT EXISTS(SELECT 1 FROM "{name}" f WHERE f.report_year=p.report_year AND f.geo_version=p.geo_version AND f.municipality_id=p.municipality_id)'
                ).fetchall()[0][0]
                status["coverage"] = dict(
                    root_cells=con.execute(
                        "SELECT count(*) FROM population"
                    ).fetchall()[0][0],
                    missing_cells=missing,
                )
                if missing:
                    warnings.append(
                        dict(
                            source_id=name,
                            code="MISSING_SOURCE_COVERAGE",
                            count=missing,
                        )
                    )
                if name == "vehicles":
                    for column, dimension in (
                        ("vehicle_category_code", "vehicles.category"),
                        ("vehicle_group_code", "vehicles.group"),
                    ):
                        complete = con.execute(
                            f"SELECT {column} FROM vehicles GROUP BY {column} HAVING count(DISTINCT cell_id)=(SELECT count(DISTINCT cell_id) FROM population) ORDER BY 1"
                        ).fetchall()
                        status["complete_values"][dimension] = [r[0] for r in complete]
            if errors:
                status.update(
                    status="unavailable" if a["required"] else "quarantined",
                    status_reasons=errors,
                )
                violations.extend(dict(source_id=name, **e) for e in errors)
            statuses[name] = status
        fixed = {
            "population": [
                "people<>women+men OR people<>swiss_people+foreign_people OR people<>age_0_19+age_20_39+age_40_64+age_65_79+age_80_plus OR age_65_plus<>age_65_79+age_80_plus",
                "reference_date IS NULL OR reference_date<>DATE '2025-12-31'",
                "geo_version<>2025",
            ],
            "vehicles": ["reference_date IS NOT NULL", "geo_version<>2025"],
            "heating": [
                "buildings<>heat_pump+heating_oil+gas+wood+electricity+district_heating+other_or_unknown",
                "reference_date IS NULL OR reference_date<>make_date(report_year,12,31)",
                "geo_version<>2025",
            ],
            "building_category": [
                "buildings IS NULL OR buildings<0 OR buildings<>single_family+multi_family+residential_secondary_use+partially_residential",
                "reference_date IS NULL OR reference_date<>make_date(report_year,12,31)",
                "geo_version<>2025",
            ],
            "taxes": ["geo_version<>2026"],
        }
        for name, predicates in fixed.items():
            if (
                statuses.get(name, {}).get("status") not in ("ready", "unavailable")
                or name not in tables
            ):
                continue
            for predicate in predicates:
                bad = con.execute(
                    f'SELECT count(*) FROM "{name}" WHERE {predicate}'
                ).fetchall()[0][0]
                if bad:
                    entry = dict(
                        source_id=name,
                        code="IDENTITY_OR_REFERENCE_VIOLATION",
                        count=bad,
                    )
                    violations.append(entry)
                    statuses[name]["status"] = (
                        "unavailable"
                        if catalog.models[name].meta["analytics"]["required"]
                        else "quarantined"
                    )
                    statuses[name]["status_reasons"].append(
                        dict(code=entry["code"], count=bad)
                    )
        if {"heating", "building_category"} <= tables.keys():
            bad = con.execute(
                "SELECT count(*) FROM heating h JOIN building_category b USING(report_year,geo_version,municipality_id) WHERE h.buildings<>b.buildings"
            ).fetchall()[0][0]
            if bad:
                violations.append(
                    dict(
                        source_id="building_category",
                        code="BUILDING_TOTAL_MISMATCH",
                        count=bad,
                    )
                )
                statuses["building_category"].update(
                    status="quarantined",
                    status_reasons=[dict(code="BUILDING_TOTAL_MISMATCH", count=bad)],
                )
    ready = all(
        statuses[n]["status"] == "ready"
        for n, m in catalog.models.items()
        if m.meta["analytics"]["required"]
    )
    if any(
        v["code"] in ("SOURCE_HASH_MISMATCH", "NON_PHYSICAL_TABLE") for v in violations
    ):
        ready = False
    return dict(
        ready=ready,
        source_status=statuses,
        violations=violations,
        warnings=warnings,
        source_sha256={a: s["sha256"] for a, s in sources.items()},
    )


async def search_catalog(catalog, service, query: str, limit: int) -> dict:
    query = query.strip()
    if not 2 <= len(query) <= 300 or type(limit) is not int or not 1 <= limit <= 20:
        raise AnalysisError(
            "E_INVALID_REQUEST",
            "Suchtext oder Trefferlimit liegt ausserhalb der Grenzen.",
        )
    response = await service.search(question=query, max_results=limit + 1, compact=True)
    matches, seen = [], set()
    for hit in response.results:
        ids = [
            mid
            for mid, metric in catalog.metrics.items()
            if metric["model_id"] in catalog.allowed_model_ids
            and (
                hit.id == f"pilot.{metric['model_id']}.{metric['column']}"
                or hit.id == f"pilot.{metric['model_id']}"
                or (
                    hit.kind == "column"
                    and hit.id.startswith(f"pilot.{metric['model_id']}.")
                    and hit.id
                    not in {
                        f"pilot.{m['model_id']}.{m['column']}"
                        for m in catalog.metrics.values()
                    }
                )
            )
        ]
        for metric_id in ids:
            if metric_id in seen:
                continue
            seen.add(metric_id)
            metric = catalog.metrics[metric_id]
            status = catalog.quality["source_status"][metric["model_id"]]
            notes = (
                ["Konkreter Beobachtungsstichtag nicht dokumentiert."]
                if metric["model_id"] == "vehicles"
                else []
            )
            matches.append(
                dict(
                    model_id=metric["model_id"],
                    metric_id=metric_id,
                    label=metric["label"],
                    description=metric["description"],
                    unit=metric["unit"],
                    available_years=list(status["available_years"]),
                    dimensions=list(metric["dimensions"]),
                    status="ready",
                    notes=notes,
                )
            )
    return dict(matches=matches[:limit], truncated=len(matches) > limit)


async def describe_catalog(catalog, service, model_id: str) -> dict:
    if len(model_id) > 80 or model_id not in catalog.models:
        raise AnalysisError("E_UNKNOWN_MODEL", "Die Modell-ID ist nicht bekannt.")
    model = catalog.models[model_id]
    a = model.meta["analytics"]
    status = catalog.quality["source_status"][model_id]
    if status["status"] == "ready":
        # Native validation/discovery is used; only the reviewed projection below is public.
        await service.inspect(
            reference=f"pilot.{model_id}",
            entity_type="model",
            format="json",
            show_sql=False,
            num_rows=0,
        )
    metrics = []
    used_dims = set()
    for mid, m in catalog.metrics.items():
        if m["model_id"] != model_id:
            continue
        used_dims.update(m["dimensions"])
        metrics.append(
            dict(
                id=mid,
                label=m["label"],
                definition=m["description"],
                unit=m["unit"],
                temporal_kind=m["temporal_kind"],
                allowed_aggregations=list(m["allowed_aggregations"]),
                dimensions=list(m["dimensions"]),
                additive_over=list(m["additive_over"]),
            )
        )
    dims = [
        {k: _plain(d[k]) for k in ("id", "label", "value_type", "scope", "owner")}
        for key, d in catalog.dimensions.items()
        if key in used_dims
    ]
    values = {}
    for s in catalog.quality["source_status"].values():
        values.update(
            {k: _plain(v) for k, v in s.get("values", {}).items() if k in used_dims}
        )
    if "year" in used_dims:
        values["year"] = [dict(code=y, label=str(y)) for y in status["available_years"]]
    source = catalog.sources[a["source_id"]]
    rules = [
        "Nur tatsächlich beobachtete Merkmalsverteilungen verwenden.",
        "Unbekannte und fehlende Werte sind keine Nullbestände.",
    ]
    if a["temporal_kind"] == "stock":
        rules.append(
            "Bestände nicht über Jahre summieren; Durchschnitt von Jahrestotalen ist möglich."
        )
    if model_id == "vehicles":
        rules.append(
            "Fahrzeugarten nur lokal filtern; der konkrete Beobachtungsstichtag ist unbekannt."
        )
    return dict(
        model_id=model_id,
        label=a["label"],
        description=model.description,
        status=status["status"],
        status_reasons=_plain(status["status_reasons"]),
        domain=a["domain"],
        population=a["population"],
        period_kind=a["period_kind"],
        available_years=list(status["available_years"]),
        reference_dates={
            str(y): a["reference_dates"].get(str(y)) for y in status["available_years"]
        },
        metrics=metrics,
        dimensions=dims,
        values=values,
        coverage=dict(
            _plain(status.get("coverage", {})),
            complete_values=_plain(status.get("complete_values", {})),
            category_coverage="unknown",
        ),
        source={
            k: _plain(source.get(k))
            for k in (
                "source_url",
                "sha256",
                "retrieved_at_utc",
                "license_uri",
                "license_evidence",
                "temporal_coverage_as_published",
            )
        },
        examples=[
            dict(
                period=dict(from_year=2025, to_year=2025),
                outputs=[
                    dict(
                        id="value", expr=dict(kind="aggregate", metric=metrics[0]["id"])
                    )
                ],
            )
        ]
        if metrics and status["status"] == "ready"
        else [],
        rules=rules,
    )
