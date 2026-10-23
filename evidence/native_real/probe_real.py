"""Native SLayer integration evidence on the unchanged real pilot tables.

This is a small probe harness, not a second normative model registry or an app.
Run: python probe_real.py [--data-dir ../slayer_detail_data]
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib.metadata as md
import json
import math
import os
from pathlib import Path
import warnings

os.environ["SLAYER_USAGE_REPORTING"] = "off"

from slayer.core.enums import DataType
from slayer.core.models import Column, DatasourceConfig, ModelJoin, SlayerModel
from slayer.engine.query_engine import SlayerQueryEngine
from slayer.storage.yaml_storage import YAMLStorage

HERE = Path(__file__).resolve().parent


def query(source, measures, dimensions=None, filters=None, **other):
    result = {"source_model": source, "measures": measures, "to_many_handling": "error"}
    if dimensions:
        result["dimensions"] = dimensions
        result["order"] = [{"column": column} for column in dimensions]
    if filters:
        result["filters"] = filters
    return result | other


def measure(name, formula):
    # Native SLayer forbids a measure alias that equals a source column.
    return {"name": "probe_" + name, "formula": formula}


def similar(actual, expected):
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(similar(a, b) for a, b in zip(actual, expected))
    if expected is None or actual is None:
        return actual is expected
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9)
    return actual == expected


async def main(data_dir):
    database = (data_dir / "normalized" / "pilot.duckdb").resolve()
    schema = json.loads(database.with_suffix(".schema.json").read_text())
    source_sha = hashlib.sha256(database.read_bytes()).hexdigest()
    assert source_sha == schema["sha256"]
    oracle = json.loads((data_dir / "expected_results.json").read_text())["results"]
    models_dir = HERE / "native_models"
    storage = YAMLStorage(base_dir=str(models_dir))
    await storage.save_datasource(DatasourceConfig(
        name="real_pilot", type="duckdb", database=str(database),
        connection_string=f"duckdb:///{database}?access_mode=READ_ONLY",
    ))
    selected = ("municipalities", "population", "vehicles", "years", "staff", "revenue")
    for name in selected:
        definition = schema["tables"][name]
        columns = []
        for field in definition["columns"]:
            physical = field["type"]
            datatype = DataType.DATE if physical == "DATE" else DataType.INT if "INT" in physical else DataType.DOUBLE if physical.startswith("DECIMAL") or physical == "DOUBLE" else DataType.TEXT
            columns.append(Column(name=field["name"], type=datatype,
                                  db_type=physical if physical.startswith("DECIMAL") else None,
                                  primary_key=field["name"] in definition["primary_key"],
                                  granularity="year" if field["name"] == "period_start" else None))
        joins = []
        if name == "population":
            joins.append(ModelJoin(target_model="municipalities", join_pairs=[[k, k] for k in ("geo_version", "municipality_id")], cardinality="many_to_one"))
        if name == "vehicles":
            joins.append(ModelJoin(target_model="population", join_pairs=[[k, k] for k in ("report_year", "geo_version", "municipality_id")], cardinality="many_to_one"))
        if name in ("staff", "revenue"):
            joins.append(ModelJoin(target_model="years", join_pairs=[["report_year", "report_year"]], cardinality="many_to_one"))
        await storage.save_model(SlayerModel(name=name, data_source="real_pilot", sql_table=name,
            columns=columns, joins=joins, default_time_dimension="period_start" if any(c.name == "period_start" for c in columns) else None))

    canton = oracle["canton_vehicle_ratios"]["rows"][0]
    municipality = oracle["population_vehicles_by_municipality"]["rows"]
    district = oracle["population_vehicles_by_district"]["rows"]
    av = oracle["staff_revenue_2024_2025"]["rows"]
    growth = oracle["nominal_growth_2025"]["rows"][0]
    category_literals = ast.unparse(ast.Tuple(elts=[ast.Constant(value=x) for x in ("01", "60")], ctx=ast.Load()))
    selected_sum = f"sum(iif(vehicles.vehicle_category_code in {category_literals}, vehicles.vehicles, None))"
    av_ratio = "sum(revenue.nominal_chf) / nullif(sum(staff.staff), 0)"
    time_kwargs = {"time_dimensions": [{"dimension": "period_start", "granularity": "year", "date_range": ["2024-01-01", "2025-12-31"]}], "order": [{"column": "period_start"}]}
    cases = [
        ("R01", "Population root: canton population and inverse vehicles", query("population", [measure("people", "sum(people)"), measure("vehicles", "sum(vehicles.vehicles)")], filters=["report_year == 2025"]), [[canton[0], canton[1]]], None),
        ("R02", "All 106 municipalities without fan-out", query("population", [measure("people", "sum(people)"), measure("vehicles", "sum(vehicles.vehicles)")], ["municipality_id"], ["report_year == 2025"]), [[r[0], r[3], r[4]] for r in municipality], None),
        ("R03", "All ten districts through municipality relation", query("population", [measure("people", "sum(people)"), measure("vehicles", "sum(vehicles.vehicles)")], ["municipalities.district_name"], ["report_year == 2025"]), [[r[0], r[1], r[2]] for r in district], None),
        ("R04", "Local 01+60 numerator, unchanged canton denominator", query("population", [measure("selected", selected_sum), measure("people", "sum(people)"), measure("per_1000", f"1000 * {selected_sum} / nullif(sum(people), 0)")], filters=["report_year == 2025"]), [[canton[3], canton[0], canton[5]]], None),
        ("R05", "Local 01+60 numerator for every municipality", query("population", [measure("selected", selected_sum), measure("people", "sum(people)"), measure("per_1000", f"1000 * {selected_sum} / nullif(sum(people), 0)")], ["municipality_id"], ["report_year == 2025"]), [[r[0], r[6], r[3], r[8]] for r in municipality], None),
        ("R06", "Explicit fixed canton denominator across all 42 vehicle categories", query("population", [measure("vehicles", "sum(vehicles.vehicles)"), measure("reference_people", "sum(people, partition_by=[])"), measure("per_1000", "1000 * sum(vehicles.vehicles) / nullif(sum(people, partition_by=[]), 0)")], ["vehicles.vehicle_category_code"], ["report_year == 2025"]), [[r[0], r[3], canton[0], 1000 * r[3] / canton[0]] for r in oracle["vehicles_by_category"]["rows"]], None),
        ("R07", "Years root: inverse staff and revenue at annual grain", query("years", [measure("staff", "sum(staff.staff)"), measure("revenue", "sum(revenue.nominal_chf)"), measure("per_person", av_ratio)], ["report_year"], ["report_year in (2024, 2025)"]), [[r[0], r[1], r[2], r[3]] for r in av], None),
        ("R08", "Mean of annual staff totals", query("years", [measure("mean_annual_staff", "avg(sum(staff.staff, partition_by=report_year))")], filters=["report_year in (2024, 2025)"]), [[oracle["staff_average_of_annual_totals_2024_2025"]["rows"][0][0]]], None),
        ("R09", "2025 revenue change with explicit 2024-2025 scan", query("years", [measure("current", "sum(revenue.nominal_chf)"), measure("previous", "time_shift(sum(revenue.nominal_chf), -1, 'year')"), measure("growth_pct", "(sum(revenue.nominal_chf) / nullif(time_shift(sum(revenue.nominal_chf), -1, 'year'), 0) - 1) * 100")], **time_kwargs), [[av[1][2], av[0][2], growth[0]]], "display_2025"),
        ("R10", "2025 revenue/person change with explicit 2024-2025 scan", query("years", [measure("current", av_ratio), measure("previous", f"time_shift({av_ratio}, -1, 'year')"), measure("growth_pct", f"(({av_ratio}) / nullif(time_shift({av_ratio}, -1, 'year'), 0) - 1) * 100")], **time_kwargs), [[av[1][3], av[0][3], growth[1]]], "display_2025"),
        ("R11", "Implicit revenue attribution to education rejected", query("years", [measure("revenue", "sum(revenue.nominal_chf)")], ["staff.education"], ["report_year == 2025"]), None, "unattributable"),
    ]
    results = []
    engine = SlayerQueryEngine(storage=storage)
    try:
        for case_id, title, body, expected, mode in cases:
            record = {"id": case_id, "title": title, "query": body, "expected": expected}
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    response = await asyncio.wait_for(engine.execute(body), timeout=25)
                output = response.model_dump(mode="json")
                actual = [list(row.values()) for row in output["data"]]
                if mode == "display_2025":
                    # Display cropping happens AFTER the native time_shift calculation.
                    actual = [row[1:] for row in actual if str(row[0]).startswith("2025-")]
                record.update(response=output, actual_compared=actual,
                              first_row_python_types={k: type(v).__name__ for k, v in (response.data[0] if response.data else {}).items()},
                              python_warnings=[str(w.message) for w in caught],
                              status="passed" if mode != "unattributable" and similar(actual, expected) else "different_result")
            except Exception as exc:
                record.update(error_type=type(exc).__name__, error=str(exc),
                              status="passed" if mode == "unattributable" and "unattributable" in str(exc) else "error")
            results.append(record)
            print(f"{case_id}: {record['status']} {title}", flush=True)
    finally:
        await engine.aclose()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == source_sha, "The real fixture database changed"
    payload = {
        "purpose": "Native integration evidence only; generated YAML is illustrative and not a second production registry.",
        "database_relative_to_data_dir": "normalized/pilot.duckdb", "database_sha256": source_sha,
        "raw_sources": schema["source_sha256"], "packages": {n: md.version(n) for n in ("motley-slayer", "duckdb", "duckdb-engine", "sqlglot", "sqlalchemy", "pydantic")},
        "connection_access_mode": "READ_ONLY", "unchanged_fixture_verified": True,
        "money_mapping": "SLayer DataType.DOUBLE is its numeric category; Column.db_type='DECIMAL(18,2)' preserves native exact aggregate values. JSON money amounts are tested as decimal strings; ratios remain floating point.",
        "local_filter_lowering": "ast.unparse of literal tuple; iif(predicate, value, None); no variables and no global fact/category predicates",
        "time_alignment_caveat": "Population/vehicle ratios are arithmetic period-alignment probes; vehicle observation date is still unspecified. No strict same-snapshot claim.",
        "execution_note": "Unmodified native SlayerQueryEngine.execute, with a 50ms event-loop wakeup callback in this probe harness only.",
        "probes": results,
    }
    (HERE / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    assert all(r["status"] == "passed" for r in results), "A native probe differed from the independent raw-source oracle"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=HERE.parents[1] / "tests" / "fixtures" / "real")
    args = parser.parse_args()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    def pulse():
        loop.call_later(0.05, pulse)
    loop.call_later(0.05, pulse)
    try:
        loop.run_until_complete(main(args.data_dir.resolve()))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
