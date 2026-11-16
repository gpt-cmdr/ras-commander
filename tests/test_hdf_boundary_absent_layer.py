"""Empty compiled boundary inventory retains its geospatial contract."""

import h5py
import pytest
from pyproj import CRS

module = __import__("ras_commander.hdf.HdfBndry", fromlist=["*"])


def test_missing_bc_group_is_not_invented_and_preserves_source_crs(tmp_path):
    path = tmp_path / "model.g01.hdf"
    with h5py.File(path, "w") as handle:
        handle.attrs["Projection"] = CRS.from_epsg(3452).to_wkt()
        handle.create_group("Geometry/2D Flow Areas")
    before = path.read_bytes()
    frame = module.HdfBndry.get_bc_lines(path)
    assert frame.empty and frame.geometry.name == "geometry"
    assert frame.crs.to_epsg() == 3452
    assert frame.attrs["boundary_condition_lines"]["status"] == "not_present_in_hdf"
    assert path.read_bytes() == before


def test_absent_projection_is_not_relabelled(tmp_path):
    path = tmp_path / "model.g01.hdf"
    with h5py.File(path, "w") as handle:
        handle.create_group("Geometry")
    frame = module.HdfBndry.get_bc_lines(path)
    assert frame.empty and frame.geometry.name == "geometry" and frame.crs is None


def test_existing_malformed_group_is_error_not_empty(tmp_path):
    path = tmp_path / "model.g01.hdf"
    with h5py.File(path, "w") as handle:
        handle.create_group("Geometry/Boundary Condition Lines")
    with pytest.raises((ValueError, KeyError)):
        module.HdfBndry.get_bc_lines(path)
