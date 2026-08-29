"""Focused control-flow regression tests for ``RasCmdr.compute_plan()``."""

import importlib
import hashlib
import inspect
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.RasCmdr import RasCmdr


rascmdr_module = importlib.import_module("ras_commander.RasCmdr")


class _DummyRas:
    """Minimal ras-like object for compute_plan control-flow tests."""

    def __init__(self, init_exception=None):
        self.project_folder = r"C:\fake_project"
        self.prj_file = r"C:\fake_project\test.prj"
        self.ras_exe_path = r"C:\Program Files\HEC-RAS\Ras.exe"
        self.ras_version = "6.6"
        self.init_exception = init_exception
        self.refresh_calls = []
        self.plan_df = None
        self.geom_df = None
        self.flow_df = None
        self.unsteady_df = None
        self.results_df = None

    def check_initialized(self):
        if self.init_exception is not None:
            raise self.init_exception

    def get_plan_entries(self):
        self.refresh_calls.append("plan")
        return "plan_df"

    def get_geom_entries(self):
        self.refresh_calls.append("geom")
        return "geom_df"

    def get_flow_entries(self):
        self.refresh_calls.append("flow")
        return "flow_df"

    def get_unsteady_entries(self):
        self.refresh_calls.append("unsteady")
        return "unsteady_df"

    def update_results_df(self, plan_numbers=None):
        self.refresh_calls.append(("results", plan_numbers))


def _patch_compute_launcher(
    monkeypatch,
    tmp_path,
    ras_obj,
    *,
    returncode=0,
    on_wait=None,
):
    """Install an exact-path, immediate fake for compute_plan launch tests."""
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"synthetic ras executable")
    ras_obj.ras_exe_path = executable

    class FakePopen:
        pid = 2468

        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = returncode

        def wait(self, timeout=None):
            del timeout
            if on_wait is not None:
                on_wait()
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        RasCmdr,
        "_launcher_create_time",
        staticmethod(lambda pid: 123.5),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_confirm_plan_solver_quiescence",
        staticmethod(lambda plan_number, ras_object: True),
    )
    return executable


def test_compute_plan_returns_failed_result_for_regular_exception():
    """Regular Exception paths should stay bool-compatible and non-raising."""
    ras_obj = _DummyRas(init_exception=RuntimeError("boom"))

    result = RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert isinstance(result, ComputeResult)
    assert result.success is False
    assert result.results_df_row is None
    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]


def test_compute_plan_keeps_domain_artifact_contracts_out_of_execution_api():
    """Plan execution must not expose caller-specific raw HDF requirements."""
    parameters = inspect.signature(RasCmdr.compute_plan).parameters

    assert "required_hdf_datasets" not in parameters
    result = ComputeResult(True, None, None)
    assert bool(result) is True
    assert result.execution_details == {}
    assert repr(result) == (
        "ComputeResult(SUCCESS, unverified, results_df_row=None)"
    )
    assert not hasattr(result, "artifact_verification_passed")
    assert not hasattr(result, "verification_failures")


def test_compute_plan_does_not_swallow_keyboard_interrupt():
    """
    Non-Exception exits must propagate after cleanup.

    This guards against returning from a finally block, which would suppress
    ``KeyboardInterrupt`` and similar BaseException subclasses.
    """
    ras_obj = _DummyRas(init_exception=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]


@pytest.mark.skipif(os.name != "nt", reason="Windows HEC-RAS process matching")
def test_cancel_plan_terminates_only_exact_project_process_tree(
    monkeypatch,
    tmp_path,
):
    """Cancellation must not target another Ras.exe session by name alone."""
    import psutil

    project_path = tmp_path / "Fox.prj"
    plan_path = tmp_path / "Fox.p01"
    tmp_hdf_path = tmp_path / "Fox.p01.tmp.hdf"
    project_path.write_text("Proj Title=Fox\n", encoding="ascii")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="ascii")

    class FakeRas:
        project_folder = tmp_path
        project_name = "Fox"
        prj_file = project_path

        @staticmethod
        def check_initialized():
            return None

        @staticmethod
        def get_plan_entries():
            return pd.DataFrame(
                [{"plan_number": "01", "full_path": str(plan_path)}]
            )

    class FakeProcess:
        def __init__(self, pid, name, command_line):
            self.pid = pid
            self.running = True
            self.info = {
                "pid": pid,
                "name": name,
                "cmdline": command_line,
                "create_time": float(pid),
                "cwd": str(tmp_path),
                "exe": str(tmp_path / name),
            }
            self._children = []
            self.terminated = False
            self.killed = False

        def children(self, recursive=False):
            return list(self._children)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.running = False

        def create_time(self):
            if not self.running:
                raise psutil.NoSuchProcess(self.pid)
            return self.info["create_time"]

        def is_running(self):
            return self.running

    launcher = FakeProcess(
        100,
        "Ras.exe",
        ["Ras.exe", "-c", str(project_path), str(plan_path)],
    )
    solver = FakeProcess(
        101,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", str(tmp_hdf_path), "x01"],
    )
    plotter = FakeProcess(102, "RasPlotDriver.exe", ["RasPlotDriver.exe"])
    launcher._children = [solver, plotter]
    unrelated = FakeProcess(
        200,
        "Ras.exe",
        ["Ras.exe", "-c", r"C:\Other\Other.prj", r"C:\Other\Other.p01"],
    )

    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda _attrs: [
            process
            for process in (launcher, solver, plotter, unrelated)
            if process.running
        ],
    )
    def wait_procs(processes, timeout):
        del timeout
        processes = list(processes)
        for process in processes:
            process.running = False
        return processes, []

    monkeypatch.setattr(psutil, "wait_procs", wait_procs)

    assert RasCmdr.cancel_plan("01", ras_object=FakeRas()) is True
    assert launcher.terminated is True
    assert solver.terminated is True
    assert plotter.terminated is True
    assert unrelated.terminated is False
    assert unrelated.killed is False


