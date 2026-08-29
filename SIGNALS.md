# Qualitative signals — extraction feasibility (2026-08-20)

Question asked: can the screener extract management-quality and business-quality
signals (serial acquisitions, financial-activity income, customer concentration,
CEO pay, option repricing, insider selling, moat, marathon-vs-sprint growth,
stated goals vs achievements, 8-K events, liquidation, deferred tax)?

Answer: **9 of 13 are extractable with primary-source provenance**, in three
tiers. Every number below was measured against the live cache (5,911 dashboard
companies, 20,236 cached `companyfacts` files) or a live SEC fetch — not
estimated. Percentages are share of the 800-company random dashboard sample
that files the tag at all.

Standing constraint that decides most of this: **Company Facts exposes only
dimension-free facts.** Anything reported per-customer, per-segment, per-award
or per-acquiree is invisible until the inline-XBRL adapter (TAGS.md §4.3
release 5).

Standing rule for anything landed from here: these are **disclosure signals,
never grades**. Criteria stay 1, 2, 3, 4, 5, 7. New findings belong in
`context_notes` / `earnings_quality`, the same shape v44/v49 established.

---

## Tier A — computable now, no new fetching

Data is already in the cache; the work is arithmetic in `normalize.py` +
`profiles.py` and a note in the payload.

### A1. Marathon vs sprint — **LANDED, engine v58**

Asked: "stable earnings 10 years > a spike in the last 1–2 years only."

`ch13.py` already computes exactly the inputs: `avg_recent` / `avg_middle` /
`avg_old` (3-year blocks), `growth_5y`, `growth_10y`, `max_decline`,
`ten_year_positive`, `stability_years`. Nothing to fetch. The missing piece is
one derived classifier over those numbers, e.g.:

- *marathon*: `ten_year_positive` = 10, `max_decline` small, `growth_10y` > 0
  and `growth_5y` ≈ `growth_10y` — the line rises in every block.
- *sprint*: `growth_5y` ≫ `growth_10y`, or latest FY ≫ `avg_middle` while
  `avg_middle` ≈ `avg_old` — flat decade, then a jump. ABT today:
  `avg_old` 2.01 → `avg_middle` 1.96 → `avg_recent` 4.87 is a textbook sprint
  shape that the dashboard currently does not name.

**What shipped.** `ch13.eps_stats` gained `growth_early` (the first half of the
record, which `growth_10y` could only report combined with the second),
`latest_vs_prior3` (the newest year against the three behind it) and `shape`.
Two shapes are named and everything else is left unnamed: **sprint** = the
recent block ≥ 50% above the middle one while the first half moved less than
10% either way; **marathon** = both halves up ≥ 10%, positive in all ten years,
worst single-year fall ≤ 40%. A first half that *declined* is deliberately not a
sprint — the rebound after a loss year is a return to where the company already
was, not new growth. `profiles.earnings_shape_note` turns the numbers into a
"Growth is recent" or "Steady record" note:

> ABT — Smoothed earnings ran $2.01 in FY2013–FY2015, $1.96 in FY2018–FY2020,
> $4.87 in FY2023–FY2025: −2% over the first half of the record and +148% over
> the second. Whatever this business is now, it became so recently.

Measured over the universe: **52 sprints** (CB, DUK, CSCO, ABT) and **394
marathons** (MSFT, GOOGL, JPM) out of the 2,677 companies whose record reaches
back the thirteen years a two-half comparison needs.

### A2. Income from financial activity — **free, today**

Asked: profit that comes from lending, investing and selling assets rather than
from operations.

| Tag | Files it |
|---|---|
| `OperatingIncomeLoss` | 78% (already read) |
| `NonoperatingIncomeExpense` | 47% |
| `OtherNonoperatingIncomeExpense` | 60% |
| `InvestmentIncomeInterest` | 39% |
| `GainLossOnInvestments` | 18% (already read as an earnings-quality gain) |
| `InterestExpense` | 62% |

Pre-tax income is already extracted for earnings-quality context. The measure is
`(pretax − operating income) ÷ pretax`: how much of the profit never came from
the business. Guard: a bank, insurer or BDC has no `OperatingIncomeLoss` by
construction — the existing `graham_profile` already separates them, so the
note fires only for OPERATING filers, exactly like the untaxed-profits signal.

`GainLossOnSaleOfSecurities`: 0/400 — dead tag, do not add.

### A3. Serial acquirer — **free, today, with one honest limit**

