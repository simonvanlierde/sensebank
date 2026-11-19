from __future__ import annotations

import io
import json
import signal
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from sensebank.cli import main


def _seed(path: Path, seed: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(seed, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_import_check_export(clean_seed: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
    seed = _seed(tmp_path / "seed.yaml", clean_seed)
    assert main(["import-6ss", str(seed), str(tmp_path / "deck"), "--commit", "abc"]) == 0
    assert main(["check", str(tmp_path / "deck")]) == 0
    assert main(["export-6ss", str(tmp_path / "deck"), str(tmp_path / "out.yaml")]) == 0
    assert (tmp_path / "out.yaml").read_bytes() == seed.read_bytes()
    capsys.readouterr()


def test_check_exits_1_on_errors_and_prints_json(defective_seed: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
    seed = _seed(tmp_path / "seed.yaml", defective_seed)
    main(["import-6ss", str(seed), str(tmp_path / "deck"), "--commit", "abc"])
    capsys.readouterr()
    assert main(["check", str(tmp_path / "deck"), "--format", "json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["error"] > 0


def test_check_csv_to_stdout(defective_seed: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
    seed = _seed(tmp_path / "seed.yaml", defective_seed)
    main(["import-6ss", str(seed), str(tmp_path / "deck"), "--commit", "abc"])
    capsys.readouterr()
    main(["check", str(tmp_path / "deck"), "--format", "csv"])
    assert capsys.readouterr().out.startswith("id,locale,key,kind,severity,")


def test_missing_deck_is_exit_3(tmp_path: Path, capsys: Any) -> None:
    assert main(["check", str(tmp_path / "nope")]) == 3
    assert capsys.readouterr().err.startswith("error:")


def test_unexpected_failure_is_exit_3_not_findings(
    clean_seed: dict[str, Any], tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    seed = _seed(tmp_path / "seed.yaml", clean_seed)
    main(["import-6ss", str(seed), str(tmp_path / "deck"), "--commit", "abc"])

    def broken(_deck: object) -> list[object]:
        msg = "bad state"
        raise RuntimeError(msg)

    monkeypatch.setattr("sensebank.cli.check_deck", broken)
    capsys.readouterr()
    assert main(["check", str(tmp_path / "deck")]) == 3
    assert capsys.readouterr().err == "error: unexpected RuntimeError: bad state\n"


def test_seed_that_is_not_6ss_shaped_is_exit_3(tmp_path: Path, capsys: Any) -> None:
    seed = tmp_path / "seed.yaml"
    seed.write_text("prompts: [1, 2]\n", encoding="utf-8")
    assert main(["import-6ss", str(seed), str(tmp_path / "deck"), "--commit", "abc"]) == 3
    assert capsys.readouterr().err.startswith("error:")


SCHEMA = json.loads((Path(__file__).parent / "output.schema.json").read_text(encoding="utf-8"))


def _run_json(argv: list[str], capsys: Any) -> tuple[int, dict[str, Any]]:
    """Run `main`, check the one JSON object on stdout against the committed schema, and keep stderr empty."""
    code = main([*argv, "--format", "json"])
    captured = capsys.readouterr()
    assert captured.err == ""
    out = json.loads(captured.out)
    jsonschema.validate(out, SCHEMA)
    return code, out


def test_every_command_json_matches_the_schema(defective_seed: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
    deck = tmp_path / "deck"
    seed = _seed(tmp_path / "seed.yaml", defective_seed)
    code, out = _run_json(["import-6ss", str(seed), str(deck), "--commit", "abc"], capsys)
    assert (code, out["counts"]["groups"], out["path"]) == (0, 2, deck.as_posix())
    code, out = _run_json(["info", str(deck)], capsys)
    assert code == 0
    assert out["locales"] == ["en", "es", "fr"]
    assert [g["id"] for g in out["groups"]] == ["zoo", "kitchen"]
    code, out = _run_json(["check", str(deck)], capsys)
    assert (code, out["errors"]) == (1, [])
    code, out = _run_json(["export-6ss", str(deck), str(tmp_path / "out.yaml")], capsys)
    assert (code, out["counts"]["concepts"]) == (0, 5)
    code, out = _run_json(["request", str(deck), "es", "-o", str(tmp_path / "es.md")], capsys)
    assert (code, out["counts"]) == (0, {"groups": 2})
    decisions = tmp_path / "decisions.csv"
    reply = tmp_path / "reply.csv"
    reply.write_text("id,field,proposed,note\nzoo:glorp:es:nonsense,label,x,\n", encoding="utf-8")
    code, out = _run_json(["review-sheet", str(deck), str(reply), "-o", str(decisions)], capsys)
    assert (code, out["counts"]) == (0, {"proposals": 1})
    code, out = _run_json(["apply", str(deck), str(decisions), "--dry-run"], capsys)
    assert code == 0
    assert out["errors"] == []


def test_json_errors_go_to_stdout_only(tmp_path: Path, capsys: Any) -> None:
    code = main(["check", str(tmp_path / "nope"), "--format", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (3, "")
    out = json.loads(captured.out)
    jsonschema.validate(out, SCHEMA)
    assert out["command"] == "check"
    assert out["errors"][0]["message"].startswith("cannot read")
    assert out["errors"][0]["help"] is None


def test_json_usage_error_is_exit_2_in_the_envelope(deck_dir: Path, capsys: Any) -> None:
    code = main(["request", str(deck_dir), "es", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    jsonschema.validate(out, SCHEMA)
    assert code == 2
    assert "needs -o" in out["errors"][0]["message"]


def test_stdin_dash_feeds_review_sheet_and_apply(deck_dir: Path, capsys: Any, monkeypatch: Any) -> None:
    reply = "id,field,proposed,note\nzoo:glorp:es:nonsense,label,x,\n"
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(reply.encode())))
    assert main(["review-sheet", str(deck_dir), "-"]) == 0
    sheet = capsys.readouterr().out
    assert sheet.startswith('"id","locale"')
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(sheet.encode())))
    assert main(["apply", str(deck_dir), "-", "--dry-run"]) == 0
    assert "skipped: undecided" in capsys.readouterr().out


def test_info_text_and_version(deck_dir: Path, capsys: Any) -> None:
    assert main(["info", str(deck_dir)]) == 0
    assert "locales en es fr" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out == f"sensebank {metadata.version('sensebank')}\n"


def test_argparse_usage_error_is_json_with_format_json(capsys: Any) -> None:
    for argv in (
        ["check", "--format", "json"],
        ["check", "d", "--bogus", "--format=json"],
        ["nope", "--format", "json"],
    ):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        captured = capsys.readouterr()
        assert (exc.value.code, captured.err) == (2, "")
        jsonschema.validate(json.loads(captured.out), SCHEMA)
    with pytest.raises(SystemExit):
        main(["check"])
    assert capsys.readouterr().err.startswith("usage:")


def test_json_without_output_is_refused_before_reading_input(tmp_path: Path, capsys: Any) -> None:
    code = main(["review-sheet", str(tmp_path / "no-deck"), str(tmp_path / "no-reply"), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert (code, out["errors"][0]["help"]) == (2, "add -o FILE")


def test_dash_dot_slash_is_a_file_and_bad_utf8_is_exit_2(
    deck_dir: Path, tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("-").write_bytes(b"\xff\xfe\x00bad")
    assert main(["apply", str(deck_dir), "./-"]) == 2
    assert capsys.readouterr().err == "error: ./- is not UTF-8\n"


def test_sigint_with_json_flushes_the_envelope(deck_dir: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "sensebank.cli", "apply", str(deck_dir), "-", "--format", "json"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    time.sleep(1.5)  # NOTE: wait until the process reads stdin; a signal sent during start-up skips main's handler
    proc.send_signal(signal.SIGINT)
    out, _ = proc.communicate(timeout=10)
    assert proc.returncode == -signal.SIGINT
    body = json.loads(out)
    jsonschema.validate(body, SCHEMA)
    assert body["errors"][0]["message"] == "interrupted"
