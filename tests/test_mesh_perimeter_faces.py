"""Complete perimeter inventory qualified against the HEC Weise 2D example."""

import hashlib
import shutil

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfBndry, HdfMesh, RasExamples


@pytest.fixture(scope="module")
def example_hdf(tmp_path_factory):
    # RasExamples owns project extraction and never modifies the archive.
    RasExamples._find_zip_file()
    if RasExamples._zip_file_path is None:
        pytest.skip(
            "HEC example archive unavailable; cache it with RasExamples.get_example_projects('6.6')"
        )
    folder = RasExamples.extract_project(
        "Weise_2D", output_path=tmp_path_factory.mktemp("perimeter")
    )
    path = folder / "Weise.g08.hdf"
    if not path.exists():
        pytest.skip("Cached HEC archive lacks the qualified Weise.g08.hdf example")
    return path


def test_complete_native_inventory_and_unassigned_faces(example_hdf):
    before = hashlib.sha256(example_hdf.read_bytes()).hexdigest()
    result = HdfMesh.get_mesh_perimeter_faces(str(example_hdf), "2DArea")
    assert isinstance(result, gpd.GeoDataFrame)
    with h5py.File(example_hdf, "r") as hdf:
        mesh = hdf["Geometry/2D Flow Areas/2DArea"]
        count = int(hdf["Geometry/2D Flow Areas/Attributes"][0]["Cell Count"])
        adjacency = mesh["Faces Cell Indexes"][:]
        expected = np.flatnonzero(
            ((adjacency >= 0) & (adjacency < count)).sum(axis=1) == 1
        )
        np.testing.assert_array_equal(result.face_id, expected)
        np.testing.assert_array_equal(result[["cell0", "cell1"]], adjacency[expected])
        np.testing.assert_allclose(
            result.face_length, mesh["Faces NormalUnitVector and Length"][expected, 2]
        )
        assert (result.interior_cell_id < count).all()
        assert (result.exterior_cell_id >= count).all()
        # One ghost in this real file has positive surface area; it remains exterior.
        assert (mesh["Cells Surface Area"][:][result.exterior_cell_id] > 0).any()
    assigned = HdfBndry.get_bc_external_faces(example_hdf)
    joined = result.dropna(subset=["bc_line_id"]).sort_values("face_id")
    native = assigned.sort_values("face_id")
    assert joined.face_id.tolist() == native.face_id.tolist()
    assert joined.bc_line_name.tolist() == native.bc_line_name.tolist()
    assert len(result) == 371
    assert result.bc_line_id.isna().sum() == 330
    assert result.geometry.length.gt(0).all()
    assert result.bc_line_id.dtype == pd.Int64Dtype()
    assert hashlib.sha256(example_hdf.read_bytes()).hexdigest() == before


def test_child_with_deliberately_unassigned_faces(example_hdf, tmp_path):
    child = tmp_path / "child.g01.hdf"
    shutil.copy2(example_hdf, child)
    with h5py.File(child, "r+") as hdf:
        group = hdf["Geometry/Boundary Condition Lines"]
        original = group["External Faces"][:]
        del group["External Faces"]
        group.create_dataset("External Faces", data=original[1:])
    result = HdfMesh.get_mesh_perimeter_faces(child, "2DArea")
    removed_face = int(original[0]["Face Index"])
    assert pd.isna(result.set_index("face_id").loc[removed_face, "bc_line_id"])
    assert result.bc_line_id.isna().sum() == 331
    assert len(result) == 371


@pytest.mark.parametrize("mutation", ["duplicate", "stale", "missing", "interior"])
def test_invalid_native_ownership_fails_closed(example_hdf, tmp_path, mutation):
    child = tmp_path / "bad.g01.hdf"
    shutil.copy2(example_hdf, child)
    with h5py.File(child, "r+") as hdf:
        group = hdf["Geometry/Boundary Condition Lines"]
        rows = group["External Faces"][:]
        del group["External Faces"]
        if mutation == "duplicate":
            rows = np.concatenate([rows, rows[:1]])
        elif mutation == "stale":
            rows[0]["FP Start Index"] += 1
        elif mutation == "interior":
            rows[0]["Face Index"] = 0
        if mutation != "missing":
            group.create_dataset("External Faces", data=rows)
    with pytest.raises(ValueError):
        HdfMesh.get_mesh_perimeter_faces(child, "2DArea")


def test_unknown_area_and_no_bc_lines(example_hdf, tmp_path):
    with pytest.raises(KeyError, match="Unknown 2D flow area"):
        HdfMesh.get_mesh_perimeter_faces(example_hdf, "unknown")
    child = tmp_path / "without_bc.g01.hdf"
    shutil.copy2(example_hdf, child)
    with h5py.File(child, "r+") as hdf:
        del hdf["Geometry/Boundary Condition Lines"]
    result = HdfMesh.get_mesh_perimeter_faces(child, "2DArea")
    assert result.bc_line_id.isna().all()
    assert result.attrs["association_status"] == "absent"
    with h5py.File(child, "r") as hdf:
        assert len(HdfMesh.get_mesh_perimeter_faces(hdf, "2DArea")) == 371


@pytest.mark.parametrize("mutation", ["cell_count", "cell_id", "endpoint", "perimeter"])
def test_malformed_mesh_topology_fails_closed(example_hdf, tmp_path, mutation):
    child = tmp_path / "bad_topology.g01.hdf"
    shutil.copy2(example_hdf, child)
    with h5py.File(child, "r+") as hdf:
        mesh = hdf["Geometry/2D Flow Areas/2DArea"]
        if mutation == "cell_count":
            attributes = hdf["Geometry/2D Flow Areas/Attributes"]
            rows = attributes[:]
            rows[0]["Cell Count"] = 1
            attributes[:] = rows
        elif mutation == "cell_id":
            mesh["Faces Cell Indexes"][3] = [-2, 0]
        elif mutation == "endpoint":
            mesh["Faces FacePoint Indexes"][3] = [0, 999999]
        else:
            del mesh["Faces Perimeter Values"]
    with pytest.raises(ValueError):
        HdfMesh.get_mesh_perimeter_faces(child, "2DArea")
