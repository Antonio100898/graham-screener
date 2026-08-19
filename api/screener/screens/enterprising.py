"""Layer 3: Graham Enterprising screen. Pure functions — no network, filesystem, or clock."""
from __future__ import annotations

from decimal import Decimal

from ..models import (
    CriterionResult,
    EpsGrowth,
    FinancialSnapshot,
    Quote,
    ScreenResult,
    Status,
    Verdict,
)

# A live price divided by long-dead earnings is not a valuation. Dormant filers
# keep their ticker and their last figures forever, so the price's own timestamp
# is compared against the newest fundamentals — the screen stays clock-free.
STALE_FOR_PRICING_DAYS = 450  # an annual-only filer legitimately lags ~15 months

PE_MAX = Decimal("10.0")
CURRENT_RATIO_MIN = Decimal("1.50")
DEBT_TO_NCA_MAX = Decimal("1.10")
PRICE_TO_TBV_MAX = Decimal("1.20")

_CENT = Decimal("0.01")
_YIELD_IMPLAUSIBLE = Decimal("100")  # per cent


def evaluate(snapshot: FinancialSnapshot, quote: Quote | None) -> ScreenResult:
    # Graham's earnings-growth requirement is deliberately absent. It compared the
    # latest year against a fixed 1966 base; the book supplies no rule for picking
    # that base in any other year, so every modern substitute is someone else's
    # criterion wearing his name. The comparison is still computed and reported —
    # see _eps_growth — but nothing in the screen turns on it.
    criteria = (
        _c1_earnings_valuation(snapshot, quote),
        _c2_liquidity(snapshot),
        _c3_debt(snapshot),
        _c4_earnings_stability(snapshot),
        _c5_dividend(snapshot, quote),
        _c7_tangible_asset_valuation(snapshot, quote),
    )
    return ScreenResult(
        ticker=snapshot.ticker,
        cik=snapshot.cik,
        verdict=_verdict(criteria),
        criteria=criteria,
        quote=quote,
        balance_sheet_date=snapshot.balance_sheet_date,
        annual_eps_series={y: f.value for y, f in sorted(snapshot.annual_eps.items())},
        assumptions=tuple(sorted(snapshot.assumed_zero)),
        eps_growth=_eps_growth(snapshot),
    )


def _verdict(criteria: tuple[CriterionResult, ...]) -> Verdict:
    statuses = {c.status for c in criteria}
    # §4.4 requires that missing data never *silently* becomes a failure. A criterion
    # that was actually measured and failed is not silent: the company definitively
    # fails the screen, and what else is unknown cannot rescue it. So a real FAIL is
    # reported as FAIL, and INDETERMINATE is reserved for "nothing definitive known".
    if Status.FAIL in statuses:
        return Verdict.FAIL
    if Status.INSUFFICIENT_DATA in statuses:
        return Verdict.INDETERMINATE
    if Status.NOT_APPLICABLE in statuses:  # N/A never permits an overall PASS
        return Verdict.INDETERMINATE
    return Verdict.PASS


def _unclassified_balance_sheet(s: FinancialSnapshot) -> bool:
    # Banks/REITs file no classified balance sheet: AssetsCurrent absent while Assets exists
    return s.current_assets is None and s.current_liabilities is None and s.total_assets is not None


_NA_NOTE = "no classified balance sheet (typical for banks/REITs); criterion not assessable"


def _stale_against(quote: Quote | None, asof) -> int | None:
    """Days between the newest fundamentals and the price they'd be valued against."""
    if quote is None or asof is None:
        return None
    return (quote.asof.date() - asof).days


