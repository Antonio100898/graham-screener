// Formatting of the price-history figures. Both helpers exist because the raw
// numbers read badly: "137 weeks" and "−0% below the high".
import assert from "node:assert/strict";
import test from "node:test";
import { below, spell } from "../src/format.js";

test("a price at its own high is 0% below it, not minus zero", () => {
  assert.equal(below(0), "0%");
  assert.equal(below(0.4), "0%");
  assert.equal(below(20.4), "−20%");
  assert.equal(below(null), "—");
});

test("weeks are spelled in the unit a reader thinks in", () => {
  assert.equal(spell(0), "0 weeks");
  assert.equal(spell(1), "1 week");
  assert.equal(spell(7), "7 weeks");
  assert.equal(spell(13), "3 months");
  assert.equal(spell(128), "2y 5m");
  assert.equal(spell(261), "5 years");
  assert.equal(spell(null), "—");
});
