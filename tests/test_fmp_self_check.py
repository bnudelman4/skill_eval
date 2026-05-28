"""FMP-self-check unit tests. Inject a fake FMP source — no network."""

from finskill_eval.checks.fmp_self_check import (
    render_markdown,
    run_fmp_self_check,
)
from finskill_eval.groundtruth.base import Value
from finskill_eval.ledger import Cell, Ledger


class FakeFMP:
    def __init__(self, by_label: dict[str, float]):
        self._by = by_label

    def get(self, ticker, period, canonical_label):
        v = self._by.get(canonical_label)
        if v is None:
            return None
        return Value(value=v, unit="USD", vintage="2024-09-28",
                     source_id="fmp", period=period, canonical_label=canonical_label)


def _direct_cell(label, value):
    return Cell(cell_id=f"{label}__FY2024", label=label, canonical_label=label,
                period=None, raw_value=str(value), value=value,
                unit="$mm", kind="direct", cell_type="direct_lookup")


def _derived_cell(label, value, formula, inputs):
    return Cell(cell_id=f"{label}__FY2024", label=label, canonical_label=label,
                period=None, raw_value=str(value), value=value,
                unit="%", kind="derived", cell_type="bivariate",
                formula=formula, inputs=inputs)


def test_direct_cell_pass_when_skill_matches_fmp():
    led = Ledger(skill="tearsheet", ticker="AAPL",
                 cells=[_direct_cell("revenue", 391_035_000_000.0)])
    fmp = FakeFMP({"revenue": 391_035_000_000.0})
    report = run_fmp_self_check(led, fmp)
    assert report.verdicts[0].status == "PASS"
    assert report.verdicts[0].rel_err == 0.0


def test_direct_cell_fail_when_skill_transcribes_wrong():
    # 392_000 vs 391_035 -> rel_err ~ 0.25% -> outside the 0.1% tight band
    led = Ledger(skill="tearsheet", ticker="AAPL",
                 cells=[_direct_cell("revenue", 392_000_000_000.0)])
    fmp = FakeFMP({"revenue": 391_035_000_000.0})
    report = run_fmp_self_check(led, fmp)
    assert report.verdicts[0].status == "FAIL"
    assert report.verdicts[0].rel_err > 0.0


def test_derived_cell_pass_when_skill_recomputes_correctly():
    cells = [
        _direct_cell("revenue", 391_035_000_000.0),
        _direct_cell("gross_profit", 180_683_000_000.0),
        _derived_cell("gross_margin", 46.2063,
                      "gross_margin", ("gross_profit__FY2024", "revenue__FY2024")),
    ]
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=cells)
    fmp = FakeFMP({
        "revenue": 391_035_000_000.0,
        "gross_profit": 180_683_000_000.0,
    })
    report = run_fmp_self_check(led, fmp)
    statuses = {v.canonical_label: v.status for v in report.verdicts}
    assert statuses["gross_margin"] == "PASS"


def test_derived_cell_fail_when_skill_used_wrong_inputs():
    """Skill stated a gross_margin that doesn't match what FMP's own inputs give."""
    cells = [
        _direct_cell("revenue", 391_035_000_000.0),
        _direct_cell("gross_profit", 180_683_000_000.0),
        _derived_cell("gross_margin", 50.0,   # arbitrarily wrong
                      "gross_margin", ("gross_profit__FY2024", "revenue__FY2024")),
    ]
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=cells)
    fmp = FakeFMP({
        "revenue": 391_035_000_000.0,
        "gross_profit": 180_683_000_000.0,
    })
    report = run_fmp_self_check(led, fmp)
    statuses = {v.canonical_label: v.status for v in report.verdicts}
    assert statuses["gross_margin"] == "FAIL"


def test_derived_cell_skip_when_fmp_missing_input():
    cells = [
        _derived_cell("gross_margin", 46.2,
                      "gross_margin", ("gross_profit__FY2024", "revenue__FY2024")),
    ]
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=cells)
    fmp = FakeFMP({"revenue": 391_035_000_000.0})   # no gross_profit
    report = run_fmp_self_check(led, fmp)
    assert report.verdicts[0].status == "SKIP"
    assert "missing" in report.verdicts[0].note


def test_pass_rate_excludes_skip():
    cells = [
        _direct_cell("revenue", 391_035_000_000.0),         # PASS
        _direct_cell("nonexistent_metric", 1.0),            # SKIP (no FMP map)
    ]
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=cells)
    fmp = FakeFMP({"revenue": 391_035_000_000.0})
    report = run_fmp_self_check(led, fmp)
    assert report.pass_rate == 1.0   # 1 PASS / (1 PASS + 0 FAIL)


def test_markdown_renders_without_error():
    led = Ledger(skill="tearsheet", ticker="AAPL",
                 cells=[_direct_cell("revenue", 391_035_000_000.0)])
    fmp = FakeFMP({"revenue": 391_035_000_000.0})
    md = render_markdown(run_fmp_self_check(led, fmp))
    assert "FMP-self-check" in md
    assert "PASS" in md
