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


def test_filer_currently_on_foreign_forms_is_rejected():
    """Even with US-GAAP facts: foreign balance sheets trail the domestic cadence."""
    foreign_gaap = {
        tag: tagdata(unit, [
            {**entry, "form": "20-F" if entry["form"].startswith("10-K") else "6-K"}
            for entry in entries
        ])
        for tag, data in GAAP.items()
        for unit, entries in data["units"].items()
    }
    with pytest.raises(UnsupportedFilerError, match="foreign"):
        build(foreign_gaap)


def test_filer_that_moved_to_domestic_forms_keeps_foreign_history():
    """Old 20-F facts stay readable once the newest financial filing is domestic."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        {**EPS[0], "form": "20-F"},  # FY2021 filed 2022 on the pre-transition form
        *EPS[1:],
    ])
    s = build(gaap)
    assert s.annual_eps[2021].provenance.form == "20-F"
    assert float(s.annual_eps[2021].value) == 3.0


def test_foreign_ifrs_facts_remain_explicitly_unsupported():
    facts = {"facts": {"ifrs-full": {
        "Revenue": tagdata("USD", [dur("2025-01-01", "2025-12-31", 1.0, form="20-F")])
    }}}
    with pytest.raises(UnsupportedFilerError, match="IFRS taxonomy"):
        build_snapshot("IFRS", "0000000002", facts)


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


def test_other_intangible_assets_net_is_last_resort():
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["OtherIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 12e9, accn="q126")])
    s = build(gaap)
    assert float(s.intangibles.value) == 12e9
    assert "OtherIntangibleAssetsNet" in s.intangibles.provenance.tag
    # the specific tags win over the ambiguous residual line
    gaap["FiniteLivedIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 20e9, accn="q126")])
    assert float(build(gaap).intangibles.value) == 20e9


def test_combined_goodwill_intangibles_line_fills_both_slots():
    gaap = {k: v for k, v in GAAP.items()
            if k not in ("Goodwill", "IntangibleAssetsNetExcludingGoodwill")}
    gaap["IntangibleAssetsNetIncludingGoodwill"] = tagdata("USD", [inst("2026-03-31", 80e9, accn="q126")])
    s = build(gaap)
    assert float(s.intangibles.value) == 80e9
    assert float(s.goodwill.value) == 0  # contained in the combined line, not missing
    assert "IntangibleAssetsNetIncludingGoodwill" in s.goodwill.provenance.tag


def test_combined_line_never_used_when_goodwill_tagged_separately():
    # goodwill + combined would double-count the goodwill inside the combined line
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["IntangibleAssetsNetIncludingGoodwill"] = tagdata("USD", [inst("2026-03-31", 80e9, accn="q126")])
    s = build(gaap)
    assert float(s.goodwill.value) == 50e9
    assert s.intangibles is None


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


def test_foreign_ifrs_filer_rejected():
    facts = {"facts": {"ifrs-full": {
        "Assets": tagdata("USD", [inst("2025-12-31", 1e9, form="20-F")])
    }}}
    with pytest.raises(UnsupportedFilerError, match="IFRS taxonomy"):
        build_snapshot("IFRS", "0000000003", facts)


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


def test_vintage_ttm_sees_only_what_was_filed():
    from screener.normalize import vintage_ttm_eps
    v = {d: float(x) for d, x in vintage_ttm_eps(GAAP).items()}
    # end of 2025: FY2025's 10-K (filed Feb 2026) is future knowledge; the newest
    # filed figure is FY2024, and Q1'25 has no prior-year comparative to roll with
    assert v["2025-12-31"] == 5.0
    # end of 2024: FY2023 stands at its ORIGINAL 4.0 — the 4.1 restatement was
    # filed in 2025 and must be invisible a year earlier
    assert v["2024-12-31"] == 4.0
    assert v["2022-12-31"] == 3.0   # only the FY2021 10-K existed then
    assert "2021-12-31" not in v    # nothing at all was filed yet


REVENUE = [
    # pre-606 element carries the old years, ending right where the new one begins
    dur("2021-01-01", "2021-12-31", 140e9, accn="k21", filed="2022-02-15"),
    dur("2022-01-01", "2022-12-31", 150e9, accn="k22", filed="2023-02-15"),
    dur("2023-01-01", "2023-12-31", 160e9, accn="k23", filed="2024-02-15"),
]
REVENUE_606 = [
    # ...and the ASC 606 element takes over without overlap
    dur("2024-01-01", "2024-12-31", 180e9, accn="k24", filed="2025-02-15"),
    dur("2025-01-01", "2025-12-31", 200e9, accn="k25", filed="2026-02-15"),
    dur("2026-01-01", "2026-03-31", 60e9, form="10-Q", accn="q126", filed="2026-05-05"),
    dur("2025-01-01", "2025-03-31", 40e9, form="10-Q", accn="q125", filed="2025-05-05"),
]


def test_revenue_series_survives_the_asc606_tag_switch():
    gaap = dict(GAAP)
    gaap["SalesRevenueNet"] = tagdata("USD", REVENUE)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", REVENUE_606)
    s = build(gaap)
    assert {y: f.value for y, f in s.annual_revenue.items()} == {
        2021: 140e9, 2022: 150e9, 2023: 160e9, 2024: 180e9, 2025: 200e9,
    }
    # TTM = FY2025 + Q1'26 - Q1'25
    assert s.ttm_revenue == Decimal("2.2E+11")


def test_no_revenue_tags_leaves_revenue_empty():
    s = build()
    assert s.annual_revenue == {} and s.ttm_revenue is None


def test_operating_income_annual_series():
    gaap = dict(GAAP)
    gaap["OperatingIncomeLoss"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 30e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 35e9, accn="k25", filed="2026-02-15"),
    ])
    s = build(gaap)
    assert {y: f.value for y, f in s.annual_operating_income.items()} == {
        2024: 30e9, 2025: 35e9,
    }


def test_dividend_record_streak_and_interruption():
    gaap = dict(GAAP)
    quarters = []
    for year in (2020, 2021, 2023, 2024, 2025):     # skipped 2022 entirely
        quarters.append(dur(f"{year}-01-01", f"{year}-03-31", 1e8, form="10-Q",
                            accn=f"q{year}", filed=f"{year}-05-05"))
    gaap["PaymentsOfDividendsCommonStock"] = tagdata("USD", quarters)
    s = build(gaap)
    assert s.dividend_record == {"first": 2020, "latest": 2025,
                                 "streak_from": 2023, "paid_years": 5}


def test_bvps_keeps_intangibles_that_tbvps_removes():
    from screener.sync import _bvps, _tbvps
    s = build()
    # assets 1000 - liabilities 400 = 600 over 10B shares
    assert _bvps(s) == 60.0
    # tangible additionally sheds goodwill 50 and intangibles 30
    assert _tbvps(s) == 52.0


def test_revenue_fill_rejects_a_different_scope():
    """ConAgra pattern: umbrella `Revenues` carries a $1.6B sub-scope while the
    goods element holds the true $13B history — the small series must not fill."""
    gaap = dict(GAAP)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 12e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 12.5e9, accn="k25", filed="2026-02-15"),
    ])
    gaap["SalesRevenueGoodsNet"] = tagdata("USD", [
        dur("2022-01-01", "2022-12-31", 13e9, accn="k22", filed="2023-02-15"),
        dur("2023-01-01", "2023-12-31", 11e9, accn="k23", filed="2024-02-15"),
    ])
    gaap["Revenues"] = tagdata("USD", [   # wrong scope, an order of magnitude off
        dur("2022-01-01", "2022-12-31", 1.6e9, accn="k22", filed="2023-02-15"),
        dur("2021-01-01", "2021-12-31", 1.5e9, accn="k21", filed="2022-02-15"),
    ])
    s = build(gaap)
    got = {y: f.value for y, f in s.annual_revenue.items()}
    # goods element joins via the continuous 2023 boundary, then extends to 2022;
    # the umbrella's 1.6B is 8x off its neighbour and 2021 never gets a foothold
    assert got == {2022: 13e9, 2023: 11e9, 2024: 12e9, 2025: 12.5e9}


def test_revenue_fill_refuses_a_disconnected_island():
    gaap = dict(GAAP)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15"),
    ])
    gaap["SalesRevenueNet"] = tagdata("USD", [   # ends three years before the winner starts
        dur("2020-01-01", "2020-12-31", 11e9, accn="k20", filed="2021-02-15"),
    ])
    s = build(gaap)
    # no adjacent year to prove the scopes match, so the island stays out
    assert sorted(s.annual_revenue) == [2025]


def test_stale_zero_on_priority_debt_tag_loses_to_newer_fact():
    """SRI pattern: the filer stopped updating LongTermDebtNoncurrent at a zero;
    the newer figure on a lower-priority tag must win, not the stale zero."""
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2025-09-30", 0, accn="q325", filed="2025-11-05")])
    gaap["LongTermDebt"] = tagdata("USD", [inst("2025-12-31", 180.9e6, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 180.9e6
    assert "LongTermDebt" in s.long_term_debt.provenance.tag


def test_equal_period_ends_keep_chain_priority_for_debt():
    # counterexample: same period end on both tags -> the chain's ranking decides
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["LongTermDebt"] = tagdata("USD", [inst("2026-03-31", 33e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 30e9
    assert s.long_term_debt.provenance.tag == "us-gaap:LongTermDebtNoncurrent"


def test_parent_only_liabilities_derivation_skips_nci():
    """Parent-only equity leaves NCI inside derived liabilities; subtracting
    MinorityInterest again would remove it twice."""
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 590e9, accn="q126")])
    gaap["MinorityInterest"] = tagdata("USD", [inst("2026-03-31", 10e9, accn="q126")])
    s = build(gaap)
    assert float(s.total_liabilities.value) == 410e9  # NCI stays inside
    assert s.noncontrolling_interest is None

    # counterpart: equity INCLUDING NCI keeps NCI out of liabilities -> it must be subtracted
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 600e9, accn="q126")])
    s = build(gaap)
    assert float(s.total_liabilities.value) == 400e9
    assert float(s.noncontrolling_interest.value) == 10e9


def test_da_part_sum_keeps_amortization_only_years_and_names_both_tags():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "DepreciationDepletionAndAmortization"}
    gaap["Depreciation"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 9e9, accn="k25", filed="2026-02-15")])
    gaap["AmortizationOfIntangibleAssets"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 2e9, accn="k24", filed="2025-02-15"),  # amortization-only year
        dur("2025-01-01", "2025-12-31", 3e9, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    oe = s.owner_earnings
    # 2025 (latest shared year): 100 op + (9+3) D&A - 20 tax - 12 capex
    assert float(oe.owner_earnings) == 80e9
    da = dict(oe.components)["+ depreciation & amortisation"]
    assert float(da) == 12e9


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


def test_stale_debt_rollup_loses_to_fresher_parts():
    """SRI: the combined rollup froze a quarter before the parts moved; the
    fresher basis must win, so the stale rollup is dropped entirely."""
    gaap = dict(GAAP)
    gaap["DebtAndCapitalLeaseObligations"] = tagdata("USD", [inst("2025-09-30", 947e3, accn="q325", filed="2025-11-05")])
    gaap["LongTermDebt"] = tagdata("USD", [inst("2025-12-31", 180.9e6, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert s.total_debt is None
    assert float(s.long_term_debt.value) == 180.9e6

    # counterexample: rollup at the same period end as the parts is kept
    gaap["DebtAndCapitalLeaseObligations"] = tagdata("USD", [inst("2025-12-31", 182e6, form="10-K", accn="k25", filed="2026-02-15")])
    assert float(build(gaap).total_debt.value) == 182e6


# --- Release 2, batch A: debt tag families (each fixture names its real-world case) ---

def test_convertible_notes_are_the_whole_debt_ddog_style():
    """DDOG/SNOW: converts under ConvertibleDebtNoncurrent are the only debt."""
    gaap = dict(GAAP)
    gaap["ConvertibleDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 985.5e6, accn="q126")])
    gaap["ConvertibleNotesPayableCurrent"] = tagdata("USD", [inst("2026-03-31", 0, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 985.5e6
    # current convertible slot is a valid zero -> short bucket computable
    assert float(s.short_term_debt.value) == 0


def test_convertible_family_not_added_beside_a_primary_rollup():
    # NOW/AFRM: the rollup already contains the converts
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["ConvertibleDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 10e9, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 30e9


def test_notes_plus_loans_summed_realty_income_style():
    gaap = dict(GAAP)
    gaap["NotesPayable"] = tagdata("USD", [inst("2026-03-31", 25091.6e6, accn="q126")])
    gaap["LoansPayable"] = tagdata("USD", [inst("2026-03-31", 2760.4e6, accn="q126")])
    # convertible would hide inside the notes total: never a separate slot here
    gaap["ConvertibleNotesPayable"] = tagdata("USD", [inst("2026-03-31", 5e9, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 25091.6e6 + 2760.4e6
    # notes totals include the current portion: the ltd_current slot is suppressed
    assert s.short_term_debt is None


def test_notes_and_loans_parent_rollup_wins_over_the_pair():
    gaap = dict(GAAP)
    gaap["NotesAndLoansPayable"] = tagdata("USD", [inst("2026-03-31", 27e9, accn="q126")])
    gaap["NotesPayable"] = tagdata("USD", [inst("2026-03-31", 25e9, accn="q126")])
    gaap["LoansPayable"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 27e9


def test_credit_line_is_additive_beside_other_instruments_sri_style():
    gaap = dict(GAAP)
    gaap["LongTermLineOfCredit"] = tagdata("USD", [inst("2026-03-31", 151.1e6, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 151.1e6


def test_secured_debt_takes_the_larger_representation_never_both():
    # AVA: instruments show a 3M fragment while SecuredLongTermDebt holds 2,759M
    gaap = dict(GAAP)
    gaap["LongTermLoansPayable"] = tagdata("USD", [inst("2026-03-31", 3e6, accn="q126")])
    gaap["SecuredLongTermDebt"] = tagdata("USD", [inst("2026-03-31", 2759e6, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 2759e6

    # BRT: a fresh zero revolver must not block the secured figure
    gaap = dict(GAAP)
    gaap["LongTermLineOfCredit"] = tagdata("USD", [inst("2026-03-31", 0, accn="q126")])
    gaap["SecuredDebt"] = tagdata("USD", [inst("2026-03-31", 469e6, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 469e6

    # the reverse: instruments larger -> secured dropped, never summed
    gaap = dict(GAAP)
    gaap["NotesPayable"] = tagdata("USD", [inst("2026-03-31", 10e9, accn="q126")])
    gaap["SecuredDebt"] = tagdata("USD", [inst("2026-03-31", 4e9, accn="q126")])
    assert float(build(gaap).long_term_debt.value) == 10e9


def test_combined_finance_lease_tag_suppresses_its_current_twin_boeing_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["FinanceLeaseLiability"] = tagdata("USD", [inst("2026-03-31", 111e6, accn="q126")])
    gaap["FinanceLeaseLiabilityCurrent"] = tagdata("USD", [inst("2026-03-31", 40e6, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 5e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 30e9 + 111e6
    assert float(s.short_term_debt.value) == 5e9  # lease current NOT double counted


def test_noncurrent_lease_tag_still_lets_the_current_lease_count():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["FinanceLeaseLiabilityNoncurrent"] = tagdata("USD", [inst("2026-03-31", 71e6, accn="q126")])
    gaap["FinanceLeaseLiabilityCurrent"] = tagdata("USD", [inst("2026-03-31", 40e6, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 5e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 30e9 + 71e6
    assert float(s.short_term_debt.value) == 5e9 + 40e6


def test_notes_payable_current_equal_to_commercial_paper_counts_once_ed_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["NotesPayableCurrent"] = tagdata("USD", [inst("2026-03-31", 869e6, accn="q126")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 869e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 869e6

    # different figures = genuinely different lines: both count
    gaap["NotesPayableCurrent"] = tagdata("USD", [inst("2026-03-31", 500e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 500e6 + 869e6


def test_bank_loans_and_notes_tag_terminates_the_borrowings_slot_key_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["ShortTermBankLoansAndNotesPayable"] = tagdata("USD", [inst("2026-03-31", 3680e6, accn="q126")])
    gaap["OtherShortTermBorrowings"] = tagdata("USD", [inst("2026-03-31", 3680e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 3680e6


def test_commercial_paper_and_other_borrowings_are_disjoint_ko_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 250e6, accn="q126")])
    gaap["OtherShortTermBorrowings"] = tagdata("USD", [inst("2026-03-31", 56e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 306e6


def test_current_family_never_added_beside_a_current_rollup_smp_style():
    # SMP: LinesOfCreditCurrent + OtherLongTermDebtCurrent == LongTermDebtCurrent exactly
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 54.6e6, accn="q126")])
    gaap["LinesOfCreditCurrent"] = tagdata("USD", [inst("2026-03-31", 34.6e6, accn="q126")])
    gaap["OtherLongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 20e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 54.6e6


def test_revolver_only_filer_gets_a_short_bucket_cal_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    gaap["LinesOfCreditCurrent"] = tagdata("USD", [inst("2026-03-31", 347.5e6, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 347.5e6


def test_senior_notes_current_only_without_parent_and_rollup_teva_style():
    # TEVA: SeniorNotesCurrent == the entire LongTermDebtCurrent rollup
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 15e9, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 2.1e9, accn="q126")])
    gaap["SeniorNotesCurrent"] = tagdata("USD", [inst("2026-03-31", 2.1e9, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 2.1e9

    del gaap["LongTermDebtCurrent"]
    assert float(build(gaap).short_term_debt.value) == 2.1e9


# --- Release 2, batch B: intangibles & goodwill ---

def test_other_intangibles_beat_a_smaller_parts_sum_hban_style():
    # HBAN: Other 1,727M contains the finite 969M plus 758M of MSRs
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["FiniteLivedIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 969e6, accn="q126")])
    gaap["OtherIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 1727e6, accn="q126")])
    assert float(build(gaap).intangibles.value) == 1727e6
    # SPGI: when the Other line is the smaller residual, the parts sum wins — never both
    gaap["OtherIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 100e6, accn="q126")])
    assert float(build(gaap).intangibles.value) == 969e6


def test_indefinite_class_tags_fill_the_empty_slot_ko_style():
    # KO: trademarks live only in IndefiniteLivedTrademarks
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["IndefiniteLivedTrademarks"] = tagdata("USD", [inst("2026-03-31", 12463e6, accn="q126")])
    gaap["FiniteLivedIntangibleAssetsNet"] = tagdata("USD", [inst("2026-03-31", 100e6, accn="q126")])
    s = build(gaap)
    assert float(s.intangibles.value) == 12463e6 + 100e6
    # the rollup wins over class tags when both exist
    gaap["IndefiniteLivedIntangibleAssetsExcludingGoodwill"] = tagdata("USD", [inst("2026-03-31", 12463e6, accn="q126")])
    assert float(build(gaap).intangibles.value) == 12463e6 + 100e6


def test_combined_minus_goodwill_derivation_needs_a_common_period_end():
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    # goodwill is annual-only; the combined line is quarterly — common end is FY
    gaap["Goodwill"] = tagdata("USD", [inst("2025-12-31", 50e9, form="10-K", accn="k25", filed="2026-02-15")])
    gaap["IntangibleAssetsNetIncludingGoodwill"] = tagdata("USD", [
        inst("2025-12-31", 80e9, form="10-K", accn="k25", filed="2026-02-15"),
        inst("2026-03-31", 82e9, accn="q126"),
    ])
    s = build(gaap)
    assert float(s.intangibles.value) == 30e9
    assert "IntangibleAssetsNetIncludingGoodwill - us-gaap:Goodwill" in s.intangibles.provenance.tag

    # CALM guard: combined below goodwill is a mistag, never a negative value
    gaap["IntangibleAssetsNetIncludingGoodwill"] = tagdata("USD", [
        inst("2025-12-31", 40e9, form="10-K", accn="k25", filed="2026-02-15")])
    assert build(gaap).intangibles is None


def test_gross_minus_accumulated_requires_matching_period_end_bby_style():
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["FiniteLivedIntangibleAssetsGross"] = tagdata("USD", [
        inst("2025-12-31", 96e8, form="10-K", accn="k25", filed="2026-02-15"),
        inst("2026-03-31", 97e8, accn="q126"),
    ])
    gaap["FiniteLivedIntangibleAssetsAccumulatedAmortization"] = tagdata("USD", [
        inst("2025-12-31", 95e8, form="10-K", accn="k25", filed="2026-02-15")])
    s = build(gaap)
    # matched at 2025-12-31: 9.6B - 9.5B, never the fresh gross alone
    assert float(s.intangibles.value) == 1e8


def test_goodwill_derived_from_gross_when_never_impaired_aaon_style():
    gaap = {k: v for k, v in GAAP.items() if k != "Goodwill"}
    gaap["GoodwillGross"] = tagdata("USD", [inst("2026-03-31", 573e6, accn="q126")])
    s = build(gaap)
    assert float(s.goodwill.value) == 573e6
    assert "never tagged" in s.goodwill.provenance.concept


def test_servicing_assets_sum_both_measurement_books_wfc_style():
    gaap = {k: v for k, v in GAAP.items()
            if k not in ("IntangibleAssetsNetExcludingGoodwill",)}
    gaap["ServicingAssetAtFairValueAmount"] = tagdata("USD", [inst("2026-03-31", 1.3e9, accn="q126")])
    gaap["ServicingAssetAtAmortizedValue"] = tagdata("USD", [inst("2026-03-31", 0.4e9, accn="q126")])
    assert float(build(gaap).intangibles.value) == 1.7e9


def test_capitalized_software_is_the_disclosed_last_resort_mcd_style():
    gaap = {k: v for k, v in GAAP.items() if k != "IntangibleAssetsNetExcludingGoodwill"}
    gaap["CapitalizedComputerSoftwareNet"] = tagdata("USD", [inst("2026-03-31", 800e6, accn="q126")])
    s = build(gaap)
    assert float(s.intangibles.value) == 800e6
    assert "standing in" in s.intangibles.provenance.concept


# --- Release 2, batch C: distributions & dividend evidence ---

def test_lp_distributions_count_as_the_common_payout_epd_style():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DistributionMadeToLimitedPartnerCashDistributionsPaid"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1.2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is True
    assert "common" in s.dividend.provenance.concept


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


def test_partners_capital_distributions_carry_the_aggregate_label_mplx_style():
    # the equity-statement total includes GP/IDR holders: disclosed, not "common"
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["PartnersCapitalAccountDistributions"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1.02e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is True
    assert "aggregate" in s.dividend.provenance.concept


def test_distribution_named_tag_is_evidence_for_unknown_not_fail():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DistributionsMade"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 5e8, form="10-Q", accn="q126", filed="2026-05-05")])
    assert build(gaap).pays_dividend is None  # unknown, never a false FAIL


def test_share_and_ratio_units_are_never_payout_evidence():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["CommonStockDividendsShares"] = tagdata("shares", [
        dur("2026-01-01", "2026-03-31", 1e6, form="10-Q", accn="q126", filed="2026-05-05")])
    assert build(gaap).pays_dividend is False  # no dollar payout anywhere -> not paying


# --- Release 2, batch D: partnership equity, NCI chain, temporary equity ---

def test_partners_capital_derives_liabilities_for_mlps_paa_style():
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 29218e6, accn="q126")])
    gaap["PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 14291e6, accn="q126")])
    gaap["PartnersCapitalAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 3212e6, accn="q126")])
    s = build(gaap)
    assert float(s.total_liabilities.value) == 29218e6 - 14291e6
    # PCI kept NCI out of liabilities -> the partners-capital NCI is subtracted
    assert float(s.noncontrolling_interest.value) == 3212e6


def test_parent_only_partners_capital_skips_nci_dkl_style():
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e6, accn="q126")])
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", -69.3e6, accn="q126")])  # deficit is fine
    gaap["PartnersCapitalAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 50e6, accn="q126")])
    s = build(gaap)
    assert float(s.total_liabilities.value) == 1000e6 + 69.3e6
    assert s.noncontrolling_interest is None  # NCI already inside derived liabilities


def test_nonredeemable_nci_is_an_alternative_never_added_ms_style():
    gaap = dict(GAAP)
    gaap["MinorityInterest"] = tagdata("USD", [inst("2026-03-31", 1111e6, accn="q126")])
    gaap["NonredeemableNoncontrollingInterest"] = tagdata("USD", [inst("2026-03-31", 1111e6, accn="q126")])
    assert float(build(gaap).noncontrolling_interest.value) == 1111e6


def test_redeemable_nci_components_only_when_the_total_is_absent_udr_style():
    gaap = dict(GAAP)
    gaap["RedeemableNoncontrollingInterestEquityCarryingAmount"] = \
        tagdata("USD", [inst("2026-03-31", 155.6e6, accn="q126")])
    gaap["RedeemableNoncontrollingInterestEquityPreferredCarryingAmount"] = \
        tagdata("USD", [inst("2026-03-31", 155.6e6, accn="q126")])
    assert float(build(gaap).noncontrolling_interest.value) == 155.6e6

    del gaap["RedeemableNoncontrollingInterestEquityCarryingAmount"]
    gaap["RedeemableNoncontrollingInterestEquityCommonCarryingAmount"] = \
        tagdata("USD", [inst("2026-03-31", 44.4e6, accn="q126")])
    assert float(build(gaap).noncontrolling_interest.value) == 200e6


def test_redeemable_fair_value_blocked_by_the_incl_nci_temporary_tag_heico_style():
    gaap = dict(GAAP)
    gaap["RedeemableNoncontrollingInterestEquityFairValue"] = \
        tagdata("USD", [inst("2026-03-31", 103.1e6, accn="q126")])
    gaap["TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"] = \
        tagdata("USD", [inst("2026-03-31", 536.7e6, accn="q126")])
    s = build(gaap)
    # same holders once: the incl-NCI line fills the temporary-equity slot instead
    assert s.noncontrolling_interest is None
    assert float(s.temporary_equity.value) == 536.7e6

    # OMC-style clean case: fair value stands when nothing else names the holders
    del gaap["TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"]
    s = build(gaap)
    assert float(s.noncontrolling_interest.value) == 103.1e6
    assert s.temporary_equity is None


def test_temporary_equity_deducted_when_preferred_is_a_zero_placeholder_kdp_style():
    gaap = dict(GAAP)
    gaap["PreferredStockValue"] = tagdata("USD", [inst("2026-03-31", 0, accn="q126")])
    gaap["TemporaryEquityCarryingAmountAttributableToParent"] = \
        tagdata("USD", [inst("2026-03-31", 4418e6, accn="q126")])
    s = build(gaap)
    assert float(s.temporary_equity.value) == 4418e6

    # nonzero preferred keeps the slot: never both
    gaap["PreferredStockValue"] = tagdata("USD", [inst("2026-03-31", 600e6, accn="q126")])
    assert build(gaap).temporary_equity is None


def test_temporary_equity_skipped_when_liabilities_were_derived():
    # a derived L = LSE - equity figure already contains the mezzanine (CMCSA/ACN)
    gaap = {k: v for k, v in GAAP.items() if k != "Liabilities"}
    gaap["LiabilitiesAndStockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")])
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 600e9, accn="q126")])
    gaap["TemporaryEquityCarryingAmountAttributableToParent"] = \
        tagdata("USD", [inst("2026-03-31", 5e9, accn="q126")])
    assert build(gaap).temporary_equity is None


def test_liquidation_preference_is_the_last_resort_eikon_style():
    gaap = dict(GAAP)
    gaap["PreferredStockValue"] = tagdata("USD", [inst("2026-03-31", 0, accn="q126")])
    gaap["TemporaryEquityLiquidationPreference"] = \
        tagdata("USD", [inst("2026-03-31", 1159.8e6, accn="q126")])
    assert float(build(gaap).temporary_equity.value) == 1159.8e6


# --- Release 2, batch E: share-count fallbacks ---

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


# --- Release 2, batches F-G: financial income, quality notes, working capital ---

def test_bdc_investment_income_becomes_the_revenue_series_arcc_style():
    gaap = dict(GAAP)
    gaap["GrossInvestmentIncomeOperating"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 2.9e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 3.052e9, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert float(s.annual_revenue[2025].value) == 3.052e9


def test_investment_company_per_share_element_yields_eps_bxsl_style():
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["InvestmentCompanyInvestmentIncomeLossFromOperationsPerShare"] = tagdata("USD/shares", [
        dur("2024-01-01", "2024-12-31", 3.1, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 3.4, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert float(s.annual_eps[2025].value) == 3.4


def test_one_time_gain_is_disclosed_with_flipped_wording():
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 1e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["GainLossOnInvestments"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 300e6, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    note = next(n for n in s.earnings_quality if "investment gain" in n.lower())
    assert "added to" in note  # positive gain BOOSTS income — opposite of a charge


def test_impairment_rollup_note_only_without_a_specific_line_gis_style():
    base = dict(GAAP)
    base["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap = dict(base)
    gaap["GoodwillImpairmentLoss"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 302.9e6, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["GoodwillAndIntangibleAssetImpairment"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1750e6, form="10-Q", accn="q126", filed="2026-05-05")])
    notes = build(gaap).earnings_quality
    assert not any("rollup" in n or "Goodwill and intangible" in n for n in notes)

    gaap = dict(base)
    gaap["GoodwillAndIntangibleAssetImpairment"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1750e6, form="10-Q", accn="q126", filed="2026-05-05")])
    notes = build(gaap).earnings_quality
    assert any("goodwill and intangible impairment" in n.lower() for n in notes)


def test_warrant_remeasurement_note_claims_no_direction():
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 1e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["FairValueAdjustmentOfWarrants"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 200e6, form="10-Q", accn="q126", filed="2026-05-05")])
    note = next(n for n in build(gaap).earnings_quality if "warrant" in n.lower())
    assert "cannot settle" in note
    assert "added to" not in note and "reduced" not in note


def test_afs_successor_tag_is_the_fragment_never_the_total_pfe_style():
    gaap = dict(OE_GAAP)
    gaap["OtherShortTermInvestments"] = tagdata("USD", [inst("2026-03-31", 12454e6, accn="q126")])
    gaap["AvailableForSaleSecuritiesDebtSecuritiesCurrent"] = tagdata("USD", [inst("2026-03-31", 9183e6, accn="q126")])
    s = build(gaap)
    # invested capital = 1000e9 assets - 40e9 cash - 12.454e9 investments - 150e9 nibcl
    assert float(s.owner_earnings.invested_capital) == 1000e9 - 40e9 - 12454e6 - 150e9

    # with no earlier chain member, the successor tag finally serves (AGIO)
    del gaap["OtherShortTermInvestments"]
    s = build(gaap)
    assert float(s.owner_earnings.invested_capital) == 1000e9 - 40e9 - 9183e6 - 150e9


def test_restricted_cash_netted_only_from_the_inclusive_rollup_aal_style():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "CashAndCashEquivalentsAtCarryingValue"}
    gaap["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"] = \
        tagdata("USD", [inst("2026-03-31", 40e9, accn="q126")])
    gaap["RestrictedCash"] = tagdata("USD", [inst("2026-03-31", 3e9, accn="q126")])
    s = build(gaap)
    assert float(s.owner_earnings.invested_capital) == 1000e9 - 37e9 - 150e9
    assert any("restricted" in c for c in s.owner_earnings.caveats)

    # plain carrying-value tag: never netted
    s = build(OE_GAAP | {"RestrictedCash": tagdata("USD", [inst("2026-03-31", 3e9, accn="q126")])})
    assert float(s.owner_earnings.invested_capital) == 810e9


def test_segment_capex_fills_only_missing_years_schl_style():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "PaymentsToAcquirePropertyPlantAndEquipment"}
    gaap["PaymentsToAcquirePropertyPlantAndEquipment"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 10e9, accn="k24", filed="2025-02-15")])
    gaap["SegmentExpenditureAdditionToLongLivedAssets"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 99e9, accn="k24", filed="2025-02-15"),  # loses to payments
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15")])  # fills the dead year
    s = build(gaap)
    # latest shared year 2025 uses the segment figure: 100 + 12 - 20 - 12
    assert float(s.owner_earnings.owner_earnings) == 80e9


# --- Release 3: harness candidates ---

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


def test_combined_debt_rollup_including_current_maturities_jpm_style():
    gaap = dict(GAAP)
    gaap["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"] = \
        tagdata("USD", [inst("2026-03-31", 460.5e9, accn="q126")])
    assert float(build(gaap).total_debt.value) == 460.5e9


def test_long_term_notes_and_loans_rollup_teva_style():
    gaap = dict(GAAP)
    gaap["LongTermNotesAndLoans"] = tagdata("USD", [inst("2026-03-31", 16.8e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 16.8e9
    # long-term-only variant: the current side stays open
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    assert float(build(gaap).short_term_debt.value) == 2e9


def test_combined_senior_notes_suppress_only_their_current_twin_syf_style():
    gaap = dict(GAAP)
    gaap["SeniorNotes"] = tagdata("USD", [inst("2026-03-31", 7.7e9, accn="q126")])
    gaap["SeniorNotesCurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    gaap["OtherNotesPayableCurrent"] = tagdata("USD", [inst("2026-03-31", 200e6, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 7.7e9
    # senior-current inside the combined tag; other notes still count
    assert float(s.short_term_debt.value) == 200e6


def test_other_loans_payable_and_junior_subordinated_notes_and_warehouse():
    gaap = dict(GAAP)
    gaap["OtherLoansPayable"] = tagdata("USD", [inst("2026-03-31", 935e6, accn="q126")])
    gaap["JuniorSubordinatedNotes"] = tagdata("USD", [inst("2026-03-31", 37e6, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 935e6 + 37e6

    gaap2 = dict(GAAP)
    gaap2["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    gaap2["WarehouseAgreementBorrowings"] = tagdata("USD", [inst("2026-03-31", 300e6, accn="q126")])
    assert float(build(gaap2).short_term_debt.value) == 300e6


def test_current_liabilities_derived_from_the_noncurrent_split():
    gaap = {k: v for k, v in GAAP.items() if k != "LiabilitiesCurrent"}
    gaap["LiabilitiesNoncurrent"] = tagdata("USD", [inst("2026-03-31", 250e9, accn="q126")])
    s = build(gaap)
    # Liabilities 400e9 - noncurrent 250e9
    assert float(s.current_liabilities.value) == 150e9
    assert "derived" in s.current_liabilities.provenance.concept


def test_redeemable_nci_other_component_counts_without_a_total_et_style():
    gaap = dict(GAAP)
    gaap["RedeemableNoncontrollingInterestEquityOtherCarryingAmount"] = \
        tagdata("USD", [inst("2026-03-31", 256e6, accn="q126")])
    assert float(build(gaap).noncontrolling_interest.value) == 256e6

    # the total wins when present — components never stack on it
    gaap["RedeemableNoncontrollingInterestEquityCarryingAmount"] = \
        tagdata("USD", [inst("2026-03-31", 256e6, accn="q126")])
    assert float(build(gaap).noncontrolling_interest.value) == 256e6
