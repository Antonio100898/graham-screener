"""Populate and refresh the local store.

    python -m screener.sync bootstrap [--limit N]   from the cache already on disk
    python -m screener.sync bulk                    download SEC's 1.4GB companyfacts.zip
    python -m screener.sync daily                   catch up via the daily index
    python -m screener.sync derive                  recompute dashboard-eligible snapshots
    python -m screener.sync derive --all-snapshots  recompute every cached snapshot
    python -m screener.sync events                  material 8-K items from each filing index
    python -m screener.sync cover                   what each filing's cover says the ticker is
    python -m screener.sync export                  write dashboard.json
    python -m screener.sync quotes                  refresh every dashboard quote
    python -m screener.sync dera --from 2021q1      dimensioned + extension facts
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
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from . import ch13, evidence, pricestats, profiles, store
from . import normalize
from .normalize import PendingFilingFactsError, UnsupportedFilerError, build_snapshot
from .screens.enterprising import (PE_MAX, PRICE_TO_TBV_MAX, STALE_FOR_PRICING_DAYS,
                                   YIELD_IMPLAUSIBLE, evaluate, settled_debt)
from .sources import cover, dera, indexes
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


def _derive_cached_worker(task: tuple[str, str, dict | None, str]):
    """Read and derive one cached filer in a process with no database handle."""
    cik, ticker, receipt, cache_dir = task
    cache = Path(cache_dir)
    fp = cache / f"companyfacts_{cik}.json"
    if not fp.exists():
        return cik, None
    bundle = evidence.EvidenceBundle(
        cik=cik,
        ticker=ticker,
        facts=json.loads(fp.read_text()),
        dimensioned=dera.load_sidecar(cache, cik),
        receipt=receipt,
    )
    return cik, _derive_evidence(bundle)


def _source(fact) -> dict | None:
    """Compact provenance for the payload: enough to open the exact filing.

    A summed or derived figure carries each component, because its own filing
    metadata belongs to whichever component was newest and describes none of the
    others."""
    if fact is None:
        return None

    def one(p) -> dict:
        src = {"tag": p.tag, "form": p.form, "accn": p.accession,
               "end": p.period_end.isoformat() if p.period_end else None,
               "filed": p.filed.isoformat() if p.filed else None}
        # A fact read on a share-class axis is not the one that tag holds without a
        # dimension: BCSS files 1,500,000 weighted shares dimension-free and
        # 10,000,000 for the class its ticker names. Provenance that omits the axis
        # points at a filing where the figure is a different number.
        if p.segments:
            src["segments"] = p.segments
        # The concept carries the caveat the tag cannot: "Dividends (aggregate —
        # may include preferred and noncontrolling)" was built for 203 rows and
        # then dropped here, so none of them ever showed it.
        if "(" in p.concept:
            src["concept"] = p.concept
        return src

    def leaves(p) -> list:
        # a component can itself be a sum; the reader wants the filings, not the
        # intermediate constructions
        if not p.components:
            return []
        out = []
        for child in p.components:
            out.extend(leaves(child) or [child])
        return out

    p = fact.provenance
    src = one(p)
    if (parts := leaves(p)):
        src["components"] = [one(c) for c in parts]
    return src


def _duration_source(fact, unit: str | None = None) -> dict | None:
    """A duration fact whose start is required to identify the exact context."""
    src = _source(fact)
    if src is not None and fact.provenance.period_start is not None:
        src["start"] = fact.provenance.period_start.isoformat()
    if src is not None and unit is not None:
        src["unit"] = unit
    return src


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


def _without_filing(companyfacts: dict, filing: tuple[str, str]) -> dict:
    """A Company Facts view before an incomplete accession appeared.

    SEC normally retains every older fact when a new filing arrives. Removing only
    the pending accession therefore reconstructs the last complete evidence set and
    lets the current engine recompute it, instead of retaining stale arithmetic or
    dropping the company while SEC finishes ingesting the new filing.
    """
    filed, accn = filing
    facts = {}
    for namespace, taxonomy in (companyfacts.get("facts") or {}).items():
        kept_taxonomy = {}
        for tag, tagdata in taxonomy.items():
            units = {}
            for unit, entries in (tagdata.get("units") or {}).items():
                kept = [e for e in entries
                        if (e.get("filed"), e.get("accn", "")) != (filed, accn)]
                if kept:
                    units[unit] = kept
            if units:
                kept_taxonomy[tag] = {**tagdata, "units": units}
        if kept_taxonomy:
            facts[namespace] = kept_taxonomy
    return {**companyfacts, "facts": facts}


def _derive(cik: str, ticker: str, facts: dict, quote=None,
            dimensioned: dict | None = None,
            receipt: dict | None = None) -> tuple[str, dict | None]:
    """Snapshot + screen result, flattened for the dashboard."""
    pending: dict | None = None
    try:
        snap = build_snapshot(ticker, cik, facts, assume_absent_zero=False,
                              dimensioned=dimensioned, receipt=receipt)
    except PendingFilingFactsError as exc:
        filed, accession = exc.filing
        pending = {
            "kind": "SEC_FACTS_PENDING",
            "filed": filed,
            "accession": accession,
            "note": ("A newer annual filing is indexed, but SEC structured statements "
                     "are not complete yet; calculations use the last complete filing."),
        }
        try:
            snap = build_snapshot(
                ticker, cik, _without_filing(facts, exc.filing),
                assume_absent_zero=False, dimensioned=dimensioned, receipt=receipt)
        except UnsupportedFilerError:
            return "pending_facts", {"data_pending": pending}
        except Exception as fallback_exc:
            return "error", {"error": repr(fallback_exc)[:200], "data_pending": pending}
    except UnsupportedFilerError:
        return "foreign", None
    except Exception as exc:  # a malformed filing must not stop a 4,000-company run
        return "error", {"error": repr(exc)[:200]}
    r = evaluate(snap, quote)
    source_namespace = (snap.total_assets.provenance.tag.partition(":")[0]
                        if snap.total_assets is not None else "us-gaap")
    statement_taxonomy = (
        normalize._ifrs_as_us_gaap(facts.get("facts", {}).get("ifrs-full", {}))
        if source_namespace == "ifrs-full"
        else facts.get("facts", {}).get("us-gaap", {})
    )
    historical_ratios = normalize.annual_ratios(
        statement_taxonomy, snap.annual_net_income,
        snap.annual_revenue, snap.annual_operating_income,
        annual_eps=snap.annual_eps)
    if receipt and receipt.get("ratio"):
        _restate_historical_ratios(historical_ratios, Decimal(str(receipt["ratio"])))
    row = {
        "cik": cik,
        "ticker": ticker,
        "verdict": r.verdict.value,
        "n_pass": sum(1 for c in r.criteria if c.status.value == "PASS"),
        "ttm_eps": float(snap.ttm_eps) if snap.ttm_eps is not None else None,
        # What the trailing figure actually is. The composite is FY + YTD - prior
        # YTD, but where a quarter is missing or contradicts, the engine falls back
        # to the audited year and said nothing: the panel labelled a figure eight
        # months old "latest 12 months", and a P/E built on it looked current.
        "ttm_basis": _ttm_basis(snap),
        "ttm_eps_vintage": {d: float(v) for d, v in snap.ttm_eps_vintage.items()},
        "balance_sheet_date": snap.balance_sheet_date.isoformat() if snap.balance_sheet_date else None,
        "annual_eps": {str(y): float(v) for y, v in r.annual_eps_series.items()},
        "annual_net_income": {str(y): float(f.value)
                              for y, f in sorted(snap.annual_net_income.items())},
        # The weighted denominator reported in the filing. The panel formerly
        # inferred this from total net income / EPS, which is not valid when the
        # EPS numerator has a narrower scope (ZWS continuing operations, LP units).
        "annual_weighted_shares": {str(y): float(f.value)
                                   for y, f in sorted(snap.annual_share_counts.items())},
        # Retained as engine evidence: EPS nets preferred dividends while the
        # income tag generally does not.
        "annual_preferred_dividends": {str(y): float(v) for y, v in
                                       sorted(snap.annual_preferred_dividends.items())} or None,
        "ttm_net_income": float(snap.ttm_net_income) if snap.ttm_net_income is not None else None,
        "assumptions": list(r.assumptions),
        "earnings_quality": list(snap.earnings_quality),
        "context_notes": list(snap.context_notes),
        "tax_record": snap.tax_record,
        # why the engine withheld the price criteria, when it did: apply_price must
        # not settle a criterion that was refused for a reason a price cannot fix
        "basis_conflict": snap.basis_conflict,
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
        # profitability: never a criterion, the same way ROIC is not
        "profitability": _profitability(snap),
        # the same ratios at each of the last fiscal year ends, each struck on its
        # own year's report. The price multiples are completed at export, where the
        # price history lives; the vintage EPS series is their denominator.
        "annual_ratios": historical_ratios,
        "current_assets": float(snap.current_assets.value) if snap.current_assets else None,
        "current_liabilities": (float(snap.current_liabilities.value)
                                if snap.current_liabilities else None),
        "long_term_debt": float(snap.long_term_debt.value) if snap.long_term_debt else None,
        "total_debt": float(snap.total_debt.value) if snap.total_debt else None,
        # Employee options as a share of the count they will dilute. Absent for the
        # filers that grant restricted stock instead, and absent is not zero.
        "options": (float(snap.options_outstanding.value)
                    if snap.options_outstanding else None),
        "rsus": float(snap.rsus_outstanding.value) if snap.rsus_outstanding else None,
        **_equity_awards(snap),
        # What criterion 3 actually weighed, rollup and parts already reconciled.
        # The panel adds it to the market value of the common to price the whole
        # enterprise, and None here means unknown rather than debt-free.
        "debt": (lambda d: float(d) if d is not None else None)(settled_debt(snap)[0]),
        "total_assets": float(snap.total_assets.value) if snap.total_assets else None,
        "total_liabilities": (float(snap.total_liabilities.value)
                              if snap.total_liabilities else None),
        "preferred_stock": float(snap.preferred_stock.value) if snap.preferred_stock else None,
        "earnings_asof": max((f.provenance.period_end for f in snap.ttm_eps_inputs
                              if f.provenance.period_end), default=None) and
                         max(f.provenance.period_end for f in snap.ttm_eps_inputs
                             if f.provenance.period_end).isoformat(),
        "shares": float(snap.shares_outstanding.value) if snap.shares_outstanding else None,
        # what the cover of a named filing says this ticker is, when it was read
        "receipt": receipt,
        # the cover page's own count, kept only so a depositary ratio can be seen:
        # a receipt count on the cover beside an ordinary count in the statements
        "cover_shares": float(snap.cover_shares.value) if snap.cover_shares else None,
        "dividend_per_share": float(snap.dividend_per_share)
                              if snap.dividend_per_share is not None else None,
        "recurring_dividend_per_share": (
            float(snap.recurring_dividend_per_share.value)
            if snap.recurring_dividend_per_share is not None else None),
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
            # the two headline flows, which had no provenance at all: a reader
            # comparing the panel against a filing needs to know WHICH concept the
            # profit is — Occidental and Rhinebeck tag only income available to the
            # common, which their statements never print beside the consolidated line
            ("net_income", _source(_newest(snap.annual_net_income))),
            ("revenue", _source(_newest(snap.annual_revenue))),
            ("total_assets", _source(snap.total_assets)),
            ("total_liabilities", _source(snap.total_liabilities)),
            ("current_assets", _source(snap.current_assets)),
            ("current_liabilities", _source(snap.current_liabilities)),
            ("long_term_debt", _source(snap.long_term_debt)),
            ("short_term_debt", _source(snap.short_term_debt)),
            ("total_debt", _source(snap.total_debt)),
            ("options", _source(snap.options_outstanding)),
            ("rsus", _source(snap.rsus_outstanding)),
            ("goodwill", _source(snap.goodwill)),
            ("intangibles", _source(snap.intangibles)),
            ("preferred_stock", _source(snap.preferred_stock)),
            ("temporary_equity", _source(snap.temporary_equity)),
            ("noncontrolling_interest", _source(snap.noncontrolling_interest)),
            ("shares", _source(snap.shares_outstanding)),
            ("weighted_shares", _source(_newest(snap.annual_share_counts))),
            ("dividend", _source(snap.dividend)),
            ("recurring_dividend_per_share",
             _duration_source(snap.recurring_dividend_per_share, "USD/shares")),
            # the newest annual earnings figure: which element stated it, and in
            # which filing — a restatement changes both
            ("eps", _source(snap.annual_eps[max(snap.annual_eps)]) if snap.annual_eps else None),
        ) if src is not None},
        # scope-switch disclosure: annual series stitched from more than one tag
        "series_mix": {name: mix for name, mix in (
            ("eps", _series_mix(snap.annual_eps)),
            ("weighted_shares", _series_mix(snap.annual_share_counts)),
            ("net_income", _series_mix(snap.annual_net_income)),
            ("revenue", _series_mix(snap.annual_revenue)),
        ) if mix is not None} or None,
    }
    if pending is not None:
        row["data_pending"] = pending
    return ("pending_facts" if pending is not None else "ok"), row


def _derive_evidence(bundle: evidence.EvidenceBundle, quote=None) -> tuple[str, dict | None]:
    """The sole production entry point from assembled evidence to a snapshot."""
    return _derive(bundle.cik, bundle.ticker, bundle.facts, quote=quote,
                   dimensioned=bundle.dimensioned, receipt=bundle.receipt)


def _restate_historical_ratios(ratios: dict, receipt_ratio: Decimal) -> None:
    """Put historical per-share book figures onto the same receipt as its prices.

    Percentages and entity-level totals do not move. The conversion is valid for
    any positive ratio: some receipts represent a fraction of one ordinary share.
    """
    if receipt_ratio <= 0 or receipt_ratio == 1:
        return
    for values in ratios.values():
        for key in ("bvps", "tbvps", "ncavps"):
            if values.get(key) is not None:
                values[key] *= float(receipt_ratio)


# A margin needs a base worth taking a percentage of, and both figures must belong
# to one fiscal year — the trailing composites for income and revenue can close on
# different dates, and a ratio across two windows is not a margin.
_MARGIN_FLOOR = Decimal("1000000")     # revenue below this makes the percentage noise
_RETURN_ON_BOOK_LAG = 800              # a year's earnings over a balance sheet this much newer is not a return


def _profitability(snap) -> dict | None:
    """Graham's two profitability ratios: profit against sales, profit against book.

    Chapter 13 compares four companies on exactly these — the margin says how much
    of each dollar of sales the business keeps, and the return on book value says
    what the shareholders' own capital earns. Neither decides anything here: the six
    criteria are cheapness, stability and solvency, and a company earning two cents
    on the dollar is not thereby disqualified. But it is a different business from
    one earning twenty, and the screen was showing neither figure.

    Return on book is deliberately absent where a fiscal year's earnings would have
    to be divided by a balance sheet from a different era — the defect the audit
    found in ROIC, where Johnson & Johnson's 2014 flows were being divided by a 2026
    balance sheet and shown as a current return.
    """
    revenue, income = snap.annual_revenue, snap.annual_net_income
    operating = snap.annual_operating_income
    years = sorted(y for y in set(revenue) & set(income)
                   if revenue[y].value >= _MARGIN_FLOOR)
    if not years:
        return None
    latest = years[-1]
    def pct(numerator, year):
        return (float(numerator[year].value / revenue[year].value * 100)
                if year in numerator else None)
    series = {y: round(float(income[y].value / revenue[y].value * 100), 2) for y in years[-10:]}

    equity = _common_equity(snap)
    year_end = income[latest].provenance.period_end
    stale = (snap.balance_sheet_date is None or year_end is None
             or (snap.balance_sheet_date - year_end).days > _RETURN_ON_BOOK_LAG)
    on_book = (round(float(income[latest].value / equity * 100), 2)
               if equity and equity > 0 and not stale else None)
    return {
        "fiscal_year": latest,
        "net": round(pct(income, latest), 2),
        "operating": round(pct(operating, latest), 2) if latest in operating else None,
        "on_book": on_book,
        "revenue": float(revenue[latest].value),
        "net_income": float(income[latest].value),
        "book_value": float(equity) if equity else None,
        # the direction matters more than the level: Graham's warning is a margin
        # that erodes while the earnings still look adequate
        "by_year": series,
    }


def _common_equity(snap):
    """What the common shareholders own — the same deductions every per-share figure
    on this page makes: preferred, the minority's share, and mezzanine."""
    if snap.total_assets is None or snap.total_liabilities is None:
        return None
    other = sum(f.value for f in (snap.preferred_stock, snap.noncontrolling_interest,
                                  snap.temporary_equity) if f)
    return snap.total_assets.value - snap.total_liabilities.value - other


