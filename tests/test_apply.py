from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import TYPE_CHECKING, Any

import pytest

from sensebank import apply as applying
from sensebank.cli import main
from sensebank.findings import CSV_COLUMNS
from sensebank.model import DeckError
from sensebank.review import fingerprint, row_id
from sensebank.store import load_deck

if TYPE_CHECKING:
    from pathlib import Path


def _tree(directory: Path) -> dict[str, str]:
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _row(deck_dir: Path, concept: str, field: str, decision: str = "accept", proposed: str = "", edited: str = "",
         group: str = "zoo", locale: str = "es") -> dict[str, str]:  # fmt: skip
    entry = load_deck(deck_dir).concept(concept).locales[locale]  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
    return dict.fromkeys(CSV_COLUMNS, "") | {
        "id": row_id(group, concept, locale, field),
        "fingerprint": fingerprint(concept, locale, entry, field),
        "decision": decision, "proposed": proposed, "edited": edited,
    }  # fmt: skip


def _csv(path: Path, rows: list[dict[str, str]]) -> Path:
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")
    return path


def _run(deck_dir: Path, rows: list[dict[str, str]], *extra: str) -> tuple[int, Any]:
    code = main(
        [
            "apply",
            str(deck_dir),
            str(_csv(deck_dir.parent / "d.csv", rows)),
            "--format",
            "json",
            "--date",
            "2026-11-15",
            *extra,
        ]
    )
    return code, None


def _outcomes(capsys: Any) -> list[dict[str, str]]:
    return json.loads(capsys.readouterr().out)["outcomes"]


def test_accept_applies_records_provenance_and_is_byte_stable(deck_dir: Path, capsys: Any) -> None:
    before = _tree(deck_dir)
    row = _row(deck_dir, "glorp", "aliases", proposed="blobo; glibber")
    assert _run(deck_dir, [row], "--reviewer", "Local Model")[0] == 0
    [o] = _outcomes(capsys)
    assert (o["status"], o["reason"], o["text"]) == ("applied", "", "blobo; glibber")
    after = _tree(deck_dir)
    assert {k for k in after if after[k] != before.get(k)} == {"concepts.yaml", "deck.yaml"}
    deck = load_deck(deck_dir)
    prov = deck.provenance("glorp", "es", "glibber")
    assert (prov.source.name, prov.review) == ("review 2026-11-15 Local Model", "accepted")
    assert (
        deck.provenance("glorp", "es", "blobo").source.id == "six-second-scribbles"
    )  # untouched word keeps its source
    assert deck.provenance("glorp", "es", "glorpa").review == "unreviewed"


def test_label_change_moves_the_override(deck_dir: Path) -> None:
    assert _run(deck_dir, [_row(deck_dir, "glorp", "label", proposed="glorpo")])[0] == 0
    entry = load_deck(deck_dir).concept("glorp").locales["es"]  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
    assert entry.label == "glorpo"
    assert list(entry.overrides) == ["glorpo"]


def test_stale_fingerprint_is_rejected_and_nothing_is_written(deck_dir: Path, capsys: Any) -> None:
    row = _row(deck_dir, "glorp", "aliases", proposed="glibber")
    concepts = deck_dir / "concepts.yaml"
    concepts.write_text(concepts.read_text(encoding="utf-8").replace("blobo", "blobbo"), encoding="utf-8")
    before = _tree(deck_dir)
    assert _run(deck_dir, [row])[0] == 1
    [o] = _outcomes(capsys)
    assert (o["status"], o["reason"]) == ("rejected", "stale")
    assert _tree(deck_dir) == before


def test_second_decision_on_a_just_changed_entry_is_stale(deck_dir: Path, capsys: Any) -> None:
    rows = [
        _row(deck_dir, "glorp", "aliases", proposed="glibber"),
        _row(deck_dir, "glorp", "aliases", proposed="gloop2"),
    ]
    assert _run(deck_dir, rows)[0] == 1
    assert [(o["status"], o["reason"]) for o in _outcomes(capsys)] == [("applied", ""), ("rejected", "stale")]


