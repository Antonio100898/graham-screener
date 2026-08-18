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
