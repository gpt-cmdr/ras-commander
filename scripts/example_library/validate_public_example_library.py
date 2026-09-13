#!/usr/bin/env python
"""Validate the public RAS Commander Example Project Library link graph.

The landing page is only the outer shell.  This validator follows the catalog
through each project viewer to the viewer and project manifests so that a
successful HTML response cannot hide missing project data.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import socket
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qs,
    parse_qsl,
    urlencode,
    urldefrag,
    urljoin,
    unquote,
    urlsplit,
    urlunsplit,
)
from urllib.request import Request, urlopen


DEFAULT_LIBRARY_URL = "https://rascommander.info/ras/examples/example-projects/"
DEFAULT_CATALOG_URL = (
    "https://rascommander.info/data/rasexamples/hec-ras-7.0/current/"
    "example-projects.geojson"
)
USER_AGENT = "rascommander-example-library-validator/1.0"
MAX_CATALOG_BYTES = 20 * 1024 * 1024
JSON_ENDPOINT_TARGETS = {"manifest", "projectManifest", "webmap-manifest"}
PMTILES_HEADER_BYTES = 127
MAX_PMTILES_METADATA_BYTES = 2 * 1024 * 1024
MAX_PMTILES_ROOT_BYTES = 16 * 1024 * 1024
MAX_PMTILES_DECOMPRESSED_BYTES = 64 * 1024 * 1024
LANDING_GEOMETRY_PROFILES = {
    "ras-1d-corpus-v1": {
        "ras_model_extent": (7, 11),
        "ras_river_centerlines": (8, 14),
        "ras_cross_sections": (10, 14),
        "ras_bank_lines": (10, 14),
    }
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FALLBACK_CATALOG = (
    REPOSITORY_ROOT / "docs" / "assets" / "javascripts" / "ras-example-projects-data.js"
)
DEFAULT_SUPPLEMENTS_CATALOG = (
    REPOSITORY_ROOT
    / "docs"
    / "assets"
    / "javascripts"
    / "ras-example-project-supplements.js"
)


@dataclass(frozen=True)
class Finding:
    """One independently reportable validation result."""

    project_id: str
    target: str
    ok: bool
    url: str = ""
    status: int | None = None
    message: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """Complete link-graph validation result."""

    findings: tuple[Finding, ...]
    project_count: int

    @property
    def ok(self) -> bool:
        return bool(self.findings) and all(finding.ok for finding in self.findings)

    @property
    def failure_count(self) -> int:
        return sum(not finding.ok for finding in self.findings)


@dataclass(frozen=True)
class _Endpoint:
    project_id: str
    target: str
    url: str
    profile: str = ""


@dataclass(frozen=True)
class _HttpResult:
    ok: bool
    status: int | None
    message: str
    body: bytes = b""
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class _PmtilesInfo:
    metadata: Mapping[str, Any]
    minzoom: int
    maxzoom: int
    root_entries: int


class _IdCollector(HTMLParser):
    """Collect HTML element IDs for fragment validation."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.casefold() == "id" and value:
                self.ids.add(value)


def _cache_control_has_no_store(value: str) -> bool:
    directives = [item.strip().split("=", 1)[0].lower() for item in value.split(",")]
    return "no-store" in directives


