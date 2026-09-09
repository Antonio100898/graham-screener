import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("the company detail panel defaults to strict filing values", async (t) => {
  const previousWindow = globalThis.window;
  const previousLocalStorage = globalThis.localStorage;
  globalThis.window = {
    location: { href: "http://localhost/", search: "" },
    setTimeout,
    clearTimeout,
  };
  globalThis.localStorage = {
    getItem() { return null; },
    setItem() {},
  };
  t.after(() => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previousLocalStorage;
  });

  const vite = await createServer({
    appType: "custom",
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());

  const { default: Detail } = await vite.ssrLoadModule("/src/Detail.jsx");
  const criteria = [1, 2, 3, 4, 5, 7].map((n) => ({
    n,
    status: "INSUFFICIENT_DATA",
    value: null,
  }));
  const row = {
    ticker: "TEST",
    name: "Detail render fixture",
    cik: "1",
    criteria,
    annual_ratios: { 2025: {} },
    assumption_mode: { status: "APPLIED", applied: [] },
  };

  const markup = renderToStaticMarkup(
    React.createElement(Detail, { row, onClose() {} }),
  );

  assert.match(markup, /class="detail clean-detail"/);
  assert.match(markup, />Ratios</);
  assert.match(markup, />TEST</);
  assert.match(markup, /Strict filing values are in use/);
  assert.match(markup, />Apply zero assumptions</);
  assert.doesNotMatch(markup, />Use strict filing values</);
  assert.doesNotMatch(markup, /Return on net tangible assets/);
});

test("foreign canonical rows render their reporting currency and workbook source", async (t) => {
  const previousWindow = globalThis.window;
  globalThis.window = { location: { href: "http://localhost/", search: "" } };
  t.after(() => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  });
  const vite = await createServer({ appType: "custom", server: { middlewareMode: true } });
  t.after(() => vite.close());
  const { default: Detail } = await vite.ssrLoadModule("/src/Detail.jsx");
  const row = {
    ticker: "ADS.DE", name: "adidas AG", cik: "IFRS-ADIDAS-AG", currency: "EUR",
    criteria: [1, 2, 3, 4, 5, 7].map((n) => ({ n, status: "INSUFFICIENT_DATA", value: null })),
    total_assets: 20_262_000_000, current_assets: 11_977_000_000, shares: 178_550_000,
    current_liabilities: 9_094_000_000, long_term_debt: 1_996_000_000,
    annual_eps: { 2023: -0.42, 2024: 4.21, 2025: 7.51 },
    owner_earnings: {
      fiscal_year: 2025,
      annual_per_share: {
        2025: {
          reported_earnings_assumption: 1_000_000_000,
          cash_flow_bridge: {
            operating_cash_flow: 11_470_000_000,
            free_cash_flow: 9_000_000_000,
            share_repurchases: [1_250_000_000, "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares",
              "IFRS-AR", "adidas-ar25-deadbeef", "2025-12-31", "EUR"],
          },
        },
      },
    },
    sources: { total_assets: {
      tag: "adidas-workbook:Total assets", form: "IFRS-AR",
      accn: "adidas-ar25-deadbeef", end: "2025-12-31",
      document: "cons-financial-statements-adidas-ar25.xlsx",
    } },
  };
  const markup = renderToStaticMarkup(React.createElement(Detail, { row, onClose() {} }));
  assert.match(markup, /€20\.26B/);
  assert.match(markup, /€11\.47B/);
  assert.match(markup, /Share repurchases \(buybacks\)/);
  assert.match(markup, /−€1\.25B/);
  assert.match(markup, /not deducted when calculating FCF/);
  assert.match(markup, /€7\.51/);
  assert.match(markup, />Calculate IV</);
  assert.match(markup, /Open IV with FY2025 FCF and current shares/);
  assert.match(markup, /cons-financial-statements-adidas-ar25\.xlsx/);
  assert.doesNotMatch(markup, /sec\.gov\/Archives\/edgar\/data\/NaN/);
});

test("the ratios history explains and displays lease-neutral RONTA", async (t) => {
  const previousWindow = globalThis.window;
  globalThis.window = { location: { href: "http://localhost/", search: "" } };
  t.after(() => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  });
  const vite = await createServer({ appType: "custom", server: { middlewareMode: true } });
  t.after(() => vite.close());
  const { default: Detail } = await vite.ssrLoadModule("/src/Detail.jsx");
  const row = {
    ticker: "ACN", name: "Accenture plc", cik: "0001467373",
    criteria: [1, 2, 3, 4, 5, 7].map((n) => ({ n, status: "INSUFFICIENT_DATA", value: null })),
    annual_ratios: {
      2025: { ronta: 86.94, lease_neutral_ronta: 125.20 },
    },
    operating_returns: { ronta: 86.94, lease_neutral_ronta: 125.20 },
  };
  const markup = renderToStaticMarkup(React.createElement(Detail, { row, onClose() {} }));
  assert.match(markup, />Lease-neutral RONTA</);
  assert.match(markup, /125\.2%/);
  assert.match(markup, /keeps both current and noncurrent operating-lease obligations with financing/);
  assert.match(markup, /does not estimate or capitalize leases from pre-ASC 842 commitments/);
});
