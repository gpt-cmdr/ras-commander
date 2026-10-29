"""Resolve 7.0.2 without substituting an older installed engine."""

from importlib import import_module

import pytest

from ras_commander import RasProcess
from ras_commander.RasPrj import get_ras_exe
from ras_commander.RasUtils import RasUtils


@pytest.mark.parametrize("version", ["7.0.2", "702", "7.02"])
def test_702_resolves_exact_discovered_install(monkeypatch, tmp_path, version):
    older = tmp_path / "7.0.1" / "Ras.exe"
    requested = tmp_path / "7.0.2" / "Ras.exe"
    for executable in (older, requested):
        executable.parent.mkdir()
        executable.touch()
    monkeypatch.setattr(
        RasUtils,
        "discover_ras_versions",
        staticmethod(lambda: {"7.0.1": older, "7.0.2": requested}),
    )

    assert get_ras_exe(version) == str(requested)


@pytest.mark.parametrize("version", ["7.0.2", "702"])
def test_rasprocess_uses_discovered_runtime(monkeypatch, tmp_path, version):
    executable = tmp_path / "custom" / "7.0.2" / "Ras.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    companion = executable.with_name("RasProcess.exe")
    companion.touch()
    module = import_module("ras_commander.RasProcess")
    monkeypatch.setattr(module, "IS_WINDOWS", True)
    monkeypatch.setattr(
        RasUtils, "discover_ras_versions", staticmethod(lambda: {"7.0.2": executable})
    )

    assert RasProcess.find_rasprocess(version) == companion
    companion.unlink()
    assert RasProcess.find_rasprocess(version) is None


@pytest.mark.parametrize("use_directory", [False, True])
def test_rasprocess_accepts_explicit_runtime(tmp_path, use_directory):
    executable = tmp_path / "Ras.exe"
    executable.touch()
    companion = tmp_path / "RasProcess.exe"
    companion.touch()
    requested = tmp_path if use_directory else executable
    assert RasProcess.find_rasprocess(requested) == companion
    companion.unlink()
    assert RasProcess.find_rasprocess(requested) is None
