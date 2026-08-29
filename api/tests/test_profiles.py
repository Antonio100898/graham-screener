"""Profile alignment and displayed-precision valuation-boundary behavior."""
from decimal import Decimal

from screener.profiles import (PROFILE_FINANCIAL, PROFILE_OPERATING, PROFILE_UTILITY,
                               enrich, profile_for)
from screener.sync import apply_price


def screen_row():
    return {
        "sector": "Industrials",
        "listed": "y",
        "price": 10.0,
        "ttm_eps": 1.5,
        "tbvps": 12.0,
        "bvps": 10.0,
        "shares": 10_000_000,
        "ttm_revenue": 150_000_000,
        "current_assets": 300_000_000,
        "current_liabilities": 100_000_000,
        "long_term_debt": 100_000_000,
        "total_assets": 600_000_000,
        "total_liabilities": 250_000_000,
        "annual_eps": {"2016": 0.5, "2017": 0.6, "2018": 0.7, "2019": 0.8, "2020": 0.9, "2021": 1.0, "2022": 1.1, "2023": 1.2, "2024": 1.3, "2025": 1.4},
        "ch13": {"growth_10y": 40.0},
        "dividend_record": {"first": 2000, "streak_from": 2000, "latest": 2025},
        "criteria": [{"n": n, "status": "PASS"} for n in (1, 2, 3, 4, 5, 7)],
    }


