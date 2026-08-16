// P/E on the 3-year average EPS: smooths one bad year, refuses stale earnings.
import assert from "node:assert/strict";
import test from "node:test";
import { pe3 } from "../src/screen.js";

const row = (eps, price = 30, asof = "2026-08-15") =>
  ({ annual_eps: eps, price, price_asof: asof });

test("averages the three most recent annual years", () => {
  // (6 + 3 + 0) / 3 = 3 → 30 / 3 = 10; the loss year dilutes, not disqualifies
  assert.equal(pe3(row({ 2022: 9, 2023: 6, 2024: 3, 2025: 0 })), 10);
});

test("null when the average is not positive", () => {
  assert.equal(pe3(row({ 2023: 1, 2024: -2, 2025: 1 })), null);
});

test("null under three years or without a price", () => {
  assert.equal(pe3(row({ 2024: 5, 2025: 5 })), null);
  assert.equal(pe3(row({ 2023: 5, 2024: 5, 2025: 5 }, null)), null);
});

test("dormant filer's stale earnings are refused", () => {
  assert.equal(pe3(row({ 2013: 5, 2014: 5, 2015: 5 })), null);
  // two years behind the quote is the normal reporting lag and still prices
  assert.equal(pe3(row({ 2022: 5, 2023: 5, 2024: 5 })), 6);
});
