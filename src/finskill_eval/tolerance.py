"""The banded comparator (Part A3). PURE — no I/O, no settings import.

rel = |pred - truth| / max(|truth|, abs_floor); when |truth| < near_zero_floor
we cannot form a meaningful relative error, so we fall back to an absolute
check: equal-at-zero -> exact, otherwise -> disagreement (FLAG).

compare() returns only band statuses PASS/WARN/FLAG. FAIL is a verify-level
verdict (exact-cell mismatch or derived arithmetic error) and is never produced
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["PASS", "WARN", "FLAG"]


@dataclass(frozen=True)
class BandSpec:
    name: str
    max_rel: float
    status: Status


@dataclass(frozen=True)
class OverflowSpec:
    name: str
    status: Status


@dataclass(frozen=True)
class BandResult:
    band: str
    status: Status
    rel_err: float


@dataclass(frozen=True)
class Bands:
    bands: tuple[BandSpec, ...]
    overflow: OverflowSpec
    near_zero_floor: float = 1e-9
    abs_floor: float = 1e-9

    @classmethod
    def default(cls) -> "Bands":
        """The ratified A3 schema as literals (keeps this module I/O-free)."""
        return cls(
            bands=(
                BandSpec("exact", 0.0, "PASS"),
                BandSpec("tight", 0.001, "PASS"),
                BandSpec("xvendor_standard", 0.005, "PASS"),
                BandSpec("xvendor_liberal", 0.01, "PASS"),
                BandSpec("materiality", 0.05, "WARN"),
            ),
            overflow=OverflowSpec("disagreement", "FLAG"),
        )


_DEFAULT = Bands.default()


def compare(pred: float, truth: float, *, bands: Bands | None = None) -> BandResult:
    b = bands or _DEFAULT
    if abs(truth) < b.near_zero_floor:
        if abs(pred - truth) <= b.near_zero_floor:
            return BandResult(b.bands[0].name, b.bands[0].status, 0.0)
        return BandResult(b.overflow.name, b.overflow.status, abs(pred - truth))

    rel = abs(pred - truth) / max(abs(truth), b.abs_floor)
    for spec in b.bands:  # tightest-first; first containing band wins
        if rel <= spec.max_rel:
            return BandResult(spec.name, spec.status, rel)
    return BandResult(b.overflow.name, b.overflow.status, rel)
