# Graham Enterprising Screener

Evaluates US-listed SEC filers against Benjamin Graham's Enterprising Investor
criteria (The Intelligent Investor, ch. 15), computed from primary SEC XBRL
filings — never aggregator fundamentals — with provenance for every figure.
The universe includes domestic filers and foreign 20-F/40-F filers when their
current annual report supplies a coherent US-GAAP or standard IFRS balance sheet
in one identifiable currency and its cover resolves the exact common-equity
security (including any depositary ratio). For non-USD statements, explicit
current and fiscal-date FX rates put a USD-listed share price on the reporting
basis; missing FX leaves valuation unavailable rather than guessed.

Six criteria are scored: P/E < 10, current ratio ≥ 1.5, debt ≤ 1.1× net current
assets, positive EPS in each of the last 5 years, a current dividend, and price
≤ 1.2× tangible book value. Graham's earnings-growth test is reported but never
scored — it measured against a fixed 1966 base no modern year can honestly replace.

```
api/   Python: sources → normalisation → screens → FastAPI, plus the local store
web/   React SPA: one fetch of dashboard.json, all filtering client-side
```

## Setup

```sh
make install
export SEC_USER_AGENT="Your Name you@example.com"   # SEC requires a contact
```

## Data

From the dashboard toolbar or the command line — same jobs either way:

| Command | What it does |
|---|---|
| `make bulk` | first full load: SEC's 1.4 GB archive, every US filer |
| `make metadata` | sector, exchange, filer size from SEC's submissions archive |
| `make daily` | refetch only companies that filed since the last run |
| `make events` | material 8-K items — restatements, delisting notices, auditor changes |
| `make cover` | resolve the exact traded class and any depositary-share ratio from annual covers |
| `make quotes` | refresh every eligible quote and atomically rebuild the shared dashboard |
| `make export` | current RTH/pre/post quotes + 5y weekly closes, rebuild `dashboard.json` |
| `make derive` | recompute dashboard-eligible snapshots after an engine change — no refetching |
| `make derive-all` | recompute every cached snapshot, including deferred filers |

Raw filings are cached as files; derived snapshots live in SQLite
(`~/.cache/graham-screener/screener.db`). Missing data is never treated as zero.

## Run

```sh
make dev     # API on :8000 + Vite on :5173
make test    # pytest + node --test
make share   # ngrok tunnel with a write-protecting token, usable from a phone
```

While the API server is running, it automatically runs `make quotes` when the
shared dashboard is at least one hour old. Research and Portfolio both read that
same atomic snapshot; there is no portfolio-only price overlay.

Key API routes: `GET /dashboard.json`, `GET /screen/enterprising/{ticker}`,
`GET /fundamentals/{ticker}` (audit trail: every figure with tag, form, accession).
