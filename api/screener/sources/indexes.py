"""Layer 1: index constituent lists."""
from __future__ import annotations

import re

import httpx

# ponytail: constituents scraped from Wikipedia (the list itself is S&P's proprietary
# pick, so there is no official free source); swap for a licensed feed if this breaks
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def sp500_ciks(timeout: float = 20.0) -> frozenset[str] | None:
    """Zero-padded CIKs of current S&P 500 members, or None when unavailable."""
    try:
        resp = httpx.get(
            WIKI_SP500_URL, timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return parse_sp500_ciks(resp.text)


def parse_sp500_ciks(html: str) -> frozenset[str] | None:
    """The constituents table is the only place 10-digit zero-padded CIKs appear."""
    table = re.search(r'id="constituents".*?</table>', html, re.S)
    if not table:
        return None
    ciks = frozenset(re.findall(r">(\d{10})<", table.group(0)))
    # far fewer than 500 means the page layout changed, not that the index shrank
    return ciks if len(ciks) > 480 else None
