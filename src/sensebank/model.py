"""Deck data model and its dict form (the YAML files hold exactly these dicts)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, get_args

Review = Literal["unreviewed", "accepted", "rejected"]
REVIEWS: tuple[str, ...] = get_args(Review)
QID = re.compile(r"Q[1-9]\d*")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")  # concept and group ids; also safe as a file name
LOCALE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]+)*")
# Characters YAML reads as line breaks (NEL, LS, PS) or that no word holds (C1 controls): saved raw,
# NEL comes back as a space, so the text would change on a round trip.
BAD_CHARS = re.compile("[\x80-\x9f\u2028\u2029]")


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
# YAML reads unquoted `yes`, `0123` or an empty value as bool, int or None. Every text field must
# already be a string: coercing with str() would turn `label: yes` into "True".


def _review(value: Any, where: str) -> Review:  # noqa: ANN401
    if value not in REVIEWS:
        msg = f"{where}: review must be one of {', '.join(REVIEWS)}, got {value!r}"
        raise DeckError(msg)
    return value


def _map(value: Any, where: str) -> dict[Any, Any]:  # noqa: ANN401
    if not isinstance(value, dict):
        msg = f"{where} must be a mapping, got {type(value).__name__}"
        raise DeckError(msg)
    return value


def _text(value: Any, where: str) -> str:  # noqa: ANN401
    if not isinstance(value, str):
        msg = f"{where} must be a string, got {value!r}"
        raise DeckError(msg)
    if bad := BAD_CHARS.search(value):
        msg = f"{where} holds U+{ord(bad.group()):04X}, a line break or control character: {value!r}"
        raise DeckError(msg)
    return value


def _str(d: dict[str, Any], key: str, where: str, default: str | None = None) -> str:
    """`d[key]` as a string; required unless a default is given."""
    if key not in d and default is not None:
        return default
    if key not in d:
        msg = f"{where}: missing '{key}'"
        raise DeckError(msg)
    return _text(d[key], f"{where}: {key}")


def _strings(value: Any, where: str) -> list[str]:  # noqa: ANN401
    if value is None:
        return []
    if not isinstance(value, list):
        msg = f"{where} must be a list of strings"
        raise DeckError(msg)
    return [_text(v, where) for v in value]


def _ids(value: Any, where: str, pattern: re.Pattern[str] = SLUG) -> list[str]:  # noqa: ANN401
    ids = _strings(value, where)
    for i in ids:
        if not pattern.fullmatch(i):
            msg = f"{where}: {i!r} must match {pattern.pattern}"
            raise DeckError(msg)
    return ids


def _flag(rules: dict[str, Any], key: str, where: str) -> bool:
    value = rules.get(key, True)
    if not isinstance(value, bool):
        msg = f"{where}: rules/{key} must be true or false, got {value!r}"
        raise DeckError(msg)
    return value


def source_from_dict(source_id: str, d: Any) -> Source:  # noqa: ANN401
    where = f"source {source_id}"
    d = _map(d, where)
    return Source(
        _text(source_id, "source id"), _str(d, "name", where), _str(d, "licence", where),
        _str(d, "snapshot", where, ""), _str(d, "url", where, ""),
    )  # fmt: skip


def source_to_dict(s: Source) -> dict[str, Any]:
    d: dict[str, Any] = {"name": s.name, "licence": s.licence}
    if s.snapshot:
        d["snapshot"] = s.snapshot
    if s.url:
        d["url"] = s.url
    return d


def _override(o: Any, where: str) -> Override:  # noqa: ANN401
    o = _map(o, where)
    source = _str(o, "source", where) if o.get("source") is not None else None
    return Override(source, _review(o["review"], where) if o.get("review") else None)


def _localized(e: Any, where: str) -> Localized:  # noqa: ANN401
    if not isinstance(e, dict):
        msg = f"{where}: expected a mapping, got {type(e).__name__}"
        raise DeckError(msg)
    overrides = _map(e.get("overrides") or {}, f"{where}: overrides")
    return Localized(
        label=_str(e, "label", where),
        aliases=_strings(e.get("aliases"), f"{where}: aliases"),
        source=_str(e, "source", where),
        review=_review(e.get("review", "unreviewed"), where),
        overrides={
            _text(w, f"{where}: override"): _override(o, f"{where}: override {w!r}") for w, o in overrides.items()
        },
    )


def concept_from_dict(d: Any) -> Concept:  # noqa: ANN401
    if not isinstance(d, dict):
        msg = f"concept: expected a mapping, got {type(d).__name__}"
        raise DeckError(msg)
    cid = _str(d, "id", "concept")
    if not SLUG.fullmatch(cid):
        msg = f"concept id {cid!r} must match {SLUG.pattern}"
        raise DeckError(msg)
    where = f"concept {cid}"
    wd = d.get("wikidata")
    wikidata = None
    if wd is not None:
        qid = _str(_map(wd, f"{where} wikidata"), "qid", f"{where} wikidata")
        if not QID.fullmatch(qid):
            msg = f"{where}: wikidata qid {qid!r} is not Q<number>"
            raise DeckError(msg)
        wikidata = Wikidata(qid, _review(wd.get("review", "unreviewed"), f"{where} wikidata"))
    if "locales" not in d:
        msg = f"{where}: missing 'locales'"
        raise DeckError(msg)
    raw = _map(d["locales"] or {}, f"{where}: locales")
    locales = {_text(loc, f"{where}: locale"): _localized(e, f"{where}/{loc}") for loc, e in raw.items()}
    return Concept(cid, _str(d, "gloss", where), locales, wikidata)


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


GROUP_RULES = ("unique_answers", "alias_distinct")


def _shared_answer(s: Any, where: str) -> SharedAnswer:  # noqa: ANN401
    if not isinstance(s, dict):
        msg = f"{where} entries must be mappings, got {s!r}"
        raise DeckError(msg)
    return SharedAnswer(
        _str(s, "locale", where), _str(s, "answer", where), _ids(s.get("concepts"), f"{where}: concepts")
    )


def group_from_dict(d: Any) -> Group:  # noqa: ANN401
    gid = _str(_map(d, "group"), "id", "group")
    check_group_ids([gid])
    where = f"group {gid}"
    rules = _map(d.get("rules") or {}, f"{where}: rules")
    for key in rules:
        if key not in GROUP_RULES:
            msg = f"{where}: unknown rules key {key!r} (known: {', '.join(GROUP_RULES)})"
            raise DeckError(msg)
    names = _map(d.get("names") or {}, f"{where}: names")
    shared = d.get("shared_answers") or []
    if not isinstance(shared, list):
        msg = f"{where}: shared_answers must be a list"
        raise DeckError(msg)
    return Group(
        id=gid,
        kind=_str(d, "kind", where, "category"),
        names={_text(loc, f"{where}: locale"): _text(n, f"{where}: names/{loc}") for loc, n in names.items()},
        members=_ids(d.get("members"), f"{where}: members"),
        meta=dict(_map(d.get("meta") or {}, f"{where}: meta")),
        unique_answers=_flag(rules, "unique_answers", where),
        alias_distinct=_flag(rules, "alias_distinct", where),
        shared_answers=[_shared_answer(s, f"{where}: shared_answers") for s in shared],
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


def rules_from_dict(d: Any) -> Rules:  # noqa: ANN401
    d = _map(d or {}, "deck rules")
    for key in d:
        if key not in Rules.__dataclass_fields__:
            msg = f"deck rules: unknown key {key!r} (known: {', '.join(Rules.__dataclass_fields__)})"
            raise DeckError(msg)
    shared = _map(d.get("shared_words") or {}, "deck rules: shared_words")
    return Rules(
        cjk_locales=_strings(d.get("cjk_locales"), "deck rules: cjk_locales"),
        junk_tokens=_strings(d.get("junk_tokens"), "deck rules: junk_tokens"),
        names=_strings(d.get("names"), "deck rules: names"),
        shared_words={
            _text(loc, "deck rules: shared_words locale"): _strings(words, f"deck rules: shared_words/{loc}")
            for loc, words in shared.items()
        },
    )


def rules_to_dict(r: Rules) -> dict[str, Any]:
    return {k: v for k, v in asdict(r).items() if v}


def check_group_ids(ids: list[str]) -> None:
    """Group ids name files under groups/, so each must be a slug (no `/` or `..`) and unique."""
    seen: set[str] = set()
    for gid in ids:
        if not isinstance(gid, str) or not SLUG.fullmatch(gid):
            msg = f"group id {gid!r} must match {SLUG.pattern}"
            raise DeckError(msg)
        if gid in seen:
            msg = f"group id {gid!r} is listed twice"
            raise DeckError(msg)
        seen.add(gid)


def _check_locales(locales: list[str]) -> set[str]:
    seen: set[str] = set()
    for locale in locales:
        if not LOCALE.fullmatch(_text(locale, "deck locale")):
            msg = f"deck locale {locale!r} must match {LOCALE.pattern}"
            raise DeckError(msg)
        if locale in seen:
            msg = f"deck locale {locale!r} is listed twice"
            raise DeckError(msg)
        seen.add(locale)
    return seen


def _check_concepts(deck: Deck, locales: set[str]) -> None:
    concept_ids: set[str] = set()
    for concept in deck.concepts:
        concept_from_dict(concept_to_dict(concept))
        if concept.id in concept_ids:
            msg = f"duplicate concept id {concept.id!r}"
            raise DeckError(msg)
        concept_ids.add(concept.id)
        for locale, entry in concept.locales.items():
            if locale not in locales:
                msg = f"concept {concept.id}: locale {locale!r} is not in the deck's locales"
                raise DeckError(msg)
            used = {entry.source, *(o.source for o in entry.overrides.values() if o.source)}
            for source_id in sorted(used - deck.sources.keys()):
                msg = f"concept {concept.id}/{locale}: unknown source {source_id!r}"
                raise DeckError(msg)


def _check_groups(groups: list[Group], locales: set[str]) -> None:
    check_group_ids([g.id for g in groups])
    for group in groups:
        group_from_dict(group_to_dict(group))
        for locale in [*group.names, *(s.locale for s in group.shared_answers)]:
            if locale not in locales:
                msg = f"group {group.id}: locale {locale!r} is not in the deck's locales"
                raise DeckError(msg)
        members: set[str] = set()
        for member in group.members:
            if member in members:
                msg = f"group {group.id}: member {member!r} is listed twice"
                raise DeckError(msg)
            members.add(member)


def validate_deck(deck: Deck) -> None:
    """Raise DeckError for anything `load_deck` would refuse, so no writer can save it.

    Each part goes through its dict form and back, which applies every field check.
    """
    locales = _check_locales(deck.locales)
    for source in deck.sources.values():
        source_from_dict(source.id, source_to_dict(source))
    rules_from_dict(rules_to_dict(deck.rules))
    _check_concepts(deck, locales)
    _check_groups(deck.groups, locales)
