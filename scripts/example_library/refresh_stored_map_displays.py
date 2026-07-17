#!/usr/bin/env python
"""Refresh Stored Map display PMTiles without changing authoritative COGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


Packager = Callable[..., Any]


class RefreshError(RuntimeError):
    """Raised when a Stored Map display cannot be refreshed safely."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RefreshError(f"Could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RefreshError(f"Expected a JSON object: {path}")
    return value


def stored_map_tilesets(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return Stored Map raster tilesets in stable identifier order."""

    return sorted(
        (
            dict(item)
            for item in manifest.get("tilesets", [])
            if isinstance(item, dict)
            and item.get("type") == "raster"
            and item.get("sourceKind") == "stored-map"
        ),
        key=lambda item: str(item.get("id") or ""),
    )


def _local_source_cog(viewer_dir: Path, source_cog: Any) -> Path:
    value = str(source_cog or "").strip()
    if not value or "://" in value:
        raise RefreshError(f"Stored Map sourceCog must be manifest-relative: {value!r}")
    path = (viewer_dir / value).resolve()
    if not path.is_file():
        raise RefreshError(f"Stored Map numeric COG does not exist: {path}")
    return path


def refresh_project(
    project_dir: Path,
    *,
    max_zoom: int,
    scratch_root: Path,
    packager: Packager | None = None,
) -> dict[str, Any]:
    """Refresh every Stored Map display derivative in one staged project."""

    if max_zoom < 0:
        raise RefreshError("max_zoom must be zero or greater")
    project_dir = Path(project_dir)
    viewer_dir = project_dir / "viewer"
    manifest_path = viewer_dir / "manifest.json"
    manifest = read_json(manifest_path)
    tilesets = stored_map_tilesets(manifest)
    if not tilesets:
        return {"project": project_dir.name, "refreshed": 0, "maxZoom": max_zoom}

    if packager is None:
        from ras2cng.maplibre import package_maplibre_stored_map

        packager = package_maplibre_stored_map

    refreshed: list[str] = []
    for tileset in tilesets:
        layer_id = str(tileset.get("id") or "").strip()
        metadata = tileset.get("storedMap")
        if not layer_id or not isinstance(metadata, dict):
            raise RefreshError(f"Stored Map tileset lacks semantic metadata: {layer_id!r}")
        source_cog = str(tileset.get("sourceCog") or "")
        packager(
            _local_source_cog(viewer_dir, source_cog),
            viewer_dir,
            plan=str(metadata.get("plan") or ""),
            map_type=str(metadata.get("mapType") or ""),
            name=str(tileset.get("name") or layer_id),
            profile=str(metadata.get("profile") or "Max"),
            geometry=str(metadata.get("geometry") or "") or None,
            layer_id=layer_id,
            source_cog=source_cog,
            units=str(tileset.get("units") or ""),
            visible=bool(tileset.get("visible")),
            domain_policy=str(tileset.get("domainPolicy") or "fixed"),
            max_zoom=max_zoom,
            scratch_dir=Path(scratch_root) / project_dir.name / layer_id,
            overwrite=True,
        )
        refreshed.append(layer_id)

    updated = read_json(manifest_path)
    updated_tilesets = {str(item.get("id")): item for item in stored_map_tilesets(updated)}
    violations = [
        layer_id
        for layer_id in refreshed
        if int(updated_tilesets.get(layer_id, {}).get("maxzoom", max_zoom + 1)) > max_zoom
    ]
    if violations:
        raise RefreshError(
            "Refreshed displays exceed the requested maximum zoom: " + ", ".join(violations)
        )
    return {
        "project": project_dir.name,
        "refreshed": len(refreshed),
        "maxZoom": max_zoom,
        "layers": refreshed,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", type=Path, required=True)
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--max-zoom", type=int, default=16)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--status", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected = args.project or sorted(
        path.name for path in args.projects_root.iterdir() if path.is_dir()
    )
    projects: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for project_id in selected:
        try:
            result = refresh_project(
                args.projects_root / project_id,
                max_zoom=args.max_zoom,
                scratch_root=args.scratch_root,
            )
            projects.append(result)
            print(f"OK {project_id}: refreshed {result['refreshed']}", flush=True)
        except Exception as error:  # noqa: BLE001 - preserve all project failures
            errors.append({"project": project_id, "error": str(error)})
            print(f"ERROR {project_id}: {error}", flush=True)
            if not args.continue_on_error:
                break

    report = {
        "schema": "rascommander.stored-map-display-refresh/v1",
        "projects": projects,
        "errors": errors,
    }
    if args.status:
        args.status.parent.mkdir(parents=True, exist_ok=True)
        args.status.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
