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
    # Investment companies report per-share operating results under their own
    # element (equals diluted EPS at BXSL four years running); the NII-only
    # sibling fragments are deliberately excluded
    "InvestmentCompanyInvestmentIncomeLossFromOperationsPerShare",
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
    # LP unit counts are true totals (ET/EPD/BSM within 0.6% of the dei cover);
    # the BASIC LP variant is deliberately absent — depositary-receipt filers
    # tag it 27x off the real count (NEN)
    "WeightedAverageLimitedPartnershipUnitsOutstandingDiluted",
)
# EPS moves when the share count moves, so the numerator is carried separately:
# a company can grow EPS on buybacks alone while earnings are flat or falling.
NET_INCOME_TAGS = (
    "NetIncomeLoss",                                        # attributable to the parent
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",                                           # includes noncontrolling interests
)
# The subset that is the common's alone. Where minority holders own part of the
# group, only these may be divided by the parent's own share count: Westlake
# Chemical Partners' sponsor takes 82.7% of the consolidated profit, and dividing
# the group figure by the public units reported $9.65 a unit against a filed $1.77.
PARENT_INCOME_TAGS = NET_INCOME_TAGS[:2]
# ...and where only the group figure carries a trailing window, the minority's own
# line is what has to come out of it.
NCI_INCOME_TAGS = (
    "NetIncomeLossAttributableToNoncontrollingInterest",
    "NetIncomeLossAttributableToRedeemableNoncontrollingInterest",
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
    # BDC total investment income (ARCC/BXSL have no revenue series without it)
    # ranks above the narrower interest-only line, so the fuller total wins the
    # tie-break (PSEC); SYF's $22.6B of interest income has no other home
    "GrossInvestmentIncomeOperating",
    "InterestIncomeOperating",
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
    # Partnerships distribute rather than pay dividends; the LP payout to
    # unitholders is the common payout for criterion 5 (EPD, MPLX, UAN). The
    # LLC-member variant is deliberately ABSENT: in Up-C structures it names
    # payouts to NCI holders only and would mark non-payers as paying.
    ("DistributionMadeToLimitedPartnerCashDistributionsPaid", ("USD",)),
    ("DistributionMadeToLimitedPartnerDistributionsPaidPerUnit", ("USD/shares",)),
    # BDCs/investment companies: the per-share element first — MAIN's dollar
    # amount tag carries supplemental-declaration fragments, the per-share one
    # reproduces the true total (BXSL: 3.08 x shares == the paid amount).
    ("InvestmentCompanyDistributionToShareholdersPerShare", ("USD/shares",)),
    ("InvestmentCompanyDividendDistribution", ("USD",)),
    # Aggregates below: they roll up preferred, GP/IDR and noncontrolling
    # distributions too, so they evidence "a payout" but not specifically a
    # common one. Tried last and labelled in provenance so criterion 5
    # discloses what it rested on.
    ("PaymentsOfOrdinaryDividends", ("USD",)),
    ("PaymentsOfDividends", ("USD",)),
    ("DividendsCash", ("USD",)),
    ("Dividends", ("USD",)),
    ("PartnersCapitalAccountDistributions", ("USD",)),
)
_AGGREGATE_DIVIDEND_TAGS = frozenset((
    "PaymentsOfOrdinaryDividends", "PaymentsOfDividends", "DividendsCash", "Dividends",
    "InvestmentCompanyDividendDistribution", "PartnersCapitalAccountDistributions",
))
# inbound dividends (received/income/proceeds/equity-method), subsidiary
# minority-interest payouts, preferred-only lines, EPS-allocation mechanics
# (undistributed/distributable), temporary-equity accretion, and cost lines that
# merely contain the word "distribution" are not common payouts
_DIVIDEND_EVIDENCE_EXCLUDE_RE = re.compile(
    r"received|income|proceeds|equitymethod|minorityinterest|noncontrolling|preferred"
    r"|receivable|paidtoparent|policyholder|temporaryequity|statutoryaccounting"
    r"|undistributed|distributable|affiliates|servicing|productionanddistribution"
    r"|propertyplant|deferredcompensation|fees"
    # ...and elements that cannot be a payment at all. Withholding a verdict is the
    # conservative direction, but it withheld one Graham's criterion could give for
    # 218 companies — BJ's, MicroStrategy, Celsius, CoreWeave among them — on the
    # strength of a capacity disclosure, a balance-sheet payable, an equity
    # reclassification or an option-pricing input.
    r"|amountavailablefor|capitaladequacy|payablecurrent|payablenoncurrent"
    r"|additionalpaidincapital|expecteddividend|dividendrate|dividendyield"
    r"|excludinginterestanddividends|arrearage|dividendspayable", re.I
)
# Preferred dividends come out of income before anything reaches the common:
# EPS already nets them, the NetIncomeLoss tag does not, so every NI-vs-EPS
# arithmetic (implied share counts, identity checks) needs this series.
PREFERRED_DIVIDEND_TAGS = (
    "DividendsPreferredStock",
    "PaymentsOfDividendsPreferredStockAndPreferenceStock",
    "PreferredStockDividendsIncomeStatementImpact",
    # Wheeler REIT's undeclared preferred dividends — 3,274,000 of a 6,242,000
    # quarter — are tagged here and nowhere else, and without them its derived
    # per-share figure counted the preferred's money as the common's.
    "OtherPreferredStockDividendsAndAdjustments",
    "PreferredStockDividendsAndOtherAdjustments",
    "DividendsPreferredStockCash",
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
    ("ImpairmentOfIntangibleAssetsExcludingGoodwill", "intangible-asset impairment"),
    ("RestructuringCharges", "restructuring charges"),
    ("InventoryWriteDown", "inventory write-down"),
    ("BusinessCombinationAcquisitionRelatedCosts", "acquisition costs"),
)
# GIS files the rollup AND both specific impairments at different amounts; the
# rollup speaks only when neither specific line produced a material note.
_IMPAIRMENT_ROLLUP = ("GoodwillAndIntangibleAssetImpairment", "goodwill and intangible impairment")
_IMPAIRMENT_SPECIFICS = frozenset(("GoodwillImpairmentLoss", "ImpairmentOfIntangibleAssetsExcludingGoodwill"))
# Gain-signed lines: a positive value ADDS to pre-tax income. One-time gains
# silently flatter the P/E test the same way one-time charges depress it.
GAIN_TAGS = (
    ("GainLossOnInvestments", "investment gain/loss"),
    ("UnrealizedGainLossOnInvestments", "unrealized investment gain/loss"),
    ("GainLossOnSaleOfPropertyPlantEquipment", "property disposal gain/loss"),
    ("GainLossOnDispositionOfAssets1", "asset disposition gain/loss"),
)
# Warrant remeasurement has no reliable sign convention in the wild (AMZN vs
# CVNA file opposite orientations), so its note reports magnitude only.
_WARRANT_TAG = ("FairValueAdjustmentOfWarrants", "warrant fair-value remeasurement")
PRETAX_TAGS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeignAndDomestic",
)
_NONCASH_MATERIALITY = Decimal("0.10")  # share of pre-tax income
_SUSPENSION_SHARE = Decimal("0.10")     # ...of the typical year, or the record broke
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
_OWNER_EARNINGS_LAG = 800      # flows this far behind the balance sheet are a different company
_INVESTED_CAPITAL_FLOOR = Decimal("0.02")   # ...of total assets, or the ratio is noise
_MILLION = Decimal("1000000")


