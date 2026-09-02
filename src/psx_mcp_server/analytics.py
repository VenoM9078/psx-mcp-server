"""Pure, close-only price analytics for EOD series."""

from __future__ import annotations

import calendar
import math
from datetime import date, timedelta
from statistics import stdev

from .models import EodBar

DEFAULT_WINDOWS = ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y")
WINDOWS = frozenset(DEFAULT_WINDOWS)


def calculate_price_performance(
    bars: list[EodBar],
    *,
    windows: list[str],
    benchmark_bars: list[EodBar] | None = None,
    benchmark_symbol: str | None = None,
) -> dict:
    """Calculate close-to-close performance with explicit calendar alignment."""
    if not windows:
        raise ValueError("windows must contain at least one supported window")
    prices, preparation_warnings = _prepare_with_warnings(bars)
    warnings = list(preparation_warnings)
    if not prices:
        return {
            "windows": {},
            "benchmark": None,
            "warnings": _unique([*warnings, "The EOD source returned no usable closing prices."]),
        }

    benchmark, benchmark_warnings = _prepare_with_warnings(benchmark_bars or [])
    warnings.extend(f"Benchmark: {warning}" for warning in benchmark_warnings)
    end_date = prices[-1][0]
    output_windows: dict[str, dict] = {}
    benchmark_windows: dict[str, dict] = {}

    for window in windows:
        result, _, history_short = _window_result(prices, window, end_date)
        output_windows[window] = result
        if result["return_pct"] is None or history_short:
            warnings.append(f"Insufficient or unusable EOD history for {window}.")

        if benchmark_symbol and benchmark:
            benchmark_result, benchmark_short = _benchmark_result(
                benchmark,
                window,
                result.get("actual_start"),
                result.get("actual_end"),
            )
            benchmark_windows[window] = benchmark_result
            if benchmark_result["return_pct"] is None or benchmark_short:
                warnings.append(f"Insufficient benchmark history for {window}.")
            exact_alignment = (
                benchmark_result["alignment"] == "matched"
                and result.get("actual_start") == benchmark_result.get("actual_start")
                and result.get("actual_end") == benchmark_result.get("actual_end")
            )
            if (
                exact_alignment
                and result["return_pct"] is not None
                and benchmark_result["return_pct"] is not None
            ):
                result["relative_return_pct"] = round(
                    result["return_pct"] - benchmark_result["return_pct"],
                    2,
                )
            else:
                result["relative_return_pct"] = None
                if benchmark_result["alignment"] == "mismatched":
                    warnings.append(
                        f"Benchmark interval mismatch for {window}: stock "
                        f"{result.get('actual_start')}..{result.get('actual_end')}; benchmark "
                        f"{benchmark_result.get('actual_start')}..{benchmark_result.get('actual_end')}."
                    )
        elif benchmark_symbol:
            benchmark_windows[window] = _benchmark_empty_result(
                window,
                result.get("actual_start"),
                result.get("actual_end"),
            )
            result["relative_return_pct"] = None
            warnings.append("The benchmark returned no usable closing prices.")

    benchmark_output = None
    if benchmark_symbol:
        benchmark_output = {
            "symbol": benchmark_symbol,
            "windows": benchmark_windows,
        }

    return {
        "windows": output_windows,
        "benchmark": benchmark_output,
        "warnings": _unique(warnings),
    }


def _prepare(bars: list[EodBar]) -> list[tuple[date, float, int]]:
    """Compatibility wrapper returning only usable sorted price rows."""
    prices, _ = _prepare_with_warnings(bars)
    return prices


def _prepare_with_warnings(
    bars: list[EodBar],
) -> tuple[list[tuple[date, float, int]], list[str]]:
    by_date: dict[date, tuple[float, int]] = {}
    warnings: list[str] = []
    duplicates = 0
    invalid = 0
    for bar in bars:
        if bar.close is None or not math.isfinite(bar.close):
            invalid += 1
            continue
        try:
            day = date.fromisoformat(bar.date)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if day in by_date:
            duplicates += 1
            continue
        by_date[day] = (float(bar.close), int(bar.volume))
    if invalid:
        warnings.append(f"Ignored {invalid} EOD bar(s) with an invalid date or close.")
    if duplicates:
        warnings.append(
            f"Ignored {duplicates} duplicate EOD date bar(s); the first bar was retained."
        )
    return [(day, values[0], values[1]) for day, values in sorted(by_date.items())], warnings


def _window_result(
    prices: list[tuple[date, float, int]],
    window: str,
    end_date: date,
) -> tuple[dict, list[tuple[date, float, int]], bool]:
    target = _target_start(end_date, window)
    start_index = _start_index(prices, target)
    if start_index is None:
        return (_empty_result(target, end_date), [], True)
    rows = prices[start_index:]
    start_day, start_close, _ = rows[0]
    _, end_close, _ = rows[-1]
    history_short = _history_is_short(start_day, target, window, end_date) or len(rows) < 2
    result = _return_result(target, start_day, end_date, start_close, end_close)
    if len(rows) < 2:
        result["return_pct"] = None
    result["average_daily_volume"] = round(sum(row[2] for row in rows) / len(rows), 2)
    result["volatility_pct"] = _volatility(rows)
    result["max_drawdown_pct"] = _max_drawdown(rows)
    result["complete"] = not history_short
    result["coverage"] = "full" if not history_short else "partial"
    return result, rows, history_short


