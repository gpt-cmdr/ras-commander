import importlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


rascontrol_module = importlib.import_module("ras_commander.RasControl")
rasbco_module = importlib.import_module("ras_commander.RasBco")
RasControl = rascontrol_module.RasControl
ProjectInfo = rascontrol_module.ProjectInfo


def _project_info(tmp_path, version="6.3"):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    (tmp_path / "Demo.p01").write_text("Plan Title=Plan 01\n", encoding="utf-8")
    return ProjectInfo(
        project_path=project_path,
        version=version,
        plan_number="01",
        plan_name="Plan 01",
    )


def _disable_detailed_logging(monkeypatch):
    monkeypatch.setattr(
        rasbco_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_file: None),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_inspect_controller_post_close_processes",
        lambda **_kwargs: (
            SimpleNamespace(complete=True, matched=(), query_errors=()),
            SimpleNamespace(complete=True, processes=(), query_errors=()),
        ),
    )


def _emit_owned_session(kwargs, *, project_path, pid=4321, created=123.5):
    callback = kwargs.get("session_open_callback")
    executable = project_path.parent / "Ras.exe"
    executable.write_bytes(b"deterministic fake Controller image")
    session = SimpleNamespace(
        project_path=str(project_path),
        ras_pid=pid,
        ras_create_time=created,
        session_id="test-session",
        detection_confidence=100,
        ras_executable_path=str(executable),
        ras_executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    )
    if callback is not None:
        callback(session)
    return session


def _owned_cleanup(pid=4321):
    return rascontrol_module._SessionCleanupResult(
        session_id="test-session",
        ras_pid=pid,
        process_detected=True,
    )


def test_exact_630_identity_preserves_release_specific_mapping():
    assert RasControl.get_controller_progid("6.3") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("6.3.1") == "RAS631.HECRASController"
    assert RasControl.get_controller_progid("6.3.0") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("6.3.0.2") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("630") == "RAS630.HECRASController"
    with pytest.raises(ValueError, match="not supported"):
        RasControl.get_controller_progid("9.9")


def test_blocking_run_uses_exact_controller_and_returns_execution_details(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    calls = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            calls.append(("plan", plan_name))

        def Compute_CurrentPlan(self, *args):
            calls.append(("compute", args))
            return True, 2, ("Starting", "Computations Completed"), True

        def Compute_Complete(self):
            raise AssertionError("blocking execution must not poll Compute_Complete")

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        strict_close=False,
        close_outcome_callback=None,
        **_kwargs,
    ):
        calls.append(("open", project_path, version, strict_close))
        _emit_owned_session(_kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=False,
        refresh_results=False,
        blocking=True,
        controller_version="6.3.0.2",
        strict_close=True,
    )

    assert result.success is True
    assert result.messages == ["Starting", "Computations Completed"]
    assert result.execution_details["requested_controller_version"] == "6.3.0.2"
    assert result.execution_details["resolved_controller_version"] == "6.3.0.2"
    assert result.execution_details["controller_progid"] == "RAS630.HECRASController"
    assert result.execution_details["compute_mode"] == "blocking"
    assert result.execution_details["message_count"] == 2
    assert result.execution_details["blocking_result"] is True
    assert result.execution_details["controller_message_count"] == 2
    assert result.execution_details["watchdog_requested"] is False
    assert result.execution_details["watchdog_started"] is False
    assert result.execution_details["execution_api"] == "ras_control"
    assert result.execution_details["engine_kind"] == "controller"
    assert result.execution_details["selected_result_format"] == "hdf"
    assert result.execution_details["calculation_attempted"] is True
    assert result.execution_details["solver_quiescence_confirmed"] is True
    assert result.execution_details["result_artifacts_finalized"] is True
    preparation = result.execution_details["artifact_preparation_cleanup"]
    finalization = result.execution_details["artifact_finalization_cleanup"]
    assert preparation["result_format"] == "legacy"
    assert preparation["include_message_sidecars"] is True
    assert preparation["removed_paths"] == []
    assert {Path(path).name for path in preparation["missing_paths"]} == {
        "Demo.O01",
        "Demo.p01.comp_msgs.txt",
        "Demo.p01.computeMsgs.txt",
        "Demo.bco01",
    }
    assert finalization["result_format"] == "legacy"
    assert finalization["include_message_sidecars"] is False
    assert finalization["removed_paths"] == []
    assert [Path(path).name for path in finalization["missing_paths"]] == [
        "Demo.O01"
    ]
    assert result.execution_details["actual_engine_provenance_confirmed"] is True
    assert result.execution_details["controller_pid"] == 4321
    assert result.execution_details["controller_create_time"] == 123.5
    assert Path(result.execution_details["controller_executable_path"]).name == "Ras.exe"
    assert result.execution_details["controller_executable_sha256"] == hashlib.sha256(
        b"deterministic fake Controller image"
    ).hexdigest()
    assert result.execution_details["controller_close_safe"] is True
    assert result.execution_details["owned_process_exit_confirmed"] is True
    assert result.execution_details["post_close_plan_processes_quiescent"] is True
    assert result.execution_details["post_close_global_processes_quiescent"] is True
    assert result.execution_details["strict_close_requested"] is True
    assert result.execution_details["max_runtime_seconds"] == 86400.0
    assert result.execution_details["duration_seconds"] >= 0
    assert json.loads(json.dumps(result.execution_details)) == result.execution_details
    success, messages = result
    assert success is True
    assert messages == result.messages
    assert ("open", info.project_path, "6.3.0.2", True) in calls
    assert ("compute", (None, None, True)) in calls


