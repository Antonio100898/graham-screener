// Precedence of the closeness grade. The order is deliberate and has been wrong
// in both directions, so it is pinned here.
import assert from "node:assert/strict";
import test from "node:test";
import { closeness } from "../src/screen.js";

const row = (statuses) => ({
  criteria: [1, 2, 3, 4, 5, 7].map((n) => ({ n, status: statuses[n] ?? "PASS" })),
});

test("every criterion met is a pass", () => {
  assert.equal(closeness(row({})).label, "PASSES");
});

test("a business failure outranks an unknown — we know why it fails", () => {
  const g = closeness(row({ 4: "FAIL", 3: "INSUFFICIENT_DATA" }));
  assert.equal(g.label, "BLOCKED");
  assert.match(g.note, /cannot be measured/);
});

test("an unknown outranks a valuation failure — no price settles it", () => {
  const g = closeness(row({ 1: "FAIL", 2: "NOT_APPLICABLE", 3: "NOT_APPLICABLE" }));
  assert.equal(g.label, "UNGRADEABLE", "a bank failing on price is not near passing");
  assert.match(g.note, /no price makes the unknown ones pass/);
});

test("valuation alone, everything else measured, is genuinely near", () => {
  assert.equal(closeness(row({ 7: "FAIL" })).label, "NEAR-PASS");
  assert.equal(closeness(row({ 1: "FAIL", 7: "FAIL" })).label, "CLOSE");
  assert.equal(closeness(row({ 7: "FAIL" })).unknown, 0);
});

test("insufficient data alone is ungradeable", () => {
  assert.equal(closeness(row({ 7: "INSUFFICIENT_DATA" })).label, "UNGRADEABLE");
});
