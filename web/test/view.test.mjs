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

const { loadView, saveView, takeOverScrollRestoration } = await import("../src/view.js");

beforeEach(() => store.clear());

test("a first visit gets the default working view", () => {
  const v = loadView();
  assert.deepEqual(v.grades, ["NEAR-PASS", "CLOSE"]);
  assert.equal(v.minCap, 500e6);
  assert.equal(v.scroll, 0);
});

test("filters, sort and search survive a reload", () => {
  saveView({
    q: "steel", grades: ["BLOCKED"], sectors: ["Energy"], venues: ["NYSE"],
    minMet: 5, trackedOnly: true, sort: { key: "pe", dir: -1 },
  });
  const v = loadView();
  assert.equal(v.q, "steel");
  assert.deepEqual(v.grades, ["BLOCKED"]);
  assert.deepEqual(v.sectors, ["Energy"]);
  assert.deepEqual(v.venues, ["NYSE"]);
  assert.equal(v.minMet, 5);
  assert.equal(v.trackedOnly, true);
  assert.deepEqual(v.sort, { key: "pe", dir: -1 });
  assert.equal(v.minCap, 500e6, "settings that were not touched keep their value");
});

test("saving the scroll position leaves the filters alone", () => {
  saveView({ q: "steel", minMet: 5 });
  saveView({ scroll: 1420 });
  const v = loadView();
  assert.equal(v.scroll, 1420);
  assert.equal(v.q, "steel");
  assert.equal(v.minMet, 5);
});

test("corrupt storage falls back to defaults instead of breaking the app", () => {
  store.set("screener-view", "{ not json");
  assert.deepEqual(loadView().grades, ["NEAR-PASS", "CLOSE"]);
});

test("browser scroll restoration is taken over", () => {
  takeOverScrollRestoration();
  assert.equal(history.scrollRestoration, "manual");
});

test("companies a criterion cannot apply to are hidden unless asked for", () => {
  // Banks and REITs file no classified balance sheet, so criteria 2 and 3 can never
  // be answered for them. Default the filter on, but let an explicit choice stand —
  // a stored false must not be overwritten by the default.
  assert.equal(loadView().hideNoApply, true);
  saveView({ hideNoApply: false });
  assert.equal(loadView().hideNoApply, false);
});
