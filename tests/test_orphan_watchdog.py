"""Deterministic safety tests for the standalone RasControl watchdog worker."""

from __future__ import annotations

import importlib


watchdog = importlib.import_module("ras_commander._orphan_watchdog")


def _run_trigger(tmp_path, process_factory):
    lock_file = tmp_path / "session.lock"
    lock_file.write_text("owned session evidence", encoding="utf-8")
    original_process = watchdog.psutil.Process
    watchdog.psutil.Process = process_factory
    try:
        exit_code, result = watchdog._cleanup_after_trigger(
            lock_file=lock_file,
            ras_pid=42,
            ras_create_time=123.5,
            ras_name="Ras.exe",
            wait_timeout=0.01,
        )
    finally:
        watchdog.psutil.Process = original_process
    return exit_code, result, lock_file


def test_access_denied_retains_lock_and_never_signals(tmp_path):
    signals = []
    constructions = 0

    class InaccessibleProcess:
        def __init__(self, pid):
            nonlocal constructions
            self.pid = pid
            self.generation = constructions
            constructions += 1

        def create_time(self):
            if self.generation:
                raise watchdog.psutil.AccessDenied(self.pid)
            return 123.5

        @staticmethod
        def name():
            return "Ras.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            signals.append("terminate")

    exit_code, result, lock_file = _run_trigger(tmp_path, InaccessibleProcess)

    assert exit_code != 0
    assert result.state == "access_denied"
    assert "AccessDenied" in result.error
    assert constructions == 2
    assert signals == []
    assert lock_file.read_text(encoding="utf-8") == "owned session evidence"


def test_query_uncertainty_retains_lock_and_never_signals(tmp_path):
    class UnqueryableProcess:
        def __init__(self, _pid):
            raise OSError("query failed")

    exit_code, result, lock_file = _run_trigger(tmp_path, UnqueryableProcess)

    assert exit_code != 0
    assert result.state == "query_failed"
    assert "query failed" in result.error
    assert lock_file.is_file()


def test_pid_reuse_removes_lock_without_signalling_replacement(tmp_path):
    signals = []
    constructions = 0

    class ReusedProcess:
        def __init__(self, pid):
            nonlocal constructions
            self.pid = pid
            self.generation = constructions
            constructions += 1

        def create_time(self):
            return 123.5 if self.generation == 0 else 999.0

        @staticmethod
        def name():
            return "Ras.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            signals.append("terminate")

        def kill(self):
            signals.append("kill")

    exit_code, result, lock_file = _run_trigger(tmp_path, ReusedProcess)

    assert exit_code == 0
    assert result.state == "pid_reused"
    assert constructions == 2
    assert signals == []
    assert not lock_file.exists()


def test_terminate_failure_retains_lock_and_reports_failure(tmp_path):
    signals = []

    class TerminateFailure:
        def __init__(self, pid):
            self.pid = pid

        @staticmethod
        def create_time():
            return 123.5

        @staticmethod
        def name():
            return "ras.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            signals.append("terminate")
            raise OSError("terminate failed")

    exit_code, result, lock_file = _run_trigger(tmp_path, TerminateFailure)

    assert exit_code != 0
    assert result.state == "terminate_failed"
    assert "terminate failed" in result.error
    assert signals == ["terminate"]
    assert lock_file.is_file()


def test_wait_timeout_and_survivor_retains_lock(tmp_path):
    events = []

    class Survivor:
        def __init__(self, pid):
            self.pid = pid

        @staticmethod
        def create_time():
            return 123.5

        @staticmethod
        def name():
            return "ras.exe"

        @staticmethod
        def is_running():
            return True

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

        def wait(self, timeout):
            events.append(("wait", timeout))
            raise watchdog.psutil.TimeoutExpired(timeout)

    exit_code, result, lock_file = _run_trigger(tmp_path, Survivor)

    assert exit_code != 0
    assert result.state == "survivor"
    assert result.terminated is True
    assert result.killed is True
    assert events == ["terminate", ("wait", 0.01), "kill", ("wait", 0.01)]
    assert lock_file.is_file()


def test_confirmed_absence_removes_lock_without_signal(tmp_path):
    def absent(pid):
        raise watchdog.psutil.NoSuchProcess(pid)

    exit_code, result, lock_file = _run_trigger(tmp_path, absent)

    assert exit_code == 0
    assert result.state == "absent"
    assert not lock_file.exists()


def test_confirmed_stop_removes_lock(tmp_path):
    events = []

    class StoppedAfterWait:
        running = True

        def __init__(self, pid):
            self.pid = pid

        @staticmethod
        def create_time():
            return 123.5

        @staticmethod
        def name():
            return "ras.exe"

        def is_running(self):
            return self.running

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))
            self.running = False

    process = StoppedAfterWait(42)

    exit_code, result, lock_file = _run_trigger(
        tmp_path,
        lambda _pid: process,
    )

    assert exit_code == 0
    assert result.state == "terminated"
    assert result.terminated is True
    assert events == ["terminate", ("wait", 0.01)]
    assert not lock_file.exists()
