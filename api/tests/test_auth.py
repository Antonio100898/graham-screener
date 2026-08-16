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
