"""Single-raster, project-CRS USGS 3DEP terrain builds.

RASMapper creates result rasters that mirror the terrain VRT structure, so the
terrain handed to HEC-RAS must be ONE raster in the project CRS with no nodata
inside the buffered model extent. These tests pin the AOI construction,
priority/backfill ordering, the integer-multiple cell-size rule, explicit
vertical unit conversion, the nodata gate, the single-member Terrain.vrt assertion, and the
HEC-RAS terrain handoff. GDAL executables, HEC-RAS, and all network
access are mocked; small real GeoTIFFs are written with rasterio where pixel
values matter.
"""

import inspect
import json
import logging
import math
import subprocess
from fractions import Fraction
from importlib import import_module
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Polygon, box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws
TerrainBuildError = usgs_module.TerrainBuildError

FTUS_PER_METRE = 3937.0 / 1200.0
PROJECT_CRS = "EPSG:2277"


def _write_raster(path, array, transform, crs, nodata):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=array.shape[1],
        height=array.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(array.astype("float32"), 1)
    return path


# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------


def test_aoi_buffer_is_absolute_us_survey_feet_in_a_feet_project():
    aoi, report = Usgs3depAws._build_terrain_aoi(
        PROJECT_CRS, aoi_geometry=box(0, 0, 1000, 1000)
    )

    assert report["buffer_distance_project_units"] == pytest.approx(100.0)
    assert aoi.bounds == pytest.approx((-100, -100, 1100, 1100))
    assert report["source"] == "caller_geometry"


def test_aoi_buffer_converts_us_survey_feet_into_a_metre_project():
    _, report = Usgs3depAws._build_terrain_aoi(
        "EPSG:26914", aoi_geometry=box(0, 0, 1000, 1000)
    )

    assert report["buffer_distance_project_units"] == pytest.approx(100.0 * 1200.0 / 3937.0)


def test_aoi_buffer_accepts_project_units():
    _, report = Usgs3depAws._build_terrain_aoi(
        "EPSG:26914",
        aoi_geometry=box(0, 0, 1000, 1000),
        buffer_distance=25,
        buffer_units="project",
    )

    assert report["buffer_distance_project_units"] == 25


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "exactly one"),
        ({"geom_path": "x.g01", "aoi_geometry": box(0, 0, 1, 1)}, "exactly one"),
        ({"aoi_geometry": box(0, 0, 1, 1), "buffer_distance": -1}, "negative"),
        ({"aoi_geometry": LineString([(0, 0), (1, 1)]), "buffer_distance": 0}, "no area"),
    ],
)
def test_aoi_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Usgs3depAws._build_terrain_aoi(PROJECT_CRS, **kwargs)


def test_aoi_rejects_geographic_project_crs():
    with pytest.raises(ValueError, match="projected"):
        Usgs3depAws._build_terrain_aoi("EPSG:4326", aoi_geometry=box(0, 0, 1, 1))


def test_aoi_from_geometry_contains_protruding_cross_sections(monkeypatch, tmp_path):
    """Cross sections past the edge-line footprint must still be inside the AOI."""
    geom_file = tmp_path / "Model.g01"
    geom_file.write_text("", encoding="utf-8")

    footprint = box(0, 0, 1000, 200)
    inside_xs = LineString([(100, 20), (100, 180)])
    protruding_xs = LineString([(500, -400), (500, 600)])

    hdf_project = import_module("ras_commander.hdf.HdfProject").HdfProject
    geom_parser = import_module("ras_commander.geom.GeomParser").GeomParser

    monkeypatch.setattr(
        hdf_project,
        "get_project_extent",
        staticmethod(
            lambda *args, **kwargs: (
                gpd.GeoDataFrame(geometry=[footprint]),
                footprint.bounds,
            )
        ),
    )
    monkeypatch.setattr(
        geom_parser,
        "get_xs_cut_lines",
        staticmethod(lambda path: gpd.GeoDataFrame(geometry=[inside_xs, protruding_xs])),
    )

    aoi, report = Usgs3depAws._build_terrain_aoi(PROJECT_CRS, geom_path=geom_file)

    assert report["cross_section_count"] == 2
    assert report["cross_sections_outside_footprint"] == 1
    for line in (inside_xs, protruding_xs):
        assert aoi.contains(line)
        # ...with the full absolute buffer around the protruding endpoints.
        assert aoi.contains(line.buffer(99.0))
    assert not footprint.buffer(100).contains(protruding_xs)


