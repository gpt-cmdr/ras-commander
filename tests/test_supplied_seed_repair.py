"""Supplied-seed repair orchestration, using real geometry text and preview doubles."""

import importlib
import os
from dataclasses import asdict
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import Polygon

from ras_commander.geom import GeomBcLines, GeomMesh, GeomStorage, MeshResult

gm = importlib.import_module("ras_commander.geom.GeomMesh")
repair_module = importlib.import_module("ras_commander.geom._seed_repair")


class Status(IntEnum):
    Complete = 0
    FacePerimeterConnectionError = 1


class Points(list):
    @property
    def Count(self):
        return len(self)

    def Add(self, point):
        self.append(point)


class Constraints(list):
    def __init__(self, name):
        super().__init__()

    def AddFeature(self, line):
        self.append(line)

    def CopyToMultiPartPolyline(self):
        return self


def point(x, y):
    return SimpleNamespace(X=x, Y=y)


def test_default_result_schema_does_not_gain_repair_fields():
    assert "seed_repair" not in asdict(MeshResult(mesh_name="Area", status="complete"))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "Model.g01"
    path.write_text(
        "Geom Title=Supplied seeds\nProgram Version=6.60\n", encoding="utf-8"
    )
    GeomStorage.set_2d_flow_area_perimeter(
        path,
        "Area",
        geometry=Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
        point_generation_data=[None, None, 20, 20],
        create_backup=False,
    )
    install = tmp_path / "runtime"
    install.mkdir()
    for filename in ("Ras.exe", "RasMapperLib.dll"):
        (install / filename).write_bytes(b"test runtime identity only")
    ns = {
        "PointMs": Points,
        "PointM": point,
        "Polygon": lambda points: points,
        "Polyline": lambda points: points,
        "PolylineFeatureLayer": Constraints,
        "MeshStatus": Status,
    }
    monkeypatch.setattr(gm, "_load_dlls", lambda *a: None)
    monkeypatch.setattr(gm, "_imports", lambda: ns)
    monkeypatch.setattr(
        repair_module, "_loaded_runtime_directory", lambda ns: install.resolve()
    )

    def preview(perimeter, seeds, *args):
        repaired = any((p.X, p.Y) == (20, 30) for p in seeds)
        return SimpleNamespace(
            NonVirtualCellCount=len(seeds),
            CellFacesCount=lambda i: 9 if not repaired and i == 0 else 4,
            MeshCompletionState=Status.Complete
            if len({(p.X, p.Y) for p in perimeter}) <= 3
            else Status.FacePerimeterConnectionError,
        )

    monkeypatch.setattr(gm, "_compute_mesh", preview)
    monkeypatch.setattr(
        gm, "_autofix_max_faces", lambda *a, **k: ([], 1, [point(20, 30)])
    )
    monkeypatch.setattr(gm, "_find_error_locations", lambda *a: [(100, 0)])
    return path, install, SimpleNamespace(ras_exe_path=install / "Ras.exe")


def test_cookie_repair_adds_midpoint_removes_vertex_and_tracks_excluded_seed(setup):
    path, install, ras = setup
    original = path.read_bytes()
    hdf = Path(str(path) + ".hdf")
    hdf.write_bytes(b"compiled carrier must not be touched")
    plan = GeomMesh.plan_computation_point_repair(
        path,
        [[20, 70], [85, 10]],
        mesh_name="Area",
        hecras_dir=install,
        ras_object=ras,
        max_parent_seed_loss_fraction=0.5,
        max_area_loss_fraction=0.5,
    )
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.bak*"))
    evidence = plan.to_dict()
    assert evidence["parent_seed_count"] == evidence["final_seed_count"] == 2
    assert evidence["added_points"] == [[20.0, 30.0]]
    assert evidence["dropped_parent_points"] == [[85.0, 10.0]]
    assert evidence["perimeter_rounds"][0]["removed_vertices"] == [[100.0, 0.0]]
    assert len(evidence["maxfaces_rounds"]) == 3
    result = GeomMesh.apply_computation_point_repair(plan)
    assert result.ok and result.cell_count == 2
    assert result.seed_repair["application_validation"]["ok"]
    assert GeomMesh.validate_computation_point_repair(plan)["ok"]
    assert path.with_suffix(".g01.bak").read_bytes() == original
    assert hdf.read_bytes() == b"compiled carrier must not be touched"
    perimeter = GeomStorage.get_storage_area_polygons(
        path, exclude_2d=False
    ).geometry.iloc[0]
    assert perimeter.equals(Polygon([(0, 0), (100, 100), (0, 100)]))


