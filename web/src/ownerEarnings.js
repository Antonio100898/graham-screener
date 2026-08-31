const finite = (value) => Number.isFinite(value) ? value : null;

function median(values) {
  const ordered = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!ordered.length) return null;
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

function fixedWindowCagr(rows, slots, valueKey = "perShare") {
  if (rows.length < slots) return null;
  const window = rows.slice(-slots);
  const base = window[0][valueKey];
  const latest = window[window.length - 1][valueKey];
  const span = slots - 1;
  return span > 0 && base > 0 && latest > 0
    ? (Math.pow(latest / base, 1 / span) - 1) * 100
    : null;
}

function maximumDrawdown(values) {
  let peak = null;
  let worst = null;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (peak == null || value > peak) peak = value;
    if (peak > 0) {
      const decline = (value / peak - 1) * 100;
      if (worst == null || decline < worst) worst = decline;
    }
  }
  return worst == null ? null : Math.abs(Math.min(worst, 0));
}

/** Build one explicit fiscal-year trend without bridging missing years.
 * `perShareKey` names the filing-backed lens; aliases preserve older payloads. */
export function ownerMetricTrend(
  oe,
  perShareKey = "reported_earnings_assumption_per_share",
  totalKey = "reported_earnings_assumption",
  length = 10,
) {
  const annual = oe?.annual_per_share ?? {};
  const latestFiscalYear = Number(oe?.fiscal_year);
  if (!Number.isFinite(latestFiscalYear) || length < 1) return null;

  const firstFiscalYear = latestFiscalYear - length + 1;
  const ascending = [];
  for (let fiscalYear = firstFiscalYear; fiscalYear <= latestFiscalYear; fiscalYear += 1) {
    const cell = annual[fiscalYear] ?? annual[String(fiscalYear)] ?? null;
    let value = finite(cell?.[perShareKey]);
    let total = finite(cell?.[totalKey]);
    if (perShareKey === "reported_earnings_assumption_per_share") {
      value ??= finite(cell?.maintenance_estimate_per_share);
      total ??= finite(cell?.maintenance_estimate);
    }
    const shares = finite(cell?.diluted_shares);
    if (total == null && value != null && shares != null) total = value * shares;
    ascending.push({
      fiscalYear,
      cell,
      perShare: value,
      total,
      shares,
      yoy: null,
      totalYoy: null,
      sharesYoy: null,
    });
  }

  let comparableSteps = 0;
  let rateSteps = 0;
  let yearsIncreased = 0;
  let yearsAtLeastSix = 0;
  let worstYoyDecline = null;
  for (let i = 1; i < ascending.length; i += 1) {
    const previous = ascending[i - 1];
    const current = ascending[i];
    if (previous.perShare != null && current.perShare != null) {
      comparableSteps += 1;
      if (current.perShare > previous.perShare) yearsIncreased += 1;
      if (previous.perShare > 0) {
        current.yoy = (current.perShare / previous.perShare - 1) * 100;
        rateSteps += 1;
        if (current.yoy >= 6) yearsAtLeastSix += 1;
        if (current.yoy < 0 && (worstYoyDecline == null || current.yoy < worstYoyDecline))
          worstYoyDecline = current.yoy;
      }
    }
    if (previous.total > 0 && current.total != null)
      current.totalYoy = (current.total / previous.total - 1) * 100;
    if (previous.shares > 0 && current.shares != null)
      current.sharesYoy = (current.shares / previous.shares - 1) * 100;
  }

  const present = ascending.filter((row) => row.perShare != null);
  const values = present.map((row) => row.perShare);
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  const variability = mean > 0 && values.length > 1
    ? Math.sqrt(values.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0)
      / values.length) / Math.abs(mean) * 100
    : null;
  const latest = ascending[ascending.length - 1].perShare;
  const median10 = median(values);
  const median5 = median(ascending.slice(-5).map((row) => row.perShare));
  const cagr = fixedWindowCagr(ascending, length);
  const totalCagr = fixedWindowCagr(ascending, length, "total");
  const shareCountCagr = fixedWindowCagr(ascending, length, "shares");

  return {
    firstFiscalYear,
    latestFiscalYear,
    rows: [...ascending].reverse(),
    yearsPresent: present.length,
    yearsExpected: length,
    yearsMissing: length - present.length,
    yearsProfitable: values.filter((value) => value > 0).length,
    comparableSteps,
    rateSteps,
    yearsIncreased,
    yearsAtLeastSix,
    cagr,
    cagr5: fixedWindowCagr(ascending, Math.min(5, length)),
    cagr3: fixedWindowCagr(ascending, Math.min(3, length)),
    totalCagr,
    shareCountCagr,
    median5,
    median10,
    latestVsMedian10: latest != null && median10 > 0
      ? (latest / median10 - 1) * 100
      : null,
    worstYoyDecline: worstYoyDecline == null ? null : Math.abs(worstYoyDecline),
    maximumDrawdown: maximumDrawdown(ascending.map((row) => row.perShare)),
    variability,
    buybackDriven: shareCountCagr != null && shareCountCagr < 0
      && totalCagr != null && totalCagr < 0 && cagr != null && cagr > totalCagr,
  };
}

/** Default owner-evidence trend: reported earnings under maintenance capex = D&A. */
export function ownerEarningsTrend(oe, length = 10) {
  return ownerMetricTrend(
    oe,
    "reported_earnings_assumption_per_share",
    "reported_earnings_assumption",
    length,
  );
}
