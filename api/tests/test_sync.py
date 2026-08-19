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


def test_live_price_removes_obsolete_missing_price_quote_note():
    r = row(ttm=5.0, tbvps=None)
    r["criteria"][-1]["note"] = "missing: intangibles, price quote"
    out = apply_price(r, price=40.0)
    c7 = {x["n"]: x for x in out["criteria"]}[7]
    assert c7["status"] == "INSUFFICIENT_DATA"
    assert c7["note"] == "missing: intangibles"


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


def test_index_membership_parsers():
    from screener.sources.indexes import djia_ciks, nasdaq100, sp500
    row = ('<tr><td><a href="/wiki/Comp_{i}">C{i}</a></td>'
           '<td>000000{i:04d}\n</td></tr>')
    sp_html = ('<table id="constituents">'
               + "".join(row.format(i=i) for i in range(1, 502)) + "</table>")
    sp = sp500(sp_html)
    assert len(sp) == 500 and sp["0000000002"] == "Comp_2"  # first row is the header
    # under ~480 rows means the page layout broke — refuse, never half an index
    assert sp500('<table id="constituents"><tr><td>x</td></tr></table>') is None

    cells = "".join(f'<td><a href="/wiki/Comp_{i}">Company {i}</a> ↑ </td>' for i in range(2, 32))
    dj_html = f'<table class="wikitable"><tr>{cells}</tr></table>'
    dj = djia_ciks(sp, dj_html)
    assert len(dj) == 30 and "0000000030" in dj
    # a footnote cell with extra prose must not add a 31st member
    noisy = dj_html.replace("</table>",
        '<tr><td>spun off <a href="/wiki/Comp_99">Company 99</a> in 2023</td></tr></table>')
    assert djia_ciks(sp, noisy) == dj

    def tick(i):
        return f"T{chr(65 + i // 26)}{chr(65 + i % 26)}"
    n_html = ('<table id="constituents">'
              + "".join(f'<tr><td>{tick(i)}</td><td><a href="/wiki/X">X</a></td></tr>'
                        for i in range(102)) + "</table>")
    assert len(nasdaq100(n_html)) == 101  # first row is the header


def test_row_carries_per_figure_provenance_and_series_mix():
    """Release 3b: every extracted figure names its tag and filing; a series
    stitched from two tags discloses which years came from which."""
    from tests.test_normalize import GAAP, facts_doc, tagdata, dur
    from screener.sync import _derive

    gaap = dict(GAAP)
    # EPS 2021 under a different element -> a scope switch worth disclosing
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        e for e in GAAP["EarningsPerShareDiluted"]["units"]["USD/shares"]
        if not e["start"].startswith("2021")])
    gaap["EarningsPerShareBasicAndDiluted"] = tagdata("USD/shares", [
        dur("2021-01-01", "2021-12-31", 3.0, accn="k21", filed="2022-02-15")])
    status, row = _derive("0000000001", "TEST", facts_doc(gaap))
    assert status == "ok"
    src = row["sources"]["total_assets"]
    assert src["tag"] == "us-gaap:Assets"
    assert src["form"] and src["accn"] and src["end"]
    assert row["sources"]["goodwill"]["tag"] == "us-gaap:Goodwill"
    mix = row["series_mix"]["eps"]
    assert mix["us-gaap:EarningsPerShareBasicAndDiluted"] == [2021]
    assert 2025 in mix["us-gaap:EarningsPerShareDiluted"]
