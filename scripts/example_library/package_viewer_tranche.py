#!/usr/bin/env python
"""Rebuild a bounded set of published Example Library viewers as manifest v2.

The command reads only projects named in the archive-metadata report, resolves
their original geometry HDFs through explicit path mappings, and writes a
complete staged project tree. It never computes a HEC-RAS plan or publishes a
release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


class TrancheError(RuntimeError):
    """Raised when a project cannot be packaged without an incomplete bundle."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrancheError(f"Could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise TrancheError(f"Expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _assignments(values: Sequence[str], *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise TrancheError(f"{label} must use NAME=VALUE syntax: {value!r}")
        key, assigned = value.split("=", 1)
        if not key.strip() or not assigned.strip():
            raise TrancheError(f"{label} must use NAME=VALUE syntax: {value!r}")
        result[key.strip()] = assigned.strip()
    return result


def translate_path(raw_path: str, mappings: Mapping[str, str]) -> Path:
    """Translate a Windows/UNC source path through one explicit prefix map."""

    normalized = raw_path.replace("\\", "/").rstrip("/")
    for source, target in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        prefix = source.replace("\\", "/").rstrip("/")
        if normalized.casefold() == prefix.casefold():
            return Path(target)
        marker = f"{prefix}/"
        if normalized.casefold().startswith(marker.casefold()):
            relative = normalized[len(marker) :]
            return Path(target).joinpath(*relative.split("/"))
    raise TrancheError(f"No --path-map matches source project path: {raw_path}")


def infer_primary_geometry(
    viewer: Mapping[str, Any], archive: Mapping[str, Any], explicit: str | None = None
) -> str:
    geometry_ids = [
        str(item.get("geom_id"))
        for item in archive.get("geometry", [])
        if isinstance(item, dict) and item.get("geom_id")
    ]
    if not geometry_ids:
        raise TrancheError("Archive contains no geometry entries")
    if explicit:
        if explicit not in geometry_ids:
            raise TrancheError(f"Primary geometry {explicit} is not in the archive")
        return explicit

    associations = viewer.get("associations")
    if isinstance(associations, dict):
        candidate = associations.get("primaryGeometry")
        if candidate in geometry_ids:
            return str(candidate)

    for group in viewer.get("groups", []):
        if not isinstance(group, dict) or group.get("visible") is not True:
            continue
        match = re.fullmatch(r"ras-geometry-(g\d+)", str(group.get("id") or ""))
        if match and match.group(1) in geometry_ids:
            return match.group(1)
    return geometry_ids[0]


def geometry_hdfs(
    project_file: Path, archive: Mapping[str, Any]
) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for item in archive.get("geometry", []):
        if not isinstance(item, dict) or not item.get("geom_id"):
            continue
        geom_id = str(item["geom_id"])
        path = project_file.with_suffix(f".{geom_id}.hdf")
        if not path.is_file():
            raise TrancheError(f"Geometry HDF does not exist: {geom_id}={path}")
        bindings[geom_id] = path
    if not bindings:
        raise TrancheError("No geometry HDF bindings were resolved")
    return bindings


def _run(command: list[str], *, runner: Runner) -> None:
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise TrancheError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{detail}"
        )


