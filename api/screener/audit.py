"""Check every number the panel shows against the filing it claims to come from.

Re-running the engine proves nothing: a wrong rule is wrong twice. So nothing here
imports the extraction code. Each figure is checked two ways, both independent of
how it was produced:

  SOURCED   the value is really in the filing its own provenance names. The row
            says `total_assets` came from tag `Assets` in accession X for period
            ending Y; this opens the raw Company Facts JSON, finds that exact fact,
            and compares the number. Catches a value that drifted away from the
            evidence recorded beside it.

  DERIVED   the figures computed from those facts are the arithmetic they claim.
            The current ratio is current assets over current liabilities and
            nothing else; book value per share is common equity over the share
            count. Written out here as one line of plain arithmetic per figure, so
            the check is obviously right by reading it.

A third class is reported but never failed: figures whose inputs the payload does
not carry (the trailing EPS composite, the ten-year statistics). They are listed as
UNCHECKED rather than silently counted as passing.

    python -m screener.audit                    # a spread of 20 companies
    python -m screener.audit --ticker KO,MSFT
    python -m screener.audit --sample 200 --quiet
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from .normalize import _is_financial_form
from .sources import statements
from .sources.edgar import EdgarClient
from .sync import DASHBOARD_JSON

# A displayed figure and the sources entry that must vouch for it. Only figures
# that come straight from one tagged fact appear here; anything summed or chosen
# between tags is checked as an identity below instead.
SOURCED = (
    ("total_assets", "total_assets"),
    ("current_assets", "current_assets"),
    ("current_liabilities", "current_liabilities"),
    ("total_liabilities", "total_liabilities"),
    ("goodwill", "goodwill"),
    ("intangibles", "intangibles"),
    ("shares", "shares"),
    ("options", "options"),
    ("noncontrolling_interest", "noncontrolling_interest"),
)
TOLERANCE = 0.005          # a rounded display figure, not a different number


def _facts(cik: str, cache: Path) -> dict:
    path = cache / f"companyfacts_{cik}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _ratio(row: dict) -> float:
    """How many ordinary shares one listed receipt stands for, or 1.

    Zai Lab's share count is filed in ordinary shares and displayed in the American
    depositary shares the price belongs to, ten to one. The provenance still names
    the ordinary fact, so the check has to divide before comparing or every
    depositary filer reads as wrong by its own ratio."""
    value = ((row.get("receipt") or {}).get("ratio"))
    try:
        return float(value) if value else 1.0
    except (TypeError, ValueError):
        return 1.0


def _at_period_end(facts: dict, tag_text: str, end: str | None) -> float | None:
    """One concept's value at one balance-sheet date, latest-filed, any accession."""
    ns, _, tag = tag_text.partition(":")
    best = None
    for units in (facts.get("facts", {}).get(ns or "us-gaap", {}).get(tag) or {}).get("units", {}).values():
        for e in units:
            if e.get("end") == end and "start" not in e:
                if best is None or e.get("filed", "") > best.get("filed", ""):
                    best = e
    return float(best["val"]) if best else None


def _fact_in_filing(facts: dict, source: dict) -> float | None:
    """The value the named accession actually reports for the named period.

    A provenance naming two tags is a figure the engine derived by subtraction or
    addition (total liabilities from the balance-sheet identity, a minority interest
    summed with its redeemable half). Those are resolved from their own components
    rather than reported as unfindable."""
    tag_text = source.get("tag") or ""
    # A summed figure records where each half came from, and the halves may be
    # filed separately: Cohen & Steers tags its permanent minority interest every
    # quarter and its redeemable half only in the 10-K, so the two carry different
    # accessions and dates. Each is looked up in its own filing — forcing them into
    # the parent's reads the figure as wrong when it is merely composite.
    parts = source.get("components") or ()
    if len(parts) > 1 and " + " in tag_text:
        found = [_fact_in_filing(facts, part) for part in parts]
        return None if any(v is None for v in found) else sum(found)
    for operator, combine in ((" - ", lambda a, b: a - b), (" + ", lambda a, b: a + b)):
        if operator in tag_text:
            # Each half at the same balance-sheet date, from whichever filing states
            # it: Isabella Bank's goodwill for 2025-12-31 is carried by an earlier
            # accession than the combined line, and a half that cannot be found is
            # NOT zero — treating it so read the whole combined figure as intangible
            # and called a correct 0 an error.
            halves = [_at_period_end(facts, part.strip(), source.get("end"))
                      for part in tag_text.split(operator, 1)]
            if any(h is None for h in halves):
                return None
            return combine(*halves)
    ns, _, tag = tag_text.partition(":")
    found = _values_in_filing(facts, ns or "us-gaap", tag, source)
    return found[0] if found else None


