from __future__ import annotations

import csv
import io
import json
from typing import Any

from sensebank.check import check_deck
from sensebank.findings import CSV_COLUMNS, to_csv, to_json
from sensebank.sixss import import_6ss


def _kinds(seed: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for finding in check_deck(import_6ss(seed, commit="x")):
        out.setdefault(finding.kind, []).append(finding)
    return out


def test_clean_deck_has_no_findings(clean_seed: dict[str, Any]) -> None:
    assert _kinds(clean_seed) == {}


def test_answer_shared_in_group(defective_seed: dict[str, Any]) -> None:
    found = _kinds(defective_seed)["answer_shared"]
    # both sides are reported, so a reviewer can decide on either entry
    assert sorted(f.id for f in found) == [
        "zoo:glorp:es:answer_shared:blobo",
        "zoo:zint:es:answer_shared:blobos",
    ]
    f = next(f for f in found if f.id.startswith("zoo:glorp"))
    assert (f.locale, f.severity, f.source, f.target) == ("es", "error", "glorp", "blobo")
    assert "zint" in f.context


def test_alias_equal_to_label(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["alias_equals_label"]
    assert (f.id, f.target, f.proposed) == ("zoo:glorp:fr:alias_equals_label:glorpe", "Glorpé", "")


def test_duplicate_alias(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["duplicate_alias"]
    assert (f.locale, f.target) == ("en", "zinger")


def test_empty_label(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["empty_label"]
    assert (f.locale, f.source, f.severity) == ("fr", "wumble", "error")


def test_missing_locale(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["missing_locale"]
    assert (f.locale, f.source) == ("fr", "flib")


def test_stray_text(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["stray_text"]
    assert (f.target, f.proposed) == (" wumbla", "wumbla")


def test_unknown_member_and_orphan(defective_seed: dict[str, Any]) -> None:
    kinds = _kinds(defective_seed)
    assert [f.target for f in kinds["unknown_member"]] == ["ghost"]
    assert [f.target for f in kinds["orphan_concept"]] == ["orphan"]


def test_shared_answer_allowance_silences_a_collision(defective_seed: dict[str, Any]) -> None:
    deck = import_6ss(defective_seed, commit="x")
    from sensebank.model import SharedAnswer

    deck.groups[0].shared_answers.append(SharedAnswer(locale="es", answer="blobo", concepts=["glorp", "zint"]))
    kinds = {f.kind for f in check_deck(deck)}
    assert "answer_shared" not in kinds


def test_stale_allowance_is_reported(clean_seed: dict[str, Any]) -> None:
    from sensebank.model import SharedAnswer

    deck = import_6ss(clean_seed, commit="x")
    deck.groups[0].shared_answers.append(SharedAnswer(locale="es", answer="nothing", concepts=["glorp", "zint"]))
    assert [f.kind for f in check_deck(deck)] == ["stale_allowance"]


def test_fingerprint_follows_the_entry(defective_seed: dict[str, Any]) -> None:
    before = {f.id: f.fingerprint for f in check_deck(import_6ss(defective_seed, commit="x"))}
    defective_seed["prompts"][1]["translations"][1]["label"] = "zintaa"
    after = {f.id: f.fingerprint for f in check_deck(import_6ss(defective_seed, commit="x"))}
    assert before["zoo:zint:es:answer_shared:blobos"] != after["zoo:zint:es:answer_shared:blobos"]
    assert before["zoo:glorp:es:answer_shared:blobo"] == after["zoo:glorp:es:answer_shared:blobo"]
    assert len(next(iter(before.values()))) == 8


def test_csv_columns_match_the_shared_decision_columns(defective_seed: dict[str, Any]) -> None:
    findings = check_deck(import_6ss(defective_seed, commit="x"))
    rows = list(csv.DictReader(io.StringIO(to_csv(findings))))
    assert list(rows[0]) == CSV_COLUMNS
    assert CSV_COLUMNS == [
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
    assert {r["decision"] for r in rows} == {""}
    assert len(rows) == len(findings)
    assert json.loads(to_json(findings))["findings"][0]["id"] == findings[0].id


def test_order_is_stable(defective_seed: dict[str, Any]) -> None:
    a = [f.id for f in check_deck(import_6ss(defective_seed, commit="x"))]
    assert a == [f.id for f in check_deck(import_6ss(defective_seed, commit="x"))]
    assert len(a) == len(set(a))


def test_script_text_and_untranslated_rules(clean_seed: dict[str, Any]) -> None:
    seed = clean_seed
    seed["prompts"][0]["translations"][1]["aliases"] = ["blob", "glorp-"]  # es alias equal to English alias
    seed["prompts"][1]["translations"][2]["aliases"] = ["ascii", "ガ"]  # fr stands in for a CJK locale below
    seed["prompts"][2]["translations"][2]["aliases"] = ["!!"]
    deck = import_6ss(seed, commit="x")
    deck.rules.cjk_locales = ["fr"]
    deck.rules.shared_words = {"es": ["blob"]}
    kinds = {(f.kind, f.target) for f in check_deck(deck)}
    assert ("ascii_in_cjk", "ascii") in kinds
    assert ("ascii_in_cjk", "ガ") not in kinds
    assert ("junk_text", "!!") in kinds
    assert not any(k == "untranslated_alias" and t == "blob" for k, t in kinds)  # allowed loanword
    deck.rules.shared_words = {}
    assert ("untranslated_alias", "blob") in {(f.kind, f.target) for f in check_deck(deck)}
