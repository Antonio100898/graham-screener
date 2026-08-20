"""Derived earnings per share against the figure the filer actually reported.

Where a company tags earnings per share only by share class, Company Facts
returns nothing and the screener divides income by a share count instead. That
stopgap is arithmetic on the company's own numbers, but it is not the company's
number: KKR's derivation reads 2.66 against a reported 2.34.

This compares the two for every company where both exist, before the reported
figure is allowed to replace the derived one anywhere. A disagreement is a
finding about the derivation, not a detail — the same denominator sits under
every multiple on the dashboard.

Run: python -m screener.dera_ab
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from .normalize import _annual_eps, _unambiguous_dimensioned
from .sources import dera

DASHBOARD = Path(__file__).parent / "static" / "dashboard.json"
CACHE = Path.home() / ".cache" / "graham-screener"
DISAGREEMENT = 0.10  # a tenth of the earnings is a tenth of every multiple


def _filed_for(row: dict, year: int):
    """When the filing behind our newest earnings figure was made. A restatement
    arrives in a later filing than the figure it replaces, which is what
    separates a corrected year from a contradicted one."""
    filed = ((row.get("sources") or {}).get("eps") or {}).get("filed")
    return date.fromisoformat(filed) if filed else None


def compare() -> dict:
    rows = json.loads(DASHBOARD.read_text())["rows"]
    both = agree = restated = 0
    findings: list[dict] = []
    gained: list[str] = []
    for row in rows:
        sidecar = dera.load_sidecar(CACHE, row["cik"])
        if not sidecar:
            continue
        classed = _unambiguous_dimensioned(sidecar)
        if not classed:
            continue
        reported = _annual_eps(classed)
        if not reported:
            continue
        derived = row.get("annual_eps") or {}
        overlap = sorted(y for y in reported if str(y) in derived)
        if not overlap:
            if reported:
                gained.append(row["ticker"])
            continue
        for year in overlap[-3:]:
            ours, theirs = derived[str(year)], float(reported[year].value)
            both += 1
            if theirs == 0:
                continue
            gap = abs(ours - theirs) / abs(theirs)
            if gap <= DISAGREEMENT:
                agree += 1
                continue
            # A reverse split restates every earlier year's earnings per share,
            # and the restatement is what today's price must be compared with.
            # When our figure comes from a later filing than theirs, the two are
            # not in conflict: ours is the newer statement of the same year.
            ours_filed = _filed_for(row, year)
            theirs_filed = reported[year].provenance.filed
            if ours_filed and theirs_filed and ours_filed > theirs_filed:
                restated += 1
                continue
            findings.append({"ticker": row["ticker"], "year": year,
                             "ours": round(ours, 4), "reported": theirs,
                             "gap": round(gap * 100, 1)})
    findings.sort(key=lambda f: -f["gap"])
    return {"compared": both, "agreed": agree, "restated": restated, "findings": findings,
            "companies_gaining_a_series": sorted(set(gained))}


def main(argv=None) -> int:
    report = compare()
    if not report["compared"]:
        print("no company has both a derived and a reported figure yet — "
              "run: python -m screener.sync dera --from 2021q1")
        return 0
    agreed, compared = report["agreed"], report["compared"]
    print(f"compared {compared} company-years where both figures exist; "
          f"{agreed} agree within {DISAGREEMENT:.0%} ({agreed / compared:.0%}); "
          f"{report['restated']} are ours restated in a later filing")
    print(f"companies with a reported series and no derived one to check: "
          f"{len(report['companies_gaining_a_series'])}")
    if report["findings"]:
        print(f"\nDISAGREEMENTS ({len(report['findings'])}), worst first — "
              "the reported figure is the company's own:")
        for f in report["findings"][:30]:
            print(f"  {f['ticker']:6s} FY{f['year']}  derived {f['ours']:>9.4f}  "
                  f"reported {f['reported']:>9.4f}  off by {f['gap']}%")
        if len(report["findings"]) > 30:
            print(f"  ... and {len(report['findings']) - 30} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
