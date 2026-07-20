"""Content-level tests for the HEC-RAS Windows/Wine qualification API."""

from __future__ import annotations

import copy
import importlib
import json
import os
import stat
import subprocess
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import (
    ExecutorProfile,
    NumericTolerance,
    RasQualification,
    RasUtils,
    RasterTolerance,
)
from ras_commander.RasPrj import get_ras_exe

qualification_module = importlib.import_module("ras_commander.RasQualification")


def _write_minimal_project(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "Fixture.prj").write_text(
        "Proj Title=Qualification Fixture\nCurrent Plan=p01\nPlan File=p01\n",
        encoding="utf-8",
    )
    (folder / "Fixture.p01").write_text(
        "Plan Title=Qualification\nProgram Version=7.01\nGeom File=g01\nFlow File=u01\n",
        encoding="utf-8",
    )
    (folder / "Fixture.g01").write_text("Geom Title=Qualification\n", encoding="utf-8")
    return folder


def test_results_receipt_rejects_complete_process_when_solver_reported_error(
    tmp_path,
    monkeypatch,
):
    from ras_commander.hdf import HdfResultsPlan

    plan_hdf = tmp_path / "Failure.p01.hdf"
    with h5py.File(plan_hdf, "w") as hdf:
        hdf.require_group("/Plan Data/Plan Information")
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_unsteady_summary",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame()),
    )
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_volume_accounting",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame()),
    )
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(
            lambda *_args, **_kwargs: (
                "Error with program: RasUnsteady.exe Exit Code = 3\n"
                "Complete Process\n"
            )
        ),
    )

    receipt = RasQualification.results_receipt(plan_hdf)

    assert receipt["successful"] is False
    assert receipt["compute_diagnostics"]["has_errors"] is True
    assert receipt["completion_checks"]["complete_process_present"] is True
    assert receipt["completion_checks"]["no_compute_errors"] is False
    assert receipt["completion_checks"]["unsteady_summary_present"] is False


def test_results_receipt_accepts_native_linux_structural_completion(
    tmp_path,
    monkeypatch,
):
    from ras_commander.hdf import HdfResultsPlan

    plan_hdf = tmp_path / "Native.p01.hdf"
    with h5py.File(plan_hdf, "w") as hdf:
        hdf.require_group("/Plan Data/Plan Information")
        hdf.require_group("/Results/Unsteady/Summary")
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_unsteady_summary",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame()),
    )
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_volume_accounting",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame()),
    )
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(lambda *_args, **_kwargs: ""),
    )

    windows = RasQualification.results_receipt(plan_hdf)
    native = RasQualification.results_receipt(
        plan_hdf,
        completion_mode="native_linux",
    )

    assert windows["successful"] is False
    assert native["successful"] is True
    assert native["completion_checks"]["complete_process_present"] is False
    assert native["completion_checks"]["accepted_completion_signal"] is True


def _write_geometry_hdf(path: Path) -> Path:
    area_dtype = np.dtype([("Name", "S32"), ("Cell Count", "<i4")])
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = "LOCAL_CS[\"Qualification\"]"
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Geometry Time"] = "16Jul2026 00:00:00"
        flow_areas = geometry.create_group("2D Flow Areas")
        flow_areas.create_dataset(
            "Attributes",
            data=np.array([(b"MainArea", 1)], dtype=area_dtype),
        )
        flow_areas.create_dataset(
            "Cell Info",
            data=np.array([[0, 5]], dtype=np.int32),
        )
        flow_areas.create_dataset(
            "Cell Points",
            data=np.array(
                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                dtype=np.float64,
            ),
        )
        area = flow_areas.create_group("MainArea")
        area.create_dataset(
            "Perimeter",
            data=np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], dtype=float),
        )
        area.create_dataset("Cells Center Coordinate", data=np.array([[0.5, 0.5]], dtype=float))
        area.create_dataset(
            "FacePoints Coordinate",
            data=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float),
        )
        area.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1], [1, 2], [2, 3], [3, 0]], dtype=np.int32),
        )
        area.create_dataset("Faces Perimeter Info", data=np.zeros((4, 2), dtype=np.int32))
        area.create_dataset("Faces Perimeter Values", data=np.empty((0, 2), dtype=float))
        area.create_dataset(
            "Cells Face and Orientation Info",
            data=np.array([[0, 4]], dtype=np.int32),
        )
        area.create_dataset(
            "Cells Face and Orientation Values",
            data=np.array([[0, 1], [1, 1], [2, 1], [3, 1]], dtype=np.int32),
        )
        area.create_dataset(
            "Cells FacePoint Indexes",
            data=np.array([[0, 1, 2, 3, -1, -1, -1, -1]], dtype=np.int32),
        )
        area.create_dataset(
            "FacePoints Cell Index Values",
            data=np.array([0, 0, 0, 0], dtype=np.int32),
        )
        area.create_dataset(
            "FacePoints Cell Info",
            data=np.array([[0, 1], [1, 1], [2, 1], [3, 1]], dtype=np.int32),
        )
        area.create_dataset(
            "FacePoints Face and Orientation Info",
            data=np.array([[0, 2], [2, 2], [4, 2], [6, 2]], dtype=np.int32),
        )
        area.create_dataset(
            "FacePoints Face and Orientation Values",
            data=np.array(
                [
                    [0, -1],
                    [3, 1],
                    [0, 1],
                    [1, -1],
                    [1, 1],
                    [2, -1],
                    [2, 1],
                    [3, -1],
                ],
                dtype=np.int32,
            ),
        )
        area.create_dataset(
            "FacePoints Is Perimeter",
            data=np.ones(4, dtype=np.int32),
        )
        area.create_dataset(
            "Faces Cell Indexes",
            data=np.array([[0, -1], [0, -1], [0, -1], [0, -1]], dtype=np.int32),
        )
        area.create_dataset(
            "Faces NormalUnitVector and Length",
            data=np.array(
                [[0, -1, 1], [1, 0, 1], [0, 1, 1], [-1, 0, 1]],
                dtype=np.float64,
            ),
        )
        area.create_dataset(
            "Faces Area Elevation Info",
            data=np.array([[0, 1], [1, 1], [2, 1], [3, 1]], dtype=np.int32),
        )
        area.create_dataset(
            "Faces Area Elevation Values",
            data=np.array(
                [
                    [0.0, 0.0, 1.0, 0.04],
                    [0.0, 0.0, 1.0, 0.04],
                    [0.0, 0.0, 1.0, 0.04],
                    [0.0, 0.0, 1.0, 0.04],
                ],
                dtype=float,
            ),
        )
        area.create_dataset("Cells Volume Elevation Info", data=np.array([[0, 2]], dtype=np.int32))
        area.create_dataset(
            "Cells Volume Elevation Values",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=float),
        )
    return path


