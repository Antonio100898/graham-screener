import assert from "node:assert/strict";
import test from "node:test";
import { ownerEarningsTrend, ownerMetricTrend } from "../src/ownerEarnings.js";

function series(values, latest = 2025) {
  return {
    fiscal_year: latest,
    annual_per_share: Object.fromEntries(
      Object.entries(values).map(([year, value]) => [
        year, { maintenance_estimate_per_share: value },
      ]),
    ),
  };
}

test("shows ten explicit years and measures a steady seven-percent compound record", () => {
  const values = {};
  for (let year = 2016; year <= 2025; year += 1)
    values[year] = 2 * Math.pow(1.07, year - 2016);

  const trend = ownerEarningsTrend(series(values));

  assert.deepEqual(trend.rows.map((row) => row.fiscalYear),
    [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]);
  assert.equal(trend.yearsPresent, 10);
  assert.equal(trend.comparableSteps, 9);
  assert.equal(trend.yearsIncreased, 9);
  assert.equal(trend.yearsAtLeastSix, 9);
  assert.ok(Math.abs(trend.cagr - 7) < 1e-9);
});

test("keeps a missing filing year blank and does not bridge it with a fake YoY", () => {
  const values = Object.fromEntries(
    Array.from({ length: 10 }, (_, i) => [2016 + i, 10 + i]),
  );
  delete values[2021];

  const trend = ownerEarningsTrend(series(values));
  const byYear = Object.fromEntries(trend.rows.map((row) => [row.fiscalYear, row]));

  assert.equal(trend.yearsPresent, 9);
  assert.equal(trend.comparableSteps, 7);
  assert.equal(byYear[2021].perShare, null);
  assert.equal(byYear[2022].yoy, null);
});

test("withholds percentage growth and CAGR when the base estimate is non-positive", () => {
  const trend = ownerEarningsTrend(series({ 2016: -2, 2017: 1, 2025: 3 }));

  assert.equal(trend.cagr, null);
  assert.equal(trend.rateSteps, 0);
  assert.equal(trend.rows.find((row) => row.fiscalYear === 2017).yoy, null);
});

test("supplements endpoint CAGR with medians, drawdown, variability, and shorter windows", () => {
  const values = [10, 12, 9, 15, 18, 16, 20, 22, 19, 24];
  const trend = ownerEarningsTrend(series(
    Object.fromEntries(values.map((value, index) => [2016 + index, value])),
  ));

  assert.equal(trend.median10, 17);
  assert.equal(trend.median5, 20);
  assert.equal(trend.yearsProfitable, 10);
  assert.equal(trend.yearsMissing, 0);
  assert.ok(trend.cagr3 > 0);
  assert.ok(trend.cagr5 > 0);
  assert.equal(trend.worstYoyDecline, 25);
  assert.equal(trend.maximumDrawdown, 25);
  assert.ok(trend.variability > 0);
  assert.ok(trend.latestVsMedian10 > 40);
});

test("tracks total values and warns when declining totals are hidden by buybacks", () => {
  const annual = {};
  for (let year = 2016; year <= 2025; year += 1) {
    const index = year - 2016;
    const total = 100 - index * 2;
    const shares = 100 - index * 4;
    annual[year] = {
      reported_earnings_assumption: total,
      reported_earnings_assumption_per_share: total / shares,
      diluted_shares: shares,
    };
  }
  const trend = ownerEarningsTrend({ fiscal_year: 2025, annual_per_share: annual });
  assert.ok(trend.cagr > 0);
  assert.ok(trend.totalCagr < 0);
  assert.ok(trend.shareCountCagr < 0);
  assert.equal(trend.buybackDriven, true);
});

test("builds the same stability record for conservative FCF variants", () => {
  const oe = {
    fiscal_year: 2025,
    annual_per_share: {
      2024: { free_cash_flow_after_stock_compensation_per_share: 2 },
      2025: { free_cash_flow_after_stock_compensation_per_share: 3 },
    },
  };
  const trend = ownerMetricTrend(
    oe,
    "free_cash_flow_after_stock_compensation_per_share",
    "free_cash_flow_after_stock_compensation",
  );
  assert.equal(trend.rows[0].perShare, 3);
  assert.equal(trend.rows[1].perShare, 2);
});
