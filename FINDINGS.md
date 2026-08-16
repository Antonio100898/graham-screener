# Stress-Test Findings — 60 tickers, 13 Aug 2026

Three batches: mega caps + edge structures (16), sector/fiscal-calendar variety (22),
small-cap retail + Graham-pass candidates (22). Verdicts: 32 FAIL, 26 INDETERMINATE,
1 rejected foreign filer (correct), 1 delisted ticker (correct). No full PASS —
consistent with 2026 valuations; closest: ASO (6/7, fails only P/TBV), M, DDS, BKE.

Verification base: 33 unit tests; 28/28 figures verified verbatim against filing
documents (AAPL, JPM, KO); TTM composite inputs hand-verified for GOOGL, MU, OXY.

---

## Fixes already applied (approved earlier, tested)

| # | Fix | Evidence it was needed |
|---|-----|------------------------|
| A1 | Staleness guard: instant facts >400 days older than latest balance sheet = missing | AAPL Goodwill from 2017 poisoned TBVPS |
| A2 | Fiscal-year labels from filer's own `fy` field (min across filings), calendar heuristic as fallback | TGT phantom missing FY2023; WMT label mismatch |
| A3 | Liabilities derived: `LiabilitiesAndStockholdersEquity − equity` (same period end enforced) | WMT, AMZN, INTC, T never tag `Liabilities` |
| A4 | Debt chains widened: `+LongTermDebtAndCapitalLeaseObligations(Current)`, `+DebtCurrent` | TGT, T, BA unblocked |
| A5 | Intangibles: total tag, else finite + indefinite-lived summed (same period end) | WMT, T (spectrum), JPM undercounts |
| A6 | Shares fallback: weighted-average diluted (flagged proxy) | F has no consolidated point-in-time count |
| A7 | Price provider: Yahoo chart endpoint (Stooq is dead behind anti-bot wall) | — |

Effect measured on batch 1: INDETERMINATE 10 → 6.

---

## Open issues — proposed fixes, NOT applied

### P1 — Comparative-only fiscal years get mislabeled (bug in current code) — HIGH

- **Evidence:** RDDT (gaps 2021, 2023), DELL (2022, 2024), CRM (2021), DUK (2020),
  MRNA (2020), UAA (2022).
- **Cause:** a year that appears only as a comparative (pre-IPO years; years whose
  original 10-K used a different EPS tag) carries the *filing's* `fy`, which
  overshoots by 1–2. `min()` can't correct it when no original filing is present →
  label collisions → years vanish → false `INSUFFICIENT_DATA` on criteria 4/6
  (~10% of tickers tested). Third-party EDGAR-API documentation confirms `fy`/`fp`
  describe the *filing*, not the fact's period — a known ecosystem pitfall.
