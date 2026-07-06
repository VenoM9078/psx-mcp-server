"""Tests for PSXClient: URLs, headers, retries, caching, error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from psx_mcp_server.client import PSXClient
from psx_mcp_server.errors import PSXUnavailableError

BASE = "https://dps.psx.com.pk"


@respx.mock
async def test_fetch_symbols_url_and_user_agent():
    route = respx.get(f"{BASE}/symbols").mock(return_value=httpx.Response(200, text="[]"))
    client = PSXClient(backoff_base=0)
    try:
        assert await client.fetch_symbols() == "[]"
        assert route.called
        assert "psx-mcp-server" in route.calls.last.request.headers["user-agent"]
    finally:
        await client.close()


@respx.mock
async def test_symbol_is_normalized_in_url():
    route = respx.get(f"{BASE}/company/HBL").mock(return_value=httpx.Response(200, text="ok"))
    client = PSXClient(backoff_base=0)
    try:
        await client.fetch_company("hbl ")
        assert route.called
    finally:
        await client.close()


@respx.mock
async def test_cache_prevents_second_network_call():
    route = respx.get(f"{BASE}/symbols").mock(return_value=httpx.Response(200, text="[]"))
    client = PSXClient(backoff_base=0)
    try:
        await client.fetch_symbols()
        await client.fetch_symbols()
        assert route.call_count == 1
    finally:
        await client.close()


@respx.mock
async def test_retry_on_500_then_success():
    route = respx.get(f"{BASE}/indices").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, text="ok")]
    )
    client = PSXClient(backoff_base=0)
    try:
        assert await client.fetch_indices() == "ok"
        assert route.call_count == 2
    finally:
        await client.close()


@respx.mock
async def test_retry_on_connect_error_then_success():
    route = respx.get(f"{BASE}/indices").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
    )
    client = PSXClient(backoff_base=0)
    try:
        assert await client.fetch_indices() == "ok"
        assert route.call_count == 2
    finally:
        await client.close()


@respx.mock
async def test_unavailable_after_exhausting_retries():
    respx.get(f"{BASE}/indices").mock(return_value=httpx.Response(503))
    client = PSXClient(backoff_base=0, max_retries=3)
    try:
        with pytest.raises(PSXUnavailableError):
            await client.fetch_indices()
    finally:
        await client.close()


@respx.mock
async def test_no_retry_on_4xx():
    route = respx.get(f"{BASE}/company/HBL").mock(return_value=httpx.Response(404))
    client = PSXClient(backoff_base=0)
    try:
        with pytest.raises(PSXUnavailableError):
            await client.fetch_company("HBL")
        assert route.call_count == 1
    finally:
        await client.close()


@respx.mock
async def test_fetch_historical_posts_form_and_ajax_header():
    route = respx.post(f"{BASE}/historical").mock(
        return_value=httpx.Response(200, text="<table></table>")
    )
    client = PSXClient(backoff_base=0)
    try:
        await client.fetch_historical("hbl", 6, 2026)
        req = route.calls.last.request
        body = req.content.decode()
        assert "symbol=HBL" in body
        assert "month=6" in body
        assert "year=2026" in body
        assert req.headers.get("x-requested-with") == "XMLHttpRequest"
    finally:
        await client.close()


@respx.mock
async def test_fetch_payouts_posts_symbol():
    route = respx.post(f"{BASE}/company/payouts").mock(
        return_value=httpx.Response(200, text="<table></table>")
    )
    client = PSXClient(backoff_base=0)
    try:
        await client.fetch_payouts("HBL")
        assert "symbol=HBL" in route.calls.last.request.content.decode()
    finally:
        await client.close()