def test_label_and_aliases_rows_on_one_entry_are_independent(deck_dir: Path, capsys: Any) -> None:
    rows = [_row(deck_dir, "glorp", "label", proposed="glorpo"), _row(deck_dir, "glorp", "aliases", proposed="glibber")]
    assert _run(deck_dir, rows)[0] == 0
    assert [o["status"] for o in _outcomes(capsys)] == ["applied", "applied"]


@pytest.mark.parametrize(
    "bad_id",
    ["nope:glorp:es:review_aliases", "zoo:ghost:es:review_aliases", "zoo:wumble:es:review_aliases",
     # ^ wumble is not in zoo
     "zoo:glorp:xx:review_aliases", "zoo:glorp:es:answer_shared:blobo", "garbage"],
)  # fmt: skip
def test_unknown_id_is_rejected(deck_dir: Path, capsys: Any, bad_id: str) -> None:
    row = _row(deck_dir, "glorp", "aliases", proposed="glibber") | {"id": bad_id}
    assert _run(deck_dir, [row])[0] == 1
    [o] = _outcomes(capsys)
    assert (o["status"], o["reason"]) == ("rejected", "unknown")


def test_alias_change_that_creates_a_collision_is_rejected(deck_dir: Path, capsys: Any) -> None:
    # zint gains "blobo", which glorp already accepts in the same group (es)
    before = _tree(deck_dir)
    assert _run(deck_dir, [_row(deck_dir, "zint", "aliases", proposed="blobo")])[0] == 1
    [o] = _outcomes(capsys)
    assert (o["status"], o["reason"]) == ("rejected", "invalid")
    assert "answer_shared" in o["detail"]
    assert _tree(deck_dir) == before


def test_plural_collision_is_also_rejected(deck_dir: Path, capsys: Any) -> None:
    assert _run(deck_dir, [_row(deck_dir, "zint", "aliases", proposed="blobos")])[0] == 1
    assert _outcomes(capsys)[0]["reason"] == "invalid"


def test_alias_equal_to_label_is_rejected(deck_dir: Path, capsys: Any) -> None:
    assert _run(deck_dir, [_row(deck_dir, "glorp", "aliases", proposed="Glorpá")])[0] == 1
    [o] = _outcomes(capsys)
    assert (o["reason"], "alias_equals_label" in o["detail"]) == ("invalid", True)


def test_preexisting_errors_do_not_block_an_unrelated_fix(
    defective_seed: dict[str, Any], tmp_path: Path, capsys: Any
) -> None:
    from sensebank.sixss import import_6ss
    from sensebank.store import save_deck

    directory = tmp_path / "deck"
    save_deck(import_6ss(defective_seed, commit="abc"), directory)
    assert _run(directory, [_row(directory, "zint", "aliases", proposed="zinger; zingo", locale="en")])[0] == 0
    assert _outcomes(capsys)[0]["status"] == "applied"


def test_edit_uses_the_edited_text_and_accept_uses_proposed(deck_dir: Path, capsys: Any) -> None:
    rows = [
        _row(deck_dir, "glorp", "aliases", "edit", proposed="ignored", edited="glibber"),
        _row(deck_dir, "zint", "label", "accept", proposed="zintaa", edited="ignored"),
    ]
    assert _run(deck_dir, rows)[0] == 0
    capsys.readouterr()
    deck = load_deck(deck_dir)
    assert deck.concept("glorp").locales["es"].aliases == ["glibber"]  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
    assert deck.concept("zint").locales["es"].label == "zintaa"  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]


def test_decision_values(deck_dir: Path, capsys: Any) -> None:
    rows = [
        _row(deck_dir, "glorp", "aliases", "reject", proposed="x"),
        _row(deck_dir, "glorp", "aliases", "", proposed="x"),
        _row(deck_dir, "glorp", "aliases", "maybe", proposed="x"),
        _row(deck_dir, "glorp", "aliases", "accept"),  # no proposed
        _row(deck_dir, "glorp", "aliases", "edit", proposed="x"),  # no edited
        _row(deck_dir, "glorp", "label", "accept", proposed="  "),
    ]
    before = _tree(deck_dir)
    assert _run(deck_dir, rows)[0] == 1
    got = [(o["status"], o["reason"]) for o in _outcomes(capsys)]
    assert got == [
        ("skipped", "declined"), ("skipped", "undecided"), ("rejected", "invalid decision"),
        ("rejected", "invalid"), ("rejected", "invalid"), ("rejected", "invalid"),
    ]  # fmt: skip
    assert _tree(deck_dir) == before


