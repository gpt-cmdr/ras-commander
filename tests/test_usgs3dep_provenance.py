"""Per-tile download provenance for USGS 3DEP terrain builds.

Consumers need to prove which tiles a terrain was built from without re-hashing
large rasters, so ``download_tiles(return_provenance=True)`` reports the source
URL, project, and the remote ``ETag`` / ``Last-Modified`` / ``Content-Length``
for every tile. All HTTP access is mocked.
"""

from importlib import import_module

import geopandas as gpd
import pytest
from shapely.geometry import box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


BBOX = (-77.1, 40.6, -77.0, 40.7)
TILE_NAME = "USGS_1M_18_x37y351_PA_Example_2020_A20.tif"
TILE_URL = f"https://example.com/{TILE_NAME}"


class _FakeHeadResponse:
    def __init__(self, headers):
        self.headers = headers

    def raise_for_status(self):
        return None


def test_get_remote_file_headers_reports_cache_and_provenance(monkeypatch):
    monkeypatch.setattr(
        usgs_module.requests,
        "head",
        lambda url, timeout: _FakeHeadResponse(
            {
                "Content-Length": "2048",
                "ETag": '"9f86d081884c7d659a2feaa0c55ad015"',
                "Last-Modified": "Tue, 04 Feb 2025 18:03:11 GMT",
            }
        ),
    )

    headers = Usgs3depAws._get_remote_file_headers(TILE_URL)

    assert headers == {
        "content_length": 2048,
        "etag": "9f86d081884c7d659a2feaa0c55ad015",
        "last_modified": "Tue, 04 Feb 2025 18:03:11 GMT",
    }


def test_get_remote_file_headers_tolerates_missing_headers(monkeypatch):
    monkeypatch.setattr(
        usgs_module.requests,
        "head",
        lambda url, timeout: _FakeHeadResponse({}),
    )

    headers = Usgs3depAws._get_remote_file_headers(TILE_URL)

    assert headers == {
        "content_length": None,
        "etag": None,
        "last_modified": None,
    }


def test_get_remote_file_headers_returns_nulls_on_error(monkeypatch):
    def fail(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(usgs_module.requests, "head", fail)

    assert Usgs3depAws._get_remote_file_headers(TILE_URL) == {
        "content_length": None,
        "etag": None,
        "last_modified": None,
    }


def test_get_remote_file_size_still_returns_content_length(monkeypatch):
    """The cache check keeps its contract and shares the single HEAD request."""
    monkeypatch.setattr(
        usgs_module.requests,
        "head",
        lambda url, timeout: _FakeHeadResponse({"Content-Length": "4096"}),
    )

    assert Usgs3depAws._get_remote_file_size(TILE_URL) == 4096


def test_build_tile_provenance_captures_stable_identity(monkeypatch, tmp_path):
    tile_path = tmp_path / TILE_NAME
    tile_path.write_bytes(b"x" * 11)

    monkeypatch.setattr(
        Usgs3depAws,
        "_get_remote_file_headers",
        staticmethod(
            lambda url: {
                "content_length": 11,
                "etag": "abc123",
                "last_modified": "Tue, 04 Feb 2025 18:03:11 GMT",
            }
        ),
    )

    record = Usgs3depAws._build_tile_provenance(
        TILE_URL, tile_path, "PA_Example_2020_A20", 2020
    )

    assert record == {
        "tile_id": "USGS_1M_18_x37y351_PA_Example_2020_A20",
        "file_name": TILE_NAME,
        "file_path": str(tile_path),
        "source_url": TILE_URL,
        "project_name": "PA_Example_2020_A20",
        "project_year": 2020,
        "etag": "abc123",
        "last_modified": "Tue, 04 Feb 2025 18:03:11 GMT",
        "content_length": 11,
        "local_size_bytes": 11,
    }


def test_download_tiles_returns_provenance_per_tile(monkeypatch, tmp_path):
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_Example_2020_A20"]},
        geometry=[box(-77.2, 40.5, -76.9, 40.8)],
        crs="EPSG:4326",
    )

    def fake_download(tile_url, output_folder, overwrite_dest):
        tile_path = output_folder / tile_url.rsplit("/", 1)[-1]
        tile_path.write_bytes(b"tile-bytes")
        return tile_path

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: [TILE_URL]),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_parse_tile_bounds_from_filename",
        staticmethod(lambda filename: (-77.1, 40.6, -77.0, 40.7)),
    )
    monkeypatch.setattr(
        Usgs3depAws, "_download_single_tile", staticmethod(fake_download)
    )
    monkeypatch.setattr(
        usgs_module.requests,
        "head",
        lambda url, timeout: _FakeHeadResponse(
            {
                "Content-Length": "10",
                "ETag": '"etag-value"',
                "Last-Modified": "Tue, 04 Feb 2025 18:03:11 GMT",
            }
        ),
    )

    tiles, provenance = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
        return_provenance=True,
    )

    assert [path.name for path in tiles] == [TILE_NAME]
    assert len(provenance) == 1

    record = provenance[0]
    assert record["tile_id"] == "USGS_1M_18_x37y351_PA_Example_2020_A20"
    assert record["source_url"] == TILE_URL
    assert record["project_name"] == "PA_Example_2020_A20"
    assert record["project_year"] == 2020
    assert record["etag"] == "etag-value"
    assert record["last_modified"] == "Tue, 04 Feb 2025 18:03:11 GMT"
    assert record["content_length"] == 10
    assert record["local_size_bytes"] == 10


