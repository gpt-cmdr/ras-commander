"""Focused control-flow regression tests for ``RasCmdr.compute_plan()``."""

import importlib
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
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
        self.results_df = None

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

    def update_results_df(self, plan_numbers=None):
        self.refresh_calls.append(("results", plan_numbers))


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


def test_compute_plan_uses_cached_plan_entries_when_prj_refresh_fails(
    monkeypatch, tmp_path
):
    """A deleted worker .prj should not prevent result-row recovery."""
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    class MissingPrjAfterRunRas:
        def __init__(self):
            self.project_folder = tmp_path
            self.project_name = "TestProject"
            self.prj_file = tmp_path / "TestProject.prj"
            self.ras_exe_path = "Ras.exe"
            self.plan_df = pd.DataFrame(
                {
                    "plan_number": ["01"],
                    "full_path": [str(plan_path)],
                    "HDF_Results_Path": [None],
                }
            )
            self.results_df = pd.DataFrame()

        def check_initialized(self):
            return None

        def get_plan_entries(self):
            raise FileNotFoundError(self.prj_file)

        def get_geom_entries(self):
            return pd.DataFrame()

        def get_flow_entries(self):
            return pd.DataFrame()

        def get_unsteady_entries(self):
            return pd.DataFrame()

        def update_results_df(self, plan_numbers=None):
            self.results_df = pd.DataFrame(
                {
                    "plan_number": list(plan_numbers),
                    "HDF_Results_Path": [str(hdf_path)],
                    "hdf_path": [str(hdf_path)],
                }
            )
            return self.results_df

    def fake_run(*args, **kwargs):
        hdf_path.write_text("computed\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=MissingPrjAfterRunRas(),
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"
    assert result.results_df_row["hdf_path"] == str(hdf_path)


def test_compute_plan_same_dest_folder_does_not_remove_active_project(
    monkeypatch, tmp_path
):
    """Passing the active project folder as dest_folder should run in place."""
    from ras_commander.RasCurrency import RasCurrency

    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        RasCurrency,
        "are_plan_results_current",
        staticmethod(lambda plan_number, ras_object: (True, "already current")),
    )

    result = RasCmdr.compute_plan(
        "01",
        dest_folder=tmp_path,
        overwrite_dest=True,
        ras_object=ras_obj,
    )

    assert result.success is True
    assert prj_path.exists()
    assert plan_path.exists()


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


def test_log_execution_results_uses_concise_info(caplog):
    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        RasCmdr._log_execution_results({"01": True, "02": False})

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    ]
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.name == "ras_commander.RasCmdr"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.RasCmdr"
    ]

    assert info_messages == ["Execution results: 1/2 plan(s) successful"]
    assert warning_messages == ["Failed plan(s): 02"]
    assert "Plan 01: Successful" in debug_messages
    assert "Plan 02: Failed" in debug_messages


def test_compute_plan_success_logging_is_concise(monkeypatch, tmp_path, caplog):
    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = tmp_path / "TestProject.prj"
    ras_obj.ras_exe_path = "Ras.exe"
    plan_path = tmp_path / "TestProject.p01"
    ras_obj.prj_file.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "are_plan_results_current",
        staticmethod(lambda plan_number, ras_object: (False, "stale results")),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    info_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    )
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is True
    assert "HEC-RAS execution completed for plan 01 in" in debug_text
    assert "seconds" in debug_text
    assert "Total run time for plan 01" not in info_text
    assert str(plan_path) not in info_text
    assert "Running command:" in debug_text
    assert str(plan_path) in debug_text


def test_compute_plan_treats_verified_hdf_after_launcher_error_as_success(
    monkeypatch, tmp_path, caplog
):
    """A nonzero Ras.exe launcher return can still yield a valid final HDF."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    hdf_path.write_text("computed\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    def fake_update_results_df(plan_numbers=None):
        ras_obj.results_df = pd.DataFrame(
            {
                "plan_number": list(plan_numbers),
                "hdf_path": [str(hdf_path)],
            }
        )
        return ras_obj.results_df

    ras_obj.update_results_df = fake_update_results_df

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "are_plan_results_current",
        staticmethod(lambda plan_number, ras_object: (False, "stale results")),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "Ras.exe")

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: True),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    error_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and record.name == "ras_commander.RasCmdr"
    )
    info_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"
    assert "Error running plan" not in error_text
    assert "final HDF verified after solver completion" in info_text


def test_compute_plan_treats_verified_hdf_after_normal_return_as_success(
    monkeypatch, tmp_path
):
    """Async HDF verification after a zero launcher return should set success."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    hdf_path = tmp_path / "TestProject.p01.hdf"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")
    hdf_path.write_text("computed\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    def fake_update_results_df(plan_numbers=None):
        ras_obj.results_df = pd.DataFrame(
            {
                "plan_number": list(plan_numbers),
                "hdf_path": [str(hdf_path)],
            }
        )
        return ras_obj.results_df

    ras_obj.update_results_df = fake_update_results_df

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "are_plan_results_current",
        staticmethod(lambda plan_number, ras_object: (False, "stale results")),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: True),
    )

    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras_obj,
        dialog_watchdog=False,
        verify=True,
    )

    assert result.success is True
    assert result.results_df_row["plan_number"] == "01"


def test_compute_plan_keeps_launcher_error_when_final_hdf_not_verified(
    monkeypatch, tmp_path, caplog
):
    """Real launcher failures should still be reported as failed plans."""
    rascurrency_module = importlib.import_module("ras_commander.RasCurrency")
    prj_path = tmp_path / "TestProject.prj"
    plan_path = tmp_path / "TestProject.p01"
    prj_path.write_text("Proj Title=TestProject\n", encoding="utf-8")
    plan_path.write_text("Plan Title=Plan 01\n", encoding="utf-8")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj_path
    ras_obj.ras_exe_path = "Ras.exe"

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascurrency_module.RasCurrency,
        "are_plan_results_current",
        staticmethod(lambda plan_number, ras_object: (False, "stale results")),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "Ras.exe")

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: False),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCmdr"):
        result = RasCmdr.compute_plan(
            "01",
            ras_object=ras_obj,
            dialog_watchdog=False,
        )

    error_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and record.name == "ras_commander.RasCmdr"
    )

    assert result.success is False
    assert "Error running plan: 01 (exit code 1)" in error_text


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
