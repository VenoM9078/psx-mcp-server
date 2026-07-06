"""Tests for the timeseries (intraday + EOD) JSON parsers."""

from __future__ import annotations

import pytest

from psx_mcp_server.errors import ParseError
from psx_mcp_server.parsers.timeseries import parse_eod, parse_intraday


def test_parse_intraday_first_tick(fixture):
    ticks = parse_intraday(fixture("timeseries_int_HBL.json"))
    assert len(ticks) > 100
    first = ticks[0]
    assert first.price == 318.14
    assert first.volume == 100
    # Newest first, converted to Pakistan Standard Time (UTC+5).
    assert first.time.isoformat() == "2026-07-06T15:49:27+05:00"


def test_parse_eod_fields_and_order(fixture):
    bars = parse_eod(fixture("timeseries_eod_HBL.json"))
    assert len(bars) > 100
    first = bars[0]
    assert first.date == "2026-07-06"
    assert first.open == 308.44
    assert first.close == 318.14
    assert first.volume == 5426927
    # Second row confirms newest-first ordering.
    assert bars[1].date == "2026-07-03"
    assert bars[1].close == 305.91


def test_parse_eod_works_for_indices(fixture):
    bars = parse_eod(fixture("timeseries_eod_KSE100.json"))
    assert bars[0].date == "2026-07-06"
    assert bars[0].close == 187454.69


def test_parse_intraday_empty_status_returns_empty():
    assert parse_intraday('{"status":0,"message":"no data","data":[]}') == []


def test_parse_eod_empty_data_returns_empty():
    assert parse_eod('{"status":1,"message":"","data":[]}') == []


@pytest.mark.parametrize("bad", ["", "not json", "<html></html>"])
def test_parse_intraday_malformed_raises(bad):
    with pytest.raises(ParseError):
        parse_intraday(bad)
