# sensebank

Multilingual word lists with concept context and group rules.

Word lists are stored as plain-text YAML (see the [design](docs/design.md)). The review loop (`request`, `review-sheet`,
`apply`) is implemented; no step calls a model. The web UI is planned.

## Usage

```sh
uv run sensebank import-6ss seed_data.yaml deck/ --quality-tests test_seed_data_quality.py
uv run sensebank check deck/ --format csv > findings.csv   # text (default), json or csv; exit 1 on errors
uv run sensebank export-6ss deck/ seed_data.yaml           # reproduces the seed file
```

`import-6ss` records each word's source as `six-second-scribbles seed_data.yaml @ <commit>`
(`--commit` overrides the commit read from git). `--quality-tests` takes the allowlists of the
Six Second Scribbles quality tests as deck rules. Exit codes: 0 clean, 1 errors found,
2 usage error, 3 could not run.

`sensebank info deck/` lists a deck's locales and groups. `--version` prints the installed package version.

### JSON output

Every command takes `--format json` (`import-6ss`, `export-6ss`, `info`, `request`, `review-sheet`, `check`, `apply`)
and then prints exactly one object on stdout: `schema_version`, `command`, the result, and `errors`, a list of
`{message, help}` (`help` is null when no fix is known). A run that fails (exit 2 or 3) prints the object with only
`schema_version`, `command` and `errors`, and stderr stays empty. `import-6ss`, `export-6ss`, `request` and
`review-sheet` report `path` and `counts`; with `--format json`, `request` and `review-sheet` need `-o`, as stdout holds
the JSON. [tests/output.schema.json](tests/output.schema.json) is the JSON Schema; a test validates real output against
it. An added field is not a breaking change; a removed or retyped one bumps `schema_version`.

`apply` and `review-sheet` read `-` as stdin, so the loop needs no temp files:

```sh
uv run sensebank request deck/ nl | model | uv run sensebank review-sheet deck/ - -o decisions.csv
```

### Review loop

```sh
uv run sensebank request deck/ nl --group animals -o nl.md        # prompt file, no model is called
# a person or a local model answers it; the reply holds a csv block: id,field,proposed,note
uv run sensebank review-sheet deck/ reply.md -o decisions.csv     # shared decision columns, decision empty
# a person fills decision (accept, reject, edit) and edited
uv run sensebank apply deck/ decisions.csv --dry-run              # every row accounted; exit 1 if any rejected
uv run sensebank apply deck/ decisions.csv --reviewer "name"      # writes the deck, records provenance
```

`apply` rejects stale rows (the field changed since the sheet), unknown ids and any change that
creates a group error, and skips declined, undecided and already applied rows. Rows apply in order, so a second row on the same entry and field is stale: list a row that gives an
alias up before the one that receives it, or run the sheet twice. See the
[design](docs/design.md#review-loop) for the formats.

## Scope

Concept entries: a stable entry id, an English gloss, language labels and accepted answers, provenance, review state and group membership.

Contextual group review and checks for conflicting accepted answers, duplicate aliases and unknown entries. Wikidata and Wiktionary supply candidates for a person to consider.

A simple local web UI is planned for reviewing findings, editing proposed wording
and accepting or rejecting changes. CSV remains an alternative for the same review.

## Development

Install uv and just, then run:

```sh
just py-sync
uv tool install prek
prek install
just check
just hooks
```

## License

[MIT](LICENSE). Third-party data and model weights keep their own licenses.
