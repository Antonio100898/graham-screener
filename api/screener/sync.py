"""Populate and refresh the local store.

    python -m screener.sync bootstrap [--limit N]   from the cache already on disk
    python -m screener.sync bulk                    download SEC's 1.4GB companyfacts.zip
    python -m screener.sync daily                   catch up via the daily index
    python -m screener.sync derive                  recompute snapshots after a code change
    python -m screener.sync export                  write dashboard.json
    python -m screener.sync status

Raw facts are never re-derived from the network when the engine changes — only
when the company actually files something new. A new filing can restate years we
already hold, so the trigger is "has it filed since we fetched", never "do we
have the latest period".
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from . import ch13, pricestats, profiles, store
from .normalize import UnsupportedFilerError, build_snapshot
from .screens.enterprising import (PE_MAX, PRICE_TO_TBV_MAX, STALE_FOR_PRICING_DAYS,
                                   evaluate)
from .sources import indexes
from .sources.edgar import EdgarClient, EdgarError, NoXbrlDataError
from .sources.prices import YahooPriceProvider

BULK_FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
BULK_SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
DAILY_INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{qtr}/form.{ymd}.idx"
DASHBOARD_JSON = Path(__file__).parent / "static" / "dashboard.json"


def _print_progress(message: str, done: int = 0, total: int = 0) -> None:
    print(f"  {message}" if not total else f"  {message} ({done}/{total})", flush=True)


def _facts_path(edgar: EdgarClient, cik: str) -> Path:
    return edgar.cache_dir / f"companyfacts_{cik}.json"


def _source(fact) -> dict | None:
    """Compact provenance for the payload: enough to open the exact filing."""
    if fact is None:
        return None
    p = fact.provenance
    return {"tag": p.tag, "form": p.form, "accn": p.accession,
            "end": p.period_end.isoformat() if p.period_end else None,
            "filed": p.filed.isoformat() if p.filed else None}


def _series_mix(series: dict) -> dict | None:
    """Which tag served which years — only when the series switched tags, so the
    reader sees a scope change (ProfitLoss beside NetIncomeLoss) instead of a
    silently uniform-looking history."""
    tags: dict[str, list[int]] = {}
    for year, fact in series.items():
        tags.setdefault(fact.provenance.tag, []).append(year)
    if len(tags) <= 1:
        return None
    return {tag: sorted(years) for tag, years in tags.items()}


def _derive(cik: str, ticker: str, facts: dict, quote=None) -> tuple[str, dict | None]:
    """Snapshot + screen result, flattened for the dashboard."""
    try:
        snap = build_snapshot(ticker, cik, facts, assume_absent_zero=False)
    except UnsupportedFilerError:
        return "foreign", None
    except Exception as exc:  # a malformed filing must not stop a 4,000-company run
        return "error", {"error": repr(exc)[:200]}
    r = evaluate(snap, quote)
    return "ok", {
        "cik": cik,
        "ticker": ticker,
        "verdict": r.verdict.value,
        "n_pass": sum(1 for c in r.criteria if c.status.value == "PASS"),
        "ttm_eps": float(snap.ttm_eps) if snap.ttm_eps is not None else None,
        "ttm_eps_vintage": {d: float(v) for d, v in snap.ttm_eps_vintage.items()},
        "balance_sheet_date": snap.balance_sheet_date.isoformat() if snap.balance_sheet_date else None,
        "annual_eps": {str(y): float(v) for y, v in r.annual_eps_series.items()},
        "annual_net_income": {str(y): float(f.value)
                              for y, f in sorted(snap.annual_net_income.items())},
        "ttm_net_income": float(snap.ttm_net_income) if snap.ttm_net_income is not None else None,
        "assumptions": list(r.assumptions),
        "earnings_quality": list(snap.earnings_quality),
        # reported beside the verdict, never inside it — see models.EpsGrowth
        "eps_growth": {
            "base_fiscal_year": r.eps_growth.base_fiscal_year,
            "base_eps": float(r.eps_growth.base_eps),
            "latest_fiscal_year": r.eps_growth.latest_fiscal_year,
            "latest_eps": float(r.eps_growth.latest_eps),
        } if r.eps_growth else None,
        "criteria": [
            {"n": c.criterion, "status": c.status.value,
             "value": float(c.value) if c.value is not None else None,
             "note": c.note}
            for c in r.criteria
        ],
        # kept so criteria 1 and 7 (and market cap) can be recomputed against a live
        # price without refetching anything
        "tbvps": _tbvps(snap),
        "bvps": _bvps(snap),
        "ncavps": _ncavps(snap),
        # chapter-13 comparison material; dollar figures repeated here so the UI
        # can show working capital and capitalization without a second request
        "annual_revenue": {str(y): float(f.value)
                           for y, f in sorted(snap.annual_revenue.items())},
        "ttm_revenue": float(snap.ttm_revenue) if snap.ttm_revenue is not None else None,
        "annual_operating_income": {str(y): float(f.value)
                                    for y, f in sorted(snap.annual_operating_income.items())},
        "dividend_record": snap.dividend_record,
        "ch13": ch13.eps_stats({y: f.value for y, f in snap.annual_eps.items()}),
        "current_assets": float(snap.current_assets.value) if snap.current_assets else None,
        "current_liabilities": (float(snap.current_liabilities.value)
                                if snap.current_liabilities else None),
        "long_term_debt": float(snap.long_term_debt.value) if snap.long_term_debt else None,
        "total_debt": float(snap.total_debt.value) if snap.total_debt else None,
        "total_assets": float(snap.total_assets.value) if snap.total_assets else None,
        "total_liabilities": (float(snap.total_liabilities.value)
                              if snap.total_liabilities else None),
        "preferred_stock": float(snap.preferred_stock.value) if snap.preferred_stock else None,
        "earnings_asof": max((f.provenance.period_end for f in snap.ttm_eps_inputs
                              if f.provenance.period_end), default=None) and
                         max(f.provenance.period_end for f in snap.ttm_eps_inputs
                             if f.provenance.period_end).isoformat(),
        "shares": float(snap.shares_outstanding.value) if snap.shares_outstanding else None,
        "dividend_per_share": float(snap.dividend_per_share)
                              if snap.dividend_per_share is not None else None,
        "owner_earnings": _owner_earnings_row(snap),
        "short_term_debt": float(snap.short_term_debt.value) if snap.short_term_debt else None,
        "goodwill": float(snap.goodwill.value) if snap.goodwill else None,
        "intangibles": float(snap.intangibles.value) if snap.intangibles else None,
        "noncontrolling_interest": (float(snap.noncontrolling_interest.value)
                                    if snap.noncontrolling_interest else None),
        "temporary_equity": (float(snap.temporary_equity.value)
                             if snap.temporary_equity else None),
        # the payment fact behind criterion 5 — covers whatever span the filer
        # tagged (its period end sits in sources.dividend)
        "dividend": float(snap.dividend.value) if snap.dividend else None,
        # per-figure provenance: which tag, in which filing, dated when — the
        # reader can open the exact document behind every number
        "sources": {name: src for name, src in (
            ("total_assets", _source(snap.total_assets)),
            ("total_liabilities", _source(snap.total_liabilities)),
            ("current_assets", _source(snap.current_assets)),
            ("current_liabilities", _source(snap.current_liabilities)),
            ("long_term_debt", _source(snap.long_term_debt)),
            ("short_term_debt", _source(snap.short_term_debt)),
            ("total_debt", _source(snap.total_debt)),
            ("goodwill", _source(snap.goodwill)),
            ("intangibles", _source(snap.intangibles)),
            ("preferred_stock", _source(snap.preferred_stock)),
            ("temporary_equity", _source(snap.temporary_equity)),
            ("noncontrolling_interest", _source(snap.noncontrolling_interest)),
            ("shares", _source(snap.shares_outstanding)),
            ("dividend", _source(snap.dividend)),
        ) if src is not None},
        # scope-switch disclosure: annual series stitched from more than one tag
        "series_mix": {name: mix for name, mix in (
            ("eps", _series_mix(snap.annual_eps)),
            ("net_income", _series_mix(snap.annual_net_income)),
            ("revenue", _series_mix(snap.annual_revenue)),
        ) if mix is not None} or None,
    }


def _owner_earnings_row(snap) -> dict | None:
    """Return on capital is not one of Graham's requirements, so it rides alongside
    the verdict rather than inside it — a way to rank companies that already passed."""
    oe = snap.owner_earnings
    if oe is None:
        return None
    return {
        "fiscal_year": oe.fiscal_year,
        "owner_earnings": float(oe.owner_earnings),
        "invested_capital": float(oe.invested_capital) if oe.invested_capital is not None else None,
        "roic": float(oe.roic) if oe.roic is not None else None,
        "roic_maintenance": float(oe.roic_maintenance) if oe.roic_maintenance is not None else None,
        "components": [[label, float(v)] for label, v in oe.components],
        "caveats": list(oe.caveats),
    }


def _ncavps(snap) -> float | None:
    """Net current asset value per share — Graham's most conservative yardstick:
    current assets less every liability, ignoring fixed assets entirely, divided by
    shares. Distinct from the net current assets in criterion 3, which subtracts
    only current liabilities."""
    need = (snap.current_assets, snap.total_liabilities, snap.shares_outstanding)
    if any(f is None for f in need) or snap.shares_outstanding.value <= 0:
        return None
    optional = sum(f.value for f in (snap.preferred_stock, snap.noncontrolling_interest) if f)
    return float((snap.current_assets.value - snap.total_liabilities.value - optional)
                 / snap.shares_outstanding.value)


def _bvps(snap) -> float | None:
    """Plain book value per share — intangibles included, unlike criterion 7's
    tangible variant, because chapter 13's P/B and earnings-on-book use the full
    equity. Preferred and minority interest are deducted the same way _tbvps does."""
    need = (snap.total_assets, snap.total_liabilities, snap.shares_outstanding)
    if any(f is None for f in need) or snap.shares_outstanding.value <= 0:
        return None
    optional = sum(f.value for f in (snap.preferred_stock, snap.noncontrolling_interest,
                                     snap.temporary_equity) if f)
    book = snap.total_assets.value - snap.total_liabilities.value - optional
    return float(book / snap.shares_outstanding.value)


def _tbvps(snap) -> float | None:
    need = (snap.total_assets, snap.total_liabilities, snap.goodwill,
            snap.intangibles, snap.shares_outstanding)
    if any(f is None for f in need) or snap.shares_outstanding.value <= 0:
        return None
    optional = sum(f.value for f in (snap.preferred_stock, snap.noncontrolling_interest,
                                     snap.temporary_equity) if f)
    tangible = (snap.total_assets.value - snap.total_liabilities.value
                - snap.goodwill.value - snap.intangibles.value - optional)
    return float(tangible / snap.shares_outstanding.value)


def _index_tickers(conn, edgar: EdgarClient) -> dict[str, tuple[str, str]]:
    """CIK -> (ticker, name) from SEC's mapping; refreshed with the ticker file."""
    store.migrate(conn)
    mapping = edgar._cached("company_tickers", "https://www.sec.gov/files/company_tickers.json")
    out = {}
    for row in mapping.values():
        cik = f"{int(row['cik_str']):010d}"
        out.setdefault(cik, (row["ticker"], row["title"]))
    for cik, (ticker, name) in out.items():
        store.upsert_company(conn, cik, ticker, name)
    conn.commit()
    return out