def test_compute_plan_uses_cached_plan_entries_when_prj_refresh_fails(
    monkeypatch, tmp_path
):
    """A deleted worker .prj should not prevent result-row recovery."""
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    class MissingPrjAfterRunRas:
        def __init__(self):
            self.project_folder = tmp_path
            self.project_name = "TestProject"
            self.prj_file = tmp_path / "TestProject.prj"
            self.ras_exe_path = "Ras.exe"
            self.ras_version = "6.6"
            self.plan_df = pd.DataFrame(
                {
                    "plan_number": ["01"],
                    "full_path": [str(plan_path)],
                    "HDF_Results_Path": [None],
                }
            )
            self.results_df = pd.DataFrame()

        def check_initialized(self):
            return None

        def get_plan_entries(self):
            raise FileNotFoundError(self.prj_file)

        def get_geom_entries(self):
            return pd.DataFrame()

        def get_flow_entries(self):
            return pd.DataFrame()

        def get_unsteady_entries(self):
            return pd.DataFrame()

        def update_results_df(self, plan_numbers=None):
            self.results_df = pd.DataFrame(
                {
                    "plan_number": list(plan_numbers),
                    "HDF_Results_Path": [str(hdf_path)],
                    "hdf_path": [str(hdf_path)],
                }
            )
            return self.results_df

    def complete_run():
        hdf_path.write_text("computed\n", encoding="utf-8")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    # This unit test supplies a fully synthetic subprocess result. Keep its
    # outcome independent of unrelated RasUnsteady.exe processes on the host.
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda tmp_hdf_path: False),
    )
    ras_obj = MissingPrjAfterRunRas()
    _patch_compute_launcher(
        monkeypatch,
        tmp_path,
        ras_obj,
        on_wait=complete_run,
    )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"
    assert result.results_df_row["hdf_path"] == str(hdf_path)


def test_compute_plan_same_dest_folder_does_not_remove_active_project(
    monkeypatch, tmp_path
):
    """Passing the active project folder as dest_folder should run in place."""
    from ras_commander.RasCurrency import RasCurrency

    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (True, "already current")
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        dest_folder=tmp_path,
        overwrite_dest=True,
        ras_object=ras_obj,
    )

    assert result.success is True
    assert prj_path.exists()
    assert plan_path.exists()


def _make_skip_scenario(monkeypatch, tmp_path, rebuild_error=None):
    """Build a project whose results are current, so the smart skip would fire.

    Returns (ras_obj, calls) where calls records whether HEC-RAS was launched, whether
    the geometry preprocessor caches were cleared, and whether the RasProcess.exe
    rebuild was invoked. Pass rebuild_error to simulate RasProcess.exe being absent.
    """
    from ras_commander.RasCurrency import RasCurrency
    from ras_commander.RasProcess import RasProcess
    from ras_commander.geom import GeomPreprocessor

    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    geom_hdf_path = tmp_path / "TestProject.g01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    geom_hdf_path.write_bytes(b"fake hdf")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    calls = {
        "ran": False,
        "cleared_geompre": False,
        "rebuilt": False,
    }

    def complete_run():
        calls["ran"] = True

    def fake_rebuild(geom_hdf, **kwargs):
        calls["rebuilt"] = True
        if rebuild_error is not None:
            raise rebuild_error
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    # Results are current: without an override, compute_plan must skip.
    monkeypatch.setattr(
        RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (True, "already current")
        ),
    )
    monkeypatch.setattr(
        RasCurrency,
        "get_geom_hdf_path",
        staticmethod(lambda plan_number, ras_object: geom_hdf_path),
    )
    def fake_clear_geompre_files(plan_files=None, ras_object=None):
        calls["cleared_geompre"] = True

    monkeypatch.setattr(
        GeomPreprocessor,
        "clear_geompre_files",
        staticmethod(fake_clear_geompre_files),
    )
    monkeypatch.setattr(
        RasProcess, "compute_geometry", staticmethod(fake_rebuild)
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    # The fake launcher below cannot own a real solver process. Isolate these
    # control-flow tests from any unrelated RasUnsteady.exe on the test host.
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda tmp_hdf_path: False),
    )
    _patch_compute_launcher(
        monkeypatch,
        tmp_path,
        ras_obj,
        on_wait=complete_run,
    )

    return ras_obj, calls


