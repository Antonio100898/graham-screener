import assert from "node:assert/strict";
import test from "node:test";

import config from "../vite.config.js";


test("development server proxies persistent and sync API routes to FastAPI", () => {
  const proxy = config.server.proxy;
  for (const route of ["/tracked", "/portfolio", "/portfolios", "/crypto", "/sync", "/config"])
    assert.equal(proxy[route], "http://127.0.0.1:8000", `${route} must not hit Vite's SPA fallback`);
});
