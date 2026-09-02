"""Tests for conservative company-page financial summaries and ratios."""

from __future__ import annotations

import json

from psx_mcp_server.parsers.financials import parse_financials


def _facts(section_or_facts, metric):
    facts = section_or_facts.facts if hasattr(section_or_facts, "facts") else section_or_facts
    return [fact for fact in facts if fact.metric == metric]


def test_bank_financials_preserve_rows_units_and_basis(fixture):
    summary = parse_financials(
        fixture("company_HBL.html"),
        source="https://dps.psx.com.pk/company/HBL",
    )

    assert summary.basis == "unknown"
    assert summary.unit_note == "All numbers in thousands (000's) except EPS"
    assert summary.annual.periods
    assert summary.annual.periods[0].value_semantics == "full_year"
    assert _facts(summary.annual, "markup_earned")
    assert _facts(summary.annual, "total_income")
    markup = _facts(summary.annual, "markup_earned")[0]
    assert markup.unit == "PKR"
    assert markup.unit_scale == 1000
    assert markup.normalized_value == markup.value * 1000
    eps = _facts(summary.annual, "eps")[0]
    assert eps.unit == "PKR/share"
    assert eps.unit_scale == 1
    assert eps.normalized_value == eps.value
    assert summary.ratios
    assert all(r.unit_scale == 1 for r in summary.ratios)
    assert any("accounting basis" in warning for warning in summary.warnings)


def test_industrial_financials_support_variable_rows_and_ratio_parentheses(fixture):
    summary = parse_financials(fixture("company_LUCK.html"))

    assert {fact.metric for fact in summary.annual.facts} >= {
        "sales",
        "profit_after_tax",
        "eps",
    }
    sales = _facts(summary.annual, "sales")[0]
    assert sales.value == 136527017.0
    assert sales.normalized_value == 136527017000.0
    eps_growth = _facts(summary.ratios, "eps_growth")
    assert eps_growth[-1].value == -56.08
    assert eps_growth[-1].normalized_value == -56.08
    assert summary.quarterly.periods[0].value_semantics == "unknown"
    assert any("Interim Q2/Q3 semantics" in warning for warning in summary.warnings)
    assert any(
        "standalone versus cumulative" in warning
        for period in summary.quarterly.periods
        for warning in period.warnings
    )


def test_technology_financials_do_not_depend_on_row_order_or_pat_presence(fixture):
    summary = parse_financials(fixture("company_SYS.html"))

    assert summary.annual.facts[0].metric == "eps"
    assert {fact.metric for fact in summary.annual.facts} == {
        "eps",
        "sales",
        "profit_after_tax",
    }
    assert not _facts(summary.quarterly, "profit_after_tax")
    assert _facts(summary.quarterly, "sales")
    assert _facts(summary.quarterly, "eps")


def test_airlink_summary_keeps_missing_sector_rows_missing(fixture):
    summary = parse_financials(fixture("company_AIRLINK.html"))

    assert _facts(summary.annual, "sales")
    assert _facts(summary.annual, "eps")
    assert not _facts(summary.annual, "profit_after_tax")
    assert summary.basis == "unknown"


def test_financials_preserve_null_cells_and_unknown_labels():
    html = """
    <div id="financials">
      <div class="tabs__panel" data-name="Annual"><table>
        <thead><tr><th></th><th>2025</th></tr></thead>
        <tbody>
          <tr><td>Profit after Taxation</td><td>-</td></tr>
          <tr><td>Other issuer KPI</td><td>12</td></tr>
        </tbody>
      </table></div>
    </div>
    """
    summary = parse_financials(html)

    pat = _facts(summary.annual, "profit_after_tax")[0]
    assert pat.value is None
    assert pat.normalized_value is None
    unknown = summary.annual.facts[1]
    assert unknown.raw_label == "Other issuer KPI"
    assert unknown.metric is None
    assert unknown.value == 12.0
    assert unknown.warnings


def test_financials_without_tables_degrade_with_warnings():
    summary = parse_financials("<html><body><p>no data</p></body></html>")

    assert summary.annual.periods == []
    assert summary.quarterly.facts == []
    assert summary.ratios == []
    assert summary.basis == "unknown"
    assert summary.warnings
    json.dumps(summary.to_dict())


def _table_html(headers=("2026", "2025", "2024"), rows=()):
    header_html = "".join(f"<th>{header}</th>" for header in ("Metric", *headers))
    body_html = "".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)
    return f"""
    <div id="financials"><div class="tabs__panel" data-name="Annual">
      <table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>
    </div></div>
    """


def _annual_facts(html):
    return parse_financials(html).annual.facts


def test_financial_grid_normal_alignment_preserves_distinct_columns():
    facts = _annual_facts(_table_html(rows=[("EPS", "111", "222", "333")]))

    assert [(fact.period, fact.value) for fact in facts] == [
        ("2026", 111.0),
        ("2025", 222.0),
        ("2024", 333.0),
    ]


def test_financial_grid_missing_final_explicit_cell_is_null_only_at_end():
    facts = _annual_facts(_table_html(rows=[("EPS", "111", "222", "")]))

    assert [fact.value for fact in facts] == [111.0, 222.0, None]


