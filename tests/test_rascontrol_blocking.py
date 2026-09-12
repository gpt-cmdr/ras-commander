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
    major = int(version.split(".", 1)[0])
    result_path = tmp_path / ("Demo.O01" if major < 5 else "Demo.p01.hdf")
    result_path.write_bytes(b"deterministic fake result")
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
        identity_state="absent",
    )


def test_exact_630_identity_preserves_release_specific_mapping():
    assert RasControl.get_controller_progid("6.3") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("6.3.1") == "RAS631.HECRASController"
    assert RasControl.get_controller_progid("6.3.0") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("6.3.0.2") == "RAS630.HECRASController"
    assert RasControl.get_controller_progid("630") == "RAS630.HECRASController"
    with pytest.raises(ValueError, match="not supported"):
        RasControl.get_controller_progid("9.9")


def test_every_supported_controller_has_an_execution_capability_contract():
    assert set(RasControl.VERSION_MAP.values()) == set(
        RasControl._CONTROLLER_CAPABILITIES
    )


def test_3x_alias_inherits_resolved_41_controller_capabilities():
    progid = RasControl.get_controller_progid("3.1")
    capabilities = RasControl._CONTROLLER_CAPABILITIES[progid]
    assert progid == "RAS41.HECRASController"
    assert capabilities.compute_current_plan_argument_count == 2
    assert capabilities.completion_method == "Compute_CurrentPlan_blocking_return"
    assert capabilities.supports_quit_ras is False


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


@pytest.mark.parametrize(
    ("close_error", "expected_close_method"),
    [
        (None, "quit_ras"),
        (OSError("QuitRas failed"), "owned_process_cleanup_after_quit_ras_failure"),
    ],
)
def test_current_controller_result_reports_null_cleanup_records(
    monkeypatch,
    tmp_path,
    close_error,
    expected_close_method,
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
                close_outcome_callback(True, _owned_cleanup(), close_error)

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
    assert result.execution_details["current_check_performed"] is True
    assert result.execution_details["current_check_close_safe"] is True
    assert result.execution_details["current_check_close_method"] == expected_close_method
    assert result.execution_details["completion_method"] is None


def test_controller_success_without_selected_artifact_fails_closed(
    monkeypatch, tmp_path
):
    info = _project_info(tmp_path)
    selected = tmp_path / "Demo.p01.hdf"

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name):
            return None
        def Compute_CurrentPlan(self, *_args):
            selected.unlink(missing_ok=True)
            return True, 1, ("Computations Completed",), True

    def fake_open_close(
        project_path, _version, operation_func, *, close_outcome_callback=None,
        **kwargs
    ):
        _emit_owned_session(kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(
        RasControl, "_get_project_info",
        staticmethod(lambda _plan, ras_object=None: info),
    )
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)

    with pytest.raises(RuntimeError, match="result artifact was not created"):
        RasControl.run_plan(
            "01", force_recompute=True, use_watchdog=False,
            refresh_results=False, blocking=True, controller_version="6.3.0.2",
        )


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


@pytest.mark.parametrize(
    ("version", "expected_progid", "expected_resolved"),
    [
        ("4.0", "RAS400.HECRASController", "4.0"),
        ("4.1.0", "RAS41.HECRASController", "4.1"),
    ],
)
@pytest.mark.parametrize("blocking", [False, True])
def test_legacy_run_uses_two_argument_blocking_return_contract(
    monkeypatch,
    tmp_path,
    version,
    expected_progid,
    expected_resolved,
    blocking,
):
    info = _project_info(tmp_path, version=version)
    calls = []

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            calls.append(("plan", plan_name))

        def Compute_CurrentPlan(self, *args):
            calls.append(("compute", args))
            return True, 2, ("Computing", "Computations Completed")

        def Compute_IsStillComputing(self):
            pytest.fail("Legacy blocking return must never be polled")

        def __getattr__(self, name):
            if name in {"Compute_Complete", "QuitRas"}:
                raise AssertionError(f"legacy Controller must not access {name}")
            raise AttributeError(name)

    def fake_open_close(
        project_path,
        requested_version,
        operation_func,
        *,
        strict_close=False,
        close_outcome_callback=None,
        **kwargs,
    ):
        calls.append(("open", project_path, requested_version, strict_close))
        _emit_owned_session(kwargs, project_path=project_path)
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
    monkeypatch.setattr(rascontrol_module.time, "sleep", lambda _seconds: None)
    _disable_detailed_logging(monkeypatch)

    result = RasControl.run_plan(
        "01",
        force_recompute=True,
        use_watchdog=False,
        refresh_results=False,
        controller_version=version,
        strict_close=True,
        blocking=blocking,
    )

    assert result.success is True
    assert result.execution_details["compute_mode"] == "blocking"
    assert result.execution_details["controller_inherently_blocking"] is True
    assert result.execution_details["blocking_requested"] is blocking
    assert result.execution_details["compute_current_plan_argument_count"] == 2
    assert result.execution_details["completion_method"] == (
        "Compute_CurrentPlan_blocking_return"
    )
    assert result.execution_details["controller_quit_supported"] is False
    assert result.execution_details["controller_close_method"] == (
        "owned_process_cleanup"
    )
    assert result.execution_details["controller_progid"] == expected_progid
    assert result.execution_details["resolved_controller_version"] == (
        expected_resolved
    )
    assert result.execution_details["poll_count"] == 0
    assert ("legacy_poll",) not in calls
    assert ("compute", (None, None)) in calls


