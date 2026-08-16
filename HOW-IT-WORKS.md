# How the Graham Enterprising Screener Works

Evaluates a US-listed ticker against the six reproducible Enterprising Investor
criteria of Benjamin Graham's Chapter 15 screen, using primary SEC XBRL filings — never aggregator data — with
full provenance for every figure. Companion docs: the technical design document
(rationale and rules) and `FINDINGS.md` (test campaigns, fixes, open issues).

```text
ticker ──> Layer 1: Sources  ──> Layer 2: Normalisation ──> Layer 3: Screen ──> Layer 4: API
           (EDGAR, Yahoo)        (XBRL -> FinancialSnapshot)  (pure functions)     (FastAPI)
```

Dependencies point downward only. Layer 3 has no network, filesystem, or clock —
every rule is unit-testable against hand-built fixtures.

---

## 1. How data is fetched (Layer 1 — `sources/`)

### 1.1 Ticker → CIK

`EdgarClient.cik_for` downloads SEC's `company_tickers.json` map (cached) and
matches the ticker. Class shares use SEC's dash form: `BRK.B` is normalised to
`BRK-B`. A ticker not in the map (delisted, acquired, never SEC-registered)
raises → API 404 with an explanatory message.

### 1.2 Fundamentals — SEC companyfacts API

One call per company: `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` —
every XBRL fact the company ever filed, grouped
`facts → taxonomy (us-gaap / dei / …) → tag → unit → [entries]`.

