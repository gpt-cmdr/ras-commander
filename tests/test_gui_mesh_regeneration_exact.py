"""Regression coverage for exact-geometry RASMapper mesh regeneration."""

from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from ras_commander.RasMap import RasMap
from ras_commander.hdf.HdfMesh import HdfMesh
from ras_commander.gui.workflows.mesh_regeneration import (
    MeshRegenerationWorkflow,
    _begin_geometry_hdf_transaction,
    _capture_geometry_association_paths,
    _finish_geometry_hdf_transaction,
    _perimeter_validation,
    _prepare_geometry_refresh_context,
    _resolve_geometry_target,
    _restore_geometry_association,
    _restore_non_target_geometry_hdfs,
    _supervise_owned_process_exit,
    _validate_geometry_import,
    _validate_geometry_refresh,
)
from ras_commander.gui.hecras_elements import HecRasElements


def _fake_project(tmp_path):
    project_file = tmp_path / "Model.prj"
    project_file.write_text(
        "Proj Title=Model\n"
        "Current Plan=p09\n"
        "Geom File=g01\nGeom File=g03\n"
        "Plan File=p01\nPlan File=p09\n",
        encoding="utf-8",
    )
    for number in ("01", "03"):
        project_file.with_suffix(f".g{number}").write_text(
            f"Geom Title=Geometry {number}\n", encoding="utf-8"
        )
    project = SimpleNamespace(
        initialized=True,
        prj_file=project_file,
        project_folder=tmp_path,
        project_name="Model",
        plan_df=pd.DataFrame(
            [
                {"plan_number": "01", "geometry_number": "01"},
                {"plan_number": "09", "geometry_number": "03"},
            ]
        ),
        geom_df=pd.DataFrame(
            [
                {"geom_number": "01", "geom_title": "Geometry 01"},
                {"geom_number": "03", "geom_title": "Geometry 03"},
            ]
        ),
    )
    project.check_initialized = lambda: None
    return project


def _mapper_geometries():
    return [
        {"name": "Geometry 01", "geom_number": "01"},
        {"name": "Geometry 03", "geom_number": "03"},
    ]


def _write_mesh_hdf(path, polygon, *, area_name="Mesh"):
    attr_dtype = np.dtype([("Name", "S32")])
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(area_name.encode("utf-8"),)], dtype=attr_dtype),
        )
        points = np.asarray(polygon.exterior.coords)
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Polygon Info",
            data=np.array([[0, len(points), 0, 1]], dtype=np.int32),
        )
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Polygon Parts",
            data=np.array([[0, len(points)]], dtype=np.int32),
        )
        hdf.create_dataset("Geometry/2D Flow Areas/Polygon Points", data=points)
        base = f"Geometry/2D Flow Areas/{area_name}"
        hdf.create_dataset(f"{base}/Perimeter", data=np.asarray(polygon.exterior.coords))
        hdf.create_dataset(
            f"{base}/Cells Center Coordinate",
            data=np.array([[1.0, 1.0], [5.0, 5.0], [9.0, 9.0]]),
        )
        hdf.create_dataset(
            f"{base}/FacePoints Coordinate",
            data=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]),
        )
        hdf.create_dataset(
            f"{base}/Faces FacePoint Indexes",
            data=np.array([[0, 1], [1, 2], [2, 0]], dtype=np.int32),
        )


def test_default_geometry_comes_from_current_plan_not_first_registration(
    tmp_path, monkeypatch
):
    project = _fake_project(tmp_path)
    monkeypatch.setattr(
        RasMap, "list_geometries", staticmethod(lambda _ras: _mapper_geometries())
    )

    target = _resolve_geometry_target(project)

    assert target["geom_number"] == "03"
    assert target["geometry_name"] == "Geometry 03"
    assert target["geom_file"] == tmp_path / "Model.g03"


def test_number_and_name_must_identify_same_mapper_geometry(tmp_path, monkeypatch):
    project = _fake_project(tmp_path)
    monkeypatch.setattr(
        RasMap, "list_geometries", staticmethod(lambda _ras: _mapper_geometries())
    )

    with pytest.raises(ValueError, match="is named"):
        _resolve_geometry_target(
            project,
            geom_number="03",
            geometry_name="Geometry 01",
        )