def _ttm_basis(snap) -> str:
    """The period behind the trailing EPS, named. One annual fact standing alone is
    the audited year, not a trailing twelve months."""
    inputs = snap.ttm_eps_inputs
    if len(inputs) == 1:
        p = inputs[0].provenance
        if p.period_start and p.period_end and (p.period_end - p.period_start).days > 300:
            return f"fiscal year to {p.period_end.isoformat()}"
    return "latest 12 months"


def _owner_earnings_row(snap) -> dict | None:
    """Serialize owner-earnings evidence without inventing maintenance capex.

    The legacy definitive fields stay present as null so an old client cannot silently
    relabel the all-capex proxy as Buffett owner earnings. The named estimates and FCF
    are the only numeric fields consumers may use.
    """
    oe = snap.owner_earnings
    if oe is None:
        return None
    # The requested view is a calendar of the latest ten fiscal-year slots, not
    # the latest ten observations. Sparse evidence must produce visible gaps
    # rather than reaching farther into the past to fill the quota.
    years = [year for year in sorted(oe.annual)
             if oe.fiscal_year - 9 <= year <= oe.fiscal_year]
    floor_sources = oe.all_capex_floor.provenance.components
    owner_sources = {}
    for name, provenance in zip(
        ("reported_earnings", "depreciation_and_amortisation", "total_capex"),
        floor_sources,
    ):
        owner_sources[name] = {
            "tag": provenance.tag,
            "form": provenance.form,
            "accn": provenance.accession,
            "end": (provenance.period_end.isoformat()
                    if provenance.period_end else None),
            "filed": provenance.filed.isoformat() if provenance.filed else None,
        }
    if oe.free_cash_flow is not None and oe.free_cash_flow.provenance.components:
        provenance = oe.free_cash_flow.provenance.components[0]
        owner_sources["operating_cash_flow"] = {
            "tag": provenance.tag,
            "form": provenance.form,
            "accn": provenance.accession,
            "end": (provenance.period_end.isoformat()
                    if provenance.period_end else None),
            "filed": provenance.filed.isoformat() if provenance.filed else None,
        }
    return {
        "fiscal_year": oe.fiscal_year,
        "status": "ESTIMATE_ONLY",
        "owner_earnings": None,
        "maintenance_capex": None,
        "maintenance_basis": "UNAVAILABLE_PRIMARY_XBRL",
        "all_capex_floor": float(oe.all_capex_floor.value),
        "maintenance_estimate": float(oe.maintenance_estimate.value),
        "free_cash_flow": (float(oe.free_cash_flow.value)
                           if oe.free_cash_flow is not None else None),
        "invested_capital": float(oe.invested_capital) if oe.invested_capital is not None else None,
        "roic": None,
        "all_capex_return": (float(oe.all_capex_return)
                             if oe.all_capex_return is not None else None),
        "maintenance_estimate_return": (
            float(oe.maintenance_estimate_return)
            if oe.maintenance_estimate_return is not None else None),
        "components": [[label, float(v)] for label, v in oe.components],
        "free_cash_flow_components": [
            [label, float(value)] for label, value in oe.free_cash_flow_components],
        # One compact source per filed input. The three derived measures share
        # these inputs; repeating their full provenance trees inflated the UI
        # payload by tens of megabytes without adding evidence.
        "sources": owner_sources,
        "caveats": list(oe.caveats),
        # Ten completed fiscal years, on today's split and traded-security basis.
        # A missing year is omitted rather than imputed; the UI renders the gap.
        "annual_per_share": {
            str(year): {
                "all_capex_floor_per_share": float(
                    oe.annual[year].all_capex_floor_per_share.value),
                "maintenance_estimate_per_share": float(
                    oe.annual[year].maintenance_estimate_per_share.value),
                "free_cash_flow_per_share": (
                    float(oe.annual[year].free_cash_flow_per_share.value)
                    if oe.annual[year].free_cash_flow_per_share is not None else None),
                "diluted_shares": float(oe.annual[year].diluted_shares.value),
                "end": (oe.annual[year].maintenance_estimate_per_share.provenance.period_end.isoformat()
                        if oe.annual[year].maintenance_estimate_per_share.provenance.period_end
                        else None),
            }
            for year in years
        },
    }


