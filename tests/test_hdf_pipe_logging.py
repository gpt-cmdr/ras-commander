import logging

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf import HdfPipe


LOGGER_NAME = "ras_commander.hdf.HdfPipe"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_hdf(path):
    with h5py.File(path, "w"):
        pass
    return path


def _write_pipe_timeseries_hdf(path):
    with h5py.File(path, "w") as hdf:
        dataset = hdf.create_dataset(
            "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/"
            "Unsteady Time Series/Pipe Networks/Davis/Nodes/Depth",
            data=np.zeros((2, 3)),
        )
        dataset.attrs["Units"] = b"ft"
    return path


def _write_pipe_summary_hdf(path):
    with h5py.File(path, "w") as hdf:
        dtype = np.dtype([("Name", "S10"), ("Maximum", "f8")])
        hdf.create_dataset(
            "Results/Unsteady/Summary/Pipe Network",
            data=np.array([(b"Depth", 1.2)], dtype=dtype),
        )
    return path


def test_optional_pipe_inlets_absence_is_quiet_by_default(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        inlets = HdfPipe.get_pipe_inlets(hdf_path)

    assert inlets.empty
    assert _records(caplog) == []


def test_missing_pipe_nodes_raise_preprocessor_guidance_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError, match="Run the HEC-RAS geometry preprocessor"):
            HdfPipe.get_pipe_nodes(hdf_path)

    assert _records(caplog) == []


def test_missing_pipe_profile_raise_preprocessor_guidance_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError) as exc_info:
            HdfPipe.get_pipe_profile(hdf_path, conduit_id=0)

    message = str(exc_info.value)
    assert "Pipe conduit terrain profile data is absent" in message
    assert "Run the HEC-RAS geometry preprocessor" in message
    assert _records(caplog) == []


def test_missing_pipe_summary_raise_plan_output_guidance_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError, match="pipe-network summary output"):
            HdfPipe.get_pipe_network_summary(hdf_path)

    assert _records(caplog) == []


def test_missing_pipe_timeseries_variable_lists_available_without_error_log(
    tmp_path, caplog
):
    hdf_path = _write_pipe_timeseries_hdf(tmp_path / "pipes.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError) as exc_info:
            HdfPipe.get_pipe_network_timeseries(
                hdf_path,
                variable="Nodes/Drop Inlet Flow",
            )

    message = str(exc_info.value)
    assert "Nodes/Drop Inlet Flow" in message
    assert "Nodes/Depth" in message
    assert "Compute the plan with pipe-network output enabled" in message
    assert _records(caplog) == []


def test_pipe_summary_success_has_no_default_log_noise(tmp_path, caplog):
    hdf_path = _write_pipe_summary_hdf(tmp_path / "summary.p01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        summary = HdfPipe.get_pipe_network_summary(hdf_path)

    assert isinstance(summary, pd.DataFrame)
    assert summary["Name"].iloc[0] == b"Depth"
    assert _records(caplog) == []
