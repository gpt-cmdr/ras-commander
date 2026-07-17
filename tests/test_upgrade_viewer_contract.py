from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "upgrade_viewer_contract.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("upgrade_viewer_contract", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_metadata_normalization_rejects_dataframe_missing_values() -> None:
    module = load_script()

    assert module._metadata_text(float("nan")) == ""
    assert module._metadata_text("<NA>") == ""
    assert module._metadata_text(" Named Plan ") == "Named Plan"
    assert module._numbered_id("p", float("nan")) == ""
    assert module._numbered_id("g", 4.0) == "g04"


def test_upgrade_adds_titles_and_all_primary_geometry_visibility() -> None:
    module = load_script()
    archive = {
        "schema_version": "2.5",
        "geometry": [{"geom_id": "g01"}, {"geom_id": "g02"}],
        "results": [{"plan_id": "p01", "geom_id": "g02", "plan_title": "Old"}],
    }
    viewer = {
        "groups": [
            {"id": "ras-geometry-g01", "name": "Geometry g01", "visible": False},
            {"id": "ras-geometry-g02", "name": "Geometry g02", "visible": True},
        ],
        "tilesets": [
            {
                "type": "vector",
                "layers": [
                    {"id": "one", "groupId": "ras-geometry-g01", "visible": False},
                    {"id": "two", "groupId": "ras-geometry-g01", "visible": False},
                    {"id": "other", "groupId": "ras-geometry-g02", "visible": True},
                ],
            }
        ],
    }

    module.update_archive_metadata(
        archive,
        geometry_titles={"g01": "Base Geometry", "g02": "Alternate"},
        plan_metadata={"p01": {"plan_title": "Existing Conditions", "geom_id": "g01"}},
        schema_version="2.6",
    )
    module.apply_geometry_visibility(
        viewer,
        primary_geometry="g01",
        show_all_primary_geometry=True,
        geometry_titles={"g01": "Base Geometry", "g02": "Alternate"},
    )

    assert archive["schema_version"] == "2.6"
    assert archive["geometry"][0]["geom_title"] == "Base Geometry"
    assert archive["results"][0] == {
        "plan_id": "p01",
        "geom_id": "g01",
        "plan_title": "Existing Conditions",
    }
    assert viewer["groups"][0] == {
        "id": "ras-geometry-g01",
        "name": "Geometry 01 - Base Geometry",
        "visible": True,
    }
    assert [layer["visible"] for layer in viewer["tilesets"][0]["layers"]] == [
        True,
        True,
        False,
    ]
