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

## Added in engine v115 — Finkle profitability

- Return on equity (ROE) = annual net income / average common shareholders'
  equity. It remains separate from the existing return on ending book value.
- Return on net tangible assets = annual net income / (common equity − goodwill
  − other intangibles), shown for the current snapshot and each historical fiscal
  year with sufficient filing evidence. This is informational and does not alter
  the enterprising screen's six scored criteria.
- Debt-to-equity = combined interest-bearing debt (current plus noncurrent) /
  common shareholders' equity.
  The generally-under-1.00× guide is displayed
  but not scored because suitable leverage varies by industry.
- Free cash flow is reconciled through Finkle's three equations. The UI shows all
  three derivations, their spread, and missing evidence; disagreement is surfaced
  as `MISMATCH`, never averaged away or forced to match.

## Added in engine v116 — RONTA

- Return on net tangible operating assets (RONTA) = normalized NOPAT / average
  NTOA. NTOA is computed at the exact beginning and ending balance sheets as
  total assets less goodwill, other intangibles, deployable cash, short-term
  investments, a filed noncurrent-investment balance, and non-interest-bearing
  current liabilities; the two endpoints are averaged.
- Non-interest-bearing current liabilities are current liabilities less filed
  short-term interest-bearing debt. Primary XBRL does not identify every
  noncurrent operating liability consistently, so none is guessed.
- Every required deduction must be filed at both dates. Missing investment or
  intangible evidence remains missing, and RONTA is informational only: it does
  not alter any Graham criterion or verdict.

## Added in engine v130 — lease-consistent and lease-neutral RONTA

- Standard RONTA now keeps a separately reported current operating-lease
  liability in financing capital, matching the existing treatment of the
  noncurrent portion. The current amount is direct
  `OperatingLeaseLiabilityCurrent` or an exact total-less-noncurrent derivation.
- Lease-neutral RONTA starts with that denominator and removes the reported
  `OperatingLeaseRightOfUseAsset`. This produces a presentation-comparability
  series across ASC 842 adoption; earlier filed years are unchanged.
- The lease-neutral series does not reconstruct or capitalize pre-adoption lease
  commitments. Missing post-recognition ROU/current-liability evidence is not
  silently zero and remains disclosed in the detail calculation.

## Added in engines v117–118 — ten-year owner cash bridge

- The Owner Earnings panel no longer repeats a dense latest-fiscal-year table.
  It retains the earnings-growth summary and presents exactly the latest ten
  fiscal-year slots as columns.
- Rows show diluted EPS and shares, common net income, D&A, separately reported
  stock compensation, other operating-cash-flow adjustments, the filed
  working-capital cash effect, operating cash flow, total CapEx, and standard
  FCF. Each cash-bridge value keeps its own filing provenance.
- Other OCF adjustments are a labelled reconciliation residual. When stock
  compensation or an aggregate working-capital cash effect is not separately
  reported, it remains inside that residual; it is never assumed to be zero.
- Maintenance and growth CapEx are shown separately only when a filing identifies
  them. Standard primary XBRL normally supplies only total cash CapEx, so an
  unavailable split remains blank.
- The separate Annual Financial History table was removed from the detail panel;
  its EPS and diluted-share rows now live in the Owner Earnings history.
- Engine v118 stores each direct bridge point compactly as value, tag, form,
  accession and period end; derived residual and FCF values refer to the direct
  rows displayed beside them. This keeps the audit trail without duplicating
  verbose provenance keys hundreds of thousands of times.

## Added in engine v123 — leverage and reconciled operating evidence

- Debt-to-equity now uses the same reconciled combined interest-bearing debt as
  Graham criterion 3, rather than all liabilities or only the noncurrent portion,
  for both the current card and historical fiscal years.
- When `OperatingIncomeLoss` is absent, operating income may be reconstructed as
  gross profit less filed operating expenses only if same-filing nonoperating
  lines reconcile the result exactly to pretax income. Every input remains in
  provenance; an unreconciled candidate stays missing.
- NTOA reads current interest-bearing debt independently. A combined long-term
  debt fact may suppress current maturities when forming total debt, but cannot
  suppress the current portion needed to separate NIBCL.

## Added in engine v132 — inverse operating-income reconciliation

- When an industrial filer omits `OperatingIncomeLoss` and does not publish one
  aggregate operating-expense rollup, operating income may also be reconstructed
  from pretax income by removing separately filed interest income, interest
  expense, and other nonoperating income/expense. Gross profit, SG&A, and the
  separately presented `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`
  must independently constrain all remaining operating-cost rows to no more than
  5% of gross profit, and every input must share the fiscal period, accession,
  and filing. Generic R&D is rejected because FSTR's FY2014 note-only disclosure
  is already included in SG&A and otherwise creates a false subtotal. This
  restores J&J while rejecting loose or incomplete arithmetic; all direct inputs
  remain in provenance.

