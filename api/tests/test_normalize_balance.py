"""What the company owns and owes at one moment, and everything standing
between the assets and the common shareholder."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot
from helpers import *  # noqa: F403 — the shared fixtures, by design
from helpers import EPS, GAAP, build, dur, facts_doc, inst, tagdata, texts
from helpers import _dimensioned, _reported, _shares, _years, _yr  # underscored, so `import *` skips them


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


def test_long_term_debt_total_tag_not_double_counted_in_short_bucket():
    gaap = dict(GAAP)
    gaap["LongTermDebt"] = tagdata("USD", [inst("2026-03-31", 100e9, accn="q126")])
    gaap["LongTermDebtCurrent"] = tagdata("USD", [inst("2026-03-31", 11e9, accn="q126")])
    gaap["CommercialPaper"] = tagdata("USD", [inst("2026-03-31", 2e9, accn="q126")])
    s = build(gaap)
    assert float(s.long_term_debt.value) == 100e9  # includes current maturities already
    assert float(s.short_term_debt.value) == 2e9  # only genuine short-term borrowings


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


def test_asset_side_debt_securities_are_not_debt_evidence():
    # investments in debt securities and undrawn revolver capacity are not liabilities
    gaap = dict(GAAP)
    gaap["AvailableForSaleSecuritiesDebtSecurities"] = tagdata("USD", [inst("2026-03-31", 7.6e9, accn="q126")])
    gaap["LineOfCreditFacilityMaximumBorrowingCapacity"] = tagdata("USD", [inst("2026-03-31", 800e6, accn="q126")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), assume_absent_zero=True)
    assert "debt" in s.assumed_zero


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


def test_no_classified_balance_sheet_yields_earnings_without_a_return():
    """Banks report no current liabilities, so invested capital cannot be separated —
    the earnings still compute, the ratio does not."""
    gaap = {k: v for k, v in OE_GAAP.items() if k != "LiabilitiesCurrent"}
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 80e9
    assert oe.invested_capital is None and oe.roic is None


def test_bvps_keeps_intangibles_that_tbvps_removes():
    from screener.sync import _bvps, _tbvps
    s = build()
    # assets 1000 - liabilities 400 = 600 over 10B shares
    assert _bvps(s) == 60.0
    # tangible additionally sheds goodwill 50 and intangibles 30
    assert _tbvps(s) == 52.0


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


def test_negative_assets_are_a_sign_error_not_a_balance_sheet():
    gaap = dict(GAAP)
    gaap["AssetsCurrent"] = tagdata("USD", [inst("2026-03-31", -26, accn="q126")])
    s = build(gaap)
    assert s.current_assets is None


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
