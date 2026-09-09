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

Split detection: a period restated by a round multiple (1.5–100×) marks a split
and rescales history rather than reporting a fake collapse. Since 2026-08-21 the
evidence must clear three tests, because each was found producing wrong EPS on
real filers: the values doing the voting must exceed five cents (a −0.02 quarter
restated to −0.01 is rounding, not a corporate action — Idaho Copper); the
weighted-share count must move by the reciprocal factor, which is what refutes
another registrant's statements filed under one CIK (Essential Utilities, 2.5×
earnings against 1.41× shares); and a run of restatements of the same factor
collapses to one event measured from the run's **latest** observation, capped at
two years, because Lam Research's 10:1 arrives one comparative at a time over 287
days and was being booked twice.

### 1.2 Net income, revenue, operating income → size test, ch. 13, earnings quality

| Concept | Tags (chain order) | Why |
|---|---|---|
| Net income | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` | carried beside EPS because buybacks can grow EPS while earnings fall |
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`, `SalesRevenueGoodsNet`, `SalesRevenueServicesNet`, then sector top lines: `RegulatedAndUnregulatedOperatingRevenue`, `OperatingLeaseLeaseIncome`, `OperatingLeasesIncomeStatementLeaseRevenue`, `RealEstateRevenueNet`, `RevenuesNetOfInterestExpense`, `InterestAndDividendIncomeOperating`, `PremiumsEarnedNet` | ASC 606 (2018) switched most filers mid-history, so selection is recency-first with per-year fill; sector lines exist because a REIT's generic `Revenues` can be a $13M scrap beside $1.5B of lease income |
| Gross profit | `GrossProfit`, checked against same-accession revenue and `CostOfRevenue`, `CostOfGoodsAndServicesSold`, or `CostOfGoodsSold` when a suspicious fact is sub-$1,000 or repeats exactly for at least three fiscal years | SEC Company Facts can expose a hidden `zerodash` as zero (Financial Gravity) or an unprinted hard-coded subtotal (Dolphin Entertainment). A contradictory suspicious fact is withheld, never rescaled or replaced with an inferred subtotal. Genuine small results survive when the identity supports them (Uranium Energy $37,000; Rubicon −$40,000). |
| Operating income | `OperatingIncomeLoss`; otherwise `GrossProfit − OperatingExpenses` or `SellingGeneralAndAdministrativeExpense` only when the same filing reconciles it exactly to pretax income through `NonoperatingIncomeExpense`, or both `InterestIncomeExpenseNonoperatingNet` and `OtherNonoperatingIncomeExpense`. A second exact inverse path starts at pretax and removes separately filed interest income, interest expense and other nonoperating income/expense, but only when gross profit, SG&A and the separately presented `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` independently constrain residual operating-cost rows to at most 5% of gross profit. Generic `ResearchAndDevelopmentExpense` is excluded because it is often a note disclosure already included in SG&A. | reconstructed industrial subtotals retain every source in provenance; the constrained residual admits separately reported rows such as J&J's acquired in-process R&D without guessing their tag. A direct comparative that contradicts a complete same-filing bridge by exactly 1,000× or 1,000,000× is replaced by the reconciled presentation-scale value while the bad fact remains named in provenance (Bio-Techne FY2013). Other disagreement, an unreconciled subtraction, and banks/insurers stay absent. |

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

Tangible book = assets − liabilities − goodwill − intangibles − preferred − NCI
− temporary equity.
NCAV/share = (current assets − total liabilities − preferred − NCI − temporary
equity) / shares.

Mezzanine (temporary) equity belongs in both and was missing from this page until
2026-08-21, although `sync.py` has deducted it since v38 — the GTN fixture two
sections down exists precisely because of it. It is not a rounding difference:
22 of 101 audited filers diverge from the formula as it was written here, and
Ingredion's NCAV/share flips sign on it, +0.41 documented against −0.365 shipped.
That sign is what the P/NCAV column and the net-net filter key off.

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
| Evidence only | regex over the latest annual report and every later structured filing (`debt|borrowing|notespayable|…`) + `InterestExpenseDebt` family — gates the explicit `assume_absent_zero` opt-in: debt may be assumed 0 only when nothing debt-shaped in that current filing window carries ≥ $1M |

The opt-in also treats a separately missing **short-term** bucket as zero when
that filing window has no current-debt-shaped evidence, even if a noncurrent
balance exists. Thus EPAM's filed $25M noncurrent debt remains $25M combined debt;
only its silent current bucket becomes zero.

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

### 1.6 Owner-earnings evidence (context metrics, not Graham criteria)

A definitive Buffett figure is deliberately withheld unless maintenance capital
expenditure and required additional working capital are evidenced. Primary XBRL
normally reports neither. The payload therefore keeps differently scoped figures
separate:

- **earnings after total capital expenditure:** `earnings available to common +
  D&A - total capex`; it can materially understate a growing business and, because
  required working capital is unknown, is not called a guaranteed floor;
