"""Government council decisions: fetch parsers, preparation, catalog entry and distribution list as its own dataset.

All decisions here are invented (year 2099, persons "Erika Muster"); the markup follows rrb.so.ch (30.10.2026).
"""

import json
from pathlib import Path

import pytest

from documents_mcp import dcat
from documents_mcp.access import Person
from documents_mcp.catalog import corpus_entry, datasheets
from documents_mcp.corpus import Corpus, ToolError
from documents_mcp.rrb import offices_from_distribution_list, prepare, read_detail, read_list, split_text
from documents_mcp.rules import Rules
from test_corpus import CATALOG, CORPUS, ROOT, RULES

LIST = """<p>1 bis 3 von 3</p><table><thead><tr><th>Sitzungsdatum</th></tr></thead><tbody>
<tr><td>05.01.2099</td><td><a href="/beschlussnummer/2099_1/">2099/1</a></td><td>Sachgeschäft</td>
<td>Departement des Innern</td><td>Vernehmlassung zum Musterschutzgesetz; Schreiben an das Bundesamt</td></tr>
<tr><td>05.01.2099</td><td>2099/2</td><td>Sachgeschäft</td><td>Finanzdepartement</td><td>Personalangelegenheit</td></tr>
<tr><td>12.01.2099</td><td>2099/3</td><td>Sachgeschäft</td><td>Bau- und Justizdepartement</td>
<td>Gemeinde Musterdorf: Genehmigung Reglement</td></tr>
<tr><td>kaputt</td></tr></tbody></table>"""

PUBLIC = """<table><tr><td>Dokumente</td><td><ul><li>
<a class="rrb_download" rel="nofollow" href="/beschlussnummer/{n}/download/abc/?fn=rrb&amp;cHash=1">RRB</a></li>
<li><a class="rrb_download" href="/beschlussnummer/{n}/download/def/?fn=brief">RR-Brief</a></li></ul></td></tr></table>"""
NOT_PUBLIC = """<table><tr><td>Dokumente
                        </td>
                        <td>
                            nicht öffentlich
             </td></tr></table>"""

TEXT_1 = """Regierungsratsbeschluss                                vom    5. Januar 2099
                                                       Nr.    2099/1

Vernehmlassung zum Musterschutzgesetz

1.        Erwägungen

Das Departement des Innern (Gesundheitsamt) unterbreitet das Schreiben. Massgebend ist
das Gesetz über die Motorfahrzeugsteuern (BGS 614.61).

2.        Beschluss

Das Schreiben wird beschlossen.

Verteiler

Departement des Innern (kein Papierversand)
Gesundheitsamt (kein Papierversand, Zustellung durch DS DDI)
Erika Muster, Musterweg 1, 4500 Solothurn
"""
TEXT_3 = """Regierungsratsbeschluss vom 12. Januar 2099 Nr. 2099/3

Gemeinde Musterdorf: Genehmigung Reglement über die Abfallentsorgung. Das Reglement wird genehmigt.
Es stützt sich auf BGS 711.1 und BGS 614.61. """ + "Weitere Erwägungen zum Reglement. " * 10 + """

Vertei ler

Bau- und Justizdepartement
Amt für Umwelt (Xy)
Einwohnergemeinde Musterdorf, Hauptstrasse 1,
4500 Musterdorf
"""


@pytest.fixture
def rrb(tmp_path) -> Path:
    target = tmp_path / "rrb"
    (target / "raw/list").mkdir(parents=True)
    (target / "raw/decisions").mkdir()
    (target / "raw/list/2099-0001.html").write_text(LIST, encoding="utf-8")
    pages = {"2099_1": PUBLIC.format(n="2099_1"), "2099_2": NOT_PUBLIC, "2099_3": PUBLIC.format(n="2099_3")}
    for name, page in pages.items():
        (target / f"raw/decisions/{name}.html").write_text(page, encoding="utf-8")
    (target / "raw/decisions/2099_1.txt").write_text(TEXT_1, encoding="utf-8")
    (target / "raw/decisions/2099_3.txt").write_text(TEXT_3, encoding="utf-8")
    prepare(target)
    return target


SHEETS = {s["id"]: s for s in datasheets(ROOT)}
RULESET = Rules.load(RULES)


def test_parse_list_and_detail():
    total, rows = read_list(LIST)
    assert total == 3 and [r["number"] for r in rows] == ["2099/1", "2099/2", "2099/3"]
    assert rows[0] == dict(number="2099/1", date="2099-01-05", business_type="Sachgeschäft",
                           lead_department="Departement des Innern",
                           title="Vernehmlassung zum Musterschutzgesetz; Schreiben an das Bundesamt")
    public = read_detail(PUBLIC.format(n="2099_1"))
    assert public["public"] and public["documents"][0].endswith("/download/abc/?fn=rrb&cHash=1")
    assert read_detail(NOT_PUBLIC) == dict(public=False, documents=[])


