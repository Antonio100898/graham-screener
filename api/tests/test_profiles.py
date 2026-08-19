"""Profile alignment and displayed-precision valuation-boundary behavior."""
from decimal import Decimal

from screener.profiles import (PROFILE_FINANCIAL, PROFILE_OPERATING, PROFILE_UTILITY,
                               enrich, profile_for)
from screener.sync import apply_price


def screen_row():
    return {
        "sector": "Industrials",
        "price": 10.0,
        "ttm_eps": 1.5,
        "tbvps": 12.0,
        "bvps": 10.0,
        "shares": 10_000_000,
        "ttm_revenue": 150_000_000,
        "current_assets": 300_000_000,
        "current_liabilities": 100_000_000,
        "long_term_debt": 100_000_000,
        "total_assets": 600_000_000,
        "total_liabilities": 250_000_000,
        "annual_eps": {"2016": 0.5, "2017": 0.6, "2018": 0.7, "2019": 0.8, "2020": 0.9, "2021": 1.0, "2022": 1.1, "2023": 1.2, "2024": 1.3, "2025": 1.4},
        "ch13": {"growth_10y": 40.0},
        "dividend_record": {"first": 2000, "streak_from": 2000, "latest": 2025},
        "criteria": [{"n": n, "status": "PASS"} for n in (1, 2, 3, 4, 5, 7)],
    }


def price_row(ttm=5.0, tbvps=10.0):
    return {
        "ttm_eps": ttm,
        "tbvps": tbvps,
        "criteria": [
            {"n": 1, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
            *[{"n": n, "status": "PASS", "value": None, "note": None} for n in (2, 3, 4, 5)],
            {"n": 7, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
        ],
    }


def criterion(row, number):
    return next(c for c in row["criteria"] if c["n"] == number)


def test_profile_mapping_keeps_financials_out_of_industrial_screen():
    assert profile_for("Industrials") == PROFILE_OPERATING
    assert profile_for("Utilities") == PROFILE_UTILITY
    assert profile_for("Financials") == PROFILE_FINANCIAL
    financial = enrich({**screen_row(), "sector": "Financials"})
    assert financial["alignment"]["enterprising"]["verdict"] == "OUT_OF_SCOPE"
    assert financial["alignment"]["defensive"]["verdict"] == "OUT_OF_SCOPE"


def test_operating_profile_exposes_both_alignments_and_modern_growth_label():
    result = enrich(screen_row())
    assert result["graham_profile"] == PROFILE_OPERATING
    assert result["alignment"]["enterprising"]["verdict"] == "ALIGNED"
    growth = result["alignment"]["enterprising"]["growth_modern_4fy"]
    assert growth["status"] == "PASS"
    assert growth["base_fy"] == 2021 and growth["latest_fy"] == 2025
    assert result["alignment"]["defensive"]["verdict"] == "ALIGNED"


def test_defensive_valuation_uses_displayed_two_decimal_boundary():
    row = screen_row()
    # 22.503... rounds to the displayed 22.50× and therefore passes by product policy.
    row.update({"price": 16.35, "bvps": 9.817500776008213,
                "annual_eps": {"2013": 1.00, "2014": 1.10, "2015": 1.20,
                               "2016": 1.30, "2017": 1.40, "2018": 1.50,
                               "2019": 1.60, "2020": 1.70, "2021": 1.80,
                               "2022": 1.90, "2023": 0.86, "2024": 1.68, "2025": 1.09}})
    result = enrich(row)
    assert result["alignment"]["defensive"]["tests"]["valuation"] == "PASS"

    # A product that displays as 22.51× remains a fail.
    row["price"] = 16.36
    result = enrich(row)
    assert result["alignment"]["defensive"]["tests"]["valuation"] == "FAIL"


def test_utility_uses_the_utility_financial_position_rule():
    row = screen_row()
    row.update({
        "sector": "Utilities",
        "total_assets": 100_000_000,
        "total_liabilities": 60_000_000,
        "long_term_debt": 80_000_000,  # exactly twice equity
    })
    result = enrich(row)
    assert result["graham_profile"] == PROFILE_UTILITY
    assert result["alignment"]["defensive"]["tests"]["financial_position"] == "PASS"
    assert result["alignment"]["enterprising"]["verdict"] == "OUT_OF_SCOPE"


def test_export_valuation_uses_raw_threshold_not_rounded_display_ratio():
    # 9.999 is below 10 and must pass, even though reader display rounds to 10.00.
    out = apply_price(price_row(ttm=1.0, tbvps=100.0), price=9.999)
    assert criterion(out, 1)["status"] == "PASS"
    assert criterion(out, 1)["value"] == 10.0

    # 1.204 is above 1.20 and must fail, even though reader display rounds to 1.20.
    out = apply_price(price_row(ttm=10.0, tbvps=100.0), price=120.4)
    assert criterion(out, 7)["status"] == "FAIL"
    assert criterion(out, 7)["value"] == 1.2

    # Graham's text says less than 120%; equality is not a pass.
    out = apply_price(price_row(ttm=10.0, tbvps=100.0), price=120.0)
    assert criterion(out, 7)["status"] == "FAIL"


def test_verified_non_payer_fails_defensive_dividend_record():
    # criterion 5 FAIL = verifiably pays nothing now; a 20-year uninterrupted
    # record is then impossible, whatever the historical paid years show
    row = screen_row()
    next(c for c in row["criteria"] if c["n"] == 5)["status"] = "FAIL"
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "FAIL"


def test_unknown_dividend_status_stays_incomplete_not_fail():
    row = screen_row()
    next(c for c in row["criteria"] if c["n"] == 5)["status"] = "INSUFFICIENT_DATA"
    row["dividend_record"] = None
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def young_row():
    # listed 2018: the whole public record is 8 years, complete
    row = screen_row()
    row["annual_eps"] = {"2018": 1.0, "2019": 1.1, "2020": 1.2, "2021": 1.4,
                         "2022": 1.6, "2023": 1.8, "2024": 1.9, "2025": 2.0}
    row["ch13"] = {}
    row["dividend_record"] = {"first": 2018, "streak_from": 2018, "latest": 2025, "paid_years": 8}
    row["first_filed"] = "2018-02-01"  # the company itself is young, not just its tags
    return row


def test_short_history_company_is_judged_over_its_whole_record():
    result = enrich(young_row())["alignment"]["defensive"]
    tests, windowed = result["tests"], result["windowed"]
    assert tests["stability_10y"] == "PASS"           # 8 of 8 years, no deficit
    assert tests["dividend_20y"] == "PASS"            # paid every year since listing
    # base avg3(2018-20)=1.1, recent avg3(2023-25)=1.9 -> +72.7% over 5-year
    # spacing, against the scaled (4/3)^0.5-1 = 15.5% threshold
    assert tests["growth_10y"] == "PASS"
    assert "8-year" in windowed["stability_10y"]
    assert "8-year" in windowed["dividend_20y"]
    assert "5-year spacing" in windowed["growth_10y"]


def test_windowing_never_applies_to_a_gappy_or_pre_xbrl_record():
    # same span but one missing year: dataset truncation, not a short history
    gappy = young_row()
    del gappy["annual_eps"]["2020"]
    tests = enrich(gappy)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["growth_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"

    # record starting in the XBRL phase-in years could belong to an older company
    old = young_row()
    old["annual_eps"] = {str(y): 1.0 for y in range(2010, 2017)}
    old["dividend_record"] = {"first": 2010, "streak_from": 2010, "latest": 2016, "paid_years": 7}
    tests = enrich(old)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def test_late_tag_adoption_never_counts_as_a_short_history_arcc_style():
    """ARCC's EPS record starts in 2020 because the BDC per-share element is
    young; the company has filed since 2004 — no windowed passes for it."""
    row = young_row()
    row["first_filed"] = "2004-10-08"
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"
    assert tests["growth_10y"] == "INSUFFICIENT_DATA"

    # unknown listing age is treated the same: no corroboration, no window
    row["first_filed"] = None
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"


def test_filing_years_without_a_dividend_disprove_the_twenty_year_record():
    """BCC: paid every year since 2017, but its own earnings series covers
    2013-2016 with no dividend — 20 uninterrupted years is impossible, not
    merely unproven."""
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2011, 2026)}
    row["dividend_record"] = {"first": 2017, "streak_from": 2017, "latest": 2026, "paid_years": 10}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "FAIL"


def test_a_young_company_is_not_failed_for_years_it_did_not_exist():
    # listed 2018, paying since 2018: no filing year inside the window is silent
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2018, 2026)}
    row["dividend_record"] = {"first": 2018, "streak_from": 2018, "latest": 2026, "paid_years": 9}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def test_early_xbrl_tagging_gap_never_disproves_the_record():
    # only pre-2013 years are silent: dividend tagging was not yet universal
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2011, 2026)}
    row["dividend_record"] = {"first": 2013, "streak_from": 2013, "latest": 2026, "paid_years": 14}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def taxed_row(untaxed=4, profitable=9, **over):
    row = screen_row()
    row["tax_record"] = {"window_from": 2016, "window_to": 2025, "profitable_years": profitable,
                         "untaxed_years": untaxed, "pass_through": False}
    row.update(over)
    return row


