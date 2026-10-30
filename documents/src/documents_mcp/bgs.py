"""Fetch and prepare the BGS Solothurn (collected cantonal law): raw (API response, XHTML, PDF) -> prepared (JSON).

Layout per act under ``corpus/bgs/<number>/``:
  raw/act.json                         master record of the act as delivered by the API
  raw/<version>.json|.xhtml|.pdf|.txt  unchanged, as delivered (or pdftotext output)
  raw/retrieved.txt                    time of the fetch (ISO 8601)
  versions/<version>.json              sections, paragraphs, items, footnotes
  act.json                             metadata, versions with validity, change table

Fetch: ``python -m documents_mcp.bgs 614.61 614.62 733.11 --target ../corpus/bgs``
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

API = "https://bgs.so.ch/api/de"
SOURCE = "BGS Solothurn (bgs.so.ch, LexWork)"
VOID = {"br", "hr", "img", "meta", "link", "input", "col", "wbr"}
DATE = r"(\d{2}\.\d{2}\.\d{4})"
XHTML = "xhtml"
PDF_HEURISTIC = "pdf-heuristic"


def iso(text: str | None) -> str | None:
    """'01.01.2023' -> '2023-01-01'; anything else -> None."""
    if not text:
        return None
    match = re.fullmatch(DATE, text.strip())
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d.%m.%Y").date().isoformat()


def validity(version_dates_str: str) -> dict:
    """Read validity from the free text of the API. The BGS does not deliver it as a field.

    'Aktuelle Version in Kraft seit: 01.01.2023 (Beschlussdatum: 28.06.2022)'
    'Version in Kraft von: 01.01.2021 bis: 31.12.2022 (Beschlussdatum: 23.06.2020)'
    """
    text = version_dates_str or ""
    start = re.search(r"(?:seit|von|ab):\s*" + DATE, text)
    end = re.search(r"bis:\s*" + DATE, text)
    decided = re.search(r"Beschlussdatum:\s*" + DATE, text)
    return dict(
        valid_from=iso(start.group(1)) if start else None,
        valid_to=iso(end.group(1)) if end else None,
        decided=iso(decided.group(1)) if decided else None,
    )


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _paragraph() -> dict:
    return dict(number="", text="", items=[])


class _XhtmlParser(HTMLParser):
    """Reads the flat XHTML structure of the BGS (sections and paragraphs are siblings)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str], str]] = []
        self.outline: dict[int, str] = {}
        self.heading = {"number": "", "title": ""}
        self.sections: list[dict] = []
        self.paragraph: dict | None = None
        self.item: dict | None = None
        self.footnotes: dict[str, str] = {}
        self.footnote_id: str | None = None
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None

    # Helpers ----------------------------------------------------------------
    def _in(self, css_class: str) -> bool:
        return any(css_class in frame[1] for frame in self.stack)

    def _in_tag(self, tag: str) -> bool:
        return any(frame[0] == tag for frame in self.stack)

    def _in_id(self, ident: str) -> bool:
        return any(frame[2] == ident for frame in self.stack)

    def _innermost(self, css_class: str) -> bool:
        return bool(self.stack) and css_class in self.stack[-1][1]

    # Events -----------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag not in VOID:
            self.stack.append((tag, classes, attrs.get("id") or ""))
        if tag == "div" and "article" in classes:
            self.sections.append(dict(number="", title="", outline=[self.outline[k] for k in sorted(self.outline)],
                                      paragraphs=[], footnotes=[]))
            self.paragraph = self.item = None
        elif tag == "div" and "paragraph" in classes and self.sections:
            self.paragraph = _paragraph()
            self.sections[-1]["paragraphs"].append(self.paragraph)
            self.item = None
        elif tag == "table" and "enumeration_item" in classes and self.sections:
            if self.paragraph is None:
                self.paragraph = _paragraph()
                self.sections[-1]["paragraphs"].append(self.paragraph)
            self.item = dict(lit="", text="")
            self.paragraph["items"].append(self.item)
        elif tag == "a" and "footnote" in classes:
            href = (attrs.get("href") or "").lstrip("#")
            if self._in("footnotes"):
                self.footnote_id = attrs.get("id") or attrs.get("name")
            elif self.sections and href:
                self.sections[-1]["footnotes"].append(href)
        elif tag == "tr" and self._in_id("modification_table"):
            self.rows.append([])
        elif tag in ("td", "th") and self._in_id("modification_table") and self.rows:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        # Sloppy HTML: unwind up to the matching tag.
        while self.stack:
            frame = self.stack.pop()
            if frame[0] == tag:
                break
        _, classes, _ = frame
        if tag == "div" and "title" in classes and any(c.startswith("level_") for c in classes):
            level = int(next(c for c in classes if c.startswith("level_")).split("_")[1])
            self.outline = {k: v for k, v in self.outline.items() if k < level}
            self.outline[level] = normalise(f"{self.heading['number']} {self.heading['title']}")
            self.heading = {"number": "", "title": ""}
        elif tag in ("td", "th") and self.cell is not None:
            self.rows[-1].append(normalise("".join(self.cell)))
            self.cell = None

    def handle_data(self, data):
        if not self.stack:
            return
        if self._in("footnotes"):
            if self._in("footnote_text") and self.footnote_id:
                self.footnotes[self.footnote_id] = self.footnotes.get(self.footnote_id, "") + data
            return
        if self.cell is not None:
            self.cell.append(data)
            return
        if self._in("footnote") and self._in_tag("a"):
            return  # footnote mark [n]
        if self._in_tag("strong") and data.strip() == "*":
            return  # change mark
        if any(c.startswith("level_") for f in self.stack for c in f[1]) and self._in("title"):
            if self._innermost("number"):
                self.heading["number"] += data
            elif self._in("title_text"):
                self.heading["title"] += data
            return
        if not self.sections:
            return
        section = self.sections[-1]
        if self._in("article_number") and self._innermost("number"):
            section["number"] += data
        elif self._in("article_title"):
            section["title"] += data
        elif self.item is not None and self._in("enumeration_item"):
            if self._in("number"):
                self.item["lit"] += data
            elif self._in("left_col"):
                self.item["text"] += data
        elif self.paragraph is not None and self._in("paragraph"):
            if self._in_tag("p"):
                self.paragraph["text"] += data
            elif self._innermost("number"):
                self.paragraph["number"] += data


