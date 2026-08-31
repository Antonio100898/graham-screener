// Persistence of the working view. Run with: node --test web/test/
import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
};
globalThis.requestAnimationFrame = (fn) => fn();
globalThis.cancelAnimationFrame = () => {};
globalThis.history = { scrollRestoration: "auto" };   // as a browser provides it

const {
  hasActiveFilters, loadView, saveView, takeOverScrollRestoration, unfilteredView,
} = await import("../src/view.js");

beforeEach(() => store.clear());

test("a first visit shows the full universe", () => {
  const v = loadView();
  assert.equal(v.lens, "BOTH");
  assert.equal(v.fit, "ALL");
  assert.equal(v.gaps, "ALL");
  assert.deepEqual(v.sort, { key: "fit", dir: 1 });
  assert.equal(v.minCap, 0);
  assert.equal(v.hideNoApply, false);
  assert.equal(v.scroll, 0);
  assert.equal(hasActiveFilters(v), false);
});

test("filters, sort, lens and Enterprising gaps survive a reload", () => {
  saveView({
    q: "steel", lens: "ENTERPRISING", fit: "BLOCKED", gaps: "ONE_GAP",
    profiles: ["OPERATING"], sectors: ["Energy"], venues: ["NYSE"],
    minMet: 5, minPositiveEps: 9, trackedOnly: true, sort: { key: "eps10", dir: 1 },
  });
  const v = loadView();
  assert.equal(v.q, "steel");
  assert.equal(v.lens, "ENTERPRISING");
  assert.equal(v.fit, "BLOCKED");
  assert.equal(v.gaps, "ONE_GAP");
  assert.deepEqual(v.profiles, ["OPERATING"]);
  assert.deepEqual(v.sectors, ["Energy"]);
  assert.deepEqual(v.venues, ["NYSE"]);
  assert.equal(v.minMet, 5);
  assert.equal(v.minPositiveEps, 9);
  assert.equal(v.trackedOnly, true);
  assert.deepEqual(v.sort, { key: "eps10", dir: 1 });
  assert.equal(v.minCap, 0, "settings that were not touched keep their value");
});

test("saving the scroll position leaves the filters alone", () => {
  saveView({ q: "steel", lens: "DEFENSIVE", minMet: 5, minPositiveEps: 7 });
  saveView({ scroll: 1420 });
  const v = loadView();
  assert.equal(v.scroll, 1420);
  assert.equal(v.q, "steel");
  assert.equal(v.lens, "DEFENSIVE");
  assert.equal(v.minMet, 5);
  assert.equal(v.minPositiveEps, 7);
});

test("a multi-column sort survives a reload in priority order", () => {
  const sort = [{ key: "fit", dir: 1 }, { key: "pe", dir: 1 }];
  saveView({ sort });
  assert.deepEqual(loadView().sort, sort);
});

test("corrupt storage falls back to the unfiltered defaults", () => {
  store.set("screener-view", "{ not json");
  const v = loadView();
  assert.equal(v.lens, "BOTH");
  assert.equal(v.gaps, "ALL");
  assert.deepEqual(v.sort, { key: "fit", dir: 1 });
});

test("browser scroll restoration is taken over", () => {
  takeOverScrollRestoration();
  assert.equal(history.scrollRestoration, "manual");
});

test("clear-all values disable every table filter", () => {
  const cleared = unfilteredView();
  assert.equal(hasActiveFilters(cleared), false);

  for (const patch of [
    { lens: "DEFENSIVE" }, { fit: "BLOCKED" }, { gaps: "ONE_GAP" },
    { profiles: ["OPERATING"] }, { sectors: ["Energy"] }, { venues: ["NYSE"] },
    { indexes: ["S&P 500"] }, { minCap: 500e6 }, { minMet: 1 },
    { minPositiveEps: 5 }, { minRoic: 6 }, { trackedOnly: true },
    { hideNA: true }, { hideNoApply: true }, { belowNcav: true },
  ]) assert.equal(hasActiveFilters({ ...cleared, ...patch }), true, JSON.stringify(patch));
});

test("an explicit applicability filter survives a reload", () => {
  assert.equal(loadView().hideNoApply, false);
  saveView({ hideNoApply: true });
  assert.equal(loadView().hideNoApply, true);
});