def test_stale_plan_and_changed_readback_are_rejected(setup):
    path, _, ras = setup
    plan = GeomMesh.plan_computation_point_repair(
        path,
        [[20, 70]],
        mesh_name="Area",
        ras_object=ras,
        max_area_loss_fraction=0.5,
    )
    path.write_bytes(path.read_bytes() + b"changed\r\n")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="changed after"):
        GeomMesh.apply_computation_point_repair(plan)
    assert path.read_bytes() == before
    with pytest.raises(RuntimeError, match="does not match"):
        GeomMesh.validate_computation_point_repair(plan)


def test_failed_repair_never_writes_geometry_or_backup(setup, monkeypatch):
    path, _, ras = setup
    original = path.read_bytes()
    monkeypatch.setattr(gm, "_autofix_max_faces", lambda *a, **k: ([], 0, []))
    with pytest.raises(RuntimeError, match="no progress"):
        GeomMesh.plan_computation_point_repair(
            path, [[20, 70]], mesh_name="Area", ras_object=ras
        )
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.bak*"))


def test_default_loss_limits_fail_with_structured_loss_report(setup):
    path, _, ras = setup
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="loss limit exceeded") as caught:
        GeomMesh.plan_computation_point_repair(
            path, [[20, 70], [85, 10]], mesh_name="Area", ras_object=ras
        )
    loss = caught.value.repair_evidence
    assert loss["dropped_parent_fraction"] == loss["area_lost_fraction"] == 0.5
    assert (
        loss["max_parent_seed_loss_fraction"] == loss["max_area_loss_fraction"] == 0.001
    )
    assert path.read_bytes() == before


def test_fallback_ras_exe_accepts_explicit_install_and_never_uses_global(
    setup, monkeypatch
):
    path, install, _ = setup
    fallback = SimpleNamespace(ras_exe_path="Ras.exe")
    plan = GeomMesh.plan_computation_point_repair(
        path,
        [[20, 70]],
        mesh_name="Area",
        ras_object=fallback,
        hecras_dir=install,
        max_area_loss_fraction=0.5,
    )
    assert plan.evidence["runtime_directory"] == str(install.resolve())
    from ras_commander.RasPrj import ras

    monkeypatch.setattr(ras, "initialized", True)
    monkeypatch.setattr(ras, "ras_exe_path", install / "Ras.exe", raising=False)
    with pytest.raises(FileNotFoundError, match="explicit hecras_dir"):
        GeomMesh.plan_computation_point_repair(path, [[20, 70]], mesh_name="Area")


@pytest.mark.parametrize("feature", ["bc_line", "breakline"])
def test_perimeter_repair_must_preserve_feature_geometry(setup, feature):
    path, _, ras = setup
    if feature == "bc_line":
        GeomBcLines.add_bc_lines(
            path,
            [
                {
                    "name": "Outlet",
                    "storage_area": "Area",
                    "coordinates": [(80, 0), (100, 20)],
                }
            ],
        )
    else:
        GeomStorage.replace_breaklines(
            path,
            "Area",
            [{"name": "Kept", "coords": [(70, 10), (80, 15)]}],
            expected_existing_names=[],
            create_backup=False,
        )
    before = path.read_bytes()
    with pytest.raises(
        RuntimeError, match="endpoints no longer touch|excludes kept breakline"
    ):
        GeomMesh.plan_computation_point_repair(
            path,
            [[20, 70]],
            mesh_name="Area",
            ras_object=ras,
            max_area_loss_fraction=0.5,
        )
    assert path.read_bytes() == before


