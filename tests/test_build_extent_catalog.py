from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, box, mapping, shape

SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "build_extent_catalog.py"
)
CATALOG_CONFIG_PATH = (
    Path(__file__).parents[1] / "agent_tasks" / "rasexamples_extent_catalog.json"
)
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


def test_san_gabriel_catalog_has_five_linked_submodel_entries() -> None:
    config = json.loads(CATALOG_CONFIG_PATH.read_text(encoding="utf-8"))

    projects = [
        item
        for item in config["projects"]
        if item["id"].startswith("san-gabriel-lbsg-")
    ]
    assert [project["id"] for project in projects] == [
        "san-gabriel-lbsg-501-12070205",
        "san-gabriel-lbsg-502-12070205",
        "san-gabriel-lbsg-503-12070205",
        "san-gabriel-lbsg-504-12070205",
        "san-gabriel-lbsg-505-12070205",
    ]
    assert all(
        project["status"] == "Source qualification candidate" for project in projects
    )
    assert all(
        project["viewer_type"] == "Qualification candidate" for project in projects
    )
    assert all(not project["webmap"] for project in projects)
    details = [project["details"] for project in projects]
    assert len(set(details)) == 5
    assert details == [
        "https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/"
        f"2026-09-05_san_gabriel_record_of_deficiencies.md#lbsg-{number}"
        for number in range(501, 506)
    ]
    assert all(
        project["record_of_deficiencies"].endswith(
            "2026-09-05_san_gabriel_record_of_deficiencies.md"
        )
        for project in projects
    )
    assert [Path(project["geometry_hdf"]).name for project in projects] == [
        "BLE_LBSG_501.g02.hdf",
        "BLE_LBSG_502.g03.hdf",
        "BLE_LBSG_503.g04.hdf",
        "BLE_LBSG_504.g05.hdf",
        "BLE_LBSG_505.g06.hdf",
    ]


def test_double_mountain_fork_brazos_catalog_has_four_linked_candidates() -> None:
    config = json.loads(CATALOG_CONFIG_PATH.read_text(encoding="utf-8"))

    projects = [
        item
        for item in config["projects"]
        if item["id"].startswith("double-mountain-fork-brazos-dmf")
    ]
    assert [project["id"] for project in projects] == [
        f"double-mountain-fork-brazos-dmf{number}-12050004" for number in range(1, 5)
    ]
    assert all(
        project["status"] == "Source qualification candidate" for project in projects
    )
    assert all(
        project["viewer_type"] == "Qualification candidate" for project in projects
    )
    assert all(
        not project[field]
        for project in projects
        for field in ("webmap", "manifest", "project_manifest")
    )
    assert [project["details"].rsplit("#", 1)[-1] for project in projects] == [
        f"dmf{number}" for number in range(1, 5)
    ]
    assert all(
        project["record_of_deficiencies"].endswith(
            "2026-09-11_double_mountain_fork_brazos_record_of_deficiencies.md"
        )
        for project in projects
    )
    assert [Path(project["geometry_hdf"]).name for project in projects] == [
        "DMF_1.g01.hdf",
        "DMF2.g01.hdf",
        "DMF_3.g01.hdf",
        "DMF_BrazosRiver4.g01.hdf",
    ]
    assert all(
        "reached unsteady computation" in project["notes"] for project in projects
    )
    assert all("pending" not in project["notes"].lower() for project in projects)


def test_alabama_ble_catalog_has_one_corpus_candidate() -> None:
    config = json.loads(CATALOG_CONFIG_PATH.read_text(encoding="utf-8"))
    project_id = "middle-chattahoochee-lake-harding-al03130002"
    projects = [item for item in config["projects"] if item["id"] == project_id]

    assert len(projects) == 1
    project = projects[0]
    assert project["status"] == "Source qualification candidate"
    assert project["viewer_type"] == "Qualification candidate"
    assert project["extent_geojson"].endswith("AL03130002_model_footprints.geojson")
    assert project["extent_source"].startswith("Union of 197")
    assert project["landing_extent_source"] == "Exact union of 197 model footprints"
    assert all(
        not project[field]
        for field in (
            "webmap",
            "manifest",
            "project_manifest",
            "landing_geometry_pmtiles",
            "landing_geometry_profile",
        )
    )
    assert "197 Alabama BLE 1D steady projects" in project["notes"]


def test_write_javascript_catalog_preserves_exact_project_footprint(
    tmp_path: Path,
) -> None:
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
    assert fallback["fallbackSource"] == "embedded-api-derived-project-footprints"
    assert "fallbackGeometry" not in fallback
    assert "fallbackGeometry" not in fallback["features"][0]["properties"]
    assert fallback["features"][0]["geometry"] == catalog["features"][0]["geometry"]
    assert not shape(fallback["features"][0]["geometry"]).equals(
        box(*fallback["features"][0]["bbox"])
    )


def test_write_javascript_catalog_derives_missing_bbox_from_geometry(
    tmp_path: Path,
) -> None:
    output = tmp_path / "ras-example-projects-data.js"
    catalog = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "title": "Model without bbox",
                    "projectId": "model-without-bbox",
                },
                "geometry": mapping(box(-111.5, 40.1, -111.4, 40.2)),
            }
        ],
    }

    builder._write_javascript_catalog(output, catalog)

    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    fallback = json.loads(
        output.read_text(encoding="utf-8").removeprefix(prefix).removesuffix(";\n")
    )
    assert fallback["features"][0]["id"] == "model-without-bbox"
    assert fallback["features"][0]["bbox"] == [-111.5, 40.1, -111.4, 40.2]


