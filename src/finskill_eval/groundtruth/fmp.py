"""FMP client — the candidate data source (M4). Never used as gold.

Maps each canonical label to an FMP endpoint + field, fetches the statement
list, and picks the row matching the requested fiscal period. The HTTP fetcher
is injected so tests run without network; the default fetcher uses httpx with
tenacity backoff and respects FMP's rate limits / 429s.

Defensive: FMP self-discloses occasional thousands/millions denomination
errors, so check_denomination() sanity-checks magnitudes and logs suspects.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from finskill_eval.groundtruth.base import Value

logger = logging.getLogger(__name__)

# canonical label -> (endpoint, field).
# Extending this is bounded (financial metric universe is closed) and one-line
# per addition; this is NOT the open-ended parser problem.
LABEL_MAP: dict[str, tuple[str, str]] = {
    # income-statement
    "revenue": ("income-statement", "revenue"),
    "net_income": ("income-statement", "netIncome"),
    "gross_profit": ("income-statement", "grossProfit"),
    "operating_income": ("income-statement", "operatingIncome"),
    "ebitda": ("income-statement", "ebitda"),
    "shares_outstanding": ("income-statement", "weightedAverageShsOutDil"),
    "diluted_eps": ("income-statement", "epsdiluted"),
    "basic_eps": ("income-statement", "eps"),
    "cost_of_revenue": ("income-statement", "costOfRevenue"),
    "rd_expense": ("income-statement", "researchAndDevelopmentExpenses"),
    "sga_expense": ("income-statement", "sellingGeneralAndAdministrativeExpenses"),
    "interest_expense": ("income-statement", "interestExpense"),
    "depreciation_and_amortization": ("income-statement", "depreciationAndAmortization"),
    # balance-sheet
    "cash_and_equivalents": ("balance-sheet-statement", "cashAndCashEquivalents"),
    "short_term_investments": ("balance-sheet-statement", "shortTermInvestments"),
    "total_debt": ("balance-sheet-statement", "totalDebt"),
    "long_term_debt": ("balance-sheet-statement", "longTermDebt"),
    "short_term_debt": ("balance-sheet-statement", "shortTermDebt"),
    "total_equity": ("balance-sheet-statement", "totalStockholdersEquity"),
    "total_assets": ("balance-sheet-statement", "totalAssets"),
    # cash-flow
    "operating_cash_flow": ("cash-flow-statement", "operatingCashFlow"),
    "capital_expenditures": ("cash-flow-statement", "capitalExpenditure"),
    "free_cash_flow": ("cash-flow-statement", "freeCashFlow"),
    "dividends_paid": ("cash-flow-statement", "netDividendsPaid"),
    "share_repurchases": ("cash-flow-statement", "commonStockRepurchased"),
    "acquisitions": ("cash-flow-statement", "acquisitionsNet"),
    # market / valuation
    "market_capitalization": ("key-metrics", "marketCap"),
    "enterprise_value": ("key-metrics", "enterpriseValue"),
    "price": ("quote", "price"),
    # FMP-published derived metrics (skip our recompute, use FMP's number)
    # Margins are stored as fractions in FMP's `ratios` endpoint; the verifier
    # already handles scale-normalization so 0.4621 vs 46.21 will land in band.
    "gross_margin": ("ratios", "grossProfitMargin"),
    "operating_margin": ("ratios", "operatingProfitMargin"),
    "net_margin": ("ratios", "netProfitMargin"),
    "ebitda_margin": ("ratios", "ebitdaratio"),
    "pe_ratio": ("ratios", "priceEarningsRatio"),
    "ev_ebitda": ("key-metrics", "enterpriseValueOverEBITDA"),
    "ps_ratio": ("ratios", "priceToSalesRatio"),
    "pb_ratio": ("ratios", "priceToBookRatio"),
    "dividend_yield": ("ratios", "dividendYield"),
    "interest_coverage": ("ratios", "interestCoverage"),
    "debt_to_equity": ("ratios", "debtEquityRatio"),
    "fcf_yield": ("ratios", "freeCashFlowYield"),
}

Fetch = Callable[[str, dict], object]


def check_denomination(statement: dict) -> list[str]:
    """Flag suspected scale (thousands/millions) errors within a statement."""
    warnings: list[str] = []
    rev = statement.get("revenue")
    ni = statement.get("netIncome")
    if rev and ni and abs(ni) > abs(rev) * 1.5:
        warnings.append(
            f"net income ({ni}) exceeds revenue ({rev}) by >1.5x — suspected "
            "denomination/scale error"
        )
    return warnings


def _fiscal_year(period: str) -> Optional[int]:
    m = re.fullmatch(r"FY(\d{4})", period or "")
    return int(m.group(1)) if m else None


class FMPClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://financialmodelingprep.com/stable/",
        fetch: Optional[Fetch] = None,
        rate_limit_rps: float = 1.5,
        max_retries: int = 4,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._rate_limit_rps = rate_limit_rps
        self._max_retries = max_retries
        self._fetch = fetch or self._default_fetch

    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]:
        spec = LABEL_MAP.get(canonical_label)
        if spec is None:
            return None
        endpoint, field = spec
        fy = _fiscal_year(period or "")
        if fy is None:
            return None

        rows = self._fetch(endpoint, {"symbol": ticker})
        if not isinstance(rows, list):
            return None
        row = next(
            (r for r in rows if int(r.get("fiscalYear", r.get("calendarYear", -1))) == fy),
            None,
        )
        if row is None or field not in row or row[field] is None:
            return None

        for w in check_denomination(row):
            logger.warning("FMP %s %s: %s", ticker, period, w)

        return Value(
            value=float(row[field]),
            unit="USD",
            vintage=str(row.get("date", period)),
            source_id="fmp",
            period=period,
            canonical_label=canonical_label,
        )

    def _default_fetch(self, endpoint: str, params: dict) -> object:
        import httpx
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        if not self._api_key:
            raise RuntimeError("FMP_API_KEY required for live fetch")

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type(httpx.HTTPStatusError),
            reraise=True,
        )
        def _do() -> object:
            url = self._base_url + endpoint
            resp = httpx.get(
                url, params={**params, "apikey": self._api_key}, timeout=30.0
            )
            resp.raise_for_status()
            return resp.json()

        return _do()
