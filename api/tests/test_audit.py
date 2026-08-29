"""The independent payload checker must compare like dates and shown precision."""

import json

from screener import audit


def test_debt_identity_does_not_add_older_components_to_a_newer_rollup():
    row = {
        "debt": 10.0,
        "total_debt": 10.0,
        "long_term_debt": 100.0,
        "short_term_debt": 20.0,
        "sources": {
            "total_debt": {"end": "2026-06-30"},
            "long_term_debt": {"end": "2025-12-31"},
            "short_term_debt": {"end": "2025-12-31"},
        },
        "criteria": [],
    }

    debt = next(item for item in audit._identities(row) if item[0] == "debt")

    assert debt[1] == 10.0
    assert debt[2] == 10.0


def test_ratio_slack_includes_four_decimal_price_rounding():
    slack = audit._rounding_slack(0.0011, 0.0057)

    assert audit._close(0.20, round(0.0011 / 0.0057, 2), slack)


def test_ratio_slack_allows_either_side_of_a_half_cent_boundary():
    slack = audit._rounding_slack(5.3, 8.48)

    assert audit._close(0.63, round(5.3 / 8.48, 2), slack)


def test_composite_source_keeps_candidates_from_each_filed_currency():
    facts = {"facts": {"us-gaap": {
        "MinorityInterest": {"units": {
            "CNY": [{"end": "2025-12-31", "val": 4_700, "accn": "a"}],
            "USD": [{"end": "2025-12-31", "val": 670, "accn": "a"}],
        }},
        "RedeemableNoncontrollingInterestEquityCarryingAmount": {"units": {
            "CNY": [{"end": "2025-12-31", "val": 107, "accn": "a"}],
            "USD": [{"end": "2025-12-31", "val": 17, "accn": "a"}],
        }},
    }}}
    source = {
        "tag": ("us-gaap:MinorityInterest + "
                "us-gaap:RedeemableNoncontrollingInterestEquityCarryingAmount"),
        "components": [
            {"tag": "us-gaap:MinorityInterest", "accn": "a", "end": "2025-12-31"},
            {"tag": "us-gaap:RedeemableNoncontrollingInterestEquityCarryingAmount",
             "accn": "a", "end": "2025-12-31"},
        ],
    }

    assert 687 in audit._source_values(facts, source)
    assert 4_807 in audit._source_values(facts, source)


def test_derived_source_subtracts_each_filed_currency_candidate():
    facts = {"facts": {"us-gaap": {
        "FiniteLivedIntangibleAssetsGross": {"units": {
            "CNY": [{"end": "2025-12-31", "val": 140, "accn": "a"}],
            "USD": [{"end": "2025-12-31", "val": 20, "accn": "a"}],
        }},
        "FiniteLivedIntangibleAssetsAccumulatedAmortization": {"units": {
            "CNY": [{"end": "2025-12-31", "val": 21, "accn": "a"}],
            "USD": [{"end": "2025-12-31", "val": 3, "accn": "a"}],
        }},
    }}}
    source = {
        "tag": ("us-gaap:FiniteLivedIntangibleAssetsGross - "
                "us-gaap:FiniteLivedIntangibleAssetsAccumulatedAmortization"),
        "accn": "a", "end": "2025-12-31",
        "components": [
            {"tag": "us-gaap:FiniteLivedIntangibleAssetsGross", "accn": "a",
             "end": "2025-12-31"},
            {"tag": "us-gaap:FiniteLivedIntangibleAssetsAccumulatedAmortization",
             "accn": "a", "end": "2025-12-31"},
        ],
    }

    assert 17 in audit._source_values(facts, source)
    assert 119 in audit._source_values(facts, source)
    source.pop("components")
    assert 17 in audit._source_values(facts, source)


def test_audit_checks_annualized_recurring_dividend_against_its_quarter(tmp_path):
    cik = "0000000001"
    facts = {"facts": {"us-gaap": {
        "CommonStockDividendsPerShareCashPaid": {"units": {"USD/shares": [{
            "start": "2026-01-01", "end": "2026-03-31", "val": 0.35,
            "accn": "q126", "form": "10-Q", "filed": "2026-05-05",
        }]}}
    }}}
    (tmp_path / f"companyfacts_{cik}.json").write_text(json.dumps(facts))
    row = {
        "cik": cik,
        "ticker": "TEST",
        "recurring_dividend_per_share": 1.40,
        "sources": {"recurring_dividend_per_share": {
            "tag": "us-gaap:CommonStockDividendsPerShareCashPaid",
            "form": "10-Q", "accn": "q126", "start": "2026-01-01",
            "end": "2026-03-31",
            "filed": "2026-05-05",
        }},
        "criteria": [],
    }

    result = audit.audit([row], tmp_path, quiet=True)

    assert result["totals"]["sourced_ok"] == 1
    assert result["totals"]["sourced_bad"] == 0


def test_duration_source_start_distinguishes_quarter_from_ytd_in_same_filing():
    facts = {"facts": {"us-gaap": {
        "CommonStockDividendsPerShareDeclared": {"units": {"USD/shares": [
            {"start": "2026-01-01", "end": "2026-06-30", "val": 0.44,
             "accn": "q226"},
            {"start": "2026-04-01", "end": "2026-06-30", "val": 0.22,
             "accn": "q226"},
        ]}}
    }}}
    source = {
        "tag": "us-gaap:CommonStockDividendsPerShareDeclared",
        "accn": "q226", "start": "2026-04-01", "end": "2026-06-30",
    }

    assert audit._source_values(facts, source) == [0.22]


def test_duration_source_unit_distinguishes_usd_rate_from_foreign_currency():
    facts = {"facts": {"us-gaap": {
        "CommonStockDividendsPerShareDeclared": {"units": {
            "CAD/shares": [{"start": "2026-04-01", "end": "2026-06-30",
                            "val": 0, "accn": "q226"}],
            "USD/shares": [{"start": "2026-04-01", "end": "2026-06-30",
                            "val": 0.03, "accn": "q226"}],
        }}
    }}}
    source = {
        "tag": "us-gaap:CommonStockDividendsPerShareDeclared", "accn": "q226",
        "start": "2026-04-01", "end": "2026-06-30", "unit": "USD/shares",
    }

    assert audit._source_values(facts, source) == [0.03]


def test_ch13_average_uses_decimal_inputs_before_display_rounding():
    row = {
        "annual_eps": {"2023": -0.085, "2024": 0.082, "2025": 0.108},
        "ch13": {"latest_fy": 2025, "avg_recent": 0.04,
                 "ten_year_present": 3, "ten_year_positive": 2},
    }

    checks = {name: (shown, expected) for name, shown, expected, *_ in
              audit._derived_series(row)}
    assert checks["ch13.avg_recent"] == (0.04, 0.04)
