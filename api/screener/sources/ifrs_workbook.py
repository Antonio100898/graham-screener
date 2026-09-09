"""Import adidas' published IFRS statement workbooks as canonical fact evidence.

This is deliberately a narrow pilot adapter, not a generic spreadsheet guesser.
It recognizes the row labels in adidas' consolidated financial-statement
downloads, preserves those labels as provenance, and emits the same canonical
concepts consumed by :mod:`screener.normalize`.

The newest annual report wins when it republishes a comparative year.  That is
important for discontinued operations and accounting restatements: AR2021, for
example, republishes FY2020 on a continuing adidas basis that differs from the
number printed in AR2020.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


FORM = "IFRS-AR"
ADAPTER_KIND = "adidas_ifrs_workbook"
DEFAULT_ENTITY_ID = "IFRS-ADIDAS-AG"
DEFAULT_TICKER = "ADS.DE"

# The legacy AR2019 workbook does not expose Office document timestamps.  The
# report was published with the FY2019 results on this date; later xlsx files
# carry their own final modified date, which is retained as the evidence date.
_LEGACY_REPORT_DATES = {2019: date(2020, 3, 11)}


def _evidence_date(report_year: int, modified: date | None) -> date:
    """A chronological publication proxy that cannot invert report vintages."""
    if report_year in _LEGACY_REPORT_DATES:
        return _LEGACY_REPORT_DATES[report_year]
    # Office metadata is useful in the actual downloads, but file-copying or
    # test creation can replace it with today's date. Only the following-year
    # timestamp is credible for an annual report; otherwise retain ordering from
    # the report year with an explicitly approximate first-quarter date.
    if modified is not None and modified.year == report_year + 1:
        return modified
    return date(report_year + 1, 3, 31)


def _normalise_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _number(value: object) -> tuple[Decimal | None, bool]:
    """Return a statement number and whether it was an explicit nil marker."""
    if value is None or isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float, Decimal)):
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None, False
        return (parsed, False) if parsed.is_finite() else (None, False)
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return None, False
    if text in {"-", "–", "—", "−"}:
        return Decimal(0), True
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("€", "").strip()
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, False
    return (-parsed if negative else parsed), False


def _report_year(path: Path) -> int:
    match = re.search(r"ar(\d{2})(?!\d)", path.stem, re.IGNORECASE)
    if not match:
        raise ValueError(f"cannot identify annual-report year from {path.name}")
    return 2000 + int(match.group(1))


def _xlsx_sheets(path: Path) -> tuple[list[tuple[str, list[list[object]]]], date | None]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - exercised by installation, not parsing
        raise RuntimeError("openpyxl is required to import .xlsx IFRS workbooks") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    modified = workbook.properties.modified
    modified_date = modified.date() if isinstance(modified, datetime) else modified
    sheets = [
        (sheet.title, [list(row) for row in sheet.iter_rows(values_only=True)])
        for sheet in workbook.worksheets
    ]
    workbook.close()
    return sheets, modified_date


def _xls_sheets(path: Path) -> tuple[list[tuple[str, list[list[object]]]], None]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - exercised by installation, not parsing
        raise RuntimeError("xlrd is required to import legacy .xls IFRS workbooks") from exc
    workbook = xlrd.open_workbook(path, on_demand=True)
    sheets = []
    for sheet in workbook.sheets():
        sheets.append((sheet.name, [sheet.row_values(index) for index in range(sheet.nrows)]))
    workbook.release_resources()
    return sheets, None


def _read_workbook(path: Path) -> tuple[list[tuple[str, list[list[object]]]], date | None]:
    if path.suffix.lower() == ".xlsx":
        return _xlsx_sheets(path)
    if path.suffix.lower() == ".xls":
        return _xls_sheets(path)
    raise ValueError(f"unsupported workbook type: {path.name}")


def _statement_kind(sheet_name: str) -> str | None:
    name = sheet_name.lower().replace("_", "-")
    if "fin-position" in name:
        return "balance"
    if "stat-income" in name and "compr" not in name:
        return "income"
    if "cash-flow" in name:
        return "cash_flow"
    return None


def _year_columns(rows: list[list[object]]) -> dict[int, int]:
    """Columns headed by a full fiscal year in adidas' two-year statements."""
    for row in rows[:12]:
        found: dict[int, int] = {}
        for column, value in enumerate(row[:8]):
            # The legacy workbook appends a footnote marker directly to 2018
            # (rendered as ``20181``), so only the leading boundary is reliable.
            matches = re.findall(r"(?<!\d)(20\d{2})", str(value or ""))
            if matches:
                found[int(matches[-1])] = column
        if len(found) >= 2:
            return found
    raise ValueError("could not locate the two fiscal-year columns")


