import assert from "node:assert/strict";
import test from "node:test";

import { alignmentPoints, alignmentSortValue } from "../src/alignment.js";

const row = (enterprising, defensive) => ({
  alignment: {
    enterprising: { passed: enterprising, total: 6 },
    defensive: { passed: defensive, total: 6 },
  },
});

test("Graham fit points add the Enterprising and Defensive pass counts", () => {
  assert.equal(alignmentPoints(row(1, 1)), 2);
  assert.equal(alignmentPoints(row(4, 5)), 9);
});

test("Graham fit sorts the highest combined score first and reverses on the next click", () => {
  const low = row(1, 1);
  const high = row(4, 5);
  const values = (direction) => [low, high]
    .sort((a, b) => (alignmentSortValue(a) - alignmentSortValue(b)) * direction)
    .map(alignmentPoints);

  assert.deepEqual(values(1), [9, 2]);
  assert.deepEqual(values(-1), [2, 9]);
});

test("Graham fit points stay missing when either displayed score is unavailable", () => {
  assert.equal(alignmentPoints({ alignment: { enterprising: { passed: 4 } } }), null);
  assert.equal(alignmentPoints({}), null);
});
