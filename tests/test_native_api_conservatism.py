"""Regression tests: native routing must not change the public behaviour of main.

Each section pins one item of the API-conservatism review. Where a reference is
needed, the expression from main is repeated inline, so these tests do not
depend on a second checkout.
"""
import datetime as dt
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pyproj import CRS

from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
from ras_commander.hdf.HdfUtils import HdfUtils

BASE_TS_PATH = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
TIME_PATH = BASE_TS_PATH + "/Time"


# ---------------------------------------------------------------------------
# 1. Timestamps: main's dtype and rounding for every date that fits in ns
# ---------------------------------------------------------------------------

def _main_convert(timesteps, start_time, time_unit="days", round_to="100ms"):
    """convert_timesteps_to_datetimes exactly as it is on main."""
    if time_unit == "days":
        datetimes = start_time + pd.to_timedelta(timesteps, unit="D")
    elif time_unit == "hours":
        datetimes = start_time + pd.to_timedelta(timesteps, unit="H")
    else:
        raise ValueError(f"Unsupported time unit: {time_unit}")
    return pd.DatetimeIndex(datetimes).round(round_to)


def _assert_identical_index(actual, expected):
    assert actual.dtype == expected.dtype
    assert actual.tz == expected.tz
    assert actual.asi8.tobytes() == expected.asi8.tobytes()


_STARTS = [
    dt.datetime(2020, 1, 1),
    dt.datetime(1999, 12, 31, 23, 59, 59, 654321),
    dt.datetime(1700, 6, 1),
    dt.datetime(2200, 1, 1),
    pd.Timestamp("2020-03-04 05:06:07.123456"),
]
_ARRAYS = {
    "simple": np.array([0.0, 0.5, 1.25]),
    "ms_ties": np.array([0.0, 149.6, 149.4, 150.0, 250.0, 50.0, 349.99]) / 86400000.0,
    "ints": np.arange(10),
    "negative": np.array([-1.5, -0.25, 0.0]),
    "nan": np.array([0.0, np.nan, 1.0]),
    "empty": np.array([]),
    "random": np.sort(np.random.default_rng(7).random(1500) * 40.0),
}


@pytest.mark.parametrize("start", _STARTS, ids=lambda s: str(s)[:10])
@pytest.mark.parametrize("name", sorted(_ARRAYS))
@pytest.mark.parametrize("time_unit", ["days", "hours"])
@pytest.mark.parametrize("round_to", ["100ms", "s", "1ms", "1ns"])
def test_convert_timesteps_matches_main_inside_ns_range(start, name, time_unit, round_to):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected = _main_convert(_ARRAYS[name], start, time_unit, round_to)
        actual = HdfUtils.convert_timesteps_to_datetimes(_ARRAYS[name], start, time_unit, round_to)
    _assert_identical_index(actual, expected)


def test_convert_timesteps_rounds_once_like_main():
    start = dt.datetime(2020, 1, 1)
    offsets = np.array([149.6]) / 86400000.0
    assert HdfUtils.convert_timesteps_to_datetimes(offsets, start)[0] == pd.Timestamp("2020-01-01 00:00:00.100")


def test_convert_timesteps_unsupported_unit_unchanged():
    with pytest.raises(ValueError, match="Unsupported time unit: weeks"):
        HdfUtils.convert_timesteps_to_datetimes(np.array([0.0]), dt.datetime(2020, 1, 1), "weeks")


def test_convert_timesteps_beyond_ns_range_falls_back_to_milliseconds():
    start = dt.datetime(3000, 1, 1)
    offsets = np.array([0.0, 149.6 / 86400000.0, 1.0 + 0.25 / 86400.0])
    index = HdfUtils.convert_timesteps_to_datetimes(offsets, start, round_to="1ms")
    assert index[0] == pd.Timestamp(2999 + 1, 1, 1)
    # Offsets are rounded once, not first to whole ms and again to round_to.
    assert index[1] == pd.Timestamp("3000-01-01 00:00:00.150")
    assert index[2] == pd.Timestamp("3000-01-02 00:00:00.250")
    assert str(index.dtype) != "datetime64[ns]"
    default = HdfUtils.convert_timesteps_to_datetimes(offsets, start)
    assert str(default.dtype) == "datetime64[ms]" or str(default.dtype) == "datetime64[us]"
    assert default[1] == pd.Timestamp("3000-01-01 00:00:00.100")