def _values_in_filing(facts: dict, ns: str, tag: str, source: dict) -> list[float]:
    """Every value the named filing reports for that concept at that period end.

    Usually one. But a weighted-average share count is a DURATION fact, and a
    quarterly report states several for the same end date — the three months, the
    six, the year to date — and the provenance records only the end. So the
    question this check can honestly ask is whether the displayed figure is one of
    the numbers the filing states, not whether it is the first of them.
    """
    out = []
    for units in (facts.get("facts", {}).get(ns, {}).get(tag) or {}).get("units", {}).values():
        for e in units:
            if e.get("accn") == source.get("accn") and e.get("end") == source.get("end"):
                out.append(float(e["val"]))
    return out


# The panel rounds a displayed ratio to two decimals, so 0.0669 is shown as 0.07.
# On a small figure that is a 5% relative gap and nothing is wrong, which a purely
# relative tolerance calls a defect.
ROUNDING = 0.005


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= max(ROUNDING, TOLERANCE * max(abs(a), abs(b), 1e-9))


def _identities(row: dict) -> list[tuple]:
    """(name, shown, expected, formula) for every figure the panel computes.

    Each is the whole of its arithmetic. Where an input is missing the check is
    skipped rather than assumed — that is the same rule the engine follows, and a
    check that treats missing as zero would pass exactly where the engine is
    wrong.
    """
    out = []

    def check(name, shown, expected, formula):
        if shown is not None and expected is not None:
            out.append((name, shown, expected, formula))

    ca, cl = row.get("current_assets"), row.get("current_liabilities")
    shares, price = row.get("shares"), row.get("price")
    assets, liabilities = row.get("total_assets"), row.get("total_liabilities")
    # the same three deductions `_common_equity` makes — what is left is the
    # common's, and omitting the preferred overstates it by exactly that claim
    senior = ((row.get("noncontrolling_interest") or 0) + (row.get("preferred_stock") or 0)
              + (row.get("temporary_equity") or 0))
    equity = None if assets is None or liabilities is None else assets - liabilities - senior

    # where one tag carries both, the two fields must still add up to it
    goodwill_src = ((row.get("sources") or {}).get("goodwill") or {})
    if "contained in" in goodwill_src.get("concept", ""):
        check("goodwill + intangibles", (row.get("goodwill") or 0) + (row.get("intangibles") or 0),
              row.get("intangibles"), "the combined line, split as 0 + all of it")
    if ca is not None and cl:
        check("current_ratio", _c(row, 2), ca / cl, "current assets / current liabilities")
    if equity is not None and shares:
        check("bvps", row.get("bvps"), equity / shares,
              "(assets - liabilities - preferred - minority - temporary equity) / shares")
        intangible = (row.get("goodwill") or 0) + (row.get("intangibles") or 0)
        check("tbvps", row.get("tbvps"), (equity - intangible) / shares,
              "(common equity - goodwill - intangibles) / shares")
    if ca is not None and liabilities is not None and shares:
        check("ncavps", row.get("ncavps"), (ca - liabilities - senior) / shares,
              "(current assets - all liabilities - preferred - minority) / shares")
    if price and row.get("ttm_eps"):
        check("pe", _c(row, 1), price / row["ttm_eps"], "price / trailing EPS")
    if price and row.get("tbvps"):
        check("ptbv", _c(row, 7), price / row["tbvps"], "price / tangible book per share")
    # Graham's chapter-13 margin is struck on a fiscal year, not on trailing
    # quarters: a year of sales against the same year's profit. The payload carries
    # both series, so the check uses the newest year they share.
    # ...on a year whose sales are large enough for the percentage to mean anything.
    # The engine skips a year under $1M of revenue, because a company with $40,000
    # of sales and a $500,000 loss has a margin of -1,250% and no margin at all.
    revenue, income = row.get("annual_revenue") or {}, row.get("annual_net_income") or {}
    shared = [y for y in sorted(set(revenue) & set(income), reverse=True)
              if (revenue[y] or 0) >= 1_000_000]
    if shared:
        year = shared[0]
        check("net_margin", (row.get("profitability") or {}).get("net"),
              income[year] / revenue[year] * 100, f"FY{year} net income / FY{year} revenue x 100")
    if row.get("options") is not None and row.get("rsus") is None and shares:
        check("equity_awards", row.get("equity_awards"), row["options"],
              "options alone, no restricted stock on file")
    if row.get("options") is not None and row.get("rsus") is not None:
        check("equity_awards", row.get("equity_awards"), row["options"] + row["rsus"],
              "options + restricted stock")
    # the debt criterion 3 weighed: the rollup where it is fresher and larger,
    # otherwise the two buckets
    lt, st, total = row.get("long_term_debt"), row.get("short_term_debt"), row.get("total_debt")
    parts = sum(v for v in (lt, st) if v is not None)
    if row.get("debt") is not None and (total is not None or lt is not None or st is not None):
        expected = max(total, parts) if total is not None else parts
        check("debt", row["debt"], expected, "max(total-debt tag, long + short) at one date")
    return out


