"""Unsupported aggregate scheduler controls refuse before mapper mutation."""
import pytest

from ras_commander import RasProcess
from ras_commander.RasterPerformance import StoreMapPerformanceOptions
from test_steady_profile_stored_maps import _configure_engine


@pytest.mark.parametrize("options,error", [
    ({"gdal_cachemax_mb": 128}, TypeError),
    (StoreMapPerformanceOptions(max_workers=2), ValueError),
    (StoreMapPerformanceOptions(reserve_memory_mb=1), ValueError),
])
def test_steady_resource_options_refuse_before_writes(monkeypatch, tmp_path, options, error):
    project, mapper, _ = _configure_engine(monkeypatch, tmp_path)
    before = mapper.read_bytes()
    with pytest.raises(error, match="performance|scheduler"):
        RasProcess.store_maps_at_steady_profiles("01", ras_object=project, performance=options)
    assert mapper.read_bytes() == before
