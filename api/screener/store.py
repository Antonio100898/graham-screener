"""Local store: what has been fetched, and what has been derived from it.

Raw companyfacts stay as files in the EdgarClient cache — they are large blobs
nothing queries. SQLite holds the small, queryable part: which companies exist,
when each last filed, and the derived snapshot per company.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from . import sectors

# Bump when normalisation changes meaning; snapshots below this are recomputed
# from stored raw facts, with no refetching.
ENGINE_VERSION = 46  # derived EPS and TTM where the per-share element is dimension-only or stale

DEFAULT_DB = Path.home() / ".cache" / "graham-screener" / "screener.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS company (
    cik           TEXT PRIMARY KEY,
    ticker        TEXT,
    name          TEXT,
    last_filing   TEXT,   -- newest 10-K/10-Q filing date seen, drives resync
    facts_synced  TEXT,   -- when raw companyfacts were last fetched
    -- from SEC's submissions feed: authoritative, and the only sector source that
    -- survives 6,000 lookups (Yahoo rate-limits after one)
    sic           TEXT,
    industry      TEXT,   -- SEC's detailed SIC description
    sector        TEXT,   -- coarse, investor-facing grouping of the SIC code
    exchange      TEXT,
    filer_size    TEXT,
    first_filed   TEXT    -- the company's first-ever SEC filing date; gates windowed tests
);
CREATE INDEX IF NOT EXISTS company_ticker ON company(ticker);
CREATE INDEX IF NOT EXISTS company_industry ON company(industry);

CREATE TABLE IF NOT EXISTS snapshot (
    cik            TEXT PRIMARY KEY,
    engine_version INTEGER NOT NULL,
    computed_at    TEXT NOT NULL,
    status         TEXT NOT NULL,   -- ok | foreign | no_xbrl | error
    data           TEXT             -- derived snapshot + screen result, JSON
);
CREATE INDEX IF NOT EXISTS snapshot_stale ON snapshot(engine_version);

-- keyed on CIK, not ticker: symbols change hands (VSCO became VSXY) but the
-- company identity does not
CREATE TABLE IF NOT EXISTS tracked (
    cik      TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    note     TEXT
);

-- weekly closes, kept so the price statistics can be recomputed without asking
-- the provider for five years of history again
CREATE TABLE IF NOT EXISTS price_history (
    cik        TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    series     TEXT NOT NULL   -- [[iso date, close], ...] oldest first
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


REQUIRED_TABLES = frozenset({"company", "snapshot", "sync_state", "tracked", "price_history"})


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Opening a connection must never need a write lock, or the status endpoint
    fails while a sync job holds one. Schema is created only when absent."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # readers see a consistent snapshot mid-write
    conn.execute("PRAGMA busy_timeout=10000")  # wait for a writer rather than erroring
    # Checking every table, not just the first: a later release adds tables, and an
    # existing database would otherwise never get them. The read stays lock-free;
    # only a genuinely missing table triggers a write.
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not REQUIRED_TABLES <= have:
        conn.executescript(SCHEMA)
    return conn


def migrate(conn) -> None:
    """One-off repairs and column additions, run by sync jobs — never by a reader."""
    conn.executescript(SCHEMA)   # creates tables added after the first run
    have = {r["name"] for r in conn.execute("PRAGMA table_info(company)")}
    for col in ("sic", "industry", "sector", "exchange", "filer_size", "first_filed"):
        if col not in have:
            conn.execute(f"ALTER TABLE company ADD COLUMN {col} TEXT")
    conn.execute("UPDATE company SET last_filing = NULL WHERE last_filing = ''")
    # a CIK is not a ticker: earlier loads wrote one when SEC's map had no symbol
    conn.execute("UPDATE company SET ticker = NULL "
                 "WHERE ticker GLOB '[0-9]*' AND length(ticker) = 10")
    backfill_sectors(conn)
    conn.commit()


def backfill_sectors(conn) -> None:
    """Sector is derived from SIC, so it can be filled in without refetching."""
    rows = conn.execute(
        "SELECT cik, sic FROM company WHERE sic IS NOT NULL AND sector IS NULL"
    ).fetchall()
    for r in rows:
        conn.execute("UPDATE company SET sector = ? WHERE cik = ?",
                     (sectors.sector_for(r["sic"]), r["cik"]))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_company(conn, cik: str, ticker: str | None, name: str | None,
                   last_filing: str | None = None, facts_synced: bool = False) -> None:
    conn.execute(
        """INSERT INTO company (cik, ticker, name, last_filing, facts_synced)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cik) DO UPDATE SET
             ticker       = COALESCE(excluded.ticker, company.ticker),
             name         = COALESCE(excluded.name, company.name),
             -- NULLIF keeps "never seen filing" as NULL; an empty string would be
             -- NOT NULL and queue every known ticker for refetch
             last_filing  = NULLIF(MAX(COALESCE(excluded.last_filing, ''),
                                       COALESCE(company.last_filing, '')), ''),
             facts_synced = COALESCE(excluded.facts_synced, company.facts_synced)""",
        (cik, ticker, name, last_filing, _now() if facts_synced else None),
    )


def put_snapshot(conn, cik: str, status: str, data: dict | None) -> None:
    conn.execute(
        """INSERT INTO snapshot (cik, engine_version, computed_at, status, data)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cik) DO UPDATE SET
             engine_version = excluded.engine_version,
             computed_at    = excluded.computed_at,
             status         = excluded.status,
             data           = excluded.data""",
        (cik, ENGINE_VERSION, _now(), status, json.dumps(data) if data else None),
    )


# a filer with no XBRL on SEC's side has nothing a recompute could read — only a
# refetch can change it, so it never counts as "stale under the current engine"
_UNRECOMPUTABLE = "('no_xbrl')"


def needs_recompute(conn) -> list[str]:
    """Companies whose derived snapshot predates the current engine — recomputed
    from stored raw facts, never refetched."""
    rows = conn.execute(
        f"SELECT cik FROM snapshot WHERE engine_version < ? AND status NOT IN {_UNRECOMPUTABLE}",
        (ENGINE_VERSION,),
    ).fetchall()
    return [r["cik"] for r in rows]


def needs_refetch(conn) -> list[str]:
    """Companies that filed something newer than our last fetch. A new filing can
    restate years we already hold, so 'do we have the latest period' is not enough."""
    rows = conn.execute(
        """SELECT cik FROM company
           WHERE last_filing IS NOT NULL
             AND (facts_synced IS NULL OR substr(facts_synced, 1, 10) < last_filing)"""
    ).fetchall()
    return [r["cik"] for r in rows]


def get_state(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def dashboard_rows(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT c.ticker, c.name, c.industry, c.sector, c.exchange, c.filer_size,
                  c.first_filed, s.data
           FROM snapshot s JOIN company c USING (cik)
           WHERE s.status = 'ok' AND s.data IS NOT NULL
             -- an unlisted filer has no ticker, no price, and cannot be bought
             AND c.ticker IS NOT NULL"""
    ).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["ticker"] = r["ticker"] or d.get("ticker")
        d.update(name=r["name"], industry=r["industry"], sector=r["sector"],
                 exchange=r["exchange"], filer_size=r["filer_size"],
                 first_filed=r["first_filed"])
        out.append(d)
    return out


