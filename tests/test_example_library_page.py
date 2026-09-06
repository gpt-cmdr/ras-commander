import json
from pathlib import Path

from shapely.geometry import box, shape
from shapely.ops import unary_union


ROOT = Path(__file__).parents[1]


def test_example_library_is_a_technical_model_catalog() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")

    assert "Technical Description" in page
    assert "HEC-RAS Version" in page
    assert '<th scope="col">CRS</th>' not in page
    assert "Published MapLibre" not in page
    assert "Upper Guadalupe Model Suite" in profiles
    assert "two diversions" in profiles
    assert "shared display context" in profiles
    assert "ether-hollow-post-fire-debris-flow-1227955d" in profiles
    assert "2,500 psf yield stress" in profiles


def test_example_library_groups_suites_and_reports_overlapping_projects() -> None:
    source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    assert "catalogEntries(features)" in source
    assert "projects at this location" in source
    assert "project-extents-fill" in source


def test_example_library_replaces_pins_with_readable_model_extents() -> None:
    source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )

    assert 'PROJECT_PIN_IMAGE_ID = "ras-project-pin"' in source
    assert "PIN_REPLACEMENT_PIXEL_SIZE" in source
    assert "projectDisplayCollections(map, features)" in source
    assert 'id: "project-pins"' in source
    assert 'id: "project-pins-hit"' in source
    assert 'map.on("moveend", updateProjectDisplay)' in source
    assert "Select a project pin or model extent." in page


def test_example_library_consumes_only_the_atomic_current_release() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    javascript = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    expected = "hec-ras-7.0/current/example-projects.geojson"
    assert expected in page
    assert expected in javascript


def test_san_gabriel_submodels_are_grouped_in_the_dashboard() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    library = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    supplement_source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))

    assert "ras-example-project-supplements.js" in page
    assert "mergeProjectCollections(await response.json())" in library
    assert "!existingIds.has(id)" in library
    expected_ids = {f"san-gabriel-lbsg-{number}-12070205" for number in range(501, 506)}
    features = supplement["features"]
    assert {feature["id"] for feature in features} == expected_ids
    assert all(
        feature["properties"]["status"] == "Source qualification candidate"
        for feature in features
    )
    assert all(
        feature["properties"]["recordOfDeficiencies"].endswith(
            "2026-09-05_san_gabriel_record_of_deficiencies.md"
        )
        for feature in features
    )
    assert "Record of Deficiencies" in library
    geometries = [shape(feature["geometry"]) for feature in features]
    assert all(geometry.is_valid for geometry in geometries)
    assert all(
        not geometry.equals(box(*feature["bbox"]))
        for feature, geometry in zip(features, geometries, strict=True)
    )
    assert all(
        feature["properties"]["landingExtentSource"] == "Exact model footprint"
        for feature in features
    )
    assert list(unary_union(geometries).bounds) == [
        -98.26813645701162,
        30.403250679780886,
        -97.00285606221672,
        30.918779935290782,
    ]
    assert profiles.count('groupId: "san-gabriel"') == 5
    assert 'title: "San Gabriel Model Suite"' in profiles
    assert 'variantLabel: "LBSG_503 (Florence)"' in profiles
    assert 'variantLabel: "LBSG_504 (Round Rock)"' in profiles
    assert 'document.createElement(webmap ? "a" : "span")' in library


def test_embedded_catalog_retains_api_derived_project_footprints() -> None:
    source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-projects-data.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    catalog = json.loads(source.removeprefix(prefix).removesuffix(";\n"))

    assert catalog["fallbackSource"] == "embedded-api-derived-project-footprints"
    assert len(catalog["features"]) == 18
    for feature in catalog["features"]:
        geometry = shape(feature["geometry"])
        assert geometry.geom_type in {"Polygon", "MultiPolygon"}
        assert geometry.is_valid
        assert not geometry.equals(box(*feature["bbox"]))
        assert "HdfProject.get_project_extent" in feature["properties"]["extentSource"]
