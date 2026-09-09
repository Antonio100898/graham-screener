# Audit — What the Dashboard Gets Right, and the 42 Places It Does Not

> **Historical record of engine 58 (2026-08-20).** Most of what follows has since
> been fixed, and the method has been superseded: this audit compared two machine
> readings of the same XBRL, which a mis-tagged fact passes. `make audit-filings`
> now reads each company's *published* balance sheet and income statement and
> checks the panel against the printed page. See `TAGS.md` §1.14 for what that
> found, and run `make regress` before trusting any figure here.


Engine 58, payload generated 2026-08-20, 5,911 rows. Sixteen area auditors, their
adversarial reviewers and three cross-cutting critics worked the code and the shipped
payload for one week. This document is the merged result: what was checked, what
survived refutation, what was refuted, and what nobody could reach.

**Headline.** The arithmetic is sound almost everywhere. Every criterion value in the
payload equals the formula applied to the fields beside it — c1 on 2,304 rows, c2 on
4,418, c3 on 1,738, c5 on 1,798, c7 on 1,595, with zero mismatches. Every per-share
book value reconciles algebraically. `n_pass`, the verdict precedence and the criterion
numbering are exact on all 5,911 rows. **The defects are almost never in the arithmetic;
they are in which fact the engine chooses to put into it, and in what the interface
claims that fact is.**

---

## 1. Method

### What "verified" means here

A claim was accepted only when the quantity was **recomputed from the raw source without
importing the code under test**. Three independent layers:

1. **Recomputation from `~/.cache/graham-screener/companyfacts_*.json`.** Each auditor
   wrote their own extractor — own tag chain, own period filter, own restatement rule —
   and diffed it against the shipped payload row by row. A disagreement was a lead, never
   a verdict: every one was classified as (a) a system defect, (b) the auditor's own
   oversimplification, or (c) a genuine definitional difference. Class (b) is reported
   below in the coverage gaps, not as findings.
2. **Recomputation from the payload's own fields.** 47 internal identities (A − L = book
   × shares, ncavps ≤ bvps, total debt ≥ its own long-term part, criterion value = the
   ratio it prints) recomputed in `Decimal` straight from `dashboard.json`, importing no
   project code. This is what caught the fragment debt rollups: the payload contradicts
   itself in public.
3. **Ground truth on sec.gov.** For every CONFIRMED finding, the filing the payload's own
   provenance names was fetched and the line quoted verbatim. 43 filings in total, with
   the required User-Agent and request spacing. A finding that could not be traced to a
   filing line is marked PARTIAL.

### Sample

| Layer | Coverage |
|---|---|
| Full-payload sweeps | all 5,911 rows, for every criterion, every identity, every note kind |
| Independent per-filer recomputation | 101 filers figure-by-figure across all 14 balance-sheet slots; a further ~400 for single quantities |
| Named fixtures re-derived by hand | MSFT KO JPM ABT WMT SRI DDOG GTN EPD ARCC LEVI DUK MAA HEI SUN KKR PAA BIIB VAL DTE TMUS META INGR AMD, plus the mega caps, REITs, MLPs, BDCs, banks, insurers, homebuilders, SPACs and microcaps |
| Filings read | 43 accessions on sec.gov, quoted verbatim in the findings |
| Regression tests written and run against HEAD | 31, every one failing today |

### Adversarial structure

Every finding was written by one agent and then **attacked by a second whose job was to
refute it**. That process killed two findings outright (§4), corrected the severity of
four, and cut the claimed blast radius of three by more than half. Where the two agents
still disagree about a number, both numbers appear below with their definitions — this
document does not silently pick a winner.

### Honest limits

- **Read-only.** Neither `make derive` nor `make export` was run. Every conclusion is
  about the engine-58 payload of 2026-08-20 plus fresh calls into `normalize.py` against
  the same fact cache. Row counts will shift when the cache moves.
- **Company Facts only, for the undimensioned path.** Facts a filer tags on a share-class
  or segment axis are invisible to the API. KKR's $2.5bn of Series D preferred is tagged
  only under `StatementClassOfStockAxis` and is never deducted. The DERA sidecar that
  `_unambiguous_dimensioned` reads was **not** independently recomputed — 195 rows' TTM
  EPS and 68 rows' share counts rest on it unverified.
- **No browser.** Every UI claim is read from `web/src` source against the exact payload
  values the components receive, except `earningsEvidence.js` and `Detail.jsx` which were
  executed directly (under `node` and `react-dom/server` respectively).
- **Historical deltas are unfalsifiable.** Claims of the form "726 companies gained
  long-term debt" need the pre-change payload, which is not retained. Named fixtures
  inside them were checked individually.
- **`assume_absent_zero` was never exercised.** Zero of 5,911 rows carry an assumption, so
  the opt-out path is judged from code alone.

Baseline green throughout: `pytest -q` → 284 passed, `npm test` → 22 passed,
`make verify-coverage` → PASS.

---

## 2. Findings

42 defects, plus 7 false statements in the repo's own documents. Severity is judged by **what the user sees**: a wrong PASS/FAIL or a headline
number wrong by a multiple is CRITICAL; a wrong number that does not flip a verdict is
MAJOR; a wrong label or explanation is MINOR; anything the user cannot reach is NIT.
Four severities were corrected by reviewers and are marked as such.

**Summary: 13 CRITICAL · 20 MAJOR · 7 MINOR · 2 NIT.**

---

### F1 · CRITICAL · CONFIRMED — One stock split counted twice: 1,122 displayed EPS values are 2×–100× wrong

**What the user sees.** Lam Research's EPS curve steps from **$0.33** (FY2022) to **$3.32**
(FY2023) with no corporate event, and "Earnings stability" reports **0.33** as the worst
of the last five years when the worst is **$2.90**. Same break on Cintas ($0.73 → $3.25),
Sherwin-Williams ($1.30 → $5.50), Old Dominion, Sempra, Williams-Sonoma, Texas Pacific
Land, Palo Alto Networks. Cognex ships **"Earnings growth · ≥ 33⅓% over 10 years · +81.0%
· PASS"** where the true figure is **−9.5%, a FAIL**.

**What is correct.** One corporate action produces one factor. LRCX split 10:1 in October
2024, so FY2022 diluted EPS of $32.75 becomes **$3.275** and the five-year minimum is $2.90.

**Proof.** LRCX, CIK 0000707549.
FY2024 10-K, accn `0000707549-24-000106`,
<https://www.sec.gov/Archives/edgar/data/707549/000070754924000106/R3.htm> —
`Diluted (usd per share) | $ 29.00 | $ 33.21 | $ 32.75` for FY2024/23/22, **one share basis
for all three**.
FY2025 10-K, accn `0000707549-25-000075`,
<https://www.sec.gov/Archives/edgar/data/707549/000070754925000075/R3.htm> —
`| $ 4.15 | $ 2.90 | $ 3.32`. 29.00/2.90 = 10.000 and 33.21/3.32 = 10.003: **one split,
factor 10**. The payload holds FY2024 2.90 and FY2023 3.32 (= as filed ÷ 10) but FY2022
**0.3275** (= 32.75 ÷ 100) — two figures from the same filing placed a factor of 10 apart.

**Code path.** `normalize.py:710-712` — the 275-day "same corporate action" window is
measured from `events[-1][0]`, the **first** filing of the run, and absorbed restatements
hit `continue` without advancing the anchor. LRCX's 10:1 reaches Company Facts on
2024-10-28, 2025-01-31, 2025-04-25 and 2025-08-11; the middle two are absorbed, the last
is 287 days past the first and is booked as a **second** 10:1. → `_split_factor` (:665) →
`_split_adjust` (:806) → `_annual_eps` (:802) → `enterprising.py:189` → `EpsCurve.jsx:27`,
`Detail.jsx:187`, `ch13.growth_10y`, `alignment.growth_modern_4fy.base_eps`.

**Affected.** 167 companies · 1,122 distinct annual EPS values wrong · 686 of them inside
the 13 years the curve draws · **66 companies with a wrong criterion-4 value** · 43 with a
wrong `growth_10y` · 4 with a wrong `pe3` · **1 wrong defensive PASS (CGNX)**. Criterion 4's
own PASS/FAIL never flips (the factor is positive, so signs survive). Everything in the
276–364 day band double-counts; ≤275 collapses correctly. Reverse splits double-count in
the other direction (SITC c4 ships 3.36 against a true 2.04).

> **Corrected by review.** The original claim said "2,539 displayed EPS values". That was
> `sum(n_affected_periods)` — the same fiscal year counted two to four times across four
> tag families. The distinct-value count is **1,122**. Apple was also a bad example: its
> wrong years (FY2007–FY2012) all fall outside the drawn curve, criterion 4's window and
> ch13's blocks, so AAPL's shipped c4, `growth_10y` and `pe3` are all correct.
> Sherwin-Williams' criterion 4 (6.98) is correct too; only its curve and `growth_10y` move.

**Repro.**
```sh
cd api && .venv/bin/python .../audit/c4-eps-series/run_collapse.py 10
cd api && .venv/bin/python .../audit/c4-eps-series/c4_value_impact.py   # 67 c4 values change
```

**Regression test** — `api/tests/test_normalize.py`. The 276–364 day band is untested today:
the existing pin spaces restatements 92 days apart, and the two-genuine-splits pin spaces
them 365 days apart.
```python
def test_one_split_restated_past_three_quarters_is_still_one_split():
    """LRCX. The 10:1 of October 2024 reaches Company Facts one comparative at a time —
    10-Qs of 2024-10-28, 2025-01-31, 2025-04-25, then the FY2025 10-K of 2025-08-11, 287
    days after the run began. Anchoring the run to its first filing rather than its latest
    observation books a second 10:1, and FY2022 — which no filing ever restated, because it
    fell out of the 3-year comparative window — comes out divided by 100."""
    eps = [_yr(2022, 32.75, "2024-08-29", "k24"), _yr(2023, 33.21, "2024-08-29", "k24"),
           _yr(2023, 3.32, "2025-08-11", "k25"), _yr(2024, 2.90, "2025-08-11", "k25"),
           dur("2022-09-26", "2022-12-25", 12.00, form="10-Q", accn="qa",  filed="2023-01-25"),
           dur("2022-09-26", "2022-12-25",  1.20, form="10-Q", accn="qa2", filed="2024-10-28"),
           dur("2022-12-26", "2023-03-26", 13.00, form="10-Q", accn="qb",  filed="2023-04-26"),
           dur("2022-12-26", "2023-03-26",  1.30, form="10-Q", accn="qb2", filed="2025-01-31"),
           dur("2023-03-27", "2023-06-25", 14.00, form="10-Q", accn="qc",  filed="2023-07-26"),
           dur("2023-03-27", "2023-06-25",  1.40, form="10-Q", accn="qc2", filed="2025-04-25")]
    gaap = dict(GAAP); gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert round(float(s.annual_eps[2022].value), 4) == 3.275   # 32.75 / 10, not / 100
    assert float(s.annual_eps[2023].value) == 3.32
```

**Caveat for whoever fixes this.** Advancing the anchor to the run's last observation is
the right direction but is not obviously safe alone — it becomes a 275-day sliding window
that can chain arbitrarily far. TPL only stays correct because its second genuine split
lands 359 days past the first run's last observation. Key on the observed cumulative ratio
per period, or cap the total span of a collapsed run.

---

### F2 · CRITICAL · CONFIRMED — A debt "total" smaller than its own long-term part ships four wrong criterion-3 PASSes

**What the user sees.** Pangaea Logistics: **"Debt load · Total debt ≤ 1.10 × NCA · 0.52 ·
PASS"**, 4 of 6 criteria met. Cumulus Media 0.01 PASS. Pursuit Attractions 0.02 PASS. CHS
0.67 PASS. ON Semiconductor's panel shows **Long-term debt $3.7B and Short-term debt
$802.6M** while the criterion beside it prints **0.00×**.

**What is correct.** PANL's real debt is $349,487,000 against net current assets of
$73,760,000 → **4.74× → FAIL**. Even on the engine's own parts (276,793) it is 3.75× → FAIL.

**Proof.** PANL 10-Q accn `0001628280-26-055365`, period 2026-06-30,
<https://www.sec.gov/Archives/edgar/data/1606909/000162828026055365/R2.htm>. The element
`us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities` = 38,521,000 is
attached to the single line **"Current portion of financing obligations"**, not to any
total. The same balance sheet carries:
```
Current portion of secured long-term debt      40,155,000
Current portion of financing obligations       38,521,000   <- what the payload calls "total debt"
Current portion of finance lease liabilities    1,000,000
Secured long-term debt, net                    66,542,000
Financing obligations, net                    195,360,000
Finance lease liabilities, net                  7,909,000
```
PRSU's rollup `DebtAndCapitalLeaseObligations` = 1,641,000 sits beside
`LongTermDebtAndCapitalLeaseObligations` = 234,082,000 **in the same accession**
(`0001193125-26-335133`). CMLS's rollup 2,028,000 is byte-identical to its own
`LongTermDebtCurrent`. CHSCP's rollup omits `ShortTermBankLoansAndNotesPayable` 1,589,756,000.

**Code path.** `normalize.py:273-289` takes the rollup unconditionally whenever its period
end is not **older** than the parts; there is no guard for a rollup *smaller* than its own
components. `screens/enterprising.py:141-143` then uses `s.total_debt` and ignores long+short
entirely.

**Affected.** 64 rows ship a total debt below their own long-term debt — arithmetically
impossible — **58 of them at an identical period end**, so staleness cannot excuse it.
124 of 418 rows carrying all three figures disagree by more than 2%. **4 rows flip
criterion 3 from PASS to FAIL** (PANL 0.52→3.75, CHSCP 0.67→1.17, PRSU 0.02→2.87,
CMLS 0.01→4.61). Largest silent understatements: GS −$28.3bn, WMT −$17.3bn, SCHW −$15.8bn,
CVX −$14.0bn, ON $1.6M against its own $4,504.9M.

**Why the harness missed it.** `coverage.py:614-621` implements exactly this parts-vs-rollup
identity — but runs only on the sampled companies, and the sampler is broken (F30). None of
the four is a pin.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
for r in rows:
    c3=[c for c in r['criteria'] if c['n']==3][0]
    td,ld,sd=r.get('total_debt'),r.get('long_term_debt') or 0,r.get('short_term_debt') or 0
    ca,cl=r.get('current_assets'),r.get('current_liabilities')
    if c3['status']=='PASS' and td and ld+sd>td*1.02 and ca and cl and ca>cl and (ld+sd)/(ca-cl)>1.10:
        print(r['ticker'], c3['value'], '->', round((ld+sd)/(ca-cl),2))"
