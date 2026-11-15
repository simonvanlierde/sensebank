"""Findings and their report formats. The CSV columns are shared with Veriglot's reviewer decisions."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass

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
        writer.writerow({**asdict(f), "decision": "", "edited": "", "note": ""})
    return out.getvalue()


def summary(findings: list[Finding]) -> dict[str, int]:
    return dict(Counter(f.severity for f in findings))


def to_json(findings: list[Finding]) -> str:
    """One object: findings plus counts per severity and kind."""
    body = {
        "schema_version": SCHEMA_VERSION,
        "summary": {"error": 0, "warning": 0, **summary(findings)},
        "kinds": dict(sorted(Counter(f.kind for f in findings).items())),
        "findings": [asdict(f) for f in findings],
    }
    return json.dumps(body, ensure_ascii=False, indent=2) + "\n"


def to_text(findings: list[Finding]) -> str:
    lines = [f"{f.severity}: {f.id}\n  {f.message}\n  context: {f.context}" for f in findings]
    counts = Counter(f.severity for f in findings)
    lines.append(f"{counts['error']} errors, {counts['warning']} warnings")
    return "\n".join(lines) + "\n"
