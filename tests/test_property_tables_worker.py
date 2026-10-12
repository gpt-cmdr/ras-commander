"""Regression contracts for the native HDF5 DLL isolation boundary."""

import ast
import importlib.util
import os
import runpy
import subprocess
import sys
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
    assert commands[0][-1] == str(geometry.absolute())
    if native.os.name == "nt":
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
    assert command[1] == "-I"
    assert Path(command[2]).name == "_property_tables_worker.py"
    assert "-m" not in command
    assert command[3:] == [str(tmp_path), str(geometry)]
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


def test_relative_environment_install_and_recovery_paths(tmp_path, monkeypatch):
    from ras_commander.dotnet.clr_bootstrap import find_hecras_install

    install = tmp_path / "runtime" / "6.6"
    install.mkdir(parents=True)
    (install / "Ras.exe").touch()
    (install / "RasMapperLib.dll").touch()
    work = tmp_path / "models"
    work.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HECRAS_INSTALL_ROOT", "runtime/6.6")
    calls = []
    monkeypatch.setattr(
        gdal_runtime, "configure_rasmapper_gdal_bridge", lambda path: calls.append(path)
    )
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs))
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    native._run_property_tables_worker(
        find_hecras_install("6.6"),
        Path("models/target.g01.hdf"),
        calibration_source=Path("source.g01.hdf"),
    )
    assert calls[0] == install
    command, options = calls[1]
    assert command[3:] == [
        str(install),
        str(work / "target.g01.hdf"),
        str(tmp_path / "source.g01.hdf"),
    ]
    assert options["cwd"] == str(work)


def test_actual_launcher_ignores_startup_hook_and_pythonpath(tmp_path, monkeypatch):
    hook = tmp_path / "hooks"
    hook.mkdir()
    marker = tmp_path / "startup-ran"
    (hook / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    worker = tmp_path / "_property_tables_worker.py"
    worker.write_text(
        "import sys\n"
        "assert sys.flags.isolated and sys.flags.ignore_environment\n"
        "assert sys.flags.no_user_site\n"
        "assert 'sitecustomize' not in sys.modules\n"
        "from pathlib import Path\n"
        "assert all(Path(p).is_absolute() for p in sys.argv[1:])\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(hook))
    monkeypatch.setenv("PYTHONUSERBASE", str(hook))
    monkeypatch.setattr(native, "__file__", str(tmp_path / "_landcover_native.py"))
    monkeypatch.setattr(gdal_runtime, "configure_rasmapper_gdal_bridge", lambda _: None)
    native._run_property_tables_worker(tmp_path, tmp_path / "model.g01.hdf")
    assert not marker.exists()


NATIVE_IDENTITY_PROBE = r"""
import ctypes, runpy, sys, types
from pathlib import Path
worker, selected, alternate, mode = sys.argv[1:]
namespace = runpy.run_path(worker)
if mode != "clean":
    foreign = ctypes.WinDLL(str(Path(alternate) / "bin64/hdf5.dll"))
    foreign.H5open()
    foreign.H5Pcreate.argtypes = [ctypes.c_longlong]
    foreign.H5Pcreate.restype = ctypes.c_longlong
    probe = foreign.H5Pcreate(
        ctypes.c_longlong.in_dll(foreign, "H5P_CLS_FILE_ACCESS_ID_g").value
    )
if mode == "identity-only":
    import clr
    clr.AddReference(str(Path(selected) / "HDF.PInvoke.dll"))
    from HDF.PInvoke import H5, H5I
    chosen = ctypes.WinDLL(str(Path(selected) / "bin64/hdf5.dll"))
    chosen.H5Iis_valid.argtypes = [ctypes.c_longlong]
    print("MANAGED_SEES_ALTERNATE", H5I.is_valid(probe),
          "SELECTED_SEES_ALTERNATE", chosen.H5Iis_valid(probe), flush=True)
    print("MANAGED_METADATA", H5.get_libversion(0, 0, 0),
          H5.is_library_threadsafe(0), flush=True)
    namespace["_verify_managed_hdf5_identity"](chosen, H5I)
else:
    class ProbeCommand:
        def __init__(self, path): pass
        def Execute(self, _):
            print("COMPUTE_REACHED", "h5py" in sys.modules, flush=True)
    module = types.ModuleType("RasMapperLib.Scripting")
    module.ComputePropertyTablesCommand = ProbeCommand
    sys.modules["RasMapperLib.Scripting"] = module
    sys.argv = [worker, selected, str(Path.cwd() / "never-opened.g01.hdf")]
    namespace["main"]()
"""


@pytest.mark.parametrize("failure", ["version", "unsafe", "query"])
def test_incompatible_hdf5_metadata_fails_closed(failure):
    worker = Path(native.__file__).with_name("_property_tables_worker.py")
    namespace = runpy.run_path(str(worker))

    def version(*pointers):
        for pointer, value in zip(pointers, (1, 10, 6)):
            pointer._obj.value = value
        return -1 if failure == "query" else 0

    library = SimpleNamespace(H5get_libversion=version)
    managed = SimpleNamespace(
        get_libversion=lambda *_: (
            (0, 2, 0, 0) if failure == "version" else (0, 1, 10, 6)
        ),
        is_library_threadsafe=lambda _: (0, 0) if failure == "unsafe" else (0, 1),
    )
    messages = {
        "version": "did not bind",
        "unsafe": "thread-safe",
        "query": "Cannot inspect",
    }
    with pytest.raises(RuntimeError, match=messages[failure]):
        namespace["_verify_hdf5_metadata"](library, managed)


@pytest.mark.parametrize("mode", ["clean", "foreign", "identity-only"])
def test_real_native_hdf5_identity_guard(tmp_path, mode):
    if sys.platform != "win32" or importlib.util.find_spec("clr") is None:
        pytest.skip("Requires Windows Python, pythonnet and two HEC-RAS installations")
    root = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    root = root / "HEC" / "HEC-RAS"
    selected = Path(os.environ.get("RAS_COMMANDER_TEST_INSTALL", root / "6.6"))
    alternate = Path(os.environ.get("RAS_COMMANDER_TEST_ALTERNATE", root / "6.5"))
    if not all((p / "bin64/hdf5.dll").is_file() for p in (selected, alternate)):
        pytest.skip("Two HEC-RAS native HDF5 installations are unavailable")
    script = tmp_path / "identity_probe.py"
    script.write_text(NATIVE_IDENTITY_PROBE)
    worker = Path(native.__file__).with_name("_property_tables_worker.py").absolute()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            str(worker),
            str(selected),
            str(alternate),
            mode,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    if mode == "clean":
        assert result.returncode == 0, output
        assert "HDF.PInvoke identity verified:" in output
        assert "COMPUTE_REACHED False" in output
    else:
        assert result.returncode != 0, output
        assert "COMPUTE_REACHED" not in output
        if mode == "foreign":
            assert "Foreign HDF5 DLL already loaded:" in output
            assert str(alternate) in output
        else:
            assert "MANAGED_SEES_ALTERNATE 1 SELECTED_SEES_ALTERNATE 0" in output
            assert "(0, 1, 10, 6) (0, 1)" in output
            assert "HDF.PInvoke DLL identity check failed:" in output
