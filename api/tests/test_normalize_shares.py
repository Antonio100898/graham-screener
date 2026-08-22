"""How many shares there are — splits, the counts that corroborate them,
and the awards and receipts that change what a share means."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot
from helpers import *  # noqa: F403 — the shared fixtures, by design
from helpers import EPS, GAAP, build, dur, facts_doc, inst, tagdata, texts
from helpers import _dimensioned, _reported, _shares, _years, _yr  # underscored, so `import *` skips them


def test_weighted_diluted_shares_fallback():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 9.9e9, form="10-Q", accn="q126", filed="2026-05-05"),  # quarter
        dur("2025-04-01", "2026-03-31", 9.5e9, form="10-Q", accn="q126", filed="2026-05-05"),  # trailing yr
    ])
    s = build(gaap)
    assert float(s.shares_outstanding.value) == 9.9e9  # shortest duration wins
    assert "proxy" in s.shares_outstanding.provenance.concept


def test_share_guard_does_not_block_dollar_totals():
    """Net income is an absolute figure: a share count change cannot invalidate
    adding one period to another. Only per-share series need the guard."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", -3.22, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", 0.0, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -12.80, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -68.1e6, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", -1.1e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -174.4e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-06-30", 283e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 50e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("-3.22"), "per-share composite still refused"
    assert s.ttm_net_income == Decimal("105200000.0"), "dollar composite must still be computed"


