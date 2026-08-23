"""The independent payload checker must compare like dates and shown precision."""

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
