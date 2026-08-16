/**
 * An endpoint-to-endpoint earnings comparison hides everything in between: a company
 * can end higher than it started while declining every year of the journey. This draws
 * the path itself — no dependency, just a polyline. Colour follows the direction of
 * travel, not the endpoints.
 *
 * The final point is the trailing twelve months, drawn dashed because it is not a
 * completed fiscal year: for a December filer the last audited year ended eight
 * months ago, and where the business is now is the point of the curve.
 */
export function trendOf(annual, ttm) {
  const years = Object.keys(annual ?? {})
    .map(Number)
    .sort((a, b) => a - b)
    .slice(-6); // criterion 4's five-year window, plus the year the growth note compares
  if (years.length < 3) return null;

  const values = years.map((y) => annual[String(y)]);
  const labels = years.map(String);
  // only worth appending when it actually differs from the year just closed
  const hasTtm = ttm != null && Math.abs(ttm - values[values.length - 1]) > 1e-9;
  if (hasTtm) {
    values.push(ttm);
    labels.push("TTM");
  }

  const ups = values.slice(1).filter((v, i) => v > values[i]).length;
  // Direction of travel from the least-squares slope rather than a tally of up
  // years: one recent uptick should not neutralise five years of decline, which
  // is exactly what counting does when the tally ties.
  const n = values.length;
  const meanX = (n - 1) / 2;
  const meanY = values.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  values.forEach((v, i) => {
    num += (i - meanX) * (v - meanY);
    den += (i - meanX) ** 2;
  });
  const slope = den ? num / den : 0;
  // scale-free: a slope worth colouring must move a real share of the average level
  const rising = slope > Math.abs(meanY) * 0.02;
  const falling = slope < -Math.abs(meanY) * 0.02;
  const first = values[0];
  const last = values[values.length - 1];
  // Dividing by a negative base flips the sign, so measure against its magnitude:
  // -3.72 -> 3.08 reads as a large improvement, which is what happened. A base too
  // close to zero makes any percentage absurd, so it is reported as not meaningful.
  const base = Math.abs(first);
  const change = base >= 0.05 ? (last - first) / base : null;
  return { labels, values, ups, downs: values.length - 1 - ups, change, last, first,
           hasTtm, rising, falling };
}

export default function Trend({ trend, format = (v) => v.toFixed(2) }) {
  if (!trend) return <span className="dim">—</span>;
  const { labels, values, ups, downs, change, hasTtm, rising, falling } = trend;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const W = 62, H = 18;
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - ((v - min) / span) * H;
  const pt = (i) => `${x(i).toFixed(1)},${y(values[i]).toFixed(1)}`;

  // Solid = the five years criterion 4 requires to be positive. Dashed at the left is
  // the earlier year the growth note compares against, dashed at the right is the
  // trailing figure — both are context, and a loss in either does not fail criterion 4.
  const lastAnnual = hasTtm ? values.length - 2 : values.length - 1;
  const firstTested = Math.max(0, lastAnnual - 4);
  const solid = values.slice(firstTested, lastAnnual + 1)
    .map((_, k) => pt(firstTested + k)).join(" ");
  const lead = firstTested > 0 ? `${pt(firstTested - 1)} ${pt(firstTested)}` : null;
  const tail = hasTtm ? `${pt(lastAnnual)} ${pt(values.length - 1)}` : null;

  const colour = rising ? "var(--pass)" : falling ? "var(--fail)" : "var(--dim)";
  const title =
    labels.map((l, i) => {
      const tested = i >= firstTested && i <= lastAnnual;
      return `${l} ${format(values[i])}${tested ? "" : "*"}`;
    }).join("  ") +
    `\n${ups} up / ${downs} down` +
    (lead || tail ? "\n* context only — solid line is the 5 years criterion 4 tests" : "");

  return (
    <span className="trend" title={title}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {min < 0 && <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="var(--line)" strokeWidth="1" />}
        {lead && (
          <polyline points={lead} fill="none" stroke={colour} strokeWidth="1.5"
                    strokeDasharray="2 1.5" strokeLinecap="round" opacity="0.55" />
        )}
        <polyline points={solid} fill="none" stroke={colour} strokeWidth="1.5"
                  strokeLinejoin="round" strokeLinecap="round" />
        {tail && (
          <>
            <polyline points={tail} fill="none" stroke={colour} strokeWidth="1.5"
                      strokeDasharray="2 1.5" strokeLinecap="round" />
            <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="1.8"
                    fill={colour} />
          </>
        )}
      </svg>
      <span className="trend-num" style={{ color: colour }}>
        {change == null
          ? "n/m"
          : `${change >= 0 ? "+" : ""}${Math.abs(change) >= 10
              ? Math.round(change).toLocaleString() + "×"
              : Math.round(change * 100) + "%"}`}
      </span>
    </span>
  );
}
