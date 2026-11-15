from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

from sensebank.cli import main

if TYPE_CHECKING:
    from pathlib import Path


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