def test_download_tiles_without_provenance_returns_paths_only(monkeypatch, tmp_path):
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_Example_2020_A20"]},
        geometry=[box(-77.2, 40.5, -76.9, 40.8)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: [TILE_URL]),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_parse_tile_bounds_from_filename",
        staticmethod(lambda filename: (-77.1, 40.6, -77.0, 40.7)),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_download_single_tile",
        staticmethod(
            lambda tile_url, output_folder, overwrite_dest: output_folder
            / tile_url.rsplit("/", 1)[-1]
        ),
    )

    def fail_head(url, timeout):
        raise AssertionError("provenance HEAD requests must stay opt-in")

    monkeypatch.setattr(usgs_module.requests, "head", fail_head)

    result = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
    )

    assert [path.name for path in result] == [TILE_NAME]


def test_download_tiles_returns_empty_provenance_when_no_projects(monkeypatch, tmp_path):
    empty = gpd.GeoDataFrame({"proj_name": []}, geometry=[], crs="EPSG:4326")
    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: empty.copy()),
    )

    tiles, provenance = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        return_provenance=True,
    )

    assert tiles == []
    assert provenance == []


def test_collect_tile_provenance_preserves_mosaic_order(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_remote_file_headers",
        staticmethod(
            lambda url: {"content_length": None, "etag": None, "last_modified": None}
        ),
    )

    groups = [
        {
            "project_name": "PA_Older_2018_B18",
            "project_year": 2018,
            "tiles": [("https://example.com/older.tif", tmp_path / "older.tif")],
        },
        {
            "project_name": "PA_Example_2020_A20",
            "project_year": 2020,
            "tiles": [("https://example.com/newer.tif", tmp_path / "newer.tif")],
        },
    ]

    records = Usgs3depAws._collect_tile_provenance(groups, max_workers=3)

    assert [record["tile_id"] for record in records] == ["older", "newer"]
    assert [record["project_year"] for record in records] == [2018, 2020]
    assert records[0]["local_size_bytes"] is None


@pytest.mark.parametrize("max_workers", [1, 4])
def test_collect_tile_provenance_handles_empty_input(max_workers):
    assert Usgs3depAws._collect_tile_provenance([], max_workers=max_workers) == []
