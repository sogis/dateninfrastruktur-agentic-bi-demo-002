"""Real integration fixtures; derived DB copies never alter frozen inputs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

os.environ["SLAYER_USAGE_REPORTING"] = "off"
os.environ["DO_NOT_TRACK"] = "1"

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "tests" / "fixtures" / "real"


@pytest.fixture(scope="session")
def oracle():
    return json.loads((REAL / "expected_results.json").read_text())["results"]


@pytest.fixture(scope="session")
def bundle_dir(tmp_path_factory):
    from slayer_app.author import build_bundle

    path = tmp_path_factory.mktemp("real-bundle") / "pilot"
    build_bundle(REAL / "manifest.json", ROOT / "models", path)
    return path


@pytest.fixture(scope="session")
def catalog(bundle_dir):
    from slayer_app.catalog import load_catalog

    return load_catalog(bundle_dir)


@pytest.fixture
def derived_catalog(catalog, tmp_path):
    """Explicitly derived test data, retaining real metadata for guard tests."""
    path = tmp_path / "derived-from-real.duckdb"
    shutil.copy2(catalog.database_path, path)
    return replace(catalog, database_path=path)


@pytest.fixture
def execute(catalog, tmp_path):
    """Compile and execute unmocked native SLayer, including native dry-run."""
    serial = 0

    def run(request, *, snapshot=None, transform_response=None):
        nonlocal serial
        serial += 1

        async def invoke():
            from slayer.engine.query_engine import SlayerQueryEngine
            from slayer_app.catalog import make_storage
            from slayer_app.contracts import AnalysisRequest
            from slayer_app.semantics import SemanticCompiler

            snapshot_ = snapshot or catalog
            dto = (
                request
                if isinstance(request, AnalysisRequest)
                else AnalysisRequest.model_validate(request)
            )
            compiler = SemanticCompiler(snapshot_)
            compiled = compiler.compile(dto)
            storage = await make_storage(snapshot_, tmp_path / f"native-{serial}")
            engine = SlayerQueryEngine(storage=storage)
            # SLayer's threaded DuckDB completion needs an event-loop wakeup on
            # this platform. This timer does not alter planning or calculation.
            loop = asyncio.get_running_loop()
            timer = None

            def pulse():
                nonlocal timer
                timer = loop.call_later(0.05, pulse)

            pulse()
            try:
                preview = await asyncio.wait_for(
                    engine.execute(compiled.native_query, dry_run=True, cache=False), 30
                )
                compiler.check_native_response(compiled, preview)
                response = await asyncio.wait_for(
                    engine.execute(compiled.native_query, cache=False), 30
                )
                compiler.check_native_response(compiled, response)
                if transform_response is not None:
                    response = transform_response(compiled, response)
                return compiler.finalize(compiled, response)
            finally:
                if timer is not None:
                    timer.cancel()
                await engine.aclose()
                # Native DuckDB engines are factory-owned until process exit.
                # Direct tests need the native documented test-teardown hook.
                from slayer.sql.engine_factory import reset_cache

                reset_cache()

        return asyncio.run(invoke())

    return run