## Added in engine v133 — historical share presentation scale

- A weighted-share fact is rescaled by exactly 1,000× or 1,000,000× only when
  the same filing and fiscal period supply EPS and its matching income numerator,
  and `EPS × rescaled shares` agrees within 5%. Continuing-operations EPS uses
  `IncomeLossFromContinuingOperations`, not total net income. This repairs 21
  historical company-years across 12 issuers without using neighboring years as
  evidence; share-class, split and depositary-receipt conflicts still stay absent.

## Added in engines v134–v136 — monetary scale and malformed subtotals

- A direct `OperatingIncomeLoss` comparative that disagrees with a complete,
  exact same-filing gross-profit/operating-expense/pretax bridge by exactly
  1,000× or 1,000,000× yields to the reconciled value. Bio-Techne FY2013 is the
  filed-thousands case; the contradictory direct fact is retained in provenance.
- `GrossProfit` is withheld when a same-accession revenue/cost identity disproves
  a suspicious sub-$1,000 fact or a value repeated exactly in three or more
  fiscal years. This rejects Financial Gravity's rendered dash and Dolphin
  Entertainment's unprinted `$3`/`$3m` series while preserving genuine small
  gross results whose statement arithmetic supports them.

## Added in engine v137 — exact cash-flow D&A extension and scale fallback

- The DERA collector keeps the explicitly admitted issuer-extension cash-flow
  concept `DepreciationAndAmortizationOfPropertyPlantAndEquipmentAndComputerPrograms`
  even below the generic $100m extension floor. For FUSB this restores the exact
  statement figures of $1.581m, $1.590m and $1.695m for FY2023–FY2025; the standard
  D&A fact in the same filings is a rounded note disclosure, not that statement row.
- Before the DERA quarter is available, latest-filed-wins has one narrow fallback:
  an earlier same-tag fact for the identical annual start/end dates may displace a
  later comparative only at an exact 1,000× or 1,000,000× conflict and only when
  both adjacent fiscal years corroborate the earlier scale. The earlier and rejected
  facts remain in provenance. Genuine small cash flows and ordinary restatements
  remain untouched.

## Added in engine v138 — working-capital cash-effect sign and complete row family

- `IncreaseDecreaseInOperatingCapital` is a change in the operating-capital
  balance, not the signed cash-flow-statement line. It is now inverted before the
  UI labels it `+/− Working-capital cash effect`. Coca-Cola FY2025 is the pinned
  report case: XBRL carries positive `$7.208bn`, while the audited cash-flow
  statement prints a `$7.208bn` use of cash.
- When no aggregate exists, the engine may reconstruct the cash effect from the
  five non-overlapping rows used by Johnson & Johnson: receivables, inventories,
  other operating assets, accounts payable/accrued liabilities, and other
  operating liabilities. Company Facts omits issuer extensions, so this is
  allowed only for exact SEC accession/year contexts already read against the
  rendered statement. All five must also share the same annual period, accession,
  and form; any additional same-context `IncreaseDecreaseIn*` fact vetoes the
  derivation. Ennis FY2026 is the negative control: its five standard rows omit a
  separately printed `$72k` prepaid/tax extension row and therefore stay blank.
- J&J FY2025 is the filing-backed arithmetic test: `-1.781 - 1.450 + 2.377 -
  6.167 - 5.697 = -12.718` billion, exactly matching its statement rows. This is
  supplemental cash-flow context and does not change a Graham criterion.

## Added in engine v139 — verified modern held-to-maturity investment rows

- Current-generation held-to-maturity tags are not globally equivalent to a
  separate short-term-investment balance. Vertiv FY2025 prints its `$99.5m`
  amount as a distinct balance-sheet row, while Westlake explicitly includes
  `$1.009bn` under the same tag family in cash equivalents.
- The tag is therefore admitted only for exact CIK/accession/date contexts whose
  rendered annual statement has been checked. Vertiv is the positive control;
  Westlake is the no-double-count negative control. Unverified contexts remain
  missing rather than turning a footnote fact into a cash deduction.
- Vertiv's verified endpoints are `$4.8289bn` and `$5.9984bn`; average invested
  capital is `$5.41365bn` and FY2025 NOPAT ROIC is `25.8602%`. RONTA remains
  blank because the separate noncurrent-investment inputs are incomplete.

## Added in engine v124 — ten-year ratio history

- The Ratios table carries the latest ten fiscal-year columns instead of five.
- Revenue is the filing-reported top line for each fiscal year. Gross margin is
  filing-reported gross profit divided by same-period revenue; it remains blank
  when either figure or their period alignment is unavailable.

## Where it shows

Detail panel → "Graham's yardsticks (ch. 13–14)" section; Revenue and Net margin
rows in "Reported annual results". Defensive marks (✓/✗) are informational —
the enterprising screen's verdict is untouched.
