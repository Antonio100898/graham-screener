"""SEC Financial Statement Data Sets — the facts Company Facts cannot express.

The Company Facts API returns only undimensioned facts from the standard
taxonomies, so two kinds of reported figure never reach us: anything qualified
by a dimension (KKR's earnings per share carry `ClassOfStock=CommonStock`, and
the API drops them), and anything an issuer defined in its own namespace.

SEC's quarterly datasets carry both, already normalised, one file per quarter —
which is why this reads them instead of parsing Inline XBRL out of the filings.
The cost is a publication lag of about a month after quarter end, so these
facts supplement Company Facts and never replace it as the freshness source.

Layer 1 only: this fetches and reshapes, and decides nothing. Which dimension
member represents the company is a normalisation question, answered upstream.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

DATASET_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
# co-registrant rows describe a subsidiary that files alongside the parent, not
# the consolidated company the screen is about
_PARENT_ONLY = ""


@dataclass(frozen=True)
class Quarter:
    year: int
    q: int

    def __str__(self) -> str:
        return f"{self.year}q{self.q}"

    def next(self) -> "Quarter":
        return Quarter(self.year + 1, 1) if self.q == 4 else Quarter(self.year, self.q + 1)


def parse_quarter(text: str) -> Quarter:
    year, _, q = text.lower().partition("q")
    return Quarter(int(year), int(q))


def quarters_through(start: Quarter, end: Quarter) -> list[Quarter]:
    out, cur = [], start
    while (cur.year, cur.q) <= (end.year, end.q):
        out.append(cur)
        cur = cur.next()
    return out


def latest_published(today: date) -> Quarter:
    """SEC publishes a quarter roughly a month after it closes, so the newest
    dataset on offer describes the quarter before last at the turn of a month."""
    q = (today.month - 1) // 3 + 1
    year = today.year
    for _ in range(2):  # step back two quarters: one closed, one for the lag
        q -= 1
        if q == 0:
            q, year = 4, year - 1
    return Quarter(year, q)


def download(quarter: Quarter, cache_dir: Path, user_agent: str) -> Path | None:
    """The zip for one quarter, cached. Datasets are immutable once published."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"dera_{quarter}.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = DATASET_URL.format(quarter=quarter)
    with httpx.stream("GET", url, headers={"User-Agent": user_agent},
                      timeout=None, follow_redirects=True) as resp:
        if resp.status_code == 404:
            return None  # not published yet
        resp.raise_for_status()
        tmp = path.with_suffix(".part")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
        tmp.rename(path)
    return path


def _period(ddate: str, qtrs: str) -> tuple[str | None, str]:
    """DERA states a period end and a length in quarters; the rest of the code
    speaks start/end, so reconstruct it. Length 0 means a balance-sheet instant."""
    end = date(int(ddate[:4]), int(ddate[4:6]), int(ddate[6:8]))
    n = int(qtrs)
    if n == 0:
        return None, end.isoformat()
    months = n * 3
    year, month = end.year, end.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(end.day, [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30,
                        31, 31, 30, 31, 30, 31][month - 1])
    # a period runs from the day after the previous close
    start = date(year, month, day)
    return (start + (date(1, 1, 2) - date(1, 1, 1))).isoformat(), end.isoformat()


def harvest(zip_path: Path, ciks: set[str], tags: frozenset[str],
            per_share_tags: frozenset[str] = frozenset(),
            extension_floor: float = 1e8) -> dict[str, dict]:
    """Facts for the companies and concepts we care about, in companyfacts shape.

    Returns {cik: {"facts": {namespace: {tag: {"units": {unit: [entry, ...]}}}}}},
    every entry carrying its `segments` string so a later layer can decide what
    the dimension means. Issuer-extension facts are kept when material, under
    their own namespace, so they can be disclosed rather than computed with.
    """
    out: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path) as z:
        submissions: dict[str, tuple[str, str, str]] = {}
        with z.open("sub.txt") as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                                      delimiter="\t"):
                cik = str(int(row["cik"])).zfill(10)
                if cik in ciks:
                    submissions[row["adsh"]] = (cik, row.get("form", ""), row.get("filed", ""))
        if not submissions:
            return out
        with z.open("num.txt") as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                                      delimiter="\t"):
                sub = submissions.get(row["adsh"])
                if sub is None or row.get("coreg", "") != _PARENT_ONLY:
                    continue
                value = row.get("value", "")
                if not value:
                    continue
                tag, version = row["tag"], row.get("version", "")
                standard = version.startswith(("us-gaap", "dei", "srt", "ifrs-full"))
                if standard:
                    if tag not in tags:
                        continue
                else:
                    try:
                        if abs(float(value)) < extension_floor:
                            continue
                    except ValueError:
                        continue
                cik, form, filed = sub
                start, end = _period(row["ddate"], row["qtrs"])
                unit = row.get("uom", "")
                if unit == "USD" and tag in per_share_tags:
                    unit = "USD/shares"  # DERA states the unit as USD for per-share concepts
                entry = {"end": end, "val": float(value), "accn": row["adsh"],
                         "form": form, "filed": _iso(filed), "fy": 0, "fp": "FY",
                         "segments": row.get("segments", "")}
                if start is not None:
                    entry["start"] = start
                namespace = version.split("/", 1)[0] if standard else f"ext:{version}"
                facts = out.setdefault(cik, {"facts": {}})["facts"]
                entries = facts.setdefault(namespace, {}).setdefault(tag, {"units": {}}) \
                               .setdefault("units", {}).setdefault(unit, [])
                entries.append(entry)
    return out


def _iso(filed: str) -> str:
    return f"{filed[:4]}-{filed[4:6]}-{filed[6:8]}" if len(filed) == 8 else filed


def sidecar_path(cache_dir: Path, cik: str) -> Path:
    return cache_dir / f"dimensioned_{cik}.json"


def merge_into_sidecars(harvested: dict[str, dict], cache_dir: Path, quarter: Quarter) -> int:
    """Accumulate quarters into one file per company. A filing appears in every
    quarter that carries it, so entries are deduplicated on what identifies a
    fact: its accession, period, unit and dimensions."""
    written = 0
    for cik, doc in harvested.items():
        path = sidecar_path(cache_dir, cik)
        existing = {"facts": {}, "quarters": []}
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except ValueError:
                pass
        for namespace, tags in doc["facts"].items():
            for tag, data in tags.items():
                for unit, entries in data["units"].items():
                    target = (existing.setdefault("facts", {}).setdefault(namespace, {})
                              .setdefault(tag, {"units": {}}).setdefault("units", {})
                              .setdefault(unit, []))
                    seen = {(e.get("accn"), e.get("start"), e.get("end"), e.get("segments"))
                            for e in target}
                    for e in entries:
                        key = (e.get("accn"), e.get("start"), e.get("end"), e.get("segments"))
                        if key not in seen:
                            target.append(e)
                            seen.add(key)
        quarters = set(existing.get("quarters") or ()) | {str(quarter)}
        existing["quarters"] = sorted(quarters)
        path.write_text(json.dumps(existing, separators=(",", ":")))
        written += 1
    return written


def load_sidecar(cache_dir: Path, cik: str) -> dict | None:
    path = sidecar_path(cache_dir, cik)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None
