"""Synthetic companyfacts JSON, and the handful of shapes every normaliser test
builds on. Imported rather than repeated: a fixture copied into four files is a
fixture that drifts in three of them.
"""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from screener.normalize import UnsupportedFilerError, _fy_label, build_snapshot
def _reported(end: str, weeks: int = 6) -> str:
    """A filing date that comes AFTER the period it reports on.

    The engine drops a fact dated later than the filing that carries it, which is
    right — a company cannot report a quarter before it ends. A fixture with a fixed
    default filing date silently becomes invalid the moment its period runs past
    that date, and the test then passes or fails for a reason it never states. So
    the default is derived from the period instead of pinned.
    """
    return (date.fromisoformat(end) + timedelta(weeks=weeks)).isoformat()
def dur(start, end, val, form="10-K", accn="k-0", filed=None):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form,
            "filed": filed or _reported(end), "fy": 0, "fp": "FY"}
def inst(end, val, form="10-Q", accn="q-0", filed=None):
    return {"end": end, "val": val, "accn": accn, "form": form,
            "filed": filed or _reported(end), "fy": 0, "fp": "Q1"}
def tagdata(unit, entries):
    return {"units": {unit: entries}}
def facts_doc(gaap=None, dei=None):
    return {"facts": {"us-gaap": gaap or {}, "dei": dei or {}}}
EPS = [
    dur("2021-01-01", "2021-12-31", 3.0, accn="k21", filed="2022-02-15"),
    dur("2022-01-01", "2022-12-31", 3.5, accn="k22", filed="2023-02-15"),
    dur("2023-01-01", "2023-12-31", 4.0, accn="k23", filed="2024-02-15"),
    dur("2023-01-01", "2023-12-31", 4.1, accn="k24", filed="2025-02-15"),  # restated in FY2024 10-K
    dur("2024-01-01", "2024-12-31", 5.0, accn="k24", filed="2025-02-15"),
    dur("2025-01-01", "2025-12-31", 6.0, accn="k25", filed="2026-02-15"),
    dur("2026-01-01", "2026-03-31", 1.6, form="10-Q", accn="q126", filed="2026-05-05"),
    dur("2025-01-01", "2025-03-31", 1.4, form="10-Q", accn="q125", filed="2025-05-05"),
]
GAAP = {
    "EarningsPerShareDiluted": tagdata("USD/shares", EPS),
    "AssetsCurrent": tagdata("USD", [
        inst("2025-12-31", 280e9, form="10-K", accn="k25", filed="2026-02-15"),
        inst("2026-03-31", 300e9, accn="q126"),
    ]),
    "LiabilitiesCurrent": tagdata("USD", [inst("2026-03-31", 150e9, accn="q126")]),
    "Assets": tagdata("USD", [inst("2026-03-31", 1000e9, accn="q126")]),
    "Liabilities": tagdata("USD", [inst("2026-03-31", 400e9, accn="q126")]),
    "Goodwill": tagdata("USD", [inst("2025-12-31", 50e9, form="10-K", accn="k25", filed="2026-02-15")]),
    "IntangibleAssetsNetExcludingGoodwill": tagdata("USD", [inst("2026-03-31", 30e9, accn="q126")]),
    "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 10e9, accn="q126")]),
    "PaymentsOfDividendsCommonStock": tagdata("USD", [
        dur("2026-01-01", "2026-03-31", 2e9, form="10-Q", accn="q126", filed="2026-05-05"),
    ]),
}
def texts(snapshot):
    """Disclosure notes carry their kind now; the wording is what tests read."""
    return [n["text"] for n in snapshot.context_notes]
def build(gaap=GAAP):
    return build_snapshot("TEST", "0000000001", facts_doc(gaap))
OE_GAAP = {
    **GAAP,
    "NetIncomeLoss": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 70e9, accn="k25", filed="2026-02-15")]),
    "OperatingIncomeLoss": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 100e9, accn="k25", filed="2026-02-15")]),
    "DepreciationDepletionAndAmortization": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15")]),
    "IncomeTaxExpenseBenefit": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 20e9, accn="k25", filed="2026-02-15")]),
    "PaymentsToAcquirePropertyPlantAndEquipment": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 12e9, accn="k25", filed="2026-02-15")]),
    "NetCashProvidedByUsedInOperatingActivities": tagdata("USD", [
        dur("2025-01-01", "2025-12-31", 75e9, accn="k25", filed="2026-02-15")]),
    "CashAndCashEquivalentsAtCarryingValue": tagdata("USD", [
        inst("2026-03-31", 40e9, accn="q126")]),
}
def _yr(y, val, filed, accn):
    return dur(f"{y}-01-01", f"{y}-12-31", val, accn=accn, filed=filed)
