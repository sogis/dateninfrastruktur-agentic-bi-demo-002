"""Fixed limits and local operator configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

os.environ["SLAYER_USAGE_REPORTING"] = "off"
os.environ["DO_NOT_TRACK"] = "1"

REQUEST_BYTES = 65_536
PUBLIC_BYTES = 2 * 1024 * 1024
WORKER_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10_000
MAX_OUTPUTS = 8
MAX_DIMENSIONS = 6
MAX_NODES = 40
MAX_DEPTH = 8
MAX_PREDICATES = 16
MAX_CHECKS = 24
MAX_MEASURES = 48
SEMANTIC_CONTRACT = "1.0"


@dataclass(frozen=True)
class Settings:
    bundle_dir: Path
    work_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: tuple[str, ...] = ("127.0.0.1:*", "localhost:*")
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:*", "http://localhost:*")
    gateway_token: str | None = field(default=None, repr=False)
    query_timeout_seconds: float = 15
    startup_timeout_seconds: float = 30


def load_settings() -> Settings:
    def env(key, default):
        return os.environ.get("SLAYER_APP_" + key, default)

    bundle = Path(env("BUNDLE_DIR", "build/pilot-v1")).resolve()
    work = Path(env("WORK_DIR", "build/work")).resolve()
    if not bundle.is_dir():
        raise ValueError("BUNDLE_DIR muss ein vorhandenes Datenbundle sein.")
    if work == bundle or bundle in work.parents:
        raise ValueError("WORK_DIR darf nicht innerhalb des Bundles liegen.")
    timeout = float(env("QUERY_TIMEOUT_SECONDS", "15"))
    startup = float(env("STARTUP_TIMEOUT_SECONDS", "30"))
    if not 1 <= timeout <= 60 or not 1 <= startup <= 120:
        raise ValueError("Ungültige Prozessfrist.")
    port = int(env("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("Ungültiger Port.")
    hosts = tuple(
        item.strip()
        for item in env("ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(",")
    )
    origins = tuple(
        item.strip()
        for item in env(
            "ALLOWED_ORIGINS", "http://127.0.0.1:*,http://localhost:*"
        ).split(",")
    )
    if not all(hosts) or not all(origins):
        raise ValueError(
            "ALLOWED_HOSTS und ALLOWED_ORIGINS müssen explizite Werte enthalten."
        )
    token = env("GATEWAY_BEARER_TOKEN", None)
    if token is not None and not token.strip():
        raise ValueError("GATEWAY_BEARER_TOKEN darf nicht leer sein.")
    work.mkdir(parents=True, exist_ok=True)
    return Settings(
        bundle,
        work,
        env("HOST", "127.0.0.1"),
        port,
        hosts,
        origins,
        token,
        timeout,
        startup,
    )
