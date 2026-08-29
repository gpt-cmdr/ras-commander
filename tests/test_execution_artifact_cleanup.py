"""Regression tests for version-aware execution-artifact cleanup."""

from __future__ import annotations

import importlib
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import (
    RasCmdr,
    RasControl,
    RasCurrency,
    ResultArtifactAmbiguityError,
)
from ras_commander.ExecutionArtifacts import (
    PlanExecutionCleanupError,
    infer_execution_result_format,
)
from ras_commander.remote.Utils import clear_staged_plan_execution_artifacts


class _ComputeRas:
    def __init__(self, root: Path, version: str) -> None:
        self.initialized = True
        self.project_folder = root
        self.project_name = "Model"
        self.prj_file = root / "Model.prj"
        self.ras_version = version
        self.ras_exe_path = root / version / "Ras.exe"
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "full_path": str(root / "Model.p01")}]
        )
        self.geom_df = pd.DataFrame()
        self.flow_df = pd.DataFrame()
        self.unsteady_df = pd.DataFrame()
        self.results_df = pd.DataFrame()

    def check_initialized(self) -> None:
        return None

    def get_plan_entries(self) -> pd.DataFrame:
        return self.plan_df

    def get_geom_entries(self) -> pd.DataFrame:
        return self.geom_df

    def get_flow_entries(self) -> pd.DataFrame:
        return self.flow_df

    def get_unsteady_entries(self) -> pd.DataFrame:
        return self.unsteady_df

    def update_results_df(self, plan_numbers=None) -> pd.DataFrame:
        return self.results_df


def _write_project(root: Path, version: str) -> _ComputeRas:
    root.mkdir()
    ras_obj = _ComputeRas(root, version)
    ras_obj.prj_file.write_text(
        "Proj Title=Cleanup Test\nCurrent Plan=p01\nPlan File=p01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        f"Plan Title=Base\nProgram Version={version}\n",
        encoding="ascii",
    )
    ras_obj.ras_exe_path.parent.mkdir(parents=True, exist_ok=True)
    ras_obj.ras_exe_path.write_bytes(b"synthetic ras executable")
    return ras_obj


def _patch_compute_scaffolding(monkeypatch, ras_obj: _ComputeRas) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda *_args, **_kwargs: ras_obj.project_folder / "Model.p01"),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_confirm_plan_solver_quiescence",
        staticmethod(lambda *_args, **_kwargs: True),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_launcher_create_time",
        staticmethod(lambda _pid: 123.5),
    )

    class RunAdapterPopen:
        pid = 2468

        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = None

        def wait(self, timeout=None):
            del timeout
            try:
                completed = rascmdr_module.subprocess.run(
                    self.argv,
                    shell=False,
                )
                self.returncode = int(getattr(completed, "returncode", 0))
            except rascmdr_module.subprocess.CalledProcessError as exc:
                self.returncode = int(exc.returncode)
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "Popen",
        RunAdapterPopen,
    )


def _fake_safe_com_open_close(controller):
    """Run a fake Controller operation and report a positively safe close."""

    def open_close(
        _path,
        _version,
        operation,
        *,
        close_outcome_callback=None,
        **_kwargs,
    ):
        executable = Path(_path).parent / "Ras.exe"
        executable.write_bytes(b"fake Controller executable")
        session_callback = _kwargs.get("session_open_callback")
        if session_callback is not None:
            session_callback(
                SimpleNamespace(
                    ras_pid=4321,
                    ras_create_time=123.5,
                    detection_confidence=100,
                    ras_executable_path=str(executable),
                    ras_executable_sha256=hashlib.sha256(
                        executable.read_bytes()
                    ).hexdigest(),
                )
            )
        try:
            return operation(controller)
        finally:
            if close_outcome_callback is not None:
                close_outcome_callback(
                    True,
                    SimpleNamespace(
                        ras_pid=4321,
                        process_survived=False,
                    ),
                    None,
                )

    return open_close


