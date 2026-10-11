"""Regression contracts for the native HDF5 DLL isolation boundary."""

import ast
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import ras_commander._gdal_runtime as gdal_runtime
import ras_commander._landcover_native as native


def test_missing_pythonnet_has_actionable_error_before_native_loading(monkeypatch):
    worker = Path(native.__file__).with_name("_property_tables_worker.py")
    namespace = runpy.run_path(str(worker))
    monkeypatch.setattr(namespace["importlib"].util, "find_spec", lambda _: None)
    with pytest.raises(ImportError, match=r"pythonnet>=3.0.5.*ras-commander\[mesh\]"):
        namespace["main"]()


def test_worker_boundary_preserves_mapped_drive_path(monkeypatch):
    geometry = Path("H:/model/model.g01.hdf")
    commands = []
    monkeypatch.setattr(gdal_runtime, "configure_rasmapper_gdal_bridge", lambda _: None)

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(native.subprocess, "run", run)
    native._run_property_tables_worker(Path("C:/HEC-RAS/6.6"), geometry)
    assert commands[0][-1] == str(geometry)
    assert commands[0][-1].startswith("H:")


def test_modern_property_computation_does_not_load_clr_in_parent(tmp_path, monkeypatch):
    mapper = tmp_path / "model.rasmap"
    geometry = tmp_path / "model.g01.hdf"
    mapper.touch()
    geometry.touch()
    calls = []
    monkeypatch.setattr(native, "find_hecras_install", lambda version: tmp_path)
    monkeypatch.setattr(
        native,
        "load_clr",
        lambda *_: pytest.fail("h5py parent must not compute native tables"),
    )
    monkeypatch.setattr(
        native, "_run_property_tables_worker", lambda *args: calls.append(args)
    )
    monkeypatch.setattr(
        native,
        "_validate_property_tables_postcondition",
        lambda path: calls.append(path),
    )
    assert (
        native.recompute_property_tables(
            rasmap_path=mapper, geometry_hdf_path=geometry, hecras_version="6.6"
        )
        == geometry
    )
    assert calls == [(tmp_path, geometry), geometry]


def test_worker_command_uses_direct_file_and_geometry_working_directory(
    tmp_path, monkeypatch
):
    geometry = tmp_path / "model with spaces.g01.hdf"
    calls = []
    monkeypatch.setattr(
        gdal_runtime, "configure_rasmapper_gdal_bridge", lambda path: None
    )

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="computed", stderr="")

    monkeypatch.setattr(native.subprocess, "run", run)
    native._run_property_tables_worker(tmp_path, geometry)
    command, options = calls[0]
    assert Path(command[1]).name == "_property_tables_worker.py"
    assert "-m" not in command
    assert command[2:] == [str(tmp_path), str(geometry)]
    assert options["cwd"] == str(tmp_path)
    assert options["timeout"] == 1800
    assert options["capture_output"]


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_worker_failure_propagates_before_success_validation(
    tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(
        gdal_runtime, "configure_rasmapper_gdal_bridge", lambda path: None
    )

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], 1800)
        return SimpleNamespace(returncode=1, stdout="", stderr="native failure detail")

    monkeypatch.setattr(native.subprocess, "run", run)
    with pytest.raises(
        RuntimeError,
        match="1800 seconds" if failure == "timeout" else "native failure detail",
    ):
        native._run_property_tables_worker(tmp_path, tmp_path / "model.g01.hdf")


def test_worker_imports_only_stdlib_and_native_interop():
    worker = Path(native.__file__).with_name("_property_tables_worker.py")
    tree = ast.parse(worker.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module.split(".")[0])
    assert roots <= {
        "__future__",
        "ctypes",
        "importlib",
        "os",
        "sys",
        "pathlib",
        "clr",
        "RasMapperLib",
        "HDF",
    }
