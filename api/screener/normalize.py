"""Layer 2: EDGAR companyfacts JSON -> FinancialSnapshot.

All XBRL messiness lives here: tag fallback chains, annual-only selection,
restatement resolution (latest-filed wins), provenance. Missing stays missing —
no value is ever coerced to zero.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from .models import Fact, FinancialSnapshot, OwnerEarnings, Provenance


class UnsupportedFilerError(Exception):
    """A filing basis not covered by the normalizer; never partially evaluate it."""


# Foreign issuers file annual 20-F/40-F reports and interim 6-K reports, mostly
# under IFRS, and their US-GAAP facts (when any) trail the domestic cadence —
# balance sheets arrive stale or not at all.  A filer whose newest financial
# filing is a foreign form is rejected outright; the form tuples still include
# the foreign forms so that a filer that later moved to 10-K/10-Q keeps its
# pre-transition history readable.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
INTERIM_FORMS = ("10-Q", "6-K")
FINANCIAL_FORMS = ANNUAL_FORMS + INTERIM_FORMS


def _is_annual_form(form: str) -> bool:
    return form.startswith(ANNUAL_FORMS)


def _is_interim_form(form: str) -> bool:
    return form.startswith(INTERIM_FORMS)


def _is_financial_form(form: str) -> bool:
    return form.startswith(FINANCIAL_FORMS)


EPS_CONTINUING_TAG = "IncomeLossFromContinuingOperationsPerDilutedShare"
EPS_TAGS = (
    "EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted",
    # Partnerships report per unit, not per share, under their own elements. Energy
    # Transfer files 39 annual years of these; without them the whole midstream sector
    # returned "no annual EPS available" and failed criteria 1, 4 and 6 together.
    "NetIncomeLossNetOfTaxPerOutstandingLimitedPartnershipUnitDiluted",
    "NetIncomeLossPerOutstandingLimitedPartnershipUnitDiluted",
    "NetIncomeLossNetOfTaxPerOutstandingLimitedPartnershipUnitBasicNetOfTax",
    "NetIncomeLossPerOutstandingLimitedPartnershipUnitBasicNetOfTax",
    "NetIncomeLossPerOutstandingLimitedPartnershipUnit",
    "NetIncomeLossPerLimitedPartnershipUnitDiluted",
    "NetIncomeLossPerLimitedPartnershipUnitBasic",
)
# Last resort per missing year only. Basic >= diluted, so it flatters EPS slightly —
# but a year dropped entirely is worse: it staled the whole series and the TTM anchor.
EPS_BASIC_TAGS = ("EarningsPerShareBasic", "IncomeLossFromContinuingOperationsPerBasicShare")
_WEIGHTED_SHARE_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfBasicAndDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfSharesIssuedBasic",
)
# EPS moves when the share count moves, so the numerator is carried separately:
# a company can grow EPS on buybacks alone while earnings are flat or falling.
NET_INCOME_TAGS = (
    "NetIncomeLoss",                                        # attributable to the parent
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",                                           # includes noncontrolling interests
)
# ASC 606 (2018) moved most filers from the SalesRevenue* elements onto
# RevenueFromContractWithCustomer*, so nearly every mature series switches tags
# mid-history — selection must be recency-first with per-year fill, like EPS.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",                                             # umbrella total, incl. non-contract
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",                                      # pre-606
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    # sector top lines — for REITs, utilities, banks and insurers the generic
    # elements above are absent or carry sub-scope scraps (Camden's `Revenues`
    # is $13M against $1.5B of lease income)
    "RegulatedAndUnregulatedOperatingRevenue",
    "OperatingLeaseLeaseIncome",
    "OperatingLeasesIncomeStatementLeaseRevenue",
    "RealEstateRevenueNet",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
    "PremiumsEarnedNet",
)
# Banks and insurers have no operating-income subtotal; absent stays absent.
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
DIVIDEND_TAGS = (
    ("PaymentsOfDividendsCommonStock", ("USD",)),
    ("DividendsCommonStockCash", ("USD",)),
    ("DividendsCommonStock", ("USD",)),
    ("CommonStockDividendsPerShareDeclared", ("USD/shares",)),
    ("CommonStockDividendsPerShareCashPaid", ("USD/shares",)),
    # Aggregates below: they roll up preferred and noncontrolling distributions too,
    # so they evidence "a dividend" but not specifically a common one. Tried last and
    # labelled in provenance so criterion 5 discloses what it rested on.
    ("PaymentsOfDividends", ("USD",)),
    ("DividendsCash", ("USD",)),
    ("Dividends", ("USD",)),
)
_AGGREGATE_DIVIDEND_TAGS = frozenset(("PaymentsOfDividends", "DividendsCash", "Dividends"))
# inbound dividends (received/income/proceeds/equity-method) and subsidiary
# minority-interest payouts are not common dividends; preferred alone isn't either
_DIVIDEND_EVIDENCE_EXCLUDE_RE = re.compile(
    r"received|income|proceeds|equitymethod|minorityinterest|noncontrolling|preferred", re.I
)
_ANNUAL_DAYS = range(340, 401)  # full-fiscal-year duration incl. 52/53-week years
_DIVIDEND_RECENCY_DAYS = 400  # broad window for the unknown-evidence scan only
# "currently pays" window scales with the fact's own tagging cadence: a suspended
# quarterly payer fails within ~2 quarters, while annual-only taggers aren't false-failed
_DIVIDEND_LAG_DAYS = 60
_STALE_DAYS = 400  # instant facts older than this vs the latest balance sheet are treated as missing

# Non-recurring / non-cash lines big enough to decide criterion 1 on their own.
NONCASH_TAGS = (
    ("InventoryLIFOReserveEffectOnIncomeNet", "inventory valuation (LCM/LIFO) adjustment"),
    ("AssetImpairmentCharges", "asset impairment"),
    ("GoodwillImpairmentLoss", "goodwill impairment"),
    ("RestructuringCharges", "restructuring charges"),
    ("InventoryWriteDown", "inventory write-down"),
    ("BusinessCombinationAcquisitionRelatedCosts", "acquisition costs"),
)
PRETAX_TAGS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeignAndDomestic",
)
_NONCASH_MATERIALITY = Decimal("0.10")  # share of pre-tax income
_SHARE_DIVERGENCE = Decimal("0.05")     # worth disclosing
# Beyond this the composite stops being arithmetic: subtracting a per-share figure
# struck on a pre-IPO share count from one struck after the raise produces a number
# that describes no company. A 2025 IPO showed +9.58 built from a -12.80 that was
# only large because it was divided by a fifth of the shares.
_SHARE_INCOMPARABLE = Decimal("0.25")
# per share; a quarterly swing beyond this against a much smaller year is mistagging
_ABSURD_DELTA = Decimal("5")
# No share has ever earned this much in a year — Berkshire's A shares, the highest-priced
# stock in the market, earn tens of thousands. A figure above this is a dollar total the
# filer tagged into a per-share element, and dividing a price by it passes criterion 1 on
# a P/E of nearly zero: GRUSF published 243,446,152 a share.
_IMPLAUSIBLE_EPS = Decimal("100000")
_MILLION = Decimal("1000000")


def build_snapshot(
    ticker: str, cik: str, companyfacts: dict, assume_absent_zero: bool = False
) -> FinancialSnapshot:
    facts = companyfacts.get("facts", {})
    _reject_foreign(facts)
    gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})

    annual_eps = _annual_eps(gaap)
    ttm_eps, ttm_inputs = _ttm_eps(gaap, annual_eps)
    annual_net_income = _annual_net_income(gaap)
    ttm_net_income, _ = _ttm_eps(gaap, annual_net_income, unit=("USD",), per_share=False)
    annual_revenue = _annual_revenue(gaap)
    ttm_revenue, _ = _ttm_eps(gaap, annual_revenue, unit=("USD",), per_share=False)

    # LiabilitiesAndStockholdersEquity equals total assets by the accounting identity,
    # so it both stands in for an untagged Assets total and keeps the staleness
    # anchor armed for filers that never tag Assets.
    total_assets = _latest_instant(gaap, "Assets", ("Assets", "LiabilitiesAndStockholdersEquity"))
    # §5.1: a concept absent from recent filings is missing, not resurrectable from
    # a years-old filing (e.g. a filer that stopped reporting Goodwill).
    fresh = (
        total_assets.provenance.period_end - timedelta(days=_STALE_DAYS)
        if total_assets and total_assets.provenance.period_end
        else None
    )
    current_assets = _latest_instant(gaap, "AssetsCurrent", ("AssetsCurrent",), not_before=fresh)
    current_liabilities = _latest_instant(gaap, "LiabilitiesCurrent", ("LiabilitiesCurrent",), not_before=fresh)
    total_debt = _latest_instant(
        gaap, "TotalDebt",
        ("DebtLongtermAndShorttermCombinedAmount", "DebtAndCapitalLeaseObligations"),
        not_before=fresh,
    )
    long_term_debt = _long_term_debt(gaap, fresh)
    # the plain LongTermDebt tag includes current maturities; keep the short bucket
    # from counting the current portion a second time
    ltd_tags = long_term_debt.provenance.tag.split(" + ") if long_term_debt else []
    short_term_debt = _short_term_debt(
        gaap, fresh, exclude_ltd_current="us-gaap:LongTermDebt" in ltd_tags
    )
    total_liabilities = _latest_instant(gaap, "Liabilities", ("Liabilities",), not_before=fresh)
    if total_liabilities is None:
        total_liabilities = _derive_liabilities(gaap, fresh)
    goodwill = _latest_instant(gaap, "Goodwill", ("Goodwill",), not_before=fresh)
    intangibles = _intangibles(gaap, fresh)
    if goodwill is None and intangibles is None:
        goodwill, intangibles = _combined_goodwill_and_intangibles(gaap, fresh)
    # liquidation preference first: it is the economically correct common-TBV deduction
    # and better maintained than the par-value tag (JPM par tag is stale since 2009)
    preferred = _latest_instant(
        gaap, "PreferredStock",
        ("PreferredStockLiquidationPreferenceValue", "PreferredStockValue",
         "PreferredStockValueOutstanding"),
        not_before=fresh,
    )
    # A - Liabilities is total equity INCLUDING noncontrolling interest, so NCI must
    # come out of common TBV — except when liabilities were derived via parent-only
    # StockholdersEquity, which already left NCI inside the liabilities figure.
    nci = None
    parent_only_derivation = total_liabilities is not None and total_liabilities.provenance.tag.endswith(
        "- us-gaap:StockholdersEquity"
    )
    if not parent_only_derivation:
        nci = _sum_facts("NoncontrollingInterest", [
            _latest_instant(gaap, "NoncontrollingInterest", ("MinorityInterest",), not_before=fresh),
            _latest_instant(
                gaap, "NoncontrollingInterest (redeemable)",
                ("RedeemableNoncontrollingInterestEquityCarryingAmount",), not_before=fresh,
            ),
        ])
    shares = _latest_instant(
        gaap, "SharesOutstanding", ("CommonStockSharesOutstanding",), unit=("shares",), not_before=fresh
    )
    if shares is None:
        shares = _latest_instant(
            dei, "SharesOutstanding", ("EntityCommonStockSharesOutstanding",),
            ns="dei", unit=("shares",), not_before=fresh,
        )
    if shares is None:
        shares = _weighted_shares(gaap, fresh)
    shares = _sane_shares(shares, gaap, dei, fresh,
                          implied=_implied_shares(gaap, annual_eps, annual_net_income))

    balance_sheet_date = next(
        (f.provenance.period_end for f in (current_assets, total_assets) if f is not None), None
    )
    reference = balance_sheet_date or _latest_annual_end(annual_eps)
    pays_dividend, dividend = _dividend(gaap, reference)
    dividend_per_share = _dividend_per_share(gaap, dividend, shares)

    assumed: set[str] = set()
    if assume_absent_zero:
        clean = _absent_zero_candidates(facts)
        # only concepts that are BOTH evidence-free forever AND missing after extraction,
        # and debt only where a classified balance sheet exists (banks/REITs stay N/A)
        if ("debt" in clean and total_debt is None
                and (long_term_debt is None or short_term_debt is None)
                and current_assets is not None and current_liabilities is not None):
            assumed.add("debt")
        if "goodwill" in clean and goodwill is None:
            assumed.add("goodwill")
        if "intangibles" in clean and intangibles is None:
            assumed.add("intangibles")

    owner_earnings = _owner_earnings(gaap, {
        "total_assets": total_assets,
        "current_liabilities": current_liabilities,
        "short_term_debt": short_term_debt,
    }, fresh)

    return FinancialSnapshot(
        cik=cik,
        ticker=ticker,
        annual_eps=annual_eps,
        annual_net_income=annual_net_income,
        ttm_net_income=ttm_net_income,
        ttm_eps=ttm_eps,
        ttm_eps_inputs=ttm_inputs,
        ttm_eps_vintage=vintage_ttm_eps(gaap),
        annual_revenue=annual_revenue,
        ttm_revenue=ttm_revenue,
        annual_operating_income=_annual_operating_income(gaap),
        dividend_record=_dividend_record(gaap),
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        long_term_debt=long_term_debt,
        short_term_debt=short_term_debt,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        goodwill=goodwill,
        intangibles=intangibles,
        preferred_stock=preferred,
        shares_outstanding=shares,
        dividend=dividend,
        dividend_per_share=dividend_per_share,
        pays_dividend=pays_dividend,
        balance_sheet_date=balance_sheet_date,
        total_debt=total_debt,
        assumed_zero=frozenset(assumed),
        noncontrolling_interest=nci,
        earnings_quality=_earnings_quality(gaap, ttm_inputs, annual_eps),
        owner_earnings=owner_earnings,
    )


def _reject_foreign(facts: dict) -> None:
    latest = {"foreign": "", "domestic": ""}
    for taxo in facts.values():
        for tagdata in taxo.values():
            for entries in tagdata.get("units", {}).values():
                for e in entries:
                    form = e.get("form", "")
                    if form.startswith(("20-F", "40-F", "6-K")):
                        side = "foreign"
                    elif form.startswith(("10-K", "10-Q")):
                        side = "domestic"
                    else:
                        continue
                    if e.get("filed", "") > latest[side]:
                        latest[side] = e["filed"]
    if latest["foreign"] > latest["domestic"]:
        raise UnsupportedFilerError(
            "filer currently reports on foreign forms (20-F/40-F/6-K); foreign "
            "reporting cadence and IFRS taxonomy are not supported"
        )


def _entries(taxo: dict, tag: str, unit_pref: tuple[str, ...]) -> list[dict]:
    units = taxo.get(tag, {}).get("units", {})
    for unit in unit_pref:
        if unit in units:
            return units[unit]
    return next(iter(units.values()), [])


def _dec(v) -> Decimal:
    return Decimal(str(v))


def _days(e: dict) -> int:
    return (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days


def _fy_label(end: date) -> int:
    # January-ending fiscal years (retail convention) are labeled with the prior year
    return end.year if end.month > 1 else end.year - 1


def _fact(concept: str, tag: str, e: dict, fiscal_year: int | None = None, ns: str = "us-gaap") -> Fact:
    return Fact(
        value=_dec(e["val"]),
        provenance=Provenance(
            concept=concept,
            tag=f"{ns}:{tag}",
            fiscal_year=fiscal_year,
            form=e.get("form", ""),
            accession=e.get("accn", ""),
            filed=date.fromisoformat(e["filed"]),
            period_end=date.fromisoformat(e["end"]),
            period_start=date.fromisoformat(e["start"]) if "start" in e else None,
        ),
    )


_SPLIT_RATIOS = (1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100)


def _as_split(ratio: Decimal) -> Decimal | None:
    """The ratio rounded to a real split, or None if it is not one.

    An ordinary restatement moves a figure by a few percent; a split moves it by a
    round multiple. Requiring the ratio to land on one keeps error corrections from
    being rescaled as though shares had been divided.
    """
    for k in _SPLIT_RATIOS:
        for cand in (Decimal(str(k)), 1 / Decimal(str(k))):
            if abs(ratio / cand - 1) < Decimal("0.02"):
                return cand
    return None


def _by_period(entries: list[dict], tag: str = "",
               into: dict | None = None) -> dict[tuple[str, str, str], list[tuple[str, Decimal]]]:
    """Every reported value for each exact period, oldest filing first.

    Keyed on tag and whole period, never the end date alone. A three-month quarter and
    a nine-month year-to-date can close on the same day, and comparing those two reads
    their threefold difference in length as a 3:1 split; basic and diluted EPS for one
    period differ slightly and would read as a restatement.
    """
    out = into if into is not None else {}
    for e in entries:
        try:
            out.setdefault((tag, e["start"], e["end"]), []).append((e["filed"], _dec(e["val"])))
        except Exception:
            continue
    for vals in out.values():
        vals.sort()
    return out


def _per_share_periods(gaap: dict) -> dict:
    """Split evidence pooled across every per-share tag the filer uses.

    A split is a corporate action, not a property of one element: it rebases every
    per-share figure at once. Broadcom restated EarningsPerShareDiluted 10:1 but left
    IncomeLossFromContinuingOperationsPerDilutedShare — the series the engine actually
    reads — carrying pre-split years with no restatement to reveal them. Evidence from
    any tag settles the factor for all of them.
    """
    out: dict = {}
    for tag in EPS_TAGS + EPS_BASIC_TAGS + (EPS_CONTINUING_TAG,):
        _by_period([e for e in _entries(gaap, tag, ("USD/shares",)) if "start" in e],
                   tag=tag, into=out)
    return out


def _split_factor(periods: dict[tuple[str, str], list[tuple[str, Decimal]]],
                  filed: str) -> Decimal:
    """How much per-share figures have been rebased since `filed`.

    A split does not change what a company earned, only how the earnings are sliced,
    so afterwards every prior year is restated onto the new share count. The same
    fiscal period therefore appears at two values in filings of different vintage, and
    the ratio between them IS the split factor — observed, not inferred. Chipotle's
    FY2022 is 32.04 in the filings up to 2024 and 0.64 in the 2025 one: 50.06, its 50:1.

    Measured per period as "value as of that date, against the newest value", rather
    than by accumulating split events: one split gets restated across several filings,
    and counting each restatement separately squared Booking Holdings' 25:1 into 625.
    Periods that never moved vote 1, so a quiet history yields no adjustment, and a
    period the filer restated for some other reason fails _as_split and abstains.
    """
    factor = Decimal(1)
    for split_filed, k in _split_events(periods):
        if filed < split_filed:
            factor *= k
    return factor


def _split_events(periods: dict[tuple[str, str], list[tuple[str, Decimal]]]
                  ) -> list[tuple[str, Decimal]]:
    """[(filing date, factor)] for each distinct split, oldest first.

    A single split is restated into every filing that still carries a period spanning
    it, so the same 25:1 shows up again a quarter later under a different period. Left
    alone that compounds — Booking Holdings' anchor came out divided by 625. Runs of
    the same factor within three quarters are therefore one corporate action, while
    Texas Pacific Land's two genuine 3:1 splits, a year apart, stay separate.
    """
    votes: dict[str, list[Decimal]] = {}
    for vals in periods.values():
        for (_, old), (filed_new, new) in zip(vals, vals[1:]):
            if not old or not new or old == new:
                continue
            k = _as_split(old / new)
            if k is not None:
                votes.setdefault(filed_new, []).append(k)
    events: list[tuple[str, Decimal]] = []
    for f in sorted(votes):
        ks = votes[f]
        k = max(set(ks), key=ks.count)  # periods disagreeing on one filing: take majority
        if events and events[-1][1] == k and \
                (date.fromisoformat(f) - date.fromisoformat(events[-1][0])).days <= 275:
            continue
        events.append((f, k))
    return events


def _annual_series(gaap: dict, tag: str, unit: tuple[str, ...] = ("USD/shares",)) -> dict[int, Fact]:
    """Full-fiscal-year facts from annual filings only. Never a sum of quarters (§5.2)."""
    by_end: dict[str, dict] = {}
    frames: dict[str, int] = {}
    annual_entries = []
    for e in _entries(gaap, tag, unit):
        if "start" not in e or not _is_annual_form(e.get("form", "")):
            continue
        if _days(e) not in _ANNUAL_DAYS:
            continue
        annual_entries.append(e)
        # SEC's frame is calendar-aligned: it names the calendar year the period mostly
        # falls in, which equals the fiscal year only for a December filer. Dorian LPG
        # closes in March, so its year ending 2024-03-31 is framed CY2023 while the
        # company — and every other tag in the same filing — calls it fiscal 2024.
        # Taking the frame as a label there shifts one series a year against the rest,
        # and since frames appear on some tags and not others, the two desynchronise.
        # So a frame is honoured only where it agrees with the period's own end date;
        # where it disagrees it is describing calendar overlap, not a fiscal label, and
        # the filer's own fy field anchors the series instead.
        m = re.fullmatch(r"CY(\d{4})", e.get("frame") or "")
        if m and int(m.group(1)) == _fy_label(date.fromisoformat(e["end"])):
            frames[e["end"]] = int(m.group(1))
        prev = by_end.get(e["end"])
        if prev is None or e["filed"] > prev["filed"]:  # restatement rule: latest-filed wins
            by_end[e["end"]] = e
    if not by_end:
        return {}
    labels = _fy_labels(sorted(by_end), frames, by_end)
    series: dict[int, Fact] = {}
    for end in sorted(by_end):
        if end not in labels:
            continue
        series[labels[end]] = _fact(tag, tag, by_end[end], fiscal_year=labels[end])
    return series


def _fy_labels(ends: list[str], frames: dict[str, int], by_end: dict[str, dict]) -> dict[str, int]:
    """Label each annual period end with its fiscal year.

    SEC's frame is authoritative and is never moved. Ends without one are placed
    relative to the nearest framed neighbour. Two invariants keep inference from
    drifting: a fiscal year always ends in its own calendar year or the next one,
    and an inferred label never displaces another period — a colliding old year is
    dropped rather than pushed into a year that does not exist.
    """
    labels = dict(frames)
    if not labels:
        last = ends[-1]
        end_d = date.fromisoformat(last)
        fy = by_end[last].get("fy")
        labels[last] = fy if isinstance(fy, int) and abs(fy - end_d.year) <= 1 else _fy_label(end_d)
    anchors = sorted(labels)
    taken = set(labels.values())
    for end in ends:
        if end in labels:
            continue
        end_d = date.fromisoformat(end)
        anchor = min(anchors, key=lambda k: abs((date.fromisoformat(k) - end_d).days))
        guess = labels[anchor] + round((end_d - date.fromisoformat(anchor)).days / 365)
        # a fiscal year cannot be labelled beyond the calendar year it ends in,
        # nor more than one year before it
        guess = max(end_d.year - 1, min(end_d.year, guess))
        if guess in taken:
            continue  # duplicate of a year already held; keep the framed/earlier one
        labels[end] = guess
        taken.add(guess)
    return labels


def _annual_eps(gaap: dict) -> dict[int, Fact]:
    continuing = _annual_series(gaap, EPS_CONTINUING_TAG)
    candidates = [s for tag in EPS_TAGS if (s := _annual_series(gaap, tag))]
    if continuing:
        candidates.append(continuing)
    if not candidates:
        candidates = [s for tag in EPS_BASIC_TAGS if (s := _annual_series(gaap, tag))]
        if not candidates:
            return {}
    # Filers switch EPS tags mid-history (FCX moved to continuing-ops-only in 2022),
    # so recency dominates: a long-dead series must never beat a current one.
    # At equal currency, §5.3 prefers continuing operations; then deeper history.
    best = max(candidates, key=lambda s: (max(s), s is continuing, len(s)))
    series = _split_adjust(_fill_missing_years(best, gaap), gaap)
    # A per-share element holding a dollar total is not a small error to carry: it is
    # unusable, and leaving it in reads as a company earning millions per share.
    return {y: f for y, f in series.items() if abs(f.value) <= _IMPLAUSIBLE_EPS}


def _split_adjust(series: dict[int, Fact], gaap: dict) -> dict[int, Fact]:
    """Put every year on the share count the company has today.

    A 10-K reports its prior years as filed, and a split only restates the two or
    three comparatives the newest filing carries — so anything older keeps a per-share
    figure struck on a share count that no longer exists. Criterion 6 compares two
    endpoints years apart and lands squarely on that discontinuity: Chipotle's FY2020
    is 12.52 as filed and 0.2504 in today's shares, which is the difference between
    recording a large pass and recording a fail.
    """
    periods = _per_share_periods(gaap)
    if not periods:
        return series
    out: dict[int, Fact] = {}
    for fy, fact in series.items():
        factor = _split_factor(periods, fact.provenance.filed.isoformat())
        out[fy] = fact if factor == 1 else Fact(value=fact.value / factor,
                                                provenance=fact.provenance)
    return out


def _fill_missing_years(series: dict[int, Fact], gaap: dict) -> dict[int, Fact]:
    """Fill years the diluted chain lacks from other EPS tags — basic last.
    A filer tagging only basic in its newest 10-K (Lennar FY2025) would otherwise
    freeze the series a year back, staling criteria 4/6 and the TTM anchor."""
    for tag in EPS_TAGS + (EPS_CONTINUING_TAG,) + EPS_BASIC_TAGS:
        other = _annual_series(gaap, tag)
        for fy, fact in other.items():
            if fy in series:
                continue
            basic = tag in EPS_BASIC_TAGS
            p = fact.provenance
            series[fy] = Fact(
                value=fact.value,
                provenance=Provenance(
                    concept=f"{p.concept} (basic — diluted not tagged)" if basic else p.concept,
                    tag=p.tag, fiscal_year=p.fiscal_year, form=p.form,
                    accession=p.accession, filed=p.filed, period_end=p.period_end,
                ),
            )
    return dict(sorted(series.items()))


def _annual_dollar_series(gaap: dict, tags: tuple[str, ...]) -> dict[int, Fact]:
    """Filers switch elements mid-history the same way they switch EPS elements —
    Advanced Energy's NetIncomeLoss series stops in 2024 while ProfitLoss runs on.
    Taking the first tag that returns anything would freeze the series a year back,
    so candidates are ranked by recency, then by depth, then by tag preference."""
    candidates = [
        (tag, series)
        for tag in tags
        if (series := _annual_series(gaap, tag, unit=("USD",)))
    ]
    if not candidates:
        return {}
    order = {tag: i for i, tag in enumerate(tags)}
    _, best = max(candidates, key=lambda c: (max(c[1]), len(c[1]), -order[c[0]]))
    for _, other in candidates:                      # fill gaps the winner lacks
        for fy, fact in other.items():
            best.setdefault(fy, fact)
    return dict(sorted(best.items()))


def _annual_net_income(gaap: dict) -> dict[int, Fact]:
    return _annual_dollar_series(gaap, NET_INCOME_TAGS)


# staying on one element tolerates real business swings (Carnival's COVID
# collapse and 6x recovery are one tag's honest numbers); moving to a different
# element demands tight agreement, because elements differ in SCOPE and a large
# step at a boundary is a scope mismatch, not history
_SAME_TAG_RATIO = (Decimal(1) / 10, Decimal(10))
_SWITCH_RATIO = (Decimal(1) / 3, Decimal(3))


def _annual_revenue(gaap: dict) -> dict[int, Fact]:
    """The revenue series is STITCHED, not merged: revenue elements carry wildly
    different scopes (ConAgra's umbrella `Revenues` holds a $1.6B sub-item beside
    $13B of true sales; Westlake's own `Revenues` changes meaning mid-history), so
    every year must prove continuity with the year it joins. The walk starts from
    the top line's latest year and extends one year at a time; a year no element
    can prove is where the series honestly ends."""
    candidates = [
        (tag, series)
        for tag in REVENUE_TAGS
        if (series := _annual_series(gaap, tag, unit=("USD",)))
    ]
    if not candidates:
        return {}
    order = {tag: i for i, tag in enumerate(REVENUE_TAGS)}
    # top-line pick: among elements current within a year of the freshest, a series
    # whose latest value is under half the biggest is a sub-scope scrap, not revenue
    latest_fy = max(max(s) for _, s in candidates)
    pool = [(t, s) for t, s in candidates if max(s) >= latest_fy - 1]
    peak = max((float(s[max(s)].value) for _, s in pool if s[max(s)].value > 0), default=0)
    strong = [(t, s) for t, s in pool if float(s[max(s)].value) >= peak / 2] or pool
    tag0, s0 = max(strong, key=lambda c: (max(c[1]), len(c[1]), -order[c[0]]))
    start = max(s0)
    chosen: dict[int, Fact] = {start: s0[start]}
    by_tag = dict(candidates)

    def _fits(v, ref, span) -> bool:
        return v > 0 and ref > 0 and span[0] <= v / ref <= span[1]

    for step in (-1, 1):                    # backward through history, then forward
        cur, ref_fy = tag0, start
        y = start + step
        floor, ceil = min(min(s) for _, s in candidates), max(max(s) for _, s in candidates)
        while floor <= y <= ceil:
            ref = chosen[ref_fy].value
            same = by_tag[cur].get(y)
            if same is not None and abs(ref_fy - y) <= 3 \
                    and _fits(same.value, ref, _SAME_TAG_RATIO):
                chosen[y] = same
            else:
                for tag, s in candidates:
                    f = s.get(y)
                    if tag != cur and f is not None and abs(ref_fy - y) <= 2 \
                            and _fits(f.value, ref, _SWITCH_RATIO):
                        chosen[y] = f
                        cur = tag
                        break
                else:
                    break                    # nothing can prove this year: stop
            ref_fy = y
            y += step
    return dict(sorted(chosen.items()))


def _annual_operating_income(gaap: dict) -> dict[int, Fact]:
    return _annual_dollar_series(gaap, OPERATING_INCOME_TAGS)


def _latest_annual_end(annual_eps: dict[int, Fact]) -> date | None:
    if not annual_eps:
        return None
    return annual_eps[max(annual_eps)].provenance.period_end


def _ttm_eps(gaap: dict, annual_eps: dict[int, Fact],
             unit: tuple[str, ...] = ("USD/shares",),
             per_share: bool = True) -> tuple[Decimal | None, tuple[Fact, ...]]:
    """Current EPS for criterion 1: latest annual, rolled forward with interim
    year-to-date figures when a newer filing exists
    (TTM = FY + YTD_current - YTD_prior_year)."""
    if not annual_eps:
        return None, ()
    latest = annual_eps[max(annual_eps)]
    tag = latest.provenance.tag.split(":", 1)[1]
    all_durations = [e for e in _entries(gaap, tag, unit) if "start" in e]
    quarters = [e for e in all_durations if _is_interim_form(e.get("form", ""))]
    if not quarters:
        return latest.value, (latest,)
    latest_end = max(date.fromisoformat(e["end"]) for e in quarters)
    if latest.provenance.period_end and latest_end <= latest.provenance.period_end:
        return latest.value, (latest,)
    ending_now = [e for e in quarters if date.fromisoformat(e["end"]) == latest_end]
    # The year-to-date leg must begin where the anchor's fiscal year ended, or the
    # composite spans the wrong window: a filer that tags no YTD total offers only a
    # three-month period, some tag a 364-day rolling year that would add a full year
    # to a full year, and after a fiscal-year change the newest quarter can belong to
    # a different year entirely. Preferring the period that actually starts the day
    # after the anchor closes rules out all three; only if none does is the longest
    # taken, and the window is then verified below.
    anchor_end = latest.provenance.period_end
    aligned = [e for e in ending_now
               if anchor_end and date.fromisoformat(e["start"]) - anchor_end == timedelta(days=1)]
    cur = max(aligned or ending_now, key=lambda e: (_days(e), e["filed"]))
    if anchor_end:
        gap = (date.fromisoformat(cur["start"]) - anchor_end).days
        # a 53-week year and an early-January close leave a few days of slack; a
        # quarter's worth of drift means the two legs do not meet
        if not (-14 <= gap <= 14):
            return latest.value, (latest,)
    target = latest_end - timedelta(days=365)
    prior_candidates = [
        e
        for e in all_durations
        if abs((date.fromisoformat(e["end"]) - target).days) <= 14
        and abs(_days(e) - _days(cur)) <= 14
    ]
    if not prior_candidates:
        # ponytail: comparative YTD missing -> latest annual stands in for TTM; provenance shows its age
        return latest.value, (latest,)
    prior = max(prior_candidates, key=lambda e: e["filed"])
    # Only per-share figures break when the share count moves. A dollar total adds
    # and subtracts across periods regardless of how many shares were outstanding.
    if per_share and _shares_incomparable(gaap, cur, prior):
        # the last audited year is a real per-share figure; the composite is not
        return latest.value, (latest,)
    # The anchor arrives already rebased onto today's share count by _split_adjust,
    # and the quarters come from the newest 10-Q, which is on that basis too. Rescaling
    # here as well divided Booking Holdings by 25 twice and produced 2.65 a share.
    delta = _dec(cur["val"]) - _dec(prior["val"])
    # Filers do mistag. Taboola's quarters carry 220.00 and -40.00 a share against a
    # full year of 0.13, giving a trailing 260.13 and a price/earnings of 0.02 that
    # passed criterion 1. No split explains a quarter dwarfing its own year by this
    # much, so the composite is refused and the audited year stands alone. Both bounds
    # are needed: the ratio alone would reject a genuine recovery off a tiny base.
    if per_share and abs(delta) > 20 * abs(latest.value) and abs(delta) > _ABSURD_DELTA:
        return latest.value, (latest,)
    value = latest.value + delta
    return value, (latest, _fact(tag, tag, cur), _fact(tag, tag, prior))


# the vintage runs only walk the EPS chains and the share-comparability guard,
# so only those tags need their history rewound
_VINTAGE_TAGS = frozenset(EPS_TAGS + EPS_BASIC_TAGS + (EPS_CONTINUING_TAG,) + _WEIGHTED_SHARE_TAGS)


def _filed_by(gaap: dict, cutoff: str) -> dict:
    """The filer's EPS-related facts as the record stood on `cutoff` — everything
    filed later removed, so restatements and splits are invisible until filed."""
    cut = {}
    for tag in _VINTAGE_TAGS:
        data = gaap.get(tag)
        if not data:
            continue
        units = {u: kept for u, entries in data.get("units", {}).items()
                 if (kept := [e for e in entries if e.get("filed", "") <= cutoff])}
        if units:
            cut[tag] = {**data, "units": units}
    return cut


def vintage_ttm_eps(gaap: dict) -> dict[str, Decimal]:
    """TTM EPS as it was knowable at each of the last six December 31sts: the
    ordinary composite, run only on facts FILED by that date. No look-ahead —
    a 10-K published in February was not knowledge the previous December.

    Each figure is then rebased onto today's share count (splits filed after the
    cutoff divided out), because the price series it will be divided into is
    split-adjusted to today as well."""
    newest = max((e["filed"] for tag in EPS_TAGS + EPS_BASIC_TAGS + (EPS_CONTINUING_TAG,)
                  for e in _entries(gaap, tag, ("USD/shares",)) if e.get("filed")),
                 default=None)
    if newest is None:
        return {}
    periods = _per_share_periods(gaap)
    out: dict[str, Decimal] = {}
    for year in range(int(newest[:4]) - 6, int(newest[:4])):
        iso = f"{year}-12-31"
        cut = _filed_by(gaap, iso)
        ttm, _ = _ttm_eps(cut, _annual_eps(cut))
        if ttm is None:
            continue
        factor = _split_factor(periods, iso) if periods else Decimal(1)
        out[iso] = ttm / factor
    return out


def _duration_fact(gaap: dict, tag: str, start: str, end: str, unit=("USD",)) -> Decimal | None:
    """Value for an exact reporting period, latest-filed wins."""
    matches = [e for e in _entries(gaap, tag, unit)
               if e.get("start") == start and e.get("end") == end
               and _is_financial_form(e.get("form", ""))]
    if not matches:
        return None
    return _dec(max(matches, key=lambda e: e["filed"])["val"])


def _year_earlier_fact(gaap: dict, tag: str, start: date, end: date) -> Decimal | None:
    """Same reporting period one year back. Fiscal calendars drift by days, so match
    on approximate dates and equal duration rather than an exact -364."""
    want_start, want_end = start - timedelta(days=365), end - timedelta(days=365)
    length = (end - start).days
    best = None
    for e in _entries(gaap, tag, ("USD",)):
        if "start" not in e or not _is_financial_form(e.get("form", "")):
            continue
        es, ee = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        if abs((ee - want_end).days) <= 10 and abs((es - want_start).days) <= 10 \
                and abs((ee - es).days - length) <= 10:
            if best is None or e["filed"] > best["filed"]:
                best = e
    return _dec(best["val"]) if best else None


def _earnings_quality(gaap: dict, ttm_inputs: tuple[Fact, ...], annual_eps: dict[int, Fact]) -> tuple[str, ...]:
    """What the trailing earnings are made of. Criterion 1 is the one test a single
    accounting line can flip, so its composition is disclosed rather than trusted."""
    notes: list[str] = []
    if len(ttm_inputs) < 3:
        return ()
    cur = ttm_inputs[1].provenance
    if cur.period_start is None or cur.period_end is None:
        return ()
    start, end = cur.period_start.isoformat(), cur.period_end.isoformat()

    pretax = next(
        (v for tag in PRETAX_TAGS if (v := _duration_fact(gaap, tag, start, end)) is not None), None
    )
    # Same line is sometimes tagged twice (DINO tags one LCM adjustment under two
    # elements); report each distinct amount once.
    seen: set[Decimal] = set()
    for tag, label in NONCASH_TAGS:
        amount = _duration_fact(gaap, tag, start, end)
        if amount is None or amount == 0 or amount in seen:
            continue
        if not (pretax and pretax != 0 and abs(amount) / abs(pretax) >= _NONCASH_MATERIALITY):
            continue
        seen.add(amount)
        share = abs(amount) / abs(pretax) * 100
        direction = "added to" if amount < 0 else "reduced"
        # the year-earlier comparable period shows whether this line is steady or a swing
        prior = _year_earlier_fact(gaap, tag, cur.period_start, cur.period_end)
        if prior is None:
            swing = " No comparable figure is tagged for the year-earlier period."
        elif abs(amount - prior) < abs(amount) * Decimal("0.25"):
            swing = (f" It was {prior / _MILLION:+,.0f}M in the same period a year earlier — "
                     "steady, so it is not what makes this period unusual.")
        else:
            swing = (f" The same line was {prior / _MILLION:+,.0f}M a year earlier, a swing of "
                     f"{abs(amount - prior) / _MILLION:,.0f}M between the two periods.")
        notes.append(
            f"{label.capitalize()} of {abs(amount) / _MILLION:,.0f}M {direction} pre-tax income "
            f"for {start} to {end}, a period inside the trailing window — {share:.0f}% of that "
            f"period's {pretax / _MILLION:,.0f}M pre-tax income.{swing} Judge for yourself "
            "whether it belongs in a run-rate earnings figure."
        )

    # a loss quarter dropping out of (or sitting inside) the window swings the TTM
    tag = ttm_inputs[0].provenance.tag.split(":", 1)[1]
    quarters = [
        e for e in _entries(gaap, tag, ("USD/shares",))
        if "start" in e and 80 <= _days(e) <= 100 and _dec(e["val"]) < 0
        and e["end"] >= (cur.period_end - timedelta(days=730)).isoformat()
    ]
    if quarters:
        worst = min(quarters, key=lambda e: e["val"])
        notes.append(
            f"A loss quarter ({worst['start']} to {worst['end']}, {_dec(worst['val'])} per share) "
            "falls in or near the trailing window; whether it is inside or outside moves the "
            "trailing figure without anything changing in the business."
        )

    counts = []
    for f in ttm_inputs:
        p = f.provenance
        if p.period_start and p.period_end:
            c = _duration_fact(gaap, "WeightedAverageNumberOfDilutedSharesOutstanding",
                               p.period_start.isoformat(), p.period_end.isoformat(), unit=("shares",))
            if c:
                counts.append(c)
    if len(counts) >= 2 and min(counts) > 0:
        spread = max(counts) / min(counts) - 1
        if spread >= _SHARE_DIVERGENCE:
            notes.append(
                f"The three periods combined into the trailing figure carry diluted share counts "
                f"differing by {spread * 100:.0f}% ({min(counts) / _MILLION:,.0f}M to "
                f"{max(counts) / _MILLION:,.0f}M), so the sum is not a like-for-like per-share number."
            )
    return tuple(notes)


def _shares_incomparable(gaap: dict, cur: dict, prior: dict) -> bool:
    """True when the two year-to-date periods were struck on share counts so
    different that their per-share figures cannot be subtracted — an IPO, a large
    secondary, or a reverse split between them."""
    # A filer that reports only basic shares left this guard blind, because it read one
    # hard-coded diluted tag and gave up. Every other extractor here walks a chain; this
    # one now does too, and both legs must come from the same tag or the comparison is
    # between two different measures rather than two periods.
    for tag in _WEIGHTED_SHARE_TAGS:
        counts = [_duration_fact(gaap, tag, e["start"], e["end"], unit=("shares",))
                  for e in (cur, prior)]
        if all(c is not None and c > 0 for c in counts):
            return max(counts) / min(counts) - 1 >= _SHARE_INCOMPARABLE
    return False            # unknown share counts are not evidence of a problem


def _latest_instant(
    taxo: dict,
    concept: str,
    tags: tuple[str, ...],
    ns: str = "us-gaap",
    unit: tuple[str, ...] = ("USD",),
    not_before: date | None = None,
) -> Fact | None:
    floor = not_before.isoformat() if not_before else ""
    for tag in tags:
        entries = [
            e
            for e in _entries(taxo, tag, unit)
            if "start" not in e
            and _is_financial_form(e.get("form", ""))
            and e["end"] >= floor
        ]
        if entries:
            e = max(entries, key=lambda e: (e["end"], e["filed"]))  # latest period, latest-filed
            return _fact(concept, tag, e, ns=ns)
    return None


def _long_term_debt(gaap: dict, not_before: date | None) -> Fact | None:
    primary = _latest_instant(
        gaap, "LongTermDebt",
        ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
         "LongTermNotesPayable", "LongTermDebt"),
        not_before=not_before,
    )
    parts = [primary] if primary else []
    if primary is None:
        # "Other…" is a component of the primary tags; additive only when they are absent
        parts.append(_latest_instant(
            gaap, "LongTermDebt (other)", ("OtherLongTermDebtNoncurrent",), not_before=not_before
        ))
    parts.append(_latest_instant(
        gaap, "LongTermDebt (subordinated debentures)",
        ("JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent",),
        not_before=not_before,
    ))
    if primary is None or "CapitalLeaseObligations" not in primary.provenance.tag:
        parts.append(_latest_instant(
            gaap, "LongTermDebt (finance leases)", ("FinanceLeaseLiabilityNoncurrent",),
            not_before=not_before,
        ))
    return _sum_facts("LongTermDebt", parts)


def _short_term_debt(
    gaap: dict, not_before: date | None, exclude_ltd_current: bool = False
) -> Fact | None:
    whole = _latest_instant(gaap, "ShortTermDebt", ("DebtCurrent",), not_before=not_before)
    if whole is not None:
        return whole  # DebtCurrent already rolls up the whole short bucket
    ltd_current = None
    if not exclude_ltd_current:  # skipped when the long bucket already includes current maturities
        ltd_current = _latest_instant(
            gaap, "ShortTermDebt (current portion of long-term)",
            ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
             "UnsecuredDebtCurrent"),
            not_before=not_before,
        )
    borrowings = _latest_instant(
        gaap, "ShortTermDebt (borrowings)", ("ShortTermBorrowings", "CommercialPaper"),
        not_before=not_before,
    )
    leases = None
    if ltd_current is None or "CapitalLeaseObligations" not in ltd_current.provenance.tag:
        leases = _latest_instant(
            gaap, "ShortTermDebt (finance leases)", ("FinanceLeaseLiabilityCurrent",),
            not_before=not_before,
        )
    return _sum_facts("ShortTermDebt", [ltd_current, borrowings, leases])


def _sum_facts(concept: str, parts: list[Fact | None]) -> Fact | None:
    """Sum component facts. Components may carry different (already staleness-guarded)
    period ends and are ALL included: dropping any part understates the total, and
    for both debt (criterion 3) and intangibles (criterion 7) overstating is the
    conservative direction. The combined tag string discloses what was summed."""
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    latest = max(parts, key=lambda p: p.provenance.period_end).provenance
    return Fact(
        value=sum(p.value for p in parts),
        provenance=Provenance(
            concept=f"{concept} (sum of components)",
            tag=" + ".join(p.provenance.tag for p in parts),
            fiscal_year=None, form=latest.form, accession=latest.accession,
            filed=latest.filed, period_end=latest.period_end,
        ),
    )


_DEBT_EVIDENCE_RE = re.compile(
    r"debt|borrowing|notespayable|loanspayable|debenture|commercialpaper"
    r"|financeleaseliability|lineofcredit", re.I,
)
_DEBT_EVIDENCE_EXCLUDE_RE = re.compile(
    r"securit|maturit|capacity|issuancecost|weightedaverage|interestrate|remaining"
    r"|proceeds|payments|repayments|gainloss|extinguish|conversion|unamortized"
    r"|commitmentfee|increase|decrease", re.I,
)
_INTEREST_EVIDENCE_TAGS = frozenset(
    ("InterestExpenseDebt", "InterestExpenseDebtExcludingAmortization", "InterestExpenseBorrowings")
)
_EVIDENCE_FLOOR = 1_000_000  # any real instrument counts; over-detection is the safe direction


def _absent_zero_candidates(facts: dict) -> set[str]:
    """Concepts with no supporting evidence anywhere in the company's entire XBRL
    history — every namespace (custom extensions included), every filing. Only such
    concepts may be assumed zero, and only behind the caller's explicit opt-in."""
    evidence = {"debt": False, "goodwill": False, "intangibles": False}
    for taxo in facts.values():
        for tag, tagdata in taxo.items():
            low = tag.lower()
            hits = []
            if not evidence["debt"] and (
                tag in _INTEREST_EVIDENCE_TAGS
                or (_DEBT_EVIDENCE_RE.search(tag) and not _DEBT_EVIDENCE_EXCLUDE_RE.search(tag))
            ):
                hits.append("debt")
            # startswith: "…ExcludingGoodwill" names goodwill without evidencing it
            if not evidence["goodwill"] and low.startswith("goodwill"):
                hits.append("goodwill")
            if not evidence["intangibles"] and "intangible" in low:
                hits.append("intangibles")
            if hits and _has_material_value(tagdata):
                for h in hits:
                    evidence[h] = True
    return {concept for concept, found in evidence.items() if not found}


