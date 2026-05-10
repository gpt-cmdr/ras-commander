from pathlib import Path

import numpy as np
import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("geopandas")
from rasterio.transform import from_origin
from shapely.geometry import box

from ras_commander.geom import GeomCrossSection, ManningsFromLandCover


def _format_values(values):
    return "".join(f"{value:8.2f}" for value in values)


def _format_xy(coords):
    values = []
    for x, y in coords:
        values.extend([x, y])
    return "".join(f"{value:16.2f}" for value in values)


def _xs_block(
    rs: str,
    y: float,
    station_max: float,
    banks=(4.0, 6.0),
    river_x0: float = 0.0,
) -> str:
    return (
        f"Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0\n"
        "Node Last Edited Time=Jan/01/2026 00:00:00\n"
        f"Bank Sta={banks[0]},{banks[1]}\n"
        "XS GIS Cut Line=2\n"
        f"{_format_xy([(river_x0, y), (river_x0 + station_max, y)])}\n"
        "#Sta/Elev= 3\n"
        f"{_format_values([0.0, 100.0, station_max / 2.0, 90.0, station_max, 100.0])}\n"
        "#Mann= 1 , 0 , 0\n"
        f"{0.0:8.2f}{0.040:8.3f}{0.0:8.0f}\n"
    )


def _write_geom(tmp_path: Path, multi_reach=False, station_max=9.0, banks=(4.0, 6.0)) -> Path:
    text = (
        "Geom Title=Manning Land Cover Test\n"
        "Program Version=6.60\n"
        "River Reach=TestRiver    ,ReachA\n"
        "Reach XY= 2\n"
        f"{_format_xy([(0.0, 5.0), (100.0, 5.0)])}\n"
        + _xs_block("1000", 5.0, station_max, banks=banks)
    )
    if multi_reach:
        text += (
            "River Reach=TestRiver    ,ReachB\n"
            "Reach XY= 2\n"
            f"{_format_xy([(0.0, 15.0), (100.0, 15.0)])}\n"
            + _xs_block("2000", 15.0, station_max, banks=banks)
        )

    geom_file = tmp_path / "landcover.g01"
    geom_file.write_text(text, encoding="utf-8")
    return geom_file


def _write_raster(tmp_path: Path, data: np.ndarray) -> Path:
    path = tmp_path / "nlcd.tif"
    height, width = data.shape
    transform = from_origin(0.0, float(height), 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype=data.dtype,
        crs="EPSG:3857",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)
    return path


def test_assign_single_reach_writes_nlcd_blocks_and_preserves_three_decimals(tmp_path):
    geom_file = _write_geom(tmp_path)
    raster = _write_raster(
        tmp_path,
        np.tile(np.array([11, 11, 11, 11, 11, 71, 71, 71, 71, 71], dtype=np.uint8), (10, 1)),
    )

    result = ManningsFromLandCover.assign(geom_file, raster)

    assert result["cross_sections_processed"] == 1
    mannings = GeomCrossSection.get_mannings_n(geom_file, "TestRiver", "ReachA", "1000")
    assert len(mannings) >= 2
    assert np.isclose(mannings.iloc[0]["n_value"], 0.025)
    assert np.isclose(mannings["n_value"].max(), 0.040)
    assert mannings.iloc[0]["Station"] == 0.0


def test_assign_processes_multiple_reaches(tmp_path):
    geom_file = _write_geom(tmp_path, multi_reach=True)
    raster = _write_raster(
        tmp_path,
        np.tile(np.array([11, 11, 11, 11, 11, 71, 71, 71, 71, 71], dtype=np.uint8), (20, 1)),
    )

    result = ManningsFromLandCover.assign(geom_file, raster)

    assert result["cross_sections_processed"] == 2
    reach_a = GeomCrossSection.get_mannings_n(geom_file, "TestRiver", "ReachA", "1000")
    reach_b = GeomCrossSection.get_mannings_n(geom_file, "TestRiver", "ReachB", "2000")
    assert len(reach_a) >= 2
    assert len(reach_b) >= 2
    assert np.isclose(reach_a.iloc[0]["n_value"], 0.025)
    assert np.isclose(reach_b.iloc[0]["n_value"], 0.025)


def test_preview_enforces_block_limit_without_cross_channel_merges(tmp_path):
    geom_file = _write_geom(tmp_path, station_max=29.0, banks=(10.0, 20.0))
    alternating = np.array([11, 71] * 15, dtype=np.uint8)
    raster = _write_raster(tmp_path, np.tile(alternating, (10, 1)))

    preview = ManningsFromLandCover.preview(geom_file, raster, max_blocks=6)

    assert len(preview) <= 6
    assert preview["raw_block_count"].iloc[0] > 6
    lob = preview[preview["Subsection"] == "LOB"]
    rob = preview[preview["Subsection"] == "ROB"]
    assert (lob["EndStation"] <= 10.0).all()
    assert (rob["Station"] >= 20.0).all()


def test_geometry_calibration_region_overrides_land_cover_region(tmp_path):
    geom_file = _write_geom(tmp_path)
    raster = _write_raster(tmp_path, np.full((10, 10), 71, dtype=np.uint8))
    land_cover_region = pd.DataFrame([
        {
            "geometry": box(5.0, 4.0, 10.0, 6.0),
            "n_value": 0.080,
            "source": "land_cover",
        }
    ])
    geometry_region = pd.DataFrame([
        {
            "geometry": box(5.0, 4.0, 10.0, 6.0),
            "n_value": 0.120,
            "source": "geometry",
        }
    ])

    preview = ManningsFromLandCover.preview(
        geom_file,
        raster,
        calibration_regions={
            "land_cover": land_cover_region,
            "geometry": geometry_region,
        },
    )

    assert np.isclose(preview.iloc[0]["n_value"], 0.040)
    assert np.isclose(preview.iloc[-1]["n_value"], 0.120)
    assert "geometry:" in preview.iloc[-1]["sources"]
