"""Scoped configuration for the native pipe-rendering race mitigation."""
import os
import subprocess
from pathlib import Path

import pytest

from ras_commander._execution_types import StoreMapPerformanceOptions
from ras_commander import _native_helper as helper


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1", 65])
def test_invalid_limits_fail_before_execution(value):
    with pytest.raises(ValueError, match="native_cpu_limit"):
        StoreMapPerformanceOptions(native_cpu_limit=value)
    with pytest.raises(ValueError, match="native_cpu_limit"):
        helper._apply_gdal_performance_env({}, 1, None, value)


def test_limit_is_scoped_to_child_environment(monkeypatch):
    key = "RAS_COMMANDER_STORE_MAP_CPU_LIMIT"
    monkeypatch.setenv(key, "5")
    env = dict(os.environ)
    helper._apply_gdal_performance_env(env, 1, None, 1)
    assert env[key] == "1"
    assert os.environ[key] == "5"
    helper._apply_gdal_performance_env(env, 1, None)
    assert key not in env
    assert os.environ[key] == "5"


@pytest.mark.parametrize("aggregate", [False, True])
def test_both_child_launch_routes_receive_limit(monkeypatch, tmp_path, aggregate):
    monkeypatch.setattr(helper, "_IS_LINUX", False)
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: {})
    seen = []
    def run(cmd, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(helper.subprocess, "run", run)
    common = dict(helper_path=tmp_path / "helper.exe", hecras_dir=tmp_path,
        helper_mode="horizontal", result_hdf_path=tmp_path / "result.hdf",
        timeout=30, working_dir=tmp_path, native_cpu_limit=1)
    if aggregate:
        helper._run_store_all_maps_once(rasmap_path=tmp_path / "test.rasmap", **common)
    else:
        helper._run_store_map_once(map_type="Depth", profile_name="Max", output_base_path=None, **common)
    assert seen[0]["RAS_COMMANDER_STORE_MAP_CPU_LIMIT"] == "1"


@pytest.mark.skipif(os.name != "nt", reason="packaged .NET Framework helper requires Windows")
def test_packaged_helper_rejects_limit_before_vendor_loading(tmp_path):
    executable = Path(__file__).resolve().parents[1] / "ras_commander/native/RasStoreMapHelper.exe"
    env = dict(os.environ, RAS_COMMANDER_STORE_MAP_CPU_LIMIT="0")
    result = subprocess.run([str(executable), str(tmp_path), "horizontal", "missing.rasmap"], env=env,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "ERROR applying native CPU limit" in result.stderr
    assert "HEC-RAS directory not found" not in result.stderr
