#!/usr/bin/env python3
"""Local Docker/OpenWebUI setup. Standard library only; Python >= 3.9."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "agentic-bi-solothurn-slayer"
MODEL_NAME = "Agentic BI – SLayer"
MCP_URL = "http://agentic-bi-mcp:8000/mcp"
COPIED_KEYS = (
    "INFOMANIAK_API_KEY",
    "INFOMANIAK_API_BASE_URL",
    "OPENWEBUI_ADMIN_NAME",
    "OPENWEBUI_ADMIN_EMAIL",
    "OPENWEBUI_ADMIN_PASSWORD",
    "WEBUI_SECRET_KEY",
)


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("Ungültige .env: KEY=value erwartet.")
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise RuntimeError("Ungültiger Variablenname in .env.")
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("\\'", "'")
        elif value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                raise RuntimeError("Ungültige Anführungszeichen in .env.") from None
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def prepare_env(root: Path = ROOT) -> dict[str, str]:
    path = root / ".env"
    if path.is_symlink():
        raise RuntimeError(".env darf kein Symlink sein.")
    if not path.exists():
        values = read_env(root / ".env.example")
        source = root.parent / "dateninfrastruktur-agentic-bi-demo-001" / ".env"
        previous = read_env(source)
        for key in COPIED_KEYS:
            if previous.get(key):
                values[key] = previous[key]
        for key in ("OPENWEBUI_ADMIN_PASSWORD", "WEBUI_SECRET_KEY"):
            if not values.get(key):
                values[key] = secrets.token_hex(32)
        if any("\n" in v or "\r" in v for v in values.values()):
            raise RuntimeError("Mehrzeilige .env-Werte werden nicht unterstützt.")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            # Compose single quotes preserve dollars and literal backslashes.
            for key, value in values.items():
                escaped = value.replace("'", "\\'")
                stream.write(f"{key}='{escaped}'\n")
        print(
            "Lokale .env angelegt; vorhandene WebUI-Zugangsdaten aus Demo 001 übernommen."
            if previous
            else "Lokale .env angelegt; INFOMANIAK_API_KEY ergänzen.",
            flush=True,
        )
    path.chmod(0o600)
    return load_env(root)


def load_env(root: Path = ROOT) -> dict[str, str]:
    values = dict(os.environ)
    for key, value in read_env(root / ".env").items():
        if value or key not in values:
            values[key] = value
    return values


def validate_env(values):
    for key in (
        "INFOMANIAK_API_KEY",
        "INFOMANIAK_API_BASE_URL",
        "OPENWEBUI_MODEL_BASE",
        "OPENWEBUI_ADMIN_EMAIL",
        "OPENWEBUI_ADMIN_PASSWORD",
        "WEBUI_SECRET_KEY",
    ):
        if not values.get(key, "").strip():
            raise RuntimeError(f"{key} fehlt in der lokalen .env.")
    ports = []
    for key, default in (
        ("OPEN_WEBUI_HOST_PORT", "3003"),
        ("AGENTIC_BI_HOST_PORT", "8003"),
    ):
        try:
            port = int(values.get(key, default))
        except ValueError:
            raise RuntimeError(f"{key} muss eine Portnummer sein.") from None
        if not 1 <= port <= 65535:
            raise RuntimeError(f"{key} muss zwischen 1 und 65535 liegen.")
        ports.append(port)
    if ports[0] == ports[1]:
        raise RuntimeError("OpenWebUI und MCP benötigen unterschiedliche Hostports.")


def api(base, method, path, payload=None, token=None, *, tolerate=()):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(8 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status in tolerate:
            return None
        # Bodies and exception text can contain credentials. Keep them private.
        raise RuntimeError(f"OpenWebUI {method} {path}: HTTP {status}.") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError(
            f"OpenWebUI {method} {path}: Verbindung fehlgeschlagen."
        ) from None
    if len(body) > 8 * 1024 * 1024:
        raise RuntimeError("OpenWebUI-Antwort überschreitet die Einrichtungsgrenze.")
    try:
        return json.loads(body) if body else None
    except ValueError:
        raise RuntimeError("OpenWebUI lieferte kein gültiges JSON.") from None


def wait_ready(url, label, seconds=600):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise RuntimeError(label + " wurde nicht rechtzeitig bereit.")


def authenticate(base, values):
    credentials = dict(
        email=values["OPENWEBUI_ADMIN_EMAIL"],
        password=values["OPENWEBUI_ADMIN_PASSWORD"],
    )
    session = api(
        base, "POST", "/api/v1/auths/signin", credentials, tolerate=(400, 401, 403)
    )
    if session is None:
        session = api(
            base,
            "POST",
            "/api/v1/auths/signup",
            dict(
                credentials,
                name=values.get("OPENWEBUI_ADMIN_NAME", "Admin"),
                profile_image_url="/user.png",
            ),
        )
    if session.get("role") != "admin":
        raise RuntimeError("Das konfigurierte Konto hat keine Adminrechte.")
    return session["token"]


def mcp_connection():
    return dict(
        url=MCP_URL,
        path="",
        type="mcp",
        auth_type="none",
        headers=None,
        key="",
        config=dict(
            enable=True,
            function_name_filter_list="search,inspect,analyse",
            access_grants=[
                dict(principal_type="user", principal_id="*", permission="read")
            ],
        ),
        info=dict(
            id=MODEL_ID,
            name="Agentic BI Kanton Solothurn – SLayer",
            description="Geprüfte Jahresdaten und fachliche Regeln über SLayer.",
        ),
        spec_type="url",
        spec="",
    )


def model_payload(values):
    return dict(
        id=MODEL_ID,
        name=MODEL_NAME,
        base_model_id=values["OPENWEBUI_MODEL_BASE"],
        is_active=True,
        meta=dict(
            description="Solothurner Jahresdaten mit nativer SLayer-Berechnung und geprüften Fachgrenzen.",
            profile_image_url="/static/favicon.png",
            toolIds=["server:mcp:" + MODEL_ID],
            capabilities=dict(
                vision=False,
                file_upload=True,
                file_context=True,
                web_search=False,
                image_generation=False,
                code_interpreter=False,
                terminal=False,
                usage=False,
                citations=True,
                status_updates=True,
                memory=False,
                builtin_tools=False,
            ),
        ),
        params=dict(
            system=(ROOT / "openwebui/system-prompt.md").read_text(encoding="utf-8"),
            temperature=0.1,
            function_calling="native",
            custom_params=dict(chat_template_kwargs=dict(enable_thinking=False)),
        ),
        access_grants=[
            dict(principal_type="user", principal_id="*", permission="read")
        ],
    )


def configure(base, token, values):
    api(
        base,
        "POST",
        "/openai/config/update",
        dict(
            ENABLE_OPENAI_API=True,
            OPENAI_API_BASE_URLS=[values["INFOMANIAK_API_BASE_URL"]],
            OPENAI_API_KEYS=[values["INFOMANIAK_API_KEY"]],
            OPENAI_API_CONFIGS={
                "0": dict(
                    enable=True,
                    tags=[],
                    prefix_id="",
                    model_ids=[],
                    connection_type="external",
                    auth_type="bearer",
                    passthrough_params=[],
                )
            },
        ),
        token,
    )
    api(
        base,
        "POST",
        "/ollama/config/update",
        dict(
            ENABLE_OLLAMA_API=False,
            OLLAMA_BASE_URLS=["http://host.docker.internal:11434"],
            OLLAMA_API_CONFIGS={"0": dict(enable=False)},
        ),
        token,
    )
    current = api(base, "GET", "/api/v1/configs/tool_servers", token=token)
    connections = [
        c
        for c in current.get("TOOL_SERVER_CONNECTIONS", []) or []
        if (c.get("info") or {}).get("id") != MODEL_ID
    ]
    api(
        base,
        "POST",
        "/api/v1/configs/tool_servers",
        dict(TOOL_SERVER_CONNECTIONS=connections + [mcp_connection()]),
        token,
    )
    api(
        base,
        "POST",
        "/api/v1/models/import",
        dict(models=[model_payload(values)]),
        token,
    )
    current = api(base, "GET", "/api/v1/configs/models", token=token)
    # Preserve unrelated preferences while selecting this stack's model.
    current.update(
        DEFAULT_MODELS=MODEL_ID,
        DEFAULT_PINNED_MODELS=MODEL_ID,
        MODEL_ORDER_LIST=[MODEL_ID]
        + [x for x in current.get("MODEL_ORDER_LIST", []) if x != MODEL_ID],
    )
    api(base, "POST", "/api/v1/configs/models", current, token)


def check(base, token, values):
    features = api(base, "GET", "/api/config", token=token).get("features", {})
    ollama = api(base, "GET", "/ollama/config", token=token)
    tasks = api(base, "GET", "/api/v1/tasks/config", token=token)
    if (
        features.get("auth") is not True
        or features.get("enable_signup") is not False
        or ollama.get("ENABLE_OLLAMA_API") is not False
        or tasks.get("ENABLE_FOLLOW_UP_GENERATION") is not False
    ):
        raise RuntimeError(
            "WebUI-Anmeldung oder deaktivierte Zusatzfunktionen sind falsch konfiguriert."
        )
    provider = api(base, "GET", "/openai/config", token=token)
    if (
        provider.get("ENABLE_OPENAI_API") is not True
        or provider.get("OPENAI_API_BASE_URLS") != [values["INFOMANIAK_API_BASE_URL"]]
        or provider.get("OPENAI_API_KEYS") != [values["INFOMANIAK_API_KEY"]]
    ):
        raise RuntimeError("Providerkonfiguration wurde nicht korrekt gespeichert.")
    current = api(base, "GET", "/api/v1/configs/tool_servers", token=token)
    matches = [
        c
        for c in current.get("TOOL_SERVER_CONNECTIONS", [])
        if (c.get("info") or {}).get("id") == MODEL_ID
    ]
    if len(matches) != 1 or matches[0]["url"] != MCP_URL:
        raise RuntimeError("MCP-Verbindung wurde nicht eindeutig gespeichert.")
    verified = api(
        base, "POST", "/api/v1/configs/tool_servers/verify", mcp_connection(), token
    )
    specs = verified.get("specs", [])
    if not verified.get("status") or {s["name"] for s in specs} != {
        "search",
        "inspect",
        "analyse",
    }:
        raise RuntimeError(
            "OpenWebUI erreicht nicht genau die drei erwarteten MCP-Werkzeuge."
        )
    exported = api(base, "GET", "/api/v1/models/export", token=token)
    models = exported if isinstance(exported, list) else exported.get("data", [])
    expected = model_payload(values)
    saved = [m for m in models if m["id"] == MODEL_ID]
    if (
        len(saved) != 1
        or any(
            saved[0].get(k) != expected[k]
            for k in ("name", "base_model_id", "is_active")
        )
        or any(
            saved[0].get(section, {}).get(key) != value
            for section in ("meta", "params")
            for key, value in expected[section].items()
        )
    ):
        raise RuntimeError("Workspace-Modell wurde nicht korrekt gespeichert.")
    defaults = api(base, "GET", "/api/v1/configs/models", token=token)
    if defaults.get("DEFAULT_MODELS") != MODEL_ID:
        raise RuntimeError("Workspace-Modell ist nicht die instanzweite Vorauswahl.")
    available = api(base, "GET", "/api/models", token=token)
    ids = {m["id"] for m in available.get("data", [])}
    if values["OPENWEBUI_MODEL_BASE"] not in ids:
        raise RuntimeError("OPENWEBUI_MODEL_BASE wird vom Provider nicht angeboten.")
    if MODEL_ID not in ids:
        raise RuntimeError("Workspace-Modell ist beim Provider nicht verfügbar.")
    print(
        "Provider, Modellkarte und drei native MCP-Werkzeuge verifiziert.", flush=True
    )
    return dict(
        ok=True,
        model_id=MODEL_ID,
        base_model_id=values["OPENWEBUI_MODEL_BASE"],
        tool_names=sorted(s["name"] for s in specs),
        tools_verified_by_openwebui=True,
        provider_configured=True,
        native_function_calling=True,
        login_required=True,
        signup_enabled=False,
        ollama_enabled=False,
        follow_up_generation_enabled=False,
    )


def analysis_results(output):
    """Read actual tool outputs, never numbers/codes merely written by the LLM."""
    call_ids = {
        item["call_id"]
        for item in output
        if item.get("type") == "function_call"
        and item.get("name", "").endswith("_analyse")
    }
    results = []
    for item in output:
        if (
            item.get("type") != "function_call_output"
            or item.get("call_id") not in call_ids
        ):
            continue
        for part in item.get("output", []):
            if part.get("type") != "input_text":
                continue
            try:
                result = json.loads(part["text"])
                # v0.12.3 wraps MCP isError content in a Python-list string.
                if isinstance(result.get("error"), str):
                    for content in ast.literal_eval(result["error"]):
                        if content.get("type") == "text":
                            results.append(json.loads(content["text"]))
                else:
                    results.append(result)
            except (ValueError, SyntaxError, TypeError, AttributeError, KeyError):
                continue
    return results


def live_check(base, token, selected=None, saved_chats=None):
    cases = [
        (
            "F04",
            "Wie viele Personenwagen und Motorräder zusammen gibt es 2025 im Kanton Solothurn je 1000 Einwohner? "
            "Nutze search, inspect und analyse und nenne den Stichtagshinweis. Gib das Verhältnis mit zwei Nachkommastellen aus. Antworte kurz.",
        ),
        (
            "N02",
            "Prüfe mit analyse das Verhältnis von Personenwagen plus Motorrädern zur Bevölkerung im Jahr 2025 "
            "bei zwingend identischem Beobachtungsstichtag. Setze im Request require_same_reference_date=true. "
            "Führe die Prüfung wirklich aus, lockere die Bedingung nach einer Ablehnung nicht und erkläre die Ablehnung kurz.",
        ),
    ]
    reports = []
    for case, prompt in cases:
        if selected and case not in selected:
            continue
        if saved_chats and case in saved_chats:
            chat = api(base, "GET", "/api/v1/chats/" + saved_chats[case], token=token)
            assistant_id = chat["chat"]["history"]["currentId"]
        else:
            user_id, assistant_id = str(uuid4()), str(uuid4())
            user = dict(
                id=user_id,
                parentId=None,
                childrenIds=[assistant_id],
                role="user",
                content=prompt,
                models=[MODEL_ID],
                timestamp=int(time.time()),
            )
            assistant = dict(
                id=assistant_id,
                parentId=user_id,
                childrenIds=[],
                role="assistant",
                content="",
                model=MODEL_ID,
                done=False,
            )
            chat = api(
                base,
                "POST",
                "/api/v1/chats/new",
                dict(
                    chat=dict(
                        title="SLayer-Abnahme – " + case,
                        models=[MODEL_ID],
                        messages=[user, assistant],
                        history=dict(
                            messages={user_id: user, assistant_id: assistant},
                            currentId=assistant_id,
                        ),
                        timestamp=int(time.time() * 1000),
                    )
                ),
                token,
            )
            api(
                base,
                "POST",
                "/api/chat/completions",
                dict(
                    model=MODEL_ID,
                    stream=True,
                    messages=[dict(role="user", content=prompt)],
                    chat_id=chat["id"],
                    id=assistant_id,
                    tool_ids=["server:mcp:" + MODEL_ID],
                    params=dict(function_calling="native", max_tokens=4000),
                ),
                token,
            )
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            saved = api(base, "GET", "/api/v1/chats/" + chat["id"], token=token)
            message = saved["chat"]["history"]["messages"].get(assistant_id, {})
            if message.get("done") or message.get("error"):
                break
            time.sleep(2)
        else:
            api(base, "POST", "/api/tasks/chat/" + chat["id"] + "/stop", token=token)
            raise RuntimeError("Live-Chat wurde nicht rechtzeitig fertig: " + case)
        if message.get("error"):
            raise RuntimeError("Live-Chat meldet einen Modellfehler: " + case)
        output = message.get("output", [])
        calls = [
            item.get("name", "")
            for item in output
            if item.get("type") == "function_call"
        ]
        if not all(
            any(name.endswith("_" + tool) for name in calls)
            for tool in ("search", "inspect", "analyse")
        ):
            raise RuntimeError(
                "Live-Chat hat nicht alle drei Werkzeuge ausgeführt: " + case
            )
        results = analysis_results(output)
        text = message.get("content") or "\n".join(
            part.get("text", "")
            for item in output
            if item.get("type") == "message"
            for part in item.get("content", [])
        )
        if case == "F04":
            results = [
                result
                for result in results
                if result.get("ok") is True
                and any(
                    value == 649.6804637625776
                    for row in result.get("data", {}).get("rows", [])
                    for value in row.values()
                )
                and "SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN"
                in json.dumps(result.get("data", {}).get("notices", []))
            ]
            if not results:
                raise RuntimeError(
                    "Live-Chat enthält nicht den geprüften F04-Wert samt Stichtagshinweis."
                )
            displayed = [
                float(value.replace(",", "."))
                for value in re.findall(r"\b\d+[.,]\d+\b", text)
            ]
            if not any(
                abs(value - 649.6804637625776) <= 0.051 for value in displayed
            ) or not re.search(r"Stichtag|Beobachtungszeitpunkt", text, re.I):
                raise RuntimeError(
                    "F04-Antwort gibt Zahl und Stichtaghinweis nicht wieder."
                )
        else:
            results = [
                result
                for result in results
                if result.get("ok") is False
                and result.get("error", {}).get("code") == "E_REFERENCE_DATE_UNKNOWN"
            ]
            if not results or "E_REFERENCE_DATE_UNKNOWN" not in text:
                raise RuntimeError(
                    "Live-Chat enthält nicht die erwartete fachliche Ablehnung."
                )
        reports.append(
            dict(
                case=case,
                ok=True,
                chat_id=chat["id"],
                tool_calls=calls,
                result_verified=True,
                answer_verified=bool(text),
                request_ids=[result["request_id"] for result in results],
                evidence=(
                    dict(
                        value=649.6804637625776,
                        notice="SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN",
                    )
                    if case == "F04"
                    else dict(error_code="E_REFERENCE_DATE_UNKNOWN")
                ),
            )
        )
        print(
            "Live-Chat " + case + ": Modell, MCP-Aufruf und Antwort geprüft.",
            flush=True,
        )
    return dict(ok=True, cases=reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("start", "seed", "check", "live-check"))
    parser.add_argument("--case", action="append", choices=("F04", "N02"))
    parser.add_argument(
        "--reuse-chat",
        action="append",
        default=[],
        metavar="CASE=UUID",
        help="Einen gespeicherten Abnahmechat erneut prüfen, ohne Provider-Aufruf.",
    )
    args = parser.parse_args()
    if (args.case or args.reuse_chat) and args.operation != "live-check":
        parser.error("--case und --reuse-chat gelten nur für live-check.")
    saved_chats = {}
    for item in args.reuse_chat:
        if not re.fullmatch(r"(F04|N02)=[0-9a-f-]{36}", item):
            parser.error("--reuse-chat erwartet F04=UUID oder N02=UUID.")
        case, chat_id = item.split("=", 1)
        saved_chats[case] = chat_id
    values = prepare_env() if args.operation == "start" else load_env()
    validate_env(values)
    base = "http://127.0.0.1:" + values.get("OPEN_WEBUI_HOST_PORT", "3003")
    if args.operation == "start":
        if not shutil.which("docker"):
            raise RuntimeError("Docker und Docker Compose werden benötigt.")
        for command in (
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            ["docker", "compose", "version"],
        ):
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["docker", "compose", "config", "--quiet"], cwd=ROOT, env=values, check=True
        )
        subprocess.run(
            ["docker", "compose", "up", "--build", "-d"],
            cwd=ROOT,
            env=values,
            check=True,
        )
    wait_ready(
        "http://127.0.0.1:" + values.get("AGENTIC_BI_HOST_PORT", "8003") + "/readyz",
        "MCP",
    )
    wait_ready(base + "/health", "OpenWebUI")
    token = authenticate(base, values)
    if args.operation in ("start", "seed"):
        configure(base, token, values)
    report = (
        live_check(base, token, args.case, saved_chats)
        if args.operation == "live-check"
        else check(base, token, values)
    )
    target = (
        ROOT
        / "build"
        / (
            "openwebui-live.json"
            if args.operation == "live-check"
            else "openwebui-check.json"
        )
    )
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        "OpenWebUI bereit: "
        + base.replace("127.0.0.1", "localhost")
        + "; Zugangsdaten in der lokalen .env.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(
            str(error)
            if isinstance(error, RuntimeError)
            else "Docker-Start fehlgeschlagen; docker compose ps und Logs prüfen.",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
