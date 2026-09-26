"""Regression tests for solver-ready gridded precipitation preprocessing."""

import importlib
import subprocess
from pathlib import Path

import h5py
import pandas as pd

raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")
RasPreprocess = raspreprocess_module.RasPreprocess


class _FakeRas:
    def __init__(self, project_folder: Path):
        self.project_folder = project_folder
        self.project_name = "fixture"
        self.ras_exe_path = project_folder / "Ras.exe"
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Geom File": "g03"}]
        )

    def check_initialized(self):
        return None


class _RunningProcess:
    pid = 12345
    returncode = None

    def poll(self):
        return self.returncode


class _ExitedProcess(_RunningProcess):
    returncode = 0


def _seed_project(tmp_path: Path, *, gridded: bool = True) -> _FakeRas:
    project = _FakeRas(tmp_path)
    project.ras_exe_path.write_bytes(b"fixture executable")
    (tmp_path / "fixture.prj").write_text(
        "Proj Title=fixture\n",
        encoding="utf-8",
    )
    (tmp_path / "fixture.p01").write_text(
        "Plan Title=fixture\nGeom File=g03\nFlow File=u02\n",
        encoding="utf-8",
    )
    mode = "Gridded" if gridded else "None"
    enabled = "Enable" if gridded else "Disable"
    (tmp_path / "fixture.u02").write_text(
        f"Precipitation Mode={enabled}\n"
        f"Met BC=Precipitation|Mode={mode}\n",
        encoding="utf-8",
    )
    return project


def _write_artifacts(folder: Path, *, materialized: bool) -> None:
    tmp_hdf = folder / "fixture.p01.tmp.hdf"
    with h5py.File(tmp_hdf, "w") as hdf:
        imported = hdf.require_group(
            "Event Conditions/Meteorology/Precipitation/Imported Raster Data"
        )
        imported.create_dataset("Values", data=[[0.0, 1.0]])
        if materialized:
            precipitation = hdf["Event Conditions/Meteorology/Precipitation"]
            precipitation.create_dataset("Values", data=[[0.0, 1.0]])
            precipitation.create_dataset("Timestamp", data=[0.0])
    (folder / "fixture.b01").write_bytes(b"ready")
    (folder / "fixture.x03").write_bytes(b"ready")


def _patch_launch(monkeypatch, monitor, process, terminated):
    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", monitor)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        RasPreprocess,
        "_tcu_supervision_availability_error",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_process_tree",
        staticmethod(lambda child: terminated.append(child)),
    )


def test_plan_uses_gridded_precipitation_reads_active_unsteady_text(tmp_path):
    ras = _seed_project(tmp_path, gridded=True)
    assert RasPreprocess._plan_uses_gridded_precipitation(
        tmp_path / "fixture.p01",
        tmp_path,
        ras.project_name,
    )

    (tmp_path / "fixture.u02").write_text(
        "Precipitation Mode=Disable\n"
        "Met BC=Precipitation|Mode=Gridded\n",
        encoding="utf-8",
    )
    assert not RasPreprocess._plan_uses_gridded_precipitation(
        tmp_path / "fixture.p01",
        tmp_path,
        ras.project_name,
    )


def test_materialized_precipitation_requires_shallow_values_and_timestamp(tmp_path):
    _write_artifacts(tmp_path, materialized=False)
    ready, detail = RasPreprocess._validate_materialized_gridded_precipitation(
        tmp_path / "fixture.p01.tmp.hdf"
    )
    assert ready is False
    assert "Precipitation/Values" in detail
    assert "Precipitation/Timestamp" in detail

    _write_artifacts(tmp_path, materialized=True)
    ready, detail = RasPreprocess._validate_materialized_gridded_precipitation(
        tmp_path / "fixture.p01.tmp.hdf"
    )
    assert ready is True
    assert detail == "ready"


def test_preprocessing_readiness_waits_for_materialized_precipitation(
    tmp_path,
    monkeypatch,
):
    _write_artifacts(tmp_path, materialized=False)
    monkeypatch.setattr(
        RasPreprocess,
        "_unsteady_compute_started",
        staticmethod(lambda *_args, **_kwargs: True),
    )

    kwargs = {
        "root_pid": 12345,
        "tmp_hdf": tmp_path / "fixture.p01.tmp.hdf",
        "b_file": tmp_path / "fixture.b01",
        "x_file": tmp_path / "fixture.x03",
    }
    assert RasPreprocess._preprocessing_ready(
        **kwargs,
        require_materialized_gridded_precipitation=False,
    )
    assert not RasPreprocess._preprocessing_ready(
        **kwargs,
        require_materialized_gridded_precipitation=True,
    )

    _write_artifacts(tmp_path, materialized=True)
    assert RasPreprocess._preprocessing_ready(
        **kwargs,
        require_materialized_gridded_precipitation=True,
    )


