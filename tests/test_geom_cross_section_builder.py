import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander.geom.GeomCrossSection import (
    CrossSectionBankStations,
    CrossSectionManningsN,
    CrossSectionReachLengths,
    GeomCrossSection,
)


RIVER = "Builder River"
REACH = "Builder Reach"


def _profile(stations=(0.0, 50.0, 100.0), elevations=(10.0, 0.0, 10.0)):
    return pd.DataFrame({"Station": stations, "Elevation": elevations})


def _write_entry(tmp_path: Path, entry_text: str) -> Path:
    geom_file = tmp_path / "builder.g01"
    geom_file.write_text(
        "Geom Title=Builder Test\n"
        "Program Version=6.50\n"
        f"River Reach={RIVER}    ,{REACH}\n"
        "Reach XY= 2\n"
        "            0.00            0.00\n"
        "          100.00            0.00\n"
        f"{entry_text}",
        encoding="utf-8",
    )
    return geom_file


def test_build_cross_section_from_cut_line_and_terrain_uses_auto_fallbacks(caplog, tmp_path):
    shapely_geometry = pytest.importorskip("shapely.geometry")
    cut_line = shapely_geometry.LineString([(0.0, 0.0), (100.0, 0.0)])
    river_centerline = shapely_geometry.LineString([(50.0, -25.0), (50.0, 25.0)])

    with caplog.at_level(logging.ERROR):
        result = GeomCrossSection.build_cross_section(
            river=RIVER,
            reach=REACH,
            rs="1000",
            cut_line=cut_line,
            river_centerline=river_centerline,
            terrain_profile=_profile(),
        )

    assert np.isclose(result.bank_stations.left_station, 40.0)
    assert np.isclose(result.bank_stations.right_station, 60.0)
    assert np.isclose(result.bank_stations.left_elevation, 2.0)
    assert np.isclose(result.bank_stations.right_elevation, 2.0)
    assert np.allclose(result.mannings_n["n_value"], [0.08, 0.06, 0.08])
    assert "#Mann= 3 , 0 , 0" in result.text
    assert "XS GIS Cut Line= 2" in result.text

    messages = "\n".join(record.message for record in caplog.records)
    assert "MC width 20" in messages
    assert "default fallback MC=0.06, LOB=ROB=0.08" in messages

    geom_file = _write_entry(tmp_path, result.text)
    assert GeomCrossSection.get_bank_stations(geom_file, RIVER, REACH, "1000") == (40.0, 60.0)
    assert len(GeomCrossSection.get_station_elevation(geom_file, RIVER, REACH, "1000")) == 5
    mannings = GeomCrossSection.get_mannings_n(geom_file, RIVER, REACH, "1000")
    assert np.allclose(mannings["n_value"], [0.08, 0.06, 0.08])


def test_build_cross_section_fully_specified_inputs_emit_no_fallback_logs(caplog, tmp_path):
    with caplog.at_level(logging.ERROR):
        result = GeomCrossSection.build_cross_section(
            river=RIVER,
            reach=REACH,
            rs="1100",
            station_elevation=_profile(),
            bank_stations=CrossSectionBankStations(25.0, 75.0, 5.0, 5.0),
            mannings_n=CrossSectionManningsN(0.04, 0.035, 0.045),
            reach_lengths=CrossSectionReachLengths(100.0, 110.0, 120.0),
            include_gis_cut_line=False,
        )

    assert result.fallback_messages == []
    assert not caplog.records
    assert {25.0, 75.0}.issubset(set(result.station_elevation["Station"]))
    assert np.isclose(
        result.station_elevation.loc[result.station_elevation["Station"].eq(25.0), "Elevation"].iloc[0],
        5.0,
    )
    assert np.allclose(result.mannings_n["n_value"], [0.04, 0.035, 0.045])

    geom_file = _write_entry(tmp_path, result.text)
    station_elevation = GeomCrossSection.get_station_elevation(geom_file, RIVER, REACH, "1100")
    assert len(station_elevation) == 5
    assert np.isclose(station_elevation["Elevation"].min(), 0.0)


def test_bank_station_fallbacks_use_terrain_then_profile(caplog):
    terrain_result = GeomCrossSection.build_cross_section(
        river=RIVER,
        reach=REACH,
        rs="1200",
        station_elevation=_profile(),
        terrain_profile=_profile(),
        bank_stations=(20.0, 80.0),
        mannings_n=(0.04, 0.05, 0.06),
        reach_lengths=(1.0, 1.0, 1.0),
        include_gis_cut_line=False,
    )
    assert np.isclose(terrain_result.bank_stations.left_elevation, 6.0)
    assert np.isclose(terrain_result.bank_stations.right_elevation, 6.0)
    assert any("interpolated LOB/ROB elevations from terrain profile" in msg for msg in terrain_result.fallback_messages)

    caplog.clear()
    with caplog.at_level(logging.ERROR):
        profile_result = GeomCrossSection.build_cross_section(
            river=RIVER,
            reach=REACH,
            rs="1300",
            station_elevation=_profile(),
            bank_stations=(20.0, 80.0),
            mannings_n=(0.04, 0.05, 0.06),
            reach_lengths=(1.0, 1.0, 1.0),
            include_gis_cut_line=False,
        )

    assert np.isclose(profile_result.bank_stations.left_elevation, 6.0)
    assert "terrain unavailable for bank elevations" in "\n".join(
        record.message for record in caplog.records
    )