def _debt_figures(gaap: dict, fresh: date | None,
                  current_liabilities: Fact | None) -> tuple[Fact | None, Fact | None, Fact | None]:
    """The three debt figures and the four rules that keep them honest.

    Borrowed money, as Graham reads it: finance leases count, operating rent does
    not. Every rule here was written for a filer that broke the obvious reading —
    a short bucket larger than the current liabilities containing it, a long bucket
    that is only a lease while the company's own history shows borrowings, a rollup
    older than its parts, a rollup smaller than a part it must contain. Returns
    (total, long, short); criterion 3 reconciles the three in `settled_debt`.
    """
    total_debt = _latest_instant_across(
        gaap, "TotalDebt",
        ("DebtLongtermAndShorttermCombinedAmount", "DebtAndCapitalLeaseObligations",
         "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
        not_before=fresh,
    )
    long_term_debt, ltd_suppress = _long_term_debt(gaap, fresh)
    short_term_debt = _short_term_debt(gaap, fresh, suppress=ltd_suppress)
    # Short-term debt is a line INSIDE current liabilities, so a bucket larger than
    # the whole cannot be right: 60 rows shipped one, Lumentum at $6.477B against
    # $3.865B of current liabilities and IBM at $11.547B where its 10-Q says
    # $5.775B. The dedupe registry is scoped to one tag pair and an exact date
    # match, so a component pair it does not name is added twice. Falling back to
    # the largest single component keeps a figure that is at least a real line.
    if (short_term_debt is not None and current_liabilities is not None
            and short_term_debt.value > current_liabilities.value
            and short_term_debt.provenance.components):
        biggest = max(short_term_debt.provenance.components,
                      key=lambda c: _component_value(gaap, c, fresh) or Decimal(0))
        recovered = _latest_instant(gaap, biggest.concept,
                                    (biggest.tag.split(":", 1)[-1],), not_before=fresh)
        short_term_debt = (recovered if recovered is not None
                           and recovered.value <= current_liabilities.value else None)

    # A long bucket built only from a finance lease is not a company's borrowings.
    # Ford's fresh debt elements are a $754M lease liability while its own funding
    # arm carries orders of magnitude more; its noncurrent debt tag went stale in
    # 2020 and the staleness guard correctly dropped it, leaving the lease alone to
    # answer criterion 3 at 0.09x. Where the filer's history shows borrowings the
    # bucket cannot see, the figure is missing, not small.
    if (long_term_debt is not None
            and all("FinanceLease" in t for t in _tags_behind(long_term_debt))
            and _debt_elsewhere(gaap, long_term_debt)):
        long_term_debt = None
    # A combined rollup older than the parts is the stale-tag trap in another
    # place: SRI's rollup froze at $0.9M while LongTermDebt moved to $180.9M a
    # quarter later. The fresher basis wins; criterion 3 then uses the parts.
    parts_end = max((f.provenance.period_end for f in (long_term_debt, short_term_debt)
                     if f is not None and f.provenance.period_end is not None), default=None)
    if (total_debt is not None and parts_end is not None
            and total_debt.provenance.period_end is not None
            and total_debt.provenance.period_end < parts_end):
        total_debt = None
    # A rollup smaller than a part it must contain is not a total but a fragment
    # wearing a total's tag: Pangaea attaches
    # LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities to a single
    # $38.5M "current portion of financing obligations" line while $235.6M of
    # noncurrent debt sits on the same balance sheet, and criterion 3 then reads a
    # 3.75x debt load as 0.52x. Sixty-four filers ship a "total" below their own
    # long-term part, 58 of them at an identical period end, so staleness cannot
    # explain it. Only a same-date comparison can say the two describe one moment.
    if total_debt is not None:
        for part in (long_term_debt, short_term_debt):
            if (part is not None
                    and part.provenance.period_end == total_debt.provenance.period_end
                    and total_debt.value < part.value):
                total_debt = None
                break
    return total_debt, long_term_debt, short_term_debt


def _senior_claims(gaap: dict, fresh: date | None, total_assets: Fact | None,
                   total_liabilities: Fact | None, liabilities_derived: bool,
                   parent_only_derivation: bool
                   ) -> tuple[Fact | None, Fact | None, Fact | None]:
    """Everything standing between the assets and the common shareholder.

    Book value per share is what is left after these, so each one that goes
    unread overstates what the common owns. Three of them, and they overlap in
    ways the tags do not admit: preferred stock, the minority holders' share of a
    consolidated subsidiary, and mezzanine equity that is neither debt nor common.
    Returns (preferred, noncontrolling interest, temporary equity).
    """
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
    redeemable_nci = None
    if not parent_only_derivation:
        # permanent leg: alternatives for one concept — first the classic tag,
        # then the fuller variants some filers use instead (MS: 1,111M under
        # NonredeemableNoncontrollingInterest while MinorityInterest sits stale)
        permanent_nci = _latest_instant_across(
            gaap, "NoncontrollingInterest",
            ("MinorityInterest", "NonredeemableNoncontrollingInterest",
             "MinorityInterestInOperatingPartnerships",
             # WLKP carries its sponsor's two-thirds of OpCo here and nowhere else
             "MinorityInterestInLimitedPartnerships",
             "MinorityInterestInPreferredUnitHolders",   # Uber, $869M
             "PartnersCapitalAttributableToNoncontrollingInterest"),
            not_before=fresh,
        )
        redeemable_total = _latest_instant(
            gaap, "NoncontrollingInterest (redeemable)",
            ("RedeemableNoncontrollingInterestEquityCarryingAmount",), not_before=fresh,
        )
        # disjoint components, which stand in for the total where it is absent and
        # replace it where it has been abandoned mid-history (UDR tags a component
        # equal to the total; ET moved to the Other element in 2026)
        redeemable_parts = _sum_facts("NoncontrollingInterest (redeemable components)", [
                _latest_instant(
                    gaap, "NoncontrollingInterest (redeemable preferred)",
                    ("RedeemableNoncontrollingInterestEquityPreferredCarryingAmount",),
                    not_before=fresh),
                _latest_instant(
                    gaap, "NoncontrollingInterest (redeemable common)",
                    ("RedeemableNoncontrollingInterestEquityCommonCarryingAmount",),
                    not_before=fresh),
                _latest_instant(
                    gaap, "NoncontrollingInterest (redeemable other)",
                    ("RedeemableNoncontrollingInterestEquityOtherCarryingAmount",),
                    not_before=fresh),
            ])
        redeemable_nci = _fresher_rollup(redeemable_total, redeemable_parts)
        if redeemable_nci is None and _latest_instant(
            gaap, "TemporaryEquity (incl. NCI)",
            ("TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",),
            not_before=fresh,
        ) is None:
            # fair value only when every carrying representation is absent —
            # HEICO tags fair value AND the incl-NCI temporary line for the
            # same holders; counting both would remove them twice
            redeemable_nci = _latest_instant(
                gaap, "NoncontrollingInterest (redeemable, fair value)",
                ("RedeemableNoncontrollingInterestEquityFairValue",), not_before=fresh,
            )
        nci = _sum_facts("NoncontrollingInterest", [permanent_nci, redeemable_nci])
    # Mezzanine (temporary) equity is senior to common but sits outside both the
    # preferred tag and liabilities (GTN: $600M of redeemable preferred = 28% of
    # equity, invisible to tangible book). Deducted only when the preferred slot
    # is empty or a zero placeholder (KDP tags PreferredStockValue=0 beside
    # $4.4B of mezzanine) and liabilities were NOT derived from the accounting
    # identity — a derived figure already contains the mezzanine.
    temporary_equity = None
    if not liabilities_derived and (preferred is None or preferred.value == 0):
        temporary_equity = _latest_instant(
            gaap, "TemporaryEquity", ("TemporaryEquityCarryingAmountAttributableToParent",),
            not_before=fresh,
        )
        if temporary_equity is None and redeemable_nci is None:
            # the incl-NCI variant only when no redeemable-NCI leg was counted,
            # or the same holders would come out twice (HEICO/ADM)
            temporary_equity = _latest_instant(
                gaap, "TemporaryEquity (incl. NCI)",
                ("TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",),
                not_before=fresh,
            )
        if temporary_equity is None:
            # liquidation preference >= carrying value: the conservative stand-in
            temporary_equity = _latest_instant(
                gaap, "TemporaryEquity (liquidation preference)",
                ("TemporaryEquityLiquidationPreference",), not_before=fresh,
            )
    return preferred, nci, temporary_equity


def build_snapshot(
    ticker: str, cik: str, companyfacts: dict, assume_absent_zero: bool = False,
    dimensioned: dict | None = None, receipt: dict | None = None,
) -> FinancialSnapshot:
    facts = companyfacts.get("facts", {})
    _reject_foreign(facts)
    gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    # Company Facts cannot express a dimension, so a filer that reports only by
    # share class looks silent to it. The unambiguous half of those facts is read
    # through the same chains, and only ever fills a gap: a consolidated figure
    # always outranks a figure that had to be attributed to one class.
    classed = _unambiguous_dimensioned(dimensioned, (receipt or {}).get('title'))

    annual_eps = _annual_eps(gaap)
    if classed:
        annual_eps = {**_annual_eps(classed), **annual_eps}
    ttm_eps, ttm_inputs = _ttm_eps(gaap, annual_eps)
    if ttm_eps is None and classed:
        ttm_eps, ttm_inputs = _ttm_eps(classed, annual_eps)
    annual_net_income = _annual_net_income(gaap)
    ttm_net_income, ttm_ni_inputs = _ttm_eps(gaap, annual_net_income, unit=("USD",),
                                             per_share=False)
    # A negative "revenue" is a fund's net investment loss wearing a revenue
    # element (the gold trusts do this); it is not a top line, and the size test
    # would read it as a company that sold less than nothing.
    annual_revenue = {y: f for y, f in _annual_revenue(gaap).items() if f.value >= 0}
    ttm_revenue, ttm_revenue_inputs = _ttm_eps(gaap, annual_revenue, unit=("USD",),
                                               per_share=False)
    if ttm_revenue is not None and ttm_revenue < 0:
        ttm_revenue, ttm_revenue_inputs = None, ()

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
    # Assets cannot be negative. A filer that tags them so has made a sign error,
    # and carrying it through would produce a current ratio and a net current
    # asset value describing no company.
    if total_assets is not None and total_assets.value < 0:
        total_assets = None
    current_assets = _latest_instant(gaap, "AssetsCurrent", ("AssetsCurrent",), not_before=fresh)
    if current_assets is not None and current_assets.value < 0:
        current_assets = None
    current_liabilities = _latest_instant(gaap, "LiabilitiesCurrent", ("LiabilitiesCurrent",), not_before=fresh)
    if current_liabilities is None:
        # some classified filers tag only the noncurrent split; the identity
        # fills the current side. NEVER mirrored on the asset side —
        # AssetsNoncurrent is an ASC 280 disclosure, not a balance-sheet rollup.
        current_liabilities = _derived_instant(
            gaap, "LiabilitiesCurrent (derived: Liabilities - LiabilitiesNoncurrent)",
            "Liabilities", "LiabilitiesNoncurrent", fresh,
        )
    # Both legs must come from one balance sheet. Solidion shows a current ratio of
    # 1.46 built from assets at 2026-06-30 and liabilities at 2024-12-31; its own
    # June balance sheet gives 2.66. Where the pair cannot be struck at one date,
    # the ratio is not available — a figure spanning two years is not a ratio.
    if (current_assets is not None and current_liabilities is not None
            and current_assets.provenance.period_end != current_liabilities.provenance.period_end):
        slots = (("AssetsCurrent", ("AssetsCurrent",)),
                 ("LiabilitiesCurrent", ("LiabilitiesCurrent",)))
        # the newest balance sheet first — it is the one every other figure on the
        # row is struck at — then the older date, where the pair may still exist
        ends = sorted({current_assets.provenance.period_end,
                       current_liabilities.provenance.period_end}, reverse=True)
        current_assets = current_liabilities = None
        for end in ends:
            matched = [_at_period_end(gaap, concept, tags, end) for concept, tags in slots]
            if all(f is not None for f in matched):
                current_assets, current_liabilities = matched
                break
    total_debt, long_term_debt, short_term_debt = _debt_figures(
        gaap, fresh, current_liabilities)
    options_outstanding = _latest_instant(gaap, "OptionsOutstanding", OPTION_COUNT_TAGS,
                                          unit=("shares",), not_before=fresh)
    rsus_outstanding = _latest_instant(gaap, "RestrictedStockUnitsOutstanding", RSU_COUNT_TAGS,
                                       unit=("shares",), not_before=fresh)
    total_liabilities = _latest_instant(gaap, "Liabilities", ("Liabilities",), not_before=fresh)
    parent_only_derivation = False
    liabilities_derived = False
    if total_liabilities is None:
        total_liabilities, parent_only_derivation = _derive_liabilities(gaap, fresh)
        liabilities_derived = total_liabilities is not None
    goodwill = _latest_instant(gaap, "Goodwill", ("Goodwill",), not_before=fresh)
    if goodwill is None:
        # RNR files no Goodwill element at all; the combined line minus the
        # ex-goodwill line is the same figure by identity
        goodwill = _derived_instant(
            gaap, "Goodwill (derived: combined line - intangibles excluding goodwill)",
            "IntangibleAssetsNetIncludingGoodwill", "IntangibleAssetsNetExcludingGoodwill", fresh,
        )
    if goodwill is None:
        goodwill = _derived_instant(
            gaap, "Goodwill (derived: gross - accumulated impairment)",
            "GoodwillGross", "GoodwillImpairedAccumulatedImpairmentLoss", fresh,
            subtrahend_optional=True,
        )
    intangibles = _intangibles(gaap, fresh)
    if goodwill is None and intangibles is None:
        goodwill, intangibles = _combined_goodwill_and_intangibles(gaap, fresh)
    preferred, nci, temporary_equity = _senior_claims(
        gaap, fresh, total_assets, total_liabilities, liabilities_derived,
        parent_only_derivation)
    shares = _latest_instant(
        gaap, "SharesOutstanding", ("CommonStockSharesOutstanding",), unit=("shares",), not_before=fresh
    )
    if shares is None:
        shares = _latest_instant(
            dei, "SharesOutstanding", ("EntityCommonStockSharesOutstanding",),
            ns="dei", unit=("shares",), not_before=fresh,
        )
    if shares is None:
        # the generic instant only AFTER the specific tags and the dei cover:
        # fragment and mis-scale cases are shielded by that ranking (SLB)
        shares = _latest_instant(
            gaap, "SharesOutstanding", ("SharesOutstanding",), unit=("shares",), not_before=fresh
        )
    if shares is None:
        shares = _weighted_shares(gaap, fresh)
    if shares is None and classed:
        shares = _latest_instant(
            classed, "SharesOutstanding", ("CommonStockSharesOutstanding",),
            unit=("shares",), not_before=fresh,
        ) or _weighted_shares(classed, fresh)
    if shares is None and _is_partnership(gaap, fresh):
        # LP unit instants are OP-unit fragments at REITs (MAA: 2.9M against a
        # 116M cover), so they count only for a filer that has partners capital
        # and no stockholders equity at all (SUN, KRP, DLNG)
        shares = _latest_instant(
            gaap, "SharesOutstanding (limited partner units)",
            ("LimitedPartnersCapitalAccountUnitsOutstanding",), unit=("shares",), not_before=fresh,
        )
    annual_preferred_dividends = _annual_union(gaap, PREFERRED_DIVIDEND_TAGS)
    # "Stale facts are missing facts" was never applied to this series: Wheeler's
    # last preferred fact ends 2019-12-31 with a value of zero, and the trailing
    # roll carried that zero forward as though the company had stopped paying its
    # preferred holders seven years ago.
    if fresh is not None:
        annual_preferred_dividends = {
            y: f for y, f in annual_preferred_dividends.items()
            if f.provenance.period_end is None or f.provenance.period_end >= fresh}
    ttm_preferred_dividends, _ = _ttm_eps(gaap, annual_preferred_dividends,
                                          unit=("USD",), per_share=False)
    # implied shares read only TAGGED eps — derived years below are computed FROM
    # the share count and would otherwise vote for themselves
    shares = _sane_shares(shares, gaap, dei, fresh,
                          implied=_implied_shares(gaap, annual_eps, annual_net_income,
                                                  annual_preferred_dividends))
    # An option pool larger than the company it is granted out of is a tagging
    # error, not dilution: Greenlane's pool jumps from 235,000 to 235,000,000
    # between two quarters, Zerocarbon reports 3.2bn options against 10.4M shares,
    # and Astrotech 234.4M against 1.76M. Seventeen rows in all, against a median
    # overhang of 2.8% and a 99th percentile of 72%. §5.1: withhold rather than
    # publish a figure the filing cannot mean.
    if shares is not None and shares.value > 0:
        if options_outstanding is not None and options_outstanding.value > shares.value:
            options_outstanding = None
        if rsus_outstanding is not None and rsus_outstanding.value > shares.value:
            rsus_outstanding = None

    # Filers that tag earnings per share only on a share-class axis publish no
    # per-share element the Company Facts API can return (KKR since 2017, PAA
    # since 2016), and a co-op may simply stop tagging one. Their own income and
    # share count still divide, so the series continues as disclosed arithmetic
    # rather than stopping years before the balance sheet.
    derived_eps = _derived_annual_eps(gaap, dei, annual_eps, annual_net_income,
                                      annual_preferred_dividends,
                                      has_nci=_has_minority_interest(gaap, fresh, nci))
    if derived_eps:
        # the same bound the tagged series carries: a per-share element holding a
        # dollar total is unusable, and a derived one can be built from a share
        # count small enough to say the same thing (-$20,176,748.50 a share shipped)
        annual_eps = {y: f for y, f in {**annual_eps, **derived_eps}.items()
                      if abs(f.value) <= _IMPLAUSIBLE_EPS}
        # A filer that stopped tagging per-share figures still has a per-share
        # TTM in its own income statement. The tagged trailing figure is not
        # merely absent for these filers — it is years stale (KKR's last tagged
        # EPS period ended 2018), and a stale figure priced against today's quote
        # is worse than none, so newer income overrides it.
        def _newest_end(facts) -> date:
            return max((f.provenance.period_end for f in facts if f.provenance.period_end),
                       default=date.min)

        income_is_newer = _newest_end(ttm_ni_inputs) > _newest_end(ttm_inputs)
        # ...and the same minority-interest guard the annual series applies: a
        # trailing figure built from ProfitLoss divides the whole group's profit,
        # the sponsor's two thirds included, by the units the public holds.
        group_profit = any(f.provenance.tag.endswith(":ProfitLoss") for f in ttm_ni_inputs)
        trailing_income, trailing_inputs = ttm_net_income, ttm_ni_inputs
        if group_profit and _has_minority_interest(gaap, fresh, nci):
            trailing_income, trailing_inputs = _ttm_eps(
                gaap, _annual_dollar_series(gaap, PARENT_INCOME_TAGS),
                unit=("USD",), per_share=False)
            if trailing_income is None:
                # Ares and KKR tag no annual parent series long enough to roll a
                # trailing window, but both report the minority's share directly.
                # Subtracting it reaches the same figure from the other side.
                minority = sum(
                    (v for tag in NCI_INCOME_TAGS
                     if (v := _ttm_eps(gaap, _annual_dollar_series(gaap, (tag,)),
                                       unit=("USD",), per_share=False)[0]) is not None),
                    Decimal(0))
                if minority:
                    trailing_income = ttm_net_income - minority
                    trailing_inputs = ttm_ni_inputs
        if ((ttm_eps is None or income_is_newer)
                and trailing_income is not None and shares and shares.value > 0):
            ttm_eps = ((trailing_income - (ttm_preferred_dividends or Decimal(0)))
                       / shares.value)
            # the trailing figure still carries a date: the newest income period
            # behind it, which is what decides whether a price may be compared
            newest = max(trailing_inputs, key=lambda f: f.provenance.period_end or date.min,
                         default=None)
            if newest is not None:
                p = newest.provenance
                ttm_inputs = (Fact(value=ttm_eps, provenance=Provenance(
                    concept="TTM EPS (derived: earnings available to common / share count)",
                    tag=f"{p.tag} / {shares.provenance.tag}",
                    fiscal_year=None, form=p.form, accession=p.accession,
                    filed=p.filed, period_end=p.period_end, period_start=p.period_start,
                )),)

    balance_sheet_date = next(
        (f.provenance.period_end for f in (current_assets, total_assets) if f is not None), None
    )
    # A trailing figure anchored to a decade-old annual filing is not trailing:
    # iShares Gold Trust last tagged revenue for 2013 and it was being presented
    # beside a 2026 balance sheet. Old is not the same as absent, but presenting
    # it as the current twelve months is the same as being wrong.
    if balance_sheet_date is not None:
        floor = balance_sheet_date - timedelta(days=_STALE_DAYS)
        if _newest_period_end(ttm_revenue_inputs) < floor:
            ttm_revenue = None

    reference = balance_sheet_date or _latest_annual_end(annual_eps)
    pays_dividend, dividend = _dividend(gaap, reference)
    dividend_per_share = _dividend_per_share(gaap, dividend, shares, fresh)

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

    # Whether the filing is internally consistent is asked of the filing's own
    # figures, before any restatement onto the traded security — the ratio moves
    # both sides of that comparison and would otherwise create the mismatch it is
    # there to detect.
    basis_conflict = _basis_conflict(gaap, dei, annual_eps, annual_net_income,
                                     annual_preferred_dividends,
                                     _has_minority_interest(gaap, fresh, nci), shares)

    # A depositary receipt is priced per receipt while the statements count the
    # ordinary shares behind it; the cover names the ratio and nothing else can.
    if receipt and receipt.get("ratio"):
        ratio = Decimal(str(receipt["ratio"]))
        if ratio > 1:
            parts = {"shares": shares, "annual_eps": annual_eps, "ttm_eps": ttm_eps,
                     "dividend_per_share": dividend_per_share,
                     "ttm_preferred_dividends": ttm_preferred_dividends}
            _restate_onto_receipt(parts, ratio, receipt.get("accn", ""))
            shares, annual_eps = parts["shares"], parts["annual_eps"]
            ttm_eps, dividend_per_share = parts["ttm_eps"], parts["dividend_per_share"]
            ttm_preferred_dividends = parts["ttm_preferred_dividends"]

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
        temporary_equity=temporary_equity,
        ttm_preferred_dividends=ttm_preferred_dividends,
        annual_preferred_dividends={y: f.value for y, f
                                    in annual_preferred_dividends.items()},
        shares_outstanding=shares,
        cover_shares=_latest_instant(dei, "EntityCommonStockSharesOutstanding",
                                     ("EntityCommonStockSharesOutstanding",),
                                     ns="dei", unit=("shares",)),
        dividend=dividend,
        dividend_per_share=dividend_per_share,
        pays_dividend=pays_dividend,
        balance_sheet_date=balance_sheet_date,
        total_debt=total_debt,
        options_outstanding=options_outstanding,
        rsus_outstanding=rsus_outstanding,
        assumed_zero=frozenset(assumed),
        noncontrolling_interest=nci,
        earnings_quality=_earnings_quality(gaap, ttm_inputs, annual_eps),
        context_notes=_context_notes(gaap, annual_eps, annual_net_income,
                                     _annual_operating_income(gaap),
                                     annual_revenue, long_term_debt, shares,
                                     _common_equity(total_assets, total_liabilities,
                                                    preferred, nci, temporary_equity),
                                     fresh, dimensioned),
        tax_record=_tax_record(gaap, fresh),
        owner_earnings=owner_earnings,
        basis_conflict=basis_conflict,
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
    """Facts for a tag, in the unit the caller asked for.

    Never in some other unit. Enbridge, Canadian Pacific and Imperial Oil report
    earnings per share only in CAD/shares, and taking whatever unit happened to be
    first divided a New York price by a Canadian figure — a P/E understated by the
    exchange rate, with nothing on the page saying so. A figure in the wrong
    currency is not a weaker figure, it is a different quantity.
    """
    units = taxo.get(tag, {}).get("units", {})
    for unit in unit_pref:
        if unit in units:
            # A period cannot close after the filing that reports it. PennyMac's
            # long-term debt was dated 2030-09-30, AAGH's a zero dated 2031-12-31 —
            # the stale-zero trap reached through the date instead of the tag order
            # — and Mannatech's dividend 2108-11-14. Eighteen such facts won a
            # "latest instant" pick outright, because latest is exactly what they
            # claim to be.
            return [e for e in units[unit]
                    if not (e.get("filed") and e.get("end") and e["end"] > e["filed"])]
    return []


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
            segments=e.get("segments", ""),
        ),
    )


_SPLIT_RATIOS = (1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100)
_FY_CLUSTER_DAYS = 20                   # a 52/53-week year re-dated is still that year
_SPLIT_VOTE_FLOOR = Decimal("0.05")     # per-share values below this vote on rounding
_SPLIT_RUN_GAP = 275                    # one restatement cycle: three quarters
_SPLIT_RUN_SPAN = 550                   # ...and a run may not chain past two years
_SHARE_CORROBORATION = Decimal("0.10")  # how far the share count may sit from the factor


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
        _by_period([e for e in _entries(gaap, tag, ("USD/shares",))
                    if "start" in e and _is_financial_form(e.get("form", ""))],
                   tag=tag, into=out)
    return out


def _share_periods(gaap: dict) -> dict:
    """The weighted-average share counts, pooled the same way, as a second witness.

    A split rebases the share count by exactly the factor it rebases per-share
    figures, so the two must move together. Essential Utilities files another
    registrant's audited statements under its own CIK: the earnings per share differ
    by 2.5x, which lands on a split candidate, while the share counts differ by 1.41x,
    which proves the two figures describe different companies rather than one company
    before and after a corporate action.
    """
    out: dict = {}
    for tag in _WEIGHTED_SHARE_TAGS:
        _by_period([e for e in _entries(gaap, tag, ("shares",))
                    if "start" in e and _is_financial_form(e.get("form", ""))],
                   tag=tag, into=out)
    return out


def _split_factor(periods: dict[tuple[str, str], list[tuple[str, Decimal]]],
                  filed: str, shares: dict | None = None) -> Decimal:
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
    for split_filed, k in _split_events(periods, shares):
        if filed < split_filed:
            factor *= k
    return factor


def _split_events(periods: dict[tuple[str, str], list[tuple[str, Decimal]]],
                  shares: dict | None = None) -> list[tuple[str, Decimal]]:
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
            # A cent moving on a two-cent figure lands on 1.5 or 0.5 as readily as a
            # real split does. Idaho Copper restated -0.02 to -0.01 and had its whole
            # pre-2021 record rescaled by a third; Apple's 2010 revenue-recognition
            # restatement read as a 2:3. Rounding is not a corporate action.
            if min(abs(old), abs(new)) < _SPLIT_VOTE_FLOOR:
                continue
            k = _as_split(old / new)
            if k is not None:
                votes.setdefault(filed_new, []).append(k)
    events: list[tuple[str, Decimal]] = []
    # the newest filing already folded into the current run, and where the run began:
    # one measures "the same restatement cycle", the other bounds how far a single
    # corporate action may go on being restated
    run_last = run_start = None
    for f in sorted(votes):
        ks = votes[f]
        k = max(set(ks), key=ks.count)  # periods disagreeing on one filing: take majority
        if not _shares_agree(shares or {}, f, k):
            continue
        if (events and events[-1][1] == k and run_last is not None
                and (date.fromisoformat(f) - date.fromisoformat(run_last)).days <= _SPLIT_RUN_GAP
                and (date.fromisoformat(f) - date.fromisoformat(run_start)).days <= _SPLIT_RUN_SPAN):
            # Lam Research's 10:1 reaches Company Facts one comparative at a time over
            # 287 days. Measuring the gap from the run's FIRST filing books the last
            # restatement as a second 10:1, and a year no filing ever restated comes out
            # divided by 100.
            run_last = f
            continue
        events.append((f, k))
        run_start = run_last = f
    return events


