#!/usr/bin/env python
"""Prepare a terrain-only WebGIS delta for RAS example project viewers.

The worker-staged terrain bundles are intentionally kept separate from the
public artifact tree. This utility copies only the viewer terrain overlays and,
for source terrains archived during this release, merges the generated terrain
catalog entries into the current public archive manifest. It never edits the
landing-page catalog or replaces unrelated project artifacts.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_PUBLIC_BASE = "https://rascommander.info/data/rasexamples/hec-ras-7.0"


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "rascommander-terrain-release/1.0"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - caller controls public base.
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {url}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required staged artifact is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def terrain_tileset(manifest: dict[str, Any], label: str) -> dict[str, Any]:
    tilesets = manifest.get("tilesets")
    if not isinstance(tilesets, list):
        raise ValueError(f"{label} viewer manifest has no tilesets list")
    matches = [item for item in tilesets if isinstance(item, dict) and item.get("id") == "terrain"]
    if len(matches) != 1:
        raise ValueError(f"{label} viewer manifest must contain exactly one terrain tileset")
    return matches[0]


def validate_terrain_manifest(manifest: dict[str, Any], label: str) -> int:
    terrain = terrain_tileset(manifest, label)
    if terrain.get("visible") is not True:
        raise ValueError(f"{label} terrain must default visible")
    if terrain.get("groupId") != "ras-terrains":
        raise ValueError(f"{label} terrain must use the ras-terrains group")
    if terrain.get("queryable") is not True:
        raise ValueError(f"{label} terrain must be queryable")
    source_cog = terrain.get("sourceCog")
    if not isinstance(source_cog, str) or not source_cog.startswith("../archive/terrain/"):
        raise ValueError(f"{label} terrain must have a project archive source COG")
    bytes_value = terrain.get("bytes")
    if not isinstance(bytes_value, int) or bytes_value <= 0:
        raise ValueError(f"{label} terrain PMTiles byte count is invalid")
    return bytes_value


def copy_staged_project(staging_root: Path, output_root: Path, public_base: str, project_id: str) -> int:
    staged_project = staging_root / project_id
    destination = output_root / "projects" / project_id
    staged_viewer = staged_project / "viewer"
    viewer_manifest = read_json(staged_viewer / "manifest.json")
    bytes_value = validate_terrain_manifest(viewer_manifest, project_id)
    copy_required(staged_viewer / "manifest.json", destination / "viewer" / "manifest.json")
    copy_required(
        staged_viewer / "tiles" / "terrain.pmtiles",
        destination / "viewer" / "tiles" / "terrain.pmtiles",
    )

    generated_manifest = staged_project / "archive" / "ras2cng-terrain-manifest.json"
    if generated_manifest.is_file():
        generated = read_json(generated_manifest)
        terrain_entries = generated.get("terrain")
        if not isinstance(terrain_entries, list) or not terrain_entries:
            raise ValueError(f"{project_id} generated archive has no terrain entries")
        public_archive = fetch_json(f"{public_base}/projects/{project_id}/archive/manifest.json")
        public_archive["terrain"] = terrain_entries
        write_json(destination / "archive" / "manifest.json", public_archive)
        for entry in terrain_entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("cog_file"), str):
                raise ValueError(f"{project_id} generated terrain entry is invalid")
            source = staged_project / "archive" / entry["cog_file"]
            copy_required(source, destination / "archive" / entry["cog_file"])
    return bytes_value


def patch_public_viewer(
    output_root: Path,
    public_base: str,
    project_id: str,
    source_cog: str,
) -> int:
    manifest = fetch_json(f"{public_base}/projects/{project_id}/viewer/manifest.json")
    terrain = terrain_tileset(manifest, project_id)
    terrain["sourceCog"] = source_cog
    terrain["groupId"] = "ras-terrains"
    terrain["visible"] = True
    terrain["queryable"] = True
    terrain.setdefault("units", "ft")
    bytes_value = validate_terrain_manifest(manifest, project_id)
    write_json(output_root / "projects" / project_id / "viewer" / "manifest.json", manifest)
    return bytes_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--project", action="append", default=[], help="Staged project ID; repeat.")
    parser.add_argument(
        "--patch-source-cog",
        action="append",
        default=[],
        metavar="PROJECT_ID=HREF",
        help="Patch a published viewer terrain source COG; repeat.",
    )
    parser.add_argument("--public-base", default=DEFAULT_PUBLIC_BASE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    staging_root = args.staging_root.resolve()
    output_root = args.output_root.resolve()
    if not staging_root.is_dir():
        raise FileNotFoundError(f"Staging root does not exist: {staging_root}")
    if output_root.name != "hec-ras-7.0":
        raise ValueError(f"Output root must be named hec-ras-7.0, got {output_root.name}")

    processed: dict[str, int] = {}
    for project_id in args.project:
        if project_id in processed:
            raise ValueError(f"Duplicate staged project: {project_id}")
        processed[project_id] = copy_staged_project(
            staging_root, output_root, args.public_base.rstrip("/"), project_id
        )
    for patch in args.patch_source_cog:
        project_id, separator, source_cog = patch.partition("=")
        if not separator or not project_id or not source_cog:
            raise ValueError("--patch-source-cog must be PROJECT_ID=HREF")
        if project_id in processed:
            raise ValueError(f"Duplicate project in source COG patch: {project_id}")
        processed[project_id] = patch_public_viewer(
            output_root, args.public_base.rstrip("/"), project_id, source_cog
        )
    if not processed:
        raise ValueError("At least one --project or --patch-source-cog is required")

    total_bytes = sum(processed.values())
    print(f"Prepared {len(processed)} terrain viewer manifests")
    print(f"Terrain PMTiles: {total_bytes:,} bytes")
    for project_id in sorted(processed):
        print(f"  {project_id}: {processed[project_id]:,} bytes")


if __name__ == "__main__":
    main()
