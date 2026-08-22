"""Layer 1: the financial statements as a reader sees them, not as XBRL reports them.

Every other check in this project compares one machine reading against another.
This one goes to the document: the balance sheet and income statement the company
actually published, rendered by SEC's own viewer, read as labelled rows of money.
It is the only evidence that does not share an ancestor with the number it checks —
if the tagged `Assets` fact and the "Total assets" line of the printed balance
sheet agree, the figure is right in the sense a person would mean.

`FilingSummary.xml` lists every rendered report in a filing with its short name,
so the balance sheet is found by name rather than by guessing at R-numbers, which
differ between filers and between years.

Two things the rendering carries and the XBRL does not:

  * the scale. The table header says "$ in Millions" and every cell is then a
    number of millions. Reading 45,468 as dollars instead of millions is the
    difference between a company and a corner shop.
  * the sign convention. A parenthesised cell is negative, and a label ending in
    a minus-bearing concept may be presented positive.
"""
from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal, InvalidOperation

SUMMARY_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/FilingSummary.xml"
REPORT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{file}"

# What each statement is called. Filers name them differently — "CONSOLIDATED
# BALANCE SHEETS", "Consolidated Statements of Financial Position", "Consolidated
# Balance Sheet (unaudited)" — so a statement is recognised by the words that
# survive all of those, and parenthetical suffixes are ignored.
STATEMENTS = {
    "balance_sheet": ("balance sheet", "financial position", "financial condition"),
    # Small filers combine the income statement with comprehensive income and title
    # it accordingly; Creatd's is "Consolidated Statements of Comprehensive Loss".
    # Ranked last, so a filer publishing both keeps the pure one.
    "income": ("statements of operations", "statement of operations",
               "statements of income", "statement of income", "statements of earnings",
               "statement of earnings", "results of operations",
               "comprehensive loss", "comprehensive income"),
}
# A "(Parenthetical)" report carries the share counts and par values that sit in
# the margin of the statement, not the statement itself.
PARENTHETICAL = "parenthetical"

_UNITS = {"thousands": Decimal("1e3"), "millions": Decimal("1e6"), "billions": Decimal("1e9")}
# The money scale is the one attached to the dollar sign. CoStar's header reads
# "$ in Thousands, shares in Millions", and a pattern that merely looks for the
# word "millions" finds the share clause and reads every figure a thousand times
# too large.
_MONEY_SCALE = re.compile(r"\$\s*in\s+(thousands|millions|billions)", re.I)
_BARE_SCALE = re.compile(r"(?<!shares )(?<!share )\bin\s+(thousands|millions|billions)", re.I)
_SHARES_UNSCALED = re.compile(r"shares?\s+in\s+(thousands|millions|billions)", re.I)
# A row counting shares, not one naming the people who hold them. "Net Income to
# Shareholders" contains the word "share" and is money; scaling it as a share count
# left Markel's $2.1bn of profit reading as $2,107,010.
_A_COUNT_OF_SHARES = re.compile(r"\bshares?\b(?!\s*holder)", re.I)
# A per-share figure is already in dollars and takes no scale at all. Coca-Cola's
# statement is headed "$ in Millions" and prints diluted earnings of 3.04; scaling
# that as money makes it $3,040,000 a share.
# "(in dollars per share)", "(in shares)" — the renderer's note of the unit, not
# part of what the line is called. JPM heads its earnings "Diluted earnings per
# share (in dollars per share)" and Apple heads the same line just "Diluted".
_UNIT_SUFFIX = re.compile(r"\s*\((?:in\s+)?(?:dollars|usd|shares|dollars per share)"
                          r"(?:\s+per\s+share)?\)\s*$", re.I)