def _shares_agree(shares: dict, filed: str, k: Decimal) -> bool:
    """Whether the share counts restated in this filing moved by the same factor.

    Silence is not dissent: a filer that reports its share count in only one vintage
    offers no second witness, and a genuine split must not be discarded for that. Only
    an observed count that moved by a materially different factor refutes the event.
    """
    observed = []
    for vals in shares.values():
        for (_, old), (filed_new, new) in zip(vals, vals[1:]):
            if filed_new == filed and old and new:
                observed.append(old / new)
    if not observed:
        return True
    # One filing restates several periods, and only the ones spanning the split move
    # by the factor — the rest drift a percent or two on buybacks. So the question is
    # whether ANY restated count moved by k, not what the typical one did: a median
    # over a dozen quiet periods vetoes every genuine split.
    # A 25:1 split divides earnings per share by 25 and multiplies the share count by
    # 25, so the two ratios are reciprocals: the corroborating count is the one whose
    # old/new lands on 1/k.
    return any(abs(ratio * k - 1) <= _SHARE_CORROBORATION for ratio in observed)


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
    kept: dict[int, str] = {}
    for end in sorted(by_end):
        if end not in labels:
            continue
        fy = labels[end]
        # one fiscal year re-dated across filings: the restatement is the answer
        prev = kept.get(fy)
        if prev is not None and by_end[end]["filed"] <= by_end[prev]["filed"]:
            continue
        kept[fy] = end
        series[fy] = _fact(tag, tag, by_end[end], fiscal_year=fy)
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
            # A 52/53-week filer re-dates the same fiscal year by a few days:
            # ATI's fiscal 2021 ends 2021-12-31 in one filing and 2022-01-02 in
            # the restated one. Dropping the second discards the restatement and
            # keeps a loss the company has since restated to a profit, which
            # inverts the latest-filed-wins rule. Two genuine annual periods
            # cannot both run 340-400 days and end a fortnight apart, so a
            # collision that close is one year reported twice.
            held = next((k for k, v in labels.items() if v == guess), None)
            if held is None or abs((end_d - date.fromisoformat(held)).days) > _FY_CLUSTER_DAYS:
                continue  # a real duplicate; keep the framed/earlier one
        labels[end] = guess
        taken.add(guess)
    return labels


_EPS_RECONCILES = Decimal("0.02")     # a rounded per-share figure lands this close
_EPS_CONTRADICTS = Decimal("0.05")    # beyond this the filing disagrees with itself


def _reconciled_annual_eps(gaap: dict, series: dict[int, Fact],
                           preferred: dict[int, Fact] | None = None,
                           has_nci: bool = False) -> dict[int, Fact]:
    """Replace an EPS that its own filing's arithmetic contradicts.

    Earnings per share is not an independent fact: the filing states the income and
    the weighted count it was struck from, and the three must agree. Where a later
    filing reports the same year again, the restatement rule takes the newer figure
    — right for a genuine restatement, wrong when the newer figure is a mis-tag,
    because a mis-tag arrives dressed as a restatement.

    The Eastern Company's fiscal 2020 is the case. Its own 10-K states $5,405,522 of
    net income on 6,264,521 weighted shares — $0.86 a share, which is what the 2021
    filing tagged. The 2022 filing tagged $1.76 against the same period while
    leaving the income and the count untouched, so the newer figure contradicts the
    numbers beside it rather than superseding them. Eleven filers do this, several
    by sign alone: Truett-Hurst tags +$0.64 for a year its own income says was
    -$0.64.

    Two things keep this narrow. The swap only ever happens WITHIN one concept, so a
    diluted figure is never quietly replaced by a basic or a continuing-operations
    one — that would change what the series measures, not correct it. And a
    continuing-operations figure is never tested at all: it is meant to differ from
    total net income, which is exactly why `_basis_conflict` abstains on it too.
    Eastern's own fiscal 2024 is the reason — $2.13 from continuing operations
    beside a total loss of $1.37 a share is not an error, it is a discontinued
    business. A real restatement moves the income with the per-share figure, so
    nothing here disturbs one.
    """
    # The same two abstentions `_basis_conflict` makes, and for the same reason:
    # earnings per share is struck on income available to the common, so a preferred
    # dividend or a minority interest puts a legitimate wedge between it and net
    # income. Markel's fiscal 2020 is $55.63 against a net income that divides to
    # $59.03, and the $47M gap is its preferred dividend, not a mis-tag.
    if not series or has_nci:
        return series
    preferred = preferred or {}
    income = _by_accession(gaap, NET_INCOME_TAGS, ("USD",))
    diluted = _by_accession(gaap, ("WeightedAverageNumberOfDilutedSharesOutstanding",), ("shares",))
    basic = _by_accession(gaap, ("WeightedAverageNumberOfSharesOutstandingBasic",), ("shares",))
    out = dict(series)
    for year, chosen in series.items():
        tag = chosen.provenance.tag.split(":", 1)[-1]
        end = chosen.provenance.period_end
        if end is None or "ContinuingOperations" in tag or year in preferred:
            continue
        iso = end.isoformat()
        # the count that belongs to this concept: a diluted figure divides the
        # diluted count, and comparing it against the basic one invents a mismatch
        counts = basic if "Basic" in tag and "Diluted" not in tag else diluted

        def implied(accn: str) -> Decimal | None:
            ni, sh = income.get((accn, iso)), counts.get((accn, iso))
            return ni / sh if ni is not None and sh else None

        target = implied(chosen.provenance.accession)
        if target is None or abs(target) < Decimal("0.01"):
            continue
        if abs(chosen.value - target) <= _EPS_CONTRADICTS * abs(target):
            continue                                    # the filing agrees with itself
        for e in _entries(gaap, tag, ("USD/shares",)):
            if e.get("end") != iso or "start" not in e or not _is_annual_form(e.get("form", "")):
                continue
            # Only where the earlier filing states the SAME income on the SAME count:
            # that is what a mis-tag looks like, a per-share figure moving while the
            # two numbers it is made of stand still. A genuine restatement moves them
            # together — Gyre's fiscal 2022 went from -$8.2M on 31.5M shares to
            # +$4.3M on 75.7M after a reverse merger — and must be left alone.
            if (income.get((e["accn"], iso)) != income.get((chosen.provenance.accession, iso))
                    or counts.get((e["accn"], iso)) != counts.get((chosen.provenance.accession, iso))):
                continue
            other = implied(e["accn"])
            if other is None:
                continue
            if abs(_dec(e["val"]) - other) <= _EPS_RECONCILES * abs(other):
                out[year] = _fact(chosen.provenance.concept, tag, e)
                break
    return out


def _by_accession(gaap: dict, tags: tuple[str, ...], unit: tuple[str, ...]) -> dict[tuple, Decimal]:
    """One full-year value per (filing, period end), so a figure can be checked
    against the others the same document states rather than against a series that
    has already collapsed several filings into one."""
    out: dict[tuple, Decimal] = {}
    for tag in tags:
        for e in _entries(gaap, tag, unit):
            if "start" not in e or not _is_annual_form(e.get("form", "")):
                continue
            if _days(e) not in _ANNUAL_DAYS:
                continue
            out.setdefault((e["accn"], e["end"]), _dec(e["val"]))
    return out


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
    named = [(f"tag{i}", series) for i, series in enumerate(candidates)]
    continuing_key = next((k for k, series in named if series is continuing), None)
    _, best = _best_series(named, {k: 0 for k, _ in named},
                           prefer=lambda tag: tag == continuing_key)
    # reconciled after the gaps are filled — a year that enters the series from a
    # second tag needs checking too, and Eastern's fiscal 2020 is exactly that —
    # and before the split adjustment, since the check compares filed figures
    # against the filed income and count they were struck from.
    # Preferred dividends and minority interests are read here rather than passed in:
    # this runs before either is settled elsewhere, and both are only needed to know
    # when to abstain.
    series = _split_adjust(
        _reconciled_annual_eps(gaap, _fill_missing_years(best, gaap),
                               preferred=_annual_union(gaap, PREFERRED_DIVIDEND_TAGS),
                               has_nci=bool(_latest_instant(gaap, "nci", ("MinorityInterest",)))),
        gaap)
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
    shares = _share_periods(gaap)
    if not periods:
        return series
    out: dict[int, Fact] = {}
    for fy, fact in series.items():
        factor = _split_factor(periods, fact.provenance.filed.isoformat(), shares)
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


def _best_series(candidates: list[tuple[str, dict]], order: dict[str, int],
                 prefer=lambda tag: False) -> tuple[str, dict]:
    """Which of several elements is THE series for a concept.

    One rule, in one place, because it was written three times with the three keys
    in three different orders and two of them were wrong. It ranks:

      1. recency — a series that stopped years ago cannot answer for today, whatever
         it is called. This is what lets a filer abandon an element mid-history.
      2. meaning — what the element IS. These chains are ordered by scope, and
         `ProfitLoss` is the whole group's profit where `NetIncomeLoss` is the
         parent's; `Revenues` is a total where a contract element is part of one.
      3. depth — only then. Starwood files sixteen years of the group's profit
         beside fourteen of its own, and ranking depth second handed two extra years
         of history the power to swap one concept for the other, so every margin and
         per-share figure divided profit the shareholders do not own.

    `prefer` marks a tag that outranks the tag order itself — §5.3's preference for
    continuing operations, which is a statement about scope rather than about which
    element a filer happens to use.
    """
    return max(candidates, key=lambda c: (max(c[1]), prefer(c[0]), -order[c[0]], len(c[1])))


def _annual_dollar_series(gaap: dict, tags: tuple[str, ...]) -> dict[int, Fact]:
    """Filers switch elements mid-history the same way they switch EPS elements —
    Advanced Energy's NetIncomeLoss series stops in 2024 while ProfitLoss runs on.
    Taking the first tag that returns anything would freeze the series a year back,
    so candidates are ranked by recency first.

    Then by tag preference, and only then by depth. The order matters: these tags
    differ in SCOPE, not merely in coverage. Starwood Property Trust files fourteen
    years of `NetIncomeLoss` — the parent's own $411.5M, which is what its printed
    income statement calls "Net income attributable to Starwood Property Trust" —
    beside sixteen years of `ProfitLoss`, the group's $443.1M including the minority
    holders. Ranking depth first handed two extra years of history the power to
    swap one for the other, and every margin and per-share figure then divided
    profit the shareholders do not own. Recency still settles the abandoned-series
    case, because a dead tag cannot win it."""
    candidates = [
        (tag, series)
        for tag in tags
        if (series := _annual_series(gaap, tag, unit=("USD",)))
    ]
    if not candidates:
        return {}
    order = {tag: i for i, tag in enumerate(tags)}
    _, best = _best_series(candidates, order)
    for _, other in candidates:                      # fill gaps the winner lacks
        for fy, fact in other.items():
            best.setdefault(fy, fact)
    return dict(sorted(best.items()))


def _annual_net_income(gaap: dict) -> dict[int, Fact]:
    """The parent's own profit each year.

    Not rebuilt from the group's figure minus the minority's, though the identity
    is tempting: Vivid Seats tags fiscal 2025 net income of +$806.1M beside a group
    loss of $721.5M, and its printed statement says -$292.2M. But the minority's
    own line is not reliably on file — TKO tags only the redeemable half of its
    noncontrolling interests without a dimension, so the same subtraction turns its
    correct $195.4M into $540.1M. One filer's bad tag is not worth another's good
    one, so the mis-tagged year stands and the audit reports it.
    """
    return _annual_dollar_series(gaap, NET_INCOME_TAGS)


# staying on one element tolerates real business swings (Carnival's COVID
# collapse and 6x recovery are one tag's honest numbers); moving to a different
# element demands tight agreement, because elements differ in SCOPE and a large
# step at a boundary is a scope mismatch, not history
_SAME_TAG_RATIO = (Decimal(1) / 10, Decimal(10))
_SWITCH_RATIO = (Decimal(1) / 3, Decimal(3))


# `Revenues` is the umbrella total and `RevenueFromContractWithCustomer...` is the
# part of it that came from contracts with customers. Only these two stand in that
# relation — the assessed-tax pair does not, and taking the larger of THOSE would
# count sales taxes collected for the state as the company's revenue.
_TOTAL_AND_PART = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")


# Revenue net of interest expense IS the top line for a filer that lends or makes
# markets — the figure its own income statement totals to. Gross interest income is
# inside it and is larger, so no comparison by size can rank the two; the concepts
# do it instead.
_NET_OF_INTEREST = "RevenuesNetOfInterestExpense"
_INSIDE_NET_OF_INTEREST = ("InterestIncomeOperating", "InterestAndDividendIncomeOperating",
                           "InterestIncomeExpenseNet")


def _wider_top_line(pool, tag: str, series: dict[int, Fact]):
    """Between a total and its own part, the total is the larger of the two.

    Ovintiv files $8,663M of contract revenue beside $8,908M of `Revenues`, and its
    income statement prints the second as "Total Revenues" — the difference is
    revenue that did not come from a contract with a customer. Ares files the
    reverse, $5,601M of contract revenue against a $4,756M `Revenues` that covers
    less than its own statement's "Total revenues". Ranking by tag order picked the
    smaller in both cases, each for a different reason.

    Whichever element holds the bigger figure for the shared year is the total; the
    other is a piece of it. Nothing else in the chain is compared this way, so a
    sector top line that is legitimately larger than a mis-scoped `Revenues` — the
    reason the order exists — is untouched.

    Not universal, and known not to be. Benchmark Electronics tags $2,748.7M of
    contract revenue against $2,659.1M of `Revenues`, and its printed statement
    closes on the smaller: sales of 2,659.1 less cost of sales of 2,389.0 is the
    gross profit of 270.1 it reports. Taking the larger is right for Ovintiv and for
    Ares and wrong for Benchmark, and no rule reading only these two tags can tell
    the three apart — the income statement's own arithmetic settles it and is not in
    the data. The rule follows the majority and `make audit-filings` names the
    exceptions.
    """
    if tag in _INSIDE_NET_OF_INTEREST:
        # Interactive Brokers' interest income is $7,782M against $6,205M of revenue
        # net of interest expense, and the panel showed the gross component as the
        # company's sales. The statement totals to the second.
        whole = next((s for t, s in pool if t == _NET_OF_INTEREST), None)
        if whole is not None and max(whole) >= max(series):
            return _NET_OF_INTEREST, whole
    if tag not in _TOTAL_AND_PART:
        return tag, series
    other = next((s for t, s in pool if t in _TOTAL_AND_PART and t != tag), None)
    if other is None:
        return tag, series
    year = max(series)
    if max(other) != year or other[year].value <= series[year].value:
        return tag, series
    return next(t for t in _TOTAL_AND_PART if t != tag), other


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
    # NOT `_best_series`: revenue ranks depth above tag order, and alone among the
    # three chains it is right to. REVENUE_TAGS is not ordered by scope but by
    # generality — the sector top lines a bank, a REIT or a utility needs come after
    # the generic elements, so preferring an earlier tag prefers a generic scrap over
    # the line that is actually the company's revenue. Duke Energy's own statement
    # totals to the $32,237M this ordering finds; ranking by tag order gave $31,741M.
    # The scope guard here is `peak / 2` above, not the order.
    tag0, s0 = max(strong, key=lambda c: (max(c[1]), len(c[1]), -order[c[0]]))
    tag0, s0 = _wider_top_line(strong, tag0, s0)
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


def fiscal_year_ends(gaap: dict) -> dict[int, str]:
    """The date each fiscal year actually closed on, by the label it carries.

    Microsoft's fiscal 2026 ends 2026-06-30, not 2026-12-31. Both halves of every
    multiple below are struck at this date — the price of that year and the
    trailing earnings knowable then — because a December close divided by a June
    balance sheet describes no moment that existed. Only annual filings are read,
    so the date has always already happened.
    """
    ends: dict[int, str] = {}
    sources = [_annual_balances(gaap, tags) for tags in
               (("Assets", "LiabilitiesAndStockholdersEquity"),
                ("StockholdersEquity",), ("AssetsCurrent",))]
    # A year whose balance sheet is untagged still closed on a date, and its own
    # income statement carries it. Without this the year would drop out of the
    # series entirely, which is worse than reading its end from the earnings side.
    sources.append(_annual_eps(gaap))
    for series in sources:
        for year, f in series.items():
            if year not in ends and f.provenance.period_end is not None:
                ends[year] = f.provenance.period_end.isoformat()
    return ends


