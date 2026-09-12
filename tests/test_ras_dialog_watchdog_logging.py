import hashlib
import json
import logging
import threading
from types import SimpleNamespace

import psutil
import pytest

import ras_commander.RasDialogWatchdog as watchdog_module
from ras_commander.RasDialogWatchdog import (
    DialogWatchdog,
    _ExactDialogObserver,
    _ExactRasProcessIdentity,
)


LOGGER_NAME = "ras_commander.RasDialogWatchdog"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def test_start_stop_with_no_dialogs_is_debug_only(monkeypatch, caplog):
    monkeypatch.setattr(watchdog_module, "_WIN32", True)
    monkeypatch.setattr(DialogWatchdog, "_poll_loop", lambda self: None)

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    watchdog = DialogWatchdog()
    watchdog.start()
    watchdog.stop()

    assert _messages(caplog, logging.INFO) == []
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert "DialogWatchdog started" in debug_text
    assert "DialogWatchdog stopped — no dialogs encountered" in debug_text


def test_pywin32_unavailable_warns_once_and_stop_is_debug(monkeypatch, caplog):
    monkeypatch.setattr(watchdog_module, "_WIN32", False)
    monkeypatch.setattr(watchdog_module, "_WIN32_UNAVAILABLE_WARNED", False)

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    first = DialogWatchdog()
    first.start()
    first.stop()
    second = DialogWatchdog()
    second.start()

    warnings = _messages(caplog, logging.WARNING)
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert len(warnings) == 1
    assert "Install pywin32 on Windows" in warnings[0]
    assert "dialog_watchdog=False" in warnings[0]
    assert "DialogWatchdog stop requested while watchdog is not running" in debug_text
    assert "DialogWatchdog unavailable because pywin32 is not installed" in debug_text
    assert "no dialogs encountered" not in "\n".join(_messages(caplog, logging.INFO))


def test_dismiss_with_button_stays_info(monkeypatch, caplog):
    sent_messages = []

    def enum_child_windows(_hwnd, callback, data):
        callback(20, data)
        callback(30, data)

    fake_win32gui = SimpleNamespace(
        GetWindowText=lambda hwnd: {
            10: "RAS Message",
            20: "Computation complete",
            30: "OK",
        }.get(hwnd, ""),
        EnumChildWindows=enum_child_windows,
        GetClassName=lambda hwnd: {
            20: "Static",
            30: "Button",
        }.get(hwnd, ""),
        SendMessage=lambda hwnd, msg, wparam, lparam: sent_messages.append(
            (hwnd, msg, wparam, lparam)
        ),
    )
    monkeypatch.setattr(watchdog_module, "win32gui", fake_win32gui)

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    watchdog = DialogWatchdog()
    monkeypatch.setattr(watchdog, "_process_name", lambda _pid: "Ras.exe")
    watchdog._dismiss(10, 1234)

    info_text = "\n".join(_messages(caplog, logging.INFO))
    assert "DialogWatchdog: auto-dismissing dialog" in info_text
    assert "process=Ras.exe PID=1234" in info_text
    assert "title='RAS Message'" in info_text
    assert "body='Computation complete'" in info_text
    assert "clicking [OK]" in info_text
    assert _messages(caplog, logging.WARNING) == []
    assert sent_messages == [(30, 0x00F5, 0, 0)]


def test_optional_example_install_is_declined(monkeypatch, caplog):
    sent_messages = []

    def enum_child_windows(_hwnd, callback, data):
        callback(20, data)
        callback(30, data)
        callback(40, data)

    fake_win32gui = SimpleNamespace(
        GetWindowText=lambda hwnd: {
            10: "RAS",
            20: "Do you want to install the example projects for HEC-RAS?",
            30: "&Yes",
            40: "&No",
        }.get(hwnd, ""),
        EnumChildWindows=enum_child_windows,
        GetClassName=lambda hwnd: {
            20: "Static",
            30: "Button",
            40: "Button",
        }.get(hwnd, ""),
        SendMessage=lambda hwnd, msg, wparam, lparam: sent_messages.append(
            (hwnd, msg, wparam, lparam)
        ),
    )
    monkeypatch.setattr(watchdog_module, "win32gui", fake_win32gui)

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    watchdog = DialogWatchdog()
    monkeypatch.setattr(watchdog, "_process_name", lambda _pid: "Ras.exe")
    watchdog._dismiss(10, 1234)

    info_text = "\n".join(_messages(caplog, logging.INFO))
    assert "clicking [&No]" in info_text
    assert sent_messages == [(40, 0x00F5, 0, 0)]


