import { useEffect, useState } from "react";
import { CRITERIA, closeness } from "./screen.js";
import { below, spell } from "./format.js";

/** Drill-down: criteria, EPS history, caveats, then the audit trail from /fundamentals. */
export default function Detail({ row, onClose }) {
  const [fundamentals, setFundamentals] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setFundamentals(null);
    setErr(null);
    fetch(`/fundamentals/${row.ticker}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setFundamentals)
      .catch((e) => setErr(e.message));
  }, [row.ticker]);

  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  // EPS and its numerator side by side: a rising EPS on falling earnings is a
  // share-count effect, and that is only visible when both are shown per year
  // when nothing newer than the 10-K has been filed, the trailing window simply is
  // that fiscal year — worth saying, or the repeated column looks like a mistake
  const eps = row.annual_eps ?? {};
  const ni = row.annual_net_income ?? {};
  const years = [...new Set([...Object.keys(eps), ...Object.keys(ni)])]
    .map(Number).sort((a, b) => a - b).slice(-8);
  const lastYear = years[years.length - 1];
  const sameAsLastYear =
    row.ttm_eps != null && eps[String(lastYear)] != null &&
    Math.abs(row.ttm_eps - eps[String(lastYear)]) < 1e-9;
  const g = closeness(row);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="detail">
        <button className="close-btn" onClick={onClose}>×</button>
        <h2>
          {row.ticker} <span className={`chip sm ${g.label.toLowerCase()}`}>{g.label}{g.unknown > 0 && <sup className="unk">?</sup>}</span>
        </h2>
        <p className="sub">{row.name}</p>
        <p className="note">{g.note}.</p>

        <div className="kv">
          <div><span>Price</span><b>{row.price ? `$${row.price.toFixed(2)}` : "—"}</b></div>
          <div><span>TTM EPS</span><b>{row.ttm_eps ?? "—"}</b></div>
          <div>
            <span>TTM net income</span>
            <b>{row.ttm_net_income == null ? "—" : money(row.ttm_net_income)}</b>
          </div>
          <div><span>Tangible book / share</span><b>{row.tbvps ? `$${row.tbvps.toFixed(2)}` : "—"}</b></div>
          <div title="Current assets less every liability, per share — Graham's most conservative yardstick. Buying below it means paying nothing for the fixed assets or the business.">
            <span>Net current asset value / share</span>
            <b className={row.ncavps && row.price && row.price < row.ncavps ? "ok" : ""}>
              {row.ncavps == null ? "—" : `$${row.ncavps.toFixed(2)}`}
            </b>
          </div>
          <div><span>Balance sheet</span><b>{row.balance_sheet_date ?? "—"}</b></div>
        </div>

        {row.price_stats && <PriceHistory p={row.price_stats} />}

        <h3>Criteria</h3>
        <table className="crittable">
          <tbody>
            {row.criteria.map((c) => (
              <tr key={c.n} className={c.status.toLowerCase()}>
                <td className="n">{c.n}</td>
                <td>{CRITERIA[c.n]}</td>
                <td className="num">{c.value == null ? "—" : c.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (c.n === 5 ? "%" : "")}</td>
                <td className="st">{c.status.replace("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {row.criteria.some((c) => c.note) && (
          <ul className="notes">
            {row.criteria.filter((c) => c.note).map((c) => (
              <li key={c.n}><b>{c.n}:</b> {c.note}</li>
            ))}
          </ul>
        )}

        {row.earnings_quality?.length > 0 && (
          <>
            <h3>What the trailing earnings are made of</h3>
            <ul className="caveats">
              {row.earnings_quality.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </>
        )}

        <h3>Reported annual results</h3>
        <div className="annual-wrap">
        <table className="annual">
          <thead>
            <tr>
              <th>Fiscal year</th>
              {years.map((y) => <th key={y} className="num">{y}</th>)}
              <th className="num ttmcol" title={sameAsLastYear
                ? "No quarter has been filed since the year end, so the trailing twelve months is that fiscal year"
                : "Trailing twelve months: last full year + this year to date − the same span a year earlier"}>
                TTM{sameAsLastYear ? "*" : ""}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Diluted EPS</td>
              {years.map((y) => {
                const v = eps[String(y)];
                return (
                  <td key={y} className={`num ${v < 0 ? "neg" : ""}`}>
                    {v == null ? "—" : v.toFixed(2)}
                  </td>
                );
              })}
              <td className="num ttmcol">{row.ttm_eps?.toFixed(2) ?? "—"}</td>
            </tr>
            <tr>
              <td>Net income</td>
              {years.map((y) => {
                const v = ni[String(y)];
                return (
                  <td key={y} className={`num ${v < 0 ? "neg" : ""}`}>
                    {v == null ? "—" : money(v)}
                  </td>
                );
              })}
              <td className="num ttmcol">
                {row.ttm_net_income == null ? "—" : money(row.ttm_net_income)}
              </td>
            </tr>
            <tr className="implied">
              <td>Implied shares</td>
              {years.map((y) => {
                const e = eps[String(y)], n = ni[String(y)];
                // A negative quotient is not a share count: it means EPS and net
                // income disagree in sign, so the two are on different bases.
                const sh = e && n && e !== 0 ? n / e : null;
                return (
                  <td key={y} className="num dim"
                      title={sh != null && sh <= 0
                        ? "EPS and net income disagree in sign for this year, so no share count follows from them"
                        : undefined}>
                    {sh != null && sh > 0 ? `${(sh / 1e6).toFixed(0)}M` : "—"}
                  </td>
                );
              })}
              <td className="num dim ttmcol">
                {row.ttm_eps && row.ttm_net_income && row.ttm_net_income / row.ttm_eps > 0
                  ? `${(row.ttm_net_income / row.ttm_eps / 1e6).toFixed(0)}M`
                  : "—"}
              </td>
            </tr>
          </tbody>
        </table>
        </div>
        {sameAsLastYear && (
          <p className="dim tiny">
            * No quarter has been filed since FY{lastYear} closed, so the trailing twelve
            months is that fiscal year.
          </p>
        )}
        <p className="dim tiny">
          Shares are implied by dividing net income by EPS — a falling count with flat
          earnings is what makes EPS grow on buybacks alone.
        </p>

        {row.eps_growth && <EpsGrowth g={row.eps_growth} />}

        <h3>Figures as filed</h3>
        {err && <p className="err">Could not load fundamentals — {err}</p>}
        {!fundamentals && !err && <p className="dim">Loading audit trail…</p>}
        {fundamentals && (
          <table className="prov">
            <thead>
              <tr><th>Figure</th><th className="num">Value</th><th>Source</th></tr>
            </thead>
            <tbody>
              {PROV.map(([label, key]) => {
                const f = fundamentals[key];
                return (
                  <tr key={key}>
                    <td>{label}</td>
                    <td className="num">{f ? money(f.value) : <span className="dim">not reported</span>}</td>
                    <td className="src">
                      {f ? (
                        <a
                          href={`https://www.sec.gov/Archives/edgar/data/${Number(fundamentals.cik)}/${f.accession.replace(/-/g, "")}/`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {f.form} {f.period_end}
                        </a>
                      ) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {row.owner_earnings && <OwnerEarnings oe={row.owner_earnings} />}
      </aside>
    </>
  );
}

