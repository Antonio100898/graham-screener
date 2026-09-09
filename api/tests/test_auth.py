"""Write protection, used when the instance is reachable off-machine."""
import os

import pytest
from fastapi.testclient import TestClient

from screener import api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SCREENER_TOKEN", "s3cret")
    return TestClient(api.app)


def test_reads_stay_open(client):
    assert client.get("/config").json() == {"write_protected": True}
    assert client.get("/health").status_code == 200


def test_write_without_token_is_refused(client):
    r = client.post("/sync", json={"command": "export"})
    assert r.status_code == 401
    assert "token" in r.json()["detail"]


def test_write_with_wrong_token_is_refused(client):
    r = client.post("/sync", json={"command": "export"}, headers={"X-Screener-Token": "guess"})
    assert r.status_code == 401


def test_write_with_token_is_allowed_through(client):
    # reaches the handler; 409 means the job layer answered, not the gate
    r = client.post("/sync", json={"command": "nope"}, headers={"X-Screener-Token": "s3cret"})
    assert r.status_code == 409


def test_unset_token_leaves_localhost_open(monkeypatch):
    monkeypatch.delenv("SCREENER_TOKEN", raising=False)
    c = TestClient(api.app)
    assert c.get("/config").json() == {"write_protected": False}
    assert c.post("/sync", json={"command": "nope"}).status_code == 409   # not 401


def test_assumption_detail_failure_returns_strict_row_not_http_500(monkeypatch):
    base = {"ticker": "TEST", "cik": "0000000001", "annual_ratios": {}}

    class Connection:
        def close(self):
            pass

    class BrokenLoader:
        def load(self, cik, ticker):
            raise RuntimeError("cached filing bundle is unavailable")

    monkeypatch.setattr(api, "_dashboard_payload", lambda: {"rows": [base]})
    monkeypatch.setattr(api.store, "connect", Connection)
    monkeypatch.setattr(api.evidence, "EvidenceLoader", lambda conn, edgar: BrokenLoader())

    response = TestClient(api.app).get(
        "/company/TEST/dashboard?assume_absent_zero=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "TEST"
    assert payload["assumption_mode"]["status"] == "UNAVAILABLE"
    assert "cached filing bundle is unavailable" in payload["assumption_mode"]["note"]


def test_ratio_gap_overlay_uses_zero_or_not_measurable_without_dashes():
    row = {"annual_ratios": {2025: {"net_margin": 12.5}}}

    details = api._fill_assumed_ratio_gaps(row)
    cell = row["annual_ratios"][2025]

    assert cell["net_margin"] == 12.5
    assert cell["revenue"] == 0
    assert cell["award_pct"] == 0
    assert "pe_undefined" in cell
    assert "current_ratio_undefined" in cell
    assert not any(value is None for value in cell.values())
    assert any(item["field"] == "revenue" and item["fiscal_year"] == 2025
               for item in details)
