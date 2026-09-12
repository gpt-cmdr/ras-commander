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


def test_example_library_does_not_expose_stale_viewer_links_during_catalog_outage() -> None:
    javascript = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    assert "qualifyViewerLinks" in javascript
    assert "MANIFEST_REQUEST_TIMEOUT_MS" in javascript
    assert "controller.abort()" in javascript
    assert "await response.json()" in javascript
    assert 'webmap: ""' in javascript
    assert 'manifest: ""' in javascript
    assert 'projectManifest: ""' in javascript
    assert "props.linkUnavailableReason" in javascript
    assert "published project maps are temporarily unavailable" in javascript
    assert "source-candidate details remain available" in javascript


def test_example_library_only_makes_http_links_clickable() -> None:
    javascript = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    assert "function resolveHttpHref" in javascript
    assert 'typeof href !== "string" || !href.trim()' in javascript
    assert '["http:", "https:"].includes(url.protocol)' in javascript
    assert 'catch (_error)' in javascript
    assert "resolveHref" not in javascript


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
    rod = (
        ROOT / "agent_tasks" / "2026-09-05_san_gabriel_record_of_deficiencies.md"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))

    assert "ras-example-project-supplements.js" in page
    assert "mergeProjectCollections(await response.json())" in library
    assert "!existingIds.has(id)" in library
    expected_ids = {f"san-gabriel-lbsg-{number}-12070205" for number in range(501, 506)}
    features = [
        feature
        for feature in supplement["features"]
        if feature["id"].startswith("san-gabriel-lbsg-")
    ]
    assert {feature["id"] for feature in features} == expected_ids
    assert all(
        feature["properties"]["status"] == "Source qualification candidate"
        for feature in features
    )
    assert all(not feature["properties"]["webmap"] for feature in features)
    details = [feature["properties"]["details"] for feature in features]
    assert len(set(details)) == 5
    assert details == [
        "https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/"
        f"2026-09-05_san_gabriel_record_of_deficiencies.md#lbsg-{number}"
        for number in range(501, 506)
    ]
    assert all(f"### LBSG {number}" in rod for number in range(501, 506))
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
    assert "webmap || resolveHttpHref(child.properties?.details)" in library
    assert 'document.createElement(projectHref ? "a" : "span")' in library
    assert 'webmap ? "Open project map" : "Open project details"' in library
    assert "const details = resolveHttpHref(props.details)" in library
    assert "!webmap && details" in library


def test_double_mountain_fork_brazos_candidate_profile_and_rod_are_validated() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    rod = (
        ROOT
        / "agent_tasks"
        / "2026-09-11_double_mountain_fork_brazos_record_of_deficiencies.md"
    ).read_text(encoding="utf-8")

    expected_ids = {
        f"double-mountain-fork-brazos-dmf{number}-12050004"
        for number in range(1, 5)
    }
    assert all(project_id in profiles for project_id in expected_ids)
    assert profiles.count('groupId: "double-mountain-fork-brazos"') == 4
    assert 'title: "Double Mountain Fork Brazos Model Suite"' in profiles
    assert "HEC-RAS 6.10 source (6.1 family)" in profiles
    assert "double-mountain-fork-brazos" in page
    assert "Terrain.Clone (1).hdf" in page
    assert "20260911Tdmfb-candidate02" in page
    assert all(f"### DMF{number}" in rod for number in range(1, 5))
    assert "compiled terrain is **not missing**" in rod
    assert "Polygons (1)" in rod
    assert "4/4 plans reached unsteady computation" in rod
    assert "native-qualification-20260911-2024" in rod
    assert "qualification pending" not in profiles.lower()


def test_double_mountain_fork_brazos_exact_candidate_footprints_are_discoverable() -> None:
    supplement_source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))
    features = [
        feature
        for feature in supplement["features"]
        if feature["id"].startswith("double-mountain-fork-brazos-dmf")
    ]

    assert [feature["id"] for feature in features] == [
        f"double-mountain-fork-brazos-dmf{number}-12050004"
        for number in range(1, 5)
    ]
    assert all(
        feature["properties"]["status"] == "Source qualification candidate"
        for feature in features
    )
    assert all(
        feature["properties"]["viewerType"] == "Qualification candidate"
        for feature in features
    )
    assert all(
        not feature["properties"][field]
        for feature in features
        for field in ("webmap", "manifest", "projectManifest")
    )
    assert [
        feature["properties"]["details"].rsplit("#", 1)[-1]
        for feature in features
    ] == [f"dmf{number}" for number in range(1, 5)]
    assert all(
        feature["properties"]["recordOfDeficiencies"].endswith(
            "2026-09-11_double_mountain_fork_brazos_record_of_deficiencies.md"
        )
        for feature in features
    )
    assert all(
        feature["properties"]["extentSource"]
        == "HdfProject.get_project_extent(geometry_type='footprint', "
        "buffer_percent=0, fill_holes=True)"
        for feature in features
    )
    assert all(
        feature["properties"]["landingExtentSource"] == "Exact model footprint"
        for feature in features
    )
    assert all(
        "reached unsteady computation" in feature["properties"]["notes"]
        for feature in features
    )
    assert all(
        "pending" not in feature["properties"]["notes"].lower()
        for feature in features
    )
    geometries = [shape(feature["geometry"]) for feature in features]
    assert all(geometry.geom_type == "Polygon" for geometry in geometries)
    assert all(geometry.is_valid for geometry in geometries)
    assert all(
        not geometry.equals(box(*feature["bbox"]))
        for feature, geometry in zip(features, geometries, strict=True)
    )
    assert all(
        list(geometry.bounds) == feature["bbox"]
        for feature, geometry in zip(features, geometries, strict=True)
    )
    assert list(unary_union(geometries).bounds) == [
        -102.66821767652011,
        32.702787543982225,
        -99.89819835922083,
        33.68199246862984,
    ]


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
