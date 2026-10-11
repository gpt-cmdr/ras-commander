"""Completion regressions with real HDF inventories and controlled processes."""

import importlib
import os
import time
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander.geom.GeomPreprocessor import GeomPreprocessor as GP


def geometry(path):
    with h5py.File(path, "w") as handle:
        handle.attrs["File Type"] = "HEC-RAS Geometry"
        handle.create_dataset("Projection", data=np.bytes_("synthetic projected CRS"))
        mesh = handle.create_group("Geometry/2D Flow Areas")
        mesh.create_dataset("Attributes", data=[1])
        area = mesh.create_group("Synthetic")
        area.create_dataset("Cells Center Coordinate", data=[[1.0, 2.0]])
        area.create_dataset("Faces FacePoint Indexes", data=[[0, 1]])
        handle.create_dataset(
            "Geometry/Land Cover (Manning's n)/Calibration Table", data=[0.04]
        )
        handle["Geometry"].attrs["AutoUpdateParameters"] = True
    return path


def test_inventory_closes_its_handles_and_includes_auxiliary_objects(tmp_path):
    path = geometry(tmp_path / "Synthetic.g01.hdf")
    before = h5py.h5f.get_obj_count(types=h5py.h5f.OBJ_FILE)
    inventory = GP._geometry_hdf_inventory(path)
    assert inventory["Projection"]["kind"] == "dataset"
    assert "AutoUpdateParameters" in inventory["Geometry"]["attributes"]
    assert h5py.h5f.get_obj_count(types=h5py.h5f.OBJ_FILE) == before


def test_open_target_handle_is_rejected_without_closing_callers_file(tmp_path):
    path = geometry(tmp_path / "Synthetic.g01.hdf")
    with h5py.File(path, "r") as handle:
        with pytest.raises(RuntimeError, match="GEOMETRY_HDF_OPEN"):
            GP._require_closed_geometry_hdf(path)
        assert handle.id.valid
    GP._require_closed_geometry_hdf(path)


def test_unrelated_open_hdf_is_allowed(tmp_path):
    path = geometry(tmp_path / "Synthetic.g01.hdf")
    other = geometry(tmp_path / "Other.g01.hdf")
    with h5py.File(other, "r"):
        GP._require_closed_geometry_hdf(path)


def test_inventory_detects_lost_roughness_projection_and_attributes(tmp_path):
    path = geometry(tmp_path / "Synthetic.g01.hdf")
    expected = GP._geometry_hdf_inventory(path)
    with h5py.File(path, "r+") as handle:
        del handle["Projection"]
        del handle["Geometry/Land Cover (Manning's n)/Calibration Table"]
        del handle["Geometry"].attrs["AutoUpdateParameters"]
    actual = GP._geometry_hdf_inventory(path)
    assert GP._missing_geometry_inventory(expected, actual) == [
        "Geometry/Land Cover (Manning's n)/Calibration Table",
        "Geometry@AutoUpdateParameters",
        "Projection",
    ]
    assert GP._geometry_hdf_readiness(path, "unsteady_2d")[0]


def test_native_recomputation_can_change_values_and_add_objects(tmp_path):
    path = geometry(tmp_path / "Synthetic.g01.hdf")
    expected = GP._geometry_hdf_inventory(path)
    with h5py.File(path, "r+") as handle:
        handle["Geometry/2D Flow Areas/Synthetic/Cells Center Coordinate"][...] = [
            [3.0, 4.0]
        ]
        handle.create_dataset("Geometry/New native table", data=[2])
    assert (
        GP._missing_geometry_inventory(expected, GP._geometry_hdf_inventory(path)) == []
    )


def test_flow_start_and_quiet_geometry_do_not_end_monitor(tmp_path, monkeypatch):
    message = tmp_path / "Synthetic.bco01"
    message.write_text("Starting Unsteady Flow Computations")
    polls = iter([None, None, None, 0])
    process = SimpleNamespace(pid=os.getpid(), poll=lambda: next(polls))
    pauses = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    monkeypatch.setattr(
        GP, "_geometry_hdf_readiness", lambda *a, **k: pytest.fail("opened active HDF")
    )
    result = GP._monitor_compute_messages(
        process,
        [message],
        time.time(),
        60,
        ["Starting Unsteady Flow Computations"],
    )
    assert len(pauses) == 3
    assert result == {
        "signal_detected": "Starting Unsteady Flow Computations",
        "timed_out": False,
        "children": (),
        "errors": [],
    }


