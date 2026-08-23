"""Focused tests for project asset inspection and atomic staging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import pandas as pd
import pytest

import ras_commander.RasProject as project_module
from ras_commander.schemas import DATAFRAME_SCHEMAS
from ras_commander import (
    ProjectPathAmbiguityError,
    ProjectPublicationError,
    inspect_project_assets,
    stage_project,
)


def _write_project(
    root: Path,
    *,
    dss: bool = False,
    geometry_hdf: bool = True,
) -> Path:
    root.mkdir(parents=True)
    project = root / "Model.prj"
    project.write_text(
        "Proj Title=Test Project\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Unsteady File=u01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        "Plan Title=Base\n"
        "Program Version=6.60\n"
        "Short Identifier=Base\n"
        "Simulation Date=01JAN2020,0000,02JAN2020,0000\n"
        "Geom File=g01\n"
        "Flow File=u01\n",
        encoding="ascii",
    )
    (root / "Model.g01").write_text("Geom Title=Base Geometry\n", encoding="ascii")
    if geometry_hdf:
        with h5py.File(root / "Model.g01.hdf", "w") as hdf:
            hdf.attrs["Projection"] = ""
    boundary = ""
    if dss:
        boundary = (
            "Boundary Location=River,Reach,1000,,,,,\n"
            "Interval=1HOUR\n"
            "Flow Hydrograph=0\n"
            "DSS File=input.dss\n"
            "DSS Path=//BASIN/LOCATION/FLOW//1HOUR/RUN/\n"
            "Use DSS=True\n"
        )
        (root / "input.dss").write_bytes(b"not-opened-by-test")
    (root / "Model.u01").write_text(
        "Flow Title=Base Flow\n"
        "Program Version=6.60\n"
        "Use Restart=0\n"
        "Precipitation Mode=Disable\n"
        + boundary,
        encoding="ascii",
    )
    (root / "empty-input-directory").mkdir()
    return project


def _add_second_plan(project: Path) -> None:
    project.write_text(
        project.read_text(encoding="ascii") + "Plan File=p02\n",
        encoding="ascii",
    )
    (project.parent / "Model.p02").write_text(
        "Plan Title=Alternative\n"
        "Program Version=6.60\n"
        "Short Identifier=Alt\n"
        "Simulation Date=03JAN2020,0000,04JAN2020,0000\n"
        "Geom File=g01\n"
        "Flow File=u01\n",
        encoding="ascii",
    )


def _write_steady_project(root: Path) -> Path:
    root.mkdir(parents=True)
    project = root / "Steady.prj"
    project.write_text(
        "Proj Title=Steady Project\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Steady.p01").write_text(
        "Plan Title=Base\n"
        "Program Version=5.07\n"
        "Short Identifier=Base\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Steady.g01").write_text("Geom Title=Steady\n", encoding="ascii")
    (root / "Steady.f01").write_text("Flow Title=Steady\n", encoding="ascii")
    return project


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file())):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_inspect_project_assets_returns_stable_arrow_schema(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "source", geometry_hdf=False)

    assets = inspect_project_assets(project, depth="current_plan")

    assert list(assets.columns) == project_module._INVENTORY_COLUMNS
    assert list(assets.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["project_asset_inventory"]["columns"]
    ]
    assert str(assets["asset_kind"].dtype) == "string[pyarrow]"
    assert str(assets["required"].dtype) == "bool[pyarrow]"
    assert str(assets["detail"].dtype) == "string[pyarrow]"
    assert str(assets["dataset_name"].dtype) == "string[pyarrow]"
    assert str(assets["expected_start"].dtype) == "timestamp[ns, tz=UTC][pyarrow]"
    assert set(assets.loc[assets["asset_kind"] == "plan", "plan_number"]) == {"01"}
    geometry_hdf = assets.loc[assets["asset_kind"] == "geometry_hdf"].iloc[0]
    assert geometry_hdf["inspection_state"] == "missing"
    assert geometry_hdf["readiness"] == "not_ready"
    assert geometry_hdf["required"] is True


def test_dss_dataset_remains_not_inspected_and_container_is_unchanged(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path / "source", dss=True)
    dss_file = project.parent / "input.dss"
    before = (dss_file.read_bytes(), dss_file.stat().st_mtime_ns)

    assets = inspect_project_assets(
        project,
        depth="current_plan",
        dss_inspection="coverage",
    )

    file_row = assets.loc[assets["asset_kind"] == "dss_file"].iloc[0]
    pathname_row = assets.loc[assets["asset_kind"] == "dss_pathname"].iloc[0]
    boundary_row = assets.loc[assets["asset_kind"] == "boundary"].iloc[0]
    assert file_row["inspection_state"] == "available"
    assert pathname_row["inspection_state"] == "not_inspected"
    assert pathname_row["readiness"] == "unknown"
    assert pathname_row["reason_code"] == "reader_not_source_immutable"
    assert pathname_row["expected_start"] == pd.Timestamp("2020-01-01", tz="UTC")
    assert pathname_row["expected_end"] == pd.Timestamp("2020-01-02", tz="UTC")
    assert boundary_row["reference_raw"].startswith("Boundary Location=")
    assert file_row["parent_asset_id"] == boundary_row["asset_id"]
    assert pathname_row["parent_asset_id"] == file_row["asset_id"]
    assert (dss_file.read_bytes(), dss_file.stat().st_mtime_ns) == before


def test_stage_project_preserves_uninspected_active_dss_as_unknown(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path / "source", dss=True)
    dss_file = project.parent / "input.dss"
    before = (dss_file.read_bytes(), dss_file.stat().st_mtime_ns)

    result = stage_project(project, tmp_path / "published-dss")

    pathname = result.assets.loc[
        result.assets["asset_kind"] == "dss_pathname"
    ].iloc[0]
    assert result.execution_readiness == "unknown"
    assert pathname["required"] is True
    assert pathname["inspection_state"] == "not_inspected"
    assert pathname["readiness"] == "unknown"
    assert (dss_file.read_bytes(), dss_file.stat().st_mtime_ns) == before


def test_shared_dss_dependencies_are_scoped_per_plan_and_hashed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source", dss=True)
    _add_second_plan(project)
    calls: dict[Path, int] = {}
    original_hash = project_module._sha256_file

    def counting_hash(path: Path) -> str:
        calls[path] = calls.get(path, 0) + 1
        return original_hash(path)

    monkeypatch.setattr(project_module, "_sha256_file", counting_hash)
    assets = inspect_project_assets(project, depth="all_plans", hash_files=True)

    pathname_rows = assets.loc[assets["asset_kind"] == "dss_pathname"]
    assert set(pathname_rows["plan_number"]) == {"01", "02"}
    assert set(pathname_rows["expected_start"]) == {
        pd.Timestamp("2020-01-01", tz="UTC"),
        pd.Timestamp("2020-01-03", tz="UTC"),
    }
    assert len(set(pathname_rows["parent_asset_id"])) == 2
    assert calls[project.parent / "input.dss"] == 1
    assert calls[project.parent / "Model.g01"] == 1
    assert calls[project.parent / "Model.u01"] == 1
    assert set(assets.loc[assets["asset_kind"] == "geometry", "plan_number"]) == {
        "01",
        "02",
    }
    assert set(
        assets.loc[assets["asset_kind"] == "unsteady_flow", "plan_number"]
    ) == {"01", "02"}
    for plan_number in ("01", "02"):
        flow_row = assets.loc[
            (assets["asset_kind"] == "unsteady_flow")
            & (assets["plan_number"] == plan_number)
        ].iloc[0]
        boundary_row = assets.loc[
            (assets["asset_kind"] == "boundary")
            & (assets["plan_number"] == plan_number)
            & (assets["inspection_state"] == "available")
        ].iloc[0]
        assert boundary_row["parent_asset_id"] == flow_row["asset_id"]


def test_steady_1d_geometry_hdf_is_not_required(tmp_path: Path) -> None:
    project = _write_steady_project(tmp_path / "steady")

    assets = inspect_project_assets(project, depth="current_plan")

    geometry_hdf = assets.loc[assets["asset_kind"] == "geometry_hdf"].iloc[0]
    assert geometry_hdf["inspection_state"] == "not_applicable"
    assert geometry_hdf["readiness"] == "not_required"
    assert geometry_hdf["required"] is False


def test_directory_input_fails_closed_when_multiple_projects_exist(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    first = _write_project(root)
    (root / "Other.prj").write_text("Proj Title=Other\n", encoding="ascii")

    with pytest.raises(ValueError, match="Ambiguous"):
        inspect_project_assets(first.parent)


def test_project_depth_initialization_does_not_open_hdf_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source")
    (project.parent / "Model.g01.hdf").write_bytes(b"not an hdf")

    from ras_commander.geom.GeomMetadata import GeomMetadata

    observed_hdf_paths: list[object] = []

    def geometry_counts(*, geom_path, hdf_path):
        observed_hdf_paths.append(hdf_path)
        return GeomMetadata.DEFAULT_COUNTS.copy()

    def forbidden_crs_refresh(self):
        raise AssertionError("project-depth inventory must not inspect HDF/raster CRS")

    monkeypatch.setattr(GeomMetadata, "get_geometry_counts", geometry_counts)
    monkeypatch.setattr(
        project_module.RasPrj,
        "refresh_project_crs",
        forbidden_crs_refresh,
    )

    assets = inspect_project_assets(project, depth="project")

    assert not assets.empty
    assert observed_hdf_paths == [None]


def test_current_plan_inventory_rejects_undeclared_plan(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "source")
    project.write_text(
        project.read_text(encoding="ascii").replace(
            "Current Plan=p01",
            "Current Plan=p99",
        ),
        encoding="ascii",
    )

    with pytest.raises(
        project_module.ProjectPopulationError,
        match="current_plan_undeclared",
    ):
        inspect_project_assets(project, depth="current_plan")


def test_inventory_emits_rows_for_restart_and_precipitation_parser_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source")

    def fail_restart(*args, **kwargs):
        raise ValueError("bad restart block")

    def fail_precipitation(*args, **kwargs):
        raise ValueError("bad precipitation block")

    monkeypatch.setattr(
        project_module.RasUnsteady,
        "get_restart_settings",
        fail_restart,
    )
    monkeypatch.setattr(
        project_module.RasUnsteady,
        "get_met_precipitation_config",
        fail_precipitation,
    )

    assets = inspect_project_assets(project, depth="current_plan")

    failures = assets.loc[assets["inspection_state"] == "failed"]
    assert set(failures["reason_code"]) >= {
        "restart_parse_failed",
        "precipitation_parse_failed",
    }


def test_gdal_precipitation_fields_are_inventoried_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source")
    raster = project.parent / "rain.nc"
    raster.write_bytes(b"netcdf-placeholder")
    raster_folder = project.parent / "rain-grid"
    raster_folder.mkdir()

    def gdal_config(*args, **kwargs):
        return {
            "enabled": True,
            "mode": "Gridded",
            "source": "GDAL Raster File(s)",
            "gdal_filename": raster.name,
            "gdal_folder": raster_folder.name,
            "gdal_group": "precipitation/hourly",
            "gdal_filter": "*.nc",
            "raw": {
                "Gridded GDAL Filename": raster.name,
                "Gridded GDAL Folder": raster_folder.name,
                "Gridded GDAL Group": "precipitation/hourly",
                "Gridded GDAL Datasetname": "legacy-precipitation",
                "Gridded GDAL Filter": "*.nc",
            },
        }

    monkeypatch.setattr(
        project_module.RasUnsteady,
        "get_met_precipitation_config",
        gdal_config,
    )

    assets = inspect_project_assets(project, depth="current_plan")

    source_apis = set(assets["source_api"])
    assert {
        "RasUnsteady.get_met_precipitation_config.gdal_filename",
        "RasUnsteady.get_met_precipitation_config.gdal_folder",
        "RasUnsteady.get_met_precipitation_config.gdal_group",
        "RasUnsteady.get_met_precipitation_config.gdal_datasetname",
        "RasUnsteady.get_met_precipitation_config.gdal_filter",
    }.issubset(source_apis)
    group = assets.loc[
        assets["source_api"]
        == "RasUnsteady.get_met_precipitation_config.gdal_group"
    ].iloc[0]
    assert group["dataset_name"] == "precipitation/hourly"
    assert group["inspection_state"] == "not_inspected"
    datasetname = assets.loc[
        assets["source_api"]
        == "RasUnsteady.get_met_precipitation_config.gdal_datasetname"
    ].iloc[0]
    assert datasetname["reference_raw"] == "legacy-precipitation"
    assert datasetname["dataset_name"] == "legacy-precipitation"


def test_stage_project_preserves_uninspected_gdal_groups_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source")
    raster = project.parent / "rain.nc"
    raster.write_bytes(b"netcdf-placeholder")
    raster_folder = project.parent / "rain-grid"
    raster_folder.mkdir()

    def gdal_config(*args, **kwargs):
        return {
            "enabled": True,
            "mode": "Gridded",
            "source": "GDAL Raster File(s)",
            "gdal_filename": raster.name,
            "gdal_folder": raster_folder.name,
            "gdal_group": "precipitation/hourly",
            "gdal_filter": "*.nc",
            "raw": {
                "Gridded GDAL Filename": raster.name,
                "Gridded GDAL Folder": raster_folder.name,
                "Gridded GDAL Group": "precipitation/hourly",
                "Gridded GDAL Datasetname": "legacy-precipitation",
                "Gridded GDAL Filter": "*.nc",
            },
        }

    monkeypatch.setattr(
        project_module.RasUnsteady,
        "get_met_precipitation_config",
        gdal_config,
    )

    result = stage_project(project, tmp_path / "published-gdal")

    dataset_rows = result.assets.loc[
        result.assets["source_api"].isin(
            {
                "RasUnsteady.get_met_precipitation_config.gdal_group",
                "RasUnsteady.get_met_precipitation_config.gdal_datasetname",
            }
        )
    ]
    assert result.execution_readiness == "unknown"
    assert len(dataset_rows) == 2
    assert dataset_rows["required"].eq(True).all()  # noqa: E712
    assert dataset_rows["inspection_state"].eq("not_inspected").all()


def test_boundary_diagnostic_asset_ids_remain_unique(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path / "source", dss=True)
    ras_object = project_module._explicit_ras(project, None)
    ras_object.boundaries_df = pd.DataFrame()

    assets = inspect_project_assets(
        project,
        ras_object=ras_object,
        depth="current_plan",
    )

    boundary_rows = assets.loc[assets["asset_kind"] == "boundary"]
    assert "boundary_inventory_mismatch" in set(boundary_rows["reason_code"])
    assert boundary_rows["asset_id"].is_unique
    assert assets["asset_id"].is_unique


def test_rasmap_unknown_paths_and_required_shapefile_sidecars_are_inventoried(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path / "source")
    vectors = project.parent / "vectors"
    vectors.mkdir()
    for suffix in (".shp", ".shx", ".dbf"):
        (vectors / f"line{suffix}").write_bytes(suffix.encode("ascii"))
    (project.parent / "Model.rasmap").write_text(
        '<RASMapper><Layer Filename="vectors/line.shp" /></RASMapper>',
        encoding="utf-8",
    )

    assets = inspect_project_assets(project, depth="project")

    sidecars = assets.loc[
        assets["source_api"] == "implied ESRI Shapefile sidecar"
    ]
    assert set(sidecars["resolved_path"].map(lambda value: Path(value).suffix)) == {
        ".shx",
        ".dbf",
    }
    assert sidecars["required"].isna().all()
    assert sidecars["exists"].all()
    assert sidecars["parent_asset_id"].nunique() == 1


def test_empty_structured_rasmap_inventory_remains_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path / "source")
    (project.parent / "Model.rasmap").write_text(
        "<RASMapper />",
        encoding="utf-8",
    )

    from ras_commander.RasMap import RasMap

    def fail_rasmap(*args, **kwargs):
        raise ValueError("structured parser failed")

    monkeypatch.setattr(RasMap, "initialize_rasmap_df", fail_rasmap)

    assets = inspect_project_assets(project, depth="project")

    row = assets.loc[
        assets["reason_code"] == "rasmap_structured_inventory_empty"
    ].iloc[0]
    assert row["inspection_state"] == "not_inspected"
    assert row["readiness"] == "unknown"


def test_stage_project_publishes_verified_copy_without_source_drift(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    source_hash = _tree_hash(source_project.parent)
    destination = tmp_path / "published"

    result = stage_project(source_project, destination)

    assert result.publication_state == "published"
    assert result.source_fingerprint_before == result.source_fingerprint_after
    assert result.source_project_file == source_project
    assert result.destination_project_file == destination / source_project.name
    assert result.ras_object.prj_file == result.destination_project_file
    assert result.ras_object.ras_version == "6.6"
    assert result.ras_object.plan_df["full_path"].str.startswith(str(destination)).all()
    assert result.assets["resolved_path"].dropna().str.startswith(str(destination)).any()
    assert result.assets.loc[result.assets["is_file"] == True, "sha256"].notna().all()  # noqa: E712
    assert (destination / "empty-input-directory").is_dir()
    manifest_path = destination / ".ras-commander" / "stage.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {item["provenance"] for item in manifest["artifacts"]} == {
        "copied_source",
        "generated_stage_metadata",
    }
    assert project_module._tree_snapshot(destination)[1] == result.published_fingerprint
    assert _tree_hash(source_project.parent) == source_hash
    assert not list(tmp_path.glob(".published.ras-stage-*"))
    assert not (tmp_path / ".published.rascommander-stage.lock").exists()


def test_stage_project_never_replaces_existing_destination(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="ascii")

    with pytest.raises(FileExistsError):
        stage_project(source_project, destination)

    assert marker.read_text(encoding="ascii") == "keep"


def test_stage_project_rejects_missing_declared_core_file(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    (source_project.parent / "Model.g01").unlink()
    destination = tmp_path / "published"

    with pytest.raises(RuntimeError, match="Invalid staged project population"):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_stage_project_rejects_missing_mechanically_required_hdf(
    tmp_path: Path,
) -> None:
    source_project = _write_project(
        tmp_path / "source",
        geometry_hdf=False,
    )
    destination = tmp_path / "published"

    with pytest.raises(
        project_module.ProjectPopulationError,
        match="required_component_unavailable",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_stage_project_rejects_overlap_and_lock_artifacts(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")

    with pytest.raises(ProjectPathAmbiguityError, match="path_overlap"):
        stage_project(source_project, source_project.parent / "nested-stage")

    lock = source_project.parent / "active.lock"
    lock.write_text("active", encoding="ascii")
    with pytest.raises(RuntimeError, match="lock file"):
        stage_project(source_project, tmp_path / "published")
    assert not (tmp_path / "published").exists()


def test_stage_project_fails_when_physical_path_identity_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"

    def denied_identity(*args, **kwargs):
        raise PermissionError("identity denied")

    monkeypatch.setattr(project_module.os.path, "samefile", denied_identity)

    with pytest.raises(
        ProjectPathAmbiguityError,
        match="path_identity_unavailable",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()


def test_source_drift_failure_leaves_destination_absent_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"
    original_copy = project_module._copy_snapshot

    def drifting_copy(source_root, destination_root, files, directories):
        original_copy(source_root, destination_root, files, directories)
        (source_root / "Model.g01").write_text("changed during copy\n", encoding="ascii")

    monkeypatch.setattr(project_module, "_copy_snapshot", drifting_copy)

    with pytest.raises(RuntimeError, match="Source project changed"):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))
    assert not (tmp_path / ".published.rascommander-stage.lock").exists()


def test_staged_file_drift_after_inventory_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    (source_project.parent / "note.bin").write_bytes(b"original")
    destination = tmp_path / "published"
    original_inspect = project_module.inspect_project_assets

    def mutating_inspect(project, **kwargs):
        assets = original_inspect(project, **kwargs)
        (Path(project).parent / "note.bin").write_bytes(b"changed after inspection")
        return assets

    monkeypatch.setattr(project_module, "inspect_project_assets", mutating_inspect)

    with pytest.raises(
        project_module.ProjectCopyVerificationError,
        match="copy_content_mismatch",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_staged_file_drift_during_fsync_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    (source_project.parent / "note.bin").write_bytes(b"original")
    destination = tmp_path / "published"
    original_fsync_tree = project_module._fsync_tree

    def mutating_fsync_tree(root: Path) -> None:
        original_fsync_tree(root)
        (Path(root) / "note.bin").write_bytes(b"changed during fsync")

    monkeypatch.setattr(project_module, "_fsync_tree", mutating_fsync_tree)

    with pytest.raises(
        project_module.ProjectCopyVerificationError,
        match="copy_content_mismatch",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_source_drift_during_fsync_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"
    original_fsync_tree = project_module._fsync_tree

    def mutating_fsync_tree(root: Path) -> None:
        original_fsync_tree(root)
        (source_project.parent / "Model.g01").write_text(
            "changed during fsync\n",
            encoding="ascii",
        )

    monkeypatch.setattr(project_module, "_fsync_tree", mutating_fsync_tree)

    with pytest.raises(
        project_module.ProjectDriftError,
        match="source_changed_before_publish",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_publication_race_leaves_competing_destination_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"
    original_rename = project_module._native_rename_noreplace

    def racing_rename(source, target):
        Path(target).mkdir()
        (Path(target) / "competitor.txt").write_text("winner", encoding="ascii")
        original_rename(source, target)

    monkeypatch.setattr(project_module, "_native_rename_noreplace", racing_rename)
    with pytest.raises(ProjectPublicationError, match="destination_race") as error:
        stage_project(source_project, destination)

    assert error.value.publication_outcome == "not_committed"
    assert (destination / "competitor.txt").read_text(encoding="ascii") == "winner"
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_publication_fails_closed_when_atomic_noreplace_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"

    def unsupported_rename(source, target):
        raise OSError(project_module.errno.ENOSYS, "unsupported")

    monkeypatch.setattr(
        project_module,
        "_native_rename_noreplace",
        unsupported_rename,
    )

    with pytest.raises(
        ProjectPublicationError,
        match="atomic_noreplace_unavailable",
    ) as error:
        stage_project(source_project, destination)

    assert error.value.publication_outcome == "not_committed"
    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))


def test_publication_reconciles_error_reported_after_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "prepared"
    source.mkdir()
    (source / "payload.txt").write_text("verified", encoding="ascii")
    destination = tmp_path / "published"
    original_rename = project_module._native_rename_noreplace

    def error_after_commit(source_path, destination_path):
        original_rename(source_path, destination_path)
        raise OSError(project_module.errno.EIO, "remote acknowledgement lost")

    monkeypatch.setattr(
        project_module,
        "_native_rename_noreplace",
        error_after_commit,
    )

    project_module._publish_directory_noreplace(source, destination)

    assert not source.exists()
    assert (destination / "payload.txt").read_text(encoding="ascii") == "verified"


def test_unprovable_publication_outcome_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "prepared"
    source.mkdir()
    destination = tmp_path / "published"

    monkeypatch.setattr(
        project_module,
        "_native_rename_noreplace",
        lambda source_path, destination_path: None,
    )

    with pytest.raises(
        ProjectPublicationError,
        match="publication_outcome_unknown",
    ) as error:
        project_module._publish_directory_noreplace(source, destination)

    assert error.value.publication_outcome == "unknown"
    assert source.is_dir()
    assert not destination.exists()


def test_post_publication_drift_reports_committed_and_retains_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    (source_project.parent / "note.bin").write_bytes(b"original")
    destination = tmp_path / "published"
    original_publish = project_module._publish_directory_noreplace

    def mutating_publish(source, target):
        original_publish(source, target)
        (Path(target) / "note.bin").write_bytes(b"changed after commit")

    monkeypatch.setattr(
        project_module,
        "_publish_directory_noreplace",
        mutating_publish,
    )

    with pytest.raises(
        ProjectPublicationError,
        match="published_fingerprint_mismatch",
    ) as error:
        stage_project(source_project, destination)

    assert error.value.publication_outcome == "committed"
    assert error.value.publication_committed is True
    assert destination.is_dir()
    assert (destination / "note.bin").read_bytes() == b"changed after commit"


def test_raw_prepublication_filesystem_error_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"

    def denied_temp(*args, **kwargs):
        raise PermissionError("temporary directory denied")

    monkeypatch.setattr(project_module.tempfile, "mkdtemp", denied_temp)

    with pytest.raises(
        project_module.ProjectStageError,
        match="staging_filesystem_error",
    ) as error:
        stage_project(source_project, destination)

    assert error.value.publication_outcome == "not_committed"
    assert not destination.exists()


def test_initialization_failure_cleans_only_owned_temporary_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"

    def fail_initialize(*args, **kwargs):
        raise RuntimeError("injected initialization failure")

    monkeypatch.setattr(project_module, "init_ras_project", fail_initialize)
    with pytest.raises(RuntimeError, match="staged_initialization_failed"):
        stage_project(source_project, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.ras-stage-*"))
    assert not (tmp_path / ".published.rascommander-stage.lock").exists()


def test_stage_project_initializes_ras_only_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "published"
    original_initialize = project_module.init_ras_project
    calls = 0

    def counting_initialize(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_initialize(*args, **kwargs)

    monkeypatch.setattr(project_module, "init_ras_project", counting_initialize)

    result = stage_project(source_project, destination)

    assert calls == 1
    assert result.ras_object.prj_file == destination / source_project.name


def test_stage_project_rejects_an_undeclared_current_plan(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    source_project.write_text(
        source_project.read_text(encoding="ascii").replace(
            "Current Plan=p01",
            "Current Plan=p99",
        ),
        encoding="ascii",
    )
    destination = tmp_path / "published"

    with pytest.raises(
        project_module.ProjectPopulationError,
        match="current_plan_undeclared",
    ):
        stage_project(source_project, destination)

    assert not destination.exists()


def test_lock_cleanup_refuses_a_replaced_lock_file(tmp_path: Path) -> None:
    lock = tmp_path / ".published.rascommander-stage.lock"
    owned_token = b"pid=1;token=owned\n"
    lock.write_bytes(owned_token)
    info = lock.stat()
    identity = (info.st_dev, info.st_ino)
    lock.write_bytes(b"pid=2;token=replacement\n")

    project_module._safe_remove_owned_lock(lock, identity, owned_token)

    assert lock.read_bytes() == b"pid=2;token=replacement\n"


def test_stage_project_requires_an_existing_destination_parent(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    destination = tmp_path / "missing-parent" / "published"

    with pytest.raises(ProjectPathAmbiguityError, match="destination_parent_missing"):
        stage_project(source_project, destination)

    assert not destination.parent.exists()


def test_tree_fingerprint_includes_empty_directory_population(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "file.txt").write_text("same bytes", encoding="ascii")
    _, before, _ = project_module._tree_snapshot(root)

    (root / "new-empty-directory").mkdir()
    _, after, _ = project_module._tree_snapshot(root)

    assert before != after


def test_tree_snapshot_fails_closed_on_traversal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()

    def failing_walk(*args, **kwargs):
        kwargs["onerror"](PermissionError("access denied"))
        yield from ()

    monkeypatch.setattr(project_module.os, "walk", failing_walk)

    with pytest.raises(ProjectPathAmbiguityError, match="tree_traversal_failed"):
        project_module._tree_snapshot(root)


def test_stage_project_rejects_a_source_reparse_ancestor(tmp_path: Path) -> None:
    source_project = _write_project(tmp_path / "source")
    source_link = tmp_path / "source-link"
    try:
        source_link.symlink_to(source_project.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Windows symlink creation is unavailable: {exc}")

    with pytest.raises(ProjectPathAmbiguityError, match="reparse_point"):
        stage_project(source_link / source_project.name, tmp_path / "published")

    assert not (tmp_path / "published").exists()
