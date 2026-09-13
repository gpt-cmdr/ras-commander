from __future__ import annotations

import gzip
import json
import struct
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import quote

from scripts.example_library.validate_public_example_library import (
    format_report,
    main,
    validate_public_example_library,
)


class _FixtureHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
    requests: list[tuple[str, str | None]] = []

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        type(self).requests.append((path, self.headers.get("Range")))
        status, headers, body = type(self).routes.get(
            path,
            (404, {"Cache-Control": "no-store"}, b"not found"),
        )
        request_range = self.headers.get("Range")
        if (
            status == 200
            and request_range
            and headers.get("Content-Type") == "application/vnd.pmtiles"
        ):
            unit, requested = request_range.split("=", 1)
            start_text, end_text = requested.split("-", 1)
            assert unit == "bytes"
            start = int(start_text)
            end = min(int(end_text), len(body) - 1)
            status = 206
            headers = {
                **headers,
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{len(body)}",
            }
            body = body[start : end + 1]
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _server(
    routes: dict[str, tuple[int, dict[str, str], bytes]],
) -> Iterator[tuple[str, type[_FixtureHandler]]]:
    handler = type("FixtureHandler", (_FixtureHandler,), {})
    handler.routes = routes
    handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _response(
    body: bytes = b"ok",
    *,
    content_type: str = "text/plain",
) -> tuple[int, dict[str, str], bytes]:
    return 200, {"Content-Type": content_type}, body


def _pmtiles_archive(
    *,
    layers: dict[str, tuple[int, int]] | None = None,
    vector_layers: list[dict[str, object]] | None = None,
    header_zooms: tuple[int, int] = (7, 14),
) -> bytes:
    layer_zooms = layers or {
        "ras_model_extent": (7, 11),
        "ras_river_centerlines": (8, 14),
        "ras_cross_sections": (10, 14),
        "ras_bank_lines": (10, 14),
    }
    layer_metadata = vector_layers or [
        {"id": layer_id, "minzoom": zooms[0], "maxzoom": zooms[1]}
        for layer_id, zooms in layer_zooms.items()
    ]
    metadata = gzip.compress(
        json.dumps(
            {
                "format": "pbf",
                "vector_layers": layer_metadata,
            }
        ).encode()
    )
    # One root entry covering one one-byte MVT payload. Directory values are:
    # count, tile-id delta, run length, byte length, and offset-plus-one.
    root = gzip.compress(bytes([1, 0, 1, 1, 1]))
    tile_data = b"\x00"
    header = bytearray(127)
    header[:7] = b"PMTiles"
    header[7] = 3
    root_offset = len(header)
    metadata_offset = root_offset + len(root)
    tile_data_offset = metadata_offset + len(metadata)
    struct.pack_into("<QQ", header, 8, root_offset, len(root))
    struct.pack_into("<QQ", header, 24, metadata_offset, len(metadata))
    struct.pack_into("<QQ", header, 56, tile_data_offset, len(tile_data))
    struct.pack_into("<QQQ", header, 72, 1, 1, 1)
    header[96] = 1
    header[97] = 2
    header[98] = 2
    header[99] = 1
    header[100], header[101] = header_zooms
    return bytes(header) + root + metadata + tile_data


def _catalog(base_url: str, *, nested_manifest: str | None = None) -> bytes:
    manifest = f"{base_url}/data/published/viewer/manifest.json?v=1"
    nested = nested_manifest or manifest
    viewer = f"{base_url}/viewer/?manifest={quote(nested, safe='')}"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "published",
                "properties": {
                    "status": "Published",
                    "webmap": viewer,
                    "manifest": manifest,
                    "projectManifest": f"{base_url}/data/published/project.json",
                    "details": f"{base_url}/published-details/",
                },
            },
            {
                "type": "Feature",
                "id": "candidate",
                "properties": {
                    "status": "Source qualification candidate",
                    "webmap": "",
                    "manifest": "",
                    "projectManifest": "",
                    "details": f"{base_url}/rod.md#candidate",
                    "recordOfDeficiencies": f"{base_url}/rod.md",
                },
            },
        ],
    }
    return json.dumps(payload).encode()


def _healthy_routes(base_url: str) -> dict[str, tuple[int, dict[str, str], bytes]]:
    return {
        "/library/": _response(b"<html>library</html>", content_type="text/html"),
        "/catalog.json": _response(
            _catalog(base_url), content_type="application/geo+json"
        ),
        "/viewer/": _response(b"<html>viewer</html>", content_type="text/html"),
        "/data/published/viewer/manifest.json": _response(
            b"{}", content_type="application/json"
        ),
        "/data/published/project.json": _response(
            b"{}", content_type="application/json"
        ),
        "/published-details/": _response(b"details"),
        "/rod.md": _response(b'<h3 id="user-content-candidate">Candidate</h3>'),
    }


