import importlib
import logging
import sys
import types
from pathlib import Path

import pandas as pd


LOGGER_NAME = "ras_commander.precip.PrecipAorc"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


class _FakeCoord:
    def __init__(self, values):
        self.values = values


class _FakeMean:
    def __init__(self, series):
        self._series = series

    def __len__(self):
        return len(self._series)

    def load(self):
        return self

    def to_series(self):
        return self._series.copy()


class _FakeAorcArray:
    dims = ("time", "latitude", "longitude")

    def __init__(self, series=None):
        self.size = 1
        self.sizes = {"time": 3, "latitude": 2, "longitude": 2}
        self.shape = (3, 2, 2)
        self.attrs = {}
        self._series = series

    def __getitem__(self, key):
        if key == "latitude":
            return _FakeCoord([42.0, 40.0])
        if key == "longitude":
            return _FakeCoord([-78.0, -77.0])
        raise KeyError(key)

    def sel(self, **kwargs):
        return self

    def load(self):
        return self

    def sortby(self, dim):
        return self

    def mean(self, dim):
        return _FakeMean(self._series)

    def to_netcdf(self, output_path):
        Path(output_path).write_bytes(b"fake netcdf")


class _FakeDataset:
    dims = {"time": 3, "latitude": 2, "longitude": 2}

    def __init__(self, array):
        self._array = array

    def __contains__(self, key):
        return key == "APCP_surface"

    def __getitem__(self, key):
        if key != "APCP_surface":
            raise KeyError(key)
        return self._array


class _FakeS3FileSystem:
    def __init__(self, anon=True):
        self.anon = anon


class _FakeS3Map:
    def __init__(self, root, s3):
        self.root = root
        self.s3 = s3


def _install_fake_aorc_modules(monkeypatch, array):
    fake_xarray = types.SimpleNamespace(
        open_zarr=lambda store: _FakeDataset(array),
        concat=lambda datasets, dim: datasets[0],
    )
    fake_s3fs = types.SimpleNamespace(
        S3FileSystem=_FakeS3FileSystem,
        S3Map=_FakeS3Map,
    )
    monkeypatch.setitem(sys.modules, "xarray", fake_xarray)
    monkeypatch.setitem(sys.modules, "s3fs", fake_s3fs)


def test_download_info_is_concise_and_debug_keeps_paths(monkeypatch, tmp_path, caplog):
    aorc_module = importlib.import_module("ras_commander.precip.PrecipAorc")
    monkeypatch.setattr(aorc_module, "_check_precip_dependencies", lambda: None)
    _install_fake_aorc_modules(monkeypatch, _FakeAorcArray())

    output_path = tmp_path / "precipitation" / "storm_20200101.nc"

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = aorc_module.PrecipAorc.download(
            bounds=(-78.0, 40.0, -77.0, 42.0),
            start_time="2020-01-01",
            end_time="2020-01-02",
            output_path=output_path,
            target_crs=None,
        )

    assert result == output_path
    info_messages = _messages(caplog, logging.INFO)
    assert len(info_messages) == 2
    assert info_messages[0].startswith("Downloading AORC APCP_surface")
    assert info_messages[1].startswith("AORC download complete: storm_20200101.nc")
    assert str(output_path) not in "\n".join(info_messages)
    assert "grid=" not in "\n".join(info_messages)

    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert str(output_path) in debug_text
    assert "s3://noaa-nws-aorc-v1-1-1km/2020.zarr" in debug_text
    assert "Writing AORC NetCDF" in debug_text
    assert "AORC output grid shape" in debug_text


def test_check_availability_accepts_polygon_and_explicit_buffer():
    aorc_module = importlib.import_module("ras_commander.precip.PrecipAorc")
    from shapely.geometry import box

    result = aorc_module.PrecipAorc.check_availability(
        bounds=box(-78.0, 40.0, -77.0, 42.0),
        start_time="2020-01-01",
        end_time="2020-01-02",
        buffer_distance=0.25,
    )

    assert result["bounds"] == (-78.25, 39.75, -76.75, 42.25)
    assert result["in_conus"] is True


