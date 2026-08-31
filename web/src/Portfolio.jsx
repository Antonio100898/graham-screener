import { useEffect, useMemo, useState } from "react";
import { compareRows, normalizeSort, updateSort } from "./sort.js";
import { matchesPortfolio, matchesPortfolioAsset, reviewChanges } from "./portfolio.js";
import { quoteStatus, quoteTitle as marketQuoteTitle, quoteTone } from "./quote.js";
import { send } from "./api.js";
import AssetModal from "./AssetModal.jsx";


const CRITERIA = {
  1: "Earnings valuation",
  2: "Liquidity",
  3: "Debt",
  4: "Earnings stability",
  5: "Dividend",
  7: "Tangible assets",
};

const MULTIPLES = [
  ["P/E", "pe", multiple],
  ["P/E3", "pe3", multiple],
  ["P/B", "pb", multiple],
  ["P/TBV", "ptbv", multiple],
  ["P/NCAV", "pncav", multiple],
  ["Recurring yield", "recurring_dividend_yield", percent],
  ["All-capex floor yield", "all_capex_floor_yield", percent],
  ["Maintenance≈D&A estimate yield", "maintenance_estimate_yield", percent],
  ["Free cash flow yield", "free_cash_flow_yield", percent],
];


function SortTh({ id, sort, onSort, children, className = "" }) {
  const priority = sort.findIndex((item) => item.key === id);
  const active = priority >= 0;
  const direction = active ? sort[priority].dir : 1;
  return (
    <th className={`${className} sortable ${active ? "sorted" : ""}`}
        onClick={(event) => onSort(id, event.shiftKey)}
        title="Click for primary sort; Shift-click to add or toggle another column">
      {children}<span className="arrow">{active ? (direction === 1 ? "▲" : "▼") : "↕"}</span>
      {active && sort.length > 1 && <span className="sort-priority">{priority + 1}</span>}
    </th>
  );
}


