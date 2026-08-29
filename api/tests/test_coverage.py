import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from screener import coverage
from screener.models import Fact, Provenance


def test_payload_audit_treats_share_reconciliation_inputs_as_witnesses(
    tmp_path, monkeypatch,
):
    dashboard = tmp_path / "dashboard.json"
    dashboard.write_text(json.dumps({"rows": [{
        "ticker": "SCALE",
        "sources": {
            "weighted_shares": {
                "tag": "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                "concept": (
                    "WeightedAverageNumberOfDilutedSharesOutstanding "
                    "(scaled 1000x: reconciled to EPS and income)"
                ),
                "components": [
                    {"tag": "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"},
                    {"tag": "us-gaap:EarningsPerShareDiluted"},
                    {"tag": "us-gaap:NetIncomeLoss"},
                ],
            },
        },
    }]}))
    monkeypatch.setattr(coverage, "DASHBOARD", dashboard)

    assert coverage.audit_payload() == []


def test_bank_note_parts_are_classified_as_contained_debt():
    for tag in (
        "NotesPayableToBank",
        "NotesPayableToBankCurrent",
        "NotesPayableToBankNoncurrent",
    ):
        assert any(rx.search(tag) for rx, _ in coverage._OOS_COMPILED)


def test_identity_check_skips_continuing_operations_eps_against_total_income():
    def fact(value, tag):
        return Fact(value=Decimal(str(value)), provenance=Provenance(
            concept=tag, tag=f"us-gaap:{tag}", fiscal_year=2025, form="10-K",
            accession="k25", filed=date(2026, 3, 1), period_end=date(2025, 12, 31),
        ))

    snap = SimpleNamespace(
        annual_eps={2025: fact(-10.51, "IncomeLossFromContinuingOperationsPerDilutedShare")},
        annual_net_income={2025: fact(-384826, "NetIncomeLoss")},
        annual_preferred_dividends={},
    )

    assert coverage._identity_implied_shares(snap, {}, 2025) is None
