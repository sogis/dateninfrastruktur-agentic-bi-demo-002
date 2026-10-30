"""Documents server logic against the real, prepared acts under corpus/bgs/ and the built catalog."""

import json
from pathlib import Path

import pytest

from documents_mcp.access import Person
from documents_mcp.corpus import Corpus, ToolError

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "catalog" / "catalog.json"
CORPUS = ROOT / "corpus"
RULES = ROOT / "rules"


@pytest.fixture(scope="module")
def corpus():
    return Corpus(CATALOG, CORPUS, RULES)


def test_catalog_overview_and_search(corpus):
    overview = {e["id"]: e for e in corpus.catalog()["entries"]}
    assert overview["ch.so.fahrzeugbestand"]["kind"] == "data" and overview["bgs"]["kind"] == "documents"
    assert "Lizenz" in overview["bgs"]["missing"] and "met" not in overview["bgs"]  # overview is short
    vehicles = corpus.catalog("Fahrzeugbestand")["entries"][0]
    assert vehicles["id"] == "ch.so.fahrzeugbestand" and "search" in vehicles["in_this_chat"]["tools"]
    assert vehicles["missing"][0]["name"] == "Stand und Gültigkeit" and "Stichtag" in vehicles["missing"][0]["finding"]
    laws = corpus.catalog("Motorfahrzeugsteuer")["entries"][0]
    assert laws["id"] == "bgs" and laws["in_this_chat"]["tools"] == "search_laws, get_section, get_changes"
    acts = {a["number"]: a for a in laws["contents"]["acts"]}
    assert set(acts) == {"614.61", "614.62", "733.11"} and "profile_missing" not in acts["614.61"]
    assert any("nicht nur als PDF" in m for m in acts["614.62"]["profile_missing"])
    download = next(e for e in corpus.catalog("Sozialhilfe", limit=20)["entries"] if e["id"] == "ch.so.sozialhilfe_kanton")
    assert "nur als Download" in download["in_this_chat"]["note"]


def test_version_by_date(corpus):
    assert corpus.version_at("614.61", "2022-06-01")["id"] == "4993"
    assert corpus.version_at("614.61", "2023-01-01")["id"] == "5302"
    with pytest.raises(ToolError, match="keine Fassung"):
        corpus.version_at("614.61", "1980-01-01")


def test_section_differs_between_versions(corpus):
    old = corpus.get_section("614.61", "§ 5", "2022-06-01")
    new = corpus.get_section("BGS 614.61", "5", "2024-01-01")
    assert "§ 7 Absätze 2 und 3" in old["text"] and "§ 9 des Gesetzes" in new["text"]
    assert new["version"]["valid_from"] == "2023-01-01"
    assert new["citation"].startswith("§ 5, Gesetz über die Steuern und Gebühren")


def test_pdf_version_carries_note(corpus):
    s1 = corpus.get_section("614.62", "1")
    assert s1["version"]["structure"] == "pdf-heuristic" and "Original-PDF" in s1["version"]["note"]
    assert "20. November 1959)" in s1["text"]


def test_search_finds_word_parts_in_valid_version(corpus):
    hits = corpus.search_laws("Motorfahrzeugsteuererträge", date="2024-01-01", act="614.61")["hits"]
    assert hits[0]["section"] == "5" and hits[0]["version"]["id"] == "5302"
    assert corpus.search_laws("Kantonspolizei", act="733.11")["hits"]


def test_changes_per_section(corpus):
    rows = corpus.get_changes("733.11", "3")["changes"]
    assert {r["element"] for r in rows} == {"§ 3 Abs. 1, e)", "§ 3 Abs. 1, a)"}
    assert all(not r["element"].startswith("§ 30") for r in rows)
    assert "note" in corpus.get_changes("614.62")


def test_unknown_input(corpus):
    with pytest.raises(ToolError, match="nicht im Bestand"):
        corpus.get_section("999.9", "1")
    with pytest.raises(ToolError, match="JJJJ-MM-TT"):
        corpus.search_laws("Steuer", date="1.1.2024")


def restricted_catalog(tmp_path, identifier="bgs") -> Path:
    """Real catalog with one dataset set to restricted (tests only)."""
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    for e in raw["dcat:dataset"]:
        if e["dct:identifier"] == identifier:
            e["dct:accessRights"] = {"@id": "http://publications.europa.eu/resource/authority/access-right/RESTRICTED"}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def test_rights_per_person(tmp_path):
    corpus = Corpus(restricted_catalog(tmp_path), CORPUS, RULES, tmp_path / "access")
    anna, stk = Person.of("anna@so.ch"), Person.of("ben@so.ch", "Staatskanzlei")
    entry = corpus.catalog("Gesetzessammlung")["entries"][0]  # restricted stays findable
    assert entry["id"] == "bgs" and "Staatskanzlei" in entry["in_this_chat"]["note"] and "contents" not in entry
    with pytest.raises(ToolError, match="Freigeben kann der Eigner: Staatskanzlei"):
        corpus.get_section("733.11", "3", person=stk)
    with pytest.raises(ToolError, match="nur mit Freigabe"):
        corpus.search_laws("Fahrzeug")
    (tmp_path / "access").mkdir(exist_ok=True)
    (tmp_path / "access/grants.yaml").write_text("bgs: [group:staatskanzlei]\n", encoding="utf-8")
    assert corpus.get_section("733.11", "3", person=stk)["act"] == "733.11"     # without restart
    assert corpus.catalog("Gesetzessammlung", person=stk)["entries"][0]["contents"]
    with pytest.raises(ToolError, match="nur mit Freigabe"):
        corpus.get_section("733.11", "3", person=anna)
    audit = (tmp_path / "access/audit.jsonl").read_text().splitlines()
    assert [json.loads(line)["allowed"] for line in audit] == [False, False, True, False]
