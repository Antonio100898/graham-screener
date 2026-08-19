# Tag Reference — What We Read, What We Calculate, and Why

Three sections: (1) every XBRL tag the screener reads today and the figure it
feeds, (2) the findings of the 2026-08-19 full-coverage audit (verified gaps,
defects, rejections), (3) a worked example from a real SEC filing (Coca-Cola)
showing raw tags → extracted facts → screened numbers.

Source of truth for section 1 is `api/screener/normalize.py`; this document
describes it, the code decides. All extraction shares four rules:

- **Missing is never zero.** A concept with no evidence stays INSUFFICIENT.
- **Latest-filed wins.** Restatements override: the same fiscal year from a
  newer accession replaces the older figure.
- **Staleness guard.** Instant (balance-sheet) facts more than 400 days older
  than the newest balance sheet are treated as missing — a filer that stopped
  reporting Goodwill in 2019 does not keep 2019 goodwill forever.
- **Provenance everywhere.** Every figure carries tag, form, accession and
  period end, so any number on the dashboard can be traced to one filing.

---

## 1. Tags we read now

### 1.1 Earnings per share → criteria 1 (P/E < 10), 4 (no deficit in 5 FY), P/E3, ch. 13 stats

We want Graham's earning power: a full annual EPS series plus a trailing-twelve-month
anchor. Annual figures come only from annual filings (340–400 day durations);
quarterly facts are never promoted to annual. TTM = latest FY + YTD − prior-YTD.

| Order | Tag | Note |
|---|---|---|
| 1 | `EarningsPerShareDiluted` | primary |
| 2 | `EarningsPerShareBasicAndDiluted` | small filers |
| 3–9 | `NetIncomeLossNetOfTaxPerOutstandingLimitedPartnershipUnitDiluted`, `NetIncomeLossPerOutstandingLimitedPartnershipUnitDiluted`, `…BasicNetOfTax` ×2, `NetIncomeLossPerOutstandingLimitedPartnershipUnit`, `NetIncomeLossPerLimitedPartnershipUnitDiluted`, `…Basic` | partnerships report per **unit**; without these the whole midstream sector had no EPS |
| fill | `EarningsPerShareBasic`, `IncomeLossFromContinuingOperationsPerBasicShare` | last resort, per missing year only; basic ≥ diluted so it flatters slightly — disclosed |
| split-guard | `IncomeLossFromContinuingOperationsPerDilutedShare` | continuing-ops cross-check |

Split detection: unexplained year-over-year ratios near 1.5–100× against the
weighted-share tags (`WeightedAverageNumberOfDilutedSharesOutstanding` + 4
variants) mark a split and rescale history rather than reporting a fake collapse.

### 1.2 Net income, revenue, operating income → size test, ch. 13, earnings quality

| Concept | Tags (chain order) | Why |
|---|---|---|
| Net income | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` | carried beside EPS because buybacks can grow EPS while earnings fall |
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`, `SalesRevenueGoodsNet`, `SalesRevenueServicesNet`, then sector top lines: `RegulatedAndUnregulatedOperatingRevenue`, `OperatingLeaseLeaseIncome`, `OperatingLeasesIncomeStatementLeaseRevenue`, `RealEstateRevenueNet`, `RevenuesNetOfInterestExpense`, `InterestAndDividendIncomeOperating`, `PremiumsEarnedNet` | ASC 606 (2018) switched most filers mid-history, so selection is recency-first with per-year fill; sector lines exist because a REIT's generic `Revenues` can be a $13M scrap beside $1.5B of lease income |
| Operating income | `OperatingIncomeLoss` | defensive size context; banks/insurers have no such subtotal — stays absent |

### 1.3 Balance sheet → criteria 2 (CR ≥ 1.5), 3 (debt ≤ 1.1× NCA), 7 (price < 1.2× TBVPS), NCAV

We want the classified balance sheet Graham's industrial tests assume. A filer
with no `AssetsCurrent`/`LiabilitiesCurrent` (banks, insurers, REITs) is
NOT_APPLICABLE for 2–3 — that is an answer, not a gap.

