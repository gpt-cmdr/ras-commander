"""Independent interval-vector and contract checks for balanced frequency storms."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ras_commander.precip.FrequencyStormDdf import FrequencyStormDdf


CASES = json.loads((Path(__file__).parent / "fixtures/balanced_hyetograph/verified_cases.json").read_text())


@pytest.mark.parametrize("case", CASES)
def test_full_reference_vector_and_interval_boundaries(case):
    durations = [float(x) for x in case["depth_duration_inches"]]
    actual = FrequencyStormDdf.generate_hyetograph(
        list(case["depth_duration_inches"].values()), durations,
        peak_position_percent=case["peak_position_pct"], simulation_duration_hours=120)
    values = actual.incremental_depth.to_numpy()
    serialized = np.round(values[1:289], 11).astype("<f8").tobytes()
    assert hashlib.sha256(serialized).hexdigest() == case["reference_quantized_11_decimal_sha256"]
    assert len(actual) == 1441 and values[0] == 0
    assert np.all(values[289:] == 0)
    np.testing.assert_allclose(actual.hour, np.arange(1441)/12, rtol=0, atol=1e-12)
    np.testing.assert_allclose(actual.cumulative_depth, np.cumsum(values), rtol=0, atol=1e-12)
    assert values.sum() == pytest.approx(case["expected_total_inches"], abs=1e-12)
    for index, expected in case["reference_incremental_samples"].items():
        assert values[int(index)+1] == pytest.approx(expected, abs=2e-13)


@pytest.mark.parametrize("kwargs", [
    {"peak_position_percent": np.nan}, {"peak_position_percent": 25},
    {"area_reduction_method": "unknown"}, {"storm_area_sqmi": 1},
    {"area_reduction_method": "TP-40"},
    {"area_reduction_method": "TP-40", "storm_area_sqmi": -1},
    {"area_reduction_method": "TP-40", "storm_area_sqmi": 401},
    {"area_reduction_method": "TP-40", "storm_area_sqmi": np.nan},
])
def test_reject_ambiguous_or_unsupported_settings(kwargs):
    case = CASES[0]
    with pytest.raises(ValueError):
        FrequencyStormDdf.generate_hyetograph(
            list(case["depth_duration_inches"].values()),
            [float(x) for x in case["depth_duration_inches"]], **kwargs)


def test_zero_area_identity_and_reduced_total_is_not_renormalized():
    case = CASES[0]
    depths = list(case["depth_duration_inches"].values())
    durations = [float(x) for x in case["depth_duration_inches"]]
    plain = FrequencyStormDdf.generate_hyetograph(depths, durations)
    zero = FrequencyStormDdf.generate_hyetograph(depths, durations,
        area_reduction_method="TP-40", storm_area_sqmi=0)
    np.testing.assert_array_equal(plain.incremental_depth, zero.incremental_depth)
    reduced = FrequencyStormDdf.generate_hyetograph(depths, durations,
        area_reduction_method="TP-40", storm_area_sqmi=100)
    assert 0 < reduced.incremental_depth.sum() < depths[-1]
    assert reduced.incremental_depth.sum() == pytest.approx(reduced.attrs["areal_storm_depth_inches"], abs=1e-12)
    assert reduced.attrs["area_reduction_applied"] is True
    factors = reduced.attrs["area_reduction_factors"]
    assert 0 < factors[0] < 1
    assert factors[:4] == [factors[3]] * 4


def test_area_adjustment_preserves_nondecreasing_equal_point_depths():
    actual = FrequencyStormDdf.generate_hyetograph([1]*8, FrequencyStormDdf.DURATIONS_MINUTES,
            area_reduction_method="TP-40", storm_area_sqmi=400)
    assert np.all(actual.incremental_depth >= 0)
    assert np.all(np.diff(actual.cumulative_depth) >= 0)