def test_monitor_timeout_is_not_readiness_success(tmp_path):
    process = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    assert GP._monitor_compute_messages(process, [], time.time() - 2, 1, []) == {
        "signal_detected": None,
        "timed_out": True,
        "children": (),
        "errors": [],
    }


def project_run(tmp_path, monkeypatch, *, exit_code=0, remove=False, timeout=False):
    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    folder = tmp_path
    path = geometry(folder / "Synthetic.g01.hdf")
    plan = folder / "Synthetic.p01"
    plan.write_text("Geom File=g01\nRun UNet=-1\nRun HTab=0\n")
    original = plan.read_bytes()
    prj = folder / "Synthetic.prj"
    prj.write_text("Current Plan=p01\n")
    exe = folder / "Ras.exe"
    exe.touch()
    obj = SimpleNamespace(
        project_folder=folder,
        project_name="Synthetic",
        prj_file=prj,
        ras_exe_path=exe,
        check_initialized=lambda: None,
    )
    monkeypatch.setattr(GP, "_resolve_plan_path", lambda *args: plan)
    monkeypatch.setattr(GP, "_resolve_geometry_number", lambda *args: "01")
    monkeypatch.setattr(GP, "_resolve_flow_type", lambda *args: "unsteady_2d")
    monkeypatch.setattr(
        module.BcoMonitor, "enable_detailed_logging", lambda *args: None
    )
    monkeypatch.setattr(
        module.RasPlan, "set_geom_preprocessor", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(GP, "_read_compute_messages", lambda *args, **kwargs: ([], ""))
    monkeypatch.setattr(GP, "_preprocessor_artifacts", lambda *args, **kwargs: [path])
    monkeypatch.setattr(
        GP, "_wait_for_preprocess_child", lambda **kwargs: {"timed_out": False}
    )
    monkeypatch.setattr(
        GP,
        "_monitor_compute_messages",
        lambda **kwargs: {"timed_out": timeout, "signal_detected": "Diagnostic"},
    )
    killed = []

    def launch(*args, **kwargs):
        assert kwargs["shell"] is False
        assert kwargs["stdout"] is not module.subprocess.PIPE
        assert h5py.h5f.get_obj_count(types=h5py.h5f.OBJ_FILE) == 0
        if remove:
            with h5py.File(path, "r+") as handle:
                del handle["Projection"]
        return SimpleNamespace(
            pid=12345,
            returncode=exit_code,
            poll=lambda: exit_code,
            wait=lambda *args, **kwargs: exit_code,
        )

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(
        GP, "_terminate_process_tree", lambda process: killed.append(process.pid)
    )
    result = GP.run_geometry_preprocessor("01", ras_object=obj, dialog_watchdog=False)
    assert plan.read_bytes() == original
    return result, killed


def test_normal_exit_with_complete_inventory_never_kills(tmp_path, monkeypatch):
    result, killed = project_run(tmp_path, monkeypatch)
    assert result.success and result.return_code == 0
    assert result.missing_geometry_inventory == []
    assert killed == []


def test_nonzero_exit_cannot_be_waived_by_diagnostic_signal(tmp_path, monkeypatch):
    result, killed = project_run(tmp_path, monkeypatch, exit_code=15)
    assert not result.success
    assert "exited with code 15" in result.error
    assert killed == []


def test_populated_mesh_with_inventory_loss_is_failure(tmp_path, monkeypatch):
    result, killed = project_run(tmp_path, monkeypatch, remove=True)
    assert not result.success
    assert result.missing_geometry_inventory == ["Projection"]
    assert "GEOMETRY_INVENTORY_LOST" in result.error
    assert killed == []


def test_timeout_fails_without_opening_postrun_hdf(tmp_path, monkeypatch):
    result, killed = project_run(tmp_path, monkeypatch, timeout=True)
    assert not result.success and result.timed_out
    assert "GEOMETRY_PREPROCESS_TIMEOUT" in result.error
    assert killed == [12345]


def child_record(*, finished=False, exit_code=None, reused=False, kill_error=False):
    import psutil

    calls = []

    def kill():
        calls.append("kill")
        if kill_error:
            raise psutil.AccessDenied(54321)

    child = SimpleNamespace(
        pid=54321,
        create_time=lambda: 2.0 if reused else 1.0,
        is_running=lambda: not finished,
        name=lambda: "RasProcess.exe",
        cmdline=lambda: [
            "RasProcess.exe",
            "CompletePreProcess",
            "Synthetic.p01.tmp.hdf",
        ],
        kill=kill,
        wait=lambda **kwargs: calls.append("reap"),
    )
    return {
        "identity": (54321, 1.0),
        "process": child,
        "finished": finished,
        "exit_code": exit_code,
        "error": None,
    }, calls


def test_child_wait_ignores_quiet_file_until_child_exits(tmp_path, monkeypatch):
    record, calls = child_record()
    path = tmp_path / "Synthetic.p01.tmp.hdf"
    path.write_bytes(b"quiet file")
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])

    def complete(_seconds):
        record.update(finished=True, exit_code=0)

    monkeypatch.setattr(time, "sleep", complete)
    result = GP._wait_for_preprocess_child(path, time.time(), 60, (record,))
    assert not result["timed_out"] and result["errors"] == []
    assert result["saw_child"] and calls == []


