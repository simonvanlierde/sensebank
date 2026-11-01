# sensebank

Multilingual word lists with concept context and group rules.

This repository contains the initial Python scaffold and [design](docs/design.md).
Review commands and the web UI are planned; they are not implemented yet.

## Scope

Concept entries: a stable entry id, an English gloss, language labels and accepted answers, provenance, review state and group membership.

Contextual group review and checks for conflicting accepted answers, duplicate aliases and unknown entries. Wikidata and Wiktionary supply candidates for a person to consider.

A simple local web UI is planned for reviewing findings, editing proposed wording
and accepting or rejecting changes. CSV remains an alternative for the same review.

## Development

Install uv, just and prek, then run:

```sh
just py-sync
prek install
just check
just hooks
```

Settle storage and the Six Second Scribbles import/export mapping, then port the existing request/apply prototype.

## License

[MIT](LICENSE). Third-party data and model weights keep their own licenses.
