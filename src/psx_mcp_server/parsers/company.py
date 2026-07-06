"""Parse the /company/{SYMBOL} page and the /company/payouts table.

The company page carries several market-segment tab panels (REG, FUT, ...) that
reuse the same stat labels, so the quote is read strictly from the REG (regular
market) panel. Fundamentals come from the Equity Profile section, and the
business description from the Company Profile section.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from .._util import parse_int, parse_number, parse_range
from ..models import Announcement, CompanyInfo, Dividend, Quote

_AS_OF = re.compile(r"As of\s+(.+?)\s*(?:REG|FUT|CSF|ODL|DFC|$)")


def has_quote(html: str) -> bool:
    """True if the page is a real company page (unknown symbols lack this block)."""
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one(".company__quote") is not None


def _stats_map(scope: Tag) -> dict[str, str]:
    """Build a {label: value} map from a region's stats_label/stats_value pairs."""
    labels = scope.select(".stats_label")
    values = scope.select(".stats_value")
    return {
        lab.get_text(strip=True): val.get_text(" ", strip=True)
        for lab, val in zip(labels, values, strict=False)
    }


def _section(soup: BeautifulSoup, title: str) -> Tag | None:
    for t in soup.select(".section__title"):
        if t.get_text(strip=True) == title:
            return t.find_parent(class_="section") or t.parent
    return None


def parse_quote(html: str) -> Quote:
    soup = BeautifulSoup(html, "lxml")
    quote_box = soup.select_one(".company__quote")

    def _text(sel: str) -> str | None:
        el = quote_box.select_one(sel) if quote_box else None
        return el.get_text(" ", strip=True) if el else None

    name = _text(".quote__name") or ""
    sector = _text(".quote__sector") or ""
    current = parse_number(_text(".quote__close"))
    as_of = None
    if quote_box:
        m = _AS_OF.search(quote_box.get_text(" ", strip=True))
        if m:
            as_of = m.group(1).strip()

    reg = soup.select_one('.tabs__panel[data-name="REG"]')
    stats = _stats_map(reg) if reg else {}
    ldcp = parse_number(stats.get("LDCP"))
    week52_low, week52_high = parse_range(
        stats.get("52-WEEK RANGE ^") or stats.get("52-WEEK RANGE")
    )

    # The displayed change is a magnitude; derive direction from current vs LDCP.
    change_mag, change_pct_mag = parse_range(_text(".quote__change"))
    sign = 1.0
    if current is not None and ldcp is not None and current < ldcp:
        sign = -1.0
    change = None if change_mag is None else round(sign * change_mag, 2)
    change_pct = None if change_pct_mag is None else round(sign * change_pct_mag, 2)

    return Quote(
        name=name,
        sector=sector,
        as_of=as_of,
        current=current,
        ldcp=ldcp,
        open=parse_number(stats.get("Open")),
        high=parse_number(stats.get("High")),
        low=parse_number(stats.get("Low")),
        change=change,
        change_pct=change_pct,
        volume=parse_int(stats.get("Volume")),
        bid=parse_number(stats.get("Bid Price")),
        bid_volume=parse_int(stats.get("Bid Volume")),
        ask=parse_number(stats.get("Ask Price")),
        ask_volume=parse_int(stats.get("Ask Volume")),
        week52_high=week52_high,
        week52_low=week52_low,
        pe_ratio=parse_number(stats.get("P/E Ratio (TTM) **") or stats.get("P/E Ratio (TTM)")),
    )


def parse_company_info(html: str) -> CompanyInfo:
    soup = BeautifulSoup(html, "lxml")
    name = _text_or_empty(soup, ".quote__name")
    sector = _text_or_empty(soup, ".quote__sector")

    description = ""
    profile = _section(soup, "Company Profile")
    if profile:
        desc_el = profile.select_one(".profile__item--decription p")
        if desc_el:
            description = desc_el.get_text(" ", strip=True)

    market_cap = shares = free_float = free_float_pct = None
    equity = _section(soup, "Equity Profile")
    if equity:
        # Free Float appears twice (absolute then %); walk pairs in order.
        pairs = list(
            zip(
                equity.select(".stats_label"),
                equity.select(".stats_value"),
                strict=False,
            )
        )
        seen_free_float = False
        for lab_el, val_el in pairs:
            lab = lab_el.get_text(strip=True)
            val = val_el.get_text(strip=True)
            if lab.startswith("Market Cap"):
                thousands = parse_number(val)
                market_cap = None if thousands is None else round(thousands * 1000, 2)
            elif lab == "Shares":
                shares = parse_int(val)
            elif lab == "Free Float":
                if not seen_free_float:
                    free_float = parse_int(val)
                    seen_free_float = True
                else:
                    free_float_pct = parse_number(val)

    reg = soup.select_one('.tabs__panel[data-name="REG"]')
    stats = _stats_map(reg) if reg else {}
    pe = parse_number(stats.get("P/E Ratio (TTM) **") or stats.get("P/E Ratio (TTM)"))

    return CompanyInfo(
        name=name,
        sector=sector,
        business_description=description,
        market_cap=market_cap,
        shares=shares,
        free_float=free_float,
        free_float_pct=free_float_pct,
        pe_ratio=pe,
    )


def parse_announcements(html: str) -> list[Announcement]:
    soup = BeautifulSoup(html, "lxml")
    section = _section(soup, "Announcements")
    if section is None:
        return []
    out: list[Announcement] = []
    for tr in section.select("tbody tr"):
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        date_txt = cells[0].get_text(strip=True)
        title = cells[1].get_text(" ", strip=True)
        if not title:
            continue
        pdf = tr.select_one('a[href$=".pdf"]')
        out.append(
            Announcement(
                date=_iso_date(date_txt),
                title=title,
                pdf_url=pdf["href"] if pdf and pdf.has_attr("href") else None,
            )
        )
    return out


def parse_payouts(html: str) -> list[Dividend]:
    """Parse the POST /company/payouts table. Columns: Date, Financial Results,
    Details, Book Closure."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("table tbody")
    if body is None:
        return []
    out: list[Dividend] = []
    for tr in body.select("tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if len(cells) < 4:
            continue
        out.append(
            Dividend(
                date=cells[0],
                period=cells[1],
                details=cells[2],
                book_closure=cells[3],
            )
        )
    return out


def _text_or_empty(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""


def _iso_date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return None