def test_child_timeout_kills_only_retained_identity(tmp_path, monkeypatch):
    record, calls = child_record()
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 0, (record,)
    )
    assert result["timed_out"]
    assert calls == ["kill", "reap"]


def test_child_pid_reuse_is_never_signalled(tmp_path, monkeypatch):
    record, calls = child_record(reused=True)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 0, (record,)
    )
    assert result["timed_out"]
    assert calls == []


def test_process_query_denial_is_failure_and_cleans_owned_children(
    tmp_path, monkeypatch
):
    record, calls = child_record()

    def denied(path):
        raise RuntimeError("GEOMETRY_PROCESS_INSPECTION_FAILED")

    monkeypatch.setattr(GP, "_ras_processes_using_path", denied)
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 60, (record,)
    )
    assert "GEOMETRY_PROCESS_INSPECTION_FAILED" in result["errors"]
    assert calls == ["kill", "reap"]


def test_unknown_child_exit_status_is_failure(tmp_path, monkeypatch):
    record, calls = child_record(finished=True)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 60, (record,)
    )
    assert "exit status None" in result["errors"][0]
    assert calls == []


def test_child_cleanup_denial_is_retained(tmp_path, monkeypatch):
    record, calls = child_record(kill_error=True)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 0, (record,)
    )
    assert result["timed_out"]
    assert "owned child cleanup failed" in result["errors"][0]
    assert calls == ["kill"]


def test_child_wait_thread_timeout_is_reported_as_timeout(tmp_path, monkeypatch):
    import threading

    import psutil

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    def expired(**kwargs):
        raise psutil.TimeoutExpired(kwargs["timeout"], pid=54321)

    child = SimpleNamespace(
        pid=54321,
        create_time=lambda: 1.0,
        wait=expired,
        is_running=lambda: False,
    )
    monkeypatch.setattr(threading, "Thread", ImmediateThread)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    record = GP._watch_preprocess_child(child, time.monotonic())
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 60, (record,)
    )
    assert result["timed_out"]
    assert "timed out" in result["errors"][0]


def test_inaccessible_process_name_fails_exact_path_scan(tmp_path, monkeypatch):
    import psutil

    def denied():
        raise psutil.AccessDenied(54321)

    monkeypatch.setattr(psutil, "process_iter", lambda: [SimpleNamespace(name=denied)])
    with pytest.raises(RuntimeError, match="GEOMETRY_PROCESS_INSPECTION_FAILED"):
        GP._ras_processes_using_path(tmp_path / "Synthetic.p01.tmp.hdf")


def test_plan_restoration_failure_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "Synthetic.p01"
    path.mkdir()
    with pytest.raises(RuntimeError, match="GEOMETRY_PLAN_RESTORE_FAILED"):
        GP._restore_plan_file(path, b"original")


def test_monitor_retains_geometry_writers_without_waiting_for_display_helpers(
    tmp_path, monkeypatch
):
    import psutil

    from ras_commander import _native_helper

    names = (
        "explorer.exe",
        "conhost.exe",
        "RasPlotDriver.exe",
        "RasProcess.exe",
        "PipeServer.exe",
        "UnknownWorker.exe",
    )
    arguments = (
        ["/desktop"],
        ["--server", "0x30", "--headless"],
        ["65670"],
        [],
        [],
        [],
    )
    children = [
        SimpleNamespace(
            pid=pid,
            name=lambda name=name: name,
            is_running=lambda: True,
            create_time=lambda: 1.0,
            cmdline=lambda name=name, args=args: [name, *args],
        )
        for pid, (name, args) in enumerate(zip(names, arguments), 1)
    ]
    monkeypatch.setattr(_native_helper, "_is_wine_helper_runtime", lambda: True)
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(children=lambda **kwargs: children),
    )
    retained = []

    def watch(child, deadline):
        retained.append(child.name())
        return {"identity": (child.pid, 1.0)}

    monkeypatch.setattr(GP, "_watch_preprocess_child", watch)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    states = iter((None, 0))
    process = SimpleNamespace(pid=123, poll=lambda: next(states))
    result = GP._monitor_compute_messages(process, [], time.time(), 60, [])
    assert not result["timed_out"]
    assert retained == ["RasProcess.exe", "PipeServer.exe", "UnknownWorker.exe"]


