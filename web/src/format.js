// Formatting shared by the table and the detail panel.

/** A distance below a high, signed — except at the high itself, where "−0%" is silly. */
export function below(pct) {
  if (pct == null) return "—";
  const n = Math.round(pct);
  return n === 0 ? "0%" : `−${n}%`;
}

/** Weeks are the unit the price series comes in; nobody thinks in 137 of them. */
export function spell(weeks) {
  if (weeks == null) return "—";
  if (weeks < 8) return `${weeks} week${weeks === 1 ? "" : "s"}`;
  const months = Math.round(weeks / 4.35);
  if (months < 18) return `${months} months`;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return rest ? `${years}y ${rest}m` : `${years} years`;
}
