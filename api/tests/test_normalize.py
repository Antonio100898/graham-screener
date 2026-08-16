"""Normaliser tests against synthetic companyfacts JSON."""
from datetime import date
from decimal import Decimal

import pytest

from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot


def dur(start, end, val, form="10-K", accn="k-0", filed="2026-02-15"):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form,
            "filed": filed, "fy": 0, "fp": "FY"}


def inst(end, val, form="10-Q", accn="q-0", filed="2026-05-05"):
    return {"end": end, "val": val, "accn": accn, "form": form, "filed": filed,
            "fy": 0, "fp": "Q1"}


def tagdata(unit, entries):
    return {"units": {unit: entries}}


def facts_doc(gaap=None, dei=None):
    return {"facts": {"us-gaap": gaap or {}, "dei": dei or {}}}


EPS = [
    dur("2021-01-01", "2021-12-31", 3.0, accn="k21", filed="2022-02-15"),
    dur("2022-01-01", "2022-12-31", 3.5, accn="k22", filed="2023-02-15"),
    dur("2023-01-01", "2023-12-31", 4.0, accn="k23", filed="2024-02-15"),
    dur("2023-01-01", "2023-12-31", 4.1, accn="k24", filed="2025-02-15"),  # restated in FY2024 10-K
    dur("2024-01-01", "2024-12-31", 5.0, accn="k24", filed="2025-02-15"),
    dur("2025-01-01", "2025-12-31", 6.0, accn="k25", filed="2026-02-15"),
    dur("2026-01-01", "2026-03-31", 1.6, form="10-Q", accn="q126", filed="2026-05-05"),
    dur("2025-01-01", "2025-03-31", 1.4, form="10-Q", accn="q125", filed="2025-05-05"),
]

GAAP = {
    "EarningsPerShareDiluted": tagdata("USD/shares", EPS),
    "AssetsCurrent": tagdata("USD", [
        inst("2025-12-31", 280e9, form="10-K", accn="k25", filed="2026-02-15"),
        inst("2026-03-31", 300e9, accn="q126"),
    ]),
    "LiabilitiesCurrent": tagdata("USD", [inst("2026-03-31", 150e9, accn="q126")]),
    "Assets": tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")]),
    "Liabilities": tagdata("USD", [inst("2026-03-31", 400e9, accn="q126")]),
    "Goodwill": tagdata("USD", [inst("2025-12-31", 50e9, form="10-K", accn="k25", filed="2026-02-15")]),
    "IntangibleAssetsNetExcludingGoodwill": tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")]),
    "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 10e9, accn="q126")]),
    "PaymentsOfDividendsCommonStock": tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05"),
    ]),
}


def build(gaap=GAAP):
    return build_snapshot("TEST", "0000000001", facts_doc(gaap))


def test_annual_eps_from_10k_only_latest_filed_wins():
    s = build()
    assert {y: float(f.value) for y, f in s.annual_eps.items()} == {
        2021: 3.0, 2022: 3.5, 2023: 4.1, 2024: 5.0, 2025: 6.0,
    }
    # restated FY2023 traces to the later filing
    assert s.annual_eps[2023].provenance.accession == "k24"
    # quarterly facts are never promoted to annual figures
    assert 2026 not in s.annual_eps


def test_ttm_is_annual_plus_ytd_delta():
    s = build()
    assert s.ttm_eps == Decimal("6.0") + Decimal("1.6") - Decimal("1.4")
    assert len(s.ttm_eps_inputs) == 3
    forms = [f.provenance.form for f in s.ttm_eps_inputs]
    assert forms == ["10-K", "10-Q", "10-Q"]


def test_ttm_falls_back_to_annual_when_no_newer_quarter():
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", EPS[:6])  # 10-K facts only
    s = build(gaap)
    assert s.ttm_eps == Decimal("6.0")
    assert len(s.ttm_eps_inputs) == 1


def test_balance_sheet_uses_latest_period_end():
    s = build()
    assert float(s.current_assets.value) == 300e9
    assert s.current_assets.provenance.period_end == date(2026, 3, 31)
    assert s.balance_sheet_date == date(2026, 3, 31)
    # goodwill only reported annually -> its own latest instant
    assert s.goodwill.provenance.period_end == date(2025, 12, 31)