def test_bco_readiness_does_not_require_short_lived_solver_process(tmp_path):
    _write_artifacts(tmp_path, materialized=True)
    assert RasPreprocess._materialized_gridded_precipitation_ready(
        tmp_path / "fixture.p01.tmp.hdf",
        tmp_path / "fixture.b01",
        tmp_path / "fixture.x03",
        artifact_baseline={
            tmp_path / "fixture.p01.tmp.hdf": None,
            tmp_path / "fixture.b01": None,
            tmp_path / "fixture.x03": None,
        },
    )


def test_alternate_signal_accepts_fresh_materialized_precipitation(
    tmp_path,
    monkeypatch,
):
    ras = _seed_project(tmp_path, gridded=True)
    process = _RunningProcess()
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = None

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **kwargs):
            self.alternate_signal_condition = kwargs[
                "alternate_signal_condition"
            ]

        def monitor_until_signal(self, _process):
            _write_artifacts(tmp_path, materialized=True)
            detected = self.alternate_signal_condition()
            assert detected is True
            self.signal_source = "alternate"
            return detected

    _patch_launch(monkeypatch, Monitor, process, terminated)

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras,
        max_wait=2,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is True
    assert result.signal_source == "materialized_gridded_precipitation"
    assert terminated == [process]


def test_bco_signal_waits_for_materialized_precipitation_before_termination(
    tmp_path,
    monkeypatch,
):
    ras = _seed_project(tmp_path, gridded=True)
    process = _RunningProcess()
    terminated = []
    readiness_checks = []

    class Monitor:
        blocked_reason = None
        signal_source = "bco"

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            _write_artifacts(tmp_path, materialized=True)
            return True

    def ready(*_args, **_kwargs):
        readiness_checks.append(True)
        return True

    _patch_launch(monkeypatch, Monitor, process, terminated)
    monkeypatch.setattr(
        RasPreprocess,
        "_materialized_gridded_precipitation_ready",
        staticmethod(ready),
    )

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras,
        max_wait=2,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is True
    assert result.signal_source == "bco_materialized_precipitation"
    assert readiness_checks == [True]
    assert terminated == [process]


def test_preprocess_rejects_imported_only_precipitation_payload(
    tmp_path,
    monkeypatch,
):
    ras = _seed_project(tmp_path, gridded=True)
    process = _RunningProcess()
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = "alternate"

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            _write_artifacts(tmp_path, materialized=False)
            return True

    _patch_launch(monkeypatch, Monitor, process, terminated)

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras,
        max_wait=2,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is False
    assert result.signal_source == "materialized_gridded_precipitation"
    assert result.tmp_hdf_path == tmp_path / "fixture.p01.tmp.hdf"
    assert "Imported Raster Data alone is not solver-ready" in result.error
    assert "Precipitation/Values" in result.error
    assert terminated == [process]


def test_naturally_exited_launcher_still_cleans_exact_plan_residue(
    tmp_path,
    monkeypatch,
):
    ras = _seed_project(tmp_path, gridded=True)
    process = _ExitedProcess()
    terminated = []
    cleanup_calls = []

    class Monitor:
        blocked_reason = None
        signal_source = "alternate"

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            _write_artifacts(tmp_path, materialized=True)
            return True

    _patch_launch(monkeypatch, Monitor, process, terminated)

    def cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return (30220,), ()

    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_exact_preprocess_residue",
        staticmethod(cleanup),
    )

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras,
        max_wait=2,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is True
    assert terminated == []
    assert len(cleanup_calls) == 1
    assert cleanup_calls[0]["project_file"] == tmp_path / "fixture.prj"
    assert cleanup_calls[0]["plan_file"] == tmp_path / "fixture.p01"
    assert cleanup_calls[0]["tmp_hdf"] == tmp_path / "fixture.p01.tmp.hdf"


def test_preprocess_fails_when_exact_plan_residue_survives_cleanup(
    tmp_path,
    monkeypatch,
):
    ras = _seed_project(tmp_path, gridded=True)
    process = _ExitedProcess()
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = "alternate"

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            _write_artifacts(tmp_path, materialized=True)
            return True

    _patch_launch(monkeypatch, Monitor, process, terminated)
    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_exact_preprocess_residue",
        staticmethod(lambda **_kwargs: ((), (30220,))),
    )

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras,
        max_wait=2,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is False
    assert "remained active after cleanup: 30220" in result.error
