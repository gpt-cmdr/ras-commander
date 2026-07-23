#!/usr/bin/env python
"""Build API-derived model extent artifacts for the Example Project Library.

The generator intentionally reads the original geometry HDF files.  Published
ras2cng archives are delivery artifacts and should not become the authority for
the model footprint.  ``HdfProject.get_project_extent`` combines 2D flow-area
perimeters with 1D river-edge footprints, including the generated-edge fallback.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely import concave_hull
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ras_commander.hdf import HdfProject


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _docs_fallback_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact metadata fallback with bbox geometry only.

    The full model footprints belong in the WebGIS GeoJSON. Shipping those
    vertices in the docs JavaScript would make every docs-page load download a
    second copy of the catalog. A bounding box keeps the fallback map and
    project links useful when WebGIS is temporarily unavailable.
    """
    features: list[dict[str, Any]] = []
    for feature in payload["features"]:
        min_x, min_y, max_x, max_y = feature["bbox"]
        properties = dict(feature["properties"])
        properties["fallbackGeometry"] = "bounding-box"
        features.append(
            {
                "type": "Feature",
                "id": feature["id"],
                "properties": properties,
                "bbox": feature["bbox"],
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [min_x, min_y],
                            [max_x, min_y],
                            [max_x, max_y],
                            [min_x, max_y],
                            [min_x, min_y],
                        ]
                    ],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "name": payload.get("name", "ras-commander-example-projects"),
        "generatedAt": payload.get("generatedAt"),
        "fallbackGeometry": "bounding-box",
        "features": features,
    }


