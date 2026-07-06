"""Parse the POST /historical HTML table (one calendar month of daily OHLCV).

Columns: DATE ('Jun 30, 2026'), OPEN, HIGH, LOW, CLOSE, VOLUME. An empty month
(future/invalid) yields an empty list rather than an error.
"""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from .._util import parse_int, parse_number
from ..models import OhlcBar


def _parse_date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_historical(html: str) -> list[OhlcBar]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("table tbody")
    if body is None:
        return []
    bars: list[OhlcBar] = []
    for tr in body.select("tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if len(cells) < 6:
            continue
        date = _parse_date(cells[0])
        if date is None:
            continue
        bars.append(
            OhlcBar(
                date=date,
                open=parse_number(cells[1]),
                high=parse_number(cells[2]),
                low=parse_number(cells[3]),
                close=parse_number(cells[4]),
                volume=parse_int(cells[5]),
            )
        )
    return bars
