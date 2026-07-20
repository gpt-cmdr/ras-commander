"""Tests for built-in real-product qualification action contracts."""

from __future__ import annotations

from pathlib import Path
import hashlib
import importlib
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasQualification
from ras_commander.RasQualificationActions import (
    ACTION_HANDLERS,
    boundary_associate,
    boundary_conflict_repair,
    concurrency_prefix_isolation,
    execute,
    geometry_area_or_perimeter,
    geometry_property_tables,
    infiltration_properties,
    land_cover_properties,
    mesh_breakline,
    mesh_generate,
    mesh_refinement_region,
    mapper_export_geotiff,
    mapper_result_layers,
    plan_compute_unsteady,
    plan_compute_unsteady_linux,
    plan_preprocess,
    path_variant_open,
    project_locking,
    project_open,
    project_save,
    projection_select,
    restart_recovery,
    terrain_build_pyramids,
    terrain_associate,
    terrain_import,
)
from ras_commander.geom import GeomMesh
from ras_commander.geom.GeomBcLines import GeomBcLines
from ras_commander.geom.GeomMeshDataclasses import BCConflict, BCFixResult, MeshResult
from ras_commander.geom.GeomStorage import GeomStorage


def _project(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "Action.prj").write_text(
        "Proj Title=Qualification Actions\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Unsteady File=u01\n",
        encoding="utf-8",
    )
    (path / "Action.p01").write_text(
        "Plan Title=Action\n"
        "Program Version=7.01\n"
        "Short Identifier=Action\n"
        "Simulation Date=01JAN2026,0000,01JAN2026,0100\n"
        "Geom File=g01\n"
        "Flow File=u01\n"
        "Computation Interval=1MIN\n",
        encoding="utf-8",
    )
    (path / "Action.g01").write_text(
        "Geom Title=Action\nProgram Version=7.01\n",
        encoding="utf-8",
    )
    (path / "Action.u01").write_text(
        "Flow Title=Action\nProgram Version=7.01\n",
        encoding="utf-8",
    )
    return path


def _context(tmp_path: Path, operation_id: str) -> dict:
    project = _project(tmp_path / "source")
    ras_exe = tmp_path / "HEC-RAS" / "7.0.1" / "Ras.exe"
    ras_exe.parent.mkdir(parents=True)
    ras_exe.write_bytes(b"fixture")
    return {
        "operation_id": operation_id,
        "project_folder": str(project),
        "project_file": str(project / "Action.prj"),
        "ras_executable": str(ras_exe),
        "workspace_root": str(tmp_path / "runs"),
        "run_directory": str(tmp_path / "receipt-run"),
        "fixture": {"id": "action-unit"},
    }


def _result_series_fixture() -> dict:
    return {
        "outflow": {
            "kind": "profile_line_flow",
            "value_columns": ["flow"],
            "records": [{"time": "2026-01-01T00:00:00", "flow": 1.0}],
        },
        "wse_cells": {
            "kind": "mesh_cells",
            "variable": "Water Surface",
            "value_columns": ["wse"],
            "records": [
                {"time": "2026-01-01T00:00:00", "cell_id": 1, "wse": 2.0}
            ],
        },
    }


def _qualified_mesh_area(
    cell_count: int,
    face_count: int,
    *,
    fingerprint_digit: str,
    complete: bool = True,
    topology_cell_count: int | None = None,
    topology_face_count: int | None = None,
) -> dict:
    topology_cells = (
        cell_count if topology_cell_count is None else topology_cell_count
    )
    topology_faces = (
        face_count if topology_face_count is None else topology_face_count
    )
    return {
        "cell_count": cell_count,
        "face_count": face_count,
        "quality": {
            "polygon_count": cell_count,
            "invalid_cell_count": 0,
            "cell_area": {"count": cell_count, "min": 1.0, "max": 2.0},
            "cell_aspect_ratio": {"count": cell_count, "max": 1.5},
            "face_length": {"count": face_count, "min": 0.5, "max": 3.0},
        },
        "mesh_topology": {
            "complete": complete,
            "fingerprint": fingerprint_digit * 64 if complete else None,
            "declared_cell_count": topology_cells,
            "face_count": topology_faces,
            "persisted_face_count": topology_faces,
            "missing_datasets": [] if complete else ["/missing/topology"],
            "errors": [],
            "components": {
                "ordered_nonvirtual_centers": {
                    "fingerprint": "c" * 64 if complete else None,
                },
                "ordered_faces_and_indexes": {
                    "fingerprint": "f" * 64 if complete else None,
                },
            },
        },
    }


def test_project_actions_prove_open_save_and_reopen(tmp_path):
    context = _context(tmp_path, "project.open")
    opened = project_open(context)
    assert opened["passed"] is True
    assert opened["evidence"]["plan_count"] == 1
    assert opened["evidence"]["geometry_count"] == 1

    context["operation_id"] = "project.save"
    saved = project_save(context, marker="persisted qualification marker")
    assert saved["passed"] is True
    assert saved["evidence"]["persisted_exactly"] is True
    assert saved["evidence"]["before_sha256"] != saved["evidence"]["after_sha256"]


def test_geometry_property_tables_requires_exact_configured_counts(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "properties.geometry_tables")
    (Path(context["project_folder"]) / "Action.g01.hdf").write_bytes(
        b"compiled geometry fixture"
    )
    monkeypatch.setattr(
        GeomMesh,
        "compute_property_tables",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(
            lambda _path: {
                "areas": {
                    "MainArea": {
                        "cell_count": 101,
                        "face_count": 222,
                        "cell_property_complete": True,
                        "face_property_complete": True,
                    }
                },
                "geometry_fingerprint": "fixture-fingerprint",
            }
        ),
    )

    passed = geometry_property_tables(
        context,
        geometry="Action.g01",
        mesh_name="MainArea",
        expected_cell_count=101,
        expected_face_count=222,
    )
    failed = geometry_property_tables(
        context,
        geometry="Action.g01",
        mesh_name="MainArea",
        expected_cell_count=100,
        expected_face_count=222,
    )

    assert passed["passed"] is True
    assert passed["evidence"]["count_checks"] == {
        "cell_count_exact": True,
        "face_count_exact": True,
    }
    assert failed["passed"] is False
    assert failed["evidence"]["count_checks"]["cell_count_exact"] is False


def test_terrain_import_requires_exact_layers_and_minimum_pyramids(
    tmp_path, monkeypatch
):
    import ras_commander.RasQualificationActions as qualification_actions
    from ras_commander.terrain import RasTerrain

    context = _context(tmp_path, "terrain.import")
    context["expected_version"] = "7.0.1"
    source = Path(context["project_folder"]) / "dem.tif"
    source.write_bytes(b"raster")
    channel = Path(context["project_folder"]) / "channel.tif"
    channel.write_bytes(b"channel")
    calls = []
    monkeypatch.setattr(
        qualification_actions,
        "_process_affinity_receipt",
        lambda: {
            "cpu_count": 1,
            "cpu_ids": [7],
            "process_mask_hex": "0x80",
            "system_mask_hex": "0xff",
        },
    )

    def create_terrain(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_folder"]) / f"{kwargs['terrain_name']}.hdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"terrain")
        return output

    monkeypatch.setattr(
        RasTerrain,
        "create_terrain_from_rasters",
        staticmethod(create_terrain),
    )
    monkeypatch.setattr(
        RasQualification,
        "terrain_receipt",
        staticmethod(
            lambda _hdf, _sources: {
                "source_rasters": [
                    {"path": str(source), "file_sha256": "source"},
                    {"path": str(channel), "file_sha256": "channel"},
                ],
                "layer_count": 2,
                "layer_priorities": {"channel": 0, "dem": 1},
                "pyramid_levels": {
                    "channel": [0, 1, 2],
                    "dem": [0, 1, 2, 3],
                },
                "stitch_datasets": {
                    "Stitch TIN Points": {
                        "present": True,
                        "shape": [11, 4],
                        "count": 11,
                        "fingerprint": "points",
                    },
                    "Stitch TIN Triangles": {
                        "present": True,
                        "shape": [7, 3],
                        "count": 7,
                        "fingerprint": "triangles",
                    },
                    "Stitches": {
                        "present": True,
                        "shape": [19, 7],
                        "count": 19,
                        "fingerprint": "stitches",
                    },
                },
                "terrain_hdf_fingerprint": "terrain-hdf",
                "terrain_hdf_raw_fingerprint": "terrain-hdf-raw",
                "data_fingerprint": "terrain-data",
                "raw_data_fingerprint": "terrain-data-raw",
            }
        ),
    )

    passed = terrain_import(
        context,
        input_rasters=["dem.tif", "channel.tif"],
        expected_layer_count=2,
        minimum_levels=3,
        expected_layer_priorities={"channel": 0, "dem": 1},
        expected_pyramid_levels={
            "channel": [0, 1, 2],
            "dem": [0, 1, 2, 3],
        },
        expected_stitch_dataset_shapes={
            "Stitch TIN Points": [11, 4],
            "Stitch TIN Triangles": [7, 3],
            "Stitches": [19, 7],
        },
        expected_stitch_dataset_counts={
            "Stitch TIN Points": 11,
            "Stitch TIN Triangles": 7,
            "Stitches": 19,
        },
        expected_terrain_hdf_fingerprint="terrain-hdf",
        expected_terrain_data_fingerprint="terrain-data",
        rasprocess_timeout_seconds=123,
        expected_process_cpu_count=1,
    )
    failed = terrain_import(
        context,
        input_rasters=["dem.tif", "channel.tif"],
        expected_layer_count=3,
        minimum_levels=3,
    )

    assert passed["passed"] is True
    assert passed["evidence"]["level_checks"] == {
        "channel": True,
        "dem": True,
    }
    assert passed["evidence"]["layer_count_exact"] is True
    assert all(passed["evidence"]["content_checks"].values())
    assert all(passed["evidence"]["stitch_shape_checks"].values())
    assert all(passed["evidence"]["stitch_count_checks"].values())
    assert calls[0]["timeout_seconds"] == 123
    assert passed["evidence"]["process_cpu_count_exact"] is True
    assert passed["evidence"]["process_cpu_affinity"]["cpu_ids"] == [7]
    assert failed["passed"] is False
    assert failed["evidence"]["layer_count_exact"] is False


def test_projection_select_requires_configured_sha256_and_normalized_epsg(
    tmp_path, monkeypatch
):
    import ras_commander.RasQualificationActions as qualification_actions
    from pyproj import CRS
    from ras_commander.RasMap import RasMap

    context = _context(tmp_path, "projection.select")
    project_folder = Path(context["project_folder"])
    projection = project_folder / "Projection.prj"
    muncie_wkt = (
        'PROJCS["NAD_1983_StatePlane_Indiana_East_FIPS_1301_Feet",'
        'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",'
        'SPHEROID["GRS_1980",6378137.0,298.257222101]],'
        'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
        'PROJECTION["Transverse_Mercator"],'
        'PARAMETER["False_Easting",328083.3333333333],'
        'PARAMETER["False_Northing",820208.3333333333],'
        'PARAMETER["Central_Meridian",-85.66666666666667],'
        'PARAMETER["Scale_Factor",0.9999666666666667],'
        'PARAMETER["Latitude_Of_Origin",37.5],'
        'UNIT["Foot_US",0.3048006096012192],AUTHORITY["EPSG",2965]]'
    )
    assert CRS.from_wkt(muncie_wkt).to_epsg() is None
    projection.write_text(muncie_wkt, encoding="utf-8")
    terrain = project_folder / "Terrain.hdf"
    terrain.write_bytes(b"terrain")
    rasmap = project_folder / "Action.rasmap"
    rasmap.write_text("<RASMapper />", encoding="utf-8")
    expected_sha256 = hashlib.sha256(projection.read_bytes()).hexdigest()

    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        rasmap_df=pd.DataFrame({"projection_path": [str(projection)]}),
        project_crs=muncie_wkt,
    )
    monkeypatch.setattr(qualification_actions, "_initialize", lambda _context: project)
    monkeypatch.setattr(
        RasMap,
        "add_terrain_layer",
        staticmethod(lambda **_kwargs: None),
    )

    passed = projection_select(
        context,
        projection_prj=projection.name,
        terrain_hdf=terrain.name,
        expected_projection_sha256=expected_sha256.upper(),
        expected_epsg=2965,
    )
    failed = projection_select(
        context,
        projection_prj=projection.name,
        terrain_hdf=terrain.name,
        expected_projection_sha256="0" * 64,
        expected_epsg=4326,
    )

    assert passed["passed"] is True
    assert passed["evidence"]["projection_sha256_exact"] is True
    assert passed["evidence"]["project_crs_epsg"] == 2965
    assert passed["evidence"]["project_crs_authority"] == {
        "name": "EPSG",
        "code": "2965",
    }
    assert passed["evidence"]["epsg_exact"] is True
    assert passed["evidence"]["epsg_min_confidence"] == 25
    assert failed["passed"] is False
    assert failed["evidence"]["projection_sha256_exact"] is False
    assert failed["evidence"]["epsg_exact"] is False


