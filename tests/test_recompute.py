"""M2.5: deterministic recompute of derived metrics.

Rule: recompute in Python; never accept the LLM's arithmetic for a derived cell.
"""

import math

import pytest

from finskill_eval.ledger import Cell, Ledger
from finskill_eval.normalize import Period
from finskill_eval.recompute import (
    FORMULAS,
    ev_ebitda,
    gross_margin,
    growth,
    operating_margin,
    pe_ratio,
    recompute,
    shareholder_yield,
)


def test_formula_hand_values():
    assert gross_margin(50.0, 200.0) == pytest.approx(25.0)
    assert operating_margin(30.0, 200.0) == pytest.approx(15.0)
    assert ev_ebitda(1000.0, 100.0) == pytest.approx(10.0)
    assert shareholder_yield(50.0, 50.0, 1000.0) == pytest.approx(10.0)
    assert growth(110.0, 100.0) == pytest.approx(10.0)
    assert pe_ratio(100.0, 5.0) == pytest.approx(20.0)


def test_registry_lists_named_formulas():
    assert {"gross_margin", "operating_margin", "ev_ebitda", "shareholder_yield"} <= set(
        FORMULAS
    )


def _direct(cell_id, value):
    return Cell(
        cell_id=cell_id,
        label=cell_id,
        canonical_label=cell_id,
        period=Period("annual", 2024, None),
        raw_value=str(value),
        value=value,
        unit="$mm",
        kind="direct",
    )


def test_recompute_resolves_inputs_from_ledger():
    gp = _direct("gp", 180683000000.0)
    rev = _direct("rev", 391035000000.0)
    margin = Cell(
        cell_id="gm",
        label="Gross margin",
        canonical_label="gross_margin",
        period=Period("annual", 2024, None),
        raw_value="46.2%",
        value=46.2,
        unit="%",
        kind="derived",
        formula="gross_margin",
        inputs=("gp", "rev"),
    )
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=[gp, rev, margin])
    out = recompute(led)
    assert set(out) == {"gm"}
    assert math.isclose(out["gm"], 46.206349815233935, rel_tol=1e-9)
