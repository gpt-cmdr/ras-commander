"""OS-boundary tests for empty Windows process names; no HEC-RAS execution."""

import ctypes
import importlib
from types import SimpleNamespace

import pytest


inspection = importlib.import_module("ras_commander._process_inspection")


class AccessDenied(Exception):
    pass


class NoSuchProcess(Exception):
    pass


class Process:
    def __init__(self, pid=43210, name="", created=123.5):
        self.pid = pid
        self.info = {
            "pid": pid, "name": name, "create_time": created,
            "cmdline": ["Ras.exe", r"C:\Models\Fox.prj"],
            "exe": r"C:\HEC\Ras.exe", "cwd": r"C:\Models",
        }

    def name(self):
        value = self.info["name"]
        if isinstance(value, Exception):
            raise value
        return value


class Psutil:
    def __init__(self, process, fresh_times=(123.5, 123.5)):
        self.process = process
        self.fresh_times = iter(fresh_times)
        self.fresh_calls = []

    def process_iter(self, attrs):
        return iter([self.process])

    def Process(self, pid):
        self.fresh_calls.append(pid)
        value = next(self.fresh_times)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(pid=pid, create_time=lambda: value)


@pytest.fixture
def snapshot(monkeypatch):
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", True)
    calls = []

    def recover(pid):
        calls.append(pid)
        return "Secure System"

    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", recover)
    return calls


def test_os_name_classifies_non_ras_with_stable_identity_without_pid_allowlist(snapshot):
    psutil = Psutil(Process(pid=54321))
    result = inspection.scan_ras_processes(psutil_module=psutil)
    assert result.complete and not result.processes and not result.query_errors
    assert snapshot == [54321]
    assert psutil.fresh_calls == [54321, 54321]


def test_os_recovered_ras_name_remains_in_inventory(snapshot, monkeypatch):
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", lambda pid: "Ras.exe")
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process()))
    assert result.complete
    assert [(item.pid, item.name, item.create_time) for item in result.processes] == [
        (43210, "Ras.exe", 123.5)
    ]


def test_recovered_ras_name_does_not_bypass_required_metadata(snapshot, monkeypatch):
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", lambda pid: "Ras.exe")
    process = Process()
    process.info["cmdline"] = []
    result = inspection.scan_ras_processes(psutil_module=Psutil(process))
    assert not result.complete and not result.processes
    assert result.query_errors[0].operation == "normalize_process_metadata"


@pytest.mark.parametrize("fresh_times, expected_snapshots", [
    ((124.5,), 0),
    ((123.5, 124.5), 1),
    ((AccessDenied("identity inaccessible"),), 0),
    ((123.5, NoSuchProcess("exited during snapshot")), 1),
])
def test_reuse_or_unavailable_fresh_identity_fails_closed(snapshot, fresh_times, expected_snapshots):
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process(), fresh_times))
    assert not result.complete and not result.processes
    assert result.query_errors[0].operation == "classify_process"
    assert len(snapshot) == expected_snapshots


@pytest.mark.parametrize("created", [0, -1, float("nan"), float("inf")])
def test_unavailable_original_identity_is_not_skipped(snapshot, created):
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process(created=created)))
    assert not result.complete and not result.processes
    assert not snapshot


@pytest.mark.parametrize("name", [None, "", "  ", 123])
def test_unknown_os_name_is_not_skipped(snapshot, monkeypatch, name):
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", lambda pid: name)
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process()))
    assert not result.complete and not result.processes
    assert "empty or malformed" in result.query_errors[0].detail


def test_os_query_failure_remains_inventory_error(snapshot, monkeypatch):
    def fail(pid):
        raise OSError("snapshot unavailable")

    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", fail)
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process()))
    assert not result.complete and not result.processes
    assert result.query_errors[0].detail == "snapshot unavailable"


def test_original_access_denied_never_uses_name_fallback(snapshot):
    process = Process()
    process.info["name"] = None
    process.name = lambda: (_ for _ in ()).throw(AccessDenied("name denied"))
    result = inspection.scan_ras_processes(psutil_module=Psutil(process))
    assert not result.complete and not result.processes
    assert result.query_errors[0].reason_code == "access_denied"
    assert not snapshot


def test_missing_original_name_is_not_coerced_to_literal_none(snapshot):
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process(name=None)))
    assert not result.complete and not result.processes
    assert not snapshot


def test_named_process_does_not_query_native_snapshot(snapshot):
    psutil = Psutil(Process(name="python.exe"), fresh_times=())
    result = inspection.scan_ras_processes(psutil_module=psutil)
    assert result.complete and not result.processes
    assert not snapshot and not psutil.fresh_calls


def test_non_windows_nameless_process_remains_incomplete(snapshot, monkeypatch):
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", False)
    result = inspection.scan_ras_processes(psutil_module=Psutil(Process()))
    assert not result.complete and not snapshot


def test_recovered_identity_must_match_final_ras_metadata(snapshot, monkeypatch):
    process = Process()

    def recover(pid):
        process.info["create_time"] = 124.5
        return "Ras.exe"

    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", recover)
    result = inspection.scan_ras_processes(psutil_module=Psutil(process))
    assert not result.complete and not result.processes
    assert "identity changed" in result.query_errors[0].detail


class Function:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class ToolHelp:
    """Exercise the real ctypes adapter with deterministic OS API responses."""

    def __init__(self, rows, *, handle=123, terminal_error=18):
        self.rows = iter(rows)
        self.handle = handle
        self.error = 0
        self.terminal_error = terminal_error
        self.closed = []
        self.CreateToolhelp32Snapshot = Function(self.snapshot)
        self.Process32FirstW = Function(self.next)
        self.Process32NextW = Function(self.next)
        self.CloseHandle = Function(lambda handle: self.closed.append(handle) or True)

    def snapshot(self, flags, pid):
        assert (flags, pid) == (2, 0)
        return self.handle

    def next(self, handle, pointer):
        assert handle == self.handle
        entry = pointer._obj
        assert entry.dwSize == ctypes.sizeof(entry)
        try:
            entry.th32ProcessID, entry.szExeFile = next(self.rows)
        except StopIteration:
            self.error = self.terminal_error
            return False
        return True


def install_toolhelp(monkeypatch, toolhelp):
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: toolhelp, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: toolhelp.error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "native query failed"), raising=False)


def test_native_snapshot_reads_exact_pid_unicode_name_and_closes(monkeypatch):
    toolhelp = ToolHelp([(99, "Ras.exe"), (43210, "Secure System"), (100, "other.exe")])
    install_toolhelp(monkeypatch, toolhelp)
    assert inspection._windows_process_snapshot_name(43210) == "Secure System"
    assert toolhelp.closed == [123]


@pytest.mark.parametrize("rows, terminal_error", [([], 18), ([(43210, "")], 18), ([], 5)])
def test_native_missing_name_or_enumeration_failure_closes_and_raises(monkeypatch, rows, terminal_error):
    toolhelp = ToolHelp(rows, terminal_error=terminal_error)
    install_toolhelp(monkeypatch, toolhelp)
    with pytest.raises((ValueError, OSError)):
        inspection._windows_process_snapshot_name(43210)
    assert toolhelp.closed == [123]


def test_native_snapshot_failure_is_not_an_empty_inventory(monkeypatch):
    toolhelp = ToolHelp([], handle=ctypes.c_void_p(-1).value)
    install_toolhelp(monkeypatch, toolhelp)
    with pytest.raises(OSError):
        inspection._windows_process_snapshot_name(43210)
    assert not toolhelp.closed