def _write_assignment(path, variable: str, collection: object) -> None:
    path.write_text(
        f"window.{variable} = {json.dumps(collection, separators=(',', ':'))};\n",
        encoding="utf-8",
    )


def test_validates_complete_link_graph_and_uses_range_gets() -> None:
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            workers=4,
            supplements_catalog=None,
        )

    assert report.ok
    assert report.project_count == 2
    assert report.failure_count == 0
    assert {finding.target for finding in report.findings} >= {
        "landing",
        "catalog",
        "webmap",
        "webmap-manifest",
        "manifest",
        "projectManifest",
        "details",
        "recordOfDeficiencies",
    }
    requests = dict(handler.requests)
    assert requests["/catalog.json"] is None
    assert requests["/data/published/viewer/manifest.json"] is None
    assert requests["/data/published/project.json"] is None
    assert requests["/rod.md"] is None
    assert requests["/library/"] == "bytes=0-65535"
    assert requests["/viewer/"] == "bytes=0-65535"
    assert requests["/published-details/"] == "bytes=0-65535"


def test_viewer_200_does_not_hide_nested_manifest_404() -> None:
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            _catalog(base_url), content_type="application/geo+json"
        )
        handler.routes["/data/published/viewer/manifest.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing",
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    assert not report.ok
    assert any(
        finding.target == "webmap" and finding.ok and finding.status == 200
        for finding in report.findings
    )
    nested = [
        finding
        for finding in report.findings
        if finding.project_id == "published" and finding.target == "webmap-manifest"
    ]
    assert len(nested) == 1
    assert nested[0].status == 404
    assert not nested[0].ok
    assert "Cache-Control lacks" not in nested[0].message


def test_manifest_html_error_shell_with_200_is_not_healthy() -> None:
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        handler.routes["/data/published/viewer/manifest.json"] = _response(
            b"<html>not a manifest</html>", content_type="text/html"
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    failures = [
        finding
        for finding in report.findings
        if finding.project_id == "published"
        and finding.target in {"manifest", "webmap-manifest"}
    ]
    assert len(failures) == 2
    assert all(not finding.ok and finding.status == 200 for finding in failures)
    assert all("not valid JSON" in finding.message for finding in failures)


def test_detects_manifest_mismatch_and_bad_error_cache_policy() -> None:
    with _server({}) as (base_url, handler):
        mismatched = f"{base_url}/data/other/manifest.json"
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            _catalog(base_url, nested_manifest=mismatched),
            content_type="application/geo+json",
        )
        handler.routes["/data/other/manifest.json"] = (
            404,
            {"Cache-Control": "public, max-age=60"},
            b"missing",
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    assert not report.ok
    assert any(
        finding.target == "webmap-manifest-match" and not finding.ok
        for finding in report.findings
    )
    failed_nested = next(
        finding
        for finding in report.findings
        if finding.target == "webmap-manifest" and finding.status == 404
    )
    assert "Cache-Control lacks no-store" in failed_nested.message


def test_candidate_requires_both_details_and_record_of_deficiencies() -> None:
    with _server({}) as (base_url, handler):
        payload = json.loads(_catalog(base_url))
        candidate = payload["features"][1]["properties"]
        candidate["details"] = ""
        candidate["recordOfDeficiencies"] = ""
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            json.dumps(payload).encode(), content_type="application/geo+json"
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    failures = {
        finding.target
        for finding in report.findings
        if finding.project_id == "candidate" and not finding.ok
    }
    assert failures == {"details", "recordOfDeficiencies"}


def test_candidate_detail_fragment_must_exist() -> None:
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            _catalog(base_url), content_type="application/geo+json"
        )
        handler.routes["/rod.md"] = _response(b'<h3 id="another-model">Other</h3>')
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    details = next(
        finding
        for finding in report.findings
        if finding.project_id == "candidate" and finding.target == "details"
    )
    rod = next(
        finding
        for finding in report.findings
        if finding.project_id == "candidate"
        and finding.target == "recordOfDeficiencies"
    )
    assert not details.ok
    assert details.status == 200
    assert "no element with id 'candidate'" in details.message
    assert rod.ok


def test_candidate_can_publish_validated_direct_corpus_geometry() -> None:
    with _server({}) as (base_url, handler):
        payload = json.loads(_catalog(base_url))
        candidate = payload["features"][1]["properties"]
        candidate["landingGeometryPmtiles"] = f"{base_url}/corpus.pmtiles"
        candidate["landingGeometryProfile"] = "ras-1d-corpus-v1"
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            json.dumps(payload).encode(), content_type="application/geo+json"
        )
        handler.routes["/corpus.pmtiles"] = _response(
            _pmtiles_archive(), content_type="application/vnd.pmtiles"
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    assert report.ok
    geometry = next(
        finding
        for finding in report.findings
        if finding.project_id == "candidate"
        and finding.target == "landingGeometryPmtiles"
    )
    assert geometry.ok
    assert geometry.status == 206
    assert "4 vector layers" in geometry.message
    ranges = [
        request_range
        for path, request_range in handler.requests
        if path == "/corpus.pmtiles"
    ]
    assert len(ranges) == 3
    assert ranges[0] == "bytes=0-126"


def test_direct_corpus_geometry_requires_ranges_and_expected_layers() -> None:
    with _server({}) as (base_url, handler):
        payload = json.loads(_catalog(base_url))
        candidate = payload["features"][1]["properties"]
        candidate["landingGeometryPmtiles"] = f"{base_url}/corpus.pmtiles"
        candidate["landingGeometryProfile"] = "ras-1d-corpus-v1"
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            json.dumps(payload).encode(), content_type="application/geo+json"
        )
        handler.routes["/corpus.pmtiles"] = _response(
            _pmtiles_archive(
                layers={
                    "ras_model_extent": (7, 11),
                    "ras_river_centerlines": (8, 14),
                    "ras_cross_sections": (10, 14),
                }
            ),
            content_type="application/vnd.pmtiles",
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    geometry = next(
        finding
        for finding in report.findings
        if finding.project_id == "candidate"
        and finding.target == "landingGeometryPmtiles"
    )
    assert not geometry.ok
    assert "ras_bank_lines" in geometry.message

    with _server({}) as (base_url, handler):
        payload = json.loads(_catalog(base_url))
        candidate = payload["features"][1]["properties"]
        candidate["landingGeometryPmtiles"] = f"{base_url}/corpus.pmtiles"
        candidate["landingGeometryProfile"] = "ras-1d-corpus-v1"
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            json.dumps(payload).encode(), content_type="application/geo+json"
        )
        handler.routes["/corpus.pmtiles"] = _response(_pmtiles_archive())
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    geometry = next(
        finding
        for finding in report.findings
        if finding.project_id == "candidate"
        and finding.target == "landingGeometryPmtiles"
    )
    assert not geometry.ok
    assert geometry.status == 200
    assert "did not honor" in geometry.message


