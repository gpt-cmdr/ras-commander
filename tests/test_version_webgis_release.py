from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "version_webgis_release.py"
)
SPEC = importlib.util.spec_from_file_location("version_webgis_release", SCRIPT_PATH)
assert SPEC and SPEC.loader
versioner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versioner)


def make_release(tmp_path: Path) -> Path:
    root = tmp_path / "hec-ras-7.0"
    viewer = root / "projects" / "muncie" / "viewer"
    viewer.mkdir(parents=True)
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "public_base": "/data/rasexamples/hec-ras-7.0",
                "items": [
                    {
                        "href": (
                            "/data/rasexamples/hec-ras-7.0/projects/"
                            "muncie/project.json"
                        )
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "example-projects.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "manifest": (
                                "https://rascommander.info/data/rasexamples/"
                                "hec-ras-7.0/projects/muncie/viewer/manifest.json"
                            ),
                            "webmap": (
                                "../viewer/?manifest=https%3A%2F%2Frascommander.info"
                                "%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects"
                                "%2Fmuncie%2Fviewer%2Fmanifest.json"
                            ),
                        },
                        "geometry": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "raster-assets.json").write_text(
        json.dumps(
            {
                "schema": "rascommander.raster-assets/v1",
                "assets": {
                    "projects/muncie/depth": {
                        "path": "projects/muncie/archive/depth.tif",
                        "revision": "revision-1",
                        "preset": "rasmapper.depth",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "snapshot.json").write_text(
        json.dumps({"catalog": "/data/rasexamples/hec-ras-7.0/catalog.json"}),
        encoding="utf-8",
    )
    (viewer / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "rascommander.maplibre/v2",
                "resources": {
                    "depth": {
                        "type": "cog",
                        "href": "../archive/depth.tif",
                        "serviceAsset": "projects/muncie/depth",
                        "serviceRevision": "revision-1",
                    }
                },
                "tilesets": [
                    {
                        "id": "depth",
                        "serviceAsset": "projects/muncie/depth",
                        "serviceRevision": "revision-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_prepare_versioned_overlay_rewrites_only_json_metadata(tmp_path: Path):
    source = make_release(tmp_path)
    overlay = tmp_path / "overlay"

    result = versioner.prepare_versioned_overlay(source, overlay, "release-20260725")

    assert result["releaseId"] == "release-20260725"
    catalog = json.loads((overlay / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["releaseId"] == "release-20260725"
    assert catalog["public_base"].endswith("/releases/release-20260725")
    assert "/releases/release-20260725/projects/" in catalog["items"][0]["href"]

    geojson = json.loads(
        (overlay / "example-projects.geojson").read_text(encoding="utf-8")
    )
    properties = geojson["features"][0]["properties"]
    assert geojson["releaseId"] == "release-20260725"
    assert "/releases/release-20260725/projects/" in properties["manifest"]
    assert "%2Freleases%2Frelease-20260725%2Fprojects%2F" in properties["webmap"]

    raster_catalog = json.loads(
        (overlay / "raster-assets.json").read_text(encoding="utf-8")
    )
    asset_id = "releases/release-20260725/projects/muncie/depth"
    assert raster_catalog["releaseId"] == "release-20260725"
    assert list(raster_catalog["assets"]) == [asset_id]
    assert raster_catalog["assets"][asset_id]["path"].startswith(
        "releases/release-20260725/projects/"
    )

    manifest = json.loads(
        (overlay / "projects/muncie/viewer/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["resources"]["depth"]["href"] == "../archive/depth.tif"
    assert manifest["resources"]["depth"]["serviceAsset"] == asset_id
    assert manifest["tilesets"][0]["serviceAsset"] == asset_id
    assert json.loads((overlay / "release.json").read_text(encoding="utf-8"))[
        "releaseId"
    ] == "release-20260725"


def test_prepare_versioned_overlay_rejects_missing_required_metadata(tmp_path: Path):
    source = tmp_path / "hec-ras-7.0"
    source.mkdir()

    with pytest.raises(FileNotFoundError, match="required metadata"):
        versioner.prepare_versioned_overlay(
            source,
            tmp_path / "overlay",
            "release-20260725",
        )


@pytest.mark.parametrize("release_id", ["", "../release", "release/one", "-release"])
def test_validate_release_id_rejects_unsafe_values(release_id: str):
    with pytest.raises(ValueError):
        versioner.validate_release_id(release_id)
