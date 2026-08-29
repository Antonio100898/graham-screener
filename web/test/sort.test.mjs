import assert from "node:assert/strict";
import test from "node:test";

import { compareRows, normalizeSort, updateSort } from "../src/sort.js";

test("old single-column saved sorts remain valid", () => {
  assert.deepEqual(normalizeSort({ key: "pe", dir: -1 }), [{ key: "pe", dir: -1 }]);
});

test("Shift-click adds and toggles secondary columns while a regular click resets", () => {
  let sort = updateSort([{ key: "fit", dir: 1 }], "pe", true);
  assert.deepEqual(sort, [{ key: "fit", dir: 1 }, { key: "pe", dir: 1 }]);

  sort = updateSort(sort, "pe", true);
  assert.deepEqual(sort, [{ key: "fit", dir: 1 }, { key: "pe", dir: -1 }]);

  assert.deepEqual(updateSort(sort, "ticker", false), [{ key: "ticker", dir: 1 }]);
});

test("multiple columns put maximum Graham points at minimum P/E first", () => {
  const rows = [
    { ticker: "LOW", points: 2, pe: 1 },
    { ticker: "HIGHERPE", points: 9, pe: 10 },
    { ticker: "BEST", points: 9, pe: 5 },
  ];
  const sorts = [{ key: "fit", dir: 1 }, { key: "pe", dir: 1 }];
  const valueOf = (row, key) => key === "fit" ? -row.points : row[key];

  rows.sort((a, b) => compareRows(a, b, sorts, valueOf));
  assert.deepEqual(rows.map((row) => row.ticker), ["BEST", "HIGHERPE", "LOW"]);
});

test("missing secondary values stay last within equal primary scores", () => {
  const rows = [
    { ticker: "MISSING", points: 9, pe: null },
    { ticker: "KNOWN", points: 9, pe: 8 },
  ];
  const sorts = [{ key: "fit", dir: 1 }, { key: "pe", dir: -1 }];
  const valueOf = (row, key) => key === "fit" ? -row.points : row[key];

  rows.sort((a, b) => compareRows(a, b, sorts, valueOf));
  assert.deepEqual(rows.map((row) => row.ticker), ["KNOWN", "MISSING"]);
});