def _has_material_value(tagdata: dict) -> bool:
    return any(
        isinstance(e.get("val"), (int, float)) and abs(e["val"]) >= _EVIDENCE_FLOOR
        for unit in tagdata.get("units", {}).values()
        for e in unit
        if _is_financial_form(e.get("form", ""))
    )


def _derive_liabilities(gaap: dict, not_before: date | None) -> Fact | None:
    """Many filers tag no Liabilities total. Derive it from the accounting identity
    L = LiabilitiesAndStockholdersEquity - total equity, same period end required."""
    lse = _latest_instant(
        gaap, "LiabilitiesAndStockholdersEquity", ("LiabilitiesAndStockholdersEquity",),
        not_before=not_before,
    )
    if lse is None:
        return None
    for equity_tag in (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ):
        equity = _latest_instant(gaap, "Equity", (equity_tag,), not_before=not_before)
        if equity and equity.provenance.period_end == lse.provenance.period_end:
            p = lse.provenance
            return Fact(
                value=lse.value - equity.value,
                provenance=Provenance(
                    concept="Liabilities (derived: LiabilitiesAndStockholdersEquity - equity)",
                    tag=f"us-gaap:LiabilitiesAndStockholdersEquity - us-gaap:{equity_tag}",
                    fiscal_year=None, form=p.form, accession=p.accession,
                    filed=p.filed, period_end=p.period_end,
                ),
            )
    return None