@pytest.fixture(autouse=True)
def _empty_controller_post_close_inventory(monkeypatch):
    rascontrol_module = importlib.import_module("ras_commander.RasControl")
    monkeypatch.setattr(
        rascontrol_module,
        "_inspect_controller_post_close_processes",
        lambda **_kwargs: (
            SimpleNamespace(complete=True, matched=()),
            SimpleNamespace(
                complete=True,
                processes=(),
                query_errors=(),
            ),
        ),
    )


def test_modern_compute_removes_legacy_before_and_after_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    ras_obj = _write_project(tmp_path / "modern", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    sidecar = ras_obj.project_folder / "Model.p01.computeMsgs.txt"
    legacy.write_bytes(b"stale legacy")
    sidecar.write_text("stale message\n", encoding="ascii")
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    def fake_run(*_args, **_kwargs):
        assert not legacy.exists()
        assert not sidecar.exists()
        hdf.write_bytes(b"new hdf")
        legacy.write_bytes(b"modern HEC-RAS recreated this")
        sidecar.write_text("new message\n", encoding="ascii")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert hdf.is_file()
    assert not legacy.exists()
    assert sidecar.read_text(encoding="ascii") == "new message\n"


def test_modern_cleanup_runs_after_prelaunch_plan_preparation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "modern-prelaunch", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    sidecar = ras_obj.project_folder / "Model.p01.computeMsgs.txt"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    def fake_set_num_cores(*_args, **_kwargs):
        # Simulate a prelaunch hook or preparatory operation recreating stale
        # artifacts after the skip decision but before the solver starts.
        legacy.write_bytes(b"recreated during preparation")
        sidecar.write_text("stale preparation message\n", encoding="ascii")
        return True

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "set_num_cores",
        staticmethod(fake_set_num_cores),
    )

    def fake_run(*_args, **_kwargs):
        assert not legacy.exists()
        assert not sidecar.exists()
        hdf.write_bytes(b"new hdf")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        num_cores=4,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert hdf.is_file()
    assert not legacy.exists()


def test_legacy_compute_removes_hdf_before_and_after_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    ras_obj = _write_project(tmp_path / "legacy", "4.10")
    legacy = ras_obj.project_folder / "Model.O01"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    sidecar = ras_obj.project_folder / "Model.p01.comp_msgs.txt"
    hdf.write_bytes(b"stale hdf")
    sidecar.write_text("stale message\n", encoding="ascii")
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    def fake_run(*_args, **_kwargs):
        assert not hdf.exists()
        assert not sidecar.exists()
        legacy.write_bytes(b"new legacy output")
        hdf.write_bytes(b"unexpected recreated hdf")
        sidecar.write_text("new legacy message\n", encoding="ascii")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert legacy.is_file()
    assert not hdf.exists()
    assert sidecar.read_text(encoding="ascii") == "new legacy message\n"