# PANL 0.52 -> 3.75 / CHSCP 0.67 -> 1.17 / PRSU 0.02 -> 2.87 / CMLS 0.01 -> 4.61
```

**Regression test** — `api/tests/test_enterprising.py`:
```python
def test_a_total_debt_rollup_smaller_than_its_own_parts_is_a_fragment():
    """PANL tags LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities on one
    current line ($38.5M) while its own noncurrent debt is $235.6M (10-Q 0001628280-26-055365).
    A rollup smaller than the components it is supposed to contain is not a total, and
    preferring it turns a 3.75x debt load into a 0.52x PASS."""
    s = snap(current_assets=fact(Decimal("265944000")),
             current_liabilities=fact(Decimal("192184000")),
             total_debt=fact(Decimal("38521000"),
                 tag="us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
             long_term_debt=fact(Decimal("235638000")),
             short_term_debt=fact(Decimal("41155000")))
    c3 = next(c for c in evaluate(s, None).criteria if c.n == 3)
    assert c3.status is Status.FAIL and c3.value == Decimal("3.75")
```

**This also refutes a documented invariant.** HOW-IT-WORKS.md §3 claims *"Error-direction
bias: wherever ambiguity forces a choice, the system errs toward FAIL/INDETERMINATE, never
toward PASS."* Here it errs toward PASS, four times.

---

### F3 · CRITICAL · PARTIAL — The audited fiscal year is shipped as "latest 12 months", and nothing on the page says so

**What the user sees.** AMC Networks: **"P/E · latest 12 months · 7.30×"**, criterion 1
PASS, 3 of 6 met — for a company whose trailing net income *in the same payload row* is
**−$19,751,000**. The criterion note is `null`, `earnings_quality` is `[]`, and the EPS
curve suppresses its dashed TTM point precisely because the figure equals the last annual
value. There is no surface anywhere on the page that names the period.

**What is correct.** When the trailing composite is refused, either the criterion says so
or the figure is withheld. HOW-IT-WORKS.md:132-135 already promises this: *"Falls back to
the latest annual figure … provenance then shows the age"* and *"all three input facts are
returned in the criterion's `inputs`"*.

**Proof.** AMCX 10-Q accn `0001514991-26-000089`,
<https://www.sec.gov/Archives/edgar/data/1514991/000151499126000089/R4.htm>:
```
Net income (loss) attributable to stockholders | (21,943) | 50,289 | (40,813) | 68,338
Diluted (in dollars per share)                 |   (0.51) |   0.91 |   (0.94) |   1.25
Diluted (in shares)                            |   43,016 | 56,350 |   43,320 | 56,482
```
FY2025 10-K accn `0001514991-26-000011`: diluted $1.66 on 56,590 thousand shares. Trailing
dollars: 89,400 − 40,813 − 68,338 = **−19,751 thousand**, matching the payload's own
`ttm_net_income` to the dollar. Shipped instead: 12.12 / 1.66 = 7.30, PASS.

**Code path.** `normalize.py:966, :984, :994, :1005` — five refusal exits, every one
`return (latest.value, (latest,))` with no marker. → `enterprising.py:107` returns
`note=None` → `sync.py:132-137` flattens criteria to `{n, status, value, note}` and **drops
`CriterionResult.inputs`** → `Detail.jsx:69` hard-codes `sub="latest 12 months"`.
`grep -rn earnings_asof web/src` exits 1. `SOURCE_LABELS` (`Detail.jsx:242-250`) has no
`"eps"` key, so `sources.eps` is filtered out of the Provenance table too.

**Affected.** **1,025 rows** substitute the audited year although both YTD legs exist and
matched; 571 differ from the computable composite by more than 10%; **0 of 5,911 disclose
it**. **31 rows ship criterion 1 = PASS on a positive per-share figure while the same
payload row's trailing net income is negative** (AMCX, LIVE, KROS, SCOR, BCIC, SOBR, GCTK,
DRIO, ANGI, PHGE, NXTT, DFNS, FOA, BMNR, SOAR, ENGN, SLXN, MEHA, PRPL, NEXM, QXL, LCGMF,
KG…). Widening to "TTM net income ÷ shares fails P/E < 10" gives 30 more, adding PALL,
CVNA, ENR, TRIN, OTF, SEVN, VIASP, QTTB, ATCH. The P/E is a **sortable column**
(`App.jsx:225, 505`), so these sit at the top of a cheapest-first screen.

> **Corrected by review.** Severity raised MAJOR → CRITICAL: this flips criterion 1's own
> PASS/FAIL on 31 rows, not merely a number. The original claim's "honest trailing figure
> for PALL is $2.46, P/E 9.85" is **wrong** — that composite mixes 24.58M, 32.79M and
> 20.41M weighted-share denominators, the very mixing the guard exists to refuse. PALL's
> defensible trailing figure is $28.364M of net income → $0.92–$1.06 a share → P/E 23–26,
> so PALL belongs in the wrongly-passing set, not outside it.
>
> **Two auditors disagree on the population.** The screener-side scan (both YTD legs present
> and matched) gives **1,025**; a payload-only detector (`ttm_eps` exactly equals the newest
> annual EPS while `ttm_net_income` rolled forward) gives **1,376**; my own re-run of the
> loosest identity gives **1,638**. All three measure different things and none is wrong.
> The number that matters — rows where the substitution flips criterion 1 — is 31.

**Marked PARTIAL** because the disclosure gap is proven and the 31 wrong PASSes are proven,
but the fix boundary is not settled: for many of the 1,025 the audited year is the only
defensible figure available, so "always disclose" is right while "always withhold" is not.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
n=[r['ticker'] for r in rows if any(c['n']==1 and c['status']=='PASS' for c in r['criteria'])
   and (r.get('ttm_net_income') or 0)<0]
print(len(n), n[:12])"   # 31
grep -rn 'earnings_asof' web/src/ ; echo "exit $? (1 = the UI never reads it)"
```

**Regression test** — `api/tests/test_enterprising.py` plus a `web/test/` companion:
```python
def test_refused_per_share_composite_never_ships_a_positive_pe_over_a_loss_year():
    """AMCX 2026-Q2: convertible notes make diluted shares 56.5M in a profit half and 43.3M
    in a loss half, so _shares_incomparable refuses the composite. The dollar composite still
    knows the trailing year is a $19.8M loss, so criterion 1 must not report a positive P/E."""
    c1 = byN(evaluate(_snapshot(ttm_eps=Decimal("1.66"), ttm_net_income=Decimal("-19751000"),
                                shares_outstanding=Decimal("43016000")),
                      _quote(Decimal("12.12"))), 1)
    assert c1.status is not Status.PASS
    assert c1.note and "fiscal year" in c1.note.lower()
```
```js
test("the P/E tile does not claim twelve months when the figure is a fiscal year", () => {
  const row = {ttm_eps: 1.66, earnings_asof: "2025-12-31",
               criteria: [{n: 1, status: "PASS", value: 7.30, note: null}]};
  assert.notEqual(peSubtitle(row), "latest 12 months");
});
```

---

### F4 · CRITICAL · CONFIRMED — Another registrant's statements filed under one CIK are read as a 2.5:1 reverse split

**What the user sees.** Essential Utilities (WTRG): **P/E 7.82×**, criterion 1 PASS, 3 of 6
met, EPS curve drawing FY2023–25 at **4.65 / 5.425 / 5.50**. The company's own 10-K reports
**$2.20**. True P/E **21.05**, criterion 1 a **FAIL**.

**What is correct.** `annual_eps[2025] = 2.20`, TTM = 2.20 + 1.16 − 1.41 = **1.95**,
P/E = 41.05 / 1.95 = **21.05**.

**Proof.** WTRG, CIK 0000078128.
FY2025 10-K, accn `0000078128-26-000050`,
<https://www.sec.gov/Archives/edgar/data/78128/000007812826000050/R4.htm> —
`Net income per common share: Basic $2.20 Diluted $2.20` (FY2024 $2.17, FY2023 $1.86),
net income $616,369K on 280,619K diluted shares. Check: 616,369/280,619 = 2.196.
An **8-K** filed 2026-03-25, accn `0001193125-26-124163`, under the *same CIK*, carries a
different entity's audited statements —
<https://www.sec.gov/Archives/edgar/data/78128/000119312526124163/R4.htm> —
`Net income attributable to common shareholders $1,111 [million]`, diluted **$5.69**
(FY2024 $5.39, FY2023 $4.90), revenue $5,140M against Essential's own $2,474,615K for the
identical FY2025, on **195M** weighted shares.

The engine compares FY2024's 2.17 against 5.39, gets 0.402597, and accepts it because
|0.402597/0.4 − 1| = 0.0065 < the 2% tolerance around the 1-for-2.5 candidate. **One vote,
no dissent** — FY2023 (0.3796) and FY2025 (0.3866) both fail the tolerance and abstain.

**The share counts refute the split outright, and the engine never looks at them.** FY2024
weighted diluted: 274,421,000 (10-K) vs 195,000,000 (8-K) = 1.41×, not 2.5×. A genuine
1:2.5 would require 109,768,400.

**Code path.** `normalize.py:649` `_per_share_periods` pools split evidence with **no form
filter at all** — every `USD/shares` entry with a `start`, whatever form. That asymmetry is
the whole bug: `_annual_series` (:717) *does* filter to annual forms, so the 8-K never
enters the EPS series itself, only the split vote. → `_split_events` (:688) → `_as_split`
(:615) → `_split_factor` (:665) → `_split_adjust` (:806) → `_ttm_eps` (:945) →
`sync.py:666`.

**No guard catches it.** `assumptions` is empty, no context note mentions a split,
`_shares_incomparable` is consulted only for the TTM composite legs and never for
`_split_adjust`, and nothing cross-checks the EPS ratio against the weighted-share ratio.

**Affected.** 205 of 5,911 rows carry a split factor on their newest annual EPS. 3 filers
have a current-anchor multiplier that exists **solely** because of non-periodic-form
evidence: WTRG, PPCB and PALX. **WTRG is the only shipped criterion-1 flip** — the other
two are loss-makers that FAIL either way. Also wrong for WTRG: `pe3` 7.91 vs 19.77,
`alignment.enterprising.valuation` PASS, `base_eps` 4.175.

**Not a cache artifact.** `data.sec.gov/api/xbrl/companyconcept/CIK0000078128/us-gaap/
EarningsPerShareDiluted.json` returns the 8-K entries live, alongside the 10-K's.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; from screener import normalize as N
g=json.load(open('/Users/antonmishanin/.cache/graham-screener/companyfacts_0000078128.json'))['facts']['us-gaap']
print('split events:', N._split_events(N._per_share_periods(g)))
s=N._annual_eps(g); print('FY2025 EPS as used:', s[2025].value, ' TTM:', N._ttm_eps(g,s)[0])"
# [('2026-03-25', Decimal('0.4'))]  5.5  5.25
```

**Regression test** — `api/tests/test_normalize.py`:
```python
def test_another_registrants_statements_in_an_8k_are_not_a_split():
    """Essential Utilities (CIK 78128). An 8-K filed 2026-03-25 under WTRG's CIK carried a
    merger target's audited statements: FY2024 EPS 5.39 on 195M weighted shares against the
    10-K's 2.17 on 274M. The EPS ratio 0.4026 lands inside the 2% window around a 1:2.5
    reverse split, but the share counts move 1.41x, not 2.5x, so no split happened."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        _yr(2023, 1.86, "2026-02-26", "k25"), _yr(2024, 2.17, "2026-02-26", "k25"),
        _yr(2025, 2.20, "2026-02-26", "k25"),
        dur("2024-01-01","2024-12-31", 5.39, form="8-K", accn="8k26", filed="2026-03-25"),
        dur("2025-01-01","2025-12-31", 5.69, form="8-K", accn="8k26", filed="2026-03-25")])
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = tagdata("shares", [
        dur("2024-01-01","2024-12-31", 274421000, accn="k25", filed="2026-02-26"),
        dur("2025-01-01","2025-12-31", 280619000, accn="k25", filed="2026-02-26"),
        dur("2024-01-01","2024-12-31", 195000000, form="8-K", accn="8k26", filed="2026-03-25"),
        dur("2025-01-01","2025-12-31", 195000000, form="8-K", accn="8k26", filed="2026-03-25")])
    s = build(gaap)
    assert float(s.annual_eps[2025].value) == 2.20
    assert float(s.annual_eps[2024].value) == 2.17
```

**Note for the fix.** A blanket "10-K/10-Q only" filter on split evidence is not obviously
right — PPCB's 1:25 restatement in a non-periodic form may well be a genuine reverse split.
**The share-count cross-check is the sound root-cause fix**, since a real split moves
weighted shares by the same factor it moves EPS.

---

### F5 · CRITICAL · CONFIRMED — The whole group's profit divided by the parent's own units: Westlake Chemical Partners looks 5.8× more profitable than it is

**What the user sees.** WLKP: **"Earnings valuation · PASS · 2.29×"** and **"Earnings
stability · PASS · 9.65"** against a $21.72 unit price, **4 of 6 criteria met** — among the
very highest scores on the dashboard, which is exactly what a Graham screener is used to
surface. The annual history shows FY2019 net income of $332.9M and EPS of $9.65 for a
partnership whose unitholders earned $61.0M, or **$1.77 a unit**.

**What is correct.** TTM attributable to unitholders = 48,698 + 28,407 − 19,506 = **$57,599K**
÷ 35,245,879 units = **$1.634 a unit** → P/E **13.29** → criterion 1 **FAIL**.

**Proof.** WLKP, CIK 0001604665.
Q2-2026 10-Q accn `0001604665-26-000027`,
<https://www.sec.gov/Archives/edgar/data/1604665/000160466526000027/R4.htm> —
`Net income 164,017 / Less: Net income attributable to noncontrolling interest in OpCo
135,610 / Net income attributable to Westlake Chemical Partners LP … 28,407`, with
`Common units (basic) $ 0.81` and `Weighted average limited partner units 35,245,879` on
the same statement. **82.7% of the group's profit belongs to Westlake Corp's interest in
OpCo.** The filer's own half-year per-unit figure is $0.81; the engine's implied half-year
figure is 164,017/35,245,879 = **$4.65**.
FY2021 10-K accn `0001604665-22-000009`,
<https://www.sec.gov/Archives/edgar/data/1604665/000160466522000009/R5.htm> — FY2019
`Net Income … Per Outstanding Limited Partnership Unit, Basic $ 1.77` against the payload's
9.65.

**Code path — two independent root causes.**
1. `_has_minority_interest` (`normalize.py:1957-1971`) reads only `StockholdersEquity` and
   `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`. WLKP files
   **neither** — it files `PartnersCapital` 253,713,000 against
   `PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest` 769,413,000, a
   3.03× signal. The permanent-NCI chain (:330-335) also omits
   `MinorityInterestInLimitedPartnerships` ($515,700,000). So `has_nci` is **False**, the
   ProfitLoss guard at `:2007` never fires, and the **annual** derived series is
   ProfitLoss-based too — the payload's own `sources.eps` proves it.
2. The TTM override at `normalize.py:454-457` has no ProfitLoss check of its own, and
   `_annual_dollar_series` (:849-866) ranks `ProfitLoss` above `NetIncomeLoss` for this
   filer on series depth (14 years vs 12).

The engine's own docstring (`normalize.py:1998-2003`) says ProfitLoss "includes
noncontrolling interests, which are not the common shareholder's earnings" and cites ARES.
**This is the project's stated rule being violated, not an outside preference.**

**Affected.** 1 of 5,911. 102 rows use the derived TTM quotient; 18 sit on an income series
including >5% of NCI; **WLKP is the only one where criterion 1 flips**, and it is the
highest-scoring row in the derived set. Beyond criterion 1: `n_pass` 4→3, row `verdict`
INDETERMINATE→FAIL, `alignment.enterprising` EVIDENCE_INCOMPLETE→BLOCKED (a UI filter
category), and the whole EPS curve and P/E3 tile wrong by the same 5.8× (FY2018–21 shown
10.25/9.65/9.69/11.40 against roughly 1.40/1.73/1.88/2.34).

> **Merged.** Reported independently by the criterion-1 and criterion-4 auditors as C1-3
> and C4-3. Same filer, same root cause, one finding. The criterion-4 half is narrower than
> its title claimed: **criterion 4's PASS is correct** (FY2017–21 are positive on either
> basis); only its displayed value is wrong (9.65 against a true $1.53).

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; from screener import normalize as N
f=json.load(open('/Users/antonmishanin/.cache/graham-screener/companyfacts_0001604665.json'))
s=N.build_snapshot('WLKP','0001604665',f); g=f['facts']['us-gaap']
print('shipped ttm_eps', s.ttm_eps)
print('income tag used:', N._annual_net_income(g)[2025].provenance.tag)
print('parent-only per unit:', N._ttm_eps(g, N._annual_dollar_series(g,('NetIncomeLoss',)),
      unit=('USD',), per_share=False)[0]/s.shares_outstanding.value)"
```

**Regression test** — `api/tests/test_normalize.py`:
```python
def test_partners_capital_filer_with_a_minority_interest_derives_no_profit_loss_eps():
    """The Ares guard reads StockholdersEquity, which a partnership never files. Westlake
    Chemical Partners consolidates an OpCo whose sponsor owns two thirds of it: FY2019
    ProfitLoss 332,895k against 60,981k attributable to unitholders, on 34,488,058 units.
    The 10-K reports $1.77 a unit (accn 0001604665-22-000009); ProfitLoss/units is $9.65."""
    gaap = {k: v for k, v in GAAP.items() if k != "EarningsPerShareDiluted"}
    gaap["ProfitLoss"]    = tagdata("USD", [dur("2019-01-01","2019-12-31", 332_895_000, accn="k21", filed="2022-03-02")])
    gaap["NetIncomeLoss"] = tagdata("USD", [dur("2019-01-01","2019-12-31",  60_981_000, accn="k21", filed="2022-03-02")])
    gaap["WeightedAverageNumberOfShareOutstandingBasicAndDiluted"] = tagdata("shares",
        [dur("2019-01-01","2019-12-31", 34_488_058, accn="k21", filed="2022-03-02")])
    gaap["PartnersCapital"] = tagdata("USD", [inst("2026-03-31", 253_713_000, accn="q126")])
    gaap["PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"] = tagdata(
        "USD", [inst("2026-03-31", 769_413_000, accn="q126")])
    gaap["MinorityInterestInLimitedPartnerships"] = tagdata("USD", [inst("2026-03-31", 515_700_000, accn="q126")])
    eps = build(gaap).annual_eps.get(2019)
    assert eps is None or float(eps.value) == pytest.approx(1.77, abs=0.01)
```

**Fixing only cause (1) is not enough.** With `has_nci` True, every WLKP annual_ni fact
carries the ProfitLoss tag, the `:2007` guard skips them all, `derived_eps` is empty, the
`if derived_eps:` gate at `:443` never opens, and criterion 1 lands on INSUFFICIENT_DATA —
not the FAIL at 13.29. Reaching the correct answer needs the TTM to prefer the
parent-attributable tag, or to subtract `NetIncomeLossAttributableToNoncontrollingInterest`.

---

### F6 · CRITICAL · CONFIRMED — Market cap, P/E, P/B and P/NCAV are wrong by the ADS ratio for every depositary-receipt filer

**What the user sees.** BeOne Medicines (ONC): **Mkt cap $554B** — 5th on the market-cap
sort — **P/E 876.42×, P/B 107×, P/NCAV 172×, NCAV/share $2.19**. Correct: ≈$43B, ≈67×,
≈8.2×, ≈13×, ≈$28.44/ADS. Akanthos (AKTX) shows **$1,106B**. Zai Lab **$30B**.

**What is correct.** `shares` is the **ordinary**-share count; `price` is the **ADS** price.
Nothing reconciles them. Market cap must divide by the ADS ratio, or the share count must
be converted.

**Proof.** ONC 10-Q cover, accn `0001628280-26-052878`,
<https://www.sec.gov/Archives/edgar/data/1651308/000162828026052878/R1.htm>:
```
Title of each class: American Depositary Shares, each representing 13 Ordinary Shares
Trading Symbol(s): ONC
Entity Common Stock, Shares Outstanding: 1,478,124,405
```
1,469,278,815 × $376.86 = **$553.7bn**, exactly what the payload multiplies. Divided by 13:
$42.6bn.

**Code path.** `App.jsx:156` `mcap: r.price && r.shares ? r.price * r.shares : null`;
`Detail.jsx:32` the same; `sync.py:227-265` divides every book value by the same
unconverted count. The ADS ratio is on the filing cover and is never read.

**Affected.** Every ADR filer in the universe. Confirmed multiples: ONC 13:1, AKTX 2,000:1,
ZLAB 10:1, SLN 3:1. All are visible under the default filters and rank high on the
market-cap sort, which is the first thing a user sorts by.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
for t in ('ONC','AKTX','ZLAB','SLN'):
    r=[x for x in rows if x['ticker']==t][0]
    print(t, 'mcap $%.1fB' % (r['shares']*r['price']/1e9), 'P/B %.1f' % (r['price']/r['bvps']))"
```

**Regression test** — `api/tests/test_sync.py`: assert that a filer whose cover names
"American Depositary Shares, each representing N Ordinary Shares" either carries the ratio
in the payload or ships no market cap at all. Missing beats wrong.

---

### F7 · CRITICAL · CONFIRMED — 14 rows price a preferred series against the common's fundamentals

**What the user sees.** Southern California Edison's preferred (`SCE-PM`): **Mkt cap $9.4B,
P/B 0.5×, NCAV/share −$181.44** — a $24.39 par-25 preferred quote multiplied by 385M
**common** shares. Visible under the default view. Oaktree's `OAK-PA` renders **P/E 8.06×,
3 of 6 met** and will surface as a cheap Graham candidate. `CFTR-PA` renders P/E 419×.

**What is correct.** A preferred series is not the common. Either exclude non-common share
classes from the universe, or carry the security type so the row can decline to compute
per-share figures.

**Proof.** The universe contains 14 `-P*` tickers: CTA-PB, SCE-PM, CDR-PB, ANG-PD, OAK-PA,
TWO-PC, ATH-PA, PRIF-PD, SRG-PA, CFTR-PA, ICR-PA, PHXE-P, CMS-PB, ETI-P. `sources/prices.py`
fetches the preferred quote; every per-share figure on the row is the issuer's common.

**Affected.** 14 of 5,911. Two are dangerous rather than merely absurd: OAK-PA at
P/E 8.06 with 3 criteria met, and ANG-PD which passes criterion 4.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
print([r['ticker'] for r in rows if '-P' in r['ticker']])"
```

**Regression test** — `api/tests/test_sync.py`:
```python
def test_universe_excludes_non_common_share_classes():
    """SCE-PM is a $25-par preferred; the row's book value and share count are the common's,
    so price x shares reads 9.4B and NCAV/share reads -181.44."""
    assert not _tradeable_common("SCE-PM")
    assert not _tradeable_common("OAK-PA")
    assert _tradeable_common("BRK-B")
```

---

### F8 · CRITICAL · CONFIRMED — Item 3.01 is read as trouble; Walmart, Palantir, Linde and Shopify are labelled "Listing deficiency" for transferring listing

**What the user sees.** Under "What the multiples do not say": **"Listing deficiency —
Item 3.01 filed 2025-11-20: notice of failure to satisfy a continued listing rule, or of
delisting. A price is only a price while the shares have an exchange to trade on."** On
Walmart.

**What is correct.** The official item title is *"Notice of Delisting or Failure to Satisfy
a Continued Listing Rule or Standard; **Transfer of Listing**"*. The code reads the number
only and cannot tell the two apart.

**Proof.** Walmart 8-K accn `0000104169-25-000177`,
<https://www.sec.gov/Archives/edgar/data/104169/000010416925000177/wmt-20251119.htm>, whose
exhibit is literally named `pressrelease-transfertonas.htm`:
> "Item 3.01. … On November 19, 2025, the Company … notified the New York Stock Exchange …
> of its intention to **voluntarily withdraw** the listing of its common stock … and
> **transfer the listings to The Nasdaq Stock Market LLC**"

**Code path.** `profiles.py:326` maps item 3.01 to the deficiency string. The file's own
comment (`profiles.py:308-315`) says items that "cannot tell a dismissal from an AGM
election" are excluded — 3.01 belongs in that excluded class.

**Affected.** **1,451 notes**, the second-largest note kind in the payload. The flagship
names are exactly the false ones.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
n=[r['ticker'] for r in rows if any(x.get('kind')=='Listing deficiency' for x in (r.get('context_notes') or []))]
print(len(n), [t for t in ('WMT','PLTR','LIN','SHOP','PANW') if t in n])"
```

**Regression test** — `api/tests/test_profiles.py`:
```python
def test_transfer_of_listing_is_not_a_listing_deficiency():
    """Item 3.01 also covers a voluntary transfer of listing (Walmart, 2025-11-20,
    accn 0000104169-25-000177). The item number alone cannot tell the two apart."""
    row = {"balance_sheet_date": "2026-07-31", "events_from": "2020-01-01",
           "filing_events": [{"filed": "2025-11-20", "item": "3.01",
                              "accn": "0000104169-25-000177"}]}
    assert "Listing deficiency" not in {n["kind"] for n in filing_event_notes(row)}
```

---

### F9 · CRITICAL · CONFIRMED — A fiscal year re-dated by a week loses its restatement: ATI fails on a loss the company has since restated to a profit

**What the user sees.** ATI Inc: **"Earnings stability · FAIL · −0.3"** with the note
*"negative EPS in FY 2021"*. The EPS curve and annual history show FY2021 −0.30 and FY2022
0.96, both superseded.

**What is correct.** ATI's fiscal 2021 is the 52 weeks ended 2022-01-02 at **$1.32**
diluted, and fiscal 2022 ended 2023-01-01 at **$2.23**. FY2021–FY2025 are all profits →
criterion 4 **PASS**, minimum 1.32.

**Proof.** ATI, CIK 0001018963.
FY2023 10-K, accn `0001628280-24-006606`,
<https://www.sec.gov/Archives/edgar/data/1018963/000162828024006606/R3.htm> — columns
`Dec. 31, 2023 | Jan. 01, 2023 | Jan. 02, 2022`:
`Sales | $ 4,173.7 | $ 3,836.0 | $ 2,799.8` · `Net income attributable to ATI | $ 410.8 |
$ 323.5 | $ 184.6` · `Diluted … per common share | $ 2.81 | $ 2.23 | $ 1.32`.
FY2022 10-K, accn `0001628280-23-005017`, same rows for 2021-12-31: `$ 2,799.8`,
`$ (38.2)`, `$ (0.30)`.
**Sales are identical at $2,799.8M in both presentations** — one fiscal year re-dated, not
two periods. Cause proven, not guessed: R58 of the FY2023 10-K is *"Change in Accounting
Principle (Details)"* showing FY2021 nonoperating retirement-benefit income restated from
37.2 to 260.0.

**Code path.** `normalize.py:780-781` `_fy_labels`: `if guess in taken: continue`. The
calendar period 2021-12-31 carries an SEC frame of `CY2021` and is labelled first; the
re-dated 2022-01-02 infers the label 2021, finds it taken, and is **dropped**. The value
kept is the older filing's −0.30 — the exact inverse of the latest-filed-wins rule stated
one screen earlier at `normalize.py:741` and in HOW-IT-WORKS.md §2.1.

**Affected.** 116 companies drop an annual EPS period to a label collision; 21 drop a
same-fiscal-year re-dating. A full-universe rescan from raw facts found **7 (company, year)
pairs restated by more than 5% across a near-duplicate end, in 4 companies**, and the
payload follows the **superseded** filing in exactly three: **ATI FY2021 and FY2022** (both
inside criterion 4's window) and **JCI FY2014** (11 years outside it). In HQI FY2018,
JCI FY2015, ONTO FY2017 and ONTO FY2018 the engine is right.

> **Corrected by review.** The original claim named five companies as materially harmed.
> Only ATI is. ONTO, HQI and JCI FY2015 show the payload correctly keeping the *later*
> filing; YUM's difference is 0.7%.

Blast radius for ATI: criterion 4 badge FAIL where PASS is correct, `n_pass` 1 instead of 2,
`alignment.enterprising` 1/6, `growth_modern_4fy.base_eps` −0.3 instead of 1.32, two wrong
points each on the EPS curve and the annual history (net income −$38.2M/$130.9M instead of
$184.6M/$323.5M), and `epsEvidence` reporting 7 of 10 positive instead of 8. `context_notes`
is empty — no warning. ATI's row verdict is FAIL either way (criteria 1, 3, 5 and 7 also
fail), so no company enters or leaves the screen.

**Repro.**
```sh
cd api && .venv/bin/python .../audit/c4-eps-series/near_duplicate_ends.py 15
```

**Regression test** — `api/tests/test_normalize.py`. The existing pin
(`test_overlapping_period_never_invents_a_later_year`) is about ends **months** apart and
must keep working:
```python
def test_fiscal_year_redated_by_a_week_keeps_its_restatement():
    """ATI moved fiscal 2021 from 2021-12-31 to 2022-01-02 and restated it in the same filing
    (retirement-benefit accounting change; sales unchanged at $2,799.8M). The re-dated end
    must not be discarded as a label collision: latest-filed wins."""
    eps = [kdur("2020-01-01","2020-12-31",-12.43,"2023-02-24","CY2020"),
           kdur("2021-01-01","2021-12-31", -0.30,"2023-02-24","CY2021"),
           kdur("2021-01-04","2022-01-02",  1.32,"2024-02-23"),
           kdur("2022-01-01","2022-12-31",  0.96,"2023-02-24","CY2022"),
           kdur("2022-01-03","2023-01-01",  2.23,"2025-02-21"),
           kdur("2023-01-02","2023-12-31",  2.81,"2026-02-20","CY2023"),
           kdur("2024-01-01","2024-12-29",  2.55,"2026-02-20","CY2024"),
           kdur("2025-01-01","2025-12-28",  2.85,"2026-02-20","CY2025")]
    gaap = dict(GAAP); gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", eps)
    s = build(gaap)
    assert float(s.annual_eps[2021].value) == 1.32
    assert float(s.annual_eps[2022].value) == 2.23
    assert 2026 not in s.annual_eps          # a re-dated end never invents a year
    c4 = next(c for c in evaluate(s, None).criteria if c.n == 4)
    assert c4.status is Status.PASS and float(c4.value) == 1.32
```

**Fix belongs in `_annual_series`/`_fy_labels`:** cluster annual ends within ~15–20 days
into one fiscal year *before* labelling, then apply latest-filed-wins inside the cluster.
Clustering is safe — two genuine annual periods cannot both be 340–400 days long and end
two days apart, and a 52/53-week transition stub is too short to survive the duration
filter. HOW-IT-WORKS.md:104 states the rule as "the same period end filed multiple times",
which literally covers only identical dates; widen the sentence with the code.

---

### F10 · CRITICAL · CONFIRMED — Criterion 4 is decided on windows that closed a decade ago

**What the user sees.** Berkshire Hathaway B: **"Earnings stability · PASS · 6,214.96"**
beside a $499.62 price. The five years behind that badge are **FY2010–FY2014**, and
Berkshire lost **$22,819M in FY2022**. Hershey PASSes on FY2010–FY2014. Plains All American
on FY2012–FY2016. Liberty Media on FY2011–FY2015.

**What is correct.** Graham's test is the last five fiscal years, not the last five on file.
When the newest fiscal year on file trails the company's own balance sheet, criterion 4
should be INSUFFICIENT_DATA naming the last year it could measure.

**Proof.** Berkshire FY2022 10-K, accn `0000950170-23-004451`,
<https://www.sec.gov/Archives/edgar/data/1067983/000095017023004451/R4.htm> —
`Net earnings (loss) attributable to Berkshire Hathaway shareholders | $ (22,819) | $ 89,795
| $ 42,521`, Class A `$ (15,535)`, Class B `$ (10.36)`. FY2022 is a deficit squarely inside
the past five fiscal years from any 2026 vantage. The payload shows criterion 4 = PASS with
6,214.96 — FY2011's Class-A-equivalent EPS — on a row whose price is $499.62 for a Class B
share.

**Code path.** `enterprising.py:171-172` `latest = max(s.annual_eps); window = range(latest-4,
latest+1)`, with **no call to `_stale_against`** — contrast criterion 1 (`:92-98`) and
criterion 7 (`:273-278`), which both have one. The upstream cause is that `annual_eps`
terminates in 2014 for share-class-axis filers: Hershey's FY2025 10-K tags EPS under
`us-gaap_StatementClassOfStockAxis`, which Company Facts drops
(<https://www.sec.gov/Archives/edgar/data/47111/000162828026008586/R122.htm> shows
`$ 4.34 | $ 10.92 | $ 9.06` under `CommonStockMember`).

**Affected.** 164 rows get a PASS or FAIL on a window ending FY2023 or earlier; 23 are PASS;
19 end FY2022 or earlier. **Five ship a PASS that the same row's own `annual_net_income`
refutes**: BRK-B (deficit FY2022), FWONA (FY2024), AYR (FY2021), PBHC (FY2025), SFRX (every
year FY2021–25). No grade label moves, but for BRK-B the entire `n_pass = 1` **is** that
false PASS, so the row survives the "Min criteria met ≥ 1" filter on the strength of a
FY2010–FY2014 window.

> **Corrected by review.** Severity raised MAJOR → CRITICAL. Three framing errors in the
> original: (a) the claimed contrast "criteria 1 and 7 say INSUFFICIENT_DATA for exactly
> that reason" holds for PAA, FWONA, SFRX and PBHC but **not** for either headline company —
> HSY's c1/c7 both FAIL for unrelated reasons on fresh 2026-06-28 data, BRK-B's say "price
> quote unavailable" and "missing: shares outstanding"; (b) the panel is not silent — the
> Annual financial history table shows EPS "—" against filled net income for FY2015–FY2025;
> (c) **Hershey, the headline example, is a correct PASS** (FY2021–25 diluted EPS all
> positive) — only the displayed 2.21 is twelve years old. The claim led with its weakest case.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; d=json.load(open('screener/static/dashboard.json'))
rows=[(r['ticker'],max(int(y) for y in r['annual_eps']),[c for c in r['criteria'] if c['n']==4][0])
      for r in d['rows'] if r.get('annual_eps')]
print([(t,y,c['value']) for t,y,c in rows if y<=2022 and c['status']=='PASS'])"
```

**Regression test** — `api/tests/test_enterprising.py`:
```python
def test_a_window_that_ends_years_before_the_balance_sheet_is_not_a_clean_record():
    """Berkshire's undimensioned EPS stops at FY2014 (its per-share facts sit on a share-class
    axis Company Facts cannot express) while it kept filing through FY2025 -- including a
    $22.8bn deficit in FY2022. The last five years ON FILE are not 'the past five fiscal
    years': a window closing years before the company's own balance sheet cannot certify a
    clean record."""
    c = crit(evaluate(snap(eps_years={2010:"7927.68", 2011:"6214.96", 2012:"8977.20",
                                      2013:"11849.50", 2014:"12091.59"},
                           balance_sheet_date=date(2026, 6, 30)), QUOTE))[4]
    assert c.status is Status.INSUFFICIENT_DATA and "2014" in c.note

def test_a_current_window_still_passes():
    """The guard must not punish an annual-only filer between 10-Ks."""
    assert crit(evaluate(snap(balance_sheet_date=date(2026, 6, 30)), QUOTE))[4].status is Status.PASS
```

**The staleness guard is a floor, not the cure.** Applied alone it leaves HSY and BRK-B with
no earnings-stability judgment at all, when the data to make one is already on the snapshot:
`models.py:87` carries `annual_net_income` to FY2025 for both, and the screen never reads it.
Anchor recency on `snapshot.balance_sheet_date` (already in-layer, keeps the screen
clock-free), not on the quote. 140 further rows have a newest EPS year of FY2024, which any
450-day rule against an August-2026 price also catches.

---

### F11 · CRITICAL · CONFIRMED — A one-cent revision of a two-cent quarter is read as a stock split

**What the user sees.** Idaho Copper's EPS curve shows FY2010 at **$0.187** when every
filing says **$0.14**; its whole pre-2021 record is 33% too high. Apple's annual history
shows FY2007–FY2009 at **1.5×** their true split-adjusted values.

**What is correct.** A restatement from −$0.02 to −$0.01 is rounding, not a corporate
action. `_as_split` (`normalize.py:615-625`) accepts any ratio within 2% of 1.5, 2, 2.5, 3 …
100 or their reciprocals, with no floor on the magnitude of the per-share values doing the
voting.

**Proof.** COPR: restatements of −0.02 → −0.01 and −0.03 → −0.02 produce a "0.5 split" and a
"1.5 split", rescaling every pre-2021 year by 1.333 (FY2013 shown −0.1467 against −0.11 as
filed). AAPL: the 2010 revenue-recognition restatement (1.35 → 2.01 = 1.489) reads as a
2:3 split. The distortion is one-sided — only years filed **before** the phantom event move,
so the series develops a step at an arbitrary filing date.

**Affected.** **627 split events across 441 companies are voted for by per-share values of
$0.05 or less**; 636 more by values of $0.25 or less. 1,165 companies have a split the
share counts do not corroborate — an upper bound, because the corroboration test false-alarms
whenever a filer reports annual share counts in only one vintage. **The $0.05-magnitude
subset, 441 companies, is the defensible figure.**

**Repro.**
```sh
cd api && .venv/bin/python .../audit/c4-eps-series/split_magnitude.py 0.05
```

**Regression test** — `api/tests/test_normalize.py`:
```python
def test_a_cent_level_revision_is_not_a_split():
    """COPR restated a -0.02 quarter to -0.01 and a -0.03 quarter to -0.02. Ratios of 0.5 and
    1.5 land on split candidates, but a one-cent move on a two-cent figure is rounding. The
    engine rescaled the whole pre-2021 record by 1.333."""
    gaap = dict(GAAP)
    gaap["EarningsPerShareDiluted"] = tagdata("USD/shares", [
        _yr(2013, -0.11, "2015-03-30", "k14"),
        dur("2020-01-01","2020-03-31", -0.02, form="10-Q", accn="qa",  filed="2020-05-10"),
        dur("2020-01-01","2020-03-31", -0.01, form="10-Q", accn="qa2", filed="2021-05-10"),
        _yr(2024, -0.03, "2025-03-30", "k24")])
    s = build(gaap)
    assert float(s.annual_eps[2013].value) == -0.11   # unrescaled
```
**Fix:** require the voting per-share values to clear a materiality floor (a few cents), and
require share-count corroboration before a split event is recorded — the same cross-check
F4 needs.

---

### F12 · CRITICAL · CONFIRMED — `growth_10y = 4.7e+32 %` ships, and the defensive growth test passes on it

**What the user sees.** Ultralife's detail panel renders, under **"Earnings growth · ≥ 33⅓%
over 10 years"**, the string
**`+470,000,000,000,000,000,000,000,000,000,000%`** with a **PASS** chip. Equinix ships
**+23,164.3%** and **+10,421.4%**, also PASS. 42 rows carry a growth ≥ 10,000%.

**What is correct.** `ch13._growth` (`ch13.py:23-31`) rejects a non-positive base — the
"criterion-6 lesson" its own docstring cites — but tests **sign only, never magnitude**.
ULBI's FY2013–15 EPS sum to exactly 0 in rationals; the payload prints `avg_old: 0.0` beside
a growth of 4.7e+32. EQIX's block is $1.89, −$4.96, $3.21 → average $0.047. BMRA's is
$0.07, −$0.03, −$0.04 → exactly $0.00.

**Proof.** ULBI's EPS series is itself a 100× filer error, ground-truthed at
<https://www.sec.gov/Archives/edgar/data/875657/000143774926009385/R4.htm> — the header
reads *"shares in Thousands, $ in Thousands"* and the line reads
`Net (loss) income per share … Diluted $ (35) | $ 38` against
`(Loss) income attributable to Ultralife (5,898) | 6,312` and
`Weighted average shares – Diluted 16,642`, i.e. true EPS **−$0.35 / $0.38**. The payload
carries EPS −35.0 beside net income −$5,898,000 and 16,663,269 shares with no reconciliation
note, and `AnnualFinancialHistory.jsx:25` prints the implied count as **0.2M** against the
16.7M it shows elsewhere.

**Code path.** `ch13.py:26` `if recent is None or earlier is None or earlier <= 0: return
None` → `ch13.py:101` → `profiles.py:460` `Decimal(str(growth_10y)) >= Decimal("33.3333333333")`
→ `Detail.jsx:179`.

**Affected.** 21 rows quote a growth against a base displaying as $0.00; 29 have a base under
10% of that block's own scale; 42 exceed 10,000%; 103 exceed 1,000%. 4 rows disagree with a
`Decimal` recomputation of their own `stability_years`.

**A second, separate rounding defect at the same threshold.** `ch13.py:28` rounds growth to
one decimal **before** it is used as a decision input. **RVTY and NFBK both grew exactly
33⅓%** (5.80/3 ÷ 4.35/3 = 4/3 and 1.60/3 ÷ 1.20/3 = 4/3, confirmed with exact rationals).
Rounded to 33.3 they fail a 33.3333333333 threshold and the panel shows **FAIL** — while
the table's own sparkline (`EarningsEvidence.jsx:35`, unrounded `>= 100/3`) paints them
**green**. Two surfaces of the same app give opposite answers for the same company.

**Repro.**
```sh
cd api && .venv/bin/python -c "
import json; rows=json.load(open('screener/static/dashboard.json'))['rows']
g=[(r['ticker'],r['ch13']['growth_10y'],r['ch13']['avg_old']) for r in rows
   if r.get('ch13') and (r['ch13'].get('growth_10y') or 0)>10000]
print(len(g), sorted(g,key=lambda x:-x[1])[:4])"
```

**Regression test** — `api/tests/test_ch13.py`:
```python
def test_growth_needs_a_material_base_not_merely_a_positive_one():
    """ULBI's FY2013-15 block averages ~3e-30 and survives `> 0`, shipping 4.7e+32 percent
    under 'Earnings growth >= 33 1/3% over 10 years' with a PASS chip. EQIX's averages $0.047
    across a loss year and ships +23,164%."""
    eps = {2013: Decimal("1.89"), 2014: Decimal("-4.96"), 2015: Decimal("3.21"),
           2018: Decimal("5"), 2019: Decimal("6"), 2020: Decimal("7"),
           2023: Decimal("9"), 2024: Decimal("10"), 2025: Decimal("11")}
    assert eps_stats(eps)["growth_10y"] is None

def test_growth_is_compared_unrounded():
    """RVTY grew exactly 33 1/3%. Rounding to 33.3 before a 33.3333333333 threshold turns a
    PASS into a FAIL, and disagrees with the table's own sparkline, which compares unrounded."""
    eps = {2013: Decimal("1.40"), 2014: Decimal("1.45"), 2015: Decimal("1.50"),
           2023: Decimal("1.90"), 2024: Decimal("1.93"), 2025: Decimal("1.97")}
    assert _defensive_growth(eps_stats(eps)) == "PASS"
