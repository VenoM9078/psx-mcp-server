"""Tests for the company page parsers: quote, company info, announcements,
not-found detection, and the (separately fetched) payouts table."""

from __future__ import annotations

import pytest

from psx_mcp_server.parsers.company import (
    has_quote,
    parse_announcements,
    parse_company_info,
    parse_payouts,
    parse_quote,
)
from psx_mcp_server.parsers.market_watch import parse_market_watch
from psx_mcp_server.tools import _quote_warnings


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
    # The signed value is preserved from PSX's source change cell.
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
    dates = [announcement.date for announcement in anns if announcement.date]
    assert dates == sorted(dates, reverse=True)
    report = next(
        announcement
        for announcement in anns
        if announcement.title.startswith("Transmission of Quarterly Report")
    )
    assert report.category == "Financial Results"
    assert report.pdf_url == "/download/document/275409.pdf"


def test_parse_payouts(fixture):
    payouts = parse_payouts(fixture("payouts_HBL.html"))
    assert len(payouts) == 6
    first = payouts[0]
    assert first.date == "April 17, 2026 5:10 PM"
    assert first.period == "31/03/2026(IQ)"
    assert first.details == "60%(i) (D)"
    assert first.book_closure == "29/04/2026  - 30/04/2026"
    assert first.action_type == "cash"
    assert first.cash_percentage == 60.0
    assert first.interim is True
    assert first.cash_dividend_per_share is None
    assert first.warnings


def test_quote_missing_returns_none_fields():
    # A page with the quote container but no stats degrades to nulls, not a crash.
    html = '<div class="company__quote"><div class="quote__name">X</div></div>'
    q = parse_quote(html)
    assert q.name == "X"
    assert q.current is None


def test_parse_payouts_empty_returns_empty():
    assert parse_payouts("<table><tbody></tbody></table>") == []


def test_parse_payout_action_markers_conservatively():
    html = """
    <table><tbody>
      <tr><td>2026-01-01</td><td>31/12/2025(YR)</td><td>20% (B)</td><td>-</td></tr>
      <tr><td>2026-01-02</td><td>31/12/2025(YR)</td><td>1 for 5 (R)</td><td>-</td></tr>
      <tr><td>2026-01-03</td><td>31/12/2025(YR)</td><td>50% (D)</td><td>-</td></tr>
      <tr><td>2026-01-04</td><td>31/12/2025(YR)</td><td>Special payout</td><td>-</td></tr>
    </tbody></table>
    """
    payouts = parse_payouts(html)

    assert [p.action_type for p in payouts] == ["bonus", "right", "cash", "unknown"]
    assert payouts[0].cash_percentage is None
    assert payouts[1].cash_percentage is None
    assert payouts[2].cash_percentage == 50.0
    assert payouts[2].cash_dividend_per_share is None
    assert payouts[2].warnings
    assert payouts[3].warnings


def test_payout_parser_preserves_multiple_actions_and_rejects_unknown_interim_token():
    html = """
    <table><tbody>
      <tr><td>2026-01-01</td><td>31/12/2025(YR)</td><td>60% (D) (B)</td><td>-</td></tr>
      <tr><td>2026-01-02</td><td>31/12/2025(YR)</td><td>60% (iiii)</td><td>-</td></tr>
    </tbody></table>
    """

    payouts = parse_payouts(html)

    assert payouts[0].action_type == "unknown"
    assert payouts[0].cash_percentage == 60.0
    assert payouts[0].interim is None
    assert payouts[0].warnings
    assert payouts[1].action_type == "unknown"
    assert payouts[1].interim is None
    assert payouts[1].warnings


def _quote_html(
    *,
    current: str | None = "100.00",
    ldcp: str | None = "100.00",
    change: str | None = "0 (0%)",
) -> str:
    current_html = f'<div class="quote__close">{current}</div>' if current is not None else ""
    change_html = f'<div class="quote__change">{change}</div>' if change is not None else ""
    ldcp_html = f'<div class="stats_value">{ldcp}</div>' if ldcp is not None else ""
    return f"""
    <div class="company__quote">{current_html}{change_html}</div>
    <div class="tabs__panel" data-name="REG">
      <div class="stats_label">LDCP</div>{ldcp_html}
    </div>
    """


@pytest.mark.parametrize(
    ("current", "ldcp", "change", "change_pct"),
    [
        ("96.00", "100.00", "-4 (-4%)", (-4.0, -4.0)),
        ("104.00", "100.00", "4 (4%)", (4.0, 4.0)),
        ("104.00", "100.00", "+4 (+4%)", (4.0, 4.0)),
        ("100.00", "100.00", "0 (0%)", (0.0, 0.0)),
        ("100.01", "100.00", "0.01 (0.01%)", (0.01, 0.01)),
    ],
)
def test_parse_quote_preserves_signed_source_values(current, ldcp, change, change_pct):
    quote = parse_quote(_quote_html(current=current, ldcp=ldcp, change=change))
    assert (quote.change, quote.change_pct) == change_pct


@pytest.mark.parametrize(
    ("current", "ldcp", "change"),
    [
        (None, "100.00", "-4 (-4%)"),
        ("96.00", None, "-4 (-4%)"),
        ("96.00", "100.00", None),
    ],
)
def test_parse_quote_missing_change_inputs_do_not_rederive_sign(current, ldcp, change):
    quote = parse_quote(_quote_html(current=current, ldcp=ldcp, change=change))
    assert quote.change == (-4.0 if change else None)
    assert quote.change_pct == (-4.0 if change else None)


def test_quote_material_arithmetic_disagreement_is_a_warning():
    quote = parse_quote(_quote_html(current="101.00", ldcp="100.00", change="5 (5%)"))
    warnings = _quote_warnings(
        quote.pe_ratio,
        current=quote.current,
        ldcp=quote.ldcp,
        change=quote.change,
        change_pct=quote.change_pct,
    )
    assert any("differs materially" in warning for warning in warnings)


def test_quote_rounding_difference_does_not_warn():
    quote = parse_quote(_quote_html(current="100.01", ldcp="100.00", change="0 (0%)"))
    warnings = _quote_warnings(
        quote.pe_ratio,
        current=quote.current,
        ldcp=quote.ldcp,
        change=quote.change,
        change_pct=quote.change_pct,
    )
    assert not warnings


def test_quote_and_market_watch_preserve_the_same_signed_change(fixture):
    quote = parse_quote(fixture("company_HBL.html"))
    market_row = next(
        row for row in parse_market_watch(fixture("market_watch.html")) if row.symbol == "HBL"
    )

    assert quote.change == market_row.change
    assert quote.change_pct == market_row.change_pct