def price_row(ttm=5.0, tbvps=10.0):
    return {
        "ttm_eps": ttm,
        "tbvps": tbvps,
        "criteria": [
            {"n": 1, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
            *[{"n": n, "status": "PASS", "value": None, "note": None} for n in (2, 3, 4, 5)],
            {"n": 7, "status": "INSUFFICIENT_DATA", "value": None, "note": "no price"},
        ],
    }


def criterion(row, number):
    return next(c for c in row["criteria"] if c["n"] == number)


def test_profile_mapping_keeps_financials_out_of_industrial_screen():
    assert profile_for("Industrials") == PROFILE_OPERATING
    assert profile_for("Utilities") == PROFILE_UTILITY
    assert profile_for("Financials") == PROFILE_FINANCIAL
    financial = enrich({**screen_row(), "sector": "Financials"})
    assert financial["alignment"]["enterprising"]["verdict"] == "OUT_OF_SCOPE"
    assert financial["alignment"]["defensive"]["verdict"] == "OUT_OF_SCOPE"


def test_operating_profile_exposes_both_alignments_and_modern_growth_label():
    result = enrich(screen_row())
    assert result["graham_profile"] == PROFILE_OPERATING
    assert result["alignment"]["enterprising"]["verdict"] == "ALIGNED"
    growth = result["alignment"]["enterprising"]["growth_modern_4fy"]
    assert growth["status"] == "PASS"
    assert growth["base_fy"] == 2021 and growth["latest_fy"] == 2025
    assert result["alignment"]["defensive"]["verdict"] == "ALIGNED"


def test_defensive_valuation_uses_displayed_two_decimal_boundary():
    row = screen_row()
    # 22.503... rounds to the displayed 22.50× and therefore passes by product policy.
    row.update({"price": 16.35, "bvps": 9.817500776008213,
                "annual_eps": {"2013": 1.00, "2014": 1.10, "2015": 1.20,
                               "2016": 1.30, "2017": 1.40, "2018": 1.50,
                               "2019": 1.60, "2020": 1.70, "2021": 1.80,
                               "2022": 1.90, "2023": 0.86, "2024": 1.68, "2025": 1.09}})
    result = enrich(row)
    assert result["alignment"]["defensive"]["tests"]["valuation"] == "PASS"

    # A product that displays as 22.51× remains a fail.
    row["price"] = 16.36
    result = enrich(row)
    assert result["alignment"]["defensive"]["tests"]["valuation"] == "FAIL"


def test_utility_uses_the_utility_financial_position_rule():
    row = screen_row()
    row.update({
        "sector": "Utilities",
        "total_assets": 100_000_000,
        "total_liabilities": 60_000_000,
        "long_term_debt": 80_000_000,  # exactly twice equity
    })
    result = enrich(row)
    assert result["graham_profile"] == PROFILE_UTILITY
    assert result["alignment"]["defensive"]["tests"]["financial_position"] == "PASS"
    assert result["alignment"]["enterprising"]["verdict"] == "OUT_OF_SCOPE"


def test_export_valuation_uses_raw_threshold_not_rounded_display_ratio():
    # 9.999 is below 10 and must pass, even though reader display rounds to 10.00.
    out = apply_price(price_row(ttm=1.0, tbvps=100.0), price=9.999)
    assert criterion(out, 1)["status"] == "PASS"
    assert criterion(out, 1)["value"] == 10.0

    # 1.204 is above 1.20 and must fail, even though reader display rounds to 1.20.
    out = apply_price(price_row(ttm=10.0, tbvps=100.0), price=120.4)
    assert criterion(out, 7)["status"] == "FAIL"
    assert criterion(out, 7)["value"] == 1.2

    # Graham's text says less than 120%; equality is not a pass.
    out = apply_price(price_row(ttm=10.0, tbvps=100.0), price=120.0)
    assert criterion(out, 7)["status"] == "FAIL"


def test_verified_non_payer_fails_defensive_dividend_record():
    # criterion 5 FAIL = verifiably pays nothing now; a 20-year uninterrupted
    # record is then impossible, whatever the historical paid years show
    row = screen_row()
    next(c for c in row["criteria"] if c["n"] == 5)["status"] = "FAIL"
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "FAIL"


def test_unknown_dividend_status_stays_incomplete_not_fail():
    row = screen_row()
    next(c for c in row["criteria"] if c["n"] == 5)["status"] = "INSUFFICIENT_DATA"
    row["dividend_record"] = None
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def young_row():
    # listed 2018: the whole public record is 8 years, complete
    row = screen_row()
    row["annual_eps"] = {"2018": 1.0, "2019": 1.1, "2020": 1.2, "2021": 1.4,
                         "2022": 1.6, "2023": 1.8, "2024": 1.9, "2025": 2.0}
    row["ch13"] = {}
    row["dividend_record"] = {"first": 2018, "streak_from": 2018, "latest": 2025, "paid_years": 8}
    row["first_filed"] = "2018-02-01"  # the company itself is young, not just its tags
    return row


def test_short_history_company_is_judged_over_its_whole_record():
    result = enrich(young_row())["alignment"]["defensive"]
    tests, windowed = result["tests"], result["windowed"]
    assert tests["stability_10y"] == "PASS"           # 8 of 8 years, no deficit
    assert tests["dividend_20y"] == "PASS"            # paid every year since listing
    # base avg3(2018-20)=1.1, recent avg3(2023-25)=1.9 -> +72.7% over 5-year
    # spacing, against the scaled (4/3)^0.5-1 = 15.5% threshold
    assert tests["growth_10y"] == "PASS"
    assert "8-year" in windowed["stability_10y"]
    assert "8-year" in windowed["dividend_20y"]
    assert "5-year spacing" in windowed["growth_10y"]


def test_windowing_never_applies_to_a_gappy_or_pre_xbrl_record():
    # same span but one missing year: dataset truncation, not a short history
    gappy = young_row()
    del gappy["annual_eps"]["2020"]
    tests = enrich(gappy)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["growth_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"

    # record starting in the XBRL phase-in years could belong to an older company
    old = young_row()
    old["annual_eps"] = {str(y): 1.0 for y in range(2010, 2017)}
    old["dividend_record"] = {"first": 2010, "streak_from": 2010, "latest": 2016, "paid_years": 7}
    tests = enrich(old)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def test_late_tag_adoption_never_counts_as_a_short_history_arcc_style():
    """ARCC's EPS record starts in 2020 because the BDC per-share element is
    young; the company has filed since 2004 — no windowed passes for it."""
    row = young_row()
    row["first_filed"] = "2004-10-08"
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"
    assert tests["growth_10y"] == "INSUFFICIENT_DATA"

    # unknown listing age is treated the same: no corroboration, no window
    row["first_filed"] = None
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["stability_10y"] == "INSUFFICIENT_DATA"


def test_filing_years_without_a_dividend_disprove_the_twenty_year_record():
    """BCC: paid every year since 2017, but its own earnings series covers
    2013-2016 with no dividend — 20 uninterrupted years is impossible, not
    merely unproven."""
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2011, 2026)}
    row["dividend_record"] = {"first": 2017, "streak_from": 2017, "latest": 2026, "paid_years": 10}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "FAIL"


