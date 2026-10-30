"""Rules (cross-cutting): criteria, document profiles and access levels, read from ``rules/``.

A check result per criterion has the form ``{"value": True | False, "finding": str | None}``: True = met,
False = missing (with a finding in words). If a criterion cannot be decided for a source, there is no result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

Results = dict[str, dict]
APPLIES_TO = ("all", "data", "documents", "non_public")
CHECKS = ("source", "document")


def met(finding: str | None = None) -> dict:
    return dict(value=True, finding=finding)


def missing(finding: str) -> dict:
    return dict(value=False, finding=finding)


@dataclass
class Rules:
    criteria: dict[str, dict]
    profiles: dict[str, dict]
    access: dict
    directory: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, directory: Path) -> "Rules":
        def read(path: Path) -> dict:
            return yaml.safe_load(path.read_text(encoding="utf-8"))

        profiles = {p["id"]: p for p in map(read, sorted((directory / "document_profiles").glob("*.yaml")))}
        rules = cls(criteria=read(directory / "criteria.yaml")["criteria"], profiles=profiles,
                    access=read(directory / "access.yaml"), directory=directory)
        rules._validate()
        return rules

    def _validate(self) -> None:
        for key, criterion in self.criteria.items():
            if criterion["applies_to"] not in APPLIES_TO:
                raise ValueError(f"Kriterium {key}: applies_to ungültig.")
        for profile in self.profiles.values():
            for name, requirement in profile["requirements"].items():
                if requirement["criterion"] not in self.criteria or requirement["check"] not in CHECKS:
                    raise ValueError(f"Dokumentprofil {profile['id']}, Anforderung {name}: criterion oder check ungültig.")

    # Access ---------------------------------------------------------------------------
    def access_to_dcat(self, level: str) -> str:
        return self.access["levels"][level]["dcat"]

    def access_from_dcat(self, uri: str) -> str:
        return next(k for k, v in self.access["levels"].items() if v["dcat"] == uri)

    def access_from_dataportal(self, value: str | None) -> str | None:
        return self.access["dataportal"].get(value or "")

    # Criteria -------------------------------------------------------------------------
    def applies(self, key: str, kind: str, access: str) -> bool:
        scope = self.criteria[key]["applies_to"]
        return scope == "all" or scope == kind or (scope == "non_public" and access != "open")

    # Document profiles ----------------------------------------------------------------
    def check_profile(self, profile_id: str, source_provides: dict, documents: list[dict],
                      checks: dict[str, Callable[[dict], bool | None]],
                      name: Callable[[dict], str]) -> tuple[Results, dict[str, list[str]]]:
        """Check a corpus against a document profile.

        source_provides: from the datasheet, what the source provides (requirement -> true/false).
        checks:          per requirement checked per 'document', a function document -> met (None = not applicable).
        Returns:         a result per criterion and, per document, the requirements it does not meet. A requirement
                         the datasheet does not answer, or that applies to no document, yields no result.
        """
        profile = self.profiles[profile_id]
        per_criterion: dict[str, list[dict]] = {}
        per_document: dict[str, list[str]] = {name(d): [] for d in documents}
        for key, requirement in profile["requirements"].items():
            if requirement["check"] == "source":
                value = source_provides.get(key)
                if value is None:
                    continue
                result = met() if value else missing(f"{requirement['text']}.")
            else:
                if key not in checks:
                    raise ValueError(f"Für Anforderung {key} ({profile_id}) fehlt die Prüfung je Dokument.")
                values = [(name(d), checks[key](d)) for d in documents]
                failed = [n for n, v in values if v is False]
                for n in failed:
                    per_document[n].append(requirement["text"])
                checked = [v for _, v in values if v is not None]
                if not checked:
                    continue
                result = (missing(f"Bei {len(failed)} von {len(checked)} Dokumenten ({_sample(failed)}): "
                                  f"{requirement['text']}.") if failed else met())
            per_criterion.setdefault(requirement["criterion"], []).append(result)
        return {k: combine(r) for k, r in per_criterion.items()}, per_document


def _sample(names: list[str], limit: int = 3) -> str:
    return ", ".join(names[:limit]) + (f" und {len(names) - limit} weitere" if len(names) > limit else "")


def combine(results: list[dict]) -> dict:
    """Several checks for the same criterion: met only if all of them are met."""
    if any(r["value"] is False for r in results):
        return missing(" ".join(r["finding"] for r in results if r["value"] is False))
    return met(" ".join(r["finding"] for r in results if r.get("finding")) or None)