def test_display_named_worker_with_file_argument_is_not_exempt(monkeypatch):
    from ras_commander import _native_helper

    monkeypatch.setattr(_native_helper, "_is_wine_helper_runtime", lambda: True)
    child = SimpleNamespace(
        name=lambda: "RasPlotDriver.exe",
        cmdline=lambda: ["RasPlotDriver.exe", "Synthetic.p01.tmp.hdf"],
    )
    assert not GP._is_wine_display_child(child)
    monkeypatch.setattr(_native_helper, "_is_wine_helper_runtime", lambda: False)
    child.cmdline = lambda: ["RasPlotDriver.exe", "65670"]
    assert not GP._is_wine_display_child(child)


def test_wine_invalid_name_handle_remains_an_unknown_worker(monkeypatch):
    from ras_commander import _native_helper

    monkeypatch.setattr(_native_helper, "_is_wine_helper_runtime", lambda: True)
    error = OSError("invalid handle")
    error.winerror = 6

    def unavailable():
        raise error

    child = SimpleNamespace(name=unavailable)
    assert not GP._is_wine_display_child(child)
    error.winerror = 5
    with pytest.raises(OSError, match="invalid handle"):
        GP._is_wine_display_child(child)


def test_monitor_reclassifies_initially_unknown_wine_display_child(monkeypatch):
    import psutil

    child = SimpleNamespace(pid=432, is_running=lambda: True, create_time=lambda: 1.0)
    monkeypatch.setattr(
        psutil, "Process", lambda pid: SimpleNamespace(children=lambda **kw: [child])
    )
    roles = iter((False, True))
    monkeypatch.setattr(GP, "_is_wine_display_child", lambda child: next(roles))
    watched = []

    def watch(child, deadline):
        watched.append(child.pid)
        return {"identity": (child.pid, 1.0)}

    monkeypatch.setattr(GP, "_watch_preprocess_child", watch)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    states = iter((None, None, 0))
    result = GP._monitor_compute_messages(
        SimpleNamespace(pid=123, poll=lambda: next(states)), [], time.time(), 60, []
    )
    assert watched == [432]
    assert result["children"] == ()
    assert not result["errors"]


def test_last_launcher_poll_unknown_display_role_is_retried(tmp_path, monkeypatch):
    import psutil

    record, calls = child_record()
    child = record["process"]
    monkeypatch.setattr(
        psutil, "Process", lambda pid: SimpleNamespace(children=lambda **kw: [child])
    )
    roles = iter((False, True))
    monkeypatch.setattr(GP, "_is_wine_display_child", lambda child: next(roles))
    monkeypatch.setattr(GP, "_watch_preprocess_child", lambda *args: record)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    states = iter((None, 0))
    monitored = GP._monitor_compute_messages(
        SimpleNamespace(pid=123, poll=lambda: next(states)), [], time.time(), 60, []
    )
    assert monitored["children"] == (record,)
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 60, monitored["children"]
    )
    assert not result["timed_out"] and not result["errors"]
    assert not result["saw_child"] and calls == []


def test_child_wait_does_not_classify_reused_pid_as_display(tmp_path, monkeypatch):
    record, calls = child_record(reused=True)
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    monkeypatch.setattr(
        GP, "_is_wine_display_child", lambda child: pytest.fail("queried reused pid")
    )
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 0, (record,)
    )
    assert result["timed_out"] and calls == []


def test_child_wait_role_query_failure_is_retained(tmp_path, monkeypatch):
    record, calls = child_record()
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])

    def denied(child):
        raise OSError("role query failed")

    monkeypatch.setattr(GP, "_is_wine_display_child", denied)
    result = GP._wait_for_preprocess_child(
        tmp_path / "Synthetic.p01.tmp.hdf", time.time(), 60, (record,)
    )
    assert result["errors"] == ["role query failed"]
    assert calls == ["kill", "reap"]
