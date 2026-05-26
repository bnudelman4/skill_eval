"""M2.6: end-to-end verify on each fixture with a MOCKED ground-truth source.

The verifier must assign exactly the bands/statuses documented in the M1
contract, including the deliberately-wrong cell (FAIL) and the WARN cell.
No agent, no live network.
"""

import json
from pathlib import Path

import pytest

from finskill_eval.parse_xlsx import parse
from finskill_eval.verify import verify

FIX = Path("fixtures")
CONTRACT = json.loads((FIX / "expected_ledgers.json").read_text())
SKILLS = [k for k in CONTRACT if not k.startswith("_")]


class MockGroundTruth:
    """Serves the contract's `truth` values keyed by (ticker, period, label)."""

    def __init__(self, contract: dict):
        self._d: dict[tuple[str, str | None, str], object] = {}
        for skill, payload in contract.items():
            if skill.startswith("_"):
                continue
            ticker = payload["ticker"]
            for c in payload["cells"]:
                self._d[(ticker, c["period"], c["canonical_label"])] = c["truth"]

    def get(self, ticker, period, canonical_label):
        return self._d.get((ticker, period, canonical_label))


@pytest.fixture(scope="module")
def gt():
    return MockGroundTruth(CONTRACT)


@pytest.fixture(params=SKILLS)
def skill(request):
    return request.param


def test_each_cell_matches_contract_band_and_status(skill, gt):
    led = parse(FIX / f"sample_{skill}.xlsx", skill=skill, ticker="AAPL")
    report = verify(led, gt)
    expected = {c["canonical_label"]: c for c in CONTRACT[skill]["cells"]}
    by_label = {v.canonical_label: v for v in report.verdicts}
    assert set(by_label) == set(expected)
    for label, exp in expected.items():
        v = by_label[label]
        assert v.status == exp["expected_status"], f"{skill}.{label} status"
        assert v.band == exp["expected_band"], f"{skill}.{label} band"


def test_deliberate_error_is_failed(gt):
    led = parse(FIX / "sample_tearsheet.xlsx", skill="tearsheet", ticker="AAPL")
    report = verify(led, gt)
    v = next(x for x in report.verdicts if x.canonical_label == "operating_margin")
    assert v.status == "FAIL"


def test_warn_cell(gt):
    led = parse(FIX / "sample_tearsheet.xlsx", skill="tearsheet", ticker="AAPL")
    report = verify(led, gt)
    v = next(x for x in report.verdicts if x.canonical_label == "cash_and_equivalents")
    assert v.status == "WARN"


def test_rollup_counts(gt):
    led = parse(FIX / "sample_tearsheet.xlsx", skill="tearsheet", ticker="AAPL")
    report = verify(led, gt)
    # tearsheet: 6 PASS, 1 WARN, 1 FAIL
    assert report.rollup.counts["PASS"] == 6
    assert report.rollup.counts["WARN"] == 1
    assert report.rollup.counts["FAIL"] == 1
    assert len(report.rollup.failures) == 1