def vintage_ttm_eps(gaap: dict) -> dict[str, Decimal]:
    """TTM EPS as it was knowable at each of the last fiscal year ends: the
    ordinary composite, run only on facts FILED by that date. No look-ahead — a
    10-K published in August was not knowledge the previous June, so a June filer's
    figure here is its trailing four quarters through Q3, exactly what a reader
    standing on that date could compute.

    Keyed by the fiscal year end itself rather than by a calendar December, which
    is the same date only for December filers. `fiscal_year_ends` is the one
    source both this series and the ratio table read, so their keys cannot drift.

    Each figure is then rebased onto today's share count (splits filed after the
    cutoff divided out), because the price series it will be divided into is
    split-adjusted to today as well."""
    periods = _per_share_periods(gaap)
    shares = _share_periods(gaap)
    out: dict[str, Decimal] = {}
    ends = fiscal_year_ends(gaap)
    for year in sorted(ends)[-7:]:
        iso = ends[year]
        cut = _filed_by(gaap, iso)
        ttm, _ = _ttm_eps(cut, _annual_eps(cut))
        if ttm is None:
            continue
        factor = _split_factor(periods, iso, shares) if periods else Decimal(1)
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
    emitted: set[str] = set()

    def swing_text(tag: str, amount: Decimal) -> str:
        # the year-earlier comparable period shows whether this line is steady or a swing
        prior = _year_earlier_fact(gaap, tag, cur.period_start, cur.period_end)
        if prior is None:
            return " No comparable figure is tagged for the year-earlier period."
        if abs(amount - prior) < abs(amount) * Decimal("0.25"):
            return (f" It was {prior / _MILLION:+,.0f}M in the same period a year earlier — "
                    "steady, so it is not what makes this period unusual.")
        return (f" The same line was {prior / _MILLION:+,.0f}M a year earlier, a swing of "
                f"{abs(amount - prior) / _MILLION:,.0f}M between the two periods.")

    def emit(tag: str, label: str, gain_signed: bool = False, neutral: bool = False) -> None:
        amount = _duration_fact(gaap, tag, start, end)
        if amount is None or amount == 0 or amount in seen:
            return
        # "23% of pre-tax income" against a pre-tax LOSS states a proportion of a
        # negative, which reads as though the charge were part of a profit. The
        # materiality test still needs a scale, and a loss is one, but the sentence
        # cannot be written as a share of income.
        if not (pretax and pretax > 0 and abs(amount) / abs(pretax) >= _NONCASH_MATERIALITY):
            return
        seen.add(amount)
        emitted.add(tag)
        share = abs(amount) / abs(pretax) * 100
        if neutral:
            lead = (f"{label.capitalize()} of {abs(amount) / _MILLION:,.0f}M moved pre-tax income "
                    "in a direction the filing's sign convention cannot settle")
        else:
            positive_adds = amount > 0 if gain_signed else amount < 0
            direction = "added to" if positive_adds else "reduced"
            lead = f"{label.capitalize()} of {abs(amount) / _MILLION:,.0f}M {direction} pre-tax income"
        notes.append(_note(
            label[0].upper() + label[1:],
            f"{lead} for {start} to {end}, a period inside the trailing window — {share:.0f}% of "
            f"that period's {pretax / _MILLION:,.0f}M pre-tax income.{swing_text(tag, amount)} "
            "Judge for yourself whether it belongs in a run-rate earnings figure."
        ))

    for tag, label in NONCASH_TAGS:
        emit(tag, label)
    if not (emitted & _IMPAIRMENT_SPECIFICS):
        emit(*_IMPAIRMENT_ROLLUP)
    for tag, label in GAIN_TAGS:
        emit(tag, label, gain_signed=True)
    emit(*_WARRANT_TAG, neutral=True)

    # a loss quarter dropping out of (or sitting inside) the window swings the TTM
    tag = ttm_inputs[0].provenance.tag.split(":", 1)[1]
    quarters = [
        e for e in _entries(gaap, tag, ("USD/shares",))
        if "start" in e and 80 <= _days(e) <= 100 and _dec(e["val"]) < 0
        and e["end"] >= (cur.period_end - timedelta(days=730)).isoformat()
    ]
    if quarters:
        worst = min(quarters, key=lambda e: e["val"])
        notes.append(_note(
            "Loss quarter",
            f"A loss quarter ({worst['start']} to {worst['end']}, {_dec(worst['val'])} per share) "
            "falls in or near the trailing window; whether it is inside or outside moves the "
            "trailing figure without anything changing in the business."
        ))

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
            notes.append(_note(
                "Share-count spread",
                f"The three periods combined into the trailing figure carry diluted share counts "
                f"differing by {spread * 100:.0f}% ({min(counts) / _MILLION:,.0f}M to "
                f"{max(counts) / _MILLION:,.0f}M), so the sum is not a like-for-like per-share number."
            ))
    return tuple(notes)


def _shares_incomparable(gaap: dict, cur: dict, prior: dict) -> bool:
    """True when the two year-to-date periods were struck on share counts so
    different that their per-share figures cannot be subtracted — an IPO, a large
    secondary, or a reverse split between them."""
    # A filer that reports only basic shares left this guard blind, because it read one
    # hard-coded diluted tag and gave up. Every other extractor here walks a chain; this
    # one now does too, and both legs must come from the same tag or the comparison is
    # between two different measures rather than two periods.
    # ...and the ratios from every tag are weighed together, not just the first.
    # A loss makes a convertible antidilutive, so the DILUTED count collapses to the
    # basic one while the company itself did nothing: AMC Networks reports 43,320
    # basic and 43,320 diluted in every loss column and 44,845 against 56,482 in every
    # profit one. Its basic count moved 3.4%. Taking the smallest disagreement asks
    # "did the share base really change", which is the question the guard exists for.
    ratios = []
    for tag in _WEIGHTED_SHARE_TAGS:
        counts = [_duration_fact(gaap, tag, e["start"], e["end"], unit=("shares",))
                  for e in (cur, prior)]
        if all(c is not None and c > 0 for c in counts):
            ratios.append(max(counts) / min(counts) - 1)
    if not ratios:
        return False        # unknown share counts are not evidence of a problem
    return min(ratios) >= _SHARE_INCOMPARABLE


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


def _at_period_end(taxo: dict, concept: str, tags: tuple[str, ...], end: date | None,
                   unit: tuple[str, ...] = ("USD",)) -> Fact | None:
    """The figure as of one exact balance-sheet date, or nothing."""
    if end is None:
        return None
    for tag in tags:
        entries = [e for e in _entries(taxo, tag, unit)
                   if "start" not in e and _is_financial_form(e.get("form", ""))
                   and e["end"] == end.isoformat()]
        if entries:
            return _fact(concept, tag, max(entries, key=lambda e: e["filed"]))
    return None


def _latest_instant_across(
    taxo: dict,
    concept: str,
    tags: tuple[str, ...],
    unit: tuple[str, ...] = ("USD",),
    not_before: date | None = None,
    largest_wins: bool = False,
) -> Fact | None:
    """Latest period end wins ACROSS the whole chain; chain order only breaks ties.

    Debt chains need this, not first-tag-wins: a filer that stops updating a
    high-priority tag leaves a stale figure — often a zero — that would outrank a
    newer fact on a lower-priority tag, and understating debt is the
    anti-conservative direction for criterion 3."""
    floor = not_before.isoformat() if not_before else ""
    best: tuple[dict, str] | None = None
    for tag in tags:
        entries = [
            e
            for e in _entries(taxo, tag, unit)
            if "start" not in e
            and _is_financial_form(e.get("form", ""))
            and e["end"] >= floor
        ]
        if not entries:
            continue
        e = max(entries, key=lambda e: (e["end"], e["filed"]))
        if best is None or e["end"] > best[0]["end"]:
            best = (e, tag)
        elif largest_wins and e["end"] == best[0]["end"] and e["val"] > best[0]["val"]:
            # Chain order breaks the tie everywhere else, and for debt that lets a
            # footnote fragment outrank the balance-sheet line it belongs to:
            # Carriage Services shipped 14.4M where its own LongTermDebt reads
            # 526.0M at the same date and LongTermDebtNoncurrent 5.4M is a note.
            # Between two figures for one date, the whole is the larger.
            best = (e, tag)
    if best is None:
        return None
    return _fact(concept, best[1], best[0])


def _tag_of(fact: Fact | None) -> str | None:
    return fact.provenance.tag.split(":", 1)[1] if fact else None


# Short-bucket slots a combined (current + noncurrent) long-bucket tag makes
# redundant. Every combined tag counted in the long bucket must name its
# suppressions here, or the current portion is counted twice across the buckets.
# NotesPayable-family totals also cover their convertible members, so counting
# them suppresses the convertible-current family too.
_COMBINED_SUPPRESSIONS = {
    "LongTermDebt": frozenset({"ltd_current"}),  # the plain tag includes current maturities
    "NotesAndLoansPayable": frozenset({"ltd_current", "notes_current", "loans_current", "convertible_current"}),
    "NotesPayable": frozenset({"ltd_current", "notes_current", "convertible_current"}),
    "LoansPayable": frozenset({"ltd_current", "loans_current"}),
    "ConvertibleDebt": frozenset({"convertible_current"}),
    "ConvertibleNotesPayable": frozenset({"convertible_current"}),
    "LineOfCredit": frozenset({"loc_current"}),
    "SecuredDebt": frozenset({"secured_current"}),
    "FinanceLeaseLiability": frozenset({"finance_lease_current"}),
    "SeniorNotes": frozenset({"senior_current"}),
    "OtherLoansPayable": frozenset({"loans_current"}),
}


def _tags_behind(fact: Fact) -> list[str]:
    """Every element a figure rests on, a sum's components included."""
    p = fact.provenance
    return [c.tag for c in p.components] or [p.tag]


def _debt_elsewhere(gaap: dict, lease: Fact) -> bool:
    """Whether the interest bill is too large for the lease to be the whole debt.

    A finance lease costs its own interest rate — a few per cent of the balance a
    year. Ford pays $1,254M against a $754M lease book, so 166% of the principal:
    money is being paid for borrowings this bucket cannot see, and its own debt
    element went stale in 2020. The bar is deliberately at the whole principal
    rather than at a plausible interest rate, because most filers with a lease-only
    bucket are genuinely debt-free (Vertex, Incyte, MongoDB, Plexus all sit well
    under it) and a wrong INSUFFICIENT costs a reader a real answer.
    """
    interest = _annual_union(gaap, INTEREST_EXPENSE_TAGS)
    if not interest or lease.value <= 0:
        return False
    latest = max(interest)
    return abs(interest[latest].value) >= lease.value


def _component_value(gaap: dict, component, fresh: date | None) -> Decimal | None:
    f = _latest_instant(gaap, component.concept, (component.tag.split(":", 1)[-1],),
                        not_before=fresh)
    return f.value if f else None


def _fresher_or_larger(a: Fact | None, b: Fact | None) -> Fact | None:
    """Between two readings of one quantity: the newer balance sheet, and at one
    date the larger figure — a fragment cannot exceed the line it is part of, and
    understating debt is the direction criterion 3 must never err in."""
    if a is None or b is None:
        return a or b
    ends = (a.provenance.period_end, b.provenance.period_end)
    if ends[0] != ends[1] and None not in ends:
        return a if ends[0] > ends[1] else b
    return a if a.value >= b.value else b


def _long_term_debt(gaap: dict, not_before: date | None) -> tuple[Fact | None, frozenset[str]]:
    primary = _latest_instant_across(
        gaap, "LongTermDebt",
        ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
         "LongTermNotesPayable", "LongTermDebt"),
        not_before=not_before, largest_wins=True,
    )
    # The instrument families are a SECOND representation of the same debt, not an
    # addition to the first, so they are built whatever the primary chain found and
    # the better of the two is taken. Gating them on "primary is None" dropped
    # WisdomTree's $1,057.6M of convertibles because a $13.6M LongTermNotesPayable
    # had satisfied the chain, and left Standard Motor's superseded revolver in
    # place while the fresher LongTermLineOfCredit sat in the same filing.
    instrument_parts: list[Fact | None] = []
    if True:
        parts_target = instrument_parts
        parts_target.append(_latest_instant(
            gaap, "LongTermDebt (other)",
            # the plain element beside the noncurrent one: Procter & Gamble carries
            # $5,265M there and nothing read it
            ("OtherLongTermDebtNoncurrent", "OtherLongTermDebt"), not_before=not_before
        ))
        parts_target.append(_latest_instant_across(
            gaap, "LongTermDebt (commercial paper, term)",
            # Disney funds $2,062M through commercial paper it classifies as
            # long-term; the element carries its own current portion
            ("LongtermCommercialPaperCurrentAndNoncurrent",), not_before=not_before,
        ))
        parts_target.append(_latest_instant_across(
            gaap, "LongTermDebt (transition bonds)",
            # utility securitisation bonds are borrowed money like any other
            ("LongTermTransitionBond",), not_before=not_before,
        ))
        parts_target.append(_latest_instant_across(
            gaap, "LongTermDebt (debtor-in-possession)",
            # borrowing arranged inside bankruptcy is still borrowing
            ("DebtorInPossessionFinancingBorrowingsOutstanding",), not_before=not_before,
        ))
        # notes/loans family: the parent rollups win over the pair (TEVA files
        # only the long-term combined variant, $16.8B)
        notes_group = _latest_instant_across(
            gaap, "LongTermDebt (notes and loans)",
            ("NotesAndLoansPayable", "LongTermNotesAndLoans"), not_before=not_before
        )
        if notes_group is None:
            notes_group = _sum_facts("LongTermDebt (notes and loans)", [
                _latest_instant_across(gaap, "LongTermDebt (notes payable)", ("NotesPayable",),
                                       not_before=not_before),
                _latest_instant_across(gaap, "LongTermDebt (loans payable)", ("LoansPayable",),
                                       not_before=not_before),
            ])
        instruments = [notes_group] if notes_group else []
        if notes_group is None:
            # convertibles hide inside the notes totals; a separate slot only
            # when no notes group fired (DDOG/SNOW: converts are the whole debt)
            instruments.append(_latest_instant_across(
                gaap, "LongTermDebt (convertible)",
                ("ConvertibleDebtNoncurrent", "ConvertibleLongTermNotesPayable",
                 "ConvertibleDebt", "ConvertibleNotesPayable"),
                not_before=not_before,
            ))
            instruments.append(_latest_instant_across(
                gaap, "LongTermDebt (loans)", ("LongTermLoansPayable", "OtherLoansPayable"),
                not_before=not_before
            ))
            # banks file this beside no instrument rollup at all; it sits INSIDE
            # unsecured borrowings, so it competes with the secured/unsecured
            # axis below rather than adding to it
            instruments.append(_latest_instant_across(
                gaap, "LongTermDebt (subordinated)", ("SubordinatedDebt",),
                not_before=not_before
            ))
            instruments.append(_latest_instant_across(
                gaap, "LongTermDebt (senior notes)", ("SeniorLongTermNotes", "SeniorNotes"),
                not_before=not_before
            ))
        instruments.append(_latest_instant_across(
            gaap, "LongTermDebt (credit line)", ("LongTermLineOfCredit", "LineOfCredit"),
            not_before=not_before,
        ))
        instruments = [f for f in instruments if f is not None]
        # Secured/unsecured is an AXIS over the same instruments, not another
        # instrument: the two sides are disjoint by definition, so their sum is
        # a second representation of the whole (GS reports $348B unsecured +
        # $11.6B secured and no instrument rollup at all). Take whichever
        # representation shows more, never both. A skip-if-present guard
        # misfires on fresh zeros (BRT) and fragments (AVA: 900x).
        axis = _sum_facts("LongTermDebt (secured + unsecured)", [
            _latest_instant_across(
                gaap, "LongTermDebt (secured)",
                # Welltower reports $2,814M under the "other" variant alone
                ("SecuredLongTermDebt", "SecuredDebt", "SecuredDebtOther"),
                not_before=not_before,
            ),
            _latest_instant_across(
                gaap, "LongTermDebt (unsecured)", ("UnsecuredLongTermDebt",),
                not_before=not_before,
            ),
        ])
        if axis is not None and axis.value > sum((f.value for f in instruments), Decimal(0)):
            parts_target.append(axis)
        else:
            parts_target.extend(instruments)

    # newer wins; at one date the larger of two representations of one quantity
    instruments_total = _sum_facts("LongTermDebt (instruments)",
                                   [f for f in instrument_parts if f is not None])
    chosen = _fresher_or_larger(primary, instruments_total)
    picked = _tag_of(chosen)
    parts = [chosen] if chosen else []
    parts.append(_latest_instant_across(
        gaap, "LongTermDebt (subordinated debentures)",
        ("JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent",
         "JuniorSubordinatedNotes"),
        not_before=not_before,
    ))
    if picked != "LongTermDebtAndCapitalLeaseObligations":
        parts.append(_latest_instant_across(
            gaap, "LongTermDebt (finance leases)",
            ("FinanceLeaseLiabilityNoncurrent", "FinanceLeaseLiability"),
            not_before=not_before,
        ))
    suppress: set[str] = set()
    for f in parts:
        if f is None:
            continue
        for tag in f.provenance.tag.split(" + "):  # summed facts carry every component tag
            suppress |= _COMBINED_SUPPRESSIONS.get(tag.split(":", 1)[1], frozenset())
    return _sum_facts("LongTermDebt", parts), frozenset(suppress)


def _short_term_debt(
    gaap: dict, not_before: date | None, suppress: frozenset[str] = frozenset()
) -> Fact | None:
    whole = _latest_instant_across(gaap, "ShortTermDebt", ("DebtCurrent",), not_before=not_before)
    if whole is not None:
        return whole  # DebtCurrent already rolls up the whole short bucket

    # Borrowings slot. ShortTermBankLoansAndNotesPayable TERMINATES the slot and
    # the notes-current family: KEY files it equal to OtherShortTermBorrowings,
    # so summing anything beside it doubles the figure.
    borrowings = _latest_instant_across(
        gaap, "ShortTermDebt (borrowings)",
        ("ShortTermBorrowings", "ShortTermBankLoansAndNotesPayable"),
        not_before=not_before,
    )
    bank_loans_won = _tag_of(borrowings) == "ShortTermBankLoansAndNotesPayable"
    if borrowings is None:
        # KO: commercial paper and other short-term borrowings are disjoint lines;
        # mortgage-warehouse lines are their own facility
        borrowings = _sum_facts("ShortTermDebt (borrowings)", [
            _latest_instant_across(gaap, "ShortTermDebt (commercial paper)",
                                   # S&P Global files only the carrying-amount variant
                                   # ($715M); Johnson & Johnson the long-term-CP current
                                   # portion ($2,000M)
                                   ("CommercialPaper", "CommercialPaperAtCarryingValue",
                                    "LongTermCommercialPaperCurrent"),
                                   not_before=not_before),
            _latest_instant_across(gaap, "ShortTermDebt (other borrowings)",
                                   ("OtherShortTermBorrowings",), not_before=not_before),
            _latest_instant_across(gaap, "ShortTermDebt (warehouse borrowings)",
                                   ("WarehouseAgreementBorrowings",), not_before=not_before),
            _latest_instant_across(gaap, "ShortTermDebt (bank and other loans)",
                                   ("LoansPayableToBankCurrent", "OtherLoansPayableCurrent"),
                                   not_before=not_before),
            _latest_instant_across(gaap, "ShortTermDebt (transition bonds)",
                                   ("LongtermTransitionBondCurrent",), not_before=not_before),
        ])

    ltd_current = None
    if "ltd_current" not in suppress:  # skipped when the long bucket already includes current maturities
        chain = ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                 "UnsecuredDebtCurrent"]
        if "notes_current" not in suppress and not bank_loans_won:
            chain.append("NotesPayableCurrent")
        chain.append("OtherLongTermDebtCurrent")  # strict component: chained, never summed (SMP/NTAP)
        if "secured_current" not in suppress:
            chain.append("SecuredDebtCurrent")
        ltd_current = _latest_instant_across(
            gaap, "ShortTermDebt (current portion of long-term)", tuple(chain),
            not_before=not_before,
        )
        # ED: NotesPayableCurrent 869M == CommercialPaper 869M, same period end —
        # the tag is often the commercial paper under another name; count once.
        if (ltd_current is not None and _tag_of(ltd_current) == "NotesPayableCurrent"
                and borrowings is not None
                and borrowings.provenance.period_end == ltd_current.provenance.period_end
                and borrowings.value == ltd_current.value):
            ltd_current = None

    # Current-side instrument families exist only when NO current rollup fired:
    # MELI's LoansPayableCurrent and SMP's LinesOfCreditCurrent are components
    # of the rollup and would double count beside it.
    family: list[Fact | None] = []
    if ltd_current is None and "ltd_current" not in suppress:
        parent = None
        if {"notes_current", "loans_current"}.isdisjoint(suppress) and not bank_loans_won:
            parent = _latest_instant_across(
                gaap, "ShortTermDebt (notes and loans, current)", ("NotesAndLoansPayableCurrent",),
                not_before=not_before,
            )
        if parent is not None:
            family.append(parent)
        else:
            if "loc_current" not in suppress:
                family.append(_latest_instant_across(
                    gaap, "ShortTermDebt (credit line, current)", ("LinesOfCreditCurrent",),
                    not_before=not_before))
            if "loans_current" not in suppress:
                family.append(_latest_instant_across(
                    gaap, "ShortTermDebt (loans, current)", ("LoansPayableCurrent",),
                    not_before=not_before))
            if "notes_current" not in suppress and not bank_loans_won:
                family.append(_latest_instant_across(
                    gaap, "ShortTermDebt (other notes, current)", ("OtherNotesPayableCurrent",),
                    not_before=not_before))
                if "senior_current" not in suppress:  # combined SeniorNotes already holds it
                    family.append(_latest_instant_across(
                        gaap, "ShortTermDebt (senior notes, current)", ("SeniorNotesCurrent",),
                        not_before=not_before))
        if "convertible_current" not in suppress:
            family.append(_latest_instant_across(
                gaap, "ShortTermDebt (convertible, current)",
                ("ConvertibleNotesPayableCurrent", "ConvertibleDebtCurrent"),
                not_before=not_before))

    leases = None
    if ("finance_lease_current" not in suppress
            and (ltd_current is None or "CapitalLeaseObligations" not in ltd_current.provenance.tag)):
        leases = _latest_instant(
            gaap, "ShortTermDebt (finance leases)", ("FinanceLeaseLiabilityCurrent",),
            not_before=not_before,
        )
    return _sum_facts("ShortTermDebt", [ltd_current, *family, borrowings, leases])