_BALANCE_ROWS = {
    "cash and cash equivalents": "CashAndCashEquivalentsAtCarryingValue",
    "short-term financial assets": "ShortTermInvestments",
    "accounts receivable": "AccountsReceivableNetCurrent",
    "inventories": "InventoryNet",
    "total current assets": "AssetsCurrent",
    "property, plant and equipment": "PropertyPlantAndEquipmentNet",
    "property, plant, and equipment": "PropertyPlantAndEquipmentNet",
    "goodwill": "Goodwill",
    "long-term financial assets": "OtherLongTermInvestments",
    "total assets": "Assets",
    "short-term borrowings": "ShortTermBorrowings",
    "total current liabilities": "LiabilitiesCurrent",
    "long-term borrowings": "LongTermDebtNoncurrent",
    "total non-current liabilities": "LiabilitiesNoncurrent",
    "shareholders' equity": "StockholdersEquity",
    "non-controlling interests": "MinorityInterest",
    "total equity": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "total liabilities and equity": "LiabilitiesAndStockholdersEquity",
}

_INCOME_ROWS = {
    "net sales": "Revenues",
    "gross profit": "GrossProfit",
    "operating profit": "OperatingIncomeLoss",
    "income before taxes": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "income taxes": "IncomeTaxExpenseBenefit",
    "net income": "ProfitLoss",
    "net (loss)/income": "ProfitLoss",
    "net income/(loss)": "ProfitLoss",
    "net income attributable to shareholders": "NetIncomeLoss",
    "net (loss)/income attributable to shareholders": "NetIncomeLoss",
    "net income/(loss) attributable to shareholders": "NetIncomeLoss",
    "net income attributable to non-controlling interests":
        "NetIncomeLossAttributableToNoncontrollingInterest",
    "basic earnings per share from continuing and discontinued operations (in €)":
        "EarningsPerShareBasic",
    "diluted earnings per share from continuing and discontinued operations (in €)":
        "EarningsPerShareDiluted",
}


def _cash_flow_tag(label: str) -> str | None:
    if label in {
        "net cash generated from operating activities",
        "net cash used in operating activities",
        "net cash (used in)/generated from operating activities",
        "net cash generated from/(used in) operating activities",
        "cash flows from operating activities",
    }:
        return "NetCashProvidedByUsedInOperatingActivities"
    if label in {
        "depreciation, amortization and impairment losses",
        "depreciation, amortization, and impairment losses",
    }:
        return "DepreciationDepletionAndAmortization"
    if label in {
        "purchase of trademarks and other intangible assets",
        "purchase of other intangible assets",
    }:
        return "PaymentsToAcquireIntangibleAssets"
    if label in {
        "purchase of property, plant and equipment",
        "purchase of property, plant, and equipment",
    }:
        return "PaymentsToAcquirePropertyPlantAndEquipment"
    if label == "income taxes paid":
        return "IncomeTaxesPaidNet"
    if label == "interest expense":
        return "InterestExpense"
    if label == "dividend paid to shareholders of adidas ag":
        return "PaymentsOfDividendsCommonStock"
    return None


def _is_wc_component(label: str) -> bool:
    return any(fragment in label for fragment in (
        "receivables and other assets", "inventories",
        "accounts payable and other liabilities",
    )) and not label.startswith("cash flows from operating activities before")