def test_dismiss_without_button_warns(monkeypatch, caplog):
    closed_windows = []

    def enum_child_windows(_hwnd, callback, data):
        callback(20, data)

    fake_win32gui = SimpleNamespace(
        GetWindowText=lambda hwnd: {
            10: "RAS Warning",
            20: "Unrecognized dialog body",
        }.get(hwnd, ""),
        EnumChildWindows=enum_child_windows,
        GetClassName=lambda hwnd: {
            20: "Static",
        }.get(hwnd, ""),
        PostMessage=lambda hwnd, msg, wparam, lparam: closed_windows.append(
            (hwnd, msg, wparam, lparam)
        ),
    )
    monkeypatch.setattr(watchdog_module, "win32gui", fake_win32gui)
    monkeypatch.setattr(watchdog_module, "win32con", SimpleNamespace(WM_CLOSE=0x0010))

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    watchdog = DialogWatchdog()
    monkeypatch.setattr(watchdog, "_process_name", lambda _pid: "Ras.exe")
    watchdog._dismiss(10, 1234)

    warning_text = "\n".join(_messages(caplog, logging.WARNING))
    assert "DialogWatchdog: closing dialog (no button found)" in warning_text
    assert "sending WM_CLOSE" in warning_text
    assert closed_windows == [(10, 0x0010, 0, 0)]


def test_psutil_process_discovery_failure_is_debug_only(monkeypatch, caplog):
    def raise_process_iter(_attrs):
        raise RuntimeError("process table unavailable")

    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(
        watchdog_module,
        "psutil",
        SimpleNamespace(process_iter=raise_process_iter),
    )

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    watchdog = DialogWatchdog()
    assert watchdog._collect_ras_pids() == set()
    assert watchdog._collect_ras_pids() == set()

    assert _messages(caplog, logging.INFO) == []
    assert _messages(caplog, logging.WARNING) == []
    debug_messages = [
        message
        for message in _messages(caplog, logging.DEBUG)
        if "process discovery failed" in message
    ]
    assert debug_messages == [
        "DialogWatchdog process discovery failed: process table unavailable"
    ]


class _FakeProcess:
    def __init__(
        self,
        pid,
        create_time,
        executable,
        *,
        name="Ras.exe",
        exe_error=None,
    ):
        self.pid = pid
        self._create_time = create_time
        self._executable = executable
        self._name = name
        self._exe_error = exe_error

    def create_time(self):
        return self._create_time

    def name(self):
        return self._name

    def exe(self):
        if self._exe_error is not None:
            raise self._exe_error
        return str(self._executable)


def _strict_observer(tmp_path, monkeypatch, *, process_factory=None):
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"reviewed ras executable")
    identity = _ExactRasProcessIdentity(
        pid=1234,
        create_time=100.25,
        process_name="Ras.exe",
        executable_path=executable,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    )
    if process_factory is None:

        def process_factory(pid):
            return _FakeProcess(pid, identity.create_time, executable)

    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(watchdog_module.psutil, "Process", process_factory)
    return _ExactDialogObserver(identity, poll_interval=0.01), identity, executable


