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


def texts(snapshot):
    """Disclosure notes carry their kind now; the wording is what tests read."""
    return [n["text"] for n in snapshot.context_notes]


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


def test_at_one_date_the_larger_debt_figure_is_the_whole_one():
    """Chain order used to break the tie, which let a footnote fragment outrank the
    balance-sheet line: Carriage Services shipped 14.4M where its own LongTermDebt
    reads 526,016,000 at the same date and LongTermDebtNoncurrent 5,411,000 is a
    note (10-Q 0001016281-26-000055). Preferring the larger is safe because the
    plain tag suppresses its own current twin from the short bucket."""
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")])
    gaap["LongTermDebt"] = tagdata("USD", [inst("2026-03-31", 33e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 33e9
    # ...and the plain tag's own current twin must not be counted a second time
    assert "LongTermDebtCurrent" not in (
        s.short_term_debt.provenance.tag if s.short_term_debt else "")
    assert s.long_term_debt.provenance.tag == "us-gaap:LongTermDebt"


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
    note = next(n["text"] for n in s.earnings_quality if "investment gain" in n["text"].lower())
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
    notes = [n["text"] for n in build(gaap).earnings_quality]
    assert not any("rollup" in n or "Goodwill and intangible" in n for n in notes)

    gaap = dict(base)
    gaap["GoodwillAndIntangibleAssetImpairment"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1750e6, form="10-Q", accn="q126", filed="2026-05-05")])
    notes = [n["text"] for n in build(gaap).earnings_quality]
    assert any("goodwill and intangible impairment" in n.lower() for n in notes)


def test_warrant_remeasurement_note_claims_no_direction():
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 1e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["FairValueAdjustmentOfWarrants"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 200e6, form="10-Q", accn="q126", filed="2026-05-05")])
    note = next(n["text"] for n in build(gaap).earnings_quality if "warrant" in n["text"].lower())
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


# --- Release 4: context notes and the secured/unsecured axis ---

def test_secured_plus_unsecured_axis_beats_a_lone_instrument_gs_style():
    """GS reports $348B unsecured and $11.6B secured with no instrument rollup;
    subordinated debt sits inside unsecured and must not be added on top."""
    gaap = dict(GAAP)
    gaap["UnsecuredLongTermDebt"] = tagdata("USD", [inst("2026-03-31", 347.96e9, accn="q126")])
    gaap["SecuredLongTermDebt"] = tagdata("USD", [inst("2026-03-31", 11.56e9, accn="q126")])
    gaap["SubordinatedDebt"] = tagdata("USD", [inst("2026-03-31", 14.81e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 347.96e9 + 11.56e9

    # a filer with subordinated debt and no axis tags still gets its figure
    gaap2 = {k: v for k, v in gaap.items()
             if k not in ("UnsecuredLongTermDebt", "SecuredLongTermDebt")}
    assert float(build(gaap2).long_term_debt.value) == 14.81e9


def test_context_notes_flag_weak_cash_conversion():
    gaap = dict(GAAP)
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur(f"{y}-01-01", f"{y}-12-31", 1000e6, accn=f"k{y}", filed=f"{y+1}-02-15")
        for y in (2023, 2024, 2025)])
    gaap["NetCashProvidedByUsedInOperatingActivities"] = tagdata("USD", [
        dur(f"{y}-01-01", f"{y}-12-31", 400e6, accn=f"k{y}", filed=f"{y+1}-02-15")
        for y in (2023, 2024, 2025)])
    note = next(n for n in texts(build(gaap)) if "operating cash" in n)
    assert "40%" in note


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


def test_context_notes_flag_thin_interest_cover():
    gaap = dict(GAAP)
    gaap["OperatingIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 200e6, accn="k25", filed="2026-02-15")])
    gaap["InterestExpense"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    note = next(n for n in texts(build(gaap)) if "covers interest" in n)
    assert "2.0x" in note


# --- Release 4b: derived EPS for filers whose per-share element is dimension-only ---

def test_eps_derived_when_no_per_share_element_exists_kkr_style():
    """KKR tags EPS only on a share-class axis, which Company Facts omits; its
    own income and share count still divide."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 2400e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 900e6, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert round(float(s.annual_eps[2025].value), 4) == round(2400 / 900, 4)
    assert "derived" in s.annual_eps[2025].provenance.concept
    assert s.annual_eps[2025].provenance.tag == (
        "us-gaap:NetIncomeLoss / us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")


def test_derived_eps_nets_preferred_dividends_first():
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 1000e6, accn="k25", filed="2026-02-15")])
    gaap["DividendsPreferredStock"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    assert float(build(gaap).annual_eps[2025].value) == 9.0  # 900M to common, not 1,000M


def test_profit_loss_never_derives_eps_for_a_filer_with_minority_interest_ares_style():
    """ProfitLoss includes noncontrolling interests. Ares tags no MinorityInterest
    at all, so the equity pair is the evidence: EPS would read 2.60 against a
    genuine 3.00-odd — the false-bargain direction."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["ProfitLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 465e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 180e6, accn="k25", filed="2026-02-15")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 4025e6, accn="q126")])
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 8602e6, accn="q126")])
    assert 2025 not in build(gaap).annual_eps

    # a filer whose equity shows no minority holders keeps the derivation (co-op)
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 4025e6, accn="q126")])
    assert 2025 in build(gaap).annual_eps


