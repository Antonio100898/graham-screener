"""Store and price-application tests — no network."""
import json

from screener import store
from screener.sync import apply_price, material_events


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


def test_peer_efficiency_needs_a_real_peer_group():
    from screener.sync import _mark_peer_efficiency
    def company(ticker, industry, income, revenue):
        return {"ticker": ticker, "industry": industry,
                "annual_operating_income": {"2025": income}, "annual_revenue": {"2025": revenue}}
    # a group of six: five healthy, one far behind
    rows = [company(f"P{i}", "Railroads", 30, 100) for i in range(5)]
    rows.append(company("LAGGARD", "Railroads", 10, 100))
    # a company alone in its industry has no median to be measured against
    rows.append(company("ALONE", "Zeppelins", 1, 100))
    _mark_peer_efficiency(rows)
    laggard = next(r for r in rows if r["ticker"] == "LAGGARD")
    assert laggard["peer_efficiency"]["behind"] is True
    assert laggard["peer_efficiency"]["industry_median"] == 30.0
    assert next(r for r in rows if r["ticker"] == "P0")["peer_efficiency"]["behind"] is False
    assert "peer_efficiency" not in next(r for r in rows if r["ticker"] == "ALONE")
    assert all("_margin" not in r for r in rows)


# --- what a filing index proves happened ---

def submissions(rows, extra=()):
    """A submissions index shaped like SEC's: parallel arrays, one per filing."""
    forms, dates, items, accns = zip(*rows) if rows else ((), (), (), ())
    return {"filings": {"recent": {
        "form": list(forms) + [f for f, *_ in extra],
        "filingDate": list(dates) + [d for _, d, *_ in extra],
        "items": list(items) + ["" for _ in extra],
        "accessionNumber": list(accns) + [a for *_, a in extra],
    }}}


def test_material_items_are_read_and_the_rest_ignored():
    seen, scanned_from = material_events(submissions([
        ("8-K", "2026-03-02", "4.02,9.01", "a-1"),   # non-reliance, with an exhibit
        ("8-K", "2025-11-10", "2.02,9.01", "a-2"),   # results of operations: routine
        ("8-K", "2024-06-01", "5.02", "a-3"),        # officer change: cannot be read
        ("10-K", "2026-02-15", "", "a-4"),
    ]))
    assert seen == [{"filed": "2026-03-02", "item": "4.02", "accn": "a-1"}]
    assert scanned_from == "2024-06-01"


def test_the_window_is_what_the_index_could_show():
    """Wells Fargo's thousand most recent filings reach back fourteen months. A
    scan may only claim the window its data covers."""
    _, scanned_from = material_events(submissions([("8-K", "2025-06-05", "3.01", "a-1")]))
    assert scanned_from == "2025-06-05"


def test_an_index_with_no_filings_claims_no_window():
    assert material_events({"filings": {"recent": {}}}) == ([], None)


