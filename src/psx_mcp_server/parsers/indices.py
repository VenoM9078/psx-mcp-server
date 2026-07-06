"""Parse the /indices HTML table.

Columns: Index, High, Low, Current, Change, % Change.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from .._util import parse_number
from ..errors import ParseError
from ..models import IndexQuote


def parse_indices(html: str) -> list[IndexQuote]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("table tbody")
    if body is None:
        raise ParseError("the indices page")
    indices: list[IndexQuote] = []
    for tr in body.select("tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if len(cells) < 6 or not cells[0]:
            continue
        indices.append(
            IndexQuote(
                name=cells[0],
                high=parse_number(cells[1]),
                low=parse_number(cells[2]),
                current=parse_number(cells[3]),
                change=parse_number(cells[4]),
                change_pct=parse_number(cells[5]),
            )
        )
    if not indices:
        raise ParseError("the indices page")
    return indices
