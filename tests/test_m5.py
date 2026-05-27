"""M5: grid build, sample scoring, metrics aggregation, scorecard, parallelism.

All execution is injected/mocked — no live agent, no live network.
"""

import json
from pathlib import Path

import pytest

from finskill_eval.metrics import aggregate
from finskill_eval.report import to_html, to_json, to_markdown
from finskill_eval.runner.grid import GridSample, SampleRecord, build_grid, score_sample
from finskill_eval.runner.invoke_skill import SkillRun

FIX = Path("fixtures")
CONTRACT = json.loads((FIX / "expected_ledgers.json").read_text())


class MockGT:
    def __init__(self, contract):
        self._d = {}
        for skill, payload in contract.items():
            if skill.startswith("_"):
                continue
            for c in payload["cells"]:
                self._d[(payload["ticker"], c["period"], c["canonical_label"])] = c["truth"]

    def get(self, ticker, period, label):
        return self._d.get((ticker, period, label))


# --------------------------------------------------------------------------- #
# grid
# --------------------------------------------------------------------------- #
def test_build_grid_cardinality():
    grid = build_grid(
        skills=["tearsheet", "comps"],
        tickers=["AAPL", "MSFT"],
        periods=["FY2024", "FY2023"],
        data_sources=["fmp"],
    )
    assert len(grid) == 2 * 2 * 2 * 1
    assert GridSample("tearsheet", "AAPL", "FY2024", "fmp") in grid


def test_score_sample_happy_path(tmp_path):
    sample = GridSample("tearsheet", "AAPL", "FY2024", "fmp")

    def fake_invoke(skill, ticker, period, data_source, *, workdir, **kw):
        return SkillRun(
            skill=skill, ticker=ticker, period=period, data_source=data_source,
            workdir=str(workdir), artifact_path=str(FIX / "sample_tearsheet.xlsx"),
            cost_usd=0.42, latency_s=12.3, num_turns=6, exit_ok=True,
            raw_log_path=str(tmp_path / "run.log"),
            activation_observed=True, skill_selected="tearsheet",
        )

    from finskill_eval.parse_xlsx import parse as parse_xlsx
    rec = score_sample(
        sample, invoke_fn=fake_invoke, ground_truth=MockGT(CONTRACT),
        workdir_root=tmp_path,
        # deterministic parser on the known fixture (avoid a live LLM extract)
        parse_fn=lambda path, skill, ticker: parse_xlsx(path, skill=skill, ticker=ticker),
    )
    assert rec.exit_ok is True
    assert rec.activation_observed is True
    assert rec.skill_selected == "tearsheet"
    assert rec.cost_usd == pytest.approx(0.42)
    assert len(rec.verdicts) == 8
    statuses = {v["status"] for v in rec.verdicts}
    assert {"PASS", "WARN", "FAIL"} <= statuses


def test_score_sample_failed_run(tmp_path):
    sample = GridSample("comps", "AAPL", "FY2024", "fmp")

    def fake_invoke(skill, ticker, period, data_source, *, workdir, **kw):
        return SkillRun(
            skill=skill, ticker=ticker, period=period, data_source=data_source,
            workdir=str(workdir), artifact_path=None, cost_usd=0.0, latency_s=1.0,
            num_turns=0, exit_ok=False, raw_log_path=str(tmp_path / "x.log"),
            activation_observed=False, skill_selected=None,
        )

    rec = score_sample(sample, invoke_fn=fake_invoke, ground_truth=MockGT(CONTRACT),
                       workdir_root=tmp_path)
    assert rec.exit_ok is False
    assert rec.verdicts == []
    assert rec.error


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def _rec(skill, selected, activation, verdicts, cost=1.0, lat=10.0):
    return SampleRecord(
        skill=skill, ticker="AAPL", period="FY2024", data_source="fmp",
        activation_observed=activation, skill_selected=selected, exit_ok=True,
        cost_usd=cost, latency_s=lat, num_turns=5, verdicts=verdicts,
    )


def _v(status, band, cell_type="direct_lookup"):
    return {"canonical_label": "x", "period": "FY2024", "cell_type": cell_type,
            "kind": "direct", "status": status, "band": band, "rel_err": 0.0}


