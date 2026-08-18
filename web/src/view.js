// Filters, sort and scroll position survive a refresh. Kept in localStorage rather
// than the URL: this is a working view you return to, not something you link to,
// and Sets serialise badly as query strings.
const KEY = "screener-view";

const DEFAULTS = {
  q: "",
  gaps: "ALL",
  lens: "BOTH",
  fit: "ALL",
  profiles: [],
  sectors: [],
  venues: [],
  indexes: [],
  minCap: 500e6,
  minMet: 0,
  minPositiveEps: 0,
  minRoic: 0,
  trackedOnly: false,
  hideNA: false,
  // on by default: criteria 2 and 3 cannot apply to a filer with no classified
  // balance sheet, so these companies are unreachable rather than merely unmeasured
  hideNoApply: true,
  belowNcav: false,
  sort: { key: "fit", dir: 1 },
  scroll: 0,
};

export function loadView() {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY)) || {}) };
  } catch {
    return { ...DEFAULTS };   // corrupt or unavailable storage must not break the app
  }
}

let pending = null;

export function saveView(patch) {
  const next = { ...loadView(), ...patch };
  // scrolling fires constantly; coalesce writes into one per frame
  cancelAnimationFrame(pending);
  pending = requestAnimationFrame(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* private mode or quota — the view simply will not persist */
    }
  });
}

/** Browsers restore scroll before the rows exist, which lands in the wrong place. */
export function takeOverScrollRestoration() {
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
}