def test_a_year_without_its_own_weighted_average_derives_nothing():
    """Measured against reported figures, the count on a report cover produced
    errors of exactly five, ten and a hundred and fifty times: a reverse split
    leaves a small current count against an old year's income, and a
    multi-class cover names one class while the income belongs to all."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2021-01-01", "2021-12-31", 1000e6, accn="k21", filed="2022-02-15")])
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [
        inst("2026-03-31", 100e6, accn="q126")])
    assert 2021 not in build(gaap).annual_eps


def test_a_reported_eps_is_never_replaced_by_a_derived_one():
    s = build()  # GAAP has EarningsPerShareDiluted for every year
    assert all("derived" not in f.provenance.concept for f in s.annual_eps.values())


# --- Review v46 follow-ups ---

def test_domestic_pretax_alone_never_becomes_owner_earnings():
    """The domestic figure is one geography, not the consolidated company."""
    gaap = {k: v for k, v in OE_GAAP.items() if k != "OperatingIncomeLoss"}
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 30e9, accn="k25", filed="2026-02-15")])
    assert build(gaap).owner_earnings is None


def test_domestic_and_foreign_pretax_sum_to_a_consolidated_figure():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "OperatingIncomeLoss"}
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 30e9, accn="k25", filed="2026-02-15")])
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 70e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert float(dict(oe.components)["operating profit"]) == 100e9
    assert any("domestic and foreign" in c for c in oe.caveats)


def test_a_summed_figure_keeps_every_component_filing():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [
        inst("2025-12-31", 30e9, form="10-K", accn="k25", filed="2026-02-15")])
    gaap["FinanceLeaseLiabilityNoncurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    parts = build(gaap).long_term_debt.provenance.components
    assert len(parts) == 2
    assert {p.accession for p in parts} == {"k25", "q126"}
    # the summary line's own date belongs to the newest part, which is exactly
    # why the parts must state their own
    assert {str(p.period_end) for p in parts} == {"2025-12-31", "2026-03-31"}


def test_a_zero_share_count_is_not_a_share_count():
    """Every per-share figure divides by this number; a tagged zero is an
    artefact, and treating it as real would make each of them meaningless."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 0, accn="q126")])
    assert build(gaap).shares_outstanding is None


def test_a_negative_revenue_is_not_a_top_line():
    """The gold trusts tag a net investment loss as Revenues; the size test
    would otherwise read a company that sold less than nothing."""
    gaap = dict(GAAP)
    gaap["Revenues"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -606e6, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert 2025 not in s.annual_revenue
    assert s.ttm_revenue is None


def test_a_trailing_figure_anchored_a_decade_back_is_not_trailing():
    gaap = dict(GAAP)
    gaap["Revenues"] = tagdata("USD", [
        dur("2013-01-01", "2013-12-31", 500e6, accn="k13", filed="2014-02-15")])
    s = build(gaap)  # GAAP's balance sheet is 2026
    assert s.annual_revenue[2013] is not None   # the year itself is real history
    assert s.ttm_revenue is None                # but it is not the trailing twelve months


def test_negative_assets_are_a_sign_error_not_a_balance_sheet():
    gaap = dict(GAAP)
    gaap["AssetsCurrent"] = tagdata("USD", [inst("2026-03-31", -26, accn="q126")])
    s = build(gaap)
    assert s.current_assets is None


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


# --- Release 5c: dimensioned facts, single-member rule ---

def dimensioned(tag, unit, entries):
    return {"facts": {"us-gaap": {tag: {"units": {unit: entries}}}}}


def classed_entry(start, end, val, segments, accn="k25", form="10-K", filed="2026-02-15"):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form,
            "filed": filed, "fy": 0, "fp": "FY", "segments": segments}