const PROV = [
  ["Current assets", "current_assets"],
  ["Current liabilities", "current_liabilities"],
  ["Long-term debt", "long_term_debt"],
  ["Short-term debt", "short_term_debt"],
  ["Total assets", "total_assets"],
  ["Total liabilities", "total_liabilities"],
  ["Goodwill", "goodwill"],
  ["Intangibles", "intangibles"],
  ["Preferred stock", "preferred_stock"],
  ["Noncontrolling interest", "noncontrolling_interest"],
  ["Shares outstanding", "shares_outstanding"],
  ["Dividend paid", "dividend"],
];

/**
 * Where the price sits inside its own history. None of this is a criterion — Graham
 * has no rule about drawdowns — but the same multiples reached after a two-year
 * decline are a different proposition from the same multiples at the top of a range.
 */
function PriceHistory({ p }) {
  const pct = below;
  const near52wLow = p.pct_above_52w_low != null && p.pct_above_52w_low < 10;
  return (
    <>
      <h3>Where the price sits <em className="sub2">weekly closes</em></h3>
      <div className="kv">
        <div title="How far the price has fallen from its best weekly close of the past year.">
          <span>Below 52-week high</span><b>{pct(p.pct_below_52w_high)}</b>
        </div>
        <div title="A price still hugging its low has not begun to recover; one far above it has.">
          <span>Above 52-week low</span>
          <b className={near52wLow ? "ok" : ""}>
            {p.pct_above_52w_low == null ? "—" : `+${Math.round(p.pct_above_52w_low)}%`}
          </b>
        </div>
        <div title="A one-year decline can be noise; a three-year one usually is not.">
          <span>Below 3-year high</span><b>{pct(p.pct_below_3y_high)}</b>
        </div>
        <div><span>Below 5-year high</span><b>{pct(p.pct_below_5y_high)}</b></div>
        <div title="The median refuses to be impressed by a single irrational peak.">
          <span>Price / 3-year median</span>
          <b className={p.price_to_3y_median < 1 ? "ok" : ""}>
            {p.price_to_3y_median == null ? "—" : `${p.price_to_3y_median.toFixed(2)}×`}
          </b>
        </div>
        <div title="Time since the last week the price stood at its five-year best.">
          <span>Depressed for</span><b>{spell(p.drawdown_weeks)}</b>
        </div>
      </div>
      <p className="dim tiny">
        The price against its own past, and nothing else — what it earns is the
        screen's business, above. Highs are the best weekly close, never an intraday
        spike. History from {p.history_from} ({p.history_weeks} weeks).
      </p>
    </>
  );
}

