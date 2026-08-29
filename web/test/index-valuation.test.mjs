import assert from "node:assert/strict";
import test from "node:test";
import { indexValuation, medianPositive, reportedRate } from "../src/screen.js";

const row = ({ index = "S&P 500", pe = null, pe3 = null, ...extra } = {}) => ({
  idx: index ? [index] : [],
  criteria: [{ n: 1, value: pe }],
  pe3,
  ...extra,
});

test("medianPositive averages the middle pair and never treats missing values as zero", () => {
  assert.equal(medianPositive([null, -4, 0, 10, 30, Number.POSITIVE_INFINITY]), 20);
  assert.equal(medianPositive([null, 0, -2]), null);
});

test("a missing reported rate is distinguished from a zero rate", () => {
  assert.equal(reportedRate(null), "Not available");
  assert.equal(reportedRate(0), "0.0%");
  assert.equal(reportedRate(12.114), "12.1%");
});

test("index valuation uses the full named-index cohort and reports usable denominators", () => {
  const result = indexValuation([
    row({ pe: 10, pe3: 12 }),
    row({ pe: 30, pe3: 42 }),
    row({ pe: null, pe3: -5 }),
    row({ pe: 0, pe3: null }),
    row({ index: "DJIA", pe: 1, pe3: 2 }),
  ], "S&P 500");

  assert.deepEqual(result, {
    members: 4,
    pe: { median: 20, count: 2 },
    pe3: { median: 27, count: 2 },
  });
});

test("current P/E comes from settled criterion 1 rather than browser arithmetic", () => {
  const result = indexValuation([
    row({ pe: 14, pe3: 16, price: 999, ttm_eps: 1 }),
  ], "S&P 500");

  assert.equal(result.pe.median, 14);
});
