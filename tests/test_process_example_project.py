from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "process_example_project.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("process_example_project", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def processor():
    return load_script()


def inspection(project_file: Path) -> dict:
    return {
        "project": {
            "name": "Muncie",
            "prj_file": str(project_file),
            "crs": "EPSG:2965",
            "units": "English",
            "ras_version": "7.0",
        },
        "geometry_files": [
            {"geom_id": "g01", "hdf_exists": True, "has_1d_xs": True},
            {"geom_id": "g02", "hdf_exists": True, "has_2d_mesh": True},
        ],
        "plan_files": [
            {
                "plan_id": "p03",
                "plan_title": "2D 50ft Grid",
                "geom_number": "02",
                "hdf_exists": True,
                "completed": True,
            }
        ],
        "terrain_files": [str(project_file.parent / "Terrain" / "Terrain.tif")],
        "terrain_details": [
            {"name": "TerrainWithChannel", "tif_count": 2, "resolution": "5 x 5"}
        ],
    }


def write_config(
    tmp_path: Path,
    *,
    inspection_data: dict | None = None,
    extract: dict | None = None,
    package: dict | None = None,
) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "Muncie.prj"
    project_file.write_text("Proj Title=Muncie\n", encoding="ascii")
    for geom_id in ("g01", "g02"):
        (project_root / f"Muncie.{geom_id}.hdf").write_bytes(b"hdf")
    output_root = tmp_path / "output"
    config = {
        "schema": "rascommander.example-project-processor/v1",
        "source": {
            "id": "hec-ras-7.0-examples",
            "version": "7.0",
            "url": "https://example.test/source",
            "working_path": str(tmp_path / "private-source"),
        },
        "project": {
            "id": "muncie",
            "title": "Muncie",
            "project_file": "Muncie.prj",
            "primary_geometry": "g02",
            "all_primary_geometry": True,
        },
        "output_root": "output",
    }
    if inspection_data is not None:
        config["inspection"] = inspection_data
    if extract is not None:
        config["extract"] = extract
    if package is not None:
        config["package"] = package
    config_path = tmp_path / "processor.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, project_root, output_root


class FakeRas2cng:
    def __init__(self, inspection_data: dict, *, fail_command: str | None = None):
        self.inspection_data = inspection_data
        self.fail_command = fail_command
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        command = list(argv)
        self.calls.append((command, kwargs))
        subcommand = command[1]
        if subcommand == self.fail_command:
            return subprocess.CompletedProcess(command, 9, stdout="partial", stderr="forced failure")
        if subcommand == "inspect":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(self.inspection_data),
                stderr="",
            )
        if subcommand == "archive":
            archive_dir = Path(command[3])
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_manifest = {
                "schema_version": "2.6",
                "project": {
                    "name": "Muncie",
                    "prj_file": command[2],
                    "source_path": str(Path(command[2]).parent),
                    "archive_path": str(archive_dir),
                    "crs": "EPSG:2965",
                },
                "geometry": [{"geom_id": "g01"}, {"geom_id": "g02"}],
                "results": [{"plan_id": "p03", "geom_id": "g02"}],
                "terrain": [
                    {
                        "terrain_name": "TerrainWithChannel",
                        "cog_file": "terrain/terrain.cog.tif",
                    }
                ],
            }
            (archive_dir / "manifest.json").write_text(
                json.dumps(archive_manifest), encoding="utf-8"
            )
            terrain = archive_dir / "terrain" / "terrain.cog.tif"
            terrain.parent.mkdir()
            terrain.write_bytes(b"cog")
        elif subcommand == "map":
            cog = Path(command[3]) / "p03" / "Depth (Max).Terrain_cog.tif"
            cog.parent.mkdir(parents=True, exist_ok=True)
            cog.write_bytes(b"cog")
        elif subcommand == "maplibre":
            viewer_dir = Path(command[3])
            viewer_dir.mkdir(parents=True, exist_ok=True)
            viewer_manifest = {
                "schema": "rascommander.maplibre/v2",
                "sourceProject": "../project.json",
                "source_path": str(viewer_dir),
                "tilesets": [],
                "groups": [],
                "layers": {},
            }
            (viewer_dir / "manifest.json").write_text(
                json.dumps(viewer_manifest), encoding="utf-8"
            )
        elif subcommand == "maplibre-import-stored-maps":
            viewer_dir = Path(command[4])
            viewer_manifest = json.loads((viewer_dir / "manifest.json").read_text())
            viewer_manifest["layers"]["result-p03-depth-max"] = {
                "sourceKind": "stored-map",
                "sourceCog": "../archive/stored-maps/p03/depth-max.cog.tif",
                "plan": "p03",
                "geometry": "g02",
            }
            (viewer_dir / "manifest.json").write_text(
                json.dumps(viewer_manifest), encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, stdout=f"{subcommand} ok", stderr="")


