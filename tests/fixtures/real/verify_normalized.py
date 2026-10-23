"""Check the physical fixture against independent unchanged-source SQL oracles."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import duckdb

from fixture_build import verify_source_hashes

HERE = Path(__file__).resolve().parent
DATABASE = HERE / "normalized" / "pilot.duckdb"

QUERIES = {
    "population_total": "SELECT count(*),sum(people),sum(women),sum(men),sum(age_65_plus) FROM population",
    "population_by_municipality": "SELECT p.municipality_id,m.municipality_name,m.district_name,p.people FROM population p JOIN municipalities m USING(geo_version,municipality_id) ORDER BY p.municipality_id",
    "population_by_district": "SELECT m.district_name,count(*),sum(p.people) FROM population p JOIN municipalities m USING(geo_version,municipality_id) GROUP BY m.district_name ORDER BY m.district_name",
    "vehicles_by_category": "SELECT vehicle_category_code,vehicle_category_name,count(*),sum(vehicles),sum(registrations) FROM vehicles GROUP BY vehicle_category_code,vehicle_category_name ORDER BY vehicle_category_code,vehicle_category_name",
    "vehicles_total": "SELECT count(*),count(DISTINCT municipality_id),sum(vehicles),sum(registrations),sum(vehicles) FILTER(WHERE vehicle_category_code='01'),sum(vehicles) FILTER(WHERE vehicle_category_code='60'),sum(vehicles) FILTER(WHERE vehicle_category_code IN('01','60')) FROM vehicles",
    "population_vehicles_by_municipality": """
        WITH v AS(SELECT report_year,geo_version,municipality_id,
            sum(vehicles) vehicles,sum(vehicles) FILTER(WHERE vehicle_category_code='01') cars,
            sum(vehicles) FILTER(WHERE vehicle_category_code IN('01','60')) selected
            FROM vehicles GROUP BY report_year,geo_version,municipality_id)
        SELECT p.municipality_id,m.municipality_name,m.district_name,p.people,v.vehicles,v.cars,v.selected,
               1000.0*v.cars/NULLIF(p.people,0),1000.0*v.selected/NULLIF(p.people,0)
        FROM population p JOIN municipalities m USING(geo_version,municipality_id)
        LEFT JOIN v USING(report_year,geo_version,municipality_id) ORDER BY p.municipality_id
    """,
    "population_vehicles_by_district": """
        WITH v AS(SELECT report_year,geo_version,municipality_id,
            sum(vehicles) vehicles,sum(vehicles) FILTER(WHERE vehicle_category_code='01') cars,
            sum(vehicles) FILTER(WHERE vehicle_category_code IN('01','60')) selected
            FROM vehicles GROUP BY report_year,geo_version,municipality_id)
        SELECT m.district_name,sum(p.people),sum(v.vehicles),sum(v.cars),sum(v.selected),
               1000.0*sum(v.cars)/NULLIF(sum(p.people),0),1000.0*sum(v.selected)/NULLIF(sum(p.people),0)
        FROM population p JOIN municipalities m USING(geo_version,municipality_id)
        LEFT JOIN v USING(report_year,geo_version,municipality_id)
        GROUP BY m.district_name ORDER BY m.district_name
    """,
    "staff_by_year": "SELECT report_year,sum(staff),count(*) FROM staff GROUP BY report_year ORDER BY report_year",
    "staff_revenue_by_year": "WITH s AS(SELECT report_year,sum(staff) people FROM staff GROUP BY report_year) SELECT s.report_year,s.people,r.nominal_chf,r.nominal_chf/NULLIF(s.people,0) FROM s LEFT JOIN revenue r USING(report_year) ORDER BY s.report_year",
    "staff_average_of_annual_totals_2024_2025": "WITH s AS(SELECT report_year,sum(staff) people FROM staff WHERE report_year IN(2024,2025) GROUP BY report_year) SELECT avg(people),count(*) FROM s",
    "staff_2025_by_education": "SELECT education,staff FROM staff WHERE report_year=2025 ORDER BY education",
    "ebau_by_quarter": "SELECT report_year,quarter(period_start),count(*),min(period_start),max(period_start),sum(submitted_dossiers),arg_max(municipalities_stock,period_start) FROM ebau GROUP BY report_year,quarter(period_start) ORDER BY report_year,quarter(period_start)",
    "heating_total": "SELECT report_year,sum(buildings),sum(heat_pump),100.0*sum(heat_pump)/NULLIF(sum(buildings),0) FROM heating GROUP BY report_year ORDER BY report_year",
}


def serial(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def main():
    verify_source_hashes()
    schema = json.loads(DATABASE.with_suffix(".schema.json").read_text())
    sha = hashlib.sha256(DATABASE.read_bytes()).hexdigest()
    assert sha == schema["sha256"], "Normalized database checksum differs from its schema manifest"
    expected = json.loads((HERE / "expected_results.json").read_text())
    checks = []
    invariants = []
    with duckdb.connect(str(DATABASE), read_only=True) as con:
        tables = con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()
        assert tables == [(name, "BASE TABLE") for name in sorted(schema["tables"])], tables
        for name, definition in schema["tables"].items():
            count = con.execute(f"SELECT count(*) FROM {name}").fetchall()[0][0]
            assert count == definition["row_count"], (name, count)
        assert con.execute("SELECT count(*) FROM vehicles WHERE reference_date IS NOT NULL").fetchall()[0][0] == 0
        assert con.execute("SELECT DISTINCT reference_date FROM population").fetchall() == [(date(2025, 12, 31),)]
        for name, violations in con.execute((HERE / "author_invariants.sql").read_text()).fetchall():
            assert violations == 0, (name, violations)
            invariants.append({"check_name": name, "violations": violations, "status": "passed"})
        for name, sql in QUERIES.items():
            actual = [[serial(v) for v in row] for row in con.execute(sql).fetchall()]
            oracle = expected["results"][name]["rows"]
            assert len(actual) == len(oracle), (name, "row count", len(actual), len(oracle))
            for index, (a, e) in enumerate(zip(actual, oracle)):
                assert len(a) == len(e), (name, index, "column count")
                for col, (av, ev) in enumerate(zip(a, e)):
                    equal = math.isclose(av, ev, rel_tol=0, abs_tol=1e-9) if isinstance(ev, float) and isinstance(av, (int, float)) else av == ev
                    assert equal, (name, index, col, av, ev)
            checks.append({"reference_query": name, "rows_compared": len(actual), "status": "passed"})
    output = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "database": DATABASE.name,
        "database_sha256": sha,
        "reference_engine_version": duckdb.__version__,
        "physical_tables_only": True,
        "raw_hashes_unchanged": True,
        "vehicle_observation_date_still_unknown": True,
        "checks": checks,
        "author_invariants": invariants,
        "note": "Verifies fixture preparation against raw-source SQL oracles; does not test SLayer or constitute approval of a strict-snapshot population/vehicle ratio.",
    }
    (HERE / "normalized" / "verification.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verified_queries": len(checks), "rows_compared": sum(c["rows_compared"] for c in checks), "author_invariants": len(invariants), "status": "passed"}))


if __name__ == "__main__":
    main()