def _fixture_time_arrays():
    manifest = os.environ.get("RAS_ROUTE1_FIXTURES")
    if not manifest or not Path(manifest).is_file():
        return []
    found = []
    for item in json.loads(Path(manifest).read_text(encoding="utf-8"))["fixtures"]:
        path = Path(item["path"])
        if not path.is_file():
            continue
        try:
            with h5py.File(path, "r") as hdf:
                if TIME_PATH in hdf:
                    found.append((item["name"], path))
        except OSError:
            continue
    return found


@pytest.mark.parametrize("name,path", _fixture_time_arrays() or [pytest.param("none", None, marks=pytest.mark.skip("no fixtures"))])
def test_convert_timesteps_matches_main_on_real_fixture_times(name, path):
    import warnings
    with h5py.File(path, "r") as hdf:
        times = hdf[TIME_PATH][()]
    start = HdfBase.get_simulation_start_time(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for round_to in ("100ms", "s", "1ms"):
            _assert_identical_index(
                HdfUtils.convert_timesteps_to_datetimes(times, start, "days", round_to),
                _main_convert(times, start, "days", round_to),
            )
        _assert_identical_index(
            HdfUtils.convert_timesteps_to_datetimes(times, start, "hours"),
            _main_convert(times, start, "hours"),
        )


MESH_NAME = "Test Mesh"


def _write_results_hdf(path, year):
    stamp = f"%02dJan{year}"
    with h5py.File(path, "w") as hdf:
        info = hdf.require_group("Plan Data/Plan Information")
        info.attrs["Simulation Start Time"] = np.bytes_(f"02Jan{year} 00:00:00")
        hdf.create_dataset(TIME_PATH, data=np.array([0.0, 1.0, 2.0]))
        hdf.create_dataset(
            BASE_TS_PATH + "/Time Date Stamp (ms)",
            data=np.array([(stamp % day + " 00:00:00.000").encode() for day in (2, 3, 4)]),
        )
        attrs_dtype = np.dtype([("Name", "S64"), ("Cell Count", "i4")])
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(MESH_NAME.encode(), 1)], dtype=attrs_dtype),
        )
        geometry = hdf.require_group(f"Geometry/2D Flow Areas/{MESH_NAME}")
        geometry.create_dataset("Cells Center Coordinate", data=np.array([[0.0, 0.0]]))
        group = hdf.require_group(f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}")
        dataset = group.create_dataset("Water Surface", data=np.array([[1.0], [2.0], [3.0]]))
        dataset.attrs["Units"] = np.bytes_("ft")
        geometry.create_dataset("Faces FacePoint Indexes", data=np.zeros((1, 2), dtype=int))
    return path


def test_mesh_time_coordinate_keeps_the_dtype_xarray_gives_main(tmp_path):
    path = _write_results_hdf(tmp_path / "y2020.p01.hdf", 2020)
    stamps = HdfBase.get_unsteady_timestamps(path)
    expected = xr.DataArray(np.zeros(3), coords={"time": stamps}, dims=["time"]).coords["time"].values
    for mesh in (
        HdfResultsMesh.get_mesh_cells_timeseries(path, mesh_names=MESH_NAME, var="Water Surface", truncate=False)[MESH_NAME],
    ):
        actual = mesh.coords["time"].values
        assert actual.dtype == expected.dtype
        assert actual.tobytes() == expected.tobytes()


def test_mesh_time_coordinate_beyond_ns_range_is_representable(tmp_path):
    path = _write_results_hdf(tmp_path / "y3000.p01.hdf", 3000)
    dataset = HdfResultsMesh.get_mesh_cells_timeseries(
        path, mesh_names=MESH_NAME, var="Water Surface", truncate=False)[MESH_NAME]
    years = dataset.coords["time"].values.astype("datetime64[Y]").astype(int) + 1970
    assert years.tolist() == [3000, 3000, 3000]


# ---------------------------------------------------------------------------
# 2. get_mesh_cell_polygons: a native failure never escapes in auto mode
# ---------------------------------------------------------------------------

