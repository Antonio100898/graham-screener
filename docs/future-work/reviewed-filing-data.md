# Reviewed filing data layer

## Status

Future work.  This document describes the intended contract; it is not yet an
implemented database or UI feature.

## User problem

Most financial figures can be extracted from SEC XBRL using global concept
families and carefully validated fallback tags.  Some primary 10-K, 10-Q, 20-F
or 40-F statements nevertheless contain an important historical value that is
absent from Company Facts, available only under an unusable extension, or
presented in prose or a table that the generic extractor cannot reconstruct
safely.

For a company under active research, a reviewer should be able to read that
value in the primary filing, record it once with exact evidence, and continue
to use it in the screener.  A normal derive, export or clean refetch must not
erase this work.  At the same time, SEC data must continue to be refreshed:
companies can file a 10-K/A, correct XBRL or restate a comparative period.

## Architectural rule

Do not edit a derived snapshot.  Snapshots are disposable outputs and must be
safe to rebuild.  Store reviewed observations as a separate durable input
layer, then apply them after generic SEC normalization and before ratios,
screens and UI serialization are calculated:

```text
raw SEC filings -> global extraction/normalization
                -> reviewed filing observations
                -> derived metrics and criteria
                -> dashboard.json
```

The extraction engine should remain global and semantic.  Company-specific
facts belong in data with provenance, not in increasingly broad heuristics.

## Two explicit operations

Every reviewed observation must declare one of these modes:

- `SUPPLEMENT`: the primary document contains a value for which the normalized
  XBRL result is missing.  Use the reviewed value only while the normalized
  value remains missing.
- `CORRECTION`: XBRL supplies a value, but the primary document proves it is
  wrong or refers to a different scope.  This requires a written explanation
  and stronger review because it intentionally supersedes machine data.

Neither mode may turn an unknown value into zero.  A reviewer must enter the
actual printed value and its unit.

## Durable record

A record should include at least:

- stable record ID and lifecycle state;
- registrant CIK and, where relevant, the exact security/share class;
- canonical metric and fiscal period start/end;
- value, unit, statement currency and sign;
- form, accession, filed date and source-document URL;
- printed statement name, row label, page or table locator;
- operation mode (`SUPPLEMENT` or `CORRECTION`);
- explanation of the XBRL limitation or contradiction;
- reviewer, review timestamp and optional second-review approval;
- fingerprint of the filing/evidence against which it was reviewed;
- supersession history rather than destructive replacement.

The record must emit the same `Fact`/provenance contract as an extracted value,
while clearly identifying `reviewed-filing` as its source.  The UI must disclose
that basis instead of presenting the observation as an ordinary XBRL tag.

## Refresh and amended-filing behaviour

A full fetch should continue to discover and cache every new filing.  A full
derive should rebuild every snapshot and reapply active reviewed observations;
it must never delete or silently rewrite them.

When a newer annual filing, 10-K/A or restatement covers the same fiscal period:

1. Run the global extractor against the new filing normally.
2. Keep the reviewed record, but mark it `REVIEW_REQUIRED` when its filing
   fingerprint or controlling accession is no longer current.
3. If the new normalized fact agrees with the reviewed observation within the
   metric's exact/rounding tolerance, retire the override as `RESOLVED_BY_XBRL`
   while retaining its audit history.
4. If it disagrees, do not choose silently.  Withhold the affected value from
   release or continue the last reviewed value with a conspicuous stale-review
   warning according to a deliberately selected release policy.
5. A reviewer can approve a replacement record tied to the new accession; the
   previous version remains immutable history.

This avoids the conflict between two desirable properties: recomputing from
new SEC evidence and preserving information that SEC XBRL never contained.

## Storage and operational boundaries

- Use a dedicated table or versioned import artifact, not the snapshot JSON.
- Database migrations and cache-clean commands must preserve this table.
- A destructive reset must require an explicit reviewed-data export or a
  separate explicit option; ordinary `make derive`, `make derive-all`,
  `make export` and refetch operations may not remove it.
- Provide deterministic export/import so reviewed data can be backed up,
  code-reviewed and restored on another machine without copying the whole
  screener database.
- Reject duplicate active records for the same company, metric, period and
  scope unless one explicitly supersedes the other.
- Require valid units, currency and period shape; do not accept an untyped
  number or a note without a primary-document locator.

## UI concept

Company Details should distinguish:

- normal filing-backed XBRL;
- reviewed supplement;
- reviewed correction;
- reviewed value awaiting confirmation after an amended filing.

A future editor should start from a specific company, metric and fiscal year,
show the current extracted fact beside the proposed value, require its filing
evidence, preview every downstream ratio/criterion change, and use the existing
write-access protection.  It should not be a generic database editor.

## Mandatory validation

- Unit tests for precedence, units, currency, periods and missing-is-not-zero.
- Rebuild test proving a reviewed observation survives a clean derive/export.
- Amended-filing tests for agreement, conflict and supersession.
- Provenance audit proving the exact source document and locator remain in the
  UI payload.
- Full UI-payload regression explaining every downstream changed field and
  verdict.
- Backup/restore round-trip test for the reviewed-data artifact.

## Definition of done

This feature is complete only when a reviewer can add one filing-backed missing
historical value, rebuild the entire database from SEC inputs, and obtain the
same reviewed value and derived metrics afterward; then introduce a newer
amended filing and receive an explicit agreement/conflict review state rather
than a silent overwrite.
