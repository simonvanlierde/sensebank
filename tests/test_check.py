from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sensebank.check import check_deck
from sensebank.findings import CSV_COLUMNS, to_csv, to_json
from sensebank.model import SharedAnswer
from sensebank.sixss import import_6ss

if TYPE_CHECKING:
    from sensebank.model import Deck


def _tr(seed: dict[str, Any], prompt: str, locale: str) -> dict[str, Any]:
    entry = next(p for p in seed["prompts"] if p["id"] == prompt)
    return next(t for t in entry["translations"] if t["locale"] == locale)


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
        f"zoo:glorp:es:alias:answer_shared:{_h('blobo')}",
        f"zoo:zint:es:alias:answer_shared:{_h('blobos')}",
    ]
    f = next(f for f in found if f.id.startswith("zoo:glorp"))
    assert (f.locale, f.severity, f.source, f.target) == ("es", "error", "glorp", "blobo")
    assert "zint" in f.context


def test_alias_equal_to_label(defective_seed: dict[str, Any]) -> None:
    [f] = _kinds(defective_seed)["alias_equals_label"]
    assert (f.id, f.target, f.proposed) == (f"glorp:fr:alias:alias_equals_label:{_h('Glorpé')}", "Glorpé", "")


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
    deck.groups[0].shared_answers.append(SharedAnswer(locale="es", answer="blobo", concepts=["glorp", "zint"]))
    kinds = {f.kind for f in check_deck(deck)}
    assert "answer_shared" not in kinds


def test_stale_allowance_is_reported(clean_seed: dict[str, Any]) -> None:
    deck = import_6ss(clean_seed, commit="x")
    deck.groups[0].shared_answers.append(SharedAnswer(locale="es", answer="nothing", concepts=["glorp", "zint"]))
    assert [f.kind for f in check_deck(deck)] == ["stale_allowance"]


def test_fingerprint_follows_the_entry(defective_seed: dict[str, Any]) -> None:
    before = {f.id: f.fingerprint for f in check_deck(import_6ss(defective_seed, commit="x"))}
    defective_seed["prompts"][1]["translations"][1]["label"] = "zintaa"
    after = {f.id: f.fingerprint for f in check_deck(import_6ss(defective_seed, commit="x"))}
    zint, glorp = f"zoo:zint:es:alias:answer_shared:{_h('blobos')}", f"zoo:glorp:es:alias:answer_shared:{_h('blobo')}"
    assert before[zint] != after[zint]
    assert before[glorp] == after[glorp]
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


