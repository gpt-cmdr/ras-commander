"""Logging when HEC-RAS is unavailable: one WARNING off Windows, Windows unchanged."""

from importlib import import_module
import logging
import sys
from pathlib import Path

from ras_commander.RasPrj import RasPrj, get_ras_exe, init_ras_project
from ras_commander.RasTcu import RasTcu, TcuStatus
from ras_commander.RasUtils import RasUtils


rasprj_module = import_module("ras_commander.RasPrj")


def _project_with_plans(tmp_path, versions):
    for index, version in enumerate(versions, start=1):
        (tmp_path / f"Model.p{index:02d}").write_text(
            f"Plan Title=Plan {index}\nProgram Version={version}\n",
            encoding="utf-8",
        )
    return tmp_path


def _stub_environment(monkeypatch, platform, discovered=None):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(
        RasUtils, "discover_ras_versions", staticmethod(lambda: dict(discovered or {}))
    )
    # get_ras_exe also probes C:/Program Files (x86)/HEC/HEC-RAS/<version>/Ras.exe
    # directly; hide real installs so the host machine cannot change the result.
    real_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: "/HEC/HEC-RAS/" not in path.as_posix() and real_is_file(path),
    )
    if platform != "win32":
        # RasTcu.status follows os.name, not sys.platform: return its off-Windows result.
        not_windows = TcuStatus(None, None, None, None, "not-windows")
        monkeypatch.setattr(RasTcu, "status", staticmethod(lambda *a, **k: not_windows))

    def fake_initialize(self, project_folder, ras_exe_path, **_kwargs):
        self.project_folder = project_folder
        self.project_name = "Synthetic"
        self.ras_exe_path = ras_exe_path

    monkeypatch.setattr(RasPrj, "initialize", fake_initialize)


def _records(caplog, level):
    return [r for r in caplog.records if r.levelno == level and r.name == rasprj_module.logger.name]


def test_non_windows_without_install_logs_one_warning(monkeypatch, tmp_path, caplog):
    _stub_environment(monkeypatch, "linux")
    project = _project_with_plans(tmp_path, ["5.00", "5.10", "6.60"])

    with caplog.at_level(logging.DEBUG, logger=rasprj_module.logger.name):
        ras = init_ras_project(project, ras_object=RasPrj(), hide_intro=True)

    assert ras.ras_exe_path == "Ras.exe"
    assert _records(caplog, logging.ERROR) == []
    warnings = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    assert warnings == [rasprj_module._RAS_UNAVAILABLE_ON_PLATFORM_MESSAGE]
    assert "folder exists" not in " ".join(warnings)
    # Diagnostic detail stays available at DEBUG.
    assert any("Ras.exe not found" in r.getMessage() for r in _records(caplog, logging.DEBUG))


def test_non_windows_with_wine_install_keeps_error(monkeypatch, tmp_path, caplog):
    _stub_environment(monkeypatch, "linux", discovered={"6.6": tmp_path / "Ras.exe"})

    with caplog.at_level(logging.ERROR, logger=rasprj_module.logger.name):
        assert get_ras_exe("5.0") == "Ras.exe"

    assert len(_records(caplog, logging.ERROR)) == 1


def test_windows_without_install_keeps_error_logging(monkeypatch, tmp_path, caplog):
    _stub_environment(monkeypatch, "win32")
    project = _project_with_plans(tmp_path, ["5.00"])

    with caplog.at_level(logging.WARNING, logger=rasprj_module.logger.name):
        init_ras_project(project, ras_object=RasPrj(), hide_intro=True)

    errors = [r.getMessage() for r in _records(caplog, logging.ERROR)]
    assert any("folder exists but Ras.exe not found" in m for m in errors)
    assert "No valid HEC-RAS version found in any plan files." in errors
    warnings = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    assert not any("not available on this platform" in m for m in warnings)
