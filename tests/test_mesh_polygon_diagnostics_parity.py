"""Auto-mode cell-polygon diagnostics equal the Python reference (API re-audit P2-N4).

In auto mode the native polygonizer may only return when its diagnostic records
(status, reason code, counts, face IDs), its warnings and its strict-mode
outcome are provably the reference ones; otherwise the Python polygonizer runs.
Each case compares ``backend="auto"`` with ``backend="python"`` on:

- the returned cells (identity and normalized geometry),
- ``attrs["cell_polygon_diagnostics"]`` and ``diagnose_mesh_cell_polygons()``,
- the WARNING records (logger and message),
- ``strict=True`` (same exception type and message, or the same result),

and records whether the native result or the reference polygonizer served
auto mode, so the cheap native path is kept where it is provably equal.

Real fixtures: set ``RAS_MESH_DIAGNOSTIC_FIXTURES`` (or
``RAS_FLUVIAL_PUBLIC_FIXTURES``) to the folder holding
``JUL2020_D100RAS.p04.hdf`` (two ``no_polygon`` cells) and
``BaldEagleDamBrk.p18.hdf``; missing fixtures are skipped, never passed.
"""
import logging
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
import shapely
from pyproj import CRS

from ras_commander import fast_hdf
from ras_commander.hdf.HdfMesh import HdfMesh

pytestmark = pytest.mark.skipif(not fast_hdf.available(), reason="native extension unavailable")

MESH = "Parity Mesh"

# Point table shared by every case.
POINTS = np.array([
    [0, 0], [1, 0], [1, 1], [0, 1],           # 0-3: unit square
    [2, 0], [3, 0], [3, 1], [2, 1],           # 4-7: open ring
    [4, 0], [5, 0], [4.5, 1],                 # 8-10: triangle one
    [6, 0], [7, 0], [6.5, 1],                 # 11-13: triangle two
    [8, 0], [9, 0],                           # 14-15: lens endpoints
], dtype=float)

FACES = [
    (0, 1), (1, 2), (2, 3), (3, 0),          # 0-3 square
    (4, 5), (5, 6), (6, 7),                  # 4-6 open ring
    (8, 9), (9, 10), (10, 8),                # 7-9 triangle one
    (11, 12), (12, 13), (13, 11),            # 10-12 triangle two
    (14, 15), (15, 14),                      # 13-14 lens: straight + curved back
    (4, 7),                                  # 15 boundary face
]
# Face 14 runs back from point 15 to 14 through (8.5, 1): faces 13 and 14
# close a triangle with only two faces.
PERIMETER = {14: [[8.5, 1.0]]}

CASES = {
    "clean": [[0, 1, 2, 3], [15]],
    "boundary_only": [[0, 1, 2, 3], [15], [4, 5]],
    "zero_faces": [[0, 1, 2, 3], []],
    "open_ring_no_polygon": [[0, 1, 2, 3], [4, 5, 6]],
    "ambiguous_two_rings": [[0, 1, 2, 3], [7, 8, 9, 10, 11, 12]],
    "two_face_lens": [[0, 1, 2, 3], [13, 14]],
    "missing_face_reference": [[0, 1, 2, 3], [0, 1, 99]],
    "combined": [[0, 1, 2, 3], [4, 5, 6], [7, 8, 9, 10, 11, 12], [15], []],
}


def _write(path, cells):
    info, values = [], []
    for faces in cells:
        info.append([len(values), len(faces)])
        values.extend([face, 1] for face in faces)
    perimeter_info, perimeter_values = [], []
    for face in range(len(FACES)):
        extra = PERIMETER.get(face, [])
        perimeter_info.append([len(perimeter_values), len(extra)])
        perimeter_values.extend(extra)
    attributes = np.zeros(1, dtype=[("Name", "S64")])
    attributes["Name"] = MESH.encode()
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        base = f"Geometry/2D Flow Areas/{MESH}"
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attributes)
        hdf.create_dataset(f"{base}/FacePoints Coordinate", data=POINTS)
        hdf.create_dataset(f"{base}/Faces FacePoint Indexes", data=np.asarray(FACES, dtype=np.int32))
        hdf.create_dataset(f"{base}/Faces Perimeter Info", data=np.asarray(perimeter_info, dtype=np.int32))
        hdf.create_dataset(f"{base}/Faces Perimeter Values",
                           data=np.asarray(perimeter_values, dtype=float).reshape(-1, 2))
        hdf.create_dataset(f"{base}/Cells Face and Orientation Info", data=np.asarray(info, dtype=np.int32))
        hdf.create_dataset(f"{base}/Cells Face and Orientation Values",
                           data=np.asarray(values, dtype=np.int32).reshape(-1, 2))
    return path


