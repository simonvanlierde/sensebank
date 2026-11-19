"""Apply reviewer decisions to a deck, accounting for every row.

Mirrors Veriglot's apply semantics (see docs/design.md); the code is separate on purpose.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from sensebank.findings import envelope, unescape_cell
from sensebank.model import DeckError, Override, Source
from sensebank.review import (
    UsageError,
    field_text,
    fingerprint,
    parse_row_id,
    parse_value,
    try_change,
)
from sensebank.store import CONCEPTS_FILE, DECK_FILE, GROUPS_DIR, load_deck, save_deck

if TYPE_CHECKING:
    from pathlib import Path

    from sensebank.model import Deck, Localized

Status = Literal["applied", "rejected", "skipped"]
REQUIRED = ("id", "fingerprint", "decision")


@dataclass(frozen=True)
class DecisionRow:
    """One reviewer decision as read from the CSV; other columns are ignored."""

    id: str
    fingerprint: str
    decision: str
    proposed: str = ""
    edited: str = ""


@dataclass(frozen=True)
class Outcome:
    """What happened to one row. `reason` is empty when applied."""

    id: str
    status: Status
    reason: str  # declined, undecided, already applied, invalid decision, unknown, stale or invalid
    detail: str = ""
    text: str = ""


def read_decisions(text: str) -> list[DecisionRow]:
    reader = csv.DictReader(io.StringIO(text))
    if missing := [c for c in REQUIRED if c not in (reader.fieldnames or ())]:
        msg = f"decisions CSV lacks column(s) {', '.join(missing)}"
        raise UsageError(msg)
    return [
        DecisionRow(
            r["id"],
            r["fingerprint"],
            r["decision"] or "",
            unescape_cell(r.get("proposed") or ""),
            unescape_cell(r.get("edited") or ""),
        )
        for r in reader
    ]


def _decide(  # noqa: C901, PLR0911 - one return per outcome keeps the order of checks readable
    deck: Deck, row: DecisionRow
) -> tuple[Outcome, tuple[Localized, str, list[str]] | None]:
    """Judge one row; on success the deck is changed and the change returned for provenance."""

    def rejected(reason: str, detail: str, text: str = "") -> tuple[Outcome, None]:
        return Outcome(row.id, "rejected", reason, detail, text), None

    decision = row.decision.strip().lower()
    if decision == "reject":
        return Outcome(row.id, "skipped", "declined"), None
    if not decision:
        return Outcome(row.id, "skipped", "undecided"), None
    if decision not in {"accept", "edit"}:
        return rejected("invalid decision", f"decision {row.decision!r} is not accept, edit, reject or empty")
    text = row.proposed if decision == "accept" else row.edited
    if not text.strip():
        return rejected(
            "invalid", f"{decision} needs text in the {'proposed' if decision == 'accept' else 'edited'} column"
        )
    ref = parse_row_id(row.id)
    group = next((g for g in deck.groups if ref and g.id == ref.group), None)
    concept = deck.concept(ref.concept) if ref else None
    entry = concept.locales.get(ref.locale) if concept and ref else None
    if ref is None or group is None or concept is None or entry is None or concept.id not in group.members:
        return rejected("unknown", f"no review entry {row.id!r} in this deck", text)
    value = parse_value(ref.field, text)
    if ref.field == "label" and not value:
        return rejected("invalid", "label is empty", text)
    if value == (entry.label if ref.field == "label" else entry.aliases):
        return Outcome(row.id, "skipped", "already applied", text=text), None
    if fingerprint(concept.id, ref.locale, entry, ref.field) != row.fingerprint:
        return rejected("stale", "the entry changed after the review", text)
    old = (entry.label, list(entry.aliases))
    if problems := try_change(deck, concept.id, ref.locale, ref.field, value, keep=True):
        return rejected("invalid", "; ".join(problems), text)
    return Outcome(row.id, "applied", "", text=field_text(entry, ref.field)), (entry, *old)


def apply_decisions(deck: Deck, rows: list[DecisionRow], source: Source) -> list[Outcome]:
    """Apply rows in order to `deck` (in memory). Each row is judged against the text left by earlier rows."""
    outcomes: list[Outcome] = []
    for row in rows:
        outcome, change = _decide(deck, row)
        outcomes.append(outcome)
        if change is None:
            continue
        entry, old_label, old_aliases = change
        # New words carry the review source; words that left the entry take their overrides with them.
        for word in {old_label, *old_aliases} - set(entry.words):
            entry.overrides.pop(word, None)
        for word in set(entry.words) - {old_label, *old_aliases}:
            entry.overrides[word] = Override(source=source.id, review="accepted")
        deck.sources.setdefault(source.id, source)
    return outcomes


def _snapshot(directory: Path) -> dict[str, bytes]:
    """Every file `save_deck` writes, and the group listing it prunes by."""
    names = [
        DECK_FILE,
        CONCEPTS_FILE,
        *sorted(p.relative_to(directory).as_posix() for p in (directory / GROUPS_DIR).glob("*.yaml")),
    ]
    return {n: (directory / n).read_bytes() for n in names}


def apply_file(
    directory: Path, rows: list[DecisionRow], *, reviewer: str, date: str, dry_run: bool
) -> tuple[list[Outcome], bool]:
    """Load, apply, and save once if anything changed. Returns the outcomes and whether files were written."""
    try:
        snapshot = _snapshot(directory)
    except OSError as err:
        msg = f"cannot read deck {directory}: {err}"
        raise DeckError(msg) from err
    deck = load_deck(directory)
    slug = "".join(ch if ch.isalnum() else "-" for ch in reviewer.lower()).strip("-") or "reviewer"
    source = Source(f"review-{date}-{slug}", f"review {date} {reviewer}", "unspecified", snapshot=date)
    if (known := deck.sources.get(source.id)) and known.name != source.name:
        msg = f"source id {source.id!r} already names {known.name!r}; pick another --reviewer or --date"
        raise DeckError(msg)
    outcomes = apply_decisions(deck, rows, source)
    changed = any(o.status == "applied" for o in outcomes)
    if changed and not dry_run:
        if _snapshot(directory) != snapshot:
            msg = f"{directory} changed on disk while the decisions were checked; nothing written"
            raise DeckError(msg)
        save_deck(deck, directory)
    return outcomes, changed and not dry_run


def to_json(outcomes: list[Outcome], *, dry_run: bool, written: bool) -> str:
    return envelope("apply", {
        "dry_run": dry_run,
        "written": written,
        "summary": {"applied": 0, "rejected": 0, "skipped": 0} | dict(Counter(o.status for o in outcomes)),
        "outcomes": [asdict(o) for o in outcomes],
    })  # fmt: skip


def to_text(outcomes: list[Outcome], *, dry_run: bool, written: bool) -> str:
    verb = "would apply" if dry_run else "applied"
    lines = []
    for o in outcomes:
        label = verb if o.status == "applied" else f"{o.status}: {o.reason}"
        shown = f" -> {o.text}" if o.status == "applied" else (f"  ({o.detail})" if o.detail else "")
        lines.append(f"{label}  {o.id}{shown}")
    counts = Counter(o.status for o in outcomes)
    tail = "written" if written else "nothing written"
    lines.append(f"{counts['applied']} {verb}, {counts['rejected']} rejected, {counts['skipped']} skipped ({tail})")
    return "\n".join(lines) + "\n"
