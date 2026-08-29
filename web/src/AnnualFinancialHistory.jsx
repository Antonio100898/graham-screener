/** Annual accounting history, intentionally kept separate from TTM valuation data. */
export default function AnnualFinancialHistory({ annualEps, annualNetIncome, weightedShares }) {
  const eps = annualEps ?? {};
  const income = annualNetIncome ?? {};
  const shares = weightedShares ?? {};
  const years = [...new Set([...Object.keys(eps), ...Object.keys(income), ...Object.keys(shares)])]
    .map(Number).filter(Number.isFinite).sort((a, b) => b - a);
  if (!years.length) return null;
  return (
    <section className="annual-history">
      <div className="criteria-title">
        <div>
          <h3>Annual financial history</h3>
          <p>Completed fiscal years only. Weighted shares are the reported EPS denominator, diluted where available and restated onto the priced receipt when applicable.</p>
        </div>
      </div>
      <div className="annual-history-scroll">
        <table className="annual-history-table">
          <thead>
            <tr><th>Fiscal year</th><th className="num">EPS</th><th className="num">Net income</th><th className="num">Weighted shares</th></tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const e = eps[year];
              const ni = income[year];
              const count = shares[year];
              return <tr key={year} className={(e != null && e < 0) || (ni != null && ni < 0) ? "loss" : ""}>
                <td><b>FY{year}</b></td>
                <td className="num">{e == null ? "—" : number(e)}</td>
                <td className="num">{ni == null ? "—" : money(ni)}</td>
                <td className="num" title={count > 0 ? "Weighted-average security count behind this fiscal year's EPS; diluted where available and restated for any depositary ratio." : "No reported weighted share count for this fiscal year."}>
                  {count > 0 ? `${(count / 1e6).toFixed(1)}M` : "—"}
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
