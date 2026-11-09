"""Enforced job commit limits and inherited-child cleanup without HEC-RAS."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time

import psutil
import pytest

from ras_commander import _native_helper as helper


@pytest.fixture(scope="module")
def memory_binary(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Native Windows jobs required")
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        pytest.skip(".NET Framework compiler unavailable")
    source = Path(helper.__file__).parent / "native/RasStoreMapHelper.cs"
    target = tmp_path_factory.mktemp("memory-job") / "helper.exe"
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64",
                    f"/out:{target}", str(source)], check=True, capture_output=True, text=True, timeout=30)
    return target


def run_probe(binary, mib=128, scenario=None, timeout=15):
    command = [str(binary), "--Mode", "JobMemoryLimitProbe", "--MemoryLimitMiB", str(mib)]
    if scenario is not None:
        command.extend(["--ProbeScenario", scenario])
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def assert_children_gone(output):
    if isinstance(output, bytes):
        output = output.decode()
    pids = [int(value) for value in re.findall(r"NATIVE_JOB_MEMORY_PROBE_CHILD_PID=(\d+)", output)]
    assert pids, output
    deadline = time.monotonic() + 5
    while any(psutil.pid_exists(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.025)
    assert not any(psutil.pid_exists(pid) for pid in pids)


@pytest.mark.parametrize("mib", [96, 128])
def test_actual_cap_readback_no_hec(memory_binary, mib):
    result = helper._probe_helper_job_memory_limit(memory_binary, mib)
    assert result["limit_mib"] == mib
    assert result["helper_sha256"] == hashlib.sha256(memory_binary.read_bytes()).hexdigest()
    assert "NATIVE_JOB_MEMORY_HEC_ASSEMBLIES_LOADED=False" in result["stdout"]
    peak = int(re.search(r"NATIVE_JOB_MEMORY_PEAK_COMMIT_BYTES=(\d+)", result["stdout"])[1])
    assert 0 < peak <= mib * 1024**2


@pytest.mark.parametrize("mib", [96, 128])
def test_parent_and_child_share_aggregate_commit_cap(memory_binary, mib):
    result = run_probe(memory_binary, mib, "Aggregate")
    assert result.returncode == 0, result.stderr
    assert "NATIVE_JOB_MEMORY_CHILD_MEMBER=True" in result.stdout
    assert "NATIVE_JOB_MEMORY_PARENT_COMMITTED_MIB=16" in result.stdout
    assert "NATIVE_JOB_MEMORY_ALLOCATION_REFUSED=True" in result.stdout
    committed = int(re.search(r"CHILD_COMMITTED_MIB=(\d+)", result.stdout)[1])
    assert 0 < committed < mib - 16
    assert "NATIVE_JOB_MEMORY_CHILDREN_EXITED=True" in result.stdout
    assert_children_gone(result.stdout)
    child_only = run_probe(memory_binary, mib, "ChildOnly")
    assert child_only.returncode == 0, child_only.stderr
    alone_committed = int(re.search(r"CHILD_COMMITTED_MIB=(\d+)", child_only.stdout)[1])
    # The parent's extra16MiB reduces the child's available commitment by the
    # same amount, within one4MiB chunk of runtime bookkeeping variability.
    assert 12 <= alone_committed - committed <= 20
    assert_children_gone(child_only.stdout)


def test_nested_job_is_verified_and_completes_cleanly(memory_binary):
    result = run_probe(memory_binary, 128, "Nested")
    assert result.returncode == 0, result.stderr
    assert "NATIVE_JOB_MEMORY_NESTED=True" in result.stdout
    assert result.stdout.count("NATIVE_JOB_MEMORY_CHILDREN_EXITED=True") == 2


def test_failure_closes_job_and_kills_only_owned_child(memory_binary):
    unrelated = subprocess.Popen([str(memory_binary), "--Mode", "JobMemoryLimitChild", "Sleep", "128"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = run_probe(memory_binary, 128, "Failure")
        assert result.returncode == 99
        assert "NATIVE_JOB_MEMORY_PEAK_COMMIT_BYTES=" in result.stdout
        assert "NATIVE_JOB_MEMORY_CHILDREN_EXITED=True" not in result.stdout
        assert_children_gone(result.stdout)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


@pytest.mark.parametrize("cpu_limit", [None, 1])
def test_timeout_kills_inherited_job_tree(memory_binary, cpu_limit):
    command = [str(memory_binary), "--Mode", "JobMemoryLimitProbe", "--MemoryLimitMiB", "128",
               "--ProbeScenario", "Timeout"]
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        helper._run_store_map_process(command, native_cpu_limit=cpu_limit,
                                      capture_output=True, text=True, timeout=1.5)
    assert_children_gone(caught.value.stdout)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "128", 1_048_577])
def test_invalid_cap_refused_before_packaged_helper(monkeypatch, value):
    monkeypatch.setattr(helper, "packaged_helper_executable_path", lambda: pytest.fail("must refuse first"))
    with pytest.raises(ValueError, match="integer"):
        helper.probe_native_job_memory_limit(value)


def test_unsupported_old_binary_cannot_supply_cap_proof(monkeypatch, tmp_path):
    binary = tmp_path / "old.exe"
    binary.write_bytes(b"identity")
    monkeypatch.setattr(helper.platform, "system", lambda: "Windows")
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    monkeypatch.setattr(helper.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "RESULT_SUCCESS=True", ""))
    with pytest.raises(RuntimeError, match="probe failed before model"):
        helper._probe_helper_job_memory_limit(binary, 128)


def test_default_child_environment_clears_inherited_cap(monkeypatch):
    env = {"RAS_COMMANDER_STORE_MAP_JOB_MEMORY_LIMIT_MIB": "128"}
    helper._apply_gdal_performance_env(env, 1, None, None)
    assert "RAS_COMMANDER_STORE_MAP_JOB_MEMORY_LIMIT_MIB" not in env


def test_cap_requires_serial_boundary_before_any_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_probe_helper_job_memory_limit", lambda *a, **k: pytest.fail("must refuse first"))
    with pytest.raises(ValueError, match="requires native_polygon_serial"):
        helper.run_store_map_helper(tmp_path, "sloping", "Depth", tmp_path / "model.hdf", "Max",
                                    native_job_memory_limit_mb=128)


def test_exact_selected_binary_probed_before_capped_mapping(monkeypatch, tmp_path):
    binary = tmp_path / "helper.exe"
    terrain = tmp_path / "terrain.hdf"
    binary.write_bytes(b"not executed")
    terrain.write_bytes(b"not executed")
    events = []

    @contextmanager
    def packaged():
        yield binary

    monkeypatch.setattr(helper, "packaged_helper_executable_path", packaged)
    monkeypatch.setattr(helper, "_IS_LINUX", False)
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: {})
    monkeypatch.setattr(helper, "validate_native_job_memory_runtime", lambda _: {
        "version": "synthetic", "sha256": {"Utility.Core.dll": "synthetic-hash"}})
    monkeypatch.setattr(helper, "_probe_helper_job_memory_limit", lambda path, limit: events.append(("probe", path, limit)))

    def run(command, **kwargs):
        events.append(("map", command[0], kwargs["env"]["RAS_COMMANDER_STORE_MAP_JOB_MEMORY_LIMIT_MIB"]))
        return subprocess.CompletedProcess(command, 0,
            "NATIVE_JOB_MEMORY_LIMIT_EFFECTIVE_MIB=128\nNATIVE_JOB_MEMORY_CHILDREN_EXITED=True\n"
            "NATIVE_JOB_MEMORY_UTILITY_CORE_SHA256=synthetic-hash\n"
            "NATIVE_JOB_MEMORY_CONTAINMENT_POLICY=direct_create_process_no_shell_no_breakaway\n", "")

    monkeypatch.setattr(helper, "_run_store_map_process", run)
    helper.run_store_map_helper(tmp_path, "sloping", "Depth", tmp_path / "model.hdf", "Max",
                                native_polygon_serial=True, terrain_hdf_path=terrain,
                                native_job_memory_limit_mb=128)
    assert events == [("probe", binary, 128), ("map", str(binary), "128")]


def test_unknown_native_launch_chain_refused_without_execution(tmp_path):
    for name in ("RasMapperLib.dll", "Utility.Core.dll", "RasProcess.exe"):
        (tmp_path / name).write_bytes(b"unverified")
    with pytest.raises(ValueError, match="independently verified"):
        helper.validate_native_job_memory_runtime(tmp_path)


@pytest.mark.parametrize("version", ["6.6", "7.0.1"])
def test_pinned_installed_launch_chain_identity_only(version):
    runtime = Path("C:/Program Files (x86)/HEC/HEC-RAS") / version
    if not runtime.is_dir():
        pytest.skip("External pinned runtime not installed")
    proof = helper.validate_native_job_memory_runtime(runtime)
    assert proof["version"] == version
    assert proof["launch_contract"] == "direct_create_process_no_shell_no_breakaway"


def test_actual_capped_helper_refuses_unknown_runtime_before_assembly_load(memory_binary, tmp_path):
    for name in ("RasMapperLib.dll", "Utility.Core.dll", "RasProcess.exe", "terrain.hdf"):
        (tmp_path / name).write_bytes(b"unverified-not-an-assembly")
    env = dict(os.environ, RAS_COMMANDER_STORE_MAP_JOB_MEMORY_LIMIT_MIB="128",
               RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL="1",
               RAS_COMMANDER_STORE_MAP_TERRAIN_HDF=str(tmp_path / "terrain.hdf"))
    result = subprocess.run([str(memory_binary), str(tmp_path), "sloping", "StoreMap", "Depth",
                             str(tmp_path / "absent-plan.hdf"), "Max"],
                            capture_output=True, text=True, timeout=10, env=env)
    assert "independently verified native launch chain" in result.stderr
    assert "BadImageFormatException" not in result.stderr
    assert "NATIVE_JOB_MEMORY_CHILDREN_EXITED=True" not in result.stdout


@pytest.fixture(scope="module")
def runtime_identity_harness(memory_binary, tmp_path_factory):
    folder = tmp_path_factory.mktemp("memory-runtime-reflection")
    source = folder / "Probe.cs"
    source.write_text('''using System;
using System.Reflection;
class Probe {
 static int Main(string[] args) {
  Type t=Assembly.LoadFrom(args[0]).GetType("RasStoreMapHelper", true);
  t.GetField("_hecrasDir",BindingFlags.Static|BindingFlags.NonPublic).SetValue(null,args[1]);
  try {t.GetMethod("ValidateMemoryRuntime",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,null);return 0;}
  catch(TargetInvocationException e){Console.Error.WriteLine(e.InnerException);return 3;}
 }
}''', encoding="utf-8")
    target = folder / "Probe.exe"
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/platform:x64", f"/out:{target}", str(source)],
                   check=True, capture_output=True, text=True, timeout=30)
    return target


@pytest.mark.parametrize("version", ["6.6", "7.0.1"])
def test_clr_loaded_utility_identity_no_model(runtime_identity_harness, memory_binary, version):
    runtime = Path("C:/Program Files (x86)/HEC/HEC-RAS") / version
    if not runtime.is_dir():
        pytest.skip("External pinned runtime not installed")
    proof = helper.validate_native_job_memory_runtime(runtime)
    result = subprocess.run([str(runtime_identity_harness), str(memory_binary), str(runtime)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert f"NATIVE_JOB_MEMORY_UTILITY_CORE_SHA256={proof['sha256']['Utility.Core.dll']}" in result.stdout
    assert "NATIVE_JOB_MEMORY_CONTAINMENT_POLICY=direct_create_process_no_shell_no_breakaway" in result.stdout