def _complete_receipt(profile: ExecutorProfile) -> dict:
    not_applicable = RasQualification._PROFILE_NOT_APPLICABLE[profile.value]
    operations = []
    for operation_id in RasQualification.REQUIRED_OPERATIONS:
        if operation_id in not_applicable:
            operations.append({"id": operation_id, "status": "not_applicable"})
        else:
            evidence = {"artifact": f"{operation_id}.json"}
            if operation_id in {
                "mesh.generate_initial",
                "mesh.regenerate",
                "mesh.refinement_region",
                "mesh.breakline",
            }:
                evidence.update(
                    {
                        "expected_cell_count": 10,
                        "expected_face_count": 21,
                        (
                            "mesh_count_checks"
                            if operation_id == "mesh.breakline"
                            else "count_checks"
                        ): {"expected_cells": True, "expected_faces": True},
                    }
                )
            operations.append(
                {
                    "id": operation_id,
                    "status": "passed",
                    "evidence": evidence,
                }
            )
    architectures = {
        "ras": "x86",
        "rasprocess": "x86",
        "rasmapperlib": "x86",
        "ras_geom_preprocess": "x64",
        "ras_unsteady": "x64",
    }
    machine_codes = {"x86": "0x014c", "x64": "0x8664"}
    return {
        "schema_version": RasQualification.SCHEMA_VERSION,
        "executor_profile": profile.value,
        "installation": {
            "detected_version": "7.0.1",
            "version_matches": True,
            "required_components_present": True,
            "components": {
                name: {
                    "exists": True,
                    "sha256": character * 64,
                    "pe": {
                        "valid_pe": True,
                        "architecture": architectures[name],
                        "machine": machine_codes[architectures[name]],
                        "error": None,
                    },
                }
                for name, character in {
                    "ras": "a",
                    "rasprocess": "b",
                    "rasmapperlib": "c",
                    "ras_geom_preprocess": "d",
                    "ras_unsteady": "e",
                }.items()
            },
        },
        "fixture": {"id": "official-small-2d", "source_fingerprint": "fixture-sha"},
        "operations": operations,
        "artifacts": {
            "geometry": {
                "geometry_fingerprint": "geometry-sha",
                "areas": {
                    "MainArea": {
                        "cell_count": 10,
                        "face_count": 21,
                        "face_property_table_ids": 21,
                        "cell_property_table_ids": 10,
                        "face_property_complete": True,
                        "cell_property_complete": True,
                        "quality": {
                            "polygon_count": 10,
                            "invalid_cell_count": 0,
                            "cell_area": {"count": 10, "min": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0, "mean": 1.0},
                            "cell_aspect_ratio": {"count": 10, "min": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0, "mean": 1.0},
                            "face_length": {"count": 21, "min": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0, "mean": 1.0},
                        },
                    }
                },
                "boundary_assignments": [
                    {"name": "Downstream", "mesh_name": "MainArea", "type": "External", "bc_line_id": 0}
                ],
                "breakline_count": 1,
                "refinement_region_count": 1,
            },
            "terrain": {
                "data_fingerprint": "terrain-sha",
                "terrain_hdf_fingerprint": "terrain-hdf-sha",
                "layer_count": 1,
                "pyramid_levels": {"qualification": [0, 1]},
                "raster_inventory": [
                    {
                        "layer": "qualification",
                        "data_fingerprint": "terrain-raster-sha",
                        "crs_wkt": "EPSG:5070",
                        "width": 2,
                        "height": 2,
                    }
                ],
                "crs_wkt": "EPSG:5070",
                "width": 2,
                "height": 2,
                "band_count": 1,
                "transform": [1, 0, 0, 0, -1, 2],
            },
            "results": {
                "max_abs_volume_error_percent": 0.1,
                "successful": True,
            },
        },
        "series": {
            "outflow": {
                "kind": "profile_line_flow",
                "value_columns": ["flow"],
                "records": [
                    {"time": "2026-01-01T00:00:00", "flow": 1.0},
                    {"time": "2026-01-01T01:00:00", "flow": 2.0},
                ]
            },
            "wse_cells": {
                "kind": "mesh_cells",
                "variable": "Water Surface",
                "value_columns": ["wse"],
                "records": [
                    {"time": "2026-01-01T00:00:00", "cell_id": 4, "wse": 100.0},
                    {"time": "2026-01-01T01:00:00", "cell_id": 4, "wse": 101.0},
                ]
            }
        },
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6.60", "6.6"),
        ("7.01", "7.0.1"),
        ("7.0.1.0", "7.0.1"),
        ("6.4.0.1", "6.4.1"),
        ("5.0.0.7", "5.0.7"),
        ("701", "7.0.1"),
        ("66", "6.6"),
        ("6.7 Beta 5", "6.7 Beta 5"),
    ],
)
def test_normalize_ras_version_supports_release_and_legacy_forms(raw, expected):
    assert RasUtils.normalize_ras_version(raw) == expected


def test_get_ras_exe_resolves_701_and_66_without_cross_version_aliasing(monkeypatch):
    installs = {
        "7.0.1": Path("Z:/qualified/7.0.1/Ras.exe"),
        "6.6": Path("Z:/qualified/6.6/Ras.exe"),
    }
    monkeypatch.setattr(RasUtils, "discover_ras_versions", lambda: installs)

    assert get_ras_exe("7.01") == str(installs["7.0.1"])
    assert get_ras_exe("701") == str(installs["7.0.1"])
    assert get_ras_exe("6.60") == str(installs["6.6"])
    assert get_ras_exe("66") == str(installs["6.6"])


def test_receipt_scaffold_is_fail_closed_and_records_evidence():
    receipt = RasQualification.create_run_receipt(
        ExecutorProfile.WINDOWS_NATIVE,
        installation={"detected_version": "7.0.1"},
        fixture={"id": "small-2d", "source_fingerprint": "abc123"},
    )

    initial = RasQualification.validate_run_receipt(receipt)
    assert initial["passed"] is False
    assert "project.open" in initial["failed_operations"]
    assert "properties.geometry_tables" not in {
        item["id"] for item in receipt["operations"]
    }
    with pytest.raises(ValueError, match="requires content evidence"):
        RasQualification.record_operation(receipt, "project.open", "passed")
    with pytest.raises(ValueError, match="required for executor profile"):
        RasQualification.record_operation(receipt, "mesh.regenerate", "not_applicable")

    operation = RasQualification.record_operation(
        receipt,
        "project.open",
        "passed",
        evidence={"project_fingerprint": "def456"},
    )
    assert operation["evidence"]["project_fingerprint"] == "def456"

    diagnostic = RasQualification.record_operation(
        receipt,
        "properties.geometry_tables",
        "failed",
        diagnostics={"reason": "direct interop probe did not return"},
    )
    assert diagnostic["status"] == "failed"


def test_failed_geometry_table_diagnostic_does_not_fail_complete_receipt():
    receipt = _complete_receipt(ExecutorProfile.WINDOWS_NATIVE)
    RasQualification.record_operation(
        receipt,
        "properties.geometry_tables",
        "failed",
        diagnostics={"reason": "standalone call timed out"},
    )

    validation = RasQualification.validate_run_receipt(receipt)

    assert validation["passed"] is True
    assert validation["diagnostic_failures"] == ["properties.geometry_tables"]
    assert "properties.geometry_tables" not in validation["failed_operations"]


def test_json_value_serializes_compute_dataframe_and_series_content():
    frame = pd.DataFrame(
        {"plan": ["01"], "volume_error": [np.float64(0.25)]}
    )
    series = pd.Series({"success": np.bool_(True), "runtime": np.float64(1.5)})

    converted = qualification_module._json_value(
        {"results_df": frame, "results_row": series}
    )

    assert converted == {
        "results_df": [{"plan": "01", "volume_error": 0.25}],
        "results_row": {"success": True, "runtime": 1.5},
    }
    json.dumps(converted, allow_nan=False)


def test_canonical_hdf_fingerprint_ignores_volatile_time_but_not_content(tmp_path):
    first = tmp_path / "first.hdf"
    second = tmp_path / "second.hdf"
    for path, timestamp in [(first, "one"), (second, "two")]:
        with h5py.File(path, "w") as hdf:
            geometry = hdf.create_group("Geometry")
            geometry.attrs["Geometry Time"] = timestamp
            geometry.attrs["Stable"] = "same"
            geometry.create_dataset("Cells", data=np.array([[1.0, 2.0], [3.0, 4.0]]))

    assert RasQualification.canonical_hdf_fingerprint(first) == RasQualification.canonical_hdf_fingerprint(second)
    with h5py.File(second, "r+") as hdf:
        hdf["Geometry/Cells"][1, 1] = 5.0
    assert RasQualification.canonical_hdf_fingerprint(first) != RasQualification.canonical_hdf_fingerprint(second)