def test_duplicate_mapper_tree_names_are_rejected(tmp_path, monkeypatch):
    project = _fake_project(tmp_path)
    duplicate_names = [
        {"name": "Duplicate", "geom_number": "01"},
        {"name": "Duplicate", "geom_number": "03"},
    ]
    monkeypatch.setattr(
        RasMap, "list_geometries", staticmethod(lambda _ras: duplicate_names)
    )

    with pytest.raises(ValueError, match="not unique"):
        _resolve_geometry_target(project, geom_number="03")


def test_refresh_context_edits_exact_geometry_root(tmp_path, monkeypatch):
    project = _fake_project(tmp_path)
    polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    monkeypatch.setattr(
        "ras_commander.gui.workflows.mesh_regeneration._resolve_geometry_target",
        lambda *_args, **_kwargs: {
            "geom_number": "03",
            "geometry_name": "Geometry 03",
            "geom_file": tmp_path / "Model.g03",
            "geom_hdf": tmp_path / "Model.g03.hdf",
        },
    )
    monkeypatch.setattr(
        "ras_commander.gui.workflows.mesh_regeneration._select_text_flow_area",
        lambda *_args, **_kwargs: ("Mesh", polygon),
    )
    monkeypatch.setattr(
        "ras_commander.gui.workflows.mesh_regeneration._geometry_hdf_stats",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "ras_commander.gui.workflows.mesh_regeneration._perimeter_validation",
        lambda *_args, **_kwargs: {"valid": False, "error": "missing"},
    )

    context = _prepare_geometry_refresh_context(
        project,
        geom_number="03",
        geometry_name="Geometry 03",
        flow_area_name="Mesh",
        coordinate_tolerance=None,
    )

    assert context["target_path"] == ["Geometries", "Geometry 03"]


def test_perimeter_validation_rejects_stale_compiled_geometry(tmp_path):
    expected = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    stale = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
    hdf_path = tmp_path / "Model.g03.hdf"
    _write_mesh_hdf(hdf_path, stale)

    result = _perimeter_validation(hdf_path, "Mesh", expected)

    assert result["valid"] is False
    assert "does not match" in result["error"]
    assert result["hdf_area"] == pytest.approx(400.0)


def test_refresh_validation_proves_exact_target_and_other_hdf_isolation(tmp_path):
    polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    target_hdf = tmp_path / "Model.g03.hdf"
    other_hdf = tmp_path / "Model.g01.hdf"
    _write_mesh_hdf(target_hdf, polygon)
    _write_mesh_hdf(other_hdf, polygon)
    project = _fake_project(tmp_path)
    other_stat = other_hdf.stat()

    result = _validate_geometry_refresh(
        {
            "geom_number": "03",
            "geometry_name": "Geometry 03",
            "geom_file": tmp_path / "Model.g03",
            "geom_hdf": target_hdf,
            "flow_area_name": "Mesh",
            "expected_polygon": polygon,
            "coordinate_tolerance": None,
            "ras_object": project,
            "pre_hdf_stats": {
                str(other_hdf.resolve()): (other_stat.st_size, other_stat.st_mtime_ns),
                str(target_hdf.resolve()): (0, 0),
            },
            "pre_perimeter_validation": {"valid": False, "error": "stale"},
        }
    )

    assert result["geom_number"] == "03"
    assert result["post_perimeter"]["valid"] is True
    assert result["mesh"]["valid"] is True
    assert result["other_geometry_hdfs_unchanged"] is True


def test_import_validation_does_not_require_computation_cells(tmp_path):
    polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    target_hdf = tmp_path / "Model.g03.hdf"
    other_hdf = tmp_path / "Model.g01.hdf"
    _write_mesh_hdf(target_hdf, polygon)
    _write_mesh_hdf(other_hdf, polygon)
    with h5py.File(target_hdf, "a") as hdf:
        del hdf["Geometry/2D Flow Areas/Mesh"]
    project = _fake_project(tmp_path)
    other_stat = other_hdf.stat()

    result = _validate_geometry_import(
        {
            "geom_number": "03",
            "geometry_name": "Geometry 03",
            "geom_file": tmp_path / "Model.g03",
            "geom_hdf": target_hdf,
            "flow_area_name": "Mesh",
            "expected_polygon": polygon,
            "coordinate_tolerance": None,
            "ras_object": project,
            "pre_hdf_stats": {
                str(other_hdf.resolve()): (other_stat.st_size, other_stat.st_mtime_ns),
                str(target_hdf.resolve()): (0, 0),
            },
            "pre_perimeter_validation": {"valid": False, "error": "missing"},
        }
    )

    assert result["post_perimeter"]["valid"] is True
    assert "mesh" not in result


