"""`request`: one Markdown review prompt per locale. No model is called; a person or a later local step answers it."""

from __future__ import annotations

import hashlib
from importlib import resources
from string import Template
from typing import TYPE_CHECKING

from sensebank.review import NONE, SEPARATOR, UsageError, entry_id

if TYPE_CHECKING:
    from sensebank.model import Deck, Group, Localized

TEMPLATE = "review-request.md"
LANGUAGES = {
    "de": "German", "en": "English", "es": "Spanish", "fr": "French", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
}  # fmt: skip


def _template() -> tuple[str, str]:
    raw = (resources.files("sensebank") / "prompts" / TEMPLATE).read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()[:12]


def _oneline(text: str) -> str:
    """Deck text as one safe line: no line breaks, table pipes, code fences or comment end."""
    return " ".join(text.split()).replace("|", "\\|").replace("```", "` ` `").replace("-->", "-- >")


def _cell(entry: Localized | None) -> str:
    if entry is None:
        return "(missing)"
    return _oneline(entry.label + (f" (also: {SEPARATOR.join(entry.aliases)})" if entry.aliases else ""))


def pick_groups(deck: Deck, groups: list[str]) -> list[Group]:
    """The deck's groups named in `groups` (all when empty); an unknown id is a usage error."""
    if unknown := [g for g in groups if g not in {x.id for x in deck.groups}]:
        msg = f"unknown group(s) {', '.join(unknown)} ({', '.join(g.id for g in deck.groups)})"
        raise UsageError(msg)
    return [g for g in deck.groups if not groups or g.id in groups]


def request(deck: Deck, locale: str, groups: list[str]) -> str:
    """The prompt for `locale`, limited to `groups` (all when empty). The header names the template hash."""
    if locale not in deck.locales:
        msg = f"locale {locale!r} is not in this deck ({', '.join(deck.locales)})"
        raise UsageError(msg)
    picked = pick_groups(deck, groups)
    language = LANGUAGES.get(locale, locale)
    template, digest = _template()
    concepts = sum(len(g.members) for g in picked)
    first = next((m for g in picked for m in g.members if deck.concept(m)), "concept")
    body = Template(template).substitute(
        deck=_oneline(deck.name), language=_oneline(language), none=NONE, groups=len(picked), concepts=concepts,
        example_id=entry_id(picked[0].id if picked else "group", first, locale),
    )  # fmt: skip
    header = (
        f"<!-- sensebank request; template {TEMPLATE} sha256:{digest}; deck {_oneline(deck.name)}; "
        f"locale {_oneline(locale)}; "
        f"groups {','.join(g.id for g in picked)} -->"
    )
    out = [
        header,
        "",
        body,
    ]
    for group in picked:
        rules = (
            f"Rules: unique answers {'on' if group.unique_answers else 'off'}, "
            f"distinct aliases {'on' if group.alias_distinct else 'off'}."
        )
        local_name = group.names.get(locale, "(missing)")
        out += [
            f"## {_oneline(group.id)}: {_oneline(group.names.get('en', group.id))} / {_oneline(local_name)}",
            "",
            rules,
        ]
        allowed = [s for s in group.shared_answers if s.locale in {"en", locale}]
        if allowed:
            out += [
                "Allowed shared answers:",
                *(f'- {s.locale} "{_oneline(s.answer)}": {_oneline(", ".join(s.concepts))}' for s in allowed),
            ]
        out += ["", f"| id | English | {_oneline(language)} |", "| --- | --- | --- |"]
        for member in group.members:
            concept = deck.concept(member)
            if concept is None:
                continue
            english, target = concept.locales.get("en"), concept.locales.get(locale)
            ident = _oneline(entry_id(group.id, concept.id, locale)) if target else "(no entry)"
            english_cell = _cell(english) if english else _oneline(concept.gloss)
            out.append(f"| {ident} | {english_cell} | {_cell(target)} |")
        out.append("")
    return "\n".join(out)