@pytest.mark.parametrize(
    ("engine_version", "declared_version", "selected_name", "opposing_name"),
    [
        ("6.60", "4.00", "Model.p01.hdf", "Model.O01"),
        ("4.10", "6.60", "Model.O01", "Model.p01.hdf"),
    ],
)
def test_compute_cleanup_uses_selected_engine_not_plan_declaration(
    tmp_path: Path,
    monkeypatch,
    engine_version: str,
    declared_version: str,
    selected_name: str,
    opposing_name: str,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(
        tmp_path / f"engine-{engine_version.replace('.', '_')}",
        engine_version,
    )
    plan_path = ras_obj.project_folder / "Model.p01"
    plan_path.write_text(
        f"Plan Title=Base\nProgram Version={declared_version}\n",
        encoding="ascii",
    )
    selected = ras_obj.project_folder / selected_name
    opposing = ras_obj.project_folder / opposing_name
    opposing.write_bytes(b"stale opposing result")
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    def fake_run(*_args, **_kwargs):
        assert not opposing.exists()
        selected.write_bytes(b"new selected result")
        opposing.write_bytes(b"HEC-RAS recreated opposing result")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert selected.read_bytes() == b"new selected result"
    assert not opposing.exists()


@pytest.mark.parametrize(
    ("configured_version", "executable_version"),
    [("4.10", "6.60"), ("6.60", "4.10")],
)
def test_execution_format_fails_closed_when_metadata_and_executable_disagree(
    tmp_path: Path,
    configured_version: str,
    executable_version: str,
) -> None:
    execution_engine = SimpleNamespace(
        ras_version=configured_version,
        ras_exe_path=tmp_path / executable_version / "Ras.exe",
    )

    with pytest.raises(ValueError, match="metadata disagrees"):
        infer_execution_result_format(execution_engine)


def test_versioned_executable_is_authoritative_within_result_family(
    tmp_path: Path,
) -> None:
    execution_engine = SimpleNamespace(
        ras_version="6.30",
        ras_exe_path=tmp_path / "7.0.1" / "Ras.exe",
    )

    assert infer_execution_result_format(execution_engine) == "hdf"


def test_compute_skip_existing_is_read_only_for_single_hdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "skip-single", "6.60")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    sidecar = ras_obj.project_folder / "Model.p01.computeMsgs.txt"
    hdf.write_bytes(b"existing hdf")
    sidecar.write_text("existing message\n", encoding="ascii")
    plan_path = ras_obj.project_folder / "Model.p01"
    original_plan_bytes = plan_path.read_bytes()
    _patch_compute_scaffolding(monkeypatch, ras_obj)
    monkeypatch.setattr(
        RasCmdr,
        "_verify_completion",
        staticmethod(lambda *_args, **_kwargs: True),
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("skipped plan must not execute")
        ),
    )
    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "use_optimal_hdf_settings",
        staticmethod(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("skipped plan must not mutate HDF settings")
            )
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        skip_existing=True,
        use_optimal_hdf_settings=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert hdf.read_bytes() == b"existing hdf"
    assert sidecar.read_text(encoding="ascii") == "existing message\n"
    assert plan_path.read_bytes() == original_plan_bytes


def test_compute_callback_failure_before_launch_preserves_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "callback-failure", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    sidecar = ras_obj.project_folder / "Model.p01.computeMsgs.txt"
    legacy.write_bytes(b"existing legacy")
    sidecar.write_text("existing message\n", encoding="ascii")
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    class FailingCallback:
        def on_exec_start(self, *_args):
            raise RuntimeError("callback setup failed")

    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("process launch must not be attempted")
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
        stream_callback=FailingCallback(),
    )

    assert result.success is False
    assert legacy.read_bytes() == b"existing legacy"
    assert sidecar.read_text(encoding="ascii") == "existing message\n"


def test_compute_callback_monitor_failure_stops_child_before_final_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "callback-monitor-failure", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    _patch_compute_scaffolding(monkeypatch, ras_obj)
    terminated = []

    class FakeProcess:
        pid = 1234
        active = True

        def poll(self):
            return None if self.active else -1

    process = FakeProcess()

    class FailingMonitor:
        @staticmethod
        def enable_detailed_logging(*_args, **_kwargs):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            legacy.write_bytes(b"recreated by active solver")
            raise RuntimeError("monitor failed after launch")

    def terminate_tree(started_process):
        assert started_process is process
        assert legacy.exists()
        started_process.active = False
        terminated.append(True)

    monkeypatch.setattr(rascmdr_module, "BcoMonitor", FailingMonitor)
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        RasCmdr,
        "_terminate_launched_process_tree",
        staticmethod(terminate_tree),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
        stream_callback=object(),
    )

    assert result.success is False
    assert terminated == [True]
    assert not legacy.exists()


