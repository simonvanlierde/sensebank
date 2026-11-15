"""A small fictional deck: a zoo and a kitchen, in three locales, with no real data."""

from __future__ import annotations

import copy
from typing import Any

import pytest

# Fictional 6ss-shaped seed file. Seeded defects are listed in DEFECTS and exist only in
# `defective_seed`, so the clean one proves the checks stay quiet.
CLEAN_SEED: dict[str, Any] = {
    "prompts": [
        {
            "id": "glorp",
            "translations": [
                {"locale": "en", "label": "glorp", "aliases": ["blob", "gloop"]},
                {"locale": "es", "label": "glorpa", "aliases": ["blobo"]},
                {"locale": "fr", "label": "glorpe", "aliases": []},
            ],
        },
        {
            "id": "zint",
            "translations": [
                {"locale": "en", "label": "zint", "aliases": ["zinger"]},
                {"locale": "es", "label": "zinta", "aliases": []},
                {"locale": "fr", "label": "zinte", "aliases": ["zingere"]},
            ],
        },
        {
            "id": "wumble",
            "translations": [
                {"locale": "en", "label": "wumble", "aliases": []},
                {"locale": "es", "label": "wumbla", "aliases": []},
                {"locale": "fr", "label": "wumble", "aliases": []},
            ],
        },
    ],
    "system_categories": [
        {
            "id": "zoo",
            "difficulty": "easy",
            "default_locale": "en",
            "translations": [
                {"locale": "en", "name": "Zoo"},
                {"locale": "es", "name": "Zooa"},
                {"locale": "fr", "name": "Zooe"},
            ],
            "items": ["glorp", "zint"],
        },
        {
            "id": "kitchen",
            "difficulty": "hard",
            "default_locale": "en",
            "translations": [
                {"locale": "en", "name": "Kitchen"},
                {"locale": "es", "name": "Kuchea"},
                {"locale": "fr", "name": "Kuche"},
            ],
            "items": ["zint", "wumble"],
        },
    ],
}


def _tr(seed: dict[str, Any], prompt: str, locale: str) -> dict[str, Any]:
    entry = next(p for p in seed["prompts"] if p["id"] == prompt)
    return next(t for t in entry["translations"] if t["locale"] == locale)


@pytest.fixture
def clean_seed() -> dict[str, Any]:
    return copy.deepcopy(CLEAN_SEED)


@pytest.fixture
def defective_seed(clean_seed: dict[str, Any]) -> dict[str, Any]:
    seed = clean_seed
    # answer shared by two entries of one group (es, group zoo): plural variant counts too
    _tr(seed, "zint", "es")["aliases"] = ["blobos"]
    _tr(seed, "glorp", "es")["aliases"] = ["blobo"]
    # alias equal to its label (fr, glorp), accent and case ignored
    _tr(seed, "glorp", "fr")["aliases"] = ["Glorpé"]
    # duplicate alias within an entry (en, zint)
    _tr(seed, "zint", "en")["aliases"] = ["zinger", "zinger"]
    # empty label (fr, wumble)
    _tr(seed, "wumble", "fr")["label"] = ""
    # missing locale (fr, wumble keeps no entry... use a second concept for clarity)
    seed["prompts"].append(
        {
            "id": "flib",
            "translations": [
                {"locale": "en", "label": "flib", "aliases": []},
                {"locale": "es", "label": "flibba", "aliases": []},
            ],
        }
    )
    seed["system_categories"][1]["items"].append("flib")
    # stray whitespace
    _tr(seed, "wumble", "es")["label"] = " wumbla"
    # a member that is not a concept
    seed["system_categories"][0]["items"].append("ghost")
    # orphan concept, in no group
    seed["prompts"].append(
        {
            "id": "orphan",
            "translations": [{"locale": loc, "label": f"orphan{loc}", "aliases": []} for loc in ("en", "es", "fr")],
        }
    )
    return seed
