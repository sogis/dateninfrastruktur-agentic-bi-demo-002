"""B03–B09, B12–B14: real transient processes; controlled process faults only."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
import shutil
import signal
import sys
import time

import pytest
import anyio

from slayer_app.config import PUBLIC_BYTES, WORKER_BYTES, Settings
from slayer_app.contracts import AnalysisRequest, success
from slayer_app.runtime import Runtime, configure_logging


def f04():
    return AnalysisRequest.model_validate(
        {
            "period": {"from_year": 2025, "to_year": 2025},
            "outputs": [
                {
                    "id": "ratio",
                    "expr": {
                        "kind": "binary",
                        "op": "divide",
                        "scale": 1000,
                        "left": {
                            "kind": "aggregate",
                            "metric": "vehicles.count",
                            "where": [
                                {
                                    "field": "vehicles.category",
                                    "op": "in",
                                    "values": ["01", "60"],
                                }
                            ],
                        },
                        "right": {"kind": "aggregate", "metric": "population.count"},
                    },
                }
            ],
        }
    )


@pytest.fixture
async def runtime(bundle_dir, tmp_path):
    instance = Runtime(Settings(bundle_dir, tmp_path / "work"))
    await instance.start()
    assert instance.ready, instance.not_ready_reason
    try:
        yield instance
    finally:
        await instance.aclose()
    assert not list(instance.settings.work_dir.iterdir())


async def wait_marker(path, *, timeout=4):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, "real DuckDB worker did not reach query"
        await asyncio.sleep(0.01)


def install_worker(monkeypatch, tmp_path, mode="slow", *, alarm=False):
    """Fixed test process, never selectable through any application request."""
    script = tmp_path / "controlled_worker.py"
    script.write_text(
        """import json, os, signal, sys, time
from pathlib import Path
job_dir = Path(sys.argv[-1])
job = json.loads((job_dir / "job.json").read_text())
mode = """
        + repr(mode)
        + """
if mode == "slow":
    if """
        + repr(alarm)
        + """:
        from slayer_app.worker import arm_deadline
        arm_deadline(job["deadline_monotonic_ns"])
    import duckdb
    con = duckdb.connect(":memory:", config={"threads": "1", "memory_limit": "256MB"})
    (job_dir / "running").write_text(str(os.getpid()))
    con.execute("SELECT sum(sqrt(i::DOUBLE)) FROM range(1000000000000) t(i)").fetchall()
elif mode == "exit":
    sys.exit(7)
elif mode == "invalid":
    (job_dir / "result.json").write_text("{broken")
elif mode == "oversize":
    (job_dir / "result.json").write_bytes(b"x" * (8*1024*1024 + 1))
elif mode == "identity":
    (job_dir / "result.json").write_text(json.dumps({"ok":True,"request_id":"wrong","catalog_version":job["catalog_version"],"data":{}}))