def test_share_count_tagged_in_thousands_is_outvoted():
    """A filer that reports shares in thousands understates the count a thousandfold,
    which inflates NCAV and book value per share by the same factor. The cover page and
    the weighted average outvote it."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 10e6, accn="q126")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 9.9e9, form="10-Q", accn="q126", filed="2026-05-05"),
    ])
    dei = {"EntityCommonStockSharesOutstanding": tagdata("shares", [
        inst("2026-03-31", 10.1e9, accn="q126")])}
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap, dei))
    assert float(s.shares_outstanding.value) == 9.9e9  # median of the three, not the outlier


def test_ordinary_share_count_disagreement_leaves_the_choice_alone():
    """The three counts are drawn on different dates and never match exactly; only an
    order-of-magnitude gap is evidence of a scale error."""
    gaap = dict(GAAP)
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 9.8e9, form="10-Q", accn="q126", filed="2026-05-05"),
    ])
    dei = {"EntityCommonStockSharesOutstanding": tagdata("shares", [
        inst("2026-04-30", 10.2e9, accn="q126")])}
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap, dei))
    assert float(s.shares_outstanding.value) == 10e9  # the balance-sheet instant still wins


def test_lone_outlier_share_count_needs_two_witnesses():
    """With only two counts there is nothing to arbitrate — a median of two would blend
    a good source with a bad one, so the ordinary preference order stands."""
    gaap = {k: v for k, v in GAAP.items() if k != "WeightedAverageNumberOfDilutedSharesOutstanding"}
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 1000, accn="q126")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap))
    assert float(s.shares_outstanding.value) == 1000


def test_basic_only_filer_still_gets_weighted_share_proxy():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["WeightedAverageNumberOfSharesOutstandingBasic"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 9.7e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert float(s.shares_outstanding.value) == 9.7e9
    assert "WeightedAverageNumberOfSharesOutstandingBasic" in s.shares_outstanding.provenance.tag


def test_per_share_dividend_detection_uses_the_chain_unit_not_the_name():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["CommonStockDividendsPerShareCashPaid"] = tagdata("USD/shares", [
        dur("2026-01-01", "2026-03-31", 0.5, form="10-Q", accn="q126", filed="2026-05-05"),
        dur("2025-01-01", "2025-03-31", 0.45, form="10-Q", accn="q125", filed="2025-05-05"),
        dur("2025-01-01", "2025-12-31", 1.9, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    # per-share fact is used directly, never divided by the share count again
    assert s.dividend_per_share == Decimal("1.9") + Decimal("0.5") - Decimal("0.45")


def test_per_unit_lp_distribution_feeds_dps_without_a_share_count_uan_style():
    gaap = {k: v for k, v in GAAP.items()
            if k not in ("PaymentsOfDividendsCommonStock", "CommonStockSharesOutstanding")}
    gaap["DistributionMadeToLimitedPartnerDistributionsPaidPerUnit"] = tagdata("USD/shares", [
        dur("2026-01-01", "2026-03-31", 2.26, form="10-Q", accn="q126", filed="2026-05-05"),
        dur("2025-01-01", "2025-03-31", 1.80, form="10-Q", accn="q125", filed="2025-05-05"),
        dur("2025-01-01", "2025-12-31", 4.37, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert s.pays_dividend is True
    # per-unit fact used directly: 4.37 + 2.26 - 1.80 — never divided by shares
    assert s.dividend_per_share == Decimal("4.37") + Decimal("2.26") - Decimal("1.80")


def test_investment_company_per_share_beats_the_fragmented_amount_tag_main_style():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["InvestmentCompanyDistributionToShareholdersPerShare"] = tagdata("USD/shares", [
        dur("2026-01-01", "2026-03-31", 0.77, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["InvestmentCompanyDividendDistribution"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 30.4e6, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert "PerShare" in s.dividend.provenance.tag


def test_share_and_ratio_units_are_never_payout_evidence():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["CommonStockDividendsShares"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 1e6, form="10-Q", accn="q126", filed="2026-05-05")])
    assert build(gaap).pays_dividend is False  # no dollar payout anywhere -> not paying


def test_lp_weighted_units_serve_as_the_share_proxy_et_style():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["WeightedAverageLimitedPartnershipUnitsOutstandingDiluted"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 3.43e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert float(s.shares_outstanding.value) == 3.43e9


def test_generic_shares_outstanding_ranks_after_the_dei_cover_slb_style():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["SharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 1e6, accn="q126")])  # class fragment
    dei = {"EntityCommonStockSharesOutstanding": tagdata("shares", [
        inst("2026-04-28", 1.4e9, form="10-Q", accn="q126", filed="2026-05-05")])}
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap, dei))
    assert float(s.shares_outstanding.value) == 1.4e9

    # with no cover and no specific tag, the generic instant finally stands
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap))
    assert float(s.shares_outstanding.value) == 1e6


def test_lp_unit_instant_needs_the_partnership_gate_maa_style():
    # a REIT with stockholders equity: the OP-unit fragment must NOT become shares
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 6e9, accn="q126")])
    gaap["LimitedPartnersCapitalAccountUnitsOutstanding"] = tagdata("shares", [
        inst("2026-03-31", 2.9e6, accn="q126")])
    assert build(gaap).shares_outstanding is None

    # a true partnership: partners capital, no stockholders equity -> units count
    del gaap["StockholdersEquity"]
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    assert float(build(gaap).shares_outstanding.value) == 2.9e6


def test_warrant_remeasurement_note_claims_no_direction():
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 1e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["FairValueAdjustmentOfWarrants"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 200e6, form="10-Q", accn="q126", filed="2026-05-05")])
    note = next(n["text"] for n in build(gaap).earnings_quality if "warrant" in n["text"].lower())
    assert "cannot settle" in note
    assert "added to" not in note and "reduced" not in note


def test_dual_class_instant_fragment_loses_to_corroborated_weighted_hei_style():
    """HEI: a stale one-class instant (55M) against the 141M weighted count that
    NI/EPS corroborates — earnings arithmetic is the third witness."""
    gaap = dict(GAAP)
    # implied = NI / EPS ~= 141M via the annual series
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 846e6, accn="k25", filed="2026-02-15")])
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 6.0, accn="k25", filed="2026-02-15")])
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [
        inst("2025-07-31", 55.1e6, accn="q325", filed="2025-08-25")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 141e6, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap))
    assert float(s.shares_outstanding.value) == 141e6


def test_lone_lp_unit_instant_retired_when_earnings_disagree_sun_style():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 1537e6, accn="k25", filed="2026-02-15")])
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    gaap["LimitedPartnersCapitalAccountUnitsOutstanding"] = tagdata("shares", [
        inst("2026-03-31", 51.5e6, accn="q126")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap))
    # implied ~256M vs 51.5M with no witness: missing beats wrong
    assert s.shares_outstanding is None


def test_uncorroborated_weighted_count_survives_a_2x_earnings_gap_gtn_style():
    # preferred dividends legitimately push NI/EPS off the true count;
    # the weighted tag is not a fragile source and must stand
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -26e6, accn="k25", filed="2026-02-15")])
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", -0.58, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 100e6, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap))
    assert float(s.shares_outstanding.value) == 100e6


def test_context_notes_flag_a_rising_share_count():
    gaap = dict(GAAP)
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur(f"{y}-01-01", f"{y}-12-31", shares, accn="k25", filed="2026-02-15")
        for y, shares in ((2023, 100e6), (2024, 118e6), (2025, 130e6))])
    note = next(n for n in texts(build(gaap)) if "share count grew" in n)
    assert "30%" in note


def test_a_stock_split_is_not_dilution():
    """NVIDIA's ten-for-one restated every earlier year. A count from a
    pre-split report against one from a post-split report measures the split:
    it read as an 867% issuance while the count had in fact fallen."""
    gaap = dict(GAAP)
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2021-01-01", "2021-12-31", 2535e6, accn="k21", filed="2022-02-15"),
        dur("2023-01-01", "2023-12-31", 24940e6, accn="k25", filed="2026-02-25"),
        dur("2024-01-01", "2024-12-31", 24804e6, accn="k25", filed="2026-02-25"),
        dur("2025-01-01", "2025-12-31", 24514e6, accn="k25", filed="2026-02-25"),
    ])
    assert not any("share count grew" in n for n in texts(build(gaap)))


def test_a_zero_share_count_is_not_a_share_count():
    """Every per-share figure divides by this number; a tagged zero is an
    artefact, and treating it as real would make each of them meaningless."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 0, accn="q126")])
    assert build(gaap).shares_outstanding is None


