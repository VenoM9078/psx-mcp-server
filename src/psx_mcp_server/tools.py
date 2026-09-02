"""MCP tool definitions. Each tool composes the client + parsers, applies
limits so responses stay small in agent context, and lets PSXError propagate
(FastMCP surfaces the message text to the calling agent).

Docstrings are written for agent consumption: they state units (PKR, shares),
timezone (Pakistan Standard Time, UTC+5, no DST), and when to prefer a sibling
tool.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit

from mcp.server.fastmcp import FastMCP

from ._util import PKT, normalize_symbol
from .analytics import DEFAULT_WINDOWS, WINDOWS, calculate_price_performance
from .client import BASE_URL, PSXClient
from .errors import NoDataError, SymbolNotFoundError
from .models import CompanyAlerts, FinancialSection, Symbol, Tick
from .parsers.alerts import compliance_clauses, find_listing_status, parse_company_status
from .parsers.announcements import parse_global_announcements, sort_announcements
from .parsers.company import (
    parse_company_info,
    parse_payouts,
    parse_quote,
)
from .parsers.financials import parse_financials
from .parsers.historical import parse_historical
from .parsers.indices import parse_indices
from .parsers.market_watch import parse_market_watch
from .parsers.reports import (
    extract_report_period_year,
    filter_reports_by_year,
    parse_company_reports,
)
from .parsers.symbols import parse_symbols
from .parsers.timeseries import parse_eod_with_warnings, parse_intraday_with_warnings

_INTERVAL_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60}
_LISTING_SEGMENTS = (
    ("main", "nc"),
    ("main", "dc"),
    ("gem", "nc"),
    ("gem", "dc"),
)
_MAX_SEARCH_LIMIT = 100
_MAX_INTRADAY_LIMIT = 500
_MAX_EOD_LIMIT = 2_600
_MAX_QUERY_LENGTH = 200
_ANNOUNCEMENT_PAGE_SIZE = 50
_MAX_ANNOUNCEMENT_PAGES = 5
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACTIVE_NON_COMPLIANCE_TAGS = frozenset({"NON COMPLIANT"})
_ACTIVE_SUSPENSION_TAGS = frozenset({"SUSPENDED"})
_ACTIVE_WINDING_UP_TAGS = frozenset({"WINDING UP"})
_ACTIVE_RWA_TAGS = frozenset({"RWA", "RISK WARNING ALERT"})


def _bounded_limit(value: int, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _status_token(text: str) -> str:
    """Canonicalize a visible status tag for exact allow-list matching."""
    normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", text.strip().upper())
    return re.sub(r"[\s_-]+", " ", normalized).strip()


def _validated_date(value: str | None, *, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"{name} must be an ISO date in YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date in YYYY-MM-DD format") from exc
    return value


def _freshness(response: object) -> dict:
    metadata = getattr(response, "metadata", None)
    if not isinstance(metadata, dict):
        return {
            "source_fetched_at": None,
            "served_at": _now_iso(),
            "cache_age_seconds": None,
            "from_cache": False,
        }
    return {
        "source_fetched_at": metadata.get("source_fetched_at"),
        "served_at": metadata.get("served_at", _now_iso()),
        "cache_age_seconds": metadata.get("cache_age_seconds"),
        "from_cache": bool(metadata.get("from_cache", False)),
    }


def register_tools(mcp: FastMCP, client: PSXClient) -> None:
    async def _symbols() -> list[Symbol]:
        return parse_symbols(await client.fetch_symbols())

    async def _require_known(symbol: str) -> str:
        sym = normalize_symbol(symbol)
        if sym not in {s.symbol for s in await _symbols()}:
            raise SymbolNotFoundError(sym)
        return sym

    @mcp.tool()
    async def search_symbols(query: str, sector: str | None = None, limit: int = 20) -> dict:
        """Search PSX ticker symbols by symbol or company name.

        Use this FIRST whenever you are unsure of the exact ticker
        (e.g. query='Habib Bank' -> HBL). Optionally filter by exact sector name.
        Returns matches ranked with exact-symbol hits first.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be empty")
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError(f"query must be at most {_MAX_QUERY_LENGTH} characters")
        limit = _bounded_limit(limit, name="limit", maximum=_MAX_SEARCH_LIMIT)
        symbols_response = await client.fetch_symbols()
        available_symbols = parse_symbols(symbols_response)
        q = query.strip().lower()
        matches: list[tuple[int, Symbol]] = []
        for s in available_symbols:
            if sector and s.sector.lower() != sector.strip().lower():
                continue
            if q == s.symbol.lower():
                rank = 0
            elif s.symbol.lower().startswith(q):
                rank = 1
            elif q in s.symbol.lower() or q in s.name.lower():
                rank = 2
            else:
                continue
            matches.append((rank, s))
        matches.sort(key=lambda t: (t[0], t[1].symbol))
        total = len(matches)
        top = matches[:limit]
        freshness = _freshness(symbols_response)
        return {
            "count": len(top),
            "truncated": total > len(top),
            "source": f"{BASE_URL}/symbols",
            "fetched_at": freshness["served_at"],
            **freshness,
            "results": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "sector": s.sector,
                    "is_etf": s.is_etf,
                    "is_debt": s.is_debt,
                }
                for _, s in top
            ],
        }

    @mcp.tool()
    async def get_quote(symbol: str) -> dict:
        """Get the latest quote for a PSX equity or ETF.

        Returns current price, LDCP (last day close), open/high/low, change and
        change %, volume, bid/ask, 52-week range, and trailing P/E — all in PKR.
        Live during market hours (Mon-Fri ~09:30-15:30 Pakistan time, UTC+5);
        outside hours it reflects the last session. For an index use get_indices.
        """
        sym = await _require_known(symbol)
        company_response = await client.fetch_company(sym)
        quote = parse_quote(company_response)
        freshness = _freshness(company_response)
        warnings = _quote_warnings(
            quote.pe_ratio,
            current=quote.current,
            ldcp=quote.ldcp,
            change=quote.change,
            change_pct=quote.change_pct,
        )
        return {
            "symbol": sym,
            **quote.to_dict(),
            "pe_basis": "unconsolidated" if quote.pe_ratio is not None else "unknown",
            "source": f"{BASE_URL}/company/{sym}",
            "fetched_at": freshness["served_at"],
            **freshness,
            "source_timestamp": quote.as_of,
            "warnings": warnings,
        }

    @mcp.tool()
    async def get_intraday(
        symbol: str,
        interval: Literal["raw", "1min", "5min", "15min", "30min", "60min"] = "5min",
        limit: int = 50,
    ) -> dict:
        """Intraday price bars for the current/most recent trading session.

        Ticks are aggregated locally into OHLCV bars per interval; 'raw' returns
        individual ticks (can be thousands — keep limit small). Times are HH:MM in
        Pakistan Standard Time. Returns the newest `limit` bars.
        """
        limit = _bounded_limit(limit, name="limit", maximum=_MAX_INTRADAY_LIMIT)
        sym = normalize_symbol(symbol)
        response = await client.fetch_intraday(sym)
        ticks, parser_warnings = parse_intraday_with_warnings(response)
        if not ticks:
            raise NoDataError(
                f"No intraday data for {sym} right now. PSX trades "
                f"Mon-Fri ~09:30-15:30 Pakistan time (UTC+5); outside hours use get_quote "
                f"or get_eod_history."
            )
        freshness = _freshness(response)
        market_date = ticks[0].time.date().isoformat()
        if interval == "raw":
            rows = [
                {"time": t.time.strftime("%H:%M:%S"), "price": t.price, "volume": t.volume}
                for t in ticks[:limit]
            ]
            return {
                "symbol": sym,
                "interval": "raw",
                "count": len(rows),
                "truncated": len(ticks) > len(rows),
                "market_date": market_date,
                "source": f"{BASE_URL}/timeseries/int/{sym}",
                "fetched_at": freshness["served_at"],
                **freshness,
                "warnings": parser_warnings,
                "ticks": rows,
            }
        bars = _aggregate(ticks, _INTERVAL_MINUTES[interval])
        top = bars[:limit]
        return {
            "symbol": sym,
            "interval": interval,
            "count": len(top),
            "truncated": len(bars) > len(top),
            "market_date": market_date,
            "source": f"{BASE_URL}/timeseries/int/{sym}",
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": parser_warnings,
            "bars": top,
        }

    @mcp.tool()
    async def get_eod_history(
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 260,
    ) -> dict:
        """Daily end-of-day history (~5 years), newest first.

        Returns open, close and volume per day — this feed has NO high/low; for
        daily high/low use get_ohlc_history. Works for indices too (e.g.
        symbol='KSE100'). Dates are ISO (YYYY-MM-DD). ~260 rows is about one
        trading year. Optionally clip with start_date/end_date (ISO).
        """
        limit = _bounded_limit(limit, name="limit", maximum=_MAX_EOD_LIMIT)
        sym = normalize_symbol(symbol)
        start_date = _validated_date(start_date, name="start_date")
        end_date = _validated_date(end_date, name="end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        response = await client.fetch_eod(sym)
        bars, parser_warnings = parse_eod_with_warnings(response)
        if start_date:
            bars = [b for b in bars if b.date >= start_date]
        if end_date:
            bars = [b for b in bars if b.date <= end_date]
        if not bars:
            raise NoDataError(f"No EOD data for {sym} in the requested range.")
        top = bars[:limit]
        freshness = _freshness(response)
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": len(bars) > len(top),
            "source": f"{BASE_URL}/timeseries/eod/{sym}",
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": parser_warnings,
            "rows": [b.to_dict() for b in top],
        }

    @mcp.tool()
    async def get_ohlc_history(symbol: str, month: int, year: int) -> dict:
        """Full daily OHLCV for a single calendar month (has daily high/low).

        This is the only free source of daily high/low. Call once per month
        needed; for a long close-only series prefer get_eod_history (one call).
        `month` is 1-12. Prices in PKR.
        """
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if isinstance(year, bool) or not isinstance(year, int):
            raise ValueError("year must be an integer")
        now = datetime.now(PKT)
        if year < 2000 or year > 2100 or (year, month) > (now.year, now.month):
            raise ValueError("year/month must be between 2000 and the current month")
        sym = normalize_symbol(symbol)
        response = await client.fetch_historical(sym, month, year)
        bars = parse_historical(response)
        freshness = _freshness(response)
        return {
            "symbol": sym,
            "month": month,
            "year": year,
            "count": len(bars),
            "source": f"{BASE_URL}/historical",
            "fetched_at": freshness["served_at"],
            **freshness,
            "rows": [b.to_dict() for b in bars],
        }

    @mcp.tool()
    async def get_market_snapshot(
        category: Literal["gainers", "losers", "volume"] = "gainers",
        limit: int = 15,
        sector: str | None = None,
    ) -> dict:
        """Market-wide snapshot with top movers and a breadth summary.

        category: 'gainers' (top change %), 'losers' (bottom change %), or
        'volume' (most traded). Optionally filter to a sector (by name). Never
        returns all ~500 securities; raise `limit` (max 100) if needed.
        """
        limit = _bounded_limit(limit, name="limit", maximum=_MAX_SEARCH_LIMIT)
        market_response = await client.fetch_market_watch()
        symbols_response = await client.fetch_symbols()
        rows = parse_market_watch(market_response)
        sector_by_symbol = {s.symbol: s.sector for s in parse_symbols(symbols_response)}
        market_summary = _market_summary(rows)

        filtered_rows = rows
        if sector:
            want = sector.strip().lower()
            filtered_rows = [r for r in rows if sector_by_symbol.get(r.symbol, "").lower() == want]

        filtered_summary = _market_summary(filtered_rows)

        if category == "volume":
            filtered_rows.sort(key=lambda r: r.volume or 0, reverse=True)
        elif category == "losers":
            filtered_rows.sort(key=lambda r: r.change_pct if r.change_pct is not None else 0.0)
        else:
            filtered_rows.sort(
                key=lambda r: r.change_pct if r.change_pct is not None else 0.0,
                reverse=True,
            )

        top = filtered_rows[:limit]
        freshness = _freshness(market_response)
        return {
            "category": category,
            "market_summary": market_summary,
            "filtered_summary": filtered_summary,
            "summary_scope": f"sector:{sector}" if sector else "market",
            "count": len(top),
            "source": f"{BASE_URL}/market-watch",
            "fetched_at": freshness["served_at"],
            **freshness,
            "source_freshness": {
                "market_watch": _freshness(market_response),
                "symbols": _freshness(symbols_response),
            },
            "rows": [
                {
                    "symbol": r.symbol,
                    "sector": sector_by_symbol.get(r.symbol, r.sector),
                    "ldcp": r.ldcp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "current": r.current,
                    "change": r.change,
                    "change_pct": r.change_pct,
                    "volume": r.volume,
                }
                for r in top
            ],
        }

    @mcp.tool()
    async def get_indices() -> dict:
        """All PSX indices (KSE100, KSE30, KMI30, ALLSHR, and ~14 others).

        Returns current value, day high/low, change and change % for each. For
        historical index values call get_eod_history with the index name as the
        symbol (e.g. 'KSE100').
        """
        response = await client.fetch_indices()
        indices = parse_indices(response)
        freshness = _freshness(response)
        return {
            "count": len(indices),
            "indices": [i.to_dict() for i in indices],
            "source": f"{BASE_URL}/indices",
            "fetched_at": freshness["served_at"],
            **freshness,
        }

    @mcp.tool()
    async def get_company_info(symbol: str) -> dict:
        """Company profile and fundamentals.

        Returns business description, sector, market cap (PKR), shares
        outstanding, free float, and trailing P/E. For the current price use
        get_quote (this tool omits the live quote to stay focused).
        """
        sym = await _require_known(symbol)
        company_response = await client.fetch_company(sym)
        info = parse_company_info(company_response)
        freshness = _freshness(company_response)
        return {
            "symbol": sym,
            **info.to_dict(),
            "pe_basis": "unconsolidated" if info.pe_ratio is not None else "unknown",
            "source": f"{BASE_URL}/company/{sym}",
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": _quote_warnings(info.pe_ratio),
        }

    @mcp.tool()
    async def get_dividends(symbol: str, limit: int = 10) -> dict:
        """Dividend / payout history, newest first.

        Details use PSX notation, e.g. '60%(i) (D)' = 60% interim cash dividend,
        '(B)' = bonus shares, '(R)' = right shares. Includes the book-closure
        window. Percentages are preserved as source notation; face value is not
        assumed and cash DPS remains null when it cannot be established.
        """
        limit = _bounded_limit(limit, name="limit", maximum=100)
        sym = await _require_known(symbol)
        response = await client.fetch_payouts(sym)
        payouts = parse_payouts(response)
        top = payouts[:limit]
        warnings = _unique(warning for payout in top for warning in payout.warnings)
        freshness = _freshness(response)
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": len(payouts) > len(top),
            "source": f"{BASE_URL}/company/payouts",
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": warnings,
            "payouts": [p.to_dict() for p in top],
        }

    @mcp.tool()
    async def get_announcements(
        symbol: str,
        limit: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        query: str | None = None,
    ) -> dict:
        """Recent company announcements, globally sorted newest first.

        The source's raw announcement type is preserved when available.  PDF
        and image links are returned separately; no document is downloaded.
        """
        limit = _bounded_limit(limit, name="limit", maximum=100)
        date_from = _validated_date(date_from, name="date_from")
        date_to = _validated_date(date_to, name="date_to")
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must be on or before date_to")
        if query is not None and len(query) > _MAX_QUERY_LENGTH:
            raise ValueError(f"query must be at most {_MAX_QUERY_LENGTH} characters")
        sym = await _require_known(symbol)
        source = f"{BASE_URL}/announcements"
        all_announcements = []
        source_freshness = []
        total: int | None = None
        pagination_truncated = False
        for page_number in range(_MAX_ANNOUNCEMENT_PAGES):
            offset = page_number * _ANNOUNCEMENT_PAGE_SIZE
            response = await client.fetch_announcements(
                sym,
                count=_ANNOUNCEMENT_PAGE_SIZE,
                offset=offset,
                query=query or "",
                date_from=date_from or "",
                date_to=date_to or "",
            )
            source_freshness.append(_freshness(response))
            page_announcements, page_total = parse_global_announcements(
                response,
                source=source,
                raw_type="C",
            )
            if page_total is not None:
                total = page_total if total is None else max(total, page_total)
            all_announcements.extend(page_announcements)
            if not page_announcements:
                break
            matching_keys = {
                _announcement_key(item)
                for item in all_announcements
                if _matches_symbol(item.symbol, sym)
            }
            reached_end = len(page_announcements) < _ANNOUNCEMENT_PAGE_SIZE or (
                page_total is not None and offset + len(page_announcements) >= page_total
            )
            if reached_end:
                break
            if len(matching_keys) >= limit:
                pagination_truncated = True
                break
        else:
            pagination_truncated = True

        deduped = {}
        for announcement in all_announcements:
            if not _matches_symbol(announcement.symbol, sym):
                continue
            deduped.setdefault(_announcement_key(announcement), announcement)
        anns = sort_announcements(list(deduped.values()))
        top = anns[:limit]
        freshness = source_freshness[0] if source_freshness else _freshness(None)
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": pagination_truncated or len(anns) > len(top),
            "source": source,
            "fetched_at": freshness["served_at"],
            **freshness,
            "source_freshness": source_freshness,
            "warnings": (
                ["The raw PSX announcement type code is preserved as 'C'."]
                if anns
                else ["The PSX announcements source returned no parseable rows."]
            ),
            "announcements": [_announcement_dict(a) for a in top],
        }

    @mcp.tool()
    async def get_financials(
        symbol: str,
        view: Literal["summary", "ratios", "all"] = "all",
        annual_limit: int = 5,
        quarterly_limit: int = 8,
    ) -> dict:
        """Get structured company-page financial summaries and ratios.

        This is not a complete income statement, balance sheet, or cash-flow
        statement.  The page does not establish accounting basis or interim
        cumulative-versus-standalone semantics, so those values remain explicit
        warnings rather than assumptions.
        """
        annual_limit = _bounded_limit(annual_limit, name="annual_limit", maximum=10)
        quarterly_limit = _bounded_limit(quarterly_limit, name="quarterly_limit", maximum=20)
        if view not in ("summary", "ratios", "all"):
            raise ValueError("view must be one of: summary, ratios, all")

        sym = await _require_known(symbol)
        source = f"{BASE_URL}/company/{sym}"
        company_response = await client.fetch_company(sym)
        summary = parse_financials(company_response, source=source)
        freshness = _freshness(company_response)
        payload = {
            "symbol": sym,
            "annual": (
                _limited_financial_section(summary.annual, annual_limit)
                if view in ("summary", "all")
                else _empty_financial_section()
            ),
            "quarterly": (
                _limited_financial_section(summary.quarterly, quarterly_limit)
                if view in ("summary", "all")
                else _empty_financial_section()
            ),
            "ratios": (
                _limited_financial_facts(summary.ratios, annual_limit)
                if view in ("ratios", "all")
                else []
            ),
            "basis": summary.basis,
            "unit_note": summary.unit_note,
            "sources": summary.sources,
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": _unique(
                [
                    "This endpoint exposes PSX summary tables, not complete financial statements.",
                    *summary.warnings,
                ]
            ),
        }
        return payload

    @mcp.tool()
    async def get_company_reports(
        symbol: str,
        fiscal_year: int | None = None,
        limit: int = 20,
    ) -> dict:
        """Discover PSX annual and periodic report documents without parsing PDFs."""
        limit = _bounded_limit(limit, name="limit", maximum=100)
        if fiscal_year is not None and (
            isinstance(fiscal_year, bool)
            or not isinstance(fiscal_year, int)
            or not 2000 <= fiscal_year <= 2100
        ):
            raise ValueError("fiscal_year must be between 2000 and 2100")

        sym = await _require_known(symbol)
        source = f"{BASE_URL}/company/reports/{sym}"
        response = await client.fetch_company_reports(sym)
        reports = parse_company_reports(response, source=source)
        reports = filter_reports_by_year(reports, fiscal_year)
        reports.sort(key=_report_sort_key, reverse=True)
        top = reports[:limit]
        freshness = _freshness(response)
        warnings = []
        if not reports:
            warnings.append("No report metadata matched the requested symbol/filter.")
        warnings.append(
            "Report links identify documents; this tool does not download or parse PDFs."
        )
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": len(reports) > len(top),
            "reports": [
                {
                    **report.to_dict(),
                    "url": _absolute(report.url, base="https://financials.psx.com.pk/"),
                }
                for report in top
            ],
            "source": source,
            "fetched_at": freshness["served_at"],
            **freshness,
            "warnings": warnings,
        }

    @mcp.tool()
    async def get_company_alerts(symbol: str) -> dict:
        """Return current PSX listing and company-page compliance evidence.

        The generic hidden RWA modal is ignored unless company-specific active
        evidence is present.  Unknown states are retained as ``unknown``.
        """
        sym = await _require_known(symbol)
        company_source = f"{BASE_URL}/company/{sym}"
        warnings: list[str] = []
        sources = [company_source]
        source_freshness: dict[str, dict] = {}
        status_tags: list[dict] = []
        rwa_links = []
        company_available = True
        try:
            company_response = await client.fetch_company(sym)
            source_freshness["company"] = _freshness(company_response)
            status_tags, rwa_links = parse_company_status(
                company_response,
                source=company_source,
            )
        except Exception as exc:
            company_available = False
            warnings.append(
                f"Company page unavailable; company-derived alert states are unknown ({exc})."
            )

        listings = []
        successful_listing_sources = 0
        failed_listing_sources = 0
        for board, segment in _LISTING_SEGMENTS:
            source = f"{BASE_URL}/listings-table/{board}/{segment}"
            sources.append(source)
            try:
                listing_response = await client.fetch_listing_table(board, segment)
                source_freshness[f"{board}/{segment}"] = _freshness(listing_response)
                row = find_listing_status(
                    listing_response,
                    segment=f"{board}/{segment}",
                    symbol=sym,
                    source=source,
                )
                successful_listing_sources += 1
                if row is not None:
                    listings.append(row)
            except Exception as exc:
                failed_listing_sources += 1
                warnings.append(f"Listing source {board}/{segment} unavailable ({exc}).")

        dc_rows = [row for row in listings if row.segment.endswith("/dc")]
        status_tokens = {_status_token(tag["text"]) for tag in status_tags}
        has_non_compliant_tag = bool(status_tokens & _ACTIVE_NON_COMPLIANCE_TAGS)
        has_suspended_tag = bool(status_tokens & _ACTIVE_SUSPENSION_TAGS)
        has_winding_up_tag = bool(status_tokens & _ACTIVE_WINDING_UP_TAGS)

        if dc_rows or has_non_compliant_tag:
            non_compliance_state: bool | str = True
        elif listings and failed_listing_sources == 0:
            non_compliance_state = False
        else:
            non_compliance_state = "unknown"

        clauses = _unique(
            clause for row in dc_rows for clause in compliance_clauses(row.non_compliance)
        )
        compliance_evidence = [
            {
                "kind": "listing_segment",
                "label": row.segment,
                "raw_text": row.non_compliance,
                "url": row.source,
            }
            for row in dc_rows
        ]
        compliance_evidence.extend(
            {
                "kind": "company_status_tag",
                "label": "NON-COMPLIANT",
                "raw_text": tag["text"],
                "url": company_source,
            }
            for tag in status_tags
            if _status_token(tag["text"]) in _ACTIVE_NON_COMPLIANCE_TAGS
        )
        rwa_tag_evidence = [
            {
                "kind": "company_status_tag",
                "label": "RWA",
                "raw_text": tag["text"],
                "url": company_source,
            }
            for tag in status_tags
            if _status_token(tag["text"]) in _ACTIVE_RWA_TAGS
        ]

        rwa_evidence = [e.to_dict() for e in rwa_links]
        rwa_evidence.extend(rwa_tag_evidence)
        rwa_state: bool | str = True if rwa_evidence else "unknown"

        if has_suspended_tag:
            suspension_state: bool | str = True
        else:
            suspension_state = "unknown"
        if has_winding_up_tag:
            winding_up_state: bool | str = True
        else:
            winding_up_state = "unknown"

        warnings.extend(
            [
                "The generic hidden footer RWA modal is not treated as company-specific evidence.",
                "Current listing evidence does not establish historical alert resolution.",
            ]
        )
        if not company_available:
            warnings.append(
                "Suspension, winding-up, and RWA status could not use company-page evidence."
            )
        if successful_listing_sources == len(_LISTING_SEGMENTS) and not dc_rows:
            warnings.append(
                "All listing segments were fetched; no symbol-specific DC row was found."
            )
        if failed_listing_sources:
            warnings.append(
                "One or more listing segments failed; absence of a row is not treated "
                "as a negative state."
            )
        if non_compliance_state == "unknown":
            warnings.append(
                "Non-compliance is unknown because authoritative source coverage is incomplete."
            )
        if suspension_state == "unknown":
            warnings.append(
                "No affirmative current suspension evidence was found; state remains unknown."
            )
        if winding_up_state == "unknown":
            warnings.append(
                "No affirmative current winding-up evidence was found; state remains unknown."
            )
        if rwa_state == "unknown":
            warnings.append("No affirmative company-specific active RWA evidence was found.")
        elif not rwa_links:
            warnings.append(
                "RWA state is supported by a visible company status tag rather than "
                "an explicit RWA link."
            )

        alert = CompanyAlerts(
            symbol=sym,
            as_of=_now_iso(),
            listing_segment=listings[0].segment if listings else None,
            status_tags=status_tags,
            non_compliance={
                "state": non_compliance_state,
                "clauses": clauses,
                "raw_text": dc_rows[0].non_compliance if dc_rows else None,
                "evidence": compliance_evidence,
            },
            rwa={"state": rwa_state, "evidence": rwa_evidence},
            suspension={
                "state": suspension_state,
                "evidence": [
                    tag
                    for tag in status_tags
                    if _status_token(tag["text"]) in _ACTIVE_SUSPENSION_TAGS
                ],
            },
            winding_up={
                "state": winding_up_state,
                "evidence": [
                    tag
                    for tag in status_tags
                    if _status_token(tag["text"]) in _ACTIVE_WINDING_UP_TAGS
                ],
            },
            sources=sources,
            warnings=_unique(warnings),
        )
        payload = alert.to_dict()
        payload["listing_records"] = [row.to_dict() for row in listings]
        payload["source_freshness"] = source_freshness
        return payload

    @mcp.tool()
    async def get_price_performance(
        symbol: str,
        windows: list[Literal["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"]] | None = None,
        benchmark_symbol: str | None = "KSE100",
        include_volume: bool = True,
        include_volatility: bool = True,
        include_drawdown: bool = True,
    ) -> dict:
        """Calculate deterministic close-only price performance from EOD history."""
        if windows is None:
            requested_windows = list(DEFAULT_WINDOWS)
        elif not windows:
            raise ValueError("windows must be omitted or contain at least one supported window")
        else:
            requested_windows = list(dict.fromkeys(windows))
        invalid = [window for window in requested_windows if window not in WINDOWS]
        if invalid:
            raise ValueError(f"Unsupported windows: {', '.join(invalid)}")

        sym = await _require_known(symbol)
        stock_response = await client.fetch_eod(sym)
        bars, stock_warnings = parse_eod_with_warnings(stock_response)
        if not bars:
            raise NoDataError(f"No EOD data for {sym}.")

        benchmark_sym = normalize_symbol(benchmark_symbol) if benchmark_symbol else None
        benchmark_bars = None
        benchmark_response = None
        benchmark_warnings: list[str] = []
        if benchmark_sym and benchmark_sym != sym:
            try:
                benchmark_response = await client.fetch_eod(benchmark_sym)
                benchmark_bars, benchmark_warnings = parse_eod_with_warnings(benchmark_response)
            except Exception as exc:
                benchmark_bars = []
                benchmark_warnings.append(
                    f"Benchmark {benchmark_sym} was unavailable; benchmark analytics "
                    f"are unknown ({exc})."
                )
        elif benchmark_sym == sym:
            benchmark_bars = bars
            benchmark_response = stock_response

        calculated = calculate_price_performance(
            bars,
            windows=requested_windows,
            benchmark_bars=benchmark_bars,
            benchmark_symbol=benchmark_sym,
        )
        calculated["warnings"] = _unique(
            [*calculated["warnings"], *stock_warnings, *benchmark_warnings]
        )
        for result in calculated["windows"].values():
            if not include_volume:
                result.pop("average_daily_volume", None)
            if not include_volatility:
                result.pop("volatility_pct", None)
            if not include_drawdown:
                result.pop("max_drawdown_pct", None)

        sources = [f"{BASE_URL}/timeseries/eod/{sym}"]
        if benchmark_sym and benchmark_sym != sym:
            sources.append(f"{BASE_URL}/timeseries/eod/{benchmark_sym}")
        freshness = _freshness(stock_response)
        return {
            "symbol": sym,
            **calculated,
            "source": sources,
            "fetched_at": freshness["served_at"],
            **freshness,
            "source_freshness": {
                "stock": freshness,
                "benchmark": _freshness(benchmark_response) if benchmark_response else None,
            },
            "methodology": {
                "returns": (
                    "Close-to-close; 1D uses the previous available trading close, 1W uses a "
                    "7-calendar-day target, 1M/3M/6M use calendar-month arithmetic, and "
                    "1Y/3Y/5Y use calendar-year arithmetic. A missing prior close falls back "
                    "to the first available row and marks coverage partial."
                ),
                "ytd": (
                    "YTD starts from the final available trading close on or before the prior "
                    "calendar year-end and ends at the latest close."
                ),
                "volatility": (
                    "Sample standard deviation of close-to-close returns, annualized by sqrt(252)."
                ),
                "drawdown": (
                    "Maximum close-to-close drawdown using closing prices only; "
                    "losses are negative."
                ),
                "benchmark_alignment": (
                    "Relative return is reported only when stock and benchmark actual_start and "
                    "actual_end match exactly; no interpolation is performed."
                ),
                "dividend_adjusted": False,
                "price_basis": "The EOD source does not specify a price basis.",
                "split_adjustment": "Source-dependent; no explicit EOD adjustment flag was found.",
            },
        }


