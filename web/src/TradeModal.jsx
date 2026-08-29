import { useEffect, useMemo, useState } from "react";
import { send } from "./api.js";
import { quoteStatus } from "./quote.js";


function localInputNow() {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}


export default function TradeModal({ portfolio, rows, initialRow, onClose, onSaved }) {
  const available = useMemo(
    () => [...rows].filter((row) => row.cik && row.ticker)
      .sort((a, b) => a.ticker.localeCompare(b.ticker)),
    [rows],
  );
  const [cik, setCik] = useState(initialRow?.cik ?? available[0]?.cik ?? "");
  const selected = available.find((row) => row.cik === cik);
  const [side, setSide] = useState("BUY");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState(initialRow?.price?.toString() ?? "");
  const [fees, setFees] = useState("1");
  const [executedAt, setExecutedAt] = useState(localInputNow);
  const [broker, setBroker] = useState("IBKR");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (initialRow) {
      setCik(initialRow.cik);
      setPrice(initialRow.price?.toString() ?? "");
    }
  }, [initialRow]);

  useEffect(() => {
    const esc = (event) => event.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, saving]);

  const selectTicker = (value) => {
    setCik(value);
    const row = available.find((candidate) => candidate.cik === value);
    if (row?.price != null) setPrice(row.price.toString());
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const response = await send(`/portfolio/${portfolio.id}/trades`, {
        body: {
          cik,
          side,
          quantity,
          price,
          fees,
          currency: portfolio.base_currency,
          executed_at: new Date(executedAt).toISOString(),
          broker: broker.trim() || null,
          account_label: portfolio.name,
          note: note.trim() || null,
        },
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.portfolio)
        throw new Error(result?.detail ?? `HTTP ${response.status}: trade was not saved`);
      onSaved(result.portfolio);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <>
      <div className="scrim trade-scrim" onClick={() => !saving && onClose()} />
      <aside className="trade-modal" aria-label="Record portfolio trade">
        <button className="close-btn" onClick={onClose} disabled={saving} aria-label="Close trade form">×</button>
        <h2>Record trade</h2>
        <p className="sub">
          {portfolio.name} · the current screen and the valuation at your fill price will be saved permanently
        </p>
        <form className="trade-form" onSubmit={submit}>
          <label>
            Ticker
            <select value={cik} onChange={(event) => selectTicker(event.target.value)}>
              {available.map((row) => (
                <option key={row.cik} value={row.cik}>{row.ticker} — {row.name}</option>
              ))}
            </select>
          </label>
          <label>
            Action
            <select value={side} onChange={(event) => setSide(event.target.value)}>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
            </select>
          </label>
          <label>
            Quantity
            <input type="number" min="0" step="any" required value={quantity}
                   onChange={(event) => setQuantity(event.target.value)} />
          </label>
          <label>
            Fill price ({portfolio.base_currency})
            <input type="number" min="0" step="any" required value={price}
                   onChange={(event) => setPrice(event.target.value)} />
            {selected?.price_asof && <small>{quoteStatus(selected)} · screen quote dated {dateTime(selected.price_asof)}</small>}
          </label>
          <label>
            Commission and fees
            <input type="number" min="0" step="any" required value={fees}
                   onChange={(event) => setFees(event.target.value)} />
          </label>
          <label>
            Executed at
            <input type="datetime-local" required value={executedAt}
                   onChange={(event) => setExecutedAt(event.target.value)} />
          </label>
          <label>
            Broker
            <input value={broker} onChange={(event) => setBroker(event.target.value)} />
          </label>
          <label className="wide">
            Note <span>(optional)</span>
            <input value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
          {error && <p className="trade-error">{error}</p>}
          <div className="trade-actions wide">
            <button type="button" onClick={onClose} disabled={saving}>Cancel</button>
            <button className="primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : `Record ${side.toLowerCase()}`}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}


const dateTime = (value) => new Date(value).toLocaleString(undefined, {
  dateStyle: "medium", timeStyle: "short",
});