def test_projection_select_preserves_legacy_pass_without_exact_expectations(
    tmp_path, monkeypatch
):
    import ras_commander.RasQualificationActions as qualification_actions
    from ras_commander.RasMap import RasMap

    context = _context(tmp_path, "projection.select")
    project_folder = Path(context["project_folder"])
    projection = project_folder / "Projection.prj"
    projection.write_text("not a recognized CRS", encoding="utf-8")
    terrain = project_folder / "Terrain.hdf"
    terrain.write_bytes(b"terrain")
    rasmap = project_folder / "Action.rasmap"
    rasmap.write_text("<RASMapper />", encoding="utf-8")
    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        rasmap_df=pd.DataFrame({"projection_path": [str(projection)]}),
        project_crs="not a recognized CRS",
    )
    monkeypatch.setattr(qualification_actions, "_initialize", lambda _context: project)
    monkeypatch.setattr(
        RasMap,
        "add_terrain_layer",
        staticmethod(lambda **_kwargs: None),
    )

    result = projection_select(
        context,
        projection_prj=projection.name,
        terrain_hdf=terrain.name,
    )
    configured = projection_select(
        context,
        projection_prj=projection.name,
        terrain_hdf=terrain.name,
        expected_epsg=2965,
    )

    assert result["passed"] is True
    assert result["evidence"]["projection_sha256_exact"] is True
    assert result["evidence"]["epsg_exact"] is True
    assert result["evidence"]["project_crs_epsg"] is None
    assert result["evidence"]["project_crs_normalization_error"]
    assert configured["passed"] is False
    assert configured["evidence"]["epsg_exact"] is False
    assert configured["evidence"]["project_crs_normalization_error"]


def test_terrain_build_pyramids_fails_closed_on_exact_content_expectations(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "terrain.build_pyramids")
    terrain_hdf = Path(context["project_folder"]) / "Terrain" / "Qualification.hdf"
    terrain_hdf.parent.mkdir()
    terrain_hdf.write_bytes(b"terrain")
    context["qualification_terrain_hdf"] = str(terrain_hdf)

    receipt = {
        "source_rasters": [],
        "layer_count": 2,
        "layer_priorities": {"channel": 0, "base": 1},
        "pyramid_levels": {"channel": [0, 1], "base": [0, 1, 2]},
        "stitch_datasets": {
            "Stitch TIN Points": {
                "present": True,
                "shape": [17, 4],
                "count": 17,
                "fingerprint": "points",
            },
            "Stitch TIN Triangles": {
                "present": True,
                "shape": [13, 3],
                "count": 13,
                "fingerprint": "triangles",
            },
            "Stitches": {
                "present": True,
                "shape": [29, 7],
                "count": 29,
                "fingerprint": "stitches",
            },
        },
        "terrain_hdf_fingerprint": "semantic-golden",
        "terrain_hdf_raw_fingerprint": "raw-hdf",
        "data_fingerprint": "content-golden",
        "raw_data_fingerprint": "raw-content",
    }
    monkeypatch.setattr(
        RasQualification,
        "terrain_receipt",
        staticmethod(lambda _hdf, _sources: receipt),
    )
    common = {
        "expected_layer_priorities": {"channel": 0, "base": 1},
        "expected_pyramid_levels": {"channel": [0, 1], "base": [0, 1, 2]},
        "expected_stitch_dataset_shapes": {
            "Stitch TIN Points": [17, 4],
            "Stitch TIN Triangles": [13, 3],
            "Stitches": [29, 7],
        },
        "expected_stitch_dataset_counts": {
            "Stitch TIN Points": 17,
            "Stitch TIN Triangles": 13,
            "Stitches": 29,
        },
        "expected_terrain_hdf_fingerprint": "semantic-golden",
        "expected_terrain_data_fingerprint": "content-golden",
    }

    passed = terrain_build_pyramids(context, **common)
    wrong = {
        **common,
        "expected_layer_priorities": {"channel": 1, "base": 0},
        "expected_stitch_dataset_counts": {
            **common["expected_stitch_dataset_counts"],
            "Stitches": 30,
        },
        "expected_terrain_data_fingerprint": "wrong-content",
    }
    failed = terrain_build_pyramids(context, **wrong)

    assert passed["passed"] is True
    assert all(passed["evidence"]["content_checks"].values())
    assert failed["passed"] is False
    assert failed["evidence"]["content_checks"] == {
        "minimum_levels_present": True,
        "layer_priorities_exact": False,
        "pyramid_levels_exact": True,
        "stitch_dataset_shapes_exact": True,
        "stitch_dataset_counts_exact": False,
        "semantic_fingerprint_exact": True,
        "content_fingerprint_exact": False,
    }


def test_terrain_associate_preserves_exact_mesh_topology_and_golden_content(
    tmp_path,
    monkeypatch,
):
    actions_module = importlib.import_module("ras_commander.RasQualificationActions")
    context = _context(tmp_path, "terrain.associate")
    project_folder = Path(context["project_folder"])
    geom_path = project_folder / "Action.g01"
    geom_hdf = Path(str(geom_path) + ".hdf")
    geom_hdf.write_bytes(b"geometry")
    terrain_hdf = project_folder / "Qualification Terrain" / "Terrain.hdf"
    terrain_hdf.parent.mkdir()
    terrain_hdf.write_bytes(b"terrain")
    source = project_folder / "terrain-source.tif"
    source.write_bytes(b"source")
    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        geom_df=pd.DataFrame(
            {
                "geom_number": ["01"],
                "full_path": [str(geom_path)],
            }
        ),
    )
    monkeypatch.setattr(actions_module, "_initialize", lambda _context: project)
    association = {}

    def set_association(_geometry, **kwargs):
        association["terrain_hdf_path"] = str(kwargs["terrain_hdf_path"])
        kwargs["managed_host_evidence"].update(
            {
                "status": "complete",
                "return_code": 0,
                "command_returned": True,
            }
        )

    monkeypatch.setattr(
        GeomMesh,
        "set_geometry_association",
        staticmethod(set_association),
    )
    monkeypatch.setattr(
        GeomMesh,
        "get_geometry_association",
        staticmethod(lambda *_args, **_kwargs: dict(association)),
    )
    receipt_calls = []

    def geometry_receipt(_path):
        receipt_calls.append(True)
        return {
            "geometry_fingerprint": ("a" if len(receipt_calls) == 1 else "b") * 64,
            "areas": {
                "MainArea": _qualified_mesh_area(
                    10,
                    20,
                    fingerprint_digit="c",
                )
            },
        }

    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(geometry_receipt),
    )
    monkeypatch.setattr(
        actions_module,
        "_terrain_hdf_receipt",
        lambda *_args, **_kwargs: {
            "terrain_hdf_sha256": "d" * 64,
            "terrain_hdf_fingerprint": "e" * 64,
            "data_fingerprint": "f" * 64,
        },
    )

    result = terrain_associate(
        context,
        geometry="01",
        terrain_hdf=terrain_hdf,
        source_rasters=[source],
        mesh_name="MainArea",
        expected_cell_count=10,
        expected_face_count=20,
        expected_topology_fingerprint="c" * 64,
        expected_terrain_hdf_fingerprint="e" * 64,
        expected_terrain_data_fingerprint="f" * 64,
        interop_backend="managed_host",
    )

    assert result["passed"] is True
    assert result["evidence"]["content_checks"] == {
        "associated_exactly": True,
        "selected_mesh_present_before": True,
        "selected_mesh_present_after": True,
        "mesh_topology_complete": True,
        "mesh_topology_preserved": True,
        "cell_count_exact": True,
        "face_count_exact": True,
        "topology_fingerprint_exact": True,
        "terrain_hdf_fingerprint_exact": True,
        "terrain_data_fingerprint_exact": True,
    }
    assert result["evidence"]["managed_host"]["command_returned"] is True


def test_path_actions_open_content_identical_space_and_long_clones(tmp_path):
    context = _context(tmp_path, "path.spaces")
    outer_lock = RasQualification.acquire_project_lock(
        context["project_folder"], owner="runner-path-test"
    )
    spaces = path_variant_open(context)
    assert spaces["passed"] is True
    assert " " in spaces["evidence"]["destination"]
    assert spaces["evidence"]["source_fingerprint"] == spaces["evidence"]["destination_fingerprint"]
    assert spaces["evidence"]["transient_lock"]["source_present_during_stage"] is True
    assert spaces["evidence"]["transient_lock"]["excluded"] is True
    assert not (
        Path(spaces["evidence"]["destination"]) / RasQualification.PROJECT_LOCK_NAME
    ).exists()

    context["operation_id"] = "path.long"
    long_path = path_variant_open(context, minimum_long_path=180)
    assert long_path["passed"] is True
    assert long_path["evidence"]["path_length"] >= 180
    assert not (
        Path(long_path["evidence"]["destination"]) / RasQualification.PROJECT_LOCK_NAME
    ).exists()
    RasQualification.release_project_lock(outer_lock)


def test_geometry_action_distinguishes_creation_from_perimeter_edit(tmp_path):
    context = _context(tmp_path, "geometry.2d_area_create")
    created = geometry_area_or_perimeter(
        context,
        flow_area_name="QualArea",
        coordinates=[(0, 0), (10, 0), (10, 10), (0, 10)],
        compile_with_mapper=False,
    )
    assert created["passed"] is True
    assert created["evidence"]["existed_before"] is False

    context["operation_id"] = "geometry.perimeter_edit"
    edited = geometry_area_or_perimeter(
        context,
        flow_area_name="QualArea",
        coordinates=[(0, 0), (12, 0), (12, 10), (0, 10)],
        compile_with_mapper=False,
    )
    assert edited["passed"] is True
    assert edited["evidence"]["existed_before"] is True
    assert edited["evidence"]["before_sha256"] != edited["evidence"]["after_sha256"]


def test_geometry_action_requires_hecras_compile_and_exact_hdf_perimeter(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "geometry.2d_area_create")
    hdf_path = Path(context["project_folder"]) / "Action.g01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.require_group("Geometry/2D Flow Areas")
    geometry_receipt = {
        "geometry_fingerprint": "g" * 64,
        "areas": {
            "QualArea": {
                "cell_count": 0,
                "face_count": 0,
                "mesh_topology": {
                    "complete": False,
                    "fingerprint": None,
                },
            }
        },
    }
    actions_module = importlib.import_module(
        "ras_commander.RasQualificationActions"
    )
    monkeypatch.setattr(
        actions_module,
        "_compiled_2d_area_feature_receipt",
        lambda *args, **kwargs: {
            "passed": True,
            "flow_area_name": "QualArea",
            "cell_count": 0,
            "polygon_matches_text": True,
        },
    )
    preprocess_module = importlib.import_module("ras_commander.RasPreprocess")
    monkeypatch.setattr(
        preprocess_module.RasPreprocess,
        "preprocess_plan",
        lambda *args, **kwargs: SimpleNamespace(success=True),
    )
    mesh_module = importlib.import_module("ras_commander.geom.GeomMesh")
    monkeypatch.setattr(
        mesh_module,
        "_synchronize_persisted_hdf_mtime",
        lambda *args, **kwargs: {"verified": True, "mtime_updated": True},
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        lambda *args, **kwargs: geometry_receipt,
    )

    result = geometry_area_or_perimeter(
        context,
        flow_area_name="QualArea",
        coordinates=[(0, 0), (10, 0), (10, 10), (0, 10)],
        compile_with_mapper=True,
        preprocess_plan_number="01",
        expected_compiled_cell_count=0,
    )

    assert result["passed"] is True
    assert result["evidence"]["mapper_reopen_passed"] is True
    assert result["evidence"]["compiled_feature"]["polygon_matches_text"] is True
    assert result["evidence"]["selected_area"]["cell_count"] == 0
    assert result["evidence"]["mesh_generation_owned_by_separate_action"] is True


