"""Mapping-only plan HDF cell subsets on independent native-layout grid meshes."""

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest
from test_mesh_cell_subset import grid

from ras_commander.geom._cell_subset import _build_subset
from ras_commander.hdf import HdfResultsMesh

AREA = "Geometry/2D Flow Areas/Area"
SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
SERIES_AREA = SERIES + "/2D Flow Areas/Area"
SUMMARY_AREA = "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/Area"
TIMES = 4


def plan(path: Path, results: bool = True, version: str = "HEC-RAS 6.6 September 2024"):
    """Turn the grid geometry fixture into a 6.6-layout plan HDF with results."""
    tables = grid(path)
    n_cells = len(tables["Cells Center Coordinate"])
    n_faces = len(tables["Faces Cell Indexes"])
    with h5py.File(path, "r+") as h:
        h.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        h.attrs["File Version"] = np.bytes_(version)
        h.create_group("Plan Data/Plan Information").attrs["Plan Name"] = b"p"
        h.create_group("Event Conditions/Meteorology/Precipitation")
        h.create_dataset("Event Conditions/Unsteady/Initial Conditions/x", data=[1])
        h.create_dataset(AREA + "/Infiltration/Curve Number", data=np.ones(16))
        h.create_dataset(
            "Geometry/Boundary Condition Lines/Attributes", data=np.zeros(1)
        )
        if not results:
            return tables
        h.require_group("Results/Unsteady").attrs["Short ID"] = b"p"
        h.create_dataset("Results/Unsteady/Summary/Compute Messages", data=b"ok")
        h.create_dataset(SERIES + "/Time", data=np.arange(TIMES, dtype=float))
        stamps = np.array([f"01JAN2000 0{t}:00:00".encode() for t in range(TIMES)])
        h.create_dataset(SERIES + "/Time Date Stamp", data=stamps)
        h.create_dataset(SERIES + "/Reference Lines/Flow", data=np.zeros((TIMES, 1)))
        t = np.arange(TIMES)[:, None]
        h.create_dataset(
            SERIES_AREA + "/Water Surface", data=1000.0 * t + np.arange(n_cells)
        )
        for name in ("Face Velocity", "Face Water Surface", "Face Mystery Term"):
            h.create_dataset(
                SERIES_AREA + "/" + name, data=1000.0 * t + np.arange(1, n_faces + 1)
            )
        h.create_dataset(
            SERIES_AREA + "/Computations/Max Courant", data=np.zeros((TIMES, 1))
        )
        h.create_dataset(
            SERIES_AREA + "/Boundary Conditions/BC", data=np.zeros((TIMES, 2))
        )
        h.create_dataset(
            SUMMARY_AREA + "/Maximum Water Surface",
            data=np.stack([np.arange(n_cells, dtype=float), np.full(n_cells, 2.0)]),
        )
        h.create_dataset(
            SUMMARY_AREA + "/Maximum Face Velocity",
            data=np.stack(
                [np.arange(1, n_faces + 1, dtype=float), np.full(n_faces, 3.0)]
            ),
        )
        h.create_dataset(
            SUMMARY_AREA + "/Starting Differences WSE", data=np.zeros((3, n_cells))
        )
    return tables


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_child_keeps_exact_topology_and_maps_results(tmp_path):
    parent = tmp_path / "Parent.p01.hdf"
    plan(parent)
    before = sha(parent)
    ids = [5, 6, 9, 10]
    sub = HdfResultsMesh.write_cell_subset(
        parent, tmp_path / "Child.p01.hdf", ids, "Area"
    )
    assert sha(parent) == before
    with h5py.File(parent) as h:
        keep = np.zeros(16, bool)
        keep[ids] = True
        expected = _build_subset(h[AREA], keep)
        ws = h[SERIES_AREA + "/Water Surface"][()]
        fv = h[SERIES_AREA + "/Face Velocity"][()]
        fws = h[SERIES_AREA + "/Face Water Surface"][()]
        smax = h[SUMMARY_AREA + "/Maximum Face Velocity"][()]
    with h5py.File(sub.child_plan_hdf) as c:
        for name, values in expected.tables.items():
            assert np.array_equal(c[AREA + "/" + name][()], values, equal_nan=True), (
                name
            )
        assert c["Geometry/2D Flow Areas/Attributes"][0]["Cell Count"] == 4
        assert np.array_equal(
            c["Geometry/2D Flow Areas/Polygon Points"][()], sub.perimeter
        )
        child_ws = c[SERIES_AREA + "/Water Surface"][()]
        child_fv = c[SERIES_AREA + "/Face Velocity"][()]
        child_fws = c[SERIES_AREA + "/Face Water Surface"][()]
        child_smax = c[SUMMARY_AREA + "/Maximum Face Velocity"][()]
        assert "Face Mystery Term" not in c[SERIES_AREA]
        assert "Computations" not in c[SERIES_AREA]
        assert "Meteorology" not in c["Event Conditions"]
        assert "Initial Conditions" in c["Event Conditions/Unsteady"]
        assert "Boundary Condition Lines" not in c["Geometry"]
        assert "Infiltration" not in c[AREA]
        assert c["Results/Unsteady/Summary/Compute Messages"][()] == b"ok"
    assert np.array_equal(sub.cell_source, expected.cell_src)
    assert np.array_equal(child_ws, ws[:, sub.cell_source])
    # The ghost below cell 5 takes the dropped neighbour's value (cell 1).
    ghosts = list(sub.cell_source[4:])
    assert sub.ghost_cell_count == len(ghosts) == 8
    assert np.array_equal(child_ws[:, 4 + ghosts.index(1)], ws[:, 1])
    sign = np.where(sub.face_reversed, -1.0, 1.0)
    assert sub.reversed_face_count > 0
    assert np.array_equal(child_fv, fv[:, sub.face_source] * sign)
    assert np.array_equal(child_fws, fws[:, sub.face_source])
    assert np.array_equal(child_smax[0], smax[0, sub.face_source] * sign)
    assert np.array_equal(child_smax[1], smax[1, sub.face_source])
    dropped = set(sub.dropped)
    assert "/" + SERIES_AREA + "/Face Mystery Term" in dropped
    assert "/" + SUMMARY_AREA + "/Starting Differences WSE" in dropped
    record = sub.to_dict()
    assert record["schema"] == "ras-mesh-results-subset/v1"
    assert record["physical_cell_count"] == 4
    assert record["hydraulic_validity"] == "not_established"
    assert "cell_source" not in record


