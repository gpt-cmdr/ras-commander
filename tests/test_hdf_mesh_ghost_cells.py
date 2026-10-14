"""Ghost cells in 2D mesh cell results.

HEC-RAS writes one result column per entry in ``Cells Center Coordinate``:
the physical cells, then ghost cells outside the mesh perimeter.
``Geometry/2D Flow Areas/Attributes`` ``Cell Count`` is the physical count.
Mesh polygons cover only the physical cells, so ghost values must be
identifiable (``is_ghost_cell``) and removable (``include_ghost_cells=False``).

The synthetic layout mirrors real plan HDFs, for example BaldEagleCrkMulti2D
p07 (89,879 result columns, Cell Count 87,039) and DavisStormSystem p02
(area2: 2,941 columns, Cell Count 2,705).
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

MESH = "Area"
PHYSICAL = 4
GHOSTS = 2
BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
TIME_BASE = f"{BASE}/Unsteady Time Series"
SUMMARY = f"{BASE}/Summary Output/2D Flow Areas/{MESH}"


def _write_hdf(path: Path, *, with_cell_count: bool = True) -> Path:
    total = PHYSICAL + GHOSTS
    wse = np.arange(3 * total, dtype=np.float32).reshape(3, total) + 100.0
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
        f.create_dataset(
            f"{geo}/Cells Center Coordinate",
            data=np.column_stack([np.arange(total, dtype=float), np.zeros(total)]),
        )
        f.create_dataset(f"{geo}/Cells Minimum Elevation", data=np.full(total, 99.0))
        f.create_dataset(f"{TIME_BASE}/2D Flow Areas/{MESH}/Water Surface", data=wse)
        f.create_dataset(
            f"{TIME_BASE}/2D Flow Areas/{MESH}/Face Velocity",
            data=np.ones((3, 5), dtype=np.float32),
        )
        f.create_dataset(
            f"{SUMMARY}/Maximum Water Surface",
            data=np.vstack([wse.max(axis=0), np.full(total, 2 / 24)]),
        )
    return path


@pytest.fixture
def hdf(tmp_path):
    return _write_hdf(tmp_path / "ghost.p01.hdf")


def test_summary_values_flag_and_drop_ghost_cells(hdf):
    values = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")
    assert len(values) == PHYSICAL + GHOSTS
    assert values["is_ghost_cell"].tolist() == [False] * PHYSICAL + [True] * GHOSTS

    physical = HdfResultsMesh.get_mesh_summary_values(
        hdf, "Maximum Water Surface", include_ghost_cells=False
    )
    assert physical["cell_id"].tolist() == list(range(PHYSICAL))
    assert not physical["is_ghost_cell"].any()


def test_max_ws_geodataframe_drops_ghost_cells(hdf):
    full = HdfResultsMesh.get_mesh_max_ws(hdf)
    assert int(full["is_ghost_cell"].sum()) == GHOSTS
    physical = HdfResultsMesh.get_mesh_max_ws(hdf, include_ghost_cells=False)
    assert len(physical) == PHYSICAL


def test_max_depth_flags_ghost_cells(hdf):
    full = HdfResultsMesh.get_mesh_max_depth(hdf)
    assert int(full["is_ghost_cell"].sum()) == GHOSTS
    assert len(HdfResultsMesh.get_mesh_max_depth(hdf, include_ghost_cells=False)) == PHYSICAL


def test_timeseries_coordinate_and_exclusion(hdf):
    full = HdfResultsMesh.get_mesh_timeseries(hdf, MESH, "Water Surface", truncate=False)
    assert full.sizes["cell_id"] == PHYSICAL + GHOSTS
    assert full["is_ghost_cell"].values.tolist() == [False] * PHYSICAL + [True] * GHOSTS

    physical = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Water Surface", truncate=False, include_ghost_cells=False
    )
    assert physical.sizes["cell_id"] == PHYSICAL
    np.testing.assert_array_equal(physical.values, full.values[:, :PHYSICAL])

    view = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Water Surface", include_ghost_cells=False, return_type="view"
    )
    assert view.shape[1] == PHYSICAL

    batches = list(
        HdfResultsMesh.iter_mesh_timeseries(
            hdf, MESH, "Water Surface", include_ghost_cells=False
        )
    )
    assert all(batch.sizes["cell_id"] == PHYSICAL for batch in batches)


def test_timeseries_selection_is_clipped_to_physical_cells(hdf):
    clipped = HdfResultsMesh.get_mesh_timeseries(
        hdf,
        MESH,
        "Water Surface",
        truncate=False,
        spatial_selection=slice(2, None),
        include_ghost_cells=False,
    )
    assert clipped["cell_id"].values.tolist() == [2, 3]

    with pytest.raises(ValueError, match="ghost cell"):
        HdfResultsMesh.get_mesh_timeseries(
            hdf, MESH, "Water Surface", spatial_selection=-1, include_ghost_cells=False
        )


def test_face_variables_are_unaffected(hdf):
    faces = HdfResultsMesh.get_mesh_timeseries(
        hdf, MESH, "Face Velocity", truncate=False, include_ghost_cells=False
    )
    assert faces.sizes["face_id"] == 5
    assert "is_ghost_cell" not in faces.coords


def test_cells_timeseries_dataset(hdf):
    full = HdfResultsMesh.get_mesh_cells_timeseries(hdf, var="Water Surface")[MESH]
    assert int(full["is_ghost_cell"].sum()) == GHOSTS
    physical = HdfResultsMesh.get_mesh_cells_timeseries(
        hdf, var="Water Surface", include_ghost_cells=False
    )[MESH]
    assert physical.sizes["cell_id"] == PHYSICAL


def test_exclusion_requires_cell_count(tmp_path):
    hdf = _write_hdf(tmp_path / "no_count.p01.hdf", with_cell_count=False)
    values = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")
    assert not values["is_ghost_cell"].any()
    with pytest.raises(ValueError, match="Cell Count"):
        HdfResultsMesh.get_mesh_summary_values(
            hdf, "Maximum Water Surface", include_ghost_cells=False
        )