def _request(
    url: str,
    *,
    timeout: float,
    retries: int,
    read_body: bool,
) -> _HttpResult:
    headers = {
        "Accept": "application/geo+json, application/json, text/html;q=0.9, */*;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if not read_body:
        # A GET is more representative than HEAD for static hosting and reverse
        # proxies, while the range keeps accidental artifact downloads bounded.
        headers["Range"] = "bytes=0-65535"

    last_result: _HttpResult | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                status = response.getcode()
                if read_body:
                    body = response.read(MAX_CATALOG_BYTES + 1)
                    if len(body) > MAX_CATALOG_BYTES:
                        return _HttpResult(
                            False,
                            status,
                            f"response exceeds {MAX_CATALOG_BYTES} bytes",
                        )
                else:
                    # Force at least one response byte through the connection,
                    # then close without consuming a server that ignored Range.
                    response.read(1)
                    body = b""
                return _HttpResult(True, status, "", body)
        except HTTPError as exc:
            cache_control = exc.headers.get("Cache-Control", "")
            cache_note = ""
            if not _cache_control_has_no_store(cache_control):
                shown = cache_control or "<missing>"
                cache_note = f"; Cache-Control lacks no-store ({shown})"
            last_result = _HttpResult(
                False,
                exc.code,
                f"HTTP {exc.code}{cache_note}",
            )
            if exc.code < 500 or attempt == retries:
                return last_result
        except (TimeoutError, socket.timeout, URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            last_result = _HttpResult(False, None, f"request failed: {reason}")
            if attempt == retries:
                return last_result

        time.sleep(min(0.25 * (2**attempt), 2.0))

    return last_result or _HttpResult(False, None, "request failed")


def _request_byte_range(
    url: str,
    *,
    start: int,
    end: int,
    timeout: float,
    retries: int,
) -> _HttpResult:
    """Read one exact HTTP byte range and reject full-body fallbacks."""

    expected_length = end - start + 1
    if start < 0 or end < start:
        return _HttpResult(False, None, f"invalid byte range {start}-{end}")
    last_result: _HttpResult | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/vnd.pmtiles, application/octet-stream",
                    "Accept-Encoding": "identity",
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": USER_AGENT,
                },
            )
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                status = response.getcode()
                headers = {
                    name.lower(): value for name, value in response.headers.items()
                }
                if status != 206:
                    response.read(min(expected_length + 1, 65536))
                    return _HttpResult(
                        False,
                        status,
                        "server did not honor the byte-range request with HTTP 206",
                        headers=headers,
                    )
                content_range = headers.get("content-range", "")
                expected_prefix = f"bytes {start}-{end}/"
                if not content_range.startswith(expected_prefix):
                    return _HttpResult(
                        False,
                        status,
                        f"unexpected Content-Range {content_range!r}",
                        headers=headers,
                    )
                body = response.read(expected_length + 1)
                if len(body) != expected_length:
                    return _HttpResult(
                        False,
                        status,
                        f"byte range returned {len(body)} bytes; expected {expected_length}",
                        body,
                        headers,
                    )
                return _HttpResult(True, status, "", body, headers)
        except HTTPError as exc:
            cache_control = exc.headers.get("Cache-Control", "")
            cache_note = ""
            if not _cache_control_has_no_store(cache_control):
                shown = cache_control or "<missing>"
                cache_note = f"; Cache-Control lacks no-store ({shown})"
            last_result = _HttpResult(
                False,
                exc.code,
                f"HTTP {exc.code}{cache_note}",
            )
            if exc.code < 500 or attempt == retries:
                return last_result
        except (TimeoutError, socket.timeout, URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            last_result = _HttpResult(False, None, f"request failed: {reason}")
            if attempt == retries:
                return last_result

        time.sleep(min(0.25 * (2**attempt), 2.0))

    return last_result or _HttpResult(False, None, "request failed")


def _decompress_pmtiles_block(
    body: bytes,
    compression: int,
    *,
    label: str,
    limit: int,
) -> bytes:
    if compression == 1:
        decoded = body
    elif compression == 2:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            decoded = stream.read(limit + 1)
    else:
        raise ValueError(
            f"unsupported PMTiles {label} compression {compression}; "
            "expected none or gzip"
        )
    if len(decoded) > limit:
        raise ValueError(f"PMTiles {label} exceeds the decoded validation limit")
    return decoded


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data) and shift <= 63:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise ValueError("invalid PMTiles directory varint")


def _directory_entry_count(data: bytes) -> int:
    """Decode enough of a PMTiles v3 directory to prove structural validity."""
    count, position = _read_varint(data, 0)
    if count <= 0 or count > 10_000_000:
        raise ValueError(f"invalid PMTiles root directory entry count {count}")
    arrays: list[list[int]] = []
    for _ in range(4):
        values = []
        for _entry in range(count):
            value, position = _read_varint(data, position)
            values.append(value)
        arrays.append(values)
    if position != len(data):
        raise ValueError("PMTiles root directory has trailing or malformed bytes")
    lengths = arrays[2]
    if any(length <= 0 for length in lengths):
        raise ValueError("PMTiles root directory contains an empty entry")
    return count


