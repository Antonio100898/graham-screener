import { useEffect } from "react";
import { awardOverhang, totalCapitalisation, workingCapitalToDebt } from "./capital.js";
import { byN, currentRatio as currentRatioOf, pe3, priceToBook as priceToBookOf,
  recurringDividendPresentation, reportedRate } from "./screen.js";
import { profileMeta } from "./Alignment.jsx";
import AnnualFinancialHistory from "./AnnualFinancialHistory.jsx";
import EpsCurve from "./EpsCurve.jsx";
import { ownerEarningsTrend, ownerMetricTrend } from "./ownerEarnings.js";
import { payloadWarnings } from "./warnings.js";
import { quoteStatus, quoteTitle } from "./quote.js";

const ENTERPRISING = {
  1: { label: "Earnings valuation", rule: "P/E < 10.0" },
  2: { label: "Liquidity", rule: "Current ratio ≥ 1.50" },
  3: { label: "Debt", rule: "Total debt ≤ 1.10 × NCA" },
  4: { label: "Earnings stability", rule: "No EPS deficit in 5 FY" },
  5: { label: "Dividend", rule: "Currently pays a dividend" },
  7: { label: "Tangible-asset valuation", rule: "Price < 1.20 × TBVPS" },
};

/** A compact investment snapshot: current market and financial facts first,
 * then the two Graham frameworks without trend charts or audit-trail clutter. */