def _install_fake_dialogs(monkeypatch, dialogs):
    """Install a small pywin32 facade and return captured bounded messages."""
    sent_messages = []
    top_level = {dialog["hwnd"]: dialog for dialog in dialogs}
    children = {
        child["hwnd"]: child
        for dialog in dialogs
        for child in dialog.get("children", [])
    }
    child_parents = {
        child["hwnd"]: dialog["hwnd"]
        for dialog in dialogs
        for child in dialog.get("children", [])
    }

    def enum_windows(callback, data):
        for hwnd in top_level:
            callback(hwnd, data)

    def enum_child_windows(hwnd, callback, data):
        for child in top_level[hwnd].get("children", []):
            callback(child["hwnd"], data)

    def get_class_name(hwnd):
        if hwnd in top_level:
            return "#32770"
        return children[hwnd]["class_name"]

    def get_window_text(hwnd):
        if hwnd in top_level:
            return top_level[hwnd].get("title", "")
        return children[hwnd].get("text", "")

    def get_window_process_id(hwnd):
        if hwnd in top_level:
            return top_level[hwnd]["pid"]
        child = children[hwnd]
        return child.get("pid", top_level[child_parents[hwnd]]["pid"])

    fake_win32gui = SimpleNamespace(
        IsWindowVisible=lambda hwnd: top_level[hwnd].get("visible", True),
        IsWindow=lambda hwnd: hwnd in top_level or hwnd in children,
        IsChild=lambda parent, child: child_parents.get(child) == parent,
        GetClassName=get_class_name,
        GetWindowText=get_window_text,
        EnumWindows=enum_windows,
        EnumChildWindows=enum_child_windows,
        SendMessageTimeout=lambda hwnd, msg, wparam, lparam, flags, timeout: (
            sent_messages.append((hwnd, msg, wparam, lparam, flags, timeout))
        ),
    )
    fake_win32process = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, get_window_process_id(hwnd)),
    )
    monkeypatch.setattr(watchdog_module, "win32gui", fake_win32gui)
    monkeypatch.setattr(watchdog_module, "win32process", fake_win32process)
    return sent_messages


def _static(hwnd, text):
    return {"hwnd": hwnd, "class_name": "Static", "text": text}


def _button(hwnd, text):
    return {"hwnd": hwnd, "class_name": "Button", "text": text}


def test_exact_identity_requires_finite_create_time_and_lowercase_digest(tmp_path):
    executable = tmp_path / "Ras.exe"

    with pytest.raises(ValueError, match="positive finite"):
        _ExactRasProcessIdentity(1, float("nan"), "Ras.exe", executable, "0" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _ExactRasProcessIdentity(1, 1.0, "Ras.exe", executable, "A" * 64)
    with pytest.raises(ValueError, match="Ras.exe exactly"):
        _ExactRasProcessIdentity(1, 1.0, "PipeServer.exe", executable, "0" * 64)


def test_strict_observer_excludes_unrelated_process_preserves_unknown_and_dedupes(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 9999,
                "title": "Unrelated dialog",
                "children": [_static(11, "Do not inspect me"), _button(12, "OK")],
            },
            {
                "hwnd": 20,
                "pid": 1234,
                "title": "Unknown RAS dialog",
                "children": [_static(21, "Unexpected warning"), _button(22, "OK")],
            },
        ],
    )

    observer._scan_once()
    observer._scan_once()
    evidence = observer._evidence()

    assert evidence["process_discovery"] is False
    assert evidence["observed_count"] == 1
    assert evidence["action_count"] == 0
    assert evidence["identity_check_count"] == 3
    assert evidence["identity_checks"][-1]["first_check_count"] == 1
    assert evidence["last_identity_check_timestamp"] is not None
    observation = evidence["observations"][0]
    assert observation["hwnd"] == 20
    assert observation["pid"] == 1234
    assert observation["title"] == "Unknown RAS dialog"
    assert observation["body"] == "Unexpected warning"
    assert observation["button_labels"] == ["OK"]
    assert observation["classification"] == "unknown_preserved"
    assert observation["action_status"] == "not_requested"
    assert observation["proof_state"] == "not_applicable"
    assert sent_messages == []


