"""Tests for the MCP tool layer, driven through an in-memory client session
with respx-mocked PSX endpoints returning committed fixtures."""

from __future__ import annotations

import contextlib
import json

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect

from conftest import load_fixture
from psx_mcp_server.client import PSXClient
from psx_mcp_server.prompts import register_prompts
from psx_mcp_server.resources import register_resources
from psx_mcp_server.tools import register_tools

BASE = "https://dps.psx.com.pk"


def _mock_all_endpoints(router) -> None:
    router.get(f"{BASE}/symbols").mock(
        return_value=httpx.Response(200, text=load_fixture("symbols.json"))
    )
    router.get(f"{BASE}/company/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("company_HBL.html"))
    )
    router.post(f"{BASE}/company/payouts").mock(
        return_value=httpx.Response(200, text=load_fixture("payouts_HBL.html"))
    )
    router.get(f"{BASE}/timeseries/int/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("timeseries_int_HBL.json"))
    )
    router.get(f"{BASE}/timeseries/eod/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("timeseries_eod_HBL.json"))
    )
    router.get(f"{BASE}/market-watch").mock(
        return_value=httpx.Response(200, text=load_fixture("market_watch.html"))
    )
    router.get(f"{BASE}/indices").mock(
        return_value=httpx.Response(200, text=load_fixture("indices.html"))
    )
    router.post(f"{BASE}/historical").mock(
        return_value=httpx.Response(200, text=load_fixture("historical_HBL_2026_06.html"))
    )


@contextlib.asynccontextmanager
async def build_session():
    """A connected in-memory session against a fully-mocked PSX backend."""
    with respx.mock(assert_all_called=False) as router:
        _mock_all_endpoints(router)
        client = PSXClient(backoff_base=0)
        mcp = FastMCP("psx-test")
        register_tools(mcp, client)
        register_resources(mcp, client)
        register_prompts(mcp)
        try:
            async with connect(mcp._mcp_server) as session:
                yield session
        finally:
            await client.close()


def payload(result) -> dict:
    """Extract a tool's structured dict payload from a CallToolResult."""
    if getattr(result, "structuredContent", None):
        sc = result.structuredContent
        # FastMCP wraps non-object returns under "result"; dicts pass through.
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(result.content[0].text)


async def call(session, name, **args) -> dict:
    result = await session.call_tool(name, args)
    assert result.isError is False, result.content
    return payload(result)


async def test_search_symbols_finds_hbl():
    async with build_session() as s:
        data = await call(s, "search_symbols", query="habib bank")
        assert data["count"] >= 1
        assert any(r["symbol"] == "HBL" for r in data["results"])


async def test_search_symbols_exact_ranked_first():
    async with build_session() as s:
        data = await call(s, "search_symbols", query="HBL")
        assert data["results"][0]["symbol"] == "HBL"


async def test_get_quote():
    async with build_session() as s:
        data = await call(s, "get_quote", symbol="hbl")
        assert data["symbol"] == "HBL"
        assert data["current"] == 318.15
        assert data["pe_ratio"] == 7.43


async def test_get_quote_unknown_symbol_is_error():
    async with build_session() as s:
        result = await s.call_tool("get_quote", {"symbol": "ZZZZINVALID"})
        assert result.isError is True
        assert "search_symbols" in result.content[0].text


async def test_get_intraday_respects_limit_and_has_ohlc():
    async with build_session() as s:
        data = await call(s, "get_intraday", symbol="HBL", interval="5min", limit=10)
        assert len(data["bars"]) <= 10
        bar = data["bars"][0]
        assert {"open", "high", "low", "close", "volume"} <= set(bar)


async def test_get_eod_history_limit():
    async with build_session() as s:
        data = await call(s, "get_eod_history", symbol="HBL", limit=5)
        assert len(data["rows"]) == 5
        assert data["truncated"] is True
        assert {"date", "open", "close", "volume"} <= set(data["rows"][0])


async def test_get_ohlc_history_has_highlow():
    async with build_session() as s:
        data = await call(s, "get_ohlc_history", symbol="HBL", month=6, year=2026)
        assert data["rows"][0]["high"] == 298.70
        assert data["rows"][0]["low"] == 283.05


async def test_get_ohlc_history_rejects_bad_month():
    async with build_session() as s:
        result = await s.call_tool("get_ohlc_history", {"symbol": "HBL", "month": 13, "year": 2026})
        assert result.isError is True


async def test_get_market_snapshot_gainers_sorted():
    async with build_session() as s:
        data = await call(s, "get_market_snapshot", category="gainers", limit=5)
        pcts = [r["change_pct"] for r in data["rows"]]
        assert pcts == sorted(pcts, reverse=True)
        assert len(data["rows"]) == 5
        assert "market_summary" in data


async def test_get_indices_has_kse100():
    async with build_session() as s:
        data = await call(s, "get_indices")
        assert any(i["name"] == "KSE100" for i in data["indices"])


async def test_get_company_info():
    async with build_session() as s:
        data = await call(s, "get_company_info", symbol="HBL")
        assert data["market_cap"] == 466679125420.0
        assert data["business_description"].startswith("Habib Bank")


async def test_get_dividends():
    async with build_session() as s:
        data = await call(s, "get_dividends", symbol="HBL", limit=3)
        assert data["count"] == 3
        assert "book_closure" in data["payouts"][0]


async def test_get_announcements():
    async with build_session() as s:
        data = await call(s, "get_announcements", symbol="HBL", limit=4)
        assert data["count"] == 4
        url = data["announcements"][0]["url"]
        assert url.startswith("https://dps.psx.com.pk/") and url.endswith(".pdf")


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_quote", {"symbol": "HBL"}),
        ("get_indices", {}),
        ("search_symbols", {"query": "bank"}),
    ],
)
async def test_tools_return_json_serializable(name, args):
    async with build_session() as s:
        result = await s.call_tool(name, args)
        assert result.isError is False
        json.dumps(payload(result))  # must be serializable