def bootstrap(conn, limit: int | None = None, progress=_print_progress) -> None:
    """Derive from whatever raw facts are already cached locally — no network."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    cached = sorted(edgar.cache_dir.glob("companyfacts_*.json"))
    if limit:
        cached = cached[:limit]
    progress(f"deriving from {len(cached)} cached companies", 0, len(cached))
    for i, fp in enumerate(cached, 1):
        cik = fp.stem.replace("companyfacts_", "")
        ticker, name = tickers.get(cik, (None, None))
        try:
            facts = json.loads(fp.read_text())
        except ValueError:
            continue
        status, data = _derive(cik, ticker or cik, facts)
        store.upsert_company(conn, cik, ticker, name, facts_synced=True)
        store.put_snapshot(conn, cik, status, data)
        if i % 100 == 0:
            conn.commit()
            progress("deriving cached companies", i, len(cached))
    conn.commit()
    progress("done")


def bulk(conn, limit: int | None = None, progress=_print_progress) -> None:
    """One 1.4GB download instead of thousands of rate-limited requests."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    progress("downloading companyfacts.zip from SEC (1.4 GB)")
    with httpx.stream("GET", BULK_FACTS_URL, headers={"User-Agent": edgar.user_agent},
                      timeout=None, follow_redirects=True) as resp:
        resp.raise_for_status()
        buf = io.BytesIO()
        for chunk in resp.iter_bytes(1 << 20):
            buf.write(chunk)
            if buf.tell() % (100 << 20) < (1 << 20):
                progress(f"downloading — {buf.tell() / 1e9:.2f} GB of ~1.4 GB")
    progress("extracting archive")
    with zipfile.ZipFile(buf) as z:
        names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
        if limit:
            names = names[:limit]
        for i, n in enumerate(names, 1):
            cik = n[3:-5]
            ticker, name = tickers.get(cik, (None, None))
            try:
                facts = json.loads(z.read(n))
            except ValueError:
                continue
            (edgar.cache_dir / f"companyfacts_{cik}.json").write_bytes(z.read(n))
            status, data = _derive(cik, ticker or cik, facts)
            store.upsert_company(conn, cik, ticker, name, facts_synced=True)
            store.put_snapshot(conn, cik, status, data)
            if i % 500 == 0:
                conn.commit()
                progress("deriving companies", i, len(names))
    conn.commit()
    progress("done")


