import subprocess
from pathlib import Path

import h5py
import pandas as pd

from ras_commander.RasBco import BcoMonitor
from ras_commander.RasPreprocess import RasPreprocess


def test_tcu_detector_matches_exact_visible_dialog(monkeypatch):
    monkeypatch.setattr(
        RasPreprocess,
        "_get_visible_window_titles",
        staticmethod(
            lambda root_pid=None: [
                "HEC-RAS 7.0.1",
                "  TERMS AND CONDITIONS FOR USE (TCU)  ",
            ]
        ),
    )

    assert (
        RasPreprocess._detect_first_run_tcu_dialog()
        == RasPreprocess._TCU_BLOCKING_ERROR
    )


def test_tcu_detector_ignores_other_windows(monkeypatch):
    monkeypatch.setattr(
        RasPreprocess,
        "_get_visible_window_titles",
        staticmethod(
            lambda root_pid=None: ["HEC-RAS 7.0.1", "Compute Window"]
        ),
    )

    assert RasPreprocess._detect_first_run_tcu_dialog() is None


class _FakeRas:
    def __init__(self, project_folder: Path, executable: Path):
        self.project_folder = project_folder
        self.project_name = "fixture"
        self.ras_exe_path = executable
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Geom File": "g01"}]
        )

    def check_initialized(self):
        return None


class _RunningProcess:
    pid = 12345
    returncode = None

    def poll(self):
        return None


def test_preprocess_reports_tcu_blocker_without_waiting_or_assent(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "fixture.prj").write_text("Proj Title=fixture\n", encoding="utf-8")
    (tmp_path / "fixture.p01").write_text("Geom File=g01\n", encoding="utf-8")
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"fixture")
    process = _RunningProcess()
    terminated = []

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda _path: True),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "_tcu_supervision_availability_error",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "_detect_first_run_tcu_dialog",
        staticmethod(
            lambda root_pid=None: RasPreprocess._TCU_BLOCKING_ERROR
        ),
    )

    def blocked_monitor(self, _process):
        self.blocked_reason = self.blocking_condition()
        return False

    monkeypatch.setattr(BcoMonitor, "monitor_until_signal", blocked_monitor)
    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_process_tree",
        staticmethod(lambda child: terminated.append(child)),
    )

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=_FakeRas(tmp_path, executable),
        clear_existing=False,
        max_wait=30,
    )

    assert not result
    assert result.error == RasPreprocess._TCU_BLOCKING_ERROR
    assert terminated == [process]


def test_tcu_detector_forwards_launcher_pid(monkeypatch):
    observed = []
    monkeypatch.setattr(
        RasPreprocess,
        "_get_visible_window_titles",
        staticmethod(
            lambda root_pid=None: observed.append(root_pid)
            or ["Terms and Conditions for Use (TCU)"]
        ),
    )

    assert RasPreprocess._detect_first_run_tcu_dialog(777)
    assert observed == [777]


def test_tcu_detector_reports_process_scope_failure(monkeypatch):
    monkeypatch.setattr(
        RasPreprocess,
        "_get_visible_window_titles",
        staticmethod(
            lambda root_pid=None: (_ for _ in ()).throw(
                RuntimeError("access denied")
            )
        ),
    )

    reason = RasPreprocess._detect_first_run_tcu_dialog(778)

    assert reason.startswith(RasPreprocess._TCU_SUPERVISION_ERROR)
    assert "access denied" in reason


def test_preprocess_checks_tcu_supervision_before_launch(tmp_path, monkeypatch):
    (tmp_path / "fixture.prj").write_text(
        "Proj Title=fixture\n",
        encoding="utf-8",
    )
    (tmp_path / "fixture.p01").write_text(
        "Geom File=g01\n",
        encoding="utf-8",
    )
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"fixture")
    popen_calls = []

    monkeypatch.setattr(
        RasPreprocess,
        "_tcu_supervision_availability_error",
        staticmethod(lambda: RasPreprocess._TCU_SUPERVISION_ERROR),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *_args, **_kwargs: popen_calls.append(True),
    )

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=_FakeRas(tmp_path, executable),
        clear_existing=False,
    )

    assert not result
    assert result.error == RasPreprocess._TCU_SUPERVISION_ERROR
    assert popen_calls == []


