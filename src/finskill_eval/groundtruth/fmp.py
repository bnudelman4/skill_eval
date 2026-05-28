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
# Comprehensive coverage of the FMP `stable/` API. Built by probing the live
# endpoints (income-statement, balance-sheet-statement, cash-flow-statement,
# key-metrics, ratios, financial-growth, enterprise-values, profile, quote)
# and mapping every analyst-facing metric to a canonical label.
#
# Extending this is bounded (financial metric universe is closed) and one-line
# per addition; this is NOT the open-ended parser problem.
LABEL_MAP: dict[str, tuple[str, str]] = {
    # ── income statement (direct) ────────────────────────────────────────
    "revenue": ("income-statement", "revenue"),
    "cost_of_revenue": ("income-statement", "costOfRevenue"),
    "gross_profit": ("income-statement", "grossProfit"),
    "operating_expenses": ("income-statement", "operatingExpenses"),
    "operating_income": ("income-statement", "operatingIncome"),
    "ebit": ("income-statement", "ebit"),
    "ebitda": ("income-statement", "ebitda"),
    "net_income": ("income-statement", "netIncome"),
    "income_before_tax": ("income-statement", "incomeBeforeTax"),
    "income_tax_expense": ("income-statement", "incomeTaxExpense"),
    "interest_expense": ("income-statement", "interestExpense"),
    "interest_income": ("income-statement", "interestIncome"),
    "depreciation_and_amortization": ("income-statement", "depreciationAndAmortization"),
    "rd_expense": ("income-statement", "researchAndDevelopmentExpenses"),
    "sga_expense": ("income-statement", "sellingGeneralAndAdministrativeExpenses"),
    "ga_expense": ("income-statement", "generalAndAdministrativeExpenses"),
    "selling_expense": ("income-statement", "sellingAndMarketingExpenses"),
    "eps": ("income-statement", "eps"),
    "diluted_eps": ("income-statement", "epsDiluted"),
    "basic_eps": ("income-statement", "eps"),
    "shares_outstanding": ("income-statement", "weightedAverageShsOutDil"),
    "weighted_shares_basic": ("income-statement", "weightedAverageShsOut"),
    "weighted_shares_diluted": ("income-statement", "weightedAverageShsOutDil"),

    # ── balance sheet (direct) ───────────────────────────────────────────
    "total_assets": ("balance-sheet-statement", "totalAssets"),
    "total_current_assets": ("balance-sheet-statement", "totalCurrentAssets"),
    "total_non_current_assets": ("balance-sheet-statement", "totalNonCurrentAssets"),
    "total_liabilities": ("balance-sheet-statement", "totalLiabilities"),
    "total_current_liabilities": ("balance-sheet-statement", "totalCurrentLiabilities"),
    "total_non_current_liabilities": ("balance-sheet-statement", "totalNonCurrentLiabilities"),
    "total_equity": ("balance-sheet-statement", "totalStockholdersEquity"),
    "total_debt": ("balance-sheet-statement", "totalDebt"),
    "long_term_debt": ("balance-sheet-statement", "longTermDebt"),
    "short_term_debt": ("balance-sheet-statement", "shortTermDebt"),
    "net_debt": ("balance-sheet-statement", "netDebt"),
    "cash_and_equivalents": ("balance-sheet-statement", "cashAndCashEquivalents"),
    "short_term_investments": ("balance-sheet-statement", "shortTermInvestments"),
    "long_term_investments": ("balance-sheet-statement", "longTermInvestments"),
    "cash_and_short_term_investments": ("balance-sheet-statement", "cashAndShortTermInvestments"),
    "accounts_receivable": ("balance-sheet-statement", "accountsReceivables"),
    "accounts_payable": ("balance-sheet-statement", "accountPayables"),
    "inventory": ("balance-sheet-statement", "inventory"),
    "goodwill": ("balance-sheet-statement", "goodwill"),
    "intangible_assets": ("balance-sheet-statement", "intangibleAssets"),
    "goodwill_and_intangibles": ("balance-sheet-statement", "goodwillAndIntangibleAssets"),
    "property_plant_equipment": ("balance-sheet-statement", "propertyPlantEquipmentNet"),
    "common_stock": ("balance-sheet-statement", "commonStock"),
    "retained_earnings": ("balance-sheet-statement", "retainedEarnings"),
    "capital_lease_obligations": ("balance-sheet-statement", "capitalLeaseObligations"),
    "deferred_revenue": ("balance-sheet-statement", "deferredRevenue"),
    "accrued_expenses": ("balance-sheet-statement", "accruedExpenses"),

    # ── cash flow statement (direct) ─────────────────────────────────────
    "operating_cash_flow": ("cash-flow-statement", "operatingCashFlow"),
    "investing_cash_flow": ("cash-flow-statement", "netCashProvidedByInvestingActivities"),
    "financing_cash_flow": ("cash-flow-statement", "netCashProvidedByFinancingActivities"),
    "capital_expenditures": ("cash-flow-statement", "capitalExpenditure"),
    "free_cash_flow": ("cash-flow-statement", "freeCashFlow"),
    "dividends_paid": ("cash-flow-statement", "netDividendsPaid"),
    "common_dividends_paid": ("cash-flow-statement", "commonDividendsPaid"),
    "share_repurchases": ("cash-flow-statement", "commonStockRepurchased"),
    "stock_issuance": ("cash-flow-statement", "commonStockIssuance"),
    "acquisitions": ("cash-flow-statement", "acquisitionsNet"),
    "change_in_working_capital": ("cash-flow-statement", "changeInWorkingCapital"),
    "income_taxes_paid": ("cash-flow-statement", "incomeTaxesPaid"),
    "interest_paid": ("cash-flow-statement", "interestPaid"),
    "deferred_income_tax": ("cash-flow-statement", "deferredIncomeTax"),

    # ── market / valuation ───────────────────────────────────────────────
    "market_capitalization": ("key-metrics", "marketCap"),
    "enterprise_value": ("key-metrics", "enterpriseValue"),
    "price": ("quote", "price"),
    "beta": ("profile", "beta"),
    "day_high": ("quote", "dayHigh"),
    "day_low": ("quote", "dayLow"),
    "average_volume": ("quote", "averageVolume"),

    # ── FMP-published derived metrics (use FMP's number rather than recompute) ──
    # Margins (note: FMP stores as fractions, e.g. 0.4621; verifier handles
    # scale-normalization so it lands against stated 46.21).
    "gross_margin": ("ratios", "grossProfitMargin"),
    "operating_margin": ("ratios", "operatingProfitMargin"),
    "net_margin": ("ratios", "netProfitMargin"),
    "ebit_margin": ("ratios", "ebitMargin"),
    "ebitda_margin": ("ratios", "ebitdaMargin"),
    "bottom_line_margin": ("ratios", "bottomLineProfitMargin"),
    # Valuation multiples
    "pe_ratio": ("ratios", "priceEarningsRatio"),
    "ps_ratio": ("ratios", "priceToSalesRatio"),
    "pb_ratio": ("ratios", "priceToBookRatio"),
    "ev_ebitda": ("key-metrics", "enterpriseValueOverEBITDA"),
    "ev_sales": ("ratios", "evToSales"),
    "ev_fcf": ("ratios", "evToFreeCashFlow"),
    "ev_operating_cash_flow": ("ratios", "evToOperatingCashFlow"),
    "forward_peg": ("ratios", "forwardPriceToEarningsGrowthRatio"),
    # Yields
    "dividend_yield": ("ratios", "dividendYield"),
    "fcf_yield": ("ratios", "freeCashFlowYield"),
    "earnings_yield": ("ratios", "earningsYield"),
    # Liquidity
    "current_ratio": ("ratios", "currentRatio"),
    "cash_ratio": ("ratios", "cashRatio"),
    # Leverage / coverage
    "debt_to_equity": ("ratios", "debtToEquityRatio"),
    "debt_to_assets": ("ratios", "debtToAssetsRatio"),
    "debt_to_capital": ("ratios", "debtToCapitalRatio"),
    "debt_to_market_cap": ("ratios", "debtToMarketCap"),
    "interest_coverage": ("ratios", "interestCoverageRatio"),
    "financial_leverage": ("ratios", "financialLeverageRatio"),
    "debt_service_coverage": ("ratios", "debtServiceCoverageRatio"),
    "capex_coverage": ("ratios", "capitalExpenditureCoverageRatio"),
    # Efficiency / turnover
    "asset_turnover": ("ratios", "assetTurnover"),
    "fixed_asset_turnover": ("ratios", "fixedAssetTurnover"),
    "days_sales_outstanding": ("ratios", "daysOfSalesOutstanding"),
    "days_inventory_outstanding": ("ratios", "daysOfInventoryOutstanding"),
    "days_payables_outstanding": ("ratios", "daysOfPayablesOutstanding"),
    "cash_conversion_cycle": ("ratios", "cashConversionCycle"),
    # Tax / payouts
    "effective_tax_rate": ("ratios", "effectiveTaxRate"),
    "dividend_payout_ratio": ("ratios", "dividendPayoutRatio"),
    "capex_to_revenue": ("ratios", "capexToRevenue"),
    "capex_to_depreciation": ("ratios", "capexToDepreciation"),
    "capex_to_ocf": ("ratios", "capexToOperatingCashFlow"),
    # Per-share metrics
    "book_value_per_share": ("ratios", "bookValuePerShare"),
    "cash_per_share": ("ratios", "cashPerShare"),
    "fcf_per_share": ("ratios", "freeCashFlowPerShare"),
    "capex_per_share": ("ratios", "capexPerShare"),
    "interest_debt_per_share": ("ratios", "interestDebtPerShare"),
    "dividend_per_share": ("ratios", "dividendPerShare"),
    # Quality / income decomposition
    "income_quality": ("ratios", "incomeQuality"),
    "interest_burden": ("ratios", "interestBurden"),
    "ebt_per_ebit": ("ratios", "ebtPerEbit"),
    # Graham screens
    "graham_number": ("ratios", "grahamNumber"),
    "graham_net_net": ("ratios", "grahamNetNet"),

    # ── growth metrics (financial-growth endpoint) ───────────────────────
    "revenue_growth": ("financial-growth", "revenueGrowth"),
    "gross_profit_growth": ("financial-growth", "grossProfitGrowth"),
    "ebit_growth": ("financial-growth", "ebitgrowth"),
    "ebitda_growth": ("financial-growth", "ebitdaGrowth"),
    "net_income_growth": ("financial-growth", "bottomLineNetIncomeGrowth"),
    "eps_growth": ("financial-growth", "epsgrowth"),
    "diluted_eps_growth": ("financial-growth", "epsdilutedGrowth"),
    "fcf_growth": ("financial-growth", "freeCashFlowGrowth"),
    "asset_growth": ("financial-growth", "assetGrowth"),
    "debt_growth": ("financial-growth", "debtGrowth"),
    "dividends_per_share_growth": ("financial-growth", "dividendsPerShareGrowth"),
    "book_value_per_share_growth": ("financial-growth", "bookValueperShareGrowth"),
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
        resolver: object = None,   # optional LLMLabelResolver (duck-typed: has .resolve())
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._rate_limit_rps = rate_limit_rps
        self._max_retries = max_retries
        self._fetch = fetch or self._default_fetch
        self._resolver = resolver

    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]:
        spec = LABEL_MAP.get(canonical_label)
        if spec is None and self._resolver is not None:
            # LLM fallback: ask the resolver for an (endpoint, field) mapping
            spec = self._resolver.resolve(canonical_label)
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
