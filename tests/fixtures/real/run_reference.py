"""Run independent direct-SQL oracles over the SHA-pinned real fixture files.

No SLayer dependency; uses DuckDB only. Does not download or modify source files.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

import duckdb

HERE = Path(__file__).resolve().parent


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    con = duckdb.connect()
    for source in manifest["sources"]:
        path = HERE / source["path"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise RuntimeError(f"Source snapshot changed: {source['alias']}")
        con.from_parquet(str(path)).create_view(source["alias"])
    script = (HERE / "reference_queries.sql").read_text()
    parts = re.split(r"^-- QUERY ([a-z0-9_]+)\s*$", script, flags=re.MULTILINE)
    output = {}
    directory = HERE / "expected"
    directory.mkdir(exist_ok=True)
    for i in range(1, len(parts), 2):
        name, sql = parts[i], parts[i+1].strip()
        query = con.execute(sql)
        columns = [d[0] for d in query.description]
        rows = [[json_value(v) for v in row] for row in query.fetchall()]
        output[name] = {"columns": columns, "rows": rows, "sql": sql}
        with (directory / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(columns)
            w.writerows(rows)
        print(json.dumps({"query": name, "rows": len(rows), "sample": rows[:2]}, ensure_ascii=False))
    result = {
        "reference_engine": "DuckDB",
        "reference_engine_version": duckdb.__version__,
        "reference_method": "independent explicit SQL on unchanged real Parquet snapshots, no SLayer execution",
        "float_absolute_tolerance": 1e-9,
        "money_representation": "decimal strings in CHF with two fractional digits",
        "source_sha256": {s["alias"]: s["sha256"] for s in manifest["sources"]},
        "vehicle_population_time_alignment": "arithmetic test only; strict same-snapshot comparison blocked because vehicle reference date is unspecified",
        "results": output,
    }
    (HERE / "expected_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