def metadata(conn, progress=_print_progress) -> None:
    """Sector, exchange and filer size from SEC's submissions archive.

    Yahoo has this too, but rate-limits after roughly one lookup; SEC serves the
    whole market in a single archive and it is the authoritative record anyway.
    """
    edgar = EdgarClient()
    store.migrate(conn)
    progress("downloading submissions.zip from SEC (1.6 GB)")
    with httpx.stream("GET", BULK_SUBMISSIONS_URL, headers={"User-Agent": edgar.user_agent},
                      timeout=None, follow_redirects=True) as resp:
        resp.raise_for_status()
        buf = io.BytesIO()
        for chunk in resp.iter_bytes(1 << 20):
            buf.write(chunk)
            if buf.tell() % (100 << 20) < (1 << 20):
                progress(f"downloading — {buf.tell() / 1e9:.2f} GB of ~1.6 GB")
    progress("reading company metadata")
    with zipfile.ZipFile(buf) as z:
        # skip the -submissions-001 shards: the base file carries the header fields
        names = [n for n in z.namelist()
                 if n.startswith("CIK") and n.endswith(".json") and "submissions" not in n]
        for i, n in enumerate(names, 1):
            try:
                d = json.loads(z.read(n))
            except ValueError:
                continue
            cik = n[3:-5]
            tickers, exchanges = d.get("tickers") or [], d.get("exchanges") or []
            store.set_metadata(
                conn, cik,
                sic=d.get("sic") or None,
                industry=d.get("sicDescription") or None,
                exchange=exchanges[0] if exchanges else None,
                filer_size=d.get("category") or None,
                ticker=tickers[0] if tickers else None,
                name=d.get("name") or None,
            )
            filings = d.get("filings") or {}
            first = [f["filingFrom"] for f in (filings.get("files") or []) if f.get("filingFrom")]
            recent_dates = (filings.get("recent") or {}).get("filingDate") or []
            if recent_dates:
                first.append(min(recent_dates))
            if first:
                store.set_first_filed(conn, cik, min(first))
            if i % 2000 == 0:
                conn.commit()
                progress("reading company metadata", i, len(names))
    conn.commit()
    progress("done", len(names), len(names))


