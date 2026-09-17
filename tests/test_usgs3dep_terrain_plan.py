"""Plan -> prefetch -> offline-build workflow for USGS 3DEP terrain.

A catalog of models plans its tiles, prefetches them once into a shared store
with a single writer, then builds every terrain in parallel with no network
and a read-only store. These tests pin the shared AOI routine, the plan
contents and JSON round trip, prefetch deduplication and caching, and the
offline build guarantees (no network calls, nothing written into the store,
missing tiles rejected). All network access is mocked or blocked.
"""

import json
import socket
import urllib.request
from fractions import Fraction
from importlib import import_module
from pathlib import Path

import numpy as np
import pytest
import rasterio
import requests
import shapely
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws
TerrainBuildError = usgs_module.TerrainBuildError
RasTerrain = import_module("ras_commander.terrain.RasTerrain").RasTerrain

PROJECT_CRS = "EPSG:2277"
AOI = box(3125000, 10003000, 3125200, 10003200)
ONE_M_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/{folder}/TIFF/{name}.tif"
SEAMLESS_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/{token}/TIFF/current/{corner}/USGS_{token}_{corner}.tif"


def _write_raster(path, array, transform, crs, nodata=-9999.0):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0], count=1,
        dtype="float32", crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(array.astype("float32"), 1)
    return Path(path)


def _headers(size=100):
    return {"content_length": size, "etag": "etag", "last_modified": "Tue, 04 Feb 2025 18:03:11 GMT"}


def _synthetic_plan(tier1_names=("USGS_1M_14_x62y333_TX_A_2020",), seamless=("n31w098",), aoi=AOI):
    """A plan shaped exactly like plan_terrain_tiles() output, for build/prefetch tests."""
    wkt = Usgs3depAws._geometry_wkt(aoi)
    aoi_wgs84 = Usgs3depAws._geometry_to_wgs84(aoi, PROJECT_CRS)
    tier1 = []
    for name in tier1_names:
        record = Usgs3depAws._plan_tile_record(
            ONE_M_URL.format(folder="TX_A_2020", name=name), "3dep_1m_project", 1,
            project="TX_A_2020", project_folder="TX_A_2020", year=2020,
        )
        record.update(_headers())
        tier1.append(record)
    tiers = [{"tier": 1, "product": "3dep_1m_project", "resolution": 1, "tiles": tier1, "coverage": None}]
    for position, (resolution, token, product) in enumerate(
        [(10, "13", "3dep_seamless_1_3_arc_second"), (30, "1", "3dep_seamless_1_arc_second")]
    ):
        tiles = []
        for corner in seamless:
            record = Usgs3depAws._plan_tile_record(
                SEAMLESS_URL.format(token=token, corner=corner), product, resolution, project=product
            )
            record.update(_headers())
            tiles.append(record)
        tiers.append({"tier": position + 2, "product": product, "resolution": resolution, "tiles": tiles, "unavailable_tiles": []})
    return {
        "schema": Usgs3depAws.TILE_PLAN_SCHEMA,
        "version": Usgs3depAws.TILE_PLAN_VERSION,
        "created_at": "2026-09-16T00:00:00+00:00",
        "project_crs": PROJECT_CRS,
        "buffer": {"distance": 0.0, "units": "us survey foot", "distance_project_units": 0.0},
        "aoi": {
            "source": "caller_geometry",
            "buffer_distance": 0.0,
            "buffer_units": "us survey foot",
            "buffer_distance_project_units": 0.0,
            "wkt": wkt,
            "wkt_sha256": "x",
            "bounds": list(aoi.bounds),
            "bounds_wgs84": list(aoi_wgs84.bounds),
        },
        "selection": {"backfill_resolutions": [10, 30]},
        "tiers": tiers,
    }