def test_missing_stays_missing():
    s = build()
    assert s.preferred_stock is None
    assert s.long_term_debt is None


def test_stale_instant_fact_treated_as_missing():
    # filer stopped reporting Goodwill years ago -> the old fact must not resurface
    gaap = dict(GAAP)
    gaap["Goodwill"] = tagdata("USD", [
        inst("2017-12-30", 5.9e9, form="10-Q", accn="q417", filed="2018-02-02"),
    ])
    assert build(gaap).goodwill is None


def test_dividend_recent_positive_payment():
    s = build()
    assert s.pays_dividend is True
    assert s.dividend.provenance.tag == "us-gaap:PaymentsOfDividendsCommonStock"


def test_no_dividend_facts_means_not_paying():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    assert build(gaap).pays_dividend is False


def test_stale_dividend_means_not_paying():
    gaap = dict(GAAP)
    gaap["PaymentsOfDividendsCommonStock"] = tagdata("USD", [
        dur("2022-01-01", "2022-03-31", 2e9, form="10-Q", accn="q122", filed="2022-05-05"),
    ])
    assert build(gaap).pays_dividend is False


def test_liabilities_derived_from_equity_identity():
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 600e9, accn="q126")])
    s = build(gaap)
    assert float(s.total_liabilities.value) == 400e9
    assert "derived" in s.total_liabilities.provenance.concept


def test_liabilities_not_derived_across_mismatched_dates():
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2025-12-31", 600e9, form="10-K", accn="k25", filed="2026-02-15")])
    assert build(gaap).total_liabilities is None


