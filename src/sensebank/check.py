"""Deterministic checks. Findings only: nothing here edits a deck."""

from __future__ import annotations

import hashlib
import json
import re
import string
from typing import TYPE_CHECKING

from sensebank.findings import Finding
from sensebank.match import normalize, same_answer

if TYPE_CHECKING:
    from sensebank.model import Concept, Deck, Group, Localized

# Characters a player could not type as part of an answer.
STRAY = set(string.punctuation) - set("-'.&")


def _fp(*parts: object) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode(), usedforsecurity=False).hexdigest()[
        :8
    ]  # a label, not security


class _Checker:
    """Collects findings, keeping the first of any id so output order is stable."""

    def __init__(self, deck: Deck) -> None:
        self.deck = deck
        self.found: dict[str, Finding] = {}
        self.by_id = {c.id: c for c in deck.concepts}
        self.owners: dict[str, Group] = {}
        for group in deck.groups:
            for member in group.members:
                self.owners.setdefault(member, group)

    def add(  # noqa: PLR0913
        self, prefix: str, concept_id: str, locale: str, kind: str, key: str, word: str, *,
        message: str, context: str = "", proposed: str = "", severity: str = "error", extra: object = "",
    ) -> None:  # fmt: skip
        concept = self.by_id.get(concept_id)
        entry = concept.locales.get(locale) if concept else None
        english = concept.locales.get("en") if concept else None
        finding = Finding(
            id=f"{prefix}:{concept_id}:{locale}:{kind}:{normalize(word)}",
            locale=locale,
            key=key,
            kind=kind,
            severity=severity,
            source=(english.label if english else concept.gloss) if concept else "",
            target=word,
            context=context or f"group {prefix}",
            message=message,
            proposed=proposed,
            fingerprint=_fp(concept_id, locale, (entry.label, entry.aliases) if entry else (), extra),
        )
        self.found.setdefault(finding.id, finding)

    def concept(self, concept: Concept) -> None:
        owner = self.owners.get(concept.id)
        prefix = owner.id if owner else "-"
        if owner is None:
            self.add(
                prefix, concept.id, "", "orphan_concept", "concept", concept.id, message="in no group, so never used"
            )
        for locale in self.deck.locales:
            if locale not in concept.locales:
                self.add(prefix, concept.id, locale, "missing_locale", "locale", "", message=f"no {locale} entry")
        english = concept.locales.get("en")
        english_words = {normalize(w) for w in english.words} if english else set()
        for locale, entry in concept.locales.items():
            if not entry.label.strip():
                self.add(prefix, concept.id, locale, "empty_label", "label", entry.label, message="label is empty")
                continue
            distinct = owner.alias_distinct if owner else True
            self.entry(prefix, concept.id, locale, entry, english_words, distinct=distinct)

    def entry(self, prefix: str, cid: str, locale: str, entry: Localized, english: set[str], *, distinct: bool) -> None:
        rules = self.deck.rules
        shared = {normalize(w) for w in [*rules.shared_words.get(locale, []), *rules.names]}
        seen = {normalize(entry.label)}
        for key, word in [("label", entry.label), *[("alias", a) for a in entry.aliases]]:
            norm = normalize(word)
            if not word.strip() or all(not ch.isalnum() for ch in word) or any(t in word for t in rules.junk_tokens):
                self.add(
                    prefix, cid, locale, "junk_text", key, word, message="blank, punctuation only or page-chrome text"
                )
            if locale in rules.cjk_locales and word.isascii() and not word.isdigit():
                self.add(
                    prefix, cid, locale, "ascii_in_cjk", key, word, message=f"{locale} text should use its own script"
                )
            if word != word.strip() or "  " in word or set(word) & STRAY:
                fixed = re.sub(r" {2,}", " ", word.strip())
                self.add(
                    prefix, cid, locale, "stray_text", key, word, message="stray whitespace or symbol", proposed=fixed
                )
            if key != "alias":
                continue
            if locale != "en" and norm in english and norm not in shared:
                self.add(
                    prefix, cid, locale, "untranslated_alias", key, word, message="same as the English label or alias"
                )
            if distinct and norm in seen:
                kind = "alias_equals_label" if norm == normalize(entry.label) else "duplicate_alias"
                self.add(prefix, cid, locale, kind, key, word, message="alias repeats the label or an earlier alias")
            seen.add(norm)

    def group(self, group: Group) -> None:
        members = []
        for member in group.members:
            if member in self.by_id:
                members.append(self.by_id[member])
            else:
                self.add(group.id, member, "", "unknown_member", "member", member, message="not a concept in this deck")
        used: set[int] = set()
        if group.unique_answers:
            for locale in self.deck.locales:
                self.collisions(group, members, locale, used)
        for i, s in enumerate(group.shared_answers):
            if i not in used:
                first = s.concepts[0] if s.concepts else "-"
                self.add(group.id, first, s.locale, "stale_allowance", "answer", s.answer,
                         severity="warning", message="no collision needs this allowance any more")  # fmt: skip

    def collisions(self, group: Group, members: list[Concept], locale: str, used: set[int]) -> None:
        for a in members:
            if locale not in a.locales:
                continue
            for word in a.locales[locale].words:
                clashes = [
                    f"{b.id} ({other})"
                    for b in members
                    if b is not a and locale in b.locales
                    for other in b.locales[locale].words
                    if same_answer(word, other, locale) and not self.allowed(group, locale, (a, word), (b, other), used)
                ]
                if clashes:
                    key = "label" if word == a.locales[locale].label else "alias"
                    self.add(group.id, a.id, locale, "answer_shared", key, word, extra=sorted(clashes),
                             context=f"group {group.id}; also accepted by: {', '.join(clashes)}",
                             message="two entries in one group accept this answer")  # fmt: skip

    @staticmethod
    def allowed(group: Group, locale: str, a: tuple[Concept, str], b: tuple[Concept, str], used: set[int]) -> bool:
        hits = [
            i for i, s in enumerate(group.shared_answers)
            if s.locale == locale and {a[0].id, b[0].id} <= set(s.concepts)
            and same_answer(s.answer, a[1], locale) and same_answer(s.answer, b[1], locale)
        ]  # fmt: skip
        used.update(hits)
        return bool(hits)


def check_deck(deck: Deck) -> list[Finding]:
    """Run every check; findings come in a stable order (concepts first, then groups)."""
    checker = _Checker(deck)
    for concept in deck.concepts:
        checker.concept(concept)
    for group in deck.groups:
        checker.group(group)
    return list(checker.found.values())
