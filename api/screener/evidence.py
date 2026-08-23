"""Assemble every local input required to normalize one filer.

Fetching and interpretation remain separate: callers may supply freshly fetched
Company Facts, while this layer consistently adds the slower-moving evidence
kept beside it (DERA dimensions and the filing-cover security description).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import store
from .sources import dera


@dataclass(frozen=True)
class EvidenceBundle:
    cik: str
    ticker: str
    facts: dict
    dimensioned: dict | None
    receipt: dict | None


class EvidenceLoader:
    """One evidence policy shared by every snapshot-producing workflow."""

    def __init__(self, conn, edgar):
        self.edgar = edgar
        # SEC's current ticker file intentionally omits a delisted security, but
        # its cached facts and cover still belong to the last symbol this database
        # knew.  A caller with no current mapping must not replace that security
        # identity with the CIK: share-class selection and cover matching both use
        # the symbol.  Export decides separately whether the security is tradable.
        self._stored_tickers = {
            row["cik"]: row["ticker"]
            for row in conn.execute(
                "SELECT cik, ticker FROM company WHERE ticker IS NOT NULL"
            )
        }
        self._covers = {
            (cik, security["symbol"]): security
            for cik, securities in store.covers_by_cik(conn).items()
            for security in securities
        }

    def load(self, cik: str, ticker: str | None,
             facts: dict | None = None) -> EvidenceBundle:
        if facts is None:
            path = self.edgar.cache_dir / f"companyfacts_{cik}.json"
            facts = json.loads(path.read_text()) if path.exists() else self.edgar.company_facts(cik)
        ticker = ticker or self._stored_tickers.get(cik) or cik
        return EvidenceBundle(
            cik=cik,
            ticker=ticker,
            facts=facts,
            dimensioned=dera.load_sidecar(self.edgar.cache_dir, cik),
            receipt=self._covers.get((cik, ticker)),
        )