def test_intangibles_summed_from_finite_and_indefinite():
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["FiniteLivedIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 20e9, accn="q126")])
    gaap["IndefiniteLivedIntangibleAssetsExcludingGoodwill"] = tagdata("USD", [inst("2026-03-31", 10e9, accn="q126")])
    s = build(gaap)
    assert float(s.intangibles.value) == 30e9
    assert "FiniteLived" in s.intangibles.provenance.tag
    assert "IndefiniteLived" in s.intangibles.provenance.tag


def test_sum_includes_components_with_different_period_ends():
    # dropping the older-but-fresh component would understate debt -> false PASS risk
    gaap = dict(GAAP)
    gaap["LongTermDebtCurrent"] = tagdata("USD", [
        inst("2025-12-31", 11e9, form="10-K", accn="k25", filed="2026-02-15")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    s = build(gaap)
    assert float(s.short_term_debt.value) == 13e9
    assert s.short_term_debt.provenance.period_end == date(2026, 3, 31)


def test_staleness_guard_armed_without_assets_tag():
    # filer never tags Assets: LiabilitiesAndStockholdersEquity (== total assets by
    # identity) must anchor the guard so ancient facts cannot resurface
    gaap = {k: v for k, v in GAAP.items() if k != "Assets"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["Goodwill"] = tagdata("USD", [inst("2017-12-30", 5.9e9, form="10-Q", accn="q417", filed="2018-02-02")])
    s = build(gaap)
    assert float(s.total_assets.value) == 1000e9
    assert s.goodwill is None  # 2017 fact stays dead


def test_basic_eps_fills_year_diluted_chain_lacks():
    # Lennar FY2025 pattern: the newest 10-K tags only EarningsPerShareBasic.
    # Without the fill the series freezes a year back and stales criteria 4/6 + TTM.
    diluted = [dur(f"{y}-01-01", f"{y}-12-31", 14.31, accn=f"d{y}", filed=f"{y + 1}-01-26")
               for y in range(2020, 2025)]
    basic = diluted + [dur("2025-01-01", "2025-12-31", 7.98, accn="b25", filed="2026-01-28")]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", diluted)
    gaap["EarningsPerShareBasic"] = tagdata("USD/shares", basic)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    assert float(s.annual_eps[2025].value) == 7.98
    assert "basic" in s.annual_eps[2025].provenance.concept
    # years the diluted chain covers keep their diluted values
    assert "basic" not in s.annual_eps[2024].provenance.concept


def test_current_continuing_series_beats_longer_dead_plain_series():
    # FCX pattern: EarningsPerShareDiluted stopped in 2021 (15 years of history),
    # continuing-ops runs through 2025 with fewer years — recency must win
    plain = [dur(f"{y}-01-01", f"{y}-12-31", 1.0, accn=f"p{y}", filed=f"{y + 1}-02-15")
             for y in range(2007, 2022)]
    cont = [dur(f"{y}-01-01", f"{y}-12-31", 2.0, accn=f"c{y}", filed=f"{y + 1}-02-15")
            for y in range(2013, 2026)]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", plain)
    gaap["IncomeLossFromContinuingOperationsPerDilutedShare"] = tagdata("USD/shares", cont)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    assert "ContinuingOperations" in s.annual_eps[2025].provenance.tag


def test_stale_continuing_ops_series_not_preferred():
    cont = [dur(f"{y}-01-01", f"{y}-12-31", 1.0, accn=f"c{y}", filed=f"{y + 1}-02-15")
            for y in (2015, 2016, 2017, 2018, 2019)]
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsPerDilutedShare"] = tagdata("USD/shares", cont)
    s = build(gaap)
    assert max(s.annual_eps) == 2025  # current diluted series wins over stale continuing-ops


def test_long_term_debt_total_tag_not_double_counted_in_short_bucket():
    gaap = dict(GAAP)
    gaap["LongTermDebt"] = tagdata("USD", [inst("2026-03-31", 100e9, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 11e9, accn="q126")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 100e9  # includes current maturities already
    assert float(s.short_term_debt.value) == 2e9  # only genuine short-term borrowings


def test_overlapping_period_never_invents_a_later_year():
    # A fiscal-year change leaves two annual periods overlapping in the same year.
    # Pushing the second one to the next label invents a year that has not happened;
    # the framed period wins and the overlap is dropped instead.
    eps = [
        {**dur("2021-07-01", "2022-06-30", -1.0, accn="k22a", filed="2022-09-15"),
         "frame": "CY2022"},
        dur("2021-10-01", "2022-09-30", 2.0, accn="k22b", filed="2023-01-15"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2022]
    assert float(s.annual_eps[2022].value) == -1.0  # SEC's own label is authoritative


def test_label_never_lands_after_the_year_the_period_ends_in():
    # Tyson pattern: many old unframed years ahead of a few framed recent ones.
    # Inference used to cascade forward and label a Sept-2025 year as FY2027.
    eps = [dur(f"{y}-10-01", f"{y + 1}-09-28", 1.0 + y % 3, accn=f"k{y}",
               filed=f"{y + 1}-11-15") for y in range(2010, 2023)]
    eps.append({**dur("2024-09-29", "2025-09-27", 1.33, accn="k25", filed="2025-11-14"),
                "frame": "CY2025"})
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    for fy, fact in s.annual_eps.items():
        end_year = fact.provenance.period_end.year
        assert end_year - 1 <= fy <= end_year, f"FY{fy} labels a period ending {end_year}"


def test_unchained_dividend_tag_gives_unknown_not_false():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DividendsDeclaredButUnpaid"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is None  # unknown, never a confident FAIL


def test_nci_extracted_when_liabilities_are_direct():
    gaap = dict(GAAP)
    gaap["MinorityInterest"] = tagdata("USD", [inst("2026-03-31", 6.6e9, accn="q126")])
    s = build(gaap)
    assert float(s.noncontrolling_interest.value) == 6.6e9


def test_nci_skipped_when_liabilities_derived_via_parent_equity():
    # L = L&SE - parent-only StockholdersEquity already leaves NCI inside liabilities;
    # deducting MinorityInterest again would double-count
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 600e9, accn="q126")])
    gaap["MinorityInterest"] = tagdata("USD", [inst("2026-03-31", 6.6e9, accn="q126")])
    s = build(gaap)
    assert s.noncontrolling_interest is None


def test_suspended_quarterly_payer_fails_within_two_quarters():
    # last positive quarterly dividend ended two quarters before the balance sheet
    gaap = dict(GAAP)
    gaap["PaymentsOfDividendsCommonStock"] = tagdata("USD", [
        dur("2025-07-01", "2025-09-30", 2e9, form="10-Q", accn="q325", filed="2025-11-05")])
    assert build(gaap).pays_dividend is False


def test_annual_cadence_dividend_still_current():
    # filer tags dividends only in the 10-K: a full-year fact ending a quarter ago is current
    gaap = dict(GAAP)
    gaap["PaymentsOfDividendsCommonStock"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 8e9, form="10-K", accn="k25", filed="2026-02-15")])
    assert build(gaap).pays_dividend is True


def test_common_specific_dividend_tag_preferred_over_aggregate():
    gaap = dict(GAAP)
    gaap["PaymentsOfDividends"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 9e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)  # GAAP already has PaymentsOfDividendsCommonStock
    assert s.dividend.provenance.tag.endswith("PaymentsOfDividendsCommonStock")
    assert "common stock" in s.dividend.provenance.concept


def test_aggregate_dividend_tag_is_labelled_as_such():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["PaymentsOfDividends"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 9e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is True
    assert "aggregate" in s.dividend.provenance.concept


def test_inbound_dividends_are_not_payer_evidence():
    # dividends RECEIVED from equity-method investees (INTC/BRK pattern) must not
    # soften a non-payer's confident False into unknown
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["EquityMethodInvestmentDividendsOrDistributions"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 4e8, form="10-Q", accn="q126", filed="2026-05-05")])
    assert build(gaap).pays_dividend is False


def test_widened_dividend_chain_tag_detected():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DividendsCommonStockCash"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    assert build(gaap).pays_dividend is True


def test_weighted_diluted_shares_fallback():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 9.9e9, form="10-Q", accn="q126", filed="2026-05-05"),  # quarter
        dur("2025-04-01", "2026-03-31", 9.5e9, form="10-Q", accn="q126", filed="2026-05-05"),  # trailing yr
    ])
    s = build(gaap)
    assert float(s.shares_outstanding.value) == 9.9e9  # shortest duration wins
    assert "proxy" in s.shares_outstanding.provenance.concept


