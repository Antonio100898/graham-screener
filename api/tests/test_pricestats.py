"""Price-history statistics — pure arithmetic over a hand-built weekly series."""
from datetime import date, timedelta
from decimal import Decimal

from screener.pricestats import compute

END = date(2026, 8, 14)


def series(weekly):
    """Newest value last; index 0 is the oldest week."""
    n = len(weekly)
    return tuple((END - timedelta(weeks=n - 1 - i), Decimal(str(v))) for i, v in enumerate(weekly))


def test_distance_from_the_high_and_the_low():
    # five years of weekly closes: peak 200 four years ago, trough 50 last year, now 60
    closes = series([100] * 52 + [200] * 52 + [80] * 52 + [50] * 65 + [60] * 40)
    s = compute(closes, Decimal("60"))
    assert s["pct_below_52w_high"] == Decimal("0.00")      # 60 is the 52-week best
    assert s["pct_above_52w_low"] == Decimal("20.00")      # 20% above last year's 50
    assert s["pct_below_3y_high"] == Decimal("25.00")      # 80 sits inside three years
    assert s["pct_below_5y_high"] == Decimal("70.00")      # 200 does not
    assert s["price_to_3y_median"] == Decimal("1.00")      # 3-year median is 60


def test_drawdown_duration_counts_weeks_since_the_five_year_peak():
    closes = series([10] * 50 + [100] + [40] * 30)
    s = compute(closes, Decimal("40"))
    assert s["drawdown_weeks"] == 30
    assert s["pct_below_5y_high"] == Decimal("60.00")


def test_a_price_at_its_peak_has_no_drawdown():
    s = compute(series([10, 20, 30, 40]), Decimal("40"))
    assert s["drawdown_weeks"] == 0
    assert s["pct_below_5y_high"] == Decimal("0.00")


def test_a_live_quote_above_every_close_is_a_new_high_not_a_negative_distance():
    """The quote is this week's price, so it belongs inside the range it is
    measured against — otherwise a stock making a new high reads as -3% below it."""
    s = compute(series([10, 20, 30]), Decimal("40"))
    assert s["high_52w"] == Decimal("40.00")
    assert s["average_3y"] == Decimal("20.00")
    assert s["pct_vs_3y_average"] == Decimal("100.00")
    assert s["pct_below_52w_high"] == Decimal("0.00")
    assert s["pct_below_5y_high"] == Decimal("0.00")
    assert s["drawdown_weeks"] == 0


def test_a_quote_under_every_close_is_the_new_low():
    s = compute(series([30, 20, 10]), Decimal("5"))
    assert s["pct_above_52w_low"] == Decimal("0.00")
    assert s["pct_below_52w_high"] == Decimal("83.33")



def test_a_short_history_reports_what_exists():
    s = compute(series([10, 12, 9, 11]), Decimal("11"))
    assert s["history_weeks"] == 4
    assert s["pct_below_52w_high"] == s["pct_below_5y_high"] == Decimal("8.33")


def test_no_history_or_no_price_yields_nothing():
    assert compute((), Decimal("10")) is None
    assert compute(series([1, 2]), Decimal("0")) is None



