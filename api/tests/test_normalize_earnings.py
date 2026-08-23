"""What the company earned and sold: the per-share chains, the annual
series behind them, and the trailing windows."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot
from helpers import *  # noqa: F403 — the shared fixtures, by design
from helpers import EPS, GAAP, build, dur, facts_doc, inst, tagdata, texts
from helpers import _dimensioned, _reported, _shares, _years, _yr  # underscored, so `import *` skips them


def test_filer_that_moved_to_domestic_forms_keeps_foreign_history():
    """Old 20-F facts stay readable once the newest financial filing is domestic."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        {**EPS[0], "form": "20-F"},  # FY2021 filed 2022 on the pre-transition form
        *EPS[1:],
    ])
    s = build(gaap)
    assert s.annual_eps[2021].provenance.form == "20-F"
    assert float(s.annual_eps[2021].value) == 3.0


def test_annual_eps_from_10k_only_latest_filed_wins():
    s = build()
    assert {y: float(f.value) for y, f in s.annual_eps.items()} == {
        2021: 3.0, 2022: 3.5, 2023: 4.1, 2024: 5.0, 2025: 6.0,
    }
    # restated FY2023 traces to the later filing
    assert s.annual_eps[2023].provenance.accession == "k24"
    # quarterly facts are never promoted to annual figures
    assert 2026 not in s.annual_eps


def test_ttm_is_annual_plus_ytd_delta():
    s = build()
    assert s.ttm_eps == Decimal("6.0") + Decimal("1.6") - Decimal("1.4")
    assert len(s.ttm_eps_inputs) == 3
    forms = [f.provenance.form for f in s.ttm_eps_inputs]
    assert forms == ["10-K", "10-Q", "10-Q"]


def test_ttm_falls_back_to_annual_when_no_newer_quarter():
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", EPS[:6])  # 10-K facts only
    s = build(gaap)
    assert s.ttm_eps == Decimal("6.0")
    assert len(s.ttm_eps_inputs) == 1


def test_basic_eps_fills_year_diluted_chain_lacks():
    # Lennar FY2025 pattern: the newest 10-K tags only EarningsPerShareBasic.
    # Without the fill the series freezes a year back and stales criteria 4/6 + TTM.
    diluted = [dur(f"{y}-01-01", f"{y}-12-31", 14.31, accn=f"d{y}", filed=f"{y + 1}-01-26")
               for y in range(2020, 2025)]
    basic = diluted + [dur("2025-01-01", "2025-12-31", 7.98, accn="b25", filed="2026-01-28")]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", diluted)
    gaap["EarningsPerShareBasic"] = tagdata("USD/shares", basic)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    assert float(s.annual_eps[2025].value) == 7.98
    assert "basic" in s.annual_eps[2025].provenance.concept
    # years the diluted chain covers keep their diluted values
    assert "basic" not in s.annual_eps[2024].provenance.concept


def test_current_continuing_series_beats_longer_dead_plain_series():
    # FCX pattern: EarningsPerShareDiluted stopped in 2021 (15 years of history),
    # continuing-ops runs through 2025 with fewer years — recency must win
    plain = [dur(f"{y}-01-01", f"{y}-12-31", 1.0, accn=f"p{y}", filed=f"{y + 1}-02-15")
             for y in range(2007, 2022)]
    cont = [dur(f"{y}-01-01", f"{y}-12-31", 2.0, accn=f"c{y}", filed=f"{y + 1}-02-15")
            for y in range(2013, 2026)]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", plain)
    gaap["IncomeLossFromContinuingOperationsPerDilutedShare"] = tagdata("USD/shares", cont)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    assert "ContinuingOperations" in s.annual_eps[2025].provenance.tag


def test_stale_continuing_ops_series_not_preferred():
    cont = [dur(f"{y}-01-01", f"{y}-12-31", 1.0, accn=f"c{y}", filed=f"{y + 1}-02-15")
            for y in (2015, 2016, 2017, 2018, 2019)]
    gaap = dict(GAAP)
    gaap["IncomeLossFromContinuingOperationsPerDilutedShare"] = tagdata("USD/shares", cont)
    s = build(gaap)
    assert max(s.annual_eps) == 2025  # current diluted series wins over stale continuing-ops