def test_legacy_malformed_blocking_return_preserves_recreated_hdf(
    monkeypatch,
    tmp_path,
):
    info = _project_info(tmp_path, version="4.1.0")
    legacy = tmp_path / "Demo.O01"
    hdf = tmp_path / "Demo.p01.hdf"
    hdf.write_bytes(b"stale opposing hdf")

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name):
            return None

        def Compute_CurrentPlan(self, *args):
            assert args == (None, None)
            assert not hdf.exists()
            legacy.write_bytes(b"possibly incomplete legacy output")
            hdf.write_bytes(b"possibly active opposing writer")
            return True, 1

        def Compute_IsStillComputing(self):
            pytest.fail("Legacy blocking return must never be polled")

        def __getattr__(self, name):
            if name in {"Compute_Complete", "QuitRas"}:
                raise AssertionError(f"legacy Controller must not access {name}")
            raise AttributeError(name)

    def fake_open_close(
        project_path,
        _version,
        operation_func,
        *,
        close_outcome_callback=None,
        **kwargs,
    ):
        _emit_owned_session(kwargs, project_path=project_path)
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

    with pytest.raises(
        RuntimeError,
        match="Blocking Compute_CurrentPlan returned an unsupported result",
    ):
        RasControl.run_plan(
            "01",
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
            controller_version="4.1.0",
            strict_close=True,
        )

    assert legacy.read_bytes() == b"possibly incomplete legacy output"
    assert hdf.read_bytes() == b"possibly active opposing writer"


@pytest.mark.parametrize("version", ["4.0", "4.1", "6.3.0.2"])
def test_blocking_return_deadline_rejects_late_completion(
    monkeypatch, tmp_path, version
):
    info = _project_info(tmp_path, version=version)
    clock = iter([0.0, 1.1])

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name): return None
        def Compute_CurrentPlan(self, *_args): return True, 1, ("Complete",)
        def Compute_IsStillComputing(self): pytest.fail("No polling of blocking call")
        def Compute_Complete(self): pytest.fail("No polling of blocking call")

    def fake_open_close(
        project_path, _version, operation_func, *, close_outcome_callback=None,
        **kwargs
    ):
        _emit_owned_session(kwargs, project_path=project_path)
        try:
            return operation_func(FakeCom())
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(True, _owned_cleanup(), None)

    monkeypatch.setattr(RasControl, "_get_project_info", staticmethod(lambda *_a, **_k: info))
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    monkeypatch.setattr(rascontrol_module.time, "monotonic", lambda: next(clock))
    _disable_detailed_logging(monkeypatch)

    with pytest.raises(TimeoutError, match="exceeded max_runtime"):
        RasControl.run_plan(
            "01", force_recompute=True, use_watchdog=False, blocking=True,
            refresh_results=False, controller_version=version, max_runtime=1.0,
        )


def test_legacy_watchdog_cleanup_is_deferred_until_controller_release(
    monkeypatch, tmp_path
):
    info = _project_info(tmp_path, version="4.1.0")
    events = []
    session = _emit_owned_session({}, project_path=info.project_path)
    session.watchdog_pid = None
    session.watchdog_create_time = None
    session.watchdog_name = None
    session.identity_unverified = False
    session.validation_error = None
    watchdog_identity = rascontrol_module._WatchdogIdentity(
        pid=99, create_time=456.0, name="python.exe"
    )

    class FakeCom:
        def Plan_SetCurrent(self, _plan_name): return None
        def Compute_CurrentPlan(self, *_args):
            events.append("compute")
            return True, 1, ("Complete",)
        def Compute_IsStillComputing(self): return False

    monkeypatch.setattr(rascontrol_module, "_spawn_watchdog", lambda **_k: watchdog_identity)
    def absent_process(pid):
        raise rascontrol_module.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", absent_process)
    def terminate_watchdog(identity):
        assert events[-2:] == ["controller_proxy_released", "ras_cleanup"]
        events.append("watchdog_stop")
        return rascontrol_module._WatchdogCleanupResult(
            pid=identity.pid, identity_state="terminated", terminated=True
        )
    monkeypatch.setattr(rascontrol_module, "_terminate_watchdog", terminate_watchdog)

    def fake_open_close(
        _project_path, _version, operation_func, *, close_outcome_callback=None,
        session_open_callback=None, **_kwargs
    ):
        rascontrol_module._active_sessions[session.session_id] = session
        if session_open_callback is not None:
            session_open_callback(session)
        try:
            result = operation_func(FakeCom())
        finally:
            events.append("controller_proxy_released")
            events.append("ras_cleanup")
            cleanup = rascontrol_module._cleanup_session(session.session_id)
            if close_outcome_callback is not None:
                close_outcome_callback(True, cleanup, None)
        return result

    monkeypatch.setattr(RasControl, "_get_project_info", staticmethod(lambda *_a, **_k: info))
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)
    result = RasControl.run_plan(
        "01", force_recompute=True, use_watchdog=True, refresh_results=False,
        controller_version="4.1.0", strict_close=True,
    )
    assert result.success is True
    assert events == ["compute", "controller_proxy_released", "ras_cleanup", "watchdog_stop"]