def test_a_lone_share_class_is_the_companys_own_figure_kkr_style():
    """KKR reports earnings per share only under ClassOfStock=CommonStock, so
    Company Facts returns nothing at all for it."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
        classed_entry("2025-01-01", "2025-12-31", 2.34, "ClassOfStock=CommonStock;")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
    assert float(s.annual_eps[2025].value) == 2.34
    assert s.annual_eps[2025].provenance.segments == "ClassOfStock=CommonStock;"


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


def test_a_consolidated_figure_always_outranks_a_classed_one():
    dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
        classed_entry("2025-01-01", "2025-12-31", 99.0, "ClassOfStock=CommonStock;")])
    s = build_snapshot("TEST", "0000000001", facts_doc(GAAP), dimensioned=dim)
    assert float(s.annual_eps[2025].value) == 6.0   # the undimensioned fact stands


def test_a_classed_share_count_serves_when_every_other_source_is_silent():
    gaap = {k: v for k, v in GAAP.items() if k != "CommonStockSharesOutstanding"}
    dim = dimensioned("CommonStockSharesOutstanding", "shares", [
        {**classed_entry(None, "2026-03-31", 890e6, "ClassOfStock=CommonStock;",
                         accn="q126", form="10-Q", filed="2026-05-05")}])
    del dim["facts"]["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"][0]["start"]
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
    assert float(s.shares_outstanding.value) == 890e6


# --- Where trouble accumulates quietly ---

def _years(tag, unit, values, instant=False):
    out = []
    for year, value in values.items():
        if instant:
            out.append(inst(f"{year}-12-31", value, form="10-K", accn=f"k{year}",
                            filed=f"{year + 1}-02-15"))
        else:
            out.append(dur(f"{year}-01-01", f"{year}-12-31", value, accn=f"k{year}",
                           filed=f"{year + 1}-02-15"))
    return tagdata(unit, out)


def test_receivables_outrunning_sales_are_stated():
    """Revenue booked and not collected looks like growth until it is written off."""
    gaap = dict(GAAP)
    gaap["Revenues"] = _years("Revenues", "USD", {2022: 1000e6, 2023: 1050e6,
                                                  2024: 1100e6, 2025: 1150e6})
    gaap["AccountsReceivableNetCurrent"] = _years(
        "AccountsReceivableNetCurrent", "USD",
        {2022: 100e6, 2023: 140e6, 2024: 190e6, 2025: 260e6}, instant=True)
    note = next(n for n in texts(build(gaap)) if n.startswith("Receivables"))
    assert "160%" in note and "15%" in note        # receivables +160%, sales +15%


def test_inventory_in_line_with_sales_says_nothing():
    gaap = dict(GAAP)
    gaap["Revenues"] = _years("Revenues", "USD", {2022: 1000e6, 2023: 1100e6,
                                                  2024: 1200e6, 2025: 1300e6})
    gaap["InventoryNet"] = _years("InventoryNet", "USD",
                                  {2022: 200e6, 2023: 220e6, 2024: 240e6, 2025: 260e6},
                                  instant=True)
    assert not any(n.startswith("Inventory") for n in texts(build(gaap)))


def test_lease_obligations_are_disclosed_beside_the_debt_test_that_ignores_them():
    # GAAP's equity is 1000bn - 400bn = 600bn, so the lease must be large to speak
    gaap = dict(GAAP)
    gaap["OperatingLeaseLiability"] = tagdata("USD", [inst("2026-03-31", 200e9, accn="q126")])
    note = next(n for n in texts(build(gaap)) if "lease obligations" in n)
    assert "200,000M" in note and "long-term debt" in note


def test_a_lease_book_that_is_trivial_to_the_company_says_nothing():
    """NVIDIA's leases are more than a quarter of its borrowings and 2% of its
    equity; against a balance sheet that size the obligation tells a reader
    nothing."""
    gaap = dict(GAAP)
    gaap["OperatingLeaseLiability"] = tagdata("USD", [inst("2026-03-31", 4.3e9, accn="q126")])
    assert not any("lease obligations" in n for n in texts(build(gaap)))


# --- Graham's NVF case: what a filing still has to disclose ---

def test_debt_sold_below_face_costs_more_than_its_coupon_says():
    """NVF's debentures paid 5% and sold at 43% of par. Where amortised discount
    is most of the interest bill, the coupon is not the cost of the money."""
    gaap = dict(GAAP)
    gaap["InterestExpense"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    gaap["AmortizationOfDebtDiscountPremium"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 60e6, accn="k25", filed="2026-02-15")])
    note = next(n for n in texts(build(gaap)) if "amortised debt discount" in n)
    assert "60%" in note


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


# --- the deferred tax footnote: the company's own opinion of its earning power ---

def annual_10k(tag, values, gaap):
    """One fiscal-year duration series, as a 10-K states it."""
    gaap[tag] = tagdata("USD", [
        dur(f"{y}-01-01", f"{y}-12-31", v, accn=f"k{y}", filed=f"{y + 1}-02-15")
        for y, v in values.items()])
    return gaap


def deferred_tax_gaap(**tags):
    """Base facts with a profitable FY2025, plus whatever the footnote says."""
    gaap = dict(GAAP)
    annual_10k("NetIncomeLoss", {2024: 800e6, 2025: 1000e6}, gaap)
    for tag, entries in tags.items():
        gaap[tag] = tagdata("USD", entries)
    return gaap


def k25(end, val):
    return inst(end, val, form="10-K", accn="k25", filed="2026-02-15")


def test_a_full_valuation_allowance_beside_profits_is_disclosed():
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 60e9)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 45e9)],
    )
    note = next(n for n in texts(build(gaap)) if "valuation allowance" in n)
    assert "75%" in note and "1,000M" in note


def test_coca_colas_allowance_is_a_seventh_of_its_deferred_assets():
    """KO reserves 388M against 5,514M at 2025-12-31 — the ordinary case, and
    the counterexample that keeps the note from firing on every filer."""
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 5514e6)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 388e6)],
    )
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_valaris_reserves_more_than_the_gross_tag_admits_to():
    """VAL tags a 1,368M 'gross' deferred tax asset and a 3,292M allowance
    against it. An allowance cannot exceed what it reserves against, so the two
    tags are not describing one thing and neither is reported."""
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 1368e6)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 3292e6)],
    )
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_the_net_tag_rebuilds_a_base_the_gross_tag_cannot_supply():
    """Biogen's gross tag stopped in 2021 while its allowance is current. Net
    plus allowance is the same balance sheet's own arithmetic."""
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[inst("2021-06-30", 945e6, form="10-K", accn="k21",
                                     filed="2021-08-01")],
        DeferredTaxAssetsNet=[k25("2025-12-31", 30e9)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 40e9)],
    )
    note = next(n for n in texts(build(gaap)) if "valuation allowance" in n)
    assert "70,000M" in note and "57%" in note