def test_yield_reads_the_annual_series_even_from_another_chained_tag_ko_style():
    """Coca-Cola's freshest dividend fact is quarterly under one element while
    its annual series lives under another; reading only the winning tag left
    167 payers stating that they pay without saying how much."""
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DividendsCommonStockCash"] = tagdata("USD", [          # freshest, quarterly only
        dur("2026-01-01", "2026-04-03", 2.28e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["CommonStockDividendsPerShareCashPaid"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 2.06, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert s.pays_dividend is True
    assert s.dividend.provenance.tag.endswith("DividendsCommonStockCash")  # recency unchanged
    assert s.dividend_per_share == Decimal("2.06")                          # yield from the series


def test_a_per_share_rate_repeated_across_contexts_is_not_a_years_dividends():
    """Visa tags 0.59 for a quarter and 0.59 again for the fiscal year: the
    element carries the rate per payment. Taking it as the annual total would
    understate the yield fourfold, so the figure is withheld instead."""
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["CommonStockDividendsPerShareDeclared"] = tagdata("USD/shares", [
        dur("2024-10-01", "2025-09-30", 0.59, form="10-K", accn="k25", filed="2025-11-15"),
        dur("2025-07-01", "2025-09-30", 0.59, form="10-K", accn="k25", filed="2025-11-15"),
    ])
    assert build(gaap).dividend_per_share is None

    # a genuine annual total, larger than any one quarter, is used
    gaap["CommonStockDividendsPerShareDeclared"] = tagdata("USD/shares", [
        dur("2024-10-01", "2025-09-30", 2.36, form="10-K", accn="k25", filed="2025-11-15"),
        dur("2025-07-01", "2025-09-30", 0.59, form="10-K", accn="k25", filed="2025-11-15"),
    ])
    assert build(gaap).dividend_per_share == Decimal("2.36")


def test_several_share_classes_leave_the_figure_missing_visa_style():
    """Visa reports Class A at 3.03, B1 at 4.71 and B2 at 4.61 for one quarter.
    None of them is Visa's without knowing which class the ticker is, and a
    wrong class is a wrong multiple on a real company."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
        classed_entry("2025-01-01", "2025-12-31", 3.03, "ClassOfStock=CommonClassA;"),
        classed_entry("2025-01-01", "2025-12-31", 4.71, "ClassOfStock=CommonClassB1;"),
        classed_entry("2025-01-01", "2025-12-31", 4.61, "ClassOfStock=CommonClassB2;")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
    assert 2025 not in s.annual_eps


def test_a_dimension_that_is_not_a_share_class_is_a_slice_not_the_company():
    """A segment, a geography or a parent-only view describes part of a
    business; only the share-class axis names a security a ticker can be."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    for segments in ("ConsolidatedEntities=ParentCompany;",
                     "BusinessSegments=InsuranceSegment;",
                     "Geographical=AsiaPacific;",
                     "ClassOfStock=CommonStock;Geographical=AsiaPacific;"):
        dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
            classed_entry("2025-01-01", "2025-12-31", 9.99, segments)])
        s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
        assert 2025 not in s.annual_eps, segments


def test_a_classed_share_count_serves_when_every_other_source_is_silent():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    dim = dimensioned("CommonStockSharesOutstanding", "shares", [
        {**classed_entry(None, "2026-03-31", 890e6, "ClassOfStock=CommonStock;",
                         accn="q126", form="10-Q", filed="2026-05-05")}])
    del dim["facts"]["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"][0]["start"]
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
    assert float(s.shares_outstanding.value) == 890e6