def _c1_earnings_valuation(s: FinancialSnapshot, q: Quote | None) -> CriterionResult:
    name, threshold = "Earnings valuation", "P/E < 10.0"
    if q is None or s.ttm_eps is None:
        missing = "price quote" if q is None else "TTM EPS"
        return CriterionResult(1, name, Status.INSUFFICIENT_DATA, None, threshold, s.ttm_eps_inputs,
                               note=f"{missing} unavailable")
    earnings_end = max((f.provenance.period_end for f in s.ttm_eps_inputs
                        if f.provenance.period_end), default=None)
    age = _stale_against(q, earnings_end)
    if age is not None and age > STALE_FOR_PRICING_DAYS:
        return CriterionResult(
            1, name, Status.INSUFFICIENT_DATA, None, threshold, s.ttm_eps_inputs,
            note=f"newest earnings end {earnings_end} — {age // 365} years before this price; "
                 "the company appears to have stopped filing, so no P/E is meaningful")
    if s.ttm_eps <= 0:
        return CriterionResult(1, name, Status.FAIL, None, threshold, s.ttm_eps_inputs,
                               note="TTM EPS non-positive; P/E undefined")
    # Decide with raw Decimal values. A rounded display ratio must never flip a pass.
    pe = (q.price / s.ttm_eps).quantize(_CENT)
    status = Status.PASS if q.price < PE_MAX * s.ttm_eps else Status.FAIL
    return CriterionResult(1, name, status, pe, threshold, s.ttm_eps_inputs)


def _c2_liquidity(s: FinancialSnapshot) -> CriterionResult:
    name, threshold = "Liquidity", "Current Ratio >= 1.50"
    if _unclassified_balance_sheet(s):
        return CriterionResult(2, name, Status.NOT_APPLICABLE, None, threshold, (), note=_NA_NOTE)
    if s.current_assets is None or s.current_liabilities is None:
        return CriterionResult(2, name, Status.INSUFFICIENT_DATA, None, threshold, (),
                               note="current assets or current liabilities unavailable")
    if s.current_liabilities.value <= 0:
        return CriterionResult(2, name, Status.INSUFFICIENT_DATA, None, threshold,
                               (s.current_assets, s.current_liabilities),
                               note="non-positive current liabilities reported; ratio undefined")
    ratio = (s.current_assets.value / s.current_liabilities.value).quantize(_CENT)
    status = (Status.PASS if s.current_assets.value >= CURRENT_RATIO_MIN * s.current_liabilities.value
              else Status.FAIL)
    return CriterionResult(2, name, status, ratio, threshold, (s.current_assets, s.current_liabilities))


def _c3_debt(s: FinancialSnapshot) -> CriterionResult:
    name, threshold = "Debt", "Total Debt <= 1.10 x Net Current Assets"
    if _unclassified_balance_sheet(s):
        return CriterionResult(3, name, Status.NOT_APPLICABLE, None, threshold, (), note=_NA_NOTE)
    if s.current_assets is None or s.current_liabilities is None:
        return CriterionResult(3, name, Status.INSUFFICIENT_DATA, None, threshold, (),
                               note="current assets or current liabilities unavailable")
    inputs = (s.current_assets, s.current_liabilities)
    notes = []
    # Negative net current assets settle the criterion by themselves: no debt
    # figure, known or missing, can bring debt <= 1.10 x NCA back within reach.
    if s.current_assets.value - s.current_liabilities.value < 0:
        return CriterionResult(3, name, Status.FAIL, None, threshold, inputs,
                               note="non-positive net current assets")
    if s.total_debt is not None:
        debt = s.total_debt.value
        inputs += (s.total_debt,)
    else:
        assumed = "debt" in s.assumed_zero
        parts = {"long-term debt": s.long_term_debt, "short-term debt": s.short_term_debt}
        missing = [k for k, f in parts.items() if f is None]
        inputs += tuple(f for f in parts.values() if f is not None)
        if missing and not assumed:
            # §5.1: missing is not zero — an absent debt tag is unknown, not debt-free
            return CriterionResult(3, name, Status.INSUFFICIENT_DATA, None, threshold, inputs,
                                   note="missing: " + ", ".join(missing))
        if missing:
            notes.append("assumed 0 for " + ", ".join(missing)
                         + " (no debt evidence in any filing; assume_absent_zero opt-in)")
        debt = sum((f.value for f in parts.values() if f is not None), Decimal(0))
    nca = s.current_assets.value - s.current_liabilities.value
    status = Status.PASS if debt <= DEBT_TO_NCA_MAX * nca else Status.FAIL
    ratio = (debt / nca).quantize(_CENT) if nca > 0 else None
    if nca <= 0:
        notes.append("non-positive net current assets")
    return CriterionResult(3, name, status, ratio, threshold, inputs,
                           note="; ".join(notes) or None)