def test_compute_callback_unconfirmed_termination_skips_final_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "callback-unconfirmed", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    _patch_compute_scaffolding(monkeypatch, ras_obj)

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

    class FailingMonitor:
        @staticmethod
        def enable_detailed_logging(*_args, **_kwargs):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            legacy.write_bytes(b"possibly still being written")
            raise RuntimeError("monitor failed")

    monkeypatch.setattr(rascmdr_module, "BcoMonitor", FailingMonitor)
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_terminate_launched_process_tree",
        staticmethod(
            lambda _process: (_ for _ in ()).throw(
                RuntimeError("child termination unconfirmed")
            )
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
        stream_callback=object(),
    )

    assert result.success is False
    assert legacy.read_bytes() == b"possibly still being written"


def test_compute_unknown_solver_state_skips_final_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "unknown-solver-state", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    _patch_compute_scaffolding(monkeypatch, ras_obj)
    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda *_args, **_kwargs: ras_obj.project_folder / "Model.p01"),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_confirm_plan_solver_quiescence",
        staticmethod(lambda *_args, **_kwargs: False),
    )

    def fake_run(*_args, **_kwargs):
        hdf.write_bytes(b"new hdf")
        legacy.write_bytes(b"possibly active writer")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is False
    assert legacy.read_bytes() == b"possibly active writer"


def test_compute_skip_existing_reruns_ambiguous_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "skip-ambiguous", "6.60")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"existing hdf")
    legacy.write_bytes(b"ambiguous legacy")
    _patch_compute_scaffolding(monkeypatch, ras_obj)
    monkeypatch.setattr(
        RasCmdr,
        "_verify_completion",
        staticmethod(lambda *_args, **_kwargs: True),
    )
    called = []

    def fake_run(*_args, **_kwargs):
        called.append(True)
        assert not legacy.exists()
        hdf.write_bytes(b"new hdf")
        legacy.write_bytes(b"recreated")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rascmdr_module.subprocess, "run", fake_run)

    result = RasCmdr.compute_plan(
        "01",
        skip_existing=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert called == [True]
    assert hdf.read_bytes() == b"new hdf"
    assert not legacy.exists()


def test_currency_raises_for_modern_newer_legacy_output(tmp_path: Path) -> None:
    ras_obj = _write_project(tmp_path / "currency", "6.60")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")
    legacy_stat = legacy.stat()
    os.utime(
        legacy,
        ns=(legacy_stat.st_atime_ns, hdf.stat().st_mtime_ns + 1_000_000_000),
    )

    with pytest.raises(ResultArtifactAmbiguityError) as caught:
        RasCurrency.are_plan_results_current(
            "01",
            ras_obj,
            check_complete=False,
        )

    assert caught.value.reason_code == "legacy_output_timestamp_after_hdf"


def test_currency_modern_multiple_formats_selects_newer_hdf(
    tmp_path: Path,
) -> None:
    ras_obj = _write_project(tmp_path / "currency-modern-hdf", "6.60")
    legacy = ras_obj.project_folder / "Model.O01"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy.write_bytes(b"legacy")
    hdf.write_bytes(b"hdf")
    legacy_stat = legacy.stat()
    hdf_stat = hdf.stat()
    os.utime(
        hdf,
        ns=(hdf_stat.st_atime_ns, legacy_stat.st_mtime_ns + 1_000_000_000),
    )

    is_current, reason = RasCurrency.are_plan_results_current(
        "01",
        ras_obj,
        check_complete=False,
    )

    assert is_current is True
    assert "hdf results are current" in reason


def test_currency_legacy_multiple_formats_selects_older_or_equal_hdf(
    tmp_path: Path,
) -> None:
    ras_obj = _write_project(tmp_path / "currency-legacy", "4.00")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")
    legacy_stat = legacy.stat()
    os.utime(hdf, ns=(legacy_stat.st_atime_ns, legacy_stat.st_mtime_ns))

    is_current, reason = RasCurrency.are_plan_results_current(
        "01",
        ras_obj,
        check_complete=False,
    )

    assert is_current is True
    assert "legacy results are current" in reason


def test_cleanup_preflights_every_target_before_deleting(tmp_path: Path) -> None:
    ras_obj = _write_project(tmp_path / "cleanup-preflight", "6.60")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy_directory = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"keep")
    legacy_directory.mkdir()

    with pytest.raises(IsADirectoryError):
        RasCmdr.remove_plan_execution_artifacts(
            "01",
            result_format="both",
            ras_object=ras_obj,
        )

    assert hdf.read_bytes() == b"keep"