def test_overlapping_period_never_invents_a_later_year():
    # A fiscal-year change leaves two annual periods overlapping in the same year.
    # Pushing the second one to the next label invents a year that has not happened;
    # the framed period wins and the overlap is dropped instead.
    eps = [
        {**dur("2021-07-01", "2022-06-30", -1.0, accn="k22a", filed="2022-09-15"),
         "frame": "CY2022"},
        dur("2021-10-01", "2022-09-30", 2.0, accn="k22b", filed="2023-01-15"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2022]
    assert float(s.annual_eps[2022].value) == -1.0  # SEC's own label is authoritative


def test_label_never_lands_after_the_year_the_period_ends_in():
    # Tyson pattern: many old unframed years ahead of a few framed recent ones.
    # Inference used to cascade forward and label a Sept-2025 year as FY2027.
    eps = [dur(f"{y}-10-01", f"{y + 1}-09-28", 1.0 + y % 3, accn=f"k{y}",
               filed=f"{y + 1}-11-15") for y in range(2010, 2023)]
    eps.append({**dur("2024-09-29", "2025-09-27", 1.33, accn="k25", filed="2025-11-14"),
                "frame": "CY2025"})
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert max(s.annual_eps) == 2025
    for fy, fact in s.annual_eps.items():
        end_year = fact.provenance.period_end.year
        assert end_year - 1 <= fy <= end_year, f"FY{fy} labels a period ending {end_year}"


def test_frame_field_labels_comparative_only_years():
    # RDDT-style: pre-IPO 2022 exists only as a comparative (fy overshoots to 2024)
    # but SEC's frame field still labels it CY2022
    eps = [
        {**dur("2022-01-01", "2022-12-31", 1.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2022"},
        {**dur("2023-01-01", "2023-12-31", 2.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2023"},
        {**dur("2024-01-01", "2024-12-31", 3.0, accn="k24", filed="2025-02-15"),
         "fy": 2024, "frame": "CY2024"},
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2022, 2023, 2024]


def test_frameless_end_filled_from_nearest_framed_neighbor():
    eps = [
        {**dur("2022-01-01", "2022-12-31", 1.0, accn="k22", filed="2023-02-15"), "fy": 2022},
        {**dur("2023-01-01", "2023-12-31", 2.0, accn="k23", filed="2024-02-15"),
         "fy": 2023, "frame": "CY2023"},
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    assert sorted(build(gaap).annual_eps) == [2022, 2023]


def test_retail_fiscal_years_use_filers_own_fy_labels():
    # Target-style calendar: year end floats across the Jan/Feb boundary. A pure
    # calendar heuristic mislabels the Feb-ending years; the fy field must win.
    def kdur(start, end, val, fy, filed):
        return {**dur(start, end, val, accn=f"k{fy}", filed=filed), "fy": fy}

    eps = [
        kdur("2021-01-31", "2022-01-29", 2.0, 2021, "2022-03-09"),
        kdur("2022-01-30", "2023-01-28", 2.5, 2022, "2023-03-08"),
        kdur("2023-01-29", "2024-02-03", 3.0, 2023, "2024-03-13"),  # 53-week, ends in Feb
        kdur("2024-02-04", "2025-02-01", 3.5, 2024, "2025-03-12"),  # ends in Feb
        kdur("2025-02-02", "2026-01-31", 4.0, 2025, "2026-03-11"),
        # FY2023 comparative inside the FY2025 10-K: fy overshoots -> min() must keep 2023
        kdur("2023-01-29", "2024-02-03", 3.1, 2025, "2026-03-11"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert sorted(s.annual_eps) == [2021, 2022, 2023, 2024, 2025]
    assert float(s.annual_eps[2023].value) == 3.1  # restated value, original label


def test_ttm_refuses_to_mix_pre_and_post_ipo_share_counts():
    """A per-share figure struck on 50M shares cannot be subtracted from one struck
    on 283M. Caris Life Sciences produced +9.58 that way, out of three loss years."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", -3.22, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", 0.0, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -12.80, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-06-30", 283e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 50e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("-3.22"), "must fall back to the audited annual figure"
    assert len(s.ttm_eps_inputs) == 1


def test_ttm_composite_survives_ordinary_buybacks():
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 6.0, accn="k25", filed="2026-02-20"),
        dur("2026-01-01", "2026-06-30", 3.4, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 3.0, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2026-01-01", "2026-06-30", 94e6, form="10-Q", accn="q126", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 100e6, form="10-Q", accn="q126", filed="2026-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("6.4"), "a 6% buyback is normal and must not block the composite"
    assert len(s.ttm_eps_inputs) == 3


def test_net_income_follows_a_tag_switch_forward():
    """Advanced Energy stopped tagging NetIncomeLoss after 2024 and continued under
    ProfitLoss. Taking the first tag that returns anything freezes the series."""
    old = [dur(f"{y}-01-01", f"{y}-12-31", 50e6, accn=f"k{y}", filed=f"{y + 1}-02-18")
           for y in range(2018, 2025)]
    new = [dur(f"{y}-01-01", f"{y}-12-31", 60e6, accn=f"p{y}", filed=f"{y + 1}-02-18")
           for y in range(2020, 2026)]
    gaap = dict(GAAP)
    gaap["NetIncomeLoss"] = tagdata("USD", old)
    gaap["ProfitLoss"] = tagdata("USD", new)
    s = build(gaap)
    assert max(s.annual_net_income) == 2025, "must follow the series that is still current"
    assert 2018 in s.annual_net_income, "older years from the dropped tag are kept"


def test_depreciation_series_survives_a_tag_change_midway():
    """A filer that drops the combined tag keeps reporting the parts; the series must
    follow rather than freeze at the year of the change."""
    gaap = {k: v for k, v in OE_GAAP.items() if k != "DepreciationDepletionAndAmortization"}
    gaap["DepreciationDepletionAndAmortization"] = tagdata("USD", [
        dur("2021-01-01", "2021-12-31", 5e9, accn="k21", filed="2022-02-15")])
    gaap["Depreciation"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 9e9, accn="k25", filed="2026-02-15")])
    gaap["AmortizationOfIntangibleAssets"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 3e9, accn="k25", filed="2026-02-15")])
    oe = build(gaap).owner_earnings
    assert oe.fiscal_year == 2025          # not 2021, where the combined tag stopped
    assert float(oe.owner_earnings) == 80e9  # 100 + (9+3) - 20 - 12


def test_non_december_filer_keeps_its_own_fiscal_year_label():
    """Dorian LPG pattern: SEC frames a March-ending year by the calendar year it
    mostly falls in, one behind the fiscal year the filer reports. Honouring the frame
    shifted EPS a year against net income — which carries no frames at all — and the
    two series stopped describing the same period."""
    def mar(y, val, filed, frame=None):
        e = dur(f"{y - 1}-04-01", f"{y}-03-31", val, accn=f"k{y}", filed=filed)
        return {**e, "fy": y, **({"frame": f"CY{y - 1}"} if frame else {})}

    eps = [mar(2024, 7.6, "2024-05-29", frame=True),
           mar(2025, 2.14, "2025-05-29", frame=True),
           mar(2026, 4.54, "2026-05-27", frame=True)]
    ni = [mar(2024, 307e6, "2024-05-29"),   # net income is framed by nobody
          mar(2025, 90e6, "2025-05-29"),
          mar(2026, 193e6, "2026-05-27")]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    gaap["NetIncomeLoss"] = tagdata("USD", ni)
    s = build(gaap)
    assert sorted(s.annual_eps)[-3:] == [2024, 2025, 2026]
    # the pair must describe one period: implied share count stays put across years
    for y in (2024, 2025, 2026):
        implied = float(s.annual_net_income[y].value) / float(s.annual_eps[y].value)
        assert 38e6 < implied < 46e6, f"FY{y} implies {implied:,.0f} shares"


def test_split_rebases_years_the_filer_never_restated():
    """Chipotle pattern. A 50:1 split restates only the comparatives the newest 10-K
    carries; older years keep a figure struck on a share count that no longer exists,
    and criterion 6 compares straight across that discontinuity."""
    eps = [
        _yr(2020, 12.52, "2021-02-10", "k20"),
        _yr(2021, 22.90, "2022-02-11", "k21"),
        _yr(2022, 32.04, "2023-02-09", "k22"),      # as filed, pre-split
        _yr(2022, 0.64, "2025-02-05", "k24"),       # restated in the post-split 10-K
        _yr(2023, 0.89, "2025-02-05", "k24"),
        _yr(2024, 1.11, "2025-02-05", "k24"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2020].value), 4) == 0.2504   # 12.52 / 50
    assert round(float(s.annual_eps[2021].value), 4) == 0.458
    assert float(s.annual_eps[2024].value) == 1.11               # already post-split


def test_one_split_restated_across_two_filings_is_counted_once():
    """Booking Holdings pattern: successive 10-Qs each restate a different period onto
    the same new basis. Treating those as separate events squared 25:1 into 625."""
    eps = [
        _yr(2023, 100.0, "2024-02-01", "k23"),
        _yr(2024, 120.0, "2025-02-01", "k24"),
        dur("2025-01-01", "2025-06-30", 37.38, form="10-Q", accn="q225", filed="2025-08-01"),
        dur("2025-01-01", "2025-06-30", 1.4952, form="10-Q", accn="q226", filed="2026-08-01"),
        dur("2025-01-01", "2025-03-31", 20.0, form="10-Q", accn="q125", filed="2025-05-01"),
        dur("2025-01-01", "2025-03-31", 0.80, form="10-Q", accn="q126", filed="2026-05-01"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2023].value), 4) == 4.0      # 100 / 25, not / 625
    assert round(float(s.annual_eps[2024].value), 4) == 4.8


def test_two_genuine_splits_a_year_apart_both_apply():
    """Texas Pacific Land split 3:1 twice. Collapsing them would leave the oldest years
    understated by a factor of three."""
    eps = [
        _yr(2021, 90.0, "2022-02-01", "k21"),
        _yr(2022, 57.77, "2023-02-01", "k22"),
        _yr(2022, 19.26, "2025-02-01", "k24"),      # first 3:1
        _yr(2023, 17.59, "2025-02-01", "k24"),
        _yr(2023, 5.86, "2026-02-01", "k25"),       # second 3:1
        _yr(2024, 6.57, "2026-02-01", "k25"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2021].value), 2) == 10.0     # 90 / 9
    assert round(float(s.annual_eps[2024].value), 2) == 6.57


def test_a_quarter_and_a_year_to_date_closing_together_are_not_a_split():
    """Both end on the same day and differ threefold by length alone; comparing them
    across periods rather than within one would read a 3:1 split that never happened."""
    eps = [
        _yr(2024, 4.0, "2025-02-01", "k24"),
        _yr(2025, 5.0, "2026-02-01", "k25"),
        dur("2026-07-01", "2026-09-30", 1.0, form="10-Q", accn="q326", filed="2026-11-01"),
        dur("2026-01-01", "2026-09-30", 3.0, form="10-Q", accn="q326", filed="2026-11-01"),
        dur("2025-01-01", "2025-09-30", 2.7, form="10-Q", accn="q325", filed="2025-11-01"),
    ]
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert float(s.annual_eps[2024].value) == 4.0    # untouched
    assert s.ttm_eps == Decimal("5.0") + Decimal("3.0") - Decimal("2.7")


def test_quarters_dwarfing_their_own_year_are_refused():
    """Taboola tags 220.00 and -40.00 a share in quarters of a year that earned 0.13,
    giving a trailing 260.13 and a price/earnings of 0.02. No corporate action explains
    it, so the audited year stands rather than the composite."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 0.13, accn="k25", filed="2026-02-15"),
        dur("2026-01-01", "2026-06-30", 220.0, form="10-Q", accn="q226", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", -40.0, form="10-Q", accn="q225", filed="2025-08-05"),
    ])
    s = build(gaap)
    assert float(s.ttm_eps) == 0.13
    assert len(s.ttm_eps_inputs) == 1


def test_a_real_recovery_off_a_small_base_still_composes():
    """The absolute bound exists so the ratio test cannot veto a genuine turnaround."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 0.05, accn="k25", filed="2026-02-15"),
        dur("2026-01-01", "2026-06-30", 2.10, form="10-Q", accn="q226", filed="2026-08-05"),
        dur("2025-01-01", "2025-06-30", 0.10, form="10-Q", accn="q225", filed="2025-08-05"),
    ])
    s = build(gaap)
    assert s.ttm_eps == Decimal("0.05") + Decimal("2.10") - Decimal("0.10")


def test_a_dollar_total_tagged_as_earnings_per_share_is_discarded():
    """GRUSF files 243,446,152 into EarningsPerShareDiluted — its net income, not a
    per-share figure. Carried through, a price divided by it passes criterion 1 on a
    price/earnings of nearly zero."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        dur("2024-01-01", "2024-12-31", 209441723.0, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 243446152.0, accn="k25", filed="2026-02-15"),
    ])
    s = build(gaap)
    assert s.annual_eps == {}
    assert s.ttm_eps is None


def test_vintage_ttm_sees_only_what_was_filed():
    from screener.normalize import vintage_ttm_eps
    v = {d: float(x) for d, x in vintage_ttm_eps(GAAP).items()}
    # end of 2025: FY2025's 10-K (filed Feb 2026) is future knowledge; the newest
    # filed figure is FY2024, and Q1'25 has no prior-year comparative to roll with
    assert v["2025-12-31"] == 5.0
    # end of 2024: FY2023 stands at its ORIGINAL 4.0 — the 4.1 restatement was
    # filed in 2025 and must be invisible a year earlier
    assert v["2024-12-31"] == 4.0
    assert v["2022-12-31"] == 3.0   # only the FY2021 10-K existed then
    assert "2021-12-31" not in v    # nothing at all was filed yet


def test_revenue_series_survives_the_asc606_tag_switch():
    gaap = dict(GAAP)
    gaap["SalesRevenueNet"] = tagdata("USD", REVENUE)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", REVENUE_606)
    s = build(gaap)
    assert {y: f.value for y, f in s.annual_revenue.items()} == {
        2021: 140e9, 2022: 150e9, 2023: 160e9, 2024: 180e9, 2025: 200e9,
    }
    # TTM = FY2025 + Q1'26 - Q1'25
    assert s.ttm_revenue == Decimal("2.2E+11")


def test_no_revenue_tags_leaves_revenue_empty():
    s = build()
    assert s.annual_revenue == {} and s.ttm_revenue is None


def test_operating_income_annual_series():
    gaap = dict(GAAP)
    gaap["OperatingIncomeLoss"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 30e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 35e9, accn="k25", filed="2026-02-15"),
    ])
    s = build(gaap)
    assert {y: f.value for y, f in s.annual_operating_income.items()} == {
        2024: 30e9, 2025: 35e9,
    }


def test_revenue_fill_rejects_a_different_scope():
    """ConAgra pattern: umbrella `Revenues` carries a $1.6B sub-scope while the
    goods element holds the true $13B history — the small series must not fill."""
    gaap = dict(GAAP)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 12e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 12.5e9, accn="k25", filed="2026-02-15"),
    ])
    gaap["SalesRevenueGoodsNet"] = tagdata("USD", [
        dur("2022-01-01", "2022-12-31", 13e9, accn="k22", filed="2023-02-15"),
        dur("2023-01-01", "2023-12-31", 11e9, accn="k23", filed="2024-02-15"),
    ])
    gaap["Revenues"] = tagdata("USD", [   # wrong scope, an order of magnitude off
        dur("2022-01-01", "2022-12-31", 1.6e9, accn="k22", filed="2023-02-15"),
        dur("2021-01-01", "2021-12-31", 1.5e9, accn="k21", filed="2022-02-15"),
    ])
    s = build(gaap)
    got = {y: f.value for y, f in s.annual_revenue.items()}
    # goods element joins via the continuous 2023 boundary, then extends to 2022;
    # the umbrella's 1.6B is 8x off its neighbour and 2021 never gets a foothold
    assert got == {2022: 13e9, 2023: 11e9, 2024: 12e9, 2025: 12.5e9}


