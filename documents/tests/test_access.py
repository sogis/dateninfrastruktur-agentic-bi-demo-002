"""Access: open for everyone, restricted only with an entry in access/grants.yaml (group or person), audit log."""

import json

import pytest

from documents_mcp.access import ANONYMOUS, AccessControl, Person


def grant(directory, content: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "grants.yaml").write_text(content, encoding="utf-8")


@pytest.fixture
def control(tmp_path):
    return AccessControl(tmp_path / "access")


def test_person():
    p = Person.of(" Anna@SO.ch ", "Intern, amt-agi,")
    assert p.principals() == {"person:anna@so.ch", "group:intern", "group:amt-agi"}
    assert ANONYMOUS.principals() == set() and "nicht angemeldet" in ANONYMOUS.describe()


def test_open_always_restricted_only_with_grant(control):
    anna = Person.of("anna@so.ch")
    assert control.may_read(ANONYMOUS, "x", "open") and not control.may_read(anna, "x", "restricted")


def test_group_or_person(control):
    grant(control.directory, "x: [group:Staatskanzlei]\ny: [person:Anna@so.ch]\n")
    assert control.may_read(Person.of("ben@so.ch", "Alle,staatskanzlei"), "x", "restricted")
    assert not control.may_read(Person.of("ben@so.ch", "Alle"), "x", "restricted")
    assert control.may_read(Person.of("anna@so.ch"), "y", "restricted")
    assert not control.may_read(Person.of("anna@so.ch"), "x", "restricted")   # per dataset
    assert not control.may_read(ANONYMOUS, "x", "restricted")


def test_change_applies_immediately(control):
    p = Person.of("ben@so.ch", "staatskanzlei")
    grant(control.directory, "x: [group:staatskanzlei]\n")
    assert control.may_read(p, "x", "restricted")
    grant(control.directory, "x: []\n")
    assert not control.may_read(p, "x", "restricted")


def test_audit(control):
    control.record(Person.of("anna@so.ch"), "x", "get_decision", False)
    control.record(ANONYMOUS, "x", "get_decision", False)
    lines = [json.loads(line) for line in (control.directory / "audit.jsonl").read_text().splitlines()]
    assert lines[0]["who"] == ["person:anna@so.ch"] and lines[1]["who"] == ["anonymous"]
    assert control.audit(1) == lines[1:]


def test_without_directory_only_open():
    control = AccessControl(None)
    assert not control.may_read(Person.of("a@so.ch", "staatskanzlei"), "x", "restricted")
    control.record(ANONYMOUS, "x", "tool", False)  # silent, no error
    assert control.grants() == {} and control.audit() == []
