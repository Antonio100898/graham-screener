# Release 5 — Dimensioned and issuer-extension facts

The Company Facts API returns only *undimensioned* facts from the *standard*
taxonomies. Two whole classes of reported data are therefore invisible to the
screener today, and both are load-bearing:

- **Dimension-qualified facts.** KKR's FY2025 diluted EPS is **$2.34**, tagged
  `EarningsPerShareDiluted` with `segments = ClassOfStock=CommonStock;`. Company
  Facts drops it. Our stopgap derivation (net income ÷ share count) produces
  **2.66** — 14% high, in the denominator of every multiple on the page.
- **Issuer-extension concepts.** 2,279 companies (39% of the universe) report at
  least one extension fact of $100M or more. Their element names are the
  issuer's own invention, so no tag chain can ever match them by name.

Measured against a single quarter (2026q1) of SEC's Financial Statement Data
Sets: **474 companies** have a dimension-qualified annual EPS, **127 of them**
currently carry a stale or empty EPS series that this would repair.

---

## 1. Source decision: the DERA datasets, not iXBRL parsing

SEC publishes quarterly **Financial Statement Data Sets** at
`sec.gov/files/dera/data/financial-statement-data-sets/<YYYY>q<N>.zip`
(~85MB compressed; `num.txt` is ~560MB uncompressed). Verified structure:

| Column | What it gives us |
|---|---|
| `adsh` | accession — restatement ordering and provenance, exactly as today |
| `tag`, `version` | `us-gaap/2025` for standard concepts; the filer's own namespace marks an **extension** |
| `segments` | the dimensions Company Facts drops (`ClassOfStock=CommonStock;`) |
| `ddate`, `qtrs` | period end and duration (`0` = instant, `4` = annual) |
| `uom`, `value`, `coreg` | unit, figure, co-registrant |

**Why not parse Inline XBRL ourselves.** Reading the filings directly means an
XBRL processor: iXBRL extraction from HTML, per-filer taxonomy schema
resolution, linkbase arcs, context and unit resolution, dimension defaults.
That is Arelle-class work, it breaks across taxonomy versions, and it would run
over 6,000 filers × dozens of filings each. DERA is the same data already
normalized by the SEC, in one file per quarter. The cost of choosing it is a
publication lag of roughly one month after quarter end — which is why **Company
Facts stays the primary source**; DERA only fills what it cannot express.

Rejected for the same reason as before: the Company Concept API (identical
undimensioned limitation) and Frames (likewise).

---

## 2. Architecture — one new source, no new engine concepts

```
sources/dera.py  ──>  cache: dimensioned_<CIK>.json   ──>  normalize.py
   (layer 1)          (shaped like companyfacts)          (layer 2, unchanged shape)
```

The sidecar is written in the *same shape as companyfacts*, so layer 2 reads it
with the existing `_entries` / `_latest_instant` machinery and every figure keeps
carrying a `Fact` with `Provenance`. Provenance gains one field: the segment
string. **Layer 3 never learns that dimensions exist** — the screens keep taking
a `FinancialSnapshot` and nothing else.

Ingest filters hard, so the sidecars stay small: only CIKs in our universe, only
tags our chains already name plus the per-share family, `coreg` rows dropped.

New command, idempotent and resumable like `bulk`:

```sh
python -m screener.sync dera --from 2018q1     # ~32 quarters, one download each
```

---

## 3. The hard part is selection, not fetching

A dimension answers "which slice", and picking the wrong slice is precisely the
failure mode this project has spent every release guarding against — a wrong
per-share figure reads as a bargain. The rules, in order:

1. **Undimensioned always wins.** A dimensioned fact may only fill a gap. It
   never overrides a consolidated figure.
2. **Never sum a non-additive concept.** EPS, per-share values, ratios: pick one
   member or leave it missing. Summing share-class EPS is meaningless arithmetic.
3. **Single member is unambiguous.** When exactly one member exists for the
   concept and period — KKR's lone `ClassOfStock=CommonStock` — that *is* the
   company's figure. This case alone covers most of the 474.
4. **Multiple members require proof.** A ticker is one share class, and HEI and
   HEI.A are different securities at different prices. Use a dimensioned
   per-share fact only when the ticker maps to a class on evidence (SEC's
   `company_tickers_exchange.json` plus the class facts on the cover). With no
   proof, leave it missing — the invariant that has held all along.
5. **Additive concepts may be summed only with a reconciliation.** Share counts
   across classes may be added when the members are provably disjoint *and* the
   sum agrees with an independent total (the dei cover count) within tolerance.
   Otherwise missing.
6. **Every dimensioned figure discloses itself** — the segment string in
   provenance, a flag in the payload, and the member named in the UI's
   provenance table.

---

## 4. Extension concepts: disclose them, do not compute with them

An extension tag's name is invented by the filer, so no chain can match it and
no heuristic should try to guess its meaning. Version 1 therefore **shows them
without using them**: a Detail section listing the issuer-specific concepts a
filer reports that no standard tag captures, with values and — from `pre.txt` —
where they sit in the statement. Asbury's franchise rights become visible as a
named balance-sheet item the screener does not fold into tangible book, rather
than silently absent.

Folding them into totals (via `pre.txt` parent and statement placement) is a
later step, and only behind the harness.

---

## 5. Verification gates — nothing ships without these

- **A/B against the current derivation.** For the ~216 companies where EPS is
  derived today, compare with the DERA-reported figure. KKR: 2.66 derived vs
  2.34 reported. Every disagreement over 10% is reported as a finding, the
  reported figure wins, and the derivation survives only where DERA has nothing.
  The derivation is retired per company, never left running in parallel.
- **A dimension layer in the coverage harness**: EPS × shares ≈ income available
  to common; the class-sum of shares ≈ the cover count. New mismatches fail the
  run exactly as they do now.
- **Fixture plus counterexample per rule**, under the standing merge rule: one
  real company proving the behaviour, one proving the guard.
- **No silent overwrites.** A figure that changes source changes provenance, and
  the provenance table already shows it.

---

## 6. Staging

| Step | Content | Ships when |
|---|---|---|
| 5a | `sources/dera.py`, `sync dera`, sidecar cache. No engine change. | coverage measured across all quarters |
| 5b | A/B report: derived vs reported EPS, published as findings | before any engine change |
| 5c | Dimensioned standard tags into `normalize.py` — **single-member rule only** — plus the harness dimension layer | fixtures green, harness clean |
| 5d | Multi-class ticker→share-class mapping (the risky one) | only with evidence-backed mapping |
| 5e | Extension-concept disclosure in the UI | after 5c |
| 5f | Foreign and IFRS filers — the same machinery reads `ifrs-full` from the `version` column, which is what hiding them was waiting for | last |

## 7. Cost and residual risk

Roughly 2.7GB of downloads for eight years of quarters, transient; the sidecars
are small. One-time ingest on the order of an hour. Restatements keep working
because DERA is accession-keyed and latest-filed still wins.

The residual risks are honest ones: dimensioned facts trail Company Facts by up
to a quarter plus a month, so a fresh figure and a dimensioned one can disagree
on date — the staleness guard already refuses to price stale earnings. And the
multi-class mapping in 5d is the one place where a wrong answer is worse than no
answer, which is why it ships last and behind evidence.