def test_events_round_trip_and_replace_wholesale(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0000000001", "TEST", "Test Co")
    store.put_snapshot(conn, "0000000001", "ok", {"cik": "0000000001", "ticker": "TEST"})
    store.set_events(conn, "0000000001", [
        {"filed": "2026-03-02", "item": "4.02", "accn": "a-1"},
        {"filed": "2025-01-05", "item": "3.01", "accn": "a-2"},
    ], "2021-01-01")
    row_ = store.dashboard_rows(conn)[0]
    assert [e["item"] for e in row_["filing_events"]] == ["3.01", "4.02"]  # oldest first
    assert row_["events_from"] == "2021-01-01"
    # a rescan is the whole truth about its window: an amended index drops rows
    store.set_events(conn, "0000000001", [
        {"filed": "2026-03-02", "item": "4.02", "accn": "a-1"}], "2022-01-01")
    row_ = store.dashboard_rows(conn)[0]
    assert [e["item"] for e in row_["filing_events"]] == ["4.02"]
    assert row_["events_from"] == "2022-01-01"


def test_a_company_never_scanned_is_distinguishable_from_one_with_no_events(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0000000002", "NEW", "New Co")
    store.put_snapshot(conn, "0000000002", "ok", {"cik": "0000000002", "ticker": "NEW"})
    row_ = store.dashboard_rows(conn)[0]
    assert row_["filing_events"] == [] and row_["events_from"] is None


def test_the_price_pass_does_not_resurrect_a_criterion_the_engine_refused():
    """SM Energy's earnings are struck on 115.0M weighted shares while its current
    count is 237.5M. The engine withholds criterion 1 for it, and apply_price used to
    recompute the ratio from ttm_eps anyway and ship PASS."""
    r = row(ttm=5.64, tbvps=10.0)
    r["basis_conflict"] = "FY2025 earnings are struck on 115.0M weighted shares..."
    out = apply_price(r, price=30.0)
    c = {x["n"]: x for x in out["criteria"]}
    assert c[1]["status"] == "INSUFFICIENT_DATA" and c[1]["value"] is None
    assert c[7]["status"] == "INSUFFICIENT_DATA"


def test_a_yield_above_par_is_not_published():
    """29 rows shipped a yield over 100%, topping at 2,240,506%. The engine refuses
    them; the export pass was publishing them regardless."""
    r = row(ttm=5.0, tbvps=10.0)
    r["dividend_per_share"] = 1770000.0
    out = apply_price(r, price=79.0)
    c5 = {x["n"]: x for x in out["criteria"]}[5]
    assert c5["value"] is None and "not meaningful" in c5["note"]


def test_profitability_is_grahams_two_ratios_on_one_fiscal_year():
    """Chapter 13 compares companies on profit against sales and profit against book
    value. Both legs must come from the same fiscal year, and the return on book is
    withheld when the balance sheet is from a different era than the earnings —
    the defect the audit found in ROIC."""
    from decimal import Decimal
    from datetime import date
    from screener.sync import _profitability

    class Snap:
        annual_revenue = {2025: type("F", (), {"value": Decimal("100000000"),
                                               "provenance": None})()}
        annual_net_income = {2025: type("F", (), {
            "value": Decimal("12000000"),
            "provenance": type("P", (), {"period_end": date(2025, 12, 31)})()})()}
        annual_operating_income = {2025: type("F", (), {"value": Decimal("18000000"),
                                                        "provenance": None})()}
        total_assets = type("F", (), {"value": Decimal("200000000")})()
        total_liabilities = type("F", (), {"value": Decimal("140000000")})()
        preferred_stock = noncontrolling_interest = temporary_equity = None
        balance_sheet_date = date(2026, 3, 31)

    p = _profitability(Snap())
    assert p["net"] == 12.0 and p["operating"] == 18.0
    assert p["on_book"] == 20.0          # 12M on 60M of common equity

    Snap.balance_sheet_date = date(2030, 3, 31)   # five years past the earnings
    assert _profitability(Snap())["on_book"] is None


def test_a_symbol_belongs_to_the_company_sec_names_today(tmp_path):
    """ATAI rendered twice — $1.77B and $2.72B at the same price — because the
    predecessor kept the ticker after the successor took it. Atai Beckley N.V. filed
    a Form 15; AtaiBeckley Inc. files the 10-Qs. upsert_company can only add a
    ticker, never clear one, so the conflict had to be resolved explicitly."""
    conn = store.connect(tmp_path / "t.db")
    store.upsert_company(conn, "0001840904", "ATAI", "Atai Beckley N.V.")
    store.upsert_company(conn, "0002081043", "ATAI", "AtaiBeckley Inc.")
    for cik in ("0001840904", "0002081043"):
        store.put_snapshot(conn, cik, "ok", {"cik": cik, "ticker": "ATAI"})
    assert len(store.dashboard_rows(conn)) == 2          # the defect

    store.resolve_ticker_conflicts(conn, {"0002081043": ("ATAI", "AtaiBeckley Inc.")})
    rows = store.dashboard_rows(conn)
    assert [r["cik"] for r in rows] == ["0002081043"]
    # the predecessor keeps everything except the claim to the symbol
    assert conn.execute("SELECT COUNT(*) FROM snapshot WHERE cik = '0001840904'").fetchone()[0] == 1


def test_the_cover_parser_reads_the_ratio_the_data_cannot_carry():
    """dei:Security12bTitle is text under a share-class axis, so Company Facts strips it
    twice over. Filers word it three ways and label it two ways; all of them are one
    sentence naming the security the ticker prices."""
    from screener.sources import cover

    assert cover.depositary_ratio(
        "American Depositary Shares, each representing 13 Ordinary Shares") == 13
    assert cover.depositary_ratio(
        "American Depositary Shares, each representing three ordinary shares") == 3
    assert cover.depositary_ratio(
        "American Depository Shares, each representing 2,000 Ordinary Shares") == 2000
    # an ordinary class says nothing about a ratio, which is the answer for most filers
    assert cover.depositary_ratio("Common Stock, $0.25 Par Value") is None
    assert cover.depositary_ratio("1.875% Notes Due 2026") is None

    page = ("Title of each class American Depositary Shares, each representing 13 Ordinary "
            "Shares, par value $0.0001 per share Trading Symbol(s) ONC Name of each exchange")
    assert cover.securities(page) == [
        {"title": "American Depositary Shares, each representing 13 Ordinary Shares, "
                  "par value $0.0001 per share", "symbol": "ONC"}]


def test_an_award_total_says_which_kinds_it_contains():
    """A company that tags only options has said nothing about its restricted stock,
    so the total names its own basis rather than implying the other half is zero."""
    from decimal import Decimal
    from datetime import date
    from screener.sync import _equity_awards
    from screener.models import Fact, Provenance

    def fact(v):
        return Fact(value=Decimal(v), provenance=Provenance(
            concept="c", tag="t", fiscal_year=2026, form="10-K",
            accession="a", filed=date(2026, 2, 1), period_end=date(2025, 12, 31)))

    class Snap:
        options_outstanding = fact(6e6)
        rsus_outstanding = fact(3e6)
    assert _equity_awards(Snap()) == {"equity_awards": 9e6, "awards_basis": "options + RSUs"}

    class OptionsOnly:
        options_outstanding = fact(6e6)
        rsus_outstanding = None
    assert _equity_awards(OptionsOnly()) == {"equity_awards": 6e6, "awards_basis": "options only"}

    class Neither:
        options_outstanding = rsus_outstanding = None
    assert _equity_awards(Neither()) == {"equity_awards": None, "awards_basis": None}


def test_the_regression_harness_ignores_what_a_recomputation_cannot_know():
    """The harness exists because three hand-written comparison scripts were wrong
    before it — they left out the dimensioned sidecar, the cover ratio, or the
    export-time enrichment, and each reported healthy companies as broken. So the
    fields a recomputation cannot reproduce are named in one place rather than
    rediscovered every time."""
    from screener.regress import PRICE_SETTLED, VOLATILE, _flat, _moved

    assert "criteria" in PRICE_SETTLED and "n_pass" in PRICE_SETTLED
    assert "price" in VOLATILE and "ttm_eps_vintage" in VOLATILE
    # nested figures are attributed to their own field, not to the whole object
    assert _flat({"annual_eps": {"2020": 1.76}, "price": 9}) == {"annual_eps.2020": 1.76}
    # a rounded last decimal is not a change; a sign flip is
    assert not _moved(1.7600, 1.76001)
    assert _moved(0.64, -0.64)


def test_a_printed_statement_is_read_at_the_scale_its_header_declares():
    """"$ in Millions" over a cell reading 45,468 means 45.468 billion dollars.
    Reading the cell as dollars is the difference between a company and a corner
    shop, and it is the one mistake a statement reader can make silently."""
    from screener.sources import statements
    doc = """<html><body><p>CONSOLIDATED BALANCE SHEETS - USD ($) $ in Millions</p>
    <table><tr><td>Total assets</td><td>104,217</td><td>100,549</td></tr>
    <tr><td>Accumulated deficit</td><td>(1,234)</td><td>(999)</td></tr></table></body></html>"""
    assert statements.scale(doc) == 1_000_000
    lines = statements.lines(doc)
    assert statements.value_for(lines, "total assets")[1] == 104_217_000_000
    # a parenthesised cell is negative, and the comparative column is ignored
    assert statements.value_for(lines, "accumulated deficit")[1] == -1_234_000_000


def test_a_statement_is_found_by_its_printed_name_not_its_number():
    """R-numbers differ between filers and between years; the name does not. The
    parenthetical companion carries share counts, not the statement."""
    from screener.sources import statements
    summary = """<Reports>
      <Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>CONDENSED CONSOLIDATED STATEMENTS OF INCOME</ShortName></Report>
      <Report><HtmlFileName>R4.htm</HtmlFileName><ShortName>CONDENSED CONSOLIDATED BALANCE SHEETS</ShortName></Report>
      <Report><HtmlFileName>R5.htm</HtmlFileName><ShortName>CONDENSED CONSOLIDATED BALANCE SHEETS PARENTHETICAL</ShortName></Report>
    </Reports>"""
    assert statements.find(summary, "balance_sheet") == "R4.htm"
    assert statements.find(summary, "income") == "R2.htm"


def test_total_liabilities_is_not_total_liabilities_and_equity():
    """Coca-Cola prints no total-liabilities line at all. Matching that label by
    substring would take "Total Liabilities and Equity" — its total assets — and
    call the company solvent to the last dollar."""
    from screener.sources import statements
    doc = """<html><body><p>$ in Millions</p><table>
      <tr><td>Total Equity</td><td>35,734</td></tr>
      <tr><td>Total Liabilities and Equity</td><td>104,217</td></tr></table></body></html>"""
    lines = statements.lines(doc)
    assert statements.value_for(lines, "total liabilities") is None


def test_the_money_scale_is_the_one_attached_to_the_dollar_sign():
    """CoStar's income statement is headed "$ in Thousands, shares in Millions".
    A pattern that looks for the word "millions" finds the share clause and reads
    every dollar figure a thousand times too large — its $7.0M of net income
    became $7.0bn."""
    from screener.sources import statements
    header = ("<html><body><p>CONSOLIDATED STATEMENTS OF OPERATIONS - USD ($) "
              "$ in Thousands, shares in Millions</p><table>"
              "<tr><td>Net income</td><td>7,000</td></tr>"
              "<tr><td>Weighted average shares outstanding</td><td>410</td></tr>"
              "</table></body></html>")
    assert statements.scale(header) == 1_000
    lines = statements.lines(header)
    assert statements.value_for(lines, "net income")[1] == 7_000_000
    # the share row takes the share scale, not the money one
    assert statements.value_for(lines, "weighted average shares outstanding")[1] == 410_000_000


def test_the_parents_share_of_profit_wins_over_the_consolidated_line():
    """Apollo prints $5,401M of consolidated net income and $3,492M attributable to
    itself. `NetIncomeLoss` is the second, and every per-share figure divides it."""
    from screener.sources import statements
    doc = ("<html><body><p>$ in Millions</p><table>"
           "<tr><td>Net income (loss)</td><td>5,401</td></tr>"
           "<tr><td>Net income (loss) attributable to noncontrolling interests</td><td>1,909</td></tr>"
           "<tr><td>Net income (loss) attributable to Apollo Global Management, Inc.</td><td>3,492</td></tr>"
           "</table></body></html>")
    lines = statements.lines(doc)
    hit = statements.value_for(lines, "net income (loss) attributable to*", "net income (loss)")
    assert hit[1] == 3_492_000_000        # not the minority holders' 1,909


def test_a_loss_is_read_whichever_side_the_dollar_sign_falls():
    """SEC renders a negative as "$ (52)" — dollar sign outside the bracket. A
    pattern expecting "(" first skips the cell silently and reads the NEXT column
    instead, which is the prior year: Hyatt's $52M loss was read as the $1,296M
    profit it made the year before."""
    from screener.sources import statements
    doc = ("<html><body><p>$ in Millions</p><table>"
           "<tr><td>Net income (loss) attributable to Hyatt Hotels Corporation</td>"
           "<td>$ (52)</td><td>$ 1,296</td><td>$ 220</td></tr></table></body></html>")
    lines = statements.lines(doc)
    assert statements.value_for(lines, "net income (loss) attributable to*")[1] == -52_000_000
    # the later columns are still available, in the order the filer printed them
    assert lines[0][1] == [-52_000_000, 1_296_000_000, 220_000_000]


def test_a_section_heading_is_not_the_total_it_introduces():
    """An income statement opens "Revenues:" as the heading of the section that
    follows, and a heading row can carry a stray figure. Matching the bare word
    first read Robinhood's revenue as $2,628M against a $4,473M year, so every
    "total" form is tried before any bare one."""
    from screener.sources import statements
    doc = ("<html><body><p>$ in Millions</p><table>"
           "<tr><td>Revenues</td><td>2,628</td></tr>"
           "<tr><td>Other revenues</td><td>1,845</td></tr>"
           "<tr><td>Total net revenues</td><td>4,473</td></tr></table></body></html>")
    lines = statements.lines(doc)
    hit = statements.value_for(lines, "total net revenues", "total revenues", "revenues")
    assert hit[1] == 4_473_000_000


def test_the_common_stockholders_line_is_the_parents_own():
    """Cohen & Steers and Vivid Seats' Class A both name the parent's share that
    way. Excluding the phrase took the consolidated figure instead — $157.4M where
    the company earned $153.2M."""
    from screener.sources import statements
    doc = ("<html><body><p>$ in Thousands</p><table>"
           "<tr><td>Net income</td><td>157,398</td></tr>"
           "<tr><td>Net income attributable to redeemable noncontrolling interests</td><td>4,181</td></tr>"
           "<tr><td>Net income attributable to common stockholders</td><td>153,217</td></tr>"
           "</table></body></html>")
    lines = statements.lines(doc)
    # the phrase is matched explicitly and late, never by the prefix: Uniti uses the
    # same words for its figure after preferred dividends
    hit = statements.value_for(lines, "net income attributable to*",
                               "net income attributable to common stockholders",
                               "net income")
    assert hit[1] == 153_217_000       # not the minority holders' 4,181


def test_a_shareholder_is_not_a_share():
    """"Net Income to Shareholders" contains the word "share" and is money. Scaling
    it as a share count left Markel's $2.1bn of profit reading as $2,107,010, which
    is small enough to look like a plausible figure and be believed."""
    from screener.sources import statements
    doc = ("<html><body><p>Shares in Thousands, $ in Thousands</p><table>"
           "<tr><td>Net Income to Shareholders</td><td>2,107,010</td></tr>"
           "<tr><td>Weighted average shares outstanding</td><td>12,600</td></tr>"
           "</table></body></html>")
    lines = statements.lines(doc)
    assert statements.value_for(lines, "net income to shareholders")[1] == 2_107_010_000
    assert statements.value_for(lines, "weighted average shares outstanding")[1] == 12_600_000


def test_a_missing_half_of_a_derived_figure_is_not_zero():
    """Isabella Bank's combined intangibles line and its goodwill are both
    $48,282,000, so intangibles excluding goodwill are correctly 0 — and the
    goodwill for that date is carried by an earlier accession than the combined
    line. Substituting zero for the half it could not find read the whole combined
    figure as intangible and called a correct answer an error."""
    from screener.audit import _fact_in_filing
    facts = {"facts": {"us-gaap": {
        "IntangibleAssetsNetIncludingGoodwill": {"units": {"USD": [
            {"end": "2025-12-31", "val": 48282000, "accn": "q3", "filed": "2026-08-10"}]}},
        "Goodwill": {"units": {"USD": [
            {"end": "2025-12-31", "val": 48282000, "accn": "k25", "filed": "2026-02-20"}]}},
    }}}
    source = {"tag": "us-gaap:IntangibleAssetsNetIncludingGoodwill - us-gaap:Goodwill",
              "accn": "q3", "end": "2025-12-31"}
    assert _fact_in_filing(facts, source) == 0

    missing = {"tag": "us-gaap:IntangibleAssetsNetIncludingGoodwill - us-gaap:NotFiled",
               "accn": "q3", "end": "2025-12-31"}
    assert _fact_in_filing(facts, missing) is None      # unknown, never 0


def test_a_weighted_average_has_several_values_for_one_end_date():
    """A quarterly report states the three-month average, the six-month and the year
    to date, all ending on the same day, and the provenance records only the end. The
    honest question is whether the displayed figure is one of the numbers the filing
    states, not whether it is the first of them."""
    from screener.audit import _values_in_filing
    facts = {"facts": {"us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {
        "units": {"shares": [
            {"end": "2026-06-30", "val": 193323374, "accn": "q2", "start": "2026-04-01"},
            {"end": "2026-06-30", "val": 75870706, "accn": "q2", "start": "2026-01-01"},
        ]}}}}}
    found = _values_in_filing(facts, "us-gaap",
                              "WeightedAverageNumberOfDilutedSharesOutstanding",
                              {"accn": "q2", "end": "2026-06-30"})
    assert sorted(found) == [75870706, 193323374]


