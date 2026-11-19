"""Findings and their report formats. The CSV columns are shared with Veriglot's reviewer decisions.

CSV escaping: a spreadsheet runs a cell that starts with `=`, `+`, `-`, `@`, tab or CR as a formula.
`to_csv` writes one extra leading `'` in front of such a cell in the text columns (`TEXT_COLUMNS`),
and also in front of a cell that is already `'` followed by one of those, so the escape round-trips.
Whatever reads a decision CSV back must call `unescape_cell` on exactly those columns, which strips
that one `'` and leaves `'s-Hertogenbosch` alone. The id, locale and fingerprint columns are never escaped.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = 1
CSV_COLUMNS = [
    "id",
    "locale",
    "key",
    "kind",
    "severity",
    "source",
    "target",
    "context",
    "message",
    "proposed",
    "fingerprint",
    "decision",
    "edited",
    "note",
]
DECISIONS = ("accept", "reject", "edit", "")
TEXT_COLUMNS = ("source", "target", "proposed", "edited", "context", "message", "note")
_FORMULA = re.compile(r"'*[=+\-@\t\r]")


def escape_cell(value: str) -> str:
    """Prefix `'` so a spreadsheet shows the text instead of running it as a formula."""
    return f"'{value}" if _FORMULA.match(value) else value


def unescape_cell(value: str) -> str:
    """Undo `escape_cell`; also strips the `'` a reviewer types before `=` in a spreadsheet."""
    return value[1:] if value.startswith("'") and _FORMULA.match(value) else value


@dataclass
class Finding:
    """One problem in one entry. `id` is stable across runs; `fingerprint` changes when the entry does."""

    id: str
    locale: str
    key: str  # which part: label, alias, locale, member, concept
    kind: str
    severity: str  # error or warning
    source: str  # English gloss
    target: str  # the offending text
    context: str  # group and the other entries involved
    message: str
    proposed: str  # replacement for target; empty means remove it
    fingerprint: str  # short hash of the entry snapshot when the finding was made


def to_csv(findings: list[Finding]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for f in findings:
        row = {**asdict(f), "decision": "", "edited": "", "note": ""}
        writer.writerow({k: escape_cell(v) if k in TEXT_COLUMNS else v for k, v in row.items()})
    return out.getvalue()


def summary(findings: list[Finding]) -> dict[str, int]:
    return dict(Counter(f.severity for f in findings))


def envelope(command: str, body: dict[str, Any] | None = None, errors: list[str] | None = None) -> str:
    """The one JSON object every `--format json` run prints: schema_version, command, the work done, errors."""
    out = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        **(body or {}),
        "errors": [{"message": m, "help": None} for m in errors or []],
    }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def to_json(findings: list[Finding]) -> str:
    """One object: findings plus counts per severity and kind."""
    return envelope("check", {
        "summary": {"error": 0, "warning": 0, **summary(findings)},
        "kinds": dict(sorted(Counter(f.kind for f in findings).items())),
        "findings": [asdict(f) for f in findings],
    })  # fmt: skip


def to_text(findings: list[Finding]) -> str:
    lines = [f"{f.severity}: {f.id}\n  {f.message}\n  context: {f.context}" for f in findings]
    counts = Counter(f.severity for f in findings)
    lines.append(f"{counts['error']} errors, {counts['warning']} warnings")
    return "\n".join(lines) + "\n"
