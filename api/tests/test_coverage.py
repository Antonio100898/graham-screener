import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from screener import coverage
from screener.models import Fact, Provenance


def test_fiscal_calendar_regression_companies_stay_in_coverage_sample():
    assert {
        "VALU", "MAMA", "MAGN", "WFRD", "RUSHA", "CODI", "TKR", "UHAL",
        "GCO", "PPIH", "AAP", "EML", "BBW", "LFCR",
        "BMRN", "BRKR", "DPZ", "JBHT", "RDAR", "MHUAF", "SHGI",
    } <= set(coverage.PINNED)


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


def test_payload_audit_distinguishes_the_same_tag_on_two_share_classes(
    tmp_path, monkeypatch,
):
    dashboard = tmp_path / "dashboard.json"
    source = {
        "tag": ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic + "
                "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic"),
        "components": [
            {"tag": "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
             "segments": "ClassOfStock=CommonClassA;"},
            {"tag": "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
             "segments": "ClassOfStock=NonvotingCommonStock;"},
        ],
    }
    dashboard.write_text(json.dumps({"rows": [{
        "ticker": "TWOCLASS", "sources": {"weighted_shares": source},
    }]}))
    monkeypatch.setattr(coverage, "DASHBOARD", dashboard)

    assert coverage.audit_payload() == []

    source["components"][1]["segments"] = "ClassOfStock=CommonClassA;"
    dashboard.write_text(json.dumps({"rows": [{
        "ticker": "TWOCLASS", "sources": {"weighted_shares": source},
    }]}))
    assert "counts WeightedAverageNumberOfSharesOutstandingBasic twice" in \
        coverage.audit_payload()[0]


def test_bank_note_parts_are_classified_as_contained_debt():
    for tag in (
        "NotesPayableToBank",
        "NotesPayableToBankCurrent",
        "NotesPayableToBankNoncurrent",
    ):
        assert any(rx.search(tag) for rx, _ in coverage._OOS_COMPILED)


def test_mixed_investment_and_sector_detail_gaps_have_explicit_scope_rules():
    for tag in (
        "LongTermInvestmentsAndReceivablesNet",
        "InterestAndDividendIncomeSecurities",
        "ProvisionForLoanAndLeaseLosses",
        "RelatedPartyDepositLiabilities",
        "OtherPayablesToBrokerDealersAndClearingOrganizations",
        "GainLossOnSaleOfAccountsReceivable",
        "DepositAssets",
        "DeferredIncomeRevenueRecognized",
    ):
        assert any(rx.search(tag) for rx, _ in coverage._OOS_COMPILED)


def test_latest_filing_detail_gaps_have_explicit_scope_rules():
    for tag in (
        "NontradeReceivablesNoncurrent",
        "NontradeReceivables",
        "SaleLeasebackTransactionHistoricalCost",
        "InterestCreditedToPolicyOwnerAccount",
        "SalesCommissionsAndFees",
        "ShortdurationInsuranceContractsDiscountedLiabilitiesAggregateDiscount",
        "EquipmentExpense",
        "DirectCommunicationsAndUtilitiesCosts",
        "DirectTaxesAndLicensesCosts",
        "OperatingInsuranceAndClaimsCostsProduction",
        "RetailRelatedInventoryMerchandise",
        "IntangibleAssetsCurrent",
        "DeferredSalesInducementsAmortizationExpense",
        "ClosedBlockAssetsAndLiabilitiesMaximumFutureEarningsToBeRecognized",
        "ReportingUnitZeroOrNegativeCarryingAmountAmountOfAllocatedGoodwill",
    ):
        assert any(rx.search(tag) for rx, _ in coverage._OOS_COMPILED)

    # These two are useful earnings-quality inputs, not registry exemptions.
    chain_tags = coverage._read_chain_tags()
    assert "OtherNonrecurringIncomeExpense" in chain_tags
    assert "OtherNonrecurringExpense" in chain_tags
    assert "SaleAndLeasebackTransactionGainLossNet" in chain_tags
    assert "InducedConversionOfConvertibleDebtExpense" in chain_tags
    assert "AmountRecognizedInIncomeDueToInflationaryAccounting" in chain_tags


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


def test_identity_check_uses_same_year_weighted_shares_not_later_outstanding():
    annual = SimpleNamespace(value=Decimal("2962528"))
    snap = SimpleNamespace(
        annual_share_counts={2024: annual},
        shares_outstanding=SimpleNamespace(value=Decimal("6105525")),
    )

    assert coverage._identity_reported_shares(snap, 2024) == Decimal("2962528")


def test_balance_sheet_identity_refuses_mismatched_periods():
    def instant(value, end):
        return Fact(value=Decimal(str(value)), provenance=Provenance(
            concept="instant", tag="us-gaap:instant", fiscal_year=None,
            form="10-Q", accession="q26", filed=date(2026, 8, 1),
            period_end=end,
        ))

    snap = SimpleNamespace(
        total_assets=instant(1000, date(2026, 6, 30)),
        total_liabilities=instant(400, date(2025, 12, 31)),
    )
    failure = coverage._balance_sheet_period_failure("STALE", snap)
    assert "different balance sheets" in failure

    snap.total_liabilities = instant(400, date(2026, 6, 30))
    assert coverage._balance_sheet_period_failure("CURRENT", snap) is None
