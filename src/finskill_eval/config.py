"""Load + validate settings/universe/locks. Secrets come from env, never yaml.

Fails loudly (pydantic ValidationError / ValueError) on missing keys, malformed
bands, or unresolved REPLACE_WITH_* pins. This is intentional: a misconfigured
run must not silently proceed.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Repo root = three parents up from this file (src/finskill_eval/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

Status = Literal["PASS", "WARN", "FLAG"]
_PLACEHOLDER_PREFIX = "REPLACE_WITH"


def _reject_placeholder(value: str, field_name: str) -> str:
    if value.strip().upper().startswith(_PLACEHOLDER_PREFIX):
        raise ValueError(
            f"{field_name} is still the placeholder {value!r}; "
            "fill in a real value before running."
        )
    return value


# --------------------------------------------------------------------------- #
# settings.yaml
# --------------------------------------------------------------------------- #
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Strict):
    project: str
    config_version: int
    citations_reverified: bool


class Pins(_Strict):
    model_snapshot: str
    skill_repo_sha: str

    @field_validator("model_snapshot", "skill_repo_sha")
    @classmethod
    def _no_placeholder(cls, v: str, info) -> str:
        return _reject_placeholder(v, info.field_name)


class Band(_Strict):
    name: str
    max_rel: float = Field(ge=0.0)
    status: Status


class OverflowBand(_Strict):
    name: str
    status: Status


class ToleranceConfig(_Strict):
    near_zero_floor: float = Field(gt=0.0)
    abs_floor: float = Field(gt=0.0)
    bands: list[Band] = Field(min_length=1)
    overflow_band: OverflowBand

    @model_validator(mode="after")
    def _bands_ascending(self) -> "ToleranceConfig":
        rels = [b.max_rel for b in self.bands]
        if rels != sorted(rels):
            raise ValueError(
                f"tolerance.bands must be ordered tightest-first (ascending "
                f"max_rel); got {rels}"
            )
        if len({b.name for b in self.bands}) != len(self.bands):
            raise ValueError("tolerance.bands names must be unique")
        return self


class Targets(_Strict):
    activation_rate_min: float = Field(ge=0.0, le=1.0)
    selection_accuracy_min: float = Field(ge=0.0, le=1.0)
    accuracy_pass_rate_min: float = Field(ge=0.0, le=1.0)
    accuracy_eval_band: str
    production_acceptable_pass_rate: float = Field(ge=0.0, le=1.0)
    production_acceptable_band: str


class Budgets(_Strict):
    cost_per_run_warn_usd: float = Field(gt=0.0)
    latency_p95_warn_s: float = Field(gt=0.0)
    cost_per_run_hard_cap_usd: float = Field(gt=0.0)


class Skills(_Strict):
    under_test: list[str] = Field(min_length=1)
    data_sources: list[str] = Field(min_length=1)
    max_skills_per_request: int = Field(gt=0, le=8)


class Invocation(_Strict):
    bare: bool
    output_format: str
    allowed_tools: list[str]
    max_turns: int = Field(gt=0)
    timeout_s: int = Field(gt=0)
    live_smoke_env_flag: str


class SnapshotConfig(_Strict):
    enabled: bool
    dir: str
    freeze_on_first_pull: bool


class FmpConfig(_Strict):
    base_url: str
    rate_limit_rps: float = Field(gt=0.0)
    max_retries: int = Field(ge=0)
    denomination_sanity_check: bool


class SecXbrlConfig(_Strict):
    user_agent: str
    company_facts_url: str


class DaloopaConfig(_Strict):
    request_scope: str


class GroundTruth(_Strict):
    gold: str
    anchor: str
    candidate: str
    bootstrap_gold: str
    snapshots: SnapshotConfig
    fmp: FmpConfig
    sec_xbrl: SecXbrlConfig
    daloopa: DaloopaConfig


class Execution(_Strict):
    max_concurrency: int = Field(gt=0)
    resume: bool
    global_fmp_rps: float = Field(gt=0.0)
    results_dir: str


class Reporting(_Strict):
    formats: list[str]
    breakdowns: list[str]
    list_flag_cells: bool
    emit_interpretation_notes: bool


class Optimization(_Strict):
    enabled: bool
    train_test_split: float = Field(gt=0.0, lt=1.0)
    runs_per_query: int = Field(gt=0)
    max_iterations: int = Field(gt=0)
    select_by: str
    optimize_targets: list[str]
    # M7 / SkillOpt guardrails (defaults keep existing configs valid)
    max_edits_per_step: int = Field(default=6, ge=1, le=20)
    description_token_cap: int = Field(default=920, gt=0)
    accuracy_nonregression_guard: bool = True
    protected_sections: bool = True


class Settings(_Strict):
    meta: Meta
    pins: Pins
    tolerance: ToleranceConfig
    targets: Targets
    budgets: Budgets
    skills: Skills
    invocation: Invocation
    ground_truth: GroundTruth
    execution: Execution
    reporting: Reporting
    optimization: Optimization

    @model_validator(mode="after")
    def _cross_checks(self) -> "Settings":
        band_names = {b.name for b in self.tolerance.bands}
        for fld in ("accuracy_eval_band", "production_acceptable_band"):
            val = getattr(self.targets, fld)
            if val not in band_names:
                raise ValueError(
                    f"targets.{fld}={val!r} is not a defined tolerance band "
                    f"{sorted(band_names)}"
                )
        if self.ground_truth.candidate == self.ground_truth.gold:
            raise ValueError(
                "ground_truth.candidate must never equal gold (candidate is "
                "the source under test)."
            )
        return self


# --------------------------------------------------------------------------- #
# universe.yaml
# --------------------------------------------------------------------------- #
class Periods(_Strict):
    kind: Literal["annual", "quarterly"]
    fiscal_years: list[int] = Field(min_length=1)


class TickerSpec(_Strict):
    symbol: str
    name: str
    cik: str
    fiscal_year_end_month: int = Field(ge=1, le=12)

    @field_validator("cik")
    @classmethod
    def _cik_zero_padded(cls, v: str) -> str:
        if not (v.isdigit() and len(v) == 10):
            raise ValueError(f"cik must be a 10-digit zero-padded string; got {v!r}")
        return v


class Universe(_Strict):
    periods: Periods
    tickers: list[TickerSpec] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# skills.lock.yaml
# --------------------------------------------------------------------------- #
class LockRepo(_Strict):
    url: str
    ref: str
    sha: str
    reviewed_date: str
    reviewed_by: str
    manual_review_complete: bool

    @field_validator("sha")
    @classmethod
    def _no_placeholder(cls, v: str, info) -> str:
        return _reject_placeholder(v, info.field_name)


class LockSkill(_Strict):
    skill_md: str
    allowed_tools: list[str] | None = None


class SkillsLock(_Strict):
    repo: LockRepo
    shared_refs: list[str]
    skills: dict[str, LockSkill]


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return data


@lru_cache(maxsize=1)
def load_settings(path: Path | None = None) -> Settings:
    return Settings.model_validate(_read_yaml(path or CONFIG_DIR / "settings.yaml"))


@lru_cache(maxsize=1)
def load_universe(path: Path | None = None) -> Universe:
    return Universe.model_validate(_read_yaml(path or CONFIG_DIR / "universe.yaml"))


@lru_cache(maxsize=1)
def load_skills_lock(path: Path | None = None) -> SkillsLock:
    return SkillsLock.model_validate(_read_yaml(path or CONFIG_DIR / "skills.lock.yaml"))


# --------------------------------------------------------------------------- #
# Secrets — env only, never yaml. Raise if a required secret is absent.
# --------------------------------------------------------------------------- #
def get_secret(name: str, *, required: bool = True) -> str | None:
    val = os.environ.get(name)
    if required and not val:
        raise RuntimeError(
            f"required secret {name} is not set in the environment "
            "(load it from your gitignored .env)."
        )
    return val


if __name__ == "__main__":
    from rich import print as rprint

    rprint(load_settings())
    rprint(load_universe())
    rprint(load_skills_lock())
