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
import re
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
    """Return an embedded fallback with the API-derived project footprints.

    The fallback is loaded only by the Example Project Library page. Preserve
    the catalog geometry verbatim so a WebGIS outage cannot silently degrade
    model footprints into bounding boxes.
    """
    features: list[dict[str, Any]] = []
    for feature in payload["features"]:
        properties = dict(feature["properties"])
        feature_id = feature.get("id") or properties.get("projectId")
        if not feature_id:
            raise ValueError("Catalog feature has neither id nor properties.projectId")
        geometry = feature.get("geometry")
        if not geometry:
            raise ValueError(f"Catalog feature {feature_id!r} has no geometry")
        footprint = shape(geometry)
        if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Catalog feature {feature_id!r} must have polygon geometry"
            )
        if not footprint.is_valid:
            raise ValueError(f"Catalog feature {feature_id!r} has invalid geometry")
        properties.pop("fallbackGeometry", None)
        features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "properties": properties,
                "bbox": [float(value) for value in footprint.bounds],
                "geometry": geometry,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": payload.get("name", "ras-commander-example-projects"),
        "generatedAt": payload.get("generatedAt"),
        "fallbackSource": "embedded-api-derived-project-footprints",
        "features": features,
    }


def _javascript_prefix(variable: str) -> str:
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", variable):
        raise ValueError(f"Invalid JavaScript variable name: {variable!r}")
    return f"window.{variable} = "


def _write_javascript_catalog(
    path: Path,
    payload: dict[str, Any],
    variable: str = "RAS_EXAMPLE_PROJECTS",
) -> None:
    """Write an exact-geometry docs fallback without changing catalog authority."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _javascript_prefix(variable)
        + json.dumps(_docs_fallback_catalog(payload), separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def _merge_javascript_catalog(
    path: Path,
    payload: dict[str, Any],
    variable: str,
) -> None:
    """Merge generated features into an existing strict JavaScript collection."""
    prefix = _javascript_prefix(variable)
    source = path.read_text(encoding="utf-8")
    if not source.startswith(prefix) or not source.endswith(";\n"):
        raise ValueError(f"Unexpected JavaScript catalog assignment in {path}")
    existing = json.loads(source.removeprefix(prefix).removesuffix(";\n"))
    generated = _docs_fallback_catalog(payload)
    existing_features = existing.get("features")
    if not isinstance(existing_features, list):
        raise ValueError(f"Existing JavaScript catalog has no features list: {path}")

    replacements = {
        str(
            feature.get("id") or feature.get("properties", {}).get("projectId")
        ): feature
        for feature in generated["features"]
    }
    if "None" in replacements or "" in replacements:
        raise ValueError("Generated catalog contains a feature without a project ID")
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feature in existing_features:
        feature_id = str(
            feature.get("id") or feature.get("properties", {}).get("projectId")
        )
        if feature_id in replacements:
            feature = replacements[feature_id]
        if feature_id in seen:
            raise ValueError(f"Duplicate existing JavaScript catalog ID: {feature_id}")
        seen.add(feature_id)
        merged.append(feature)
    for feature_id, feature in replacements.items():
        if feature_id not in seen:
            merged.append(feature)

    existing["generatedAt"] = generated.get("generatedAt")
    existing["features"] = merged
    path.write_text(
        prefix + json.dumps(existing, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def _landing_extent_geometry(project: dict[str, Any], geometry):
    """Return a discovery-map geometry without changing the exact footprint."""
    policy = project.get("landing_extent") or {}
    mode = str(policy.get("mode", "footprint")).strip().lower()
    if mode == "footprint":
        return geometry, project.get(
            "landing_extent_source",
            "Exact model footprint",
        )
    if mode != "concave_hull":
        raise ValueError(f"Unsupported landing extent mode for {project['id']}: {mode}")

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
    return (
        overview,
        "Model coverage envelope (concave hull of exact 1D reach footprints)",
    )


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
            raise FileNotFoundError(
                f"Model extent GeoJSON does not exist: {extent_path}"
            )
        payload = json.loads(extent_path.read_text(encoding="utf-8"))
        footprint_geometries.extend(
            shape(feature["geometry"])
            for feature in payload.get("features", [])
            if feature.get("geometry")
        )
        source_crs = project.get("extent_geojson_crs", "EPSG:4326")
        extent_source = project.get(
            "extent_source",
            "Configured model-footprint GeoJSON (unioned without generalization)",
        )
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
                raise ValueError(
                    f"No footprint was produced for {project['id']}: {hdf_path}"
                )
            if extent_gdf.crs is None:
                extent_gdf = extent_gdf.set_crs(project["crs"])
            footprint_geometries.extend(extent_gdf.geometry)
        source_crs = project["crs"]
        extent_source = (
            "HdfProject.get_project_extent(geometry_type='footprint', fill_holes=True)"
        )

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
        "landingGeometryPmtiles": project.get(
            "landingGeometryPmtiles",
            project.get("landing_geometry_pmtiles", ""),
        ),
        "landingGeometryProfile": project.get(
            "landingGeometryProfile",
            project.get("landing_geometry_profile", ""),
        ),
        "viewerType": project.get("viewer_type", "MapLibre"),
        "details": project.get("details", ""),
        "recordOfDeficiencies": project.get("record_of_deficiencies", ""),
        "notes": project["notes"],
        "extentSource": extent_source,
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
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Generate only this configured project ID; repeat for multiple projects.",
    )
    parser.add_argument(
        "--javascript-variable",
        default="RAS_EXAMPLE_PROJECTS",
        help="Window variable used by --fallback-js-output.",
    )
    parser.add_argument(
        "--merge-fallback-js",
        action="store_true",
        help="Merge selected project features into an existing fallback JavaScript file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.project_id:
        wanted = set(args.project_id)
        selected = [item for item in config["projects"] if item["id"] in wanted]
        found = {item["id"] for item in selected}
        if found != wanted:
            raise ValueError(
                f"Unknown configured project IDs: {sorted(wanted - found)}"
            )
        config = {**config, "projects": selected}
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    catalog = build_catalog(config, args.source_root, args.webgis_root, generated_at)
    catalog_output = args.catalog_output
    if not catalog_output.is_absolute():
        catalog_output = args.webgis_root / catalog_output
    _write_json(catalog_output, catalog)
    if args.fallback_js_output:
        if args.merge_fallback_js:
            _merge_javascript_catalog(
                args.fallback_js_output,
                catalog,
                args.javascript_variable,
            )
        else:
            _write_javascript_catalog(
                args.fallback_js_output,
                catalog,
                args.javascript_variable,
            )
    print(f"Wrote {len(catalog['features'])} model footprints to {catalog_output}")


if __name__ == "__main__":
    main()