def _absolute(url: str | None, *, base: str = f"{BASE_URL}/") -> str | None:
    if not url:
        return None
    try:
        candidate = urljoin(base, url.strip())
        parsed = urlsplit(candidate)
    except (AttributeError, ValueError):
        return None
    known_hosts = {
        "dps.psx.com.pk",
        "financials.psx.com.pk",
        "psx.com.pk",
        "www.psx.com.pk",
    }
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in known_hosts:
        return None
    return candidate


def _now_iso() -> str:
    return datetime.now(PKT).isoformat()


def _quote_warnings(
    pe_ratio: float | None,
    *,
    current: float | None = None,
    ldcp: float | None = None,
    change: float | None = None,
    change_pct: float | None = None,
) -> list[str]:
    warnings = []
    if pe_ratio is not None:
        warnings.append(
            "PSX labels this P/E Ratio (TTM) as based on unconsolidated financials; "
            "it is not a consolidated P/E."
        )
    if current is None or ldcp is None:
        return warnings

    expected_change = round(current - ldcp, 2)
    if change is not None and abs(expected_change - change) > 0.05:
        warnings.append(
            "The signed PSX change differs materially from current minus LDCP; "
            "the source value was preserved."
        )
    if change_pct is not None and ldcp != 0:
        expected_pct = round((current - ldcp) / ldcp * 100, 2)
        if abs(expected_pct - change_pct) > 0.10:
            warnings.append(
                "The signed PSX change percentage differs materially from the "
                "current/LDCP arithmetic check; the source value was preserved."
            )
    return warnings


