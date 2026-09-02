"""Parse the /timeseries/int and /timeseries/eod JSON feeds.

Intraday rows are [unix_ts, price, volume]; EOD rows are
[unix_ts, close, volume, open]. Both come newest-first and we preserve that.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .._util import to_pkt
from ..errors import ParseError
from ..models import EodBar, Tick


def _load_data(text: str, what: str) -> list:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ParseError(what) from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise ParseError(what)
    data = payload.get("data") or []
    if not isinstance(data, list):
        raise ParseError(what)
    return data


def parse_intraday(text: str) -> list[Tick]:
    """[[unix_ts, price, volume], ...] -> newest-first list of Tick."""
    ticks, _ = parse_intraday_with_warnings(text)
    return ticks


def parse_intraday_with_warnings(text: str) -> tuple[list[Tick], list[str]]:
    """Parse usable intraday rows and report skipped malformed rows."""
    rows = _load_data(text, "the intraday timeseries")
    ticks: list[Tick] = []
    malformed = 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            malformed += 1
            continue
        ts, price, volume = row[0], row[1], row[2]
        parsed = _parse_tick(ts, price, volume)
        if parsed is None:
            malformed += 1
            continue
        ticks.append(parsed)
    warnings = [f"Skipped {malformed} malformed intraday row(s)."] if malformed else []
    return ticks, warnings


def parse_eod(text: str) -> list[EodBar]:
    """[[unix_ts, close, volume, open], ...] -> newest-first list of EodBar."""
    bars, _ = parse_eod_with_warnings(text)
    return bars


def parse_eod_with_warnings(text: str) -> tuple[list[EodBar], list[str]]:
    """Parse usable EOD rows, skipping malformed rows deterministically."""
    rows = _load_data(text, "the EOD timeseries")
    bars: list[EodBar] = []
    seen_dates: set[str] = set()
    malformed = 0
    duplicates = 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            malformed += 1
            continue
        ts, close, volume, open_ = row[0], row[1], row[2], row[3]
        parsed = _parse_eod_bar(ts, close, volume, open_)
        if parsed is None:
            malformed += 1
            continue
        if parsed.date in seen_dates:
            duplicates += 1
            continue
        seen_dates.add(parsed.date)
        bars.append(parsed)
    warnings: list[str] = []
    if malformed:
        warnings.append(f"Skipped {malformed} malformed EOD row(s).")
    if duplicates:
        warnings.append(
            f"Skipped {duplicates} duplicate EOD date row(s); the first source row was retained."
        )
    return bars, warnings


def _parse_tick(ts: Any, price: Any, volume: Any) -> Tick | None:
    try:
        if isinstance(ts, bool) or isinstance(price, bool) or isinstance(volume, bool):
            return None
        parsed_time = to_pkt(ts)
        parsed_price = float(price)
        parsed_volume = int(volume)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if (
        not math.isfinite(parsed_price)
        or parsed_price < 0
        or parsed_volume < 0
        or not _is_integer_like(volume)
    ):
        return None
    return Tick(time=parsed_time, price=parsed_price, volume=parsed_volume)


def _parse_eod_bar(ts: Any, close: Any, volume: Any, open_: Any) -> EodBar | None:
    try:
        if (
            isinstance(ts, bool)
            or isinstance(close, bool)
            or isinstance(volume, bool)
            or isinstance(open_, bool)
        ):
            return None
        parsed_date = to_pkt(ts).date().isoformat()
        parsed_close = float(close)
        parsed_open = float(open_)
        parsed_volume = int(volume)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if (
        not math.isfinite(parsed_close)
        or not math.isfinite(parsed_open)
        or parsed_close < 0
        or parsed_open < 0
        or parsed_volume < 0
        or not _is_integer_like(volume)
    ):
        return None
    return EodBar(
        date=parsed_date,
        open=parsed_open,
        close=parsed_close,
        volume=parsed_volume,
    )


def _is_integer_like(value: Any) -> bool:
    try:
        return float(value).is_integer()
    except (TypeError, ValueError, OverflowError):
        return False
