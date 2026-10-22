"""Explicit seeds use real geometry text without loading native DLLs."""

import numpy as np
import pytest
from shapely.geometry import box

from ras_commander.geom import GeomMesh, GeomStorage


def geometry(tmp_path):
    path = tmp_path / "Model.g01"
    path.write_text("Geom Title=Explicit seeds\nProgram Version=6.60\n", encoding="utf-8")
    for name, bounds in (("Area", (0, 0, 100, 100)), ("Other", (200, 200, 300, 300))):
        GeomStorage.set_2d_flow_area_perimeter(
            path, name, geometry=box(*bounds),
            point_generation_data=[None, None, 20, 20], create_backup=False,
        )
    return path


def test_explicit_seeds_preserve_order_and_other_area(tmp_path):
    path = geometry(tmp_path)
    hdf = tmp_path / "Model.g01.hdf"
    hdf.write_bytes(b"compiled source remains untouched")
    original = path.read_bytes()
    before = path.read_text(encoding="utf-8").split("Storage Area=Other", 1)[1]
    points = np.array([[80.25, 15.5], [10.125, 50.25], [35.0, 90.0]])
    result = GeomMesh.write_computation_points(path, points, mesh_name="Area")
    assert result.ok and result.operation == "computation_points"
    assert result.cell_count == 3 and result.mesh_name == "Area"
    text = path.read_text(encoding="utf-8")
    assert text.split("Storage Area=Other", 1)[1] == before
    rows = text.split("Storage Area 2D Points= 3", 1)[1].splitlines()[1:3]
    values = [float(row[i:i + 16]) for row in rows for i in range(0, len(row), 16) if row[i:i + 16].strip()]
    np.testing.assert_array_equal(np.asarray(values).reshape(-1, 2), points)
    assert hdf.read_bytes() == b"compiled source remains untouched"
    assert path.with_suffix(".g01.bak").read_bytes() == original
    GeomMesh.write_computation_points(path, points, mesh_name="Area")
    assert path.with_suffix(".g01.bak").read_bytes() == original
    assert path.with_suffix(".g01.bak1").is_file()


@pytest.mark.parametrize("points", [
    [], [[1, 2, 3]], [[np.nan, 2]], [[1, np.inf]], [[1, 2], [1, 2]],
    [[0, 50]], [[101, 50]],
    [[1e-16, 50], [2e-16, 50]], [[1e-16, 50]],
])
def test_invalid_explicit_seeds_never_mutate_geometry(tmp_path, points):
    path = geometry(tmp_path)
    before = path.read_bytes()
    result = GeomMesh.write_computation_points(path, points, mesh_name="Area")
    assert not result.ok and result.error_message
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak*"))


def test_native_coordinate_field_overflow_fails_without_mutation(tmp_path):
    path = geometry(tmp_path)
    GeomStorage.set_2d_flow_area_perimeter(
        path, "Area", geometry=box(0, 0, 1e18, 1e18), create_backup=False,
    )
    before = path.read_bytes()
    result = GeomMesh.write_computation_points(path, [[1e17, 1e17]], mesh_name="Area")
    assert not result.ok and "16-character" in result.error_message
    assert path.read_bytes() == before and not list(tmp_path.glob("*.bak*"))


def test_failed_atomic_replace_retains_original_and_backup(tmp_path, monkeypatch):
    from pathlib import Path

    path = geometry(tmp_path)
    original = path.read_bytes()
    real_replace = Path.replace

    def fail_staged_replace(source, target):
        if source.parent.name.startswith(".ras-points-"):
            raise OSError("injected replacement failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_staged_replace)
    result = GeomMesh.write_computation_points(path, [[50, 50]], mesh_name="Area")
    assert not result.ok and "injected replacement failure" in result.error_message
    assert path.read_bytes() == original
    assert path.with_suffix(".g01.bak").read_bytes() == original


@pytest.mark.parametrize("kwargs", [{"mesh_name": "missing"}, {"mesh_index": -1}, {"mesh_index": 3}])
def test_explicit_area_selection_is_unambiguous(tmp_path, kwargs):
    path = geometry(tmp_path)
    before = path.read_bytes()
    assert not GeomMesh.write_computation_points(path, [[1, 2]], **kwargs).ok
    assert path.read_bytes() == before