def test_cleanup_reports_partial_removal_if_unlink_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ras_obj = _write_project(tmp_path / "cleanup-partial", "6.60")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")
    real_unlink = Path.unlink

    def guarded_unlink(path: Path, *args, **kwargs):
        if path == legacy:
            raise PermissionError("locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    with pytest.raises(PlanExecutionCleanupError) as caught:
        RasCmdr.remove_plan_execution_artifacts(
            "01",
            result_format="both",
            ras_object=ras_obj,
        )

    assert caught.value.cleanup.removed_paths == (hdf,)
    assert caught.value.failed_path == legacy
    assert not hdf.exists()
    assert legacy.is_file()


def test_compute_plan_unresolved_engine_preserves_both_result_families(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ras_obj = _write_project(tmp_path / "unresolved-engine", "6.60")
    ras_obj.ras_version = None
    ras_obj.ras_exe_path = ras_obj.project_folder / "Ras.exe"
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("HEC-RAS must not be launched"),
    )

    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras_obj,
        force_rerun=True,
        dialog_watchdog=False,
    )

    assert result.success is False
    assert hdf.read_bytes() == b"hdf"
    assert legacy.read_bytes() == b"legacy"


def test_docker_staging_clears_final_results_but_preserves_tmp_hdf(
    tmp_path: Path,
) -> None:
    ras_obj = _write_project(tmp_path / "docker-source", "6.60")
    staging = tmp_path / "docker-staging"
    staging.mkdir()
    for source in ras_obj.project_folder.iterdir():
        if source.is_file():
            (staging / source.name).write_bytes(source.read_bytes())
    final_hdf = staging / "Model.p01.hdf"
    tmp_hdf = staging / "Model.p01.tmp.hdf"
    legacy = staging / "Model.O01"
    message = staging / "Model.p01.computeMsgs.txt"
    final_hdf.write_bytes(b"stale final")
    tmp_hdf.write_bytes(b"required preprocessing")
    legacy.write_bytes(b"stale legacy")
    message.write_bytes(b"stale messages")

    removed = clear_staged_plan_execution_artifacts(
        staging,
        "01",
        ras_obj,
    )

    assert set(removed) == {final_hdf, legacy, message}
    assert tmp_hdf.read_bytes() == b"required preprocessing"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (None, False),
        ("Did not Complete Process\n", False),
        ("Complete Process\t1.25 sec\n", True),
    ],
)
def test_legacy_verification_requires_exact_completion_record(
    tmp_path: Path,
    message: str | None,
    expected: bool,
) -> None:
    ras_obj = _write_project(tmp_path / f"legacy-verify-{expected}", "4.00")
    (ras_obj.project_folder / "Model.O01").write_bytes(b"legacy result")
    if message is not None:
        (ras_obj.project_folder / "Model.p01.comp_msgs.txt").write_text(
            message,
            encoding="ascii",
        )

    assert RasCmdr._verify_legacy_result(
        "01",
        ras_obj,
        check_errors=True,
    ) is expected


def test_rascontrol_current_but_ambiguous_plan_reruns_and_normalizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-skip", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")
    calls = []

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def PlanOutput_IsCurrent(self):
            calls.append("current")
            return True

        def Compute_CurrentPlan(self, *_args):
            calls.append("compute")
            assert not legacy.exists()
            hdf.write_bytes(b"new hdf")
            legacy.write_bytes(b"recreated")
            return True, 0, ["Complete Process"], 0

        def Compute_Complete(self):
            return True

    controller = Controller()
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(controller)),
    )

    result = RasControl.run_plan(
        "01",
        ras_object=ras_obj,
        use_watchdog=False,
        refresh_results=False,
    )

    assert result.success is True
    assert calls == ["current", "compute"]
    assert hdf.read_bytes() == b"new hdf"
    assert not legacy.exists()


