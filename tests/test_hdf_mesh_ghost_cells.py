"""Ghost cells in 2D mesh cell results.

HEC-RAS writes one result column per entry in ``Cells Center Coordinate``:
the physical cells, then ghost cells outside the mesh perimeter.
``Geometry/2D Flow Areas/Attributes`` ``Cell Count`` is the physical count.
Mesh polygons cover only the physical cells, so ghost values must be
identifiable (``is_ghost_cell``) and are excluded by default
(``include_ghost_cells=True`` keeps them). Ghost values are placeholders: the
summary maxima are 0.0 and the minimum elevation is NaN.

The synthetic layout mirrors real plan HDFs, for example BaldEagleCrkMulti2D
p07 (89,879 result columns, Cell Count 87,039) and DavisStormSystem p02
(area2: 2,941 columns, Cell Count 2,705).
"""
from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfMesh import HdfMesh
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
from ras_commander.hdf.HdfResultsQuery import HdfResultsQuery

MESH = "Area"
PHYSICAL = 4
GHOSTS = 2
BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
TIME_BASE = f"{BASE}/Unsteady Time Series"
SUMMARY = f"{BASE}/Summary Output/2D Flow Areas/{MESH}"


def _write_hdf(path: Path, *, with_cell_count: bool = True) -> Path:
    """Write a plan HDF with embedded geometry and ghost cells after the physical cells."""
    total = PHYSICAL + GHOSTS
    wse = np.arange(3 * total, dtype=np.float32).reshape(3, total) + 100.0
    summary_max = wse.max(axis=0)
    summary_max[PHYSICAL:] = 0.0  # HEC-RAS writes 0.0 for ghost cells
    min_elev = np.full(total, 99.0)
    min_elev[PHYSICAL:] = np.nan  # ghost cells have no terrain
    with h5py.File(path, "w") as f:
        f.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        f.require_group("Plan Data/Plan Information").attrs[
            "Simulation Start Time"
        ] = "01Jan2024 00:00:00"
        f.create_dataset(f"{TIME_BASE}/Time", data=np.arange(3) / 24.0)
        f.create_dataset(
            f"{TIME_BASE}/Time Date Stamp (ms)",
            data=np.array(
                [f"01Jan2024 0{h}:00:00:000".encode() for h in range(3)], dtype="S24"
            ),
        )
        if with_cell_count:
            dtype = np.dtype([("Name", "S16"), ("Cell Count", "i4")])
            row = (MESH.encode(), PHYSICAL)
        else:
            dtype = np.dtype([("Name", "S16")])
            row = (MESH.encode(),)
        f.create_dataset(
            "Geometry/2D Flow Areas/Attributes", data=np.array([row], dtype=dtype)
        )
        geo = f"Geometry/2D Flow Areas/{MESH}"
        # Physical centers at x = 0..3; ghost centers at x = 4, 5 (perimeter side).
        f.create_dataset(
            f"{geo}/Cells Center Coordinate",
            data=np.column_stack([np.arange(total, dtype=float), np.zeros(total)]),
        )
        f.create_dataset(f"{geo}/Cells Minimum Elevation", data=min_elev)
        f.create_dataset(f"{TIME_BASE}/2D Flow Areas/{MESH}/Water Surface", data=wse)
        f.create_dataset(
            f"{TIME_BASE}/2D Flow Areas/{MESH}/Face Velocity",
            data=np.ones((3, 5), dtype=np.float32),
        )
        f.create_dataset(
            f"{SUMMARY}/Maximum Water Surface",
            data=np.vstack([summary_max, np.full(total, 2 / 24)]),
        )
        f.create_dataset(
            f"{geo}/Faces FacePoint Indexes", data=np.zeros((5, 2), dtype=int)
        )
    return path


@pytest.fixture
def hdf(tmp_path):
    return _write_hdf(tmp_path / "ghost.p01.hdf")


def test_summary_values_exclude_ghost_cells_by_default(hdf):
    physical = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")
    assert physical["cell_id"].tolist() == list(range(PHYSICAL))
    assert not physical["is_ghost_cell"].any()
    assert (physical["maximum_water_surface"] > 0).all()

    full = HdfResultsMesh.get_mesh_summary_values(
        hdf, "Maximum Water Surface", include_ghost_cells=True
    )
    assert len(full) == PHYSICAL + GHOSTS
    assert full["is_ghost_cell"].tolist() == [False] * PHYSICAL + [True] * GHOSTS
    assert full.loc[full["is_ghost_cell"], "maximum_water_surface"].eq(0.0).all()


def test_max_ws_geodataframe_excludes_ghost_cells(hdf):
    physical = HdfResultsMesh.get_mesh_max_ws(hdf)
    assert len(physical) == PHYSICAL
    full = HdfResultsMesh.get_mesh_max_ws(hdf, include_ghost_cells=True)
    assert int(full["is_ghost_cell"].sum()) == GHOSTS