export default function Detail({ row, onClose, tracked = false, onToggleTracked, onRecordTrade }) {
  useEffect(() => {
    const esc = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const profile = profileMeta(row);
  const ca = row.current_assets;
  const cl = row.current_liabilities;
  const ltd = row.long_term_debt;
  // criterion 3's "net current assets" and working capital are one quantity; the
  // panel used to show it twice, one row apart, under two names
  const workingCapital = ca != null && cl != null ? ca - cl : null;
  const currentRatio = currentRatioOf(row);
  const marketCap = row.price != null && row.shares != null ? row.price * row.shares : null;
  const priceToBook = priceToBookOf(row);
  const pe3Value = pe3(row);
  const defensive = row.alignment?.defensive;
  const enterprising = row.alignment?.enterprising;
  const ch13 = row.ch13 ?? {};
  // Graham's two profitability ratios, chapter 13: profit against sales, and
  // profit against the shareholders' own capital. Neither is a criterion.
  const prof = row.profitability ?? {};
  // Graham's chapter-18 comparisons carry two figures this panel did not: what the
  // whole enterprise costs (the common's market value plus the debt ahead of it),
  // and how far the working capital covers that debt — "no debt" being an answer
  // in its own right, as it is for National Presto.
  const capitalisation = totalCapitalisation(row);
  const awards = awardOverhang(row);
  const wcToDebt = workingCapitalToDebt(row);
  const dividend = row.dividend_record;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="detail clean-detail">
        <button className="close-btn" onClick={onClose} aria-label="Close company details">×</button>
        <header className="detail-head">
          <div>
            <h2>{row.ticker}</h2>
            <p className="sub">{row.name}</p>
          </div>
          <div className="detail-head-actions">
            {onRecordTrade && (
              <button className="trade-button" onClick={onRecordTrade}>Record trade</button>
            )}
            {onToggleTracked && (
              <button className={`track-btn ${tracked ? "on" : ""}`} onClick={onToggleTracked}
                      aria-pressed={tracked}
                      title={tracked ? "Remove from tracked" : "Track this company"}>
                {tracked ? "★ Tracked" : "☆ Track"}
              </button>
            )}
            <span className={`profile-pill ${String(row.graham_profile ?? "REVIEW").toLowerCase()}`}>{profile.short}</span>
          </div>
        </header>

        <DataWarnings row={row} />
        <AnalysisRoutes routes={row.analysis_routes} />

        <section className="snapshot-section" aria-label="Market and financial snapshot">
          <h3>Market &amp; financial snapshot</h3>
          <div className="snapshot-grid">
            <Metric label="Price" sub={quoteStatus(row)} value={moneyPrice(row.price)}
                    title={quoteTitle(row)} />
            <Metric label="TTM EPS" sub={row.ttm_basis ?? "trailing twelve months"}
                    value={moneyPrice(row.ttm_eps)} />
            <Metric label="52-week high" sub="weekly close" value={moneyPrice(row.price_stats?.high_52w)} />
            <Metric label="Current vs 3Y avg" sub={row.price_stats?.average_3y == null ? undefined : `3Y avg ${moneyPrice(row.price_stats.average_3y)}`} value={signedPercent(row.price_stats?.pct_vs_3y_average)} />
            <Metric label="Market cap" value={money(marketCap)} />
            <Metric label="Working capital" sub="= net current assets, criterion 3's base"
                    value={money(workingCapital)} />
            <Metric label="Total capitalisation" sub="market value of the common plus its debt"
                    value={money(capitalisation)} />
            <Metric label="Equity awards" sub={row.awards_basis ? `${row.awards_basis}, % of shares` : "options and restricted stock, % of shares"}
                    value={rateOrDash(awards)} />
            <Metric label="Long-term debt" value={money(ltd)} />
            <Metric label="Short-term debt" sub="due within a year" value={money(row.short_term_debt)} />
            <Metric label="Operating-lease liabilities" sub="outside Graham's debt test"
                    value={money(row.operating_lease_liability)} />
            <Metric label="Lease-adjusted debt" sub="reported debt plus operating leases"
                    value={money(row.lease_adjusted_debt)} />
            <Metric label="Fixed-charge coverage" sub="reported operating-income proxy"
                    value={multiple(row.fixed_charge_coverage)} />
            <Metric label="NCAV / share" value={moneyPrice(row.ncavps)} emphasis={row.ncavps != null && row.price != null && row.price <= row.ncavps} />
          </div>
        </section>

        <Ratios row={row} currentRatio={currentRatio} priceToBook={priceToBook}
                pe3Value={pe3Value} prof={prof} wcToDebt={wcToDebt} awards={awards} />

        <AssetProtection row={row} />

        <EpsCurve annualEps={row.annual_eps} ttmEps={row.ttm_eps} />

        <CriteriaSection
          title="Enterprising criteria"
          verdict={enterprising?.verdict}
          rows={row.criteria.map(enterprisingRow)}
          extra={enterprising?.growth_modern_4fy && <ModernGrowth growth={enterprising.growth_modern_4fy} />}
        />

        <CriteriaSection
          title="Defensive criteria"
          verdict={defensive?.verdict}
          rows={defensiveRows({ row, defensive, ch13, dividend, currentRatio, workingCapital, ltd, marketCap, pe3Value, priceToBook })}
        />

        <OwnerEarnings oe={row.owner_earnings} cik={row.cik} />
        <Notes title="What the multiples do not say"
               subtitle="Cash conversion, dilution, interest cover, leases, receivables and inventory against sales, untaxed profits, tax charged but not paid, valuation allowances, an eroding margin, a foreign listing whose ratio is only on the cover page, a book value made of acquisitions, the shape of the ten-year record, peer efficiency, warrants, debt discount, and the events the company's own filing index proves — context, never part of a grade"
               notes={row.context_notes} />
        <Notes title="What the trailing earnings are made of"
               subtitle="Non-recurring lines large enough to decide criterion 1 on their own"
               notes={row.earnings_quality} />
        <ProseGaps row={row} />
        <AnnualFinancialHistory annualEps={row.annual_eps} annualNetIncome={row.annual_net_income}
                                weightedShares={row.annual_weighted_shares} />
        <SeriesMix mix={row.series_mix} />
        <Provenance row={row} />
      </aside>
    </>
  );
}

function DataWarnings({ row }) {
  const warnings = payloadWarnings(row);
  if (!warnings.length) return null;
  return (
    <section className="data-warnings" aria-label="Data freshness warnings">
      {warnings.map((warning) => {
        const filingUrl = warning.accession && edgarUrl(row.cik, warning.accession);
        return (
          <p key={`${warning.kind}-${warning.accession ?? "history"}`}>
            <b>{warning.kind}</b>
            <span>{warning.text}</span>
            {filingUrl && (
              <a href={filingUrl} target="_blank" rel="noreferrer">
                Open filing{warning.filed ? ` filed ${warning.filed}` : ""}
              </a>
            )}
          </p>
        );
      })}
    </section>
  );
}

function AnalysisRoutes({ routes }) {
  if (!routes?.length) return null;
  return (
    <section className="criteria-section analysis-routes" aria-label="Business-model comparability">
      <div className="criteria-title"><div><h3>Business-model routing</h3>
        <p>These are comparability warnings, not grades. The screener does not invent
           sector measures that the filing does not report.</p></div></div>
      <div className="analysis-route-grid">
        {routes.map((route) => (
          <article key={route.id}>
            <b>{route.label}</b>
            <p><strong>Prefer:</strong> {route.preferred}.</p>
            <p><strong>De-emphasize:</strong> {route.deemphasize}.</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function AssetProtection({ row }) {
  const quality = row.asset_quality ?? {};
  const marketCap = row.price != null && row.shares != null ? row.price * row.shares : null;
  if ([row.bvps, row.tbvps, row.ncavps, quality.common_equity, quality.inventory,
    quality.receivables, quality.net_cash].every((value) => value == null)) return null;
  return (
    <section className="criteria-section" aria-label="Asset protection">
      <div className="criteria-title"><div><h3>Asset protection</h3>
        <p>Reported book and NCAV composition. No liquidation haircuts are assumed.</p></div></div>
      <div className="snapshot-grid">
        <Metric label="Book value / share" value={moneyPrice(row.bvps)} />
        <Metric label="Tangible book / share" value={moneyPrice(row.tbvps)} />
        <Metric label="NCAV / share" value={moneyPrice(row.ncavps)} />
        <Metric label="Common equity" value={money(quality.common_equity)} />
        <Metric label="Goodwill / common equity" value={rateOrDash(quality.goodwill_to_common_equity)} />
        <Metric label="Goodwill + intangibles / equity"
                value={rateOrDash(quality.goodwill_and_intangibles_to_common_equity)} />
        <Metric label="Inventory / positive NCAV" value={rateOrDash(quality.inventory_to_ncav)} />
        <Metric label="Receivables / positive NCAV" value={rateOrDash(quality.receivables_to_ncav)} />
        <Metric label="Net cash" sub="cash + short investments − reported debt"
                value={money(quality.net_cash)} />
        <Metric label="Market cap / positive net cash"
                sub={marketCap == null ? undefined : `market cap ${money(marketCap)}`}
                value={multiple(quality.market_cap_to_net_cash)} />
      </div>
    </section>
  );
}

/** Every ratio the panel shows, at today's price and at each of the last five
 * fiscal year ends. Chapter 13 compares companies by laying the same handful of
 * ratios side by side, and a single current column says how a business looks today
 * while saying nothing about how it got there. Each past column is struck on its own
 * year: that year's report, and the price as it stood then, over trailing earnings
 * computed from what had been filed by then — no column mixes eras. */
function Ratios({ row, currentRatio, priceToBook, pe3Value, prof, wcToDebt, awards }) {
  const history = row.annual_ratios ?? {};
  // newest first: the current column, then back through the record
  const years = Object.keys(history).map(Number).sort((a, b) => b - a).slice(0, 5);
  const lines = [
    { label: "P/E", sub: row.ttm_basis ?? "trailing", now: byN(row, 1).value, key: "pe", fmt: multiple },
    { label: "P/E", sub: "3-year average EPS", now: pe3Value, fmt: multiple },
    { label: "P/B", now: priceToBook, key: "pb", fmt: multiple },
    { label: "P/TBV", sub: "criterion 7 \u00b7 under 1.20\u00d7", now: byN(row, 7).value, key: "ptbv", fmt: multiple },
    { label: "P/NCAV", sub: "Graham buys under 0.67\u00d7", now: priceToNcav(row), key: "pncav", fmt: multiple },
    { label: "Current ratio", sub: "criterion 2 \u00b7 at least 1.50\u00d7", now: currentRatio, key: "current_ratio", fmt: multiple },
    { label: "Working capital / debt", sub: "Graham's chapter-18 comparison", now: wcToDebt,
      fmt: (v) => (typeof v === "string" ? v : multiple(v)) },
    { label: "Equity awards", sub: `${row.awards_basis ?? "options and restricted stock"} \u00b7 % of shares`,
      now: awards, key: "award_pct", fmt: rateOrDash },
    { label: "Net margin", sub: "profit per $ of sales", now: prof.net, key: "net_margin", fmt: rateOrDash },
    { label: "Operating margin", sub: "reported operating income / sales", now: prof.operating,
      key: "operating_margin", fmt: reportedRate,
      missing: "No same-period, filing-reported operating income and revenue pair is available; the screener does not invent an operating-profit subtotal from differently scoped lines." },
    { label: "Return on book value", sub: "earnings on common equity", now: prof.on_book, key: "return_on_book", fmt: rateOrDash },
  ];
  if (!years.length && lines.every((line) => line.now == null)) return null;
  return (
    <section className="annual-history ratios-section">
      <div className="criteria-title">
        <div>
          <h3>Ratios</h3>
        </div>
      </div>
      <div className="annual-history-scroll">
        <table className="annual-history-table ratios">
          <thead>
            <tr>
              <th>Ratio</th>
              <th className="num current">Current</th>
              {years.map((y) => (
                <th key={y} className="num" title={history[y]?.end ? `fiscal year ended ${history[y].end}` : undefined}>
                  FY{y}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.label + (line.sub ?? "")}>
                <td><b>{line.label}</b>{line.sub && <small>{line.sub}</small>}</td>
                <td className="num current" title={line.now == null ? line.missing : undefined}>
                  {line.fmt(line.now)}
                </td>
                {years.map((y) => (
                  <td key={y} className="num"
                    title={line.key && history[y]?.[line.key] == null ? line.missing : undefined}>
                    {line.key ? line.fmt(history[y]?.[line.key]) : <span className="dim">{"—"}</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}


/** Graham's hardest bargain: the price against net current assets alone, with
 * every liability already subtracted and the fixed assets thrown in free. Only
 * meaningful while net current assets are positive — a negative denominator
 * turns "cheap" upside down. */
function priceToNcav(row) {
  if (row.price == null || row.ncavps == null || row.ncavps <= 0) return null;
  const ratio = row.price / row.ncavps;
  // Graham buys under 0.67x. At 6,425,308x the figure has stopped being a
  // multiple of anything — the net current assets are a rounding error, which is
  // information the number itself no longer carries.
  return ratio > 1000 ? null : ratio;
}

function Metric({ label, sub, value, emphasis = false, title }) {
  return <div className="metric" title={title}><span>{label}{sub && <em>{sub}</em>}</span><b className={emphasis ? "ok" : ""}>{value}</b></div>;
}

function CriteriaSection({ title, verdict, rows, extra }) {
  return (
    <section className="criteria-section">
      <div className="criteria-title"><div><h3>{title}</h3></div><Status value={verdict} /></div>
      <table className="criteria-clean">
        <thead><tr><th>Test</th><th>Rule</th><th className="num">Current</th><th>Status</th></tr></thead>
        <tbody>{rows.map((item) => <CriteriaRow key={item.label} {...item} />)}</tbody>
      </table>
      {extra}
    </section>
  );
}

function CriteriaRow({ label, rule, value, status, note }) {
  return <tr className={String(status ?? "INSUFFICIENT_DATA").toLowerCase()} title={note ?? undefined}>
    <td><b>{label}</b>{note && <small>{note}</small>}</td>
    <td className="rule">{rule}</td>
    <td className="num">{value}</td>
    <td><Status value={status} /></td>
  </tr>;
}

function ModernGrowth({ growth }) {
  const value = growth.status === "INSUFFICIENT_DATA"
    ? "Insufficient annual EPS history"
    : `FY${growth.latest_fy} ${number(growth.latest_eps)} vs FY${growth.base_fy} ${number(growth.base_eps)}`;
  return <p className="criteria-note"><b>Modern four-fiscal-year EPS analogue:</b> {value} <Status value={growth.status} /></p>;
}

function defensiveRows({ row, defensive, ch13, dividend, currentRatio, workingCapital, ltd, marketCap, pe3Value, priceToBook }) {
  const test = (name) => defensive?.tests?.[name] ?? "INSUFFICIENT_DATA";
  const dividendEvidence = dividend?.latest != null && dividend?.streak_from != null
    ? `${dividend.latest - dividend.streak_from + 1} years (from ${dividend.streak_from})`
    : "No verified record";
  const sizeValue = row.graham_profile === "UTILITY" ? money(row.total_assets) : money(row.ttm_revenue);
  const financialValue = row.graham_profile === "UTILITY"
    ? `LT debt ${money(ltd)} · equity ${money(row.total_assets != null && row.total_liabilities != null ? row.total_assets - row.total_liabilities : null)}`
    : `CR ${multiple(currentRatio)} · WC ${money(workingCapital)} · LT debt ${money(ltd)}`;
  const valuationProduct = pe3Value != null && priceToBook != null ? pe3Value * priceToBook : null;
  return [
    { label: "Adequate size", rule: row.graham_profile === "UTILITY" ? "Assets ≥ $50M" : "Revenue ≥ $100M", value: sizeValue, status: test("size") },
    { label: "Financial position", rule: row.graham_profile === "UTILITY" ? "LT debt ≤ 2× equity" : "CR ≥ 2 and LT debt ≤ working capital", value: financialValue, status: test("financial_position") },
    { label: "Earnings stability", rule: "No deficit in 10 FY", value: `${ch13.ten_year_positive ?? "—"} of ${ch13.ten_year_present ?? "—"} positive years`, status: test("stability_10y"), note: defensive?.windowed?.stability_10y },
    { label: "Dividend record", rule: "20 uninterrupted years", value: dividendEvidence, status: test("dividend_20y"), note: defensive?.windowed?.dividend_20y },
    { label: "Earnings growth", rule: "≥ 33⅓% over 10 years", value: ch13.growth_10y == null ? "—" : `${signed(ch13.growth_10y)}%`, status: test("growth_10y"), note: defensive?.windowed?.growth_10y },
    { label: "Valuation", rule: "P/E3 ≤ 15 and P/E3 × P/B ≤ 22.5", value: `P/E3 ${multiple(pe3Value)} · product ${multiple(valuationProduct)}`, status: test("valuation") },
  ];
}

// Where two decimals would land exactly on the threshold while the criterion was
// decided on the unrounded figure, the reader sees "1.50× · FAIL" under "≥ 1.50".
// Those nine rows get a third decimal rather than a contradiction.
const THRESHOLDS = { 1: 10.0, 2: 1.5, 3: 1.1, 7: 1.2 };

function shown(criterion) {
  const v = criterion.value;
  if (v == null) return null;
  const limit = THRESHOLDS[criterion.n];
  const rounded = Math.round(v * 100) / 100;
  return limit != null && rounded === limit && v !== limit
    ? Number(v).toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 })
    : number(v);
}

function enterprisingValue(criterion) {
  if (criterion.n === 1 || criterion.n === 2 || criterion.n === 3 || criterion.n === 7) {
    const v = shown(criterion);
    return v == null ? "—" : `${v}×`;
  }
  if (criterion.n === 5) return recurringDividendPresentation(criterion.value, criterion.note).value;
  return criterion.value == null ? "—" : number(criterion.value);
}

function enterprisingRow(criterion) {
  const cash = criterion.n === 5
    ? recurringDividendPresentation(criterion.value, criterion.note)
    : null;
  return {
    label: ENTERPRISING[criterion.n]?.label ?? `Criterion ${criterion.n}`,
    rule: ENTERPRISING[criterion.n]?.rule ?? "—",
    value: cash?.value ?? enterprisingValue(criterion),
    status: criterion.status,
    note: cash?.note ?? criterion.note,
  };
}

/** Separately labelled evidence around Buffett owner earnings. Not a Graham criterion. */
function OwnerEarnings({ oe, cik }) {
  if (!oe) return null;
  const rate = (value) => (value == null ? "—" : `${number(value)}%`);
  const trend = ownerEarningsTrend(oe);
  const fcfAfterSbc = ownerMetricTrend(
    oe, "free_cash_flow_after_stock_compensation_per_share",
    "free_cash_flow_after_stock_compensation");
  const latest = trend?.rows.find((row) => row.fiscalYear === oe.fiscal_year);
  const beginning = oe.invested_capital_evidence?.beginning;
  const ending = oe.invested_capital_evidence?.ending;
  return (
    <section className="criteria-section">
      <div className="criteria-title">
        <div><h3>Owner earnings &amp; cash-generation evidence</h3>
          <p>No definitive owner-earnings number is claimed: maintenance capex and required
             incremental working capital are not separately reported in primary XBRL.</p></div>
        <b>Evidence lenses</b>
      </div>
      {trend && (
        <div className="snapshot-grid owner-earnings-summary">
          <Metric label={`FY${oe.fiscal_year} reported earnings / share`}
                  sub="maintenance capex assumed equal to D&A; equals earnings by construction"
                  value={moneyPrice(latest?.perShare)} />
          <Metric label="10-slot CAGR" sub={`${trend.firstFiscalYear}–${trend.latestFiscalYear}`}
                  value={rate(trend.cagr)} />
          <Metric label="5-slot CAGR" value={rate(trend.cagr5)} />
          <Metric label="3-slot CAGR" value={rate(trend.cagr3)} />
          <Metric label="Total earnings CAGR" value={rate(trend.totalCagr)} />
          <Metric label="Diluted-share CAGR" value={rate(trend.shareCountCagr)} />
          <Metric label="10-year median / share" value={moneyPrice(trend.median10)} />
          <Metric label="Latest vs 10-year median" value={signedPercent(trend.latestVsMedian10)} />
          <Metric label="Worst YoY decline" value={rate(trend.worstYoyDecline)} />
          <Metric label="Maximum peak-to-trough decline" value={rate(trend.maximumDrawdown)} />
          <Metric label="Variability" sub="coefficient of variation"
                  value={rate(trend.variability)} />
          <Metric label="History" value={`${trend.yearsPresent}/${trend.yearsExpected} years · ${trend.yearsProfitable} positive`} />
        </div>
      )}
      {trend?.buybackDriven && (
        <p className="criteria-note warning"><b>Buyback-driven growth:</b> per-share results
          improved while total reported earnings declined because diluted shares fell.</p>
      )}
      <table className="criteria-clean">
        <thead><tr><th>Measurement</th><th className="num">FY{oe.fiscal_year}</th></tr></thead>
        <tbody>
          {oe.components.map(([label, value]) => (
            <tr key={label}><td><b>{label}</b></td><td className="num">{money(value)}</td></tr>
          ))}
          <tr><td><b>Earnings after total capital expenditure</b>
            <small>Growth and maintenance capex deducted together; not a guaranteed floor.</small></td>
              <td className="num">{money(oe.all_capex_floor)}</td></tr>
          <tr><td><b>Reported earnings — maintenance capex assumed equal to D&amp;A</b>
            <small>The D&amp;A add-back and assumed maintenance deduction cancel by construction.</small></td>
              <td className="num">{money(oe.maintenance_estimate)}</td></tr>
          <tr><td><b>Standard free cash flow</b><small>Operating cash flow less cash capex.</small></td>
              <td className="num">{money(oe.free_cash_flow)}</td></tr>
          {oe.free_cash_flow_after_stock_compensation != null && <tr>
            <td><b>FCF after stock compensation</b><small>Conservative shareholder-cost diagnostic.</small></td>
            <td className="num">{money(oe.free_cash_flow_after_stock_compensation)}</td></tr>}
          {oe.free_cash_flow_after_acquisitions != null && <tr>
            <td><b>FCF after cash acquisitions</b></td>
            <td className="num">{money(oe.free_cash_flow_after_acquisitions)}</td></tr>}
          {oe.expanded_free_cash_flow != null && <tr>
            <td><b>FCF after capitalized software and acquired intangibles</b></td>
            <td className="num">{money(oe.expanded_free_cash_flow)}</td></tr>}
          {oe.operating_cash_flow_before_working_capital != null && <tr>
            <td><b>CFO before reported working-capital cash effect</b></td>
            <td className="num">{money(oe.operating_cash_flow_before_working_capital)}</td></tr>}
          {oe.average_working_capital_cash_effect_3y != null && <tr>
            <td><b>Three-year average working-capital cash effect</b></td>
            <td className="num">{money(oe.average_working_capital_cash_effect_3y)}</td></tr>}
          {oe.stock_compensation_to_revenue != null && <tr>
            <td><b>Stock compensation / revenue</b></td>
            <td className="num">{rate(oe.stock_compensation_to_revenue)}</td></tr>}
          {oe.stock_compensation_to_free_cash_flow != null && <tr>
            <td><b>Stock compensation / standard FCF</b></td>
            <td className="num">{rate(oe.stock_compensation_to_free_cash_flow)}</td></tr>}
          {oe.acquisitions_to_free_cash_flow != null && <tr>
            <td><b>Cash acquisitions / standard FCF</b></td>
            <td className="num">{rate(oe.acquisitions_to_free_cash_flow)}</td></tr>}
          {oe.acquisition_years_10 != null && <tr>
            <td><b>Fiscal years with reported cash acquisitions</b><small>Latest ten fiscal-year slots; missing facts are not zero.</small></td>
            <td className="num">{number(oe.acquisition_years_10)}</td></tr>}
          <tr><td><b>Average invested capital</b>
            <small>All cash and short-term investments excluded; exact beginning and ending balance sheets required.</small></td>
              <td className="num">{money(oe.invested_capital)}</td></tr>
          {(beginning || ending) && <tr><td><b>Capital endpoints</b></td>
            <td className="num">{money(beginning?.value)} ({beginning?.end ?? "—"}) → {money(ending?.value)} ({ending?.end ?? "—"})</td></tr>}
          <tr><td><b>Average capital including cash</b></td>
              <td className="num">{money(oe.capital_including_cash)}</td></tr>
          <tr><td><b>All-capex cash return / average invested capital</b></td>
              <td className="num">{rate(oe.all_capex_return)}</td></tr>
          <tr><td><b>Earnings-based return / average invested capital</b></td>
              <td className="num">{rate(oe.maintenance_estimate_return)}</td></tr>
          <tr><td><b>All-capex cash return / capital including cash</b></td>
              <td className="num">{rate(oe.all_capex_return_including_cash)}</td></tr>
          {oe.nopat_roic != null && <tr><td><b>NOPAT ROIC</b>
            <small>Operating income after the median usable three-year tax rate, over average invested capital.</small></td>
              <td className="num">{rate(oe.nopat_roic)}</td></tr>}
          {oe.nopat_return_including_cash != null && <tr><td><b>NOPAT return including cash</b></td>
              <td className="num">{rate(oe.nopat_return_including_cash)}</td></tr>}
        </tbody>
      </table>
      {trend && (
        <div className="annual-history-scroll owner-earnings-history">
          <table className="annual-history-table">
            <thead><tr><th>Fiscal year</th><th className="num">Reported earnings / share</th>
              <th className="num">Reported earnings total</th><th className="num">YoY / share</th>
              <th className="num">After total capex / share</th><th className="num">After total capex total</th>
              <th className="num">Standard FCF / share</th><th className="num">Standard FCF total</th>
              <th className="num">FCF after SBC / share</th><th className="num">FCF after acquisitions / share</th>
              <th className="num">Expanded FCF / share</th><th className="num">Diluted shares</th></tr></thead>
            <tbody>
              {trend.rows.map(({ fiscalYear, cell, perShare, total, yoy }) => (
                <tr key={fiscalYear} className={perShare != null && perShare < 0 ? "loss" : ""}>
                  <td><b>FY{fiscalYear}</b>{fiscalYear === oe.fiscal_year && <small>latest completed</small>}</td>
                  <td className="num">{moneyPrice(perShare)}</td>
                  <td className="num">{money(total)}</td>
                  <td className="num">{signedPercent(yoy)}</td>
                  <td className="num">{moneyPrice(cell?.earnings_after_total_capex_per_share ?? cell?.all_capex_floor_per_share)}</td>
                  <td className="num">{money(cell?.earnings_after_total_capex ?? cell?.all_capex_floor)}</td>
                  <td className="num">{moneyPrice(cell?.free_cash_flow_per_share)}</td>
                  <td className="num">{money(cell?.free_cash_flow)}</td>
                  <td className="num">{moneyPrice(cell?.free_cash_flow_after_stock_compensation_per_share)}</td>
                  <td className="num">{moneyPrice(cell?.free_cash_flow_after_acquisitions_per_share)}</td>
                  <td className="num">{moneyPrice(cell?.expanded_free_cash_flow_per_share)}</td>
                  <td className="num">{shareCount(cell?.diluted_shares)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {fcfAfterSbc?.yearsPresent > 1 && <p className="criteria-note">
        <b>FCF after stock compensation record:</b> {fcfAfterSbc.yearsPresent}/10 years,
        5-slot CAGR {rate(fcfAfterSbc.cagr5)}, maximum drawdown {rate(fcfAfterSbc.maximumDrawdown)}.
      </p>}
      {!!Object.keys(oe.sources ?? {}).length && (
        <div className="owner-source-list">
          <b>Latest-year filing inputs</b>
          {Object.entries(oe.sources).map(([name, source]) => (
            <span key={name}><code>{name.replaceAll("_", " ")}: {source.tag}</code>
              <SourceCell cik={cik} source={source} /></span>
          ))}
        </div>
      )}
      {!!oe.caveats?.length && <ul className="disclosure-notes compact">
        {oe.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
      </ul>}
    </section>
  );
}

/** Disclosure paragraphs: read alongside the grades, never folded into them. */
function Notes({ title, subtitle, notes }) {
  if (!notes || notes.length === 0) return null;
  return (
    <section className="criteria-section notes-section">
      <div className="criteria-title"><div><h3>{title}</h3><p>{subtitle}</p></div></div>
      <ul className="disclosure-notes">
        {notes.map((note, i) => (
          <li key={i}>
            {note.kind && <b className="note-kind">{note.kind}</b>}
            {note.text ?? note}
          </li>
        ))}
      </ul>
    </section>
  );
}

const SOURCE_LABELS = {
  total_assets: "Total assets", total_liabilities: "Total liabilities",
  current_assets: "Current assets", current_liabilities: "Current liabilities",
  long_term_debt: "Long-term debt", short_term_debt: "Short-term debt",
  total_debt: "Total debt (rollup)", goodwill: "Goodwill", intangibles: "Intangibles",
  operating_lease_liability: "Operating-lease liabilities", lease_cost: "Lease cost",
  fixed_charge_coverage: "Fixed-charge coverage proxy",
  inventory: "Inventory", receivables: "Receivables", cash: "Cash",
  short_term_investments: "Short-term investments",
  preferred_stock: "Preferred stock", temporary_equity: "Temporary equity",
  noncontrolling_interest: "Noncontrolling interest", shares: "Shares outstanding",
  dividend: "Dividend paid (tagged period)",
  recurring_dividend_per_share: "Recurring dividend / share (annualized)",
};

/** The filing's index page, which names its primary document — not the bare
 * archive folder, which leaves the reader to guess which file is the filing. */
function edgarUrl(cik, accn) {
  if (!cik || !accn) return null;
  return `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accn.replaceAll("-", "")}/${accn}-index.htm`;
}

function SourceCell({ cik, source }) {
  const url = edgarUrl(cik, source.accn);
  const label = `${source.form} · ${source.end ?? "—"}`;
  return (
    <>
      {url ? <a href={url} target="_blank" rel="noreferrer" title={`Open filing ${source.accn}`}>{label}</a>
           : label}
      <small className="accn">{source.accn}</small>
    </>
  );
}

/** Every figure names its tag, filing and date — the audit trail behind the screen. */
function Provenance({ row }) {
  const sources = row.sources;
  if (!sources || Object.keys(sources).length === 0) return null;
  return (
    <section className="criteria-section provenance-section">
      <div className="criteria-title"><div><h3>Data provenance</h3>
        <p>Which XBRL tag, in which SEC filing, dated when. Filing links open EDGAR.</p></div></div>
      <div className="provenance-scroll">
        <table className="criteria-clean">
          <thead><tr><th>Figure</th><th>Value</th><th>Tag</th><th>Filing</th></tr></thead>
          <tbody>
            {Object.entries(SOURCE_LABELS).filter(([key]) => sources[key]).flatMap(([key, label]) => {
              const s = sources[key];
              const stored = row[key] ?? row.asset_quality?.[key];
              const raw = key === "dividend" && stored == null ? undefined : stored;
              const value = key === "shares" ? number(raw)
                : key === "fixed_charge_coverage" ? multiple(raw) : money(raw);
              const out = [(
                <tr key={key}>
                  <td><b>{label}</b></td>
                  <td className="num">{value}</td>
                  <td className="rule"><code>{s.tag}</code></td>
                  <td><SourceCell cik={row.cik} source={s} /></td>
                </tr>
              )];
              // a summed figure's own filing is whichever component was newest,
              // so each component states its own rather than borrowing that one
              (s.components ?? []).forEach((part, i) => out.push(
                <tr key={`${key}-${i}`} className="component-row">
                  <td><span className="component-mark">↳ component</span></td>
                  <td className="num"></td>
                  <td className="rule"><code>{part.tag}</code></td>
                  <td><SourceCell cik={row.cik} source={part} /></td>
                </tr>
              ));
              return out;
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** A series stitched from more than one tag can change scope mid-history. */
/** The questions this company's filings answer and its XBRL does not. Every other
 * figure on the page carries a tag and an accession; these carry a document to read. */
function ProseGaps({ row }) {
  const gaps = row.prose_gaps ?? [];
  if (!gaps.length) return null;
  return (
    <section className="criteria-section prose-gaps">
      <div className="criteria-title">
        <div>
          <h3>Check the filing</h3>
          <p>Answers that exist only as prose in a document — not tagged, so not extractable.
             Nothing here has been guessed at.</p>
        </div>
      </div>
      <ul className="disclosure-notes">
        {gaps.map((gap, i) => (
          <li key={i}>
            <b className="note-kind">Unverified</b>
            {gap.what}. <em>Affects:</em> {gap.affects}. <em>Where:</em> {gap.where}
            {gap.accn && <> — <a href={edgarUrl(row.cik, gap.accn)} target="_blank" rel="noreferrer">open the filing</a></>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SeriesMix({ mix }) {
  if (!mix) return null;
  const NAMES = { eps: "EPS", net_income: "Net income", revenue: "Revenue" };
  return (
    <div className="series-mix">
      {Object.entries(mix).map(([series, tags]) => (
        <p key={series} className="criteria-note">
          <b>{NAMES[series] ?? series} series is stitched from {Object.keys(tags).length} tags:</b>{" "}
          {Object.entries(tags).map(([tag, years]) =>
            `${tag.replace("us-gaap:", "")} (${years[0]}–${years[years.length - 1]})`).join(" · ")}
          {" — "}scope can differ between tags; judge year-over-year steps that cross a boundary accordingly.
        </p>
      ))}
    </div>
  );
}

function Status({ value }) {
  const label = {
    PASS: "Pass", ALIGNED: "Aligned", FAIL: "Fail", BLOCKED: "Blocked",
    INSUFFICIENT_DATA: "Incomplete", EVIDENCE_INCOMPLETE: "Incomplete",
    NOT_APPLICABLE: "N/A", OUT_OF_SCOPE: "Out of scope",
  }[value] ?? "Incomplete";
  return <span className={`criterion-status ${String(value ?? "INSUFFICIENT_DATA").toLowerCase()}`}>{label}</span>;
}

function number(value) {
  return value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function multiple(value) { return value == null ? "—" : `${number(value)}×`; }
function signedPercent(value) { return value == null ? "—" : `${value >= 0 ? "+" : ""}${number(value)}%`; }
function signed(value) { return value >= 0 ? `+${number(value)}` : number(value); }
function money(value) {
  if (value == null) return "—";
  // the minus sign belongs in front of the amount, not between the currency and
  // the digits: Walmart's working capital rendered as "$-26.2B"
  const sign = value < 0 ? "−" : "";
  const absolute = Math.abs(value);
  for (const [divisor, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (absolute >= divisor)
      return `${sign}$${(absolute / divisor).toFixed(absolute / divisor < 10 ? 1 : 0)}${suffix}`;
  return `${sign}$${number(absolute)}`;
}
function rateOrDash(value) {
  return value == null ? "—" : `${Number(value).toFixed(1)}%`;
}
function moneyPrice(value) {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "";
  const absolute = Math.abs(value);
  if (absolute < 1) return `${sign}$${absolute.toFixed(3)}`;
  return `${sign}$${absolute.toFixed(2)}`;
}
function shareCount(value) {
  if (!(value > 0)) return "—";
  for (const [divisor, suffix] of [[1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (value >= divisor) return `${number(value / divisor)}${suffix}`;
  return number(value);
}
