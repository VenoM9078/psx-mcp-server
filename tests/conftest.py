"""Shared test helpers: load committed fixtures from tests/fixtures/."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Return the raw text of a committed fixture file."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture():
    """Fixture factory: `fixture("symbols.json")` -> raw text."""
    return load_fixture