def test_maxfaces_midpoints_round_before_inset(monkeypatch):
    observed = []
    polygon = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    monkeypatch.setattr(gm, "_perimeter_shapely_polygon", lambda p: polygon)

    def inset(midpoint, length, perimeter, ns):
        observed.append((midpoint.X, midpoint.Y))
        return point(midpoint.X + 0.0007, midpoint.Y), True

    monkeypatch.setattr(gm, "_inset_perimeter_midpoint", inset)
    mesh = SimpleNamespace(
        NonVirtualCellCount=1,
        CellFacesCount=lambda i: 9,
        CellFaces=lambda i: [0],
        FaceSimpleLength=lambda f: 20,
        PointsOnFace=lambda f: Points([1, 2]),
        FaceSegment=lambda f: SimpleNamespace(
            MidPoint=lambda: point(10.00049, 20.00049)
        ),
    )
    _, _, added = gm._autofix_max_faces(
        mesh, [], {"PointM": point}, perimeter=object(), midpoint_round_decimals=3
    )
    assert observed == [(10.0, 20.0)]
    assert added[0].X == 10.0007


def test_maxfaces_recurrence_after_perimeter_change_is_repaired(setup, monkeypatch):
    path, _, ras = setup

    def preview(perimeter, seeds, *args):
        xy = {(p.X, p.Y) for p in seeds}
        changed = len({(p.X, p.Y) for p in perimeter}) == 3
        bad = (20, 30) not in xy or (changed and (30, 80) not in xy)
        return SimpleNamespace(
            NonVirtualCellCount=len(seeds),
            CellFacesCount=lambda i: 9 if i == 0 and bad else 4,
            MeshCompletionState=Status.Complete
            if changed
            else Status.FacePerimeterConnectionError,
        )

    def midpoint(mesh, seeds, *args, **kwargs):
        xy = {(p.X, p.Y) for p in seeds}
        return [], 1, [point(30, 80) if (20, 30) in xy else point(20, 30)]

    monkeypatch.setattr(gm, "_compute_mesh", preview)
    monkeypatch.setattr(gm, "_autofix_max_faces", midpoint)
    plan = GeomMesh.plan_computation_point_repair(
        path, [[20, 70]], mesh_name="Area", ras_object=ras, max_area_loss_fraction=0.5
    )
    assert plan.evidence["added_points"] == [[20.0, 30.0], [30.0, 80.0]]
    assert any(
        row["phase"] == "after_perimeter_0" and any(row["cells_over_8"].values())
        for row in plan.evidence["maxfaces_rounds"]
    )


def test_runtime_conflict_fails_before_native_load(setup, monkeypatch, tmp_path):
    path, _, ras = setup
    monkeypatch.setattr(
        gm, "_load_dlls", lambda *a: pytest.fail("must not load conflicting runtime")
    )
    with pytest.raises(ValueError, match="conflicts"):
        GeomMesh.plan_computation_point_repair(
            path, [[20, 70]], hecras_dir=tmp_path, ras_object=ras
        )


def test_exhausted_maxfaces_budget_fails_without_mutation(setup, monkeypatch):
    path, _, ras = setup
    before = path.read_bytes()
    calls = []

    def preview(*args):
        return SimpleNamespace(
            NonVirtualCellCount=1,
            CellFacesCount=lambda i: 9,
            MeshCompletionState=Status.Complete,
        )

    def add(*args, **kwargs):
        calls.append(1)
        return [], 1, [point(30 + len(calls), 80)]

    monkeypatch.setattr(gm, "_compute_mesh", preview)
    monkeypatch.setattr(gm, "_autofix_max_faces", add)
    with pytest.raises(RuntimeError, match="did not converge"):
        GeomMesh.plan_computation_point_repair(
            path, [[20, 70]], mesh_name="Area", ras_object=ras
        )
    assert len(calls) == 7 * 3
    assert path.read_bytes() == before


def test_previously_loaded_different_runtime_is_rejected(setup, monkeypatch, tmp_path):
    path, _, ras = setup
    monkeypatch.setattr(
        repair_module,
        "_loaded_runtime_directory",
        lambda ns: tmp_path / "other-runtime",
    )
    with pytest.raises(RuntimeError, match="Loaded RasMapperLib conflicts"):
        GeomMesh.plan_computation_point_repair(
            path, [[20, 70]], mesh_name="Area", ras_object=ras
        )


def test_complete_seed_set_preserves_coordinates_and_perimeter(setup, monkeypatch):
    path, _, ras = setup
    monkeypatch.setattr(
        gm,
        "_compute_mesh",
        lambda *a: SimpleNamespace(
            NonVirtualCellCount=1,
            CellFacesCount=lambda i: 4,
            MeshCompletionState=Status.Complete,
        ),
    )
    plan = GeomMesh.plan_computation_point_repair(
        path, [[20.125, 70.25]], mesh_name="Area", ras_object=ras
    )
    assert plan.evidence["added_points"] == plan.evidence["dropped_parent_points"] == []
    assert plan.evidence["serialized_points"] == [[20.125, 70.25]]
    assert plan.evidence["perimeter_after"] == plan.evidence["perimeter_before"]


