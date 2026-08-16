"""Layer 4: FastAPI wiring. Serialisation only; no business logic."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, jobs, pricestats, store
from .models import CriterionResult, Fact, FinancialSnapshot, ScreenResult
from .normalize import UnsupportedFilerError, build_snapshot
from .screens.enterprising import evaluate
from .sources.edgar import EdgarClient, EdgarError, NoXbrlDataError, UnknownTickerError
from .sources.prices import YahooPriceProvider

app = FastAPI(title="Graham Enterprising Screener", version="1.0")
# no-op unless SCREENER_TOKEN is set, which is how a tunnelled instance is run
app.middleware("http")(auth.require_token)
_edgar = EdgarClient()
_prices = YahooPriceProvider()


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
        return build_snapshot(ticker.upper(), cik, facts, assume_absent_zero=assume_absent_zero)
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
    command: str  # bootstrap | bulk | daily | derive | export
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
        "assumed_zero": sorted(s.assumed_zero),
        "earnings_quality": list(s.earnings_quality),
    }


# Mounted last so it never shadows the API routes above.
if (STATIC / "ui").exists():
    app.mount("/", StaticFiles(directory=STATIC / "ui", html=True), name="ui")
