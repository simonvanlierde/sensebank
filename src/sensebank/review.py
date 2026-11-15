"""Review entries: ids, fingerprints and the check gate that `review-sheet` and `apply` share.

A review entry is one concept in one locale as seen from one group, and a proposal changes one of
its fields (`label` or `aliases`). Entry ids are `<group>:<concept>:<locale>`; a decision row's id
adds the kind, `review_label` or `review_aliases`.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sensebank.check import _fp, check_deck
from sensebank.findings import CSV_COLUMNS, TEXT_COLUMNS, escape_cell

if TYPE_CHECKING:
    from sensebank.model import Deck, Localized

FIELDS = ("label", "aliases")
KIND_PREFIX = "review_"
NONE = "(none)"  # an empty proposed cell is invalid, so this spells "remove every alias"
SEPARATOR = "; "
PROPOSAL_COLUMNS = ("id", "field", "proposed", "note")


class UsageError(ValueError):
    """The caller's input is wrong (exit 2), as opposed to a deck that cannot be read (exit 3)."""


@dataclass(frozen=True)
class Ref:
    """A parsed decision id."""

    group: str
    concept: str
    locale: str
    field: str


def entry_id(group: str, concept: str, locale: str) -> str:
    return f"{group}:{concept}:{locale}"


def row_id(group: str, concept: str, locale: str, field: str) -> str:
    return f"{entry_id(group, concept, locale)}:{KIND_PREFIX}{field}"


def parse_row_id(value: str) -> Ref | None:
    parts = value.split(":")
    if len(parts) != 4 or not parts[3].startswith(KIND_PREFIX) or parts[3][len(KIND_PREFIX) :] not in FIELDS:
        return None
    return Ref(parts[0], parts[1], parts[2], parts[3][len(KIND_PREFIX) :])


def fingerprint(concept: str, locale: str, entry: Localized, field: str) -> str:
    """Hash of the one field a row would change, so a label row and an aliases row on one entry stay independent."""
    return _fp(concept, locale, field, entry.label if field == "label" else entry.aliases)


def field_text(entry: Localized, field: str) -> str:
    if field == "label":
        return entry.label
    return SEPARATOR.join(entry.aliases) or NONE


def parse_value(field: str, text: str) -> str | list[str]:
    """The label, or the complete alias list, a cell stands for. Order kept, repeats dropped."""
    if field == "label":
        return text.strip()
    if text.strip() == NONE:
        return []
    return list(dict.fromkeys(a.strip() for a in text.split(";") if a.strip()))


def set_field(entry: Localized, field: str, value: str | list[str]) -> None:
    if field == "label":
        entry.label = str(value)
    else:
        entry.aliases = list(value)


def scope(deck: Deck, concept_id: str) -> Deck:
    """The groups holding the concept, with their concepts: the only place a change to it can create an error.

    Concept objects are shared, so a change made through the scope is a change to the deck.
    """
    groups = [g for g in deck.groups if concept_id in g.members]
    wanted = {m for g in groups for m in g.members} | {concept_id}
    return replace(deck, groups=groups, concepts=[c for c in deck.concepts if c.id in wanted])


def error_keys(deck: Deck) -> set[tuple[str, str]]:
    """Error findings as (id, context): context carries the clashing entries, so a clash that grows is new."""
    return {(f.id, f.context) for f in check_deck(deck) if f.severity == "error"}


def new_errors(deck: Deck, before: set[tuple[str, str]]) -> list[str]:
    """Messages of error findings the deck has now and `before` did not."""
    return [
        f"{f.id}: {f.message}" for f in check_deck(deck) if f.severity == "error" and (f.id, f.context) not in before
    ]


def read_proposals(text: str) -> list[dict[str, str]]:
    """Rows of the reviewer's reply. A fenced csv block wins over surrounding reasoning."""
    fenced = re.findall(r"```(?:csv)?[ \t]*\n(.*?)```", text, flags=re.DOTALL)
    reader = csv.DictReader(io.StringIO(fenced[-1] if fenced else text))
    if missing := [c for c in PROPOSAL_COLUMNS if c not in (reader.fieldnames or ())]:
        msg = f"proposal CSV lacks column(s) {', '.join(missing)}"
        raise UsageError(msg)
    return [{c: (row.get(c) or "").strip() for c in PROPOSAL_COLUMNS} for row in reader]


def review_sheet(deck: Deck, proposals: list[dict[str, str]]) -> str:
    """Merge model proposals into the shared decision CSV; every proposal becomes one row."""
    members = {g.id: set(g.members) for g in deck.groups}
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    for p in proposals:
        group, _, rest = p["id"].partition(":")
        concept_id, _, locale = rest.partition(":")
        field = p["field"]
        concept = deck.concept(concept_id)
        entry = concept.locales.get(locale) if concept else None
        ok = field in FIELDS and entry is not None and concept_id in members.get(group, set())
        row = dict.fromkeys(CSV_COLUMNS, "") | {
            "locale": locale,
            "key": field,
            "proposed": p["proposed"],
            "note": p["note"],
        }
        kind = f"{KIND_PREFIX}{field}"
        if not ok or concept is None or entry is None:
            found = {"id": f"{p['id']}:{kind}", "kind": kind, "severity": "error", "message": "unknown entry or field"}
        else:
            english = concept.locales.get("en")
            view = scope(deck, concept_id)
            before = error_keys(view)
            old = (entry.label, list(entry.aliases))
            set_field(entry, field, parse_value(field, p["proposed"]))
            problems = new_errors(view, before) if p["proposed"] else ["proposed is empty"]
            entry.label, entry.aliases = old
            found = {
                "id": row_id(group, concept_id, locale, field), "kind": kind,
                "severity": "error" if problems else "info",
                "source": english.label if english else concept.gloss,
                "target": field_text(entry, field),
                "context": f"group {group}",
                "message": "; ".join(problems) or "passes the group checks",
                "fingerprint": fingerprint(concept_id, locale, entry, field),
            }  # fmt: skip
        writer.writerow({k: escape_cell(v) if k in TEXT_COLUMNS else v for k, v in (row | found).items()})
    return out.getvalue()