def test_the_parentheses_carry_the_sign_and_the_label_never_does():
    """Intellicheck heads its line "Net loss" and prints "$ 1,273" beside a prior
    year of "$ (918)" — a stale caption over a real profit, which the page's own
    arithmetic confirms: pre-tax 1,331 less tax 58 is 1,273. Reading the caption as
    a sign turned a profitable year into a loss."""
    from screener.sources import statements
    doc = ("<html><body><p>$ in Thousands</p><table>"
           "<tr><td>Net income (loss) before provision for income taxes</td>"
           "<td>1,331</td><td>(885)</td></tr>"
           "<tr><td>Provision for income taxes</td><td>58</td><td>33</td></tr>"
           "<tr><td>Net loss</td><td>$ 1,273</td><td>$ (918)</td></tr></table></body></html>")
    lines = statements.lines(doc)
    assert statements.value_for(lines, "net loss")[1] == 1_273_000
    assert statements.value_for(lines, "net loss", column=1)[1] == -918_000


def test_a_note_is_never_mistaken_for_the_statement_itself():
    """Creatd titles its income statement "Consolidated Statements of Comprehensive
    Loss", which no operations-shaped phrase matches, so the search ran on and
    reached a note eighty reports later that happened to mention operations. SEC
    marks the primary statements with MenuCategory, which settles it outright."""
    from screener.sources import statements
    summary = """<Reports>
      <Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>Consolidated Balance Sheets</ShortName><MenuCategory>Statements</MenuCategory></Report>
      <Report><HtmlFileName>R4.htm</HtmlFileName><ShortName>Consolidated Statements of Comprehensive Loss</ShortName><MenuCategory>Statements</MenuCategory></Report>
      <Report><HtmlFileName>R71.htm</HtmlFileName><ShortName>Segment Results of Operations (Details)</ShortName><MenuCategory>Details</MenuCategory></Report>
    </Reports>"""
    assert statements.find(summary, "income") == "R4.htm"
    assert statements.find(summary, "balance_sheet") == "R2.htm"


def test_a_pure_operations_statement_outranks_a_combined_one():
    """A filer publishing both keeps the income statement, not the comprehensive one:
    comprehensive income carries currency and pension movements that are not
    earnings."""
    from screener.sources import statements
    summary = """<Reports>
      <Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>Consolidated Statements of Operations</ShortName><MenuCategory>Statements</MenuCategory></Report>
      <Report><HtmlFileName>R3.htm</HtmlFileName><ShortName>Consolidated Statements of Comprehensive Income</ShortName><MenuCategory>Statements</MenuCategory></Report>
    </Reports>"""
    assert statements.find(summary, "income") == "R2.htm"