export default function Portfolio({ data, loading, error, query = "", onRecordTrade,
                                    onDeleteTrade, onDataChange }) {
  const [sort, setSort] = useState([{ key: "ticker", dir: 1 }]);
  const [selectedCik, setSelectedCik] = useState(null);
  const [tab, setTab] = useState("stocks");
  const [assetEditor, setAssetEditor] = useState(null);
  const [assetError, setAssetError] = useState(null);
  const selected = data?.positions.find((position) => position.cik === selectedCik) ?? null;
  const sorted = useMemo(() => {
    if (!data) return [];
    const value = (position, key) => {
      if (key === "ticker") return position.ticker;
      if (key === "quantity") return position.quantity;
      if (key === "cost") return position.cost_basis;
      if (key === "price") return position.current_price;
      if (key === "value") return position.market_value;
      if (key === "pnl") return position.unrealized_pnl;
      if (key === "pnl_pct") return position.unrealized_pnl_pct;
      if (key === "weight") return position.portfolio_weight_pct;
      if (key === "review") return -reviewChanges(position).length;
      if (key === "pe") return position.current_valuation?.pe;
      return null;
    };
    return data.positions.filter((position) => matchesPortfolio(position, query))
      .sort((a, b) => compareRows(a, b, sort, value));
  }, [data, query, sort]);

  if (loading && !data) return <div className="portfolio-empty">Loading portfolio…</div>;
  if (error && !data) return <div className="portfolio-empty err">Portfolio could not be loaded: {error}</div>;
  if (!data) return null;
  const summary = data.summary;
  const bonds = data.assets?.bonds ?? [];
  const crypto = data.assets?.crypto ?? [];
  const manualAssets = tab === "bonds" ? bonds : crypto;
  const filteredManualAssets = manualAssets.filter((asset) => matchesPortfolioAsset(asset, query));
  const quoteFailures = data.positions
    .filter((position) => position.quote_refresh_warning)
    .map((position) => position.ticker);
  const sortBy = (key, additive) => setSort((current) => updateSort(current, key, additive));
  const chooseTab = (next) => {
    setTab(next);
    setSelectedCik(null);
    setAssetError(null);
  };
  const openAssetEditor = (asset = null) => setAssetEditor({
    assetType: tab === "bonds" ? "BOND" : "CRYPTO",
    asset,
  });
  const deleteAsset = async (asset) => {
    const description = asset.symbol ? `${asset.symbol} — ${asset.name}` : asset.name;
    if (!window.confirm(`Delete ${description}?\n\nThis removes the manual holding and cannot be undone.`)) return;
    setAssetError(null);
    try {
      const response = await send(`/portfolio/${data.portfolio.id}/assets/${asset.id}`, {
        method: "DELETE",
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.portfolio)
        throw new Error(result?.detail ?? `HTTP ${response.status}: holding was not deleted`);
      onDataChange(result.portfolio);
    } catch (err) {
      setAssetError(err.message);
    }
  };
  const primaryAction = tab === "stocks"
    ? () => onRecordTrade(null)
    : () => openAssetEditor();
  const primaryLabel = tab === "stocks" ? "Record trade" : `Add ${tab === "bonds" ? "bond" : "crypto"}`;
  const totalUnavailable = summary.total_assets == null;
  const totalNote = summary.unpriced_stock_positions > 0
    ? `${summary.unpriced_stock_positions} stock quote${summary.unpriced_stock_positions === 1 ? "" : "s"} unavailable`
    : summary.liquid_cash == null ? "enter liquid cash to complete" : "all entered assets";

  return (
    <section className="portfolio-page">
      <div className="portfolio-titlebar">
        <div>
          <span className="index-valuation-kicker">Personal ledger</span>
          <h2>{data.portfolio.name} portfolio</h2>
          <p>One view of stocks, bonds, crypto and money available to invest</p>
        </div>
        <div className="portfolio-actions">
          <button className="primary" onClick={primaryAction}>{primaryLabel}</button>
        </div>
      </div>

      {error && <p className="portfolio-inline-error">Refresh failed: {error}</p>}
      {quoteFailures.length > 0 && (
        <p className="portfolio-inline-error">
          Hourly quote unavailable for {quoteFailures.join(", ")}; each dated previous quote remains in use when available.
        </p>
      )}

      <div className="portfolio-summary asset-summary">
        <Summary label="Total assets" value={money(summary.total_assets, data.portfolio.base_currency)}
                 sub={totalUnavailable ? totalNote : `${summary.holdings} holding${summary.holdings === 1 ? "" : "s"}`} />
        <Summary label="Invested" value={money(summary.invested_assets, data.portfolio.base_currency)}
                 sub="stocks + bonds + crypto" />
        <Summary label="Stocks" value={money(summary.stock_value, data.portfolio.base_currency)}
                 sub={`${summary.positions} position${summary.positions === 1 ? "" : "s"}`} />
        <Summary label="Bonds" value={money(summary.bond_value, data.portfolio.base_currency)}
                 sub={`${bonds.length} manual holding${bonds.length === 1 ? "" : "s"}`} />
        <Summary label="Crypto" value={money(summary.crypto_value, data.portfolio.base_currency)}
                 sub={`${crypto.length} live holding${crypto.length === 1 ? "" : "s"}`} />
        <CashSummary data={data} onSaved={onDataChange} />
      </div>

      <Allocation allocation={data.allocation ?? []} currency={data.portfolio.base_currency}
                  total={summary.total_assets} />

      <div className="portfolio-tabs" role="tablist" aria-label="Portfolio asset types">
        <button role="tab" aria-selected={tab === "stocks"} className={tab === "stocks" ? "active" : ""}
                onClick={() => chooseTab("stocks")}>Stocks <span>{summary.positions}</span></button>
        <button role="tab" aria-selected={tab === "bonds"} className={tab === "bonds" ? "active" : ""}
                onClick={() => chooseTab("bonds")}>Bonds <span>{bonds.length}</span></button>
        <button role="tab" aria-selected={tab === "crypto"} className={tab === "crypto" ? "active" : ""}
                onClick={() => chooseTab("crypto")}>Crypto <span>{crypto.length}</span></button>
      </div>

      {tab === "stocks" ? <>
        <div className="portfolio-summary stock-summary">
          <Summary label="Positions" value={summary.positions.toLocaleString()} />
          <Summary label="Cost basis" value={money(summary.cost_basis)} sub="buy fees included" />
          <Summary label="Value at quotes" value={money(summary.market_value)} />
          <Summary label="P&L at quotes" value={moneySigned(summary.unrealized_pnl)}
                   sub={percentSigned(summary.unrealized_pnl_pct)} tone={tone(summary.unrealized_pnl)} />
          <Summary label="Realised P&L" value={moneySigned(summary.realized_pnl)} tone={tone(summary.realized_pnl)} />
          <Summary label="Fees paid" value={money(summary.fees)} />
        </div>

        {summary.pre_trade_quotes > 0 && (
          <div className="portfolio-quote-warning" role="status">
            <b>{summary.pre_trade_quotes} quote{summary.pre_trade_quotes === 1 ? "" : "s"} predate the latest trade.</b>
            {" "}Their values and P&amp;L are reference amounts, not post-purchase performance;
            price-dependent exit signals stay pending until the hourly update or <b>Refresh prices</b> rebuilds the shared dashboard with a newer RTH or extended-hours quote.
          </div>
        )}

        {sorted.length === 0 ? (
          <div className="portfolio-empty">
            {data.positions.length === 0
              ? "No stock positions yet. Record a buy to preserve its fill, fees, criteria and valuation snapshot."
              : `No stock position matches “${query.trim()}”.`}
          </div>
        ) : (
          <>
            <div className="portfolio-table-note">
              <span>{sorted.length}{query.trim() ? ` of ${data.positions.length}` : ""} open positions</span>
              <span>Shift-click headers to add sort</span>
            </div>
            <div className="portfolio-table-scroll">
              <table className="grid portfolio-grid">
                <thead><tr>
                  <SortTh id="ticker" sort={sort} onSort={sortBy}>Ticker</SortTh>
                  <SortTh id="quantity" sort={sort} onSort={sortBy} className="num">Shares</SortTh>
                  <SortTh id="cost" sort={sort} onSort={sortBy} className="num">Cost basis<em className="sub2">avg cost</em></SortTh>
                  <SortTh id="price" sort={sort} onSort={sortBy} className="num">Price<em className="sub2">entry → latest</em></SortTh>
                  <SortTh id="value" sort={sort} onSort={sortBy} className="num">Value</SortTh>
                  <SortTh id="pnl" sort={sort} onSort={sortBy} className="num">P&amp;L</SortTh>
                  <SortTh id="pnl_pct" sort={sort} onSort={sortBy} className="num">Return</SortTh>
                  <SortTh id="weight" sort={sort} onSort={sortBy} className="num">Portfolio weight</SortTh>
                  <SortTh id="pe" sort={sort} onSort={sortBy} className="num">P/E<em className="sub2">entry → latest</em></SortTh>
                  <th>Graham fit<em className="sub2">entry → latest</em></th>
                  <SortTh id="review" sort={sort} onSort={sortBy}>Review</SortTh>
                </tr></thead>
                <tbody>{sorted.map((position) => {
                  const reviews = reviewChanges(position);
                  const quotePending = position.quote_after_latest_trade === false;
                  return (
                    <tr key={position.cik} onClick={() => setSelectedCik(position.cik)}>
                      <td className="tick" data-label="Ticker">
                        {position.ticker}<small>{position.name}</small>
                      </td>
                      <td className="num" data-label="Shares">{number(position.quantity)}</td>
                      <td className="num" data-label="Cost basis">
                        <b>{money(position.cost_basis)}</b><small>{money(position.average_cost)} / share</small>
                      </td>
                      <td className="num" data-label="Price" title={quoteTitle(position)}>
                        <span className="pair">{money(position.average_entry_price)} → <b>{money(position.current_price)}</b></span>
                        <small className={`quote-session ${quoteTone(position)}`}>{quoteStatus(position)}</small>
                        {quotePending && <small className="quote-pending">pre-trade quote</small>}
                      </td>
                      <td className="num" data-label="Value">{money(position.market_value)}</td>
                      <td className="num" data-label="P&L">{moneySigned(position.unrealized_pnl)}</td>
                      <td className="num" data-label="Return">{percentSigned(position.unrealized_pnl_pct)}</td>
                      <td className="num" data-label="Portfolio weight">{percent(position.portfolio_weight_pct)}</td>
                      <td className="num" data-label="P/E">
                        <span className="pair">{multiple(position.entry_valuation?.pe)} → <b>{multiple(position.current_valuation?.pe)}</b></span>
                      </td>
                      <td data-label="Graham fit"><FitPair entry={position.entry_alignment} current={position.current_alignment} /></td>
                      <td data-label="Review">
                        {reviews.length ? <span className="review-badge">{reviews.length} deterioration{reviews.length === 1 ? "" : "s"}</span>
                          : quotePending ? <span className="pending-badge">New quote needed</span>
                            : <span className="stable-badge">No PASS→FAIL</span>}
                      </td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          </>
        )}
      </> : <ManualAssetsTab type={tab} assets={manualAssets} filtered={filteredManualAssets}
                              query={query} currency={data.portfolio.base_currency}
                              error={assetError} onAdd={() => openAssetEditor()}
                              onEdit={openAssetEditor} onDelete={deleteAsset} />}

      {selected && <PositionDetail position={selected} onClose={() => setSelectedCik(null)}
                                   onRecordTrade={() => onRecordTrade({ cik: selected.cik, ticker: selected.ticker, price: selected.current_price })}
                                   onDeleteTrade={onDeleteTrade} />}
      {assetEditor && <AssetModal portfolio={data.portfolio} assetType={assetEditor.assetType}
                                  asset={assetEditor.asset} onClose={() => setAssetEditor(null)}
                                  onSaved={(next) => { onDataChange(next); setAssetEditor(null); setAssetError(null); }} />}
    </section>
  );
}


function Summary({ label, value, sub, tone: toneClass = "" }) {
  return <div><span>{label}</span><strong className={toneClass}>{value}</strong>{sub && <small>{sub}</small>}</div>;
}


function CashSummary({ data, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(data.cash?.amount?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!editing) setAmount(data.cash?.amount?.toString() ?? "");
  }, [data.cash?.amount, editing]);

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const response = await send(`/portfolio/${data.portfolio.id}/cash`, {
        method: "PUT", body: { amount },
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.portfolio)
        throw new Error(result?.detail ?? `HTTP ${response.status}: cash balance was not saved`);
      onSaved(result.portfolio);
      setEditing(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return <div className="cash-summary-card">
    <span>Liquid cash</span>
    {editing ? <form onSubmit={save}>
      <input type="number" min="0" step="any" required autoFocus aria-label="Liquid cash amount"
             value={amount} onChange={(event) => setAmount(event.target.value)} />
      <button type="submit" disabled={saving}>{saving ? "…" : "Save"}</button>
      <button type="button" disabled={saving} onClick={() => { setEditing(false); setError(null); }}>Cancel</button>
    </form> : <>
      <strong>{data.cash?.amount == null ? "Not entered" : money(data.cash.amount, data.portfolio.base_currency)}</strong>
      <small>{data.cash?.updated_at ? `updated ${dateTime(data.cash.updated_at)}` : "available and not invested"}</small>
      <button className="cash-edit" onClick={() => setEditing(true)}>{data.cash?.amount == null ? "Enter cash" : "Update"}</button>
    </>}
    {error && <small className="negative">{error}</small>}
  </div>;
}


function Allocation({ allocation, currency, total }) {
  const available = total != null && Number(total) > 0;
  const unavailableNote = total == null
    ? "Complete cash and stock values to calculate percentages"
    : "Add a positive asset or cash value to calculate percentages";
  return <section className="allocation-panel" aria-label="Asset allocation">
    <div className="allocation-heading">
      <div><b>Asset allocation</b><small>Current value across every portfolio tab and liquid cash</small></div>
      {!available && <span>{unavailableNote}</span>}
    </div>
    <div className="allocation-rows">
      {allocation.map((item) => <div className="allocation-row" key={item.type}>
        <div className="allocation-row-label">
          <span>{item.label}</span>
          <small>{money(item.value, currency)}</small>
          <b>{item.weight_pct == null ? "—" : percent(item.weight_pct)}</b>
        </div>
        <div className="allocation-track" role="progressbar" aria-label={`${item.label} allocation`}
             aria-valuemin="0" aria-valuemax="100" aria-valuenow={item.weight_pct ?? 0}>
          <i className={item.type.toLowerCase()}
             style={{ width: `${available ? Math.max(0, Math.min(100, item.weight_pct ?? 0)) : 0}%` }} />
        </div>
      </div>)}
    </div>
  </section>;
}


function ManualAssetsTab({ type, assets, filtered, query, currency, error, onAdd, onEdit, onDelete }) {
  const singular = type === "bonds" ? "bond" : "crypto holding";
  const isCrypto = type === "crypto";
  return <section className="manual-assets-tab" role="tabpanel">
    <div className="manual-assets-heading">
      <div><b>{type === "bonds" ? "Bond holdings" : "Crypto holdings"}</b>
        <small>{isCrypto
          ? "Coinbase quotes refresh automatically every 30 seconds while this page is open."
          : "Current prices are entered manually and show when they were last updated."}</small></div>
      <button onClick={onAdd}>Add {singular}</button>
    </div>
    {error && <p className="portfolio-inline-error">Holding change failed: {error}</p>}
    {filtered.length === 0 ? <div className="portfolio-empty">
      {assets.length === 0
        ? `No ${type} yet. Add your first ${singular} to include it in total assets.`
        : `No ${singular} matches “${query.trim()}”.`}
    </div> : <div className="portfolio-table-scroll">
      <table className="grid manual-assets-grid">
        <thead><tr><th>Holding</th><th className="num">Quantity</th><th className="num">{isCrypto ? "Live unit price" : "Manual unit price"}</th>
          <th className="num">Current value</th><th className="num">Portfolio weight</th><th>{isCrypto ? "Quote time" : "Updated"}</th><th></th></tr></thead>
        <tbody>{filtered.map((asset) => <tr key={asset.id}>
          <td data-label="Holding"><b>{asset.symbol || asset.name}</b>
            {asset.symbol && <small>{asset.name}</small>}{asset.note && <small>{asset.note}</small>}</td>
          <td className="num" data-label="Quantity">{number(asset.quantity)}</td>
          <td className="num" data-label={isCrypto ? "Live unit price" : "Manual unit price"}>
            {money(asset.current_price, currency)}
            <small className={isCrypto && asset.price_live ? "positive" : ""}>
              {isCrypto ? (asset.price_live ? "Coinbase · live" : "saved fallback") : "manual"}
            </small>
          </td>
          <td className="num" data-label="Current value"><b>{money(asset.market_value, currency)}</b></td>
          <td className="num" data-label="Portfolio weight">{percent(asset.weight_pct)}</td>
          <td data-label={isCrypto ? "Quote time" : "Updated"}
              title={asset.quote_refresh_warning?.note}>{dateTime(asset.price_asof ?? asset.updated_at)}
            {asset.quote_refresh_warning && <small className="negative">refresh failed</small>}</td>
          <td className="manual-asset-actions" data-label="Actions">
            <div>
              <button onClick={() => onEdit(asset)}>Edit</button>
              <button className="delete" onClick={() => onDelete(asset)}>Delete</button>
            </div>
          </td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}


function FitPair({ entry, current }) {
  return <span className="fit-pair">{fit(entry)} <span>→</span> <b>{fit(current)}</b></span>;
}


function fit(alignment) {
  const e = alignment?.enterprising;
  const d = alignment?.defensive;
  if (!e && !d) return "—";
  const side = (label, value) => value ? `${label} ${value.passed}/${value.total}` : `${label} —`;
  return `${side("E", e)} · ${side("D", d)}`;
}


function PositionDetail({ position, onClose, onRecordTrade, onDeleteTrade }) {
  useEffect(() => {
    const esc = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const entryByN = Object.fromEntries(position.entry_criteria.map((criterion) => [criterion.n, criterion]));
  const currentByN = Object.fromEntries(position.current_criteria.map((criterion) => [criterion.n, criterion]));
  const reviews = reviewChanges(position);
  const decision = position.entry_snapshot;
  const quotePending = position.quote_after_latest_trade === false;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="detail clean-detail portfolio-detail">
        <button className="close-btn" onClick={onClose} aria-label="Close position details">×</button>
        <header className="detail-head">
          <div><h2>{position.ticker}</h2><p className="sub">{position.name}</p></div>
          <button className="trade-button" onClick={onRecordTrade}>Add buy / sell</button>
        </header>

        <div className="snapshot-grid position-snapshot">
          <Metric label="Shares" value={number(position.quantity)} />
          <Metric label="Average cost" sub="fees included" value={money(position.average_cost)} />
          <Metric label={quotePending ? "Reference price" : "Latest price"}
                  sub={`${quoteStatus(position)} · ${position.price_asof ? dateTime(position.price_asof) : "quote unavailable"}`}
                  value={money(position.current_price)} />
          <Metric label="Cost basis" value={money(position.cost_basis)} />
          <Metric label={quotePending ? "Reference value" : "Market value"} value={money(position.market_value)} />
          <Metric label={quotePending ? "Reference P&L" : "Unrealised P&L"} value={`${moneySigned(position.unrealized_pnl)} · ${percentSigned(position.unrealized_pnl_pct)}`} tone={tone(position.unrealized_pnl)} />
        </div>

        {quotePending && <div className="portfolio-quote-warning compact" role="status">
          <b>The latest screener quote predates this position's latest trade.</b> Values and P&amp;L below are a dated reference.
          Price-dependent PASS→FAIL changes are withheld from exit review until a newer quote is exported.
        </div>}

        <section className="criteria-section">
          <div className="criteria-title"><div><h3>Exit-review signals</h3>
            <p>A signal asks for review; Graham's entry tests are not an automatic sell rule.</p></div></div>
          {reviews.length ? (
            <ul className="review-list">{reviews.map((change) => (
              <li key={change.n} className={change.price_dependent ? "price" : "fundamental"}>
                <b>Criterion {change.n}: {CRITERIA[change.n]}</b>
                <span>PASS → FAIL · {change.price_dependent ? "price-dependent" : "filing/fundamental"}</span>
              </li>
            ))}</ul>
          ) : quotePending
            ? <p className="pending-callout">Price-dependent review is waiting for a post-trade quote.</p>
            : <p className="stable-callout">No criterion has deteriorated from PASS to FAIL.</p>}
        </section>

        <section className="criteria-section">
          <div className="criteria-title"><div><h3>Criteria at execution versus latest screen</h3>
            <p>Purchase values use the actual fill price; non-price evidence is the immutable decision snapshot.</p></div></div>
          <table className="criteria-clean portfolio-criteria">
            <thead><tr><th>Criterion</th><th>At execution</th><th>Latest screen</th><th>Change</th></tr></thead>
            <tbody>{[1, 2, 3, 4, 5, 7].map((n) => {
              const before = entryByN[n] ?? {};
              const after = currentByN[n] ?? {};
              const changed = before.status !== after.status;
              const preTradeValuation = quotePending && (n === 1 || n === 7);
              return <tr key={n}>
                <td><b>{n}. {CRITERIA[n]}</b></td>
                <td><Status value={before.status} /> <small>{criterionValue(before)}</small></td>
                <td><Status value={after.status} /> <small>{criterionValue(after)}</small></td>
                <td>{preTradeValuation ? <span className="dim">pre-trade reference</span>
                  : changed ? `${before.status ?? "—"} → ${after.status ?? "—"}`
                    : <span className="dim">unchanged</span>}</td>
              </tr>;
            })}</tbody>
          </table>
        </section>

        <section className="criteria-section">
          <div className="criteria-title"><div><h3>Valuation at execution versus latest screen</h3>
            <p>The execution column uses the broker fill, not the screener's displayed quote.</p></div></div>
          <table className="criteria-clean valuation-compare">
            <thead><tr><th>Multiple</th><th>At execution</th><th>Latest screen</th><th>Change</th></tr></thead>
            <tbody>{MULTIPLES.map(([label, key, format]) => {
              const before = position.entry_valuation?.[key];
              const after = position.current_valuation?.[key];
              return <tr key={key}><td><b>{label}</b></td><td className="num">{format(before)}</td>
                <td className="num">{format(after)}</td><td className="num">{delta(before, after, format)}</td></tr>;
            })}</tbody>
          </table>
          <p className="snapshot-meta">
            Decision captured {dateTime(decision?.captured_at)} · dashboard {dateTime(decision?.dashboard_generated)} · engine v{decision?.engine_version ?? "—"}
          </p>
        </section>

        <section className="criteria-section">
          <div className="criteria-title"><div><h3>Trade ledger</h3>
            <p>Fees are part of buy cost basis and reduce sell proceeds.</p></div></div>
          <div className="portfolio-table-scroll"><table className="criteria-clean trade-ledger">
            <thead><tr><th>Date</th><th>Side</th><th>Quantity</th><th>Price</th><th>Fee</th><th></th></tr></thead>
            <tbody>{[...position.trades].sort((a, b) => b.executed_at.localeCompare(a.executed_at)).map((trade) => (
              <tr key={trade.id}><td>{dateTime(trade.executed_at)}</td><td><b className={trade.side === "BUY" ? "positive" : "negative"}>{trade.side}</b></td>
                <td className="num">{number(trade.quantity)}</td><td className="num">{money(trade.price)}</td>
                <td className="num">{money(trade.fees)}</td><td className="num">
                  <button className="delete-trade" onClick={() => onDeleteTrade(trade)}>Delete</button>
                </td></tr>
            ))}</tbody>
          </table></div>
        </section>
      </aside>
    </>
  );
}


function Metric({ label, sub, value, tone: toneClass = "" }) {
  return <div className="metric"><span>{label}{sub && <em>{sub}</em>}</span><b className={toneClass}>{value}</b></div>;
}


function Status({ value }) {
  return <span className={`criterion-status ${String(value ?? "INSUFFICIENT_DATA").toLowerCase()}`}>{value ?? "UNKNOWN"}</span>;
}


function criterionValue(criterion) {
  if (criterion.value == null) return "";
  return criterion.n === 5 ? percent(criterion.value) : multiple(criterion.value);
}


function quoteTitle(position) {
  if (!position.price_asof) return "Screener quote unavailable";
  const prefix = position.quote_after_latest_trade === false ? "Pre-trade reference quote" : "Latest screener quote";
  return `${prefix} as of ${dateTime(position.price_asof)} · ${marketQuoteTitle(position)}`;
}


function delta(before, after, format) {
  if (!Number.isFinite(before) || !Number.isFinite(after)) return "—";
  const difference = after - before;
  return `${difference >= 0 ? "+" : ""}${format(difference)}`;
}


function tone(value) { return value > 0 ? "positive" : value < 0 ? "negative" : ""; }
function number(value) { return value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 }); }
function money(value, currency = "USD") { return value == null ? "—" : Number(value).toLocaleString(undefined, { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function moneySigned(value) { return value == null ? "—" : `${value > 0 ? "+" : ""}${money(value)}`; }
function percent(value) { return value == null ? "—" : `${number(value)}%`; }
function percentSigned(value) { return value == null ? "—" : `${value > 0 ? "+" : ""}${percent(value)}`; }
function multiple(value) { return value == null ? "—" : `${number(value)}×`; }
function dateTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