def listing_age(conn, progress=_print_progress) -> None:
    """First-ever SEC filing date, for companies whose EPS record starts after
    2011. The windowed defensive tests need this corroboration: a record that
    begins late can mean a young company (LEVI, 2019) or an old company whose
    tag is young (ARCC's BDC per-share element starts 2020, the company 2004) —
    XBRL alone cannot tell the two apart."""
    edgar = EdgarClient()
    store.migrate(conn)
    todo = []
    for row in store.dashboard_rows(conn):
        if row.get("first_filed"):
            continue
        years = [int(y) for y in (row.get("annual_eps") or {})]
        if years and min(years) > 2011:
            todo.append(row["cik"])
    progress(f"{len(todo)} companies need a listing age")
    for i, cik in enumerate(todo, 1):
        try:
            d = edgar.submissions(cik)
        except (EdgarError, NoXbrlDataError):
            continue
        filings = d.get("filings") or {}
        dates = [f["filingFrom"] for f in (filings.get("files") or []) if f.get("filingFrom")]
        recent = (filings.get("recent") or {}).get("filingDate") or []
        if recent:
            dates.append(min(recent))
        if dates:
            store.set_first_filed(conn, cik, min(dates))
        if i % 100 == 0:
            conn.commit()
            progress("listing ages", i, len(todo))
    conn.commit()
    progress("done", len(todo), len(todo))


