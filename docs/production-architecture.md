# Production architecture

## Status

Proposed target architecture. This document defines the intended production
boundary and migration order; it does not claim that PostgreSQL, authentication,
or hosted deployment already exists.

## Objective

Turn the local Graham Screener into a durable web application that can serve
multiple users while preserving the current calculation, evidence, and audit
invariants.

The production system has these properties:

- PostgreSQL is the single application source of truth across every client.
- React reads filtered, sorted, paginated data from FastAPI. It does not load a
  complete `dashboard.json` universe and does not initiate data refreshes.
- One Python application service serves the API and runs automatic scheduled
  ingestion jobs.
- Long jobs are durable and resumable. A restart cannot silently lose their
  progress or leave a partial dataset published.
- Raw SEC and EDINET source documents are retained in object storage with
  hashes, source identity, and retrieval timestamps.
- A completed data version is published atomically. Readers never see a mixture
  of old and new derived snapshots.
- Public company data is shared. Watchlists, portfolios, saved screens, and
  notes belong to authenticated users.
- The existing normalization, screening, missing-data, security-identity, and
  provenance rules remain authoritative.

## Non-goals

The first production migration will not:

- rewrite the financial engine merely to rearrange modules;
- replace filing-backed facts with aggregator fundamentals;
- introduce MongoDB, Redis, Kafka, or a separate worker deployment without a
  measured need;
- compute screens from raw filings during an interactive HTTP request;
- use browser state, GitHub Actions cache, or a generated JSON file as the
  authoritative database;
- make automatic buy or sell recommendations;
- introduce microservices before operational load requires them.

## Architectural decision

Use a modular monolith:

```text
Browsers
   |
   v
React frontend
   |
   v
One Python application service
   |-- FastAPI request handlers
   |-- automatic scheduler
   |-- durable job runner
   |-- SEC / EDINET / JPX / quote adapters
   |-- normalization and screening engine
   |
   +--> PostgreSQL         application source of truth
   +--> Object storage     immutable filing artifacts
```

The API and job runner are separate modules and responsibilities, but initially
run in the same deployed service. If ingestion later competes with HTTP traffic,
the same codebase can be started in two roles without changing data contracts:

```text
python -m screener.server
python -m screener.worker
```

That is an operational split, not a rewrite into separate products.

## Why PostgreSQL rather than MongoDB

The domain has stable relationships and constraints: issuers own securities;
filings contain facts; facts have periods, units, dimensions, and provenance;
snapshots depend on evidence and ruleset versions; portfolios own immutable
trades. Correctness depends on transactions, uniqueness, foreign keys, exact
decimal values, and reproducible joins.

PostgreSQL provides those guarantees and still supports JSONB for structured
payloads whose shape evolves, such as compact derived snapshots, job parameters,
warnings, and provenance summaries. JSONB is a deliberate boundary inside a
relational model, not a reason to make every record an untyped document.

## Sources of truth

There are two related meanings of source:

1. Primary filing documents are the evidentiary source of financial facts.
   Their immutable bytes live in object storage and are addressed by source ID
   and content hash.
2. PostgreSQL is the application's operational source of truth. Every API
   client reads the same active company, snapshot, price, and user records.

Derived values are disposable and reproducible, but their active published
version is stored in PostgreSQL. Object storage is not queried to render an
ordinary company list.

Caches are never authoritative. A cache entry may be deleted at any time and
reconstructed from PostgreSQL or object storage.

## Application service

### HTTP responsibility

FastAPI handles short interactive operations:

- company screening queries;
- company detail and provenance queries;
- market summaries and filter facets;
- authentication and current-user identity;
- tracked companies and saved screens;
- portfolios, trades, manual assets, and notes;
- read-only system freshness and job status.

Public clients do not receive an endpoint that starts SEC, EDINET, price, or
derive jobs. Data refresh policy is owned by the server.

### Scheduler responsibility

During application startup, one instance acquires a PostgreSQL advisory lock and
becomes scheduler leader. It evaluates schedules and creates durable job rows.
If the lock is already held, that instance serves HTTP requests but does not
schedule duplicate work.

Initial schedules:

