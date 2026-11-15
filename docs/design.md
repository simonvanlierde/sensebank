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

### Validation

`load_deck`, `save_deck` and `import-6ss` refuse a malformed deck with an error (exit 3) rather than
a finding. Text fields (ids, gloss, labels, aliases, sources, group names, source fields, rule lists)
must already be strings: YAML reads an unquoted `yes`, `0123` or empty value as a bool, int or null,
and these are refused, not converted. Group rule flags must be `true` or `false`. Unknown rule keys
are refused. Concept, group and member ids match `[a-z0-9][a-z0-9_-]*` (a group id is also a file
name, so `../x` is refused before any path is built); locales match `[A-Za-z]{2,3}(-[A-Za-z0-9]+)*`,
and every concept, group-name and shared-answer locale is one of `deck.yaml`'s `locales`. Group ids
and members are unique, and `groups/<id>.yaml` holds `id: <id>`. Text holding U+0085, U+2028,
U+2029 or another C1 control is refused, because YAML would read the saved text back changed.
An imported deck lists every locale any prompt has, in first-seen order.

`save_deck` validates first, writes each file to a temporary name and renames it into place with LF
line ends, and deletes a stale group file only after the new ones exist.

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
kind, severity, source, target, context, message, proposed, fingerprint`. `key` names the part:
`label`, `alias`, `name` (a group name), `locale`, `member`, `concept` or `answer`.

Finding ids:

- Concept-level kinds: `<concept>:<locale>:<key>:<kind>:<h>`. These do not depend on which groups
  hold the concept, so reordering groups keeps every id.
- Group-level kinds (`answer_shared`, `unknown_member`, `stale_allowance`, and the text checks on a
  group name): `<group>:<concept>:<locale>:<key>:<kind>:<h>`.
- `-` stands for a part that does not apply (no locale, or no concept for a group name).
- `<h>` is the first 8 hex digits of the SHA-256 of the raw word, not the normalised one, so `cat`
  and `Cat` get different ids and no id holds `:` or a newline. When the same word repeats in one
  place (`zinger, zinger, zinger`), the n-th finding with an otherwise equal id hashes the word plus
  `n`. No finding is ever merged into another.

The fingerprint is a short hash of the entry's label and aliases when the finding was made, so a
later apply can detect stale text. Kinds: `answer_shared` (both sides reported; plural variants
match as the game scores them), `alias_equals_label`, `duplicate_alias`, `empty_label`,
`missing_locale`, `junk_text`, `ascii_in_cjk`, `untranslated_alias`, `stray_text`,
`unknown_member`, `orphan_concept`, and `stale_allowance` (a warning). `junk_text`, `ascii_in_cjk`
and `stray_text` also run over group names. A concept in several groups gets the alias checks when
any of its groups sets `alias_distinct`. A `stray_text` proposal drops the stray symbols and extra
spaces; `proposed` is left empty when the fix would not change the text.

Decision CSV columns match Veriglot's:
`id,locale,key,kind,severity,source,target,context,message,proposed,fingerprint,decision,edited,note`.
A spreadsheet runs a cell starting with `=`, `+`, `-`, `@`, tab or CR as a formula, so the text
columns (`source`, `target`, `proposed`, `edited`, `context`, `message`, `note`) get one leading `'`
when they start with any number of `'` and then one of those characters. Reading a decision CSV
back must strip exactly that one `'` from the same columns: `findings.unescape_cell` does it, and
the review loop below uses it for its own sheet.

## Review loop

No model call happens in Sensebank: a person or a later local-model step turns a prompt file into a
reply, and Sensebank only writes the prompt and applies decisions.

```text
request  ->  (reviewer reply)  ->  review-sheet  ->  (person decides)  ->  apply
```

- **`request DECK LOCALE [--group ID ...] [-o FILE]`** writes one Markdown prompt: every group's
  concepts in English and the target language, the group rules, the allowed shared answers, and the
  reply contract. The template is a versioned file, `src/sensebank/prompts/review-request.md`; the
  first line of the output names it and its sha256 prefix. The prompt asks for reasoning per group
  first and then one short CSV block, not strict JSON, which may lower a small model's judgement.
- **Reply (proposal) CSV**: `id,field,proposed,note`. `id` is `<group>:<concept>:<locale>` as printed
  in the prompt, `field` is `label` or `aliases`, and `proposed` is the new label or the complete new
  alias list separated by `;` (`(none)` removes every alias). A fenced `csv` block among prose is
  accepted. The reply is untrusted input and is parsed and validated in code.
- **`review-sheet DECK REPLY [-o FILE]`** merges the reply into the shared decision CSV
  (`id,locale,key,kind,severity,source,target,context,message,proposed,fingerprint,decision,edited,note`).
  The model cannot supply `source`, `target` or `fingerprint`, and the deck can; that is why this step
  exists. Row id: `<group>:<concept>:<locale>:review_<field>`; `severity` is `info`, or `error` when
  the proposal would be rejected on apply, with the reason in `message`. Unknown ids stay in the sheet
  as error rows, so nothing vanishes. `decision` is left empty: model agreement is not native
  correctness, so a person fills it in with `accept`, `reject` or `edit` (the new text in `edited`).
- **`apply DECK DECISIONS [--dry-run] [--format text|json] [--reviewer NAME] [--date D]`** judges rows
  in order and writes `concepts.yaml` and `deck.yaml` once, only when a row applied. Every row gets an
  outcome: `reject` is skipped (declined); empty is skipped (undecided); another value is rejected
  (invalid decision); `accept` without `proposed` or `edit` without `edited` is rejected (invalid);
  an id that does not name a member of that group's locale entry is rejected (unknown); text already in
  place is skipped (already applied); a fingerprint that no longer matches the current field is
  rejected (stale); a change that creates an error finding is rejected (invalid, with the findings).
  These are Veriglot's semantics, implemented separately; extract shared code only after both
  implementations show common behaviour.
- **Fingerprint** is a hash of the one field a row changes. A label row and an aliases row on one
  entry are independent; a second row on a field that an earlier row just changed is stale.
- **Check gate**: after a change the groups holding the concept are checked again, and an error finding
  that was not there before (compared by id and context, so a clash that gains a member counts) rejects
  the row and leaves the deck as it was. Errors the deck already had never block an unrelated fix. A
  swap between two entries (an answer moves from one card to another) must therefore list the entry
  that gives the answer up first; a rejected row is fixed by running the same sheet again.
- **Provenance**: each word an applied row adds gets a per-word override with review `accepted` and a
  source `review-<date>-<reviewer>` (name `review <date> <reviewer>`, licence `unspecified`, because a
  model reply has no licence of its own). Words that leave the entry lose their override.
- The deck files are re-read before writing; a change on disk since the load aborts with exit 3.
- Spreadsheet formulas: sheet cells that start with `=`, `+`, `-`, `@`, tab or carriage return get a
  leading `'`, which `apply` strips from `proposed` and `edited`.
- Exit codes: 0, 1 when any row was rejected, 2 usage error (unknown locale or group, bad CSV header,
  bad date), 3 could not run.

A person's accept is recorded as review `accepted`. That says the person took the proposal, not that a
native speaker verified it.

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

## Next

The local web review list (above) and reviewing `check` findings through the same sheet: `apply` takes
`review_*` rows only, and a `check` finding's fix is applied by hand for now.
