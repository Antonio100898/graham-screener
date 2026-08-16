"""One background sync at a time, with progress the UI can poll.

Deliberately a single in-process thread: this is a local single-user tool, so a
job queue would be machinery with nothing to do. The lock exists because two
concurrent loads would fight over the SEC rate limiter and the same SQLite rows.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone

from . import store, sync

_lock = threading.Lock()
_thread: threading.Thread | None = None
_cancel = threading.Event()
_state: dict = {"status": "idle", "command": None, "message": "", "done": 0, "total": 0,
                "started": None, "finished": None, "error": None}


class JobCancelled(Exception):
    """Raised inside the worker at the next progress checkpoint."""

COMMANDS = {
    "bootstrap": ("Derive from local cache", sync.bootstrap, ()),
    "bulk": ("Load every US filer from SEC", sync.bulk, ()),
    "metadata": ("Load sectors and exchanges from SEC", sync.metadata, ()),
    "daily": ("Update companies that filed recently", sync.daily, ("days",)),
    "derive": ("Recompute after an engine change", sync.derive, ()),
    "export": ("Refresh prices and rebuild the dashboard", sync.export, ()),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _progress(message: str, done: int = 0, total: int = 0) -> None:
    """Progress checkpoints double as cancellation points — the worker stops at the
    next one, leaving whatever it already committed intact."""
    if _cancel.is_set():
        raise JobCancelled()
    _state.update(message=message, done=done, total=total)


def start(command: str, **kwargs) -> tuple[bool, str]:
    """Returns (started, message). Refuses rather than queueing — a second heavy
    load while one is running only slows both down."""
    global _thread
    if command not in COMMANDS:
        return False, f"unknown command: {command}"
    with _lock:
        if _state["status"] == "running":
            return False, f"{_state['command']} is already running"
        _cancel.clear()
        _state.update(status="running", command=command, message="starting…", done=0, total=0,
                      started=_now(), finished=None, error=None)

    label, fn, accepted = COMMANDS[command]
    call_kwargs = {k: v for k, v in kwargs.items() if k in accepted}

    def run():
        # The connection lives and dies with the job. A cancelled job that left one
        # open would hold a write transaction and lock out every later writer.
        conn = store.connect()
        try:
            fn(conn, progress=_progress, **call_kwargs)
            conn.commit()
            _state.update(status="done", message=f"{label} — finished")
        except JobCancelled:
            conn.commit()  # keep the work already done, then release the lock
            _state.update(status="cancelled", message=f"{label} — stopped; work already done is kept")
        except Exception as exc:
            conn.rollback()
            traceback.print_exc()
            _state.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300],
                          message="failed")
        finally:
            conn.close()
            _state["finished"] = _now()

    _thread = threading.Thread(target=run, name=f"sync-{command}", daemon=True)
    _thread.start()
    return True, label


def cancel() -> bool:
    if _state["status"] != "running":
        return False
    _cancel.set()
    _state["message"] = "stopping…"
    return True


def status() -> dict:
    conn = store.connect()
    try:
        return {**_state, "store": store.stats(conn)}
    except Exception as exc:  # a status poll must never fail because a job is writing
        return {**_state, "store": None, "store_error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        conn.close()
