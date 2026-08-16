"""Screen-layer fixtures per design doc §7.1."""
from datetime import date, datetime
from decimal import Decimal

from screener.models import Fact, FinancialSnapshot, Provenance, Quote, Status, Verdict
from screener.screens.enterprising import evaluate

QUOTE = Quote(price=Decimal("50"), asof=datetime(2026, 8, 13, 16, 0), source="test")

EPS_YEARS = {2020: "2.5", 2021: "3.0", 2022: "3.5", 2023: "4.0", 2024: "5.0", 2025: "6.0"}


def F(concept, value, fy=None, form="10-K"):
    return Fact(
        Decimal(str(value)),
        Provenance(concept, f"us-gaap:{concept}", fy, form, "0000000000-26-000001",
                   date(2026, 5, 2), date(2026, 3, 31)),
    )


def snap(**overrides):
    eps_years = overrides.pop("eps_years", EPS_YEARS)
    eps = {y: F("EarningsPerShareDiluted", v, fy=y) for y, v in eps_years.items()}
    # net income mirrors EPS at a nominal share count; the screen never reads it,
    # but the snapshot carries it so share-count effects stay visible
    net = {y: F("NetIncomeLoss", Decimal(str(v)) * 1_000_000, fy=y) for y, v in eps_years.items()}
    base = dict(
        cik="0000000001",
        ticker="TEST",
        annual_eps=eps,
        annual_net_income=net,
        ttm_net_income=Decimal("6000000"),
        ttm_eps=Decimal("6.0"),
        ttm_eps_inputs=(eps[max(eps)],) if eps else (),
        current_assets=F("AssetsCurrent", 300),
        current_liabilities=F("LiabilitiesCurrent", 150),
        long_term_debt=F("LongTermDebtNoncurrent", 100),
        short_term_debt=F("LongTermDebtCurrent", 10),
        total_assets=F("Assets", 1000),
        total_liabilities=F("Liabilities", 400),
        goodwill=F("Goodwill", 50),
        intangibles=F("IntangibleAssetsNetExcludingGoodwill", 30),
        preferred_stock=None,
        shares_outstanding=F("CommonStockSharesOutstanding", 10),
        dividend=F("Dividends", 5),
        dividend_per_share=Decimal("0.50"),
        pays_dividend=True,
        balance_sheet_date=date(2026, 3, 31),
    )
    base.update(overrides)
    return FinancialSnapshot(**base)


def crit(result):
    return {c.criterion: c for c in result.criteria}


def test_clean_company_passes_every_criterion():
    r = evaluate(snap(), QUOTE)
    assert [c.criterion for c in r.criteria] == [1, 2, 3, 4, 5, 7]  # no 6: see EpsGrowth
    assert [c.status for c in r.criteria] == [Status.PASS] * 6
    assert r.verdict == Verdict.PASS


def test_hidden_loss_year_fails_criterion_4():
    # TTM EPS positive, but one fiscal year in the window is negative
    r = evaluate(snap(eps_years={**EPS_YEARS, 2023: "-0.5"}), QUOTE)
    c = crit(r)
    assert c[1].status == Status.PASS  # TTM still positive
    assert c[4].status == Status.FAIL
    assert "2023" in c[4].note
    assert r.verdict == Verdict.FAIL


def test_bank_without_classified_balance_sheet():
    r = evaluate(
        snap(current_assets=None, current_liabilities=None,
             long_term_debt=None, short_term_debt=None),
        QUOTE,
    )
    c = crit(r)
    assert c[2].status == Status.NOT_APPLICABLE
    assert c[3].status == Status.NOT_APPLICABLE
    assert r.verdict == Verdict.INDETERMINATE  # N/A never permits overall PASS


def test_missing_goodwill_is_insufficient_never_pass():
    r = evaluate(snap(goodwill=None), QUOTE)
    c = crit(r)
    assert c[7].status == Status.INSUFFICIENT_DATA
    assert r.verdict == Verdict.INDETERMINATE


