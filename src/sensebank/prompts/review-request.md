# Word deck review: $deck, $language

Each concept below is played in a word game: a player is shown a group and one concept's English
label, and guesses are typed against the concept's **label** and its **aliases**, the other
answers the game accepts. Players never see the aliases. Below is every group with all its
concepts, in English and in $language. Review the $language.

- Read each word in the sense its **group and English concept** give it. In a vehicles group,
  "plane" is an aircraft, never a flat surface.
- A label should be the everyday word a $language speaker would use while playing, not a
  literal translation.
- Aliases are words people would really type for this concept: synonyms, the common short
  form, a common spelling variant. Remove anything that names something else, is a rare or
  formal word, or is in another language (a loanword $language speakers actually use is fine).
- No answer may be accepted by two concepts in the same group, unless it is listed under that
  group's allowed shared answers. Plural and singular forms count as the same answer. If two
  concepts share an alias, keep it on the concept it names best, or on neither.
- An alias must differ from its concept's label, and aliases must differ from each other.
- You are a second opinion, not an authority: when unsure, leave the word as it is.

## How to answer

Go through the groups in order. For each one, write a few lines on what you would change and
why, then "checked". After the last group, give one CSV block with only the fields you change:

```csv
id,field,proposed,note
$example_id,aliases,alias one; alias two,"dropped X: means something else"
```

- `id` is copied from the first column of the tables below.
- `field` is `label` or `aliases`.
- For `aliases`, `proposed` is the **complete new list**, separated by "; ". Write `$none` to
  remove every alias. For `label`, it is the new label.
- One row per field you change. Keep the note short. Return nothing else in the CSV block.

There are $groups groups and $concepts concepts.