def test_compute_plan_smart_skip_fires_when_results_are_current(monkeypatch, tmp_path):
    """Baseline: current results skip execution when no override is requested."""
    ras_obj, calls = _make_skip_scenario(monkeypatch, tmp_path)

    result = RasCmdr.compute_plan("01", ras_object=ras_obj, dialog_watchdog=False)

    assert result.success is True
    assert calls["ran"] is False
    assert result.execution_details == {
        "execution_api": "ras_cmdr",
        "engine_kind": "executable",
        "selected_result_format": "hdf",
        "calculation_attempted": False,
        "solver_quiescence_confirmed": None,
        "result_artifacts_finalized": False,
        "actual_engine_provenance_confirmed": False,
        "selected_executable_path": None,
        "selected_executable_sha256": None,
        "launcher_pid": None,
        "launcher_create_time": None,
    }


@pytest.mark.parametrize("with_callback", [False, True])
def test_compute_plan_uses_one_exact_popen_path_and_reports_provenance(
    monkeypatch,
    tmp_path,
    with_callback,
):
    ras_obj, _calls = _make_skip_scenario(monkeypatch, tmp_path)
    launches = []
    monitor_calls = []

    class CapturingPopen:
        pid = 7654

        def __init__(self, argv, **kwargs):
            launches.append((argv, kwargs))
            self.returncode = 0

        def wait(self, timeout=None):
            del timeout
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", CapturingPopen)
    monkeypatch.setattr(
        RasCmdr,
        "_launcher_create_time",
        staticmethod(lambda pid: 456.75),
    )

    callback = None
    if with_callback:
        class FakeMonitor:
            @staticmethod
            def enable_detailed_logging(*_args, **_kwargs):
                return None

            def __init__(self, **_kwargs):
                pass

            def monitor_until_signal(self, process):
                monitor_calls.append(process.pid)

        monkeypatch.setattr(rascmdr_module, "BcoMonitor", FakeMonitor)
        callback = object()

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
        stream_callback=callback,
    )

    executable = Path(ras_obj.ras_exe_path).resolve(strict=True)
    expected_argv = [
        str(executable),
        "-c",
        str(Path(ras_obj.prj_file).resolve()),
        str((Path(ras_obj.project_folder) / "TestProject.p01").resolve()),
    ]
    assert len(launches) == 1
    assert launches[0][0] == expected_argv
    assert launches[0][1]["shell"] is False
    assert launches[0][1]["cwd"] == str(ras_obj.project_folder)
    assert monitor_calls == ([7654] if with_callback else [])
    assert result.success is True
    assert result.execution_details == {
        "execution_api": "ras_cmdr",
        "engine_kind": "executable",
        "selected_result_format": "hdf",
        "calculation_attempted": True,
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "actual_engine_provenance_confirmed": True,
        "selected_executable_path": str(executable),
        "selected_executable_sha256": hashlib.sha256(
            executable.read_bytes()
        ).hexdigest(),
        "launcher_pid": 7654,
        "launcher_create_time": 456.75,
    }


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("pid", True),
        ("pid", 0),
        ("pid", -1),
        ("create_time", True),
        ("create_time", 0.0),
        ("create_time", -1.0),
        ("create_time", float("nan")),
        ("create_time", float("inf")),
    ],
)
def test_compute_plan_rejects_invalid_launcher_identity_before_provenance(
    monkeypatch,
    tmp_path,
    field,
    invalid,
):
    ras_obj, _calls = _make_skip_scenario(monkeypatch, tmp_path)
    if field == "pid":
        monkeypatch.setattr(rascmdr_module.subprocess.Popen, "pid", invalid)
    else:
        monkeypatch.setattr(
            RasCmdr,
            "_launcher_create_time",
            staticmethod(lambda _pid: invalid),
        )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is False
    assert result.execution_details["actual_engine_provenance_confirmed"] is False
    assert result.execution_details["launcher_pid"] is None
    assert result.execution_details["launcher_create_time"] is None