def test_text_without_distribution_list():
    text, distribution_list = split_text(TEXT_1)
    assert "Das Schreiben wird beschlossen." in text and "Muster" not in text.split("beschlossen.")[1]
    assert "Erika" not in text and len(distribution_list) == 3


def test_prepare_features(rrb):
    decisions = {d["number"]: d for d in json.loads((rrb / "decisions.json").read_text(encoding="utf-8"))}
    assert decisions["2099/1"]["offices"] == ["Departement des Innern", "Gesundheitsamt"]  # no private person
    assert decisions["2099/1"]["bgs"] == ["614.61"]
    assert decisions["2099/3"]["offices"] == ["Amt für Umwelt", "Bau- und Justizdepartement"]  # "Vertei ler" found
    assert decisions["2099/3"]["bgs"] == ["614.61", "711.1"]
    assert not decisions["2099/2"]["public"] and "text" not in decisions["2099/2"]
    assert decisions["2099/1"]["no_text_layer"] is False


def test_catalog_entry(rrb):
    entry = corpus_entry(SHEETS["rrb"], RULESET, rrb)
    c = entry["criteria"]
    assert c["retrievable"]["value"] is False and c["machine_readable"]["value"] is True  # text layer is enough
    assert "1 von 3 Beschlüssen (33 %) nicht öffentlich" in c["quality"]["finding"]
    assert "Verteiler als eigenes Feld" in c["fields"]["finding"]
    part = corpus_entry(SHEETS["rrb-distribution-list"], RULESET, rrb, parent=SHEETS["rrb"])
    assert part["access"] == "restricted" and part["part_of"] == "rrb"
    assert part["criteria"]["legal_basis"]["value"] is False and part["owner"]["abbreviation"] == "STK"


@pytest.fixture
def corpus(rrb, tmp_path):
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    own = [dcat.to_dcat(corpus_entry(SHEETS["rrb"], RULESET, rrb), RULESET),
           dcat.to_dcat(corpus_entry(SHEETS["rrb-distribution-list"], RULESET, rrb, SHEETS["rrb"]), RULESET)]
    raw["dcat:dataset"] = [e for e in raw["dcat:dataset"] if not e["dct:identifier"].startswith("rrb")] + own
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    directory = tmp_path / "corpus"
    directory.mkdir()
    (directory / "bgs").symlink_to(CORPUS / "bgs")
    (directory / "rrb").symlink_to(rrb)
    return Corpus(catalog, directory, RULES, tmp_path / "access")


def test_search_decisions(corpus):
    assert corpus.search_decisions(office="gesundheitsamt")["count"] == 1
    assert [d["number"] for d in corpus.search_decisions(bgs_number="BGS 614.61")["decisions"]] == ["2099/3", "2099/1"]
    assert corpus.search_decisions(department="Finanz")["decisions"][0]["note"].startswith("Dokumente")
    assert corpus.search_decisions(date_from="2099-01-10")["count"] == 1
    hits = corpus.search_decisions("Abfallentsorgung")["decisions"]
    assert [d["number"] for d in hits] == ["2099/3"] and "«" in hits[0]["excerpt"]
    assert corpus.search_decisions("Erika")["count"] == 0  # the distribution list is not searchable


def test_distribution_list_only_with_grant(corpus):
    public = corpus.get_decision("2099/1")
    assert "distribution_list" not in public and "rrb-distribution-list" in public["distribution_list_note"]
    assert public["offices"] == ["Departement des Innern", "Gesundheitsamt"]
    anna = Person.of("anna@so.ch", "intern")
    assert "distribution_list" not in corpus.get_decision("2099/1", person=anna)  # group alone is not enough
    corpus.access.directory.mkdir(parents=True, exist_ok=True)
    (corpus.access.directory / "grants.yaml").write_text("rrb-distribution-list: [group:intern]\n", encoding="utf-8")
    granted = corpus.get_decision("RRB 2099_1", person=anna)
    assert any("Erika Muster" in line for line in granted["distribution_list"])
    hidden = corpus.get_decision("2099/2")
    assert "text" not in hidden and "nicht öffentlich" in hidden["note"]
    with pytest.raises(ToolError, match="nicht im Bestand"):
        corpus.get_decision("2099/9")
    entries = corpus.catalog("Regierungsrat Beschluss")["entries"]
    assert {e["id"] for e in entries} >= {"rrb", "rrb-distribution-list"}
    assert next(e for e in entries if e["id"] == "rrb")["contents"]["decisions"] == 3


def test_offices_also_after_the_department():
    lines = ["Departement des Innern, Gesundheitsamt, (kein Papierversand)", "Amt für Wald, Jagd und Fischerei",
             "Kantonales Steueramt", "Max Muster, Musterweg 1, 4500 Solothurn"]
    assert offices_from_distribution_list(lines) == ["Amt für Wald, Jagd und Fischerei", "Departement des Innern",
                                                     "Gesundheitsamt", "Kantonales Steueramt"]
