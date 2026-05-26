"""Paired A/B: converted FMP skill vs Daloopa-baseline skill (M6, Stage 3).

Matches samples by (skill, ticker, period) so each pair is the same deliverable
produced two ways. Reports per-pair pass-rate deltas with a 95% CI, the
candidate's absolute pass-rate vs the production-acceptable bar, and the
research interpretation flags (notably: if the candidate *beats* the gold,
suspect a standardized-vs-as-reported gold mismatch, don't celebrate).

Pure/deterministic: arithmetic in Python, never an LLM.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from finskill_eval.metrics import _BAND_ORDER_DEFAULT, pass_rate_at
from finskill_eval.runner.grid import SampleRecord

_Z95 = 1.959963984540054


@dataclass
class Comparison:
    band: str
    n_pairs: int
    baseline_pass_rate: float
    candidate_pass_rate: float
    mean_delta: float
    ci_low: float
    ci_high: float
    production_acceptable: bool
    by_skill: dict[str, dict] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def _key(r: SampleRecord) -> tuple[str, str, str]:
    return (r.skill, r.ticker, r.period)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pooled_pass_rate(records: list[SampleRecord], band: str, order: list[str]) -> float:
    verdicts = [v for r in records for v in r.verdicts]
    return pass_rate_at(verdicts, band, order)


def compare_arms(
    baseline: list[SampleRecord],
    candidate: list[SampleRecord],
    *,
    band: str = "xvendor_liberal",
    production_acceptable: float = 0.85,
    band_order: list[str] | None = None,
) -> Comparison:
    order = band_order or _BAND_ORDER_DEFAULT
    base_by = {_key(r): r for r in baseline}
    cand_by = {_key(r): r for r in candidate}
    keys = sorted(base_by.keys() & cand_by.keys())

    deltas: list[float] = []
    matched_base: list[SampleRecord] = []
    matched_cand: list[SampleRecord] = []
    per_skill: dict[str, list[float]] = {}
    for k in keys:
        b, c = base_by[k], cand_by[k]
        bp = pass_rate_at(b.verdicts, band, order)
        cp = pass_rate_at(c.verdicts, band, order)
        d = cp - bp
        deltas.append(d)
        matched_base.append(b)
        matched_cand.append(c)
        per_skill.setdefault(k[0], []).append(d)

    n = len(deltas)
    mean_delta = _mean(deltas)
    if n >= 2:
        var = sum((d - mean_delta) ** 2 for d in deltas) / (n - 1)
        half = _Z95 * math.sqrt(var / n)
    else:
        half = 0.0
    ci_low, ci_high = mean_delta - half, mean_delta + half

    base_rate = _pooled_pass_rate(matched_base, band, order)
    cand_rate = _pooled_pass_rate(matched_cand, band, order)

    by_skill = {
        s: {"n_pairs": len(ds), "delta": _mean(ds)} for s, ds in sorted(per_skill.items())
    }

    flags: list[str] = []
    if cand_rate >= production_acceptable:
        flags.append(
            f"Candidate FMP pass-rate {cand_rate:.1%} >= {production_acceptable:.0%} "
            f"-> production-acceptable at {band}."
        )
    else:
        flags.append(
            f"Candidate FMP pass-rate {cand_rate:.1%} < {production_acceptable:.0%} "
            f"-> below production bar at {band}."
        )
    if cand_rate > base_rate:
        sig = " (CI excludes 0)" if n >= 2 and ci_low > 0 else ""
        flags.append(
            f"Candidate beats baseline{sig} -> investigate the gold: likely a "
            "standardized-vs-as-reported mismatch, not a real FMP win."
        )
    elif cand_rate < base_rate:
        sig = " (CI excludes 0)" if n >= 2 and ci_high < 0 else ""
        flags.append(
            f"Candidate worse than baseline{sig} -> data-layer swap lost fidelity; "
            "inspect fmp_data_access.md field map for the failing cells."
        )

    return Comparison(
        band=band,
        n_pairs=n,
        baseline_pass_rate=base_rate,
        candidate_pass_rate=cand_rate,
        mean_delta=mean_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        production_acceptable=cand_rate >= production_acceptable,
        by_skill=by_skill,
        flags=flags,
    )


def comparison_markdown(c: Comparison) -> str:
    sign = "+" if c.mean_delta >= 0 else ""
    lines = [
        "# finskill-eval conversion A/B — Daloopa baseline vs converted FMP",
        "",
        f"Matched pairs: **{c.n_pairs}** (same skill x ticker x period, both arms)",
        f"Evaluated at band: **{c.band}**",
        "",
        "| Arm | Pass-rate |",
        "|---|---|",
        f"| Daloopa baseline (gold-authored) | {c.baseline_pass_rate:.1%} |",
        f"| Converted FMP (candidate) | {c.candidate_pass_rate:.1%} |",
        "",
        f"Mean paired delta (FMP − Daloopa): **{sign}{c.mean_delta:.1%}** "
        f"(95% CI {c.ci_low:+.1%} … {c.ci_high:+.1%})",
        f"Production-acceptable (>= bar at {c.band}): "
        f"**{'YES' if c.production_acceptable else 'NO'}**",
        "",
        "## By skill",
        "",
        "| Skill | Pairs | Δ pass-rate |",
        "|---|---|---|",
    ]
    lines += [
        f"| {s} | {d['n_pairs']} | {d['delta']:+.1%} |"
        for s, d in c.by_skill.items()
    ]
    lines += ["", "## Interpretation flags", ""]
    lines += [f"- {f}" for f in c.flags] or ["- none"]
    return "\n".join(lines) + "\n"


def write_comparison(c: Comparison, out_dir, basename: str = "conversion_ab") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out / f"{basename}.json",
        "markdown": out / f"{basename}.md",
    }
    paths["json"].write_text(json.dumps(asdict(c), indent=2, sort_keys=True), "utf-8")
    paths["markdown"].write_text(comparison_markdown(c), "utf-8")
    return {k: str(v) for k, v in paths.items()}