def test_profits_without_tax_carry_the_penn_central_warning():
    note = enrich(taxed_row())["context_notes"][-1]
    assert "Penn Central" in note and "4 of 9" in note


def test_a_pass_through_structure_is_explained_not_accused():
    row = taxed_row()
    row["tax_record"]["pass_through"] = True
    note = enrich(row)["context_notes"][-1]
    assert "pass-through" in note and "Penn Central" not in note

    # a REIT is a pass-through the facts alone cannot show; its industry does
    reit = taxed_row(industry="Real Estate Investment Trusts")
    assert "pass-through" in enrich(reit)["context_notes"][-1]


def test_an_ordinary_tax_record_says_nothing():
    assert enrich(taxed_row(untaxed=1))["context_notes"] == []
    assert enrich(screen_row())["context_notes"] == []


def test_a_margin_far_under_the_industry_median_is_stated():
    row = screen_row()
    row["peer_efficiency"] = {"margin": 4.2, "industry_median": 12.5, "peers": 18, "behind": True}
    note = enrich(row)["context_notes"][-1]
    assert "4.2%" in note and "12.5%" in note and "18 companies" in note


def test_a_margin_in_line_with_peers_says_nothing():
    row = screen_row()
    row["peer_efficiency"] = {"margin": 11.0, "industry_median": 12.5, "peers": 18, "behind": False}
    assert enrich(row)["context_notes"] == []
