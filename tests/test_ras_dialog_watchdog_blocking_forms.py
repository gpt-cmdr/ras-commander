"""Blocking HEC-RAS VB6 error forms: classification, watchdog capture, fail-fast wait.

HEC-RAS 6.x reports fatal unsteady-flow input errors (for example a missing DSS
file) in a VB6 form of class ``ThunderRT6FormDC``. Closing it does not let the
run continue, so before this fix ``compute_plan`` waited until ``max_runtime``.
"""

import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import ras_commander.RasDialogWatchdog as watchdog_module
from ras_commander.RasCmdr import RasCmdr
from ras_commander.RasDialogWatchdog import (
    DialogWatchdog,
    DismissedDialog,
    RasBlockingDialogError,
    classify_ras_dialog,
)

UNSTEADY_PREP_TITLE = (
    "The following errors were found preparing unsteady flow data for simulation:"
)
FORM_BUTTONS = ["File ...", "Print ...", "Clipboard", "Close"]


# -- classification ---------------------------------------------------------


def test_unsteady_flow_preparation_form_is_classified():
    assert (
        classify_ras_dialog("ThunderRT6FormDC", UNSTEADY_PREP_TITLE, "", FORM_BUTTONS)
        == "unsteady_flow_preparation_error"
    )


def test_unsteady_flow_preparation_phrase_in_body_is_classified():
    assert (
        classify_ras_dialog(
            "ThunderRT6FormDC",
            "HEC-RAS",
            "The following errors were found preparing unsteady flow data",
            ["Close"],
        )
        == "unsteady_flow_preparation_error"
    )


def test_generic_vb6_error_form_with_close_is_blocking():
    assert (
        classify_ras_dialog("ThunderRT6FormDC", "Geometry Errors", "", ["&Close"])
        == "blocking_error"
    )


@pytest.mark.parametrize(
    "window_class, title, buttons",
    [
        # Win32 message boxes keep the existing click-to-continue behavior.
        ("#32770", UNSTEADY_PREP_TITLE, ["OK"]),
        # Progress form: never classified, even when its text mentions errors.
        ("ThunderRT6FormDC", "HEC-RAS Computations", ["Pause", "Close"]),
        ("ThunderRT6FormDC", "Errors during computation", ["Pause", "Close"]),
        ("ThunderRT6FormDC", "Loading File", []),
        # No dismissal button: not an error report.
        ("ThunderRT6FormDC", "Error summary", ["Print ..."]),
        # Non-error title.
        ("ThunderRT6FormDC", "Unsteady Flow Analysis", ["Close"]),
        ("ThunderRT6Main", "RAS", []),
    ],
)
def test_non_blocking_windows_are_not_classified(window_class, title, buttons):
    assert classify_ras_dialog(window_class, title, "", buttons) is None


# -- watchdog capture ---------------------------------------------------------


TRACKED_PID = 4100
OTHER_RUN_PID = 4200
BODY = (
    "Boundary Condition for River: Example  Reach: Upper at RS: 100 | "
    "DSS File: 'project\\100.dss' not found."
)


def _fake_form_desktop(owner_pid):
    """One visible VB6 unsteady-prep error form owned by ``owner_pid``."""
    windows = {
        10: ("ThunderRT6FormDC", UNSTEADY_PREP_TITLE),
        20: ("ThunderRT6CommandButton", "Clipboard"),
        21: ("ThunderRT6CommandButton", "Close"),
        30: ("ThunderRT6ListBox", ""),
    }
    clicked = []

    def enum_windows(callback, data):
        callback(10, data)

    def enum_child_windows(_hwnd, callback, data):
        for child in (20, 21, 30):
            callback(child, data)

    fake_win32gui = SimpleNamespace(
        IsWindowVisible=lambda hwnd: True,
        GetClassName=lambda hwnd: windows[hwnd][0],
        GetWindowText=lambda hwnd: windows[hwnd][1],
        EnumWindows=enum_windows,
        EnumChildWindows=enum_child_windows,
    )
    fake_win32process = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, owner_pid)
    )
    return fake_win32gui, fake_win32process, clicked


def _install(monkeypatch, owner_pid, discovered_pids):
    fake_win32gui, fake_win32process, clicked = _fake_form_desktop(owner_pid)
    monkeypatch.setattr(watchdog_module, "win32gui", fake_win32gui)
    monkeypatch.setattr(watchdog_module, "win32process", fake_win32process)
    watchdog = DialogWatchdog()
    monkeypatch.setattr(watchdog, "_collect_ras_pids", lambda: set(discovered_pids))
    monkeypatch.setattr(watchdog, "_process_name", lambda _pid: "Ras.exe")

    def control_text(hwnd, control_class):
        assert control_class == "ThunderRT6ListBox"
        return BODY.split(" | ")

    def send(hwnd, message, wparam, lparam, timeout_ms=1000):
        clicked.append((hwnd, message))
        return 1

    monkeypatch.setattr(watchdog, "_control_text", control_text)
    monkeypatch.setattr(watchdog, "_send_message_timeout", send)
    return watchdog, clicked


