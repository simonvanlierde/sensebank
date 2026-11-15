"""Deck directory: deck.yaml (sources, rules, order), concepts.yaml, groups/<id>.yaml."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import yaml

from sensebank.model import (
    Deck,
    DeckError,
    Rules,
    concept_from_dict,
    concept_to_dict,
    group_from_dict,
    group_to_dict,
    source_from_dict,
    source_to_dict,
)

if TYPE_CHECKING:
    from pathlib import Path

DECK_FILE = "deck.yaml"
CONCEPTS_FILE = "concepts.yaml"
GROUPS_DIR = "groups"


def dump_yaml(data: Any) -> str:  # noqa: ANN401
    """Block-style YAML in the order given: file order is data, so keys are never sorted."""
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _read(path: Path) -> Any:  # noqa: ANN401
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        msg = f"cannot read {path}: {err}"
        raise DeckError(msg) from err


def save_deck(deck: Deck, directory: Path) -> None:
    """Write the deck, replacing group files that no longer exist."""
    groups_dir = directory / GROUPS_DIR
    groups_dir.mkdir(parents=True, exist_ok=True)
    for stale in groups_dir.glob("*.yaml"):
        if stale.stem not in {g.id for g in deck.groups}:
            stale.unlink()
    head = {
        "name": deck.name,
        "locales": list(deck.locales),
        "sources": {s.id: source_to_dict(s) for s in deck.sources.values()},
        "rules": {k: v for k, v in asdict(deck.rules).items() if v},
        "groups": [g.id for g in deck.groups],
    }
    (directory / DECK_FILE).write_text(dump_yaml(head), encoding="utf-8")
    (directory / CONCEPTS_FILE).write_text(dump_yaml([concept_to_dict(c) for c in deck.concepts]), encoding="utf-8")
    for group in deck.groups:
        (groups_dir / f"{group.id}.yaml").write_text(dump_yaml(group_to_dict(group)), encoding="utf-8")


def load_deck(directory: Path) -> Deck:
    """Read and validate a deck directory. Content problems are findings; only structure raises."""
    head = _read(directory / DECK_FILE)
    if not isinstance(head, dict):
        msg = f"{directory / DECK_FILE}: expected a mapping"
        raise DeckError(msg)
    sources = {sid: source_from_dict(sid, d) for sid, d in (head.get("sources") or {}).items()}
    concepts = [concept_from_dict(d) for d in _read(directory / CONCEPTS_FILE) or []]
    seen: set[str] = set()
    for concept in concepts:
        if concept.id in seen:
            msg = f"duplicate concept id {concept.id!r}"
            raise DeckError(msg)
        seen.add(concept.id)
        for locale, entry in concept.locales.items():
            used = {entry.source, *(o.source for o in entry.overrides.values() if o.source)}
            for source_id in sorted(used - sources.keys()):
                msg = f"concept {concept.id}/{locale}: unknown source {source_id!r}"
                raise DeckError(msg)
    groups = [group_from_dict(_read(directory / GROUPS_DIR / f"{gid}.yaml")) for gid in head.get("groups") or []]
    rules = Rules(**(head.get("rules") or {}))
    return Deck(str(head.get("name", "")), list(head.get("locales") or []), sources, concepts, groups, rules)
