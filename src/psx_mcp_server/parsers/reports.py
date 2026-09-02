"""Parse the company report catalogue returned by PSX."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import CompanyReport


def parse_company_reports(
    html: str,
    *,
    source: str | None = None,
) -> list[CompanyReport]:
    """Parse report metadata without downloading or interpreting PDF contents."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table")
    if table is None:
        return []

    reports: list[CompanyReport] = []
    body_rows = table.select("tbody tr")
    if not body_rows:
        rows = table.select("tr")
        body_rows = rows[1:] if len(rows) > 1 else []
    for row in body_rows:
        cells = row.select("td")
        if len(cells) < 3:
            continue
        link = cells[0].select_one("a[href]")
        report_type = link.get_text(" ", strip=True) if link else cells[0].get_text(" ", strip=True)
        if not report_type:
            continue
        reports.append(
            CompanyReport(
                report_type=report_type,
                period_ended=_clean(cells[1].get_text(" ", strip=True)),
                posting_date=_clean(cells[2].get_text(" ", strip=True)),
                url=link["href"] if link else None,
                source=source,
            )
        )
    return reports


def filter_reports_by_year(
    reports: list[CompanyReport],
    fiscal_year: int | None,
) -> list[CompanyReport]:
    """Filter catalogue rows using an explicit year in ``period_ended``."""
    if fiscal_year is None:
        return reports
    return [
        report
        for report in reports
        if extract_report_period_year(report.period_ended) == fiscal_year
    ]


def extract_report_period_year(value: str | None) -> int | None:
    """Extract only supported fiscal-period formats, never posting-date years."""
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value.strip())
    match = re.fullmatch(r"(\d{4})-\d{2}-\d{2}", normalized)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"\d{2}/\d{2}/(\d{4})", normalized)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"FY\s*(\d{4})", normalized, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"(\d{4})", normalized)
    return int(match.group(1)) if match else None


def _clean(value: str) -> str | None:
    return value or None
