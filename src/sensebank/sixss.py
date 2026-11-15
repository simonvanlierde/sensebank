"""Six Second Scribbles `seed_data.yaml` import and export.

The seed file has `prompts` (id plus per-locale label and aliases) and `system_categories`
(id, difficulty, default_locale, per-locale name, member prompt ids). Prompts become concepts and
categories become groups; difficulty and default_locale ride in the group's `meta`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

from sensebank.model import Concept, Deck, DeckError, Group, Localized, Rules, SharedAnswer, Source

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_ID = "six-second-scribbles"
CJK_LOCALES = ["ja", "ko", "zh-CN", "zh-TW"]


def import_6ss(
    seed: dict[str, Any],
    *,
    commit: str,
    rules: Rules | None = None,
    shared: list[tuple[str, str, str, list[str]]] | None = None,
) -> Deck:
    """Build a deck from parsed seed data. Every word is marked as coming from the seed file."""
    source = Source(
        SOURCE_ID,
        f"six-second-scribbles seed_data.yaml @ {commit}",
        "MIT",
        snapshot=commit,
        url="https://github.com/simonvanlierde/6-second-scribbles",
    )
    concepts = [
        Concept(
            id=p["id"],
            gloss=next((t["label"] for t in p["translations"] if t["locale"] == "en"), p["id"]),
            locales={
                t["locale"]: Localized(t["label"], list(t.get("aliases") or []), source=SOURCE_ID)
                for t in p["translations"]
            },
        )
        for p in seed["prompts"]
    ]
    groups = [
        Group(
            id=c["id"],
            names={t["locale"]: t["name"] for t in c["translations"]},
            members=list(c["items"]),
            meta={"difficulty": c["difficulty"], "default_locale": c["default_locale"]},
        )
        for c in seed["system_categories"]
    ]
    by_id = {g.id: g for g in groups}
    for locale, category, answer, cards in shared or []:
        by_id[category].shared_answers.append(SharedAnswer(locale, answer, sorted(cards)))
    locales = [t["locale"] for t in seed["prompts"][0]["translations"]] if seed["prompts"] else []
    deck_rules = rules or Rules()
    deck_rules.cjk_locales = deck_rules.cjk_locales or CJK_LOCALES
    return Deck("six-second-scribbles", locales, {SOURCE_ID: source}, concepts, groups, deck_rules)


def export_6ss(deck: Deck) -> dict[str, Any]:
    """Rebuild the seed structure. Gloss, Wikidata and provenance have no place in it and are dropped."""
    prompts = [
        {
            "id": c.id,
            "translations": [
                {"locale": loc, "label": e.label, "aliases": list(e.aliases)} for loc, e in c.locales.items()
            ],
        }
        for c in deck.concepts
    ]
    categories = []
    for g in deck.groups:
        for key in ("difficulty", "default_locale"):
            if key not in g.meta:
                msg = f"group {g.id!r} has no meta.{key}, which the seed file needs"
                raise DeckError(msg)
        categories.append(
            {
                "id": g.id,
                "difficulty": g.meta["difficulty"],
                "default_locale": g.meta["default_locale"],
                "translations": [{"locale": loc, "name": name} for loc, name in g.names.items()],
                "items": list(g.members),
            }
        )
    return {"prompts": prompts, "system_categories": categories}


def read_quality_rules(path: Path) -> tuple[Rules, list[tuple[str, str, str, list[str]]]]:
    """Read the allowlists out of 6ss's `test_seed_data_quality.py` without importing it.

    Only the literal tables are evaluated (JUNK_TOKENS, NAMES, SHARED_WORDS, SHARED_ANSWERS).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {"JUNK_TOKENS", "NAMES", "SHARED_WORDS", "SHARED_ANSWERS"}
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in wanted and value is not None:
            code = compile(ast.Expression(value), str(path), "eval")
            found[target.id] = eval(code, {"__builtins__": {}, "frozenset": frozenset})  # noqa: S307 # own repo's literals
    missing = wanted - found.keys()
    if missing:
        msg = f"{path}: no {', '.join(sorted(missing))}"
        raise DeckError(msg)
    rules = Rules(
        junk_tokens=list(found["JUNK_TOKENS"]),
        names=sorted(found["NAMES"]),
        shared_words={loc: sorted(words) for loc, words in found["SHARED_WORDS"].items()},
    )
    return rules, [(loc, cat, ans, sorted(cards)) for loc, cat, ans, cards in found["SHARED_ANSWERS"]]