def _h(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()[:8]


def _ids(deck: Deck) -> list[str]:
    ids = [f.id for f in check_deck(deck)]
    assert len(ids) == len(set(ids))  # a repeated id would mean a finding was merged away
    return ids


def test_concept_finding_ids_do_not_depend_on_group_order(defective_seed: dict[str, Any]) -> None:
    deck = import_6ss(defective_seed, commit="x")
    before = _ids(deck)
    deck.groups.reverse()
    assert sorted(_ids(deck)) == sorted(before)
    assert f"zint:en:alias:duplicate_alias:{_h('zinger')}" in before


def test_alias_distinct_applies_if_any_owning_group_asks(defective_seed: dict[str, Any]) -> None:
    deck = import_6ss(defective_seed, commit="x")  # zint is in zoo and kitchen and repeats an alias
    for first_opts_out in (True, False):
        deck.groups[0].alias_distinct = not first_opts_out
        deck.groups[1].alias_distinct = first_opts_out
        assert "duplicate_alias" in {f.kind for f in check_deck(deck)}
    deck.groups[0].alias_distinct = deck.groups[1].alias_distinct = False
    assert "duplicate_alias" not in {f.kind for f in check_deck(deck)}


def test_label_and_alias_findings_are_both_kept(clean_seed: dict[str, Any]) -> None:
    _tr(clean_seed, "glorp", "es").update(label="glorpa!", aliases=["glorpa!"])
    found = [(f.key, f.kind) for f in check_deck(import_6ss(clean_seed, commit="x")) if f.target == "glorpa!"]
    assert ("label", "stray_text") in found
    assert ("alias", "stray_text") in found


def test_ids_hash_the_raw_word(clean_seed: dict[str, Any]) -> None:
    _tr(clean_seed, "glorp", "en")["aliases"] = ["cat", "Cat", "CAT", "cat", "a:b\nc"]
    deck = import_6ss(clean_seed, commit="x")
    found = [f for f in check_deck(deck) if f.kind in {"duplicate_alias", "stray_text"}]
    assert sorted((f.kind, f.target) for f in found) == [
        ("duplicate_alias", "CAT"), ("duplicate_alias", "Cat"), ("duplicate_alias", "cat"), ("stray_text", "a:b\nc"),
    ]  # fmt: skip
    assert all(len(f.id.split(":")) == 5 for f in found)
    assert all("\n" not in i for i in _ids(deck))


def test_every_finding_survives_repeats(clean_seed: dict[str, Any]) -> None:
    _tr(clean_seed, "glorp", "en")["aliases"] = ["blob!", "blob!", "blob!"]
    deck = import_6ss(clean_seed, commit="x")
    deck.groups[0].shared_answers += [
        SharedAnswer("es", "nothing", ["glorp", "zint"]),
        SharedAnswer("es", "Nothing", ["glorp", "zint"]),
        SharedAnswer("es", "nothing", ["glorp", "zint"]),
    ]
    found = check_deck(deck)
    assert [f.kind for f in found].count("stray_text") == 3
    assert [f.kind for f in found].count("duplicate_alias") == 2
    stale = [f.id for f in found if f.kind == "stale_allowance"]
    assert len(stale) == 3
    assert stale[1] == f"zoo:glorp:es:answer:stale_allowance:{_h('Nothing')}"
    _ids(deck)


def test_group_names_are_checked(clean_seed: dict[str, Any]) -> None:
    deck = import_6ss(clean_seed, commit="x")
    deck.rules.cjk_locales = ["fr"]
    deck.rules.junk_tokens = ["Kuchea"]
    deck.groups[0].names["en"] = "Zoo "
    found = {(f.id, f.key, f.kind, f.target) for f in check_deck(deck)}
    assert found == {
        (f"zoo:-:fr:name:ascii_in_cjk:{_h('Zooe')}", "name", "ascii_in_cjk", "Zooe"),
        (f"kitchen:-:fr:name:ascii_in_cjk:{_h('Kuche')}", "name", "ascii_in_cjk", "Kuche"),
        (f"kitchen:-:es:name:junk_text:{_h('Kuchea')}", "name", "junk_text", "Kuchea"),
        (f"zoo:-:en:name:stray_text:{_h('Zoo ')}", "name", "stray_text", "Zoo "),
    } | {(f.id, f.key, f.kind, f.target) for f in check_deck(deck) if f.key != "name"}


def test_stray_text_proposal_drops_the_stray_symbol(clean_seed: dict[str, Any]) -> None:
    _tr(clean_seed, "glorp", "en")["aliases"] = ["blob!", "gloop  (x)"]
    found = {f.target: f.proposed for f in check_deck(import_6ss(clean_seed, commit="x")) if f.kind == "stray_text"}
    assert found == {"blob!": "blob", "gloop  (x)": "gloop x"}


def test_csv_neutralises_formula_cells_and_round_trips(defective_seed: dict[str, Any]) -> None:
    from sensebank.findings import unescape_cell

    first = check_deck(import_6ss(defective_seed, commit="x"))[0]
    texts = ["=HYPERLINK(1)", "+1", "-x", "@sum", "\tx", "\rx", "'=x", "''+x", "'s-Hertogenbosch", "plain"]
    findings = [replace(first, target=text, message=text) for text in texts]
    rows = list(csv.DictReader(io.StringIO(to_csv(findings))))
    assert rows[0]["target"] == "'=HYPERLINK(1)"
    assert rows[6]["target"] == "''=x"
    assert rows[8]["target"] == "'s-Hertogenbosch"
    assert rows[0]["id"] == findings[0].id  # only text columns are escaped
    assert [unescape_cell(r["target"]) for r in rows[: len(texts)]] == texts
    assert [unescape_cell(r["message"]) for r in rows[: len(texts)]] == texts


def test_japanese_voicing_keeps_group_answers_apart(clean_seed: dict[str, Any]) -> None:
    import unicodedata

    nfd_bus = unicodedata.normalize("NFD", "ばす")
    clean_seed["prompts"][0]["translations"].append({"locale": "ja", "label": "ガラス", "aliases": ["ばす"]})
    clean_seed["prompts"][1]["translations"].append({"locale": "ja", "label": "カラス", "aliases": [nfd_bus]})
    shared = [(f.source, f.target) for f in check_deck(import_6ss(clean_seed, commit="x")) if f.kind == "answer_shared"]
    # ガラス (glass) and カラス (crow) differ; the decomposed ばす is still the composed one
    assert sorted(shared) == [("glorp", "ばす"), ("zint", nfd_bus)]
