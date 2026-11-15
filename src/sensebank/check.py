"""Deterministic checks. Findings only: nothing here edits a deck."""

from __future__ import annotations

import hashlib
import json
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


def _h(word: str, occurrence: int = 1) -> str:
    """First 8 hex of sha256 of the raw word: distinct words never share an id, and no id holds `:` or a newline.

    The same word written twice in one place (`zinger, zinger`) gives two findings that differ only by
    position; the n-th one hashes `word NUL n` instead.
    """
    raw = word if occurrence == 1 else f"{word}\x00{occurrence}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class _Checker:
    """Collects findings in a stable order. No finding is ever merged into another: ids are unique."""

    def __init__(self, deck: Deck) -> None:
        self.deck = deck
        self.found: dict[str, Finding] = {}
        self.by_id = {c.id: c for c in deck.concepts}
        self.owners: dict[str, list[Group]] = {}
        for group in deck.groups:
            for member in group.members:
                self.owners.setdefault(member, []).append(group)

    def add(  # noqa: PLR0913
        self, group: str | None, concept_id: str, locale: str, kind: str, key: str, word: str, *,
        message: str, context: str, proposed: str = "", severity: str = "error", extra: object = "",
    ) -> None:  # fmt: skip
        """Record a finding. `group` is set only for group-level kinds, and is then the id's first part."""
        concept = self.by_id.get(concept_id)
        entry = concept.locales.get(locale) if concept else None
        english = concept.locales.get("en") if concept else None
        parts = [concept_id or "-", locale or "-", key, kind]
        prefix = ":".join(parts if group is None else [group, *parts])
        n = 1
        while f"{prefix}:{_h(word, n)}" in self.found:
            n += 1
        finding = Finding(
            id=f"{prefix}:{_h(word, n)}",
            locale=locale,
            key=key,
            kind=kind,
            severity=severity,
            source=(english.label if english else concept.gloss) if concept else "",
            target=word,
            context=context,
            message=message,
            proposed=proposed,
            fingerprint=_fp(concept_id, locale, (entry.label, entry.aliases) if entry else (), extra),
        )
        self.found[finding.id] = finding

    def concept(self, concept: Concept) -> None:
        owners = self.owners.get(concept.id, [])
        context = f"groups: {', '.join(g.id for g in owners)}" if owners else "in no group"
        if not owners:
            self.add(None, concept.id, "", "orphan_concept", "concept", concept.id, context=context,
                     message="in no group, so never used")  # fmt: skip
        for locale in self.deck.locales:
            if locale not in concept.locales:
                self.add(None, concept.id, locale, "missing_locale", "locale", "", context=context,
                         message=f"no {locale} entry")  # fmt: skip
        english = concept.locales.get("en")
        english_words = {normalize(w) for w in english.words} if english else set()
        # A concept in several groups keeps one set of aliases, so the strictest group decides.
        distinct = any(g.alias_distinct for g in owners) if owners else True
        for locale, entry in concept.locales.items():
            if not entry.label.strip():
                self.add(None, concept.id, locale, "empty_label", "label", entry.label, context=context,
                         message="label is empty")  # fmt: skip
                continue
            self.entry(concept.id, locale, entry, english_words, context=context, distinct=distinct)

    def text(self, group: str | None, cid: str, locale: str, key: str, word: str, context: str) -> None:
        """Checks that apply to any text a player sees: labels, aliases and group names."""
        rules = self.deck.rules
        if not word.strip() or all(not ch.isalnum() for ch in word) or any(t in word for t in rules.junk_tokens):
            self.add(group, cid, locale, "junk_text", key, word, context=context,
                     message="blank, punctuation only or page-chrome text")  # fmt: skip
        if locale in rules.cjk_locales and word.isascii() and not word.isdigit():
            self.add(group, cid, locale, "ascii_in_cjk", key, word, context=context,
                     message=f"{locale} text should use its own script")  # fmt: skip
        if word != word.strip() or "  " in word or set(word) & STRAY:
            fixed = " ".join("".join(" " if ch in STRAY else ch for ch in word).split())
            self.add(group, cid, locale, "stray_text", key, word, context=context, message="stray whitespace or symbol",
                     proposed=fixed if fixed != word else "")  # fmt: skip

    def entry(self, cid: str, locale: str, entry: Localized, english: set[str], *, context: str,
              distinct: bool) -> None:  # fmt: skip
        rules = self.deck.rules
        shared = {normalize(w) for w in [*rules.shared_words.get(locale, []), *rules.names]}
        seen = {normalize(entry.label)}
        for i, word in enumerate(entry.words):
            key = "label" if i == 0 else "alias"
            self.text(None, cid, locale, key, word, context)
            if key != "alias":
                continue
            norm = normalize(word)
            if locale != "en" and norm in english and norm not in shared:
                self.add(None, cid, locale, "untranslated_alias", key, word, context=context,
                         message="same as the English label or alias")  # fmt: skip
            if distinct and norm in seen:
                kind = "alias_equals_label" if norm == normalize(entry.label) else "duplicate_alias"
                self.add(None, cid, locale, kind, key, word, context=context,
                         message="alias repeats the label or an earlier alias")  # fmt: skip
            seen.add(norm)

    def group(self, group: Group) -> None:
        context = f"group {group.id}"
        for locale, name in group.names.items():
            self.text(group.id, "", locale, "name", name, context)
        members = []
        for member in group.members:
            if member in self.by_id:
                members.append(self.by_id[member])
            else:
                self.add(group.id, member, "", "unknown_member", "member", member, context=context,
                         message="not a concept in this deck")  # fmt: skip
        used: set[int] = set()
        if group.unique_answers:
            for locale in self.deck.locales:
                self.collisions(group, members, locale, used)
        for i, s in enumerate(group.shared_answers):
            if i not in used:
                first = s.concepts[0] if s.concepts else ""
                self.add(group.id, first, s.locale, "stale_allowance", "answer", s.answer, context=context,
                         severity="warning",
                         message="no collision needs this allowance any more")  # fmt: skip

    def collisions(self, group: Group, members: list[Concept], locale: str, used: set[int]) -> None:
        for a in members:
            if locale not in a.locales:
                continue
            for i, word in enumerate(a.locales[locale].words):
                clashes = [
                    f"{b.id} ({other})"
                    for b in members
                    if b is not a and locale in b.locales
                    for other in b.locales[locale].words
                    if same_answer(word, other, locale) and not self.allowed(group, locale, (a, word), (b, other), used)
                ]
                if clashes:
                    key = "label" if i == 0 else "alias"
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
