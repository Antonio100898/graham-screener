// The two chapter-18 figures, and the one way they must not fail: 93% of filers
// tag no combined debt rollup, so folding an unknown debt to zero would have
// printed a utility's market cap as the price of the whole enterprise.
import assert from "node:assert/strict";
import test from "node:test";
import { awardOverhang, totalCapitalisation, workingCapitalToDebt } from "../src/capital.js";

const KO = { price: 91.1, shares: 4302.5e6, debt: 43.86e9,
             current_assets: 26.7e9, current_liabilities: 27.5e9 };

test("total capitalisation adds the debt to the market value of the common", () => {
  assert.equal(Math.round(totalCapitalisation(KO) / 1e9), 436);
});

test("foreign-filer capitalisation is measured on the statement-currency basis", () => {
  const toyota = {
    price: 200,
    price_reporting_currency: 30000,
    reporting_currency: "JPY",
    quote_currency: "USD",
    shares: 10,
    debt: 50000,
  };
  assert.equal(totalCapitalisation(toyota), 350000);
});

test("an unknown debt withholds both figures instead of reading as debt-free", () => {
  const aes = { ...KO, debt: null };          // AES: no bucket the engine will settle
  assert.equal(totalCapitalisation(aes), null);
  assert.equal(workingCapitalToDebt(aes), null);
});

test("no price means no capitalisation, but the debt ratio still stands", () => {
  const unpriced = { ...KO, price: null };
  assert.equal(totalCapitalisation(unpriced), null);
  assert.ok(workingCapitalToDebt(unpriced) < 0);
});

test("a company that owes nothing says so rather than dividing by zero", () => {
  assert.equal(workingCapitalToDebt({ ...KO, debt: 0 }), "no debt");
});

test("equity awards are shown against the count they would dilute", () => {
  // Coca-Cola: 27.0M options on 4,302.5M shares, no RSU count on file
  assert.equal(awardOverhang({ equity_awards: 27.0e6, shares: 4302.5e6 }).toFixed(2), "0.63");
});

test("options and restricted stock are one overhang, not two", () => {
  assert.equal(awardOverhang({ equity_awards: 9e6, shares: 100e6 }), 9);
});

test("a filer that tags neither kind has said nothing, not zero", () => {
  // Apple tags no option or RSU balance in Company Facts or in five quarters of DERA
  assert.equal(awardOverhang({ equity_awards: null, shares: 14840e6 }), null);
});
