"""Focused control-flow regression tests for ``RasCmdr.compute_plan()``."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.RasCmdr import RasCmdr


rascmdr_module = importlib.import_module("ras_commander.RasCmdr")


class _DummyRas:
    """Minimal ras-like object for compute_plan control-flow tests."""

    def __init__(self, init_exception=None):
        self.project_folder = r"C:\fake_project"
        self.prj_file = r"C:\fake_project\test.prj"
        self.ras_exe_path = r"C:\Program Files\HEC-RAS\Ras.exe"
        self.init_exception = init_exception
        self.refresh_calls = []
        self.plan_df = None
        self.geom_df = None
        self.flow_df = None
        self.unsteady_df = None

    def check_initialized(self):
        if self.init_exception is not None:
            raise self.init_exception

    def get_plan_entries(self):
        self.refresh_calls.append("plan")
        return "plan_df"

    def get_geom_entries(self):
        self.refresh_calls.append("geom")
        return "geom_df"

    def get_flow_entries(self):
        self.refresh_calls.append("flow")
        return "flow_df"

    def get_unsteady_entries(self):
        self.refresh_calls.append("unsteady")
        return "unsteady_df"


def test_compute_plan_returns_failed_result_for_regular_exception():
    """Regular Exception paths should stay bool-compatible and non-raising."""
    ras_obj = _DummyRas(init_exception=RuntimeError("boom"))

    result = RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert isinstance(result, ComputeResult)
    assert result.success is False
    assert result.results_df_row is None
    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]


def test_compute_plan_does_not_swallow_keyboard_interrupt():
    """
    Non-Exception exits must propagate after cleanup.

    This guards against returning from a finally block, which would suppress
    ``KeyboardInterrupt`` and similar BaseException subclasses.
    """
    ras_obj = _DummyRas(init_exception=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]


def test_windows_path_to_wsl_decodes_utf8(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="/mnt/c/model-\xe9\n", stderr="")

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    assert RasCmdr._windows_path_to_wsl("C:/model-\xe9") == "/mnt/c/model-\xe9"
    assert calls[0][0] == ["wsl", "wslpath", "-a", "C:/model-\xe9"]
    assert calls[0][1]["text"] is True
    assert calls[0][1]["encoding"] == "utf-8"


def test_wsl_linux_retry_script_uses_utf8_and_cleans_io_tmp(monkeypatch, tmp_path):
    popen_calls = []
    run_calls = []

    class FakePopen:
        returncode = 1

        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

        def communicate(self, timeout=None):
            return "", "ras failed"

        def kill(self):
            pass

    def fake_run(args, **kwargs):
        run_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        RasCmdr,
        "_windows_path_to_wsl",
        staticmethod(lambda path: f"/mnt/test/{Path(path).name}"),
    )
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    io_tmp_hdf = tmp_path / "io.tmp.hdf"
    io_tmp_hdf.write_bytes(b"stale")

    result = RasCmdr._compute_plan_linux_via_wsl(
        ras_exe="/mnt/c/HEC-RAS/RasUnsteady",
        ras_exe_dir="/mnt/c/HEC-RAS",
        plan_number="01",
        geom_num="01",
        project_dir=tmp_path,
        project_name="Demo",
        tmp_hdf=tmp_path / "Demo.p01.tmp.hdf",
        timeout_sec=30,
        dos2unix=False,
        retry=False,
        retry_delay_sec=0,
        ras_obj=SimpleNamespace(),
    )

    assert result.success is False
    assert not io_tmp_hdf.exists()

    script = popen_calls[0][0][3]
    assert '[ -d "\\$d" ] && ld_path=' not in script
    assert 'if [ -d "\\$d" ]; then' in script
    assert popen_calls[0][1]["text"] is True
    assert popen_calls[0][1]["encoding"] == "utf-8"
    expected_cleanup = (
        f"cd /mnt/test/{tmp_path.name} && "
        "find . -maxdepth 1 -type l -name 'io.*' -delete"
    )
    assert run_calls[0][0] == ["wsl", "bash", "-lc", expected_cleanup]
    assert run_calls[0][1]["encoding"] == "utf-8"
