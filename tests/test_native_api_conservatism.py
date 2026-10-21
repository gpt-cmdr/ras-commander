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


# ---------------------------------------------------------------------------
# 4. An unrecognised RAS_COMMANDER_FAST_HDF value is "auto" plus one warning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["yes", "enabled", "2", "Auto!"])
def test_invalid_fast_hdf_value_behaves_as_auto_and_warns_once(tmp_path, monkeypatch, caplog, value):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "_warned_modes", set())
    path = _write_polygon_mesh(tmp_path / "clean.g01.hdf", CLEAN_CELLS)
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    expected_names = HdfMesh.get_mesh_area_names(path)
    expected = HdfMesh.get_mesh_cell_polygons(path, backend="python")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", value)
    with caplog.at_level("WARNING", logger="ras_commander.fast_hdf"):
        assert fast_hdf._mode("auto") == "auto"
        assert HdfMesh.get_mesh_area_names(path) == expected_names == ["Poly Mesh"]
        _same_polygons(HdfMesh.get_mesh_cell_polygons(path), expected)
        assert fast_hdf.native_required() is False
    warnings = [r for r in caplog.records if "RAS_COMMANDER_FAST_HDF" in r.getMessage()]
    assert len(warnings) == 1


def test_valid_fast_hdf_values_do_not_warn(monkeypatch, caplog):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "_warned_modes", set())
    expected = {"": "auto", "auto": "auto", " AUTO ": "auto", "1": "auto", "on": "auto", "true": "auto",
                "0": "python", "off": "python", "false": "python", "python": "python",
                "required": "rust", "rust": "rust"}
    with caplog.at_level("WARNING", logger="ras_commander.fast_hdf"):
        for value, mode in expected.items():
            monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", value)
            assert fast_hdf._mode("auto") == mode
    assert not caplog.records


def test_invalid_explicit_backend_still_raises():
    from ras_commander import fast_hdf
    with pytest.raises(ValueError, match="backend must be"):
        fast_hdf._mode("fast")


# ---------------------------------------------------------------------------
# 5. A failed extension import is attempted once per process
# ---------------------------------------------------------------------------

def test_missing_extension_is_imported_once(monkeypatch):
    import importlib
    import time
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "_native_state", None)
    attempts = []

    def failing_import(name, *args, **kwargs):
        attempts.append(name)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", failing_import)
    started = time.perf_counter()
    for _ in range(20000):
        assert fast_hdf._native("auto") is None
    elapsed = time.perf_counter() - started
    assert attempts == ["ras_commander_fast_hdf"]
    assert elapsed / 20000 < 20e-6
    with pytest.raises(fast_hdf.FastHdfError, match="unavailable"):
        fast_hdf._native("rust")
    assert len(attempts) == 1


def test_incompatible_extension_warns_once(monkeypatch, caplog):
    import importlib
    import types
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "_native_state", None)
    monkeypatch.setattr(importlib, "import_module", lambda name: types.SimpleNamespace(API_VERSION=3))
    with caplog.at_level("WARNING", logger="ras_commander.fast_hdf"):
        for _ in range(50):
            assert fast_hdf._native("auto") is None
    assert len([r for r in caplog.records if "incompatible" in r.getMessage()]) == 1
    with pytest.raises(fast_hdf.FastHdfError, match="version 11"):
        fast_hdf._native("rust")


# ---------------------------------------------------------------------------
# 6. Native-only errors never abort calls that main tolerates (python/auto)
# ---------------------------------------------------------------------------

SUMMARY_PATH = ("Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/"
                f"2D Flow Areas/{MESH_NAME}")


def _write_mesh_results_hdf(path):
    _write_results_hdf(path, 2020)
    with h5py.File(path, "a") as hdf:
        group = hdf.require_group(SUMMARY_PATH)
        group.create_dataset("Maximum Water Surface", data=np.array([[5.0], [1.0]]))
        group.create_dataset("Maximum Face Velocity", data=np.array([[0.3], [2.0]]))
        group.create_dataset("Minimum Water Surface", data=np.array([[0.5], [1.0]]))
    return path


class _BrokenSession:
    """A binding that answers every read with a wrong-typed array."""

    calls = 0

    def __getattr__(self, name):
        def call(*args, **kwargs):
            type(self).calls += 1
            if name == "read_numeric_batch":
                return {}
            junk = np.zeros(1, dtype=np.float16)
            return {"values": junk} if name.startswith("read_mesh") else junk
        return call

    def close(self):
        pass


