import { useEffect } from "react";
import { byN, pe3 } from "./screen.js";
import { profileMeta } from "./Alignment.jsx";
import AnnualFinancialHistory from "./AnnualFinancialHistory.jsx";

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
export default function Detail({ row, onClose }) {
  useEffect(() => {
    const esc = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const profile = profileMeta(row);
  const ca = row.current_assets;
  const cl = row.current_liabilities;
  const ltd = row.long_term_debt;
  const workingCapital = ca != null && cl != null ? ca - cl : null;
  const nca = workingCapital;
  const currentRatio = ca != null && cl > 0 ? ca / cl : null;
  const marketCap = row.price != null && row.shares != null ? row.price * row.shares : null;
  const priceToBook = row.price != null && row.bvps > 0 ? row.price / row.bvps : null;
  const pe3Value = pe3(row);
  const defensive = row.alignment?.defensive;
  const enterprising = row.alignment?.enterprising;
  const ch13 = row.ch13 ?? {};
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
          <span className={`profile-pill ${String(row.graham_profile ?? "REVIEW").toLowerCase()}`}>{profile.short}</span>
        </header>

        <section className="snapshot-section" aria-label="Market and financial snapshot">
          <h3>Market &amp; financial snapshot</h3>
          <div className="snapshot-grid">
            <Metric label="Price" value={moneyPrice(row.price)} />
            <Metric label="52-week high" sub="weekly close" value={moneyPrice(row.price_stats?.high_52w)} />
            <Metric label="Current vs 3Y avg" sub={row.price_stats?.average_3y == null ? undefined : `3Y avg ${moneyPrice(row.price_stats.average_3y)}`} value={signedPercent(row.price_stats?.pct_vs_3y_average)} />
            <Metric label="Market cap" value={money(marketCap)} />
            <Metric label="P/E" sub="latest 12 months" value={multiple(byN(row, 1).value)} />
            <Metric label="P/E" sub="3-year average EPS" value={multiple(pe3Value)} />
            <Metric label="P/TBV" value={multiple(byN(row, 7).value)} />
            <Metric label="P/B" value={multiple(priceToBook)} />
            <Metric label="Current ratio" value={multiple(currentRatio)} />
            <Metric label="Working capital" value={money(workingCapital)} />
            <Metric label="Net current assets" value={money(nca)} />
            <Metric label="Long-term debt" value={money(ltd)} />
            <Metric label="Tangible book / share" value={moneyPrice(row.tbvps)} />
            <Metric label="NCAV / share" value={moneyPrice(row.ncavps)} emphasis={row.ncavps != null && row.price != null && row.price <= row.ncavps} />
            <Metric label="Price / NCAV" sub="Graham buys under 0.67×"
                    value={multiple(priceToNcav(row))}
                    emphasis={priceToNcav(row) != null && priceToNcav(row) <= 2 / 3} />
          </div>
        </section>

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
               subtitle="Cash conversion, dilution and interest cover — context, never part of a grade"
               notes={row.context_notes} />
        <Notes title="What the trailing earnings are made of"
               subtitle="Non-recurring lines large enough to decide criterion 1 on their own"
               notes={row.earnings_quality} />
        <AnnualFinancialHistory annualEps={row.annual_eps} annualNetIncome={row.annual_net_income} />
        <SeriesMix mix={row.series_mix} />
        <Provenance row={row} />
      </aside>
    </>
  );
}

/** Graham's hardest bargain: the price against net current assets alone, with
 * every liability already subtracted and the fixed assets thrown in free. Only
 * meaningful while net current assets are positive — a negative denominator
 * turns "cheap" upside down. */
function priceToNcav(row) {
  if (row.price == null || row.ncavps == null || row.ncavps <= 0) return null;
  return row.price / row.ncavps;
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

function enterprisingValue(criterion) {
  if (criterion.n === 1 || criterion.n === 2 || criterion.n === 3 || criterion.n === 7) return multiple(criterion.value);
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
        {notes.map((note, i) => <li key={i}>{note}</li>)}
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
  const absolute = Math.abs(value);
  for (const [divisor, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (absolute >= divisor) return `$${(value / divisor).toFixed(value / divisor < 10 ? 1 : 0)}${suffix}`;
  return `$${number(value)}`;
}
function moneyPrice(value) {
  if (value == null) return "—";
  if (value < 1) return `$${Number(value).toFixed(3)}`;
  return `$${Number(value).toFixed(2)}`;
}