@pytest.mark.parametrize(
    ("case", "expected_state"),
    [
        ("pid_reused", "pid_reused"),
        ("name_mismatch", "name_mismatch"),
        ("path_mismatch", "path_mismatch"),
        ("hash_mismatch", "hash_mismatch"),
        ("access_uncertain", "identity_unverified"),
    ],
)
def test_strict_identity_failures_never_enumerate_or_act(
    tmp_path,
    monkeypatch,
    case,
    expected_state,
):
    observer, identity, executable = _strict_observer(tmp_path, monkeypatch)
    alternate = tmp_path / "alternate" / "Ras.exe"
    alternate.parent.mkdir()
    alternate.write_bytes(executable.read_bytes())

    if case == "pid_reused":
        process = _FakeProcess(identity.pid, identity.create_time + 1, executable)
    elif case == "name_mismatch":
        process = _FakeProcess(
            identity.pid,
            identity.create_time,
            executable,
            name="PipeServer.exe",
        )
    elif case == "path_mismatch":
        process = _FakeProcess(identity.pid, identity.create_time, alternate)
    elif case == "hash_mismatch":
        executable.write_bytes(b"different executable bytes")
        process = _FakeProcess(identity.pid, identity.create_time, executable)
    else:
        process = _FakeProcess(
            identity.pid,
            identity.create_time,
            executable,
            exe_error=psutil.AccessDenied(identity.pid),
        )
    monkeypatch.setattr(watchdog_module.psutil, "Process", lambda _pid: process)

    enum_calls = []
    monkeypatch.setattr(
        watchdog_module,
        "win32gui",
        SimpleNamespace(
            EnumWindows=lambda callback, data: enum_calls.append((callback, data))
        ),
    )

    observer._scan_once()
    evidence = observer._evidence()

    assert enum_calls == []
    assert evidence["observed_count"] == 0
    assert evidence["action_count"] == 0
    assert evidence["identity_checks"][-1]["state"] == expected_state


def test_strict_allowlist_clicks_only_exact_no_or_cancel_button(tmp_path, monkeypatch):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(
                        11, "Do you want to install the example projects for HEC-RAS?"
                    ),
                    _button(12, "&Yes"),
                    _button(13, "&No"),
                ],
            },
            {
                "hwnd": 20,
                "pid": 1234,
                "title": "Near match",
                "children": [
                    _static(
                        21, "Do you want to install the example projects for HEC-RAS"
                    ),
                    _button(22, "No"),
                ],
            },
            {
                "hwnd": 30,
                "pid": 1234,
                "title": "Exact prompt without a reviewed button",
                "children": [
                    _static(
                        31, "Do you want to install the example projects for HEC-RAS?"
                    ),
                    _button(32, "Close"),
                ],
            },
        ],
    )

    observer._scan_once()
    evidence = observer._evidence()

    assert sent_messages == [(13, 0x00F5, 0, 0, 0x0003, 500)]
    assert evidence["observed_count"] == 3
    assert evidence["action_count"] == 1
    assert evidence["action_attempt_count"] == 1
    assert evidence["observations"][0]["classification"] == (
        "allowlisted_dialog_declined"
    )
    assert evidence["observations"][0]["rule_id"] == (
        "decline_optional_example_install"
    )
    assert [item["classification"] for item in evidence["observations"][1:]] == [
        "unknown_preserved",
        "unknown_preserved",
    ]


def test_strict_action_rechecks_identity_and_preserves_on_pid_reuse(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(
                        11, "Do you want to install the example projects for HEC-RAS?"
                    ),
                    _button(12, "No"),
                ],
            },
        ],
    )
    states = iter(["exact", "exact", "pid_reused"])
    monkeypatch.setattr(observer, "_verify_identity", lambda: next(states))

    observer._scan_once()
    evidence = observer._evidence()

    assert sent_messages == []
    assert evidence["action_count"] == 0
    assert evidence["observations"][0]["classification"] == (
        "identity_changed_preserved"
    )
    assert evidence["observations"][0]["identity_state"] == "pid_reused"


