"""Deck directory: deck.yaml (sources, rules, order), concepts.yaml, groups/<id>.yaml."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from sensebank.model import (
    BAD_CHARS,
    Deck,
    DeckError,
    check_group_ids,
    concept_from_dict,
    concept_to_dict,
    group_from_dict,
    group_to_dict,
    rules_from_dict,
    rules_to_dict,
    source_from_dict,
    source_to_dict,
    validate_deck,
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
        text = path.read_text(encoding="utf-8")
        # Checked before parsing: YAML reads a raw NEL, LS or PS as a line break, so the text would change.
        if bad := BAD_CHARS.search(text):
            line = text.count("\n", 0, bad.start()) + 1
            msg = f"{path}:{line}: holds U+{ord(bad.group()):04X}, a line break or control character"
            raise DeckError(msg)
        return yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as err:
        msg = f"cannot read {path}: {err}"
        raise DeckError(msg) from err


def _write(path: Path, text: str) -> None:
    """Replace `path` in one step, with LF line ends on every platform, so a crash never leaves half a file."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def save_deck(deck: Deck, directory: Path) -> None:
    """Validate and write the deck, then delete group files that no longer exist."""
    validate_deck(deck)
    head = {
        "name": deck.name,
        "locales": list(deck.locales),
        "sources": {s.id: source_to_dict(s) for s in deck.sources.values()},
        "rules": rules_to_dict(deck.rules),
        "groups": [g.id for g in deck.groups],
    }
    groups_dir = directory / GROUPS_DIR
    files = {
        directory / DECK_FILE: dump_yaml(head),
        directory / CONCEPTS_FILE: dump_yaml([concept_to_dict(c) for c in deck.concepts]),
        **{groups_dir / f"{g.id}.yaml": dump_yaml(group_to_dict(g)) for g in deck.groups},
    }
    groups_dir.mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        _write(path, text)
    for stale in groups_dir.glob("*.yaml"):
        if stale not in files:
            stale.unlink()


def load_deck(directory: Path) -> Deck:
    """Read and validate a deck directory. Content problems are findings; only structure raises."""
    head = _read(directory / DECK_FILE)
    if not isinstance(head, dict):
        msg = f"{directory / DECK_FILE}: expected a mapping"
        raise DeckError(msg)
    sources = head.get("sources") or {}
    if not isinstance(sources, dict):
        msg = f"{directory / DECK_FILE}: sources must be a mapping"
        raise DeckError(msg)
    concepts = _read(directory / CONCEPTS_FILE) or []
    if not isinstance(concepts, list):
        msg = f"{directory / CONCEPTS_FILE}: expected a list of concepts"
        raise DeckError(msg)
    group_ids = head.get("groups") or []
    if not isinstance(group_ids, list):
        msg = f"{directory / DECK_FILE}: groups must be a list of group ids"
        raise DeckError(msg)
    check_group_ids(group_ids)  # before any id becomes part of a path
    groups = []
    for gid in group_ids:
        group = group_from_dict(_read(directory / GROUPS_DIR / f"{gid}.yaml"))
        if group.id != gid:
            msg = f"{GROUPS_DIR}/{gid}.yaml: id {group.id!r} differs from {gid!r}"
            raise DeckError(msg)
        groups.append(group)
    name = head.get("name", "")
    if not isinstance(name, str):
        msg = f"{directory / DECK_FILE}: name must be a string, got {name!r}"
        raise DeckError(msg)
    locales = head.get("locales") or []
    if not isinstance(locales, list):
        msg = f"{directory / DECK_FILE}: locales must be a list"
        raise DeckError(msg)
    deck = Deck(
        name,
        locales,
        {sid: source_from_dict(sid, d) for sid, d in sources.items()},
        [concept_from_dict(d) for d in concepts],
        groups,
        rules_from_dict(head.get("rules")),
    )
    validate_deck(deck)
    return deck
