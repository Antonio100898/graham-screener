# Graham Enterprising Screener

This repository screens US-listed SEC filers against Benjamin Graham's
Enterprising Investor criteria using primary XBRL filings and per-figure
provenance.
dasd
## Repository map

- `api/`: Python. Data flows from `sources/` through `normalize.py` into
  `screens/`, then through `api.py` (FastAPI). `store.py` manages SQLite at
  `~/.cache/graham-screener/screener.db`; raw filings are cached as files.
- `web/`: React/Vite SPA. It fetches `dashboard.json` once and performs filtering
  and sorting client-side.
- The large Markdown files at the root are design and audit records. Consult the
  relevant one before changing behavior, but do not treat plans as newer than
  tests and implementation.

## Invariants

- Criteria are numbered 1, 2, 3, 4, 5, and 7. There is no criterion 6: Graham's
  growth test is disclosed but never scored. Look criteria up by number (`byN`),
  never by array position.
- Snapshots are stored without prices. At export, `sync.apply_price()` settles
  criteria 1 and 7. The browser does not recompute them; `priceToPass()` only
  answers what price would clear the tests.
- Missing data is never zero. Missing evidence remains `INSUFFICIENT`; only
  `?assume_absent_zero=true` opts out, and that assumption must be disclosed.
- Grade precedence, pinned by `web/test/grade.test.mjs`, is: definitive non-price
  `FAIL` -> `BLOCKED`; any uncomputable criterion -> `UNGRADEABLE`; valuation-only
  failures -> `NEAR-PASS`/`CLOSE`. A measured `FAIL` outranks `INDETERMINATE`.
- Refetch only for new filings. For engine changes, bump `store.ENGINE_VERSION`
  and run `make derive`; do not refetch to repair a code defect.
- Instant facts more than 400 days older than the balance sheet are missing.
  Fundamentals more than 450 days older than the quote withhold price criteria.
- Every extracted figure carries provenance: tag, form, accession, and period end.
  New figures must preserve it. Disclose assumptions and weaker tags in the
  payload rather than silently guessing.

## Validation

- Python tests live in `api/tests/`; JavaScript tests live in `web/test/`.
- Run `make test` for the normal suite (pytest plus `node --test`).
- After an engine change, also run `make regress`, `make audit`, and
  `make audit-filings`. These validate real-company output and filing provenance,
  which synthetic unit fixtures cannot cover.
- `make audit-filings` and several data/export commands use the network.
- Do not claim checks passed when dependencies, cached data, credentials, or
  network access prevented them. Report exactly what ran and what did not.

### Mandatory UI-payload regression gate

After every engine, extraction, evidence, pricing, profile, or serialization
change, validate against the exact `dashboard.json` currently used by the UI.
Unit tests alone are never sufficient.

1. Preserve the pre-change UI payload as the baseline; do not overwrite it first.
2. Run `make regress` against the full universe, not only a sample.
3. Rebuild through the same export/enrichment path the UI consumes.
4. Run `make audit` and, for changed provenance or extraction, `make audit-filings`.
5. Explain every changed field and verdict. Intended changes require filing-backed
   evidence; unexplained changes are regressions and block completion.
6. Check payload identities and UI-derived values, including criteria, verdict,
   market cap, valuation multiples, yields, historical ratios, alignment/profile
   results, notes, source accessions, row count, and ticker/CIK uniqueness.

Never report "zero regressions" when the database, raw filing cache, price inputs,
or baseline UI payload are unavailable. Report the change as unverified and stop
before treating it as release-ready.

## Common commands

```sh
make install   # create api/.venv and install Python and Node dependencies
make test      # Python and web tests
make derive    # recompute snapshots after an engine change, without refetching
make export    # add live prices and rebuild dashboard.json
make dev       # FastAPI on :8000 and Vite on :5173
```

The Makefile uses POSIX paths and shell commands. On native Windows without
`make`, use WSL/Git Bash or invoke the equivalent tools directly; do not rewrite
the Makefile merely to work around the current agent environment.

## Working conventions

- Keep changes focused and preserve unrelated user edits.
- Add or update the narrowest relevant tests with behavioral changes.
- Treat `CLAUDE.md` as compatibility guidance for Claude Code. Keep its shared
  project invariants synchronized when an invariant changes.