def test_current_controller_result_reports_null_cleanup_records(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    (tmp_path / "Demo.p01.hdf").write_bytes(b"current HDF")

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name):
            return None

        def PlanOutput_IsCurrent(self):
            return True

    def fake_open_close(
        _project_path,
        _version,
        operation_func,
        *,
        close_outcome_callback=None,
        **_kwargs,
    ):
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))

    result = RasControl.run_plan(
        "01",
        force_recompute=False,
        use_watchdog=False,
        refresh_results=False,
        controller_version="6.3.0.2",
    )

    assert result.success is True
    assert result.execution_details["compute_mode"] == "skipped_current"
    assert result.execution_details["calculation_attempted"] is False
    assert result.execution_details["artifact_preparation_cleanup"] is None
    assert result.execution_details["artifact_finalization_cleanup"] is None


def test_default_run_retains_async_polling_contract(monkeypatch, tmp_path):
    info = _project_info(tmp_path, version="6.3.1")
    calls = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            calls.append(("plan", plan_name))

        def Compute_CurrentPlan(self, *args):
            calls.append(("compute", args))
            return True, 1, ("Computations Started",), False

        def Compute_Complete(self):
            calls.append(("poll",))
            return True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        strict_close=False,
        close_outcome_callback=None,
        **_kwargs,
    ):
        calls.append(("open", project_path, version, strict_close))
        _emit_owned_session(_kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=False,
        refresh_results=False,
    )

    assert result.success is True
    assert result.messages == ["Computations Started"]
    assert result.execution_details["requested_controller_version"] == "6.3.1"
    assert result.execution_details["resolved_controller_version"] == "6.3.1"
    assert result.execution_details["controller_progid"] == ("RAS631.HECRASController")
    assert result.execution_details["compute_mode"] == "poll"
    assert result.execution_details["controller_message_count"] == 1
    assert result.execution_details["poll_count"] == 0
    assert ("compute", (None, None)) in calls
    assert ("poll",) in calls


def test_blocking_rejects_legacy_controller_before_open(monkeypatch, tmp_path):
    info = _project_info(tmp_path, version="4.1")
    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(
            lambda *args, **kwargs: pytest.fail(
                "legacy validation must precede COM open"
            )
        ),
    )

    with pytest.raises(ValueError, match="HEC-RAS 5.x and newer"):
        RasControl.run_plan("01", blocking=True)


@pytest.mark.parametrize(
    "max_runtime",
    [0, -1, True, None, "60", float("nan"), float("inf")],
)
def test_run_plan_rejects_invalid_max_runtime(max_runtime):
    with pytest.raises(ValueError, match="max_runtime must be a positive"):
        RasControl.run_plan("01", max_runtime=max_runtime)


def test_strict_close_failure_during_current_check_does_not_start_compute(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    calls = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            calls.append(("plan", plan_name))

        def PlanOutput_IsCurrent(self):
            calls.append(("current",))
            return True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        strict_close=False,
        close_outcome_callback=None,
        **_kwargs,
    ):
        calls.append(("open", project_path, version, strict_close))
        result = operation_func(FakeCom())
        close_error = OSError("close failed")
        if close_outcome_callback is not None:
            close_outcome_callback(True, SimpleNamespace(), close_error)
        assert result is True
        raise RuntimeError("QuitRas() failed: close failed") from close_error

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    monkeypatch.setattr(
        rasbco_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "strict current-check close failure must not start execution"
            )
        ),
    )

    with pytest.raises(RuntimeError, match=r"QuitRas\(\) failed: close failed"):
        RasControl.run_plan(
            "01",
            use_watchdog=False,
            refresh_results=False,
            strict_close=True,
        )

    assert calls == [
        ("open", info.project_path, info.version, True),
        ("plan", info.plan_name),
        ("current",),
    ]


