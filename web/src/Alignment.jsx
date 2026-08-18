const PROFILE = {
  OPERATING: { short: "Operating", label: "Industrial-style operating business" },
  UTILITY: { short: "Utility", label: "Public utility" },
  FINANCIAL: { short: "Financial", label: "Financial / real-estate structure" },
  SPECIAL: { short: "Special", label: "Special structure" },
  REVIEW: { short: "Review", label: "Manual applicability review" },
};

const WORD = {
  ALIGNED: "Aligned",
  BLOCKED: "Blocked",
  EVIDENCE_INCOMPLETE: "Evidence incomplete",
  OUT_OF_SCOPE: "Out of scope",
};

export const profileMeta = (row) =>
  row.graham_profile_meta ?? PROFILE[row.graham_profile] ?? PROFILE.REVIEW;

export const alignmentWord = (value) => WORD[value] ?? "Evidence incomplete";

export function alignmentRank(row, lens = "BOTH") {
  const a = row.alignment ?? {};
  const e = a.enterprising ?? {};
  const d = a.defensive ?? {};
  const score = (x) => {
    const base = { ALIGNED: 0, EVIDENCE_INCOMPLETE: 1, BLOCKED: 2, OUT_OF_SCOPE: 3 }[x.verdict] ?? 4;
    return base * 100 - (x.passed ?? 0) * 10 + (x.unknown ?? 0);
  };
  if (lens === "ENTERPRISING") return score(e);
  if (lens === "DEFENSIVE") return score(d);
  return Math.min(score(e), score(d));
}

function Status({ value }) {
  return <span className={`align-status ${String(value ?? "EVIDENCE_INCOMPLETE").toLowerCase()}`}>{alignmentWord(value)}</span>;
}

export function AlignmentCompact({ row }) {
  const e = row.alignment?.enterprising;
  const d = row.alignment?.defensive;
  if (!e || !d) return <span className="dim">needs refresh</span>;
  return (
    <div className="align-compact">
      <span title={`Enterprising: ${alignmentWord(e.verdict)}`}>E <b>{e.passed}/{e.total}</b></span>
      <span title={`Defensive evidence: ${alignmentWord(d.verdict)}`}>D <b>{d.passed}/{d.total}</b></span>
    </div>
  );
}

export function AlignmentPanel({ row }) {
  const profile = profileMeta(row);
  const e = row.alignment?.enterprising;
  const d = row.alignment?.defensive;
  if (!e || !d) {
    return <section className="alignment-panel"><p className="dim">Alignment data needs a dashboard refresh.</p></section>;
  }
  const growth = e.growth_modern_4fy;
  const growthText = growth?.status === "INSUFFICIENT_DATA"
    ? "not enough annual EPS history"
    : growth ? `FY${growth.latest_fy} vs FY${growth.base_fy}` : "not available";
  return (
    <section className="alignment-panel">
      <div className="profile-line">
        <span className={`profile-pill ${String(row.graham_profile ?? "REVIEW").toLowerCase()}`}>{profile.short}</span>
        <div><b>{profile.label}</b><p>{row.graham_profile_meta?.detail}</p></div>
      </div>
      <div className="alignment-cards">
        <article className="alignment-card enterprising">
          <header><span>Enterprising</span><Status value={e.verdict} /></header>
          <strong>{e.passed}/{e.total} direct tests passed</strong>
          <p>Industrial low-multiplier criteria. {e.profile_note}</p>
          <div className={`growth-note ${String(growth?.status ?? "INSUFFICIENT_DATA").toLowerCase()}`}>
            <b>4-FY EPS analogue:</b> {growthText}
          </div>
        </article>
        <article className="alignment-card defensive">
          <header><span>Defensive</span><Status value={d.verdict} /></header>
          <strong>{d.passed}/{d.total} evidence tests passed</strong>
          <p>{d.profile_note}</p>
        </article>
      </div>
    </section>
  );
}