def test_unclassified_face_results_are_kept_without_reversed_faces(tmp_path):
    parent = tmp_path / "Parent.p01.hdf"
    plan(parent)
    sub = HdfResultsMesh.write_cell_subset(
        parent, tmp_path / "Child.p01.hdf", [0], "Area"
    )
    assert sub.reversed_face_count == 0
    with h5py.File(sub.child_plan_hdf) as c:
        assert "Face Mystery Term" in c[SERIES_AREA]


def test_output_rows_select_and_order_time_axis(tmp_path):
    parent = tmp_path / "Parent.p01.hdf"
    plan(parent)
    sub = HdfResultsMesh.write_cell_subset(
        parent, tmp_path / "Child.p01.hdf", [5, 6], "Area", output_rows=[3, 1]
    )
    assert sub.output_rows == (3, 1)
    with h5py.File(sub.child_plan_hdf) as c:
        assert list(c[SERIES + "/Time"][()]) == [3.0, 1.0]
        assert c[SERIES + "/Time Date Stamp"][0] == b"01JAN2000 03:00:00"
        ws = c[SERIES_AREA + "/Water Surface"][()]
    assert np.array_equal(ws[:, 0], [3005.0, 1005.0])


def test_parent_without_results_writes_geometry_only_plan(tmp_path):
    parent = tmp_path / "Parent.p01.hdf"
    plan(parent, results=False)
    child = tmp_path / "Child.p01.hdf"
    sub = HdfResultsMesh.write_cell_subset(parent, child, [5, 6, 9, 10], "Area")
    assert not sub.has_results and sub.output_rows == ()
    with h5py.File(child) as c:
        assert "Results" not in c and "Plan Data" in c
    with pytest.raises(ValueError, match="no results"):
        HdfResultsMesh.write_cell_subset(
            parent, child, [5], "Area", output_rows=[0], overwrite=True
        )


@pytest.mark.parametrize(
    "case, error",
    [
        ("geometry", "plan HDF"),
        ("version", "qualified"),
        ("area", "not in the parent"),
        ("hole", "ring"),
        ("rows", "output_rows"),
        ("ghost", "physical"),
    ],
)
def test_unsupported_inputs_block_without_writing(tmp_path, case, error):
    parent = tmp_path / "Parent.p01.hdf"
    plan(
        parent,
        version="HEC-RAS 6.5 February 2024"
        if case == "version"
        else "HEC-RAS 6.6 September 2024",
    )
    if case == "geometry":
        with h5py.File(parent, "r+") as h:
            h.attrs["File Type"] = np.bytes_("HEC-RAS Geometry")
    ids = {"hole": [i for i in range(16) if i != 5], "ghost": [16]}.get(case, [5, 6])
    kwargs = {"output_rows": [0, 9]} if case == "rows" else {}
    child = tmp_path / "Child.p01.hdf"
    with pytest.raises(ValueError, match=error):
        HdfResultsMesh.write_cell_subset(
            parent, child, ids, "Nope" if case == "area" else "Area", **kwargs
        )
    assert not child.exists()
    assert not (tmp_path / "Child.p01.hdf.partial").exists()


def test_existing_child_and_same_path_are_refused(tmp_path):
    parent = tmp_path / "Parent.p01.hdf"
    plan(parent)
    child = tmp_path / "Child.p01.hdf"
    child.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        HdfResultsMesh.write_cell_subset(parent, child, [5], "Area")
    assert child.read_bytes() == b"keep"
    with pytest.raises(ValueError, match="differ"):
        HdfResultsMesh.write_cell_subset(parent, parent, [5], "Area", overwrite=True)
    HdfResultsMesh.write_cell_subset(parent, child, [5], "Area", overwrite=True)
    assert h5py.is_hdf5(child)
