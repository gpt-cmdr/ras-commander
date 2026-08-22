"""Run one real HEC-DSS grid bridge scenario in a clean Python process."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ras_commander import RasDss


def _run_shg_round_trip(
    output_dir: Path,
    autoclass: Callable[[str], Any],
    cast: Callable[[str, Any], Any],
) -> None:
    dss_file = output_dir / "synthetic_grid.dss"
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

    result = RasDss.read_grid(dss_file, written[2])

    assert result["dss_file"] == str(dss_file.resolve())
    assert result["pathname"] == written[2]
    assert result["shape"] == (10, 10)
    assert result["data"].dtype == np.float32
    assert np.allclose(result["data"], data[2])
    assert result["units"] == "mm"
    assert result["data_type"] == "PER-CUM"
    assert result["grid_type"] == "albers"
    assert "Albers_Equal_Area" in result["crs"]
    assert result["cell_size"] == 2000.0
    assert result["start_time"] == pd.Timestamp("2020-01-01 02:00")
    assert result["end_time"] == pd.Timestamp("2020-01-01 03:00")

    metadata = result["metadata"]
    assert metadata["grid_class"] == "hec.heclib.grid.AlbersInfo"
    assert metadata["pathname_parts"] == {
        "A": "SHG",
        "B": "TEST",
        "C": "PRECIP",
        "D": "01JAN2020:0200",
        "E": "01JAN2020:0300",
        "F": "RC_TEST",
    }
    assert metadata["grid_type_code"] == 420
    assert metadata["data_type_code"] == 1
    assert metadata["shape"] == (10, 10)
    assert metadata["lower_left_cell"] == (548, 758)
    assert metadata["origin"] == (1096000.0, 1516000.0)
    assert metadata["number_missing"] == 0
    assert metadata["projection"]["units"] == "Meter"
    assert metadata["projection"]["central_meridian"] == -96.0
    assert metadata["timing"]["period"] == (
        "1 January 2020, 02:00 to 1 January 2020, 03:00"
    )

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


def _run_specified_grid_round_trip(
    output_dir: Path,
    _autoclass: Callable[[str], Any],
    _cast: Callable[[str, Any], Any],
) -> None:
    dss_file = output_dir / "specified_grid.dss"
    data = np.array([[[1.25, np.nan], [3.5, 4.75]]], dtype=np.float32)
    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname="/SPECIFIED/TEST/PRECIP/01JUN2024:1200/01JUN2024:1230/RC_TEST/",
        data=data,
        times=[datetime(2024, 6, 1, 12, 30)],
        grid_info={
            "cellsize": 0.01,
            "origin": (-95.5, 29.5),
            "x_coord_cell_zero": -180.0,
            "y_coord_cell_zero": -90.0,
            "crs": "EPSG:4326",
            "crs_name": "WGS 84",
            "units": "INCHES",
            "data_type": "PER-CUM",
            "interval_minutes": 30,
            "compression": "ZLIB",
        },
    )

    result = RasDss.read_grid(str(dss_file), written[0])

    assert result["pathname"] == written[0]
    assert result["grid_type"] == "specified"
    assert result["crs"] == "EPSG:4326"
    assert result["cell_size"] == pytest.approx(0.01)
    assert result["start_time"] == pd.Timestamp("2024-06-01 12:00")
    assert result["end_time"] == pd.Timestamp("2024-06-01 12:30")
    np.testing.assert_allclose(result["data"], data[0], equal_nan=True)

    metadata = result["metadata"]
    assert metadata["grid_class"] == "hec.heclib.grid.SpecifiedGridInfo"
    assert metadata["number_missing"] == 1
    assert metadata["projection"]["x_coord_cell_zero"] == -180.0
    assert metadata["projection"]["y_coord_cell_zero"] == -90.0
    assert metadata["origin"] == pytest.approx((-95.5, 29.5))


def _run_exact_path_error(
    output_dir: Path,
    _autoclass: Callable[[str], Any],
    _cast: Callable[[str, Any], Any],
) -> None:
    dss_file = output_dir / "exact_path.dss"
    pathname = "/BASIN/LOCATION/PRECIP/01JAN2020:0000/01JAN2020:0100/TEST/"
    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname=pathname,
        data=np.ones((1, 1, 1), dtype=np.float32),
        times=[datetime(2020, 1, 1, 1)],
        grid_info={"cellsize": 2000, "crs": "SHG"},
    )

    with pytest.raises(ValueError, match="exact pathname"):
        RasDss.read_grid(dss_file, written[0].replace("PRECIP", "TEMPERATURE"))


SCENARIOS = {
    "shg_round_trip": _run_shg_round_trip,
    "specified_grid_round_trip": _run_specified_grid_round_trip,
    "exact_path_error": _run_exact_path_error,
}


def main() -> int:
    scenario_name = sys.argv[1]
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        RasDss._configure_jvm()
        from jnius import autoclass, cast
    except (ImportError, RuntimeError) as exc:
        print(f"C03C_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        return 77

    SCENARIOS[scenario_name](output_dir, autoclass, cast)
    print(f"C03C_SCENARIO_OK:{scenario_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
