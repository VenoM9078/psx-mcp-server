"""Tests for the company page parsers: quote, company info, announcements,
not-found detection, and the (separately fetched) payouts table."""

from __future__ import annotations

from psx_mcp_server.parsers.company import (
    has_quote,
    parse_announcements,
    parse_company_info,
    parse_payouts,
    parse_quote,
)


def test_has_quote_true_for_valid(fixture):
    assert has_quote(fixture("company_HBL.html")) is True


def test_has_quote_false_for_unknown(fixture):
    assert has_quote(fixture("company_UNKNOWN.html")) is False


def test_parse_quote_core_fields(fixture):
    q = parse_quote(fixture("company_HBL.html"))
    assert q.name == "Habib Bank Limited"
    assert q.sector == "COMMERCIAL BANKS"
    assert q.as_of == "Mon, Jul 6, 2026 3:49 PM"
    assert q.current == 318.15
    assert q.ldcp == 305.91
    assert q.open == 308.44
    assert q.high == 319.25
    assert q.low == 307.00
    assert q.volume == 5426927
    assert q.pe_ratio == 7.43


def test_parse_quote_change_and_ranges(fixture):
    q = parse_quote(fixture("company_HBL.html"))
    # Direction derived from current (318.15) vs ldcp (305.91): up.
    assert q.change == 12.24
    assert q.change_pct == 4.00
    assert q.week52_low == 197.60
    assert q.week52_high == 369.99


def test_parse_company_info(fixture):
    info = parse_company_info(fixture("company_HBL.html"))
    assert info.name == "Habib Bank Limited"
    assert info.business_description.startswith("Habib Bank Limited is incorporated in Pakistan")
    # Market Cap shown in thousands on the page; exposed as actual PKR.
    assert info.market_cap == 466679125420.0
    assert info.shares == 1466852508
    assert info.free_float == 586741003
    assert info.free_float_pct == 40.00
    assert info.pe_ratio == 7.43


def test_parse_announcements(fixture):
    anns = parse_announcements(fixture("company_HBL.html"))
    assert len(anns) == 15
    first = anns[0]
    assert first.date == "2026-04-28"
    assert first.title.startswith("Transmission of Quarterly Report")
    assert first.pdf_url == "/download/document/275409.pdf"


def test_parse_payouts(fixture):
    payouts = parse_payouts(fixture("payouts_HBL.html"))
    assert len(payouts) == 6
    first = payouts[0]
    assert first.date == "April 17, 2026 5:10 PM"
    assert first.period == "31/03/2026(IQ)"
    assert first.details == "60%(i) (D)"
    assert first.book_closure == "29/04/2026  - 30/04/2026"


def test_quote_missing_returns_none_fields():
    # A page with the quote container but no stats degrades to nulls, not a crash.
    html = '<div class="company__quote"><div class="quote__name">X</div></div>'
    q = parse_quote(html)
    assert q.name == "X"
    assert q.current is None


def test_parse_payouts_empty_returns_empty():
    assert parse_payouts("<table><tbody></tbody></table>") == []
