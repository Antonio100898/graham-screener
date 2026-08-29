const DEFAULT_SORT = { key: "fit", dir: 1 };

export function normalizeSort(value) {
  const candidates = Array.isArray(value) ? value : [value];
  const seen = new Set();
  const result = [];

  for (const item of candidates) {
    if (!item || typeof item.key !== "string" || seen.has(item.key)) continue;
    seen.add(item.key);
    result.push({ key: item.key, dir: item.dir === -1 ? -1 : 1 });
  }
  return result.length ? result : [{ ...DEFAULT_SORT }];
}

export function updateSort(value, key, additive = false) {
  const current = normalizeSort(value);
  if (!additive) {
    const direction = current[0].key === key ? -current[0].dir : 1;
    return [{ key, dir: direction }];
  }

  const existing = current.findIndex((item) => item.key === key);
  if (existing === -1) return [...current, { key, dir: 1 }];
  return current.map((item, index) =>
    index === existing ? { ...item, dir: -item.dir } : item
  );
}

export function compareRows(a, b, sorts, valueOf) {
  for (const { key, dir } of normalizeSort(sorts)) {
    const x = valueOf(a, key);
    const y = valueOf(b, key);

    // Missing values stay last for this criterion in either direction. If both
    // are missing, the next requested sort column still gets a chance to decide.
    if (x == null || y == null) {
      if (x == null && y == null) continue;
      return x == null ? 1 : -1;
    }

    const comparison = typeof x === "string" ? x.localeCompare(y) : x - y;
    if (comparison) return comparison * dir;
  }
  return (a.ticker ?? "").localeCompare(b.ticker ?? "");
}