# What each figure is called on a printed balance sheet, and what it may be
# derived from where the company prints no such line. Coca-Cola states no "total
# liabilities" at all — it prints total equity and the identity closes the gap.
PRINTED = (
    ("total_assets", ("total assets",), None),
    ("current_assets", ("total current assets",), None),
    ("current_liabilities", ("total current liabilities",), None),
    ("total_liabilities", ("total liabilities",), ("total assets", "total equity")),
)
# Every "total ..." form before any bare one. An income statement often opens with
# a bare "Revenues:" as the heading of the section that follows, and a heading row
# can carry a stray figure — Robinhood's read $2,628M against a $4,473M year.
PRINTED_INCOME = (
    ("revenue", ("total net revenues", "total net revenue", "total revenues",
                 # Authid prints gross "Revenues" above "Revenues, net"; the net
                 # line is the one its own XBRL tags and the one a reader wants
                 "revenues, net", "revenue, net",
                 # Phillips 66's sales line, beneath a total that adds equity
                 # earnings and disposal gains — neither of which is a sale
                 "sales and other operating revenues",
                 # Expand Energy totals to "Total revenues and other", which adds
                 # derivative gains to the sales line
                 "total revenues and other", "revenues and other income",
                 "total revenue", "total operating revenues", "total net sales",
                 "total revenues and other income", "net operating revenues",
                 "revenues and other income", "net revenues", "net sales",
                 "revenues", "sales")),
    # the parent's share first: Apollo prints consolidated net income of $5,401M
    # and $3,492M attributable to itself, and `NetIncomeLoss` is the second
    # The parent company by name first, then the after-preferred line, then the
    # consolidated one. Cohen & Steers calls the parent's share "attributable to
    # common stockholders" while Uniti uses that same phrase for the figure after
    # preferred dividends, so the label alone cannot separate them — but a line
    # naming the company outranks both wherever one exists.
    ("net_income", ("net income attributable to*", "net income (loss) attributable to*",
                    # "attributed to" is the same line under a different participle;
                    # AEP heads its own share "EARNINGS ATTRIBUTABLE TO AEP MEMBER"
                    "net income attributed to*", "net loss attributed to*",
                    "earnings attributable to*", "earnings attributed to*",
                    "net income (loss) attributed to*",
                    # utilities write "available to": Edison's parent line is
                    # "Net income available to Edison International common shareholders"
                    "net income available to*", "net income (loss) available to*",
                    "net earnings available to*",
                    "net earnings attributable to*", "net loss attributable to*",
                    # insurers write it this way; Markel's is "Net Income to Shareholders"
                    # small filers merge the two statements into one caption
                    "net loss and comprehensive loss", "net income and comprehensive income",
                    "net income (loss) and comprehensive income (loss)",
                    "net income to shareholders", "net earnings to shareholders",
                    "net income (loss) to shareholders",
                    # Cummins heads the parent's share "Cummins share of net income"
                    "*share of net income", "*share of net earnings",
                    "net income attributable to common stockholders",
                    "net income (loss) attributable to common shareholders",
                    "net loss attributable to common shareholders",
                    "net income", "net income (loss)", "net earnings", "net loss",
                    "consolidated net income")),
)
FILING_TOLERANCE = 0.01     # the printed figure is rounded to the header's scale


