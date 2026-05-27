"""Aggregate grid results into headline + breakdown metrics (M5).

Pure: takes SampleRecords, returns a Metrics object. pass-rate is cumulative
per tolerance band; WARN does not count as PASS and FLAG is excluded from the
denominator (cross-vendor disagreements are not skill failures).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from finskill_eval.runner.grid import SampleRecord
from finskill_eval.tolerance import Bands

_BAND_ORDER_DEFAULT = [b.name for b in Bands.default().bands] + [
    Bands.default().overflow.name
]


@dataclass
class Metrics:
    n_samples: int
    activation_rate: float
    selection_accuracy: float
    counts: dict[str, int]
    pass_rate_by_band: dict[str, float]
    accuracy_pass_rate: float
    accuracy_eval_band: str
    cost_total: float
    cost_mean: float
    latency_mean: float
    latency_p95: float
    by_skill: dict[str, dict] = field(default_factory=dict)
    by_ticker: dict[str, dict] = field(default_factory=dict)
    by_cell_type: dict[str, dict] = field(default_factory=dict)
    by_band: dict[str, dict] = field(default_factory=dict)
    flag_cells: list[dict] = field(default_factory=list)
    targets_eval: dict[str, bool] = field(default_factory=dict)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _all_verdicts(records: Iterable[SampleRecord]) -> list[dict]:
    return [v for r in records for v in r.verdicts]


def pass_rate_at(verdicts: list[dict], band: str, order: list[str] | None = None) -> float:
    """Public: cumulative pass-rate of a verdict set at a tolerance band.
    FLAG cells are excluded from the denominator; WARN does not count as PASS."""
    return _pass_rate_at(verdicts, band, order or _BAND_ORDER_DEFAULT)


def _pass_rate_at(verdicts: list[dict], band: str, order: list[str]) -> float:
    gradeable = [v for v in verdicts if v["status"] not in ("FLAG", "SKIP")]
    if not gradeable:
        return 0.0
    idx = order.index(band)
    passed = sum(
        1
        for v in gradeable
        if v["status"] == "PASS" and order.index(v["band"]) <= idx
    )
    return passed / len(gradeable)


def _group_metrics(verdicts: list[dict], band: str, order: list[str]) -> dict:
    counts = {s: 0 for s in ("PASS", "WARN", "FLAG", "FAIL", "SKIP")}
    for v in verdicts:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {
        "n_cells": len(verdicts),
        "counts": counts,
        "pass_rate": _pass_rate_at(verdicts, band, order),
    }


def aggregate(
    records: list[SampleRecord],
    *,
    activation_min: float,
    selection_min: float,
    accuracy_min: float,
    accuracy_eval_band: str,
    band_order: list[str] | None = None,
) -> Metrics:
    order = band_order or _BAND_ORDER_DEFAULT
    n = len(records)
    verdicts = _all_verdicts(records)

    activation_rate = sum(r.activation_observed for r in records) / n if n else 0.0
    selected = [r for r in records if r.skill_selected is not None]
    selection_accuracy = (
        sum(1 for r in selected if r.skill_selected == r.skill) / len(selected)
        if selected
        else 0.0
    )

    counts = {s: 0 for s in ("PASS", "WARN", "FLAG", "FAIL", "SKIP")}
    for v in verdicts:
        counts[v["status"]] = counts.get(v["status"], 0) + 1

    pass_rate_by_band = {
        name: _pass_rate_at(verdicts, name, order)
        for name in order
        if name != "exact"  # exact pass-rate is rarely meaningful as a headline
    }
    accuracy_pass_rate = _pass_rate_at(verdicts, accuracy_eval_band, order)

    costs = [r.cost_usd for r in records]
    lats = [r.latency_s for r in records]

    def _grp(key) -> dict[str, dict]:
        buckets: dict[str, list[dict]] = {}
        for r in records:
            buckets.setdefault(key(r), [])
        # group verdicts by the record's key
        for r in records:
            buckets[key(r)].extend(r.verdicts)
        return {k: _group_metrics(vs, accuracy_eval_band, order) for k, vs in buckets.items()}

    by_cell_type: dict[str, list[dict]] = {}
    for v in verdicts:
        by_cell_type.setdefault(v.get("cell_type") or "unknown", []).append(v)

    return Metrics(
        n_samples=n,
        activation_rate=activation_rate,
        selection_accuracy=selection_accuracy,
        counts=counts,
        pass_rate_by_band=pass_rate_by_band,
        accuracy_pass_rate=accuracy_pass_rate,
        accuracy_eval_band=accuracy_eval_band,
        cost_total=sum(costs),
        cost_mean=sum(costs) / n if n else 0.0,
        latency_mean=sum(lats) / n if n else 0.0,
        latency_p95=_percentile(lats, 0.95),
        by_skill=_grp(lambda r: r.skill),
        by_ticker=_grp(lambda r: r.ticker),
        by_cell_type={
            k: _group_metrics(vs, accuracy_eval_band, order)
            for k, vs in by_cell_type.items()
        },
        by_band={name: {"n_cells": counts2} for name, counts2 in
                 {b: sum(1 for v in verdicts if v["band"] == b) for b in order}.items()},
        flag_cells=[v for v in verdicts if v["status"] == "FLAG"],
        targets_eval={
            "activation_pass": activation_rate >= activation_min,
            "selection_pass": selection_accuracy >= selection_min,
            "accuracy_pass": accuracy_pass_rate >= accuracy_min,
        },
    )


# --------------------------------------------------------------------------- #
# Per-skill effect size (M7 / friend's point): surface per-skill deltas with a
# confidence interval, not just an aggregate. Used by the A/B (M6) and the
# before/after optimization report (M7).
# --------------------------------------------------------------------------- #
import math


@dataclass
class EffectSize:
    n: int
    mean_delta: float       # mean of paired (variant - baseline)
    sd: float               # sample std dev of the deltas
    ci95_low: float
    ci95_high: float
    cohens_d: float         # mean_delta / sd (paired)

    @property
    def significant(self) -> bool:
        """95% CI excludes zero -> the delta is unlikely to be noise."""
        return self.ci95_low > 0.0 or self.ci95_high < 0.0


def effect_size(deltas: list[float]) -> EffectSize:
    """Paired effect size for a list of (variant - baseline) deltas.

    Uses a normal approximation for the 95% CI (1.96 * SE). For small n this is
    approximate; the CI is a guide for 'is this real', not a hypothesis test.
    """
    n = len(deltas)
    if n == 0:
        return EffectSize(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mean = sum(deltas) / n
    if n == 1:
        return EffectSize(1, mean, 0.0, mean, mean, 0.0)
    var = sum((d - mean) ** 2 for d in deltas) / (n - 1)
    sd = math.sqrt(var)
    se = sd / math.sqrt(n)
    half = 1.96 * se
    d = mean / sd if sd > 0 else 0.0
    return EffectSize(n, mean, sd, mean - half, mean + half, d)
