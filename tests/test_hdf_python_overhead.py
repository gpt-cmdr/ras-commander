"""Vectorized helpers of the mesh result readers: identical to what they replace.

Each helper replaces per-row Python work in a public reader. These tests
compare every helper with the code it replaces on inputs that exercise its
edge cases, and check that it declines the inputs it cannot prove equal (the
readers then keep the original path).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf.HdfMesh import HdfMesh
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
from ras_commander.hdf.HdfUtils import HdfUtils


def _reference_datetimes(timesteps, start, unit, round_to):
    """convert_timesteps_to_datetimes before the distinct-value conversion."""
    units = {"days": "D", "hours": "h"}
    return pd.DatetimeIndex(start + pd.to_timedelta(timesteps, unit=units[unit])).round(round_to)


def _same_index(a, b):
    assert a.dtype == b.dtype and a.freq == b.freq and a.name == b.name
    assert np.array_equal(a.asi8, b.asi8)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("unit", ["days", "hours"])
@pytest.mark.parametrize("round_to", ["100ms", "1ms", "1s"])
def test_summary_times_equal_the_elementwise_conversion(dtype, unit, round_to):
    rng = np.random.default_rng(7)
    steps = (rng.integers(0, 865, 20_000) / 288).astype(dtype)
    steps[::997] = np.nan
    steps[5] = -0.0
    steps[6] = 0.0
    steps[7] = -1.5
    start = datetime(2020, 1, 5, 13, 0, 0)
    _same_index(HdfUtils.convert_timesteps_to_datetimes(steps, start, unit, round_to),
                _reference_datetimes(steps, start, unit, round_to))


def test_distinct_time_axes_use_the_direct_conversion():
    steps = np.arange(10_000, dtype=np.float64) / 1440
    start = datetime(2021, 6, 1)
    _same_index(HdfUtils.convert_timesteps_to_datetimes(steps, start),
                _reference_datetimes(steps, start, "days", "100ms"))


def test_out_of_range_summary_times_keep_the_microsecond_fallback():
    steps = np.r_[np.zeros(5000), np.full(5000, 200_000.0)]
    result = HdfUtils.convert_timesteps_to_datetimes(steps, datetime(2000, 1, 1))
    assert str(result.dtype) == "datetime64[us]"
    assert result[-1].year > 2262


def test_repeated_text_infers_the_list_column_dtype():
    for size in (0, 1, 1000):
        listed = pd.DataFrame({"mesh_name": ["Area 1"] * size, "cell_id": range(size)})
        repeated = pd.DataFrame({"mesh_name": HdfUtils._repeat_text("Area 1", size),
                                 "cell_id": range(size)})
        pd.testing.assert_frame_equal(listed, repeated)
        assert listed.dtypes.equals(repeated.dtypes)


def test_no_chunks_keep_the_empty_list_columns():
    assert HdfMesh._join_chunks([]) == []
    assert HdfMesh._join_chunks([np.empty(0, object), np.empty(0, object)]) == []
    joined = HdfMesh._join_chunks([np.arange(2), np.arange(3)])
    assert joined.tolist() == [0, 1, 0, 1, 2]


def _geometry_frame(blocks):
    names, ids = [], []
    for name, count in blocks:
        names += [name] * count
        ids += list(range(count))
    return pd.DataFrame({"mesh_name": names, "face_id": ids,
                         "geometry": [f"{n}:{i}" for n, i in zip(names, ids)]})


def _values_frame(rows):
    return pd.DataFrame({"mesh_name": [n for n, _ in rows],
                         "face_id": np.array([i for _, i in rows], dtype=np.int64),
                         "value": np.arange(len(rows), dtype=np.float32)})


def _merged(values, geometry):
    return values.merge(geometry[["mesh_name", "face_id", "geometry"]],
                        on=["mesh_name", "face_id"], how="left")


@pytest.mark.parametrize("rows", [
    [("A", 0), ("A", 1), ("A", 2), ("B", 0), ("B", 1)],          # identical keys
    [("A", 0), ("A", 1), ("B", 0)],                              # leading rows per mesh (no ghosts)
    [("B", 1), ("A", 2), ("A", 0), ("B", 1)],                    # any order, repeated keys
])
def test_geometry_rows_give_the_left_merge(rows):
    geometry = _geometry_frame([("A", 3), ("B", 2)])
    values = _values_frame(rows)
    positions = HdfResultsMesh._geometry_rows(values, geometry, "face_id")
    assert positions is not None
    joined = values.reset_index(drop=True)
    joined["geometry"] = geometry["geometry"].to_numpy()[positions]
    pd.testing.assert_frame_equal(joined, _merged(values, geometry))


@pytest.mark.parametrize("geometry, rows", [
    (_geometry_frame([("A", 3)]), [("A", 3)]),                   # key not in geometry
    (_geometry_frame([("A", 3)]), [("C", 0)]),                   # mesh not in geometry
    (_geometry_frame([("A", 2), ("B", 1), ("A", 1)]), [("A", 0)]),  # mesh split in two blocks
    (_geometry_frame([("A", 3)]).iloc[[0, 2, 1]].reset_index(drop=True), [("A", 0)]),  # IDs out of order
    (_geometry_frame([("A", 3)]).iloc[[0, 0, 1]].reset_index(drop=True), [("A", 0)]),  # duplicate key
])
def test_geometry_rows_decline_what_only_the_merge_handles(geometry, rows):
    assert HdfResultsMesh._geometry_rows(_values_frame(rows), geometry, "face_id") is None


native = pytest.importorskip("ras_commander.hdf.HdfFluvialNative", exc_type=ImportError)


def _loop_edge_faces(meshes):
    edge_faces = {}
    for mesh_id, (low, high, faces, coordinates, starts, stops) in meshes.items():
        for k in range(len(faces)):
            key = (mesh_id, int(low[k]), int(high[k]))
            coords = tuple(tuple(map(float, c)) for c in coordinates[starts[k]:stops[k]])
            edge_faces.setdefault(key, []).append((int(faces[k]), coords))
    return edge_faces


def test_edge_faces_mapping_equals_the_loop_dict():
    rng = np.random.default_rng(3)
    meshes = {}
    for mesh_id in (0, 2):
        count = 400
        low = rng.integers(0, 50, count)
        high = low + rng.integers(0, 5, count)
        faces = np.sort(rng.choice(10_000, count, replace=False))
        sizes = rng.integers(2, 5, count)
        stops = np.cumsum(sizes)
        starts = stops - sizes
        coordinates = rng.random((int(stops[-1]), 2))
        meshes[mesh_id] = (low, high, faces, coordinates, starts, stops)
    mapping = native._EdgeFaces()
    for mesh_id, (low, high, faces, coordinates, starts, stops) in meshes.items():
        mapping.add_mesh(mesh_id, low, high, faces, coordinates, starts, stops)
    # A mesh written by the loop itself goes through setdefault.
    mapping.setdefault((1, 4, 7), []).append((9, ((0.0, 1.0), (2.0, 3.0))))
    expected = _loop_edge_faces({0: meshes[0]})
    expected[(1, 4, 7)] = [(9, ((0.0, 1.0), (2.0, 3.0)))]
    expected.update(_loop_edge_faces({2: meshes[2]}))
    assert list(mapping) == list(expected)
    assert len(mapping) == len(expected)
    for key, value in expected.items():
        assert key in mapping and mapping[key] == value
    for missing in ((0, 999, 1000), (5, 1, 2), (0, 3, 2), "x"):
        assert missing not in mapping
        with pytest.raises(KeyError):
            mapping[missing]


def _loop_peaks(sources, meshes, peaks):
    peak_map = {(str(m), int(c)): t for m, c, t in
                peaks[["mesh_name", "cell_id", "maximum_water_surface_time"]].itertuples(index=False, name=None)}
    pairs = [native.integer_milliseconds(peak_map.get((meshes[m], row))) for m, row in sources]
    return [value for value, _ in pairs], [valid for _, valid in pairs]


@pytest.mark.parametrize("unit", ["ns", "us"])
def test_peak_times_equal_the_per_cell_conversion(unit):
    times = pd.to_datetime(["2020-01-01 00:00:00.100", None, "2020-01-03 12:00:00.000",
                            "2020-01-02 06:30:00.001", "1969-12-31 23:59:59.900"]).astype(f"datetime64[{unit}]")
    peaks = pd.DataFrame({"mesh_name": pd.array(["A", "A", "B", "B", "B"], dtype=HdfUtils._TEXT_DTYPE),
                          "cell_id": np.array([0, 1, 0, 2, 3], dtype=np.int64),
                          "maximum_water_surface_time": times})
    meshes = ["A", "B"]
    sources = [(0, 0), (0, 1), (0, 2), (1, 2), (1, 0), (1, 1), (1, 3)]
    assert native._fast_peak_times(sources, meshes, peaks) == _loop_peaks(sources, meshes, peaks)
    assert native._fast_peak_times(sources, meshes, None) == ([0] * 7, [False] * 7)


def test_sub_millisecond_peaks_raise_like_the_loop():
    peaks = pd.DataFrame({"mesh_name": ["A"], "cell_id": [0],
                          "maximum_water_surface_time": pd.to_datetime(["2020-01-01 00:00:00.0001"])})
    with pytest.raises(ValueError, match="sub-millisecond"):
        native._fast_peak_times([(0, 0)], ["A"], peaks)
    # Not looked up: the loop never converts it either.
    assert native._fast_peak_times([(0, 1)], ["A"], peaks) == ([0], [False])


def test_peak_times_decline_timezone_aware_columns():
    peaks = pd.DataFrame({"mesh_name": ["A"], "cell_id": [0],
                          "maximum_water_surface_time": pd.to_datetime(["2020-01-01"]).tz_localize("UTC")})
    assert native._fast_peak_times([(0, 0)], ["A"], peaks) is None


def _reference_trim(values, time_slice):
    active = values != 0 if values.ndim == 1 else np.any(values != 0, axis=1)
    positions = np.flatnonzero(active)
    if not len(positions):
        return values, time_slice
    first, last = int(positions[0]), int(positions[-1])
    return (values[first:last + 1],
            slice(time_slice.start + first * time_slice.step,
                  time_slice.start + (last + 1) * time_slice.step, time_slice.step))


@pytest.mark.parametrize("rows, active", [
    (0, []), (1, []), (1, [0]), (10, []), (10, [0]), (10, [9]), (10, [3, 6]),
    (5000, [4999]), (5000, [0, 2]), (5000, [1234, 3000]), (5000, []),
])
@pytest.mark.parametrize("width", [1, 7, 5000])
def test_trim_finds_the_same_active_rows(rows, active, width):
    from ras_commander.hdf.HdfResultView import HdfResultView

    values = np.zeros((rows, width), dtype=np.float32)
    for row in active:
        values[row, width // 2] = np.nan if row % 2 else -1.0
    time_slice = slice(3, 3 + 2 * rows, 2)
    got, got_slice = HdfResultView._trim_materialized(values, time_slice)
    want, want_slice = _reference_trim(values, time_slice)
    assert got_slice == want_slice
    assert got.shape == want.shape and np.array_equal(got, want, equal_nan=True)
