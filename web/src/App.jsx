import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Detail from "./Detail.jsx";
import LoadBar from "./LoadBar.jsx";
import MultiSelect from "./MultiSelect.jsx";
import EarningsEvidence, { epsEvidence } from "./EarningsEvidence.jsx";
import { send } from "./api.js";
import { below, spell } from "./format.js";
import { loadView, saveView, takeOverScrollRestoration } from "./view.js";
import { TOTAL_CRITERIA, byN, indexValuation, pe3 } from "./screen.js";
import { AlignmentCompact } from "./Alignment.jsx";
import { alignmentSortValue } from "./alignment.js";
import { compareRows, normalizeSort, updateSort } from "./sort.js";
import { payloadWarnings } from "./warnings.js";
import Portfolio from "./Portfolio.jsx";
import TradeModal from "./TradeModal.jsx";
import { matchesPortfolio, openPortfolioCiks } from "./portfolio.js";
import { quoteStatus, quoteTitle, quoteTone } from "./quote.js";


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
const DESCENDING_BY_DEFAULT = new Set(["fit", "n_pass", "mcap", "ni", "trend", "offhigh", "eps10"]);
const EPS_POSITIVE_FLOORS = [5, 6, 7, 9, 10];
const LENSES = ["BOTH", "ENTERPRISING", "DEFENSIVE"];
const FITS = ["ALL", "ALIGNED", "EVIDENCE_INCOMPLETE", "BLOCKED"];
const PROFILE_NAMES = {
  OPERATING: "Operating businesses", UTILITY: "Public utilities",
  FINANCIAL: "Financials & real estate", SPECIAL: "Special structures",
  REVIEW: "Manual review",
};
function enterprisingGap(row) {
  const screen = row.alignment?.enterprising;
  if (!screen || row.profile !== "OPERATING") return "OUT_OF_SCOPE";
  if (screen.unknown > 0 || screen.verdict === "EVIDENCE_INCOMPLETE") return "INCOMPLETE";
  const gaps = (screen.total ?? 0) - (screen.passed ?? 0);
  if (gaps === 0) return "ALL_PASS";
  if (gaps === 1) return "ONE_GAP";
  if (gaps === 2) return "TWO_GAPS";
  return "THREE_PLUS";
}

function Th({ id, sort, onSort, children, className = "" }) {
  const priority = sort.findIndex((item) => item.key === id);
  const active = priority !== -1;
  const direction = active ? sort[priority].dir : 1;
  const up = DESCENDING_BY_DEFAULT.has(id) ? direction !== 1 : direction === 1;
  return (
    <th
      className={`${className} sortable ${active ? "sorted" : ""}`}
      onClick={(event) => onSort(id, event.shiftKey)}
      title="Click for primary sort; Shift-click to add or toggle another column"
    >
      {children}
      <span className="arrow">{active ? (up ? "▲" : "▼") : "↕"}</span>
      {active && sort.length > 1 && <span className="sort-priority">{priority + 1}</span>}
    </th>
  );
}

// narrowest first: 30 companies beat 500 beat ~100 beat every Nasdaq listing
const INDEX_RANK = { "DJIA": 0, "S&P 500": 1, "Nasdaq 100": 2, "Nasdaq Comp": 3 };
// "Nasdaq Comp" is every Nasdaq listing, which the Exchange filter already says;
// the badge is named for what it is rather than for an index it does not track
const INDEX_SHORT = { "DJIA": "DJIA", "S&P 500": "S&P", "Nasdaq 100": "N100", "Nasdaq Comp": "Nasdaq-listed" };

const saved = loadView();
takeOverScrollRestoration();

