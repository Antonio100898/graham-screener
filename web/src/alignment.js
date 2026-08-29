export function alignmentPoints(row) {
  const e = row.alignment?.enterprising?.passed;
  const d = row.alignment?.defensive?.passed;
  return Number.isFinite(e) && Number.isFinite(d) ? e + d : null;
}

export function alignmentSortValue(row) {
  const points = alignmentPoints(row);
  return points == null ? null : -points;
}
