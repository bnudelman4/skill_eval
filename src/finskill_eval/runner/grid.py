"""Evaluation grid: sample definitions and per-sample scoring (M5).

A GridSample is one (skill x ticker x period x data_source). score_sample ties
the M3 invocation -> M2/M4 parse+verify pipeline into a SampleRecord. All
external work (agent invocation, ground truth) is injected so this is testable
offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from finskill_eval.extract.llm_extract import extract_ledger
from finskill_eval.groundtruth.base import GroundTruthSource
from finskill_eval.parse_xlsx import parse as parse_xlsx  # legacy/deterministic option
from finskill_eval.runner.invoke_skill import SkillRun
from finskill_eval.verify import verify


@dataclass(frozen=True)
class GridSample:
    skill: str
    ticker: str
    period: str
    data_source: str

    @property
    def sample_id(self) -> str:
        return f"{self.skill}__{self.ticker}__{self.period}__{self.data_source}"


@dataclass
class SampleRecord:
    skill: str
    ticker: str
    period: str
    data_source: str
    activation_observed: bool
    skill_selected: Optional[str]
    exit_ok: bool
    cost_usd: float
    latency_s: float
    num_turns: int
    verdicts: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def sample_id(self) -> str:
        return f"{self.skill}__{self.ticker}__{self.period}__{self.data_source}"


InvokeFn = Callable[..., SkillRun]
ParseFn = Callable[[str, str, str], object]


def build_grid(
    *,
    skills: list[str],
    tickers: list[str],
    periods: list[str],
    data_sources: list[str],
) -> list[GridSample]:
    return [
        GridSample(skill, ticker, period, source)
        for skill in skills
        for ticker in tickers
        for period in periods
        for source in data_sources
    ]


def _verdict_to_dict(v) -> dict:
    return {
        "canonical_label": v.canonical_label,
        "period": v.period,
        "cell_type": v.cell_type,
        "kind": v.kind,
        "status": v.status,
        "band": v.band,
        "rel_err": v.rel_err,
    }


def score_sample(
    sample: GridSample,
    *,
    invoke_fn: InvokeFn,
    ground_truth: GroundTruthSource,
    workdir_root: Path,
    parse_fn: Optional[ParseFn] = None,
) -> SampleRecord:
    # Default ingestion is Option C (LLM extraction): robust to free-form skill
    # layouts with no per-layout code. parse_xlsx remains injectable as the
    # deterministic fallback. Tests inject their own parse_fn.
    parse_fn = parse_fn or (lambda path, skill, ticker: extract_ledger(path, skill=skill, ticker=ticker))
    workdir = Path(workdir_root) / sample.sample_id

    run = invoke_fn(
        sample.skill, sample.ticker, sample.period, sample.data_source,
        workdir=workdir,
    )

    base = dict(
        skill=sample.skill, ticker=sample.ticker, period=sample.period,
        data_source=sample.data_source,
        activation_observed=run.activation_observed,
        skill_selected=run.skill_selected, exit_ok=run.exit_ok,
        cost_usd=run.cost_usd, latency_s=run.latency_s, num_turns=run.num_turns,
    )

    if not run.exit_ok or not run.artifact_path:
        return SampleRecord(**base, verdicts=[], error="run failed or produced no artifact")

    try:
        ledger = parse_fn(run.artifact_path, sample.skill, sample.ticker)
        report = verify(ledger, ground_truth)
        verdicts = [_verdict_to_dict(v) for v in report.verdicts]
        return SampleRecord(**base, verdicts=verdicts)
    except Exception as exc:  # parsing/verification failure is a sample-level error
        return SampleRecord(**base, verdicts=[], error=f"{type(exc).__name__}: {exc}")


def record_to_dict(rec: SampleRecord) -> dict:
    return asdict(rec)
