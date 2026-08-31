import assert from "node:assert/strict";
import test from "node:test";


globalThis.window = {
  location: { search: "", href: "http://localhost/" },
  history: { replaceState() {} },
  setTimeout,
  clearTimeout,
};
globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
};

const { fetchJson } = await import("../src/api.js");


test("crypto reads stop with a retryable timeout instead of fetching forever", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      reject(new DOMException("aborted", "AbortError"));
    });
  });
  try {
    await assert.rejects(
      fetchJson("/crypto/quote/BTC-USD", { timeoutMs: 5 }),
      /Request timed out after 1 seconds\. Try again\./,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