def _write_javascript_catalog(path: Path, payload: dict[str, Any]) -> None:
    """Write a compact docs fallback without making it the catalog authority."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "window.RAS_EXAMPLE_PROJECTS = "
        + json.dumps(_docs_fallback_catalog(payload), indent=2)
        + ";\n",
        encoding="utf-8",
    )


def _landing_extent_geometry(project: dict[str, Any], geometry):
    """Return a discovery-map geometry without changing the exact footprint."""
    policy = project.get("landing_extent") or {}
    mode = str(policy.get("mode", "footprint")).strip().lower()
    if mode == "footprint":
        return geometry, "Exact model footprint"
    if mode != "concave_hull":
        raise ValueError(
            f"Unsupported landing extent mode for {project['id']}: {mode}"
        )

    ratio = float(policy.get("ratio", 0.10))
    if not 0.0 <= ratio <= 1.0:
        raise ValueError(
            f"landing_extent.ratio must be between 0 and 1 for {project['id']}"
        )
    overview = concave_hull(geometry, ratio=ratio, allow_holes=False)
    if overview.is_empty or overview.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"Could not produce a polygon coverage envelope for {project['id']}"
        )
    if not overview.is_valid:
        raise ValueError(f"Invalid coverage envelope for {project['id']}")
    return overview, "Model coverage envelope (concave hull of exact 1D reach footprints)"


def _landing_project_feature(
    project: dict[str, Any], exact_feature: dict[str, Any]
) -> dict[str, Any]:
    """Build the landing-map feature while retaining an exact extent artifact."""
    landing_geometry, landing_extent_source = _landing_extent_geometry(
        project, shape(exact_feature["geometry"])
    )
    properties = dict(exact_feature["properties"])
    properties["landingExtentSource"] = landing_extent_source
    return {
        "type": "Feature",
        "id": exact_feature["id"],
        "properties": properties,
        "bbox": [float(value) for value in landing_geometry.bounds],
        "geometry": mapping(landing_geometry),
    }


def _project_feature(project: dict[str, Any], source_root: Path) -> dict[str, Any]:
    footprint_geometries = []
    extent_geojson = project.get("extent_geojson")
    if extent_geojson:
        extent_path = source_root / extent_geojson
        if not extent_path.is_file():
            raise FileNotFoundError(f"Model extent GeoJSON does not exist: {extent_path}")
        payload = json.loads(extent_path.read_text(encoding="utf-8"))
        footprint_geometries.extend(
            shape(feature["geometry"])
            for feature in payload.get("features", [])
            if feature.get("geometry")
        )
        source_crs = project.get("extent_geojson_crs", "EPSG:4326")
    else:
        configured_hdfs = project.get("geometry_hdfs") or [project["geometry_hdf"]]
        for relative_hdf_path in configured_hdfs:
            hdf_path = source_root / relative_hdf_path
            if not hdf_path.is_file():
                raise FileNotFoundError(f"Geometry HDF does not exist: {hdf_path}")

            extent_gdf, _ = HdfProject.get_project_extent(
                hdf_path,
                geometry_type="footprint",
                buffer_percent=0,
                fill_holes=True,
            )
            if extent_gdf.empty:
                raise ValueError(f"No footprint was produced for {project['id']}: {hdf_path}")
            if extent_gdf.crs is None:
                extent_gdf = extent_gdf.set_crs(project["crs"])
            footprint_geometries.extend(extent_gdf.geometry)
        source_crs = project["crs"]

    geometry = unary_union(footprint_geometries)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"Expected a non-empty polygon footprint for {project['id']}, "
            f"got {geometry.geom_type}"
        )
    wgs84 = gpd.GeoSeries([geometry], crs=source_crs).to_crs("EPSG:4326")
    geometry = wgs84.iloc[0]
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"Expected a non-empty polygon footprint for {project['id']}, "
            f"got {geometry.geom_type}"
        )
    if not geometry.is_valid:
        raise ValueError(f"Invalid footprint for {project['id']}")

    properties = {
        "title": project["title"],
        "sourceFamily": project["source_family"],
        "crs": project.get("crs_display", project["crs"]),
        "crsDefinition": project["crs"],
        "status": project.get("status", "Published"),
        "projectId": project["id"],
        "webmap": project["webmap"],
        "manifest": project["manifest"],
        "projectManifest": project["project_manifest"],
        "viewerType": "MapLibre",
        "notes": project["notes"],
        "extentSource": (
            "HdfProject.get_project_extent(geometry_type='footprint', "
            "fill_holes=True)"
        ),
    }
    return {
        "type": "Feature",
        "id": project["id"],
        "properties": properties,
        "bbox": [float(value) for value in geometry.bounds],
        "geometry": mapping(geometry),
    }


def build_catalog(
    config: dict[str, Any], source_root: Path, webgis_root: Path, generated_at: str
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for project in config["projects"]:
        exact_feature = _project_feature(project, source_root)
        features.append(_landing_project_feature(project, exact_feature))
        extent_payload = {
            "type": "FeatureCollection",
            "name": f"{project['id']}-model-extent",
            "generatedAt": generated_at,
            "features": [exact_feature],
        }
        _write_json(webgis_root / project["extent_output"], extent_payload)

    return {
        "type": "FeatureCollection",
        "name": "ras-commander-example-projects",
        "generatedAt": generated_at,
        "features": features,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Root containing the organized source_projects and compute_outputs folders.",
    )
    parser.add_argument(
        "--webgis-root",
        type=Path,
        required=True,
        help="WebGIS HEC-RAS version root, e.g. .../rasexamples/hec-ras-7.0.",
    )
    parser.add_argument(
        "--catalog-output",
        type=Path,
        required=True,
        help="Public GeoJSON catalog path, relative to --webgis-root unless absolute.",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="ISO-8601 generation time. Defaults to the current UTC time.",
    )
    parser.add_argument(
        "--fallback-js-output",
        type=Path,
        default=None,
        help=(
            "Optional JavaScript fallback for the docs page. The WebGIS GeoJSON "
            "remains the authoritative published catalog."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    catalog = build_catalog(config, args.source_root, args.webgis_root, generated_at)
    catalog_output = args.catalog_output
    if not catalog_output.is_absolute():
        catalog_output = args.webgis_root / catalog_output
    _write_json(catalog_output, catalog)
    if args.fallback_js_output:
        _write_javascript_catalog(args.fallback_js_output, catalog)
    print(f"Wrote {len(catalog['features'])} model footprints to {catalog_output}")


if __name__ == "__main__":
    main()
