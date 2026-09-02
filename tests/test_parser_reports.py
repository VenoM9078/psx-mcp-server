"""Tests for report-catalogue metadata parsing."""

from __future__ import annotations

import pytest

from psx_mcp_server.models import CompanyReport
from psx_mcp_server.parsers.reports import (
    extract_report_period_year,
    filter_reports_by_year,
    parse_company_reports,
)


def test_parse_reports_and_filter_by_fiscal_year(fixture):
    reports = parse_company_reports(
        fixture("reports_HBL.html"),
        source="https://dps.psx.com.pk/company/reports/HBL",
    )

    assert len(reports) == 3
    assert reports[0].report_type == "Quarterly"
    assert reports[0].period_ended == "2026-03-31"
    assert reports[0].posting_date == "2026-04-28"
    assert reports[0].url.startswith("https://financials.psx.com.pk/")
    assert reports[0].source.endswith("/HBL")
    assert len(filter_reports_by_year(reports, 2025)) == 2
    assert len(filter_reports_by_year(reports, None)) == 3


def test_parse_reports_accepts_header_without_tbody():
    html = """
    <table><tr><th>Reports</th><th>Period Ended</th><th>Posting Date</th></tr>
      <tr><td>Annual</td><td>2024</td><td>2025-03-01</td></tr>
    </table>
    """
    reports = parse_company_reports(html)
    assert len(reports) == 1
    assert reports[0].url is None


def test_parse_reports_malformed_or_empty_response_is_empty():
    assert parse_company_reports("") == []
    assert parse_company_reports("<table><tbody><tr><td>bad</td></tr></tbody></table>") == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-12-31", 2025),
        ("31/12/2025", 2025),
        ("FY 2025", 2025),
        ("FY2025", 2025),
        ("2025", 2025),
        ("posted 2025", None),
        ("", None),
    ],
)
def test_extract_report_period_year_is_explicit(value, expected):
    assert extract_report_period_year(value) == expected


def test_report_filter_uses_period_year_not_posting_year():
    reports = [
        CompanyReport("Annual", "FY 2025", "2026-03-01", None),
        CompanyReport("Quarterly", "31/12/2025", "2025-12-31", None),
        CompanyReport("Unknown", "posted 2025", "2025-12-31", None),
    ]

    filtered = filter_reports_by_year(reports, 2025)
    assert [report.report_type for report in filtered] == ["Annual", "Quarterly"]
