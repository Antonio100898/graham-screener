import { useEffect, useMemo, useRef, useState } from "react";
import {
  calculateGrowthValuationMatrix,
  launcherPoint,
  mergeCompanyIntrinsicValueInputs,
  OPEN_INTRINSIC_VALUE_EVENT,
  parseDiscountRates,
  parseGrowthRates,
  snapLauncherPoint,
} from "./intrinsicValue.js";

const INPUTS_KEY = "screener-intrinsic-value-v3";
const ANCHOR_KEY = "screener-intrinsic-value-anchor-v1";
const EDGE_MARGIN = 16;
const BUTTON_SIZE = 58;
const CORNER_SNAP = 76;
const MAX_YEARS = 50;
const COMMON_CURRENCIES = ["USD", "EUR", "GBP", "ILS"];

const DEFAULT_INPUTS = {
  currentIncome: "",
  shares: "",
  years: 10,
  growthRates: "0, 5, 10",
  discountRates: "8, 10, 12",
  terminalGrowth: "2",
  currency: "USD",
};
const DEFAULT_ANCHOR = { edge: "right", ratio: 1 };

function readStored(key, fallback) {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    return saved && typeof saved === "object" ? saved : fallback;
  } catch {
    return fallback;
  }
}

function normaliseInputs(saved) {
  const savedCurrency = String(saved?.currency ?? "USD").trim().toUpperCase();
  return {
    currentIncome: String(saved?.currentIncome ?? ""),
    shares: String(saved?.shares ?? ""),
    years: Math.max(1, Math.min(MAX_YEARS, Number(saved?.years) || DEFAULT_INPUTS.years)),
    growthRates: String(saved?.growthRates ?? DEFAULT_INPUTS.growthRates),
    discountRates: String(saved?.discountRates ?? DEFAULT_INPUTS.discountRates),
    terminalGrowth: String(saved?.terminalGrowth ?? DEFAULT_INPUTS.terminalGrowth),
    currency: /^[A-Z]{3}$/.test(savedCurrency) ? savedCurrency : "USD",
  };
}

function normaliseAnchor(anchor) {
  const edge = ["left", "right", "top", "bottom"].includes(anchor?.edge)
    ? anchor.edge
    : DEFAULT_ANCHOR.edge;
  const ratio = Number.isFinite(Number(anchor?.ratio))
    ? Math.max(0, Math.min(1, Number(anchor.ratio)))
    : DEFAULT_ANCHOR.ratio;
  return { edge, ratio };
}

function viewportPoint(anchor) {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  return launcherPoint(anchor, { width: window.innerWidth, height: window.innerHeight }, {
    buttonSize: BUTTON_SIZE,
    margin: EDGE_MARGIN,
  });
}

function clampPoint(x, y) {
  const maxX = Math.max(EDGE_MARGIN, window.innerWidth - BUTTON_SIZE - EDGE_MARGIN);
  const maxY = Math.max(EDGE_MARGIN, window.innerHeight - BUTTON_SIZE - EDGE_MARGIN);
  return {
    x: Math.max(EDGE_MARGIN, Math.min(maxX, x)),
    y: Math.max(EDGE_MARGIN, Math.min(maxY, y)),
  };
}

function snapPoint(point) {
  return snapLauncherPoint(point, { width: window.innerWidth, height: window.innerHeight }, {
    buttonSize: BUTTON_SIZE,
    margin: EDGE_MARGIN,
    cornerSnap: CORNER_SNAP,
  });
}

const formatMoney = (value, currency) => {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: Math.abs(value) < 100 ? 2 : 0,
    maximumFractionDigits: Math.abs(value) < 100 ? 2 : 0,
  }).format(value);
};

