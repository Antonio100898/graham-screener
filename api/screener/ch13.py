"""Chapter-13 comparison statistics derived from the annual EPS series.

Graham compares smoothed three-year earning-power levels roughly five and ten
years apart, tests stability as the worst decline against the trailing three-year
average, and asks for positive earnings in every one of the last ten years.
Everything here is arithmetic over the audited annual series — no criterion, no
verdict. A statistic whose input years are missing is omitted, never guessed:
each result names the years it rests on so the reader can see the basis.
"""
from __future__ import annotations

from decimal import Decimal


def _avg3(eps: dict[int, Decimal], last: int) -> Decimal | None:
    """Average of the three fiscal years ending at `last`; None unless all exist."""
    ys = (last - 2, last - 1, last)
    if any(y not in eps for y in ys):
        return None
    return sum(eps[y] for y in ys) / 3


def _growth(recent: Decimal | None, earlier: Decimal | None) -> float | None:
    """Total % change between two smoothed levels — not CAGR. A non-positive
    base makes the percentage meaningless (the criterion-6 lesson), so None."""
    if recent is None or earlier is None or earlier <= 0:
        return None
    return round(float((recent / earlier - 1) * 100), 1)


def eps_stats(eps: dict[int, Decimal]) -> dict | None:
    """All chapter-13 EPS statistics for one company, or None without a series."""
    if not eps:
        return None
    last = max(eps)
    avg_recent = _avg3(eps, last)
    avg_middle = _avg3(eps, last - 5)   # Graham's 1968-70 vs 1963-65 spacing
    avg_old = _avg3(eps, last - 10)     # ...vs 1958-60

    # stability: for each of the last ten years, the decline against the average
    # of the three preceding years; the worst one is the measure. A year is only
    # examined when all four inputs exist and the base average is positive.
    worst = None
    examined = []
    for t in range(last - 9, last + 1):
        base = _avg3(eps, t - 1)
        if t not in eps or base is None or base <= 0:
            continue
        examined.append(t)
        decline = max(Decimal(0), (base - eps[t]) / base * 100)
        if worst is None or decline > worst:
            worst = decline

    ten = [y for y in range(last - 9, last + 1) if y in eps]
    positive = [y for y in ten if eps[y] > 0]

    def f(v):
        return None if v is None else round(float(v), 2)

    return {
        "latest_fy": last,
        "avg_recent": f(avg_recent), "avg_middle": f(avg_middle), "avg_old": f(avg_old),
        "growth_5y": _growth(avg_recent, avg_middle),
        "growth_10y": _growth(avg_recent, avg_old),
        "max_decline": f(worst),
        "stability_years": len(examined),
        "ten_year_present": len(ten),
        "ten_year_positive": len(positive),
    }