def test_strict_evidence_is_finite_json_and_reports_stopped_lifecycle(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    monkeypatch.setattr(watchdog_module, "_WIN32", True)
    monkeypatch.setattr(watchdog_module.time, "time", lambda: float("nan"))
    monkeypatch.setattr(observer, "_poll_loop", lambda: None)

    assert observer._start() is True
    observer._record_identity_check("exact")
    observer._stop_observing()
    evidence = observer._evidence()

    assert evidence["scope"] == "exact_controller_identity"
    assert evidence["lifecycle"] == "stopped"
    assert evidence["available"] is True
    assert evidence["start_attempted"] is True
    assert evidence["started"] is True
    assert evidence["start_status"] == "started"
    assert evidence["stop_requested"] is True
    assert evidence["stop_confirmed"] is True
    assert evidence["thread_alive"] is False
    assert evidence["stop_status"] == "completed"
    assert evidence["identity_checks"] == [
        {"state": "exact", "first_check_count": 1, "timestamp": 0.0}
    ]
    assert evidence["identity_check_count"] == 1
    assert evidence["last_identity_check_timestamp"] == 0.0
    json.dumps(evidence, allow_nan=False)


def test_private_lifecycle_distinguishes_unavailable_and_stop_before_start(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    monkeypatch.setattr(watchdog_module, "_WIN32", False)

    assert observer._start() is False
    unavailable = observer._evidence()
    assert unavailable["available"] is False
    assert unavailable["start_attempted"] is True
    assert unavailable["started"] is False
    assert unavailable["start_status"] == "dependency_unavailable"
    assert unavailable["lifecycle"] == "unavailable"
    assert unavailable["thread_alive"] is False

    observer._stop_observing()
    stopped = observer._evidence()
    assert stopped["stop_requested"] is True
    assert stopped["stop_confirmed"] is True
    assert stopped["stop_status"] == "stopped_before_start"
    assert stopped["lifecycle"] == "stopped"
    assert [item["reason"] for item in stopped["lifecycle_transitions"]] == [
        "observer_created",
        "dependency_unavailable",
        "stopped_before_start",
    ]


def test_private_lifecycle_records_thread_start_failure(tmp_path, monkeypatch):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    monkeypatch.setattr(watchdog_module, "_WIN32", True)

    class FailingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("simulated thread start failure")

        def is_alive(self):
            return False

    monkeypatch.setattr(watchdog_module.threading, "Thread", FailingThread)

    with pytest.raises(RuntimeError, match="simulated thread start failure"):
        observer._start()
    evidence = observer._evidence()

    assert evidence["available"] is True
    assert evidence["start_attempted"] is True
    assert evidence["started"] is False
    assert evidence["start_status"] == "thread_start_failed"
    assert evidence["lifecycle"] == "start_failed"
    assert evidence["thread_alive"] is False
    assert evidence["lifecycle_transitions"][-1]["reason"] == (
        "thread_start_failed:RuntimeError"
    )


class _FakeHashStream:
    def __init__(self, data):
        self._chunks = iter([data, b""])

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def fileno(self):
        return 99

    def read(self, _size):
        return next(self._chunks)


class _FakeHashPath:
    def __init__(self, path_stats, data=b"same"):
        self._path_stats = iter(path_stats)
        self._data = data

    def open(self, _mode):
        return _FakeHashStream(self._data)

    def stat(self):
        return next(self._path_stats)


def _fake_stat(*, inode, size=4, mtime=10, ctime=20):
    return SimpleNamespace(
        st_dev=1,
        st_ino=inode,
        st_size=size,
        st_mtime_ns=mtime,
        st_ctime_ns=ctime,
    )


def test_stable_hash_rejects_same_size_same_mtime_path_replacement(monkeypatch):
    original = _fake_stat(inode=100)
    replacement = _fake_stat(inode=200)
    path = _FakeHashPath([original, replacement])
    handle_stats = iter([original, original])
    monkeypatch.setattr(watchdog_module.os, "fstat", lambda _descriptor: next(handle_stats))

    with pytest.raises(OSError, match="path was replaced"):
        watchdog_module._stable_file_sha256(path)


@pytest.mark.parametrize("change", ["process", "path"])
def test_identity_rechecks_process_metadata_after_hash(
    tmp_path,
    monkeypatch,
    change,
):
    observer, identity, executable = _strict_observer(tmp_path, monkeypatch)
    alternate = tmp_path / "alternate" / "Ras.exe"
    alternate.parent.mkdir()
    alternate.write_bytes(executable.read_bytes())

    class ChangingProcess(_FakeProcess):
        def __init__(self):
            super().__init__(identity.pid, identity.create_time, executable)
            self._create_times = iter(
                [
                    identity.create_time,
                    identity.create_time + (1 if change == "process" else 0),
                ]
            )
            self._executables = iter(
                [executable, alternate if change == "path" else executable]
            )

        def create_time(self):
            return next(self._create_times)

        def exe(self):
            return str(next(self._executables))

    monkeypatch.setattr(watchdog_module.psutil, "Process", lambda _pid: ChangingProcess())

    expected = "pid_reused" if change == "process" else "path_mismatch"
    assert observer._verify_identity() == expected


def test_action_preserves_dialog_when_exact_body_changes_before_click(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(11, "Do you want to install the example projects for HEC-RAS?"),
                    _button(12, "No"),
                ],
            },
        ],
    )
    original_read = observer._read_dialog
    read_count = 0

    def changing_read(hwnd):
        nonlocal read_count
        read_count += 1
        title, body, buttons = original_read(hwnd)
        if read_count == 2:
            body = "A different dialog now owns this handle"
        return title, body, buttons

    monkeypatch.setattr(observer, "_read_dialog", changing_read)

    observer._scan_once()
    observation = observer._evidence()["observations"][0]

    assert sent_messages == []
    assert observation["classification"] == "dialog_content_changed_preserved"
    assert observation["proof_state"] == "dialog_content_changed"
    assert observation["revalidated_body"] == "A different dialog now owns this handle"


