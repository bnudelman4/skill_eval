"""Scorecard rendering (M5): JSON (machine) + Markdown/HTML (human).

Reports headline metrics against targets, per-skill and per-cell-type
breakdowns, and the list of FLAG cells for manual review. Interpretation notes
from the research are emitted as annotations.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from finskill_eval.metrics import Metrics

_INTERPRETATION = [
    "Cross-vendor disagreement (FLAG) is expected/informative, not a skill bug "
    "— usually a restatement or calendarization difference.",
    "Activation <90% -> fix skill descriptions, not bodies.",
    "Selection <95% with activation >=90% -> overlapping skills; consolidate.",
    "Pass-rate much lower at 0.1% than at 1% -> rounding/units bug; add a normalizer.",
    "Pass-rate flat across bands -> wrong cell mapping (calendarization/definition drift).",
    "Cost/run > $3.78 without accuracy payoff -> bloated context; cap skills <=8.",
]


def to_json(m: Metrics) -> str:
    return json.dumps(asdict(m), indent=2, sort_keys=True)


def _mark(ok: bool) -> str:
    return "PASS" if ok else "miss"


def to_markdown(m: Metrics) -> str:
    t = m.targets_eval
    lines = [
        "# finskill-eval scorecard",
        "",
        f"Samples: **{m.n_samples}**",
        "",
        "## Headline vs targets",
        "",
        "| Metric | Value | Target met |",
        "|---|---|---|",
        f"| Activation rate | {m.activation_rate:.1%} | {_mark(t['activation_pass'])} |",
        f"| Selection accuracy | {m.selection_accuracy:.1%} | {_mark(t['selection_pass'])} |",
        f"| Pass-rate @ {m.accuracy_eval_band} | {m.accuracy_pass_rate:.1%} | {_mark(t['accuracy_pass'])} |",
        "",
        f"Cells: PASS {m.counts['PASS']} · WARN {m.counts['WARN']} · "
        f"FAIL {m.counts['FAIL']} · FLAG {m.counts['FLAG']}",
        f"Cost: ${m.cost_total:.2f} total, ${m.cost_mean:.2f}/run · "
        f"Latency: {m.latency_mean:.0f}s mean, {m.latency_p95:.0f}s p95",
        "",
        "## Pass-rate by tolerance band (cumulative)",
        "",
        "| Band | Pass-rate |",
        "|---|---|",
    ]
    lines += [f"| {b} | {r:.1%} |" for b, r in m.pass_rate_by_band.items()]
    lines += ["", "## By skill", "", "| Skill | Cells | Pass-rate |", "|---|---|---|"]
    lines += [
        f"| {s} | {d['n_cells']} | {d['pass_rate']:.1%} |"
        for s, d in sorted(m.by_skill.items())
    ]
    lines += ["", "## By cell type (FAITH)", "", "| Type | Cells | Pass-rate |", "|---|---|---|"]
    lines += [
        f"| {c} | {d['n_cells']} | {d['pass_rate']:.1%} |"
        for c, d in sorted(m.by_cell_type.items())
    ]
    lines += ["", f"## FLAG cells for manual review ({len(m.flag_cells)})", ""]
    if m.flag_cells:
        lines += ["| Label | Period | Band |", "|---|---|---|"]
        lines += [
            f"| {v['canonical_label']} | {v['period']} | {v['band']} |"
            for v in m.flag_cells
        ]
    else:
        lines.append("_none_")
    lines += ["", "## Interpretation notes", ""]
    lines += [f"- {note}" for note in _INTERPRETATION]
    return "\n".join(lines) + "\n"


def to_html(m: Metrics) -> str:
    body = to_markdown(m).replace("&", "&amp;").replace("<", "&lt;")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>finskill-eval scorecard</title></head><body><pre>"
        f"{body}</pre></body></html>"
    )


def write_scorecard(m: Metrics, out_dir, basename: str = "scorecard") -> dict:
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out / f"{basename}.json",
        "markdown": out / f"{basename}.md",
        "html": out / f"{basename}.html",
    }
    paths["json"].write_text(to_json(m), encoding="utf-8")
    paths["markdown"].write_text(to_markdown(m), encoding="utf-8")
    paths["html"].write_text(to_html(m), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}
