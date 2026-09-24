"""Translate named EDINET XBRL concepts into the canonical facts contract."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from .edinet import xbrl_facts


ADAPTER_KIND = "edinet_xbrl"
FORM = "JP-AR"

# Each source concept has a checked accounting meaning. The order of a source
# group's entries is the preference when statement and summary values coexist.
_CONCEPTS = {
    "jpigp_cor": {
        "Revenues": ("RevenueIFRS",),
        "AssetsCurrent": ("CurrentAssetsIFRS",),
        "LiabilitiesCurrent": ("TotalCurrentLiabilitiesIFRS",),
        "Liabilities": ("LiabilitiesIFRS",),
        "StockholdersEquity": ("EquityAttributableToOwnersOfParentIFRS",),
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": (
            "EquityIFRS",),
        "CashAndCashEquivalentsAtCarryingValue": ("CashAndCashEquivalentsIFRS",),
        "InventoryNet": ("InventoriesCAIFRS",),
        "Goodwill": ("GoodwillIFRS",),
        "IntangibleAssetsNetExcludingGoodwill": ("IntangibleAssetsIFRS",),
        "DebtCurrent": ("ShortTermDebtIncludingCurrentPortionOfLongTermDebtCLIFRS",),
        "OperatingIncomeLoss": ("OperatingProfitLossIFRS",),
        "NetIncomeLoss": ("ProfitLossAttributableToOwnersOfParentIFRS",),
        "EarningsPerShareBasic": ("BasicEarningsLossPerShareIFRS",),
        "EarningsPerShareDiluted": ("DilutedEarningsLossPerShareIFRS",),
        "NetCashProvidedByUsedInOperatingActivities": (
            "NetCashProvidedByUsedInOperatingActivitiesIFRS",),
        "DepreciationAndAmortization": ("DepreciationAndAmortizationOpeCFIFRS",),
        "PaymentsOfDividendsCommonStock": ("DividendsPaidToOwnersOfParentFinCFIFRS",),
        "Assets": ("AssetsIFRS",),
    },
    "jppfs_cor": {
        "Revenues": ("NetSales",),
        "AssetsCurrent": ("CurrentAssets",),
        "LiabilitiesCurrent": ("CurrentLiabilities",),
        "Liabilities": ("Liabilities",),
        "InventoryNet": ("Inventories",),
        "OperatingIncomeLoss": ("OperatingIncome",),
        "NetIncomeLoss": ("ProfitLossAttributableToOwnersOfParent",),
        "ProfitLoss": ("ProfitLoss",),
        "IncomeTaxExpenseBenefit": ("IncomeTaxes",),
        "NetCashProvidedByUsedInOperatingActivities": (
            "NetCashProvidedByUsedInOperatingActivities",),
        "PaymentsOfOrdinaryDividends": ("CashDividendsPaidFinCF",),
        "Assets": ("Assets",),
    },
    "jpcrp_cor": {
        "Revenues": ("RevenueIFRSSummaryOfBusinessResults",
                     "NetSalesSummaryOfBusinessResults"),
        "NetIncomeLoss": (
            "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
            "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        ),
        "StockholdersEquity": (
            "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",),
        "Assets": ("TotalAssetsIFRSSummaryOfBusinessResults",
                   "TotalAssetsSummaryOfBusinessResults"),
        "CashAndCashEquivalentsAtCarryingValue": (
            "CashAndCashEquivalentsIFRSSummaryOfBusinessResults",
            "CashAndCashEquivalentsSummaryOfBusinessResults",
        ),
        "NetCashProvidedByUsedInOperatingActivities": (
            "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
            "NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults",
        ),
        "EarningsPerShareBasic": (
            "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
            "BasicEarningsLossPerShareSummaryOfBusinessResults",
        ),
        "EarningsPerShareDiluted": (
            "DilutedEarningsLossPerShareIFRSSummaryOfBusinessResults",),
    },
}
_SOURCE_TO_CANONICAL = {
    (namespace, tag): (canonical, rank)
    for namespace, mappings in _CONCEPTS.items()
    for canonical, tags in mappings.items()
    for rank, tag in enumerate(tags)
}
_PER_SHARE = {"EarningsPerShareDiluted", "EarningsPerShareBasic"}
_CASH_OUTFLOWS = {"PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"}


def _taxonomy(namespace: str) -> str | None:
    for name in _CONCEPTS:
        if namespace.rstrip("/").endswith("/" + name):
            return name
    return None


def _filing_date(record: dict) -> str:
    value = record.get("submitDateTime") or record.get("filed")
    if not value:
        raise ValueError("EDINET filing has no submission date")
    result = str(value)[:10]
    date.fromisoformat(result)
    return result


def build_edinet_companyfacts(
    record: dict, archive: bytes, *, ticker: str | None = None,
) -> dict:
    """Build a canonical bundle for one filed annual EDINET XBRL archive.

    Only undimensioned, named concepts in the filing's own monetary unit enter.
    Missing concepts remain absent; no value is inferred from another row.
    """
    if record.get("docTypeCode") not in {"120", "130"} or record.get("xbrlFlag") != "1":
        raise ValueError("EDINET record is not an XBRL annual securities report")
    document_id = record["docID"]
    entity_id = record["edinetCode"]
    security_code = record["secCode"]
    period_end = record.get("periodEnd")
    if not isinstance(period_end, str) or not period_end:
        raise ValueError("EDINET annual filing has no period end")
    date.fromisoformat(period_end)
    filed = _filing_date(record)
    raw = xbrl_facts(archive, document_id)
    anchors = {
        (namespace, fact["unit"])
        for fact in raw
        if (namespace := _taxonomy(fact["namespace"])) in {"jpigp_cor", "jppfs_cor"}
        and fact["tag"] == ("AssetsIFRS" if namespace == "jpigp_cor" else "Assets")
        and (fact.get("entity") or "").partition("-")[0] == entity_id
        and fact["start"] is None and fact["end"] == period_end
        and not fact["dimensions"] and fact["end"] <= filed
        and isinstance(fact["unit"], str)
        and len(fact["unit"]) == 3 and fact["unit"].isupper()
        and fact["unit"].isalpha()
    }
    if len(anchors) != 1:
        raise ValueError("EDINET annual filing lacks one reported balance currency")
    statement_basis, reporting_currency = anchors.pop()

    candidates: dict[tuple, tuple[int, dict, str, str]] = {}
    for fact in raw:
        namespace = _taxonomy(fact["namespace"])
        if (namespace is None or fact["dimensions"] or not fact["end"]
                or (fact.get("entity") or "").partition("-")[0] != entity_id):
            continue
        if namespace == "jpcrp_cor":
            if ("IFRS" in fact["tag"]) != (statement_basis == "jpigp_cor"):
                continue
        elif namespace != statement_basis:
            continue
        mapped = _SOURCE_TO_CANONICAL.get((namespace, fact["tag"]))
        if mapped is None:
            continue
        canonical, rank = mapped
        if fact["tag"].endswith("SummaryOfBusinessResults"):
            rank += 1
        unit = fact["unit"]
        if (not isinstance(unit, str) or
                (canonical in _PER_SHARE and not unit.endswith("/shares")) or
                (canonical not in _PER_SHARE and "/" in unit)):
            continue
        currency = unit.removesuffix("/shares")
        if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
            continue
        if currency != reporting_currency:
            continue
        if fact["end"] > filed:
            continue
        key = (canonical, fact["start"], fact["end"], unit)
        previous = candidates.get(key)
        if previous is None or rank < previous[0]:
            candidates[key] = (rank, fact, namespace, currency)

    canonical_facts: dict = defaultdict(lambda: {"units": defaultdict(list)})
    for (canonical, start, end, unit), (_, fact, namespace, currency) in candidates.items():
        if end > period_end:
            continue
        value = abs(fact["value"]) if canonical in _CASH_OUTFLOWS else fact["value"]
        entry = {
            "val": str(value),
            "accn": document_id,
            "fy": int(period_end[:4]),
            "fp": "FY",
            "form": f"{FORM}/A" if record["docTypeCode"] == "130" else FORM,
            "filed": filed,
            "end": end,
            "_canonical_adapter": ADAPTER_KIND,
            "_source_namespace": namespace,
            "_source_tag": fact["tag"],
            "_source_unit": unit,
            "_source_document": document_id,
            "_normalized_tag": canonical,
            "_source_file": fact["source_file"],
        }
        if start is not None:
            entry["start"] = start
        if value != fact["value"]:
            entry["_source_concept"] = (
                f"{canonical} (cash outflow magnitude; source signed negative)"
            )
        canonical_facts[canonical]["units"][unit].append(entry)

    return {
        "cik": entity_id,
        "entityName": (record.get("filerNameEnglish") or record.get("filerNameEn")
                       or record.get("filerName") or entity_id),
        "facts": {"canonical": {
            tag: {"units": dict(data["units"])}
            for tag, data in canonical_facts.items()
        }},
        "_adapter": {
            "kind": ADAPTER_KIND,
            "statement_basis": "canonical",
            "reporting_currency": reporting_currency,
            "quote_currency": reporting_currency,
            "ticker": ticker,
            "security_code": security_code,
            "security_basis": "PRIMARY_ORDINARY_SHARE",
            "reports": [{
                "fiscal_year": int(period_end[:4]),
                "published": filed,
                "period_start": record.get("periodStart"),
                "period_end": period_end,
                "document": document_id,
                "mapped_facts": sum(
                    len(entries)
                    for data in canonical_facts.values()
                    for entries in data["units"].values()
                ),
            }],
        },
    }
