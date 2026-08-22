"""Layer 1: the cover page of a filing, which Company Facts cannot express.

Two facts on every cover decide what a price means, and neither survives the
Company Facts API — one because it is dimension-qualified, both because they are
text:

    dei:Security12bTitle   "American Depositary Shares, each representing 10
                            Ordinary Shares, par value $0.000006 per share"
    dei:TradingSymbol      "ZLAB"

They sit under a share-class axis, so the symbol is attached to *one* class. That
is the only deterministic answer to the question every per-share figure depends
on: which security does this ticker price? For a depositary receipt it also
carries the ratio between the receipt and the ordinary shares the statements
count — the number that makes a market capitalisation right or ten times too
large.

The rendered cover (SEC's R1 report) is read rather than the raw instance: it is
one small request per filing, carries the same tagged values, and needs no XBRL
toolchain.
"""
from __future__ import annotations

import html
import re
from decimal import Decimal

R_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/R{n}.htm"
# a cover is one of the first few rendered reports; beyond that come statements
COVER_REPORTS = (1, 2, 3)

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fifteen": 15, "twenty": 20, "twenty-five": 25, "forty": 40, "fifty": 50,
    "one hundred": 100, "two hundred": 200, "five hundred": 500,
    "one thousand": 1000, "two thousand": 2000,
}
_RATIO = re.compile(
    r"each\s+(?:\w+\s+){0,2}?repr\w*\s+(?:the\s+right\s+to\s+\w+\s+)?"
    r"(?:(?P<num>[\d,.]+)|(?P<word>[a-z\-]+(?:\s+[a-z\-]+)?))\s+"
    r"(?:ordinary|common|class\s+\w+)\s+shar",
    re.I,
)


def text_of(document: str) -> str:
    """The rendered report as one line of readable text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", document)))


def securities(document: str) -> list[dict]:
    """Every registered class the cover names, with the symbol attached to it.

    The rendered cover repeats one block per class, so title and symbol pair by
    position: the symbol that follows a title belongs to that title.
    """
    flat = text_of(document)
    out: list[dict] = []
    # Filers label the same two elements either way: "Title of 12(b) Security"
    # with "Trading Symbol", or "Title of each class" with "Trading Symbol(s)".
    # Onconova uses the second pair, and its title carries the 13:1 ratio that
    # nothing in Company Facts can express.
    for match in re.finditer(
        r"(?:Title of (?:12\(b\) Security|each class)|Security12bTitle)\s*(.+?)\s*"
        r"Trading Symbol\(?s?\)?\s*([A-Z0-9.\-]{1,12})", flat
    ):
        title = match.group(1).strip(" |")
        if title and len(title) < 400:
            out.append({"title": title, "symbol": match.group(2)})
    if out:
        return out
    # A filer can tag the symbol and no class title at all — American Vanguard and
    # Manitowoc both do. There is nothing further to learn from their cover, and
    # saying so is worth more than leaving the question open forever.
    bare = re.search(r"Trading Symbol\(?s?\)?\s*([A-Z0-9.\-]{1,12})", flat)
    if bare and "Cover" in flat or (bare and "Document Type" in flat):
        return [{"title": "", "symbol": bare.group(1)}]
    return out


def depositary_ratio(title: str) -> Decimal | None:
    """How many underlying shares one receipt stands for, from the title's own
    sentence. None where the title describes no receipt — an ordinary share class
    says nothing about a ratio, which is the right answer for most filers."""
    match = _RATIO.search(title)
    if not match:
        return None
    if match.group("num"):
        try:
            return Decimal(match.group("num").replace(",", ""))
        except Exception:
            return None
    word = " ".join((match.group("word") or "").split()).lower()
    value = _WORDS.get(word) or _WORDS.get(word.split()[-1] if word else "")
    return Decimal(value) if value else None
