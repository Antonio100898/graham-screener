/** Build an explicit ten-fiscal-year maintenance≈D&A estimate/share record.
 * Missing years remain rows, and percentage growth is withheld when a non-positive
 * base would make the percentage economically misleading. */
export function ownerEarningsTrend(oe, length = 10) {
  const annual = oe?.annual_per_share ?? {};
  const latestFiscalYear = Number(oe?.fiscal_year);
  if (!Number.isFinite(latestFiscalYear) || length < 1) return null;

  const firstFiscalYear = latestFiscalYear - length + 1;
  const ascending = [];
  for (let fiscalYear = firstFiscalYear; fiscalYear <= latestFiscalYear; fiscalYear += 1) {
    const cell = annual[fiscalYear] ?? annual[String(fiscalYear)] ?? null;
    const value = cell?.maintenance_estimate_per_share;
    ascending.push({
      fiscalYear,
      cell,
      perShare: Number.isFinite(value) ? value : null,
      yoy: null,
    });
  }

  let comparableSteps = 0;
  let rateSteps = 0;
  let yearsIncreased = 0;
  let yearsAtLeastSix = 0;
  for (let i = 1; i < ascending.length; i += 1) {
    const previous = ascending[i - 1].perShare;
    const current = ascending[i].perShare;
    if (previous == null || current == null) continue;
    comparableSteps += 1;
    if (current > previous) yearsIncreased += 1;
    if (previous <= 0) continue;
    const yoy = (current / previous - 1) * 100;
    ascending[i].yoy = yoy;
    rateSteps += 1;
    if (yoy >= 6) yearsAtLeastSix += 1;
  }

  const base = ascending[0].perShare;
  const latest = ascending[ascending.length - 1].perShare;
  const span = length - 1;
  const cagr = span > 0 && base > 0 && latest > 0
    ? (Math.pow(latest / base, 1 / span) - 1) * 100
    : null;

  return {
    firstFiscalYear,
    latestFiscalYear,
    rows: ascending.reverse(),
    yearsPresent: ascending.filter((row) => row.perShare != null).length,
    yearsExpected: length,
    comparableSteps,
    rateSteps,
    yearsIncreased,
    yearsAtLeastSix,
    cagr,
  };
}
