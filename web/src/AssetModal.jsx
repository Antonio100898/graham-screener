import { useEffect, useMemo, useState } from "react";
import { fetchJson, send } from "./api.js";


export default function AssetModal({ portfolio, assetType, asset = null, onClose, onSaved }) {
  const isBond = assetType === "BOND";
  const label = isBond ? "bond" : "crypto holding";
  const [name, setName] = useState(asset?.name ?? "");
  const [symbol, setSymbol] = useState(asset?.symbol ?? "");
  const [quantity, setQuantity] = useState(asset?.quantity?.toString() ?? "");
  const [currentPrice, setCurrentPrice] = useState(asset?.current_price?.toString() ?? "");
  const [note, setNote] = useState(asset?.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [products, setProducts] = useState([]);
  const [productsLoading, setProductsLoading] = useState(!isBond);
  const [liveQuote, setLiveQuote] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [requestAttempt, setRequestAttempt] = useState(0);
  const marketValue = useMemo(() => {
    const value = Number(quantity) * Number(currentPrice);
    return quantity !== "" && currentPrice !== "" && Number.isFinite(value) ? value : null;
  }, [quantity, currentPrice]);

  useEffect(() => {
    const esc = (event) => event.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, saving]);

  useEffect(() => {
    if (isBond) return undefined;
    let active = true;
    setProductsLoading(true);
    fetchJson(`/crypto/products?currency=${encodeURIComponent(portfolio.base_currency)}`, {
      timeoutMs: 12_000,
    })
      .then((result) => {
        if (!active) return;
        const available = Array.isArray(result?.products) ? result.products : [];
        setProducts(available);
        const entered = String(asset?.symbol ?? symbol).toUpperCase();
        const selected = available.find((product) =>
          product.id === entered || product.symbol === entered);
        if (selected) {
          setSymbol(selected.id);
          setName(selected.name);
        }
        setError(null);
      })
      .catch((err) => active && setError(err.message))
      .finally(() => active && setProductsLoading(false));
    return () => { active = false; };
  }, [asset?.symbol, isBond, portfolio.base_currency, requestAttempt]);

  useEffect(() => {
    if (isBond || !symbol || productsLoading) return undefined;
    let active = true;
    const selected = products.find((product) => product.id === symbol.toUpperCase());
    if (!selected) {
      setLiveQuote(null);
      setQuoteLoading(false);
      return undefined;
    }
    setName(selected.name);
    setQuoteLoading(true);
    setLiveQuote(null);
    fetchJson(`/crypto/quote/${encodeURIComponent(selected.id)}?currency=${encodeURIComponent(portfolio.base_currency)}`, {
      timeoutMs: 8_000,
    })
      .then((quote) => {
        if (!active) return;
        setLiveQuote(quote);
        setCurrentPrice(String(quote.price));
        setName(quote.name);
        setError(null);
      })
      .catch((err) => active && setError(err.message))
      .finally(() => active && setQuoteLoading(false));
    return () => { active = false; };
  }, [isBond, portfolio.base_currency, products, productsLoading, requestAttempt, symbol]);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const path = asset
        ? `/portfolio/${portfolio.id}/assets/${asset.id}`
        : `/portfolio/${portfolio.id}/assets`;
      const response = await send(path, {
        method: asset ? "PUT" : "POST",
        body: {
          asset_type: assetType,
          name: name.trim() || symbol.trim(),
          symbol: symbol.trim() || null,
          quantity,
          current_price: currentPrice,
          currency: portfolio.base_currency,
          note: note.trim() || null,
        },
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.portfolio)
        throw new Error(result?.detail ?? `HTTP ${response.status}: holding was not saved`);
      onSaved(result.portfolio);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <>
      <div className="scrim trade-scrim" onClick={() => !saving && onClose()} />
      <aside className="trade-modal asset-modal" aria-label={`${asset ? "Edit" : "Add"} ${label}`}>
        <button className="close-btn" onClick={onClose} disabled={saving} aria-label="Close holding form">×</button>
        <h2>{asset ? "Edit" : "Add"} {label}</h2>
        <p className="sub">{isBond
          ? `Enter the current value manually in ${portfolio.base_currency}. It will be labelled as manual in your dashboard.`
          : `Choose a Coinbase ${portfolio.base_currency} market. Its quote and holding value refresh automatically.`}</p>
        <form className="trade-form" onSubmit={submit}>
          {isBond ? <>
            <label>
              Bond name or issuer
              <input required autoFocus value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              Ticker / ISIN <span>(optional)</span>
              <input value={symbol} onChange={(event) => setSymbol(event.target.value)} />
            </label>
          </> : <label className="wide">
            Crypto ticker
            <input required autoFocus list="crypto-products" placeholder={productsLoading ? "Loading Coinbase tickers…" : "Search e.g. BTC-USD"}
                   value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} />
            <datalist id="crypto-products">{products.map((product) =>
              <option key={product.id} value={product.id}>{product.name}</option>)}</datalist>
            <small>{productsLoading ? "Fetching active markets…" : `${products.length} active ${portfolio.base_currency} crypto markets available`}</small>
          </label>}
          <label>
            Quantity
            <input type="number" min="0" step="any" required value={quantity}
                   onChange={(event) => setQuantity(event.target.value)} />
          </label>
          {isBond ? <label>
              Current price per unit ({portfolio.base_currency})
              <input type="number" min="0" step="any" required value={currentPrice}
                     onChange={(event) => setCurrentPrice(event.target.value)} />
              <small>Use the currency value of one unit, not a quoted percentage, unless your quantity is adjusted for it.</small>
            </label> : <div className="live-quote-field">
              <span>Live unit price ({portfolio.base_currency})</span>
              <b>{quoteLoading ? "Fetching…" : money(liveQuote?.price, portfolio.base_currency)}</b>
              <small>{liveQuote?.asof ? `Coinbase · ${dateTime(liveQuote.asof)}` : "Select a valid ticker"}</small>
            </div>}
          <label className="wide">
            Note <span>(optional)</span>
            <input value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
          <div className="asset-value-preview wide">
            <span>Current holding value</span>
            <b>{money(marketValue, portfolio.base_currency)}</b>
          </div>
          {error && <p className="trade-error">
            {error}
            {!isBond && !saving && <>{" "}<button type="button" className="linkish"
              onClick={() => { setError(null); setRequestAttempt((value) => value + 1); }}>
              Retry live price
            </button></>}
          </p>}
          <div className="trade-actions wide">
            <button type="button" onClick={onClose} disabled={saving}>Cancel</button>
            <button className="primary" type="submit"
                    disabled={saving || (!isBond && (!liveQuote || quoteLoading || productsLoading))}>
              {saving ? "Saving…" : asset ? "Save changes" : `Add ${label}`}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}


function money(value, currency) {
  if (value == null) return "—";
  return Number(value).toLocaleString(undefined, {
    style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}


const dateTime = (value) => new Date(value).toLocaleString(undefined, {
  dateStyle: "medium", timeStyle: "medium",
});
