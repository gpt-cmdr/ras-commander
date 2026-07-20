import importlib
import os
import time
from pathlib import Path
from types import SimpleNamespace

from ras_commander.geom.GeomPreprocessor import (
    GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
    GeomPreprocessor,
)
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


geom_preprocessor_module = importlib.import_module(
    "ras_commander.geom.GeomPreprocessor"
)


def test_compute_message_paths_include_data_error_files(tmp_path):
    paths = GeomPreprocessor._compute_message_paths(tmp_path, "Model", "04")

    names = {Path(path).name for path in paths}

    assert "Model.p04.data_errors.txt" in names
    assert "Model.p04.data_warnings.txt" in names


def test_read_compute_messages_ignores_stale_hdf_messages(tmp_path, monkeypatch):
    start_time = time.time()
    hdf_path = tmp_path / "Model.p01.hdf"
    hdf_path.write_bytes(b"placeholder")
    os.utime(hdf_path, (start_time - 30, start_time - 30))

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(lambda _path: "stale hdf messages"),
    )

    paths, messages = GeomPreprocessor._read_compute_messages(
        [],
        hdf_message_path=hdf_path,
        modified_after=start_time,
    )

    assert paths == []
    assert messages == ""


def test_read_compute_messages_includes_fresh_hdf_messages(tmp_path, monkeypatch):
    start_time = time.time()
    hdf_path = tmp_path / "Model.p01.hdf"
    hdf_path.write_bytes(b"placeholder")
    os.utime(hdf_path, (start_time + 1, start_time + 1))

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(lambda _path: "fresh hdf messages"),
    )

    paths, messages = GeomPreprocessor._read_compute_messages(
        [],
        hdf_message_path=hdf_path,
        modified_after=start_time,
    )

    assert paths == [hdf_path]
    assert messages == "fresh hdf messages"


def test_preprocessor_artifacts_include_fresh_tmp_hdf_only(tmp_path):
    start_time = time.time()
    stale_geom_hdf = tmp_path / "Model.g01.hdf"
    fresh_tmp_hdf = tmp_path / "Model.p02.tmp.hdf"
    stale_geom_hdf.write_bytes(b"old")
    fresh_tmp_hdf.write_bytes(b"new")
    os.utime(stale_geom_hdf, (start_time - 30, start_time - 30))
    os.utime(fresh_tmp_hdf, (start_time + 1, start_time + 1))

    artifacts = GeomPreprocessor._preprocessor_artifacts(
        tmp_path,
        "Model",
        "02",
        "01",
        tmp_hdf_path=fresh_tmp_hdf,
        modified_after=start_time,
    )

    assert artifacts == [fresh_tmp_hdf]


def test_geometry_only_run_flags_disable_unsteady_flow(tmp_path):
    plan_path = tmp_path / "Model.p01"
    plan_path.write_text(
        "\n".join(
            [
                "Run HTab=-1 ",
                "Run UNet=-1 ",
                "Run PostProcess=-1 ",
                "Run RASMapper=-1 ",
                "Run Sediment=-1 ",
                "Run WQNet=-1 ",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    GeomPreprocessor._set_plan_run_flags(
        plan_path,
        GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
    )

    updated = plan_path.read_text(encoding="utf-8")
    assert "Run UNet= 0" in updated
    assert "Run PostProcess= 0" in updated
    assert "Run RASMapper= 0" in updated
def test_geometry_only_disables_unsteady_and_restores_plan(tmp_path, monkeypatch):
    plan_path = tmp_path / "Model.p01"
    original_plan_text = (
        "Plan Title=Test\n"
        "Geom File=g01\n"
        "Run UNet= 1\n"
        "Run PostProcess= 1\n"
        "Run RASMapper= 1\n"
        "Run Sediment= 1\n"
        "Run WQNet= 1\n"
    )
    plan_path.write_text(original_plan_text, encoding="utf-8")

    prj_path = tmp_path / "Model.prj"
    prj_path.write_text("Proj Title=Test\n", encoding="utf-8")
    ras_exe_path = tmp_path / "Ras.exe"
    ras_exe_path.write_bytes(b"placeholder")

    ras_object = SimpleNamespace(
        check_initialized=lambda: None,
        project_folder=tmp_path,
        project_name="Model",
        prj_file=prj_path,
        ras_exe_path=ras_exe_path,
        plan_df=None,
    )
    plan_at_launch = {}

    class CompletedProcess:
        pid = 12345
        returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def communicate(self, timeout=None):
            return b"", b""

    def fake_popen(*_args, **_kwargs):
        plan_at_launch["text"] = plan_path.read_text(encoding="utf-8")
        return CompletedProcess()

    monkeypatch.setattr(
        geom_preprocessor_module.BcoMonitor,
        "enable_detailed_logging",
        lambda _path: None,
    )
    monkeypatch.setattr(geom_preprocessor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        GeomPreprocessor,
        "_monitor_compute_messages",
        staticmethod(
            lambda **_kwargs: {"timed_out": False, "signal_detected": None}
        ),
    )
    monkeypatch.setattr(
        GeomPreprocessor,
        "_wait_for_preprocess_child",
        staticmethod(
            lambda **_kwargs: {
                "saw_child": False,
                "timed_out": False,
                "tmp_hdf_path": None,
            }
        ),
    )
    monkeypatch.setattr(
        GeomPreprocessor,
        "_read_compute_messages",
        staticmethod(lambda *_args, **_kwargs: ([], "")),
    )
    monkeypatch.setattr(
        GeomPreprocessor,
        "_preprocessor_artifacts",
        staticmethod(lambda *_args, **_kwargs: [tmp_path / "Model.x01"]),
    )

    result = GeomPreprocessor.run_geometry_preprocessor(
        plan_path,
        ras_object=ras_object,
        force=False,
        clear_messages=False,
        geometry_only=True,
        restore_plan_settings=True,
        dialog_watchdog=False,
    )

    assert result.success
    assert "Run UNet= 0" in plan_at_launch["text"]
    assert "Run PostProcess= 0" in plan_at_launch["text"]
    assert "Run RASMapper= 0" in plan_at_launch["text"]
    assert plan_path.read_text(encoding="utf-8") == original_plan_text
