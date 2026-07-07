import logging
from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander.hdf.HdfResultsBreach import HdfResultsBreach


LOGGER_NAME = "ras_commander.hdf.HdfResultsBreach"


def _empty_hdf(path: Path) -> None:
    with h5py.File(path, "w"):
        pass


def _structure_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01 00:00"]),
            "total_flow": [100.0],
            "weir_flow": [25.0],
            "hw": [20.0],
            "tw": [10.0],
        }
    )


def test_direct_missing_sa2d_connection_warns(tmp_path, caplog):
    """Direct breach data requests should stay visible when required data is absent."""
    hdf_path = tmp_path / "no_sa_conn.p01.hdf"
    _empty_hdf(hdf_path)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfResultsBreach.get_breaching_variables(hdf_path)

    assert result.empty
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]
    assert messages == [f"No SA 2D Area Conn data in {hdf_path.name}"]


def test_breach_timeseries_partial_result_is_debug_only(
    tmp_path,
    caplog,
    monkeypatch,
):
    """Fallback from missing breach variables to structure data should not warn."""
    hdf_path = tmp_path / "structure_only.p01.hdf"
    _empty_hdf(hdf_path)

    def fake_structure_variables(hdf_path, structure_name=None, *, ras_object=None):
        return _structure_dataframe()

    def fake_breaching_variables(hdf_path, structure_name=None, *, ras_object=None):
        return pd.DataFrame()

    monkeypatch.setattr(
        HdfResultsBreach,
        "get_structure_variables",
        staticmethod(fake_structure_variables),
    )
    monkeypatch.setattr(
        HdfResultsBreach,
        "get_breaching_variables",
        staticmethod(fake_breaching_variables),
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfResultsBreach.get_breach_timeseries(hdf_path)

    assert not result.empty
    assert not [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfResultsBreach.get_breach_timeseries(hdf_path)

    assert any(
        record.name == LOGGER_NAME
        and record.levelno == logging.DEBUG
        and "No breach data available, returning structure data only"
        in record.getMessage()
        for record in caplog.records
    )


def test_breach_timeseries_error_log_includes_hdf_path(
    tmp_path,
    caplog,
    monkeypatch,
):
    hdf_path = tmp_path / "failure.p01.hdf"
    _empty_hdf(hdf_path)

    def fake_structure_variables(hdf_path, structure_name=None, *, ras_object=None):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(
        HdfResultsBreach,
        "get_structure_variables",
        staticmethod(fake_structure_variables),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(RuntimeError):
            HdfResultsBreach.get_breach_timeseries(hdf_path)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]
    assert len(messages) == 1
    assert "Error creating combined breach timeseries" in messages[0]
    assert str(hdf_path) in messages[0]
    assert "synthetic failure" in messages[0]