def test_get_storm_catalog_collapses_info_and_keeps_debug_details(monkeypatch, caplog):
    aorc_module = importlib.import_module("ras_commander.precip.PrecipAorc")
    monkeypatch.setattr(aorc_module, "_check_precip_dependencies", lambda: None)
    precip_series = pd.Series(
        [0.0, 20.0, 15.0, 0.0, 0.0, 0.0, 30.0, 0.0, 0.0, 0.0],
        index=pd.date_range("2020-01-01", periods=10, freq="h"),
    )
    _install_fake_aorc_modules(monkeypatch, _FakeAorcArray(series=precip_series))

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        catalog = aorc_module.PrecipAorc.get_storm_catalog(
            bounds=(-78.0, 40.0, -77.0, 42.0),
            year=2020,
            inter_event_hours=3,
            min_depth_inches=0.5,
            buffer_hours=1,
        )

    assert len(catalog) == 2
    info_messages = _messages(caplog, logging.INFO)
    assert len(info_messages) == 2
    assert info_messages[0].startswith("Generating AORC storm catalog for 2020")
    assert info_messages[1].startswith("Storm catalog complete: 2 storms; depth")
    assert "s3://" not in "\n".join(info_messages)
    assert "Identified" not in "\n".join(info_messages)

    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert "Loading AORC store: s3://noaa-nws-aorc-v1-1-1km/2020.zarr" in debug_text
    assert "Loaded 10 hourly AORC timesteps" in debug_text
    assert "Identified 2 raw AORC storm events" in debug_text


def test_create_storm_plans_logs_one_summary_per_storm(monkeypatch, tmp_path, caplog):
    aorc_module = importlib.import_module("ras_commander.precip.PrecipAorc")
    rasplan_module = importlib.import_module("ras_commander.RasPlan")
    rasunsteady_module = importlib.import_module("ras_commander.RasUnsteady")

    class FakeRasProject:
        project_folder = tmp_path

        def check_initialized(self):
            return None

    plan_paths = {"06": tmp_path / "project.p06"}
    plan_paths["06"].write_text("Flow File=u01\nHDF Write Time Slices=0\n", encoding="utf-8")
    next_plan = iter(["07", "08"])
    next_unsteady = iter(["02", "03"])

    def fake_get_plan_path(plan_number, ras_object=None):
        return plan_paths.get(str(plan_number))

    def fake_clone_unsteady(template_unsteady, new_title, ras_object=None):
        return next(next_unsteady)

    def fake_clone_plan(template_plan, new_plan_shortid, new_title, ras_object=None):
        plan_number = next(next_plan)
        plan_path = tmp_path / f"project.p{plan_number}"
        plan_path.write_text("Flow File=u01\nHDF Write Time Slices=0\n", encoding="utf-8")
        plan_paths[plan_number] = plan_path
        return plan_number

    monkeypatch.setattr(rasplan_module.RasPlan, "get_plan_path", fake_get_plan_path)
    monkeypatch.setattr(rasplan_module.RasPlan, "clone_unsteady", fake_clone_unsteady)
    monkeypatch.setattr(rasplan_module.RasPlan, "clone_plan", fake_clone_plan)
    monkeypatch.setattr(rasplan_module.RasPlan, "set_unsteady", lambda *args, **kwargs: None)
    monkeypatch.setattr(rasplan_module.RasPlan, "update_simulation_date", lambda *args, **kwargs: None)
    monkeypatch.setattr(rasunsteady_module.RasUnsteady, "set_gridded_precipitation", lambda *args, **kwargs: None)

    storm_catalog = pd.DataFrame(
        [
            {
                "storm_id": 1,
                "start_time": pd.Timestamp("2020-01-01 01:00"),
                "sim_start": pd.Timestamp("2020-01-01 00:00"),
                "sim_end": pd.Timestamp("2020-01-01 04:00"),
                "total_depth_in": 1.25,
            },
            {
                "storm_id": 2,
                "start_time": pd.Timestamp("2020-02-03 01:00"),
                "sim_start": pd.Timestamp("2020-02-03 00:00"),
                "sim_end": pd.Timestamp("2020-02-03 04:00"),
                "total_depth_in": 0.85,
            },
        ]
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        results = aorc_module.PrecipAorc.create_storm_plans(
            storm_catalog=storm_catalog,
            bounds=(-78.0, 40.0, -77.0, 42.0),
            template_plan="06",
            ras_object=FakeRasProject(),
            download_data=False,
        )

    assert results["status"].tolist() == ["success", "success"]
    info_messages = _messages(caplog, logging.INFO)
    assert len(info_messages) == 4
    assert info_messages[0] == "Creating storm plans from template plan 06 (unsteady 01); processing 2 storms"
    assert info_messages[1].startswith("Created storm 1: 2020-01-01")
    assert info_messages[2].startswith("Created storm 2: 2020-02-03")
    assert info_messages[3] == "Storm plan creation complete: 2/2 successful"
    assert str(tmp_path) not in "\n".join(info_messages)
    assert "Cloning" not in "\n".join(info_messages)
    assert "Configuring gridded precipitation" not in "\n".join(info_messages)

    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert str(tmp_path / "Precipitation") in debug_text
    assert "Cloning unsteady file for storm 1" in debug_text
    assert "Configuring gridded precipitation for storm 2" in debug_text
