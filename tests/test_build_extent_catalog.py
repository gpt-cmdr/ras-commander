from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "example_library" / "build_extent_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_extent_catalog", SCRIPT_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_write_javascript_catalog_assigns_the_feature_collection(tmp_path: Path) -> None:
    output = tmp_path / "ras-example-projects-data.js"
    catalog = {"type": "FeatureCollection", "features": [{"id": "model-1"}]}

    builder._write_javascript_catalog(output, catalog)

    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    contents = output.read_text(encoding="utf-8")
    assert contents.startswith(prefix)
    assert contents.endswith(";\n")
    assert json.loads(contents.removeprefix(prefix).removesuffix(";\n")) == catalog


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