def package_project(
    *,
    project_id: str,
    project_file: Path,
    source_project_dir: Path,
    output_projects_root: Path,
    ras2cng: str,
    scratch_root: Path,
    primary_geometry: str | None = None,
    refreshed_archive: Path | None = None,
    stored_maps: Path | None = None,
    require_all_stored_maps: bool = True,
    overwrite: bool = False,
    validate: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Build one complete staged project, replacing it only after success."""

    archive_source = Path(refreshed_archive) if refreshed_archive else source_project_dir / "archive"
    if not archive_source.is_dir():
        raise TrancheError(f"Archive directory does not exist: {archive_source}")
    archive = _read_json(archive_source / "manifest.json")
    old_viewer = _read_json(source_project_dir / "viewer" / "manifest.json")
    project = _read_json(source_project_dir / "project.json")
    primary = infer_primary_geometry(old_viewer, archive, primary_geometry)
    bindings = geometry_hdfs(project_file, archive)
    title = str(old_viewer.get("title") or project.get("title") or project_id)

    output_projects_root.mkdir(parents=True, exist_ok=True)
    target = output_projects_root / project_id
    working = output_projects_root / f".{project_id}.working"
    if working.exists():
        shutil.rmtree(working)
    if target.exists() and not overwrite:
        raise TrancheError(f"Output project already exists: {target}")
    shutil.copytree(source_project_dir, working)
    if refreshed_archive is not None:
        shutil.rmtree(working / "archive", ignore_errors=True)
        shutil.copytree(archive_source, working / "archive")
    shutil.rmtree(working / "viewer", ignore_errors=True)

    scratch = scratch_root / project_id
    scratch.mkdir(parents=True, exist_ok=True)
    viewer_dir = working / "viewer"
    command = [
        ras2cng,
        "maplibre",
        str(working / "archive"),
        str(viewer_dir),
    ]
    for geom_id, hdf_path in sorted(bindings.items()):
        command.extend(["--geometry-hdf", f"{geom_id}={hdf_path}"])
    command.extend(
        [
            "--vector-results",
            "--primary-geometry",
            primary,
            "--standard-primary-geometry",
            "--title",
            title,
            "--source-project",
            "../project.json",
            "--scratch-dir",
            str(scratch / "viewer"),
        ]
    )
    crs = str(archive.get("project", {}).get("crs") or project.get("crs") or "")
    if crs:
        command.extend(["--crs", crs])
    _run(command, runner=runner)

    terrain_count = 0
    for index, terrain in enumerate(archive.get("terrain", []), start=1):
        if not isinstance(terrain, dict) or not terrain.get("cog_file"):
            continue
        cog_relative = Path(str(terrain["cog_file"]))
        cog_path = working / "archive" / cog_relative
        if not cog_path.is_file():
            raise TrancheError(f"Archived terrain COG does not exist: {cog_path}")
        terrain_command = [
            ras2cng,
            "maplibre-terrain",
            str(cog_path),
            str(viewer_dir),
            "--name",
            str(terrain.get("terrain_name") or f"Terrain {index}"),
            "--source-cog",
            f"../archive/{cog_relative.as_posix()}",
            "--units",
            "ft",
            "--scratch-dir",
            str(scratch / f"terrain-{index}"),
        ]
        if index > 1:
            terrain_command.append("--overwrite")
        _run(terrain_command, runner=runner)
        terrain_count += 1

    if stored_maps is not None:
        if not stored_maps.is_dir():
            raise TrancheError(f"Stored Map directory does not exist: {stored_maps}")
        import_command = [
            ras2cng,
            "maplibre-import-stored-maps",
            str(stored_maps),
            str(working / "archive"),
            str(viewer_dir),
            "--scratch-dir",
            str(scratch / "stored-maps"),
            "--overwrite",
        ]
        import_command.insert(
            -1,
            "--require-all" if require_all_stored_maps else "--allow-partial",
        )
        _run(import_command, runner=runner)

    if validate:
        _run(
            [
                ras2cng,
                "validate-publication",
                str(viewer_dir / "manifest.json"),
                str(working / "archive" / "manifest.json"),
                "--json",
            ],
            runner=runner,
        )

    status = {
        "schema": "rascommander.example-viewer-tranche-status/v1",
        "project": project_id,
        "title": title,
        "primaryGeometry": primary,
        "geometryCount": len(bindings),
        "terrainCount": terrain_count,
        "refreshedArchive": refreshed_archive is not None,
        "storedMapsImported": stored_maps is not None,
        "validated": validate,
    }
    _write_json(working / "viewer-v2-status.json", status)
    if target.exists():
        shutil.rmtree(target)
    os.replace(working, target)
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", type=Path, required=True)
    parser.add_argument("--metadata-report", type=Path, required=True)
    parser.add_argument("--output-projects-root", type=Path, required=True)
    parser.add_argument("--ras2cng", default="ras2cng")
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--primary", action="append", default=[])
    parser.add_argument("--archive", action="append", default=[])
    parser.add_argument("--stored-maps", action="append", default=[])
    parser.add_argument(
        "--allow-partial-stored-maps",
        action="store_true",
        help="Allow incomplete Stored Map sets for diagnostic tranche builds.",
    )
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--status", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path_maps = _assignments(args.path_map, label="--path-map")
    primary = _assignments(args.primary, label="--primary")
    archives = {
        key: Path(value)
        for key, value in _assignments(args.archive, label="--archive").items()
    }
    stored_maps = {
        key: Path(value)
        for key, value in _assignments(args.stored_maps, label="--stored-maps").items()
    }
    report = _read_json(args.metadata_report)
    projects = {
        str(item.get("id")): item
        for item in report.get("projects", [])
        if isinstance(item, dict) and item.get("id")
    }
    selected = args.project or list(projects)
    unknown = sorted(set(selected) - set(projects))
    if unknown:
        raise TrancheError(f"Project(s) absent from metadata report: {', '.join(unknown)}")

    statuses: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for project_id in selected:
        item = projects[project_id]
        try:
            project_file = translate_path(str(item["project"]), path_maps)
            statuses.append(
                package_project(
                    project_id=project_id,
                    project_file=project_file,
                    source_project_dir=args.projects_root / project_id,
                    output_projects_root=args.output_projects_root,
                    ras2cng=args.ras2cng,
                    scratch_root=args.scratch_root,
                    primary_geometry=primary.get(project_id),
                    refreshed_archive=archives.get(project_id),
                    stored_maps=stored_maps.get(project_id),
                    require_all_stored_maps=not args.allow_partial_stored_maps,
                    overwrite=args.overwrite,
                    validate=args.validate,
                )
            )
            print(f"OK {project_id}", flush=True)
        except Exception as error:  # noqa: BLE001 - tranche report preserves each failure
            errors.append({"project": project_id, "error": str(error)})
            print(f"ERROR {project_id}: {error}", file=sys.stderr, flush=True)
            if not args.continue_on_error:
                break

    result = {
        "schema": "rascommander.example-viewer-tranche-report/v1",
        "projects": statuses,
        "errors": errors,
    }
    status_path = args.status or args.output_projects_root.parent / "viewer-v2-report.json"
    _write_json(status_path, result)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
