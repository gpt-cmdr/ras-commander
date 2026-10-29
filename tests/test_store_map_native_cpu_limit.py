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
    monkeypatch.setattr(helper, "_run_store_map_process", run)
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


@pytest.mark.parametrize("aggregate", [False, True])
def test_native_windows_routes_use_preclr_launcher(monkeypatch, tmp_path, aggregate):
    monkeypatch.setattr(helper, "_IS_LINUX", False)
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: {})
    seen = []
    def run(cmd, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(helper, "_run_store_map_process", run)
    common = dict(helper_path=tmp_path / "helper.exe", hecras_dir=tmp_path,
        helper_mode="horizontal", result_hdf_path=tmp_path / "result.hdf",
        timeout=30, working_dir=tmp_path, native_cpu_limit=1)
    if aggregate:
        helper._run_store_all_maps_once(rasmap_path=tmp_path / "test.rasmap", **common)
    else:
        helper._run_store_map_once(map_type="Depth", profile_name="Max", output_base_path=None, **common)
    assert seen[0]["native_cpu_limit"] == 1


def test_cpu_mask_never_expands_inherited_cpus():
    assert helper._select_native_cpu_mask(0b101100, 0b111111, 2) == 0b001100
    with pytest.raises(ValueError, match="exceeds"):
        helper._select_native_cpu_mask(0b1000, 0b1111, 2)
    for inherited, system in [(0, 0b1111), (0b10000, 0b1111)]:
        with pytest.raises(RuntimeError, match="unambiguous"):
            helper._select_native_cpu_mask(inherited, system, 1)


@pytest.mark.parametrize("failure", [None, "configure", "timeout"])
def test_suspended_child_order_and_failure_cleanup(monkeypatch, failure):
    monkeypatch.setattr(helper.platform, "system", lambda: "Windows")
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    events = []
    class Child:
        pid = 123
        returncode = 0
        calls = 0
        def __enter__(self): return self
        def __exit__(self, *args): events.append("closed")
        def communicate(self, timeout=None):
            events.append("communicate")
            self.calls += 1
            if failure == "timeout" and self.calls == 1:
                raise subprocess.TimeoutExpired(["helper"], timeout)
            return "stdout", "stderr"
        def kill(self): events.append("killed")
    def popen(cmd, **kwargs):
        assert kwargs["creationflags"] == 0x4
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.PIPE
        assert "timeout" not in kwargs and "capture_output" not in kwargs
        events.append("created suspended")
        return Child()
    def configure(pid, limit):
        assert (pid, limit) == (123, 1)
        events.append("configured/resumed")
        if failure == "configure": raise OSError("cannot set affinity")
    monkeypatch.setattr(helper.subprocess, "Popen", popen)
    monkeypatch.setattr(helper, "_configure_suspended_child", configure)
    if failure:
        error = OSError if failure == "configure" else subprocess.TimeoutExpired
        with pytest.raises(error) as caught:
            helper._run_store_map_process(["helper"], native_cpu_limit=1,
                capture_output=True, text=True, timeout=30, env={})
        assert events[-3:] == ["killed", "communicate", "closed"]
        if failure == "timeout": assert caught.value.stdout == "stdout"
    else:
        result = helper._run_store_map_process(["helper"], native_cpu_limit=1,
            capture_output=True, text=True, timeout=30, env={})
        assert (result.returncode, result.stdout, result.stderr) == (0, "stdout", "stderr")
        assert events == ["created suspended", "configured/resumed", "communicate", "closed"]


@pytest.mark.skipif(os.name != "nt", reason="Win32 suspended process launch")
def test_child_affinity_is_set_before_user_code_without_changing_parent():
    import json
    import sys
    import psutil
    parent = psutil.Process()
    before = parent.cpu_affinity()
    result = helper._run_store_map_process([sys.executable, "-c",
        "import json,psutil; print(json.dumps(psutil.Process().cpu_affinity()))"],
        native_cpu_limit=1, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [min(before)]
    assert parent.cpu_affinity() == before


@pytest.mark.skipif(os.name != "nt", reason="packaged CLR helper launch requires Windows")
def test_packaged_clr_helper_observes_prestartup_affinity(monkeypatch, tmp_path):
    # Invalid runtime directory stops before vendor loading. The CPU diagnostic
    # runs first, so this checks CLR startup without an installed HEC-RAS runtime.
    executable = Path(__file__).resolve().parents[1] / "ras_commander/native/RasStoreMapHelper.exe"
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: dict(os.environ))
    result = helper._run_store_all_maps_once(executable, tmp_path, "horizontal",
        tmp_path / "missing.rasmap", tmp_path / "missing.hdf", 30, tmp_path,
        native_cpu_limit=1)
    assert result.returncode == 2
    assert "thread_pool_min=1/1" in result.stdout, result.stdout + result.stderr
    assert "selected=0x" in result.stdout
