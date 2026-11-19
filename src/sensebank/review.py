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
from sensebank.model import DeckError, validate_deck

if TYPE_CHECKING:
    from sensebank.model import Deck, Localized

FIELDS = ("label", "aliases")
KIND_PREFIX = "review_"
NONE = "(none)"  # an empty proposed cell is invalid, so this spells "remove every alias"
SEPARATOR = "; "
PROPOSAL_COLUMNS = ("id", "field", "proposed", "note")


class UsageError(ValueError):
    """The caller's input is wrong (exit 2), as opposed to a deck that cannot be read (exit 3)."""

    def __init__(self, message: str, help_: str | None = None) -> None:
        super().__init__(message)
        self.help = help_


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


CLASH_MARK = "also accepted by: "


def error_keys(deck: Deck) -> dict[str, frozenset[str]]:
    """Error findings by id, each with the entries an `answer_shared` finding says it clashes with."""
    return {
        f.id: frozenset(f.context.partition(CLASH_MARK)[2].split(", ")) if f.kind == "answer_shared" else frozenset()
        for f in check_deck(deck)
        if f.severity == "error"
    }


def new_errors(deck: Deck, before: dict[str, frozenset[str]]) -> list[str]:
    """Messages of error findings that are new: an unknown id, or a clash set that is not within the old one.

    Compared by id, not by text: dropping one party of a three-way clash shrinks the others' context.
    """
    out = []
    for f in check_deck(deck):
        if f.severity != "error":
            continue
        clashes = (
            frozenset(f.context.partition(CLASH_MARK)[2].split(", ")) if f.kind == "answer_shared" else frozenset()
        )
        if f.id not in before or not clashes <= before[f.id]:
            out.append(f"{f.id}: {f.message}")
    return out


def word_problems(value: str | list[str]) -> list[str]:
    """Why proposed words cannot be written: odd whitespace, or the `;` that separates aliases in a cell."""
    problems = []
    for word in [value] if isinstance(value, str) else value:
        if " ".join(word.split()) != word:
            problems.append(f"{word!r} holds whitespace other than single spaces")
        if ";" in word:
            problems.append(f"{word!r} holds ';', which separates aliases")
    return problems


def try_change(
    deck: Deck, concept_id: str, locale: str, field: str, value: str | list[str], *, keep: bool
) -> list[str]:
    """Set one field and return why it is not allowed. The change stays only when allowed and `keep`."""
    concept = deck.concept(concept_id)
    entry = concept.locales[locale] if concept else None
    if entry is None:
        return [f"no entry {concept_id}/{locale}"]
    if problems := word_problems(value):
        return problems
    view = scope(deck, concept_id)
    before = error_keys(view)
    old = (entry.label, list(entry.aliases))
    set_field(entry, field, value)
    try:
        validate_deck(view)
    except DeckError as err:
        problems = [str(err)]
    else:
        problems = new_errors(view, before)
    if problems or not keep:
        entry.label, entry.aliases = old
    return problems


_FENCE = re.compile(r"```([A-Za-z]*)[ \t]*$")


def _blocks(text: str) -> list[str]:
    """Bodies of the fenced blocks, fences at column 0 only (so a fence inside a value is not one)."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if current is None and _FENCE.fullmatch(line):
            current = []
        elif current is not None and line.rstrip() == "```":
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return ["\n".join(b) for b in blocks]


_ROW_ID = re.compile(r"[^:,\s]+:[^:,\s]+:[^:,\s]+")


def _proposal_block(candidates: list[str]) -> str | None:
    """CSV rows without the header from the last proposal block; "" for an empty block (no changes); else None."""
    chosen = None
    empty = False
    for block in candidates:
        body = block.lstrip("\ufeff")
        empty = empty or not body.strip()
        first = next(csv.reader(io.StringIO(body)), [])
        if [h.strip().lower() for h in first] == list(PROPOSAL_COLUMNS):
            chosen = body.split("\n", 1)[1] if "\n" in body else ""
        elif first and _ROW_ID.fullmatch(first[0].strip()):
            chosen = body
    return "" if chosen is None and empty else chosen


def read_proposals(text: str) -> list[dict[str, str]]:
    """Rows of the reviewer's reply: the last fenced block headed `id,field,proposed,note`, else the whole text.

    Models drift from strict CSV, so a block whose first row is already a proposal id counts as headed, a quoted
    word that opens a note is read leniently, an unquoted comma in the note stays in the note, and an empty block
    means no proposals. An unbalanced quote is still refused: it means a value was cut off.
    """
    chosen = _proposal_block(_blocks(text) or [text])
    if chosen is None:
        msg = f"no CSV block with the header {','.join(PROPOSAL_COLUMNS)}"
        raise UsageError(msg)
    try:
        rows = list(csv.reader(io.StringIO(chosen), strict=True))
    except csv.Error as err:
        if chosen.count('"') % 2:
            msg = f"proposal CSV is malformed: {err}"
            raise UsageError(msg) from err
        rows = list(csv.reader(io.StringIO(chosen)))
    out = []
    for fields in rows:
        if not any(f.strip() for f in fields):
            continue
        head, rest = fields[:3], fields[3:]
        values = [f.strip() for f in head] + [""] * (3 - len(head)) + [",".join(rest).strip()]
        if any("```" in v for v in values):
            msg = "a proposal value contains a code fence; fix the reply"
            raise UsageError(msg)
        row = dict(zip(PROPOSAL_COLUMNS, values, strict=True))
        out.append(row | {"field": row["field"].lower()})
    return out


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
            problems = (
                try_change(deck, concept_id, locale, field, parse_value(field, p["proposed"]), keep=False)
                if p["proposed"]
                else ["proposed is empty"]
            )
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