# ---------------------------------------------------------------------------
# Resolution and grid
# ---------------------------------------------------------------------------


def test_native_resolution_of_1m_utm_is_exact_us_survey_feet(tmp_path):
    raster = _write_raster(
        tmp_path / "utm.tif",
        np.zeros((4, 4)),
        from_origin(620000, 3330000, 1.0, 1.0),
        "EPSG:26914",
        -9999,
    )

    result = Usgs3depAws._native_resolution_in_crs_units(
        raster, PROJECT_CRS, box(3125000, 10003000, 3125001, 10003001).centroid
    )

    assert result["native_resolution_project_units"] == 3.2808333333333333
    assert result["_native_resolution_exact"] == Fraction(3937, 1200)
    assert result["native_resolution_source_unit"] == "metre"


def test_native_resolution_of_one_third_arc_second_is_about_30_feet(tmp_path):
    step = 1.0 / 3.0 / 3600.0
    raster = _write_raster(
        tmp_path / "geo.tif",
        np.zeros((4, 4)),
        from_origin(-98.0, 31.0, step, step),
        "EPSG:4269",
        -999999,
    )

    result = Usgs3depAws._native_resolution_in_crs_units(
        raster, PROJECT_CRS, box(3125000, 10003000, 3125001, 10003001).centroid
    )

    assert result["native_resolution_source_unit"] == "degree"
    assert 28.0 < result["native_resolution_project_units"] < 32.0


def test_snap_bounds_outward_matches_target_aligned_pixels():
    assert Usgs3depAws._snap_bounds_outward((12.5, 7.1, 38.2, 19.9), 10) == (10, 0, 40, 20)


# ---------------------------------------------------------------------------
# Cell-size rule
# ---------------------------------------------------------------------------

ONE_METRE_FTUS = Fraction(3937, 1200)


@pytest.mark.parametrize(
    "dominant, minimum, expected_multiple, expected_cell",
    [
        # 1 m in EPSG:2277: 3.28 ft < 5 ft, so k = 2.
        (ONE_METRE_FTUS, 5.0, 2, Fraction(3937, 600)),
        # 10 m (32.8 ft) already meets the minimum: k = 1.
        (10 * ONE_METRE_FTUS, 5.0, 1, 10 * ONE_METRE_FTUS),
        # Exactly equal to the minimum: k = 1, not 2.
        (Fraction(5), 5.0, 1, Fraction(5)),
        # An exact divisor of the minimum: k = 2 exactly, not 3.
        (Fraction(5, 2), 5.0, 2, Fraction(5)),
        # Metre project, 1 m source, 5 m minimum: k = 5.
        (Fraction(1), 5.0, 5, Fraction(5)),
    ],
)
def test_cell_size_rule_picks_smallest_multiple_reaching_the_minimum(
    dominant, minimum, expected_multiple, expected_cell
):
    cell, report = Usgs3depAws._cell_size_for_dominant(dominant, minimum)

    assert cell == expected_cell
    assert report["multiple"] == expected_multiple
    assert report["value"] == float(expected_cell)
    assert report["dominant_resolution"] == float(dominant)
    assert report["minimum_cell_size"] == minimum
    assert report["chosen_by"] == "minimum_cell_size_rule"
    assert report["snapped"] is False


def test_cell_size_for_1m_in_epsg2277_is_exactly_twice_3937_over_1200_ftus():
    cell, _ = Usgs3depAws._cell_size_for_dominant(ONE_METRE_FTUS, 5.0)

    assert cell == Fraction(3937, 600)
    assert float(cell) == 6.5616666666666667