| Job | Initial cadence |
|---|---|
| SEC daily filing discovery | Daily after the SEC filing day |
| EDINET filing discovery | Daily after the Japanese filing day |
| Material filing events | Daily |
| Security cover/identity completion | After a new annual filing |
| Current quotes | Hourly during supported market sessions |
| Price history | Daily, and when a new security becomes eligible |
| Listing and index metadata | Daily or source-appropriate cadence |
| Retry pending filings | Bounded recurring retry |
| Engine/ruleset migration | Enqueued once after a new deployed version |

Schedules use UTC internally and record the intended market timezone where it
matters. A missed schedule after downtime is detected from persisted state and
queued on startup; it is not silently skipped.

### Job-runner responsibility

The embedded job runner claims queued work from PostgreSQL. Network-bound source
requests use bounded asynchronous concurrency or threads. CPU-heavy snapshot
derivation uses a process pool so it cannot block the API event loop.

The service initially runs one application process and one replica. It must not
start multiple Uvicorn web workers until scheduler leadership and job claiming
have been validated under multiple processes.

FastAPI `BackgroundTasks` is not used for ingestion. It does not provide durable
ownership, checkpoints, recovery, or progress after a process restart.

## Durable jobs and checkpoints

Every long operation is represented in PostgreSQL. A minimal job record contains:

```text
job
  id
  kind
  status                 QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELLED
  parameters             JSONB
  checkpoint             JSONB
  data_version_id
  attempts
  progress_current
  progress_total
  scheduled_for
  started_at
  heartbeat_at
  finished_at
  error_code
  error_summary
  created_at
```

Workers claim jobs with row locking (`FOR UPDATE SKIP LOCKED`) and record a
lease/heartbeat. On startup, a job whose lease expired is made resumable. Recovery
continues from its last committed checkpoint rather than restarting the entire
range.

Checkpoints are source-specific:

- SEC bulk: archive identity plus completed member/CIK;
- SEC daily: last completed filing date and accession;
- EDINET: last completed filing date and document ID;
- derive: last completed entity/security key and ruleset fingerprint;
- prices: last completed security and provider batch;
- export compatibility: last completed active data version.

A checkpoint advances in the same database transaction as the facts or snapshots
it covers. It cannot claim progress that was not committed.

Jobs are idempotent. Reprocessing the same accession, EDINET document, quote
observation, or derived dependency set updates or confirms the same logical
record rather than creating duplicates.

## Atomic data publication

Ingestion and publication are separate states. A refresh may update raw artifacts
and normalized facts incrementally, but readers continue to use the current
active derived version until the replacement passes validation.

```text
active version 184
        |
        |  ingest and derive version 185 in staging
        v
validate identities, row counts, provenance, and arithmetic
        |
        v
single transaction: mark 185 ACTIVE and 184 SUPERSEDED
```

Every list and detail response identifies its `data_version` and generation
time. One request is evaluated against one active version. A company list cannot
contain version 185 rows while its detail endpoint still reads version 184.

The current atomic file replacement behavior of `dashboard.json` therefore
becomes an atomic database version switch.

## Core data model

Names below describe responsibilities, not final migration names.

### Filing and market data

- `issuer`: SEC CIK, EDINET code, legal identity, jurisdiction, metadata.
- `security`: independently keyed traded security, ticker, exchange, security
  kind, quote currency, active state, and verified issuer relationship.
- `security_identity_evidence`: cover accession/document, receipt ratio, share
  class, verification status, and warnings.
- `filing`: source, form/document type, accession/document ID, submission time,
  period, issuer, correction relationship, and artifact hash.
- `filing_artifact`: object key, media type, byte size, content hash, retrieval
  time, and source URL.
- `fact`: canonical concept, exact decimal value, unit, start/end period,
  dimensions/scope, filing, and source tag/namespace.
- `reviewed_fact`: the durable supplement/correction layer described in
  `docs/future-work/reviewed-filing-data.md`.
- `quote`: security, price, currency, timestamp, session, provider, and source
  state.
- `price_history`: security, observation date, adjusted/validated close, source,
  and validation metadata.
- `fx_observation`: base/counter currencies, rate, date/time, and source.
- `filing_event`: filing-backed material event and exact source identity.

