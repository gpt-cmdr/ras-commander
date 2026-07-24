from pathlib import Path


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
    assert "<th scope=\"col\">CRS</th>" not in page
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
