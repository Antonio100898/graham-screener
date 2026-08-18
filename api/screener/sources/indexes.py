"""Layer 1: index membership lists.

The lists themselves are the index owners' proprietary picks with no official
free feed, so they are read from Wikipedia — the parse API, because the plain
article HTML no longer carries the constituent tables expanded. Every parser
returns None when the page or its table shape is gone, never a partial list:
an index column that silently lost half its members would look like
reconstitution, and absence is visible.
"""
from __future__ import annotations

import re

import httpx

WIKI_API = ("https://en.wikipedia.org/w/api.php"
            "?action=parse&prop=text&format=json&formatversion=2&page={page}")


def _page(page: str, timeout: float = 20.0) -> str | None:
    try:
        resp = httpx.get(WIKI_API.format(page=page), timeout=timeout, follow_redirects=True,
                         headers={"User-Agent": "graham-screener (contact via repo)"})
        resp.raise_for_status()
        return resp.json()["parse"]["text"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def sp500(html: str | None = None) -> dict[str, str] | None:
    """Current S&P 500 members as {zero-padded CIK: wiki article path} — the
    article path is the join key that lets the DJIA name-list map onto tickers."""
    html = html if html is not None else _page("List_of_S%26P_500_companies")
    if html is None:
        return None
    table = re.search(r'id="constituents".*?</table>', html, re.S)
    if not table:
        return None
    out: dict[str, str] = {}
    for row in table.group(0).split("<tr")[2:]:
        cik = re.search(r">(\d{10})\s*<", row)
        href = re.search(r'href="/wiki/([^"#]+)"', row)
        if cik and href:
            out[cik.group(1)] = href.group(1)
    # far fewer than 500 means the page layout changed, not that the index shrank
    return out if len(out) > 480 else None


def djia_ciks(sp: dict[str, str], html: str | None = None) -> frozenset[str] | None:
    """Current DJIA members' CIKs. Wikipedia lists the Dow by company NAME only,
    but each name links to the same article the S&P 500 table links to, and every
    Dow member is an S&P 500 member — so the article path joins name to CIK.
    Only cells that contain nothing but the company link count; footnote links
    (Kenvue under a spin-off note) must not enter the index."""
    html = html if html is not None else _page(
        "Historical_components_of_the_Dow_Jones_Industrial_Average")
    if html is None:
        return None
    tables = re.findall(r"<table[^>]*wikitable[^>]*>.*?</table>", html, re.S)
    if not tables:
        return None
    # a cell may carry a change-marker arrow after the name, but any richer
    # content (a footnote's spin-off mention) disqualifies it as a member cell
    members = re.findall(
        r'<td[^>]*>\s*<a [^>]*href="/wiki/([^"#]+)"[^>]*>[^<]+</a>[\s↑↓*]*</td>', tables[0])
    hrefs = frozenset(members)
    if len(hrefs) != 30:
        return None
    by_href = {}
    for cik, href in sp.items():
        by_href.setdefault(href, set()).add(cik)
    out = frozenset(c for h in hrefs for c in by_href.get(h, ()))
    return out if len(out) == 30 else None


def nasdaq100(html: str | None = None) -> frozenset[str] | None:
    """Current Nasdaq-100 members as tickers (the list page carries no CIK)."""
    html = html if html is not None else _page("List_of_NASDAQ-100_companies")
    if html is None:
        return None
    table = re.search(r'id="constituents".*?</table>', html, re.S)
    if not table:
        return None
    ticks = frozenset(
        m.group(1)
        for row in table.group(0).split("<tr")[2:]
        if (m := re.search(r"<td[^>]*>([A-Z][A-Z.]{0,5})\s*</td>", row))
    )
    # the index holds 100 companies but some list two share classes
    return ticks if 95 <= len(ticks) <= 110 else None
