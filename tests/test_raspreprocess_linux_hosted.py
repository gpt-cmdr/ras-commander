"""Focused contracts for Linux-hosted unsteady plan preparation."""

import importlib
import subprocess
import sys
from pathlib import Path

import h5py
import pandas as pd

from ras_commander.RasPreprocess import RasPreprocess


raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")


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


def _seed_project(tmp_path: Path) -> _FakeRas:
    project = _FakeRas(tmp_path)
    project.ras_exe_path.write_bytes(b"fixture executable")
    (tmp_path / "fixture.prj").write_text(
        "Proj Title=fixture\n",
        encoding="utf-8",
    )
    (tmp_path / "fixture.p01").write_text(
        "Plan Title=fixture\nGeom File=g03\n",
        encoding="utf-8",
    )
    return project


def _write_preprocess_outputs(folder: Path):
    (folder / "fixture.p01.tmp.hdf").write_bytes(b"ready")
    (folder / "fixture.b01").write_bytes(b"ready")
    (folder / "fixture.x03").write_bytes(b"ready")


def test_preprocess_uses_owned_launcher_and_records_alternate_signal(
    tmp_path,
    monkeypatch,
):
    ras_obj = _seed_project(tmp_path)
    process = _RunningProcess()
    launched = {}
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = "alternate"

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **kwargs):
            launched["monitor"] = kwargs

        def monitor_until_signal(self, _process):
            _write_preprocess_outputs(tmp_path)
            return True

    def popen(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        return process

    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", Monitor)
    monkeypatch.setattr(subprocess, "Popen", popen)
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

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras_obj,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result
    assert result.signal_source == "owned_process_artifacts"
    assert result.full_result_copied is False
    assert terminated == [process]
    assert launched["command"] == [
        sys.executable,
        "-c",
        "import subprocess,sys; "
        "raise SystemExit(subprocess.call(sys.argv[1:], shell=False))",
        str(ras_obj.ras_exe_path),
        "-c",
        str(tmp_path / "fixture.prj"),
        str(tmp_path / "fixture.p01"),
    ]
    assert launched["kwargs"]["shell"] is False
    assert callable(launched["monitor"]["alternate_signal_condition"])
    assert callable(launched["monitor"]["blocking_condition"])


def test_preprocess_timeout_terminates_owned_tree_and_fails_closed(
    tmp_path,
    monkeypatch,
):
    ras_obj = _seed_project(tmp_path)
    process = _RunningProcess()
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = None

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            return False

    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", Monitor)
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

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras_obj,
        max_wait=2,
        clear_existing=False,
    )

    assert not result
    assert result.signal_source == "timeout"
    assert result.timed_out is True
    assert "timed out after 2 seconds" in result.error
    assert terminated == [process]


def test_unsteady_signal_requires_owned_process_and_all_artifacts(
    tmp_path,
    monkeypatch,
):
    artifacts = [
        tmp_path / "fixture.p01.tmp.hdf",
        tmp_path / "fixture.b01",
        tmp_path / "fixture.x03",
    ]
    for path in artifacts:
        path.write_bytes(b"ready")

    class Child:
        def name(self):
            return "RasUnsteady.exe"

        def cmdline(self):
            return [r"C:\HEC-RAS\x64\RasUnsteady.exe"]

    class Root:
        def children(self, recursive):
            assert recursive is True
            return [Child()]

    import psutil

    monkeypatch.setattr(psutil, "Process", lambda _pid: Root())

    assert RasPreprocess._unsteady_compute_started(12345, *artifacts)
    artifacts[-1].write_bytes(b"")
    assert not RasPreprocess._unsteady_compute_started(12345, *artifacts)


def test_unsteady_signal_rejects_unrelated_descendant(tmp_path, monkeypatch):
    artifacts = [
        tmp_path / "fixture.p01.tmp.hdf",
        tmp_path / "fixture.b01",
        tmp_path / "fixture.x03",
    ]
    for path in artifacts:
        path.write_bytes(b"ready")

    class Child:
        def name(self):
            return "Ras.exe"

        def cmdline(self):
            return [r"C:\HEC-RAS\Ras.exe"]

    class Root:
        def children(self, recursive):
            return [Child()]

    import psutil

    monkeypatch.setattr(psutil, "Process", lambda _pid: Root())
    assert not RasPreprocess._unsteady_compute_started(12345, *artifacts)