- **Proposed fix (research-upgraded):** use the SEC's own `frame` field. Empirically
  verified on DELL/RDDT/DUK: every distinct annual period-end carries exactly one
  `CY####` frame across all its entries, assigned by SEC calendar alignment and
  present even for comparative-only years (RDDT's pre-IPO 2022 → `CY2022`,
  DELL's Jan-2024 year-end → `CY2023`). Label = frame year, taken from whichever
  entry for that period-end carries it; anchored back-walk from the latest year
  only as fallback for frame-less ends.
- **Risk:** low; SEC-authoritative, simpler than any heuristic. Labels become
  calendar-aligned (Dell's self-styled "FY2026" → label 2025) — internally
  consistent, which is all criteria 4/6 need; period ends stay in provenance.

### P2 — Preferred stock: par-value tag is stale AND economically wrong — HIGH (correctness direction)

- **Evidence (empirical, cached companyfacts):**

  | Issuer | `PreferredStockValue` (par) | `PreferredStockLiquidationPreferenceValue` |
  |---|---|---|
  | JPM | $8.15B, stale 2009 | **$21.2B, fresh 2026-06-30** |
  | USB | $4.77B, stale 2013 | **$7.03B, fresh 2026-06-30** |
  | PSA | $4.35B fresh | $4.35B fresh (equal) |
  | OXY | $8.29B fresh | — (par ≈ carrying here) |

  Today both JPM and USB screen with preferred = 0 (flagged) → TBVPS overstated —
  the one direction a Graham screen must never err.
- **Research:** accounting guidance (PwC; standard TBV definitions) confirms common
  tangible book must deduct preferred at **liquidation preference**, which can far
  exceed par/stated value; `PreferredStockValue` is defined as par/stated value only.
- **Proposed fix:** reorder chain to `PreferredStockLiquidationPreferenceValue` →
  `PreferredStockValue` → `PreferredStockValueOutstanding`, staleness-guarded.
  Where none is fresh (dimensional-only tagging), keep flagged zero-default and
  surface the flag prominently for financials.
- **Risk:** low; strictly more correct and better-maintained tags.

### P3 — Zero-vs-unknown for never-tagged concepts — HIGH (coverage), needs a policy call

- **Evidence:** 12/22 small caps blocked on criterion 3 because debt-free companies
  never tag debt (DDS, BKE, CATO, ANF, WSM, DKS, MOV, SFIX, BOOT…); COST, KSS, TGT
  blocked on criterion 7 for never-tagged goodwill/intangibles. This hits precisely
  the cheap, simple companies the Enterprising screen exists to find; DDS and BKE
  are near-passes stuck at INDETERMINATE.
- **Research supporting the assumption:** SEC staff guidance requires every amount
  presented in the financial statements to be tagged with the standard us-gaap
  element where one exists (custom tags only where none exists); untagged presented
  amounts are a disclosure deficiency. So a debt concept absent from a company's
  entire XBRL history means the statements never presented it — evidence of
  absence, not ignorance.
- **Research against (residual risk):** average custom-tag ("extension") rates run
  ~20% of tags and are rising for smaller reporting companies. A filer whose debt
  lives in a custom extension element would be invisible to any standard-tag scan.
- **Empirical stress of the naive proposal (13 Aug, full-namespace scan of all 13
  blocked tickers):** the naive "never tagged on our chains ⇒ zero" rule would have
  produced FALSE data. DDS carries real debt under tags outside every chain we use
  ($225.7M `OtherLongTermDebtNoncurrent` + $96M `UnsecuredDebtCurrent` + $200M
  junior subordinated debentures, $38M interest expense). DKS carries **$1.9B**
  (`UnsecuredDebt` / `DebtAndCapitalLeaseObligations`). BOOT has finance leases.
  Meanwhile BKE, CATO, ANF, WSM, SFIX, LULU are genuinely clean — their only
  debt-pattern facts are asset-side investments (`AvailableForSaleDebtSecurities…`)
  or undrawn revolver capacity, and no material interest expense exists in any
  filing. The cohort is separable, but only by scanning the whole fact universe,
  not our tag chains.
- **Layered plan (replaces the naive proposal):**
  - **P3a — no policy change needed, just coverage:** prefer total-style tags
    (`DebtAndCapitalLeaseObligations`, `DebtLongtermAndShorttermCombinedAmount`)
    when fresh; widen component chains with the liability-side tags found
    (`UnsecuredDebt(Current)`, `OtherLongTermDebtNoncurrent`, `LoansPayable*`,
    `JuniorSubordinatedDebenture*`, `FinanceLeaseLiability(Current/Noncurrent)`,
    `CommercialPaper`, `LineOfCreditFacilityAmountOutstanding` — note: *outstanding*,
    never *capacity*). Where components must be summed and tag definitions overlap,
    the overlap overstates debt → conservative FAIL bias, never a false PASS —
    acceptable in a Graham screen and flagged in the note. Fixes DDS, DKS, BOOT
    with real filed numbers. Zero §5.1 relaxation.
  - **P3b — evidence-gated assume-zero, opt-in only:** assume debt = 0 only when a
    scan of the **entire** us-gaap + company-extension namespaces finds, in any
    filing ever: no liability-side debt-instrument tag with a material value
    (asset-side `…DebtSecurities…` investment tags and `…BorrowingCapacity`
    facts excluded by pattern), and no material `InterestExpenseDebt`. Exposed
    behind an explicit API opt-in (`?assume_absent_zero=true`); default behavior
    stays strict §5.1 INSUFFICIENT_DATA. Response marks every assumed value with
    `assumed_zero: true` and the criterion note names the assumption. Unblocks the
    genuinely clean cohort (BKE, CATO, ANF, WSM, SFIX, LULU) without ever asserting
    more than the filings support by default.
  - Same two-layer pattern applies to goodwill/intangibles (evidence scan:
    `BusinessCombination*`/`Goodwill*` family) — lower stakes, acquisitions leave
    louder XBRL traces.
- **Risk after layering:** P3a is pure coverage (recommended unconditionally).
  P3b's residual risk — debt in a custom extension element with no standard-tagged
  trace and no interest expense — is small and the opt-in keeps the default honest.

### P4 — Long-term debt variant `LongTermNotesPayable` — LOW

- **Evidence:** ORCL tags its (large) debt as `LongTermNotesPayable` (fresh
  2026-05-31); our chain's tags are stale-2022 for ORCL → criterion 3 blocked.
- **Proposed fix:** append `LongTermNotesPayable` to the long-term chain.

### P5 — Dimensional-only filers — ACCEPT for v1, concrete v2 path found

- **Evidence:** GM and F tag debt, BRK-B tags EPS/shares, only with XBRL dimensions
  (segment / share class). The companyfacts API strips dimensioned facts, so these
  stay honestly INSUFFICIENT.
- **Research:** SEC's quarterly "Financial Statement Data Sets" were reprocessed in
  Dec 2024 and the NUM file now carries a `segments` column — dimensional facts
  from the primary financial statements are available in bulk without parsing
  filing instances. That is the v2 source for GM/F/BRK-B-class filers.
- **Recommendation:** (a) accept + document for v1; (b) v2: FSDS `num.txt` with
  `segments` as an additional source-layer provider.

### P6 — Delisted-ticker error message — COSMETIC

- **Evidence:** WBA (taken private) fails with bare `"WBA"`.
- **Proposed fix:** message "unknown ticker WBA: not in SEC mapping (delisted or
  never SEC-registered)".

### P7 — Edges observed but not fully exercised

- Fiscal-year transition stubs (UAA) — P1's spacing walk handles the labels, but a
  stub year is a genuine §5.6 comparability break; consider surfacing a note.
- Post-Chapter-11 EPS series (§5.6) — untested; known design limitation.
- TTM composite where the filer restates mid-year — inputs are traceable but the
  composite carries no restatement pass of its own.

---

## Round-2 fixes applied 13 Aug 2026 (P1 + P2 + P4 + P3a + P3b), measured

All four recommendations plus the opt-in are implemented and tested (46 unit tests).

- **P1**: fiscal labels now come from SEC's `frame` field (`CY####`), filled from the
  nearest framed neighbour when absent; fy/heuristic only as anchor of last resort.
  CRM, DUK, MRNA, UAA label gaps gone. DELL's FY2021 and RDDT's pre-IPO years
  remain missing because those annual EPS facts genuinely don't exist in XBRL —
  honest INSUFFICIENT, not label bugs.
- **P2**: preferred chain is `PreferredStockLiquidationPreferenceValue` →
  `PreferredStockValue` → `PreferredStockValueOutstanding`. USB's $7.0B and JPM's
  $21.2B preferred now reduce TBVPS.
- **P3a/P4**: `total_debt` rollup tags (`DebtAndCapitalLeaseObligations`,
  `DebtLongtermAndShorttermCombinedAmount`) preferred; long/short buckets sum
  disjoint component groups (current-portion + borrowings + finance leases;
  `LongTermNotesPayable`, `OtherLongTermDebtNoncurrent`, subordinated debentures).
  DDS criterion 3 now PASSes on its real $425.7M; DKS, BOOT, AEO, F, ORCL compute.
  AAPL's short-term debt now correctly includes commercial paper.
- **P3b**: `?assume_absent_zero=true` (batch: body field). Default remains strict
  §5.1. Assumption applied only when the entire filing history shows zero
  liability-side debt / goodwill / intangibles evidence.

**Measured on the 60-ticker set:** INDETERMINATE 26 → **19** strict → **15** with
opt-in (LULU, DDS, BKE, SFIX unblocked fully). The opt-in unblocks fewer than the
~6-floor estimate — correctly: ANF, WSM, MOV, GIII, PLTR, RDDT carry *historical*
debt facts (paid-off loans, drawn credit lines), so the never-tagged-ever gate
refuses to assume. Those are genuine unknowns under the policy as designed.

**Possible future refinement (not planned):** debt differs from goodwill —
a repaid loan leaves the balance sheet, so "old debt facts + none fresh" usually
means zero *now*. A debt-specific recency variant of the assumption would unblock
the paid-off cohort at slightly higher risk. Not implemented; revisit only if the
INDETERMINATE floor matters in practice.

## Round-3: /code-review findings fixed 13 Aug 2026

All 10 verified findings from the high-effort review are fixed (54 unit tests):
_sum_facts now includes differently-dated fresh components (understating debt was
a false-PASS risk); the staleness anchor falls back to
`LiabilitiesAndStockholdersEquity` (== total assets by identity) so it stays armed
without an `Assets` tag; a stale continuing-ops EPS series can no longer displace
the current diluted series; criterion 5 answers "unknown" instead of FAIL when
dividend-like facts exist under unchained tags (inbound/equity-method/minority
dividends excluded as evidence — INTC/BRK-B stay confident non-payers); the
`LongTermDebt` total-tag no longer double-counts current maturities against the
short bucket; dot-form class tickers (BRK.B) reach Yahoo in dash form; the SEC
rate limiter is thread-safe under FastAPI's threadpool; fiscal-label collisions
bump instead of silently swallowing a year; one bad filing no longer voids a
whole batch; and a non-JSON 200 from SEC retries then maps to 502 instead of
escaping as a 500. E2E re-verified: 60-ticker sweep matches the round-2 baseline
(plus BRK.B now quoting), API surface checked end-to-end.

## Batch 4 — 50 more tickers (pharma, energy, defense, insurers, utilities,
## homebuilders, payments, micro-cap retail), 13 Aug 2026

Verdicts: 30 FAIL, 17 INDETERMINATE, 3 delisted (X, SCVL, GES — correct
rejections). 110 tickers screened in total across all batches.

**Fixed during this batch (55 unit tests):**
- EPS tag-switch recency bug: FCX's `EarningsPerShareDiluted` died in 2021
  (15 years of history) while its continuing-ops series runs through FY2025
  (13 years); the length test let the dead series win, pinning criteria 1/4/6 —
  and the TTM — to 2021 data (TTM 3.42 vs the correct 1.52). Selection now ranks
  recency first, then §5.3 continuing-ops preference, then depth.

**New evidence for known issues:**
- P5 (dimensional-only tagging) now includes mega-caps: XOM, V, and HVT tag EPS
  with **no** non-dimensional per-share element at all — the companyfacts API
  returns nothing, criteria 1/4/6 honestly INSUFFICIENT. With BRK-B, GM, F this
  is the strongest argument for the FSDS `segments` source in v2.
- TTM composite spikes verified as-filed, not bugs: MRK (H1-26 EPS −2.26),
  GILD (−6.82), HON (+20.39, spin-off gains). §5.6/§8.7 territory — the response
  discloses the inputs.
- Stopped-tagging goodwill/intangibles blocks c7 for COP, DVN, FCX, AIG, LNC,
  UNM, BBY, DHI, NVR, TOL — the opt-in correctly refuses (historical evidence
  exists). Only the documented recency-variant policy would unblock these.

**Design observation worth a decision eventually:** unclassified-balance-sheet
filers (banks, insurers, homebuilders) can never reach overall PASS — §4.4 turns
their N/A on criteria 2–3 into INDETERMINATE. LEN passes all five computable
criteria (P/E 6.8) and LNC screens at P/E 3.8, yet both are structurally capped.
That is the doc's stated intent ("a screen that cannot assess liquidity has not
screened the company") — but it means the screen is silent on entire sectors
where Graham-style value currently concentrates.

## Batch 5 — 83-ticker value-tilted real screen (refiners, chemicals, steel,
## auto parts, transport, food, deep-value healthcare, homebuilders), 13 Aug 2026

193 tickers screened lifetime. **First batch with zero new extraction issues** —
no fiscal gaps, no TTM anomalies, no crashes across 78 evaluated tickers; the
normalization layer has stabilized.

- **Still no full PASS.** Closest ever: **DINO (HF Sinclair) 6/7** — P/E 8.48,
  liquidity, debt, stability, dividend, growth all pass; only P/TBV (2.26 vs
  1.20) blocks. Then VLO, STLD, RS, INGR at 5/7 (all blocked by c1+c7);
  CF 5-pass INDETERMINATE (short-term debt unknown).
- GT trades below tangible book (P/TBV 0.82 → c7 PASS) but fails the earnings
  criteria — the classic value-trap shape, correctly caught.
- 5 ERROR tickers verified as genuine ticker churn, not bugs: VSCO now trades
  as VSXY (re-screened fine under the new symbol), IPG merged into OMC,
  CTRA/HBI/TMHC gone from the SEC map. The map is authoritative.
- Extreme-but-correct values spot-checked plausible: GPC P/E 538 (TTM collapse),
  EBAY P/TBV 619 (buyback-shrunk tangible book).

## Batch 6 — broad US run, 501 tickers, 13 Aug 2026

Report: `~/Desktop/Graham-Enterprising-Screen-US-2026-08-13.pdf` (91 pages).
440 evaluated · 0 PASS · 319 FAIL · 121 INDETERMINATE · 56 unknown tickers
(stale symbols in the universe list) · 5 foreign filers rejected.

**Bug found and fixed — basic-only annual EPS (material, caught pre-delivery).**
Lennar's FY2025 10-K tags **only** `EarningsPerShareBasic`; the diluted-only
chain silently froze LEN's series at FY2024, which staled criteria 4/6 and
corrupted the TTM anchor (it computed FY2024 annual + FY2026 H1 − FY2025 H1,
skipping FY2025 entirely). Effect: **P/E 6.81 → 13.70**, flipping criterion 1
from PASS to FAIL. LEN was on track to headline the report as "passes every
assessable criterion" on wrong data.
Fix: after choosing the diluted series, fill years it lacks from other EPS tags,
basic last, flagged in provenance (`basic — diluted not tagged`). Diluted still
wins for every year that has it, so the conservative bias holds. Blast radius:
73 of 440 tickers gained EPS years — only LEN gained a *recent* one; the other
72 gained historical years, deepening criterion 6 coverage. 63 unit tests.

**Ranking method for the report.** Counting satisfied criteria is a poor measure
of "close" — it called NVDA a near-pass while it misses P/E by 3.4×. Companies
are ranked by *worst remaining gap*: the largest multiple by which any failing
ratio criterion misses its threshold. Unassessable criteria are reported as
unknowns, never as small gaps.

Closest names: AEO 6/7 (1.60× on P/TBV), DINO 6/7 (1.88× on P/TBV), M and ETD
5/7 at 1.44×. ZION/LEN/ORI pass everything computable but carry unassessable
criteria (no classified balance sheet) and so remain capped.

## Verification of the independent findings document, 13 Aug 2026

Checked `graham-screener-verification-findings.md` claim by claim against filings.

**Confirmed verbatim (the load-bearing claims are all correct):**
- DINO LCM reserve $706M → $64M with a **(642)** adjustment; H1-26 pre-tax income
  $2,011M; effective rate 23.3%. The 642 is 31.9% of pre-tax — the document said
  ~32%. Its normalisation (≈$2.73/sh, TTM ≈7.76, P/E ≈11.5 → FAIL) reproduces.
- AEO's *"last year's $75 million inventory write-down of spring and summer
  merchandise"* appears verbatim; diluted shares 172,342K (Q1-26) vs 179,548K
  (Q1-25); accession matches exactly.
- Both margin figures are real: the document quoted Q2 ($16.50 → $25.95, +57%),
  the earlier check quoted six-month ($12.91 → $18.13, +40%). No conflict.
- Debt reconciles: its 2,772 + 71 + 14 and our 2,843 + 14 both total **$2,857M**.
- Lubricants & Specialties separation announced 28 July 2026 — verbatim.

**Two corrections to the document:**
1. **F-3 overstates the risk.** Values are *displayed* rounded but *computed* on
   exact filed integers in Decimal. Macy's is 6,896,000,000 / 4,674,000,000 =
   **1.475396** — 1.6% below the limit, a stable verdict, not one that "could land
   either side" of 1.50. Debt/NCA is 1.094509 vs 1.10. The transparency fix is
   still worth doing; the correctness risk it implies does not exist.
2. **F-4 is real but not for the stated reason.** THO does not tag
   `IntangibleAssetsNetExcludingGoodwill` at all, and its
   `IndefiniteLivedIntangibleAssetsExcludingGoodwill` was last tagged in **2011**
   — the staleness guard correctly excludes it. The generosity is unavoidable
   from XBRL, so the fix is to flag the finite-only path, not to sum a dead tag.

**Implemented from the recommendations (R-1, R-2, R-3, R-5, R-7):** the engine now
computes `earnings_quality` disclosures in the snapshot (exposed via
`/fundamentals`, not only the PDF) — non-cash items ≥10% of pre-tax income in a
TTM component period with the year-earlier comparable for context, a loss quarter
in or near the window, and diluted share counts diverging >5% across the three
components. The report adds a "P/E on last FY" column (R-5). Two implementation
bugs were caught while building it: DINO tags one LCM line under **two** elements
(deduplicated by amount), and AEO's `BusinessCombinationAcquisitionRelatedCosts`
runs at $61M/quarter and $261M/year — recurring, so asserting "non-recurring"
would have been wrong. Disclosures now state magnitude and year-over-year swing
and let the reader judge, exactly as R-1 asked.

**F-3 validated itself in production:** on the latest quote AEO's P/E is
**10.02** — criterion 1 now FAILS and AEO has dropped from NEAR-PASS to CLOSE. A
0.2% margin flipped on an ordinary intraday move, which is precisely why the
threshold-proximity flag exists. **ASO is now the cleanest NEAR-PASS: zero
caveats, TTM 8.75 against FY 8.9** — the document predicted exactly this.

## DINO end-to-end verification + review round 5, 13 Aug 2026

**DINO verified against its actual filings — every figure correct, and the
cyclical-earnings concern fully confirmed.** Diluted EPS of 4.93 (Q2-26), 8.48
(H1-26), 1.07 (H1-25), 3.08 (FY2025) and 0.91 (FY2024) all appear verbatim in
`dino-20260630.htm` and `dino-20251231.htm`. The TTM composite
(3.08 + 8.48 − 1.07 = 10.49) is arithmetically right and correctly sourced.

The screen is being *misled by a real number*, not a wrong one. HF Sinclair's
own 10-Q states: *"Adjusted refinery gross margin per barrel sold increased
$5.22, or 40%, from $12.91 … to $18.13 … favorable crack spreads."* H1-2026 EPS
alone is 2.8× the whole of FY2025. Same price ($90.11), different earnings base:

| Earnings basis | EPS | P/E | Criterion 1 |
|---|---|---|---|
| TTM (what criterion 1 uses) | 10.49 | **8.59** | PASS |
| FY2025 as filed | 3.08 | 29.26 | fail |
| 3-year average (Graham's Defensive smoothing) | 4.09 | 22.01 | fail |
| 5-year average | 5.99 | 15.04 | fail |

This is §8.7 exactly: the enterprising screen's single-year earnings test makes
a cyclical look cheapest at the top of its cycle. Behaviour is per spec — the
gap was that nothing disclosed it.

**Report disclosures added (the reviewer's highest-value recommendation):**
- *Earnings may not be representative* — fires when TTM diverges ≥35% from the
  last full year, and restates the P/E on FY and 5-year-average earnings.
  Catches DINO (3.4×), AEO (1.5×), EOG, FLXS.
- *Growth measured against a loss year* — fires when criterion 6's base year EPS
  is negative. FY2020 is a pandemic loss for much of the market, which makes the
  test vacuous; catches AEO, DINO, M, EOG, FLXS and inflates the market-wide
  criterion-6 pass rate.
- *Decided at the threshold* — fires within 2% of a limit, with unrounded values.
  Catches AEO's criterion 1 (9.98 vs 10.00, a 0.2% margin) and Macy's criteria 2
  and 3 (1.48 vs 1.50; 1.09 vs 1.10).
- *Dividend evidence is an aggregate* — see below.
168 of 440 companies carry at least one caveat; the shortlist marks each with ⚠.

**Also fixed:** the dividend chain tried the aggregate `PaymentsOfDividends`
second, ahead of common-specific tags. Aggregates roll up preferred and
noncontrolling distributions, so they are not proof of a *common* dividend.
Common-specific tags now come first; aggregates are tried last and labelled
"aggregate — may include preferred and noncontrolling" in provenance, with a
report caveat when the filer also has preferred stock outstanding. 65 tests.

**Checked, no change needed:** REGN's assumed-zero goodwill is correct — its
sole "goodwill" mention is boilerplate risk-factor prose, not a balance-sheet
line. THO's finite-lived-only intangibles fallback is real but immaterial there
(it fails regardless); the summing path already prefers the total tag.

## Japanese-issuer investigation, 13 Aug 2026

Swept the SEC ticker map: 39 Japanese issuers — 15 file 20-F with XBRL, 22 have
no XBRL at all (ADR shells), 2 file 10-K. All 20-F filers correctly rejected
(422). Data inspection confirms rejection is right, not merely policy: IFRS
taxonomy, JPY values against USD ADR prices, ADR ratios absent from XBRL (10×
error risk), and no interim filings (Toyota's newest structured data is ~17
months stale). Full analysis in `HOW-IT-WORKS.md` §4.1b; EDINET is the route to
the TSE small caps where Japanese Graham value actually sits.

**Bug found and fixed during the sweep:** a companyfacts **404** (filer exists
but never submitted XBRL — 22 of the Japanese names, plus ADR shells and
pre-2009 registrants generally) was surfaced as `502 EDGAR unavailable`,
implying an outage and inviting pointless retries. Now a distinct
`NoXbrlDataError` → **404** with an explanatory message. Note the 404 is raised
immediately rather than retried, so these lookups also stop burning four
backoff attempts.

## Research sources (13 Aug 2026)

- [SEC staff FAQs on interactive data](https://www.sec.gov/about/divisions-offices/division-economic-risk-analysis/office-structured-disclosure-staff/staff-interpretations-faqs-related-interactive-data-disclosure) — tagging mandate, "no/none = zero" disclosure test
- [SEC sample comment letter on XBRL disclosures](https://www.sec.gov/rules-regulations/staff-guidance/disclosure-guidance/sample-letter-companies-regarding-their-xbrl) — untagged presented amounts = deficiency
- [SEC custom-tag rate trends](https://www.sec.gov/data-research/structured-data/us-gaap-xbrl-custom-tags-trend) — ~20% average extension rate, rising for smaller filers
- [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets) — Dec-2024 reprocessing added `segments` to NUM
- [fundamentalshub: SEC JSON structured filings](https://fundamentalshub.com/blog/sec-data-json-format), [tldrfiling: EDGAR XBRL API tutorial](https://tldrfiling.com/blog/sec-edgar-xbrl-api-python-tutorial) — fy/fp refer to the reporting filing; dedup must key off period end
- [Calcbench: PreferredStockValue element](https://www.calcbench.com/element/PreferredStockValue) — defined as par/stated value
- [PwC Viewpoint 5.6 Preferred stock](https://viewpoint.pwc.com/dt/us/en/pwc/accounting_guides/financial_statement_/financial_statement___18_US/chapter_5_stockholde_US/56_preferred_stock_US.html) — liquidation preference can far exceed par; must be disclosed
- [FIG banking TBV guide](https://ibinterviewquestions.com/guides/fig-investment-banking/price-to-book-value-tangible-book-value) — tangible common equity deducts preferred at liquidation preference
- Frame-field behavior verified empirically against cached companyfacts (DELL, RDDT, DUK)
