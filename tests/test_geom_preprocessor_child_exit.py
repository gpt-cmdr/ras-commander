"""Exit status of short-lived HEC-RAS preprocessing helpers.

``psutil.Process.wait()`` opens a Windows handle by PID only when it runs and
returns ``None`` once the process has exited with no handle left open. HEC-RAS
starts short-lived helpers (``PipeServer.exe``, ``conhost.exe``,
``RasPlotDriver.exe``) during preprocessing. When one exited before the waiter
thread ran, the completion check reported ``exit status None`` and FAILED a
successful run. These tests use real processes whose parent has exited, so no
handle other than RAS Commander's keeps their exit code.
"""

import os
import subprocess
import sys
import threading
import time

import psutil
import pytest

from ras_commander.geom.GeomPreprocessor import GeomPreprocessor as GP
from ras_commander.geom.GeomPreprocessor import _NativeExitHandle

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process handles")


def _orphan(exit_code: int, seconds: float) -> psutil.Process:
    """Start a process whose launcher exits at once, leaving no other handle."""
    child_code = f"import sys, time; time.sleep({seconds}); sys.exit({exit_code})"
    python = getattr(sys, "_base_executable", sys.executable)
    launcher = (
        "import subprocess, sys\n"
        f"p = subprocess.Popen([{python!r}, '-c', {child_code!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        "print(p.pid, flush=True)\n"
    )
    out = subprocess.run(
        [python, "-c", launcher], capture_output=True, text=True, check=True
    )
    return psutil.Process(int(out.stdout.strip()))


def _finish(record, timeout=30.0):
    stop = time.monotonic() + timeout
    while not record["finished"]:
        assert time.monotonic() < stop, "waiter did not finish"
        time.sleep(0.05)
    return record


class _LateThread(threading.Thread):
    """Start the waiter only after the watched process has exited."""

    delay = 0.0

    def start(self):
        time.sleep(self.delay)
        super().start()


@pytest.mark.parametrize("code", [0, 7])
def test_exit_code_survives_a_late_waiter_thread(monkeypatch, code):
    child = _orphan(code, 0.3)
    _LateThread.delay = 1.5  # the child exits ~0.3 s after start
    monkeypatch.setattr(threading, "Thread", _LateThread)
    record = _finish(GP._watch_preprocess_child(child, time.monotonic() + 60))
    assert record["error"] is None
    assert record["exit_code"] == code


def test_nonzero_exit_still_fails_the_completion_wait(monkeypatch):
    child = _orphan(3, 0.2)
    record = _finish(GP._watch_preprocess_child(child, time.monotonic() + 60))
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child("x.tmp.hdf", time.time(), 60, (record,))
    assert any("exit status 3" in error for error in result["errors"])


def test_child_gone_before_its_handle_opens_is_unverified_not_success(monkeypatch):
    child = _orphan(0, 0.1)
    stop = time.monotonic() + 30
    while psutil.pid_exists(child.pid):
        assert time.monotonic() < stop
        time.sleep(0.05)
    record = GP._watch_preprocess_child(child, time.monotonic() + 60)
    assert record["finished"] and record["exit_code"] is None
    assert "exit status unobservable" in record["error"]
    monkeypatch.setattr(GP, "_ras_processes_using_path", lambda path: [])
    result = GP._wait_for_preprocess_child("x.tmp.hdf", time.time(), 60, (record,))
    assert result["errors"]


def test_reused_pid_is_not_accepted_as_the_child():
    child = _orphan(0, 5.0)
    try:
        with pytest.raises(psutil.NoSuchProcess, match="different process"):
            _NativeExitHandle.open(child.pid, child.create_time() + 100.0)
    finally:
        child.kill()


def test_wait_timeout_is_reported():
    child = _orphan(0, 10.0)
    try:
        record = _finish(GP._watch_preprocess_child(child, time.monotonic() + 0.3))
        assert record["timed_out"] is True
        assert "timed out" in record["error"]
    finally:
        child.kill()
