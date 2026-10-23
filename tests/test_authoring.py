"""Real authoring acceptance; mutations here are explicitly derived test data."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from slayer_app.author import build_bundle, verify_bundle, NORMALIZATIONS
from slayer_app.catalog import (
    check_data,
    describe_catalog,
    file_hash,
    load_catalog,
    make_storage,
    search_catalog,
)
from slayer_app.contracts import AnalysisError

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "tests" / "fixtures" / "real"


def test_real_hashes_schema_and_eighteen_baseline_invariants(bundle_dir, catalog):
    manifest = json.loads((REAL / "manifest.json").read_text())
    assert len(manifest["sources"]) == 9
    for source in manifest["sources"]:
        assert file_hash(REAL / source["path"]) == source["sha256"]
        assert file_hash(bundle_dir / source["path"]) == source["sha256"]
    verified = verify_bundle(bundle_dir)
    assert verified["ready"] is True
    assert verified["violations"] == []
    with duckdb.connect(str(catalog.database_path), read_only=True) as con:
        result = con.execute((REAL / "author_invariants.sql").read_text()).fetchall()
        assert len(result) == 18
        assert all(row[1] == 0 for row in result)
        assert (
            con.execute(
                "SELECT table_type FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            == [("BASE TABLE",)] * 10
        )
        assert con.execute(
            "SELECT typeof(nominal_chf) FROM revenue LIMIT 1"
        ).fetchall() == [("DECIMAL(18,2)",)]
    assert load_catalog(bundle_dir).catalog_version == catalog.catalog_version


def test_real_quarantine_and_measured_category_coverage(catalog):
    quality = check_data(catalog)
    assert quality["ready"] is True
    sex = quality["source_status"]["population_sex_nationality"]
    assert (sex["status"], sex["row_count"], sex["key_count"]) == (
        "quarantined",
        106,
        104,
    )
    assert sex["status_reasons"] == [
        dict(code="DUPLICATE_KEY", key=2525, duplicate_rows=3)
    ]
    assert "population_sex_nationality" not in catalog.allowed_model_ids
    vehicles = quality["source_status"]["vehicles"]
    assert vehicles["complete_values"]["vehicles.category"] == [
        "01",
        "30",
        "43",
        "60",
        "90",
    ]
    assert len(vehicles["values"]["vehicles.category"]) == 42
    assert vehicles["coverage"] == dict(root_cells=106, missing_cells=0)
    assert quality["source_status"]["staff"]["available_years"] == list(
        range(1980, 2026)
    )
    assert quality["source_status"]["revenue"]["available_years"] == list(
        range(1983, 2026)
    )
    assert (
        quality["source_status"]["taxes"]["status_reasons"][0]["code"]
        == "INCOMPATIBLE_GEOGRAPHY"
    )
    assert (
        quality["source_status"]["ebau"]["status_reasons"][0]["code"]
        == "UNSUPPORTED_PERIOD"
    )


def test_build_refuses_changed_original_and_existing_destination(tmp_path, bundle_dir):
    derived = tmp_path / "derived-hash-test"
    shutil.copytree(REAL / "raw", derived / "raw")
    shutil.copyfile(REAL / "manifest.json", derived / "manifest.json")
    original = derived / "raw" / "population_age.parquet"
    original.write_bytes(original.read_bytes() + b"derived test mutation")
    with pytest.raises(AnalysisError) as error:
        build_bundle(
            derived / "manifest.json", ROOT / "models", tmp_path / "must-not-exist"
        )
    assert error.value.details["quality_code"] == "SOURCE_HASH_MISMATCH"
    assert not (tmp_path / "must-not-exist").exists()
    manifest = json.loads((derived / "manifest.json").read_text())
    next(s for s in manifest["sources"] if s["alias"] == "population_age")["sha256"] = (
        file_hash(original)
    )
    (derived / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AnalysisError) as changed_manifest:
        build_bundle(
            derived / "manifest.json", ROOT / "models", tmp_path / "must-not-exist"
        )
    assert changed_manifest.value.details["quality_code"] == "SOURCE_HASH_MISMATCH"
    with pytest.raises(FileExistsError):
        build_bundle(REAL / "manifest.json", ROOT / "models", bundle_dir)


def test_bundle_tampering_prevents_readiness(tmp_path, bundle_dir):
    derived = tmp_path / "derived-corrupt-bundle"
    shutil.copytree(bundle_dir, derived)
    (derived / "models" / "population.yaml").write_text("name: changed\n")
    with pytest.raises(AnalysisError) as error:
        load_catalog(derived)
    assert error.value.code == "E_NOT_READY"


def test_M01_real_derived_duplicate_core_key(derived_catalog):
    path = REAL / "edgecases" / "duplicate_population_key.parquet"
    with duckdb.connect(str(derived_catalog.database_path)) as con:
        con.from_parquet(str(path)).create_view("raw_population_age")
        con.execute(
            "CREATE TABLE derived_population AS " + NORMALIZATIONS["population"]
        ).fetchall()
        con.execute("DROP TABLE population").fetchall()
        con.execute("ALTER TABLE derived_population RENAME TO population").fetchall()
        con.execute("DROP VIEW raw_population_age").fetchall()
    quality = check_data(derived_catalog)
    assert quality["ready"] is False
    assert quality["source_status"]["population"]["row_count"] == 107
    assert any(
        v["source_id"] == "population" and v["code"] == "DUPLICATE_KEY"
        for v in quality["violations"]
    )


def test_M03_real_derived_missing_vehicle_municipality(derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as con:
        con.execute("DELETE FROM vehicles WHERE municipality_id=2401").fetchall()
    quality = check_data(derived_catalog)
    assert quality["ready"] is True  # A measured gap remains guarded at result release.
    assert quality["source_status"]["vehicles"]["row_count"] == 2597
    assert quality["source_status"]["vehicles"]["coverage"]["missing_cells"] == 1
    assert (
        dict(source_id="vehicles", code="MISSING_SOURCE_COVERAGE", count=1)
        in quality["warnings"]
    )


def test_required_null_metric_is_a_hard_failure(derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as con:
        con.execute(
            "UPDATE vehicles SET registrations=NULL WHERE municipality_id=2401 AND vehicle_category_code='01'"
        ).fetchall()
    quality = check_data(derived_catalog)
    assert quality["ready"] is False
    assert any(
        v["code"] == "INVALID_REQUIRED_METRIC" and v["column"] == "registrations"
        for v in quality["violations"]
    )


def test_B13_native_datasource_read_only_offline_and_private_models(catalog, tmp_path):
    from slayer.sql.engine_factory import get_engine, reset_cache

    before = {
        str(p): file_hash(p) for p in catalog.bundle_dir.rglob("*") if p.is_file()
    }
    storage = asyncio.run(make_storage(catalog, tmp_path / "private-work"))
    datasource = asyncio.run(storage.get_datasource("pilot"))
    engine = get_engine(datasource)
    try:
        with engine.connect() as conn:
            settings = conn.exec_driver_sql(
                "SELECT current_setting('enable_external_access'),current_setting('autoinstall_known_extensions'),current_setting('autoload_known_extensions'),current_setting('threads')"
            ).fetchall()
            assert settings == [(False, False, False, 1)]
            assert conn.exec_driver_sql(
                "SELECT sum(people) FROM population"
            ).fetchall() == [(293081,)]
            with pytest.raises(Exception):
                conn.exec_driver_sql("CREATE TABLE forbidden(value INTEGER)").fetchall()
    finally:
        reset_cache()
    assert before == {
        str(p): file_hash(p) for p in catalog.bundle_dir.rglob("*") if p.is_file()
    }
    assert (
        tmp_path / "private-work" / "storage" / "models" / "pilot" / "population.yaml"
    ).exists()
    assert not (
        tmp_path
        / "private-work"
        / "storage"
        / "models"
        / "pilot"
        / "population_sex_nationality.yaml"
    ).exists()


def test_native_discovery_safe_projection(catalog, tmp_path):
    from slayer.search.service import SearchService
    from slayer.search.retrievers import BM25Retriever, TantivyRetriever
    from slayer.inspect.service import InspectService

    async def run():
        storage = await make_storage(catalog, tmp_path / "discovery")
        search = SearchService(
            storage=storage,
            engine=None,
            retrievers=[BM25Retriever(), TantivyRetriever()],
        )
        inspection = InspectService(storage=storage, engine=None)
        result = await search_catalog(catalog, search, "Fahrzeugbestand", 10)
        assert any(hit["metric_id"] == "vehicles.count" for hit in result["matches"])
        assert all(hit["status"] == "ready" for hit in result["matches"])
        assert (await search_catalog(catalog, search, "unfindablezxqv", 10))[
            "matches"
        ] == []
        vehicles = await describe_catalog(catalog, inspection, "vehicles")
        assert vehicles["reference_dates"] == {"2025": None}
        assert vehicles["values"]["vehicles.category"][0] == dict(
            code="01", label="Personenwagen"
        )
        assert "sql_table" not in json.dumps(vehicles)
        sex = await describe_catalog(catalog, inspection, "population_sex_nationality")
        assert sex["status"] == "quarantined"
        assert sex["status_reasons"][0]["code"] == "DUPLICATE_KEY"

    asyncio.run(run())


def test_catalog_identity_stable_across_fresh_builds_and_discovery(
    bundle_dir, tmp_path
):
    # The DuckDB binary checksum may vary; the logical catalogue identity must not.
    first = load_catalog(bundle_dir)
    second_path = tmp_path / "independent-build"
    build_bundle(REAL / "manifest.json", ROOT / "models", second_path)
    second = load_catalog(second_path)
    assert first.catalog_version == second.catalog_version
    assert (
        first.quality["source_status"]["population_sex_nationality"]["status"]
        == "quarantined"
    )
    assert all(
        first.quality["source_status"][n]["status"] == "ready"
        for n in first.allowed_model_ids
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("unsafe_identifier", "Unsafe native identifier"),
        ("missing_join_key", "join_pairs"),
        ("duplicate_metric", "metric identity"),
        ("ambiguous_path", "Ambiguous native join path"),
        ("bad_dimension_owner", "dimension ownership"),
        ("invalid_metadata_type", "metric metadata type"),
    ],
)
def test_author_rejects_invalid_metadata_and_native_paths(tmp_path, mutation, reason):
    import yaml
    from slayer_app.catalog import _read_models, _indexes

    models_path = tmp_path / "derived-invalid-models"
    shutil.copytree(ROOT / "models", models_path)
    path = models_path / "vehicles.yaml"
    model = yaml.safe_load(path.read_text())
    metric = next(c for c in model["columns"] if c["name"] == "vehicles")
    if mutation == "unsafe_identifier":
        model["name"] = "unsafe-name"
        path.rename(models_path / "unsafe-name.yaml")
        path = models_path / "unsafe-name.yaml"
    elif mutation == "missing_join_key":
        model["joins"][0]["join_pairs"][0][0] = "missing_physical_column"
    elif mutation == "duplicate_metric":
        next(c for c in model["columns"] if c["name"] == "registrations")["meta"][
            "analytics"
        ]["metric_id"] = "vehicles.count"
    elif mutation == "ambiguous_path":
        model["joins"].append(
            dict(
                target_model="municipalities",
                join_pairs=[
                    ["geo_version", "geo_version"],
                    ["municipality_id", "municipality_id"],
                ],
                cardinality="many_to_one",
            )
        )
    elif mutation == "bad_dimension_owner":
        next(c for c in model["columns"] if c["name"] == "vehicle_category_code")[
            "meta"
        ]["analytics"]["owner"] = "population"
    elif mutation == "invalid_metadata_type":
        metric["meta"]["analytics"]["unit"] = 12
    path.write_text(yaml.safe_dump(model, allow_unicode=True, sort_keys=False))
    with pytest.raises(ValueError):
        _, models = _read_models(models_path)
        manifest = json.loads((REAL / "manifest.json").read_text())
        _indexes(models, {s["alias"]: s for s in manifest["sources"]}, {})


def test_author_checks_nonpublic_building_control_total(derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as con:
        con.execute(
            "UPDATE building_category SET buildings=NULL WHERE municipality_id=2401"
        ).fetchall()
    quality = check_data(derived_catalog)
    assert quality["ready"] is True
    assert quality["source_status"]["building_category"]["status"] == "quarantined"
    assert any(v["source_id"] == "building_category" for v in quality["violations"])


def test_shared_dimension_codes_labels_and_paths_are_complete(catalog):
    municipalities = catalog.quality["source_status"]["municipalities"]["values"]
    assert len(municipalities["municipality"]) == 106
    assert len(municipalities["district"]) == 10
    for dimension in ("municipality", "district", "year"):
        assert catalog.dimensions[dimension]["scope"] == "shared"
        assert catalog.dimensions[dimension]["owner"] is None
        assert catalog.dimensions[dimension]["value_type"] == "integer"
    assert set(catalog.dimensions["year"]["native_paths"]) == {"population", "years"}
    assert catalog.dimensions["vehicles.category"]["native_paths"]["population"] == (
        "vehicles",
        "vehicle_category_code",
    )
    assert catalog.metrics["revenue.nominal_chf"]["db_type"] == "DECIMAL(18,2)"


def test_settings_boundaries_secret_and_resolved_work_path(tmp_path, monkeypatch):
    from slayer_app.config import load_settings

    for key in tuple(__import__("os").environ):
        if key.startswith("SLAYER_APP_"):
            monkeypatch.delenv(key)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setenv("SLAYER_APP_BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SLAYER_APP_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("SLAYER_APP_GATEWAY_BEARER_TOKEN", "secret-marker-for-repr")
    monkeypatch.setenv("SLAYER_APP_ALLOWED_HOSTS", " localhost:* , 127.0.0.1:* ")
    settings = load_settings()
    assert settings.host == "127.0.0.1"
    assert settings.allowed_hosts == ("localhost:*", "127.0.0.1:*")
    assert settings.work_dir.is_dir()
    assert "secret-marker-for-repr" not in repr(settings)
    monkeypatch.setenv("SLAYER_APP_WORK_DIR", str(bundle / "work"))
    with pytest.raises(ValueError):
        load_settings()
    alias = tmp_path / "bundle-symlink"
    alias.symlink_to(bundle, target_is_directory=True)
    monkeypatch.setenv("SLAYER_APP_WORK_DIR", str(alias / "work"))
    with pytest.raises(ValueError):
        load_settings()
    assert not (bundle / "work").exists()


@pytest.mark.parametrize(
    "variable,value",
    [
        ("QUERY_TIMEOUT_SECONDS", "0.99"),
        ("QUERY_TIMEOUT_SECONDS", "60.01"),
        ("QUERY_TIMEOUT_SECONDS", "nan"),
        ("QUERY_TIMEOUT_SECONDS", "inf"),
        ("STARTUP_TIMEOUT_SECONDS", "0"),
        ("STARTUP_TIMEOUT_SECONDS", "121"),
        ("PORT", "0"),
        ("PORT", "65536"),
        ("ALLOWED_HOSTS", ""),
        ("ALLOWED_ORIGINS", " , "),
        ("GATEWAY_BEARER_TOKEN", " "),
    ],
)
def test_invalid_operator_settings_fail_before_creating_work(
    tmp_path, monkeypatch, variable, value
):
    from slayer_app.config import load_settings

    for key in tuple(__import__("os").environ):
        if key.startswith("SLAYER_APP_"):
            monkeypatch.delenv(key)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setenv("SLAYER_APP_BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SLAYER_APP_WORK_DIR", str(tmp_path / "uncreated-work"))
    monkeypatch.setenv("SLAYER_APP_" + variable, value)
    with pytest.raises(ValueError):
        load_settings()
    assert not (tmp_path / "uncreated-work").exists()


def test_envelopes_and_worker_jobs_reject_contradictory_protocol_payloads():
    from pydantic import ValidationError
    from slayer_app.contracts import ToolEnvelope, WorkerJob, success, failure

    assert "error" not in success("request", "sha256:test", {}).model_dump()
    assert (
        "data"
        not in failure(
            "request", None, AnalysisError("E_NOT_READY", "Not ready")
        ).model_dump()
    )
    for ok, data, error in (
        (True, None, None),
        (True, {}, {}),
        (False, {}, {}),
        (False, None, None),
    ):
        with pytest.raises(ValidationError):
            ToolEnvelope(
                ok=ok,
                request_id="request",
                catalog_version=None,
                data=data,
                error=error,
            )
    common = dict(
        protocol_version=1,
        request_id="request",
        deadline_monotonic_ns=1,
        bundle_dir="fixed",
        catalog_version="sha256:test",
        allowed_model_ids=[],
    )
    with pytest.raises(ValidationError):
        WorkerJob(operation="analyse", request=None, **common)
    with pytest.raises(ValidationError):
        WorkerJob(
            operation="validate",
            request=dict(period=dict(from_year=2025, to_year=2025), outputs=[]),
            **common,
        )
    WorkerJob(operation="validate", request=None, **common)


def test_source_schema_types_are_checked_against_original_parquet(tmp_path):
    derived = tmp_path / "derived-manifest-schema-test"
    shutil.copytree(REAL / "raw", derived / "raw")
    manifest = json.loads((REAL / "manifest.json").read_text())
    next(source for source in manifest["sources"] if source["alias"] == "vehicles")[
        "columns"
    ][0]["type"] = "VARCHAR"
    (derived / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AnalysisError) as error:
        build_bundle(
            derived / "manifest.json", ROOT / "models", tmp_path / "rejected-bundle"
        )
    assert error.value.details["quality_code"] == "SOURCE_SCHEMA_MISMATCH"
    assert not (tmp_path / "rejected-bundle").exists()


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing_district", "INVALID_DIMENSION_VALUE"),
        ("conflicting_district_label", "DIMENSION_LABEL_CONFLICT"),
    ],
)
def test_shared_dimension_incomplete_or_conflicting_mapping_blocks_readiness(
    derived_catalog, change, code
):
    with duckdb.connect(str(derived_catalog.database_path)) as con:
        if change == "missing_district":
            con.execute(
                "UPDATE municipalities SET district_id=NULL WHERE municipality_id=2401"
            ).fetchall()
        else:
            con.execute(
                "UPDATE municipalities SET district_name='derived conflicting label' WHERE municipality_id=2401"
            ).fetchall()
    quality = check_data(derived_catalog)
    assert quality["ready"] is False
    assert any(
        v["source_id"] == "municipalities" and v["code"] == code
        for v in quality["violations"]
    )


def test_bundle_cannot_omit_database_from_checksum_index(tmp_path, bundle_dir):
    derived = tmp_path / "derived-incomplete-integrity-index"
    shutil.copytree(bundle_dir, derived)
    manifest_path = derived / "bundle.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"].pop("pilot.duckdb")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(AnalysisError) as error:
        load_catalog(derived)
    assert error.value.code == "E_NOT_READY"
