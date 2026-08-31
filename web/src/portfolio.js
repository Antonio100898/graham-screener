/** PASS→FAIL changes that are meaningful after the position's latest trade. */
export function reviewChanges(position) {
  return (position.criterion_changes ?? []).filter((change) =>
    change.from === "PASS" && change.to === "FAIL"
      && (position.quote_after_latest_trade !== false || !change.price_dependent)
  );
}


/** Portfolio search mirrors Research's phrase/word OR behavior. */
export function matchesPortfolio(position, query) {
  const phrase = String(query ?? "").trim().toLowerCase();
  if (!phrase) return true;
  const words = phrase.split(/[\s,]+/).filter((word) => word.length > 1);
  const needles = words.length ? [phrase, ...words] : [phrase];
  const haystack = [position?.ticker, position?.name]
    .filter(Boolean).join(" ").toLowerCase();
  return needles.some((needle) => haystack.includes(needle));
}


/** Bonds and crypto use the same search behavior as stock positions. */
export function matchesPortfolioAsset(asset, query) {
  const phrase = String(query ?? "").trim().toLowerCase();
  if (!phrase) return true;
  const words = phrase.split(/[\s,]+/).filter((word) => word.length > 1);
  const needles = words.length ? [phrase, ...words] : [phrase];
  const haystack = [asset?.symbol, asset?.name, asset?.note]
    .filter(Boolean).join(" ").toLowerCase();
  return needles.some((needle) => haystack.includes(needle));
}


export function portfolioHoldingCount(portfolio) {
  return Number(portfolio?.summary?.holdings
    ?? (portfolio?.positions?.length ?? 0)
      + (portfolio?.assets?.bonds?.length ?? 0)
      + (portfolio?.assets?.crypto?.length ?? 0));
}


/** CIKs with a positive open position. A closed ledger history is never a holding. */
export function openPortfolioCiks(portfolio) {
  return new Set((portfolio?.positions ?? [])
    .filter((position) => Number(position?.quantity) > 0 && position?.cik)
    .map((position) => position.cik));
}
