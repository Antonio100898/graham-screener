// Filters, sort and scroll position survive a refresh. Kept in localStorage rather
// than the URL: this is a working view you return to, not something you link to,
// and Sets serialise badly as query strings.
const KEY = "screener-view";

/** Every table-filter control in its genuinely unfiltered state. */
export function unfilteredView() {
  return {
    gaps: "ALL",
    lens: "BOTH",
    fit: "ALL",
    profiles: [],
    sectors: [],
    venues: [],
    indexes: [],
    minCap: 0,
    minMet: 0,
    minPositiveEps: 0,
    maxPe: 0,
    maxPe3: 0,
    trackedOnly: false,
    hideNA: false,
    hideNoApply: false,
    belowNcav: false,
  };
}

const selected = (value) => value?.size ?? value?.length ?? 0;

/** Whether the table is narrower than the full loaded universe. */
export function hasActiveFilters(view) {
  return view.lens !== "BOTH"
    || view.fit !== "ALL"
    || view.gaps !== "ALL"
    || selected(view.profiles) > 0
    || selected(view.sectors) > 0
    || selected(view.venues) > 0
    || selected(view.indexes) > 0
    || view.minCap > 0
    || view.minMet > 0
    || view.minPositiveEps > 0
    || view.maxPe > 0
    || view.maxPe3 > 0
    || Boolean(view.trackedOnly)
    || Boolean(view.hideNA)
    || Boolean(view.hideNoApply)
    || Boolean(view.belowNcav);
}

const DEFAULTS = {
  q: "",
  ...unfilteredView(),
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