def test_allowance_and_base_must_share_a_balance_sheet_date():
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 60e9)],
        DeferredTaxAssetsValuationAllowance=[
            inst("2025-09-30", 45e9, form="10-Q", accn="q325", filed="2025-11-01")],
    )
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_a_loss_making_filer_gets_no_allowance_note():
    """A company with no profits is expected to reserve its tax assets; the
    contradiction only exists when it is earning money and still reserving."""
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 60e9)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 45e9)],
    )
    annual_10k("NetIncomeLoss", {2024: -500e6, 2025: -900e6}, gaap)
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_a_tax_charge_that_was_not_paid_is_disclosed():
    """Service Corp's FY2025 charge of 191M against 171M reported: the current
    half was a refund."""
    gaap = deferred_tax_gaap()
    annual_10k("IncomeTaxExpenseBenefit", {2025: 170.9e6}, gaap)
    annual_10k("DeferredIncomeTaxExpenseBenefit", {2025: 191.5e6}, gaap)
    note = next(n for n in texts(build(gaap)) if "deferred" in n and "income tax charge" in n)
    assert "112%" in note and "21M refund" in note


def test_an_ordinary_deferred_share_says_nothing():
    """KO's FY2025: 517M deferred inside a 2,861M charge."""
    gaap = deferred_tax_gaap()
    annual_10k("IncomeTaxExpenseBenefit", {2025: 2861e6}, gaap)
    annual_10k("DeferredIncomeTaxExpenseBenefit", {2025: 517e6}, gaap)
    assert not any("income tax charge" in n for n in texts(build(gaap)))


def test_a_tax_footnote_older_than_the_earnings_record_is_not_reported():
    gaap = deferred_tax_gaap()
    annual_10k("IncomeTaxExpenseBenefit", {2021: 100e6}, gaap)
    annual_10k("DeferredIncomeTaxExpenseBenefit", {2021: 95e6}, gaap)
    assert not any("income tax charge" in n for n in texts(build(gaap)))


def test_a_deferred_amount_immaterial_to_earnings_says_nothing():
    gaap = deferred_tax_gaap()
    annual_10k("IncomeTaxExpenseBenefit", {2025: 10e6}, gaap)
    annual_10k("DeferredIncomeTaxExpenseBenefit", {2025: 9e6}, gaap)   # 0.9% of net income
    assert not any("income tax charge" in n for n in texts(build(gaap)))


# --- splits: one corporate action, one factor, corroborated by the share count ---

def _yr(year, val, filed, accn):
    return dur(f"{year}-01-01", f"{year}-12-31", val, accn=accn, filed=filed)


def _shares(year, val, filed, accn):
    return dur(f"{year}-01-01", f"{year}-12-31", val, accn=accn, filed=filed)


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