def test_cell_size_override_that_is_an_integer_multiple_is_used_as_is(caplog):
    caplog.set_level(logging.WARNING, logger=usgs_module.logger.name)

    cell, report = Usgs3depAws._cell_size_for_dominant(
        ONE_METRE_FTUS, 5.0, target_resolution=float(3 * ONE_METRE_FTUS)
    )

    assert cell == 3 * ONE_METRE_FTUS
    assert report["chosen_by"] == "override"
    assert report["snapped"] is False
    assert "not an integer multiple" not in caplog.text


@pytest.mark.parametrize(
    "requested, expected_multiple",
    [
        (10.0, 3),   # 10 / 3.28 = 3.05 -> 3 x = 9.8425 ft
        (12.0, 4),   # 12 / 3.28 = 3.66 -> 4 x = 13.1233 ft
        (1.0, 1),    # below the dominant resolution -> at least 1 x
    ],
)
def test_cell_size_override_that_is_not_a_multiple_is_snapped_with_a_warning(
    caplog, requested, expected_multiple
):
    caplog.set_level(logging.WARNING, logger=usgs_module.logger.name)

    cell, report = Usgs3depAws._cell_size_for_dominant(
        ONE_METRE_FTUS, 5.0, target_resolution=requested
    )

    assert cell == expected_multiple * ONE_METRE_FTUS
    assert report["multiple"] == expected_multiple
    assert report["requested_resolution"] == requested
    assert report["snapped"] is True
    assert report["chosen_by"] == "override_snapped"
    assert "not an integer multiple" in caplog.text


def test_cell_size_rule_rejects_non_positive_sizes():
    with pytest.raises(ValueError):
        Usgs3depAws._cell_size_for_dominant(ONE_METRE_FTUS, 0)
    with pytest.raises(ValueError):
        Usgs3depAws._cell_size_for_dominant(ONE_METRE_FTUS, 5.0, target_resolution=-1)