def _c4_earnings_stability(s: FinancialSnapshot) -> CriterionResult:
    name, threshold = "Earnings stability", "EPS >= 0 in each of the past 5 fiscal years"
    if not s.annual_eps:
        return CriterionResult(4, name, Status.INSUFFICIENT_DATA, None, threshold, (),
                               note="no annual EPS available")
    latest = max(s.annual_eps)
    window = range(latest - 4, latest + 1)
    present = [y for y in window if y in s.annual_eps]
    # Chapter 15 says "no deficit". A zero year is not a deficit; a product that
    # wants a stricter positive-EPS adaptation can layer it separately.
    losses = [y for y in present if s.annual_eps[y].value < 0]
    facts = tuple(s.annual_eps[y] for y in present)
    # A loss already in the window settles it: the years we are missing cannot
    # undo one that happened. Only an unbroken run of profits can be incomplete.
    if losses:
        return CriterionResult(
            4, name, Status.FAIL, min(f.value for f in facts), threshold, facts,
            note="negative EPS in FY " + ", ".join(map(str, losses))
            + (f" (only {len(present)} of 5 years on file)" if len(present) < 5 else ""))
    missing = [y for y in window if y not in s.annual_eps]
    if missing:
        return CriterionResult(4, name, Status.INSUFFICIENT_DATA, None, threshold, facts,
                               note="profitable in every year on file, but missing annual EPS "
                                    "for FY " + ", ".join(map(str, missing)))
    return CriterionResult(4, name, Status.PASS, min(f.value for f in facts), threshold, facts)


def _c5_dividend(s: FinancialSnapshot, q: Quote | None) -> CriterionResult:
    name, threshold = "Dividend", "currently pays a dividend"
    if s.pays_dividend is None:
        return CriterionResult(5, name, Status.INSUFFICIENT_DATA, None, threshold, (),
                               note="dividend status could not be established")
    if s.pays_dividend:
        inputs = (s.dividend,) if s.dividend else ()
        # the test is yes/no, but the yield is what a reader actually wants to see
        yield_pct = None
        note = None
        if s.dividend_per_share is not None and q is not None and q.price > 0:
            pct = (s.dividend_per_share / q.price * 100).quantize(_CENT)
            note = f"{s.dividend_per_share.quantize(_CENT)} per share over twelve months"
            # A yield above par is arithmetic, not information: it means the price and
            # the payment describe different securities — a preferred-share ticker
            # mapped to the parent's facts, or a stub price against a real dividend.
            # The test is unaffected either way; only the figure is withheld.
            if pct <= _YIELD_IMPLAUSIBLE:
                yield_pct = pct
            else:
                note += f"; yield of {pct}% is not meaningful against this price"
        return CriterionResult(5, name, Status.PASS, yield_pct, threshold, inputs, note=note)
    return CriterionResult(5, name, Status.FAIL, None, threshold, (),
                           note="no dividend payments found in recent filings")


