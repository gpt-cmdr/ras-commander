import json
from pathlib import Path

import pytest
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


def test_example_library_does_not_expose_stale_viewer_links_during_catalog_outage() -> (
    None
):
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
    assert "catch (_error)" in javascript
    assert "resolveHref" not in javascript


def test_example_library_supports_direct_1d_corpus_geometry_overlay() -> None:
    javascript = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    assert '"ras-1d-corpus-v1"' in javascript
    assert 'sourceLayer: "ras_model_extent"' in javascript
    assert 'sourceLayer: "ras_river_centerlines"' in javascript
    assert 'sourceLayer: "ras_cross_sections"' in javascript
    assert 'sourceLayer: "ras_bank_lines"' in javascript
    assert "nativeMinzoom: 7" in javascript
    assert "nativeMaxzoom: 11" in javascript
    assert "nativeMinzoom: 8" in javascript
    assert "nativeMinzoom: 10" in javascript
    assert "nativeMaxzoom: 14" in javascript
    assert "properties.landingGeometryPmtiles" in javascript
    assert "properties.landingGeometryProfile" in javascript
    assert "addSelectedGeometryTileset" in javascript
    assert 'map.getLayer("selected-project-extent-halo")' in javascript
    overlay_builder = javascript.split("function addSelectedGeometryTileset", 1)[
        1
    ].split("async function showSelectedProjectGeometry", 1)[0]
    assert "maxzoom: Number(" not in overlay_builder
    assert "should overzoom beyond" in overlay_builder
    assert 'map.getSource("selected-project").setData' in javascript


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
        f"double-mountain-fork-brazos-dmf{number}-12050004" for number in range(1, 5)
    }
    assert all(project_id in profiles for project_id in expected_ids)
    assert profiles.count('groupId: "double-mountain-fork-brazos"') == 4
    assert 'title: "Double Mountain Fork Brazos Model Suite"' in profiles
    assert "HEC-RAS 6.10 source (6.1 family)" in profiles
    assert "double-mountain-fork-brazos" in page
    assert "Terrain.Clone (1).hdf" in page
    assert "20260912Talabama-ble-corpus01" in page
    assert all(f"### DMF{number}" in rod for number in range(1, 5))
    assert "compiled terrain is **not missing**" in rod
    assert "Polygons (1)" in rod
    assert "4/4 plans reached unsteady computation" in rod
    assert "native-qualification-20260911-2024" in rod
    dmf_profiles = profiles.split(
        '"double-mountain-fork-brazos-dmf1-12050004"', 1
    )[1].split('"middle-chattahoochee-lake-harding-al03130002"', 1)[0]
    assert "qualification pending" not in dmf_profiles.lower()


def test_double_mountain_fork_brazos_exact_candidate_footprints_are_discoverable() -> (
    None
):
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
        f"double-mountain-fork-brazos-dmf{number}-12050004" for number in range(1, 5)
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
        feature["properties"]["details"].rsplit("#", 1)[-1] for feature in features
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
        "pending" not in feature["properties"]["notes"].lower() for feature in features
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


def test_alabama_ble_corpus_is_one_exact_discovery_entry() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    supplement_source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))
    project_id = "middle-chattahoochee-lake-harding-al03130002"
    features = [item for item in supplement["features"] if item["id"] == project_id]

    assert len(features) == 1
    feature = features[0]
    geometry = shape(feature["geometry"])
    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid
    assert not geometry.equals(box(*feature["bbox"]))
    assert list(geometry.bounds) == feature["bbox"]
    assert feature["properties"]["status"] == "Source qualification candidate"
    assert feature["properties"]["viewerType"] == "Qualification candidate"
    assert all(
        not feature["properties"][field]
        for field in (
            "webmap",
            "manifest",
            "projectManifest",
            "landingGeometryPmtiles",
            "landingGeometryProfile",
        )
    )
    assert (
        feature["properties"]["landingExtentSource"]
        == "Exact union of 197 model footprints"
    )
    assert feature["properties"]["extentSource"].startswith("Union of 197")
    assert "197-model 1D steady BLE corpus" in profiles
    assert profiles.count(f'"{project_id}"') == 1
    assert "groupId" not in profiles.split(f'"{project_id}"', 1)[1].split("},", 1)[0]
    assert "AL03130002" in page
    assert page.count("Alabama Middle Chattahoochee–Lake Harding BLE") == 1
    assert "20260925Tupper-guadalupe02" in page