def _fresher_rollup(total: Fact | None, parts: Fact | None) -> Fact | None:
    """A total tag and the components that make it, where the two disagree on date.

    Newer wins; at one date the total wins, because a rollup is the whole and the
    components on file may be a fragment of it. The same rule criterion 3 applies
    to the debt rollup, for the same reason: a filer that moves to a new element
    leaves the old one in place, and reading the abandoned one gives a figure that
    was true once.

    Energy Transfer moved its redeemable minority interest from
    `RedeemableNoncontrollingInterestEquityCarryingAmount` to `...Other...` after
    2025-12-31. Taking the total first read $250M into a June balance sheet whose
    printed page says $256M, and the difference was deducted from common equity.
    """
    if total is None or parts is None:
        return total or parts
    if parts.provenance.period_end is None or total.provenance.period_end is None:
        return total
    return parts if parts.provenance.period_end > total.provenance.period_end else total


def _sum_facts(concept: str, parts: list[Fact | None]) -> Fact | None:
    """Sum component facts. Components may carry different (already staleness-guarded)
    period ends and are ALL included: dropping any part understates the total, and
    for both debt (criterion 3) and intangibles (criterion 7) overstating is the
    conservative direction. The combined tag string discloses what was summed.

    The 2026-08-21 audit proposed requiring one period end across the components,
    because Coca-Cola's short-term debt picks up an OtherShortTermBorrowings from a
    superseded quarter and lands 26M under the filing's own 4,825M. That was not
    adopted: restricting the sum to the newest date drops a real component whenever
    a filer reports its pieces at different frequencies, which understates by more
    than the mismatch costs, and understating debt is the anti-conservative
    direction. The provenance names every component and its date, so the mismatch
    is visible rather than hidden."""
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
            # components may carry different (individually fresh) period ends, so
            # the summary line's date belongs to one of them and not the rest
            components=tuple(p.provenance for p in parts),
        ),
    )


_DEBT_EVIDENCE_RE = re.compile(
    r"debt|borrowing|notespayable|loanspayable|debenture|commercialpaper"
    r"|financeleaseliability|lineofcredit|seniornotes|subordinatednotes"
    r"|mediumtermnotes|federalhomeloan|federalfundspurchased|bankoverdraft", re.I,
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


def _derive_liabilities(gaap: dict, not_before: date | None) -> tuple[Fact | None, bool]:
    """Many filers tag no Liabilities total. Derive it from the accounting identity
    L = LiabilitiesAndStockholdersEquity - total equity, same period end required.
    The boolean is True when the derivation used PARENT-ONLY equity, leaving
    noncontrolling interest inside the derived liabilities figure — the caller
    must then not subtract NCI a second time."""
    lse = _latest_instant(
        gaap, "LiabilitiesAndStockholdersEquity", ("LiabilitiesAndStockholdersEquity",),
        not_before=not_before,
    )
    if lse is None:
        return None, False
    for equity_tag, parent_only in (
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", False),
        ("StockholdersEquity", True),
        # partnerships have no stockholders equity at all (PAA's Liabilities tag
        # is stale since 2011); their capital accounts carry the same identity
        ("PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest", False),
        ("PartnersCapital", True),
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
            ), parent_only
    return None, False


def _instants_by_end(gaap: dict, tag: str, not_before: date | None) -> dict[str, dict]:
    """Freshness-filtered instant entries keyed by period end, latest-filed wins."""
    floor = not_before.isoformat() if not_before else ""
    out: dict[str, dict] = {}
    for e in _entries(gaap, tag, ("USD",)):
        if "start" in e or not _is_financial_form(e.get("form", "")) or e["end"] < floor:
            continue
        cur = out.get(e["end"])
        if cur is None or e["filed"] > cur["filed"]:
            out[e["end"]] = e
    return out


def _derived_instant(
    gaap: dict, concept: str, minuend: str, subtrahend: str,
    not_before: date | None, subtrahend_optional: bool = False,
) -> Fact | None:
    """minuend − subtrahend at their latest COMMON period end. Mixed period ends
    would subtract different balance sheets (BBY: gross-only overstates 96x), and
    a negative result marks a mistagged pair (CALM), never a value. With
    subtrahend_optional the bare minuend stands when the subtrahend was never
    tagged — overstating a deduction is the conservative direction."""
    a = _instants_by_end(gaap, minuend, not_before)
    if not a:
        return None
    b = _instants_by_end(gaap, subtrahend, not_before)
    if not b and subtrahend_optional:
        end = max(a)
        return _fact(f"{concept} — {subtrahend} never tagged", minuend, a[end])
    common = set(a) & set(b)
    if not common:
        return None
    end = max(common)
    value = _dec(a[end]["val"]) - _dec(b[end]["val"])
    if value < 0:
        return None
    base = a[end] if a[end]["filed"] >= b[end]["filed"] else b[end]
    return Fact(
        value=value,
        provenance=Provenance(
            concept=concept,
            tag=f"us-gaap:{minuend} - us-gaap:{subtrahend}",
            fiscal_year=None, form=base.get("form", ""), accession=base.get("accn", ""),
            filed=date.fromisoformat(base["filed"]), period_end=date.fromisoformat(end),
        ),
    )


_INDEFINITE_CLASS_TAGS = (
    "IndefiniteLivedTradeNames", "IndefiniteLivedTrademarks",
    "IndefiniteLivedLicenseAgreements", "OtherIndefiniteLivedIntangibleAssets",
)


def _intangibles(gaap: dict, not_before: date | None) -> Fact | None:
    """Total ex-goodwill tag when present; otherwise the larger of the
    finite+indefinite parts sum and the OtherIntangibleAssetsNet line (HBAN files
    both, and the Other line holds MSRs the parts miss — max never sums, so it
    cannot double count); then derivations; then sector last resorts."""
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
    if indefinite is None:
        # KO's trademarks and VZ's spectrum live only in class tags
        indefinite = _sum_facts("Intangibles (indefinite-lived classes)", [
            _latest_instant(gaap, f"Intangibles ({tag})", (tag,), not_before=not_before)
            for tag in _INDEFINITE_CLASS_TAGS
        ])
    summed = _sum_facts("Intangibles", [finite, indefinite])
    other = _latest_instant(
        gaap, "Intangibles (other, net)", ("OtherIntangibleAssetsNet",), not_before=not_before
    )
    if summed is not None and other is not None:
        return other if other.value > summed.value else summed
    if summed is not None or other is not None:
        return summed or other
    derived = _derived_instant(
        gaap, "Intangibles (derived: combined line - goodwill)",
        "IntangibleAssetsNetIncludingGoodwill", "Goodwill", not_before,
    )
    if derived is not None:
        return derived
    for minuend in ("IntangibleAssetsGrossExcludingGoodwill", "FiniteLivedIntangibleAssetsGross"):
        derived = _derived_instant(
            gaap, "Intangibles (derived: gross - accumulated amortization)",
            minuend, "FiniteLivedIntangibleAssetsAccumulatedAmortization",
            not_before, subtrahend_optional=True,
        )
        if derived is not None:
            return derived
    servicing = _sum_facts("Intangibles (mortgage servicing rights)", [
        # the two measurement books are disjoint under ASC 860-50; WFC carries both
        _latest_instant(gaap, "Intangibles (servicing, fair value)",
                        ("ServicingAssetAtFairValueAmount",), not_before=not_before),
        _latest_instant(gaap, "Intangibles (servicing, amortized)",
                        ("ServicingAssetAtAmortizedValue",), not_before=not_before),
    ]) or _latest_instant(
        gaap, "Intangibles (mortgage servicing rights)", ("ServicingAsset",), not_before=not_before
    )
    if servicing is not None:
        return servicing
    return _latest_instant(
        gaap, "Intangibles (capitalized software standing in for an untagged intangibles line)",
        ("CapitalizedComputerSoftwareNet",), not_before=not_before,
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
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeignAndDomestic",
)
# The domestic figure is one geography, not the consolidated company: standing
# alone it understates a multinational's profit, and with it the owner earnings
# and return on capital built on top. It serves only added to its foreign twin,
# and only where both cover the same year.
_PRETAX_GEOGRAPHY_TAGS = ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
                          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign")
# Rollup tags first: a filer that reports the combined figure rarely also splits it,
# and summing the parts when the rollup exists would double-count.
DA_TAGS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
)
DA_PART_TAGS = ("Depreciation", "AmortizationOfIntangibleAssets")
TAX_TAGS = ("IncomeTaxExpenseBenefit",)
# The deferred tax footnote answers two questions the income statement does not:
# how much of the tax charge was actually payable this year, and how much of the
# deductions the company has already earned it does not expect to use. Both are
# the company's own signed opinion of its future earning power.
DEFERRED_TAX_EXPENSE_TAGS = ("DeferredIncomeTaxExpenseBenefit",)
DEFERRED_TAX_ASSET_TAGS = ("DeferredTaxAssetsGross",)
# gross = net + allowance, so the net tag rebuilds the base when the gross one
# is stale or scoped to something narrower than the allowance covers
DEFERRED_TAX_ASSET_NET_TAGS = ("DeferredTaxAssetsNet",)
DEFERRED_TAX_ALLOWANCE_TAGS = ("DeferredTaxAssetsValuationAllowance",)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
    # last, so per-year fill only covers years the payments tags lack (SCHL's
    # payments tag died in FY2020); accrual-basis overstatement is conservative
    # for owner earnings and the provenance discloses the segment source
    "SegmentExpenditureAdditionToLongLivedAssets",
)
CASH_TAGS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
# Context only — never an adjustment, never a criterion. Reported earnings that
# do not arrive as cash, a share count quietly growing, and interest that eats
# operating profit are the three things a Graham reader wants flagged beside a
# passing multiple.
OPERATING_CASH_FLOW_TAGS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
INTEREST_EXPENSE_TAGS = (
    "InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense",
    "InterestExpenseNonoperating", "InterestIncomeExpenseNet",
)
# Where trouble accumulates quietly. None of these decides a criterion: a
# receivable growing faster than the sales it came from, inventory the customers
# did not take, and rent obligations that criterion 3 does not count as debt are
# all things a reader should see before trusting reported earnings.
RECEIVABLE_TAGS = ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
                   "AccountsReceivableNet")
# NVF bought a company seven times its size with debentures sold at 43 cents on
# the dollar, and Graham's objection was that neither the interest statement nor
# the share count told the truth afterwards: the coupon understated the cost of
# money, and warrants issued as currency diluted holders who could not see them.
# Both leave a trace a filing still has to make.
DEBT_DISCOUNT_TAGS = ("AmortizationOfDebtDiscountPremium",)
WARRANT_SHARE_TAGS = ("ClassOfWarrantOrRightNumberOfSecuritiesCalledByWarrantsOrRights",)
# Graham counts a convertible preferred as the common it becomes — table 18.6's
# share count for McGraw-Hill carries the footnote "including the conversion of
# preferred shares", and its book value per share is struck on that larger count.
# The reasoning is that the issue is small, the conversion arithmetic is easy, and
# at any favourable price those shares exist.
# Employee options still outstanding. Filers that grant only restricted stock —
# Apple, Microsoft and Nvidia among them — tag none of these, and that is a silence
# about options, not a zero: §5.1 applies here as everywhere.
OPTION_COUNT_TAGS = (
    "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber",
    "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsExercisableNumber",
)
# Restricted stock still to vest. A promise of shares rather than a right to buy
# them, so it dilutes whatever the price does — but the nonvested balance sits in a
# roll-forward table dimensioned by award type, which Company Facts drops and which
# Apple, Microsoft, Nvidia and Coca-Cola do not tag in the quarterly datasets either.
RSU_COUNT_TAGS = (
    "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber",
    "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsOutstandingNumber",
)
PREFERRED_COUNT_TAGS = ("PreferredStockSharesOutstanding", "PreferredStockSharesIssued")
_CONVERSION_OVERHANG = Decimal("0.05")  # same floor the warrant note uses
CONVERTIBLE_PREFERRED_SHARE_TAGS = (
    "ConvertiblePreferredStockSharesIssuedUponConversion",
    "PreferredStockConvertibleSharesIssuable",
    "ConvertiblePreferredStockSharesOutstanding",
)
INVENTORY_TAGS = ("InventoryNet",)
LEASE_OBLIGATION_TAGS = ("OperatingLeaseLiability",)
_DIVERGENCE = Decimal("1.30")   # this much faster than sales is worth saying
_DIVERGENCE_SPAN = 3            # years back to compare against
# The two post-ASU-2016-01 AFS successors and held-to-maturity go END of chain:
# PFE tags OtherShortTermInvestments as the total and the AFS tag as its
# footnote fragment. The dead pre-ASU AvailableForSaleSecuritiesCurrent is gone
# (zero fresh instants across the cache).
SHORT_TERM_INVESTMENT_TAGS = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "OtherShortTermInvestments",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent",
    "HeldToMaturitySecuritiesCurrent",
)