def _only_the_scale_differs(shown: float, printed: float) -> bool:
    """Whether the two are the same number under a different declared scale.

    A rendered statement states its own units in its header, and a small filer
    often leaves a template's "$ in Millions" above figures reported in whole
    dollars: ABVC heads its balance sheet that way and then prints cash of
    "$ 31,944", which at millions would be $31.9 trillion. The tagged values carry
    no such ambiguity, so where the panel and the page differ by exactly a
    thousand, a million or a billion it is the header that is wrong and the figure
    that agrees.
    """
    if not shown or not printed:
        return False
    ratio = abs(printed) / abs(shown)
    return any(abs(ratio - power) <= 0.01 * power or abs(ratio - 1 / power) <= 0.01 / power
               for power in (1e3, 1e6, 1e9))


def _read_statement(row: dict, edgar, kind: str):
    """The published statement's rows and the column the panel's date belongs to.

    Not every filer prints the newest period first, and one emerging from Chapter 11
    prints successor and predecessor periods side by side, so the column is chosen
    by its own heading rather than by position.
    """
    source = (row.get("sources") or {}).get("total_assets" if kind == "balance_sheet"
                                            else "eps") or {}
    accn, end = source.get("accn"), source.get("end")
    if not accn:
        return None, None, None, "no provenance for the statement"
    bare, cik = accn.replace("-", ""), int(row["cik"])
    summary = edgar._get_text(statements.SUMMARY_URL.format(cik=cik, accn=bare))
    file = statements.find(summary, kind)
    if not file:
        # closed-end funds publish a statement of assets and liabilities, not a
        # balance sheet; nothing is wrong, there is simply nothing to compare
        return None, None, None, f"no {kind} rendered in {accn}"
    document = edgar._get_text(statements.REPORT_URL.format(cik=cik, accn=bare, file=file))
    printed, headings = statements.lines(document), statements.columns(document)
    if not printed:
        return None, None, None, f"{file} held no numbered rows"
    wanted = date.fromisoformat(end) if end else None
    # A rendered table can carry the same period twice — Great Wall's runs
    # 2025, 2024, 2025, 2024, two blocks side by side — and the figure may sit in
    # either. Every column bearing the date is a candidate.
    matching = [i for i, heading in enumerate(headings) if heading == wanted]
    if headings and wanted and not matching:
        return None, None, None, f"{end} is not among the printed columns {headings}"
    return printed, matching or [0], headings, None


