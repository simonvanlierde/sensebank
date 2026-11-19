"""Command line: import-6ss, export-6ss, info, check, request, review-sheet, apply."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import signal
import subprocess
import sys
from importlib.metadata import version as _version
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import yaml

from sensebank import apply as applying
from sensebank import findings as fmt
from sensebank.check import check_deck
from sensebank.model import Deck, DeckError
from sensebank.request import request
from sensebank.review import UsageError, read_proposals, review_sheet
from sensebank.sixss import export_6ss, import_6ss, read_quality_rules
from sensebank.store import load_deck, save_deck

if TYPE_CHECKING:
    from typing import NoReturn

EXIT_FINDINGS, EXIT_USAGE, EXIT_FAILED = 1, 2, 3
COMMANDS = ("import-6ss", "export-6ss", "info", "check", "request", "review-sheet", "apply")
FORMATS = ("text", "json", "csv")


class _Parser(argparse.ArgumentParser):
    """A usage error is exit 2 with the JSON envelope on stdout when the arguments ask for `--format json`."""

    argv: ClassVar[list[str]] = []

    def error(self, message: str) -> NoReturn:
        argv = self.argv
        if "--format=json" not in argv and ("--format", "json") not in pairwise(argv):
            super().error(message)
        command = next((a for a in argv if not a.startswith("-")), "")
        sys.stdout.write(fmt.envelope(command if command in COMMANDS else "", errors=[message]))
        sys.exit(EXIT_USAGE)


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
    p = _Parser(
        prog="sensebank",
        description="Multilingual word lists with concept context and group rules.",
        epilog="exit codes: 0 clean, 1 check found errors or apply rejected rows, 2 usage error, 3 could not run",
    )
    p.add_argument("--version", action="version", version=f"sensebank {_version('sensebank')}")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    imp = sub.add_parser("import-6ss", help="import a Six Second Scribbles seed_data.yaml into a deck directory",
                         epilog="example: sensebank import-6ss seed_data.yaml deck/ --commit 36f09f5")  # fmt: skip
    imp.add_argument("seed", type=Path)
    imp.add_argument("outdir", type=Path)
    imp.add_argument(
        "--commit", help="commit recorded as the source snapshot (default: HEAD of the seed file's repository)"
    )
    imp.add_argument("--quality-tests", type=Path, metavar="FILE",
                     help="6ss test_seed_data_quality.py; its allowlists become deck rules")  # fmt: skip
    imp.add_argument("--format", choices=("text", "json"), default="text")
    exp = sub.add_parser("export-6ss", help="write a deck directory as a seed_data.yaml",
                         epilog="example: sensebank export-6ss deck/ seed_data.yaml")  # fmt: skip
    exp.add_argument("deck", type=Path)
    exp.add_argument("seed", type=Path)
    exp.add_argument("--format", choices=("text", "json"), default="text")
    info = sub.add_parser("info", help="list a deck's locales and groups",
                          epilog="example: sensebank info deck/ --format json")  # fmt: skip
    info.add_argument("deck", type=Path)
    info.add_argument("--format", choices=("text", "json"), default="text")
    chk = sub.add_parser("check", help="run the group checks; exit 1 when there are errors",
                         epilog="example: sensebank check deck/ --format csv > findings.csv")  # fmt: skip
    chk.add_argument("deck", type=Path)
    chk.add_argument("--format", choices=FORMATS, default="text")
    req = sub.add_parser("request", help="write the Markdown review prompt for one locale (no model is called)",
                         epilog="example: sensebank request deck/ nl --group zoo -o nl.md")  # fmt: skip
    req.add_argument("deck", type=Path)
    req.add_argument("locale")
    req.add_argument("--group", action="append", default=[], metavar="ID", help="only this group (repeatable)")
    req.add_argument("-o", "--output", type=Path, help="write here instead of stdout (required with --format json)")
    req.add_argument("--format", choices=("text", "json"), default="text", help="json: report the written file")
    sheet = sub.add_parser("review-sheet", help="merge a reviewer's proposal CSV into the shared decision CSV",
                           epilog="example: sensebank review-sheet deck/ reply.md -o decisions.csv")  # fmt: skip
    sheet.add_argument("deck", type=Path)
    sheet.add_argument("proposals", help="the reply to `request`: CSV, or text with a fenced csv block; - reads stdin")
    sheet.add_argument("-o", "--output", type=Path, help="write here instead of stdout (required with --format json)")
    sheet.add_argument("--format", choices=("text", "json"), default="text", help="json: report the written file")
    app = sub.add_parser("apply", help="apply a decision CSV; exit 1 when rows were rejected",
                         epilog="example: sensebank apply deck/ decisions.csv --dry-run --format json")  # fmt: skip
    app.add_argument("deck", type=Path)
    app.add_argument("decisions", help="the decision CSV; - reads stdin")
    app.add_argument("--dry-run", action="store_true", help="judge every row, write nothing")
    app.add_argument("--format", choices=("text", "json"), default="text")
    app.add_argument("--reviewer", default="reviewer", help="who decided; recorded as the source of changed words")
    app.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="review date for the source (default: today)")
    return p


def _read_input(name: str) -> str:
    """The text of file `name`, or of stdin for exactly `-` (`./-` is a file); a leading BOM is dropped."""
    try:
        raw = sys.stdin.buffer.read() if name == "-" else Path(name).read_bytes()
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as err:
        msg = f"{'stdin' if name == '-' else name} is not UTF-8"
        raise UsageError(msg) from err


def _report(args: argparse.Namespace, path: Path, counts: dict[str, int]) -> None:
    """The result of a command that writes a file: `path` and `counts` as JSON, else one text line."""
    if args.format == "json":
        sys.stdout.write(fmt.envelope(args.command, {"path": path.as_posix(), "counts": counts}))
    else:
        print(f"wrote {path.as_posix()}" + "".join(f", {n} {k}" for k, n in counts.items()))


def _emit(args: argparse.Namespace, text: str, counts: dict[str, int]) -> None:
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8", newline="\n")
        _report(args, args.output, counts)
    else:
        sys.stdout.write(text)


def _info(deck: Deck, path: Path, fmt_: str) -> str:
    groups = [{"id": g.id, "kind": g.kind, "members": len(g.members)} for g in deck.groups]
    if fmt_ == "json":
        return fmt.envelope(
            "info", {"path": path.as_posix(), "name": deck.name, "locales": deck.locales,
                     "concepts": len(deck.concepts), "groups": groups},
        )  # fmt: skip
    lines = [f"{deck.name}: {len(deck.concepts)} concepts, locales {' '.join(deck.locales)}"]
    lines += [f"  {g['id']} ({g['kind']}): {g['members']} members" for g in groups]
    return "\n".join(lines) + "\n"


def _run(args: argparse.Namespace) -> int:  # noqa: PLR0911 # one return per command
    if args.command in ("request", "review-sheet") and args.format == "json" and args.output is None:
        msg = "--format json needs -o: stdout holds the JSON, not the file"
        raise UsageError(msg, "add -o FILE")
    if args.command == "import-6ss":
        seed = yaml.safe_load(args.seed.read_text(encoding="utf-8"))
        rules, shared = read_quality_rules(args.quality_tests) if args.quality_tests else (None, None)
        deck = import_6ss(seed, commit=args.commit or _commit_of(args.seed), rules=rules, shared=shared)
        save_deck(deck, args.outdir)
        _report(args, args.outdir, {"concepts": len(deck.concepts), "groups": len(deck.groups)})
        return 0
    if args.command == "export-6ss":
        deck = load_deck(args.deck)
        args.seed.write_text(yaml.safe_dump(export_6ss(deck), sort_keys=False, allow_unicode=True), encoding="utf-8")
        _report(args, args.seed, {"concepts": len(deck.concepts), "groups": len(deck.groups)})
        return 0
    if args.command == "info":
        sys.stdout.write(_info(load_deck(args.deck), args.deck, args.format))
        return 0
    if args.command == "request":
        deck = load_deck(args.deck)
        groups = [g for g in deck.groups if not args.group or g.id in args.group]
        _emit(args, request(deck, args.locale, args.group), {"groups": len(groups)})
        return 0
    if args.command == "review-sheet":
        proposals = read_proposals(_read_input(args.proposals))
        _emit(args, review_sheet(load_deck(args.deck), proposals), {"proposals": len(proposals)})
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
        rows = applying.read_decisions(_read_input(args.decisions))
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
    _Parser.argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)  # a usage error exits 2 here

    def fail(message: str, code: int, help_: str | None = None) -> int:
        # With --format json stdout holds the one error object and stderr stays empty.
        if getattr(args, "format", "text") == "json":
            sys.stdout.write(fmt.envelope(args.command, errors=[message], help_=help_))
        else:
            print(f"error: {message}", file=sys.stderr)
            if help_:
                print(f"help: {help_}", file=sys.stderr)
        return code

    try:
        return _run(args)
    except UsageError as err:
        return fail(str(err), EXIT_USAGE, err.help)
    except (DeckError, OSError, yaml.YAMLError, KeyError) as err:
        return fail(str(err).splitlines()[0] if str(err) else type(err).__name__, EXIT_FAILED)
    except KeyboardInterrupt:
        fail("interrupted", 130)
        sys.stdout.flush()  # raise_signal kills the process before the buffers are flushed
        sys.stderr.flush()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.raise_signal(signal.SIGINT)
        return 130
    except Exception as err:  # noqa: BLE001 # exit 1 means findings, so a crash must not fall through to it
        return fail(f"unexpected {type(err).__name__}: {err}", EXIT_FAILED)


if __name__ == "__main__":
    sys.exit(main())
