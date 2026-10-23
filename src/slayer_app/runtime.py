"""Single-slot supervision, safe discovery, and structured operational logs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time
from uuid import uuid4

import anyio

from .config import PUBLIC_BYTES, WORKER_BYTES, Settings
from .contracts import (
    AnalysisError,
    AnalysisRequest,
    ToolEnvelope,
    WorkerJob,
    failure,
    success,
)

_LOG = logging.getLogger("slayer_app.events")
_SAFE_FIELDS = frozenset(
    {
        "request_id",
        "catalog_version",
        "model_ids",
        "metric_ids",
        "duration_ms",
        "internal_rows",
        "returned_rows",
        "truncated",
        "ok",
        "error_code",
        "available_sources",
        "quarantined_sources",
        "unavailable_sources",
        "quality_codes",
        "exception_class",
    }
)


def configure_logging() -> None:
    # Every emitted application message is already a JSON object. Native logs
    # may contain SQL, paths or user literals, so their handlers stay disabled.
    logging.getLogger().handlers.clear()
    logging.getLogger().addHandler(logging.NullHandler())
    logging.getLogger().setLevel(logging.CRITICAL)
    for name in (
        "slayer",
        "mcp",
        "httpx",
        "httpcore",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # Disable existing native descendants even if they installed explicit levels.
    for name, logger in logging.root.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and name.startswith(
            ("slayer.", "mcp.", "httpx.", "httpcore.", "uvicorn.")
        ):
            logger.disabled = True
            logger.handlers.clear()
    _LOG.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False


def log_event(event: str, **safe_fields) -> None:
    document = {"event": event, "time_utc": datetime.now(timezone.utc).isoformat()}
    document.update(
        {key: value for key, value in safe_fields.items() if key in _SAFE_FIELDS}
    )
    _LOG.info(
        json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ready = False
        self.closing = False
        self.catalog = None
        self.storage = None
        self.search_service = None
        self.inspect_service = None
        self.active_process = None
        self._active_task = None
        self._busy = False
        self._hard_failure = False
        self._discovery_dir = None
        self._discovery_tasks = set()
        self.not_ready_reason = "STARTING"
        self._last_stats = {}

    @property
    def catalog_version(self):
        return self.catalog.catalog_version if self.catalog is not None else None

    def _not_ready(self):
        if not self.ready or self.closing or self._hard_failure:
            raise AnalysisError(
                "E_NOT_READY",
                "Der Dienst ist für Analysen noch nicht bereit.",
                {"quality_code": self.not_ready_reason},
            )

    def _job(self, operation, request_id, seconds, request=None):
        return WorkerJob(
            protocol_version=1,
            operation=operation,
            request_id=request_id,
            deadline_monotonic_ns=time.monotonic_ns() + int(seconds * 1_000_000_000),
            bundle_dir=str(self.settings.bundle_dir),
            catalog_version=self.catalog_version,
            allowed_model_ids=list(self.catalog.allowed_model_ids),
            request=request,
        )

    async def start(self) -> None:
        from .catalog import load_catalog, make_storage, _plain
        from slayer.search.service import SearchService
        from slayer.search.retrievers.bm25 import BM25Retriever
        from slayer.search.retrievers.tantivy import TantivyRetriever
        from slayer.inspect.service import InspectService

        self.settings.work_dir.mkdir(parents=True, exist_ok=True)
        startup_dir = None
        try:
            self.catalog = load_catalog(self.settings.bundle_dir)
            startup_dir = Path(
                tempfile.mkdtemp(prefix="validate-", dir=self.settings.work_dir)
            )
            job = self._job(
                "validate", str(uuid4()), self.settings.startup_timeout_seconds
            )
            result = await self._run_worker(job, startup_dir)
            if not result.ok:
                raise AnalysisError(
                    "E_NOT_READY",
                    "Die Startprüfung ist fehlgeschlagen.",
                    {"quality_code": result.error["code"]},
                )
            report = result.data
            if not report.get("ready"):
                codes = sorted({v["code"] for v in report.get("violations", [])})
                raise AnalysisError(
                    "E_NOT_READY",
                    "Die Kernquellen haben die Startprüfung nicht bestanden.",
                    {"quality_code": codes[0] if codes else "DATA_INVALID"},
                )
            if report != _plain(self.catalog.quality):
                raise AnalysisError(
                    "E_NOT_READY",
                    "Der geprüfte Qualitätsstand stimmt nicht mit dem Bundle überein.",
                    {"quality_code": "QUALITY_REPORT_CHANGED"},
                )
            self._discovery_dir = Path(
                tempfile.mkdtemp(prefix="discovery-", dir=self.settings.work_dir)
            )
            self.storage = await make_storage(self.catalog, self._discovery_dir)
            self.search_service = SearchService(
                storage=self.storage,
                engine=None,
                retrievers=[BM25Retriever(), TantivyRetriever()],
            )
            self.inspect_service = InspectService(storage=self.storage, engine=None)
            self.ready = True
            self.not_ready_reason = ""
            source_counts = {
                status: len(
                    {
                        self.catalog.models[name].meta["analytics"]["source_id"]
                        for name, item in report["source_status"].items()
                        if item["status"] == status
                    }
                )
                for status in ("ready", "quarantined", "unavailable")
            }
            log_event(
                "startup",
                catalog_version=self.catalog_version,
                ok=True,
                available_sources=source_counts["ready"],
                quarantined_sources=source_counts["quarantined"],
                unavailable_sources=source_counts["unavailable"],
                quality_codes=sorted(
                    {v["code"] for v in report.get("violations", [])}
                    | {
                        r["code"]
                        for s in report["source_status"].values()
                        for r in s["status_reasons"]
                    }
                ),
            )
        except AnalysisError as error:
            self.ready = False
            self.not_ready_reason = error.details.get("quality_code", error.code)
            log_event(
                "startup",
                catalog_version=self.catalog_version,
                ok=False,
                available_sources=0,
                quarantined_sources=0,
                unavailable_sources=0,
                error_code=error.code,
                quality_codes=[self.not_ready_reason],
            )
        except BaseException:
            await self.aclose()
            raise
        finally:
            if startup_dir is not None:
                shutil.rmtree(startup_dir, ignore_errors=True)

    async def _discover(self, operation, value, limit=None):
        request_id = str(uuid4())
        task = asyncio.current_task()
        self._discovery_tasks.add(task)
        try:
            self._not_ready()
            from .catalog import describe_catalog, search_catalog

            if operation == "search":
                data = await search_catalog(
                    self.catalog, self.search_service, value, limit
                )
            else:
                data = await describe_catalog(self.catalog, self.inspect_service, value)
            return success(request_id, self.catalog_version, data)
        except AnalysisError as error:
            return failure(request_id, self.catalog_version, error)
        except Exception as error:
            return failure(
                request_id,
                self.catalog_version,
                AnalysisError(
                    "E_INTERNAL",
                    "Die Beschreibung konnte nicht erstellt werden.",
                    {"exception_class": type(error).__name__},
                ),
            )
        finally:
            self._discovery_tasks.discard(task)

    async def search(self, query: str, limit: int = 10) -> ToolEnvelope:
        return await self._discover("search", query, limit)

    async def inspect(self, model_id: str) -> ToolEnvelope:
        return await self._discover("inspect", model_id)

    async def analyse(self, request: AnalysisRequest) -> ToolEnvelope:
        request_id = str(uuid4())
        started = time.monotonic_ns()
        job_dir = None
        acquired = False
        envelope = None
        metrics = set()
        if self.catalog is not None:

            def walk(node):
                if node.kind == "aggregate" and node.metric in self.catalog.metrics:
                    metrics.add(node.metric)
                elif node.kind == "binary":
                    walk(node.left)
                    walk(node.right)
                elif node.kind == "period":
                    walk(node.value)

            for output in request.outputs:
                walk(output.expr)
        stats = {}
        try:
            self._not_ready()
            # No await occurs between checking and reserving this single slot.
            if self._busy:
                raise AnalysisError(
                    "E_BUSY",
                    "Eine Analyse läuft bereits; bitte später erneut anfragen.",
                    retryable=True,
                )
            self._busy = acquired = True
            self._active_task = asyncio.current_task()
            job = self._job(
                "analyse", request_id, self.settings.query_timeout_seconds, request
            )
            job_dir = Path(
                tempfile.mkdtemp(prefix="query-", dir=self.settings.work_dir)
            )
            envelope = await self._run_worker(job, job_dir)
            stats = self._last_stats
            return envelope
        except AnalysisError as error:
            envelope = failure(request_id, self.catalog_version, error)
            return envelope
        except asyncio.CancelledError:
            envelope = failure(
                request_id,
                self.catalog_version,
                AnalysisError("E_ENGINE_FAILURE", "Die Analyse wurde beendet."),
            )
            raise
        except Exception as error:
            envelope = failure(
                request_id,
                self.catalog_version,
                AnalysisError(
                    "E_INTERNAL",
                    "Die Analyse konnte nicht bearbeitet werden.",
                    {"exception_class": type(error).__name__},
                ),
            )
            return envelope
        finally:
            if acquired:
                if job_dir is not None:
                    shutil.rmtree(job_dir, ignore_errors=True)
                if not self._hard_failure:
                    self._busy = False
                    self._active_task = None
            data = envelope.data if envelope is not None and envelope.ok else {}
            log_event(
                "analysis_complete",
                request_id=request_id,
                catalog_version=self.catalog_version,
                model_ids=sorted(
                    {self.catalog.metrics[m]["model_id"] for m in metrics}
                ),
                metric_ids=sorted(metrics),
                duration_ms=round((time.monotonic_ns() - started) / 1_000_000, 3),
                internal_rows=stats.get("internal_rows", 0),
                returned_rows=len(data.get("rows", [])),
                truncated=data.get("truncated", False),
                ok=bool(envelope and envelope.ok),
                error_code=envelope.error["code"]
                if envelope and envelope.error
                else None,
            )

    async def _run_worker(self, job: WorkerJob, job_dir: Path) -> ToolEnvelope:
        (job_dir / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
        process = None
        self._last_stats = {}
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "slayer_app.worker",
                "--job-dir",
                str(job_dir),
                start_new_session=True,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        try:
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    while process is None:
                        try:
                            process = await asyncio.shield(spawn)
                        except asyncio.CancelledError:
                            continue
                raise
            self.active_process = process
            remaining = (
                job.deadline_monotonic_ns - time.monotonic_ns()
            ) / 1_000_000_000
            if remaining <= 0:
                raise TimeoutError
            await asyncio.wait_for(process.wait(), remaining)
            if (
                time.monotonic_ns() >= job.deadline_monotonic_ns
                or process.returncode in (124, -signal.SIGALRM)
            ):
                raise TimeoutError
            if process.returncode != 0:
                raise AnalysisError(
                    "E_ENGINE_FAILURE",
                    "Der Berechnungsprozess wurde unerwartet beendet.",
                )
            try:
                with (job_dir / "result.json").open("rb") as stream:
                    payload = stream.read(WORKER_BYTES + 1)
                if len(payload) > WORKER_BYTES:
                    raise ValueError("size")
                if job.operation == "analyse" and len(payload) > PUBLIC_BYTES:
                    raise AnalysisError(
                        "E_RESULT_TOO_LARGE",
                        "Die Ergebnisgrösse überschreitet die Dienstgrenze.",
                    )
                document = json.loads(
                    payload,
                    parse_constant=lambda _: (_ for _ in ()).throw(
                        ValueError("finite")
                    ),
                )
                envelope = ToolEnvelope.model_validate(document)
                if (
                    envelope.request_id != job.request_id
                    or envelope.catalog_version != job.catalog_version
                    or (envelope.data is None) == (envelope.error is None)
                    or envelope.ok != (envelope.error is None)
                ):
                    raise ValueError("identity")
            except AnalysisError:
                raise
            except Exception as error:
                raise AnalysisError(
                    "E_WORKER_PROTOCOL",
                    "Der Berechnungsprozess lieferte keine gültige Antwort.",
                ) from error
            stats_path = job_dir / "stats.json"
            if stats_path.exists() and stats_path.stat().st_size <= 256:
                stats = json.loads(stats_path.read_text())
                if all(
                    type(stats.get(k)) is int and stats[k] >= 0
                    for k in ("internal_rows", "returned_rows")
                ):
                    self._last_stats = stats
            if time.monotonic_ns() >= job.deadline_monotonic_ns:
                raise TimeoutError
            return envelope
        except TimeoutError as error:
            raise AnalysisError(
                "E_TIMEOUT",
                "Die Analyse überschritt die Zeitgrenze; bitte die Analyse vereinfachen.",
            ) from error
        finally:
            if process is not None:
                await self._terminate_and_reap(process)
                if not self._hard_failure:
                    self.active_process = None

    async def _terminate_and_reap(self, process) -> None:
        # Both AnyIO level cancellation and repeated asyncio.Task.cancel calls
        # must leave cleanup running until the OS child has been reaped.
        with anyio.CancelScope(shield=True):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                # Confirmation below is authoritative even if kill failed.
                pass
            wait_task = asyncio.create_task(process.wait())
            deadline = asyncio.get_running_loop().time() + 2
            while not wait_task.done():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(wait_task), remaining)
                except asyncio.CancelledError:
                    continue
                except TimeoutError:
                    break
            if not wait_task.done():
                self.ready = False
                self._hard_failure = True
                self.not_ready_reason = "PROCESS_NOT_REAPED"
                log_event(
                    "process_cleanup_failed",
                    catalog_version=self.catalog_version,
                    ok=False,
                    error_code="E_NOT_READY",
                )
                wait_task.cancel()
                await asyncio.gather(wait_task, return_exceptions=True)
                # The server observes this flag and exits for operator restart.
                raise AnalysisError(
                    "E_NOT_READY", "Das Prozessende konnte nicht bestätigt werden."
                )
            wait_task.result()

    async def aclose(self) -> None:
        self.closing = True
        self.ready = False
        current = asyncio.current_task()
        task = self._active_task
        if task is not None and task is not current and not task.done():
            task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)
        elif self.active_process is not None:
            await self._terminate_and_reap(self.active_process)
            if not self._hard_failure:
                self.active_process = None
        pending = [t for t in self._discovery_tasks if t is not current]
        for task in pending:
            task.cancel()
        if pending:
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*pending, return_exceptions=True)
        self.search_service = self.inspect_service = self.storage = None
        if self._discovery_dir is not None:
            shutil.rmtree(self._discovery_dir, ignore_errors=True)
            self._discovery_dir = None