def test_legacy_blocking_capability_means_no_configurable_third_argument():
    for progid in ("RAS400.HECRASController", "RAS41.HECRASController"):
        capabilities = RasControl._CONTROLLER_CAPABILITIES[progid]
        assert capabilities.supports_blocking is False
        assert capabilities.compute_current_plan_argument_count == 2
        assert capabilities.completion_method == "Compute_CurrentPlan_blocking_return"


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
    assert result.execution_details["watchdog_pid"] == 99
    assert result.execution_details["watchdog_create_time"] == 123.0
    assert result.execution_details["watchdog_name"] == "python.exe"
    assert events == ["watchdog_start", "compute", "watchdog_stop"]


@pytest.mark.parametrize("worker_pid", [99, 100])
def test_watchdog_worker_receives_exact_parent_and_ras_identity(
    monkeypatch,
    tmp_path,
    worker_pid,
):
    launches = []

    class WatchdogProcess:
        pid = 99

    def launch(argv, **kwargs):
        launches.append((argv, kwargs))
        arguments = dict(zip(argv[2::2], argv[3::2]))
        Path(arguments["--identity-file"]).write_text(json.dumps({
            "schema": "ras-commander-orphan-watchdog/v1",
            "token": arguments["--identity-token"],
            "pid": worker_pid, "create_time": 123.0, "name": "python.exe",
            "exe": rascontrol_module.sys.executable,
            "parent_pid": 12 if worker_pid == 99 else 99,
            "argv": argv[1:],
        }), encoding="utf-8")
        return WatchdogProcess()

    monkeypatch.setattr(rascontrol_module.subprocess, "Popen", launch)

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

        def exe(self):
            return rascontrol_module.sys.executable

        def cmdline(self):
            return launches[0][0]

        def ppid(self):
            return 99 if self.pid == 100 else 12

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
        worker_pid, 123.0, "python.exe"
    )
    argv = launches[0][0]
    assert Path(argv[1]).name == "_orphan_watchdog.py"
    arguments = dict(zip(argv[2::2], argv[3::2]))
    assert Path(arguments.pop("--identity-file")).is_file()
    assert len(arguments.pop("--identity-token")) == 32
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


def test_requested_watchdog_requires_exact_session_before_compute(monkeypatch, tmp_path):
    info = _project_info(tmp_path)

    class FakeCom:
        def Plan_SetCurrent(self, plan_name):
            pass

        def Compute_CurrentPlan(self, *args):
            pytest.fail("An unprotected requested-watchdog run must not compute")

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

    with pytest.raises(RuntimeError, match="Requested watchdog requires an exact"):
        RasControl.run_plan(
            "01", force_recompute=True, use_watchdog=True,
            refresh_results=False, blocking=True, controller_version="6.3.0.2",
        )


def test_actual_watchdog_python_child_handshake_and_exact_cleanup(monkeypatch, tmp_path):
    """Launch only the Python watchdog, with a proved-absent artificial RAS PID."""
    absent_ras_pid = 2147483647
    assert rascontrol_module.psutil.pid_exists(absent_ras_pid) is False
    lock_file = tmp_path / "watchdog-only-test.lock"
    lock_file.write_text("watchdog process transport test; no HEC-RAS", encoding="ascii")
    popen = rascontrol_module.subprocess.Popen
    launched = []

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(rascontrol_module.subprocess, "Popen", launch)
    identity = None
    try:
        identity = rascontrol_module._spawn_watchdog(
            parent_pid=rascontrol_module.os.getpid(), ras_pid=absent_ras_pid,
            ras_create_time=1.0, max_runtime=1.0, lock_file_path=lock_file,
        )
        assert identity is not None and identity.complete
        records = list(tmp_path.glob("*.identity.json"))
        assert len(records) == 1
        payload = json.loads(records[0].read_text(encoding="utf-8"))
        assert payload["pid"] == identity.pid
        assert payload["create_time"] == identity.create_time
        assert payload["name"] == identity.name
        assert payload["parent_pid"] in {launched[0].pid, rascontrol_module.os.getpid()}
        state, _ = rascontrol_module._watchdog_process_state(identity)
        assert state == "exact"
        cleanup = rascontrol_module._terminate_watchdog(identity)
        assert cleanup.safe is True
        assert cleanup.pid == identity.pid
        state, _ = rascontrol_module._watchdog_process_state(identity)
        assert state in {"absent", "pid_reused"}
    finally:
        if identity is not None and identity.complete:
            assert rascontrol_module._terminate_watchdog(identity).safe is True
        # Also reap a Windows venv launcher after its actual worker exits. If
        # identity could not be proved, allow only the worker's own one-second
        # timeout (observed at its five-second tick); never signal an unknown PID.
        for process in launched:
            process.wait(timeout=7)


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


