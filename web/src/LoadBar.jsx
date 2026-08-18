import { useEffect, useRef, useState } from "react";
import { send } from "./api.js";

// Each action touches exactly one stage of the pipeline; the labels say which.
// Recomputation after an engine change has no button: it starts by itself the
// moment the app notices snapshots below the current engine version.
const ACTIONS = [
  {
    cmd: "bulk",
    label: "Load all",
    sub: "every US filer, one download",
    hint: "Downloads SEC's complete 1.4 GB archive of every filer's financials, then screens them all. Do this once.",
    confirm:
      "Load every US filer from SEC?\n\n" +
      "• downloads a 1.4 GB archive\n• needs roughly 15 GB of disk\n• takes a while — you can Stop at any point\n\n" +
      "Afterwards, 'Fetch filings' keeps it current.",
    heavy: true,
  },
  {
    cmd: "daily",
    label: "Fetch filings",
    sub: "only companies that filed",
    hint: "Reads SEC's daily index to see who filed a 10-K or 10-Q, and refetches only those companies.",
  },
  {
    cmd: "export",
    label: "Refresh prices",
    sub: "rebuilds the table",
    hint: "Fetches current share prices, recomputes the valuation criteria, and rebuilds the table below.",
  },
];

// "3h ago" reads faster than a timestamp; the exact moment is in the tooltip
function ago(iso) {
  if (!iso) return "never";
  const mins = Math.max(0, (Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${Math.round(mins)}m ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

export default function LoadBar({ onFinished, shown }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [help, setHelp] = useState(false);
  const wasRunning = useRef(false);
  const autoDerived = useRef(false);

  const poll = () =>
    fetch("/sync/status")
      .then((r) => r.json())
      .then((s) => {
        setJob(s);
        if (wasRunning.current && s.status !== "running") {
          wasRunning.current = false;
          onFinished?.();
        }
        if (s.status === "running") wasRunning.current = true;
        // engine moved since these snapshots were computed: recompute without
        // being asked, once per page load so a failure cannot loop
        if (!autoDerived.current && s.status !== "running" && (s.store?.stale ?? 0) > 0) {
          autoDerived.current = true;
          send("/sync", { body: { command: "derive" } }).then(() => {
            wasRunning.current = true;
            poll();
          }).catch(() => {});
        }
      })
      .catch(() => {});

  useEffect(() => {
    poll();
    const id = setInterval(poll, 1200);
    return () => clearInterval(id);
  }, []);

  const run = async (action) => {
    if (action.confirm && !window.confirm(action.confirm)) return;
    setError(null);
    const r = await send("/sync", { body: { command: action.cmd } });
    if (!r.ok) setError((await r.json()).detail ?? `HTTP ${r.status}`);
    else {
      wasRunning.current = true;
      poll();
    }
  };

  const st = job?.store;
  const running = job?.status === "running";
  const pct = running && job.total ? Math.round((job.done / job.total) * 100) : null;
  const unloaded = st ? st.companies - st.snapshots : 0;

  return (
    <div className="loadbar">
      <div className="topline">
        <div className="actions">
          {ACTIONS.map((a) => (
            <button key={a.cmd} onClick={() => run(a)} disabled={running} title={a.hint}
                    className={a.heavy ? "heavy" : ""}>
              <b>{a.label}</b>
              <em>{a.sub}</em>
            </button>
          ))}
        </div>
        <button className="helptoggle" onClick={() => setHelp((h) => !h)}>
          {help ? "hide" : "how this works"}
        </button>
      </div>

      {running ? (
        <div className="prog">
          <div className="bar">
            <div className="fill" style={{ width: pct == null ? "100%" : `${pct}%` }}
                 data-indeterminate={pct == null} />
          </div>
          <button className="stop" onClick={() => send("/sync/cancel")}>Stop</button>
          <span className="txt">
            {job.message}
            {job.total ? ` — ${job.done.toLocaleString()} of ${job.total.toLocaleString()}` : ""}
          </span>
        </div>
      ) : (
        st && (
          <div className="coverage">
            <span className="fresh">
              <span title={st.last_fetch ?? "no fetch recorded"}>
                filings fetched <b>{ago(st.last_fetch)}</b>
              </span>
              {" · "}
              <span title={st.computed_at ?? "nothing computed"}>
                computed <b>{ago(st.computed_at)}</b>
              </span>
              {" · "}
              <span title={st.last_export ?? "no price refresh recorded"}>
                prices <b>{ago(st.last_export)}</b>
              </span>
            </span>
            <span>
              <b>{st.snapshots.toLocaleString()}</b> of {st.companies.toLocaleString()} companies have
              financial data
              {unloaded > 0 && (
                <> · <b className="gap">{unloaded.toLocaleString()} never loaded</b></>
              )}
              {" · "}
              <b>{shown?.toLocaleString() ?? "—"}</b> shown in the table
              {st.pending_refetch > 0 && (
                <> · {st.pending_refetch.toLocaleString()} filed since last sync</>
              )}
            </span>
            {job.status === "done" && <b className="ok">✓ {job.message}</b>}
            {job.status === "cancelled" && <b className="dim">⏹ stopped — work already done was kept</b>}
            {job.status === "error" && <b className="bad">✗ {job.error}</b>}
          </div>
        )
      )}
      {error && <div className="bad">{error}</div>}

      {help && (
        <div className="help">
          <p>
            <b>Where the company list comes from.</b> SEC publishes a file mapping every ticker to a
            permanent company ID (CIK). Nothing is hand-maintained — that file is the universe.
          </p>
          <p>
            <b>Where the numbers come from.</b> Each company's complete filing history is one file
            from SEC, downloaded once and kept. Screening runs locally against that copy, so it
            costs nothing to re-run.
          </p>
          <p>
            <b>Why data still needs refreshing.</b> Filings are permanent, but companies restate
            earlier years — after a stock split or a correction, a year you already hold changes.
            So the rule is "refetch anything that has filed since we last looked", not "refetch
            anything missing a recent quarter".
          </p>
          <p className="dim">
            To cover the whole market: <b>Load all</b> once, then <b>Refresh prices</b>.
            Afterwards <b>Fetch filings</b> daily or weekly keeps it current. When the
            screening engine itself changes, results are recomputed automatically.
          </p>
        </div>
      )}
    </div>
  );
}
