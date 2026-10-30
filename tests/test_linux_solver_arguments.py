"""Offline tests for release-driven native Linux solver arguments in RasCmdr.

HEC-RAS releases before 6.3.1 (5.0.7, 6.1) invoke the solver as
``<engine> <proj>.c<geom> b<plan>`` ("cfile"); 6.3.1 and later as
``RasUnsteady <proj>.p<plan>.tmp.hdf x<geom>`` ("tmphdf"). The library layout
(canonical libs/ tree vs 5.0.7 bin_ras/) is independent. The solver here is a
fake ``RasUnsteady`` script; these tests never run HEC-RAS.
"""

import importlib
import json
import shlex
import shutil
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import os
import pytest

from ras_commander.RasCmdr import RasCmdr

rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

BASH = shutil.which("bash")
C_BYTES = b"\x00\x01CGEOM\r\n\x00\xff" * 8


# ---- convention selection ---------------------------------------------------

@pytest.mark.parametrize("release, expected", [
    ("5.0.7", "cfile"),
    ("6.1", "cfile"),
    ("6.2", "cfile"),
    ("6.3", "cfile"),
    ("6.3.1", "tmphdf"),
    ("6.5", "tmphdf"),
    ("6.6", "tmphdf"),
    ("7.0.1", "tmphdf"),
    ("HEC-RAS 5.0.7 March 2019", "cfile"),
    (b"HEC-RAS 6.1 September 2021", "cfile"),
    (np.bytes_(b"HEC-RAS 6.3.1 October 2022"), "tmphdf"),
    ("HEC-RAS 6.6 September 2024", "tmphdf"),
    ((7, 0, 1), "tmphdf"),
    ((6, 1), "cfile"),
    (None, None),
    ("not a release", None),
])
def test_convention_for_release(release, expected):
    assert RasCmdr._linux_solver_arguments_for_release(release) == expected


def _plan_hdf(path, file_version=None, cores=True):
    with h5py.File(path, "w") as hdf:
        if file_version is not None:
            hdf.attrs["File Version"] = np.bytes_(file_version.encode())
        params = hdf.create_group("Plan Data/Plan Parameters")
        if cores:
            params.attrs["1D Cores"] = np.int32(1)
            params.attrs["2D Cores (per mesh)"] = np.array([1], dtype=np.int32)


CANONICAL = {"needs_c_file": False, "label": "canonical"}
BIN_RAS = {"needs_c_file": True, "label": "bin_ras (5.0.7)"}


@pytest.mark.parametrize("version, layout, expected", [
    ("HEC-RAS 5.0.7 March 2019", BIN_RAS, "cfile"),
    ("HEC-RAS 6.1 September 2021", CANONICAL, "cfile"),
    ("HEC-RAS 6.3.1 October 2022", CANONICAL, "tmphdf"),
    ("HEC-RAS 6.6 September 2024", CANONICAL, "tmphdf"),
    ("HEC-RAS 7.0.1 2025", CANONICAL, "tmphdf"),
    (None, BIN_RAS, "cfile"),       # fallback: layout decides
    (None, CANONICAL, "tmphdf"),
])
def test_select_uses_file_version_then_layout(tmp_path, version, layout, expected):
    tmp_hdf = tmp_path / "Demo.p01.tmp.hdf"
    _plan_hdf(tmp_hdf, version)
    convention, source = RasCmdr._select_linux_solver_arguments(tmp_hdf, layout)
    assert convention == expected
    assert source.startswith("tmp.hdf File Version") is (version is not None)


def test_select_falls_back_for_unreadable_hdf(tmp_path):
    tmp_hdf = tmp_path / "Demo.p01.tmp.hdf"
    tmp_hdf.write_bytes(b"not hdf")
    assert RasCmdr._select_linux_solver_arguments(tmp_hdf, CANONICAL)[0] == "tmphdf"
    assert RasCmdr._select_linux_solver_arguments(tmp_path / "missing", BIN_RAS)[0] == "cfile"


def test_select_refuses_modern_hdf_on_bin_ras(tmp_path):
    tmp_hdf = tmp_path / "Demo.p01.tmp.hdf"
    _plan_hdf(tmp_hdf, "HEC-RAS 6.6 September 2024")
    with pytest.raises(ValueError, match="runs only HEC-RAS 5.0.7"):
        RasCmdr._select_linux_solver_arguments(tmp_hdf, BIN_RAS)


