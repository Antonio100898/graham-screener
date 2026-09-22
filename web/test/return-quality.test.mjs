import assert from "node:assert/strict";
import test from "node:test";

import { returnQuality } from "../src/screen.js";

const row = (roe, roic, ronta, debtToEquity = 0, estimate = null, assumption = null) => ({
  profitability: { on_equity: roe },
  operating_returns: { nopat_roic: roic, ronta },
  operating_returns_estimate: estimate,
  return_quality_assumption: assumption,
  debt_to_equity: debtToEquity,
});

test("return quality rewards three jointly strong operating returns", () => {
  const balanced = returnQuality(row(30, 30, 30));
  assert.equal(balanced.score, 30);
  assert.deepEqual(
    { roe: balanced.roe, roic: balanced.roic, ronta: balanced.ronta },
    { roe: 30, roic: 30, ronta: 30 },
  );
});

test("one denominator-driven outlier cannot dominate return quality", () => {
  const outlier = returnQuality(row(1600, 20, 40));
  const genuinelyStrong = returnQuality(row(80, 80, 80));

  assert.ok(outlier.score < 40);
  assert.ok(genuinelyStrong.score > outlier.score);
});

test("debt to equity penalizes returns that were amplified by leverage", () => {
  const debtFree = returnQuality(row(60, 40, 50, 0));
  const leveraged = returnQuality(row(60, 40, 50, 3));

  assert.equal(leveraged.returnScore, debtFree.returnScore);
  assert.equal(leveraged.score, debtFree.score / 4);
});

test("an irrelevant RONTA is omitted, but sparse returns remain unavailable", () => {
  assert.ok(returnQuality(row(30, null, 40)).score > 0);
  assert.equal(returnQuality(row(30, null, null)).score, null);
  assert.equal(returnQuality(row(30, 0, 40)).score, null);
  assert.equal(returnQuality(row(30, -5, 40)).score, null);
  assert.equal(returnQuality(row(30, 20, 40, null)).score, null);
  assert.equal(returnQuality(row(30, 20, 40, -1)).score, null);
});

test("a disclosed conservative estimate fills only strict blanks", () => {
  const estimate = {
    status: "CONSERVATIVE_LOWER_BOUND",
    nopat_roic: 20,
    ronta: 40,
    operating_return_assumptions: ["intangibles"],
  };
  const quality = returnQuality(row(30, null, null, 0, estimate));

  assert.ok(quality.score > 0);
  assert.equal(quality.estimated, true);
  assert.deepEqual(quality.estimatedInputs, { roic: true, ronta: true });
  assert.deepEqual(quality.assumptions, ["intangibles"]);
});

test("an exact reported return always wins over its estimate", () => {
  const estimate = {
    status: "CONSERVATIVE_LOWER_BOUND",
    nopat_roic: 99,
    ronta: 99,
  };
  const quality = returnQuality(row(30, 20, null, 0, estimate));

  assert.equal(quality.roic, 20);
  assert.equal(quality.ronta, 99);
  assert.deepEqual(quality.estimatedInputs, { roic: false, ronta: true });
});

test("an undisclosed number cannot masquerade as a conservative estimate", () => {
  const quality = returnQuality(row(30, null, null, 0, { nopat_roic: 20, ronta: 40 }));
  assert.equal(quality.score, null);
  assert.equal(quality.estimated, false);
});

test("the exported zero-assumption inputs drive Return Quality by default", () => {
  const assumption = {
    status: "APPLIED",
    roe: 30,
    nopat_roic: 20,
    ronta: 40,
    debt_to_equity: 0,
    applied: ["debt", "intangibles"],
    input_assumptions: {
      roe: [],
      nopat_roic: ["intangibles"],
      ronta: ["intangibles"],
      debt_to_equity: ["debt"],
    },
  };
  const quality = returnQuality(row(30, null, null, null, null, assumption));

  assert.ok(quality.score > 0);
  assert.equal(quality.assumptionMode, true);
  assert.equal(quality.assumptionApplied, true);
  assert.equal(quality.estimated, false);
  assert.deepEqual(quality.assumedInputs, {
    roe: false, roic: true, ronta: true, debtToEquity: true,
  });
  assert.deepEqual(quality.assumptions, ["debt", "intangibles"]);
});

test("an assumed zero operating return produces a zero quality score", () => {
  const assumption = {
    status: "APPLIED",
    roe: 30,
    nopat_roic: 0,
    ronta: 0,
    debt_to_equity: 0,
    applied: ["operating_income"],
    input_assumptions: {
      nopat_roic: ["operating_income"],
      ronta: ["operating_income"],
    },
  };
  const quality = returnQuality(row(30, null, null, null, null, assumption));

  assert.equal(quality.score, 0);
  assert.equal(quality.returnScore, 0);
});