def daily(conn, days: int = 7, progress=_print_progress) -> None:
    """One ~1MB file per day names every company that filed. Refetch only those."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    end = store.today()
    last = store.get_state(conn, "last_daily_index")
    start = max(end - timedelta(days=days),
                (store.today() - timedelta(days=days)) if not last else
                __import__("datetime").date.fromisoformat(last) + timedelta(days=1))
    filed: dict[str, str] = {}
    day = start
    while day <= end:
        url = DAILY_INDEX_URL.format(year=day.year, qtr=(day.month - 1) // 3 + 1,
                                     ymd=day.strftime("%Y%m%d"))
        try:
            text = edgar._get_text(url)
        except EdgarError:
            day += timedelta(days=1)
            continue  # weekends and holidays have no index
        for line in text.splitlines():
            if not line.startswith(("10-K", "10-Q")):
                continue
            parts = [p for p in line.split("  ") if p.strip()]
            if len(parts) < 3:
                continue
            cik_field = next((p.strip() for p in parts if p.strip().isdigit()), None)
            if cik_field:
                filed[f"{int(cik_field):010d}"] = day.isoformat()
        progress(f"scanning {day} — {len(filed)} filers found")
        store.set_state(conn, "last_daily_index", day.isoformat())
        day += timedelta(days=1)
    for cik, when in filed.items():
        store.upsert_company(conn, cik, *tickers.get(cik, (None, None)), last_filing=when)
    conn.commit()

    pending = store.needs_refetch(conn)
    progress(f"{len(pending)} companies filed since last sync", 0, len(pending))
    for i, cik in enumerate(pending, 1):
        ticker, name = tickers.get(cik, (None, None))
        try:
            facts = edgar.company_facts(cik)
        except NoXbrlDataError:
            store.put_snapshot(conn, cik, "no_xbrl", None)
            store.upsert_company(conn, cik, ticker, name, facts_synced=True)
            continue
        except EdgarError as exc:
            print(f"  {ticker}: {exc}")
            continue
        status, data = _derive(cik, ticker or cik, facts)
        store.upsert_company(conn, cik, ticker, name, facts_synced=True)
        store.put_snapshot(conn, cik, status, data)
        progress("refetching filers", i, len(pending))
        if i % 50 == 0:
            conn.commit()
    conn.commit()
    progress("done")


def derive(conn, progress=_print_progress) -> None:
    """Recompute snapshots after an engine change, from raw facts already on disk."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    stale = store.needs_recompute(conn)
    progress(f"{len(stale)} snapshots predate engine v{store.ENGINE_VERSION}", 0, len(stale))
    for i, cik in enumerate(stale, 1):
        fp = _facts_path(edgar, cik)
        if not fp.exists():
            continue
        ticker, name = tickers.get(cik, (None, None))
        status, data = _derive(cik, ticker or cik, json.loads(fp.read_text()))
        store.put_snapshot(conn, cik, status, data)
        if i % 200 == 0:
            conn.commit()
            progress("recomputing snapshots", i, len(stale))
    conn.commit()
    progress("done")


