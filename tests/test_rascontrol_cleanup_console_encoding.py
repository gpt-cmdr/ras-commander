"""RasControl cleanup reports on a console that cannot encode their status marks.

``RasControl.cleanup_orphans`` and ``RasControl.force_cleanup_all`` print status marks
outside ASCII. On a cp1252 console (the default for a redirected Windows process)
``print`` raised ``UnicodeEncodeError`` after the orphan had already been handled, so a
successful cleanup ended in an exception. No HEC-RAS process is started or signalled here.
"""

from __future__ import annotations

import importlib
import io
import time
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace

import sys

import pytest

pytest.importorskip("psutil")

# RasControl drives the HECRASController COM interface, which exists only on Windows; the
# reports these tests check name Windows project paths.
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="RasControl is Windows-only")

from ras_commander import RasControl

rascontrol_module = importlib.import_module("ras_commander.RasControl")


@contextmanager
def narrow_console(encoding: str):
    """``sys.stdout`` as a strict text stream in ``encoding``; yields a reader of its text."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding=encoding, errors="strict", newline="\n")

    def text() -> str:
        stream.flush()
        return raw.getvalue().decode(encoding)

    with redirect_stdout(stream):
        yield text


def _orphan():
    return SimpleNamespace(
        ras_pid=424242, python_pid=434343, project_path=r"C:\models\Example.prj",
        start_time=time.time() - 120, session_id="not-a-real-session",
    )


def test_the_status_marks_do_not_fit_a_cp1252_console():
    """The premise: a plain ``print`` of the report fails on such a console."""
    with narrow_console("cp1252"), pytest.raises(UnicodeEncodeError):
        print("\u2705 No orphaned processes found")


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_cleanup_orphans_reports_no_orphans_on_a_narrow_console(monkeypatch, encoding):
    monkeypatch.setattr(RasControl, "scan_orphans", staticmethod(lambda: []))

    with narrow_console(encoding) as text:
        assert RasControl.cleanup_orphans(interactive=False) == 0
        report = text()

    assert "No orphaned processes found" in report


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_cleanup_orphans_lists_orphans_on_a_narrow_console(monkeypatch, encoding):
    monkeypatch.setattr(RasControl, "scan_orphans", staticmethod(lambda: [_orphan()]))

    with narrow_console(encoding) as text:
        assert RasControl.cleanup_orphans(interactive=False, dry_run=True) == 0
        report = text()

    assert "Found 1 orphaned RAS process(es):" in report
    assert "PID 424242: Example.prj" in report
    assert "[Dry run - no action taken]" in report


def test_cleanup_orphans_reports_the_result_on_a_narrow_console(monkeypatch):
    """The summary after the per-process loop is the line that raised."""
    monkeypatch.setattr(RasControl, "scan_orphans", staticmethod(lambda: [_orphan()]))

    def gone(pid):
        raise rascontrol_module.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(rascontrol_module.psutil, "Process", gone)

    with narrow_console("cp1252") as text:
        assert RasControl.cleanup_orphans(interactive=False) == 0
        report = text()

    assert "Failed to terminate PID 424242" in report
    assert "Cleaned up 0/1 processes" in report


def test_force_cleanup_all_reports_no_processes_on_a_narrow_console(monkeypatch):
    monkeypatch.setattr(rascontrol_module.psutil, "process_iter", lambda *_args, **_kwargs: [])

    with narrow_console("cp1252") as text:
        assert RasControl.force_cleanup_all() == 0
        report = text()

    assert "No ras.exe processes found" in report


def test_console_print_keeps_the_marks_where_the_console_has_them():
    with narrow_console("utf-8") as text:
        rascontrol_module._console_print("\u2705 done")
        assert text() == "\u2705 done\n"
