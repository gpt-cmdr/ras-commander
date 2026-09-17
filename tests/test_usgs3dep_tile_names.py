"""USGS 3DEP 1m tile-name parsing and tile exclusion.

Tile names encode the upper-left corner in 10km UTM units: ``x`` is the west
edge and ``y`` is the NORTH edge. The expectations below come from real tile
headers read from S3. All network access is mocked.
"""

from importlib import import_module
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


def test_1m_tile_name_y_index_is_the_north_edge():
    """Observed: USGS_1M_14_x80y330 spans northing 3290000-3300000 (EPSG:26914)."""
    from pyproj import Transformer

    bounds = Usgs3depAws._parse_tile_bounds_from_filename("USGS_1M_14_x80y330_TX_Houston_B24.tif")
    to_wgs84 = Transformer.from_crs("EPSG:26914", "EPSG:4326", always_xy=True)
    centre_lon, centre_lat = to_wgs84.transform(805000, 3295000)
    north_lon, north_lat = to_wgs84.transform(805000, 3305000)

    assert bounds[0] < centre_lon < bounds[2] and bounds[1] < centre_lat < bounds[3]
    assert not bounds[1] < north_lat < bounds[3]


def test_unzoned_1m_tile_names_need_a_zone():
    name = "USGS_one_meter_x62y333_TX_Central_B1_2017.tif"

    assert Usgs3depAws._parse_tile_bounds_from_filename(name) is None
    bounds = Usgs3depAws._parse_tile_bounds_from_filename(name, utm_zone=14)
    # Observed tile header: EPSG:26914, x 619994-630006, y 3319994-3330006.
    assert bounds[0] < -97.7 < bounds[2] and bounds[1] < 30.08 < bounds[3]


def test_download_tiles_reads_zone_once_and_honours_exclusions(monkeypatch, tmp_path):
    projects = gpd.GeoDataFrame(
        {"proj_name": ["TX_Central_B1_2017"]},
        geometry=[box(-98.0, 29.5, -97.0, 30.5)],
        crs="EPSG:4326",
    )
    urls = [
        "https://example.com/USGS_one_meter_x62y333_TX_Central_B1_2017.tif",
        "https://example.com/USGS_one_meter_x63y333_TX_Central_B1_2017.tif",
    ]
    zone_lookups = []

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(Usgs3depAws, "_get_project_tile_urls", staticmethod(lambda name: urls))
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_tile_utm_zone",
        staticmethod(lambda url: zone_lookups.append(url) or 14),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_tile_bounds_wgs84",
        staticmethod(lambda url: pytest.fail("slow /vsicurl/ fallback must not be used")),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_download_single_tile",
        staticmethod(lambda tile_url, output_folder, overwrite_dest: Path(output_folder) / tile_url.rsplit("/", 1)[-1]),
    )

    result = Usgs3depAws.download_tiles(
        (-97.8, 29.9, -97.5, 30.2),
        1,
        tmp_path,
        max_workers=1,
        exclude_tile_ids=["USGS_one_meter_x63y333_TX_Central_B1_2017"],
    )

    assert [path.name for path in result] == ["USGS_one_meter_x62y333_TX_Central_B1_2017.tif"]
    assert len(zone_lookups) == 1