def test_warrants_are_dilution_a_share_count_does_not_show():
    """NVF paid for Sharon Steel partly in warrants on its own stock."""
    gaap = dict(GAAP)
    gaap["ClassOfWarrantOrRightNumberOfSecuritiesCalledByWarrantsOrRights"] = tagdata(
        "shares", [inst("2026-03-31", 2e9, accn="q126")])   # against 10bn outstanding
    note = next(n for n in texts(build(gaap)) if "Warrants call for" in n)
    assert "20%" in note


def test_a_small_warrant_overhang_says_nothing():
    gaap = dict(GAAP)
    gaap["ClassOfWarrantOrRightNumberOfSecuritiesCalledByWarrantsOrRights"] = tagdata(
        "shares", [inst("2026-03-31", 100e6, accn="q126")])   # 1% of the count
    assert not any("Warrants call for" in n for n in texts(build(gaap)))


def test_allowance_and_base_must_share_a_balance_sheet_date():
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 60e9)],
        DeferredTaxAssetsValuationAllowance=[
            inst("2025-09-30", 45e9, form="10-Q", accn="q325", filed="2025-11-01")],
    )
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_an_ordinary_deferred_share_says_nothing():
    """KO's FY2025: 517M deferred inside a 2,861M charge."""
    gaap = deferred_tax_gaap()
    annual_10k("IncomeTaxExpenseBenefit", {2025: 2861e6}, gaap)
    annual_10k("DeferredIncomeTaxExpenseBenefit", {2025: 517e6}, gaap)
    assert not any("income tax charge" in n for n in texts(build(gaap)))


def test_one_split_restated_past_three_quarters_is_still_one_split():
    """Lam Research's 10:1 of October 2024 reaches Company Facts one comparative at a
    time — 2024-10-28, 2025-01-31, 2025-04-25, then the FY2025 10-K of 2025-08-11, 287
    days after the run began. Anchoring the run to its first filing rather than its
    latest observation books a second 10:1, and FY2022 — which no filing ever restated,
    because it had fallen out of the comparative window — came out divided by 100."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        _yr(2022, 32.75, "2024-08-29", "k24"), _yr(2023, 33.21, "2024-08-29", "k24"),
        _yr(2023, 3.32, "2025-08-11", "k25"), _yr(2024, 2.90, "2025-08-11", "k25"),
        dur("2022-09-26", "2022-12-25", 12.00, form="10-Q", accn="qa", filed="2023-01-25"),
        dur("2022-09-26", "2022-12-25", 1.20, form="10-Q", accn="qa2", filed="2024-10-28"),
        dur("2022-12-26", "2023-03-26", 13.00, form="10-Q", accn="qb", filed="2023-04-26"),
        dur("2022-12-26", "2023-03-26", 1.30, form="10-Q", accn="qb2", filed="2025-01-31"),
        dur("2023-03-27", "2023-06-25", 14.00, form="10-Q", accn="qc", filed="2023-07-26"),
        dur("2023-03-27", "2023-06-25", 1.40, form="10-Q", accn="qc2", filed="2025-04-25"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        _shares(2023, 132e6, "2024-08-29", "k24"), _shares(2023, 1320e6, "2025-08-11", "k25"),
    ])
    s = build(gaap)
    assert round(float(s.annual_eps[2022].value), 4) == 3.275   # 32.75 / 10, never / 100
    assert float(s.annual_eps[2023].value) == 3.32


def test_a_cent_level_revision_is_not_a_split():
    """Idaho Copper restated a -0.02 quarter to -0.01. The ratio lands on a split
    candidate, but a one-cent move on a two-cent figure is rounding, and the engine
    rescaled the company's whole pre-2021 record by a third."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        _yr(2013, -0.11, "2015-03-30", "k14"),
        dur("2020-01-01", "2020-03-31", -0.02, form="10-Q", accn="qa", filed="2020-05-10"),
        dur("2020-01-01", "2020-03-31", -0.01, form="10-Q", accn="qa2", filed="2021-05-10"),
        _yr(2024, -0.03, "2025-03-30", "k24"),
    ])
    assert float(build(gaap).annual_eps[2013].value) == -0.11


