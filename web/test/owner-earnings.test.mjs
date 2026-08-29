import assert from "node:assert/strict";
import test from "node:test";
import { ownerEarningsTrend } from "../src/ownerEarnings.js";

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
