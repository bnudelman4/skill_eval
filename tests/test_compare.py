"""M6: paired A/B comparison (baseline skill vs converted FMP skill)."""

import pytest

from finskill_eval.conversion.compare import compare_arms
from finskill_eval.runner.grid import SampleRecord


def _rec(skill, ticker, source, *, statuses, activation=True, selected=None):
    """Build a SampleRecord with verdicts of the given statuses at xvendor_liberal."""
    verdicts = [
        {"canonical_label": f"c{i}", "period": "FY2024", "cell_type": "direct_lookup",
         "kind": "direct", "status": s, "band": "tight" if s == "PASS" else
         ("materiality" if s == "WARN" else ("disagreement" if s == "FLAG" else "tight")),
         "rel_err": 0.0}
        for i, s in enumerate(statuses)
    ]
    return SampleRecord(
        skill=skill, ticker=ticker, period="FY2024", data_source=source,
        activation_observed=activation, skill_selected=selected or skill,
        exit_ok=True, cost_usd=1.0, latency_s=10.0, num_turns=5, verdicts=verdicts,
    )


def test_pairs_matched_by_skill_ticker_period():
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS", "PASS", "FAIL"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS", "PASS", "PASS"])]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert r.n_pairs == 1
    assert r.baseline_pass_rate == pytest.approx(2 / 3)
    assert r.candidate_pass_rate == pytest.approx(1.0)
    assert r.mean_delta == pytest.approx(1 / 3)


def test_unmatched_samples_dropped():
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS"]),
            _rec("comps", "MSFT", "daloopa", statuses=["PASS"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS"])]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert r.n_pairs == 1  # only AAPL/tearsheet matched


def test_ci_zero_width_for_constant_delta():
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS", "FAIL"]),
            _rec("comps", "MSFT", "daloopa", statuses=["PASS", "FAIL"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS", "PASS"]),
            _rec("comps", "MSFT", "fmp", statuses=["PASS", "PASS"])]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert r.mean_delta == pytest.approx(0.5)
    assert r.ci_low == pytest.approx(r.ci_high)  # identical per-pair deltas


def test_production_acceptable_flag():
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS"] * 9 + ["FAIL"])]
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS"] * 10)]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert r.candidate_pass_rate == pytest.approx(0.9)
    assert r.production_acceptable is True


def test_candidate_beats_baseline_raises_gold_flag():
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS", "FAIL", "FAIL", "FAIL"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS", "PASS", "PASS", "PASS"])]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert any("investigate the gold" in f.lower() for f in r.flags)


def test_per_skill_breakdown():
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS", "FAIL"]),
            _rec("comps", "AAPL", "daloopa", statuses=["PASS", "PASS"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS", "PASS"]),
            _rec("comps", "AAPL", "fmp", statuses=["PASS", "FAIL"])]
    r = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    assert set(r.by_skill) == {"tearsheet", "comps"}
    assert r.by_skill["tearsheet"]["delta"] == pytest.approx(0.5)
    assert r.by_skill["comps"]["delta"] == pytest.approx(-0.5)


def test_comparison_markdown_and_writer(tmp_path):
    from finskill_eval.conversion.compare import comparison_markdown, write_comparison
    base = [_rec("tearsheet", "AAPL", "daloopa", statuses=["PASS", "FAIL"])]
    cand = [_rec("tearsheet", "AAPL", "fmp", statuses=["PASS", "PASS"])]
    c = compare_arms(base, cand, band="xvendor_liberal", production_acceptable=0.85)
    md = comparison_markdown(c)
    assert "conversion A/B" in md and "By skill" in md
    paths = write_comparison(c, tmp_path)
    import json
    assert json.loads(open(paths["json"]).read())["n_pairs"] == 1
    assert open(paths["markdown"]).read().strip()