def _annual_union(gaap: dict, tags: tuple[str, ...],
                  unit: tuple[str, ...] = ("USD",)) -> dict[int, Fact]:
    """One annual series assembled from a chain of tags, earlier tags winning a year.

    Filers change tags mid-history and leave the abandoned one in place, so taking the
    first tag that has any data at all freezes the series at the year it was dropped.
    Filling year by year keeps the preferred tag where it exists and stays current.
    """
    out: dict[int, Fact] = {}
    for tag in tags:
        for year, fact in _annual_series(gaap, tag, unit=unit).items():
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
    # The fallback is per year, not per company: Johnson & Johnson stopped tagging an
    # operating subtotal after 2014 and kept reporting pre-tax income, so an
    # all-or-nothing substitution froze its return on capital at a twelve-year-old
    # year rather than continuing the series.
    if series := _annual_union(gaap, PRETAX_INCOME_TAGS):
        existing = flows.get("operating profit", {})
        filled = [y for y in series if y not in existing]
        if filled:
            flows["operating profit"] = {**series, **existing}
            caveats.append(
                "no operating subtotal is reported for FY"
                + ", FY".join(str(y) for y in sorted(filled)[-3:])
                + ", so pre-tax income stands in for operating profit there and carries "
                  "non-operating items with it")
    if "operating profit" not in flows and (series := _geographic_pretax(gaap)):
        flows["operating profit"] = series
        caveats.append("no operating subtotal or consolidated pre-tax total is reported, so "
                       "pre-tax income is the sum of the domestic and foreign figures for the "
                       "same year, and carries non-operating items with it")

    da = _annual_union(gaap, DA_TAGS)
    parts = [s for tag in DA_PART_TAGS if (s := _annual_series(gaap, tag, unit=("USD",)))]
    if parts:
        # A filer that drops the combined tag mid-history keeps reporting the pieces;
        # taking the rollup wherever it exists and the sum elsewhere keeps the series
        # current instead of freezing it at the year the tag changed. Every year with
        # ANY part counts, and a summed year's provenance names every summed tag.
        summed = {}
        for y in {y for p in parts for y in p}:
            present = [p[y] for p in parts if y in p]
            summed[y] = present[0] if len(present) == 1 else _sum_facts(
                "DepreciationAndAmortization (sum of parts)", present)
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
    # A return divides a year's flows by the capital that produced them. Johnson &
    # Johnson stopped tagging an operating subtotal after 2014, and its FY2014 flows
    # were being divided by a 2026 balance sheet and shown as today's ROIC, green
    # highlight and all. Twelve years apart is not a return on anything.
    newest_end = max((flows[k][fy].provenance.period_end for k in required
                      if flows[k][fy].provenance.period_end), default=None)
    if (fresh is not None and newest_end is not None
            and (fresh - newest_end).days > _OWNER_EARNINGS_LAG):
        return None

    op, dep = flows["operating profit"][fy].value, flows["depreciation & amortisation"][fy].value
    tax, capex = flows["tax"][fy].value, flows["capital expenditure"][fy].value
    # Capex is a positive cash outflow in every tag we chain. Tax is NOT:
    # IncomeTaxExpenseBenefit is signed, and a company with a net benefit files it
    # negative. Forcing it positive charged Uber for a $4.3bn benefit it received,
    # moving owner earnings the wrong way by twice the amount and reporting 3.36%
    # where the truth is 21.59%. Subtracting the signed value adds a benefit back.
    capex = abs(capex)
    # InspireMD tags $476M of depreciation against $44.6M of total assets. A single
    # year's flow cannot exceed everything the company owns; where it does, the
    # element is holding something other than the flow it names.
    scale = snap_parts.get("total_assets")
    if scale is not None and scale.value > 0:
        if any(abs(v) > scale.value for v in (op, dep, tax, capex)):
            return None
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
    # When the cash rollup includes restricted cash, net out exactly ONE
    # restricted representation at the SAME period end — restricted cash is not
    # deployable capital (AAL), but a mismatched period would net a different
    # balance sheet. Never against the plain carrying-value tag.
    if cash is not None and _tag_of(cash) == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents":
        restricted = _restricted_cash(gaap, fresh, cash.provenance.period_end)
        if restricted is not None and Decimal(0) < restricted.value <= cash.value:
            cash = Fact(value=cash.value - restricted.value, provenance=Provenance(
                concept="Cash (restricted portion netted out)",
                tag=f"{cash.provenance.tag} - {restricted.provenance.tag}",
                fiscal_year=None, form=cash.provenance.form,
                accession=cash.provenance.accession, filed=cash.provenance.filed,
                period_end=cash.provenance.period_end,
            ))
            caveats.append("the cash rollup includes restricted cash; the restricted portion "
                           "was netted out of invested capital at the same period end")
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
        # ...and one that is a material share of the assets employed. A denominator
        # of a few thousand dollars against millions of flow prints returns in the
        # thousands of per cent: 75 rows shipped |ROIC| over 1,000%.
        if invested > 0 and invested >= assets.value * _INVESTED_CAPITAL_FLOOR:
            roic = owner / invested * 100
            roic_maint = (op - tax) / invested * 100  # maintenance capex assumed equal to D&A
        else:
            invested = None
            caveats.append("invested capital is too small a part of the assets employed for a "
                           "return on it to mean anything")
    else:
        caveats.append("no classified balance sheet, so invested capital cannot be separated")

    return OwnerEarnings(fiscal_year=fy, owner_earnings=owner, invested_capital=invested,
                         roic=roic, roic_maintenance=roic_maint, components=components,
                         caveats=tuple(caveats))


_DERIVED_EPS_SHARE_LAG = 460  # a cover count this close to the year end counts that year


_BASIS_TOLERANCE = Decimal("1.5")   # how far EPS x shares may sit from the filer's own income


def _restate_onto_receipt(snapshot_parts: dict, ratio: Decimal, accn: str) -> None:
    """Put every per-share figure onto the security the price belongs to.

    A depositary receipt stands for a fixed number of ordinary shares, and a
    filer's statements count the ordinary ones. The price does not: it is quoted
    per receipt. So earnings per receipt are the ordinary figure times the ratio,
    and the receipt count is the ordinary count divided by it — one transformation,
    applied to both sides, leaving every multiple on the page comparing like with
    like. Onconova's thirteen ordinary shares per receipt made its market
    capitalisation $550bn instead of $42bn.

    The ratio is transcribed from the cover of a named filing, so it carries an
    accession like any other figure here.
    """
    def restated(fact: Fact, factor: Decimal, what: str) -> Fact:
        p = fact.provenance
        return Fact(value=fact.value * factor, provenance=Provenance(
            concept=f"{p.concept} (per depositary receipt: {what})", tag=p.tag,
            fiscal_year=p.fiscal_year, form=p.form, accession=p.accession, filed=p.filed,
            period_end=p.period_end, period_start=p.period_start, components=p.components))

    per_receipt = f"x{ratio} ordinary shares, cover of {accn}"
    shares = snapshot_parts.get("shares")
    if shares is not None:
        snapshot_parts["shares"] = restated(shares, 1 / ratio, per_receipt)
    for key in ("annual_eps",):
        snapshot_parts[key] = {y: restated(f, ratio, per_receipt)
                               for y, f in (snapshot_parts.get(key) or {}).items()}
    for key in ("ttm_eps", "dividend_per_share", "ttm_preferred_dividends"):
        value = snapshot_parts.get(key)
        if value is not None:
            snapshot_parts[key] = value * ratio if key != "shares" else value


def _basis_conflict(gaap: dict, dei: dict, annual_eps: dict[int, Fact],
                    annual_ni: dict[int, Fact], preferred: dict[int, Fact],
                    has_nci: bool, shares: Fact | None = None) -> str | None:
    """Whether the earnings series and the share count describe the same security.

    A filer's own earnings per share times its own weighted share count is its own
    net income. Where the two disagree by half again, one of them belongs to
    something else — a depositary share standing for thirteen ordinary ones, a
    class the ticker does not represent, a count struck for a different entity —
    and every per-share figure built on the pair is wrong by that factor. SM Energy
    ships a P/E of 4.03 where its own filing gives 13.25.

    The weighted count is used, not today's, so an issue after the year end cannot
    masquerade as a mismatch. Minority interests, preferred dividends and a
    continuing-operations basis are legitimate wedges, so the check abstains there.

    One family stays out of reach: a depositary receipt whose statements count
    ordinary shares reconciles with its own earnings perfectly, and only the ratio
    on the filing cover — which Company Facts does not carry — says that the price
    belongs to a bundle of thirteen of them. Comparing the cover count against the
    statements does not separate that case from a second share class (Heico's cover
    states one class of two), so it is not attempted here.
    """
    if has_nci:
        return None
    counts = _annual_share_counts(gaap, dei)
    for year in sorted(set(annual_eps) & set(annual_ni) & set(counts), reverse=True):
        eps, ni, count = annual_eps[year], annual_ni[year], counts[year]
        if eps.value == 0 or count.value <= 0 or year in preferred:
            continue
        if "ContinuingOperations" in eps.provenance.tag:
            continue
        stated = eps.value * count.value
        if stated == 0 or ni.value == 0:
            continue
        ratio = ni.value / stated
        if ratio > _BASIS_TOLERANCE or ratio < 1 / _BASIS_TOLERANCE:
            return (f"FY{year} earnings per share of {eps.value} on {count.value / _MILLION:,.1f}M "
                    f"weighted shares comes to {stated / _MILLION:,.0f}M against the "
                    f"{ni.value / _MILLION:,.0f}M of net income the same filing reports: the "
                    "two do not describe one security")
        # The series can reconcile with its own year and still not describe the
        # security being priced: SM Energy's earnings are struck on 115.0M weighted
        # shares while the count every per-share figure divides by is 237.5M. A
        # price against that pair mixes two bases, whichever of them is right.
        if shares is not None and shares.value > 0:
            drift = shares.value / count.value
            if drift > _BASIS_TOLERANCE or drift < 1 / _BASIS_TOLERANCE:
                return (f"FY{year} earnings are struck on {count.value / _MILLION:,.1f}M "
                        f"weighted shares while the current count is "
                        f"{shares.value / _MILLION:,.1f}M, {drift:.2f}x apart: a per-share "
                        "figure cannot mix the two")
        return None
    return None


def _has_minority_interest(gaap: dict, fresh: date | None, nci: Fact | None) -> bool:
    """Whether minority holders own part of this balance sheet. The NCI tag is
    not the only evidence: Ares tags no MinorityInterest at all, yet its equity
    including noncontrolling interests is more than twice its parent equity."""
    if nci is not None and nci.value != 0:
        return True
    # A partnership files neither StockholdersEquity element. Westlake Chemical
    # Partners consolidates an OpCo two thirds owned by its sponsor and shows it
    # as PartnersCapital 253.7M inside 769.4M including the minority — a 3.03x
    # signal invisible to the corporate pair, which is why its whole group profit
    # was being divided by its own unit count.
    for incl, parent_tag in (
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
         "StockholdersEquity"),
        ("PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest",
         "PartnersCapital"),
    ):
        both = _latest_instant(gaap, "Equity (incl. NCI)", (incl,), not_before=fresh)
        parent = _latest_instant(gaap, "Equity (parent)", (parent_tag,), not_before=fresh)
        if both is None or parent is None or both.value == 0:
            continue
        if abs(both.value - parent.value) / abs(both.value) > Decimal("0.02"):
            return True
    return False


def _annual_share_counts(gaap: dict, dei: dict) -> dict[int, Fact]:
    """The share count a filer itself divided by for a given year.

    Only the weighted average serves. The count on a report cover looked like a
    reasonable stand-in and is not: measured against the figures companies
    actually report, it produced errors of exactly five, ten and a hundred and
    fifty times — a reverse split leaves today's small count against an old
    year's income, and a multi-class filer's cover names one class while the
    income belongs to all of them. Both failures are silent and both read as a
    bargain, so the stand-in is gone: a year without its own weighted average
    keeps no derived figure.
    """
    return _annual_union(gaap, _WEIGHTED_SHARE_TAGS, unit=("shares",))


def _derived_annual_eps(gaap: dict, dei: dict, annual_eps: dict[int, Fact],
                        annual_ni: dict[int, Fact], annual_preferred: dict[int, Fact],
                        has_nci: bool = False) -> dict[int, Fact]:
    """Per-share earnings for years the filer reported income but tagged no
    per-share element: (net income - preferred dividends) / that year's share
    count. Both figures are the company's own and belong to the same year; the
    provenance names both tags so no reader mistakes it for a reported EPS.

    ProfitLoss includes noncontrolling interests, which are not the common
    shareholder's earnings — dividing it by the common share count inflates EPS
    and makes the price look cheap. It serves only where the balance sheet shows
    no minority interest to inflate it (ARES would have read 2.60 against a
    genuine 3.00-odd; a co-op with no NCI is unaffected)."""
    counts = _annual_share_counts(gaap, dei)
    # Where the group figure would be divided by the parent's own count, the
    # parent-attributable series takes its place — refusing the year outright
    # would leave a partnership with no per-unit figure at all when its own
    # income statement carries one.
    parent_ni = _annual_dollar_series(gaap, PARENT_INCOME_TAGS) if has_nci else {}
    out: dict[int, Fact] = {}
    for year, income in annual_ni.items():
        if year in annual_eps:
            continue
        if has_nci and income.provenance.tag.endswith(":ProfitLoss"):
            income = parent_ni.get(year)
            if income is None:
                continue
        count = counts.get(year)
        if count is None or count.value <= 0:
            continue
        end = income.provenance.period_end
        share_end = count.provenance.period_end
        if end and share_end and (share_end - end).days > _DERIVED_EPS_SHARE_LAG:
            continue  # a count struck long after the year describes a different company
        preferred = annual_preferred.get(year)
        common = income.value - (preferred.value if preferred else Decimal(0))
        p, q = income.provenance, count.provenance
        out[year] = Fact(
            value=common / count.value,
            provenance=Provenance(
                concept="EarningsPerShare (derived: earnings available to common / share count)",
                tag=f"{p.tag} / {q.tag}",
                fiscal_year=year, form=p.form, accession=p.accession,
                filed=p.filed, period_end=p.period_end, period_start=p.period_start,
            ),
        )
    return out


_UNTAXED_SHARE = Decimal("0.01")  # tax this small against a profit is no tax at all


def _tax_record(gaap: dict, fresh: date | None) -> dict | None:
    """Profitable years, and how many of them carried effectively no income tax.

    Penn Central reported profits and paid no income tax for eleven years before
    it failed; Graham's reading was that the tax authorities did not believe the
    earnings and neither should the investor. The counting happens here, on the
    facts. Whether it is a warning or merely a pass-through structure doing what
    pass-through structures do is decided where the company's profile is known.
    """
    tax = _annual_union(gaap, TAX_TAGS)
    pretax = _annual_union(gaap, PRETAX_TAGS) or _annual_union(gaap, PRETAX_INCOME_TAGS)
    shared = sorted(set(tax) & set(pretax), reverse=True)[:10]
    if len(shared) < 5:
        return None
    profitable = [y for y in shared if pretax[y].value > 0]
    untaxed = [y for y in profitable if tax[y].value <= abs(pretax[y].value) * _UNTAXED_SHARE]
    return {
        "window_from": min(shared), "window_to": max(shared),
        "profitable_years": len(profitable), "untaxed_years": len(untaxed),
        # a partnership or an investment company owes no entity-level tax by
        # design, and neither does a REIT — but only the first two are legible
        # from the facts themselves
        "pass_through": _is_partnership(gaap, fresh) or bool(
            _annual_union(gaap, ("InvestmentCompanyInvestmentIncomeLossFromOperationsPerShare",
                                 "InvestmentIncomeOperatingAfterExpenseAndTax"))),
    }


# A dimension answers "which slice of the company", and most slices are not the
# company: a segment, a geography, a parent-only view. Only the share-class axis
# names a security a ticker can be, so only it can supply a company's figure.
_CLASS_AXES = frozenset(("ClassOfStock", "StatementClassOfStock", "EquityClassOfStock"))


def _class_member(title: str) -> frozenset[str]:
    """The words that identify a share class, from either side of the question.

    A cover page says "Common Stock, one dollar par value" and a dimension member
    says "CommonStock"; a cover says "Class A Common Stock" and the member says
    "CommonClassA". Reduced to word sets the two are comparable, and the par value
    and other decoration fall away.
    """
    words = re.findall(r"[A-Z]?[a-z]+", re.sub(r"[^A-Za-z ]", " ", title))
    return frozenset(w.lower() for w in words if w.lower() not in
                     {"stock", "shares", "share", "par", "value", "per", "the", "of", "and",
                      "one", "dollar", "no", "common"}) or frozenset({"common"})


def _dimensioned_class(dimensioned: dict, registered: str | None) -> str | None:
    """Which dimension member is the class the ticker registers, when it can be told.

    Hershey reports earnings per share for its Common Stock and its Class B
    together; Company Facts drops both because they are dimensioned, and the
    ambiguity rule below then refuses both because there are two. The cover of its
    own 10-Q names which one the symbol is — "Common Stock, one dollar par value" —
    and that is the missing half. Where the cover says nothing or the match is not
    unique, the refusal stands: a wrong class is worse than no class.
    """
    if not registered:
        return None
    want = _class_member(registered)
    members = {p.split("=", 1)[1]
               for data in (dimensioned.get("facts", {}).get("us-gaap", {}) or {}).values()
               for entries in (data.get("units") or {}).values()
               for e in entries
               for p in (e.get("segments") or "").split(";")
               if p and p.split("=", 1)[0] in _CLASS_AXES}
    matched = [m for m in members if _class_member(m) == want]
    return matched[0] if len(matched) == 1 else None


def _unambiguous_dimensioned(dimensioned: dict | None, registered: str | None = None) -> dict:
    """The dimensioned facts that can only mean one thing, shaped like the facts
    Company Facts returns so the ordinary chains can read them.

    Two conditions. The dimension must be a share class alone — a fact carrying a
    segment or a geography describes part of a business, and a fact carrying two
    axes at once describes a corner of it. And the class must be identifiable: one
    class reported for that concept and period, or several of which the filing's
    own cover page names the one this ticker registers.
    """
    if not dimensioned:
        return {}
    chosen = _dimensioned_class(dimensioned, registered)
    out: dict[str, dict] = {}
    for tag, data in (dimensioned.get("facts", {}).get("us-gaap", {}) or {}).items():
        for unit, entries in (data.get("units") or {}).items():
            by_period: dict[tuple, list[dict]] = {}
            for e in entries:
                segments = e.get("segments") or ""
                pairs = [p for p in segments.split(";") if p]
                if len(pairs) != 1 or pairs[0].split("=", 1)[0] not in _CLASS_AXES:
                    continue
                by_period.setdefault((e.get("start"), e.get("end")), []).append(e)
            keep = [e for group in by_period.values()
                    if len({g["segments"] for g in group}) == 1
                    for e in group]
            if not keep and chosen:
                # several classes, and the cover says which one the ticker is
                keep = [e for group in by_period.values() for e in group
                        if e["segments"].split("=", 1)[-1].rstrip(";") == chosen]
            if keep:
                out.setdefault(tag, {"units": {}})["units"][unit] = keep
    return out


def _preferred_outstanding(dimensioned: dict | None, fresh: date | None) -> Decimal | None:
    """How much preferred is still on the books, counting every class at once.

    A different question from `_unambiguous_dimensioned`, which picks the one class
    a ticker registers. Here the classes are summed rather than chosen: what
    settles whether a tagged conversion is still ahead of the company is simply
    whether ANY convertible preferred remains, so an ambiguous split across three
    series is not ambiguity at all. Zero is a real answer here and means the
    conversion has already happened — the shares it created are inside the common
    count, and adding them again would count them twice.
    """
    if not dimensioned:
        return None
    floor = fresh.isoformat() if fresh else ""
    facts = dimensioned.get("facts", {}).get("us-gaap", {}) or {}
    for tag in PREFERRED_COUNT_TAGS:
        entries = [e for e in ((facts.get(tag) or {}).get("units", {}) or {}).get("shares", [])
                   if "start" not in e and e.get("end", "") >= floor
                   and _is_financial_form(e.get("form", ""))]
        if not entries:
            continue
        newest = max(e["end"] for e in entries)
        latest = [e for e in entries if e["end"] == newest]
        # one filing's view of that date, the latest-filed, so a restatement does
        # not get added to the figure it replaced
        filed = max(e.get("filed", "") for e in latest)
        latest = [e for e in latest if e.get("filed", "") == filed]
        by_class: dict[str, Decimal] = {}
        for e in latest:
            by_class[e.get("segments") or ""] = _dec(e["val"])
        if "" in by_class and len(by_class) > 1:
            by_class.pop("")          # a total beside its own parts would double
        return sum(by_class.values(), Decimal(0))
    return None