def _intangibles(gaap: dict, not_before: date | None) -> Fact | None:
    """Total ex-goodwill tag when present; otherwise finite + indefinite-lived parts;
    otherwise the OtherIntangibleAssetsNet line some filers use as their only total.
    Last because when the specific tags exist it may be a residual category, and
    adding it to them would risk double counting."""
    total = _latest_instant(
        gaap, "Intangibles", ("IntangibleAssetsNetExcludingGoodwill",), not_before=not_before
    )
    if total is not None:
        return total
    finite = _latest_instant(
        gaap, "Intangibles (finite-lived)", ("FiniteLivedIntangibleAssetsNet",), not_before=not_before
    )
    indefinite = _latest_instant(
        gaap, "Intangibles (indefinite-lived)", ("IndefiniteLivedIntangibleAssetsExcludingGoodwill",),
        not_before=not_before,
    )
    summed = _sum_facts("Intangibles", [finite, indefinite])
    if summed is not None:
        return summed
    return _latest_instant(
        gaap, "Intangibles (other, net)", ("OtherIntangibleAssetsNet",), not_before=not_before
    )


def _combined_goodwill_and_intangibles(gaap: dict, not_before: date | None) -> tuple[Fact | None, Fact | None]:
    """Some filers tag one combined goodwill+intangibles balance line and nothing
    else. Subtracting that line once equals subtracting both parts, so it fills
    the intangibles slot; goodwill becomes an explicit zero whose provenance
    names the combined line that already contains it."""
    combined = _latest_instant(
        gaap, "Intangibles (incl. goodwill)", ("IntangibleAssetsNetIncludingGoodwill",),
        not_before=not_before,
    )
    if combined is None:
        return None, None
    p = combined.provenance
    goodwill = Fact(
        value=Decimal(0),
        provenance=Provenance(
            concept="Goodwill (contained in the combined intangibles line)",
            tag=p.tag, fiscal_year=p.fiscal_year, form=p.form,
            accession=p.accession, filed=p.filed, period_end=p.period_end,
        ),
    )
    return goodwill, combined


OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
# Energy and other filers whose income statement has no operating subtotal report a
# pre-tax figure instead. It includes non-operating items, so it is flagged when used.
PRETAX_INCOME_TAGS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
)
# Rollup tags first: a filer that reports the combined figure rarely also splits it,
# and summing the parts when the rollup exists would double-count.
DA_TAGS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
)
DA_PART_TAGS = ("Depreciation", "AmortizationOfIntangibleAssets")
TAX_TAGS = ("IncomeTaxExpenseBenefit",)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
)
CASH_TAGS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
SHORT_TERM_INVESTMENT_TAGS = (
    "ShortTermInvestments",
    "AvailableForSaleSecuritiesCurrent",
    "MarketableSecuritiesCurrent",
    "OtherShortTermInvestments",
)


def _annual_union(gaap: dict, tags: tuple[str, ...]) -> dict[int, Fact]:
    """One annual series assembled from a chain of tags, earlier tags winning a year.

    Filers change tags mid-history and leave the abandoned one in place, so taking the
    first tag that has any data at all freezes the series at the year it was dropped.
    Filling year by year keeps the preferred tag where it exists and stays current.
    """
    out: dict[int, Fact] = {}
    for tag in tags:
        for year, fact in _annual_series(gaap, tag, unit=("USD",)).items():
            out.setdefault(year, fact)
    return out


