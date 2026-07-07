import importlib
import logging
import sys
import types
from pathlib import Path

import pandas as pd


LOGGER_NAME = "ras_commander.usgs.catalog"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_path = str(project_folder)
        self.prj_file = project_folder / "project.prj"
        self.geom_df = pd.DataFrame({"hdf_path": [project_folder / "project.g01.hdf"]})


def _install_fake_dataretrieval(monkeypatch):
    fake_nwis = types.ModuleType("dataretrieval.nwis")
    fake_dataretrieval = types.ModuleType("dataretrieval")
    fake_dataretrieval.nwis = fake_nwis
    monkeypatch.setitem(sys.modules, "dataretrieval", fake_dataretrieval)
    monkeypatch.setitem(sys.modules, "dataretrieval.nwis", fake_nwis)


def _fake_gauges():
    return pd.DataFrame(
        {
            "site_no": ["01500000", "01500001"],
            "station_nm": ["Example Creek near Test", "Example River at Test"],
            "dec_lat_va": [40.0, 40.1],
            "dec_long_va": [-77.0, -77.1],
            "drain_area_va": [10.0, 20.0],
            "state_cd": ["PA", "PA"],
            "county_nm": ["Test", "Test"],
            "huc_cd": ["02050205", "02050205"],
            "site_tp_cd": ["ST", "ST"],
            "distance_km": [1.0, 2.0],
            "position": ["upstream", "downstream"],
        }
    )


def _fake_metadata(site_id):
    return {
        "site_id": site_id,
        "station_name": f"USGS {site_id}",
        "latitude": 40.0,
        "longitude": -77.0,
        "drainage_area_sqmi": 10.0,
        "gage_datum_ft": 100.0,
        "state": "PA",
        "county": "Test",
        "huc_cd": "02050205",
        "site_type": "ST",
        "active": True,
        "available_parameters": ["flow"],
        "begin_date": "2000-01-01",
        "end_date": "2020-01-01",
        "count_nu": 20,
    }