def _warnings(caplog):
    return [(r.name, r.getMessage()) for r in caplog.records if r.levelno >= logging.WARNING]


def _call(caplog, *args, **kwargs):
    caplog.clear()
    try:
        out = HdfMesh.get_mesh_cell_polygons(*args, **kwargs)
    except Exception as exc:  # compared, not swallowed
        return ("raised", type(exc), str(exc)), _warnings(caplog)
    return out, _warnings(caplog)


def _assert_same_cells(auto, python):
    assert list(auto.columns) == list(python.columns)
    assert auto["mesh_name"].tolist() == python["mesh_name"].tolist()
    assert auto["cell_id"].tolist() == python["cell_id"].tolist()
    assert auto["cell_id"].dtype == python["cell_id"].dtype
    assert auto.crs == python.crs
    if len(python):
        assert np.all(shapely.equals(shapely.normalize(auto.geometry.values),
                                     shapely.normalize(python.geometry.values)))


def _compare(path, caplog, monkeypatch):
    """Assert auto == python; return how auto mode was served."""
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    served = []
    original = HdfMesh._reference_mesh_cell_polygons

    def reference(*args, **kwargs):
        served.append("reference")
        return original(*args, **kwargs)
    with caplog.at_level(logging.WARNING):
        python, python_warnings = _call(caplog, path, backend="python")
        monkeypatch.setattr(HdfMesh, "_reference_mesh_cell_polygons", staticmethod(reference))
        auto, auto_warnings = _call(caplog, path, backend="auto")
        auto_served = served[:] or ["native"]
        _assert_same_cells(auto, python)
        assert auto.attrs["cell_polygon_diagnostics"] == python.attrs["cell_polygon_diagnostics"]
        assert auto_warnings == python_warnings
        pd.testing.assert_frame_equal(
            HdfMesh.diagnose_mesh_cell_polygons(path, backend="auto"),
            HdfMesh.diagnose_mesh_cell_polygons(path, backend="python"))
        monkeypatch.setattr(HdfMesh, "_reference_mesh_cell_polygons", staticmethod(original))
        python_strict, python_strict_warnings = _call(caplog, path, backend="python", strict=True)
        auto_strict, auto_strict_warnings = _call(caplog, path, backend="auto", strict=True)
    if isinstance(python_strict, tuple):
        assert auto_strict == python_strict
    else:
        _assert_same_cells(auto_strict, python_strict)
        assert auto_strict.attrs == python_strict.attrs
    assert auto_strict_warnings == python_strict_warnings
    return auto_served, python.attrs["cell_polygon_diagnostics"]


