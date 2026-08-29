# Engine architecture — validated migration

## Objective

The same source artifacts must produce the same financial snapshot regardless of
whether the caller is `bulk`, `daily`, `derive`, the API, or an audit harness.
Price-based conclusions must describe a verified traded security, while filing
facts remain attached to the reporting entity and retain reproducible provenance.

## What was validated

The first proposed boundary is now implemented: `EvidenceLoader` assembles
Company Facts, the DERA dimensioned sidecar, and the matching cover-page security
record. Every production snapshot path and the regression/coverage harness uses
that policy. Fetching remains outside normalization, so fresh Company Facts can be
supplied without creating network behavior inside the calculation engine.

Evidence changes are distinct from code changes. `snapshot_dirty` invalidates a
current-engine snapshot when a cover record or DERA sidecar changes; writing the
replacement snapshot clears that state. Re-reading identical evidence is
idempotent and does not cause a recomputation loop.

The security-adjustment hypothesis was also confirmed. A receipt conversion must
move all per-security values together (shares, current and historical EPS,
dividend/share, BVPS, TBVPS, NCAVPS and their provenance) while leaving entity
dollar totals unchanged. Tests now pin that invariant. This is an intermediate
repair; the transformation should ultimately become its own typed stage.

Security identity now has an operational guard before that larger split. When the
current SEC map omits a CIK, evidence assembly retains the database's last symbol
solely to match its cover and select the correct share class. Export does not ask
the quote provider for that symbol and `apply_price` independently refuses a
supplied quote. Entity fundamentals and the delisting warning remain visible;
price, price history, market value, yield and valuation criteria remain unknown.

Statement presentation scale is now treated as evidence, not guessed from company
size. Some filings state that shares are in thousands or millions while Company
Facts exposes the displayed table number under the plain `shares` unit. A weighted
share count is rescaled only by exactly 1,000 or 1,000,000, only when EPS, income,
count, accession and period all agree, and only when the resulting accounting
identity reconciles within five per cent. Other class, ADR and split disagreements
remain withheld by the security-basis guard.

## Current boundaries

```text
SEC Company Facts ─┐
DERA sidecar ──────┼─> EvidenceBundle ─> build_snapshot ─> FinancialSnapshot
filing cover ──────┘                              │
                                                  └─> security rebasing
quote provider ─────────────────────────────────────> screen/export
```

This is intentionally evolutionary. The tag chains and filing-specific knowledge
in `normalize.py` are valuable and should not be rewritten merely to rearrange
files.

Three operational guards sit across those boundaries:

- Annual statement series share one filing-anchored fiscal calendar. The newest
  credible annual declaration settles whether a January/February year uses the
  ending calendar year or the prior year; comparative columns are propagated from
  that anchor. Non-conflicting dates from an older calendar regime may fill history
  without shifting the current convention.
- When a new 20-F/40-F accession reaches Company Facts before its structured
  statements, `pending_filing` keeps it on the retry queue while normalization
  recomputes and clearly labels the last complete filing. The company therefore
  remains visible without presenting old fundamentals as current.
- Export accepts only positive finite USD quotes. A refreshed weekly history may
  not lose coverage or rescale old closes unless a recent provider split event
  explains the factor; rejected refreshes retain the stored series and add a UI
  warning.
- The running API performs one small quote request for every eligible ticker each
  hour and atomically replaces `dashboard.json`. It reuses validated local weekly
  histories; both Research and Portfolio consume this one snapshot. A failed
  ticker request retains its previous timestamped quote and adds a warning.

## Next boundary: entity versus security

Introduce persistent `security` records keyed independently of CIK, carrying the
symbol, exchange, security kind, quote currency, active state, underlying ratio,
cover accession, and an identity status. SEC filing facts belong to the entity;
quotes and per-share valuation belong to a security.

An unresolved identity may still expose entity-level fundamentals, but must not
settle P/E, P/TBV, market capitalization, P/NCAV, or dividend yield. The existing
prose warning is useful context but is not a sufficient calculation guard. The
interim export guard enforces this today; the persistent security model should
make the rule structural rather than dependent on a `listed` field.

## Next boundary: one evaluator

Store a structured, price-free `FinancialSnapshot`. At API/export time, deserialize
it and call `screens.enterprising.evaluate(snapshot, quote)`. Retire the duplicate
criterion implementation in `sync.apply_price` only after payload-parity tests pin
all notes, staleness decisions, strict boundaries, and verdict precedence.

## Next boundary: dependency-aware invalidation

The current engine version is one global cache key. Any calculation change marks
all 20,266 stored snapshots stale, even when an evidence predicate proves that only
a small subset can be affected. Replace that key with stage/ruleset fingerprints
and artifact hashes: evidence assembly, normalization, security rebasing, profile
evaluation and export enrichment should invalidate their own dependants only.

This is a write-side optimization, not permission to weaken the release gate. A
targeted rebuild may touch only affected snapshots, but the final read-only
regression must still reconstruct and compare every one of the 5,885 UI rows.

## Source policy