@pytest.mark.parametrize("corruption", [
    "token", "schema", "argv", "exe", "parent_pid", "zero_time",
    "live_arguments", "live_parent", "reused_after_read",
])
def test_watchdog_handshake_rejects_unproved_worker(monkeypatch, tmp_path, corruption):
    argv = [str(tmp_path / "python.exe"), str(tmp_path / "_orphan_watchdog.py"),
            "--identity-token", "a" * 32]
    payload = {
        "schema": "ras-commander-orphan-watchdog/v1", "token": "a" * 32,
        "pid": 99, "create_time": 123.0, "name": "python.exe",
        "exe": argv[0], "parent_pid": 12, "argv": argv[1:],
    }
    if corruption in {"token", "schema", "exe"}:
        payload[corruption] = "different"
    elif corruption == "argv":
        payload["argv"] = ["another_worker.py"]
    elif corruption == "parent_pid":
        payload["parent_pid"] = 41
    elif corruption == "zero_time":
        payload["create_time"] = 0
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(json.dumps(payload), encoding="utf-8")
    lookups = []

    class FakeWorker:
        def __init__(self, pid):
            self.pid = pid
            lookups.append(pid)

        def create_time(self):
            return 999 if corruption == "reused_after_read" and len(lookups) > 1 else 123.0

        def name(self): return "python.exe"
        def is_running(self): return True
        def exe(self): return argv[0]
        def cmdline(self):
            return [argv[0], "other.py"] if corruption == "live_arguments" else argv
        def ppid(self): return 41 if corruption == "live_parent" else 12

    monkeypatch.setattr(rascontrol_module.psutil, "Process", FakeWorker)
    with pytest.raises(ValueError):
        rascontrol_module._read_watchdog_worker_identity(
            identity_file, token="a" * 32, argv=argv,
            launcher=rascontrol_module._WatchdogIdentity(99, 123.0, "python.exe"),
            parent_pid=12,
        )
    assert identity_file.is_file(), "Uncertain identity evidence must be preserved"


@pytest.mark.parametrize("outcome", ["success", "open_error", "interrupt", "start_failure", "stop_failure"])
def test_exact_dialog_observer_lifecycle_surrounds_project_open_and_cleanup(
    monkeypatch, tmp_path, outcome
):
    watchdog_module = importlib.import_module("ras_commander.RasDialogWatchdog")
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"deterministic exact Controller image")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    events = []
    evidence = []

    def project_open(path):
        assert path == str(project_path)
        events.append("open")
        assert "observer_start" in events
        if outcome == "open_error":
            raise OSError("Project_Open failed")

    fake_com = SimpleNamespace(Project_Open=project_open)
    _patch_com_session(monkeypatch, tmp_path, fake_com, [])
    monkeypatch.setattr(
        rascontrol_module, "_find_our_ras_process",
        lambda *_args: (4321, 123.5, 100, str(executable), digest),
    )

    class FakeObserver:
        def __init__(self, identity):
            assert (identity.pid, identity.create_time) == (4321, 123.5)
            assert identity.executable_path == executable
            assert identity.executable_sha256 == digest

        def _start(self):
            events.append("observer_start")
            return outcome != "start_failure"

        def _stop_observing(self):
            events.append("observer_stop")

        def _evidence(self):
            return {
                "scope": "exact_controller_identity", "process_discovery": False,
                "started": outcome != "start_failure",
                "stop_confirmed": outcome != "stop_failure",
                "thread_alive": outcome == "stop_failure",
                "observations": [{"classification": "unknown_preserved", "action": "none"}],
            }

    monkeypatch.setattr(watchdog_module, "_ExactDialogObserver", FakeObserver)

    def cleanup(session_id):
        events.append("cleanup")
        rascontrol_module._active_sessions.pop(session_id, None)
        return _owned_cleanup()

    monkeypatch.setattr(rascontrol_module, "_cleanup_session", cleanup)

    def operation(com):
        assert com is fake_com
        events.append("compute")
        if outcome == "interrupt":
            raise KeyboardInterrupt("outer supervisor stopped compute")
        return "computed"

    def run():
        return RasControl._com_open_close(
            project_path, "4.1", operation, strict_close=True,
            observe_dialogs=True, dialog_observation_callback=evidence.append,
        )

    if outcome == "success":
        assert run() == "computed"
    else:
        expected = {"open_error": OSError, "interrupt": KeyboardInterrupt,
                    "start_failure": RuntimeError, "stop_failure": RuntimeError}[outcome]
        with pytest.raises(expected) as raised:
            run()
        assert raised.value.execution_details["dialog_observation"] == evidence[-1]
    assert events[-2:] == ["observer_stop", "cleanup"]
    assert evidence[-1]["observations"][0]["action"] == "none"
    assert not rascontrol_module._active_sessions
    if outcome == "start_failure":
        assert "open" not in events


