"""M7.3/4: validation gate + loop. Fully offline (fake run_fn + fake llm)."""

from finskill_eval.optimize.loop import (
    Query,
    RunObs,
    VariantScore,
    evaluate,
    optimize_skill,
    split_queries,
)
from finskill_eval.optimize.skilldoc import SkillDoc

DOC = SkillDoc.parse(
    """---
name: comps
description: comps thing
argument-hint: TICKER
---

## body
Frozen analytical prose.
"""
)

# queries: 6 positive for comps, 2 negative
QUERIES = [Query(f"relative value q{i}", "comps") for i in range(6)] + [
    Query("unrelated q1", None),
    Query("unrelated q2", None),
]


def test_split_is_deterministic_and_proportioned():
    a1, b1 = split_queries(QUERIES, 0.6, seed=1)
    a2, b2 = split_queries(QUERIES, 0.6, seed=1)
    assert [q.prompt for q in a1] == [q.prompt for q in a2]   # deterministic
    assert len(a1) + len(b1) == len(QUERIES)
    assert len(a1) == round(len(QUERIES) * 0.6)


def _run_fn_factory(good_marker: str, base_act: float, good_act: float):
    """Activation depends on whether the description contains good_marker.
    accuracy_passrate fixed high (body frozen)."""
    import random as _r

    def run_fn(doc: SkillDoc, q: Query) -> RunObs:
        rng = _r.Random(hash((doc.description, q.prompt)) & 0xFFFF)
        p = good_act if good_marker in doc.description else base_act
        activated = rng.random() < p
        return RunObs(activated=activated,
                      selected="comps" if activated else None,
                      accuracy_passrate=0.95)
    return run_fn


def test_evaluate_only_counts_positive_queries():
    run_fn = _run_fn_factory("trigger", base_act=1.0, good_act=1.0)
    sc = evaluate(DOC, QUERIES, runs_per_query=2, run_fn=run_fn)
    # 6 positive queries x 2 runs = 12, negatives ignored
    assert sc.n == 12
    assert sc.activation_rate == 1.0


def test_optimizer_promotes_better_description():
    # LLM injects the magic marker that lifts activation from 0.2 -> 0.95
    def llm(prompt: str) -> str:
        return "comps thing trigger relative-value valuation"

    run_fn = _run_fn_factory("trigger", base_act=0.2, good_act=0.95)
    res = optimize_skill(
        DOC, QUERIES, llm,
        train_frac=0.6, runs_per_query=4, max_iterations=5,
        max_edits=12, token_cap=920, accuracy_guard=True, run_fn=run_fn, seed=3,
    )
    assert res.improved
    assert "trigger" in res.best_doc.description
    assert res.best_doc.body_hash() == DOC.body_hash()       # body protected
    assert any(h.accepted for h in res.history)


def test_optimizer_keeps_baseline_when_no_real_gain():
    # LLM proposes a change that does NOT contain the marker -> no activation lift
    def llm(prompt: str) -> str:
        return "comps thing slightly reworded wording"

    run_fn = _run_fn_factory("trigger", base_act=0.5, good_act=0.95)
    res = optimize_skill(
        DOC, QUERIES, llm,
        train_frac=0.6, runs_per_query=4, max_iterations=5,
        max_edits=12, token_cap=920, accuracy_guard=True, run_fn=run_fn, seed=3,
    )
    assert not res.improved
    assert res.best_doc.description == DOC.description        # unchanged


def test_accuracy_guard_rejects_regressing_candidate():
    def llm(prompt: str) -> str:
        return "comps thing trigger relative-value valuation"

    # marker lifts activation BUT tanks accuracy -> must be rejected by guard
    def run_fn(doc: SkillDoc, q: Query) -> RunObs:
        good = "trigger" in doc.description
        return RunObs(activated=True, selected="comps",
                      accuracy_passrate=0.40 if good else 0.95)

    res = optimize_skill(
        DOC, QUERIES, llm,
        train_frac=0.6, runs_per_query=2, max_iterations=5,
        max_edits=12, token_cap=920, accuracy_guard=True, run_fn=run_fn, seed=3,
    )
    assert not res.improved
    assert any("accuracy regressed" in h.reason for h in res.history)
