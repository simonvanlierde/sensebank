"""Round trip on the real Six Second Scribbles deck. Skipped unless the sibling repository is present.

The seed file is MIT like this repository, but at ~21k lines it is read from the checkout rather than vendored.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from sensebank.check import check_deck
from sensebank.sixss import export_6ss, import_6ss, read_quality_rules
from sensebank.store import load_deck, save_deck

REPO = Path(os.environ.get("SIXSS_REPO", "~/code/6-second-scribbles")).expanduser()
SEED = "backend/scripts/seed_data.yaml"
QUALITY = "backend/tests/unit/test_seed_data_quality.py"


def _show(path: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(REPO), "show", f"origin/main:{path}"], capture_output=True, text=True, check=False
    )
    if run.returncode:
        pytest.skip(f"no {path} at origin/main in {REPO}")
    return run.stdout


def test_real_deck_round_trips_and_passes_its_own_rules(tmp_path: Path) -> None:
    text = _show(SEED)
    quality = tmp_path / "quality.py"
    quality.write_text(_show(QUALITY), encoding="utf-8")
    rules, shared = read_quality_rules(quality)
    deck = import_6ss(yaml.safe_load(text), commit="test", rules=rules, shared=shared)
    save_deck(deck, tmp_path / "deck")
    exported = yaml.safe_dump(export_6ss(load_deck(tmp_path / "deck")), sort_keys=False, allow_unicode=True)
    assert yaml.safe_load(exported) == yaml.safe_load(text)
    assert exported == text
    assert check_deck(deck) == []
