import test from "node:test";
import assert from "node:assert/strict";

import { matchesPortfolio, openPortfolioCiks, reviewChanges } from "../src/portfolio.js";


test("a pre-trade quote cannot create a price-dependent exit-review signal", () => {
  const position = {
    quote_after_latest_trade: false,
    criterion_changes: [
      { n: 1, from: "PASS", to: "FAIL", price_dependent: true },
      { n: 3, from: "PASS", to: "FAIL", price_dependent: false },
    ],
  };

  assert.deepEqual(reviewChanges(position).map((change) => change.n), [3]);
});


test("a post-trade quote can create a price-dependent exit-review signal", () => {
  const position = {
    quote_after_latest_trade: true,
    criterion_changes: [
      { n: 1, from: "PASS", to: "FAIL", price_dependent: true },
    ],
  };

  assert.deepEqual(reviewChanges(position).map((change) => change.n), [1]);
});


test("portfolio search matches ticker and company name case-insensitively", () => {
  const paypal = { ticker: "PYPL", name: "PayPal Holdings, Inc." };

  assert.equal(matchesPortfolio(paypal, "pypl"), true);
  assert.equal(matchesPortfolio(paypal, "PAYPAL"), true);
  assert.equal(matchesPortfolio(paypal, "Adobe"), false);
});


test("portfolio multi-word search uses the same OR behavior as Research", () => {
  const paypal = { ticker: "PYPL", name: "PayPal Holdings, Inc." };

  assert.equal(matchesPortfolio(paypal, "Adobe PayPal"), true);
});


test("research holding markers include only positive open portfolio positions", () => {
  const ciks = openPortfolioCiks({ positions: [
    { cik: "0001", quantity: 2 },
    { cik: "0002", quantity: "0" },
    { cik: "0003", quantity: -1 },
    { cik: null, quantity: 4 },
  ] });

  assert.deepEqual([...ciks], ["0001"]);
});
