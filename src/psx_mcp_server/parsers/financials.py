"""Parse conservative financial-summary and ratio tables from company pages.

The PSX page is presentation HTML rather than a statement API. In particular,
the parser never compacts a malformed row to make it fit the header: a missing
placeholder, duplicate header, or spanning cell produces null values and a
warning instead of silently assigning a value to the wrong period.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .._util import parse_number
from ..models import FinancialFact, FinancialPeriod, FinancialSection, FinancialSummary

UNIT_NOTE = "All numbers in thousands (000's) except EPS"

_PERIOD_YEAR = re.compile(r"^(?:Q[1-3]\s+)?(\d{4})$")
_QUARTER = re.compile(r"^(Q[1-3])\s+(\d{4})$")

_METRIC_CODES = {
    "sales": "sales",
    "profit after taxation": "profit_after_tax",
    "eps": "eps",
    "mark-up earned": "markup_earned",
    "total income": "total_income",
    "gross profit margin (%)": "gross_profit_margin",
    "net profit margin (%)": "net_profit_margin",
    "eps growth (%)": "eps_growth",
    "peg": "peg",
}
_AMOUNT_METRICS = {"sales", "profit_after_tax", "markup_earned", "total_income"}
_PERCENT_METRICS = {"gross_profit_margin", "net_profit_margin", "eps_growth"}
_PERCENT_WORDS = ("margin", "growth", "roe", "roa", "dividend yield")


def parse_financials(html: str, *, source: str | None = None) -> FinancialSummary:
    """Parse annual/quarterly summaries and annual ratios with provenance warnings."""
    soup = BeautifulSoup(html, "lxml")
    financials, selection_warnings = _select_financials(soup)
    warnings: list[str] = [
        "The PSX company summary does not establish consolidated versus "
        "unconsolidated accounting basis; basis is unknown.",
        *selection_warnings,
    ]
    page_text = soup.get_text(" ", strip=True)
    has_unit_note = "All numbers in thousands" in page_text
    unit_note = (
        UNIT_NOTE if has_unit_note else "Source did not provide a financial-table unit note."
    )
    if not has_unit_note:
        warnings.append("The source did not provide the expected financial-table unit note.")
    if "Data powered by Capital Stake" in page_text:
        warnings.append(
            "The company page states that Capital Stake may standardize data; "
            "values may differ from the issuer's as-reported figures."
        )

    annual = FinancialSection()
    quarterly = FinancialSection()
    ratios: list[FinancialFact] = []

    if financials is None:
        warnings.append("The company page has no visible structured Financials section.")
    else:
        annual = _parse_tab(financials, "Annual", source=source)
        quarterly = _parse_tab(financials, "Quarterly", source=source)
        warnings.extend(annual.warnings)
        warnings.extend(quarterly.warnings)
        if quarterly.periods:
            warnings.append(
                "Interim Q2/Q3 semantics are not established by the source; "
                "no standalone/cumulative conversion is applied."
            )

    ratio_candidates = soup.select("#ratios table")
    ratio_tables = [table for table in ratio_candidates if _is_visible(table)]
    if ratio_candidates and not ratio_tables:
        warnings.append("Only hidden Ratios table candidates were found; none was parsed.")
    if len(ratio_tables) > 1:
        warnings.append(
            "Multiple visible Ratios tables were found; the semantically first table was used."
        )
        if _semantic_tie(ratio_tables, "Ratios"):
            warnings.append("Ratios table candidates remain semantically ambiguous.")
    if ratio_tables:
        ratio_periods, ratios, ratio_warnings = _parse_table(
            ratio_tables[0],
            kind="Ratios",
            source=source,
        )
        warnings.extend(ratio_warnings)
        if ratio_periods:
            warnings.append(
                "Ratio periods are source year labels; no accounting-basis or "
                "restatement metadata is supplied by this page."
            )

    sources = []
    if source:
        sources.append(
            {
                "url": source,
                "type": "company_html",
                "sections": ["Financials", "Ratios"],
            }
        )

    return FinancialSummary(
        annual=annual,
        quarterly=quarterly,
        ratios=ratios,
        basis="unknown",
        unit_note=unit_note,
        sources=sources,
        warnings=_unique(warnings),
    )


def _parse_tab(
    financials: Tag,
    tab_name: str,
    *,
    source: str | None,
) -> FinancialSection:
    panels = [
        panel
        for panel in financials.select(f'.tabs__panel[data-name="{tab_name}"]')
        if _is_visible(panel)
    ]
    if not panels:
        hidden_panels = financials.select(f'.tabs__panel[data-name="{tab_name}"]')
        if hidden_panels:
            return FinancialSection(
                warnings=[f"The {tab_name} financial table candidates were hidden."]
            )
        return FinancialSection()
    panel = _best_table_container(panels, tab_name)
    selection_warnings: list[str] = []
    if len(panels) > 1:
        selection_warnings.append(
            f"Multiple visible {tab_name} panel candidates were found; the semantically "
            "best panel was used."
        )
        if _semantic_tie(panels, tab_name):
            selection_warnings.append(f"{tab_name} panel candidates remain semantically ambiguous.")
    tables = [table for table in panel.find_all("table") if _is_visible(table)]
    if not tables:
        return FinancialSection(warnings=[f"The visible {tab_name} panel has no table."])
    if len(tables) > 1:
        table = _best_table_container(tables, tab_name)
        selection_warnings.append(
            f"Multiple visible {tab_name} table candidates were found; the semantically "
            "best candidate was used."
        )
    else:
        table = tables[0]
    if len(tables) > 1 and _semantic_tie(tables, tab_name):
        selection_warnings.append(f"{tab_name} table candidates remain semantically ambiguous.")
    periods, facts, table_warnings = _parse_table(table, kind=tab_name, source=source)
    warnings = [*selection_warnings, *table_warnings]
    return FinancialSection(periods=periods, facts=facts, warnings=_unique(warnings))


def _parse_table(
    table: Tag,
    *,
    kind: str,
    source: str | None,
) -> tuple[list[FinancialPeriod], list[FinancialFact], list[str]]:
    header_row = table.select_one("thead tr") or table.select_one("tr")
    if header_row is None:
        return ([], [], [f"The {kind} table has no header row."])

    header_cells, header_warnings = _expand_row(header_row)
    if len(header_cells) < 2:
        return ([], [], [f"The {kind} table header has fewer than two columns."])
    period_cells = header_cells[1:]
    period_labels = [_cell_text(cell) if cell is not None else "" for cell in period_cells]
    if not any(period_labels):
        return ([], [], [f"The {kind} table has no usable period headers."])

    periods = [_period_from_label(label, kind) for label in period_labels]
    warnings = list(header_warnings)
    duplicate_headers = {
        label for label in period_labels if label and period_labels.count(label) > 1
    }
    if duplicate_headers:
        warnings.append(
            "Duplicate financial period header(s) found; values in those columns were left null: "
            + ", ".join(sorted(duplicate_headers))
        )
    blank_header_indexes = {index for index, label in enumerate(period_labels) if not label}
    if blank_header_indexes:
        warnings.append("One or more financial period headers are blank; those values are unknown.")

    body_rows = table.select("tbody tr")
    if not body_rows:
        all_rows = table.select("tr")
        body_rows = all_rows[1:] if len(all_rows) > 1 else []

    facts: list[FinancialFact] = []
    seen_row_labels: set[str] = set()
    table_has_rowspan = any(
        _span_value(cell, "rowspan") > 1 for cell in table.find_all(["td", "th"])
    )
    if table_has_rowspan:
        warnings.append(
            f"The {kind} table uses rowspan; affected values were left null because row ownership "
            "is not safely reconstructable."
        )

    expected_cells = len(period_labels) + 1
    for row in body_rows:
        cells, row_warnings = _expand_row(row)
        if not cells:
            continue
        label_cell = cells[0] if cells else None
        raw_label = _cell_text(label_cell)
        if not raw_label:
            warnings.append(f"Skipped a {kind} row without a financial label.")
            continue
        normalized_row_label = re.sub(r"\s+", " ", raw_label.lower())
        duplicate_row = normalized_row_label in seen_row_labels
        if duplicate_row:
            warnings.append(f"Duplicate {kind} row label preserved: {raw_label}.")
        seen_row_labels.add(normalized_row_label)

        aligned_cells, alignment_warnings = _align_row(cells, expected_cells, kind)
        row_warnings = [*row_warnings, *alignment_warnings]
        warnings.extend(row_warnings)
        row_is_ambiguous = bool(row_warnings) or table_has_rowspan
        for index, period_label in enumerate(period_labels):
            cell = aligned_cells[index + 1] if index + 1 < len(aligned_cells) else None
            raw_value = _cell_text(cell)
            fact_warnings = list(row_warnings)
            force_unusable = row_is_ambiguous
            if index in blank_header_indexes:
                force_unusable = True
                fact_warnings.append("The value has no non-blank period header.")
            if period_label in duplicate_headers:
                force_unusable = True
                fact_warnings.append("The value has a duplicate period header.")
            if duplicate_row:
                fact_warnings.append(
                    "The row label is duplicated; both source rows were preserved."
                )
            facts.append(
                _fact(
                    raw_label,
                    period_label,
                    raw_value,
                    kind,
                    source,
                    force_unusable=force_unusable,
                    extra_warnings=fact_warnings,
                )
            )
    return (periods, facts, _unique(warnings))


def _align_row(
    cells: list[Tag | None],
    expected_cells: int,
    kind: str,
) -> tuple[list[Tag | None], list[str]]:
    if len(cells) == expected_cells:
        return cells, []
    if len(cells) < expected_cells:
        return (
            [cells[0] if cells else None, *([None] * (expected_cells - 1))],
            [
                f"A {kind} row has structurally missing cell(s); period alignment is ambiguous "
                "and all values in the row were left null."
            ],
        )
    return (
        [cells[0] if cells else None, *([None] * (expected_cells - 1))],
        [
            f"A {kind} row has too many cells; period alignment is ambiguous and all values in "
            "the row were left null."
        ],
    )


def _expand_row(row: Tag) -> tuple[list[Tag | None], list[str]]:
    """Expand explicit colspan positions without ever repeating a value."""
    cells = row.find_all(["th", "td"], recursive=False)
    expanded: list[Tag | None] = []
    warnings: list[str] = []
    for cell in cells:
        colspan = _span_value(cell, "colspan")
        rowspan = _span_value(cell, "rowspan")
        if rowspan > 1:
            warnings.append("A rowspan cell prevents safe financial-grid reconstruction.")
        if colspan > 1:
            # Keep the source cell in each logical slot so its raw text is not
            # lost, but the row warning below ensures no duplicated value is
            # normalized into multiple periods.
            expanded.extend([cell] * colspan)
            warnings.append("A colspan cell prevents safe period alignment for that row.")
        else:
            expanded.append(cell)
    return expanded, _unique(warnings)


def _span_value(cell: Tag, attribute: str) -> int:
    try:
        value = int(cell.get(attribute, 1))
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _select_financials(soup: BeautifulSoup) -> tuple[Tag | None, list[str]]:
    candidates = soup.select("#financials")
    visible = [candidate for candidate in candidates if _is_visible(candidate)]
    if not visible:
        if candidates:
            return None, ["Only hidden Financials section candidates were found; none was parsed."]
        return None, []
    if len(visible) == 1:
        return visible[0], []
    ranked = sorted(visible, key=lambda item: _semantic_score(item, "Financials"), reverse=True)
    warnings = [
        "Multiple visible Financials section candidates were found; the semantically best "
        "candidate was used."
    ]
    if len(ranked) > 1 and _semantic_score(ranked[0], "Financials") == _semantic_score(
        ranked[1], "Financials"
    ):
        warnings.append("Financials section candidates remain semantically ambiguous.")
    return ranked[0], warnings


def _best_table_container(candidates: list[Tag], kind: str) -> Tag:
    return max(candidates, key=lambda item: _semantic_score(item, kind))


def _semantic_tie(candidates: list[Tag], kind: str) -> bool:
    scores = sorted((_semantic_score(candidate, kind) for candidate in candidates), reverse=True)
    return len(scores) > 1 and scores[0] == scores[1]


def _semantic_score(tag: Tag, kind: str) -> int:
    text = tag.get_text(" ", strip=True).lower()
    score = 0
    if kind.lower() in text:
        score += 1
    if "annual" in text:
        score += 2
    if "quarter" in text:
        score += 2
    if tag.find("thead") is not None:
        score += 2
    if tag.find("table") is not None:
        score += 1
    classes = " ".join(tag.get("class", [])).lower()
    if "mobile" in classes:
        score -= 2
    return score


def _is_visible(tag: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if current.has_attr("hidden"):
            return False
        style = str(current.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return False
        classes = {str(value).lower() for value in current.get("class", [])}
        if classes & {"d-none", "hidden", "invisible", "mobile-only", "mobile-hidden"}:
            return False
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return True


def _period_from_label(label: str, kind: str) -> FinancialPeriod:
    fiscal_year: int | None = None
    normalized_period: str | None = None
    semantics = "unknown"
    period_warnings: list[str] = []

    if not label:
        period_warnings.append("The period header is blank; no period can be assigned.")
    elif kind == "Annual" and re.fullmatch(r"\d{4}", label):
        fiscal_year = int(label)
        normalized_period = "FY"
        semantics = "full_year"
    else:
        quarter = _QUARTER.fullmatch(label)
        if quarter:
            normalized_period = quarter.group(1)
            fiscal_year = int(quarter.group(2))
            period_warnings.append(
                "The source labels this interim column but does not establish "
                "standalone versus cumulative value semantics."
            )
        else:
            year_match = _PERIOD_YEAR.fullmatch(label)
            if year_match:
                fiscal_year = int(year_match.group(1))

    return FinancialPeriod(
        raw_label=label,
        normalized_period=normalized_period,
        fiscal_year=fiscal_year,
        value_semantics=semantics,
        period_start=None,
        period_end=None,
        publication_date=None,
        warnings=period_warnings,
    )


def _fact(
    raw_label: str,
    period_label: str,
    raw_value: str,
    kind: str,
    source: str | None,
    *,
    force_unusable: bool = False,
    extra_warnings: tuple[str, ...] | list[str] = (),
) -> FinancialFact:
    normalized_label = re.sub(r"\s+", " ", raw_label.strip().lower())
    metric = _METRIC_CODES.get(normalized_label)
    is_eps = metric == "eps"
    is_ratio = kind == "Ratios"
    explicit_percent = "%" in normalized_label or any(
        word in normalized_label for word in _PERCENT_WORDS
    )

    if metric in _PERCENT_METRICS or explicit_percent:
        unit = "%"
        unit_scale: int | None = 1
    elif metric == "peg" or is_ratio:
        unit = "ratio"
        unit_scale = 1
    elif is_eps:
        unit = "PKR/share"
        unit_scale = 1
    elif metric in _AMOUNT_METRICS:
        unit = "PKR"
        unit_scale = 1000
    else:
        unit = "unknown"
        unit_scale = None

    value = parse_number(raw_value)
    parsed_value = None if force_unusable else value
    normalized_value = (
        None if parsed_value is None or unit_scale is None else parsed_value * unit_scale
    )
    fact_warnings: list[str] = list(extra_warnings)
    if value is None and raw_value:
        fact_warnings.append("The displayed value could not be parsed as a number.")
    if metric is None:
        fact_warnings.append("No confident normalized metric code exists; raw label is preserved.")
    if unit == "unknown":
        fact_warnings.append(
            "The source does not establish a safe unit or scaling rule for this row."
        )
    if force_unusable:
        fact_warnings.append(
            "The parsed value was withheld because its period alignment is ambiguous."
        )

    return FinancialFact(
        period=period_label,
        raw_label=raw_label,
        metric=metric,
        raw_value=raw_value,
        value=parsed_value,
        unit=unit,
        unit_scale=unit_scale,
        normalized_value=normalized_value,
        source=source,
        warnings=_unique(fact_warnings),
    )


def _cell_text(cell: Tag | None) -> str:
    return cell.get_text(" ", strip=True) if cell is not None else ""


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