def _too_stale(asof: str | None, price_asof: str | None) -> int | None:
    """Days between the fundamentals and the price, when that gap is too wide to value."""
    if not asof or not price_asof:
        return None
    gap = (date.fromisoformat(price_asof[:10]) - date.fromisoformat(asof)).days
    return gap if gap > STALE_FOR_PRICING_DAYS else None


def apply_price(row: dict, price: float | None) -> dict:
    """Criteria 1 and 7 are the only price-dependent tests. Snapshots are stored
    price-free (they change only when the company files), so the valuation
    criteria are settled here — pure arithmetic over ttm_eps and tbvps, no I/O.
    The same rule runs client-side when the UI refreshes a price."""
    crit = {c["n"]: c for c in row["criteria"]}
    if price is not None and price > 0:
        eps, tbvps = row.get("ttm_eps"), row.get("tbvps")
        # Snapshots are intentionally price-free.  Once export has supplied a
        # live price, do not retain a stale "price quote" token in an otherwise
        # incomplete tangible-book explanation.
        note = crit[7].get("note")
        if isinstance(note, str) and note.startswith("missing: "):
            missing = [item.strip() for item in note.removeprefix("missing: ").split(",")]
            missing = [item for item in missing if item != "price quote"]
            crit[7]["note"] = "missing: " + ", ".join(missing) if missing else None
        pa = row.get("price_asof")
        # a dormant filer keeps its ticker; valuing today's price against its last
        # figures from years ago produces a confident, meaningless number
        stale_eps = _too_stale(row.get("earnings_asof"), pa)
        stale_bs = _too_stale(row.get("balance_sheet_date"), pa)
        if stale_eps:
            crit[1].update(status="INSUFFICIENT_DATA", value=None,
                           note=f"newest earnings are {stale_eps // 365} years older than this "
                                "price; the company appears to have stopped filing")
            eps = None
        if stale_bs:
            crit[7].update(status="INSUFFICIENT_DATA", value=None,
                           note=f"balance sheet is {stale_bs // 365} years older than this price")
            tbvps = None
        if eps is not None:
            if eps <= 0:
                crit[1].update(status="FAIL", value=None,
                               note="TTM EPS non-positive; P/E undefined")
            else:
                price_d, eps_d = Decimal(str(price)), Decimal(str(eps))
                pe = round(price / eps, 2)  # display only
                crit[1].update(status="PASS" if price_d < PE_MAX * eps_d else "FAIL",
                               value=pe, note=None)
        dps = row.get("dividend_per_share")
        if dps is not None and crit[5]["status"] == "PASS":
            crit[5]["value"] = round(dps / price * 100, 2)
            crit[5]["note"] = f"${dps:,.2f} per share over twelve months"
        if tbvps is not None:
            if tbvps <= 0:
                crit[7].update(status="FAIL", value=None, note="non-positive tangible book value")
            else:
                price_d, tbvps_d = Decimal(str(price)), Decimal(str(tbvps))
                ptbv = round(price / tbvps, 2)  # display only
                crit[7].update(status="PASS" if price_d < PRICE_TO_TBV_MAX * tbvps_d else "FAIL",
                               value=ptbv, note=None)
    statuses = {c["status"] for c in row["criteria"]}
    row["n_pass"] = sum(1 for c in row["criteria"] if c["status"] == "PASS")
    # a measured failure outranks an unknown: see _verdict in screens/enterprising
    row["verdict"] = (
        "FAIL" if "FAIL" in statuses
        else "INDETERMINATE" if "INSUFFICIENT_DATA" in statuses
        else "INDETERMINATE" if "NOT_APPLICABLE" in statuses
        else "PASS"
    )
    return row


def _price_stats_row(row: dict, closes) -> dict | None:
    """Where the price sits in its own five-year history. Never a criterion."""
    if not closes or not row.get("price"):
        return None
    series = tuple((d, Decimal(str(c))) for d, c in closes)
    stats = pricestats.compute(series, Decimal(str(row["price"])))
    if stats is None:
        return None
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in stats.items()}