def test_non_strict_current_check_failure_retains_compute_fallback(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    calls = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            calls.append(("plan", plan_name))

        def PlanOutput_IsCurrent(self):
            calls.append(("current",))
            raise OSError("currency query unavailable")

        def Compute_CurrentPlan(self, *args):
            calls.append(("compute", args))
            return True, 1, ("Computations Started",), False

        def Compute_Complete(self):
            calls.append(("poll",))
            return True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        strict_close=False,
        close_outcome_callback=None,
        **_kwargs,
    ):
        calls.append(("open", project_path, version, strict_close))
        _emit_owned_session(_kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        use_watchdog=False,
        refresh_results=False,
    )

    assert result.success is True
    assert calls == [
        ("open", info.project_path, info.version, False),
        ("plan", info.plan_name),
        ("current",),
        ("open", info.project_path, info.version, False),
        ("plan", info.plan_name),
        ("compute", (None, None)),
        ("poll",),
    ]


@pytest.mark.parametrize(
    ("host_inventory", "message"),
    [
        (
            SimpleNamespace(
                complete=False,
                processes=(),
                query_errors=(SimpleNamespace(reason_code="access_denied"),),
            ),
            "inventory was incomplete",
        ),
        (
            SimpleNamespace(
                complete=True,
                processes=(SimpleNamespace(pid=4321),),
                query_errors=(),
            ),
            "already active on this host",
        ),
    ],
)
def test_pre_run_global_inventory_fails_before_any_plan_mutation(
    monkeypatch,
    tmp_path,
    host_inventory,
    message,
):
    info = _project_info(tmp_path)
    hdf = tmp_path / "Demo.p01.hdf"
    legacy = tmp_path / "Demo.O01"
    hdf.write_bytes(b"existing hdf bytes")
    legacy.write_bytes(b"existing legacy bytes")
    plan_before = (tmp_path / "Demo.p01").read_bytes()
    plan_inventory = SimpleNamespace(
        complete=True,
        matched=(),
        query_errors=(),
    )

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_inspect_controller_post_close_processes",
        lambda **_kwargs: (plan_inventory, host_inventory),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "Controller must not open after failed global pre-run gate"
            )
        ),
    )
    monkeypatch.setattr(
        rasbco_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "plan logging mutation must not precede global process gate"
            )
        ),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "prepare_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact cleanup must not precede global process gate"
        ),
    )

    with pytest.raises(RuntimeError, match=message):
        RasControl.run_plan(
            "01",
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
            blocking=True,
            controller_version="6.3.0.2",
        )

    assert (tmp_path / "Demo.p01").read_bytes() == plan_before
    assert hdf.read_bytes() == b"existing hdf bytes"
    assert legacy.read_bytes() == b"existing legacy bytes"


def test_blocking_normalizes_scalar_message_and_rejects_malformed_return(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    returns = iter(
        [
            (True, 1, "Computations Completed", object()),
            (True, 0),
        ]
    )

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            pass

        def Compute_CurrentPlan(self, *args):
            return next(returns)

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        close_outcome_callback=None,
        **_kwargs,
    ):
        _emit_owned_session(_kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=False,
        refresh_results=False,
        blocking=True,
        controller_version="630",
    )

    assert result.messages == ["Computations Completed"]
    assert result.execution_details["resolved_controller_version"] == "6.3.0.2"
    assert isinstance(result.execution_details["blocking_result"], str)
    json.dumps(result.execution_details)

    with pytest.raises(RuntimeError, match="unsupported result"):
        RasControl.run_plan(
            "01",
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
            blocking=True,
            controller_version="6.3.0.2",
        )