def test_merge_javascript_catalog_replaces_and_appends_exact_features(
    tmp_path: Path,
) -> None:
    output = tmp_path / "ras-example-project-supplements.js"
    existing = {
        "type": "FeatureCollection",
        "name": "supplements",
        "generatedAt": "old",
        "features": [
            {
                "type": "Feature",
                "id": "retained",
                "properties": {"title": "Retained"},
                "geometry": mapping(box(-86.0, 32.0, -85.9, 32.1)),
            },
            {
                "type": "Feature",
                "id": "replaced",
                "properties": {"title": "Old"},
                "geometry": mapping(box(-85.8, 32.0, -85.7, 32.1)),
            },
        ],
    }
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    output.write_text(prefix + json.dumps(existing) + ";\n", encoding="utf-8")
    replacement_geometry = mapping(box(-85.7, 32.1, -85.6, 32.2))
    appended_geometry = mapping(box(-85.6, 32.2, -85.5, 32.3))
    generated = {
        "type": "FeatureCollection",
        "generatedAt": "new",
        "features": [
            {
                "type": "Feature",
                "id": "replaced",
                "properties": {"title": "New"},
                "geometry": replacement_geometry,
            },
            {
                "type": "Feature",
                "id": "appended",
                "properties": {"title": "Appended"},
                "geometry": appended_geometry,
            },
        ],
    }

    builder._merge_javascript_catalog(
        output,
        generated,
        "RAS_EXAMPLE_PROJECT_SUPPLEMENTS",
    )

    merged = json.loads(
        output.read_text(encoding="utf-8").removeprefix(prefix).removesuffix(";\n")
    )
    assert merged["generatedAt"] == "new"
    assert [feature["id"] for feature in merged["features"]] == [
        "retained",
        "replaced",
        "appended",
    ]
    assert shape(merged["features"][1]["geometry"]).equals(shape(replacement_geometry))
    assert shape(merged["features"][2]["geometry"]).equals(shape(appended_geometry))
    assert all(
        "fallbackGeometry" not in item["properties"] for item in merged["features"]
    )


def test_javascript_catalog_rejects_invalid_variable_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid JavaScript variable"):
        builder._write_javascript_catalog(
            tmp_path / "catalog.js",
            {"type": "FeatureCollection", "features": []},
            "BAD;alert(1)",
        )


def test_project_feature_uses_display_crs_without_losing_definition(
    monkeypatch, tmp_path: Path
) -> None:
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    extent = gpd.GeoDataFrame(geometry=[box(-85.0, 40.0, -84.9, 40.1)], crs="EPSG:4326")
    calls = []

    def get_project_extent(*args, **kwargs):
        calls.append((args, kwargs))
        return extent, extent.total_bounds

    monkeypatch.setattr(builder.HdfProject, "get_project_extent", get_project_extent)
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
        "landing_geometry_pmtiles": "https://example.test/corpus.pmtiles",
        "landing_geometry_profile": "ras-1d-corpus-v1",
        "notes": "Test model",
    }

    feature = builder._project_feature(project, tmp_path)

    assert feature["properties"]["crs"] == "WGS 84"
    assert feature["properties"]["crsDefinition"] == "EPSG:4326"
    assert calls == [
        (
            (hdf_path,),
            {
                "geometry_type": "footprint",
                "buffer_percent": 0,
                "fill_holes": True,
            },
        )
    ]
    assert "fill_holes=True" in feature["properties"]["extentSource"]
    assert (
        feature["properties"]["landingGeometryPmtiles"]
        == "https://example.test/corpus.pmtiles"
    )
    assert feature["properties"]["landingGeometryProfile"] == "ras-1d-corpus-v1"


def test_project_feature_unions_configured_geometry_hdfs(
    monkeypatch, tmp_path: Path
) -> None:
    first_hdf_path = tmp_path / "model.g01.hdf"
    second_hdf_path = tmp_path / "model.g02.hdf"
    first_hdf_path.touch()
    second_hdf_path.touch()
    extents = {
        first_hdf_path: gpd.GeoDataFrame(
            geometry=[box(-85.0, 40.0, -84.9, 40.1)], crs="EPSG:4326"
        ),
        second_hdf_path: gpd.GeoDataFrame(
            geometry=[box(-84.8, 40.0, -84.7, 40.1)], crs="EPSG:4326"
        ),
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


def test_project_feature_accepts_api_generated_extent_geojson(tmp_path: Path) -> None:
    extent_path = tmp_path / "viewer" / "model_extent.geojson"
    extent_path.parent.mkdir()
    extent_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"geometry_id": "g01"},
                        "geometry": box(-89.0, 42.0, -88.9, 42.1).__geo_interface__,
                    },
                    {
                        "type": "Feature",
                        "properties": {"geometry_id": "g02"},
                        "geometry": box(-88.8, 42.0, -88.7, 42.1).__geo_interface__,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    project = {
        "id": "model-1",
        "title": "Model 1",
        "source_family": "Example",
        "crs": "EPSG:3435",
        "extent_geojson": "viewer/model_extent.geojson",
        "extent_geojson_crs": "EPSG:4326",
        "webmap": "../viewer/",
        "manifest": "https://example.test/manifest.json",
        "project_manifest": "https://example.test/project.json",
        "notes": "Test model",
    }

    feature = builder._project_feature(project, tmp_path)

    assert feature["geometry"]["type"] == "MultiPolygon"
    assert feature["bbox"] == [-89.0, 42.0, -88.7, 42.1]


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