```

---

### F13 · CRITICAL · CONFIRMED — The share count and the EPS series sit on different bases; SM Energy and NRC Health pass criterion 1 on it

**What the user sees.** SM Energy: **P/E 6.41×, PASS**, 3 of 6 met. NRC Health: **P/E 0.44×,
PASS**, 3 of 6 met.

**What is correct.** SM: $648,000,000 of FY2025 net income ÷ 237,494,374 shares = **$2.73**
→ P/E **13.25 → FAIL**. NRC: $11,600,000 ÷ 22,139,315 = **$0.52** → P/E **41.9 → FAIL**.

**Proof.**
**SM Energy** 10-Q balance-sheet parenthetical,
<https://www.sec.gov/Archives/edgar/data/893538/000089353826000121/R3.htm>:
```
Common Stock, Shares Authorized   400,000,000 | 200,000,000
Common Stock, Shares Outstanding  237,494,374 | 114,630,905     (Jun 30 2026 | Dec 31 2025)
```
Authorized **and** outstanding both doubling is a 2-for-1 split. The share count is
post-split; the whole `annual_eps` series (2022 8.96 … 2025 5.64) is pre-split and was never
rebased. `bvps` $32.90 and every per-share book figure are on the new base while EPS is on
the old one. **No note in `context_notes` or `earnings_quality` mentions the change.**
**NRC Health**: its FY2025 10-K (`0001437749-26-007002`) tags `EarningsPerShareDiluted` =
**50.00** for CY2025, while the quarters inside that same year in the same dataset are 0.25,
−0.01, 0.18 and the 9-month figure is 0.43 — a 100× filer scale error, the identical mistake
Ultralife makes. A filer error, but **the payload carries the disproof in the adjacent field
and ships the PASS anyway.**

**Code path.** No cross-check exists between `annual_eps × shares` and `annual_net_income`.
`_implied_shares` (`normalize.py:2438-2456`) computes exactly this quantity for the share
sanity vote, and criterion 1 never consults it.

**Affected.** Restricting to the 2,780 rows with no NCI, no preferred and no
continuing-operations EPS element: 2,026 reconcile (0.8–1.25×), **487 are off by more than
1.5×**, 36 have opposite signs. 111 of the 487 are explained by real post-year-end dilution —
a legitimate timing wedge. **23 of the 487 currently ship criterion 1 = PASS**, including SM,
NRC, WTRG (F4) and SNEX. NRC's market cap is $487M, just under the default $500M floor —
visible at any lower floor, and it sorts first on P/E ascending.

**SNEX**, verified against the live SEC API
(`companyconcept/CIK0000913760/us-gaap/CommonStockSharesOutstanding.json`): the same instant
2025-09-30 carries **three** values — 52,186,635 / 78,279,953 / 117,419,470 — from three
successive filings. Market cap shown $7.94bn instead of ~$3.45bn; `bvps` $23.70 and `tbvps`
$17.58 are each 2.3× too low; criterion 7 shows 3.76× against a true ~1.63×.

**Repro.**
```sh
cd api && .venv/bin/python .../audit/consistency/eps_x_shares.py
```

**Regression test** — `api/tests/test_enterprising.py`:
```python
def test_criterion_1_refuses_an_eps_its_own_net_income_contradicts():
    """SM Energy split 2-for-1 (authorized and outstanding both doubled, 10-Q R3). The share
    count is post-split and annual_eps is not, so EPS x shares is 2.07x the row's own net
    income and a P/E of 13.25 shipped as 6.41 PASS."""
    s = snap(ttm_eps=Decimal("5.64"), shares_outstanding=fact(Decimal("237494374")),
             annual_net_income={2025: fact(Decimal("648000000"))})
    c1 = byN(evaluate(s, _quote(Decimal("36.14"))), 1)
    assert c1.status is not Status.PASS
