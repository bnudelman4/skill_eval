"""M2.2: the banded comparator. PURE — zero I/O.

compare() returns the A3 band + its status (PASS/WARN/FLAG) and the relative
error. FAIL is NOT a band — it is a verify-level verdict, so compare never
returns it.
"""

import math

import pytest

from finskill_eval.tolerance import Bands, compare


@pytest.fixture
def bands() -> Bands:
    return Bands.default()


@pytest.mark.parametrize(
    "pred, truth, expected_band, expected_status",
    [
        (100.0, 100.0, "exact", "PASS"),              # exactly equal
        (100.0001, 100.0, "tight", "PASS"),           # rel 1e-6
        (100.1, 100.0, "tight", "PASS"),              # rel == 0.001 boundary
        (100.11, 100.0, "xvendor_standard", "PASS"),  # just above tight
        (100.5, 100.0, "xvendor_standard", "PASS"),   # rel == 0.005 boundary
        (100.51, 100.0, "xvendor_liberal", "PASS"),   # just above standard
        (101.0, 100.0, "xvendor_liberal", "PASS"),    # rel == 0.01 boundary
        (101.01, 100.0, "materiality", "WARN"),       # just above liberal
        (103.0, 100.0, "materiality", "WARN"),        # rel 3%
        (105.0, 100.0, "materiality", "WARN"),        # rel == 0.05 boundary
        (106.0, 100.0, "disagreement", "FLAG"),       # > 5%
        (140.0, 100.0, "disagreement", "FLAG"),       # way off
    ],
)
def test_band_boundaries(bands, pred, truth, expected_band, expected_status):
    r = compare(pred, truth, bands=bands)
    assert r.band == expected_band
    assert r.status == expected_status


def test_relative_error_is_symmetric_in_magnitude(bands):
    # under- and over-shoot by the same fraction land in the same band
    assert compare(97.0, 100.0, bands=bands).band == "materiality"
    assert compare(103.0, 100.0, bands=bands).band == "materiality"


def test_relative_error_value(bands):
    r = compare(110.0, 100.0, bands=bands)
    assert math.isclose(r.rel_err, 0.10, rel_tol=1e-9)


def test_near_zero_truth_equal_is_exact(bands):
    r = compare(0.0, 0.0, bands=bands)
    assert r.band == "exact"
    assert r.status == "PASS"


def test_near_zero_truth_nonzero_pred_flags(bands):
    # truth ~0 but pred materially nonzero -> relative error meaningless -> FLAG
    r = compare(5.0, 0.0, bands=bands)
    assert r.band == "disagreement"
    assert r.status == "FLAG"


def test_compare_is_pure_no_settings_import():
    # default bands require no file/network access
    b = Bands.default()
    assert b.bands[0].name == "exact"
    assert b.overflow.status == "FLAG"