def test_debt_capital_lease_obligation_tags():
    gaap = dict(GAAP)
    gaap["LongTermDebtAndCapitalLeaseObligations"] = tagdata("USD", [inst("2026-03-31", 40e9, accn="q126")])
    gaap["DebtCurrent"] = tagdata("USD", [inst("2026-03-31", 5e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 40e9
    assert float(s.short_term_debt.value) == 5e9


def test_bank_without_classified_balance_sheet():
    gaap = {k: v for k, v in GAAP.items() if k not in ("AssetsCurrent", "LiabilitiesCurrent")}
    s = build(gaap)
    assert s.current_assets is None
    assert s.current_liabilities is None
    assert s.total_assets is not None


def test_foreign_filer_rejected():
    gaap = {"Assets": tagdata("USD", [inst("2025-12-31", 1e9, form="20-F")])}
    with pytest.raises(UnsupportedFilerError):
        build(gaap)


def test_frame_field_labels_comparative_only_years():
    # RDDT-style: pre-IPO 2022 exists only as a comparative (fy overshoots to 2024)
    # but SEC's frame field still labels it CY2022
    eps = [
        {**dur("2022-01-01", "2022-12-31", 1.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2022"},
        {**dur("2023-01-01", "2023-12-31", 2.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2023"},
        {**dur("2024-01-01", "2024-12-31", 3.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2024"},
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2022, 2023, 2024]


def test_frameless_end_filled_from_nearest_framed_neighbor():
    eps = [
        {**dur("2022-01-01", "2022-12-31", 1.0, accn="k22", filed="2023-02-15"), "fy": 2022},
        {**dur("2023-01-01", "2023-12-31", 2.0, accn="k23", filed="2024-02-15"),
         "fy": 2023, "frame": "CY2023"},
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    assert sorted(build(gaap).annual_eps) == [2022, 2023]


def test_preferred_liquidation_preference_wins_over_par():
    gaap = dict(GAAP)
    gaap["PreferredStockValue"] = tagdata("USD", [inst("2026-03-31", 1e6, accn="q126")])
    gaap["PreferredStockLiquidationPreferenceValue"] = tagdata("USD", [inst("2026-03-31", 21.2e9, accn="q126")])
    s = build(gaap)
    assert float(s.preferred_stock.value) == 21.2e9
    assert "LiquidationPreference" in s.preferred_stock.provenance.tag


def test_debt_components_summed_dds_style():
    # no primary long-term tag: "other" LTD + subordinated debentures must sum
    gaap = dict(GAAP)
    gaap["OtherLongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 225.7e6, accn="q126")])
    gaap["JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent"] = tagdata(
        "USD", [inst("2026-03-31", 200e6, accn="q126")])
    gaap["UnsecuredDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 96e6, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 425.7e6
    assert "sum of components" in s.long_term_debt.provenance.concept
    assert float(s.short_term_debt.value) == 96e6


def test_short_debt_sums_current_portion_and_commercial_paper():
    # AAPL-style: term debt current + commercial paper are separate lines
    gaap = dict(GAAP)
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 11e9, accn="q126")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    s = build(gaap)
    assert float(s.short_term_debt.value) == 13e9


def test_total_debt_rollup_tag_extracted():
    gaap = dict(GAAP)
    gaap["DebtAndCapitalLeaseObligations"] = tagdata("USD", [inst("2026-03-31", 1.94e9, accn="q126")])
    assert float(build(gaap).total_debt.value) == 1.94e9


def test_assume_absent_zero_requires_opt_in_and_clean_history():
    gaap = {k: v for k, v in GAAP.items() if k not in ("Goodwill",)}
    # default: strict, nothing assumed
    assert build_snapshot("TEST", "0000000001", facts_doc(gaap)).assumed_zero == frozenset()
    # opt-in: debt + goodwill have zero evidence anywhere -> assumable
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), assume_absent_zero=True)
    assert s.assumed_zero == {"debt", "goodwill"}


def test_assume_zero_blocked_by_debt_evidence():
    # a material debt-instrument fact anywhere in history blocks the assumption
    gaap = dict(GAAP)
    gaap["UnsecuredDebt"] = tagdata("USD", [inst("2018-12-31", 500e6, form="10-K", accn="k18", filed="2019-02-15")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), assume_absent_zero=True)
    assert "debt" not in s.assumed_zero


def test_asset_side_debt_securities_are_not_debt_evidence():
    # investments in debt securities and undrawn revolver capacity are not liabilities
    gaap = dict(GAAP)
    gaap["AvailableForSaleSecuritiesDebtSecurities"] = tagdata("USD", [inst("2026-03-31", 7.6e9, accn="q126")])
    gaap["LineOfCreditFacilityMaximumBorrowingCapacity"] = tagdata("USD", [inst("2026-03-31", 800e6, accn="q126")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), assume_absent_zero=True)
    assert "debt" in s.assumed_zero


def test_fiscal_year_label_january_end_belongs_to_prior_year():
    assert _fy_label(date(2026, 1, 31)) == 2025
    assert _fy_label(date(2025, 9, 27)) == 2025


def test_retail_fiscal_years_use_filers_own_fy_labels():
    # Target-style calendar: year end floats across the Jan/Feb boundary. A pure
    # calendar heuristic mislabels the Feb-ending years; the fy field must win.
    def kdur(start, end, val, fy, filed):
        return {**dur(start, end, val, accn=f"k{fy}", filed=filed), "fy": fy}

    eps = [
        kdur("2021-01-31", "2022-01-29", 2.0, 2021, "2022-03-09"),
        kdur("2022-01-30", "2023-01-28", 2.5, 2022, "2023-03-08"),
        kdur("2023-01-29", "2024-02-03", 3.0, 2023, "2024-03-13"),  # 53-week, ends in Feb
        kdur("2024-02-04", "2025-02-01", 3.5, 2024, "2025-03-12"),  # ends in Feb
        kdur("2025-02-02", "2026-01-31", 4.0, 2025, "2026-03-11"),
        # FY2023 comparative inside the FY2025 10-K: fy overshoots -> min() must keep 2023
        kdur("2023-01-29", "2024-02-03", 3.1, 2025, "2026-03-11"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2021, 2022, 2023, 2024, 2025]
    assert float(s.annual_eps[2023].value) == 3.1  # restated value, original label


def test_ttm_refuses_to_mix_pre_and_post_ipo_share_counts():
    """A per-share figure struck on 50M shares cannot be subtracted from one struck
    on 283M. Caris Life Sciences produced +9.58 that way, out of three loss years."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", -3.22, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", 0.0, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -12.80, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-06-30", 283e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 50e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("-3.22"), "must fall back to the audited annual figure"
    assert len(s.ttm_eps_inputs) == 1


def test_ttm_composite_survives_ordinary_buybacks():
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 6.0, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", 3.4, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 3.0, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-06-30", 94e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 100e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("6.4"), "a 6% buyback is normal and must not block the composite"
    assert len(s.ttm_eps_inputs) == 3


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


def test_net_income_follows_a_tag_switch_forward():
    """Advanced Energy stopped tagging NetIncomeLoss after 2024 and continued under
    ProfitLoss. Taking the first tag that returns anything freezes the series."""
    old = [dur(f"{y}-01-01", f"{y}-12-31", 50e6, accn=f"k{y}", filed=f"{y + 1}-02-18")
           for y in range(2018, 2025)]
    new = [dur(f"{y}-01-01", f"{y}-12-31", 60e6, accn=f"p{y}", filed=f"{y + 1}-02-18")
           for y in range(2020, 2026)]
    gaap = dict(GAAP)
    gaap["NetIncomeLoss"] = tagdata("USD", old)
    gaap["ProfitLoss"] = tagdata("USD", new)
    s = build(gaap)
    assert max(s.annual_net_income) == 2025, "must follow the series that is still current"
    assert 2018 in s.annual_net_income, "older years from the dropped tag are kept"


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


OE_GAAP = {
    **GAAP,
    "OperatingIncomeLoss": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e9, accn="k25", filed="2026-02-15")]),
    "DepreciationDepletionAndAmortization": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15")]),
    "IncomeTaxExpenseBenefit": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 20e9, accn="k25", filed="2026-02-15")]),
    "PaymentsToAcquirePropertyPlantAndEquipment": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15")]),
    "CashAndCashEquivalentsAtCarryingValue": tagdata("USD", [
        inst("2026-03-31", 40e9, accn="q126")]),
}


def test_owner_earnings_and_invested_capital():
    s = build(OE_GAAP)
    oe = s.owner_earnings
    # 100 + 12 - 20 - 12
    assert float(oe.owner_earnings) == 80e9
    # assets 1000 - cash 40 - non-interest-bearing current liabilities 150
    assert float(oe.invested_capital) == 810e9
    assert round(float(oe.roic), 4) == round(80 / 810 * 100, 4)
    # with maintenance capex assumed equal to depreciation the two cancel: 100 - 20
    assert round(float(oe.roic_maintenance), 4) == round(80 / 810 * 100, 4)


def test_interest_bearing_current_debt_stays_in_invested_capital():
    """Only what suppliers and employees fund is netted off; borrowed money is capital."""
    gaap = {**OE_GAAP, "DebtCurrent": tagdata("USD", [inst("2026-03-31", 50e9, accn="q126")])}
    s = build(gaap)
    # current liabilities 150 less 50 of debt leaves 100 of non-interest-bearing funding
    assert float(s.owner_earnings.invested_capital) == 860e9


def test_depreciation_series_survives_a_tag_change_midway():
    """A filer that drops the combined tag keeps reporting the parts; the series must
    follow rather than freeze at the year of the change."""
    gaap = {k: v for k, v in OE_GAAP.items() if k != "DepreciationDepletionAndAmortization"}
    gaap["DepreciationDepletionAndAmortization"] = tagdata("USD", [
        dur("2021-01-01", "2021-12-31", 5e9, accn="k21", filed="2022-02-15")])
    gaap["Depreciation"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 9e9, accn="k25", filed="2026-02-15")])
    gaap["AmortizationOfIntangibleAssets"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 3e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert oe.fiscal_year == 2025          # not 2021, where the combined tag stopped
    assert float(oe.owner_earnings) == 80e9  # 100 + (9+3) - 20 - 12


def test_pretax_income_stands_in_when_no_operating_subtotal():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "OperatingIncomeLoss"}
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2025-01-01", "2025-12-31", 90e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 70e9  # 90 + 12 - 20 - 12
    assert any("pre-tax" in c for c in oe.caveats)


def test_no_classified_balance_sheet_yields_earnings_without_a_return():
    """Banks report no current liabilities, so invested capital cannot be separated —
    the earnings still compute, the ratio does not."""
    gaap = {k: v for k, v in OE_GAAP.items() if k != "LiabilitiesCurrent"}
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 80e9
    assert oe.invested_capital is None and oe.roic is None


def test_non_december_filer_keeps_its_own_fiscal_year_label():
    """Dorian LPG pattern: SEC frames a March-ending year by the calendar year it
    mostly falls in, one behind the fiscal year the filer reports. Honouring the frame
    shifted EPS a year against net income — which carries no frames at all — and the
    two series stopped describing the same period."""
    def mar(y, val, filed, frame=None):
        e = dur(f"{y - 1}-04-01", f"{y}-03-31", val, accn=f"k{y}", filed=filed)
        return {**e, "fy": y, **({"frame": f"CY{y - 1}"} if frame else {})}

    eps = [mar(2024, 7.6, "2024-05-29", frame=True),
           mar(2025, 2.14, "2025-05-29", frame=True),
           mar(2026, 4.54, "2026-05-27", frame=True)]
    ni = [mar(2024, 307e6, "2024-05-29"),   # net income is framed by nobody
          mar(2025, 90e6, "2025-05-29"),
          mar(2026, 193e6, "2026-05-27")]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    gaap["NetIncomeLoss"] = tagdata("USD", ni)
    s = build(gaap)
    assert sorted(s.annual_eps)[-3:] == [2024, 2025, 2026]
    # the pair must describe one period: implied share count stays put across years
    for y in (2024, 2025, 2026):
        implied = float(s.annual_net_income[y].value) / float(s.annual_eps[y].value)
        assert 38e6 < implied < 46e6, f"FY{y} implies {implied:,.0f} shares"


def _yr(y, val, filed, accn):
    return dur(f"{y}-01-01", f"{y}-12-31", val, accn=accn, filed=filed)


def test_split_rebases_years_the_filer_never_restated():
    """Chipotle pattern. A 50:1 split restates only the comparatives the newest 10-K
    carries; older years keep a figure struck on a share count that no longer exists,
    and criterion 6 compares straight across that discontinuity."""
    eps = [
        _yr(2020, 12.52, "2021-02-10", "k20"),
        _yr(2021, 22.90, "2022-02-11", "k21"),
        _yr(2022, 32.04, "2023-02-09", "k22"),      # as filed, pre-split
        _yr(2022, 0.64, "2025-02-05", "k24"),       # restated in the post-split 10-K
        _yr(2023, 0.89, "2025-02-05", "k24"),
        _yr(2024, 1.11, "2025-02-05", "k24"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2020].value), 4) == 0.2504   # 12.52 / 50
    assert round(float(s.annual_eps[2021].value), 4) == 0.458
    assert float(s.annual_eps[2024].value) == 1.11               # already post-split


def test_one_split_restated_across_two_filings_is_counted_once():
    """Booking Holdings pattern: successive 10-Qs each restate a different period onto
    the same new basis. Treating those as separate events squared 25:1 into 625."""
    eps = [
        _yr(2023, 100.0, "2024-02-01", "k23"),
        _yr(2024, 120.0, "2025-02-01", "k24"),
        dur("2025-01-01", "2025-06-30", 37.38, form="10-Q", accn="q225", filed="2025-08-01"),
        dur("2025-01-01", "2025-06-30", 1.4952, form="10-Q", accn="q226", filed="2026-08-01"),
        dur("2025-01-01", "2025-03-31", 20.0, form="10-Q", accn="q125", filed="2025-05-01"),
        dur("2025-01-01", "2025-03-31", 0.80, form="10-Q", accn="q126", filed="2026-05-01"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2023].value), 4) == 4.0      # 100 / 25, not / 625
    assert round(float(s.annual_eps[2024].value), 4) == 4.8


def test_two_genuine_splits_a_year_apart_both_apply():
    """Texas Pacific Land split 3:1 twice. Collapsing them would leave the oldest years
    understated by a factor of three."""
    eps = [
        _yr(2021, 90.0, "2022-02-01", "k21"),
        _yr(2022, 57.77, "2023-02-01", "k22"),
        _yr(2022, 19.26, "2025-02-01", "k24"),      # first 3:1
        _yr(2023, 17.59, "2025-02-01", "k24"),
        _yr(2023, 5.86, "2026-02-01", "k25"),       # second 3:1
        _yr(2024, 6.57, "2026-02-01", "k25"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2021].value), 2) == 10.0     # 90 / 9
    assert round(float(s.annual_eps[2024].value), 2) == 6.57


def test_a_quarter_and_a_year_to_date_closing_together_are_not_a_split():
    """Both end on the same day and differ threefold by length alone; comparing them
    across periods rather than within one would read a 3:1 split that never happened."""
    eps = [
        _yr(2024, 4.0, "2025-02-01", "k24"),
        _yr(2025, 5.0, "2026-02-01", "k25"),
        dur("2026-07-01", "2026-09-30", 1.0, form="10-Q", accn="q326", filed="2026-11-01"),
        dur("2026-01-01", "2026-09-30", 3.0, form="10-Q", accn="q326", filed="2026-11-01"),
        dur("2025-01-01", "2025-09-30", 2.7, form="10-Q", accn="q325", filed="2025-11-01"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert float(s.annual_eps[2024].value) == 4.0    # untouched
    assert s.ttm_eps == Decimal("5.0") + Decimal("3.0") - Decimal("2.7")


def test_income_tax_benefit_is_added_back_not_charged():
    """IncomeTaxExpenseBenefit is signed; a net-benefit year files it negative. Forcing
    it positive charged Uber for a benefit it received, twice over."""
    gaap = dict(OE_GAAP)
    gaap["IncomeTaxExpenseBenefit"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -20e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 120e9   # 100 + 12 - (-20) - 12


def test_quarters_dwarfing_their_own_year_are_refused():
    """Taboola tags 220.00 and -40.00 a share in quarters of a year that earned 0.13,
    giving a trailing 260.13 and a price/earnings of 0.02. No corporate action explains
    it, so the audited year stands rather than the composite."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 0.13, accn="k25", filed="2026-02-15"),
        dur("2026-01-01", "2026-06-30", 220.0, form="10-Q", accn="q226", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -40.0, form="10-Q", accn="q225", filed="2025-08-05"),
    ])
    s = build(gaap)
    assert float(s.ttm_eps) == 0.13
    assert len(s.ttm_eps_inputs) == 1


def test_a_real_recovery_off_a_small_base_still_composes():
    """The absolute bound exists so the ratio test cannot veto a genuine turnaround."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 0.05, accn="k25", filed="2026-02-15"),
        dur("2026-01-01", "2026-06-30", 2.10, form="10-Q", accn="q226", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 0.10, form="10-Q", accn="q225", filed="2025-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("0.05") + Decimal("2.10") - Decimal("0.10")


def test_a_dollar_total_tagged_as_earnings_per_share_is_discarded():
    """GRUSF files 243,446,152 into EarningsPerShareDiluted — its net income, not a
    per-share figure. Carried through, a price divided by it passes criterion 1 on a
    price/earnings of nearly zero."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2024-01-01", "2024-12-31", 209441723.0, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 243446152.0, accn="k25", filed="2026-02-15"),
    ])
    s = build(gaap)
    assert s.annual_eps == {}
    assert s.ttm_eps is None
