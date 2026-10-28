import sys
import types

import pandas as pd

from ras_commander.hdf.HdfProject import HdfProject
from ras_commander.usgs.spatial import UsgsGaugeSpatial


def test_find_gauges_in_project_forwards_extent_element_flags(tmp_path, monkeypatch):
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"")
    seen = {}

    def fake_project_bounds(
        path,
        buffer_percent,
        include_1d,
        include_2d,
        include_storage,
        project_crs=None,
    ):
        seen["extent"] = {
            "path": path,
            "buffer_percent": buffer_percent,
            "include_1d": include_1d,
            "include_2d": include_2d,
            "include_storage": include_storage,
            "project_crs": project_crs,
        }
        return (-78.0, 40.0, -77.0, 41.0)

    def fake_monitoring_locations(**kwargs):
        seen["query"] = kwargs
        return (
            pd.DataFrame(
                {
                    "site_no": ["01500000"],
                    "monitoring_location_id": ["USGS-01500000"],
                    "station_nm": ["Example Creek near Test"],
                    "site_type_code": ["ST"],
                    "site_status": ["Active"],
                    "dec_lat_va": [40.5],
                    "dec_long_va": [-77.5],
                }
            ),
            {},
        )

    fake_waterdata = types.ModuleType("waterdata")
    fake_waterdata.get_monitoring_locations = fake_monitoring_locations
    fake_waterdata.get_time_series_metadata = lambda **kw: (pd.DataFrame({
        "monitoring_location_id": ["USGS-01500000"], "parameter_code": ["00060"],
        "end": [(pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=1)).isoformat()],
    }), {})
    fake_dataretrieval = types.ModuleType("dataretrieval")
    fake_dataretrieval.waterdata = fake_waterdata

    monkeypatch.setattr(HdfProject, "get_project_bounds_latlon", fake_project_bounds)
    monkeypatch.setitem(sys.modules, "dataretrieval", fake_dataretrieval)
    monkeypatch.setitem(sys.modules, "dataretrieval.waterdata", fake_waterdata)

    gauges = UsgsGaugeSpatial.find_gauges_in_project(
        hdf_path,
        buffer_percent=0.0,
        active_only=True,
        project_crs="EPSG:2271",
        include_1d=False,
        include_2d=True,
        include_storage=False,
    )

    assert seen["extent"] == {
        "path": hdf_path,
        "buffer_percent": 0.0,
        "include_1d": False,
        "include_2d": True,
        "include_storage": False,
        "project_crs": "EPSG:2271",
    }
    assert seen["query"] == {
        "bbox": [-78.0, 40.0, -77.0, 41.0],
        "site_type_code": "ST",
        "agency_code": "USGS",
    }
    assert gauges.crs == "EPSG:4326"
    assert gauges["site_no"].tolist() == ["01500000"]



def test_modern_discovery_filters_requested_series_by_recency(monkeypatch):
    from ras_commander.usgs import _waterdata_adapter as adapter
    monkeypatch.setattr(adapter, "_wait", lambda: None)
    now = pd.Timestamp.now(tz="UTC")
    ids = ["USGS-01646500", "USGS-08158000", "USGS-01500000"]
    calls = []
    api = types.SimpleNamespace(
        get_monitoring_locations=lambda **kw: (pd.DataFrame({"monitoring_location_id": ids}), {}),
    )
    def metadata(**kw):
        calls.append(kw)
        return pd.DataFrame({"monitoring_location_id": ids, "parameter_code": ["00060", "00065", "00060"],
            "end": [(now-pd.Timedelta(days=d)).isoformat() for d in [1, 1, 184]]}), {}
    api.get_time_series_metadata = metadata
    found = UsgsGaugeSpatial._query_modern_sites(-80, 30, -70, 40, "ST", "00060", True, api)
    assert found["monitoring_location_id"].tolist() == [ids[0]]
    assert calls == [{"monitoring_location_id": ids, "parameter_code": ["00060"]}]
    found = UsgsGaugeSpatial._query_modern_sites(-80, 30, -70, 40, "ST", "00060", False, api)
    assert found["monitoring_location_id"].tolist() == [ids[0], ids[2]]


def test_modern_discovery_batches_and_rate_limits(monkeypatch):
    from ras_commander.usgs import _waterdata_adapter as adapter
    waits, sizes = [], []
    monkeypatch.setattr(adapter, "_wait", lambda: waits.append(1))
    ids = [f"USGS-{i:08d}" for i in range(101)]
    api = types.SimpleNamespace(get_monitoring_locations=lambda **kw: (pd.DataFrame({"monitoring_location_id": ids}), {}))
    def metadata(**kw):
        sizes.append(len(kw["monitoring_location_id"]))
        return pd.DataFrame({"monitoring_location_id": kw["monitoring_location_id"], "parameter_code": "00060"}), {}
    api.get_time_series_metadata = metadata
    found = UsgsGaugeSpatial._query_modern_sites(-80, 30, -70, 40, "ST", "00060", False, api)
    assert len(found) == 101
    assert sizes == [50, 50, 1]
    assert len(waits) == 4
