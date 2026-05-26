# FMP Data Access Reference

The FMP analogue of Daloopa's `data-access.md`. Skills converted to the FMP
data layer read **this** file instead. Workflow, analysis, and report structure
are unchanged — only the data source is swapped. Read `../design-system.md` for
formatting conventions (unchanged).

Base URL: `https://financialmodelingprep.com/stable/`
Auth: append `&apikey=$FMP_API_KEY` (from the environment; never hardcode).

---

## Section 1: FMP Fetch Tools

The converted skills reference these tokens. Each maps to an FMP endpoint. Fetch
with `Bash` (curl) or the project's FMP client; results are JSON.

| Token (used in skill) | Purpose | FMP endpoint |
|---|---|---|
| `fmp_profile` | Find company, name, exchange, market cap, beta, shares out | `profile?symbol=TICKER` |
| `fmp_quote` | Current price + day range; historical close for multiples | `quote?symbol=TICKER`, `historical-price-eod/full?symbol=TICKER` |
| `fmp_statements` | Income / balance / cash-flow line items | `income-statement`, `balance-sheet-statement`, `cash-flow-statement` (`?symbol=TICKER&period=annual` or `quarter`) |
| `fmp_fields` | Which field supplies a metric (this Section 3 table) | — (reference only) |
| `fmp_filings_search` | Recent filing text / developments | SEC EDGAR full-text search + WebSearch fallback |

`fmp_profile` replaces `discover_companies`; `fmp_quote` replaces
`get_stock_prices`; `fmp_statements`+`fmp_fields` replace
`get_company_fundamentals`/`discover_company_series`; `fmp_filings_search`
replaces `search_documents`.

## Section 1.5: Period Determination

FMP statement rows carry `fiscalYear`, `period` (FY/Q1–Q4), `date`, and
`calendarYear`. To get the last N fiscal years, request
`period=annual&limit=N`; for quarters, `period=quarter&limit=N`. **Always select
the row by `fiscalYear`/`period` — never assume the current calendar date is the
latest filed period.** For multi-company comparison (comps), align on
`calendarYear` to normalize different fiscal year-ends; for single-company
(tearsheet, capital-allocation) use the company's fiscal labels.

## Section 1.7: Prices & Multiples

`fmp_quote` returns price, `marketCap`, `sharesOutstanding`. For quarter-end
prices (valuation multiples), pull `historical-price-eod/full` and take the
close on/just before the period-end date.

- P/E = close × diluted shares / net income (trailing 4Q) — or `ratios.priceToEarningsRatio`
- EV/EBITDA = (marketCap + totalDebt − cashAndShortTermInvestments) / EBITDA — or `key-metrics.enterpriseValueOverEBITDA`
- FMP also exposes precomputed `ratios?symbol=TICKER` and
  `key-metrics?symbol=TICKER`; prefer recomputing from raw statements when the
  skill needs an auditable figure, use precomputed only for cross-checks.

## Section 2: Field Map (metric → statement.field)

| Metric | Statement | FMP field |
|---|---|---|
| Revenue | income-statement | `revenue` |
| Gross Profit | income-statement | `grossProfit` |
| Operating Income | income-statement | `operatingIncome` |
| EBITDA | income-statement | `ebitda` |
| Net Income | income-statement | `netIncome` |
| Diluted EPS | income-statement | `epsDiluted` |
| Diluted Shares | income-statement | `weightedAverageShsOutDil` |
| D&A | cash-flow-statement | `depreciationAndAmortization` |
| Operating Cash Flow | cash-flow-statement | `operatingCashFlow` |
| CapEx | cash-flow-statement | `capitalExpenditure` (negative; use abs) |
| Free Cash Flow | cash-flow-statement | `freeCashFlow` |
| Dividends Paid | cash-flow-statement | `netDividendsPaid` (or `dividendsPaid`) |
| Share Repurchases | cash-flow-statement | `commonStockRepurchased` |
| Cash & Equivalents | balance-sheet-statement | `cashAndCashEquivalents` |
| Total Debt | balance-sheet-statement | `totalDebt` |
| Shares Outstanding | profile / balance-sheet | `sharesOutstanding` / `weightedAverageShsOut` |
| Market Cap | profile | `marketCap` |

Derived metrics (margins, growth, FCF, multiples) are **computed by the skill
from the fields above** — the eval recomputes them in Python and never trusts an
LLM's arithmetic. Mark computed cells "(calc.)" exactly as before.

## Section 3: Denomination Check

FMP self-discloses occasional thousands/millions scale errors. After pulling a
statement, sanity-check magnitudes against a sibling field (e.g. net margin =
netIncome/revenue should fall in a plausible band); if a value is ~1000× off,
flag it rather than trusting it.

## Section 4: Sourcing Convention (replaces Daloopa citations)

Daloopa's per-figure `daloopa.com/src/{id}` links have no FMP equivalent.
Instead, every financial figure cites its **endpoint + fiscal period**, e.g.
`income-statement AAPL FY2024 revenue`. Footer reads:
`Prepared by {FIRM_NAME} | Data sourced from Financial Modeling Prep (FMP)`.
Default `{FIRM_NAME}` unchanged. Never hallucinate a firm name.
