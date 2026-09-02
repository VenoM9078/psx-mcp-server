"""Verify the assembled server exposes the expected tools, resources, prompts."""

from __future__ import annotations

import sys

from psx_mcp_server.server import http_main, mcp

EXPECTED_TOOLS = {
    "search_symbols",
    "get_quote",
    "get_intraday",
    "get_eod_history",
    "get_ohlc_history",
    "get_market_snapshot",
    "get_indices",
    "get_company_info",
    "get_dividends",
    "get_announcements",
    "get_financials",
    "get_company_reports",
    "get_company_alerts",
    "get_price_performance",
}


async def test_exposes_all_tools():
    names = {t.name for t in await mcp.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_tools_have_descriptions():
    for tool in await mcp.list_tools():
        assert tool.description and len(tool.description) > 20


async def test_exposes_resources():
    uris = {str(r.uri) for r in await mcp.list_resources()}
    assert uris == {"psx://symbols", "psx://sectors", "psx://indices"}


async def test_exposes_prompts():
    names = {p.name for p in await mcp.list_prompts()}
    assert names == {"analyze_stock", "market_overview"}


def test_http_entrypoint_uses_unauthenticated_streamable_http(monkeypatch):
    calls = []
    original_host = mcp.settings.host
    original_port = mcp.settings.port
    original_transport_security = mcp.settings.transport_security
    monkeypatch.setattr(sys, "argv", ["psx-mcp-http", "--port", "8765"])
    monkeypatch.setattr(mcp, "run", lambda **kwargs: calls.append(kwargs))

    try:
        http_main()
    finally:
        mcp.settings.host = original_host
        mcp.settings.port = original_port
        mcp.settings.transport_security = original_transport_security

    assert calls == [{"transport": "streamable-http"}]
    assert mcp.settings.auth is None