@pytest.mark.parametrize(
    ("child_class", "child_pid"),
    [("Edit", 1234), ("Button", 9999)],
)
def test_action_preserves_reused_or_foreign_button_handle(
    tmp_path,
    monkeypatch,
    child_class,
    child_pid,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(11, "Do you want to install the example projects for HEC-RAS?"),
                    {
                        "hwnd": 12,
                        "class_name": child_class,
                        "text": "No",
                        "pid": child_pid,
                    },
                ],
            },
        ],
    )
    monkeypatch.setattr(
        observer,
        "_read_dialog",
        lambda _hwnd: (
            "RAS",
            "Do you want to install the example projects for HEC-RAS?",
            [(12, "No")],
        ),
    )

    observer._scan_once()
    observation = observer._evidence()["observations"][0]

    assert sent_messages == []
    assert observation["classification"] == "button_window_changed_preserved"
    assert observation["proof_state"] == "button_window_changed"


def test_bounded_action_timeout_is_recorded_as_unknown_outcome(tmp_path, monkeypatch):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(11, "Do you want to install the example projects for HEC-RAS?"),
                    _button(12, "Cancel"),
                ],
            },
        ],
    )

    def time_out(*_args):
        raise TimeoutError("simulated bounded send timeout")

    monkeypatch.setattr(watchdog_module.win32gui, "SendMessageTimeout", time_out)

    observer._scan_once()
    evidence = observer._evidence()
    observation = evidence["observations"][0]

    assert sent_messages == []
    assert evidence["action_count"] == 0
    assert evidence["action_attempt_count"] == 1
    assert observation["action"] == "BM_CLICK"
    assert observation["action_status"] == "timed_out"
    assert observation["action_timeout_ms"] == 500
    assert observation["classification"] == "action_timeout_outcome_unknown"
    json.dumps(evidence, allow_nan=False)