Asked: "buys too many other companies (> 2–3 per year)".

**Deal *count* is not extractable.** It lives on `BusinessAcquisitionAxis`
(dimension-qualified → dropped by Company Facts); `NumberOfBusinessesAcquired`
is filed by 3% of filers. Do not promise a count.

**Acquisition *cadence and size* are extractable:**

| Tag | Files it |
|---|---|
| `PaymentsToAcquireBusinessesNetOfCashAcquired` | 43% |
| `PaymentsToAcquireBusinessesGross` | 19% |
| `BusinessCombinationConsiderationTransferred1` | 13% |
| `GoodwillAcquiredDuringPeriod` | 33% |
| `Goodwill` (already read), `PaymentsToAcquirePropertyPlantAndEquipment` (**69.8%** — the 53% first measured here was over all cached filers, not the dashboard) | — |

Measured: of filers that report the cash-flow tag, the **median has positive
acquisition spend in 5 separate fiscal years**. Proposed disclosure: years-with-
acquisition-spend out of the last 10, cumulative acquisition spend vs
cumulative capex ("growth bought, not built"), and acquisition spend vs
operating cash flow. This pairs with the existing "Acquisition-only book" note
(ABT: goodwill + intangibles 53,096M > 52,061M of common equity), which is
already the balance-sheet end of the same story.

### A4. Deferred tax — **LANDED, engine v58**

| Tag | Files it |
|---|---|
| `DeferredTaxAssetsValuationAllowance` | 74% |
| `DeferredTaxAssetsGross` | 66% |
| `DeferredIncomeTaxExpenseBenefit` | 60% |
| `DeferredTaxAssetsOperatingLossCarryforwards` | 60% |
| `DeferredIncomeTaxLiabilitiesNet` | 36% |

Best coverage of anything on this page. Two readings worth surfacing:

1. **Valuation allowance ÷ gross DTA** — management's own signed statement that
   it does not expect enough future profit to use its tax assets. A high ratio
   beside reported profits is the contradiction Graham looked for.
2. **Deferred share of tax expense** — profit reported to shareholders that was
   not taxed in cash. Direct companion to the v49 untaxed-profits signal, and
   the mechanism behind it (the current v49 test sees only the total).

**What shipped** — 265 companies carry the allowance note, 194 the deferred-charge
note — and the two traps found in the data on the way:

- The allowance and the assets it reserves against must come from **one
  balance-sheet date**, and the allowance can never exceed them. Valaris tags a
  3,292M allowance beside a 1,368M "gross" deferred tax asset — the two tags are
  not describing one thing, so neither is reported. Biogen's gross tag stopped
  in 2021 while its allowance is current, so the base is rebuilt from the same
  filing's `DeferredTaxAssetsNet` + allowance (verified against KO and ABT,
  where gross − allowance equals the net tag to the dollar).
- Both notes fire only beside a **profitable** latest year: a loss-maker
  reserving its tax assets is doing the expected thing, and a company earning
  money while reserving is the contradiction Graham was reading for. The
  allowance must also be ≥ 10% of common equity — the same materiality gate the
  lease note uses.
- Deferred share of the charge ≥ 80%, and the deferred amount ≥ 10% of the
  year's earnings. DTE FY2025: an 88M charge of which 358M was deferred, so the
  current half was a **270M refund** — its own `CurrentIncomeTaxExpenseBenefit`
  confirms the derived figure exactly. KO's FY2025 (517M deferred inside a
  2,861M charge, 18%) is the counterexample fixture that keeps it quiet.

### A5. Option / SBC dilution — **partly free**

| Tag | Files it |
|---|---|
| `ShareBasedCompensation` (cash-flow add-back) | 75% |
| `AllocatedShareBasedCompensationExpense` | 63% |

Extractable: SBC ÷ revenue, SBC ÷ operating cash flow, SBC vs net income. The
5-year share-count drift note (v44) already covers the dilution end.