def test_revenue_fill_refuses_a_disconnected_island():
    gaap = dict(GAAP)
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15"),
    ])
    gaap["SalesRevenueNet"] = tagdata("USD", [   # ends three years before the winner starts
        dur("2020-01-01", "2020-12-31", 11e9, accn="k20", filed="2021-02-15"),
    ])
    s = build(gaap)
    # no adjacent year to prove the scopes match, so the island stays out
    assert sorted(s.annual_revenue) == [2025]


def test_da_part_sum_keeps_amortization_only_years_and_names_both_tags():
    gaap = {k: v for k, v in OE_GAAP.items() if k != "DepreciationDepletionAndAmortization"}
    gaap["Depreciation"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 9e9, accn="k25", filed="2026-02-15")])
    gaap["AmortizationOfIntangibleAssets"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 2e9, accn="k24", filed="2025-02-15"),  # amortization-only year
        dur("2025-01-01", "2025-12-31", 3e9, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    oe = s.owner_earnings
    # 2025 (latest shared year): 100 op + (9+3) D&A - 20 tax - 12 capex
    assert float(oe.owner_earnings) == 80e9
    da = dict(oe.components)["+ depreciation & amortisation"]
    assert float(da) == 12e9


def test_bdc_investment_income_becomes_the_revenue_series_arcc_style():
    gaap = dict(GAAP)
    gaap["GrossInvestmentIncomeOperating"] = tagdata("USD", [
        dur("2024-01-01", "2024-12-31", 2.9e9, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 3.052e9, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert float(s.annual_revenue[2025].value) == 3.052e9


def test_investment_company_per_share_element_yields_eps_bxsl_style():
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["InvestmentCompanyInvestmentIncomeLossFromOperationsPerShare"] = tagdata("USD/shares", [
        dur("2024-01-01", "2024-12-31", 3.1, accn="k24", filed="2025-02-15"),
        dur("2025-01-01", "2025-12-31", 3.4, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert float(s.annual_eps[2025].value) == 3.4


def test_eps_derived_when_no_per_share_element_exists_kkr_style():
    """KKR tags EPS only on a share-class axis, which Company Facts omits; its
    own income and share count still divide."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 2400e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 900e6, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert round(float(s.annual_eps[2025].value), 4) == round(2400 / 900, 4)
    assert "derived" in s.annual_eps[2025].provenance.concept
    assert s.annual_eps[2025].provenance.tag == (
        "us-gaap:NetIncomeLoss / us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")


def test_derived_eps_nets_preferred_dividends_first():
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 1000e6, accn="k25", filed="2026-02-15")])
    gaap["DividendsPreferredStock"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 100e6, accn="k25", filed="2026-02-15")])
    assert float(build(gaap).annual_eps[2025].value) == 9.0  # 900M to common, not 1,000M


def test_profit_loss_never_derives_eps_for_a_filer_with_minority_interest_ares_style():
    """ProfitLoss includes noncontrolling interests. Ares tags no MinorityInterest
    at all, so the equity pair is the evidence: EPS would read 2.60 against a
    genuine 3.00-odd — the false-bargain direction."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["ProfitLoss"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 465e6, accn="k25", filed="2026-02-15")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2025-01-01", "2025-12-31", 180e6, accn="k25", filed="2026-02-15")])
    gaap["StockholdersEquity"] = tagdata("USD", [inst("2026-03-31", 4025e6, accn="q126")])
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 8602e6, accn="q126")])
    assert 2025 not in build(gaap).annual_eps

    # a filer whose equity shows no minority holders keeps the derivation (co-op)
    gaap["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"] = \
        tagdata("USD", [inst("2026-03-31", 4025e6, accn="q126")])
    assert 2025 in build(gaap).annual_eps


def test_a_year_without_its_own_weighted_average_derives_nothing():
    """Measured against reported figures, the count on a report cover produced
    errors of exactly five, ten and a hundred and fifty times: a reverse split
    leaves a small current count against an old year's income, and a
    multi-class cover names one class while the income belongs to all."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2021-01-01", "2021-12-31", 1000e6, accn="k21", filed="2022-02-15")])
    gaap["CommonStockSharesOutstanding"] = tagdata("shares", [
        inst("2026-03-31", 100e6, accn="q126")])
    assert 2021 not in build(gaap).annual_eps


def test_a_reported_eps_is_never_replaced_by_a_derived_one():
    s = build()  # GAAP has EarningsPerShareDiluted for every year
    assert all("derived" not in f.provenance.concept for f in s.annual_eps.values())


def test_a_summed_figure_keeps_every_component_filing():
    gaap = dict(GAAP)
    gaap["LongTermDebtNoncurrent"] = tagdata("USD", [
        inst("2025-12-31", 30e9, form="10-K", accn="k25", filed="2026-02-15")])
    gaap["FinanceLeaseLiabilityNoncurrent"] = tagdata("USD", [inst("2026-03-31", 1e9, accn="q126")])
    parts = build(gaap).long_term_debt.provenance.components
    assert len(parts) == 2
    assert {p.accession for p in parts} == {"k25", "q126"}
    # the summary line's own date belongs to the newest part, which is exactly
    # why the parts must state their own
    assert {str(p.period_end) for p in parts} == {"2025-12-31", "2026-03-31"}


def test_a_negative_revenue_is_not_a_top_line():
    """The gold trusts tag a net investment loss as Revenues; the size test
    would otherwise read a company that sold less than nothing."""
    gaap = dict(GAAP)
    gaap["Revenues"] = tagdata("USD", [
        dur("2025-01-01", "2025-12-31", -606e6, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert 2025 not in s.annual_revenue
    assert s.ttm_revenue is None


def test_a_trailing_figure_anchored_a_decade_back_is_not_trailing():
    gaap = dict(GAAP)
    gaap["Revenues"] = tagdata("USD", [
        dur("2013-01-01", "2013-12-31", 500e6, accn="k13", filed="2014-02-15")])
    s = build(gaap)  # GAAP's balance sheet is 2026
    assert s.annual_revenue[2013] is not None   # the year itself is real history
    assert s.ttm_revenue is None                # but it is not the trailing twelve months


def test_a_lone_share_class_is_the_companys_own_figure_kkr_style():
    """KKR reports earnings per share only under ClassOfStock=CommonStock, so
    Company Facts returns nothing at all for it."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
        classed_entry("2025-01-01", "2025-12-31", 2.34, "ClassOfStock=CommonStock;")])
    s = build_snapshot("TEST", "0000000001", facts_doc(gaap), dimensioned=dim)
    assert float(s.annual_eps[2025].value) == 2.34
    assert s.annual_eps[2025].provenance.segments == "ClassOfStock=CommonStock;"


