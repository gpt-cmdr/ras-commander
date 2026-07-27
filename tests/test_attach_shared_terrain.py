from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "attach_shared_terrain.py"
)
SPEC = importlib.util.spec_from_file_location("attach_shared_terrain", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_attach_shared_terrain_uses_hosted_urls_and_explicit_provenance() -> None:
    target = {
        "schema": "rascommander.maplibre.project/1",
        "tilesets": [{"id": "geometry", "type": "vector"}],
        "groups": [{"id": "ras-geometry-g01", "name": "Geometry g01"}],
    }
    source = {
        "tilesets": [
            {
                "id": "terrain",
                "name": "Terrain",
                "type": "raster",
                "href": "tiles/terrain.pmtiles?v=1",
                "sourceCog": "../archive/terrain/terrain.cog.tif",
                "groupId": "ras-terrains",
                "visible": True,
                "storedMap": {"mapType": "terrain"},
            }
        ]
    }

    result = module.attach_shared_terrain(
        target,
        source,
        source_manifest_url=(
            "https://rascommander.info/data/projects/multi/viewer/manifest.json"
        ),
        source_project_id="multi",
        source_project_title="Multi2D",
    )

    terrain = result["tilesets"][-1]
    assert terrain["href"] == (
        "https://rascommander.info/data/projects/multi/viewer/tiles/terrain.pmtiles?v=1"
    )
    assert terrain["sourceCog"] == (
        "https://rascommander.info/data/projects/multi/archive/terrain/terrain.cog.tif"
    )
    assert terrain["visible"] is True
    assert terrain["sharedDisplayResource"] == {
        "sourceProjectId": "multi",
        "sourceProjectTitle": "Multi2D",
        "modelOwned": False,
        "purpose": "display-context",
    }
    assert result["sharedDisplayResources"][0]["layerId"] == "shared-terrain-multi"
    assert any(group["id"] == "ras-terrains" for group in result["groups"])


def test_attach_shared_terrain_updates_manifest_v2_tree_and_resources() -> None:
    target = {
        "schema": "rascommander.maplibre/v2",
        "resources": {},
        "layers": {},
        "legends": {},
        "tree": [{"id": "geometries", "children": []}],
        "tilesets": [],
    }
    source = {
        "schema": "rascommander.maplibre/v2",
        "resources": {
            "terrain-display": {
                "type": "raster-pmtiles",
                "href": "tiles/terrain.pmtiles",
            },
            "terrain-numeric": {
                "type": "cog",
                "href": "../archive/terrain/terrain.cog.tif",
            },
        },
        "layers": {
            "terrain": {
                "name": "Terrain50",
                "resource": "terrain-display",
                "role": "terrain",
                "sourceKind": "terrain",
                "visible": True,
                "style": {"legendRef": "legend-terrain"},
                "query": {"numericResource": "terrain-numeric"},
                "provenance": {"source": "HEC-RAS terrain GeoTIFF"},
            }
        },
        "legends": {"legend-terrain": {"type": "continuous"}},
        "tilesets": [
            {
                "id": "terrain",
                "type": "raster",
                "href": "tiles/terrain.pmtiles",
                "sourceCog": "../archive/terrain/terrain.cog.tif",
                "groupId": "ras-terrains",
            }
        ],
    }

    result = module.attach_shared_terrain(
        target,
        source,
        source_manifest_url="https://example.test/projects/multi/viewer/manifest.json",
        source_project_id="multi",
        source_project_title="Multi2D",
    )

    layer = result["layers"]["shared-terrain-multi"]
    assert layer["visible"] is True
    assert layer["provenance"]["modelOwned"] is False
    assert result["resources"]["shared-terrain-multi-display"]["href"] == (
        "https://example.test/projects/multi/viewer/tiles/terrain.pmtiles"
    )
    assert result["resources"]["shared-terrain-multi-numeric"]["href"] == (
        "https://example.test/projects/multi/archive/terrain/terrain.cog.tif"
    )
    terrains = next(node for node in result["tree"] if node["id"] == "terrains")
    assert terrains["children"][0]["layerId"] == "shared-terrain-multi"
