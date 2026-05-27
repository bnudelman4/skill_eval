"""Top-level M7 orchestrator: optimize each skill's description, write scorecard.

Gated behind settings.optimization.enabled. The LLM (description proposer) and
run_fn (eval) are injected so the orchestration is testable offline; the
production run_fn factory wraps invoke_skill -> parse -> verify and is wired by
the caller when running live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from finskill_eval.optimize.candidate import LLM
from finskill_eval.optimize.loop import OptResult, Query, RunFn, optimize_skill
from finskill_eval.optimize.report import render_optimization_report
from finskill_eval.optimize.skilldoc import SkillDoc


def optimize_all(
    skill_paths: dict[str, Path],          # skill name -> SKILL.md path
    queries_by_skill: dict[str, list[Query]],
    llm: LLM,
    run_fn: RunFn,
    *,
    train_frac: float,
    runs_per_query: int,
    max_iterations: int,
    max_edits: int,
    token_cap: int,
    accuracy_guard: bool,
    seed: int = 0,
    out_report: Optional[Path] = None,
) -> list[OptResult]:
    results: list[OptResult] = []
    for skill, path in skill_paths.items():
        doc = SkillDoc.parse(Path(path).read_text(encoding="utf-8"))
        res = optimize_skill(
            doc, queries_by_skill.get(skill, []), llm,
            train_frac=train_frac, runs_per_query=runs_per_query,
            max_iterations=max_iterations, max_edits=max_edits,
            token_cap=token_cap, accuracy_guard=accuracy_guard,
            run_fn=run_fn, seed=seed,
        )
        results.append(res)

    if out_report is not None:
        out_report = Path(out_report)
        out_report.parent.mkdir(parents=True, exist_ok=True)
        out_report.write_text(render_optimization_report(results), encoding="utf-8")
    return results


def write_best(results: list[OptResult], skill_paths: dict[str, Path]) -> list[Path]:
    """Persist improved descriptions back to their SKILL.md (body untouched)."""
    written = []
    for res in results:
        if res.improved and res.skill in skill_paths:
            p = Path(skill_paths[res.skill])
            p.write_text(res.best_doc.to_text(), encoding="utf-8")
            written.append(p)
    return written
