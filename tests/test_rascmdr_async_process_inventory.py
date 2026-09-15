"""Async completion uses canonical Windows inventory; no HEC-RAS is launched."""

import importlib
import os
from types import SimpleNamespace

import h5py
import psutil
import pytest

from ras_commander import RasCmdr


cmdr = importlib.import_module("ras_commander.RasCmdr")
inspection = importlib.import_module("ras_commander._process_inspection")


class Process:
    def __init__(self, name="", *, command=None, cwd=None):
        self.pid = 54321
        self.info = {
            "pid": self.pid,
            "name": name,
            "create_time": 123.5,
            "cmdline": command,
            "exe": r"C:\HEC\RasUnsteady.exe",
            "cwd": cwd,
        }

    def name(self):
        return self.info["name"]

    def cmdline(self):
        return self.info["cmdline"]

    def cwd(self):
        return self.info["cwd"]


class BytesPath:
    def __fspath__(self):
        return b"unknown"


@pytest.fixture
def completed_plan(tmp_path):
    hdf_path = tmp_path / "Model.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_group("Plan Data/Plan Information")
        hdf.create_dataset(
            "Results/Summary/Compute Messages (text)",
            data=b"Steady Flow Simulation HEC-RAS 6.6\r\nComplete Process\t1\r\n",
        )
    assert RasCmdr._verify_completion(hdf_path) is True
    assert not (tmp_path / "Model.p01.tmp.hdf").exists()
    return SimpleNamespace(project_folder=tmp_path, project_name="Model")


def install_inventory(monkeypatch, process, *, recovered_name="Secure System", fresh_times=(123.5, 123.5)):
    """Keep the real inventory and name-recovery code; replace only OS reads."""
    monkeypatch.setattr(cmdr, "os", SimpleNamespace(
        name="nt", path=os.path, fspath=os.fspath, PathLike=os.PathLike
    ))
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", True)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([process]))
    fresh = iter(fresh_times)
    identities = []

    def fresh_process(pid):
        identities.append(pid)
        value = next(fresh)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(pid=pid, create_time=lambda: value)

    def snapshot(pid):
        if isinstance(recovered_name, Exception):
            raise recovered_name
        return recovered_name

    monkeypatch.setattr(psutil, "Process", fresh_process)
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", snapshot)
    return identities


def test_complete_hdf_with_recovered_non_ras_name_finishes_async_wait(monkeypatch, completed_plan):
    identities = install_inventory(monkeypatch, Process())

    assert RasCmdr._wait_for_async_plan_completion("01", completed_plan) is True
    assert identities == [54321, 54321]


@pytest.mark.parametrize(
    ("process_name", "recovered_name", "fresh_times"),
    [
        ("", None, (123.5, 123.5)),
        ("", OSError("snapshot denied"), (123.5,)),
        ("", "Secure System", (123.5, 124.5)),
        ("", "Secure System", (psutil.AccessDenied(pid=54321),)),
        ("", "RasUnsteady.exe", (123.5, 123.5)),
        ("RasUnsteady.exe", "unused", ()),
    ],
)
def test_complete_hdf_cannot_override_incomplete_or_uncertain_ras_inventory(
    monkeypatch, completed_plan, process_name, recovered_name, fresh_times
):
    install_inventory(
        monkeypatch, Process(name=process_name),
        recovered_name=recovered_name, fresh_times=fresh_times,
    )

    assert RasCmdr._wait_for_async_plan_completion("01", completed_plan) is False


@pytest.mark.parametrize("name", ["", "RasUnsteady.exe"])
def test_canonical_inventory_preserves_exact_tmp_hdf_solver_match(monkeypatch, tmp_path, name):
    target = tmp_path / "Model.p01.tmp.hdf"
    process = Process(name=name, command=["RasUnsteady.exe", str(target)], cwd=str(tmp_path))
    install_inventory(monkeypatch, process, recovered_name="RasUnsteady.exe")

    assert RasCmdr._rasunsteady_process_running_for_tmp_hdf(target) is True


def test_complete_inventory_keeps_other_plan_solver_separate(monkeypatch, tmp_path):
    process = Process(name="RasUnsteady.exe", command=["RasUnsteady.exe", "b02"], cwd=str(tmp_path))
    install_inventory(monkeypatch, process)

    assert RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_path / "Model.p01.tmp.hdf") is False


@pytest.mark.parametrize("invalid_token", [None, 123, False, b"unknown", BytesPath()])
def test_malformed_solver_command_cannot_become_a_proven_nonmatch(
    monkeypatch, completed_plan, invalid_token
):
    # Without token validation, stringification plus another plan's b02 marker
    # could incorrectly turn malformed process metadata into a proved nonmatch.
    process = Process(
        name="RasUnsteady.exe",
        command=["RasUnsteady.exe", invalid_token, "b02"],
        cwd=str(completed_plan.project_folder),
    )
    install_inventory(monkeypatch, process)

    assert RasCmdr._wait_for_async_plan_completion("01", completed_plan) is False


def test_text_pathlike_solver_argument_keeps_exact_match(monkeypatch, tmp_path):
    target = tmp_path / "Model.p01.tmp.hdf"
    process = Process(name="RasUnsteady.exe", command=["RasUnsteady.exe", target], cwd=str(tmp_path))
    install_inventory(monkeypatch, process)

    assert RasCmdr._rasunsteady_process_running_for_tmp_hdf(target) is True


def test_non_windows_async_state_does_not_query_windows_inventory(monkeypatch, tmp_path):
    monkeypatch.setattr(cmdr, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: pytest.fail("Windows inventory queried"))

    assert RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_path / "Model.p01.tmp.hdf") is False
