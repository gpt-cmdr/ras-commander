import importlib
import logging
from pathlib import Path

import pandas as pd


raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")
RasPreprocess = raspreprocess_module.RasPreprocess

PREPROCESS_LOGGER = "ras_commander.RasPreprocess"


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "PreprocessProject"
        self.ras_exe_path = self.project_folder / "Ras.exe"
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Geom File": "g03"}]
        )

    def check_initialized(self):
        return None


class _FakeProcess:
    pid = 12345
    returncode = None

    def poll(self):
        return None


def _preprocess_records(caplog):
    return [record for record in caplog.records if record.name == PREPROCESS_LOGGER]


def _seed_project(tmp_path: Path) -> _FakeRasProject:
    project = _FakeRasProject(tmp_path / "project")
    project.project_folder.mkdir(parents=True)
    project.ras_exe_path.write_text("", encoding="utf-8")
    (project.project_folder / "PreprocessProject.prj").write_text(
        "Proj Title=PreprocessProject\n",
        encoding="utf-8",
    )
    (project.project_folder / "PreprocessProject.p01").write_text(
        "Plan Title=Preprocess Test\nGeom File=g03\n",
        encoding="utf-8",
    )
    return project


def _write_preprocess_outputs(project_folder: Path):
    (project_folder / "PreprocessProject.p01.tmp.hdf").write_bytes(b"t" * 1024 * 1024)
    (project_folder / "PreprocessProject.b01").write_bytes(b"b" * 2048)
    (project_folder / "PreprocessProject.x03").write_bytes(b"x" * 4096)


def test_verify_preprocessing_is_debug_only(tmp_path, caplog):
    ras_obj = _seed_project(tmp_path)
    _write_preprocess_outputs(ras_obj.project_folder)
    caplog.set_level(logging.DEBUG, logger=PREPROCESS_LOGGER)

    assert RasPreprocess.verify_preprocessing("01", ras_object=ras_obj) is True

    records = _preprocess_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]
    assert info_messages == []
    assert "All preprocessing files verified for plan 01" in debug_messages


def test_preprocess_plan_logs_start_and_final_info_only(
    tmp_path,
    monkeypatch,
    caplog,
):
    ras_obj = _seed_project(tmp_path)

    class FakeBcoMonitor:
        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, *, project_path, **_kwargs):
            self.project_path = Path(project_path)

        def monitor_until_signal(self, _process):
            _write_preprocess_outputs(self.project_path)
            return True

    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", FakeBcoMonitor)
    monkeypatch.setattr(
        raspreprocess_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_process_tree",
        staticmethod(
            lambda _process: raspreprocess_module.logger.debug(
                "HEC-RAS process tree terminated"
            )
        ),
    )
    caplog.set_level(logging.DEBUG, logger=PREPROCESS_LOGGER)

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras_obj,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is True
    records = _preprocess_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages[0] == "Starting HEC-RAS preprocessing for plan 01"
    assert len(info_messages) == 2
    assert info_messages[1].startswith("Preprocessing complete for plan 01 in ")
    assert "tmp.hdf=1.0MB, b=2KB, x=4KB" in info_messages[1]
    assert all(str(ras_obj.project_folder) not in message for message in info_messages)
    assert any("Preprocessing signal detected; terminating HEC-RAS" in message for message in debug_messages)
    assert "HEC-RAS process tree terminated" in debug_messages
    assert any(str(result.tmp_hdf_path) in message for message in debug_messages)


def test_full_simulation_fallback_warning_is_concise(
    tmp_path,
    monkeypatch,
    caplog,
):
    ras_obj = _seed_project(tmp_path)
    (ras_obj.project_folder / "PreprocessProject.p01.hdf").write_bytes(b"h" * 1024)
    (ras_obj.project_folder / "PreprocessProject.b01").write_bytes(b"b" * 2048)
    (ras_obj.project_folder / "PreprocessProject.x03").write_bytes(b"x" * 4096)

    class CompletedProcess:
        pid = 12345
        returncode = 0

        def poll(self):
            return 0

    class FakeBcoMonitor:
        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **_kwargs):
            return None

        def monitor_until_signal(self, _process):
            return True

    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", FakeBcoMonitor)
    monkeypatch.setattr(
        raspreprocess_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: CompletedProcess(),
    )
    caplog.set_level(logging.DEBUG, logger=PREPROCESS_LOGGER)

    result = RasPreprocess.preprocess_plan(
        "01",
        ras_object=ras_obj,
        clear_existing=False,
        fix_line_endings=False,
    )

    assert result.success is True
    warning_messages = [
        record.getMessage()
        for record in _preprocess_records(caplog)
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in _preprocess_records(caplog)
        if record.levelno == logging.DEBUG
    ]

    assert warning_messages == [
        "Full simulation completed before early termination; copying "
        "PreprocessProject.p01.hdf to PreprocessProject.p01.tmp.hdf"
    ]
    assert all(str(ras_obj.project_folder) not in message for message in warning_messages)
    assert "Preprocessing complete; HEC-RAS process already exited" in debug_messages
