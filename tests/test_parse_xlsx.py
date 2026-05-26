"""M2.4: xlsx artifact -> Ledger, validated against the M1 contract."""

import json
from pathlib import Path

import pytest

from finskill_eval.parse_xlsx import parse

FIX = Path("fixtures")
CONTRACT = json.loads((FIX / "expected_ledgers.json").read_text())
SKILLS = [k for k in CONTRACT if not k.startswith("_")]


@pytest.fixture(params=SKILLS)
def skill(request):
    return request.param


def _contract_by_label(skill):
    return {c["canonical_label"]: c for c in CONTRACT[skill]["cells"]}


def test_parse_cell_count_and_labels(skill):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    expected = _contract_by_label(skill)
    assert {c.canonical_label for c in led.cells} == set(expected)


def test_parse_canonical_values_and_units(skill):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    expected = _contract_by_label(skill)
    for c in led.cells:
        exp = expected[c.canonical_label]
        if isinstance(exp["value"], str):
            assert c.value == exp["value"]
        else:
            assert c.value == pytest.approx(exp["value"], rel=1e-9)


def test_parse_kind_classification(skill):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    expected = _contract_by_label(skill)
    for c in led.cells:
        assert c.kind == expected[c.canonical_label]["kind"], c.canonical_label


def test_derived_cells_wired_to_inputs(skill):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    for c in led.cells:
        if c.kind == "derived":
            assert c.formula, f"{c.canonical_label} missing formula"
            assert c.inputs, f"{c.canonical_label} missing inputs"
            for input_id in c.inputs:
                assert led.by_id(input_id) is not None


def test_parse_assigns_faith_cell_type(skill):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    expected = _contract_by_label(skill)
    for c in led.cells:
        assert c.cell_type == expected[c.canonical_label]["cell_type"], c.canonical_label


def test_unit_scaling_thousands_to_canonical():
    led = parse(FIX / "sample_tearsheet.xlsx", skill="tearsheet", ticker="AAPL")
    shares = next(c for c in led.cells if c.canonical_label == "shares_outstanding")
    assert shares.value == pytest.approx(15408000000.0)
