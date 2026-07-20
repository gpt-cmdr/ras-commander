from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "package_viewer_tranche.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("package_viewer_tranche", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_translate_path_uses_longest_case_insensitive_prefix() -> None:
    module = load_script()
    translated = module.translate_path(
        r"\\192.168.3.20\CLB-Engineering\Models\Muncie.prj",
        {
            r"\\192.168.3.20\CLB-Engineering": "/mnt/clb",
            r"\\192.168.3.20\CLB-Engineering\Models": "/mnt/models",
        },
    )
    assert translated == Path("/mnt/models/Muncie.prj")


def test_infer_primary_geometry_uses_visible_legacy_group() -> None:
    module = load_script()
    viewer = {
        "groups": [
            {"id": "ras-geometry-g01", "visible": False},
            {"id": "ras-geometry-g02", "visible": True},
        ]
    }
    archive = {"geometry": [{"geom_id": "g01"}, {"geom_id": "g02"}]}
    assert module.infer_primary_geometry(viewer, archive) == "g02"


def test_package_project_builds_vector_viewer_and_terrain(tmp_path: Path) -> None:
    module = load_script()
    source = tmp_path / "source" / "muncie"
    archive = source / "archive"
    viewer = source / "viewer"
    archive.mkdir(parents=True)
    viewer.mkdir()
    project_file = tmp_path / "model" / "Muncie.prj"
    project_file.parent.mkdir()
    project_file.write_text("Proj Title=Muncie\n", encoding="ascii")
    project_file.with_suffix(".g01.hdf").write_bytes(b"hdf")
    terrain = archive / "terrain" / "terrain.cog.tif"
    terrain.parent.mkdir()
    terrain.write_bytes(b"cog")
    (archive / "manifest.json").write_text(
        json.dumps(
            {
                "project": {"crs": "EPSG:2965"},
                "geometry": [{"geom_id": "g01"}],
                "terrain": [
                    {"terrain_name": "TerrainWithChannel", "cog_file": "terrain/terrain.cog.tif"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (viewer / "manifest.json").write_text(
        json.dumps(
            {
                "title": "Muncie",
                "groups": [{"id": "ras-geometry-g01", "visible": True}],
            }
        ),
        encoding="utf-8",
    )
    (source / "project.json").write_text(
        json.dumps({"title": "Muncie", "crs": "EPSG:2965"}), encoding="utf-8"
    )
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        if command[1] == "maplibre":
            output = Path(command[3])
            output.mkdir(parents=True)
            (output / "manifest.json").write_text(
                json.dumps({"schema": "rascommander.maplibre/v2"}), encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    status = module.package_project(
        project_id="muncie",
        project_file=project_file,
        source_project_dir=source,
        output_projects_root=tmp_path / "output" / "projects",
        ras2cng="ras2cng",
        scratch_root=tmp_path / "scratch",
        overwrite=True,
        runner=runner,
    )

    assert [command[1] for command in calls] == ["maplibre", "maplibre-terrain"]
    assert "--vector-results" in calls[0]
    assert "--standard-primary-geometry" in calls[0]
    assert calls[0][calls[0].index("--primary-geometry") + 1] == "g01"
    assert calls[1][calls[1].index("--source-cog") + 1] == "../archive/terrain/terrain.cog.tif"
    assert status["terrainCount"] == 1
    assert status["refreshedArchive"] is False
    assert (tmp_path / "output" / "projects" / "muncie" / "viewer-v2-status.json").is_file()


def test_package_project_atomically_overlays_refreshed_archive(tmp_path: Path) -> None:
    module = load_script()
    source = tmp_path / "source" / "muncie"
    stale_archive = source / "archive"
    viewer = source / "viewer"
    stale_archive.mkdir(parents=True)
    viewer.mkdir()
    (stale_archive / "manifest.json").write_text(
        json.dumps({"project": {"crs": "EPSG:2965"}, "geometry": [{"geom_id": "g01"}]}),
        encoding="utf-8",
    )
    (viewer / "manifest.json").write_text(
        json.dumps({"title": "Muncie", "groups": []}), encoding="utf-8"
    )
    (source / "project.json").write_text(
        json.dumps({"title": "Muncie", "crs": "EPSG:2965"}), encoding="utf-8"
    )

    refreshed = tmp_path / "refreshed" / "archive"
    refreshed_terrain = refreshed / "terrain" / "fresh.cog.tif"
    refreshed_terrain.parent.mkdir(parents=True)
    refreshed_terrain.write_bytes(b"fresh-cog")
    (refreshed / "manifest.json").write_text(
        json.dumps(
            {
                "project": {"crs": "EPSG:2965"},
                "geometry": [{"geom_id": "g02"}],
                "terrain": [
                    {"terrain_name": "Fresh Terrain", "cog_file": "terrain/fresh.cog.tif"}
                ],
            }
        ),
        encoding="utf-8",
    )
    project_file = tmp_path / "model" / "Muncie.prj"
    project_file.parent.mkdir()
    project_file.write_text("Proj Title=Muncie\n", encoding="ascii")
    project_file.with_suffix(".g02.hdf").write_bytes(b"hdf")
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        if command[1] == "maplibre":
            output = Path(command[3])
            output.mkdir(parents=True)
            (output / "manifest.json").write_text(
                json.dumps({"schema": "rascommander.maplibre/v2"}), encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    status = module.package_project(
        project_id="muncie",
        project_file=project_file,
        source_project_dir=source,
        output_projects_root=tmp_path / "output" / "projects",
        ras2cng="ras2cng",
        scratch_root=tmp_path / "scratch",
        refreshed_archive=refreshed,
        overwrite=True,
        runner=runner,
    )

    target = tmp_path / "output" / "projects" / "muncie"
    assert calls[0][calls[0].index("--geometry-hdf") + 1].startswith("g02=")
    assert calls[1][calls[1].index("--source-cog") + 1] == "../archive/terrain/fresh.cog.tif"
    assert (target / "archive" / "terrain" / "fresh.cog.tif").read_bytes() == b"fresh-cog"
    assert not (target / "archive" / "stale.txt").exists()
    assert status["refreshedArchive"] is True


def test_package_project_requires_complete_stored_maps_by_default(tmp_path: Path) -> None:
    module = load_script()
    source = tmp_path / "source" / "muncie"
    archive = source / "archive"
    viewer = source / "viewer"
    stored_maps = tmp_path / "stored-maps"
    archive.mkdir(parents=True)
    viewer.mkdir()
    stored_maps.mkdir()
    project_file = tmp_path / "model" / "Muncie.prj"
    project_file.parent.mkdir()
    project_file.write_text("Proj Title=Muncie\n", encoding="ascii")
    project_file.with_suffix(".g01.hdf").write_bytes(b"hdf")
    (archive / "manifest.json").write_text(
        json.dumps({"project": {"crs": "EPSG:2965"}, "geometry": [{"geom_id": "g01"}]}),
        encoding="utf-8",
    )
    (viewer / "manifest.json").write_text(
        json.dumps({"title": "Muncie", "groups": []}), encoding="utf-8"
    )
    (source / "project.json").write_text(
        json.dumps({"title": "Muncie", "crs": "EPSG:2965"}), encoding="utf-8"
    )
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        if command[1] == "maplibre":
            output = Path(command[3])
            output.mkdir(parents=True)
            (output / "manifest.json").write_text(
                json.dumps({"schema": "rascommander.maplibre/v2"}), encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    module.package_project(
        project_id="muncie",
        project_file=project_file,
        source_project_dir=source,
        output_projects_root=tmp_path / "output" / "projects",
        ras2cng="ras2cng",
        scratch_root=tmp_path / "scratch",
        stored_maps=stored_maps,
        overwrite=True,
        runner=runner,
    )

    import_command = next(command for command in calls if command[1] == "maplibre-import-stored-maps")
    assert "--require-all" in import_command
    assert "--allow-partial" not in import_command