def test_all_mode_builds_safe_commands_imports_stored_maps_and_records_status(
    tmp_path: Path, processor
) -> None:
    project_root = tmp_path / "project"
    project_file = project_root / "Muncie.prj"
    config_path, project_root, output_root = write_config(
        tmp_path,
        extract={"plans": ["p03"], "render_mode": "slopingPretty"},
    )
    fake = FakeRas2cng(inspection(project_file))

    status = processor.process_project(
        config_path=config_path,
        project_root=project_root,
        mode="all",
        runner=fake,
    )

    commands = [call[0] for call in fake.calls]
    assert [command[1] for command in commands] == [
        "inspect",
        "archive",
        "map",
        "maplibre",
        "maplibre-terrain",
        "maplibre-import-stored-maps",
    ]
    inspect_command, archive_command, map_command, maplibre_command, terrain_command, import_command = commands
    assert inspect_command[2:] == [str(project_root / "Muncie.prj"), "--json"]
    assert "--results" in archive_command
    assert archive_command[archive_command.index("--plans") + 1] == "p03"
    assert "--terrain" in archive_command
    assert "--consolidate-terrain" in archive_command
    assert archive_command[archive_command.index("--results-layout") + 1] == "variable"
    assert archive_command[archive_command.index("--results-geometry") + 1] == "none"
    assert "--auxiliary-results" in archive_command
    assert {
        "--cog",
        "--inundation-boundary",
        "--froude",
        "--shear-stress",
        "--dv",
        "--dv-sq",
        "--arrival-time",
        "--duration",
        "--percent-inundated",
        "--render-mode",
    } <= set(map_command)
    assert map_command[map_command.index("--arrival-depth") + 1] == "0.1"
    assert "--vector-results" in maplibre_command
    assert maplibre_command[maplibre_command.index("--primary-geometry") + 1] == "g02"
    assert "--all-primary-geometry" in maplibre_command
    hdf_bindings = [
        maplibre_command[index + 1]
        for index, value in enumerate(maplibre_command)
        if value == "--geometry-hdf"
    ]
    assert [binding.split("=", 1)[0] for binding in hdf_bindings] == ["g01", "g02"]
    assert terrain_command[terrain_command.index("--source-cog") + 1] == "../archive/terrain/terrain.cog.tif"
    assert "--allow-partial" in import_command
    assert "--overwrite" in import_command
    assert all(kwargs["shell"] is False for _, kwargs in fake.calls)

    assert status["state"] == "completed"
    assert status["source"]["id"] == "hec-ras-7.0-examples"
    assert status["project"]["id"] == "muncie"
    assert status["phases"]["package"]["storedMapsImported"] == [
        "result-p03-depth-max"
    ]
    assert all(
        status["phases"][name][timestamp]
        for name in ("inspect", "extract", "package")
        for timestamp in ("startedAt", "finishedAt")
    )

    archive = json.loads((output_root / "archive" / "manifest.json").read_text())
    assert archive["project"]["prj_file"] == "Muncie.prj"
    assert "source_path" not in archive["project"]
    assert "archive_path" not in archive["project"]
    viewer = json.loads((output_root / "viewer" / "manifest.json").read_text())
    stored_map = viewer["layers"]["result-p03-depth-max"]
    assert stored_map["sourceCog"] == "../archive/stored-maps/p03/depth-max.cog.tif"
    assert str(tmp_path) not in json.dumps(viewer)
    project_manifest = json.loads((output_root / "project.json").read_text())
    assert project_manifest["source"] == {
        "id": "hec-ras-7.0-examples",
        "version": "7.0",
        "url": "https://example.test/source",
    }
    assert str(tmp_path) not in json.dumps(project_manifest)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Depth (Max).Terrain_cog.tif", "depth"),
        ("Water Surface Elevation (Max).Terrain_cog.tif", "wse"),
        ("Velocity (Max).Terrain_cog.tif", "velocity"),
        ("Froude Number (Max).Terrain_cog.tif", "froude"),
        ("Shear Stress (Max).Terrain_cog.tif", "shear-stress"),
        ("Depth x Velocity (Max).Terrain_cog.tif", "depth-x-velocity"),
        ("D _ V Squared (Max).Terrain_cog.tif", "depth-x-velocity-squared"),
        ("Arrival Time (Max).Terrain_cog.tif", "arrival-time"),
        ("Duration (Max).Terrain_cog.tif", "duration"),
        ("Percent Time Inundated (Max).Terrain_cog.tif", "percent-inundated"),
        ("Inundation Boundary (Max).shp", "inundation-boundary"),
    ],
)
def test_stored_map_type_recognizes_every_default_output(
    filename: str, expected: str, processor
) -> None:
    assert processor._stored_map_type(filename)[0] == expected