@pytest.mark.parametrize("outcome", ["success", "no_output", "postclose_failure"])
def test_run_plan_retains_opt_in_dialog_evidence_after_close(monkeypatch, tmp_path, outcome):
    info = _project_info(tmp_path, version="4.1")
    observed = {"scope": "exact_controller_identity", "stop_confirmed": True,
                "thread_alive": False, "observations": []}

    class FakeCom:
        def Plan_SetCurrent(self, _name): pass
        def Compute_CurrentPlan(self, *args):
            assert args == (None, None)
            return True, 0, ()

    def fake_open_close(path, _version, operation, **kwargs):
        assert kwargs["observe_dialogs"] is True
        _emit_owned_session(kwargs, project_path=path)
        result = operation(FakeCom())
        kwargs["dialog_observation_callback"](observed)
        kwargs["close_outcome_callback"](True, _owned_cleanup(), None)
        return result

    monkeypatch.setattr(RasControl, "_get_project_info", staticmethod(lambda *_a, **_k: info))
    monkeypatch.setattr(RasControl, "_com_open_close", staticmethod(fake_open_close))
    _disable_detailed_logging(monkeypatch)
    original_error = RuntimeError("post-close inspection failed")
    if outcome == "no_output":
        (tmp_path / "Demo.O01").unlink()
    elif outcome == "postclose_failure":
        original_error.execution_details = {"original_detail": "preserve me"}
        preflight = rascontrol_module._inspect_controller_post_close_processes
        inspection_count = 0
        def fail_inspection(**_kwargs):
            nonlocal inspection_count
            inspection_count += 1
            if inspection_count == 1:
                return preflight(**_kwargs)
            raise original_error
        monkeypatch.setattr(
            rascontrol_module, "_inspect_controller_post_close_processes", fail_inspection
        )

    def run():
        return RasControl.run_plan(
            "01", force_recompute=True, use_watchdog=False, refresh_results=False,
            controller_version="4.1", observe_dialogs=True,
        )

    if outcome == "success":
        details = run().execution_details
    else:
        with pytest.raises(RuntimeError) as raised:
            run()
        if outcome == "postclose_failure":
            assert raised.value is original_error
            assert raised.value.execution_details["original_detail"] == "preserve me"
        else:
            assert "result artifact was not created" in str(raised.value)
        details = raised.value.execution_details
    assert details["dialog_observation_requested"] is True
    assert details["dialog_observation"] == observed


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
                session_id=session_id, ras_pid=None, identity_state="absent"
            ),
        )[1],
    )
    rascontrol_module._active_sessions.clear()


def test_legacy_strict_close_uses_exact_owned_process_cleanup(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"legacy Controller image")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    fake_com = SimpleNamespace(Project_Open=lambda _path: None)
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)
    monkeypatch.setattr(
        rascontrol_module,
        "_find_our_ras_process",
        lambda _project_path, _before_snapshot: (
            4321,
            123.5,
            100,
            str(executable),
            executable_sha256,
        ),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: (
            rascontrol_module._active_sessions.pop(session_id, None),
            rascontrol_module._SessionCleanupResult(
                session_id=session_id,
                ras_pid=4321,
                process_detected=True,
                terminated=True,
                identity_state="terminated",
            ),
        )[1],
    )

    result = RasControl._com_open_close(
        project_path,
        "4.1.0",
        lambda _com_rc: "computed",
        strict_close=True,
    )

    assert result == "computed"
    assert dispatched == ["RAS41.HECRASController"]
    assert not rascontrol_module._active_sessions


def test_legacy_close_never_accesses_nonexistent_quit_ras(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")

    class FakeLegacyCom:
        def Project_Open(self, _path):
            return None

        def PlanOutput_IsCurrent(self):
            return True

        def __getattr__(self, name):
            if name == "QuitRas":
                raise AssertionError("legacy Controller must not access QuitRas")
            raise AttributeError(name)

    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, FakeLegacyCom(), dispatched)
    monkeypatch.setattr(
        rascontrol_module,
        "_find_our_ras_process",
        lambda *_args: (4321, 123.5, 100, str(tmp_path / "Ras.exe"), "0" * 64),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: rascontrol_module._SessionCleanupResult(
            session_id=session_id, ras_pid=4321, terminated=True,
            identity_state="terminated",
        ),
    )
    assert RasControl._com_open_close(
        project_path, "4.1", lambda controller: controller.PlanOutput_IsCurrent(),
        strict_close=True
    ) is True


