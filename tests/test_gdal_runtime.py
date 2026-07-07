import os
import importlib
import logging
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from ras_commander import _gdal_runtime
from ras_commander.geom.GeomMesh import GeomMesh

geom_mesh_module = importlib.import_module("ras_commander.geom.GeomMesh")


def _make_hecras_gdal_tree(tmp_path: Path) -> Path:
    hecras_dir = tmp_path / "HEC-RAS" / "7.0"
    (hecras_dir / "GDAL" / "bin64").mkdir(parents=True)
    (hecras_dir / "GDAL" / "common" / "data").mkdir(parents=True)
    return hecras_dir


def test_configure_hecras_gdal_runtime_uses_bundled_gdal(monkeypatch, tmp_path):
    hecras_dir = _make_hecras_gdal_tree(tmp_path)
    dll_dirs = []

    class FakeDllDirectory:
        def close(self):
            return None

    def fake_add_dll_directory(path):
        dll_dirs.append(Path(path))
        return FakeDllDirectory()

    monkeypatch.setattr(os, "add_dll_directory", fake_add_dll_directory, raising=False)
    monkeypatch.setattr(_gdal_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setenv("PATH", "C:\\Existing")

    if str(hecras_dir) in sys.path:
        sys.path.remove(str(hecras_dir))

    paths = _gdal_runtime.configure_hecras_gdal_runtime(hecras_dir)

    assert paths.gdal_bin == hecras_dir / "GDAL" / "bin64"
    assert os.environ["GDAL_DATA"] == str(hecras_dir / "GDAL" / "common" / "data")
    assert os.environ["PROJ_LIB"] == os.environ["GDAL_DATA"]
    assert os.environ["PATH"].split(os.pathsep)[:2] == [
        str(hecras_dir / "GDAL" / "bin64"),
        str(hecras_dir),
    ]
    assert dll_dirs == [hecras_dir, hecras_dir / "GDAL" / "bin64"]
    assert str(hecras_dir) in sys.path


def test_configure_rasmapper_gdal_bridge_creates_python_sibling(
    monkeypatch,
    tmp_path,
    caplog,
):
    hecras_dir = _make_hecras_gdal_tree(tmp_path)
    python_dir = tmp_path / "uv-python"
    python_dir.mkdir()
    commands = []

    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    monkeypatch.setattr(_gdal_runtime.platform, "system", lambda: "Windows")

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        (python_dir / "GDAL" / "bin64").mkdir(parents=True)
        (python_dir / "GDAL" / "common" / "data").mkdir(parents=True)
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_gdal_runtime.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG, logger="ras_commander._gdal_runtime")

    paths = _gdal_runtime.configure_rasmapper_gdal_bridge(
        hecras_dir,
        python_dir=python_dir,
    )

    assert paths.hecras_dir == hecras_dir
    assert _gdal_runtime.python_gdal_bridge_is_usable(python_dir)
    assert commands

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander._gdal_runtime"
        and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander._gdal_runtime"
        and record.levelno == logging.DEBUG
    ]
    assert info_messages == ["Created GDAL junction for HEC-RAS GDAL bridge"]
    assert all(str(tmp_path) not in message for message in info_messages)
    assert any(
        str(python_dir / "GDAL") in message and str(hecras_dir / "GDAL") in message
        for message in debug_messages
    )


def test_configure_rasmapper_gdal_bridge_creates_venv_and_base_bridges(
    monkeypatch, tmp_path
):
    hecras_dir = _make_hecras_gdal_tree(tmp_path)
    venv_scripts = tmp_path / "project" / ".venv" / "Scripts"
    base_python_dir = tmp_path / "uv-python"
    venv_scripts.mkdir(parents=True)
    base_python_dir.mkdir()
    commands = []

    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    monkeypatch.setattr(_gdal_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        _gdal_runtime.sys,
        "executable",
        str(venv_scripts / "python.exe"),
    )
    monkeypatch.setattr(
        _gdal_runtime.sys,
        "_base_executable",
        str(base_python_dir / "python.exe"),
        raising=False,
    )
    monkeypatch.setattr(_gdal_runtime.sys, "prefix", str(tmp_path / "project" / ".venv"))
    monkeypatch.setattr(_gdal_runtime.sys, "base_prefix", str(base_python_dir))
    monkeypatch.setattr(
        _gdal_runtime.sys,
        "exec_prefix",
        str(tmp_path / "project" / ".venv"),
    )
    monkeypatch.setattr(_gdal_runtime.sys, "base_exec_prefix", str(base_python_dir))

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        command_text = cmd[-1]
        for candidate in (venv_scripts, base_python_dir):
            if str(candidate / "GDAL") in command_text:
                (candidate / "GDAL" / "bin64").mkdir(parents=True)
                (candidate / "GDAL" / "common" / "data").mkdir(parents=True)
                return CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Unexpected GDAL junction command: {command_text}")

    monkeypatch.setattr(_gdal_runtime.subprocess, "run", fake_run)

    _gdal_runtime.configure_rasmapper_gdal_bridge(hecras_dir)

    assert _gdal_runtime.python_gdal_bridge_is_usable(venv_scripts)
    assert _gdal_runtime.python_gdal_bridge_is_usable(base_python_dir)
    assert len(commands) == 2


def test_geom_mesh_setup_gdal_bridge_creates_python_gdal_by_default(monkeypatch, tmp_path):
    hecras_dir = _make_hecras_gdal_tree(tmp_path)
    python_dir = tmp_path / "uv-python"
    python_dir.mkdir()

    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    monkeypatch.setattr(_gdal_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(geom_mesh_module.platform, "system", lambda: "Windows")

    def fake_run(cmd, **kwargs):
        (python_dir / "GDAL" / "bin64").mkdir(parents=True)
        (python_dir / "GDAL" / "common" / "data").mkdir(parents=True)
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_gdal_runtime.subprocess, "run", fake_run)

    assert GeomMesh.setup_gdal_bridge(
        hecras_dir=hecras_dir,
        python_dir=python_dir,
    )
    assert _gdal_runtime.python_gdal_bridge_is_usable(python_dir)


def test_geom_mesh_load_dlls_stops_before_rasmapper_when_bridge_fails(monkeypatch):
    add_reference_calls = []

    class FakeClr:
        @staticmethod
        def AddReference(path):
            add_reference_calls.append(path)

    monkeypatch.setattr(geom_mesh_module, "_dlls_loaded", False)
    monkeypatch.setattr(geom_mesh_module.platform, "system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "clr", FakeClr)
    monkeypatch.setattr(
        GeomMesh,
        "setup_gdal_bridge",
        staticmethod(lambda hecras_dir=None, create_junction=True: False),
    )

    with pytest.raises(RuntimeError, match="GDAL bridge"):
        geom_mesh_module._load_dlls("C:/HEC-RAS/7.0")

    assert add_reference_calls == []


def test_resolve_hecras_gdal_paths_reports_missing_bin64(tmp_path):
    hecras_dir = tmp_path / "HEC-RAS" / "7.0"
    (hecras_dir / "GDAL" / "common" / "data").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="bin64"):
        _gdal_runtime.resolve_hecras_gdal_paths(hecras_dir)
