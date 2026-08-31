"""Layer 4: FastAPI wiring. Serialisation only; no business logic."""
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, evidence, jobs, portfolio, pricestats, store
from .models import CriterionResult, Fact, FinancialSnapshot, ScreenResult
from .normalize import UnsupportedFilerError, build_snapshot
from .screens.enterprising import evaluate
from .sources.edgar import EdgarClient, EdgarError, NoXbrlDataError, UnknownTickerError
from .sources.crypto import CoinbaseCryptoProvider
from .sources.prices import YahooPriceProvider


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    jobs.start_hourly_quotes()
    try:
        yield
    finally:
        jobs.stop_hourly_quotes()


app = FastAPI(title="Graham Enterprising Screener", version="1.0", lifespan=_lifespan)
# no-op unless SCREENER_TOKEN is set, which is how a tunnelled instance is run
app.middleware("http")(auth.require_token)
# The dashboard payload is one 35MB JSON document of mostly repeated keys; it
# compresses to about an eighth of that, and the UI downloads all of it on every
# first visit.
app.add_middleware(GZipMiddleware, minimum_size=1024)
_edgar = EdgarClient()
_prices = YahooPriceProvider()
_crypto = CoinbaseCryptoProvider()


def _snapshot_for(ticker: str, assume_absent_zero: bool = False) -> FinancialSnapshot:
    try:
        cik = _edgar.cik_for(ticker)
        facts = _edgar.company_facts(cik)
    except UnknownTickerError:
        raise HTTPException(
            404, f"unknown ticker {ticker}: not in SEC mapping (delisted or never SEC-registered)"
        )
    except NoXbrlDataError:
        raise HTTPException(
            404,
            f"no XBRL data for {ticker}: the filer has never submitted structured data "
            "(typical for ADR shells and pre-2009 registrants)",
        )
    except EdgarError as exc:
        raise HTTPException(502, f"EDGAR unavailable: {exc}")
    try:
        conn = store.connect()
        try:
            bundle = evidence.EvidenceLoader(conn, _edgar).load(cik, ticker.upper(), facts)
        finally:
            conn.close()
        return build_snapshot(bundle.ticker, bundle.cik, bundle.facts,
                              assume_absent_zero=assume_absent_zero,
                              dimensioned=bundle.dimensioned, receipt=bundle.receipt)
    except UnsupportedFilerError as exc:
        raise HTTPException(422, str(exc))


def _price_stats(hist) -> dict | None:
    """Disclosure beside the verdict: where the price sits in its own history."""
    if hist is None or not hist.closes:
        return None
    stats = pricestats.compute(hist.closes, hist.quote.price)
    return None if stats is None else {k: _num(v) if isinstance(v, Decimal) else v
                                       for k, v in stats.items()}


@app.get("/screen/enterprising/{ticker}")
def screen_enterprising(ticker: str, assume_absent_zero: bool = False):
    snap = _snapshot_for(ticker, assume_absent_zero)
    # one request carries both the quote and the five-year weekly series
    hist = _prices.history(ticker)
    result = _screen_dict(evaluate(snap, hist.quote if hist else None))
    result["price_stats"] = _price_stats(hist)
    return result


class BatchRequest(BaseModel):
    tickers: list[str]
    assume_absent_zero: bool = False


@app.post("/screen/enterprising")
def screen_enterprising_batch(req: BatchRequest):
    results = []
    for ticker in req.tickers:
        try:
            snap = _snapshot_for(ticker, req.assume_absent_zero)
            results.append(_screen_dict(evaluate(snap, _prices.quote(ticker))))
        except HTTPException as exc:
            results.append({"ticker": ticker.upper(), "error": exc.detail})
        except Exception as exc:  # one malformed filing must not void the whole batch
            results.append({"ticker": ticker.upper(), "error": f"internal error: {exc!r}"})
    return {"results": results}


@app.get("/fundamentals/{ticker}")
def fundamentals(ticker: str, assume_absent_zero: bool = False):
    return _snapshot_dict(_snapshot_for(ticker, assume_absent_zero))