def _announcement_dict(announcement) -> dict:
    return {
        "date": announcement.date,
        "time": announcement.time,
        "symbol": announcement.symbol,
        "title": announcement.title,
        "category": announcement.category,
        "raw_type": announcement.raw_type,
        "url": _absolute(announcement.pdf_url),
        "image_url": _absolute(announcement.image_url),
        "source": announcement.source,
    }


def _matches_symbol(raw_symbol: str | None, requested_symbol: str) -> bool:
    if not raw_symbol or not raw_symbol.strip():
        return False
    try:
        return normalize_symbol(raw_symbol) == requested_symbol
    except ValueError:
        return False


def _announcement_key(announcement) -> tuple:
    return (
        normalize_symbol(announcement.symbol),
        announcement.date,
        announcement.time,
        announcement.title.strip(),
        announcement.pdf_url,
        announcement.image_url,
    )


def _limited_financial_section(section: FinancialSection, limit: int) -> dict:
    periods = section.periods[:limit]
    labels = {period.raw_label for period in periods}
    return {
        "periods": [period.to_dict() for period in periods],
        "facts": [fact.to_dict() for fact in section.facts if fact.period in labels],
        "warnings": section.warnings,
    }


def _empty_financial_section() -> dict:
    return {"periods": [], "facts": []}