```

---

## MAJOR

Twenty findings where a shipped number is wrong but no criterion verdict flips. Each row
carries what the user sees, the proof, the code path, and the population.

### F14 · MAJOR · PARTIAL — An antidilutive convertible trips the share-comparability guard

**User sees.** AMCX P/E 7.30 "latest 12 months" PASS; LIVE 2.03; FOA 5.38; MSGM 2.76;
VIASP 9.49. **Correct.** AMCX trailing EPS is **−0.53** (or −0.45 on basic, or −0.46 on the
dollar route — all negative, so criterion 1 is FAIL on any of them).
**Proof.** AMCX 10-Q `0001514991-26-000089` (quoted in F3): diluted shares **equal** basic in
every loss column (43,320/43,320) and exceed it in every profit column (56,482 vs 44,845).
That is antidilution on the face of the filing; the **basic** count moved 3.4%, not 30%.
**Code path.** `normalize.py:993` → `_shares_incomparable` (`:1178`), which returns on the
**first** tag in `_WEIGHTED_SHARE_TAGS` holding both legs — the diluted tag — so the basic
evidence at `:1186` is never reached. Threshold `_SHARE_INCOMPARABLE = 0.25` (`:202`).
**Affected.** **13 rows, bidirectional.** 5 wrong PASSes (AMCX −0.53, LIVE −1.20, FOA −0.34,
MSGM true P/E 13.17, VIASP 29.79) and **8 wrong FAILs** where the loss sat in the *prior*
period (GPRE shipped −1.80 against a composite +1.67, RLYB −1.59 → +5.00, MDRR −1.90 → +3.97,
INR 0.89 → 2.96, FBIO, TYGO, CNOB, BKV).

> **Corrected by review.** Severity CRITICAL → MAJOR, and the claimed scope cut ~3×. The
> original named 15 tickers; **for 10 of them the basic ratio also exceeds 0.25**, so the
> guard fires on a genuine discontinuity and reading the basic tag would change nothing
> (KROS 1.06, BCIC 0.35, OTF 0.32, TRIN 0.36, DFNS 4.68, JCAP 42.1, **BMNR 202.2**, GCTK 9.0,
> SOAR 11.2, MEHA 3.5). BMNR's share count moved by a factor of 203 — subtracting per-share
> figures across that is exactly what the guard exists to refuse. Two of the five real flips
> are not the antidilution case either: VIASP is the mirror image (Class B counted in the
> current diluted figure and not the prior), and FOA/MSGM are genuine ~22% basic-share moves
> straddling the threshold on the noisier leg.

**Fix is not the 0.25 threshold.** `_shares_incomparable` should take the **minimum** ratio
across the tags that have both legs, or prefer the basic tag, which no antidilution rule can
move. Note the machinery already exists 300 lines up: `normalize.py:454` `income_is_newer`
covers this exact situation but is gated behind `if derived_eps:` and never runs for a filer
that tags its own per-share figures.
**Repro.** `.venv/bin/python .../audit/c1_2_flip_detail.py`
**Test.** Assert `_shares_incomparable` is `False` for AMCX's four share facts, and that
`_ttm_eps` returns `Decimal("-0.53")`. Both fail on HEAD.

### F15 · MAJOR · PARTIAL — The derived trailing EPS omits preferred dividends and carries a seven-year-old zero forward

**User sees.** WHLR: **P/E 0.04×, PASS**, 2 of 6 met — a market valuing the company at
fifteen days of earnings.
**Correct.** Earnings available to common give **$5.14 a share** and a P/E of **0.07** (still
a PASS; the number is wrong, the verdict is not).
**Proof.** WHLR 10-Q `0001527541-26-000251`,
<https://www.sec.gov/Archives/edgar/data/1527541/000152754126000251/R4.htm>:
`Net Income (Loss) Attributable to Wheeler REIT | 6,242,000` ·
`Preferred Stock dividends - undeclared | (3,274,000)` ·
`Attributable to Common Shareholders | 1,881,000`. The preferred line's element is
`us-gaap:OtherPreferredStockDividendsAndAdjustments`.
**Code path.** `normalize.py:454-457` computes `(ttm_net_income − ttm_preferred_dividends) /
shares`, and `ttm_preferred_dividends` is 0 for two compounding reasons: (a)
`PREFERRED_DIVIDEND_TAGS` (`:154-158`) holds only three tags, none of them the one WHLR
files; (b) WHLR's last `PreferredStockDividendsIncomeStatementImpact` fact **ends 2019-12-31
with value 0**, and `_ttm_eps` falls through to "annual anchor stands in for TTM", carrying a
seven-year-old zero forward as this year's preferred dividends — the exact failure mode
CLAUDE.md's "stale facts are missing facts" invariant exists to prevent, with the 400/450-day
floors not applied to this series. Meanwhile the filer tags exactly the figure the derived
path wants (`NetIncomeLossAvailableToCommonStockholdersBasic`) and `_annual_dollar_series`
ranks `NetIncomeLoss` above it on depth.
**Affected.** 102 rows use the derived quotient; 6 are criterion-1 PASS; 8 of 11 sampled
override rows differ materially from the tagged path, 3 with a sign flip.

> **Corrected by review.** The original diagnosis — "no share-count comparability guard" — is
> wrong. `_shares_incomparable` is *deliberately* gated on `per_share` (`:990-993`, "a dollar
> total adds and subtracts across periods regardless of how many shares were outstanding"),
> and each dollar leg was verified against the filing. Cloning the per-share guard onto a
> dollar sum would suppress a valid total. The original's "20× share move" also compares two
> different reverse-split bases; within the single filing that restates both legs the move is
> ~13,600×. And "on any consistent basis WHLR is not a 0.04 P/E" is false — every consistent
> basis leaves criterion 1 a PASS far under 1.

**Secondary, structural.** The override's own justification — "filers that tag EPS only on a
share-class axis publish no per-share element (KKR since 2017, PAA since 2016)" — does not
describe WHLR, which tags `EarningsPerShareDiluted` in every filing. The override fires only
because the gate is `if derived_eps:` and one historical year made it non-empty. That gate is
what discards `_shares_incomparable`'s deliberate refusal at `:993`. Narrow it to "the filer
has no tagged per-share element covering the trailing window".

### F16 · MAJOR · CONFIRMED — Derived EPS is bounded by nothing: criterion 4 reports −$20,176,748.50 a share

**User sees.** Aditxt's "Earnings stability" reads **−20,176,748.5** for a stock priced at
$0.002. American Rebel −17,604,364. Wheeler −150,500. Empire Diversified −187,796.71.
Hershey's curve spikes to **$1,903.95** in FY2009 between $1.37 and $2.21, flattening the
decade onto the axis, and its history table shows 0.2M implied shares.
**Correct.** `normalize.py:205-208` states the rule: *"No share has ever earned this much in
a year… A figure above this is a dollar total the filer tagged into a per-share element."*
Hershey's FY2009 diluted EPS is **$1.90**.
**Proof.** HSY FY2011 10-K, accn `0001193125-12-067143`,
<https://www.sec.gov/Archives/edgar/data/47111/000119312512067143/R1.htm>, *"In Thousands,
except Per Share data"*: FY2009 `Net income $435,994`, `Net Income Per Share - Diluted -
Common Stock $ 1.90`. The screen prints **1002× the filing**, because that same 10-K tagged
FY2009 diluted shares as **228,995** (thousands) while the 2011 filing had 227,845,000
(units). WHLR FY2025 10-K,
<https://www.sec.gov/Archives/edgar/data/1527541/000152754126000050/R5.htm>: FY2024
`Diluted $ (346,484.38)` on `64` shares — and the screen prints −150,500, a number appearing
in no WHLR filing (it is −9,632,000/64, the derived formula with the preferred deductions
omitted).
**Code path.** The `_IMPLAUSIBLE_EPS` ceiling is applied inside `_annual_eps` at
`normalize.py:803`; `_derived_annual_eps` is merged at `:444`, **afterwards**. The existing
pin (`tests/test_normalize.py:878`) carries no `NetIncomeLoss` and no share count, so it
never exercises the derived path.
**Affected.** 8 payload EPS values exceed the engine's own ceiling, **all 8 derived**, and
**4 are the printed criterion-4 value**. 21 derived observations exceed $200/share across 10
companies. 106 derived years across 68 tickers use a share count ≥20× or ≤1/20 the filer's
own median. No status, verdict or grade moves — division by a positive count preserves sign.
**Two distinct causes, both needed.** HSY and BRK-B are filer **unit** errors the ceiling
cannot catch (1,903.95 < 100,000) and need a share-count scale/continuity test. ADTX, AREB,
WHLR and EMPD are genuine retroactive reverse-split restatements where the sole defect is
that the ceiling does not bound the derived series — the engine deletes the filer's
impossible figure and substitutes its own.
**Caveat.** Applying the ceiling alone moves the printed values to −27,038 / −63,214 /
−13,158 / −2,602 — still absurd, because the surviving tagged years sit on three different
post-split bases. The ceiling fixes the magnitude, not the comparability.

### F17 · MAJOR · CONFIRMED — ROIC has no denominator floor; 75 rows print |ROIC| > 1000%

**User sees.** AnaptysBio ($1.7B cap, visible by default): **ROIC 3,157%**,
green-highlighted, passing the "15%+ (exceptional)" filter, **3rd on the ROIC sort**. CAPC
−111,823%. GRTX −104,932%. ALUR −21,874%.
**Correct.** `normalize.py:1944` guards only `if invested > 0`. ANAB's assets are $329.7M and
its invested capital nets to **$1.527M** — 0.46% of the balance sheet.
**Affected.** 75 rows exceed |1000%|. **Fix:** floor invested capital as a share of total
assets, or suppress and add a caveat below the threshold.

### F18 · MAJOR · CONFIRMED — Owner-earnings components have no magnitude cross-check

**User sees.** InspireMD: **"+ depreciation & amortisation $476.0M"**, **"Owner earnings
$424.7M"**, **"Return on invested capital 9,284.2%"** — for a company with `total_assets`
$44.6M. First on the ROIC sort.
**Proof.** The filer's own 10-K (`0001493152-26-010886`) tags, for the identical FY2025
period, `DepreciationAndAmortization = 476,000,000` **and** `Depreciation = 476,000`. A 1,000×
filer scale error, sitting beside its own refutation in the same filing.
**Affected.** 1 proven; the class is unbounded — no component is ever sized against the
balance sheet. **Fix:** reject a flow component that exceeds total assets.

### F19 · MAJOR · CONFIRMED — ROIC divides a fiscal-year flow by a balance sheet years newer

**User sees.** Veeva **ROIC 252.36%** from FY2019 flows against a 2026-04-30 balance sheet —
while the same row's `annual_operating_income` runs to FY2025 at $916,369,000 against the
$286,219,000 used. NTIP 149.15% (FY2011 flows, 2026 sheet). GE, TJX, JNJ likewise.
**Code path.** `normalize.py:1908-1944` takes `owner` from the newest year all four flow
series share and `invested` from the current snapshot, with no staleness guard and nothing in
`caveats`.
**Affected.** **257 rows ≥2 years apart, up to 15 years. 20 of them clear the "15%+
(exceptional)" ROIC filter.** 214 rows have a year in their own `annual_operating_income`
newer than `fiscal_year + 1`.

### F20 · MAJOR · CONFIRMED — One "balance sheet" stitched from several period ends

**User sees.** DOMH passes criterion 2 at **27.54×** on current assets of $206,328,000 dated
2025-09-30 divided by total assets of $57,412,000 dated 2026-06-30 — a classified balance
sheet the company stopped filing. Solidion Technology (STI) shows **Current ratio 1.46×,
Working capital $9.0M, FAIL** from 2026-06-30 assets over **2025-06-30** liabilities.
**Proof.** STI 10-Q accn `0001213900-26-086220`,
<https://www.sec.gov/Archives/edgar/data/1881551/000121390026086220/R2.htm>: at Jun 30 2026
`Total Current Assets 28,443,515`, and the liabilities section lists only current items
summing to `Total Liabilities 10,692,506` with **no noncurrent section**. True current ratio
**2.66 — a PASS**.
**Code path.** `_STALE_DAYS = 400` (`normalize.py:164`) is a **lower bound only**: each slot
independently takes its own latest instant on or after the floor, with no requirement that it
be no newer than, or equal to, the anchor. `_derived_instant` (`:1591`) refuses mixed period
ends explicitly, and TAGS.md:59 says the liabilities derivation "requires identical period
ends" — the rule exists everywhere except here.
**Affected.** **2,715 of 5,911 rows carry more than one period end among their balance-sheet
figures**, widest span 4,595 days. Downstream impossibilities: current assets > total assets
(8 rows), current liabilities > total liabilities (28, 3 at the same date), LTD > total
liabilities (48, 14 same-date), STD > current liabilities (61, 16 same-date), goodwill +
intangibles > total assets (19), ncavps > bvps (8), ncavps > tbvps (32, 5 at one date).
**39 rows divide the current ratio across two dates**, gaps of 90–820 days. **578 of the
2,542 tbvps rows (22.7%) mix period ends**; 147 by more than 185 days. **27 rows'
`balance_sheet_date` names a date their own total assets do not carry** (`normalize.py:472-474`
takes it from current assets first) — ESMC labels 2026-03-31 against a 2026-06-30 assets
figure; TGLO labels 2026-06-30 against total assets dated **2018-06-30**.
**The Provenance table does print each figure's `end`**, so the evidence is on the page — but
the snapshot grid, criteria 2/3, all three book values and the defensive `financial_position`
combine them as if they were one statement.

### F21 · MAJOR · CONFIRMED — Non-USD figures are read as dollars

**User sees.** Enbridge: **Working capital "$-6.9B"**, **Current assets "$17.7B"**, and a
dividend yield of **7.61%** where the USD-correct figure is ≈5.5%. Criterion 4 values: ENB
1.28, CP 3.77, IMO 3.48, CGC −132.78, NEXM 5.00 — all Canadian dollars rendered with a "$".
**Proof.** ENB 10-Q accn `0001193125-26-326752`,
<https://www.sec.gov/Archives/edgar/data/895728/000119312526326752/R7.htm>, header:
*"CONSOLIDATED STATEMENTS OF FINANCIAL POSITION - **CAD ($)** $ in Millions"*;
`Current assets | 17,720`. The payload carries 17720000000.0 and the UI prefixes "$".
**Code path.** `normalize.py:574-580` `_entries(taxo, tag, ("USD",))` returns the USD bucket
when present and otherwise `next(iter(units.values()))` — **whatever unit happens to be
first**. There is no currency check anywhere in the chain, and `sync.py:151-153` writes a bare
float.
**Affected.** 6 filers on the current pair (ENB, CP, IMO, NEXM, CGC CAD-only; SSM EUR-only);
5 on the EPS series; 12 (company, tag) pairs where the chain's declared unit is absent
entirely. The unit-based per-share detector (`normalize.py:2618`) reads the **chain's**
declared unit, not the unit the returned entries carry, so the same fallback silently changes
what the number means.
**Note.** SSM reports `Assets` in both EUR and USD while `AssetsCurrent` is EUR-only — total
assets and current assets in different currencies on one row.

### F22 · MAJOR · CONFIRMED — Debt buckets both understate and double-count

Four distinct mechanisms in `normalize.py:1274-1465`, all reaching `Detail.jsx:75-76`.

| Mechanism | Code | What ships | Population |
|---|---|---|---|
| Additive instrument slots run only `if primary is None` | `:1283-1351` | WisdomTree's `ConvertibleDebtNoncurrent` **$1,057,600,000** dropped because a 2025-09-30 `LongTermNotesPayable` of $13,564,000 satisfied the primary chain (10-Q `0001214659-26-009661`) | **6 PASS rows flip to FAIL**: WT, MIR, VOYG, NP, HIVE |
| Primary chain tie broken by chain order, so a footnote fragment outranks the balance-sheet line | `:1275-1280` | Carriage Services shows **$14.4M** where the 10-Q's balance-sheet `LongTermDebt` is **$526,016,000** and `LongTermDebtNoncurrent` $5,411,000 is a footnote fragment (accn `0001016281-26-000055`) | **5 PASS rows flip**: CSV, HLIO, DTI, CLNN, SKYX; 5 more understate without flipping |
| Current-maturities dedupe is scoped to one tag pair and needs an exact period-end match | `:1414-1420` | **60 rows ship a short-term debt larger than their own total current liabilities.** LITE ships $6.477B against $3.865B of current liabilities; IBM ships $11.547B where its 10-Q says $5.775B | 27 confirmed double counts of 308 at-risk rows |
| `_sum_facts` includes every fresh component regardless of period end | `:1468-1490` | AMD sums `LongTermDebtCurrent` $875M @2026-06-27 with `ShortTermBorrowings` $874M @2025-12-27; the filer's own combined figure at 2026-06-27 is $3,226M = 2,351 + 875 | 431 long-bucket and 316 short-bucket sums mix ends |

Also: **56 rows understate long-term debt** against the filer's own same-date elements —
Avis shows $6.0B where `LineOfCredit` is **$18.468B** at the same date
(10-Q `0000723612-26-000028`); Allegiant shows $29.5M against a `LongTermDebt` of $2,779M.

**And SRI ships a superseded figure.** 10-Q accn `0001043337-26-000074`,
<https://www.sec.gov/Archives/edgar/data/1043337/000104333726000074/R2.htm> —
`Revolving credit facility  151,089  |  180,942` (current | 2025-12-31). The payload ships
**180,942,000** from the prior year end, 19.8% high, while `LongTermLineOfCredit` =
151,089,000 @2026-06-30 sits in the cache from the very filing the rest of the row is built
on. Cause: `LongTermLineOfCredit` lives inside the `if primary is None` branch, so a fresher
LOC can never beat a stale primary. TAGS.md §3.4 states the fix as "latest-period-end
selection **plus the LOC family**"; only the first half, and only within one family, was built.

### F23 · MAJOR · CONFIRMED — `apply_price` erases every disclosure the engine wrote

**User sees.** Nothing — which is the defect. **846 price-settled rows default preferred
stock to 0 and none carries the note**; **60 rows deduct mezzanine equity and none carries
the note**. Not one instance of either string survives anywhere in the 39 MB payload.
**Correct.** `enterprising.py:276-279` builds the notes correctly (*"no preferred-stock value
tagged; defaulted to 0 (flagged per §5.1)"*, *"mezzanine (temporary) equity deducted…"*), and
TAGS.md §1.3, HOW-IT-WORKS.md §2.5 and §3 all promise them.
**Code path.** `sync.py:678-679` `crit[7].update(status=…, value=ptbv, note=None)`; same for
criterion 1 at `:666-667`. Any row with a price loses the disclosure.
**Test.** `test_apply_price_keeps_the_engine_s_disclosures` — settle the ratio, keep the note.

### F24 · MAJOR · CONFIRMED — Criterion 5 passes on payouts that are not the common's

**User sees.** Boeing: criterion 5 **PASS**. **Proof.** `us-gaap:PaymentsOfDividends`
172,000,000 for the six months to 2026-06-30 **equals** `us-gaap:DividendsPreferredStock` for
the identical period; the 10-Q cash-flow line reads *"Dividends paid on mandatory convertible
preferred stock (172)"* and there is **no common dividend line**. Wynn's `DividendsCommonStockCash`
of 94,939,000 is the **total** row: `Cash dividends declared ( 51,890 ) ( 43,049 ) ( 94,939 )` —
$51.9M to Wynn shareholders plus $43.0M to noncontrolling interests
(<https://www.sec.gov/Archives/edgar/data/1174922/000117492226000055/wynn-20260630.htm>).
**Code path.** `PREFERRED_DIVIDEND_TAGS` exists (`normalize.py:151-158`) but `_dividend`
never consults it; the exclusion regex (`:145-150`) contains "preferred" but applies **only**
to the unknown-status scan, never to the 14 chained tags.
**Affected.** **56 PASS rows provably rest on a non-common payout.** 203 rows rest on an
aggregate tag and 164 of those show a yield; the provenance concept string
*"Dividends (aggregate — may include preferred and noncontrolling)"* is built at
`normalize.py:2666` and then **discarded** by `sync._source` (`:54-66`), which emits only
tag/form/accn/end/filed. **0 of 203 rows carry the disclosure.**

### F25 · MAJOR · CONFIRMED — `dividend_per_share` has no staleness guard

**User sees.** Apple: **$0.87 per share over twelve months**. Its Q3 FY2026 10-Q states $0.79
declared for nine months against $0.76 prior year on a FY2025 base of $1.02 → **$1.05**
(<https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/aapl-20260627.htm>). The
$0.87 is a **FY2017** aggregate.
**Code path.** `normalize.py:2597-2632` — when the TTM composite cannot be built, the stale
annual value is returned unchanged. Unlike `ttm_revenue` (`:478-483`) and the price criteria
(`sync.py:645-658`), there is no age check.
**Affected.** **82 of 1,813 rows (4.5%) rest on evidence older than 450 days; 40 older than
five years** — SKT and KMPR from FY2010 (5,660 days), LEVI FY2011, WYNN FY2012. **No
provenance is emitted for `dividend_per_share` at all** (0 of 1,813), which is what makes this
invisible: AAPL's `sources.dividend` points at the fresh 2026 10-Q beside a 2017 number.
**Related.** The quarterly-rate guard `_is_a_rate_not_a_total` (`:2573-2593`) is net positive —
it correctly rejects ~50 filers whose annual per-share element repeats the quarterly rate —
but has no guard against `0 == 0` in a pre-dividend year (26 of 125 triggers) or a
once-a-year payment (17 more). That is why AAPL's whole 2010–2025 series was discarded.

### F26 · MAJOR · CONFIRMED — The dividend streak survives a suspension

**User sees.** Wynn Resorts: **"Dividend record — 18 years (from 2009)"**. Wynn suspended its
common dividend from Q2 2020 to Q4 2022. 2021 is kept alive by `PaymentsOfDividends` of
**$1,553,000** and 2022 by $1,445,000 — dividend-equivalent residuals against a $95M
half-year run rate — plus a stray `CommonStockDividendsPerShareCashPaid` of 1 dated 2021-03-31.
**Code path.** `normalize.py:2648-2652` walks back while calendar years are consecutive; a
year counts if **any** positive fact ends in it.
**Affected.** **222 streaks span a year whose entire payout is under a tenth of that
company's own median year.** Ford's 2020 counts although it suspended in March 2020.

### F27 · MAJOR · CONFIRMED — The yield cap is unreachable; 29 rows ship a yield above 100%

**User sees.** NSARO renders **"2,240,506.33% yield"** and the note *"$1,770,000.00 per share
over twelve months"*.
**Correct.** `enterprising.py:27, 210` defines `_YIELD_IMPLAUSIBLE` with the comment *"A yield
above par is arithmetic, not information"* — and it is never reached, because
`sync.apply_price` overwrites `crit[5]["value"]` with no cap.
**Affected.** 29 rows above 100%; 65 more between 20% and 100% whose legitimacy is untested.
**Same root cause as F23**: the live path (`apply_price`) reimplements what the screen already
decided, and drops the screen's guards on the way.

### F28 · MAJOR · CONFIRMED — "Unknown rather than FAIL" fires on tags that cannot be a payment

**User sees.** BJ's Wholesale, MicroStrategy, Celsius, CoreWeave and 214 others show criterion
5 as **INSUFFICIENT_DATA · "dividend status could not be established"**.
**Code path.** `normalize.py:2669-2688` treats **any** us-gaap tag containing "dividend" or
"distribut", outside the chain and outside a small exclusion regex, with any positive entry in
400 days, as grounds to withhold a verdict.
**Affected.** **218 of 645 INSUFFICIENT rows are unknown solely because of a non-chained tag,
and ~150 of those tags cannot be a payment at all** —
`AmountAvailableForDividendDistributionWithoutAffectingCapitalAdequacyRequirements` (a capacity
disclosure), `DividendsPayableCurrent` (a balance-sheet instant),
`AdjustmentsToAdditionalPaidInCapitalDividendsInExcessOfRetainedEarnings`,
`RevenuesExcludingInterestAndDividends`, `ShareBasedCompensation…WeightedAverageExpectedDividend`.
Conservative in direction, but it withholds a verdict Graham's criterion could give.

### F29 · MAJOR · CONFIRMED — Three share-count selection defects and one blind spot

| Defect | Code | Proof | Rows |
|---|---|---|---|
| No rule prefers a fresher count over an older one — the 400-day floor is the only guard | `normalize.py:164, 251-255` | MCHB ships a count dated 2025-06-30 beside a 2026-06-30 balance sheet; ABTC 366 days; BETA 273 days | 26 rows ≥120 days stale against a >1.5×-different count from the same filer |
| SPAC class fallback picks the founder class | `:2068-2093` `_unambiguous_dimensioned` requires exactly one class per concept; the public class sits in temporary equity under a different concept | LPAA ships **5,750,000** (`CommonClassB`) while `TemporaryEquitySharesOutstanding` is **23,000,000** | 31 rows |
| Warrant-overhang note takes an instant with **no** freshness floor | `:2337-2348` — `_latest_instant(…, "WarrantShares")` with no `not_before` | GM's warrant fact of 136,000,000 is dated **2009-12-31** against a 2026-06-30 balance sheet — 16.5 years | **251 of 373 notes (67%)** rest on evidence >400 days stale |
| Two-witness dual-class rule needs a 1.5× gap and treats same-accession facts as independent | `:2506-2510` | Boeing's cover and weighted average agree within 0.15% and both sit **28% below** the chosen count; nothing fires | 15 firings, 486 rows label a weighted average as "Shares outstanding" |

Also: **the implied-shares column in the annual history table omits preferred dividends**
while its Python twin subtracts them. OXY FY2025 prints **3,509.6M implied shares** beside a
reported count of 999.7M; netting the preferred gives 2,503.7M. 1,903 rows print a count more
than 10% from the count the same panel shows, 576 beyond 2×, 120 beyond 10×; 158 are explained
by the missing preferred term (`AnnualFinancialHistory.jsx:25-32`).

### F30 · MAJOR · CONFIRMED — The coverage harness's sector strata sample nobody

**Claim.** TAGS.md §4.3 rel 3c: *"Harness widened to 40 companies across 13 strata + 40 pins:
40/40 clean, PASS."*
**Reality.** `coverage.py:365-369` selects rows where `r.get("mcap")` is truthy. **`mcap` is
not a field of `dashboard.json`** — it is computed client-side in `App.jsx:156`. Verified:
`any("mcap" in r for r in rows)` → `False`. Every stratum list is empty; `picked` never grows
past `PINNED`. The harness's own output says `sampled 40 companies` — exactly `len(PINNED)`.
Thirteen strata × `PER_STRATUM = 6` is dead code.
**Consequence.** This is why F2 survived: `coverage.py:614-621` implements precisely the
parts-vs-rollup check that catches PANL/CMLS/PRSU/CHSCP/ON, and none of them is a pin.
**Repro.** `cd api && .venv/bin/python -m screener.coverage` → "sampled 40 companies".
**Test.** `assert len(coverage._sample(rows)) > len(coverage.PINNED)`.

### F31 · MAJOR · CONFIRMED — Toolbar counts describe 5,911 rows; the table shows 1,990

**User sees.** With the app's own defaults (`view.js`: minCap $500M, `hideNoApply` true):
"≤ NCAV" reads **132** and one row qualifies; "Judged on all 6" reads **4,393** against 896;
"3/6 and above" reads **725** against 462. Selecting Sector = Technology still shows
"Nasdaq 2,730".
**Code path.** `App.jsx:257-298` — `metCounts`, `naCount`, `netNetCount`, `noApplyCount`,
`positiveEpsCounts`, `sectorCounts`, `profileCounts`, `exchanges`, `indexCounts` all
`useMemo(…, [rows])`, never `[view]`.
**Also.** **523 priced rows carry no share count**, so `mcap` is null and
`(r.mcap ?? 0) >= minCap` silently removes them at the default floor while the header still
says 5,911 — including **Visa and Berkshire Hathaway**. And `App.jsx:462` caps the table at
`view.slice(0, 300)`.

### F32 · MAJOR · CONFIRMED — 276 notes take a percentage of a negative pre-tax base

**User sees.** Air Products: *"Restructuring charges of 2,929M **reduced** pre-tax income … —
**1440% of that period's −203M pre-tax income**."* Also INTC (27% and 26% of −14,765M), GTN
(222% of −9M), GT, OLN.
**Code path.** `normalize.py:1119` gates on `abs(pretax)`; `:1132` prints the share. A share
of a loss is not a share, and the direction word is inverted.

### F33 · MAJOR · CONFIRMED — One auditor transition split across two 8-Ks is reported as two changes

**User sees.** Fastenal: *"**2 changes of certifying accountant** since 2021-07-01 … signed by
a succession of firms, none of them for long."*
**Proof.** Two Item 4.01 filings, 197 days apart, describing **one** KPMG→Deloitte transition:
<https://www.sec.gov/Archives/edgar/data/815556/000081555624000033/fast-20240719.htm> (the
committee approves the change) and
<https://www.sec.gov/Archives/edgar/data/815556/000081555625000068/fast-20240719.htm> (*"On
February 6, 2025, KPMG completed its audit … and its dismissal was effective immediately
thereafter"*).
**Code path.** `profiles.py:277` `_ONE_TRANSITION_DAYS = 90`. Same shape at MOG-A (110d),
MELI (109d), RNR (185d), of 670 notes.

---

## MINOR

Seven wrong labels and explanations. The status and the number are right; the sentence is not.

| # | Finding | User sees | Reality | Rows |
|---|---|---|---|---|
| **F34** | **Criterion 1 blames the quote when the missing input is the EPS** | Berkshire, Visa and Exxon show *"price quote unavailable"* directly beneath a Price tile of $499.62 / $365.54 / $164.77 | `enterprising.py:90` `missing = "price quote" if q is None else "TTM EPS"`, and `sync.py:97/107` evaluates every snapshot with `quote=None`, so the "TTM EPS" arm is unreachable at derive time. `apply_price` rewrites criterion 7's stale note (`:637-645`, pinned by a test) and was never given the same treatment for criterion 1 | **823 of 1,005** have a live price and no `ttm_eps` |
| **F35** | **The staleness note says an active filer "stopped filing"** | BAM, PAA, PAGP, COKE, CQP, WW, Fubo, Clearway: *"newest earnings are N years older than this price; the company appears to have stopped filing"* | BAM filed a 10-Q on **2026-08-10**, nine days before the price. Verified against `data.sec.gov/submissions/` for BAM, PAA and COKE. `sync.py:651-653` emits it from the date gap alone with no check of the newest filing — while `screener.db`'s `company.last_filing` column already holds 2026-08-10 for both BAM and PAA | **111 of 273** filed within 200 days of the price, 69 within 30 days |
| **F36** | **"1 years"** | 104 rows print `1 years` | `gap // 365` truncating; true gaps 451–723 days, **79 of them 1.5 years or more** | 104 |
| **F37** | **The displayed ratio contradicts the verdict beside it** | EMN shows **1.50×** under "Current ratio ≥ 1.50" marked **FAIL** (raw 1.498239) while DKS shows 1.50× **PASS** (raw 1.500865). GDRX **1.10×** under "≤ 1.10" **FAIL** (1.10222). CBKM and CNX **1.20×** under "Price < 1.20 ×" **PASS** (1.1960, 1.1952) | The criteria compare unrounded Decimals; `Detail.jsx:342` prints two. The codebase already has a stated policy for exactly this (`profiles.py:515-522`: *"the defensive valuation comparison follows the same two-decimal ratios displayed in the interface"*); the six Chapter-15 criteria do not follow it | **9** |
| **F38** | **"Net current assets" is literally the same variable as "Working capital"** | Every company shows the identical string twice, one row apart | `Detail.jsx:30` `const nca = workingCapital;` | **5,911** |
| **F39** | **Negative money renders as `$-26.2B`** | Walmart's working capital | `Detail.jsx:351` interpolates the sign inside the number, after the currency symbol | **1,336** |
| **F40** | **The EPS curve draws a gapped series as continuous, and counts the TTM point as a loss** | VAL is missing FY2021, so FY2020 (−24.42) is drawn adjacent to FY2022 (2.33). Gilead, Boston Beer, Teleflex, Trimble, Ziff Davis and Stepan read *"1 of 14 figures is a loss"* with the **entire curve painted red** while criterion 4 passes on the same series | `EpsCurve.jsx:22-24, 39` spaces x by array index, not by year; `:53-54, 67` computes `losses` over `values`, which includes the appended dashed TTM point | 269 gapped; 22 falsely red |