STATIC = Path(__file__).parent / "static"


class SyncRequest(BaseModel):
    command: str  # bootstrap | bulk | daily | derive | quotes | export
    days: int = 7


@app.post("/sync")
def sync_start(req: SyncRequest):
    """Kick off a load in the background. One at a time — a second heavy load
    while one runs only makes both slower and fights the SEC rate limiter."""
    started, message = jobs.start(req.command, days=req.days)
    if not started:
        raise HTTPException(409, message)
    return {"started": True, "command": req.command, "message": message}


@app.post("/sync/cancel")
def sync_cancel():
    """Stops at the next checkpoint; everything already committed is kept."""
    if not jobs.cancel():
        raise HTTPException(409, "no job is running")
    return {"cancelling": True}


@app.get("/sync/status")
def sync_status():
    return jobs.status()


class TrackRequest(BaseModel):
    cik: str
    note: str | None = None


@app.get("/tracked")
def tracked_list():
    conn = store.connect()
    try:
        return {"tracked": store.tracked(conn)}
    finally:
        conn.close()


@app.post("/tracked")
def tracked_add(req: TrackRequest):
    conn = store.connect()
    try:
        store.track(conn, req.cik, req.note)
        return {"tracked": True, "cik": req.cik}
    finally:
        conn.close()


@app.delete("/tracked/{cik}")
def tracked_remove(cik: str):
    conn = store.connect()
    try:
        if not store.untrack(conn, cik):
            raise HTTPException(404, f"{cik} is not tracked")
        return {"tracked": False, "cik": cik}
    finally:
        conn.close()


class PortfolioRequest(BaseModel):
    name: str
    base_currency: str = "USD"


class PortfolioTradeRequest(BaseModel):
    cik: str
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: Decimal
    price: Decimal
    fees: Decimal = Decimal("0")
    currency: str = "USD"
    executed_at: datetime
    broker: str | None = None
    account_label: str | None = None
    external_id: str | None = None
    note: str | None = None


class PortfolioAssetRequest(BaseModel):
    asset_type: Literal["BOND", "CRYPTO"]
    name: str
    symbol: str | None = None
    quantity: Decimal
    current_price: Decimal | None = None
    currency: str = "USD"
    note: str | None = None


class PortfolioCashRequest(BaseModel):
    amount: Decimal


@lru_cache(maxsize=2)
def _dashboard_payload_cached(path: str, modified_ns: int) -> dict:
    # `modified_ns` is deliberately part of the key: a completed export becomes
    # visible to portfolio P&L without restarting the API process.
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _dashboard_payload() -> dict:
    path = STATIC / "dashboard.json"
    if not path.exists():
        raise HTTPException(404, "dashboard.json not built — run: python -m screener.sync export")
    return _dashboard_payload_cached(str(path), path.stat().st_mtime_ns)


def _portfolio_rows() -> tuple[dict, dict[str, dict]]:
    dashboard = _dashboard_payload()
    return dashboard, {row["cik"]: row for row in dashboard.get("rows", [])}


def _portfolio_response(conn, selected: dict) -> dict:
    _, rows = _portfolio_rows()
    trades = store.portfolio_trades(conn, selected["id"])
    try:
        result = portfolio.build_portfolio(
            selected,
            trades,
            rows,
            _portfolio_assets_with_crypto_quotes(conn, selected),
            store.portfolio_cash(conn, selected["id"]),
        )
        # Portfolio and Research deliberately share this one immutable snapshot.
        # Universe refresh replaces it atomically once all quotes are ready.
        result["quote_refresh"] = None
        return result
    except portfolio.PortfolioError as exc:
        raise HTTPException(409, str(exc))


@app.get("/portfolios")
def portfolio_list():
    conn = store.connect()
    try:
        if not store.portfolios(conn):
            store.ensure_portfolio(conn)
        return {"portfolios": store.portfolios(conn)}
    finally:
        conn.close()