@pytest.mark.parametrize(
    ("failed_gate", "expected_quiescence", "expected_finalized"),
    [
        ("provenance", True, True),
        ("quiescence", False, False),
        ("finalization", True, False),
    ],
)
def test_compute_plan_never_reports_success_with_an_unproven_terminal_gate(
    monkeypatch,
    tmp_path,
    failed_gate,
    expected_quiescence,
    expected_finalized,
):
    ras_obj, _calls = _make_skip_scenario(monkeypatch, tmp_path)
    if failed_gate == "provenance":
        monkeypatch.setattr(
            RasCmdr,
            "_launcher_create_time",
            staticmethod(
                lambda _pid: (_ for _ in ()).throw(
                    OSError("process identity unavailable")
                )
            ),
        )
    elif failed_gate == "quiescence":
        monkeypatch.setattr(
            RasCmdr,
            "_confirm_plan_solver_quiescence",
            staticmethod(lambda *_args, **_kwargs: False),
        )
    else:
        monkeypatch.setattr(
            rascmdr_module,
            "finalize_plan_execution_artifacts",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("finalization failed")
            ),
        )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    details = result.execution_details
    assert result.success is False
    assert details["calculation_attempted"] is True
    assert details["solver_quiescence_confirmed"] is expected_quiescence
    assert details["result_artifacts_finalized"] is expected_finalized
    assert details["actual_engine_provenance_confirmed"] is (
        failed_gate != "provenance"
    )


def test_compute_plan_force_geompre_bypasses_smart_skip(monkeypatch, tmp_path):
    """force_geompre must execute even when results look current.

    are_plan_results_current() only compares .p##/.g##/.u## mtimes against the results
    HDF, so it cannot see a sidecar-only change. If the skip wins, the native
    reprocessing request is dropped silently and compute_plan still reports
    success -- the caller has no signal that reprocessing never happened.
    """
    ras_obj, calls = _make_skip_scenario(monkeypatch, tmp_path)

    result = RasCmdr.compute_plan(
        "01",
        force_geompre=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert calls["ran"] is True, "force_geompre was skipped: HEC-RAS never launched"
    assert calls["cleared_geompre"] is True, ".c## preprocessor files were not cleared"


def test_compute_plan_clear_geompre_is_skipped_when_results_are_current(
    monkeypatch, tmp_path
):
    """Documents a sharp edge: clear_geompre does NOT override the smart skip.

    The skip is evaluated before the clearing branch, so when results look current
    nothing is cleared and HEC-RAS never runs. That matters for land cover sweeps: a
    perturbed sidecar leaves the .g## mtime untouched, so the results still look
    current and the perturbation silently never reaches the solver. Use force_geompre
    (or force_rerun) for those ensembles.
    """
    ras_obj, calls = _make_skip_scenario(monkeypatch, tmp_path)

    result = RasCmdr.compute_plan(
        "01",
        clear_geompre=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert calls["ran"] is False
    assert calls["cleared_geompre"] is False, (
        "clear_geompre ran despite the skip -- if this now bypasses the skip, update "
        "the land cover rule and this test's premise together"
    )


def test_compute_plan_force_geompre_preserves_hdf_then_requests_native_rebuild(
    monkeypatch, tmp_path
):
    """force_geompre clears .c## files and requests native geometry processing.

    It must not delete or selectively mutate the .g##.hdf: those actions can
    destroy solver-owned data or the land-cover / terrain association.
    """
    from ras_commander.RasCurrency import RasCurrency

    ras_obj, calls = _make_skip_scenario(monkeypatch, tmp_path)

    deleted_whole_hdf = {"called": False}
    monkeypatch.setattr(
        RasCurrency,
        "clear_geom_hdf",
        staticmethod(
            lambda plan_number, ras_object: deleted_whole_hdf.__setitem__("called", True)
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_geompre=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert calls["cleared_geompre"] is True
    assert calls["rebuilt"] is True, "RasProcess.exe rebuild was not invoked"
    assert deleted_whole_hdf["called"] is False, (
        "force_geompre deleted the whole geometry HDF, destroying the land cover association"
    )


def test_compute_plan_force_geompre_survives_missing_rasprocess(monkeypatch, tmp_path):
    """The RasProcess.exe rebuild is best effort and must not fail the compute.

    This keeps force_geompre usable on HEC-RAS versions where the
    CompleteGeometry verb is unavailable while still forcing the plan run.
    """
    ras_obj, calls = _make_skip_scenario(
        monkeypatch,
        tmp_path,
        rebuild_error=FileNotFoundError("RasProcess.exe not found"),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_geompre=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True, "a missing RasProcess.exe must not fail the compute"
    assert calls["rebuilt"] is True
    assert calls["cleared_geompre"] is True
    assert calls["ran"] is True, "HEC-RAS must still run after native preprocessing fails"


def test_windows_path_to_wsl_decodes_utf8(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="/mnt/c/model-\xe9\n", stderr="")

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    assert RasCmdr._windows_path_to_wsl("C:/model-\xe9") == "/mnt/c/model-\xe9"
    assert calls[0][0] == ["wsl", "wslpath", "-a", "C:/model-\xe9"]
    assert calls[0][1]["text"] is True
    assert calls[0][1]["encoding"] == "utf-8"


def test_log_execution_results_uses_concise_info(caplog):
    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        RasCmdr._log_execution_results({"01": True, "02": False})

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    ]
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.name == "ras_commander.RasCmdr"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.RasCmdr"
    ]

    assert info_messages == ["Execution results: 1/2 plan(s) successful"]
    assert warning_messages == ["Failed plan(s): 02"]
    assert "Plan 01: Successful" in debug_messages
    assert "Plan 02: Failed" in debug_messages


def test_compute_plan_success_logging_is_concise(monkeypatch, tmp_path, caplog):
    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = tmp_path / "TestProject.prj"
    ras_obj.ras_exe_path = "Ras.exe"
    plan_path = tmp_path / "TestProject.p01"
    ras_obj.prj_file.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (False, "stale results")
        ),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    _patch_compute_launcher(monkeypatch, tmp_path, ras_obj)
    # This is a logging test around a synthetic launcher, so process discovery
    # must not depend on another user's live RasUnsteady.exe session.
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda tmp_hdf_path: False),
    )
    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    info_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    )
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is True
    assert "HEC-RAS execution completed for plan 01 in" in debug_text
    assert "seconds" in debug_text
    assert "Total run time for plan 01" not in info_text
    assert str(plan_path) not in info_text
    assert "Running command:" in debug_text
    assert str(plan_path) in debug_text