def _owner_earnings(gaap: dict, snap_parts: dict, fresh: date | None) -> OwnerEarnings | None:
    """Owner earnings over invested capital, on the latest fully audited year.

    Three terms in the classic definition no longer describe how companies report,
    and carrying them anyway would corrupt the number rather than complete it:

    Goodwill amortisation ended with SFAS 142 in 2001 — goodwill is impaired now, not
    amortised, and the tag appears in none of the filings on hand. Stock option cost is
    already inside operating income: ASC 718 has required it to be expensed since 2006,
    so the deduction the definition calls for has been made before we see the figure,
    and subtracting it again would charge it twice. Pension return assumptions are
    disclosed by too few filers to adjust for, and only defined-benefit plans can play
    that game at all.

    What is left is measurable: operating profit, plus depreciation and amortisation
    because they are non-cash, less tax actually charged, less the capital spending the
    business cannot avoid. That last term is the one no filing discloses — a company
    reports total capital expenditure, never the split between maintaining the business
    and growing it. Total capex is the conservative reading and the headline here, and
    since Buffett's own approximation is that maintenance spending roughly equals
    depreciation, that variant is carried alongside as the optimistic bound. A company
    whose ROIC clears the bar on both readings clears it on any.
    """
    caveats: list[str] = []
    flows: dict[str, dict[int, Fact]] = {}
    for label, tags in (("operating profit", OPERATING_INCOME_TAGS), ("tax", TAX_TAGS),
                        ("capital expenditure", CAPEX_TAGS)):
        if series := _annual_union(gaap, tags):
            flows[label] = series
    if "operating profit" not in flows and (series := _annual_union(gaap, PRETAX_INCOME_TAGS)):
        flows["operating profit"] = series
        caveats.append("no operating subtotal is reported, so pre-tax income stands in for "
                       "operating profit and carries non-operating items with it")

    da = _annual_union(gaap, DA_TAGS)
    parts = [s for tag in DA_PART_TAGS if (s := _annual_series(gaap, tag, unit=("USD",)))]
    if parts:
        # A filer that drops the combined tag mid-history keeps reporting the pieces;
        # taking the rollup wherever it exists and the sum elsewhere keeps the series
        # current instead of freezing it at the year the tag changed.
        summed = {y: Fact(sum(p[y].value for p in parts if y in p), parts[0][y].provenance)
                  for p in parts for y in p if y in parts[0]}
        da = {**summed, **da}
    if da:
        flows["depreciation & amortisation"] = da

    required = ("operating profit", "depreciation & amortisation", "tax", "capital expenditure")
    if any(k not in flows for k in required):
        return None
    shared = set.intersection(*(set(flows[k]) for k in required))
    if not shared:
        return None
    fy = max(shared)

    op, dep = flows["operating profit"][fy].value, flows["depreciation & amortisation"][fy].value
    tax, capex = flows["tax"][fy].value, flows["capital expenditure"][fy].value
    # Capex is a positive cash outflow in every tag we chain. Tax is NOT:
    # IncomeTaxExpenseBenefit is signed, and a company with a net benefit files it
    # negative. Forcing it positive charged Uber for a $4.3bn benefit it received,
    # moving owner earnings the wrong way by twice the amount and reporting 3.36%
    # where the truth is 21.59%. Subtracting the signed value adds a benefit back.
    capex = abs(capex)
    owner = op + dep - tax - capex
    components = (
        ("operating profit", op),
        ("+ depreciation & amortisation", dep),
        ("- income tax", -tax),
        ("- capital expenditure", -capex),
    )

    caveats += [
        "maintenance capital expenditure is not a reported figure; total capital "
        "expenditure is used, which understates owner earnings for a company still growing",
        "past write-offs that reduced invested capital cannot be reconstructed from the "
        "filings, so invested capital is the balance sheet as it stands",
        "stock compensation is already expensed within operating profit and is not "
        "deducted a second time",
    ]

    invested = roic = roic_maint = None
    assets, cur_liab = snap_parts.get("total_assets"), snap_parts.get("current_liabilities")
    short_debt = snap_parts.get("short_term_debt")
    cash = _latest_instant(gaap, "Cash", CASH_TAGS, not_before=fresh)
    investments = _latest_instant(gaap, "ShortTermInvestments", SHORT_TERM_INVESTMENT_TAGS,
                                  not_before=fresh)
    if assets is not None and cur_liab is not None:
        # Non-interest-bearing current liabilities are what suppliers and employees fund;
        # only the borrowed part of current liabilities is capital anyone charges for.
        nibcl = cur_liab.value - (short_debt.value if short_debt else Decimal(0))
        invested = (assets.value
                    - (cash.value if cash else Decimal(0))
                    - (investments.value if investments else Decimal(0))
                    - max(nibcl, Decimal(0)))
        if cash is None:
            caveats.append("no cash balance found, so invested capital is overstated")
        if invested > 0:
            roic = owner / invested * 100
            roic_maint = (op - tax) / invested * 100  # maintenance capex assumed equal to D&A
        else:
            invested = None
            caveats.append("invested capital is zero or negative, so a return on it has no meaning")
    else:
        caveats.append("no classified balance sheet, so invested capital cannot be separated")

    return OwnerEarnings(fiscal_year=fy, owner_earnings=owner, invested_capital=invested,
                         roic=roic, roic_maintenance=roic_maint, components=components,
                         caveats=tuple(caveats))


