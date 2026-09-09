const number = (value) => {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value.replaceAll(",", "").trim());
  return Number.isFinite(parsed) ? parsed : null;
};

export const OPEN_INTRINSIC_VALUE_EVENT = "screener:open-intrinsic-value";

const bridgeValue = (point) => {
  if (Array.isArray(point)) return number(point[0]);
  if (point && typeof point === "object") return number(point.value);
  return number(point);
};

const currencyCode = (value) => {
  const currency = String(value ?? "USD").trim().toUpperCase();
  return /^[A-Z]{3}$/.test(currency) ? currency : "USD";
};

/** Use the exact annual FCF displayed by the company cash-bridge table. When the
 * newest fiscal-year slot is blank, choose the newest earlier slot with evidence
 * instead of converting that blank to zero. Current shares come from the company
 * snapshot rather than an historical weighted-average EPS denominator. */
export function companyIntrinsicValuePrefill(row) {
  const annual = row?.owner_earnings?.annual_per_share ?? {};
  const candidates = Object.entries(annual)
    .map(([fiscalYear, cell]) => ({
      fiscalYear: Number(fiscalYear),
      currentIncome: bridgeValue(cell?.cash_flow_bridge?.free_cash_flow),
    }))
    .filter(({ fiscalYear }) => Number.isFinite(fiscalYear))
    .sort((left, right) => right.fiscalYear - left.fiscalYear);
  const latest = candidates.find(({ currentIncome }) => currentIncome != null) ?? null;
  const currentShares = number(row?.shares);
  const shares = currentShares != null && currentShares > 0 ? currentShares : null;

  return {
    ticker: row?.ticker ?? null,
    fiscalYear: latest?.fiscalYear ?? null,
    currentIncome: latest?.currentIncome ?? null,
    shares,
    currency: currencyCode(row?.currency),
    ready: latest?.currentIncome != null && shares != null,
  };
}

/** Replace only the company-specific inputs. The user's stored forecast years,
 * growth scenarios, required returns, and terminal-growth assumption survive. */
export function mergeCompanyIntrinsicValueInputs(current, prefill) {
  if (!prefill?.ready) return current;
  return {
    ...current,
    currentIncome: String(prefill.currentIncome),
    shares: String(prefill.shares),
    currency: currencyCode(prefill.currency),
  };
}

export function openIntrinsicValueCalculator(prefill) {
  const host = typeof window === "undefined" ? null : window;
  const EventConstructor = host?.CustomEvent ?? globalThis.CustomEvent;
  if (!prefill?.ready || !host?.dispatchEvent || typeof EventConstructor !== "function") return false;
  host.dispatchEvent(new EventConstructor(OPEN_INTRINSIC_VALUE_EVENT, { detail: prefill }));
  return true;
}

/**
 * Parse user-entered percentages without turning blanks or malformed values into
 * zero. Repeated rates would create duplicate matrix rows, so they are removed.
 */
export function parseDiscountRates(value) {
  const rates = String(value ?? "")
    .split(/[;,\s]+/)
    .map(number)
    .filter((rate) => rate != null && rate > 0);
  return [...new Set(rates)];
}

/** Annual forecast growth may be zero or negative, but below -100% is not a
 * meaningful compounding path. */
export function parseGrowthRates(value) {
  const rates = String(value ?? "")
    .split(/[;,\s]+/)
    .map(number)
    .filter((rate) => rate != null && rate >= -100);
  return [...new Set(rates)];
}

/**
 * A DCF with Gordon Growth terminal value. cashFlows contains years 1..N and
 * terminalIncome is year N's cash flow. The next-year terminal cash flow is
 * terminalIncome × (1 + g), and r must be strictly greater than g.
 */
