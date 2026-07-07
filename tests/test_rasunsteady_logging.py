"""Logging regressions for RasUnsteady notebook-facing output."""

import logging

import pandas as pd
import pytest

from ras_commander import RasUnsteady


LOGGER_NAME = "ras_commander.RasUnsteady"


class _DummyRas:
    def __init__(self, project_folder=None, project_name="Model"):
        self.project_folder = project_folder
        self.project_name = project_name

    def check_initialized(self):
        return None

    def get_unsteady_entries(self):
        return pd.DataFrame()


def _records(caplog, level=None):
    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    if level is not None:
        records = [record for record in records if record.levelno == level]
    return records


def _messages(caplog, level=None):
    return [record.getMessage() for record in _records(caplog, level)]


def _write_unsteady(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_flow_title_success_info_uses_filename_and_debug_keeps_path(tmp_path, caplog):
    unsteady_file = _write_unsteady(
        tmp_path / "project" / "Model.u02",
        ["Flow Title=Old Flow", "Program Version=6.60"],
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady.update_flow_title(
            unsteady_file,
            "New Flow",
            ras_object=_DummyRas(),
        )

    info_messages = _messages(caplog, logging.INFO)
    assert "Applied Flow Title modification to Model.u02" in info_messages
    assert not any(str(unsteady_file.parent) in message for message in info_messages)
    assert any(str(unsteady_file) in message for message in _messages(caplog, logging.DEBUG))


def test_restart_settings_collapses_success_log_and_debug_keeps_path(tmp_path, caplog):
    unsteady_file = _write_unsteady(
        tmp_path / "project" / "Model.u01",
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Use Restart=0",
            "Restart Filename=old_restart.rst",
            "Boundary Location=TestBoundary",
        ],
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady.set_restart_settings(
            unsteady_file,
            use_restart=True,
            restart_filename="new_restart.rst",
            ras_object=_DummyRas(),
        )

    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "Updated restart settings in Model.u01: "
        "use_restart=True, restart_filename=new_restart.rst"
    ]
    assert not any("Updated Use Restart" in message for message in info_messages)
    assert not any("Set Restart Filename" in message for message in info_messages)
    assert not any(str(unsteady_file.parent) in message for message in info_messages)
    assert any(str(unsteady_file) in message for message in _messages(caplog, logging.DEBUG))


def test_boundary_query_summaries_are_debug_not_info(tmp_path, caplog):
    unsteady_file = _write_unsteady(
        tmp_path / "Model.u01",
        [
            "Flow Title=Boundary Test",
            "Program Version=6.60",
            "Boundary Location=River,Reach,100.0,,,,,,",
            "Interval=1HOUR",
            "Flow Hydrograph=2",
            "    1.00    2.00",
            "Use DSS=False",
            "Boundary Location=River,Reach,200.0,,,,,,",
            "Interval=1HOUR",
            "Flow Hydrograph=2",
            "DSS File=flow.dss",
            "DSS Path=//A/SUB1/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            "Use DSS=True",
        ],
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        dss_boundaries = RasUnsteady.get_dss_boundaries(unsteady_file)
        inline_boundaries = RasUnsteady.get_inline_hydrograph_boundaries(unsteady_file)
        subbasins = RasUnsteady.get_unique_dss_subbasins(unsteady_file)

    assert len(dss_boundaries) == 1
    assert len(inline_boundaries) == 1
    assert subbasins == ["SUB1"]
    assert _messages(caplog, logging.INFO) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady.get_dss_boundaries(unsteady_file)
        RasUnsteady.get_inline_hydrograph_boundaries(unsteady_file)
        RasUnsteady.get_unique_dss_subbasins(unsteady_file)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Found 1 DSS-linked boundaries in Model.u01" in message for message in debug_messages)
    assert any("Found 1 inline hydrograph boundaries in Model.u01" in message for message in debug_messages)
    assert any("Found 1 unique HMS subbasins in DSS paths" in message for message in debug_messages)


def test_gridded_precipitation_configuration_info_is_concise(tmp_path, caplog):
    unsteady_file = _write_unsteady(
        tmp_path / "Model.u01",
        [
            "Flow Title=Gridded Precipitation",
            "Program Version=6.60",
            "Met BC=Precipitation|Gridded Source=DSS",
            "Met BC=Precipitation|Gridded DSS Pathname=/A/B/PRECIP/01JAN2020/1HOUR/RUN/",
        ],
    )
    precip_file = tmp_path / "Precipitation" / "storm.nc"
    precip_file.parent.mkdir()
    precip_file.write_text("", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady.set_gridded_precipitation(
            "01",
            precip_file,
            interpolation="Bilinear",
            ras_object=_DummyRas(project_folder=tmp_path, project_name="Model"),
        )

    info_messages = _messages(caplog, logging.INFO)
    assert (
        "Configured gridded precipitation in Model.u01: "
        "source=.\\Precipitation\\storm.nc, interpolation=Bilinear"
    ) in info_messages
    assert not any(str(tmp_path) in message for message in info_messages)
    assert any(str(unsteady_file) in message for message in _messages(caplog, logging.DEBUG))


def test_gridded_precipitation_hdf_import_logs_one_concise_info(tmp_path, caplog, monkeypatch):
    pytest.importorskip("h5py")
    xr = pytest.importorskip("xarray")

    import h5py
    import numpy as np

    netcdf_path = tmp_path / "Precipitation" / "storm.nc"
    netcdf_path.parent.mkdir()
    netcdf_path.write_text("", encoding="utf-8")

    class _FakeArray:
        def __init__(self, values):
            self.values = values

    class _FakeDataset:
        data_vars = {"APCP": object()}

        def __init__(self):
            self._values = {
                "APCP": np.array([[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]]),
                "time": pd.date_range("2020-01-01", periods=2, freq="h").to_numpy(),
                "y": np.array([0.0, 1.0]),
                "x": np.array([0.0, 1.0]),
            }

        def __getitem__(self, key):
            return _FakeArray(self._values[key])

        def close(self):
            return None

    monkeypatch.setattr(xr, "open_dataset", lambda path: _FakeDataset())

    hdf_path = tmp_path / "Model.u01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady._update_precipitation_hdf(
            hdf_path=hdf_path,
            netcdf_path=netcdf_path,
            netcdf_rel_path=".\\Precipitation\\storm.nc",
            interpolation="Bilinear",
        )

    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "Imported gridded precipitation into Model.u01.hdf: "
        "2 timesteps, 4 cells, range=1.0-12.0 mm"
    ]
    assert not any(str(tmp_path) in message for message in info_messages)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any(str(hdf_path) in message for message in debug_messages)
    assert any("NetCDF precipitation grid: 2 timesteps, 2x2 grid" in message for message in debug_messages)


def test_meteorology_mutation_info_uses_filename_and_debug_keeps_path(tmp_path, caplog):
    unsteady_file = _write_unsteady(
        tmp_path / "project" / "Model.u01",
        ["Flow Title=Meteorology", "Program Version=6.60"],
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasUnsteady.set_meteorological_station(
            unsteady_file,
            name="Gauge_A",
            x=1.0,
            y=2.0,
        )
        RasUnsteady.set_point_evapotranspiration(
            unsteady_file,
            station_name="Gauge_A",
            et_df=pd.DataFrame({"hour": [0.0, 1.0], "et": [0.1, 0.2]}),
            x=1.0,
            y=2.0,
        )

    info_messages = _messages(caplog, logging.INFO)
    assert "Updated meteorological station 'Gauge_A' in Model.u01" in info_messages
    assert any(
        message.startswith("Configured point ET for station 'Gauge_A' in Model.u01")
        for message in info_messages
    )
    assert not any(str(unsteady_file.parent) in message for message in info_messages)
    assert any(str(unsteady_file) in message for message in _messages(caplog, logging.DEBUG))
