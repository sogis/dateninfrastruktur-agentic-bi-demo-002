"""Explicit offline preparation of a new, immutable pilot data bundle."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from . import config  # noqa: F401 — configure offline SLayer before native imports.

import duckdb

from .catalog import (
    CatalogSnapshot,
    _read_models,
    _indexes,
    _freeze,
    check_data,
    file_hash,
    catalog_digest,
    load_catalog,
    make_storage,
    SEMANTIC_CONTRACT,
)
from .contracts import AnalysisError

# Explicitly pinned original snapshot; derived test manifests are never a release input.
ORIGINAL_SHA256 = {
    "building_category": "9af9b8b2cb73f57730fcc1c4b4ae77eb68f3c05ca3f584da916da4ffd340245b",
    "ebau": "6fe91a3cde375356d08f15f8cfde363ddbe7436f5b8614da6c157bf6a029a132",
    "heating": "2df4fbe698b798639773865025736917e76984041bb83dc2e1ee8c43e501c3b6",
    "population_age": "72647f0811e9db892f1571275bc7adf6201aee30f18cac4fe64228175546c750",
    "population_sex_nationality": "26bb6a4452a0626a211a82b47a516ad45f894430204d37b01b0e80eb794da583",
    "revenue": "61039f6321eff0e0888157e2acba6eefc05bef6a941ee5822fd66c2b9d3e2328",
    "staff": "149d720c99993c838d8e02ecbb09f3986a144562fe7f836ee78361c53f8955aa",
    "taxes": "2434371697f848bccd55eecb1a7c037242a2a9ec77ef733b3d07be01d5b2d9bf",
    "vehicles": "0e09e311cb5e089f5533e52c3d27724a421f385f3c4b31a5f57129bbcba7fd08",
}

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
    "vehicles": [
        "report_year",
        "geo_version",
        "municipality_id",
        "vehicle_category_code",
    ],
    "staff": ["report_year", "education"],
    "revenue": ["report_year"],
    "heating": ["report_year", "geo_version", "municipality_id"],
    "building_category": ["report_year", "geo_version", "municipality_id"],
    "ebau": ["period_start"],
    "taxes": ["report_year", "geo_version", "municipality_id"],
    "years": ["report_year"],
}


def build_bundle(source_manifest: Path, models_dir: Path, output_dir: Path) -> dict:
    source_manifest, models_dir, output_dir = (
        source_manifest.resolve(),
        models_dir.resolve(),
        output_dir.resolve(),
    )
    if output_dir.exists():
        raise FileExistsError("Existing bundle directories are never overwritten")
    source_doc = json.loads(source_manifest.read_text())
    sources = {s["alias"]: s for s in source_doc["sources"]}
    expected = {
        "population_age",
        "population_sex_nationality",
        "vehicles",
        "staff",
        "revenue",
        "heating",
        "building_category",
        "taxes",
        "ebau",
    }
    if (
        source_doc.get("manifest_version") != 1
        or len(source_doc["sources"]) != 9
        or sources.keys() != expected
    ):
        raise AnalysisError(
            "E_NOT_READY",
            "Das feste Quellenmanifest ist unvollständig.",
            {"quality_code": "INVALID_SOURCE_MANIFEST"},
        )
    for alias, source in sources.items():
        if (
            source["sha256"] != ORIGINAL_SHA256[alias]
            or source["path"] != f"raw/{alias}.parquet"
        ):
            raise AnalysisError(
                "E_NOT_READY",
                "Abgeleitete Daten sind kein freigegebener Originalsnapshot.",
                {"quality_code": "SOURCE_HASH_MISMATCH", "source_id": alias},
            )
        path = (source_manifest.parent / source["path"]).resolve()
        if (
            not path.is_relative_to(source_manifest.parent)
            or file_hash(path) != source["sha256"]
        ):
            raise AnalysisError(
                "E_NOT_READY",
                "Originalprüfsumme stimmt nicht überein.",
                {"quality_code": "SOURCE_HASH_MISMATCH", "source_id": alias},
            )
    raw_models, models = _read_models(models_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".pilot-build-", dir=output_dir.parent))
    try:
        (staging / "models").mkdir()
        for path in sorted(models_dir.glob("*.yaml")):
            shutil.copyfile(path, staging / "models" / path.name)
        for source in sources.values():
            target = staging / source["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_manifest.parent / source["path"], target)
        # Remove machine-specific catalogue paths, retaining their provenance hashes.
        source_doc.pop("catalogue_path", None)
        source_doc.pop("metadata_path", None)
        (staging / "sources.json").write_text(
            json.dumps(source_doc, ensure_ascii=False, indent=2) + "\n"
        )
        schemas = {}
        database = staging / "pilot.duckdb"
        with duckdb.connect(str(database)) as con:
            for alias, source in sources.items():
                path = staging / source["path"]
                actual = con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
                ).fetchall()
                if [{"name": r[0], "type": r[1]} for r in actual] != source["columns"]:
                    raise AnalysisError(
                        "E_NOT_READY",
                        "Quellschema stimmt nicht überein.",
                        {"quality_code": "SOURCE_SCHEMA_MISMATCH", "source_id": alias},
                    )
                if (
                    con.execute(
                        "SELECT count(*) FROM read_parquet(?)", [str(path)]
                    ).fetchall()[0][0]
                    != source["row_count"]
                ):
                    raise AnalysisError(
                        "E_NOT_READY",
                        "Quellzeilenzahl stimmt nicht überein.",
                        {
                            "quality_code": "SOURCE_ROW_COUNT_MISMATCH",
                            "source_id": alias,
                        },
                    )
                con.from_parquet(str(path)).create_view("raw_" + alias)
            # Exact cents are required; an authored cast must not silently round a source.
            bad = con.execute(
                "SELECT count(*) FROM raw_revenue WHERE umsatz IS NULL OR umsatz<>CAST(umsatz AS DECIMAL(18,2))"
            ).fetchall()[0][0]
            if bad:
                raise AnalysisError(
                    "E_NOT_READY",
                    "Umsatz hat nicht verlustfrei normalisierbare Werte.",
                    {"quality_code": "MONEY_PRECISION_LOSS"},
                )
            bad = con.execute(
                "SELECT count(*) FROM (SELECT GDENR FROM raw_vehicles GROUP BY GDENR HAVING count(DISTINCT GDEBZNR)<>1)"
            ).fetchall()[0][0]
            if bad:
                raise AnalysisError(
                    "E_NOT_READY",
                    "Gemeinde hat keine eindeutige Bezirkzuordnung.",
                    {"quality_code": "DISTRICT_MAPPING_CONFLICT"},
                )
            for table, sql in NORMALIZATIONS.items():
                con.execute(f'CREATE TABLE "{table}" AS {sql}').fetchall()
                try:
                    con.execute(
                        f'ALTER TABLE "{table}" ADD PRIMARY KEY ({",".join(KEYS[table])})'
                    ).fetchall()
                except duckdb.ConstraintException as exc:
                    raise AnalysisError(
                        "E_NOT_READY",
                        "Ein erforderlicher Tabellenschlüssel ist nicht eindeutig.",
                        {"source_id": table, "quality_code": "DUPLICATE_KEY"},
                    ) from exc
                columns = con.execute(f'DESCRIBE "{table}"').fetchall()
                schemas[table] = dict(
                    row_count=con.execute(f'SELECT count(*) FROM "{table}"').fetchall()[
                        0
                    ][0],
                    primary_key=KEYS[table],
                    columns=[dict(name=r[0], type=r[1]) for r in columns],
                    derivation_sql=sql.strip(),
                )
            for alias in sources:
                con.execute("DROP VIEW raw_" + alias).fetchall()
            con.execute("CHECKPOINT").fetchall()
        schema = dict(
            database="pilot.duckdb",
            duckdb_version=duckdb.__version__,
            physical_tables_only=True,
            source_sha256={a: s["sha256"] for a, s in sources.items()},
            tables=schemas,
        )
        (staging / "schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        )
        metrics, dimensions, roots = _indexes(models, sources, {})
        candidate = CatalogSnapshot(
            "candidate",
            staging,
            database,
            _freeze(models),
            _freeze(metrics),
            _freeze(dimensions),
            _freeze(roots),
            _freeze(sources),
            _freeze({}),
            tuple(models),
        )
        quality = check_data(candidate)
        if not quality["ready"]:
            raise AnalysisError(
                "E_NOT_READY",
                "Qualitätsprüfung des Kernbundles fehlgeschlagen.",
                {"quality_code": "CORE_QUALITY_FAILED"},
            )
        (staging / "quality.json").write_text(
            json.dumps(quality, ensure_ascii=False, indent=2) + "\n"
        )
        version = catalog_digest(raw_models, source_doc, schema, quality)
        files = {
            str(p.relative_to(staging)): file_hash(p)
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        }
        bundle = dict(
            manifest_version=1,
            bundle_id=version,
            catalog_version=version,
            semantic_contract=SEMANTIC_CONTRACT,
            files=files,
        )
        (staging / "bundle.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
        )
        _verify_native_models(load_catalog(staging))
        staging.rename(output_dir)
        return dict(
            bundle_id=version,
            bundle_dir=str(output_dir),
            ready=True,
            source_status=quality["source_status"],
            source_sha256=quality["source_sha256"],
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _verify_native_models(catalog: CatalogSnapshot) -> None:
    # The synchronous authoring CLI owns this loop; runtime awaits make_storage directly.
    with tempfile.TemporaryDirectory(prefix="pilot-native-validation-") as directory:
        asyncio.run(make_storage(catalog, Path(directory)))


def verify_bundle(bundle_dir: Path) -> dict:
    catalog = load_catalog(bundle_dir)
    quality = check_data(catalog)
    _verify_native_models(catalog)
    if not quality["ready"]:
        raise AnalysisError(
            "E_NOT_READY",
            "Qualitätsprüfung des Kernbundles fehlgeschlagen.",
            {"quality_code": "CORE_QUALITY_FAILED"},
        )
    return dict(bundle_id=catalog.catalog_version, **quality)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--models", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            build_bundle(args.manifest, args.models, args.output)
            if args.operation == "build"
            else verify_bundle(args.bundle)
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except AnalysisError as exc:
        print(
            json.dumps(
                dict(
                    ok=False,
                    error=dict(code=exc.code, message=exc.message, details=exc.details),
                ),
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
