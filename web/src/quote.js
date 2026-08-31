const SESSION = {
  PRE: "Pre-market",
  REGULAR: "RTH",
  POST: "After-hours",
  UNKNOWN: "Unknown-session",
};

const STATE = {
  PRE: "pre-market open",
  REGULAR: "RTH open",
  POST: "after-hours open",
  CLOSED: "sleeping",
  UNKNOWN: "status unavailable",
};

const STATUS_FRESH_MS = 20 * 60 * 1000;


export function quoteStatus(row, now = Date.now()) {
  if (quotePrice(row) == null) return "No quote";
  const quoteSession = SESSION[row.price_session] ?? SESSION.UNKNOWN;
  const checked = Date.parse(row.market_state_asof ?? "");
  if (!Number.isFinite(checked) || Math.abs(now - checked) > STATUS_FRESH_MS)
    return `${quoteSession} quote · session status stale`;
  const state = STATE[row.market_state] ?? STATE.UNKNOWN;
  if (row.market_state === row.price_session)
    return `${quoteSession} · open at refresh`;
  return `${quoteSession} quote · ${state} at refresh`;
}


export function quoteTone(row, now = Date.now()) {
  const checked = Date.parse(row?.market_state_asof ?? "");
  if (!Number.isFinite(checked) || Math.abs(now - checked) > STATUS_FRESH_MS) return "stale";
  if (row.market_state === "CLOSED") return "closed";
  if (row.market_state === "PRE" || row.market_state === "POST") return "extended";
  if (row.market_state === "REGULAR") return "regular";
  return "stale";
}


export function quoteIcon(row, now = Date.now()) {
  if (quotePrice(row) == null) return "⊘";
  return {
    regular: "●",
    extended: "◐",
    closed: "☾",
    stale: "◇",
  }[quoteTone(row, now)] ?? "◇";
}


export function quoteTitle(row) {
  if (quotePrice(row) == null) return "Quote unavailable";
  const parts = [quoteStatus(row)];
  if (row.price_asof) parts.push(`price at ${new Date(row.price_asof).toLocaleString()}`);
  if (row.market_state_asof) parts.push(`session checked ${new Date(row.market_state_asof).toLocaleString()}`);
  if (row.market_timezone) parts.push(row.market_timezone);
  if (row.price_source) parts.push(`source: ${row.price_source}`);
  return parts.join(" · ");
}


function quotePrice(row) {
  return row?.price ?? row?.current_price ?? null;
}
