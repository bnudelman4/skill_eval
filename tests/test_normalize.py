"""M2.1: number / label / period normalization."""

import pytest

from finskill_eval.normalize import (
    Period,
    normalize_label,
    normalize_number,
    normalize_period,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("391,035", 391035.0),
        ("1,234.5", 1234.5),
        ("$1,234.5", 1234.5),
        ("(1,234)", -1234.0),       # parentheses = negative
        ("(1,234.50)", -1234.5),
        ("12.3%", 12.3),            # percent sign stripped, value kept
        ("1.2bn", 1.2e9),           # suffix scaling
        ("3.4m", 3.4e6),
        ("5k", 5_000.0),
        ("  42 ", 42.0),
        ("-17", -17.0),
        ("0", 0.0),
    ],
)
def test_normalize_number_values(raw, expected):
    assert normalize_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "  ", "NA", "N/A", "-", "—", None, "n/a"])
def test_normalize_number_blanks_to_none(raw):
    assert normalize_number(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Revenue", "revenue"),
        ("Total Revenue", "revenue"),     # synonym -> revenue
        ("Net revenue", "revenue"),
        ("Net sales", "revenue"),
        ("Gross profit", "gross_profit"),
        ("Gross margin", "gross_margin"),
        ("Cash & equivalents", "cash_and_equivalents"),  # & -> and
        ("EV/EBITDA", "ev_ebitda"),
        ("Shareholder yield", "shareholder_yield"),
        ("Market capitalization", "market_capitalization"),
        ("  Operating   Income  ", "operating_income"),  # whitespace collapse
    ],
)
def test_normalize_label(raw, expected):
    assert normalize_label(raw) == expected


def test_net_income_variants_stay_distinct():
    # definition drift is a real failure mode -> must NOT silently merge
    assert normalize_label("Net income") == "net_income"
    assert normalize_label("Net income to common") == "net_income_to_common"
    assert normalize_label("Net income") != normalize_label("Net income to common")


@pytest.mark.parametrize(
    "raw, kind, fy, fq",
    [
        ("FY2024", "annual", 2024, None),
        ("FY24", "annual", 2024, None),
        ("2024", "annual", 2024, None),
        ("Q4 2025", "quarterly", 2025, 4),
        ("Q1 2023", "quarterly", 2023, 1),
        ("2024-12-31", "annual", 2024, None),
    ],
)
def test_normalize_period(raw, kind, fy, fq):
    p = normalize_period(raw)
    assert p == Period(kind=kind, fiscal_year=fy, fiscal_quarter=fq)


@pytest.mark.parametrize("raw", ["", None, "  "])
def test_normalize_period_blank_to_none(raw):
    assert normalize_period(raw) is None
