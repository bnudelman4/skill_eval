"""One-command baseline grid -> scorecard (M5 definition of done).

Builds the grid from config, scores each sample (M3 invoke -> M4/M2 verify),
aggregates, and writes a JSON/MD/HTML scorecard. Loads .env with override=True
so headless runs bill the metered ANTHROPIC_API_KEY (see project memory on
headless auth), not the interactive session login.

Daloopa MCP is pending, so the gold reference is SEC XBRL (bootstrap_gold).

--dry-run wires a fixture-backed invoker + fixture ground truth so the full
pipeline produces a real scorecard offline (no agent, no network). Live mode is
wired but intentionally requires the converted skills (M6) and explicit opt-in.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finskill_eval.config import load_settings, load_universe
from finskill_eval.metrics import Metrics, aggregate
from finskill_eval.report import write_scorecard
from finskill_eval.runner.grid import GridSample, SampleRecord, score_sample
from finskill_eval.runner.invoke_skill import SkillRun
from finskill_eval.runner.parallel import run_grid

FIX = Path("fixtures")


class _FixtureGroundTruth:
    """Serves the M1 contract truths — offline gold for --dry-run."""

    def __init__(self):
        contract = json.loads((FIX / "expected_ledgers.json").read_text())
        self._d = {}
        for skill, payload in contract.items():
            if skill.startswith("_"):
                continue
            for c in payload["cells"]:
                self._d[(payload["ticker"], c["period"], c["canonical_label"])] = c["truth"]

    def get(self, ticker, period, label):
        return self._d.get((ticker, period, label))


def _fixture_invoke(skill, ticker, period, data_source, *, workdir, **kw):
    """Dry-run invoker: returns the matching fixture artifact, no agent call."""
    artifact = FIX / f"sample_{skill}.xlsx"
    return SkillRun(
        skill=skill, ticker=ticker, period=period, data_source=data_source,
        workdir=str(workdir), artifact_path=str(artifact) if artifact.exists() else None,
        cost_usd=0.0, latency_s=0.0, num_turns=0,
        exit_ok=artifact.exists(), raw_log_path=str(Path(workdir) / "dry.log"),
        activation_observed=True, skill_selected=skill,
    )


def run_baseline(
    *,
    dry_run: bool,
    results_dir: Path | None = None,
    tickers: list[str] | None = None,
    periods: list[str] | None = None,
    data_sources: list[str] | None = None,
) -> tuple[Metrics, dict]:
    settings = load_settings()
    results_dir = Path(results_dir or settings.execution.results_dir)

    if dry_run:
        skills = settings.skills.under_test
        tickers = tickers or ["AAPL"]
        periods = periods or ["FY2024"]
        data_sources = data_sources or ["fmp"]
        invoke_fn = _fixture_invoke
        ground_truth = _FixtureGroundTruth()
    else:
        from dotenv import load_dotenv

        from finskill_eval.groundtruth.sec_xbrl import SECXBRLClient
        from finskill_eval.runner.invoke_skill import run_skill

        load_dotenv(Path(".env"), override=True)  # metered key, not session login
        universe = load_universe()
        skills = settings.skills.under_test
        tickers = tickers or [t.symbol for t in universe.tickers]
        periods = periods or [f"FY{y}" for y in universe.periods.fiscal_years]
        data_sources = data_sources or ["fmp"]
        cik = {t.symbol: t.cik for t in universe.tickers}
        ground_truth = SECXBRLClient(
            user_agent=settings.ground_truth.sec_xbrl.user_agent, cik_lookup=cik
        )

        def invoke_fn(skill, ticker, period, data_source, *, workdir, **kw):
            return run_skill(
                skill, ticker, period, data_source, workdir=workdir,
                model=settings.pins.model_snapshot,
                timeout=settings.invocation.timeout_s,
                allowed_tools=settings.invocation.allowed_tools,
                bare=settings.invocation.bare,
            )

    grid = [
        GridSample(s, t, p, d)
        for s in skills for t in tickers for p in periods for d in data_sources
    ]

    workdir_root = results_dir / "workdirs"

    def score_fn(sample: GridSample) -> SampleRecord:
        return score_sample(
            sample, invoke_fn=invoke_fn, ground_truth=ground_truth,
            workdir_root=workdir_root,
        )

    records = run_grid(
        grid, score_fn,
        concurrency=settings.execution.max_concurrency,
        global_rps=settings.execution.global_fmp_rps,
        resume=settings.execution.resume,
        results_dir=results_dir / "samples",
    )

    metrics = aggregate(
        records,
        activation_min=settings.targets.activation_rate_min,
        selection_min=settings.targets.selection_accuracy_min,
        accuracy_min=settings.targets.accuracy_pass_rate_min,
        accuracy_eval_band=settings.targets.accuracy_eval_band,
    )
    paths = write_scorecard(metrics, results_dir)
    return metrics, paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the baseline grid -> scorecard.")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline: fixture artifacts + fixture gold, no agent/network")
    ap.add_argument("--results-dir", default=None)
    args = ap.parse_args()
    metrics, paths = run_baseline(dry_run=args.dry_run, results_dir=args.results_dir)
    print(f"samples={metrics.n_samples} "
          f"activation={metrics.activation_rate:.1%} "
          f"pass@{metrics.accuracy_eval_band}={metrics.accuracy_pass_rate:.1%}")
    for fmt, p in paths.items():
        print(f"  {fmt}: {p}")


if __name__ == "__main__":
    main()
