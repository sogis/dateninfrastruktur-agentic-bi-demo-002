"""Catalog build: read the data portal, criteria for data and document corpora, DCAT-AP CH + DQV, reproducibility."""

import json
from pathlib import Path

import pytest

from documents_mcp import dcat
from documents_mcp.catalog import (add_licenses, build, corpus_entry, data_entry, datasheets, read_dataportal,
                                   read_licenses)
from documents_mcp.rules import Rules

ROOT = Path(__file__).resolve().parents[2]
RULES = Rules.load(ROOT / "rules")

# Excerpt in the structure of the data portal catalog (SO_AGI_DataCatalog_PublishedCatalog), values invented.
XTF = """<?xml version="1.0" encoding="UTF-8"?>
<ili:transfer xmlns:ili="http://www.interlis.ch/xtf/2.4/INTERLIS" xmlns:P="http://example.org/P" xmlns:B="http://example.org/B">
<ili:datasection><P:Publication ili:bid="b"><P:Catalog ili:tid="c">
 <P:title>Datenportal Test</P:title><P:homepage>https://example.org</P:homepage><P:modified>2026-10-16</P:modified>
 <P:datasets><P:Dataset>
  <P:identifier>ch.so.test.flaeche</P:identifier><P:title>Fläche nach Gemeinde</P:title>
  <P:description>Erster Satz. Zweiter Satz.</P:description>
  <P:creator><P:Office><P:name>Amt für Test</P:name><P:abbreviation>AFT</P:abbreviation></P:Office></P:creator>
  <P:contactPoint><B:ContactPoint><B:email>mailto:vorname.name@example.org</B:email></B:ContactPoint></P:contactPoint>
  <P:keywords>Fläche</P:keywords><P:modified>2026-10-15</P:modified>
  <P:accessRights><P:AccessRights><P:localAccessLevel>internal</P:localAccessLevel></P:AccessRights></P:accessRights>
  <P:temporalCoverage><B:TemporalCoverage><B:referenceDate>2025-12-31</B:referenceDate></B:TemporalCoverage></P:temporalCoverage>
  <P:model>SO_Test_20261015</P:model><P:landingPage>https://example.org/flaeche</P:landingPage>
  <P:attributes><B:DatasetAttribute><B:name>BFS_NR</B:name><B:description>BFS-Nummer</B:description></B:DatasetAttribute>
   <B:DatasetAttribute><B:name>FLAECHE</B:name></B:DatasetAttribute></P:attributes>
  <P:distributions><P:Distribution><P:downloadURL>https://s3.eu-central-1.amazonaws.com/x/f.csv</P:downloadURL><P:format>csv</P:format></P:Distribution></P:distributions>
 </P:Dataset></P:datasets>
 <P:datasetSeries><P:DatasetSeries>
  <P:identifier>ch.so.test.reihe</P:identifier><P:title>Reihe</P:title>
  <P:accessRights><P:AccessRights><P:localAccessLevel>open</P:localAccessLevel></P:AccessRights></P:accessRights>
  <P:issues>
   <P:DatasetIssue><P:identifier>ch.so.test.reihe_2024</P:identifier><P:issueLabel>2024</P:issueLabel><P:isCurrentIssue>false</P:isCurrentIssue></P:DatasetIssue>
   <P:DatasetIssue><P:identifier>ch.so.test.reihe-2025</P:identifier><P:issueLabel>2025</P:issueLabel><P:isCurrentIssue>true</P:isCurrentIssue>
    <P:distributions><P:Distribution><P:downloadURL>https://example.org/r.parquet</P:downloadURL><P:format>parquet</P:format></P:Distribution></P:distributions></P:DatasetIssue>
  </P:issues>
 </P:DatasetSeries></P:datasetSeries>
</P:Catalog></P:Publication></ili:datasection></ili:transfer>
"""


@pytest.fixture
def dataportal(tmp_path):
    path = tmp_path / "catalog.xtf"
    path.write_text(XTF, encoding="utf-8")
    return read_dataportal(path)


