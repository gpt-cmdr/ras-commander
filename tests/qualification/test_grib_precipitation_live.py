"""Opt-in real-GRIB qualification using NOAA's filtered HRRR service."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest
import requests

from ras_commander import RasUnsteady
from ras_commander.precip import PrecipHrrr, RasPrecipGrid


pytestmark = [pytest.mark.integration, pytest.mark.qualification_critical]


def test_real_projected_hrrr_grib2_normalizes_and_authors_native_hdf(tmp_path):
    if os.environ.get("RUN_LIVE_GRIB_QUALIFICATION") != "1":
        pytest.skip("set RUN_LIVE_GRIB_QUALIFICATION=1 for live NOAA GRIB test")

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cycle_time = None
    for lookback in range(2, 9):
        candidate = now - timedelta(hours=lookback)
        if PrecipHrrr.check_availability(candidate.strftime("%Y-%m-%d"), candidate.hour):
            cycle_time = candidate
            break
    if cycle_time is None:
        pytest.skip("No recent HRRR cycle is currently available")

    date_key = cycle_time.strftime("%Y%m%d")
    filename = f"hrrr.t{cycle_time.hour:02d}z.wrfsfcf06.grib2"
    response = requests.get(
        "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl",
        params={
            "file": filename,
            "lev_surface": "on",
            "var_APCP": "on",
            "subregion": "",
            "leftlon": "-100.0",
            "rightlon": "-75.0",
            "toplat": "45.0",
            "bottomlat": "30.0",
            "dir": f"/hrrr.{date_key}/conus",
        },
        timeout=120,
    )
    response.raise_for_status()
    assert response.content.startswith(b"GRIB")
    source = tmp_path / filename
    source.write_bytes(response.content)

    valid_time = cycle_time.replace(tzinfo=None) + timedelta(hours=6)
    cube = RasPrecipGrid.from_grib(
        source,
        timestamps=[valid_time],
        units="mm",
        value_type="amount",
        first_timestep_hours=6.0,
        bands=[1],
    )

    assert cube.values.ndim == 3
    assert cube.values.shape[0] == 2
    assert cube.values.shape[1] > 1 and cube.values.shape[2] > 1
    assert np.all(np.isfinite(cube.values))
    assert float(np.nanmin(cube.values)) >= 0.0
    assert float(np.nanmax(cube.values)) > 0.0
    assert "PROJCS" in cube.crs_wkt or "PROJCRS" in cube.crs_wkt

    unsteady = tmp_path / "LiveHrrr.u01"
    unsteady.write_text(
        "Flow Title=Live HRRR GRIB qualification\nProgram Version=6.60\n",
        encoding="ascii",
    )
    project = SimpleNamespace(
        project_folder=tmp_path,
        project_name="LiveHrrr",
        ras_version="6.6",
        check_initialized=lambda: None,
    )
    result = RasUnsteady.set_gridded_precipitation_grib(
        unsteady,
        source,
        timestamps=[valid_time],
        units="mm",
        value_type="amount",
        first_timestep_hours=6.0,
        bands=[1],
        ratio=1.0,
        ras_object=project,
    )
    assert result.source_format == "grib"
    assert result.route_qualification == "documented"
    assert result.cache_path.is_file()
    with h5py.File(Path(str(unsteady) + ".hdf"), "r") as hdf:
        imported = hdf[
            "Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values"
        ][...]
    assert float(np.nanmax(imported)) > 0.0