def _install_broken_session(monkeypatch):
    import contextlib
    from ras_commander import fast_hdf

    _BrokenSession.calls = 0

    @contextlib.contextmanager
    def session(*args, **kwargs):
        yield _BrokenSession()

    monkeypatch.setattr(fast_hdf, "_session", session)


def _outcome(call):
    try:
        value = call()
    except Exception as exc:  # noqa: BLE001 - the exception type/text is the contract
        return ("raise", type(exc).__name__, str(exc))
    if isinstance(value, dict):
        return ("ok", {k: _digest(v) for k, v in value.items()})
    return ("ok", _digest(value))


def _digest(value):
    if isinstance(value, xr.Dataset):
        return {name: (var.dims, var.values.tolist()) for name, var in value.data_vars.items()}, \
            {name: coord.values.tolist() for name, coord in value.coords.items()}
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="list"), dict(value.attrs)
    return repr(value)


MESH_RESULT_CALLS = {
    "cells_timeseries": lambda p: HdfResultsMesh.get_mesh_cells_timeseries(
        p, mesh_names=MESH_NAME, var="Water Surface", truncate=False),
    "cells_timeseries_all": lambda p: HdfResultsMesh.get_mesh_cells_timeseries(p),
    "max_ws": lambda p: HdfResultsMesh.get_mesh_max_ws(p),
    "max_face_v": lambda p: HdfResultsMesh.get_mesh_max_face_v(p),
    "min_ws": lambda p: HdfResultsMesh.get_mesh_min_ws(p),
}


@pytest.mark.parametrize("call", sorted(MESH_RESULT_CALLS))
def test_auto_mesh_results_ignore_a_misbehaving_binding(tmp_path, monkeypatch, native_module, call):
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    reference = _outcome(lambda: MESH_RESULT_CALLS[call](path))
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF")
    _install_broken_session(monkeypatch)
    assert _outcome(lambda: MESH_RESULT_CALLS[call](path)) == reference
    assert _BrokenSession.calls > 0, "the injected failure was never exercised"


@pytest.mark.parametrize("call", ["cells_timeseries", "max_ws"])
def test_required_mesh_results_surface_native_failure(tmp_path, monkeypatch, native_module, call):
    from ras_commander.fast_hdf import FastHdfError
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    _install_broken_session(monkeypatch)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(FastHdfError):
        MESH_RESULT_CALLS[call](path)


