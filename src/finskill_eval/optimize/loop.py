"""Validation-gated description optimization loop (M7.3 / M7.4).

The verifier scorecard is the reward signal. Each iteration proposes a bounded
description edit, scores it on a TRAIN split, and only promotes it if it also
wins on a held-out TEST split (overfit guard). Accuracy is a non-regression
guardrail: since the body is frozen, accuracy should not move; if a candidate
drops it, the candidate is rejected (something leaked or the description started
mis-triggering). Bounded to max_iterations.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from finskill_eval.optimize.candidate import make_candidate, LLM
from finskill_eval.optimize.skilldoc import SkillDoc

_EPS = 1e-9


@dataclass
class Query:
    prompt: str
    expected_skill: Optional[str]  # the skill that SHOULD trigger (None = none)


@dataclass
class RunObs:
    activated: bool
    selected: Optional[str]
    accuracy_passrate: float  # per-cell pass-rate of the produced artifact


# run_fn(doc, query) -> RunObs : wraps invoke_skill + verify in production
RunFn = Callable[[SkillDoc, Query], RunObs]


@dataclass
class VariantScore:
    n: int
    activation_rate: float
    selection_accuracy: float
    accuracy_passrate: float

    @property
    def primary(self) -> float:
        """Description-driven objective: mostly activation, some selection."""
        return 0.7 * self.activation_rate + 0.3 * self.selection_accuracy


def evaluate(
    doc: SkillDoc, queries: list[Query], *, runs_per_query: int, run_fn: RunFn
) -> VariantScore:
    """Average over positive queries x runs. runs_per_query stabilizes the
    activation-rate estimate against run-to-run nondeterminism."""
    skill = doc.name
    pos = [q for q in queries if q.expected_skill == skill]
    if not pos:
        return VariantScore(0, 0.0, 0.0, 0.0)
    activated = selected_ok = acc_sum = acc_n = 0
    total = 0
    for q in pos:
        for _ in range(runs_per_query):
            obs = run_fn(doc, q)
            total += 1
            if obs.activated:
                activated += 1
                if obs.selected == skill:
                    selected_ok += 1
                acc_sum += obs.accuracy_passrate
                acc_n += 1
    return VariantScore(
        n=total,
        activation_rate=activated / total if total else 0.0,
        selection_accuracy=selected_ok / activated if activated else 0.0,
        accuracy_passrate=acc_sum / acc_n if acc_n else 0.0,
    )


def split_queries(
    queries: list[Query], train_frac: float, *, seed: int = 0
) -> tuple[list[Query], list[Query]]:
    qs = list(queries)
    random.Random(seed).shuffle(qs)
    k = max(1, round(len(qs) * train_frac))
    return qs[:k], qs[k:]


@dataclass
class IterRecord:
    iteration: int
    accepted: bool
    reason: str
    train_primary: Optional[float] = None
    test_primary: Optional[float] = None
    description: Optional[str] = None


@dataclass
class OptResult:
    skill: str
    baseline_test: VariantScore
    best_test: VariantScore
    best_doc: SkillDoc
    history: list[IterRecord] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.best_test.primary > self.baseline_test.primary + _EPS


def optimize_skill(
    doc: SkillDoc,
    queries: list[Query],
    llm: LLM,
    *,
    train_frac: float,
    runs_per_query: int,
    max_iterations: int,
    max_edits: int,
    token_cap: int,
    accuracy_guard: bool,
    run_fn: RunFn,
    seed: int = 0,
) -> OptResult:
    train, test = split_queries(queries, train_frac, seed=seed)
    base_train = evaluate(doc, train, runs_per_query=runs_per_query, run_fn=run_fn)
    base_test = evaluate(doc, test, runs_per_query=runs_per_query, run_fn=run_fn)

    best_doc = doc
    best_test = base_test
    best_train_primary = base_train.primary
    history: list[IterRecord] = []

    for i in range(1, max_iterations + 1):
        cand = make_candidate(best_doc, llm, max_edits=max_edits, token_cap=token_cap)
        if cand is None:
            history.append(IterRecord(i, False, "candidate rejected by guards"))
            continue

        ct = evaluate(cand, train, runs_per_query=runs_per_query, run_fn=run_fn)

        if accuracy_guard and ct.accuracy_passrate < base_train.accuracy_passrate - _EPS:
            history.append(IterRecord(i, False, "accuracy regressed",
                                      ct.primary, None, cand.description))
            continue

        if ct.primary <= best_train_primary + _EPS:
            history.append(IterRecord(i, False, "no train gain",
                                      ct.primary, None, cand.description))
            continue

        # train gain -> evaluate on held-out test; promote ONLY on test gain
        cte = evaluate(cand, test, runs_per_query=runs_per_query, run_fn=run_fn)
        if cte.primary > best_test.primary + _EPS:
            best_doc, best_test, best_train_primary = cand, cte, ct.primary
            history.append(IterRecord(i, True, "promoted (test gain)",
                                      ct.primary, cte.primary, cand.description))
        else:
            history.append(IterRecord(i, False, "train gain but no test gain (overfit)",
                                      ct.primary, cte.primary, cand.description))

    return OptResult(doc.name, base_test, best_test, best_doc, history)
