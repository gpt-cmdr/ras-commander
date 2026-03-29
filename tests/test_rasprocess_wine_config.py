from importlib import import_module
import subprocess

import pytest


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


@pytest.fixture(autouse=True)
def restore_wine_config():
    original = RasProcess._wine_config
    yield
    RasProcess._wine_config = original


def _make_wine_prefix(tmp_path):
    prefix = tmp_path / "wineprefix"
    (prefix / "drive_c").mkdir(parents=True)
    return prefix


def test_linux_to_wine_path_uses_winepath_for_wine64(
    monkeypatch,
    tmp_path,
):
    prefix = _make_wine_prefix(tmp_path)
    RasProcess.configure_wine(wine_prefix=prefix, wine_executable="wine64")

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="Z:\\converted\n",
            stderr="",
        )

    monkeypatch.setattr(ras_process_module.subprocess, "run", fake_run)

    converted = RasProcess._linux_to_wine_path(
        tmp_path / "outside-drive-c" / "example.txt"
    )

    assert converted == "Z:\\converted"
    assert calls[0][0][0] == "winepath"
    assert calls[0][0][0] != "wine64path"
    assert calls[0][1]["env"]["WINEPREFIX"] == str(prefix)


def test_linux_to_wine_path_prefers_sibling_winepath(
    monkeypatch,
    tmp_path,
):
    prefix = _make_wine_prefix(tmp_path)
    wine_dir = tmp_path / "custom-wine" / "bin"
    wine_dir.mkdir(parents=True)
    wine_executable = wine_dir / "wine64"
    winepath_executable = wine_dir / "winepath"
    wine_executable.write_text("", encoding="utf-8")
    winepath_executable.write_text("", encoding="utf-8")
    RasProcess.configure_wine(
        wine_prefix=prefix,
        wine_executable=str(wine_executable),
    )

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="Z:\\converted\n",
            stderr="",
        )

    monkeypatch.setattr(ras_process_module.subprocess, "run", fake_run)

    RasProcess._linux_to_wine_path(tmp_path / "outside-drive-c" / "example.txt")

    assert calls[0][0][0] == str(winepath_executable)


def test_check_wine_environment_uses_configured_wine_executable(
    monkeypatch,
    tmp_path,
):
    prefix = _make_wine_prefix(tmp_path)
    wine_dir = tmp_path / "custom-wine" / "bin"
    wine_dir.mkdir(parents=True)
    wine_executable = wine_dir / "wine64"
    wine_executable.write_text("", encoding="utf-8")
    RasProcess.configure_wine(
        wine_prefix=prefix,
        wine_executable=str(wine_executable),
    )

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="wine-10.0\n",
            stderr="",
        )

    monkeypatch.setattr(ras_process_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        RasProcess,
        "find_rasprocess",
        staticmethod(lambda ras_version=None: None),
    )

    status = RasProcess.check_wine_environment()

    assert status["wine_found"] is True
    assert status["wine_version"] == "wine-10.0"
    assert calls[0][0] == [str(wine_executable), "--version"]
    assert calls[0][1]["env"]["WINEPREFIX"] == str(prefix)


def test_check_wine_environment_defaults_to_plain_wine(
    monkeypatch,
):
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="wine-9.0\n",
            stderr="",
        )

    monkeypatch.setattr(ras_process_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        RasProcess,
        "_get_wine_config",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        RasProcess,
        "find_rasprocess",
        staticmethod(lambda ras_version=None: None),
    )

    status = RasProcess.check_wine_environment()

    assert status["wine_found"] is True
    assert calls[0][0] == ["wine", "--version"]
    assert "WINEPREFIX" not in calls[0][1]["env"]
