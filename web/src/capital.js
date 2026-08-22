// Graham's chapter-18 comparisons price the whole enterprise, not just the
// equity: National General's common looked cheap until its warrants and its debt
// were counted beside it. Both figures below refuse a missing debt figure rather
// than reading it as zero — a company shown debt-free on no evidence is the
// worst answer of the three.

/** Market value of the common plus the debt ahead of it. */
export function totalCapitalisation(row) {
  const marketCap = row.price != null && row.shares != null ? row.price * row.shares : null;
  if (marketCap == null || row.debt == null) return null;
  return marketCap + row.debt;
}

/** How far the working capital covers the debt. "no debt" is an answer, not a gap. */
export function workingCapitalToDebt(row) {
  const { current_assets: ca, current_liabilities: cl, debt } = row;
  if (ca == null || cl == null || debt == null) return null;
  return debt > 0 ? (ca - cl) / debt : "no debt";
}

/** Employee equity awards — options plus restricted stock — as a share of the count
 *  they dilute. Null when neither is tagged: Apple, Microsoft and Nvidia report no
 *  machine-readable count of either, and nothing is not zero. Read `awards_basis`
 *  alongside it, which names the kinds the figure actually contains. */
export function awardOverhang(row) {
  if (row.equity_awards == null || !row.shares) return null;
  return (row.equity_awards / row.shares) * 100;
}
