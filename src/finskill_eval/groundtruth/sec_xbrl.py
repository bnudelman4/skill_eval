"""SEC EDGAR XBRL client (M4).

Independent as-originally-reported anchor (and bootstrap gold while Daloopa is
pending). Reads the company-facts API, maps canonical labels to ordered lists
of US-GAAP concepts (first present wins), and selects the annual (10-K, fp=FY)
datum for the requested fiscal year. Market metrics (market cap, EV) are not in
XBRL and return None. EDGAR requires a descriptive User-Agent; the fetcher is
injected so tests run without network.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from finskill_eval.groundtruth.base import Value

# canonical label -> ordered candidate US-GAAP concepts (first present wins)
CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "dividends_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "share_repurchases": ["PaymentsForRepurchaseOfCommonStock"],
    "shares_outstanding": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}

Fetch = Callable[[str], dict]


def _fiscal_year(period: str) -> Optional[int]:
    m = re.fullmatch(r"FY(\d{4})", period or "")
    return int(m.group(1)) if m else None


class SECXBRLClient:
    def __init__(
        self,
        *,
        user_agent: str,
        cik_lookup: Optional[dict[str, str]] = None,
        company_facts_url: str = "https://data.sec.gov/api/xbrl/companyfacts/",
        fetch: Optional[Fetch] = None,
    ):
        self._ua = user_agent
        self._cik = cik_lookup or {}
        self._url = company_facts_url
        self._fetch = fetch or self._default_fetch

    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]:
        concepts = CONCEPT_MAP.get(canonical_label)
        if concepts is None:
            return None
        fy = _fiscal_year(period or "")
        if fy is None:
            return None
        cik = self._cik.get(ticker)
        if cik is None:
            return None

        facts = self._fetch(cik).get("facts", {}).get("us-gaap", {})
        for concept in concepts:
            entry = facts.get(concept)
            if not entry:
                continue
            for unit_rows in entry.get("units", {}).values():
                row = next(
                    (
                        r
                        for r in unit_rows
                        if r.get("fy") == fy
                        and r.get("fp") == "FY"
                        and str(r.get("form", "")).startswith("10-K")
                    ),
                    None,
                )
                if row is not None:
                    return Value(
                        value=float(row["val"]),
                        unit="USD",
                        vintage=str(row.get("end", period)),
                        source_id="sec_xbrl",
                        period=period,
                        canonical_label=canonical_label,
                    )
        return None

    def _default_fetch(self, cik: str) -> dict:
        import httpx

        url = f"{self._url}CIK{cik}.json"
        resp = httpx.get(url, headers={"User-Agent": self._ua}, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
