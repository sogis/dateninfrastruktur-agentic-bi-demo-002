"""Parsers for BGS XHTML and PDF text. Small excerpts in the structure of the real BGS output (derived test
data); the complete acts are covered by test_corpus.py."""

from pathlib import Path
import shutil

from documents_mcp.bgs import parse_pdftext, parse_xhtml, prepare, validity

XHTML = """<div class='document'>
  <div class='level_1 title'><span class='number'>2.</span> <span class='title_text'>Zust&auml;ndigkeiten</span></div>
  <div class='article'>
    <div class='article_number'><span class='article_symbol'>&sect;</span> <span class='number'>3</span></div>
    <div class='article_title'><span class='title_text'>Zust&auml;ndige Beh&ouml;rde</span></div>
  </div>
  <div class='paragraph'><span class='number'>1</span>
    <p><span class='text_content'>Der Vollzug obliegt folgenden Amtsstellen:</span></p></div>
  <table class='enumeration_item'><tr><td class='number'>a)<strong>*</strong></td>
    <td class='left_col last' colspan='3'>Aufgehoben.</td></tr></table>
  <table class='enumeration_item'><tr><td class='number'>b)</td>
    <td class='left_col last' colspan='3'>dem Bau- und Justizdepartement<a class="footnote" href="#fn_9_c" id="fn_9">[9]</a>;</td></tr></table>
  <div class='paragraph_post'></div>
  <div class='article'>
    <div class='article_number'><span class='article_symbol'>&sect;</span> <span class='number'>4</span></div>
    <div class='article_title'><span class='title_text'><strong>*</strong></span></div>
  </div>
  <div class='paragraph'><span class='number'>1</span><p><span class='abrogation_ellip'>&hellip;<strong>*</strong></span></p></div>
</div>
<div class='footnotes'><ol><li><a class='footnote' href='#fn_9' id="fn_9_c">[9]</a>
  <span class='footnote_text'>Neue Departementsbezeichnung.</span></li></ol></div>
<div id='modification_table'><table>
  <tr><th>Beschluss</th><th>Inkrafttreten</th><th>Element</th><th>&Auml;nderung</th><th>GS Fundstelle</th></tr>
  <tr><td>24.03.2014</td><td>01.04.2014</td><td>&sect; 3 Abs. 1, a)</td><td>ge&auml;ndert</td><td>GS 2014, 7</td></tr>
  <tr><td>24.03.2014</td><td>01.04.2014</td><td>&sect; 3 Abs. 1, a)</td><td>ge&auml;ndert</td><td>GS 2014, 7</td></tr>
</table></div>"""


def test_xhtml_section_items_footnote():
    content = parse_xhtml(XHTML)
    s3, s4 = content["sections"]
    assert (s3["number"], s3["title"], s3["outline"]) == ("3", "Zuständige Behörde", ["2. Zuständigkeiten"])
    paragraph = s3["paragraphs"][0]
    assert paragraph["number"] == "1" and paragraph["text"] == "Der Vollzug obliegt folgenden Amtsstellen:"
    assert paragraph["items"] == [
        {"lit": "a)", "text": "Aufgehoben."},
        {"lit": "b)", "text": "dem Bau- und Justizdepartement;"},
    ]
    assert s3["footnotes"] == ["Neue Departementsbezeichnung."]
    assert not s3["repealed"] and s4["repealed"] and s4["title"] == ""


def test_xhtml_change_table_iso_without_duplicates():
    assert parse_xhtml(XHTML)["changes"] == [
        dict(decided="2014-03-24", in_force="2014-04-01", element="§ 3 Abs. 1, a)",
             change="geändert", reference="GS 2014, 7")
    ]


def test_validity_from_free_text():
    assert validity("Aktuelle Version in Kraft seit: 01.01.2023 (Beschlussdatum: 28.06.2022)") == dict(
        valid_from="2023-01-01", valid_to=None, decided="2022-06-28")
    assert validity("Version in Kraft von: 01.01.2021 bis: 31.12.2022 (Beschlussdatum: 23.06.2020)") == dict(
        valid_from="2021-01-01", valid_to="2022-12-31", decided="2020-06-23")


PDFTEXT = """614.62
Verordnung
Erster Teil

Steuern
1. Allgemeine Bestimmungen
§ 1.
Steuerobjekte
1
Ausgenommen sind Fahrzeuge (Art. 37 der Verordnung vom 20. November 19591)).
2
Die Motorfahrzeuge des Bun-
des werden besteuert.
§ 2.
Steuersubjekte2)
Steuerpflichtig ist der Halter.
________________
1)
SR 741.31.
§ 9 Absatz 3 aufgehoben am 16. März 2010.
1
\f614.62
§ 3.
...
...
"""


def test_pdftext_marks_sections_footnotes():
    sections = parse_pdftext(PDFTEXT, "614.62")["sections"]
    assert [s["number"] for s in sections] == ["1", "2", "3"]  # '§ 9 Absatz …' from the footnote ignored
    s1 = sections[0]
    assert s1["outline"] == ["Erster Teil", "1. Allgemeine Bestimmungen"]
    assert s1["paragraphs"][0]["text"].endswith("vom 20. November 1959).")  # not '195)'
    assert s1["paragraphs"][1]["text"] == "Die Motorfahrzeuge des Bundes werden besteuert."
    assert sections[1]["title"] == "Steuersubjekte"
    assert sections[2]["repealed"]


def test_prepare_is_reproducible(tmp_path):
    """The prepared stage comes from raw/ only: recomputed = versioned state (also in a fresh clone)."""
    corpus = Path(__file__).resolve().parents[2] / "corpus" / "bgs"
    for directory in sorted(p for p in corpus.iterdir() if p.is_dir()):
        shutil.copytree(directory / "raw", tmp_path / directory.name / "raw")
        prepare(directory.name, tmp_path)
        for path in [Path("act.json"), *(p.relative_to(directory) for p in (directory / "versions").glob("*.json"))]:
            assert (tmp_path / directory.name / path).read_text(encoding="utf-8") == (directory / path).read_text(encoding="utf-8"), path
