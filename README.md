# Graham Enterprising Screener

Evaluates US-listed companies against the six reproducible Enterprising Investor
criteria of Benjamin Graham's Chapter 15 screen, using primary SEC XBRL filings —
never aggregator data — with full provenance for every figure.

His earnings-growth requirement is reported but never scored: it measured the
latest year against a fixed 1966 base, and no modern base year can be attributed
to him (see "There is no criterion 6" in `HOW-IT-WORKS.md`).

Alongside the verdict, each company carries where its price sits in its own
five-year history — distance below the 52-week, 3-year and 5-year highs, distance
above the 52-week low, price against the 3-year median, and how long the drawdown
has lasted. Price against its own past only; what the company earns is the
screen's business. Context for judgment, not criteria.

- `HOW-IT-WORKS.md` — how the engine fetches, normalises and screens, plus known gaps
- `FINDINGS.md` — verification campaigns, bugs found and fixed, open issues

## Layout

```
api/     Python: sources -> normalisation -> screens -> FastAPI, plus the local store
web/     React SPA: one fetch of dashboard.json, all filtering client-side
```

## Setup

```sh
make install
export SEC_USER_AGENT="Your Name you@example.com"   # SEC requires a contact
```

## Loading data

From the dashboard toolbar, or the command line — same jobs either way:

| Button | Command | What it does |
|---|---|---|
| Load all companies | `make bulk` | first full load: SEC's 1.4 GB archive, every US filer at once |
| — | `make metadata` | sector, exchange and filer size from SEC's 1.6 GB submissions archive |
| Fetch new filings | `make daily` | one index file per day, refetch only companies that filed |
| Refresh prices & table | `make export` | new quotes and five years of weekly closes (one request serves both), recompute the valuation criteria and the price-history statistics, rebuild `dashboard.json` |
| Recompute | `make derive` | (only shown when the engine version has moved)  rebuild snapshots after an engine change — no refetching |
| — | `make bootstrap` | derive from whatever is already cached locally (no network) |

One job runs at a time; a second request returns 409 rather than queueing, since
two concurrent loads only fight over the SEC rate limiter. Progress is polled
from `/sync/status`, and the table reloads itself when a job finishes.

Raw filings are cached as files; the derived snapshots live in SQLite
(`~/.cache/graham-screener/screener.db`). Changing the normalisation logic does
**not** require refetching — bump `ENGINE_VERSION` and run `make derive`.

Filings are immutable, but *facts are not*: 46% of companies restate an already
filed year at some point (stock splits, restatements, reclassification). So the
resync trigger is "has this company filed anything since we fetched", never "do
we already have the latest period".

## Running

```sh
make dev     # API on :8000 + Vite on :5173
# or, single process:
make build && cd api && .venv/bin/uvicorn screener.api:app
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard.json` | whole universe, one payload |
| POST | `/sync` | start a load: `{"command": "bulk" \| "daily" \| "export" \| "derive" \| "bootstrap"}` |
| GET | `/sync/status` | job progress + store counts |
| GET | `/screen/enterprising/{ticker}` | six-criterion evaluation + the earnings-growth disclosure |
| GET | `/fundamentals/{ticker}` | audit trail: every figure with tag, form, accession |
| POST | `/screen/enterprising` | batch: `{"tickers": ["AAPL", "JPM"]}` |
| GET | `/health` | liveness + EDGAR reachability |

Optional `?assume_absent_zero=true` treats concepts with no evidence anywhere in
a company's filing history as zero, flagged in the response. Default is strict:
missing is never zero.

## Opening it from a phone

```sh
make share      # starts the API and an ngrok tunnel, prints a URL with a token
```

The tunnel is public, so writes are protected: reading needs nothing, but the
load jobs download gigabytes onto this machine and require the token printed by
the script. Set `SCREENER_TOKEN` yourself to keep a stable one. Without that
variable the app is unprotected, which is fine on localhost and not fine on a
tunnel — `share.sh` always sets it.

## Tests

```sh
make test
```
