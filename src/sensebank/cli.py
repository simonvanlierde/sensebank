"""Command line: import-6ss, export-6ss, check."""

from __future__ import annotations

import argparse
import io
import signal
import subprocess
import sys
from pathlib import Path

import yaml

from sensebank import findings as fmt
from sensebank.check import check_deck
from sensebank.model import DeckError
from sensebank.sixss import export_6ss, import_6ss, read_quality_rules
from sensebank.store import load_deck, save_deck

EXIT_FINDINGS, EXIT_USAGE, EXIT_FAILED = 1, 2, 3
FORMATS = ("text", "json", "csv")


def _commit_of(path: Path) -> str:
    """The commit that last touched `path`'s repository, or `unknown` outside git."""
    try:
        run = subprocess.run(  # noqa: S603
            ["git", "-C", str(path.resolve().parent), "rev-parse", "--short=12", "HEAD"],  # noqa: S607
            capture_output=True, text=True, check=False,
        )  # fmt: skip
    except OSError:
        return "unknown"
    return run.stdout.strip() if run.returncode == 0 and run.stdout.strip() else "unknown"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sensebank",
        description="Multilingual word lists with concept context and group rules.",
        epilog="exit codes: 0 clean, 1 check found errors, 2 usage error, 3 could not run",
    )
    p.add_argument("--version", action="version", version="sensebank 0.1.0")
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-6ss", help="import a Six Second Scribbles seed_data.yaml into a deck directory",
                         epilog="example: sensebank import-6ss seed_data.yaml deck/ --commit 36f09f5")  # fmt: skip
    imp.add_argument("seed", type=Path)
    imp.add_argument("outdir", type=Path)
    imp.add_argument(
        "--commit", help="commit recorded as the source snapshot (default: HEAD of the seed file's repository)"
    )
    imp.add_argument("--quality-tests", type=Path, metavar="FILE",
                     help="6ss test_seed_data_quality.py; its allowlists become deck rules")  # fmt: skip
    exp = sub.add_parser("export-6ss", help="write a deck directory as a seed_data.yaml",
                         epilog="example: sensebank export-6ss deck/ seed_data.yaml")  # fmt: skip
    exp.add_argument("deck", type=Path)
    exp.add_argument("seed", type=Path)
    chk = sub.add_parser("check", help="run the group checks; exit 1 when there are errors",
                         epilog="example: sensebank check deck/ --format csv > findings.csv")  # fmt: skip
    chk.add_argument("deck", type=Path)
    chk.add_argument("--format", choices=FORMATS, default="text")
    return p


def _run(args: argparse.Namespace) -> int:
    if args.command == "import-6ss":
        seed = yaml.safe_load(args.seed.read_text(encoding="utf-8"))
        rules, shared = read_quality_rules(args.quality_tests) if args.quality_tests else (None, None)
        deck = import_6ss(seed, commit=args.commit or _commit_of(args.seed), rules=rules, shared=shared)
        save_deck(deck, args.outdir)
        print(f"imported {len(deck.concepts)} concepts, {len(deck.groups)} groups into {args.outdir.as_posix()}")
        return 0
    if args.command == "export-6ss":
        args.seed.write_text(
            yaml.safe_dump(export_6ss(load_deck(args.deck)), sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"wrote {args.seed.as_posix()}")
        return 0
    found = check_deck(load_deck(args.deck))
    sys.stdout.write({"text": fmt.to_text, "json": fmt.to_json, "csv": fmt.to_csv}[args.format](found))
    return EXIT_FINDINGS if any(f.severity == "error" for f in found) else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        return _run(_parser().parse_args(argv))
    except (DeckError, OSError, yaml.YAMLError, KeyError) as err:
        print(f"error: {str(err).splitlines()[0] if str(err) else type(err).__name__}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.raise_signal(signal.SIGINT)
        return 130
    except Exception as err:  # noqa: BLE001 # exit 1 means findings, so a crash must not fall through to it
        print(f"error: unexpected {type(err).__name__}: {err}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
