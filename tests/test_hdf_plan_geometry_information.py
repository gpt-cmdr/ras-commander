from datetime import datetime

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfPlan


@pytest.mark.parametrize("as_string", [False, True])
@pytest.mark.parametrize("include_units", [False, True])
def test_get_geometry_information_preserves_converted_datetime(tmp_path, as_string, include_units):
    geom_hdf = tmp_path / "Example.g01.hdf"
    with h5py.File(geom_hdf, "w") as hdf_file:
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Creation Date"] = np.bytes_("21Aug2026 06:00:00")
        if include_units:
            geometry.attrs["Units"] = np.bytes_("US Customary")

    information = HdfPlan.get_geometry_information(str(geom_hdf) if as_string else geom_hdf)

    assert information.columns.tolist() == ["Value"]
    assert information["Value"].dtype == object
    assert type(information.loc["Creation Date", "Value"]) is datetime
    assert information.loc["Creation Date", "Value"] == datetime(
        2026, 8, 21, 6, 0, 0
    )
    if include_units:
        assert information.loc["Units", "Value"] == "US Customary"