def test_a_measured_failure_outranks_an_unknown():
    """A criterion that was measured and failed is decisive; what could not be
    measured cannot rescue it. INDETERMINATE is reserved for "nothing known"."""
    r = evaluate(snap(goodwill=None, eps_years={**EPS_YEARS, 2023: "-0.5"}), QUOTE)
    assert crit(r)[4].status == Status.FAIL
    assert crit(r)[7].status == Status.INSUFFICIENT_DATA
    assert r.verdict == Verdict.FAIL


def test_indeterminate_only_when_nothing_definitive_is_known():
    r = evaluate(snap(goodwill=None), QUOTE)          # only the unknown, no failure
    assert not any(c.status == Status.FAIL for c in r.criteria)
    assert r.verdict == Verdict.INDETERMINATE


def test_fail_with_not_applicable_is_fail():
    r = evaluate(
        snap(current_assets=None, current_liabilities=None,
             long_term_debt=None, short_term_debt=None,
             eps_years={**EPS_YEARS, 2023: "-0.5"}),
        QUOTE,
    )
    assert r.verdict == Verdict.FAIL


def test_no_quote_makes_price_criteria_insufficient():
    r = evaluate(snap(), None)
    c = crit(r)
    assert c[1].status == Status.INSUFFICIENT_DATA
    assert c[7].status == Status.INSUFFICIENT_DATA
    assert r.verdict == Verdict.INDETERMINATE


def test_negative_ttm_eps_fails_criterion_1():
    r = evaluate(snap(ttm_eps=Decimal("-1")), QUOTE)
    assert crit(r)[1].status == Status.FAIL


def test_pe_boundary_is_strict():
    # price 60 / eps 6.0 = exactly 10 -> FAIL (test is P/E < 10)
    q = Quote(price=Decimal("60"), asof=QUOTE.asof, source="test")
    assert crit(evaluate(snap(), q))[1].status == Status.FAIL


def test_short_eps_history_is_insufficient():
    r = evaluate(snap(eps_years={y: EPS_YEARS[y] for y in (2022, 2023, 2024, 2025)}), QUOTE)
    assert crit(r)[4].status == Status.INSUFFICIENT_DATA
    assert r.eps_growth is None  # nothing 4-7 years back to compare against


def test_missing_debt_tag_is_insufficient_not_zero():
    r = evaluate(snap(short_term_debt=None), QUOTE)
    c = crit(r)
    assert c[3].status == Status.INSUFFICIENT_DATA
    assert "short-term debt" in c[3].note


def test_preferred_default_is_flagged():
    c = crit(evaluate(snap(), QUOTE))[7]
    assert c.status == Status.PASS
    assert "defaulted to 0" in c.note


def test_growth_is_reported_against_the_best_year_in_the_window():
    # the base is the best year in the 4-7 window, here FY2021 (3.0), not the
    # positional five-years-back FY2020 (2.5)
    g = evaluate(snap(), QUOTE).eps_growth
    assert (g.base_fiscal_year, g.base_eps) == (2021, Decimal("3.0"))
    assert (g.latest_fiscal_year, g.latest_eps) == (2025, Decimal("6.0"))


def test_zero_current_liabilities_is_insufficient():
    r = evaluate(snap(current_liabilities=F("LiabilitiesCurrent", 0)), QUOTE)
    assert crit(r)[2].status == Status.INSUFFICIENT_DATA


def test_no_dividend_fails_criterion_5():
    r = evaluate(snap(pays_dividend=False, dividend=None), QUOTE)
    assert crit(r)[5].status == Status.FAIL


def test_noncontrolling_interest_deducted_from_tbv():
    # clean fixture TBV = 520 on 10 shares; NCI 120 -> TBV 400 -> TBVPS 40
    # price 50 -> P/TBV 1.25 > 1.20 -> FAIL (was PASS at 1.15 without the deduction)
    r = evaluate(snap(noncontrolling_interest=F("MinorityInterest", 120)), QUOTE)
    c = crit(r)[7]
    assert c.status == Status.FAIL
    assert c.value == Decimal("1.25")


