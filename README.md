# Graham Enterprising Screener

Evaluates every US-listed company against Benjamin Graham's Enterprising Investor
criteria (The Intelligent Investor, ch. 15), computed from primary SEC XBRL
filings — never aggregator data — with provenance for every figure.

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
| `make export` | live quotes + 5y weekly closes, rebuild `dashboard.json` |
| `make derive` | recompute snapshots after an engine change — no refetching |

Raw filings are cached as files; derived snapshots live in SQLite
(`~/.cache/graham-screener/screener.db`). Missing data is never treated as zero.

## Run

```sh
make dev     # API on :8000 + Vite on :5173
make test    # pytest + node --test
make share   # ngrok tunnel with a write-protecting token, usable from a phone
```

Key API routes: `GET /dashboard.json`, `GET /screen/enterprising/{ticker}`,
`GET /fundamentals/{ticker}` (audit trail: every figure with tag, form, accession).
