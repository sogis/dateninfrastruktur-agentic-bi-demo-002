"""B01/B02/B04/B12/B14: actual MCP SDK, HTTP transport and application lifespan."""

from __future__ import annotations

import asyncio
import json
import socket

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest
import uvicorn

from slayer_app.config import PUBLIC_BYTES, Settings
from slayer_app.server import create_app
from test_runtime import f04


async def test_B01_B02_actual_mcp_http_F04(bundle_dir, tmp_path, record_property):
    settings = Settings(bundle_dir, tmp_path / "work")
    app = create_app(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            access_log=False,
            log_config=None,
            proxy_headers=False,
            timeout_graceful_shutdown=5,
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    serve = asyncio.create_task(server.serve(sockets=[sock]))
    wires = []

    async def record_response(response):
        await response.aread()
        wires.append(len(response.content))

    try:
        deadline = asyncio.get_running_loop().time() + 20
        while not server.started:
            assert not serve.done(), serve.exception() if serve.done() else ""
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.02)
        async with httpx.AsyncClient(
            event_hooks={"response": [record_response]}
        ) as http:
            assert (
                await http.get(f"http://127.0.0.1:{port}/readyz")
            ).status_code == 200
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=http
            ) as (read, write, _):
                async with ClientSession(read, write) as client:
                    initialized = await client.initialize()
                    assert initialized.serverInfo.name == "Solothurn Datenanalyse"
                    tools = (await client.list_tools()).tools
                    assert {t.name for t in tools} == {"search", "inspect", "analyse"}
                    for tool in tools:
                        assert (
                            tool.annotations.readOnlyHint
                            and not tool.annotations.destructiveHint
                        )
                        assert (
                            tool.annotations.idempotentHint
                            and not tool.annotations.openWorldHint
                        )
                    schema = next(t.inputSchema for t in tools if t.name == "analyse")
                    assert schema["required"] == ["request"]
                    assert "request" in schema["properties"]
                    assert "AnalysisRequest" in schema.get("$defs", {})
                    info = await client.call_tool("inspect", {"model_id": "vehicles"})
                    assert info.structuredContent["ok"]
                    assert any(
                        v["code"] == "01"
                        for v in info.structuredContent["data"]["values"][
                            "vehicles.category"
                        ]
                    )
                    found = await client.call_tool(
                        "search", {"query": "Fahrzeugbestand", "limit": 5}
                    )
                    assert (
                        found.structuredContent["ok"]
                        and found.structuredContent["data"]["matches"]
                    )
                    result = await client.call_tool(
                        "analyse", {"request": f04().model_dump()}
                    )
                    envelope = result.structuredContent
                    assert not result.isError and envelope["ok"], envelope
                    assert json.loads(result.content[0].text) == envelope
                    assert envelope["data"]["rows"][0]["ratio"] == pytest.approx(
                        649.6804637625776, abs=1e-9, rel=0
                    )
                    assert any(
                        n["code"] == "SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN"
                        for n in envelope["data"]["notices"]
                    )
                    assert (
                        len(
                            json.dumps(
                                envelope, ensure_ascii=False, separators=(",", ":")
                            ).encode()
                        )
                        <= PUBLIC_BYTES
                    )
                    # Wire carries both JSON representations; record actual HTTP bytes.
                    record_property("B12_actual_F04_mcp_wire_bytes", wires[-1])
                    assert wires[-1] > len(result.content[0].text.encode())
                    quarantine = await client.call_tool(
                        "inspect", {"model_id": "population_sex_nationality"}
                    )
                    assert (
                        quarantine.structuredContent["data"]["status"] == "quarantined"
                    )
                    rejected = await client.call_tool(
                        "analyse",
                        {
                            "request": {
                                "period": {"from_year": 2025, "to_year": 2025},
                                "outputs": [
                                    {
                                        "id": "blocked",
                                        "expr": {
                                            "kind": "aggregate",
                                            "metric": "population_sex_nationality.count",
                                        },
                                    }
                                ],
                            }
                        },
                    )
                    assert (
                        rejected.isError
                        and rejected.structuredContent["error"]["code"]
                        == "E_MODEL_UNAVAILABLE"
                    )
            oversized = await http.post(
                f"http://127.0.0.1:{port}/mcp",
                content=b"x" * 65_537,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert oversized.status_code == 413
    finally:
        server.should_exit = True
        await asyncio.wait_for(serve, 8)
        sock.close()
    assert not app.state.runtime.ready
    assert not list(settings.work_dir.iterdir())


async def test_B14_token_constant_time_gate_keeps_probes_public(
    bundle_dir, tmp_path, capsys
):
    from slayer_app.runtime import configure_logging

    secret = "test-only-sensitive-token-93488"
    settings = Settings(bundle_dir, tmp_path / "work", gateway_token=secret)
    assert secret not in repr(settings)
    configure_logging()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/readyz")).status_code == 200
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            headers = {"Accept": "application/json, text/event-stream"}
            assert (
                await client.post("/mcp", json=body, headers=headers)
            ).status_code == 401
            assert (
                await client.post(
                    "/mcp",
                    json=body,
                    headers={**headers, "Authorization": "Bearer wrong"},
                )
            ).status_code == 401
            authorized = await client.post(
                "/mcp",
                json=body,
                headers={**headers, "Authorization": "Bearer " + secret},
            )
            assert (
                authorized.status_code == 200
                and len(authorized.json()["result"]["tools"]) == 3
            )
            badhost = await client.post(
                "/mcp",
                json=body,
                headers={
                    **headers,
                    "Authorization": "Bearer " + secret,
                    "Host": "untrusted.example",
                },
            )
            assert badhost.status_code == 421
    logged = capsys.readouterr().out
    assert secret not in logged and "Bearer" not in logged and "wrong" not in logged
    startup = [json.loads(line) for line in logged.splitlines() if line.startswith("{")]
    assert len([d for d in startup if d["event"] == "startup"]) == 1
    with capsys.disabled():
        configure_logging()


async def test_B04_health_with_unready_core_bundle(tmp_path):
    settings = Settings(tmp_path / "missing-bundle", tmp_path / "work")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/readyz")).status_code == 503
            result = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "analyse",
                        "arguments": {"request": f04().model_dump()},
                    },
                },
            )
            assert (
                result.json()["result"]["structuredContent"]["error"]["code"]
                == "E_NOT_READY"
            )
