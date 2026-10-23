"""Local setup configuration and isolated HTTP error handling; no provider calls."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
from pathlib import Path
import stat
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "webui_setup", ROOT / "scripts/openwebui.py"
)
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)


def test_one_time_credentials_copy_uses_new_ports_and_keeps_source(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("INFOMANIAK_API_KEY", raising=False)
    source = tmp_path / "dateninfrastruktur-agentic-bi-demo-001"
    target = tmp_path / "dateninfrastruktur-agentic-bi-demo-002"
    source.mkdir()
    target.mkdir()
    previous = "INFOMANIAK_API_KEY='literal-$key'\nOPENWEBUI_ADMIN_PASSWORD='private-password'\nWEBUI_SECRET_KEY='private-signing-key'\nOPEN_WEBUI_HOST_PORT='3002'\nAGENTIC_BI_HOST_PORT='8002'\nCUBE_SQL_PASSWORD='not-copied'\n"
    (source / ".env").write_text(previous)
    (target / ".env.example").write_text((ROOT / ".env.example").read_text())
    values = setup.prepare_env(target)
    assert values["INFOMANIAK_API_KEY"] == "literal-$key"
    assert values["OPENWEBUI_ADMIN_PASSWORD"] == "private-password"
    assert values["WEBUI_SECRET_KEY"] == "private-signing-key"
    assert values["OPEN_WEBUI_HOST_PORT"] == "3003"
    assert values["AGENTIC_BI_HOST_PORT"] == "8003"
    assert values["OPENWEBUI_MODEL_BASE"] == "Qwen/Qwen3.8-27B-FP8"
    assert "CUBE_SQL_PASSWORD" not in setup.read_env(target / ".env")
    assert stat.S_IMODE((target / ".env").stat().st_mode) == 0o600
    assert (source / ".env").read_text() == previous
    initial = (target / ".env").read_bytes()
    (source / ".env").write_text("INFOMANIAK_API_KEY='changed-source-key'\n")
    assert setup.prepare_env(target)["INFOMANIAK_API_KEY"] == "literal-$key"
    assert (target / ".env").read_bytes() == initial


def test_existing_explicit_env_wins_over_machine_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("INFOMANIAK_API_KEY='explicit-repo-key'\n")
    monkeypatch.setenv("INFOMANIAK_API_KEY", "machine-key")
    assert setup.load_env(tmp_path)["INFOMANIAK_API_KEY"] == "explicit-repo-key"


def test_env_symlink_is_not_overwritten(tmp_path):
    source = tmp_path / "credentials"
    source.write_text("private")
    (tmp_path / ".env").symlink_to(source)
    with pytest.raises(RuntimeError, match="Symlink"):
        setup.prepare_env(tmp_path)
    assert source.read_text() == "private"


@pytest.mark.parametrize(
    "mutation",
    [
        {"INFOMANIAK_API_KEY": ""},
        {"OPEN_WEBUI_HOST_PORT": "0"},
        {"AGENTIC_BI_HOST_PORT": "65536"},
        {"OPEN_WEBUI_HOST_PORT": "not-a-port"},
        {"AGENTIC_BI_HOST_PORT": "3003"},
    ],
)
def test_invalid_configuration_fails_before_docker(mutation):
    values = setup.read_env(ROOT / ".env.example")
    values.update(
        INFOMANIAK_API_KEY="private-key",
        OPENWEBUI_ADMIN_PASSWORD="private-password",
        WEBUI_SECRET_KEY="private-signing-key",
    )
    values.update(mutation)
    with pytest.raises(RuntimeError) as error:
        setup.validate_env(values)
    assert "private-" not in str(error.value)


@contextmanager
def failing_http_server(body):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_http_failures_do_not_publish_credentials():
    with failing_http_server(b'{"detail":"provider key private-token"}') as base:
        with pytest.raises(RuntimeError) as error:
            setup.api(base, "GET", "/config")
    assert str(error.value) == "OpenWebUI GET /config: HTTP 500."
    assert error.value.__cause__ is None


def test_missing_base_model_is_rejected_even_if_workspace_card_exists(monkeypatch):
    """Isolated setup failure; this does not replace an MCP/engine integration."""
    values = setup.read_env(ROOT / ".env.example")
    values["INFOMANIAK_API_KEY"] = "private-key"
    responses = {
        "/api/config": dict(features=dict(auth=True, enable_signup=False)),
        "/ollama/config": dict(ENABLE_OLLAMA_API=False),
        "/api/v1/tasks/config": dict(ENABLE_FOLLOW_UP_GENERATION=False),
        "/openai/config": dict(
            ENABLE_OPENAI_API=True,
            OPENAI_API_BASE_URLS=[values["INFOMANIAK_API_BASE_URL"]],
            OPENAI_API_KEYS=[values["INFOMANIAK_API_KEY"]],
        ),
        "/api/v1/configs/tool_servers": dict(
            TOOL_SERVER_CONNECTIONS=[setup.mcp_connection()]
        ),
        "/api/v1/configs/tool_servers/verify": dict(
            status=True, specs=[dict(name=n) for n in ("search", "inspect", "analyse")]
        ),
        "/api/v1/models/export": [setup.model_payload(values)],
        "/api/v1/configs/models": dict(DEFAULT_MODELS=setup.MODEL_ID),
        "/api/models": dict(data=[dict(id=setup.MODEL_ID)]),
    }
    monkeypatch.setattr(
        setup, "api", lambda base, method, path, *a, **kw: responses[path]
    )
    with pytest.raises(RuntimeError, match="wird vom Provider nicht angeboten"):
        setup.check("http://unused", "private-token", values)


def test_prompt_model_and_filter_use_our_public_contract():
    connection = setup.mcp_connection()
    assert connection["config"]["function_name_filter_list"] == "search,inspect,analyse"
    values = setup.read_env(ROOT / ".env.example")
    payload = setup.model_payload(values)
    assert payload["params"]["function_calling"] == "native"
    assert payload["meta"]["toolIds"] == ["server:mcp:" + setup.MODEL_ID]
    prompt = payload["params"]["system"]
    assert "require_same_reference_date=true" in prompt
    assert "mean_annual_totals" in prompt
    assert all(
        tool not in prompt
        for tool in ("run_semantic_query", "render_semantic_chart", "run_r_analysis")
    )
    examples = [
        json.loads(line)
        for line in prompt.splitlines()
        if line.startswith('{"request"')
    ]
    from slayer_app.contracts import AnalysisRequest

    assert len(examples) == 2
    for example in examples:
        AnalysisRequest.model_validate(example["request"])


def test_live_evidence_reads_only_correlated_analysis_outputs():
    # Minimal public envelopes derived from the two real v0.12.3 chat traces.
    success = dict(
        ok=True, request_id="positive", data=dict(rows=[dict(ratio=649.6804637625776)])
    )
    refusal = dict(
        ok=False, request_id="negative", error=dict(code="E_REFERENCE_DATE_UNKNOWN")
    )
    output = [
        dict(type="function_call", call_id="a", name="server_analyse"),
        dict(type="function_call", call_id="b", name="server_analyse"),
        dict(
            type="function_call_output",
            call_id="a",
            output=[dict(type="input_text", text=json.dumps(success))],
        ),
        dict(
            type="function_call_output",
            call_id="b",
            output=[
                dict(
                    type="input_text",
                    text=json.dumps(
                        dict(error=str([dict(type="text", text=json.dumps(refusal))]))
                    ),
                )
            ],
        ),
        dict(
            type="function_call_output",
            call_id="unrelated",
            output=[dict(type="input_text", text=json.dumps(success))],
        ),
        dict(
            type="message", content=[dict(type="output_text", text=json.dumps(success))]
        ),
    ]
    assert setup.analysis_results(output) == [success, refusal]
    assert setup.analysis_results(output[-2:]) == []