REPEALED = ("…", "Aufgehoben.", "")


def parse_xhtml(xhtml: str) -> dict:
    """XHTML of one version -> sections + change table."""
    parser = _XhtmlParser()
    parser.feed(xhtml)
    parser.close()
    sections = []
    for raw in parser.sections:
        paragraphs = [dict(number=normalise(p["number"]), text=normalise(p["text"]),
                           items=[dict(lit=normalise(i["lit"]), text=normalise(i["text"])) for i in p["items"]])
                      for p in raw["paragraphs"]]
        texts = [p["text"] for p in paragraphs] + [i["text"] for p in paragraphs for i in p["items"]]
        sections.append(dict(
            number=normalise(raw["number"]), title=normalise(raw["title"]), outline=raw["outline"],
            paragraphs=paragraphs,
            footnotes=[normalise(parser.footnotes[r]) for r in raw["footnotes"] if r in parser.footnotes],
            repealed=bool(texts) and all(t in REPEALED for t in texts),
        ))
    changes, seen = [], set()
    for row in parser.rows:
        if len(row) < 5 or row[0] == "Beschluss":
            continue
        entry = dict(decided=iso(row[0]) or row[0], in_force=iso(row[1]) or row[1],
                     element=row[2], change=row[3], reference=row[4])
        key = tuple(entry.values())
        if key not in seen:  # the table appears after the decision and after each section
            seen.add(key)
            changes.append(entry)
    return dict(sections=sections, changes=changes)


SECTION = re.compile(r"^§\s*(\d+)\s*([a-z]*)\.?\s*(.*)$")
PART = re.compile(r"^(Erster|Zweiter|Dritter|Vierter|Fünfter|Sechster|Siebter) Teil$")
CHAPTER = re.compile(r"^\d+\.\s+[A-ZÄÖÜ]")
FOOTNOTE_LANGUAGE = re.compile(r"^(Absatz|Fassung|Buchstabe|Ziffer|eingefügt|aufgehoben)|aufgehoben am|eingefügt am")


