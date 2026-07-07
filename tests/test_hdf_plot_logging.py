from __future__ import annotations

import logging

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from shapely.geometry import Polygon

from ras_commander.hdf.HdfPlot import HdfPlot


LOGGER_NAME = "ras_commander.hdf.HdfPlot"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


@pytest.fixture(autouse=True)
def _disable_show(monkeypatch):
    monkeypatch.setattr(plt, "show", lambda: None)
    yield
    plt.close("all")


def test_plot_mesh_cells_success_has_no_stdout_or_default_logs(
    capsys,
    caplog,
):
    cells = pd.DataFrame(
        {
            "cell_id": [1],
            "geometry": [
                Polygon(
                    [
                        (0.0, 0.0),
                        (1.0, 0.0),
                        (1.0, 1.0),
                        (0.0, 1.0),
                    ]
                )
            ],
        }
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfPlot.plot_mesh_cells(cells, projection="EPSG:4326")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert result.crs.to_string() == "EPSG:4326"
    assert result["cell_id"].tolist() == [1]
    assert _records(caplog) == []


def test_plot_mesh_cells_empty_input_raises_without_stdout(capsys, caplog):
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfPlot.plot_mesh_cells(pd.DataFrame(), projection="EPSG:4326")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "input DataFrame is empty" in str(exc_info.value)
    assert _records(caplog) == []


def test_plot_time_series_success_has_no_stdout_or_default_logs(
    capsys,
    caplog,
):
    data = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=2, freq="h"),
            "stage": [10.0, 11.5],
        }
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        HdfPlot.plot_time_series(data, x_col="time", y_col="stage")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert _records(caplog) == []


def test_plot_time_series_missing_columns_are_actionable(capsys, caplog):
    data = pd.DataFrame({"time": [1, 2], "flow": [100.0, 200.0]})

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfPlot.plot_time_series(data, x_col="timestamp", y_col="stage")

    captured = capsys.readouterr()
    message = str(exc_info.value)
    assert captured.out == ""
    assert "missing column(s): ['timestamp', 'stage']" in message
    assert "Available columns: ['time', 'flow']" in message
    assert _records(caplog) == []
