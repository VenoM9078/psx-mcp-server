"""Parse PSX listing-segment and company-page compliance evidence."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .._util import normalize_symbol, parse_int
from ..models import AlertEvidence, ListingStatus
from .announcements import PSX_BASE_URL


def parse_listing_table(
    html: str,
    *,
    segment: str,
    source: str | None = None,
) -> list[ListingStatus]:
    """Parse one /listings-table/{board}/{segment} response."""
    soup = BeautifulSoup(html, "lxml")
    visible_tables = [table for table in soup.select("table") if _is_visible(table)]
    table = visible_tables[0] if visible_tables else None
    if table is None:
        return []

    header_row = table.select_one("thead tr") or table.select_one("tr")
    if header_row is None:
        return []
    headers = [cell.get_text(" ", strip=True).lower() for cell in header_row.select("th, td")]
    body_rows = table.select("tbody tr")
    if not body_rows:
        rows = table.select("tr")
        body_rows = rows[1:] if len(rows) > 1 else []

    def index_containing(*terms: str) -> int | None:
        for index, header in enumerate(headers):
            if any(term in header for term in terms):
                return index
        return None

    symbol_index = index_containing("symbol")
    name_index = index_containing("name")
    sector_index = index_containing("sector")
    clearing_index = index_containing("clearing")
    shares_index = index_containing("shares")
    free_float_index = index_containing("free float")
    listed_index = index_containing("listed in")
    compliance_index = index_containing("non-compliance")
    if symbol_index is None:
        return []

    statuses: list[ListingStatus] = []
    for row in body_rows:
        cells = row.select("td")
        if symbol_index >= len(cells):
            continue
        symbol = cells[symbol_index].get_text(" ", strip=True)
        if not symbol:
            continue
        symbol = normalize_symbol(symbol)
        statuses.append(
            ListingStatus(
                symbol=symbol,
                name=_cell_text(cells, name_index),
                sector=_cell_text(cells, sector_index),
                segment=segment,
                clearing_type=_optional(_cell_text(cells, clearing_index)),
                shares=parse_int(_cell_text(cells, shares_index)),
                free_float=parse_int(_cell_text(cells, free_float_index)),
                listed_in=_tags(cells, listed_index),
                non_compliance=_optional(_cell_text(cells, compliance_index)),
                source=source,
            )
        )
    return statuses


def find_listing_status(
    html: str,
    *,
    segment: str,
    symbol: str,
    source: str | None = None,
) -> ListingStatus | None:
    """Find one normalized symbol in a listing table."""
    wanted = normalize_symbol(symbol)
    return next(
        (
            row
            for row in parse_listing_table(html, segment=segment, source=source)
            if row.symbol == wanted
        ),
        None,
    )


def parse_company_status(
    html: str,
    *,
    source: str | None = None,
) -> tuple[list[dict], list[AlertEvidence]]:
    """Extract visible company status tags and affirmative RWA markers.

    The generic hidden ``footer__rwaModal`` is intentionally ignored.  It is a
    site-wide template and is not company-specific evidence.
    """
    soup = BeautifulSoup(html, "lxml")
    tags: list[dict] = []
    for tag in soup.select(".company__quote .tag"):
        if not _is_visible(tag):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        tags.append(
            {
                "text": text,
                "classes": [
                    class_name for class_name in tag.get("class", []) if class_name != "tag"
                ],
                "source": source,
            }
        )

    evidence: list[AlertEvidence] = []
    for link in soup.select(".defaulterRWA__link"):
        if not _is_visible(link):
            continue
        href = link.get("href")
        if not href or not href.strip() or href.strip() == "#":
            continue
        evidence.append(
            AlertEvidence(
                kind="active_rwa_link",
                label="Risk Warning Alert",
                raw_text=link.get_text(" ", strip=True) or None,
                url=urljoin(PSX_BASE_URL, href) if href else None,
                source=source,
            )
        )
    return tags, evidence


def compliance_clauses(raw_text: str | None) -> list[str]:
    """Split a PSX non-compliance cell into conservative clause tokens."""
    if not raw_text:
        return []
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in raw_text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        if character == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(character)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _cell_text(cells: list, index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return cells[index].get_text(" ", strip=True)


def _optional(value: str) -> str | None:
    return value or None


def _tags(cells: list, index: int | None) -> list[str]:
    if index is None or index >= len(cells):
        return []
    cell = cells[index]
    tags = [tag.get_text(" ", strip=True) for tag in cell.select(".tag")]
    tags = [tag for tag in tags if tag]
    if tags:
        return tags
    return [part.strip() for part in cell.get_text(" ", strip=True).split(",") if part.strip()]


def _is_visible(tag: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if current.has_attr("hidden"):
            return False
        style = str(current.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return False
        classes = {str(value).lower() for value in current.get("class", [])}
        if classes & {"d-none", "hidden", "invisible"}:
            return False
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return True