def test_a_consolidated_figure_always_outranks_a_classed_one():
    dim = dimensioned("EarningsPerShareDiluted", "USD/shares", [
        classed_entry("2025-01-01", "2025-12-31", 99.0, "ClassOfStock=CommonStock;")])
    s = build_snapshot("TEST", "0000000001", facts_doc(GAAP), dimensioned=dim)
    assert float(s.annual_eps[2025].value) == 6.0   # the undimensioned fact stands


def test_coca_colas_allowance_is_a_seventh_of_its_deferred_assets():
    """KO reserves 388M against 5,514M at 2025-12-31 — the ordinary case, and
    the counterexample that keeps the note from firing on every filer."""
    gaap = deferred_tax_gaap(
        DeferredTaxAssetsGross=[k25("2025-12-31", 5514e6)],
        DeferredTaxAssetsValuationAllowance=[k25("2025-12-31", 388e6)],
    )
    assert not any("valuation allowance" in n for n in texts(build(gaap)))


def test_a_partnership_never_divides_the_whole_groups_profit_by_its_own_units():
    """Westlake Chemical Partners consolidates an OpCo whose sponsor owns two thirds of
    it. The corporate equity pair the guard reads does not exist for a partnership: WLKP
    files PartnersCapital 253.7M inside 769.4M including the minority. FY2019 ProfitLoss
    is 332,895k against 60,981k attributable to unitholders on 34,488,058 units, and the
    10-K reports $1.77 a unit (accn 0001604665-22-000009), not the $9.65 that shipped."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["ProfitLoss"] = tagdata("USD", [
        dur("2019-01-01", "2019-12-31", 332_895_000, accn="k21", filed="2022-03-02")])
    gaap["NetIncomeLoss"] = tagdata("USD", [
        dur("2019-01-01", "2019-12-31", 60_981_000, accn="k21", filed="2022-03-02")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2019-01-01", "2019-12-31", 34_488_058, accn="k21", filed="2022-03-02")])
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", 253_713_000, accn="q126")])
    gaap["PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"] = tagdata(
        "USD", [inst("2026-03-31", 769_413_000, accn="q126")])
    eps = build(gaap).annual_eps[2019]
    assert round(float(eps.value), 2) == 1.77


def test_a_canadian_filers_earnings_are_not_read_as_dollars():
    """Enbridge, Canadian Pacific and Imperial Oil tag earnings per share only in
    CAD/shares. Taking whatever unit came first divided a New York price by a Canadian
    figure and understated every P/E by the exchange rate."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["EarningsPerShareDiluted"] = tagdata("CAD/shares", [
        dur("2025-01-01", "2025-12-31", 3.22, accn="k25", filed="2026-02-15")])
    s = build(gaap)
    assert s.annual_eps == {} and s.ttm_eps is None