def test_build_cross_section_without_terrain_interpolates_adjacent_profiles(caplog):
    upstream = _profile(elevations=(12.0, 2.0, 12.0))
    downstream = _profile(elevations=(8.0, -2.0, 8.0))

    with caplog.at_level(logging.ERROR):
        result = GeomCrossSection.build_cross_section(
            river=RIVER,
            reach=REACH,
            rs="1400",
            upstream_profile=upstream,
            downstream_profile=downstream,
            interpolation_ratio=0.5,
            include_gis_cut_line=False,
        )

    assert len(result.station_elevation) >= 5
    assert result.bank_stations.left_station < result.bank_stations.right_station
    assert np.allclose(result.mannings_n["n_value"], [0.08, 0.06, 0.08])
    messages = "\n".join(record.message for record in caplog.records)
    assert "interpolated profile from adjacent cross sections" in messages
    assert "using thalweg station" in messages
    assert "terrain unavailable for bank elevations" in messages


def test_mannings_n_landcover_neighbor_user_and_default_strategies():
    table = pd.DataFrame({
        "Land Cover Name": ["woods", "channel", "grass"],
        "Base Mannings n Value": [0.11, 0.045, 0.07],
    })
    base_kwargs = dict(
        river=RIVER,
        reach=REACH,
        station_elevation=_profile(),
        bank_stations=CrossSectionBankStations(25.0, 75.0, 5.0, 5.0),
        reach_lengths=(1.0, 1.0, 1.0),
        include_gis_cut_line=False,
    )

    landcover = GeomCrossSection.build_cross_section(
        **base_kwargs,
        rs="1500",
        landcover_samples={"LOB": "woods", "Channel": "channel", "ROB": "grass"},
        landcover_table=table,
    )
    assert np.allclose(landcover.mannings_n["n_value"], [0.11, 0.045, 0.07])

    neighbor = GeomCrossSection.build_cross_section(
        **base_kwargs,
        rs="1600",
        mannings_strategy="neighbor",
        upstream_mannings=(0.08, 0.04, 0.09),
        downstream_mannings=(0.10, 0.06, 0.11),
        interpolation_ratio=0.25,
    )
    assert np.allclose(neighbor.mannings_n["n_value"], [0.085, 0.045, 0.095])

    user = GeomCrossSection.build_cross_section(
        **base_kwargs,
        rs="1700",
        mannings_strategy="user",
        mannings_n=(0.04, 0.035, 0.05),
    )
    assert np.allclose(user.mannings_n["n_value"], [0.04, 0.035, 0.05])

    default = GeomCrossSection.build_cross_section(**base_kwargs, rs="1800")
    assert np.allclose(default.mannings_n["n_value"], [0.08, 0.06, 0.08])
    assert any("Manning's n data missing" in msg for msg in default.fallback_messages)


def test_point_reduction_preserves_banks_thalweg_and_slope_breaks():
    stations = np.linspace(0.0, 1000.0, 601)
    elevations = np.piecewise(
        stations,
        [stations < 250.0, (stations >= 250.0) & (stations < 500.0), stations >= 500.0],
        [
            lambda sta: 100.0 - 0.02 * sta,
            lambda sta: 95.0 - 0.18 * (sta - 250.0),
            lambda sta: 50.0 + 0.10 * (sta - 500.0),
        ],
    )
    dense_profile = pd.DataFrame({"Station": stations, "Elevation": elevations})

    result = GeomCrossSection.build_cross_section(
        river=RIVER,
        reach=REACH,
        rs="1900",
        station_elevation=dense_profile,
        bank_stations=CrossSectionBankStations(100.0, 900.0, 98.0, 90.0),
        mannings_n=(0.04, 0.05, 0.06),
        reach_lengths=(1.0, 1.0, 1.0),
        max_points=25,
        include_gis_cut_line=False,
    )

    kept_stations = set(np.round(result.station_elevation["Station"], 6))
    assert len(result.station_elevation) <= 25
    assert {100.0, 900.0, 500.0}.issubset(kept_stations)
    assert any(np.isclose(result.station_elevation["Station"], 250.0))
