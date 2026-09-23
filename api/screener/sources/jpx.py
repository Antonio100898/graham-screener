"""Current Tokyo Stock Exchange listed ordinary-share identities."""
from __future__ import annotations

import io
import re

import httpx
import openpyxl


LIST_URL = (
    "https://www.jpx.co.jp/english/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_e.xlsx"
)


def listed_companies(workbook: bytes) -> dict[str, dict]:
    """Map four-character TSE local codes to verified current equity listings."""
    book = openpyxl.load_workbook(io.BytesIO(workbook), read_only=True, data_only=True)
    try:
        rows = book.active.iter_rows(values_only=True)
        header = next(rows, ())
        if tuple(header[:4]) != (
        "Effective Date", "Local Code", "Name (English)", "Section/Products"
        ):
            raise ValueError("unexpected JPX listing columns")
        out = {}
        for row in rows:
            _, code, name, section, _, industry, *_ = row
            code = str(code or "")
            section = str(section or "")
            if (not re.fullmatch(r"[0-9A-Z]{4}", code)
                    or not re.search(r"Market\s*\(Domestic\)", section)):
                continue
            out[code] = {
                "name": name,
                "market": section,
                "industry": industry,
                "asof": row[0],
            }
        return out
    finally:
        book.close()


def fetch_listed_companies(http: httpx.Client | None = None) -> dict[str, dict]:
    if http is None:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(LIST_URL)
    else:
        response = http.get(LIST_URL)
    response.raise_for_status()
    return listed_companies(response.content)
