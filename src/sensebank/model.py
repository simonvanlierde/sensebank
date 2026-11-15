"""Deck data model and its dict form (the YAML files hold exactly these dicts)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

Review = Literal["unreviewed", "accepted", "rejected"]
REVIEWS: tuple[str, ...] = get_args(Review)
QID = re.compile(r"Q[1-9]\d*")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")


class DeckError(ValueError):
    """A deck file is malformed."""


@dataclass
class Source:
    """Where words came from. Licence lives here so text under different licences stays separable."""

    id: str
    name: str
    licence: str
    snapshot: str = ""  # commit, dump date or retrieval date
    url: str = ""


@dataclass
class Override:
    """Per-word exception to its entry's source or review state."""

    source: str | None = None
    review: Review | None = None


@dataclass
class Wikidata:
    """Optional concept link. It identifies the concept; it never defines accepted answers."""

    qid: str
    review: Review = "unreviewed"


@dataclass
class Localized:
    """A concept in one locale: one label and the other accepted answers."""

    label: str
    aliases: list[str] = field(default_factory=list)
    source: str = ""
    review: Review = "unreviewed"
    overrides: dict[str, Override] = field(default_factory=dict)  # keyed by the word as written

    @property
    def words(self) -> list[str]:
        return [self.label, *self.aliases]


@dataclass
class Concept:
    """One stable local concept id with an English gloss."""

    id: str
    gloss: str
    locales: dict[str, Localized] = field(default_factory=dict)
    wikidata: Wikidata | None = None


@dataclass
class SharedAnswer:
    """An answer that several members of one group accept on purpose."""

    locale: str
    answer: str
    concepts: list[str]


@dataclass
class Group:
    """An ordered set of concepts that play together (a 6ss category, a Scattergories category list)."""

    id: str
    kind: str = "category"
    names: dict[str, str] = field(default_factory=dict)
    members: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # consumer data such as 6ss difficulty
    unique_answers: bool = True  # no answer accepted by two members
    alias_distinct: bool = True  # no alias equal to its label or another alias
    shared_answers: list[SharedAnswer] = field(default_factory=list)


@dataclass
class Rules:
    """Deck-wide check data."""

    cjk_locales: list[str] = field(default_factory=list)
    junk_tokens: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # proper names that read the same everywhere
    shared_words: dict[str, list[str]] = field(default_factory=dict)  # loanwords per locale


@dataclass
class Provenance:
    """Resolved provenance of one word."""

    source: Source
    review: Review


@dataclass
class Deck:
    """A whole deck: concepts, groups, sources and rules. Order is data and is kept."""

    name: str
    locales: list[str]
    sources: dict[str, Source] = field(default_factory=dict)
    concepts: list[Concept] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    rules: Rules = field(default_factory=Rules)

    def concept(self, concept_id: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == concept_id), None)

    def provenance(self, concept_id: str, locale: str, word: str) -> Provenance:
        """Source and review state of `word`, applying its per-word override."""
        concept = self.concept(concept_id)
        if concept is None or locale not in concept.locales:
            msg = f"no entry {concept_id}/{locale}"
            raise KeyError(msg)
        entry = concept.locales[locale]
        override = entry.overrides.get(word, Override())
        return Provenance(self.sources[override.source or entry.source], override.review or entry.review)


# --- dict form -------------------------------------------------------------------------------


def _review(value: Any, where: str) -> Review:  # noqa: ANN401
    if value not in REVIEWS:
        msg = f"{where}: review must be one of {', '.join(REVIEWS)}, got {value!r}"
        raise DeckError(msg)
    return value


def _need(data: Any, key: str, where: str) -> Any:  # noqa: ANN401
    if not isinstance(data, dict) or key not in data:
        msg = f"{where}: missing '{key}'"
        raise DeckError(msg)
    return data[key]


def _strings(value: Any, where: str) -> list[str]:  # noqa: ANN401
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        msg = f"{where}: expected a list of strings"
        raise DeckError(msg)
    return list(value)