def _without_marks(line: str, expected: int) -> tuple[str, int]:
    """Remove footnote marks. They run per page (1), 2), ...); only the next expected mark is removed, so that
    '19594))' becomes '1959)' and not '195)'."""
    while True:
        match = re.search(rf"(?:(?<=\S)|^){expected}\)\s?", line)
        if not match:
            return line, expected
        line = line[: match.start()] + line[match.end():]
        expected += 1


def parse_pdftext(text: str, number: str) -> dict:
    """Heuristic for versions the BGS only delivers as PDF (pdftotext output).

    Unverified: the outline is guessed, footnote texts at the page bottom are dropped, section numbers must
    ascend (otherwise the line counts as a reference inside a footnote).
    """
    lines: list[str] = []
    for page in text.split("\f"):
        parts = [line.strip() for line in page.splitlines()]
        if any(line.startswith("____") for line in parts):  # footnotes at the page bottom
            parts = parts[: next(i for i, line in enumerate(parts) if line.startswith("____"))]
        while parts and not parts[-1]:
            parts.pop()
        if parts and re.fullmatch(r"\d{1,3}", parts[-1]):  # page number
            parts.pop()
        expected = 1
        for line in parts:
            if line and line != number:
                line, expected = _without_marks(line, expected)
                if line.strip():
                    lines.append(line.strip())
    sections: list[dict] = []
    outline: list[str] = []
    awaiting_title = False
    last = 0
    for line in lines:
        match = SECTION.match(line)
        if match:
            value, rest = int(match.group(1)), match.group(3).strip()
            if value < last or FOOTNOTE_LANGUAGE.search(rest):
                continue  # reference from a footnote, not a new section
            last = value
            sections.append(dict(number=f"{value}{match.group(2)}", title=rest, outline=list(outline),
                                 paragraphs=[], footnotes=[], repealed=False))
            awaiting_title = not rest
            continue
        if PART.match(line) or (CHAPTER.match(line) and len(line) < 80):
            outline = [line] if PART.match(line) else outline[:1] + [line]
            continue
        if not sections:
            continue
        current = sections[-1]
        if re.fullmatch(r"\d{1,2}", line):
            current["paragraphs"].append(dict(number=line, text="", items=[]))
            awaiting_title = False
            continue
        if awaiting_title:
            current["title"], awaiting_title = line, False
            continue
        if not current["paragraphs"]:
            current["paragraphs"].append(_paragraph())
        paragraph = current["paragraphs"][-1]
        if paragraph["text"].endswith("-") and line[:1].islower():
            paragraph["text"] = paragraph["text"][:-1] + line
        else:
            paragraph["text"] = (paragraph["text"] + " " + line).strip()
    for s in sections:
        # Remaining marks the page counter missed: only after letters/punctuation (never after digits, otherwise
        # years would be cut).
        s["title"] = re.sub(r"^\d{1,2}\)\s*|(?<=[^\d\s])\d{1,2}\)$", "", s["title"]).strip()
        for p in s["paragraphs"]:
            p["text"] = re.sub(r"(?<=[A-Za-zÄÖÜäöüß:;,.])\d{1,2}\)", "", p["text"])
        texts = [p["text"] for p in s["paragraphs"]]
        s["repealed"] = s["title"] in ("...", "…") and all(t in ("...", "…", "") for t in texts)
    return dict(sections=sections, changes=[])


