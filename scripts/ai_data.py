#!/usr/bin/env python3
"""Prototype "AI-ready data": start demo 002 and add the documents server.

scripts/openwebui.py of demo 002 stays unchanged and is only used here. The compose extension comes in via
COMPOSE_FILE (docker-compose.yml:compose.ai-data.yml) from the local .env.

  python3 scripts/ai_data.py start     # start demo 002 + documents server + model "Daten + Dokumente"
  python3 scripts/ai_data.py seed      # set up our part again
  python3 scripts/ai_data.py check     # overall check: repo, tests, services, OpenWebUI (no provider costs)
  python3 scripts/ai_data.py ask "…"   # ask a question as a saved chat (costs a provider call)
  python3 scripts/ai_data.py catalog   # build the catalog (offline) and show the most frequent gaps
  python3 scripts/ai_data.py access grants|audit   # show rights (grants: access/grants.yaml)

Messages are German, like those of demo 002.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import openwebui as demo  # noqa: E402

DOCUMENTS_ID = "ai-data-documents"
DOCUMENTS_URL = "http://documents-mcp:8000/mcp"
DOCUMENTS_TOOLS = {"catalog", "search_laws", "get_section", "get_changes", "search_decisions", "get_decision"}
MODEL_ID = "ai-data"
MODEL_NAME = "KI-taugliche Daten – Daten + Dokumente"
TOOL_IDS = ["server:mcp:" + demo.MODEL_ID, "server:mcp:" + DOCUMENTS_ID]
# Test group in OpenWebUI: members may read the RRB distribution list (access/grants.yaml). Members by hand.
TEST_GROUP = "Staatskanzlei"
# Everything outside these paths belongs to demo 002 and must match its state (main).
OWN_PATHS = ("documents/", "corpus/", "catalog/", "rules/", "access/", "compose.ai-data.yml", "scripts/ai_data.py",
             "openwebui/ai-data-prompt.md", "KI-DATEN.md")
SERVICES = {"open-webui", "agentic-bi-mcp", "documents-mcp"}
DEMO_DEFAULT_MODEL = "Workspace-Modell ist nicht die instanzweite Vorauswahl."
# OpenWebUI fills in e-mail and groups of the signed-in person on every tool call.
PERSON_HEADERS = {"X-User-Email": "{{USER_EMAIL}}", "X-User-Groups": "{{USER_GROUPS}}"}
DATAPORTAL_CURRENT = "https://s3.eu-central-1.amazonaws.com/ch.so.daten-test/current.json"


def documents_connection(values: dict) -> dict:
    connection = demo.mcp_connection()
    connection.update(
        url=DOCUMENTS_URL, auth_type="bearer", key=values["DOCUMENTS_API_KEY"], headers=PERSON_HEADERS,
        info=dict(id=DOCUMENTS_ID, name="Dokumente und Katalog (BGS, RRB)",
                  description="Gemeinsamer Katalog für Daten und Dokumente, Erlasse mit Fassungen, "
                              "Regierungsratsbeschlüsse."),
    )
    connection["config"] = dict(connection["config"], function_name_filter_list=",".join(sorted(DOCUMENTS_TOOLS)))
    return connection


def model(values: dict) -> dict:
    payload = demo.model_payload(values)
    system = payload["params"]["system"] + "\n\n" + (ROOT / "openwebui/ai-data-prompt.md").read_text(encoding="utf-8")
    payload.update(id=MODEL_ID, name=MODEL_NAME)
    payload["meta"] = dict(payload["meta"],
                           description="Zahlen aus dem Datenportal, Regeln aus dem BGS und Regierungsratsbeschlüsse "
                                       "über einen gemeinsamen Katalog.",
                           toolIds=TOOL_IDS)
    payload["params"] = dict(payload["params"], system=system)
    return payload


def seed(base: str, token: str, values: dict) -> None:
    current = demo.api(base, "GET", "/api/v1/configs/tool_servers", token=token)
    others = [c for c in current.get("TOOL_SERVER_CONNECTIONS", []) or []
              if (c.get("info") or {}).get("id") != DOCUMENTS_ID]
    demo.api(base, "POST", "/api/v1/configs/tool_servers",
             dict(TOOL_SERVER_CONNECTIONS=others + [documents_connection(values)]), token)
    demo.api(base, "POST", "/api/v1/models/import", dict(models=[model(values)]), token)
    defaults = demo.api(base, "GET", "/api/v1/configs/models", token=token)
    defaults.update(
        DEFAULT_MODELS=MODEL_ID,
        DEFAULT_PINNED_MODELS=",".join([MODEL_ID, demo.MODEL_ID]),
        MODEL_ORDER_LIST=[MODEL_ID] + [x for x in defaults.get("MODEL_ORDER_LIST", []) if x != MODEL_ID],
    )
    demo.api(base, "POST", "/api/v1/configs/models", defaults, token)
    groups = demo.api(base, "GET", "/api/v1/groups/", token=token)
    if not any(g.get("name") == TEST_GROUP for g in groups):
        demo.api(base, "POST", "/api/v1/groups/create", dict(
            name=TEST_GROUP, description="Test der Rechte: Mitglieder sehen den Verteiler der RRB (access/grants.yaml)."),
            token)


def verify(base: str, token: str, values: dict) -> None:
    checked = demo.api(base, "POST", "/api/v1/configs/tool_servers/verify", documents_connection(values), token)
    names = {s["name"] for s in checked.get("specs", [])}
    if not checked.get("status") or names != DOCUMENTS_TOOLS:
        raise RuntimeError(f"OpenWebUI erreicht nicht die {len(DOCUMENTS_TOOLS)} Dokumente-Werkzeuge "
                           f"(gefunden: {sorted(names)}).")
    stored = demo.api(base, "GET", "/api/v1/configs/tool_servers", token=token).get("TOOL_SERVER_CONNECTIONS") or []
    connection = next((c for c in stored if (c.get("info") or {}).get("id") == DOCUMENTS_ID), {})
    if (connection.get("auth_type"), connection.get("key"), connection.get("headers")) != (
            "bearer", values["DOCUMENTS_API_KEY"], PERSON_HEADERS):
        raise RuntimeError("Dokumente-Verbindung in OpenWebUI ohne Schlüssel oder Person: python3 scripts/ai_data.py seed")
    exported = demo.api(base, "GET", "/api/v1/models/export", token=token)
    models = exported if isinstance(exported, list) else exported.get("data", [])
    saved = [m for m in models if m["id"] == MODEL_ID]
    if len(saved) != 1 or saved[0]["meta"].get("toolIds") != model(values)["meta"]["toolIds"]:
        raise RuntimeError("Modell 'Daten + Dokumente' wurde nicht korrekt gespeichert.")
    if demo.api(base, "GET", "/api/v1/configs/models", token=token).get("DEFAULT_MODELS") != MODEL_ID:
        raise RuntimeError("Modell 'Daten + Dokumente' ist nicht die Vorauswahl.")
    # /api/models also reloads the model cache of OpenWebUI; only then is the model usable in the chat.
    available = {m["id"] for m in demo.api(base, "GET", "/api/models", token=token).get("data", [])}
    if MODEL_ID not in available:
        raise RuntimeError("Modell 'Daten + Dokumente' ist im Chat nicht verfügbar.")


# Overall check ---------------------------------------------------------------------
class Notice(Exception):
    """Not an error, but something worth knowing (e.g. a newer data portal release)."""


def _git(*arguments: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True).stdout


def demo_unchanged() -> str:
    # Base: main of demo 002, in a fork as upstream/main, in the original repository as origin/main.
    ref = next((r for r in ("upstream/main", "origin/main", "main")
                if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", r],
                                  capture_output=True).returncode == 0), None)
    if ref is None:
        raise RuntimeError("Kein main der Demo 002 gefunden (upstream/main, origin/main oder main).")
    base = _git("merge-base", "HEAD", ref).strip()
    changed = [p for p in _git("diff", "--name-only", base).splitlines() if p]
    foreign = [p for p in changed if not p.startswith(OWN_PATHS)]
    if foreign:
        raise RuntimeError("Dateien der Demo 002 verändert: " + ", ".join(foreign))
    return f"{len(changed)} eigene Dateien, keine der Demo 002 verändert (Basis {base[:7]})"


def raw_unchanged() -> str:
    pending = [line for line in _git("status", "--porcelain", "--", "corpus").splitlines() if "/raw/" in line]
    if pending:
        raise RuntimeError(f"Roh-Stufe weicht vom Commit ab ({len(pending)} Dateien), z. B. {pending[0].strip()}")
    return "corpus/*/raw/ entspricht dem Commit"


def tests() -> str:
    run = subprocess.run(["uv", "run", "--group", "dev", "pytest", "-q", "-rs"], cwd=ROOT / "documents",
                         capture_output=True, text=True)
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else run.stderr.strip()
    if run.returncode != 0:
        raise RuntimeError(summary)
    if "skipped" in summary:
        reason = next((line for line in lines if line.startswith("SKIPPED")), "")
        raise Notice(f"{summary} – {reason}")
    return summary


def _containers() -> dict[str, tuple[str, str, str]]:
    output = subprocess.run(["docker", "compose", "ps", "--format", "json"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    containers = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines() if line]
    return {c["Service"]: (c["State"], c.get("Health", ""), c["Image"]) for c in containers}


def services_running(values: dict) -> str:
    deadline = demo.time.monotonic() + 90
    while True:  # freshly started services need a few seconds until their first health check
        status = _containers()
        if not any(health == "starting" for _, health, _ in status.values()) or demo.time.monotonic() > deadline:
            break
        demo.time.sleep(2)
    missing = sorted(SERVICES - {s for s, (state, health, _) in status.items() if state == "running" and health == "healthy"})
    if missing:
        raise RuntimeError("nicht gesund oder nicht gestartet: " + ", ".join(missing))
    expected = next(i for i in subprocess.run(["docker", "compose", "config", "--images"], cwd=ROOT, check=True,
                                              capture_output=True, text=True).stdout.split() if "open-webui" in i)
    if status["open-webui"][2] != expected:
        raise RuntimeError(f"OpenWebUI läuft mit {status['open-webui'][2]}, erwartet {expected}: docker compose up -d")
    return "open-webui, agentic-bi-mcp, documents-mcp laufen und sind gesund"


def catalog_in_service(values: dict) -> str:
    ready = demo.api("http://127.0.0.1:" + values.get("DOCUMENTS_HOST_PORT", "8005"), "GET", "/readyz")
    local = hashlib.sha256((ROOT / "catalog/catalog.json").read_bytes()).hexdigest()
    if ready.get("catalog_sha256") != local:
        raise RuntimeError("Dokumente-Server hat einen anderen Katalog geladen: docker compose up -d --build documents-mcp")
    if not ready.get("per_person_access"):
        raise RuntimeError("Dokumente-Server ohne Schlüssel (nur öffentlich): DOCUMENTS_API_KEY in .env, docker compose up -d")
    if not ready.get("grants_loaded"):
        raise RuntimeError("Dokumente-Server ohne Freigaben: access/ nicht eingebunden (compose.ai-data.yml)")
    if (ROOT / "catalog/datasheets/rrb.yaml").exists() and not ready.get("decisions"):
        raise RuntimeError("Dokumente-Server ohne Regierungsratsbeschlüsse: corpus/rrb/ fehlt (nur lokal), siehe KI-DATEN.md")
    return (f"Dokumente-Server: {ready['datasets']} Datensätze im Katalog, Erlasse {', '.join(ready['acts'])}, "
            f"{ready.get('decisions', 0)} Beschlüsse, Rechte je Person und Freigaben aktiv")


def dataportal_current() -> str:
    catalog = json.loads((ROOT / "catalog/catalog.json").read_text(encoding="utf-8"))
    own = catalog["dct:source"]["dataportal"]["release"]
    try:
        with urllib.request.urlopen(DATAPORTAL_CURRENT, timeout=15) as response:
            current = json.loads(response.read())["releaseId"]
    except OSError as error:
        raise Notice(f"Datenportal nicht erreichbar ({error.__class__.__name__}); Katalog auf Release {own[:8]}")
    if current != own:
        raise Notice(f"neuere Datenportal-Ausgabe {current[:8]} (Katalog: {own[:8]}): "
                     "python3 scripts/ai_data.py catalog --fetch")
    return f"Katalog auf aktueller Datenportal-Ausgabe {own[:8]}, Stand {catalog['dct:modified']}"


def openwebui(base: str, token: str, values: dict) -> str:
    version = demo.api(base, "GET", "/api/config").get("version")
    try:
        demo.check(base, token, values)
    except RuntimeError as error:
        if str(error) != DEMO_DEFAULT_MODEL:
            raise RuntimeError(f"Prüfung der Demo 002: {error}") from None
        # Intended: our model is the default. Repeat the remaining checks of demo 002 after that point here.
        available = {m["id"] for m in demo.api(base, "GET", "/api/models", token=token).get("data", [])}
        if not {values["OPENWEBUI_MODEL_BASE"], demo.MODEL_ID} <= available:
            raise RuntimeError("Basismodell oder Modell der Demo 002 ist beim Provider nicht verfügbar.") from None
    verify(base, token, values)
    return (f"OpenWebUI {version}: Modell der Demo 002 + 3 Daten-Werkzeuge, unser Modell + "
            f"{len(DOCUMENTS_TOOLS)} Dokumente-Werkzeuge")


def overall_check(values: dict) -> bool:
    base = "http://127.0.0.1:" + values.get("OPEN_WEBUI_HOST_PORT", "3003")
    steps = [
        ("Demo 002 unverändert", demo_unchanged),
        ("Roh-Stufe unverändert", raw_unchanged),
        ("Tests", tests),
        ("Dienste", lambda: services_running(values)),
        ("Katalog im Dienst", lambda: catalog_in_service(values)),
        ("OpenWebUI", lambda: openwebui(base, demo.authenticate(base, values), values)),
        ("Datenportal", dataportal_current),
    ]
    failures = 0
    for name, step in steps:
        try:
            print(f"✓ {name}: {step()}", flush=True)
        except Notice as notice:
            print(f"! {name}: {notice}", flush=True)
        except Exception as error:  # report every step, even if an earlier one fails
            failures += 1
            print(f"✗ {name}: {error}", flush=True)
    print("Alles in Ordnung." if not failures else f"{failures} Prüfung(en) fehlgeschlagen.", flush=True)
    return not failures


def ask(base: str, token: str, text: str) -> dict:
    """Ask a question as a saved chat (paid provider call) and evaluate it."""
    user_id, answer_id = str(demo.uuid4()), str(demo.uuid4())
    user = dict(id=user_id, parentId=None, childrenIds=[answer_id], role="user", content=text,
                models=[MODEL_ID], timestamp=int(demo.time.time()))
    answer = dict(id=answer_id, parentId=user_id, childrenIds=[], role="assistant", content="",
                  model=MODEL_ID, done=False)
    chat = demo.api(base, "POST", "/api/v1/chats/new", dict(chat=dict(
        title="Prototyp – " + text[:60], models=[MODEL_ID], messages=[user, answer],
        history=dict(messages={user_id: user, answer_id: answer}, currentId=answer_id),
        timestamp=int(demo.time.time() * 1000))), token)
    demo.api(base, "POST", "/api/chat/completions", dict(
        model=MODEL_ID, stream=True, messages=[dict(role="user", content=text)], chat_id=chat["id"],
        id=answer_id, tool_ids=TOOL_IDS, params=dict(function_calling="native", max_tokens=4000)), token)
    deadline = demo.time.monotonic() + 360
    while demo.time.monotonic() < deadline:
        message = demo.api(base, "GET", "/api/v1/chats/" + chat["id"], token=token)["chat"]["history"]["messages"].get(answer_id, {})
        if message.get("done") or message.get("error"):
            break
        demo.time.sleep(2)
    else:
        demo.api(base, "POST", "/api/tasks/chat/" + chat["id"] + "/stop", token=token)
        raise RuntimeError("Chat wurde nicht rechtzeitig fertig.")
    output = message.get("output", [])
    calls = [(i.get("name", ""), i.get("arguments", "")) for i in output if i.get("type") == "function_call"]
    content = message.get("content") or "\n".join(
        p.get("text", "") for i in output if i.get("type") == "message" for p in i.get("content", []))
    return dict(chat_id=chat["id"], error=message.get("error"), calls=calls, answer=content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("operation", choices=("start", "seed", "check", "ask", "catalog", "access"))
    parser.add_argument("text", nargs="?", help="Frage für 'ask', Befehl für 'access' (grants|audit)")
    args, rest = parser.parse_known_args()
    python = str(ROOT / "documents/.venv/bin/python")
    if args.operation == "catalog":  # without OpenWebUI and offline (unless --fetch)
        subprocess.run([python, "-m", "documents_mcp.catalog", "--root", ".."] + ([args.text] if args.text else []) + rest,
                       cwd=ROOT / "documents", check=True)
        return
    if args.operation == "access":  # show rights: grants (access/grants.yaml) and audit log
        subprocess.run([python, "-m", "documents_mcp.access", "--dir", str(ROOT / "access")]
                       + ([args.text] if args.text else ["--help"]) + rest, check=True)
        return
    if args.operation == "ask" and not args.text:
        parser.error("'ask' braucht einen Fragetext.")
    values = demo.load_env()
    if "compose.ai-data.yml" not in values.get("COMPOSE_FILE", ""):
        raise RuntimeError("COMPOSE_FILE=docker-compose.yml:compose.ai-data.yml fehlt in der lokalen .env.")
    if len(values.get("DOCUMENTS_API_KEY", "")) < 32:
        raise RuntimeError("DOCUMENTS_API_KEY (mind. 32 Zeichen, z. B. python3 -c 'import secrets; "
                           "print(secrets.token_urlsafe(32))') fehlt in der lokalen .env.")
    if args.operation == "start":
        subprocess.run([sys.executable, str(ROOT / "scripts/openwebui.py"), "start"], check=True)
    demo.validate_env(values)
    if args.operation == "check":
        sys.exit(0 if overall_check(values) else 1)
    base = "http://127.0.0.1:" + values.get("OPEN_WEBUI_HOST_PORT", "3003")
    demo.wait_ready("http://127.0.0.1:" + values.get("DOCUMENTS_HOST_PORT", "8005") + "/readyz", "Dokumente-Server")
    demo.wait_ready(base + "/health", "OpenWebUI")
    token = demo.authenticate(base, values)
    if args.operation == "ask":
        print(json.dumps(ask(base, token, args.text), ensure_ascii=False, indent=1), flush=True)
        return
    if args.operation in ("start", "seed"):
        seed(base, token, values)
    verify(base, token, values)
    print(f"Dokumente-Server ({len(DOCUMENTS_TOOLS)} Werkzeuge) und Modell 'Daten + Dokumente' verifiziert.", flush=True)
    print(f"Bereit: {base.replace('127.0.0.1', 'localhost')} — Modell '{MODEL_NAME}'.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Start der Demo 002 fehlgeschlagen.", file=sys.stderr)
        sys.exit(1)