def test_aggregate_rates_and_counts():
    records = [
        _rec("tearsheet", "tearsheet", True,
             [_v("PASS", "exact"), _v("PASS", "tight"), _v("WARN", "materiality"),
              _v("FAIL", "disagreement"), _v("FLAG", "disagreement")]),
        _rec("comps", "comps", True, [_v("PASS", "exact")], cost=3.0, lat=200.0),
        _rec("capital_allocation", "tearsheet", False, [_v("PASS", "exact")]),
    ]
    m = aggregate(records, activation_min=0.95, selection_min=0.98,
                  accuracy_min=0.90, accuracy_eval_band="xvendor_liberal")
    assert m.n_samples == 3
    assert m.activation_rate == pytest.approx(2 / 3)
    # selection: among 3 with a selected skill, 2 match intended
    assert m.selection_accuracy == pytest.approx(2 / 3)
    assert m.counts["PASS"] == 4
    assert m.counts["WARN"] == 1
    assert m.counts["FAIL"] == 1
    assert m.counts["FLAG"] == 1
    assert m.cost_total == pytest.approx(5.0)
    # pass-rate at xvendor_liberal: PASS cells / gradeable (exclude FLAG) = 4/6
    assert m.accuracy_pass_rate == pytest.approx(4 / 6)
    assert m.targets_eval["activation_pass"] is False
    assert m.targets_eval["accuracy_pass"] is False


def test_aggregate_cell_type_breakdown():
    records = [_rec("tearsheet", "tearsheet", True,
                    [_v("PASS", "exact", "direct_lookup"),
                     _v("FAIL", "disagreement", "bivariate")])]
    m = aggregate(records, activation_min=0.95, selection_min=0.98,
                  accuracy_min=0.90, accuracy_eval_band="xvendor_liberal")
    assert set(m.by_cell_type) == {"direct_lookup", "bivariate"}
    assert m.by_cell_type["direct_lookup"]["pass_rate"] == pytest.approx(1.0)
    assert m.by_cell_type["bivariate"]["pass_rate"] == pytest.approx(0.0)


def test_latency_p95():
    records = [_rec("s", "s", True, [_v("PASS", "exact")], lat=float(i)) for i in range(1, 101)]
    m = aggregate(records, activation_min=0, selection_min=0, accuracy_min=0,
                  accuracy_eval_band="xvendor_liberal")
    assert 90 <= m.latency_p95 <= 100


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def test_report_renders_all_formats():
    records = [_rec("tearsheet", "tearsheet", True,
                    [_v("PASS", "exact"), _v("FLAG", "disagreement")])]
    m = aggregate(records, activation_min=0.95, selection_min=0.98,
                  accuracy_min=0.90, accuracy_eval_band="xvendor_liberal")
    j = json.loads(to_json(m))
    assert j["activation_rate"] == pytest.approx(1.0)
    md = to_markdown(m)
    assert "Activation" in md and ("PASS" in md or "miss" in md.lower())
    assert "<html" in to_html(m).lower()


# --------------------------------------------------------------------------- #
# parallel
# --------------------------------------------------------------------------- #
def test_run_grid_resumable(tmp_path):
    from finskill_eval.runner.parallel import run_grid

    samples = build_grid(skills=["tearsheet"], tickers=["AAPL", "MSFT"],
                         periods=["FY2024"], data_sources=["fmp"])
    calls = {"n": 0}

    def score_fn(sample):
        calls["n"] += 1
        return _rec(sample.skill, sample.skill, True, [_v("PASS", "exact")])

    r1 = run_grid(samples, score_fn, concurrency=2, global_rps=100.0,
                  resume=True, results_dir=tmp_path)
    assert len(r1) == 2
    assert calls["n"] == 2

    # second run: all cached -> score_fn not called again
    r2 = run_grid(samples, score_fn, concurrency=2, global_rps=100.0,
                  resume=True, results_dir=tmp_path)
    assert len(r2) == 2
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# one-command baseline (offline dry-run) + Inspect adapter
# --------------------------------------------------------------------------- #
def test_dry_run_baseline_produces_scorecard(tmp_path):
    from finskill_eval.runner.run_baseline import run_baseline

    metrics, paths = run_baseline(dry_run=True, results_dir=tmp_path)
    # 3 skills x 1 ticker x 1 period x 1 source
    assert metrics.n_samples == 3
    assert metrics.activation_rate == pytest.approx(1.0)
    sc = json.loads(Path(paths["json"]).read_text())
    assert sc["n_samples"] == 3
    assert Path(paths["markdown"]).exists() and Path(paths["html"]).exists()
    # tearsheet contributes the one deliberate FAIL
    assert metrics.counts["FAIL"] >= 1


def test_inspect_task_builds():
    inspect_ai = pytest.importorskip("inspect_ai")  # noqa: F841
    from finskill_eval.runner.harness import build_task

    samples = build_grid(skills=["tearsheet"], tickers=["AAPL"],
                         periods=["FY2024"], data_sources=["fmp"])

    def fake_invoke(skill, ticker, period, data_source, *, workdir, **kw):
        return SkillRun(
            skill=skill, ticker=ticker, period=period, data_source=data_source,
            workdir=str(workdir), artifact_path=None, cost_usd=0.0, latency_s=0.0,
            num_turns=0, exit_ok=False, raw_log_path="x",
            activation_observed=False, skill_selected=None,
        )

    task = build_task(samples, invoke_fn=fake_invoke, ground_truth=MockGT(CONTRACT),
                      workdir_root=Path("."))
    assert task is not None
