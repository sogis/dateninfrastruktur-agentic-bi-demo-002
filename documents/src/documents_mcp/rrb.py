"""Fetch and prepare government council decisions (RRB, rrb.so.ch): raw (HTML, PDF) -> prepared (JSON).

Layout under ``corpus/rrb/`` (not versioned: titles and distribution lists contain personal data):
  raw/list/<year>-<page>.html        result list, unchanged
  raw/decisions/<year>_<nr>.html     detail page, unchanged
  raw/decisions/<year>_<nr>.pdf      first document (the decision itself; no letters or attachments)
  raw/decisions/<year>_<nr>.txt      pdftotext output (-layout, keeps the indentation in the distribution list)
  decisions.json                     fields, text without distribution list, distribution list, derived features

Quirks of rrb.so.ch: the result list only pages without a page size (10 per page), the date filter needs
``YYYYMMDD0000``, and the first document on the detail page is the decision.

Fetch (polite, one request per second, resumable): ``python -m documents_mcp.rrb 2026 --target ../corpus/rrb``
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

from .distribution_list import CANTONAL_RECIPIENTS, is_heading, parse_block

BASE = "https://rrb.so.ch"
SOURCE = "Regierungsratsbeschlüsse (rrb.so.ch, aus CMI)"
PAUSE = 1.0
USER_AGENT = "dateninfrastruktur-agentic-bi-demo-002/documents (Prototyp, Kanton Solothurn)"
_HITS = re.compile(r"von\s+([\d'’.,]+)")
_TBODY = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.I | re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_NUMBER = re.compile(r"^(\d{4})/(\d{1,4})$")
_PDF = re.compile(r'href="(/beschlussnummer/[^"]+/download/[^"]+)"')
_NOT_PUBLIC = re.compile(r"Dokumente\s*</td>\s*<td>\s*nicht\s+öffentlich", re.I)
_BGS = re.compile(r"\bBGS\s+(\d{3}(?:\.\d+)+)")
# Cantonal bodies that count as feature "involved office" (no private persons, municipalities, companies).
# Longer names first, so that "Amt für Wald, Jagd und Fischerei" does not count as "Amt für Wald".
_OFFICES = tuple(sorted(CANTONAL_RECIPIENTS, key=len, reverse=True))


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _iso(date: str) -> str | None:
    parts = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", date.strip())
    return f"{parts[3]}-{parts[2]}-{parts[1]}" if parts else None


def read_list(page: str) -> tuple[int, list[dict]]:
    """Total hits and rows of a result list (date, number, business type, lead department, title)."""
    hits = _HITS.search(page)
    total = int(re.sub(r"\D", "", hits[1]) or 0) if hits else 0
    tbody = _TBODY.search(page)
    rows = []
    for row in _ROW.findall(tbody[1] if tbody else ""):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) >= 5 and _NUMBER.match(cells[1]) and cells[4]:
            rows.append(dict(number=cells[1], date=_iso(cells[0]), business_type=cells[2],
                             lead_department=cells[3], title=cells[4]))
    return total, rows


def read_detail(page: str) -> dict:
    """Document links and status of a detail page."""
    links = [BASE + html.unescape(link) for link in _PDF.findall(page)]
    return dict(public=not _NOT_PUBLIC.search(page) and bool(links), documents=links)


def offices_from_distribution_list(entries: list[str]) -> list[str]:
    """All cantonal bodies named in any line of the distribution list. Taking only the first name per line would
    turn "Departement des Innern, Gesundheitsamt" into the department alone (2026: 24 of 90 decisions with
    Gesundheitsamt in the list)."""
    found = set()
    for entry in entries:
        rest = entry
        for office in _OFFICES:
            if office in rest:
                found.add(office)
                rest = rest.replace(office, " ")
    return sorted(found)


def split_text(text: str) -> tuple[str, list[str]]:
    """Decision text without the distribution list (which always comes last) and the list entries."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if is_heading(line)), len(lines))
    body = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in lines[:start])
    return re.sub(r"\n{3,}", "\n\n", body).strip(), parse_block(text)


# Fetch -----------------------------------------------------------------------
class _Fetcher:
    """Fetches pages with a fixed pause between two requests; existing files are not fetched again."""

    def __init__(self) -> None:
        self.last = 0.0
        self.requests = 0

    def __call__(self, url: str, target: Path) -> bytes:
        if target.exists() and target.stat().st_size:
            return target.read_bytes()
        time.sleep(max(0.0, self.last + PAUSE - time.monotonic()))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
        finally:
            self.last, self.requests = time.monotonic(), self.requests + 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return content


def _list_url(year: int, page: int) -> str:
    date_filter = f"dateRange:{year}01010000-{year}12310000"
    return BASE + "/?" + urllib.parse.urlencode([("tx_solr[filter][]", date_filter), ("tx_solr[page]", str(page))])