def test_legacy_safe_close_rejects_unidentified_owned_process(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(Project_Open=lambda _path: None)
    dispatched = []
    _patch_com_session(monkeypatch, tmp_path, fake_com, dispatched)

    with pytest.raises(
        RuntimeError,
        match="Controller close and owned-process exit could not be confirmed",
    ):
        RasControl._com_open_close(
            project_path,
            "4.1.0",
            lambda _com_rc: "computed",
            strict_close=True,
        )

    assert dispatched == ["RAS41.HECRASController"]
    assert not rascontrol_module._active_sessions


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
            identity_state="identity_unverified",
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
        identity_state="identity_unverified",
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
                identity_state="absent",
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
        def __init__(self, pid, label):
            self.pid = pid
            self.label = label
            self.running = True

        def is_running(self):
            return self.running

        def name(self):
            return "ras.exe"

        def create_time(self):
            events.append(("identity", self.label))
            return 123.5

        def terminate(self):
            events.append(("terminate", self.label))

        def kill(self):
            events.append(("kill", self.label))

        def wait(self, timeout):
            events.append(("wait", self.label, timeout))
            if self.label == "terminate-handle":
                raise rascontrol_module.psutil.TimeoutExpired(timeout)
            self.running = False

    terminate_proc = FakeProcess(4321, "terminate-handle")
    kill_proc = FakeProcess(4321, "fresh-kill-handle")
    process_queries = 0

    def process_factory(pid):
        nonlocal process_queries
        process_queries += 1
        if process_queries == 1:
            return terminate_proc
        if process_queries == 2:
            return kill_proc
        if not kill_proc.running:
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        return pytest.fail("unexpected process lookup")

    lock = _tracked_lock(tmp_path)
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_factory)
    monkeypatch.setattr(
        rascontrol_module, "_remove_session_lock", lambda session_id: None
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is True
    assert result.process_detected is True
    assert result.killed is True
    assert result.process_survived is False
    assert lock.session_id not in rascontrol_module._active_sessions
    assert process_queries == 3
    assert events == [
        ("identity", "terminate-handle"),
        ("terminate", "terminate-handle"),
        ("wait", "terminate-handle", 5),
        ("identity", "fresh-kill-handle"),
        ("kill", "fresh-kill-handle"),
        ("wait", "fresh-kill-handle", 5),
    ]


def test_cleanup_does_not_kill_reused_pid_from_cached_timeout_handle(
    monkeypatch,
    tmp_path,
):
    events = []
    process_queries = 0

    class TimedOutHandle:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def name(self):
            return "ras.exe"

        def create_time(self):
            events.append("cached-identity")
            return 123.5

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("cached-kill")

        def wait(self, timeout):
            events.append(("wait", timeout))
            raise rascontrol_module.psutil.TimeoutExpired(timeout)

    class ReusedHandle:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            events.append("fresh-reused-identity")
            return 999.0

        def kill(self):
            events.append("replacement-kill")

    timed_out = TimedOutHandle(4321)
    reused = ReusedHandle(4321)

    def process_factory(_pid):
        nonlocal process_queries
        process_queries += 1
        return timed_out if process_queries == 1 else reused

    lock = _tracked_lock(tmp_path)
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_factory)
    monkeypatch.setattr(
        rascontrol_module,
        "_remove_session_lock",
        lambda _session_id: None,
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is True
    assert result.terminated is True
    assert result.killed is False
    assert result.identity_state == "terminated"
    assert "cached-kill" not in events
    assert "replacement-kill" not in events
    assert events.count("cached-identity") == 1
    assert process_queries == 3
    assert lock.session_id not in rascontrol_module._active_sessions


def test_cleanup_retains_evidence_when_fresh_kill_identity_is_unverifiable(
    monkeypatch,
    tmp_path,
):
    events = []
    process_queries = 0

    class TimedOutHandle:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def name(self):
            return "ras.exe"

        def create_time(self):
            return 123.5

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("cached-kill")

        def wait(self, timeout):
            raise rascontrol_module.psutil.TimeoutExpired(timeout)

    class UnverifiableFreshHandle:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            raise rascontrol_module.psutil.AccessDenied(self.pid)

        def kill(self):
            events.append("unverified-kill")

    timed_out = TimedOutHandle(4321)
    unverified = UnverifiableFreshHandle(4321)

    def process_factory(_pid):
        nonlocal process_queries
        process_queries += 1
        return timed_out if process_queries == 1 else unverified

    lock = _tracked_lock(tmp_path)
    lock_path = tmp_path / "retained-session.lock"
    lock_path.write_text(lock.to_json(), encoding="utf-8")
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_factory)
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: lock_path,
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is False
    assert result.process_survived is True
    assert result.lock_retained is True
    assert result.identity_state == "identity_unverified"
    assert "before forced termination" in result.error
    assert events == ["terminate"]
    assert process_queries == 2
    assert lock.session_id in rascontrol_module._active_sessions
    assert lock_path.exists()