_IN_SHARES = re.compile(r"\(\s*in\s+shares\s*\)", re.I)
_PER_SHARE = re.compile(r"\bper\s+(?:basic\s+|diluted\s+|common\s+)?(?:share|unit)", re.I)
# The sign comes from the parentheses and from nothing else. A label is not
# evidence: Intellicheck heads its line "Net loss" and prints "$ 1,273" beside a
# prior year of "$ (918)" — a stale caption over a real profit, which the page's own
# arithmetic confirms (pre-tax 1,331 less tax 58). Reading the caption as a sign
# inverted a profitable year into a loss.
# A money cell, in any of the orders the renderer uses: "1,296", "$ 1,296",
# "(52)", "$ (52)". The dollar sign may sit outside the bracket or inside it, and
# a pattern that fixes the order silently skips every loss — Hyatt's "$ (52)" was
# passed over and the next column's $1,296 profit read in its place.
_CELL = re.compile(r"^\$?\s*\(?\s*\$?\s*(-?[\d,]+(?:\.\d+)?)\s*\)?$")
# An "attributable to" line belonging to somebody other than the parent: the
# minority holders, or a per-share figure. "Attributable to common stockholders" is
# NOT excluded — for Cohen & Steers and for Vivid Seats' Class A that phrasing IS
# the parent's own line, and skipping it took the consolidated figure instead.
_NOT_THE_PARENT = re.compile(
    r"noncontrolling|non-controlling|minority|per share|per unit|preferred|redeemable"
    # an intermediate holding company is not the registrant: Ares prints "attributable
    # to Ares Operating Group entities" above its own line, $307M larger
    r"|operating group|operating partnership|operating compan"
    # and "attributable to common stockholders" is claimed by two different figures,
    # so it is matched by its own phrase further down the list, never by the prefix
    r"|common stockholders|common shareholders", re.I)


def reports(summary_xml: str) -> list[dict]:
    """Every rendered report in the filing: {file, name, category}.

    `MenuCategory` is SEC's own division of a filing into "Statements", "Notes",
    "Details" and the rest. It is the difference between the income statement and a
    note that happens to mention operations, and matching on the name alone reached
    for R71 of Creatd's 10-K — a note eighty reports past the statement itself.
    """
    out = []
    for block in re.findall(r"<Report[^>]*>(.*?)</Report>", summary_xml, re.S | re.I):
        def field(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S | re.I)
            return html.unescape(m.group(1)).strip() if m else ""
        file, name = field("HtmlFileName") or field("XmlFileName"), field("ShortName")
        if file and name:
            out.append({"file": file, "name": name, "category": field("MenuCategory")})
    return out


def find(summary_xml: str, kind: str) -> str | None:
    """The rendered file holding one statement, chosen by its printed name.

    The main statement wins over its parenthetical companion, and the first match
    wins over later ones — a filing that restates a segment later in the document
    still opens with the consolidated statement.
    """
    wanted = STATEMENTS[kind]
    found = reports(summary_xml)
    primary = [r for r in found if r.get("category") == "Statements"] or found
    # phrase order carries the preference, so the whole set is searched for the
    # first phrase before the second is tried
    for phrase in wanted:
        for report in primary:
            name = report["name"].lower()
            if PARENTHETICAL in name:
                continue
            if phrase in name:
                return report["file"]
    return None


def _readable_head(document: str) -> str:
    """The first of the document a reader sees, with the machinery removed.

    The rendered reports carry a block of script and comments before the table, and
    it mentions units of its own. CoStar's income statement is headed "$ in
    Thousands" while the preamble contains the word "Millions", so scanning raw
    characters read every figure a thousand times too large.
    """
    body = re.sub(r"<script[^>]*>.*?</script>", " ", document, flags=re.S | re.I)
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))[:600]


def scale(document: str) -> Decimal:
    """The multiplier the table header declares, or 1."""
    head = _readable_head(document)
    for pattern in (_MONEY_SCALE, _BARE_SCALE):
        found = pattern.search(head)
        if found:
            return _UNITS[found.group(1).lower()]
    return Decimal(1)


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I)]


_HEADER_DATE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def columns(document: str) -> list[date]:
    """The period end each numeric column belongs to, left to right.

    Not every filer prints the newest year first. Hyatt's income statement opens
    with fiscal 2024, so reading the leftmost column reported $1,296M of profit for
    a year the company actually lost $52M. The column has to be chosen by its own
    heading, not by position.
    """
    head = re.search(r"<thead[^>]*>(.*?)</thead>", document, re.S | re.I)
    # these renderings carry no <thead>; the period headings sit in the first rows
    scope = head.group(1) if head else _readable_head(document)
    out = []
    for match in _HEADER_DATE.finditer(re.sub(r"<[^>]+>", " ", scope)):
        month, day, year = match.groups()
        try:
            out.append(date(int(year), _MONTHS[month[:3].lower()], int(day)))
        except ValueError:
            continue
    return out