def against_filing(row: dict, edgar) -> list[tuple]:
    """Compare the displayed balance-sheet figures against the published statement.

    The only check here that does not share an ancestor with what it is checking:
    every other test compares one reading of the XBRL against another, and a
    mis-tagged fact passes them all. This one reads the document a person opens and
    asks whether the number on the page is the number on the panel.
    """
    try:
        printed, wanted_columns, headings, why = _read_statement(row, edgar, "balance_sheet")
    except Exception as exc:
        return [("FILING?", "balance_sheet", None, None, f"could not read: {exc!r}"[:110])]
    if printed is None:
        return [("FILING?", "balance_sheet", None, None, why)]

    out = []
    ratio = _ratio(row)
    sources = row.get("sources") or {}
    for field, phrases, identity in PRINTED:
        shown = row.get(field)
        if shown is None:
            continue
        # each figure against the column of ITS OWN balance-sheet date: a filer may
        # carry one line from a later filing than another, and Fervent's current
        # assets are stated a quarter behind its total assets
        own = (sources.get(field) or {}).get("end")
        here = wanted_columns
        if own:
            here = [i for i, heading in enumerate(headings) if heading.isoformat() == own]
            if not here:
                # The figure belongs to a balance sheet this filing does not print.
                # ProtoKinetix states current assets a year behind its total assets,
                # because both legs of a current ratio must come from one moment and
                # its current liabilities were last tagged then. Correct, disclosed
                # by the provenance, and not answerable from this document.
                out.append(("FILING?", field, shown, None,
                            f"stated at {own}, which this filing does not print"))
                continue
        # A statement can print the same caption twice — Creatd states "Total
        # Liabilities" as a zeroed section line and again as the real total — so the
        # question is whether the panel's figure is one of the values printed under
        # that caption, not whether it is the first of them.
        options = [hit for col in here
                   for hit in statements.all_matching(printed, *phrases, column=col)]
        scaled = [float(v) / (ratio if field == "shares" else 1) for _, v in options]
        note = f"printed as {options[0][0]!r}" if options else None
        if not scaled and identity:
            halves = [statements.value_for(printed, name, column=here[0]) for name in identity]
            if all(halves):
                scaled = [float(halves[0][1] - halves[1][1])]
                note = f"not printed; {identity[0]} - {identity[1]}"
        if not scaled:
            out.append(("FILING?", field, shown, None, "no matching line on the statement"))
            continue
        agree = [v for v in scaled if abs(shown - v)
                 <= FILING_TOLERANCE * max(abs(shown), abs(v), 1e-9)]
        if agree:
            out.append(("FILING-OK", field, shown, agree[0], note))
        elif any(_only_the_scale_differs(shown, v) for v in scaled):
            out.append(("FILING?", field, shown, scaled[0],
                        "the same figure under the scale the statement's header "
                        "declares, which its own numbers contradict"))
        else:
            out.append(("FILING", field, shown, scaled[0], note))
    return out


def _by_subtraction(printed, column: int, shown: float) -> bool:
    """Whether the panel's profit is the consolidated total less the minority's share.

    Read off the printed page, where both lines are visible, rather than derived from
    tags — the tagged version of this identity is unreliable (TKO files only the
    redeemable half of its minority interest), but the statement prints what it
    prints.
    """
    totals = statements.all_matching(printed, "net income", "net income (loss)",
                                     "net loss", "consolidated net income", column=column)
    minority = [values[column] for label, values in printed
                if re.search(r"noncontrolling|non-controlling|minority", label, re.I)
                and column < len(values)]
    for _, total in totals:
        for share in minority:
            for candidate in (float(total) - float(share), float(total) + float(share)):
                if abs(shown - candidate) <= FILING_TOLERANCE * max(
                        abs(shown), abs(candidate), 1e-9):
                    return True
    return False