def test_geometry_refresh_captures_and_restores_associations(tmp_path, monkeypatch):
    hdf_path = tmp_path / "Model.g03.hdf"
    terrain = tmp_path / "Terrain" / "Terrain.hdf"
    landcover = tmp_path / "Land Classification" / "LandCover.hdf"
    terrain.parent.mkdir(parents=True)
    landcover.parent.mkdir(parents=True)
    terrain.write_bytes(b"terrain")
    landcover.write_bytes(b"landcover")
    with h5py.File(hdf_path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Terrain Filename"] = b".\\Terrain\\Terrain.hdf"
        geometry.attrs["Terrain Layername"] = b"Terrain"
        geometry.attrs["Land Cover Filename"] = (
            b".\\Land Classification\\LandCover.hdf"
        )
        geometry.attrs["Land Cover Layername"] = b"LandCover"

    captured = _capture_geometry_association_paths(hdf_path)
    assert captured == {
        "terrain_hdf_path": terrain.resolve(),
        "landcover_hdf_path": landcover.resolve(),
    }

    calls = []

    def fake_set(target, **kwargs):
        calls.append((target, kwargs))
        return Path(target)

    monkeypatch.setattr(
        "ras_commander.geom.GeomMesh.set_geometry_association",
        fake_set,
    )
    monkeypatch.setattr(
        "ras_commander.geom.GeomMesh.get_geometry_association",
        lambda _target: {key: str(value) for key, value in captured.items()},
    )
    evidence = _restore_geometry_association(
        {
            "geom_hdf": hdf_path,
            "ras_object": SimpleNamespace(),
            "pre_geometry_association_paths": captured,
        }
    )

    assert evidence["restored"] is True
    assert calls[0][0] == hdf_path
    assert calls[0][1]["terrain_hdf_path"] == terrain.resolve()
    assert calls[0][1]["landcover_hdf_path"] == landcover.resolve()


def test_geometry_refresh_rejects_missing_association_artifact(tmp_path):
    hdf_path = tmp_path / "Model.g03.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Terrain Filename"] = b".\\Terrain\\Missing.hdf"
        geometry.attrs["Terrain Layername"] = b"Missing"

    with pytest.raises(FileNotFoundError, match="Cannot preserve terrain_hdf_path"):
        _capture_geometry_association_paths(hdf_path)


def test_mesh_area_reader_supports_fresh_unmeshed_geometry_hdf(tmp_path):
    polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    hdf_path = tmp_path / "Model.g03.hdf"
    _write_mesh_hdf(hdf_path, polygon)
    with h5py.File(hdf_path, "a") as hdf:
        del hdf["Geometry/2D Flow Areas/Mesh"]

    areas = HdfMesh.get_mesh_areas(hdf_path)

    assert areas["mesh_name"].tolist() == ["Mesh"]
    assert areas.iloc[0].geometry.area == pytest.approx(100.0)


def test_geometry_hdf_transaction_rolls_back_failed_import(tmp_path):
    target = tmp_path / "Model.g03.hdf"
    target.write_bytes(b"original")
    context = {"geom_hdf": target}

    _begin_geometry_hdf_transaction(context)
    target.write_bytes(b"failed replacement")
    evidence = _finish_geometry_hdf_transaction(
        context,
        success=False,
        keep_backup=False,
    )

    assert target.read_bytes() == b"original"
    assert evidence["rolled_back"] is True


