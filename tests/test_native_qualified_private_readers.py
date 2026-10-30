"""Native and h5py give identical results for three private HDF readers.

``RasUnsteady._preflight_precipitation_ratio``, ``_container_compute._prepared_window``
and ``_landcover_native.validate_native_landcover`` run natively in ``auto`` mode.
Each test runs the reader on both backends, requires identical outcomes (values,
types, exception type and message), checks the values against an independent
plain-h5py read, and requires the native run to have read through the engine.

The precipitation case uses a HEC-RAS 7.0.1-written unsteady HDF
(``tests/fixtures/precipitation/ratio_baldeagle_701``). The real-file runs for
the other two readers are the ROUTE-NONHDF cases
``exec:_container_compute._prepared_window[tmp]`` and
``land:_landcover_native.validate_native_landcover[classes]``.
"""
import shutil
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf

PRECIP = "Event Conditions/Meteorology/Precipitation"
RATIO_FIXTURE = (Path(__file__).parent / "fixtures" / "precipitation"
                 / "ratio_baldeagle_701" / "BaldEagleDamBrk.u03.hdf")
NATIVE_READS = {"native-typed", "native-generic"}

BACKENDS = ["h5py", "native"]


def _run(backend, func, *args, **kwargs):
    if backend == "native":
        pytest.importorskip("ras_commander_fast_hdf")
    fast_hdf.close_sessions()
    try:
        with fast_hdf.backend_scope(backend), fast_hdf.trace_reads() as trace:
            try:
                outcome = ("ok", func(*args, **kwargs))
            except Exception as exc:  # compared, never hidden
                outcome = ("raise", type(exc), str(exc))
    finally:
        fast_hdf.close_sessions()
    return outcome, list(trace)


def _both(func, *args, **kwargs):
    """Run on h5py and native; require identical outcomes and a native read."""
    py, py_trace = _run("h5py", func, *args, **kwargs)
    assert all(r["backend"] == "h5py" for r in py_trace)
    native, native_trace = _run("native", func, *args, **kwargs)
    assert py[0] == native[0]
    if py[0] == "ok":
        assert type(py[1]) is type(native[1])
        assert repr(py[1]) == repr(native[1])
    else:
        assert py[1] is native[1] and py[2] == native[2]
    assert not [r for r in native_trace if r["backend"] in {"h5py", "h5py-fallback"}]
    return py, [r for r in native_trace if r["backend"] in NATIVE_READS]


# ---------------------------------------------------------- precipitation ratio
def _unsteady_pair(tmp_path, ratio=None):
    """Copy the HEC-RAS-written u03.hdf next to a text file without a Ratio line."""
    unsteady = tmp_path / "BaldEagleDamBrk.u03"
    unsteady.write_text("Flow Title=Gridded Precipitation\nMet BC=Precipitation|Mode=Gridded\n",
                        encoding="utf-8")
    hdf_path = tmp_path / "BaldEagleDamBrk.u03.hdf"
    shutil.copyfile(RATIO_FIXTURE, hdf_path)
    if ratio is not None:
        with h5py.File(hdf_path, "r+") as hdf:
            hdf[PRECIP].attrs["Ratio"] = np.float32(ratio)
    return unsteady


def test_fixture_stores_ratio_as_float32_scalar():
    with h5py.File(RATIO_FIXTURE, "r") as hdf:
        value = hdf[PRECIP].attrs["Ratio"]
    assert isinstance(value, np.float32) and value == np.float32(0.5)


def test_preflight_reads_hec_ras_written_ratio(tmp_path):
    from ras_commander.RasUnsteady import RasUnsteady

    unsteady = _unsteady_pair(tmp_path)
    with h5py.File(RATIO_FIXTURE, "r") as hdf:
        stored = float(hdf[PRECIP].attrs["Ratio"])
    outcome, native_reads = _both(RasUnsteady._preflight_precipitation_ratio, unsteady, None, None)
    assert outcome[0] == "raise" and outcome[1] is ValueError
    assert outcome[2].startswith(f"BaldEagleDamBrk.u03.hdf retains precipitation Ratio={stored:g}.")
    assert [r["route"] for r in native_reads] == ["attr:Ratio"]


def test_preflight_unit_hdf_ratio_passes(tmp_path):
    from ras_commander.RasUnsteady import RasUnsteady

    unsteady = _unsteady_pair(tmp_path, ratio=1.0)
    outcome, native_reads = _both(RasUnsteady._preflight_precipitation_ratio, unsteady, None, None)
    assert outcome == ("ok", None)
    assert [r["route"] for r in native_reads] == ["attr:Ratio"]


@pytest.mark.parametrize("ratio", [1.0, 0.5])
def test_preflight_explicit_ratio_does_not_read_hdf(tmp_path, ratio):
    from ras_commander.RasUnsteady import RasUnsteady

    unsteady = _unsteady_pair(tmp_path)
    outcome, native_reads = _both(RasUnsteady._preflight_precipitation_ratio, unsteady, None, ratio)
    assert outcome == ("ok", None) and native_reads == []


