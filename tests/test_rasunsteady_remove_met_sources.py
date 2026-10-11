from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import RasUnsteady


def test_boundary_only_child_removes_met_dss_and_keeps_boundary_and_infiltration(
    tmp_path,
):
    flow = tmp_path / "child.u02"
    flow.write_bytes(
        b"Flow Title=Child\r\nProgram Version=6.60\r\n"
        b"Boundary Location=,,,,,Area,,Inlet,\r\n"
        b"DSS File=boundary.dss\r\nDSS Path=/A/B/FLOW//1HOUR/F/\r\n"
        b"Use DSS=True\r\nInfiltration=Keep\r\n"
        b"Met Station Name=Parent gage\r\nMet Station XY=10,20\r\n"
        b"Met Point Raster Parameters=1,2,3\r\nPrecipitation Mode=Enable\r\n"
        b"Met BC=Precipitation|Mode=Gridded\r\n"
        b"Met BC=Precipitation|Gridded DSS Filename=parent.dss\r\n"
        b"Met BC=Precipitation|Point Time Series=parent-point.dss\r\n"
        b"Met BC=Evapotranspiration|Gridded DSS Filename=parent-et.dss\r\n"
        b"Met BC=Wind Speed|Point Time Series=parent-wind.dss\r\n"
        b"Met BC=Precipitation|Expanded View=0\r\n"
    )
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w") as hdf:
        met = hdf.create_group("Event Conditions/Meteorology")
        rain = met.create_group("Precipitation")
        rain.attrs["DSS Filename"] = np.bytes_("parent.dss")
        rain.create_dataset("Values", data=[1, 2])
        hdf.create_dataset("Event Conditions/Boundary/Values", data=[3, 4])
        hdf.create_dataset("Geometry/Infiltration/Values", data=[5, 6])
    evidence = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    raw = flow.read_bytes()
    assert b"parent" not in raw.lower()
    assert b"Met Station" not in raw
    assert b"Precipitation Mode=Disable\r\n" in raw
    assert b"Met BC=Precipitation|Mode=None\r\n" in raw
    assert b"DSS File=boundary.dss\r\n" in raw
    assert b"Infiltration=Keep\r\n" in raw
    assert b"Met BC=Precipitation|Expanded View=0\r\n" in raw
    assert evidence["source_references_removed"] is True
    with h5py.File(sidecar, "r") as hdf:
        met = hdf["Event Conditions/Meteorology"]
        assert all(int(g.attrs["Enabled"]) == 0 and not len(g) for g in met.values())
        assert list(hdf["Event Conditions/Boundary/Values"][:]) == [3, 4]
        assert list(hdf["Geometry/Infiltration/Values"][:]) == [5, 6]
    RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert flow.read_bytes() == raw


@pytest.mark.parametrize("prefix", ["Met Station=", "Meteorological Station="])
def test_legacy_station_trailer_is_not_a_boundary_record(tmp_path, prefix):
    flow = tmp_path / "child.u02"
    boundary = "Boundary Location=,,,,,Area,,Inlet,\nDSS File=boundary.dss\n"
    flow.write_text("Flow Title=Child\n" + boundary + prefix + "Gage,1,2,3,4,5\n")
    evidence = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert prefix not in flow.read_text()
    assert boundary in flow.read_text()
    assert evidence["boundary_conditions_unchanged"]