def test_unsteady_signal_rejects_stale_preexisting_artifacts(
    tmp_path,
    monkeypatch,
):
    artifacts = [
        tmp_path / "fixture.p01.tmp.hdf",
        tmp_path / "fixture.b01",
        tmp_path / "fixture.x03",
    ]
    for path in artifacts:
        path.write_bytes(b"ready")
    baseline = {
        path: RasPreprocess._artifact_state(path)
        for path in artifacts
    }

    class Child:
        def name(self):
            return "RasUnsteady.exe"

        def cmdline(self):
            return [r"C:\HEC-RAS\x64\RasUnsteady.exe"]

    class Root:
        def children(self, recursive):
            return [Child()]

    import psutil

    monkeypatch.setattr(psutil, "Process", lambda _pid: Root())

    assert not RasPreprocess._unsteady_compute_started(
        12345,
        *artifacts,
        artifact_baseline=baseline,
    )
    artifacts[0].write_bytes(b"new preparation")
    assert not RasPreprocess._unsteady_compute_started(
        12345,
        *artifacts,
        artifact_baseline=baseline,
    )
    artifacts[1].write_bytes(b"new preparation")
    artifacts[2].write_bytes(b"new preparation")
    assert RasPreprocess._unsteady_compute_started(
        12345,
        *artifacts,
        artifact_baseline=baseline,
    )


def _standalone_geometry_fixture(tmp_path: Path):
    ras_obj = _seed_project(tmp_path)
    executable = tmp_path / "x64" / "RasGeomPreprocess.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"geometry preprocessor")
    input_hdf = tmp_path / "fixture.p01.tmp.hdf"
    with h5py.File(input_hdf, "w") as handle:
        handle.create_group("Geometry")
    x_file = tmp_path / "fixture.x03"
    x_file.write_bytes(b"execution data")
    return ras_obj, executable, input_hdf, x_file


def test_run_ras_geom_preprocess_uses_argument_vector_and_fingerprints(
    tmp_path,
    monkeypatch,
):
    ras_obj, executable, input_hdf, _x_file = _standalone_geometry_fixture(
        tmp_path
    )
    observed = {}

    class Process:
        returncode = 0

        def communicate(self, timeout):
            observed["timeout"] = timeout
            with h5py.File(input_hdf, "a") as handle:
                handle["Geometry"].create_dataset("Product Marker", data=[1])
            return "Errors: 0\nFinished Processing Geometry", ""

    def popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(subprocess, "Popen", popen)

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
        timeout_sec=45,
        require_hdf_change=True,
    )

    assert result
    assert result.executable_path == executable
    assert result.executable_sha256 == RasPreprocess._file_sha256(executable)
    assert result.output_changed is True
    assert result.hdf_readable is True
    assert result.geometry_group_present is True
    assert result.error_count == 0
    assert observed["command"] == [str(executable), str(input_hdf), "x03"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"]["cwd"] == str(tmp_path)
    assert observed["timeout"] == 45


def test_run_ras_geom_preprocess_timeout_terminates_and_fails_closed(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = (
        _standalone_geometry_fixture(tmp_path)
    )
    terminated = []

    class Process:
        returncode = None
        calls = 0

        def communicate(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("RasGeomPreprocess", timeout)
            return "", ""

    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)

    def terminate(child):
        terminated.append(child)
        child.returncode = -9

    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_process_tree",
        staticmethod(terminate),
    )

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
        timeout_sec=2,
        require_hdf_change=True,
    )

    assert not result
    assert result.timed_out is True
    assert result.return_code == -9
    assert terminated == [process]
    assert "timed out after 2 seconds" in result.error
    assert "did not change" in result.error


def test_run_ras_geom_preprocess_rejects_corrupt_hdf(tmp_path, monkeypatch):
    ras_obj, _executable, input_hdf, _x_file = _standalone_geometry_fixture(
        tmp_path
    )

    class Process:
        returncode = 0

        def communicate(self, timeout):
            input_hdf.write_bytes(b"not an HDF5 file")
            return "Finished Processing Geometry", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
        require_hdf_change=True,
    )

    assert not result
    assert result.output_changed is True
    assert result.hdf_readable is False
    assert "output HDF is unreadable" in result.error


def test_tcu_detector_is_scoped_and_never_automates_assent(monkeypatch):
    observed = []
    monkeypatch.setattr(
        RasPreprocess,
        "_get_visible_window_titles",
        staticmethod(
            lambda root_pid=None: observed.append(root_pid)
            or ["Terms and Conditions for Use (TCU)"]
        ),
    )

    assert RasPreprocess._detect_first_run_tcu_dialog(777) == (
        RasPreprocess._TCU_BLOCKING_ERROR
    )
    assert observed == [777]