def _write_polygon_mesh(path, cell_faces):
    points = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [3, 0], [3, 1], [2, 1]], dtype=float)
    face_indexes = np.array(
        [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7]], dtype=np.int32)
    offsets, values = [], []
    for face_ids in cell_faces:
        offsets.append([len(values), len(face_ids)])
        values.extend([face_id, 1] for face_id in face_ids)
    attributes = np.zeros(1, dtype=[("Name", "S64")])
    attributes["Name"] = b"Poly Mesh"
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        base = "Geometry/2D Flow Areas"
        mesh = f"{base}/Poly Mesh"
        hdf_file.create_dataset(f"{base}/Attributes", data=attributes)
        hdf_file.create_dataset(f"{mesh}/Faces FacePoint Indexes", data=face_indexes)
        hdf_file.create_dataset(f"{mesh}/FacePoints Coordinate", data=points)
        hdf_file.create_dataset(f"{mesh}/Faces Perimeter Info", data=np.zeros((len(face_indexes), 2), dtype=np.int32))
        hdf_file.create_dataset(f"{mesh}/Faces Perimeter Values", data=np.empty((0, 2), dtype=float))
        hdf_file.create_dataset(f"{mesh}/Cells Face and Orientation Info", data=np.asarray(offsets, dtype=np.int32))
        hdf_file.create_dataset(f"{mesh}/Cells Face and Orientation Values", data=np.asarray(values, dtype=np.int32))
    return path


CLEAN_CELLS = [[0, 1, 2, 3]]
BROKEN_CELLS = [[0, 1, 2, 3], [4, 5, 6], [0, 1, 99]]  # open ring + missing face


def _same_polygons(actual, expected):
    assert list(actual.columns) == list(expected.columns)
    assert actual.crs == expected.crs
    assert actual["mesh_name"].tolist() == expected["mesh_name"].tolist()
    assert actual["cell_id"].tolist() == expected["cell_id"].tolist()
    assert [g.wkt for g in actual.geometry] == [g.wkt for g in expected.geometry] or all(
        a.equals(b) for a, b in zip(actual.geometry, expected.geometry))
    assert actual.attrs == expected.attrs


@pytest.fixture
def native_module():
    return pytest.importorskip("ras_commander_fast_hdf")


@pytest.mark.parametrize("error", [
    RuntimeError("engine exploded"), ValueError("bad connectivity"), OSError("mapping failed"),
    KeyError("missing"), "fast_hdf_error", "corrupt",
])
@pytest.mark.parametrize("strict", [False, True])
def test_auto_polygons_equal_python_when_native_fails(tmp_path, monkeypatch, native_module, error, strict):
    from ras_commander import fast_hdf
    if error == "fast_hdf_error":
        error = fast_hdf.FastHdfError("native batch omitted")
    elif error == "corrupt":
        error = native_module.CorruptDataError("checksum")
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    path = _write_polygon_mesh(tmp_path / "clean.g01.hdf", CLEAN_CELLS)
    reference = HdfMesh.get_mesh_cell_polygons(path, strict=strict, backend="python")

    def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr(fast_hdf, "_assemble", failing)
    _same_polygons(HdfMesh.get_mesh_cell_polygons(path, strict=strict), reference)


def test_native_failure_still_raises_in_required_mode(tmp_path, monkeypatch, native_module):
    from ras_commander import fast_hdf
    path = _write_polygon_mesh(tmp_path / "clean.g01.hdf", CLEAN_CELLS)
    monkeypatch.setattr(fast_hdf, "_assemble", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(fast_hdf.FastHdfError):
        HdfMesh.get_mesh_cell_polygons(path, backend="rust")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(fast_hdf.FastHdfError):
        HdfMesh.get_mesh_cell_polygons(path)


def test_auto_polygons_reproduce_main_on_corrupt_topology(tmp_path, monkeypatch, native_module):
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    path = _write_polygon_mesh(tmp_path / "broken.g01.hdf", BROKEN_CELLS)
    _same_polygons(
        HdfMesh.get_mesh_cell_polygons(path),
        HdfMesh.get_mesh_cell_polygons(path, backend="python"),
    )
    with pytest.raises(MeshCellPolygonError) as python_error:
        HdfMesh.get_mesh_cell_polygons(path, strict=True, backend="python")
    with pytest.raises(MeshCellPolygonError) as auto_error:
        HdfMesh.get_mesh_cell_polygons(path, strict=True)
    assert str(auto_error.value) == str(python_error.value)


@pytest.mark.parametrize("strict", [False, True])
def test_auto_polygons_on_unreadable_file_equal_python(tmp_path, monkeypatch, native_module, strict):
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    path = tmp_path / "not-hdf.g01.hdf"
    path.write_bytes(b"this is not an HDF5 file")
    outcomes = []
    for backend in ("python", "auto"):
        try:
            result = HdfMesh.get_mesh_cell_polygons(path, strict=strict, backend=backend)
            outcomes.append(("result", result.empty, result.attrs))
        except Exception as exc:  # noqa: BLE001 - compare whatever main did
            outcomes.append(("raise", type(exc).__name__, str(exc)))
    assert outcomes[0] == outcomes[1]