@pytest.mark.parametrize("blocking_result", [float("nan"), float("inf"), float("-inf")])
def test_controller_execution_details_reject_nonfinite_float_payloads(
    monkeypatch,
    tmp_path,
    blocking_result,
):
    info = _project_info(tmp_path)
    closed = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            del plan_name

        def Compute_CurrentPlan(self, *args):
            del args
            return True, 1, ("Computations Completed",), blocking_result

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        close_outcome_callback=None,
        **kwargs,
    ):
        del version
        _emit_owned_session(kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            closed.append(True)
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    with pytest.raises(ValueError, match="detail floats must be finite"):
        RasControl.run_plan(
            "01",
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
            blocking=True,
            controller_version="6.3.0.2",
        )

    assert closed == [True]


def test_watchdog_starts_before_blocking_compute(monkeypatch, tmp_path):
    info = _project_info(tmp_path)
    events = []
    controller_image = tmp_path / "Ras.exe"
    controller_image.write_bytes(b"watchdog Controller image")
    session = SimpleNamespace(
        project_path=str(info.project_path),
        ras_pid=4321,
        ras_create_time=123.5,
        session_id="session-1",
        detection_confidence=100,
        ras_executable_path=str(controller_image),
        ras_executable_sha256=hashlib.sha256(
            controller_image.read_bytes()
        ).hexdigest(),
    )

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            pass

        def Compute_CurrentPlan(self, *args):
            events.append("compute")
            return True, 1, ("Computations Completed",), True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        close_outcome_callback=None,
        **_kwargs,
    ):
        callback = _kwargs.get("session_open_callback")
        if callback is not None:
            callback(session)
        rascontrol_module._active_sessions[session.session_id] = session
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)
            rascontrol_module._active_sessions.clear()

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)
    monkeypatch.setattr(
        rascontrol_module,
        "_spawn_watchdog",
        lambda **kwargs: events.append("watchdog_start")
        or rascontrol_module._WatchdogIdentity(99, 123.0, "python.exe"),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_terminate_watchdog",
        lambda identity: events.append("watchdog_stop")
        or rascontrol_module._WatchdogCleanupResult(
            pid=identity.pid,
            identity_state="terminated",
            terminated=True,
        ),
    )

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=True,
        refresh_results=False,
        blocking=True,
        controller_version="6.3.0.2",
    )

    assert result.success is True
    assert result.execution_details["watchdog_requested"] is True
    assert result.execution_details["watchdog_started"] is True
    assert events == ["watchdog_start", "compute", "watchdog_stop"]


def test_watchdog_worker_receives_exact_parent_and_ras_identity(
    monkeypatch,
    tmp_path,
):
    launches = []

    class WatchdogProcess:
        pid = 99

    monkeypatch.setattr(
        rascontrol_module.subprocess,
        "Popen",
        lambda argv, **kwargs: launches.append((argv, kwargs)) or WatchdogProcess(),
    )

    class ExactWatchdog:
        def __init__(self, pid):
            self.pid = pid

        @staticmethod
        def create_time():
            return 123.0

        @staticmethod
        def name():
            return "python.exe"

        @staticmethod
        def is_running():
            return True

    monkeypatch.setattr(
        rascontrol_module.psutil,
        "Process",
        ExactWatchdog,
    )

    watchdog_identity = rascontrol_module._spawn_watchdog(
        parent_pid=12,
        ras_pid=34,
        ras_create_time=56.75,
        max_runtime=60,
        lock_file_path=tmp_path / "session.lock",
    )

    assert watchdog_identity == rascontrol_module._WatchdogIdentity(
        99, 123.0, "python.exe"
    )
    argv = launches[0][0]
    assert Path(argv[1]).name == "_orphan_watchdog.py"
    arguments = dict(zip(argv[2::2], argv[3::2]))
    assert arguments == {
        "--parent-pid": "12",
        "--parent-create-time": "123.0",
        "--parent-name": "python.exe",
        "--ras-pid": "34",
        "--ras-create-time": "56.75",
        "--ras-name": "ras.exe",
        "--max-runtime": "60",
        "--lock-file": str(tmp_path / "session.lock"),
    }


def test_watchdog_receipt_reports_requested_but_not_started(monkeypatch, tmp_path):
    info = _project_info(tmp_path)

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            pass

        def Compute_CurrentPlan(self, *args):
            return True, 1, ("Computations Completed",), True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        *,
        close_outcome_callback=None,
        **_kwargs,
    ):
        _emit_owned_session(_kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=True,
        refresh_results=False,
        blocking=True,
        controller_version="6.3.0.2",
    )

    assert result.execution_details["watchdog_requested"] is True
    assert result.execution_details["watchdog_started"] is False


def test_watchdog_cleanup_never_signals_reused_pid(monkeypatch):
    signals = []

    class ReusedWatchdog:
        def __init__(self, pid):
            self.pid = pid

        @staticmethod
        def create_time():
            return 999.0

        @staticmethod
        def name():
            return "python.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            signals.append("terminate")

        def kill(self):
            signals.append("kill")

    monkeypatch.setattr(rascontrol_module.psutil, "Process", ReusedWatchdog)

    result = rascontrol_module._terminate_watchdog(
        rascontrol_module._WatchdogIdentity(99, 123.0, "python.exe")
    )

    assert result.safe is True
    assert result.identity_state == "pid_reused"
    assert signals == []