def test_stored_map_candidates_include_rasters_and_inundation_boundaries(
    tmp_path: Path, processor
) -> None:
    plan_dir = tmp_path / "maps" / "p03"
    plan_dir.mkdir(parents=True)
    for filename in (
        "Froude Number (Max).Terrain_cog.tif",
        "D _ V Squared (Max).Terrain_cog.tif",
        "Inundation Boundary (Max).shp",
    ):
        (plan_dir / filename).touch()
    (plan_dir / "Inundation Boundary (Max).dbf").touch()

    candidates = processor._stored_map_candidates(tmp_path / "maps")

    assert [(plan, path.name) for plan, path in candidates] == [
        ("p03", "D _ V Squared (Max).Terrain_cog.tif"),
        ("p03", "Froude Number (Max).Terrain_cog.tif"),
        ("p03", "Inundation Boundary (Max).shp"),
    ]


def test_dry_run_records_planned_argv_without_invoking_subprocess(
    tmp_path: Path, processor
) -> None:
    project_file = tmp_path / "project" / "Muncie.prj"
    inspection_data = inspection(project_file)
    config_path, project_root, output_root = write_config(
        tmp_path,
        inspection_data=inspection_data,
        extract={"plans": ["p03"]},
    )

    def unexpected_runner(*_args, **_kwargs):
        raise AssertionError("dry-run invoked subprocess")

    status = processor.process_project(
        config_path=config_path,
        project_root=project_root,
        mode="all",
        dry_run=True,
        runner=unexpected_runner,
    )

    assert status["state"] == "dry-run"
    assert [
        command[1]
        for phase in status["phases"].values()
        for command in phase["commands"]
    ] == ["inspect", "archive", "map", "maplibre"]
    assert all(
        output["returnCode"] is None and output["dryRun"] is True
        for phase in status["phases"].values()
        for output in phase["outputs"]
    )
    assert not (output_root / "archive").exists()
    assert not (output_root / "viewer").exists()
    status_path = output_root / "processor-status.json"
    assert json.loads(status_path.read_text())["state"] == "dry-run"
    assert list(output_root.glob(f".{status_path.name}.*.tmp")) == []


def test_distinct_named_terrains_are_never_consolidated(tmp_path: Path, processor) -> None:
    config_path, project_root, _ = write_config(tmp_path)
    context = processor.build_context(config_path, project_root)
    inspected = inspection(project_root / "Muncie.prj")
    inspected["terrain_details"] = [
        {"name": "Existing", "tif_count": 2},
        {"name": "Proposed", "tif_count": 1},
    ]

    commands, policy = processor.build_extract_commands(context, inspected)

    assert "--terrain" in commands[0]
    assert "--consolidate-terrain" not in commands[0]
    assert policy["terrainConsolidated"] is False

    context.config["extract"] = {"consolidate_terrain": True}
    with pytest.raises(processor.ProcessorError, match="distinct named terrains"):
        processor.build_extract_commands(context, inspected)


def test_manifest_sanitizer_removes_known_paths_and_rejects_unknown_leaks(
    tmp_path: Path, processor
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "project": {
                    "prj_file": str(tmp_path / "Muncie.prj"),
                    "source_path": str(tmp_path / "source"),
                },
                "sourceProject": str(tmp_path / "private" / "project.json"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(processor.ProcessorError, match=r"\$\.sourceProject"):
        processor.sanitize_public_manifest(manifest_path, local_roots=[tmp_path])

    manifest_path.write_text(
        json.dumps(
            {
                "project": {
                    "prj_file": str(tmp_path / "Muncie.prj"),
                    "source_path": str(tmp_path / "source"),
                },
                "sourceProject": "../project.json",
            }
        ),
        encoding="utf-8",
    )
    sanitized = processor.sanitize_public_manifest(manifest_path, local_roots=[tmp_path])
    assert sanitized == {
        "project": {"prj_file": "Muncie.prj"},
        "sourceProject": "../project.json",
    }


def test_recursive_project_discovery_is_not_allowed(tmp_path: Path, processor) -> None:
    root = tmp_path / "project"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "Hidden.prj").write_text("hidden", encoding="ascii")
    config = {
        "source": {"id": "source"},
        "project": {"id": "hidden", "primary_geometry": "g01"},
        "output_root": "output",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(processor.ProcessorError, match="found 0"):
        processor.build_context(config_path, root)


def test_command_failure_is_written_to_atomic_status(tmp_path: Path, processor) -> None:
    project_file = tmp_path / "project" / "Muncie.prj"
    config_path, project_root, output_root = write_config(
        tmp_path,
        extract={"plans": ["p03"]},
    )
    fake = FakeRas2cng(inspection(project_file), fail_command="map")

    with pytest.raises(processor.ProcessorError, match="forced failure"):
        processor.process_project(
            config_path=config_path,
            project_root=project_root,
            mode="extract",
            runner=fake,
        )

    status = json.loads((output_root / "processor-status.json").read_text())
    assert status["state"] == "failed"
    assert status["errors"][0]["phase"] == "extract"
    assert status["phases"]["extract"]["outputs"][1]["returnCode"] == 9
    assert status["phases"]["extract"]["outputs"][1]["stderr"] == "forced failure"
    assert status["phases"]["extract"]["errors"]
    archive = json.loads((output_root / "archive" / "manifest.json").read_text())
    assert "source_path" not in archive["project"]
    assert "archive_path" not in archive["project"]