def test_cleanup_retains_evidence_when_fresh_post_signal_proof_is_denied(
    monkeypatch,
    tmp_path,
):
    events = []
    process_queries = 0

    class TerminatedHandle:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def name(self):
            return "ras.exe"

        def create_time(self):
            return 123.5

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))

    class UnverifiablePostHandle:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            raise rascontrol_module.psutil.AccessDenied(self.pid)

    terminated = TerminatedHandle(4321)
    unverified = UnverifiablePostHandle(4321)

    def process_factory(_pid):
        nonlocal process_queries
        process_queries += 1
        return terminated if process_queries == 1 else unverified

    lock = _tracked_lock(tmp_path)
    lock_path = tmp_path / "retained-post-signal.lock"
    lock_path.write_text(lock.to_json(), encoding="utf-8")
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_factory)
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: lock_path,
    )

    result = rascontrol_module._cleanup_session(lock.session_id)

    assert result.success is False
    assert result.terminated is True
    assert result.killed is False
    assert result.process_survived is True
    assert result.lock_retained is True
    assert result.identity_state == "identity_unverified"
    assert "after signal" in result.error
    assert events == ["terminate", ("wait", 5)]
    assert process_queries == 2
    assert lock.session_id in rascontrol_module._active_sessions
    assert lock_path.exists()


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


@pytest.mark.parametrize(
    "query_error",
    [rascontrol_module.psutil.AccessDenied(4321), OSError("identity query failed")],
)
def test_cleanup_identity_query_uncertainty_retains_evidence_without_signal(
    monkeypatch, tmp_path, query_error
):
    signals = []
    class UncertainProcess:
        def __init__(self, pid): self.pid = pid
        @staticmethod
        def is_running(): return True
        @staticmethod
        def name(): return "ras.exe"
        @staticmethod
        def create_time(): raise query_error
        def terminate(self): signals.append("terminate")
    lock = _tracked_lock(tmp_path)
    lock_path = tmp_path / "uncertain.lock"
    lock_path.write_text("evidence", encoding="utf-8")
    monkeypatch.setitem(rascontrol_module._active_sessions, lock.session_id, lock)
    monkeypatch.setattr(rascontrol_module.psutil, "Process", UncertainProcess)
    monkeypatch.setattr(rascontrol_module, "_get_lock_file_path", lambda _sid: lock_path)
    result = rascontrol_module._cleanup_session(lock.session_id)
    assert result.identity_state == "identity_unverified"
    assert result.process_survived is True
    assert result.lock_retained is True
    assert signals == []
    assert lock.session_id in rascontrol_module._active_sessions
    assert lock_path.exists()


def _patch_orphan_cleanup(monkeypatch, tmp_path, lock, process_factory):
    lock_path = tmp_path / "orphan-cleanup.lock"
    lock_path.write_text(lock.to_json(), encoding="utf-8")
    monkeypatch.setattr(
        RasControl,
        "scan_orphans",
        staticmethod(lambda: [lock]),
    )
    monkeypatch.setattr(rascontrol_module.psutil, "Process", process_factory)
    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: lock_path,
    )
    return lock_path


def test_cleanup_orphans_terminates_exact_identity_and_retires_lock(
    monkeypatch,
    tmp_path,
):
    events = []

    class ExactProcess:
        exited = False

        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            events.append("identity")
            return 123.5

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))
            self.exited = True

    proc = ExactProcess(4321)

    def process_factory(pid):
        if proc.exited:
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        return proc

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        process_factory,
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == 1
    assert events == ["identity", "terminate", ("wait", 10)]
    assert not lock_path.exists()


def test_cleanup_orphans_force_kills_only_after_exact_recheck(
    monkeypatch,
    tmp_path,
):
    events = []

    class ExactProcess:
        def __init__(self, pid, label):
            self.pid = pid
            self.label = label
            self.exited = False

        def create_time(self):
            events.append(("identity", self.label))
            return 123.5

        def terminate(self):
            events.append(("terminate", self.label))

        def kill(self):
            events.append(("kill", self.label))

        def wait(self, timeout):
            events.append(("wait", self.label, timeout))
            if self.label == "terminate-handle":
                raise rascontrol_module.psutil.TimeoutExpired(timeout)
            self.exited = True

    terminate_proc = ExactProcess(4321, "terminate-handle")
    kill_proc = ExactProcess(4321, "fresh-kill-handle")
    process_queries = 0

    def process_factory(pid):
        nonlocal process_queries
        process_queries += 1
        if process_queries == 1:
            return terminate_proc
        if process_queries == 2:
            return kill_proc
        if kill_proc.exited:
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        return pytest.fail("unexpected process lookup")

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        process_factory,
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == 1
    assert events == [
        ("identity", "terminate-handle"),
        ("terminate", "terminate-handle"),
        ("wait", "terminate-handle", 10),
        ("identity", "fresh-kill-handle"),
        ("kill", "fresh-kill-handle"),
        ("wait", "fresh-kill-handle", 10),
    ]
    assert process_queries == 3
    assert not lock_path.exists()


