"""M7.6: feedback capture + optimization report."""

from finskill_eval.optimize.feedback import (
    FeedbackEntry,
    append_feedback,
    load_feedback,
    summarize_feedback,
)
from finskill_eval.optimize.loop import IterRecord, OptResult, VariantScore
from finskill_eval.optimize.report import render_optimization_report
from finskill_eval.optimize.skilldoc import SkillDoc


def test_feedback_roundtrip(tmp_path):
    p = tmp_path / "feedback.jsonl"
    e1 = FeedbackEntry("comps", "AAPL", "FY2024", "revenue", "FLAG", "correct", "restatement")
    e2 = FeedbackEntry("comps", "AAPL", "FY2024", "ebitda", "PASS", "wrong", "wrong base")
    append_feedback(p, e1)
    append_feedback(p, e2)
    loaded = load_feedback(p)
    assert len(loaded) == 2
    assert loaded[0].canonical_label == "revenue"
    assert loaded[0].disagrees and loaded[1].disagrees


def test_feedback_summary_flags_band_issues():
    entries = [
        FeedbackEntry("comps", "AAPL", "FY2024", "revenue", "FLAG", "correct"),
        FeedbackEntry("comps", "MSFT", "FY2024", "ebitda", "PASS", "wrong"),
        FeedbackEntry("comps", "JPM", "FY2024", "net_income", "PASS", "correct"),
    ]
    s = summarize_feedback(entries)
    assert s.total == 3
    assert s.agreements == 1
    assert s.flag_overturned_correct == 1
    assert s.pass_overturned_wrong == 1
    assert any("too tight" in x for x in s.suggestions)
    assert any("too loose" in x for x in s.suggestions)


def test_load_missing_file_returns_empty(tmp_path):
    assert load_feedback(tmp_path / "nope.jsonl") == []


def test_optimization_report_renders():
    doc = SkillDoc.parse("---\nname: comps\ndescription: better desc\n---\nbody\n")
    res = OptResult(
        skill="comps",
        baseline_test=VariantScore(10, 0.60, 0.90, 0.95),
        best_test=VariantScore(10, 0.92, 0.98, 0.95),
        best_doc=doc,
        history=[IterRecord(1, True, "promoted (test gain)", 0.9, 0.92, "better desc")],
    )
    md = render_optimization_report([res])
    assert "comps" in md
    assert "better desc" in md
    assert "✅" in md
    assert "promoted" in md
