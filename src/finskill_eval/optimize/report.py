"""Optimization scorecard (M7): per-skill before/after with accepted diffs."""

from __future__ import annotations

from finskill_eval.optimize.loop import OptResult


def render_optimization_report(results: list[OptResult]) -> str:
    lines = ["# Skill Description Optimization — Scorecard", ""]
    lines.append("Optimized ONLY descriptions; bodies frozen (protected). "
                 "Best variant selected by held-out TEST score (overfit guard).")
    lines.append("")
    lines.append("| skill | baseline primary | best primary | Δ | activation Δ | promoted |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        d = r.best_test.primary - r.baseline_test.primary
        act_d = r.best_test.activation_rate - r.baseline_test.activation_rate
        lines.append(
            f"| {r.skill} | {r.baseline_test.primary:.3f} | {r.best_test.primary:.3f} "
            f"| {d:+.3f} | {act_d:+.3f} | {'✅' if r.improved else '—'} |"
        )
    lines.append("")
    for r in results:
        lines.append(f"## {r.skill}")
        if r.improved:
            lines.append(f"- **best description:** {r.best_doc.description}")
        else:
            lines.append("- no improvement; baseline description kept")
        accepted = [h for h in r.history if h.accepted]
        lines.append(f"- iterations: {len(r.history)}, accepted: {len(accepted)}")
        for h in r.history:
            mark = "ACCEPT" if h.accepted else "reject"
            tp = f"{h.train_primary:.3f}" if h.train_primary is not None else "—"
            te = f"{h.test_primary:.3f}" if h.test_primary is not None else "—"
            lines.append(f"  - iter {h.iteration} [{mark}] {h.reason} "
                         f"(train={tp}, test={te})")
        lines.append("")
    return "\n".join(lines)
