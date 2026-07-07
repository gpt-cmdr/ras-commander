from __future__ import annotations

import logging

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from shapely.geometry import Point

from ras_commander.hdf.HdfResultsPlot import HdfResultsPlot


LOGGER_NAME = "ras_commander.hdf.HdfResultsPlot"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


@pytest.fixture(autouse=True)
def _disable_show(monkeypatch):
    monkeypatch.setattr(plt, "show", lambda: None)
    yield
    plt.close("all")


def _max_ws_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "geometry": [Point(0.0, 0.0), Point(1.0, 1.0)],
            "maximum_water_surface": [101.2, 103.4],
            "maximum_water_surface_time": [
                "2018-09-09 00:00:00",
                "2018-09-09 06:00:00",
            ],
        }
    )


def test_plot_results_max_wsel_success_has_no_stdout_or_default_logs(
    capsys,
    caplog,
):
    data = _max_ws_df()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        HdfResultsPlot.plot_results_max_wsel(data)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert _records(caplog) == []
    assert "x" not in data.columns
    assert "y" not in data.columns


def test_plot_results_max_wsel_missing_columns_are_actionable(capsys, caplog):
    data = pd.DataFrame({"geometry": [Point(0.0, 0.0)]})

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfResultsPlot.plot_results_max_wsel(data)

    captured = capsys.readouterr()
    message = str(exc_info.value)
    assert captured.out == ""
    assert "missing column(s): ['maximum_water_surface']" in message
    assert "Available columns: ['geometry']" in message
    assert _records(caplog) == []


def test_plot_results_max_wsel_all_null_geometry_is_actionable(capsys, caplog):
    data = pd.DataFrame(
        {
            "geometry": [None],
            "maximum_water_surface": [101.2],
        }
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfResultsPlot.plot_results_max_wsel(data)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no valid point geometries" in str(exc_info.value)
    assert _records(caplog) == []


def test_plot_results_max_wsel_time_default_has_no_stdout_or_default_logs(
    capsys,
    caplog,
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsPlot.plot_results_max_wsel_time(_max_ws_df())

    captured = capsys.readouterr()
    assert result is None
    assert captured.out == ""
    assert _records(caplog) == []


def test_plot_results_max_wsel_time_show_stats_returns_concise_dict(
    capsys,
    caplog,
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        stats = HdfResultsPlot.plot_results_max_wsel_time(
            _max_ws_df(),
            show_stats=True,
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert stats["time_range_hours"] == pytest.approx(6.0)
    assert stats["count"] == 2
    assert stats["min_hours"] == pytest.approx(0.0)
    assert stats["max_hours"] == pytest.approx(6.0)
    assert _records(caplog) == []


def test_plot_results_max_wsel_time_invalid_time_column_is_actionable(
    capsys,
    caplog,
):
    data = _max_ws_df()
    data.loc[0, "maximum_water_surface_time"] = "not a date"

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfResultsPlot.plot_results_max_wsel_time(data)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not be parsed as datetimes" in str(exc_info.value)
    assert _records(caplog) == []


def test_plot_results_mesh_variable_success_has_no_stdout_or_default_logs(
    capsys,
    caplog,
):
    data = pd.DataFrame(
        {
            "geometry": [Point(0.0, 0.0), Point(1.0, 1.0)],
            "Velocity": [2.0, 3.5],
        }
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        HdfResultsPlot.plot_results_mesh_variable(data, "Velocity")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert _records(caplog) == []


def test_plot_results_mesh_variable_requires_geometry_column(capsys, caplog):
    data = pd.DataFrame({"Velocity": [2.0, 3.5]})

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfResultsPlot.plot_results_mesh_variable(data, "Velocity")

    captured = capsys.readouterr()
    message = str(exc_info.value)
    assert captured.out == ""
    assert "missing column(s): ['geometry']" in message
    assert "Available columns: ['Velocity']" in message
    assert _records(caplog) == []


def test_plot_results_mesh_variable_requires_variable_column(capsys, caplog):
    data = pd.DataFrame({"geometry": [Point(0.0, 0.0)]})

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfResultsPlot.plot_results_mesh_variable(data, "Velocity")

    captured = capsys.readouterr()
    message = str(exc_info.value)
    assert captured.out == ""
    assert "missing column(s): ['Velocity']" in message
    assert "Available columns: ['geometry']" in message
    assert _records(caplog) == []
