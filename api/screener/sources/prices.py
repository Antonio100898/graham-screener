"""Layer 1: price quotes behind a swappable PriceProvider protocol."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from ..models import PriceHistory, Quote


class PriceProvider(Protocol):
    def quote(self, ticker: str) -> Quote | None: ...
    def history(self, ticker: str) -> PriceHistory | None: ...


YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"

_BAD = (httpx.HTTPError, InvalidOperation, KeyError, IndexError, TypeError, ValueError)


class YahooPriceProvider:
    # ponytail: free unofficial Yahoo endpoint; swap in a paid PriceProvider impl for production SLAs
    def __init__(self, timeout: float = 20.0):
        self._http = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        )

    def _chart(self, ticker: str, range_: str, interval: str) -> dict | None:
        # Yahoo uses dash-form class symbols (BRK-B), matching SEC's ticker map
        symbol = ticker.strip().upper().replace(".", "-")
        try:
            resp = self._http.get(YAHOO_URL.format(symbol=symbol, range=range_, interval=interval))
            resp.raise_for_status()
            return resp.json()["chart"]["result"][0]
        except _BAD:
            return None  # unavailable is the protocol's signal -> criteria 1/7 go INSUFFICIENT

    @staticmethod
    def _quote_from(result: dict) -> Quote | None:
        try:
            meta = result["meta"]
            return Quote(price=Decimal(str(meta["regularMarketPrice"])),
                         asof=datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc),
                         source="yahoo")
        except _BAD:
            return None

    def quote(self, ticker: str) -> Quote | None:
        result = self._chart(ticker, "1d", "1d")
        return self._quote_from(result) if result else None

    def history(self, ticker: str) -> PriceHistory | None:
        """Five years of weekly closes, and the live quote that comes with them.

        One request serves both: the chart response carries the same `meta` block
        the quote endpoint returns, so asking for history costs no extra call.
        """
        result = self._chart(ticker, "5y", "1wk")
        if not result:
            return None
        q = self._quote_from(result)
        if q is None:
            return None
        try:
            stamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
        except _BAD:
            return PriceHistory(quote=q, closes=())
        series = tuple(
            (datetime.fromtimestamp(t, tz=timezone.utc).date(), Decimal(str(c)))
            # a null close is a week the exchange reported nothing; dropping it
            # keeps a hole from being read as a crash to zero
            for t, c in zip(stamps, closes) if c is not None
        )
        return PriceHistory(quote=q, closes=series)