def _ncavps(snap) -> float | None:
    """Net current asset value per share — Graham's most conservative yardstick:
    current assets less every liability, ignoring fixed assets entirely, divided by
    shares. Distinct from the net current assets in criterion 3, which subtracts
    only current liabilities."""
    need = (snap.current_assets, snap.total_liabilities, snap.shares_outstanding)
    if any(f is None for f in need) or snap.shares_outstanding.value <= 0:
        return None
    # mezzanine equity is senior to the common the same way preferred is, and
    # tangible book already deducts it; leaving it in here would credit the
    # common with assets it stands behind
    optional = sum(f.value for f in (snap.preferred_stock, snap.noncontrolling_interest,
                                     snap.temporary_equity) if f)
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
    # ...and take the symbol back from whoever used to hold it
    store.resolve_ticker_conflicts(conn, out)
    conn.commit()
    return out


def bootstrap(conn, limit: int | None = None, progress=_print_progress) -> None:
    """Derive from whatever raw facts are already cached locally — no network."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    loader = evidence.EvidenceLoader(conn, edgar)
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
        status, data = _derive_evidence(loader.load(cik, ticker, facts))
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
    loader = evidence.EvidenceLoader(conn, edgar)
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
            status, data = _derive_evidence(loader.load(cik, ticker, facts))
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


def _dera_tags() -> tuple[frozenset[str], frozenset[str]]:
    """The concepts worth carrying over from the quarterly datasets, and which of
    them are per-share. Both come from the chains themselves, so the two sources
    can never drift apart."""
    per_share = frozenset(
        normalize.EPS_TAGS + normalize.EPS_BASIC_TAGS + (normalize.EPS_CONTINUING_TAG,)
        + tuple(tag for tag, unit in normalize.DIVIDEND_TAGS if "USD/shares" in unit)
        + tuple(normalize.IFRS_PER_SHARE_TAGS)
    )
    wanted = frozenset(
        tuple(per_share)
        + tuple(normalize._WEIGHTED_SHARE_TAGS)
        + normalize.NET_INCOME_TAGS + normalize.REVENUE_TAGS
        + normalize.OPERATING_INCOME_TAGS + normalize.PRETAX_TAGS
        + tuple(tag for tag, _ in normalize.DIVIDEND_TAGS)
        + tuple(normalize.IFRS_SOURCE_TAGS)
        + ("Assets", "Liabilities", "AssetsCurrent", "LiabilitiesCurrent",
           "CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding",
           "Goodwill", "IntangibleAssetsNetExcludingGoodwill")
        # Preferred counts live on a share-class axis, so Company Facts returns
        # nothing for them and a convertible preferred cannot be told from one
        # that has already converted. Here the axis survives.
        + normalize.PREFERRED_COUNT_TAGS
    )
    return wanted, per_share


def dera_sync(conn, start: str | None = None, progress=_print_progress) -> None:
    """Carry the dimension-qualified and issuer-extension facts that Company
    Facts cannot express into a sidecar cache beside the raw filings.

    Changed sidecars invalidate their companies' snapshots. The next derive or
    export reads them through the same evidence bundle as every other path."""
    edgar = EdgarClient()
    cache = edgar.cache_dir
    ciks = {r["cik"] for r in conn.execute(
        "SELECT cik FROM company WHERE ticker IS NOT NULL").fetchall()}
    wanted, per_share = _dera_tags()
    first = dera.parse_quarter(start) if start else dera.Quarter(date.today().year - 2, 1)
    quarters = dera.quarters_through(first, dera.latest_published(date.today()))
    progress(f"{len(quarters)} quarters to read for {len(ciks)} companies")
    for i, quarter in enumerate(quarters, 1):
        path = dera.download(quarter, cache, edgar.user_agent)
        if path is None:
            progress(f"{quarter} is not published yet", i, len(quarters))
            continue
        harvested = dera.harvest(path, ciks, wanted, per_share)
        changed = dera.merge_into_sidecars(harvested, cache, quarter)
        for cik in changed:
            store.mark_snapshot_dirty(conn, cik, f"DERA evidence updated through {quarter}")
        conn.commit()
        progress(f"{quarter}: {len(changed)} companies changed", i, len(quarters))
    progress("done", len(quarters), len(quarters))


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


def material_events(submissions: dict) -> tuple[list[dict], str | None]:
    """Material 8-K items in a submissions index, and the oldest filing it shows.

    Which items count is `profiles.EVENT_ITEMS`, beside the notes they become —
    an item is stored only where something is prepared to say what it means.

    The index holds the filer's most recent thousand filings. For nearly every
    company that is its whole history, but a prolific one buries years under
    Form 4s — Wells Fargo's thousand reach back fourteen months — so the scan
    reports the date it could see back to. A window is only claimable when the
    data covers it.
    """
    recent = (submissions.get("filings") or {}).get("recent") or {}
    dates = recent.get("filingDate") or []
    events = []
    for form, filed, codes, accn in zip(recent.get("form") or [], dates,
                                        recent.get("items") or [],
                                        recent.get("accessionNumber") or []):
        if not form.startswith("8-K"):
            continue
        for item in (codes or "").split(","):
            if (item := item.strip()) in profiles.EVENT_ITEMS:
                events.append({"filed": filed, "item": item, "accn": accn})
    return events, min(dates) if dates else None


def events(conn, progress=_print_progress) -> None:
    """What each company's own filing index says happened to it.

    Restatements, bankruptcy, delisting notices, accelerated debt and auditor
    changes are reported as 8-K item numbers, which makes them the only company
    events readable without opening a document. XBRL cannot express any of them:
    a withdrawn financial statement is a statement about facts, not a fact.
    """
    edgar = EdgarClient()
    store.migrate(conn)
    ciks = store.dashboard_ciks(conn)
    progress(f"scanning filing indexes for {len(ciks)} companies", 0, len(ciks))

    def scan(cik: str):
        """Fetch and read one index inside the worker: an index is megabytes and
        what it yields is a handful of dates, so only the dates travel back."""
        try:
            d = edgar.submissions(cik)
            return (cik, *material_events(d), d.get("stateOfIncorporation"),
                    d.get("stateOfIncorporationDescription"))
        except Exception:  # one unreadable index must not stop a 6,000-company scan
            return cik, None, None, None, None

    found = done = 0
    # the SEC's ten-per-second cap is enforced inside the client, so a small pool
    # spends the wait on network latency instead of adding to it
    with ThreadPoolExecutor(max_workers=8) as pool:
        for cik, seen, scanned_from, inc, inc_name in pool.map(scan, ciks):
            done += 1
            if seen is None:
                continue
            store.set_events(conn, cik, seen, scanned_from)
            store.set_incorporation(conn, cik, inc, inc_name)
            found += len(seen)
            if done % 200 == 0:
                conn.commit()
                progress(f"scanning filing indexes — {found} events", done, len(ciks))
    conn.commit()
    progress("done", len(ciks), len(ciks))


def _current_supported_annual(facts: dict) -> tuple[str, str] | None:
    """Newest foreign annual filing when it carries supported USD statements.

    Old facts from another reporting basis can remain after a transition, so the
    accession must match the newest 20-F/40-F represented anywhere in Company Facts.
    """
    namespaces = (facts.get("facts") or {})
    newest, statement_basis = normalize._current_supported_foreign_annual(namespaces)
    if newest is None or statement_basis is None or not newest[1]:
        return None
    return newest[1], newest[0]


def _submissions_identity(d: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Incorporation plus the visible filing-history span from one SEC header."""
    filings = d.get("filings") or {}
    recent = (filings.get("recent") or {}).get("filingDate") or []
    first = [f["filingFrom"] for f in (filings.get("files") or []) if f.get("filingFrom")]
    if recent:
        first.append(min(recent))
    return (d.get("stateOfIncorporation"), d.get("stateOfIncorporationDescription"),
            min(first) if first else None, max(recent) if recent else None)