export default function IntrinsicValueTool() {
  const [open, setOpen] = useState(false);
  const [inputs, setInputs] = useState(() => normaliseInputs(readStored(INPUTS_KEY, DEFAULT_INPUTS)));
  const [anchor, setAnchor] = useState(() => normaliseAnchor(readStored(ANCHOR_KEY, DEFAULT_ANCHOR)));
  const [dragPoint, setDragPoint] = useState(null);
  const [companyPrefill, setCompanyPrefill] = useState(null);
  const [, setViewportRevision] = useState(0);
  const drag = useRef(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    try { localStorage.setItem(INPUTS_KEY, JSON.stringify(inputs)); } catch { /* optional persistence */ }
  }, [inputs]);

  useEffect(() => {
    try { localStorage.setItem(ANCHOR_KEY, JSON.stringify(anchor)); } catch { /* optional persistence */ }
  }, [anchor]);

  useEffect(() => {
    const resized = () => setViewportRevision((revision) => revision + 1);
    window.addEventListener("resize", resized);
    return () => window.removeEventListener("resize", resized);
  }, []);

  useEffect(() => {
    const loadCompany = (event) => {
      const prefill = event.detail;
      if (!prefill?.ready) return;
      setInputs((current) => mergeCompanyIntrinsicValueInputs(current, prefill));
      setCompanyPrefill(prefill);
      setOpen(true);
    };
    window.addEventListener(OPEN_INTRINSIC_VALUE_EVENT, loadCompany);
    return () => window.removeEventListener(OPEN_INTRINSIC_VALUE_EVENT, loadCompany);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const escape = (event) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open]);

  const point = dragPoint ?? viewportPoint(anchor);
  const growthRates = useMemo(() => parseGrowthRates(inputs.growthRates), [inputs.growthRates]);
  const discountRates = useMemo(
    () => parseDiscountRates(inputs.discountRates),
    [inputs.discountRates],
  );
  const terminalGrowth = useMemo(
    () => parseGrowthRates(inputs.terminalGrowth)[0],
    [inputs.terminalGrowth],
  );
  const matrix = useMemo(() => calculateGrowthValuationMatrix({
    currentIncome: inputs.currentIncome,
    years: inputs.years,
    growthRates,
    discountRates,
    terminalGrowthPercent: terminalGrowth,
    shares: inputs.shares,
  }), [
    inputs.currentIncome,
    inputs.years,
    growthRates,
    discountRates,
    terminalGrowth,
    inputs.shares,
  ]);
  const completeCells = matrix.flatMap((row) => row.cells).filter(Boolean).length;

  const update = (field, value) => setInputs((current) => ({ ...current, [field]: value }));
  const setYears = (raw) => update(
    "years",
    Math.max(1, Math.min(MAX_YEARS, Number(raw) || 1)),
  );
  const reset = () => {
    setInputs(normaliseInputs(DEFAULT_INPUTS));
    setCompanyPrefill(null);
  };

  const pointerDown = (event) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin: viewportPoint(anchor),
      moved: false,
    };
  };

  const pointerMove = (event) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.current.startX;
    const dy = event.clientY - drag.current.startY;
    if (!drag.current.moved && Math.hypot(dx, dy) < 4) return;
    drag.current.moved = true;
    drag.current.lastPoint = clampPoint(drag.current.origin.x + dx, drag.current.origin.y + dy);
    setDragPoint(drag.current.lastPoint);
  };

  const pointerUp = (event) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    if (drag.current.moved) {
      setAnchor(snapPoint(drag.current.lastPoint ?? drag.current.origin));
      setDragPoint(null);
      suppressClick.current = true;
    }
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const buttonClick = () => {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    setOpen((visible) => !visible);
  };

  return (
    <>
      <button
        type="button"
        className={`intrinsic-launcher ${dragPoint ? "dragging" : ""}`}
        style={{ left: point.x, top: point.y }}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={() => { drag.current = null; setDragPoint(null); }}
        onClick={buttonClick}
        aria-label="Open intrinsic value calculator"
        aria-expanded={open}
        title="Intrinsic value calculator · drag to move"
      >
        <span>IV</span>
        <small>DCF</small>
      </button>

      {open && (
        <>
          <div className="intrinsic-scrim" onMouseDown={() => setOpen(false)} />
          <aside className="intrinsic-panel intrinsic-panel-simple" role="dialog" aria-modal="true"
                 aria-labelledby="intrinsic-title">
            <button type="button" className="close-btn" onClick={() => setOpen(false)}
                    aria-label="Close intrinsic value calculator">×</button>
            <div className="intrinsic-heading">
              <span>Standalone valuation workspace</span>
              <h2 id="intrinsic-title">Intrinsic Value Calculation</h2>
              <p>
                Enter the starting Owner Earnings / FCF and percentage assumptions. The calculator
                builds every future year and returns the price-per-share matrix.
              </p>
              {companyPrefill && (
                <p className="intrinsic-prefill-note">
                  Loaded {companyPrefill.ticker}: FY{companyPrefill.fiscalYear} FCF and current shares.
                </p>
              )}
            </div>

            <section className="intrinsic-inputs intrinsic-inputs-simple"
                     aria-label="Valuation assumptions">
              <label>
                <span>Current annual Owner Earnings / FCF</span>
                <input type="number" inputMode="decimal" value={inputs.currentIncome}
                       onChange={(event) => update("currentIncome", event.target.value)}
                       placeholder="e.g. 125000000" />
                <small>The latest sustainable cash flow attributable to shareholders.</small>
              </label>
              <label>
                <span>Current shares outstanding</span>
                <input type="number" inputMode="decimal" min="0" value={inputs.shares}
                       onChange={(event) => update("shares", event.target.value)}
                       placeholder="e.g. 42000000" />
                <small>Income and shares may both be full figures or both be in millions.</small>
              </label>
              <label>
                <span>Forecast years</span>
                <input type="number" min="1" max={MAX_YEARS} value={inputs.years}
                       onChange={(event) => setYears(event.target.value)} />
                <small>Growth compounds for 1–{MAX_YEARS} explicit future years.</small>
              </label>
              <label>
                <span>Annual income growth scenarios (%)</span>
                <input value={inputs.growthRates}
                       onChange={(event) => update("growthRates", event.target.value)}
                       placeholder="0, 5, 10" />
                <small>Each percentage becomes one matrix column.</small>
              </label>
              <label>
                <span>Required annual returns (%)</span>
                <input value={inputs.discountRates}
                       onChange={(event) => update("discountRates", event.target.value)}
                       placeholder="8, 10, 12" />
                <small>Each percentage becomes one matrix row and discount rate.</small>
              </label>
              <label>
                <span>Stable terminal growth (%)</span>
                <input type="number" inputMode="decimal" step="0.1"
                       value={inputs.terminalGrowth}
                       onChange={(event) => update("terminalGrowth", event.target.value)}
                       placeholder="2" />
                <small>Gordon Growth after the forecast period; it must remain below r.</small>
              </label>
              <label>
                <span>Currency</span>
                <select value={inputs.currency} onChange={(event) => update("currency", event.target.value)}>
                  {!COMMON_CURRENCIES.includes(inputs.currency) && (
                    <option value={inputs.currency}>{inputs.currency}</option>
                  )}
                  <option value="USD">USD ($)</option>
                  <option value="EUR">EUR (€)</option>
                  <option value="GBP">GBP (£)</option>
                  <option value="ILS">ILS (₪)</option>
                </select>
                <small>Display only; no FX conversion is performed.</small>
              </label>
            </section>

            <div className="intrinsic-toolbar intrinsic-toolbar-simple">
              <p>
                Gordon Growth uses year {inputs.years + 1} FCF and a {terminalGrowth == null
                  ? "missing"
                  : `${terminalGrowth}%`} stable growth rate. Cells where g ≥ r are withheld.
              </p>
              <button type="button" className="quiet" onClick={reset}>Reset</button>
            </div>

            <section className="intrinsic-results intrinsic-results-simple"
                     aria-labelledby="matrix-heading">
              <div className="intrinsic-section-title">
                <div>
                  <h3 id="matrix-heading">Intrinsic value per share</h3>
                  <p>Rows are required returns. Columns are annual growth assumptions.</p>
                </div>
                <span>{completeCells} of {discountRates.length * growthRates.length} values ready</span>
              </div>
              <div className="intrinsic-table-scroll">
                <table className="intrinsic-matrix">
                  <thead>
                    <tr>
                      <th>Required return</th>
                      {growthRates.map((growth) => <th key={growth}>Growth {growth}%</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.map((row) => (
                      <tr key={row.ratePercent}>
                        <th>{row.ratePercent.toLocaleString()}%</th>
                        {row.cells.map((cell, index) => (
                          <td key={growthRates[index]}
                              className={!cell && terminalGrowth != null
                                && row.ratePercent <= terminalGrowth ? "intrinsic-invalid" : ""}
                              title={cell
                                ? `Year 1 FCF: ${formatMoney(cell.firstYearIncome, inputs.currency)} · Year ${inputs.years} FCF: ${formatMoney(cell.finalYearIncome, inputs.currency)} · Next-year terminal FCF: ${formatMoney(cell.terminalNextYearCashFlow, inputs.currency)} · Forecast PV: ${formatMoney(cell.forecastPresentValue, inputs.currency)} · Terminal PV: ${formatMoney(cell.terminalPresentValue, inputs.currency)}`
                                : terminalGrowth != null && row.ratePercent <= terminalGrowth
                                  ? "Gordon Growth requires terminal growth to be lower than the required return"
                                  : "Enter current Owner Earnings / FCF, terminal growth, and positive shares"}>
                            {!cell && terminalGrowth != null && row.ratePercent <= terminalGrowth
                              ? "r ≤ g"
                              : formatMoney(cell?.perShare, inputs.currency)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {(discountRates.length === 0 || growthRates.length === 0) && (
                      <tr><td colSpan={Math.max(2, growthRates.length + 1)} className="intrinsic-empty">
                        Enter at least one growth rate and one required return greater than 0%.
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {completeCells === 0 && discountRates.length > 0 && growthRates.length > 0 && (
                <p className="intrinsic-empty-note">
                  Enter current Owner Earnings / FCF, terminal growth, and a positive diluted share
                  count to calculate the matrix.
                </p>
              )}
            </section>

            <details className="intrinsic-formula" open>
              <summary>How the formula works</summary>
              <ol>
                <li>Forecast FCF: FCF<sub>t</sub> = FCF<sub>0</sub> × (1 + g<sub>forecast</sub>)<sup>t</sup>.</li>
                <li>Forecast PV: Σ FCF<sub>t</sub> / (1 + r)<sup>t</sup>, for years 1 through N.</li>
                <li>Next-year FCF: FCF<sub>N+1</sub> = FCF<sub>N</sub> × (1 + g<sub>terminal</sub>).</li>
                <li>Terminal value: TV<sub>N</sub> = FCF<sub>N+1</sub> / (r − g<sub>terminal</sub>).</li>
                <li>Price per share: [forecast PV + TV<sub>N</sub> / (1 + r)<sup>N</sup>] / current shares.</li>
              </ol>
              <p>
                The selected matrix column supplies forecast growth; the selected row supplies r.
                This is an equity-level Owner Earnings / FCF model. The calculated equity value is
                divided directly by the current shares outstanding.
              </p>
            </details>
          </aside>
        </>
      )}
    </>
  );
}
