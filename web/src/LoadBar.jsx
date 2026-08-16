import { useEffect, useRef, useState } from "react";
import { send } from "./api.js";

// Each action touches exactly one stage of the pipeline; the labels say which.
const ACTIONS = [
  {
    cmd: "bulk",
    label: "Load all companies",
    sub: "every US filer, one download",
    hint: "Downloads SEC's complete 1.4 GB archive of every filer's financials, then screens them all. Do this once.",
    confirm:
      "Load every US filer from SEC?\n\n" +
      "• downloads a 1.4 GB archive\n• needs roughly 15 GB of disk\n• takes a while — you can Stop at any point\n\n" +
      "Afterwards, 'Fetch new filings' keeps it current.",
    heavy: true,
  },
  {
    cmd: "daily",
    label: "Fetch new filings",
    sub: "only companies that filed",
    hint: "Reads SEC's daily index to see who filed a 10-K or 10-Q, and refetches only those companies.",
  },
  {
    cmd: "export",
    label: "Refresh prices & table",
    sub: "rebuilds what you see",
    hint: "Fetches current share prices, recomputes the valuation criteria, and rebuilds the table below.",
  },
  {
    cmd: "derive",
    label: "Recompute",
    sub: "after an engine update",
    hint: "The screening logic changed since these results were computed. Re-runs the maths over data already on disk — no downloading.",
    // only shown when snapshots predate the current engine; otherwise it is noise
    onlyIfStale: true,
  },
];

export default function LoadBar({ onFinished, shown }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [help, setHelp] = useState(false);
  const wasRunning = useRef(false);

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
          {ACTIONS.filter((a) => !a.onlyIfStale || (st?.stale ?? 0) > 0).map((a) => (
            <button key={a.cmd} onClick={() => run(a)} disabled={running} title={a.hint}
                    className={a.heavy ? "heavy" : a.onlyIfStale ? "stale" : ""}>
              <b>{a.label}{a.onlyIfStale ? ` (${st.stale.toLocaleString()})` : ""}</b>
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
            To cover the whole market: <b>Load all companies</b> once, then <b>Refresh prices &amp;
            table</b>. Afterwards <b>Fetch new filings</b> daily or weekly keeps it current.
          </p>
        </div>
      )}
    </div>
  );
}