def test_rerun_is_idempotent(deck_dir: Path, capsys: Any) -> None:
    rows = [_row(deck_dir, "glorp", "aliases", proposed="glibber")]
    assert _run(deck_dir, rows)[0] == 0
    capsys.readouterr()
    after_first = _tree(deck_dir)
    assert _run(deck_dir, rows)[0] == 0  # same file, old fingerprint: already in place, not stale
    [o] = _outcomes(capsys)
    assert (o["status"], o["reason"]) == ("skipped", "already applied")
    assert _tree(deck_dir) == after_first


def test_dry_run_writes_nothing_but_judges_every_row(deck_dir: Path, capsys: Any) -> None:
    rows = [
        _row(deck_dir, "glorp", "aliases", proposed="blobo; glibber"),
        _row(deck_dir, "zint", "aliases", proposed="blobo"),
    ]
    before = _tree(deck_dir)
    assert _run(deck_dir, rows, "--dry-run")[0] == 1
    out = json.loads(capsys.readouterr().out)
    assert (out["dry_run"], out["written"]) == (True, False)
    assert [o["status"] for o in out["outcomes"]] == ["applied", "rejected"]
    assert _tree(deck_dir) == before


def test_every_row_is_accounted(deck_dir: Path, capsys: Any) -> None:
    rows = [
        _row(deck_dir, "glorp", "aliases", proposed="blobo; glibber"),
        _row(deck_dir, "glorp", "aliases", "reject"),
        _row(deck_dir, "zint", "aliases", "", proposed="x"),
        _row(deck_dir, "zint", "aliases", proposed="blobo"),
    ] + [_row(deck_dir, "glorp", "aliases", proposed="x") | {"id": f"x:y:z:review_label{i}"} for i in range(3)]
    _run(deck_dir, rows)
    out = json.loads(capsys.readouterr().out)
    assert [o["id"] for o in out["outcomes"]] == [r["id"] for r in rows]
    assert sum(out["summary"].values()) == len(rows)
    assert out["summary"] == {"applied": 1, "rejected": 4, "skipped": 2}


def test_text_report_names_every_row(deck_dir: Path, capsys: Any) -> None:
    csv_path = _csv(deck_dir.parent / "d.csv", [_row(deck_dir, "glorp", "aliases", proposed="glibber")])
    assert main(["apply", str(deck_dir), str(csv_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would apply  zoo:glorp:es:review_aliases -> glibber" in out
    assert out.endswith("1 would apply, 0 rejected, 0 skipped (nothing written)\n")


def test_decision_csv_needs_its_columns(deck_dir: Path, capsys: Any) -> None:
    bad = deck_dir.parent / "bad.csv"
    bad.write_text("id,decision\nx,accept\n", encoding="utf-8")
    assert main(["apply", str(deck_dir), str(bad)]) == 2
    assert "fingerprint" in capsys.readouterr().err


def test_missing_deck_is_exit_3(tmp_path: Path) -> None:
    path = _csv(tmp_path / "d.csv", [])
    assert main(["apply", str(tmp_path / "nope"), str(path)]) == 3


def test_a_deck_edited_during_apply_is_not_overwritten(deck_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter([(b"a", b"a"), (b"a", b"b")])
    monkeypatch.setattr(applying, "_snapshot", lambda _d: next(calls))
    rows = [applying.DecisionRow(**{k: v for k, v in _row(deck_dir, "glorp", "aliases", proposed="glibber").items()
                                    if k in {"id", "fingerprint", "decision", "proposed"}})]  # fmt: skip
    before = _tree(deck_dir)
    with pytest.raises(DeckError, match="changed on disk"):
        applying.apply_file(deck_dir, rows, reviewer="r", date="2026-11-15", dry_run=False)
    assert _tree(deck_dir) == before