def test_the_cover_names_which_share_class_the_ticker_is():
    """Hershey reports earnings per share for its Common Stock and its Class B in the
    same filing. Company Facts drops both because they are dimensioned, and the
    ambiguity rule refuses both because there are two — so its series stopped in 2014
    and criterion 4 was decided on a decade-old window. The cover of its own filing
    names the one the symbol registers: "Common Stock, one dollar par value"."""
    facts = facts_doc({k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"})
    dimensioned = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        dict(dur("2025-01-01", "2025-12-31", 4.34, accn="k25", filed="2026-02-15"),
             segments="ClassOfStock=CommonStock"),
        dict(dur("2025-01-01", "2025-12-31", 4.05, accn="k25", filed="2026-02-15"),
             segments="ClassOfStock=CommonClassB"),
    ]}}}}}
    blind = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned)
    assert 2025 not in blind.annual_eps, "two classes and no cover: the refusal must stand"

    told = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned,
                          receipt={"title": "Common Stock, one dollar par value"})
    assert float(told.annual_eps[2025].value) == 4.34

    # a cover naming a class that matches neither member changes nothing
    other = build_snapshot("HSY", "0000047111", facts, dimensioned=dimensioned,
                           receipt={"title": "Class C Capital Stock"})
    assert 2025 not in other.annual_eps


