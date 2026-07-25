from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "validate_public_webgis_release.py"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_public_webgis_release",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def response(
    status: int,
    document=None,
    *,
    cache_control: str = "",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
):
    response_headers = dict(headers or {})
    if cache_control:
        response_headers["cache-control"] = cache_control
    return validator.HttpResult(
        status=status,
        headers=response_headers,
        content=content
        if content is not None
        else json.dumps(document or {}).encode("utf-8"),
    )


def test_validate_release_exercises_public_delivery_contract(monkeypatch):
    release_id = "release-20260725"
    release_root = (
        "https://rascommander.info/data/rasexamples/hec-ras-7.0/"
        f"releases/{release_id}"
    )
    manifest_url = f"{release_root}/projects/muncie/viewer/manifest.json"
    requests: list[str] = []

    index = {
        "type": "FeatureCollection",
        "releaseId": release_id,
        "features": [
            {
                "properties": {
                    "projectId": "muncie",
                    "title": "Muncie",
                    "manifest": manifest_url,
                }
            }
        ],
    }
    manifest = {
        "resources": {
            "geometry": {"type": "vector-pmtiles", "href": "tiles/geometry.pmtiles"},
            "depth": {
                "type": "cog",
                "href": "../archive/depth.tif",
                "serviceAsset": f"releases/{release_id}/projects/muncie/depth",
                "serviceRevision": "revision-1",
                "bounds": [-85.1, 40.0, -84.9, 40.2],
            },
        },
        "services": {
            "numericRaster": {
                "baseUrl": "/ras-raster",
                "samplePath": "/sample",
                "statisticsPath": "/stats",
                "tilePath": "/tiles/{z}/{x}/{y}.png",
                "cogPath": "/cog",
            }
        },
    }

    def fake_request(url: str, *, headers=None, timeout=30):
        requests.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path == "/ras-raster/health":
            return response(
                200,
                {"releaseId": release_id, "assets": 1238},
                cache_control="no-store",
            )
        if parsed.path == "/ras-raster/ready":
            return response(200, {"status": "ready"}, cache_control="no-store")
        if parsed.path.endswith("/current/release.json"):
            return response(
                200,
                {"releaseId": release_id},
                cache_control="no-cache, no-transform",
            )
        if parsed.path.endswith("/example-projects.geojson"):
            return response(200, index, cache_control="public, immutable")
        if parsed.path.endswith("/viewer/manifest.json"):
            return response(200, manifest, cache_control="public, immutable")
        if parsed.path.endswith(".pmtiles"):
            return response(
                206,
                cache_control="public, immutable, no-transform",
                content=b"PMTiles",
                headers={"content-range": "bytes 0-16383/20000"},
            )
        if parsed.path.endswith("/archive/depth.tif"):
            return response(
                206,
                cache_control="public, immutable, no-transform",
                content=b"TIFF",
            )
        if parsed.path == "/ras-raster/sample" and query.get("asset") == [
            "__missing__"
        ]:
            return response(404, {"detail": "missing"}, cache_control="no-store")
        if parsed.path == "/ras-raster/sample":
            return response(200, {"state": "value", "value": 1.0})
        if parsed.path == "/ras-raster/stats":
            return response(200, {"domain": {"minimum": 0, "maximum": 10}})
        if parsed.path.startswith("/ras-raster/tiles/"):
            return response(200, content=b"\x89PNG\r\n")
        if parsed.path == "/ras-raster/cog":
            return response(
                206,
                cache_control="public, immutable, no-transform",
                content=b"TIFF",
            )
        if parsed.path.endswith("/__missing-validation-asset__.json"):
            return response(404, cache_control="no-store")
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(validator, "request", fake_request)

    result = validator.validate_release(
        "https://rascommander.info",
        release_id,
    )

    assert result["releaseId"] == release_id
    assert result["assets"] == 1238
    assert result["projectManifest"] == manifest_url
    assert any("/ras-raster/health?release=release-20260725" in url for url in requests)
    assert any("/ras-raster/ready?release=release-20260725" in url for url in requests)
    assert any("/ras-raster/tiles/" in url for url in requests)
    assert any("range=bytes%3D0-16383" in url for url in requests)


def test_tile_for_point_stays_within_web_mercator_grid():
    assert validator.tile_for_point(-180, 90, 2) == (0, 0)
    assert validator.tile_for_point(180, -90, 2) == (3, 3)