def test_watchdog_cleanup_access_denied_is_unverified_and_unsignalled(monkeypatch):
    signals = []

    class UnverifiableWatchdog:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            raise rascontrol_module.psutil.AccessDenied(self.pid)

        def terminate(self):
            signals.append("terminate")

        def kill(self):
            signals.append("kill")

    monkeypatch.setattr(
        rascontrol_module.psutil,
        "Process",
        UnverifiableWatchdog,
    )

    result = rascontrol_module._terminate_watchdog(
        rascontrol_module._WatchdogIdentity(99, 123.0, "python.exe")
    )

    assert result.safe is False
    assert result.identity_state == "identity_unverified"
    assert signals == []


def test_watchdog_reverifies_before_kill_and_never_kills_reused_pid(monkeypatch):
    signals = []
    constructions = 0

    class Watchdog:
        def __init__(self, pid):
            nonlocal constructions
            self.pid = pid
            self.generation = constructions
            constructions += 1

        def create_time(self):
            return 123.0 if self.generation == 0 else 999.0

        @staticmethod
        def name():
            return "python.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            signals.append("terminate")

        def wait(self, timeout):
            signals.append(("wait", timeout))
            raise rascontrol_module.psutil.TimeoutExpired(timeout)

        def kill(self):
            signals.append("kill")

    monkeypatch.setattr(rascontrol_module.psutil, "Process", Watchdog)

    result = rascontrol_module._terminate_watchdog(
        rascontrol_module._WatchdogIdentity(99, 123.0, "python.exe")
    )

    assert result.safe is True
    assert result.identity_state == "pid_reused"
    assert signals == ["terminate", ("wait", 3)]


def test_unverified_spawned_watchdog_retains_session_lock_before_compute(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path)
    session = _tracked_lock(tmp_path)
    session.project_path = str(info.project_path)
    lock_path = tmp_path / "retained-session.lock"
    compute_called = False

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name):
            pass

        def Compute_CurrentPlan(self, *_args):
            nonlocal compute_called
            compute_called = True
            return True, 1, ("Computations Completed",), True

    def fake_open_close(
        project_path,
        version,
        operation_func,
        **kwargs,
    ):
        del project_path, version
        callback = kwargs.get("session_open_callback")
        if callback is not None:
            callback(session)
        rascontrol_module._active_sessions[session.session_id] = session
        return operation_func(FakeCom())

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(lambda plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: lock_path,
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_spawn_watchdog",
        lambda **_kwargs: rascontrol_module._WatchdogIdentity(99, None, None),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "prepare_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact cleanup must not run after unverified watchdog launch"
        ),
    )
    _disable_detailed_logging(monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="identity could not be proved"):
            RasControl.run_plan(
                "01",
                force_recompute=True,
                use_watchdog=True,
                refresh_results=False,
                blocking=True,
                controller_version="6.3.0.2",
            )
    finally:
        rascontrol_module._active_sessions.clear()

    assert compute_called is False
    assert lock_path.is_file()
    retained = rascontrol_module.SessionLock.from_file(lock_path)
    assert retained.identity_unverified is True
    assert retained.watchdog_pid == 99
    assert retained.watchdog_create_time is None
    assert retained.watchdog_name is None


