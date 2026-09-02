"""Parse the /company/{SYMBOL} page and the /company/payouts table.

The company page carries several market-segment tab panels (REG, FUT, ...) that
reuse the same stat labels, so the quote is read strictly from the REG (regular
market) panel. Fundamentals come from the Equity Profile section, and the
business description from the Company Profile section.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .._util import parse_int, parse_number, parse_range
from ..models import Announcement, CompanyInfo, Dividend, Quote
from .announcements import PSX_BASE_URL, sort_announcements

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

    # PSX already supplies signed change values.  Preserve those signs instead
    # of deriving a second sign from current versus LDCP.
    change_source, change_pct_source = parse_range(_text(".quote__change"))
    change = None if change_source is None else round(change_source, 2)
    change_pct = None if change_pct_source is None else round(change_pct_source, 2)

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
    panels = section.select(".tabs__panel[data-name]")
    if not panels:
        panels = [section]
    for panel in panels:
        category = panel.get("data-name")
        for tr in panel.select("tbody tr"):
            cells = tr.select("td")
            if len(cells) < 2:
                continue
            date_txt = cells[0].get_text(strip=True)
            title = cells[1].get_text(" ", strip=True)
            if not title:
                continue
            pdf = _document_link(tr)
            image_id = _image_id(tr)
            out.append(
                Announcement(
                    date=_iso_date(date_txt),
                    title=title,
                    pdf_url=pdf,
                    category=category,
                    image_url=(
                        urljoin(PSX_BASE_URL, f"/download/image/{image_id}") if image_id else None
                    ),
                )
            )
    return sort_announcements(out)


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
        action_type, cash_percentage, interim, warnings = _parse_dividend_details(
            cells[2], cells[1]
        )
        out.append(
            Dividend(
                date=cells[0],
                period=cells[1],
                details=cells[2],
                book_closure=cells[3],
                action_type=action_type,
                cash_percentage=cash_percentage,
                interim=interim,
                warnings=warnings,
            )
        )
    return out


def _document_link(row: Tag) -> str | None:
    for link in row.select("a[href]"):
        href = link.get("href", "")
        path = urlsplit(href).path.lower()
        if path.endswith(".pdf") or path.startswith("/download/document/"):
            return href
    return None


def _image_id(row: Tag) -> str | None:
    link = row.select_one("a[data-images]")
    if link is None:
        return None
    return link.get("data-images") or None


def _parse_dividend_details(
    details: str,
    period: str,
) -> tuple[str, float | None, bool | None, list[str]]:
    upper = details.upper()
    markers = {
        "cash": "(D)" in upper or "CASH" in upper,
        "bonus": "(B)" in upper or "BONUS" in upper,
        "right": "(R)" in upper or "RIGHT" in upper,
    }
    kinds = [kind for kind, present in markers.items() if present]
    action_type = kinds[0] if len(kinds) == 1 else "unknown"
    warnings: list[str] = []
    if len(kinds) > 1:
        warnings.append("Multiple payout action markers were present; action_type is unknown.")
    if not kinds:
        warnings.append("No recognized payout action marker was present; action_type is unknown.")

    cash_percentage = None
    if markers["cash"]:
        percentages = re.findall(r"(\d+(?:\.\d+)?)\s*%", details)
        if len(percentages) == 1:
            cash_percentage = float(percentages[0])
        elif not percentages:
            warnings.append(
                "Cash payout evidence has no well-formed percentage; cash_percentage is unknown."
            )
        else:
            warnings.append("Multiple cash percentages were present; cash_percentage is unknown.")
    interim: bool | None = None
    if re.search(r"\(\s*(?:i|ii|iii|iq)\s*\)", f"{details} {period}", re.IGNORECASE):
        interim = True
    elif re.search(r"\(\s*f\s*\)", f"{details} {period}", re.IGNORECASE):
        interim = False

    if markers["cash"]:
        warnings.append(
            "Cash percentage is preserved as source notation; face value is unknown, "
            "so cash_dividend_per_share is null."
        )
    return action_type, cash_percentage, interim, warnings


def _text_or_empty(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""


def _iso_date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return None