### Derivation and publication

- `ruleset`: engine/stage fingerprints and deployed code identity.
- `evidence_bundle`: artifact/fact hashes used to construct a snapshot.
- `financial_snapshot`: price-free normalized output for one issuer/security and
  ruleset, stored in typed columns plus JSONB where the structure is genuinely
  nested.
- `evaluated_snapshot`: price/FX-settled criteria, grades, profiles, notes, and
  compact detail evidence for one data version.
- `data_version`: BUILDING, VALIDATING, ACTIVE, SUPERSEDED, or REJECTED, with
  universe counts and validation results.
- `job` and `job_event`: durable execution state and bounded diagnostic history.

### User data

- `user_account`: external authentication subject and application status.
- `tracked_company`: user and issuer/security relationship plus note.
- `saved_screen`: named filter/sort configuration owned by a user.
- `portfolio`: user-owned portfolio and base currency.
- `portfolio_trade`: immutable decimal-valued execution record and decision
  snapshot reference.
- `portfolio_asset` and `portfolio_cash`: current non-stock/manual holdings.
- `company_note`: private user research attached to an issuer/security.

Public market data is shared by every user. Private rows always carry an owner
and are protected by authorization checks in the API and database access layer.

## API design

### Company list

React requests only the rows it needs:

```http
GET /api/companies
    ?query=steel
    &exchange=NYSE
    &max_pe=15
    &max_pe3=20
    &min_positive_eps_years=7
    &sort=pe
    &direction=asc
    &limit=100
    &cursor=...
```

Example response shape:

```json
{
  "data_version": 185,
  "generated_at": "2026-09-25T04:30:00Z",
  "items": [],
  "next_cursor": "opaque-value",
  "total": 428
}
```

Cursor pagination is preferred over large offsets for stable traversal. Sort
keys have deterministic tie-breakers, normally security/issuer ID.

Filtering occurs on stored evaluated fields. An interactive request never parses
XBRL or recalculates the universe.

### Detail and supporting endpoints

Initial public/read endpoints:

```text
GET /api/companies/{security_id}
GET /api/companies/{security_id}/fundamentals
GET /api/companies/{security_id}/filings
GET /api/filters
GET /api/market-summary
GET /api/data-version
GET /api/system/freshness
```

Initial authenticated endpoints:

```text
GET/POST/DELETE /api/me/tracked/...
GET/POST/PATCH/DELETE /api/me/saved-screens/...
GET/POST/PATCH/DELETE /api/me/portfolios/...
GET/POST/DELETE /api/me/portfolios/{id}/trades/...
```

Operational job mutation endpoints are private administrative interfaces, not
buttons available to ordinary React clients.

### Facets and counts

The API returns filter options and counts for the active data version. Expensive
facet combinations may use short-lived caches or precomputed summaries, but a
cache key always includes the data version and relevant authorization scope.

## Indexing strategy

The first PostgreSQL indexes should follow measured UI access patterns:

- active data version plus ticker/security ID;
- active version plus exchange, profile, sector, and alignment status;
- active version plus positive P/E, P/E3, market cap, and criteria-passed count;
- filing source plus accession/document ID unique indexes;
- fact uniqueness across filing, concept, period, unit, and dimension hash;
- quote security plus timestamp;
- job status plus scheduled time and lease expiry;
- user-owned rows by user ID and stable child key.

Do not create an index for every possible payload field. Use query plans and
production measurements to add composite or partial indexes.

## Caching policy

PostgreSQL is queried directly at first. Add only these low-risk layers:

- HTTP `ETag` or version-aware conditional responses;
- a small in-process cache for public filter metadata and market summaries;
- CDN caching for explicitly public, versioned GET responses;
- PostgreSQL connection pooling.

No cache stores authoritative job progress, facts, portfolios, or notes. Redis is
deferred until measurements show that cross-instance cache sharing or queue
throughput justifies another operational dependency.

## Object storage

Use an S3-compatible API so development and hosting are portable. Local
development can use MinIO; production can use AWS S3, Cloudflare R2, Backblaze
B2, or a compatible managed service.

Object keys are content- or source-addressed and never contain secrets. Metadata
in PostgreSQL records the expected hash and source identity. Upload completes
before the corresponding filing is eligible for derivation.

