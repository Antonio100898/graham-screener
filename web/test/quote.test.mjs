import test from "node:test";
import assert from "node:assert/strict";

import { quoteIcon, quoteStatus, quoteTone } from "../src/quote.js";

const checked = "2026-08-28T13:10:00+00:00";
const now = Date.parse(checked);


test("an actively traded pre-market quote is identified as extended-hours", () => {
  const row = {
    price: 52.75, price_session: "PRE", market_state: "PRE", market_state_asof: checked,
  };
  assert.equal(quoteStatus(row, now), "Pre-market · open at refresh");
  assert.equal(quoteTone(row, now), "extended");
  assert.equal(quoteIcon(row, now), "◐");
});


test("portfolio rows use current_price for the same quote status", () => {
  const position = {
    current_price: 52.75,
    price_session: "PRE",
    market_state: "PRE",
    market_state_asof: checked,
  };

  assert.equal(quoteStatus(position, now), "Pre-market · open at refresh");
  assert.equal(quoteTone(position, now), "extended");
});


test("a regular close during pre-market discloses that no newer trade was found", () => {
  const row = {
    price: 10, price_session: "REGULAR", market_state: "PRE", market_state_asof: checked,
  };
  assert.equal(quoteStatus(row, now), "RTH quote · pre-market open at refresh");
});


test("outside published sessions the stock is marked sleeping", () => {
  const row = {
    price: 51.25, price_session: "POST", market_state: "CLOSED", market_state_asof: checked,
  };
  assert.equal(quoteStatus(row, now), "After-hours quote · sleeping at refresh");
  assert.equal(quoteTone(row, now), "closed");
  assert.equal(quoteIcon(row, now), "☾");
});


test("an old market-state check is never presented as current", () => {
  const row = {
    price: 51.25, price_session: "POST", market_state: "CLOSED", market_state_asof: checked,
  };
  assert.equal(quoteStatus(row, now + 21 * 60 * 1000),
    "After-hours quote · session status stale");
  assert.equal(quoteTone(row, now + 21 * 60 * 1000), "stale");
  assert.equal(quoteIcon(row, now + 21 * 60 * 1000), "◇");
});


test("missing quotes get an unavailable icon", () => {
  assert.equal(quoteIcon({}, now), "⊘");
});