def test_max_depth_excludes_ghost_cells(hdf):
    physical = HdfResultsMesh.get_mesh_max_depth(hdf)
    assert len(physical) == PHYSICAL
    assert physical["maximum_depth"].notna().all()
    full = HdfResultsMesh.get_mesh_max_depth(hdf, include_ghost_cells=True)
    assert int(full["is_ghost_cell"].sum()) == GHOSTS


def test_timeseries_excludes_ghost_cells_by_default(hdf):
    physical = HdfResultsMesh.get_mesh_timeseries(hdf, MESH, "Water Surface", truncate=False)
    assert physical.sizes["cell_id"] == PHYSICAL
    assert not physical["is_ghost_cell"].values.any()

    full = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Water Surface", truncate=False, include_ghost_cells=True
    )
    assert full.sizes["cell_id"] == PHYSICAL + GHOSTS
    assert full["is_ghost_cell"].values.tolist() == [False] * PHYSICAL + [True] * GHOSTS
    np.testing.assert_array_equal(physical.values, full.values[:, :PHYSICAL])

    view = HdfResultsMesh.get_mesh_timeseries(hdf, MESH, "Water Surface", return_type="view")
    assert view.shape[1] == PHYSICAL

    batches = list(HdfResultsMesh.iter_mesh_timeseries(hdf, MESH, "Water Surface"))
    assert all(batch.sizes["cell_id"] == PHYSICAL for batch in batches)


def test_timeseries_selection_is_clipped_to_physical_cells(hdf):
    clipped = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Water Surface", truncate=False, spatial_selection=slice(2, None)
    )
    assert clipped["cell_id"].values.tolist() == [2, 3]

    last = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Water Surface", truncate=False, spatial_selection=-1
    )
    assert last["cell_id"].values.tolist() == [PHYSICAL - 1]

    with pytest.raises(ValueError, match="ghost cell"):
        HdfResultsMesh.get_mesh_timeseries(
            hdf, MESH, "Water Surface", spatial_selection=PHYSICAL
        )

    ghost = HdfResultsMesh.get_mesh_timeseries(
        hdf,
        MESH,
        "Water Surface",
        truncate=False,
        spatial_selection=PHYSICAL,
        include_ghost_cells=True,
    )
    assert ghost["is_ghost_cell"].values.tolist() == [True]


def test_face_variables_are_unaffected(hdf):
    faces = HdfResultsMesh.get_mesh_timeseries(hdf, MESH, "Face Velocity", truncate=False)
    assert faces.sizes["face_id"] == 5
    assert "is_ghost_cell" not in faces.coords


def test_cells_timeseries_dataset(hdf):
    physical = HdfResultsMesh.get_mesh_cells_timeseries(hdf, var="Water Surface")[MESH]
    assert physical.sizes["cell_id"] == PHYSICAL
    full = HdfResultsMesh.get_mesh_cells_timeseries(
        hdf, var="Water Surface", include_ghost_cells=True
    )[MESH]
    assert int(full["is_ghost_cell"].sum()) == GHOSTS


def test_missing_cell_count_keeps_all_cells_with_warning(tmp_path, caplog):
    hdf = _write_hdf(tmp_path / "no_count.p01.hdf", with_cell_count=False)
    with caplog.at_level(logging.WARNING):
        values = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")
        series = HdfResultsMesh.get_mesh_cells_timeseries(hdf)[MESH]
    assert len(values) == PHYSICAL + GHOSTS
    assert not values["is_ghost_cell"].any()
    assert series.sizes["cell_id"] == PHYSICAL + GHOSTS
    assert "ghost cells cannot be identified" in caplog.text


def test_cell_points_can_exclude_ghost_cells(hdf):
    assert len(HdfMesh.get_mesh_cell_points(hdf)) == PHYSICAL + GHOSTS
    physical = HdfMesh.get_mesh_cell_points(hdf, include_ghost_cells=False)
    assert physical["cell_id"].tolist() == list(range(PHYSICAL))


def test_point_query_never_snaps_to_a_ghost_cell(hdf):
    """A point beside the last physical cell is nearer a ghost center."""
    point = np.array([[3.9, 0.0]])
    wse = HdfResultsQuery.query_points(hdf, point, variable="wse", time_index="max")
    assert int(wse["cell_id"].iloc[0]) == PHYSICAL - 1
    assert float(wse["value"].iloc[0]) == pytest.approx(100.0 + 2 * (PHYSICAL + GHOSTS) + 3)
    depth = HdfResultsQuery.query_points(hdf, point, variable="depth", time_index="max")
    assert np.isfinite(depth["value"].iloc[0])
    current = HdfResultsQuery.query_points(hdf, point, variable="wse", time_index=-1)
    assert int(current["cell_id"].iloc[0]) == PHYSICAL - 1
