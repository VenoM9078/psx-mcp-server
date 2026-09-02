"""Plain dataclasses for parsed PSX data. No pydantic — FastMCP builds tool
schemas from type hints, and these are just JSON-safe data carriers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    time: str | None = None
    symbol: str | None = None
    category: str | None = None
    raw_type: str | None = None
    image_url: str | None = None
    source: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Dividend:
    """A payout/dividend entry from the company payouts table."""

    date: str
    period: str
    details: str
    book_closure: str
    action_type: str = "unknown"
    cash_percentage: float | None = None
    interim: bool | None = None
    cash_dividend_per_share: float | None = None
    warnings: list[str] = field(default_factory=list)

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


@dataclass(slots=True)
class FinancialPeriod:
    """A conservative period descriptor for PSX's company summary tables."""

    raw_label: str
    normalized_period: str | None
    fiscal_year: int | None
    value_semantics: str
    period_start: str | None
    period_end: str | None
    publication_date: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FinancialFact:
    """One source row/value from a financial summary or ratio table."""

    period: str
    raw_label: str
    metric: str | None
    raw_value: str
    value: float | None
    unit: str
    unit_scale: int | None
    normalized_value: float | None
    source: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FinancialSection:
    """A bounded set of periods and facts from one company-page table."""

    periods: list[FinancialPeriod] = field(default_factory=list)
    facts: list[FinancialFact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "periods": [p.to_dict() for p in self.periods],
            "facts": [f.to_dict() for f in self.facts],
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class FinancialSummary:
    """Structured company-page summaries, deliberately not full statements."""

    annual: FinancialSection
    quarterly: FinancialSection
    ratios: list[FinancialFact]
    basis: str
    unit_note: str
    sources: list[dict]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "annual": self.annual.to_dict(),
            "quarterly": self.quarterly.to_dict(),
            "ratios": [r.to_dict() for r in self.ratios],
            "basis": self.basis,
            "unit_note": self.unit_note,
            "sources": self.sources,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class CompanyReport:
    """A report catalogue row; the report contents are intentionally not parsed."""

    report_type: str
    period_ended: str | None
    posting_date: str | None
    url: str | None
    source: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ListingStatus:
    """One row from a PSX listing-segment table."""

    symbol: str
    name: str
    sector: str
    segment: str
    clearing_type: str | None
    shares: int | None
    free_float: int | None
    listed_in: list[str]
    non_compliance: str | None
    source: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class AlertEvidence:
    """Company-specific evidence supporting or qualifying an alert state."""

    kind: str
    label: str
    raw_text: str | None
    url: str | None
    source: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CompanyAlerts:
    """Current compliance evidence with tri-state alert semantics."""

    symbol: str
    as_of: str
    listing_segment: str | None
    status_tags: list[dict]
    non_compliance: dict
    rwa: dict
    suspension: dict
    winding_up: dict
    sources: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