def _as_converted_note(gaap: dict, shares: Fact | None, fresh: date | None,
                       dimensioned: dict | None = None) -> str | None:
    """What a convertible preferred would do to the share count, said rather than done.

    Graham's table 18.6 counts McGraw-Hill's shares "including the conversion of
    preferred" and strikes book value on that larger number, and the arithmetic is
    plainly right when you are reading the filing: the preferred converts, the
    common grows, the senior claim disappears. The elements that would let a
    machine do it cannot carry the same meaning, because three different facts are
    tagged with the same name:

      * a conversion that has ALREADY happened, its shares inside the common count
        (Structure Therapeutics tags 67.0M against 2023-02-07, the day its
        preferred became common at the IPO);
      * a ceiling on preferred that no longer exists (Aqua Power tags 500M,
        Ilustrato 31.98bn, both against nothing outstanding);
      * a live conversion right of preferred still on the books, which is the only
        one Graham means (XWELL, 66.7M issuable against 31,333 preferred shares).

    The preferred count separates them, and it is filed on a share-class axis that
    Company Facts drops — but the quarterly DERA datasets keep the axis, so for the
    filers those cover the first case can be recognised and dropped rather than
    shown as a warning about nothing. What is still not deducible is the second
    against the third: whether a tagged figure is the total common the preferred
    becomes or a ceiling nobody will reach. So the count is never touched; the
    note reports what is outstanding and names the document that settles the rest.
    """
    if shares is None or shares.value <= 0:
        return None
    converted = _latest_instant(gaap, "ConvertiblePreferredShares",
                                CONVERTIBLE_PREFERRED_SHARE_TAGS,
                                unit=("shares",), not_before=fresh)
    if converted is None or converted.value <= 0:
        return None
    if converted.value / shares.value < _CONVERSION_OVERHANG:
        return None
    outstanding = _preferred_outstanding(dimensioned, fresh)
    if outstanding is not None and outstanding == 0:
        # the conversion is history: those shares are in the common count already
        return None
    standing = (f"{outstanding:,.0f} preferred shares are still outstanding, so the "
                "conversion is ahead of the company rather than behind it, but the tag "
                "does not say whether that figure is the common they become or a "
                "ceiling nobody reaches. "
                if outstanding else
                "The tag is used for conversions already done as well as for conversions "
                "still to come, and no preferred count is on file to tell them apart. ")
    return (
        f"A convertible preferred is tagged at {converted.value / _MILLION:,.1f}M shares "
        f"against {shares.value / _MILLION:,.1f}M common, "
        f"{converted.value / shares.value * 100:,.0f}% more. Graham counts shares "
        "\"including the conversion of preferred\" and strikes book value per share on "
        f"that larger number. {standing}Every per-share figure here is therefore struck "
        "on the common as it stands. Read the capitalisation note in the "
        f"{converted.provenance.form} ({converted.provenance.accession})."
    )


def _equity_for_scale(gaap: dict, equity: Decimal | None) -> Decimal | None:
    """Common equity, only as a yardstick for whether an obligation is large."""
    return equity if equity and equity > 0 else None


def _note(kind: str, text: str) -> dict:
    """A disclosure note and what kind of thing it is. The kind is decided where
    the evidence is, not guessed from the prose by whatever displays it."""
    return {"kind": kind, "text": text}


def annual_ratios(gaap: dict, annual_ni: dict[int, Fact], annual_revenue: dict[int, Fact],
                  annual_operating: dict[int, Fact], years: int = 6) -> dict[int, dict]:
    """Graham's comparison ratios as they stood at each fiscal year end.

    Chapter 13 compares companies by putting the same handful of ratios side by
    side; a single current column says how a business looks today and nothing about
    how it got there. Every figure here comes from the annual report of its own
    year — the balance sheet that year closed on, divided into the earnings that
    year produced — so no ratio mixes a period with a balance sheet from another.

    The per-share book figures are carried rather than the price multiples: a
    multiple needs the price of that year, which lives in the price history at
    export time, not in the filings.
    """
    ca = _annual_balances(gaap, ("AssetsCurrent",))
    cl = _annual_balances(gaap, ("LiabilitiesCurrent",))
    assets = _annual_balances(gaap, ("Assets", "LiabilitiesAndStockholdersEquity"))
    liabilities = _annual_balances(gaap, ("Liabilities",))
    minority = _annual_balances(gaap, ("MinorityInterest",))
    parent_equity = _annual_balances(gaap, ("StockholdersEquity",))
    group_equity = _annual_balances(
        gaap, ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",))
    preferred = _annual_balances(gaap, ("PreferredStockLiquidationPreferenceValue",
                                        "PreferredStockValue", "PreferredStockValueOutstanding"))
    goodwill = _annual_balances(gaap, ("Goodwill",))
    intangibles = _annual_balances(gaap, ("IntangibleAssetsNetExcludingGoodwill",))
    counts = _annual_share_counts(gaap, {})
    options = _annual_balances(gaap, OPTION_COUNT_TAGS, unit=("shares",))
    rsus = _annual_balances(gaap, RSU_COUNT_TAGS, unit=("shares",))
    ends = fiscal_year_ends(gaap)

    def at(series, year):
        f = series.get(year)
        return f.value if f is not None else None

    out: dict[int, dict] = {}
    for year in sorted(set(annual_ni) | set(ca) | set(assets))[-years:]:
        row: dict[str, float] = {}
        ca_v, cl_v = at(ca, year), at(cl, year)
        if ca_v is not None and cl_v:
            row["current_ratio"] = float(ca_v / cl_v)
        ni, rev = at(annual_ni, year), at(annual_revenue, year)
        if ni is not None and rev and rev > 0:
            row["net_margin"] = float(ni / rev * 100)
        op = at(annual_operating, year)
        if op is not None and rev and rev > 0:
            row["operating_margin"] = float(op / rev * 100)
        # The common's own capital that year. The filer's own equity line is the
        # direct reading — Coca-Cola tags no Liabilities total at all, so the
        # subtraction below cannot run for it — and minority holders and preferred
        # are removed either way, the same deduction every per-share figure makes.
        a_v, l_v = at(assets, year), at(liabilities, year)
        equity = at(parent_equity, year)
        if equity is None and (incl := at(group_equity, year)) is not None:
            equity = incl - (at(minority, year) or 0)
        if equity is None and a_v is not None and l_v is not None:
            equity = a_v - l_v - (at(minority, year) or 0)
        if equity is not None:
            equity -= at(preferred, year) or 0
        if equity is not None:
            if equity > 0 and ni is not None:
                row["return_on_book"] = float(ni / equity * 100)
        shares = at(counts, year)
        if shares and shares > 0:
            # see the guard in build_snapshot: an award count above the whole share
            # count is a mis-tag, and each kind is judged on its own before summing
            awards = [v for v in (at(options, year), at(rsus, year))
                      if v is not None and 0 <= v <= shares]
            if awards:
                row["award_pct"] = float(sum(awards) / shares * 100)
            if equity is not None:
                row["bvps"] = float(equity / shares)
                tangible = equity - (at(goodwill, year) or 0) - (at(intangibles, year) or 0)
                row["tbvps"] = float(tangible / shares)
            if ca_v is not None and l_v is not None:
                row["ncavps"] = float((ca_v - l_v - (at(preferred, year) or 0)
                                       - (at(minority, year) or 0)) / shares)
        if row:
            out[year] = {k: round(v, 4) for k, v in row.items()}
            # the date this year's figures were struck at, so export prices them
            # against the market of that day rather than of the following December
            if year in ends:
                out[year]["end"] = ends[year]
    return out


def _annual_balances(gaap: dict, tags: tuple[str, ...],
                     unit: tuple[str, ...] = ("USD",)) -> dict[int, Fact]:
    """A balance-sheet line at each fiscal year end, from the annual reports.

    Balance figures appear in every quarterly filing too; only the ones a 10-K
    states are comparable year to year, which is what a trend needs."""
    for tag in tags:
        out: dict[int, Fact] = {}
        for e in _entries(gaap, tag, unit):
            if "start" in e or not e.get("form", "").startswith(ANNUAL_FORMS):
                continue
            year = _fy_label(date.fromisoformat(e["end"]))
            kept = out.get(year)
            if kept is None or e["filed"] > kept.provenance.filed.isoformat():
                out[year] = _fact(tag, tag, e)
        if out:
            return out
    return {}


def _divergence_note(gaap: dict, tags: tuple[str, ...], annual_revenue: dict[int, Fact],
                     label: str, meaning: str) -> str | None:
    """Whether a balance has grown faster than the sales behind it.

    Receivables and inventory are where an income statement and reality part
    company: revenue booked but not collected, and goods made but not sold, both
    look like growth until the write-down arrives."""
    balances = _annual_balances(gaap, tags)
    years = sorted(set(balances) & set(annual_revenue))
    if len(years) < _DIVERGENCE_SPAN + 1:
        return None
    latest, base = years[-1], years[-1 - _DIVERGENCE_SPAN]
    if base not in years:
        return None
    now_sales, then_sales = annual_revenue[latest].value, annual_revenue[base].value
    now, then = balances[latest].value, balances[base].value
    if then <= 0 or then_sales <= 0 or now_sales <= 0:
        return None
    now_ratio, then_ratio = now / now_sales, then / then_sales
    if then_ratio <= 0 or now_ratio / then_ratio < _DIVERGENCE:
        return None
    return (f"{label} grew {(now / then - 1) * 100:.0f}% between FY{base} and FY{latest} "
            f"while sales grew {(now_sales / then_sales - 1) * 100:.0f}%, so it now stands at "
            f"{now_ratio * 100:.0f}% of sales against {then_ratio * 100:.0f}% then. {meaning}")


def _common_equity(assets, liabilities, preferred, nci, temporary) -> Decimal | None:
    """What the common shareholders own, for scale only."""
    if assets is None or liabilities is None:
        return None
    other = sum(f.value for f in (preferred, nci, temporary) if f is not None)
    return assets.value - liabilities.value - other


def _newest_period_end(facts) -> date:
    return max((f.provenance.period_end for f in facts if f.provenance.period_end),
               default=date.min)


def _geographic_pretax(gaap: dict) -> dict[int, Fact]:
    """Consolidated pre-tax income rebuilt from its two geographies, for the year
    both cover. Either half alone describes part of a company; only the pair
    describes the whole, so a year missing one of them stays missing."""
    domestic, foreign = (_annual_series(gaap, tag, unit=("USD",))
                         for tag in _PRETAX_GEOGRAPHY_TAGS)
    out: dict[int, Fact] = {}
    for year in set(domestic) & set(foreign):
        pair = [domestic[year], foreign[year]]
        if len({f.provenance.period_end for f in pair}) != 1:
            continue
        summed = _sum_facts("PretaxIncome (domestic + foreign)", pair)
        if summed is not None:
            out[year] = summed
    return out


_ALLOWANCE_SHARE = Decimal("0.50")     # this much of the deferred assets reserved is worth saying
_ALLOWANCE_MATERIAL = Decimal("0.10")  # ...and only when the assets matter to the company
_DEFERRED_SHARE = Decimal("0.80")      # a tax charge this deferred was not paid
_DEFERRED_MATERIAL = Decimal("0.10")   # deferred amount against the year's earnings


def _deferred_tax_assets(gaap: dict, fresh: date | None) -> tuple[Fact, Decimal] | None:
    """The valuation allowance and the deferred tax assets it stands against,
    both struck at one balance-sheet date.

    The gross tag is the direct reading, but a filer can leave it stale (Biogen's
    is four years older than its allowance) or scope it to something narrower
    than the allowance covers (Valaris reserves 3,292M against a "gross" 1,368M).
    One rule catches both: an allowance cannot exceed the assets it reserves
    against, so a pair that says otherwise is not a pair. The net tag then
    rebuilds the base from the same filing through gross = net + allowance.
    """
    allowance = _latest_instant(gaap, "DeferredTaxAssetsValuationAllowance",
                                DEFERRED_TAX_ALLOWANCE_TAGS, not_before=fresh)
    # a filer tagging the allowance as a negative contra amount is on a different
    # sign convention, and the identity below would silently invert
    if allowance is None or allowance.value <= 0:
        return None
    for concept, tags, derived in (
        ("DeferredTaxAssetsGross", DEFERRED_TAX_ASSET_TAGS, False),
        ("DeferredTaxAssetsGross (derived: net + allowance)", DEFERRED_TAX_ASSET_NET_TAGS, True),
    ):
        base = _latest_instant(gaap, concept, tags, not_before=fresh)
        if base is None or base.provenance.period_end != allowance.provenance.period_end:
            continue
        gross = base.value + allowance.value if derived else base.value
        if gross >= allowance.value:
            return allowance, gross
    return None


def _context_notes(gaap: dict, annual_eps: dict[int, Fact],
                   annual_ni: dict[int, Fact], annual_op: dict[int, Fact],
                   annual_revenue: dict[int, Fact] | None = None,
                   long_term_debt: Fact | None = None,
                   shares: Fact | None = None,
                   fresh_equity: Decimal | None = None,
                   fresh: date | None = None,
                   dimensioned: dict | None = None) -> tuple[str, ...]:
    """Three standing questions a passing multiple cannot answer by itself.

    Disclosure only: nothing here enters a criterion, a grade or an adjustment —
    a company can be cheap on every Graham test and still be worth a second look
    because its earnings never became cash, its share count keeps climbing, or
    its interest bill is most of its operating profit.
    """
    notes: list[str] = []
    ocf = _annual_union(gaap, OPERATING_CASH_FLOW_TAGS)
    shared = sorted(set(ocf) & set(annual_ni), reverse=True)[:3]
    if shared:
        cash = sum(ocf[y].value for y in shared)
        income = sum(annual_ni[y].value for y in shared)
        if income > 0:
            ratio = cash / income
            if ratio < Decimal("0.8"):
                notes.append(_note("Cash conversion",
                    f"Over FY{min(shared)}–FY{max(shared)} the business turned "
                    f"{ratio * 100:.0f}% of reported net income into operating cash "
                    f"({cash / _MILLION:,.0f}M against {income / _MILLION:,.0f}M). "
                    "Earnings that do not arrive as cash still count in every "
                    "multiple on this page."
                ))
            elif ratio > Decimal("1.5"):
                notes.append(_note("Cash conversion",
                    f"Operating cash flow over FY{min(shared)}–FY{max(shared)} is "
                    f"{ratio * 100:.0f}% of reported net income — depreciation-heavy "
                    "or working-capital-driven, so the earnings multiple understates "
                    "what the business collects."
                ))

    # Share counts must be compared within one filing. A split restates every
    # earlier year, so a count taken from a pre-split report against one from a
    # post-split report measures the split and calls it dilution: NVIDIA's
    # ten-for-one made it look like an 867% issuance when the count had fallen.
    # A report states three years on one basis, which is basis enough.
    weighted = _annual_union(gaap, _WEIGHTED_SHARE_TAGS, unit=("shares",))
    newest = max((f.provenance.accession for f in weighted.values()), default=None,
                 key=lambda a: max(f.provenance.filed for f in weighted.values()
                                   if f.provenance.accession == a))
    same_filing = {y: f for y, f in weighted.items() if f.provenance.accession == newest}
    years = sorted(same_filing)
    if len(years) >= 3:
        latest, base = years[-1], years[0]
        old, new = same_filing[base].value, same_filing[latest].value
        if old > 0:
            change = (new / old - 1) * 100
            if change > 10:
                notes.append(_note("Dilution",
                    f"The share count grew {change:.0f}% between FY{base} and FY{latest} "
                    f"({old / _MILLION:,.1f}M to {new / _MILLION:,.1f}M shares). Per-share "
                    "figures are divided by a denominator that keeps rising."
                ))
            elif change < -10:
                notes.append(_note("Buybacks",
                    f"The share count fell {abs(change):.0f}% between FY{base} and FY{latest} "
                    f"({old / _MILLION:,.1f}M to {new / _MILLION:,.1f}M shares) — buybacks "
                    "are lifting per-share figures independently of the business."
                ))

    interest = _annual_union(gaap, INTEREST_EXPENSE_TAGS)
    shared_op = sorted(set(interest) & set(annual_op), reverse=True)[:1]
    for year in shared_op:
        cost, profit = abs(interest[year].value), annual_op[year].value
        if cost > 0 and profit > 0:
            cover = profit / cost
            if cover < 3:
                notes.append(_note("Interest cover",
                    f"FY{year} operating profit covers interest {cover:.1f}x "
                    f"({profit / _MILLION:,.0f}M against {cost / _MILLION:,.0f}M of interest). "
                    "Graham's debt test measures the balance sheet; this is what the "
                    "income statement pays for it."
                ))

    revenue = annual_revenue or {}
    if revenue:
        for tags, label, meaning in (
            (RECEIVABLE_TAGS, "Receivables",
             "Revenue booked and not yet collected is revenue the customer has not "
             "confirmed with cash."),
            (INVENTORY_TAGS, "Inventory",
             "Goods made and not sold sit at cost until they are written down."),
        ):
            note = _divergence_note(gaap, tags, revenue, label, meaning)
            if note:
                notes.append(_note(label, note))

    # NVF's debentures paid a 5% coupon and were sold at 43% of par, so the
    # interest statement described a cheaper company than the one that existed.
    # Where amortised discount is most of the interest bill, the coupon is not
    # the cost of the money.
    discount = _annual_union(gaap, DEBT_DISCOUNT_TAGS)
    shared_interest = sorted(set(discount) & set(interest), reverse=True)[:1]
    for year in shared_interest:
        amortised, total = abs(discount[year].value), abs(interest[year].value)
        if total > 0 and amortised / total >= Decimal("0.25"):
            notes.append(_note(
                "Debt discount",
                f"FY{year} interest of {total / _MILLION:,.0f}M includes "
                f"{amortised / _MILLION:,.0f}M of amortised debt discount, "
                f"{amortised / total * 100:.0f}% of the bill. Debt sold below face value "
                "costs more than its coupon says, and the difference arrives as a charge "
                "rather than a payment."
            ))

    conversion = _as_converted_note(gaap, shares, fresh, dimensioned)
    if conversion:
        notes.append(_note("Convertible preferred", conversion))

    # Graham devotes a whole section to warrants because they are dilution a
    # share count does not show: NVF paid for Sharon Steel partly in warrants on
    # its own stock, and every per-share figure afterwards was struck on a
    # denominator that ignored them.
    warrants = _latest_instant(gaap, "WarrantShares", WARRANT_SHARE_TAGS, unit=("shares",),
                               not_before=fresh)
    if warrants is not None and warrants.value > 0 and shares is not None and shares.value > 0:
        overhang = warrants.value / shares.value
        if overhang >= Decimal("0.05"):
            notes.append(_note(
                "Warrant overhang",
                f"Warrants call for {warrants.value / _MILLION:,.1f}M shares against "
                f"{shares.value / _MILLION:,.1f}M outstanding, {overhang * 100:.0f}% more. "
                "Graham's rule for these is not the fully-diluted one — assuming exercise and "
                "retiring debt with the proceeds he calls illogical, since it left National "
                "General's reported earnings per share unchanged at $1.51 either way. His rule "
                "is that warrants are part of the common-stock package, so their own market "
                "value belongs inside the market capitalisation: adding $221M of warrant value "
                "to $192M of common trebled the true price of that equity and took its "
                "price/earnings from 32 to 69. Warrants trade under their own symbols and this "
                "screen prices none of them, so the market capitalisation and every multiple "
                "built on it are understated by whatever the warrants are worth."
            ))

    # Graham read Penn Central's tax accounting as a second opinion on its
    # earnings, and took the tax authorities' side. The deferred tax footnote
    # holds two such opinions, and both are the company's own.
    latest_profit = annual_ni.get(max(annual_ni)) if annual_ni else None
    pair = _deferred_tax_assets(gaap, fresh)
    if pair is not None and latest_profit is not None and latest_profit.value > 0:
        allowance, gross = pair
        share = allowance.value / gross
        equity = _equity_for_scale(gaap, fresh_equity)
        # a full allowance on a tax asset worth a rounding error says nothing
        material = equity is None or gross >= equity * _ALLOWANCE_MATERIAL
        if share >= _ALLOWANCE_SHARE and material:
            notes.append(_note(
                "Valuation allowance",
                f"Deferred tax assets of {gross / _MILLION:,.0f}M carry a "
                f"{allowance.value / _MILLION:,.0f}M valuation allowance — "
                f"{share * 100:.0f}% of them — beside FY{max(annual_ni)} earnings of "
                f"{latest_profit.value / _MILLION:,.0f}M. The allowance is the company's own "
                "statement that it does not expect enough future profit to use deductions "
                "it has already earned."
            ))

    tax = _annual_union(gaap, TAX_TAGS)
    deferred = _annual_union(gaap, DEFERRED_TAX_EXPENSE_TAGS)
    for year in sorted(set(tax) & set(deferred) & set(annual_ni), reverse=True)[:1]:
        charge, postponed, profit = tax[year].value, deferred[year].value, annual_ni[year].value
        # a tax footnote older than the earnings record describes a different company
        if year < max(annual_ni) - 1 or charge <= 0 or profit <= 0:
            continue
        if (postponed / charge >= _DEFERRED_SHARE
                and abs(postponed) >= profit * _DEFERRED_MATERIAL):
            payable = charge - postponed
            paid = (f"only {payable / _MILLION:,.0f}M was currently payable" if payable > 0
                    else f"the current charge was a {abs(payable) / _MILLION:,.0f}M refund")
            notes.append(_note(
                "Deferred tax",
                f"FY{year}'s income tax charge of {charge / _MILLION:,.0f}M is "
                f"{postponed / charge * 100:.0f}% deferred: {paid}. Earnings taxed on paper "
                "and not in cash — usually timing on heavy capital spending, always a charge "
                "the tax return has not yet collected."
            ))

    # Rent is not borrowed money under criterion 3, which is Graham's reading and
    # the engine's policy — but a company can carry more of it than debt, and the
    # test that ignores it should say how much it is ignoring.
    leases = _latest_instant(gaap, "OperatingLeaseLiability", LEASE_OBLIGATION_TAGS)
    if leases is not None and leases.value > 0:
        debt = long_term_debt.value if long_term_debt else Decimal(0)
        # Large against the debt is only half of it: NVIDIA's lease book is more
        # than a quarter of its borrowings and 2% of its equity, which tells a
        # reader nothing. The obligation has to matter to the company too.
        equity = _equity_for_scale(gaap, fresh_equity)
        material = equity is None or leases.value >= equity * Decimal("0.10")
        if material and leases.value >= max(debt, Decimal(0)) * Decimal("0.25"):
            against = (f"against {debt / _MILLION:,.0f}M of long-term debt"
                       if debt else "with no long-term debt reported")
            notes.append(_note(
                "Lease obligations",
                f"Operating-lease obligations of {leases.value / _MILLION:,.0f}M {against}. "
                "The debt test counts borrowed money and not rent, which is Graham's "
                "reading, so this obligation sits outside it."
            ))
    return tuple(notes)


def _restricted_cash(gaap: dict, fresh: date | None, end: date | None) -> Fact | None:
    """One restricted-cash representation at exactly the given period end: the
    single total first, else current+noncurrent, else the cash-equivalents pair
    (GE's only fresh figure is the noncurrent variant of the latter)."""
    def at_end(concept: str, tag: str) -> Fact | None:
        f = _latest_instant(gaap, concept, (tag,), not_before=fresh)
        return f if f is not None and f.provenance.period_end == end else None

    total = at_end("RestrictedCash", "RestrictedCash")
    if total is not None:
        return total
    summed = _sum_facts("RestrictedCash", [
        at_end("RestrictedCash (current)", "RestrictedCashCurrent"),
        at_end("RestrictedCash (noncurrent)", "RestrictedCashNoncurrent"),
    ])
    if summed is not None:
        return summed
    return _sum_facts("RestrictedCash", [
        at_end("RestrictedCash (and equivalents)", "RestrictedCashAndCashEquivalents"),
        at_end("RestrictedCash (and equivalents, noncurrent)",
               "RestrictedCashAndCashEquivalentsNoncurrent"),
    ])


def _implied_shares(gaap: dict, annual_eps: dict[int, Fact], annual_ni: dict[int, Fact],
                    annual_preferred: dict[int, Fact] | None = None) -> Decimal | None:
    """Share count implied by the filer's own earnings: net income over EPS.

    Independent of every share tag, because it is the denominator the company must
    have divided by to publish the EPS it published. EPS nets preferred dividends
    from income and the NetIncomeLoss tag does not, so they come out first —
    GTN's implied count was 2.2x off until they did.
    """
    for year in sorted(annual_eps, reverse=True):
        eps, ni = annual_eps.get(year), annual_ni.get(year)
        if eps is None or ni is None or eps.value == 0:
            continue
        preferred = (annual_preferred or {}).get(year)
        common = ni.value - (preferred.value if preferred else Decimal(0))
        implied = common / eps.value
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
    # A company cannot have no shares. A zero is a tagging artefact, and it is
    # the most dangerous one available: every per-share figure divides by this.
    if chosen is None or chosen.value <= 0:
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

    def ratio(a: Decimal, b: Decimal) -> Decimal:
        return max(a, b) / min(a, b)

    if len(candidates) >= 3:
        if all(ratio(chosen.value, f.value) > 10 for f in others):
            return sorted(candidates, key=lambda f: f.value)[1]
        # Dual-class fragment: an undimensioned instant can carry ONE class of a
        # multi-class filer — a 2-3x error, far under the magnitude test. When
        # the two independent witnesses agree with each other and both disagree
        # with the chosen count, the chosen count is the fragment.
        if (ratio(others[0].value, others[1].value) < Decimal("1.35")
                and all(ratio(chosen.value, f.value) > Decimal("1.5") for f in others)):
            return sorted(candidates, key=lambda f: f.value)[1]
        return chosen
    if len(candidates) == 2 and implied is not None and implied > 0:
        # earnings arithmetic is the third witness: HEI's stale 55M class
        # instant loses to the 141M weighted count that NI/EPS corroborates
        other = others[0]
        if (ratio(chosen.value, other.value) > Decimal("1.5")
                and ratio(other.value, implied) < Decimal("1.35")):
            return other
    # With one source there is nothing to outvote, and that is exactly where a filer
    # tagging shares in thousands slips through: Hub Group reported 60,333 against a
    # true 60.3 million, which passed criterion 7 at a price-to-book of 0.00. Earnings
    # give an independent reading, so an order-of-magnitude disagreement retires the
    # count rather than publishing a thousandfold-wrong book value.
    if implied is not None and implied > 0 and chosen.value > 0:
        if max(chosen.value, implied) / min(chosen.value, implied) > 10:
            return None
        # The last-resort tags are fragments exactly when nothing corroborates
        # them (SUN's LP-unit instant is 51.5M of ~136M real units); with no
        # witness and a 2x earnings disagreement, missing beats wrong.
        if not others and chosen.provenance.tag in (
            "us-gaap:LimitedPartnersCapitalAccountUnitsOutstanding",
            "us-gaap:SharesOutstanding",
        ) and max(chosen.value, implied) / min(chosen.value, implied) > 2:
            return None
    return chosen


def _is_partnership(gaap: dict, not_before: date | None) -> bool:
    """Partners capital present and stockholders equity absent — the shape of a
    filer whose 'shares' are limited-partner units."""
    partners = _latest_instant(
        gaap, "PartnersCapital",
        ("PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest", "PartnersCapital"),
        not_before=not_before,
    )
    stockholders = _latest_instant(
        gaap, "StockholdersEquity",
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
         "StockholdersEquity"),
        not_before=not_before,
    )
    return partners is not None and stockholders is None