# ---------------------------------------------------------- prepared window
def _prepared(path, start=b"01Jan2000 00:00:00", end=b"01Jan2000 06:00:00", results=False):
    with h5py.File(path, "w") as hdf:
        info = hdf.require_group("Plan Data/Plan Information")
        if start is not None:
            info.attrs["Simulation Start Time"] = np.bytes_(start)
        if end is not None:
            info.attrs["Simulation End Time"] = np.bytes_(end)
        if results:
            hdf.require_group("Results")
    return path


def test_prepared_window_values(tmp_path):
    from ras_commander import _container_compute

    path = _prepared(tmp_path / "Model.p01.tmp.hdf")
    with h5py.File(path, "r") as hdf:
        info = hdf["Plan Data/Plan Information"].attrs
        expected = tuple(datetime.strptime(info[k].decode(), "%d%b%Y %H:%M:%S")
                         for k in ("Simulation Start Time", "Simulation End Time"))
    outcome, native_reads = _both(_container_compute._prepared_window, path)
    assert outcome == ("ok", expected)
    assert sorted(r["route"] for r in native_reads) == [
        "attr:Simulation End Time", "attr:Simulation Start Time"]


@pytest.mark.parametrize("kwargs, message", [
    ({"results": True}, "stale /Results"),
    ({"end": None}, "lacks Simulation End Time"),
    ({"end": b"01Jan2000 00:00:00"}, "end must follow its start"),
])
def test_prepared_window_errors(tmp_path, kwargs, message):
    from ras_commander import _container_compute

    path = _prepared(tmp_path / "Model.p01.tmp.hdf", **kwargs)
    outcome, _ = _both(_container_compute._prepared_window, path)
    assert outcome[0] == "raise" and outcome[1] is ValueError and message in outcome[2]


# ---------------------------------------------------------- native land cover
def _layer(tmp_path, legacy):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    # Dataset layout as RASMapper writes it (S28 names, gzip, chunk 100, unlimited).
    def put(hdf, name, data, chunk):
        hdf.create_dataset(name, data=data, maxshape=(None,), chunks=(chunk,), compression="gzip")

    hdf_path = tmp_path / "LandCover.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        if legacy:
            put(hdf, "IDs", np.array([0, 1, 2], dtype=np.uint8), 3)
            put(hdf, "Names", np.array([b"NoData", b"A", b"B"], dtype="S28"), 3)
            put(hdf, "ManningsN", np.array([np.finfo(np.float32).max, 0.03, 0.08], np.float32), 3)
        else:
            # Root identity attributes of a RASMapper 2.0 land-cover layer.
            hdf.attrs["File Type"] = np.bytes_(b"HEC Land Cover")
            hdf.attrs["LC Type"] = np.bytes_(b"LandCover")
            hdf.attrs["Version"] = np.bytes_(b"2.0")
            put(hdf, "Raster Map", np.array(
                [(0, b"NoData"), (1, b"A"), (2, b"B")], dtype=[("ID", "<i4"), ("Name", "S28")]), 100)
            put(hdf, "Variables", np.array(
                [(b"NoData", np.finfo(np.float32).max), (b"A", 0.03), (b"B", 0.08)],
                dtype=[("Name", "S28"), ("ManningsN", "<f4")]), 100)
    data = np.array([[0, 1] * 16, [2, 1] * 16] * 16, dtype=np.uint8)
    with rasterio.open(hdf_path.with_suffix(".tif"), "w", driver="GTiff", width=32, height=32,
                       count=1, dtype="uint8", transform=from_origin(0, 32, 1, 1),
                       tiled=True, blockxsize=16, blockysize=16, compress="deflate") as raster:
        raster.write(data, 1)
    return hdf_path


@pytest.mark.parametrize("legacy", [True, False])
def test_validate_native_landcover_values(tmp_path, legacy):
    from ras_commander._landcover_native import validate_native_landcover

    hdf_path = _layer(tmp_path, legacy)
    with h5py.File(hdf_path, "r") as hdf:
        ids = sorted(int(v) for v in (hdf["IDs"][()] if legacy else hdf["Raster Map"]["ID"]))
    outcome, native_reads = _both(validate_native_landcover, hdf_path,
                                  expected_class_ids={1, 2}, legacy=legacy)
    assert outcome[0] == "ok"
    assert outcome[1]["hdf_class_ids"] == ids == [0, 1, 2]
    assert outcome[1]["raster_class_ids"] == [0, 1, 2]
    assert len(native_reads) == 1


@pytest.mark.parametrize("legacy, expected, message", [
    (True, {1, 3}, "missing requested class IDs: 3"),
    (False, {1, 3}, "missing requested class IDs: 3"),
    (False, set(), "collapsed to class 0"),
])
def test_validate_native_landcover_errors(tmp_path, legacy, expected, message):
    from ras_commander._landcover_native import validate_native_landcover

    hdf_path = _layer(tmp_path, legacy)
    outcome, native_reads = _both(validate_native_landcover, hdf_path,
                                  expected_class_ids=expected, legacy=legacy)
    assert outcome[0] == "raise" and outcome[1] is RuntimeError and message in outcome[2]
    assert len(native_reads) == 1
