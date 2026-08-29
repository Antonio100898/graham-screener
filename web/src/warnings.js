/** Payload caveats that must remain beside the figures they qualify. */
export function payloadWarnings(row = {}) {
  const warnings = [];
  const pending = row.data_pending;
  if (pending) {
    warnings.push({
      kind: "Latest filing pending",
      text: pending.note ?? "SEC structured statements for the latest annual filing are not complete yet.",
      filed: pending.filed ?? null,
      accession: pending.accession ?? null,
    });
  }
  const history = row.price_history_warning;
  if (history) {
    warnings.push({
      kind: "Price history retained",
      text: history.note ?? "The latest historical-price refresh failed validation; the previously validated series remains in use.",
    });
  }
  const quote = row.quote_refresh_warning;
  if (quote) {
    warnings.push({
      kind: "Quote refresh failed",
      text: quote.note ?? "The hourly quote request failed; the dated previous quote remains visible.",
    });
  }
  return warnings;
}
