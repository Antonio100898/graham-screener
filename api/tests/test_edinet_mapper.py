from decimal import Decimal

import pytest

from screener.normalize import build_snapshot
from screener.sources import edinet_mapper


def _record(document, entity, security):
    return {
        "docID": document,
        "edinetCode": entity,
        "secCode": security,
        "docTypeCode": "120",
        "xbrlFlag": "1",
        "submitDateTime": "2026-06-19 15:30",
        "periodStart": "2025-04-01",
        "periodEnd": "2026-03-31",
    }


def _fact(namespace, tag, value, *, unit="JPY", start="2025-04-01",
          end="2026-03-31", dimensions=None, document="S100YETA"):
    return {
        "namespace": f"http://disclosure.edinet-fsa.go.jp/taxonomy/{namespace}",
        "tag": tag,
        "value": Decimal(str(value)),
        "unit": unit,
        "start": start,
        "end": end,
        "dimensions": dimensions or [],
        "document_id": document,
        "entity": "E02367-000" if document == "S100Y9NX" else "E01772-000",
        "source_file": "XBRL/PublicDoc/annual.xbrl",
    }


def _entry(bundle, concept, unit="JPY"):
    return bundle["facts"]["canonical"][concept]["units"][unit][0]


def test_missing_period_end_is_an_unsupported_filing(monkeypatch):
    record = _record("S100WK02", "E00001", "11110")
    record["periodEnd"] = None
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: [])

    with pytest.raises(ValueError, match="no period end"):
        edinet_mapper.build_edinet_companyfacts(record, b"archive", ticker="1111.T")


def test_panasonic_ifrs_concepts_keep_filing_evidence_and_prefer_statement(monkeypatch):
    raw = [
        _fact("jpcrp_cor", "RevenueIFRSSummaryOfBusinessResults", 8048722000000),
        _fact("jpigp_cor", "RevenueIFRS", 8048722000001),
        _fact("jpigp_cor", "DilutedEarningsLossPerShareIFRS", "81.17",
              unit="JPY/shares"),
        _fact("jpigp_cor", "AssetsIFRS", 10172412000000, start=None),
        _fact("jpigp_cor", "RevenueIFRS", 1,
              dimensions=[{"axis": "ConsolidationAxis", "member": "NonConsolidatedMember"}]),
        _fact("jpigp_cor", "UnknownRevenue", 999),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)

    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100YETA", "E01772", "67520"), b"archive", ticker="6752.T")

    revenue = _entry(bundle, "Revenues")
    assert Decimal(revenue["val"]) == Decimal("8048722000001")
    assert revenue["_source_tag"] == "RevenueIFRS"
    assert revenue["_source_namespace"] == "jpigp_cor"
    assert revenue["_normalized_tag"] == "Revenues"
    assert revenue["_source_document"] == revenue["accn"] == "S100YETA"
    assert revenue["_source_unit"] == "JPY"
    assert revenue["_canonical_adapter"] == "edinet_xbrl"
    assert (revenue["start"], revenue["end"], revenue["filed"]) == (
        "2025-04-01", "2026-03-31", "2026-06-19")
    assert Decimal(_entry(bundle, "EarningsPerShareDiluted", "JPY/shares")["val"]) == Decimal("81.17")
    assert Decimal(_entry(bundle, "Assets")["val"]) == Decimal("10172412000000")
    assert "start" not in _entry(bundle, "Assets")
    assert set(bundle["facts"]["canonical"]) == {
        "Revenues", "EarningsPerShareDiluted", "Assets"}
    assert bundle["_adapter"]["reporting_currency"] == "JPY"
    assert bundle["_adapter"]["security_code"] == "67520"
    assert bundle["_adapter"]["reports"][0]["period_end"] == "2026-03-31"
    snapshot = build_snapshot("6752.T", "E01772", bundle)
    assert snapshot.reporting_currency == "JPY"
    assert snapshot.total_assets.value == Decimal("10172412000000")
    assert snapshot.total_assets.provenance.tag == "jpigp_cor:AssetsIFRS"
    assert snapshot.total_assets.provenance.document == "S100YETA"


