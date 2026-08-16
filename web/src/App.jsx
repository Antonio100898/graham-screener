import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Detail from "./Detail.jsx";
import LoadBar from "./LoadBar.jsx";
import MultiSelect from "./MultiSelect.jsx";
import Trend, { trendOf } from "./Trend.jsx";
import { send } from "./api.js";
import { below, spell } from "./format.js";
import { loadView, saveView, takeOverScrollRestoration } from "./view.js";
import { TOTAL_CRITERIA, byN, closeness, pe3, whyBlocked } from "./screen.js";


// OR semantics: any typed word matching any field keeps the row. Short and
// common words are dropped first, or "pays no dividend" would match half the
// market on "no". The whole phrase is always tried too, so exact wording wins.
const STOPWORDS = new Set(["the", "and", "for", "with", "not", "are", "was", "its", "inc", "corp"]);

function matcher(query) {
  const phrase = query.trim().toLowerCase();
  if (!phrase) return null;
  const words = phrase
    .split(/[\s,]+/)
    .filter((w) => w.length > 2 && !STOPWORDS.has(w));
  const needles = words.length ? [phrase, ...words] : [phrase];
  return (rows) => rows.filter((r) => needles.some((n) => r.hay.includes(n)));
}


// These columns sort best-first by negating their value, so ascending order puts the
// largest at the top. The arrow must describe what the reader sees, not the sign.
const DESCENDING_BY_DEFAULT = new Set(["n_pass", "mcap", "ni", "trend", "offhigh"]);

function Th({ id, sort, onSort, children, className = "" }) {
  const active = sort.key === id;
  const up = DESCENDING_BY_DEFAULT.has(id) ? sort.dir !== 1 : sort.dir === 1;
  return (
    <th
      className={`${className} sortable ${active ? "sorted" : ""}`}
      onClick={() => onSort(id)}
      title="Sort by this column"
    >
      {children}
      <span className="arrow">{active ? (up ? "▲" : "▼") : "↕"}</span>
    </th>
  );
}

const GRADES = ["NEAR-PASS", "CLOSE", "BLOCKED", "UNGRADEABLE"];
const GRADE_RANK = Object.fromEntries(["PASSES", ...GRADES].map((g, i) => [g, i]));

