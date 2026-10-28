"""Modern Water Data translation and public retrieval contracts, without HTTP."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ras_commander.usgs import _waterdata_adapter as adapter
from ras_commander.usgs.core import RasUsgsCore
from ras_commander.usgs.real_time import RasUsgsRealTime


def observations(*, code="00060", statistic="00011", units="ft^3/s"):
    return pd.DataFrame({
        "monitoring_location_id": ["USGS-01646500"] * 3,
        "parameter_code": [code] * 3, "statistic_id": [statistic] * 3,
        "time": ["2024-01-01T01:00:00Z", "2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"],
        "value": [3., 1., 2.], "unit_of_measure": [units] * 3,
        "approval_status": ["Provisional", "Approved", "Approved"],
        "qualifier": [None, None, "e"], "time_series_id": ["primary-series"] * 3,
    })


@pytest.fixture
def service(monkeypatch):
    calls = []
    def continuous(**kwargs):
        calls.append(kwargs)
        return observations(), {}
    api = SimpleNamespace(get_continuous=continuous,
        get_daily=lambda **kw: (observations(statistic="00003"), {}),
        get_monitoring_locations=lambda **kw: (pd.DataFrame(), {}),
        get_time_series_metadata=lambda **kw: (pd.DataFrame(), {}))
    monkeypatch.setattr(adapter, "_backend", lambda: api)
    monkeypatch.setattr(adapter, "_wait", lambda: None)
    monkeypatch.setattr(RasUsgsCore, "_ensure_dataretrieval", staticmethod(lambda: adapter._WaterDataAdapter))
    monkeypatch.setattr(RasUsgsRealTime, "_ensure_dataretrieval", staticmethod(lambda: adapter._WaterDataAdapter))
    return api, calls


def test_continuous_request_and_sorted_utc_contract(service):
    _, calls = service
    result, metadata = adapter._WaterDataAdapter.get_iv(
        sites="USGS-01646500", parameterCd="00060", start="2024-01-01", end="2024-01-01")
    assert calls[0] == dict(monitoring_location_id="USGS-01646500", parameter_code="00060",
        statistic_id="00011", time="2024-01-01T00:00:00+00:00/2024-01-02T00:00:00+00:00")
    assert str(result.index.tz) == "UTC"
    assert result.index.is_monotonic_increasing
    assert result["01646500_00060"].tolist() == [1., 2., 3.]
    assert result["01646500_00060_cd"].tolist() == ["A", "A", "P"]
    assert metadata["source"] == "dataretrieval.waterdata"


@pytest.mark.parametrize("daily", [False, True])
def test_date_end_includes_last_day_but_not_next_midnight(service, daily):
    api, _ = service
    data = observations(statistic="00003" if daily else "00011")
    data["time"] = ["2024-01-01T23:59:00Z", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"]
    setattr(api, "get_daily" if daily else "get_continuous", lambda **kw: (data, {}))
    result, _ = adapter._retrieve(sites="01646500", parameterCd="00060", start="2024-01-01", end="2024-01-01", daily=daily)
    assert len(result) == 2
    assert result.index.max().day == 1


def test_long_queries_are_split_and_rate_limited(monkeypatch, service):
    api, calls = service
    waits = []
    monkeypatch.setattr(adapter, "_wait", lambda: waits.append(1))
    _, metadata = adapter._WaterDataAdapter.get_iv(sites="01646500", parameterCd="00060", start="2020-01-01", end="2022-01-01")
    assert len(calls) == len(waits) == metadata["request_count"] == 3
    assert calls[0]["time"].endswith("/2021-01-01T00:00:00+00:00")


@pytest.mark.parametrize("field,value", [("unit_of_measure", "m^3/s"), ("approval_status", None),
    ("approval_status", "Unknown"), ("parameter_code", "00065"),
    ("monitoring_location_id", "USGS-00000000"), ("statistic_id", "00003"), ("time", None)])
def test_unexpected_provider_contract_is_rejected(field, value):
    frame = observations()
    frame[field] = value
    with pytest.raises(ValueError):
        adapter._normalize(frame, "01646500", "00060", "00011")


def test_conflicting_series_not_silently_selected():
    frame = observations()
    conflict = frame.iloc[[0]].copy()
    conflict["value"] = 99
    conflict["time_series_id"] = "secondary-series"
    with pytest.raises(ValueError, match="conflicting observations"):
        adapter._normalize(pd.concat([frame, conflict], ignore_index=True), "01646500", "00060", "00011")
    identical = adapter._normalize(pd.concat([frame, frame], ignore_index=True), "01646500", "00060", "00011")
    assert len(identical) == len(frame)


@pytest.mark.parametrize("method", ["retrieve_flow_data", "retrieve_stage_data"])
@pytest.mark.parametrize("kind", ["iv", "dv"])
def test_core_public_flow_and_stage_outputs(service, method, kind):
    api, _ = service
    code, unit = ("00060", "ft^3/s") if method == "retrieve_flow_data" else ("00065", "ft")
    fetch = lambda **kw: (observations(code=code, statistic=kw["statistic_id"], units=unit), {})
    api.get_continuous = api.get_daily = fetch
    result = getattr(RasUsgsCore, method)("01646500", "2024-01-01", "2024-01-01", kind)
    assert result.columns.tolist() == ["datetime", "value"]
    assert result["value"].tolist() == [1., 2., 3.]
    assert result.attrs["parameter_code"] == code
    assert result.attrs["data_type"] == kind


def test_latest_value_uses_approval_field_and_time_not_frame_index(service):
    api, _ = service
    now = pd.Timestamp.now(tz="UTC").floor("s")
    frame = observations()
    frame["time"] = [(now - pd.Timedelta(minutes=i)).isoformat() for i in [0, 2, 1]]
    frame.index = [100, 30, 70]
    api.get_continuous = lambda **kw: (frame, {})
    result = RasUsgsRealTime.get_latest_value("01646500")
    assert result["value"] == 3
    assert result["provisional"] is True
    assert "P" in result["qualifiers"]
    frame["approval_status"] = "Approved"
    assert RasUsgsRealTime.get_latest_value("01646500")["provisional"] is False


@pytest.mark.parametrize("geometry_kind", ["point", "list", "tuple", "geojson"])
def test_monitoring_location_metadata_mapping(service, geometry_kind):
    from shapely.geometry import Point
    api, _ = service
    geometry = {"point": Point(-77., 39.), "list": [-77., 39.],
                "tuple": (-77., 39.), "geojson": {"coordinates": [-77., 39.]}}[geometry_kind]
    api.get_monitoring_locations = lambda **kw: (pd.DataFrame([dict(
        monitoring_location_id="USGS-01646500", monitoring_location_name="Public Gauge",
        geometry=geometry, drainage_area=100., altitude=20., state_code="24",
        county_name="Example", hydrologic_unit_code="02070008", site_type_code="ST")]), {})
    api.get_time_series_metadata = lambda **kw: (pd.DataFrame({"parameter_code": ["00060", "00065"]}), {})
    result = RasUsgsCore.get_gauge_metadata("01646500")
    assert result["station_name"] == "Public Gauge"
    assert (result["latitude"], result["longitude"]) == (39., -77.)
    assert result["drainage_area_sqmi"] == 100
    assert result["available_parameters"] == ["00060", "00065"]


@pytest.mark.parametrize("geometry", [None, np.nan, [], [np.nan, 39.], [-77., float("inf")]])
def test_metadata_rejects_missing_coordinates(service, geometry):
    api, _ = service
    api.get_monitoring_locations = lambda **kw: (pd.DataFrame([{
        "monitoring_location_id": "USGS-01646500", "geometry": geometry}]), {})
    with pytest.raises(ValueError, match="geographic point"):
        adapter._WaterDataAdapter.get_info(sites="01646500")


def test_empty_response_retains_public_empty_shape(service):
    api, _ = service
    api.get_continuous = lambda **kw: (pd.DataFrame(), {})
    result = RasUsgsCore.retrieve_flow_data("01646500", "2024-01-01", "2024-01-01")
    assert result.empty and result.columns.tolist() == ["datetime", "value"]


@pytest.mark.parametrize("site,start,end", [("not-a-site", "2024-01-01", "2024-01-02"),
    ("01646500", "2024-01-02", "2024-01-01")])
def test_invalid_requests_are_rejected_before_network(service, site, start, end):
    _, calls = service
    with pytest.raises(ValueError):
        adapter._WaterDataAdapter.get_iv(sites=site, parameterCd="00060", start=start, end=end)
    assert not calls


def test_initial_condition_uses_utc_and_actual_approval(service):
    from ras_commander.usgs.initial_conditions import InitialConditions
    value, metadata = InitialConditions.get_ic_value_from_usgs(
        "01646500", "2024-01-01 01:00:00", parameter="flow")
    assert value == 3
    assert metadata["approval_status"] == "Provisional"
    assert str(metadata["actual_time"].tz) == "UTC"
    assert metadata["source_url"].startswith("https://api.waterdata.usgs.gov/")


def test_recent_and_refresh_keep_sorted_utc_values(service):
    api, _ = service
    now = pd.Timestamp.now(tz="UTC").floor("s")
    frame = observations()
    frame["time"] = [(now - pd.Timedelta(minutes=i)).isoformat() for i in [0, 2, 1]]
    api.get_continuous = lambda **kw: (frame, {})
    recent = RasUsgsRealTime.get_recent_data("01646500", hours=1)
    assert recent["value"].tolist() == [1., 2., 3.]
    refreshed = RasUsgsRealTime.refresh_data("01646500", cached_df=recent)
    assert refreshed["value"].tolist() == [1., 2., 3.]
    assert refreshed["datetime"].is_monotonic_increasing


def test_dependency_loaders_use_waterdata_and_never_nwis(monkeypatch):
    import sys
    from types import ModuleType
    package = ModuleType("dataretrieval")
    package.waterdata = SimpleNamespace(**{
        name: (lambda **kw: (pd.DataFrame(), {})) for name in
        ["get_continuous", "get_daily", "get_monitoring_locations", "get_time_series_metadata"]
    })
    def forbidden(name):
        if name == "nwis":
            raise AssertionError("Unexpected legacy dependency access")
        raise AttributeError(name)
    package.__getattr__ = forbidden
    monkeypatch.setitem(sys.modules, "dataretrieval", package)
    for cls in [RasUsgsCore, RasUsgsRealTime]:
        monkeypatch.setattr(cls, "_dataretrieval_loaded", False)
        result = cls._ensure_dataretrieval()
        assert result is adapter._WaterDataAdapter
        # Do not leave the synthetic adapter cached after this test.
        monkeypatch.setattr(cls, "_dataretrieval_loaded", False)


def test_recorded_official_response_preserves_observations():
    import json
    from pathlib import Path
    receipt = json.loads((Path(__file__).parent / 'fixtures/usgs/waterdata_continuous.json').read_text())
    result = adapter._normalize(pd.DataFrame(receipt['records']), '01646500', '00060', '00011')
    assert len(result) == 5
    assert result.index[0] == pd.Timestamp('2024-01-01T00:00:00Z')
    assert result.index[-1] == pd.Timestamp('2024-01-01T01:00:00Z')
    assert result['01646500_00060'].iloc[0] == 9640.0
    assert result['01646500_00060_cd'].eq('A').all()


def test_missing_dependency_has_actionable_upgrade_message(monkeypatch):
    import sys
    from types import ModuleType
    monkeypatch.setitem(sys.modules, 'dataretrieval', ModuleType('dataretrieval'))
    with pytest.raises(ImportError, match='dataretrieval>=1.4'):
        adapter._backend()


def test_ic_rejects_records_outside_exact_tolerance(service):
    from ras_commander.usgs.initial_conditions import InitialConditions
    with pytest.raises(ValueError, match='No flow data'):
        InitialConditions.get_ic_value_from_usgs('01646500', '2024-01-01 01:15:00', tolerance_hours=0)


def test_modern_peak_flow_pagination_dates_units_and_qualifiers(monkeypatch):
    import io
    import json
    from ras_commander.usgs.study import UsgsGaugeStudy
    from urllib.parse import parse_qs, urlsplit
    waits, queries = [], []
    monkeypatch.setattr(adapter, "_wait", lambda: waits.append(1))
    def row(year, month, day, value):
        return {"type": "Feature", "properties": {
            "monitoring_location_id": "USGS-01646500", "parameter_code": "00060",
            "unit_of_measure": "ft^3/s", "year": year, "month": month, "day": day,
            "value": value, "water_year": year, "qualifier": ["e"],
        }}
    pages = [dict(type="FeatureCollection", features=[row(2023, 4, 5, 100)], links=[
        dict(rel="next", href="?f=json&offset=1")]),
        dict(type="FeatureCollection", features=[row(2024, 4, 5, 200), row(2024, None, None, 300)], links=[])]
    def fetch(url, timeout):
        assert timeout == 60
        queries.append(url)
        return io.BytesIO(json.dumps(pages[len(queries) - 1]).encode())
    frame = UsgsGaugeStudy.retrieve_peak_flow_data("01646500", "2023-01-01", "2024-12-31", fetch)
    assert len(waits) == 2
    assert parse_qs(urlsplit(queries[0]).query)["parameter_code"] == ["00060"]
    assert frame["value"].tolist() == [100, 200]
    assert frame["datetime"].dt.strftime("%Y-%m-%d").tolist() == ["2023-04-05", "2024-04-05"]
    assert frame["qualifier"].tolist() == [["e"], ["e"]]
    assert "gage_height_ft" not in frame
    assert frame.attrs["units"] == "cfs"


@pytest.mark.parametrize("change", [dict(unit_of_measure="m^3/s"), dict(parameter_code="00065"),
    dict(monitoring_location_id="USGS-00000000")])
def test_peak_flow_rejects_unexpected_units_parameter_or_site(monkeypatch, change):
    import io, json
    from ras_commander.usgs.study import UsgsGaugeStudy
    monkeypatch.setattr(adapter, "_wait", lambda: None)
    record = dict(monitoring_location_id="USGS-01646500", parameter_code="00060",
        unit_of_measure="ft^3/s", year=2024, month=1, day=1, value=100)
    record.update(change)
    page = dict(type="FeatureCollection", features=[dict(properties=record)])
    with pytest.raises(ValueError, match="unexpected"):
        UsgsGaugeStudy.retrieve_peak_flow_data("01646500", urlopen_func=lambda *a, **kw: io.BytesIO(json.dumps(page).encode()))


def test_peak_flow_rejects_external_pagination_before_fetch(monkeypatch):
    import io, json
    from ras_commander.usgs.study import UsgsGaugeStudy
    monkeypatch.setattr(adapter, "_wait", lambda: None)
    page = dict(type="FeatureCollection", features=[], links=[dict(rel="next", href="https://example.org/data")])
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(json.dumps(page).encode())
    with pytest.raises(ValueError, match="official peaks collection"):
        UsgsGaugeStudy.retrieve_peak_flow_data("01646500", urlopen_func=fetch)
    assert len(calls) == 1


def test_recorded_usgs_observations_align_in_utc_across_dst():
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/usgs/waterdata_utc_comparison.json").read_text())
    for case in fixture["cases"]:
        assert case["unmatched"] == case["different"] == 0
        rows = pd.DataFrame(case["rows"])
        rows["datetime"] = rows.pop("index")
        assert rows["legacy"].equals(rows["modern"])
        frame = pd.DataFrame({"time": rows["datetime"], "value": rows["modern"],
            "monitoring_location_id": f"USGS-{case['site']}", "parameter_code": "00060",
            "statistic_id": "00011", "unit_of_measure": "ft^3/s", "approval_status": "Approved"})
        result = adapter._normalize(frame, case["site"], "00060", "00011")
        assert result.index.equals(pd.DatetimeIndex(pd.to_datetime(rows["datetime"], utc=True), name="datetime"))
        assert result[f"{case['site']}_00060"].tolist() == rows["legacy"].tolist()


def test_core_rate_limits_once_per_actual_request(service, monkeypatch):
    from ras_commander.usgs import core
    waits = []
    monkeypatch.setattr(core, "_apply_rate_limit", lambda: waits.append(1))
    monkeypatch.setattr(adapter, "_wait", lambda: core._apply_rate_limit())
    _, calls = service
    result = RasUsgsCore.retrieve_flow_data("01646500", "2024-01-01", "2024-01-01")
    assert not result.empty
    assert len(calls) == len(waits) == 1
