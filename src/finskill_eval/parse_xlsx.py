"""xlsx artifact -> Ledger (M2.4).

Walks the sheet, forward-filling label/period/unit columns so merged cells and
sparse layouts still pair each value with its nearest descriptive label.
Normalizes values, applies unit-based scaling to canonical base units, and
classifies direct vs. derived. Derived cells are wired to their input cells via
the metric-definition registry so recompute() can run later.
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook

from finskill_eval.ledger import Cell, Ledger
from finskill_eval.normalize import (
    normalize_label,
    normalize_number,
    normalize_period,
    period_key,
)
from finskill_eval.recompute import METRIC_DEFS

# Unit string -> multiplier into canonical base units (absolute $, share count).
# Percent and multiples are already dimensionless.
UNIT_SCALE: dict[str, float] = {
    "$mm": 1_000_000.0,
    "$m": 1_000_000.0,
    "mm": 1_000_000.0,
    "$bn": 1_000_000_000.0,
    "thousands": 1_000.0,
    "$k": 1_000.0,
    "%": 1.0,
    "x": 1.0,
    "": 1.0,
}

# Editable keyword fallback for classifying derived cells when a metric is not
# (yet) in METRIC_DEFS. METRIC_DEFS membership is authoritative.
_DERIVED_KEYWORDS = re.compile(r"margin|yield|growth|ratio|multiple|ev_ebitda|pe_")
_DERIVED_UNITS = {"x"}


def _classify_kind(canonical_label: str, unit: str, is_numeric: bool) -> str:
    if not is_numeric:
        return "direct"
    if canonical_label in METRIC_DEFS:
        return "derived"
    if _DERIVED_KEYWORDS.search(canonical_label) or unit in _DERIVED_UNITS:
        return "derived"
    return "direct"


def parse(path: str | Path, *, skill: str, ticker: str) -> Ledger:
    wb = load_workbook(Path(path), data_only=True)
    ws = wb.active

    label_fill = period_fill = unit_fill = ""
    raw_cells: list[dict] = []
    for row in ws.iter_rows(values_only=True):
        # pad to 4 columns: Metric | Period | Value | Unit
        cols = list(row) + [None] * (4 - len(row))
        metric, period_raw, value_raw, unit_raw = cols[:4]

        # skip blank/header rows BEFORE forward-fill, so header tokens
        # ("Period", "Unit") never pollute the carried-down values
        if value_raw is None or str(value_raw).strip() == "":
            continue
        if str(value_raw).strip().lower() == "value":  # header row
            continue

        # forward-fill descriptive columns (merged-cell robustness)
        if metric not in (None, ""):
            label_fill = str(metric)
        if period_raw not in (None, ""):
            period_fill = str(period_raw)
        if unit_raw not in (None, ""):
            unit_fill = str(unit_raw)

        raw_cells.append(
            {
                "label": label_fill,
                "period_raw": period_fill,
                "value_raw": value_raw,
                "unit": unit_fill,
            }
        )

    cells: list[Cell] = []
    by_label_period: dict[tuple[str, str | None], str] = {}
    for rc in raw_cells:
        canonical = normalize_label(rc["label"])
        period = normalize_period(rc["period_raw"])
        pkey = period_key(period)
        num = normalize_number(rc["value_raw"])
        unit = rc["unit"]

        if num is None:
            value: float | str = str(rc["value_raw"]).strip()  # non-numeric (exact)
            is_numeric = False
        else:
            value = num * UNIT_SCALE.get(unit, 1.0)
            is_numeric = True

        kind = _classify_kind(canonical, unit, is_numeric)
        cell_id = f"{canonical}__{pkey}" if pkey else canonical
        cells.append(
            Cell(
                cell_id=cell_id,
                label=rc["label"],
                canonical_label=canonical,
                period=period,
                raw_value=str(rc["value_raw"]),
                value=value,
                unit=unit,
                kind=kind,
            )
        )
        by_label_period[(canonical, pkey)] = cell_id

    # wire derived cells to their input cells (same period) via METRIC_DEFS
    wired: list[Cell] = []
    for c in cells:
        if c.kind == "derived" and c.canonical_label in METRIC_DEFS:
            formula, input_labels = METRIC_DEFS[c.canonical_label]
            pkey2 = c.cell_id.split("__", 1)[1] if "__" in c.cell_id else None
            input_ids = tuple(
                by_label_period[(lbl, pkey2)]
                for lbl in input_labels
                if (lbl, pkey2) in by_label_period
            )
            wired.append(c.model_copy(update={"formula": formula, "inputs": input_ids}))
        else:
            wired.append(c)

    return Ledger(skill=skill, ticker=ticker, cells=wired)
