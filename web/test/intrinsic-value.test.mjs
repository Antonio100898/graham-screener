import assert from "node:assert/strict";
import test from "node:test";
import {
  calculateGrowthValuationMatrix,
  calculateIntrinsicValue,
  companyIntrinsicValuePrefill,
  launcherPoint,
  mergeCompanyIntrinsicValueInputs,
  parseDiscountRates,
  parseGrowthRates,
  snapLauncherPoint,
}
  from "../src/intrinsicValue.js";

test("company IV prefill uses the newest displayed FCF and current shares", () => {
  const prefill = companyIntrinsicValuePrefill({
    ticker: "JNJ",
    currency: "USD",
    shares: 2_405_000_000,
    owner_earnings: {
      annual_per_share: {
        2025: { cash_flow_bridge: { free_cash_flow: null } },
        2024: { cash_flow_bridge: { free_cash_flow: [18_000_000_000, "tag"] } },
        2023: { cash_flow_bridge: { free_cash_flow: { value: 17_000_000_000 } } },
      },
    },
  });

  assert.deepEqual(prefill, {
    ticker: "JNJ",
    fiscalYear: 2024,
    currentIncome: 18_000_000_000,
    shares: 2_405_000_000,
    currency: "USD",
    ready: true,
  });
});

test("company prefill preserves every saved forecast assumption", () => {
  const current = {
    currentIncome: "1",
    shares: "2",
    years: 7,
    growthRates: "3, 6, 9",
    discountRates: "9, 11",
    terminalGrowth: "2.5",
    currency: "USD",
  };
  const merged = mergeCompanyIntrinsicValueInputs(current, {
    ready: true,
    currentIncome: 90,
    shares: 10,
    currency: "EUR",
  });

  assert.deepEqual(merged, {
    ...current,
    currentIncome: "90",
    shares: "10",
    currency: "EUR",
  });
});

test("company prefill keeps missing FCF missing instead of inventing zero", () => {
  const prefill = companyIntrinsicValuePrefill({ shares: 100, owner_earnings: {
    annual_per_share: { 2025: { cash_flow_bridge: {} } },
  } });
  assert.equal(prefill.currentIncome, null);
  assert.equal(prefill.ready, false);
});

test("a constant zero-growth cash flow values as a perpetuity across the forecast boundary", () => {
  const result = calculateIntrinsicValue({
    cashFlows: [100, 100, 100, 100, 100],
    terminalIncome: 100,
    discountRate: 0.10,
    shares: 100,
  });

  assert.ok(Math.abs(result.equityValue - 1000) < 1e-9);
  assert.ok(Math.abs(result.perShare - 10) < 1e-9);
  assert.ok(Math.abs(result.forecastPresentValue + result.terminalPresentValue - 1000) < 1e-9);
});

test("missing forecast evidence is not silently converted to zero", () => {
  assert.equal(calculateIntrinsicValue({
    cashFlows: [100, "", 120], terminalIncome: 120, discountRate: 0.1, shares: 10,
  }), null);
  assert.equal(calculateIntrinsicValue({
    cashFlows: [100], terminalIncome: 100, discountRate: 0.1, shares: 0,
  }), null);
});

test("Gordon Growth uses next-year cash flow and rejects g at or above r", () => {
  const result = calculateIntrinsicValue({
    cashFlows: [100],
    terminalIncome: 100,
    discountRate: 0.10,
    terminalGrowthRate: 0.02,
    shares: 100,
  });

  assert.equal(result.terminalNextYearCashFlow, 102);
  assert.ok(Math.abs(result.terminalValueAtHorizon - 1275) < 1e-9);
  assert.ok(Math.abs(result.perShare - 12.5) < 1e-9);
  assert.equal(calculateIntrinsicValue({
    cashFlows: [100],
    terminalIncome: 100,
    discountRate: 0.02,
    terminalGrowthRate: 0.02,
    shares: 100,
  }), null);
});

test("parses several positive return assumptions and removes duplicates", () => {
  assert.deepEqual(parseDiscountRates("8, 10; 12 10 bad 0 -4"), [8, 10, 12]);
  assert.deepEqual(parseGrowthRates("-10, 0, 5 5 bad -101"), [-10, 0, 5]);
});

test("builds future years automatically and crosses growth with required return", () => {
  const matrix = calculateGrowthValuationMatrix({
    currentIncome: 100,
    years: 5,
    growthRates: [0, 5],
    discountRates: [8, 10],
    terminalGrowthPercent: 0,
    shares: 100,
  });

  assert.equal(matrix.length, 2);
  assert.deepEqual(matrix.map((row) => row.cells.length), [2, 2]);
  assert.ok(Math.abs(matrix[1].cells[0].perShare - 10) < 1e-9);
  assert.ok(Math.abs(matrix[0].cells[1].finalYearIncome - 100 * Math.pow(1.05, 5)) < 1e-9);
  assert.ok(matrix[0].cells[0].perShare > matrix[1].cells[0].perShare);
  assert.ok(matrix[0].cells[1].perShare > matrix[0].cells[0].perShare);
});

test("the launcher snaps to an edge, becomes a corner nearby, and follows resizes", () => {
  const viewport = { width: 1000, height: 700 };
  const left = snapLauncherPoint({ x: 22, y: 350 }, viewport);
  assert.equal(left.edge, "left");
  assert.ok(left.ratio > 0 && left.ratio < 1);
  assert.equal(launcherPoint(left, viewport).x, 16);

  const bottomRight = snapLauncherPoint({ x: 920, y: 640 }, viewport);
  assert.deepEqual(bottomRight, { edge: "bottom", ratio: 1 });
  assert.deepEqual(launcherPoint(bottomRight, viewport), { x: 926, y: 626 });
  assert.deepEqual(launcherPoint(bottomRight, { width: 1200, height: 800 }), {
    x: 1126,
    y: 726,
  });
});