@app.post("/portfolios")
def portfolio_create(req: PortfolioRequest):
    name = req.name.strip()
    currency = req.base_currency.strip().upper()
    if not name:
        raise HTTPException(422, "portfolio name is required")
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(422, "base currency must be a three-letter code")
    conn = store.connect()
    try:
        try:
            return store.create_portfolio(conn, name, currency)
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"portfolio {name!r} already exists")
    finally:
        conn.close()


@app.get("/portfolio")
def portfolio_default():
    conn = store.connect()
    try:
        selected = store.ensure_portfolio(conn)
        return _portfolio_response(conn, selected)
    finally:
        conn.close()


@app.get("/portfolio/{portfolio_id}")
def portfolio_get(portfolio_id: int):
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        return _portfolio_response(conn, selected)
    finally:
        conn.close()


@app.post("/portfolio/{portfolio_id}/trades")
def portfolio_trade_add(portfolio_id: int, req: PortfolioTradeRequest):
    if req.executed_at.tzinfo is None or req.executed_at.utcoffset() is None:
        raise HTTPException(422, "execution time must include a timezone")
    try:
        quantity = portfolio.decimal_value(req.quantity, "quantity", positive=True)
        price = portfolio.decimal_value(req.price, "price", positive=True)
        fees = portfolio.decimal_value(req.fees, "fees", nonnegative=True)
    except portfolio.PortfolioError as exc:
        raise HTTPException(422, str(exc))

    currency = req.currency.strip().upper()
    dashboard, rows = _portfolio_rows()
    row = rows.get(req.cik)
    if row is None:
        raise HTTPException(404, f"CIK {req.cik} is not in the current dashboard")
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        if currency != selected["base_currency"]:
            raise HTTPException(
                422,
                f"{selected['name']} is a {selected['base_currency']} portfolio; "
                "FX conversion is not implemented, so another currency cannot be totalled safely",
            )
        snapshot = portfolio.decision_snapshot(dashboard, row, price)
        candidate = {
            "id": 0,
            "portfolio_id": portfolio_id,
            "cik": req.cik,
            "ticker": row["ticker"],
            "side": req.side,
            "quantity": portfolio.canonical_decimal(quantity),
            "price": portfolio.canonical_decimal(price),
            "fees": portfolio.canonical_decimal(fees),
            "currency": currency,
            "executed_at": req.executed_at.isoformat(),
            "broker": req.broker,
            "account_label": req.account_label,
            "external_id": req.external_id,
            "note": req.note,
            "decision_snapshot": snapshot,
            "created_at": datetime.now(req.executed_at.tzinfo).isoformat(),
        }
        if req.side == "SELL":
            hypothetical = store.portfolio_trades(conn, portfolio_id) + [candidate]
            hypothetical.sort(key=lambda trade: (trade["executed_at"], trade["id"]))
            try:
                portfolio.build_portfolio(selected, hypothetical, rows)
            except portfolio.PortfolioError as exc:
                raise HTTPException(409, str(exc))
        try:
            trade = store.add_portfolio_trade(
                conn,
                portfolio_id=portfolio_id,
                cik=req.cik,
                ticker=row["ticker"],
                side=req.side,
                quantity=portfolio.canonical_decimal(quantity),
                price=portfolio.canonical_decimal(price),
                fees=portfolio.canonical_decimal(fees),
                currency=currency,
                executed_at=req.executed_at.isoformat(),
                broker=req.broker,
                account_label=req.account_label,
                external_id=req.external_id,
                note=req.note,
                decision_snapshot=snapshot,
            )
        except sqlite3.IntegrityError as exc:
            if req.external_id:
                raise HTTPException(409, f"execution {req.external_id!r} was already imported")
            raise HTTPException(409, f"trade could not be saved: {exc}")
        return {"trade": trade, "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


@app.delete("/portfolio/{portfolio_id}/trades/{trade_id}")
def portfolio_trade_remove(portfolio_id: int, trade_id: int):
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        trades = store.portfolio_trades(conn, portfolio_id)
        if not any(trade["id"] == trade_id for trade in trades):
            raise HTTPException(404, f"trade {trade_id} not found")
        _, rows = _portfolio_rows()
        remaining = [trade for trade in trades if trade["id"] != trade_id]
        try:
            portfolio.build_portfolio(selected, remaining, rows)
        except portfolio.PortfolioError as exc:
            raise HTTPException(409, f"cannot remove this trade: {exc}")
        store.delete_portfolio_trade(conn, portfolio_id, trade_id)
        return {"deleted": True, "trade_id": trade_id,
                "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


def _crypto_products(currency: str) -> list[dict]:
    products = _crypto.products(currency)
    if products is None:
        raise HTTPException(502, "Coinbase crypto ticker catalogue is temporarily unavailable")
    return products


def _crypto_product(product_id: str, currency: str) -> dict | None:
    requested = product_id.strip().upper()
    if "-" not in requested:
        requested = f"{requested}-{currency}"
    return next((product for product in _crypto_products(currency)
                 if product["id"] == requested), None)


def _crypto_quote_payload(product: dict) -> dict:
    quote = _crypto.quote(product["id"])
    if quote is None:
        raise HTTPException(
            502, f"live Coinbase quote unavailable for {product['id']}")
    return {
        "product_id": quote.product_id,
        "symbol": product["symbol"],
        "name": product["name"],
        "price": float(quote.price),
        "currency": product["quote_currency"],
        "asof": quote.asof.isoformat(),
        "source": quote.source,
    }


@app.get("/crypto/products")
def crypto_products(currency: str = "USD"):
    currency = currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(422, "currency must be a three-letter code")
    return {"currency": currency, "products": _crypto_products(currency)}


@app.get("/crypto/quote/{product_id}")
def crypto_quote(product_id: str, currency: str = "USD"):
    currency = currency.strip().upper()
    product = _crypto_product(product_id, currency)
    if product is None:
        raise HTTPException(404, f"active Coinbase market {product_id!r} not found")
    return _crypto_quote_payload(product)


def _portfolio_assets_with_crypto_quotes(conn, selected: dict) -> list[dict]:
    assets = store.portfolio_assets(conn, selected["id"])
    for asset in assets:
        if asset["asset_type"] != "CRYPTO":
            asset.update({
                "price_live": False,
                "price_source": "manual",
                "price_asof": asset["updated_at"],
            })
            continue
        product_id = (asset.get("symbol") or "").strip().upper()
        if "-" not in product_id and product_id:
            product_id = f"{product_id}-{selected['base_currency']}"
        quote = _crypto.quote(product_id) if product_id else None
        live = quote is not None
        quote = quote or (_crypto.cached_quote(product_id) if product_id else None)
        if quote is not None:
            asset["current_price"] = portfolio.canonical_decimal(quote.price)
            asset.update({
                "symbol": quote.product_id,
                "price_live": live,
                "price_source": quote.source,
                "price_asof": quote.asof.isoformat(),
            })
        else:
            asset.update({
                "price_live": False,
                "price_source": "saved",
                "price_asof": asset["updated_at"],
            })
        if not live:
            asset["quote_refresh_warning"] = {
                "kind": "CRYPTO_QUOTE_REFRESH_FAILED",
                "note": "Coinbase quote unavailable; the last saved or cached price remains in use",
            }
    return assets


def _portfolio_asset_fields(req: PortfolioAssetRequest, selected: dict) -> dict:
    name = req.name.strip()
    symbol = req.symbol.strip().upper() if req.symbol and req.symbol.strip() else None
    note = req.note.strip() if req.note and req.note.strip() else None
    currency = req.currency.strip().upper()
    if not name:
        raise HTTPException(422, "asset name is required")
    if len(name) > 160:
        raise HTTPException(422, "asset name must be 160 characters or fewer")
    if symbol and len(symbol) > 32:
        raise HTTPException(422, "asset symbol or identifier must be 32 characters or fewer")
    if currency != selected["base_currency"]:
        raise HTTPException(
            422,
            f"{selected['name']} is a {selected['base_currency']} portfolio; "
            "holdings must be entered in the portfolio currency",
        )
    try:
        quantity = portfolio.decimal_value(req.quantity, "quantity", positive=True)
    except portfolio.PortfolioError as exc:
        raise HTTPException(422, str(exc))
    if req.asset_type == "CRYPTO":
        if symbol is None:
            raise HTTPException(422, "crypto ticker is required")
        product = _crypto_product(symbol, currency)
        if product is None:
            raise HTTPException(422, f"{symbol!r} is not an active Coinbase {currency} market")
        quote = _crypto.quote(product["id"])
        if quote is None:
            raise HTTPException(502, f"live Coinbase quote unavailable for {product['id']}")
        symbol = product["id"]
        current_price = portfolio.decimal_value(
            quote.price, "current price", positive=True)
    else:
        try:
            current_price = portfolio.decimal_value(
                req.current_price, "current price", nonnegative=True)
        except portfolio.PortfolioError as exc:
            raise HTTPException(422, str(exc))
    return {
        "asset_type": req.asset_type,
        "symbol": symbol,
        "name": name,
        "quantity": portfolio.canonical_decimal(quantity),
        "current_price": portfolio.canonical_decimal(current_price),
        "currency": currency,
        "note": note,
    }


@app.post("/portfolio/{portfolio_id}/assets")
def portfolio_asset_add(portfolio_id: int, req: PortfolioAssetRequest):
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        asset = store.add_portfolio_asset(
            conn, portfolio_id=portfolio_id, **_portfolio_asset_fields(req, selected))
        return {"asset": asset, "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


@app.put("/portfolio/{portfolio_id}/assets/{asset_id}")
def portfolio_asset_update(portfolio_id: int, asset_id: int,
                           req: PortfolioAssetRequest):
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        asset = store.update_portfolio_asset(
            conn, portfolio_id=portfolio_id, asset_id=asset_id,
            **_portfolio_asset_fields(req, selected))
        if asset is None:
            raise HTTPException(404, f"portfolio asset {asset_id} not found")
        return {"asset": asset, "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


@app.delete("/portfolio/{portfolio_id}/assets/{asset_id}")
def portfolio_asset_remove(portfolio_id: int, asset_id: int):
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        if not store.delete_portfolio_asset(conn, portfolio_id, asset_id):
            raise HTTPException(404, f"portfolio asset {asset_id} not found")
        return {"deleted": True, "asset_id": asset_id,
                "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


@app.put("/portfolio/{portfolio_id}/cash")
def portfolio_cash_set(portfolio_id: int, req: PortfolioCashRequest):
    try:
        amount = portfolio.decimal_value(req.amount, "liquid cash", nonnegative=True)
    except portfolio.PortfolioError as exc:
        raise HTTPException(422, str(exc))
    conn = store.connect()
    try:
        selected = store.portfolio_by_id(conn, portfolio_id)
        if selected is None:
            raise HTTPException(404, f"portfolio {portfolio_id} not found")
        cash = store.set_portfolio_cash(
            conn, portfolio_id, portfolio.canonical_decimal(amount))
        return {"cash": cash, "portfolio": _portfolio_response(conn, selected)}
    finally:
        conn.close()


@app.get("/dashboard.json")
def dashboard():
    """The whole universe in one payload — the UI fetches it once and filters locally."""
    path = STATIC / "dashboard.json"
    if not path.exists():
        raise HTTPException(404, "dashboard.json not built — run: python -m screener.sync export")
    return FileResponse(path, media_type="application/json")


@app.get("/config")
def config():
    """Lets the UI know whether it must ask for a token before offering write actions."""
    return {"write_protected": auth.token() is not None}


@app.get("/health")
def health():
    try:
        resp = httpx.head(
            "https://data.sec.gov/", timeout=5.0, headers={"User-Agent": _edgar.user_agent}
        )
        edgar_ok = resp.status_code < 500
    except httpx.HTTPError:
        edgar_ok = False
    return {"status": "ok" if edgar_ok else "degraded", "edgar_reachable": edgar_ok}


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _fact_dict(f: Fact) -> dict:
    p = f.provenance
    return {
        "concept": p.concept,
        "value": _num(f.value),
        "tag": p.tag,
        "fiscal_year": p.fiscal_year,
        "form": p.form,
        "accession": p.accession,
        "filed": p.filed.isoformat(),
        "period_end": p.period_end.isoformat() if p.period_end else None,
        "period_start": p.period_start.isoformat() if p.period_start else None,
    }


def _criterion_dict(c: CriterionResult) -> dict:
    return {
        "criterion": c.criterion,
        "name": c.name,
        "status": c.status.value,
        "value": _num(c.value),
        "threshold": c.threshold,
        "note": c.note,
        "inputs": [_fact_dict(f) for f in c.inputs],
    }


def _screen_dict(r: ScreenResult) -> dict:
    return {
        "ticker": r.ticker,
        "cik": r.cik,
        "verdict": r.verdict.value,
        "quote": {
            "price": _num(r.quote.price),
            "asof": r.quote.asof.isoformat(),
            "source": r.quote.source,
            "session": r.quote.session,
            "market_state": r.quote.market_state,
            "market_timezone": r.quote.market_timezone,
            "market_state_asof": (r.quote.market_state_asof.isoformat()
                                    if r.quote.market_state_asof else None),
        }
        if r.quote
        else None,
        "balance_sheet_date": r.balance_sheet_date.isoformat() if r.balance_sheet_date else None,
        "annual_eps": {str(y): _num(v) for y, v in r.annual_eps_series.items()},
        "assumptions": list(r.assumptions),
        "criteria": [_criterion_dict(c) for c in r.criteria],
        "eps_growth": _eps_growth_dict(r.eps_growth),
    }


def _eps_growth_dict(g) -> dict | None:
    """Disclosure alongside the verdict — Graham's fixed 1966 base has no modern heir."""
    if g is None:
        return None
    return {
        "base_fiscal_year": g.base_fiscal_year,
        "base_eps": _num(g.base_eps),
        "latest_fiscal_year": g.latest_fiscal_year,
        "latest_eps": _num(g.latest_eps),
    }


def _snapshot_dict(s: FinancialSnapshot) -> dict:
    opt = lambda f: _fact_dict(f) if f else None  # noqa: E731
    return {
        "ticker": s.ticker,
        "cik": s.cik,
        "balance_sheet_date": s.balance_sheet_date.isoformat() if s.balance_sheet_date else None,
        "ttm_eps": _num(s.ttm_eps),
        "ttm_eps_inputs": [_fact_dict(f) for f in s.ttm_eps_inputs],
        "annual_eps": {str(y): _fact_dict(f) for y, f in sorted(s.annual_eps.items())},
        "ttm_net_income": _num(s.ttm_net_income),
        "annual_net_income": {str(y): _fact_dict(f)
                              for y, f in sorted(s.annual_net_income.items())},
        "current_assets": opt(s.current_assets),
        "current_liabilities": opt(s.current_liabilities),
        "long_term_debt": opt(s.long_term_debt),
        "short_term_debt": opt(s.short_term_debt),
        "total_debt": opt(s.total_debt),
        "total_assets": opt(s.total_assets),
        "total_liabilities": opt(s.total_liabilities),
        "goodwill": opt(s.goodwill),
        "intangibles": opt(s.intangibles),
        "preferred_stock": opt(s.preferred_stock),
        "noncontrolling_interest": opt(s.noncontrolling_interest),
        "shares_outstanding": opt(s.shares_outstanding),
        "dividend": opt(s.dividend),
        "pays_dividend": s.pays_dividend,
        "dividend_per_share": _num(s.dividend_per_share),
        "recurring_dividend_per_share": opt(s.recurring_dividend_per_share),
        "assumed_zero": sorted(s.assumed_zero),
        "earnings_quality": list(s.earnings_quality),
    }


# Mounted last so it never shadows the API routes above.
if (STATIC / "ui").exists():
    app.mount("/", StaticFiles(directory=STATIC / "ui", html=True), name="ui")
