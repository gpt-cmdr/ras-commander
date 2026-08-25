"""Regression tests for version-aware execution-artifact cleanup."""

from __future__ import annotations

import importlib
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
from ras_commander.ExecutionArtifacts import PlanExecutionCleanupError
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

    result = RasCmdr.compute_plan(
        "01",
        skip_existing=True,
        ras_object=ras_obj,
        dialog_watchdog=False,
    )

    assert result.success is True
    assert hdf.read_bytes() == b"existing hdf"
    assert sidecar.read_text(encoding="ascii") == "existing message\n"


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


def test_currency_raises_for_modern_multiple_result_formats(tmp_path: Path) -> None:
    ras_obj = _write_project(tmp_path / "currency", "6.60")
    (ras_obj.project_folder / "Model.p01.hdf").write_bytes(b"hdf")
    (ras_obj.project_folder / "Model.O01").write_bytes(b"legacy")

    with pytest.raises(ResultArtifactAmbiguityError) as caught:
        RasCurrency.are_plan_results_current(
            "01",
            ras_obj,
            check_complete=False,
        )

    assert caught.value.reason_code == "multiple_result_formats_modern_plan"


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
        staticmethod(lambda _path, _version, operation: operation(controller)),
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
        staticmethod(lambda _path, _version, operation: operation(controller)),
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