def test_boundary_conflict_repair_persists_text_and_mapper_reopen(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "boundary.conflict_repair")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    GeomStorage.set_2d_flow_area_perimeter(
        geom_path,
        flow_area_name="MainArea",
        coordinates=[(0, 0), (20, 0), (20, 20), (0, 20)],
        create_backup=False,
    )
    GeomBcLines.add_bc_lines(
        geom_path,
        [
            {
                "name": "NormDepth1",
                "storage_area": "MainArea",
                "coordinates": [(0, 0), (5, 0), (10, 0)],
            },
            {
                "name": "USInflow1",
                "storage_area": "MainArea",
                "coordinates": [(0, 0), (0, 5), (0, 10)],
            },
        ],
    )
    hdf_path.write_bytes(b"compiled conflict fixture")
    topology = "t" * 64
    assignments = [
        {
            "name": "NormDepth1",
            "mesh_name": "MainArea",
            "type": "External",
            "bc_line_id": 0,
        },
        {
            "name": "USInflow1",
            "mesh_name": "MainArea",
            "type": "External",
            "bc_line_id": 1,
        },
    ]
    receipt = {
        "geometry_fingerprint": "g" * 64,
        "boundary_assignments": assignments,
        "areas": {
            "MainArea": {
                "cell_count": 10,
                "face_count": 21,
                "mesh_topology": {
                    "complete": True,
                    "fingerprint": topology,
                },
            }
        },
    }
    conflict = BCConflict(
        face_id=4,
        flow_area_name="MainArea",
        bc_names=["NormDepth1", "USInflow1"],
        normal_depth_bc="NormDepth1",
    )
    detections = iter([[conflict], []])
    conflict_scales = []

    def detect_conflicts(_path, scale, **_kwargs):
        conflict_scales.append(float(scale))
        return next(detections)

    monkeypatch.setattr(
        GeomMesh,
        "detect_bc_conflicts",
        staticmethod(detect_conflicts),
    )

    def fix_conflicts(_path, scale, **_kwargs):
        conflict_scales.append(float(scale))
        return BCFixResult(
            conflicts_found=1,
            conflicts_fixed=1,
            trims=[("MainArea/NormDepth1", "trimmed 1 pts from start")],
            modified_hdf=True,
        )

    monkeypatch.setattr(
        GeomMesh,
        "fix_bc_conflicts",
        staticmethod(fix_conflicts),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(lambda *args, **kwargs: receipt),
    )
    from shapely.geometry import LineString

    repaired_frame = pd.DataFrame(
        [
            {
                "SA-2D": "MainArea",
                "Name": "NormDepth1",
                "geometry": LineString([(5, 0), (10, 0)]),
            },
            {
                "SA-2D": "MainArea",
                "Name": "USInflow1",
                "geometry": LineString([(0, 0), (0, 5), (0, 10)]),
            },
        ]
    )
    from ras_commander.hdf import HdfBndry

    monkeypatch.setattr(
        HdfBndry,
        "get_bc_lines",
        staticmethod(lambda *args, **kwargs: repaired_frame),
    )
    actions_module = importlib.import_module(
        "ras_commander.RasQualificationActions"
    )
    monkeypatch.setattr(
        actions_module,
        "mesh_generate",
        lambda *args, **kwargs: {
            "passed": True,
            "evidence": {"count_checks": {"expected_cells": True}},
            "artifacts": {"geometry": receipt},
        },
    )

    result = boundary_conflict_repair(
        context,
        geometry="Action.g01",
        cell_size=50,
        conflict_detection_cell_size=500,
        expected_cell_count=10,
        expected_face_count=21,
        expected_topology_fingerprint=topology,
    )

    assert result["passed"] is True
    assert result["evidence"]["text_matches_repair"] is True
    assert result["evidence"][
        "hdf_matches_repair_after_mapper_reopen"
    ] is True
    assert result["evidence"]["topology_preserved"] is True
    assert result["evidence"]["rolled_back"] is False
    assert result["evidence"]["mesh_cell_size"] == 50.0
    assert result["evidence"]["conflict_detection_cell_size"] == 500.0
    assert conflict_scales == [500.0, 500.0, 500.0]
    persisted = {
        item["name"]: item for item in GeomBcLines.get_bc_lines(geom_path)
    }
    assert persisted["NormDepth1"]["coordinates"] == [(5.0, 0.0), (10.0, 0.0)]


def test_boundary_associate_accepts_canonical_fixed_width_coordinate_precision(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "boundary.associate")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    unsteady_path = Path(context["project_folder"]) / "Action.u01"
    expected = [
        (2083619.25048206, 364802.613025156),
        (2083715.3463744002, 364884.6536255998),
        (2083750.0, 364909.7841174452),
    ]
    persisted = [
        (2083619.25, 364802.613),
        (2083715.346, 364884.6536),
        (2083750.0, 364909.7841),
    ]
    boundaries = pd.DataFrame(
        [
            {
                "area_2d": "MainArea",
                "bc_line_name": "QualConflict",
                "bc_type": "Normal Depth",
                "friction_slope_value": 0.001,
            }
        ]
    )
    fake_project = SimpleNamespace(boundaries_df=boundaries)
    actions_module = importlib.import_module("ras_commander.RasQualificationActions")
    monkeypatch.setattr(actions_module, "_initialize", lambda _context: fake_project)
    monkeypatch.setattr(
        GeomBcLines,
        "add_bc_lines",
        staticmethod(lambda *args, **kwargs: {"inserted": ["QualConflict"]}),
    )
    monkeypatch.setattr(
        GeomBcLines,
        "get_bc_lines",
        staticmethod(
            lambda *args, **kwargs: [
                {
                    "name": "QualConflict",
                    "storage_area": "MainArea",
                    "coordinates": persisted,
                }
            ]
        ),
    )
    from ras_commander.RasUnsteady import RasUnsteady

    monkeypatch.setattr(
        RasUnsteady,
        "ensure_2d_boundary_location",
        staticmethod(lambda *args, **kwargs: {"created": True}),
    )
    monkeypatch.setattr(
        RasUnsteady,
        "set_normal_depth_boundary",
        staticmethod(lambda *args, **kwargs: {"updated": True}),
    )

    result = boundary_associate(
        context,
        geometry=geom_path,
        unsteady=unsteady_path,
        line={
            "name": "QualConflict",
            "storage_area": "MainArea",
            "coordinates": expected,
        },
        friction_slope=0.001,
    )

    assert result["passed"] is True
    assert result["evidence"]["line_content_exact"] is True
    assert result["evidence"]["coordinate_max_abs_error"] == pytest.approx(
        0.000482060015201569
    )
    assert result["evidence"]["coordinate_abs_tolerance"] == 0.005


def test_mesh_action_requires_rasmapper_result_to_match_hdf_counts(tmp_path, monkeypatch):
    context = _context(tmp_path, "mesh.generate_initial")
    hdf_path = Path(context["project_folder"]) / "Action.g01.hdf"
    hdf_path.write_bytes(b"compiled geometry fixture")

    generate_calls = []

    def generate(*args, **kwargs):
        generate_calls.append(kwargs)
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            cell_count=10,
            face_count=21,
            geom_text_path=str(Path(context["project_folder"]) / "Action.g01"),
            geom_hdf_path=str(hdf_path),
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))
    geometry_receipt = {
        "path": str(hdf_path),
        "file_sha256": "a" * 64,
        "geometry_fingerprint": "b" * 64,
        "mesh_area_count": 1,
        "areas": {
            "MainArea": {
                "cell_count": 10,
                "face_count": 21,
                "face_property_complete": False,
                "cell_property_complete": False,
            }
        },
        "boundary_assignments": [],
        "breakline_count": 1,
        "refinement_region_count": 0,
    }
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(lambda _path: geometry_receipt),
    )

    matched = mesh_generate(
        context,
        expected_cell_count=10,
        expected_face_count=21,
        seed_generation_mode="point_generator",
    )
    assert matched["passed"] is True
    assert matched["artifacts"]["geometry"] == geometry_receipt
    assert generate_calls[0]["seed_generation_mode"] == "point_generator"

    mismatched = mesh_generate(context, expected_cell_count=11)
    assert mismatched["passed"] is False
    assert mismatched["evidence"]["count_checks"]["expected_cells"] is False