def test_a_young_company_is_not_failed_for_years_it_did_not_exist():
    # listed 2018, paying since 2018: no filing year inside the window is silent
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2018, 2026)}
    row["dividend_record"] = {"first": 2018, "streak_from": 2018, "latest": 2026, "paid_years": 9}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def test_early_xbrl_tagging_gap_never_disproves_the_record():
    # only pre-2013 years are silent: dividend tagging was not yet universal
    row = screen_row()
    row["annual_eps"] = {str(y): 1.0 for y in range(2011, 2026)}
    row["dividend_record"] = {"first": 2013, "streak_from": 2013, "latest": 2026, "paid_years": 14}
    tests = enrich(row)["alignment"]["defensive"]["tests"]
    assert tests["dividend_20y"] == "INSUFFICIENT_DATA"


def taxed_row(untaxed=4, profitable=9, **over):
    row = screen_row()
    row["tax_record"] = {"window_from": 2016, "window_to": 2025, "profitable_years": profitable,
                         "untaxed_years": untaxed, "pass_through": False}
    row.update(over)
    return row


def test_profits_without_tax_carry_the_penn_central_warning():
    note = enrich(taxed_row())["context_notes"][-1]["text"]
    assert "Penn Central" in note and "4 of 9" in note


def test_a_pass_through_structure_is_explained_not_accused():
    row = taxed_row()
    row["tax_record"]["pass_through"] = True
    note = enrich(row)["context_notes"][-1]["text"]
    assert "pass-through" in note and "Penn Central" not in note

    # a REIT is a pass-through the facts alone cannot show; its industry does
    reit = taxed_row(industry="Real Estate Investment Trusts")
    assert "pass-through" in enrich(reit)["context_notes"][-1]["text"]


def test_an_ordinary_tax_record_says_nothing():
    assert enrich(taxed_row(untaxed=1))["context_notes"] == []
    assert enrich(screen_row())["context_notes"] == []


def test_a_margin_far_under_the_industry_median_is_stated():
    row = screen_row()
    row["peer_efficiency"] = {"margin": 4.2, "industry_median": 12.5, "peers": 18, "behind": True}
    note = enrich(row)["context_notes"][-1]["text"]
    assert "4.2%" in note and "12.5%" in note and "18 companies" in note


def test_a_margin_in_line_with_peers_says_nothing():
    row = screen_row()
    row["peer_efficiency"] = {"margin": 11.0, "industry_median": 12.5, "peers": 18, "behind": False}
    assert enrich(row)["context_notes"] == []


def test_a_book_value_made_entirely_of_acquisitions_is_stated():
    """NVF's balance sheet was the accounting of its own takeover."""
    row = screen_row()
    row.update(total_assets=1000, total_liabilities=700, goodwill=200, intangibles=150)
    note = enrich(row)["context_notes"][-1]["text"]
    assert "tangible book value is gone" in note

    row.update(goodwill=50, intangibles=50)      # 100 against 300 of equity
    assert not any("tangible book value is gone" in n
                   for n in enrich(row)["context_notes"] for n in [n["text"]])


# --- which half of the record produced the growth ---

def shaped_row(**ch13):
    row = screen_row()
    row["ch13"] = {"latest_fy": 2025, "avg_old": 1.0, "avg_middle": 1.0, "avg_recent": 3.0,
                   "growth_early": 0.0, "growth_5y": 200.0, "growth_10y": 200.0,
                   "max_decline": 0.0, "latest_vs_prior3": 80.0, "shape": "sprint"}
    row["ch13"].update(ch13)
    return row


def test_a_decade_carried_by_its_last_three_years_says_so():
    note = enrich(shaped_row())["context_notes"][-1]
    assert note["kind"] == "Growth is recent"
    assert "+0%" in note["text"] and "+200%" in note["text"]
    assert "FY2013–FY2015" in note["text"] and "FY2023–FY2025" in note["text"]
    assert "FY2025 alone came in +80%" in note["text"]


def test_growth_in_both_halves_reads_as_a_steady_record():
    note = enrich(shaped_row(shape="marathon", growth_early=40.0, growth_5y=45.0,
                             avg_middle=1.4, avg_recent=2.03, max_decline=6.0))["context_notes"][-1]
    assert note["kind"] == "Steady record"
    assert "no pause" in note["text"] and "worst single-year fall 6%" in note["text"]


