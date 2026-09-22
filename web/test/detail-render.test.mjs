import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("the company detail panel enables zero assumptions by default", async (t) => {
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
    price: 10,
    shares: 100,
    bvps: 8,
    tbvps: 7,
    ncavps: 6,
    asset_quality: { common_equity: 800, net_cash: 200 },
    profitability: { on_book: 12, on_equity: 11 },
    operating_returns: { normalized_tax_rate: 20, nopat: 75, nopat_roic: 15 },
    criteria,
    annual_ratios: { 2025: {} },
    assumption_mode: { status: "APPLIED", applied: [] },
    latest_quarterly_filing: {
      form: "10-Q", filed: "2026-08-01", period: "2026-06-30",
      document: "test-10q.htm",
      url: "https://www.sec.gov/Archives/edgar/data/1/000000000126000003/0000000001-26-000003-index.htm",
    },
    owner_earnings: {
      fiscal_year: 2025,
      annual_per_share: {
        2025: { reported_earnings_assumption_per_share: 3 },
      },
    },
  };

  const markup = renderToStaticMarkup(
    React.createElement(Detail, { row, tracked: true, onClose() {} }),
  );

  assert.match(markup, /class="detail clean-detail"/);
  assert.match(markup, />Ratios</);
  assert.match(markup, />TEST</);
  assert.match(markup, />Latest quarterly filing</);
  assert.match(markup, /10-Q/);
  assert.match(markup, /Read the SEC filing/);
  assert.match(markup, /Checking the current annual report/);
  assert.match(markup, />Use strict filing values</);
  assert.doesNotMatch(markup, />Apply zero assumptions</);
  assert.doesNotMatch(markup, /Return on net tangible assets/);
  assert.doesNotMatch(markup, />Asset protection</);
  assert.doesNotMatch(markup, />P\/NCAV</);
  assert.doesNotMatch(markup, />Return on book value</);
  assert.doesNotMatch(markup, /<b>NOPAT<\/b>/);
  assert.doesNotMatch(markup, />Normalized tax rate</);
  assert.doesNotMatch(markup, />Worst YoY decline</);
  assert.doesNotMatch(markup, />Maximum peak-to-trough decline</);
  assert.doesNotMatch(markup, />Variability</);
  assert.match(markup, /FY2015–FY2017 average → FY2025/);
  assert.match(markup, /FY2020–FY2022 average → FY2025/);
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

test("the ratios panel labels conservative lower bounds separately from exact returns", async (t) => {
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
    ticker: "LOW", name: "Lower bound fixture", cik: "0000000001",
    criteria: [1, 2, 3, 4, 5, 7].map((n) => ({
      n, status: "INSUFFICIENT_DATA", value: null,
    })),
    annual_ratios: { 2025: {} },
    operating_returns: { nopat: 75, nopat_roic: null, ronta: null },
    operating_returns_estimate: {
      status: "CONSERVATIVE_LOWER_BOUND",
      nopat_roic: 20,
      ronta: 30,
      operating_return_assumptions: ["intangibles", "noncurrent_investments"],
      note: "Discovery-only lower bound.",
    },
  };

  const markup = renderToStaticMarkup(React.createElement(Detail, { row, onClose() {} }));
  assert.match(markup, /≥ 20\.0%/);
  assert.match(markup, /≥ 30\.0%/);
  assert.match(markup, /Conservative discovery estimate/);
  assert.match(markup, /intangibles, noncurrent_investments/);
  assert.match(markup, /exact reported ratios and Graham verdicts are unchanged/);
});
