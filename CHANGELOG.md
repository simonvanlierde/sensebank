# Changelog

All notable changes are recorded here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Deck storage as YAML (concepts, groups, per-word provenance and licences), Six Second Scribbles import and export, and deterministic group checks with CSV, JSON and text findings (`sensebank import-6ss`, `export-6ss`, `check`). Finding ids are stable across group order and never collide; CSV cells a spreadsheet would run as formulas are escaped.
- Deck validation on load, save and import: text fields must be strings (no `yes` becoming `True`), ids and locales must match their patterns, group ids cannot leave the deck directory, and text with line-separator or C1 control characters is refused. Saves are atomic per file with LF line ends.
- Python development scaffold and [review design](docs/design.md), including the planned CSV and local web review interfaces.

[Unreleased]: https://github.com/simonvanlierde/sensebank/commits/main
