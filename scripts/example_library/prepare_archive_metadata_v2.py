#!/usr/bin/env python
"""Add source titles and publication-safe paths to existing ras2cng archives."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.example_library.upgrade_viewer_contract import (
    project_metadata,
    read_json,
    update_archive_metadata,
    write_json,
)


WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
POSIX_LOCAL_PREFIXES = ("/mnt/", "/home/", "/tmp/", "/var/tmp/", "/Users/", "/Volumes/")


def resolve_project_file(source_root: Path, project: dict[str, Any]) -> Path:
    relative_hdf = project.get("geometry_hdf") or (project.get("geometry_hdfs") or [None])[0]
    if not relative_hdf:
        raise ValueError(f"Project {project.get('id')} has no geometry HDF")
    hdf_path = (source_root / str(relative_hdf)).resolve()
    match = re.match(r"^(?P<stem>.+)\.g\d\d\.hdf$", hdf_path.name, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Geometry HDF does not use a canonical name: {hdf_path}")
    project_file = hdf_path.with_name(f"{match.group('stem')}.prj")
    if not project_file.is_file():
        raise FileNotFoundError(f"Project file for archive metadata was not found: {project_file}")
    return project_file


def _is_local_path(value: str) -> bool:
    return bool(
        WINDOWS_ABSOLUTE.match(value)
        or value.startswith("\\\\")
        or value.startswith(POSIX_LOCAL_PREFIXES)
        or value.startswith("file:")
    )


def redact_local_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_local_paths(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_local_paths(child) for child in value]
    if isinstance(value, str) and _is_local_path(value):
        normalized = value.replace("\\", "/")
        return PureWindowsPath(normalized).name or Path(normalized).name
    return value


def prepare_archive(
    *,
    project: dict[str, Any],
    source_root: Path,
    artifact_root: Path,
    schema_version: str,
) -> dict[str, Any]:
    project_file = resolve_project_file(source_root, project)
    archive_path = artifact_root / "projects" / project["id"] / "archive" / "manifest.json"
    archive = read_json(archive_path)
    geometry_titles, plans = project_metadata(project_file)
    update_archive_metadata(
        archive,
        geometry_titles=geometry_titles,
        plan_metadata=plans,
        schema_version=schema_version,
    )
    archive = redact_local_paths(archive)
    metadata = archive.setdefault("project", {})
    metadata["source_path"] = f"{project.get('source_family', 'public')}:{project['id']}"
    metadata["archive_path"] = "."
    metadata["local_paths_redacted"] = True
    write_json(archive_path, archive)
    return {
        "id": project["id"],
        "project": str(project_file),
        "archive": str(archive_path),
        "geometry_titles": geometry_titles,
        "plans": plans,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--project-id", action="append")
    parser.add_argument("--schema-version", default="2.6")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = read_json(args.catalog)
    selected = set(args.project_id or [])
    reports = [
        prepare_archive(
            project=project,
            source_root=args.source_root,
            artifact_root=args.artifact_root,
            schema_version=args.schema_version,
        )
        for project in catalog.get("projects", [])
        if project.get("title") != "Muncie" and (not selected or project.get("id") in selected)
    ]
    payload = {"schema": "rascommander.archive-metadata-upgrade/1", "projects": reports}
    if args.report:
        write_json(args.report, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
