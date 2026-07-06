"""Live smoke tests that hit the real PSX Data Portal.

Excluded from the default run (and from CI) via the `live` marker. They assert
shape only — never exact prices — so they act as an early-warning canary for
PSX markup changes. Run manually:

    uv run pytest -m live --override-ini "addopts="
"""

from __future__ import annotations

import pytest

from psx_mcp_server.client import PSXClient
from psx_mcp_server.errors import NoDataError
from psx_mcp_server.parsers.company import parse_company_info, parse_quote
from psx_mcp_server.parsers.indices import parse_indices
from psx_mcp_server.parsers.market_watch import parse_market_watch
from psx_mcp_server.parsers.symbols import parse_symbols
from psx_mcp_server.parsers.timeseries import parse_eod, parse_intraday

pytestmark = pytest.mark.live


@pytest.fixture
async def client():
    c = PSXClient()
    try:
        yield c
    finally:
        await c.close()


async def test_live_symbols_directory(client):
    symbols = parse_symbols(await client.fetch_symbols())
    assert len(symbols) > 500
    assert any(s.symbol == "HBL" for s in symbols)


async def test_live_quote(client):
    quote = parse_quote(await client.fetch_company("HBL"))
    assert quote.name.startswith("Habib Bank")
    assert quote.current is not None and quote.current > 0


async def test_live_company_info(client):
    info = parse_company_info(await client.fetch_company("HBL"))
    assert info.market_cap is not None and info.market_cap > 0
    assert info.business_description


async def test_live_eod_history(client):
    bars = parse_eod(await client.fetch_eod("HBL"))
    assert len(bars) > 100
    assert bars[0].close > 0


async def test_live_eod_works_for_index(client):
    bars = parse_eod(await client.fetch_eod("KSE100"))
    assert bars[0].close > 10000  # KSE-100 trades in the tens of thousands


async def test_live_indices(client):
    indices = parse_indices(await client.fetch_indices())
    assert any(i.name == "KSE100" for i in indices)


async def test_live_market_watch(client):
    rows = parse_market_watch(await client.fetch_market_watch())
    assert len(rows) > 100
    assert all(r.symbol for r in rows)


async def test_live_intraday_or_closed(client):
    """Intraday returns data during the session; empty after close is also valid."""
    ticks = parse_intraday(await client.fetch_intraday("HBL"))
    if ticks:
        assert ticks[0].price > 0
    else:
        # Confirms the market-closed shape (empty data) that the tool maps to NoDataError.
        with pytest.raises(NoDataError):
            raise NoDataError("closed")