def test_terrain_semantic_fingerprint_ignores_guid_time_and_float_noise(tmp_path):
    first = tmp_path / "terrain-first.hdf"
    second = tmp_path / "terrain-second.hdf"
    values = [
        (first, "guid-one", "2026Jul18 11:08:48", 15.65261866142545),
        (second, "guid-two", "2026Jul18 11:17:17", 15.652618661421732),
    ]
    for path, guid, last_access, standard_deviation in values:
        with h5py.File(path, "w") as hdf:
            terrain = hdf.create_group("Terrain")
            terrain.attrs["GUID"] = guid
            layer = terrain.create_group("Layer")
            layer.attrs["File Last-Access"] = last_access
            level = layer.create_group("3")
            level.attrs["Standard Deviation"] = standard_deviation
            level.create_dataset("Values", data=np.array([1.0, 2.0, 3.0]))

    assert RasQualification.canonical_hdf_fingerprint(
        first, roots=("/Terrain",)
    ) != RasQualification.canonical_hdf_fingerprint(second, roots=("/Terrain",))
    assert RasQualification.terrain_hdf_semantic_fingerprint(
        first
    ) == RasQualification.terrain_hdf_semantic_fingerprint(second)


def test_terrain_receipt_captures_multisource_priorities_levels_and_stitch_data():
    pytest.importorskip("rasterio")
    terrain_hdf = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "example_projects"
        / "Muncie_geom_completion_bundled"
        / "Terrain"
        / "TerrainWithChannel.hdf"
    )
    if not terrain_hdf.is_file():
        pytest.skip("Bundled Muncie multi-source terrain is not tracked in this checkout")


    receipt = RasQualification.terrain_receipt(terrain_hdf)

    assert receipt["layer_count"] == 2
    assert receipt["layer_priorities"] == {
        "TerrainWithChannel.ChannelOnly": 0,
        "TerrainWithChannel.muncie_clip": 1,
    }
    assert receipt["pyramid_levels"] == {
        "TerrainWithChannel.ChannelOnly": [0, 1, 2, 3],
        "TerrainWithChannel.muncie_clip": [0, 1, 2, 3, 4, 5],
    }
    assert {
        item["layer"]: item["priority"]
        for item in receipt["raster_inventory"]
    } == receipt["layer_priorities"]
    assert {
        name: (item["shape"], item["count"])
        for name, item in receipt["stitch_datasets"].items()
    } == {
        "Stitch TIN Points": ([16754, 4], 16754),
        "Stitch TIN Triangles": ([16556, 3], 16556),
        "Stitches": ([41214, 7], 41214),
    }
    assert all(
        item["present"] and len(item["fingerprint"]) == 64
        for item in receipt["stitch_datasets"].values()
    )


def test_stage_project_preserves_content_and_exercises_spaces_and_long_paths(tmp_path):
    source = _write_minimal_project(tmp_path / "source")
    spaces = RasQualification.stage_project(source, tmp_path / "runs", "spaces", "spaces")
    long_path = RasQualification.stage_project(
        source,
        tmp_path / "runs",
        "long",
        "long",
        minimum_long_path=180,
    )

    assert spaces["content_matches"] is True
    assert " " in spaces["destination"]
    assert long_path["content_matches"] is True
    assert long_path["path_length"] >= 180
    assert (source / "Fixture.prj").read_text(encoding="utf-8").startswith("Proj Title=")


def test_project_lock_is_atomic_owner_checked_and_reacquirable(tmp_path):
    project = _write_minimal_project(tmp_path / "project")
    before = RasQualification.project_tree_fingerprint(project)

    first = RasQualification.acquire_project_lock(project, owner="worker-one")
    observed = RasQualification.inspect_project_lock(project)
    assert first["acquired"] is True
    assert RasQualification.project_tree_fingerprint(project) == before
    assert observed["token"] == first["token"]
    assert observed["file_sha256"] == first["file_sha256"]

    with pytest.raises(FileExistsError, match="already locked"):
        RasQualification.acquire_project_lock(project, owner="worker-two")

    wrong_owner = {**first, "token": "not-the-owner-token"}
    with pytest.raises(PermissionError, match="different token"):
        RasQualification.release_project_lock(wrong_owner)
    assert RasQualification.inspect_project_lock(project)["token"] == first["token"]

    released = RasQualification.release_project_lock(first)
    assert released["released"] is True
    assert released["exists_after_release"] is False
    assert RasQualification.inspect_project_lock(project) is None

    second = RasQualification.acquire_project_lock(project, owner="worker-two")
    assert second["token"] != first["token"]
    RasQualification.release_project_lock(second)
    assert RasQualification.project_tree_fingerprint(project) == before


def test_stage_project_excludes_transient_runner_lock(tmp_path):
    source = _write_minimal_project(tmp_path / "locked-source")
    source_fingerprint = RasQualification.project_tree_fingerprint(source)
    lock = RasQualification.acquire_project_lock(source, owner="staging-owner")

    stage = RasQualification.stage_project(source, tmp_path / "runs", "locked-copy")

    destination = Path(stage["destination"])
    assert stage["source_fingerprint"] == source_fingerprint
    assert stage["destination_fingerprint"] == source_fingerprint
    assert stage["transient_lock"]["source_present_during_stage"] is True
    assert stage["transient_lock"]["excluded"] is True
    assert not (destination / RasQualification.PROJECT_LOCK_NAME).exists()
    RasQualification.release_project_lock(lock)


def test_stage_project_makes_only_the_isolated_read_only_fixture_copy_writable(
    tmp_path,
):
    source = _write_minimal_project(tmp_path / "read-only-source")
    source_file = source / "Fixture.prj"
    original_source_mode = source.stat().st_mode
    original_file_mode = source_file.stat().st_mode
    source_file.chmod(original_file_mode & ~stat.S_IWUSR)
    source.chmod(original_source_mode & ~stat.S_IWUSR)

    try:
        stage = RasQualification.stage_project(
            source,
            tmp_path / "runs",
            "read-only-copy",
        )
        destination = Path(stage["destination"])
        destination_file = destination / source_file.name

        assert source.stat().st_mode & stat.S_IWUSR == 0
        assert source_file.stat().st_mode & stat.S_IWUSR == 0
        assert destination.stat().st_mode & stat.S_IWUSR
        assert destination_file.stat().st_mode & stat.S_IWUSR
        assert stage["writable_clone"] == {
            "normalized": True,
            "owner_write_verified": True,
            "directory_count": 1,
            "file_count": 3,
            "source_permissions_unchanged": True,
        }

        lock = RasQualification.acquire_project_lock(
            destination,
            owner="read-only-fixture-regression",
        )
        RasQualification.release_project_lock(lock)
    finally:
        source.chmod(original_source_mode | stat.S_IWUSR)
        source_file.chmod(original_file_mode | stat.S_IWUSR)


def test_stage_project_uses_mapped_drive_safe_resolution(tmp_path, monkeypatch):
    source = _write_minimal_project(tmp_path / "source")
    workspace = tmp_path / "workspace"
    resolved = []

    def safe_resolve(path):
        resolved.append(Path(path))
        return Path(path).absolute()

    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(safe_resolve))
    stage = RasQualification.stage_project(source, workspace, task_id="mapped-drive")

    assert resolved == [source, workspace]
    assert Path(stage["destination"]).drive == Path(workspace.absolute()).drive
    assert stage["content_matches"] is True


def test_create_isolated_wine_prefix_uses_unique_win64_prefixes(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "initialized", "")

    monkeypatch.setattr(qualification_module.subprocess, "run", fake_run)
    first = RasQualification.create_isolated_wine_prefix(tmp_path, "array-17")
    second = RasQualification.create_isolated_wine_prefix(tmp_path, "array-17")

    assert first["initialized"] is True
    assert first["prefix"] != second["prefix"]
    assert calls[0][1]["env"]["WINEPREFIX"] == first["prefix"]
    assert calls[0][1]["env"]["WINEARCH"] == "win64"
    assert json.loads((Path(first["prefix"]) / ".ras-commander-prefix.json").read_text())["task_id"] == "array-17"


