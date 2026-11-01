"""Smoke test: replace with real tests."""

import sensebank


def test_imports() -> None:
    """The package imports."""
    assert sensebank.__name__ == "sensebank"