def test_a_partnership_never_divides_the_whole_groups_profit_by_its_own_units():
    """Westlake Chemical Partners consolidates an OpCo whose sponsor owns two thirds of
    it. The corporate equity pair the guard reads does not exist for a partnership: WLKP
    files PartnersCapital 253.7M inside 769.4M including the minority. FY2019 ProfitLoss
    is 332,895k against 60,981k attributable to unitholders on 34,488,058 units, and the
    10-K reports $1.77 a unit (accn 0001604665-22-000009), not the $9.65 that shipped."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["ProfitLoss"] = tagdata("USD", [
        dur("2019-01-01", "2019-12-31", 332_895_000, accn="k21", filed="2022-03-02")])
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2019-01-01", "2019-12-31", 60_981_000, accn="k21", filed="2022-03-02")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2019-01-01", "2019-12-31", 34_488_058, accn="k21", filed="2022-03-02")])
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", 253_713_000, accn="q126")])
    gaap["PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"] = tagdata(
        "USD", [inst("2026-03-31", 769_413_000, accn="q126")])
    eps = build(gaap).annual_eps[2019]
    assert round(float(eps.value), 2) == 1.77


def test_a_canadian_filers_earnings_are_not_read_as_dollars():
    """Enbridge, Canadian Pacific and Imperial Oil tag earnings per share only in
    CAD/shares. Taking whatever unit came first divided a New York price by a Canadian
    figure and understated every P/E by the exchange rate."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["EarningsPerShareDiluted"] = tagdata("CAD/shares", [
        dur("2025-01-01", "2025-12-31", 3.22, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert s.annual_eps == {} and s.ttm_eps is None


def test_a_lease_book_does_not_stand_in_for_a_companys_borrowings():
    """Ford's noncurrent debt element went stale in 2020, leaving a $754M finance
    lease as the only fresh long-term figure and criterion 3 passing at 0.09x. Its
    interest bill is $1,254M — 166% of the lease principal, which no lease produces."""
    gaap = dict(GAAP)
    gaap["FinanceLeaseLiabilityNoncurrent"] = tagdata("USD", [
        inst("2025-12-31", 754e6, form="10-K", accn="k25", filed="2026-02-11")])
    gaap["InterestExpense"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 1254e6, accn="k25", filed="2026-02-11")])
    assert build(gaap).long_term_debt is None


def test_a_debt_free_filers_lease_is_still_its_debt():
    """Vertex, Incyte, MongoDB and Plexus all carry a lease-only bucket and no
    borrowings; their interest is a fraction of the principal and the figure stands."""
    gaap = dict(GAAP)
    gaap["FinanceLeaseLiabilityNoncurrent"] = tagdata("USD", [
        inst("2025-12-31", 106.7e6, form="10-K", accn="k25", filed="2026-02-11")])
    gaap["InterestExpense"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 13.3e6, accn="k25", filed="2026-02-11")])
    ltd = build(gaap).long_term_debt
    assert ltd is not None and float(ltd.value) == 106700000.0


def test_the_cover_names_which_share_class_the_ticker_is():
    """Hershey reports earnings per share for its Common Stock and its Class B in the
    same filing. Company Facts drops both because they are dimensioned, and the
    ambiguity rule refuses both because there are two — so its series stopped in 2014
    and criterion 4 was decided on a decade-old window. The cover of its own filing
    names the one the symbol registers: "Common Stock, one dollar par value"."""
    facts = facts_doc({k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"})
    dimensioned = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        dict(dur("2025-01-01", "2025-12-31", 4.34, accn="k25", filed="2026-02-15"),
             segments="ClassOfStock=CommonStock"),
        dict(dur("2025-01-01", "2025-12-31", 4.05, accn="k25", filed="2026-02-15"),
             segments="ClassOfStock=CommonClassB"),
    ]}}}}}
    blind = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned)
    assert 2025 not in blind.annual_eps, "two classes and no cover: the refusal must stand"

    told = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned,
                          receipt={"title": "Common Stock, one dollar par value"})
    assert float(told.annual_eps[2025].value) == 4.34

    # a cover naming a class that matches neither member changes nothing
    other = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned,
                           receipt={"title": "Class C Capital Stock"})
    assert 2025 not in other.annual_eps