# Fetch -----------------------------------------------------------------------
def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json, */*"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _versions(master: dict) -> list[dict]:
    return (
        [dict(v, status="current") for v in [master["current_version"]]]
        + [dict(v, status="past") for v in master.get("old_versions") or []]
        + [dict(v, status="future") for v in master.get("future_versions") or []]
    )


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fetch(number: str, target: Path) -> dict:
    """Raw stage: store the act with all versions unchanged, then prepare."""
    raw = target / number / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    master = json.loads(_get(f"{API}/texts_of_law/{number}"))["text_of_law"]
    _write(raw / "act.json", master)
    for entry in _versions(master):
        vid = str(entry["id"])
        version = json.loads(_get(f"{API}/texts_of_law/{number}/versions/{vid}"))["text_of_law"]["selected_version"]
        xhtml = version.pop("xhtml_tol", None)
        for heavy in ("xhtml_cac_tol", "xhtml_cac_unified_tol"):
            version.pop(heavy, None)  # bilingual renderings, not needed for German
        _write(raw / f"{vid}.json", version)
        if xhtml:
            (raw / f"{vid}.xhtml").write_text(xhtml, encoding="utf-8")
        else:
            if not shutil.which("pdftotext"):
                raise RuntimeError("pdftotext (poppler-utils) fehlt für reine PDF-Fassungen.")
            pdf = raw / f"{vid}.pdf"
            pdf.write_bytes(_get(version["pdf_link_tol"]))
            text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
                                  check=True, capture_output=True, text=True).stdout
            (raw / f"{vid}.txt").write_text(text, encoding="utf-8")
    (raw / "retrieved.txt").write_text(datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n", encoding="utf-8")
    return prepare(number, target)


def prepare(number: str, target: Path) -> dict:
    """Compute the prepared stage from the raw stage only (offline, repeatable)."""
    directory = target / number
    raw = directory / "raw"
    (directory / "versions").mkdir(exist_ok=True)
    master = json.loads((raw / "act.json").read_text(encoding="utf-8"))
    versions, changes = [], []
    for entry in _versions(master):
        vid = str(entry["id"])
        version = json.loads((raw / f"{vid}.json").read_text(encoding="utf-8"))
        if (raw / f"{vid}.xhtml").exists():
            content, structure = parse_xhtml((raw / f"{vid}.xhtml").read_text(encoding="utf-8")), XHTML
        else:
            content, structure = parse_pdftext((raw / f"{vid}.txt").read_text(encoding="utf-8"), number), PDF_HEURISTIC
        if entry["status"] == "current":
            changes = content["changes"]
        _write(directory / "versions" / f"{vid}.json", dict(version=vid, structure=structure, sections=content["sections"]))
        versions.append(dict(id=vid, status=entry["status"], structure=structure,
                             **validity(entry["version_dates_str"]), validity_text=entry["version_dates_str"],
                             pdf=version.get("pdf_link_tol"), sections=len(content["sections"])))
    versions.sort(key=lambda v: v["valid_from"] or "")
    act = dict(
        number=number, title=master["title"], abbreviation=master.get("abbreviation") or None,
        source=SOURCE, url=master["canonical_link"], repealed=bool(master.get("abrogated")),
        decided=master.get("date_of_decision"), in_force_since=master.get("enactment"),
        retrieved=(raw / "retrieved.txt").read_text(encoding="utf-8").strip(),
        versions=versions, changes=changes,
        amending_acts=[
            dict(number=c.get("number"), title=c.get("document_title"),
                 decided=iso(c.get("date_of_decision_string")),
                 published=iso(c.get("date_of_publication_string")), pdf=c.get("pdf_link"))
            for c in master.get("change_documents") or []
        ],
    )
    _write(directory / "act.json", act)
    return act


# Per-document checks for the document profile "legal_text" (rules/document_profiles/legal_text.yaml) ----------
def current_version(act: dict) -> dict:
    return next((v for v in act["versions"] if v["status"] == "current"), act["versions"][-1])


CHECKS = {
    "structured_text": lambda a: current_version(a)["structure"] == XHTML,
    "outline": lambda a: current_version(a)["structure"] == XHTML,  # from PDF only heuristically structured
    "act_identifier": lambda a: bool(re.fullmatch(r"\d+(\.\d+)+", a["number"])),
    "metadata": lambda a: bool(a["title"] and a["decided"] and a["in_force_since"]),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="BGS-Erlasse abrufen und aufbereiten.")
    parser.add_argument("numbers", nargs="+")
    parser.add_argument("--target", type=Path, default=Path("corpus/bgs"))
    parser.add_argument("--prepare-only", action="store_true",
                        help="Keinen Abruf, nur die aufbereitete Stufe aus raw/ neu berechnen.")
    args = parser.parse_args()
    for number in args.numbers:
        act = prepare(number, args.target) if args.prepare_only else fetch(number, args.target)
        kinds = ", ".join(f"{v['id']}:{v['structure']}" for v in act["versions"])
        print(f"{number} {act['title']} — {len(act['versions'])} Fassungen ({kinds}), "
              f"{len(act['changes'])} Änderungen", flush=True)


if __name__ == "__main__":
    main()
