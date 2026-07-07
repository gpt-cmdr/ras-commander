import logging

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfPump


LOGGER_NAME = "ras_commander.hdf.HdfPump"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_hdf(path):
    with h5py.File(path, "w"):
        pass
    return path


def _variable_units(column_count=5):
    rows = [
        [b"Flow", b"cfs"],
        [b"Stage HW", b"ft"],
        [b"Stage TW", b"ft"],
        [b"Pump Station", b""],
        [b"Pumps on", b"Pumps on"],
    ]
    return np.array(rows[:column_count], dtype="S32")


def _write_pump_results_hdf(path, station_name="Pump A", rows=2, timestamp_count=2):
    data = np.arange(rows * 5, dtype=np.float32).reshape(rows, 5)
    timestamps = np.array(
        [
            b"10APR2024 00:00:00:000",
            b"10APR2024 00:05:00:000",
            b"10APR2024 00:10:00:000",
        ][:timestamp_count],
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
            station_group = base_group.require_group(f"Pumping Stations/{station_name}")
            dataset = station_group.create_dataset("Structure Variables", data=data)
            dataset.attrs["Variable_Unit"] = _variable_units()

        base_output = hdf.require_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        )
        base_output.create_dataset("Time Date Stamp (ms)", data=timestamps)

    return path


def _write_station_without_structure_variables(path, station_name="Pump A"):
    with h5py.File(path, "w") as hdf:
        base = (
            "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/"
            "Unsteady Time Series/Pumping Stations"
        )
        hdf.require_group(f"{base}/{station_name}")
    return path


def test_missing_optional_pump_geometry_is_quiet_by_default(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        stations = HdfPump.get_pump_stations(hdf_path)
        groups = HdfPump.get_pump_groups(hdf_path)
        summary = HdfPump.get_pump_station_summary(hdf_path)

    assert stations.empty
    assert groups.empty
    assert summary.empty
    assert _records(caplog) == []


def test_missing_optional_pump_geometry_has_debug_context(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfPump.get_pump_stations(hdf_path)
        HdfPump.get_pump_groups(hdf_path)
        HdfPump.get_pump_station_summary(hdf_path)

    messages = [record.getMessage() for record in _records(caplog)]
    assert any("No pump station geometry group" in message for message in messages)
    assert any("No pump station pump-group geometry" in message for message in messages)
    assert any("Pump station summary data not found" in message for message in messages)
    assert not any(record.levelno >= logging.WARNING for record in _records(caplog))


def test_missing_pump_station_timeseries_group_raises_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError) as exc_info:
            HdfPump.get_pump_station_timeseries(hdf_path, pump_station="Pump A")

    message = str(exc_info.value)
    assert "Pump station timeseries extraction" in message
    assert "Compute the plan with pump station output available" in message
    assert _records(caplog) == []


def test_missing_requested_pump_station_lists_available_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_pump_results_hdf(tmp_path / "pump.p01.hdf", station_name="Pump A")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfPump.get_pump_station_timeseries(hdf_path, pump_station="Pump B")

    message = str(exc_info.value)
    assert "Pump B" in message
    assert "Pump A" in message
    assert "Available pump stations" in message
    assert _records(caplog) == []


def test_missing_pump_structure_variables_raise_without_error_log(tmp_path, caplog):
    hdf_path = _write_station_without_structure_variables(
        tmp_path / "missing_structure.p01.hdf",
        station_name="Pump A",
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError) as exc_info:
            HdfPump.get_pump_station_timeseries(hdf_path, pump_station="Pump A")

    message = str(exc_info.value)
    assert "Structure Variables" in message
    assert "Pump A" in message
    assert "Compute the plan with pump station output available" in message
    assert _records(caplog) == []


def test_pump_operation_missing_station_lists_available_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_pump_results_hdf(tmp_path / "pump.p01.hdf", station_name="Pump A")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfPump.get_pump_operation_timeseries(hdf_path, pump_station="Pump B")

    message = str(exc_info.value)
    assert "Pump B" in message
    assert "Pump A" in message
    assert "Available pump stations" in message
    assert _records(caplog) == []


def test_successful_pump_results_do_not_log_by_default(tmp_path, caplog):
    hdf_path = _write_pump_results_hdf(tmp_path / "pump.p01.hdf", station_name="Pump A")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        timeseries = HdfPump.get_pump_station_timeseries(
            hdf_path,
            pump_station="Pump A",
        )
        operation = HdfPump.get_pump_operation_timeseries(
            hdf_path,
            pump_station="Pump A",
        )

    assert timeseries.shape == (2, 5)
    assert len(operation) == 2
    assert _records(caplog) == []


def test_timestamp_mismatch_warning_is_specific_and_path_concise(tmp_path, caplog):
    hdf_path = _write_pump_results_hdf(
        tmp_path / "mismatch.p01.hdf",
        station_name="Pump A",
        rows=2,
        timestamp_count=1,
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        timeseries = HdfPump.get_pump_station_timeseries(
            hdf_path,
            pump_station="Pump A",
        )

    records = _records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert "Pump A" in message
    assert "Structure Variables" in message
    assert "timestamps=1 rows=2" in message
    assert str(hdf_path) not in message
    assert timeseries.coords["time"].values.tolist() == [0, 1]
