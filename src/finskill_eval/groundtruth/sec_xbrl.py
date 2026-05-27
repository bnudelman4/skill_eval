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


def _end_year(end: Optional[str]) -> Optional[int]:
    m = re.match(r"(\d{4})-", end or "")
    return int(m.group(1)) if m else None


class SECXBRLClient:
    def __init__(
        self,
        *,
        user_agent: str,
        cik_lookup: Optional[dict[str, str]] = None,
        company_facts_url: str = "https://data.sec.gov/api/xbrl/companyfacts/",
        tickers_url: str = "https://www.sec.gov/files/company_tickers.json",
        fetch: Optional[Fetch] = None,
        tickers_fetch: Optional[Callable[[], dict]] = None,
    ):
        self._ua = user_agent
        self._cik = dict(cik_lookup or {})
        self._url = company_facts_url
        self._tickers_url = tickers_url
        self._fetch = fetch or self._default_fetch
        self._tickers_fetch = tickers_fetch or self._default_tickers_fetch
        self._tickers_loaded = False

    def _resolve_cik(self, ticker: str) -> Optional[str]:
        """Ticker -> 10-digit zero-padded CIK. Explicit cik_lookup wins; else
        lazily load + cache SEC's company_tickers.json mapping."""
        t = ticker.upper()
        if t in self._cik:
            return self._cik[t]
        if not self._tickers_loaded:
            try:
                data = self._tickers_fetch()
            except Exception:
                data = {}
            for row in (data.values() if isinstance(data, dict) else data):
                sym = str(row.get("ticker", "")).upper()
                if sym:
                    self._cik.setdefault(sym, str(row["cik_str"]).zfill(10))
            self._tickers_loaded = True
        return self._cik.get(t)

    def _default_tickers_fetch(self) -> dict:
        import httpx

        resp = httpx.get(self._tickers_url, headers={"User-Agent": self._ua}, timeout=30.0)
        resp.raise_for_status()
        return resp.json()

    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]:
        concepts = CONCEPT_MAP.get(canonical_label)
        if concepts is None:
            return None
        fy = _fiscal_year(period or "")
        if fy is None:
            return None
        cik = self._resolve_cik(ticker)
        if cik is None:
            return None

        facts = self._fetch(cik).get("facts", {}).get("us-gaap", {})
        for concept in concepts:
            entry = facts.get(concept)
            if not entry:
                continue
            for unit_rows in entry.get("units", {}).values():
                # Select by the DATA period's end-date year, not the filing's
                # `fy`: one 10-K reports 3 comparative years all tagged with the
                # filing fy, so fy-matching alone returns the earliest year.
                # Among matches (restatements across filings) prefer the latest
                # `filed` (most recently reported value).
                candidates = [
                    r
                    for r in unit_rows
                    if r.get("fp") == "FY"
                    and str(r.get("form", "")).startswith("10-K")
                    and _end_year(r.get("end")) == fy
                ]
                row = max(candidates, key=lambda r: r.get("filed", ""), default=None)
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
