"""M7 mechanics demonstration — deterministic, no live calls.

Exercises optimize_all() end-to-end with a stand-in proposer and a synthetic
run_fn whose activation probability rises with the description's trigger-keyword
content. Produces a real iteration_report.md so the optimizer's *mechanics* are
observable (candidate generation, validation gate, accept/reject by test score,
overfit guard, protected-body invariant) without spending live quota.

A real end-to-end live optimization is documented in docs/next_steps.md as the
next thing to run; this script is offline-deterministic so it can ship today.

Run:   PYTHONPATH=src python scripts/m7_demo.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from finskill_eval.optimize.loop import Query, RunObs
from finskill_eval.optimize.run_optimization import optimize_all
from finskill_eval.optimize.skilldoc import SkillDoc

# Trigger keywords the synthetic activation function rewards.
TRIGGERS = [
    "tearsheet", "fundamentals", "quarterly", "annual",
    "snapshot", "financial", "summary", "company", "overview",
]


import re

_DESC_RE = re.compile(r"Current description:\s*\n(.*?)\n\nRewrite", re.DOTALL)


def proposer(prompt_or_desc: str) -> str:
    """Deterministically extends the description with trigger keywords. Accepts
    either the raw description or the full proposer prompt (the loop calls us
    with the prompt template; the description is embedded in it)."""
    m = _DESC_RE.search(prompt_or_desc)
    current_desc = m.group(1).strip() if m else prompt_or_desc.strip()
    missing = [w for w in TRIGGERS if w.lower() not in current_desc.lower()]
    if not missing:
        return current_desc
    add = missing[:3]                  # stay well under max_edits
    return current_desc.rstrip(".") + f". Use for {', '.join(add)} analyses."


def make_run_fn():
    """Synthetic eval. Activation probability scales with the number of trigger
    keywords present in the description; selection is the skill name when
    activated. Deterministic on (description, query)."""
    def run_fn(doc: SkillDoc, query: Query) -> RunObs:
        desc = doc.description.lower()
        n_triggers = sum(1 for t in TRIGGERS if t in desc)
        # baseline 20%, +12% per trigger; cap 92%
        prob = min(0.20 + 0.12 * n_triggers, 0.92)
        seed = f"{doc.description}|{query.prompt}"
        h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) / 2**32
        activated = h < prob
        return RunObs(
            activated=activated,
            selected="tearsheet" if activated else None,
            accuracy_passrate=0.872,   # held constant — description doesn't drive accuracy
        )
    return run_fn


def main() -> None:
    skill_path = Path("skills/fmp/tearsheet/SKILL.md")
    skill_paths = {"tearsheet": skill_path}

    # mix of positive queries that should trigger tearsheet
    tickers = ["AAPL", "MSFT", "JPM", "NKE", "TSLA", "GOOGL", "WMT", "PG"]
    queries = [
        Query(prompt=f"Produce a tearsheet for {t}", expected_skill="tearsheet")
        for t in tickers
    ]

    out_report = Path("results/_m7_demo/iteration_report.md")
    results = optimize_all(
        skill_paths,
        {"tearsheet": queries},
        llm=proposer,
        run_fn=make_run_fn(),
        train_frac=0.6,
        runs_per_query=3,
        max_iterations=3,
        max_edits=15,         # SkillOpt's 4-8 is per *atomic* edit; our test
                              # candidate appends a phrase counted as ~9 inserts
        token_cap=200,
        accuracy_guard=True,
        seed=42,
        out_report=out_report,
    )

    print(f"\n=== M7 demo headline ===")
    for r in results:
        bs, be = r.baseline_test, r.best_test
        print(
            f"  skill={r.skill:12s} improved={r.improved}\n"
            f"    baseline  primary={bs.primary:.3f}  activation={bs.activation_rate:.3f}  "
            f"selection={bs.selection_accuracy:.3f}\n"
            f"    best      primary={be.primary:.3f}  activation={be.activation_rate:.3f}  "
            f"selection={be.selection_accuracy:.3f}\n"
            f"    accepted iters: {sum(1 for h in r.history if h.accepted)}/{len(r.history)}"
        )
    print(f"\nreport: {out_report}")


if __name__ == "__main__":
    main()
