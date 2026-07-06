"""Plain dataclasses for parsed PSX data. No pydantic — FastMCP builds tool
schemas from type hints, and these are just JSON-safe data carriers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(slots=True)
class Symbol:
    """A listed PSX security from the /symbols directory."""

    symbol: str
    name: str
    sector: str
    is_etf: bool
    is_debt: bool
    is_gem: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MarketRow:
    """One security's row in the market-watch snapshot."""

    symbol: str
    sector: str
    listed_in: str
    ldcp: float | None
    open: float | None
    high: float | None
    low: float | None
    current: float | None
    change: float | None
    change_pct: float | None
    volume: int | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class IndexQuote:
    """A PSX index (KSE100, KSE30, KMI30, ...) snapshot."""

    name: str
    current: float | None
    high: float | None
    low: float | None
    change: float | None
    change_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class OhlcBar:
    """A full daily OHLCV bar from the /historical endpoint (has high/low)."""

    date: str  # ISO date (YYYY-MM-DD)
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Quote:
    """A live-ish quote parsed from the company page (regular-market segment)."""

    name: str
    sector: str
    as_of: str | None
    current: float | None
    ldcp: float | None
    open: float | None
    high: float | None
    low: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    bid: float | None
    bid_volume: int | None
    ask: float | None
    ask_volume: int | None
    week52_high: float | None
    week52_low: float | None
    pe_ratio: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CompanyInfo:
    """Company profile and fundamentals from the company page."""

    name: str
    sector: str
    business_description: str
    market_cap: float | None
    shares: int | None
    free_float: int | None
    free_float_pct: float | None
    pe_ratio: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Announcement:
    """A corporate announcement with a link to its document."""

    date: str | None
    title: str
    pdf_url: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Dividend:
    """A payout/dividend entry from the company payouts table."""

    date: str
    period: str
    details: str
    book_closure: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Tick:
    """A single intraday trade/price point."""

    time: datetime
    price: float
    volume: int

    def to_dict(self) -> dict:
        return {"time": self.time.isoformat(), "price": self.price, "volume": self.volume}


@dataclass(slots=True)
class EodBar:
    """A daily end-of-day bar. Note: the EOD feed has no high/low."""

    date: str  # ISO date (YYYY-MM-DD) in PKT
    open: float
    close: float
    volume: int

    def to_dict(self) -> dict:
        return asdict(self)
