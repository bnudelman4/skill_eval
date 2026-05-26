"""M6 entrypoint: generate FMP skills, run the A/B, emit a comparison scorecard.

Stage 3 of the experiment. Two arms scored by the same deterministic verifier:
  - baseline : Daloopa skills, data_source=daloopa   (gold-authored reference)
  - candidate: converted FMP skills, data_source=fmp

Daloopa MCP is pending, so:
  * --dry-run wires both arms from the M1 fixtures (pipeline smoke; the baseline
    arm is synthetic until a Daloopa key lands) and writes a real comparison
    scorecard fully offline.
  * live mode is wired but requires the converted skills + agent runs + explicit
    opt-in; with Daloopa pending the baseline arm is unavailable, so live A/B is
    blocked until the key arrives (candidate-vs-SEC runs via run_baseline today).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from finskill_eval.config import load_settings
from finskill_eval.conversion.compare import Comparison, compare_arms, write_comparison
from finskill_eval.conversion.convert_skill import convert_all

_DALOOPA_SRC = Path("skills/daloopa")
_FMP_OUT = Path("skills/fmp")
_SKILL_DIRS = ["tearsheet", "comps", "capital-allocation"]


def generate_fmp_skills(src=_DALOOPA_SRC, dest=_FMP_OUT) -> list[Path]:
    return convert_all(src, dest, skills=_SKILL_DIRS)


def _dry_run_arms(settings):
    """Build both arms offline from fixtures. The candidate arm degrades one
    cell so the comparison path exercises a non-zero, signed delta."""
    import json

    from finskill_eval.runner.grid import SampleRecord

    contract = json.loads(Path("fixtures/expected_ledgers.json").read_text())
    skills = [s for s in contract if not s.startswith("_")]

    def verdicts_for(skill, degrade):
        cells = contract[skill]["cells"]
        out = []
        for i, c in enumerate(cells):
            status = c.get("expected_status", "PASS")
            band = c.get("expected_band", "tight")
            if degrade and i == 0 and status == "PASS":  # one cell worse on candidate
                status, band = "FAIL", "tight"
            out.append({
                "canonical_label": c["canonical_label"], "period": c["period"],
                "cell_type": c["cell_type"], "kind": c.get("kind", "direct"),
                "status": status, "band": band, "rel_err": 0.0,
            })
        return out

    def arm(source, degrade):
        recs = []
        for skill in skills:
            recs.append(SampleRecord(
                skill=skill, ticker=contract[skill]["ticker"], period="FY2024",
                data_source=source, activation_observed=True, skill_selected=skill,
                exit_ok=True, cost_usd=0.0, latency_s=0.0, num_turns=0,
                verdicts=verdicts_for(skill, degrade),
            ))
        return recs

    return arm("daloopa", degrade=False), arm("fmp", degrade=True)


def run_conversion_ab(*, dry_run: bool, results_dir: Path | None = None) -> tuple[Comparison, dict]:
    settings = load_settings()
    results_dir = Path(results_dir or settings.execution.results_dir) / "conversion"
    generate_fmp_skills()

    if dry_run:
        baseline, candidate = _dry_run_arms(settings)
    else:  # pragma: no cover - requires Daloopa gold + agent runs
        raise NotImplementedError(
            "Live A/B needs the Daloopa baseline arm (MCP key pending). Run "
            "run_baseline for the FMP-vs-SEC candidate scorecard in the meantime."
        )

    comp = compare_arms(
        baseline, candidate,
        band=settings.targets.production_acceptable_band,
        production_acceptable=settings.targets.production_acceptable_pass_rate,
    )
    paths = write_comparison(comp, results_dir)
    return comp, paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate FMP skills + run conversion A/B.")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline: fixture-backed arms, no agent/network")
    ap.add_argument("--results-dir", default=None)
    args = ap.parse_args()
    comp, paths = run_conversion_ab(dry_run=args.dry_run, results_dir=args.results_dir)
    print(f"pairs={comp.n_pairs} baseline={comp.baseline_pass_rate:.1%} "
          f"candidate={comp.candidate_pass_rate:.1%} "
          f"delta={comp.mean_delta:+.1%} acceptable={comp.production_acceptable}")
    for fmt, p in paths.items():
        print(f"  {fmt}: {p}")


if __name__ == "__main__":
    main()
