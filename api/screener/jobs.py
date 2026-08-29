"""One background sync at a time, with progress the UI can poll.

Deliberately a single in-process thread: this is a local single-user tool, so a
job queue would be machinery with nothing to do. The lock exists because two
concurrent loads would fight over the SEC rate limiter and the same SQLite rows.
"""
from __future__ import annotations

import os
import threading
import traceback
from datetime import datetime, timedelta, timezone

from . import store, sync

_lock = threading.Lock()
_thread: threading.Thread | None = None
_cancel = threading.Event()
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
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
    "quotes": ("Refresh every universe quote", sync.quotes, ()),
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


def _auto_quotes_enabled() -> bool:
    return os.getenv("SCREENER_AUTO_QUOTES", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _quote_interval_seconds() -> int:
    try:
        return max(60, int(os.getenv("SCREENER_QUOTE_REFRESH_SECONDS", "3600")))
    except ValueError:
        return 3600


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _quote_schedule(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    interval = _quote_interval_seconds()
    candidates = [
        _timestamp(store.get_state(conn, "last_quote_refresh_attempt")),
        _timestamp(store.get_state(conn, "last_quote_refresh")),
        _timestamp(store.get_state(conn, "last_export")),
    ]
    last = max((value for value in candidates if value is not None), default=None)
    next_due = last + timedelta(seconds=interval) if last else now
    return {
        "enabled": _auto_quotes_enabled(),
        "running": bool(_scheduler_thread and _scheduler_thread.is_alive()),
        "interval_seconds": interval,
        "next_due": next_due.isoformat(timespec="seconds"),
        "due": bool(not last or now >= next_due),
    }


def run_scheduled_quote_check(now: datetime | None = None) -> bool:
    """Start one due universe refresh. Exposed so the scheduler is testable."""
    if not _auto_quotes_enabled() or not sync.DASHBOARD_JSON.exists():
        return False
    conn = store.connect()
    try:
        if not _quote_schedule(conn, now)["due"]:
            return False
    finally:
        conn.close()
    started, _ = start("quotes")
    if not started:  # another job owns the single worker; retry on the next check
        return False
    attempted = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    conn = store.connect()
    try:
        store.set_state(conn, "last_quote_refresh_attempt", attempted)
        conn.commit()
    finally:
        conn.close()
    return True


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            run_scheduled_quote_check()
        except Exception:
            traceback.print_exc()
        # Check often enough to start close to the hour boundary. A failed job is
        # still rate-limited by last_quote_refresh_attempt, so this cannot hammer
        # the provider every thirty seconds.
        _scheduler_stop.wait(min(30, _quote_interval_seconds()))


def start_hourly_quotes() -> bool:
    """Start the API-lifetime scheduler; safe to call more than once."""
    global _scheduler_thread
    if not _auto_quotes_enabled():
        return False
    with _lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return False
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop, name="hourly-universe-quotes", daemon=True,
        )
        _scheduler_thread.start()
    return True


def stop_hourly_quotes() -> None:
    global _scheduler_thread
    _scheduler_stop.set()
    thread = _scheduler_thread
    if thread and thread.is_alive():
        thread.join(timeout=5)
    _scheduler_thread = None


def status() -> dict:
    conn = store.connect()
    try:
        return {**_state, "store": store.stats(conn), "auto_quotes": _quote_schedule(conn)}
    except Exception as exc:  # a status poll must never fail because a job is writing
        return {**_state, "store": None, "store_error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        conn.close()
