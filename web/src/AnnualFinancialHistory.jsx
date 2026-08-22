/** Annual accounting history, intentionally kept separate from TTM valuation data. */
export default function AnnualFinancialHistory({ annualEps, annualNetIncome, preferred }) {
  const eps = annualEps ?? {};
  const income = annualNetIncome ?? {};
  // Earnings per share are struck on what is left for the common; the net income
  // tag is not. Dividing one by the other without removing the preferred's share
  // printed 3,509.6M implied shares for Occidental against a reported 999.7M.
  const pref = preferred ?? {};
  const years = [...new Set([...Object.keys(eps), ...Object.keys(income)])]
    .map(Number).filter(Number.isFinite).sort((a, b) => b - a);
  if (!years.length) return null;
  return (
    <section className="annual-history">
      <div className="criteria-title">
        <div>
          <h3>Annual financial history</h3>
          <p>Completed fiscal years only. Share count is implied by net income ÷ EPS and is shown as a cross-check, not a reported share-count fact.</p>
        </div>
      </div>
      <div className="annual-history-scroll">
        <table className="annual-history-table">
          <thead>
            <tr><th>Fiscal year</th><th className="num">EPS</th><th className="num">Net income</th><th className="num">Implied shares</th></tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const e = eps[year];
              const ni = income[year];
              const common = ni == null ? null : ni - (pref[year] ?? 0);
              const shares = e != null && e !== 0 && common != null ? common / e : null;
              const validShares = shares != null && shares > 0;
              return <tr key={year} className={(e != null && e < 0) || (ni != null && ni < 0) ? "loss" : ""}>
                <td><b>FY{year}</b></td>
                <td className="num">{e == null ? "—" : number(e)}</td>
                <td className="num">{ni == null ? "—" : money(ni)}</td>
                <td className="num" title={validShares ? "Earnings available to common (net income less preferred dividends) divided by EPS; this is an implied weighted share count." : "Cannot infer a meaningful share count when EPS or net income is missing, zero, or of a different sign."}>
                  {validShares ? `${(shares / 1e6).toFixed(1)}M` : "—"}
                </td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function number(value) { return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 }); }
function money(value) {
  const absolute = Math.abs(value);
  for (const [divisor, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (absolute >= divisor) return `$${(value / divisor).toFixed(Math.abs(value / divisor) < 10 ? 1 : 0)}${suffix}`;
  return `$${number(value)}`;
}
