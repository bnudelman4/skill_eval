"""Orchestrates parse -> match -> recompute -> score (M2.6).

For each cell:
  * exact non-numeric (ticker/label): string equality -> exact/PASS or FAIL.
  * direct numeric: compare(stated, truth) -> band/status.
  * derived: recompute from the skill's OWN inputs, then
      (a) arithmetic check: stated vs recomputed. If it exceeds the arithmetic
          tolerance (the 'tight' band) the skill did the math wrong -> FAIL.
      (b) sourcing check: recomputed vs truth -> cross-vendor band.
    The reported band is the wider of (a) and (b); status follows sourcing
    unless arithmetic FAILed.

Ground truth is any object with get(ticker, period_key, canonical_label) -> value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol, Union

from finskill_eval.ledger import Ledger
from finskill_eval.normalize import period_key
from finskill_eval.recompute import recompute
from finskill_eval.tolerance import Bands, compare

VerifyStatus = Literal["PASS", "WARN", "FLAG", "FAIL"]
Value = Union[float, str, None]


class GroundTruthSource(Protocol):
    def get(self, ticker: str, period: Optional[str], canonical_label: str) -> Value: ...


@dataclass(frozen=True)
class CellVerdict:
    cell_id: str
    canonical_label: str
    period: Optional[str]
    kind: str
    cell_type: Optional[str]
    pred: Value
    truth: Value
    recomputed: Optional[float]
    rel_err: Optional[float]
    band: str
    status: VerifyStatus
    note: str = ""


@dataclass
class Rollup:
    counts: dict[str, int]
    band_counts: dict[str, int]
    pass_rate: float
    failures: list[CellVerdict] = field(default_factory=list)
    flags: list[CellVerdict] = field(default_factory=list)
    warns: list[CellVerdict] = field(default_factory=list)


@dataclass
class VerifyReport:
    skill: str
    ticker: str
    verdicts: list[CellVerdict]
    rollup: Rollup


def _band_order(bands: Bands) -> list[str]:
    return [b.name for b in bands.bands] + [bands.overflow.name]


def _arithmetic_threshold(bands: Bands, band_name: str) -> float:
    for b in bands.bands:
        if b.name == band_name:
            return b.max_rel
    raise ValueError(f"arithmetic band {band_name!r} not found in schema")


def verify(
    ledger: Ledger,
    ground_truth: GroundTruthSource,
    *,
    bands: Optional[Bands] = None,
    arithmetic_band: str = "tight",
) -> VerifyReport:
    b = bands or Bands.default()
    order = _band_order(b)
    arith_tol = _arithmetic_threshold(b, arithmetic_band)
    recomputed = recompute(ledger)

    def wider(band1: str, band2: str) -> str:
        return band1 if order.index(band1) >= order.index(band2) else band2

    verdicts: list[CellVerdict] = []
    for cell in ledger.cells:
        pkey = period_key(cell.period)
        # sources may return a raw scalar or a Value record; unwrap to the scalar
        raw_truth = ground_truth.get(ledger.ticker, pkey, cell.canonical_label)
        truth = getattr(raw_truth, "value", raw_truth)

        # exact non-numeric (e.g. ticker)
        if isinstance(cell.value, str):
            ok = truth is not None and str(cell.value) == str(truth)
            verdicts.append(
                CellVerdict(
                    cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                    cell.value, truth, None, None,
                    "exact" if ok else "disagreement",
                    "PASS" if ok else "FAIL",
                )
            )
            continue

        if cell.kind == "derived" and cell.cell_id in recomputed:
            recomp = recomputed[cell.cell_id]
            arith = compare(float(cell.value), recomp, bands=b)
            if arith.rel_err > arith_tol:
                verdicts.append(
                    CellVerdict(
                        cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                        cell.value, truth, recomp, arith.rel_err,
                        arith.band, "FAIL",
                        note="stated value disagrees with recompute of its own inputs",
                    )
                )
                continue
            if truth is None:
                verdicts.append(
                    CellVerdict(
                        cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                        cell.value, None, recomp, arith.rel_err,
                        arith.band, "FAIL", note="no ground-truth value",
                    )
                )
                continue
            src = compare(recomp, float(truth), bands=b)
            verdicts.append(
                CellVerdict(
                    cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                    cell.value, truth, recomp, src.rel_err,
                    wider(arith.band, src.band), src.status,
                )
            )
            continue

        # direct numeric (or derived without wired inputs -> treat as direct)
        if truth is None:
            verdicts.append(
                CellVerdict(
                    cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                    cell.value, None, None, None,
                    "disagreement", "FAIL", note="no ground-truth value",
                )
            )
            continue
        r = compare(float(cell.value), float(truth), bands=b)
        verdicts.append(
            CellVerdict(
                cell.cell_id, cell.canonical_label, pkey, cell.kind, cell.cell_type,
                cell.value, truth, None, r.rel_err, r.band, r.status,
            )
        )

    return VerifyReport(ledger.skill, ledger.ticker, verdicts, _rollup(verdicts, order))


def _rollup(verdicts: list[CellVerdict], band_order: list[str]) -> Rollup:
    counts = {s: 0 for s in ("PASS", "WARN", "FLAG", "FAIL")}
    band_counts = {name: 0 for name in band_order}
    for v in verdicts:
        counts[v.status] += 1
        band_counts[v.band] = band_counts.get(v.band, 0) + 1
    total = len(verdicts) or 1
    return Rollup(
        counts=counts,
        band_counts=band_counts,
        pass_rate=counts["PASS"] / total,
        failures=[v for v in verdicts if v.status == "FAIL"],
        flags=[v for v in verdicts if v.status == "FLAG"],
        warns=[v for v in verdicts if v.status == "WARN"],
    )