def test_a_convertible_preferred_is_disclosed_and_not_added_to_the_count():
    """Graham counts shares "including the conversion of preferred" (table 18.6), but the
    tag carries conversions already done as well as conversions still to come, and the
    preferred count that separates them is filed under a class axis. So the overhang is
    stated and the denominator left alone — Structure Therapeutics' 67.0M sit inside its
    71.2M common already, and adding them would have restated every per-share figure."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 20e9, accn="q126")])
    gaap["PreferredStockLiquidationPreferenceValue"] = tagdata("USD", [
        inst("2026-03-31", 5e9, accn="q126")])
    gaap["ConvertiblePreferredStockSharesIssuedUponConversion"] = tagdata("shares", [
        inst("2026-03-31", 4e9, accn="q126")])
    s = build(gaap)
    assert float(s.shares_outstanding.value) == 20e9          # untouched
    assert float(s.preferred_stock.value) == 5e9              # still a senior claim
    note = next(n for n in s.context_notes if n["kind"] == "Convertible preferred")
    assert "4,000.0M shares" in note["text"] and "20,000.0M common" in note["text"]
    assert "capitalisation note" in note["text"]              # names the document to read


def test_a_small_conversion_right_is_not_worth_a_note():
    """The same 5% floor the warrant note uses: an overhang that cannot move a
    per-share figure meaningfully is noise on the page, not a disclosure."""
    gaap = dict(GAAP)
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [inst("2026-03-31", 20e9, accn="q126")])
    gaap["ConvertiblePreferredStockSharesIssuedUponConversion"] = tagdata("shares", [
        inst("2026-03-31", 1e8, accn="q126")])          # 0.5%
    s = build(gaap)
    assert not any(n["kind"] == "Convertible preferred" for n in s.context_notes)


JUNE_FILER = {
    # a Microsoft-shaped calendar: fiscal 2025 closes 2025-06-30, its 10-K lands
    # in August, and fiscal 2026 closes a year later
    "EarningsPerShareDiluted": tagdata("USD/shares", [
        dur("2023-07-01", "2024-06-30", 11.0, accn="k24", filed="2024-08-01"),
        dur("2024-07-01", "2025-06-30", 13.0, accn="k25", filed="2025-08-01"),
        dur("2025-07-01", "2026-06-30", 15.0, accn="k26", filed="2026-08-01"),
        # the quarters a reader standing on 2026-06-30 could already see
        dur("2025-07-01", "2025-09-30", 3.5, form="10-Q", accn="q126", filed="2025-10-25"),
        dur("2024-07-01", "2024-09-30", 3.0, form="10-Q", accn="q125", filed="2024-10-25"),
    ]),
    "Assets": tagdata("USD", [
        inst("2024-06-30", 460e9, form="10-K", accn="k24", filed="2024-08-01"),
        inst("2025-06-30", 500e9, form="10-K", accn="k25", filed="2025-08-01"),
        inst("2026-06-30", 560e9, form="10-K", accn="k26", filed="2026-08-01"),
    ]),
}


def test_fiscal_years_end_when_the_company_says_they_do():
    """Microsoft's fiscal 2026 closed 2026-06-30. Reading it as 2026-12-31 asked the
    price history for a December that has not arrived, so the newest P/E column was
    blank for 206 companies, and every older column divided a June balance sheet
    into the following December's market."""
    from screener.normalize import fiscal_year_ends
    ends = fiscal_year_ends(JUNE_FILER)
    assert ends[2025] == "2025-06-30"
    assert ends[2026] == "2026-06-30"


def test_vintage_earnings_are_cut_at_those_same_ends():
    """One helper feeds both series, so the keys cannot drift apart — and the newest
    fiscal year now HAS a figure, which is what the blank column was missing."""
    from screener.normalize import vintage_ttm_eps
    v = {d: float(x) for d, x in vintage_ttm_eps(JUNE_FILER).items()}
    assert "2026-06-30" in v          # the year the December cutoff could not reach
    # no look-ahead: the FY2026 10-K was filed in August, so a reader on 2026-06-30
    # had only the trailing four quarters through Q1 — 13.0 + 3.5 - 3.0
    assert v["2026-06-30"] == 13.5
    assert not any(d.endswith("-12-31") for d in v)


def _dimensioned(entries):
    return {"facts": {"us-gaap": {"PreferredStockSharesOutstanding": tagdata("shares", entries)}}}


CONVERTING = dict(GAAP) | {
    "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 20e9, accn="q126")]),
    "ConvertiblePreferredStockSharesIssuedUponConversion": tagdata("shares", [
        inst("2026-03-31", 4e9, accn="q126")]),
}


def test_a_preferred_that_already_converted_raises_no_warning():
    """Company Facts drops the preferred count because it is filed on a share-class
    axis; the DERA datasets keep the axis. Structure Therapeutics' 67.0M is its IPO
    conversion, already inside the common count — nothing to disclose."""
    s = build_snapshot("TEST", "0000000001", facts_doc(CONVERTING),
                       dimensioned=_dimensioned([
                           inst("2026-03-31", 0, form="10-K", accn="k25")
                           | {"segments": "ClassOfStock=SeriesAConvertiblePreferred;"}]))
    assert not any(n["kind"] == "Convertible preferred" for n in s.context_notes)