"""
    )
    original = asyncio.create_subprocess_exec
    calls = []

    async def launch(*args, **kwargs):
        calls.append(args)
        return await original(sys.executable, str(script), args[-1], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    return calls, original


async def active_query(runtime):
    deadline = time.monotonic() + 4
    while runtime.active_process is None:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    directory = next(runtime.settings.work_dir.glob("query-*"))
    await wait_marker(directory / "running")
    # The fixed 10^12-row CPU query cannot complete in this interval.
    await asyncio.sleep(0.1)
    assert runtime.active_process.returncode is None
    return runtime.active_process, directory


def assert_reaped(process):
    assert process.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)


async def test_B03_quarantine_ready_and_native_analysis(runtime):
    info = await runtime.inspect("population_sex_nationality")
    assert info.ok and info.data["status"] == "quarantined"
    assert "DUPLICATE_KEY" in json.dumps(info.data["status_reasons"])
    assert runtime.ready
    result = await runtime.analyse(f04())
    assert result.ok, result.error
    assert result.data["rows"][0]["ratio"] == pytest.approx(
        649.6804637625776, abs=1e-9, rel=0
    )
    assert "internal_rows" not in result.data


async def test_B04_bad_core_is_not_ready(bundle_dir, tmp_path):
    import duckdb
    from slayer_app.catalog import file_hash

    path = tmp_path / "derived-bad-core"
    shutil.copytree(bundle_dir, path)
    con = duckdb.connect(str(path / "pilot.duckdb"))
    con.execute(
        "CREATE OR REPLACE TABLE population AS SELECT * FROM population UNION ALL (SELECT * FROM population LIMIT 1)"
    )
    con.close()
    # Explicit derived test bundle: update only physical-file integrity so the
    # startup data check, rather than a checksum rejection, sees the bad key.
    manifest = json.loads((path / "bundle.json").read_text())
    manifest["files"]["pilot.duckdb"] = file_hash(path / "pilot.duckdb")
    (path / "bundle.json").write_text(json.dumps(manifest))
    runtime = Runtime(Settings(path, tmp_path / "work"))
    try:
        await runtime.start()
        assert not runtime.ready
        result = await runtime.analyse(f04())
        assert result.error["code"] == "E_NOT_READY"
    finally:
        await runtime.aclose()


async def test_B05_busy_no_queue_discovery_remains_available(
    runtime, tmp_path, monkeypatch
):
    calls, _ = install_worker(monkeypatch, tmp_path)
    task = asyncio.create_task(runtime.analyse(f04()))
    process, _ = await active_query(runtime)
    started = time.monotonic()
    busy = await runtime.analyse(f04())
    assert busy.error["code"] == "E_BUSY" and busy.error["retryable"]
    assert time.monotonic() - started < 0.2
    assert len(calls) == 1 and runtime.ready
    assert (await runtime.inspect("vehicles")).ok
    assert (await runtime.search("Fahrzeugbestand", 2)).ok
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_reaped(process)
    assert not runtime._busy


async def test_B06_supervisor_kills_running_duckdb_then_next_query(
    runtime, tmp_path, monkeypatch
):
    calls, original = install_worker(monkeypatch, tmp_path, alarm=False)
    runtime.settings = replace(runtime.settings, query_timeout_seconds=2)
    task = asyncio.create_task(runtime.analyse(f04()))
    process, directory = await active_query(runtime)
    result = await task
    assert result.error["code"] == "E_TIMEOUT"
    assert_reaped(process)
    assert process.returncode == -signal.SIGKILL
    assert not directory.exists() and not runtime._busy
    assert len(calls) == 1
    monkeypatch.setattr(asyncio, "create_subprocess_exec", original)
    runtime.settings = replace(runtime.settings, query_timeout_seconds=15)
    assert (await runtime.analyse(f04())).ok


async def test_B07_worker_alarm_without_supervisor_kill(tmp_path, monkeypatch):
    _, original = install_worker(monkeypatch, tmp_path, alarm=True)
    job_dir = tmp_path / "alarm-job"
    job_dir.mkdir()
    job = {"deadline_monotonic_ns": time.monotonic_ns() + 1_500_000_000}
    (job_dir / "job.json").write_text(json.dumps(job))
    process = await original(
        sys.executable,
        str(tmp_path / "controlled_worker.py"),
        str(job_dir),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await wait_marker(job_dir / "running")
        await asyncio.wait_for(process.wait(), 4)
        assert process.returncode == -signal.SIGALRM
        assert_reaped(process)
    finally:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


@pytest.mark.parametrize("shutdown", [False, True], ids=["cancellation", "shutdown"])
async def test_B08_cancellation_and_shutdown_reap_before_release(
    runtime, tmp_path, monkeypatch, shutdown
):
    install_worker(monkeypatch, tmp_path)
    task = asyncio.create_task(runtime.analyse(f04()))
    process, directory = await active_query(runtime)
    if shutdown:
        await runtime.aclose()
    else:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_reaped(process)
    assert not directory.exists() and not runtime._busy
    if shutdown:
        assert (await runtime.analyse(f04())).error["code"] == "E_NOT_READY"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("exit", "E_ENGINE_FAILURE"),
        ("invalid", "E_WORKER_PROTOCOL"),
        ("oversize", "E_WORKER_PROTOCOL"),
        ("identity", "E_WORKER_PROTOCOL"),
    ],
)
async def test_B09_worker_faults_are_safe_and_clean(
    runtime, tmp_path, monkeypatch, mode, code
):
    install_worker(monkeypatch, tmp_path, mode)
    result = await runtime.analyse(f04())
    assert result.error["code"] == code
    assert "Traceback" not in result.model_dump_json()
    assert not runtime._busy and runtime.active_process is None
    assert not list(runtime.settings.work_dir.glob("query-*"))


def test_B12_public_and_internal_result_size(tmp_path):
    from slayer_app.worker import write_result
    from slayer_app.server import to_mcp

    huge = success(
        "server-id", "sha256:test", {"rows": [{"value": "x" * PUBLIC_BYTES}]}
    )
    path = tmp_path / "result.json"
    write_result(path, huge, public=True)
    assert json.loads(path.read_bytes())["error"]["code"] == "E_RESULT_TOO_LARGE"
    assert path.stat().st_size < PUBLIC_BYTES
    assert to_mcp(huge).structuredContent["error"]["code"] == "E_RESULT_TOO_LARGE"
    path.unlink()
    internal = success("server-id", "sha256:test", {"report": "x" * WORKER_BYTES})
    write_result(path, internal, public=False)
    assert json.loads(path.read_bytes())["error"]["code"] == "E_RESULT_TOO_LARGE"


async def test_B14_json_completion_logs_are_safe(runtime, capsys):
    configure_logging()
    result = await runtime.analyse(f04())
    assert result.ok
    documents = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    completion = [d for d in documents if d["event"] == "analysis_complete"]
    assert len(completion) == 1
    event = completion[0]
    assert event["request_id"] == result.request_id
    assert event["catalog_version"] == result.catalog_version
    assert event["metric_ids"] == ["population.count", "vehicles.count"]
    assert event["internal_rows"] == event["returned_rows"] == 1
    assert event["duration_ms"] > 0 and event["ok"]
    text = json.dumps(documents)
    assert all(
        value not in text
        for value in (
            "SELECT",
            "649.680",
            "vehicle_category_code",
            "Bearer",
            "connection_string",
        )
    )
    with capsys.disabled():
        configure_logging()


async def test_B08_anyio_level_cancellation_and_repeated_task_cancel(
    runtime, tmp_path, monkeypatch
):
    install_worker(monkeypatch, tmp_path)
    async with anyio.create_task_group() as group:
        group.start_soon(runtime.analyse, f04())
        process, directory = await active_query(runtime)
        group.cancel_scope.cancel()
    assert_reaped(process)
    assert not directory.exists() and not runtime._busy
    task = asyncio.create_task(runtime.analyse(f04()))
    process, directory = await active_query(runtime)
    for _ in range(5):
        if task.done():
            break
        task.cancel()
        await asyncio.sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_reaped(process)
    assert not directory.exists() and not runtime._busy


async def test_B08_unconfirmed_reap_blocks_slot_and_readiness(runtime, monkeypatch):
    from types import SimpleNamespace
    from slayer_app.contracts import AnalysisError

    # A bounded process-control fault is the only stub here; all actual engine,
    # timeout and cancellation acceptance paths above use real OS children.
    async def never_confirms():
        await asyncio.Event().wait()

    process = SimpleNamespace(pid=99999999, wait=never_confirms)
    monkeypatch.setattr(os, "killpg", lambda *args: None)
    runtime._busy = True
    with pytest.raises(AnalysisError) as raised:
        await runtime._terminate_and_reap(process)
    assert raised.value.code == "E_NOT_READY"
    assert runtime._hard_failure and not runtime.ready and runtime._busy
    assert (await runtime.analyse(f04())).error["code"] == "E_NOT_READY"


async def test_startup_rejects_quality_report_drift(bundle_dir, tmp_path):
    """Derived test bundle: optional status cannot silently change its version."""
    import duckdb
    from slayer_app.catalog import file_hash

    path = tmp_path / "derived-quality-drift"
    shutil.copytree(bundle_dir, path)
    with duckdb.connect(str(path / "pilot.duckdb")) as connection:
        connection.execute(
            "CREATE OR REPLACE TABLE heating AS SELECT * FROM heating UNION ALL SELECT * FROM heating LIMIT 107"
        ).fetchall()
    manifest = json.loads((path / "bundle.json").read_text())
    manifest["files"]["pilot.duckdb"] = file_hash(path / "pilot.duckdb")
    (path / "bundle.json").write_text(json.dumps(manifest))
    service = Runtime(Settings(path, tmp_path / "work"))
    try:
        await service.start()
        assert not service.ready
        assert service.not_ready_reason == "QUALITY_REPORT_CHANGED"
        assert (await service.analyse(f04())).error["code"] == "E_NOT_READY"
    finally:
        await service.aclose()


def test_not_ready_envelope_keeps_null_catalog_version():
    from slayer_app.contracts import AnalysisError, failure
    from slayer_app.server import to_mcp

    envelope = failure(
        "server-generated-id", None, AnalysisError("E_NOT_READY", "Noch nicht bereit.")
    )
    result = to_mcp(envelope)
    assert "catalog_version" in result.structuredContent
    assert result.structuredContent["catalog_version"] is None
    assert "data" not in result.structuredContent
    assert json.loads(result.content[0].text) == result.structuredContent
