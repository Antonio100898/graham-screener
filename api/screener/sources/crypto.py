"""Public crypto product discovery and live USD quotes.

Coinbase Exchange exposes its product catalogue and last-trade ticker without
credentials.  A short quote cache keeps one portfolio render from asking for the
same market twice while still allowing the browser to refresh values frequently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import time

import httpx


PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
CURRENCIES_URL = "https://api.exchange.coinbase.com/currencies"
TICKER_URL = "https://api.exchange.coinbase.com/products/{product_id}/ticker"
_BAD = (httpx.HTTPError, InvalidOperation, KeyError, TypeError, ValueError)


@dataclass(frozen=True)
class CryptoQuote:
    product_id: str
    price: Decimal
    asof: datetime
    source: str = "coinbase"


class CoinbaseCryptoProvider:
    def __init__(self, timeout: float = 10.0, *, product_cache_seconds: int = 3600,
                 quote_cache_seconds: int = 5):
        self._http = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "graham-screener/1.0"},
        )
        self._product_cache_seconds = product_cache_seconds
        self._quote_cache_seconds = quote_cache_seconds
        self._products: list[dict] | None = None
        self._products_at = 0.0
        self._quotes: dict[str, tuple[float, CryptoQuote]] = {}

    def close(self) -> None:
        self._http.close()

    def _json(self, url: str):
        try:
            response = self._http.get(url)
            response.raise_for_status()
            return response.json()
        except _BAD:
            return None

    def products(self, quote_currency: str = "USD") -> list[dict] | None:
        now = time.monotonic()
        if self._products is None or now - self._products_at >= self._product_cache_seconds:
            products = self._json(PRODUCTS_URL)
            currencies = self._json(CURRENCIES_URL)
            if not isinstance(products, list) or not isinstance(currencies, list):
                return None
            currency_by_id = {
                item.get("id"): item for item in currencies
                if isinstance(item, dict) and item.get("id")
            }
            discovered = []
            for product in products:
                if not isinstance(product, dict):
                    continue
                base = currency_by_id.get(product.get("base_currency"), {})
                if ((base.get("details") or {}).get("type") != "crypto"
                        or product.get("status") != "online"
                        or product.get("trading_disabled") is True):
                    continue
                discovered.append({
                    "id": product.get("id"),
                    "symbol": product.get("base_currency"),
                    "name": base.get("name") or product.get("base_currency"),
                    "display_name": product.get("display_name") or product.get("id"),
                    "quote_currency": product.get("quote_currency"),
                })
            self._products = [item for item in discovered if item["id"]]
            self._products_at = now

        currency = quote_currency.strip().upper()
        return sorted(
            (dict(item) for item in self._products if item["quote_currency"] == currency),
            key=lambda item: (item["symbol"], item["id"]),
        )

    def quote(self, product_id: str) -> CryptoQuote | None:
        product_id = product_id.strip().upper()
        now = time.monotonic()
        cached = self._quotes.get(product_id)
        if cached and now - cached[0] < self._quote_cache_seconds:
            return cached[1]
        payload = self._json(TICKER_URL.format(product_id=product_id))
        if not isinstance(payload, dict):
            return None
        try:
            price = Decimal(str(payload["price"]))
            asof = datetime.fromisoformat(str(payload["time"]).replace("Z", "+00:00"))
            if not price.is_finite() or price <= 0 or asof.tzinfo is None:
                return None
            quote = CryptoQuote(
                product_id=product_id,
                price=price,
                asof=asof.astimezone(timezone.utc),
            )
        except _BAD:
            return None
        self._quotes[product_id] = (now, quote)
        return quote

    def cached_quote(self, product_id: str) -> CryptoQuote | None:
        cached = self._quotes.get(product_id.strip().upper())
        return cached[1] if cached else None