def test_auto_datasets_with_a_broken_binding_read_like_h5py(tmp_path, monkeypatch, native_module):
    from ras_commander import fast_hdf
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    _install_broken_session(monkeypatch)
    names = [SUMMARY_PATH + "/Maximum Water Surface", SUMMARY_PATH + "/Maximum Face Velocity",
             f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Water Surface"]
    with h5py.File(path, "r") as hdf:
        expected = {n: hdf[n][()] for n in names}
        for name in names:
            np.testing.assert_array_equal(fast_hdf.read_dataset(hdf[name]), expected[name])
        batch = fast_hdf.read_datasets(hdf, names)
        for name in names:
            np.testing.assert_array_equal(batch[name], expected[name])
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_dataset(hdf[names[0]], backend="rust")


def test_auto_attribute_reads_survive_a_malformed_engine_descriptor(tmp_path, monkeypatch, native_module):
    from ras_commander import _fast_hdf_typed, fast_hdf
    path = tmp_path / "attrs.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["a"] = 3
        hdf.attrs["b"] = "text"
    monkeypatch.setattr(_fast_hdf_typed, "_typed_attributes", lambda module, obj: {"a": None, "b": object()})
    with h5py.File(path, "r") as hdf:
        assert fast_hdf.read_attrs(hdf) == {"a": 3, "b": "text"}
        assert fast_hdf.read_attr(hdf, "a") == 3
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_attrs(hdf, backend="rust")


def test_auto_temporal_reduce_ignores_a_malformed_native_result(tmp_path, monkeypatch, native_module):
    from ras_commander import fast_results
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    monkeypatch.setattr(native_module, "temporal_reduce", lambda *a, **k: {"rows": 3})
    with h5py.File(path, "r") as hdf:
        dataset = hdf[f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Water Surface"]
        assert fast_results.native_temporal_reduce(dataset) is None
        with pytest.raises(fast_results.FastHdfError):
            fast_results.native_temporal_reduce(dataset, backend="rust")


# ---------------------------------------------------------------------------
# 3. No HDF stays open after a public call (Windows locks / network shares)
# ---------------------------------------------------------------------------

@pytest.fixture
def session_spy(monkeypatch, native_module):
    """Count native session opens while leaving the real implementation in place."""
    import contextlib
    from ras_commander import fast_hdf
    fast_hdf.close_sessions()
    opened = []
    real = fast_hdf._session

    @contextlib.contextmanager
    def spy(module, path, threads=None):
        before = set(fast_hdf._sessions)
        with real(module, path, threads) as session:
            if set(fast_hdf._sessions) - before:
                opened.append(str(path))
            yield session

    monkeypatch.setattr(fast_hdf, "_session", spy)
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    monkeypatch.delenv("RAS_COMMANDER_HDF_SESSION_CACHE", raising=False)
    yield opened
    fast_hdf.close_sessions()


PUBLIC_READS = {
    "cell_polygons": lambda p: HdfMesh.get_mesh_cell_polygons(p),
    "max_ws": lambda p: HdfResultsMesh.get_mesh_max_ws(p),
    "cells_timeseries": lambda p: HdfResultsMesh.get_mesh_cells_timeseries(p),
    "max_face_v": lambda p: HdfResultsMesh.get_mesh_max_face_v(p),
}


def _project_with(tmp_path, writer, name):
    folder = tmp_path / "project"
    folder.mkdir()
    return writer(folder / name)


@pytest.mark.parametrize("call", sorted(PUBLIC_READS))
def test_public_read_leaves_no_native_session_open(tmp_path, session_spy, call):
    from ras_commander import fast_hdf
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    _write_polygon_mesh_into(path)
    PUBLIC_READS[call](path)
    assert not fast_hdf._sessions


def _write_polygon_mesh_into(path):
    """Add polygon topology to a results file so one file serves every read."""
    other = _write_polygon_mesh(path.with_name("poly-source.hdf"), CLEAN_CELLS)
    with h5py.File(other, "r") as src, h5py.File(path, "a") as dst:
        for group in ("Faces FacePoint Indexes", "FacePoints Coordinate", "Faces Perimeter Info",
                      "Faces Perimeter Values", "Cells Face and Orientation Info",
                      "Cells Face and Orientation Values"):
            source = f"Geometry/2D Flow Areas/Poly Mesh/{group}"
            target = f"Geometry/2D Flow Areas/{MESH_NAME}/{group}"
            if target in dst:
                del dst[target]
            dst.create_dataset(target, data=src[source][()])
        dst.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()


def test_project_folder_can_be_renamed_deleted_and_re_extracted_after_reads(tmp_path, session_spy):
    import shutil
    path = _project_with(tmp_path, _write_mesh_results_hdf, "model.p01.hdf")
    folder = path.parent
    for call in PUBLIC_READS.values():
        try:
            call(path)
        except Exception:  # noqa: BLE001 - the synthetic file need not satisfy every reader
            pass
    assert session_spy, "no native session was opened; the test would prove nothing"
    renamed = tmp_path / "renamed"
    os.rename(folder, renamed)          # fails on Windows while a handle is open
    os.rename(renamed, folder)
    os.remove(path)                      # fails on network shares while a handle is open
    _write_mesh_results_hdf(path)       # same name again
    shutil.rmtree(folder)               # RasExamples.extract_project does exactly this
    assert not folder.exists()


def test_one_session_serves_every_read_of_a_public_call(tmp_path, session_spy):
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    HdfResultsMesh.get_mesh_cells_timeseries(path)
    assert len(session_spy) == 1


def test_session_is_released_when_a_public_call_raises(tmp_path, session_spy, monkeypatch):
    from ras_commander import fast_hdf
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    real = HdfResultsMesh._mesh_series_id_dim

    def read_then_fail(*args, **kwargs):
        fast_hdf.read_dataset(args[2])           # open a session inside the public call
        assert fast_hdf._sessions
        raise RuntimeError("late failure")

    monkeypatch.setattr(HdfResultsMesh, "_mesh_series_id_dim", staticmethod(read_then_fail))
    with pytest.raises(Exception):
        HdfResultsMesh.get_mesh_cells_timeseries(path, mesh_names=MESH_NAME, var="Water Surface", truncate=False)
    assert not fast_hdf._sessions
    monkeypatch.setattr(HdfResultsMesh, "_mesh_series_id_dim", real)


def test_direct_low_level_reads_keep_their_documented_cache(tmp_path, session_spy):
    from ras_commander import fast_hdf
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    name = f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Water Surface"
    with h5py.File(path, "r") as hdf:
        fast_hdf.read_dataset(hdf[name])
        assert len(fast_hdf._sessions) == 1
    fast_hdf.close_sessions(path)
    assert not fast_hdf._sessions


def test_persist_setting_keeps_sessions_across_public_calls(tmp_path, session_spy, monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", "persist")
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    HdfResultsMesh.get_mesh_max_ws(path)
    assert len(fast_hdf._sessions) == 1
    HdfResultsMesh.get_mesh_max_ws(path)
    assert len(session_spy) == 1
    fast_hdf.close_sessions()
    assert not fast_hdf._sessions


def test_cache_off_opens_per_read_and_holds_nothing(tmp_path, session_spy, monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", "0")
    path = _write_mesh_results_hdf(tmp_path / "results.p01.hdf")
    HdfResultsMesh.get_mesh_max_ws(path)
    assert not fast_hdf._sessions


# ---------------------------------------------------------------------------
# 7. Unrelated changes ride-alongs stay out
# ---------------------------------------------------------------------------

def test_get_pipe_nodes_resolves_the_projection_last_like_main(tmp_path, monkeypatch):
    from ras_commander.hdf.HdfPipe import HdfPipe
    calls = []
    real = HdfBase.get_projection
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *a, **k: calls.append(a) or real(*a, **k)))
    path = tmp_path / "no-pipes.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
    with pytest.raises(KeyError, match="Pipe Nodes"):
        HdfPipe.get_pipe_nodes(path)
    assert calls == []        # main raised before ever resolving a projection
    with h5py.File(path, "a") as hdf:
        attributes = np.zeros(1, dtype=[("Name", "S8")])
        hdf.create_dataset("Geometry/Pipe Nodes/Attributes", data=attributes)
        hdf.create_dataset("Geometry/Pipe Nodes/Points", data=np.array([[1.0, 2.0]]))
    nodes = HdfPipe.get_pipe_nodes(path)
    assert len(calls) == 1 and nodes.crs is not None


def test_geometry_text_output_is_main_s():
    """GeomCrossSection keeps main's 10-value '#XS Ineff' rows and bank-station rounding."""
    from ras_commander.geom.GeomCrossSection import GeomCrossSection
    assert not hasattr(GeomCrossSection, "INEFFECTIVE_VALUES_PER_LINE")
    assert not hasattr(GeomCrossSection, "_round_trip_decimals")


# ---------------------------------------------------------------------------
# 8. Documentation matches the code for the native surface
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]


def test_every_ras_commander_environment_variable_is_documented():
    import re
    variables = set()
    for source in (REPO / "ras_commander").rglob("*.py"):
        variables |= set(re.findall(r"RAS_COMMANDER_[A-Z0-9_]+", source.read_text(encoding="utf-8")))
    native = {v for v in variables if v.startswith(("RAS_COMMANDER_FAST", "RAS_COMMANDER_HDF"))}
    assert {"RAS_COMMANDER_FAST_HDF", "RAS_COMMANDER_HDF_SESSION_CACHE", "RAS_COMMANDER_FAST_TEXT"} <= native
    docs = (REPO / "docs" / "api" / "hdf.md").read_text(encoding="utf-8")
    agents = (REPO / "ras_commander" / "hdf" / "AGENTS.md").read_text(encoding="utf-8")
    for name in sorted(native):
        assert name in docs, f"{name} is not in docs/api/hdf.md"
        assert name in agents, f"{name} is not in ras_commander/hdf/AGENTS.md"
    assert "close_sessions" in docs and "close_sessions" in agents


def test_hdfutils_api_reference_lists_every_public_method():
    import inspect
    import re
    docs = (REPO / "docs" / "api" / "hdf.md").read_text(encoding="utf-8")
    block = docs.split("::: ras_commander.hdf.HdfUtils.HdfUtils", 1)[1]
    block = block.split("### ", 1)[0]
    listed = set(re.findall(r"^\s+- (\w+)\s*$", block, flags=re.M))
    public = {name for name, member in inspect.getmembers(HdfUtils)
              if not name.startswith("_") and callable(member)}
    assert public - listed == set(), f"undocumented HdfUtils methods: {sorted(public - listed)}"
    assert "::: ras_commander.hdf.HdfUtils.CrsEvidence" in docs
    assert "::: ras_commander.hdf.HdfUtils.CrsResolution" in docs


def test_fast_hdf_public_names_exclude_the_low_level_plumbing():
    from ras_commander import fast_hdf
    internal = {"read_typed", "read_attrs", "read_attr", "read_dataset", "read_datasets",
                "mesh_series_domain", "trace_reads", "native_required", "reraise_required"}
    assert not internal & set(fast_hdf.__all__)
    assert len(fast_hdf.__all__) == len(set(fast_hdf.__all__))
    for name in fast_hdf.__all__:
        assert hasattr(fast_hdf, name)
    # still importable by name for the Hdf* classes and the qualification suites
    for name in internal:
        assert callable(getattr(fast_hdf, name))