def test_generate_gauge_catalog_info_is_concise_and_debug_keeps_paths(monkeypatch, tmp_path, caplog):
    catalog_module = importlib.import_module("ras_commander.usgs.catalog")
    _install_fake_dataretrieval(monkeypatch)

    output_folder = tmp_path / "USGS Gauge Data"
    progress_calls = []

    def fake_tqdm(iterable, **kwargs):
        progress_calls.append(kwargs)
        return iterable

    monkeypatch.setattr(catalog_module, "TQDM_AVAILABLE", True)
    monkeypatch.setattr(catalog_module, "tqdm", fake_tqdm)
    monkeypatch.setattr(catalog_module, "GEOPANDAS_AVAILABLE", True)
    monkeypatch.setattr(
        catalog_module.UsgsGaugeSpatial,
        "find_gauges_in_project",
        lambda **kwargs: _fake_gauges(),
    )
    monkeypatch.setattr(catalog_module.RasUsgsCore, "get_gauge_metadata", _fake_metadata)
    monkeypatch.setattr(
        catalog_module.RasUsgsCore,
        "check_data_availability",
        lambda *args, **kwargs: {
            "available": True,
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
        },
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        summary = catalog_module.UsgsGaugeCatalog.generate_gauge_catalog(
            ras_object=_FakeRasProject(tmp_path),
            buffer_percent=25.0,
            include_historical=False,
            historical_years=1,
            output_folder=output_folder,
            parameters=["flow"],
            rate_limit_rps=0,
            api_key="test-key",
        )

    assert summary["gauge_count"] == 2
    assert summary["gauges_processed"] == 2
    assert progress_calls == [
        {
            "total": 2,
            "desc": "Processing gauges",
            "leave": False,
            "disable": True,
        }
    ]
    info_messages = _messages(caplog, logging.INFO)
    assert len(info_messages) == 2
    assert info_messages[0] == (
        "Generating USGS gauge catalog: buffer=25.0%, history=1 years, "
        "parameters=flow, historical_data=False"
    )
    assert info_messages[1].startswith("USGS gauge catalog complete: 2/2 gauges processed, 0 failed")
    assert str(output_folder) not in "\n".join(info_messages)
    assert "Processing gauge" not in "\n".join(info_messages)
    assert "Saved catalog" not in "\n".join(info_messages)

    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert str(output_folder) in debug_text
    assert "Processing gauge 01500000" in debug_text
    assert "Saved catalog:" in debug_text


def test_catalog_read_helpers_are_quiet_at_info_and_debug_keeps_paths(tmp_path, caplog):
    catalog_module = importlib.import_module("ras_commander.usgs.catalog")
    catalog_folder = tmp_path / "USGS Gauge Data"
    gauge_folder = catalog_folder / "USGS-01500000"
    gauge_folder.mkdir(parents=True)
    pd.DataFrame(
        {
            "site_id": ["01500000"],
            "station_name": ["Example Creek"],
            "folder_path": ["USGS-01500000"],
        }
    ).to_csv(catalog_folder / "gauge_catalog.csv", index=False)
    pd.DataFrame(
        {
            "datetime": pd.date_range("2020-01-01", periods=2, freq="h"),
            "value": [1.0, 2.0],
            "units": ["cfs", "cfs"],
            "qualifiers": ["A", "A"],
        }
    ).to_csv(gauge_folder / "historical_flow.csv", index=False)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        catalog = catalog_module.UsgsGaugeCatalog.load_gauge_catalog(catalog_folder=catalog_folder)
        flow = catalog_module.UsgsGaugeCatalog.load_gauge_data(
            "01500000",
            parameter="flow",
            catalog_folder=catalog_folder,
        )

    assert catalog["site_id"].tolist() == ["01500000"]
    assert len(flow) == 2
    assert _messages(caplog, logging.INFO) == []
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert str(catalog_folder / "gauge_catalog.csv") in debug_text
    assert "Loaded 2 flow records for gauge 01500000" in debug_text


def test_update_gauge_catalog_info_is_concise_and_debug_keeps_mechanics(monkeypatch, tmp_path, caplog):
    catalog_module = importlib.import_module("ras_commander.usgs.catalog")
    catalog_folder = tmp_path / "USGS Gauge Data"
    gauge_folder = catalog_folder / "USGS-01500000"
    gauge_folder.mkdir(parents=True)
    pd.DataFrame(
        {
            "site_id": ["01500000"],
            "folder_path": ["USGS-01500000"],
        }
    ).to_csv(catalog_folder / "gauge_catalog.csv", index=False)
    (gauge_folder / "data_availability.json").write_text(
        '{"flow": {"available": true, "end_date": "2020-01-01", "record_count": 1}}',
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2020-01-01")],
            "value": [1.0],
        }
    ).to_csv(gauge_folder / "historical_flow.csv", index=False)
    progress_calls = []

    def fake_tqdm(iterable, **kwargs):
        progress_calls.append(kwargs)
        return iterable

    monkeypatch.setattr(catalog_module, "TQDM_AVAILABLE", True)
    monkeypatch.setattr(catalog_module, "tqdm", fake_tqdm)
    monkeypatch.setattr(
        catalog_module.RasUsgsCore,
        "retrieve_flow_data",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2020-01-02")],
                "value": [2.0],
            }
        ),
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        summary = catalog_module.UsgsGaugeCatalog.update_gauge_catalog(
            catalog_folder=catalog_folder,
            parameters=["flow"],
            rate_limit_rps=0,
            api_key="test-key",
        )

    assert summary["gauges_updated"] == 1
    assert summary["gauges_failed"] == 0
    assert progress_calls == [
        {
            "total": 1,
            "desc": "Updating gauges",
            "leave": False,
            "disable": True,
        }
    ]
    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "Updating gauge catalog: 1 gauges",
        "Catalog update complete: 1 updated, 0 failed",
    ]
    assert str(catalog_folder) not in "\n".join(info_messages)

    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert "Using provided API key for USGS requests" in debug_text
    assert "Loaded gauge catalog: 1 gauges from" in debug_text
    assert "Gauge 01500000: Updated flow data" in debug_text