def test_stop_during_blocked_final_scan_prevents_later_click(tmp_path, monkeypatch):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(11, "Do you want to install the example projects for HEC-RAS?"),
                    _button(12, "No"),
                ],
            },
        ],
    )
    original_read = observer._read_dialog
    final_scan_entered = threading.Event()
    release_final_scan = threading.Event()
    read_count = 0

    def blocking_read(hwnd):
        nonlocal read_count
        read_count += 1
        if read_count == 2:
            final_scan_entered.set()
            assert release_final_scan.wait(timeout=2)
        return original_read(hwnd)

    monkeypatch.setattr(observer, "_read_dialog", blocking_read)
    scan_thread = threading.Thread(target=observer._scan_once)
    observer._thread = scan_thread
    observer._lifecycle = "running"
    scan_thread.start()
    assert final_scan_entered.wait(timeout=2)

    stop_thread = threading.Thread(target=observer._stop_observing)
    stop_thread.start()
    assert observer._stop.wait(timeout=2)
    release_final_scan.set()
    stop_thread.join(timeout=2)
    scan_thread.join(timeout=2)

    evidence = observer._evidence()
    observation = evidence["observations"][0]
    assert not stop_thread.is_alive()
    assert not scan_thread.is_alive()
    assert sent_messages == []
    assert evidence["lifecycle"] == "stopped"
    assert evidence["stop_prevented_action_count"] == 1
    assert observation["action_status"] == "stop_requested"
    assert observation["classification"] == "stop_requested_preserved"


def test_stop_deadline_bounds_action_gate_wait_and_later_scan_cannot_click(
    tmp_path,
    monkeypatch,
):
    observer, _, _ = _strict_observer(tmp_path, monkeypatch)
    observer._stop_timeout_seconds = 0.02
    sent_messages = _install_fake_dialogs(
        monkeypatch,
        [
            {
                "hwnd": 10,
                "pid": 1234,
                "title": "RAS",
                "children": [
                    _static(11, "Do you want to install the example projects for HEC-RAS?"),
                    _button(12, "No"),
                ],
            },
        ],
    )
    original_read = observer._read_dialog
    final_scan_entered = threading.Event()
    release_final_scan = threading.Event()
    read_count = 0

    def indefinitely_blocked_read(hwnd):
        nonlocal read_count
        read_count += 1
        if read_count == 2:
            final_scan_entered.set()
            assert release_final_scan.wait(timeout=2)
        return original_read(hwnd)

    monkeypatch.setattr(observer, "_read_dialog", indefinitely_blocked_read)
    scan_thread = threading.Thread(target=observer._scan_once)
    observer._thread = scan_thread
    observer._lifecycle = "running"
    scan_thread.start()
    assert final_scan_entered.wait(timeout=2)

    started = watchdog_module.time.monotonic()
    observer._stop_observing()
    elapsed = watchdog_module.time.monotonic() - started
    timed_out_evidence = observer._evidence()

    assert elapsed < 0.5
    assert scan_thread.is_alive()
    assert timed_out_evidence["lifecycle"] == "stop_timeout"
    assert timed_out_evidence["stop_status"] == "action_gate_timeout"
    assert timed_out_evidence["stop_timeout_seconds"] == 0.02
    assert timed_out_evidence["stop_requested"] is True
    assert timed_out_evidence["stop_confirmed"] is False
    assert timed_out_evidence["thread_alive"] is True
    assert observer._start() is False
    refused = observer._evidence()
    assert refused["start_status"] == "restart_refused_thread_alive"
    assert refused["lifecycle"] == "stop_timeout"
    assert refused["lifecycle_transitions"][-1]["reason"] == (
        "restart_refused_thread_alive"
    )

    release_final_scan.set()
    scan_thread.join(timeout=2)
    evidence = observer._evidence()
    observation = evidence["observations"][0]

    assert not scan_thread.is_alive()
    assert sent_messages == []
    assert evidence["lifecycle"] == "stop_timeout"
    assert evidence["stop_status"] == "action_gate_timeout"
    assert observation["action_status"] == "stop_requested"
    assert observation["classification"] == "stop_requested_preserved"