def test_watchdog_records_and_closes_form_for_tracked_run(monkeypatch):
    watchdog, clicked = _install(monkeypatch, TRACKED_PID, {TRACKED_PID})
    watchdog.add_pid(TRACKED_PID)
    monkeypatch.setattr(watchdog, "_collect_tracked_pids", lambda: {TRACKED_PID})

    watchdog._scan_and_dismiss()
    watchdog._scan_and_dismiss()  # the same form is recorded once

    blocking = watchdog.blocking_errors()
    assert len(blocking) == 1
    record = blocking[0]
    assert record.classification == "unsteady_flow_preparation_error"
    assert record.window_class == "ThunderRT6FormDC"
    assert record.title == UNSTEADY_PREP_TITLE
    assert record.body == BODY
    assert record.button == "Close"
    assert clicked == [(21, 0x00F5)]
    assert record.to_dict()["classification"] == "unsteady_flow_preparation_error"


def test_watchdog_ignores_forms_of_other_runs(monkeypatch):
    # Another session's Ras.exe is auto-discovered, but VB6 forms are only
    # inspected for this run's registered process tree.
    watchdog, clicked = _install(
        monkeypatch, OTHER_RUN_PID, {TRACKED_PID, OTHER_RUN_PID}
    )
    watchdog.add_pid(TRACKED_PID)
    monkeypatch.setattr(watchdog, "_collect_tracked_pids", lambda: {TRACKED_PID})

    watchdog._scan_and_dismiss()

    assert watchdog.blocking_errors() == []
    assert clicked == []


def test_dismissed_dialog_defaults_are_backward_compatible():
    record = DismissedDialog(1, "Ras.exe", "RAS", "body", "OK")
    assert record.window_class == "#32770"
    assert record.classification is None
    assert record.is_blocking_error is False


# -- compute_plan launcher wait ----------------------------------------------


class _HungProcess:
    def __init__(self):
        self.waits = 0

    def wait(self, timeout=None):
        self.waits += 1
        raise subprocess.TimeoutExpired("Ras.exe", timeout)


class _FakeWatchdog:
    def __init__(self, after_waits, process):
        self._after = after_waits
        self._process = process

    def blocking_errors(self):
        if self._process.waits < self._after:
            return []
        return [
            DismissedDialog(
                TRACKED_PID,
                "Ras.exe",
                UNSTEADY_PREP_TITLE,
                BODY,
                "Close",
                window_class="ThunderRT6FormDC",
                classification="unsteady_flow_preparation_error",
            )
        ]


def test_launcher_wait_fails_fast_on_blocking_dialog():
    process = _HungProcess()
    details = {}
    started = time.monotonic()
    with pytest.raises(RasBlockingDialogError) as excinfo:
        RasCmdr._wait_for_launcher(
            process,
            _FakeWatchdog(2, process),
            time.monotonic() + 600,
            plan_number="01",
            max_runtime_seconds=600,
            execution_details=details,
            poll_seconds=0.01,
        )
    assert time.monotonic() - started < 5
    assert "DSS File" in str(excinfo.value)
    assert UNSTEADY_PREP_TITLE in str(excinfo.value)
    assert details["blocking_dialogs"][0]["body"] == BODY


def test_launcher_wait_still_honors_deadline_without_dialogs():
    process = _HungProcess()
    with pytest.raises(subprocess.TimeoutExpired):
        RasCmdr._wait_for_launcher(
            process,
            _FakeWatchdog(10**9, process),
            time.monotonic() + 0.05,
            plan_number="01",
            max_runtime_seconds=0.05,
            poll_seconds=0.01,
        )


def test_launcher_wait_returns_exit_code():
    process = SimpleNamespace(wait=lambda timeout=None: 0)
    assert (
        RasCmdr._wait_for_launcher(
            process,
            _FakeWatchdog(0, process),
            None,
            plan_number="01",
            max_runtime_seconds=None,
        )
        == 0
    )


# -- real HEC-RAS -------------------------------------------------------------


def _ras_exe(version):
    return Path(r"C:\Program Files (x86)\HEC\HEC-RAS") / version / "Ras.exe"


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.skipif(
    os.environ.get("RAS_COMMANDER_RUN_REAL_RAS") != "1"
    or not _ras_exe(os.environ.get("RAS_COMMANDER_DIALOG_RAS_VERSION", "6.3")).exists(),
    reason="Set RAS_COMMANDER_RUN_REAL_RAS=1 with HEC-RAS installed "
    "(RAS_COMMANDER_DIALOG_RAS_VERSION, default 6.3)",
)
def test_missing_dss_unsteady_prep_dialog_fails_fast(tmp_path):
    from ras_commander import RasExamples, init_ras_project

    version = os.environ.get("RAS_COMMANDER_DIALOG_RAS_VERSION", "6.3")
    project = RasExamples.extract_project("Balde Eagle Creek", output_path=tmp_path)
    unsteady = Path(project) / "BaldEagle.u02"
    text = unsteady.read_text()
    # Point the first (upstream flow hydrograph) boundary at a missing DSS file.
    old = "DSS Path=\nUse DSS=False\n"
    assert old in text
    text = text.replace(
        old,
        "DSS File=HMS DSS\\100.dss\n"
        "DSS Path=//BASIN/UPSTREAM/FLOW/01JAN1999/1HOUR/RUN:100/\n"
        "Use DSS=True\n",
        1,
    )
    unsteady.write_text(text)

    ras = init_ras_project(project, version)
    started = time.monotonic()
    result = RasCmdr.compute_plan("01", ras_object=ras, max_runtime=300, num_cores=2)
    elapsed = time.monotonic() - started

    details = result.execution_details
    assert not result.success
    assert elapsed < 120
    assert details["failure_type"] == "RasBlockingDialogError"
    assert details["runtime_timed_out"] is False
    dialog = details["blocking_dialogs"][0]
    assert dialog["classification"] == "unsteady_flow_preparation_error"
    assert "not found" in dialog["body"]
