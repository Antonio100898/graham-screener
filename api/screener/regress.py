"""What an engine change did to every number, before it is shipped.

The unit tests pin about 320 synthetic fixtures. The product is 5,892 real
companies times some forty figures each, and the gap between those two is where
every defect in this engine has lived: a share count that moved for 62 filers, a
criterion resurrected after the engine withheld it, an option pool of 1.3 billion
per cent. Each was found by hand-writing a one-off comparison script, and three of
those scripts were themselves wrong — they forgot the dimensioned sidecar, or the
cover ratio, and reported companies as broken that were fine.

So the comparison lives here instead, built once, calling exactly what `derive`
calls. It recomputes a sample against the shipped dashboard and reports what moved,
bucketed by field. It answers the only question that matters after a change: did
this fix the eleven companies it was meant to fix, and what else did it touch?

    python -m screener.regress                 # 600 companies, every field
    python -m screener.regress --all           # every company
    python -m screener.regress --field ttm_eps --sample 2000
    python -m screener.regress --ticker EML,MKL,GYRE
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from . import store
from .sources import dera
from .sources.edgar import EdgarClient
from . import profiles
from .sync import DASHBOARD_JSON, _derive, _index_tickers

# Fields whose value is a live quote or a clock reading rather than a product of
# the engine. They differ on every run and would bury the fields that matter.
VOLATILE = frozenset({
    "price", "quote_time", "generated", "market_cap", "dividend_yield",
    "price_stats", "pe", "ptbv", "pncav", "pb", "engine_version", "as_of",
    # dropped from the payload on the way out: engine-internal, no reader
    "ttm_eps_vintage",
})
# Settled at export against a live quote (criteria 1 and 7 and everything counted
# over them). A recomputation has no quote, so these are carried over from the
# shipped row rather than compared — otherwise every company reads as a regression.
PRICE_SETTLED = frozenset({
    "criteria", "n_pass", "verdict", "grade", "peer", "membership", "in_index",
})
# How far a number may drift before it counts as moved: enough to ignore the last
# decimal place of a rounded figure, not enough to hide a real change.
TOLERANCE = 0.005


def _flat(row: dict, prefix: str = "") -> dict:
    """One row as {field: value}, nested dicts flattened onto dotted keys, so a
    change inside `annual_eps` or `profitability` is attributed to its own field
    rather than to the whole object."""
    out = {}
    for key, value in (row or {}).items():
        name = f"{prefix}{key}"
        if key in VOLATILE:
            continue
        if isinstance(value, dict):
            out.update(_flat(value, f"{name}."))
        elif isinstance(value, list):
            out[name] = json.dumps(value, sort_keys=True)
        else:
            out[name] = value
    return out


def _moved(before, after) -> bool:
    if before == after:
        return False
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        scale = max(abs(before), abs(after), 1e-9)
        return abs(before - after) / scale > TOLERANCE
    return True


def compare(sample: int | None, tickers: set[str] | None, field: str | None,
            progress=print) -> dict:
    """Recompute and diff. Returns {field: [(ticker, before, after), ...]}."""
    shipped = json.loads(Path(DASHBOARD_JSON).read_text())["rows"]
    rows = {r["ticker"]: r for r in shipped if r.get("ticker")}
    if tickers:
        chosen = [rows[t] for t in tickers if t in rows]
    elif sample is None:
        chosen = list(rows.values())
    else:
        random.seed(0)  # the same companies every run, so two runs are comparable
        chosen = random.sample(list(rows.values()), min(sample, len(rows)))

    conn = store.connect()
    edgar = EdgarClient()
    index = _index_tickers(conn, edgar)
    covers = {(cik, s["symbol"]): s
              for cik, found in store.covers_by_cik(conn).items() for s in found}
    # Export builds the auditor and delisting notes from these, then drops them from
    # the payload. Without them the notes cannot be rebuilt and read as deleted.
    events = store.events_by_cik(conn)
    events_from = {r["cik"]: r["events_from"] for r in
                   conn.execute("SELECT cik, events_from FROM company").fetchall()}

    changes: dict[str, list] = defaultdict(list)
    failed = []
    for i, row in enumerate(chosen, 1):
        cik = row["cik"]
        path = Path(edgar.cache_dir) / f"companyfacts_{cik}.json"
        if not path.exists():
            continue
        ticker = index.get(cik, (row["ticker"], None))[0] or row["ticker"]
        try:
            # exactly what derive() passes — the sidecar and the cover ratio
            # included, because leaving either out invents differences
            status, fresh = _derive(cik, ticker, json.loads(path.read_text()),
                                    dimensioned=dera.load_sidecar(path.parent, cik),
                                    receipt=covers.get((cik, ticker)))
        except Exception as exc:                     # a bad filing must not stop the sweep
            failed.append((row["ticker"], repr(exc)[:80]))
            continue
        if not fresh:
            continue
        # `derive` is only half the pipeline. Export merges stored metadata into the
        # row — sector, exchange, filer size — and then enriches it, so a bare
        # recomputation is missing fields the engine never produced and reports them
        # as deleted. Overlaying onto the shipped row keeps whatever `derive` does
        # not own, which is exactly the set that must not count as a change.
        merged = {**row, **{k: v for k, v in fresh.items() if k not in PRICE_SETTLED},
                  "filing_events": events.get(cik, []),
                  "events_from": events_from.get(cik)}
        merged.update(profiles.enrich(merged))
        for gone in ("filing_events", "events_from"):   # popped on the way out
            merged.pop(gone, None)
        old, new = _flat(row), _flat(merged)
        for key in sorted(set(old) | set(new)):
            if field and not key.startswith(field):
                continue
            a, b = old.get(key), new.get(key)
            if _moved(a, b):
                changes[key].append((row["ticker"], a, b))
        if i % 250 == 0:
            progress(f"  {i}/{len(chosen)} compared")
    if failed:
        progress(f"  {len(failed)} companies could not be recomputed: {failed[:3]}")
    return dict(changes), len(chosen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--all", action="store_true", help="every company, not a sample")
    ap.add_argument("--field", help="only fields starting with this prefix")
    ap.add_argument("--ticker", help="comma-separated tickers instead of a sample")
    ap.add_argument("--show", type=int, default=6, help="examples per field")
    args = ap.parse_args(argv)

    tickers = {t.strip().upper() for t in args.ticker.split(",")} if args.ticker else None
    changes, n = compare(None if args.all else args.sample, tickers, args.field)

    if not changes:
        print(f"\nno field moved across {n} companies")
        return 0
    print(f"\n{sum(len(v) for v in changes.values())} changes across {n} companies:\n")
    for key in sorted(changes, key=lambda k: -len(changes[k])):
        hits = changes[key]
        print(f"  {key}  —  {len(hits)} companies ({len(hits) / n * 100:.1f}%)")
        for ticker, before, after in hits[:args.show]:
            print(f"      {ticker:8s} {before!r} -> {after!r}")
        if len(hits) > args.show:
            print(f"      ... and {len(hits) - args.show} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
