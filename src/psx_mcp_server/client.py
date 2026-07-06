"""Async HTTP client for the PSX Data Portal.

Owns all network I/O: URLs, an identifying User-Agent, per-endpoint TTL caching,
and retry/backoff with error mapping. Returns raw response text — parsing lives
in parsers/, so this layer stays free of markup knowledge.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

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

_DEFAULT_UA = f"psx-mcp-server/{__version__} (+https://github.com/ahemdraza-96/psx-mcp-server)"

# httpx exceptions worth a retry (transient transport failures).
_RETRYABLE_EXC = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


class PSXClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        user_agent: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base
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

    async def fetch_market_watch(self) -> str:
        return await self._get("/market-watch", TTL_MARKET)

    async def fetch_indices(self) -> str:
        return await self._get("/indices", TTL_INDICES)

    async def fetch_payouts(self, symbol: str) -> str:
        return await self._post(
            "/company/payouts", {"symbol": normalize_symbol(symbol)}, TTL_PAYOUTS
        )

    async def fetch_historical(self, symbol: str, month: int, year: int) -> str:
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
            return cached

        headers = {"X-Requested-With": "XMLHttpRequest"} if method == "POST" else None
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.request(method, path, data=form, headers=headers)
            except _RETRYABLE_EXC as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    self._cache.set(key, resp.text, ttl)
                    return resp.text
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