def test_managed_mesh_action_accepts_complete_text_seeds_before_preprocess(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.generate_initial")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"compiled geometry fixture")
    packed = "".join(f"{value:16.6f}" for value in (10.0, 20.0, 30.0, 40.0))
    geom_path.write_text(
        "Geom Title=Action\n"
        "Storage Area=MainArea,5.0,5.0\n"
        "Storage Area Surface Line= 5\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 0.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (10.0, 0.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (10.0, 10.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 10.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 0.0))}\n"
        "Storage Area Type= 0\n"
        "Storage Area Area=\n"
        "Storage Area Min Elev=\n"
        "Storage Area Is2D=-1\n"
        "Storage Area Point Generation Data=,,100.000000,100.000000\n"
        "Storage Area 2D Points= 2 \n"
        f"{packed}\n",
        encoding="utf-8",
    )
    original_text = geom_path.read_bytes()

    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(
            lambda *args, **kwargs: MeshResult(
                mesh_name="MainArea",
                status="complete",
                mesh_state="Complete",
                cell_count=2,
                face_count=5,
                geom_text_path=str(geom_path),
                geom_hdf_path=str(hdf_path),
                interop_backend="managed_host",
                seed_generation_mode="managed_host_regenerate",
            )
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(
            lambda _path: {
                "path": str(hdf_path),
                "file_sha256": "a" * 64,
                "geometry_fingerprint": "b" * 64,
                "mesh_area_count": 1,
                "areas": {"MainArea": {"cell_count": 10, "face_count": 21}},
                "boundary_assignments": [],
                "breakline_count": 0,
                "refinement_region_count": 0,
            }
        ),
    )

    result = mesh_generate(
        context,
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        interop_backend="managed_host",
    )

    assert result["passed"] is True
    assert result["evidence"]["persistence_mode"] == (
        "geometry_text_then_preprocess"
    )
    assert result["evidence"]["text_seed_receipt"]["coordinate_count"] == 2
    assert result["evidence"]["hdf_count_observation"][
        "matches_generated_mesh"
    ] is False


def test_managed_mesh_action_rejects_unobservable_fingerprint_before_preprocess(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.generate_initial")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"compiled geometry fixture")
    packed = "".join(f"{value:16.6f}" for value in (10.0, 20.0, 30.0, 40.0))
    geom_path.write_text(
        "Geom Title=Action\n"
        "Storage Area=MainArea\n"
        "Storage Area 2D Points= 2 \n"
        f"{packed}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(
            lambda *args, **kwargs: MeshResult(
                mesh_name="MainArea",
                status="complete",
                mesh_state="Complete",
                cell_count=2,
                face_count=5,
                geom_text_path=str(geom_path),
                geom_hdf_path=str(hdf_path),
                interop_backend="managed_host",
                seed_generation_mode="managed_host_regenerate",
            )
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(
            lambda _path: {
                "path": str(hdf_path),
                "file_sha256": "a" * 64,
                "geometry_fingerprint": "b" * 64,
                "mesh_area_count": 1,
                "areas": {"MainArea": {"cell_count": 10, "face_count": 21}},
                "boundary_assignments": [],
                "breakline_count": 0,
                "refinement_region_count": 0,
            }
        ),
    )

    result = mesh_generate(
        context,
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        expected_ordered_center_fingerprint="c" * 64,
        expected_ordered_face_fingerprint="f" * 64,
        interop_backend="managed_host",
    )

    assert result["passed"] is False
    checks = result["evidence"]["count_checks"]
    assert checks["hdf_persistence_deferred_to_preprocess"] is True
    assert checks["ordered_center_fingerprint_exact"] is False
    assert checks["ordered_face_fingerprint_exact"] is False
    assert checks["mesh_quality_complete"] is False


def test_managed_mesh_action_qualifies_transactional_hdf_persistence(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.generate_initial")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"compiled geometry fixture")
    packed = "".join(f"{value:16.6f}" for value in (10.0, 20.0, 30.0, 40.0))
    geom_path.write_text(
        "Geom Title=Action\n"
        "Storage Area=MainArea\n"
        "Storage Area 2D Points= 2 \n"
        f"{packed}\n",
        encoding="utf-8",
    )
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            mesh_state="Complete",
            cell_count=2,
            face_count=5,
            geom_text_path=str(geom_path),
            geom_hdf_path=str(hdf_path),
            interop_backend="managed_host",
            seed_generation_mode="managed_host_regenerate",
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=True,
            persisted_cell_count=2,
            persisted_face_count=5,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))
    geometry_receipt = {
        "path": str(hdf_path),
        "file_sha256": "a" * 64,
        "geometry_fingerprint": "b" * 64,
        "mesh_area_count": 1,
        "areas": {
            "MainArea": _qualified_mesh_area(
                2,
                5,
                fingerprint_digit="c",
            )
        },
        "boundary_assignments": [],
        "breakline_count": 0,
        "refinement_region_count": 0,
    }
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(lambda _path: geometry_receipt),
    )

    result = mesh_generate(
        context,
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        expected_topology_fingerprint="c" * 64,
        expected_ordered_center_fingerprint="c" * 64,
        expected_ordered_face_fingerprint="f" * 64,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is True
    assert result["evidence"]["persistence_mode"] == (
        "transactional_rasmapper_hdf"
    )
    assert result["evidence"]["count_checks"]["managed_hdf_persisted"] is True
    assert result["evidence"]["count_checks"]["mesh_topology_complete"] is True
    assert result["evidence"]["count_checks"][
        "ordered_center_fingerprint_exact"
    ] is True
    assert result["evidence"]["count_checks"][
        "ordered_face_fingerprint_exact"
    ] is True
    assert result["evidence"]["count_checks"]["mesh_quality_complete"] is True
    assert calls[0]["managed_host_persistence_mode"] == "transactional_direct"
    assert calls[0]["managed_host_expected_cell_count"] == 2
    assert calls[0]["managed_host_expected_face_count"] == 5


def test_managed_mesh_action_legacy_save_uses_geometry_receipt(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.regenerate")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    geom_path.write_text(
        "Storage Area=MainArea\n"
        "Storage Area 2D Points= 2 \n"
        f"{1.0:16.6f}{2.0:16.6f}{3.0:16.6f}{4.0:16.6f}\n",
        encoding="utf-8",
    )
    hdf_path.write_bytes(b"legacy product save")

    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(
            lambda *args, **kwargs: MeshResult(
                mesh_name="MainArea",
                status="complete",
                mesh_state="Complete",
                cell_count=2,
                face_count=5,
                geom_text_path=str(geom_path),
                geom_hdf_path=str(hdf_path),
                interop_backend="managed_host",
                seed_generation_mode="regenerate",
                hdf_persistence_mode="legacy_save",
                hdf_persisted=True,
                persisted_cell_count=0,
                persisted_face_count=0,
            )
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(
            lambda _path: {
                "path": str(hdf_path),
                "file_sha256": "a" * 64,
                "geometry_fingerprint": "b" * 64,
                "mesh_area_count": 1,
                "areas": {
                    "MainArea": _qualified_mesh_area(
                        2, 5, fingerprint_digit="c"
                    )
                },
                "boundary_assignments": [],
                "breakline_count": 0,
                "refinement_region_count": 0,
            }
        ),
    )

    result = mesh_generate(
        context,
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        interop_backend="managed_host",
        managed_host_persistence_mode="auto",
    )

    assert result["passed"] is True, result["evidence"]
    checks = result["evidence"]["count_checks"]
    assert checks["managed_hdf_persisted"] is True
    assert "managed_reopened_cells_exact" not in checks
    assert "managed_reopened_faces_exact" not in checks


def test_refinement_action_restores_hdf_after_mapper_rejection(tmp_path, monkeypatch):
    context = _context(tmp_path, "mesh.refinement_region")
    hdf_path = Path(context["project_folder"]) / "Action.g01.hdf"
    hdf_path.write_bytes(b"prechange compiled geometry")

    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions",
        staticmethod(
            lambda *args, **kwargs: (
                [] if hdf_path.read_bytes().startswith(b"prechange") else [
                    {"fid": 0, "name": "Qualification", "spacing_dx": 5.0,
                     "spacing_dy": 5.0}
                ]
            )
        ),
    )
    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions_mapper",
        staticmethod(
            lambda *args, **kwargs: (
                [] if hdf_path.read_bytes().startswith(b"prechange") else [
                    {
                        "fid": 0,
                        "name": "Qualification",
                        "spacing_dx": 5.0,
                        "spacing_dy": 5.0,
                        "point_count": 5,
                    }
                ]
            )
        ),
    )

    def add_region(*args, **kwargs):
        hdf_path.write_bytes(b"mutated invalid compiled geometry")
        return 0

    monkeypatch.setattr(GeomMesh, "add_refinement_region", staticmethod(add_region))
    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(
            lambda *args, **kwargs: MeshResult(
                mesh_name="MainArea",
                status="error",
                error_message="Mapper rejected region",
            )
        ),
    )

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": {
                    "cell_count": (
                        10 if Path(path).read_bytes().startswith(b"prechange") else 11
                    ),
                    "face_count": 20,
                }
            },
            "refinement_region_count": (
                0 if Path(path).read_bytes().startswith(b"prechange") else 1
            ),
        }

    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(receipt),
    )

    result = mesh_refinement_region(
        context,
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        spacing_dx=5.0,
        name="Qualification",
        mesh_name="MainArea",
    )

    assert result["passed"] is False
    assert hdf_path.read_bytes() == b"prechange compiled geometry"
    assert result["evidence"]["rolled_back_after_mapper_rejection"] is True
    assert result["evidence"]["rollback_restored_exact_geometry"] is True


def test_refinement_action_requires_mapper_reload_and_exact_mesh_content(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.refinement_region")
    hdf_path = Path(context["project_folder"]) / "Action.g01.hdf"
    hdf_path.write_bytes(b"prechange compiled geometry")

    def changed():
        return hdf_path.read_bytes().startswith(b"mutated")

    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions",
        staticmethod(
            lambda *args, **kwargs: (
                [{"fid": 0, "name": "Qualification", "spacing_dx": 5.0,
                  "spacing_dy": 5.0}]
                if changed()
                else []
            )
        ),
    )
    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions_mapper",
        staticmethod(
            lambda *args, **kwargs: (
                [{"fid": 0, "name": "Qualification", "spacing_dx": 5.0,
                  "spacing_dy": 5.0, "point_count": 5}]
                if changed()
                else []
            )
        ),
    )

    def add_region(*args, **kwargs):
        assert kwargs["use_rasmapper"] is True
        hdf_path.write_bytes(b"mutated valid compiled geometry")
        return 0

    monkeypatch.setattr(GeomMesh, "add_refinement_region", staticmethod(add_region))
    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(
            lambda *args, **kwargs: MeshResult(
                mesh_name="MainArea",
                status="complete",
                cell_count=14,
                face_count=26,
            )
        ),
    )

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": {
                    "cell_count": 14 if changed() else 10,
                    "face_count": 26 if changed() else 20,
                }
            },
            "refinement_region_count": 1 if changed() else 0,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_refinement_region(
        context,
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        spacing_dx=5.0,
        name="Qualification",
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=26,
        minimum_cell_count_delta=4,
    )

    assert result["passed"] is True, result["evidence"]
    assert result["evidence"]["count_checks"] == {
        "hdf_region_added": True,
        "rasmapper_region_added": True,
        "hdf_and_rasmapper_region_counts_match": True,
        "rasmapper_region_content_matches": True,
        "mesh_regenerated": True,
        "minimum_cell_count_delta": True,
        "expected_cells": True,
        "expected_faces": True,
    }
    assert result["evidence"]["cell_count_delta"] == 4


def test_managed_refinement_action_requires_product_reload_and_text_mesh(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.refinement_region")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"prechange compiled geometry")

    def write_seeds(count, values):
        packed = "".join(f"{value:16.6f}" for value in values)
        geom_path.write_text(
            "Geom Title=Action\n"
            "Storage Area=MainArea\n"
            f"Storage Area 2D Points= {count} \n"
            f"{packed}\n",
            encoding="utf-8",
        )

    write_seeds(2, (10.0, 20.0, 30.0, 40.0))

    def changed():
        return hdf_path.read_bytes().startswith(b"mutated")

    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions",
        staticmethod(
            lambda *args, **kwargs: (
                [
                    {
                        "fid": 0,
                        "name": "Qualification",
                        "spacing_dx": 5.0,
                        "spacing_dy": 5.0,
                    }
                ]
                if changed()
                else []
            )
        ),
    )

    def add_region(*args, **kwargs):
        assert kwargs["use_rasmapper"] is False
        assert kwargs["_require_current_hdf"] is False
        hdf_path.write_bytes(b"mutated complete region schema")
        return 0

    monkeypatch.setattr(GeomMesh, "add_refinement_region", staticmethod(add_region))

    product_region = {
        "fid": 0,
        "name": "Qualification",
        "spacing_dx": 5.0,
        "spacing_dy": 5.0,
        "point_count": 5,
    }

    generate_calls = []

    def generate(*args, **kwargs):
        assert kwargs["interop_backend"] == "managed_host"
        generate_calls.append(kwargs)
        if len(generate_calls) == 1:
            write_seeds(2, (10.0, 20.0, 30.0, 40.0))
            return MeshResult(
                mesh_name="MainArea",
                status="complete",
                mesh_state="Complete",
                cell_count=2,
                face_count=5,
                interop_backend="managed_host",
                product_refinement_regions=[],
            )
        write_seeds(3, (10.0, 20.0, 30.0, 40.0, 50.0, 60.0))
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            mesh_state="Complete",
            cell_count=3,
            face_count=7,
            interop_backend="managed_host",
            product_refinement_regions=[product_region],
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {"MainArea": {"cell_count": 2, "face_count": 5}},
            "refinement_region_count": 1 if changed() else 0,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_refinement_region(
        context,
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        spacing_dx=5.0,
        name="Qualification",
        mesh_name="MainArea",
        expected_cell_count=3,
        expected_face_count=7,
        minimum_cell_count_delta=1,
        interop_backend="managed_host",
    )

    assert result["passed"] is True, result["evidence"]
    assert result["evidence"]["persistence_mode"] == (
        "complete_hdf_region_schema_product_reloaded_and_text_mesh"
    )
    assert result["evidence"]["cell_count_delta"] == 1
    assert len(generate_calls) == 2
    assert result["evidence"]["baseline_mesh_result"]["cell_count"] == 2
    assert result["evidence"]["rasmapper_regions_after"] == [product_region]
    assert result["evidence"]["text_seed_receipt"]["coordinate_count"] == 3
    assert result["evidence"]["count_checks"][
        "hdf_and_rasmapper_region_counts_match"
    ] is True
    assert all(
        "managed_host_expected_cell_count" not in call
        and "managed_host_expected_face_count" not in call
        for call in generate_calls
    )