def _benchmark_result(
    prices: list[tuple[date, float, int]],
    window: str,
    actual_start: str | None,
    actual_end: str | None,
) -> tuple[dict, bool]:
    if not actual_start or not actual_end:
        return _benchmark_empty_result(window, actual_start, actual_end), True
    try:
        start_target = date.fromisoformat(actual_start)
        end_target = date.fromisoformat(actual_end)
    except ValueError:
        return _benchmark_empty_result(window, actual_start, actual_end), True
    start_index = _start_index(prices, start_target)
    end_index = _end_index(prices, end_target)
    if start_index is None or end_index is None or end_index < start_index:
        return _benchmark_empty_result(window, actual_start, actual_end), True
    start_day, start_close, _ = prices[start_index]
    end_day, end_close, _ = prices[end_index]
    start_short = start_day > start_target
    end_short = end_day < end_target
    one_observation = end_index == start_index
    alignment = "matched" if start_day == start_target and end_day == end_target else "mismatched"
    result = _return_result(start_target, start_day, end_day, start_close, end_close)
    if one_observation:
        result["return_pct"] = None
    result.update(
        {
            "requested_window": window,
            "requested_start": result["requested_start"],
            "actual_start": result["actual_start"],
            "actual_end": result["actual_end"],
            "start_close": result["start_close"],
            "end_close": result["end_close"],
            "return_pct": result["return_pct"],
            "alignment": alignment,
            "complete": not (start_short or end_short or one_observation),
            "coverage": "full" if not (start_short or end_short or one_observation) else "partial",
        }
    )
    return result, start_short or end_short or one_observation


def _benchmark_empty_result(
    window: str,
    actual_start: str | None,
    actual_end: str | None,
) -> dict:
    return {
        "requested_window": window,
        "requested_start": actual_start,
        "actual_start": None,
        "actual_end": None,
        "start_close": None,
        "end_close": None,
        "return_pct": None,
        "alignment": "unavailable",
        "complete": False,
        "coverage": "partial",
    }


def _return_result(
    target: date | None,
    start_day: date | None,
    end_day: date | None,
    start_close: float | None,
    end_close: float | None,
) -> dict:
    return {
        "requested_start": target.isoformat() if target else None,
        "actual_start": start_day.isoformat() if start_day else None,
        "actual_end": end_day.isoformat() if end_day else None,
        "start_close": start_close,
        "end_close": end_close,
        "return_pct": _return_pct(start_close, end_close),
        "average_daily_volume": None,
        "volatility_pct": None,
        "max_drawdown_pct": None,
    }


def _empty_result(target: date | None, end_date: date | None) -> dict:
    result = _return_result(target, None, None, None, None)
    result["complete"] = False
    result["coverage"] = "partial"
    return result


def _return_pct(start_close: float | None, end_close: float | None) -> float | None:
    if start_close is None or end_close is None or start_close == 0:
        return None
    return round((end_close / start_close - 1) * 100, 2)


def _target_start(end_date: date, window: str) -> date:
    if window == "YTD":
        return date(end_date.year - 1, 12, 31)
    if window == "1D":
        return end_date - timedelta(days=1)
    if window == "1W":
        return end_date - timedelta(days=7)
    if window in {"1M", "3M", "6M"}:
        return _subtract_months(end_date, {"1M": 1, "3M": 3, "6M": 6}[window])
    if window in {"1Y", "3Y", "5Y"}:
        return _subtract_years(end_date, int(window[0]))
    raise ValueError(f"Unsupported performance window: {window}")


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _subtract_years(value: date, years: int) -> date:
    year = value.year - years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return date(year, value.month, day)


def _history_is_short(start_day: date, target: date, window: str, end_date: date) -> bool:
    """Flag a source series that starts after the requested calendar boundary."""
    return start_day > target


def _start_index(
    prices: list[tuple[date, float, int]],
    target: date,
    *,
    prefer_following: bool = False,
) -> int | None:
    if prefer_following:
        following = [index for index, row in enumerate(prices) if row[0] >= target]
        if following:
            return following[0]
    preceding = [index for index, row in enumerate(prices) if row[0] <= target]
    if preceding:
        return preceding[-1]
    following = [index for index, row in enumerate(prices) if row[0] >= target]
    return following[0] if following else None


def _end_index(prices: list[tuple[date, float, int]], target: date) -> int | None:
    preceding = [index for index, row in enumerate(prices) if row[0] <= target]
    return preceding[-1] if preceding else None


def _volatility(rows: list[tuple[date, float, int]]) -> float | None:
    returns = [
        current[1] / previous[1] - 1
        for previous, current in zip(rows, rows[1:], strict=False)
        if previous[1] != 0
    ]
    if len(returns) < 2:
        return None
    return round(stdev(returns) * math.sqrt(252) * 100, 2)


def _max_drawdown(rows: list[tuple[date, float, int]]) -> float | None:
    """Return the most negative close-to-close peak-to-trough loss percentage."""
    if not rows:
        return None
    peak = rows[0][1]
    maximum = 0.0
    for _, close, _ in rows:
        peak = max(peak, close)
        if peak > 0:
            maximum = min(maximum, (close / peak - 1) * 100)
    return round(maximum, 2)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
