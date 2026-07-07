import logging
from types import SimpleNamespace

import ras_commander.RasDialogWatchdog as watchdog_module
from ras_commander.RasDialogWatchdog import DialogWatchdog


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