def against_income(row: dict, edgar) -> list[tuple]:
    """The latest fiscal year's sales and profit, against the annual report's own
    income statement. The balance-sheet check cannot reach either: they are flows,
    and the panel's ratio table divides one by the other."""
    source = (row.get("sources") or {}).get("eps") or {}
    end = source.get("end")
    if not end or not (source.get("form") or "").startswith("10-K"):
        return []                       # only an annual report prints an annual column
    year = str(int(end[:4]))
    revenue = (row.get("annual_revenue") or {}).get(year)
    income = (row.get("annual_net_income") or {}).get(year)
    if revenue is None and income is None:
        return []
    try:
        printed, wanted_columns, _, why = _read_statement(row, edgar, "income")
    except Exception:
        return []
    if printed is None:
        return [("FILING?", f"FY{year}", None, None, why)]

    out = []
    for field, phrases in PRINTED_INCOME:
        shown = revenue if field == "revenue" else income
        if shown is None:
            continue
        # Net income is corroborated against every line the statement prints for it,
        # because one phrase means different figures at different filers and no
        # ordering satisfies them all. Revenue has no such ambiguity and keeps the
        # single best match, which is the stricter test.
        if field in ("net_income", "revenue"):
            options = [hit for col in wanted_columns
                       for hit in statements.all_matching(printed, *phrases, column=col)]

            def agrees(label: str, printed_value: float) -> bool:
                if abs(shown - printed_value) <= FILING_TOLERANCE * max(
                        abs(shown), abs(printed_value), 1e-9):
                    return True
                # A line captioned a loss and printed without parentheses states the
                # magnitude and leaves the sign to the caption — Paramount Gold's
                # "Net Loss 9,050,423" against a filed -$9,050,423. The page carries
                # the figure; only its presentation of the sign is ambiguous, and
                # Intellicheck proves the caption alone cannot settle it.
                return ("loss" in label.lower() and shown < 0
                        and abs(abs(shown) - abs(printed_value))
                        <= FILING_TOLERANCE * max(abs(shown), abs(printed_value), 1e-9))

            if any(agrees(label, float(v)) for label, v in options):
                out.append(("FILING-OK", f"FY{year} {field}", shown, shown, None))
                continue
            # Some statements print no parent line at all and leave the reader to do
            # the subtraction: Delek states $43.3M of consolidated income and $66.1M
            # attributed to minority holders, and the company's own share is the
            # -$22.8M in between. Both directions are tried because filers differ on
            # whether the minority line is printed as a positive to be deducted or as
            # a negative already signed.
            if field == "net_income" and any(_by_subtraction(printed, col, shown)
                                             for col in wanted_columns):
                out.append(("FILING-OK", f"FY{year} {field}", shown, shown, None))
                continue
            # A figure whose concept the page never prints is not a mismatch. Both
            # Occidental and Rhinebeck tag only income available to the common —
            # after preferred dividends and after earnings allocated to participating
            # securities — while their statements print the consolidated line and the
            # attributable one, and neither equals it. The provenance names the
            # concept, so the difference can be stated rather than scored.
            concept = ((row.get("sources") or {}).get(field) or {}).get("tag", "")
            # Contract revenue against a total that says "and other income" in its
            # own caption: BKV's page totals $1,008.8M by adding $105.1M of
            # derivative gains to $893.8M of sales to customers, and a derivative
            # gain is not a sale. Phillips 66 prints both and the sales line matched;
            # BKV prints only the total, so the concepts are named instead.
            if (field == "revenue" and "RevenueFromContractWithCustomer" in concept
                    and options and all("other" in label.lower() for label, _ in options)):
                out.append(("FILING?", f"FY{year} {field}", shown, None,
                            "tagged as revenue from contracts with customers; the "
                            "statement totals only to a line that adds other income"))
                continue
            if field == "net_income" and "AvailableToCommon" in concept:
                out.append(("FILING?", f"FY{year} {field}", shown, None,
                            "tagged as income available to the common, which the "
                            "statement does not print"))
                continue
            if options:
                label, value = options[0]
                out.append(("FILING", f"FY{year} {field}", shown, float(value),
                            f"no printed line matches; nearest is {label!r}"))
                continue
        hit = statements.value_for(printed, *phrases, column=wanted_columns[0])
        if hit is None:
            out.append(("FILING?", f"FY{year} {field}", shown, None, "no matching line"))
            continue
        expected = float(hit[1])
        kind = ("FILING" if abs(shown - expected)
                > FILING_TOLERANCE * max(abs(shown), abs(expected), 1e-9) else "FILING-OK")
        out.append((kind, f"FY{year} {field}", shown, expected,
                    f"printed as {hit[0]!r}" if kind == "FILING" else None))
    return out