def lines(document: str) -> list[tuple[str, list[Decimal]]]:
    """(label, [value per column]) for every row of the statement that states numbers.

    Every numeric cell is kept, because which one is wanted depends on the period
    being checked and the order the filer chose to print.
    """
    factor = scale(document)
    # "Shares in Thousands, $ in Millions" scales the two differently; where the
    # header says so, a row whose label is about shares takes the share scale.
    share_word = _SHARES_UNSCALED.search(_readable_head(document))
    share_factor = _UNITS.get(share_word.group(1).lower() if share_word else "", Decimal(1))

    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", document, re.S | re.I):
        cells = [c for c in _cells(row) if c]
        if len(cells) < 2:
            continue
        label = cells[0].rstrip(" :")
        if not label or _CELL.match(label):
            continue
        per_share = bool(_PER_SHARE.search(label))
        about_shares = bool(_A_COUNT_OF_SHARES.search(label)) and not per_share
        values = []
        for cell in cells[1:]:
            m = _CELL.match(cell)
            if not m:
                continue
            try:
                value = Decimal(m.group(1).replace(",", ""))
            except InvalidOperation:
                continue
            if "(" in cell:
                value = -value
            unit = (Decimal(1) if per_share else
                    share_factor if (about_shares and "$" not in cell) else factor)
            values.append(value * unit)
        if values:
            out.append((label, values))
    # Rows that state fewer figures than the table has columns cannot be indexed by
    # column: Sarepta's balance sheet heads three dates and prints two values per
    # line, so the first value belongs to a column the reader cannot identify. Such
    # rows are dropped rather than misread.
    widest = max((len(v) for _, v in out), default=0)
    return [(label, values) for label, values in out
            if len(values) == widest or widest == 0]


def _label_key(label: str) -> str:
    """A printed label reduced to what it calls the line.

    Footnote markers and the renderer's note of the unit fall away: JPMorgan heads
    its earnings "Diluted earnings per share (in dollars per share)" and Apple heads
    the same line just "Diluted". Written once, because the two matchers below had
    a copy each and one of them drifted.
    """
    clean = re.sub(r"\s+", " ", label.lower()).strip(" .:")
    clean = re.sub(r"\s*\[\d+\]$", "", clean)
    return _UNIT_SUFFIX.sub("", clean).strip()


def value_for(statement_lines, *phrases: str, column: int = 0) -> tuple[str, Decimal] | None:
    """The first line whose label matches one of these phrases, longest first.

    Labels are matched whole-word-ish rather than by substring: "Total assets"
    must not match "Total assets of discontinued operations", and "Total
    liabilities" must not match "Total liabilities and equity", which is a
    different and much larger number.
    """
    for phrase in phrases:
        target = phrase.lower().rstrip("*")
        prefix = phrase.endswith("*")
        for label, values in statement_lines:
            clean = _label_key(label)
            if clean == target or (prefix and clean.startswith(target)
                                   and not _NOT_THE_PARENT.search(clean)):
                if column < len(values):
                    return label, values[column]
    return None


def all_matching(statement_lines, *phrases: str, column: int = 0,
                 only_the_parent: bool = True,
                 money_only: bool = False) -> list[tuple[str, Decimal]]:
    """Every line whose label matches one of these phrases, in printed order.

    Where one phrase means two different figures depending on the filer, a single
    best match cannot be chosen by label. Edison calls the parent's share "Net
    income available to Edison International common shareholders" and prints the
    consolidated total as "Net income"; Uniti prints the parent's share AS "Net
    income" and uses "attributable to common shareholders" for the figure after
    preferred dividends. The same words, opposite meanings.

    So the caller asks a weaker but answerable question: is the figure on the panel
    one of the numbers this statement prints for this concept? A value that appears
    nowhere on the page is still caught; a value that appears is corroborated
    without the checker having to out-guess the filer's wording.
    """
    out = []
    for phrase in phrases:
        suffix, prefix = phrase.startswith("*"), phrase.endswith("*")
        target = phrase.lower().strip("*")
        for label, values in statement_lines:
            clean = _label_key(label)
            if only_the_parent and _NOT_THE_PARENT.search(clean) and "common" not in clean:
                continue                        # the minority holders' own line
            # "Diluted (in shares)" and "Diluted (in dollars per share)" are the same
            # word once the unit suffix falls away, and one of them is a count of
            # shares. Where a per-share figure is wanted, the count is not it.
            if money_only and _IN_SHARES.search(label):
                continue
            hit = (clean.endswith(target) if suffix else
                   clean.startswith(target) if prefix else clean == target)
            if hit and column < len(values):
                out.append((label, values[column]))
    return out