def test_an_unclassified_record_says_nothing_about_its_shape():
    assert enrich(shaped_row(shape=None))["context_notes"] == []


# --- what the filing index proves happened ---

def evented_row(events, events_from="2018-01-01"):
    row = screen_row()
    row.update(balance_sheet_date="2026-06-30", events_from=events_from,
               filing_events=[{"filed": d, "item": i, "accn": f"a-{n}"}
                              for n, (d, i) in enumerate(events)])
    return row


def kinds(row):
    return [n["kind"] for n in enrich(row)["context_notes"]]


def test_a_withdrawn_financial_statement_is_the_loudest_event():
    note = enrich(evented_row([("2025-03-02", "4.02")]))["context_notes"][-1]
    assert note["kind"] == "Non-reliance"
    assert "2025-03-02" in note["text"] and "no longer be relied upon" in note["text"]


def test_several_events_each_get_their_own_note():
    row = evented_row([("2025-03-02", "4.02"), ("2024-09-01", "2.06"), ("2023-04-04", "1.03")])
    assert kinds(row) == ["Non-reliance", "Bankruptcy", "Material impairment"]


def test_a_transfer_of_listing_is_not_a_deficiency():
    """Item 3.01 is 'Notice of Delisting or Failure to Satisfy a Continued Listing Rule
    or Standard; Transfer of Listing'. Walmart, Palantir, Linde and Shopify all filed one
    to move exchange, and the item number cannot tell that from a company in breach."""
    assert kinds(evented_row([("2025-11-20", "3.01")])) == []


def test_an_event_older_than_the_window_is_not_reported():
    # five years back from the company's own newest balance sheet
    assert kinds(evented_row([("2020-01-04", "4.02")])) == []
    assert kinds(evented_row([("2021-08-04", "4.02")])) == ["Non-reliance"]


def test_a_truncated_index_narrows_the_window_it_claims():
    """A prolific filer's index holds only its last thousand filings."""
    row = evented_row([("2026-01-04", "4.01"), ("2024-06-04", "4.01"),
                       ("2022-06-04", "4.01")],
                      events_from="2022-05-01")
    note = enrich(row)["context_notes"][-1]
    # the scan could not see back to 2021-07-01, so the note may not claim it
    assert "since 2022-05-01" in note["text"]


def test_one_auditor_transition_reported_twice_is_not_churn():
    """T-Mobile filed item 4.01 three weeks apart for a single change, and Fastenal
    197 days apart: the committee approves the handover in one filing, the outgoing
    firm's dismissal takes effect in the next once it has finished the year in
    progress. Both are one transition."""
    assert kinds(evented_row([("2025-04-15", "4.01"), ("2025-05-06", "4.01")])) == []
    assert kinds(evented_row([("2024-07-19", "4.01"), ("2025-02-06", "4.01")])) == []
    # genuinely separate transitions are
    row = evented_row([("2022-03-15", "4.01"), ("2023-08-16", "4.01"), ("2025-08-25", "4.01")])
    note = enrich(row)["context_notes"][-1]
    assert note["kind"] == "Auditor changes" and "3 changes" in note["text"]


def test_a_company_with_no_scan_reports_no_events():
    row = screen_row()
    row["balance_sheet_date"] = "2026-06-30"
    assert enrich(row)["context_notes"] == []


def test_a_foreign_issuer_is_told_to_read_its_cover_page():
    """A depositary receipt stands for several ordinary shares, and the ratio is prose
    on the filing cover — no XBRL feed carries it. SEC codes every non-US jurisdiction
    with a digit (E9 Cayman Islands, X0 United Kingdom), which is how the row knows."""
    row = screen_row()
    row["incorporation"] = "E9|Cayman Islands"
    note = enrich(row)["context_notes"][-1]
    assert note["kind"] == "Foreign listing" and "Cayman Islands" in note["text"]
    assert "cover" in note["text"]


def test_a_bare_symbol_on_the_cover_does_not_answer_the_receipt_question():
    """AMRN's cover tags its symbol but no security title. That is not evidence
    that its statement share count and ADS price use the same basis."""
    row = screen_row()
    row.update(
        incorporation="X0|United Kingdom",
        receipt={"symbol": "AMRN", "title": "", "ratio": None, "accn": "k25"},
    )
    enriched = enrich(row)

    note = next(n for n in enriched["context_notes"] if n["kind"] == "Depositary receipt")
    assert "does not establish" in note["text"]
    assert any("depositary receipt" in gap["what"] for gap in enriched["prose_gaps"])


