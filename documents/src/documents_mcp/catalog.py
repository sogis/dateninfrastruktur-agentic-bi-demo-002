"""Build the shared catalog: automatically from what the sources deliver; by hand only one datasheet per corpus.

Inputs (all read-only):
  rules/                            criteria, document profiles, access levels (apply to all sources)
  catalog/raw/dataportal/           data portal release as delivered (current.json + published-catalog XTF) and
                                    its DCAT export opendata.rdf (only for the license: the XTF does not carry it)
  models/, tests/fixtures/real/     data server of demo 002: which datasets can be queried as metrics
  catalog/datasheets/*.yaml         one datasheet per document corpus (by hand, once per corpus)
  corpus/<corpus>/                  prepared document corpus (acts or decisions)
Output:
  catalog/catalog.json              DCAT-AP CH + DQV (JSON-LD, see dcat.py), one entry per dataset, series or corpus

Per criterion: met or missing, with a finding in words. Nothing is estimated: what cannot be decided from the
available information gets no result.

  python -m documents_mcp.catalog --root .. --fetch   # fetch the current data portal release, then build
  python -m documents_mcp.catalog --root ..           # build only, offline, reproducible
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET

import yaml

from . import bgs, dcat, rrb
from .rules import Results, Rules, combine, met, missing

DATAPORTAL = "https://s3.eu-central-1.amazonaws.com/ch.so.daten-test"
# Interfaces (dcat:DataService). The catalog only names the interface; which tools an application makes of it is
# up to the application (corpus.py).
METRICS = dict(id="metrics", title="Kennzahl-Abfrage über den Semantic Layer (Agentic-BI-Demo 002, AGI)",
               endpoint="http://localhost:8004/mcp",
               description="https://github.com/sogis/dateninfrastruktur-agentic-bi-demo-002")
DOCUMENTS = dict(id="documents", title="Dokumente-Schnittstelle: Lesen, Suchen, Zitieren (Prototyp KI-taugliche Daten)",
                 endpoint="http://localhost:8005/mcp", description="KI-DATEN.md")
MACHINE_READABLE = {"csv", "parquet", "xlsx", "json"}
# Findings from the semantic layer of demo 002 (meta.analytics of the models) -> criterion and finding in words.
SERVER_FINDINGS = {
    "DUPLICATE_KEY": ("identifier", "Schlüssel nicht eindeutig, z. B. eine Gemeindenummer mehrfach (im Daten-Server gesperrt)."),
    "INCOMPATIBLE_GEOGRAPHY": ("validity", "Anderer Gebietsstand als die übrigen Gemeindedaten; nicht kombinierbar."),
    "UNSUPPORTED_PERIOD": ("metrics", "Zeitraster (z. B. Monate) wird vom Semantic Layer der Demo noch nicht unterstützt."),
}


# Data portal -------------------------------------------------------------------
def _path(path: str) -> str:
    return "/".join("{*}" + part for part in path.split("/"))


def _text(element: ET.Element, path: str) -> str | None:
    value = element.findtext(_path(path))
    return value.strip() if value and value.strip() else None


ABBREVIATIONS = {"inkl", "bzw", "ca", "z", "b", "u", "a", "d", "h", "vgl", "nr", "abs", "art", "ggf", "usw", "etc", "evtl"}


def _first_sentence(text: str | None, limit: int = 240) -> str | None:
    """First sentence (German abbreviations like 'inkl.' or 'z. B.' do not end it), at most ``limit`` characters."""
    if not text:
        return None
    text = text.strip()
    sentence = text
    for end in re.finditer(r"[.!?](?=\s)", text):
        word = re.search(r"(\w+)$", text[: end.start()])
        if not (end.group() == "." and word and word.group(1).lower() in ABBREVIATIONS):
            sentence = text[: end.end()]
            break
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rsplit(" ", 1)[0] + " …"


def _period(element: ET.Element) -> dict | None:
    reference_date = _text(element, "temporalCoverage/TemporalCoverage/referenceDate")
    if reference_date:
        return dict(reference_date=reference_date)
    start = _text(element, "temporalCoverage/TemporalCoverage/startDate")
    end = _text(element, "temporalCoverage/TemporalCoverage/endDate")
    return dict(start=start, end=end) if start or end else None


def _office(element: ET.Element, role: str) -> dict | None:
    office = {k: v for k, v in (("name", _text(element, f"{role}/Office/name")),
                                ("abbreviation", _text(element, f"{role}/Office/abbreviation")),
                                ("uri", _text(element, f"{role}/Office/officeUri"))) if v}
    return office or None


def _distributions(element: ET.Element) -> list[dict]:
    return [{k: v for k, v in (("uri", _text(d, "distributionUri")), ("access_url", _text(d, "accessURL")),
                               ("download_url", _text(d, "downloadURL")), ("format", _text(d, "format"))) if v}
            for d in element.findall(_path("distributions/Distribution"))]


def _dataset(element: ET.Element, type_: str) -> dict:
    """Fields of a dataset or series as in the data portal. Contact addresses of persons (contactPoint) are not
    taken over, only the shared address of the office."""
    owner = _office(element, "creator")
    email = _text(element, "creator/Office/email")
    attributes = element.findall(".//" + _path("DatasetAttribute"))
    return dict(
        id=_text(element, "identifier"), title=_text(element, "title"), type=type_,
        description=_first_sentence(_text(element, "description")),
        keywords=[k.text.strip() for k in element.findall(_path("keywords")) if k.text],
        owner=owner, publisher=_office(element, "publisher"),
        contact=dict(name=(owner or {}).get("name"), email=email) if email else None,
        uri=_text(element, "resourceUri"),
        themes=[t.text.strip() for t in element.findall(_path("themes/ThemeAssignment/themeUri")) if t.text],
        issued=_text(element, "issued"), modified=_text(element, "modified"),
        license=_text(element, "licenseUri"),
        update_frequency_uri=_text(element, "accrualPeriodicity/AccrualPeriodicity/frequencyUri"),
        dataportal_access=_text(element, "accessRights/AccessRights/localAccessLevel"),
        period=_period(element), data_model=_text(element, "model"), source=_text(element, "landingPage"),
        attributes=len(attributes), attributes_described=sum(1 for a in attributes if _text(a, "description")),
        distributions=_distributions(element),
        issues=[dict(id=_text(i, "identifier"), label=_text(i, "issueLabel"),
                     current=_text(i, "isCurrentIssue") == "true", distributions=_distributions(i))
                for i in element.findall(_path("issues/DatasetIssue"))],
    )


def read_dataportal(xtf: Path) -> tuple[dict, list[dict]]:
    root = ET.parse(xtf).getroot().find(".//" + _path("Catalog"))
    if root is None:
        raise ValueError(f"{xtf}: kein Catalog-Objekt gefunden.")
    header = dict(title=_text(root, "title"), modified=_text(root, "modified"), source=_text(root, "homepage"))
    datasets = [_dataset(d, "dataset") for d in root.findall(_path("datasets/Dataset"))]
    datasets += [_dataset(s, "series") for s in root.findall(_path("datasetSeries/DatasetSeries"))]
    return header, datasets


def read_licenses(rdf: Path) -> dict[str, str]:
    """Identifier -> license from the DCAT export of the data portal (license per distribution; series appear there
    as their issue). Only unambiguous values."""
    rdf_ns = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
    licenses = {}
    for d in ET.parse(rdf).getroot().iter("{http://www.w3.org/ns/dcat#}Dataset"):
        values = {e.attrib.get(rdf_ns + "resource") for e in d.iter("{http://purl.org/dc/terms/}license")} - {None}
        if len(values) == 1:
            licenses[d.attrib[rdf_ns + "about"].rsplit("/", 1)[-1]] = values.pop()
    return licenses


def add_licenses(datasets: list[dict], licenses: dict[str, str]) -> None:
    for d in datasets:
        if not d["license"]:
            found = {licenses[k] for k in [d["id"]] + [i["id"] for i in d["issues"]] if k in licenses}
            d["license"] = found.pop() if len(found) == 1 else None


def fetch(raw: Path) -> str:
    """Raw stage: store current.json, the catalog of the current release and the DCAT export unchanged."""
    raw.mkdir(parents=True, exist_ok=True)
    pointer = _get(f"{DATAPORTAL}/current.json")
    release = json.loads(pointer)
    (raw / "current.json").write_bytes(pointer)
    (raw / f"published-catalog-{release['releaseId']}.xtf").write_bytes(_get(f"{DATAPORTAL}/{release['catalog']}"))
    (raw / "opendata.rdf").write_bytes(_get(f"{DATAPORTAL}/opendata.rdf"))
    return release["releaseId"]


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as response:
        return response.read()


# Data server of demo 002 -------------------------------------------------------
def data_server(root: Path) -> dict[str, list[dict]]:
    """Catalog identifier -> semantic models in the data server (from models/ and the source manifest of demo 002)."""
    manifest = json.loads((root / "tests/fixtures/real/manifest.json").read_text(encoding="utf-8"))
    identifier = {s["alias"]: s["dataset_identifier"] for s in manifest["sources"]}
    models: dict[str, list[dict]] = {}
    for path in sorted((root / "models").glob("*.yaml")):
        model = yaml.safe_load(path.read_text(encoding="utf-8"))
        analytics = (model.get("meta") or {}).get("analytics") or {}
        if analytics.get("source_id") in identifier:
            models.setdefault(identifier[analytics["source_id"]], []).append(dict(
                model=model["name"], status=analytics.get("status") or "ready",
                reason=analytics.get("status_reason"), temporal_kind=analytics.get("temporal_kind"),
                reference_dates=analytics.get("reference_dates") or {},
            ))
    return models


# Check rules: data ---------------------------------------------------------------
def check_data(raw: dict, models: list[dict], access: str | None) -> Results:
    """Criteria for a dataset of the data portal. Every rule is spelled out here, one line per check."""
    r: dict[str, list[dict]] = {}

    def add(key: str, result: dict) -> None:
        r.setdefault(key, []).append(result)

    distributions = raw["distributions"] + [d for i in raw["issues"] for d in i["distributions"]]
    formats = {d.get("format", "").lower() for d in distributions}
    model = raw["data_model"]
    # Structure
    add("machine_readable", met(f"Download als {', '.join(sorted(formats))}.") if formats & MACHINE_READABLE
        else missing("Kein maschinenlesbares Format im Download."))
    add("fields", met(f"Datenmodell {model}; Anlieferregeln des Datenportals (BFS-Nummer, ISO-Datum).") if model
        else missing("Kein Datenmodell angegeben."))
    deviating = [i["id"] for i in raw["issues"] if i["id"] != f"{raw['id']}_{i['label']}"]
    add("identifier", missing(f"Kennung uneinheitlich: {', '.join(deviating)} statt Muster {raw['id']}_<Jahr>.") if deviating
        else met())
    # Versioning
    add("validity", met() if raw["period"] else missing("Stichtag oder Zeitraum im Datenblatt nicht angegeben."))
    add("changes", met("Änderungsdatum je Datensatz im Katalog.") if raw["modified"] else missing("Kein Änderungsdatum."))
    # Metadata
    if not (raw["title"] and raw["description"]):
        add("description", missing("Titel oder Beschreibung fehlen."))
    elif raw["attributes"] and raw["attributes_described"] < raw["attributes"]:
        add("description", missing(f"Nur {raw['attributes_described']} von {raw['attributes']} Feldern beschrieben."))
    else:
        add("description", met(f"Titel, Beschreibung, {raw['attributes']} Felder beschrieben." if raw["attributes"] else None))
    # Semantics
    ready = sorted({m["model"] for m in models if m["status"] == "ready"})
    add("metrics", met(f"Semantic Layer: {', '.join(ready)}.") if ready
        else missing("Keine Kennzahlen definiert (nicht im Semantic Layer)."))
    # Interfaces
    add("retrievable", met("Download je Datensatz bzw. Jahrgang.") if any(d.get("download_url") for d in distributions)
        else missing("Kein Download angegeben."))
    # Quality
    if model:
        add("quality", met("Lieferung gegen das Datenmodell geprüft."))
    # Permissions
    add("personal_data", missing("Im Datenportal nicht angegeben, ob Personendaten enthalten sind."))
    if access is None:
        add("personal_data", missing(f"Zugriffsstufe unbekannt ({raw['dataportal_access']}), darum als restricted geführt."))
    if access != "open":
        add("legal_basis", missing("Rechtsgrundlage für die Nutzung nicht angegeben."))
    add("license", met(f"Lizenz {raw['license'].rsplit('/', 1)[-1]} (DCAT-Export des Datenportals).") if raw["license"]
        else missing("Keine Lizenz im Datenportal."))
    # Governance
    add("responsibility", met() if raw["owner"] else missing("Kein Eigner angegeben."))
    if not raw["update_frequency_uri"]:
        add("responsibility", missing("Nachführung nicht angegeben."))
    # Findings from the semantic layer of demo 002
    for m in models:
        without_date = sorted(year for year, day in m["reference_dates"].items() if day is None)
        if m["temporal_kind"] == "stock" and without_date:
            add("validity", missing(f"Bestandsgrösse ohne Stichtag (Jahr {', '.join(without_date)}): Vergleich mit "
                                    "anderen Bestandszahlen nur mit Vorbehalt."))
        if m["status"] != "ready":
            key, text = SERVER_FINDINGS.get(m["reason"], ("quality", f"Im Daten-Server gesperrt ({m['reason']})."))
            add(key, missing(text))
            if m["status"] == "quarantined":
                add("quality", missing("Im Daten-Server in Quarantäne (bekannter Datenfehler)."))
    return {k: combine(v) for k, v in r.items()}


def data_entry(raw: dict, server: dict[str, list[dict]], rules: Rules) -> dict:
    identifiers = [raw["id"]] + [i["id"] for i in raw["issues"]]
    models = [m for k in identifiers for m in server.get(k, [])]
    access = rules.access_from_dataportal(raw["dataportal_access"])
    results = check_data(raw, models, access)
    access = access or "restricted"  # unknown means not public
    entry = {k: v for k, v in raw.items() if k not in ("dataportal_access", "attributes", "attributes_described")}
    if any(m["status"] == "ready" for m in models):
        entry["distributions"] = raw["distributions"] + [dict(title="Kennzahl-Abfrage", access_url=METRICS["endpoint"],
                                                              service=METRICS["id"])]
    return dict(entry, kind="data", access=access, criteria=results)


# Check rules: document corpora -------------------------------------------------------
CORPORA = {
    # document type -> how the corpus is checked per document
    "legal_text": dict(checks=bgs.CHECKS, name=lambda a: a["number"]),
    "decision": dict(checks=rrb.CHECKS, name=lambda d: d["number"]),
}


def read_documents(document_type: str, directory: Path) -> list[dict]:
    if document_type == "legal_text":
        return sorted((json.loads(p.read_text(encoding="utf-8")) for p in directory.glob("*/act.json")),
                      key=lambda a: [int(x) for x in re.findall(r"\d+", a["number"])])
    path = directory / "decisions.json"
    if not path.exists():
        raise ValueError(f"{path} fehlt (nur lokal): python -m documents_mcp.rrb <jahr> --target {directory}")
    return json.loads(path.read_text(encoding="utf-8"))


def _decision_coverage(documents: list[dict]) -> str:
    public = [d for d in documents if d["public"]]
    hidden = len(documents) - len(public)
    dates = sorted(d["date"] for d in documents if d["date"])
    return (f"Die Quelle sagt nicht, was fehlt. Im Abruf ({dates[0]} bis {dates[-1]}): {hidden} von {len(documents)} "
            f"Beschlüssen ({round(100 * hidden / len(documents))} %) nicht öffentlich, nur Felder.")


def check_corpus(sheet: dict, rules: Rules, documents: list[dict]) -> tuple[Results, dict[str, list[str]]]:
    """Criteria for a document corpus: document profile (source and per document) plus datasheet information."""
    document_type = sheet["document_type"]
    profile, per_document = rules.check_profile(document_type, sheet.get("source_provides") or {}, documents,
                                                CORPORA[document_type]["checks"], CORPORA[document_type]["name"])
    r: dict[str, list[dict]] = {k: [v] for k, v in profile.items()}

    def add(key: str, result: dict) -> None:
        r.setdefault(key, []).append(result)

    # Metadata
    add("description", met() if sheet.get("title") and sheet.get("description")
        else missing("Titel oder Beschreibung fehlen."))
    # Quality
    if sheet.get("completeness") or sheet.get("accuracy"):
        add("quality", met(" ".join(filter(None, [sheet.get("completeness"), sheet.get("accuracy")]))))
    elif document_type == "decision":
        add("quality", missing(_decision_coverage(documents)))
    # Permissions
    personal_data = sheet.get("personal_data")
    add("personal_data", met(f"Personendaten: {personal_data}.") if personal_data
        else missing("Im Datenblatt fehlt, ob Personendaten enthalten sind."))
    if sheet["access"] != "open":
        add("legal_basis", met(sheet["legal_basis"]) if sheet.get("legal_basis")
            else missing("Rechtsgrundlage für die Nutzung nicht im Datenblatt."))
    license_ = sheet.get("license") or ""
    add("license", met() if license_.startswith("http") else missing(f"Keine Lizenz-Adresse. {license_}".strip()))
    # Governance (the owner is a mandatory field of the datasheet)
    add("responsibility", met(sheet["update_frequency"]) if sheet.get("update_frequency")
        else missing("Nachführung nicht angegeben."))
    return {k: combine(v) for k, v in r.items()}, per_document


INHERITED = ("document_type", "corpus", "source_provides", "owner", "source", "license", "update_frequency")
REQUIRED = ("id", "title", "document_type", "access", "owner", "corpus")


def corpus_entry(sheet: dict, rules: Rules, directory: Path, parent: dict | None = None) -> dict:
    if parent:  # part of a corpus (e.g. the distribution list): source information from the parent datasheet
        sheet = {**{k: parent[k] for k in INHERITED if k in parent}, **sheet}
    for field in REQUIRED:
        if not sheet.get(field):
            raise ValueError(f"Datenblatt {sheet.get('id', '?')}: Pflichtfeld '{field}' fehlt.")
    if sheet["document_type"] not in rules.profiles:
        raise ValueError(f"Datenblatt {sheet['id']}: kein Dokumentprofil '{sheet['document_type']}' in rules/.")
    if sheet["access"] not in rules.access["levels"]:
        raise ValueError(f"Datenblatt {sheet['id']}: unbekannte Zugriffsstufe '{sheet['access']}'.")
    unknown = set(sheet.get("source_provides") or {}) - set(rules.profiles[sheet["document_type"]]["requirements"]) - {"checked"}
    if unknown:
        raise ValueError(f"Datenblatt {sheet['id']}: source_provides kennt das Dokumentprofil nicht: {sorted(unknown)}.")
    documents = read_documents(sheet["document_type"], directory)
    results, _ = check_corpus(sheet, rules, documents)
    retrieved = [d["retrieved"][:10] for d in documents if d.get("retrieved")]
    return dict(
        id=sheet["id"], type="corpus", kind="documents", title=sheet["title"],
        description=" ".join(sheet["description"].split()),
        document_type=sheet["document_type"], document_profile=sheet["document_type"],
        owner=sheet["owner"], publisher=sheet.get("publisher"), access=sheet["access"],
        license=sheet.get("license"), update_frequency=sheet.get("update_frequency"), source=sheet.get("source"),
        keywords=sheet.get("keywords"), part_of=sheet.get("part_of"),
        modified=max(retrieved) if retrieved else None,
        distributions=list(sheet.get("distributions") or [])
        + [dict(title="Dokumente-Schnittstelle (Prototyp)", access_url=DOCUMENTS["endpoint"], service=DOCUMENTS["id"])],
        criteria=results,
    )


# Build ----------------------------------------------------------------------------
def datasheets(root: Path) -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((root / "catalog/datasheets").glob("*.yaml"))]


def build(root: Path, target: Path | None = None) -> dict:
    rules = Rules.load(root / "rules")
    raw = root / "catalog/raw/dataportal"
    release = json.loads((raw / "current.json").read_text(encoding="utf-8"))
    header, datasets = read_dataportal(raw / f"published-catalog-{release['releaseId']}.xtf")
    rdf = raw / "opendata.rdf"
    if not rdf.exists():
        raise ValueError(f"{rdf} fehlt: python -m documents_mcp.catalog --root .. --fetch")
    add_licenses(datasets, read_licenses(rdf))
    server = data_server(root)
    known = {k for d in datasets for k in [d["id"]] + [i["id"] for i in d["issues"]]}
    for unknown in sorted(set(server) - known):
        print(f"Warnung: {unknown} ist im Daten-Server, aber nicht im Datenportal-Katalog.", flush=True)
    records = [data_entry(d, server, rules) for d in sorted(datasets, key=lambda d: d["id"])]
    sheets = {s["id"]: s for s in datasheets(root)}
    for sheet in sheets.values():
        parent = sheets[sheet["part_of"]] if sheet.get("part_of") else None
        records.append(corpus_entry(sheet, rules, root / "corpus" / (sheet.get("corpus") or parent["corpus"]), parent))
    services = [
        dcat.service(METRICS["id"], METRICS["title"], METRICS["endpoint"], METRICS["description"],
                     [r["id"] for r in records if any(d.get("service") == METRICS["id"] for d in r["distributions"])]),
        dcat.service(DOCUMENTS["id"], DOCUMENTS["title"], DOCUMENTS["endpoint"], DOCUMENTS["description"],
                     [r["id"] for r in records if r["kind"] == "documents"]),
    ]
    result = dcat.catalog(
        "Gemeinsamer Katalog für Daten und Dokumente (Prototyp KI-taugliche Daten)",
        max(filter(None, [header["modified"]] + [r.get("modified") for r in records])),
        [dcat.to_dcat(r, rules) for r in records], services,
        provenance=dict(dataportal=dict(release=release["releaseId"], modified=header["modified"], source=header["source"],
                                        dcat_export=hashlib.sha256(rdf.read_bytes()).hexdigest()),
                        datasheets=sorted(f"{s}.yaml" for s in sheets), rules="rules/"),
    )
    target = target or root / "catalog/catalog.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemeinsamen Katalog bauen.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Wurzel des Repos")
    parser.add_argument("--fetch", action="store_true", help="Zuerst den aktuellen Datenportal-Release holen.")
    args = parser.parse_args()
    if args.fetch:
        print(f"Datenportal-Release {fetch(args.root / 'catalog/raw/dataportal')} abgerufen.", flush=True)
    result = build(args.root)
    rules = Rules.load(args.root / "rules")
    views = [dcat.view(e, rules) for e in result["dcat:dataset"]]
    gaps = Counter(m["name"] for v in views for m in v.get("missing", []))
    complete = [v["id"] for v in views if not v.get("missing")]
    standard = Counter(g for e in result["dcat:dataset"] for g in dcat.standard_gaps(e))
    print(f"Katalog Stand {result['dct:modified']}: {Counter(v['kind'] for v in views)}", flush=True)
    print(f"Häufigste Lücken (Anzahl Quellen): {gaps.most_common(6)}", flush=True)
    print(f"Ohne Lücke: {complete or 'keine'}", flush=True)
    print(f"DCAT-AP CH, fehlt für die Veröffentlichung: {dict(standard)}", flush=True)


if __name__ == "__main__":
    main()