# Excerpt in the structure of the DCAT export (opendata.rdf): license per distribution, series as their issue.
RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dcat="http://www.w3.org/ns/dcat#" xmlns:dct="http://purl.org/dc/terms/">
 <dcat:Catalog><dcat:dataset>
  <dcat:Dataset rdf:about="https://data.so.ch/dataset/ch.so.test.reihe-2025"><dcat:distribution><dcat:Distribution>
   <dct:license rdf:resource="http://dcat-ap.ch/vocabulary/licenses/terms_open"/></dcat:Distribution></dcat:distribution>
  </dcat:Dataset></dcat:dataset></dcat:Catalog>
</rdf:RDF>
"""


def test_license_from_dcat_export(dataportal, tmp_path):
    path = tmp_path / "opendata.rdf"
    path.write_text(RDF, encoding="utf-8")
    _, (area, series) = dataportal
    add_licenses([area, series], read_licenses(path))
    assert series["license"] == "http://dcat-ap.ch/vocabulary/licenses/terms_open"  # found via the issue
    assert area["license"] is None
    assert data_entry(series, {}, RULES)["criteria"]["license"]["value"] is True


def model(status="ready", reason=None, temporal_kind="stock", reference_dates=None):
    return dict(model="m", status=status, reason=reason, temporal_kind=temporal_kind,
                reference_dates=reference_dates or {"2025": "2025-12-31"})


def test_read_dataportal_without_personal_addresses(dataportal):
    header, (area, series) = dataportal
    assert header["modified"] == "2026-10-16"
    assert area["owner"] == dict(name="Amt für Test", abbreviation="AFT") and area["description"] == "Erster Satz."
    assert area["period"] == dict(reference_date="2025-12-31") and (area["attributes"], area["attributes_described"]) == (2, 1)
    assert [i["id"] for i in series["issues"]] == ["ch.so.test.reihe_2024", "ch.so.test.reihe-2025"]
    assert series["issues"][1]["distributions"][0]["format"] == "parquet"  # downloads belong to the issue
    assert "@" not in json.dumps(dataportal)


def test_criteria_data(dataportal):
    _, (area, series) = dataportal
    ready = data_entry(area, {"ch.so.test.flaeche": [model()]}, RULES)
    c = ready["criteria"]
    assert ready["access"] == "restricted"  # internal in the data portal
    assert c["description"] == dict(value=False, finding="Nur 1 von 2 Feldern beschrieben.")
    assert c["metrics"]["value"] is True and c["license"]["value"] is False
    assert c["legal_basis"]["value"] is False  # restricted (internal) without legal basis
    assert set(c) <= set(RULES.criteria)
    assert any(d.get("service") == "metrics" for d in ready["distributions"])
    without_date = data_entry(area, {"ch.so.test.flaeche": [model(reference_dates={"2025": None})]}, RULES)
    assert "ohne Stichtag" in without_date["criteria"]["validity"]["finding"]
    locked = data_entry(area, {"ch.so.test.flaeche": [model("quarantined", "DUPLICATE_KEY")]}, RULES)
    assert locked["criteria"]["identifier"]["value"] is False and locked["criteria"]["quality"]["value"] is False
    assert not any(d.get("service") for d in locked["distributions"])
    not_in_server = data_entry(series, {}, RULES)
    c = not_in_server["criteria"]
    assert not_in_server["access"] == "open" and c["machine_readable"]["value"] and c["fields"]["value"] is False
    assert "ch.so.test.reihe-2025 statt Muster" in c["identifier"]["finding"] and c["metrics"]["value"] is False
    assert "Kein Eigner" in c["responsibility"]["finding"] and "legal_basis" not in c  # open
    assert "quality" not in c  # without a data model not decidable: no result


def bgs_sheet(**change):
    return dict(next(s for s in datasheets(ROOT) if s["id"] == "bgs"), **change)


def test_criteria_corpus_bgs():
    entry = corpus_entry(bgs_sheet(), RULES, ROOT / "corpus/bgs")
    c = entry["criteria"]
    assert "(614.62)" in c["machine_readable"]["finding"]
    assert c["validity"]["value"] is False and "Datumsfeld" in c["validity"]["finding"]
    assert c["retrievable"]["value"] is True and c["license"]["value"] is False and c["personal_data"]["value"] is True
    better = corpus_entry(bgs_sheet(source_provides=dict(bgs_sheet()["source_provides"], validity_as_date=True)),
                          RULES, ROOT / "corpus/bgs")
    assert better["criteria"]["validity"]["value"] is True  # the source provides it: gap closed
    assert entry["document_profile"] == "legal_text" and entry["modified"] == "2026-10-30"
    with pytest.raises(ValueError, match="owner"):
        corpus_entry(bgs_sheet(owner=None), RULES, ROOT / "corpus/bgs")
    with pytest.raises(ValueError, match="Zugriffsstufe"):
        corpus_entry(bgs_sheet(access="internal"), RULES, ROOT / "corpus/bgs")
    with pytest.raises(ValueError, match="kennt das Dokumentprofil nicht"):
        corpus_entry(bgs_sheet(source_provides=dict(invented=True)), RULES, ROOT / "corpus/bgs")
    with pytest.raises(ValueError, match="kein Dokumentprofil"):
        corpus_entry(bgs_sheet(document_type="directive"), RULES, ROOT / "corpus/bgs")


@pytest.mark.skipif(not (ROOT / "catalog/raw/dataportal/current.json").exists()
                    or not (ROOT / "catalog/raw/dataportal/opendata.rdf").exists()
                    or not (ROOT / "corpus/rrb/decisions.json").exists(),
                    reason="Roh-Stufe des Datenportals oder Bestand RRB fehlt (beide nur lokal, siehe KI-DATEN.md)")
def test_catalog_reproducible(tmp_path):
    rebuilt = build(ROOT, tmp_path / "catalog.json")
    assert rebuilt == json.loads((ROOT / "catalog/catalog.json").read_text(encoding="utf-8"))


def test_catalog_standard_only():
    """The versioned catalog is DCAT-AP CH + DQV; custom are only vocabularies under so:, no fields."""
    raw = json.loads((ROOT / "catalog/catalog.json").read_text(encoding="utf-8"))
    assert raw["@type"] == "dcat:Catalog" and set(raw["@context"]) == {"dcat", "dct", "foaf", "vcard", "dqv", "rdfs", "so"}

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    prefixes = {k.split(":")[0] for k in keys(raw["dcat:dataset"]) if not k.startswith("@")}
    assert prefixes <= {"dcat", "dct", "foaf", "vcard", "dqv", "rdfs"}
    assert "server" not in json.dumps(raw["dcat:dataset"]) and "tool" not in json.dumps(raw["dcat:dataset"])
    views = {e["dct:identifier"]: dcat.view(e, RULES) for e in raw["dcat:dataset"]}
    vehicles = views["ch.so.fahrzeugbestand"]
    assert [m["name"] for m in vehicles["missing"]] == ["Stand und Gültigkeit", "Personendaten bekannt"]
    assert "Lizenz" in vehicles["met"] and "dct:license" in next(
        e for e in raw["dcat:dataset"] if e["dct:identifier"] == "ch.so.fahrzeugbestand")
    assert vehicles["missing"][0]["finding"] and "Kennzahlen definiert" in vehicles["met"]
    assert "Maschinenlesbar" in [m["name"] for m in views["bgs"]["missing"]]
    assert views["rrb-distribution-list"]["access"] == "restricted"
    assert views["rrb-distribution-list"]["part_of"] == "rrb"
    services = {s["dct:identifier"]: s for s in raw["dcat:service"]}
    assert {"@id": dcat.entry_id("bgs")} in services["documents"]["dcat:servesDataset"]
    agi = next(e for e in raw["dcat:dataset"] if e["dct:identifier"] == "ch.so.abstimmungsresultate")
    assert agi["@id"].startswith("https://data.so.ch/") and agi["dct:publisher"]["dct:identifier"] == "AGI"
    gaps = {e["dct:identifier"]: dcat.standard_gaps(e) for e in raw["dcat:dataset"]}
    assert all(not v for k, v in gaps.items() if k.startswith("ch.so."))  # data: license from the DCAT export
    assert gaps["bgs"] == ["dct:license"]  # documents: no license given by the source