# Native serves auto mode where its records are provably the reference's.
EXPECTED_SERVER = {
    "clean": "native",
    "boundary_only": "native",
    "zero_faces": "native",
    "open_ring_no_polygon": "either",  # native refuses the open chain (TopologyError)
    "ambiguous_two_rings": "reference",
    "two_face_lens": "either",  # native leaves it unassembled: boundary_only, as the reference
    "missing_face_reference": "reference",
    "combined": "reference",
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_auto_diagnostics_equal_reference(tmp_path, caplog, monkeypatch, case):
    path = _write(tmp_path / f"{case}.g01.hdf", CASES[case])
    served, records = _compare(path, caplog, monkeypatch)
    # Native may refuse a layout itself (any failure falls back), so only the
    # cases that must not be served natively are asserted strictly.
    if EXPECTED_SERVER[case] == "reference":
        assert served == ["reference"], records
    elif EXPECTED_SERVER[case] == "native":
        assert served == ["native"], records


def test_ambiguous_case_really_is_ambiguous_in_the_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    path = _write(tmp_path / "ambiguous.g01.hdf", CASES["ambiguous_two_rings"])
    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(path, backend="auto")
    assert diagnostics[["cell_id", "status", "reason_code", "polygon_count"]].values.tolist() == [
        [1, "ambiguous", "multiple_polygons", 2]]


def test_open_ring_gets_the_reference_reason_code(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    path = _write(tmp_path / "open.g01.hdf", CASES["open_ring_no_polygon"])
    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(path, backend="auto")
    assert diagnostics[["cell_id", "status", "reason_code"]].values.tolist() == [
        [1, "omitted", "no_polygon"]]


def _fixture(name):
    root = os.environ.get("RAS_MESH_DIAGNOSTIC_FIXTURES") or os.environ.get("RAS_FLUVIAL_PUBLIC_FIXTURES")
    path = Path(root or "missing") / name
    if not path.exists():
        pytest.skip(f"fixture unavailable: {path}")
    return path


@pytest.mark.parametrize("name,expected", [
    ("JUL2020_D100RAS.p04.hdf", {("omitted", "no_polygon"), ("boundary_only", "insufficient_faces")}),
    ("BaldEagleDamBrk.p18.hdf", {("boundary_only", "insufficient_faces")}),
])
def test_real_fixture_auto_diagnostics_equal_reference(caplog, monkeypatch, name, expected):
    served, records = _compare(_fixture(name), caplog, monkeypatch)
    assert {(r["status"], r["reason_code"]) for r in records} == expected
    # Both fixtures are provably equal, so the native path keeps serving them.
    assert served == ["native"]


@pytest.fixture
def native_drops_cell_zero(monkeypatch):
    """Simulate a native assembly that leaves a polygonizable cell unassembled.

    Before the P2-N4 guard, auto mode returned such a result as is: the cell
    was missing from the frame and labelled boundary_only/insufficient_faces,
    while the reference returns its polygon and no record.
    """
    module = fast_hdf._native("auto")
    original = module.assemble_cells

    def assemble_cells(*args, threads=None, strict=True, return_diagnostics=False):
        result = original(*args, threads=threads, strict=strict, return_diagnostics=return_diagnostics)
        coordinates, offsets, cell_ids = result[:3]
        keep = np.asarray(cell_ids) != 0
        assert not keep.all(), "fixture expects native to assemble cell 0"
        first = int(offsets[1])
        trimmed = (np.asarray(coordinates)[first:], np.asarray(offsets)[1:] - first,
                   np.asarray(cell_ids)[1:])
        return trimmed + tuple(result[3:])
    monkeypatch.setattr(module, "assemble_cells", assemble_cells)


def test_unproven_native_omission_falls_back_to_reference(tmp_path, caplog, monkeypatch, native_drops_cell_zero):
    path = _write(tmp_path / "dropped.g01.hdf", CASES["boundary_only"])
    served, records = _compare(path, caplog, monkeypatch)
    assert served == ["reference"]
    assert [r["cell_id"] for r in records] == [1, 2]


def test_reference_missing_cell_rules():
    from ras_commander.fast_hdf import _reference_missing_cell
    path_cells = CASES["combined"]
    info, values = [], []
    for faces in path_cells:
        info.append([len(values), len(faces)])
        values.extend([face, 1] for face in faces)
    perimeter_info, perimeter_values = [], []
    for face in range(len(FACES)):
        extra = PERIMETER.get(face, [])
        perimeter_info.append([len(perimeter_values), len(extra)])
        perimeter_values.extend(extra)
    args = (POINTS, np.asarray(FACES, dtype=np.int64), np.asarray(perimeter_info, dtype=np.int64),
            np.asarray(perimeter_values, dtype=float).reshape(-1, 2), np.asarray(info, dtype=np.int64),
            np.asarray(values, dtype=np.int64).reshape(-1, 2))
    rule = lambda cell, invalid=False: _reference_missing_cell(args, *map(int, args[4][cell]), invalid)
    assert rule(0) is None                       # the square polygonizes: not an omission
    assert rule(1) == "no_polygon"               # open ring
    assert rule(1, invalid=True) == "no_polygon"
    assert rule(2) is None                       # two rings: ambiguous in the reference
    assert rule(3) == "boundary_only"
    assert rule(3, invalid=True) is None         # the reference says boundary_only, native no_polygon
    assert rule(4) == "zero_faces"
    assert _reference_missing_cell(args, len(values), 1, False) is None   # invalid span
    bad = args[:5] + (np.array([[99, 1]], dtype=np.int64),)
    assert _reference_missing_cell(bad, 0, 1, False) is None             # missing face reference
