"""Parser for the distribution list ("Verteiler") at the end of a government council decision (RRB) PDF.

The distribution list says which offices take note of or implement a decision. rrb.so.ch does not offer it as a
field, but it is in the PDF full text, in a stable form (example invented):

    Verteiler

    Bau- und Justizdepartement
    Amt für Raumplanung (AB) (2), Dossier-Nr. 100'000, mit Akten
    Einwohnergemeinde Musterdorf, Hauptstrasse 1, 4500 Musterdorf, mit
             1 gen. Dossier (später), mit Rechnung (Einschreiben)

Input is ``pdftotext -layout`` output, so continuation lines keep their indentation. Figures in the comments were
measured on the 1441 decisions of 2025.
"""

from __future__ import annotations

from collections.abc import Iterable
import re

# Heading detection. Everything after the heading up to the end of the document belongs to the block: the
# distribution list always comes last.
#
# Matching the word "Verteiler" is not enough, for two reasons. The heading often carries a suffix
# ("Verteiler RRB", "Verteiler (Versand durch Staatskanzlei)", "Verteiler mit B+E"), and the word itself is not
# reliable in the source: it appears split ("Vertei ler", RRB 2025/301) or glued to the next word
# ("Verteilerbew", RRB 2025/1518). So the check uses the letter sequence of the line: drop all non-letters,
# lower-case, then test for "verteiler". The length limit keeps body sentences out that start with
# "Verteiler" ("Verteiler der Kosten auf die Gemeinden erfolgt nach ..."); no false positive in 2025.
_HEADING_CORE = "verteiler"
_MAX_HEADING_LENGTH = 90
_NON_LETTER = re.compile(r"[^a-zäöüéèàç]")

# Continuation lines are the delicate part: an unrecognised continuation becomes a phantom recipient, and the
# offices derived from the list are what users filter on later. Each rule below is sufficient on its own.
_CONTINUATION_INDENT = 6

# A recipient name starts with a capital letter. A line starting in lower case belongs to the previous one.
# Known exception: company names in lower case ("santesuisse") get appended. Accepted on purpose: no phantom
# office is created, only a longer entry, and cantonal offices never start in lower case.
_STARTS_LOWER = re.compile(r"^[a-zäöüéèàç]")

# Postcode plus place is always the continuation of an address: "Holinger AG, Kasthoferstrasse 23," / "3006 Bern".
_POSTCODE_PLACE = re.compile(r"^\d{4}\s+\D")

# Too short to be a recipient (counters, remains of footnotes: "3", "rl").
_MIN_RECIPIENT_LENGTH = 4

# Line endings after which an entry cannot be complete. The source breaks inside names ("Bau- und" /
# "Justizdepartement") and inside dispatch notes ("mit 1 gen." / "Dossier (später)"); in both cases the next line
# starts in upper case and is long enough to pass the other rules. 2025: 49 lines, no false positive.
_HANGING_END = re.compile(
    r"(?:\b(?:mit|und|sowie|c/o|z\.?\s?Hd\.?|gen\.|inkl\.|nebst|samt|per|von|an|für|"
    r"zur|zum|im|in|dem|der|des|den|die|das|beim|über|à)|[&+])\s*$",
    re.IGNORECASE,
)

# A colon ends a line cleanly: it introduces a section ("Eröffnung und Versand durch Amt für Landwirtschaft:"), and
# what follows is a new recipient. Without this exception the hanging-end rule would swallow it ("durch").
_SECTION_END = re.compile(r":\s*$")

# Postcode plus place anywhere in the line, together with a comma at the end of the previous line: a wrapped
# address whose next line starts with the street ("... Preisüberwachung," / "Einsteinstrasse 2, 3003 Bern").
_CONTAINS_POSTCODE_PLACE = re.compile(r"\b\d{4}\s+[A-ZÄÖÜ]")
_ENDS_WITH_COMMA = re.compile(r",\s*$")

# A line of digits only is a page number: dropped, not appended.
_DIGITS_ONLY = re.compile(r"^\d+$")