def test_a_receipt_rebases_every_per_security_figure_and_no_dollar_total():
    """One receipt represents two ordinary shares: all per-security history moves
    together, while entity income and preferred dividends remain company totals."""
    gaap = dict(GAAP)
    gaap["CommonStockDividendsPerShareDeclared"] = tagdata("USD/shares", [
        dur("2025-01-01", "2025-12-31", 1.25, accn="k25", filed="2026-02-15")])
    facts = facts_doc(gaap)
    ordinary = build_snapshot("ADR", "0000000001", facts)
    receipt = build_snapshot(
        "ADR", "0000000001", facts,
        receipt={"ratio": "2", "accn": "cover-1", "title": "ADS, each representing 2 shares"},
    )

    assert receipt.shares_outstanding.value == ordinary.shares_outstanding.value / 2
    assert receipt.ttm_eps == ordinary.ttm_eps * 2
    assert receipt.annual_eps[2025].value == ordinary.annual_eps[2025].value * 2
    assert receipt.dividend_per_share == ordinary.dividend_per_share * 2
    assert receipt.ttm_eps_vintage == {k: v * 2 for k, v in ordinary.ttm_eps_vintage.items()}
    assert [f.value for f in receipt.ttm_eps_inputs] == [
        f.value * 2 for f in ordinary.ttm_eps_inputs]
    assert receipt.ttm_net_income == ordinary.ttm_net_income
    assert receipt.ttm_preferred_dividends == ordinary.ttm_preferred_dividends


def test_fiscal_years_end_when_the_company_says_they_do():
    """Microsoft's fiscal 2026 closed 2026-06-30. Reading it as 2026-12-31 asked the
    price history for a December that has not arrived, so the newest P/E column was
    blank for 206 companies, and every older column divided a June balance sheet
    into the following December's market."""
    from screener.normalize import fiscal_year_ends
    ends = fiscal_year_ends(JUNE_FILER)
    assert ends[2025] == "2025-06-30"
    assert ends[2026] == "2026-06-30"


def test_vintage_earnings_are_cut_at_those_same_ends():
    """One helper feeds both series, so the keys cannot drift apart — and the newest
    fiscal year now HAS a figure, which is what the blank column was missing."""
    from screener.normalize import vintage_ttm_eps
    v = {d: float(x) for d, x in vintage_ttm_eps(JUNE_FILER).items()}
    assert "2026-06-30" in v          # the year the December cutoff could not reach
    # no look-ahead: the FY2026 10-K was filed in August, so a reader on 2026-06-30
    # had only the trailing four quarters through Q1 — 13.0 + 3.5 - 3.0
    assert v["2026-06-30"] == 13.5
    assert not any(d.endswith("-12-31") for d in v)


