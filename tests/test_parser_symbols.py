"""Tests for the /symbols JSON parser."""

from __future__ import annotations

import pytest

from psx_mcp_server.errors import ParseError
from psx_mcp_server.parsers.symbols import parse_symbols


def test_parse_symbols_count_and_hbl(fixture):
    symbols = parse_symbols(fixture("symbols.json"))
    assert len(symbols) == 1073
    hbl = next(s for s in symbols if s.symbol == "HBL")
    assert hbl.name == "Habib Bank Limited"
    assert hbl.sector == "COMMERCIAL BANKS"
    assert hbl.is_etf is False
    assert hbl.is_debt is False


def test_parse_symbols_missing_isgem_defaults_false(fixture):
    # The first record in the fixture has no isGEM key.
    symbols = parse_symbols(fixture("symbols.json"))
    assert all(isinstance(s.is_gem, bool) for s in symbols)


@pytest.mark.parametrize("bad", ["", "not json", "{}"])
def test_parse_symbols_malformed_raises(bad):
    with pytest.raises(ParseError):
        parse_symbols(bad)


def test_parse_symbols_empty_array_returns_empty():
    assert parse_symbols("[]") == []
