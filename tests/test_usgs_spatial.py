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
    }
    assert gauges.crs == "EPSG:4326"
    assert gauges["site_no"].tolist() == ["01500000"]


def test_legacy_site_service_parses_rdb_and_rounds_bbox(monkeypatch):
    seen = {}

    class FakeResponse:
        text = """# comment
agency_cd\tsite_no\tstation_nm\tsite_tp_cd\tdec_lat_va\tdec_long_va
5s\t15s\t50s\t7s\t16s\t16s
USGS\t04107850\tKALAMAZOO RIVER NEAR ALLEGAN, MI\tST\t42.48225575\t-85.798355
"""

        def raise_for_status(self):
            return None

    def fake_get(url, params, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("ras_commander.usgs.spatial.requests.get", fake_get)

    df = UsgsGaugeSpatial._query_legacy_site_service(
        west=-85.867758123,
        south=42.475847456,
        east=-85.790666789,
        north=42.533323012,
        site_type="ST",
        param_codes="00060,00065",
        active_only=False,
    )

    assert seen["url"] == "https://waterservices.usgs.gov/nwis/site/"
    assert (
        seen["params"]["bBox"]
        == "-85.8677581,42.4758475,-85.7906668,42.5333230"
    )
    assert seen["params"]["parameterCd"] == "00060,00065"
    assert seen["params"]["siteStatus"] == "all"
    assert df["site_no"].tolist() == ["04107850"]
