"""M7/M5: per-skill effect size with CI."""

import pytest

from finskill_eval.metrics import effect_size


def test_zero_and_singleton():
    assert effect_size([]).n == 0
    one = effect_size([0.05])
    assert one.n == 1 and one.mean_delta == pytest.approx(0.05)


def test_clear_positive_delta_is_significant():
    es = effect_size([0.10, 0.12, 0.09, 0.11, 0.10, 0.10])
    assert es.mean_delta > 0
    assert es.ci95_low > 0          # CI excludes zero
    assert es.significant is True
    assert es.cohens_d > 0


def test_noisy_delta_not_significant():
    es = effect_size([0.1, -0.1, 0.05, -0.08, 0.02, -0.04])
    assert es.ci95_low < 0 < es.ci95_high
    assert es.significant is False


def test_ci_brackets_mean():
    es = effect_size([1.0, 2.0, 3.0, 4.0])
    assert es.ci95_low < es.mean_delta < es.ci95_high
    assert es.mean_delta == pytest.approx(2.5)