def test_rascontrol_current_single_result_skip_preserves_plan_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-read-only-skip", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    plan_path = ras_obj.project_folder / "Model.p01"
    original_plan_bytes = plan_path.read_bytes()
    (ras_obj.project_folder / "Model.p01.hdf").write_bytes(b"hdf")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def PlanOutput_IsCurrent(self):
            return True

    controller = Controller()
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("skip must not alter detailed logging settings")
            )
        ),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(controller)),
    )

    result = RasControl.run_plan(
        "01",
        ras_object=ras_obj,
        use_watchdog=False,
        refresh_results=False,
    )

    assert result.success is True
    assert result.execution_details["execution_api"] == "ras_control"
    assert result.execution_details["engine_kind"] == "controller"
    assert result.execution_details["selected_result_format"] == "hdf"
    assert result.execution_details["calculation_attempted"] is False
    assert result.execution_details["solver_quiescence_confirmed"] is None
    assert result.execution_details["result_artifacts_finalized"] is False
    assert result.execution_details["actual_engine_provenance_confirmed"] is False
    assert result.execution_details["controller_close_safe"] is False
    assert result.execution_details["owned_process_exit_confirmed"] is False
    assert plan_path.read_bytes() == original_plan_bytes


@pytest.mark.parametrize("strict_close", [False, True])
def test_rascontrol_current_check_surviving_process_is_not_a_successful_skip(
    tmp_path: Path,
    monkeypatch,
    strict_close: bool,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / f"control-skip-survivor-{strict_close}", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    plan_path = ras_obj.project_folder / "Model.p01"
    original_plan_bytes = plan_path.read_bytes()
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    hdf.write_bytes(b"current hdf")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def PlanOutput_IsCurrent(self):
            return True

    def unsafe_open_close(
        _path,
        _version,
        operation,
        *,
        close_outcome_callback=None,
        require_safe_close=False,
        **_kwargs,
    ):
        result = operation(Controller())
        if close_outcome_callback is not None:
            close_outcome_callback(
                False,
                SimpleNamespace(process_survived=True, ras_pid=4321),
                None,
            )
        if require_safe_close:
            raise RuntimeError("owned ras.exe PID 4321 survived cleanup")
        return result

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "unsafe currency close must not proceed to computation"
            )
        ),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(unsafe_open_close),
    )

    with pytest.raises(RuntimeError, match="computation was not started"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            use_watchdog=False,
            refresh_results=False,
            strict_close=strict_close,
        )

    assert plan_path.read_bytes() == original_plan_bytes
    assert hdf.read_bytes() == b"current hdf"