def _implied_shares(gaap: dict, annual_eps: dict[int, Fact],
                    annual_ni: dict[int, Fact]) -> Decimal | None:
    """Share count implied by the filer's own earnings: net income over EPS.

    Independent of every share tag, because it is the denominator the company must
    have divided by to publish the EPS it published.
    """
    for year in sorted(annual_eps, reverse=True):
        eps, ni = annual_eps.get(year), annual_ni.get(year)
        if eps is None or ni is None or eps.value == 0:
            continue
        implied = ni.value / eps.value
        if implied > 0:
            return implied
    return None


def _sane_shares(chosen: Fact | None, gaap: dict, dei: dict, fresh: date | None,
                 implied: Decimal | None = None) -> Fact | None:
    """A filer that tags its share count in thousands understates it a thousandfold,
    and that one number divides net current asset value, tangible book and market cap
    alike — so the error arrives disguised as a deep bargain rather than as a gap.

    Every filing carries three share counts drawn independently: the balance-sheet
    instant, the cover page, and the weighted average behind EPS. They never agree
    exactly — the cover page is dated later, the weighted average spans a period — but
    they agree on the order of magnitude, because they count the same shares. So when
    the chosen one sits a full order of magnitude from both others, it is the outlier
    rather than the truth, and the median of the three is taken instead. A median of
    three is unmoved by any single bad source, and since it returns one of the reported
    values rather than a blend, the ordinary drift between them cannot distort it. With
    fewer than three counts there is nothing to arbitrate, so the choice stands.
    """
    if chosen is None:
        return None
    cover = _latest_instant(
        dei, "SharesOutstanding", ("EntityCommonStockSharesOutstanding",),
        ns="dei", unit=("shares",), not_before=fresh,
    )
    weighted = _weighted_shares(gaap, fresh)
    # The weighted average is only a third opinion when it is not already the choice;
    # counting it twice made the median a median of two, and the outlier test compared
    # the chosen value against its own duplicate — a ratio of one, so it never fired.
    others = [f for f in (cover, weighted)
              if f is not None and f.value > 0 and f is not chosen]
    candidates = [chosen] + others
    if len(candidates) >= 3:
        outlier = all(max(chosen.value, f.value) / min(chosen.value, f.value) > 10
                      for f in others)
        if outlier:
            return sorted(candidates, key=lambda f: f.value)[1]
        return chosen
    # With one source there is nothing to outvote, and that is exactly where a filer
    # tagging shares in thousands slips through: Hub Group reported 60,333 against a
    # true 60.3 million, which passed criterion 7 at a price-to-book of 0.00. Earnings
    # give an independent reading, so an order-of-magnitude disagreement retires the
    # count rather than publishing a thousandfold-wrong book value.
    if implied is not None and implied > 0 and chosen.value > 0:
        if max(chosen.value, implied) / min(chosen.value, implied) > 10:
            return None
    return chosen


