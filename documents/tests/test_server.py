"""Real MCP calls over Streamable HTTP (no mocks)."""

import json

from starlette.testclient import TestClient

from documents_mcp.corpus import Corpus
from documents_mcp.server import create_app
from test_corpus import CATALOG, CORPUS, RULES, restricted_catalog

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Host": "localhost:8000"}
TOOLS = {"catalog", "search_laws", "get_section", "get_changes", "search_decisions", "get_decision"}


def rpc(client, method, params, number=1):
    response = client.post("/mcp", headers=HEADERS, json=dict(jsonrpc="2.0", id=number, method=method, params=params))
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_tools_and_call():
    with TestClient(create_app(Corpus(CATALOG, CORPUS, RULES)), base_url="http://localhost:8000") as client:
        ready = client.get("/readyz").json()
        assert ready["acts"] == ["614.61", "614.62", "733.11"] and not ready["per_person_access"]
        rpc(client, "initialize", dict(protocolVersion="2025-06-18", capabilities={},
                                       clientInfo=dict(name="test", version="0")))
        assert {t["name"] for t in rpc(client, "tools/list", {}, 2)["tools"]} == TOOLS
        result = rpc(client, "tools/call", dict(name="get_section", arguments=dict(act="733.11", section="3")), 3)
        data = json.loads(result["content"][0]["text"])
        assert not result["isError"] and data["ok"] and "Motorfahrzeugkontrolle" in data["text"]
        error = rpc(client, "tools/call", dict(name="get_section", arguments=dict(act="1.1", section="1")), 4)
        assert error["isError"] and "nicht im Bestand" in json.loads(error["content"][0]["text"])["error"]


def test_person_only_with_key(tmp_path):
    corpus = Corpus(restricted_catalog(tmp_path), CORPUS, RULES, tmp_path / "access")
    (tmp_path / "access").mkdir(exist_ok=True)
    (tmp_path / "access/grants.yaml").write_text("bgs: [group:intern, person:änne@so.ch]\n", encoding="utf-8")
    app = create_app(corpus, api_key="secret")
    with TestClient(app, base_url="http://localhost:8000") as client:
        def locked(headers):
            response = client.post("/mcp", headers=dict(HEADERS, **headers), json=dict(
                jsonrpc="2.0", id=1, method="tools/call",
                params=dict(name="get_section", arguments=dict(act="733.11", section="3"))))
            return response.json()["result"]["isError"]

        assert client.get("/readyz").json()["per_person_access"]
        assert locked({}) is True                                                # anonymous: open only
        assert locked({"X-User-Groups": "intern"}) is True                       # groups without key do not count
        assert locked({"Authorization": "Bearer wrong", "X-User-Groups": "intern"}) is True
        assert locked({"Authorization": "Bearer secret", "X-User-Groups": "Alle,intern"}) is False
        assert locked({"Authorization": "Bearer secret", "X-User-Email": "%C3%A4nne@so.ch"}) is False
        assert locked({"Authorization": "Bearer secret", "X-User-Email": "otto@so.ch"}) is True
