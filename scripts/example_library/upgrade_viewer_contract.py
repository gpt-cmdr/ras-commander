#!/usr/bin/env python
"""Upgrade existing Example Library manifests without rebuilding GIS assets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


def geometry_label(geometry_id: str, title: str = "") -> str:
    normalized = geometry_id.strip().lower()
    number = normalized[1:] if normalized.startswith("g") else normalized
    label = f"Geometry {number}"
    return f"{label} - {title.strip()}" if title.strip() else label


def update_archive_metadata(
    archive: dict[str, Any],
    *,
    geometry_titles: Mapping[str, str],
    plan_metadata: Mapping[str, Mapping[str, str]],
    schema_version: str,
) -> None:
    archive["schema_version"] = schema_version
    for entry in archive.get("geometry", []):
        geometry_id = str(entry.get("geom_id") or "").lower()
        if geometry_id in geometry_titles:
            entry["geom_title"] = geometry_titles[geometry_id]
    for entry in archive.get("results", []):
        plan_id = str(entry.get("plan_id") or "").lower()
        metadata = plan_metadata.get(plan_id)
        if not metadata:
            continue
        if metadata.get("plan_title"):
            entry["plan_title"] = metadata["plan_title"]
        if metadata.get("geom_id"):
            entry["geom_id"] = metadata["geom_id"]


def apply_geometry_visibility(
    viewer: dict[str, Any],
    *,
    primary_geometry: str,
    show_all_primary_geometry: bool,
    geometry_titles: Mapping[str, str],
) -> None:
    primary_group = f"ras-geometry-{primary_geometry.lower()}"
    for group in viewer.get("groups", []):
        group_id = str(group.get("id") or "")
        if not group_id.startswith("ras-geometry-"):
            continue
        geometry_id = group_id.removeprefix("ras-geometry-")
        group["name"] = geometry_label(geometry_id, geometry_titles.get(geometry_id, ""))
        group["visible"] = group_id == primary_group

    for tileset in viewer.get("tilesets", []):
        if tileset.get("type") != "vector":
            continue
        for layer in tileset.get("layers", []):
            group_id = str(layer.get("groupId") or "")
            if not group_id.startswith("ras-geometry-"):
                continue
            if group_id != primary_group:
                layer["visible"] = False
            elif show_all_primary_geometry:
                layer["visible"] = True


def _metadata_text(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return "" if text.casefold() in {"nan", "nat", "none", "<na>"} else text


def _numbered_id(prefix: str, value: Any) -> str:
    text = _metadata_text(value)
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    return f"{prefix}{int(match.group(1)):02d}" if match else ""


def project_metadata(project_path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    from ras_commander import init_ras_project

    ras = init_ras_project(
        project_path.parent,
        ras_object="new",
        load_results_summary=False,
    )
    geometry_titles: dict[str, str] = {}
    for _, row in ras.geom_df.iterrows():
        geometry_id = _numbered_id("g", row.get("geom_number"))
        if geometry_id:
            geometry_titles[geometry_id] = _metadata_text(row.get("geom_title"))

    plan_metadata: dict[str, dict[str, str]] = {}
    for _, row in ras.plan_df.iterrows():
        plan_id = _numbered_id("p", row.get("plan_number"))
        if not plan_id:
            continue
        plan_title = _metadata_text(row.get("Plan Title")) or _metadata_text(
            row.get("plan_title")
        )
        plan_metadata[plan_id] = {
            "plan_title": plan_title,
            "geom_id": _numbered_id("g", row.get("geometry_number")),
        }
    return geometry_titles, plan_metadata


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-project-root", type=Path, required=True)
    parser.add_argument("--primary-geometry", required=True)
    parser.add_argument("--all-primary-geometry", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from ras2cng.catalog import SCHEMA_VERSION
    from ras2cng.viewer_manifest import apply_manifest_v2, validate_manifest_v2

    archive_path = args.source_project_root / "archive" / "manifest.json"
    viewer_path = args.source_project_root / "viewer" / "manifest.json"
    archive = read_json(archive_path)
    viewer = read_json(viewer_path)
    geometry_titles, plan_metadata = project_metadata(args.project.resolve())
    update_archive_metadata(
        archive,
        geometry_titles=geometry_titles,
        plan_metadata=plan_metadata,
        schema_version=SCHEMA_VERSION,
    )
    apply_geometry_visibility(
        viewer,
        primary_geometry=args.primary_geometry,
        show_all_primary_geometry=args.all_primary_geometry,
        geometry_titles=geometry_titles,
    )
    apply_manifest_v2(viewer, archive=archive)
    validate_manifest_v2(viewer)

    write_json(args.output_project_root / "archive" / "manifest.json", archive)
    write_json(args.output_project_root / "viewer" / "manifest.json", viewer)
    visible_geometry = sorted(
        layer_id
        for layer_id, layer in viewer["layers"].items()
        if layer.get("sourceKind") == "geometry" and layer.get("visible")
    )
    result_plans = [
        {
            "name": node["name"],
            **node.get("metadata", {}),
        }
        for root in viewer["tree"]
        if root.get("id") == "results"
        for node in root.get("children", [])
    ]
    print(
        json.dumps(
            {
                "schemaVersion": viewer["schema"],
                "archiveSchemaVersion": archive["schema_version"],
                "visibleGeometryLayers": visible_geometry,
                "resultPlans": result_plans,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