def test_direct_corpus_geometry_rejects_truncated_duplicate_and_bad_zoom_archives() -> (
    None
):
    expected = [
        {"id": "ras_model_extent", "minzoom": 7, "maxzoom": 11},
        {"id": "ras_river_centerlines", "minzoom": 8, "maxzoom": 14},
        {"id": "ras_cross_sections", "minzoom": 10, "maxzoom": 14},
        {"id": "ras_bank_lines", "minzoom": 10, "maxzoom": 14},
    ]
    archives = {
        "truncated": _pmtiles_archive()[:-1],
        "duplicate": _pmtiles_archive(vector_layers=[*expected[:-1], expected[0]]),
        "non-string": _pmtiles_archive(
            vector_layers=[*expected[:-1], {"id": 7, "minzoom": 10, "maxzoom": 14}]
        ),
        "bad-header-zoom": _pmtiles_archive(header_zooms=(8, 14)),
    }

    for label, archive in archives.items():
        with _server({}) as (base_url, handler):
            payload = json.loads(_catalog(base_url))
            candidate = payload["features"][1]["properties"]
            candidate["landingGeometryPmtiles"] = f"{base_url}/corpus.pmtiles"
            candidate["landingGeometryProfile"] = "ras-1d-corpus-v1"
            handler.routes = _healthy_routes(base_url)
            handler.routes["/catalog.json"] = _response(
                json.dumps(payload).encode(), content_type="application/geo+json"
            )
            handler.routes["/corpus.pmtiles"] = _response(
                archive, content_type="application/vnd.pmtiles"
            )
            report = validate_public_example_library(
                library_url=f"{base_url}/library/",
                catalog_url=f"{base_url}/catalog.json",
                timeout=2,
                retries=0,
                supplements_catalog=None,
            )

        geometry = next(
            finding
            for finding in report.findings
            if finding.project_id == "candidate"
            and finding.target == "landingGeometryPmtiles"
        )
        assert not geometry.ok, label