@pytest.mark.parametrize(
    "identity_error",
    [
        None,
        rascontrol_module.psutil.AccessDenied(4321),
        rascontrol_module.psutil.NoSuchProcess(4321),
    ],
    ids=["pid-reused", "identity-unverified", "absent"],
)
def test_cleanup_orphans_refuses_nonexact_identity_before_terminate(
    monkeypatch,
    tmp_path,
    identity_error,
):
    signals = []

    class NonexactProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            if identity_error is not None:
                raise identity_error
            return 999.0

        def terminate(self):
            signals.append("terminate")

        def kill(self):
            signals.append("kill")

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        NonexactProcess,
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == 0
    assert signals == []
    assert lock_path.exists()


@pytest.mark.parametrize(
    ("fresh_state", "expected_cleaned", "lock_retained"),
    [
        ("pid_reused", 1, False),
        ("identity_unverified", 0, True),
        ("absent", 1, False),
    ],
)
def test_cleanup_orphans_uses_fresh_handle_before_kill(
    monkeypatch,
    tmp_path,
    fresh_state,
    expected_cleaned,
    lock_retained,
):
    events = []
    process_queries = 0

    class TimedOutHandle:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            events.append("cached-identity")
            return 123.5

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

        def wait(self, timeout):
            events.append(("wait", timeout))
            raise rascontrol_module.psutil.TimeoutExpired(timeout)

    class FreshHandle:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            events.append("fresh-identity")
            if fresh_state == "identity_unverified":
                raise rascontrol_module.psutil.AccessDenied(self.pid)
            return 999.0

        def kill(self):
            events.append("kill")

    timed_out = TimedOutHandle(4321)
    fresh = FreshHandle(4321)

    def process_factory(pid):
        nonlocal process_queries
        process_queries += 1
        if process_queries == 1:
            return timed_out
        if fresh_state == "absent":
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        return fresh

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        process_factory,
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == expected_cleaned
    assert "kill" not in events
    assert events[:3] == ["cached-identity", "terminate", ("wait", 10)]
    assert events.count("cached-identity") == 1
    assert lock_path.exists() is lock_retained


@pytest.mark.parametrize(
    ("post_state", "expected_cleaned", "lock_retained"),
    [
        ("pid_reused", 1, False),
        ("identity_unverified", 0, True),
        ("exact", 0, True),
    ],
)
def test_cleanup_orphans_requires_terminal_post_signal_state(
    monkeypatch,
    tmp_path,
    post_state,
    expected_cleaned,
    lock_retained,
):
    events = []
    process_queries = 0

    class Process:
        def __init__(self, pid, create_time):
            self.pid = pid
            self._create_time = create_time

        def create_time(self):
            if isinstance(self._create_time, Exception):
                raise self._create_time
            return self._create_time

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))

    exact = Process(4321, 123.5)
    post_create_time = {
        "pid_reused": 999.0,
        "identity_unverified": rascontrol_module.psutil.AccessDenied(4321),
        "exact": 123.5,
    }[post_state]

    def process_factory(pid):
        nonlocal process_queries
        process_queries += 1
        if process_queries == 1:
            return exact
        return Process(pid, post_create_time)

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        process_factory,
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == expected_cleaned
    assert events == ["terminate", ("wait", 10)]
    assert lock_path.exists() is lock_retained


def test_cleanup_orphans_does_not_count_cleanup_when_lock_retirement_fails(
    monkeypatch,
    tmp_path,
):
    class ExactProcess:
        exited = False

        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 123.5

        def terminate(self):
            return None

        def wait(self, timeout):
            self.exited = True

    proc = ExactProcess(4321)

    def process_factory(pid):
        if proc.exited:
            raise rascontrol_module.psutil.NoSuchProcess(pid)
        return proc

    lock = _tracked_lock(tmp_path)
    lock_path = _patch_orphan_cleanup(
        monkeypatch,
        tmp_path,
        lock,
        process_factory,
    )

    class UnretirableLock:
        @staticmethod
        def unlink(*, missing_ok):
            raise OSError("lock is busy")

    monkeypatch.setattr(
        rascontrol_module,
        "_get_lock_file_path",
        lambda _session_id: UnretirableLock(),
    )

    cleaned = RasControl.cleanup_orphans(interactive=False)

    assert cleaned == 0
    assert lock_path.exists()
