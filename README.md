# sensebank

Multilingual word lists with concept context and group rules.

Word lists are stored as plain-text YAML (see the [design](docs/design.md)). The model review loop
and the web UI are planned; they are not implemented yet.

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

Next: port the Six Second Scribbles request/apply prototype.

## License

[MIT](LICENSE). Third-party data and model weights keep their own licenses.
