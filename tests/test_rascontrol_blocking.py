import importlib
import json
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
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)

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
    assert result.execution_details["duration_seconds"] >= 0
    assert json.loads(json.dumps(result.execution_details)) == result.execution_details
    success, messages = result
    assert success is True
    assert messages == result.messages
    assert ("open", info.project_path, "6.3.0.2", True) in calls
    assert ("compute", (None, None, True)) in calls


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
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)

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
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)

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
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)

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


def test_watchdog_starts_before_blocking_compute(monkeypatch, tmp_path):
    info = _project_info(tmp_path)
    events = []
    session = SimpleNamespace(
        project_path=str(info.project_path),
        ras_pid=4321,
        session_id="session-1",
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
        rascontrol_module._active_sessions[session.session_id] = session
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)
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
        lambda **kwargs: events.append("watchdog_start") or 99,
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_terminate_watchdog",
        lambda pid: events.append("watchdog_stop"),
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
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, SimpleNamespace(), None)

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
        lambda project_path, before_snapshot: (None, 0),
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
    )


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
