"""Operation success remains distinct from compiled mesh readiness (#460)."""

import importlib
import sys
from types import SimpleNamespace

import pytest

from ras_commander import RasExamples
from ras_commander.geom import GeomMesh, GeomStorage
from ras_commander.geom.GeomMeshDataclasses import MeshResult


@pytest.mark.parametrize(
    "status, expected",
    [
        ("success", False),
        ("complete", True),
        ("error", False),
        ("exception", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_mesh_result_boolean_contract(status, expected):
    result = MeshResult(mesh_name="audit", status=status, cell_count=10)
    assert result.ok is expected
    assert bool(result) is expected
    assert result.status == status


def test_public_bootstrap_reports_success_without_claiming_compiled_mesh(
    tmp_path, monkeypatch
):
    module = importlib.import_module("ras_commander.geom.GeomMesh")
    folder = RasExamples.extract_project(
        "Muncie", output_path=tmp_path, suffix="bootstrap"
    )
    geometry = folder / "Muncie.g02"
    area = GeomStorage.get_storage_area_polygons(geometry, exclude_2d=False)
    area = area[area["is_2d"]].iloc[0]
    center = area.geometry.representative_point()
    points = [
        SimpleNamespace(X=center.x, Y=center.y),
        SimpleNamespace(X=center.x + 1, Y=center.y + 1),
    ]

    class PointMs:
        def __init__(self):
            self.values = []

        def Add(self, point):
            self.values.append(point)

    monkeypatch.setitem(
        sys.modules,
        "RasMapperLib",
        SimpleNamespace(
            PointMs=PointMs,
            PointM=lambda x, y: SimpleNamespace(X=x, Y=y),
            Polygon=lambda values: values,
        ),
    )
    monkeypatch.setattr(module, "_load_dlls", lambda *a: None)
    monkeypatch.setattr(module, "_imports", lambda: {})
    monkeypatch.setattr(
        module,
        "_generate_seeds_safe",
        lambda *a: SimpleNamespace(Count=2, PointM=points.__getitem__),
    )
    hdf = geometry.with_suffix(geometry.suffix + ".hdf")
    before = hdf.read_bytes()
    result = GeomMesh.generate_computation_points(
        geometry, mesh_name=area["Name"], cell_size=100
    )
    assert result.status == "complete" and result.ok and bool(result)
    assert result.operation == "computation_points"
    assert result.cell_count == 2 and result.face_count == 0
    assert result.geom_hdf_path == ""
    assert hdf.read_bytes() == before
    assert "Storage Area 2D Points= 2" in geometry.read_text()

    failed = GeomMesh.generate_computation_points(
        geometry, mesh_name="missing-area", cell_size=100
    )
    assert failed.status == "error" and not failed
    assert failed.operation == "computation_points"
