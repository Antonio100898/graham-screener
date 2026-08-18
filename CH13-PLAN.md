# Chapter 13/14 parameters — coverage map

Source: `~/Downloads/graham_company_analysis_parameters.md` (Tables 13-1, 13-2, ch. 14 defensive checklist).
Status: implemented in engine v29 unless marked otherwise.

## Already present before v29

price, shares, market cap, net income (annual + TTM), EPS (annual + TTM),
3-year-average P/E, dividend per share + yield, current assets/liabilities,
current ratio, P/TBV, 52w/3y/5y price stats, long/short debt + preferred
(extracted with provenance).

## Added in v29 — derived from data already stored

- Average EPS for three 3-year periods: FY(L-2..L), FY(L-7..L-5), FY(L-12..L-10)
- Growth between smoothed levels, 5y and 10y apart (total %, not CAGR;
  refused when the earlier average is not positive)
- Stability: worst decline vs trailing 3-year average over the last 10 years,
  with the number of examinable years disclosed
- Positive-EPS count over the last 10 years, missing years disclosed
- BVPS (intangibles included; preferred + NCI deducted as in TBVPS) → P/B,
  earnings-on-book (TTM EPS / BVPS), and P/E₃ᵧ × P/B ≤ 22.5
- Working capital, working capital / long-term debt, LT-debt ≤ WC mark
- Total capitalization = market cap + LT debt + preferred (preferred absent
  counts as zero — same convention as TBVPS)

## Added in v29 — new extraction

- **Revenue**: annual series + TTM. Revenue elements carry wildly different
  scopes (ConAgra's umbrella `Revenues` = $1.6B sub-item beside $13B true sales;
  Westlake's own `Revenues` changes meaning mid-history), so the series is
  STITCHED: start from the top line's latest year and extend one year at a time —
  same element tolerates 10x swings (COVID is real), switching elements demands
  3x agreement, an unprovable year ends the series. Sector top-line elements
  (lease income, interest income, regulated revenue, premiums) cover REITs,
  banks, utilities, insurers. Enables net margin and Graham's size parameter.
- **Operating income**: `OperatingIncomeLoss` annual series. Kept separate from
  net margin because ch. 13 explicitly distinguishes the two. Banks/insurers
  have no such subtotal — stays absent.
- **Dividend record**: calendar years with a positive common-dividend fact;
  reports first recorded year, current streak start, interruptions. The
  20-year defensive test is NOT verifiable from XBRL (record starts ~2009-11) —
  the record start is always displayed instead of a faked verdict.

## Deliberately not done

- 20-year dividend verdict (impossible honestly; see above)
- Size thresholds ($100M sales is a 1970 dollar figure; shown as data, no verdict)
- Price record beyond 5 years (needs a separate `range=max` fetch per ticker;
  revisit if wanted)
- Convertible-dilution analysis beyond diluted EPS (terms not reliably in XBRL)

## Where it shows

Detail panel → "Graham's yardsticks (ch. 13–14)" section; Revenue and Net margin
rows in "Reported annual results". Defensive marks (✓/✗) are informational —
the enterprising screen's verdict is untouched.
