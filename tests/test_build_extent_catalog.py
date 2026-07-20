from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, box, shape

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "example_library" / "build_extent_catalog.py"
CATALOG_CONFIG_PATH = Path(__file__).parents[1] / "agent_tasks" / "rasexamples_extent_catalog.json"
SPEC = importlib.util.spec_from_file_location("build_extent_catalog", SCRIPT_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_catalog_extent_outputs_do_not_overlap_viewer_artifacts() -> None:
    config = json.loads(CATALOG_CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["projects"]
    for project in config["projects"]:
        assert project["extent_output"].startswith("project-extents/")
        assert "/viewer/" not in project["extent_output"]


def test_write_javascript_catalog_assigns_a_compact_bbox_fallback(tmp_path: Path) -> None:
    output = tmp_path / "ras-example-projects-data.js"
    catalog = {
        "type": "FeatureCollection",
        "name": "example-projects",
        "generatedAt": "2026-07-13T00:00:00Z",
        "features": [
            {
                "type": "Feature",
                "id": "model-1",
                "properties": {"title": "Model 1"},
                "bbox": [-85.0, 40.0, -84.0, 41.0],
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-85.0, 40.0],
                            [-84.5, 40.0],
                            [-84.0, 41.0],
                            [-85.0, 40.0],
                        ]
                    ],
                },
            }
        ],
    }

    builder._write_javascript_catalog(output, catalog)

    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    contents = output.read_text(encoding="utf-8")
    assert contents.startswith(prefix)
    assert contents.endswith(";\n")
    fallback = json.loads(contents.removeprefix(prefix).removesuffix(";\n"))
    assert fallback["name"] == catalog["name"]
    assert fallback["fallbackGeometry"] == "bounding-box"
    assert fallback["features"][0]["properties"]["fallbackGeometry"] == "bounding-box"
    assert fallback["features"][0]["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[-85.0, 40.0], [-84.0, 40.0], [-84.0, 41.0], [-85.0, 41.0], [-85.0, 40.0]]],
    }


def test_project_feature_uses_display_crs_without_losing_definition(monkeypatch, tmp_path: Path) -> None:
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    extent = gpd.GeoDataFrame(geometry=[box(-85.0, 40.0, -84.9, 40.1)], crs="EPSG:4326")
    monkeypatch.setattr(builder.HdfProject, "get_project_extent", lambda *args, **kwargs: (extent, extent.total_bounds))
    project = {
        "id": "model-1",
        "title": "Model 1",
        "source_family": "Example",
        "crs": "EPSG:4326",
        "crs_display": "WGS 84",
        "geometry_hdf": hdf_path.name,
        "webmap": "../viewer/",
        "manifest": "https://example.test/manifest.json",
        "project_manifest": "https://example.test/project.json",
        "notes": "Test model",
    }

    feature = builder._project_feature(project, tmp_path)

    assert feature["properties"]["crs"] == "WGS 84"
    assert feature["properties"]["crsDefinition"] == "EPSG:4326"


def test_project_feature_unions_configured_geometry_hdfs(monkeypatch, tmp_path: Path) -> None:
    first_hdf_path = tmp_path / "model.g01.hdf"
    second_hdf_path = tmp_path / "model.g02.hdf"
    first_hdf_path.touch()
    second_hdf_path.touch()
    extents = {
        first_hdf_path: gpd.GeoDataFrame(geometry=[box(-85.0, 40.0, -84.9, 40.1)], crs="EPSG:4326"),
        second_hdf_path: gpd.GeoDataFrame(geometry=[box(-84.8, 40.0, -84.7, 40.1)], crs="EPSG:4326"),
    }

    def get_project_extent(path: Path, **_kwargs):
        extent = extents[path]
        return extent, extent.total_bounds

    monkeypatch.setattr(builder.HdfProject, "get_project_extent", get_project_extent)
    project = {
        "id": "model-1",
        "title": "Model 1",
        "source_family": "Example",
        "crs": "EPSG:4326",
        "geometry_hdf": first_hdf_path.name,
        "geometry_hdfs": [first_hdf_path.name, second_hdf_path.name],
        "webmap": "../viewer/",
        "manifest": "https://example.test/manifest.json",
        "project_manifest": "https://example.test/project.json",
        "notes": "Test model",
    }

    feature = builder._project_feature(project, tmp_path)

    assert feature["geometry"]["type"] == "MultiPolygon"
    assert feature["bbox"] == [-85.0, 40.0, -84.7, 40.1]


def test_catalog_uses_configured_landing_envelope_without_changing_exact_extent(
    monkeypatch, tmp_path: Path
) -> None:
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    exact_geometry = MultiPolygon(
        [box(-85.0, 40.0, -84.99, 40.01), box(-84.8, 40.1, -84.79, 40.11)]
    )
    exact_extent = gpd.GeoDataFrame(geometry=[exact_geometry], crs="EPSG:4326")
    monkeypatch.setattr(
        builder.HdfProject,
        "get_project_extent",
        lambda *args, **kwargs: (exact_extent, exact_extent.total_bounds),
    )
    project = {
        "id": "model-1",
        "title": "Model 1",
        "source_family": "Example",
        "crs": "EPSG:4326",
        "geometry_hdf": hdf_path.name,
        "extent_output": "project-extents/model-1.geojson",
        "webmap": "../viewer/",
        "manifest": "https://example.test/manifest.json",
        "project_manifest": "https://example.test/project.json",
        "notes": "Test model",
        "landing_extent": {"mode": "concave_hull", "ratio": 0.1},
    }

    catalog = builder.build_catalog(
        {"projects": [project]}, tmp_path, tmp_path / "webgis", "2026-07-14T00:00:00Z"
    )

    landing_feature = catalog["features"][0]
    exact_feature = json.loads(
        (tmp_path / "webgis" / "project-extents" / "model-1.geojson").read_text()
    )["features"][0]
    assert landing_feature["geometry"]["type"] == "Polygon"
    assert landing_feature["properties"]["landingExtentSource"].startswith(
        "Model coverage envelope"
    )
    assert shape(exact_feature["geometry"]).equals(exact_geometry)
