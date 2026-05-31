"""Integration tests for HEC-DSS grid writing through RasDss."""

from datetime import datetime

import numpy as np
import pytest


pytestmark = pytest.mark.integration


def _configure_dss_or_skip():
    from ras_commander import RasDss

    try:
        RasDss._configure_jvm()
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"HEC Monolith/pyjnius unavailable: {exc}")
    return RasDss


def test_write_grid_timeseries_round_trips_synthetic_shg_grid(tmp_path):
    RasDss = _configure_dss_or_skip()

    dss_file = tmp_path / "synthetic_grid.dss"
    data = np.arange(5 * 10 * 10, dtype=np.float32).reshape(5, 10, 10)
    times = [datetime(2020, 1, 1, hour) for hour in range(1, 6)]

    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname="/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/RC_TEST/",
        data=data,
        times=times,
        grid_info={
            "cellsize": 2000,
            "origin": (1096000, 1516000),
            "crs": "SHG",
            "units": "mm",
            "data_type": "PER-CUM",
        },
    )

    assert written == [
        "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0100/01JAN2020:0200/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0200/01JAN2020:0300/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0300/01JAN2020:0400/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0400/01JAN2020:0500/RC_TEST/",
    ]

    catalog = RasDss.get_catalog(dss_file)
    assert sorted(catalog["pathname"].tolist()) == sorted(written)

    from jnius import autoclass, cast

    HecDss = autoclass("hec.heclib.dss.HecDss")
    dss = HecDss.open(str(dss_file))
    try:
        container = cast("hec.io.GridContainer", dss.get(written[2]))
        grid_data = container.getGridData()
        grid_info = cast("hec.heclib.grid.AlbersInfo", grid_data.getGridInfo())
        values = np.asarray(grid_data.getData(), dtype=np.float32)
    finally:
        dss.done()

    assert grid_info.getNumberOfCellsX() == 10
    assert grid_info.getNumberOfCellsY() == 10
    assert grid_info.getLowerLeftCellX() == 548
    assert grid_info.getLowerLeftCellY() == 758
    assert grid_info.getCellSize() == 2000
    assert grid_info.getDataUnits() == "mm"
    assert grid_info.getDataTypeName() == "PER-CUM"
    assert grid_info.getGridType() == 420
    assert np.allclose(values, data[2].ravel())