def test_create_isolated_wine_prefix_clones_immutable_template_before_update(tmp_path, monkeypatch):
    template = tmp_path / "template-prefix"
    (template / "drive_c" / "Python311").mkdir(parents=True)
    (template / "drive_c" / "Python311" / "python.exe").write_bytes(b"windows-python")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "updated", "")

    monkeypatch.setattr(qualification_module.subprocess, "run", fake_run)
    receipt = RasQualification.create_isolated_wine_prefix(
        tmp_path / "prefixes",
        task_id="job-1",
        template_prefix=template,
        wineboot_dll_overrides="winemenubuilder.exe=d",
    )

    prefix = Path(receipt["prefix"])
    assert prefix != template
    assert (prefix / "drive_c" / "Python311" / "python.exe").read_bytes() == b"windows-python"
    assert receipt["template_fingerprint"] == RasQualification.project_tree_fingerprint(template)
    assert receipt["wineboot_dll_overrides"] == "winemenubuilder.exe=d"
    assert calls[0][1]["env"]["WINEDLLOVERRIDES"] == "winemenubuilder.exe=d"
    assert calls[0][0][-1] == "--update"


def test_create_isolated_wine_prefix_uses_prepared_template_without_wineboot(tmp_path, monkeypatch):
    template = tmp_path / "prepared-template"
    (template / "drive_c").mkdir(parents=True)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("wineboot must not run for a prepared template clone")

    monkeypatch.setattr(qualification_module.subprocess, "run", unexpected_run)
    receipt = RasQualification.create_isolated_wine_prefix(
        tmp_path / "prefixes",
        task_id="job-2",
        template_prefix=template,
        initialize=False,
    )

    assert receipt["initialized"] is True
    assert receipt["initialization_requested"] is False
    assert receipt["initialization_mode"] == "prepared_template_clone"
    assert (Path(receipt["prefix"]) / ".ras-commander-prefix.json").is_file()


def test_inspect_installation_requires_exact_version_and_components(tmp_path, monkeypatch):
    install = tmp_path / "HEC-RAS" / "7.0"
    (install / "x64").mkdir(parents=True)
    for relative in [
        "Ras.exe",
        "RasProcess.exe",
        "RasMapperLib.dll",
        "x64/RasGeomPreprocess.exe",
        "x64/RasUnsteady.exe",
    ]:
        (install / relative).write_bytes(relative.encode("ascii"))

    monkeypatch.setattr(
        RasUtils,
        "get_executable_version",
        staticmethod(
            lambda _path: {
                "file_version": "7.0.1.0",
                "product_version": "7.0.1.0",
                "normalized_version": "7.0.1",
                "source": "test",
            }
        ),
    )
    receipt = RasQualification.inspect_installation(install)

    assert receipt["version_matches"] is True
    assert receipt["required_components_present"] is True
    assert all(component["sha256"] for component in receipt["components"].values())


def test_inspect_python_packages_requires_one_exact_distribution(tmp_path):
    site_packages = tmp_path / "Lib" / "site-packages"
    pythonnet = site_packages / "pythonnet-3.0.5.dist-info" / "METADATA"
    clr_loader = site_packages / "clr_loader-0.2.10.dist-info" / "METADATA"
    pythonnet.parent.mkdir(parents=True)
    clr_loader.parent.mkdir(parents=True)
    pythonnet.write_text("Name: pythonnet\nVersion: 3.0.5\n", encoding="utf-8")
    clr_loader.write_text("Name: clr-loader\nVersion: 0.2.10\n", encoding="utf-8")

    report = RasQualification.inspect_python_packages(
        site_packages,
        {"pythonnet": "3.0.5", "clr_loader": "0.2.10"},
    )

    assert report["all_match"] is True
    assert report["checks"]["pythonnet"]["matches"] is True
    assert report["checks"]["clr_loader"]["installed"][0]["version"] == "0.2.10"

    mismatched = RasQualification.inspect_python_packages(
        site_packages,
        {"pythonnet": "3.1.0"},
    )
    assert mismatched["all_match"] is False


@pytest.mark.skipif(os.name == "nt", reason="Exercises the Linux pefile reader")
def test_executable_version_reports_malformed_pe_without_crashing(tmp_path):
    pytest.importorskip("pefile")
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"not-a-portable-executable")

    result = RasUtils.get_executable_version(executable)

    assert result["source"] is None
    assert result["normalized_version"] is None
    assert result["valid_pe"] is False
    assert "PEFormatError" in result["error"]


def test_pe_architecture_reads_machine_type_without_execution(tmp_path):
    executable = tmp_path / "compute.exe"
    header = bytearray(70)
    header[:2] = b"MZ"
    header[0x3C:0x40] = (64).to_bytes(4, "little")
    header[64:68] = b"PE\x00\x00"
    header[68:70] = (0x8664).to_bytes(2, "little")
    executable.write_bytes(header)

    result = RasUtils.get_pe_architecture(executable)

    assert result == {
        "valid_pe": True,
        "machine": "0x8664",
        "architecture": "x64",
        "error": None,
    }


def test_geometry_receipt_checks_counts_properties_and_quality(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path / "fixture.g01.hdf")
    receipt = RasQualification.geometry_receipt(hdf_path)

    assert receipt["mesh_area_count"] == 1
    assert receipt["areas"]["MainArea"]["cell_count"] == 1
    assert receipt["areas"]["MainArea"]["face_count"] == 4
    assert receipt["areas"]["MainArea"]["face_property_complete"] is True
    assert receipt["areas"]["MainArea"]["cell_property_complete"] is True
    assert receipt["areas"]["MainArea"]["quality"]["invalid_cell_count"] == 0
    topology = receipt["areas"]["MainArea"]["mesh_topology"]
    assert topology["complete"] is True
    assert topology["declared_cell_count"] == 1
    assert topology["face_count"] == topology["persisted_face_count"] == 4
    assert len(topology["fingerprint"]) == 64
    assert len(topology["components"]["ordered_nonvirtual_centers"]["fingerprint"]) == 64
    assert len(topology["components"]["ordered_faces_and_indexes"]["fingerprint"]) == 64
    assert topology["datasets"]["Faces Cell Indexes"]["dtype"]["str"] == "<i4"
    assert topology["datasets"]["Faces Cell Indexes"]["shape"] == [4, 2]


def test_geometry_receipt_uses_declared_cell_count_not_hdf_capacity_rows(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path / "capacity.g01.hdf")
    before = RasQualification.geometry_receipt(hdf_path, include_quality=False)
    with h5py.File(hdf_path, "r+") as hdf:
        area = hdf["Geometry/2D Flow Areas/MainArea"]
        del area["Cells Center Coordinate"]
        area.create_dataset(
            "Cells Center Coordinate",
            data=np.array([[0.5, 0.5], [999.0, 999.0]], dtype=float),
        )

    receipt = RasQualification.geometry_receipt(hdf_path, include_quality=False)
    area = receipt["areas"]["MainArea"]

    assert area["cell_count"] == 1
    assert area["cell_center_storage_rows"] == 2
    assert area["cell_storage_has_capacity_rows"] is True
    before_topology = before["areas"]["MainArea"]["mesh_topology"]
    after_topology = area["mesh_topology"]
    assert after_topology["fingerprint"] != before_topology["fingerprint"]
    assert (
        after_topology["components"]["ordered_nonvirtual_centers"]["fingerprint"]
        == before_topology["components"]["ordered_nonvirtual_centers"]["fingerprint"]
    )


def test_mesh_topology_fingerprint_excludes_properties_and_unrelated_geometry(tmp_path):
    first_path = _write_geometry_hdf(tmp_path / "first.g01.hdf")
    second_path = _write_geometry_hdf(tmp_path / "second.g01.hdf")
    with h5py.File(second_path, "r+") as hdf:
        hdf["Geometry"].attrs["Geometry Time"] = "19Jul2026 12:34:56"
        hdf["Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values"][0, 3] = 0.09
        unrelated = hdf["Geometry"].create_group("Unrelated Qualification Data")
        unrelated.create_dataset("Values", data=np.array([7, 8, 9], dtype=np.int16))

    first = RasQualification.geometry_receipt(first_path, include_quality=False)
    second = RasQualification.geometry_receipt(second_path, include_quality=False)
    first_topology = first["areas"]["MainArea"]["mesh_topology"]
    second_topology = second["areas"]["MainArea"]["mesh_topology"]

    assert first["geometry_fingerprint"] != second["geometry_fingerprint"]
    assert first_topology["fingerprint"] == second_topology["fingerprint"]
    assert first_topology["datasets"] == second_topology["datasets"]