def test_financial_grid_empty_middle_cell_does_not_shift_later_value():
    facts = _annual_facts(_table_html(rows=[("EPS", "111", "", "333")]))

    assert [fact.value for fact in facts] == [111.0, None, 333.0]


def test_financial_grid_structurally_missing_middle_fails_closed():
    html = """
    <div id="financials"><div class="tabs__panel" data-name="Annual"><table>
      <thead><tr><th>Metric</th><th>2026</th><th>2025</th><th>2024</th></tr></thead>
      <tbody><tr><td>EPS</td><td>111</td><td>333</td></tr></tbody>
    </table></div></div>
    """
    summary = parse_financials(html)

    assert [fact.value for fact in summary.annual.facts] == [None, None, None]
    assert any("structurally missing" in warning for warning in summary.annual.warnings)


def test_financial_grid_colspan_does_not_duplicate_a_value_into_periods():
    html = """
    <div id="financials"><div class="tabs__panel" data-name="Annual"><table>
      <thead><tr><th>Metric</th><th>2026</th><th>2025</th><th>2024</th></tr></thead>
      <tbody><tr><td>EPS</td><td colspan="2">111</td><td>333</td></tr></tbody>
    </table></div></div>
    """
    summary = parse_financials(html)

    assert [fact.value for fact in summary.annual.facts] == [None, None, None]
    assert any("colspan" in warning for warning in summary.annual.warnings)


def test_financial_grid_blank_header_withholds_only_unnamed_slot():
    facts = _annual_facts(
        _table_html(headers=("2026", "", "2024"), rows=[("EPS", "111", "222", "333")])
    )

    assert [fact.value for fact in facts] == [111.0, None, 333.0]
    assert facts[1].period == ""
    assert any("blank" in warning.lower() for warning in facts[1].warnings)


def test_financial_grid_duplicate_header_withholds_duplicate_columns():
    html = _table_html(headers=("2026", "2026", "2024"), rows=[("EPS", "111", "222", "333")])
    facts = _annual_facts(html)

    assert [fact.value for fact in facts] == [None, None, 333.0]
    assert any(
        "Duplicate financial period header" in warning
        for warning in parse_financials(html).warnings
    )


def test_financial_grid_duplicate_row_label_preserves_both_source_rows():
    html = _table_html(rows=[("EPS", "111", "222", "333"), ("EPS", "444", "555", "666")])
    facts = _annual_facts(html)

    assert len(facts) == 6
    assert [fact.value for fact in facts[3:]] == [444.0, 555.0, 666.0]
    assert any(
        "Duplicate Annual row label" in warning for warning in parse_financials(html).warnings
    )


def test_financial_grid_extra_cells_fail_closed():
    html = _table_html(rows=[("EPS", "111", "222", "333", "999")])
    facts = _annual_facts(html)

    assert [fact.value for fact in facts] == [None, None, None]
    assert any("too many cells" in warning for warning in parse_financials(html).annual.warnings)


def test_financial_grid_fewer_cells_fail_closed_without_left_shift():
    html = _table_html(rows=[("EPS", "111", "222")])
    facts = _annual_facts(html)

    assert [fact.value for fact in facts] == [None, None, None]
    assert all(fact.raw_value == "" for fact in facts)
    assert any(
        "structurally missing" in warning for warning in parse_financials(html).annual.warnings
    )


def test_unknown_financial_units_are_not_scaled_and_percent_semantics_are_explicit():
    summary = parse_financials(
        _table_html(
            headers=("2025",),
            rows=[
                ("Book Value per Share", "10"),
                ("Dividend per Share", "2"),
                ("ROE (%)", "12.5"),
                ("Unknown Amount", "100"),
                ("Unknown Percentage (%)", "5"),
                ("Dividend Yield (%)", "4"),
            ],
        )
    )
    by_label = {fact.raw_label: fact for fact in summary.annual.facts}

    for label in ("Book Value per Share", "Dividend per Share", "Unknown Amount"):
        assert by_label[label].metric is None
        assert by_label[label].unit == "unknown"
        assert by_label[label].unit_scale is None
        assert by_label[label].normalized_value is None
        assert by_label[label].value is not None
    for label in ("ROE (%)", "Unknown Percentage (%)", "Dividend Yield (%)"):
        assert by_label[label].metric is None
        assert by_label[label].unit == "%"
        assert by_label[label].unit_scale == 1
        assert by_label[label].normalized_value == by_label[label].value


def test_financial_section_prefers_visible_candidate_over_hidden_mobile_duplicate():
    html = """
    <div id="financials" style="display:none"><div class="tabs__panel" data-name="Annual">
      <table><tr><th>Metric</th><th>2026</th></tr><tr><td>EPS</td><td>999</td></tr></table>
    </div></div>
    <div id="financials"><div class="tabs__panel" data-name="Annual">
      <table><tr><th>Metric</th><th>2026</th></tr><tr><td>EPS</td><td>111</td></tr></table>
    </div></div>
    """

    facts = parse_financials(html).annual.facts
    assert facts[0].value == 111.0