**Repricing itself is not extractable** — award-level modification data is
dimension-qualified and the disclosure that matters ("we lowered the strike
price after the stock fell") is proxy prose. See Tier C.

---

## Tier B — new source, structured and cheap

### B1. 8-K events — **LANDED, engine v58 (`make events`)**

`sync listing-age` (v43) already pulls
`https://data.sec.gov/submissions/CIK{cik}.json`. That same file carries an
`items` column for every 8-K. Verified live on AAPL: `"2.02,9.01"`,
`"5.02"` — machine-readable item codes, no document parsing.

Codes worth a note, in Graham order of severity:

| Item | Meaning |
|---|---|
| 4.02 | Non-reliance on previously issued financials — *the* restatement flag |
| 1.03 | Bankruptcy or receivership |
| 3.01 | Delisting notice / failure to satisfy a listing rule |
| 2.04 | Triggering events accelerating a debt obligation |
| 2.06 | Material impairment |
| 5.02 | Departure/appointment of directors and officers — churn is countable |
| 1.02 | Termination of a material definitive agreement |

Cost: one JSON per filer (the same one already fetched), plus the older-history
files it references (`CIK…-submissions-001.json`) when more than 1,000 recent
filings exist. This is the highest signal-per-byte item on the page.

**What shipped.** `make events` scans every dashboard company's filing index
into a `filing_event` table; `profiles.filing_event_notes` reads it at export.
Two item codes from the list above were **measured and dropped**: 5.02 (officer
departures) fires for 87% of a 200-company sample and cannot separate a
dismissal from an AGM election, and 1.02 (terminated agreements) fires for 38%
and cannot separate a lost customer from a refinanced credit line. An item
number is evidence; a guess about which kind of event it was is not.

Measured over the whole universe: 19,232 events, **2,165 of 5,911 companies
(36%) carry at least one note** — 1,451 listing deficiencies, 670 auditor-churn,
573 non-reliance, 215 debt accelerations, 185 impairments, 52 bankruptcies —
and 2,291 companies scan clean, which is an answer rather than a blank.

A full scan costs one request per company (~3.5 GB, about an hour, bandwidth-
bound). The obvious next optimisation is to harvest the same item numbers out of
the 1.6 GB `submissions.zip` that `make metadata` already downloads, making an
event refresh free for anyone running that job.

Three things the data forced:

- **The window is what the index can show.** The recent array holds a filer's
  last thousand filings — for Wells Fargo that is fourteen months, because Form
  4s crowd it out (3/200 companies were truncated inside five years). Each
  company stores `events_from`, and a note never claims a window wider than the
  scan covered.
- **Notes are bounded by the company's own newest balance sheet**, five years
  back from it, not by the wall clock — the same stored data always produces the
  same note.
- **Repeat filings about one auditor transition are collapsed** (within 90
  days): T-Mobile filed item 4.01 three weeks apart for a single change, so
  churn means ≥ 2 *separate* transitions, not ≥ 2 filings.

### B2. Insider selling — **quarterly bulk data set, same pattern as `dera.py`**

Form 4 XML parses cleanly (verified on an AAPL filing: owner name, officer/
director flag, `transactionCode`, shares, price, acquired/disposed), but the
per-filing route does not scale — AAPL alone filed 587 Form 4s inside its last
1,000 filings.

The scalable route already has a precedent in this repo. `sources/dera.py`
downloads a quarterly SEC zip and harvests it into per-CIK sidecars. SEC
publishes an insider data set in exactly that shape:

`https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip`
— verified live: **13.9 MB for 2026Q1**, covering every filer.

Contents verified:

- `SUBMISSION.tsv` — `ISSUERCIK` (joins straight to dashboard CIKs),
  `PERIOD_OF_REPORT`, and **`AFF10B5ONE`** — whether the trade ran under a
  pre-set 10b5-1 plan. This is the discriminator between routine scheduled
  selling and discretionary dumping; without it the signal is noise.
- `NONDERIV_TRANS.tsv` — `TRANS_CODE` (S sale, P open-market purchase, M option
  exercise, A award, F tax withholding), `TRANS_SHARES`,
  `TRANS_PRICEPERSHARE`, `TRANS_ACQUIRED_DISP_CD`, `SHRS_OWND_FOLWNG_TRANS`.
- `REPORTINGOWNER.tsv` — `RPTOWNER_RELATIONSHIP` (Officer / Director / 10%
  owner), `RPTOWNER_TITLE`.
- `DERIV_TRANS.tsv`, holdings, footnotes.

Measure: discretionary sales (code S, `AFF10B5ONE` false) by officers and
directors as a share of their holdings, over 4–8 quarters. ~14 MB × 20 quarters
= ~280 MB for five years of history, one-time.

### B3. CEO pay — **21% free today, 100% needs release 5**

Pay-versus-Performance is inline-XBRL-tagged in the proxy, and the SEC does
merge some of it into Company Facts under the `ecd` namespace. Measured on the
dashboard: **`ecd:PeoTotalCompAmt` present for 21%** (312/1500).

Verified values carry full provenance — `start`/`end`/`frame`, `form: DEF 14A`,
accession:

- JPM: PEO total comp 2023 $35.96M → 2024 $37.68M → 2025 $40.63M, while
  *compensation actually paid* runs $104M / $227M / $247M.
- DDOG: total $11.6M → $19.8M → $27.1M; actually paid up to $50.1M.

Note the gap between `PeoTotalCompAmt` and `PeoActuallyPaidCompAmt` — that gap
*is* the equity-award revaluation, and it is the closest machine-readable proxy
to the option question in A5.

The limit is real and lopsided: **MSFT, KO, AAPL and ABT have no `ecd` facts in
Company Facts at all**, so the 79% missing is not a small-filer tail. Full
coverage means reading the DEF 14A's inline XBRL directly — the release-5
adapter, not a new tag chain. Measures once landed: CEO total comp ÷ net
income, ÷ revenue, and its 3-year growth vs EPS growth.

---

## Tier C — needs document text; outside the current architecture

These have no dimension-free XBRL fact. Landing them means ingesting filing
documents and, for three of them, model judgement over prose — which cannot
carry a tag-level provenance row and so must live in a clearly separated,
never-graded layer.

### C1. Customer concentration — blocked by dimensions, not by absence

`ConcentrationRiskPercentage1` is filed by 10% of the dashboard, but the
dimension-free residue is unusable: sampled values are 0.14, 0.975, 1.0, 0.2,
0.69 with **no way to tell whether the axis was a customer, a supplier, a
geography or a product line**. `NumberOfMajorCustomers`: 0/400.

The real fact sits on `ConcentrationRiskByMajorCustomersAxis` in the filing's
inline XBRL, plus the "Concentrations" note in prose. Release 5 unlocks the
percentage honestly; the customer's *name* is prose only.

### C2. Moat / competitive advantage — no tag; quantitative proxies already exist

There is no XBRL concept for a moat, and there will not be one. What the
screener already computes as evidence *of* one:

- `owner_earnings.all_capex_return` — a conservative floor that deducts all capex;
  the separate maintenance≈D&A estimate is assumption-labelled.
- `peer_efficiency` (v49) — operating margin vs the median of the company's own
  industry; 527 companies materially behind.
- Gross margin (`GrossProfit`, 43%) stability across the 10-year series, and
  R&D intensity (`ResearchAndDevelopmentExpense`, 40%).

Sustained high returns across both owner-earnings estimates plus an above-median
margin are the numeric footprint of a moat.
The narrative ("why can nobody take this business") is prose.

### C3. Management goals vs actual achievements — largest build, weakest provenance

Requires the shareholder letter / MD&A of year N, the same section of year N+3,
and a judgement about whether what was promised happened. That is document
ingestion plus model comparison across years. It cannot produce a tag-and-
accession provenance row of the kind every figure on this dashboard carries; at
best it produces a quote pair with two accessions.

Recommendation: not until Tier A and B are landed, and then only as an
explicitly separate, explicitly non-graded panel.

### C4. "Does the company want to become a leader" / option repricing

Same class as C3: CD&A and strategy prose. Repricing has award-level tags but
they are dimension-qualified and the substance is the narrative.

### C5. Liquidation — partly Tier B after all

`NetAssetsInLiquidation`: **0/800 in the dashboard** — companies adopting
liquidation-basis accounting are gone from the screen by the time they file it,
so the tag will never appear here. The live signal is Tier B instead: 8-K item
1.03, and a `PREM14A`/`DEF 14A` carrying a plan of dissolution, both visible as
form types in the submissions index.

---

## Order

1. **A1 + A4 + B1 — DONE (engine v58).** Details above; impact in TAGS.md §4.3.
2. **A2 + A3 + A5** — non-operating income share, acquisition cadence, SBC
   intensity. Same engine bump shape as v44's context notes.
3. **B2** — insider selling; new quarterly harvest, but `dera.py` is the
   template and 14 MB/quarter is cheap.
4. **B3 partial** — CEO pay for the 21% that Company Facts already exposes,
   disclosed as partial coverage, with the rest deferred to release 5.
5. **C1** — customer concentration, as a release-5 rider.
6. **C2/C3/C4** — only after a deliberate decision to add a prose layer.

Per TAGS.md §4.2, none of it merges without a named real-company fixture, a
counterexample fixture, and provenance visible in the output.
