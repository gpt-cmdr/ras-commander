"""Synthetic admission tests; no native helper or model is executed."""
from dataclasses import fields
from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import RasProcess, StoreMapPerformanceOptions
from ras_commander.RasterPerformance import StoreMapResourceEstimate, SystemMemorySnapshot

module = import_module("ras_commander.RasProcess")
helper = import_module("ras_commander._native_helper")


def options(**kwargs):
    values = dict(native_polygon_serial=True, native_job_memory_limit_mb=8192)
    values.update(kwargs)
    return StoreMapPerformanceOptions(**values)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "8192", 1048577])
def test_cap_requires_bounded_strict_integer(value):
    with pytest.raises(ValueError, match="native_job_memory_limit_mb"):
        options(native_job_memory_limit_mb=value)


@pytest.mark.parametrize("value", [1, 1048576])
def test_cap_accepts_inclusive_bounds(value):
    assert options(native_job_memory_limit_mb=value).native_job_memory_limit_mb == value


@pytest.mark.parametrize("kwargs", [dict(native_polygon_serial=False), dict(max_workers=None),
    dict(max_workers=2), dict(memory_policy="warn"), dict(memory_policy="ignore"),
    dict(worker_memory_override_mb=1024)])
def test_cap_requires_single_enforced_serial_helper(kwargs):
    with pytest.raises(ValueError, match="native_job_memory_limit_mb"):
        options(**kwargs)


def test_default_serialization_retains_exact_original_keys():
    payload = StoreMapPerformanceOptions().to_dict()
    assert set(payload) == {f.name for f in fields(StoreMapPerformanceOptions)} - {"native_job_memory_limit_mb"}
    assert options().to_dict()["native_job_memory_limit_mb"] == 8192


@pytest.mark.parametrize("system,wine,maps", [
    ("Linux", False, ("inundation_boundary",)), ("Windows", True, ("inundation_boundary",)),
    ("Windows", False, ("depth",)), ("Windows", False, ("inundation_boundary", "wse"))])
def test_cap_route_rejects_unsupported_platform_or_products(monkeypatch, system, wine, maps):
    monkeypatch.setattr(module.platform, "system", lambda: system)
    with pytest.raises(ValueError):
        module._validate_native_job_cap_route(options(), maps, wine_runtime=wine)


def test_default_route_never_checks_platform(monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: pytest.fail("default platform check"))
    module._validate_native_job_cap_route(StoreMapPerformanceOptions(), ("depth",))


@pytest.mark.parametrize("change", [dict(limit_mib=8193), dict(limit_mib=True),
    dict(stdout="NATIVE_JOB_MEMORY_LIMIT_EFFECTIVE_MIB=81920"), dict(helper_sha256="bad")])
def test_preflight_rejects_inconsistent_proof(monkeypatch, change):
    proof = dict(limit_mib=8192, helper_sha256="a" * 64,
                 stdout="NATIVE_JOB_MEMORY_LIMIT_EFFECTIVE_MIB=8192\n")
    proof.update(change)
    monkeypatch.setattr(helper, "probe_native_job_memory_limit", lambda *a, **k: proof)
    with pytest.raises(RuntimeError, match="preflight proof"):
        module._preflight_native_job_cap(8192)


def test_preflight_forwards_exact_cap_and_bounded_timeout(monkeypatch):
    proof = dict(limit_mib=8192, helper_sha256="a" * 64,
                 stdout="NATIVE_JOB_MEMORY_LIMIT_EFFECTIVE_MIB=8192\n")
    calls = []
    monkeypatch.setattr(helper, "probe_native_job_memory_limit",
                        lambda *a, **k: calls.append((a, k)) or proof)
    assert module._preflight_native_job_cap(8192) == proof
    assert calls == [((8192,), dict(timeout=15))]


def test_cap_estimate_reserves_cap_not_full_grid_or_gdal_twice(monkeypatch, tmp_path):
    (tmp_path / "Demo.p01.hdf").write_bytes(b"plan")
    terrain = tmp_path / "terrain.hdf"
    terrain.write_bytes(b"terrain")
    rasmap = tmp_path / "Demo.rasmap"
    rasmap.write_bytes(b"<RASMapper />")
    ras = SimpleNamespace(project_folder=tmp_path, project_name="Demo", ras_version="6.6",
                          ras_exe_path=tmp_path / "hecras/Ras.exe", check_initialized=lambda: None)
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_is_wine_helper_runtime", lambda: False)
    monkeypatch.setattr(helper, "validate_native_job_memory_runtime", lambda _: {"runtime_id": "6.6"})
    monkeypatch.setattr(helper, "probe_native_job_memory_limit", lambda *a, **k: pytest.fail("metadata-only estimate"))
    monkeypatch.setattr(module.RasMap, "get_rasmap_path", lambda _: rasmap)
    monkeypatch.setattr(module.RasMap, "list_terrain_layers", lambda *a, **k:
                        pd.DataFrame([dict(name="selected", resolved_path=str(terrain))]))
    monkeypatch.setattr(RasProcess, "_get_projection_info", lambda _: module.ProjectionInfo(None, None))
    monkeypatch.setattr(module, "_terrain_resource_estimates", lambda _: ((), ()))
    monkeypatch.setattr(module, "get_system_memory_snapshot", lambda: SystemMemorySnapshot(32768, 30000, 2000, 40000))
    result = RasProcess.estimate_store_map_resources("01", ("inundation_boundary",),
        terrain_name="selected", ras_object=ras, performance=options(gdal_cachemax_mb=512))
    assert type(result) is StoreMapResourceEstimate
    assert result.estimated_worker_private_mb == 8192
    assert result.effective_reserve_mb == 8192
    assert result.memory_limit == 2
    assert result.estimate_source == "native_job_cap"
    assert result.native_job_memory_limit_bytes == 8192 * 1024**2
    assert result.source_scope["selected_terrain"]["terrain_hdf"] == str(terrain.resolve())
    assert result.source_scope["native_runtime"] == {"runtime_id": "6.6"}
    assert result.native_job_preflight is None
    assert "native_job_preflight" not in result.to_dict()
    assert "not RSS" in result.memory_measure
