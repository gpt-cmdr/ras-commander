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
from shapely.geometry import mapping
from shapely.ops import unary_union

from ras_commander.hdf import HdfProject


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_javascript_catalog(path: Path, payload: dict[str, Any]) -> None:
    """Write a small docs fallback without making it the catalog authority."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "window.RAS_EXAMPLE_PROJECTS = " + json.dumps(payload, indent=2) + ";\n",
        encoding="utf-8",
    )


def _project_feature(project: dict[str, Any], source_root: Path) -> dict[str, Any]:
    configured_hdfs = project.get("geometry_hdfs") or [project["geometry_hdf"]]
    footprint_geometries = []
    for relative_hdf_path in configured_hdfs:
        hdf_path = source_root / relative_hdf_path
        if not hdf_path.is_file():
            raise FileNotFoundError(f"Geometry HDF does not exist: {hdf_path}")

        extent_gdf, _ = HdfProject.get_project_extent(
            hdf_path,
            geometry_type="footprint",
            buffer_percent=0,
        )
        if extent_gdf.empty:
            raise ValueError(f"No footprint was produced for {project['id']}: {hdf_path}")
        if extent_gdf.crs is None:
            extent_gdf = extent_gdf.set_crs(project["crs"])
        footprint_geometries.extend(extent_gdf.geometry)

    geometry = unary_union(footprint_geometries)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"Expected a non-empty polygon footprint for {project['id']}, "
            f"got {geometry.geom_type}"
        )
    wgs84 = gpd.GeoSeries([geometry], crs=project["crs"]).to_crs("EPSG:4326")
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
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
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
        feature = _project_feature(project, source_root)
        features.append(feature)
        extent_payload = {
            "type": "FeatureCollection",
            "name": f"{project['id']}-model-extent",
            "generatedAt": generated_at,
            "features": [feature],
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
