"""Shared data model. Decimal for all financial arithmetic; float never."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class Provenance:
    concept: str
    tag: str
    fiscal_year: int | None
    form: str
    accession: str
    filed: date
    period_end: date | None = None
    period_start: date | None = None  # duration facts only; None for balance-sheet instants


@dataclass(frozen=True)
class Fact:
    value: Decimal
    provenance: Provenance


@dataclass(frozen=True)
class Quote:
    price: Decimal
    asof: datetime
    source: str


@dataclass(frozen=True)
class PriceHistory:
    """Weekly closes behind the quote, oldest first — the input to pricestats."""
    quote: Quote
    closes: tuple[tuple[date, Decimal], ...]


@dataclass(frozen=True)
class OwnerEarnings:
    """Buffett's owner earnings over the invested capital that produced them.

    Never a criterion — Graham's requirements do not measure return on capital at all.
    This is a quality lens for ranking the survivors: two companies can clear the
    same balance-sheet tests while one compounds at 20% and the other at 4%.
    """
    fiscal_year: int
    owner_earnings: Decimal
    invested_capital: Decimal | None
    roic: Decimal | None  # owner earnings / invested capital, as a percentage
    # signed contributions in statement order, so the UI can show the derivation
    components: tuple[tuple[str, Decimal], ...]
    # ROIC if maintenance capital expenditure is assumed to equal depreciation —
    # Buffett's own approximation, and the optimistic end of the range
    roic_maintenance: Decimal | None = None
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class FinancialSnapshot:
    cik: str
    ticker: str
    annual_eps: dict[int, Fact]  # fiscal year -> diluted EPS, 10-K facts only
    annual_net_income: dict[int, Fact]  # the numerator behind EPS, same basis
    ttm_net_income: Decimal | None
    ttm_eps: Decimal | None
    ttm_eps_inputs: tuple[Fact, ...]
    current_assets: Fact | None
    current_liabilities: Fact | None
    long_term_debt: Fact | None
    short_term_debt: Fact | None
    total_assets: Fact | None
    total_liabilities: Fact | None
    goodwill: Fact | None
    intangibles: Fact | None
    preferred_stock: Fact | None
    shares_outstanding: Fact | None
    dividend: Fact | None  # evidence for pays_dividend, when True
    dividend_per_share: Decimal | None  # rolled to twelve months, for the yield
    pays_dividend: bool | None
    balance_sheet_date: date | None
    total_debt: Fact | None = None  # total-style rollup tag; preferred over long+short when present
    # concepts with zero facts anywhere in the filing history, opt-in treated as 0 (flagged)
    assumed_zero: frozenset = frozenset()
    # deducted in TBV: Assets - Liabilities includes minority holders' equity;
    # None when the liabilities derivation already excluded it
    noncontrolling_interest: Fact | None = None
    # disclosures about what the TTM earnings are made of — never criteria, but
    # criterion 1 can turn on a single non-recurring line, so they are surfaced
    earnings_quality: tuple[str, ...] = ()
    owner_earnings: OwnerEarnings | None = None
    # "Dec 31" -> TTM EPS computable from facts FILED by that date, rebased onto
    # today's share count; the hindsight-free denominator for historical P/E
    ttm_eps_vintage: dict[str, Decimal] = field(default_factory=dict)
    # chapter-13 comparison inputs: sales, operating income, dividend continuity
    annual_revenue: dict[int, Fact] = field(default_factory=dict)
    ttm_revenue: Decimal | None = None
    annual_operating_income: dict[int, Fact] = field(default_factory=dict)
    # {"first", "latest", "streak_from", "paid_years"} — calendar years with a
    # positive common dividend; None when the record holds none
    dividend_record: dict | None = None
    # mezzanine (temporary) equity senior to common — set only when it must be
    # deducted from common book: absent/zero preferred, liabilities not derived
    temporary_equity: Fact | None = None
    # trailing preferred dividends: EPS nets them, NetIncomeLoss does not
    ttm_preferred_dividends: Decimal | None = None
    # cash conversion, dilution and interest coverage — context a passing
    # multiple cannot answer; never a criterion, never an adjustment
    context_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpsGrowth:
    """Latest annual EPS against the best year in the 4-7-year window behind it.

    Never a criterion. Graham's fifth requirement compared the latest year against
    a *fixed* calendar year, 1966, and the book gives no rule for choosing that base
    in any other year — a rolling pointer, a prior peak, and a prior average all
    change what passing proves, and none of them is his. Rather than attribute a
    modern base year to Graham, the comparison is reported and left to the reader.
    """
    base_fiscal_year: int
    base_eps: Decimal
    latest_fiscal_year: int
    latest_eps: Decimal


@dataclass(frozen=True)
class CriterionResult:
    criterion: int
    name: str
    status: Status
    value: Decimal | None
    threshold: str
    inputs: tuple[Fact, ...]
    note: str | None = None


@dataclass(frozen=True)
class ScreenResult:
    ticker: str
    cik: str
    verdict: Verdict
    criteria: tuple[CriterionResult, ...]
    quote: Quote | None
    balance_sheet_date: date | None
    annual_eps_series: dict[int, Decimal]
    # relaxations applied to the screen: assumed-zero concepts (opt-in)
    assumptions: tuple[str, ...] = ()
    # disclosure, not a test — see EpsGrowth
    eps_growth: EpsGrowth | None = None
