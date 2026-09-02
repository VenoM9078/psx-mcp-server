"""Async HTTP client for the PSX Data Portal.

Owns all network I/O: URLs, an identifying User-Agent, per-endpoint TTL caching,
and retry/backoff with error mapping. Returns raw response text — parsing lives
in parsers/, so this layer stays free of markup knowledge.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from time import monotonic

import httpx

from . import __version__
from ._util import PKT, normalize_symbol
from .cache import TTLCache
from .errors import PSXUnavailableError

BASE_URL = "https://dps.psx.com.pk"

# Per-endpoint cache lifetimes (seconds). Intraday moves fast; the symbol
# directory barely changes day to day.
TTL_INTRADAY = 30
TTL_MARKET = 60
TTL_INDICES = 60
TTL_COMPANY = 300
TTL_PAYOUTS = 300
TTL_EOD = 3600
TTL_SYMBOLS = 86400
TTL_HISTORICAL_PAST = 86400
TTL_HISTORICAL_CURRENT = 3600
TTL_REPORTS = 86400
TTL_ANNOUNCEMENTS = 900
TTL_LISTINGS = 900

_DEFAULT_UA = f"psx-mcp-server/{__version__} (+https://github.com/ahmedraza-96/psx-mcp-server)"
MAX_RESPONSE_BYTES = 5_000_000

# httpx exceptions worth a retry (transient transport failures).
_RETRYABLE_EXC = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


class FetchedText(str):
    """Response text that carries source/cache freshness without breaking str APIs."""

    def __new__(cls, value: str, metadata: dict) -> FetchedText:
        instance = super().__new__(cls, value)
        instance.metadata = metadata
        return instance


class _CachedPayload:
    def __init__(self, text: str, source_fetched_at: str) -> None:
        self.text = text
        self.source_fetched_at = source_fetched_at
        self.stored_monotonic = monotonic()


class PSXClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        user_agent: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout: float = 15.0,
        max_concurrent_requests: int = 8,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        ua = user_agent or os.environ.get("PSX_MCP_USER_AGENT") or _DEFAULT_UA
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": ua, "Accept": "text/html,application/json"},
        )
        self._cache = TTLCache()

    async def close(self) -> None:
        await self._client.aclose()

    # -- endpoint methods (return raw text) --------------------------------

    async def fetch_symbols(self) -> str:
        return await self._get("/symbols", TTL_SYMBOLS)

    async def fetch_intraday(self, symbol: str) -> str:
        return await self._get(f"/timeseries/int/{normalize_symbol(symbol)}", TTL_INTRADAY)

    async def fetch_eod(self, symbol: str) -> str:
        return await self._get(f"/timeseries/eod/{normalize_symbol(symbol)}", TTL_EOD)

    async def fetch_company(self, symbol: str) -> str:
        return await self._get(f"/company/{normalize_symbol(symbol)}", TTL_COMPANY)

    async def fetch_company_reports(self, symbol: str) -> str:
        return await self._get(f"/company/reports/{normalize_symbol(symbol)}", TTL_REPORTS)

    async def fetch_market_watch(self) -> str:
        return await self._get("/market-watch", TTL_MARKET)

    async def fetch_indices(self) -> str:
        return await self._get("/indices", TTL_INDICES)

    async def fetch_payouts(self, symbol: str) -> str:
        return await self._post(
            "/company/payouts", {"symbol": normalize_symbol(symbol)}, TTL_PAYOUTS
        )

    async def fetch_announcements(
        self,
        symbol: str,
        *,
        count: int = 50,
        offset: int = 0,
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        raw_type: str = "C",
    ) -> str:
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 100:
            raise ValueError("announcement count must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("announcement offset must be non-negative")
        if len(query) > 200:
            raise ValueError("announcement query must be at most 200 characters")
        form = {
            "type": raw_type,
            "symbol": normalize_symbol(symbol),
            "query": query,
            "count": str(count),
            "offset": str(offset),
            "date_from": date_from,
            "date_to": date_to,
            "page": "annc",
        }
        return await self._post("/announcements", form, TTL_ANNOUNCEMENTS)

    async def fetch_listing_table(self, board: str, segment: str) -> str:
        return await self._get(f"/listings-table/{board}/{segment}", TTL_LISTINGS)

    async def fetch_historical(self, symbol: str, month: int, year: int) -> str:
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
            raise ValueError("year must be between 2000 and 2100")
        form = {"month": str(month), "year": str(year), "symbol": normalize_symbol(symbol)}
        return await self._post("/historical", form, self._historical_ttl(month, year))

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _historical_ttl(month: int, year: int) -> int:
        now = datetime.now(PKT)
        if (year, month) < (now.year, now.month):
            return TTL_HISTORICAL_PAST
        return TTL_HISTORICAL_CURRENT

    async def _get(self, path: str, ttl: int) -> str:
        return await self._request("GET", path, None, ttl)

    async def _post(self, path: str, form: dict[str, str], ttl: int) -> str:
        return await self._request("POST", path, form, ttl)

    async def _request(self, method: str, path: str, form: dict[str, str] | None, ttl: int) -> str:
        key = (method, path, frozenset(form.items()) if form else None)
        cached = self._cache.get(key)
        if cached is not None:
            if isinstance(cached, _CachedPayload):
                served_at = datetime.now(PKT).isoformat()
                return FetchedText(
                    cached.text,
                    {
                        "source_fetched_at": cached.source_fetched_at,
                        "served_at": served_at,
                        "cache_age_seconds": round(monotonic() - cached.stored_monotonic, 3),
                        "from_cache": True,
                    },
                )
            return cached

        headers = {"X-Requested-With": "XMLHttpRequest"} if method == "POST" else None
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with self._request_semaphore:
                    resp = await self._client.request(method, path, data=form, headers=headers)
            except _RETRYABLE_EXC as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    if len(resp.content) > MAX_RESPONSE_BYTES:
                        raise PSXUnavailableError(
                            f"PSX returned an oversized response for {path}; "
                            "the response was not cached."
                        )
                    text = resp.text
                    source_fetched_at = datetime.now(PKT).isoformat()
                    self._cache.set(key, _CachedPayload(text, source_fetched_at), ttl)
                    return FetchedText(
                        text,
                        {
                            "source_fetched_at": source_fetched_at,
                            "served_at": source_fetched_at,
                            "cache_age_seconds": 0.0,
                            "from_cache": False,
                        },
                    )
                if resp.status_code < 500:
                    # Client error — not transient, do not retry.
                    raise PSXUnavailableError(
                        f"PSX returned HTTP {resp.status_code} for {path}. "
                        f"The endpoint or symbol may be invalid."
                    )
                last_exc = PSXUnavailableError(f"PSX returned HTTP {resp.status_code} for {path}.")
            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._backoff_base * (2**attempt))

        raise PSXUnavailableError(
            f"PSX Data Portal (dps.psx.com.pk) is not responding for {path} "
            f"after {self._max_retries} attempts ({last_exc}). This is a PSX-side "
            f"issue; please try again shortly."
        )
