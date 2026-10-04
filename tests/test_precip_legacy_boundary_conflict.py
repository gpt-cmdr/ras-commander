"""Regression for the conflicting rainfall sources observed in official Davis 6.6."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from ras_commander import RasUnsteady


@pytest.mark.parametrize("route", ["netcdf", "dss"])
def test_gridded_precipitation_rejects_legacy_area_rain_before_mutation(tmp_path, route):
    # Exact boundary layout and rainfall values from the official Davis u01.
    content = (
        "Flow Title=Full System Rain w/ Pump\r\nProgram Version=6.60\r\n"
        "Boundary Location=                ,                ,        ,        ,"
        "                ,area2           ,                ,                                ,\r\n"
        "Interval=1HOUR\r\nPrecipitation Hydrograph= 3 \r\n"
        "      .1      .1      .1\r\nUse DSS=False\r\n"
        "Met Point Raster Parameters=,,,,\r\nPrecipitation Mode=Disable\r\n"
    ).encode("ascii")
    unsteady = tmp_path / "DavisStormSystem.u01"
    unsteady.write_bytes(content)
    sidecar = unsteady.with_suffix(".u01.hdf")
    sidecar.write_bytes(b"existing sidecar must not be opened or replaced")
    existing_hdf = sidecar.read_bytes()
    ras = SimpleNamespace(check_initialized=lambda: None, project_folder=tmp_path,
                          project_name="DavisStormSystem")
    with pytest.raises(ValueError, match="legacy Precipitation Hydrograph.*area2.*stage_project"):
        if route == "netcdf":
            RasUnsteady.set_gridded_precipitation(
                unsteady, tmp_path / "rain.nc", ras_object=ras)
        else:
            RasUnsteady.configure_gridded_dss_precipitation(
                unsteady, tmp_path / "rain.dss", "/SHG/QA/PRECIP///QA/")
    assert unsteady.read_bytes() == content
    assert sidecar.read_bytes() == existing_hdf
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "DavisStormSystem.u01", "DavisStormSystem.u01.hdf"]


def test_gridded_precipitation_allows_nonprecipitation_boundary(tmp_path):
    unsteady = tmp_path / "Model.u01"
    unsteady.write_text(
        "Flow Title=Normal Depth\nProgram Version=6.60\n"
        "Boundary Location=,,,,,DS Channel,,DS Normal,\nFriction Slope=0.003,0\n")
    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady, "rain.dss", "/SHG/QA/PRECIP///QA/")
    assert RasUnsteady.get_met_precipitation_config(unsteady)["mode"] == "Gridded"
