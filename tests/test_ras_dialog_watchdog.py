"""Fail-closed tests for HEC-RAS modal-dialog supervision."""

import pytest

import ras_commander.RasDialogWatchdog as watchdog_module
from ras_commander.RasDialogWatchdog import DialogWatchdog
from ras_commander._legal_dialogs import (
    TCU_BLOCKING_ERROR,
    legal_dialog_blocking_reason,
)


class _FakeWin32Gui:
    def __init__(self, title, children, top_class="#32770"):
        self.title = title
        self.children = children
        self.top_class = top_class
        self.sent = []
        self.posted = []

    def GetWindowText(self, hwnd):
        if hwnd == 100:
            return self.title
        return self.children[hwnd][1]

    def GetClassName(self, hwnd):
        if hwnd == 100:
            return self.top_class
        return self.children[hwnd][0]

    def IsWindowVisible(self, _hwnd):
        return True

    def EnumWindows(self, callback, context):
        callback(100, context)

    def EnumChildWindows(self, _hwnd, callback, context):
        for child in self.children:
            callback(child, context)

    def SendMessage(self, *args):
        self.sent.append(args)

    def PostMessage(self, *args):
        self.posted.append(args)


class _FakeWin32Process:
    def __init__(self, pid):
        self.pid = pid

    def GetWindowThreadProcessId(self, _hwnd):
        return 1, self.pid


def _watchdog_with_gui(
    monkeypatch,
    title,
    children,
    safe_dialog_titles=None,
    top_class="#32770",
    pid=4321,
):
    fake = _FakeWin32Gui(title, children, top_class=top_class)
    monkeypatch.setattr(watchdog_module, "win32gui", fake)
    monkeypatch.setattr(watchdog_module, "win32process", _FakeWin32Process(pid))
    monkeypatch.setattr(watchdog_module, "_PSUTIL", False)
    instance = DialogWatchdog(safe_dialog_titles=safe_dialog_titles)
    terminated = []
    monkeypatch.setattr(
        instance,
        "_terminate_process_tree",
        lambda pid: terminated.append(pid) or True,
    )
    return instance, fake, terminated


def test_nonstandard_vb_tcu_form_is_discovered_and_blocked(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Terms and Conditions for Use (TCU)",
        {
            201: ("Static", "Please review the terms."),
            202: ("Button", "Agree"),
        },
        top_class="ThunderRT6FormDC",
        pid=4327,
    )
    instance.add_pid(4327)

    instance._scan_and_dismiss()

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert instance.blocked_reason == TCU_BLOCKING_ERROR
    assert terminated == [4327]


def test_untitled_nonstandard_vb_tcu_form_is_recognized_from_body(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Welcome",
        {
            201: ("Static", "Review the end-user license agreement."),
            202: ("Button", "Agree"),
        },
        top_class="ThunderRT6FormDC",
        pid=4328,
    )
    instance.add_pid(4328)

    instance._scan_and_dismiss()

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert instance.blocked_reason == TCU_BLOCKING_ERROR
    assert terminated == [4328]


def test_tcu_dialog_is_blocked_without_click_or_close(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Terms and Conditions for Use (TCU)",
        {
            201: ("Static", "Please review the terms."),
            202: ("Button", "Agree"),
            203: ("Button", "Do Not Agree"),
        },
    )

    instance._dismiss(100, 4321)

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert instance.blocked_reason == TCU_BLOCKING_ERROR
    assert terminated == [4321]


def test_unknown_multibutton_dialog_never_uses_first_button(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Unexpected model question",
        {
            201: ("Static", "Choose how to continue."),
            202: ("Button", "Retry"),
            203: ("Button", "Cancel"),
        },
    )

    instance._dismiss(100, 4322)

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert "unrecognized modal" in instance.blocked_reason
    assert terminated == [4322]


def test_informational_ok_dialog_can_be_dismissed(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Compute information",
        {
            201: ("Static", "The operation completed."),
            202: ("Button", "OK"),
        },
        safe_dialog_titles={"Compute information"},
    )

    instance._dismiss(100, 4323)

    assert fake.sent == [(202, 0x00F5, 0, 0)]
    assert fake.posted == []
    assert len(instance.dismissed) == 1
    assert instance.blocked == []
    assert terminated == []


