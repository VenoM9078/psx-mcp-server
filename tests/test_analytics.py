"""Deterministic tests for close-only price performance calculations."""

from __future__ import annotations

from datetime import date

from psx_mcp_server.analytics import (
    DEFAULT_WINDOWS,
    _max_drawdown,
    _prepare,
    _subtract_months,
    _subtract_years,
    calculate_price_performance,
)
from psx_mcp_server.models import EodBar


def _bars(values, volume_start=100):
    return [
        EodBar(date=day, open=close, close=close, volume=volume_start + index * 10)
        for index, (day, close) in enumerate(values)
    ]


def _long_history():
    return _bars(
        [
            ("2020-12-31", 90),
            ("2021-01-04", 100),
            ("2022-01-03", 120),
            ("2023-01-03", 110),
            ("2024-01-02", 130),
            ("2025-01-02", 125),
            ("2025-07-01", 140),
            ("2025-10-01", 130),
            ("2025-12-01", 150),
            ("2025-12-30", 155),
            ("2026-01-02", 150),
            ("2026-01-05", 160),
            ("2026-01-06", 176),
        ]
    )


def test_all_windows_and_benchmark_are_close_only_and_json_safe():
    stock = _long_history()
    benchmark = _bars([(bar.date, bar.close / 2) for bar in stock], volume_start=500)

    result = calculate_price_performance(
        stock,
        windows=list(DEFAULT_WINDOWS),
        benchmark_bars=benchmark,
        benchmark_symbol="KSE100",
    )

    assert set(result["windows"]) == set(DEFAULT_WINDOWS)
    assert all(result["windows"][window]["return_pct"] is not None for window in DEFAULT_WINDOWS)
    assert result["windows"]["YTD"]["actual_start"] == "2025-12-30"
    assert result["windows"]["YTD"]["requested_start"] == "2025-12-31"
    assert result["windows"]["1D"]["average_daily_volume"] == 215.0
    assert result["windows"]["5Y"]["volatility_pct"] is not None
    assert result["windows"]["5Y"]["max_drawdown_pct"] < 0
    assert result["windows"]["5Y"]["complete"] is True
    assert result["windows"]["5Y"]["coverage"] == "full"
    assert result["benchmark"]["symbol"] == "KSE100"
    assert result["windows"]["1D"]["relative_return_pct"] == 0.0
    assert not result["warnings"]


def test_weekend_start_matches_previous_trading_date():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
    )

    one_day = result["windows"]["1D"]
    assert one_day["requested_start"] == "2026-01-04"
    assert one_day["actual_start"] == "2026-01-02"
    assert one_day["return_pct"] == 10.0


def test_benchmark_aligns_to_stock_actual_dates():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-02", 50), ("2026-01-05", 55)]),
        benchmark_symbol="KSE100",
    )

    benchmark_window = result["benchmark"]["windows"]["1D"]
    assert benchmark_window["actual_start"] == "2026-01-02"
    assert benchmark_window["actual_end"] == "2026-01-05"
    assert benchmark_window["return_pct"] == 10.0
    assert result["windows"]["1D"]["relative_return_pct"] == 0.0


def test_insufficient_long_history_returns_available_value_with_warning():
    result = calculate_price_performance(
        _bars([("2025-01-02", 100), ("2026-01-02", 110)]),
        windows=["3Y", "5Y"],
    )

    assert result["windows"]["5Y"]["return_pct"] == 10.0
    assert result["windows"]["5Y"]["actual_start"] == "2025-01-02"
    assert any("5Y" in warning for warning in result["warnings"])


def test_no_data_and_zero_start_are_null_with_warnings():
    empty = calculate_price_performance([], windows=["1D"])
    assert empty["windows"] == {}
    assert empty["warnings"]

    zero = calculate_price_performance(
        _bars([("2026-01-01", 0), ("2026-01-02", 10)]),
        windows=["1D"],
    )
    assert zero["windows"]["1D"]["return_pct"] is None
    assert any("1D" in warning for warning in zero["warnings"])