def test_transactional_refinement_uses_distinct_baseline_and_final_counts(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.refinement_region")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"initial compiled geometry")
    state = {"region_added": False, "stage": "initial"}

    def write_seeds(count):
        values = [float(value) for value in range(count * 2)]
        packed = "".join(f"{value:16.6f}" for value in values)
        geom_path.write_text(
            "Geom Title=Action\n"
            "Storage Area=MainArea\n"
            f"Storage Area 2D Points= {count} \n"
            f"{packed}\n",
            encoding="utf-8",
        )

    product_region = {
        "fid": 0,
        "name": "Qualification",
        "spacing_dx": 5.0,
        "spacing_dy": 5.0,
        "point_count": 5,
    }
    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions",
        staticmethod(
            lambda *args, **kwargs: (
                [dict(product_region)] if state["region_added"] else []
            )
        ),
    )

    def add_region(*args, **kwargs):
        assert kwargs["use_rasmapper"] is False
        assert kwargs["_require_current_hdf"] is False
        state["region_added"] = True
        state["stage"] = "region"
        hdf_path.write_bytes(b"compiled geometry with region")
        return 0

    monkeypatch.setattr(GeomMesh, "add_refinement_region", staticmethod(add_region))
    generate_calls = []

    def generate(*args, **kwargs):
        generate_calls.append(kwargs)
        baseline = len(generate_calls) == 1
        cells, faces = (10, 20) if baseline else (14, 28)
        state["stage"] = "baseline" if baseline else "final"
        hdf_path.write_bytes(state["stage"].encode("ascii"))
        write_seeds(cells)
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            mesh_state="Complete",
            cell_count=cells,
            face_count=faces,
            interop_backend="managed_host",
            product_refinement_regions=([] if baseline else [product_region]),
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=True,
            persisted_cell_count=cells,
            persisted_face_count=faces,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        final = state["stage"] == "final"
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": _qualified_mesh_area(
                    14 if final else 10,
                    28 if final else 20,
                    fingerprint_digit="b" if final else "a",
                ),
            },
            "boundary_assignments": [
                {
                    "name": "Upstream",
                    "mesh_name": "MainArea",
                    "type": "Flow Hydrograph",
                    "bc_line_id": 7,
                }
            ],
            "refinement_region_count": 1 if state["region_added"] else 0,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_refinement_region(
        context,
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        spacing_dx=5.0,
        name="Qualification",
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=28,
        baseline_expected_cell_count=10,
        baseline_expected_face_count=20,
        minimum_cell_count_delta=4,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is True, result["evidence"]
    assert len(generate_calls) == 2
    assert generate_calls[0]["managed_host_persistence_mode"] == (
        "transactional_direct"
    )
    assert generate_calls[0]["managed_host_expected_cell_count"] == 10
    assert generate_calls[0]["managed_host_expected_face_count"] == 20
    assert generate_calls[1]["managed_host_expected_cell_count"] == 14
    assert generate_calls[1]["managed_host_expected_face_count"] == 28
    assert result["evidence"]["persistence_mode"] == (
        "transactional_rasmapper_hdf"
    )
    checks = result["evidence"]["count_checks"]
    assert checks["baseline_hdf_persisted"] is True
    assert checks["managed_hdf_persisted"] is True
    assert checks["result_matches_hdf_cells"] is True
    assert checks["result_matches_hdf_faces"] is True
    assert checks["final_topology_complete"] is True
    assert checks["final_topology_declared_cells_exact"] is True
    assert checks["final_topology_persisted_faces_exact"] is True
    baseline_topology = result["evidence"]["baseline_mesh_topology"]
    assert baseline_topology["cell_count"] == 10
    assert baseline_topology["face_count"] == 20
    assert baseline_topology["topology_fingerprint"] == "a" * 64
    final_topology = result["evidence"]["final_mesh_topology"]
    assert final_topology["cell_count"] == 14
    assert final_topology["face_count"] == 28
    assert final_topology["topology_fingerprint"] == "b" * 64
    assert final_topology["ordered_center_fingerprint"] == "c" * 64
    assert final_topology["ordered_face_index_fingerprint"] == "f" * 64
    assert final_topology["quality_metrics"]["invalid_cell_count"] == 0
    assert final_topology["selected_area_boundary_assignments"] == [
        {
            "name": "Upstream",
            "mesh_name": "MainArea",
            "type": "Flow Hydrograph",
            "bc_line_id": 7,
        }
    ]
    assert "mesh_hdf_persistence_deferred_to_preprocess" not in checks


def test_transactional_refinement_rejects_incomplete_final_topology(
    tmp_path,
    monkeypatch,
):
    context = _context(tmp_path, "mesh.refinement_region")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    original_text = geom_path.read_bytes()
    original_hdf = b"initial compiled geometry"
    hdf_path.write_bytes(original_hdf)
    state = {"region_added": False, "generation": 0}
    product_region = {
        "fid": 0,
        "name": "Qualification",
        "spacing_dx": 5.0,
        "spacing_dy": 5.0,
        "point_count": 5,
    }

    monkeypatch.setattr(
        GeomMesh,
        "get_refinement_regions",
        staticmethod(
            lambda *args, **kwargs: (
                [dict(product_region)] if state["region_added"] else []
            )
        ),
    )

    def add_region(*args, **kwargs):
        state["region_added"] = True
        hdf_path.write_bytes(b"compiled geometry with region")
        return 0

    monkeypatch.setattr(GeomMesh, "add_refinement_region", staticmethod(add_region))

    def generate(*args, **kwargs):
        state["generation"] += 1
        baseline = state["generation"] == 1
        cells, faces = (10, 20) if baseline else (14, 28)
        hdf_path.write_bytes(b"baseline" if baseline else b"final")
        values = [float(value) for value in range(cells * 2)]
        geom_path.write_text(
            "Geom Title=Action\n"
            "Storage Area=MainArea\n"
            f"Storage Area 2D Points= {cells} \n"
            + "".join(f"{value:16.6f}" for value in values)
            + "\n",
            encoding="utf-8",
        )
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            cell_count=cells,
            face_count=faces,
            interop_backend="managed_host",
            product_refinement_regions=([] if baseline else [product_region]),
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=True,
            persisted_cell_count=cells,
            persisted_face_count=faces,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        content = Path(path).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        final = content == b"final"
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": _qualified_mesh_area(
                    14 if final else 10,
                    28 if final else 20,
                    fingerprint_digit="b" if final else "a",
                    complete=not final,
                )
            },
            "boundary_assignments": [],
            "refinement_region_count": 1 if state["region_added"] else 0,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_refinement_region(
        context,
        polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        spacing_dx=5.0,
        name="Qualification",
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=28,
        baseline_expected_cell_count=10,
        baseline_expected_face_count=20,
        minimum_cell_count_delta=4,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is False
    assert result["evidence"]["count_checks"]["final_topology_complete"] is False
    assert result["evidence"]["rolled_back_after_mapper_rejection"] is True
    assert result["evidence"]["baseline_mesh_topology"][
        "topology_fingerprint"
    ] == "a" * 64
    assert geom_path.read_bytes() == original_text
    assert hdf_path.read_bytes() == original_hdf


def test_transactional_refinement_requires_baseline_and_final_counts(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.refinement_region")
    (Path(context["project_folder"]) / "Action.g01.hdf").write_bytes(b"compiled")
    generate_calls = []
    monkeypatch.setattr(
        GeomMesh,
        "generate",
        staticmethod(lambda *args, **kwargs: generate_calls.append(kwargs)),
    )

    with pytest.raises(ValueError, match="baseline and final counts"):
        mesh_refinement_region(
            context,
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            spacing_dx=5.0,
            expected_cell_count=14,
            expected_face_count=28,
            interop_backend="managed_host",
            managed_host_persistence_mode="transactional_direct",
        )

    assert generate_calls == []


def test_plan_preprocess_requires_compiled_geometry_to_match_text_mesh(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "plan.preprocess")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"compiled geometry")
    packed = "".join(f"{value:16.6f}" for value in (10.0, 20.0, 30.0, 40.0))
    geom_path.write_text(
        "Geom Title=Action\n"
        "Storage Area=MainArea,5.0,5.0\n"
        "Storage Area Surface Line= 5\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 0.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (10.0, 0.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (10.0, 10.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 10.0))}\n"
        f"{''.join(f'{value:16.6f}' for value in (0.0, 0.0))}\n"
        "Storage Area Type= 0\n"
        "Storage Area Area=\n"
        "Storage Area Min Elev=\n"
        "Storage Area Is2D=-1\n"
        "Storage Area Point Generation Data=,,100.000000,100.000000\n"
        "Storage Area 2D Points= 2 \n"
        f"{packed}\n",
        encoding="utf-8",
    )
    original_text = geom_path.read_bytes()
    outputs = []
    for name in ("Action.p01.tmp.hdf", "Action.b01", "Action.x01"):
        path = Path(context["project_folder"]) / name
        path.write_bytes(name.encode("ascii"))
        outputs.append(path)

    from ras_commander.RasPreprocess import RasPreprocess

    monkeypatch.setattr(
        RasPreprocess,
        "preprocess_plan",
        staticmethod(
            lambda *args, **kwargs: SimpleNamespace(
                success=True,
                tmp_hdf_path=outputs[0],
                b_file_path=outputs[1],
                x_file_path=outputs[2],
                __bool__=lambda self: True,
            )
        ),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "run_ras_geom_preprocess",
        staticmethod(
            lambda *args, **kwargs: SimpleNamespace(
                success=True,
                return_code=0,
                hdf_readable=True,
                geometry_group_present=True,
                output_changed=True,
            )
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(
            lambda _path: {
                "geometry_fingerprint": "f" * 64,
                "areas": {
                    "MainArea": {
                        "cell_count": 2,
                        "face_count": 5,
                        "cell_property_complete": True,
                        "face_property_complete": True,
                        "mesh_topology": {
                            "complete": True,
                            "fingerprint": "mesh-topology",
                            "datasets": {
                                "Attributes (Name and Cell Count)": {
                                    "dtype": {
                                        "descr": [
                                            ["Name", "|S16"],
                                            ["Cell Count", "<i4"],
                                        ]
                                    }
                                }
                            },
                        },
                        "quality": {"invalid_cell_count": 0},
                    }
                },
            }
        ),
    )

    result = plan_preprocess(
        context,
        plan_number="01",
        geometry="Action.g01",
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        force_text_geometry_recompile=True,
    )

    assert result["passed"] is True
    assert result["evidence"]["count_checks"] == {
        "preprocess_succeeded": True,
        "vendor_geometry_preprocessor_succeeded": True,
        "all_prerequisites_present": True,
        "expected_cells": True,
        "expected_faces": True,
        "plan_hdf_expected_cells": True,
        "plan_hdf_expected_faces": True,
        "geometry_property_tables_complete": True,
        "geometry_topology_complete": True,
        "plan_hdf_topology_complete": True,
        "geometry_attributes_name_width_16": True,
        "plan_hdf_attributes_name_width_16": True,
        "plan_hdf_property_tables_complete": True,
        "geometry_hdf_matches_text_seed_count": True,
        "property_table_transition_observed": True,
        "geometry_topology_preserved": True,
        "plan_hdf_topology_matches_geometry": True,
        "geometry_expected_ordered_center_fingerprint": True,
        "geometry_expected_ordered_face_fingerprint": True,
        "plan_hdf_expected_ordered_center_fingerprint": True,
        "plan_hdf_expected_ordered_face_fingerprint": True,
        "text_geometry_recompile_applied": True,
        "boundary_repair_survived_preprocess": True,
    }
    assert all(
        len(item["sha256"]) == 64
        for item in result["evidence"]["files"].values()
    )
    assert geom_path.read_bytes() != original_text
    recompile = result["evidence"]["text_geometry_recompile"]
    assert recompile["requested"] is True
    assert recompile["applied"] is True
    assert recompile["canonicalized"] is True
    assert recompile["content_changed_by_canonicalization"] is True
    assert recompile["mesh_seed_coordinates_preserved"] is True
    assert recompile["point_generation_data_before"] == (
        ",,100.000000,100.000000"
    )
    assert recompile["point_generation_data_after"] == ",,100,100"
    assert recompile["text_newer_than_hdf"] is True
    assert recompile["geometry_text_mtime_ns_after"] > recompile[
        "geometry_hdf_mtime_ns"
    ]


@pytest.mark.parametrize(
    (
        "plan_topology",
        "geometry_topology",
        "plan_semantic_topology",
        "geometry_semantic_topology",
        "require_topology_preserved",
        "expected_passed",
        "expected_preserved",
        "expected_plan_matches",
    ),
    [
        (
            "mesh-topology",
            "mesh-topology",
            "mesh-topology",
            "mesh-topology",
            True,
            True,
            True,
            True,
        ),
        (
            "changed-topology",
            "changed-topology",
            "changed-topology",
            "changed-topology",
            True,
            False,
            False,
            True,
        ),
        (
            "changed-topology",
            "mesh-topology",
            "changed-topology",
            "mesh-topology",
            False,
            False,
            True,
            False,
        ),
        (
            "plan-canonical-storage",
            "geometry-canonical-storage",
            "mesh-topology",
            "mesh-topology",
            True,
            True,
            True,
            True,
        ),
    ],
)
def test_plan_preprocess_owns_property_transition_and_preserves_topology(
    tmp_path,
    monkeypatch,
    plan_topology,
    geometry_topology,
    plan_semantic_topology,
    geometry_semantic_topology,
    require_topology_preserved,
    expected_passed,
    expected_preserved,
    expected_plan_matches,
):
    context = _context(tmp_path, "plan.preprocess")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"compiled geometry")
    packed = "".join(f"{value:16.6f}" for value in (10.0, 20.0, 30.0, 40.0))
    geom_path.write_text(
        "Geom Title=Action\n"
        "Storage Area=MainArea\n"
        "Storage Area 2D Points= 2 \n"
        f"{packed}\n",
        encoding="utf-8",
    )
    outputs = []
    for name in ("Action.p01.tmp.hdf", "Action.b01", "Action.x01"):
        path = Path(context["project_folder"]) / name
        path.write_bytes(name.encode("ascii"))
        outputs.append(path)

    from ras_commander.RasPreprocess import RasPreprocess

    monkeypatch.setattr(
        RasPreprocess,
        "preprocess_plan",
        staticmethod(
            lambda *args, **kwargs: SimpleNamespace(
                success=True,
                tmp_hdf_path=outputs[0],
                b_file_path=outputs[1],
                x_file_path=outputs[2],
            )
        ),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "run_ras_geom_preprocess",
        staticmethod(lambda *args, **kwargs: SimpleNamespace(success=True)),
    )

    def receipt(*, tables_complete, topology, semantic_topology=None):
        semantic_topology = semantic_topology or topology
        return {
            "geometry_fingerprint": f"geometry-{topology}",
            "areas": {
                "MainArea": {
                    "cell_count": 2,
                    "face_count": 5,
                    "cell_property_complete": tables_complete,
                    "face_property_complete": tables_complete,
                    "mesh_topology": {
                        "complete": True,
                        "fingerprint": topology,
                        "components": {
                            "ordered_nonvirtual_centers": {
                                "fingerprint": f"centers-{semantic_topology}",
                            },
                            "ordered_faces_and_indexes": {
                                "fingerprint": f"faces-{semantic_topology}",
                            },
                        },
                        "datasets": {
                            "Attributes (Name and Cell Count)": {
                                "dtype": {
                                    "descr": [
                                        ["Name", "|S16"],
                                        ["Cell Count", "<i4"],
                                    ]
                                }
                            }
                        },
                    },
                    "quality": {"invalid_cell_count": 0},
                }
            },
        }

    receipts = iter(
        [
            receipt(tables_complete=False, topology="mesh-topology"),
            receipt(
                tables_complete=True,
                topology=plan_topology,
                semantic_topology=plan_semantic_topology,
            ),
            receipt(
                tables_complete=True,
                topology=geometry_topology,
                semantic_topology=geometry_semantic_topology,
            ),
        ]
    )
    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(lambda _path: next(receipts)),
    )

    result = plan_preprocess(
        context,
        plan_number="01",
        geometry="Action.g01",
        mesh_name="MainArea",
        expected_cell_count=2,
        expected_face_count=5,
        expected_ordered_center_fingerprint="centers-mesh-topology",
        expected_ordered_face_fingerprint="faces-mesh-topology",
        require_property_table_transition=True,
        require_topology_preserved=require_topology_preserved,
    )

    assert result["passed"] is expected_passed
    assert result["evidence"]["count_checks"][
        "property_table_transition_observed"
    ] is True
    assert result["evidence"]["count_checks"][
        "geometry_topology_preserved"
    ] is expected_preserved
    assert result["evidence"]["count_checks"][
        "plan_hdf_topology_matches_geometry"
    ] is expected_plan_matches
    comparison = result["evidence"]["topology_comparison"]
    assert comparison["mode"] == "semantic_components"
    assert comparison["geometry_preserved"] is expected_preserved
    assert comparison["plan_matches_geometry"] is expected_plan_matches
    expected_golden_match = geometry_semantic_topology == "mesh-topology"
    assert result["evidence"]["count_checks"][
        "geometry_expected_ordered_center_fingerprint"
    ] is expected_golden_match
    assert result["evidence"]["count_checks"][
        "geometry_expected_ordered_face_fingerprint"
    ] is expected_golden_match
    assert result["evidence"][
        "property_table_generation_owned_by_preprocess"
    ] is True


