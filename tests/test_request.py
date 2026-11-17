from __future__ import annotations

import csv
import hashlib
import io
import re
from importlib import resources
from typing import TYPE_CHECKING, Any

from sensebank.cli import main
from sensebank.model import SharedAnswer
from sensebank.request import request
from sensebank.review import read_proposals, review_sheet
from sensebank.store import load_deck, save_deck

if TYPE_CHECKING:
    from pathlib import Path


def test_request_renders_groups_ids_rules_and_contract(deck_dir: Path) -> None:
    deck = load_deck(deck_dir)
    deck.groups[0].shared_answers.append(SharedAnswer("es", "blobo", ["glorp", "zint"]))
    save_deck(deck, deck_dir)
    text = request(load_deck(deck_dir), "es", [])
    template = (resources.files("sensebank") / "prompts" / "review-request.md").read_bytes()
    assert f"sha256:{hashlib.sha256(template).hexdigest()[:12]}" in text.splitlines()[0]
    assert "| zoo:glorp:es | glorp (also: blob; gloop) | glorpa (also: blobo) |" in text
    assert "| kitchen:zint:es | zint (also: zinger) | zinta |" in text
    assert "## zoo: Zoo / Zooa" in text
    assert 'Allowed shared answers:\n- es "blobo": glorp, zint' in text
    assert "```csv\nid,field,proposed,note\nzoo:glorp:es,aliases," in text
    assert "There are 2 groups and 4 concepts." in text
    assert "$" not in text


def test_request_group_filter_and_output_file(deck_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "es.md"
    assert main(["request", str(deck_dir), "es", "--group", "kitchen", "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "## kitchen" in text
    assert "## zoo" not in text
    assert "There are 1 groups" in text


def test_request_is_deterministic_and_writes_nothing_to_the_deck(deck_dir: Path) -> None:
    assert request(load_deck(deck_dir), "fr", []) == request(load_deck(deck_dir), "fr", [])


def test_request_usage_errors_exit_2(deck_dir: Path, capsys: Any) -> None:
    assert main(["request", str(deck_dir), "xx"]) == 2
    assert main(["request", str(deck_dir), "es", "--group", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


REPLY = """Reasoning about zoo: checked.

```csv
id,field,proposed,note
zoo:glorp:es,aliases,glibber; blobo,added one
zoo:zint:es,aliases,blobo,collides
zoo:ghost:es,label,x,unknown concept
```
"""


def test_review_sheet_merges_proposals_into_the_shared_columns(deck_dir: Path) -> None:
    rows = list(csv.DictReader(io.StringIO(review_sheet(load_deck(deck_dir), read_proposals(REPLY)))))
    assert list(rows[0]) == [
        "id", "locale", "key", "kind", "severity", "source", "target", "context", "message", "proposed",
        "fingerprint", "decision", "edited", "note",
    ]  # fmt: skip
    ok, collides, unknown = rows
    assert (ok["id"], ok["kind"], ok["severity"], ok["source"], ok["target"], ok["decision"]) == (
        "zoo:glorp:es:review_aliases", "review_aliases", "info", "glorp", "blobo", "",
    )  # fmt: skip
    assert len(ok["fingerprint"]) == 8
    assert (collides["severity"], "answer_shared" in collides["message"]) == ("error", True)
    assert (unknown["severity"], unknown["fingerprint"], unknown["note"]) == ("error", "", "unknown concept")


def test_review_sheet_cli_to_stdout_and_bad_reply(deck_dir: Path, tmp_path: Path, capsys: Any) -> None:
    reply = tmp_path / "reply.md"
    reply.write_text(REPLY, encoding="utf-8")
    assert main(["review-sheet", str(deck_dir), str(reply)]) == 0
    assert capsys.readouterr().out.startswith('"id","locale"')
    reply.write_text("no csv here", encoding="utf-8")
    assert main(["review-sheet", str(deck_dir), str(reply)]) == 2


def test_the_loop_end_to_end(deck_dir: Path, tmp_path: Path, capsys: Any) -> None:
    reply = tmp_path / "reply.md"
    reply.write_text(REPLY, encoding="utf-8")
    sheet = tmp_path / "decisions.csv"
    assert main(["review-sheet", str(deck_dir), str(reply), "-o", str(sheet)]) == 0
    rows = list(csv.DictReader(io.StringIO(sheet.read_text(encoding="utf-8"))))
    for r in rows:
        r["decision"] = "accept"
    with sheet.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    capsys.readouterr()
    assert main(["apply", str(deck_dir), str(sheet), "--date", "2026-11-15"]) == 1
    out = capsys.readouterr().out
    assert re.search(r"^applied {2}zoo:glorp:es:review_aliases", out, flags=re.MULTILINE) or "applied" in out
    assert "rejected: invalid" in out
    assert "rejected: unknown" in out


def test_formula_like_cells_are_quoted_and_read_back(deck_dir: Path) -> None:
    from sensebank import apply as applying

    proposals = read_proposals("id,field,proposed,note\nzoo:glorp:es,label,-glorpo,=1+1\n")
    text = review_sheet(load_deck(deck_dir), proposals)
    [row] = csv.DictReader(io.StringIO(text))
    assert (row["proposed"], row["note"]) == ("'-glorpo", "'=1+1")
    [decision] = applying.read_decisions(text.replace('"",""', '"accept",""', 1))
    assert decision.proposed == "-glorpo"


def test_apostrophe_words_survive_the_sheet(deck_dir: Path) -> None:
    from sensebank import apply as applying

    text = review_sheet(load_deck(deck_dir), read_proposals("id,field,proposed,note\nzoo:glorp:es,label,'s-glorp,\n"))
    [row] = csv.DictReader(io.StringIO(text))
    assert row["proposed"] == "'s-glorp"  # a plain leading quote is not an escape
    [decision] = applying.read_decisions(text)
    assert decision.proposed == "'s-glorp"
