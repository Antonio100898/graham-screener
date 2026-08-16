"""Store and price-application tests — no network."""
import json

from screener import store
from screener.sync import apply_price


def row(ttm=5.0, tbvps=10.0, others="PASS"):
    return {
        "ttm_eps": ttm, "tbvps": tbvps,
        "criteria": [
            {"n": 1, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
            *[{"n": n, "status": others, "value": None, "note": None} for n in (2, 3, 4, 5)],
            {"n": 7, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
        ],
    }


def test_price_settles_valuation_criteria():
    r = apply_price(row(ttm=5.0, tbvps=10.0), price=40.0)  # P/E 8, P/TBV 4
    c = {x["n"]: x for x in r["criteria"]}
    assert c[1]["status"] == "PASS" and c[1]["value"] == 8.0
    assert c[7]["status"] == "FAIL" and c[7]["value"] == 4.0
    assert r["verdict"] == "FAIL"


def test_every_criterion_passing_gives_pass_verdict():
    r = apply_price(row(ttm=5.0, tbvps=40.0), price=40.0)  # P/E 8, P/TBV 1.0
    assert r["n_pass"] == 6
    assert r["verdict"] == "PASS"


def test_missing_price_leaves_criteria_unknown():
    r = apply_price(row(), price=None)
    assert r["verdict"] == "INDETERMINATE"
    assert all(c["status"] == "INSUFFICIENT_DATA" for c in r["criteria"] if c["n"] in (1, 7))


def test_negative_eps_fails_rather_than_unknown():
    r = apply_price(row(ttm=-2.0), price=40.0)
    assert {c["n"]: c for c in r["criteria"]}[1]["status"] == "FAIL"


def test_not_applicable_never_yields_pass(tmp_path):
    r = apply_price(row(ttm=5.0, tbvps=40.0, others="NOT_APPLICABLE"), price=40.0)
    assert r["verdict"] == "INDETERMINATE"


def test_store_roundtrip_and_staleness(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0000000001", "TEST", "Test Co", last_filing="2026-08-01")
    store.put_snapshot(conn, "0000000001", "ok", {"ticker": "TEST", "verdict": "FAIL"})
    assert store.dashboard_rows(conn)[0]["ticker"] == "TEST"
    # a company that filed after our last fetch must be queued for refetch
    assert store.needs_refetch(conn) == ["0000000001"]
    store.upsert_company(conn, "0000000001", "TEST", "Test Co", facts_synced=True)
    assert store.needs_refetch(conn) == []
    # snapshots below the current engine version are recomputed, not refetched
    conn.execute("UPDATE snapshot SET engine_version = 0")
    assert store.needs_recompute(conn) == ["0000000001"]


def test_known_ticker_without_filings_is_not_queued(tmp_path):
    # the ticker map upserts thousands of companies with no filing date; if that
    # wrote '' instead of NULL, every one of them would queue for refetch
    conn = store.connect(tmp_path / "t.db")
    for i in range(3):
        store.upsert_company(conn, f"000000000{i}", f"T{i}", f"Co {i}")  # no last_filing
        store.upsert_company(conn, f"000000000{i}", f"T{i}", f"Co {i}")  # seen again
    assert conn.execute(
        "SELECT COUNT(*) FROM company WHERE last_filing IS NOT NULL").fetchone()[0] == 0
    assert store.needs_refetch(conn) == []
    # only a company that actually filed is queued
    store.upsert_company(conn, "0000000001", "T1", "Co 1", last_filing="2026-08-12")
    assert store.needs_refetch(conn) == ["0000000001"]


def test_upsert_keeps_newest_filing_date(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0000000002", "A", "A Co", last_filing="2026-08-05")
    store.upsert_company(conn, "0000000002", None, None, last_filing="2026-07-01")
    row_ = conn.execute("SELECT last_filing, ticker FROM company").fetchone()
    assert row_["last_filing"] == "2026-08-05"  # older filing must not overwrite
    assert row_["ticker"] == "A"                # nor blank the ticker


def test_dormant_filer_gets_no_pe_or_ptbv():
    """A live price against decade-old figures is a confident, meaningless number."""
    r = row(ttm=2.42, tbvps=30.0)
    r.update(earnings_asof="2010-12-31", balance_sheet_date="2010-12-31",
             price_asof="2026-08-14T20:00:00+00:00")
    out = apply_price(r, price=40.0)
    c = {x["n"]: x for x in out["criteria"]}
    assert c[1]["status"] == "INSUFFICIENT_DATA" and c[1]["value"] is None
    assert c[7]["status"] == "INSUFFICIENT_DATA" and c[7]["value"] is None
    assert "stopped filing" in c[1]["note"]
    assert out["verdict"] == "INDETERMINATE"


def test_recent_filer_still_priced_normally():
    r = row(ttm=5.0, tbvps=40.0)
    r.update(earnings_asof="2026-06-30", balance_sheet_date="2026-06-30",
             price_asof="2026-08-14T20:00:00+00:00")
    out = apply_price(r, price=40.0)
    c = {x["n"]: x for x in out["criteria"]}
    assert c[1]["status"] == "PASS" and c[1]["value"] == 8.0
    assert c[7]["status"] == "PASS"


def test_annual_only_filer_within_the_lag_is_not_penalised():
    # a 10-K-only filer legitimately lags around 15 months before the next one lands
    r = row(ttm=5.0, tbvps=40.0)
    r.update(earnings_asof="2025-06-30", balance_sheet_date="2025-06-30",
             price_asof="2026-08-14T20:00:00+00:00")
    out = apply_price(r, price=40.0)
    assert {x["n"]: x for x in out["criteria"]}[1]["status"] == "PASS"


def test_missing_table_is_created_on_an_existing_database(tmp_path):
    """A release that adds a table must not require deleting the database."""
    db = tmp_path / "t.db"
    conn = store.connect(db)
    conn.execute("DROP TABLE tracked")   # a database made before the feature existed
    conn.commit()
    conn.close()
    conn = store.connect(db)             # reopening must restore it
    assert store.tracked(conn) == []


def test_track_and_untrack(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0000000001", "GHC", "Graham Holdings Co")
    store.track(conn, "0000000001")
    assert [r["ticker"] for r in store.tracked(conn)] == ["GHC"]
    store.track(conn, "0000000001", note="watch the education segment")
    assert store.tracked(conn)[0]["note"] == "watch the education segment"
    assert len(store.tracked(conn)) == 1                 # tracking twice is not a duplicate
    assert store.untrack(conn, "0000000001") is True
    assert store.tracked(conn) == []
    assert store.untrack(conn, "0000000001") is False    # already gone


def test_median_pe_excludes_loss_makers_and_discloses_counts():
    from screener.sync import _median_pe
    rows = [
        {"price": 100.0, "ttm_eps": 10.0},   # P/E 10
        {"price": 100.0, "ttm_eps": 5.0},    # P/E 20
        {"price": 100.0, "ttm_eps": 2.0},    # P/E 50
        {"price": 100.0, "ttm_eps": -3.0},   # loss — no P/E
        {"price": None, "ttm_eps": 4.0},     # unpriced — no P/E
    ]
    stats = _median_pe(rows)
    assert stats == {"median_pe": 20.0, "n": 3, "members": 5}
    assert _median_pe([{"price": None, "ttm_eps": None}]) is None
    # even count averages the middle pair
    assert _median_pe(rows[:2])["median_pe"] == 15.0


def test_sp500_parser_reads_only_the_constituents_table():
    from screener.sources.indexes import parse_sp500_ciks
    cell = "<tr><td>MMM</td><td>0000{i:06d}</td></tr>"
    rows = "".join(cell.format(i=i) for i in range(1, 502))
    html = f'<table>>9999999999<</table><table id="constituents">{rows}</table>'
    ciks = parse_sp500_ciks(html)
    assert len(ciks) == 501 and "0000000001" in ciks and "9999999999" not in ciks
    # a broken layout must return None, never a half-parsed index
    assert parse_sp500_ciks("<p>no table</p>") is None
    assert parse_sp500_ciks('<table id="constituents"><td>0000000001</td></table>') is None


def test_index_history_medians_returns_and_year_end_pe():
    from datetime import date
    from screener.sync import _index_history
    closes = {
        # doubles every year: Dec closes 10, 20, 40; live price 60 mid-2024
        "A": [(date(2021, 12, 27), 10.0), (date(2022, 12, 26), 20.0),
              (date(2023, 12, 25), 40.0), (date(2024, 6, 3), 55.0)],
        # flat at 100
        "B": [(date(2021, 12, 27), 100.0), (date(2022, 12, 26), 100.0),
              (date(2023, 12, 25), 100.0), (date(2024, 6, 3), 100.0)],
    }
    rows = [
        {"cik": "A", "price": 60.0, "annual_eps": {"2021": 1.0, "2022": 2.0, "2023": -1.0}},
        {"cik": "B", "price": 100.0, "annual_eps": {"2021": 10.0, "2022": 5.0, "2023": 4.0}},
    ]
    hist = {h["year"]: h for h in _index_history(rows, closes)}
    y22, y23, y24 = hist[2022], hist[2023], hist[2024]
    assert y22["ret"] == 50.0 and y22["ret_n"] == 2          # median of +100% and 0%
    assert y22["pe"] == 15.0 and y22["pe_n"] == 2            # median of 20/2 and 100/5
    assert y23["pe"] == 25.0 and y23["pe_n"] == 1            # A's loss year excluded
    assert y24["ytd"] and y24["ret"] == 25.0                 # to live quote: +50% and 0%
    assert y24["pe"] is None                                 # no December close yet
    assert 2021 in hist and hist[2021]["ret"] is None        # no 2020 base in a 5y series