def test_breakline_action_restores_text_and_hdf_after_mapper_rejection(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.breakline")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    original_text = geom_path.read_bytes()
    hdf_path.write_bytes(b"prechange compiled geometry")

    def spacing(*args, **kwargs):
        if geom_path.read_bytes() == original_text:
            return [(0, "Channel", 10.0, 20.0, 0, 0)]
        return [(0, "Channel", 12.0, 30.0, 2, 1)]

    monkeypatch.setattr(GeomMesh, "get_breakline_spacing", staticmethod(spacing))

    def generate(*args, **kwargs):
        geom_path.write_bytes(b"mutated text geometry")
        hdf_path.write_bytes(b"mutated compiled geometry")
        return MeshResult(
            mesh_name="MainArea",
            status="error",
            error_message="Mapper rejected breakline",
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "breakline_count": 1,
        }

    monkeypatch.setattr(
        RasQualification,
        "geometry_receipt",
        staticmethod(receipt),
    )

    result = mesh_breakline(
        context,
        breakline_fid=0,
        near=12.0,
        far=30.0,
        near_repeats=2,
        protection_radius=1,
        mesh_name="MainArea",
    )

    assert result["passed"] is False
    assert geom_path.read_bytes() == original_text
    assert hdf_path.read_bytes() == b"prechange compiled geometry"
    assert not geom_path.with_suffix(".g01.bak").exists()
    assert result["evidence"]["rolled_back_after_mapper_rejection"] is True
    assert result["evidence"]["rollback_restored_exact_geometry"] is True
    assert result["evidence"]["rollback_restored_exact_text"] is True


def test_breakline_action_dispatches_creation_with_exact_mesh_contract(
    tmp_path,
    monkeypatch,
):
    context = _context(tmp_path, "mesh.breakline")
    module = importlib.import_module("ras_commander.RasQualificationActions")
    captured = {}

    def fake_create(received_context, **parameters):
        captured["context"] = received_context
        captured.update(parameters)
        return {"passed": True, "evidence": {"created": True}}

    monkeypatch.setattr(module, "_mesh_breakline_create", fake_create)

    result = mesh_breakline(
        context,
        geometry="Action.g01",
        polyline=[(10.0, 20.0), (30.0, 40.0)],
        name="Qualification breakline",
        near=25.0,
        far=50.0,
        near_repeats=2,
        protection_radius=1,
        mesh_name="MainArea",
        baseline_expected_cell_count=100,
        baseline_expected_face_count=220,
        expected_cell_count=112,
        expected_face_count=250,
        expected_ordered_center_fingerprint="c" * 64,
        expected_ordered_face_fingerprint="f" * 64,
        minimum_cell_count_delta=12,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
        cell_size=100.0,
    )

    assert result["passed"] is True
    assert captured["context"] is context
    assert captured["polyline"] == [(10.0, 20.0), (30.0, 40.0)]
    assert captured["baseline_expected_cell_count"] == 100
    assert captured["expected_cell_count"] == 112
    assert captured["expected_ordered_center_fingerprint"] == "c" * 64
    assert captured["expected_ordered_face_fingerprint"] == "f" * 64
    assert captured["minimum_cell_count_delta"] == 12
    assert captured["mesh_parameters"]["cell_size"] == 100.0


def test_transactional_breakline_qualifies_reopened_hdf_and_exact_counts(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.breakline")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    hdf_path.write_bytes(b"initial compiled geometry")
    state = {"updated": False}
    generate_calls = []

    monkeypatch.setattr(
        GeomMesh,
        "get_breakline_spacing",
        staticmethod(
            lambda *args, **kwargs: [
                (0, "Channel", 12.0, 30.0, 2, 1)
                if state["updated"]
                else (0, "Channel", 10.0, 20.0, 0, 0)
            ]
        ),
    )

    def generate(*args, **kwargs):
        generate_calls.append(kwargs)
        state["updated"] = True
        geom_path.write_bytes(b"updated text geometry")
        hdf_path.write_bytes(b"transactionally persisted compiled geometry")
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            mesh_state="Complete",
            cell_count=14,
            face_count=28,
            interop_backend="managed_host",
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=True,
            persisted_cell_count=14,
            persisted_face_count=28,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": _qualified_mesh_area(
                    14 if state["updated"] else 10,
                    28 if state["updated"] else 20,
                    fingerprint_digit="b" if state["updated"] else "a",
                ),
            },
            "boundary_assignments": [
                {
                    "name": "Downstream",
                    "mesh_name": "MainArea",
                    "type": "Normal Depth",
                    "bc_line_id": 9,
                }
            ],
            "breakline_count": 1,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_breakline(
        context,
        breakline_fid=0,
        near=12.0,
        far=30.0,
        near_repeats=2,
        protection_radius=1,
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=28,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is True, result["evidence"]
    assert len(generate_calls) == 1
    assert generate_calls[0]["managed_host_persistence_mode"] == (
        "transactional_direct"
    )
    assert generate_calls[0]["managed_host_expected_cell_count"] == 14
    assert generate_calls[0]["managed_host_expected_face_count"] == 28
    assert result["evidence"]["persistence_mode"] == (
        "transactional_rasmapper_hdf"
    )
    checks = result["evidence"]["mesh_count_checks"]
    assert checks["managed_hdf_persisted"] is True
    assert checks["managed_reopened_cells_exact"] is True
    assert checks["managed_reopened_faces_exact"] is True
    assert checks["result_matches_hdf_cells"] is True
    assert checks["result_matches_hdf_faces"] is True
    assert checks["final_topology_complete"] is True
    final_topology = result["evidence"]["final_mesh_topology"]
    assert final_topology["cell_count"] == 14
    assert final_topology["face_count"] == 28
    assert final_topology["topology_fingerprint"] == "b" * 64
    assert final_topology["ordered_center_fingerprint"] == "c" * 64
    assert final_topology["ordered_face_index_fingerprint"] == "f" * 64
    assert final_topology["quality_metrics"]["polygon_count"] == 14
    assert final_topology["selected_area_boundary_assignments"] == [
        {
            "name": "Downstream",
            "mesh_name": "MainArea",
            "type": "Normal Depth",
            "bc_line_id": 9,
        }
    ]
    assert result["evidence"]["text_seed_receipt"] is None


@pytest.mark.parametrize(
    ("topology_defect", "failed_check"),
    [
        ("missing_area", "final_selected_area_present"),
        ("incomplete", "final_topology_complete"),
        ("count_mismatch", "final_topology_declared_cells_exact"),
    ],
)
def test_transactional_breakline_rejects_unqualified_final_topology(
    tmp_path,
    monkeypatch,
    topology_defect,
    failed_check,
):
    context = _context(tmp_path, "mesh.breakline")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    original_text = geom_path.read_bytes()
    original_hdf = b"initial compiled geometry"
    hdf_path.write_bytes(original_hdf)

    monkeypatch.setattr(
        GeomMesh,
        "get_breakline_spacing",
        staticmethod(
            lambda *args, **kwargs: [
                (0, "Channel", 10.0, 20.0, 0, 0)
                if geom_path.read_bytes() == original_text
                else (0, "Channel", 12.0, 30.0, 2, 1)
            ]
        ),
    )

    def generate(*args, **kwargs):
        geom_path.write_bytes(b"updated text geometry")
        hdf_path.write_bytes(b"transactionally persisted compiled geometry")
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            cell_count=14,
            face_count=28,
            interop_backend="managed_host",
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=True,
            persisted_cell_count=14,
            persisted_face_count=28,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        content = Path(path).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        persisted = content != original_hdf
        if persisted and topology_defect == "missing_area":
            areas = {}
        else:
            areas = {
                "MainArea": _qualified_mesh_area(
                    14 if persisted else 10,
                    28 if persisted else 20,
                    fingerprint_digit="b" if persisted else "a",
                    complete=not (persisted and topology_defect == "incomplete"),
                    topology_cell_count=(
                        13
                        if persisted and topology_defect == "count_mismatch"
                        else None
                    ),
                )
            }
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": areas,
            "boundary_assignments": [],
            "breakline_count": 1,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_breakline(
        context,
        breakline_fid=0,
        near=12.0,
        far=30.0,
        near_repeats=2,
        protection_radius=1,
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=28,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is False
    assert result["evidence"]["mesh_count_checks"][failed_check] is False
    assert result["evidence"]["rolled_back_after_mapper_rejection"] is True
    assert geom_path.read_bytes() == original_text
    assert hdf_path.read_bytes() == original_hdf


def test_transactional_breakline_rolls_back_when_hdf_not_persisted(
    tmp_path, monkeypatch
):
    context = _context(tmp_path, "mesh.breakline")
    geom_path = Path(context["project_folder"]) / "Action.g01"
    hdf_path = Path(str(geom_path) + ".hdf")
    original_text = geom_path.read_bytes()
    hdf_path.write_bytes(b"initial compiled geometry")
    state = {"updated": False}

    monkeypatch.setattr(
        GeomMesh,
        "get_breakline_spacing",
        staticmethod(
            lambda *args, **kwargs: [
                (0, "Channel", 12.0, 30.0, 2, 1)
                if state["updated"]
                else (0, "Channel", 10.0, 20.0, 0, 0)
            ]
        ),
    )

    def generate(*args, **kwargs):
        state["updated"] = True
        geom_path.write_bytes(b"updated text geometry")
        hdf_path.write_bytes(b"unqualified compiled geometry")
        return MeshResult(
            mesh_name="MainArea",
            status="complete",
            cell_count=14,
            face_count=28,
            interop_backend="managed_host",
            hdf_persistence_mode="transactional_direct",
            hdf_persisted=False,
            persisted_cell_count=14,
            persisted_face_count=28,
        )

    monkeypatch.setattr(GeomMesh, "generate", staticmethod(generate))

    def receipt(path):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        persisted = Path(path).read_bytes() != b"initial compiled geometry"
        return {
            "file_sha256": digest,
            "geometry_fingerprint": digest,
            "areas": {
                "MainArea": {
                    "cell_count": 14 if persisted else 10,
                    "face_count": 28 if persisted else 20,
                }
            },
            "breakline_count": 1,
        }

    monkeypatch.setattr(RasQualification, "geometry_receipt", staticmethod(receipt))

    result = mesh_breakline(
        context,
        breakline_fid=0,
        near=12.0,
        far=30.0,
        near_repeats=2,
        protection_radius=1,
        mesh_name="MainArea",
        expected_cell_count=14,
        expected_face_count=28,
        interop_backend="managed_host",
        managed_host_persistence_mode="transactional_direct",
    )

    assert result["passed"] is False
    assert result["evidence"]["mesh_count_checks"]["managed_hdf_persisted"] is False
    assert result["evidence"]["rolled_back_after_mapper_rejection"] is True
    assert geom_path.read_bytes() == original_text
    assert hdf_path.read_bytes() == b"initial compiled geometry"


def test_transactional_breakline_requires_exact_final_counts(tmp_path):
    context = _context(tmp_path, "mesh.breakline")
    (Path(context["project_folder"]) / "Action.g01.hdf").write_bytes(b"compiled")

    with pytest.raises(ValueError, match="exact final counts"):
        mesh_breakline(
            context,
            managed_host_persistence_mode="transactional_direct",
            expected_cell_count=14,
        )


def test_mapper_export_requires_every_requested_georeferenced_raster(
    tmp_path,
    monkeypatch,
):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    from ras_commander.RasProcess import RasProcess

    context = _context(tmp_path, "mapper.export_geotiff")
    output = Path(context["project_folder"]) / "Qualification Maps"
    output.mkdir()
    rasters = {}
    for key, filename in {
        "wse": "WSE Max.tif",
        "depth": "Depth Max.tif",
        "velocity": "Velocity Max.tif",
    }.items():
        path = output / filename
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:5070",
            transform=from_origin(0, 2, 1, 1),
            nodata=-9999.0,
        ) as dataset:
            dataset.write(np.full((1, 2, 2), 1.0, dtype=np.float32))
        rasters[key] = [path]

    monkeypatch.setattr(
        RasProcess,
        "store_maps",
        staticmethod(lambda *args, **kwargs: rasters),
    )
    result = mapper_export_geotiff(
        context,
        plan_number="01",
        wse=True,
        depth=True,
        velocity=True,
    )
    assert result["passed"] is True
    assert result["evidence"]["requested_map_checks"] == {
        "wse": True,
        "depth": True,
        "velocity": True,
    }
    assert set(result["evidence"]["rasters_by_type"]) == {
        "wse",
        "depth",
        "velocity",
    }
    assert all(
        len(result["evidence"]["rasters_by_type"][map_type]) == 1
        for map_type in ("wse", "depth", "velocity")
    )
    assert result["artifacts"]["map_rasters_by_type"] == result["evidence"][
        "rasters_by_type"
    ]
    assert len(result["artifacts"]["map_rasters"]) == 3
    assert result["artifacts"]["depth_grid"]["path"].endswith("Depth Max.tif")

    monkeypatch.setattr(
        RasProcess,
        "store_maps",
        staticmethod(lambda *args, **kwargs: {key: value for key, value in rasters.items() if key != "velocity"}),
    )
    missing = mapper_export_geotiff(
        context,
        plan_number="01",
        wse=True,
        depth=True,
        velocity=True,
    )
    assert missing["passed"] is False
    assert missing["evidence"]["requested_map_checks"]["velocity"] is False
    assert missing["artifacts"]["map_rasters_by_type"]["velocity"] == []

    ungeoreferenced = output / "Velocity Without CRS.tif"
    with rasterio.open(
        ungeoreferenced,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        transform=from_origin(0, 2, 1, 1),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(np.full((1, 2, 2), 1.0, dtype=np.float32))
    ungeoreferenced_maps = dict(rasters)
    ungeoreferenced_maps["velocity"] = [ungeoreferenced]
    monkeypatch.setattr(
        RasProcess,
        "store_maps",
        staticmethod(lambda *args, **kwargs: ungeoreferenced_maps),
    )
    invalid = mapper_export_geotiff(
        context,
        plan_number="01",
        wse=True,
        depth=True,
        velocity=True,
    )
    assert invalid["passed"] is False
    velocity_checks = invalid["evidence"]["requested_map_receipt_checks"][
        "velocity"
    ]
    assert velocity_checks["checks"]["every_raster_georeferenced"] is False
    assert velocity_checks["passed"] is False

    boundary = output / "Inundation Boundary (Max).shp"
    boundary.write_bytes(b"qualification boundary fixture")
    maps_with_boundary = dict(rasters)
    maps_with_boundary["inundation_boundary"] = [boundary]
    monkeypatch.setattr(
        RasProcess,
        "store_maps",
        staticmethod(lambda *args, **kwargs: maps_with_boundary),
    )
    with_boundary = mapper_export_geotiff(
        context,
        plan_number="01",
        wse=True,
        depth=True,
        velocity=True,
        inundation_boundary=True,
    )
    assert with_boundary["passed"] is True
    assert with_boundary["evidence"]["requested_map_checks"][
        "inundation_boundary"
    ] is True
    assert "inundation_boundary" not in with_boundary["artifacts"][
        "map_rasters_by_type"
    ]


def test_mapper_result_layers_registers_and_reopens_exact_children(tmp_path):
    context = _context(tmp_path, "mapper.result_layers")
    project_folder = Path(context["project_folder"])
    (project_folder / "Action.p01.hdf").write_bytes(b"result fixture")
    (project_folder / "Action.rasmap").write_text(
        "<RASMapper><Results Checked=\"True\" /></RASMapper>",
        encoding="utf-8",
    )

    result = mapper_result_layers(
        context,
        plan_number="01",
        profile="Max",
        terrain_name="Qualification Terrain",
        wse=True,
        depth=True,
        velocity=False,
    )

    assert result["passed"] is True
    assert result["evidence"]["requested_map_types"] == ["wse", "depth"]
    assert result["evidence"]["child_checks"] == {
        "wse": True,
        "depth": True,
    }
    assert len(result["evidence"]["matched_plans"]) == 1
    assert result["evidence"]["matched_children"]["wse"][0][
        "map_parameters"
    ] == {
        "MapType": "elevation",
        "LayerName": "WSE",
        "Terrain": "Qualification Terrain",
        "ProfileIndex": "2147483647",
        "ProfileName": "Max",
        "ArrivalDepth": "0",
    }
    assert result["artifacts"]["rasmap"]["size"] > 0

    repeated = mapper_result_layers(
        context,
        plan_number="01",
        profile="Max",
        terrain_name="Qualification Terrain",
        wse=True,
        depth=True,
        velocity=False,
    )
    assert repeated["passed"] is True
    assert len(repeated["evidence"]["result_map_layers"]) == 2


def test_mapper_result_layers_rejects_noop_request(tmp_path):
    context = _context(tmp_path, "mapper.result_layers")
    project_folder = Path(context["project_folder"])
    (project_folder / "Action.p01.hdf").write_bytes(b"result fixture")

    with pytest.raises(ValueError, match="at least one result map type"):
        mapper_result_layers(
            context,
            plan_number="01",
            wse=False,
            depth=False,
            velocity=False,
        )


def test_plan_compute_unsteady_proves_declared_results_were_removed(
    tmp_path,
    monkeypatch,
):
    from ras_commander.ComputeResults import ComputeResult
    from ras_commander.RasCmdr import RasCmdr
    from ras_commander.RasPlan import RasPlan

    actions_module = importlib.import_module("ras_commander.RasQualificationActions")
    context = _context(tmp_path, "plan.compute_unsteady")
    project_folder = Path(context["project_folder"])
    plan_path = project_folder / "Action.p01"
    result_hdf = Path(str(plan_path) + ".hdf")
    stale_sidecar = project_folder / "Action.c01"
    result_hdf.write_bytes(b"stale result")
    stale_sidecar.write_bytes(b"stale sidecar")
    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        plan_df=pd.DataFrame({"plan_number": ["01"], "Geom File": ["g01"]}),
    )
    monkeypatch.setattr(actions_module, "_initialize", lambda _context: project)
    monkeypatch.setattr(
        RasPlan,
        "get_plan_path",
        staticmethod(lambda *_args, **_kwargs: plan_path),
    )

    def compute(*_args, **_kwargs):
        assert not result_hdf.exists()
        assert not stale_sidecar.exists()
        result_hdf.write_bytes(b"fresh result")
        return ComputeResult(success=True)

    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(compute))
    monkeypatch.setattr(
        RasQualification,
        "results_receipt",
        staticmethod(
            lambda path: {
                "file_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "successful": True,
                "max_abs_volume_error_percent": 0.1,
            }
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "extract_result_series",
        staticmethod(lambda *_args, **_kwargs: _result_series_fixture()),
    )

    result = plan_compute_unsteady(
        context,
        plan_number="01",
        series={"outflow": {}, "wse_cells": {}},
        fresh_result_files=["Action.p01.hdf", "Action.c01"],
        require_results_group_absent_before_compute=True,
    )

    assert result["passed"] is True
    freshness = result["evidence"]["fresh_compute"]
    assert freshness["passed"] is True
    assert all(item["existed"] for item in freshness["declared_outputs"])
    assert all(item["absent_after_removal"] for item in freshness["declared_outputs"])
    assert result["artifacts"]["results"]["file_sha256"] == hashlib.sha256(
        b"fresh result"
    ).hexdigest()


def test_plan_compute_unsteady_linux_uses_pinned_engine_and_preprocessed_inputs(
    tmp_path,
    monkeypatch,
):
    from ras_commander.ComputeResults import ComputeResult
    from ras_commander.RasCmdr import RasCmdr
    from ras_commander.RasPlan import RasPlan

    actions_module = importlib.import_module("ras_commander.RasQualificationActions")
    context = _context(tmp_path, "plan.compute_unsteady_linux")
    project_folder = Path(context["project_folder"])
    plan_path = project_folder / "Action.p01"
    result_hdf = Path(str(plan_path) + ".hdf")
    result_hdf.write_bytes(b"stale result")
    (project_folder / "Action.p01.tmp.hdf").write_bytes(b"preprocessed plan")
    (project_folder / "Action.b01").write_bytes(b"boundary")
    (project_folder / "Action.x01").write_bytes(b"geometry preprocessor")
    engine_root = tmp_path / "linux-engine"
    engine_root.mkdir()
    engine = engine_root / "RasUnsteady"
    engine.write_bytes(b"ELF fixture")
    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        plan_df=pd.DataFrame({"plan_number": ["01"], "Geom File": ["g01"]}),
    )
    monkeypatch.setattr(actions_module, "_initialize", lambda _context: project)
    monkeypatch.setattr(actions_module.os, "access", lambda *_args: True)
    monkeypatch.setattr(
        RasPlan,
        "get_plan_path",
        staticmethod(lambda *_args, **_kwargs: plan_path),
    )

    calls = []

    def compute(number, **kwargs):
        calls.append((number, kwargs))
        assert not result_hdf.exists()
        tmp_hdf = project_folder / "Action.p01.tmp.hdf"
        result_hdf.write_bytes(tmp_hdf.read_bytes() + b" solved")
        tmp_hdf.unlink()
        (project_folder / "compute_linux_01.log").write_text(
            " ABSDATE=13SEP2018\n"
            " ABSTIME=23:59:20\n"
            "Overall Volume Accounting Error as percentage: 0.0002\n"
            "Finished Unsteady Flow Simulation\n",
            encoding="utf-8",
        )
        return ComputeResult(success=True)

    monkeypatch.setattr(RasCmdr, "compute_plan_linux", staticmethod(compute))
    monkeypatch.setattr(
        RasQualification,
        "results_receipt",
        staticmethod(
            lambda path, **_kwargs: {
                "file_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "successful": True,
                "max_abs_volume_error_percent": 0.2,
            }
        ),
    )
    monkeypatch.setattr(
        RasQualification,
        "extract_result_series",
        staticmethod(lambda *_args, **_kwargs: _result_series_fixture()),
    )

    result = plan_compute_unsteady(
        context,
        execution_backend="linux_native",
        ras_exe_dir=engine_root,
        plan_number="01",
        num_cores=1,
        series={"outflow": {}, "wse_cells": {}},
        fresh_result_files=["Action.p01.hdf"],
        require_results_group_absent_before_compute=True,
    )

    assert result["passed"] is True
    assert result["evidence"]["native_solver_log"]["passed"] is True
    assert calls[0][0] == "01"
    assert calls[0][1]["ras_exe_dir"] == engine_root.resolve()
    assert result["evidence"]["engine"]["sha256"] == hashlib.sha256(
        b"ELF fixture"
    ).hexdigest()
    prerequisites = result["evidence"]["prerequisites"]
    assert prerequisites["plan_tmp_hdf"]["exists_after"] is False
    assert prerequisites["boundary"]["sha256_after"] == prerequisites["boundary"][
        "sha256_before"
    ]
    assert prerequisites["geometry_preprocessor"]["sha256_after"] == prerequisites[
        "geometry_preprocessor"
    ]["sha256_before"]