- **reported earnings — maintenance capex assumed equal to D&A:** the D&A add-back
  and assumed maintenance deduction cancel by construction; and
- **standard free cash flow:** `operating cash flow - cash capex`.

Engine v115 also publishes Finkle's three-equation reconciliation for the latest
completed fiscal year: (1) CFO − cash capex; (2) operating income − filed cash
taxes paid − the change in exact cash-excluded operating capital; and (3) revenue
− operating costs − filed cash taxes paid − that same capital investment. Methods
2 and 3 are algebraic rearrangements; method 1 is the independent cash-flow-
statement check. All inputs must cover the same fiscal period. The payload reports
`MATCH`, `MISMATCH`, or `INCOMPLETE` and never adjusts a method to force agreement.

The common numerator prefers a direct
`NetIncomeLossAvailableToCommonStockholders*` fact. Where only parent income is
available, a same-period preferred-dividend fact is deducted and both source facts
remain in provenance. Standard FCF includes actual working-capital movements but
cannot identify which portion was required. None is serialized or labelled as
definitive owner earnings.

Engine v112 adds separately named diagnostics without changing any Graham grade:

| Diagnostic | Tags / formula | Guard |
|---|---|---|
| FCF after stock compensation | `ShareBasedCompensation`, then `AllocatedShareBasedCompensationExpense`; standard FCF less the CFO add-back | same fiscal period; conservative shareholder-cost diagnostic, not a second earnings expense |
| FCF after cash acquisitions | `PaymentsToAcquireBusinessesNetOfCashAcquired`, then gross | same fiscal period; never relabelled standard FCF |
| Capitalized-intangible cash investment | sum of `PaymentsToDevelopSoftware` and `PaymentsToAcquireIntangibleAssets` | only distinct, same-period cash-flow facts; content/contract costs remain absent without a reliable standard tag |
| Working-capital cash effect | inverse of `IncreaseDecreaseInOperatingCapital`; signed adapter rollup `IncreaseDecreaseInOperatingAssetsAndLiabilities`; or a filing-verified complete component family (`IncreaseDecreaseInAccountsReceivable`, `IncreaseDecreaseInInventories`, `IncreaseDecreaseInOtherOperatingAssets`, `IncreaseDecreaseInAccountsPayableAndAccruedLiabilities`, `IncreaseDecreaseInOtherOperatingLiabilities`) | the US-GAAP operating-capital balance movement is sign-inverted to the cash effect; because Company Facts omits issuer-extension rows, a five-row sum is accepted only for an exact SEC accession/year already checked against the rendered statement, and same-context/overlap guards still apply |
| Operating-lease context | `OperatingLeaseLiability`; lease cost from `OperatingLeaseCost`, `LeaseCost`, `OperatingLeaseExpense`, then `RentExpense` | lease-adjusted debt requires both settled debt and the lease fact; fixed-charge coverage requires operating income, interest and lease cost for one annual period |

Every return denominator is now the exact average of the fiscal year's beginning
and ending capital. Both balance sheets must report assets, current liabilities,
and current debt; missing current debt is not treated as zero. Two views are shown:
capital including all cash, and capital excluding all filed cash and short-term
investments. The proprietary earnings/cash returns retain those names. A separate
NOPAT ROIC uses reported or exactly reconciled operating income, the median of at least two usable tax
rates from the latest three years, and average invested capital; pass-through
entities suppress it. No excess-cash estimate is invented.

Engine v116 adds RONTA = normalized NOPAT / average net tangible operating
assets. Each NTOA endpoint is the exact-date cash-excluded capital above, less
goodwill, other intangible assets, and one filed noncurrent-investment balance.
The noncurrent-investment alternatives are `OtherLongTermInvestments`,
`LongTermInvestments`, `MarketableSecuritiesNoncurrent`,
`AvailableForSaleSecuritiesNoncurrent`,
`DebtSecuritiesAvailableForSaleNoncurrent`, `HeldToMaturitySecuritiesNoncurrent`,
then `EquityMethodInvestments`. They are never summed because footnote categories
often overlap a balance-sheet rollup. Absence is not zero: both exact endpoints
and every deduction are required. The liability deduction remains current
liabilities less short-term interest-bearing debt. That current portion is read
independently even when a combined long-term-debt rollup contains it; the
total-debt double-counting suppression does not apply to NIBCL. XBRL does not identify a
complete cross-issuer set of noncurrent operating liabilities.

Engine v117 serializes a provenance-backed cash-flow bridge for each of the
latest ten owner-earnings fiscal-year slots. The identity is reported common net
income + D&A + separately filed stock compensation + other reconciliation
adjustments + the filed working-capital cash effect = operating cash flow;
operating cash flow - cash CapEx = standard FCF. The "other" line is derived as
the exact residual from those filed totals. If stock compensation or the aggregate
working-capital cash effect is unavailable, it remains inside the residual instead
of being assigned zero. CapEx uses the filed total; maintenance and growth portions
remain missing unless a filing provides a reliable separate fact.