def _standalone_preprocess_fixture(tmp_path: Path):
    (tmp_path / "fixture.prj").write_text(
        "Proj Title=fixture\n",
        encoding="utf-8",
    )
    (tmp_path / "fixture.p01").write_text(
        "Geom File=g01\n",
        encoding="utf-8",
    )
    ras_exe = tmp_path / "Ras.exe"
    ras_exe.write_bytes(b"fixture")
    geom_preprocess = tmp_path / "x64" / "RasGeomPreprocess.exe"
    geom_preprocess.parent.mkdir()
    geom_preprocess.write_bytes(b"fixture")
    input_hdf = tmp_path / "fixture.p01.tmp.hdf"
    with h5py.File(input_hdf, "w") as handle:
        handle.create_group("Geometry")
    x_file = tmp_path / "fixture.x01"
    x_file.write_bytes(b"execution-data")
    return _FakeRas(tmp_path, ras_exe), geom_preprocess, input_hdf, x_file


def test_run_ras_geom_preprocess_uses_argument_vector_and_fingerprints_output(
    tmp_path,
    monkeypatch,
):
    ras_obj, executable, input_hdf, x_file = _standalone_preprocess_fixture(
        tmp_path
    )
    observed = {}

    class Process:
        returncode = None

        def communicate(self, timeout):
            observed["timeout"] = timeout
            with h5py.File(input_hdf, "a") as handle:
                handle["Geometry"].create_dataset("Product Marker", data=[1])
            self.returncode = 0
            return "geometry preprocessing complete", ""

    def popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(subprocess, "Popen", popen)

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
        timeout=45,
    )

    assert result
    assert result.executable_path == executable
    assert result.executable_sha256 == RasPreprocess._file_sha256(executable)
    assert result.input_hdf_path == input_hdf
    assert result.x_file_path == x_file
    assert result.output_changed is True
    assert result.input_hdf_sha256_before != result.input_hdf_sha256_after
    assert result.return_code == 0
    assert result.timed_out is False
    assert observed["command"] == [str(executable), str(input_hdf), "x01"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"]["cwd"] == str(tmp_path)
    assert observed["timeout"] == 45


def test_run_ras_geom_preprocess_timeout_terminates_and_fails_closed(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
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
        timeout=2,
        require_hdf_change=True,
    )

    assert not result
    assert result.timed_out is True
    assert result.return_code == -9
    assert terminated == [process]
    assert "timed out after 2 seconds" in result.error
    assert "did not change" in result.error


def test_run_ras_geom_preprocess_rejects_missing_vendor_executable(
    tmp_path,
    monkeypatch,
):
    ras_obj, executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
    )
    executable.unlink()
    popen_calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: popen_calls.append(True),
    )

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
    )

    assert not result
    assert str(executable) in result.error
    assert popen_calls == []


def test_run_ras_geom_preprocess_allows_readable_idempotent_noop_by_default(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
    )

    class Process:
        returncode = 0

        def communicate(self, timeout):
            return "Finished Processing Geometry", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
    )

    assert result
    assert result.output_changed is False
    assert result.hdf_readable is True
    assert result.geometry_group_present is True


def test_run_ras_geom_preprocess_rejects_changed_but_corrupt_hdf(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, input_hdf, _x_file = _standalone_preprocess_fixture(
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


def test_run_ras_geom_preprocess_rejects_fatal_output_with_zero_exit(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
    )

    class Process:
        returncode = 0

        def communicate(self, timeout):
            return "Fatal: invalid geometry table", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
    )

    assert not result
    assert result.first_error_line == "Fatal: invalid geometry table"
    assert "reported an error" in result.error


def test_run_ras_geom_preprocess_rejects_misplaced_x_file_before_launch(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
    )
    misplaced = tmp_path / "other" / "fixture.x01"
    misplaced.parent.mkdir()
    misplaced.write_bytes(b"execution-data")
    popen_calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: popen_calls.append(True),
    )

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
        x_file_path=misplaced,
    )

    assert not result
    assert "beside the input HDF" in result.error
    assert popen_calls == []


def test_run_ras_geom_preprocess_requires_final_return_code(
    tmp_path,
    monkeypatch,
):
    ras_obj, _executable, _input_hdf, _x_file = _standalone_preprocess_fixture(
        tmp_path
    )

    class Process:
        returncode = None

        def communicate(self, timeout):
            return "Finished Processing Geometry", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())

    result = RasPreprocess.run_ras_geom_preprocess(
        "01",
        ras_object=ras_obj,
    )

    assert not result
    assert "final return code" in result.error
