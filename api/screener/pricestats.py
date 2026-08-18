"""Where the price sits inside its own history — pure functions, no I/O, no clock.

The screen answers "is this cheap against the business". These answer a different
question: "has the market already marked it down, and for how long". Graham's
enterprising method rests on a discrepancy between price and value, and a stock
sitting at the top of its range is a different proposition from the same
multiples reached after a two-year decline. None of this is a criterion — the
book has no rule about drawdowns — so every figure here is disclosure.

Everything here is the price against its own past — no earnings enter. A ratio
mixing the two would need a P/E per past week, and the only EPS series available
by date is the annual one, which puts it on a different basis from criterion 1's
trailing twelve months. Two P/Es in one panel is a trap; the multiples stay in
the screen, and this module answers "what has the market done to this price".

One limit, disclosed to the reader: the series is *weekly closes*, so a high is
the highest weekly close, never an intraday spike.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from statistics import median

_CENT = Decimal("0.01")
_YEAR = 365


def _pct(v: Decimal) -> Decimal:
    return v.quantize(_CENT)


def _window(closes: tuple[tuple[date, Decimal], ...], end: date, days: int):
    start = end - timedelta(days=days)
    return [c for d, c in closes if d >= start]


def _below_high(price: Decimal, closes: list[Decimal]) -> Decimal | None:
    """How far under the window's best close the price now sits.

    The live quote counts as part of the range it is being measured against — it
    is this week's price, and a stock making a new high is 0% below its high, not
    a negative distance from a stale weekly close.
    """
    if not closes:
        return None
    high = max(max(closes), price)
    return _pct((high - price) / high * 100) if high > 0 else None


def compute(closes: tuple[tuple[date, Decimal], ...], price: Decimal) -> dict | None:
    """`closes` ascending by date; `price` is the live quote."""
    if not closes or price is None or price <= 0:
        return None
    end = closes[-1][0]
    w52, w3y, w5y = (_window(closes, end, n * _YEAR) for n in (1, 3, 5))
    low52 = min(min(w52), price) if w52 else None
    high52 = max(max(w52), price) if w52 else None
    median3y = median(w3y) if w3y else None
    average3y = sum(w3y, Decimal(0)) / len(w3y) if w3y else None

    # a price at a new high has no drawdown to date, whatever the closes say
    peak = max(((d, c) for d, c in closes if d >= end - timedelta(days=5 * _YEAR)),
               key=lambda t: t[1])
    peak_date = end if price >= peak[1] else peak[0]

    return {
        "high_52w": high52.quantize(_CENT) if high52 is not None else None,
        "pct_below_52w_high": _below_high(price, w52),
        # a stock pinned to its low has not begun to recover; one far above it has
        "pct_above_52w_low": _pct((price - low52) / low52 * 100)
                             if low52 and low52 > 0 else None,
        "pct_below_3y_high": _below_high(price, w3y),
        "pct_below_5y_high": _below_high(price, w5y),
        # The average provides the requested current-versus-three-year reference;
        # it is contextual market history, never a Graham pass/fail input.
        "average_3y": average3y.quantize(_CENT) if average3y is not None else None,
        "pct_vs_3y_average": _pct((price - average3y) / average3y * 100)
                              if average3y and average3y > 0 else None,
        # The median remains available for tooltip context because it refuses to
        # be impressed by one irrational peak.
        "price_to_3y_median": _pct(price / median3y)
                              if median3y and median3y > 0 else None,
        # weeks since the last time the price stood at its five-year best: a
        # decline that ended last month reads very differently from one grinding
        # on for three years
        "drawdown_weeks": (end - peak_date).days // 7,
        "history_weeks": len(closes),
        "history_from": closes[0][0].isoformat(),
    }