def _weighted_shares(gaap: dict, not_before: date | None) -> Fact | None:
    """Multi-class filers often tag no point-in-time consolidated share count.
    Weighted-average diluted shares from the income statement is the flagged proxy."""
    tag = "WeightedAverageNumberOfDilutedSharesOutstanding"
    floor = not_before.isoformat() if not_before else ""
    entries = [
        e
        for e in _entries(gaap, tag, ("shares",))
        if "start" in e and _is_financial_form(e.get("form", "")) and e["end"] >= floor
    ]
    if not entries:
        return None
    latest_end = max(e["end"] for e in entries)
    best = None
    for e in entries:
        if e["end"] != latest_end:
            continue
        # shortest duration = closest to a point-in-time count; then latest filed
        if best is None or _days(e) < _days(best) or (_days(e) == _days(best) and e["filed"] > best["filed"]):
            best = e
    return _fact("SharesOutstanding (weighted-average diluted proxy)", tag, best)


def _dividend_per_share(gaap: dict, dividend: Fact | None, shares: Fact | None) -> Decimal | None:
    """A dividend fact covers whatever span the filer tagged — a quarter for one
    company, half a year for another — so the raw figure is not comparable. Roll it
    to twelve months the same way earnings are, then express it per share."""
    if dividend is None:
        return None
    tag = dividend.provenance.tag.split(":", 1)[1]
    per_share = tag.startswith("CommonStockDividendsPerShare")
    unit = ("USD/shares",) if per_share else ("USD",)
    annual = _annual_series(gaap, tag, unit=unit)
    if not annual:
        return None
    ttm, _ = _ttm_eps(gaap, annual, unit=unit, per_share=False)
    if ttm is None:
        return None
    if per_share:
        return ttm
    if shares is None or shares.value <= 0:
        return None
    return ttm / shares.value