def test_a_live_preferred_is_named_with_what_is_outstanding():
    """Every class is summed rather than chosen: whether the conversion is still
    ahead of the company does not depend on which series it sits in."""
    s = build_snapshot("TEST", "0000000001", facts_doc(CONVERTING),
                       dimensioned=_dimensioned([
                           inst("2026-03-31", 30000, form="10-K", accn="k25")
                           | {"segments": "ClassOfStock=SeriesA;"},
                           inst("2026-03-31", 1333, form="10-K", accn="k25")
                           | {"segments": "ClassOfStock=SeriesB;"}]))
    note = next(n for n in s.context_notes if n["kind"] == "Convertible preferred")
    assert "31,333 preferred shares are still outstanding" in note["text"]


def test_a_total_beside_its_own_classes_is_not_added_to_them():
    """A filer that tags both the rollup and the parts would otherwise double."""
    s = build_snapshot("TEST", "0000000001", facts_doc(CONVERTING),
                       dimensioned=_dimensioned([
                           inst("2026-03-31", 31333, form="10-K", accn="k25"),
                           inst("2026-03-31", 30000, form="10-K", accn="k25")
                           | {"segments": "ClassOfStock=SeriesA;"},
                           inst("2026-03-31", 1333, form="10-K", accn="k25")
                           | {"segments": "ClassOfStock=SeriesB;"}]))
    note = next(n for n in s.context_notes if n["kind"] == "Convertible preferred")
    assert "31,333 preferred shares are still outstanding" in note["text"]


def test_no_preferred_count_on_file_says_so_rather_than_guessing():
    """The filers DERA does not reach keep the weaker note, not a wrong answer."""
    s = build(CONVERTING)
    note = next(n for n in s.context_notes if n["kind"] == "Convertible preferred")
    assert "no preferred count is on file" in note["text"]


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


def test_an_eps_its_own_filing_contradicts_is_replaced():
    """The Eastern Company's 2022 10-K tags $1.76 against fiscal 2020 while leaving
    that year's income and share count untouched at $5,405,522 on 6,264,521 shares —
    $0.86. A per-share figure moving while the two numbers it is made of stand still
    is a mis-tag wearing a restatement's clothes, and it withheld Eastern's P/E."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2019-12-29", "2021-01-02", 0.86, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 1.76, accn="k21", filed="2022-03-17"),
        ]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2019-12-29", "2021-01-02", 5405522, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 5405522, accn="k21", filed="2022-03-17"),
        ]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2019-12-29", "2021-01-02", 6264521, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 6264521, accn="k21", filed="2022-03-17"),
        ]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2020].value) == 0.86


def test_a_real_restatement_moves_the_income_with_it_and_is_kept():
    """Gyre's fiscal 2022 went from -$8.2M on 31.5M shares to +$4.3M on 75.7M after a
    reverse merger. Both inputs moved, so the newer per-share figure supersedes the
    older one and must survive — the check only fires when they stand still."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2022-01-01", "2022-12-31", -0.26, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 0.03, accn="k23", filed="2024-03-27"),
        ]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2022-01-01", "2022-12-31", -8242000, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 4314000, accn="k23", filed="2024-03-27"),
        ]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2022-01-01", "2022-12-31", 31545723, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 75686406, accn="k23", filed="2024-03-27"),
        ]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2022].value) == 0.03


