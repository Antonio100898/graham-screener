import { useEffect, useRef, useState } from "react";
import { send } from "./api.js";

// This control is shared by Research and Portfolio, so it stays above their
// navigation rather than looking like part of either page.
const ACTIONS = [
  {
    cmd: "bulk",
    label: "Load all",
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
    hint: "Reads SEC's daily index to see who filed a 10-K or 10-Q, and refetches only those companies.",
  },
  {
    cmd: "quotes",
    label: "Refresh prices",
    hint: "Fetches every universe quote and atomically rebuilds the shared Research and Portfolio snapshot.",
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
    try {
      const r = await send("/sync", { body: { command: action.cmd } });
      if (!r.ok) setError((await r.json()).detail ?? `HTTP ${r.status}`);
      else {
        wasRunning.current = true;
        poll();
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const st = job?.store;
  const running = job?.status === "running";
  const pct = running && job.total ? Math.round((job.done / job.total) * 100) : null;

  return (
    <aside className="loadbar" aria-label="Shared data controls">
      <div className="topline">
        <span className="loadbar-label">Data</span>
        <div className="actions">
          {ACTIONS.map((a) => (
            <button key={a.cmd} onClick={() => run(a)} disabled={running} title={a.hint}
                    className={a.heavy ? "heavy" : ""}>
              {a.label}
            </button>
          ))}
        </div>
        {running ? (
          <div className="prog">
            <div className="bar">
              <div className="fill" style={{ width: pct == null ? "100%" : `${pct}%` }}
                   data-indeterminate={pct == null} />
            </div>
            <span className="txt">
              {job.message}
              {job.total ? ` · ${job.done.toLocaleString()}/${job.total.toLocaleString()}` : ""}
            </span>
            <button className="stop" onClick={() => send("/sync/cancel")}>Stop</button>
          </div>
        ) : st && (
          <div className="loadbar-status">
            <span title={st.last_fetch ?? "no fetch recorded"}>Filings <b>{ago(st.last_fetch)}</b></span>
            <span title={st.last_quote_refresh ?? st.last_export ?? "no price refresh recorded"}>
              Prices <b>{ago(st.last_quote_refresh ?? st.last_export)}</b>
            </span>
            <span><b>{shown?.toLocaleString() ?? st.snapshots.toLocaleString()}</b> screened</span>
            {st.pending_refetch > 0 && <span className="pending">{st.pending_refetch.toLocaleString()} new filing{st.pending_refetch === 1 ? "" : "s"}</span>}
            {job.status === "error" && <span className="bad" title={job.error}>Last job failed</span>}
          </div>
        )}
        {error && <span className="bad loadbar-error">{error}</span>}
      </div>
    </aside>
  );
}
