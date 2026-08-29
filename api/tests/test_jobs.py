from datetime import datetime, timedelta, timezone

from screener import jobs, store


def test_hourly_schedule_uses_the_latest_export_as_its_first_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_QUOTE_REFRESH_SECONDS", "3600")
    conn = store.connect(tmp_path / "schedule.db")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    store.set_state(conn, "last_export", (now - timedelta(minutes=59)).isoformat())
    conn.commit()

    assert jobs._quote_schedule(conn, now)["due"] is False
    assert jobs._quote_schedule(conn, now + timedelta(minutes=2))["due"] is True
    conn.close()


def test_due_scheduler_starts_one_universe_quote_job_and_records_attempt(
        tmp_path, monkeypatch):
    database = tmp_path / "schedule.db"
    original_connect = store.connect
    original_connect(database).close()
    dashboard = tmp_path / "dashboard.json"
    dashboard.write_text('{"rows":[]}', encoding="utf-8")
    monkeypatch.setattr(jobs.sync, "DASHBOARD_JSON", dashboard)
    monkeypatch.setattr(jobs.store, "connect", lambda: original_connect(database))
    monkeypatch.setenv("SCREENER_AUTO_QUOTES", "1")
    monkeypatch.setenv("SCREENER_QUOTE_REFRESH_SECONDS", "3600")
    started = []
    monkeypatch.setattr(jobs, "start", lambda command: (started.append(command) or True, command))
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    assert jobs.run_scheduled_quote_check(now) is True
    assert started == ["quotes"]
    conn = original_connect(database)
    assert store.get_state(conn, "last_quote_refresh_attempt") == now.isoformat(timespec="seconds")
    conn.close()
