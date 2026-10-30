"""Documents server (MCP, Streamable HTTP): shared catalog and corpora (acts, decisions), rights per person."""

from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path
from urllib.parse import unquote

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .access import ANONYMOUS, Person
from .corpus import Corpus, ToolError

LOG = logging.getLogger("documents_mcp")
INSTRUCTIONS = (
    "Zuerst catalog mit Begriffen zum Thema verwenden: Er zeigt je Datensatz kind (data/documents), access, was für "
    "die KI-Tauglichkeit fehlt (missing, mit Befund) und unter in_this_chat die passenden Werkzeuge. "
    "Ohne Werkzeuge ist ein Datensatz nur als Download vorhanden: das sagen, nicht rechnen. Rechtstexte immer mit "
    "Zitat, Fassung und Gültigkeit wiedergeben. Befunde (z. B. nur PDF, Stichtag fehlt) an die Person weitergeben. "
    "Was eine Person sieht, hängt von ihren Freigaben ab; gesperrte Inhalte nicht erraten oder umschreiben, sondern "
    "sagen, wer sie freigeben kann."
)
EMAIL_HEADER = "x-user-email"    # set by OpenWebUI per call: {{USER_EMAIL}} of the signed-in person
GROUPS_HEADER = "x-user-groups"  # {{USER_GROUPS}}


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def person_from(request, api_key: str | None) -> Person:
    """E-mail and groups only count if the call carries the shared key (i.e. comes from OpenWebUI, where the person
    is signed in). Otherwise, or without a configured key: anonymous, public datasets only."""
    if request is None or not api_key:
        return ANONYMOUS
    if not hmac.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {api_key}".encode()):
        LOG.warning("call without valid key: anonymous")
        return ANONYMOUS
    return Person.of(unquote(request.headers.get(EMAIL_HEADER, "")),
                     [unquote(g) for g in request.headers.get(GROUPS_HEADER, "").split(",")])


def respond(function, *args, person: Person) -> CallToolResult:
    try:
        payload, is_error = dict(ok=True, **function(*args, person=person)), False
    except ToolError as error:
        payload, is_error = dict(ok=False, error=str(error)), True
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    LOG.info("tool=%s ok=%s bytes=%d person=%s", function.__name__, not is_error, len(text),
             "|".join(sorted(person.principals())) or "anonymous")
    return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=payload, isError=is_error)


def create_app(corpus: Corpus, api_key: str | None = None) -> Starlette:
    mcp = FastMCP(
        "Solothurn Dokumente und Katalog",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        instructions=INSTRUCTIONS,
        transport_security=TransportSecuritySettings(
            allowed_hosts=_env_list("DOCUMENTS_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*"),
            allowed_origins=_env_list("DOCUMENTS_ALLOWED_ORIGINS", "http://127.0.0.1:*,http://localhost:*"),
        ),
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    def person(ctx: Context) -> Person:
        return person_from(ctx.request_context.request, api_key)

    @mcp.tool(annotations=read_only)
    async def catalog(ctx: Context, query: str = "", limit: int = 6) -> CallToolResult:
        """Gemeinsamer Katalog für Daten und Dokumente. Mit query (Begriffe zum Thema): passende Datensätze mit kind
        (data/documents), access, was fehlt (missing: Kriterium, Befund), was erfüllt ist (met), Werkzeugen in diesem
        Chat (in_this_chat) und Inhalt des Bestands (contents). Ohne query: kurze Übersicht."""
        return respond(corpus.catalog, query, limit, person=person(ctx))

    @mcp.tool(annotations=read_only)
    async def search_laws(ctx: Context, query: str, date: str | None = None, act: str | None = None,
                          limit: int = 8) -> CallToolResult:
        """Volltextsuche in den Erlassen (act = BGS-Nummer, optional), in der am Datum (JJJJ-MM-TT, Standard heute)
        gültigen Fassung."""
        return respond(corpus.search_laws, query, date, act, limit, person=person(ctx))

    @mcp.tool(annotations=read_only)
    async def get_section(ctx: Context, act: str, section: str, date: str | None = None) -> CallToolResult:
        """Wortlaut eines Paragrafen (section) eines Erlasses (act = BGS-Nummer) in der am Datum gültigen Fassung,
        mit Zitat, Fussnoten und Quelle."""
        return respond(corpus.get_section, act, section, date, person=person(ctx))

    @mcp.tool(annotations=read_only)
    async def get_changes(ctx: Context, act: str, section: str | None = None) -> CallToolResult:
        """Fassungen mit Gültigkeit und Änderungstabelle eines Erlasses, optional auf einen Paragrafen gefiltert."""
        return respond(corpus.get_changes, act, section, person=person(ctx))

    @mcp.tool(annotations=read_only)
    async def search_decisions(ctx: Context, query: str = "", office: str | None = None,
                               department: str | None = None, date_from: str | None = None,
                               date_to: str | None = None, bgs: str | None = None,
                               limit: int = 10) -> CallToolResult:
        """Regierungsratsbeschlüsse suchen und filtern: Volltext (query), beteiligtes Amt (office, z. B.
        "Gesundheitsamt"), federführendes Departement (department), Zeitraum (date_from/date_to JJJJ-MM-TT),
        genannte BGS-Nummer (bgs). Liefert Anzahl und Treffer."""
        return respond(corpus.search_decisions, query, office, department, date_from, date_to, bgs, limit,
                       person=person(ctx))

    @mcp.tool(annotations=read_only)
    async def get_decision(ctx: Context, number: str) -> CallToolResult:
        """Ein Regierungsratsbeschluss (number JJJJ/NNNN) mit Angaben, Text und, falls berechtigt, Verteiler
        (distribution_list)."""
        return respond(corpus.get_decision, number, person=person(ctx))

    mcp_app = mcp.streamable_http_app()

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def ready(request):
        # Only what is visible without sign-in, plus whether rights per person are active.
        return JSONResponse({"ready": True, "datasets": len(corpus.entries),
                             "acts": sorted(corpus.acts), "decisions": len(corpus.decisions),
                             "per_person_access": bool(api_key), "grants_loaded": corpus.access.directory is not None,
                             "catalog_modified": corpus.catalog_modified, "catalog_sha256": corpus.catalog_sha256})

    app = Starlette(
        routes=[Route("/healthz", health), Route("/readyz", ready), Mount("/", app=mcp_app)],
        lifespan=lambda app: mcp.session_manager.run(),
    )
    app.state.mcp = mcp
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    access = os.environ.get("DOCUMENTS_ACCESS", "").strip()
    corpus = Corpus(
        Path(os.environ.get("DOCUMENTS_CATALOG", "catalog/catalog.json")),
        Path(os.environ.get("DOCUMENTS_CORPUS", "corpus")),
        Path(os.environ.get("DOCUMENTS_RULES", "rules")),
        Path(access) if access else None,
    )
    api_key = os.environ.get("DOCUMENTS_API_KEY", "").strip() or None
    LOG.info("ready: %d datasets, %d acts, %d decisions, rights per person %s", len(corpus.entries),
             len(corpus.acts), len(corpus.decisions), "on" if api_key else "off (public only)")
    uvicorn.run(
        create_app(corpus, api_key),
        host=os.environ.get("DOCUMENTS_HOST", "127.0.0.1"),
        port=int(os.environ.get("DOCUMENTS_PORT", "8000")),
        workers=1, access_log=False, log_config=None, proxy_headers=False,
    )


if __name__ == "__main__":
    main()
