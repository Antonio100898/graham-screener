"""Evidence assembly and invalidation — the boundary shared by every pipeline."""
import json

from screener import evidence, store
from screener.sources import dera


class EdgarStub:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def company_facts(self, cik):  # pragma: no cover - supplied facts should win
        raise AssertionError("unexpected network fetch")


def test_loader_always_adds_dimensioned_and_cover_evidence(tmp_path):
    cik, ticker = "0000000001", "ADR"
    facts = {"facts": {"us-gaap": {}}}
    dimensioned = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {}}}}
    (tmp_path / f"dimensioned_{cik}.json").write_text(json.dumps(dimensioned))
    conn = store.connect(tmp_path / "store.db")
    store.set_cover(conn, cik, [{
        "symbol": ticker,
        "title": "American Depositary Shares, each representing 13 Ordinary Shares",
        "ratio": 13,
    }], "accn-1")

    bundle = evidence.EvidenceLoader(conn, EdgarStub(tmp_path)).load(cik, ticker, facts)

    assert bundle.facts is facts
    assert bundle.dimensioned == dimensioned
    assert bundle.receipt["ratio"] == "13"
    assert bundle.receipt["accn"] == "accn-1"


def test_loader_uses_stored_symbol_when_current_sec_mapping_is_absent(tmp_path):
    cik, ticker = "0000000001", "OLD"
    facts = {"facts": {"us-gaap": {}}}
    conn = store.connect(tmp_path / "store.db")
    store.upsert_company(conn, cik, ticker, "Formerly listed")
    store.set_cover(conn, cik, [{
        "symbol": ticker,
        "title": "Class A common stock",
        "ratio": None,
    }], "accn-1")

    bundle = evidence.EvidenceLoader(conn, EdgarStub(tmp_path)).load(cik, None, facts)

    assert bundle.ticker == ticker
    assert bundle.receipt["symbol"] == ticker
    assert bundle.receipt["title"] == "Class A common stock"


def test_changed_cover_invalidates_current_snapshot_until_recomputed(tmp_path):
    cik = "0000000001"
    conn = store.connect(tmp_path / "store.db")
    store.put_snapshot(conn, cik, "ok", {"ticker": "ADR"})
    assert store.needs_recompute(conn) == []

    security = {"symbol": "ADR", "title": "ADS, each representing 2 Ordinary Shares",
                "ratio": 2}
    store.set_cover(conn, cik, [security], "accn-1")
    assert store.needs_recompute(conn) == [cik]

    store.put_snapshot(conn, cik, "ok", {"ticker": "ADR", "receipt_ratio": 2})
    assert store.needs_recompute(conn) == []
    # Reading the identical cover again is idempotent and must not dirty the row.
    store.set_cover(conn, cik, [security], "accn-1")
    assert store.needs_recompute(conn) == []


def test_dera_merge_reports_only_real_evidence_changes(tmp_path):
    cik = "0000000001"
    harvested = {cik: {"facts": {"us-gaap": {"Assets": {"units": {"USD": [{
        "end": "2026-03-31", "val": 10, "accn": "a", "form": "10-Q",
        "filed": "2026-05-01", "fy": 0, "fp": "FY", "segments": "",
    }]}}}}}}
    quarter = dera.Quarter(2026, 1)

    assert dera.merge_into_sidecars(harvested, tmp_path, quarter) == {cik}
    assert dera.merge_into_sidecars(harvested, tmp_path, quarter) == set()