Engine v118 compacts each direct bridge point to `[value, tag, form, accession,
period end]`. Residual and FCF are audited derivations from those direct rows, so
their source facts are not duplicated in the payload.

Engine v130 makes operating-lease treatment internally consistent in RONTA.
`OperatingLeaseLiabilityCurrent` (or the exact difference between
`OperatingLeaseLiability` and `OperatingLeaseLiabilityNoncurrent`) is retained as
financing instead of disappearing inside the non-interest-bearing-current-
liability deduction; the noncurrent portion was already retained by construction.
A second lease-neutral RONTA removes `OperatingLeaseRightOfUseAsset` from that
denominator to compare post-ASC-842 balance sheets with their earlier reported
presentation. It does not capitalize pre-adoption lease commitments. Both exact
endpoints keep the lease tags and filing provenance; an incomplete post-recognition
pair remains missing unless the explicit detail assumption mode is requested.

The company panel carries the newest ten completed fiscal-year slots. Every year
requires the three same-period floor inputs and that year's reported diluted weighted
average share count; a missing or differently dated input leaves the year blank.
It shows total and per-share values together and supplements endpoint CAGR with
three- and five-slot CAGR, medians, profitable/missing years, worst YoY decline,
maximum drawdown, variability, and diluted-share CAGR. A declining total hidden
by a falling share count is disclosed as buyback-driven per-share growth.
Historical denominators are rebased for filing-observed later splits and for the
priced depositary-receipt ratio, so the per-share values are on today's traded-
security basis. If one interior denominator is an exact 1,000x/1,000,000x table-
scale outlier and both adjacent split-adjusted years agree, that exact correction
is applied to this series and disclosed; otherwise the filed count is not guessed.
The UI shows each year, YoY change, endpoint CAGR, coverage, years
increased, and years growing at least 6%. These are observations, never scores.

| Concept | Tags |
|---|---|
| Reported earnings attributable to owners | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, then `ProfitLoss` when it is the only usable total |
| D&A | `DepreciationDepletionAndAmortization`, `DepreciationAmortizationAndAccretionNet`, `DepreciationAndAmortization`, else `Depreciation` + `AmortizationOfIntangibleAssets`; the explicitly allowlisted DERA extension `DepreciationAndAmortizationOfPropertyPlantAndEquipmentAndComputerPrograms` outranks a same-period standard narrative fact when it is at least as recent | FUSB's cash-flow statement reports $1.581m/$1.590m/$1.695m for FY2023–FY2025 through that issuer extension, while its standard element is a rounded note sentence and one filing loses the million scale. If the DERA extension is not cached, an earlier fact for the identical annual period is retained only when the newer value differs by exactly 1,000× or 1,000,000× and both adjacent years corroborate the earlier scale. A lone unusual value is never rescaled. |
| Total capex | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`, `PaymentsForCapitalImprovements` |
| Operating cash flow (standard FCF only) | `NetCashProvidedByUsedInOperatingActivities`, `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` |
| Cash & investments (netted from invested capital) | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`; `ShortTermInvestments`, `AvailableForSaleSecuritiesCurrent`, `MarketableSecuritiesCurrent`, `OtherShortTermInvestments`; modern `DebtSecuritiesHeldToMaturity*Current` only in filing-verified CIK/accession/date contexts |

The modern held-to-maturity current elements are deliberately not general
fallbacks. Vertiv's 2025 balance sheet proves a distinct `$99.5m` short-term-
investment row, but Westlake's note classifies `$1.009bn` from the same tag
family inside cash equivalents. Engine v139 accepts only the exact verified
Vertiv statement contexts and preserves Westlake as an adverse no-double-count
test; all other contexts remain missing until their statements are read.

### 1.7 Earnings-quality notes → criterion 1 disclosure

Non-cash / non-recurring lines large enough (≥ 10% of pre-tax) to distort the
P/E get a note, never an adjustment: `InventoryLIFOReserveEffectOnIncomeNet`,
`AssetImpairmentCharges`, `GoodwillImpairmentLoss`, `RestructuringCharges`,
`InventoryWriteDown`, `BusinessCombinationAcquisitionRelatedCosts`.

### 1.8 Deferred tax → context notes (engine v58)

The tax footnote is the company's own opinion of its future earning power, and
it is signed. Two readings are disclosed, neither ever a criterion.

