"""Build physical canonical tables from the immutable real fixture snapshots.

This prepares test fixtures. It is not a production catalogue importer.
All runtime tables are materialized; there are no runtime read_parquet views.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent

NORMALIZATIONS = {
    "municipalities": """
        SELECT 2025::INTEGER AS geo_version,p.BFS_Nr::INTEGER AS municipality_id,
               p.Gemeinde AS municipality_name,p.Bezirk AS district_name,
               v.GDEBZNR::INTEGER AS district_id
        FROM raw_population_age p
        JOIN (SELECT DISTINCT GDENR,GDEBZNR FROM raw_vehicles) v ON p.BFS_Nr=v.GDENR
        ORDER BY municipality_id
    """,
    "population": """
        SELECT 2025::INTEGER AS report_year,DATE '2025-01-01' AS period_start,
               DATE '2025-12-31' AS reference_date,2025::INTEGER AS geo_version,
               BFS_Nr::INTEGER AS municipality_id,concat(2025,'|',2025,'|',BFS_Nr) AS cell_id,Total AS people,
               Total_Weiblich AS women,Total_Maennlich AS men,
               Total_SchweizerInnen AS swiss_people,Total_AuslaenderInnen AS foreign_people,
               Alter_0_bis_19 AS age_0_19,Alter_20_bis_39 AS age_20_39,
               Alter_40_bis_64 AS age_40_64,Alter_65_bis_79 AS age_65_79,
               Alter_80_und_mehr AS age_80_plus,
               Alter_65_bis_79+Alter_80_und_mehr AS age_65_plus
        FROM raw_population_age ORDER BY municipality_id
    """,
    "vehicles": """
        SELECT 2025::INTEGER AS report_year,DATE '2025-01-01' AS period_start,
               NULL::DATE AS reference_date,2025::INTEGER AS geo_version,
               GDENR::INTEGER AS municipality_id,concat(2025,'|',2025,'|',GDENR) AS cell_id,FZART_CD AS vehicle_category_code,
               FZART_NA AS vehicle_category_name,FZ_GROUP AS vehicle_group_code,
               FZ_GROUP_NA AS vehicle_group_name,Anzahl AS vehicles,
               Anzahl_ohne_WS AS registrations
        FROM raw_vehicles ORDER BY municipality_id,vehicle_category_code
    """,
    "staff": """
        SELECT jahr::INTEGER AS report_year,make_date(jahr::INTEGER,1,1) AS period_start,
               ausbildung AS education,anzahl_mitarbeitende AS staff
        FROM raw_staff ORDER BY report_year,education
    """,
    "revenue": """
        SELECT jahr::INTEGER AS report_year,make_date(jahr::INTEGER,1,1) AS period_start,
               CAST(umsatz AS DECIMAL(18,2)) AS nominal_chf
        FROM raw_revenue ORDER BY report_year
    """,
    "heating": """
        SELECT jahr::INTEGER AS report_year,make_date(jahr::INTEGER,1,1) AS period_start,
               make_date(jahr::INTEGER,12,31) AS reference_date,jahr::INTEGER AS geo_version,
               bfs_gemeinde_nr::INTEGER AS municipality_id,concat(jahr,'|',jahr,'|',bfs_gemeinde_nr) AS cell_id,gebaeude_total AS buildings,
               geb_hz_waermepumpe AS heat_pump,geb_hz_heizoel AS heating_oil,
               geb_hz_gas AS gas,geb_hz_holz AS wood,geb_hz_elektrizitaet AS electricity,
               geb_hz_fernwaerme AS district_heating,geb_hz_andere_unbekannt AS other_or_unknown
        FROM raw_heating ORDER BY report_year,municipality_id
    """,
    "building_category": """
        SELECT jahr::INTEGER AS report_year,make_date(jahr::INTEGER,1,1) AS period_start,
               make_date(jahr::INTEGER,12,31) AS reference_date,jahr::INTEGER AS geo_version,
               bfs_gemeinde_nr::INTEGER AS municipality_id,concat(jahr,'|',jahr,'|',bfs_gemeinde_nr) AS cell_id,gebaeude_total AS buildings,
               geb_kat_efh AS single_family,geb_kat_mfh AS multi_family,
               geb_kat_wohn_nebennutzung AS residential_secondary_use,
               geb_kat_teilw_wohnnutzung AS partially_residential
        FROM raw_building_category ORDER BY report_year,municipality_id
    """,
    "ebau": """
        SELECT year(berichtsmonat)::INTEGER AS report_year,berichtsmonat AS period_start,
               anzahl_gemeinden_in_ebau AS municipalities_stock,
               anzahl_ueber_ebau_eingereichte_dossiers AS submitted_dossiers
        FROM raw_ebau ORDER BY period_start
    """,
    "taxes": """
        SELECT 2025::INTEGER AS report_year,DATE '2025-01-01' AS period_start,
               2026::INTEGER AS geo_version,gemeinde_bfs_nr::INTEGER AS municipality_id,
               concat(2026,'|',2025,'|',gemeinde_bfs_nr) AS cell_id,
               gemeinde AS municipality_name,staatssteuer_np_tchf AS natural_person_tax_tchf,
               staatssteuer_jp_tchf AS legal_person_tax_tchf,
               staatssteuer_total_tchf AS tax_total_tchf,
               CAST(staatssteuer_total_tchf * 1000 AS DECIMAL(18,2)) AS tax_total_chf
        FROM raw_taxes ORDER BY municipality_id
    """,
    "years": """
        SELECT DISTINCT report_year,make_date(report_year,1,1) AS period_start
        FROM (SELECT report_year FROM staff UNION SELECT report_year FROM revenue)
        ORDER BY report_year
    """,
}

KEYS = {
    "municipalities": ["geo_version", "municipality_id"],
    "population": ["report_year", "geo_version", "municipality_id"],
    "vehicles": ["report_year", "geo_version", "municipality_id", "vehicle_category_code"],
    "staff": ["report_year", "education"],
    "revenue": ["report_year"],
    "heating": ["report_year", "geo_version", "municipality_id"],
    "building_category": ["report_year", "geo_version", "municipality_id"],
    "ebau": ["period_start"],
    "taxes": ["report_year", "geo_version", "municipality_id"],
    "years": ["report_year"],
}


def verify_source_hashes():
    manifest = json.loads((HERE / "manifest.json").read_text())
    for source in manifest["sources"]:
        path = HERE / source["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise RuntimeError(f"Snapshot checksum mismatch: {source['alias']}")
    return manifest


def build(output: Path):
    manifest = verify_source_hashes()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Choose a new output path; refusing to overwrite {output}")
    schemas = {}
    with duckdb.connect(str(output)) as con:
        for source in manifest["sources"]:
            con.from_parquet(str(HERE / source["path"])).create_view("raw_" + source["alias"])
        source_error = con.execute("SELECT BFS_Nr, COUNT(*) n FROM raw_population_sex_nationality GROUP BY BFS_Nr HAVING n>1 ORDER BY BFS_Nr").fetchall()
        if source_error != [(2525, 3)]:
            raise RuntimeError("Expected real-source duplicate-key fixture has changed")
        if con.execute("SELECT count(*) FROM (SELECT GDENR,count(DISTINCT GDEBZNR) n FROM raw_vehicles GROUP BY GDENR HAVING n<>1)").fetchone()[0]:
            raise RuntimeError("Vehicle municipality/district mapping is inconsistent")
        for table, sql in NORMALIZATIONS.items():
            con.execute(f"CREATE TABLE {table} AS {sql}")
            con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({','.join(KEYS[table])})")
            columns = con.execute(f"DESCRIBE {table}").fetchall()
            schemas[table] = {
                "row_count": con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                "primary_key": KEYS[table],
                "columns": [{"name": r[0], "type": r[1]} for r in columns],
                "derivation_sql": sql.strip(),
            }
        if schemas["municipalities"]["row_count"] != 106:
            raise RuntimeError("Municipality coverage changed")
        for source in manifest["sources"]:
            con.execute("DROP VIEW raw_" + source["alias"])
        con.execute("CHECKPOINT")
    result = {
        "database": output.name,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "duckdb_version": duckdb.__version__,
        "physical_tables_only": True,
        "period_start_meaning": "Technical period key (annual rows: January 1); never infer observation date from it.",
        "vehicle_reference_date": None,
        "vehicle_report_year_evidence": "2025-01-01..2025-12-31 temporalCoverage in supplied DatasetIssue metadata",
        "population_reference_date_evidence": "2025-12-31 referenceDate in supplied DatasetIssue metadata",
        "geography_2025_binding": "Authored fixture binding to the complete 106-municipality key set matching the declared 2025 vehicle/GWS geography; does not infer geography from filename.",
        "excluded_from_runtime_tables": {"population_sex_nationality": "Real duplicate municipality key 2525; raw source retained as quarantine test."},
        "source_sha256": {s["alias"]: s["sha256"] for s in manifest["sources"]},
        "tables": schemas,
    }
    output.with_suffix(".schema.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"database": str(output), "tables": {k: v['row_count'] for k, v in schemas.items()}, "bytes": output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "normalized" / "pilot.duckdb")
    args = parser.parse_args()
    build(args.output)
