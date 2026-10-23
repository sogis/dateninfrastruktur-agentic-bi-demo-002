"""Create explicit negative fixtures by minimally mutating pinned real rows.

Raw source snapshots remain unchanged. These are test-only source overrides,
not corrected source data and not candidates for publication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import duckdb

from fixture_build import verify_source_hashes

HERE = Path(__file__).resolve().parent


def main():
    manifest = verify_source_hashes()
    sources = {s["alias"]: s for s in manifest["sources"]}
    target = HERE / "edgecases"
    target.mkdir(exist_ok=True)
    con = duckdb.connect()
    for alias in ("population_age", "vehicles"):
        con.from_parquet(str(HERE / sources[alias]["path"])).create_view(alias)
    municipality = con.execute("SELECT BFS_Nr,Gemeinde,Total FROM population_age ORDER BY BFS_Nr LIMIT 1").fetchall()[0]
    assert municipality == (2401, "Egerkingen", 4362), municipality
    counts = [r[0] for r in con.execute("DESCRIBE population_age").fetchall() if r[0] not in ("BFS_Nr", "Gemeinde", "Bezirk")]
    zero_select = ", ".join(f"CASE WHEN BFS_Nr=2401 THEN 0::BIGINT ELSE {name} END AS {name}" for name in counts)
    cases = [
        {
            "case_id": "missing_vehicle_municipality",
            "source_override": "vehicles",
            "mutation": "Remove every vehicle category row for BFS 2401 Egerkingen; other rows are byte-value identical.",
            "sql": "SELECT * FROM vehicles WHERE GDENR<>2401 ORDER BY GDENR,FZART_CD",
            "expected_gate": "Vehicle municipality coverage fails: BFS 2401 is missing. Do not substitute zero and issue an apparently complete canton ratio.",
        },
        {
            "case_id": "zero_population_denominator",
            "source_override": "population_age",
            "mutation": "Set all demographic counts in the one BFS 2401 Egerkingen row to zero, preserving its labels and every other row. This keeps row-level additive identities consistent.",
            "sql": f"SELECT BFS_Nr,Gemeinde,Bezirk,{zero_select} FROM population_age ORDER BY BFS_Nr",
            "expected_gate": "A vehicle/population ratio for BFS 2401 is undefined because the denominator is zero; report a distinct reason, never infinity or an invented zero ratio.",
        },
        {
            "case_id": "duplicate_population_key",
            "source_override": "population_age",
            "mutation": "Append an exact second copy of the actual BFS 2401 Egerkingen row.",
            "sql": "SELECT * FROM population_age UNION ALL SELECT * FROM population_age WHERE BFS_Nr=2401 ORDER BY BFS_Nr",
            "expected_gate": "Population key uniqueness fails before model activation. A source with duplicate report_year/geo_version/municipality_id may not be used as a denominator.",
        },
    ]
    output = []
    for item in cases:
        path = target / (item["case_id"] + ".parquet")
        if path.exists():
            path.unlink()  # Only derived fixtures are regenerated, never originals.
        con.sql(item["sql"]).write_parquet(str(path), compression="zstd")
        source = sources[item["source_override"]]
        result = {
            **item,
            "derived_test_data": True,
            "source_path": source["path"],
            "source_sha256": source["sha256"],
            "path": str(path.relative_to(HERE)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "original_row_count": source["row_count"],
            "derived_row_count": con.from_parquet(str(path)).count("*").fetchall()[0][0],
        }
        output.append(result)
    con.from_parquet(str(target / "missing_vehicle_municipality.parquet")).create_view("vehicles_missing")
    missing = con.execute("SELECT p.BFS_Nr,p.Gemeinde FROM population_age p LEFT JOIN (SELECT DISTINCT GDENR FROM vehicles_missing) v ON p.BFS_Nr=v.GDENR WHERE v.GDENR IS NULL ORDER BY p.BFS_Nr").fetchall()
    assert missing == [(2401, "Egerkingen")], missing
    removed = con.execute("SELECT count(*),sum(Anzahl),sum(Anzahl) FILTER(WHERE FZART_CD='01') FROM vehicles WHERE GDENR=2401").fetchall()[0]
    output[0]["observed_removed_rows"] = removed[0]
    output[0]["removed_vehicles"] = removed[1]
    output[0]["removed_passenger_cars"] = removed[2]
    output[0]["missing_municipality_ids"] = [2401]
    con.from_parquet(str(target / "zero_population_denominator.parquet")).create_view("population_zero")
    zero = con.execute("SELECT p.Total,1000.0*sum(v.Anzahl)/NULLIF(p.Total,0) FROM population_zero p JOIN vehicles v ON p.BFS_Nr=v.GDENR WHERE p.BFS_Nr=2401 AND v.FZART_CD='01' GROUP BY p.Total").fetchall()[0]
    assert zero == (0, None), zero
    output[1]["zero_denominator_municipality_ids"] = [2401]
    output[1]["sql_reference_ratio"] = None
    con.from_parquet(str(target / "duplicate_population_key.parquet")).create_view("population_duplicate")
    duplicate = con.execute("SELECT BFS_Nr,count(*) FROM population_duplicate GROUP BY BFS_Nr HAVING count(*)>1 ORDER BY BFS_Nr").fetchall()
    assert duplicate == [(2401, 2)], duplicate
    output[2]["duplicate_keys"] = [{"municipality_id": 2401, "row_count": 2}]
    value = {
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "purpose": "Deterministic test-only mutations derived from real source snapshots; not observations, corrections, or alternative published datasets.",
        "application": "For each case, override exactly the named raw source for a candidate preparation/validation test. All other inputs remain the original manifest-pinned files. The default fixture_build.py deliberately accepts only the unmodified manifest and does not load these variants.",
        "originals_unchanged": True,
        "cases": output,
    }
    (target / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    verify_source_hashes()
    print(json.dumps({"cases": [{"case_id": x["case_id"], "rows": x["derived_row_count"]} for x in output], "raw_checksums_still_match": True}))


if __name__ == "__main__":
    main()
