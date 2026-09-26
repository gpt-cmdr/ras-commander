"""Opt-in RasExamples regression for AORC's first hourly accumulation."""
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pyproj import CRS

from ras_commander import RasExamples, init_ras_project
from ras_commander.precip import PrecipAorc


@pytest.mark.integration
def test_aorc_storm_plan_preserves_first_hour_on_rasexamples(tmp_path):
    if os.environ.get("RUN_RAS_PRECIP_QUALIFICATION") != "1":
        pytest.skip("set RUN_RAS_PRECIP_QUALIFICATION=1 to extract RasExamples")
    RasExamples.get_example_projects("6.6")
    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path)
    ras = init_ras_project(project, "6.6", load_results_summary=False, hide_intro=True)
    folder = Path(ras.project_folder) / "Precipitation"
    folder.mkdir(exist_ok=True)
    # Controlled interval amounts on a real project isolate the temporal contract
    # from live NOAA availability. Both intervals are nonzero and asymmetric.
    amounts = np.array([[[1, 2], [3, 4]], [[2, 3], [4, 5]]], dtype=np.float32)
    wkt = CRS.from_epsg(5070).to_wkt()
    ds = xr.Dataset(
        {"APCP_surface": (("time", "y", "x"), amounts,
                          {"units": "kg/m^2", "grid_mapping": "spatial_ref"}),
         "spatial_ref": ((), 0, {"spatial_ref": wkt, "crs_wkt": wkt})},
        coords={"time": pd.to_datetime(["2024-08-09 11:00", "2024-08-09 12:00"]),
                "x": [500, 1500], "y": [1500, 500]},
    )
    ds.to_netcdf(folder / "storm_20240809.nc", engine="scipy")
    catalog = pd.DataFrame([dict(storm_id=1, start_time=pd.Timestamp("2024-08-09 11:00"),
                                sim_start=pd.Timestamp("2024-08-09 10:00"),
                                sim_end=pd.Timestamp("2024-08-09 13:00"), total_depth_in=1.0)])
    result = PrecipAorc.create_storm_plans(
        catalog, bounds=(-77.71, 41.01, -77.25, 41.22), template_plan="06",
        ras_object=ras, download_data=False,
    )
    assert result.iloc[0]["status"] == "success", result.to_dict()
    number = result.iloc[0]["unsteady_number"]
    with h5py.File(Path(ras.project_folder) / f"{ras.project_name}.u{number}.hdf") as hdf:
        data = hdf["Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values"][:]
    assert data.shape == (3, 4)
    np.testing.assert_allclose(data[0], 0)
    np.testing.assert_allclose(np.sort(data[1]), np.sort(amounts[0].ravel()))
    np.testing.assert_allclose(np.sort(data[2]), np.sort(amounts.sum(axis=0).ravel()))