def _entry(
    *, value: Decimal, year: int, report_year: int, filed: date,
    accession: str, label: str, document: str, per_share: bool,
    nil_marker: bool = False, source_concept: str | None = None,
) -> dict:
    end = date(year, 12, 31)
    result = {
        "val": int(value) if value == value.to_integral_value() else float(value),
        "accn": accession,
        "fy": report_year,
        "fp": "FY",
        "form": FORM,
        "filed": filed.isoformat(),
        "frame": f"CY{year}",
        "start": date(year, 1, 1).isoformat(),
        "end": end.isoformat(),
        "_source_namespace": "adidas-workbook",
        "_source_tag": label,
        "_source_unit": "EUR/shares" if per_share else "EUR",
        "_source_document": document,
        "_canonical_adapter": ADAPTER_KIND,
    }
    if nil_marker:
        result["_source_nil_marker"] = True
    if source_concept:
        result["_source_concept"] = source_concept
    return result


def _instant_entry(**kwargs) -> dict:
    result = _entry(**kwargs)
    result.pop("start", None)
    result["frame"] += "Q4I"
    return result


def _append(facts: dict, tag: str, unit: str, entry: dict) -> None:
    entry["_normalized_tag"] = tag
    tagdata = facts.setdefault(tag, {
        "label": tag,
        "description": "Canonical concept mapped from an adidas IFRS workbook row",
        "units": defaultdict(list),
    })
    tagdata["units"][unit].append(entry)


def _mapped_rows(
    rows: list[list[object]], kind: str, *, report_year: int, filed: date,
    accession: str, document: str, facts: dict,
) -> None:
    year_columns = _year_columns(rows)
    values_by_label: dict[str, dict[int, tuple[Decimal, bool, str]]] = defaultdict(dict)
    for row in rows:
        if not row:
            continue
        source_label = str(row[0] or "").strip()
        label = _normalise_label(source_label)
        if not label:
            continue
        for year, column in year_columns.items():
            raw = row[column] if column < len(row) else None
            value, nil_marker = _number(raw)
            if value is not None:
                values_by_label[label][year] = (value, nil_marker, source_label)

    direct: dict[str, str] = {}
    if kind == "balance":
        direct = _BALANCE_ROWS
    elif kind == "income":
        direct = _INCOME_ROWS

    for label, tag in direct.items():
        for year, (value, nil_marker, source_label) in values_by_label.get(label, {}).items():
            per_share = tag in {"EarningsPerShareBasic", "EarningsPerShareDiluted"}
            unit = "EUR/shares" if per_share else "EUR"
            maker = _instant_entry if kind == "balance" else _entry
            _append(facts, tag, unit, maker(
                value=value * (Decimal(1) if per_share else Decimal(1_000_000)),
                year=year, report_year=report_year, filed=filed,
                accession=accession, label=source_label, document=document,
                per_share=per_share, nil_marker=nil_marker,
            ))

    if kind == "cash_flow":
        for label, by_year in values_by_label.items():
            tag = _cash_flow_tag(label)
            if tag is None:
                continue
            for year, (value, nil_marker, source_label) in by_year.items():
                source_concept = None
                if tag == "DepreciationDepletionAndAmortization":
                    source_concept = (
                        "Depreciation, amortization and impairment losses "
                        "(combined workbook row)"
                    )
                if tag in {
                    "PaymentsToAcquireIntangibleAssets",
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    "PaymentsOfDividendsCommonStock",
                    "IncomeTaxesPaidNet",
                    "InterestExpense",
                }:
                    # Company Facts payment concepts carry a positive magnitude;
                    # adidas' cash-flow statement prints cash uses with a minus.
                    # Preserve the exact row in provenance and normalize only the
                    # sign convention required by the canonical concept.
                    value = abs(value)
                    source_concept = (
                        f"{source_label} (cash-payment magnitude; workbook sign normalized)"
                    )
                _append(facts, tag, "EUR", _entry(
                    value=value * Decimal(1_000_000), year=year,
                    report_year=report_year, filed=filed, accession=accession,
                    label=source_label, document=document, per_share=False,
                    nil_marker=nil_marker, source_concept=source_concept,
                ))

    def add_sum(tag: str, labels: Iterable[str], *, instant: bool, concept: str) -> None:
        selected = [(label, values_by_label.get(label, {})) for label in labels]
        years = set.intersection(*(set(by_year) for _, by_year in selected)) if selected else set()
        for year in years:
            components = [by_year[year] for _, by_year in selected]
            value = sum((component[0] for component in components), Decimal(0))
            source_labels = [component[2] for component in components]
            maker = _instant_entry if instant else _entry
            _append(facts, tag, "EUR", maker(
                value=value * Decimal(1_000_000), year=year,
                report_year=report_year, filed=filed, accession=accession,
                label=" + ".join(source_labels), document=document,
                per_share=False, nil_marker=all(component[1] for component in components),
                source_concept=concept,
            ))

    if kind == "balance":
        # Prior reports split trademarks from other intangibles; AR2022 onward
        # publishes one combined "Other intangible assets" line.
        trademarks = values_by_label.get("trademarks", {})
        other = values_by_label.get("other intangible assets", {})
        for year in sorted(set(trademarks) | set(other)):
            components = [series[year] for series in (trademarks, other) if year in series]
            value = sum((component[0] for component in components), Decimal(0))
            source_labels = [component[2] for component in components]
            _append(facts, "IntangibleAssetsNetExcludingGoodwill", "EUR", _instant_entry(
                value=value * Decimal(1_000_000), year=year,
                report_year=report_year, filed=filed, accession=accession,
                label=" + ".join(source_labels), document=document,
                per_share=False, nil_marker=all(component[1] for component in components),
                source_concept="Other intangible assets (including trademarks when separately shown)",
            ))
        add_sum(
            "OperatingLeaseLiability",
            ("current lease liabilities", "non-current lease liabilities"),
            instant=True, concept="Current and non-current lease liabilities",
        )
    elif kind == "cash_flow":
        wc_labels = [label for label in values_by_label if _is_wc_component(label)]
        # Adidas reports exactly one line for each of receivables/other assets,
        # inventory, and payables/other liabilities. Refuse incomplete subsets.
        if len(wc_labels) == 3:
            add_sum(
                "IncreaseDecreaseInOperatingAssetsAndLiabilities", wc_labels,
                instant=False,
                concept="Reported working-capital cash effect (three workbook rows)",
            )