def test_unknown_ok_cancel_dialog_is_blocked(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Unexpected confirmation",
        {
            201: ("Static", "Review this condition."),
            202: ("Button", "OK"),
            203: ("Button", "Cancel"),
        },
    )

    instance._dismiss(100, 4325)

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert terminated == [4325]


def test_unknown_close_dialog_is_blocked(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Unexpected report",
        {
            201: ("Static", "Something happened."),
            202: ("Button", "Close"),
        },
    )

    instance._dismiss(100, 4326)

    assert fake.sent == []
    assert fake.posted == []
    assert instance.dismissed == []
    assert len(instance.blocked) == 1
    assert terminated == [4326]


def test_yes_button_is_not_a_safe_generic_dismissal(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Confirm operation",
        {
            201: ("Static", "Continue?"),
            202: ("Button", "Yes"),
            203: ("Button", "No"),
        },
    )

    instance._dismiss(100, 4324)

    assert fake.sent == []
    assert fake.posted == []
    assert len(instance.blocked) == 1
    assert terminated == [4324]


def test_legal_marker_in_dialog_body_is_fail_closed():
    reason = legal_dialog_blocking_reason(
        title="Welcome",
        body="Review the end-user license agreement before continuing.",
    )

    assert reason == TCU_BLOCKING_ERROR


