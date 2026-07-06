"""Parse the /timeseries/int and /timeseries/eod JSON feeds.

Intraday rows are [unix_ts, price, volume]; EOD rows are
[unix_ts, close, volume, open]. Both come newest-first and we preserve that.
"""

from __future__ import annotations

import json

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
    rows = _load_data(text, "the intraday timeseries")
    ticks: list[Tick] = []
    for row in rows:
        ts, price, volume = row[0], row[1], row[2]
        ticks.append(Tick(time=to_pkt(ts), price=float(price), volume=int(volume)))
    return ticks


def parse_eod(text: str) -> list[EodBar]:
    """[[unix_ts, close, volume, open], ...] -> newest-first list of EodBar."""
    rows = _load_data(text, "the EOD timeseries")
    bars: list[EodBar] = []
    for row in rows:
        ts, close, volume, open_ = row[0], row[1], row[2], row[3]
        bars.append(
            EodBar(
                date=to_pkt(ts).date().isoformat(),
                open=float(open_),
                close=float(close),
                volume=int(volume),
            )
        )
    return bars