def test_nintendo_jgaap_known_rows_and_missing_diluted_eps(monkeypatch):
    raw = [
        _fact("jppfs_cor", "NetSales", 2313051000000, document="S100Y9NX"),
        _fact("jpcrp_cor", "BasicEarningsLossPerShareSummaryOfBusinessResults",
              "364.51", unit="JPY/shares", document="S100Y9NX"),
        _fact("jppfs_cor", "Assets", 3805312000000, start=None,
              document="S100Y9NX"),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    bundle = edinet_mapper.build_edinet_companyfacts(
        {**_record("S100Y9NX", "E02367", "79740"),
         "filerName": "任天堂株式会社", "filerNameEnglish": "Nintendo Co., Ltd."},
        b"archive")
    assert bundle["entityName"] == "Nintendo Co., Ltd."
    assert Decimal(_entry(bundle, "Revenues")["val"]) == Decimal("2313051000000")
    assert Decimal(_entry(bundle, "EarningsPerShareBasic", "JPY/shares")["val"]) == Decimal("364.51")
    assert Decimal(_entry(bundle, "Assets")["val"]) == Decimal("3805312000000")
    assert "EarningsPerShareDiluted" not in bundle["facts"]["canonical"]


def test_mixed_currency_and_dimensioned_balance_do_not_define_statement(monkeypatch):
    raw = [
        _fact("jpigp_cor", "AssetsIFRS", 100, start=None,
              dimensions=[{"axis": "ConsolidationAxis", "member": "NonConsolidatedMember"}]),
        _fact("jpcrp_cor", "RevenueIFRSSummaryOfBusinessResults", 200),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    with pytest.raises(ValueError, match="balance currency"):
        edinet_mapper.build_edinet_companyfacts(
            _record("S100YETA", "E01772", "67520"), b"archive")

    raw[0]["dimensions"] = []
    raw.append(_fact("jpigp_cor", "RevenueIFRS", 300, unit="USD"))
    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100YETA", "E01772", "67520"), b"archive")
    assert list(bundle["facts"]["canonical"]["Revenues"]["units"]) == ["JPY"]


def test_other_entity_context_cannot_supply_the_reported_balance(monkeypatch):
    foreign_balance = _fact("jpigp_cor", "AssetsIFRS", 100, start=None)
    foreign_balance["entity"] = "E99999-000"
    monkeypatch.setattr(edinet_mapper, "xbrl_facts",
                        lambda archive, doc: [foreign_balance])
    with pytest.raises(ValueError, match="balance currency"):
        edinet_mapper.build_edinet_companyfacts(
            _record("S100YETA", "E01772", "67520"), b"archive")


def test_complete_corrected_report_keeps_its_own_filing_form(monkeypatch):
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: [
        _fact("jpigp_cor", "AssetsIFRS", 10172412000000, start=None)])
    record = {**_record("S100YETA", "E01772", "67520"), "docTypeCode": "130"}
    bundle = edinet_mapper.build_edinet_companyfacts(record, b"archive")
    assert _entry(bundle, "Assets")["form"] == "JP-AR/A"


def test_ifrs_summary_is_used_only_when_direct_row_is_missing(monkeypatch):
    raw = [
        _fact("jpcrp_cor", "RevenueIFRSSummaryOfBusinessResults", 8048722000000),
        _fact("jpigp_cor", "AssetsIFRS", 10172412000000, start=None),
        _fact("jpcrp_cor", "BasicEarningsLossPerShareSummaryOfBusinessResults",
              999, unit="JPY/shares"),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100YETA", "E01772", "67520"), b"archive")
    assert _entry(bundle, "Revenues")["_source_namespace"] == "jpcrp_cor"
    assert Decimal(_entry(bundle, "Revenues")["val"]) == Decimal("8048722000000")
    assert "EarningsPerShareBasic" not in bundle["facts"]["canonical"]


def test_five_year_summary_eps_remains_on_reported_fiscal_periods(monkeypatch):
    raw = [_fact("jpigp_cor", "AssetsIFRS", 10172412000000, start=None)]
    for year, eps in [(2022, "109.37"), (2023, "113.72"),
                      (2024, "190.15"), (2025, "156.83"), (2026, "81.17")]:
        raw.append(_fact(
            "jpcrp_cor", "DilutedEarningsLossPerShareIFRSSummaryOfBusinessResults",
            eps, unit="JPY/shares", start=f"{year-1}-04-01", end=f"{year}-03-31"))
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100YETA", "E01772", "67520"), b"archive")
    entries = bundle["facts"]["canonical"]["EarningsPerShareDiluted"]["units"]["JPY/shares"]
    assert [entry["end"] for entry in entries] == [f"{year}-03-31" for year in range(2022, 2027)]
    assert [Decimal(entry["val"]) for entry in entries] == [
        Decimal(value) for value in ("109.37", "113.72", "190.15", "156.83", "81.17")]


def test_observed_ifrs_statement_rows_map_without_inventing_missing_fields(monkeypatch):
    balances = {
        "AssetsIFRS": ("Assets", 1000),
        "CurrentAssetsIFRS": ("AssetsCurrent", 400),
        "TotalCurrentLiabilitiesIFRS": ("LiabilitiesCurrent", 200),
        "LiabilitiesIFRS": ("Liabilities", 600),
        "EquityAttributableToOwnersOfParentIFRS": ("StockholdersEquity", 350),
        "EquityIFRS": (
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 400),
        "CashAndCashEquivalentsIFRS": ("CashAndCashEquivalentsAtCarryingValue", 120),
        "InventoriesCAIFRS": ("InventoryNet", 80),
        "GoodwillIFRS": ("Goodwill", 30),
        "IntangibleAssetsIFRS": ("IntangibleAssetsNetExcludingGoodwill", 20),
        "ShortTermDebtIncludingCurrentPortionOfLongTermDebtCLIFRS": ("DebtCurrent", 50),
    }
    flows = {
        "OperatingProfitLossIFRS": ("OperatingIncomeLoss", 90),
        "ProfitLossAttributableToOwnersOfParentIFRS": ("NetIncomeLoss", 70),
        "NetCashProvidedByUsedInOperatingActivitiesIFRS": (
            "NetCashProvidedByUsedInOperatingActivities", 110),
        "DepreciationAndAmortizationOpeCFIFRS": ("DepreciationAndAmortization", 25),
        "DividendsPaidToOwnersOfParentFinCFIFRS": ("PaymentsOfDividendsCommonStock", -15),
    }
    raw = [
        *(_fact("jpigp_cor", source, value, start=None)
          for source, (_, value) in balances.items()),
        *(_fact("jpigp_cor", source, value)
          for source, (_, value) in flows.items()),
        _fact("jpigp_cor", "BasicEarningsLossPerShareIFRS", "82.00",
              unit="JPY/shares"),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100YETA", "E01772", "67520"), b"archive")
    for source, (canonical, value) in {**balances, **flows}.items():
        entry = _entry(bundle, canonical)
        assert entry["_source_tag"] == source
        expected = abs(value) if canonical == "PaymentsOfDividendsCommonStock" else value
        assert Decimal(entry["val"]) == expected
    assert Decimal(_entry(bundle, "EarningsPerShareBasic", "JPY/shares")["val"]) == Decimal("82.00")
    dividend = _entry(bundle, "PaymentsOfDividendsCommonStock")
    assert dividend["_source_concept"].endswith("source signed negative)")
    snapshot = build_snapshot("6752.T", "E01772", bundle)
    assert snapshot.current_assets.value == 400
    assert snapshot.current_liabilities.value == 200
    assert snapshot.total_liabilities.value == 600
    assert snapshot.short_term_debt.value == 50


def test_observed_jgaap_rows_keep_net_assets_and_intangibles_unmapped(monkeypatch):
    balances = {
        "Assets": ("Assets", 1000),
        "CurrentAssets": ("AssetsCurrent", 400),
        "CurrentLiabilities": ("LiabilitiesCurrent", 200),
        "Liabilities": ("Liabilities", 600),
        "Inventories": ("InventoryNet", 80),
    }
    flows = {
        "NetSales": ("Revenues", 500),
        "OperatingIncome": ("OperatingIncomeLoss", 90),
        "ProfitLossAttributableToOwnersOfParent": ("NetIncomeLoss", 70),
        "ProfitLoss": ("ProfitLoss", 75),
        "IncomeTaxes": ("IncomeTaxExpenseBenefit", 25),
        "NetCashProvidedByUsedInOperatingActivities": (
            "NetCashProvidedByUsedInOperatingActivities", 110),
        "CashDividendsPaidFinCF": ("PaymentsOfOrdinaryDividends", -15),
    }
    raw = [
        *(_fact("jppfs_cor", source, value, start=None, document="S100Y9NX")
          for source, (_, value) in balances.items()),
        *(_fact("jppfs_cor", source, value, document="S100Y9NX")
          for source, (_, value) in flows.items()),
        _fact("jppfs_cor", "NetAssets", 400, start=None, document="S100Y9NX"),
        _fact("jppfs_cor", "IntangibleAssets", 20, start=None,
              document="S100Y9NX"),
    ]
    monkeypatch.setattr(edinet_mapper, "xbrl_facts", lambda archive, doc: raw)
    bundle = edinet_mapper.build_edinet_companyfacts(
        _record("S100Y9NX", "E02367", "79740"), b"archive")
    for source, (canonical, value) in {**balances, **flows}.items():
        entry = _entry(bundle, canonical)
        assert entry["_source_tag"] == source
        expected = abs(value) if canonical == "PaymentsOfOrdinaryDividends" else value
        assert Decimal(entry["val"]) == expected
    assert "StockholdersEquity" not in bundle["facts"]["canonical"]
    assert "IntangibleAssetsNetExcludingGoodwill" not in bundle["facts"]["canonical"]