def test_registered_launcher_disables_global_process_discovery(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_PSUTIL", False)
    instance = DialogWatchdog(pids={111})

    assert instance._collect_ras_pids() == {111}


def test_global_process_discovery_is_opt_in(monkeypatch):
    process_iter_called = []

    class FakePsutil:
        @staticmethod
        def process_iter(_fields):
            process_iter_called.append(True)
            return []

    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(watchdog_module, "psutil", FakePsutil)

    instance = DialogWatchdog()

    assert instance._collect_ras_pids() == set()
    assert process_iter_called == []


def test_missing_pywin32_fails_before_monitor_start(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_WIN32", False)

    with pytest.raises(RuntimeError, match="refused to launch HEC-RAS"):
        DialogWatchdog().require_available()


def test_missing_psutil_fails_before_monitor_start(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_WIN32", True)
    monkeypatch.setattr(watchdog_module, "_PSUTIL", False)

    with pytest.raises(RuntimeError, match="requires psutil"):
        DialogWatchdog().require_available()


def test_access_denied_is_not_reported_as_terminated(monkeypatch):
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    class FakePsutil:
        @staticmethod
        def Process(_pid):
            raise AccessDenied()

    FakePsutil.AccessDenied = AccessDenied
    FakePsutil.NoSuchProcess = NoSuchProcess

    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(watchdog_module, "psutil", FakePsutil)

    assert DialogWatchdog()._terminate_process_tree(444) is False


def test_surviving_child_is_not_reported_as_terminated(monkeypatch):
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    class FakeProcess:
        def __init__(self, pid, children=None):
            self.pid = pid
            self._children = children or []

        def children(self, recursive=True):
            return self._children

        def kill(self):
            pass

    child = FakeProcess(446)
    parent = FakeProcess(445, [child])

    class FakePsutil:
        @staticmethod
        def Process(_pid):
            return parent

        @staticmethod
        def wait_procs(_targets, timeout):
            return [parent], [child]

    FakePsutil.AccessDenied = AccessDenied
    FakePsutil.NoSuchProcess = NoSuchProcess

    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(watchdog_module, "psutil", FakePsutil)

    assert DialogWatchdog()._terminate_process_tree(parent.pid) is False


def test_scan_failure_is_structured_and_terminates_registered_root(monkeypatch):
    instance = DialogWatchdog(pids={447})
    terminated = []
    monkeypatch.setattr(
        instance,
        "_scan_and_dismiss",
        lambda: (_ for _ in ()).throw(RuntimeError("scan failed")),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_process_tree",
        lambda pid: terminated.append(pid) or True,
    )

    instance._poll_loop()

    assert "modal supervision failed" in instance.blocked_reason
    assert "scan failed" in instance.blocked_reason
    assert terminated == [447]
    assert "termination verification" in instance.summary()
    assert "447: True" in instance.summary()


def test_child_dialog_terminates_registered_launcher_root(monkeypatch):
    instance, fake, terminated = _watchdog_with_gui(
        monkeypatch,
        "Unexpected child error",
        {
            201: ("Static", "A child process reported an error."),
            202: ("Button", "OK"),
        },
    )
    instance.add_pid(111)

    instance._dismiss(100, 222)

    assert fake.sent == []
    assert terminated == [111]
    assert instance.blocked[0].pid == 222
    assert instance.blocked[0].termination_root_pid == 111


def test_block_reason_is_published_before_tree_termination(monkeypatch):
    instance, _fake, _terminated = _watchdog_with_gui(
        monkeypatch,
        "Terms and Conditions for Use (TCU)",
        {
            201: ("Static", "Please review the terms."),
            202: ("Button", "Agree"),
        },
    )
    reason_seen_during_termination = []

    def terminate(_pid):
        reason_seen_during_termination.append(instance.blocked_reason)
        return True

    monkeypatch.setattr(instance, "_terminate_process_tree", terminate)

    instance._dismiss(100, 333)

    assert reason_seen_during_termination == [TCU_BLOCKING_ERROR]


def test_window_inspection_error_is_not_silently_ignored(monkeypatch):
    instance, fake, _terminated = _watchdog_with_gui(
        monkeypatch,
        "RAS",
        {},
        top_class="ThunderRT6Main",
        pid=449,
    )
    instance.add_pid(449)
    monkeypatch.setattr(
        fake,
        "GetClassName",
        lambda _hwnd: (_ for _ in ()).throw(RuntimeError("classification failed")),
    )

    with pytest.raises(RuntimeError, match="classification failed"):
        instance.observe_windows()

    assert fake.sent == []
    assert fake.posted == []


def test_child_text_inspection_error_is_not_silently_ignored(monkeypatch):
    instance, fake, _terminated = _watchdog_with_gui(
        monkeypatch,
        "Welcome",
        {201: ("Static", "end-user license agreement")},
        top_class="ThunderRT6FormDC",
        pid=450,
    )
    instance.add_pid(450)
    original = fake.GetWindowText

    def fail_child(hwnd):
        if hwnd == 201:
            raise RuntimeError("child text denied")
        return original(hwnd)

    monkeypatch.setattr(fake, "GetWindowText", fail_child)

    with pytest.raises(RuntimeError, match="child text denied"):
        instance.observe_windows()

    assert fake.sent == []
    assert fake.posted == []


def test_child_enumeration_error_is_not_silently_ignored(monkeypatch):
    instance, fake, _terminated = _watchdog_with_gui(
        monkeypatch,
        "Welcome",
        {},
        top_class="ThunderRT6FormDC",
        pid=451,
    )
    instance.add_pid(451)
    monkeypatch.setattr(
        fake,
        "EnumChildWindows",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("children unavailable")),
    )

    with pytest.raises(RuntimeError, match="children unavailable"):
        instance.observe_windows()


def test_dismiss_inspection_failure_propagates_to_supervisor(monkeypatch):
    instance, fake, _terminated = _watchdog_with_gui(
        monkeypatch,
        "Unexpected",
        {201: ("Static", "body")},
        pid=452,
    )
    monkeypatch.setattr(
        fake,
        "GetWindowText",
        lambda _hwnd: (_ for _ in ()).throw(RuntimeError("title unavailable")),
    )

    with pytest.raises(RuntimeError, match="title unavailable"):
        instance._dismiss(100, 452)

    assert fake.sent == []
    assert fake.posted == []


def test_registered_tree_access_denied_fails_supervision(monkeypatch):
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    class FakePsutil:
        @staticmethod
        def Process(_pid):
            raise AccessDenied()

    FakePsutil.AccessDenied = AccessDenied
    FakePsutil.NoSuchProcess = NoSuchProcess
    monkeypatch.setattr(watchdog_module, "_PSUTIL", True)
    monkeypatch.setattr(watchdog_module, "psutil", FakePsutil)
    instance = DialogWatchdog(pids={453})

    with pytest.raises(RuntimeError, match="enumeration was denied"):
        instance.scoped_pids()


def test_monitor_thread_join_timeout_sets_supervision_error(monkeypatch):
    class StuckThread:
        def is_alive(self):
            return True

        def join(self, timeout):
            assert timeout == 5

    instance = DialogWatchdog()
    instance._thread = StuckThread()

    instance.stop()

    assert "did not stop" in instance.supervision_error