def test_direct_corpus_geometry_rejects_non_http_url_and_unknown_profile() -> None:
    with _server({}) as (base_url, handler):
        payload = json.loads(_catalog(base_url))
        candidate = payload["features"][1]["properties"]
        candidate["landingGeometryPmtiles"] = "file:///tmp/corpus.pmtiles"
        candidate["landingGeometryProfile"] = "unknown-profile"
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = _response(
            json.dumps(payload).encode(), content_type="application/geo+json"
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    failures = {
        finding.target
        for finding in report.findings
        if finding.project_id == "candidate" and not finding.ok
    }
    assert failures == {"landingGeometryPmtiles", "landingGeometryProfile"}


def test_cli_returns_nonzero_and_prints_project_diagnostics(capsys, tmp_path) -> None:
    supplements_path = tmp_path / "supplements.js"
    _write_assignment(
        supplements_path,
        "RAS_EXAMPLE_PROJECT_SUPPLEMENTS",
        {"type": "FeatureCollection", "features": []},
    )
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        handler.routes["/data/published/project.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing",
        )
        exit_code = main(
            [
                "--library-url",
                f"{base_url}/library/",
                "--catalog-url",
                f"{base_url}/catalog.json",
                "--timeout",
                "2",
                "--retries",
                "0",
                "--workers",
                "2",
                "--supplements-catalog",
                str(supplements_path),
            ]
        )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "published:" in output
    assert "FAIL projectManifest [404]" in output
    assert "2 projects" in output
    assert "failures" in output


def test_format_report_does_not_claim_success_for_404() -> None:
    with _server({}) as (base_url, handler):
        handler.routes = _healthy_routes(base_url)
        handler.routes["/data/published/viewer/manifest.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing",
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            timeout=2,
            retries=0,
            supplements_catalog=None,
        )

    text = format_report(report)
    assert "FAIL manifest [404]" in text
    assert report.failure_count == 2


def test_catalog_404_still_audits_fallback_and_supplement_links(tmp_path) -> None:
    fallback_path = tmp_path / "fallback.js"
    supplements_path = tmp_path / "supplements.js"
    with _server({}) as (base_url, handler):
        fallback = json.loads(_catalog(base_url))
        # Keep one published fallback entry and make its nested manifest fail.
        fallback["features"] = fallback["features"][:1]
        supplement = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "candidate-from-supplement",
                    "properties": {
                        "status": "Source qualification candidate",
                        "details": f"{base_url}/candidate-details.md#model",
                        "recordOfDeficiencies": f"{base_url}/candidate-rod.md",
                    },
                }
            ],
        }
        _write_assignment(fallback_path, "RAS_EXAMPLE_PROJECTS", fallback)
        _write_assignment(
            supplements_path,
            "RAS_EXAMPLE_PROJECT_SUPPLEMENTS",
            supplement,
        )
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing catalog",
        )
        handler.routes["/data/published/viewer/manifest.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing manifest",
        )
        handler.routes["/candidate-details.md"] = _response(
            b'<h3 id="model">Candidate</h3>'
        )
        handler.routes["/candidate-rod.md"] = _response(b"rod")

        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            fallback_catalog=fallback_path,
            supplements_catalog=supplements_path,
            timeout=2,
            retries=0,
        )

    assert not report.ok
    assert report.project_count == 2
    assert any(
        finding.project_id == "library"
        and finding.target == "catalog"
        and finding.status == 404
        for finding in report.findings
    )
    assert any(
        finding.project_id == "published"
        and finding.target == "webmap-manifest"
        and finding.status == 404
        for finding in report.findings
    )
    assert all(
        finding.ok
        for finding in report.findings
        if finding.project_id == "candidate-from-supplement"
    )
    requested_paths = {path for path, _range in handler.requests}
    assert "/candidate-details.md" in requested_paths
    assert "/candidate-rod.md" in requested_paths


def test_supplement_ids_are_deduplicated_with_primary_precedence(tmp_path) -> None:
    fallback_path = tmp_path / "fallback.js"
    supplements_path = tmp_path / "supplements.js"
    with _server({}) as (base_url, handler):
        fallback = json.loads(_catalog(base_url))
        supplement = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "candidate",
                    "properties": {
                        "status": "Source qualification candidate",
                        "details": f"{base_url}/should-not-be-requested",
                        "recordOfDeficiencies": f"{base_url}/should-not-be-requested",
                    },
                }
            ],
        }
        _write_assignment(fallback_path, "RAS_EXAMPLE_PROJECTS", fallback)
        _write_assignment(
            supplements_path,
            "RAS_EXAMPLE_PROJECT_SUPPLEMENTS",
            supplement,
        )
        handler.routes = _healthy_routes(base_url)
        handler.routes["/catalog.json"] = (
            404,
            {"Cache-Control": "no-store"},
            b"missing catalog",
        )
        report = validate_public_example_library(
            library_url=f"{base_url}/library/",
            catalog_url=f"{base_url}/catalog.json",
            fallback_catalog=fallback_path,
            supplements_catalog=supplements_path,
            timeout=2,
            retries=0,
        )

    assert report.project_count == 2
    assert not any(
        path == "/should-not-be-requested" for path, _range in handler.requests
    )
