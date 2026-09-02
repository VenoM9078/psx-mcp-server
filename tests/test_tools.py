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
from psx_mcp_server.tools import _absolute, register_tools

BASE = "https://dps.psx.com.pk"


def _mock_all_endpoints(router) -> None:
    router.get(f"{BASE}/symbols").mock(
        return_value=httpx.Response(200, text=load_fixture("symbols.json"))
    )
    router.get(f"{BASE}/company/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("company_HBL.html"))
    )
    router.get(f"{BASE}/company/LUCK").mock(
        return_value=httpx.Response(200, text=load_fixture("company_LUCK.html"))
    )
    router.get(f"{BASE}/company/SYS").mock(
        return_value=httpx.Response(200, text=load_fixture("company_SYS.html"))
    )
    router.get(f"{BASE}/company/AIRLINK").mock(
        return_value=httpx.Response(200, text=load_fixture("company_AIRLINK.html"))
    )
    router.get(f"{BASE}/company/reports/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("reports_HBL.html"))
    )
    router.post(f"{BASE}/company/payouts").mock(
        return_value=httpx.Response(200, text=load_fixture("payouts_HBL.html"))
    )
    router.post(f"{BASE}/announcements").mock(
        return_value=httpx.Response(200, text=load_fixture("announcements_HBL.html"))
    )
    router.get(f"{BASE}/timeseries/int/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("timeseries_int_HBL.json"))
    )
    router.get(f"{BASE}/timeseries/eod/HBL").mock(
        return_value=httpx.Response(200, text=load_fixture("timeseries_eod_HBL.json"))
    )
    router.get(f"{BASE}/timeseries/eod/KSE100").mock(
        return_value=httpx.Response(200, text=load_fixture("timeseries_eod_KSE100.json"))
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
    router.get(f"{BASE}/listings-table/main/nc").mock(
        return_value=httpx.Response(200, text=load_fixture("listing_main_nc.html"))
    )
    router.get(f"{BASE}/listings-table/main/dc").mock(
        return_value=httpx.Response(200, text=load_fixture("listing_main_dc.html"))
    )
    router.get(f"{BASE}/listings-table/gem/nc").mock(
        return_value=httpx.Response(200, text=load_fixture("listing_empty.html"))
    )
    router.get(f"{BASE}/listings-table/gem/dc").mock(
        return_value=httpx.Response(200, text=load_fixture("listing_empty.html"))
    )


@contextlib.asynccontextmanager
async def build_session(configure=None):
    """A connected in-memory session against a fully-mocked PSX backend."""
    with respx.mock(assert_all_called=False) as router:
        _mock_all_endpoints(router)
        if configure:
            configure(router)
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
        assert data["pe_basis"] == "unconsolidated"
        assert data["source"] == f"{BASE}/company/HBL"
        assert data["fetched_at"]
        assert any("unconsolidated" in warning for warning in data["warnings"])


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
        assert data["filtered_summary"] == data["market_summary"]


async def test_get_market_snapshot_sector_summary_matches_filtered_scope():
    async with build_session() as s:
        data = await call(
            s,
            "get_market_snapshot",
            category="volume",
            sector="COMMERCIAL BANKS",
            limit=100,
        )
        assert data["summary_scope"] == "sector:COMMERCIAL BANKS"
        assert data["filtered_summary"]["securities"] <= data["market_summary"]["securities"]
        assert data["filtered_summary"]["unknown_change"] >= 0


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
        assert data["payouts"][0]["action_type"] == "cash"
        assert data["payouts"][0]["cash_dividend_per_share"] is None
        assert data["warnings"]


async def test_get_announcements():
    async with build_session() as s:
        data = await call(s, "get_announcements", symbol="HBL", limit=4)
        assert data["count"] == 4
        assert (data["announcements"][0]["date"], data["announcements"][0]["time"]) == (
            "2026-06-17",
            "8:00 AM",
        )
        assert data["announcements"][0]["image_url"].endswith("/3.gif")
        assert any(item["url"] and item["url"].endswith(".pdf") for item in data["announcements"])
        assert all(item["raw_type"] == "C" for item in data["announcements"])


async def test_get_financials_handles_industrial_and_technology_row_sets():
    async with build_session() as s:
        luck = await call(s, "get_financials", symbol="LUCK", view="all")
        sys = await call(s, "get_financials", symbol="SYS", view="all")

        assert luck["symbol"] == "LUCK"
        assert luck["basis"] == "unknown"
        assert any(fact["metric"] == "sales" for fact in luck["annual"]["facts"])
        assert any(fact["unit_scale"] == 1000 for fact in luck["annual"]["facts"])
        assert any(
            fact["metric"] == "eps" and fact["unit_scale"] == 1 for fact in luck["annual"]["facts"]
        )
        assert sys["annual"]["facts"][0]["metric"] == "eps"
        assert not any(fact["metric"] == "profit_after_tax" for fact in sys["quarterly"]["facts"])
        assert any("not complete financial statements" in warning for warning in luck["warnings"])


async def test_get_company_reports_filters_without_reading_documents():
    async with build_session() as s:
        data = await call(s, "get_company_reports", symbol="HBL", fiscal_year=2025, limit=1)

        assert data["count"] == 1
        assert data["truncated"] is True
        assert data["reports"][0]["period_ended"].startswith("2025")
        assert data["reports"][0]["url"].startswith("https://financials.psx.com.pk/")
        assert any("does not download or parse PDFs" in warning for warning in data["warnings"])


async def test_get_company_alerts_does_not_promote_generic_hidden_rwa_modal():
    async with build_session() as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

        assert data["listing_segment"] == "main/nc"
        assert data["non_compliance"]["state"] is False
        assert data["rwa"]["state"] == "unknown"
        assert data["suspension"]["state"] == "unknown"
        assert data["winding_up"]["state"] == "unknown"
        assert data["rwa"]["evidence"] == []
        assert data["listing_records"][0]["symbol"] == "AIRLINK"
        assert any("hidden footer RWA modal" in warning for warning in data["warnings"])


async def test_get_price_performance_uses_eod_and_benchmark():
    async with build_session() as s:
        data = await call(
            s,
            "get_price_performance",
            symbol="HBL",
            windows=["1D"],
            benchmark_symbol="KSE100",
            include_volume=False,
        )

        result = data["windows"]["1D"]
        assert result["return_pct"] is not None
        assert "average_daily_volume" not in result
        assert data["benchmark"]["symbol"] == "KSE100"
        assert "relative_return_pct" in result
        assert data["methodology"]["dividend_adjusted"] is False


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


async def test_dc_listing_does_not_make_rwa_true():
    async with build_session() as s:
        data = await call(s, "get_company_alerts", symbol="AAL")

    assert data["non_compliance"]["state"] is True
    assert data["rwa"]["state"] == "unknown"
    assert data["suspension"]["state"] == "unknown"
    assert data["winding_up"]["state"] == "unknown"


async def test_visible_explicit_rwa_link_is_affirmative():
    def configure(router):
        router.get(f"{BASE}/company/AIRLINK").mock(
            return_value=httpx.Response(200, text=load_fixture("company_alert_rwa.html"))
        )

    async with build_session(configure) as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

    assert data["rwa"]["state"] is True
    assert data["rwa"]["evidence"][0]["kind"] == "active_rwa_link"


def _company_status_tag_html(tag_text: str) -> str:
    return (
        '<div class="company__quote"><div class="quote__name">Example Company</div>'
        f'<div class="tag">{tag_text}</div></div>'
    )


@pytest.mark.parametrize(
    "tag_text",
    [
        "NO RWA",
        "NOT SUSPENDED",
        "NOT SUSPENDED FROM TRADING",
        "NON-COMPLIANT RESOLVED",
        "NON COMPLIANT RESOLVED",
        "RWA RESOLVED",
        "RISK WARNING ALERT RESOLVED",
        "WINDING-UP RESOLVED",
        "NOT WINDING-UP",
    ],
)
async def test_negative_status_tags_do_not_create_affirmative_alerts(tag_text):
    def configure(router):
        router.get(f"{BASE}/company/AIRLINK").mock(
            return_value=httpx.Response(200, text=_company_status_tag_html(tag_text))
        )

    async with build_session(configure) as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

    assert data["non_compliance"]["state"] is False
    assert data["rwa"]["state"] == "unknown"
    assert data["suspension"]["state"] == "unknown"
    assert data["winding_up"]["state"] == "unknown"


@pytest.mark.parametrize(
    ("tag_text", "field"),
    [
        ("SUSPENDED", "suspension"),
        ("WINDING-UP", "winding_up"),
        ("RWA", "rwa"),
        ("NON-COMPLIANT", "non_compliance"),
    ],
)
async def test_active_status_tags_remain_affirmative(tag_text, field):
    def configure(router):
        router.get(f"{BASE}/company/AIRLINK").mock(
            return_value=httpx.Response(200, text=_company_status_tag_html(tag_text))
        )

    async with build_session(configure) as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

    assert data[field]["state"] is True


@pytest.mark.parametrize(
    "failed_path",
    [
        "/listings-table/main/nc",
        "/listings-table/main/dc",
        "/listings-table/gem/nc",
        "/listings-table/gem/dc",
    ],
)
async def test_company_alerts_preserve_partial_listing_results(failed_path):
    def configure(router):
        router.get(f"{BASE}{failed_path}").mock(side_effect=httpx.ReadTimeout("broken"))

    async with build_session(configure) as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

    assert data["symbol"] == "AIRLINK"
    assert data["rwa"]["state"] == "unknown"
    assert data["suspension"]["state"] == "unknown"
    assert data["winding_up"]["state"] == "unknown"
    assert any(failed_path in warning for warning in data["warnings"])
    assert data["non_compliance"]["state"] == "unknown"


async def test_company_alerts_survive_company_page_failure():
    def configure(router):
        router.get(f"{BASE}/company/AIRLINK").mock(side_effect=httpx.ReadTimeout("broken"))

    async with build_session(configure) as s:
        data = await call(s, "get_company_alerts", symbol="AIRLINK")

    assert data["listing_records"][0]["symbol"] == "AIRLINK"
    assert data["non_compliance"]["state"] is False
    assert data["rwa"]["state"] == "unknown"
    assert data["suspension"]["state"] == "unknown"
    assert data["winding_up"]["state"] == "unknown"
    assert any("Company page unavailable" in warning for warning in data["warnings"])


def _announcement_page(rows, total):
    body = "".join(
        f"<tr><td>{date}</td><td>{time}</td><td>{symbol}</td><td></td><td>{title}</td>"
        f"<td>{link}</td></tr>"
        for date, time, symbol, title, link in rows
    )
    return (
        f'<div class="announcementsResults__header">Showing 1 to {len(rows)} of {total} '
        "entries</div>"
        '<table id="announcementsTable"><thead><tr><th>Date</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


async def test_announcements_merge_pages_filter_exact_symbol_and_deduplicate():
    page_one_rows = [
        ("2026-01-01", "09:00", "HBL", "Older", '<a href="/download/document/old.pdf">PDF</a>'),
        ("2026-01-01", "09:01", "", "Global", ""),
        ("2026-01-01", "09:02", "UBL", "Other", ""),
    ] + [("2026-01-01", "09:03", "ZZZ", f"Noise {index}", "") for index in range(47)]
    page_two_rows = [
        ("2026-01-01", "09:00", "HBL", "Older", '<a href="/download/document/old.pdf">PDF</a>'),
        ("2026-01-01", "09:00", "HBL", "Newer", '<a href="/download/document/new.pdf?x=1">PDF</a>'),
        ("2026-01-01", "09:05", "", "Global two", ""),
        ("2026-01-01", "09:06", "UBL", "Other two", ""),
    ]

    def configure(router):
        router.post(f"{BASE}/announcements").mock(
            side_effect=[
                httpx.Response(200, text=_announcement_page(page_one_rows, 54)),
                httpx.Response(200, text=_announcement_page(page_two_rows, 54)),
            ]
        )

    async with build_session(configure) as s:
        data = await call(s, "get_announcements", symbol="HBL", limit=2)

    assert data["count"] == 2
    assert [item["title"] for item in data["announcements"]] == ["Older", "Newer"]
    assert all(item["symbol"] == "HBL" for item in data["announcements"])
    assert next(item for item in data["announcements"] if item["title"] == "Newer")["url"].endswith(
        "new.pdf?x=1"
    )
    assert data["truncated"] is False


async def test_announcements_empty_second_page_is_not_truncated():
    page_one_rows = [
        ("2026-01-01", "09:00", "HBL", "Only row", ""),
    ] + [("2026-01-01", "09:03", "ZZZ", f"Noise {index}", "") for index in range(49)]

    def configure(router):
        router.post(f"{BASE}/announcements").mock(
            side_effect=[
                httpx.Response(200, text=_announcement_page(page_one_rows, 51)),
                httpx.Response(200, text=_announcement_page([], 51)),
            ]
        )

    async with build_session(configure) as s:
        data = await call(s, "get_announcements", symbol="HBL", limit=10)

    assert [item["title"] for item in data["announcements"]] == ["Only row"]
    assert data["truncated"] is False


async def test_announcements_continue_past_cross_page_duplicate_until_unique_limit():
    page_one_rows = [("2026-01-01", "09:00", "HBL", "Same", "")] + [
        ("2026-01-01", "09:03", "ZZZ", f"Noise one {index}", "") for index in range(49)
    ]
    page_two_rows = [("2026-01-01", "09:00", "HBL", "Same", "")] + [
        ("2026-01-01", "09:04", "ZZZ", f"Noise two {index}", "") for index in range(49)
    ]
    page_three_rows = [("2026-01-01", "09:01", "HBL", "Unique", "")]

    def configure(router):
        router.post(f"{BASE}/announcements").mock(
            side_effect=[
                httpx.Response(200, text=_announcement_page(page_one_rows, 151)),
                httpx.Response(200, text=_announcement_page(page_two_rows, 151)),
                httpx.Response(200, text=_announcement_page(page_three_rows, 151)),
            ]
        )

    async with build_session(configure) as s:
        data = await call(s, "get_announcements", symbol="HBL", limit=2)

    assert data["count"] == 2
    assert {item["title"] for item in data["announcements"]} == {"Same", "Unique"}
    assert data["truncated"] is False


async def test_price_performance_keeps_stock_when_benchmark_fails():
    def configure(router):
        router.get(f"{BASE}/timeseries/eod/KSE100").mock(return_value=httpx.Response(404))

    async with build_session(configure) as s:
        data = await call(
            s,
            "get_price_performance",
            symbol="HBL",
            windows=["1D"],
            benchmark_symbol="KSE100",
        )

    assert data["windows"]["1D"]["return_pct"] is not None
    assert data["windows"]["1D"]["relative_return_pct"] is None
    assert data["benchmark"]["windows"]["1D"]["alignment"] == "unavailable"
    assert any("benchmark" in warning.lower() for warning in data["warnings"])


async def test_price_performance_same_symbol_is_deterministically_zero_relative_return():
    async with build_session() as s:
        data = await call(
            s,
            "get_price_performance",
            symbol="HBL",
            windows=["1D"],
            benchmark_symbol="HBL",
        )

    assert data["windows"]["1D"]["relative_return_pct"] == 0.0
    assert data["benchmark"]["windows"]["1D"]["alignment"] == "matched"


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_eod_history", {"symbol": "HBL", "limit": 0}),
        ("get_eod_history", {"symbol": "HBL", "limit": -5}),
        ("get_eod_history", {"symbol": "HBL", "limit": 99999}),
        ("get_eod_history", {"symbol": "HBL", "start_date": "banana"}),
        (
            "get_eod_history",
            {"symbol": "HBL", "start_date": "2026-06-30", "end_date": "2026-06-01"},
        ),
        ("get_company_reports", {"symbol": "HBL", "fiscal_year": 99999}),
        ("get_quote", {"symbol": "../../etc/passwd"}),
        ("get_price_performance", {"symbol": "HBL", "windows": []}),
        ("search_symbols", {"query": "x" * 201}),
    ],
)
async def test_tools_reject_invalid_inputs(name, args):
    async with build_session() as s:
        result = await s.call_tool(name, args)
    assert result.isError is True


def test_report_urls_are_joined_and_restricted_to_known_hosts():
    assert _absolute("/lib/DownloadPDF.php?id=1", base="https://financials.psx.com.pk/") == (
        "https://financials.psx.com.pk/lib/DownloadPDF.php?id=1"
    )
    assert _absolute("lib/DownloadPDF.php?id=1", base="https://financials.psx.com.pk/") == (
        "https://financials.psx.com.pk/lib/DownloadPDF.php?id=1"
    )
    assert _absolute("https://financials.psx.com.pk/lib/DownloadPDF.php?id=1")
    assert _absolute("//financials.psx.com.pk/lib/DownloadPDF.php?id=1")
    assert _absolute("javascript:alert(1)") is None
    assert _absolute("https://example.com/report.pdf") is None