Retention policy:

- primary filing archives and reviewed source documents: retain indefinitely;
- reproducible temporary extraction products: lifecycle-managed;
- generated compatibility artifacts: short retention and never authoritative;
- user uploads, if later supported: private bucket/prefix with explicit access
  policy and deletion semantics.

## Ten-year EDINET backfill

One annual cycle (about 400 days) is enough to discover current filers, but it is
not equivalent to the SEC ten-year evidence path. SEC Company Facts commonly
returns many historical periods in one issuer response. EDINET exposes separate
dated filing lists and separate archives.

The parity target is approximately September 2016 through September 2026, subject
to verified API/archive availability. The backfill must:

1. Enumerate filing dates in bounded chunks.
2. Retain only supported annual reports and corrections for current verified JPX
   common-equity listings.
3. Record each date/document checkpoint transactionally.
4. Cache the dated list response and store every downloaded archive by hash.
5. Treat malformed or unsupported filings as explicit per-document outcomes, not
   fatal errors for the range.
6. Merge successive annual filings without duplicating the same document.
7. Preserve taxonomy/source tag, document ID, unit, period, currency, and exact
   source row for every accepted fact.
8. Produce ten-year evidence only from actually available fiscal periods; missing
   years remain missing.
9. Retry bounded transient failures without restarting completed years.
10. Publish the Japanese universe only after uniqueness, currency, quote identity,
    provenance, and payload regression gates pass.

Backfill progress is visible through administrative status but is not initiated
by React. Normal daily EDINET discovery continues from its own cursor after the
historical job completes.

## Failure and recovery

- A process restart expires its job lease; the next scheduler leader resumes from
  the committed checkpoint.
- A source outage fails or delays only its job. The active data version remains
  available.
- A malformed filing is recorded with a stable unsupported/error reason and does
  not abort unrelated filings.
- Repeated transient failures use capped exponential backoff and eventually move
  to a visible failed state.
- A validation failure marks the candidate data version REJECTED. It does not
  replace the active version.
- Database migrations are forward-only in production and run before application
  traffic reaches code that requires the new schema.
- PostgreSQL has automated backups and tested point-in-time recovery.
- Object storage uses versioning or equivalent protection for primary artifacts.

## Authentication and authorization

Use an external OpenID Connect provider rather than storing passwords in this
application. The provider may change without changing the internal `user_account`
identity contract.

Public company research endpoints may remain anonymous. Portfolio, tracking,
saved-screen, notes, and administrative endpoints require authentication.

Authorization is server-side on every private operation. A client-supplied user
ID is never trusted. Administrative job controls require a separate role and are
not inferred from possession of an ordinary account.

## Deployment

Keep provider-specific choices outside the domain code.

Minimum production resources:

- one containerized Python application service;
- one managed PostgreSQL database;
- one S3-compatible object store;
- one static React deployment/CDN;
- one OpenID Connect application registration;
- centralized logs and an error-reporting destination.

The application service runs one process initially. Health checks distinguish:

- liveness: the process/event loop responds;
- readiness: required schema and database connectivity are available;
- freshness: sources and active data version are within disclosed expectations.

Freshness degradation does not necessarily make the API unready; stale data stays
available with explicit timestamps and warnings.

## Local development

Use Docker Compose for PostgreSQL and MinIO. Run React and FastAPI normally from
the repository. Provide deterministic seed/migration commands.

SQLite may remain temporarily as a compatibility backend while repository
boundaries are introduced. Production features must not depend on SQLite-specific
SQL or file-copy behavior. Once migration parity is proven, SQLite becomes an
optional lightweight mode rather than the reference implementation.

## Observability

Structured logs include job ID, data version, source, issuer/security identity,
filing/accession/document ID, and bounded error codes. They never include API
keys or private portfolio contents unnecessarily.

Initial metrics:

- HTTP request latency/error rate by route;
- database pool saturation and query latency;
- active data version age;
- latest successful SEC, EDINET, quote, and metadata refresh;
- queued/running/failed jobs and expired leases;
- filings discovered, accepted, skipped, failed, and retried;
- snapshot derivation throughput and validation failures;
- universe, identity, quote, and provenance counts.

