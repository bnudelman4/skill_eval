"""M7 orchestration — offline, end-to-end with fakes."""

from pathlib import Path

from finskill_eval.optimize.loop import Query, RunObs
from finskill_eval.optimize.run_optimization import optimize_all, write_best
from finskill_eval.optimize.skilldoc import SkillDoc

SKILL_MD = """---
name: comps
description: comps thing
argument-hint: TICKER
---

## body
Frozen prose.
"""


def _setup(tmp_path):
    p = tmp_path / "comps" / "SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text(SKILL_MD)
    queries = {"comps": [Query(f"q{i}", "comps") for i in range(6)]}
    return {"comps": p}, queries


def _good_run_fn(doc: SkillDoc, q: Query) -> RunObs:
    act = 0.95 if "trigger" in doc.description else 0.2
    import hashlib
    import random
    seed = int(hashlib.sha256(f"{doc.description}|{q.prompt}".encode()).hexdigest(), 16) & 0xFFFF
    r = random.Random(seed).random()
    on = r < act
    return RunObs(on, "comps" if on else None, 0.95)


def test_optimize_all_writes_report_and_improves(tmp_path):
    paths, queries = _setup(tmp_path)
    report = tmp_path / "opt.md"
    results = optimize_all(
        paths, queries,
        llm=lambda p: "comps thing trigger relative-value",
        run_fn=_good_run_fn,
        train_frac=0.6, runs_per_query=4, max_iterations=5,
        max_edits=12, token_cap=920, accuracy_guard=True, seed=3,
        out_report=report,
    )
    assert report.exists() and "comps" in report.read_text()
    assert results[0].improved

    # write_best persists the improved description but keeps body byte-identical
    orig_body = SkillDoc.parse(SKILL_MD).body
    write_best(results, paths)
    after = SkillDoc.parse(paths["comps"].read_text())
    assert "trigger" in after.description
    assert after.body == orig_body


def test_write_best_skips_unimproved(tmp_path):
    paths, queries = _setup(tmp_path)
    results = optimize_all(
        paths, queries,
        llm=lambda p: "comps thing reworded",          # no marker -> no gain
        run_fn=_good_run_fn,
        train_frac=0.6, runs_per_query=4, max_iterations=5,
        max_edits=12, token_cap=920, accuracy_guard=True, seed=3,
    )
    assert not results[0].improved
    assert write_best(results, paths) == []             # nothing written
    assert SkillDoc.parse(paths["comps"].read_text()).description == "comps thing"
