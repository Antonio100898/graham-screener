// Screen semantics shared by the table and the detail panel. Criteria 1 and 7 are
// recomputed here against the live price, so a price refresh needs no backend call.

export const CRITERIA = {
  1: "Earnings valuation — P/E < 10",
  2: "Liquidity — current ratio ≥ 1.5",
  3: "Debt ≤ 1.1 × net current assets",
  4: "EPS > 0 in each of the past 5 years",
  5: "Currently pays a dividend",
  7: "Price ≤ 1.2 × tangible book value",
};

// Number 6 is missing on purpose: Graham's earnings-growth requirement measured
// the latest year against a fixed 1966 base, and no modern base year can be
// attributed to him. The comparison is reported in the detail panel instead.
export const TOTAL_CRITERIA = Object.keys(CRITERIA).length;

export const PLAIN = {
  1: "too expensive vs earnings",
  2: "not enough working capital",
  3: "too much debt",
  4: "a loss year in the last five",
  5: "pays no dividend",
  7: "too expensive vs tangible assets",
};

const PRICE_CRITERIA = new Set([1, 7]);

/** Criterion by its number — the array is no longer numbered 1..n positionally. */
export const byN = (row, n) => row.criteria.find((c) => c.n === n);

export function closeness(row) {
  const unmet = row.criteria.filter((c) => c.status !== "PASS");
  if (unmet.length === 0)
    return { label: "PASSES", note: `meets all ${TOTAL_CRITERIA} criteria` };

  // A definitive failure settles the company whatever else is unknown, so it is
  // reported ahead of the unknowns. Checking unknowns first would file a known
  // failure under "we cannot say", which throws away a fact we actually have.
  const business = unmet.filter((c) => c.status === "FAIL" && !PRICE_CRITERIA.has(c.n));
  const priceFails = unmet.filter((c) => c.status === "FAIL" && PRICE_CRITERIA.has(c.n));
  const unknown = unmet.filter((c) => c.status !== "FAIL");
  const alsoUnknown = unknown.length
    ? `; ${unknown.length} further criteri${unknown.length === 1 ? "on cannot" : "a cannot"} be measured`
    : "";

  // Anything actually measured and failed outranks what could not be measured: an
  // unknown never rescues a company that already failed a test it did take.
  // Order of precedence:
  //  1. a definitive failure the price cannot fix — we know why it fails
  //  2. anything we could not compute — no verdict is available at any price
  //  3. valuation alone, with every criterion measured — genuinely near
  // Step 2 sits above step 3 deliberately: calling a company "near passing" while
  // a criterion is unknown claims a closeness the data does not support.
  if (business.length)
    return { label: "BLOCKED", unknown: unknown.length,
             note: "a business result, not the price, is in the way" + alsoUnknown };
  if (unknown.length)
    return {
      label: "UNGRADEABLE",
      unknown: unknown.length,
      note: `${unknown.length} criteri${unknown.length === 1 ? "on" : "a"} cannot be computed from its filings` +
        (priceFails.length
          ? `; it also fails ${priceFails.length} valuation test${priceFails.length === 1 ? "" : "s"}, but no price makes the unknown ones pass`
          : " — nothing definitive is known"),
    };
  return {
    label: priceFails.length === 1 ? "NEAR-PASS" : "CLOSE",
    unknown: 0,
    note: `${priceFails.length} valuation test${priceFails.length === 1 ? "" : "s"} unmet, everything else measured and passing — a lower price would complete the screen`,
  };
}

export function whyBlocked(row) {
  const unmet = row.criteria.filter((c) => c.status !== "PASS");
  if (!unmet.length) return "Nothing";
  const price = unmet.filter((c) => c.status === "FAIL" && PRICE_CRITERIA.has(c.n));
  const business = unmet.filter((c) => c.status === "FAIL" && !PRICE_CRITERIA.has(c.n));
  const unknown = unmet.filter((c) => c.status !== "FAIL");
  const parts = [];
  if (business.length) parts.push(business.map((c) => PLAIN[c.n]).join(" and "));
  if (price.length) parts.push(price.map((c) => PLAIN[c.n]).join(" and "));
  if (unknown.length) {
    const ns = new Set(unknown.map((c) => c.n));
    parts.push(
      ns.has(2) && ns.has(3)
        ? "liquidity and debt cannot be measured from its filings"
        : `${unknown.map((c) => PLAIN[c.n] ?? `criterion ${c.n}`).join(" and ")} cannot be measured`,
    );
  }
  const s = parts.join("; ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Price at which every price-dependent criterion would pass; null if price is not the issue. */
export function priceToPass(row) {
  if (!row.price) return null;
  const limits = [];
  const c1 = byN(row, 1);
  const c7 = byN(row, 7);
  if (c1.status === "FAIL" && row.ttm_eps > 0) limits.push(9.99 * row.ttm_eps);
  if (c7.status === "FAIL" && row.tbvps > 0) limits.push(1.2 * row.tbvps);
  if (!limits.length) return null;
  // only meaningful when nothing else blocks it
  const other = row.criteria.filter((c) => c.status !== "PASS" && !PRICE_CRITERIA.has(c.n));
  if (other.length) return null;
  return Math.min(...limits);
}

/** Graham smoothed a lucky or disastrous single year by pricing the average of
 * several: current price over the mean of the three latest annual EPS. TTM is
 * deliberately not mixed in — the annual series is the only dated one we have.
 * Null when years are missing, the average is not positive, or the newest year
 * is too old to price (dormant filers keep tickers and stale earnings). */
export function pe3(row) {
  const eps = row.annual_eps;
  if (!eps || !row.price) return null;
  const years = Object.keys(eps).map(Number).sort((a, b) => b - a).slice(0, 3);
  if (years.length < 3) return null;
  const priceYear = Number((row.price_asof ?? "").slice(0, 4));
  if (priceYear && years[0] < priceYear - 2) return null;
  const avg = (eps[years[0]] + eps[years[1]] + eps[years[2]]) / 3;
  return avg > 0 ? row.price / avg : null;
}
