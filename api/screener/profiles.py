"""Graham applicability and alignment summaries for the dashboard.

These are deliberately separate from a strict screen verdict.  Graham stated
industrial and public-utility financial tests explicitly, but did not supply a
universal modern sector formula.  The dashboard therefore exposes both (a) the
profile to which a company belongs and (b) the evidence currently available.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .ch13 import _avg3

# Annual XBRL filing became mandatory for every filer size by fiscal 2011; a
# record that begins later marks a genuinely short public history, not a gap in
# the dataset. Windowed defensive tests need at least this many years to say
# anything about a company's record.
_XBRL_FULL_COVERAGE = 2011
_MIN_WINDOW_YEARS = 5

PROFILE_OPERATING = "OPERATING"
PROFILE_UTILITY = "UTILITY"
PROFILE_FINANCIAL = "FINANCIAL"
PROFILE_SPECIAL = "SPECIAL"
PROFILE_REVIEW = "REVIEW"

PROFILE_META = {
    PROFILE_OPERATING: {
        "label": "Industrial-style operating business",
        "short": "Operating",
        "detail": "Eligible for the Chapter 15 industrial financial-condition tests.",
    },
    PROFILE_UTILITY: {
        "label": "Public utility",
        "short": "Utility",
        "detail": "Use the defensive utility financial-position rule; the industrial current-ratio rule is not applicable.",
    },
    PROFILE_FINANCIAL: {
        "label": "Financial / real-estate structure",
        "short": "Financial",
        "detail": "Show valuation evidence, but do not present an industrial Graham verdict.",
    },
    PROFILE_SPECIAL: {
        "label": "Special structure",
        "short": "Special",
        "detail": "Shells and blank-check companies are outside the ordinary-company screens.",
    },
    PROFILE_REVIEW: {
        "label": "Manual applicability review",
        "short": "Review",
        "detail": "Sector or business-model classification is not reliable enough for a strict profile.",
    },
}


def _number(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _status(pass_: bool | None) -> str:
    if pass_ is None:
        return "INSUFFICIENT_DATA"
    return "PASS" if pass_ else "FAIL"


def profile_for(sector: str | None) -> str:
    """Return a cautious Graham applicability profile from the existing SIC sector."""
    if sector == "Utilities":
        return PROFILE_UTILITY
    if sector in {"Financials", "Real estate"}:
        return PROFILE_FINANCIAL
    if sector == "Shell & blank-check":
        return PROFILE_SPECIAL
    if sector in (None, "", "Other"):
        return PROFILE_REVIEW
    return PROFILE_OPERATING


def _eps_series(row: dict) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for year, value in (row.get("annual_eps") or {}).items():
        try:
            out[int(year)] = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return out


def _criterion_status(row: dict, number: int) -> str:
    for criterion in row.get("criteria") or ():
        if criterion.get("n") == number:
            return criterion.get("status") or "INSUFFICIENT_DATA"
    return "INSUFFICIENT_DATA"


def _pe3(row: dict) -> Decimal | None:
    """Current price over the three latest consecutive fiscal-year EPS values."""
    price = _number(row.get("price"))
    eps = _eps_series(row)
    if price is None or not eps:
        return None
    latest = max(eps)
    years = (latest - 2, latest - 1, latest)
    if any(year not in eps for year in years):
        return None
    average = sum((eps[year] for year in years), Decimal(0)) / Decimal(3)
    return price / average if average > 0 else None


def _summary(tests: dict[str, str], eligible: bool = True) -> dict:
    n_pass = sum(status == "PASS" for status in tests.values())
    n_fail = sum(status == "FAIL" for status in tests.values())
    n_unknown = len(tests) - n_pass - n_fail
    if not eligible:
        verdict = "OUT_OF_SCOPE"
    elif n_fail:
        verdict = "BLOCKED"
    elif n_unknown:
        verdict = "EVIDENCE_INCOMPLETE"
    else:
        verdict = "ALIGNED"
    return {"verdict": verdict, "passed": n_pass, "total": len(tests), "unknown": n_unknown, "tests": tests}


def _enterprising(row: dict, profile: str) -> dict:
    # The six existing test fields are kept intact.  The additional growth
    # comparison is a clearly marked modern 4-fiscal-year analogue, not
    # attributed as an original rolling Graham requirement.
    tests = {
        "valuation": _criterion_status(row, 1),
        "liquidity": _criterion_status(row, 2),
        "debt": _criterion_status(row, 3),
        "stability": _criterion_status(row, 4),
        "dividend": _criterion_status(row, 5),
        "tangible_assets": _criterion_status(row, 7),
    }
    eps = _eps_series(row)
    latest = max(eps) if eps else None
    base = latest - 4 if latest is not None else None
    if latest is None or base not in eps:
        growth = {"status": "INSUFFICIENT_DATA", "label": "Modern 4-FY EPS comparison", "base_fy": base, "latest_fy": latest}
    else:
        growth = {
            "status": "PASS" if eps[latest] > eps[base] else "FAIL",
            "label": "Modern 4-FY EPS comparison",
            "base_fy": base,
            "base_eps": float(eps[base]),
            "latest_fy": latest,
            "latest_eps": float(eps[latest]),
        }
    # Strictly, this is the book's industrial low-multiplier method.  We still
    # show the six direct tests outside the profile so a reader can inspect
    # valuation evidence, but never call it an enterprising alignment.
    result = _summary(tests, eligible=profile == PROFILE_OPERATING)
    result["growth_modern_4fy"] = growth
    result["profile_note"] = (
        "The four-year EPS comparison is a disclosed modern analogue; Graham named FY1966 and gave no rolling formula."
    )
    return result


def _defensive(row: dict, profile: str) -> dict:
    """Summarize defensive evidence without claiming a 20-year history that XBRL cannot prove."""
    eps = _eps_series(row)
    latest = max(eps) if eps else None
    first = min(eps) if eps else None
    recent10 = [eps.get(year) for year in range(latest - 9, latest + 1)] if latest else []
    # A record that only begins after full XBRL coverage belongs to a company with
    # a genuinely short public history, so its whole record IS the available
    # window. An older company's short series is dataset truncation, never a
    # licence to judge fewer years than Graham asked for. The company's own
    # first-ever SEC filing must corroborate the youth: ARCC's EPS record starts
    # in 2020 because the BDC per-share tag is young, but the company filed
    # since 2004 — without the corroboration it would earn unearned passes.
    first_filed = row.get("first_filed")
    listed_after_xbrl = bool(first_filed) and int(str(first_filed)[:4]) > _XBRL_FULL_COVERAGE
    span = latest - first + 1 if latest is not None else 0
    short_history = (
        latest is not None
        and first > _XBRL_FULL_COVERAGE
        and listed_after_xbrl
        and all(year in eps for year in range(first, latest + 1))
    )
    windowed: dict[str, str] = {}

    revenue = _number(row.get("ttm_revenue"))
    assets = _number(row.get("total_assets"))
    liabilities = _number(row.get("total_liabilities"))
    ca = _number(row.get("current_assets"))
    cl = _number(row.get("current_liabilities"))
    ltd = _number(row.get("long_term_debt"))
    shares = _number(row.get("shares"))
    bvps = _number(row.get("bvps"))
    price = _number(row.get("price"))
    pe3 = _pe3(row)

    if profile == PROFILE_UTILITY:
        size = _status(assets >= Decimal("50000000") if assets is not None else None)
        equity = assets - liabilities if assets is not None and liabilities is not None else None
        financial = _status(ltd <= Decimal("2") * equity if ltd is not None and equity is not None else None)
    elif profile == PROFILE_OPERATING:
        size = _status(revenue >= Decimal("100000000") if revenue is not None else None)
        if ca is None or cl is None or ltd is None or cl <= 0:
            financial = "INSUFFICIENT_DATA"
        else:
            working_capital = ca - cl
            financial = _status(ca >= Decimal("2") * cl and ltd <= working_capital)
    else:
        size = "NOT_APPLICABLE"
        financial = "NOT_APPLICABLE"

    if len(recent10) == 10 and not any(value is None for value in recent10):
        # Chapter 14 says "some earnings".  In literal mode, zero is not a
        # deficit; a product may offer a stricter positive-EPS profile later.
        stability = _status(all(value >= 0 for value in recent10))
    elif short_history and span >= _MIN_WINDOW_YEARS:
        stability = _status(all(eps[year] >= 0 for year in range(first, latest + 1)))
        windowed["stability_10y"] = (
            f"judged over the company's full {span}-year record (first FY {first})"
        )
    else:
        stability = "INSUFFICIENT_DATA"

    ch13 = row.get("ch13") or {}
    growth10 = _number(ch13.get("growth_10y"))
    if growth10 is not None:
        growth = _status(growth10 >= Decimal("33.3333333333"))
    else:
        growth = "INSUFFICIENT_DATA"
        if short_history:
            spacing = latest - (first + 2)
            base = _avg3(eps, first + 2)
            recent = _avg3(eps, latest)
            if spacing >= _MIN_WINDOW_YEARS and base is not None and recent is not None and base > 0:
                pct = float(recent / base - 1) * 100
                # Graham's 33 1/3 % is a per-decade rate; a shorter spacing gets
                # the same compound rate over the years the record actually has
                required = ((4 / 3) ** (spacing / 10) - 1) * 100
                growth = _status(pct >= required)
                windowed["growth_10y"] = (
                    f"{pct:+.1f}% over the {spacing}-year spacing the record allows; "
                    f"threshold scaled to {required:.1f}%"
                )

    record = row.get("dividend_record") or {}
    latest_dividend_year = record.get("latest")
    streak_start = record.get("streak_from")
    if _criterion_status(row, 5) == "FAIL":
        # Criterion 5 FAIL means the filer verifiably pays nothing now, and a
        # current non-payer cannot hold an uninterrupted 20-year record —
        # however far back the paid years reach.
        dividend = "FAIL"
    elif latest_dividend_year is None or streak_start is None:
        dividend = "INSUFFICIENT_DATA"
    elif latest_dividend_year - streak_start + 1 >= 20:
        dividend = "PASS"
    elif (
        short_history
        and span >= _MIN_WINDOW_YEARS
        # a mid-year listing may push the first payout into the next calendar
        # year, and the latest payout may trail the latest fiscal year by one
        and streak_start <= first + 1
        and latest_dividend_year >= latest - 1
    ):
        dividend = "PASS"
        windowed["dividend_20y"] = (
            f"paid every year of the company's {span}-year public record; "
            "20 years is longer than the company has traded"
        )
    else:
        # A short XBRL record cannot prove a 20-year uninterrupted record and
        # must not be turned into a fail merely because the dataset is young.
        dividend = "INSUFFICIENT_DATA"

    if pe3 is None or bvps is None or bvps <= 0 or price is None:
        valuation = "INSUFFICIENT_DATA"
    else:
        pb = price / bvps
        # Product policy: the defensive valuation comparison follows the same
        # two-decimal ratios displayed in the interface.  Thus a displayed
        # 22.50× product passes; a displayed 22.51× product fails.
        displayed_pe3 = pe3.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        displayed_product = (pe3 * pb).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        valuation = _status(displayed_pe3 <= Decimal("15.00") and displayed_product <= Decimal("22.50"))

    result = _summary(
        {
            "size": size,
            "financial_position": financial,
            "stability_10y": stability,
            "dividend_20y": dividend,
            "growth_10y": growth,
            "valuation": valuation,
        },
        eligible=profile in {PROFILE_OPERATING, PROFILE_UTILITY},
    )
    if windowed:
        result["windowed"] = windowed
    result["profile_note"] = (
        "Dividend history is evidence-incomplete unless this dataset itself proves an "
        "uninterrupted 20-year record — or the record covers the whole public life of "
        "a company listed after 2011 (disclosed per test)."
    )
    return result


def enrich(row: dict) -> dict:
    """Add compact, JSON-safe applicability and alignment fields to one dashboard row."""
    profile = profile_for(row.get("sector"))
    return {
        "graham_profile": profile,
        "graham_profile_meta": PROFILE_META[profile],
        "alignment": {
            "enterprising": _enterprising(row, profile),
            "defensive": _defensive(row, profile),
        },
    }