def test_an_eps_its_own_filing_contradicts_is_replaced():
    """The Eastern Company's 2022 10-K tags $1.76 against fiscal 2020 while leaving
    that year's income and share count untouched at $5,405,522 on 6,264,521 shares —
    $0.86. A per-share figure moving while the two numbers it is made of stand still
    is a mis-tag wearing a restatement's clothes, and it withheld Eastern's P/E."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2019-12-29", "2021-01-02", 0.86, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 1.76, accn="k21", filed="2022-03-17"),
        ]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2019-12-29", "2021-01-02", 5405522, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 5405522, accn="k21", filed="2022-03-17"),
        ]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2019-12-29", "2021-01-02", 6264521, accn="k20", filed="2021-03-16"),
            dur("2019-12-29", "2021-01-02", 6264521, accn="k21", filed="2022-03-17"),
        ]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2020].value) == 0.86


def test_a_real_restatement_moves_the_income_with_it_and_is_kept():
    """Gyre's fiscal 2022 went from -$8.2M on 31.5M shares to +$4.3M on 75.7M after a
    reverse merger. Both inputs moved, so the newer per-share figure supersedes the
    older one and must survive — the check only fires when they stand still."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2022-01-01", "2022-12-31", -0.26, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 0.03, accn="k23", filed="2024-03-27"),
        ]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2022-01-01", "2022-12-31", -8242000, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 4314000, accn="k23", filed="2024-03-27"),
        ]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2022-01-01", "2022-12-31", 31545723, accn="k22", filed="2023-03-30"),
            dur("2022-01-01", "2022-12-31", 75686406, accn="k23", filed="2024-03-27"),
        ]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2022].value) == 0.03


def test_a_preferred_dividend_is_not_a_contradiction():
    """Markel's fiscal 2020 EPS of $55.63 divides to $59.03 on its own net income,
    and the $47M gap is its preferred dividend — earnings per share is struck on
    income available to the common. The same abstention `_basis_conflict` makes."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2020-01-01", "2020-12-31", 55.63, accn="k20", filed="2021-02-19")]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2020-01-01", "2020-12-31", 816030000, accn="k20", filed="2021-02-19")]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2020-01-01", "2020-12-31", 13823000, accn="k20", filed="2021-02-19")]),
        "PreferredStockDividendsAndOtherAdjustments": tagdata("USD", [
            dur("2020-01-01", "2020-12-31", 47060000, accn="k20", filed="2021-02-19")]),
    }
    from screener.normalize import _annual_eps
    assert float(_annual_eps(gaap)[2020].value) == 55.63


def test_income_available_to_common_does_not_redefine_parent_profit():
    gaap = {
        "EarningsPerShareBasic": tagdata("USD/shares", [
            dur("2025-01-01", "2025-12-31", -35.71, accn="k25", filed="2026-06-15")]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2025-01-01", "2025-12-31", -6486000, accn="k25", filed="2026-06-15")]),
        "NetIncomeLossAvailableToCommonStockholdersDiluted": tagdata("USD", [
            dur("2025-01-01", "2025-12-31", -17128000, accn="k25", filed="2026-06-15")]),
        "WeightedAverageNumberOfSharesOutstandingBasic": tagdata("shares", [
            dur("2025-01-01", "2025-12-31", 479613, accn="k25", filed="2026-06-15")]),
    }

    from screener.normalize import _annual_net_income

    income = _annual_net_income(gaap)

    assert float(income[2025].value) == -6486000
    assert "NetIncomeLoss" in income[2025].provenance.tag


def test_statement_share_scale_is_reconciled_from_same_filing_arithmetic():
    """McDonald's states shares in millions but exposes 716.4 under the plain
    `shares` unit. EPS, income and count from one accession prove the multiplier."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2025-01-01", "2025-12-31", 11.95, accn="k25", filed="2026-02-24")]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2025-01-01", "2025-12-31", 8563e6, accn="k25", filed="2026-02-24")]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2025-01-01", "2025-12-31", 716.4, accn="k25", filed="2026-02-24")]),
    }
    from screener.normalize import (
        _annual_eps, _annual_net_income, _annual_share_counts, _basis_conflict,
    )
    eps, income = _annual_eps(gaap), _annual_net_income(gaap)
    counts = _annual_share_counts(gaap, {}, eps, income)

    assert counts[2025].value == Decimal("716400000.0")
    assert "scaled 1000000x" in counts[2025].provenance.concept
    assert _basis_conflict(gaap, {}, eps, income, {}, False) is None


def test_non_decimal_security_basis_mismatch_is_not_scaled_away():
    """A 13x ADR/class mismatch is not a thousands-or-millions presentation scale."""
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2025-01-01", "2025-12-31", 11.95, accn="k25", filed="2026-02-24")]),
        "NetIncomeLoss": tagdata("USD", [
            dur("2025-01-01", "2025-12-31", 8563e6, accn="k25", filed="2026-02-24")]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": tagdata("shares", [
            dur("2025-01-01", "2025-12-31", 55e6, accn="k25", filed="2026-02-24")]),
    }
    from screener.normalize import (
        _annual_eps, _annual_net_income, _annual_share_counts, _basis_conflict,
    )
    eps, income = _annual_eps(gaap), _annual_net_income(gaap)
    counts = _annual_share_counts(gaap, {}, eps, income)

    assert counts[2025].value == Decimal("55000000.0")
    assert _basis_conflict(gaap, {}, eps, income, {}, False) is not None


def test_the_parents_own_profit_outranks_a_longer_group_series():
    """Starwood Property Trust files fourteen years of NetIncomeLoss — $411.5M, what
    its printed income statement calls "Net income attributable to Starwood Property
    Trust" — beside sixteen years of ProfitLoss, the group's $443.1M including the
    minority holders. Ranking by depth let two extra years of history swap one for
    the other, and every margin and per-share figure then divided profit the
    shareholders do not own."""
    gaap = {
        "NetIncomeLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 411.5e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2012, 2026)]),
        "ProfitLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 443.1e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2010, 2026)]),
    }
    from screener.normalize import _annual_net_income
    series = _annual_net_income(gaap)
    assert float(series[2025].value) == 411.5e6
    assert "NetIncomeLoss" in series[2025].provenance.tag


