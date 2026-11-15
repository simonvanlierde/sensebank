from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sensebank.model import DeckError
from sensebank.sixss import export_6ss, import_6ss
from sensebank.store import load_deck, save_deck

if TYPE_CHECKING:
    from pathlib import Path


def test_import_builds_concepts_groups_and_provenance(clean_seed: dict[str, Any]) -> None:
    deck = import_6ss(clean_seed, commit="abc1234")
    assert deck.locales == ["en", "es", "fr"]
    assert [c.id for c in deck.concepts] == ["glorp", "zint", "wumble"]
    glorp = deck.concepts[0]
    assert glorp.gloss == "glorp"
    assert glorp.wikidata is None
    assert [g.id for g in deck.groups] == ["zoo", "kitchen"]
    assert deck.groups[1].members == ["zint", "wumble"]
    prov = deck.provenance("glorp", "es", "blobo")
    assert "@ abc1234" in prov.source.name
    assert prov.source.licence == "MIT"
    assert prov.review == "unreviewed"


def test_save_load_round_trip_is_stable(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    deck = import_6ss(clean_seed, commit="abc1234")
    save_deck(deck, tmp_path / "a")
    reloaded = load_deck(tmp_path / "a")
    assert reloaded == deck
    save_deck(reloaded, tmp_path / "b")
    for path in sorted((tmp_path / "a").rglob("*.yaml")):
        assert path.read_bytes() == (tmp_path / "b" / path.relative_to(tmp_path / "a")).read_bytes()


def test_one_file_per_group(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    assert sorted(p.name for p in (tmp_path / "groups").iterdir()) == ["kitchen.yaml", "zoo.yaml"]


def test_export_reproduces_the_seed_file(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    assert export_6ss(load_deck(tmp_path)) == clean_seed


def test_load_rejects_duplicate_concept_ids(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    path = tmp_path / "concepts.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text + text[: text.index("- id: zint")], encoding="utf-8")
    with pytest.raises(DeckError, match="duplicate concept id 'glorp'"):
        load_deck(tmp_path)
    clean_seed["prompts"].append(clean_seed["prompts"][0])
    with pytest.raises(DeckError, match="duplicate concept id 'glorp'"):
        import_6ss(clean_seed, commit="x")


def test_load_rejects_unknown_source(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    path = tmp_path / "concepts.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("source: six-second-scribbles", "source: nowhere", 1))
    with pytest.raises(DeckError, match="unknown source 'nowhere'"):
        load_deck(tmp_path)


def test_load_rejects_bad_wikidata_id(clean_seed: dict[str, Any], tmp_path: Path) -> None:
    save_deck(import_6ss(clean_seed, commit="x"), tmp_path)
    path = tmp_path / "concepts.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  gloss: glorp\n", "  gloss: glorp\n  wikidata: {qid: nope, review: unreviewed}\n"
        )
    )
    with pytest.raises(DeckError, match="wikidata"):
        load_deck(tmp_path)


def test_export_needs_no_wikidata(clean_seed: dict[str, Any]) -> None:
    deck = import_6ss(clean_seed, commit="x")
    deck.concepts[0].wikidata = None  # missing coverage never blocks an entry
    assert export_6ss(deck) == clean_seed