| Concept | Tags | Rule |
|---|---|---|
| Total assets | `Assets`, `LiabilitiesAndStockholdersEquity` | the identity substitute also anchors the staleness clock |
| Total liabilities | `Liabilities`, else derived `LiabilitiesAndStockholdersEquity − StockholdersEquity(IncludingNCI)` | derivation requires identical period ends; parent-only equity flagged so NCI is not subtracted twice |
| Current assets / liabilities | `AssetsCurrent` / `LiabilitiesCurrent` | single-tag reads on purpose — summing incomplete components would overstate the current ratio (false-PASS direction) |
| Goodwill | `Goodwill` | subtracted for tangible book |
| Intangibles | `IntangibleAssetsNetExcludingGoodwill`, else `FiniteLivedIntangibleAssetsNet` + `IndefiniteLivedIntangibleAssetsExcludingGoodwill`, else `OtherIntangibleAssetsNet` | subtracted for tangible book; overstating the deduction is the conservative direction |
| Combined line | `IntangibleAssetsNetIncludingGoodwill` | only when both slots above are empty; fills intangibles and sets goodwill to an explicit zero whose provenance names the combined line |
| Preferred stock | `PreferredStockLiquidationPreferenceValue`, `PreferredStockValue`, `PreferredStockValueOutstanding` | liquidation preference first — the par tag rots (JPM's is stale since 2009); missing preferred defaults to 0 **with a disclosure note** |
| Noncontrolling interest | `MinorityInterest` + `RedeemableNoncontrollingInterestEquityCarryingAmount` (summed) | A − L is equity incl. NCI; the minority share is not the common's |
| Shares outstanding | `CommonStockSharesOutstanding`, else `dei:EntityCommonStockSharesOutstanding`, else weighted-average tags | sanity-voted against implied NI/EPS shares — one number divides NCAV, TBV and market cap |

Tangible book = assets − liabilities − goodwill − intangibles − preferred − NCI.
NCAV/share = (current assets − total liabilities − preferred) / shares.

### 1.4 Debt → criterion 3

We want borrowed money (finance leases count, operating rentals do not).
Overstating debt is conservative; double counting is still wrong.

| Bucket | Tags |
|---|---|
| Total (preferred) | `DebtLongtermAndShorttermCombinedAmount`, `DebtAndCapitalLeaseObligations` |
| Long, primary chain | `LongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligations`, `LongTermNotesPayable`, `LongTermDebt` |
| Long, additive parts | `OtherLongTermDebtNoncurrent` (only when primary absent), `JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent`, `FinanceLeaseLiabilityNoncurrent` (skipped when the primary already contains leases) |
| Short, rollup | `DebtCurrent` (terminates the bucket) |
| Short, parts | `LongTermDebtCurrent` / `LongTermDebtAndCapitalLeaseObligationsCurrent` / `UnsecuredDebtCurrent` (skipped when the long bucket already holds current maturities), `ShortTermBorrowings` / `CommercialPaper`, `FinanceLeaseLiabilityCurrent` |
| Evidence only | regex over the filer's whole history (`debt|borrowing|notespayable|…`) + `InterestExpenseDebt` family — gates `assume_absent_zero`: debt may be assumed 0 only when nothing debt-shaped ever carried ≥ $1M |

### 1.5 Dividends → criterion 5 ("currently pays"), defensive 20-year record

| Order | Tag | Unit |
|---|---|---|
| 1–3 | `PaymentsOfDividendsCommonStock`, `DividendsCommonStockCash`, `DividendsCommonStock` | USD |
| 4–5 | `CommonStockDividendsPerShareDeclared`, `CommonStockDividendsPerShareCashPaid` | USD/share |
| 6–8 | `PaymentsOfDividends`, `DividendsCash`, `Dividends` | USD aggregates — may include preferred/NCI, so provenance labels them and criterion 5 discloses it |

"Currently pays": the newest positive fact must end within its own period length
+ 60 days of the balance-sheet date — a suspended quarterly payer fails within
about two quarters, an annual tagger is not false-failed. If the chain misses but
*any* other dividend-named tag has a recent positive value, the answer is
**unknown**, never FAIL. The per-year record (calendar years with a positive
fact) feeds the defensive dividend test and the windowed short-history variant.

### 1.6 Owner earnings / ROIC (context metrics, not Graham criteria)

| Concept | Tags |
|---|---|
| Pre-tax income | `IncomeLossFromContinuingOperationsBeforeIncomeTaxes…` (3 variants — see audit finding on the Domestic fragment) |
| D&A | `DepreciationDepletionAndAmortization`, `DepreciationAmortizationAndAccretionNet`, `DepreciationAndAmortization`, else `Depreciation` + `AmortizationOfIntangibleAssets` |
| Tax | `IncomeTaxExpenseBenefit` |
| Capex | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`, `PaymentsForCapitalImprovements` |
| Cash & investments (netted from invested capital) | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`; `ShortTermInvestments`, `AvailableForSaleSecuritiesCurrent`, `MarketableSecuritiesCurrent`, `OtherShortTermInvestments` |

### 1.7 Earnings-quality notes → criterion 1 disclosure

Non-cash / non-recurring lines large enough (≥ 10% of pre-tax) to distort the
P/E get a note, never an adjustment: `InventoryLIFOReserveEffectOnIncomeNet`,
`AssetImpairmentCharges`, `GoodwillImpairmentLoss`, `RestructuringCharges`,
`InventoryWriteDown`, `BusinessCombinationAcquisitionRelatedCosts`.

### 1.8 What is *calculated* from these

| Output | Formula | Where settled |
|---|---|---|
| C1 P/E | price / TTM EPS, PASS < 10.0 | at export (`sync.apply_price`), mirrored in `web/src/screen.js` |
| C2 current ratio | CA / CL, PASS ≥ 1.50 | engine |
| C3 debt load | total debt / (CA − CL), PASS ≤ 1.10 | engine |
| C4 stability | min EPS of last 5 FY ≥ 0 | engine |
| C5 dividend | pays now (yield shown when price sane) | engine + price |
| C7 tangible valuation | price / TBVPS, PASS < 1.20 | at export, mirrored client-side |
| P/E3, ch. 13 stats | 3-year smoothed averages, 5/10-year growth, max decline, 10-year positive years | `ch13.py` / `profiles.py` |
| Defensive tests | size, financial position, stability 10y, dividend 20y, growth ≥ 33⅓%/decade, valuation ≤ 15 / 22.5 | `profiles.py` (windowed for post-2011 listings) |

---

## 2. Audit findings — 2026-08-19 (release 1 of §4.3 implemented at engine v37; §2.2 tag additions still pending)

Full report: the "XBRL Tag Coverage Audit" artifact. Method: tag inventory over
all 5,903 dashboard companies (4,888 live tags), 8 domain classifiers + 8
adversarial verifiers sampling raw cached filings + 1 synthesis. 84 proposals,
17 rejected. Estimated impact if landed: **~2,000 companies (~34%) gain at
least one missing concept**.

### 2.1 Defects in what we read today

1. **Stale-zero selection** — debt chains take the *first* tag with any fresh
   entry, not the latest period end. SRI is scored debt-free on a stale zero;
   BridgeBio 0 → $2,652.9M. Fix: latest-period-end-wins, chain order as tiebreak.
2. **`exclude_ltd_current` string match** — only `us-gaap:LongTermDebt`
   suppresses its current portion; any combined tag double counts (Boeing $111M).
   Fix: suppression registry.
3. **`LongTermNotesPayable` mis-ranked** — a component ranked above the
   `LongTermDebt` rollup; when it wins, siblings are skipped (41 companies understated).
4. **Derived-liabilities double subtraction** — when L = LSE − SEI, redeemable
   NCI is inside derived liabilities *and* subtracted again (~31 filers: CMCSA, ACN, ADM).
5. **`parent_only_derivation` is a provenance-string `endswith`** — breaks
   silently when the derivation chain grows; needs a structured flag.
6. **`PRETAX_INCOME_TAGS` ends in the `…Domestic` fragment** — understates
   multinationals' pre-tax income.
7. **D&A part-sum provenance** names one tag of a two-tag sum; year filter drops
   amortization-only years.
8. **Per-share dividend detection by `startswith`** — blocks every per-unit
   distribution tag; would mis-scale catastrophically if one were added naively.
9. **`_weighted_shares` hardcodes the diluted tag** — basic-only filers (TR,
   UHAL) get no share count although the tuple has the fallbacks.
10. **`_intangibles` never consults `OtherIntangibleAssetsNet` when the parts
    sum exists** — HBAN understated $758M (MSRs).
11. **Series gap-fill without disclosure** — a `ProfitLoss`-filled year sits on
    a different NCI scope than its neighbours, silently.
12. **Debt evidence has no recency bound** — one $1M entry from 2012 blocks
    `assume_absent_zero` forever.

### 2.2 Verified missing tags (accepted, with the guards verification added)

- **Debt (700–900 companies gain a figure).** Fallback families for the
  primary-is-None branch: finance leases (`FinanceLeaseLiability` combined —
  must suppress its Current twin), convertibles (`ConvertibleDebtNoncurrent` →
  `ConvertibleLongTermNotesPayable` → `ConvertibleDebt` → `ConvertibleNotesPayable`;
  DDOG $985M / SNOW $2.28B / DXCM $1.24B are invisible today), notes/loans
  (`NotesAndLoansPayable` parent wins, else `NotesPayable` + `LoansPayable`;
  Realty Income $27.9B has no rollup), credit lines (`LongTermLineOfCredit` →
  `LineOfCredit`), `LongTermLoansPayable`, `SeniorLongTermNotes` (suppressed
  under the notes group — CAG's equals the whole rollup), secured debt as
  **max(family sum, secured)** — never both, never skip-if-present (AVA would
  be 900× understated). Short bucket: `NotesPayableCurrent` (dedupe against
  commercial paper — ED's is the same $869M), convertible-current family,
  `LinesOfCreditCurrent` + `LoansPayableCurrent` + notes-current family only
  when the LTD-current rollups are absent (MELI's child equals the rollup),
  `ShortTermBankLoansAndNotesPayable` terminates the borrowings slot (KEY would
  double to $7.4B), `OtherShortTermBorrowings` summed with CP (KO files both,
  disjoint). Evidence regex gains `seniornotes|subordinatednotes|mediumtermnotes|federalhomeloan|federalfundspurchased|bankoverdraft`.
- **Mezzanine equity (~440 filers).** New temporary-equity deduction:
  `TemporaryEquityCarryingAmountAttributableToParent` (GTN: $600M = 28% of
  equity invisible), gated on preferred returning nothing *or zero* (KDP tags
  $0 preferred beside $4.4B mezzanine) and skipped in the derived-liabilities
  path; incl-NCI and liquidation-preference variants chain behind it.
- **MLP equity & NCI.** Liabilities derivation via
  `PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest` →
  `PartnersCapital` (PAA's `Liabilities` is stale since 2011; unlocks EPD, ET);
  permanent-NCI alternatives `NonredeemableNoncontrollingInterest` (MS $1.1B
  missed since 2012), `MinorityInterestInOperatingPartnerships`,
  `PartnersCapitalAttributableToNoncontrollingInterest`; redeemable-NCI
  components summed only when the total is absent; fair-value variant last.
- **Shares.** Walk `_WEIGHTED_SHARE_TAGS` (fixes defect 9);
  `WeightedAverageLimitedPartnershipUnitsOutstandingDiluted` (true totals at
  ET/EPD/BSM); `SharesOutstanding` only *after* the dei cover;
  `LimitedPartnersCapitalAccountUnitsOutstanding` gated on partnership equity
  present + no stockholders equity (MAA's OP-unit fragment is 2.5% of the real
  count).
- **Dividends/distributions.** After the per-share-flag fix:
  `DistributionMadeToLimitedPartnerCashDistributionsPaid` and `…PaidPerUnit`
  (ends false FAILs at EPD/MPLX/UAN), `InvestmentCompanyDistributionToShareholdersPerShare`
  before the USD amount tag (MAIN's amount tag holds fragments),
  `PaymentsOfOrdinaryDividends`, `PartnersCapitalAccountDistributions`
  (aggregate label — includes GP/IDR). Evidence scan widened to
  `/dividend|distribut/` with tightened exclusions, so distribution payers land
  unknown rather than FAIL and true non-payers can finally FAIL cleanly.
- **Intangibles.** max-merge of Other vs parts (fixes defect 10);
  indefinite-lived class tags (`IndefiniteLivedTradeNames`, `…Trademarks`,
  `…LicenseAgreements`, `OtherIndefiniteLivedIntangibleAssets` — VZ ~$158B
  spectrum, KO $12.5B trademarks); derivations with same-period-end + ≥ 0
  guards: combined − goodwill, combined − excluding (goodwill slot), gross −
  accumulated (BBY would be 96× overstated without the period guard),
  `GoodwillGross` − impairment; MSR servicing assets (sum both measurement
  books — WFC carries both); `CapitalizedComputerSoftwareNet` as disclosed last
  resort.
- **Financial-sector income (~150 companies).** Revenue:
  `GrossInvestmentIncomeOperating` → `InterestIncomeOperating` (SYF $22.6B has
  no revenue series today; ARCC/BXSL likewise). EPS:
  `InvestmentCompanyInvestmentIncomeLossFromOperationsPerShare` (equals diluted
  EPS at BXSL four years straight).
- **Working capital & quality.** AFS successors
  (`AvailableForSaleSecuritiesDebtSecuritiesCurrent`,
  `DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent`,
  `HeldToMaturitySecuritiesCurrent`) go **end of chain** (PFE fragment trap);
  drop dead `AvailableForSaleSecuritiesCurrent`; restricted-cash netting
  against the restricted-inclusive rollup only. Earnings-quality: intangibles
  impairment components with presence-gating (GIS files three overlapping
  rollups), a new gain-signed tuple (`GainLossOnInvestments`,
  `UnrealizedGainLossOnInvestments`, `GainLossOnSaleOfPropertyPlantEquipment`,
  `GainLossOnDispositionOfAssets1`) closing the one-time-gain blind spot,
  `FairValueAdjustmentOfWarrants` magnitude-only. Capex:
  `SegmentExpenditureAdditionToLongLivedAssets` fills missing years only.

### 2.3 Rejected — and why the rejections matter

| Rejected | Reason |
|---|---|
| `CommonStockSharesIssued`, `SharesIssued`, treasury math | fragments fire exactly when no cross-check exists → per-share values inflated 3–1000× (false-bargain direction) |
| Interest-expense debt evidence | revokes correct zero-debt grades (LULU, Chewy, TPL) |
| Up-C distribution tags (`PaymentsOfCapitalDistribution`, LLC-member variant) | payouts to NCI holders only — would mark GLXY/SDHC non-payers as paying |
| `DebtInstrumentCarryingAmount` | per-instrument fragment posing as a total |
| `OtherBorrowings` | bank-only cohort, no classified-balance-sheet rescue |
| Component-summed `AssetsCurrent`/`LiabilitiesCurrent` | 6 of 7,179 filers would benefit; incomplete sums overstate CR (false PASS) |
| Composed bank revenue (NII + noninterest) | stale parts at 4 of 5 named banks |
| NCI net-income pairing | ~4 immaterial fixes |
| Dropping the junior-subordinated debenture tag | inventory said dead; Dillard's files it fresh ($200M) — never drop a read tag on counts alone |

### 2.4 Deliberately out of scope

Cash-flow-statement totals (no criterion consumes OCF; owner earnings is built
from parts with provenance on purpose) and the ASC 842 operating-lease family
(rentals are not borrowed money under criterion 3; the current portion already
sits inside `LiabilitiesCurrent`). Trap tags documented as never-fallbacks:
`AssetsFairValueDisclosure`, `LiabilitiesFairValueDisclosure`, `NoncurrentAssets`.

---

## 3. Worked example — The Coca-Cola Company (KO, CIK 0000021344)

Everything below is real extracted data. Primary filings: FY2025 10-K
(accession `0001628280-26-010047`, filed 2026-02-20) and Q1-2026 10-Q
(accession `0001628280-26-028802`, balance sheet dated 2026-04-03).

### 3.1 Raw tags → facts (with provenance)

| Concept | Tag that won | Value | From |
|---|---|---|---|
| Total assets | `us-gaap:Assets` | $104,217M | 10-Q `…-028802`, end 2026-04-03 |
| Total liabilities | derived: `LiabilitiesAndStockholdersEquity` − `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` | $68,483M | same 10-Q — KO tags no `Liabilities` total; the accounting identity fills it, same period end required |
| Current assets | `us-gaap:AssetsCurrent` | $30,390M | same 10-Q |
| Current liabilities | `us-gaap:LiabilitiesCurrent` | $22,378M | same 10-Q |
| Goodwill | `us-gaap:Goodwill` | $15,411M | same 10-Q |
| Intangibles | — | **MISSING** | see 3.3 — this is audit finding territory |
| Noncontrolling interest | `us-gaap:MinorityInterest` | $2,101M | same 10-Q |
| Long-term debt | `us-gaap:LongTermDebtAndCapitalLeaseObligations` | $39,065M | same 10-Q |
| Short-term debt | `us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent` + `us-gaap:CommercialPaper` | $4,743M | summed parts, provenance names both tags |
| Shares outstanding | `dei:EntityCommonStockSharesOutstanding` | 4,302,482,418 | 10-Q cover, 2026-04-28 — the gaap share tag was absent/stale, the dei cover is the fallback |
| Dividend (latest period) | `us-gaap:DividendsCommonStockCash` | $2,280M | Q1-2026 duration fact |
| FY2025 diluted EPS | `us-gaap:EarningsPerShareDiluted` | $3.04 | 10-K `…-010047`, period 2025-01-01 → 2025-12-31 |

### 3.2 Facts → calculated figures

- **TTM EPS = 3.18** — FY2025 (3.04) + Q1-2026 YTD (0.91) − Q1-2025 YTD (0.77).
  Three input facts, each with its own provenance row.
- **Annual EPS series** (last 5 of 10+): 2021 2.25 · 2022 2.19 · 2023 2.47 ·
  2024 2.46 · 2025 3.04 → **criterion 4 PASS** (minimum 2.19 ≥ 0).
- **Chapter 13 stats**: avg(2023–25) = 2.66 vs avg(2013–15) = 1.72 →
  **10-year growth +54.2%** (≥ 33⅓% → defensive growth PASS); 10 of 10 years
  positive → stability PASS.
- **Current ratio = 30,390 / 22,378 = 1.36** → **criterion 2 FAIL** (< 1.50).
- **Total debt = 39,065 + 4,743 = $43,808M**; net current assets =
  30,390 − 22,378 = $8,012M → **debt / NCA = 5.47** → **criterion 3 FAIL** (> 1.10).
- **Dividend record**: positive common-dividend facts in every calendar year
  2007–2026, streak from 2007, 20 paid years → **criterion 5 PASS** and the
  defensive 20-year test PASS — the XBRL record itself just barely proves 20 years.
- **Criterion 1** at price $88.82: P/E = 88.82 / 3.18 = **27.9 → FAIL** (≥ 10).
- **Book value/share** = (104,217 − 68,483 − 2,101) / 4,302.5M = **$7.82**.

### 3.3 Where the audit shows up in this very company

- **Criterion 7 is INSUFFICIENT for KO** — `missing: intangibles`. KO files no
  `IntangibleAssetsNetExcludingGoodwill` (or finite/indefinite rollup) at all;
  its trademarks live in the class tag **`IndefiniteLivedTrademarks`:
  $12,463M at 2026-04-03** — exactly the indefinite-lived class family in
  audit section 2.2. The moment that class-tag fallback lands, KO's tangible
  book becomes computable:
  104,217 − 68,483 − 15,411 − 12,463 − 2,101 ≈ $5,759M → TBVPS ≈ $1.34, and
  criterion 7 would grade (price 88.82 ≫ 1.20 × 1.34 → FAIL, honestly, instead
  of "insufficient").
- KO also files `OtherShortTermBorrowings` beside `CommercialPaper` as disjoint
  face lines — the exact short-bucket pair verified in the debt findings.
- KO appears in the *evidence-only* deferred-tax noise family
  (`DeferredTaxAssetsGoodwillAndIntangibleAssets`) — a tag that must count as
  evidence that intangibles exist, but never as a value.

**Verdict today**: 2 of 6 PASS, engine verdict FAIL (measured FAILs on 1, 2, 3
outrank the intangibles gap) — Graham's cheap-and-sturdy test working as
intended on a great-but-expensive business; the audit's only change for KO
would be turning criterion 7's "insufficient" into an honest FAIL.

### 3.4 Validation across ten more filers (2026-08-19)

Same extraction, ten deliberately different profiles. "✓" = concept extracted
with correct provenance; "—" = correctly absent/N-A; "✗" = a gap this document
predicts.

| Ticker | Profile | Extraction result | Audit finding it confirms |
|---|---|---|---|
| MSFT | mega-cap operating | everything ✓ (debt summed `LongTermDebtCurrent`+`CommercialPaper`, intangibles via finite tag) | control case — clean filer needs no fallbacks |
| PPC | special dividend | everything ✓; record shows 3 paid years, streak from 2025 | the 29% "yield" is one-off specials; record data already exposes it |
| EPD | MLP | liabilities **✗ MISSING** (no `Liabilities`, derivation needs `StockholdersEquity` which an LP lacks); dividend **✗ unknown** while paying billions | PartnersCapital derivation + distribution tags (§2.2) |
| ARCC | BDC | classified BS — correctly N/A for 2–3; EPS/dividend present | see new finding ① below |
| JPM | bank | preferred $21.2B via liquidation preference ✓; N/A for 2–3 ✓; $6.00/sh dividend via per-share tag ✓; 20-year record just provable | preferred chain and financial-profile handling work |
| DDOG | convertible SaaS | long **and** short debt **✗ MISSING** despite $985.5M converts → criterion 3 INSUFFICIENT; shares via weighted-average fallback | convertible family (§2.2) |
| GTN | mezzanine | preferred **✗ MISSING** while $600M redeemable preferred sits in temporary equity → tangible book overstated 28% | temporary-equity slot (§2.2) |
| LEVI | 2019 IPO | windowed tests fired: stability over 9-year record, growth −1.2% vs scaled 18.8% → honest FAIL, dividend record actually reaches to 2009 (pre-IPO years disclosed in IPO-era filings) | windowing works; XBRL can predate listing |
| DUK | utility | derived liabilities ✓, debt incl. finance leases ✓, $4.24/sh dividend ✓ | utility profile clean |
| SRI | stale-zero case | **✗ long-term debt = 0 from a 2025-09-30 filing while the balance sheet is 2026-06-30 → criterion 3 PASSES today on a stale zero** (the revolver — `LongTermDebt` $180.9M at FY25 = `LongTermLineOfCredit`, $151.1M at 2026-06-30 — is invisible) | defect §2.1-1, live and worse than stated: not merely unscored, a false PASS |

**New findings from this test:**

1. **Windowed-tests false positive for late tag adopters.** ARCC's EPS series
   starts in FY2020 — because BDCs only began filing the per-share element
   then, not because the company listed then (ARCC IPO'd 2004). The
   short-history heuristic (record starts after 2011 ⇒ young company) reads
   this as a 6-year-old company and grants windowed stability/dividend passes
   whose notes say "the company's public record" — factually wrong for ARCC.
   Concern: any filer that adopted its EPS tag late gets the same misread.
   XBRL facts cannot fix this — ARCC's earliest fact of any kind is
   2012-12-31, still past the 2011 floor. Corroborating listing age needs the
   EDGAR submissions index (ARCC's filings reach back to 2004), which the
   screener does not currently fetch.
2. **SRI's false PASS on criterion 3** upgrades audit defect №1 from
   "understated debt" to "wrong verdict shipped today": CA−CL = $162M net
   current assets against a stale-zero debt figure passes the 1.10× test while
   the ~$151M revolver balance goes uncounted. (Verified: SRI's
   `LongTermLineOfCredit` at FY25 exactly equals its `LongTermDebt` — one
   facility under two names, so the fix is latest-period-end selection plus
   the LOC family, counted once.)

---

## 4. Independent review outcome (2026-08-19)

An external review checked this document against `normalize.py`, the dashboard
output, and the KO cache. Verdict and consequences:

### 4.1 What the review confirmed

- **All 12 chain defects in §2.1** were independently confirmed against the
  current code (stale-zero selection, string-matched `exclude_ltd_current`,
  `LongTermNotesPayable` mis-rank, provenance-string `parent_only_derivation`,
  domestic pre-tax fragment, D&A provenance/year loss, `startswith` per-share
  detection, hardcoded weighted-share tag, `OtherIntangibleAssetsNet` ordering,
  undisclosed scope-switch gap-fill, unbounded debt evidence).
- **The KO example reconciles line by line** (P/E 27.9, CR 1.36, BVPS $7.82,
  `IndefiniteLivedTrademarks` $12,463M present while every read intangibles tag
  is absent). The review highlighted its policy value: broader intangible
  coverage converts an unknown into a correct **fail**, not a cheaper stock.
- Five predicted gaps were also replicated live in §3.4 (SRI, DDOG, GTN, EPD,
  KO). The **~2,000-companies-gaining estimate remains an unreplicated
  hypothesis** — treat it as such until a census rerun.

### 4.2 Merge rule adopted

No proposed tag is implemented without:
1. a named real-company **regression fixture** with the expected value,
2. a **counterexample fixture** proving no double count / fragment selection,
3. **provenance visible** in the output.

Coverage growth alone is never a merge reason. The §2.3 rejection table is a
**permanent never-fallback registry** — tags listed there must not be re-proposed
without new evidence overturning the recorded counterexample.

### 4.3 Release order

| Release | Content |
|---|---|
| 1 | **DONE — engine v37 (2026-08-19).** Debt precedence (latest-period-end wins across the chain), current-debt suppression registry, parent-scope flag on derived liabilities, D&A part-sum provenance + amortization-only years, weighted-share tuple walk, unit-based per-share dividend detection. Two additions found during verification: a combined-debt rollup older than the parts is dropped (SRI's stale $0.9M rollup was beating the fresh $180.9M parts and criterion 3 preferred it), and negative net current assets settle criterion 3 as FAIL even with debt parts missing. Result vs v35: SRI's false PASS is gone; 737 companies moved INSUFFICIENT→FAIL on the negative-NCA rule; 10 stale-data PASSes became honest INSUFFICIENT; 24 basic-only filers (UHAL, TR…) gained share counts. 156 pytest + 22 node fixtures green. |
| 2 | **DONE — engine v38 (2026-08-19).** All verified §2.2 families, 48 named fixtures (202 pytest total). Result vs v37: **726 companies gained long-term debt** (convertibles/notes/LOC/secured-max — DDOG 0 → $985.5M); **115 gained tangible book** (KO → $1.34/share exactly as §3.3 predicted; MCD, WFC, LNC via class tags/derivations/MSRs; GTN's FCC licenses honestly sink it to −$61/share); **criterion 5 fixed for MLPs** (EPD/MPLX → PASS; 80 true non-payers finally FAIL via widened evidence); **85 financials gained revenue** (SYF $22.65B, ARCC $3.08B), **34 BDCs gained EPS** (PNNT, PFLT, GBTC); **5 partnerships gained share counts** (SUN, BSM, KRP); mezzanine equity now deducted (GTN $600M). |
| 2.5 | **DONE — `make verify-coverage` (2026-08-19).** `api/screener/coverage.py`: 30 companies (all §3.4/fixture pins + sector strata), significance floor 0.3% of assets. Sweep classifies every material recent tag as consumed / chain-known / registry-out-of-scope (~90 reasoned families) / gap; identity layer checks A−L−mezzanine vs tagged equity and NI/EPS vs the share count. First full run: **PASS with 27/30 companies fully clean and 10 tracked release-3 candidates** — 7 unread debt-side rollups (`LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities` JPM $460B, `LongTermNotesAndLoans` TEVA $16.8B, `SeniorNotes` SYF, `OtherLoansPayable`, `WarehouseAgreementBorrowings`, `JuniorSubordinatedNotes`, `LiabilitiesNoncurrent`-derivation) and 3 identity catches: **dual-class share counts are single-class fragments at HEI (~55M of ~141M — per-share values overstated 2.5×), GTN and SUN**. New gaps or new identity mismatches fail the run. Original spec: 50–100 companies stratified across profiles (operating, utility, bank, insurer, REIT, MLP, BDC, young listing, microcap) plus every §3.4 known-hard case as a permanent fixture. Three layers: (a) *completeness sweep*, automatic — material facts in companyfacts minus facts the snapshot consumed; every leftover tag must classify as covered-by-rollup / registry-out-of-scope / **gap**, and the gap bucket must be empty; (b) *statement reconciliation*, automatic — UI numbers against the filing's own rollups via identities (A = L + E, CA + noncurrent = A, debt buckets vs filing totals, equity − goodwill − intangibles = TBV, EPS × shares ≈ NI) to catch double counts and fragment picks, not just misses; (c) *human-only residue*, flagged never extracted — prose disclosures (commitments, guarantees, covenants, legal ranges, "special" dividend labels): the harness links the section, a human reads it. Runs on every engine bump. Limit until release 5: proves completeness of what Company Facts exposes — dimension-qualified and some issuer-extension facts stay out of reach. |
| 3a | **DONE — engine v39 (2026-08-19).** All 10 harness candidates: dual-class share counts fixed by a two-witness fragment rule (an instant disagreeing >1.5× with two agreeing independent counts is the fragment; earnings arithmetic serves as the third witness in two-source cases) — HEI 55M → 141M, plus 20 more corrections all verified against real market caps (EMN, JACK, EG, PSN…); a fragile-source veto retires uncorroborated LP-unit instants when NI/EPS disagrees 2× (SUN: missing beats wrong); GTN's mismatch diagnosed as preferred-dividend scope, count verified correct. Debt: `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities` in the TotalDebt chain (JPM $460.5B), `LongTermNotesAndLoans`, combined `SeniorNotes` with its own current-suppression key, `OtherLoansPayable`, `WarehouseAgreementBorrowings`, `JuniorSubordinatedNotes`, and `LiabilitiesCurrent` derived from the noncurrent split. Harness: **30/30 companies clean, PASS**. 210 pytest + 22 node. |
| 3b | **DONE — engine v40 (2026-08-19).** Every dashboard row carries `sources` (14 balance-sheet figures × tag · form · accession · period end · filed date) and `series_mix` (which tag served which years, only when a series switched tags — 3,159 companies disclose one, mostly the ASC 606 revenue migration). Detail panel gains a "Data provenance" section — every figure links to its exact EDGAR filing — and a scope-switch warning under the annual history. Verified rendering in a headless browser (zero console errors). Payload 25.8 → 33.7 MB raw (~5 MB gzipped). |
| 3c | **DONE — engine v43 (2026-08-19).** (i) Windowed defensive tests now require **listing-age corroboration**: `sync listing-age` fetches each candidate's first-ever SEC filing date from the EDGAR submissions index (2,470 fetched); a record starting after 2011 earns a window only when the company itself first filed after 2011. ARCC (filed 2004) loses its unearned window — and so do LEVI/CFG, which filed as debt registrants years before their equity IPOs: their truncation is the dataset's. 1,251 → 1,045 windowed rows. Resolves §3.4 finding ①. (ii) **Preferred dividends** (`DividendsPreferredStock` family) now enter every NI/EPS arithmetic — implied share counts and the harness identity check; GTN's 2.2× mismatch is resolved, not just documented. (iii) Redeemable-NCI **Other** component read (ET $256M). Harness widened to 40 companies across 13 strata + 40 pins: **40/40 clean, PASS**; three tracked candidates remain (GS `UnsecuredLongTermDebt` $348B / `SubordinatedDebt` — bank cohort, pending fixtures; PLD in-place-lease intangibles). |
| 4 | **DONE — engine v44 (2026-08-19).** (i) A dividend record can now **disprove** twenty years, not only fail to prove them: two or more years inside the window where the company has earnings and no dividend fact make an uninterrupted record impossible → FAIL (BCC pays since 2017 but filed through 2013–2016 without paying). Guards: the year must carry earnings (absence is silence, not non-payment) and fall after 2013 (before that a payer might not have tagged). Result: 3,744 FAIL / 342 PASS / 1,810 still incomplete. (ii) Debt gains a **secured + unsecured axis** — the two sides are disjoint, so their sum is a second representation of the whole and competes with the instrument sum instead of adding to it (GS: $348B unsecured + $11.6B secured, no instrument rollup at all; subordinated debt sits inside unsecured and is never stacked on top). GS long-term debt 11.6B → 359.5B. (iii) **Context notes** — cash conversion over three years, five-year share-count drift, interest cover — disclosure only, never a grade; 3,781 companies carry at least one (KO: 75% of net income arrives as cash). They also gave `earnings_quality` its first UI home: it had been computed since the first release and never rendered. Harness: 40/40 clean, all tracked candidates resolved. |
| 4 | Quality/context layer (one-time gains, warrants, impairments) — warnings only, never adjustments to Graham grades. |
| 5 | Inline-XBRL extension adapter — the only route to issuer-extension concepts (e.g. franchise rights) that Company Facts cannot expose. |

### 4.4 Foreign-filer policy (clarified, not a conflict)

The review flagged v35's hiding of foreign-form filers (e.g. MNDY) against
v34's guarded US-GAAP 20-F support as an unresolved conflict. It is a
**deliberate, user-directed reversal** (2026-08-19): most foreign-form filers
carried stale or partial balance sheets, so all filers whose newest financial
filing is 20-F/40-F/6-K are hidden until proper IFRS/Inline-XBRL ingestion
exists. Now documented in `HOW-IT-WORKS.md` §2.7.
