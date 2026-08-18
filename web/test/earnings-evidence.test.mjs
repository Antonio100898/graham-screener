import assert from "node:assert/strict";
import test from "node:test";
import { earningsQuality, epsEvidence } from "../src/earningsEvidence.js";

const eps10 = Object.fromEntries(Array.from({ length: 10 }, (_, i) => [2016 + i, 1 + i / 10]));
const eps13 = Object.fromEntries(Array.from({ length: 13 }, (_, i) => [2013 + i, 1 + i / 10]));

test("ten-year EPS evidence uses completed fiscal years for stability", () => {
  const result = epsEvidence(eps10);
  assert.equal(result.present, 10);
  assert.equal(result.positive, 10);
  assert.equal(result.stable, true);
  assert.equal(result.growth, null, "ten annual observations do not prove Graham's ten-year three-year-average growth test");
  assert.deepEqual(result.years, [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]);
  assert.deepEqual(result.growthBaseYears, [2013, 2014, 2015]);
});

test("Graham defensive growth requires the two three-year windows thirteen fiscal years apart", () => {
  const result = epsEvidence(eps13);
  // First three average 1.1; last three average 2.1; growth is 90.91%.
  assert.ok(Math.abs(result.growth - 90.90909) < 0.001);
  assert.deepEqual(result.growthBaseYears, [2013, 2014, 2015]);
  assert.deepEqual(result.growthRecentYears, [2023, 2024, 2025]);
});

test("missing history remains incomplete rather than filling years with zero", () => {
  const result = epsEvidence({ 2021: 1, 2022: 1.1, 2023: 1.2, 2024: 1.3, 2025: 1.4 });
  assert.equal(result.present, 5);
  assert.equal(result.stable, false);
  assert.equal(result.growth, null);
});

test("a deficit is visible in the ten-year evidence", () => {
  const result = epsEvidence({ ...eps10, 2020: -0.2 });
  assert.equal(result.positive, 9);
  assert.equal(result.stable, false);
});

test("earnings-quality warning appears only for material EPS and net-income divergence", () => {
  const years = { 2021: 1, 2022: 1.1, 2023: 1.2, 2024: 1.3, 2025: 1.5 };
  const diverging = { 2021: 100, 2022: 95, 2023: 90, 2024: 85, 2025: 70 };
  assert.equal(earningsQuality(years, diverging)?.label, "EPS ↑ · NI ↓");
  assert.equal(earningsQuality(years, { 2021: 100, 2022: 105, 2023: 110, 2024: 120, 2025: 130 }), null);
});
