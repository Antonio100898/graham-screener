import assert from "node:assert/strict";
import test from "node:test";

import { recurringDividendPresentation } from "../src/screen.js";

test("the recurring yield, not special-inclusive cash, is the headline", () => {
  const note = "$1.40 annualized; trailing cash was $4.40 including any specials";
  const shown = recurringDividendPresentation(3.22, note);

  assert.equal(shown.value, "3.22% recurring");
  assert.equal(shown.note, note);
});

test("missing recurring evidence remains missing without inventing a rate", () => {
  assert.deepEqual(recurringDividendPresentation(null, "no reliable recurring rate"), {
    value: "—",
    note: "no reliable recurring rate",
  });
});