def test_composite_orders_sources_lowest_priority_first(monkeypatch, tmp_path):
    gdalwarp = tmp_path / "6.6" / "GDAL" / "bin64" / "gdalwarp.exe"
    gdalwarp.parent.mkdir(parents=True)
    gdalwarp.write_text("", encoding="utf-8")
    calls = []

    def fake_run(cmd, capture_output, text, timeout, env):
        calls.append((cmd, env))
        Path(cmd[-1]).write_text("tif", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    ras_terrain = import_module("ras_commander.terrain.RasTerrain").RasTerrain
    monkeypatch.setattr(
        Usgs3depAws, "_find_gdalwarp_path", staticmethod(lambda hecras_version=None: gdalwarp)
    )
    monkeypatch.setattr(
        ras_terrain,
        "_build_hecras_terrain_env",
        staticmethod(lambda install_dir: {"HEC_INSTALL": str(install_dir)}),
    )
    monkeypatch.setattr(usgs_module.subprocess, "run", fake_run)

    tiers = [
        {"tier": 1, "paths": [Path("old_1m.tif"), Path("new_1m.tif")]},
        {"tier": 2, "paths": [Path("USGS_13_n31w098.tif")]},
        {"tier": 3, "paths": [Path("USGS_1_n31w098.tif")]},
    ]

    Usgs3depAws._composite_terrain_sources(
        tiers,
        tmp_path / "composite.tif",
        PROJECT_CRS,
        3.2808333333333333,
        (3125000.4, 10003000.4, 3125600.2, 10003600.2),
        src_nodata=None,
        nodata=-9999.0,
    )

    cmd, env = calls[0]
    assert env == {"HEC_INSTALL": str(tmp_path / "6.6")}
    sources = cmd[-5:-1]
    assert sources == [
        "USGS_1_n31w098.tif",
        "USGS_13_n31w098.tif",
        "old_1m.tif",
        "new_1m.tif",
    ]
    assert cmd[cmd.index("-t_srs") + 1] == PROJECT_CRS
    assert cmd[cmd.index("-tr") + 1: cmd.index("-tr") + 3] == [
        "3.2808333333333333",
        "3.2808333333333333",
    ]
    assert "-tap" in cmd
    te = [float(value) for value in cmd[cmd.index("-te") + 1: cmd.index("-te") + 5]]
    assert te[0] <= 3125000.4 and te[1] <= 10003000.4
    assert te[2] >= 3125600.2 and te[3] >= 10003600.2
    for value in te:
        assert math.isclose(round(value / 3.2808333333333333), value / 3.2808333333333333, abs_tol=1e-6)
    assert cmd[cmd.index("-of") + 1] == "GTiff"
    assert cmd[cmd.index("-dstnodata") + 1] == "-9999.0"
    assert "-srcnodata" not in cmd
    assert "BIGTIFF=IF_SAFER" in cmd


# ---------------------------------------------------------------------------
# Vertical conversion, nodata gate, VRT members
# ---------------------------------------------------------------------------


def test_scale_raster_values_converts_metres_to_us_survey_feet(tmp_path):
    array = np.array([[100.0, -9999.0], [np.nan, 194.1614]], dtype="float32")
    source = _write_raster(
        tmp_path / "metres.tif", array, from_origin(0, 20, 10, 10), PROJECT_CRS, -9999.0
    )
    output = tmp_path / "feet.tif"

    Usgs3depAws._scale_raster_values(source, output, FTUS_PER_METRE, -9999.0, "us survey foot")

    with rasterio.open(output) as src:
        scaled = src.read(1)
        assert src.nodata == -9999.0
        assert src.crs == rasterio.crs.CRS.from_string(PROJECT_CRS)
        assert src.transform == from_origin(0, 20, 10, 10)
        assert src.tags(1)["VERTICAL_UNIT"] == "us survey foot"

    assert scaled[0, 0] == pytest.approx(328.08333, rel=1e-6)
    assert scaled[1, 1] == pytest.approx(194.1614 * FTUS_PER_METRE, rel=1e-6)
    assert scaled[0, 1] == -9999.0
    assert scaled[1, 0] == -9999.0
    # Guard against the silent 3.28x error in either direction.
    assert scaled[0, 0] / 100.0 == pytest.approx(3.2808333, rel=1e-6)


def test_nodata_gate_ignores_nodata_outside_the_aoi_polygon(tmp_path):
    array = np.full((10, 10), 5.0, dtype="float32")
    array[0, 9] = -9999.0  # top-right corner: inside the bbox, outside the triangle
    raster = _write_raster(
        tmp_path / "gate.tif", array, from_origin(0, 100, 10, 10), PROJECT_CRS, -9999.0
    )
    triangle = Polygon([(0, 0), (100, 0), (0, 100)])

    result = Usgs3depAws._count_nodata_in_aoi(raster, triangle, -9999.0)

    assert result["nodata_pixel_count"] == 0
    assert result["nodata_bounds"] is None
    assert result["aoi_pixel_count"] < 100


def test_nodata_gate_counts_and_locates_nodata_inside_the_aoi(tmp_path):
    array = np.full((10, 10), 5.0, dtype="float32")
    array[9, 0] = -9999.0
    array[8, 1] = np.nan
    raster = _write_raster(
        tmp_path / "gate.tif", array, from_origin(0, 100, 10, 10), PROJECT_CRS, -9999.0
    )
    triangle = Polygon([(0, 0), (100, 0), (0, 100)])

    result = Usgs3depAws._count_nodata_in_aoi(raster, triangle, -9999.0, window_size=3)

    assert result["nodata_pixel_count"] == 2
    assert result["nodata_bounds"] == [0.0, 0.0, 20.0, 20.0]
    assert sorted(result["nodata_samples"]) == [[5.0, 5.0], [15.0, 15.0]]


def _vrt(members):
    sources = "".join(
        f"<ComplexSource><SourceFilename relativeToVRT=\"1\">{name}</SourceFilename>"
        "<SourceBand>1</SourceBand></ComplexSource>"
        for name in members
    )
    return (
        '<VRTDataset rasterXSize="1" rasterYSize="1">'
        f'<VRTRasterBand dataType="Float32" band="1">{sources}</VRTRasterBand>'
        "</VRTDataset>"
    )


@pytest.mark.parametrize("members", [["Terrain.dem.tif"], ["a.tif", "b.tif"]])
def test_count_vrt_source_members(tmp_path, members):
    vrt = tmp_path / "Terrain.vrt"
    vrt.write_text(_vrt(members), encoding="utf-8")

    assert Usgs3depAws._count_vrt_source_members(vrt) == members


# ---------------------------------------------------------------------------
# End-to-end orchestration with mocked sources and gdalwarp
# ---------------------------------------------------------------------------

AOI = box(3125000, 10003000, 3125200, 10003200)
TIER_RESOLUTION = {
    "t1.tif": Fraction(3937, 1200),   # 1 m -> k = 2 -> 6.5616666666666667 ft
    "t2.tif": Fraction(30),           # ~10 m backfill already >= 5 ft -> k = 1
    "t3.tif": Fraction(90),
}
CELL_1M = float(Fraction(3937, 600))


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Fake sources whose tier-1 coverage is a configurable fraction of the grid."""
    state = {"tier1_fraction": 1.0, "composites": [], "seamless_requests": [], "hec_members": ["one.tif"]}

    def fake_download_tiles(bbox, resolution, output_folder, cache_folder=None, **kwargs):
        assert kwargs["project_selection"] == "coverage"
        assert kwargs["return_provenance"] is True
        if state["tier1_fraction"] == 0:
            return [], []
        return [Path("t1.tif")], [_prov("t1", "TX_Central_B1_2017", 2017)]

    def fake_seamless(bounds_wgs84, resolution, output_folder, max_workers=3, exclude_tile_ids=None):
        state["seamless_requests"].append((resolution, bounds_wgs84))
        name = "t2" if resolution == 10 else "t3"
        if name in (exclude_tile_ids or []):
            return [], []
        return [Path(f"{name}.tif")], [_prov(name, f"seamless_{resolution}", None)]

    def fake_native(path, project_crs, point):
        return {
            "native_resolution_source_units": 1.0,
            "native_resolution_source_unit": "metre",
            "native_resolution_source_crs": "EPSG:26914",
            "native_resolution_project_units": float(TIER_RESOLUTION[Path(path).name]),
            "_native_resolution_exact": TIER_RESOLUTION[Path(path).name],
        }

    def fake_composite(tiers, output_path, project_crs, resolution, aoi_bounds, **kwargs):
        names = [path.name for tier in reversed(list(tiers)) for path in tier["paths"]]
        state["composites"].append((names, resolution))
        minx, miny, maxx, maxy = Usgs3depAws._snap_bounds_outward(aoi_bounds, resolution)
        width = int(round((maxx - minx) / resolution))
        height = int(round((maxy - miny) / resolution))
        array = np.full((height, width), -9999.0, dtype="float32")
        if "t2.tif" in names or "t3.tif" in names:
            array[:, :] = 50.0
        covered = int(round(width * state["tier1_fraction"]))
        if "t1.tif" in names:
            array[:, :covered] = 100.0
        _write_raster(
            output_path, array, from_origin(minx, maxy, resolution, resolution), project_crs, -9999.0
        )
        return Path(output_path), Path("gdalwarp.exe")

    def fake_create_terrain_hdf(input_rasters, output_hdf, projection_prj, units, stitch, timeout_seconds, **kwargs):
        state["hec_call"] = dict(input_rasters=input_rasters, units=units, stitch=stitch)
        Path(output_hdf).write_text("hdf", encoding="utf-8")
        Path(output_hdf).with_suffix(".vrt").write_text(_vrt(state["hec_members"]), encoding="utf-8")
        return Path(output_hdf)

    ras_terrain = import_module("ras_commander.terrain.RasTerrain").RasTerrain
    monkeypatch.setattr(Usgs3depAws, "download_tiles", staticmethod(fake_download_tiles))
    monkeypatch.setattr(Usgs3depAws, "_download_seamless_tiles", staticmethod(fake_seamless))
    monkeypatch.setattr(Usgs3depAws, "_native_resolution_in_crs_units", staticmethod(fake_native))
    monkeypatch.setattr(Usgs3depAws, "_composite_terrain_sources", staticmethod(fake_composite))
    monkeypatch.setattr(ras_terrain, "create_terrain_hdf", staticmethod(fake_create_terrain_hdf))

    state["output"] = tmp_path / "terrain.tif"
    return state


def _prov(tile_id, project, year):
    return {
        "tile_id": tile_id,
        "file_name": f"{tile_id}.tif",
        "file_path": f"{tile_id}.tif",
        "source_url": f"https://example.com/{tile_id}.tif",
        "project_name": project,
        "project_year": year,
        "etag": "etag",
        "last_modified": "Tue, 04 Feb 2025 18:03:11 GMT",
        "content_length": 10,
        "local_size_bytes": 10,
    }


def test_build_uses_only_tier1_when_it_covers_the_aoi(pipeline):
    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0
    )

    assert pipeline["seamless_requests"] == []
    assert [tier["status"] for tier in receipt["tiers"]] == ["used", "not_required", "not_required"]
    resolution = receipt["resolution"]
    assert resolution["value"] == CELL_1M == 6.5616666666666667
    assert resolution["multiple"] == 2
    assert resolution["dominant_resolution"] == 3.2808333333333333
    assert resolution["minimum_cell_size"] == 5.0
    assert resolution["chosen_by"] == "minimum_cell_size_rule"
    assert resolution["resampling"] == "bilinear"
    assert "smallest integer multiple" in resolution["reason"]
    # One composite at the final cell size: no re-warp.
    assert [cell for _, cell in pipeline["composites"]] == [CELL_1M]
    assert "_native_resolution_exact" not in receipt["tiers"][0]
    assert receipt["composite"]["resampling"] == "bilinear"
    assert receipt["nodata"]["inside_aoi_count"] == 0
    assert receipt["vertical"]["scale_factor"] == pytest.approx(FTUS_PER_METRE)
    assert receipt["tiers"][0]["projects"] == ["TX_Central_B1_2017"]
    assert receipt["tiers"][0]["tiles"][0]["etag"] == "etag"

    with rasterio.open(pipeline["output"]) as src:
        values = src.read(1)
        assert src.count == 1
        assert src.res == pytest.approx((CELL_1M, CELL_1M))
    assert np.allclose(values, 100.0 * FTUS_PER_METRE)
    assert json.loads(pipeline["output"].with_name("terrain.terrain_receipt.json").read_text())["status"] == "pass"


def test_build_backfills_only_where_tier1_leaves_gaps(pipeline):
    pipeline["tier1_fraction"] = 0.75

    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0
    )

    tiers = receipt["tiers"]
    assert [tier["status"] for tier in tiers] == ["used", "used", "not_required"]
    assert [request[0] for request in pipeline["seamless_requests"]] == [10]
    # Tier 2 is requested only for the bounds of the uncovered pixels.
    request_bounds = pipeline["seamless_requests"][0][1]
    aoi_wgs84 = Usgs3depAws._geometry_to_wgs84(AOI, PROJECT_CRS).bounds
    assert request_bounds[0] > aoi_wgs84[0]
    # Composite order: lowest priority first.
    assert pipeline["composites"][-1][0] == ["t2.tif", "t1.tif"]
    assert tiers[0]["contributed_aoi_pixels"] > tiers[1]["contributed_aoi_pixels"] > 0
    assert receipt["resolution"]["dominant_tier"] == 1

    with rasterio.open(pipeline["output"]) as src:
        values = src.read(1)
    assert (values != -9999.0).all()
    assert np.unique(values).tolist() == pytest.approx(
        [50.0 * FTUS_PER_METRE, 100.0 * FTUS_PER_METRE], rel=1e-6
    )


def test_build_uses_backfill_resolution_when_backfill_dominates(pipeline):
    pipeline["tier1_fraction"] = 0.2

    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0
    )

    assert receipt["resolution"]["dominant_tier"] == 2
    # The dominant backfill cell (30 ft) already meets the 5-ft minimum: k = 1.
    assert receipt["resolution"]["multiple"] == 1
    assert receipt["resolution"]["value"] == 30.0
    assert "tier 2" in receipt["resolution"]["reason"]
    assert pipeline["composites"][-1] == (["t2.tif", "t1.tif"], 30.0)


def test_build_minimum_cell_size_is_adjustable(pipeline):
    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0, minimum_cell_size=10.0
    )

    assert receipt["resolution"]["multiple"] == 4
    assert receipt["resolution"]["value"] == float(4 * Fraction(3937, 1200))


def test_build_honours_an_integer_multiple_override(pipeline):
    requested = float(3 * Fraction(3937, 1200))

    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0, target_resolution=requested
    )

    assert receipt["resolution"]["chosen_by"] == "override"
    assert receipt["resolution"]["snapped"] is False
    assert all(cell == requested for _, cell in pipeline["composites"])


def test_build_snaps_a_non_multiple_override_and_records_it(pipeline, caplog):
    caplog.set_level(logging.WARNING, logger=usgs_module.logger.name)

    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0, target_resolution=10.0
    )

    resolution = receipt["resolution"]
    assert resolution["chosen_by"] == "override_snapped"
    assert resolution["requested_resolution"] == 10.0
    assert resolution["snapped"] is True
    assert resolution["multiple"] == 3
    assert resolution["value"] == float(3 * Fraction(3937, 1200))
    assert all(cell == resolution["value"] for _, cell in pipeline["composites"])
    assert "not an integer multiple" in caplog.text


def test_build_defaults_to_bilinear_and_a_5_unit_minimum():
    parameters = inspect.signature(Usgs3depAws.build_terrain_raster).parameters

    assert parameters["minimum_cell_size"].default == 5.0
    assert parameters["resampling_method"].default == "bilinear"
    assert "dominant_resampling" not in parameters
    assert "backfill_resampling" not in parameters


def test_build_validates_minimum_cell_size(pipeline):
    with pytest.raises(ValueError, match="minimum_cell_size"):
        Usgs3depAws.build_terrain_raster(
            pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, minimum_cell_size=0
        )


def test_build_fails_the_gate_when_backfill_is_exhausted(pipeline):
    pipeline["tier1_fraction"] = 0.5

    with pytest.raises(TerrainBuildError) as excinfo:
        Usgs3depAws.build_terrain_raster(
            pipeline["output"],
            PROJECT_CRS,
            aoi_geometry=AOI,
            buffer_distance=0,
            exclude_tile_ids=["t2", "t3"],
        )

    error = excinfo.value
    assert error.reason_code == Usgs3depAws.TERRAIN_REASON_AOI_NODATA
    assert error.details["nodata_pixel_count"] > 0
    assert error.details["nodata_bounds"][0] > AOI.bounds[0]
    assert len(error.details["nodata_samples"]) > 0
    assert not pipeline["output"].exists()

    receipt = json.loads(Path(error.details["receipt_path"]).read_text())
    assert receipt["status"] == "fail"
    assert receipt["reason_code"] == "terrain_aoi_nodata_after_backfill"
    assert [tier["status"] for tier in receipt["tiers"]] == ["used", "no_sources", "no_sources"]


def test_build_fails_when_no_tier_supplies_tiles(pipeline):
    pipeline["tier1_fraction"] = 0

    with pytest.raises(TerrainBuildError) as excinfo:
        Usgs3depAws.build_terrain_raster(
            pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, buffer_distance=0, backfill_resolutions=()
        )

    assert excinfo.value.reason_code == Usgs3depAws.TERRAIN_REASON_NO_SOURCES


def test_build_hec_terrain_has_exactly_one_source_member(pipeline, tmp_path):
    receipt = Usgs3depAws.build_terrain_raster(
        pipeline["output"],
        PROJECT_CRS,
        aoi_geometry=AOI,
        hec_terrain_hdf=tmp_path / "hec" / "Terrain.hdf",
    )

    assert pipeline["hec_call"] == {
        "input_rasters": [pipeline["output"]],
        "units": "Feet",
        "stitch": False,
    }
    assert receipt["hec_terrain"]["source_member_count"] == 1
    assert receipt["hec_terrain"]["build_seconds"] >= 0
    assert "PROJCS" in (tmp_path / "hec" / "Projection.prj").read_text()
    assert sorted(path.name for path in pipeline["output"].parent.glob("*.tif")) == ["terrain.tif"]


def test_build_rejects_a_multi_source_hec_terrain(pipeline, tmp_path):
    pipeline["hec_members"] = ["a.tif", "b.tif"]

    with pytest.raises(TerrainBuildError) as excinfo:
        Usgs3depAws.build_terrain_raster(
            pipeline["output"],
            PROJECT_CRS,
            aoi_geometry=AOI,
            hec_terrain_hdf=tmp_path / "hec" / "Terrain.hdf",
        )

    assert excinfo.value.reason_code == Usgs3depAws.TERRAIN_REASON_HEC_MULTI_SOURCE


def test_build_refuses_to_overwrite_and_validates_backfill(pipeline):
    pipeline["output"].write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        Usgs3depAws.build_terrain_raster(pipeline["output"], PROJECT_CRS, aoi_geometry=AOI)

    with pytest.raises(ValueError, match="backfill_resolutions"):
        Usgs3depAws.build_terrain_raster(
            pipeline["output"], PROJECT_CRS, aoi_geometry=AOI, overwrite=True, backfill_resolutions=(3,)
        )


# ---------------------------------------------------------------------------
# Seamless backfill tiles and 1m tile naming
# ---------------------------------------------------------------------------


def test_seamless_tile_names_use_the_north_west_corner():
    assert Usgs3depAws._seamless_tile_names((-97.73, 30.07, -97.69, 30.09), 10) == ["USGS_13_n31w098"]
    assert Usgs3depAws._seamless_tile_names((-98.2, 29.9, -97.9, 30.1), 30) == [
        "USGS_1_n31w099",
        "USGS_1_n31w098",
        "USGS_1_n30w099",
        "USGS_1_n30w098",
    ]


def test_download_seamless_tiles_skips_missing_and_excluded(monkeypatch, tmp_path):
    requested = []

    def fake_size(url):
        return None if "w099" in url else 42

    def fake_download(tile_url, output_folder, overwrite_dest):
        requested.append(tile_url)
        return Path(output_folder) / tile_url.rsplit("/", 1)[-1]

    monkeypatch.setattr(Usgs3depAws, "_get_remote_file_size", staticmethod(fake_size))
    monkeypatch.setattr(Usgs3depAws, "_download_single_tile", staticmethod(fake_download))
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_remote_file_headers",
        staticmethod(lambda url: {"content_length": 42, "etag": "e", "last_modified": "lm"}),
    )

    paths, provenance = Usgs3depAws._download_seamless_tiles(
        (-98.2, 29.9, -97.9, 30.1), 10, tmp_path, exclude_tile_ids=["USGS_13_n30w098"]
    )

    assert [path.name for path in paths] == ["USGS_13_n31w098.tif"]
    assert requested == [
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n31w098/USGS_13_n31w098.tif"
    ]
    assert provenance[0]["project_name"] == "3dep_seamless_1_3_arc_second"
