"""MCP tool definitions. Each tool composes the client + parsers, applies
limits so responses stay small in agent context, and lets PSXError propagate
(FastMCP surfaces the message text to the calling agent).

Docstrings are written for agent consumption: they state units (PKR, shares),
timezone (Pakistan Standard Time, UTC+5, no DST), and when to prefer a sibling
tool.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ._util import normalize_symbol
from .client import BASE_URL, PSXClient
from .errors import NoDataError, SymbolNotFoundError
from .models import Symbol, Tick
from .parsers.company import (
    parse_announcements,
    parse_company_info,
    parse_payouts,
    parse_quote,
)
from .parsers.historical import parse_historical
from .parsers.indices import parse_indices
from .parsers.market_watch import parse_market_watch
from .parsers.symbols import parse_symbols
from .parsers.timeseries import parse_eod, parse_intraday

_INTERVAL_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60}


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
        q = query.strip().lower()
        matches: list[tuple[int, Symbol]] = []
        for s in await _symbols():
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
        top = matches[: max(1, limit)]
        return {
            "count": len(top),
            "truncated": total > len(top),
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
        quote = parse_quote(await client.fetch_company(sym))
        return {"symbol": sym, **quote.to_dict()}

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
        ticks = parse_intraday(await client.fetch_intraday(symbol))
        if not ticks:
            raise NoDataError(
                f"No intraday data for {normalize_symbol(symbol)} right now. PSX trades "
                f"Mon-Fri ~09:30-15:30 Pakistan time (UTC+5); outside hours use get_quote "
                f"or get_eod_history."
            )
        sym = normalize_symbol(symbol)
        market_date = ticks[0].time.date().isoformat()
        if interval == "raw":
            rows = [
                {"time": t.time.strftime("%H:%M:%S"), "price": t.price, "volume": t.volume}
                for t in ticks[: max(1, limit)]
            ]
            return {
                "symbol": sym,
                "interval": "raw",
                "count": len(rows),
                "truncated": len(ticks) > len(rows),
                "market_date": market_date,
                "ticks": rows,
            }
        bars = _aggregate(ticks, _INTERVAL_MINUTES[interval])
        top = bars[: max(1, limit)]
        return {
            "symbol": sym,
            "interval": interval,
            "count": len(top),
            "truncated": len(bars) > len(top),
            "market_date": market_date,
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
        bars = parse_eod(await client.fetch_eod(symbol))
        if start_date:
            bars = [b for b in bars if b.date >= start_date]
        if end_date:
            bars = [b for b in bars if b.date <= end_date]
        if not bars:
            raise NoDataError(f"No EOD data for {normalize_symbol(symbol)} in the requested range.")
        top = bars[: max(1, limit)]
        return {
            "symbol": normalize_symbol(symbol),
            "count": len(top),
            "truncated": len(bars) > len(top),
            "rows": [b.to_dict() for b in top],
        }

    @mcp.tool()
    async def get_ohlc_history(symbol: str, month: int, year: int) -> dict:
        """Full daily OHLCV for a single calendar month (has daily high/low).

        This is the only free source of daily high/low. Call once per month
        needed; for a long close-only series prefer get_eod_history (one call).
        `month` is 1-12. Prices in PKR.
        """
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        now = datetime.now()
        if year < 2000 or (year, month) > (now.year, now.month):
            raise ValueError("year/month must be between 2000 and the current month")
        bars = parse_historical(await client.fetch_historical(symbol, month, year))
        return {
            "symbol": normalize_symbol(symbol),
            "month": month,
            "year": year,
            "count": len(bars),
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
        rows = parse_market_watch(await client.fetch_market_watch())
        sector_by_symbol = {s.symbol: s.sector for s in await _symbols()}

        summary = {
            "securities": len(rows),
            "advancers": sum(1 for r in rows if (r.change_pct or 0) > 0),
            "decliners": sum(1 for r in rows if (r.change_pct or 0) < 0),
            "unchanged": sum(1 for r in rows if (r.change_pct or 0) == 0),
            "total_volume": sum(r.volume or 0 for r in rows),
        }

        if sector:
            want = sector.strip().lower()
            rows = [r for r in rows if sector_by_symbol.get(r.symbol, "").lower() == want]

        if category == "volume":
            rows.sort(key=lambda r: r.volume or 0, reverse=True)
        elif category == "losers":
            rows.sort(key=lambda r: r.change_pct if r.change_pct is not None else 0.0)
        else:
            rows.sort(key=lambda r: r.change_pct if r.change_pct is not None else 0.0, reverse=True)

        top = rows[: min(max(1, limit), 100)]
        return {
            "category": category,
            "market_summary": summary,
            "count": len(top),
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
        indices = parse_indices(await client.fetch_indices())
        return {"count": len(indices), "indices": [i.to_dict() for i in indices]}

    @mcp.tool()
    async def get_company_info(symbol: str) -> dict:
        """Company profile and fundamentals.

        Returns business description, sector, market cap (PKR), shares
        outstanding, free float, and trailing P/E. For the current price use
        get_quote (this tool omits the live quote to stay focused).
        """
        sym = await _require_known(symbol)
        info = parse_company_info(await client.fetch_company(sym))
        return {"symbol": sym, **info.to_dict()}

    @mcp.tool()
    async def get_dividends(symbol: str, limit: int = 10) -> dict:
        """Dividend / payout history, newest first.

        Details use PSX notation, e.g. '60%(i) (D)' = 60% interim cash dividend,
        '(B)' = bonus shares, '(R)' = right shares. Includes the book-closure
        window. Percentages are of face value (PKR 10 for most PSX stocks).
        """
        sym = await _require_known(symbol)
        payouts = parse_payouts(await client.fetch_payouts(sym))
        top = payouts[: max(1, limit)]
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": len(payouts) > len(top),
            "payouts": [p.to_dict() for p in top],
        }

    @mcp.tool()
    async def get_announcements(symbol: str, limit: int = 10) -> dict:
        """Recent corporate announcements, newest first.

        Each item has a date, title, and a link to the PSX document (PDF) when
        available.
        """
        sym = await _require_known(symbol)
        anns = parse_announcements(await client.fetch_company(sym))
        top = anns[: max(1, limit)]
        return {
            "symbol": sym,
            "count": len(top),
            "truncated": len(anns) > len(top),
            "announcements": [
                {
                    "date": a.date,
                    "title": a.title,
                    "url": _absolute(a.pdf_url),
                }
                for a in top
            ],
        }


def _absolute(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else f"{BASE_URL}{url}"


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
