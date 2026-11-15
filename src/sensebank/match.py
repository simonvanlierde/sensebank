"""Answer matching, ported from the Six Second Scribbles scorer so group checks agree with the game."""

from __future__ import annotations

import functools
import unicodedata

# Languages whose regular plural adds -s or -es; others form plurals differently, so a blind -s
# would join two unrelated words.
S_PLURAL_LANGUAGES = frozenset({"en", "es", "fr", "pt"})


def normalize(text: str) -> str:
    """Casefold, drop combining marks and strip, so `café` equals `cafe`."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", without_marks).strip()


@functools.lru_cache(maxsize=4096)
def _variants(normalized: str, language: str) -> frozenset[str]:
    variants = {normalized}
    if language in S_PLURAL_LANGUAGES:
        if normalized.endswith("s"):
            variants.add(normalized[:-1])
            if normalized.endswith("es"):
                variants.add(normalized[:-2])
        else:
            variants.update((f"{normalized}s", f"{normalized}es"))
    if language == "en" and normalized.endswith("ing"):
        variants.add(normalized[:-3])
    variants.discard("")  # a word that is all suffix would leave "", which every such word shares
    return frozenset(variants)


def same_answer(a: str, b: str, locale: str) -> bool:
    """Whether the game scores `a` and `b` as the same answer in `locale`."""
    language = locale.split("-", maxsplit=1)[0].lower()
    return bool(_variants(normalize(a), language) & _variants(normalize(b), language))
