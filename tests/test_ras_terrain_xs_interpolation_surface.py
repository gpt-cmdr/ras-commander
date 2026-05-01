from importlib import import_module

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString


ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
RasTerrain = ras_terrain_module.RasTerrain


def _fixed_width(values, width=8, per_line=10):
    lines = []
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        lines.append("".join(f"{value:>{width}.2f}" for value in chunk))
    return "\n".join(lines)


def _write_synthetic_geom(path):
    sta_elev = [
        0.0, 102.0,
        40.0, 90.0,
        50.0, 88.0,
        60.0, 90.0,
        100.0, 102.0,
    ]
    xs_specs = [
        ("300.0", 0.0),
        ("200.0", 50.0),
        ("100.0", 100.0),
    ]

    parts = [
        "Geom Title=XS Interpolation Test",
        "Program Version=6.60",
        "River Reach=Test River    ,Test Reach",
        "Reach XY= 2",
        f"{0.0:16.2f}{0.0:16.2f}{100.0:16.2f}{0.0:16.2f}",
    ]
    for rs, x_coord in xs_specs:
        parts.extend(
            [
                f"Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0",
                "Bank Sta=40,60",
                "XS GIS Cut Line= 2",
                f"{x_coord:16.2f}{-50.0:16.2f}{x_coord:16.2f}{50.0:16.2f}",
                "#Sta/Elev= 5",
                _fixed_width(sta_elev),
                "#Mann= 2 , 0 , 0",
                "     0   .04     0     0 100   .04     0     0",
            ]
        )

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def test_compute_xs_interpolation_surface_plain_geometry(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    geom_path = tmp_path / "Synthetic.g01"
    _write_synthetic_geom(geom_path)
    output_gpkg = tmp_path / "xs_surface.gpkg"
    output_raster = tmp_path / "xs_surface.tif"

    result = RasTerrain.compute_xs_interpolation_surface(
        geom_path,
        output_gpkg=output_gpkg,
        output_raster=output_raster,
        raster_cell_size=5.0,
        crs="EPSG:26915",
    )

    assert result["metadata"]["source_type"] == "plain_geometry"
    assert result["metadata"]["bank_line_source"] == "xs_bank_stations"
    assert result["metadata"]["footprint_source"] == "channel_banks"
    assert result["metadata"]["cross_section_count"] == 3
    assert result["metadata"]["interpolation_point_count"] == 9
    assert len(result["bank_lines"]) == 2
    assert not result["triangles"].empty
    assert not result["channel_polygon"].empty
    assert output_gpkg.exists()
    assert output_raster.exists()

    with rasterio.open(output_raster) as src:
        assert src.crs.to_string() == "EPSG:26915"
        array = src.read(1)
        valid = array[array != src.nodata]
        assert valid.size > 0
        assert float(valid.min()) >= 88.0
        assert float(valid.max()) <= 90.0


def test_compute_xs_interpolation_surface_full_xs_extents(tmp_path):
    geom_path = tmp_path / "Synthetic.g01"
    _write_synthetic_geom(geom_path)

    result = RasTerrain.compute_xs_interpolation_surface(
        geom_path,
        channel_only=False,
        crs="EPSG:26915",
    )

    assert result["metadata"]["footprint_source"] == "xs_extents"
    assert result["metadata"]["interpolation_point_count"] == 15
    assert not result["triangles"].empty
    assert result["channel_polygon"].geometry.iloc[0].area > 0


def test_compute_xs_interpolation_surface_hdf_path_uses_hdf_readers(monkeypatch, tmp_path):
    from ras_commander import hdf as hdf_pkg

    hdf_path = tmp_path / "Synthetic.g01.hdf"
    hdf_path.write_text("placeholder", encoding="utf-8")
    station_elevation = np.asarray(
        [
            [0.0, 102.0],
            [40.0, 90.0],
            [50.0, 88.0],
            [60.0, 90.0],
            [100.0, 102.0],
        ],
        dtype=float,
    )
    xs_gdf = gpd.GeoDataFrame(
        [
            {
                "River": "Test River",
                "Reach": "Test Reach",
                "RS": "300.0",
                "Left Bank": 40.0,
                "Right Bank": 60.0,
                "station_elevation": station_elevation,
                "geometry": LineString([(0.0, -50.0), (0.0, 50.0)]),
            },
            {
                "River": "Test River",
                "Reach": "Test Reach",
                "RS": "200.0",
                "Left Bank": 40.0,
                "Right Bank": 60.0,
                "station_elevation": station_elevation,
                "geometry": LineString([(50.0, -50.0), (50.0, 50.0)]),
            },
            {
                "River": "Test River",
                "Reach": "Test Reach",
                "RS": "100.0",
                "Left Bank": 40.0,
                "Right Bank": 60.0,
                "station_elevation": station_elevation,
                "geometry": LineString([(100.0, -50.0), (100.0, 50.0)]),
            },
        ],
        geometry="geometry",
    )
    centerlines_gdf = gpd.GeoDataFrame(
        [{"River Name": "Test River", "Reach Name": "Test Reach", "geometry": LineString([(0.0, 0.0), (100.0, 0.0)])}],
        geometry="geometry",
        crs="EPSG:26915",
    )
    empty_bank_lines = gpd.GeoDataFrame(
        columns=["bank_id", "bank_side", "geometry"],
        geometry="geometry",
        crs="EPSG:26915",
    )

    monkeypatch.setattr(
        hdf_pkg.HdfBase,
        "get_projection",
        staticmethod(lambda path: "EPSG:26915"),
    )
    monkeypatch.setattr(
        hdf_pkg.HdfXsec,
        "get_cross_sections",
        staticmethod(lambda path: xs_gdf),
    )
    monkeypatch.setattr(
        hdf_pkg.HdfXsec,
        "get_river_centerlines",
        staticmethod(lambda path: centerlines_gdf),
    )
    monkeypatch.setattr(
        hdf_pkg.HdfXsec,
        "get_river_bank_lines",
        staticmethod(lambda path: empty_bank_lines),
    )

    result = RasTerrain.compute_xs_interpolation_surface(hdf_path)

    assert result["metadata"]["source_type"] == "geometry_hdf"
    assert result["metadata"]["crs"] == "EPSG:26915"
    assert result["metadata"]["bank_line_source"] == "xs_bank_stations"
    assert result["metadata"]["interpolation_point_count"] == 9
    assert len(result["bank_lines"]) == 2
    assert not result["river_centerlines"].empty
