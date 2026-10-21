"""Scalar and full-vector checks for the bounded TP-40 reduction relation."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from ras_commander.precip.FrequencyStormDdf import FrequencyStormDdf
from ras_commander.precip.Tp40Reduction import Tp40Reduction


VERIFIED_CASES = json.loads(
    (Path(__file__).parent / "fixtures/balanced_hyetograph/tp40_verified_cases.json").read_text()
)


@pytest.mark.parametrize(
    ("duration_minutes", "expected_coefficient"),
    [
        (5.0, 0.48),
        (10.0, 0.48),
        (15.0, 0.48),
        (30.0, 0.48),
        (60.0, 0.35),
        (120.0, 0.2611223134780174),
        (180.0, 0.22),
        (360.0, 0.17),
        (720.0, 0.1236931687685298),
        (1440.0, 0.09),
    ],
)
def test_hms_compatibility_duration_coefficients_follow_log_log_interpolation(
    duration_minutes, expected_coefficient
):
    area_sqmi = 10.0
    observed = Tp40Reduction.factor(duration_minutes, area_sqmi)
    expected = 1.0 - expected_coefficient * (1.0 - math.exp(-0.015 * area_sqmi))
    assert observed == pytest.approx(expected, abs=1e-15)


def test_zero_area_is_an_identity_multiplier():
    for duration_minutes in (5.0, 30.0, 120.0, 1440.0):
        assert Tp40Reduction.factor(duration_minutes, 0.0) == 1.0


@pytest.mark.parametrize(
    ("duration_minutes", "storm_area_sqmi"),
    [
        (4.999, 1.0),
        (1440.001, 1.0),
        (float("nan"), 1.0),
        (60.0, -0.001),
        (60.0, 400.001),
        (60.0, float("inf")),
    ],
)
def test_rejects_unqualified_duration_or_area(duration_minutes, storm_area_sqmi):
    with pytest.raises(ValueError):
        Tp40Reduction.factor(duration_minutes, storm_area_sqmi)


@pytest.mark.parametrize("case", VERIFIED_CASES, ids=lambda case: case["case"])
def test_full_hyetograph_matches_independent_tp40_reference_vector(case):
    """Check reduction, interpolation, and alternating placement together."""
    result = FrequencyStormDdf.generate_hyetograph(
        case["depth_duration_inches"],
        case["durations_minutes"],
        peak_position_percent=case["peak_position_percent"],
        area_reduction_method="TP-40",
        storm_area_sqmi=case["storm_area_sqmi"],
    )
    vector = result.incremental_depth.to_numpy()[1:289]
    digest = hashlib.sha256(np.round(vector, 11).astype("<f8").tobytes()).hexdigest()
    assert digest == case["reference_quantized_11_decimal_sha256"]
    assert vector.sum() == pytest.approx(case["expected_total_inches"], abs=1e-12)
    for index, expected in case["reference_incremental_samples"].items():
        assert vector[int(index)] == pytest.approx(expected, abs=2e-13)