Alert on missing daily discovery, repeated job failure, stuck heartbeat, rejected
publication, database capacity, and unexpectedly large universe/identity changes.

## Validation and release gates

The repository invariants and current mandatory payload gate remain in force.
The migration adds these checks:

1. SQLite/PostgreSQL parity on a pinned fixture database during transition.
2. Full-universe reconstruction against the exact pre-change active payload.
3. API list/detail agreement for one active data version.
4. Atomic-publication tests proving BUILDING rows cannot leak to readers.
5. Job restart tests proving checkpoints neither skip nor duplicate filings.
6. Concurrent scheduler tests proving only one leader queues each scheduled job.
7. Object hash tests proving stored artifacts match recorded bytes.
8. Authorization tests proving one user cannot read or mutate another user's data.
9. Backup/restore rehearsal for PostgreSQL and primary filing artifacts.
10. Load tests for representative filter, sort, pagination, and detail queries.

No migration is complete merely because unit tests pass. Production-shaped data,
filing provenance, row identity, price/FX behavior, and every changed verdict must
remain explainable.

## Migration plan

### Phase 0 — contracts and decisions

- Accept this architecture and record provider-neutral configuration contracts.
- Inventory every direct `sqlite3` call and filesystem cache dependency.
- Pin the current full dashboard payload, database statistics, and audit output.
- Define typed repository interfaces without changing financial behavior.

### Phase 1 — PostgreSQL foundation

- Add PostgreSQL development services and Alembic migrations.
- Implement issuer, security, filing, artifact, job, data-version, and user tables.
- Port the current local ledger with exact decimals and ownership-ready keys.
- Add a one-time SQLite-to-PostgreSQL migration command and reconciliation report.

### Phase 2 — durable artifacts and ingestion

- Introduce an object-store interface and local MinIO implementation.
- Move SEC/EDINET raw-cache writes behind that interface.
- Make source ingest idempotent and checkpointed.
- Preserve the current `EvidenceLoader` and normalization contracts.

### Phase 3 — automatic jobs in the application service

- Add scheduler leadership, durable job claiming, leases, heartbeats, and retries.
- Move hourly quotes and filing discovery out of request-triggered behavior.
- Add private operational status and administrative controls.
- Prove restart/resume behavior under forced termination.

### Phase 4 — versioned API reads

- Persist price-free and evaluated snapshots by data version.
- Implement filtered, sorted, cursor-paginated company endpoints.
- Implement detail, provenance, facets, market summary, and freshness endpoints.
- Switch React from full-payload filtering to API queries.
- Retain `dashboard.json` only as a temporary compatibility/export tool.

### Phase 5 — multi-user application

- Add OpenID Connect authentication.
- Associate tracked companies, saved screens, portfolios, trades, assets, cash,
  and notes with a user account.
- Migrate the current local portfolio into an explicitly selected initial user.
- Add authorization and audit logging for private mutations.

### Phase 6 — historical backfills and deployment

- Deploy the database, object store, application service, and React frontend.
- Migrate and reconcile the current SEC universe.
- Run the resumable ten-year EDINET backfill.
- Run full regression, audit, filing audit, identity, and uniqueness gates.
- Atomically activate the first production data version.

### Phase 7 — measured scaling

Only after observing production load:

- add API replicas;
- run the same application package in a separate worker role;
- introduce Redis or another queue/cache if PostgreSQL job claiming or query
  caching becomes a measured bottleneck;
- add read replicas or analytical storage if reporting load warrants them.

## Definition of done

The production migration is complete when:

- two different clients receive the same active public data version;
- no client action is required to refresh market or filing data;
- a forced restart during SEC or EDINET ingestion resumes without a duplicate or
  missing accepted filing;
- a candidate refresh cannot partially alter public API results;
- the full SEC and ten-year EDINET evidence sets can be rebuilt from retained
  primary artifacts;
- every displayed fact retains its required provenance;
- user A cannot observe or mutate user B's private research or portfolio data;
- the complete UI-payload/API regression and filing audits pass with every
  intentional change explained;
- deployment and database restoration have been rehearsed from documented steps.