# ---- library path ---------------------------------------------------------------

def _make_61_install(root: Path) -> Path:
    """HEC's HEC-RAS_610_Linux.zip layout: Ras_v61/Release + a libs tree two levels up."""
    release = root / "RAS_Linux_test_setup" / "Ras_v61" / "Release"
    release.mkdir(parents=True)
    libs = root / "RAS_Linux_test_setup" / "libs"
    for sub in ("mkl", "rhel_8", "centos_7"):
        (libs / sub).mkdir(parents=True)
    return release


# LD_LIBRARY_PATH is ':'-separated POSIX paths, and the solver stand-in is a
# shell script executed directly; neither holds for a Windows tmp_path.
posix_linux_solver = pytest.mark.skipif(
    os.name == "nt", reason="Linux solver contract: POSIX paths and a shell-script solver"
)


@posix_linux_solver
def test_ld_path_finds_61_libs_two_levels_up_and_skips_centos_7(tmp_path):
    release = _make_61_install(tmp_path)
    libs = release.parent.parent / "libs"
    ld = RasCmdr._build_linux_ld_path(release, {"lib_dirs": []})
    assert ld.split(":") == [str(libs), str(libs / "mkl"), str(libs / "rhel_8")]


@posix_linux_solver
def test_ld_path_keeps_centos_7_when_it_is_the_only_variant(tmp_path):
    root = tmp_path / "install"
    (root / "libs" / "centos_7").mkdir(parents=True)
    (root / "libs" / "mkl").mkdir()
    ld = RasCmdr._build_linux_ld_path(root, {"lib_dirs": []})
    assert ld.split(":") == [str(root / "libs"), str(root / "libs" / "centos_7"),
                             str(root / "libs" / "mkl")]


# ---- compute_plan_linux with a fake RasUnsteady -----------------------------------

_FAKE_SOLVER_PY = r'''
import json, os, sys
import h5py, numpy as np
record = {"argv": sys.argv[1:], "cwd": os.getcwd(),
          "ld": os.environ.get("LD_LIBRARY_PATH"), "omp": os.environ.get("OMP_NUM_THREADS")}
with open(os.environ["FAKE_RECORD"], "w") as fh:
    json.dump(record, fh)
with h5py.File("Muncie.p04.tmp.hdf", "r+") as hdf:
    hdf.create_dataset("Results/Unsteady/Output/Water Surface", data=np.ones(3))
print("Finished Unsteady Flow Simulation")
'''


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_ras_unsteady(directory: Path) -> Path:
    (directory / "fake_solver.py").write_text(_FAKE_SOLVER_PY, encoding="utf-8")
    exe = directory / "RasUnsteady"
    _write_executable(exe, (
        "#!/bin/bash\n"
        f"exec {shlex.quote(sys.executable)} "
        f"{shlex.quote(str(directory / 'fake_solver.py'))} \"$@\"\n"
    ))
    return exe


