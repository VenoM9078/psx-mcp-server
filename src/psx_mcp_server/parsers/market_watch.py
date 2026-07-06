"""Parse the /market-watch HTML table (~500 traded securities).

Columns: SYMBOL, SECTOR, LISTED IN, LDCP, OPEN, HIGH, LOW, CURRENT, CHANGE,
CHANGE (%), VOLUME.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from .._util import parse_int, parse_number
from ..errors import ParseError
from ..models import MarketRow


def parse_market_watch(html: str) -> list[MarketRow]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("table tbody")
    if body is None:
        raise ParseError("the market-watch page")
    rows: list[MarketRow] = []
    for tr in body.select("tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if len(cells) < 11:
            continue
        rows.append(
            MarketRow(
                symbol=cells[0],
                sector=cells[1],
                listed_in=cells[2],
                ldcp=parse_number(cells[3]),
                open=parse_number(cells[4]),
                high=parse_number(cells[5]),
                low=parse_number(cells[6]),
                current=parse_number(cells[7]),
                change=parse_number(cells[8]),
                change_pct=parse_number(cells[9]),
                volume=parse_int(cells[10]),
            )
        )
    if not rows:
        raise ParseError("the market-watch page")
    return rows