def test_compute_plan_treats_verified_hdf_after_launcher_error_as_success(
    monkeypatch, tmp_path, caplog
):
    """A nonzero Ras.exe launcher return can still yield a valid final HDF."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    hdf_path.write_text("computed\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    def fake_update_results_df(plan_numbers=None):
        ras_obj.results_df = pd.DataFrame(
            {
                "plan_number": list(plan_numbers),
                "hdf_path": [str(hdf_path)],
            }
        )
        return ras_obj.results_df

    ras_obj.update_results_df = fake_update_results_df

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (False, "stale results")
        ),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )

    _patch_compute_launcher(
        monkeypatch,
        tmp_path,
        ras_obj,
        returncode=1,
    )
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: True),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    error_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and record.name == "ras_commander.RasCmdr"
    )
    info_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"
    assert "Error running plan" not in error_text
    assert "final HDF verified after solver completion" in info_text


def test_compute_plan_treats_verified_hdf_after_normal_return_as_success(
    monkeypatch, tmp_path
):
    """Async HDF verification after a zero launcher return should set success."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    hdf_path.write_text("computed\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    def fake_update_results_df(plan_numbers=None):
        ras_obj.results_df = pd.DataFrame(
            {
                "plan_number": list(plan_numbers),
                "hdf_path": [str(hdf_path)],
            }
        )
        return ras_obj.results_df

    ras_obj.update_results_df = fake_update_results_df

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (False, "stale results")
        ),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    _patch_compute_launcher(monkeypatch, tmp_path, ras_obj)
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: True),
    )

    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras_obj,
        dialog_watchdog=False,
        verify=True,
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"


def test_verify_completion_rejects_hdf_older_than_execution(tmp_path):
    hdf_path = tmp_path / "old.p01.hdf"
    hdf_path.write_bytes(b"old successful result")
    old_time = time.time() - 3600
    os.utime(hdf_path, (old_time, old_time))

    assert RasCmdr._verify_completion(
        hdf_path,
        modified_after=time.time(),
    ) is False


def test_async_wait_does_not_finalize_while_completed_hdf_has_active_solver(
    monkeypatch,
    tmp_path,
):
    tmp_hdf = tmp_path / "TestProject.p01.tmp.hdf"
    tmp_hdf.write_bytes(b"active partial")
    ras_obj = SimpleNamespace(
        project_folder=tmp_path,
        project_name="TestProject",
    )
    active_checks = []

    def solver_active(_path):
        active_checks.append(True)
        if len(active_checks) == 1:
            return True
        tmp_hdf.unlink()
        return False

    monkeypatch.setattr(
        RasCmdr,
        "_get_hdf_path",
        staticmethod(lambda *_args, **_kwargs: tmp_path / "TestProject.p01.hdf"),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_verify_completion",
        staticmethod(lambda *_args, **_kwargs: True),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(solver_active),
    )
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda *_args: None)

    assert RasCmdr._wait_for_async_plan_completion(
        "01",
        ras_obj,
        poll_interval=0,
        timeout_seconds=1,
    ) is True
    assert len(active_checks) == 2


def test_process_query_failure_returns_unknown(monkeypatch, tmp_path):
    import psutil

    monkeypatch.setattr(rascmdr_module, "os", SimpleNamespace(name="nt"))

    def fail_process_query(*_args, **_kwargs):
        raise psutil.AccessDenied(pid=1234)

    monkeypatch.setattr(
        psutil,
        "process_iter",
        fail_process_query,
    )

    assert RasCmdr._rasunsteady_process_running_for_tmp_hdf(
        tmp_path / "TestProject.p01.tmp.hdf"
    ) is None


