"""The real-company regression gate must include final UI calculations."""

from screener.regress import _flat


def test_only_current_quote_fields_are_volatile_not_historical_multiples():
    row = {
        "price": 100.0,
        "price_asof": "2026-08-23T00:00:00+00:00",
        "market_cap": 1_000_000.0,
        "dividend_yield": 2.5,
        "annual_ratios": {"2025": {"price": 90.0, "pe": 12.0, "pb": 3.0}},
    }

    flat = _flat(row)

    assert "price" not in flat and "price_asof" not in flat
    assert flat["market_cap"] == 1_000_000.0
    assert flat["dividend_yield"] == 2.5
    assert flat["annual_ratios.2025.price"] == 90.0
    assert flat["annual_ratios.2025.pe"] == 12.0
    assert flat["annual_ratios.2025.pb"] == 3.0