def test_restart_recovery_compares_baseline_hydrograph_wse_and_volume(
    tmp_path,
    monkeypatch,
):
    from ras_commander.RasCmdr import RasCmdr
    from ras_commander.RasPlan import RasPlan
    from ras_commander.RasUnsteady import RasUnsteady

    actions_module = importlib.import_module("ras_commander.RasQualificationActions")
    context = _context(tmp_path, "recovery.restart")
    project_folder = Path(context["project_folder"])
    baseline_plan = project_folder / "Action.p01"
    restart_plan = project_folder / "Action.p02"
    restart_plan.write_text(baseline_plan.read_text(encoding="utf-8"), encoding="utf-8")
    baseline_hdf = Path(str(baseline_plan) + ".hdf")
    restart_hdf = Path(str(restart_plan) + ".hdf")
    baseline_hdf.write_bytes(b"baseline results")
    restart_hdf.write_bytes(b"restart results")
    restart_unsteady = project_folder / "Action.u02"
    restart_unsteady.write_text("Flow Title=Restart\n", encoding="utf-8")
    restart_file = project_folder / "Action.restart.rst"
    restart_file.write_bytes(b"restart state")

    project = SimpleNamespace(
        project_folder=project_folder,
        project_name="Action",
        plan_df=pd.DataFrame(
            {
                "plan_number": ["01", "02"],
                "unsteady_number": ["01", "02"],
            }
        ),
    )
    monkeypatch.setattr(actions_module, "_initialize", lambda _context: project)
    monkeypatch.setattr(
        RasPlan,
        "get_plan_path",
        staticmethod(
            lambda number, ras_object=None: {
                "01": baseline_plan,
                "02": restart_plan,
            }[str(number)]
        ),
    )
    monkeypatch.setattr(
        RasPlan,
        "get_unsteady_path",
        staticmethod(lambda number, ras_object=None: restart_unsteady),
    )
    monkeypatch.setattr(
        RasUnsteady,
        "set_restart_settings",
        staticmethod(lambda *args, **kwargs: {"updated": True}),
    )
    monkeypatch.setattr(
        RasUnsteady,
        "get_restart_settings",
        staticmethod(lambda *args, **kwargs: {"use_restart": True}),
    )
    monkeypatch.setattr(
        RasCmdr,
        "compute_plan",
        staticmethod(lambda *args, **kwargs: True),
    )

    def result_receipt(path):
        path = Path(path)
        return {
            "path": str(path),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "successful": True,
            "max_abs_volume_error_percent": 0.1,
        }

    monkeypatch.setattr(
        RasQualification,
        "results_receipt",
        staticmethod(result_receipt),
    )
    series_records = {
        "outflow": {
            "kind": "profile_line_flow",
            "value_columns": ["flow"],
            "records": [
                {"time": "2026-01-01T01:00:00", "flow": 100.0},
                {"time": "2026-01-01T02:00:00", "flow": 125.0},
            ],
        },
        "wse_cells": {
            "kind": "mesh_cells",
            "variable": "Water Surface",
            "value_columns": ["wse"],
            "records": [
                {"time": "2026-01-01T01:00:00", "cell_id": 3, "wse": 101.0},
                {"time": "2026-01-01T02:00:00", "cell_id": 3, "wse": 101.5},
            ],
        },
    }
    monkeypatch.setattr(
        RasQualification,
        "extract_result_series",
        staticmethod(lambda *args, **kwargs: series_records),
    )
    specifications = {
        "outflow": {"kind": "profile_line_flow", "line_name": "Outlet"},
        "wse_cells": {
            "kind": "mesh_cells",
            "mesh_name": "MainArea",
            "variable": "Water Surface",
            "cell_ids": [3],
        },
    }
    tolerances = {
        "outflow": {
            "key_columns": ["time"],
            "columns": {"flow": {"max_abs": 0.1, "rmse": 0.1}},
        },
        "wse_cells": {
            "key_columns": ["time", "cell_id"],
            "columns": {"wse": {"max_abs": 0.01, "rmse": 0.01}},
        },
    }

    result = restart_recovery(
        context,
        restart_plan_number="02",
        baseline_plan_number="01",
        restart_filename=restart_file.name,
        series=specifications,
        series_tolerances=tolerances,
        max_volume_error_difference_percent=0.01,
    )
    assert result["passed"] is True
    assert result["evidence"]["volume_error_matches"] is True
    assert all(
        comparison["passed"]
        for comparison in result["evidence"]["series_comparisons"].values()
    )