@pytest.mark.parametrize(
    ("complete", "matched", "tmp_exists", "expected"),
    [
        (False, (), False, False),
        (
            True,
            (SimpleNamespace(pid=10, name="Ras.exe"),),
            False,
            False,
        ),
        (
            True,
            (SimpleNamespace(pid=11, name="RasUnsteady.exe"),),
            False,
            False,
        ),
        (True, (), True, False),
        (True, (), False, True),
    ],
)
def test_confirm_plan_solver_quiescence_requires_complete_empty_inventory(
    monkeypatch,
    tmp_path,
    complete,
    matched,
    tmp_exists,
    expected,
):
    ras_obj = SimpleNamespace(
        project_folder=tmp_path,
        project_name="TestProject",
    )
    if tmp_exists:
        (tmp_path / "TestProject.p01.tmp.hdf").write_bytes(b"partial")
    monkeypatch.setattr(
        RasCmdr,
        "inspect_plan_processes",
        staticmethod(
            lambda *_args, **_kwargs: SimpleNamespace(
                complete=complete,
                matched=matched,
            )
        ),
    )

    assert RasCmdr._confirm_plan_solver_quiescence("01", ras_obj) is expected


def test_solver_process_match_is_literal_and_resolves_relative_path(tmp_path):
    target_folder = tmp_path / "model [literal]"
    target_folder.mkdir()
    target = target_folder / "TestProject.p01.tmp.hdf"
    target.write_bytes(b"active")
    process = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": [
                "RasUnsteady.exe",
                '"TestProject.p01.tmp.hdf"',
                "x01",
            ],
            "cwd": str(target_folder),
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is True


def test_solver_process_match_infers_executable_from_cmdline_when_name_unavailable(
    tmp_path,
):
    target = tmp_path / "TestProject.p01.tmp.hdf"
    target.write_bytes(b"active")
    process = SimpleNamespace(
        info={
            "name": None,
            "cmdline": [
                r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\x64\RasUnsteady.exe",
                str(target),
                "x01",
            ],
            "cwd": str(tmp_path),
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is True


def test_solver_process_match_supports_native_cwd_batch_signature(tmp_path):
    target = tmp_path / "TestProject.p08.tmp.hdf"
    exact = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": [
                "RasUnsteady.exe",
                str(tmp_path / "TestProject.c01"),
                "b08",
            ],
            "cwd": str(tmp_path),
        }
    )
    wrong_plan = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": [
                "RasUnsteady.exe",
                str(tmp_path / "TestProject.c01"),
                "b09",
            ],
            "cwd": str(tmp_path),
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [exact],
    ) is True
    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [wrong_plan],
    ) is False


