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
_NUMBER_WORD = "|".join(sorted((re.escape(word) for word in _WORDS), key=len, reverse=True))
_RATIO = re.compile(
    r"(?:each\s+(?:\w+\s+){0,2}?|(?:one|an?)\s+(?:american\s+)?depositary\s+share\s+)"
    r"repr\w*\s+(?:the\s+right\s+to\s+\w+\s+)?"
    rf"(?:(?P<num>[\d,.]+)|(?P<word>{_NUMBER_WORD}))\s+"
    r"(?:(?:ordinary|common)\s+shares?|(?:class|series)\s+\w+\s+"
    r"(?:(?:ordinary|common)\s+)?shares?"
    r"|shares?(?:\s+of\s+(?:common|ordinary)\s+stock)?)",
    re.I,
)
_DEPOSITARY_SECURITY = re.compile(
    r"\b(?:american\s+)?deposit(?:ary|ory)\b|\b(?:ADS|ADR)s?\b", re.I,
)
_NONCOMMON_SECURITY = re.compile(
    r"\b(?:preferred|preference|warrant|right|note|bond|debenture|debt|ETNs?)\b", re.I,
)
_COMMON_EQUITY = re.compile(
    r"\b(?:common|ordinary|voting)\b|\b(?:limited\s+partner|partnership\s+interest)\b|"
    r"\btrust\s+units?\b|\bunits?\s+representing\b|"
    r"^(?:(?:class\s+)?[A-Z]\s+)?shares?\b", re.I,
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
    # Exchange-rendered preferred symbols may contain spaces ("GLP pr B"). A
    # token-only capture truncated that to GLP, so the preferred row overwrote the
    # real GLP common-unit row in storage. The exchange-name cell is the reliable
    # right boundary; retain a narrow fallback below for older covers without it.
    block = re.compile(
        r"(?:Title of (?:12\(b\) Security|each class)|Security12bTitle)\s*(.+?)\s*"
        r"Trading Symbol\(?s?\)?\s*(.+?)\s*"
        r"(?:Security Exchange Name|Name of each exchange)", re.I,
    )
    matches = list(block.finditer(flat)) or list(re.finditer(
        r"(?:Title of (?:12\(b\) Security|each class)|Security12bTitle)\s*(.+?)\s*"
        r"Trading Symbol\(?s?\)?\s*([A-Z0-9.\-]{1,12})", flat
    ))
    for match in matches:
        title = match.group(1).strip(" |")
        symbol = " ".join(match.group(2).strip(" |").split())
        if title and len(title) < 400 and 0 < len(symbol) < 40:
            out.append({"title": title, "symbol": symbol})
    if out:
        return unique_securities(out)
    # A filer can tag the symbol and no class title at all — American Vanguard and
    # Manitowoc both do. There is nothing further to learn from their cover, and
    # saying so is worth more than leaving the question open forever.
    bare = re.search(r"Trading Symbol\(?s?\)?\s*([A-Z0-9.\-]{1,12})", flat)
    if bare and "Cover" in flat or (bare and "Document Type" in flat):
        return [{"title": "", "symbol": bare.group(1)}]
    return out


def unique_securities(rows: list[dict]) -> list[dict]:
    """One registered class per exact trading symbol.

    A 20-F can repeat the ADS ticker on the unlisted underlying ordinary-share
    row (LX), while older parsers could also truncate an exchange-rendered debt
    or preferred symbol to the common's plain ticker (HON/PPG/GLP). Storage is
    keyed by ``(cik, symbol)``, so letting the last row win silently changes what
    one priced share means. Prefer the depositary class, then common equity, and
    keep the first row when two descriptions have the same standing.
    """
    winners: dict[str, tuple[int, int, dict]] = {}
    for position, row in enumerate(rows):
        symbol = row.get("symbol") or ""
        title = row.get("title") or ""
        rank = 2 if is_depositary_security(title) else (1 if is_common_equity_security(title) else 0)
        current = winners.get(symbol)
        if current is None or rank > current[0]:
            winners[symbol] = (rank, position, row)
    return [winner[2] for winner in sorted(winners.values(), key=lambda item: item[1])]


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


def is_depositary_security(title: str) -> bool:
    """Whether a registered-class title says the ticker prices a receipt.

    A foreign ordinary/common share needs no conversion. A depositary title does:
    without its underlying-shares-per-receipt ratio, prices and statement figures
    cannot safely be put on one basis.
    """
    return bool(_DEPOSITARY_SECURITY.search(title or ""))


def is_common_equity_security(title: str) -> bool:
    """Whether the registered class is an equity security this screen can price.

    Exact symbol matching can still land on a preferred share, warrant or ETN.
    Those securities do not own the common earnings/book value being screened.
    """
    title = title or ""
    if _NONCOMMON_SECURITY.search(title):
        return False
    return is_depositary_security(title) or bool(_COMMON_EQUITY.search(title))


def is_untraded_underlying(title: str) -> bool:
    """Whether a starred 20-F row names the ordinary shares behind an ADS.

    Foreign covers commonly repeat the ADS symbol on an ordinary-share row and
    mark that row with ``*`` to say the ordinary shares are not themselves
    listed. Such a row cannot establish the priced security's identity.
    """
    title = title or ""
    return (title.rstrip().endswith("*") and not is_depositary_security(title)
            and is_common_equity_security(title))
