"""Access control, simplified after the access model of the AGI data infrastructure (experiment).

- Sign-in only says *who* someone is: e-mail and groups, which OpenWebUI sends with every tool call.
- Rights apply to a whole dataset: open = everyone, restricted = only those listed for that dataset in
  ``access/grants.yaml`` (``group:<name>`` or ``person:<e-mail>``).
- The file is read on every check, so a change applies to the next call.
- Every access to a restricted dataset is written to ``access/audit.jsonl`` (local only), allowed or not.

How a grant comes about (request, decision, expiry, revocation) is deliberately not part of the prototype; the
canton decides that. Here the owner enters it in the file (in the prototype: by hand).

  python -m documents_mcp.access grants | audit
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path

import yaml

GRANTS = "grants.yaml"
AUDIT = "audit.jsonl"


@dataclass(frozen=True)
class Person:
    """Who is asking: e-mail and groups, as OpenWebUI sends them with each tool call."""

    email: str | None = None
    groups: frozenset[str] = frozenset()

    @classmethod
    def of(cls, email: str | None = None, groups: str | list[str] | None = None) -> "Person":
        if isinstance(groups, str):
            groups = groups.split(",")
        return cls((email or "").strip().lower() or None, frozenset(g.strip().lower() for g in groups or [] if g.strip()))

    def principals(self) -> set[str]:
        return ({f"person:{self.email}"} if self.email else set()) | {f"group:{g}" for g in self.groups}

    def describe(self) -> str:
        if not self.email and not self.groups:
            return "nicht angemeldet (nur öffentliche Datensätze)"
        return " ".join(filter(None, [self.email, f"Gruppen: {', '.join(sorted(self.groups))}" if self.groups else None]))


ANONYMOUS = Person()


class AccessControl:
    def __init__(self, directory: Path | None) -> None:
        self.directory = directory

    def grants(self) -> dict[str, set[str]]:
        """Dataset -> who may read it (group:<name>, person:<e-mail>), from access/grants.yaml."""
        path = self.directory / GRANTS if self.directory else None
        if path is None or not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {dataset: {p.strip().lower() for p in (who or [])} for dataset, who in raw.items()}

    def may_read(self, person: Person, dataset: str, access: str) -> bool:
        return access == "open" or bool(person.principals() & self.grants().get(dataset, set()))

    def record(self, person: Person, dataset: str, tool: str, allowed: bool) -> None:
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = dict(time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     who=sorted(person.principals()) or ["anonymous"], dataset=dataset, tool=tool, allowed=allowed)
        with open(self.directory / AUDIT, "a", encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def audit(self, last: int = 20) -> list[dict]:
        path = self.directory / AUDIT if self.directory else None
        if path is None or not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()][-last:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Rechte des Prototyps anzeigen (Freigaben, Protokoll).")
    parser.add_argument("--dir", type=Path, default=Path("../access"), help="Ordner access/ (Standard ../access)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("grants", help=f"wer welchen restricted Datensatz lesen darf ({GRANTS})")
    audit = commands.add_parser("audit", help="letzte Zugriffe auf restricted Datensätze")
    audit.add_argument("--last", type=int, default=20)
    args = parser.parse_args()
    control = AccessControl(args.dir)
    result = ({k: sorted(v) for k, v in control.grants().items()} if args.command == "grants"
              else control.audit(args.last))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
