"""Answer matching agrees with the Six Second Scribbles scorer."""
# spell-checker: ignore dakuten handakuten

from __future__ import annotations

import unicodedata
from typing import Literal

import pytest

from sensebank.match import normalize, same_answer


@pytest.mark.parametrize(
    ("guess", "target"), [("ガラス", "カラス"), ("ばす", "はす"), ("ぱん", "はん"), ("ぱん", "ばん")]
)
@pytest.mark.parametrize("form", ["NFC", "NFD"])
def test_japanese_voicing_changes_the_answer(guess: str, target: str, form: Literal["NFC", "NFD"]) -> None:
    """Dakuten and handakuten are part of the letter, so voiced and unvoiced kana differ."""
    guess, target = unicodedata.normalize(form, guess), unicodedata.normalize(form, target)
    assert not same_answer(guess, target, "ja")
    assert not same_answer(target, guess, "ja")


@pytest.mark.parametrize(("answer", "locale"), [("ガラス", "ja"), ("ばす", "ja"), ("ぱん", "ja"), ("café", "fr")])
def test_canonical_forms_are_the_same_answer(answer: str, locale: str) -> None:
    """NFC and NFD spell one answer, and every other combining mark stays optional."""
    assert same_answer(unicodedata.normalize("NFD", answer), unicodedata.normalize("NFC", answer), locale)
    assert normalize(unicodedata.normalize("NFD", answer)) == normalize(answer)
    assert same_answer("cafe", "Café", "fr")
    assert same_answer("cafés", "cafe", "fr-FR")