def _populate_store(store, plan):
    for tier in plan["tiers"]:
        for tile in tier["tiles"]:
            path = store / tile["relative_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 100)


def _snapshot(folder):
    return sorted(
        (str(path.relative_to(folder)), path.stat().st_size, path.stat().st_mtime_ns)
        for path in Path(folder).rglob("*")
    )


@pytest.fixture
def offline_pipeline(monkeypatch):
    """Local-only fakes for gdalwarp and HEC-RAS; every remote entry point fails loudly."""
    state = {"composites": []}

    def fail(*args, **kwargs):
        raise AssertionError("network or remote tile access attempted")

    def fake_native(path, project_crs, point):
        return {
            "native_resolution_source_units": 1.0,
            "native_resolution_source_unit": "metre",
            "native_resolution_source_crs": "EPSG:26914",
            "native_resolution_project_units": float(Fraction(3937, 1200)),
            "_native_resolution_exact": Fraction(3937, 1200),
        }

    def fake_composite(tiers, output_path, project_crs, resolution, aoi_bounds, **kwargs):
        sources = [Path(path) for tier in reversed(list(tiers)) for path in tier["paths"]]
        assert all(path.is_file() for path in sources)
        state["composites"].append(sources)
        minx, miny, maxx, maxy = Usgs3depAws._snap_bounds_outward(aoi_bounds, resolution)
        width = int(round((maxx - minx) / resolution))
        height = int(round((maxy - miny) / resolution))
        _write_raster(output_path, np.full((height, width), 100.0), from_origin(minx, maxy, resolution, resolution), project_crs)
        return Path(output_path), Path("gdalwarp.exe")

    def fake_create_terrain_hdf(input_rasters, output_hdf, projection_prj, units, stitch, timeout_seconds, **kwargs):
        Path(output_hdf).write_text("hdf", encoding="utf-8")
        Path(output_hdf).with_suffix(".vrt").write_text(
            '<VRTDataset><VRTRasterBand><ComplexSource><SourceFilename relativeToVRT="1">'
            "Terrain.terrain.tif</SourceFilename></ComplexSource></VRTRasterBand></VRTDataset>",
            encoding="utf-8",
        )
        return Path(output_hdf)

    for name in (
        "download_tiles", "_download_seamless_tiles", "_download_single_tile", "find_tiles_for_bbox",
        "download_tile_index", "_get_project_tile_urls", "_get_remote_file_headers",
        "_get_remote_file_size", "_select_1m_tile_groups", "_build_terrain_aoi",
    ):
        monkeypatch.setattr(Usgs3depAws, name, staticmethod(fail))
    monkeypatch.setattr(Usgs3depAws, "_native_resolution_in_crs_units", staticmethod(fake_native))
    monkeypatch.setattr(Usgs3depAws, "_composite_terrain_sources", staticmethod(fake_composite))
    monkeypatch.setattr(RasTerrain, "create_terrain_hdf", staticmethod(fake_create_terrain_hdf))

    # Block the network for the whole process, not just the known entry points.
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(requests, "head", fail)
    monkeypatch.setattr(requests.Session, "request", fail)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setattr(usgs_module.requests, "get", fail)
    monkeypatch.setattr(usgs_module.requests, "head", fail)
    return state


# ---------------------------------------------------------------------------
# plan_terrain_tiles
# ---------------------------------------------------------------------------


def _mock_plan_network(monkeypatch, groups, coverage=None, missing_urls=()):
    monkeypatch.setattr(
        Usgs3depAws,
        "_select_1m_tile_groups",
        staticmethod(lambda *args, **kwargs: (groups, coverage)),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_remote_file_headers",
        staticmethod(
            lambda url: {"content_length": None, "etag": None, "last_modified": None}
            if url in missing_urls else _headers(len(url))
        ),
    )


def test_plan_aoi_is_the_same_aoi_build_terrain_raster_uses(monkeypatch, tmp_path):
    recorded = []
    original = Usgs3depAws._build_terrain_aoi

    def spy(*args, **kwargs):
        aoi, report = original(*args, **kwargs)
        recorded.append(aoi)
        return aoi, report

    monkeypatch.setattr(Usgs3depAws, "_build_terrain_aoi", staticmethod(spy))
    _mock_plan_network(monkeypatch, groups=[])
    geometry = Polygon([(3125000, 10003000), (3125600, 10003100), (3125300, 10003500)])

    plan = Usgs3depAws.plan_terrain_tiles(PROJECT_CRS, aoi_geometry=geometry, buffer_distance=100.0)

    monkeypatch.setattr(Usgs3depAws, "download_tiles", staticmethod(lambda *a, **k: ([], [])))
    monkeypatch.setattr(Usgs3depAws, "_download_seamless_tiles", staticmethod(lambda *a, **k: ([], [])))
    with pytest.raises(TerrainBuildError) as excinfo:
        Usgs3depAws.build_terrain_raster(tmp_path / "t.tif", PROJECT_CRS, aoi_geometry=geometry, buffer_distance=100.0)
    assert excinfo.value.reason_code == Usgs3depAws.TERRAIN_REASON_NO_SOURCES

    # One routine computed both AOIs, and they are identical.
    assert len(recorded) == 2
    assert recorded[0].equals_exact(recorded[1], 0)
    assert shapely.from_wkt(plan["aoi"]["wkt"]).equals_exact(recorded[1], 0)
    receipt = json.loads((tmp_path / "t.terrain_receipt.json").read_text())
    assert receipt["aoi"]["wkt_sha256"] == plan["aoi"]["wkt_sha256"]


def test_plan_lists_tier1_in_composite_order_and_round_trips_through_json(monkeypatch):
    groups = [
        {"project_name": "TX_New_2020", "project_folder": "TX_New_2020", "project_year": 2020,
         "tile_urls": [ONE_M_URL.format(folder="TX_New_2020", name=n) for n in ("USGS_1M_14_x63y333_TX_New_2020", "USGS_1M_14_x62y333_TX_New_2020")]},
        {"project_name": "TX_Old_2017_Collection", "project_folder": "TX_Old_2017", "project_year": 2017,
         "tile_urls": [ONE_M_URL.format(folder="TX_Old_2017", name="USGS_one_meter_x61y333_TX_Old_2017")]},
    ]
    coverage = {
        "bbox_area": 2.0, "covered_fraction": 0.75, "uncovered_fraction": 0.25,
        "uncovered_geometry": box(-97.8, 30.0, -97.7, 30.1), "projects": [{"project": "TX_New_2020", "year": 2020, "area_fraction": 0.75}],
    }
    _mock_plan_network(monkeypatch, groups, coverage)

    plan = Usgs3depAws.plan_terrain_tiles(PROJECT_CRS, aoi_geometry=AOI, exclude_tile_ids=["nothing"])

    tier1 = plan["tiers"][0]
    # Oldest project first, filename order within a project: later tiles win in gdalwarp.
    assert [tile["tile_id"] for tile in tier1["tiles"]] == [
        "USGS_one_meter_x61y333_TX_Old_2017",
        "USGS_1M_14_x62y333_TX_New_2020",
        "USGS_1M_14_x63y333_TX_New_2020",
    ]
    old = tier1["tiles"][0]
    assert old["project"] == "TX_Old_2017_Collection"
    assert old["project_folder"] == "TX_Old_2017"
    assert old["year"] == 2017
    assert old["filename"] == "USGS_one_meter_x61y333_TX_Old_2017.tif"
    assert old["relative_path"] == "3dep_1m_project/USGS_one_meter_x61y333_TX_Old_2017.tif"
    assert old["etag"] == "etag" and old["content_length"] == len(old["url"])
    assert tier1["coverage"]["uncovered_fraction"] == 0.25
    assert tier1["coverage"]["uncovered_area_wgs84_deg2"] == 0.5
    assert shapely.from_wkt(tier1["coverage"]["uncovered_geometry_wkt_wgs84"]).equals(box(-97.8, 30.0, -97.7, 30.1))

    assert plan["schema"] == Usgs3depAws.TILE_PLAN_SCHEMA
    assert plan["project_crs"] == PROJECT_CRS
    assert plan["buffer"] == {"distance": 100.0, "units": "us survey foot", "distance_project_units": 100.0}
    assert plan["aoi"]["bounds"] == pytest.approx([3124900, 10002900, 3125300, 10003300])
    assert len(plan["aoi"]["bounds_wgs84"]) == 4
    assert [tier["resolution"] for tier in plan["tiers"]] == [1, 10, 30]

    round_tripped = json.loads(json.dumps(plan))
    assert round_tripped == plan
    assert Usgs3depAws._tile_plan_digest(round_tripped) == Usgs3depAws._tile_plan_digest(plan)
    assert shapely.from_wkt(round_tripped["aoi"]["wkt"]).equals_exact(shapely.from_wkt(plan["aoi"]["wkt"]), 0)


def test_plan_backfill_tiers_list_every_intersecting_one_degree_tile(monkeypatch):
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:26914", always_xy=True)
    # A triangle around the -98/30 corner whose bounding box touches four
    # 1-degree tiles but whose polygon misses the north-east one.
    triangle = Polygon([to_utm.transform(lon, lat) for lon, lat in [(-98.05, 29.95), (-97.96, 29.95), (-98.05, 30.04)]])
    missing = {SEAMLESS_URL.format(token="1", corner="n30w099")}
    _mock_plan_network(monkeypatch, groups=None, missing_urls=missing)

    plan = Usgs3depAws.plan_terrain_tiles("EPSG:26914", aoi_geometry=triangle, buffer_distance=0)

    tier2, tier3 = plan["tiers"][1], plan["tiers"][2]
    assert tier2["product"] == "3dep_seamless_1_3_arc_second"
    assert sorted(tile["tile_id"] for tile in tier2["tiles"]) == ["USGS_13_n30w098", "USGS_13_n30w099", "USGS_13_n31w099"]
    assert tier2["unavailable_tiles"] == []
    assert sorted(tile["tile_id"] for tile in tier3["tiles"]) == ["USGS_1_n30w098", "USGS_1_n31w099"]
    assert tier3["unavailable_tiles"] == ["USGS_1_n30w099"]
    assert plan["tiers"][0]["tiles"] == []
    tile = next(t for t in tier2["tiles"] if t["tile_id"] == "USGS_13_n31w099")
    assert tile["url"] == SEAMLESS_URL.format(token="13", corner="n31w099")
    assert tile["relative_path"] == "3dep_seamless_1_3_arc_second/USGS_13_n31w099.tif"


def test_plan_honours_exclusions_and_backfill_selection(monkeypatch):
    _mock_plan_network(monkeypatch, groups=None)

    plan = Usgs3depAws.plan_terrain_tiles(
        PROJECT_CRS, aoi_geometry=AOI, backfill_resolutions=(30,), exclude_tile_ids=["USGS_1_n31w098"]
    )

    assert [tier["resolution"] for tier in plan["tiers"]] == [1, 30]
    assert plan["tiers"][1]["tiles"] == []
    assert plan["selection"]["exclude_tile_ids"] == ["USGS_1_n31w098"]


def test_plan_rejects_invalid_backfill():
    with pytest.raises(ValueError, match="backfill_resolutions"):
        Usgs3depAws.plan_terrain_tiles(PROJECT_CRS, aoi_geometry=AOI, backfill_resolutions=(3,))


def test_seamless_tile_bounds_parse_the_north_west_corner():
    assert Usgs3depAws._seamless_tile_bounds("USGS_13_n31w098") == (-98.0, 30.0, -97.0, 31.0)
    with pytest.raises(ValueError):
        Usgs3depAws._seamless_tile_bounds("USGS_1M_14_x62y333")


# ---------------------------------------------------------------------------
# prefetch_terrain_tiles
# ---------------------------------------------------------------------------


def test_prefetch_dedupes_across_plans_keeps_matching_files_and_reports_failures(monkeypatch, tmp_path):
    plan_a = _synthetic_plan(tier1_names=("USGS_1M_14_x62y333_TX_A_2020",), seamless=("n31w098",))
    plan_b = _synthetic_plan(
        tier1_names=("USGS_1M_14_x62y333_TX_A_2020", "USGS_1M_14_x63y333_TX_A_2020"),
        seamless=("n31w098",),
        aoi=box(3126000, 10003000, 3126200, 10003200),
    )
    failing_url = plan_b["tiers"][0]["tiles"][1]["url"]
    store = tmp_path / "store"
    cached_tile = plan_a["tiers"][0]["tiles"][0]
    (store / cached_tile["relative_path"]).parent.mkdir(parents=True)
    (store / cached_tile["relative_path"]).write_bytes(b"x" * 100)
    calls = []

    def fake_download(url, folder, overwrite):
        calls.append(url)
        path = Path(folder) / url.rsplit("/", 1)[-1]
        if url == failing_url:
            path.write_bytes(b"partial")
            return None
        if path.exists() and not overwrite and path.stat().st_size == 100:
            return path
        path.write_bytes(b"x" * 100)
        return path

    monkeypatch.setattr(Usgs3depAws, "_download_single_tile", staticmethod(fake_download))
    monkeypatch.setattr(Usgs3depAws, "_get_remote_file_headers", staticmethod(lambda url: _headers(100)))

    manifest = Usgs3depAws.prefetch_terrain_tiles([plan_a, plan_b], store, max_workers=3)

    # 1m x62 shared + 1m x63 + one 1/3 and one 1 arc-second tile = 4 unique urls, each fetched once.
    assert sorted(calls) == sorted({tile["url"] for plan in (plan_a, plan_b) for tier in plan["tiers"] for tile in tier["tiles"]})
    assert len(calls) == 4
    assert manifest["counts"] == {"plans": 2, "tiles": 4, "downloaded": 2, "cached": 1, "failed": 1}

    by_id = {tile["tile_id"]: tile for tile in manifest["tiles"]}
    shared = by_id["USGS_1M_14_x62y333_TX_A_2020"]
    assert shared["status"] == "cached"
    assert shared["referenced_by_plans"] == [
        Usgs3depAws._tile_plan_digest(plan_a),
        Usgs3depAws._tile_plan_digest(plan_b),
    ]
    assert shared["tier_resolutions"] == [1]
    assert shared["etag"] == "etag" and shared["content_length"] == 100 and shared["local_size_bytes"] == 100
    assert shared["project"] == "TX_A_2020" and shared["filename"] == "USGS_1M_14_x62y333_TX_A_2020.tif"

    failed = by_id["USGS_1M_14_x63y333_TX_A_2020"]
    assert failed["status"] == "failed" and failed["error"] == "download failed"
    assert not (store / failed["relative_path"]).exists()  # partial file removed
    assert by_id["USGS_13_n31w098"]["status"] == "downloaded"
    assert json.loads(json.dumps(manifest)) == manifest


def test_prefetch_removes_size_mismatched_downloads(monkeypatch, tmp_path):
    plan = _synthetic_plan(seamless=())

    def fake_download(url, folder, overwrite):
        path = Path(folder) / url.rsplit("/", 1)[-1]
        path.write_bytes(b"x" * 50)
        return path

    monkeypatch.setattr(Usgs3depAws, "_download_single_tile", staticmethod(fake_download))
    monkeypatch.setattr(Usgs3depAws, "_get_remote_file_headers", staticmethod(lambda url: _headers(100)))

    manifest = Usgs3depAws.prefetch_terrain_tiles(plan, tmp_path)

    tile = manifest["tiles"][0]
    assert tile["status"] == "failed" and "size mismatch" in tile["error"]
    assert not (tmp_path / tile["relative_path"]).exists()


def test_prefetch_requires_a_valid_plan(tmp_path):
    with pytest.raises(ValueError):
        Usgs3depAws.prefetch_terrain_tiles([], tmp_path)
    with pytest.raises(ValueError, match="tile plan"):
        Usgs3depAws.prefetch_terrain_tiles({"schema": "other"}, tmp_path)


# ---------------------------------------------------------------------------
# build_terrain_raster(tile_plan=..., require_cached_tiles=...)
# ---------------------------------------------------------------------------


def test_offline_build_makes_no_network_calls_and_writes_nothing_to_the_store(offline_pipeline, tmp_path):
    plan = _synthetic_plan()
    store = tmp_path / "store"
    _populate_store(store, plan)
    before = _snapshot(store)
    output = tmp_path / "out" / "terrain.tif"

    receipt = Usgs3depAws.build_terrain_raster(
        output,
        PROJECT_CRS,
        download_folder=store,
        tile_plan=plan,
        require_cached_tiles=True,
        hec_terrain_hdf=tmp_path / "out" / "hec" / "Terrain.hdf",
    )

    assert _snapshot(store) == before
    assert receipt["status"] == "pass"
    assert receipt["build_mode"]["offline"] is True
    assert receipt["build_mode"]["network_access"] == "none"
    assert receipt["build_mode"]["tile_plan"]["sha256"] == Usgs3depAws._tile_plan_digest(plan)
    assert receipt["resolution"]["value"] == float(Fraction(3937, 600))
    assert receipt["nodata"]["inside_aoi_count"] == 0
    assert receipt["hec_terrain"]["source_member_count"] == 1
    tier1 = receipt["tiers"][0]
    assert tier1["contributed_aoi_pixels"] == receipt["nodata"]["aoi_pixel_count"]
    assert tier1["tiles"][0]["provenance_source"] == "tile_plan"
    assert tier1["tiles"][0]["size_matches_plan"] is True
    assert tier1["tiles"][0]["file_path"] == str(store / plan["tiers"][0]["tiles"][0]["relative_path"])
    assert [path.name for path in offline_pipeline["composites"][-1]] == ["USGS_1M_14_x62y333_TX_A_2020.tif"]
    assert output.exists() and output.parent != store
    assert json.loads(output.with_name("terrain.terrain_receipt.json").read_text())["build_mode"]["offline"] is True


@pytest.mark.parametrize("tier_index", [0, 1])
def test_offline_build_with_a_missing_tile_fails_with_the_not_cached_reason(offline_pipeline, tmp_path, tier_index):
    plan = _synthetic_plan()
    store = tmp_path / "store"
    _populate_store(store, plan)
    missing = plan["tiers"][tier_index]["tiles"][0]["relative_path"]
    (store / missing).unlink()
    before = _snapshot(store)
    output = tmp_path / "out" / "terrain.tif"

    with pytest.raises(TerrainBuildError) as excinfo:
        Usgs3depAws.build_terrain_raster(
            output, PROJECT_CRS, download_folder=store, tile_plan=plan, require_cached_tiles=True
        )

    error = excinfo.value
    assert error.reason_code == Usgs3depAws.TERRAIN_REASON_TILE_NOT_CACHED == "terrain_tile_not_cached"
    assert error.details["missing_tiles"] == [missing]
    assert missing in str(error)
    assert not output.exists()
    assert _snapshot(store) == before
    receipt = json.loads(Path(error.details["receipt_path"]).read_text())
    assert receipt["status"] == "fail" and receipt["reason_code"] == "terrain_tile_not_cached"
    assert receipt["build_mode"]["offline"] is True


def test_require_cached_tiles_without_a_plan_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="require_cached_tiles=True needs tile_plan"):
        Usgs3depAws.build_terrain_raster(
            tmp_path / "t.tif", PROJECT_CRS, aoi_geometry=AOI, require_cached_tiles=True
        )


