"""M0: config loads, validates, and fails loudly on bad input."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from finskill_eval.config import (
    Settings,
    load_settings,
    load_skills_lock,
    load_universe,
)


def test_settings_load_and_pins_resolved():
    s = load_settings()
    assert s.meta.project == "finskill-eval"
    assert not s.pins.model_snapshot.upper().startswith("REPLACE_WITH")
    assert not s.pins.skill_repo_sha.upper().startswith("REPLACE_WITH")


def test_universe_grid():
    u = load_universe()
    assert len(u.tickers) == 8
    assert u.periods.fiscal_years == [2022, 2023, 2024, 2025]
    # WMT is the Jan fiscal-year-end name kept in the "clean" set.
    assert any(t.symbol == "WMT" and t.fiscal_year_end_month == 1 for t in u.tickers)


def test_skills_lock_sha_pinned():
    lock = load_skills_lock()
    assert len(lock.repo.sha) == 40
    assert set(lock.skills) == {"tearsheet", "comps", "capital_allocation"}


def test_placeholder_pin_is_rejected():
    base = yaml.safe_load((Path("config/settings.yaml")).read_text())
    base["pins"]["model_snapshot"] = "REPLACE_WITH_DATED_SNAPSHOT"
    with pytest.raises(ValidationError, match="placeholder"):
        Settings.model_validate(base)


def test_candidate_cannot_equal_gold():
    base = yaml.safe_load((Path("config/settings.yaml")).read_text())
    base["ground_truth"]["gold"] = "fmp"  # same as candidate
    with pytest.raises(ValidationError, match="candidate must never equal gold"):
        Settings.model_validate(base)


def test_bands_must_be_ascending():
    base = yaml.safe_load((Path("config/settings.yaml")).read_text())
    base["tolerance"]["bands"][0]["max_rel"] = 0.99  # break ordering
    with pytest.raises(ValidationError, match="tightest-first"):
        Settings.model_validate(base)
