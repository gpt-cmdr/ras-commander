"""Process inventory used to verify native preprocessing ownership."""

import sys

import pytest

psutil = pytest.importorskip("psutil")

from ras_commander import RasPreprocess  # noqa: E402

rp = sys.modules[RasPreprocess.__module__]


class FakeProcess:
    def __init__(self, pid, name, ppid, cmdline=None, created=1.0e9):
        self.info = {"pid": pid, "name": name}
        self._ppid, self._cmdline, self._created = ppid, cmdline, created

    def ppid(self):
        return self._ppid

    def cmdline(self):
        if self._cmdline is None:
            raise psutil.AccessDenied(self.info["pid"])
        return self._cmdline

    def create_time(self):
        return self._created


def _inventory(monkeypatch, processes, os_name="nt"):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(processes))
    monkeypatch.setattr(rp.os, "name", os_name)
    return RasPreprocess._preprocess_process_inventory()


def test_kernel_minimal_process_without_a_name_is_skipped_on_windows(monkeypatch):
    ras = FakeProcess(2001, "Ras.exe", 1500, ["Ras.exe", "-c", "M.prj", "M.p01"])
    procs = [FakeProcess(140, "", 4), FakeProcess(200, "", 0), FakeProcess(10, "python.exe", 1), ras]
    found = _inventory(monkeypatch, procs)
    assert [info["pid"] for _, info in found] == [2001]


def test_nameless_user_process_still_fails_closed(monkeypatch):
    assert _inventory(monkeypatch, [FakeProcess(3000, "", 1500)]) is None


def test_nameless_process_fails_closed_off_windows(monkeypatch):
    assert _inventory(monkeypatch, [FakeProcess(140, "", 4)], os_name="posix") is None
