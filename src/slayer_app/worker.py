"""One transient, alarm-bounded native SLayer query process.

Only standard-library imports occur before the command entry point arms SIGALRM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import ToolEnvelope, WorkerJob


def arm_deadline(deadline_monotonic_ns: int) -> None:
    remaining = (deadline_monotonic_ns - time.monotonic_ns()) / 1_000_000_000
    if remaining <= 0:
        raise SystemExit(124)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining)


def write_result(path: Path, envelope: ToolEnvelope, *, public: bool) -> None:
    from .config import PUBLIC_BYTES, WORKER_BYTES
    from .contracts import AnalysisError, failure

    payload = json.dumps(
        envelope.model_dump(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > (PUBLIC_BYTES if public else WORKER_BYTES):
        envelope = failure(
            envelope.request_id,
            envelope.catalog_version,
            AnalysisError(
                "E_RESULT_TOO_LARGE",
                "Die Ergebnisgrösse überschreitet die Dienstgrenze.",
            ),
        )
        payload = json.dumps(
            envelope.model_dump(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    temporary = path.with_suffix(".tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
    os.replace(temporary, path)


async def run_job(job: WorkerJob, job_dir: Path) -> ToolEnvelope:
    from . import config as _config  # noqa: F401 — disables telemetry before SLayer imports
    from .contracts import AnalysisError, failure, success
    from .catalog import check_data, load_catalog, make_storage

    try:
        catalog = load_catalog(Path(job.bundle_dir))
        if job.catalog_version != catalog.catalog_version or set(
            job.allowed_model_ids
        ) != set(catalog.allowed_model_ids):
            raise AnalysisError(
                "E_WORKER_PROTOCOL",
                "Der Worker erhielt einen abweichenden Katalogstand.",
            )
        if job.operation == "validate":
            report = check_data(catalog)
            # Saving models exercises the native model/relationship validation.
            await make_storage(catalog, job_dir / "native")
            return success(job.request_id, catalog.catalog_version, report)
        if job.request is None:
            raise AnalysisError(
                "E_WORKER_PROTOCOL", "Die interne Analyseanfrage fehlt."
            )
        from slayer.engine.query_engine import SlayerQueryEngine
        from .semantics import SemanticCompiler

        compiler = SemanticCompiler(catalog)
        compiled = compiler.compile(job.request)
        storage = await make_storage(catalog, job_dir / "native")
        engine = SlayerQueryEngine(storage=storage)
        # Native threaded DuckDB completion on macOS requires an event-loop
        # wakeup. This timer does not alter the query, its plan, or its numbers.
        loop = asyncio.get_running_loop()
        timer = None

        def pulse():
            nonlocal timer
            timer = loop.call_later(0.05, pulse)

        pulse()
        try:
            preview = await engine.execute(
                compiled.native_query, dry_run=True, cache=False
            )
            compiler.check_native_response(compiled, preview)
            response = await engine.execute(compiled.native_query, cache=False)
            compiler.check_native_response(compiled, response)
            data = compiler.finalize(compiled, response)
            (job_dir / "stats.json").write_text(
                json.dumps(
                    {
                        "internal_rows": len(response.data),
                        "returned_rows": len(data["rows"]),
                    }
                ),
                encoding="utf-8",
            )
            return success(job.request_id, catalog.catalog_version, data)
        finally:
            if timer is not None:
                timer.cancel()
            await engine.aclose()
    except AnalysisError as error:
        return failure(job.request_id, job.catalog_version, error)
    except Exception as error:
        return failure(
            job.request_id,
            job.catalog_version,
            AnalysisError(
                "E_ENGINE_FAILURE",
                "Die Berechnung konnte nicht ausgeführt werden.",
                {"exception_class": type(error).__name__},
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, required=True)
    arguments = parser.parse_args()
    # The job is private and small; no native or validation imports precede alarm.
    try:
        with (arguments.job_dir / "job.json").open("rb") as stream:
            raw = stream.read(131_073)
        if len(raw) > 131_072:
            return 2
        document = json.loads(raw)
        deadline = document["deadline_monotonic_ns"]
        if type(deadline) is not int:
            return 2
        arm_deadline(deadline)
    except (OSError, ValueError, KeyError, TypeError):
        return 2
    os.environ["SLAYER_USAGE_REPORTING"] = "off"
    os.environ["DO_NOT_TRACK"] = "1"
    import logging

    logging.disable(logging.CRITICAL)
    from .contracts import WorkerJob

    try:
        job = WorkerJob.model_validate(document)
        if (job.operation == "analyse") != (job.request is not None):
            return 2
        envelope = asyncio.run(run_job(job, arguments.job_dir))
        write_result(
            arguments.job_dir / "result.json",
            envelope,
            public=job.operation == "analyse",
        )
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
