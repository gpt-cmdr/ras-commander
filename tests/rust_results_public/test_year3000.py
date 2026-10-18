"""Year-3000 and post-2262 timestamps through the native public route.

pandas nanosecond timestamps end at 2262-04-11; peak times are produced as
integer epoch milliseconds from Python datetimes, so later rows stay exact.
"""
from datetime import datetime, timedelta

import h5py
import numpy as np

from ras_commander import fast_results
from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
MESH = "Future"
STAMPS = [b"10APR2262 00:00:00:000", b"12APR2262 06:30:00:250", b"02JAN3000 00:00:00:000",
          b"04JAN3000 23:59:59:999"]
NS_LIMIT = datetime(2262, 4, 11, 23, 47, 16)


def build(path):
    wse = np.array([[1.0, 5.0, 2.0, np.nan],
                    [4.0, 5.0, 2.5, np.nan],
                    [3.0, 4.0, 2.5, np.nan],
                    [2.0, 6.0, 9.0, np.nan]], dtype=np.float32)
    with h5py.File(path, "w") as hdf:
        hdf.require_group("Plan Data/Plan Information").attrs["Simulation Start Time"] = (
            np.bytes_("10Apr2262 00:00:00"))
        hdf[f"{BASE}/Time"] = np.array([0.0, 2.27, 268.0, 270.99], dtype=np.float64)
        hdf[f"{BASE}/Time Date Stamp (ms)"] = np.array(STAMPS)
        attrs = np.dtype([("Name", "S16"), ("Cell Count", "i4")])
        hdf["Geometry/2D Flow Areas/Attributes"] = np.array([(MESH.encode(), 3)], dtype=attrs)
        geometry = hdf.require_group(f"Geometry/2D Flow Areas/{MESH}")
        geometry["Cells Center Coordinate"] = np.arange(8, dtype=np.float64).reshape(4, 2)
        geometry["Cells Minimum Elevation"] = np.array([1.0, 4.5, 0.0, 0.0], dtype=np.float32)
        hdf.create_dataset(f"{BASE}/2D Flow Areas/{MESH}/Water Surface", data=wse,
                           chunks=(2, 4), compression="gzip")
    return wse


def test_year3000_peak_times_and_public_max_depth(tmp_path, native_calls, monkeypatch):
    path = tmp_path / "future.p01.hdf"
    build(path)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    result = HdfResultsMesh.get_mesh_max_depth(path, include_ghost_cells=True)
    assert len(native_calls) == 1
    np.testing.assert_array_equal(result["maximum_depth"].to_numpy(),
                                  np.array([3.0, 1.5, 9.0, np.nan], dtype=np.float32))
    assert result["is_ghost_cell"].tolist() == [False, False, False, True]

    with h5py.File(path, "r") as hdf:
        dataset = hdf[f"{BASE}/2D Flow Areas/{MESH}/Water Surface"]
        offset = hdf[f"Geometry/2D Flow Areas/{MESH}/Cells Minimum Elevation"][()]
        reduction = fast_results.temporal_reduce(dataset, offset, threshold=1.5, backend="rust")
        stamps = HdfBase.get_unsteady_timestamps(hdf)
    assert reduction.peak_index.tolist() == [1, 3, 3, -1]
    assert reduction.first_exceed_index.tolist() == [1, 3, 0, -1]  # inclusive: 1.5 >= 1.5
    assert reduction.exceed_count.tolist() == [2, 1, 4, 0]
    times = fast_results.peak_times_ms(stamps, reduction.peak_index)
    expected = datetime(3000, 1, 4, 23, 59, 59, 999000)
    assert stamps[3] == expected and stamps[1] > NS_LIMIT
    exact = (expected - datetime(1970, 1, 1)) // timedelta(milliseconds=1)
    assert times.dtype == np.int64 and times[2] == exact == 32_504_025_599_999
    assert times[0] == (stamps[1] - datetime(1970, 1, 1)) // timedelta(milliseconds=1)
    assert times.mask.tolist() == [False, False, False, True]
    # The nanosecond representation of these times would overflow int64.
    assert int(times[2]) * 1_000_000 > np.iinfo(np.int64).max


def test_stored_depth_public_route_keeps_negative_values(tmp_path, native_calls, monkeypatch):
    """Stored Depth is reduced as-is: no clipping, no dry sentinel, NaN ignored."""
    path = tmp_path / "stored.p01.hdf"
    build(path)
    depth = np.array([[-0.25, 0.0, np.nan, np.inf], [-0.5, 2.0, np.nan, 1.0]], dtype=np.float32)
    with h5py.File(path, "a") as hdf:
        hdf.create_dataset(f"{BASE}/2D Flow Areas/{MESH}/Depth", data=depth,
                           chunks=(1, 4), compression="gzip")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    accelerated = HdfResultsMesh.get_mesh_max_depth(path, include_ghost_cells=True)
    assert len(native_calls) == 1
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    reference = HdfResultsMesh.get_mesh_max_depth(path, include_ghost_cells=True)
    assert len(native_calls) == 1
    expected = np.array([-0.25, 2.0, np.nan, 1.0], dtype=np.float32)
    np.testing.assert_array_equal(accelerated["maximum_depth"].to_numpy(), expected)
    np.testing.assert_array_equal(reference["maximum_depth"].to_numpy(), expected)