/**
 * Graham's fifth requirement asked whether the latest year beat a fixed calendar year,
 * 1966. He gives no rule for choosing that base in any other year, and the candidates —
 * a rolling point five years back, a prior peak, a prior average — each prove something
 * different. So the comparison is shown and left to the reader rather than scored.
 */
function EpsGrowth({ g }) {
  const change = g.base_eps > 0 ? (g.latest_eps / g.base_eps - 1) * 100 : null;
  const up = g.latest_eps > g.base_eps;
  return (
    <>
      <h3>Earnings growth <em className="sub2">reported, not scored</em></h3>
      <p className="note">
        FY{g.latest_fiscal_year} EPS <b>{g.latest_eps.toFixed(2)}</b> against{" "}
        FY{g.base_fiscal_year} EPS <b>{g.base_eps.toFixed(2)}</b> — the best year four to
        seven years back{" "}
        <b className={up ? "ok" : "neg"}>
          {up ? "↑" : "↓"}{change == null ? "" : ` ${Math.abs(Math.round(change))}%`}
        </b>
      </p>
      <p className="dim tiny">
        Graham required the latest year to exceed a fixed 1966 base, chosen by name in a
        book written in 1973. No modern base year can be attributed to him, so this
        comparison carries no pass or fail and cannot block a company.
      </p>
    </>
  );
}

function money(v) {
  if (v == null) return "—";
  const a = Math.abs(v);
  for (const [d, s] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (a >= d) return `${(v / d).toFixed(2)}${s}`;
  return v.toLocaleString();
}


/**
 * Graham's criteria say nothing about return on capital: a company can pass every one
 * of them and still grind capital down year after year. This is the derivation behind
 * that number, shown in full because two of its terms are estimates rather than
 * reported figures, and a reader deserves to see which.
 */
function OwnerEarnings({ oe }) {
  const pct = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);
  return (
    <>
      <h3>Return on capital <em className="sub2">FY{oe.fiscal_year}</em></h3>
      <table className="crittable oe">
        <tbody>
          {oe.components.map(([label, v]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="num">{money(v)}</td>
            </tr>
          ))}
          <tr className="pass">
            <td><b>owner earnings</b></td>
            <td className="num"><b>{money(oe.owner_earnings)}</b></td>
          </tr>
          <tr>
            <td>invested capital</td>
            <td className="num">
              {oe.invested_capital == null ? "—" : money(oe.invested_capital)}
            </td>
          </tr>
          <tr className={oe.roic >= 10 ? "pass" : ""}>
            <td><b>ROIC</b></td>
            <td className="num"><b>{pct(oe.roic)}</b></td>
          </tr>
          <tr title="Buffett's own approximation — the optimistic end of the range. A wide gap from the figure above means the company is spending well beyond replacement.">
            <td>ROIC if maintenance capex = depreciation</td>
            <td className="num">{pct(oe.roic_maintenance)}</td>
          </tr>
        </tbody>
      </table>
      <ul className="caveats">
        {oe.caveats.map((c) => <li key={c}>{c}</li>)}
      </ul>
    </>
  );
}
