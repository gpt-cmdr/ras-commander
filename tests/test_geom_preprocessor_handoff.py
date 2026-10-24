"""A second native pass must not start over a live tree or locked tmp HDF."""

import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from ras_commander import GeomPreprocessor as GP
from ras_commander import RasPreprocess


def paths(tmp_path):
    return (
        tmp_path / "Synthetic.prj",
        tmp_path / "Synthetic.p01",
        tmp_path / "Synthetic.p01.tmp.hdf",
    )


def guard(tmp_path, timeout=0):
    project, plan, temporary = paths(tmp_path)
    GP._wait_for_previous_native_exit(
        project, plan, temporary, paths_to_clear=[temporary], timeout_seconds=timeout
    )


def lock_hdf(path):
    # Use an actual child process and actual HDF lock. No HEC-RAS installation
    # is needed to reproduce the file-sharing part of the native handoff.
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                'import h5py,sys; f=h5py.File(sys.argv[1],"w"); '
                'f.create_dataset("synthetic",data=[1]); f.flush(); '
                'print("READY",flush=True); sys.stdin.readline(); f.close()'
            ),
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().strip() == "READY"
    return process


def stop(process):
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    process.wait(timeout=10)
    process.stdout.close()
    process.stderr.close()


def test_locked_hdf_times_out_without_deleting_or_launching(tmp_path, monkeypatch):
    monkeypatch.setattr(RasPreprocess, "_preprocess_process_inventory", list)
    temporary = paths(tmp_path)[2]
    process = lock_hdf(temporary)
    try:
        with pytest.raises(RuntimeError, match="GEOMETRY_PREPROCESS_HANDOFF_TIMEOUT"):
            guard(tmp_path, timeout=0.05)
        assert temporary.exists() and process.poll() is None
    finally:
        stop(process)


def test_handoff_waits_for_actual_hdf_handle_release(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    monkeypatch.setattr(RasPreprocess, "_preprocess_process_inventory", list)
    temporary = paths(tmp_path)[2]
    process = lock_hdf(temporary)
    attempts = []

    def release(_duration):
        assert temporary.exists()
        attempts.append("waited")
        stop(process)

    monkeypatch.setattr(module.time, "sleep", release)
    try:
        guard(tmp_path, timeout=2)
        assert attempts == ["waited"]
        assert not temporary.exists() and process.returncode == 0
    finally:
        if process.poll() is None:
            stop(process)


def test_retains_child_identity_after_previous_launcher_exits(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + 1)
    )
    monkeypatch.setattr(GP, "_is_wine_display_child", lambda process: False)
    project, plan, temporary = paths(tmp_path)
    temporary.write_bytes(b"untouched until previous child exits")
    child = SimpleNamespace(
        pid=22,
        create_time=lambda: 1002,
        is_running=lambda: clock[0] < 3,
        status=lambda: psutil.STATUS_SLEEPING,
    )
    parent = SimpleNamespace(
        pid=21,
        create_time=lambda: 1001,
        is_running=lambda: clock[0] < 1,
        status=lambda: psutil.STATUS_SLEEPING,
        children=lambda **kwargs: [child],
    )
    info = {"cmdline": ["Ras.exe", str(project), str(plan)]}
    monkeypatch.setattr(
        RasPreprocess,
        "_preprocess_process_inventory",
        lambda: [(parent, info)] if clock[0] == 0 else [],
    )
    guard(tmp_path, timeout=5)
    assert clock[0] == 3 and not temporary.exists()


def test_other_project_is_not_waited_or_inspected(tmp_path, monkeypatch):
    other = SimpleNamespace(
        children=lambda **kwargs: pytest.fail("unrelated process inspected")
    )
    monkeypatch.setattr(
        RasPreprocess,
        "_preprocess_process_inventory",
        lambda: [
            (
                other,
                {
                    "cmdline": [
                        "Ras.exe",
                        str(tmp_path / "Other.prj"),
                        str(tmp_path / "Other.p01"),
                    ]
                },
            )
        ],
    )
    guard(tmp_path)


def test_public_api_fails_before_plan_or_geometry_mutation_when_ownership_unknown(
    tmp_path, monkeypatch
):
    lifecycle = runpy.run_path(
        str(Path(__file__).with_name("test_geom_preprocessor_persistence.py"))
    )
    result, launched = lifecycle["project_run"](
        tmp_path,
        monkeypatch,
        previous_process_inventory=None,
        max_wait=0.01,
    )
    assert not result.success
    assert "GEOMETRY_PREPROCESS_HANDOFF_TIMEOUT" in result.error
    assert "ownership is unverified" in result.error
    assert result.timed_out
    assert not launched
    assert not list(tmp_path.glob("*.preprocess-*.bak"))


def test_public_api_does_not_launch_over_previous_locked_tmp_hdf(tmp_path, monkeypatch):
    lifecycle = runpy.run_path(
        str(Path(__file__).with_name("test_geom_preprocessor_persistence.py"))
    )
    temporary = paths(tmp_path)[2]
    process = lock_hdf(temporary)
    try:
        result, launched = lifecycle["project_run"](
            tmp_path,
            monkeypatch,
            max_wait=0.05,
        )
        assert not result.success and result.timed_out
        assert "GEOMETRY_PREPROCESS_HANDOFF_TIMEOUT" in result.error
        assert not launched and temporary.exists() and process.poll() is None
        assert not list(tmp_path.glob("*.preprocess-*.bak"))
    finally:
        stop(process)


def test_stale_file_delete_does_not_warn_and_continue(tmp_path, monkeypatch):
    temporary = paths(tmp_path)[2]
    temporary.touch()
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path == temporary:
            raise PermissionError(32, "Sharing violation", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(PermissionError, match="Sharing violation"):
        GP._delete_files([temporary])
