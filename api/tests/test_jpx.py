import io

import openpyxl

from screener.sources.jpx import listed_companies


def test_jpx_listing_matches_domestic_shares_without_funds_or_foreign_rows():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Effective Date", "Local Code", "Name (English)",
                  "Section/Products", "33 Sector(Code)", "33 Sector(name)"])
    sheet.append(["20260831", "6752", "Panasonic", "Prime Market (Domestic)",
                  "3650", "Electric Appliances"])
    sheet.append(["20260831", "7974", "Nintendo", "Standard Market(Domestic)",
                  "3800", "Other Products"])
    sheet.append(["20260831", "1306", "Index Fund", "ETFs/ ETNs", None, None])
    sheet.append(["20260831", "9999", "Foreign Company", "Prime Market(Foreign)",
                  None, None])
    stream = io.BytesIO()
    book.save(stream)
    companies = listed_companies(stream.getvalue())
    assert set(companies) == {"6752", "7974"}
    assert companies["6752"]["name"] == "Panasonic"