def _pmtiles_metadata(
    url: str,
    *,
    timeout: float,
    retries: int,
) -> tuple[_PmtilesInfo | None, _HttpResult]:
    """Read and validate a PMTiles v3 header, root directory, and metadata."""

    header_result = _request_byte_range(
        url,
        start=0,
        end=PMTILES_HEADER_BYTES - 1,
        timeout=timeout,
        retries=retries,
    )
    if not header_result.ok:
        return None, header_result
    header = header_result.body
    if header[:7] != b"PMTiles" or header[7] != 3:
        return None, _HttpResult(
            False,
            header_result.status,
            "response is not a PMTiles v3 archive",
        )
    root_offset, root_length = struct.unpack_from("<QQ", header, 8)
    metadata_offset, metadata_length = struct.unpack_from("<QQ", header, 24)
    tile_data_offset, tile_data_length = struct.unpack_from("<QQ", header, 56)
    internal_compression = header[97]
    tile_type = header[99]
    minzoom = header[100]
    maxzoom = header[101]
    if tile_type != 1:
        return None, _HttpResult(
            False,
            header_result.status,
            f"PMTiles archive is not vector MVT data (tile type {tile_type})",
        )
    if not 0 < metadata_length <= MAX_PMTILES_METADATA_BYTES:
        return None, _HttpResult(
            False,
            header_result.status,
            "PMTiles metadata length is missing or exceeds the validation limit",
        )
    if not 0 < root_length <= MAX_PMTILES_ROOT_BYTES:
        return None, _HttpResult(
            False,
            header_result.status,
            "PMTiles root directory length is missing or exceeds the validation limit",
        )
    if tile_data_length <= 0:
        return None, _HttpResult(
            False,
            header_result.status,
            "PMTiles tile-data section is empty",
        )
    if minzoom > maxzoom:
        return None, _HttpResult(
            False,
            header_result.status,
            f"PMTiles header has invalid zoom range {minzoom}-{maxzoom}",
        )
    content_range = (header_result.headers or {}).get("content-range", "")
    try:
        archive_length = int(content_range.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return None, _HttpResult(
            False,
            header_result.status,
            f"PMTiles header response has invalid Content-Range {content_range!r}",
        )
    for label, offset, length in (
        ("root directory", root_offset, root_length),
        ("metadata", metadata_offset, metadata_length),
        ("tile data", tile_data_offset, tile_data_length),
    ):
        if offset < PMTILES_HEADER_BYTES or offset + length > archive_length:
            return None, _HttpResult(
                False,
                header_result.status,
                f"PMTiles {label} range falls outside the archive",
            )

    metadata_result = _request_byte_range(
        url,
        start=metadata_offset,
        end=metadata_offset + metadata_length - 1,
        timeout=timeout,
        retries=retries,
    )
    if not metadata_result.ok:
        return None, metadata_result
    root_result = _request_byte_range(
        url,
        start=root_offset,
        end=root_offset + root_length - 1,
        timeout=timeout,
        retries=retries,
    )
    if not root_result.ok:
        return None, root_result
    try:
        metadata_bytes = _decompress_pmtiles_block(
            metadata_result.body,
            internal_compression,
            label="metadata",
            limit=MAX_PMTILES_METADATA_BYTES,
        )
        metadata = json.loads(metadata_bytes)
        root_bytes = _decompress_pmtiles_block(
            root_result.body,
            internal_compression,
            label="root directory",
            limit=MAX_PMTILES_DECOMPRESSED_BYTES,
        )
        root_entries = _directory_entry_count(root_bytes)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, _HttpResult(
            False,
            metadata_result.status,
            f"PMTiles structure is invalid: {exc}",
        )
    if not isinstance(metadata, Mapping):
        return None, _HttpResult(
            False,
            metadata_result.status,
            "PMTiles metadata JSON is not an object",
        )
    return _PmtilesInfo(metadata, minzoom, maxzoom, root_entries), root_result


def _check_pmtiles_endpoint(
    endpoint: _Endpoint,
    *,
    timeout: float,
    retries: int,
) -> Finding:
    expected_layers = LANDING_GEOMETRY_PROFILES[endpoint.profile]
    info, result = _pmtiles_metadata(
        endpoint.url,
        timeout=timeout,
        retries=retries,
    )
    if info is None:
        return Finding(
            endpoint.project_id,
            endpoint.target,
            False,
            url=endpoint.url,
            status=result.status,
            message=result.message,
        )
    layers = info.metadata.get("vector_layers")
    if not isinstance(layers, list) or not all(
        isinstance(layer, Mapping) for layer in layers
    ):
        message = "PMTiles metadata has no valid vector_layers array"
    elif not all(isinstance(layer.get("id"), str) for layer in layers):
        message = "PMTiles vector_layers IDs must all be strings"
    elif len({layer["id"] for layer in layers}) != len(layers):
        message = "PMTiles vector_layers IDs must be unique"
    else:
        layers_by_id = {layer["id"]: layer for layer in layers}
        actual_ids = set(layers_by_id)
        expected_ids = set(expected_layers)
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            unexpected = sorted(actual_ids - expected_ids)
            message = f"PMTiles layers do not match profile; missing={missing}, unexpected={unexpected}"
        else:
            zoom_mismatches = []
            for layer_id, (minimum, maximum) in expected_layers.items():
                layer = layers_by_id[layer_id]
                if layer.get("minzoom") != minimum or layer.get("maxzoom") != maximum:
                    zoom_mismatches.append(
                        f"{layer_id}={layer.get('minzoom')}-{layer.get('maxzoom')}"
                    )
            message = (
                "PMTiles layer zooms do not match profile: "
                + ", ".join(zoom_mismatches)
                if zoom_mismatches
                else ""
            )
            if not message:
                expected_minzoom = min(value[0] for value in expected_layers.values())
                expected_maxzoom = max(value[1] for value in expected_layers.values())
                if (info.minzoom, info.maxzoom) != (
                    expected_minzoom,
                    expected_maxzoom,
                ):
                    message = (
                        "PMTiles header zooms do not match profile: "
                        f"{info.minzoom}-{info.maxzoom}"
                    )
    return Finding(
        endpoint.project_id,
        endpoint.target,
        not message,
        url=endpoint.url,
        status=result.status,
        message=message
        or (
            f"validated {endpoint.profile} with {len(expected_layers)} vector layers "
            f"and {info.root_entries} root directory entries"
        ),
    )


def _resolved_url(base_url: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    resolved = urljoin(base_url, value.strip())
    scheme = urlsplit(resolved).scheme.lower()
    if scheme not in {"http", "https"}:
        return ""
    return resolved


def _canonical_url(url: str) -> str:
    """Return a comparison form that ignores query ordering and fragments."""

    resolved, _fragment = urldefrag(url)
    parts = urlsplit(resolved)
    host = (parts.hostname or "").lower()
    port = parts.port
    if port is not None and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    query = urlencode(
        sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True
    )
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", query, ""))


def _is_candidate(properties: Mapping[str, Any]) -> bool:
    labels = (properties.get("status"), properties.get("viewerType"))
    return any("candidate" in str(value).casefold() for value in labels if value)


def _read_catalog_assignment(path: Path, variable: str) -> Mapping[str, Any]:
    """Read one exact ``window.NAME = <JSON>;`` data assignment without eval."""

    prefix = f"window.{variable} = "
    source = path.read_text(encoding="utf-8")
    if not source.startswith(prefix):
        raise ValueError(f"expected assignment prefix {prefix!r}")
    payload = source[len(prefix) :].rstrip()
    if not payload.endswith(";"):
        raise ValueError("assignment must end with a semicolon")
    payload = payload[:-1]
    try:
        collection = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"assignment payload is not JSON: {exc}") from exc
    if not isinstance(collection, Mapping) or not isinstance(
        collection.get("features"), list
    ):
        raise ValueError("assignment must contain an object with a features array")
    return collection


def _project_id(feature: object) -> str:
    if not isinstance(feature, Mapping):
        return ""
    properties = feature.get("properties")
    property_id = properties.get("projectId") if isinstance(properties, Mapping) else ""
    return str(feature.get("id") or property_id or "")


def _merge_project_collections(
    primary: Mapping[str, Any], supplements: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """Mirror the landing page's primary-first, project-ID deduplication."""

    features = list(primary.get("features", []))
    existing_ids = {_project_id(feature) for feature in features}
    if supplements:
        for feature in supplements.get("features", []):
            identifier = _project_id(feature)
            if identifier and identifier not in existing_ids:
                features.append(feature)
                existing_ids.add(identifier)
    return {**primary, "features": features}


def _load_local_collection(
    path: Path | str | None,
    *,
    variable: str,
    target: str,
) -> tuple[Mapping[str, Any] | None, Finding | None]:
    if path is None:
        return None, None
    resolved_path = Path(path).resolve()
    try:
        collection = _read_catalog_assignment(resolved_path, variable)
    except (OSError, ValueError) as exc:
        return None, Finding(
            "library",
            target,
            False,
            url=str(resolved_path),
            message=str(exc),
        )
    return collection, Finding(
        "library",
        target,
        True,
        url=str(resolved_path),
        message=f"loaded {len(collection['features'])} features",
    )


def _local_finding(project_id: str, target: str, message: str) -> Finding:
    return Finding(project_id, target, False, message=message)


def _project_endpoints(
    feature: Mapping[str, Any],
    *,
    library_url: str,
    ordinal: int,
) -> tuple[list[_Endpoint], list[Finding]]:
    properties_value = feature.get("properties")
    if not isinstance(properties_value, Mapping):
        project_id = str(feature.get("id") or f"feature-{ordinal}")
        return [], [
            _local_finding(project_id, "catalog", "properties is not an object")
        ]

    properties = properties_value
    project_id = str(
        feature.get("id")
        or properties.get("projectId")
        or properties.get("title")
        or f"feature-{ordinal}"
    )
    candidate = _is_candidate(properties)
    endpoints: list[_Endpoint] = []
    findings: list[Finding] = []

    webmap = _resolved_url(library_url, properties.get("webmap"))
    manifest = _resolved_url(library_url, properties.get("manifest"))
    project_manifest = _resolved_url(library_url, properties.get("projectManifest"))
    landing_pmtiles_value = properties.get("landingGeometryPmtiles")
    landing_profile_value = properties.get("landingGeometryProfile")
    landing_pmtiles = _resolved_url(library_url, landing_pmtiles_value)
    landing_profile = (
        landing_profile_value.strip() if isinstance(landing_profile_value, str) else ""
    )

    if webmap:
        endpoints.append(_Endpoint(project_id, "webmap", webmap))
        manifest_parameters = parse_qs(urlsplit(webmap).query).get("manifest", [])
        if len(manifest_parameters) != 1 or not manifest_parameters[0].strip():
            findings.append(
                _local_finding(
                    project_id,
                    "webmap-manifest",
                    "viewer URL must contain exactly one non-empty manifest parameter",
                )
            )
        else:
            nested_manifest = _resolved_url(webmap, manifest_parameters[0])
            if not nested_manifest:
                findings.append(
                    _local_finding(
                        project_id,
                        "webmap-manifest",
                        "viewer manifest parameter is not an HTTP(S) URL",
                    )
                )
            else:
                endpoints.append(
                    _Endpoint(project_id, "webmap-manifest", nested_manifest)
                )
                if manifest and _canonical_url(nested_manifest) != _canonical_url(
                    manifest
                ):
                    findings.append(
                        _local_finding(
                            project_id,
                            "webmap-manifest-match",
                            "viewer manifest parameter does not match catalog manifest: "
                            f"{nested_manifest!r} != {manifest!r}",
                        )
                    )
    elif not candidate:
        findings.append(
            _local_finding(project_id, "webmap", "published project has no webmap URL")
        )

    if manifest:
        endpoints.append(_Endpoint(project_id, "manifest", manifest))
    elif not candidate:
        findings.append(
            _local_finding(
                project_id, "manifest", "published project has no manifest URL"
            )
        )

    if project_manifest:
        endpoints.append(_Endpoint(project_id, "projectManifest", project_manifest))
    elif not candidate:
        findings.append(
            _local_finding(
                project_id,
                "projectManifest",
                "published project has no projectManifest URL",
            )
        )

    if landing_pmtiles_value or landing_profile_value:
        if not landing_pmtiles:
            findings.append(
                _local_finding(
                    project_id,
                    "landingGeometryPmtiles",
                    "landing geometry PMTiles must be an HTTP(S) URL",
                )
            )
        if landing_profile not in LANDING_GEOMETRY_PROFILES:
            findings.append(
                _local_finding(
                    project_id,
                    "landingGeometryProfile",
                    f"unsupported landing geometry profile {landing_profile!r}",
                )
            )
        if landing_pmtiles and landing_profile in LANDING_GEOMETRY_PROFILES:
            endpoints.append(
                _Endpoint(
                    project_id,
                    "landingGeometryPmtiles",
                    landing_pmtiles,
                    landing_profile,
                )
            )

    for field, target in (
        ("details", "details"),
        ("recordOfDeficiencies", "recordOfDeficiencies"),
    ):
        url = _resolved_url(library_url, properties.get(field))
        if url:
            endpoints.append(_Endpoint(project_id, target, url))
        elif candidate:
            findings.append(
                _local_finding(
                    project_id,
                    target,
                    f"source qualification candidate has no {field} URL",
                )
            )

    return endpoints, findings


def _check_endpoints(
    endpoints: Iterable[_Endpoint],
    *,
    timeout: float,
    retries: int,
    workers: int,
) -> list[Finding]:
    all_endpoints = list(endpoints)
    pmtiles_endpoints = [
        endpoint
        for endpoint in all_endpoints
        if endpoint.target == "landingGeometryPmtiles"
    ]
    endpoint_list = [
        endpoint
        for endpoint in all_endpoints
        if endpoint.target != "landingGeometryPmtiles"
    ]
    request_urls = {
        endpoint.url: urldefrag(endpoint.url)[0] for endpoint in endpoint_list
    }
    unique_urls = sorted(set(request_urls.values()))
    json_urls = {
        request_urls[endpoint.url]
        for endpoint in endpoint_list
        if endpoint.target in JSON_ENDPOINT_TARGETS
    }
    html_urls = {
        request_urls[endpoint.url]
        for endpoint in endpoint_list
        if urlsplit(endpoint.url).fragment
    }
    results: dict[str, _HttpResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _request,
                url,
                timeout=timeout,
                retries=retries,
                read_body=url in json_urls or url in html_urls,
            ): url
            for url in unique_urls
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    for url in json_urls:
        result = results[url]
        if not result.ok:
            continue
        try:
            payload = json.loads(result.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            results[url] = _HttpResult(
                False,
                result.status,
                f"response is not valid JSON: {exc}",
                result.body,
            )
        else:
            if not isinstance(payload, Mapping):
                results[url] = _HttpResult(
                    False,
                    result.status,
                    "JSON response is not an object",
                    result.body,
                )

    html_ids: dict[str, set[str]] = {}
    for url in html_urls:
        result = results[url]
        if not result.ok:
            continue
        collector = _IdCollector()
        collector.feed(result.body.decode("utf-8", errors="replace"))
        html_ids[url] = collector.ids

    findings: list[Finding] = []
    for endpoint in endpoint_list:
        request_url = request_urls[endpoint.url]
        result = results[request_url]
        fragment = unquote(urlsplit(endpoint.url).fragment)
        accepted_ids = {fragment, f"user-content-{fragment}"}
        if (
            result.ok
            and fragment
            and accepted_ids.isdisjoint(html_ids.get(request_url, set()))
        ):
            result = _HttpResult(
                False,
                result.status,
                f"HTML response has no element with id {fragment!r}",
                result.body,
            )
        findings.append(
            Finding(
                endpoint.project_id,
                endpoint.target,
                result.ok,
                url=endpoint.url,
                status=result.status,
                message=result.message,
            )
        )
    if pmtiles_endpoints:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {
                executor.submit(
                    _check_pmtiles_endpoint,
                    endpoint,
                    timeout=timeout,
                    retries=retries,
                ): endpoint
                for endpoint in pmtiles_endpoints
            }
            for future in as_completed(futures):
                findings.append(future.result())
    return findings


def validate_public_example_library(
    *,
    library_url: str = DEFAULT_LIBRARY_URL,
    catalog_url: str = DEFAULT_CATALOG_URL,
    timeout: float = 15.0,
    retries: int = 2,
    workers: int = 8,
    fallback_catalog: Path | str | None = DEFAULT_FALLBACK_CATALOG,
    supplements_catalog: Path | str | None = DEFAULT_SUPPLEMENTS_CATALOG,
) -> ValidationReport:
    """Validate the landing page and every project-level catalog link."""

    findings: list[Finding] = []
    library_url = _resolved_url(library_url, library_url)
    catalog_url = _resolved_url(library_url, catalog_url)
    if not library_url:
        return ValidationReport(
            (_local_finding("library", "landing", "invalid library HTTP(S) URL"),),
            0,
        )
    if not catalog_url:
        return ValidationReport(
            (_local_finding("library", "catalog", "invalid catalog HTTP(S) URL"),),
            0,
        )

    landing_result = _request(
        library_url,
        timeout=timeout,
        retries=retries,
        read_body=False,
    )
    findings.append(
        Finding(
            "library",
            "landing",
            landing_result.ok,
            url=library_url,
            status=landing_result.status,
            message=landing_result.message,
        )
    )

    catalog_result = _request(
        catalog_url,
        timeout=timeout,
        retries=retries,
        read_body=True,
    )
    findings.append(
        Finding(
            "library",
            "catalog",
            catalog_result.ok,
            url=catalog_url,
            status=catalog_result.status,
            message=catalog_result.message,
        )
    )
    catalog: Mapping[str, Any] | None = None
    if catalog_result.ok:
        try:
            parsed_catalog = json.loads(catalog_result.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(
                _local_finding("library", "catalog-json", f"invalid JSON: {exc}")
            )
        else:
            if isinstance(parsed_catalog, Mapping) and isinstance(
                parsed_catalog.get("features"), list
            ):
                catalog = parsed_catalog
            else:
                findings.append(
                    _local_finding(
                        "library",
                        "catalog-json",
                        "catalog must be an object with a features array",
                    )
                )

    if catalog is None:
        catalog, fallback_finding = _load_local_collection(
            fallback_catalog,
            variable="RAS_EXAMPLE_PROJECTS",
            target="fallback-catalog",
        )
        if fallback_finding:
            findings.append(fallback_finding)
        if catalog is None:
            return ValidationReport(tuple(findings), 0)

    supplements, supplements_finding = _load_local_collection(
        supplements_catalog,
        variable="RAS_EXAMPLE_PROJECT_SUPPLEMENTS",
        target="supplements-catalog",
    )
    if supplements_finding:
        findings.append(supplements_finding)
    catalog = _merge_project_collections(catalog, supplements)

    features = catalog["features"]
    endpoints: list[_Endpoint] = []
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, Mapping):
            findings.append(
                _local_finding(
                    f"feature-{ordinal}", "catalog", "feature is not an object"
                )
            )
            continue
        project_endpoints, project_findings = _project_endpoints(
            feature,
            library_url=library_url,
            ordinal=ordinal,
        )
        endpoints.extend(project_endpoints)
        findings.extend(project_findings)

    findings.extend(
        _check_endpoints(
            endpoints,
            timeout=timeout,
            retries=retries,
            workers=workers,
        )
    )
    findings.sort(key=lambda item: (item.project_id, item.target, item.url))
    return ValidationReport(tuple(findings), len(features))


def format_report(report: ValidationReport) -> str:
    """Render concise, stable diagnostics for terminal and scheduled runs."""

    lines: list[str] = []
    current_project = ""
    for finding in report.findings:
        if finding.project_id != current_project:
            if lines:
                lines.append("")
            current_project = finding.project_id
            lines.append(f"{current_project}:")
        state = "OK" if finding.ok else "FAIL"
        status = f" [{finding.status}]" if finding.status is not None else ""
        message = f" - {finding.message}" if finding.message else ""
        lines.append(f"  {state} {finding.target}{status}{message}")
        if finding.url:
            lines.append(f"    {finding.url}")

    lines.extend(
        [
            "",
            (
                f"Summary: {report.project_count} projects; "
                f"{len(report.findings)} checks; {report.failure_count} failures"
            ),
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-url", default=DEFAULT_LIBRARY_URL)
    parser.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--fallback-catalog",
        type=Path,
        default=DEFAULT_FALLBACK_CATALOG,
        help="strict window.RAS_EXAMPLE_PROJECTS JSON assignment used if the public catalog fails",
    )
    parser.add_argument(
        "--supplements-catalog",
        type=Path,
        default=DEFAULT_SUPPLEMENTS_CATALOG,
        help="strict window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS JSON assignment merged by project ID",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")
    if args.retries < 0:
        raise SystemExit("--retries must be zero or greater")
    if args.workers <= 0:
        raise SystemExit("--workers must be greater than zero")

    report = validate_public_example_library(
        library_url=args.library_url,
        catalog_url=args.catalog_url,
        timeout=args.timeout,
        retries=args.retries,
        workers=args.workers,
        fallback_catalog=args.fallback_catalog,
        supplements_catalog=args.supplements_catalog,
    )
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
