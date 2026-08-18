"""Chapter-13 statistics: smoothed averages, growth, stability, ten-year record."""
from decimal import Decimal

from screener.ch13 import eps_stats


def series(vals, last=2025):
    return {last - len(vals) + 1 + i: Decimal(str(v)) for i, v in enumerate(vals)}


def test_three_period_averages_and_growth():
    # 13 flat-growing years: 1..13 ending FY2025
    s = eps_stats(series(list(range(1, 14))))
    assert s["avg_recent"] == 12.0    # (11+12+13)/3
    assert s["avg_middle"] == 7.0     # (6+7+8)/3, five years earlier
    assert s["avg_old"] == 2.0        # (1+2+3)/3, ten years earlier
    assert s["growth_5y"] == round((12 / 7 - 1) * 100, 1)
    assert s["growth_10y"] == 500.0
    assert s["ten_year_positive"] == 10 and s["ten_year_present"] == 10


def test_short_series_omits_what_it_cannot_average():
    s = eps_stats(series([5, 6, 7]))          # three years only
    assert s["avg_recent"] == 6.0
    assert s["avg_middle"] is None and s["avg_old"] is None
    assert s["growth_5y"] is None and s["growth_10y"] is None
    assert s["ten_year_present"] == 3


def test_growth_refuses_a_non_positive_base():
    vals = [-1, -1, -1] + [1] * 7 + [4, 5, 6]  # old period averages below zero
    s = eps_stats(series(vals))
    assert s["avg_old"] == -1.0
    assert s["growth_10y"] is None             # percentage from a loss base is noise


def test_stability_finds_the_worst_decline():
    # steady 10s, one collapse to 4 in 2020: decline (10-4)/10 = 60%
    vals = [10] * 8 + [4] + [10] * 5
    s = eps_stats(series(vals))
    assert s["max_decline"] == 60.0
    assert s["stability_years"] == 10


def test_stability_ignores_gains_and_reports_zero_for_a_clean_record():
    s = eps_stats(series([3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7]))
    assert s["max_decline"] == 0.0             # rises never count as declines


def test_loss_years_counted_in_ten_year_record():
    vals = [1] * 9 + [-2] + [1] * 3
    s = eps_stats(series(vals))
    assert s["ten_year_present"] == 10
    assert s["ten_year_positive"] == 9


def test_empty_series_is_none():
    assert eps_stats({}) is None
