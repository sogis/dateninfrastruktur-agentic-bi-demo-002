"""Documents server logic: read the catalog, search and cite the corpora (acts, decisions), check rights per person.

Layers: the catalog (DCAT-AP CH) says what exists and how good it is. The corpus delivers the content. Access
control (access.py) decides per call whether this person may read the dataset. Which chat tools belong to which
interface is known only to this application (TOOLS below), not to the catalog.

Convention: the corpus of a document dataset lives under corpus/<identifier> (bgs, rrb). A dataset with
dct:isPartOf (e.g. rrb-distribution-list) is a more strictly protected part of its parent corpus.

Messages returned to the model are German, like the rest of the user-facing text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from . import bgs, dcat
from .access import ANONYMOUS, AccessControl, Person
from .rules import Rules

TEXT_LIMIT = 12000  # characters per decision; longer texts are cut, with a note
PDF_NOTE = (
    "Diese Fassung liegt im BGS nur als PDF vor. Text und Gliederung sind automatisch extrahiert "
    "und ungeprüft; Tabellen können zerstört sein. Für verbindliche Angaben das Original-PDF prüfen."
)
# Application: interface (from the catalog) -> tools in this chat.
TOOLS = {
    "metrics": "Daten-Server: search, inspect, analyse",
    "legal_text": "search_laws, get_section, get_changes",
    "decision": "search_decisions, get_decision",
    "distribution_list": "get_decision (Feld distribution_list)",
}


class ToolError(ValueError):
    """Domain error with a message the language model can understand (German)."""


def section_text(section: dict) -> str:
    lines = []
    for paragraph in section["paragraphs"]:
        lines.append(f"{paragraph['number']} {paragraph['text']}".strip())
        lines.extend(f"  {i['lit']} {i['text']}" for i in paragraph["items"])
    return "\n".join(lines)


def _matches(words: list[str], text: str) -> int:
    """Number of search words found in the text, also via a shared word start of 6 characters
    ('Motorfahrzeugsteuer' matches 'Motorfahrzeuge')."""
    text = text.lower()
    starts = {w[:6] for w in re.findall(r"\w{6,}", text)}
    return sum(1 for w in words if w in text or (len(w) >= 6 and w[:6] in starts))


def citation(act: dict, section: dict) -> str:
    title = f" {section['title']}" if section["title"] and section["title"] not in ("...", "…") else ""
    return f"§ {section['number']}{title}, {act['title']} (BGS {act['number']})"


def _fts(db: sqlite3.Connection, ddl: str) -> None:
    # Trigrams also find parts of words ('steuer' in 'Motorfahrzeugsteuer').
    try:
        db.execute(ddl.format("trigram remove_diacritics 1"))
    except sqlite3.OperationalError:  # SQLite < 3.45
        db.execute(ddl.format("trigram"))


def _words(query: str) -> list[str]:
    return [w for w in re.findall(r"\w+", query) if len(w) >= 3]


def _fts_query(words: list[str]) -> str:
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words)


class Corpus:
    def __init__(self, catalog: Path, corpus: Path, rules: Path, access: Path | None = None) -> None:
        content = catalog.read_bytes()
        self.catalog_sha256 = hashlib.sha256(content).hexdigest()  # shows which catalog the service has loaded
        raw = json.loads(content)
        self.rules = Rules.load(rules)
        self.access = AccessControl(access)
        self.catalog_modified = raw["dct:modified"]
        self.entries: dict[str, dict] = {e["dct:identifier"]: e for e in raw["dcat:dataset"]}
        self.views: dict[str, dict] = {k: dcat.view(e, self.rules) for k, e in self.entries.items()}
        self.acts: dict[str, dict] = {}
        self.versions: dict[tuple[str, str], dict] = {}
        self.decisions: dict[str, dict] = {}
        self.bgs_id: str | None = None
        self.rrb_id: str | None = None
        self.distribution_list_id: str | None = None
        for identifier, v in self.views.items():
            if v["kind"] != "documents":
                continue
            if v.get("part_of"):
                self.distribution_list_id = identifier  # the only part in the prototype
            elif v["document_type"] == "legal_text":
                self.bgs_id = identifier
                for path in sorted((corpus / identifier).glob("*/act.json")):
                    act = json.loads(path.read_text(encoding="utf-8"))
                    self.acts[act["number"]] = act
                    for version in act["versions"]:
                        self.versions[(act["number"], version["id"])] = json.loads(
                            (path.parent / "versions" / f"{version['id']}.json").read_text(encoding="utf-8"))
            elif v["document_type"] == "decision":
                # Local only (personal data); without the corpus the catalog entry stays without content.
                path = corpus / identifier / "decisions.json"
                if path.exists():
                    self.rrb_id = identifier
                    self.decisions = {d["number"]: d for d in json.loads(path.read_text(encoding="utf-8"))}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        _fts(self.db, "CREATE VIRTUAL TABLE section_fts USING fts5(act UNINDEXED, version UNINDEXED, "
                      "section UNINDEXED, title, text, tokenize='{}')")
        for (number, vid), version in self.versions.items():
            self.db.executemany(
                "INSERT INTO section_fts VALUES (?, ?, ?, ?, ?)",
                [(number, vid, s["number"], s["title"], section_text(s)) for s in version["sections"] if not s["repealed"]],
            )
        _fts(self.db, "CREATE VIRTUAL TABLE decision_fts USING fts5(number UNINDEXED, title, text, tokenize='{}')")
        # The distribution list is not searchable: it is a separate, more strictly protected dataset.
        self.db.executemany("INSERT INTO decision_fts VALUES (?, ?, ?)",
                            [(d["number"], d["title"], d.get("text", "")) for d in self.decisions.values()])

    # Rights -------------------------------------------------------------------------------
    def _allowed(self, person: Person, identifier: str, tool: str) -> bool:
        access = self.views[identifier]["access"]
        allowed = self.access.may_read(person, identifier, access)
        if access != "open":
            self.access.record(person, identifier, tool, allowed)
        return allowed

    def _locked(self, identifier: str) -> str:
        v = self.views[identifier]
        return (f"Datensatz '{identifier}' ({v['title']}) ist {v['access']}: Inhalt nur mit Freigabe. "
                f"Freigeben kann der Eigner: {v.get('owner') or 'unbekannt'}.")

    def _require(self, identifier: str | None, label: str, person: Person, tool: str) -> str:
        if identifier is None:
            raise ToolError(f"{label} sind hier nicht geladen.")
        if not self._allowed(person, identifier, tool):
            raise ToolError(self._locked(identifier))
        return identifier

    # Catalog ------------------------------------------------------------------------------
    def _tools(self, v: dict) -> str | None:
        if "metrics" in v.get("services", []):
            return TOOLS["metrics"]
        if v["kind"] == "documents":
            return TOOLS["distribution_list" if v.get("part_of") else v["document_type"]]
        return None

    def _contents(self, identifier: str) -> dict | None:
        """What the corpus contains (from the corpus, not from the catalog), with findings per document."""
        if identifier == self.bgs_id:
            profile = self.rules.profiles["legal_text"]["requirements"]
            acts = []
            for a in sorted(self.acts.values(), key=lambda a: [int(x) for x in re.findall(r"\d+", a["number"])]):
                current = bgs.current_version(a)
                missing = [profile[k]["text"] for k, check in bgs.CHECKS.items() if check(a) is False]
                acts.append(dict(number=a["number"], title=a["title"], versions=len(a["versions"]),
                                 versions_since=a["versions"][0]["valid_from"], current_since=current["valid_from"],
                                 structure=current["structure"], changes=len(a["changes"]),
                                 **({"profile_missing": missing} if missing else {})))
            return dict(acts=acts)
        if identifier == self.rrb_id:
            every = list(self.decisions.values())
            with_text = [d for d in every if d["public"] and d.get("text") and not d.get("no_text_layer")]
            dates = sorted(d["date"] for d in every if d["date"])
            return dict(decisions=len(every), public=sum(1 for d in every if d["public"]), with_text=len(with_text),
                        date_from=dates[0] if dates else None, date_to=dates[-1] if dates else None,
                        with_office=sum(1 for d in with_text if d["offices"]), with_bgs=sum(1 for d in with_text if d["bgs"]),
                        note="Merkmale offices (aus dem Verteiler) und bgs (aus dem Text) sind im Prototyp "
                             "automatisch herausgelesen und ungeprüft; die Quelle führt sie nicht als Feld.")
        return None

    def catalog(self, query: str = "", limit: int = 6, person: Person = ANONYMOUS) -> dict:
        header = dict(catalog_modified=self.catalog_modified, signed_in_as=person.describe())
        words = [w.lower() for w in _words(query)]
        if not words:
            return dict(header, note="Übersicht. Mit query (Begriffe zum Thema) Details, Lücken und Inhalt abrufen.",
                        entries=[dcat.view(e, self.rules, detailed=False) for e in self.entries.values()])
        scored = []
        for identifier, v in self.views.items():
            text = " ".join([identifier, v["title"], v.get("description") or "", v.get("owner") or "",
                             *v.get("keywords", [])])
            # Matching documents in the corpus count too (e.g. acts on vehicle tax in the BGS).
            documents = [a["number"] + " " + a["title"] for a in self.acts.values()] if identifier == self.bgs_id else []
            score = _matches(words, text) + sum(1 for d in documents if _matches(words, d))
            if score:
                scored.append((score, identifier))
        entries = []
        for _, identifier in sorted(scored, key=lambda x: -x[0])[: max(1, min(limit, 20))]:
            v = dict(self.views[identifier])
            v.pop("keywords", None)
            allowed = self.access.may_read(person, identifier, v["access"])
            tools = self._tools(v)
            v["in_this_chat"] = (
                dict(tools=tools) if tools and allowed
                else dict(note=self._locked(identifier)) if not allowed
                else dict(note="Keine Abfrage-Schnittstelle: nur als Download vorhanden (source). Nichts rechnen."))
            contents = self._contents(identifier) if allowed else None
            if contents:
                v["contents"] = contents
            entries.append(v)
        return dict(header, entries=entries)

    # Acts ---------------------------------------------------------------------------------
    def _act(self, number: str, person: Person, tool: str) -> dict:
        self._require(self.bgs_id, "Erlasse", person, tool)
        number = number.strip().removeprefix("BGS").strip()
        if number not in self.acts:
            raise ToolError(f"Erlass {number} ist nicht im Bestand. Verfügbar: {', '.join(sorted(self.acts)) or 'keine'}.")
        return self.acts[number]

    @staticmethod
    def _date(value: str | None) -> str:
        if not value:
            return dt.date.today().isoformat()
        try:
            return dt.date.fromisoformat(value).isoformat()
        except ValueError:
            raise ToolError("Datum im Format JJJJ-MM-TT angeben.") from None

    def version_at(self, act: str, day: str | None, person: Person = ANONYMOUS) -> dict:
        return self._version(self._act(act, person, "version_at"), self._date(day))

    @staticmethod
    def _version(act: dict, day: str) -> dict:
        """The version valid on the day (the caller has already checked rights)."""
        for version in act["versions"]:
            if (version["valid_from"] or "") <= day and (version["valid_to"] is None or day <= version["valid_to"]):
                return version
        earliest = act["versions"][0]["valid_from"]
        raise ToolError(f"Für {day} ist im BGS keine Fassung von {act['number']} vorhanden (früheste ab {earliest}).")

    def _version_short(self, version: dict) -> dict:
        short = {k: version[k] for k in ("id", "status", "valid_from", "valid_to", "structure")}
        if version["structure"] != bgs.XHTML:
            short["note"] = PDF_NOTE
        return short

    def search_laws(self, query: str, date: str | None = None, act: str | None = None, limit: int = 8,
                    person: Person = ANONYMOUS) -> dict:
        words = _words(query)
        if not words:
            raise ToolError("Suchtext mit mindestens einem Wort ab drei Zeichen angeben.")
        day = self._date(date)
        numbers = [self._act(act, person, "search_laws")["number"]] if act else (
            sorted(self.acts) if self._require(self.bgs_id, "Erlasse", person, "search_laws") else [])
        valid = {}
        for number in numbers:
            try:
                valid[number] = self._version(self.acts[number], day)["id"]
            except ToolError:
                continue
        if not valid:
            return dict(date=day, hits=[])
        condition = " OR ".join("(act = ? AND version = ?)" for _ in valid)
        parameters = [_fts_query(words)] + [x for pair in valid.items() for x in pair] + [max(1, min(limit, 20))]
        rows = self.db.execute(
            "SELECT act, version, section, title, snippet(section_fts, 4, '«', '»', ' … ', 48) FROM section_fts "
            f"WHERE section_fts MATCH ? AND ({condition}) ORDER BY bm25(section_fts, 0, 0, 0, 2.0, 1.0) LIMIT ?",
            parameters,
        ).fetchall()
        hits = []
        for number, vid, section, title, excerpt in rows:
            act_data = self.acts[number]
            version = next(v for v in act_data["versions"] if v["id"] == vid)
            section_data = next(s for s in self.versions[(number, vid)]["sections"] if s["number"] == section)
            hits.append(dict(act=number, section=section, title=title, citation=citation(act_data, section_data),
                             excerpt=excerpt, version=self._version_short(version)))
        return dict(date=day, hits=hits)

    def get_section(self, act: str, section: str, date: str | None = None, person: Person = ANONYMOUS) -> dict:
        act_data = self._act(act, person, "get_section")
        version = self._version(act_data, self._date(date))
        number = section.strip().removeprefix("§").strip()
        found = next((s for s in self.versions[(act_data["number"], version["id"])]["sections"] if s["number"] == number), None)
        if found is None:
            raise ToolError(f"§ {number} gibt es in BGS {act_data['number']} (Fassung ab {version['valid_from']}) nicht.")
        return dict(
            citation=citation(act_data, found), act=act_data["number"], act_title=act_data["title"],
            section=found["number"], title=found["title"], outline=found["outline"],
            repealed=found["repealed"], text=section_text(found), footnotes=found["footnotes"],
            version=self._version_short(version), date=self._date(date),
            source=dict(url=act_data["url"], pdf=version["pdf"], retrieved=act_data["retrieved"]),
        )

    def get_changes(self, act: str, section: str | None = None, person: Person = ANONYMOUS) -> dict:
        act_data = self._act(act, person, "get_changes")
        rows = act_data["changes"]
        if section:
            number = section.strip().removeprefix("§").strip()
            rows = [r for r in rows if re.match(rf"§\s*{re.escape(number)}(?![0-9a-z])", r["element"])]
        result = dict(
            act=act_data["number"], act_title=act_data["title"],
            versions=[self._version_short(v) for v in act_data["versions"]],
            changes=rows, amending_acts=act_data["amending_acts"],
        )
        if not act_data["changes"]:
            result["note"] = "Für diesen Erlass liefert das BGS keine maschinenlesbare Änderungstabelle."
        return result

    # Decisions ------------------------------------------------------------------------
    @staticmethod
    def _decision_short(d: dict) -> dict:
        short = {k: d.get(k) for k in ("number", "date", "title", "business_type", "lead_department", "url")}
        if not d["public"]:
            short["note"] = "Dokumente auf rrb.so.ch nicht öffentlich; nur die Angaben oben sind bekannt."
        else:
            short.update(offices=d.get("offices", []), bgs=d.get("bgs", []))
        return short

    def search_decisions(self, query: str = "", office: str | None = None, department: str | None = None,
                         date_from: str | None = None, date_to: str | None = None, bgs_number: str | None = None,
                         limit: int = 10, person: Person = ANONYMOUS) -> dict:
        self._require(self.rrb_id, "Die Regierungsratsbeschlüsse", person, "search_decisions")
        date_from = self._date(date_from) if date_from else None
        date_to = self._date(date_to) if date_to else None
        number = bgs_number.strip().removeprefix("BGS").strip() if bgs_number else None

        def fits(d: dict) -> bool:
            return ((not office or any(office.lower() in o.lower() for o in d.get("offices", [])))
                    and (not department or department.lower() in d["lead_department"].lower())
                    and (not date_from or (d["date"] or "") >= date_from)
                    and (not date_to or (d["date"] or "9") <= date_to)
                    and (not number or number in d.get("bgs", [])))

        words = _words(query)
        if words:
            rows = self.db.execute(
                "SELECT number, snippet(decision_fts, 2, '«', '»', ' … ', 32) FROM decision_fts "
                "WHERE decision_fts MATCH ? ORDER BY bm25(decision_fts, 0, 3.0, 1.0)", [_fts_query(words)]).fetchall()
            candidates = [(self.decisions[n], excerpt) for n, excerpt in rows]
        else:
            candidates = [(d, None) for d in sorted(self.decisions.values(), key=lambda d: d["date"] or "", reverse=True)]
        hits = [(d, e) for d, e in candidates if fits(d)]
        return dict(
            count=len(hits),
            filter=dict(query=query or None, office=office, department=department, date_from=date_from,
                        date_to=date_to, bgs=number),
            note="offices und bgs sind automatisch herausgelesen (offices aus dem Verteiler) und ungeprüft.",
            decisions=[dict(self._decision_short(d), **({"excerpt": e} if e else {})) for d, e in hits[: max(1, min(limit, 30))]],
        )

    def get_decision(self, number: str, person: Person = ANONYMOUS) -> dict:
        self._require(self.rrb_id, "Die Regierungsratsbeschlüsse", person, "get_decision")
        number = number.strip().replace("_", "/").removeprefix("RRB").strip()
        if number not in self.decisions:
            raise ToolError(f"Beschluss {number} ist nicht im Bestand (geladen: {self._coverage()}).")
        d = self.decisions[number]
        result = dict(self._decision_short(d), pdf=d.get("pdf"), retrieved=d["retrieved"])
        if not d["public"] or "text" not in d:
            return result
        text = d["text"]
        result["text"] = text[:TEXT_LIMIT]
        if len(text) > TEXT_LIMIT:
            result["text_note"] = f"Text gekürzt ({len(text)} Zeichen); vollständig im PDF."
        if d.get("no_text_layer"):
            result["text_note"] = "Scan ohne Textebene: Inhalt nur im PDF."
        if self.distribution_list_id and self._allowed(person, self.distribution_list_id, "get_decision"):
            result["distribution_list"] = d.get("distribution_list", [])
        elif self.distribution_list_id:
            result["distribution_list_note"] = (self._locked(self.distribution_list_id)
                                                + " Die beteiligten Ämter stehen öffentlich unter offices.")
        return result

    def _coverage(self) -> str:
        dates = sorted(d["date"] for d in self.decisions.values() if d["date"])
        return f"{len(self.decisions)} Beschlüsse {dates[0]} bis {dates[-1]}" if dates else "keine"