def test_a_preferred_dividend_is_not_a_contradiction():
    """Markel's fiscal 2020 EPS of $55.63 divides to $59.03 on its own net income,
    and the $47M gap is its preferred dividend — earnings per share is struck on
    income available to the common. The same abstention `_basis_conflict` makes."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2020-01-01", "2020-12-31", 55.63, accn="k20", filed="2021-02-19")]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2020-01-01", "2020-12-31", 816030000, accn="k20", filed="2021-02-19")]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2020-01-01", "2020-12-31", 13823000, accn="k20", filed="2021-02-19")]),
        "PreferredStockDividendsAndOtherAdjustments": tagdata("USD", [
            dur("2020-01-01", "2020-12-31", 47060000, accn="k20", filed="2021-02-19")]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2020].value) == 55.63


def test_an_abandoned_tag_does_not_outrank_the_element_that_replaced_it():
    """Energy Transfer moved its redeemable minority interest to the `Other` element
    after 2025-12-31 and left the old one on file. Reading the old one first put
    $250M into a June balance sheet whose printed page says $256M, and the
    difference came straight off common equity. Newer wins."""
    gaap = dict(GAAP) | {
        "MinorityInterest": tagdata("USD", [
            inst("2026-06-30", 15191e6, accn="q226", filed="2026-08-06")]),
        # abandoned mid-history, still within the staleness window
        "RedeemableNoncontrollingInterestEquityCarryingAmount": tagdata("USD", [
            inst("2025-12-31", 250e6, form="10-K", accn="k25", filed="2026-02-19")]),
        "RedeemableNoncontrollingInterestEquityOtherCarryingAmount": tagdata("USD", [
            inst("2026-06-30", 256e6, accn="q226", filed="2026-08-06")]),
    }
    s = build(gaap)
    assert float(s.noncontrolling_interest.value) == 15191e6 + 256e6
    assert s.noncontrolling_interest.provenance.period_end.isoformat() == "2026-06-30"


def test_a_total_still_wins_over_its_own_components_at_one_date():
    """A rollup is the whole; the components on file may be a fragment of it. Only
    a newer date displaces it — UDR tags a component equal to its own total."""
    gaap = dict(GAAP) | {
        "MinorityInterest": tagdata("USD", [
            inst("2026-06-30", 100e6, accn="q226", filed="2026-08-06")]),
        "RedeemableNoncontrollingInterestEquityCarryingAmount": tagdata("USD", [
            inst("2026-06-30", 80e6, accn="q226", filed="2026-08-06")]),
        "RedeemableNoncontrollingInterestEquityCommonCarryingAmount": tagdata("USD", [
            inst("2026-06-30", 30e6, accn="q226", filed="2026-08-06")]),
    }
    s = build(gaap)
    assert float(s.noncontrolling_interest.value) == 180e6      # total, not the part


def test_the_parents_own_profit_outranks_a_longer_group_series():
    """Starwood Property Trust files fourteen years of NetIncomeLoss — $411.5M, what
    its printed income statement calls "Net income attributable to Starwood Property
    Trust" — beside sixteen years of ProfitLoss, the group's $443.1M including the
    minority holders. Ranking by depth let two extra years of history swap one for
    the other, and every margin and per-share figure then divided profit the
    shareholders do not own."""
    gaap = {
        "NetIncomeLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 411.5e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2012, 2026)]),
        "ProfitLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 443.1e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2010, 2026)]),
    }
    from screener.normalize import _annual_net_income
    series = _annual_net_income(gaap)
    assert float(series[2025].value) == 411.5e6
    assert "NetIncomeLoss" in series[2025].provenance.tag


def test_a_dead_parent_series_still_yields_to_a_live_group_one():
    """Advanced Energy's NetIncomeLoss stops while ProfitLoss runs on. Recency is
    still decided first: a figure of the right scope that stopped years ago is
    worse than a live one of the wrong scope, which is at least disclosed."""
    gaap = {
        "NetIncomeLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 100e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2015, 2024)]),
        "ProfitLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 120e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2015, 2026)]),
    }
    from screener.normalize import _annual_net_income
    assert float(_annual_net_income(gaap)[2025].value) == 120e6


def test_revenue_takes_the_total_over_its_own_contract_component():
    """Ovintiv files $8,663M of contract revenue beside $8,908M of `Revenues`, and
    its income statement prints the second as "Total Revenues" — the difference is
    revenue that did not come from a contract with a customer."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 8663e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "Revenues": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 8908e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 8908e6


def test_and_the_other_way_round_when_the_umbrella_tag_is_the_narrow_one():
    """Ares files the reverse: $5,601M of contract revenue against a $4,756M
    `Revenues` covering less than its own statement's "Total revenues". Whichever
    element holds the bigger figure is the total; the other is a piece of it."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 5601482e3, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "Revenues": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 4755618e3, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 5601482e3


def test_sales_tax_collected_for_the_state_is_never_revenue():
    """The comparison is only ever between a total and its own part. The assessed-tax
    pair does not stand in that relation, and taking the larger of THOSE would count
    sales taxes collected for the state as the company's own revenue."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 1000e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "RevenueFromContractWithCustomerIncludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 1080e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 1000e6


def test_a_brokers_top_line_is_revenue_net_of_interest_expense():
    """Interactive Brokers reports $7,782M of gross interest income against $6,205M
    of revenue net of interest expense — the figure its own income statement totals
    to. The component is the larger of the two, so no comparison by size can rank
    them; the concepts do it."""
    gaap = {
        "InterestIncomeOperating": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 7782e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2018, 2026)]),
        "RevenuesNetOfInterestExpense": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 6205e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    series = _annual_revenue(gaap)
    assert float(series[2025].value) == 6205e6


def test_interest_income_still_stands_where_there_is_no_net_line():
    """A filer that reports interest income and nothing wider keeps it: the rule
    replaces a component with its own total, never with nothing."""
    gaap = {
        "InterestIncomeOperating": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 500e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 500e6
