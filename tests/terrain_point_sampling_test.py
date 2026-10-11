"""Exact supplied-coordinate and fail-closed native point readback contracts."""

import numpy as np
import pytest

from ras_commander._terrain_point_sampling import (
    _point_elevation_batches,
    iter_point_elevations,
)


def test_layer_loaded_once_coordinates_preserved_and_results_ordered(
    tmp_path, monkeypatch
):
    from ras_commander import _terrain_point_sampling as sampling

    mapper = tmp_path / "model.rasmap"
    mapper.write_text("native registered terrain")
    first = np.array([[np.nextafter(1.0, 2.0), -0.0], [1.0, 2.0]], dtype=np.float64)
    second = first[::-1].copy()
    original = [batch.tobytes() for batch in (first, second)]
    loads, received = [], []

    def load(*args):
        loads.append(args)

        def evaluate(coordinates):
            received.append(coordinates.tobytes())
            return coordinates[:, 1] + 100

        return evaluate

    monkeypatch.setattr(sampling, "_load_native_point_reader", load)
    values = list(
        iter_point_elevations(mapper, "Terrain", [first, second], 10.0, True, [-9999.0])
    )
    assert loads == [(mapper.resolve(), "Terrain", True, 10.0)]
    assert received == original
    assert [batch.tobytes() for batch in (first, second)] == original
    assert [v.tolist() for v in values] == [[100.0, 102.0], [102.0, 100.0]]
    assert all(v.dtype == np.float32 for v in values)


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        [1.0],
        [1.0, np.nan],
        [1.0, np.inf],
        [1.0, -9999.0],
        [1.0, -np.finfo(np.float32).max],
    ],
)
def test_missing_or_invalid_native_values_never_fall_back(result):
    points = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    with pytest.raises(RuntimeError):
        list(_point_elevation_batches([points], lambda coordinates: result, [-9999.0]))


@pytest.mark.parametrize(
    "points",
    [
        np.ones((2, 2), dtype=np.float32),
        np.ones((2, 3)),
        np.empty((0, 2)),
        np.array([[np.nan, 1.0]]),
    ],
)
def test_point_contract_rejects_coercion_empty_or_nonfinite_inputs(points):
    def never_evaluate(coordinates):
        pytest.fail("invalid coordinates reached native sampling")

    with pytest.raises(ValueError):
        list(_point_elevation_batches([points], never_evaluate, [-9999.0]))