def _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched):
    monkeypatch.setattr(
        rascontrol_module,
        "win32com",
        SimpleNamespace(
            client=SimpleNamespace(
                Dispatch=lambda progid: dispatched.append(progid) or fake_com
            )
        ),
    )
    monkeypatch.setattr(rascontrol_module.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(
        rascontrol_module,
        "_find_our_ras_process",
        lambda project_path, before_snapshot: (None, None, 0, None, None),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_create_session_lock",
        lambda session_id, lock_data: tmp_path / "session.lock",
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: (
            rascontrol_module._active_sessions.pop(session_id, None),
            rascontrol_module._SessionCleanupResult(
                session_id=session_id, ras_pid=None
            ),
        )[1],
    )
    rascontrol_module._active_sessions.clear()


def test_strict_close_reports_quit_failure(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")

    class FakeCom:
        def Project_Open(self, path):
            pass

        def QuitRas(self):
            raise OSError("close failed")

    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, FakeCom(), dispatched)

    with pytest.raises(RuntimeError, match=r"QuitRas\(\) failed: close failed"):
        RasControl._com_open_close(
            project_path,
            "6.3.0.2",
            lambda com_rc: "computed",
            strict_close=True,
        )

    assert dispatched == ["RAS630.HECRASController"]
    assert not rascontrol_module._active_sessions


def test_non_strict_close_retains_backward_compatibility(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(
        Project_Open=lambda path: None,
        QuitRas=lambda: (_ for _ in ()).throw(OSError("close failed")),
    )
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)

    result = RasControl._com_open_close(
        project_path,
        "6.3.0.2",
        lambda com_rc: "computed",
    )

    assert result == "computed"
    assert dispatched == ["RAS630.HECRASController"]


def test_operation_error_is_not_masked_by_quit_failure(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(
        Project_Open=lambda path: None,
        QuitRas=lambda: (_ for _ in ()).throw(OSError("close failed")),
    )
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)

    def fail_operation(com_rc):
        raise ValueError("compute failed")

    with pytest.raises(ValueError, match="compute failed"):
        RasControl._com_open_close(
            project_path,
            "6.3.0.2",
            fail_operation,
            strict_close=True,
        )


def test_strict_close_reports_surviving_owned_process(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(Project_Open=lambda path: None, QuitRas=lambda: None)
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: rascontrol_module._SessionCleanupResult(
            session_id=session_id,
            ras_pid=4321,
            process_detected=True,
            process_survived=True,
            lock_retained=True,
        ),
    )

    with pytest.raises(RuntimeError, match="owned ras.exe PID 4321 survived"):
        RasControl._com_open_close(
            project_path,
            "6.3.0.2",
            lambda com_rc: "computed",
            strict_close=True,
        )
    rascontrol_module._active_sessions.clear()


def test_required_safe_close_reports_survivor_in_non_strict_mode(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(Project_Open=lambda path: None, QuitRas=lambda: None)
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)
    cleanup_result = rascontrol_module._SessionCleanupResult(
        session_id="unsafe-session",
        ras_pid=4321,
        process_detected=True,
        process_survived=True,
        lock_retained=True,
    )
    outcomes = []
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda _session_id: cleanup_result,
    )

    with pytest.raises(RuntimeError, match="owned ras.exe PID 4321 survived"):
        RasControl._com_open_close(
            project_path,
            "6.3.0.2",
            lambda com_rc: "computed",
            require_safe_close=True,
            close_outcome_callback=lambda *args: outcomes.append(args),
        )

    assert outcomes == [(False, cleanup_result, None)]
    rascontrol_module._active_sessions.clear()


def test_required_safe_close_rejects_failed_quit_without_owned_pid(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(
        Project_Open=lambda path: None,
        QuitRas=lambda: (_ for _ in ()).throw(OSError("close failed")),
    )
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)

    with pytest.raises(RuntimeError, match="process exit could not be confirmed"):
        RasControl._com_open_close(
            project_path,
            "6.3.0.2",
            lambda com_rc: "computed",
            require_safe_close=True,
        )


def _tracked_lock(tmp_path, pid=4321):
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"tracked Controller image")
    return rascontrol_module.SessionLock(
        python_pid=123,
        ras_pid=pid,
        project_path=str(tmp_path / "Demo.prj"),
        ras_version="6.3.0.2",
        session_id="cleanup-session",
        start_time=0.0,
        python_exe="python.exe",
        hostname="test-host",
        detection_confidence=100,
        ras_create_time=123.5,
        ras_executable_path=str(executable),
        ras_executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    )


def test_session_lock_migrates_old_json_without_process_provenance(tmp_path):
    payload = _tracked_lock(tmp_path).to_json()
    raw = json.loads(payload)
    raw.pop("ras_create_time")
    raw.pop("ras_executable_path")
    raw.pop("ras_executable_sha256")

    restored = rascontrol_module.SessionLock.from_json(json.dumps(raw))

    assert restored.ras_pid == 4321
    assert restored.ras_create_time is None
    assert restored.ras_executable_path is None
    assert restored.ras_executable_sha256 is None
    assert restored.identity_unverified is True
    assert restored.validation_error == (
        "legacy lock lacks complete Ras.exe process provenance"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_time", float("nan")),
        ("ras_create_time", float("inf")),
        ("watchdog_create_time", float("-inf")),
    ],
)
def test_session_lock_constructor_rejects_nonfinite_values(
    tmp_path,
    field,
    value,
):
    payload = json.loads(_tracked_lock(tmp_path).to_json())
    if field == "watchdog_create_time":
        payload["watchdog_pid"] = 99
        payload["watchdog_name"] = "python.exe"
    payload[field] = value

    with pytest.raises(ValueError, match="must be finite"):
        rascontrol_module.SessionLock(**payload)


def test_session_lock_to_json_revalidates_mutation_and_disallows_nan(tmp_path):
    lock = _tracked_lock(tmp_path)
    lock.start_time = float("nan")

    with pytest.raises(ValueError, match="must be finite"):
        lock.to_json()


