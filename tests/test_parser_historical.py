"""Tests for the POST /historical HTML parser."""

from __future__ import annotations

from psx_mcp_server.parsers.historical import parse_historical


def test_parse_historical_row_count(fixture):
    bars = parse_historical(fixture("historical_HBL_2026_06.html"))
    assert len(bars) == 20


def test_parse_historical_first_row(fixture):
    bars = parse_historical(fixture("historical_HBL_2026_06.html"))
    first = bars[0]
    assert first.date == "2026-06-30"
    assert first.open == 289.94
    assert first.high == 298.70
    assert first.low == 283.05
    assert first.close == 292.21
    assert first.volume == 3443555


def test_parse_historical_empty_month_returns_empty(fixture):
    # A far-future month legitimately has no data — empty, not an error.
    assert parse_historical(fixture("historical_empty.html")) == []


def test_parse_historical_garbage_returns_empty():
    # No table at all -> nothing to return (the tool decides if that's NoData).
    assert parse_historical("") == []