REVENUE = [
    # pre-606 element carries the old years, ending right where the new one begins
    dur("2021-01-01", "2021-12-31", 140e9, accn="k21", filed="2022-02-15"),
    dur("2022-01-01", "2022-12-31", 150e9, accn="k22", filed="2023-02-15"),
    dur("2023-01-01", "2023-12-31", 160e9, accn="k23", filed="2024-02-15"),
]
REVENUE_606 = [
    # ...and the ASC 606 element takes over without overlap
    dur("2024-01-01", "2024-12-31", 180e9, accn="k24", filed="2025-02-15"),
    dur("2025-01-01", "2025-12-31", 200e9, accn="k25", filed="2026-02-15"),
    dur("2026-01-01", "2026-03-31", 60e9, form="10-Q", accn="q126", filed="2026-05-05"),
    dur("2025-01-01", "2025-03-31", 40e9, form="10-Q", accn="q125", filed="2025-05-05"),
]
def dimensioned(tag, unit, entries):
    return {"facts": {"us-gaap": {tag: {"units": {unit: entries}}}}}
def classed_entry(start, end, val, segments, accn="k25", form="10-K", filed="2026-02-15"):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form,
            "filed": filed, "fy": 0, "fp": "FY", "segments": segments}
def _years(tag, unit, values, instant=False):
    out = []
    for year, value in values.items():
        if instant:
            out.append(inst(f"{year}-12-31", value, form="10-K", accn=f"k{year}",
                            filed=f"{year + 1}-02-15"))
        else:
            out.append(dur(f"{year}-01-01", f"{year}-12-31", value, accn=f"k{year}",
                           filed=f"{year + 1}-02-15"))
    return tagdata(unit, out)
def annual_10k(tag, values, gaap):
    """One fiscal-year duration series, as a 10-K states it."""
    gaap[tag] = tagdata("USD", [
        dur(f"{y}-01-01", f"{y}-12-31", v, accn=f"k{y}", filed=f"{y + 1}-02-15")
        for y, v in values.items()])
    return gaap
def deferred_tax_gaap(**tags):
    """Base facts with a profitable FY2025, plus whatever the footnote says."""
    gaap = dict(GAAP)
    annual_10k("NetIncomeLoss", {2024: 800e6, 2025: 1000e6}, gaap)
    for tag, entries in tags.items():
        gaap[tag] = tagdata("USD", entries)
    return gaap
def k25(end, val):
    return inst(end, val, form="10-K", accn="k25", filed="2026-02-15")
def _yr(year, val, filed, accn):
    return dur(f"{year}-01-01", f"{year}-12-31", val, accn=accn, filed=filed)
def _shares(year, val, filed, accn):
    return dur(f"{year}-01-01", f"{year}-12-31", val, accn=accn, filed=filed)
JUNE_FILER = {
    # a Microsoft-shaped calendar: fiscal 2025 closes 2025-06-30, its 10-K lands
    # in August, and fiscal 2026 closes a year later
    "EarningsPerShareDiluted": tagdata("USD/shares", [
        dur("2023-07-01", "2024-06-30", 11.0, accn="k24", filed="2024-08-01"),
        dur("2024-07-01", "2025-06-30", 13.0, accn="k25", filed="2025-08-01"),
        dur("2025-07-01", "2026-06-30", 15.0, accn="k26", filed="2026-08-01"),
        # the quarters a reader standing on 2026-06-30 could already see
        dur("2025-07-01", "2025-09-30", 3.5, form="10-Q", accn="q126", filed="2025-10-25"),
        dur("2024-07-01", "2024-09-30", 3.0, form="10-Q", accn="q125", filed="2024-10-25"),
    ]),
    "Assets": tagdata("USD", [
        inst("2024-06-30", 460e9, form="10-K", accn="k24", filed="2024-08-01"),
        inst("2025-06-30", 500e9, form="10-K", accn="k25", filed="2025-08-01"),
        inst("2026-06-30", 560e9, form="10-K", accn="k26", filed="2026-08-01"),
    ]),
}
def _dimensioned(entries):
    return {"facts": {"us-gaap": {"PreferredStockSharesOutstanding": tagdata("shares", entries)}}}
CONVERTING = dict(GAAP) | {
    "CommonStockSharesOutstanding": tagdata("shares", [inst("2026-03-31", 20e9, accn="q126")]),
    "ConvertiblePreferredStockSharesIssuedUponConversion": tagdata("shares", [
        inst("2026-03-31", 4e9, accn="q126")]),
}