def test_mesh_topology_component_fingerprints_localize_center_and_face_changes(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path / "components.g01.hdf")
    before = RasQualification.geometry_receipt(hdf_path, include_quality=False)["areas"][
        "MainArea"
    ]["mesh_topology"]

    with h5py.File(hdf_path, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/MainArea/Cells Center Coordinate"][0, 0] += 0.125
    after_center = RasQualification.geometry_receipt(
        hdf_path, include_quality=False
    )["areas"]["MainArea"]["mesh_topology"]

    assert after_center["fingerprint"] != before["fingerprint"]
    assert (
        after_center["components"]["ordered_nonvirtual_centers"]["fingerprint"]
        != before["components"]["ordered_nonvirtual_centers"]["fingerprint"]
    )
    assert (
        after_center["components"]["ordered_faces_and_indexes"]["fingerprint"]
        == before["components"]["ordered_faces_and_indexes"]["fingerprint"]
    )

    with h5py.File(hdf_path, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/MainArea/Faces Cell Indexes"][0, 1] = -2
    after_face = RasQualification.geometry_receipt(
        hdf_path, include_quality=False
    )["areas"]["MainArea"]["mesh_topology"]

    assert (
        after_face["components"]["ordered_nonvirtual_centers"]["fingerprint"]
        == after_center["components"]["ordered_nonvirtual_centers"]["fingerprint"]
    )
    assert (
        after_face["components"]["ordered_faces_and_indexes"]["fingerprint"]
        != after_center["components"]["ordered_faces_and_indexes"]["fingerprint"]
    )


def test_mesh_topology_fingerprint_preserves_dataset_dtype_and_marks_missing(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path / "dtype.g01.hdf")
    before = RasQualification.geometry_receipt(hdf_path, include_quality=False)["areas"][
        "MainArea"
    ]["mesh_topology"]
    normals_path = "Geometry/2D Flow Areas/MainArea/Faces NormalUnitVector and Length"
    with h5py.File(hdf_path, "r+") as hdf:
        values = hdf[normals_path][()].astype(np.float32)
        del hdf[normals_path]
        hdf.create_dataset(normals_path, data=values)

    changed_dtype = RasQualification.geometry_receipt(
        hdf_path, include_quality=False
    )["areas"]["MainArea"]["mesh_topology"]
    assert changed_dtype["complete"] is True
    assert changed_dtype["fingerprint"] != before["fingerprint"]
    assert changed_dtype["datasets"]["Faces NormalUnitVector and Length"]["dtype"]["str"] == "<f4"

    with h5py.File(hdf_path, "r+") as hdf:
        del hdf[normals_path]
    incomplete = RasQualification.geometry_receipt(
        hdf_path, include_quality=False
    )["areas"]["MainArea"]["mesh_topology"]

    assert incomplete["complete"] is False
    assert incomplete["fingerprint"] is None
    assert f"/{normals_path}" in incomplete["missing_datasets"]
    assert incomplete["components"]["ordered_faces_and_indexes"]["fingerprint"] is None
    assert incomplete["components"]["ordered_nonvirtual_centers"]["fingerprint"]


def test_geometry_receipt_reads_refinement_regions_from_geometry_hdf(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path / "refinement.g01.hdf")
    with h5py.File(hdf_path, "r+") as hdf:
        group = hdf["Geometry"].create_group("2D Flow Area Refinement Regions")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(b"Channel", np.float32(25), np.float32(25))],
                dtype=np.dtype(
                    [("Name", "S32"), ("Spacing dx", "<f4"), ("Spacing dy", "<f4")]
                ),
            ),
        )
        group.create_dataset("Polygon Info", data=np.array([[0, 5, 0, 1]], dtype=np.int32))
        group.create_dataset("Polygon Parts", data=np.array([[0, 5]], dtype=np.int32))
        group.create_dataset(
            "Polygon Points",
            data=np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], dtype=float),
        )

    receipt = RasQualification.geometry_receipt(hdf_path, include_quality=False)

    assert receipt["refinement_region_count"] == 1
    assert len(receipt["geometry_fingerprint"]) == 64


@pytest.mark.slow
def test_terrain_receipt_fingerprints_example_output_raster_and_pyramids(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    try:
        from ras_commander import RasExamples

        project = RasExamples.extract_project(
            "Weise_2D",
            output_path=tmp_path,
            suffix="terrain_receipt",
        )
    except Exception as exc:
        pytest.skip(f"Weise_2D example not available: {exc}")

    terrain_hdfs = sorted(Path(project).rglob("Terrain_With_Walls_0p01m.hdf"))
    if not terrain_hdfs:
        pytest.skip("Weise_2D terrain fixture not present in the example archive")
    terrain_hdf = terrain_hdfs[0]

    before = RasQualification.terrain_receipt(terrain_hdf)
    assert before["source_rasters"] == []
    assert before["layer_count"] == 1
    assert before["pyramid_levels"]
    assert before["raster_inventory"][0]["path"].endswith(".tif")
    assert before["data_fingerprint"] != before["terrain_hdf_fingerprint"]

    output_raster = Path(before["raster_inventory"][0]["path"])
    with rasterio.open(output_raster, "r+") as dataset:
        values = dataset.read(1)
        values[0, 0] = values[0, 0] + 0.125
        dataset.write(values, 1)

    after = RasQualification.terrain_receipt(terrain_hdf)
    assert after["terrain_hdf_fingerprint"] == before["terrain_hdf_fingerprint"]
    assert after["raster_inventory"][0]["data_fingerprint"] != before["raster_inventory"][0]["data_fingerprint"]
    assert after["data_fingerprint"] != before["data_fingerprint"]


def test_extract_result_series_requires_explicit_hydrograph_and_wse_locations(
    tmp_path,
    monkeypatch,
):
    import xarray as xr

    from ras_commander.hdf import HdfResultsMesh

    plan_hdf = tmp_path / "Qualification.p01.hdf"
    plan_hdf.write_bytes(b"fixture")
    times = pd.to_datetime(["2026-01-01T00:00:00", "2026-01-01T01:00:00"])
    hydrograph = pd.DataFrame(
        {
            "time": times,
            "flow": [10.0, 12.5],
            "line_name": ["Outlet", "Outlet"],
        }
    )
    hydrograph.attrs["units"] = "cfs"
    mesh_wse = xr.DataArray(
        np.array([[100.0, 101.0, 102.0], [100.5, 101.5, 102.5]]),
        dims=["time", "cell_id"],
        coords={"time": times, "cell_id": [0, 1, 2]},
        attrs={"units": "ft"},
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_profile_line_flow_timeseries",
        lambda *args, **kwargs: hydrograph,
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_mesh_timeseries",
        lambda *args, **kwargs: mesh_wse,
    )

    series = RasQualification.extract_result_series(
        plan_hdf,
        {
            "outflow": {
                "kind": "profile_line_flow",
                "line_name": "Outlet",
                "mesh_name": "Qualification Area",
                "start_time": "2026-01-01T01:00:00",
            },
            "wse_cells": {
                "kind": "mesh_cells",
                "mesh_name": "Qualification Area",
                "variable": "Water Surface",
                "cell_ids": [0, 2],
                "start_time": "2026-01-01T01:00:00",
            },
        },
    )

    assert series["outflow"]["kind"] == "profile_line_flow"
    assert series["outflow"]["records"] == [
        {
            "time": "2026-01-01T01:00:00",
            "flow": 12.5,
            "line_name": "Outlet",
        }
    ]
    assert series["wse_cells"]["entity_ids"] == [0, 2]
    assert len(series["wse_cells"]["records"]) == 2
    assert {record["cell_id"] for record in series["wse_cells"]["records"]} == {0, 2}

    with pytest.raises(ValueError, match="missing cell_ids"):
        RasQualification.extract_result_series(
            plan_hdf,
            {
                "wse_cells": {
                    "kind": "mesh_cells",
                    "mesh_name": "Qualification Area",
                    "variable": "Water Surface",
                    "cell_ids": [99],
                }
            },
        )


def test_extract_result_series_supports_native_pure_python_hdf_backend(
    tmp_path,
    monkeypatch,
):
    from ras_commander.hdf import HdfResultsMesh

    plan_hdf = tmp_path / "Qualification.p01.hdf"
    plan_hdf.write_bytes(b"fixture")
    hydrograph = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2026-01-01T00:00:00", "2026-01-01T01:00:00"]
            ),
            "flow": [10.0, 12.0],
        }
    )
    calls = []
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_profile_line_flow_timeseries_legacy",
        lambda *args, **kwargs: calls.append((args, kwargs)) or hydrograph,
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_profile_line_flow_timeseries",
        lambda *_args, **_kwargs: pytest.fail("RasMapper backend must not be used"),
    )

    series = RasQualification.extract_result_series(
        plan_hdf,
        {
            "outflow": {
                "kind": "profile_line_flow",
                "line_name": "Outlet",
                "mesh_name": "Qualification Area",
                "direction": "signed",
                "extraction_backend": "hdf",
            }
        },
    )

    assert calls
    assert series["outflow"]["extraction_backend"] == "pure_python_hdf"
    assert [record["flow"] for record in series["outflow"]["records"]] == [
        10.0,
        12.0,
    ]


