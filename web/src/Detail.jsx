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

        <AnnualFinancialHistory annualEps={row.annual_eps} annualNetIncome={row.annual_net_income} />
      </aside>
    </>
  );
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
    { label: "Earnings stability", rule: "No deficit in 10 FY", value: `${ch13.ten_year_positive ?? "—"} of ${ch13.ten_year_present ?? "—"} positive years`, status: test("stability_10y") },
    { label: "Dividend record", rule: "20 uninterrupted years", value: dividendEvidence, status: test("dividend_20y") },
    { label: "Earnings growth", rule: "≥ 33⅓% over 10 years", value: ch13.growth_10y == null ? "—" : `${signed(ch13.growth_10y)}%`, status: test("growth_10y") },
    { label: "Valuation", rule: "P/E3 ≤ 15 and P/E3 × P/B ≤ 22.5", value: `P/E3 ${multiple(pe3Value)} · product ${multiple(valuationProduct)}`, status: test("valuation") },
  ];
}

function enterprisingValue(criterion) {
  if (criterion.n === 1 || criterion.n === 2 || criterion.n === 3 || criterion.n === 7) return multiple(criterion.value);
  if (criterion.n === 5) return criterion.value == null ? "—" : `${number(criterion.value)}% yield`;
  return criterion.value == null ? "—" : number(criterion.value);
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