def test_tile_plan_rejects_geometry_mismatched_crs_and_unplanned_backfill(tmp_path):
    plan = _synthetic_plan()
    with pytest.raises(ValueError, match="not both"):
        Usgs3depAws.build_terrain_raster(tmp_path / "t.tif", PROJECT_CRS, aoi_geometry=AOI, tile_plan=plan)
    with pytest.raises(ValueError, match="does not match"):
        Usgs3depAws.build_terrain_raster(tmp_path / "t.tif", "EPSG:26914", tile_plan=plan)
    plan["tiers"] = plan["tiers"][:2]
    with pytest.raises(ValueError, match="not in the tile plan"):
        Usgs3depAws.build_terrain_raster(tmp_path / "t.tif", PROJECT_CRS, tile_plan=plan)


def test_online_plan_build_uses_plan_tiles_without_index_or_listing_queries(offline_pipeline, monkeypatch, tmp_path):
    plan = _synthetic_plan()
    store = tmp_path / "store"
    downloads = []

    def fake_download(url, folder, overwrite):
        downloads.append(url)
        path = Path(folder) / url.rsplit("/", 1)[-1]
        path.write_bytes(b"x" * 100)
        return path

    monkeypatch.setattr(Usgs3depAws, "_download_single_tile", staticmethod(fake_download))

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    receipt = Usgs3depAws.build_terrain_raster(
        tmp_path / "out" / "terrain.tif", PROJECT_CRS, download_folder=store, tile_plan=plan_path
    )

    assert receipt["status"] == "pass"
    assert receipt["build_mode"]["offline"] is False
    assert receipt["build_mode"]["tile_plan"]["sha256"] == Usgs3depAws._tile_plan_digest(plan)
    # Only tier 1 was needed; its plan tile was fetched directly into the store layout.
    assert downloads == [plan["tiers"][0]["tiles"][0]["url"]]
    assert (store / plan["tiers"][0]["tiles"][0]["relative_path"]).exists()
    assert [tier["status"] for tier in receipt["tiers"]] == ["used", "not_required", "not_required"]
