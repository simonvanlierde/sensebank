# Changelog

All notable changes are recorded here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Deck storage as YAML (concepts, groups, per-word provenance and licences), Six Second Scribbles import and export, and deterministic group checks with CSV, JSON and text findings (`sensebank import-6ss`, `export-6ss`, `check`). Finding ids are stable across group order and never collide; CSV cells a spreadsheet would run as formulas are escaped.
- Deck validation on load, save and import: text fields must be strings (no `yes` becoming `True`), ids and locales must match their patterns, group ids cannot leave the deck directory, and text with line-separator or C1 control characters is refused. Saves are atomic per file with LF line ends.
- Python development scaffold and [review design](docs/design.md), including the planned CSV and local web review interfaces.
- Review loop: `sensebank request` writes a versioned Markdown review prompt per locale, `review-sheet` merges the reply into the shared decision CSV, and `apply` applies accepted and edited rows with stale, unknown and group-check rejection, a full per-row report, `--dry-run`, and per-word review provenance.
- `--format json` on `import-6ss`, `export-6ss`, `request` and `review-sheet` (`path` and `counts`), `sensebank info` to list a deck's locales and groups, `-` for stdin on `review-sheet` and `apply`, and a committed output JSON Schema (`tests/output.schema.json`) that a test checks against real output.

### Changed

- With `--format json`, errors are one object on stdout (`errors: [{message, help}]`) and stderr stays empty; every JSON object now has a `command` field, and `check` has an `errors` list like `apply`. `--version` reads the package metadata. The `wrote FILE` line of `import-6ss`, `export-6ss`, `request -o` and `review-sheet -o` moved from stderr to stdout. A usage error from argparse is also the JSON object when the arguments hold `--format json`.

### Fixed

- Group and alias checks no longer treat Japanese words that differ only by a dakuten or handakuten as the same answer (ガラス and カラス, ばす and はす), matching the Six Second Scribbles scorer. Other accents stay optional, so `café` still matches `cafe`.

[Unreleased]: https://github.com/simonvanlierde/sensebank/commits/main