def _weighted_shares(gaap: dict, not_before: date | None) -> Fact | None:
    """Multi-class filers often tag no point-in-time consolidated share count.
    Weighted-average shares from the income statement is the flagged proxy —
    diluted first, so basic-only filers still get a count instead of none."""
    floor = not_before.isoformat() if not_before else ""
    for tag in _WEIGHTED_SHARE_TAGS:
        entries = [
            e
            for e in _entries(gaap, tag, ("shares",))
            if "start" in e and _is_financial_form(e.get("form", "")) and e["end"] >= floor
        ]
        if not entries:
            continue
        latest_end = max(e["end"] for e in entries)
        best = None
        for e in entries:
            if e["end"] != latest_end:
                continue
            # shortest duration = closest to a point-in-time count; then latest filed
            if best is None or _days(e) < _days(best) or (_days(e) == _days(best) and e["filed"] > best["filed"]):
                best = e
        return _fact("SharesOutstanding (weighted-average proxy)", tag, best)
    return None


def _is_a_rate_not_a_total(gaap: dict, tag: str, unit: tuple[str, ...],
                           annual: dict[int, Fact]) -> bool:
    """Whether a per-share dividend element states the quarterly rate rather than
    the year's total.

    Visa tags 0.59 for a ninety-day quarter and 0.59 again for the whole fiscal
    year: the element carries the rate per payment, repeated against every
    context. Treating that as a year's dividends understates the yield fourfold,
    and the filer's own facts are what give it away — a total cannot equal one
    of its own quarters."""
    for year, fact in annual.items():
        end = fact.provenance.period_end
        if end is None:
            continue
        for e in _entries(gaap, tag, unit):
            if "start" not in e or not _is_financial_form(e.get("form", "")):
                continue
            if e["end"] != end.isoformat() or not 80 <= _days(e) <= 100:
                continue
            if _dec(e["val"]) == fact.value:
                return True
    return False


def _dividend_per_share(gaap: dict, dividend: Fact | None, shares: Fact | None,
                        fresh: date | None = None) -> Decimal | None:
    """A dividend fact covers whatever span the filer tagged — a quarter for one
    company, half a year for another — so the raw figure is not comparable. Roll it
    to twelve months the same way earnings are, then express it per share."""
    if dividend is None:
        return None
    # The element that proves a company still pays is not always the one it uses
    # for its annual totals: Coca-Cola's freshest dividend fact is quarterly
    # under DividendsCommonStockCash, and it tags no annual series there at all,
    # so reading the yield from that one tag alone left 167 payers — Coke, ADP,
    # Visa, Exxon — showing that they pay without saying how much. Every chained
    # element is tried, per-share ones first: those need no share count, so they
    # cannot inherit an error from it.
    chosen = dividend.provenance.tag.split(":", 1)[1]
    ordered = sorted(
        DIVIDEND_TAGS,
        key=lambda pair: (pair[0] != chosen, "USD/shares" not in pair[1]),
    )
    for tag, unit in ordered:
        # The chain's own unit declaration decides per-share vs dollar aggregate;
        # a name test would silently mis-scale any newly added per-unit tag.
        per_share = "USD/shares" in unit
        annual = _annual_series(gaap, tag, unit=unit)
        if not annual:
            continue
        if per_share and _is_a_rate_not_a_total(gaap, tag, unit, annual):
            continue
        # A twelve-month roll built from a series that stopped years ago is not a
        # twelve-month figure. Wynn's 2012 special dividend was still being divided
        # by a 2026 price and published as a 9.49% yield.
        if fresh is not None:
            newest = max((f.provenance.period_end for f in annual.values()
                          if f.provenance.period_end), default=None)
            if newest is None or newest < fresh:
                continue
        ttm, _ = _ttm_eps(gaap, annual, unit=unit, per_share=False)
        if ttm is None or ttm <= 0:
            continue
        if per_share:
            return ttm
        if shares is not None and shares.value > 0:
            return ttm / shares.value
    return None


def _dividend_record(gaap: dict) -> dict | None:
    """Which calendar years the filer actually paid a common dividend, from the
    chained tags' own facts. XBRL history only begins around 2009-2011, so the
    start of the record is part of the answer: "paid since 2011" can mean "paid
    for longer than the record can show" — display must say when the record begins."""
    totals: dict[int, Decimal] = {}
    for tag, unit in DIVIDEND_TAGS:
        for e in _entries(gaap, tag, unit):
            if "start" in e and _is_financial_form(e.get("form", "")) \
                    and _dec(e["val"]) > 0:
                year = int(e["end"][:4])
                totals[year] = max(totals.get(year, Decimal(0)), _dec(e["val"]))
    if not totals:
        return None
    # Graham's twenty years is a record of *paying*, and a company that cut its
    # dividend to a rounding error did interrupt it. A year whose largest payment
    # is a small fraction of the record's typical one is a suspension with a
    # residue, not a paid year.
    ordered = sorted(totals.values())
    typical = ordered[len(ordered) // 2]
    paid = {y for y, v in totals.items() if v >= typical * _SUSPENSION_SHARE}
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


def _is_all_preferred(gaap: dict, e: dict) -> bool:
    """Whether a payment for this exact period is entirely the preferred's."""
    for tag in PREFERRED_DIVIDEND_TAGS:
        for other in _entries(gaap, tag, ("USD",)):
            if (other.get("start") == e.get("start") and other.get("end") == e.get("end")
                    and _dec(other["val"]) >= _dec(e["val"]) * Decimal("0.99")):
                return True
    return False


def _dividend(gaap: dict, reference: date | None) -> tuple[bool | None, Fact | None]:
    if reference is None:
        return None, None
    for tag, unit in DIVIDEND_TAGS:
        positive = [e for e in _entries(gaap, tag, unit) if "start" in e and _dec(e["val"]) > 0]
        if not positive:
            continue
        e = max(positive, key=lambda e: (e["end"], e["filed"]))
        # An aggregate tag can hold a payment the common never receives: Boeing's
        # PaymentsOfDividends for the half year to 2026-06-30 is 172,000,000, and
        # its own DividendsPreferredStock for that identical period is the same
        # 172,000,000 — the cash-flow line reads "Dividends paid on mandatory
        # convertible preferred stock" and there is no common line at all. Where
        # the whole of a payment is the preferred's, it is not evidence that the
        # common is paid.
        if tag in _AGGREGATE_DIVIDEND_TAGS and _is_all_preferred(gaap, e):
            continue
        if (reference - date.fromisoformat(e["end"])).days <= _days(e) + _DIVIDEND_LAG_DAYS:
            concept = ("Dividends (aggregate — may include preferred and noncontrolling)"
                       if tag in _AGGREGATE_DIVIDEND_TAGS else "Dividends (common stock)")
            return True, _fact(concept, tag, e)
    # The chain missed, but a recent positive fact under ANY other dividend- or
    # distribution-named tag means the filer likely pays via a tag we don't
    # read: unknown, never FAIL. Up-C filers whose only payouts go to NCI
    # holders (SDHC/GLXY pattern) intentionally land here as unknown.
    floor = (reference - timedelta(days=_DIVIDEND_RECENCY_DAYS)).isoformat()
    chained = {tag for tag, _ in DIVIDEND_TAGS}
    for tag, tagdata in gaap.items():
        low = tag.lower()
        if tag in chained or ("dividend" not in low and "distribut" not in low):
            continue
        if _DIVIDEND_EVIDENCE_EXCLUDE_RE.search(tag):
            continue
        for unit_name, unit in tagdata.get("units", {}).items():
            if unit_name in ("shares", "pure"):  # counts and ratios are not payouts
                continue
            for e in unit:
                if (_is_financial_form(e.get("form", ""))
                        and e.get("end", "") >= floor
                        and isinstance(e.get("val"), (int, float)) and e["val"] > 0):
                    return None, None
    # Dividend payers must report payments in the cash-flow statement; no recent
    # positive fact under any dividend-named tag => not currently paying.
    return False, None
