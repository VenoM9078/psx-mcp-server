"""Parse the richer global PSX announcements response."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..models import Announcement

PSX_BASE_URL = "https://dps.psx.com.pk"
_TOTAL_ENTRIES = re.compile(r"of\s+(\d+)\s+entries", re.IGNORECASE)


def parse_global_announcements(
    html: str,
    *,
    source: str | None = None,
    raw_type: str | None = None,
) -> tuple[list[Announcement], int | None]:
    """Parse a POST /announcements page and return rows plus source total."""
    soup = BeautifulSoup(html, "lxml")
    total = None
    header = soup.select_one(".announcementsResults__header")
    if header:
        match = _TOTAL_ENTRIES.search(header.get_text(" ", strip=True))
        if match:
            total = int(match.group(1))

    table = soup.select_one("#announcementsTable") or soup.select_one("table")
    if table is None:
        return [], total

    announcements: list[Announcement] = []
    body_rows = table.select("tbody tr")
    if not body_rows:
        rows = table.select("tr")
        body_rows = rows[1:] if len(rows) > 1 else []
    for row in body_rows:
        cells = row.select("td")
        if len(cells) < 5:
            continue
        date = _iso_date(cells[0].get_text(" ", strip=True))
        time = cells[1].get_text(" ", strip=True) or None
        symbol = cells[2].get_text(" ", strip=True) or None
        title = cells[4].get_text(" ", strip=True)
        if not title:
            continue
        pdf = _document_link(row)
        image_id = _image_id(row)
        image_url = urljoin(PSX_BASE_URL, f"/download/image/{image_id}") if image_id else None
        announcements.append(
            Announcement(
                date=date,
                title=title,
                pdf_url=pdf,
                time=time,
                symbol=symbol,
                category=None,
                raw_type=raw_type,
                image_url=image_url,
                source=source,
            )
        )
    return announcements, total


def sort_announcements(announcements: list[Announcement]) -> list[Announcement]:
    """Return newest announcements first, putting undated rows last."""
    return sorted(announcements, key=_sort_key, reverse=True)


def announcement_sort_key(announcement: Announcement) -> tuple[int, str, str, str]:
    """Expose a deterministic sort key for callers that need to merge pages."""
    return _sort_key(announcement)


def _sort_key(announcement: Announcement) -> tuple[int, str, str, str]:
    if not announcement.date:
        return (0, "", announcement.symbol or "", announcement.title)
    parsed = None
    if announcement.time:
        for time_format in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
            try:
                parsed = datetime.strptime(
                    f"{announcement.date} {announcement.time}",
                    f"%Y-%m-%d {time_format}",
                )
                break
            except ValueError:
                continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(announcement.date)
        except ValueError:
            return (0, announcement.date, announcement.symbol or "", announcement.title)
    return (1, parsed.isoformat(), announcement.symbol or "", announcement.title)


def _document_link(cell) -> str | None:
    for link in cell.select("a[href]"):
        href = link.get("href", "")
        path = urlsplit(href).path.lower()
        if path.endswith(".pdf") or path.startswith("/download/document/"):
            return href
    return None


def _image_id(cell) -> str | None:
    link = cell.select_one("a[data-images]")
    if link is None:
        return None
    image_id = link.get("data-images")
    return image_id or None


def _iso_date(value: str) -> str | None:
    for date_format in ("%b %d, %Y", "%Y-%m-%d", "%d %b, %Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    return None
