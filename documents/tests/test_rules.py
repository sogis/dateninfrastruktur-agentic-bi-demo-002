"""Rules: criteria, document profiles, access levels."""

from pathlib import Path

import pytest

from documents_mcp.rules import Rules, combine, met, missing

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def rules():
    return Rules.load(ROOT / "rules")


def test_rules_complete(rules):
    assert len(rules.criteria) == 13
    assert all(c["name"] and c["question"] for c in rules.criteria.values())
    assert set(rules.profiles) == {"legal_text", "decision"}
    assert rules.access_from_dcat(rules.access_to_dcat("restricted")) == "restricted"
    assert rules.access_from_dataportal("confidental") == "restricted" and rules.access_from_dataportal("x") is None


def test_applies(rules):
    assert rules.applies("metrics", "data", "open") and not rules.applies("metrics", "documents", "open")
    assert not rules.applies("legal_basis", "data", "open") and rules.applies("legal_basis", "documents", "restricted")


def test_combine():
    assert combine([met(), met("a")]) == met("a")
    assert combine([met("a"), missing("b"), missing("c")]) == missing("b c")  # missing as soon as one check fails


def test_check_profile(rules):
    documents = [dict(number="1", ok=True), dict(number="2", ok=False), dict(number="3", ok=None)]
    checks = {k: (lambda d: d["ok"]) for k, r in rules.profiles["decision"]["requirements"].items()
              if r["check"] == "document"}
    results, per_document = rules.check_profile(
        "decision", dict(fields=True, retrieve_all=False), documents, checks, lambda d: d["number"])
    assert results["machine_readable"]["value"] is False and "1 von 2 Dokumenten (2)" in results["machine_readable"]["finding"]
    assert results["retrievable"] == missing("Abruf aller Beschlüsse (Export oder Schnittstelle), nicht nur Suchmaske.")
    assert "validity" not in results  # date_as_field not answered in the datasheet: no result
    assert per_document["2"] and not per_document["1"] and not per_document["3"]
    with pytest.raises(ValueError, match="Prüfung je Dokument"):
        rules.check_profile("decision", {}, documents, {}, lambda d: d["number"])
