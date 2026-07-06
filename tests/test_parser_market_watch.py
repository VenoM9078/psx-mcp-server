"""Tests for the /market-watch HTML parser."""

from __future__ import annotations

import pytest

from psx_mcp_server.errors import ParseError
from psx_mcp_server.parsers.market_watch import parse_market_watch


def test_parse_market_watch_row_count(fixture):
    rows = parse_market_watch(fixture("market_watch.html"))
    assert len(rows) == 495


def test_parse_market_watch_first_row(fixture):
    rows = parse_market_watch(fixture("market_watch.html"))
    tplp = next(r for r in rows if r.symbol == "TPLP")
    assert tplp.ldcp == 11.64
    assert tplp.open == 11.87
    assert tplp.high == 12.74
    assert tplp.low == 11.87
    assert tplp.current == 12.54
    assert tplp.change == 0.90
    assert tplp.change_pct == 7.73
    assert tplp.volume == 66770551


def test_parse_market_watch_all_have_symbol_and_numeric_current(fixture):
    rows = parse_market_watch(fixture("market_watch.html"))
    assert all(r.symbol for r in rows)
    assert all(isinstance(r.current, float) for r in rows)


@pytest.mark.parametrize("bad", ["", "<html><body>no table</body></html>"])
def test_parse_market_watch_no_table_raises(bad):
    with pytest.raises(ParseError):
        parse_market_watch(bad)
