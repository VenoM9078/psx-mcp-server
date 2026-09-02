"""Tests for official listing/status evidence parsing."""

from __future__ import annotations

from psx_mcp_server.parsers.alerts import (
    compliance_clauses,
    find_listing_status,
    parse_company_status,
    parse_listing_table,
)


def test_parse_normal_listing_row(fixture):
    rows = parse_listing_table(
        fixture("listing_main_nc.html"),
        segment="main/nc",
        source="https://dps.psx.com.pk/listings-table/main/nc",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "AIRLINK"
    assert row.clearing_type == "NC"
    assert row.shares == 395269231
    assert row.free_float == 118580769
    assert row.listed_in == ["KSE100", "KSE30"]
    assert row.non_compliance is None
    assert (
        find_listing_status(
            fixture("listing_main_nc.html"),
            segment="main/nc",
            symbol="airlink",
        ).symbol
        == "AIRLINK"
    )


def test_parse_non_compliance_listing_and_clauses(fixture):
    row = parse_listing_table(fixture("listing_main_dc.html"), segment="main/dc")[0]

    assert row.symbol == "AAL"
    assert row.non_compliance == "5.11.1.(a,b,c),5.11.2(a)"
    assert compliance_clauses(row.non_compliance) == ["5.11.1.(a,b,c)", "5.11.2(a)"]


def test_generic_hidden_rwa_modal_is_not_evidence(fixture):
    tags, evidence = parse_company_status(fixture("company_alert_normal.html"))

    assert tags == []
    assert evidence == []


def test_active_rwa_link_is_affirmative_evidence(fixture):
    tags, evidence = parse_company_status(
        fixture("company_alert_rwa.html"),
        source="https://dps.psx.com.pk/company/EXAMPLE",
    )

    assert tags == []
    assert len(evidence) == 1
    assert evidence[0].kind == "active_rwa_link"
    assert evidence[0].url == "https://dps.psx.com.pk/rwa"


def test_suspension_and_winding_up_tags_are_preserved(fixture):
    tags, evidence = parse_company_status(fixture("company_alert_suspended.html"))

    assert evidence == []
    assert {tag["text"] for tag in tags} == {"SUSPENDED", "WINDING-UP"}
    assert all(tag["classes"] for tag in tags)


def test_empty_listing_is_not_a_false_negative():
    assert parse_listing_table("<table><tbody></tbody></table>", segment="main/nc") == []


def test_hidden_active_looking_tag_and_rwa_link_are_ignored():
    html = """
    <div class="company__quote">
      <span class="tag" style="display: none">RWA</span>
      <span class="tag">SUSPENDED</span>
    </div>
    <a class="defaulterRWA__link" style="visibility:hidden" href="/rwa">RWA</a>
    """

    tags, evidence = parse_company_status(html)

    assert [tag["text"] for tag in tags] == ["SUSPENDED"]
    assert evidence == []
