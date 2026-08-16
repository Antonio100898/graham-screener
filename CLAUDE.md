# Graham Enterprising Screener

Screens every US-listed SEC filer against Graham's Enterprising Investor criteria
(Intelligent Investor, ch. 15), from primary XBRL filings with per-figure provenance.

## Layout

```
api/   Python. Layers: sources/ (EDGAR, Yahoo, index lists) -> normalize.py
       (facts -> Snapshot) -> screens/ (criteria) -> api.py (FastAPI).
       store.py: SQLite at ~/.cache/graham-screener/screener.db; raw filings cached as files.
web/   React SPA (Vite, no runtime deps beyond React). One fetch of dashboard.json,
       all filtering/sorting client-side.
```

## Invariants — do not break

- **Criteria are numbered 1, 2, 3, 4, 5, 7.** There is no 6 (Graham's growth test
  is disclosed, never scored). Always look up by number (`byN`), never by position.
- **Snapshots are stored price-free.** Criteria 1 and 7 are settled at export by
  `sync.apply_price()`; the same arithmetic is mirrored in `web/src/screen.js` for
  client-side price refresh. Change one → change both.
- **Missing is never zero.** A figure with no evidence stays INSUFFICIENT;
  `?assume_absent_zero=true` is the only opt-out, and it is flagged in the response.
- **Grade precedence** (pinned by `web/test/grade.test.mjs`): definitive non-price
  FAIL → BLOCKED, any uncomputable criterion → UNGRADEABLE, valuation-only fails →
  NEAR-PASS/CLOSE. The engine verdict ranks a measured FAIL above INDETERMINATE.
- **Refetch on new filings only.** Engine changes are recomputed locally: bump
  `store.ENGINE_VERSION`, run `make derive`. Never refetch to fix a code bug.
- **Stale facts are missing facts.** Instant facts >400 days older than the
  balance sheet are dropped; fundamentals >450 days older than the quote withhold
  the price criteria.

## Commands

```sh
make test      # pytest (api/.venv) + node --test (web), both required green
make derive    # recompute snapshots after an engine change
make export    # live prices + rebuild dashboard.json
make dev       # API :8000 + Vite :5173
```

## Conventions

- Python tests in `api/tests/`, JS tests in `web/test/` (`node --test`, zero deps).
- Every extracted figure carries provenance (tag, form, accession, period end);
  new figures must too.
- Disclose rather than guess: when a number rests on an assumption or a weaker
  tag, say so in the payload (`assumptions`, notes), don't silently proceed.
