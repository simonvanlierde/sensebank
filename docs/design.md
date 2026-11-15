# Design

## Scope

Concept entries: a stable local concept id, an English gloss, per-locale labels and accepted
answers, per-word provenance, review state and group membership. Groups carry rules.
Wikidata and Wiktionary supply candidates for a person to consider.

## Storage

A deck is a directory of plain-text YAML, so a change is a readable diff and the repository
is the history:

```text
deck.yaml          name, locales, sources (with licences), deck-wide rules, group order
concepts.yaml      every concept, in order
groups/<id>.yaml   one group: names, rules, shared-answer allowances, members
```

YAML over TOML because the Six Second Scribbles seed is YAML and TOML has no clean way to write
nested lists of tables with stable order. Order is data (the game deals prompts in file order), so
nothing is key-sorted: load then save is byte-stable, and `export-6ss` of an imported deck
reproduces the seed file byte for byte. One file per group because groups are what reviewers
read; concepts sit in one file because several groups share a concept (`zint` in `zoo` and
`kitchen`). Split `concepts.yaml` per concept if its diffs get noisy.

`.po` stays the interchange format for UI strings (see Veriglot); word lists are separate data.

## Schema

See `src/sensebank/model.py`.

- **Concept**: `id` (stable, `[a-z0-9_-]`), `gloss` (English), optional `wikidata {qid, review}`,
  `locales`. A missing Wikidata link never blocks an entry, and a link identifies the concept; it
  does not define accepted answers.
- **Localized** (one concept in one locale): `label`, `aliases` (the other accepted answers),
  `source` (a key of `deck.yaml` `sources`), `review` (`unreviewed`, `accepted`, `rejected`) and
  optional `overrides`, a map from a word as written to its own `source` or `review`.
  `Deck.provenance(concept, locale, word)` resolves one word to its source (name, licence,
  snapshot) and review state.
- **Group**: `id`, `kind`, per-locale `names`, ordered `members` (concept ids), `meta` (consumer
  data: 6ss difficulty and default locale; Scattergories keeps its difficulty and playability here
  or in its own repository), `rules` and `shared_answers`.
- **Rules**: `unique_answers` (no answer accepted by two members), `alias_distinct` (no alias equal
  to its label or another alias). `shared_answers` lists `{locale, answer, concepts}` for an
  answer that truly names several members; an allowance that no collision needs is reported.
  Deck-wide: `cjk_locales`, `junk_tokens`, `names`, `shared_words`.

A Scattergories category list is a group whose members are category concepts, each with a label
per locale; its letters, difficulty and playability stay in that game.

## Licences

Every word names a source; a source records its licence and snapshot. Wiktionary text (CC BY-SA)
therefore stays attributable per word, and an export for a CC0 or MIT consumer can filter on
`Source.licence`. Wikidata links and labels are CC0. Imported Six Second Scribbles words carry
`six-second-scribbles seed_data.yaml @ <commit>`, licence MIT. The upstream licence of its machine
translations is not recorded there; treat them as unreviewed.

## Checks

`sensebank check` is deterministic and offline. A finding has the shared shape `id, locale, key,
kind, severity, source, target, context, message, proposed, fingerprint`. `id` is
`<group>:<concept>:<locale>:<kind>:<normalised word>` (`-` for a concept in no group); the
fingerprint is a short hash of the entry's label and aliases when the finding was made, so a
later apply can detect stale text. Kinds: `answer_shared` (both sides reported; plural variants
match as the game scores them), `alias_equals_label`, `duplicate_alias`, `empty_label`,
`missing_locale`, `junk_text`, `ascii_in_cjk`, `untranslated_alias`, `stray_text`,
`unknown_member`, `orphan_concept`, and `stale_allowance` (a warning). Decision CSV columns match
Veriglot's: `id,locale,key,kind,severity,source,target,context,message,proposed,fingerprint,decision,edited,note`.
Only the findings export exists so far.

## One review implementation

The review module produces findings with stable entry identifiers, source and target
text, locale, context, an error kind and a proposed correction when available.
Model calls and domain checks belong inside that module. The CLI, CSV export and
web UI consume its results rather than implementing checks themselves.

A reviewer can accept, reject or edit a proposal. Applying those decisions checks
the current input against the reviewed snapshot, validates the resulting changes
and returns an explicit account of applied and rejected rows. Unknown identifiers,
stale text and invalid proposals must never disappear silently or overwrite newer edits.
CSV and the web UI use this same apply implementation.

Keep these contracts as design requirements until the first working review establishes
the concrete types. Add adapters where two actual implementations need the same
interface, rather than introducing a general plugin framework.

## Simple web review

Start with a local review list: filter by locale and error kind, inspect source,
translation and context, edit wording, accept or reject, then save the decisions.
Provide keyboard access, visible focus, labelled controls and an unsaved-changes warning.

The review UI needs no accounts, hosted database or collaborative workflow initially.
Choose its frontend and transport when implementing it; the Python review and apply
modules must be usable without a browser. CSV is an alternative interface, not the
web UI's internal data model.

## Relationship to the sibling project

Veriglot reviews app UI catalogs. Sensebank reviews concept-based word lists and
group rules. They remain separate packages and repositories. Both may use the same
local model endpoint and reviewer decision columns. Establish the CSV contract with
real examples from both before treating it as stable.

Build Veriglot's first working review before implementing Sensebank. Extract a shared
package only after both implementations demonstrate common behavior. Model choice,
license, language coverage and memory requirements must be checked before use.

## First working example

Storage, the Six Second Scribbles import/export and the deterministic group checks exist (above).
Next: port the 6ss `request`/`apply` prototype (`backend/scripts/translations.py` on branch
`archive/word-deck-review`). `request <locale>` writes one Markdown prompt per locale with every
group's concepts in English and the target language plus the deck rules. `apply <file.csv>` takes the
model's label and alias changes, skips unknown rows, saves the deck and re-runs the checks. Both map
onto this model: the prompt reads groups and concepts, and `apply` edits `Localized.label` and
`aliases` by `(group, concept, locale, field)` and gates on `check_deck` where 6ss ran its pytest file.