def test_rascontrol_com_activation_failure_preserves_both_result_families(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-activation-failure", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"hdf")
    legacy.write_bytes(b"legacy")

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("COM activation failed")
            )
        ),
    )

    with pytest.raises(RuntimeError, match="COM activation failed"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"hdf"
    assert legacy.read_bytes() == b"legacy"


def test_rascontrol_compute_complete_failure_preserves_recreated_opposing_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-completion-unknown", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            assert not legacy.exists()
            hdf.write_bytes(b"possibly incomplete hdf")
            legacy.write_bytes(b"possibly active legacy writer")
            return True, 0, ["Computing"], 0

        def Compute_Complete(self):
            raise OSError("completion status unavailable")

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(Controller())),
    )

    with pytest.raises(RuntimeError, match="Could not confirm HEC-RAS solver quiescence"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"possibly incomplete hdf"
    assert legacy.read_bytes() == b"possibly active legacy writer"


def test_rascontrol_compute_failure_preserves_recreated_opposing_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-compute-failure", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            assert not legacy.exists()
            hdf.write_bytes(b"partial hdf")
            legacy.write_bytes(b"possibly active legacy writer")
            raise OSError("compute dispatch failed")

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(Controller())),
    )

    with pytest.raises(OSError, match="compute dispatch failed"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"partial hdf"
    assert legacy.read_bytes() == b"possibly active legacy writer"


@pytest.mark.parametrize("strict_close", [False, True])
def test_rascontrol_surviving_owned_process_preserves_opposing_output(
    tmp_path: Path,
    monkeypatch,
    strict_close: bool,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / f"control-survivor-{strict_close}", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            assert not legacy.exists()
            hdf.write_bytes(b"complete hdf")
            legacy.write_bytes(b"owned process may still write")
            return True, 0, ["Complete Process"], 0

        def Compute_Complete(self):
            return True

    def unsafe_open_close(
        _path,
        _version,
        operation,
        *,
        close_outcome_callback=None,
        require_safe_close=False,
        **_kwargs,
    ):
        result = operation(Controller())
        if close_outcome_callback is not None:
            close_outcome_callback(
                False,
                SimpleNamespace(process_survived=True, ras_pid=4321),
                None,
            )
        if require_safe_close:
            raise RuntimeError("owned ras.exe PID 4321 survived cleanup")
        return result

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(unsafe_open_close),
    )

    with pytest.raises(RuntimeError, match="owned ras.exe PID 4321 survived"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
            strict_close=strict_close,
        )

    assert hdf.read_bytes() == b"complete hdf"
    assert legacy.read_bytes() == b"owned process may still write"


@pytest.mark.parametrize("use_watchdog", [False, True])
def test_rascontrol_nonblocking_deadline_preserves_opposing_output(
    tmp_path: Path,
    monkeypatch,
    use_watchdog: bool,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / f"control-timeout-{use_watchdog}", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            assert not legacy.exists()
            hdf.write_bytes(b"partial hdf")
            legacy.write_bytes(b"possibly active writer")
            return True, 0, ["Computing"], 0

        def Compute_Complete(self):
            return False

    monotonic_values = iter([100.0, 101.0])
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(Controller())),
    )
    monkeypatch.setattr(
        importlib.import_module("ras_commander.RasControl").time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(TimeoutError, match="exceeded max_runtime"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=use_watchdog,
            max_runtime=0.5,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"partial hdf"
    assert legacy.read_bytes() == b"possibly active writer"


def test_rascontrol_nonblocking_deadline_rejects_late_complete_poll(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-late-complete", "6.60")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            assert not legacy.exists()
            hdf.write_bytes(b"late hdf")
            legacy.write_bytes(b"late legacy")
            return True, 0, ["Complete Process"], 0

        def Compute_Complete(self):
            return True

    # Compute starts at 100.0 and enters its first poll at 100.1, but the COM
    # poll only returns after the 100.5 deadline. A late True is not proof that
    # the solver completed within the permitted runtime.
    monotonic_values = iter([100.0, 100.1, 101.0])
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(Controller())),
    )
    monkeypatch.setattr(
        importlib.import_module("ras_commander.RasControl").time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(TimeoutError, match="exceeded max_runtime"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            max_runtime=0.5,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"late hdf"
    assert legacy.read_bytes() == b"late legacy"


def test_rascontrol_modern_run_normalizes_recreated_legacy_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / "control-run", "6.6")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"old hdf")
    legacy.write_bytes(b"old legacy")
    calls = []

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def PlanOutput_IsCurrent(self):
            calls.append("current")
            return False

        def Compute_CurrentPlan(self, *_args):
            calls.append("compute")
            assert not legacy.exists()
            hdf.write_bytes(b"new hdf")
            legacy.write_bytes(b"recreated")
            return True, 0, ["Complete Process"], 0

        def Compute_Complete(self):
            return True

    controller = Controller()
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(controller)),
    )

    result = RasControl.run_plan(
        "01",
        ras_object=ras_obj,
        use_watchdog=False,
        refresh_results=False,
    )

    assert result.success is True
    assert calls == ["current", "compute"]
    assert hdf.read_bytes() == b"new hdf"
    assert not legacy.exists()