def test_compare_numeric_frames_checks_keys_nan_peak_max_and_rmse():
    native = pd.DataFrame(
        {"time": [0, 1, 2], "flow": [0.0, 10.0, 5.0], "wse": [100.0, 101.0, 100.5]}
    )
    wine = pd.DataFrame(
        {"time": [0, 1, 2], "flow": [0.0, 10.1, 5.0], "wse": [100.0, 101.01, 100.5]}
    )
    result = RasQualification.compare_numeric_frames(
        native,
        wine,
        key_columns=["time"],
        tolerances={
            "flow": NumericTolerance(max_abs=0.2, rmse=0.1, peak_relative=0.02),
            "wse": NumericTolerance(max_abs=0.02, rmse=0.01),
        },
    )

    assert result["passed"] is True
    assert result["keys_match"] is True
    assert result["columns"]["flow"]["max_abs"] == pytest.approx(0.1)


def test_compare_numeric_frames_fails_on_key_or_tolerance_difference():
    native = pd.DataFrame({"time": [0, 1], "wse": [100.0, 101.0]})
    wine = pd.DataFrame({"time": [0, 2], "wse": [100.0, 101.5]})
    result = RasQualification.compare_numeric_frames(
        native,
        wine,
        key_columns=["time"],
        tolerances={"wse": NumericTolerance(max_abs=0.1, rmse=0.1)},
    )
    assert result["passed"] is False
    assert result["keys_match"] is False


def test_compare_compute_receipts_checks_volume_metadata_keys_and_values():
    reference = {
        "artifacts": {
            "results": {
                "successful": True,
                "file_sha256": "a" * 64,
                "max_abs_volume_error_percent": 0.0004,
            }
        },
        "series": {
            "outflow": {
                "kind": "profile_line_flow",
                "mesh_name": "MainArea",
                "line_name": "Downstream",
                "direction": "signed",
                "units": "cfs",
                "value_columns": ["flow"],
                "records": [
                    {"time": "00:00", "flow": 10.0},
                    {"time": "00:01", "flow": 12.0},
                ],
            }
        },
    }
    candidate = copy.deepcopy(reference)
    candidate["artifacts"]["results"].update(
        {
            "file_sha256": "b" * 64,
            "max_abs_volume_error_percent": 0.00041,
        }
    )
    candidate["series"]["outflow"]["records"][1]["flow"] = 12.0001
    tolerances = {
        "volume_accounting": {
            "max_abs_error_percent": 0.01,
            "max_abs_difference_percent": 0.0001,
        },
        "series": {
            "outflow": {
                "key_columns": ["time"],
                "columns": {
                    "flow": {
                        "max_abs": 0.001,
                        "rmse": 0.001,
                        "peak_relative": 0.0001,
                    }
                },
            }
        },
    }

    result = RasQualification.compare_compute_receipts(
        reference,
        candidate,
        tolerances,
    )

    assert result["passed"] is True
    assert result["volume_accounting"]["passed"] is True
    assert result["series"]["outflow"]["metadata_exact"] is True
    assert result["series"]["outflow"]["numeric"]["keys_match"] is True
    assert result["series"]["outflow"]["reference_records_sha256"] != (
        result["series"]["outflow"]["candidate_records_sha256"]
    )

    candidate["series"]["outflow"]["units"] = "cms"
    failed = RasQualification.compare_compute_receipts(
        reference,
        candidate,
        tolerances,
    )
    assert failed["passed"] is False
    assert failed["series"]["outflow"]["metadata_exact"] is False


def test_validate_run_receipt_rejects_critical_skip_and_missing_evidence():
    receipt = _complete_receipt(ExecutorProfile.LINUX_WINE_WINDOWS_RAS)
    assert RasQualification.validate_run_receipt(receipt)["passed"] is True

    skipped = copy.deepcopy(receipt)
    operation = next(item for item in skipped["operations"] if item["id"] == "mesh.regenerate")
    operation["status"] = "skipped"
    operation.pop("evidence")
    validation = RasQualification.validate_run_receipt(skipped)
    assert validation["passed"] is False
    assert validation["skipped_critical_operations"] == ["mesh.regenerate"]

    no_evidence = copy.deepcopy(receipt)
    operation = next(item for item in no_evidence["operations"] if item["id"] == "terrain.associate")
    operation["evidence"] = {}
    validation = RasQualification.validate_run_receipt(no_evidence)
    assert "terrain.associate" in validation["missing_operation_evidence"]

    no_mesh_golden = copy.deepcopy(receipt)
    operation = next(
        item
        for item in no_mesh_golden["operations"]
        if item["id"] == "mesh.refinement_region"
    )
    operation["evidence"]["expected_cell_count"] = None
    validation = RasQualification.validate_run_receipt(no_mesh_golden)
    assert validation["passed"] is False
    assert validation["checks"]["mesh_exact_counts_configured"] is False
    assert validation["mesh_exact_count_checks"]["mesh.refinement_region"] is False

    malformed = copy.deepcopy(receipt)
    malformed["installation"]["components"]["ras"] = "not component evidence"
    validation = RasQualification.validate_run_receipt(malformed)
    assert validation["passed"] is False
    assert validation["checks"]["component_identity_present"] is False

    wrong_architecture = copy.deepcopy(receipt)
    wrong_architecture["installation"]["components"]["ras_unsteady"]["pe"][
        "architecture"
    ] = "x86"
    validation = RasQualification.validate_run_receipt(wrong_architecture)
    assert validation["passed"] is False
    assert validation["checks"]["component_architecture_valid"] is False

    missing_wse = copy.deepcopy(receipt)
    del missing_wse["series"]["wse_cells"]
    validation = RasQualification.validate_run_receipt(missing_wse)
    assert validation["passed"] is False
    assert validation["checks"]["hydrograph_wse_series_present"] is False


def _write_raster(path: Path, values: np.ndarray, *, transform=None) -> Path:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    if transform is None:
        transform = from_origin(0, values.shape[0], 1, 1)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:5070",
        transform=transform,
        nodata=-9999.0,
    ) as target:
        target.write(values.astype(np.float32), 1)
    return path


def test_depth_raster_comparison_checks_overlap_and_values(tmp_path):
    native = _write_raster(tmp_path / "native.tif", np.array([[0.0, 1.0], [2.0, 3.0]]))
    wine = _write_raster(tmp_path / "wine.tif", np.array([[0.0, 1.05], [2.0, 3.0]]))
    result = RasQualification.compare_depth_rasters(
        native,
        wine,
        RasterTolerance(max_abs=0.1, rmse=0.05, minimum_wet_overlap=1.0),
    )

    assert result["passed"] is True
    assert result["wet_overlap"] == 1.0
    assert result["max_abs"] == pytest.approx(0.05, abs=1e-6)
    assert result["wet_max_abs"] == pytest.approx(0.05, abs=1e-6)
    assert result["wet_rmse"] == pytest.approx(0.05 / np.sqrt(3), abs=1e-6)