const initialSort = normalizeSort(saved.sort).map((item) =>
  ["grade", "ptbv"].includes(item.key) ? { key: "fit", dir: 1 } : item
);

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState(saved.q);
  const [lens, setLens] = useState(saved.lens);
  const [fit, setFit] = useState(saved.fit);
  const [gaps, setGaps] = useState(saved.gaps);
  const [sort, setSort] = useState(() => normalizeSort(initialSort));
  const [sectors_, setSectors] = useState(new Set(saved.sectors));
  const [profiles, setProfiles] = useState(new Set(saved.profiles));
  const [idxSel, setIdxSel] = useState(new Set(saved.indexes));
  const [venues, setVenues] = useState(new Set(saved.venues));
  const [minCap, setMinCap] = useState(saved.minCap);   // micro caps are mostly noise here
  // criteria satisfied, 0 = no floor; a floor saved when the screen had more
  // criteria would now match nothing, so it is clamped to what exists today
  const [minMet, setMinMet] = useState(Math.min(saved.minMet, TOTAL_CRITERIA));
  const [minPositiveEps, setMinPositiveEps] = useState(saved.minPositiveEps);
  const [minRoic, setMinRoic] = useState(saved.minRoic); // return on capital, 0 = no floor
  const [selected, setSelected] = useState(null);
  const [tracked, setTracked] = useState(new Set());
  const [trackingError, setTrackingError] = useState(null);
  const [trackedOnly, setTrackedOnly] = useState(saved.trackedOnly);
  const [hideNA, setHideNA] = useState(saved.hideNA);
  const [hideNoApply, setHideNoApply] = useState(saved.hideNoApply);
  const [belowNcav, setBelowNcav] = useState(saved.belowNcav);
  const [page, setPage] = useState(() => window.location.hash === "#portfolio" ? "portfolio" : "screener");
  const [portfolioData, setPortfolioData] = useState(null);
  const [portfolioError, setPortfolioError] = useState(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [portfolioQ, setPortfolioQ] = useState("");
  const [tradeTarget, setTradeTarget] = useState(null);

  const load = useCallback(() => {
    // cache-bust so a finished sync shows immediately rather than the stale payload
    fetch(`/dashboard.json?t=${Date.now()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const loadPortfolio = useCallback(() => {
    setPortfolioLoading(true);
    fetch(`/portfolio?t=${Date.now()}`)
      .then((response) => response.ok
        ? response.json()
        : response.json().catch(() => null).then((body) => Promise.reject(new Error(body?.detail ?? `HTTP ${response.status}`))))
      .then((result) => { setPortfolioData(result); setPortfolioError(null); })
      .catch((err) => setPortfolioError(err.message))
      .finally(() => setPortfolioLoading(false));
  }, []);

  useEffect(() => { loadPortfolio(); }, [loadPortfolio, page]);

  useEffect(() => {
    const changed = () => setPage(window.location.hash === "#portfolio" ? "portfolio" : "screener");
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);

  useEffect(() => {
    saveView({
      q, lens, fit, gaps, sectors: [...sectors_], profiles: [...profiles], venues: [...venues],
      indexes: [...idxSel],
      minCap, minMet, minPositiveEps, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, sort,
    });
  }, [q, lens, fit, gaps, sectors_, profiles, venues, idxSel, minCap, minMet, minPositiveEps, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, sort]);

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
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        if (!Array.isArray(d.tracked)) throw new Error("invalid tracking response");
        setTracked(new Set(d.tracked.map((t) => t.cik)));
        setTrackingError(null);
      })
      .catch((e) => setTrackingError(`Tracked companies could not be loaded: ${e.message}`));
  }, []);

  const toggleTracked = async (row, e) => {
    e?.stopPropagation();         // the row click opens the detail panel; the detail star has none
    const on = tracked.has(row.cik);
    setTracked((prev) => {        // optimistic: the list is local and cheap to revert
      const next = new Set(prev);
      on ? next.delete(row.cik) : next.add(row.cik);
      return next;
    });
    try {
      const response = await send(on ? `/tracked/${row.cik}` : "/tracked", {
        method: on ? "DELETE" : "POST",
        body: on ? undefined : { cik: row.cik },
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || result?.tracked !== !on || result?.cik !== row.cik)
        throw new Error(result?.detail ?? `HTTP ${response.status}: invalid tracking response`);
      setTrackingError(null);
    } catch (e) {
      // The optimistic star must not claim persistence the server did not confirm.
      setTracked((prev) => {
        const next = new Set(prev);
        on ? next.add(row.cik) : next.delete(row.cik);
        return next;
      });
      setTrackingError(`Tracking change was not saved: ${e.message}`);
    }
  };

  const navigate = (next) => {
    window.location.hash = next === "portfolio" ? "portfolio" : "";
    setPage(next);
  };

  const deleteTrade = async (trade) => {
    if (!portfolioData) return;
    const description = `${trade.side} ${trade.quantity} ${trade.ticker} at $${trade.price}`;
    if (!window.confirm(`Delete ${description}?\n\nThis corrects the local ledger and cannot be undone.`)) return;
    try {
      const response = await send(`/portfolio/${portfolioData.portfolio.id}/trades/${trade.id}`, {
        method: "DELETE",
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.portfolio)
        throw new Error(result?.detail ?? `HTTP ${response.status}: trade was not deleted`);
      setPortfolioData(result.portfolio);
      setPortfolioError(null);
      loadPortfolio();
    } catch (err) {
      setPortfolioError(err.message);
    }
  };

  const portfolioCiks = useMemo(() => openPortfolioCiks(portfolioData), [portfolioData]);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.rows.map((r) => {
      return {
        ...r,
        mcap: r.price && r.shares ? r.price * r.shares : null,
        eps10: epsEvidence(r.annual_eps),
        // any criterion we could not decide either way leaves the verdict incomplete
        unjudged: r.criteria.some((c) => c.status !== "PASS" && c.status !== "FAIL"),
        // criteria 2 and 3 cannot be asked of a filer with no classified balance
        // sheet — unlike a missing figure, no later filing will ever supply it
        inapplicable: r.criteria.some((c) => c.status === "NOT_APPLICABLE"),
        netNet: r.ncavps != null && r.price != null && r.ncavps > 0 && r.price <= r.ncavps,
        // only while net current assets are positive: a negative denominator
        // would turn the cheapest-looking ratio into the most expensive company
        pncav: r.ncavps != null && r.price != null && r.ncavps > 0 ? r.price / r.ncavps : null,
        idx: r.index_memberships ?? [],
        pe3: pe3(r),
        // This is the explicitly labelled total-capex floor return, not a
        // definitive Buffett owner-earnings return.
        roic: r.owner_earnings?.all_capex_return ?? null,
        profile: r.graham_profile ?? "REVIEW",
        warnings: payloadWarnings(r),
        // searched fields, flattened once: ticker, name, sector, and issuer profile
        hay: [r.ticker, r.name, r.sector, r.industry, r.exchange, r.graham_profile]
          .filter(Boolean).join(" ").toLowerCase(),
      };
    });
  }, [data]);

  // This market reference deliberately ignores the filters below. It describes
  // every S&P 500 member represented in the loaded dashboard payload.
  const sp500 = useMemo(() => indexValuation(rows, "S&P 500"), [rows]);

  const view = useMemo(() => {
    const match = matcher(q);
    let out = rows;
    if (profiles.size) out = out.filter((r) => profiles.has(r.profile));
    if (lens !== "BOTH") {
      const key = lens.toLowerCase();
      // Selecting one lens also hides companies to which that historical method
      // does not apply; their valuation evidence remains available under Both.
      out = out.filter((r) => r.alignment?.[key]?.verdict !== "OUT_OF_SCOPE");
    }
    if (fit !== "ALL") {
      const key = lens === "BOTH" ? null : lens.toLowerCase();
      out = out.filter((r) => key
        ? r.alignment?.[key]?.verdict === fit
        : [r.alignment?.enterprising?.verdict, r.alignment?.defensive?.verdict].includes(fit));
    }
    // Gaps are meaningful only for Chapter 15's industrial direct tests.
    if (lens === "ENTERPRISING" && gaps !== "ALL")
      out = out.filter((r) => enterprisingGap(r) === gaps);
    if (sectors_.size) out = out.filter((r) => sectors_.has(r.sector ?? "Unclassified"));
    if (venues.size) out = out.filter((r) => venues.has(r.exchange));
    if (idxSel.size)
      out = out.filter((r) =>
        r.idx.some((m) => idxSel.has(m)) || (idxSel.has("Outside") && r.idx.length === 0));
    // a company with no price or no share count cannot be sized, so a floor excludes it
    if (minCap) out = out.filter((r) => (r.mcap ?? 0) >= minCap);
    if (trackedOnly) out = out.filter((r) => tracked.has(r.cik));
    if (minMet) out = out.filter((r) => r.n_pass >= minMet);
    // Uses the same completed FY(L-9)..FY(L) evidence window shown in the table.
    // Missing years stay missing; they are never silently filled with zero.
    if (minPositiveEps) out = out.filter((r) => r.eps10?.positive >= minPositiveEps);
    // a company whose return on capital could not be computed cannot clear a floor
    if (minRoic) out = out.filter((r) => r.roic != null && r.roic >= minRoic);
    if (hideNoApply) out = out.filter((r) => !r.inapplicable);
    if (hideNA) out = out.filter((r) => !r.unjudged);
    if (belowNcav) out = out.filter((r) => r.netNet);
    if (match) out = match(out);
    // null means "no value" — never a number. Returning Infinity here would park
    // those rows at the top as soon as the sort flipped to descending.
    const val = (r, key) => {
      // Graham fit displays Enterprising and Defensive points together, so its
      // sort follows that visible combined score rather than verdict labels.
      if (key === "fit") return alignmentSortValue(r);
      if (key === "ticker") return r.ticker ?? "";
      if (key === "sector") return r.sector ?? null;
      if (key === "index") return r.idx.length ? INDEX_RANK[r.idx[0]] ?? 8 : 9;
      if (key === "name") return r.name ?? "";
      if (key === "n_pass") return -r.n_pass;
      if (key === "pe") return byN(r, 1).value ?? null;
      if (key === "pe3") return r.pe3 ?? null;
      // the interesting end is the highest return, so it leads on the first click
      if (key === "roic") return r.roic == null ? null : -r.roic;
      // here the interesting end is the cheapest, which is the lowest ratio
      if (key === "pncav") return r.pncav ?? null;
      // the interesting end is the most beaten-down, so sort those to the top
      if (key === "offhigh")
        return r.price_stats?.pct_below_52w_high == null
          ? null : -r.price_stats.pct_below_52w_high;
      if (key === "price") return r.price ?? null;
      if (key === "mcap") return r.mcap == null ? null : -r.mcap;
      if (key === "eps10") {
        // The column is sorted by the visible positive-year count, not by its
        // separate Graham growth calculation.  A negative value puts the most
        // positive years first on the initial descending-style sort.
        return r.eps10 ? -r.eps10.positive : null;
      }
      return 0;
    };
    return out.sort((a, b) => compareRows(a, b, sort, val));
  }, [rows, q, lens, fit, gaps, sort, sectors_, profiles, venues, idxSel, minCap, minMet, minPositiveEps, minRoic, hideNA, hideNoApply, belowNcav, trackedOnly, tracked]);

  // Counted over the rows on screen, not over all 5,893: with the app's own
  // defaults the "below NCAV" chip read 132 beside a table holding one of them,
  // and "judged on all 6" read 4,393 against 896. A count that describes a
  // universe the reader cannot see is not a count of anything they can act on.
  const positiveEpsCounts = useMemo(() => Object.fromEntries(
    EPS_POSITIVE_FLOORS.map((floor) => [floor, view.filter((r) => r.eps10?.positive >= floor).length])
  ), [view]);
  const naCount = useMemo(() => view.filter((r) => r.unjudged).length, [view]);
  const netNetCount = useMemo(() => view.filter((r) => r.netNet).length, [view]);
  const noApplyCount = useMemo(() => view.filter((r) => r.inapplicable).length, [view]);
  const portfolioMatches = useMemo(() =>
    (portfolioData?.positions ?? []).filter((position) => matchesPortfolio(position, portfolioQ)).length,
  [portfolioData, portfolioQ]);

  const metCounts = useMemo(() => {
    const c = {};
    view.forEach((r) => {
      for (let n = 1; n <= r.n_pass; n++) c[n] = (c[n] ?? 0) + 1;
    });
    return c;
  }, [view]);

  const sectorCounts = useMemo(() => {
    const c = {};
    rows.forEach((r) => {
      const k = r.sector ?? "Unclassified";
      c[k] = (c[k] ?? 0) + 1;
    });
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [rows]);
  const profileCounts = useMemo(() => {
    const c = {};
    rows.forEach((r) => (c[r.profile] = (c[r.profile] ?? 0) + 1));
    return Object.entries(c).sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);
  const exchanges = useMemo(() => {
    const c = {};
    rows.forEach((r) => r.exchange && (c[r.exchange] = (c[r.exchange] ?? 0) + 1));
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [rows]);
  const indexCounts = useMemo(() => {
    const c = { Outside: 0 };
    rows.forEach((r) => {
      if (!r.idx.length) c.Outside += 1;
      r.idx.forEach((m) => (c[m] = (c[m] ?? 0) + 1));
    });
    return Object.entries(c)
      .sort((a, b) => (INDEX_RANK[a[0]] ?? 9) - (INDEX_RANK[b[0]] ?? 9));
  }, [rows]);

  // a search that hits nothing inside the active filters, but matches elsewhere,
  // must say so rather than showing an empty table
  const matchesAnywhere = useMemo(() => {
    const match = matcher(q);
    return match ? match(rows).length : 0;
  }, [rows, q]);


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

  const sortBy = (key, additive) => setSort((current) => updateSort(current, key, additive));
  const recordTrade = (row) => setTradeTarget(row ?? {});

  if (page === "portfolio") return (
    <div className="app">
      <AppHeader page={page} onNavigate={navigate} rows={rows} data={data}
                 portfolioData={portfolioData} portfolioQ={portfolioQ}
                 setPortfolioQ={setPortfolioQ} portfolioMatches={portfolioMatches} />
      <LoadBar onFinished={() => { load(); loadPortfolio(); }} shown={rows.length} />
      <Portfolio data={portfolioData} loading={portfolioLoading} error={portfolioError}
                 query={portfolioQ}
                 onRefresh={() => { load(); loadPortfolio(); }}
                 onRecordTrade={recordTrade} onDeleteTrade={deleteTrade} />
      {tradeTarget !== null && portfolioData && (
        <TradeModal portfolio={portfolioData.portfolio} rows={rows}
                    initialRow={tradeTarget.cik ? tradeTarget : null}
                    onClose={() => setTradeTarget(null)}
                    onSaved={(next) => { setPortfolioData(next); setTradeTarget(null); loadPortfolio(); }} />
      )}
    </div>
  );

  return (
    <div className="app">
      <AppHeader page={page} onNavigate={navigate} rows={rows} data={data}
                 portfolioData={portfolioData} q={q} setQ={setQ} matches={view.length} />

      <section className="index-valuation" aria-labelledby="sp500-valuation-title">
        <div className="index-valuation-intro">
          <span className="index-valuation-kicker">Market reference</span>
          <h2 id="sp500-valuation-title">S&amp;P 500 valuation</h2>
          <p>
            {sp500.members.toLocaleString()} index members in this dashboard · full cohort,
            unaffected by the filters below
          </p>
        </div>
        <div className="index-valuation-metric">
          <span>Median P/E</span>
          <strong>{fmtMultiple(sp500.pe.median)}</strong>
          <small>{sp500.pe.count.toLocaleString()} companies with a valid positive TTM P/E</small>
        </div>
        <div className="index-valuation-metric">
          <span>Median P/E3</span>
          <strong>{fmtMultiple(sp500.pe3.median)}</strong>
          <small>{sp500.pe3.count.toLocaleString()} companies · price / 3-year average EPS</small>
        </div>
        <p className="index-valuation-note">
          Missing and non-positive multiples are excluded from each median, never counted as zero.
        </p>
      </section>

      <LoadBar onFinished={load} shown={rows.length} />

      {trackingError && <div className="msg err">{trackingError}</div>}

      <div className="filters graham-controls">
        <select className="mincap lens" value={lens} onChange={(e) => setLens(e.target.value)}
                title="Choose which Graham framework to use for the alignment view and ranking.">
          <option value="BOTH">Graham lens: Both</option>
          <option value="ENTERPRISING">Graham lens: Enterprising</option>
          <option value="DEFENSIVE">Graham lens: Defensive</option>
        </select>
        {lens === "ENTERPRISING" && <select className="mincap lens" value={gaps} onChange={(e) => setGaps(e.target.value)}
          title="A research filter for operating companies only. It counts measured gaps in the six direct Enterprising tests.">
          <option value="ALL">Any Enterprising gaps</option>
          <option value="ALL_PASS">All 6 direct tests</option>
          <option value="ONE_GAP">One measured gap</option>
          <option value="TWO_GAPS">Two measured gaps</option>
          <option value="INCOMPLETE">Incomplete evidence</option>
        </select>}
        <select className="mincap lens" value={fit} onChange={(e) => setFit(e.target.value)}
                title="Filter by the selected framework's alignment status. Under Both, a company is kept if either framework has that status.">
          <option value="ALL">Any alignment evidence</option>
          <option value="ALIGNED">Aligned only</option>
          <option value="EVIDENCE_INCOMPLETE">Evidence incomplete</option>
          <option value="BLOCKED">Blocked by a measured test</option>
        </select>
        <MultiSelect label="Applicability" options={profileCounts} selected={profiles} onChange={setProfiles}
          formatName={(profile) => PROFILE_NAMES[profile] ?? profile}
          renderOption={(profile) => PROFILE_NAMES[profile] ?? profile} />
        <MultiSelect label="Sector" options={sectorCounts} selected={sectors_} onChange={setSectors} />
        <MultiSelect label="Exchange" options={exchanges} selected={venues} onChange={setVenues} />
        <MultiSelect label="Index" options={indexCounts} selected={idxSel} onChange={setIdxSel} />
        <select className="mincap" value={minMet} onChange={(e) => setMinMet(Number(e.target.value))}>
          <option value={0}>Any criteria met</option>
          {[...Array(4)].map((_, i) => TOTAL_CRITERIA - i).map((n) => (
            <option key={n} value={n}>
              {n}/{TOTAL_CRITERIA} and above{metCounts[n] ? ` (${metCounts[n].toLocaleString()})` : ""}
            </option>
          ))}
        </select>
        <select className="mincap" value={minPositiveEps} onChange={(e) => setMinPositiveEps(Number(e.target.value))}
                title="Keeps companies with at least the chosen count of positive annual EPS observations in the completed FY(L-9)..FY(L) window. Missing years do not count as positive.">
          <option value={0}>Any 10Y positive EPS count</option>
          {EPS_POSITIVE_FLOORS.map((floor) => (
            <option key={floor} value={floor}>
              {floor}+ positive EPS years{positiveEpsCounts[floor] ? ` (${positiveEpsCounts[floor].toLocaleString()})` : ""}
            </option>
          ))}
        </select>
        <select className="mincap" value={minRoic} onChange={(e) => setMinRoic(Number(e.target.value))}
                title="Reported earnings plus D&A less total capital expenditure, divided by invested capital. This is a conservative floor, not definitive Buffett owner earnings.">
          <option value={0}>Any all-capex return</option>
          <option value={15}>15%+ all-capex return</option>
          <option value={10}>10%+ all-capex return</option>
          <option value={6}>6%+ all-capex return</option>
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
        {(lens !== "BOTH" || fit !== "ALL" || gaps !== "ALL" || profiles.size > 0 || sectors_.size > 0 || venues.size > 0 || idxSel.size > 0 || minMet > 0 || minPositiveEps > 0 || minRoic > 0 || hideNA || !hideNoApply || belowNcav) && (
          <button className="chip clear" onClick={() => {
            setLens("BOTH"); setFit("ALL"); setGaps("ALL"); setProfiles(new Set()); setSectors(new Set()); setVenues(new Set()); setIdxSel(new Set()); setMinMet(0); setMinPositiveEps(0); setMinRoic(0); setHideNA(false); setHideNoApply(true); setBelowNcav(false);
          }}>clear all</button>
        )}
        <span className="showing">
          showing {view.length.toLocaleString()} of {rows.length.toLocaleString()}
        </span>
        <span className="sort-help">Shift-click headers to add sort</span>
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th className="starcol"></th>
            <Th id="ticker" sort={sort} onSort={sortBy}>Ticker</Th>
            <Th id="name" sort={sort} onSort={sortBy}>Company</Th>
            <Th id="sector" sort={sort} onSort={sortBy}>Sector</Th>
            <Th id="fit" sort={sort} onSort={sortBy}>Graham fit<em className="sub2">E · D</em></Th>
            <Th id="index" sort={sort} onSort={sortBy}>Index</Th>
            <Th id="eps10" sort={sort} onSort={sortBy}>10Y EPS evidence<em className="sub2">positive years · growth</em></Th>
            <Th id="mcap" sort={sort} onSort={sortBy} className="num">Mkt cap</Th>
            <Th id="price" sort={sort} onSort={sortBy} className="num">Price</Th>
            <Th id="offhigh" sort={sort} onSort={sortBy} className="num">
              Off high<em className="sub2">52w · 3y</em>
            </Th>
            <Th id="pe" sort={sort} onSort={sortBy} className="num">P/E</Th>
            <Th id="pe3" sort={sort} onSort={sortBy} className="num">
              P/E 3y<em className="sub2">avg EPS</em>
            </Th>
            <Th id="roic" sort={sort} onSort={sortBy} className="num">
              All-capex return<em className="sub2">floor · not definitive OE</em>
            </Th>
            <Th id="pncav" sort={sort} onSort={sortBy} className="num">P/NCAV</Th>
          </tr>
        </thead>
        <tbody>
          {view.slice(0, 300).map((r) => (
            <tr key={r.cik} onClick={() => setSelected(r)}
                className={`${tracked.has(r.cik) ? "istracked" : ""}${portfolioCiks.has(r.cik) ? " inportfolio" : ""}`.trim()}>
              <td className="starcol" data-label="">
                <button className={`star-btn ${tracked.has(r.cik) ? "on" : ""}`}
                        title={tracked.has(r.cik) ? "Remove from tracked" : "Track this company"}
                        onClick={(e) => toggleTracked(r, e)}>
                  {tracked.has(r.cik) ? "★" : "☆"}
                </button>
              </td>
              <td className="tick" data-label="Ticker">
                {r.ticker}
                {portfolioCiks.has(r.cik) && (
                  <span className="portfolio-mark" title="Open position in your portfolio"
                        aria-label="In portfolio">◆</span>
                )}
                {r.netNet && (
                  <span className="netnetmark" title="trading at or below net current asset value">
                    net-net
                  </span>
                )}
                {r.prose_gaps?.length > 0 && (
                  <span className="verifymark"
                        title={`Some data cannot be extracted and must be read in the filing:\n\n`
                               + r.prose_gaps.map((g) => `• ${g.what}\n  affects ${g.affects}`).join("\n\n")}>
                    check filing
                  </span>
                )}
                {r.warnings.length > 0 && (
                  <span className="warningmark"
                        title={r.warnings.map((warning) => `${warning.kind}: ${warning.text}`).join("\n\n")}>
                    data warning
                  </span>
                )}
              </td>
              <td className="name" data-label="Company">{r.name}</td>
              <td className="sector" data-label="Sector" title={r.industry ?? ""}>
                <span className={`profile-mini ${r.profile.toLowerCase()}`}>{r.graham_profile_meta?.short ?? r.profile}</span>
                <span className="sector-name">{r.sector ?? "Unclassified"}</span>
                {r.exchange === "OTC" && <span className="otc">OTC</span>}
              </td>
              <td data-label="Graham fit"><AlignmentCompact row={r} /></td>
              <td className="idxcell" data-label="Index" title={r.idx.join(" · ") || "not in a tracked index"}>
                {r.idx.length
                  ? r.idx.map((m) => <span key={m} className="idxbadge">{INDEX_SHORT[m] ?? m}</span>)
                  : <span className="dim">—</span>}
              </td>
              <td data-label="10Y EPS evidence"><EarningsEvidence annual={r.annual_eps} /></td>
              <td className="num" data-label="Mkt cap">{fmtCap(r.mcap)}</td>
              <td className="num" data-label="Price" title={quoteTitle(r)}>
                {fmtPrice(r.price)}
                {r.price != null && <small className={`quote-session ${quoteTone(r)}`}>{quoteStatus(r)}</small>}
              </td>
              <td className="num offhigh" data-label="Off high" title={drawdownTitle(r)}>
                {r.price_stats?.pct_below_52w_high == null ? (
                  <span className="dim">—</span>
                ) : (
                  <>
                    <b>{below(r.price_stats.pct_below_52w_high)}</b>
                    <span className="dim"> · {below(r.price_stats.pct_below_3y_high)}</span>
                  </>
                )}
              </td>
              <td className="num" data-label="P/E">{fmt(byN(r, 1).value)}</td>
              <td className="num" data-label="P/E 3y"
                  title="current price over the average of the three latest annual EPS — one lucky or disastrous year moves it a third as much as it moves the TTM P/E">
                {fmt(r.pe3)}
              </td>
              <td className="num" data-label="All-capex return"
                  title="reported earnings + depreciation and amortisation − total capital expenditure, over invested capital. Growth capex is deducted, so this is a floor rather than definitive Buffett owner earnings">
                {r.roic == null ? "—" : `${r.roic.toFixed(1)}%`}
              </td>
              <td className={`num${r.pncav != null && r.pncav <= 2 / 3 ? " ok" : ""}`} data-label="P/NCAV"
                  title="price over net current asset value per share — current assets less every liability, fixed assets counted as nothing. Graham's hardest bargain is a price under two-thirds of it; blank where net current assets are not positive">
                {r.pncav == null ? "—" : `${r.pncav.toFixed(2)}×`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {view.length === 0 && matchesAnywhere > 0 && (
        <p className="msg">
          No match inside the current filters, but <b>{matchesAnywhere.toLocaleString()}</b>{" "}
          elsewhere.{" "}
          <button className="linkish" onClick={() => { setGaps("ALL"); setSectors(new Set()); setVenues(new Set()); }}>
            search everything
          </button>
        </p>
      )}
      {view.length === 0 && matchesAnywhere === 0 && q.trim() && (
        <p className="msg dim">Nothing matches “{q.trim()}”.</p>
      )}
      {view.length > 300 && <p className="msg dim">First 300 shown — narrow the filter to see more.</p>}

      {selected && <Detail row={selected} onClose={() => setSelected(null)}
                           tracked={tracked.has(selected.cik)}
                           onToggleTracked={() => toggleTracked(selected)}
                           onRecordTrade={() => recordTrade(selected)} />}
      {tradeTarget !== null && portfolioData && (
        <TradeModal portfolio={portfolioData.portfolio} rows={rows}
                    initialRow={tradeTarget.cik ? tradeTarget : null}
                    onClose={() => setTradeTarget(null)}
                    onSaved={(next) => { setPortfolioData(next); setTradeTarget(null); }} />
      )}
    </div>
  );
}

function AppHeader({ page, onNavigate, rows, data, portfolioData, q, setQ, matches,
                     portfolioQ, setPortfolioQ, portfolioMatches }) {
  const searchValue = page === "portfolio" ? portfolioQ : q;
  const setSearch = page === "portfolio" ? setPortfolioQ : setQ;
  const searchMatches = page === "portfolio" ? portfolioMatches : matches;
  return (
    <header className="app-header">
      <div>
        <h1>Graham Screener</h1>
        <p className="sub">
          {page === "portfolio"
            ? `${portfolioData?.summary?.positions ?? 0} positions · cost basis and decision evidence`
            : `${rows.length.toLocaleString()} companies · enterprising and defensive evidence · engine v${data.engine_version}`}
        </p>
        <nav className="app-nav" aria-label="Primary views">
          <button className={page === "screener" ? "active" : ""} onClick={() => onNavigate("screener")}>Research</button>
          <button className={page === "portfolio" ? "active" : ""} onClick={() => onNavigate("portfolio")}>
            Portfolio <span>{portfolioData?.summary?.positions ?? 0}</span>
          </button>
        </nav>
      </div>
      <div className="searchwrap">
        <input className="search" placeholder={page === "portfolio" ? "Search portfolio…" : "Search…"}
               value={searchValue ?? ""}
               onChange={(event) => setSearch(event.target.value)} />
        {(searchValue ?? "").trim() && <span className="searchhint">
          {(searchMatches ?? 0).toLocaleString()} match{searchMatches === 1 ? "" : "es"}
        </span>}
      </div>
    </header>
  );
}

const fmt = (v) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 }));
const fmtMultiple = (v) => (v == null ? "—" : `${v.toLocaleString(undefined, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})}×`);

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
    `${p.pct_vs_3y_average >= 0 ? "+" : ""}${p.pct_vs_3y_average}% versus the 3-year average (${fmtPrice(p.average_3y)})`,
    `${p.price_to_3y_median}× the 3-year median price`,
    "\nweekly closing prices — a high here is the best weekly close, not an intraday spike",
  ].join("\n");
}

const fmtCap = (v) => {
  if (!v) return "—";
  for (const [d, s] of [[1e12, "T"], [1e9, "B"], [1e6, "M"]])
    if (v >= d) return `$${(v / d).toFixed(v / d < 10 ? 1 : 0)}${s}`;
  return `$${(v / 1e3).toFixed(0)}K`;
};