def fetch(year: int, target: Path, limit: int | None = None) -> dict:
    """Store the raw stage of one year. Resumable: existing files are skipped; errors per decision are reported
    and do not stop the run."""
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext (poppler-utils) fehlt.")
    get, raw = _Fetcher(), target / "raw"
    seen: dict[str, dict] = {}
    page = 1
    while True:
        total, rows = read_list(get(_list_url(year, page), raw / "list" / f"{year}-{page:04d}.html").decode("utf-8"))
        new = [r for r in rows if r["number"] not in seen]
        seen.update((r["number"], r) for r in new)
        if not new or len(seen) >= total or (limit and len(seen) >= limit):
            break
        page += 1
    errors = []
    for number in sorted(seen, key=lambda n: int(n.split("/")[1]))[:limit]:
        name = number.replace("/", "_")
        try:
            detail = read_detail(get(f"{BASE}/beschlussnummer/{name}/", raw / "decisions" / f"{name}.html")
                                 .decode("utf-8"))
            if detail["public"]:
                pdf = raw / "decisions" / f"{name}.pdf"
                get(detail["documents"][0], pdf)
                txt = pdf.with_suffix(".txt")
                if not txt.exists():
                    txt.write_text(subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
                                                  check=True, capture_output=True, text=True).stdout, encoding="utf-8")
        except Exception as error:  # one broken decision must not stop the year
            errors.append(f"{number}: {error.__class__.__name__} {error}")
            print(f"Fehler {number}: {error}", flush=True)
        if get.requests and get.requests % 100 == 0:
            print(f"… {get.requests} Anfragen", flush=True)
    return dict(year=year, decisions=len(seen), requests=get.requests, errors=errors)


def prepare(target: Path) -> list[dict]:
    """Compute the prepared stage from the raw stage only (offline, repeatable)."""
    raw = target / "raw"
    rows: dict[str, dict] = {}
    for page in sorted((raw / "list").glob("*.html")):
        rows.update((r["number"], r) for r in read_list(page.read_text(encoding="utf-8"))[1])
    decisions = []
    for number, row in sorted(rows.items(), key=lambda x: (x[0][:4], int(x[0].split("/")[1]))):
        name = number.replace("/", "_")
        page = raw / "decisions" / f"{name}.html"
        if not page.exists():
            continue  # not fetched yet
        detail = read_detail(page.read_text(encoding="utf-8"))
        entry = dict(row, url=f"{BASE}/beschlussnummer/{name}/", public=detail["public"],
                     documents=len(detail["documents"]), pdf=detail["documents"][0] if detail["documents"] else None,
                     retrieved=datetime.fromtimestamp(page.stat().st_mtime, timezone.utc).date().isoformat())
        txt = page.with_suffix(".txt")
        if detail["public"] and txt.exists():
            text, distribution_list = split_text(txt.read_text(encoding="utf-8"))
            entry.update(
                text=text, no_text_layer=len(re.sub(r"\s", "", text)) < 200,  # scan without text layer
                distribution_list=distribution_list, distribution_list_found=bool(distribution_list),
                offices=offices_from_distribution_list(distribution_list),
                bgs=sorted(set(_BGS.findall(text)), key=lambda n: [int(x) for x in n.split(".")]),
            )
        decisions.append(entry)
    (target / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return decisions


# Per-document checks for the document profile "decision" (rules/document_profiles/decision.yaml) --------------
# None means: not applicable (non-public decisions have no text that could be checked).
CHECKS = {
    "text_machine_readable": lambda d: (not d.get("no_text_layer") and bool(d.get("text"))) if d["public"] else None,
    "identifier": lambda d: bool(_NUMBER.fullmatch(d["number"])),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Regierungsratsbeschlüsse eines Jahrgangs abrufen und aufbereiten.")
    parser.add_argument("year", type=int, nargs="?")
    parser.add_argument("--target", type=Path, default=Path("corpus/rrb"))
    parser.add_argument("--limit", type=int, help="Nur die ersten N Beschlüsse (zum Ausprobieren).")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Keinen Abruf, nur die aufbereitete Stufe aus raw/ neu berechnen.")
    args = parser.parse_args()
    if not args.prepare_only:
        if not args.year:
            parser.error("Jahr fehlt.")
        run = fetch(args.year, args.target, args.limit)
        print(f"Abruf {run['year']}: {run['decisions']} Beschlüsse, {run['requests']} Anfragen, "
              f"{len(run['errors'])} Fehler", flush=True)
    decisions = prepare(args.target)
    public = [d for d in decisions if d["public"]]
    print(f"Aufbereitet: {len(decisions)} Beschlüsse, davon {len(public)} öffentlich, "
          f"{sum(d.get('no_text_layer', False) for d in public)} ohne Text, "
          f"{sum(d.get('distribution_list_found', False) for d in public)} mit erkanntem Verteiler", flush=True)


if __name__ == "__main__":
    main()
