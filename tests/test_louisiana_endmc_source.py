"""Tests for the Louisiana Watershed Initiative EnDMC source.

Unit tests use recorded or hand-written listings and an in-memory HTTP fake.
The ``network`` tests read the public ``lwi-model-data`` bucket anonymously
and skip when it is unreachable. No credentials are used anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import zlib
from urllib.parse import unquote

import pandas as pd
import pytest
import requests

from ras_commander.sources import LouisianaEndmc as ExportedLouisianaEndmc
from ras_commander.sources.base import SourceStatus
from ras_commander.sources.state import louisiana_endmc as endmc
from ras_commander.sources.state.louisiana_endmc import LouisianaEndmc

FIXTURES = Path(__file__).parent / "fixtures" / "endmc"
TINY_DATASET = "65e8c7fdb6e82281370fd742"
FAKE_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
MiB = 1024 * 1024


# ---------------------------------------------------------------------------
# HTTP fake
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i : i + size]

    def json(self):
        return json.loads(self.content)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeBucket:
    """Serve ListObjectsV2 and ranged GETs for an in-memory prefix."""

    def __init__(self, kind, resource_id, files, checksums=None):
        self.prefix = f"endmc-managed/{kind}/{resource_id}/"
        self.files = {self.prefix + rel: data for rel, data in files.items()}
        self.etags = {key: f"etag{i:04d}" for i, key in enumerate(self.files)}
        # {relative path: (algorithm, base64 value)} served on HEAD with checksum mode.
        self.checksums = {self.prefix + rel: v for rel, v in (checksums or {}).items()}
        self.requests = []
        self.fail_ranges = set()

    def listing(self, params):
        prefix = params.get("prefix", "")
        items = []
        for key, data in self.files.items():
            if key.startswith(prefix):
                checksum = ""
                if key in self.checksums:
                    checksum = (
                        f"<ChecksumAlgorithm>{self.checksums[key][0]}</ChecksumAlgorithm>"
                        "<ChecksumType>FULL_OBJECT</ChecksumType>"
                    )
                items.append(
                    f"<Contents><Key>{key}</Key><LastModified>2026-01-01T00:00:00.000Z"
                    f"</LastModified><ETag>&quot;{self.etags[key]}&quot;</ETag>{checksum}"
                    f"<Size>{len(data)}</Size><StorageClass>STANDARD</StorageClass></Contents>"
                )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult '
            'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false'
            "</IsTruncated>" + "".join(items) + "</ListBucketResult>"
        )
        return _Response(200, body.encode())

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        headers = headers or {}
        if url == endmc.S3_ENDPOINT + "/":
            return self.listing(params or {})
        key = unquote(url[len(endmc.S3_ENDPOINT) + 1 :])
        data = self.files[key]
        if headers.get("If-Match") and headers["If-Match"].strip('"') != self.etags[key]:
            return _Response(412)
        rng = headers.get("Range")
        self.requests.append((key, rng))
        if rng:
            start, end = (int(v) for v in rng.split("=")[1].split("-"))
            if (key, start) in self.fail_ranges:
                return _Response(503)
            return _Response(206, data[start : end + 1])
        return _Response(200, data)

    def head(self, url, headers=None, timeout=None):
        key = unquote(url[len(endmc.S3_ENDPOINT) + 1 :])
        if key in self.checksums and (headers or {}).get("x-amz-checksum-mode") == "ENABLED":
            algorithm, value = self.checksums[key]
            return _Response(
                200,
                b"",
                {f"x-amz-checksum-{algorithm.lower()}": value, "x-amz-checksum-type": "FULL_OBJECT"},
            )
        return _Response(200, b"", {})


@pytest.fixture
def fake_bucket(monkeypatch):
    def install(files, kind="model_application", resource_id=FAKE_ID, checksums=None):
        bucket = FakeBucket(kind, resource_id, files, checksums)
        monkeypatch.setattr(endmc.requests, "get", bucket.get)
        monkeypatch.setattr(endmc.requests, "head", bucket.head)
        return bucket

    return install


# ---------------------------------------------------------------------------
# Listing and catalog parsing
# ---------------------------------------------------------------------------


def test_exports_and_catalog_registration():
    assert ExportedLouisianaEndmc is LouisianaEndmc
    source = LouisianaEndmc()
    assert source.source_name == "Louisiana LWI EnDMC"
    assert source.source_type == "state"


def test_parse_recorded_listing_fixture():
    root = ET.fromstring((FIXTURES / f"list_dataset_{TINY_DATASET}.xml").read_bytes())
    objects, token = endmc.parse_list_objects(root)
    assert token is None
    assert len(objects) == 10
    shp = next(o for o in objects if o["key"].endswith(".shp"))
    assert shp["size"] == 71776
    assert shp["checksum_algorithm"] == "CRC64NVME"
    assert shp["checksum_type"] == "FULL_OBJECT"
    assert not shp["etag"].startswith('"')

    df = endmc.objects_dataframe(objects, f"endmc-managed/dataset/{TINY_DATASET}/")
    components = dict(zip(df["relative_path"], df["component"]))
    assert components["Combined_BridgeCrossSection_Data.shp"] == "gis"
    # A .prj beside a shapefile is a GIS projection, not a RAS project file.
    assert components["Combined_BridgeCrossSection_Data.prj"] == "gis"
    assert components["file_listing.json"] == "metadata"
    assert components[".endmc_public"] == "metadata"
    assert components["image.png"] == "docs"
    assert df["url"].str.startswith(endmc.S3_ENDPOINT).all()


def test_listing_follows_continuation_tokens(monkeypatch):
    pages = {
        None: (FIXTURES / "list_two_pages_page1.xml").read_bytes(),
        "token-page-2": (FIXTURES / "list_two_pages_page2.xml").read_bytes(),
    }
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(params.get("continuation-token"))
        return _Response(200, pages[params.get("continuation-token")])

    monkeypatch.setattr(endmc.requests, "get", fake_get)
    df = LouisianaEndmc.list_objects(FAKE_ID, kind="model_application")
    assert seen == [None, "token-page-2"]
    assert list(df["component"]) == ["ras_project", "geometry_hdf", "output_depth"]
    assert df.attrs["s3_prefix"] == f"endmc-managed/model_application/{FAKE_ID}/"
    assert "Output%20Rasters/Depth" in df.loc[2, "url"]

    depth = LouisianaEndmc.list_objects(FAKE_ID, kind="model_application", components=["output_depth"])
    assert len(depth) == 1
    globbed = LouisianaEndmc.list_objects(FAKE_ID, kind="model_application", patterns=["model/*.PRJ"])
    assert list(globbed["relative_path"]) == ["Model/Example.prj"]
    with pytest.raises(ValueError, match="Unknown component"):
        LouisianaEndmc.list_objects(FAKE_ID, kind="model_application", components=["depth"])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("_Abbeville/VE_Abbeville.prj", "ras_project"),
        ("_Abbeville/Projection/Projection.prj", "gis"),
        ("_Abbeville/VE_Abbeville.p01", "ras_project"),
        ("_Abbeville/VE_Abbeville.rasmap", "ras_project"),
        ("_Abbeville/VE_Abbeville.u01.hdf", "ras_project"),
        ("_Abbeville/VE_Abbeville.g01.hdf", "geometry_hdf"),
        ("_Abbeville/Backup/VE_Abbeville.g01.hdf", "ras_run_artifact"),
        ("_Abbeville/VE_Abbeville.p01.hdf", "plan_hdf"),
        ("_Abbeville/VE_Abbeville.b01", "ras_run_artifact"),
        ("_Abbeville/VE_Abbeville.bco01", "ras_run_artifact"),
        ("_Abbeville/VE_Abbeville.c01", "ras_run_artifact"),
        ("_Abbeville/VE_Abbeville.p01.computeMsgs.txt", "ras_run_artifact"),
        ("DU/Terrain/DugdemonaRi_Bathy_2021.hdf", "terrain"),
        ("DU/Terrain/DugdemonaRi_Bathy_2021.Bathy_SP1701_zFt.tif", "terrain"),
        ("DU/Land Cover/DugdemonaRi_Manning_2D.hdf", "land_cover"),
        ("DU/Land Cover/DugdemonaRi_Manning_2D.tif", "land_cover"),
        ("Output Rasters/Depth/02_DU_100YR_X_Depth.tif", "output_depth"),
        ("Output Rasters/WSE/02_DU_100YR_X_WSE.tif", "output_wse"),
        ("Output Rasters/Velocity/02_DU_100YR_X_Velocity.tif", "output_velocity"),
        ("WaterSurfaceElevation/Tickfaw_100yr.tif", "output_wse"),
        ("Plan/Depth (Max).Tickfaw_Bathy.tif.aux.xml", "output_depth"),
        ("Plan/WSE (Max).Tickfaw_Bathy.tif", "output_wse"),
        ("FloodOutputRasters/Arrival_Time.tif", "output_raster_other"),
        ("HECFIA/maps/HMS_Terrain_Resample100x100_DU.tif", "terrain"),
        ("Map Layer/NLCD_Manning_Roughness.hdf", "land_cover"),
        ("Model/ST_TunicaSwamp/TSLandCover.hdf", "land_cover"),
        ("Map Layer/gSSURGO_InfiltrationDC.hdf", "infiltration"),
        ("Soil_Data/WCLC_Infiltration.hdf", "infiltration"),
        ("Map Layer/NLCD_Manning_Roughness.backup.hdf", "ras_run_artifact"),
        ("Model/BF1.p02.snapshot.hdf", "ras_run_artifact"),
        ("WC.p01.InitialCondition.rst", "ras_run_artifact"),
        ("model.hms", "hms"),
        ("model.basin", "hms"),
        ("results/run.results", "hms"),
        ("Hydrologic Input/flows.dss", "dss"),
        ("GIS Features/streams.shp", "gis"),
        ("GIS Features/streams.shp.xml", "gis"),
        ("Reports/final_report.pdf", "docs"),
        ("Boundary_Conditions/Readme.txt", "docs"),
        ("file_listing.json", "metadata"),
        ("notes.weird", "other"),
    ],
)
def test_classify_object(path, expected):
    assert endmc.classify_object(path) == expected


def test_parse_search_payload_and_region_software(monkeypatch):
    payload = json.loads((FIXTURES / "search_payload.json").read_text())
    rows = endmc.parse_search_payload(payload)
    assert [r["resource_id"] for r in rows] == [
        "aaaaaaaaaaaaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbbbbbbbbbbbb",
        "cccccccccccccccccccccccc",
        "dddddddddddddddddddddddd",
    ]
    assert rows[0]["title"] == "LWI Region 5 Example Breakout HEC-RAS Model"
    assert rows[0]["keywords"][-1] == "Region 5"

    calls = []

    def fake_search(params, timeout):
        calls.append(dict(params))
        if params.get("software") == "6349ac1e22ebd4a9959d593c":
            return {"results": {"model_application": [{"_id": "aaaaaaaaaaaaaaaaaaaaaaaa"}]}}
        if params.get("software") == "63cabd42d9e3b6aea518a788":
            return {"results": {"model_application": [{"_id": "bbbbbbbbbbbbbbbbbbbbbbbb"}]}}
        if params.get("software"):
            return {"results": {}}
        return payload

    monkeypatch.setattr(endmc, "_search_json", fake_search)
    monkeypatch.setattr(endmc, "_live_cache", {})
    df = LouisianaEndmc.list_resources(source="live", kinds=CATALOG_ALL)
    assert set(df["catalog_source"]) == {"live"}
    by_id = df.set_index("resource_id")
    assert by_id.loc["aaaaaaaaaaaaaaaaaaaaaaaa", "software"] == "HEC-RAS"
    assert by_id.loc["aaaaaaaaaaaaaaaaaaaaaaaa", "region"] == "Region 5"
    assert by_id.loc["bbbbbbbbbbbbbbbbbbbbbbbb", "region"] == "Region 6"
    assert by_id.loc["bbbbbbbbbbbbbbbbbbbbbbbb", "software"] == "HEC-HMS"
    assert pd.isna(by_id.loc["dddddddddddddddddddddddd", "s3_prefix"])
    assert by_id.loc["cccccccccccccccccccccccc", "s3_prefix"] == (
        "endmc-managed/dataset/cccccccccccccccccccccccc/"
    )
    assert len(calls) == 1 + len(endmc.SOFTWARE_IDS)

    # Cached: no further HTTP calls; filters apply client-side.
    ras = LouisianaEndmc.list_resources(source="live", software="hec-ras", region=5)
    assert list(ras["resource_id"]) == ["aaaaaaaaaaaaaaaaaaaaaaaa"]
    assert len(calls) == 1 + len(endmc.SOFTWARE_IDS)


CATALOG_ALL = ("model_application", "dataset", "simulation_package")


def test_auto_source_falls_back_to_snapshot(monkeypatch):
    def offline(params, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(endmc, "_search_json", offline)
    monkeypatch.setattr(endmc, "_live_cache", {})
    df = LouisianaEndmc.list_resources()
    assert set(df["catalog_source"]) == {"snapshot"}
    assert set(df["kind"]) == {"model_application", "dataset"}
    assert len(df) >= 400
    assert df["resource_id"].str.fullmatch(r"[0-9a-f]{24}").all()
    with pytest.raises(requests.ConnectionError):
        LouisianaEndmc.list_resources(source="live")


def test_snapshot_contains_public_fields_only():
    snapshot = endmc._load_snapshot()
    text = json.dumps(snapshot)
    assert "@" not in text
    assert snapshot["schema"] == "ras-commander-endmc-catalog-snapshot/1"
    row = snapshot["resources"][0]
    assert set(row) == {"resource_id", "kind", "title", "software", "date", "keywords"}
    abbeville = LouisianaEndmc.list_resources(source="snapshot", search="Abbeville Breakout")
    assert (abbeville["region"] == "Region 5").all()
    assert (abbeville["software"] == "HEC-RAS").any()


def test_list_models_metadata_from_snapshot():
    models = LouisianaEndmc.list_models(location="Region 2", source="snapshot", limit=5)
    assert 0 < len(models) <= 5
    for model in models:
        assert model.source_name == "Louisiana LWI EnDMC"
        assert "hec-ras" in model.tags
        assert model.extra["s3_prefix"].startswith("endmc-managed/model_application/")
        assert model.url.startswith("https://lwi.endmc.org/view/model_application/")


def test_parse_resource_page_omits_contacts():
    parsed = endmc.parse_resource_page((FIXTURES / "view_page.html").read_text())
    assert parsed["title"] == "Example Breakout HEC-RAS Model"
    assert parsed["fields"]["Application date"] == "2026-06-26"
    assert parsed["fields"]["Coordinate system"] == "EPSG:3452"
    assert parsed["fields"]["Keywords"] == "hec-ras, Region 5"
    assert "Authors" not in parsed["fields"]
    assert parsed["access_level"] == "public"
    assert parsed["containing_packages"][0]["url"].endswith(
        "/view/simulation_package/dddddddddddddddddddddddd"
    )
    assert "owner@example.com" not in json.dumps(parsed)


def test_urls_and_vsicurl():
    key = "endmc-managed/dataset/x/Output Rasters/A+B.tif"
    url = LouisianaEndmc.object_url(key)
    assert url == endmc.S3_ENDPOINT + "/endmc-managed/dataset/x/Output%20Rasters/A%2BB.tif"
    assert LouisianaEndmc.vsicurl_path(key) == "/vsicurl/" + url


def test_invalid_ids_and_paths(tmp_path):
    with pytest.raises(ValueError):
        LouisianaEndmc.list_objects("../etc", kind="dataset")
    with pytest.raises(ValueError):
        endmc.safe_destination(tmp_path, "../escape.txt")
    with pytest.raises(ValueError):
        endmc.safe_destination(tmp_path, "a//b.txt")
    with pytest.raises(ValueError):
        endmc.safe_destination(tmp_path, "a/b:c.txt")
    with pytest.raises(ValueError):
        endmc.safe_destination(tmp_path, "a\\b.txt")
    assert endmc.safe_destination(tmp_path, "a/b c.txt") == tmp_path / "a" / "b c.txt"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _payload(size, seed=7):
    return bytes((i * seed + i // 251) % 256 for i in range(size))


def test_download_parallel_ranges_receipt_and_skip(tmp_path, fake_bucket):
    big = _payload(2 * MiB + 12345)
    small = b"Proj Title=Example\n"
    bucket = fake_bucket(
        {
            "Model/Example.prj": small,
            "Model/Example.g01.hdf": big,
            "Output Rasters/Depth/Example_Depth.tif": b"tif",
        }
    )
    dest = tmp_path / "ex"
    df = LouisianaEndmc.download_resource(
        FAKE_ID,
        dest,
        kind="model_application",
        components=["ras_project", "geometry_hdf"],
        chunk_size=MiB,
        max_workers=3,
    )
    assert set(df["status"]) == {"downloaded"}
    assert (dest / "Model" / "Example.g01.hdf").read_bytes() == big
    assert (dest / "Model" / "Example.prj").read_bytes() == small
    assert not (dest / "Output Rasters").exists()
    assert not list(dest.rglob("*.part*"))
    ranged = [r for k, r in bucket.requests if k.endswith(".g01.hdf")]
    assert len(ranged) == 3 and all(r.startswith("bytes=") for r in ranged)

    receipt = json.loads(Path(df.attrs["receipt_path"]).read_text())
    assert receipt["schema"] == "ras-commander-endmc-download/1"
    assert receipt["files"]["Model/Example.g01.hdf"]["verified"] == "size"
    assert receipt["files"]["Model/Example.g01.hdf"]["size"] == len(big)

    bucket.requests.clear()
    again = LouisianaEndmc.download_resource(
        FAKE_ID, dest, kind="model_application", components=["ras_project", "geometry_hdf"], chunk_size=MiB
    )
    assert set(again["status"]) == {"present"}
    assert bucket.requests == []


def test_download_resumes_from_partial_state(tmp_path, fake_bucket):
    big = _payload(3 * MiB, seed=11)
    bucket = fake_bucket({"Terrain/terrain.tif": big})
    dest = tmp_path / "r"
    bucket.fail_ranges.add((bucket.prefix + "Terrain/terrain.tif", 2 * MiB))

    first = LouisianaEndmc.download_resource(
        FAKE_ID, dest, kind="model_application", chunk_size=MiB, max_workers=1
    )
    assert first.loc[0, "status"] == "failed"
    state = json.loads((dest / "Terrain" / "terrain.tif.part.json").read_text())
    assert sorted(state["done"]) == [0, 1]

    bucket.fail_ranges.clear()
    bucket.requests.clear()
    second = LouisianaEndmc.download_resource(
        FAKE_ID, dest, kind="model_application", chunk_size=MiB, max_workers=2
    )
    assert second.loc[0, "status"] == "downloaded"
    assert [r for _, r in bucket.requests] == [f"bytes={2 * MiB}-{3 * MiB - 1}"]
    assert (dest / "Terrain" / "terrain.tif").read_bytes() == big


def test_download_restarts_when_etag_changes(tmp_path, fake_bucket):
    data = _payload(2 * MiB + 1)
    bucket = fake_bucket({"a.bin": data})
    dest = tmp_path / "e"
    part = dest / "a.bin.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"\0" * len(data))
    (dest / "a.bin.part.json").write_text(
        json.dumps({"etag": "stale", "size": len(data), "chunk_size": MiB, "done": [0, 1]})
    )
    df = LouisianaEndmc.download_resource(FAKE_ID, dest, kind="model_application", chunk_size=MiB)
    assert df.loc[0, "status"] == "downloaded"
    assert len(bucket.requests) == 3
    assert (dest / "a.bin").read_bytes() == data


def test_download_guards_path_length_size_and_dry_run(tmp_path, fake_bucket):
    fake_bucket({"Deep/" + "x" * 120 + "/file.tif": b"123", "small.txt": b"abc"})
    with pytest.raises(ValueError, match="max_path_length"):
        LouisianaEndmc.download_resource(
            FAKE_ID, tmp_path / ("y" * 100), kind="model_application", max_path_length=200
        )
    with pytest.raises(ValueError, match="max_bytes"):
        LouisianaEndmc.download_resource(
            FAKE_ID, tmp_path / "z", kind="model_application", max_bytes=4, max_path_length=None
        )
    plan = LouisianaEndmc.download_resource(
        FAKE_ID, tmp_path / "z", kind="model_application", dry_run=True, max_path_length=None
    )
    assert set(plan["status"]) == {"planned"}
    assert plan.attrs["total_bytes"] == 6
    assert not (tmp_path / "z").exists()


def test_download_model_protocol_wrapper(tmp_path, fake_bucket):
    fake_bucket({"Model/Example.prj": b"Proj Title=Example\n"})
    result = LouisianaEndmc.download_model(FAKE_ID, tmp_path / "m", kind="model_application")
    assert result.success
    assert (tmp_path / "m" / "Model" / "Example.prj").exists()
    refused = LouisianaEndmc.download_model(
        FAKE_ID, tmp_path / "n", kind="model_application", max_bytes=1
    )
    assert not refused.success
    assert "max_bytes" in refused.message


def test_crc64nvme_matches_reference_vector(tmp_path):
    pytest.importorskip("awscrt")
    path = tmp_path / "check.txt"
    path.write_bytes(b"123456789")
    # CRC-64/NVME check value for "123456789" is 0xAE8B14860A799888.
    expected = __import__("base64").b64encode(bytes.fromhex("ae8b14860a799888")).decode()
    assert endmc.crc64nvme_file(path) == expected


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_file_checksum_algorithms(tmp_path):
    path = tmp_path / "check.txt"
    path.write_bytes(b"123456789")
    # CRC-32 (ISO-HDLC) check value for "123456789" is 0xCBF43926.
    assert endmc.file_checksum(path, "CRC32") == _b64(bytes.fromhex("cbf43926"))
    assert endmc.file_checksum(path, "sha256") == _b64(hashlib.sha256(b"123456789").digest())
    with pytest.raises(ValueError):
        endmc.file_checksum(path, "MD5")


def _block_awscrt(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "awscrt" or name.startswith("awscrt."):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


def test_checksum_verify_crc32_without_awscrt(monkeypatch, tmp_path, fake_bucket):
    _block_awscrt(monkeypatch)
    good = b"Proj Title=Example\n"
    plain = b"no checksum stored"
    fake_bucket(
        {"Model/Example.prj": good, "Model/notes.txt": plain},
        checksums={"Model/Example.prj": ("CRC32", _b64(zlib.crc32(good).to_bytes(4, "big")))},
    )
    df = LouisianaEndmc.download_resource(
        FAKE_ID, tmp_path / "v", kind="model_application", verify="checksum"
    ).set_index("relative_path")
    assert df.loc["Model/Example.prj", "verified"] == "crc32"
    assert df.loc["Model/notes.txt", "verified"] == "size"
    receipt = json.loads((tmp_path / "v" / f"_endmc_{FAKE_ID}.json").read_text())
    assert receipt["files"]["Model/Example.prj"]["checksum"].startswith("crc32:")


def test_checksum_mismatch_fails_file(tmp_path, fake_bucket):
    fake_bucket(
        {"a.txt": b"actual bytes"},
        checksums={"a.txt": ("CRC32", _b64((0).to_bytes(4, "big")))},
    )
    df = LouisianaEndmc.download_resource(FAKE_ID, tmp_path / "m", kind="model_application", verify="checksum")
    assert df.loc[0, "status"] == "failed"
    assert "CRC32 mismatch" in df.loc[0, "error"]
    assert not (tmp_path / "m" / "a.txt").exists()


def test_crc64nvme_objects_require_awscrt(monkeypatch, tmp_path, fake_bucket):
    _block_awscrt(monkeypatch)
    fake_bucket({"a.bin": b"x"}, checksums={"a.bin": ("CRC64NVME", "AAAAAAAAAAA=")})
    with pytest.raises(ImportError, match="awscrt"):
        LouisianaEndmc.download_resource(FAKE_ID, tmp_path, kind="model_application", verify="checksum")
    with pytest.raises(ValueError, match="verify"):
        LouisianaEndmc.download_resource(FAKE_ID, tmp_path, kind="model_application", verify="md5")


# ---------------------------------------------------------------------------
# Live, anonymous, public bucket
# ---------------------------------------------------------------------------


def _bucket_reachable() -> bool:
    try:
        return LouisianaEndmc.get_source_status() == SourceStatus.AVAILABLE
    except Exception:
        return False


@pytest.mark.network
@pytest.mark.integration
def test_live_list_small_dataset_and_range_read(tmp_path):
    if not _bucket_reachable():
        pytest.skip("lwi-model-data bucket unreachable")
    objects = LouisianaEndmc.list_objects(TINY_DATASET, kind="dataset")
    assert "Combined_BridgeCrossSection_Data.shp" in set(objects["relative_path"])
    shp = objects.set_index("relative_path").loc["Combined_BridgeCrossSection_Data.shp"]
    header = LouisianaEndmc.read_range(shp["key"], 0, 4)
    # ESRI shapefile magic number 9994, big-endian.
    assert header == bytes.fromhex("0000270a")

    df = LouisianaEndmc.download_resource(
        TINY_DATASET, tmp_path / "t", kind="dataset", patterns=["file_listing.json"]
    )
    assert df.loc[0, "status"] == "downloaded"
    listing = json.loads((tmp_path / "t" / "file_listing.json").read_text())
    assert "Combined_BridgeCrossSection_Data.shp" in listing[""]["files"]


@pytest.mark.network
@pytest.mark.integration
def test_live_checksum_verification(tmp_path):
    pytest.importorskip("awscrt")
    if not _bucket_reachable():
        pytest.skip("lwi-model-data bucket unreachable")
    # This dataset's objects carry full-object CRC64NVME checksums.
    df = LouisianaEndmc.download_resource(
        TINY_DATASET, tmp_path / "c", kind="dataset", patterns=["*.cpg"], verify="checksum"
    )
    assert df.loc[0, "verified"] == "crc64nvme"
    # The Abbeville project file carries a full-object CRC32 checksum.
    df = LouisianaEndmc.download_resource(
        "6a3d7158f74d9b1d5415493a",
        tmp_path / "a",
        kind="model_application",
        patterns=["_Abbeville/VE_Abbeville.prj"],
        verify="checksum",
    )
    assert df.loc[0, "verified"] == "crc32"