def _limited_financial_facts(facts: list, limit: int) -> list[dict]:
    labels = list(dict.fromkeys(fact.period for fact in facts))[:limit]
    selected = set(labels)
    return [fact.to_dict() for fact in facts if fact.period in selected]


def _report_sort_key(report) -> tuple[int, str]:
    if not report.period_ended:
        return (0, "")
    return (extract_report_period_year(report.period_ended) or 0, report.period_ended)


def _market_summary(rows: list) -> dict:
    known_changes = [row.change_pct for row in rows if row.change_pct is not None]
    return {
        "securities": len(rows),
        "advancers": sum(change > 0 for change in known_changes),
        "decliners": sum(change < 0 for change in known_changes),
        "unchanged": sum(change == 0 for change in known_changes),
        "unknown_change": len(rows) - len(known_changes),
        "total_volume": sum(row.volume for row in rows if row.volume is not None),
        "unknown_volume": sum(row.volume is None for row in rows),
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _aggregate(ticks: list[Tick], minutes: int) -> list[dict]:
    """Aggregate newest-first ticks into OHLCV bars, returned newest first."""
    buckets: dict[datetime, list[Tick]] = {}
    for t in ticks:
        floored = t.time.replace(
            minute=(t.time.minute // minutes) * minutes, second=0, microsecond=0
        )
        buckets.setdefault(floored, []).append(t)
    bars: list[dict] = []
    for key in sorted(buckets, reverse=True):
        group = sorted(buckets[key], key=lambda t: t.time)  # oldest -> newest within bar
        prices = [t.price for t in group]
        bars.append(
            {
                "time": key.strftime("%H:%M"),
                "open": group[0].price,
                "high": max(prices),
                "low": min(prices),
                "close": group[-1].price,
                "volume": sum(t.volume for t in group),
            }
        )
    return bars