def cover_pages(conn, progress=_print_progress, *, foreign_only: bool = False,
                ciks: set[str] | None = None) -> None:
    """Read the cover of each company's newest annual filing.

    Two facts there decide what every per-share figure on this dashboard means,
    and no XBRL feed carries either: which share class the ticker prices, and —
    for a depositary receipt — how many ordinary shares one receipt stands for.
    Onconova's cover says "each representing 13 Ordinary Shares" and its market
    capitalisation was thirteen times too large without it.

    Only companies whose figures the answer would change are fetched: a domestic
    filer with one class of common has nothing here that the statements do not
    already say.
    """
    edgar = EdgarClient()
    store.migrate(conn)
    # Every company, not only the ones whose data betrays a question. Onconova is
    # the reason: both its share counts are ordinary, its incorporation field is
    # empty, and nothing anywhere in its XBRL hints that the price belongs to a
    # receipt worth thirteen of them. Targeting the detectable cases would have
    # skipped precisely the case this exists for.
    # the NEWEST filing, not the one that happened to supply the earnings: a filer
    # whose per-share element is dimension-only has an EPS accession years old, and
    # Hershey's was a 2015 cover that predates cover-page tagging entirely
    def newest(row):
        filings = [(s.get("filed"), s.get("accn"))
                   for s in (row.get("sources") or {}).values() if s.get("accn")]
        return max(filings)[1] if filings else None

    todo = [] if foreign_only else [
        (r["cik"], r["ticker"], newest(r), False) for r in store.dashboard_rows(conn)
    ]

    # Foreign-form rows are not on the dashboard yet, so they cannot be reached
    # through dashboard_rows(). Read the cached facts just far enough to select
    # current USD US-GAAP/IFRS 20-F/40-F filers.
    foreign_rows = conn.execute(
        """SELECT c.cik, c.ticker, c.name
           FROM snapshot s JOIN company c USING (cik)
           WHERE s.status = 'foreign' AND c.listed = 'y' AND c.ticker IS NOT NULL
             AND NOT (c.ticker GLOB '*-P' OR c.ticker GLOB '*-P[A-Z]')
           ORDER BY c.cik"""
    ).fetchall()
    for row in foreign_rows:
        if ciks is not None and row["cik"] not in ciks:
            continue
        path = _facts_path(edgar, row["cik"])
        if not path.exists():
            continue
        try:
            current = _current_supported_annual(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
        if current:
            accn, filed = current
            store.upsert_company(conn, row["cik"], row["ticker"], row["name"],
                                 last_filing=filed)
            todo.append((row["cik"], row["ticker"], accn, True))

    # An unchanged cover is immutable. Do not make another SEC request merely
    # because the derivation engine changed; parser improvements are applied to
    # the preserved title by EvidenceLoader.
    covered = {
        (cik, security["symbol"], security["accn"])
        for cik, securities in store.covers_by_cik(conn).items()
        for security in securities
    }
    todo = [(cik, ticker, accn, foreign) for cik, ticker, accn, foreign in todo
            if accn and (cik, ticker, accn) not in covered]
    progress(f"reading cover pages for {len(todo)} companies", 0, len(todo))

    def read(item):
        cik, ticker, accn, foreign = item
        identity = (None, None, None, None)
        if foreign:
            try:
                identity = _submissions_identity(edgar.submissions(cik))
            except Exception:
                pass
        for n in cover.COVER_REPORTS:
            try:
                url = cover.R_URL.format(cik=int(cik), accn=accn.replace("-", ""), n=n)
                found = cover.securities(edgar._get_text(url))
            except Exception:
                continue
            if found:
                for security in found:
                    security["ratio"] = cover.depositary_ratio(security["title"])
                return cik, accn, found, identity
        return cik, accn, [], identity

    done = ratios = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for cik, accn, found, identity in pool.map(read, todo):
            done += 1
            inc, inc_name, first_filed, last_filing = identity
            if inc:
                store.set_incorporation(conn, cik, inc, inc_name)
            if first_filed:
                store.set_first_filed(conn, cik, first_filed)
            if last_filing:
                store.upsert_company(conn, cik, None, None, last_filing=last_filing)
            if found:
                store.set_cover(conn, cik, found, accn)
                ratios += sum(1 for s in found if s["ratio"])
            if done % 100 == 0:
                conn.commit()
                progress(f"reading cover pages — {ratios} depositary ratios", done, len(todo))
    conn.commit()
    progress("done", len(todo), len(todo))


def daily(conn, days: int = 7, progress=_print_progress) -> None:
    """One ~1MB file per day names every company that filed. Refetch only those."""
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    loader = evidence.EvidenceLoader(conn, edgar)
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
            if not line.startswith(normalize.FINANCIAL_FORMS):
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
        status, data = _derive_evidence(loader.load(cik, ticker, facts))
        store.upsert_company(conn, cik, ticker, name, facts_synced=True)
        store.put_snapshot(conn, cik, status, data)
        progress("refetching filers", i, len(pending))
        if i % 50 == 0:
            conn.commit()
    conn.commit()
    progress("done")

    # A newly filed 20-F/40-F can change the registered class or its receipt
    # ratio. The stale cover deliberately made the first derivation unsupported;
    # refresh just those new foreign annual filers, then retry from cached facts.
    if filed:
        cover_pages(conn, progress, foreign_only=True, ciks=set(filed))
        derive(conn, progress)


def derive(conn, progress=_print_progress, *, all_snapshots: bool = False,
           workers: int = 4) -> None:
    """Recompute snapshots after an engine change from cached raw facts.

    Filing reads and normalization are independent per CIK and CPU-bound, so
    separate processes do that expensive work concurrently. SQLite writes stay on
    this calling process: one writer preserves the existing WAL/commit behavior.
    """
    edgar = EdgarClient()
    tickers = _index_tickers(conn, edgar)
    loader = evidence.EvidenceLoader(conn, edgar)
    stale = store.needs_recompute(conn, eligible_only=not all_snapshots)
    scope = "cached" if all_snapshots else "dashboard-eligible"
    progress(f"{len(stale)} {scope} snapshots predate engine v{store.ENGINE_VERSION}",
             0, len(stale))

    tasks = []
    for cik in stale:
        ticker, name = tickers.get(cik, (None, None))
        ticker, receipt = loader.identity(cik, ticker)
        tasks.append((cik, ticker, receipt, str(edgar.cache_dir)))

    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_derive_cached_worker, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            cik, result = future.result()
            if result is not None:
                status, data = result
                store.put_snapshot(conn, cik, status, data)
            if i % 200 == 0:
                conn.commit()
                progress("recomputing snapshots", i, len(stale))
    conn.commit()
    progress("done")

_DORMANT_DAYS = 200   # a filer silent this long has stopped, not merely gone stale


def _span(days: int) -> str:
    """A gap in words. `days // 365` printed "1 years" for everything from 451 to
    723 days, most of which are nearer two."""
    if days < 545:
        return f"{round(days / 30.4)} months"
    years = days / 365
    return f"{years:.1f} years" if years < 10 else f"{round(years)} years"


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
    Portfolio execution snapshots mirror these two thresholds server-side; the
    browser only displays settled criteria."""
    # A symbol absent from SEC's current company/ticker mapping has no verified
    # security identity.  Yahoo may still return a stale quote, or may later reuse
    # the symbol for another issuer; neither may be joined to this CIK's filings.
    # Rows without a `listed` key are direct/unit-test callers and retain the
    # historical API contract.  Exported rows always carry the key.
    if "listed" in row and row.get("listed") != "y":
        price = None
        for field in ("price", "price_asof", "price_session", "market_state",
                      "market_timezone", "market_state_asof", "price_source"):
            row.pop(field, None)
    crit = {c["n"]: c for c in row["criteria"]}
    if price is not None and price > 0 and not row.get("basis_conflict"):
        eps, tbvps = row.get("ttm_eps"), row.get("tbvps")
        # Snapshots are intentionally price-free.  Once export has supplied a
        # live price, do not retain a stale "price quote" token in an otherwise
        # incomplete tangible-book explanation.
        for n in (1, 7):
            note = crit[n].get("note")
            if isinstance(note, str) and note.startswith("missing: "):
                missing = [item.strip() for item in note.removeprefix("missing: ").split(",")]
                missing = [item for item in missing if item != "price quote"]
                crit[n]["note"] = "missing: " + ", ".join(missing) if missing else None
        pa = row.get("price_asof")
        # a dormant filer keeps its ticker; valuing today's price against its last
        # figures from years ago produces a confident, meaningless number
        stale_eps = _too_stale(row.get("earnings_asof"), pa)
        stale_bs = _too_stale(row.get("balance_sheet_date"), pa)
        if stale_eps:
            # Whether the company stopped filing is a question the filing index
            # answers, and the store already holds it: Brookfield filed a 10-Q nine
            # days before this price and was being told it had gone quiet. Absent a
            # filing date, the gap alone is stated and nothing is inferred from it.
            filed = row.get("last_filing")
            dormant = not filed or (date.fromisoformat(pa[:10])
                                    - date.fromisoformat(filed[:10])).days > _DORMANT_DAYS
            crit[1].update(status="INSUFFICIENT_DATA", value=None,
                           note=f"newest earnings are {_span(stale_eps)} older than this price"
                                + ("; the company appears to have stopped filing" if dormant
                                   else f", though it filed on {filed[:10]} — the earnings "
                                        "element it uses has gone stale, not the company"))
            eps = None
        if stale_bs:
            crit[7].update(status="INSUFFICIENT_DATA", value=None,
                           note=f"balance sheet is {_span(stale_bs)} older than this price")
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
        dps = row.get("recurring_dividend_per_share")
        if dps is not None and crit[5]["status"] == "PASS":
            pct = round(dps / price * 100, 2)
            # The engine refuses to publish a yield above par — it means the price
            # and the payment describe different securities — and this pass used to
            # publish it anyway, up to 2,240,506%.
            if pct <= float(YIELD_IMPLAUSIBLE):
                crit[5]["value"] = pct
                # ...and the engine's own note is evidence, not decoration: appending
                # keeps the aggregate-tag and unknown-payer disclosures it wrote.
                source = ((row.get("sources") or {}).get("recurring_dividend_per_share") or {})
                quarter = source.get("end")
                paid = (f"${dps:,.2f} per share annualized from the latest ordinary "
                        "quarterly rate"
                        + (f" reported for the quarter ended {quarter}" if quarter else "")
                        + "; special dividends excluded")
                trailing = row.get("dividend_per_share")
                if trailing is not None and trailing != dps:
                    paid += (f"; trailing cash was ${trailing:,.2f} per share "
                             "including any specials")
                crit[5]["note"] = f"{crit[5]['note']}; {paid}" if crit[5].get("note") else paid
            else:
                crit[5]["value"] = None
                crit[5]["note"] = ((crit[5].get("note") or "")
                                   + f"; yield of {pct}% is not meaningful against this price").lstrip("; ")
        elif crit[5]["status"] == "PASS":
            missing = ("pays a dividend, but no reliable recurring rate is available "
                       "from direct quarterly per-share filing facts")
            crit[5]["value"] = None
            crit[5]["note"] = (f"{crit[5]['note']}; {missing}"
                               if crit[5].get("note") and missing not in crit[5]["note"]
                               else crit[5].get("note") or missing)
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


def _newest(series: dict) -> object | None:
    """The latest year's fact in an annual series, for its provenance."""
    return series[max(series)] if series else None


_HISTORY_COVERAGE_SLACK = 45
_HISTORY_POINT_SLACK = 8
_HISTORY_REVISION_TOLERANCE = Decimal("0.05")
_SPLIT_EVENT_LOOKBACK = 7


def _validated_price_history(
    old_fetched: datetime | None,
    old_closes,
    new_closes,
    split_events=(),
) -> tuple[tuple | None, str | None]:
    """Accept a provider history only when revisions have an evidenced cause.

    Small candle corrections are harmless. A split can legitimately rescale every
    pre-event close, but only by the provider's declared corporate-action factor.
    Unexplained rescaling and suddenly truncated coverage retain the stored series
    instead of silently rewriting every historical multiple in the UI.
    """
    new = tuple((d, Decimal(str(value))) for d, value in new_closes
                if Decimal(str(value)).is_finite() and Decimal(str(value)) > 0)
    if not new:
        return None, "the provider returned no positive historical closes"
    if any(new[i][0] <= new[i - 1][0] for i in range(1, len(new))):
        return None, "the provider returned duplicate or unordered history dates"

    old = tuple((d, Decimal(str(value))) for d, value in old_closes
                if Decimal(str(value)).is_finite() and Decimal(str(value)) > 0)
    if not old:
        return new, None
    if new[0][0] > old[0][0] + timedelta(days=_HISTORY_COVERAGE_SLACK):
        return None, "the refreshed history lost its oldest coverage"
    if new[-1][0] < old[-1][0] - timedelta(days=14):
        return None, "the refreshed history ends before the stored history"
    if len(new) + _HISTORY_POINT_SLACK < len(old):
        return None, "the refreshed history unexpectedly lost weekly observations"

    old_by_date = dict(old)
    overlap = [(d, old_by_date[d], value) for d, value in new if d in old_by_date]
    if len(old) >= 20 and len(overlap) < 8:
        return None, "too few dates overlap the stored history to validate it"

    floor = ((old_fetched.date() - timedelta(days=_SPLIT_EVENT_LOOKBACK))
             if old_fetched is not None else date.max)
    recent_splits = [(d, Decimal(str(factor))) for d, factor in split_events
                     if d >= floor and Decimal(str(factor)) > 0]
    bad = 0
    for day, old_value, new_value in overlap:
        expected = Decimal(1)
        for split_day, factor in recent_splits:
            if day < split_day:
                expected *= factor
        actual = new_value / old_value
        if abs(actual / expected - 1) > _HISTORY_REVISION_TOLERANCE:
            bad += 1
    if bad > max(2, len(overlap) // 20):
        return None, "historical closes were rescaled without matching split evidence"
    return new, None


def _equity_awards(snap) -> dict:
    """Options and restricted stock together, and which of the two are in the figure.

    They dilute the same shareholders and belong in one number, but a company that
    tags only options has said nothing about its restricted stock — so the total
    carries the basis it was struck on, the way a trailing P/E carries `ttm_basis`.
    "options only" is a statement about the evidence, not about the company.
    """
    parts = {"options": snap.options_outstanding, "RSUs": snap.rsus_outstanding}
    present = [k for k, f in parts.items() if f is not None]
    if not present:
        return {"equity_awards": None, "awards_basis": None}
    total = sum((parts[k].value for k in present), Decimal(0))
    basis = " + ".join(present) if len(present) > 1 else f"{present[0]} only"
    return {"equity_awards": float(total), "awards_basis": basis}


def _price_the_ratio_history(row: dict, closes) -> None:
    """Turn each past year's book figures into the multiples the panel shows.

    The price of that year comes from the stored weekly closes, and the earnings
    denominator from `ttm_eps_vintage` — trailing EPS as it was knowable at that
    year end, computed only from facts filed by then. Both sides are therefore
    contemporaries: no ratio prices a 2022 balance sheet against today's quote,
    and none of them knows what the company would report in February.

    "That year end" is the company's own, not the calendar's. Microsoft's fiscal
    2025 closed on 2025-06-30, and pricing it at the following December divided a
    June balance sheet into a December market — its price/book read 10.28 where
    the contemporaneous figure is 10.84. A June filer's newest year fared worse
    still: the cutoff fell in a December that has not arrived, so no vintage EPS
    existed for it and the P/E column was simply blank for 206 companies.
    """
    ratios = row.get("annual_ratios") or {}
    if not ratios or not closes:
        return
    vintage = row.get("ttm_eps_vintage") or {}
    by_date = sorted((d.isoformat() if hasattr(d, "isoformat") else str(d), c) for d, c in closes)
    for year, values in ratios.items():
        # the fiscal year end this row's figures were struck at; only a December
        # filer's is the December the label suggests
        cutoff = values.get("end") or f"{year}-12-31"
        prior = [c for d, c in by_date if d <= cutoff]
        if not prior:
            continue
        price = float(prior[-1])
        values["price"] = round(price, 4)
        eps = vintage.get(cutoff)
        if eps and eps > 0:
            values["pe"] = round(price / float(eps), 2)
        for key, book in (("pb", "bvps"), ("ptbv", "tbvps"), ("pncav", "ncavps")):
            if values.get(book, 0) > 0:
                values[key] = round(price / values[book], 2)


def _price_stats_row(row: dict, closes) -> dict | None:
    """Where the price sits in its own five-year history. Never a criterion."""
    if not closes or not row.get("price"):
        return None
    series = tuple((d, Decimal(str(c))) for d, c in closes)
    stats = pricestats.compute(series, Decimal(str(row["price"])))
    if stats is None:
        return None
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in stats.items()}


_PEER_MINIMUM = 5           # fewer than this and the median describes nothing
_EFFICIENCY_GAP = 0.66      # a margin this far under the peer median is worth stating


def _mark_peer_efficiency(rows: list[dict]) -> None:
    """Operating margin against the median of the company's own industry.

    Graham's sixth Penn Central signal was that its operating ratio had long run
    far worse than a comparable railroad's — the kind of gap that says the
    business is weaker than its peers whatever the reported earnings say. It is
    the one measure here that no single filing can produce, because it needs
    every other filer in the industry, so it is computed at export.
    """
    margins: dict[str, list[float]] = {}
    for row in rows:
        margin = _operating_margin(row)
        if margin is None:
            continue
        row["_margin"] = margin
        industry = row.get("industry")
        if industry:
            margins.setdefault(industry, []).append(margin)
    for row in rows:
        margin = row.pop("_margin", None)
        industry = row.get("industry")
        peers = margins.get(industry or "", ())
        if margin is None or len(peers) < _PEER_MINIMUM:
            continue
        ordered = sorted(peers)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        row["peer_efficiency"] = {
            "margin": round(margin * 100, 1),
            "industry_median": round(median * 100, 1),
            "peers": len(ordered),
            # only a shortfall is worth a reader's attention, and only against a
            # peer group that is itself profitable
            "behind": bool(median > 0 and margin < median * _EFFICIENCY_GAP),
        }


def _operating_margin(row: dict) -> float | None:
    """Latest fiscal year where the company reported both operating income and
    revenue. Banks and insurers report no operating subtotal and get none."""
    income = row.get("annual_operating_income") or {}
    revenue = row.get("annual_revenue") or {}
    shared = sorted(set(income) & set(revenue), reverse=True)
    for year in shared[:1]:
        sales = revenue[year]
        if sales and sales > 0:
            return income[year] / sales
    return None


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


_QUOTE_FIELDS = (
    "price", "price_asof", "price_session", "market_state",
    "market_timezone", "market_state_asof", "price_source",
)


def _previous_dashboard_rows() -> dict[str, dict]:
    """Read the snapshot that readers are using before replacing it.

    An hourly provider miss must not turn a real, dated quote into missing data.
    The previous quote is safe to retain because its timestamp remains attached.
    """
    try:
        payload = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
        return {row["cik"]: row for row in payload.get("rows", []) if row.get("cik")}
    except (OSError, TypeError, ValueError):
        return {}


def _set_quote(row: dict, quote) -> None:
    row.update({
        "price": float(quote.price),
        "price_asof": quote.asof.isoformat(),
        "price_session": quote.session,
        "market_state": quote.market_state,
        "market_timezone": quote.market_timezone,
        "market_state_asof": (
            quote.market_state_asof.isoformat() if quote.market_state_asof else None
        ),
        "price_source": quote.source,
    })


def _retain_previous_quote(row: dict, previous: dict | None) -> bool:
    if previous is None or previous.get("price") is None:
        return False
    for field in _QUOTE_FIELDS:
        if field in previous:
            row[field] = previous[field]
    return True


def export(conn, with_prices: bool = True, progress=_print_progress,
           *, quote_only: bool = False) -> None:
    """Write the whole universe as one JSON file — the UI fetches it once.
    Snapshots below the current engine are recomputed first, so a refresh never
    ships stale arithmetic — recomputation is automatic, not a separate button.

    ``quote_only`` is the hourly path: one small intraday request per ticker and
    the already-validated local weekly histories. A full export still refreshes
    those histories and current index membership lists.
    """
    stale = store.needs_recompute(conn, eligible_only=True)
    if stale:
        derive(conn, progress=progress)
    rows = store.dashboard_rows(conn)
    previous_rows = _previous_dashboard_rows()
    quote_updated = 0
    quote_failed = 0
    if with_prices:
        prices = YahooPriceProvider()
        priceable = [r for r in rows if r.get("ticker") and r.get("listed") == "y"]
        label = "quotes" if quote_only else "prices and history"
        progress(f"fetching {label} for {len(priceable)} verified tickers", 0,
                 len(priceable))
        done = 0
        # Calls are independent. Hourly refreshes ask only for the one-day chart;
        # full exports also replace the five-year weekly history.
        try:
            with ThreadPoolExecutor(max_workers=12) as pool:
                fetch = prices.quote if quote_only else prices.history
                futures = {pool.submit(fetch, r["ticker"]): r for r in priceable}
                for fut in as_completed(futures):
                    row = futures[fut]
                    try:
                        result = fut.result()
                    except Exception:
                        result = None
                    quote = result if quote_only else (result.quote if result else None)
                    if quote is not None:
                        _set_quote(row, quote)
                        quote_updated += 1
                        if not quote_only:
                            row["_history"] = result
                    else:
                        quote_failed += 1
                        retained = quote_only and _retain_previous_quote(
                            row, previous_rows.get(row["cik"])
                        )
                        if quote_only:
                            row["quote_refresh_warning"] = {
                                "kind": "QUOTE_REFRESH_FAILED",
                                "note": (
                                    "the hourly provider request failed; the previous dated quote "
                                    "remains in use" if retained else
                                    "the hourly provider request failed and no previous quote is available"
                                ),
                            }
                    done += 1
                    if done % 25 == 0 or done == len(futures):
                        progress(f"fetching {label}", done, len(futures))
        finally:
            prices.close()
        # the series is written once per company, so a later `derive` can rebuild
        # the statistics without asking the provider for five more years of data
        closes_by_cik = {}
        for row in rows:
            history = row.pop("_history", None)
            closes = None
            if history is not None:
                old_fetched, old_closes = store.price_history_record(conn, row["cik"])
                closes, warning = _validated_price_history(
                    old_fetched, old_closes, history.closes, history.splits)
                if warning is not None:
                    row["price_history_warning"] = {
                        "kind": "HISTORY_REJECTED",
                        "note": warning + "; the previously validated history remains in use",
                    }
                elif closes:
                    store.set_price_history(conn, row["cik"], closes)
            elif quote_only:
                prior = previous_rows.get(row["cik"], {})
                if prior.get("price_history_warning"):
                    row["price_history_warning"] = prior["price_history_warning"]
            apply_price(row, row.get("price"))
            closes_by_cik[row["cik"]] = [] if row.get("listed") != "y" else (
                closes or store.price_history(conn, row["cik"])
            )
            row["price_stats"] = _price_stats_row(row, closes_by_cik[row["cik"]])
        conn.commit()
    else:
        closes_by_cik = {
            r["cik"]: (store.price_history(conn, r["cik"])
                       if r.get("listed") == "y" else [])
            for r in rows
        }
        for row in rows:
            row["price_stats"] = _price_stats_row(row, closes_by_cik[row["cik"]])
    DASHBOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    if with_prices and not quote_only:  # full refresh owns the changing index lists
        _mark_memberships(rows, progress)
    elif quote_only:  # hourly prices must not erase memberships during a list outage
        for row in rows:
            prior = previous_rows.get(row["cik"], {})
            if prior.get("index_memberships"):
                row["index_memberships"] = prior["index_memberships"]
    _mark_peer_efficiency(rows)
    for row in rows:
        row.update(profiles.enrich(row))
    for row in rows:
        _price_the_ratio_history(row, closes_by_cik.get(row["cik"]) or [])
    for row in rows:  # engine-internal series with no reader in the payload
        row.pop("ttm_eps_vintage", None)
        # the event scan is read by the notes above; the raw item codes would be
        # a second, unrendered copy of what those notes already say
        row.pop("filing_events", None)
        row.pop("events_from", None)
        row.pop("last_filing", None)   # read by apply_price, not by the panel
    refreshed_at = store._now()
    payload = {"generated": refreshed_at, "engine_version": store.ENGINE_VERSION, "rows": rows}
    # Readers see either the complete old payload or the complete new one, never
    # a partially-written 35 MB JSON document during an hourly replacement.
    temporary = DASHBOARD_JSON.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(DASHBOARD_JSON)
    store.set_state(conn, "last_export", refreshed_at)
    if with_prices:
        store.set_state(conn, "last_quote_refresh", refreshed_at)
        store.set_state(conn, "last_quote_refresh_updated", str(quote_updated))
        store.set_state(conn, "last_quote_refresh_failed", str(quote_failed))
    conn.commit()
    suffix = (f"; {quote_updated} quotes updated, {quote_failed} retained/missing"
              if quote_only else "")
    progress(f"wrote dashboard.json — {DASHBOARD_JSON.stat().st_size / 1e6:.2f} MB, "
             f"{len(rows)} companies{suffix}", len(rows), len(rows))


def quotes(conn, progress=_print_progress) -> None:
    """Refresh all eligible universe quotes using stored price histories."""
    export(conn, with_prices=True, progress=progress, quote_only=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["bootstrap", "bulk", "metadata", "daily",
                                        "derive", "export", "quotes", "listing-age", "events",
                                        "cover", "dera", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-prices", action="store_true")
    ap.add_argument("--all-snapshots", action="store_true",
                    help="with derive, include cached filers that cannot enter the dashboard")
    ap.add_argument("--from", dest="start", help="first quarter for dera, e.g. 2021q1")
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
        derive(conn, all_snapshots=args.all_snapshots)
    elif args.command == "listing-age":
        listing_age(conn)
    elif args.command == "events":
        events(conn)
    elif args.command == "cover":
        cover_pages(conn)
    elif args.command == "dera":
        dera_sync(conn, args.start)
    elif args.command == "export":
        export(conn, not args.no_prices)
    elif args.command == "quotes":
        quotes(conn)
    else:
        print(json.dumps(store.stats(conn), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