def test_an_unresolved_depositary_title_does_not_claim_one_to_one():
    row = screen_row()
    row["receipt"] = {
        "symbol": "ADS", "title": "American Depositary Shares", "ratio": None,
        "accn": "cover-1",
    }
    note = next(n for n in enrich(row)["context_notes"]
                if n["kind"] == "Depositary receipt")
    assert "cannot safely" in note["text"]
    assert "one class, no depositary ratio" not in note["text"]


def test_a_cover_count_and_a_statement_count_far_apart_name_both():
    """Zai Lab's cover states 88.6M receipts while its statements count 1,122.4M
    ordinary shares — the gap is the depositary ratio, and the note says so."""
    row = screen_row()
    row.update(incorporation="E9|Cayman Islands", shares=1_122_445_390, cover_shares=88_592_343)
    text = enrich(row)["context_notes"][-1]["text"]
    assert "88.6M" in text and "1,122.4M" in text and "12.7x apart" in text


def test_a_domestic_filer_gets_no_depositary_warning():
    row = screen_row()
    row["incorporation"] = "DE|DE"
    assert enrich(row)["context_notes"] == []


def test_prose_gaps_name_the_question_the_figures_and_the_filing():
    """A foreign issuer's depositary ratio is prose on the cover. The row records what
    cannot be settled, which figures it would move, and where to read it — rather than
    guessing at a ratio or silently shipping four wrong multiples."""
    row = screen_row()
    row.update(incorporation="E9|Cayman Islands", shares=1_122_445_390,
               cover_shares=88_592_343, sources={"eps": {"accn": "0001704292-26-000015"}})
    gap = enrich(row)["prose_gaps"][0]
    assert "depositary receipt" in gap["what"] and "12.7x apart" in gap["what"]
    assert "P/NCAV" in gap["affects"]
    assert gap["accn"] == "0001704292-26-000015"


def test_an_item_3_01_is_a_question_not_a_verdict():
    """The item number covers a delisting notice and a routine transfer of listing
    alike. It is no longer read as trouble; it is recorded as something to check."""
    row = screen_row()
    row.update(balance_sheet_date="2026-06-30", events_from="2021-01-01",
               filing_events=[{"filed": "2025-11-20", "item": "3.01", "accn": "a-1"}])
    gap = enrich(row)["prose_gaps"][0]
    assert "transfer of listing" in gap["what"] and gap["accn"] == "a-1"


def test_a_plain_domestic_filer_has_nothing_to_check():
    row = screen_row()
    row["incorporation"] = "DE|DE"
    assert enrich(row)["prose_gaps"] == []


def test_a_symbol_sec_no_longer_lists_is_marked_not_dropped():
    """American Electric Power still files 10-Qs while its submissions index carries no
    ticker and no exchange; Farmer Brothers filed a Form 15 in May. Both still carry a
    Yahoo price here, and a price for a security nobody can buy is the one number this
    screen must never present as ordinary — so the row says so instead of hiding it."""
    row = screen_row()
    row["listed"] = None
    gap = enrich(row)["prose_gaps"][0]
    assert "still tradable" in gap["what"] and "Form 25 or Form 15" in gap["where"]
    assert "dividend yield" in gap["affects"]


def test_a_cover_that_has_been_read_answers_the_question_instead_of_asking_it():
    """Onconova's cover says "each representing 13 Ordinary Shares". Once that is read
    the depositary gap is not a gap — the ratio has been applied to every per-share
    figure — and the note quotes the filer's own sentence so the parse can be checked."""
    row = screen_row()
    row["receipt"] = {"title": "American Depositary Shares, each representing 13 Ordinary Shares",
                      "ratio": "13", "accn": "0001628280-26-011946"}
    row["incorporation"] = "E9|Cayman Islands"
    enriched = enrich(row)
    assert enriched["prose_gaps"] == []
    note = next(n for n in enriched["context_notes"] if n["kind"] == "Depositary receipt")
    assert "each representing 13 Ordinary Shares" in note["text"]
    assert "divided by 13" in note["text"]
