"""FMP-self-check: did the LLM transcribe & compute correctly from FMP?

For every cell in the ledger:
- direct cells: query FMP independently for the canonical field, compare to stated.
- derived cells: query FMP for the formula's inputs, recompute, compare to stated.

This is *not* an independence check — both we and the skill are reading FMP. It
catches LLM transcription, field-selection, period-grab, and arithmetic errors.
For independence (vendor-vs-vendor disagreement), see verify.py + the SEC anchor.

Tolerance: tight band (0.1% relative) by default — these should be exact matches
modulo display rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from finskill_eval.groundtruth.base import GroundTruthSource
from finskill_eval.ledger import Ledger
from finskill_eval.normalize import period_key
from finskill_eval.recompute import FORMULAS, METRIC_DEFS


@dataclass
class SelfCheckVerdict:
    cell_id: str
    canonical_label: str
    period: Optional[str]
    kind: str                 # "direct" or "derived"
    stated: Optional[float]
    fmp_value: Optional[float]
    rel_err: Optional[float]
    status: str               # "PASS" | "FAIL" | "SKIP"
    note: str = ""


@dataclass
class SelfCheckReport:
    skill: str
    ticker: str
    verdicts: list[SelfCheckVerdict]

    @property
    def counts(self) -> dict[str, int]:
        out = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for v in self.verdicts:
            out[v.status] = out.get(v.status, 0) + 1
        return out

    @property
    def pass_rate(self) -> float:
        c = self.counts
        denom = c.get("PASS", 0) + c.get("FAIL", 0)
        return (c.get("PASS", 0) / denom) if denom else 0.0


_TIGHT_REL = 0.001   # 0.1% — these are same-source checks, should be exact

# Try ×{1e-9 ... 1e9} and both signs. Cash-flow items in FMP encode outflows
# as negative ("commonStockRepurchased = -3.493e+09"); skills typically state
# the absolute amount returned. Same value, different convention.
# Includes 1e2 / 1e-2 for the percent-vs-fraction convention (skill states
# 0.4421 fraction, Python recompute returns 44.21 percent — ×100 apart).
_SCALE_FACTORS = (1.0, 100.0, 0.01, 1e3, 1e-3, 1e6, 1e-6, 1e9, 1e-9)


def _rel_err(a: float, b: float) -> float:
    if b == 0:
        return abs(a)
    return abs(a - b) / abs(b)


def _best_match(stated: float, fmp_value: float) -> tuple[float, float, str]:
    """Try scale + sign combinations, return (best_rel_err, factor_applied, note).
    Sign flip handles FMP's negative-for-outflow convention vs skills stating
    the absolute amount."""
    best = (_rel_err(stated, fmp_value), 1.0, "")
    for f in _SCALE_FACTORS:
        for sign in (1.0, -1.0):
            r = _rel_err(stated * f * sign, fmp_value)
            if r < best[0]:
                tag = ""
                if f != 1.0 and sign != 1.0:
                    tag = f"scale x{f:g} + sign-flipped"
                elif f != 1.0:
                    tag = f"scale-normalized x{f:g}"
                elif sign != 1.0:
                    tag = "sign-flipped (FMP outflow convention)"
                best = (r, f * sign, tag)
    return best


def _check_direct(cell, fmp: GroundTruthSource) -> SelfCheckVerdict:
    pkey = period_key(cell.period)
    if not isinstance(cell.value, (int, float)):
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, "direct",
            None, None, None, "SKIP", note="non-numeric cell",
        )
    raw = fmp.get(cell.ticker if hasattr(cell, "ticker") else "", pkey, cell.canonical_label)
    # cell doesn't carry ticker; caller must pass it via the wrapper
    return SelfCheckVerdict(
        cell.cell_id, cell.canonical_label, pkey, "direct",
        float(cell.value), None, None, "SKIP",
        note="ticker not on cell — use run_fmp_self_check()",
    )


def _check_one_cell(cell, ticker: str, ledger: Ledger,
                    fmp: GroundTruthSource) -> SelfCheckVerdict:
    pkey = period_key(cell.period)
    if not isinstance(cell.value, (int, float)):
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, cell.kind,
            None, None, None, "SKIP", note="non-numeric cell",
        )

    # DIRECT cell: look up the canonical field directly in FMP
    if cell.kind == "direct":
        truth = fmp.get(ticker, pkey, cell.canonical_label)
        if truth is None:
            return SelfCheckVerdict(
                cell.cell_id, cell.canonical_label, pkey, "direct",
                float(cell.value), None, None, "SKIP",
                note="FMP has no field for this label",
            )
        tval = float(getattr(truth, "value", truth))
        # try scale/sign combinations — same value under different conventions
        # (e.g. cash items: skill states +3.5B paid out vs FMP -3.5B outflow)
        rel, _factor, note = _best_match(float(cell.value), tval)
        status = "PASS" if rel <= _TIGHT_REL else "FAIL"
        # only annotate when the convention adjustment actually helped land it
        annotation = note if (status == "PASS" and note) else ""
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, "direct",
            float(cell.value), tval, rel, status, note=annotation,
        )

    # DERIVED cell: query FMP for the formula's INPUTS (not the skill's stated
    # inputs), recompute, compare. Catches "skill grabbed the wrong revenue".
    spec = METRIC_DEFS.get(cell.canonical_label)
    if spec is None:
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, "derived",
            float(cell.value), None, None, "SKIP",
            note=f"no formula registered for {cell.canonical_label}",
        )
    formula_name, input_labels = spec
    fn = FORMULAS.get(formula_name)
    if fn is None:
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, "derived",
            float(cell.value), None, None, "SKIP",
            note=f"unknown formula {formula_name!r}",
        )

    args: list[float] = []
    missing: list[str] = []
    for lbl in input_labels:
        raw = fmp.get(ticker, pkey, lbl)
        if raw is None:
            missing.append(lbl)
            continue
        args.append(float(getattr(raw, "value", raw)))
    if missing:
        return SelfCheckVerdict(
            cell.cell_id, cell.canonical_label, pkey, "derived",
            float(cell.value), None, None, "SKIP",
            note=f"FMP missing inputs: {','.join(missing)}",
        )

    fmp_computed = fn(*args)
    rel, _factor, note = _best_match(float(cell.value), fmp_computed)
    status = "PASS" if rel <= _TIGHT_REL else "FAIL"
    annotation = note if (status == "PASS" and note) else ""
    return SelfCheckVerdict(
        cell.cell_id, cell.canonical_label, pkey, "derived",
        float(cell.value), fmp_computed, rel, status, note=annotation,
    )


def run_fmp_self_check(ledger: Ledger, fmp: GroundTruthSource) -> SelfCheckReport:
    """Run FMP-self-check across every cell in the ledger.

    For each cell, asks: 'is the value the LLM wrote what FMP would say,
    either as a direct lookup or as a recompute from FMP's own inputs?'
    """
    verdicts = [
        _check_one_cell(c, ledger.ticker, ledger, fmp)
        for c in ledger.cells
    ]
    return SelfCheckReport(ledger.skill, ledger.ticker, verdicts)


def render_markdown(report: SelfCheckReport) -> str:
    c = report.counts
    lines = [
        f"# FMP-self-check — {report.skill} {report.ticker}",
        "",
        f"**Pass rate (excl. SKIP):** {report.pass_rate:.1%}",
        f"**Counts:** PASS {c.get('PASS',0)} · FAIL {c.get('FAIL',0)} · SKIP {c.get('SKIP',0)}",
        "",
        "| metric | period | kind | stated | fmp | rel_err | status | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for v in report.verdicts:
        st = f"{v.stated:.4g}" if v.stated is not None else "—"
        fv = f"{v.fmp_value:.4g}" if v.fmp_value is not None else "—"
        re = f"{v.rel_err:.4f}" if v.rel_err is not None else "—"
        lines.append(
            f"| {v.canonical_label} | {v.period} | {v.kind} | {st} | {fv} | {re} | {v.status} | {v.note} |"
        )
    return "\n".join(lines) + "\n"