def test_geometry_hdf_transaction_restores_non_target_side_effects(tmp_path):
    target = tmp_path / "Model.g03.hdf"
    other = tmp_path / "Model.g01.hdf"
    target.write_bytes(b"target original")
    other.write_bytes(b"parent original")
    other_stat = other.stat()
    context = {
        "geom_hdf": target,
        "pre_hdf_stats": {
            str(target.resolve()): (target.stat().st_size, target.stat().st_mtime_ns),
            str(other.resolve()): (other_stat.st_size, other_stat.st_mtime_ns),
        },
    }

    _begin_geometry_hdf_transaction(context)
    other.write_bytes(b"RASMapper side effect")
    evidence = _restore_non_target_geometry_hdfs(context)

    assert other.read_bytes() == b"parent original"
    assert evidence["changed_during_gui"] == [str(other)]
    assert evidence["restored_paths"] == [str(other)]

    # Cleanup is idempotent when the outer workflow's finally path runs.
    again = _restore_non_target_geometry_hdfs(context)
    assert again["restored_paths"] == []


def test_synchronous_launch_routes_through_exact_project_open(monkeypatch):
    project = SimpleNamespace()
    project.check_initialized = lambda: None
    sentinel = (SimpleNamespace(pid=123), 456)
    calls = []

    monkeypatch.setattr(
        "ras_commander.gui.hecras_elements.WIN32_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        HecRasElements,
        "_launch_project_with_com",
        staticmethod(
            lambda ras_object, *, timeout: (
                calls.append((ras_object, timeout)) or sentinel
            )
        ),
    )

    result = HecRasElements.launch_and_wait(
        ras_object=project,
        timeout=45,
        synchronous_project_open=True,
    )

    assert result == sentinel
    assert calls == [(project, 45)]


def test_geometry_hdf_transaction_commits_with_optional_backup(tmp_path):
    target = tmp_path / "Model.g03.hdf"
    target.write_bytes(b"original")
    context = {"geom_hdf": target}

    _begin_geometry_hdf_transaction(context)
    target.write_bytes(b"replacement")
    evidence = _finish_geometry_hdf_transaction(
        context,
        success=True,
        keep_backup=True,
    )

    assert target.read_bytes() == b"replacement"
    backup = tmp_path / "Model.g03.hdf.pre-rasmapper.bak"
    assert backup.read_bytes() == b"original"
    assert evidence["backup"] == str(backup)


def test_geometry_hdf_transaction_numbers_existing_backup(tmp_path):
    target = tmp_path / "Model.g03.hdf"
    target.write_bytes(b"original")
    existing_backup = tmp_path / "Model.g03.hdf.pre-rasmapper.bak"
    existing_backup.write_bytes(b"earlier parent")
    context = {"geom_hdf": target}

    _begin_geometry_hdf_transaction(context)
    target.write_bytes(b"replacement")
    evidence = _finish_geometry_hdf_transaction(
        context,
        success=True,
        keep_backup=True,
    )

    next_backup = tmp_path / "Model.g03.hdf.pre-rasmapper.bak1"
    assert target.read_bytes() == b"replacement"
    assert existing_backup.read_bytes() == b"earlier parent"
    assert next_backup.read_bytes() == b"original"
    assert evidence["backup"] == str(next_backup)


def test_owned_process_supervision_terminates_only_captured_tree(monkeypatch):
    import psutil

    class FakePopen:
        pid = 101

        def wait(self, timeout):
            raise TimeoutError

        def poll(self):
            return None

    class FakeOwned:
        def __init__(self, pid):
            self.pid = pid
            self.alive = True

        def is_running(self):
            return self.alive

        def status(self):
            return "running"

        def terminate(self):
            self.alive = False

        def kill(self):
            self.alive = False

    owned = [FakeOwned(101), FakeOwned(202)]

    def fake_wait_procs(processes, timeout):
        gone = [process for process in processes if not process.alive]
        alive = [process for process in processes if process.alive]
        return gone, alive

    monkeypatch.setattr(psutil, "wait_procs", fake_wait_procs)

    result = _supervise_owned_process_exit(FakePopen(), owned)

    assert result["observed_pids"] == [101, 202]
    assert result["terminated_pids"] == [202, 101]
    assert result["survivor_pids"] == []


def test_single_attempt_steps_select_before_save_and_validate_after(tmp_path):
    steps = MeshRegenerationWorkflow._build_single_attempt_steps(
        {"timeout": 60, "close_after": True}
    )
    names = [step.name for step in steps]

    assert names.index("Select exact geometry for editing") < names.index(
        "Save geometry (trigger HDF regeneration)"
    )
    assert names.index("Wait for save to complete") < names.index(
        "Validate exact geometry HDF"
    )