def test_austin_oyster_is_one_exact_source_qualification_candidate() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    supplement_source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))
    project_id = "austin-oyster-12040205"
    features = [item for item in supplement["features"] if item["id"] == project_id]

    assert len(features) == 1
    feature = features[0]
    geometry = shape(feature["geometry"])
    assert geometry.geom_type == "Polygon"
    assert geometry.is_valid
    assert not geometry.equals(box(*feature["bbox"]))
    assert list(geometry.bounds) == feature["bbox"]
    assert feature["properties"]["crsDefinition"] == "EPSG:6588"
    assert feature["properties"]["status"] == "Source qualification candidate"
    assert feature["properties"]["viewerType"] == "Qualification candidate"
    assert all(
        not feature["properties"][field]
        for field in (
            "webmap",
            "manifest",
            "projectManifest",
            "landingGeometryPmtiles",
            "landingGeometryProfile",
        )
    )
    assert (
        feature["properties"]["landingExtentSource"] == "Exact model footprint"
    )
    assert "HdfProject.get_project_extent" in feature["properties"]["extentSource"]
    assert feature["properties"]["details"].startswith("https://")
    assert feature["properties"]["recordOfDeficiencies"].startswith("https://")
    assert "reached unsteady-solver startup" in feature["properties"]["notes"]
    assert profiles.count(f'"{project_id}"') == 1
    assert "HEC-RAS 5.0.7 source; unsteady-start validated" in profiles
    assert "20260925Tupper-guadalupe02" in page


