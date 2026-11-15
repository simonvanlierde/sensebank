"""Malformed decks and seeds raise DeckError naming the field, and never write outside the deck."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from sensebank.model import DeckError, Group
from sensebank.sixss import import_6ss, read_quality_rules
from sensebank.store import load_deck, save_deck

if TYPE_CHECKING:
    from collections.abc import Callable


def _deck_dir(seed: dict[str, Any], tmp_path: Path) -> Path:
    save_deck(import_6ss(seed, commit="x"), tmp_path / "deck")
    return tmp_path / "deck"


def _edit(path: Path, change: Callable[[Any], None]) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _set_label(*, value: object) -> Callable[[Any], None]:
    def change(concepts: Any) -> None:
        concepts[0]["locales"]["en"]["label"] = value

    return change


@pytest.mark.parametrize(
    ("file", "change", "match"),
    [
        ("concepts.yaml", _set_label(value=True), "concept glorp/en: label must be a string, got True"),  # label: yes
        ("concepts.yaml", _set_label(value=None), "concept glorp/en: label must be a string, got None"),  # label:
        ("concepts.yaml", lambda c: c[0].update(id=83), "concept: id must be a string, got 83"),  # id: 0123
        ("concepts.yaml", lambda c: c[0].update(gloss=1.5), "concept glorp: gloss must be a string"),
        ("concepts.yaml", lambda c: c[0]["locales"]["en"]["aliases"].append(7), "concept glorp/en: aliases"),
        ("concepts.yaml", lambda c: c[0]["locales"]["en"].update(source=False), "concept glorp/en: source"),
        ("concepts.yaml", lambda c: c[0].update(wikidata={"qid": 42}), "concept glorp wikidata: qid"),
        ("groups/zoo.yaml", lambda g: g["names"].update(en=True), "group zoo: names/en must be a string"),
        ("deck.yaml", lambda d: d["sources"]["six-second-scribbles"].update(name=1), "source six-second-scr.*name"),
        ("deck.yaml", lambda d: d["sources"]["six-second-scribbles"].update(snapshot=None), "snapshot"),
    ],
)
def test_unquoted_scalars_are_not_coerced(
    clean_seed: dict[str, Any], tmp_path: Path, file: str, change: Callable[[Any], None], match: str
) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / file, change)
    with pytest.raises(DeckError, match=match):
        load_deck(deck)


@pytest.mark.parametrize("value", ["false", 0, None])
def test_group_rule_flags_must_be_booleans(clean_seed: dict[str, Any], tmp_path: Path, value: object) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / "groups/zoo.yaml", lambda g: g["rules"].update(unique_answers=value))
    with pytest.raises(DeckError, match="group zoo: rules/unique_answers must be true or false"):
        load_deck(deck)


def test_import_rejects_a_non_string_label(clean_seed: dict[str, Any]) -> None:
    clean_seed["prompts"][1]["translations"][0]["label"] = True
    with pytest.raises(DeckError, match="concept zint/en: label must be a string, got True"):
        import_6ss(clean_seed, commit="x")


@pytest.mark.parametrize(
    ("file", "change", "match"),
    [
        ("concepts.yaml", lambda c: c[0]["locales"].update(en=["glorp"]), "concept glorp/en: expected a mapping"),
        ("concepts.yaml", lambda c: c[0].update(locales=["en"]), "concept glorp: locales must be a mapping"),
        ("concepts.yaml", lambda c: c[0]["locales"]["en"].update(overrides=["blob"]), "overrides must be a mapping"),
        ("concepts.yaml", lambda c: c.__setitem__(0, "glorp"), "concept: expected a mapping"),
        ("groups/zoo.yaml", lambda g: g["rules"].update(uniq=True), "group zoo: unknown rules key 'uniq'"),
        ("groups/zoo.yaml", lambda g: g.update(shared_answers=[["es", "x"]]), "group zoo: shared_answers"),
        ("deck.yaml", lambda d: d.update(rules={"junk": ["x"]}), "deck rules: unknown key 'junk'"),
        ("deck.yaml", lambda d: d.update(sources=["six-second-scribbles"]), "sources must be a mapping"),
    ],
)
def test_malformed_structure_is_a_deck_error(
    clean_seed: dict[str, Any], tmp_path: Path, file: str, change: Callable[[Any], None], match: str
) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / file, change)
    with pytest.raises(DeckError, match=match):
        load_deck(deck)


@pytest.mark.parametrize(
    "table",
    [
        "JUNK_TOKENS = open('x')",  # a call literal_eval refuses: ValueError
        "JUNK_TOKENS = [1 +]",  # SyntaxError
        "SHARED_ANSWERS = (('es', 'zoo'),)",  # a row that does not unpack: ValueError
    ],
)
def test_bad_quality_tables_are_a_deck_error(tmp_path: Path, table: str) -> None:
    tables = {
        "JUNK_TOKENS": "JUNK_TOKENS = ['x']",
        "NAMES": "NAMES = frozenset()",
        "SHARED_WORDS": "SHARED_WORDS = {}",
        "SHARED_ANSWERS": "SHARED_ANSWERS = ()",
    }
    tables[table.split(" ", 1)[0]] = table
    path = tmp_path / "quality.py"
    path.write_text("\n".join(tables.values()) + "\n", encoding="utf-8")
    with pytest.raises(DeckError, match=r"quality\.py"):
        read_quality_rules(path)


def test_shared_answer_for_an_unknown_category_is_a_deck_error(clean_seed: dict[str, Any]) -> None:
    with pytest.raises(DeckError, match="SHARED_ANSWERS names category 'attic', which the seed file lacks"):
        import_6ss(clean_seed, commit="x", shared=[("es", "attic", "x", ["glorp", "zint"])])


def test_import_takes_every_prompts_locales_in_first_seen_order(clean_seed: dict[str, Any]) -> None:
    clean_seed["prompts"][0]["translations"].pop()  # glorp has no fr
    clean_seed["prompts"][1]["translations"].append({"locale": "nl", "label": "zintje", "aliases": []})
    assert import_6ss(clean_seed, commit="x").locales == ["en", "es", "fr", "nl"]


@pytest.mark.parametrize(
    ("file", "change", "match"),
    [
        ("concepts.yaml", lambda c: c[0]["locales"].update(de=c[0]["locales"]["en"]), "concept glorp: locale 'de'"),
        ("groups/zoo.yaml", lambda g: g["names"].update(de="Zoo"), "group zoo: locale 'de' is not in the deck"),
        ("concepts.yaml", lambda c: c[0].update(id="glo:rp"), "concept id 'glo:rp' must match"),
        ("deck.yaml", lambda d: d["locales"].append("e:n"), "deck locale 'e:n' must match"),
        ("deck.yaml", lambda d: d["locales"].append("en"), "deck locale 'en' is listed twice"),
    ],
)
def test_locales_and_ids_are_validated(
    clean_seed: dict[str, Any], tmp_path: Path, file: str, change: Callable[[Any], None], match: str
) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / file, change)
    with pytest.raises(DeckError, match=match):
        load_deck(deck)


def test_import_rejects_a_group_id_that_leaves_the_deck(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    clean_seed["system_categories"][0]["id"] = "../../escaped"
    with pytest.raises(DeckError, match=re.escape("group id '../../escaped' must match")):
        save_deck(import_6ss(clean_seed, commit="x"), tmp_path / "a" / "b")
    assert list(tmp_path.rglob("*.yaml")) == []


def test_save_rejects_a_bad_group_id_before_writing(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    deck = import_6ss(clean_seed, commit="x")
    deck.groups.append(Group(id="../escaped", members=["glorp"]))
    with pytest.raises(DeckError, match=re.escape("group id '../escaped' must match")):
        save_deck(deck, tmp_path / "deck")
    assert list(tmp_path.rglob("*.yaml")) == []


def test_load_checks_group_ids_before_building_paths(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    (deck / "outside.yaml").write_text("id: outside\nmembers: [glorp]\n", encoding="utf-8")
    _edit(deck / "deck.yaml", lambda d: d["groups"].append("../outside"))
    with pytest.raises(DeckError, match=re.escape("group id '../outside' must match")):
        load_deck(deck)


@pytest.mark.parametrize(
    ("file", "change", "match"),
    [
        ("groups/zoo.yaml", lambda g: g.update(id="kitchen"), "groups/zoo.yaml: id 'kitchen' differs from 'zoo'"),
        ("deck.yaml", lambda d: d["groups"].append("zoo"), "group id 'zoo' is listed twice"),
        ("groups/zoo.yaml", lambda g: g["members"].append("glorp"), "group zoo: member 'glorp' is listed twice"),
    ],
)
def test_group_files_must_agree_with_the_deck(
    clean_seed: dict[str, Any], tmp_path: Path, file: str, change: Callable[[Any], None], match: str
) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / file, change)
    with pytest.raises(DeckError, match=match):
        load_deck(deck)


@pytest.mark.parametrize("char", ["\u0085", "\u2028", "\u2029", "\x9b"])
def test_line_separators_and_c1_controls_are_rejected(clean_seed: dict[str, Any], tmp_path: Path, char: str) -> None:
    deck = _deck_dir(clean_seed, tmp_path)
    _edit(deck / "concepts.yaml", lambda c: c[0]["locales"]["es"]["aliases"].append(f"blo{char}bo"))
    with pytest.raises(DeckError, match=r"holds U\+"):
        load_deck(deck)
    deck_obj = import_6ss(clean_seed, commit="x")
    deck_obj.concepts[0].locales["es"].aliases.append(f"blo{char}bo")
    with pytest.raises(DeckError, match=r"concept glorp/es: aliases.*U\+"):
        save_deck(deck_obj, tmp_path / "other")
    clean_seed["prompts"][0]["translations"][1]["label"] = f"glo{char}rpa"
    with pytest.raises(DeckError, match=r"concept glorp/es: label.*U\+"):
        import_6ss(clean_seed, commit="x")


def test_failed_save_leaves_the_old_deck(
    clean_seed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck_dir = _deck_dir(clean_seed, tmp_path)
    before = load_deck(deck_dir)
    smaller = import_6ss(clean_seed, commit="new")
    smaller.groups.pop()  # kitchen would become stale

    def boom(_group: Group) -> Any:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr("sensebank.store.group_to_dict", boom)
    with pytest.raises(OSError, match="disk full"):
        save_deck(smaller, deck_dir)
    assert load_deck(deck_dir) == before


def test_save_writes_lf_on_every_platform(
    clean_seed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.write_text

    def windows_write_text(self: Path, data: str, encoding: str | None = None, errors: str | None = None,
                           newline: str | None = None) -> int:  # fmt: skip
        if newline is None:  # what text mode does on Windows
            data = data.replace("\n", "\r\n")
        return real(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", windows_write_text)
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    assert not any(b"\r" in p.read_bytes() for p in tmp_path.rglob("*.yaml"))
