"""P1: matrix + multi-sheet xlsx parsing (metrics as rows, periods as columns)."""

from openpyxl import Workbook

from finskill_eval.parse_xlsx import parse
from finskill_eval.normalize import normalize_period, period_key


def _matrix_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Income Statement"
    ws.append(["Apple Inc. (AAPL)"])
    ws.append(["INCOME STATEMENT ($ millions)"])
    ws.append(["Metric ($ millions)", "Dec'22", "Mar'23", "Jun'23", "Sep'23"])
    ws.append(["Revenue", 117154, 94836, 81797, 89498])
    ws.append(["Net Income", 29998, 24160, 19881, 22956])
    ws2 = wb.create_sheet("Reinvestment")
    ws2.append(["Apple Inc. (AAPL)"])
    ws2.append(["REINVESTMENT ($ millions)"])
    ws2.append(["Metric ($ millions)", "Dec'22", "Mar'23"])
    ws2.append(["Revenue", 117154, 94836])           # duplicate metric across sheets
    ws2.append(["R&D as % Revenue", 0.0658, 0.0786])  # ratio: must NOT be $-scaled
    wb.save(path)


def test_month_year_period_parsing():
    p = normalize_period("Dec'22")
    assert p.kind == "quarterly" and p.fiscal_year == 2022 and p.fiscal_quarter == 4
    assert normalize_period("Sep 23").fiscal_quarter == 3
    assert normalize_period("FY2023 Q1").fiscal_quarter == 1


def test_matrix_parse_extracts_metric_x_period(tmp_path):
    f = tmp_path / "cap.xlsx"
    _matrix_workbook(f)
    led = parse(f, skill="capital_allocation", ticker="AAPL")
    by = {(c.canonical_label, period_key(c.period)): c for c in led.cells}

    rev_q1 = by[("revenue", period_key(normalize_period("Dec'22")))]
    assert rev_q1.value == 117154 * 1_000_000        # $mm scaling applied
    rev_q3 = by[("revenue", period_key(normalize_period("Jun'23")))]
    assert rev_q3.value == 81797 * 1_000_000


def test_matrix_ratio_row_not_dollar_scaled(tmp_path):
    f = tmp_path / "cap.xlsx"
    _matrix_workbook(f)
    led = parse(f, skill="capital_allocation", ticker="AAPL")
    rnd = [c for c in led.cells if "r_and_d_as" in c.canonical_label or "r_d_as" in c.canonical_label
           or c.canonical_label.startswith("r")]
    pct = [c for c in led.cells if c.unit == "" and isinstance(c.value, float) and c.value < 1]
    assert any(c.value == 0.0658 for c in pct)        # left as ratio, not *1e6


def test_duplicate_metric_across_sheets_deduped(tmp_path):
    f = tmp_path / "cap.xlsx"
    _matrix_workbook(f)
    led = parse(f, skill="capital_allocation", ticker="AAPL")
    ids = [c.cell_id for c in led.cells]
    assert len(ids) == len(set(ids))                  # no duplicate cell_ids
