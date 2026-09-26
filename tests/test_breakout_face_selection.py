"""Boundary partition topology, active-cell filtering, and orientation checks."""

import h5py
import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import box

from ras_commander import RasBreakout2D
from ras_commander.RasBreakout2D import BOUNDARY_FACE_COLUMNS
from ras_commander.hdf.HdfMesh import HdfMesh


@pytest.fixture
def mesh_hdf(tmp_path):
    path = tmp_path / "partition.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = CRS.from_epsg(6588).to_wkt()
        areas = hdf.create_group("Geometry/2D Flow Areas")
        areas["Attributes"] = np.array([(b"Mesh",)], dtype=[("Name", "S20")])
        areas["Cell Info"] = [[0, 3]]
        mesh = areas.create_group("Mesh")
        # Three active cells, then one exterior ghost.
        mesh["Cells Center Coordinate"] = [[0., 0.], [2., 0.], [4., 0.], [-2., 0.]]
        mesh["Faces Cell Indexes"] = [[0, 1], [2, 1], [0, 3], [0, -1], [0, 99]]
        mesh["Faces NormalUnitVector and Length"] = [[1., 0., 2.]] * 5
        mesh["Faces FacePoint Indexes"] = [[0, 1], [2, 3], [0, 1], [0, 1], [0, 1]]
        mesh["FacePoints Coordinate"] = [[1., -1.], [1., 1.], [3., -1.], [3., 1.]]
        mesh["Faces Perimeter Info"] = [[0, 1], [0, 0], [0, 0], [0, 0], [0, 0]]
        mesh["Faces Perimeter Values"] = [[1.25, 0.]]
    return path


def test_partition_preserves_schema_curves_normals_and_active_cells(mesh_hdf, monkeypatch):
    def disallow_full_geometry(*args, **kwargs):
        pytest.fail("Full mesh geometry must not be materialized")

    monkeypatch.setattr(HdfMesh, "get_mesh_cell_faces", disallow_full_geometry)
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_points", disallow_full_geometry)
    result = RasBreakout2D.select_parent_boundary_faces(mesh_hdf, "Mesh", box(-1, -2, 1, 2))
    assert list(result.columns) == BOUNDARY_FACE_COLUMNS
    assert result.face_id.tolist() == [0]
    assert result.inside_cell.tolist() == [0]
    assert result.outside_cell.tolist() == [1]
    assert result.orientation_multiplier.tolist() == [1.0]
    assert list(result.geometry.iloc[0].coords) == [(1, -1), (1.25, 0), (1, 1)]
    assert result.crs.to_epsg() == 6588


def test_reversed_cell_index_and_boundary_center_inclusion(mesh_hdf):
    result = RasBreakout2D.select_parent_boundary_faces(mesh_hdf, "Mesh", box(2, -2, 3, 2))
    assert set(result.face_id) == {0, 1}
    assert result.boundary_station.is_monotonic_increasing
    by_id = result.set_index("face_id")
    assert by_id.loc[0, "orientation_multiplier"] == -1.0
    assert by_id.loc[1, "orientation_multiplier"] == 1.0
    assert set(result.inside_cell) == {1}


def test_empty_partition_and_unorientable_face_fail(mesh_hdf):
    with pytest.raises(ValueError, match="No parent faces"):
        RasBreakout2D.select_parent_boundary_faces(mesh_hdf, "Mesh", box(10, 10, 11, 11))
    with h5py.File(mesh_hdf, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/Mesh/Faces NormalUnitVector and Length"][0] = [0, 1, 2]
    with pytest.raises(ValueError, match="normal cannot be oriented"):
        RasBreakout2D.select_parent_boundary_faces(mesh_hdf, "Mesh", box(-1, -2, 1, 2))


def test_geometry_attribute_count_overrides_zero_cell_info(mesh_hdf):
    # Real remeshed geometry HDFs may retain zero Cell Info counts until compute.
    with h5py.File(mesh_hdf, "r+") as hdf:
        areas = hdf["Geometry/2D Flow Areas"]
        del areas["Attributes"]
        areas["Attributes"] = np.array(
            [(b"Mesh", 3)], dtype=[("Name", "S20"), ("Cell Count", "i4")]
        )
        areas["Cell Info"][0] = [0, 0]
    result = RasBreakout2D.select_parent_boundary_faces(mesh_hdf, "Mesh", box(-1, -2, 1, 2))
    assert result.face_id.tolist() == [0]