def test_max_drawdown_is_a_negative_close_to_close_loss():
    assert _max_drawdown(_prepare(_bars([("2026-01-01", 100), ("2026-01-02", 110)]))) == 0.0
    assert (
        _max_drawdown(
            _prepare(_bars([("2026-01-01", 100), ("2026-01-02", 90), ("2026-01-03", 80)]))
        )
        == -20.0
    )
    assert (
        _max_drawdown(
            _prepare(
                _bars(
                    [
                        ("2026-01-01", 100),
                        ("2026-01-02", 120),
                        ("2026-01-03", 90),
                        ("2026-01-04", 110),
                    ]
                )
            )
        )
        == -25.0
    )


def test_calendar_window_boundaries_clamp_month_and_leap_day():
    assert _subtract_months(date(2024, 1, 31), 1) == date(2023, 12, 31)
    assert _subtract_months(date(2024, 2, 29), 1) == date(2024, 1, 29)
    assert _subtract_years(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_benchmark_missing_start_withholds_relative_return():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-03", 50), ("2026-01-05", 55)]),
        benchmark_symbol="KSE100",
    )

    benchmark = result["benchmark"]["windows"]["1D"]
    assert benchmark["alignment"] == "mismatched"
    assert result["windows"]["1D"]["relative_return_pct"] is None
    assert any(
        "2026-01-02" in warning and "2026-01-03" in warning for warning in result["warnings"]
    )


def test_benchmark_missing_end_withholds_relative_return():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-02", 50), ("2026-01-04", 55)]),
        benchmark_symbol="KSE100",
    )

    assert result["benchmark"]["windows"]["1D"]["actual_end"] == "2026-01-04"
    assert result["benchmark"]["windows"]["1D"]["alignment"] == "mismatched"
    assert result["windows"]["1D"]["relative_return_pct"] is None


def test_stock_short_history_is_machine_readable_and_can_align_to_benchmark():
    bars = _bars([("2026-01-03", 100), ("2026-01-05", 110)])
    result = calculate_price_performance(
        bars,
        windows=["1M"],
        benchmark_bars=_bars([("2026-01-03", 50), ("2026-01-05", 55)]),
        benchmark_symbol="KSE100",
    )

    assert result["windows"]["1M"]["complete"] is False
    assert result["windows"]["1M"]["coverage"] == "partial"
    assert result["windows"]["1M"]["relative_return_pct"] == 0.0


def test_benchmark_holiday_gap_is_mismatched_without_interpolation():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-02", 50), ("2026-01-06", 55)]),
        benchmark_symbol="KSE100",
    )

    assert result["benchmark"]["windows"]["1D"]["alignment"] == "mismatched"
    assert result["windows"]["1D"]["relative_return_pct"] is None


def test_benchmark_with_no_common_interval_is_unavailable():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2027-01-02", 50)]),
        benchmark_symbol="KSE100",
    )

    assert result["benchmark"]["windows"]["1D"]["alignment"] == "unavailable"
    assert result["windows"]["1D"]["relative_return_pct"] is None


def test_one_observation_does_not_create_a_misleading_relative_return():
    result = calculate_price_performance(
        _bars([("2026-01-02", 100), ("2026-01-05", 110)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-02", 50)]),
        benchmark_symbol="KSE100",
    )

    assert result["benchmark"]["windows"]["1D"]["alignment"] == "mismatched"
    assert result["windows"]["1D"]["relative_return_pct"] is None


def test_one_stock_observation_has_partial_coverage_and_no_return():
    result = calculate_price_performance(
        _bars([("2026-01-05", 100)]),
        windows=["1D"],
        benchmark_bars=_bars([("2026-01-05", 50)]),
        benchmark_symbol="KSE100",
    )

    stock = result["windows"]["1D"]
    assert stock["return_pct"] is None
    assert stock["complete"] is False
    assert stock["coverage"] == "partial"
    assert result["benchmark"]["windows"]["1D"]["alignment"] == "matched"
    assert result["benchmark"]["windows"]["1D"]["return_pct"] is None
    assert stock["relative_return_pct"] is None
