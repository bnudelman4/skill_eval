"""Inspect AI adapter (M5): model each grid sample as an Inspect Sample, with a
Solver that invokes the skill and a Scorer that runs the deterministic verifier.

inspect_ai is imported inside build_task so importing this module never requires
the Inspect runtime. The practical batch runner is runner.parallel.run_grid
(no Docker required); this adapter exists for Inspect-native evaluation and
sandboxed execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from finskill_eval.groundtruth.base import GroundTruthSource
from finskill_eval.runner.grid import GridSample, score_sample
from finskill_eval.runner.invoke_skill import SkillRun


def build_task(
    samples: list[GridSample],
    *,
    invoke_fn: Callable[..., SkillRun],
    ground_truth: GroundTruthSource,
    workdir_root: Path,
):
    """Construct an inspect_ai Task whose scorer is our deterministic verifier."""
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import Score, Target, mean, scorer
    from inspect_ai.solver import Generate, TaskState, solver

    ds = MemoryDataset(
        [
            Sample(
                input=s.sample_id,
                metadata={
                    "skill": s.skill, "ticker": s.ticker,
                    "period": s.period, "data_source": s.data_source,
                },
            )
            for s in samples
        ]
    )

    @solver
    def invoke_and_verify():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            md = state.metadata
            sample = GridSample(md["skill"], md["ticker"], md["period"], md["data_source"])
            rec = score_sample(
                sample, invoke_fn=invoke_fn, ground_truth=ground_truth,
                workdir_root=workdir_root,
            )
            state.metadata["record"] = rec
            return state

        return solve

    @scorer(metrics=[mean()])
    def verifier_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            rec = state.metadata.get("record")
            verdicts = rec.verdicts if rec else []
            gradeable = [v for v in verdicts if v["status"] != "FLAG"]
            passed = sum(1 for v in gradeable if v["status"] == "PASS")
            value = passed / len(gradeable) if gradeable else 0.0
            return Score(value=value, metadata={"counts_n": len(verdicts)})

        return score

    return Task(dataset=ds, solver=invoke_and_verify(), scorer=verifier_scorer())