export function calculateIntrinsicValue({
  cashFlows,
  terminalIncome,
  discountRate,
  terminalGrowthRate = 0,
  shares,
}) {
  const flows = Array.isArray(cashFlows) ? cashFlows.map(number) : [];
  const terminal = number(terminalIncome);
  const shareCount = number(shares);

  if (!flows.length || flows.some((flow) => flow == null)) return null;
  if (terminal == null || shareCount == null || shareCount <= 0) return null;
  if (!Number.isFinite(discountRate) || discountRate <= 0) return null;
  if (!Number.isFinite(terminalGrowthRate) || terminalGrowthRate <= -1) return null;
  if (discountRate <= terminalGrowthRate) return null;

  const forecastPresentValue = flows.reduce(
    (sum, flow, index) => sum + flow / Math.pow(1 + discountRate, index + 1),
    0,
  );
  const terminalNextYearCashFlow = terminal * (1 + terminalGrowthRate);
  const terminalValueAtHorizon = terminalNextYearCashFlow
    / (discountRate - terminalGrowthRate);
  const terminalPresentValue = terminalValueAtHorizon
    / Math.pow(1 + discountRate, flows.length);
  const equityValue = forecastPresentValue + terminalPresentValue;

  return {
    forecastPresentValue,
    terminalNextYearCashFlow,
    terminalValueAtHorizon,
    terminalPresentValue,
    equityValue,
    perShare: equityValue / shareCount,
  };
}

/**
 * Build the user's matrix from just E0, N, growth scenarios and required-return
 * scenarios. The explicit income path compounds at g for N years, then Gordon
 * Growth uses the separately supplied stable long-term growth assumption.
 */
export function calculateGrowthValuationMatrix({
  currentIncome,
  years,
  growthRates,
  discountRates,
  terminalGrowthPercent,
  shares,
}) {
  const income = number(currentIncome);
  const yearCount = Number(years);
  const validYears = Number.isInteger(yearCount) && yearCount > 0;

  return discountRates.map((ratePercent) => ({
    ratePercent,
    cells: growthRates.map((growthPercent) => {
      if (income == null || !validYears) return null;
      const growth = growthPercent / 100;
      const cashFlows = Array.from(
        { length: yearCount },
        (_, index) => income * Math.pow(1 + growth, index + 1),
      );
      const terminalIncome = cashFlows.at(-1);
      const result = calculateIntrinsicValue({
        cashFlows,
        terminalIncome,
        discountRate: ratePercent / 100,
        terminalGrowthRate: terminalGrowthPercent / 100,
        shares,
      });
      return result && {
        ...result,
        growthPercent,
        firstYearIncome: cashFlows[0],
        finalYearIncome: terminalIncome,
      };
    }),
  }));
}

const launcherLimits = (viewport, buttonSize, margin) => ({
  maxX: Math.max(margin, viewport.width - buttonSize - margin),
  maxY: Math.max(margin, viewport.height - buttonSize - margin),
});

/** Convert a persisted edge/ratio anchor into viewport coordinates. */
export function launcherPoint(anchor, viewport, { buttonSize = 58, margin = 16 } = {}) {
  const { maxX, maxY } = launcherLimits(viewport, buttonSize, margin);
  const ratio = Math.max(0, Math.min(1, Number(anchor?.ratio) || 0));
  const width = maxX - margin;
  const height = maxY - margin;
  if (anchor?.edge === "left") return { x: margin, y: margin + height * ratio };
  if (anchor?.edge === "top") return { x: margin + width * ratio, y: margin };
  if (anchor?.edge === "bottom") return { x: margin + width * ratio, y: maxY };
  return { x: maxX, y: margin + height * ratio };
}

/** Snap a released launcher to the nearest edge, and to a corner when nearby. */
export function snapLauncherPoint(
  point,
  viewport,
  { buttonSize = 58, margin = 16, cornerSnap = 76 } = {},
) {
  const { maxX, maxY } = launcherLimits(viewport, buttonSize, margin);
  const clamped = {
    x: Math.max(margin, Math.min(maxX, point.x)),
    y: Math.max(margin, Math.min(maxY, point.y)),
  };
  const distances = [
    ["left", clamped.x - margin],
    ["right", maxX - clamped.x],
    ["top", clamped.y - margin],
    ["bottom", maxY - clamped.y],
  ];
  const edge = distances.sort((a, b) => a[1] - b[1])[0][0];
  const vertical = edge === "left" || edge === "right";
  const end = vertical ? maxY : maxX;
  const coordinate = vertical ? clamped.y : clamped.x;
  let ratio = end === margin ? 0 : (coordinate - margin) / (end - margin);
  if (coordinate - margin <= cornerSnap) ratio = 0;
  if (end - coordinate <= cornerSnap) ratio = 1;
  return { edge, ratio: Math.max(0, Math.min(1, ratio)) };
}