- Use SEC bulk Company Facts for the initial universe and efficient full refreshes.
- Use submissions/Company Facts APIs for low-latency incremental filing updates.
- Treat DERA as a quarterly supplement for dimensions and issuer extensions, not
  as the freshness clock.
- Parse a new annual filing's cover as part of ingesting that filing, rather than
  relying on a separate command the normal UI never runs.
- Retain raw artifacts with hashes and source timestamps. A snapshot records the
  artifact hashes and resolver/rules versions that produced it.
- A quote joins only through a verified security record. Provider symbol alone is
  not proof of identity.
- Constituency lists are enrichment inputs with an all-or-nothing contract. Their
  transport must identify the client as Wikimedia requires; an unavailable or
  structurally incomplete list blocks membership replacement instead of silently
  publishing an empty reconstitution.

## Production validation — 2026-08-23

The migration was exercised from an empty local database, not only fixtures:

- Regenerated 20,266 SEC Company Facts snapshots, 21 DERA quarters from 2021q1
  through 2026q1, 5,475 filing covers, and 10,665 material filing events.
- Rebuilt all 20,266 snapshots at engine v89; 18,399 are supported and 1,867 are
  explicitly unsupported foreign filer shapes. No stored snapshot predates v89.
- Compared v85 and v87 on identical regenerated evidence across 5,885 UI rows.
  The only 89 field changes were historical BVPS/TBVPS/NCAVPS for six filed ADR
  ratios: SLN x3, DBVT x5, ONC x13, ZLAB x10, MREO x5 and GPCR x3.
- Compared the final v87 payload with v88 before persistence: seven companies
  gained filing-backed sale/disposal warnings, and no number, ratio, criterion,
  verdict, source, identity field, or historical cell moved.
- Compared v88 with v89 before persistence. The 1,382 changed UI cells were all
  consequences of corrected weighted-share presentation scale: current basis
  conflicts cleared for 35 companies, recent historical BVPS/TBVPS/NCAVPS and
  their price multiples were repaired, and only their dependent criteria,
  profiles, notes and verdicts moved. No revenue, earnings total, balance-sheet
  total, margin, debt, source identity or unrelated field changed. An independent
  raw-fact scan found 597 supported fiscal years across 246 companies: 561 exact
  1,000x corrections and 36 exact 1,000,000x corrections.
- Recomputed v89 against the final live UI payload: no field moved across 5,885
  companies. The strict-JSON artifact is 51,038,271 bytes, generated at
  `2026-08-23T12:16:46+00:00`, with SHA-256
  `64D62B2309252EE53AD0ABDAACE32C1BCB207964F0773C7C89BDC24C550D24ED`.
- Independently checked the final payload: 34,888 sourced values and 105,043
  arithmetic identities matched, with zero wrong. A published-statement sample
  matched 289 lines with zero wrong; 67 lines not printed by that statement
  adapter and 92 payload figures without sufficient independent inputs were
  reported as uncheckable instead of being counted as passes.
- The material-tag/identity coverage gate checked all 5,885 constructed rows and
  a stratified 113-company SEC-fact sample: all constructions were clean and all
  113 had zero unexplained material tags. Thirteen filing identity disagreements
  remain visible and tracked: ten security-basis anomalies withhold affected
  valuation, while three debt-representation differences use the documented
  same-date/later-date selection rule.
- The final universe has 5,885 unique CIKs and tickers: 5,746 current SEC-listed
  identities, 139 unresolved identities with no quote leakage, and 5,604 valid
  positive quotes. The 142 verified tickers without a quote were also unpriced in
  the retained v85 payload except for four new symbols.
- The release suites passed 375 Python tests, 29 browser/logic tests, and the Vite
  production build. MCD now ships price 270.95, TTM EPS 12.31 and P/E 22.01; its
  false security-basis conflict is absent.

The retained UI baseline is the original Downloads payload (engine v85), SHA-256
`5B0D01703A46D0893DF7E3AE9B2322AFB7C4D7E42030D1827A2880E01498BB39`.

## Migration gates

1. Pipeline parity: bulk, daily, derive, API and regression produce identical
   snapshots from one evidence bundle.
2. Security invariants: receipt conversion changes every per-security quantity by
   the same factor and changes no entity total.
3. Temporal invariants: inputs to a ratio share the required period or the ratio is
   withheld with a reason.
4. Release evidence: retain a prior payload and a pinned adversarial filing corpus;
   report every changed field and verdict before accepting an engine version.
5. Universe report: publish counts for verified securities, unresolved identities,
   stale sources, unsupported currencies and criteria withheld by evidence class.

No engine change is release-ready until these gates run against the exact
pre-change `dashboard.json` shown by the UI and the rebuilt full-universe payload.
Synthetic tests establish local rules; they cannot establish zero regressions in
the final product data.

## Deliberately deferred

- Splitting the large normalizer into smaller resolver modules. Do this along
  accounting boundaries only when tests can prove no selection-order change.
- Replacing the quote provider. First establish the security identity contract;
  then Yahoo or a paid provider can implement it without affecting calculations.
- General inline-XBRL parsing. Use it as a targeted fallback after measuring what
  Company Facts plus DERA and covers still cannot resolve.