def test_malformed_legacy_lock_is_quarantined_and_never_unlinked(
    monkeypatch,
    tmp_path,
):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    lock_path = lock_dir / "rasctl_123_legacy.lock"
    raw = json.loads(_tracked_lock(tmp_path).to_json())
    raw["start_time"] = float("nan")
    raw["ras_create_time"] = "not-a-create-time"
    lock_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(rascontrol_module, "LOCK_DIR", lock_dir)

    quarantined = rascontrol_module.SessionLock.from_file(lock_path)
    orphans = RasControl.scan_orphans()

    assert quarantined.identity_unverified is True
    assert quarantined.ras_pid is None
    assert quarantined.validation_error
    assert "NaN" not in quarantined.to_json()
    assert rascontrol_module._classify_lock_file(quarantined) == (
        "identity_unverified"
    )
    assert orphans == []
    assert lock_path.is_file()


def test_find_controller_process_returns_atomic_exact_identity(
    monkeypatch,
    tmp_path,
):
    created = rascontrol_module.time.time()
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"exact running image")

    class ExactProcess:
        pid = 10

        @staticmethod
        def create_time():
            return created

        @staticmethod
        def name():
            return "Ras.exe"

        @staticmethod
        def exe():
            return str(executable)

    exact = SimpleNamespace(
        pid=10,
        info={
            "pid": 10,
            "name": "Ras.exe",
            "cmdline": ["Ras.exe", r"C:\Models\Demo.prj"],
            "create_time": created,
            "cwd": r"C:\Models",
            "exe": str(executable),
        },
    )
    basename_collision = SimpleNamespace(
        pid=11,
        info={
            "pid": 11,
            "name": "Ras.exe",
            "cmdline": ["Ras.exe", r"C:\Other\Demo.prj.backup"],
            "create_time": created + 0.1,
            "cwd": r"C:\Other",
            "exe": str(executable),
        },
    )
    monkeypatch.setattr(rascontrol_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        rascontrol_module.psutil,
        "process_iter",
        lambda _attrs: [basename_collision, exact],
    )
    monkeypatch.setattr(
        rascontrol_module.psutil,
        "Process",
        lambda pid: ExactProcess() if pid == 10 else pytest.fail("wrong PID"),
    )

    (
        pid,
        create_time,
        confidence,
        executable_path,
        executable_sha256,
    ) = rascontrol_module._find_our_ras_process(
        rascontrol_module.Path(r"C:\Models\Demo.prj"),
        {},
    )

    assert (pid, create_time) == (10, created)
    assert confidence >= 90
    assert rascontrol_module.Path(executable_path).samefile(executable)
    assert executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


def test_controller_image_proof_rejects_forged_snapshot_path(
    monkeypatch,
    tmp_path,
):
    actual = tmp_path / "actual" / "Ras.exe"
    claimed = tmp_path / "claimed" / "Ras.exe"
    actual.parent.mkdir()
    claimed.parent.mkdir()
    actual.write_bytes(b"actual")
    claimed.write_bytes(b"claimed")

    class Process:
        pid = 10

        @staticmethod
        def create_time():
            return 123.5

        @staticmethod
        def name():
            return "Ras.exe"

        @staticmethod
        def exe():
            return str(actual)

    monkeypatch.setattr(rascontrol_module.psutil, "Process", lambda _pid: Process())

    with pytest.raises(RuntimeError, match="path changed"):
        rascontrol_module._prove_ras_process_image(
            pid=10,
            create_time=123.5,
            snapshot_executable=str(claimed),
        )


def test_controller_image_proof_rejects_pid_reuse_after_hash(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"stable bytes")

    class ReusedProcess:
        pid = 10

        def __init__(self):
            self.reads = 0

        def create_time(self):
            self.reads += 1
            return 123.5 if self.reads == 1 else 999.0

        @staticmethod
        def name():
            return "Ras.exe"

        @staticmethod
        def exe():
            return str(executable)

    process = ReusedProcess()
    monkeypatch.setattr(rascontrol_module.psutil, "Process", lambda _pid: process)

    with pytest.raises(RuntimeError, match="PID identity changed"):
        rascontrol_module._prove_ras_process_image(
            pid=10,
            create_time=123.5,
            snapshot_executable=str(executable),
        )


def test_stable_controller_hash_rejects_file_identity_race(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"stable bytes")
    identities = iter(((1, 2, 12, 3, 4), (1, 2, 13, 5, 6)))
    monkeypatch.setattr(
        rascontrol_module,
        "_file_identity",
        lambda _stat: next(identities),
    )

    with pytest.raises(RuntimeError, match="changed while hashing"):
        rascontrol_module._stable_file_sha256(executable)


def test_classify_lock_retains_identity_evidence_on_access_denied(
    monkeypatch,
    tmp_path,
):
    lock = _tracked_lock(tmp_path)
    lock.hostname = rascontrol_module.socket.gethostname()

    def process_for_pid(pid):
        if pid == lock.python_pid:
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        raise rascontrol_module.psutil.AccessDenied(pid)

    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_for_pid)

    assert rascontrol_module._classify_lock_file(lock) == "identity_unverified"


