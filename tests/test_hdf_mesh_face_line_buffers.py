"""Packed face-line buffers: identical to the per-face LineString loop.

``HdfMesh.get_mesh_cell_faces`` builds every face of a mesh in one Shapely
call from packed buffers (native engine or NumPy). These tests prove the
buffers give the per-face loop's geometry (WKB, validity) on the layouts they
accept and that every other layout is declined, so the loop still runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from ras_commander import HdfMesh, fast_hdf
from ras_commander.hdf.HdfMesh import _packed_face_lines

REAL_HDF_ENV = "RAS_COMMANDER_FACE_LINES_TEST_HDF"
MESH = "Area 1"


def _native_face_lines_available():
    # Extensions before HdfSession.read_mesh_face_lines read this minimal
    # synthetic mesh through typed mesh readers, which need more tables.
    module = fast_hdf._native("auto")
    return module is not None and hasattr(module.HdfSession, "read_mesh_face_lines")


def _loop(endpoints, points, info, values):
    """The per-face loop of get_mesh_cell_faces, verbatim."""
    lines = []
    for (a, b), (start, count) in zip(endpoints, info):
        coords = [points[a]]
        if count > 0:
            coords.extend(values[start:start + count])
        coords.append(points[b])
        lines.append(LineString(coords))
    return np.array(lines, dtype=object)


def _from_packed(packed):
    coordinates, offsets = packed
    return shapely.from_ragged_array(
        shapely.GeometryType.LINESTRING, coordinates, (offsets,))


def _tables(points_dtype=np.float64, values_dtype=np.float64, conn_dtype=np.int32,
            negative_count=True):
    # Two straight faces, one curved face with two perimeter points, one
    # zero-length face (a valid input that gives an invalid line), and
    # optionally a negative count, which the loop treats as straight.
    points = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.1, 0.2]], dtype=points_dtype)
    endpoints = np.array([[0, 1], [1, 2], [2, 3], [3, 3], [3, 0]], dtype=conn_dtype)
    info = np.array([[0, 0], [0, 0], [1, 2], [3, 0], [0, -1 if negative_count else 0]],
                    dtype=np.int32)
    values = np.array([[99.0, 99.0], [7.5, 12.25], [3.0, 11.0]], dtype=values_dtype)
    return endpoints, points, info, values


@pytest.mark.parametrize("points_dtype", [np.float64, np.float32])
@pytest.mark.parametrize("values_dtype", [np.float64, np.float32])
@pytest.mark.parametrize("conn_dtype", [np.int32, np.int64, np.uint16])
def test_packed_lines_equal_the_per_face_loop(points_dtype, values_dtype, conn_dtype):
    tables = _tables(points_dtype, values_dtype, conn_dtype)
    expected = _loop(*tables)
    packed = _packed_face_lines(*tables)
    assert packed is not None
    assert packed[0].dtype == np.float64 and packed[1].dtype == np.int64
    got = _from_packed(packed)
    assert list(shapely.to_wkb(got)) == list(shapely.to_wkb(expected))
    assert np.array_equal(shapely.is_valid(got), shapely.is_valid(expected))
    assert not shapely.is_valid(got[3])  # the zero-length face stays invalid


def test_empty_mesh_packs_no_lines():
    packed = _packed_face_lines(
        np.empty((0, 2), np.int32), np.empty((0, 2)), np.empty((0, 2), np.int32), np.empty((0, 2)))
    assert packed is not None
    assert len(packed[0]) == 0 and packed[1].tolist() == [0]


def _modified(change):
    endpoints, points, info, values = (t.copy() for t in _tables())
    tables = {"endpoints": endpoints, "points": points, "info": info, "values": values}
    change(tables)
    return tables["endpoints"], tables["points"], tables["info"], tables["values"]


@pytest.mark.parametrize("name, change", [
    ("negative endpoint wraps in the loop", lambda t: t["endpoints"].__setitem__((0, 0), -1)),
    ("endpoint out of range", lambda t: t["endpoints"].__setitem__((0, 1), 4)),
    ("negative perimeter start", lambda t: t["info"].__setitem__((2, 0), -1)),
    ("perimeter span overruns", lambda t: t["info"].__setitem__((2, 1), 3)),
    ("nonfinite coordinate", lambda t: t["values"].__setitem__((1, 0), np.nan)),
    ("unequal face tables are zipped", lambda t: t.__setitem__("info", t["info"][:-1])),
    ("three-column points", lambda t: t.__setitem__("points", np.c_[t["points"], np.zeros(4)])),
    ("three-column values", lambda t: t.__setitem__("values", np.c_[t["values"], np.zeros(3)])),
    ("float connectivity", lambda t: t.__setitem__("endpoints", t["endpoints"].astype(float))),
    ("integer coordinates", lambda t: t.__setitem__("points", t["points"].astype(np.int64))),
    ("one-column endpoints", lambda t: t.__setitem__("endpoints", t["endpoints"][:, :1])),
])
def test_layouts_the_loop_reads_differently_are_declined(name, change):
    assert _packed_face_lines(*_modified(change)) is None, name


def _write_mesh(path: Path, negative_count=False):
    endpoints, points, info, values = _tables(values_dtype=np.float32,
                                              negative_count=negative_count)
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(MESH.encode(), 1)], dtype=[("Name", "S16"), ("Cell Count", "i4")]))
        group = hdf.require_group(f"Geometry/2D Flow Areas/{MESH}")
        group["FacePoints Coordinate"] = points
        group["Faces FacePoint Indexes"] = endpoints
        group["Faces Perimeter Info"] = info
        group["Faces Perimeter Values"] = values
    return _loop(endpoints, points, info, values)


@pytest.mark.parametrize("mode", ["h5py", "auto", "native"])
def test_get_mesh_cell_faces_is_the_loop_in_every_mode(tmp_path, monkeypatch, mode):
    if mode == "native" and not _native_face_lines_available():
        pytest.skip("native face lines unavailable in this extension")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "faces.g01.hdf"
    expected = _write_mesh(path)
    faces = HdfMesh.get_mesh_cell_faces(path)
    assert faces["mesh_name"].tolist() == [MESH] * len(expected)
    assert faces["face_id"].tolist() == list(range(len(expected)))
    assert faces["face_id"].dtype == np.int64
    got = np.asarray(faces.geometry.values, dtype=object)
    assert list(shapely.to_wkb(got)) == list(shapely.to_wkb(expected))


def test_native_refusal_raises_in_native_mode_and_falls_back_in_auto(tmp_path, monkeypatch):
    # The engine refuses a negative perimeter count (the loop reads it as zero).
    if not _native_face_lines_available():
        pytest.skip("native face lines unavailable in this extension")
    path = tmp_path / "faces.g01.hdf"
    expected = _write_mesh(path, negative_count=True)
    with pytest.raises(fast_hdf.FastHdfError):
        fast_hdf.mesh_face_lines(path, MESH, backend="native")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    assert fast_hdf.mesh_face_lines(path, MESH) is None
    got = np.asarray(HdfMesh.get_mesh_cell_faces(path).geometry.values, dtype=object)
    assert list(shapely.to_wkb(got)) == list(shapely.to_wkb(expected))


def test_native_face_lines_decline_when_h5py_is_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    path = tmp_path / "faces.g01.hdf"
    _write_mesh(path)
    assert fast_hdf.mesh_face_lines(path, MESH) is None


@pytest.mark.skipif(not os.environ.get(REAL_HDF_ENV), reason=f"set {REAL_HDF_ENV} to a HEC-RAS HDF")
def test_real_file_face_lines_match_the_loop_natively_and_in_numpy():
    path = os.environ[REAL_HDF_ENV]
    with h5py.File(path, "r") as hdf:
        for mesh in HdfMesh.get_mesh_area_names(path):
            base = f"Geometry/2D Flow Areas/{mesh}/"
            tables = [hdf[base + name][()] for name in (
                "Faces FacePoint Indexes", "FacePoints Coordinate",
                "Faces Perimeter Info", "Faces Perimeter Values")]
            expected = shapely.to_wkb(_loop(*tables))
            assert list(shapely.to_wkb(_from_packed(_packed_face_lines(*tables)))) == list(expected)
            if fast_hdf.available():
                native = fast_hdf.mesh_face_lines(path, mesh, backend="native")
                if native is not None:
                    assert list(shapely.to_wkb(_from_packed(native))) == list(expected)
