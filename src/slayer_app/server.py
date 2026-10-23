"""The three read-only MCP tools over one Streamable HTTP endpoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import PUBLIC_BYTES, REQUEST_BYTES, Settings, load_settings
from .contracts import AnalysisError, AnalysisRequest, ToolEnvelope, failure
from .runtime import Runtime, configure_logging


def to_mcp(envelope: ToolEnvelope) -> CallToolResult:
    payload = envelope.model_dump()
    text = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    if len(text.encode("utf-8")) > PUBLIC_BYTES:
        envelope = failure(
            envelope.request_id,
            envelope.catalog_version,
            AnalysisError(
                "E_RESULT_TOO_LARGE",
                "Die Ergebnisgrösse überschreitet die Dienstgrenze.",
            ),
        )
        payload = envelope.model_dump()
        text = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=not envelope.ok,
    )


def create_app(settings: Settings) -> Starlette:
    runtime = Runtime(settings)
    mcp = FastMCP(
        "Solothurn Datenanalyse",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        max_request_body_size=REQUEST_BYTES,
        instructions=(
            "Zuerst search und inspect verwenden; Codes statt Namen übergeben. "
            "Neue Analysen im veröffentlichten Ausdrucksvertrag kombinieren. "
            "Systemdefinition, Formel, Hinweise und cell_status erhalten; NULL ist keine 0. "
            "Nicht beobachtete gemeinsame Merkmale lassen sich nicht durch Joins schätzen."
        ),
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
    )
    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(annotations=annotations)
    async def search(query: str, limit: int = 10) -> CallToolResult:
        """Freigegebene Kennzahlen lexikalisch suchen; danach Definitionen mit inspect prüfen."""
        return to_mcp(await runtime.search(query, limit))

    @mcp.tool(annotations=annotations)
    async def inspect(model_id: str) -> CallToolResult:
        """Definitionen, typisierte Codes, verfügbare Jahre, Quellen und fachliche Grenzen lesen."""
        return to_mcp(await runtime.inspect(model_id))

    @mcp.tool(annotations=annotations)
    async def analyse(request: AnalysisRequest) -> CallToolResult:
        """Eine neue Jahresanalyse prüfen und mit SLayer berechnen; Hinweise und Zellstatus beibehalten."""
        return to_mcp(await runtime.analyse(request))

    mcp_app = mcp.streamable_http_app()

    async def protected_mcp(scope, receive, send):
        if scope["type"] == "http" and settings.gateway_token is not None:
            authorization = dict(scope.get("headers", [])).get(b"authorization", b"")
            expected = ("Bearer " + settings.gateway_token).encode("utf-8")
            if not hmac.compare_digest(authorization, expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(
                    scope, receive, send
                )
                return
        await mcp_app(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await runtime.start()
            async with mcp.session_manager.run():
                yield
        finally:
            await runtime.aclose()

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def ready(request):
        available = runtime.ready and not runtime.closing and not runtime._hard_failure
        return JSONResponse({"ready": available}, status_code=200 if available else 503)

    app = Starlette(
        routes=[
            Route("/healthz", health),
            Route("/readyz", ready),
            Mount("/", app=protected_mcp),
        ],
        lifespan=lifespan,
        max_body_size=REQUEST_BYTES,
    )
    app.state.runtime = runtime
    app.state.mcp = mcp
    return app


def main() -> None:
    import uvicorn

    configure_logging()
    settings = load_settings()
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        reload=False,
        access_log=False,
        log_config=None,
        proxy_headers=False,
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)

    async def serve():
        async def monitor():
            while not server.should_exit:
                if app.state.runtime._hard_failure:
                    server.should_exit = True
                    return
                await asyncio.sleep(0.1)

        monitor_task = asyncio.create_task(monitor())
        try:
            await server.serve()
        finally:
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)

    asyncio.run(serve())
    if app.state.runtime._hard_failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
