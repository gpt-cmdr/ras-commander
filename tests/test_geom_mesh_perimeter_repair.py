"""Perimeter handoff regression tests; native mesh and Ras.exe calls are mocked."""

import hashlib
import json
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
from test_geom_mesh import (
    FakeMesh,
    FakeMeshState,
    MockPointM,
    MockPointMs,
    MockPolygon,
    _mock_generate_success,
    _write_mesh_hdf,
)
from test_geom_mesh import (
    geom_mesh_module as module,
)

from ras_commander.geom import GeomPreprocessor, GeomStorage


@pytest.fixture
def repair_project(tmp_path, monkeypatch):
    path = tmp_path / "repair.g01"
    # The 1-unit notch is removed by the real DP algorithm at tolerance 5.
    original = [(0, 0), (50, 1), (100, 0), (100, 100), (0, 100), (0, 0)]
    path.write_text("Geom Title=Repair\n", encoding="utf-8")
    GeomStorage.set_2d_flow_area_perimeter(
        path,
        "MainArea",
        coordinates=original,
        point_generation_data=",,50,50",
        create_backup=False,
    )
    _mock_generate_success(monkeypatch, path, has_breaklines=False)
    hdf_path = path.with_suffix(".g01.hdf")
    calls = []

    def compile_hdf():
        ring = module._text_flow_area_perimeter(path, "MainArea")
        _write_mesh_hdf(
            hdf_path,
            [
                {
                    "name": "MainArea",
                    "spacing_dx": 50.0,
                    "spacing_dy": 50.0,
                    "cell_count": 2,
                }
            ],
        )
        with h5py.File(hdf_path, "a") as hdf:
            group = hdf["Geometry/2D Flow Areas"]
            group.create_dataset("Polygon Info", data=np.array([[0, len(ring), 0, 1]]))
            group.create_dataset("Polygon Parts", data=np.array([[0, len(ring)]]))
            group.create_dataset("Polygon Points", data=ring)

    compile_hdf()
    ras = SimpleNamespace(
        check_initialized=lambda: None,
        get_plan_entries=lambda: pd.DataFrame(
            [{"plan_number": "01", "Geom Path": str(path)}]
        ),
    )

    def bootstrap(geom_number, **kwargs):
        calls.append(("points", kwargs))
        module._patch_text_seeds(
            path, np.array([[25.0, 25.0], [75.0, 75.0]]), mesh_name="MainArea"
        )
        return SimpleNamespace(status="success", cell_count=2, error_message="")

    def preprocessor(plan_number, **kwargs):
        calls.append(("preprocess", kwargs))
        assert plan_number == "01"
        compile_hdf()
        return SimpleNamespace(success=True, error="", first_error_line="")

    monkeypatch.setattr(module.GeomMesh, "generate_computation_points", bootstrap)
    monkeypatch.setattr(GeomPreprocessor, "run_geometry_preprocessor", preprocessor)
    ns = module._imports()

    def load_geometry(hdf):
        calls.append(("load", hdf))
        # Loading reads the compiled collection, never the in-memory candidate.
        ring = module._hdf_flow_area_perimeter(hdf_path, "MainArea")
        return SimpleNamespace(
            D2FlowArea=SimpleNamespace(
                GetFeatureByName=lambda name: 0,
                Geometry=SimpleNamespace(
                    MeshPerimeters=SimpleNamespace(
                        Polygon=lambda fid: MockPolygon(ring.tolist())
                    )
                ),
            )
        )

    ns["RASGeometry"] = load_geometry
    monkeypatch.setattr(module, "_imports", lambda: ns)
    monkeypatch.setattr(
        module,
        "_generate_seeds_via_net",
        lambda *args, **kwargs: SimpleNamespace(Count=2),
    )
    monkeypatch.setattr(
        module, "_remove_short_perimeter_segments", lambda perim, *args: perim
    )
    monkeypatch.setattr(module, "_meshfv2d_takes_min_face_ratio", lambda ns: False)
    monkeypatch.setattr(module, "_find_error_locations", lambda *args: [])
    # Let the actual DP helper import a .NET stand-in, as in existing unit tests.
    import sys

    monkeypatch.setitem(
        sys.modules,
        "RasMapperLib",
        SimpleNamespace(
            PointM=MockPointM,
            PointMs=MockPointMs,
            Polygon=MockPolygon,
        ),
    )
    return path, hdf_path, ras, calls


