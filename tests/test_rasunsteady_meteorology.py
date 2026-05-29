"""Tests for RasUnsteady meteorological station and point ET authoring.

Uses real HEC-RAS example projects via RasExamples to validate
round-trip read/write of meteorological station metadata and
point evapotranspiration time series in unsteady flow files.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasExamples, RasUnsteady, init_ras_project


@pytest.fixture(scope="module", autouse=True)
def _load_examples():
    RasExamples.get_example_projects()


@pytest.fixture
def muncie_unsteady(tmp_path):
    """Extract Muncie project and return path to its .u01 file."""
    proj = RasExamples.extract_project("Muncie", output_path=tmp_path, suffix="met")
    ras = init_ras_project(proj, "6.5")
    u_path = Path(ras.unsteady_df.iloc[0]["full_path"])
    return proj, ras, u_path


def test_set_and_get_meteorological_station_roundtrip(muncie_unsteady):
    """Write a met station to a real unsteady file and read it back."""
    proj, ras, u_path = muncie_unsteady

    RasUnsteady.set_meteorological_station(
        u_path,
        name="Gauge_A",
        x=528714.0,
        y=4482718.0,
        longitude=-85.38,
        latitude=40.19,
        height_m=285.0,
    )

    stations = RasUnsteady.get_meteorological_stations(u_path)
    assert len(stations) >= 1
    gauge = stations[stations["name"] == "Gauge_A"].iloc[0]
    assert gauge["x"] == pytest.approx(528714.0)
    assert gauge["y"] == pytest.approx(4482718.0)
    assert gauge["longitude"] == pytest.approx(-85.38)
    assert gauge["latitude"] == pytest.approx(40.19)
    assert gauge["height_m"] == pytest.approx(285.0)


def test_set_meteorological_station_updates_existing(muncie_unsteady):
    """Updating a station replaces it without duplication."""
    proj, ras, u_path = muncie_unsteady

    RasUnsteady.set_meteorological_station(u_path, name="StationX", x=1.0, y=2.0)
    RasUnsteady.set_meteorological_station(u_path, name="StationX", x=99.0, y=88.0)

    stations = RasUnsteady.get_meteorological_stations(u_path)
    matches = stations[stations["name"] == "StationX"]
    assert len(matches) == 1
    assert matches.iloc[0]["x"] == pytest.approx(99.0)
    assert matches.iloc[0]["y"] == pytest.approx(88.0)


def test_set_point_et_with_datetime_index(muncie_unsteady):
    """Write hourly ET from a DatetimeIndex DataFrame, read it back."""
    proj, ras, u_path = muncie_unsteady

    et_df = pd.DataFrame(
        {"evapotranspiration": [1.25, 1.30, 1.35, 1.40, 1.38]},
        index=pd.date_range("2018-01-01 06:00", periods=5, freq="h"),
    )

    RasUnsteady.set_point_evapotranspiration(
        u_path,
        station_name="ET_Gauge",
        et_df=et_df,
        units="mm/day",
        x=528714.0,
        y=4482718.0,
    )

    parsed = RasUnsteady.get_point_evapotranspiration(u_path)
    assert len(parsed) == 5
    assert parsed["station_name"].unique().tolist() == ["ET_Gauge"]
    assert parsed["hour"].tolist() == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0])
    assert parsed["value"].tolist() == pytest.approx([1.25, 1.30, 1.35, 1.40, 1.38])
    assert parsed["interval"].unique().tolist() == ["1HOUR"]
    assert parsed["units"].unique().tolist() == ["mm/day"]
    assert parsed["mode"].unique().tolist() == ["Point Gage"]
    assert parsed["datetime"].iloc[0] == pd.Timestamp("2018-01-01 06:00:00")


def test_set_point_et_with_hour_column(muncie_unsteady):
    """Write ET using an 'hour' column (no timestamps)."""
    proj, ras, u_path = muncie_unsteady

    et_df = pd.DataFrame({
        "hour": [0.0, 0.5, 1.0, 1.5],
        "pet": [0.10, 0.20, 0.30, 0.25],
    })

    RasUnsteady.set_point_evapotranspiration(
        u_path,
        station_name="HalfHour",
        et_df=et_df,
        x=528714.0,
        y=4482718.0,
    )

    parsed = RasUnsteady.get_point_evapotranspiration(u_path)
    half_hour = parsed[parsed["station_name"] == "HalfHour"]
    assert len(half_hour) == 4
    assert half_hour["interval"].unique().tolist() == ["30MIN"]
    assert half_hour["value"].tolist() == pytest.approx([0.10, 0.20, 0.30, 0.25])


def test_set_point_et_replaces_existing_series(muncie_unsteady):
    """Writing ET for the same station twice replaces without duplication."""
    proj, ras, u_path = muncie_unsteady

    first_df = pd.DataFrame({"hour": [0.0, 1.0, 2.0], "et": [0.10, 0.20, 0.30]})
    second_df = pd.DataFrame({"hour": [0.0, 0.5, 1.0], "et": [0.40, 0.50, 0.60]})

    RasUnsteady.set_point_evapotranspiration(u_path, "Replace", first_df, x=1.0, y=2.0)
    RasUnsteady.set_point_evapotranspiration(u_path, "Replace", second_df, x=1.0, y=2.0)

    content = u_path.read_text()
    assert content.count("Met BC=Evapotranspiration|Point Time Series=Replace") == 1

    parsed = RasUnsteady.get_point_evapotranspiration(u_path)
    replace_rows = parsed[parsed["station_name"] == "Replace"]
    assert len(replace_rows) == 3
    assert replace_rows["value"].tolist() == pytest.approx([0.40, 0.50, 0.60])
    assert replace_rows["interval"].unique().tolist() == ["30MIN"]


def test_set_point_et_preserves_existing_boundary_conditions(muncie_unsteady):
    """ET authoring does not corrupt existing flow hydrograph boundaries."""
    proj, ras, u_path = muncie_unsteady

    original_content = u_path.read_text()
    has_flow_hydrograph = "Flow Hydrograph" in original_content

    et_df = pd.DataFrame({"hour": [0.0, 1.0], "et": [0.12, 0.14]})
    RasUnsteady.set_point_evapotranspiration(
        u_path, station_name="SafeTest", et_df=et_df, x=1.0, y=2.0,
    )

    updated_content = u_path.read_text()
    if has_flow_hydrograph:
        assert "Flow Hydrograph" in updated_content


def test_get_meteorological_stations_empty_on_clean_file(muncie_unsteady):
    """A fresh Muncie unsteady file has no met stations by default."""
    proj, ras, u_path = muncie_unsteady

    # Read the original file before any modifications
    clean_path = u_path.parent / "Muncie_clean.u01"
    proj_u = RasExamples.extract_project("Muncie", output_path=u_path.parent, suffix="clean")
    clean_ras = init_ras_project(proj_u, "6.5")
    clean_u = clean_ras.unsteady_df.iloc[0]["full_path"]

    stations = RasUnsteady.get_meteorological_stations(clean_u)
    assert len(stations) == 0


def test_set_meteorological_station_via_short_number(muncie_unsteady):
    """Resolve unsteady file via short number '01' using ras_object."""
    proj, ras, u_path = muncie_unsteady

    RasUnsteady.set_meteorological_station(
        "01",
        name="ShortNum",
        x=100.0,
        y=200.0,
        ras_object=ras,
    )

    stations = RasUnsteady.get_meteorological_stations("01", ras_object=ras)
    matches = stations[stations["name"] == "ShortNum"]
    assert len(matches) == 1
    assert matches.iloc[0]["x"] == pytest.approx(100.0)