def test_solver_process_match_treats_missing_process_identity_as_unknown(tmp_path):
    target = tmp_path / "TestProject.p01.tmp.hdf"
    target.write_bytes(b"active")
    process = SimpleNamespace(
        info={
            "name": None,
            "cmdline": None,
            "cwd": None,
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is None


@pytest.mark.parametrize(
    "alias",
    [
        r"Z:\Models\TestProject.p01.tmp.hdf",
        r"\\server\share\Models\TestProject.p01.tmp.hdf",
        r"C:\MODELS~1\TestProject.p01.tmp.hdf",
        r"C:\links\TestProject.p01.tmp.hdf",
    ],
    ids=["mapped-drive", "unc", "short-path", "symlink"],
)
@pytest.mark.skipif(os.name != "nt", reason="Windows path aliases")
def test_solver_process_match_uses_file_identity_for_path_aliases(
    monkeypatch,
    tmp_path,
    alias,
):
    target = tmp_path / "TestProject.p01.tmp.hdf"
    target.write_bytes(b"active")
    comparisons = []

    def samefile(candidate, expected):
        comparisons.append((str(candidate), str(expected)))
        return str(candidate) == alias and Path(expected) == target

    monkeypatch.setattr(rascmdr_module.os.path, "samefile", samefile)
    process = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", alias, "x01"],
            "cwd": None,
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is True
    assert comparisons == [(alias, str(target))]


def test_solver_process_match_uses_actual_file_identity(tmp_path):
    target = tmp_path / "TestProject.p01.tmp.hdf"
    alias = tmp_path / "TestProject-alias.p01.tmp.hdf"
    target.write_bytes(b"active")
    os.link(target, alias)
    process = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", str(alias), "x01"],
            "cwd": str(tmp_path),
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is True


def test_solver_process_match_treats_identity_failure_as_unknown(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "target" / "TestProject.p01.tmp.hdf"
    alias = tmp_path / "unavailable" / "TestProject.p01.tmp.hdf"
    target.parent.mkdir()
    target.write_bytes(b"active")
    monkeypatch.setattr(
        rascmdr_module.os.path,
        "samefile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("identity unavailable")
        ),
    )
    process = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", str(alias), "x01"],
            "cwd": None,
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is None


@pytest.mark.parametrize(
    "process_info",
    [
        {"name": "RasUnsteady.exe", "cmdline": None, "cwd": None},
        {
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", "unrecognized-input"],
            "cwd": None,
        },
        {
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", "TestProject.p01.tmp.hdf"],
            "cwd": None,
        },
    ],
    ids=["unreadable-command-line", "unparsed-command-line", "relative-without-cwd"],
)
def test_solver_process_match_treats_parsing_uncertainty_as_unknown(
    tmp_path,
    process_info,
):
    target = tmp_path / "TestProject.p01.tmp.hdf"
    target.write_bytes(b"active")

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [SimpleNamespace(info=process_info)],
    ) is None


def test_solver_process_match_distinguishes_confirmed_unrelated_solver(tmp_path):
    target = tmp_path / "target" / "TestProject.p01.tmp.hdf"
    unrelated = tmp_path / "other" / "TestProject.p01.tmp.hdf"
    target.parent.mkdir()
    unrelated.parent.mkdir()
    target.write_bytes(b"target")
    unrelated.write_bytes(b"other")
    process = SimpleNamespace(
        info={
            "name": "RasUnsteady.exe",
            "cmdline": ["RasUnsteady.exe", str(unrelated), "x01"],
            "cwd": str(unrelated.parent),
        }
    )

    assert RasCmdr._rasunsteady_processes_reference_tmp_hdf(
        target,
        [process],
    ) is False


def test_compute_plan_does_not_credit_stale_hdf_after_failed_rerun(
    monkeypatch,
    tmp_path,
):
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    hdf_path.write_text("old complete result\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda _plan_path: None),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_get_hdf_path",
        staticmethod(lambda *_args, **_kwargs: hdf_path),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_verify_completion",
        staticmethod(
            lambda _path, check_errors=True, modified_after=None: (
                modified_after is None
            )
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras_obj,
        force_rerun=True,
        verify=True,
        dialog_watchdog=False,
    )

    assert result.success is False


def test_compute_plan_keeps_launcher_error_when_final_hdf_not_verified(
    monkeypatch, tmp_path, caplog
):
    """Real launcher failures should still be reported as failed plans."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "_are_plan_results_current_for_execution",
        staticmethod(
            lambda plan_number, ras_object, **kwargs: (False, "stale results")
        ),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )

    _patch_compute_launcher(
        monkeypatch,
        tmp_path,
        ras_obj,
        returncode=1,
    )
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: False),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    error_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is False
    assert "Error running plan: 01 (exit code 1)" in error_text


def test_wsl_linux_retry_script_uses_utf8_and_cleans_io_tmp(monkeypatch, tmp_path):
    popen_calls = []
    run_calls = []

    class FakePopen:
        returncode = 1

        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

        def communicate(self, timeout=None):
            return "", "ras failed"

        def kill(self):
            pass

    def fake_run(args, **kwargs):
        run_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        RasCmdr,
        "_windows_path_to_wsl",
        staticmethod(lambda path: f"/mnt/test/{Path(path).name}"),
    )
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    io_tmp_hdf = tmp_path / "io.tmp.hdf"
    io_tmp_hdf.write_bytes(b"stale")

    result = RasCmdr._compute_plan_linux_via_wsl(
        ras_exe="/mnt/c/HEC-RAS/RasUnsteady",
        ras_exe_dir="/mnt/c/HEC-RAS",
        plan_number="01",
        geom_num="01",
        project_dir=tmp_path,
        project_name="Demo",
        tmp_hdf=tmp_path / "Demo.p01.tmp.hdf",
        timeout_sec=30,
        dos2unix=False,
        retry=False,
        retry_delay_sec=0,
        ras_obj=SimpleNamespace(
            project_folder=tmp_path,
            project_name="Demo",
        ),
    )

    assert result.success is False
    assert not io_tmp_hdf.exists()

    script = popen_calls[0][0][3]
    assert '[ -d "\\$d" ] && ld_path=' not in script
    assert 'if [ -d "\\$d" ]; then' in script
    assert popen_calls[0][1]["text"] is True
    assert popen_calls[0][1]["encoding"] == "utf-8"
    expected_cleanup = (
        f"cd /mnt/test/{tmp_path.name} && "
        "find . -maxdepth 1 -type l -name 'io.*' -delete"
    )
    assert run_calls[0][0] == ["wsl", "bash", "-lc", expected_cleanup]
    assert run_calls[0][1]["encoding"] == "utf-8"


def test_wsl_linux_retry_normalizes_opposing_result_after_each_attempt(
    monkeypatch,
    tmp_path,
):
    legacy = tmp_path / "Demo.O01"
    launches = []

    class FakePopen:
        returncode = 1

        def __init__(self, _args, **_kwargs):
            assert not legacy.exists()
            launches.append(len(launches) + 1)

        def communicate(self, timeout=None):
            legacy.write_bytes(b"recreated by failed modern attempt")
            return "", "ras failed"

        def kill(self):
            pass

    monkeypatch.setattr(
        RasCmdr,
        "_windows_path_to_wsl",
        staticmethod(lambda path: f"/mnt/test/{Path(path).name}"),
    )
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    result = RasCmdr._compute_plan_linux_via_wsl(
        ras_exe="/mnt/c/HEC-RAS/RasUnsteady",
        ras_exe_dir="/mnt/c/HEC-RAS",
        plan_number="01",
        geom_num="01",
        project_dir=tmp_path,
        project_name="Demo",
        tmp_hdf=tmp_path / "Demo.p01.tmp.hdf",
        timeout_sec=30,
        dos2unix=False,
        retry=True,
        retry_delay_sec=0,
        ras_obj=SimpleNamespace(
            project_folder=tmp_path,
            project_name="Demo",
        ),
    )

    assert result.success is False
    assert launches == [1, 2]
    assert not legacy.exists()


def test_compute_plan_linux_wsl_uses_canonical_layout_without_c_file(
    monkeypatch,
    tmp_path,
):
    """The /mnt WSL branch must reach its adapter without an unbound layout."""
    project_name = "Demo"
    plan_path = tmp_path / f"{project_name}.p01"
    plan_path.write_text("Geom File=g01\n", encoding="utf-8")
    (tmp_path / f"{project_name}.p01.tmp.hdf").write_bytes(b"tmp")
    (tmp_path / f"{project_name}.b01").write_bytes(b"boundary")
    (tmp_path / f"{project_name}.x01").write_bytes(b"geometry")

    ras_obj = SimpleNamespace(
        project_folder=tmp_path,
        project_name=project_name,
        check_initialized=lambda: None,
    )
    captured = {}

    def fake_wsl_compute(**kwargs):
        captured.update(kwargs)
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_compute_plan_linux_via_wsl",
        staticmethod(fake_wsl_compute),
    )

    result = RasCmdr.compute_plan_linux(
        "01",
        ras_exe_dir="/mnt/c/HEC-RAS/7.0.1/Linux/Linux",
        ras_object=ras_obj,
        retry=False,
    )

    assert result.success is True
    assert captured["geom_num"] == "01"
    assert captured["tmp_hdf"] == tmp_path / f"{project_name}.p01.tmp.hdf"
    assert not (tmp_path / f"{project_name}.c01").exists()


def test_compute_plan_linux_wsl_preflight_failure_preserves_legacy_result(
    monkeypatch,
    tmp_path,
):
    project_name = "Demo"
    plan_path = tmp_path / f"{project_name}.p01"
    plan_path.write_text("Geom File=g01\n", encoding="utf-8")
    (tmp_path / f"{project_name}.p01.tmp.hdf").write_bytes(b"tmp")
    (tmp_path / f"{project_name}.b01").write_bytes(b"boundary")
    (tmp_path / f"{project_name}.x01").write_bytes(b"geometry")
    legacy = tmp_path / f"{project_name}.O01"
    legacy.write_bytes(b"existing legacy result")
    ras_obj = SimpleNamespace(
        project_folder=tmp_path,
        project_name=project_name,
        check_initialized=lambda: None,
    )

    monkeypatch.setattr(rascmdr_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_compute_plan_linux_via_wsl",
        staticmethod(
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("WSL path conversion failed")
            )
        ),
    )

    with pytest.raises(RuntimeError, match="WSL path conversion failed"):
        RasCmdr.compute_plan_linux(
            "01",
            ras_exe_dir="/mnt/c/HEC-RAS/7.0.1/Linux/Linux",
            ras_object=ras_obj,
            retry=False,
        )

    assert legacy.read_bytes() == b"existing legacy result"


def test_wsl_linux_exit_zero_does_not_promote_incomplete_hdf(
    monkeypatch,
    tmp_path,
):
    """Exit code zero is insufficient when the temporary HDF lacks results."""

    class FakePopen:
        returncode = 0

        def __init__(self, args, **kwargs):
            pass

        def communicate(self, timeout=None):
            return "", ""

        def kill(self):
            pass

    tmp_hdf = tmp_path / "Demo.p01.tmp.hdf"
    with h5py.File(tmp_hdf, "w") as hdf_file:
        hdf_file.create_group("Geometry")
    (tmp_path / "compute_linux_01.log").write_text(
        "Finished Unsteady Flow Simulation\n",
        encoding="utf-8",
    )
    plan_hdf = tmp_path / "Demo.p01.hdf"

    monkeypatch.setattr(
        RasCmdr,
        "_windows_path_to_wsl",
        staticmethod(lambda path: f"/mnt/test/{Path(path).name}"),
    )
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_get_hdf_path",
        staticmethod(
            lambda *args, **kwargs: pytest.fail(
                "Incomplete WSL result must not be promoted"
            )
        ),
    )

    result = RasCmdr._compute_plan_linux_via_wsl(
        ras_exe="/mnt/c/HEC-RAS/RasUnsteady",
        ras_exe_dir="/mnt/c/HEC-RAS",
        plan_number="01",
        geom_num="01",
        project_dir=tmp_path,
        project_name="Demo",
        tmp_hdf=tmp_hdf,
        timeout_sec=30,
        dos2unix=False,
        retry=False,
        retry_delay_sec=0,
        ras_obj=SimpleNamespace(
            project_folder=tmp_path,
            project_name="Demo",
        ),
    )

    assert result.success is False
    assert tmp_hdf.exists()
    assert not plan_hdf.exists()
