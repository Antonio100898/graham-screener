import assert from "node:assert/strict";
import test from "node:test";

import { payloadWarnings } from "../src/warnings.js";

test("a pending annual filing discloses that the previous complete filing is in use", () => {
  assert.deepEqual(payloadWarnings({ data_pending: {
    note: "Calculations use the last complete filing.",
    filed: "2026-08-27",
    accession: "000000-26-000001",
  }}), [{
    kind: "Latest filing pending",
    text: "Calculations use the last complete filing.",
    filed: "2026-08-27",
    accession: "000000-26-000001",
  }]);
});

test("a rejected historical-price refresh is visible without inventing a replacement", () => {
  const warnings = payloadWarnings({ price_history_warning: {
    note: "unexplained rescaling; the previously validated history remains in use",
  }});
  assert.equal(warnings[0].kind, "Price history retained");
  assert.match(warnings[0].text, /previously validated history/);
});

test("ordinary rows have no warning marker", () => {
  assert.deepEqual(payloadWarnings({}), []);
});

test("an hourly quote failure discloses that the dated quote was retained", () => {
  const warnings = payloadWarnings({ quote_refresh_warning: {
    note: "the hourly provider request failed; the previous dated quote remains in use",
  }});
  assert.equal(warnings[0].kind, "Quote refresh failed");
  assert.match(warnings[0].text, /previous dated quote/);
});
