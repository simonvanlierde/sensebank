"""Command line: import-6ss, export-6ss, check, request, review-sheet, apply."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import signal
import subprocess
import sys
from pathlib import Path

import yaml

from sensebank import apply as applying
from sensebank import findings as fmt
from sensebank.check import check_deck
from sensebank.model import DeckError
from sensebank.request import request
from sensebank.review import UsageError, read_proposals, review_sheet
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
        epilog="exit codes: 0 clean, 1 check found errors or apply rejected rows, 2 usage error, 3 could not run",
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
    req = sub.add_parser("request", help="write the Markdown review prompt for one locale (no model is called)",
                         epilog="example: sensebank request deck/ nl --group zoo -o nl.md")  # fmt: skip
    req.add_argument("deck", type=Path)
    req.add_argument("locale")
    req.add_argument("--group", action="append", default=[], metavar="ID", help="only this group (repeatable)")
    req.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    sheet = sub.add_parser("review-sheet", help="merge a reviewer's proposal CSV into the shared decision CSV",
                           epilog="example: sensebank review-sheet deck/ reply.md -o decisions.csv")  # fmt: skip
    sheet.add_argument("deck", type=Path)
    sheet.add_argument("proposals", type=Path, help="the reply to `request`: CSV, or text with a fenced csv block")
    sheet.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    app = sub.add_parser("apply", help="apply a decision CSV; exit 1 when rows were rejected",
                         epilog="example: sensebank apply deck/ decisions.csv --dry-run --format json")  # fmt: skip
    app.add_argument("deck", type=Path)
    app.add_argument("decisions", type=Path)
    app.add_argument("--dry-run", action="store_true", help="judge every row, write nothing")
    app.add_argument("--format", choices=("text", "json"), default="text")
    app.add_argument("--reviewer", default="reviewer", help="who decided; recorded as the source of changed words")
    app.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="review date for the source (default: today)")
    return p


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {output.as_posix()}", file=sys.stderr)


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
    if args.command == "request":
        _emit(request(load_deck(args.deck), args.locale, args.group), args.output)
        return 0
    if args.command == "review-sheet":
        proposals = read_proposals(args.proposals.read_text(encoding="utf-8-sig"))
        _emit(review_sheet(load_deck(args.deck), proposals), args.output)
        return 0
    if args.command == "apply":
        try:
            date = (
                dt.date.fromisoformat(args.date).isoformat()
                if args.date
                else dt.datetime.now(dt.UTC).date().isoformat()
            )
        except ValueError as err:
            msg = f"--date: {err}"
            raise UsageError(msg) from err
        rows = applying.read_decisions(args.decisions.read_text(encoding="utf-8-sig"))
        outcomes, written = applying.apply_file(
            args.deck, rows, reviewer=args.reviewer, date=date, dry_run=args.dry_run
        )
        render = applying.to_json if args.format == "json" else applying.to_text
        sys.stdout.write(render(outcomes, dry_run=args.dry_run, written=written))
        return EXIT_FINDINGS if any(o.status == "rejected" for o in outcomes) else 0
    found = check_deck(load_deck(args.deck))
    sys.stdout.write({"text": fmt.to_text, "json": fmt.to_json, "csv": fmt.to_csv}[args.format](found))
    return EXIT_FINDINGS if any(f.severity == "error" for f in found) else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        return _run(_parser().parse_args(argv))
    except UsageError as err:
        print(f"error: {err}", file=sys.stderr)
        return EXIT_USAGE
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
