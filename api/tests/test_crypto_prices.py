from datetime import datetime, timezone
from decimal import Decimal

from screener.sources.crypto import (
    CURRENCIES_URL,
    PRODUCTS_URL,
    CoinbaseCryptoProvider,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_coinbase_products_keep_active_crypto_pairs_in_requested_currency(monkeypatch):
    provider = CoinbaseCryptoProvider()
    payloads = {
        PRODUCTS_URL: [
            {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD",
             "display_name": "BTC/USD", "status": "online", "trading_disabled": False},
            {"id": "BTC-EUR", "base_currency": "BTC", "quote_currency": "EUR",
             "display_name": "BTC/EUR", "status": "online", "trading_disabled": False},
            {"id": "OLD-USD", "base_currency": "OLD", "quote_currency": "USD",
             "display_name": "OLD/USD", "status": "offline", "trading_disabled": True},
            {"id": "EUR-USD", "base_currency": "EUR", "quote_currency": "USD",
             "display_name": "EUR/USD", "status": "online", "trading_disabled": False},
        ],
        CURRENCIES_URL: [
            {"id": "BTC", "name": "Bitcoin", "details": {"type": "crypto"}},
            {"id": "OLD", "name": "Old coin", "details": {"type": "crypto"}},
            {"id": "EUR", "name": "Euro", "details": {"type": "fiat"}},
        ],
    }
    monkeypatch.setattr(provider._http, "get", lambda url: Response(payloads[url]))

    assert provider.products("USD") == [{
        "id": "BTC-USD", "symbol": "BTC", "name": "Bitcoin",
        "display_name": "BTC/USD", "quote_currency": "USD",
    }]
    assert provider.products("EUR")[0]["id"] == "BTC-EUR"
    provider.close()


def test_coinbase_quote_preserves_decimal_price_time_and_short_cache(monkeypatch):
    provider = CoinbaseCryptoProvider(quote_cache_seconds=60)
    calls = []

    def get(url):
        calls.append(url)
        return Response({"price": "61345.12000000", "time": "2026-08-30T18:45:01.250Z"})

    monkeypatch.setattr(provider._http, "get", get)
    first = provider.quote("btc-usd")
    second = provider.quote("BTC-USD")

    assert first == second
    assert first.price == Decimal("61345.12000000")
    assert first.asof == datetime(2026, 8, 30, 18, 45, 1, 250000, tzinfo=timezone.utc)
    assert first.source == "coinbase"
    assert len(calls) == 1
    provider.close()


def test_invalid_coinbase_price_is_unavailable(monkeypatch):
    provider = CoinbaseCryptoProvider()
    monkeypatch.setattr(
        provider._http, "get",
        lambda _url: Response({"price": "0", "time": "2026-08-30T18:45:01Z"}),
    )

    assert provider.quote("BTC-USD") is None
    provider.close()