| Concept | Tags | Rule |
|---|---|---|
| Deferred portion of the tax charge | `DeferredIncomeTaxExpenseBenefit` against `IncomeTaxExpenseBenefit` | latest shared fiscal year, and only within a year of the newest earnings; a charge ≥ 80% deferred means the tax return has not collected it (DTE FY2025: 88M charged, 358M deferred, a 270M current refund — its own `CurrentIncomeTaxExpenseBenefit` confirms the figure) |
| Valuation allowance | `DeferredTaxAssetsValuationAllowance` over `DeferredTaxAssetsGross`, else over `DeferredTaxAssetsNet` + allowance | one balance-sheet date for both; an allowance larger than the assets it reserves against proves the two tags are not one pair (VAL: 3,292M against a "gross" 1,368M → no note), and the derivation rescues filers whose gross tag went stale (BIIB's stopped in 2021) |

Both fire only beside a profitable latest year — a loss-maker reserving its tax
assets is doing the expected thing — and the allowance must matter against
common equity. `DeferredIncomeTaxesAndTaxCredits` (18% of filers) is a tracked
candidate, not read: it folds tax credits into the same figure.

### 1.10 Convertible preferred and warrants → context notes, never the share count (engine v69)

Graham counts shares "including the conversion of preferred" (table 18.6, where
McGraw-Hill's book value per share is struck on 24.2M converted shares), and he
prices warrants by adding their own market value to the capitalisation — the
fully-diluted alternative he calls illogical, because assuming exercise and
retiring debt with the proceeds left National General's EPS at $1.51 either way.

Neither can be done deterministically here, so both are disclosed instead.

| Concept | Tags | Why it is a note and not a figure |
|---|---|---|
| Convertible preferred | `ConvertiblePreferredStockSharesIssuedUponConversion` (8% of filers), `PreferredStockConvertibleSharesIssuable` (2%), `ConvertiblePreferredStockSharesOutstanding` (<1%) | One tag, three meanings: a conversion already done and inside the common count (Structure Therapeutics, 67.0M against 2023-02-07, its IPO); a ceiling on preferred that no longer exists (Aqua Power 500M, Ilustrato 31.98bn); a live conversion right (XWELL, 66.7M issuable against 31,333 preferred shares). The first is now separable — see below — but the second and third are not, so the count is never touched |
| Warrants | `WARRANT_SHARE_TAGS` | The screen prices no warrants — they trade under their own symbols — so the note says the capitalisation is understated by whatever they are worth, rather than diluting the denominator |

Both fire at a 5% overhang. The convertible note also raises a prose gap naming
the capitalisation note to read; 42 companies carry it.

**Which case a filer is in** (engine v72). `PreferredStockSharesOutstanding` is
filed on a share-class axis, so Company Facts drops it and Sachem's Series A reads
as absent rather than as a number. The quarterly DERA datasets keep the axis, so
the tag joins the harvest whitelist (`sync._dera_tags`) and
`normalize._preferred_outstanding()` sums it across **every** preferred class —
the question is whether any is left, not which series it sits in, so a split
across three series is not ambiguity. Zero means the conversion is history and the
note is dropped rather than shown as a warning about nothing.

Of the 42 companies flagged, 33 fall inside the harvested window and 9 are dormant
shells whose last filing predates it; the full-archive scan resolves 34, of which
13 had already converted. What no tag settles is whether the conversion figure is
the common the preferred becomes or a ceiling nobody reaches, so the note reports
what is outstanding and the prose gap asks for the conversion ratio.

**Warrants stay a note, and cannot stop being one.** Graham's rule needs their
market value. `FairValueAdjustmentOfWarrants` (93 of the 122 flagged companies) is
the P&L *change*, not the balance. A balance exists for only 17, always as an
issuer extension under a different name per filing agent (`WarrantLiabilityCurrent`,
`WarrantLiabilityNoncurrent`, `PublicWarrantLiabilityNoncurrent`,
`CurrentPortionOfWarrantLiability`). Two problems survive full coverage: only
liability-classified warrants carry a mark at all — the equity-classified majority,
which is Graham's NVF case, carries none — and a fair-value mark is a model number,
not the traded price he means. The warrants trade under their own symbols and this
screen prices none of them.

### 1.13 Equity awards → dilution the share count does not show (engine v73-75)

| Concept | Tags | Rule |
|---|---|---|
| Options outstanding | `ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber`, then `...OptionsExercisableNumber` | dimension-free and fresh |
| Restricted stock | `...EquityInstrumentsOtherThanOptionsNonvestedNumber`, then `...OtherThanOptionsOutstandingNumber` | same |

Summed into one overhang against shares outstanding — both promise shares to
employees and dilute the same holders; what differs is that an option needs a
rising price to be worth anything and a restricted share does not. The total
carries the basis it was struck on (`awards_basis`), the way a trailing P/E carries
`ttm_basis`: "options only" is a statement about the evidence, not about the
company.

2,192 companies (37%): **1,792 options only, 232 both, 168 RSUs only**. Median
overhang **2.89%**, 95th percentile 21.6%. Restricted stock is the thinner series
of the two — a fresh, dimension-free nonvested balance exists for only about 5% of
filers, because the count sits in a roll-forward table dimensioned by award type.

Apple, Microsoft, Nvidia, Tesla, JPMorgan and Coca-Cola tag **no machine-readable
count of either kind** — not in Company Facts, and not in five quarters of the
DERA datasets, which was checked directly. §5.1 applies: the panel shows an em
dash, never 0%.

**A pool larger than the company is a tagging error**, not dilution, and is
withheld: Greenlane's reads 235,000 one quarter and 235,000,000 the next,
Zerocarbon reports 3.2bn options against 10.4M shares, Astrotech 234.4M against
1.76M. Seventeen rows shipped an overhang above 100% (XXI at 1,344,649,800%, its
own share count tagged as 1) before the ceiling went in; none do now, and the
largest surviving figure is 90.1%.

### 1.14 What the 2026-08-22 filing audit changed (engine v76-79)

The first audit to read the *published statements* rather than compare two machine
readings of the same XBRL. `make audit-filings` fetches each company's rendered
balance sheet and income statement and checks the panel against the printed page.

| filer | was | now | the printed page says |
|---|---|---|---|
| EML | no P/E at all | 18.87 | $5,405,522 / 6,264,521 sh = $0.86, not the $1.76 a later filing tagged |
| ET | NCI 15,441M | 15,447M | "Noncontrolling interests 15,191" + "Redeemable 256" |
| STWD | FY2025 profit 443,093K | 411,544K | "Net income attributable to Starwood Property Trust" |
| TKO | FY2025 profit 546,290K | 195,403K | 546,290 less 350,887 of noncontrolling interests |
| OVV | FY2025 revenue 8,663M | 8,908M | "Total Revenues" |
| ARES | FY2025 revenue 4,756M | 5,601M | "Total revenues" |

Two root causes, both the same shape — a ranking that put coverage above meaning:

* **Net income** ranked candidates by (recency, series length, tag preference), so
  `ProfitLoss` — the *group's* profit, minority holders included — won on having
  more years than `NetIncomeLoss`. Scope now outranks depth; recency still settles
  an abandoned series. 23 companies (2.9%) move.
* **Revenue** ranked `RevenueFromContractWithCustomerExcludingAssessedTax` above
  `Revenues`, and the two filers above err in opposite directions, so no ordering
  fixes both. They are a total and its part, so between *those two* the larger is
  the total. Never applied to the assessed-tax pair, where the larger would count
  sales tax collected for the state as revenue. 10 companies (1.4%) move.

**Known and not fixed.** Vivid Seats tags
`RevenueFromContractWithCustomerExcludingAssessedTax` dimension-free at its
MarketPlace segment alone; the consolidated total is $127.7M larger and exists only
under a `BusinessSegments=Consolidated` axis. One company in 4,489 does this, so
the engine reads a segment as the whole — a per-filer special case would be worse
than the error.

Vivid Seats also tags fiscal 2025 net income of +$806.1M beside a group loss of
$721.5M; its statement says -$292.2M. Rebuilding the parent's figure as group minus
minority fixes it and breaks TKO, which tags only the redeemable half of its
noncontrolling interests without a dimension. Left alone deliberately.

### 1.15 What ~2,000 companies against their published statements settled (engine v82-83)

Four sweeps, four seeds, every figure checked three ways: against the filing its own
provenance names, against its own arithmetic, and against the balance sheet and
income statement the company published.

| | result |
|---|---|
| values matching the filing they name | **4,823 / 4,823** |
| figures matching their own arithmetic | **4,008 / 4,008** |
| lines matching the published statement | **3,456 ok, 10 wrong** |
| components superseded by a newer filing | **0** |

Defects this found, beyond §1.14:

* **Sales tax cannot exceed the sale.** Precision Optics tags $53.5M including
  assessed tax against $24.2M excluding it; thirty filers tag a pair no rate
  explains (Lifestance 462x, SS Innovations exactly 1000x, a units error wearing a
  revenue tag). Worse than the bad figure: the sub-scope guard anchors on the
  LARGEST candidate, so one inflated element pushed Precision Optics' own $24.0M —
  the "Net sales" its statement prints — out of contention as a scrap.
* **`_class_member` could not tell Class A from Class B.** Its pattern needed a
  lowercase tail, so the lone "A" was dropped and both classes read as
  `{"class"}`. Every dual-class cover then produced two matches, read as ambiguous,
  and was refused — the one thing the cover reader exists to settle. Resolution
  went from 46 to 160 of the first 1,200 companies; PJT's count was a weighted
  average and is now its Class A outstanding count.
* **126 of 5,791 cover titles** run into the next rendered cell.
* **Provenance now carries the share-class axis.** 137 figures were read on one
  while naming only the tag, which points at a filing where the number differs.

**Where the filing is the unreliable side.** Four classes, each now named rather
than scored: a header declaring "$ in Millions" over whole dollars (ABVC's cash of
"$ 31,944" would be $31.9 trillion); a newer figure in an S-1, which the engine
does not read; a figure derived by identity, which contains the mezzanine a printed
"Total liabilities" excludes; and a concept the statement never prints at all —
income available to the common, which Occidental, Rhinebeck and Interactive Brokers
tag and no line on their pages equals.

**Still open**, each with its reason in the code: Benchmark Electronics, Blackstone
Mortgage, Vivid Seats.

### 1.11 Settled debt → criterion 3 and the capitalisation figures (engine v70)

`screens.enterprising.settled_debt()` is the single place the rollup-versus-parts
reconciliation lives, and the row exports its answer as `debt` (41% of rows;
`total_debt` alone is tagged by only 7%). Criterion 3 weighs it and the detail
panel adds it to the market value of the common. `None` means unknown, never
debt-free — folding it to zero printed AES, a utility, at $11B of pure market
cap under a label promising its debt was included.

### 1.12 Fiscal year ends → the past columns of the Ratios table (engine v71)

`normalize.fiscal_year_ends()` reads the date each fiscal year actually closed on
(annual balance sheets first, the annual EPS series as backup) and is the single
source both `vintage_ttm_eps` and `sync._price_the_ratio_history` read, so their
keys cannot drift.

Before v71 both used a calendar `{year}-12-31`, which is the right date only for
December filers:

| | KO (Dec) | MSFT (Jun) |
|---|---|---|
| newest FY | 2025, closed 2025-12-31 | 2026, closed 2026-06-30 |
| old cutoff | 2025-12-31 ✓ | 2026-12-31 — four months away |
| newest P/E | 22.89 | *blank* → **23.26** |
| FY2025 P/B | 9.27 (unchanged) | 10.28 → **10.84** |

206 companies had no P/E in their newest column; 77 remain and all are correct —
64 lost money that year, and MCHP/MNRO/CPRI closed a year positive whose *trailing*
figure on the closing day was still negative, which is the no-look-ahead rule
working. Every non-December filer was also silently pricing a mid-year balance
sheet against the following December's market; that is now the close of the day the
year ended.

### 1.9 What is *calculated* from these

| Output | Formula | Where settled |
|---|---|---|
| C1 P/E | price / TTM EPS, PASS < 10.0 | at export (`sync.apply_price`) only — the browser reads the settled status, it does not recompute |
| C2 current ratio | CA / CL, PASS ≥ 1.50 | engine |
| C3 debt load | total debt / (CA − CL), PASS ≤ 1.10 | engine |
| C4 stability | min EPS of last 5 FY ≥ 0 | engine |
| C5 dividend | pays now (yield shown when price sane) | engine + price |
| C7 tangible valuation | price / TBVPS, PASS < 1.20 | at export only, same as C1 |
| Past-year multiples | that year's book figures ÷ the close on the day the fiscal year ended, P/E over `ttm_eps_vintage` | `normalize.fiscal_year_ends` fixes the date for both sides (engine v71) |
| P/E3, ch. 13 stats | 3-year smoothed averages, 5/10-year growth, max decline, 10-year positive years | `ch13.py` / `profiles.py` |
| Award overhang | (options + restricted stock) ÷ shares, each kind refused above 100% | `normalize`, `web/src/capital.js` |
| Total capitalisation | market value of common + settled debt | `web/src/capital.js`, withheld when either is unknown |
| Working capital / debt | (CA − CL) / settled debt, "no debt" at zero | `web/src/capital.js` |
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
12. ~~**Debt evidence has no recency bound.**~~ Resolved in engine 125: the
    explicit opt-in searches the latest annual report and all later structured
    filings, so retired historical borrowings do not masquerade as current debt.

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

Other cash-flow-statement totals (no criterion consumes them; OCF is read only for
the separately labelled standard-FCF context metric) and the ASC 842 operating-lease family
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
| Intangibles | `us-gaap:IndefiniteLivedTrademarks` | $12,463M | landed at v38; §3.3 kept the pre-v38 reading until 2026-08-21 |
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

- **Criterion 7 was INSUFFICIENT for KO until v38, and this section described that
  state for twenty engine versions after it stopped being true.** The class-tag
  fallback landed as release 2 below; KO now ships `intangibles` $12,463M,
  TBVPS $1.34 and criterion 7 **FAIL at 67.5**. The prediction underneath was
  correct and is kept because it is the reasoning that produced the fix — but it
  is history, not the current reading. KO files no
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

- **8 of the 12 chain defects in §2.1 are now fixed** (audit of 2026-08-21;
  defect 6 was fixed at v49, *before* the review below claimed to confirm it).
  Still live: #1 in part (stale-zero selection — the SRI class), #3
  (`LongTermNotesPayable` mis-ranked), #4 (derived liabilities subtract
  redeemable NCI twice — 35 rows including CMCSA, ACN and ADM: `redeemable_nci`
  is gated on `parent_only_derivation` where `temporary_equity` is gated on
  `liabilities_derived`), and #12 (debt evidence has no recency bound). The
  original review text follows, unedited, because what it found is why the
  releases below exist.
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
| 4b | **DONE — engine v46 (2026-08-19).** **Derived EPS** for filers whose per-share element is dimension-only (Company Facts drops it) or years stale: `(net income − preferred dividends) ÷ that year's share count`, using the weighted average where filed and otherwise the count on that year's report cover, and only when the count is struck within 460 days of the year end. **216 companies' EPS series reached the present** at v46 (KKR 2017→2025, PAA 2016→2025, PAGP 2014→2025, CQP, GGROU) — but the cover-count half of that fallback was **removed after v46** when it was measured producing errors of five, ten and a hundred and fifty times, and `_annual_share_counts` says so in its own docstring. What survives is the weighted-average path: PAA's series ends 2016 again and KKR reaches 2025 through v53's dimensioned reader, not through this release. The named companies are the claim's original evidence, not a current inventory; the trailing figure is recomputed too whenever the income data is newer than the last tagged per-share period, since a stale TTM priced against today's quote is worse than none — 148 companies moved from unknown to a measured criterion-1 FAIL, 15 to PASS. Guard found in verification: `ProfitLoss` includes noncontrolling interests, so it derives EPS only where the equity pair shows no minority holders — Ares tags no `MinorityInterest` at all yet its equity including NCI is twice its parent equity, and would have read 2.60 against a genuine 3.00-odd. **ROIC surfaced**: the Davis-Funds owner-earnings measure has been computed since the first release and appeared nowhere — now a sortable table column and a Detail section showing every component, invested capital, both capex readings and the caveats (2,978 companies carry one, 774 at 10%+). |
| 4c | **DONE — engine v49 (2026-08-19).** Graham's Penn Central signals, and a standing integrity rule. **Untaxed profits**: a taxable company reporting profit for years while paying effectively no income tax now says so (689 companies) — Graham's reading was that the tax authorities did not believe the earnings; a partnership, investment company or REIT gets the structural explanation instead (69). **Peer efficiency**: operating margin against the median of the company's own industry, computed at export because no single filing can produce it (527 companies materially behind). **Data-integrity audit over all 5,907 companies**, not just the sample: it immediately found four classes of false data now fixed — a zero share count (every per-share figure divides by it), a negative "revenue" that is really a fund's investment loss (IAU, BUR), negative assets from a filer's sign error (OYCG), and iShares Gold Trust's **2013** revenue presented beside a 2026 balance sheet as the trailing twelve months. |
| 4d | **DONE — engine v58 (2026-08-20).** Three questions the criteria cannot answer, all disclosure and none of them a grade. (i) **The shape of the ten-year record.** `ch13` now reports the *first* half of the record separately (`growth_early`) — the ten-year figure adds both halves and cannot say which one produced the result — plus the latest year against the three behind it, and names the two unambiguous shapes: **52 sprints** (a flat decade carried by its last three years: CB, DUK, CSCO, ABT — whose smoothed EPS went $2.01 in FY2013–15 → $1.96 in FY2018–20 → $4.87 in FY2023–25) and **394 marathons** (both halves up ≥ 10%, ten positive years, no fall worse than 40%: MSFT, GOOGL, JPM). A first half that *declined* is deliberately neither: the rebound after a loss year is a return to where the company already was (D: −33% then +591%). (ii) **Deferred tax — the company's own signed opinion of its future earning power.** 265 companies reserve more than half their deferred tax assets while reporting a profit (META: 15,895M of 28,090M, and gross − allowance reconciles to its net tag to the dollar); 194 report a tax charge ≥ 80% deferred (TMUS FY2025: 3,289M charged, 425M currently payable; DTE: 88M charged against a 270M current *refund*, confirmed by its own `CurrentIncomeTaxExpenseBenefit`). Two traps found in the data and guarded: an allowance larger than the assets it reserves against proves the two tags are not one pair (VAL reserves 3,292M against a "gross" 1,368M), and a gross tag gone stale is rebuilt from net + allowance at the same date (BIIB's stopped in 2021). (iii) **`make events`** — material 8-K item numbers from each company's own filing index, the only company events readable without opening a document: non-reliance (4.02), bankruptcy (1.03), debt acceleration (2.04), listing deficiency (3.01), material impairment (2.06), repeated auditor changes (4.01). Items 5.02 and 1.02 were measured against a 200-company sample and **dropped** — at 87% and 38% of filers their numbers cannot separate a fired CFO from a board election, or a lost customer from a refinanced credit line. 19,232 events across all 5,911 companies; **2,165 (36%) carry at least one note** — 1,451 listing deficiencies, 670 auditor-churn, **573 non-reliance**, 215 debt accelerations, 185 impairments, 52 bankruptcies — and 2,291 companies are scanned clean, which is an answer rather than a blank. Each company records how far back its own index could be read (Wells Fargo's thousand most recent filings reach back fourteen months), and no note claims a window wider than that. |
| 4 | Quality/context layer (one-time gains, warrants, impairments) — warnings only, never adjustments to Graham grades. |
| 4e | **DONE — engine v67 (2026-08-22).** The audit of 2026-08-21 and its repairs. Thirty of thirty-three findings fixed, each against the company that proved it: one split counted twice (Lam Research FY2022 0.3275 to 3.275), an 8-K read as a split (Essential Utilities 5.50 to its filed 2.20), a debt rollup smaller than its own parts (Pangaea 0.52x PASS to 3.75x FAIL), a lease book standing in for Ford's borrowings, a partnership's group profit over its own units (Westlake 2.29x PASS to 13.29x FAIL), a 52/53-week year losing its restatement (ATI FAIL to PASS), criterion 4 decided on windows that closed a decade ago (Hershey, Berkshire), earnings and share counts on different bases (SM Energy, NRC), Canadian filers priced in the wrong currency, ROIC divided by a balance sheet twelve years newer (J&J FY2014 13.1% to FY2025 22.0%), a 2012 special dividend priced as a 9.49% yield, yields above 100% shipped by the export the engine refuses to publish, preferred-only payouts passing criterion 5 (Boeing), and a current ratio built from two different balance-sheet dates. **The coverage harness sampled nobody**: `coverage.py` selected on `mcap`, which the payload does not carry, so thirteen strata drew zero companies and only the forty pins were ever tested — the parts-vs-rollup identity that catches Pangaea was already written and had never run. Fixed, and the first real run over 113 companies found 110 unclassified tag families and fifteen identity mismatches; all are now read, registered with a reason, or explained by the engine's own refusal. **New**: Graham's two profitability ratios (net margin, return on book value) and a ratio table showing every ratio at today's price and at each of the last five fiscal year ends, each column struck on its own year's report and its own year's price; per-company incorporation from the filing index; a "check the filing" record for what only prose can settle (927 rows). **The cover page is read** (`sources/cover.py`, `make cover`): `dei:Security12bTitle` and `dei:TradingSymbol` are text under a share-class axis, so Company Facts strips both, and between them they settle the question every per-share figure rests on — which security the ticker prices. 3,750 covers read, 4,709 registered classes, six depositary ratios above one. Where a ratio exists the figures are restated onto the traded security: the share count divided by it, earnings, book value and dividends multiplied, so both sides of every multiple describe one thing. Onconova's market capitalisation falls from $550.2B to $42.3B and its P/E becomes measurable at 67.0; Akari's from $1,099B to $0.55B. The note quotes the filer's own sentence, so the parse can be checked rather than trusted, and a cover that has been read closes the gap it answers — 927 down to 632. Seven documentation defects corrected, including a verdict precedence stated backwards and a client-side price mirror that four documents promised and no commit ever built. 307 pytest + 22 node. |
| 4f | **DONE — engine v112 (2026-08-29).** Owner/cash evidence now starts with income available to common, deducts a same-period preferred claim from parent income when necessary, and labels the D&A-cancelling estimate as reported earnings. Return denominators use exact average beginning/end capital and publish cash-included and cash-excluded views; cash-excluded capital is withheld unless cash, short-term investments, current debt, and any restricted-cash portion are explicitly filed at both endpoints. Normalized tax and supplemental cash-flow comparisons require aligned annual periods, and NOPAT ROIC is withheld for pass-through structures. Supplemental, provenance-backed lenses cover FCF after stock compensation, acquisitions and capitalized intangible cash investment, reported working-capital cash effects, operating leases and fixed-charge coverage. The UI adds total-versus-per-share trends, shorter CAGRs, medians, drawdowns, variability, asset-quality composition, buyback warnings, and explicit bank/insurer/REIT/MLP/shipping/retail/software/acquirer/commodity/utility comparability routes. Historical prices now adopt a declared split restatement only after the filing-derived EPS/BVPS history proves the same factor; until then the export retains contemporaneous closes and discloses the basis gap. Subjective adjusted-NCAV haircuts, estimated excess cash, custom-tag AFFO/DCF, and automated content normalization remain withheld rather than guessed. |
| 5 | Inline-XBRL extension adapter — the only route to issuer-extension concepts (e.g. franchise rights) that Company Facts cannot expose, **and to the cover page**: `dei:Security12bTitle` carries the depositary ratio in prose ("each representing 10 Ordinary Shares") with the trading symbol attached to one share class, which is the only deterministic answer to "which security does this ticker price". 616 rows are waiting on it for the ratio and 183 for the class. |

### 4.4 Foreign-filer policy

Engine v95 (2026-08-25) replaces the blanket foreign-form exclusion with an
evidence gate. A current 20-F/40-F filer enters when that same annual accession
carries a USD US-GAAP balance-sheet anchor and its cover attaches the exact ticker
to common/ordinary/voting/partnership equity. A depositary security enters only
with a positive underlying-shares-per-receipt ratio parsed from that cover; the
engine applies the conversion to shares, EPS, dividends, book value and historical
per-share ratios, including fractional ratios. New 20-F/40-F/6-K filings are now
part of the daily refresh, and a new annual filing invalidates the old cover until
the current class is read. The initial filing-backed cohort adds 420 listed foreign
issuers.

Engine v102 (2026-08-27) extends the same evidence gate to standard IFRS. A USD
`ifrs-full` balance sheet in the current 20-F/40-F is normalized through explicit
accounting-equivalent concept aliases; every selected figure keeps its original
`ifrs-full` element, form, accession and period in provenance. The mapping does not
convert currencies or infer missing values. Ambiguous near-matches are omitted:
for example, the generic IFRS 16 lease liability is disclosed as lease context and
is not silently reclassified as Graham debt. Non-USD reporters remain outside the
table until a filing-date-aware currency pipeline exists.