def _dividend_record(gaap: dict) -> dict | None:
    """Which calendar years the filer actually paid a common dividend, from the
    chained tags' own facts. XBRL history only begins around 2009-2011, so the
    start of the record is part of the answer: "paid since 2011" can mean "paid
    for longer than the record can show" — display must say when the record begins."""
    paid: set[int] = set()
    for tag, unit in DIVIDEND_TAGS:
        for e in _entries(gaap, tag, unit):
            if "start" in e and _is_financial_form(e.get("form", "")) \
                    and _dec(e["val"]) > 0:
                paid.add(int(e["end"][:4]))
    if not paid:
        return None
    years = sorted(paid)
    streak_from = years[-1]
    for y in reversed(years[:-1]):
        if y != streak_from - 1:
            break
        streak_from = y
    return {"first": years[0], "latest": years[-1],
            "streak_from": streak_from, "paid_years": len(years)}


def _dividend(gaap: dict, reference: date | None) -> tuple[bool | None, Fact | None]:
    if reference is None:
        return None, None
    for tag, unit in DIVIDEND_TAGS:
        positive = [e for e in _entries(gaap, tag, unit) if "start" in e and _dec(e["val"]) > 0]
        if not positive:
            continue
        e = max(positive, key=lambda e: (e["end"], e["filed"]))
        if (reference - date.fromisoformat(e["end"])).days <= _days(e) + _DIVIDEND_LAG_DAYS:
            concept = ("Dividends (aggregate — may include preferred and noncontrolling)"
                       if tag in _AGGREGATE_DIVIDEND_TAGS else "Dividends (common stock)")
            return True, _fact(concept, tag, e)
    # The chain missed, but a recent positive fact under ANY other dividend-named
    # tag means the filer likely pays via a tag we don't read: unknown, never FAIL.
    floor = (reference - timedelta(days=_DIVIDEND_RECENCY_DAYS)).isoformat()
    chained = {tag for tag, _ in DIVIDEND_TAGS}
    for tag, tagdata in gaap.items():
        if tag in chained or "dividend" not in tag.lower():
            continue
        if _DIVIDEND_EVIDENCE_EXCLUDE_RE.search(tag):
            continue
        for unit in tagdata.get("units", {}).values():
            for e in unit:
                if (_is_financial_form(e.get("form", ""))
                        and e.get("end", "") >= floor
                        and isinstance(e.get("val"), (int, float)) and e["val"] > 0):
                    return None, None
    # Dividend payers must report payments in the cash-flow statement; no recent
    # positive fact under any dividend-named tag => not currently paying.
    return False, None