def test_cleanup_never_signals_reused_pid(monkeypatch, tmp_path):
    signals = []

    class ReusedProcess:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def name(self):
            return "ras.exe"

        def create_time(self):
            return 999.0

        def terminate(self):
            signals.append("terminate")

        def kill(self):
            signals.append("kill")

    lock = _tracked_lock(tmp_path)
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", ReusedProcess)
    monkeypatch.setattr(
        rascontrol_module,
        "_remove_session_lock",
        lambda _session_id: None,
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is True
    assert result.process_detected is False
    assert signals == []
    assert lock.session_id not in rascontrol_module._active_sessions


def test_cleanup_retains_lock_when_watchdog_identity_is_unverifiable(
    monkeypatch,
    tmp_path,
):
    lock = _tracked_lock(tmp_path)
    lock.ras_pid = None
    lock.ras_create_time = None
    lock.ras_executable_path = None
    lock.ras_executable_sha256 = None
    lock.watchdog_pid = 99
    lock.watchdog_create_time = 123.0
    lock.watchdog_name = "python.exe"
    lock_path = tmp_path / "retained-watchdog.lock"
    lock_path.write_text(lock.to_json(), encoding="utf-8")
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: lock_path,
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_terminate_watchdog",
        lambda _identity: rascontrol_module._WatchdogCleanupResult(
            pid=99,
            identity_state="identity_unverified",
            error="AccessDenied",
        ),
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is False
    assert result.process_survived is True
    assert result.lock_retained is True
    assert lock.identity_unverified is True
    assert "AccessDenied" in lock.validation_error
    assert lock.session_id in rascontrol_module._active_sessions
    assert lock_path.is_file()


def test_com_session_preserves_failed_identity_proof_as_absent(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(
        Project_Open=lambda _path: None,
        QuitRas=lambda: None,
    )
    observed_locks = []
    observed_sessions = []

    monkeypatch.setattr(
        rascontrol_module,
        "win32com",
        SimpleNamespace(
            client=SimpleNamespace(Dispatch=lambda _progid: fake_com)
        ),
    )
    monkeypatch.setattr(rascontrol_module.psutil, "process_iter", lambda _attrs: [])
    monkeypatch.setattr(
        rascontrol_module,
        "_find_our_ras_process",
        lambda *_args, **_kwargs: (None, None, 0, None, None),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_create_session_lock",
        lambda _session_id, lock: observed_locks.append(lock)
        or (tmp_path / "session.lock"),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: (
            rascontrol_module._active_sessions.pop(session_id, None),
            rascontrol_module._SessionCleanupResult(
                session_id=session_id,
                ras_pid=None,
            ),
        )[1],
    )

    result = RasControl._com_open_close(
        project_path,
        "6.3.0.2",
        lambda _controller: "done",
        session_open_callback=observed_sessions.append,
    )

    assert result == "done"
    assert len(observed_locks) == 1
    assert observed_locks[0].ras_pid is None
    assert observed_locks[0].ras_create_time is None
    assert observed_locks[0].ras_executable_path is None
    assert observed_locks[0].ras_executable_sha256 is None
    assert observed_sessions == observed_locks


def test_cleanup_force_kills_then_verifies_exit(monkeypatch, tmp_path):
    events = []

    class FakeProcess:
        running = True

        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return self.running

        def name(self):
            return "ras.exe"

        def create_time(self):
            return 123.5

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

        def wait(self, timeout):
            events.append(("wait", timeout))
            if "kill" not in events:
                raise rascontrol_module.psutil.TimeoutExpired(timeout)
            self.running = False

    lock = _tracked_lock(tmp_path)
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", FakeProcess)
    monkeypatch.setattr(
        rascontrol_module, "_remove_session_lock", lambda session_id: None
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is True
    assert result.process_detected is True
    assert result.killed is True
    assert result.process_survived is False
    assert lock.session_id not in rascontrol_module._active_sessions
    assert events == ["terminate", ("wait", 5), "kill", ("wait", 5)]


def test_cleanup_retains_session_evidence_when_process_survives(monkeypatch, tmp_path):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def name(self):
            return "ras.exe"

        def create_time(self):
            return 123.5

        def terminate(self):
            raise rascontrol_module.psutil.AccessDenied(self.pid)

    lock = _tracked_lock(tmp_path)
    lock_path = tmp_path / "session.lock"
    lock_path.write_text("evidence", encoding="utf-8")
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", FakeProcess)
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda session_id: lock_path,
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is False
    assert result.process_survived is True
    assert result.lock_retained is True
    assert lock.session_id in rascontrol_module._active_sessions
    assert lock_path.exists()