# Cantonal recipients as they appear in distribution lists. Longer names are checked first by the caller, so that
# "Amt für Wald, Jagd und Fischerei" does not count as "Amt für Wald".
CANTONAL_RECIPIENTS: tuple[str, ...] = (
    "Amt für Berufsbildung, Mittel- und Hochschulen",
    "Amt für Denkmalpflege und Archäologie",
    "Amt für Militär und Bevölkerungsschutz",
    "Amt für Volksschule und Kindergarten",
    "Amt für Verkehr und Tiefbau",
    "Amt für Wirtschaft und Arbeit",
    "Amt für soziale Sicherheit",
    "Amt für Geoinformation",
    "Amt für Landwirtschaft",
    "Amt für Raumplanung",
    "Amt für Gemeinden",
    "Amt für Finanzen",
    "Amt für Umwelt",
    "Amt für Kultur und Sport",
    "Amt für Wald, Jagd und Fischerei",
    "Amt für Wald",
    "Amt für Gesellschaft und Soziales",
    "Amt für Informatik und Organisation",
    "Amt für Justizvollzug",
    "Gesundheitsamt",
    "Volksschulamt",
    "Kantonales Steueramt",
    "Steueramt",
    "Departement für Bildung und Kultur",
    "Bau- und Justizdepartement",
    "Volkswirtschaftsdepartement",
    "Departement des Innern",
    "Finanzdepartement",
    "Staatskanzlei",
    "Kantonale Finanzkontrolle",
    "Kantonspolizei",
    "Hochbauamt",
    "Personalamt",
    "Parlamentsdienste",
    "Motorfahrzeugkontrolle",
    "Solothurnische Gebäudeversicherung",
    "Sekretariat der Katasterschätzung",
)


def is_heading(line: str) -> bool:
    """Does this line open the distribution list?

    >>> is_heading("Verteiler RRB")
    True
    >>> is_heading("Vertei ler")
    True
    >>> is_heading("Verteiler der Kosten auf die Gemeinden erfolgt nach Ziffer 3.2 des Beschlusses und nach Anhang")
    False
    """
    content = line.strip()
    if not content or len(content) > _MAX_HEADING_LENGTH:
        return False
    return _NON_LETTER.sub("", content.lower()).startswith(_HEADING_CORE)


def parse_block(text: str) -> list[str]:
    """Split the distribution list of a decision into recipient lines, in document order.

    Indented continuation lines are appended to the previous line, so that an address does not count as an extra
    recipient. Line endings may be ``\\n``, ``\\r\\n`` or ``\\r``. Returns an empty list if there is no heading.
    """
    if not text:
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if is_heading(line)), None)
    if start is None:
        return []
    return _join((line, line.strip()) for line in lines[start + 1:])


def _join(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """Append continuation lines to their recipient. ``pairs``: (raw line with indentation, stripped content)."""
    entries: list[str] = []
    for raw, content in pairs:
        if not content or _DIGITS_ONLY.match(content):
            # Page numbers run through the list. They belong to no recipient, and as the first line of the block
            # they would become an entry of their own.
            continue
        if entries and _is_continuation(raw, content, entries[-1]):
            entries[-1] = f"{entries[-1]} {content}"
        else:
            entries.append(content)
    return entries


def _is_continuation(raw: str, content: str, previous: str) -> bool:
    """Does this line belong to the previous recipient? The first five rules look at the line itself, the last two
    at the previous line: a line ending in "mit" or in a comma before an address is unfinished."""
    if raw[:_CONTINUATION_INDENT].isspace():                 # 1. indentation
        return True
    if previous.count("(") > previous.count(")"):            # 2. open bracket in the previous line
        return True
    if _STARTS_LOWER.match(content):                          # 3. starts in lower case
        return True
    if _POSTCODE_PLACE.match(content):                        # 4. postcode plus place
        return True
    # 5. Rest of a wrapped bracket or enumeration; "(Einschreiben)" on its own line is a note on the previous
    #    recipient, not a new one (65 times in 2025).
    if content[0] in "()],;" or len(content) < _MIN_RECIPIENT_LENGTH:
        return True
    if _SECTION_END.search(previous):                         # a colon ends the previous line cleanly
        return False
    if _HANGING_END.search(previous):                         # 6. previous line ends hanging
        return True
    # 7. Wrapped address: comma at the end, postcode in the next line.
    return bool(_ENDS_WITH_COMMA.search(previous) and _CONTAINS_POSTCODE_PLACE.search(content))