def test_depth_raster_comparison_rejects_all_dry_grids(tmp_path):
    values = np.zeros((2, 2), dtype=float)
    native = _write_raster(tmp_path / "native-dry.tif", values)
    wine = _write_raster(tmp_path / "wine-dry.tif", values)

    result = RasQualification.compare_depth_rasters(
        native,
        wine,
        RasterTolerance(max_abs=0.0, rmse=0.0, minimum_wet_overlap=0.0),
    )

    assert result["passed"] is False
    assert result["wet_union_count"] == 0
    assert result["wet_overlap"] is None
    assert result["wet_max_abs"] is None
    assert result["wet_rmse"] is None


def test_depth_raster_comparison_rejects_nodata_only_grids(tmp_path):
    values = np.full((2, 2), -9999.0, dtype=float)
    native = _write_raster(tmp_path / "native-nodata.tif", values)
    wine = _write_raster(tmp_path / "wine-nodata.tif", values)

    result = RasQualification.compare_depth_rasters(
        native,
        wine,
        RasterTolerance(max_abs=0.0, rmse=0.0, minimum_wet_overlap=0.0),
    )

    assert result["passed"] is False
    assert result["comparable_count"] == 0
    assert result["wet_union_count"] == 0
    assert result["wet_overlap"] is None


def test_depth_raster_comparison_checks_sparse_wet_error_separately(tmp_path):
    native_values = np.zeros((10, 10), dtype=float)
    wine_values = np.zeros((10, 10), dtype=float)
    native_values[0, 0] = 1.0
    wine_values[0, 0] = 2.0
    native = _write_raster(tmp_path / "native-sparse.tif", native_values)
    wine = _write_raster(tmp_path / "wine-sparse.tif", wine_values)

    result = RasQualification.compare_depth_rasters(
        native,
        wine,
        RasterTolerance(max_abs=1.0, rmse=0.2, minimum_wet_overlap=1.0),
    )

    assert result["rmse"] == pytest.approx(0.1)
    assert result["wet_rmse"] == pytest.approx(1.0)
    assert result["wet_comparable_count"] == result["wet_union_count"] == 1
    assert result["passed"] is False


def test_depth_raster_comparison_aligns_shifted_grids(tmp_path):
    from rasterio.transform import from_origin

    native_values = np.array([[0.0, 1.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 0.0]])
    wine_values = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 2.0], [0.0, 0.0, 0.0]])
    native = _write_raster(
        tmp_path / "native-shifted.tif",
        native_values,
        transform=from_origin(0, 3, 1, 1),
    )
    wine = _write_raster(
        tmp_path / "wine-shifted.tif",
        wine_values,
        transform=from_origin(-1, 3, 1, 1),
    )

    result = RasQualification.compare_depth_rasters(
        native,
        wine,
        RasterTolerance(max_abs=0.0, rmse=0.0, minimum_wet_overlap=1.0),
    )

    assert result["same_grid"] is False
    assert result["wet_overlap"] == 1.0
    assert result["wet_rmse"] == 0.0
    assert result["passed"] is True


def test_map_raster_comparison_uses_exact_first_then_explicit_tolerance(tmp_path):
    native = _write_raster(
        tmp_path / "native" / "Velocity Max.tif",
        np.array([[0.0, 1.0], [2.0, 3.0]]),
    )
    exact_wine = _write_raster(
        tmp_path / "wine-exact" / "Velocity Max.tif",
        np.array([[0.0, 1.0], [2.0, 3.0]]),
    )
    limits = RasterTolerance(
        max_abs=0.05,
        rmse=0.03,
        minimum_wet_overlap=1.0,
        minimum_valid_overlap=1.0,
    )

    exact = RasQualification.compare_rasters(native, exact_wine, limits)

    assert exact["passed"] is True
    assert exact["comparison_mode"] == "exact"
    assert exact["exact_match"] is True
    assert exact["dimensions_exact"] is True
    assert exact["crs_exact"] is True
    assert exact["transform_exact"] is True
    assert exact["native_crs_wkt"] == exact["wine_crs_wkt"]
    assert exact["native_transform"] == exact["wine_transform"]
    assert exact["valid_mask_exact"] is True
    assert exact["values_exact"] is True

    tolerant_wine = _write_raster(
        tmp_path / "wine-tolerant" / "Velocity Max.tif",
        np.array([[0.0, 1.02], [2.0, 3.0]]),
    )
    tolerant = RasQualification.compare_rasters(native, tolerant_wine, limits)

    assert tolerant["passed"] is True
    assert tolerant["comparison_mode"] == "tolerance"
    assert tolerant["exact_match"] is False
    assert tolerant["tolerance_passed"] is True
    assert tolerant["valid_mask_overlap"] == 1.0
    assert tolerant["max_abs"] == pytest.approx(0.02, abs=1e-6)


def test_map_raster_comparison_requires_exact_grid_and_valid_mask_overlap(tmp_path):
    from rasterio.transform import from_origin

    native = _write_raster(
        tmp_path / "native" / "Depth Max.tif",
        np.array([[0.0, 1.0], [2.0, 3.0]]),
        transform=from_origin(0, 2, 1, 1),
    )
    shifted = _write_raster(
        tmp_path / "shifted" / "Depth Max.tif",
        np.array([[0.0, 1.0], [2.0, 3.0]]),
        transform=from_origin(1, 2, 1, 1),
    )
    limits = RasterTolerance(
        max_abs=10.0,
        rmse=10.0,
        minimum_wet_overlap=0.0,
        minimum_valid_overlap=0.0,
    )

    shifted_result = RasQualification.compare_rasters(native, shifted, limits)

    assert shifted_result["passed"] is False
    assert shifted_result["transform_exact"] is False
    assert shifted_result["same_grid"] is False
    assert shifted_result["tolerance_passed"] is False

    masked = _write_raster(
        tmp_path / "masked" / "Depth Max.tif",
        np.array([[0.0, 1.0], [2.0, -9999.0]]),
    )
    mask_result = RasQualification.compare_rasters(
        native,
        masked,
        RasterTolerance(
            max_abs=0.0,
            rmse=0.0,
            minimum_wet_overlap=0.0,
            minimum_valid_overlap=1.0,
        ),
    )

    assert mask_result["passed"] is False
    assert mask_result["valid_mask_exact"] is False
    assert mask_result["valid_mask_overlap"] == pytest.approx(0.75)
    assert mask_result["valid_overlap_passed"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"max_abs": -1.0},
        {"rmse": -1.0},
        {"minimum_wet_overlap": -0.01},
        {"minimum_wet_overlap": 1.01},
        {"minimum_valid_overlap": -0.01},
        {"minimum_valid_overlap": 1.01},
        {"wet_threshold": -1.0},
        {"max_abs": float("nan")},
        {"rmse": float("inf")},
        {"resampling": "cubic"},
    ],
)
def test_raster_tolerance_rejects_invalid_limits(override):
    values = {
        "max_abs": 0.1,
        "rmse": 0.05,
        "minimum_wet_overlap": 0.9,
        "wet_threshold": 0.0,
        "resampling": "nearest",
    }
    values.update(override)

    with pytest.raises(ValueError):
        RasterTolerance(**values)


