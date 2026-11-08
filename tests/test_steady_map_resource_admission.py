"""Unsupported aggregate scheduler controls refuse before mapper mutation."""
import pytest

from ras_commander import RasProcess
from ras_commander.RasterPerformance import StoreMapPerformanceOptions
from test_steady_profile_stored_maps import _configure_engine, ras_process_module


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


@pytest.mark.parametrize("cpu_limit", [2, 64])
def test_steady_wine_cpu_conflict_refuses_before_writes_or_launch(
    monkeypatch, tmp_path, cpu_limit,
):
    project, mapper, _ = _configure_engine(monkeypatch, tmp_path)
    before = mapper.read_bytes()
    launched = []
    monkeypatch.setattr(ras_process_module, "_is_wine_helper_runtime", lambda: True)
    monkeypatch.setattr(
        ras_process_module, "run_store_all_maps_helper",
        lambda **kwargs: launched.append(kwargs),
    )
    destination = tmp_path / "maps"
    with pytest.raises(ValueError, match="Wine.*one CPU"):
        RasProcess.store_maps_at_steady_profiles(
            "01", ras_object=project, output_path=destination,
            performance=StoreMapPerformanceOptions(native_cpu_limit=cpu_limit),
        )
    assert not launched
    assert not destination.exists()
    assert mapper.read_bytes() == before
