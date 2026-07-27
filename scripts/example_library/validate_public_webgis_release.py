#!/usr/bin/env python
"""Exercise one immutable Example Library release through the public origin."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    content: bytes

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> HttpResult:
    """Return both success and expected HTTP error responses."""

    request_object = Request(url, headers=headers or {}, method="GET")
    try:
        response = urlopen(request_object, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        return HttpResult(
            status=response.status,
            headers={key.lower(): value for key, value in response.headers.items()},
            content=response.read(),
        )


def require_status(result: HttpResult, expected: int, label: str) -> None:
    if result.status != expected:
        raise RuntimeError(f"{label} returned HTTP {result.status}, expected {expected}")


def require_cache_token(result: HttpResult, token: str, label: str) -> None:
    cache_control = result.headers.get("cache-control", "").lower()
    if token.lower() not in cache_control:
        raise RuntimeError(
            f"{label} cache policy {cache_control!r} does not contain {token!r}"
        )


def tile_for_point(longitude: float, latitude: float, zoom: int) -> tuple[int, int]:
    latitude = max(-85.05112878, min(85.05112878, latitude))
    scale = 2**zoom
    x = int((longitude + 180.0) / 360.0 * scale)
    latitude_radians = math.radians(latitude)
    y = int(
        (
            1.0
            - math.asinh(math.tan(latitude_radians)) / math.pi
        )
        / 2.0
        * scale
    )
    return max(0, min(scale - 1, x)), max(0, min(scale - 1, y))


def find_muncie_manifest(index: dict[str, Any], needle: str) -> str:
    for feature in index.get("features") or []:
        properties = feature.get("properties") or {}
        project_id = str(properties.get("projectId") or "")
        title = str(properties.get("title") or "")
        if needle.lower() in f"{project_id} {title}".lower():
            manifest = properties.get("manifest")
            if manifest:
                return str(manifest)
    raise RuntimeError(f"No project matching {needle!r} has a manifest URL")


def find_numeric_resource(manifest: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for resource_id, resource in (manifest.get("resources") or {}).items():
        if (
            resource.get("type") == "cog"
            and resource.get("serviceAsset")
            and resource.get("serviceRevision")
            and resource.get("bounds")
        ):
            return resource_id, resource
    raise RuntimeError("The validation project has no queryable numeric COG")


def find_pmtiles_resource(manifest: dict[str, Any]) -> dict[str, Any]:
    for resource in (manifest.get("resources") or {}).values():
        if str(resource.get("type") or "").endswith("pmtiles") and resource.get(
            "href"
        ):
            return resource
    raise RuntimeError("The validation project has no PMTiles resource")


def validate_release(
    origin: str,
    release_id: str,
    *,
    project_needle: str = "muncie",
) -> dict[str, Any]:
    origin = origin.rstrip("/")
    version_root = f"{origin}/data/rasexamples/hec-ras-7.0"
    release_root = f"{version_root}/releases/{release_id}"

    release_query = urlencode({"release": release_id})
    health = request(f"{origin}/ras-raster/health?{release_query}")
    require_status(health, 200, "Raster health")
    require_cache_token(health, "no-store", "Raster health")
    health_document = health.json()
    if health_document.get("releaseId") != release_id:
        raise RuntimeError("Raster health reports a different active release")

    ready = request(f"{origin}/ras-raster/ready?{release_query}")
    require_status(ready, 200, "Raster readiness")
    require_cache_token(ready, "no-store", "Raster readiness")
    if ready.json().get("status") != "ready":
        raise RuntimeError("Raster readiness does not report ready")

    current = request(f"{version_root}/current/release.json?{release_query}")
    require_status(current, 200, "Current release pointer")
    require_cache_token(current, "no-cache", "Current release pointer")
    if current.json().get("releaseId") != release_id:
        raise RuntimeError("The public current pointer has not switched releases")

    index = request(f"{release_root}/example-projects.geojson")
    require_status(index, 200, "Versioned project index")
    require_cache_token(index, "immutable", "Versioned project index")
    index_document = index.json()
    if index_document.get("releaseId") != release_id:
        raise RuntimeError("The project index has the wrong release identity")
    manifest_url = find_muncie_manifest(index_document, project_needle)
    if f"/releases/{release_id}/" not in manifest_url:
        raise RuntimeError("The project index does not use immutable manifest URLs")

    manifest_response = request(manifest_url)
    require_status(manifest_response, 200, "Project manifest")
    require_cache_token(manifest_response, "immutable", "Project manifest")
    manifest = manifest_response.json()

    pmtiles = find_pmtiles_resource(manifest)
    pmtiles_url = urljoin(manifest_url, str(pmtiles["href"]))
    pmtiles_range = request(pmtiles_url, headers={"Range": "bytes=0-16383"})
    require_status(pmtiles_range, 206, "PMTiles range")
    require_cache_token(pmtiles_range, "immutable", "PMTiles range")
    require_cache_token(pmtiles_range, "no-transform", "PMTiles range")
    if not pmtiles_range.headers.get("content-range", "").startswith("bytes 0-"):
        raise RuntimeError("PMTiles response has no valid Content-Range")

    _, numeric = find_numeric_resource(manifest)
    cog_url = urljoin(manifest_url, str(numeric["href"]))
    cog_range = request(cog_url, headers={"Range": "bytes=0-16383"})
    require_status(cog_range, 206, "Direct COG range")
    require_cache_token(cog_range, "immutable", "Direct COG range")
    require_cache_token(cog_range, "no-transform", "Direct COG range")

    service = (manifest.get("services") or {}).get("numericRaster") or {}
    service_base = urljoin(manifest_url, str(service.get("baseUrl") or "/ras-raster"))
    bounds = [float(value) for value in numeric["bounds"]]
    longitude = (bounds[0] + bounds[2]) / 2
    latitude = (bounds[1] + bounds[3]) / 2
    common = {
        "asset": numeric["serviceAsset"],
        "revision": numeric["serviceRevision"],
    }
    sample = request(
        f"{service_base.rstrip('/')}/{str(service.get('samplePath') or '/sample').lstrip('/')}?"
        + urlencode({**common, "lng": longitude, "lat": latitude})
    )
    require_status(sample, 200, "Numeric raster sample")

    stats = request(
        f"{service_base.rstrip('/')}/{str(service.get('statisticsPath') or '/stats').lstrip('/')}?"
        + urlencode(
            {
                **common,
                "bbox": ",".join(str(value) for value in bounds),
                "width": 512,
                "height": 512,
                "exact": "false",
            }
        )
    )
    require_status(stats, 200, "Viewport statistics")
    domain = stats.json().get("domain") or {}

    zoom = min(12, int(numeric.get("maxzoom") or 12))
    tile_x, tile_y = tile_for_point(longitude, latitude, zoom)
    tile_parameters: dict[str, Any] = dict(common)
    if domain.get("minimum") is not None and domain.get("maximum") is not None:
        tile_parameters["minimum"] = domain["minimum"]
        tile_parameters["maximum"] = domain["maximum"]
    tile_path = str(service.get("tilePath") or "/tiles/{z}/{x}/{y}.png").format(
        z=zoom,
        x=tile_x,
        y=tile_y,
    )
    tile = request(
        f"{service_base.rstrip('/')}/{tile_path.lstrip('/')}?"
        + urlencode(tile_parameters)
    )
    require_status(tile, 200, "Styled raster tile")
    if not tile.content.startswith(b"\x89PNG"):
        raise RuntimeError("Styled raster tile is not a PNG")

    bounded_cog = request(
        f"{service_base.rstrip('/')}/{str(service.get('cogPath') or '/cog').lstrip('/')}?"
        + urlencode({**common, "range": "bytes=0-16383"})
    )
    require_status(bounded_cog, 206, "Bounded COG range")
    require_cache_token(bounded_cog, "immutable", "Bounded COG range")
    require_cache_token(bounded_cog, "no-transform", "Bounded COG range")

    missing_api = request(
        f"{service_base.rstrip('/')}/{str(service.get('samplePath') or '/sample').lstrip('/')}?"
        + urlencode({"asset": "__missing__", "lng": longitude, "lat": latitude})
    )
    require_status(missing_api, 404, "Missing API asset")
    require_cache_token(missing_api, "no-store", "Missing API asset")

    missing_static = request(f"{release_root}/__missing-validation-asset__.json")
    require_status(missing_static, 404, "Missing static asset")
    require_cache_token(missing_static, "no-store", "Missing static asset")

    return {
        "releaseId": release_id,
        "assets": health_document.get("assets"),
        "projectManifest": manifest_url,
        "numericAsset": numeric["serviceAsset"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://rascommander.info")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--project-contains", default="muncie")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = validate_release(
        args.origin,
        args.release_id,
        project_needle=args.project_contains,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