**Also MINOR, same class:** criterion 4 is labelled **"EPS > 0"** in README, HOW-IT-WORKS §3
and `screen.js:9` while the code tests `>= 0` (*"Chapter 15 says 'no deficit'. A zero year is
not a deficit"*) — **63 companies PASS with a year of exactly 0.00**, one of them (GFMH)
rendering **"0 of 10 positive years"** beside a PASS chip. The "N100" badge covers **94**
constituents, and "Nasdaq Comp" is `exchange == "Nasdaq"` (2,730 rows), making that badge and
its filter a restatement of the Exchange filter. `P/NCAV` prints up to **6,425,308×** with no
ceiling. 18 figures win the "latest instant" pick on a period end **after their own filing
date** — PMT's long-term debt is dated **2030-09-30**, AAGH's is **0.0 dated 2031-12-31**
(precisely the stale-zero trap `_latest_instant_across`'s docstring warns about, reached
through the date instead of the tag order), MTEX's dividend is dated **2108-11-14**.

---

## NIT

**F41 · The client-side price mirror that four documents promise does not exist.**
CLAUDE.md's invariant (*"the same arithmetic is mirrored in `web/src/screen.js` … Change one →
change both"*), TAGS.md:136, TAGS.md:141 and the `apply_price` docstring (`sync.py:633`) all
assert a mirror. `grep -rn "ttm_eps\|tbvps\|PE_MAX\|applyPrice" web/src` returns three lines,
all inside `priceToPass()` — a *different* calculation, imported by no module and covered by
no test. `git log --follow -- web/src/screen.js` returns a single commit and
`git log --all -S "applyPrice" -- web/src/` returns nothing: **the mirror was never removed,
it was never built**. `screen.js:1-2` ("a price refresh needs no backend call") is false too —
the Refresh button POSTs `cmd: "export"` and the SPA refetches `dashboard.json`.

> **Corrected by review.** Severity MINOR → NIT: nothing reaches the screen. Also, the
> original claim flagged the wrong line. `9.99 * ttm_eps` at `screen.js:101` is **correct** —
> criterion 1 is strict (`price < 10.0 × eps`), so `10.0 × eps` itself fails and any concrete
> "price at which it would pass" must sit strictly below. The genuinely inconsistent line is
> the next one, `screen.js:102`: `1.2 * row.tbvps` **fails** the equally strict criterion 7
> (`price < 1.20 × tbvps`, pinned by `tests/test_profiles.py:108-110`, *"equality is not a
> pass"*). The original's MKL arithmetic was also wrong: 9.99 × 181.19 = 1810.09, not 1809.09.

**F42 · The second Notes block never renders a kind.** All `earnings_quality` entries are
bare strings, so `Detail.jsx:233 <b className="note-kind">` never fires under "What the
trailing earnings are made of". The v56 promise holds only for `context_notes`. The Notes
subtitle (`Detail.jsx:109`) also omits two kinds it renders — **Acquisition-only book** (753
notes) and **Valuation allowance** (265).

---

## Documentation defects

Seven claims in the repo's own documents are false against the shipped code. They are listed
separately because they misdirect maintainers rather than users.

| # | Document | Claim | Reality |
|---|---|---|---|
| **D1** | HOW-IT-WORKS.md §3 | *"any `INSUFFICIENT_DATA` → `INDETERMINATE` … else any `FAIL` → `FAIL`"* | Backwards. `enterprising.py:57-69` and `sync.py:683-688` both put FAIL first, and CLAUDE.md states it correctly. **3,478 rows carry both statuses and all 3,478 ship `verdict: FAIL`** — 59% of the universe would be INDETERMINATE under the documented rule |
| **D2** | HOW-IT-WORKS.md §3 | *"Error-direction bias … never toward PASS"* | F2: four criterion-3 PASSes from a fragment rollup |
| **D3** | TAGS.md §1.3 · HOW-IT-WORKS.md §3 | `NCAV = (CA − TL − preferred)/shares`; `TBV = A − L − gw − int − preferred − NCI` | Both omit **temporary (mezzanine) equity**, which `sync.py:225-266` deducts. 22 of 101 sampled filers differ from the documented NCAV formula, and **INGR flips sign** (+0.412 documented vs −0.365 shipped) — the difference between having net current asset value and not, which is what the P/NCAV column and the net-net filter key off. Mezzanine is the entire point of the GTN fixture the same document celebrates |
| **D4** | TAGS.md §3.1/§3.3 (the KO worked example) | *"Intangibles — MISSING"*, *"Criterion 7 is INSUFFICIENT for KO"* | Landed at v38, twenty engine versions ago — §4.3 of the same file says so. Shipped: `intangibles: 12,463,000,000`, `tbvps: 1.3385`, criterion 7 **FAIL at 67.5** |
| **D5** | TAGS.md §3.2 | KO short-term debt 4,743, total debt 43,808, debt/NCA 5.47 | Three different numbers for one company. Filing (accn `0001628280-26-028802`, R4): 4,825 / 43,890 / 5.48. Payload: 4,799 / 43,558 / 5.44 — it sums a `OtherShortTermBorrowings` from a **superseded period end** and then discards KO's entire "Loans and notes payable" line to the F2 rollup |
| **D6** | TAGS.md §4.3 rel 4b | *"216 companies' EPS series now reach the present (KKR 2017→2025, **PAA 2016→2025, PAGP 2014→2025, CQP**)"* | The cover-count fallback was **removed** after v46; `normalize.py:1974-1986`'s own docstring says so. PAA's `annual_eps` ends **2016** and criterion 1 reads *"the company appears to have stopped filing"* for a filer that filed a 10-Q for 2026-06-30. PAGP has two years. KKR reaches 2025 via v53's dimensioned reader, not this feature |
| **D7** | TAGS.md §2.1/§4.1 | *"Defects in what we read today"*; *"All 12 chain defects in §2.1 were independently confirmed against the current code"* | **8 of 12 are fixed.** Defect 6 was fixed at v49, *before* the review that claims to confirm it. Still live: #1 (stale-zero selection, partial — F22/SRI), #3 (`LongTermNotesPayable` mis-ranked), #4 (derived-liabilities double-subtraction of redeemable NCI — 35 rows incl. CMCSA, ACN, ADM: `redeemable_nci` at `:337` is gated only on `parent_only_derivation`, never on `liabilities_derived`, while `temporary_equity` at `:378` **is**), #12 (debt evidence has no recency bound) |

Plus stale counts throughout §4.3 (series_mix 3,159→3,212; windowed 1,045→1,066;
dividend_20y 3,744/342/1,810→3,761/348/1,802; ROIC 2,978/774→2,982/775; pytest 210→284;
payload 33.7 MB→39.2 MB; universe 5,903→5,911), TAGS §1 omitting ~65 shipping elements
including the very tag behind F2, one materially wrong SIGNALS.md frequency
(`PaymentsToAcquirePropertyPlantAndEquipment` claimed 53%, measured 69.8% — it is the
denominator of the proposed "growth bought, not built" ratio), and the v49 untaxed-profits
headline that has moved from **689 to 162** with nothing recording that a shipped Graham
signal shrank by 77% under a rule nobody changed.

---

## 3. Verified correct

This is the bulk of the audit's value. Everything below was recomputed independently and
agreed. **Where an agreement rate is not 100%, every difference was traced and classified.**

### 3.1 The criteria themselves

| Item | Formula as implemented | Sample | Agreement |
|---|---|---|---|
| **c1 = price / ttm_eps**, PASS iff `Decimal(price) < Decimal("10.0") * Decimal(eps)`, strict | `enterprising.py:106`, `sync.py:666` | all 5,911 rows | **5,911/5,911** exact, status and value |
| **c2 = CA / CL**, PASS iff `CA >= 1.50 * CL`, non-strict, decided on raw Decimals | `enterprising.py:121-122` | 4,418 scored rows | **4,418/4,418** |
| **c3 = debt / (CA − CL)**, PASS iff `debt <= 1.10 * nca` | `enterprising.py:157-159` | 1,738 rows | **1,738/1,738** (arithmetic; the *basis* is F2) |
| **c4 = min EPS over FY(L−4..L) ≥ 0** | `enterprising.py:166-190` | all 5,911, recomputed from `row.annual_eps` alone | **5,911/5,911** status, value **and note text** |
| **c5 yield = dps / price × 100** | `sync.py:668-671` | 1,798 rows | **1,798/1,798** to the cent |
| **c7 = price / tbvps**, PASS iff `price < 1.20 * tbvps` | `sync.py:672-679` | 1,595 rows | **1,595/1,595** |
| **n_pass, verdict precedence, criterion numbering {1,2,3,4,5,7}** | `sync.py:684-691` | all 5,911 × 3 | **5,911/5,911** |
| **Enterprising alignment tests vs the criteria they mirror** | `profiles.py` | all 5,911 | **0 disagreements** |
| **Defensive `financial_position` vs the CA/CL/LTD printed beside it** | `profiles.py:430-440` | 2,4xx rows | **0 disagreements** |

Boundary behaviour is right everywhere it was probed. Exactly one row prints a P/E of "10"
(AGO, raw 10.003989, **FAIL**) — the display rounds across the line, the status does not, and
that is the documented and tested behaviour (`tests/test_profiles.py:96-100` pins
"9.999 must pass while displaying 10.0"). The `>= 1.50` boundary is inclusive as documented
(CA=150/CL=100 PASS; 149.99 FAIL). The `>= 2×` defensive boundary likewise (SMP 2.00342 PASS,
G 1.995611 FAIL). Zero current liabilities → INSUFFICIENT_DATA, never a division by zero
(3 rows). Zero-EPS years are treated as no deficit, deliberately and consistently (63 rows).

### 3.2 Extraction

| Item | Sample | Agreement | Notes |
|---|---|---|---|
| **TTM EPS = latest FY + current YTD − prior-year YTD**, all three legs from the same tag | 70 hand-picked names, then all 5,911 | **68/70** hand sample; 3,856 of 4,924 comparable rows exact or within 1% | KO 3.18 = 3.04 + 0.91 − 0.77; META 26.55; GOOGL 19.93; ABT 3.57. The 1,067 population differences decompose exactly into F1/F3/F5/F15 plus 195 DERA-sidecar rows (my blind spot) |
| **`annual_eps` from annual forms only, 340–400 day durations** | all 5,911, independent rebuild | 21/22 named fixtures exact | MSFT 19/19 years, KO 19/19, and JPM/ABT/WMT/DUK/DTE/BIIB/TMUS/META/AMD/INGR/HEI/MAA/EPD/ARCC/LEVI/PAA all exact. 52/53-week years (363–370d) correctly inside |
| **Restatement rule: latest-filed wins per period end** | all 5,911 | 5,900/5,911 unambiguous | AAPL FY2009 correctly takes 9.08 (10-K/A) over 6.29. HON's prior-year leg correctly taken post-restatement (8.26, not 4.13) so both legs sit on one share basis |
| **`current_assets` / `current_liabilities`: single-tag, latest end then latest filed, financial forms only** | all 5,911, recomputed from raw JSON with no screener import | **5,911/5,911 exact on both legs** | MSFT 207,710M / 168,825M ground-truthed against the FY2026 10-K; STI's S-1/A instants correctly ignored; a 10-Q/A restatement correctly preferred |
| **Split detection when a split is real** | 1,863 companies with an event | verified line by line on BKNG, KO, CMG, TPL, LRCX, CTAS, NEXM | BKNG's 25:1 self-consistent end to end: FY2025 165.57/25 = 6.6228, shares 751,380,500 = 30.06M × 25, P/E 23.66. NEXM's 1:20 reverse correctly multiplies. **Without the split machinery BKNG's P/E would read 167.95** |
| **`_IMPLAUSIBLE_EPS` on the tagged chain** | all 5,911 | 0 tagged-chain violations | GRUSF tags 243,446,152 into a per-share element; the engine drops the year and derives −0.0115 → FAIL. A naive reader gives a P/E of 0.0000000018 |
| **`_ABSURD_DELTA` guard** | population | works | TBLA tags H1-2026 at 220.00 against a full year of 0.13; the guard keeps 0.13 → P/E 29.69 FAIL. Without it criterion 1 passes at 0.01 |
| **`_derived_annual_eps` = (net income − preferred) / weighted shares** | 182 companies, 506 observations | **490/506 exact** | KKR FY2022 −0.79 and FY2025 2.34 reproduce; HSY FY2010 to 13 digits. 7 of the 16 differences are F5 |
| **Preferred read at liquidation preference before carrying value** | 2,109 rows with a preferred figure | all reproduce | 117 rows use the liquidation preference. USB deducts $7,026M; JPM $21,200M; WFC $16,116M. Economically the correct common-TBV deduction |
| **NCI, both legs, and the fair-value guard** | 1,497 rows | reproduces | WMT = `MinorityInterest` 6,352M + `RedeemableNCI` 293M = 6,645M, matching the 10-Q's two lines. The HEICO/ADM fair-value guard fires correctly: 4 rows use it, none also carries a temporary-equity figure |
| **Mezzanine gate: skipped when liabilities were derived from the identity** | all 5,911 | **0 violations** | A derived L already contains the mezzanine; no row double-subtracts it |
| **Parent-scope flag: no double subtraction of NCI** | 324 rows using a parent-only derivation | **324/324 clean** | SRI: A − L − preferred equals the filer's own equity to the dollar |
| **Goodwill and intangibles chains** (13 paths: primary, two derivations each, indefinite-lived class tags, max-merge against `OtherIntangibleAssetsNet`, MSR servicing assets, capitalised software) | 2,826 goodwill and 3,453 intangibles rows | provenance and tag choice verified on all; 3 ground-truthed | ARES `Goodwill 3,464,289` matches the 10-Q line exactly; CIM `108,677`; WMT 28,152M. KO's `IndefiniteLivedTrademarks` is the sole reason KO has a criterion 7 at all. VZ 170,476M correctly sums finite + indefinite at identical dates. WFC's MSRs correctly counted (tbvps 43.97 vs bvps 54.18) |
| **Operating leases excluded from every debt figure** | all debt provenance across 5,911 rows | **0 of 47 distinct tags contains "OperatingLease"** | Consistent with `normalize.py:2408` "the debt test counts borrowed money and not rent" |
| **Current-portion suppression registry** | 247 rows with a combined tag beside a current tag | **0 rows double count a current maturity across buckets** | MSFT's long bucket uses `FinanceLeaseLiability` (combined) and the short bucket correctly omits `FinanceLeaseLiabilityCurrent` — 0 of 5,911 show both |
| **Secured+unsecured axis competes with, never adds to, the instrument sum** | 68 rows | **68/68 show one representation** | GS 359,521M matches TAGS.md's $348B + $11.6B; AVA's `SecuredDebt` 2,789M is not 900× understated |
| **Share-count chain (6 steps) and its sanity rules** | all 5,911, mirrored independently | **5,843/5,911 (98.85%) exact**; the 68 are the DERA and LP branches my mirror omits | The magnitude rule fires 9 times and improves every one (PSKY 1,000 → 1,071,666,977). The fragile-source veto correctly refuses SUN's uncorroborated LP instant (51,517,198 against 231,140,351 implied) and ships **no** count — missing beats wrong. `_implied_shares` correctly nets preferred (the GTN fix: 217.7M → 97,163,121 against a class sum of 102,002,814) and correctly reads the **split-adjusted** series (BKNG 815,972,000 vs a shipped 751,380,500 — a 1.09× agreement; an un-split-adjusted implied count would have vetoed BKNG wrongly) |
| **Dividend chain, per-share vs aggregate, MLP and BDC tags** | all 5,911 replayed from raw facts | **5,907/5,911** exact on status, value, record and fact | EPD $2.194/unit (real ≈$2.20), MPLX $4.197 (≈$4.10), ET $1.388 (≈$1.35), HTGC $1.88, ARCC $1.905 (real $1.92 + specials), BXSL $3.071 (real $3.08). KO's $2.06 TTM reproduces exactly |
| **`ch13` statistics: `avg_recent/avg_middle/avg_old`, `latest_vs_prior3`, `max_decline`, `stability_years`, 10-year counts, `shape`, `latest_fy`** | all 4,971 rows with a ch13 block, recomputed in Decimal | **4,971/4,971 exact** on every field except the 4 near-zero-base rows of F12 | MSFT avg3 14.4633 → payload 14.46, ground-truthed against the FY2026 10-K's diluted `$17.95 / $13.64 / $11.80`; RVTY avg_old 1.45 against PerkinElmer's FY2016 10-K. **52 sprints and 394 marathons reproduce exactly**, matching SIGNALS.md |
| **`eps_growth` base year = best EPS in FY(L−7..L−4)** | all 5,911 | 5,910/5,911 | The one difference is an undefined tie-break among three equal zeros |
| **`epsEvidence()` 10-year window, gap slots, growth guard** | executed directly under `node` | correct | Requires all six block years non-null and a positive base, else `n/m`; never divides by a negative base; `EarningsEvidence.jsx:41-53` breaks the polyline at a null |
| **Owner-earnings arithmetic** | 3,999 rows | **0 mismatches** on `oe = Σ components`; **0** on `roic = oe / invested` (2,982); **0** on the operating-profit component equalling `annual_operating_income[fy]` (3,479) | The arithmetic is exact; F17/F18/F19 are about the magnitudes and vintages fed into it |
| **`peer_efficiency.margin` = operating income ÷ revenue at the latest shared FY** | 3,303 rows | **3,303/3,303** | F-tier defect is the vintage (F-list M5), not the formula |
| **Defensive tests: adequate size (industrial $100M revenue, utility $50M assets), financial position, dividend 20y, growth 33⅓%** | all 5,911 recomputed without importing `profiles.py` | **5,911/5,911** on profile mapping and eligibility; exact on every branch | The utility branch correctly does **not** consult the current ratio — DUK's criterion 2 FAILs at 0.66 while its defensive financial position PASSes, exactly as Graham specifies (82 utilities in that state). Every criterion-5 FAIL maps to `dividend_20y` FAIL, 3,367/3,367, no exceptions |

### 3.3 Payload identities

47 identities recomputed in `Decimal` straight from `dashboard.json`, importing no project
code. Fully clean:

| Identity | Checked | Violations |
|---|---|---|
| A − L = bvps × shares + preferred + NCI + temporary equity | 5,254 | **0** |
| bvps ≥ tbvps, **and** bvps − tbvps = (goodwill + intangibles) / shares | 2,542 | **0** |
| tbvps reproduces from A/L/gw/int/pref/NCI/temp/shares | 2,542 | **0** |
| ncavps reproduces from CA/TL/pref/NCI/temp/shares | 4,266 | **0** |
| market cap = shares × price, identical expression in `App.jsx:156` and `Detail.jsx:32` | 5,388 | **0** |
| every criterion value = the ratio it prints | 12,062 checks | **0** |
| `n_pass` = count(PASS); verdict precedence; criterion set | 5,911 × 3 | **0** |
| ttm_eps vs annual_eps[latest] where the windows coincide | 1,412 | **1** (HOVR, cosmetic) |
| owner earnings = Σ components; roic = oe / invested | 3,999 / 2,982 | **0** |

**Legitimate differences of definition, confirmed not defects:** NCAV subtracting *all*
liabilities while criterion 3's net current assets subtracts only current ones; `dividend_per_share`
being a TTM roll of a per-share chain rather than `dividend / shares`; `ttm_net_income ≠
annual_net_income[latest]` on 4,821 rows (different windows); 151 of the 207 sign
disagreements between `ttm_eps` and `ttm_net_income` carrying an NCI, preferred or
continuing-operations element that explains the wedge.

### 3.4 Ground truth against the filings

The single strongest positive result: **for 101 filers, every figure was re-read from the raw
cache at the exact accession and period end the payload's `sources` block names, and CR,
debt/NCA, BVPS, TBVPS, NCAVPS, P/E and P/TBV re-derived. 101 of 101 reconcile to the cent on
the code-true formulas, with zero status disagreements at any threshold.** Every headline
balance-sheet number on the dashboard is faithful to the filing it cites. The findings above
are about which fact is **chosen** and what the interface **claims** it is — never about
arithmetic or provenance.

The full TAGS.md §3 Coca-Cola worked example was re-verified figure by figure against
accn `0001628280-26-028802` (R4, R7). **20 of 22 claims exact**, including total assets
$104,217M, the derived total liabilities $68,483M, current assets 30,390 / liabilities 22,378,
goodwill $15,411M, NCI $2,101M, long-term debt $39,065M, the `dei` share count 4,302,482,418,
the FY2025 EPS 3.04 and TTM 3.18, the 20-year unbroken dividend record, BVPS $7.82 and TBVPS
$1.34. The two failures are D4 and D5.

### 3.5 Also confirmed correct, briefly

The `NOT_APPLICABLE` gate for unclassified balance sheets (992 rows, none of which can reach
an overall PASS; 935 never tag either concept in any filing). The refusal to sum current-asset
components — an incomplete sum moves the ratio in the false-PASS direction, which is the
direction that matters. Negative `AssetsCurrent` dropped as a sign error (OYCG, pinned by an
existing test). "Missing is never zero" holds absolutely: no criterion in the payload passes
on an absent input, and `assume_absent_zero` is never opted into at export. `ENGINE_VERSION =
58` matches the payload, with 20,236 of 20,328 snapshots at 58 and the 92 stragglers all in
unrecomputable statuses. All 273 staleness voids obey a strict `gap > 450` rule with an exact
boundary (TAYD 445 and IMAA 446 keep their verdicts; LFCR 451 is voided). No negative debt
value, no infinite or NaN criterion value, and no zero share count ships anywhere.

---

## 4. Refuted

Two findings were investigated, attacked and killed. **Do not re-raise them.**

| Claim | Why it is wrong |
|---|---|
| **"The implied NI/EPS count is not independent of the weighted average, and the pair outvotes a correct total share count"** (Excelerate Energy, Fluence) | The mechanism reproduces exactly, but every "correct" number in the claim divides a **parent-only equity numerator by a whole-company share count**. EE is an Up-C: its 82,021,389 Class B shares carry no claim on EE Inc.'s equity — their economics **are** the $1,585,237K noncontrolling interest the engine already subtracted. The claim's denominator counts those holders a second time. The 10-Q cover names one 12(b) security, "Class A Common Stock": market value of the listed stock is $38.14 × 31,408,625 = **$1.198B**, and the shipped $1.234B is 3.0% high, not 3.5× low. The claim's $4.326B is the fully-exchanged enterprise value, which pairs only with equity *including* NCI. FLNC is worse: the count the rule **rejected** was the undimensioned 51,499,195, which the DERA sidecar identifies as a Class B-1 fragment — the rule moved FLNC toward the right answer. A full-payload scan finds 6 firings of this rule family; 4 are the treasury-stock mis-tags it exists to catch (JACK, EMN, EG, RSKIA, recorded as verified in TAGS.md:424), EE is correct on this project's stated basis, and the one genuine casualty is a $73K OTC shell whose verdict is unchanged either way |
| **"SIGNALS.md's 2,677 thirteen-year records should be 2,563"** | **2,677 is exactly right** and reproduces off the shipped payload two independent ways: rows where `ch13.avg_old is not None` = 2,677, and rows where FY(L−12), FY(L−11), FY(L−10) are all present = 2,677 — **symmetric difference 0 tickers**. The claim's 2,563 counts *thirteen consecutive years with no gaps*, a predicate appearing nowhere in `ch13.py`, `profiles.py` or `sync.py`. `_avg3` reads nine of the thirteen years; FY(L−9), FY(L−8), FY(L−4) and FY(L−3) are never read, and the binding constraint is the oldest block, which is exactly what the sentence describes ("whose record reaches back"). All 446 shaped companies fall inside the 2,677, so the denominator is valid. SIGNALS.md is untracked in git and unreferenced by any code, so it reaches no user regardless |

**One unresolved contradiction between two agents, recorded rather than adjudicated.**
`format.js`'s `spell()` is marked **DEFECT** by the price-stats auditor and **CORRECT** by the
mirror-and-format auditor, on identical evidence ("imported at `App.jsx:7`, called nowhere").
It is dead code; the disagreement is about whether dead code is a defect. Related dead code
nobody classified: `divergence()` and `niTitle()` (`App.jsx:555-570`) read `r.trend` and
`r.niTrend`, **fields the payload does not contain**.

**One coverage claim that reads as a contradiction and is not.** The criterion-1 auditor's
final reviewer reported *"criterion 1 as shipped is CORRECT — 4,906 priced rows, zero
mismatches"*. That check recomputed `price / ttm_eps` and the PASS/FAIL from the payload's own
`ttm_eps`. It is true, and it is the check in §3.1. It says nothing about whether `ttm_eps`
itself is right, which is what F3, F4, F5, F13, F14 and F15 are about.

---

## 5. Coverage gaps

What was not reached, and what closing it would take.

| Gap | Size | To close it |
|---|---|---|
| **The DERA dimensioned sidecar was never independently recomputed.** 195 rows' TTM EPS and 68 rows' share counts rest on it. KKR's shipped 2.34 matches what the sidecar reports, which is corroboration, not verification | 195 + 68 rows | Build a second reader for the sidecar and diff it, then ground-truth 5 filers against their filings. ~4 hours |
| **Facts tagged only on a share-class or segment axis are invisible to Company Facts.** KKR's $2,543,404K of Series D preferred is never deducted; the payload discloses only the generic "no preferred-stock value tagged; defaulted to 0" note — which F23 then erases | Unmeasured | Cross-read the DERA financial-statement datasets for the preferred and debt slots |
| **Segment-dimensioned debt.** Ford is proven from its filing; LIVE (criterion 3 PASS at 0.94× on a lease-only $42.9M against $165M of noncurrent liabilities and $15.6M of interest expense) is strongly suspected and unopened. Issuer-extension elements (`csv:LeaseLiabilitiesAndDebtCurrent`) are outside every scan | Unknown | Read filings for the 1,847 criterion-3 INSUFFICIENT rows, or the DERA datasets |
| **1,847 criterion-3 INSUFFICIENT rows cannot be priced for F22's understatement**, because with no debt figure there is nothing to compare. A row that should FAIL on debt may be sitting in UNGRADEABLE | 722 with no debt figure at all | Same as above |
| **107 sign disagreements between `ttm_eps` and `ttm_net_income`** with no NCI, preferred or continuing-ops marker to explain them (STZ −0.45 vs +$1.82bn; MDLN −0.01 vs +$1.15bn; DAN −0.52 vs +$1.12bn) | 107 | 107 filings |
| **376 of the 487 EPS/share basis mismatches (F13)** were not individually resolved into "share-count error" vs "EPS error" | 376 | A full split-history reconstruction per filer |
| **65 rows with yields between 20% and 100%** — genuine high-yield mortgage REITs and BDCs, or further instances of F24/F25? NHTC 51.98%, AHT 89.82%, BHR 29.49% | 65 | One filing each |
| **PAA's $2.49/unit distribution and 10.38% yield** rest on `PartnersCapitalAccountDistributions`, which rolls up Series A preferred, GP and NCI. PAA's own per-unit elements stop in 2018, so no in-file cross-check exists. WES, BXP, SBAC, BAM, GRMN, THG, SLB, DHR are in the same unverified population | 203 aggregate rows | Filings |
| **5 mixed-date criterion-2 PASSes could not be disproved** (ENHA, LEGO, MMTX, STQN, TVIV). Total liabilities at the current-assets date bound the true ratio below 1.50 for each, but these are SPACs whose liabilities may legitimately be noncurrent | 5 | 5 filings |
| **Whether a company's price is on the same split basis as its split-adjusted EPS** is not checkable from filings. SLXN (price 0.4132, ttm_eps 89.60, P/E 0.00, PASS) and GCTK (0.349 / 31.22 / 0.01) look like basis mismatches after real reverse splits | ~2 known | The quote provider's adjustment history |
| **The `?assume_absent_zero=true` path was never exercised** — 0 of 5,911 rows carry an assumption | Whole feature | An integration test against the API route |
| **Historical delta claims are unfalsifiable** without the pre-change payload ("726 companies gained long-term debt", "148 moved to a measured criterion-1 FAIL", the 689→162 untaxed-profits collapse) | ~15 doc claims | Retain one payload per engine version |
| **No browser exercise.** Every UI claim is source-read against real payload values, except `earningsEvidence.js` (run under `node`) and `Detail.jsx` (rendered with `react-dom/server`) | All UI findings | A screenshot pass over 20 named rows |
| **Identity anomalies not chased.** `SPCX` (CIK 0001181412, "SPACE EXPLORATION TECHNOLOGIES CORP", SIC "Services-Computer Programming", $819B cap) and `XOM` (CIK 0002115436, "ExxonMobil Holdings Corp", **not** CIK 34088) look like CIK reuse after a reverse merger. **4 tickers appear twice** (GORO, DTSS, CLBK, ATAI — ATAI renders at $1.77B and $2.72B simultaneously, both priced $7.36, because the table keys on `cik` while the price joins on `ticker`) | ~6 rows | An hour with EDGAR |
| **800 OTC rows and 327 with a null exchange** reach the table under a $500M default cap; whether their Yahoo quotes are the right security is untested | 1,127 | Sample 20 against the exchange |

---

## 6. Fix list, in order

Ordered by damage per hour of work. The first five are one afternoon each and remove eleven
wrong verdicts and four impossible numbers between them.

**Tier 1 — wrong verdicts, small diffs**

1. **F2 · Reject a debt rollup smaller than its own parts.** `normalize.py:283-292` already
   drops a rollup that is *older*; add "or smaller than long+short at the same date". Removes
   4 wrong criterion-3 PASSes and 58 impossible rows. **The identity check already exists in
   `coverage.py:614` — fixing F30 in the same commit stops it recurring.**
2. **F30 · Fix the coverage sampler.** `coverage.py:366` selects on `mcap`, which the payload
   does not carry. Compute it, or select on `total_assets`. One line; it is the reason F2
   shipped.
3. **F4 + F11 · Cross-check every split against the weighted-share ratio, and floor the
   voting magnitude.** One guard in `_split_events` kills both: an 8-K carrying a merger
   target's statements moves EPS 2.5× and shares 1.41×; a cent-level revision moves EPS 1.5×
   and shares not at all. Removes 1 wrong criterion-1 PASS and repairs 441 companies' curves.
4. **F1 · Anchor the split run-collapse window on its last observation, not its first** —
   with a cap on the total span, or keyed on cumulative ratio per period. Repairs 1,122 EPS
   values, 66 criterion-4 values and 1 wrong defensive PASS.
5. **F5 · Teach `_has_minority_interest` to read partnership evidence** (`PartnersCapital*`,
   `MinorityInterestInLimitedPartnerships`) **and give the TTM override its own ProfitLoss
   check.** Both halves are needed — see the note under F5. Removes the dashboard's
   highest-scoring wrong row.

**Tier 2 — wrong verdicts, structural**

6. **F3 · Never ship an unlabelled fiscal year as "latest 12 months".** Two parts: keep
   `CriterionResult.inputs` through `sync.py:132`, and either note the period on criterion 1
   or refuse when the payload's own trailing net income contradicts the sign. Removes 31 wrong
   PASSes.
7. **F10 · Give criterion 4 a recency guard anchored on `balance_sheet_date`**, and read
   `annual_net_income` when `annual_eps` has gone dark. Removes 5 wrong PASSes.
8. **F9 · Cluster annual period ends within ~20 days before labelling**, then latest-filed
   wins inside the cluster. Widen HOW-IT-WORKS.md:104 with it.
9. **F13 · Cross-check `annual_eps × shares` against `annual_net_income`** and withhold
   criterion 1 when they disagree by more than a factor. `_implied_shares` already computes
   this quantity. Removes 23 wrong PASSes.
10. **F6 + F7 · Fix the universe.** Exclude non-common share classes; carry the ADS ratio or
    ship no market cap. Missing beats wrong.
11. **F14 · Take the minimum share ratio across tags, or prefer basic**, in
    `_shares_incomparable`. Fixes 13 rows in both directions.

**Tier 3 — wrong numbers**

12. **F20 · Require the balance-sheet slots to share a period end**, or disclose the stitch on
    the panel rather than only in the provenance table. 2,715 rows; start with the current
    pair (39 rows), where it changes a criterion.
13. **F22 · Four debt fixes**: let additive instrument slots run alongside a primary; break
    primary-chain ties by magnitude, not tag order; widen the current-maturities dedupe beyond
    one tag pair; require `_sum_facts` components to share a period end.
14. **F16 · Apply `_IMPLAUSIBLE_EPS` after the derived merge**, and add a share-count
    scale/continuity test. Both are needed.
15. **F17 + F18 + F19 · Guard owner earnings**: floor invested capital against total assets,
    reject a flow component exceeding total assets, and require the flow year to be within ~2
    years of the balance sheet (or caveat it).
16. **F21 · Refuse a non-USD unit** rather than falling back to `next(iter(units.values()))`.
17. **F23 + F27 · Stop `apply_price` discarding the screen's notes and guards.** It currently
    reimplements criteria 1, 5 and 7 and drops the disclosures and the yield cap on the way.
    Repairs 846 + 60 + 29 rows and is a prerequisite for F34.
18. **F24 + F25 + F26 + F28 · Four dividend fixes**: exclude preferred-only aggregates; add a
    staleness guard and provenance for `dividend_per_share`; require a materially sized
    payment to continue a streak; narrow the unknown-scan to tags that can be a payment.
19. **F8 · Read the filing body for item 3.01**, or drop the item. 1,451 notes.
20. **F29 · Prefer a fresher share count; floor the warrant instant; net preferred out of the
    implied-shares column.**
21. **F31 · Compute the toolbar counts over `view`, not `rows`.** One `useMemo` dependency
    array.

**Tier 4 — labels, one commit each**

22. F34/F35/F36 (criterion-1 notes), F37 (display vs threshold — adopt `profiles.py:515-522`'s
    stated policy), F38/F39 (Detail.jsx one-liners), F40 (EpsCurve gaps and loss count),
    F32/F33 (note text), F41/F42 (dead code and note kinds), the "EPS > 0" label, the N100
    badge.

**Tier 5 — documents**

23. **D1** (verdict precedence backwards), **D3** (both formulas missing mezzanine), **D6**
    (a removed feature described as live, with two broken fixtures), **D7** (8 of 12 defects
    fixed), **D4/D5** (the KO worked example), **F41** (four false mirror claims in CLAUDE.md,
    TAGS.md ×2 and `sync.py:633`) — then the stale counts, the ~65 unlisted tags, and the
    SIGNALS.md frequency.

---

*Audited against engine 58, payload of 2026-08-20. 43 filings read on sec.gov. 31 regression
tests written and confirmed failing on HEAD; none was added to the repository. No file in the
repository was modified by this audit.*

---

## 7. 2026-09-08 addendum — operating-income and published-statement sweep

This is the first incremental pass of the new source-to-UI audit. It does not supersede the
engine-58 findings above and is not a claim that the whole universe has been manually read.

### Johnson & Johnson ground truth

J&J's 2025 annual report, page 44, presents its consolidated earnings statement in millions.
The reported rows reconcile operating income exactly even though the standard
`OperatingIncomeLoss` Company Facts series stops after FY2014:

| FY | Gross profit | SG&A | R&D excluding acquired IPR&D | IPR&D impairment | Restructuring | Reconciled operating income |
|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 63,937 | 23,676 | 14,665 | 81 | 228 | **25,287** |
| 2024 | 61,350 | 22,869 | 17,232 | 211 | 234 | **20,804** |
| 2023 | 58,606 | 21,512 | 15,085 | 313 | 489 | **21,207** |

The independent bridge from pretax income through interest income, interest expense and other
nonoperating income/expense produces the same three totals. Engine 132 accepts this inverse
bridge only when gross profit, SG&A and the separately presented R&D row constrain all omitted
operating costs to no more than 5% of gross profit. Every component keeps its accession, period,
form and tag in provenance.

The guard was attacked with FSTR FY2014. Its generic `ResearchAndDevelopmentExpense` comes from
a note and is already contained in SG&A; treating it as a separately presented statement row
would create a false operating-income subtotal. The generic tag is therefore excluded, and the
FSTR case remains absent rather than guessed.

### Audit-harness defects found by the sweep

The first filing pass initially printed 12 apparent mismatches. Direct filing review showed all
12 were audit-harness false positives, not payload errors:

- the auditor compared every balance field with the accession chosen for total assets, even
  when the field's own retained provenance pointed to a different annual filing;
- USD convenience translations were compared with a published CNY or other filed-currency row;
- a visibly printed current-period value was treated as wrong when the SEC element hyperlink
  exposed only the comparative-period cell.

The auditor now reads each field's retained source accession, recognizes the same concept and
period in another filed unit, and reports incomplete SEC element links as `FILING?` rather than
as false errors. The EXDW 2025 10-K was the concrete incomplete-link regression: both 121,590 and
126,913 are visible in the statement, while the element link indexes only the comparative cell.

### Historical presentation-scale findings

A population scan found 91 isolated exact-scale flow/share observations and 230 years where
`EPS × weighted shares` missed the matching income by approximately 1,000× or 1,000,000×. The
neighbor-year pattern was used only to find candidates. A repair is accepted only when the same
accession and fiscal period carry the weighted count, EPS and the economically matching income
numerator and the exact rescale reconciles them within 5%. Continuing-operations EPS is paired
with continuing-operations income rather than total net income.

That proof corrected **21 company-years across 12 issuers**: DOV (1), MDU (2), NEON (1), SPXC
(2), SENEA (1), PAR (2), CVSA (3), ESE (1), PESI (2), NNDM (3), FXHO (1), and ZSTK (2). Direct
report checks covered four different statement shapes: Dover FY2009 and Perma-Fix FY2020 report
their counts in thousands; Nano Dimension FY2025 reports 215,742 thousand shares against
−$0.46 continuing-operations EPS and −$100.355m continuing loss; UTime FY2026 reports 56,302
thousand shares against −$0.07 and −$4.035m. The corrected counts now read 186.736m, 12.347m,
215.742m and 56.302m respectively. No approximate scale or cross-filing evidence is accepted.

### Monetary scale and malformed subtotal findings

- Bio-Techne's FY2013 `OperatingIncomeLoss` comparative appears in Company Facts as `$158,469`,
  but its 2015 10-K states that the table is in thousands and prints `158,469`. Gross profit
  `$231.110m` less operating expense `$72.641m` equals `$158.469m`; pretax `$160.662m` less
  nonoperating income `$2.193m` independently gives the same number. Engine 134 corrects this
  exact 1,000× contradiction and retains the bad direct fact in the derived provenance.
- Dolphin Entertainment's reports do not print a gross-profit subtotal, yet Company Facts
  supplied a repeated `$3m` in six years and `$3` in FY2022. Same-filing revenue and direct costs
  contradict every one of those values, so all seven are now absent rather than displayed as a
  margin. Financial Gravity's FY2021 `GrossProfit=0` was an Inline-XBRL `zerodash`, not a reported
  zero, and is also withheld.
- Two adverse controls remain untouched: Uranium Energy's FY2024 `$37,000` gross profit and
  Rubicon Technology's FY2012 `$40,000` gross loss are visibly printed and exactly supported by
  revenue less cost of revenue. This prevents a magnitude filter from erasing genuine weak years.

### Cash-flow bridge scale findings

The next incremental scan covered the seven direct rows in every available ten-year cash-flow
bridge for all 6,586 UI companies. It produced only five isolated exact-scale candidates. Four
were real extremes: SPXC's FY2022 net income is `$0.2m`; CWK's FY2019 net income is `$0.2m`;
Immersion's FY2020 operating cash flow is `$22,000`; and AerSale's FY2022 operating cash flow is
`-$113,000`. Each value is printed in its audited statement and remains unchanged. A separate
net-income scan also checked CATO FY2022 (`$29,000`), Applied Optoelectronics FY2017 (`$9`) and
Pure Bioscience FY2020 (`$4,000`) against their reports; those unusual profits are also real.

FUSB was the one confirmed extraction defect. Its 2024 10-K cash-flow statement is in thousands
and prints D&A of `1,590` for FY2024 and `1,581` for FY2023. The exact Inline-XBRL row is issuer
extension `DepreciationAndAmortizationOfPropertyPlantAndEquipmentAndComputerPrograms` with scale
3, but Company Facts omits issuer extensions. The standard `DepreciationAndAmortization` element
instead belongs to the rounded note sentence “Depreciation expense of $1.6” and the filing tags it
with scale 0. Engine 137 therefore admits that one semantically exact DERA extension below the
generic $100m extension floor. The latest two DERA quarters supply exact values of `$1.581m`,
`$1.590m`, and `$1.695m` for FY2023–FY2025.

When the DERA quarter is not yet cached, the engine does not guess the extension value. It may
retain an earlier standard fact for the identical annual period only if the newer comparative
differs by exactly 1,000× or 1,000,000× and the earlier scale agrees within one order of magnitude
with both adjacent years. This fallback yields the earlier filed `$1.6m`, preserves both versions
in provenance, and never fires for a lone outlier. Ordinary restatements and the seven direct-
report adverse controls above remain latest-filed-wins.

### Working-capital cash-effect findings

The UI-baseline population contains 31,466 annual cash-flow bridges with operating cash flow,
but only 678 separately populated working-capital effects: 2.15% of company-years and 122 of
3,990 companies with a usable bridge. Most blanks are therefore real extraction-policy gaps,
not reported zeros. The original policy kept the working-capital movement inside the exact
`Other OCF adjustments` residual unless one aggregate tag was available.

Reviewing the aggregate exposed a sign defect. `IncreaseDecreaseInOperatingCapital` is the
increase/decrease in the operating-capital balance; it is not the signed cash-flow-statement
effect. Coca-Cola's 2025 10-K tags positive `$7.208bn`, while both its consolidated cash-flow
statement and Note 21 print a negative `$7.208bn` cash effect. Engine 138 inverts this standard
tag, repairing all retained years that used it while leaving the OCF reconciliation identity
exact. Two opposite-direction controls confirm that this is semantic rather than a Coca-Cola
presentation quirk: HNI's FY2025 Company Facts value is `-$23.9m` while its statement prints a
positive `$23.9m` cash contribution, and Vertiv's raw `-$339.3m` likewise appears as positive
`$339.3m` in both its statement and management's cash-flow discussion. The 2026 FASB taxonomy
documentation independently defines the element as the asset/liability balance movement.

Johnson & Johnson demonstrates one safe way to recover a missing rollup. Its 2025 statement
prints five non-overlapping changes: receivables `-$1.781bn`, inventories `-$1.450bn`, accounts
payable/accrued liabilities `+$2.377bn`, other operating assets `-$6.167bn`, and other operating
liabilities `-$5.697bn`. The five values total **-$12.718bn**, which also agrees with management's
cash-flow discussion. Boston Scientific FY2018 independently prints the same five-row shape and a
`-$2.169bn` sum.

A population scan found that the apparent five-tag pattern also occurs at Ennis, but its 2026
statement has a sixth `+$72k` prepaid-expenses-and-income-taxes row carried by an issuer extension
that Company Facts omits. The naive five-tag result would be wrong. Engine 138 therefore permits
component reconstruction only for exact SEC accession/year contexts already read against the
rendered statement; it does not infer completeness from the standard tags alone. The five facts
must still have one annual period, accession and form, and any other visible same-context
`IncreaseDecreaseIn*` fact vetoes the result. Unverified, incomplete or potentially overlapping
sets remain blank and inside the residual; missing is not treated as zero. J&J remains in the
real-company statement and coverage sets, and Ennis is a pinned refusal test.

### Operating-return denominator findings

The next whole-payload scan covered 48,339 annual company-years. Operating income is available
for 77.06% of them and NOPAT for 37.64%, but the exact average cash-excluded invested-capital pair
needed for NOPAT ROIC is available for only 7.89%; 5.31% produce the ratio. RONTA is narrower:
2.43% have an exact average NTOA pair and 2.03% produce RONTA. The dominant cause is missing
beginning/end investment evidence, not a reported zero. Strict UI blanks must therefore stay
blank unless a filing proves every denominator input.

Vertiv FY2025 exposed one real taxonomy-transition miss. Its audited balance sheet prints cash of
`$1.7284bn`, a separate short-term-investment row of `$99.5m`, assets of `$12.2124bn`, current
liabilities of `$4.4070bn`, and current debt of `$20.9m`; FY2024 prints `$1.2276bn`, zero,
`$9.1325bn`, `$3.0970bn`, and `$21.0m`, respectively. The investment row uses the newer
`DebtSecuritiesHeldToMaturityAmortizedCostAfterAllowanceForCreditLossCurrent` element, which the
old chain did not read. Those statement values produce endpoint invested capital of `$4.8289bn`
and `$5.9984bn`, hence an exact average of **$5.41365bn**. Operating profit of `$1.8297bn` and the
median aligned FY2023–FY2025 effective tax rate produce NOPAT of `$1.399979bn` and **25.8602%
NOPAT ROIC**.

That modern tag cannot enter the global fallback chain. Westlake's 2025 filing uses the same
held-to-maturity family for `$0` and `$1.009bn` of securities with original maturities of three
months or less and explicitly classifies them as cash equivalents. Subtracting it as a separate
investment would count the same cash twice. Engine 139 therefore admits the modern tag only for
the exact Vertiv accession and statement dates already checked; Westlake is the pinned negative
control. Both are now permanent coverage-sample companies.

Johnson & Johnson is the opposite kind of correct blank. Its annual report discloses total
operating-lease ROU assets of `$1.3bn`/`$1.1bn` and total lease liabilities of
`$1.4bn`/`$1.2bn`, but says only that the current portion sits inside accrued liabilities and the
noncurrent portion inside other liabilities. It does not disclose the exact split. NOPAT and
NOPAT ROIC are computable after the operating-income repair; lease-consistent RONTA and
lease-neutral RONTA remain withheld rather than inventing the current liability.

The coverage run also exposed validator defects. Its duplicate-tag check interpreted the
legitimate repeated lease-cost input in `(operating income + lease cost) / (interest + lease
cost)` as 2,383 double counts. Its component counter could not parse reconciled operating-income
expressions or a workbook-row subtraction, producing another 25 false failures. Duplicate
protection now applies to additive constructions rather than both sides of a quotient, and
provenance coverage compares the exact formula references with their source components. Tests
preserve a genuinely duplicated sum and a deliberately extra reconciliation witness as opposite
controls.

The eight remaining material tag gaps were then read, not silently allowlisted. Exxon's
`LongTermInvestmentsAndReceivablesNet` is the clearest: its `$45.317bn` balance-sheet line contains
`$38.783bn` of equity-method investments and advances, `$271m` of other investments, and
`$6.263bn` of long-term receivables. The pure investment tags already feed RONTA; subtracting the
combined line would incorrectly remove operating receivables. The other seven are bank/broker
operating and funding detail, income/revenue components, or asset composition already inside
the read totals. Each now has a narrow documented scope rule.

SOPAQ's apparent NI/EPS share mismatch was also a validator period error. FY2024 NI/EPS implies
about `2.964m` weighted shares and the filing reports `2.963m`; the company then reports `4.968m`
shares outstanding on March 31, 2025 and `6.106m` by September. Comparing a duration identity to
that later instant mistook ordinary issuance for a split/basis defect. The identity now uses the
same fiscal year's filed weighted count. Final `make verify-coverage` is **PASS**: all 6,586
payload rows pass structural checks, the 117-company sample has no new material tag or identity
failure, and only three already explained debt-representation disagreements are reported.

An extreme-return sample then checked TEAD, ABBV and ABEO. All **39/39** provenance values,
**440/440** arithmetic identities and **54/54** machine-readable published-statement comparisons
matched; seven additional statement cells were not printed as one comparable concept. Their
large ROIC/RONTA magnitudes come from small but positive cash- or intangible-excluded
denominators, not scale or sign defects: ABEO's `$5.684m` invested capital is 3.78% of its
`$150.246m` capital including cash; TEAD's average NTOA is `$46.002m`; ABBV's is `$4.075bn` after
large goodwill/intangible deductions. These informational ratios remain visible beside the
cash-included return and outside Graham scoring; an arbitrary new suppression threshold was not
introduced from three examples.

### Reproducible results and release gate

- Python suite: **555 passed** (one Starlette deprecation warning).
- Web suite: **75 passed**.
- Fixed-seed 200-company arithmetic/source pass: **1,864/1,864 sourced figures** and
  **16,074/16,074 derived checks**, with zero confirmed errors; two payload-only checks remain
  unverified.
- The same sample against SEC-rendered statements after the harness fixes:
  **2,807/2,807 published-statement comparisons**, zero confirmed errors, 334 unavailable or
  non-machine-comparable cells.
- A fresh J&J row, round-tripped through the UI payload shape, matched all **15/15** statement
  checks for revenue, gross profit, net income, EPS and reconciled operating income across
  FY2023–FY2025.
- Full-universe regression after engine 138 covered **6,586 companies** (6,585 cached rows could
  be recomputed) and produced **3,656 field changes**. The preceding engine state accounted for
  706 of those; the working-capital correction adds a net **2,950** changes. That large count is
  expected because each corrected annual fact also changes its provenance, per-share value,
  OCF-before-working-capital presentation and exactly offsetting `Other OCF adjustments`
  residual. It does **not** change reported OCF, FCF, any Graham criterion or verdict. A separate
  whole-population component scan produced exactly four new company-years: J&J FY2023–FY2025 and
  Boston Scientific FY2018. Ennis remained absent. The earlier payload still contains 379
  pre-existing dirty-tree changes, and eight later pre-engine-138 differences have not yet been
  attributed independently in this pass. Therefore `derive`/`export` remains intentionally
  blocked and the currently served `dashboard.json` has not been overwritten.
- Full-universe regression after engine 139 again covered **6,586 companies** (6,585 recomputed)
  and reported **3,685 cumulative changes** against the preserved pre-change baseline. A direct
  engine-138/139 toggle isolated exactly **29 exported-field changes**, all on Vertiv; Westlake
  and every other company were unchanged. The new fields are the exact capital endpoints and
  averages, NOPAT ROIC, dependent owner-return/reconciliation fields, their caveats and
  provenance. Independent audit of the freshly recomputed Vertiv row produced **13/13 sourced**
  and **103/103 arithmetic** matches; the targeted JNJ/VRT/WLK filing audit produced **66/66
  published-statement** matches, with one Vertiv D&A sum not printed as a single concept and no
  wrong values. The served payload is still not overwritten because the earlier unrelated
  dirty-tree changes remain unattributed.

This phase fixes the fake-zero presentation as well: the detail panel is strict by default.
Missing filing evidence remains blank; zero substitution happens only after the user explicitly
selects the disclosed assumption mode. For J&J, NOPAT and NOPAT ROIC become meaningful once the
new engine snapshot is exported. RONTA and lease-neutral RONTA correctly remain absent because
their exact-date investment and lease inputs are not complete.

## Fiscal-calendar follow-up — engine 141

The historical-period sweep found two real losses introduced by the broader engine-140 calendar
normalization. Dycom changed from a July year-end to a January year-end through a six-month
transition period. Its audited reports identify July 29, 2017 as FY2017, the January 27, 2018
period as the transition, and January 26, 2019 through January 29, 2022 as FY2019 through FY2022.
Company Facts retains stale `fy` labels on the first post-transition accessions, which shifted
the January regime backward and removed FY2022 from selected history. Engine 141 pins that one
verified CIK/calendar boundary; it preserves FY2017, deliberately does not invent a comparable
FY2018, and restores FY2019–FY2022.

RBC Bearings' amended FY2022 10-K states that the fiscal year ended April 2, 2022. The same XBRL
accession contains three contradictory duplicate revenue/gross-profit contexts ending April 30.
Choosing the latest date erased the filing's net income, EPS, weighted shares, operating income
and operating cash flow. Engine 141 pins the audited April 2 end for that exact accession and
rejects only its conflicting sibling contexts. The selected values agree with the published
statement: revenue `$942.937m`, gross profit `$357.068m`, operating income `$121.094m`, net income
`$54.710m`, diluted EPS `$1.56`, and operating cash flow `$180.293m`. Later comparative filings
round some of those values but do not change their meaning.

Broad calendar heuristics were tested and rejected because they changed valid predecessor,
merger, bankruptcy and short-transition histories. The final engine-140/141 isolation changes
exactly two companies: **24 exported fields for DY and 7 for RBC**, with no third-company delta.

Validation for this follow-up:

- Focused normalization tests: **98 passed**.
- Full Python suite: **570 passed** (one Starlette deprecation warning).
- Web suite: **84 passed**.
- Full-universe regression: **6,586 companies**, with **12,938 cumulative changes** against the
  preserved engine-131 payload and criteria changes in 30 companies. These are accumulated dirty-
  tree changes, not an engine-141 release delta; DY and RBC are the only newly isolated rows.
- Fresh DY/RBC UI-shaped rows: **24/24 sourced** and **220/220 derived** audit checks, zero wrong;
  filing audit **17/17 statement matches**, zero wrong, plus one informational all-capex tag that
  is not a directly comparable printed total.
- Broad filing audit against the preserved payload: **278/278 sourced**, **3,099/3,099 derived**,
  and **376/376 published-statement** comparisons, zero wrong.

The served `dashboard.json` remains the pre-change baseline. It was not overwritten because the
12,938 cumulative payload differences have not all been attributed independently; engine 141 is
verified as an isolated fix but the combined dirty tree is not yet release-ready.

## Filing-detail and material-tag follow-up — engine 145

Johnson & Johnson's missing operating-return numerators were first checked against the printed
2025 annual report, not accepted merely because a Company Facts tag existed.  The statement does
not publish one operating-income subtotal, but its revenue, cost of products sold, selling and
administrative expense, separately presented research expense, and restructuring/IPR&D rows form
the exact operating reconciliation.  Engine output retains every component in provenance.  Its
NOPAT and cash-excluded NOPAT ROIC are consequently available; RONTA remains blank because the
filing does not disclose the current/noncurrent operating-lease-liability split needed for an
exact denominator.

The next material-tag pass found a different defect at The Eastern Company (EML).  Its July 4,
2026 10-Q balance sheet separately prints **$5,082,816 of trademarks** and **$4,121,143 of patents
and other intangibles, net**.  The filer uses `IntangibleAssetsNetExcludingGoodwill` for only the
finite-lived $4,121,143 line, despite the element's nominal roll-up meaning.  The correct
ex-goodwill intangible balance is therefore **$9,203,959**.  Engine 145 sums the two lines only
for this verified CIK and only when the nominal total exactly equals the same-period finite-lived
fact.  A generic version of the rule was rejected: it altered historical tangible-book figures
for 37 unrelated foreign/canonical filers.  The final v142/v145 isolation changes nine companies
and 91 leaf fields; all 694 accidental v144/v145 historical-ratio differences restore the v142
values.

Four other EML extension/standard tags were read against the filing and explicitly kept out of
unrelated chains.  `IntangibleAssetsCurrent` is the note's gross finite-lived cost, not a current
asset; `DeferredSalesInducementsAmortizationExpense` is ordinary intangible amortization already
inside D&A; the closed-block element is misused for the operating-lease liability; and the
reporting-unit element is misused for total goodwill.  Ten further material tags at CODI, UHAL
and GCO were likewise classified narrowly as asset composition, insurance/operating detail or
already-included totals.  Two economically useful tags were admitted as earnings-quality
disclosures: `OtherNonrecurringIncomeExpense` and `SaleAndLeasebackTransactionGainLossNet`.
They add warnings at DD, Q, WHR, CE, IP and WFRD without changing reported profit or a Graham
criterion.

The foreign-cover sweep also found two corporate-action edges.  Toyota's 2026 20-F was indexed
before Company Facts carried its full statements.  Cover refresh selected the older statement
accession, so the current one-ADS-to-ten-shares ratio could never reach a fallback snapshot.  The
cover job now prefers the pending annual accession and includes otherwise-usable snapshots with
a pending filing; Toyota keeps the last complete financial statements, receives the explicit
pending warning, and uses the current filing-backed ratio of 10.  YFOR is a separate unresolved
case: its Nasdaq symbol changed from YYGH on September 2, 2026, after its latest 20-F.  The annual
cover still says YYGH while the current metadata and quote use YFOR.  The strict exact-symbol
identity gate therefore excludes it from the candidate instead of silently joining a current
price to an old symbol.  Supporting a post-annual ticker rename requires explicit corporate-
action continuity evidence and remains a tracked next fix; the gate was not weakened merely to
restore the row.

Validation for this follow-up:

- Focused normalization, coverage and sync tests: **210 passed**.
- Full Python suite: **576 passed** (one Starlette deprecation warning).
- Web suite: **84 passed**.
- Candidate payload audit: **6,585 companies**, no duplicate/impossible/non-finite figures; all
  **58/58** sampled companies have zero unexplained material tags.
- Standard filing audit: **278/278 sourced**, **3,138/3,138 arithmetic**, and **378/378 printed-
  statement** matches, zero wrong; 66 lines were not printed as one comparable concept and one
  payload-only item is not independently checkable.
- Targeted EML/UHAL/TM/CODI/WFRD/GCO/JNJ/DD/Q/WHR/CE/IP audit: **148/148 sourced**,
  **1,639/1,639 arithmetic**, and **233/233 printed-statement** matches, zero wrong; 20 lines were
  not printed as one comparable concept and none were unchecked.
- Full-universe regression against the preserved engine-131 UI payload reports **14,082 cumulative
  field changes across 6,586 baseline companies**; 6,585 candidate rows recompute.  That is the
  accumulated dirty-tree delta, not an engine-145 delta.  Since it is not yet fully attributed,
  the served `api/screener/static/dashboard.json` remains untouched and this combined branch is
  not release-ready.

## Intangible-rollup and stale-balance follow-up — engines 146–147

The next balance-sheet pass found two opposite XBRL presentation cases. OPKO Health's June 30,
2026 balance sheet separately prints **$477.566m** of amortising intangible assets and **$195m**
of in-process research and development. Its note states total intangible assets other than
goodwill of **$672.6m**. The nominal ex-goodwill total element carries only the amortising row,
while the nominal indefinite-lived element carries the rounded complete note total. Engine 146
uses that larger total only for OPK's verified CIK. American Vanguard is the negative control:
its balance sheet prints net intangibles of **$133.185m**, while its **$314.580m** indefinite-
lived element is gross cost and must not replace or be added to the net total.

BioMarin proves why no market-wide addition rule is safe. Its June 2026 balance sheet prints net
intangibles of **$4,879.367m**. The note reconciles finite-lived gross cost of **$5,173.642m** plus
**$300m** indefinite-lived assets less **$594.275m** accumulated amortisation to that exact net
amount. The filer uses both `IntangibleAssetsNetExcludingGoodwill` and
`FiniteLivedIntangibleAssetsNet` for the final total; adding the separately tagged $300m would
double count it. BMRN is now a permanent pinned refusal test and engine 147 leaves every one of
its exported fields unchanged.

Bruker's June 30, 2026 report exposed two stale-tag defects. The nominal intangible total stopped
at the December 2025 value of **$899.6m**, while the current note prints net intangibles of
**$867.8m**. Its nominal `Liabilities` total also stopped at the December value of **$3,731.1m**.
The current balance sheet instead prints current liabilities of **$1,204.7m**, long-term debt of
**$1,814.7m**, and other long-term liabilities of **$597.7m**: exactly **$3,617.1m**. Together
with **$2,400.2m** equity including NCI and **$35.6m** redeemable NCI, those rows reconcile to the
printed **$6,052.9m** assets. Engine 147 admits this exhaustive three-row reconstruction only for
BRKR, only when every component has one period and accession, and lets the newer finite-lived
intangible fact replace the abandoned total. It does not infer that arbitrary liability detail
is exhaustive. The coverage identity check now also fails explicitly when assets and liabilities
come from different balance-sheet dates instead of performing invalid cross-period arithmetic.

The material-tag sweep added the 2025-taxonomy successor `OtherNonrecurringExpense` to the
earnings-quality chain. Bruker dual-tags one **$39.4m** "Other charges, net" rollup under both the
old and new elements; equal amounts are de-duplicated into one warning. Solstice's current
**$47m** is filed transaction-related cost and correctly reduces pre-tax income. UNFI files
**-$18m** because current cybersecurity insurance recoveries exceeded the related costs; its
report's pre-tax bridge independently shows the $18m benefit, so the warning correctly says it
added to income. The earlier engine-146 tag additions similarly disclose Advanced Energy's
**$31.8m** and Ormat's **$34.413m** induced-debt-conversion charges. OPK's historical **$32.647m**
charge remains outside the current trailing window and correctly produces no current warning.

The exact engine-145/146 payload comparison changed 16 leaves across OPK, AEIS and ORA. The exact
engine-146/147 comparison changed **29 leaves across three companies**: BRKR's two corrected
balances, provenance and dependent book/asset-quality figures, plus one earnings-quality list at
UNFI and SOLS. No Graham criterion or verdict moved in the isolated engine-147 step.

Validation for this follow-up:

- Full Python suite: **582 passed** (one Starlette deprecation warning); web suite: **84 passed**.
- Candidate coverage: all **6,585** payload rows pass structural checks and all **62/62** sampled
  companies have zero unexplained material tags or identity failures.
- Standard audit: **278/278 sourced**, **3,138/3,138 arithmetic**, and **378/378 published-
  statement** comparisons, zero wrong; 66 cells are not printed as one comparable subtotal and
  one payload-only item cannot be independently checked.
- Targeted BRKR/BMRN/UNFI/SOLS audit: **55/55 sourced**, **574/574 arithmetic**, and **85/85
  published-statement** comparisons, zero wrong; five constructed values are not printed as one
  directly comparable cell. The preceding AVD/OPK/AEIS/ORA run was **53/53**, **667/667**, and
  **89/89**, respectively, also with zero wrong.
- Full regression against the preserved engine-131 UI payload reports **14,122 cumulative field
  changes across 6,586 baseline companies**; 6,585 candidate rows recompute. The isolated
  engine-147 change is the 29-leaf set above, but the cumulative dirty-tree delta is not fully
  attributed. The served `api/screener/static/dashboard.json` therefore remains untouched and
this combined branch is still not release-ready.

## Cross-period balance-sheet follow-up — engines 149–150

A full scan of the UI payload found **42 companies** whose displayed total assets and total
liabilities came from different balance-sheet dates. The first attempted general repair
(engine 148) deliberately did not advance: it replaced same-date equity-identity derivations
with classified liability subtotals for 401 companies and changed 28 Graham criteria. Some of
those decompositions were economically better, but others moved amounts such as redeemable or
temporary equity between liabilities and senior claims. That 2,104-leaf radius was too broad to
attribute safely in this gradual audit. Advancing `Assets` independently to a newer
`LiabilitiesAndStockholdersEquity` fact also created new mixed-period pairs, so that part was
reverted rather than shipping a locally plausible but globally unsafe heuristic.

Engine 149 keeps the existing derivation when a filer has no direct liabilities total and uses
the standard `LiabilitiesCurrent + LiabilitiesNoncurrent` construction only when both exact,
same-accession subtotals are newer than an abandoned direct `Liabilities` fact. This fixes five
filers and no others: **DPZ, CMRE, ICCM, ONEG and EROK**. Domino's June 14, 2026 statement is the
large US control: current liabilities of **$588.670m** plus long-term liabilities of
**$5,157.083m** equal **$5,745.753m**. With assets of **$1,763.322m**, the resulting
**-$3,982.431m** stockholders' deficit is exactly the balance-sheet line. The isolated
engine-147/149 payload diff is **66 leaves across those five companies**: five liability totals
and their source records plus dependent common equity, BVPS/TBVPS/NCAVPS, asset-quality and
profitability values. No Graham criterion or verdict changed. The global mixed-period count
fell from 42 to 37 with no new mismatch.

J.B. Hunt does not file the standard noncurrent subtotal, so it remains outside the generic
rule. Its June 30, 2026 balance sheet instead prints five exhaustive rows: current liabilities
**$1,444.663m**, long-term debt **$1,145.337m**, self-insurance reserves **$487.457m**, other
long-term liabilities **$298.697m**, and deferred income taxes **$911.509m**. Their sum is
**$4,287.663m**, exactly equal to assets of **$7,944.778m** less stockholders' equity of
**$3,657.115m**. Engine 150 admits those rows only for JBHT's verified CIK and only when all five
share one accession and period. The engine-149/150 diff is **20 leaves in JBHT alone**; its
no-price criteria and verdict do not change. Against the priced served baseline, the serialized
criteria list is one additional explained leaf because the corrected book value changes the
numeric valuation input. The mixed-period count falls once more, from 37 to **36**.

Pinning JBHT in the material-tag harness also exposed three previously unclassified operating-
expense details: direct communications/utilities, operating taxes/licenses and operating
insurance/claims. They are separately printed components already included in reported operating
income; adding them to another chain would double count costs. The coverage registry now states
that reason explicitly instead of silently ignoring the tags.

Validation for this follow-up:

- Exact candidate comparisons: engine 147 to 149 changes **5 companies / 66 leaves**; engine 149
  to 150 changes **1 company / 20 leaves**. The final candidate contains **6,585 companies**.
- Full Python suite: **584 passed** (one Starlette deprecation warning); web suite: **84 passed**.
- Candidate coverage: all 6,585 rows pass structural checks and all **64/64** sampled companies
  have zero unexplained material tags or identity failures.
- Targeted DPZ/CMRE/ICCM/ONEG/EROK filing audit: **55/55 sourced**, **269/269 arithmetic**, and
  **85/85 published-statement** comparisons, zero wrong. Targeted JBHT: **12/12 sourced**,
  **162/162 arithmetic**, and **20/20 published-statement** comparisons, zero wrong.
- Standard audit: **278/278 sourced** and **3,138/3,138 arithmetic**, zero wrong. Filing audit:
  **378/378 published-statement** comparisons, zero wrong; 66 values are not printed as one
  comparable subtotal and one share-class item is not independently checkable from the payload.
- Full regression against the preserved engine-131 UI payload reports **14,209 cumulative field
  changes across 6,586 baseline companies**. That is the accumulated dirty-tree delta, not an
  engine-150 release delta. Because those older changes remain only partly attributed, the
  served `api/screener/static/dashboard.json` remains untouched and the combined branch is not
  yet release-ready.

Engine 151 adds one further market-wide rule, but only under an exact accounting identity that
cannot confuse parent equity with consolidated equity. A newer liability total replaces a stale
direct fact only when `Assets`, `LiabilitiesAndStockholdersEquity`, and equity **including NCI**
all have the same period and accession, the two asset totals are exactly equal, and the identity
date matches the selected balance-sheet date. Parent-only equity and mixed-accession facts are
explicit negative tests. This changes exactly **35 leaves across RDAR, MHUAF and SHGI**. Their
derived liabilities are respectively **$4,315,427**, **$18,251,143**, and **$0**; each is the
exact difference between the two same-filing totals. The global mixed-period count falls from 36
to **33**, with no new mismatch and no isolated criterion or verdict change.

The targeted RDAR/MHUAF/SHGI filing audit reports **20/20 sourced**, **120/120 arithmetic**, and
**31/31 published-statement** comparisons, zero wrong. All three are now pinned in coverage,
which passes **67/67** companies. The final engine-151 gates are **586 Python tests**, **84 web
tests**, **278/278** standard source checks, **3,138/3,138** arithmetic checks, and **378/378**
published-statement comparisons, all with zero wrong. Full regression against engine 131 is
**14,244 cumulative fields across 6,586 baseline companies**. The served payload remains the
preserved baseline.

## Cross-period isolation and auditor follow-up — engine 156

The remaining balance-sheet scan found **33 companies** whose selected total assets and total
liabilities still came from different dates after every exact reconstruction path had run. The
lags ranged from 91 days to more than eleven years. Combining those values created fictitious
common equity and therefore fictitious BVPS, NCAVPS, tangible-book and return denominators. BCS
was the clearest large case: 2021 assets minus 2025 liabilities displayed a false **-£82.081bn**
of current common equity.

Engine 156 keeps the original facts for independent history, scale checks and disclosure
materiality, but withholds the older side from the current snapshot whenever the two selected
total dates disagree. The missing side is not zero and the UI criterion note now names it as
missing. Bank/REIT applicability is captured before the withholding step, so hiding one stale
total cannot accidentally convert a not-applicable liquidity test into an ordinary missing-data
test. No generic parent-equity subtraction was added: for many of these filings that would omit
NCI, mezzanine equity or other senior claims and merely replace a visible absence with a plausible
but false liability total.

Statement history now chooses its XBRL namespace from any surviving core balance-sheet fact, not
only total assets. That preserves BCS's legitimate IFRS history after its stale asset total is
withheld and also restores filing-backed history for **WPP, RTO, MNY, HDL and DGNX**. Those five
rows account for 233 isolated UI leaves. Their independent audit reports **37/37 sourced**,
**221/221 arithmetic**, and **41/41 published-statement** matches, zero wrong; 28 additional
statement lines are not printed as one directly comparable concept.

The filing auditor itself exposed and fixed one false alarm while checking AHII. FY2012 gross
profit of **$16.375m** is printed in the 2012 report as $54.396m sales less $38.021m cost of goods,
but the auditor had compared it with the FY2012 comparative column in a newer accession. It now
opens the exact annual accession that supplied each older serialized year before declaring a
statement mismatch. The audit CLI also accepts an explicit candidate payload, allowing the exact
UI export to be checked without replacing the served baseline. The full regression harness now
keeps only sixteen derivations in flight on four workers; this removes the Windows submission
stall caused by queuing all 6,585 jobs before consuming the first result.

The auditor can now sweep the complete payload rather than only the standard spread or a random
sample. Its first full run left 88 explicitly uncheckable share counts, all sourced from a
share-class dimension that Company Facts omits. The values were present in the independently
cached SEC Financial Statement Data Set sidecars. The auditor now merges those raw observations
for verification and requires exact accession, period, unit **and dimension** equality; a Class A
observation cannot substantiate the displayed Class B count. The second full run closes all 88
without weakening the check.

Validation for this follow-up:

- The engine-156 candidate contains **6,585 companies** and the full balance-period scan reports
  **zero** remaining mixed-date asset/liability pairs.
- The engine-151/156 full regression completes all **6,585/6,585** rows and reports 1,163 leaves.
  Of these, **581** are explained engine changes across 38 companies: 348 leaves in the 33
  cross-period rows and 233 in the five restored namespace histories. The other 582 are refreshed
  historical price/FX-derived fields; 22 of them are split-adjusted GTBP/BRTX history inside the
  33-company subset. No criterion status or verdict changes in this isolated engine step.
- Targeted cross-period audit: **195/195 sourced**, **533/533 arithmetic**, and **254/254
  published-statement** comparisons, zero wrong; 52 values are not separately printed.
- Candidate coverage passes all structural checks; **139/140** sampled companies have no
  unexplained material tag, with the remaining item covered by the registry's known-identity
  controls. Standard candidate audit is **278/278 sourced**, **3,168/3,168 arithmetic**, and
  **378/378 published-statement** comparisons, zero wrong; 66 statement values are not separately
  printed and one payload-only item cannot be independently checked.
- Full local candidate audit across all 6,585 companies is **61,367/61,367 sourced** and
  **511,837/511,837 arithmetic**, with zero wrong, zero superseded-date components and zero
  uncheckable values. Published-statement rendering remains the narrower targeted/network gate
  reported above rather than a claim that 6,585 HTML reports were downloaded.
- Final suites are **593 Python tests** and **84 web tests**, all passing. The only Python warning
  is Starlette's existing `httpx` deprecation notice.
- Full cumulative regression against the preserved engine-131 UI payload completes 6,585 current
  rows from 6,586 baseline companies and reports **15,124** changed fields. YFOR is the one omitted
  row under the already-documented strict ticker-continuity gate. The only cumulative defensive
  verdict change is the previously audited EML fiscal-calendar/history repair.

The exact candidate is retained outside the served path as
`tmp/pdfs/jnj-2025-audit/dashboard-engine-156-candidate.json`. The served
`api/screener/static/dashboard.json` remains the engine-131 baseline; the cumulative dirty-tree
change set is verified by the gates above but has not been published implicitly.

## Reviewed presentation-scale contradictions — engine 157

The next historical scale sweep found one filing-backed corruption in **Golden Sun Health
Technology Group (GSUN)**. Its 2023 annual filing, accession
`0001213900-24-011180`, prints FY2022 revenue **$10,814,656**, gross profit **$4,811,398**,
operating loss **$1,540,421**, and attributable net loss **$2,139,320**. The following annual
filing, accession `0001213900-25-013985`, repeats those exact visible digits but labels its
statement `$ in Thousands`; its machine facts consequently make every repeated amount exactly
1,000 times larger. The contradiction also reaches cash-flow and balance-sheet comparisons:
FY2022 operating cash flow is **$910,251**, capital expenditure **$174,074**, and depreciation
and amortisation **$169,808**, while FY2023 common equity is **$4,427,990** and liabilities are
**$15,071,828**. The corrected values reconcile to both earlier exact annual reports and the
published statement arithmetic.

Engine 157 reconciles duration and instant monetary histories only after an exact 1,000x or
1,000,000x contradiction has been independently proved. The general repair is then gated by a
reviewed-accession registry: neighbouring years alone are not treated as proof. This is important
for **IOR**, whose older filings alternate between apparently scaled and unscaled observations;
the negative-control test requires that ambiguous history to remain untouched. Corrected facts
retain their original accession, form, period and component provenance. The same guard covers the
UI's **+/− Working-capital cash effect**, both when it comes from a direct rollup and when it is
assembled from components; missing evidence still remains missing rather than becoming zero.

The sweep also exposed a regression-harness defect rather than an extractor defect. Rebuilding a
foreign filer during comparison omitted its stored historical FX closes, falsely removing annual
price and valuation fields. The harness now reuses the export path's statement currency and exact
stored USD/counter-currency history. A focused UL/BCS/SONY/HMC control leaves those histories
unchanged, so foreign-price noise cannot hide accounting changes.

Validation for this follow-up:

- The exact engine-156/157 full-universe comparison completes **6,585/6,585** current rows and
  changes **62 leaves**. Numeric and provenance changes are confined to GSUN; SODI and COHR have
  wording-only caveat changes. No Graham criterion or verdict changes.
- GSUN's independent published-filing audit is **13/13 sourced**, **88/88 arithmetic**, and
  **25/25 published-statement** comparisons, zero wrong and zero unchecked.
- Full candidate audit is **61,367/61,367 sourced** and **507,520/507,520 arithmetic**, with zero
  wrong, zero superseded-date components and zero uncheckable values. The standard network filing
  gate is **279/279 sourced**, **3,138/3,138 arithmetic**, and **378/378 published-statement**
  comparisons, zero wrong; 66 constructed or differently presented cells are explicitly marked
  as not printed as one directly comparable line.
- Candidate coverage passes all structural checks across **6,585 companies**; all **67/67**
  sampled companies have zero unexplained material tags.
- Final suites are **599 Python tests** and **84 web tests**, all passing. The only Python warning
  is Starlette's existing `httpx` deprecation notice.
- The cumulative comparison against the preserved engine-131 payload completes successfully and
  reports **16,147 changed fields across 6,586 baseline companies**. It includes later filings,
  refreshed market inputs and every prior audited engine change, so it is not used to attribute
  engine 157; attribution comes from the adjacent 156/157 baseline above.

The exact candidate is retained as
`tmp/pdfs/jnj-2025-audit/dashboard-engine-157-candidate.json`. The served
`api/screener/static/dashboard.json` remains the engine-131 baseline and was not overwritten by
derive, export, coverage or audit commands.

## Filing-specific working-capital expansion — engine 158

The first measured sweep of the UI's **+/− Working-capital cash effect** found that 3,989
companies have a current annual operating-cash-flow bridge, but only 69 have a separately proved
current working-capital effect; across history the counts are 684 of 31,524 annual OCF rows. The
missing cells are honest absences, not zeroes. A raw Company Facts scan found 27 current filings
with all five commonly used standard components, but 26 also carry additional contract, tax,
lease or other `IncreaseDecreaseIn...` facts. The Ennis negative control proves why the common
five cannot be summed generically: its rendered statement contains an issuer-extension row that
Company Facts omits.

**Applied Materials (AMAT)** is the next filing-verified exception. Its 2025 10-K, accession
`0001628280-25-056742`, prints seven working-capital rows: receivables, inventory, other assets,
payables/accruals, contract liabilities, taxes payable and other liabilities. They sum to cash
effects of **+$775m in FY2023**, **+$1,117m in FY2024**, and **-$200m in FY2025**. The same
statement separately prints deferred tax among non-cash adjustments; that **-$639m** FY2025 fact
is explicitly permitted in the context but excluded from the working-capital family.

The verified-context registry now carries each filing's exact component weights and explicitly
classified non-working-capital tags. Every included component must still share the configured
accession, form, start and end, and any unreviewed same-context `IncreaseDecreaseIn...` tag blocks
the reconstruction. This allows different filers to have different complete statement families
without turning a visual naming pattern into an accounting assumption.

Validation for this follow-up:

- The exact engine-157/158 full-universe regression completes **6,585/6,585** rows and changes
  exactly **20 leaves in AMAT alone**. They are the three working-capital bridges, per-share and
  three-year/current displays, provenance, and the corresponding residual reclassification.
  Operating cash flow, free cash flow, criteria and verdict do not change.
- AMAT's independent audit is **13/13 sourced**, **209/209 arithmetic**, and **24/24
  published-statement** comparisons, with zero wrong, zero unprinted and zero unchecked.
- Full candidate audit remains **61,367/61,367 sourced** and **507,520/507,520 arithmetic**, zero
  wrong and zero unchecked. The standard filing gate remains **279/279**, **3,138/3,138**, and
  **378/378**, respectively, with zero wrong.
- Candidate coverage passes all **6,585** rows and all **67/67** sampled companies. Final suites
  are **600 Python tests** and **84 web tests**, all passing apart from the existing Starlette
  deprecation warning.

The engine-158 candidate is retained as
`tmp/pdfs/jnj-2025-audit/dashboard-engine-158-candidate.json`; the served engine-131 payload was
again left untouched.

## Published-statement working-capital sweep — engine 159

The next pass reviewed every current Company Facts context that exposed the common five
working-capital components plus additional `IncreaseDecreaseIn...` concepts. Twelve further
filings have complete standard-tag families that can be reconstructed without an issuer-
extension guess: **RIVN, USLM, SONO, KVUE, MTZ, BYD, FIX, TGLS, PTON, BARK, OMQS and FTAI**.
Each exception is pinned to one CIK, one accession and its explicitly reviewed fiscal years;
the family records whether each extra row is an asset or liability movement and separately
permits any same-accession non-cash adjustment that must not enter working capital.

The rendered statements were read row by row before admission. The resulting cash effects are:

- RIVN: **-$1,414m, +$1,167m, +$1,440m** for FY2023–FY2025.
- USLM: **-$8.756m, -$10.957m, -$2.603m** for FY2023–FY2025.
- SONO: **-$38.936m, +$102.779m, +$27.936m** for FY2023–FY2025.
- KVUE: **+$797m, -$571m, +$52m** for FY2023–FY2025.
- MTZ: **+$276.332m, +$441.125m, -$409.554m** for FY2023–FY2025.
- BYD: **-$126.527m, -$100.221m, +$350.064m** for FY2023–FY2025.
- FIX: **+$73.471m, +$107.401m, -$67.667m** for FY2023–FY2025.
- TGLS: **-$48.278m, -$24.167m, -$42.375m** for FY2023–FY2025.
- PTON: **-$14.0m, +$27.3m, -$35.5m** for FY2024–FY2026.
- BARK: **+$12.549m, -$11.051m, -$14.411m** for FY2024–FY2026.
- OMQS: **+$9.944m and +$6.285m** for FY2024–FY2025.
- FTAI: **-$75.928m, -$254.423m, -$702.498m** for FY2023–FY2025.

The sign review caught two easy-to-miss cases before they reached the payload: TGLS's commodity-
contract line is an asset movement, and OMQS's deferred-income-tax line is a working-capital
asset in that statement. BYD's similarly named deferred-tax line is instead printed in its
non-cash section and is therefore permitted but excluded. This is why names alone do not drive
the generic extractor.

Thirteen apparent candidates deliberately remain blank: **TMUS, ALCO, AES, WAT, FSLR, MELI,
CALY, NRGV, PRPH, MPAA, FBIO, EBF and DYNR**. Their statements contain lease, prepaid, tax,
government-grant, funds-payable or issuer-extension rows that the available standard Company
Facts family does not completely represent. Showing a partial sum would be more misleading than
the UI dash. Coverage rises from **67 to 79 current companies** and from **687 to 722 historical
annual rows**, out of **31,524** annual OCF rows; every other missing value remains missing, never
zero.

Validation for this follow-up:

- The exact engine-158/159 full-universe regression recomputes and compares **6,585/6,585** rows
  and reports exactly **235 leaves across the twelve reviewed companies**. Every change is the
  working-capital bridge, its current/three-year/per-share presentation, provenance or the equal-
  and-opposite residual reclassification. Operating cash flow, FCF, Owner Earnings, Graham
  criteria and verdicts do not change.
- Targeted filing audit is **154/154 sourced**, **1,564/1,564 arithmetic**, and **259/259
  published-statement** comparisons, zero wrong. Seven unrelated constructed or differently
  captioned figures are explicitly reported as not printed as one directly comparable line.
- Full candidate audit is **61,367/61,367 sourced** and **507,520/507,520 arithmetic**, zero
  wrong, zero superseded-date components and zero uncheckable values.
- Candidate coverage passes structural checks across all **6,585 companies** and all **67/67**
  stratified companies have zero unexplained material tags. Final suites are **612 Python tests**
  and **84 web tests**, all passing apart from the existing Starlette deprecation warning.

The engine-159 candidate is retained as
`tmp/pdfs/jnj-2025-audit/dashboard-engine-159-candidate.json`; the served engine-131 payload was
again left untouched.

## Historical scale, period and statement sweep — engines 160–171

The next staged sweep followed the values shown in Company Details backwards from the UI to
their annual XBRL observations and then, for suspicious cases, to the primary statement a person
reads.  Engines 160 and 162 added filing-specific reconciliation for exact historical monetary-
flow and weighted-share scale contradictions.  Engines 165–168 then removed an unsafe generic
EPS sign inference and admitted only statement-verified sign, share, EPS and monetary scale
exceptions.  The rules remain deliberately narrow: a value is never multiplied, divided, sign-
flipped or treated as a split merely because a neighbouring year looks more plausible.

The final scale scan still reports eight visually isolated tiny values: **CATO** FY2022 net
income $29,000, **SPXC** $200,000, **AOXY** $9, **PURE** $4,000, **UEC** gross profit $37,000,
**RBCN** $40,000, **SHIP** FY2010 split-adjusted EPS $15 and **CWK** net income $200,000.  Each
was checked against its actual filing and is a real small value, not a thousands/millions defect.
More importantly, the mechanical cross-check finds **zero** remaining exact 1,000x or 1,000,000x
contradictions between annual EPS and its share denominator.

Engine 168 contains two further primary-statement corrections.  **APCX** had a filing-specific
gross/operating presentation scale and sign contradiction; **ZCAR** had an already-restated
comparative that the generic split path would otherwise restate again.  The exact engine-165/168
payload comparison contains **391 changed leaves across 6,585 companies**; the changed financial
histories are the reviewed exceptions and their direct per-share/ratio consumers.

### Fiscal-year alignment and the independent statement reader

Engine 169 fixes a separate class of old-report errors: in a fresh-start or year-end transition,
several instant facts can share a filed date and fiscal label.  The annual balance-sheet selector
now prefers the observation anchored to the annual report's own period end rather than whichever
same-filed candidate happens to appear first.  The audit accepts a predecessor-plus-successor
income statement only when the two reported periods exactly form the transition year.  **FLYYQ**
was the filing-backed reproducer.  The adjacent engine-168/169 comparison reports **1,869 changed
leaves across 304 companies**, all downstream of the corrected annual-period alignment, with no
verdict or grade changes.

That comparison was followed by a rendered-statement sweep.  Six apparent extraction failures
were actually defects in the independent auditor, and therefore could have hidden or invented
future alarms:

- **AZTA** and **DCO** publish quarterly and annual blocks with the same ending date; the auditor
  had selected the first block instead of accepting the exact annual block.
- **GWLL** repeats an annual block, which must not be interpreted as a different value.
- **CCI** reserves an entirely blank dated scenario column before the populated columns.
- **FBCD** has an XBRL-linked row with an empty visible caption; dropping that cell shifted every
  tagged value one column left.
- **SHFH** has no HTML `thead`; scanning later prose found the statement dates in the opposite
  order and reversed the year mapping.

The statement parser now reads only leading header rows, preserves empty cell positions, removes
only columns proved empty across the whole table and keeps all same-date annual candidates for
comparison.  A final cash-flow guard also ignores an empty tagged comparative cell instead of
attempting to convert it to a number.  These are audit-only changes; they do not reinterpret the
payload.

### Three confirmed UI data defects — engine 171

After removing those false alarms, three cases remained and were verified in the primary filing:

- **BNET** has no revenue line or revenue activity in its FY2025 statement.  A $62 non-operating
  interest line tagged `InterestIncomeOperating` had been selected as revenue, producing absurd
  multi-million-percent margins.  Revenue and every dependent margin are now missing, not zero.
- **FLZH** prints FY2024 EPS of **-$73.12** in its newer annual report.  The older diluted chain
  still held pre-reverse-split **-$2.62** and produced **-$65.50** after generic adjustment.  The
  exact newer basic-only comparative now supersedes that obsolete value.
- **MBBC** prints EPS of **$0.02** for FY2025 and **-$0.07** for FY2024.  A rounded quarterly move
  from $0.09 to $0.06 resembled a 1.5-for-1 split, but the report identifies a **1.3728 conversion
  exchange ratio**, not a stock split.  That exact filing date is excluded from split inference;
  all affected historical share denominators and per-share owner-earnings fields follow the
  reported basis again.

A broader proposed engine-170 rule was intentionally rejected by the mandatory full-payload
gate: it changed 2,154 leaves, 45 criterion payloads and hundreds of unrelated EPS histories.
Engine 171 replaces it with three exact CIK/accession/year exceptions.  The engine-169/171
comparison is consequently limited to **165 leaves** whose financial changes belong to BNET,
FLZH and MBBC and their direct derived fields.  No verdict or grade changes; FLZH and MBBC retain
their prior criterion statuses, while BNET's unsupported size evidence becomes `INSUFFICIENT`.

### Johnson & Johnson and the requested operating-return fields

The **JNJ FY2025 10-K** was read directly as a report as well as through XBRL.  It prints operating
income of **$25.287bn**; the UI now carries that exact amount, not zero.  With the aligned three-
year median tax rate of **15.7068%**, the model produces NOPAT **$21.315bn**, NOPAT ROIC
**17.4184%**, and the cash-inclusive operating return **14.7323%**.  Its FY2025 operating cash flow
is **$24.530bn** and the complete printed working-capital bridge is **-$12.718bn**, so operating
cash flow before working capital is **$37.248bn**.  Those three values reconcile exactly.

RONTA and lease-neutral RONTA remain dashes by design.  The filing exposes an operating-lease ROU
asset but not an exact-date current operating-lease-liability split for both ends of the average,
and no exact positive beginning/ending net tangible operating-asset pair can be proved.  Filling
either return would require silently guessing an economically material denominator, which would
violate the project's missing-is-not-zero invariant.

Final validation of the engine-171 UI payload:

- Full derivation and export completed for **7,163/7,163** cached snapshots and produced **6,585
  UI rows**.  Ticker and CIK identities are unique; the served payload and retained candidate are
  byte-identical with SHA-256
  `99cddc10691a43d9c369f9bf09abe313ac2c648d52ba1e2fe600441a1939535d`.
- Independent full-payload audit: **61,366/61,366 sourced values** and **511,863/511,863 derived
  arithmetic checks**, zero wrong, zero superseded and zero uncheckable.
- Standard real-filing spread: **279/279 sourced**, **3,168/3,168 arithmetic** and **378/378
  published-statement** comparisons, zero wrong.  The focused JNJ/defect set is **97/97**,
  **904/904** and **168/168**, respectively, also zero wrong.
- The expanded set of all 301 period-alignment-affected companies is **3,023/3,023 sourced**,
  **24,453/24,453 arithmetic** and **4,561/4,561 published-statement** comparisons, zero wrong.
  The 373 cells reported as “not printed” are constructed figures or differently presented
  subtotals and are explicitly excluded rather than counted as passing.
- Final suites are **647 Python tests** and **84 web tests**, all passing (apart from Starlette's
  existing `httpx` deprecation warning), and the Vite production bundle builds successfully.

The exact release payload is retained as
`tmp/pdfs/jnj-2025-audit/dashboard-engine-171-candidate.json` and is also the current
`api/screener/static/dashboard.json` consumed by the UI.