def test_classification_actions_require_registration_and_geometry_association(
    tmp_path,
    monkeypatch,
):
    from ras_commander.RasMap import RasMap
    from ras_commander.geom import GeomMesh
    from ras_commander.hdf import HdfInfiltration, HdfLandCover

    context = _context(tmp_path, "properties.land_cover")
    project_folder = Path(context["project_folder"])
    landcover = project_folder / "Land Classification" / "LandCover.hdf"
    infiltration = project_folder / "Soils Data" / "Infiltration.hdf"
    landcover.parent.mkdir()
    infiltration.parent.mkdir()
    landcover.write_bytes(b"landcover")
    infiltration.write_bytes(b"infiltration")

    associations = {}

    def set_association(_geometry, **kwargs):
        for key in ("landcover_hdf_path", "infiltration_hdf_path"):
            if kwargs.get(key) is not None:
                associations[key] = str(kwargs[key])

    monkeypatch.setattr(
        GeomMesh,
        "set_geometry_association",
        staticmethod(set_association),
    )
    monkeypatch.setattr(
        GeomMesh,
        "get_geometry_association",
        staticmethod(lambda *args, **kwargs: dict(associations)),
    )
    monkeypatch.setattr(
        HdfLandCover,
        "get_landcover_raster_map",
        staticmethod(lambda _path: pd.DataFrame([{"class": "Developed", "n": 0.08}])),
    )
    monkeypatch.setattr(
        HdfInfiltration,
        "get_infiltration_layer_data",
        staticmethod(lambda _path: pd.DataFrame([{"class": "A", "curve_number": 70}])),
    )
    monkeypatch.setattr(
        HdfInfiltration,
        "get_infiltration_baseoverrides",
        staticmethod(lambda _path: pd.DataFrame()),
    )
    monkeypatch.setattr(
        RasMap,
        "list_landcover_layers",
        staticmethod(
            lambda *args, **kwargs: pd.DataFrame([{"resolved_path": str(landcover)}])
        ),
    )
    monkeypatch.setattr(
        RasMap,
        "list_infiltration_layers",
        staticmethod(
            lambda *args, **kwargs: pd.DataFrame([{"resolved_path": str(infiltration)}])
        ),
    )

    landcover_result = land_cover_properties(
        context,
        geometry="Action.g01",
        layer_hdf="Land Classification/LandCover.hdf",
    )
    assert landcover_result["passed"] is True
    assert landcover_result["evidence"]["registered_exactly"] is True
    assert landcover_result["evidence"]["associated_exactly"] is True

    context["operation_id"] = "properties.infiltration"
    infiltration_result = infiltration_properties(
        context,
        geometry="Action.g01",
        layer_hdf="Soils Data/Infiltration.hdf",
    )
    assert infiltration_result["passed"] is True
    assert infiltration_result["evidence"]["registered_exactly"] is True
    assert infiltration_result["evidence"]["associated_exactly"] is True


def test_project_locking_action_proves_contention_and_recovery(tmp_path):
    context = _context(tmp_path, "locking.project")
    result = project_locking(context)

    assert result["passed"] is True
    assert all(result["evidence"]["checks"].values())
    assert result["evidence"]["contention"]["return_code"] == 23
    assert result["evidence"]["contention"]["payload"]["error_type"] == "FileExistsError"
    assert result["evidence"]["recovery_process"]["return_code"] == 0
    assert not (Path(context["project_folder"]) / ".ras-commander-project.lock").exists()


def test_concurrency_action_proves_disjoint_task_writes_without_wineboot(tmp_path):
    source = _project(tmp_path / "immutable-source")
    template = tmp_path / "prepared-template"
    (template / "drive_c").mkdir(parents=True)
    (template / "drive_c" / "template.txt").write_text("immutable\n", encoding="utf-8")
    context = {
        "operation_id": "concurrency.prefix_isolation",
        "executor_profile": "unit_test",
        "source_project": str(source),
        "run_directory": str(tmp_path / "run"),
        "fixture": {"id": "concurrency-unit"},
    }

    result = concurrency_prefix_isolation(
        context,
        task_count=2,
        template_prefix=template,
        initialize_prefixes=False,
    )

    assert result["passed"] is True
    assert all(result["evidence"]["checks"].values())
    tasks = result["evidence"]["tasks"]
    assert len({item["prefix"]["prefix"] for item in tasks}) == 2
    assert len({item["project"]["destination"] for item in tasks}) == 2
    assert not (source / ".ras-qualification-task-write.json").exists()


def test_every_worker_required_operation_has_a_builtin_real_action():
    runner_builtins = {"installation.detect", "project.clone"}
    missing = set(RasQualification.REQUIRED_OPERATIONS) - runner_builtins - set(ACTION_HANDLERS)
    assert missing == set()