def test_another_registrants_statements_are_not_a_split():
    """Essential Utilities' own 10-K reports FY2024 diluted EPS of 2.17 on 274.4M shares.
    An 8-K filed under the same CIK carries a different entity's audited statements: 5.39
    on 195M shares. The earnings ratio lands within 0.7% of a 1-for-2.5 reverse split; the
    share counts moved 1.41x and refute it outright."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        _yr(2024, 2.17, "2026-02-26", "k25"), _yr(2025, 2.20, "2026-02-26", "k25"),
        _yr(2024, 5.39, "2026-03-25", "8k"), _yr(2025, 5.69, "2026-03-25", "8k"),
    ])
    gaap["EarningsPerShareDiluted"]["units"]["USD/shares"][2]["form"] = "8-K"
    gaap["EarningsPerShareDiluted"]["units"]["USD/shares"][3]["form"] = "8-K"
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        _shares(2024, 274421000, "2026-02-26", "k25"),
        dict(_shares(2024, 195000000, "2026-03-25", "8k"), form="8-K"),
    ])
    s = build(gaap)
    assert float(s.annual_eps[2025].value) == 2.20   # not 5.50
    assert float(s.annual_eps[2024].value) == 2.17


def test_a_small_conversion_right_is_not_worth_a_note():
    """The same 5% floor the warrant note uses: an overhang that cannot move a
    per-share figure meaningfully is noise on the page, not a disclosure."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 20e9, accn="q126")])
    gaap["ConvertiblePreferredStockSharesIssuedUponConversion"] = tagdata("shares", [
        inst("2026-03-31", 1e8, accn="q126")])          # 0.5%
    s = build(gaap)
    assert not any(n["kind"] == "Convertible preferred" for n in s.context_notes)


def test_options_outstanding_are_read_against_the_count_they_dilute():
    """A share count says who owns the company today; the option pool says how much
    of it is already promised to someone else."""
    gaap = dict(GAAP) | {
        "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 100e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber":
            tagdata("shares", [inst("2026-03-31", 6e6, accn="q126")]),
    }
    s = build(gaap)
    assert float(s.options_outstanding.value) == 6e6


def test_a_filer_that_grants_no_options_reports_none_rather_than_zero():
    """Apple, Microsoft and Nvidia tag no option count in Company Facts or in the
    quarterly datasets — they grant restricted stock. §5.1: that is silence about
    options, and a panel showing 0% would be asserting something no filing says."""
    s = build(GAAP)
    assert s.options_outstanding is None


def test_restricted_stock_joins_the_options_in_one_overhang():
    """Both promise shares to employees and dilute the same holders, so they are one
    figure. What differs is that an option needs a rising price to be worth anything
    and a restricted share does not."""
    gaap = dict(GAAP) | {
        "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 100e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber":
            tagdata("shares", [inst("2026-03-31", 6e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber":
            tagdata("shares", [inst("2026-03-31", 3e6, accn="q126")]),
    }
    s = build(gaap)
    assert float(s.options_outstanding.value) == 6e6
    assert float(s.rsus_outstanding.value) == 3e6


def test_each_award_kind_is_judged_against_the_share_count_on_its_own():
    """A mis-tagged options figure must not take a sound RSU figure down with it."""
    gaap = dict(GAAP) | {
        "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 10e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber":
            tagdata("shares", [inst("2026-03-31", 3.2e9, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber":
            tagdata("shares", [inst("2026-03-31", 1e6, accn="q126")]),
    }
    s = build(gaap)
    assert s.options_outstanding is None
    assert float(s.rsus_outstanding.value) == 1e6


def test_an_option_pool_bigger_than_the_company_is_a_tagging_error():
    """Greenlane's pool reads 235,000 one quarter and 235,000,000 the next, and
    Zerocarbon reports 3.2bn options against 10.4M shares. A company cannot have
    granted away more than all of itself, so the figure is withheld rather than
    shipped as a 31,000% overhang."""
    gaap = dict(GAAP) | {
        "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 10e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber":
            tagdata("shares", [inst("2026-03-31", 3.2e9, accn="q126")]),
    }
    assert build(gaap).options_outstanding is None


def test_a_pool_that_fits_inside_the_count_is_kept():
    """The guard is a ceiling on the absurd, not a haircut on real dilution: at the
    99th percentile a genuine overhang is still 72%."""
    gaap = dict(GAAP) | {
        "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 10e6, accn="q126")]),
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber":
            tagdata("shares", [inst("2026-03-31", 7.2e6, accn="q126")]),
    }
    assert float(build(gaap).options_outstanding.value) == 7.2e6