def build_adidas_companyfacts(
    directory: str | Path, *, entity_id: str = DEFAULT_ENTITY_ID,
    ticker: str = DEFAULT_TICKER,
) -> dict:
    """Build a Company-Facts-shaped canonical bundle from adidas workbooks."""
    root = Path(directory).expanduser().resolve()
    paths = sorted(
        path for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in {".xls", ".xlsx"}
        and re.search(r"adidas.*ar\d{2}", path.name, re.IGNORECASE)
    )
    if not paths:
        raise FileNotFoundError(f"no adidas annual-report workbooks found in {root}")

    facts: dict = {}
    reports = []
    for path in paths:
        report_year = _report_year(path)
        sheets, modified = _read_workbook(path)
        filed = _evidence_date(report_year, modified)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        accession = f"adidas-ar{str(report_year)[-2:]}-{digest[:12]}"
        mapped = 0
        for sheet_name, rows in sheets:
            kind = _statement_kind(sheet_name)
            if kind is None:
                continue
            before = sum(len(entries) for tagdata in facts.values()
                         for entries in tagdata["units"].values())
            _mapped_rows(
                rows, kind, report_year=report_year, filed=filed,
                accession=accession, document=path.name, facts=facts,
            )
            after = sum(len(entries) for tagdata in facts.values()
                        for entries in tagdata["units"].values())
            mapped += after - before
        reports.append({
            "fiscal_year": report_year,
            "published": filed.isoformat(),
            "document": path.name,
            "sha256": digest,
            "mapped_facts": mapped,
        })

    # defaultdict is convenient while collecting but should not leak into the
    # persistent cache contract.
    for tagdata in facts.values():
        tagdata["units"] = dict(tagdata["units"])
    return {
        "cik": entity_id,
        "entityName": "adidas AG",
        "facts": {"canonical": facts},
        "_adapter": {
            "kind": ADAPTER_KIND,
            "statement_basis": "canonical",
            "reporting_currency": "EUR",
            "quote_currency": "EUR",
            "ticker": ticker,
            "source_directory": str(root),
            "reports": reports,
            "comparative_policy": "latest-published-report-wins",
        },
    }


def write_adidas_companyfacts(
    directory: str | Path, destination: str | Path, *,
    entity_id: str = DEFAULT_ENTITY_ID, ticker: str = DEFAULT_TICKER,
) -> dict:
    bundle = build_adidas_companyfacts(directory, entity_id=entity_id, ticker=ticker)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    return bundle
