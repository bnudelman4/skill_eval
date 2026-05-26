"""M2.3: typed cell ledger datatypes."""

import pytest
from pydantic import ValidationError

from finskill_eval.ledger import Cell, Ledger
from finskill_eval.normalize import Period


def _cell(**kw):
    base = dict(
        cell_id="c1",
        label="Revenue",
        canonical_label="revenue",
        period=Period("annual", 2024, None),
        raw_value="391,035",
        value=391035000000.0,
        unit="$mm",
        kind="direct",
    )
    base.update(kw)
    return Cell(**base)


def test_cell_construction():
    c = _cell()
    assert c.kind == "direct"
    assert c.value == 391035000000.0


def test_cell_rejects_bad_kind():
    with pytest.raises(ValidationError):
        _cell(kind="sideways")


def test_cell_value_can_be_string_for_exact():
    c = _cell(value="AAPL", unit="", canonical_label="ticker", kind="direct")
    assert c.value == "AAPL"


def test_ledger_lookup_by_id():
    a = _cell(cell_id="a")
    b = _cell(cell_id="b", canonical_label="net_income", value=1.0)
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=[a, b])
    assert led.by_id("b").canonical_label == "net_income"
    assert led.by_id("missing") is None
