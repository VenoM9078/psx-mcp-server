"""Tests for PSXClient: URLs, headers, retries, caching, error mapping."""

from __future__ import annotations

import asyncio

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
async def test_cache_freshness_distinguishes_network_fetch_and_cache_service():
    route = respx.get(f"{BASE}/symbols").mock(return_value=httpx.Response(200, text="[]"))
    client = PSXClient(backoff_base=0)
    try:
        first = await client.fetch_symbols()
        second = await client.fetch_symbols()
        first_meta = first.metadata
        second_meta = second.metadata
        assert first_meta["from_cache"] is False
        assert second_meta["from_cache"] is True
        assert second_meta["source_fetched_at"] == first_meta["source_fetched_at"]
        assert second_meta["served_at"] >= first_meta["served_at"]
        assert second_meta["cache_age_seconds"] >= 0

        key = next(iter(client._cache._store))
        _expires_at, cached = client._cache._store[key]
        cached.stored_monotonic -= 3600
        aged = await client.fetch_symbols()
        assert aged.metadata["from_cache"] is True
        assert aged.metadata["cache_age_seconds"] >= 3599

        client._cache._store[key] = (0, cached)
        await asyncio.sleep(0.001)
        refetched = await client.fetch_symbols()
        assert refetched.metadata["from_cache"] is False
        assert refetched.metadata["source_fetched_at"] != first_meta["source_fetched_at"]
        assert route.call_count == 2
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


@respx.mock
async def test_fetch_company_reports_uses_normalized_path():
    route = respx.get(f"{BASE}/company/reports/HBL").mock(
        return_value=httpx.Response(200, text="reports")
    )
    client = PSXClient(backoff_base=0)
    try:
        assert await client.fetch_company_reports("hbl") == "reports"
        assert route.called
    finally:
        await client.close()


@respx.mock
async def test_fetch_announcements_posts_global_filters_and_raw_type():
    route = respx.post(f"{BASE}/announcements").mock(
        return_value=httpx.Response(200, text="announcements")
    )
    client = PSXClient(backoff_base=0)
    try:
        assert (
            await client.fetch_announcements(
                "hbl",
                count=20,
                offset=10,
                query="results",
                date_from="2026-01-01",
                date_to="2026-06-30",
                raw_type="C",
            )
            == "announcements"
        )
        body = route.calls.last.request.content.decode()
        assert "type=C" in body
        assert "symbol=HBL" in body
        assert "count=20" in body
        assert "offset=10" in body
        assert "query=results" in body
        assert "date_from=2026-01-01" in body
        assert "date_to=2026-06-30" in body
        assert "page=annc" in body
        assert route.calls.last.request.headers.get("x-requested-with") == "XMLHttpRequest"
    finally:
        await client.close()


@respx.mock
async def test_fetch_listing_table_uses_board_and_segment_path():
    route = respx.get(f"{BASE}/listings-table/main/dc").mock(
        return_value=httpx.Response(200, text="listing")
    )
    client = PSXClient(backoff_base=0)
    try:
        assert await client.fetch_listing_table("main", "dc") == "listing"
        assert route.called
    finally:
        await client.close()