def test_growth_disclosure_never_appears_among_the_criteria():
    """Graham's 1966 base has no modern heir, so the comparison is reported beside
    the verdict and can neither pass, fail, nor make a company indeterminate."""
    # earnings a third of the window's best year — under the old criterion 6 a FAIL
    years = {2018: "1.0", 2019: "2.0", 2020: "9.0", 2021: "3.0",
             2022: "3.5", 2023: "4.0", 2024: "5.0", 2025: "6.0"}
    r = evaluate(snap(eps_years=years), QUOTE)
    assert 6 not in crit(r)
    assert r.verdict == Verdict.PASS
    assert r.eps_growth.base_fiscal_year == 2020      # the window's best, not its last
    assert r.eps_growth.latest_eps < r.eps_growth.base_eps


def test_total_debt_rollup_preferred_over_components():
    r = evaluate(snap(total_debt=F("DebtAndCapitalLeaseObligations", 200),
                      long_term_debt=None, short_term_debt=None), QUOTE)
    c = crit(r)[3]
    assert c.status == Status.FAIL  # 200 > 1.10 * 150
    assert c.value == Decimal("1.33")


def test_assumed_zero_debt_computes_criterion_3_with_note():
    r = evaluate(snap(long_term_debt=None, short_term_debt=None,
                      assumed_zero=frozenset({"debt"})), QUOTE)
    c = crit(r)[3]
    assert c.status == Status.PASS  # debt 0 <= 1.10 * NCA
    assert "assumed 0" in c.note
    assert "debt" in r.assumptions


def test_assumed_zero_goodwill_computes_criterion_7_with_note():
    r = evaluate(snap(goodwill=None, assumed_zero=frozenset({"goodwill"})), QUOTE)
    c = crit(r)[7]
    assert c.status == Status.PASS
    assert "assumed 0 for goodwill" in c.note


def test_without_assumption_missing_debt_still_insufficient():
    r = evaluate(snap(long_term_debt=None, short_term_debt=None), QUOTE)
    assert crit(r)[3].status == Status.INSUFFICIENT_DATA


def test_declining_earnings_are_disclosed_not_penalised():
    """ASO shape: four consecutive years of decline off a pandemic trough. The reader
    sees the fall; the screen's verdict is settled entirely by the other criteria."""
    years = {2020: "3.79", 2021: "7.12", 2022: "7.49", 2023: "6.70", 2024: "5.73", 2025: "5.54"}
    r = evaluate(snap(eps_years=years, ttm_eps=Decimal("5.66")), QUOTE)
    assert r.eps_growth.base_fiscal_year == 2021     # the peak, not the FY2020 trough
    assert r.eps_growth.latest_eps == Decimal("5.54")
    assert r.verdict == Verdict.PASS


def test_a_loss_ridden_window_still_reports_its_best_year():
    """A negative base is arithmetic, not an error — and no longer decides anything."""
    years = {2018: "-2.0", 2019: "-1.5", 2020: "-3.0", 2021: "-0.5",
             2022: "1.0", 2023: "2.0", 2024: "3.0", 2025: "4.0"}
    g = evaluate(snap(eps_years=years), QUOTE).eps_growth
    assert (g.base_fiscal_year, g.base_eps) == (2021, Decimal("-0.5"))


def test_known_loss_year_fails_even_when_the_window_is_incomplete():
    """A recent IPO with three filed years, all losses, definitively fails — the
    two missing years cannot undo a loss that already happened."""
    r = evaluate(snap(eps_years={2023: "-13.24", 2024: "-10.66", 2025: "-3.22"}), QUOTE)
    c = crit(r)[4]
    assert c.status == Status.FAIL
    assert "only 3 of 5 years on file" in c.note


def test_short_but_unbroken_history_stays_insufficient():
    """Profitable in every year we have, but we cannot claim five clean years."""
    r = evaluate(snap(eps_years={2023: "1.10", 2024: "1.40", 2025: "1.80"}), QUOTE)
    c = crit(r)[4]
    assert c.status == Status.INSUFFICIENT_DATA
    assert "profitable in every year on file" in c.note