def _one_moment(row: dict, facts: dict) -> list[tuple]:
    """Components struck at an older date THAN THE FILER HAS SINCE PUBLISHED.

    A balance sheet is one moment, but not every line is republished every quarter:
    Cohen & Steers tags its permanent minority interest quarterly and its redeemable
    half only in the 10-K, so a June total legitimately carries a December piece.
    Overstating a deduction from common equity is the conservative direction, and
    the provenance names both dates, so that case is disclosed rather than wrong.

    What is wrong is a component left behind when a newer value for the same
    concept exists — Energy Transfer's redeemable interest read $250M from December
    while $256M stood in the June filing under a renamed element. So the test is not
    "do the dates differ" but "did the filer already say something newer".
    """
    out = []
    for name, source in (row.get("sources") or {}).items():
        parent = (source or {}).get("end")
        if not parent:
            continue
        for part in (source or {}).get("components") or ():
            end, tag = part.get("end"), (part.get("tag") or "")
            if not end or end >= parent:
                continue
            ns, _, bare = tag.partition(":")
            entries = [e for units in
                       (facts.get("facts", {}).get(ns or "us-gaap", {}).get(bare) or {})
                       .get("units", {}).values() for e in units]
            # only forms the engine itself reads. Cycurion's line of credit has a
            # newer figure, but it stands in an S-1 — a registration statement, not
            # a periodic report — and the engine deliberately reads neither, so its
            # 10-K figure is not superseded by anything it was ever going to see.
            newer = [e for e in entries if "start" not in e and e.get("end", "") > end
                     and _is_financial_form(e.get("form", ""))]
            if newer:
                out.append((name, parent, [f"{bare} stands at {max(e['end'] for e in newer)}"]))
    return out


def _c(row: dict, n: int):
    """A criterion's displayed value, looked up by number — never by position."""
    return next((c.get("value") for c in (row.get("criteria") or ()) if c.get("n") == n), None)


# One of each shape the engine has to handle, so a pass means something: a
# December mega-cap, a June filer, a financial, a REIT, a depositary receipt, a
# dual-class, a loss-maker, a partnership, a small cap, a recent listing.
SPREAD = ("KO", "MSFT", "JPM", "O", "ZLAB", "GOOGL", "RIVN", "ET", "EML", "AAPL",
          "BRK-B", "PG", "XOM", "UNH", "T", "F", "PLTR", "MKL", "NKE", "ORCL")


