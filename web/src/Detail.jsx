import { useEffect } from "react";
import { awardOverhang, totalCapitalisation, workingCapitalToDebt } from "./capital.js";
import { byN, pe3 } from "./screen.js";
import { profileMeta } from "./Alignment.jsx";
import AnnualFinancialHistory from "./AnnualFinancialHistory.jsx";
import EpsCurve from "./EpsCurve.jsx";

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
export default function Detail({ row, onClose, tracked = false, onToggleTracked }) {
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
  const currentRatio = ca != null && cl > 0 ? ca / cl : null;
  const marketCap = row.price != null && row.shares != null ? row.price * row.shares : null;
  const priceToBook = row.price != null && row.bvps > 0 ? row.price / row.bvps : null;
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

        <section className="snapshot-section" aria-label="Market and financial snapshot">
          <h3>Market &amp; financial snapshot</h3>
          <div className="snapshot-grid">
            <Metric label="Price" value={moneyPrice(row.price)} />
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
            <Metric label="NCAV / share" value={moneyPrice(row.ncavps)} emphasis={row.ncavps != null && row.price != null && row.price <= row.ncavps} />
          </div>
        </section>

        <Ratios row={row} currentRatio={currentRatio} priceToBook={priceToBook}
                pe3Value={pe3Value} prof={prof} wcToDebt={wcToDebt} awards={awards} />

        <EpsCurve annualEps={row.annual_eps} ttmEps={row.ttm_eps} />

        <CriteriaSection
          title="Enterprising criteria"
          subtitle="Chapter 15 industrial low-multiplier method"
          verdict={enterprising?.verdict}
          rows={row.criteria.map((criterion) => ({
            label: ENTERPRISING[criterion.n]?.label ?? `Criterion ${criterion.n}`,
            rule: ENTERPRISING[criterion.n]?.rule ?? "—",
            value: enterprisingValue(criterion),
            status: criterion.status,
            note: criterion.note,
          }))}
          extra={enterprising?.growth_modern_4fy && <ModernGrowth growth={enterprising.growth_modern_4fy} />}
        />

        <CriteriaSection
          title="Defensive criteria"
          subtitle="Chapter 14 evidence; dividend continuity remains incomplete unless the record itself proves 20 years"
          verdict={defensive?.verdict}
          rows={defensiveRows({ row, defensive, ch13, dividend, currentRatio, workingCapital, ltd, marketCap, pe3Value, priceToBook })}
        />

        <OwnerEarnings oe={row.owner_earnings} />
        <Notes title="What the multiples do not say"
               subtitle="Cash conversion, dilution, interest cover, leases, receivables and inventory against sales, untaxed profits, tax charged but not paid, valuation allowances, an eroding margin, a foreign listing whose ratio is only on the cover page, a book value made of acquisitions, the shape of the ten-year record, peer efficiency, warrants, debt discount, and the events the company's own filing index proves — context, never part of a grade"
               notes={row.context_notes} />
        <Notes title="What the trailing earnings are made of"
               subtitle="Non-recurring lines large enough to decide criterion 1 on their own"
               notes={row.earnings_quality} />
        <ProseGaps row={row} />
        <AnnualFinancialHistory annualEps={row.annual_eps} annualNetIncome={row.annual_net_income}
                                preferred={row.annual_preferred_dividends} />
        <SeriesMix mix={row.series_mix} />
        <Provenance row={row} />
      </aside>
    </>
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
    { label: "Operating margin", now: prof.operating, key: "operating_margin", fmt: rateOrDash },
    { label: "Return on book value", sub: "earnings on common equity", now: prof.on_book, key: "return_on_book", fmt: rateOrDash },
  ];
  if (!years.length && lines.every((line) => line.now == null)) return null;
  return (
    <section className="annual-history ratios-section">
      <div className="criteria-title">
        <div>
          <h3>Ratios</h3>
          <p>Today, and at each of the last five fiscal year ends &mdash; the company&rsquo;s own,
             which for a June or September filer is not December. Every past column is struck on
             that year&rsquo;s own report and the price on the day it closed, so none of them mixes
             a past balance sheet with a later market.</p>
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
                <td className="num current">{line.fmt(line.now)}</td>
                {years.map((y) => (
                  <td key={y} className="num">
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

function Metric({ label, sub, value, emphasis = false }) {
  return <div className="metric"><span>{label}{sub && <em>{sub}</em>}</span><b className={emphasis ? "ok" : ""}>{value}</b></div>;
}

function CriteriaSection({ title, subtitle, verdict, rows, extra }) {
  return (
    <section className="criteria-section">
      <div className="criteria-title"><div><h3>{title}</h3><p>{subtitle}</p></div><Status value={verdict} /></div>
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
  if (criterion.n === 5) return criterion.value == null ? "—" : `${number(criterion.value)}% yield`;
  return criterion.value == null ? "—" : number(criterion.value);
}

/** Owner earnings over invested capital — the Davis Funds measure Zweig sets
 * against earnings per share. Not a Graham criterion: it ranks what already
 * passed, so it sits beside the verdict rather than inside it. */
function OwnerEarnings({ oe }) {
  if (!oe) return null;
  const rate = (value) => (value == null ? "—" : `${number(value)}%`);
  return (
    <section className="criteria-section">
      <div className="criteria-title">
        <div><h3>Return on invested capital</h3>
          <p>FY{oe.fiscal_year} owner earnings ÷ invested capital — 10% attractive, 6% acceptable behind a strong brand</p></div>
        <b className={oe.roic >= 10 ? "ok" : ""}>{rate(oe.roic)}</b>
      </div>
      <table className="criteria-clean">
        <thead><tr><th>Component</th><th className="num">FY{oe.fiscal_year}</th></tr></thead>
        <tbody>
          {oe.components.map(([label, value]) => (
            <tr key={label}><td><b>{label}</b></td><td className="num">{money(value)}</td></tr>
          ))}
          <tr><td><b>Owner earnings</b></td><td className="num">{money(oe.owner_earnings)}</td></tr>
          <tr><td><b>Invested capital</b><small>assets less cash, short-term investments and non-interest-bearing current liabilities</small></td>
              <td className="num">{money(oe.invested_capital)}</td></tr>
          <tr><td><b>Return on invested capital</b></td><td className="num">{rate(oe.roic)}</td></tr>
          <tr><td><b>…with maintenance capex assumed equal to depreciation</b></td>
              <td className="num">{rate(oe.roic_maintenance)}</td></tr>
        </tbody>
      </table>
      {oe.caveats?.length > 0 && (
        <ul className="disclosure-notes">{oe.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
      )}
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
  preferred_stock: "Preferred stock", temporary_equity: "Temporary equity",
  noncontrolling_interest: "Noncontrolling interest", shares: "Shares outstanding",
  dividend: "Dividend paid (tagged period)",
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
              const raw = key === "dividend" && row[key] == null ? undefined : row[key];
              const value = key === "shares" ? number(raw) : money(raw);
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
