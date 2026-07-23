"""Attach another example project's terrain as explicit display context."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urljoin


def attach_shared_terrain(
    target: dict,
    source: dict,
    *,
    source_manifest_url: str,
    source_project_id: str,
    source_project_title: str,
) -> dict:
    """Return a target manifest with the source terrain linked by hosted URLs."""

    if (
        target.get("schema") == "rascommander.maplibre/v2"
        and source.get("schema") == "rascommander.maplibre/v2"
    ):
        return _attach_shared_terrain_v2(
            target,
            source,
            source_manifest_url=source_manifest_url,
            source_project_id=source_project_id,
            source_project_title=source_project_title,
        )

    terrain = next(
        (
            item
            for item in source.get("tilesets", [])
            if item.get("type") == "raster"
            and (
                item.get("sourceKind") == "terrain"
                or item.get("groupId") == "ras-terrains"
                or item.get("id") == "terrain"
            )
        ),
        None,
    )
    if terrain is None:
        raise ValueError("Source manifest does not contain a terrain tileset")

    shared = copy.deepcopy(terrain)
    shared["id"] = f"shared-terrain-{source_project_id}"
    shared["name"] = f"Shared Terrain ({source_project_title})"
    shared["groupId"] = "ras-terrains"
    shared["sourceKind"] = "terrain"
    shared["visible"] = True
    shared["href"] = urljoin(source_manifest_url, terrain["href"])
    if terrain.get("sourceCog"):
        shared["sourceCog"] = urljoin(source_manifest_url, terrain["sourceCog"])
    shared["sharedDisplayResource"] = {
        "sourceProjectId": source_project_id,
        "sourceProjectTitle": source_project_title,
        "modelOwned": False,
        "purpose": "display-context",
    }
    shared.setdefault("storedMap", {}).update(
        {
            "sharedFromProject": source_project_id,
            "modelOwned": False,
            "purpose": "display-context",
        }
    )

    result = copy.deepcopy(target)
    result["tilesets"] = [
        item
        for item in result.get("tilesets", [])
        if item.get("id") != shared["id"]
    ]
    result["tilesets"].append(shared)
    groups = result.setdefault("groups", [])
    if not any(group.get("id") == "ras-terrains" for group in groups):
        groups.append({"id": "ras-terrains", "name": "Terrains", "visible": True})
    result["sharedDisplayResources"] = [
        item
        for item in result.get("sharedDisplayResources", [])
        if item.get("layerId") != shared["id"]
    ]
    result["sharedDisplayResources"].append(
        {
            "layerId": shared["id"],
            **shared["sharedDisplayResource"],
        }
    )
    return result


def _attach_shared_terrain_v2(
    target: dict,
    source: dict,
    *,
    source_manifest_url: str,
    source_project_id: str,
    source_project_title: str,
) -> dict:
    source_layer_id, source_layer = next(
        (
            (layer_id, layer)
            for layer_id, layer in source.get("layers", {}).items()
            if layer.get("sourceKind") == "terrain" or layer.get("role") == "terrain"
        ),
        (None, None),
    )
    if source_layer is None:
        raise ValueError("Source manifest does not contain a terrain layer")

    layer_id = f"shared-terrain-{source_project_id}"
    display_resource_id = f"{layer_id}-display"
    numeric_resource_id = f"{layer_id}-numeric"
    legend_id = f"legend-{layer_id}"

    result = copy.deepcopy(target)
    layer = copy.deepcopy(source_layer)
    source_display_resource = source.get("resources", {}).get(source_layer["resource"], {})
    display_resource = copy.deepcopy(source_display_resource)
    display_resource["href"] = urljoin(source_manifest_url, source_display_resource["href"])
    result.setdefault("resources", {})[display_resource_id] = display_resource
    layer["resource"] = display_resource_id

    source_numeric_id = source_layer.get("query", {}).get("numericResource")
    if source_numeric_id:
        source_numeric_resource = source.get("resources", {}).get(source_numeric_id, {})
        numeric_resource = copy.deepcopy(source_numeric_resource)
        numeric_resource["href"] = urljoin(source_manifest_url, source_numeric_resource["href"])
        result["resources"][numeric_resource_id] = numeric_resource
        layer.setdefault("query", {})["numericResource"] = numeric_resource_id

    source_legend_id = source_layer.get("style", {}).get("legendRef")
    if source_legend_id:
        result.setdefault("legends", {})[legend_id] = copy.deepcopy(
            source.get("legends", {}).get(source_legend_id, {})
        )
        layer.setdefault("style", {})["legendRef"] = legend_id

    layer["name"] = f"Shared Terrain ({source_project_title})"
    layer["visible"] = True
    layer["groupId"] = "ras-terrains"
    layer["provenance"] = {
        **(layer.get("provenance") or {}),
        "sharedFromProject": source_project_id,
        "sourceProjectTitle": source_project_title,
        "modelOwned": False,
        "purpose": "display-context",
        "sourceLayerId": source_layer_id,
    }
    result.setdefault("layers", {})[layer_id] = layer

    terrains = next(
        (node for node in result.setdefault("tree", []) if node.get("id") == "terrains"),
        None,
    )
    if terrains is None:
        terrains = {
            "id": "terrains",
            "name": "Terrains",
            "role": "terrains",
            "children": [],
        }
        result["tree"].append(terrains)
    terrains["children"] = [
        child for child in terrains.get("children", []) if child.get("layerId") != layer_id
    ]
    terrains["children"].append(
        {
            "id": f"layer-{layer_id}",
            "name": layer["name"],
            "role": "terrain",
            "layerId": layer_id,
        }
    )

    result["sharedDisplayResources"] = [
        item
        for item in result.get("sharedDisplayResources", [])
        if item.get("layerId") != layer_id
    ]
    result["sharedDisplayResources"].append(
        {
            "layerId": layer_id,
            "sourceProjectId": source_project_id,
            "sourceProjectTitle": source_project_title,
            "modelOwned": False,
            "purpose": "display-context",
        }
    )

    source_compatibility = next(
        (
            item
            for item in source.get("tilesets", [])
            if item.get("id") == source_layer_id
            or item.get("sourceKind") == "terrain"
            or item.get("groupId") == "ras-terrains"
        ),
        None,
    )
    if source_compatibility:
        compatibility = copy.deepcopy(source_compatibility)
        compatibility["id"] = layer_id
        compatibility["name"] = layer["name"]
        compatibility["visible"] = True
        compatibility["href"] = display_resource["href"]
        if numeric_resource_id in result["resources"]:
            compatibility["sourceCog"] = result["resources"][numeric_resource_id]["href"]
        compatibility["sharedDisplayResource"] = result["sharedDisplayResources"][-1]
        result["tilesets"] = [
            item for item in result.get("tilesets", []) if item.get("id") != layer_id
        ]
        result["tilesets"].append(compatibility)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest-url", required=True)
    parser.add_argument("--source-project-id", required=True)
    parser.add_argument("--source-project-title", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    target = json.loads(args.target_manifest.read_text(encoding="utf-8"))
    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    updated = attach_shared_terrain(
        target,
        source,
        source_manifest_url=args.source_manifest_url,
        source_project_id=args.source_project_id,
        source_project_title=args.source_project_title,
    )
    output = args.output or args.target_manifest
    output.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