@pytest.fixture()
def muncie(tmp_path, monkeypatch):
    project = tmp_path / "Muncie"
    project.mkdir()
    plan = project / "Muncie.p04"
    plan.write_text("Plan Title=x\nGeom File=g04\n", encoding="utf-8")
    (project / "Muncie.b04").write_bytes(b"boundary\n")
    (project / "Muncie.x04").write_bytes(b"geometry\n")
    (project / "Muncie.c04").write_bytes(C_BYTES)
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    calls = {"set_num_cores": []}
    monkeypatch.setattr(rascmdr_module.RasPlan, "get_plan_path",
                        staticmethod(lambda plan_number, ras_object: plan))
    monkeypatch.setattr(rascmdr_module.RasPlan, "set_num_cores",
                        staticmethod(lambda path, num_cores, ras_object:
                                     calls["set_num_cores"].append(num_cores)))
    monkeypatch.setattr(rascmdr_module, "prepare_plan_execution_artifacts",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(rascmdr_module, "finalize_plan_execution_artifacts",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(RasCmdr, "_get_hdf_path",
                        staticmethod(lambda plan_number, ras_obj: project / "Muncie.p04.hdf"))
    monkeypatch.setattr(RasCmdr, "_effective_linux_core_count", staticmethod(lambda n: n))
    ras_obj = SimpleNamespace(project_folder=project, project_name="Muncie",
                              check_initialized=lambda: None)
    return SimpleNamespace(project=project, ras_obj=ras_obj, record=record, calls=calls)


def _run(muncie, install, **kwargs):
    return RasCmdr.compute_plan_linux("04", ras_exe_dir=install, ras_object=muncie.ras_obj,
                                      dos2unix=False, retry=False, **kwargs)


def _core_attrs(path):
    with h5py.File(path, "r") as hdf:
        params = hdf["Plan Data/Plan Parameters"].attrs
        return int(params["1D Cores"]), np.asarray(params["2D Cores (per mesh)"]).tolist()


@posix_linux_solver
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_compute_plan_linux_61_uses_cfile_arguments_and_canonical_libs(muncie, tmp_path):
    release = _make_61_install(tmp_path / "hec")
    _fake_ras_unsteady(release)
    tmp_hdf = muncie.project / "Muncie.p04.tmp.hdf"
    _plan_hdf(tmp_hdf, "HEC-RAS 6.1 September 2021")

    result = _run(muncie, release, num_cores=2)

    assert result.success is True
    record = json.loads(muncie.record.read_text())
    assert record["argv"] == ["Muncie.c04", "b04"]  # never the tmp.hdf / x04
    assert Path(record["cwd"]) == muncie.project
    libs = release.parent.parent / "libs"
    assert record["ld"] == ":".join(str(p) for p in (libs, libs / "mkl", libs / "rhel_8"))
    assert record["omp"] == "2"
    assert muncie.calls["set_num_cores"] == [2]
    final = muncie.project / "Muncie.p04.hdf"
    assert final.is_file() and not tmp_hdf.exists()
    # Compiled-HDF core attributes are not rewritten for pre-6.3.1 releases.
    assert _core_attrs(final) == (1, [1])
    assert (muncie.project / "Muncie.c04").read_bytes() == C_BYTES
    assert not list(muncie.project.glob("io.*"))


@posix_linux_solver
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_compute_plan_linux_66_keeps_tmphdf_arguments(muncie, tmp_path):
    install = tmp_path / "hec66"
    (install / "libs" / "mkl").mkdir(parents=True)
    (install / "libs" / "rhel_8").mkdir()
    _fake_ras_unsteady(install)
    (muncie.project / "Muncie.c04").unlink()  # not needed for 6.3.1+
    tmp_hdf = muncie.project / "Muncie.p04.tmp.hdf"
    _plan_hdf(tmp_hdf, "HEC-RAS 6.6 September 2024")

    result = _run(muncie, install, num_cores=3)

    assert result.success is True
    record = json.loads(muncie.record.read_text())
    assert record["argv"] == [str(tmp_hdf), "x04"]
    assert _core_attrs(muncie.project / "Muncie.p04.hdf") == (3, [3])


def test_compute_plan_linux_61_requires_non_empty_c_file(muncie, tmp_path):
    release = _make_61_install(tmp_path / "hec")
    _fake_ras_unsteady(release)
    _plan_hdf(muncie.project / "Muncie.p04.tmp.hdf", "HEC-RAS 6.1 September 2021")
    (muncie.project / "Muncie.c04").write_bytes(b"")
    with pytest.raises(FileNotFoundError, match=r"\.c04 \(empty\)"):
        _run(muncie, release)
    (muncie.project / "Muncie.c04").unlink()
    with pytest.raises(FileNotFoundError, match=r"cfile solver arguments\): \.c04"):
        _run(muncie, release)


def test_compute_plan_linux_bin_ras_refuses_modern_tmp_hdf(muncie, tmp_path):
    install = tmp_path / "hec507"
    (install / "bin_ras").mkdir(parents=True)
    _write_executable(install / "bin_ras" / "rasUnsteady64", "#!/bin/bash\nexit 99\n")
    _plan_hdf(muncie.project / "Muncie.p04.tmp.hdf", "HEC-RAS 6.6 September 2024")
    with pytest.raises(ValueError, match="runs only HEC-RAS 5.0.7"):
        _run(muncie, install)


# ---- WSL adapter -----------------------------------------------------------------

def _capture_wsl_script(monkeypatch, tmp_path, **kwargs):
    popen_calls = []

    class FakePopen:
        returncode = 1

        def __init__(self, args, **_kwargs):
            popen_calls.append(args)

        def communicate(self, timeout=None):
            return "", "ras failed"

        def kill(self):
            pass

    monkeypatch.setattr(RasCmdr, "_windows_path_to_wsl",
                        staticmethod(lambda path: f"/mnt/test/{Path(path).name}"))
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(rascmdr_module.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    RasCmdr._compute_plan_linux_via_wsl(
        ras_exe="/mnt/c/HEC-RAS/RasUnsteady", ras_exe_dir="/mnt/c/HEC-RAS",
        plan_number="01", geom_num="02", project_dir=tmp_path, project_name="Demo",
        tmp_hdf=tmp_path / "Demo.p01.tmp.hdf", timeout_sec=30, dos2unix=False,
        retry=False, retry_delay_sec=0,
        ras_obj=SimpleNamespace(project_folder=tmp_path, project_name="Demo"), **kwargs)
    return popen_calls[0][3]


def test_wsl_adapter_default_keeps_tmphdf_arguments(monkeypatch, tmp_path):
    script = _capture_wsl_script(monkeypatch, tmp_path)
    assert "/mnt/c/HEC-RAS/RasUnsteady /mnt/test/Demo.p01.tmp.hdf x02 >" in script


def test_wsl_adapter_cfile_arguments(monkeypatch, tmp_path):
    script = _capture_wsl_script(monkeypatch, tmp_path, solver_arguments="cfile")
    assert "/mnt/c/HEC-RAS/RasUnsteady Demo.c02 b01 >" in script
    assert "Demo.p01.tmp.hdf x02" not in script


def test_wsl_adapter_rejects_unknown_convention(tmp_path):
    with pytest.raises(ValueError, match="solver_arguments"):
        RasCmdr._compute_plan_linux_via_wsl(
            ras_exe="/mnt/c/HEC-RAS/RasUnsteady", ras_exe_dir="/mnt/c/HEC-RAS",
            plan_number="01", geom_num="02", project_dir=tmp_path, project_name="Demo",
            tmp_hdf=tmp_path / "Demo.p01.tmp.hdf", timeout_sec=30, dos2unix=False,
            retry=False, retry_delay_sec=0, ras_obj=None, solver_arguments="weird")


@pytest.mark.parametrize("version, expected, needs_c", [
    ("HEC-RAS 6.1 September 2021", "cfile", True),
    ("HEC-RAS 6.6 September 2024", "tmphdf", False),
])
def test_compute_plan_linux_wsl_passes_release_convention(monkeypatch, tmp_path,
                                                          version, expected, needs_c):
    plan_path = tmp_path / "Demo.p01"
    plan_path.write_text("Geom File=g01\n", encoding="utf-8")
    _plan_hdf(tmp_path / "Demo.p01.tmp.hdf", version)
    (tmp_path / "Demo.b01").write_bytes(b"boundary")
    (tmp_path / "Demo.x01").write_bytes(b"geometry")
    captured = {}
    monkeypatch.setattr(rascmdr_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(rascmdr_module.RasPlan, "get_plan_path",
                        staticmethod(lambda plan_number, ras_object: plan_path))
    monkeypatch.setattr(rascmdr_module.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(RasCmdr, "_compute_plan_linux_via_wsl",
                        staticmethod(lambda **kw: captured.update(kw) or
                                     rascmdr_module.ComputeResult(success=True)))
    ras_obj = SimpleNamespace(project_folder=tmp_path, project_name="Demo",
                              check_initialized=lambda: None)
    run = lambda: RasCmdr.compute_plan_linux(  # noqa: E731
        "01", ras_exe_dir="/mnt/c/HEC-RAS/Linux", ras_object=ras_obj, retry=False)
    if needs_c:
        with pytest.raises(FileNotFoundError, match=r"\.c01"):
            run()
        (tmp_path / "Demo.c01").write_bytes(C_BYTES)
    assert run().success is True
    assert captured["solver_arguments"] == expected
