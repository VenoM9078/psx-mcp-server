"""Small shared helpers: timezone conversion and number/symbol normalization."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

# PSX operates in Pakistan Standard Time (UTC+5, no daylight saving). Every unix
# timestamp from the portal is converted through this single helper so date
# handling is consistent (and testable) across the codebase.
PKT = ZoneInfo("Asia/Karachi")


def to_pkt(unix_ts: int | float) -> datetime:
    """Convert a unix timestamp to a Pakistan-Standard-Time aware datetime."""
    return datetime.fromtimestamp(unix_ts, PKT)


def normalize_symbol(symbol: str) -> str:
    """Uppercase and validate a ticker so ``'hbl '`` becomes ``'HBL'``.

    The symbol is eventually interpolated into a path or form value. Keeping
    this check at the shared boundary prevents path-like input from reaching
    any endpoint while still allowing normal PSX punctuation.
    """
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a text ticker")
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,19}", normalized):
        raise ValueError(
            "Invalid PSX symbol. Use a ticker containing only letters, numbers, '.', '-' or '_'."
        )
    return normalized


def parse_number(text: str | None) -> float | None:
    """Parse a PSX-formatted number ('5,426,927', '318.14', '-1.63%') to float.

    Returns None for blanks, dashes, or unparseable text so callers can treat
    missing values as null rather than crashing.
    """
    if text is None:
        return None
    cleaned = (
        text.strip().replace(",", "").replace("%", "").replace("Rs.", "").replace("−", "-").strip()
    )
    if cleaned in ("", "-", "--", "N/A", "n/a"):
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        inner = cleaned[1:-1].strip()
        if not inner:
            return None
        cleaned = inner if inner.startswith("-") else f"-{inner}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    """Parse a PSX-formatted integer ('5,426,927') to int, or None."""
    value = parse_number(text)
    return int(value) if value is not None else None


_RANGE_NUMBER = re.compile(r"[-−+]?\d[\d,]*\.?\d*")


def parse_range(text: str | None) -> tuple[float | None, float | None]:
    """Extract (low, high) from a range like '197.60 - 369.99'.

    PSX renders the separator as an en-dash that is often mis-encoded, so we pull
    the two numbers by regex instead of splitting on the separator character.
    """
    if not text:
        return (None, None)
    nums = [parse_number(m.group()) for m in _RANGE_NUMBER.finditer(text)]
    nums = [n for n in nums if n is not None]
    if len(nums) >= 2:
        return (nums[0], nums[1])
    if len(nums) == 1:
        return (nums[0], None)
    return (None, None)