def test_upper_guadalupe_is_one_group_with_four_exact_project_links() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    catalog_source = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-projects-data.js"
    ).read_text(encoding="utf-8")
    rod = (
        ROOT / "agent_tasks" / "2026-09-25_upper_guadalupe_record_of_deficiencies.md"
    ).read_text(encoding="utf-8")
    config = json.loads(
        (ROOT / "agent_tasks" / "rasexamples_extent_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    catalog = json.loads(catalog_source.removeprefix(prefix).removesuffix(";\n"))
    expected_ids = [
        "upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a",
        "upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b",
        "upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4",
        "upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f",
    ]
    configured = [
        item for item in config["projects"] if item["id"] in expected_ids
    ]
    features = [
        feature for feature in catalog["features"] if feature["id"] in expected_ids
    ]

    assert [item["id"] for item in configured] == expected_ids
    assert [feature["id"] for feature in features] == expected_ids
    assert all(
        feature["properties"]["status"] == "Source qualification candidate"
        for feature in features
    )
    assert all(
        feature["properties"]["viewerType"] == "Qualification candidate"
        for feature in features
    )
    assert all(
        not feature["properties"].get(field)
        for feature in features
        for field in ("webmap", "manifest", "projectManifest")
    )
    assert all(
        "2026-09-25_upper_guadalupe_record_of_deficiencies.md"
        in feature["properties"]["details"]
        for feature in features
    )
    assert [item["details"].rsplit("#", 1)[-1] for item in configured] == [
        f"upgu{number}" for number in range(1, 5)
    ]
    assert all(f"### UPGU{number}" in rod for number in range(1, 5))
    assert profiles.count('groupId: "upper-guadalupe"') == 4
    assert profiles.count('title: "Upper Guadalupe Model Suite"') == 1
    assert "2026-09-25_upper_guadalupe_record_of_deficiencies.md" in profiles
    assert "fresh unsteady-start evidence applies only to UPGU1" in profiles
    assert "owned unsteady-solver startup" in profiles
    assert "not solver-start qualified" in profiles
    assert page.count("FEMA Upper Guadalupe eBFE (12100201)") == 1
    assert "20260925Tupper-guadalupe02" in page

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
    assert list(unary_union(geometries).bounds) == pytest.approx([
        -99.69714999942667,
        29.796267715490476,
        -98.17561174692321,
        30.26653385380409,
    ])


def test_pedernales_is_one_exact_530_model_corpus_entry() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    supplement_source = (
        ROOT
        / "docs"
        / "assets"
        / "javascripts"
        / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))
    project_id = "pedernales-12090206"
    features = [item for item in supplement["features"] if item["id"] == project_id]

    assert len(features) == 1
    feature = features[0]
    geometry = shape(feature["geometry"])
    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid
    assert not geometry.equals(box(*feature["bbox"]))
    assert list(geometry.bounds) == feature["bbox"]
    assert feature["bbox"] == pytest.approx(
        [-99.333429740989, 30.097184696581284, -98.05629526827822, 30.459610125321067]
    )
    assert feature["properties"]["landingExtentSource"] == (
        "Exact union of 530 active model footprints"
    )
    assert "Union of 530 HdfProject.get_project_extent" in (
        feature["properties"]["extentSource"]
    )
    assert all(
        not feature["properties"][field]
        for field in (
            "webmap",
            "manifest",
            "projectManifest",
            "landingGeometryPmtiles",
            "landingGeometryProfile",
        )
    )
    assert profiles.count(f'"{project_id}"') == 1
    assert "530-model 1D steady BLE corpus" in profiles
    assert "one exact union outline and one table row" in page
    assert page.count("FEMA Pedernales eBFE (12090206)") == 1
    assert "20260925Tpedernales-cibolo-medina02" in page


def test_cibolo_and_medina_exact_dashboard_entries_are_grouped_correctly() -> None:
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    profiles = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-project-profiles.js"
    ).read_text(encoding="utf-8")
    supplement_source = (
        ROOT
        / "docs"
        / "assets"
        / "javascripts"
        / "ras-example-project-supplements.js"
    ).read_text(encoding="utf-8")
    prefix = "window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = "
    supplement = json.loads(supplement_source.removeprefix(prefix).removesuffix(";\n"))
    by_id = {feature["id"]: feature for feature in supplement["features"]}

    cibolo = by_id["cibolo-12100304"]
    cibolo_geometry = shape(cibolo["geometry"])
    assert cibolo_geometry.geom_type == "Polygon"
    assert cibolo_geometry.is_valid
    assert not cibolo_geometry.equals(box(*cibolo["bbox"]))
    assert list(cibolo_geometry.bounds) == cibolo["bbox"]
    assert cibolo["properties"]["crsDefinition"] == "EPSG:2278"
    assert all(
        not cibolo["properties"][field]
        for field in ("webmap", "manifest", "projectManifest")
    )

    medina_ids = [
        "medina-leon1-12100302",
        "medina-leon2-12100302",
        "medina-leon3-12100302",
        "medina-middle-lower-medina-12100302",
        "medina-upper-medina-headwaters-12100302",
    ]
    medina = [by_id[project_id] for project_id in medina_ids]
    geometries = [shape(feature["geometry"]) for feature in medina]
    assert all(geometry.geom_type == "Polygon" for geometry in geometries)
    assert all(geometry.is_valid for geometry in geometries)
    assert all(
        not geometry.equals(box(*feature["bbox"]))
        for feature, geometry in zip(medina, geometries, strict=True)
    )
    assert all(
        list(geometry.bounds) == feature["bbox"]
        for feature, geometry in zip(medina, geometries, strict=True)
    )
    assert list(unary_union(geometries).bounds) == pytest.approx(
        [-99.59062442992771, 29.148980516486763, -98.40305457755368, 29.96342500081802]
    )
    assert all(
        not feature["properties"][field]
        for feature in medina
        for field in ("webmap", "manifest", "projectManifest")
    )
    assert medina[-1]["properties"]["status"] == "Critical source gap — blocked"
    assert medina[-1]["properties"]["viewerType"] == "Blocked source model"
    assert "not downstream-usable" in medina[-1]["properties"]["notes"]
    assert profiles.count('groupId: "medina"') == 5
    assert profiles.count('title: "Medina Model Suite"') == 1
    assert all(
        feature["properties"]["status"] == "Qualified: unsteady start"
        for feature in medina[:4]
    )
    assert all(
        "owned unsteady-solver startup" in feature["properties"]["notes"]
        for feature in medina[:4]
    )
    assert "HEC-RAS 5.0.7 source; unsteady-start validated" in profiles
    assert profiles.count(
        "HEC-RAS 6.4.1 source; unsteady-start validated"
    ) == 4
    assert 'variantLabel: "Upper Medina Headwaters — BLOCKED"' in profiles
    assert page.count("FEMA Cibolo eBFE (12100304)") == 1
    assert page.count("FEMA Medina eBFE (12100302)") == 1
    assert "missing compiled modified terrain is a critical 2D source" in page


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
