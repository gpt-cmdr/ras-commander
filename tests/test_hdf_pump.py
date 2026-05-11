from pathlib import Path

import h5py
import numpy as np

from ras_commander.hdf import HdfPump


def _write_pump_hdf(path: Path) -> None:
    data = np.array(
        [
            [0.0, -21.0, 1.0, 10.0, 1.0, 20.0, 2.0],
            [5.0, -20.5, 1.2, 12.0, 1.0, 25.0, 3.0],
        ],
        dtype=np.float32,
    )
    variable_units = np.array(
        [
            [b"Flow", b"cfs"],
            [b"Stage HW", b"ft"],
            [b"Stage TW", b"ft"],
            [b"V Pumps", b"cfs"],
            [b"V Pumps", b"Pumps on"],
            [b"G Pumps", b"cfs"],
            [b"G Pumps", b"Pumps on"],
        ],
        dtype="S32",
    )
    timestamps = np.array(
        [b"10APR2024 00:00:00:000", b"10APR2024 00:05:00:000"],
        dtype="S24",
    )

    with h5py.File(path, "w") as hdf:
        for output_block in ("DSS Hydrograph Output", "DSS Profile Output"):
            base = (
                "Results/Unsteady/Output/Output Blocks/"
                f"{output_block}/Unsteady Time Series"
            )
            base_group = hdf.require_group(base)
            base_group.create_dataset("Time Date Stamp (ms)", data=timestamps)
            station_group = base_group.require_group("Pumping Stations/17th St Pumps")
            dataset = station_group.create_dataset("Structure Variables", data=data)
            dataset.attrs["Variable_Unit"] = variable_units

        base_output = hdf.require_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        )
        base_output.create_dataset("Time Date Stamp (ms)", data=timestamps)


def test_pump_station_timeseries_supports_multi_group_columns(tmp_path):
    hdf_path = tmp_path / "multi_group_pump.p01.hdf"
    _write_pump_hdf(hdf_path)

    pump_timeseries = HdfPump.get_pump_station_timeseries(
        hdf_path,
        pump_station="17th St Pumps",
    )

    assert list(pump_timeseries.coords["variable"].values) == [
        "Flow",
        "Stage HW",
        "Stage TW",
        "V Pumps Flow",
        "V Pumps Pumps on",
        "G Pumps Flow",
        "G Pumps Pumps on",
    ]
    assert pump_timeseries.sel(variable="V Pumps Flow").values.tolist() == [
        10.0,
        12.0,
    ]
    assert pump_timeseries.attrs["unit_by_variable"]["G Pumps Pumps on"] == "Pumps on"


def test_pump_operation_timeseries_supports_multi_group_columns(tmp_path):
    hdf_path = tmp_path / "multi_group_pump.p01.hdf"
    _write_pump_hdf(hdf_path)

    pump_operation = HdfPump.get_pump_operation_timeseries(
        hdf_path,
        pump_station="17th St Pumps",
    )

    assert list(pump_operation.columns) == [
        "Flow",
        "Stage HW",
        "Stage TW",
        "V Pumps Flow",
        "V Pumps Pumps on",
        "G Pumps Flow",
        "G Pumps Pumps on",
        "Time",
    ]
    assert pump_operation["G Pumps Flow"].tolist() == [20.0, 25.0]
    assert pump_operation.attrs["unit_by_variable"]["V Pumps Flow"] == "cfs"