def source_from_dict(source_id: str, d: dict[str, Any]) -> Source:
    return Source(
        source_id, str(_need(d, "name", f"source {source_id}")), str(_need(d, "licence", f"source {source_id}")),
        str(d.get("snapshot", "")), str(d.get("url", "")),
    )  # fmt: skip


def source_to_dict(s: Source) -> dict[str, Any]:
    d: dict[str, Any] = {"name": s.name, "licence": s.licence}
    if s.snapshot:
        d["snapshot"] = s.snapshot
    if s.url:
        d["url"] = s.url
    return d


def concept_from_dict(d: dict[str, Any]) -> Concept:
    cid = str(_need(d, "id", "concept"))
    where = f"concept {cid}"
    wd = d.get("wikidata")
    wikidata = None
    if wd is not None:
        qid = str(_need(wd, "qid", f"{where} wikidata"))
        if not QID.fullmatch(qid):
            msg = f"{where}: wikidata qid {qid!r} is not Q<number>"
            raise DeckError(msg)
        wikidata = Wikidata(qid, _review(wd.get("review", "unreviewed"), f"{where} wikidata"))
    locales: dict[str, Localized] = {}
    for locale, e in (_need(d, "locales", where) or {}).items():
        w = f"{where}/{locale}"
        overrides = {
            word: Override(o.get("source"), _review(o["review"], w) if o.get("review") else None)
            for word, o in (e.get("overrides") or {}).items()
        }
        locales[locale] = Localized(
            label=str(_need(e, "label", w)),
            aliases=_strings(e.get("aliases"), w),
            source=str(_need(e, "source", w)),
            review=_review(e.get("review", "unreviewed"), w),
            overrides=overrides,
        )
    return Concept(cid, str(_need(d, "gloss", where)), locales, wikidata)


def concept_to_dict(c: Concept) -> dict[str, Any]:
    d: dict[str, Any] = {"id": c.id, "gloss": c.gloss}
    if c.wikidata:
        d["wikidata"] = {"qid": c.wikidata.qid, "review": c.wikidata.review}
    locales: dict[str, Any] = {}
    for locale, e in c.locales.items():
        item: dict[str, Any] = {"label": e.label, "aliases": list(e.aliases), "source": e.source, "review": e.review}
        if e.overrides:
            item["overrides"] = {
                w: {k: v for k, v in (("source", o.source), ("review", o.review)) if v} for w, o in e.overrides.items()
            }
        locales[locale] = item
    d["locales"] = locales
    return d


def group_from_dict(d: dict[str, Any]) -> Group:
    gid = str(_need(d, "id", "group"))
    if not SLUG.fullmatch(gid):
        msg = f"group id {gid!r} must match {SLUG.pattern}"
        raise DeckError(msg)
    rules = d.get("rules") or {}
    return Group(
        id=gid,
        kind=str(d.get("kind", "category")),
        names=dict(d.get("names") or {}),
        members=_strings(d.get("members"), f"group {gid}"),
        meta=dict(d.get("meta") or {}),
        unique_answers=bool(rules.get("unique_answers", True)),
        alias_distinct=bool(rules.get("alias_distinct", True)),
        shared_answers=[
            SharedAnswer(s["locale"], s["answer"], _strings(s["concepts"], f"group {gid}"))
            for s in d.get("shared_answers") or []
        ],
    )


def group_to_dict(g: Group) -> dict[str, Any]:
    d: dict[str, Any] = {"id": g.id, "kind": g.kind, "names": dict(g.names)}
    if g.meta:
        d["meta"] = dict(g.meta)
    d["rules"] = {"unique_answers": g.unique_answers, "alias_distinct": g.alias_distinct}
    if g.shared_answers:
        d["shared_answers"] = [
            {"locale": s.locale, "answer": s.answer, "concepts": list(s.concepts)} for s in g.shared_answers
        ]
    d["members"] = list(g.members)
    return d