Each entry carries: `val`, `end` (period end), `start` (duration facts only),
`form` (10-K / 10-Q / …), `accn` (accession number), `filed`, `fy`/`fp`
(the **filing's** fiscal period — see §2.2), and sometimes `frame` (`CY2024`).

**Critical API property: dimensional facts are stripped.** Facts tagged with
XBRL dimensions (per share class, per segment) never appear. This is the root
cause of the biggest coverage gap (§4.1).

### 1.3 SEC etiquette (mandated + defensive)

- `User-Agent` with contact details (SEC requirement; `SEC_USER_AGENT` env var).
- ≤ 10 requests/second — enforced by a **thread-locked** limiter (FastAPI sync
  endpoints run on a threadpool; an unlocked limiter bursts past the cap).
- Exponential backoff (1s/2s/4s, 4 attempts) on 429/5xx/network errors, and on
  a 200 response with a non-JSON body (SEC occasionally serves an HTML
  interstitial); after retries → API 502.
- Disk cache in `~/.cache/graham-screener/`, TTL 1 day (filings are immutable
  once filed — the cache is the main performance lever). Corrupt cache file =
  cache miss, refetched.

### 1.4 Prices — Yahoo chart endpoint

`YahooPriceProvider` (behind a swappable `PriceProvider` protocol) hits
`query1.finance.yahoo.com/v8/finance/chart/{symbol}` — free, unofficial,
delayed. Symbols are dash-normalised (`BRK.B → BRK-B`). Returns price + quote
timestamp; the timestamp is carried into the response because P/E and P/TBV mix
a live price with a balance sheet up to a quarter old. No quote → criteria 1
and 7 go `INSUFFICIENT_DATA`, never a guess.

*(Stooq, the original choice, is dead behind an anti-bot wall.)*

`history()` asks the same endpoint for `range=5y&interval=1wk`. The response
carries the same `meta` block as the quote call, so five years of weekly closes
cost **no extra request** — the export fetches history instead of quotes and
gets both. Null closes (a week the exchange reported nothing) are dropped rather
than read as a crash to zero. Series are stored in the `price_history` table
keyed on CIK, so the statistics can be recomputed without refetching.

---

## 2. How raw XBRL becomes a snapshot (Layer 2 — `normalize.py`)

All the messiness lives here. Output: `FinancialSnapshot` — every value is a
`Fact` (Decimal value + `Provenance`: concept, tag, fiscal year, form,
accession, filed date, period end). Float is never used for money.

### 2.1 Annual EPS series (criteria 4 and 6)

- **10-K facts only**, duration 340–400 days (covers 52/53-week years).
  Quarterly summation is prohibited (§5.2 of the design doc) — diluted share
  counts change across quarters, so summed quarters ≠ reported annual EPS.
- **Restatements**: the same period end filed multiple times → latest-filed
  wins; the accession number records which filing the value came from.
- **Tag selection**: candidates are `EarningsPerShareDiluted`,
  `EarningsPerShareBasicAndDiluted`, and
  `IncomeLossFromContinuingOperationsPerDilutedShare`. Ranked by **recency
  first** (filers switch tags mid-history — FCX's plain diluted tag died in
  2021 while continuing-ops runs on), then continuing-ops preference (§5.3),
  then history depth.

### 2.2 Fiscal-year labels — the `fy` trap and the `frame` fix

The `fy`/`fp` fields describe the **filing**, not the fact: a FY2023 comparative
inside the FY2025 10-K carries `fy=2025`. Naive labeling collapses or loses
years (phantom "missing FY2023" for Jan/Feb year-ends like Target; vanished
pre-IPO years for RDDT).

Solution: SEC's **`frame`** field (`CY####`) is its calendar-aligned canonical
label, present even for comparative-only years — verified empirically on
DELL/RDDT/DUK. Ends without a frame are filled from the nearest framed
neighbour by period-end spacing; a final pass forces labels strictly increasing
so two fiscal years can never collapse into one slot (a hidden loss year is the
failure mode). Labels are therefore calendar-aligned: Dell's self-styled
"FY2026" (ends Jan 2026) gets label 2025 — internally consistent, which is all
criteria 4/6 need; provenance keeps the real period ends.

### 2.3 Current (TTM) EPS (criterion 1)

TTM = latest annual EPS + latest 10-Q fiscal-YTD − same-duration prior-year YTD
(all same tag). Falls back to the latest annual figure when no newer quarter or
no comparative exists — provenance then shows the age. Approximate by nature
(share counts differ across the three pieces); all three input facts are
returned in the criterion's `inputs`.

### 2.4 Balance-sheet items and the staleness guard

Each concept takes its **latest instant** fact (latest period end, then latest
filed) from 10-K/10-Q filings, via per-concept tag fallback chains.

**Staleness guard (§5.1):** instant facts more than 400 days older than the
latest balance sheet are treated as missing — a filer that *stopped* reporting a
line (AAPL's last `Goodwill` fact is from 2017) must not have the old value
resurrected into TBVPS. The anchor is `Assets`, falling back to
`LiabilitiesAndStockholdersEquity` (equal to total assets by the accounting
identity) so the guard stays armed for filers that never tag `Assets`
(WMT-class).

### 2.5 Tag chains as actually implemented (evolved well beyond the design doc §3.2)

| Concept | Resolution |
|---|---|
| Total assets | `Assets` → `LiabilitiesAndStockholdersEquity` (identity) |
| Total liabilities | `Liabilities` → derived `L&SE − equity` (incl-NCI preferred), same period end enforced |
| Total debt (rollup) | `DebtLongtermAndShorttermCombinedAmount` → `DebtAndCapitalLeaseObligations`; preferred over long+short when present |
| Long-term debt | first of `LongTermDebtNoncurrent` / `LongTermDebtAndCapitalLeaseObligations` / `LongTermNotesPayable` / `LongTermDebt`, **plus** additive components (subordinated debentures; finance leases unless already included; `OtherLongTermDebtNoncurrent` only when no primary) |
| Short-term debt | `DebtCurrent` alone, else current-portion group + borrowings group (`ShortTermBorrowings`/`CommercialPaper`) + current finance leases. When the long bucket used the plain `LongTermDebt` total (which includes current maturities), the current-portion group is skipped — no double count |
| Goodwill | `Goodwill` |
| Intangibles | `IntangibleAssetsNetExcludingGoodwill` → finite-lived + indefinite-lived parts summed |
| Preferred stock | `PreferredStockLiquidationPreferenceValue` **first** (the economically correct common-TBV deduction; the par-value tag is both wrong and often stale — JPM's par tag died in 2009 at $8.15B vs $21.2B liquidation preference) → `PreferredStockValue` → `PreferredStockValueOutstanding`. Absent → 0, flagged |
| Noncontrolling interest | `MinorityInterest` + `RedeemableNoncontrollingInterestEquityCarryingAmount` summed. `Assets − Liabilities` is equity **including** minority holders' share (MPC: $6.64B NCI on $19.08B parent equity — a 35% TBVPS overstatement if skipped), so it is deducted in TBV. Skipped when liabilities were derived via parent-only `StockholdersEquity`, which already leaves NCI inside the liabilities figure — deducting again would double-count. Absent → 0 (an equity line not presented is one the filer doesn't have) |
| Shares outstanding | `CommonStockSharesOutstanding` → `dei:EntityCommonStockSharesOutstanding` → weighted-average diluted shares (flagged proxy, for multi-class filers like Ford) |
| Dividends | 8-tag chain (`PaymentsOfDividendsCommonStock`, `PaymentsOfDividends`, `DividendsCommonStockCash`, …). "Currently pays" = latest positive fact ends within **its own duration + 60 days** of the balance-sheet date — the window scales with tagging cadence, so a suspended quarterly payer fails within ~2 quarters while annual-only taggers aren't false-failed. Chain missed but some *other* dividend-named tag has a recent positive (inbound/equity-method/minority-interest/preferred excluded) → **unknown**, never a confident FAIL. Nothing anywhere → not paying (payers must show payments in the cash-flow statement) |

Component sums include **all** fresh parts even at different period ends —
dropping a part understates debt/intangibles, and overstating is the
conservative direction for both criteria 3 and 7. The combined tag string
discloses exactly what was summed.

### 2.6 Missing is not zero — and the opt-in exception

Default: an absent concept is *unknown* → `INSUFFICIENT_DATA` → overall
`INDETERMINATE`. Never coerced to zero (absent goodwill treated as 0 would
manufacture false criterion-7 passes).

`?assume_absent_zero=true` (batch: body field) relaxes this **only** for
concepts with zero supporting evidence in the company's **entire XBRL history**,
every namespace (custom extensions included):

- debt: no liability-side debt-instrument tag ever (asset-side
  `…DebtSecurities…` investments and undrawn `…BorrowingCapacity` excluded by
  pattern) and no material debt-interest expense; classified balance sheet
  required;
- goodwill / intangibles: no tag whose subject is that concept, ever.

Every assumption is flagged (`assumptions` array + criterion note). Rationale:
SEC requires standard-tagging every presented amount — 15 years of filings with
no debt tag means debt was never presented. A company that *stopped* tagging
(paid-off debt, AAPL goodwill) never qualifies — that stays honestly unknown.
This gate was validated the hard way: the naive version would have zeroed DDS's
real $520M and DKS's $1.9B of debt hiding under unchained tags.

### 2.7 Foreign filers

20-F/40-F-only filers are rejected explicitly (API 422), never partially
evaluated.

---

## 3. The screen (Layer 3 — `screens/enterprising.py`)

Pure function: `evaluate(snapshot, quote) -> ScreenResult`.

| # | Criterion | Test | Key handling |
|---|---|---|---|
| 1 | Earnings valuation | P/E < 10.0, **TTM EPS** (not an average — intentional Graham asymmetry) | EPS ≤ 0 → FAIL (P/E undefined); no quote/EPS → INSUFFICIENT |
| 2 | Liquidity | Current Ratio ≥ 1.50 | No classified balance sheet (banks/REITs/insurers/homebuilders) → NOT_APPLICABLE |
| 3 | Debt | Total Debt ≤ 1.10 × Net Current Assets | Total-debt rollup preferred; else long+short; missing debt → INSUFFICIENT unless assumed-zero (flagged) |
| 4 | Earnings stability | EPS > 0 in **each** of the past 5 fiscal years | All 5 consecutive years required; any gap → INSUFFICIENT (this is the criterion TTM blending hides — the reason aggregators are unusable) |
| 5 | Dividend | Currently pays | pays/None/False from §2.5 → PASS/INSUFFICIENT/FAIL |
| 7 | Tangible-asset valuation | Price ≤ 1.20 × TBVPS; TBV = A − L − goodwill − intangibles − preferred − **noncontrolling interest** | Missing goodwill/intangibles → INSUFFICIENT unless assumed; preferred defaults to 0 flagged; TBVPS ≤ 0 → FAIL |

**There is no criterion 6.** Graham's earnings-growth requirement compared the
latest year against a *fixed* calendar year — 1966, named in a book written in
1973. The text gives no rule for choosing that base in any other year, and the
candidate substitutes (a rolling point five years back, a prior cyclical peak, a
prior average, a prior high-water mark) each change what passing proves. Rather
than ship someone else's criterion under Graham's name, `evaluate()` returns the
comparison as a disclosure — `ScreenResult.eps_growth`: latest annual EPS beside
the best year 4–7 years earlier, with both fiscal years named. It appears in the
detail panel and in `/screen/enterprising/{ticker}`, and it can neither pass,
fail, nor make a company indeterminate. The numbering keeps its gap so that
criterion 7 still means what it has always meant.

**Verdict (§4.4):** any `INSUFFICIENT_DATA` → `INDETERMINATE` (never resolves to
PASS, never silently to FAIL); else any `FAIL` → `FAIL`; else any
`NOT_APPLICABLE` → `INDETERMINATE` (a screen that couldn't assess liquidity has
not screened the company); else `PASS`.

### 3.1 Where the price sits in its own history (`pricestats.py`)

Also disclosure, never criteria — the book has no rule about drawdowns. The
screen asks whether a price is low against the business; these ask whether the
market has already marked it down, and for how long. Computed from the weekly
series at export, exposed as `price_stats` on every dashboard row and on
`/screen/enterprising/{ticker}`.

| Field | Reading |
|---|---|
| `pct_below_52w_high` / `pct_below_3y_high` / `pct_below_5y_high` | magnitude of the decline over one, three and five years — a one-year fall can be noise, a three-year one usually is not |
| `pct_above_52w_low` | whether the price is still pinned to its depressed level or has begun to recover |
| `price_to_3y_median` | the same question without relying on a single possibly irrational peak |
| `drawdown_weeks` | weeks since the last week the price stood at its five-year best |

Three decisions worth knowing:

- **Weekly closes.** A "high" is the best weekly close, never an intraday spike.
- **The live quote is part of its own range.** Highs, lows and the drawdown clock
  all include today's price, so a stock making a new high reads 0% below it
  rather than a negative distance from a stale weekly close.
- **Price only — no multiples.** A P/E against its own history was built and then
  removed: the only EPS series available by date is the annual one, which would
  have put that P/E on a different basis from criterion 1's trailing twelve
  months (GHC read 17.9 one way, 9.6 the other). Two P/Es in one panel mislead
  more than the extra field informs. Earnings questions stay in the screen; this
  section answers what the market has done to the price. Rebuilding it honestly
  would mean a vintage TTM EPS series — a quarterly-by-filing-date reconstruction
  that does not exist here yet.

**Error-direction bias:** wherever ambiguity forces a choice, the system errs
toward FAIL/INDETERMINATE, never toward PASS — overlapping debt components
overstate debt, summed intangibles shrink TBV, missing data blocks rather than
defaults.

---

## 4. Gaps and limitations (found across 110 live tickers; details in FINDINGS.md)

### 4.1 Dimensional-only filers — the hard floor
XOM, V, BRK-B, HVT tag EPS (and GM/F their debt) **only with XBRL dimensions**,
which the companyfacts API strips. These screen honestly INSUFFICIENT.
The fix is a new source: SEC's Financial Statement Data Sets, whose `num.txt`
gained a `segments` column in Dec 2024 (bulk dimensional facts, no filing
parsing). Designed for v2, not built.

### 4.1b Japanese (and all foreign) issuers — findable, not screenable
A name sweep of SEC's ticker map found **39 Japanese issuers**: 15 file 20-F
with XBRL (TM, SONY, HMC, MUFG, SMFG, MFG, NMR, TAK, IX, NTTYY, HTHIY, KYOCF,
CAJPY, ATEYY, TKLF), 22 have **no XBRL data at all** (ADR shells: Marubeni,
Itochu, SoftBank, Seven & i, Shin-Etsu, Murata…), and 2 file 10-K.

The 20-F filers are rejected by design (§1.2 / §8.2 of the design doc), and the
data confirms the rejection is the honest call rather than mere policy:

- **IFRS taxonomy.** Facts live under `ifrs-full` (`CurrentAssets`,
  `DilutedEarningsLossPerShare`, `EquityAndLiabilities`), needing a parallel tag
  map. Goodwill is absent entirely for Toyota.
- **Currency mismatch.** Values are JPY (Toyota: assets ¥93.6 trillion, EPS
  ¥359.56) while the ADR price is USD — P/E and P/TBV need an FX source the
  service does not have.
- **ADR ratio, and it is not in XBRL.** Toyota reports 13.05B *ordinary* shares;
  one ADR represents 10 ordinary shares. Getting this wrong is a silent 10×
  error in both per-share criteria.
- **No interim reporting.** 20-F is annual; 6-K is unstructured. Toyota's newest
  structured data ends 2025-03-31 — ~17 months stale — so criterion 1's "current
  EPS" could not be current, and the TTM roll-forward is impossible.

Supporting Japan properly means FX + ADR-ratio sources, an IFRS tag map, and a
staleness policy — a scope expansion, not a patch. And the ADR universe is ~15
mega-caps: Japanese Graham value (sub-book small caps, net-nets) sits in the
~3,800 TSE listings that never file with the SEC at all. Reaching those needs
**EDINET** (Japan's FSA disclosure system, which publishes XBRL with a free
API), i.e. a second Layer-1 source — the natural home for a "Graham Japan"
variant if that is ever wanted.

### 4.2 Stopped-tagging unknowns
Concepts that disappear from filings (paid-off debt: ANF, WSM, MOV; goodwill
that stopped being presented: AAPL, COP, DVN, TOL) stay unknown even with the
opt-in — evidence of past existence blocks the assumption. A debt-specific
recency variant ("old debt facts + none fresh usually means repaid") would
unblock them at slightly higher risk; documented, deliberately not built.

### 4.3 The N/A cap silences whole sectors — decided: keep it
Unclassified-balance-sheet filers (banks, insurers, homebuilders) can never
reach overall PASS: LEN passes all five computable criteria at P/E 6.8, LNC
screens at P/E 3.8, both structurally INDETERMINATE. **Decision (external
review concurred): correct as-is.** A company whose liquidity and leverage
cannot be assessed is precisely what criteria 2–3 exist to catch; INDETERMINATE
is the honest answer. If those sectors are ever wanted, the right move is a
separate sector-appropriate screen, not waiving criteria 2–3.

### 4.4 Remaining known limitations
- **Custom-extension tagging** (~20% of tags on average, rising for small
  filers): debt held in a company-specific element with no standard trace would
  fool the assume-zero evidence scan; the interest-expense cross-check closes
  most of this hole.
- **TTM composite** mixes three periods' share counts (restatements ARE handled —
  every piece takes the latest-filed fact for its period); spin-offs and one-off
  charges make it spike legitimately (MRK −2.26 H1-26, HON +20.39 spin gains) —
  criterion 1 inherits Graham's cyclical peak-earnings risk (§8.7), the 5-year
  series is surfaced so the caller can judge.
- **Structural discontinuities** (bankruptcy, spin-offs, fiscal-year changes)
  are not detected (§5.6) — label handling survives them, comparability is the
  caller's judgment.
- **Genuine XBRL absences** exist: DELL's FY-ending-Jan-2022 EPS and RDDT's
  pre-IPO years were simply never filed as annual facts — INSUFFICIENT is
  correct, not a bug.
- **Filer tagging errors propagate** — provenance (accession + tag on every
  figure, `/fundamentals/{ticker}` for hand-checking) exists to diagnose them.
- **Yahoo quotes** are unofficial and delayed; the timestamp is disclosed, the
  provider is swappable.
- **Sequential batch**: a 50-ticker batch takes minutes (rate limit + no
  fan-out) — known, acceptable for v1.

### 4.5 Verification status — and the headline result
**Of 110 tickers live-screened, exactly zero reached overall PASS.** That is the
screen working as designed, not a defect: at 2026 valuations, the any-gap →
INDETERMINATE rule plus the N/A cap leaves the closest candidates at ASO (6/7),
LEN (5/5 computable), M, DDS, BKE. A mechanical Graham screen is *supposed* to
return nearly empty in an expensive market.

Verification base: 28/28 figures verified verbatim against actual filing
documents (AAPL, JPM, KO); TTM composites hand-verified (GOOGL, MU, OXY);
110 tickers live-screened across four campaigns; 10 findings from a multi-angle
code review plus 3 from an external design review fixed and re-verified
end-to-end; 62 unit tests, including every §7.1 fixture from the design doc
(hidden-loss-year, bank N/A, absent-goodwill, restated-year).