@pytest.mark.parametrize(
    ("plan_complete", "host_complete", "plan_matched", "host_processes", "message"),
    [
        (False, True, (), (), "inventory was incomplete"),
        (
            True,
            True,
            (SimpleNamespace(pid=7001),),
            (SimpleNamespace(pid=7001),),
            "compute process remained",
        ),
    ],
)
def test_rascontrol_post_close_process_gate_preserves_opposing_output(
    tmp_path: Path,
    monkeypatch,
    plan_complete,
    host_complete,
    plan_matched,
    host_processes,
    message,
) -> None:
    from ras_commander.RasBco import BcoMonitor

    ras_obj = _write_project(tmp_path / f"post-close-{plan_complete}", "6.6")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    legacy.write_bytes(b"stale legacy")

    class Controller:
        def Plan_SetCurrent(self, _name):
            return None

        def Compute_CurrentPlan(self, *_args):
            hdf.write_bytes(b"complete hdf")
            legacy.write_bytes(b"post-close writer evidence")
            return True, 0, ["Complete Process"], 0

        def Compute_Complete(self):
            return True

    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_fake_safe_com_open_close(Controller())),
    )
    rascontrol_module = importlib.import_module("ras_commander.RasControl")
    inventories = iter(
        [
            (
                SimpleNamespace(complete=True, matched=()),
                SimpleNamespace(
                    complete=True,
                    processes=(),
                    query_errors=(),
                ),
            ),
            (
                SimpleNamespace(complete=plan_complete, matched=plan_matched),
                SimpleNamespace(
                    complete=host_complete,
                    processes=host_processes,
                    query_errors=(),
                ),
            ),
        ]
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_inspect_controller_post_close_processes",
        lambda **_kwargs: next(inventories),
    )

    with pytest.raises(RuntimeError, match=message):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"complete hdf"
    assert legacy.read_bytes() == b"post-close writer evidence"


def test_rascontrol_pre_run_exact_process_gate_precedes_artifact_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ras_obj = _write_project(tmp_path / "control-pre-run-active", "6.6")
    ras_obj.plan_df["Plan Title"] = ["Base"]
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"existing hdf")
    legacy.write_bytes(b"existing legacy")
    rascontrol_module = importlib.import_module("ras_commander.RasControl")
    monkeypatch.setattr(
        rascontrol_module,
        "_inspect_controller_post_close_processes",
        lambda **_kwargs: (
            SimpleNamespace(
                complete=True,
                matched=(SimpleNamespace(pid=7001),),
            ),
            SimpleNamespace(
                complete=True,
                processes=(),
                query_errors=(),
            ),
        ),
    )
    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "Controller activation must follow the pre-run process gate"
            )
        ),
    )

    with pytest.raises(RuntimeError, match="already active before Controller"):
        RasControl.run_plan(
            "01",
            ras_object=ras_obj,
            force_recompute=True,
            use_watchdog=False,
            refresh_results=False,
        )

    assert hdf.read_bytes() == b"existing hdf"
    assert legacy.read_bytes() == b"existing legacy"


def test_rascmdr_pre_run_exact_process_gate_precedes_artifact_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    ras_obj = _write_project(tmp_path / "cmdr-pre-run-active", "6.6")
    hdf = ras_obj.project_folder / "Model.p01.hdf"
    legacy = ras_obj.project_folder / "Model.O01"
    hdf.write_bytes(b"existing hdf")
    legacy.write_bytes(b"existing legacy")
    _patch_compute_scaffolding(monkeypatch, ras_obj)
    monkeypatch.setattr(
        RasCmdr,
        "inspect_plan_processes",
        staticmethod(
            lambda *_args, **_kwargs: SimpleNamespace(
                complete=True,
                matched=(SimpleNamespace(pid=7001),),
            )
        ),
    )
    monkeypatch.setattr(
        rascmdr_module,
        "prepare_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact cleanup must follow the pre-run process gate"
        ),
    )

    result = RasCmdr.compute_plan(
        "01",
        force_rerun=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is False
    assert hdf.read_bytes() == b"existing hdf"
    assert legacy.read_bytes() == b"existing legacy"
