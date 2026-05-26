"""Deterministically (re)generate the three known-answer xlsx fixtures.

Run: python fixtures/_build_fixtures.py
The expected verifier verdict for every cell lives in expected_ledgers.json,
authored independently of this generator (input vs. expected-output are
separate artifacts, so there is no circularity).

Sheet layout (intentionally simple but exercises the parser): one row per
cell, columns A..D = Metric | Period | Value (as displayed) | Unit. The parser
must pair the value with its nearest descriptive label, infer scale from the
unit, and classify direct vs. derived itself (no 'kind' column to cheat from).
"""

from pathlib import Path

from openpyxl import Workbook

FIX = Path(__file__).resolve().parent

# (metric, period, value-as-displayed, unit)
TEARSHEET = [
    ("Metric", "Period", "Value", "Unit"),
    ("Revenue", "FY2024", "391,035", "$mm"),
    ("Net income", "FY2024", "93,736", "$mm"),
    ("Gross profit", "FY2024", "180,683", "$mm"),
    ("Operating income", "FY2024", "123,216", "$mm"),
    ("Gross margin", "FY2024", "46.2%", "%"),       # derived, correct
    ("Operating margin", "FY2024", "40.0%", "%"),   # derived, DELIBERATE ERROR
    ("Shares outstanding", "FY2024", "15,408,000", "thousands"),  # unit-scaled
    ("Cash & equivalents", "FY2024", "31,000", "$mm"),            # WARN band
]

COMPS = [
    ("Metric", "Period", "Value", "Unit"),
    ("Ticker", "", "AAPL", ""),                     # exact (non-numeric)
    ("Enterprise value", "FY2024", "3,000,000", "$mm"),
    ("EBITDA", "FY2024", "133,333", "$mm"),
    ("EV/EBITDA", "FY2024", "22.5", "x"),           # derived multiple
]

CAPITAL_ALLOCATION = [
    ("Metric", "Period", "Value", "Unit"),
    ("Dividends paid", "FY2024", "15,234", "$mm"),
    ("Share repurchases", "FY2024", "94,949", "$mm"),
    ("Market capitalization", "FY2024", "3,000,000", "$mm"),
    ("Shareholder yield", "FY2024", "3.67%", "%"),  # derived
]


def _write(rows, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    print(f"wrote {path.relative_to(FIX.parent)}")


def main() -> None:
    _write(TEARSHEET, FIX / "sample_tearsheet.xlsx")
    _write(COMPS, FIX / "sample_comps.xlsx")
    _write(CAPITAL_ALLOCATION, FIX / "sample_capital_allocation.xlsx")


if __name__ == "__main__":
    main()
