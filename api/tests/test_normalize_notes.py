"""The disclosures: what the figures do not say on their own, and the
guards that decide when a note is worth making."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot
from helpers import *  # noqa: F403 — the shared fixtures, by design
from helpers import EPS, GAAP, build, dur, facts_doc, inst, tagdata, texts
from helpers import _dimensioned, _reported, _shares, _years, _yr  # underscored, so `import *` skips them


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


def test_foreign_ifrs_facts_remain_explicitly_unsupported():
    facts = {"facts": {"ifrs-full": {
        "Revenue": tagdata("USD", [dur("2025-01-01", "2025-12-31", 1.0, form="20-F")])
    }}}
    with pytest.raises(UnsupportedFilerError, match="IFRS taxonomy"):
        build_snapshot("IFRS", "0000000002", facts)


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


def test_unchained_dividend_tag_gives_unknown_not_false():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DividendsDeclaredButUnpaid"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is None  # unknown, never a confident FAIL


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


def test_foreign_ifrs_filer_rejected():
    facts = {"facts": {"ifrs-full": {
        "Assets": tagdata("USD", [inst("2025-12-31", 1e9, form="20-F")])
    }}}
    with pytest.raises(UnsupportedFilerError, match="IFRS taxonomy"):
        build_snapshot("IFRS", "0000000003", facts)


def test_assume_zero_blocked_by_debt_evidence():
    # a material debt-instrument fact anywhere in history blocks the assumption
    gaap = dict(GAAP)
    gaap["UnsecuredDebt"] = tagdata("USD", [inst("2018-12-31", 500e6, form="10-K", accn="k18", filed="2019-02-15")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), assume_absent_zero=True)
    assert "debt" not in s.assumed_zero


def test_fiscal_year_label_january_end_belongs_to_prior_year():
    assert _fy_label(date(2026, 1, 31)) == 2025
    assert _fy_label(date(2025, 9, 27)) == 2025


def test_pretax_income_stands_in_when_no_operating_subtotal():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "OperatingIncomeLoss"}
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2025-01-01", "2025-12-31", 90e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 70e9  # 90 + 12 - 20 - 12
    assert any("pre-tax" in c for c in oe.caveats)


def test_income_tax_benefit_is_added_back_not_charged():
    """IncomeTaxExpenseBenefit is signed; a net-benefit year files it negative. Forcing
    it positive charged Uber for a benefit it received, twice over."""
    gaap = dict(OE_GAAP)
    gaap["IncomeTaxExpenseBenefit"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -20e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert float(oe.owner_earnings) == 120e9   # 100 + 12 - (-20) - 12


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


def test_lp_distributions_count_as_the_common_payout_epd_style():
    gaap = {k: v for k, v in GAAP.items() if k != "PaymentsOfDividendsCommonStock"}
    gaap["DistributionMadeToLimitedPartnerCashDistributionsPaid"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 1.2e9, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    assert s.pays_dividend is True
    assert "common" in s.dividend.provenance.concept


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


def test_one_time_gain_is_disclosed_with_flipped_wording():
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        tagdata("USD", [dur("2026-01-01", "2026-03-31", 1e9, form="10-Q", accn="q126", filed="2026-05-05")])
    gaap["GainLossOnInvestments"] = tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 300e6, form="10-Q", accn="q126", filed="2026-05-05")])
    s = build(gaap)
    note = next(n["text"] for n in s.earnings_quality if "investment gain" in n["text"].lower())
    assert "added to" in note  # positive gain BOOSTS income — opposite of a charge


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


def test_context_notes_flag_thin_interest_cover():
    gaap = dict(GAAP)
    gaap["OperatingIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 200e6, accn="k25", filed="2026-02-15")])
    gaap["InterestExpense"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    note = next(n for n in texts(build(gaap)) if "covers interest" in n)
    assert "2.0x" in note


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


def test_a_full_valuation_allowance_beside_profits_is_disclosed():
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 60e9)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 45e9)],
    )
    note = next(n for n in texts(build(gaap)) if "valuation allowance" in n)
    assert "75%" in note and "1,000M" in note


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


def test_the_series_rule_ranks_meaning_above_depth():
    """Written three times with the three keys in three different orders, two of them
    wrong. Recency first, so an abandoned element cannot answer for today; then what
    the element MEANS; then how much of it there is. Starwood files sixteen years of
    the group's profit beside fourteen of its own, and ranking depth second let two
    extra years swap one concept for the other."""
    from screener.normalize import _best_series
    parent = {y: y for y in range(2012, 2026)}          # 14 years, preferred concept
    group = {y: y for y in range(2010, 2026)}           # 16 years, wrong concept
    order = {"NetIncomeLoss": 0, "ProfitLoss": 2}
    tag, _ = _best_series([("NetIncomeLoss", parent), ("ProfitLoss", group)], order)
    assert tag == "NetIncomeLoss"

    # ...but a dead series of the right concept still yields to a live one
    stopped = {y: y for y in range(2012, 2024)}
    tag, _ = _best_series([("NetIncomeLoss", stopped), ("ProfitLoss", group)], order)
    assert tag == "ProfitLoss"


def test_a_preferred_concept_outranks_the_tag_order_itself():
    """§5.3 prefers continuing operations, which is a statement about scope rather
    than about which element a filer happens to use."""
    from screener.normalize import _best_series
    a = {y: y for y in range(2012, 2026)}
    b = {y: y for y in range(2012, 2026)}
    tag, _ = _best_series([("first", a), ("second", b)], {"first": 0, "second": 1},
                          prefer=lambda t: t == "second")
    assert tag == "second"