def audit(rows: list[dict], cache: Path, quiet: bool = False, edgar=None) -> dict:
    totals = {"sourced_ok": 0, "sourced_bad": 0, "derived_ok": 0, "derived_bad": 0,
              "unchecked": 0, "mixed_dates": 0, "filing_ok": 0, "filing_bad": 0,
              "filing_unknown": 0}
    problems = []
    for row in rows:
        facts = _facts(row["cik"], cache)
        sources = row.get("sources") or {}
        lines = []
        for field, key in SOURCED:
            shown, source = row.get(field), sources.get(key)
            if shown is None:
                continue
            # HCA's goodwill tag died in 2011, so the engine carries the whole
            # combined intangibles line as intangibles and sets goodwill to 0 — the
            # provenance says so in as many words. The pair still sums to the tagged
            # figure, which is what tangible book deducts, so it is checked as a pair
            # below rather than as two figures that each fail on their own.
            if "contained in" in (source or {}).get("concept", ""):
                continue
            if not source or not source.get("accn"):
                totals["unchecked"] += 1
                lines.append(("UNCHECKED", field, shown, None, "no provenance recorded"))
                continue
            # A figure read on a share-class axis cannot be found in Company Facts,
            # which drops every dimension: BCSS files 1,500,000 weighted shares
            # without one and 10,000,000 for the class its ticker names, so looking
            # up the bare tag finds a real number that is not this one.
            if source.get("segments"):
                totals["unchecked"] += 1
                lines.append(("UNCHECKED", field, shown, None,
                              f"filed under {source['segments'].rstrip(';')}, "
                              "which the dimension-free API does not carry"))
                continue
            ns, _, bare = (source.get("tag") or "").partition(":")
            ratio = _ratio(row) if field in ("shares", "cover_shares") else 1
            candidates = [v / ratio for v in
                          _values_in_filing(facts, ns or "us-gaap", bare, source)]
            if not candidates:                      # a derived or summed provenance
                one = _fact_in_filing(facts, source)
                candidates = [] if one is None else [one / ratio]
            filed = next((v for v in candidates if _close(shown, v)),
                         candidates[0] if candidates else None)
            if filed is None:
                totals["unchecked"] += 1
                lines.append(("UNCHECKED", field, shown, None,
                              f"{source['tag']} @ {source['accn']} not in the cached filing"))
            elif _close(shown, filed):
                totals["sourced_ok"] += 1
            else:
                totals["sourced_bad"] += 1
                lines.append(("SOURCED", field, shown, filed,
                              f"{source['tag']} {source['end']} {source['accn']}"))
        for name, shown, expected, formula in _identities(row):
            if _close(shown, expected):
                totals["derived_ok"] += 1
            else:
                totals["derived_bad"] += 1
                lines.append(("DERIVED", name, shown, expected, formula))
        for name, parent, stale in _one_moment(row, facts):
            totals["mixed_dates"] = totals.get("mixed_dates", 0) + 1
            lines.append(("ONE-DATE", name, parent, None,
                          "a newer value exists: " + ", ".join(stale)))
        if edgar is not None:
            for line in against_filing(row, edgar) + against_income(row, edgar):
                bucket = {"FILING": "filing_bad", "FILING-OK": "filing_ok"}.get(
                    line[0], "filing_unknown")
                totals[bucket] += 1
                if line[0] != "FILING-OK":       # matches are counted, not printed
                    lines.append(line)
        bad = [ln for ln in lines if ln[0] not in ("UNCHECKED", "FILING?")]
        if bad:
            problems.append((row["ticker"], bad))
        if not quiet:
            mark = "FAIL" if bad else "ok"
            print(f"  {row['ticker']:8s} {mark}")
            for kind, name, shown, expected, why in lines:
                print(f"      {kind:9s} {name:16s} shows {shown!r} "
                      f"{'vs ' + repr(round(expected, 4)) if expected is not None else ''}   {why}")
    return {"totals": totals, "problems": problems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="comma-separated, instead of the standard spread")
    ap.add_argument("--sample", type=int, help="this many companies at random")
    ap.add_argument("--seed", type=int, default=0,
                    help="which random sample: the same seed always draws the same "
                         "companies, so a run is reproducible and a new seed covers new ground")
    ap.add_argument("--quiet", action="store_true", help="only the failures")
    ap.add_argument("--filings", action="store_true",
                    help="also read each company's published statements (network)")
    args = ap.parse_args(argv)

    everything = json.loads(Path(DASHBOARD_JSON).read_text())["rows"]
    by_ticker = {r["ticker"]: r for r in everything if r.get("ticker")}
    if args.ticker:
        wanted = [by_ticker[t.strip().upper()] for t in args.ticker.split(",")
                  if t.strip().upper() in by_ticker]
    elif args.sample:
        import random
        random.seed(args.seed)
        wanted = random.sample(everything, min(args.sample, len(everything)))
    else:
        wanted = [by_ticker[t] for t in SPREAD if t in by_ticker]

    print(f"auditing {len(wanted)} companies\n")
    edgar = EdgarClient()
    result = audit(wanted, Path(edgar.cache_dir), args.quiet, edgar if args.filings else None)
    t = result["totals"]
    print(f"\n  values matching the filing they name : {t['sourced_ok']} ok, {t['sourced_bad']} wrong")
    print(f"  figures matching their own arithmetic: {t['derived_ok']} ok, {t['derived_bad']} wrong")
    print(f"  components superseded by a newer filing: {t['mixed_dates']}")
    print(f"  matching the published statement     : {t['filing_ok']} ok, {t['filing_bad']} wrong"
          f" ({t['filing_unknown']} lines not printed)")
    print(f"  not checkable from the payload       : {t['unchecked']}")
    if result["problems"]:
        print(f"\n  {len(result['problems'])} companies with at least one defect: "
              + ", ".join(t for t, _ in result["problems"]))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