def _eps_growth(s: FinancialSnapshot) -> EpsGrowth | None:
    """Latest annual EPS beside the best year 4-7 years back — reported, never scored.

    The window is the closest honest stand-in for Graham's 1966 base: far enough
    back to span a cycle, and taking its best year keeps a trough from making the
    comparison flattering. That is a reading of what he was after, not his rule,
    which is exactly why it produces a number for the reader rather than a verdict.
    """
    if not s.annual_eps:
        return None
    latest = max(s.annual_eps)
    window = {y: f for y, f in s.annual_eps.items() if latest - 7 <= y <= latest - 4}
    if not window:
        return None
    base = max(window, key=lambda y: window[y].value)
    return EpsGrowth(base_fiscal_year=base, base_eps=window[base].value,
                     latest_fiscal_year=latest, latest_eps=s.annual_eps[latest].value)


def _c7_tangible_asset_valuation(s: FinancialSnapshot, q: Quote | None) -> CriterionResult:
    name, threshold = "Tangible-asset valuation", "Price < 1.20 x TBVPS"
    required = {
        "total assets": s.total_assets,
        "total liabilities": s.total_liabilities,
        "goodwill": s.goodwill,  # §5.1: absent goodwill is unknown, never zero
        "intangibles": s.intangibles,
        "shares outstanding": s.shares_outstanding,
    }
    assumable = {"goodwill", "intangibles"}
    assumed = [k for k in assumable if required[k] is None and k in s.assumed_zero]
    missing = [k for k, f in required.items()
               if f is None and not (k in assumable and k in s.assumed_zero)]
    if q is None:
        missing.append("price quote")
    inputs = tuple(f for f in required.values() if f is not None)
    if s.preferred_stock is not None:
        inputs += (s.preferred_stock,)
    if s.noncontrolling_interest is not None:
        inputs += (s.noncontrolling_interest,)
    if s.temporary_equity is not None:
        inputs += (s.temporary_equity,)
    if missing:
        return CriterionResult(7, name, Status.INSUFFICIENT_DATA, None, threshold, inputs,
                               note="missing: " + ", ".join(missing))
    if s.shares_outstanding.value <= 0:
        return CriterionResult(7, name, Status.INSUFFICIENT_DATA, None, threshold, inputs,
                               note="non-positive shares outstanding")
    age = _stale_against(q, s.balance_sheet_date)
    if age is not None and age > STALE_FOR_PRICING_DAYS:
        return CriterionResult(
            7, name, Status.INSUFFICIENT_DATA, None, threshold, inputs,
            note=f"balance sheet dated {s.balance_sheet_date} — {age // 365} years before this "
                 "price; tangible book value cannot be compared with today's quote")
    notes = []
    if assumed:
        notes.append("assumed 0 for " + ", ".join(sorted(assumed))
                     + " (no evidence in any filing; assume_absent_zero opt-in)")
    if s.preferred_stock is None:
        notes.append("no preferred-stock value tagged; defaulted to 0 (flagged per §5.1)")
    if s.temporary_equity is not None:
        notes.append("mezzanine (temporary) equity deducted — senior to common, outside the preferred tag")
    value_of = lambda f: f.value if f is not None else Decimal(0)  # noqa: E731
    tangible = (
        s.total_assets.value
        - s.total_liabilities.value
        - value_of(s.goodwill)
        - value_of(s.intangibles)
        - value_of(s.preferred_stock)
        # A - L is equity incl. NCI; minority holders' share is not the common's
        - value_of(s.noncontrolling_interest)
        - value_of(s.temporary_equity)
    )
    tbvps = tangible / s.shares_outstanding.value
    if tbvps <= 0:
        notes.insert(0, "non-positive tangible book value")
        return CriterionResult(7, name, Status.FAIL, None, threshold, inputs,
                               note="; ".join(notes))
    # "Less than 120%" is strict. Compare raw inputs, not the rounded reader value.
    ratio = (q.price / tbvps).quantize(_CENT)
    status = Status.PASS if q.price < PRICE_TO_TBV_MAX * tbvps else Status.FAIL
    return CriterionResult(7, name, status, ratio, threshold, inputs,
                           note="; ".join(notes) or None)
