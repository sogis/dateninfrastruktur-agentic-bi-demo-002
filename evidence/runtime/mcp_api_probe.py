"""Research-only verification of the installed FastMCP/Starlette API and mount."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib.metadata as md
import inspect
import json
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount


async def main():
    state = {'ready': False, 'lifespan_starts': 0}
    mcp = FastMCP('runtime-api-probe', stateless_http=True, json_response=True,
                  streamable_http_path='/mcp', max_request_body_size=65536,
                  transport_security=TransportSecuritySettings(
                      allowed_hosts=['testserver'], allowed_origins=['http://testserver']))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                         idempotentHint=True, openWorldHint=False))
    async def probe_tool() -> CallToolResult:
        payload = {'ok': False, 'error': {'code': 'BUSY', 'retryable': True}}
        return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload))],
                              structuredContent=payload, isError=True)

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        state['lifespan_starts'] += 1
        state['ready'] = True
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            state['ready'] = False

    async def health(request):
        return JSONResponse({'status': 'ok'})

    async def ready(request):
        return JSONResponse({'ready': state['ready']}, status_code=200 if state['ready'] else 503)

    app = Starlette(routes=[Route('/healthz', health, methods=['GET']),
                            Route('/readyz', ready, methods=['GET']),
                            Mount('/', app=mcp_app)],
                    lifespan=lifespan, max_body_size=65536)
    report = {
        'versions': {p: md.version(p) for p in ['motley-slayer','mcp','starlette','uvicorn','duckdb',
                                              'duckdb-engine','sqlglot','SQLAlchemy','pydantic','anyio']},
        'signatures': {name: str(inspect.signature(obj)) for name, obj in [
            ('FastMCP',FastMCP), ('FastMCP.run',FastMCP.run), ('FastMCP.tool',FastMCP.tool),
            ('FastMCP.custom_route',FastMCP.custom_route),
            ('FastMCP.streamable_http_app',FastMCP.streamable_http_app),
            ('FastMCP.sse_app',FastMCP.sse_app), ('Starlette',Starlette),
            ('Route',Route), ('Mount',Mount), ('JSONResponse',JSONResponse)]},
    }
    transport = httpx.ASGITransport(app=app)
    headers = {'Accept': 'application/json, text/event-stream'}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            report['health_status'] = (await client.get('/healthz')).status_code
            report['ready_status'] = (await client.get('/readyz')).status_code
            initialized = await client.post('/mcp', headers=headers, json={
                'jsonrpc':'2.0','id':1,'method':'initialize',
                'params':{'protocolVersion':'2025-06-18','capabilities':{},
                          'clientInfo':{'name':'probe','version':'1'}}})
            report['initialize_status'] = initialized.status_code
            report['initialize_result'] = initialized.json()
            listed = await client.post('/mcp', headers=headers, json={
                'jsonrpc':'2.0','id':2,'method':'tools/list'})
            report['tools_status'] = listed.status_code
            report['tools_result'] = listed.json()
            called = await client.post('/mcp', headers=headers, json={
                'jsonrpc':'2.0','id':3,'method':'tools/call',
                'params':{'name':'probe_tool','arguments':{}}})
            report['tool_status'] = called.status_code
            report['tool_result'] = called.json()
            oversized = await client.post('/mcp', headers={**headers,'Content-Type':'application/json'},
                                          content='x'*65537)
            report['oversize_status'] = oversized.status_code
            report['lifespan_starts'] = state['lifespan_starts']
    report['ready_after_shutdown'] = state['ready']
    target = Path(__file__).with_name('mcp_api_probe_results.json')
    target.write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'signatures'}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