def _mark_memberships(rows: list[dict], progress) -> None:
    """Tag each row with the indexes it currently belongs to. A list that cannot
    be read is skipped WHOLE — a half-parsed index would read as reconstitution —
    and the skip is said out loud rather than silently shipping blanks."""
    sp = indexes.sp500()
    dj = indexes.djia_ciks(sp) if sp else None
    n100 = indexes.nasdaq100()
    if not (sp and dj and n100):
        progress("index lists unavailable: "
                 + ", ".join(n for n, v in (("S&P 500", sp), ("DJIA", dj),
                                            ("Nasdaq 100", n100)) if not v))
    for r in rows:
        m = []
        if dj and r["cik"] in dj:
            m.append("DJIA")
        if sp and r["cik"] in sp:
            m.append("S&P 500")
        if n100 and r.get("ticker") in n100:
            m.append("Nasdaq 100")
        if r.get("exchange") == "Nasdaq":
            m.append("Nasdaq Comp")
        if m:
            r["index_memberships"] = m


def export(conn, with_prices: bool = True, progress=_print_progress) -> None:
    """Write the whole universe as one JSON file — the UI fetches it once.
    Snapshots below the current engine are recomputed first, so a refresh never
    ships stale arithmetic — recomputation is automatic, not a separate button."""
    stale = store.needs_recompute(conn)
    if stale:
        derive(conn, progress=progress)
    rows = store.dashboard_rows(conn)
    if with_prices:
        prices = YahooPriceProvider()
        progress(f"fetching prices for {len(rows)} tickers", 0, len(rows))
        done = 0
        # one request per company returns the quote *and* five years of weekly
        # closes, so the price statistics cost no extra call; each is independent,
        # and a small pool turns an hour of waiting into a few minutes
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(prices.history, r["ticker"]): r for r in rows if r.get("ticker")}
            for fut in as_completed(futures):
                row = futures[fut]
                try:
                    hist = fut.result()
                except Exception:
                    hist = None
                if hist:
                    row["price"] = float(hist.quote.price)
                    row["price_asof"] = hist.quote.asof.isoformat()
                    row["_closes"] = hist.closes
                done += 1
                if done % 25 == 0 or done == len(futures):
                    progress("fetching prices", done, len(futures))
        # the series is written once per company, so a later `derive` can rebuild
        # the statistics without asking the provider for five more years of data
        closes_by_cik = {}
        for row in rows:
            closes = row.pop("_closes", None)
            if closes:
                store.set_price_history(conn, row["cik"], closes)
            apply_price(row, row.get("price"))
            closes_by_cik[row["cik"]] = closes or store.price_history(conn, row["cik"])
            row["price_stats"] = _price_stats_row(row, closes_by_cik[row["cik"]])
        conn.commit()
    else:
        closes_by_cik = {r["cik"]: store.price_history(conn, r["cik"]) for r in rows}
        for row in rows:
            row["price_stats"] = _price_stats_row(row, closes_by_cik[row["cik"]])
    DASHBOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    if with_prices:  # membership needs the network; offline exports keep blanks
        _mark_memberships(rows, progress)
    for row in rows:
        row.update(profiles.enrich(row))
    for row in rows:  # engine-internal series with no reader in the payload
        row.pop("ttm_eps_vintage", None)
    payload = {"generated": store._now(), "engine_version": store.ENGINE_VERSION, "rows": rows}
    DASHBOARD_JSON.write_text(json.dumps(payload, separators=(",", ":")))
    store.set_state(conn, "last_export", store._now())
    conn.commit()
    progress(f"wrote dashboard.json — {DASHBOARD_JSON.stat().st_size / 1e6:.2f} MB, {len(rows)} companies", len(rows), len(rows))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["bootstrap", "bulk", "metadata", "daily",
                                        "derive", "export", "listing-age", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-prices", action="store_true")
    args = ap.parse_args(argv)
    conn = store.connect()
    if args.command == "bootstrap":
        bootstrap(conn, args.limit)
    elif args.command == "bulk":
        bulk(conn, args.limit)
    elif args.command == "metadata":
        metadata(conn)
    elif args.command == "daily":
        daily(conn, args.days)
    elif args.command == "derive":
        derive(conn)
    elif args.command == "listing-age":
        listing_age(conn)
    elif args.command == "export":
        export(conn, not args.no_prices)
    else:
        print(json.dumps(store.stats(conn), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