@pytest.mark.parametrize("pattern", ["grid", "maxfaces", "perimeter"])
def test_native_cookie_seed_repair_when_explicitly_enabled(tmp_path, pattern):
    install = os.environ.get("RAS_SEED_REPAIR_NATIVE_INSTALL")
    if not install or not (Path(install) / "RasMapperLib.dll").is_file():
        pytest.skip(
            "set RAS_SEED_REPAIR_NATIVE_INSTALL to an installed HEC-RAS runtime"
        )
    path = tmp_path / "Native.g01"
    path.write_text(
        "Geom Title=Native supplied seeds\nProgram Version=6.60\n", encoding="utf-8"
    )
    ring = [(0, 0), (100, 0), (100, 100), (0, 100)]
    if pattern == "perimeter":
        ring = [
            (0, 0),
            (49.999999, 0),
            (49.999999, 29.9999),
            (50.000001, 29.9999),
            (50.000001, 0),
            (100, 0),
            (100, 10000),
            (0, 10000),
        ]
    GeomStorage.set_2d_flow_area_perimeter(
        path,
        "Area",
        geometry=Polygon(ring),
        point_generation_data=[None, None, 20, 20],
        create_backup=False,
    )
    if pattern == "perimeter":
        from shapely import contains_xy

        points = np.array(
            [(x, y) for y in range(10, 10000, 20) for x in range(10, 100, 20)]
        )
        points = points[contains_xy(Polygon(ring), points[:, 0], points[:, 1])]
        GeomStorage.replace_breaklines(
            path,
            "Area",
            [
                {
                    "name": "Interior",
                    "coords": [(20, 80), (80, 80)],
                    "cell_size_near": 20,
                    "cell_size_far": 20,
                }
            ],
            expected_existing_names=[],
            create_backup=False,
        )
        GeomBcLines.add_bc_lines(
            path,
            [
                {
                    "name": "Outlet",
                    "storage_area": "Area",
                    "coordinates": [(0, 20), (0, 80)],
                }
            ],
        )
    elif pattern == "grid":
        points = np.array(
            [(x, y) for y in range(10, 100, 20) for x in range(10, 100, 20)]
        )
    else:
        # Twelve neighbours give the centre more than HEC-RAS's eight faces.
        angles = np.arange(12) * (2 * np.pi / 12)
        points = np.vstack(
            (
                [50, 50],
                np.column_stack((50 + 30 * np.cos(angles), 50 + 30 * np.sin(angles))),
            )
        )
    runtime = (
        SimpleNamespace(ras_exe_path="Ras.exe") if pattern == "perimeter" else None
    )
    original = path.read_bytes()
    if pattern == "perimeter":
        with pytest.raises(RuntimeError, match="loss limit exceeded") as caught:
            GeomMesh.plan_computation_point_repair(
                path,
                points,
                mesh_name="Area",
                hecras_dir=install,
                ras_object=runtime,
                max_area_loss_fraction=0.0,
            )
        assert caught.value.repair_evidence["area_lost"] > 0
        assert path.read_bytes() == original
    plan = GeomMesh.plan_computation_point_repair(
        path,
        points,
        mesh_name="Area",
        hecras_dir=install,
        ras_object=runtime,
    )
    assert all(not p["cells_over_8"] for p in plan.evidence["final_previews"])
    if pattern == "maxfaces":
        assert any(plan.evidence["maxfaces_rounds"][0]["cells_over_8"].values())
        assert plan.evidence["added_points"]
    if pattern == "perimeter":
        assert (
            plan.evidence["perimeter_rounds"][0]["state"]
            == "FacePerimeterConnectionError"
        )
        assert len(plan.evidence["perimeter_rounds"]) > 1
        assert 0 < plan.evidence["area_lost_fraction"] < 0.001
        assert 0 < plan.evidence["dropped_parent_fraction"] < 0.001
        assert plan.evidence["feature_audit"]["ok"]
        assert plan.evidence["native_constraint_count"] == 1
    assert GeomMesh.apply_computation_point_repair(plan).ok