def test_a_dead_parent_series_still_yields_to_a_live_group_one():
    """Advanced Energy's NetIncomeLoss stops while ProfitLoss runs on. Recency is
    still decided first: a figure of the right scope that stopped years ago is
    worse than a live one of the wrong scope, which is at least disclosed."""
    gaap = {
        "NetIncomeLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 100e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2015, 2024)]),
        "ProfitLoss": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 120e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2015, 2026)]),
    }
    from screener.normalize import _annual_net_income
    assert float(_annual_net_income(gaap)[2025].value) == 120e6


def test_revenue_takes_the_total_over_its_own_contract_component():
    """Ovintiv files $8,663M of contract revenue beside $8,908M of `Revenues`, and
    its income statement prints the second as "Total Revenues" — the difference is
    revenue that did not come from a contract with a customer."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 8663e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "Revenues": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 8908e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 8908e6


def test_and_the_other_way_round_when_the_umbrella_tag_is_the_narrow_one():
    """Ares files the reverse: $5,601M of contract revenue against a $4,756M
    `Revenues` covering less than its own statement's "Total revenues". Whichever
    element holds the bigger figure is the total; the other is a piece of it."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 5601482e3, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "Revenues": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 4755618e3, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 5601482e3


def test_sales_tax_collected_for_the_state_is_never_revenue():
    """The comparison is only ever between a total and its own part. The assessed-tax
    pair does not stand in that relation, and taking the larger of THOSE would count
    sales taxes collected for the state as the company's own revenue."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 1000e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
        "RevenueFromContractWithCustomerIncludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 1080e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 1000e6


def test_a_brokers_top_line_is_revenue_net_of_interest_expense():
    """Interactive Brokers reports $7,782M of gross interest income against $6,205M
    of revenue net of interest expense — the figure its own income statement totals
    to. The component is the larger of the two, so no comparison by size can rank
    them; the concepts do it."""
    gaap = {
        "InterestIncomeOperating": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 7782e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2018, 2026)]),
        "RevenuesNetOfInterestExpense": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 6205e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    series = _annual_revenue(gaap)
    assert float(series[2025].value) == 6205e6


def test_interest_income_still_stands_where_there_is_no_net_line():
    """A filer that reports interest income and nothing wider keeps it: the rule
    replaces a component with its own total, never with nothing."""
    gaap = {
        "InterestIncomeOperating": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 500e6, accn=f"k{y}", filed=f"{y+1}-02-15")
            for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 500e6


def test_sales_tax_cannot_be_larger_than_the_sale():
    """Thirty filers tag an assessed-tax pair no rate of tax explains — Precision
    Optics at 2.2x, SS Innovations at exactly 1000x, which is a units error wearing
    a revenue tag. The wider element is then not revenue.

    Dropping it matters beyond the choice: the sub-scope guard anchors on the
    LARGEST candidate, so one inflated element pushes every honest one below the
    threshold. Precision Optics' own $24.2M was being discarded as a scrap beside a
    $53.5M figure it never earned."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 24.246e6, accn=f"k{y}") for y in range(2020, 2026)]),
        "RevenueFromContractWithCustomerIncludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 53.492e6, accn=f"k{y}") for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 24.246e6


def test_a_real_sales_tax_leaves_the_pair_whole_and_the_chain_decides():
    """The check is a ceiling on the absurd, not a rule against the element. With a
    genuine 7% tax both elements stay, and the chain's own ordering then prefers the
    excluding one — which is right on its own terms: sales tax collected for the
    state was never the company's revenue."""
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 100e6, accn=f"k{y}") for y in range(2020, 2026)]),
        "RevenueFromContractWithCustomerIncludingAssessedTax": tagdata("USD", [
            dur(f"{y}-01-01", f"{y}-12-31", 107e6, accn=f"k{y}") for y in range(2020, 2026)]),
    }
    from screener.normalize import _annual_revenue
    assert float(_annual_revenue(gaap)[2025].value) == 100e6   # excluding the tax


def test_a_retail_year_is_labelled_the_way_its_own_filer_labels_it():
    """A year ending 2026-02-01 is fiscal 2025 to SEC's frame and 2026 to the month
    it ends in. The earnings reader used the first and the balance-sheet reader the
    second, so GameStop, Kohl's and Macy's printed the same date against two years
    and paired one year's balance sheet with another year's earnings."""
    end, prior = "2026-01-31", "2025-02-01"
    gaap = {
        "EarningsPerShareDiluted": tagdata("USD/shares", [
            dur("2025-02-02", end, 3.0, accn="k25"),
            dur("2024-02-04", prior, 2.0, accn="k24")]),
        "Assets": tagdata("USD", [
            inst(end, 5e9, form="10-K", accn="k25"),
            inst(prior, 4e9, form="10-K", accn="k24")]),
        "AssetsCurrent": tagdata("USD", [
            inst(end, 2e9, form="10-K", accn="k25"),
            inst(prior, 1.8e9, form="10-K", accn="k24")]),
    }
    from screener.normalize import fiscal_year_ends
    ends = fiscal_year_ends(gaap)
    assert ends[2025] == end and ends[2024] == prior
    # ...and one date is claimed by one year only, never by two
    assert len(set(ends.values())) == len(ends)


def test_the_balance_sheet_follows_the_earnings_labelling():
    """The whole table has to agree on which year a date is, or a column pairs a
    balance sheet with the wrong year's profit."""
    from screener.normalize import _annual_balances
    gaap = {"Assets": tagdata("USD", [inst("2026-02-01", 5e9, form="10-K", accn="k25")])}
    naive = _annual_balances(gaap, ("Assets",))
    assert 2026 in naive                                    # by the month it ends in
    aligned = _annual_balances(gaap, ("Assets",), labels={"2026-02-01": 2025})
    assert 2025 in aligned and 2026 not in aligned          # by the filer's own frame