@pytest.mark.parametrize("repair_kind", ["dp", "vertex_removal"])
def test_generate_persists_reloads_and_retries(
    repair_project, monkeypatch, repair_kind
):
    path, hdf, ras, calls = repair_project
    before = path.read_bytes()
    attempts = []

    def compute(perim, seeds, breaklines, ratio, ns):
        attempts.append(perim)
        mesh = FakeMesh()
        if len(attempts) == 1:
            mesh.MeshCompletionState = FakeMeshState(4, "PerimeterPolygonError")
        return mesh

    monkeypatch.setattr(module, "_compute_mesh", compute)
    monkeypatch.setattr(
        module,
        "_autofix_perimeter",
        lambda *args: [1] if repair_kind == "vertex_removal" else [],
    )
    result = module.GeomMesh.generate(
        path, mesh_name="MainArea", ras_object=ras, max_iterations=2
    )
    assert result.ok
    assert result.iterations == 2
    assert len(result.perimeter_repairs) == 1
    record = result.perimeter_repairs[0]
    assert record["max_vertex_displacement"] == pytest.approx(1.0)
    assert record["area_change"] == pytest.approx(50.0)
    assert record["original_perimeter_hash"] != record["repaired_perimeter_hash"]
    from pathlib import Path

    assert Path(record["backup_path"]).read_bytes() == before
    assert "PerimeterPolygonError" in record["reason"]
    compiled_ring = module._hdf_flow_area_perimeter(hdf, "MainArea").tolist()
    assert attempts[1]._coords == compiled_ring
    expected_hash = hashlib.sha256(
        json.dumps(compiled_ring, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert record["repaired_perimeter_hash"] == expected_hash
    assert [name for name, _ in calls] == ["load", "points", "preprocess", "load"]
    preprocess = calls[2][1]
    assert (
        preprocess["geometry_only"]
        and preprocess["force"]
        and preprocess["clear_geompre"]
    )
    assert preprocess["ras_object"] is ras


@pytest.mark.parametrize(
    "failure",
    ["preprocess", "stale_hdf", "retry", "bound", "containment", "seeds", "dp"],
)
def test_failed_handoff_or_retry_raises_original_reason(
    repair_project, monkeypatch, failure
):
    path, _hdf, ras, calls = repair_project
    count = 0

    def compute(*args):
        nonlocal count
        count += 1
        mesh = FakeMesh()
        mesh.MeshCompletionState = FakeMeshState(4, "PerimeterPolygonError")
        if count > 1 and failure == "retry":
            raise ValueError("native retry failure")
        return mesh

    monkeypatch.setattr(module, "_compute_mesh", compute)
    monkeypatch.setattr(module, "_autofix_perimeter", lambda *args: [])
    if failure == "dp":

        def fail_dp(*args):
            raise ValueError("DP algorithm failure")

        monkeypatch.setattr(module, "_douglas_peucker_polygon", fail_dp)
    if failure in ("preprocess", "stale_hdf"):
        monkeypatch.setattr(
            GeomPreprocessor,
            "run_geometry_preprocessor",
            lambda *args, **kwargs: SimpleNamespace(
                success=failure == "stale_hdf",
                error="native preprocessor failure",
                first_error_line="",
            ),
        )
    if failure == "seeds":
        monkeypatch.setattr(
            module.GeomMesh,
            "generate_computation_points",
            lambda *args, **kwargs: SimpleNamespace(
                status="exception",
                cell_count=0,
                error_message="no points",
            ),
        )
    if failure == "containment":
        audit = module._audit_domain_containment_hdf

        def containment(*args):
            return audit(*args) if count == 0 else False

        monkeypatch.setattr(module, "_audit_domain_containment_hdf", containment)
    with pytest.raises(RuntimeError, match="Mesh repair/retry failed") as error:
        module.GeomMesh.generate(
            path,
            mesh_name="MainArea",
            ras_object=ras,
            max_iterations=1 if failure == "bound" else 2,
        )
    assert "PerimeterPolygonError" in str(error.value.__cause__)
    assert count <= 2
    if failure == "bound":
        assert [name for name, _ in calls] == ["load"]


def test_no_plan_does_not_write_repaired_perimeter(repair_project):
    path, hdf, ras, calls = repair_project
    before = path.read_bytes()
    ras.get_plan_entries = lambda: pd.DataFrame()
    with pytest.raises(RuntimeError, match="could not find a plan"):
        module._reseed_after_perimeter_fix(
            path,
            hdf,
            MockPolygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            50.0,
            "MainArea",
            ras_object=ras,
        )
    assert path.read_bytes() == before
    assert calls == []


def test_noop_dp_exhausts_bound_without_preprocessing(repair_project, monkeypatch):
    path, _hdf, ras, calls = repair_project
    attempts = []

    def compute(*args):
        attempts.append(1)
        mesh = FakeMesh()
        mesh.MeshCompletionState = FakeMeshState(4, "PerimeterPolygonError")
        return mesh

    monkeypatch.setattr(module, "_compute_mesh", compute)
    monkeypatch.setattr(module, "_autofix_perimeter", lambda *args: [])
    monkeypatch.setattr(module, "_douglas_peucker_polygon", lambda perim, *args: perim)
    with pytest.raises(RuntimeError, match="Max iterations") as error:
        module.GeomMesh.generate(
            path, mesh_name="MainArea", ras_object=ras, max_iterations=2
        )
    assert "PerimeterPolygonError" in str(error.value.__cause__)
    assert len(attempts) == 2
    assert [name for name, _ in calls] == ["load"]


def test_vertex_candidate_failure_chains_mesh_reason(repair_project, monkeypatch):
    path, _hdf, ras, _calls = repair_project

    def compute(*args):
        mesh = FakeMesh()
        mesh.MeshCompletionState = FakeMeshState(4, "PerimeterPolygonError")
        return mesh

    def fail_remove(*args):
        raise ValueError("vertex removal failure")

    monkeypatch.setattr(module, "_compute_mesh", compute)
    monkeypatch.setattr(module, "_autofix_perimeter", lambda *args: [1])
    monkeypatch.setattr(module, "_remove_perimeter_points", fail_remove)
    with pytest.raises(RuntimeError, match="vertex removal failure") as error:
        module.GeomMesh.generate(path, mesh_name="MainArea", ras_object=ras)
    assert "PerimeterPolygonError" in str(error.value.__cause__)