def test_compare_run_receipts_enforces_geometry_terrain_volume_series_and_depth(tmp_path):
    native = _complete_receipt(ExecutorProfile.WINDOWS_NATIVE)
    wine = _complete_receipt(ExecutorProfile.LINUX_WINE_WINDOWS_RAS)
    native_depth = _write_raster(tmp_path / "native-depth.tif", np.array([[0.0, 1.0], [2.0, 3.0]]))
    wine_depth = _write_raster(tmp_path / "wine-depth.tif", np.array([[0.0, 1.02], [2.0, 3.0]]))
    native["artifacts"]["depth_grid"] = {"path": str(native_depth)}
    wine["artifacts"]["depth_grid"] = {"path": str(wine_depth)}
    result = RasQualification.compare_run_receipts(
        native,
        wine,
        tolerances={
            "volume_accounting": {
                "max_abs_error_percent": 1.0,
                "max_abs_difference_percent": 0.1,
            },
            "series": {
                "outflow": {
                    "key_columns": ["time"],
                    "columns": {
                        "flow": {"max_abs": 0.1, "rmse": 0.1, "peak_relative": 0.05},
                    },
                },
                "wse_cells": {
                    "key_columns": ["time", "cell_id"],
                    "columns": {"wse": {"max_abs": 0.05, "rmse": 0.05}},
                }
            },
            "depth_raster": {
                "max_abs": 0.05,
                "rmse": 0.03,
                "minimum_wet_overlap": 1.0,
            },
        },
    )

    assert result["passed"] is True
    assert all(result["checks"].values())

    missing_wse_tolerance = RasQualification.compare_run_receipts(
        native,
        wine,
        tolerances={
            "volume_accounting": {
                "max_abs_error_percent": 1.0,
                "max_abs_difference_percent": 0.1,
            },
            "series": {
                "outflow": {
                    "key_columns": ["time"],
                    "columns": {"flow": {"max_abs": 0.1, "rmse": 0.1}},
                }
            },
            "depth_raster": {
                "max_abs": 0.05,
                "rmse": 0.03,
                "minimum_wet_overlap": 1.0,
            },
        },
    )
    assert missing_wse_tolerance["passed"] is False
    assert missing_wse_tolerance["checks"]["hydrograph_wse_tolerances"] is False

    wine_bad = copy.deepcopy(wine)
    wine_bad["artifacts"]["geometry"]["areas"]["MainArea"]["cell_count"] = 11
    wine_bad["artifacts"]["geometry"]["areas"]["MainArea"]["quality"]["invalid_cell_count"] = 1
    wine_bad["installation"]["components"]["ras"]["sha256"] = "f" * 64
    failed = RasQualification.compare_run_receipts(
        native,
        wine_bad,
        tolerances={
            "volume_accounting": {
                "max_abs_error_percent": 1.0,
                "max_abs_difference_percent": 0.1,
            },
            "series": {
                "outflow": {
                    "key_columns": ["time"],
                    "columns": {"flow": {"max_abs": 0.1, "rmse": 0.1}},
                },
                "wse_cells": {
                    "key_columns": ["time", "cell_id"],
                    "columns": {"wse": {"max_abs": 0.05, "rmse": 0.05}},
                }
            },
            "depth_raster": {
                "max_abs": 0.05,
                "rmse": 0.03,
                "minimum_wet_overlap": 1.0,
            },
        },
    )
    assert failed["passed"] is False
    assert failed["checks"]["installation_identity"] is False
    assert failed["checks"]["geometry"] is False
    assert failed["checks"]["geometry"] is False


def test_compare_run_receipts_compares_every_requested_mapper_raster_type(tmp_path):
    native = _complete_receipt(ExecutorProfile.WINDOWS_NATIVE)
    wine = _complete_receipt(ExecutorProfile.LINUX_WINE_WINDOWS_RAS)
    native_folder = tmp_path / "native-maps"
    wine_folder = tmp_path / "wine-maps"
    map_values = {
        "wse": ("WSE Max.tif", np.array([[10.0, 11.0], [12.0, 13.0]])),
        "depth": ("Depth Max.tif", np.array([[0.0, 1.0], [2.0, 3.0]])),
        "velocity": ("Velocity Max.tif", np.array([[0.0, 0.5], [1.0, 1.5]])),
    }
    native_maps = {}
    wine_maps = {}
    for map_type, (filename, values) in map_values.items():
        native_path = _write_raster(native_folder / filename, values)
        wine_values = values.copy()
        if map_type == "depth":
            wine_values[0, 1] += 0.02
        wine_path = _write_raster(wine_folder / filename, wine_values)
        native_maps[map_type] = [RasQualification.raster_receipt(native_path)]
        wine_maps[map_type] = [RasQualification.raster_receipt(wine_path)]

    native["artifacts"]["map_rasters_by_type"] = native_maps
    wine["artifacts"]["map_rasters_by_type"] = wine_maps
    native["artifacts"]["map_rasters"] = [
        item for receipts in native_maps.values() for item in receipts
    ]
    wine["artifacts"]["map_rasters"] = [
        item for receipts in wine_maps.values() for item in receipts
    ]
    native["artifacts"]["depth_grid"] = native_maps["depth"][0]
    wine["artifacts"]["depth_grid"] = wine_maps["depth"][0]

    map_limits = {
        map_type: {
            "max_abs": 0.05,
            "rmse": 0.03,
            "minimum_wet_overlap": 1.0,
            "minimum_valid_overlap": 1.0,
        }
        for map_type in map_values
    }
    tolerances = {
        "volume_accounting": {
            "max_abs_error_percent": 1.0,
            "max_abs_difference_percent": 0.1,
        },
        "series": {
            "outflow": {
                "key_columns": ["time"],
                "columns": {
                    "flow": {
                        "max_abs": 0.1,
                        "rmse": 0.1,
                        "peak_relative": 0.05,
                    }
                },
            },
            "wse_cells": {
                "key_columns": ["time", "cell_id"],
                "columns": {"wse": {"max_abs": 0.05, "rmse": 0.05}},
            },
        },
        "map_rasters": map_limits,
    }

    result = RasQualification.compare_run_receipts(native, wine, tolerances)

    assert result["passed"] is True
    assert result["checks"]["map_rasters"] is True
    assert result["map_rasters"]["requested_map_types"] == [
        "depth",
        "velocity",
        "wse",
    ]
    assert set(result["map_rasters"]["types"]) == {
        "depth",
        "velocity",
        "wse",
    }
    assert all(
        item["passed"] is True
        for item in result["map_rasters"]["types"].values()
    )
    assert result["depth_raster"]["comparison_mode"] == "tolerance"
    assert result["map_rasters"]["types"]["wse"]["rasters"][
        "wse max.tif"
    ]["comparison_mode"] == "exact"

    missing_tolerance = copy.deepcopy(tolerances)
    del missing_tolerance["map_rasters"]["velocity"]
    missing_tolerance_result = RasQualification.compare_run_receipts(
        native,
        wine,
        missing_tolerance,
    )
    assert missing_tolerance_result["passed"] is False
    assert missing_tolerance_result["map_rasters"]["checks"][
        "tolerances_cover_requested_types_exactly"
    ] is False
    assert missing_tolerance_result["map_rasters"]["types"]["velocity"][
        "checks"
    ]["tolerance_configured"] is False

    missing_velocity = copy.deepcopy(wine)
    del missing_velocity["artifacts"]["map_rasters_by_type"]["velocity"]
    missing_velocity_result = RasQualification.compare_run_receipts(
        native,
        missing_velocity,
        tolerances,
    )
    assert missing_velocity_result["passed"] is False
    assert missing_velocity_result["map_rasters"]["checks"][
        "requested_map_types_exact"
    ] is False
    assert missing_velocity_result["map_rasters"]["types"]["velocity"][
        "checks"
    ]["wine_receipts_present"] is False

    incomplete_receipt = copy.deepcopy(wine)
    incomplete_receipt["artifacts"]["map_rasters_by_type"]["wse"][0][
        "crs_wkt"
    ] = None
    incomplete_result = RasQualification.compare_run_receipts(
        native,
        incomplete_receipt,
        tolerances,
    )
    assert incomplete_result["passed"] is False
    assert incomplete_result["map_rasters"]["types"]["wse"]["checks"][
        "wine_receipts_complete"
    ] is False


def test_receipt_json_round_trip_is_strict(tmp_path):
    receipt = _complete_receipt(ExecutorProfile.WINDOWS_NATIVE)
    path = RasQualification.write_receipt(receipt, tmp_path / "receipt.json")
    assert RasQualification.read_receipt(path) == receipt