const saved = loadView();
takeOverScrollRestoration();

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState(saved.q);
  const [grades, setGrades] = useState(new Set(saved.grades));
  const [sort, setSort] = useState(saved.sort);
  const [sectors_, setSectors] = useState(new Set(saved.sectors));
  const [venues, setVenues] = useState(new Set(saved.venues));
  const [minCap, setMinCap] = useState(saved.minCap);   // micro caps are mostly noise here
  // criteria satisfied, 0 = no floor; a floor saved when the screen had more
  // criteria would now match nothing, so it is clamped to what exists today
  const [minMet, setMinMet] = useState(Math.min(saved.minMet, TOTAL_CRITERIA));
  const [minRoic, setMinRoic] = useState(saved.minRoic); // return on capital, 0 = no floor
  const [selected, setSelected] = useState(null);
  const [tracked, setTracked] = useState(new Set());
  const [trackedOnly, setTrackedOnly] = useState(saved.trackedOnly);
  const [hideNA, setHideNA] = useState(saved.hideNA);
  const [hideNoApply, setHideNoApply] = useState(saved.hideNoApply);
  const [belowNcav, setBelowNcav] = useState(saved.belowNcav);

  const load = useCallback(() => {
    // cache-bust so a finished sync shows immediately rather than the stale payload
    fetch(`/dashboard.json?t=${Date.now()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    saveView({
      q, grades: [...grades], sectors: [...sectors_], venues: [...venues],
      minCap, minMet, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, sort,
    });
  }, [q, grades, sectors_, venues, minCap, minMet, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, sort]);

  useEffect(() => {
    const onScroll = () => saveView({ scroll: window.scrollY });
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // restore only after the rows exist, or the page is still too short to scroll
  const restored = useRef(false);
  useLayoutEffect(() => {
    if (restored.current || !data || !saved.scroll) return;
    restored.current = true;
    requestAnimationFrame(() => window.scrollTo(0, saved.scroll));
  }, [data]);

  useEffect(() => {
    fetch("/tracked")
      .then((r) => r.json())
      .then((d) => setTracked(new Set(d.tracked.map((t) => t.cik))))
      .catch(() => {});
  }, []);

  const toggleTracked = async (row, e) => {
    e.stopPropagation();          // the row click opens the detail panel
    const on = tracked.has(row.cik);
    setTracked((prev) => {        // optimistic: the list is local and cheap to revert
      const next = new Set(prev);
      on ? next.delete(row.cik) : next.add(row.cik);
      return next;
    });
    await send(on ? `/tracked/${row.cik}` : "/tracked", {
      method: on ? "DELETE" : "POST",
      body: on ? undefined : { cik: row.cik },
    }).catch(() => {});
  };

  const rows = useMemo(() => {
    if (!data) return [];
    return data.rows.map((r) => {
      const g = closeness(r);
      const blocked = whyBlocked(r);
      return {
        ...r, grade: g.label, gradeNote: g.note, blocked,
        mcap: r.price && r.shares ? r.price * r.shares : null,
        trend: trendOf(r.annual_eps, r.ttm_eps),
        // any criterion we could not decide either way leaves the verdict incomplete
        unjudged: r.criteria.some((c) => c.status !== "PASS" && c.status !== "FAIL"),
        // criteria 2 and 3 cannot be asked of a filer with no classified balance
        // sheet — unlike a missing figure, no later filing will ever supply it
        inapplicable: r.criteria.some((c) => c.status === "NOT_APPLICABLE"),
        netNet: r.ncavps != null && r.price != null && r.ncavps > 0 && r.price <= r.ncavps,
        pe3: pe3(r),
        roic: r.owner_earnings?.roic ?? null,
        niTrend: trendOf(r.annual_net_income, r.ttm_net_income),
        // searched fields, flattened once: ticker, name, both sector levels,
        // the plain-English blocker, and the grade itself
        hay: [r.ticker, r.name, r.sector, r.industry, r.exchange, blocked, g.label]
          .filter(Boolean).join(" ").toLowerCase(),
      };
    });
  }, [data]);

  const view = useMemo(() => {
    const match = matcher(q);
    let out = rows.filter((r) => grades.size === 0 || grades.has(r.grade));
    if (sectors_.size) out = out.filter((r) => sectors_.has(r.sector ?? "Unclassified"));
    if (venues.size) out = out.filter((r) => venues.has(r.exchange));
    // a company with no price or no share count cannot be sized, so a floor excludes it
    if (minCap) out = out.filter((r) => (r.mcap ?? 0) >= minCap);
    if (trackedOnly) out = out.filter((r) => tracked.has(r.cik));
    if (minMet) out = out.filter((r) => r.n_pass >= minMet);
    // a company whose return on capital could not be computed cannot clear a floor
    if (minRoic) out = out.filter((r) => r.roic != null && r.roic >= minRoic);
    if (hideNoApply) out = out.filter((r) => !r.inapplicable);
    if (hideNA) out = out.filter((r) => !r.unjudged);
    if (belowNcav) out = out.filter((r) => r.netNet);
    if (match) out = match(out);
    const { key, dir } = sort;
    // null means "no value" — never a number. Returning Infinity here would park
    // those rows at the top as soon as the sort flipped to descending.
    const val = (r) => {
      if (key === "grade") return GRADE_RANK[r.grade] ?? 99;
      if (key === "ticker") return r.ticker ?? "";
      if (key === "sector") return r.sector ?? null;
      if (key === "name") return r.name ?? "";
      if (key === "n_pass") return -r.n_pass;
      if (key === "pe") return byN(r, 1).value ?? null;
      if (key === "pe3") return r.pe3 ?? null;
      // the interesting end is the most beaten-down, so sort those to the top
      if (key === "offhigh")
        return r.price_stats?.pct_below_52w_high == null
          ? null : -r.price_stats.pct_below_52w_high;
      if (key === "ptbv") return byN(r, 7).value ?? null;
      if (key === "price") return r.price ?? null;
      if (key === "mcap") return r.mcap == null ? null : -r.mcap;
      if (key === "ni") {
        if (!r.niTrend) return null;
        return r.niTrend.change == null ? -r.niTrend.ups : -r.niTrend.change;
      }
      // sort by the real 8-year path, not the two endpoints the growth note compares
      if (key === "trend") {
        if (!r.trend) return null;
        return r.trend.change == null ? -r.trend.ups : -r.trend.change;
      }
      return 0;
    };
    return out.sort((a, b) => {
      const x = val(a), y = val(b);
      // rows with nothing to compare always finish last, whichever way we sort
      if (x == null || y == null) {
        if (x == null && y == null) return (a.ticker ?? "").localeCompare(b.ticker ?? "");
        return x == null ? 1 : -1;
      }
      const cmp = typeof x === "string" ? x.localeCompare(y) : x - y;
      return cmp * dir || (a.ticker ?? "").localeCompare(b.ticker ?? "");
    });
  }, [rows, q, grades, sort, sectors_, venues, minCap, minMet, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, tracked]);

  const naCount = useMemo(() => rows.filter((r) => r.unjudged).length, [rows]);
  const netNetCount = useMemo(() => rows.filter((r) => r.netNet).length, [rows]);
  const noApplyCount = useMemo(() => rows.filter((r) => r.inapplicable).length, [rows]);

  const metCounts = useMemo(() => {
    const c = {};
    rows.forEach((r) => {
      for (let n = 1; n <= r.n_pass; n++) c[n] = (c[n] ?? 0) + 1;
    });
    return c;
  }, [rows]);

  const sectorCounts = useMemo(() => {
    const c = {};
    rows.forEach((r) => {
      const k = r.sector ?? "Unclassified";
      c[k] = (c[k] ?? 0) + 1;
    });
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [rows]);
  const exchanges = useMemo(() => {
    const c = {};
    rows.forEach((r) => r.exchange && (c[r.exchange] = (c[r.exchange] ?? 0) + 1));
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [rows]);

  // a search that hits nothing inside the active filters, but matches elsewhere,
  // must say so rather than showing an empty table
  const matchesAnywhere = useMemo(() => {
    const match = matcher(q);
    return match ? match(rows).length : 0;
  }, [rows, q]);

  const gradeCounts = useMemo(() => {
    const c = {};
    rows.forEach((r) => (c[r.grade] = (c[r.grade] ?? 0) + 1));
    return GRADES.map((g) => [g, c[g] ?? 0]);
  }, [rows]);

  if (error)
    return (
      <div className="app">
        <LoadBar onFinished={load} />
        <div className="msg err">
          No data yet — {error}
          <br />
          Use <b>Load all filers</b> above, or run <code>make bulk &amp;&amp; make export</code>.
        </div>
      </div>
    );
  if (!data) return <div className="msg">Loading universe…</div>;

  const sortBy = (key) =>
    setSort((s) => ({ key, dir: s.key === key ? -s.dir : 1 }));
  const toggleGrade = (g) =>
    setGrades((s) => {
      const n = new Set(s);
      n.has(g) ? n.delete(g) : n.add(g);
      return n;
    });

  return (
    <div className="app">
      <header>
        <div>
          <h1>Graham Enterprising Screener</h1>
          <p className="sub">
            {rows.length.toLocaleString()} companies · engine v{data.engine_version} · generated{" "}
            {data.generated?.slice(0, 16).replace("T", " ")}
          </p>
          {(data.indexes?.sp500 || data.indexes?.nasdaq) && (
            <p className="sub" title="Median of price ÷ trailing-twelve-month EPS across index members. Loss-makers have no P/E and are left out — the counts say how many members carried one.">
              Median P/E
              {data.indexes.sp500 && (
                <> · S&amp;P 500 <b>{data.indexes.sp500.median_pe}</b>
                  <span className="dim"> ({data.indexes.sp500.n} of {data.indexes.sp500.members})</span></>
              )}
              {data.indexes.nasdaq && (
                <> · Nasdaq <b>{data.indexes.nasdaq.median_pe}</b>
                  <span className="dim"> ({data.indexes.nasdaq.n} of {data.indexes.nasdaq.members})</span></>
              )}
            </p>
          )}
          <IndexHistory indexes={data.indexes} />
        </div>
        <div className="searchwrap">
        <input
          className="search"
          placeholder="Search…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {q.trim() && (
          <span className="searchhint">
            {view.length.toLocaleString()} match{view.length === 1 ? "" : "es"}
          </span>
        )}
        </div>
      </header>

      <LoadBar onFinished={load} shown={rows.length} />

      <div className="filters">
        <MultiSelect label="How close" options={gradeCounts} selected={grades} onChange={setGrades} />
        <MultiSelect label="Sector" options={sectorCounts} selected={sectors_} onChange={setSectors} />
        <MultiSelect label="Exchange" options={exchanges} selected={venues} onChange={setVenues} />
        <select className="mincap" value={minMet} onChange={(e) => setMinMet(Number(e.target.value))}>
          <option value={0}>Any criteria met</option>
          {[...Array(4)].map((_, i) => TOTAL_CRITERIA - i).map((n) => (
            <option key={n} value={n}>
              {n}/{TOTAL_CRITERIA} and above{metCounts[n] ? ` (${metCounts[n].toLocaleString()})` : ""}
            </option>
          ))}
        </select>
        <select className="mincap" value={minRoic} onChange={(e) => setMinRoic(Number(e.target.value))}
                title="Owner earnings divided by invested capital. Graham's followers treat 10% as attractive and 6% as acceptable for a strong brand or a business temporarily under a cloud.">
          <option value={0}>Any ROIC</option>
          <option value={15}>15%+ (exceptional)</option>
          <option value={10}>10%+ (attractive)</option>
          <option value={6}>6%+ (acceptable)</option>
        </select>
        <select className="mincap" value={minCap} onChange={(e) => setMinCap(Number(e.target.value))}>
          <option value={0}>Any size</option>
          <option value={50e6}>$50M+</option>
          <option value={500e6}>$500M+</option>
          <option value={2e9}>$2B+</option>
          <option value={10e9}>$10B+</option>
        </select>
        <button className={`chip na ${hideNoApply ? "on" : ""}`}
                onClick={() => setHideNoApply((v) => !v)}
                title="Banks, insurers and REITs file no classified balance sheet, so criteria 2 and 3 ask for a figure their accounts never contain. No later filing will supply it, so these can never be graded on every criterion.">
          {hideNoApply ? "Applicable only" : "Hide not-applicable"} <span className="count">{noApplyCount}</span>
        </button>
        <button className={`chip na ${hideNA ? "on" : ""}`}
                onClick={() => setHideNA((v) => !v)}
                title="Hides any company where a criterion could not be decided — banks and homebuilders whose filings make criteria 2 and 3 meaningless, and companies missing the figures a test needs. What remains has been judged on every criterion.">
          {hideNA ? "Judged only" : `Judged on all ${TOTAL_CRITERIA}`} <span className="count">{naCount}</span>
        </button>
        <button className={`chip netnet ${belowNcav ? "on" : ""}`}
                onClick={() => setBelowNcav((v) => !v)}
                title="Price at or below net current asset value per share — the liquid assets left after paying every liability. Graham's deepest-value test.">
          ≤ NCAV <span className="count">{netNetCount}</span>
        </button>
        <button className={`chip star ${trackedOnly ? "on" : ""}`}
                onClick={() => setTrackedOnly((v) => !v)}>
          ★ Tracked <span className="count">{tracked.size}</span>
        </button>
        {(grades.size > 0 || sectors_.size > 0 || venues.size > 0 || minMet > 0 || minRoic > 0 || hideNA || !hideNoApply || belowNcav) && (
          <button className="chip clear" onClick={() => {
            setGrades(new Set()); setSectors(new Set()); setVenues(new Set()); setMinMet(0); setMinRoic(0); setHideNA(false); setHideNoApply(true); setBelowNcav(false);
          }}>clear all</button>
        )}
        <span className="showing">
          showing {view.length.toLocaleString()} of {rows.length.toLocaleString()}
        </span>
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th className="starcol"></th>
            <Th id="ticker" sort={sort} onSort={sortBy}>Ticker</Th>
            <Th id="name" sort={sort} onSort={sortBy}>Company</Th>
            <Th id="sector" sort={sort} onSort={sortBy}>Sector</Th>
            <Th id="grade" sort={sort} onSort={sortBy}>How close</Th>
            <Th id="n_pass" sort={sort} onSort={sortBy}>Met</Th>
            <Th id="ni" sort={sort} onSort={sortBy}>Net income<em className="sub2">5-year shape</em></Th>
            <Th id="trend" sort={sort} onSort={sortBy}>EPS trend</Th>
            <Th id="mcap" sort={sort} onSort={sortBy} className="num">Mkt cap</Th>
            <Th id="price" sort={sort} onSort={sortBy} className="num">Price</Th>
            <Th id="offhigh" sort={sort} onSort={sortBy} className="num">
              Off high<em className="sub2">52w · 5y</em>
            </Th>
            <Th id="pe" sort={sort} onSort={sortBy} className="num">P/E</Th>
            <Th id="pe3" sort={sort} onSort={sortBy} className="num">
              P/E 3y<em className="sub2">avg EPS</em>
            </Th>
            <Th id="ptbv" sort={sort} onSort={sortBy} className="num">P/TBV</Th>
          </tr>
        </thead>
        <tbody>
          {view.slice(0, 300).map((r) => (
            <tr key={r.cik} onClick={() => setSelected(r)}
                className={tracked.has(r.cik) ? "istracked" : ""}>
              <td className="starcol" data-label="">
                <button className={`star-btn ${tracked.has(r.cik) ? "on" : ""}`}
                        title={tracked.has(r.cik) ? "Remove from tracked" : "Track this company"}
                        onClick={(e) => toggleTracked(r, e)}>
                  {tracked.has(r.cik) ? "★" : "☆"}
                </button>
              </td>
              <td className="tick" data-label="Ticker">
                {r.ticker}
                {r.earnings_quality?.length ? <span className="warn" title="earnings caveats">⚠</span> : null}
                {r.netNet && (
                  <span className="netnetmark" title="trading at or below net current asset value">
                    net-net
                  </span>
                )}
              </td>
              <td className="name" data-label="Company">{r.name}</td>
              <td className="sector" data-label="Sector" title={r.industry ?? ""}>{r.sector ?? "—"}{r.exchange === "OTC" && <span className="otc">OTC</span>}</td>
              <td data-label="How close">
                <span className={`chip sm ${r.grade.toLowerCase()} ${r.unknownCount ? "partial" : ""}`}
                      title={r.gradeNote}>
                  {r.grade}
                  {r.unknownCount > 0 && <sup className="unk">?{r.unknownCount}</sup>}
                </span>
              </td>
              <td className="num" data-label="Met">{r.n_pass}/{TOTAL_CRITERIA}</td>
              <td data-label="Net income" title={niTitle(r)}>
                <Trend trend={r.niTrend} format={(v) => fmtCap(v)} />
                {divergence(r) && <span className="diverge">{divergence(r)}</span>}
              </td>
              <td data-label="EPS trend"><Trend trend={r.trend} /></td>
              <td className="num" data-label="Mkt cap">{fmtCap(r.mcap)}</td>
              <td className="num" data-label="Price">{fmtPrice(r.price)}</td>
              <td className="num offhigh" data-label="Off high" title={drawdownTitle(r)}>
                {r.price_stats?.pct_below_52w_high == null ? (
                  <span className="dim">—</span>
                ) : (
                  <>
                    <b>{below(r.price_stats.pct_below_52w_high)}</b>
                    <span className="dim"> · {below(r.price_stats.pct_below_5y_high)}</span>
                  </>
                )}
              </td>
              <td className="num" data-label="P/E">{fmt(byN(r, 1).value)}</td>
              <td className="num" data-label="P/E 3y"
                  title="current price over the average of the three latest annual EPS — one lucky or disastrous year moves it a third as much as it moves the TTM P/E">
                {fmt(r.pe3)}
              </td>
              <td className="num" data-label="P/TBV">{fmt(byN(r, 7).value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {view.length === 0 && matchesAnywhere > 0 && (
        <p className="msg">
          No match inside the current filters, but <b>{matchesAnywhere.toLocaleString()}</b>{" "}
          elsewhere.{" "}
          <button className="linkish" onClick={() => { setGrades(new Set()); setSectors(new Set()); setVenues(new Set()); }}>
            search everything
          </button>
        </p>
      )}
      {view.length === 0 && matchesAnywhere === 0 && q.trim() && (
        <p className="msg dim">Nothing matches “{q.trim()}”.</p>
      )}
      {view.length > 300 && <p className="msg dim">First 300 shown — narrow the filter to see more.</p>}

      {selected && <Detail row={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

const fmt = (v) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 }));

function IndexHistory({ indexes }) {
  const sp = indexes?.sp500?.history, nq = indexes?.nasdaq?.history;
  if (!sp && !nq) return null;
  const years = [...new Set([...(sp ?? []), ...(nq ?? [])].map((h) => h.year))].sort();
  const at = (hist, y) => hist?.find((h) => h.year === y) ?? {};
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
  return (
    <table className="idxhist"
           title={"Median across today's members (past years carry survivorship bias)."
             + "\nΔ price — the member's price change over that calendar year; the current year runs to the live quote."
             + "\nP/E — December's last close over the annual EPS reported for that fiscal year; loss-makers excluded. The current year has no closed annual figure yet."}>
      <thead>
        <tr><th></th><th colSpan={2}>S&amp;P 500</th><th colSpan={2}>Nasdaq</th></tr>
        <tr><th></th><th>Δ price</th><th>P/E</th><th>Δ price</th><th>P/E</th></tr>
      </thead>
      <tbody>
        {years.map((y) => {
          const s = at(sp, y), n = at(nq, y);
          return (
            <tr key={y}>
              <td>{y}{(s.ytd || n.ytd) ? " YTD" : ""}</td>
              <td className={s.ret < 0 ? "neg" : ""}>{pct(s.ret)}</td>
              <td>{s.pe ?? "—"}</td>
              <td className={n.ret < 0 ? "neg" : ""}>{pct(n.ret)}</td>
              <td>{n.pe ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// penny stocks rounded to 2dp all read "$0.00", which looks like missing data
const fmtPrice = (v) => {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toPrecision(2)}`;
  if (v < 1) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
};

// EPS can rise on buybacks alone, so flag when the two move differently
function divergence(r) {
  const e = r.trend?.change, n = r.niTrend?.change;
  if (e == null || n == null) return null;
  if (e > 0.05 && n < 0) return "▲EPS ▼earnings";
  if (e < 0 && n > 0.05) return "▼EPS ▲earnings";
  return null;
}

function niTitle(r) {
  const n = r.niTrend;
  const ttm = r.ttm_net_income != null ? `TTM net income ${fmtCap(r.ttm_net_income)}` : "";
  if (!n) return ttm || "net income";
  const pct = n.change == null ? "n/m" : `${n.change >= 0 ? "+" : ""}${Math.round(n.change * 100)}%`;
  return `${ttm}\nchange over the window ${pct}\n` +
         n.labels.map((l, i) => `${l} ${(n.values[i] / 1e6).toFixed(0)}M`).join("  ");
}

/** How long the market has kept the company down, and how far off its own range. */
export function drawdownTitle(r) {
  const p = r.price_stats;
  if (!p) return "no price history available";
  return [
    `${p.pct_below_52w_high}% below the 52-week high`,
    `${p.pct_above_52w_low}% above the 52-week low`,
    `${p.pct_below_3y_high}% below the 3-year high`,
    `${p.pct_below_5y_high}% below the 5-year high`,
    `${p.price_to_3y_median}× the 3-year median price`,
    `last at its 5-year peak ${spell(p.drawdown_weeks)} ago`,
    "\nweekly closing prices — a high here is the best weekly close, not an intraday spike",
  ].join("\n");
}

const fmtCap = (v) => {
  if (!v) return "—";
  for (const [d, s] of [[1e12, "T"], [1e9, "B"], [1e6, "M"]])
    if (v >= d) return `$${(v / d).toFixed(v / d < 10 ? 1 : 0)}${s}`;
  return `$${(v / 1e3).toFixed(0)}K`;
};