def set_first_filed(conn, cik: str, first_filed: str) -> None:
    conn.execute("UPDATE company SET first_filed = ? WHERE cik = ?", (first_filed, cik))


def set_metadata(conn, cik: str, sic, industry, exchange, filer_size, ticker=None, name=None) -> None:
    conn.execute(
        """UPDATE company SET sic = COALESCE(?, sic), industry = COALESCE(?, industry),
               sector = COALESCE(?, sector),
               exchange = COALESCE(?, exchange), filer_size = COALESCE(?, filer_size),
               ticker = COALESCE(ticker, ?), name = COALESCE(?, name)
           WHERE cik = ?""",
        (sic, industry, sectors.sector_for(sic), exchange, filer_size, ticker, name, cik),
    )


def tracked(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT t.cik, t.added_at, t.note, c.ticker, c.name
           FROM tracked t LEFT JOIN company c USING (cik)
           ORDER BY t.added_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def track(conn, cik: str, note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO tracked (cik, added_at, note) VALUES (?, ?, ?) "
        "ON CONFLICT(cik) DO UPDATE SET note = COALESCE(excluded.note, tracked.note)",
        (cik, _now(), note),
    )
    conn.commit()


def untrack(conn, cik: str) -> bool:
    changed = conn.execute("DELETE FROM tracked WHERE cik = ?", (cik,)).rowcount
    conn.commit()
    return bool(changed)


def set_price_history(conn, cik: str, closes) -> None:
    """Closes as (date, Decimal) pairs; stored as floats — this is a chart series,
    not money being added up, and the statistics over it are ratios."""
    conn.execute(
        "INSERT INTO price_history (cik, fetched_at, series) VALUES (?, ?, ?) "
        "ON CONFLICT(cik) DO UPDATE SET fetched_at = excluded.fetched_at, "
        "series = excluded.series",
        (cik, _now(), json.dumps([[d.isoformat(), float(c)] for d, c in closes])),
    )


def price_history(conn, cik: str) -> list[tuple[date, float]]:
    row = conn.execute("SELECT series FROM price_history WHERE cik = ?", (cik,)).fetchone()
    if row is None:
        return []
    return [(date.fromisoformat(d), c) for d, c in json.loads(row["series"])]


def stats(conn) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "companies": q("SELECT COUNT(*) FROM company"),
        "snapshots": q("SELECT COUNT(*) FROM snapshot"),
        "ok": q("SELECT COUNT(*) FROM snapshot WHERE status='ok'"),
        "stale": conn.execute(
            f"SELECT COUNT(*) FROM snapshot WHERE engine_version < ? "
            f"AND status NOT IN {_UNRECOMPUTABLE}", (ENGINE_VERSION,)
        ).fetchone()[0],
        "pending_refetch": q(
            """SELECT COUNT(*) FROM company WHERE last_filing IS NOT NULL
               AND (facts_synced IS NULL OR substr(facts_synced,1,10) < last_filing)"""),
        "last_daily_index": get_state(conn, "last_daily_index"),
        "price_histories": q("SELECT COUNT(*) FROM price_history"),
        "engine_version": ENGINE_VERSION,
        # freshness for the UI: when filings were last fetched, when the newest
        # snapshot was computed, when prices/dashboard were last rebuilt
        "last_fetch": q("SELECT MAX(facts_synced) FROM company"),
        "computed_at": q("SELECT MAX(computed_at) FROM snapshot"),
        "last_export": get_state(conn, "last_export"),
    }


def today() -> date:
    return datetime.now(timezone.utc).date()
