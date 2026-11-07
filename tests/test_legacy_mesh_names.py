"""Legacy geometry name discovery preserves source bytes and modern behavior."""

import hashlib

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfMesh import HdfMesh


def fixture(path, *, modern=False, names=(b"LegacyMesh",)):
    with h5py.File(path, "w") as handle:
        handle.attrs["Projection"] = np.bytes_(CRS.from_epsg(3452).to_wkt())
        group = handle.create_group("Geometry/2D Flow Areas")
        if modern:
            attrs = np.zeros(len(names), dtype=[("Name", "S16"), ("Cell Count", "i8")])
            attrs["Name"] = names
            attrs["Cell Count"] = 2
            group.create_dataset("Attributes", data=attrs)
        else:
            group.create_dataset("Names", data=np.asarray(names, dtype="S16"))
        for raw in set(names):
            try:
                name = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not name or "/" in name or "\\" in name:
                continue
            mesh = group.create_group(name)
            mesh.attrs["Cell Maximum Index"] = 1  # Not a qualified physical cell count.
            mesh.create_dataset(
                "Cells Center Coordinate", data=[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
            )
            mesh.create_dataset("Cells Surface Area", data=[10.0, 0.0, 0.0])


def test_legacy_names_and_all_centres_are_read_only(tmp_path):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert HdfMesh.get_mesh_area_names(path) == ["LegacyMesh"]
    with h5py.File(path, "r") as handle:
        assert HdfMesh._physical_cell_counts(handle) == {}
    points = HdfMesh.get_mesh_cell_points(path, include_ghost_cells=False)
    assert len(points) == 3  # Never truncate using the stale Cell Maximum Index.
    assert points["cell_id"].tolist() == [0, 1, 2]
    assert points["mesh_name"].tolist() == ["LegacyMesh"] * 3
    assert points.geometry.x.tolist() == [0.0, 1.0, 2.0]
    assert points.crs.to_epsg() == 3452
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_modern_schema_keeps_existing_physical_count_policy(tmp_path):
    path = tmp_path / "M.g01.hdf"
    fixture(path, modern=True)
    assert HdfMesh.get_mesh_area_names(path) == ["LegacyMesh"]
    assert len(HdfMesh.get_mesh_cell_points(path, include_ghost_cells=False)) == 2
    assert len(HdfMesh.get_mesh_cell_points(path, include_ghost_cells=True)) == 3


def test_legacy_utf8_vlen_names(tmp_path):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    with h5py.File(path, "r+") as handle:
        group = handle["Geometry/2D Flow Areas"]
        del group["Names"]
        group.move("LegacyMesh", "Båy")
        group.create_dataset("Names", data=["Båy"], dtype=h5py.string_dtype("utf-8"))
    assert HdfMesh.get_mesh_area_names(path) == ["Båy"]


@pytest.mark.parametrize(
    "names",
    [
        (b"",),
        (b"   ",),
        (b"LegacyMesh", b"LegacyMesh"),
        (b"\xff",),
        (b"a/b",),
        (b"a\\b",),
    ],
)
def test_invalid_names_fail_closed(tmp_path, names):
    path = tmp_path / "M.g01.hdf"
    fixture(path, names=names)
    assert HdfMesh.get_mesh_area_names(path) == []


@pytest.mark.parametrize(
    "fault",
    [
        "missing_group",
        "missing_centres",
        "centres_shape",
        "centres_type",
        "missing_areas",
        "areas_length",
        "areas_shape",
        "areas_type",
        "names_shape",
        "names_type",
    ],
)
def test_invalid_legacy_mesh_arrays_fail_closed(tmp_path, fault):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    with h5py.File(path, "r+") as handle:
        group = handle["Geometry/2D Flow Areas"]
        mesh = group["LegacyMesh"]
        if fault == "missing_group":
            del group["LegacyMesh"]
        elif fault.startswith("centres") or fault == "missing_centres":
            del mesh["Cells Center Coordinate"]
            if fault == "centres_shape":
                mesh.create_dataset("Cells Center Coordinate", data=np.zeros((3, 3)))
            elif fault == "centres_type":
                mesh.create_dataset(
                    "Cells Center Coordinate", data=np.full((3, 2), b"x")
                )
        elif fault.startswith("areas") or fault == "missing_areas":
            del mesh["Cells Surface Area"]
            if fault == "areas_length":
                mesh.create_dataset("Cells Surface Area", data=[1.0, 2.0])
            elif fault == "areas_shape":
                mesh.create_dataset("Cells Surface Area", data=np.ones((3, 1)))
            elif fault == "areas_type":
                mesh.create_dataset("Cells Surface Area", data=[b"x"] * 3)
        else:
            del group["Names"]
            group.create_dataset(
                "Names",
                data=np.array([[b"LegacyMesh"]]) if fault == "names_shape" else [123],
            )
    assert HdfMesh.get_mesh_area_names(path) == []


def test_malformed_modern_schema_does_not_use_legacy_fallback(tmp_path):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    with h5py.File(path, "r+") as handle:
        handle["Geometry/2D Flow Areas"].create_dataset("Attributes", data=[123])
    assert HdfMesh.get_mesh_area_names(path) == []


def test_undeclared_groups_are_not_guessed(tmp_path):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    with h5py.File(path, "r+") as handle:
        del handle["Geometry/2D Flow Areas/Names"]
    assert HdfMesh.get_mesh_area_names(path) == []


def test_required_native_errors_propagate(tmp_path, monkeypatch):
    import importlib

    from ras_commander.fast_hdf import FastHdfError

    module = importlib.import_module("ras_commander.hdf.HdfMesh")
    path = tmp_path / "M.g01.hdf"
    fixture(path, modern=True)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")

    def fail(dataset):
        raise FastHdfError("injected native read failure")

    monkeypatch.setattr(module, "read_typed", fail)
    with pytest.raises(FastHdfError, match="injected native"):
        HdfMesh.get_mesh_area_names(path)


@pytest.mark.parametrize("backend", ["python", "auto"])
def test_legacy_names_backend_equivalence(tmp_path, monkeypatch, backend):
    path = tmp_path / "M.g01.hdf"
    fixture(path)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", backend)
    assert HdfMesh.get_mesh_area_names(path) == ["LegacyMesh"]
