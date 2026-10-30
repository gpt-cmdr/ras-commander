"""Offline tests for HEC-RAS 6.1 (canonical libs + pre-6.3.1 ``cfile`` arguments) in RasApptainer.

HEC's 6.1 Linux distribution ships ``RasUnsteady`` with a ``libs/`` tree (the canonical
library layout) but is invoked as ``RasUnsteady <proj>.c## b##`` like 5.0.7. The 6.1
tmp.hdf here is a small synthetic stand-in; the solver is a fake ``RasUnsteady``.
"""

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ras_commander import RasApptainer
from ras_commander.RasApptainer import (
    ApptainerProfileError,
    DEFAULT_HECRAS_DIR,
    DEFAULT_LD_LIBRARY_PATH,
    _validate_collected_solve,
    check_solver_ready,
)

FIXTURES = Path(__file__).parent / "fixtures" / "apptainer"
PROFILE = FIXTURES / "site_profile.json"
BASH = shutil.which("bash")
END_TIME = "03Jan1900 00:00:00"
C_BYTES = b"\x00\x01CGEOM61\r\n\x00\xff\r\n" * 16
FILE_VERSION_61 = b"HEC-RAS 6.1 September 2021"


def _profile_dict(**over):
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    data["ras_version"] = "6.1"
    data.update(over)
    return data


def _make_61_tmp_hdf(path: Path, *, completed: bool = True,
                     file_version: bytes = FILE_VERSION_61) -> None:
    import h5py
    import numpy as np

    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = np.bytes_(file_version)
        event = hdf.create_group("Event Conditions")
        if completed:
            event.attrs["Completed Successfully"] = True
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation End Time"] = np.bytes_(END_TIME.encode())
        params = hdf.create_group("Plan Data/Plan Parameters")
        params.attrs["1D Cores"] = np.int32(0)
        params.attrs["2D Cores (per mesh)"] = np.array([0], dtype=np.int32)
        area = hdf.create_group("Geometry/2D Flow Areas/Area1")
        # The solver reads property tables from the .c file; HDF placeholders are not checked.
        area.create_dataset("Cells Volume Elevation Values",
                            data=np.full((2, 2), np.nan, dtype="f4"))
        attrs = np.zeros(1, dtype=[("Name", "S16")])
        attrs["Name"] = b"Area1"
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)


@pytest.fixture()
def project61(tmp_path):
    folder = tmp_path / "proj61"
    folder.mkdir()
    (folder / "TEST.p08").write_bytes(b"Plan Title=x\r\nGeom File=g02\r\n")
    _make_61_tmp_hdf(folder / "TEST.p08.tmp.hdf")
    (folder / "TEST.b08").write_bytes(b"line1\r\nline2\r\n")
    (folder / "TEST.x02").write_bytes(b"xdata\r\n")
    (folder / "TEST.c02").write_bytes(C_BYTES)
    return folder


@pytest.fixture()
def profile61():
    return RasApptainer.profile_from_dict(_profile_dict())


# ---- profile ---------------------------------------------------------------

@pytest.mark.parametrize("version, layout, arguments", [
    ("5.0.7", "bin_ras", "cfile"),
    ("6.1", "canonical", "cfile"),
    ("6.5", "canonical", "tmphdf"),
    ("6.6", "canonical", "tmphdf"),
    ("7.0.1", "canonical", "tmphdf"),
])
def test_profile_derives_layout_and_arguments_from_release(version, layout, arguments):
    prof = RasApptainer.profile_from_dict(_profile_dict(ras_version=version))
    assert (prof.layout, prof.arguments) == (layout, arguments)
    assert "solver_arguments" not in prof.to_dict()
    assert "native_layout" not in prof.to_dict()


def test_61_profile_uses_canonical_library_defaults(profile61):
    assert profile61.hecras_dir == DEFAULT_HECRAS_DIR
    assert profile61.ld_library_path == DEFAULT_LD_LIBRARY_PATH


def test_solver_arguments_is_overridable_and_recorded():
    prof = RasApptainer.profile_from_dict(_profile_dict(ras_version="6.1", solver_arguments="tmphdf"))
    assert prof.arguments == "tmphdf" and prof.to_dict()["solver_arguments"] == "tmphdf"
    prof = RasApptainer.profile_from_dict(_profile_dict(ras_version="6.6", solver_arguments="cfile"))
    assert prof.arguments == "cfile"
    prof = RasApptainer.profile_from_dict(_profile_dict(ras_version="5.0.7", solver_arguments="cfile"))
    assert (prof.layout, prof.arguments) == ("bin_ras", "cfile")


@pytest.mark.parametrize("over, fragment", [
    ({"solver_arguments": "weird"}, "solver_arguments must be"),
    ({"ras_version": "5.0.7", "solver_arguments": "tmphdf"}, "not available for the bin_ras"),
    ({"geom_preprocess": True}, "only qualified for 'tmphdf'"),
    ({"ras_version": "6.6", "solver_arguments": "cfile", "geom_preprocess": True},
     "only qualified for 'tmphdf'"),
    ({"native_layout": "bin_ras"}, "uses 'canonical'"),
])
def test_profile_rejects_invalid_cfile_combinations(over, fragment):
    with pytest.raises(ApptainerProfileError, match=fragment):
        RasApptainer.profile_from_dict(_profile_dict(**over))


# ---- input check -------------------------------------------------------------

@pytest.mark.synthetic_hdf_layout
def test_check_solver_ready_relaxes_c_file_content_for_61(project61):
    assert check_solver_ready(project61 / "TEST.p08.tmp.hdf") == []


def test_check_solver_ready_still_requires_completion_flag_for_61(tmp_path):
    path = tmp_path / "x.tmp.hdf"
    _make_61_tmp_hdf(path, completed=False)
    problems = check_solver_ready(path)
    assert any("Completed Successfully" in p for p in problems)
    assert not any("GeomPreprocess" in p or "NaN" in p for p in problems)


@pytest.mark.synthetic_hdf_layout
def test_check_solver_ready_stays_strict_for_631(tmp_path):
    path = tmp_path / "x.tmp.hdf"
    _make_61_tmp_hdf(path, file_version=b"HEC-RAS 6.3.1 October 2022")
    problems = check_solver_ready(path)
    assert any("GeomPreprocess" in p for p in problems)
    assert any("NaN in Geometry/2D Flow Areas/Area1/Cells Volume Elevation Values" in p
               for p in problems)


# ---- rendering -----------------------------------------------------------------

@pytest.mark.synthetic_hdf_layout
def test_render_job_61_stages_c_file_and_canonical_cfile_engine(project61, profile61, tmp_path):
    source_hdf = (project61 / "TEST.p08.tmp.hdf").read_bytes()
    job = RasApptainer.render_job(project61, "TEST", 8, profile61, tmp_path / "job")
    inputs = job.job_directory / "inputs"
    assert (inputs / "TEST.c02").read_bytes() == C_BYTES
    assert (inputs / "TEST.b08").read_bytes() == b"line1\nline2\n"
    assert (inputs / "TEST.p08.tmp.hdf").read_bytes() == source_hdf  # cores not rewritten
    manifest = (inputs / "SHA256SUMS").read_text(encoding="utf-8")
    assert f"{hashlib.sha256(C_BYTES).hexdigest()}  TEST.c02" in manifest

    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert "XTOKEN=x02\nCTOKEN=c02\n" in engine
    assert '"$HECRAS/RasUnsteady" "$PROJECT.$CTOKEN" "b$PLAN" > solver.log 2>&1 &' in engine
    assert '"$PROJECT.p$PLAN.tmp.hdf" "$XTOKEN"' not in engine
    assert "rasUnsteady64" not in engine and "RasGeomPreprocess" not in engine
    assert f"HECRAS={DEFAULT_HECRAS_DIR}\n" in engine
    assert f"export LD_LIBRARY_PATH={':'.join(DEFAULT_LD_LIBRARY_PATH)}\n" in engine
    assert 'mv "$PROJECT.p$PLAN.tmp.hdf" "$PROJECT.p$PLAN.hdf"' in engine

    meta = json.loads((job.job_directory / "job.json").read_text(encoding="utf-8"))
    request = meta["request"]
    assert request["native_layout"] == "canonical"
    assert request["solver_arguments"] == "cfile" and request["ctoken"] == "c02"
    assert "TEST.c02" in request["input_hashes"]
    assert meta["core_evidence"]["skipped"].startswith("cfile (HEC-RAS 6.1)")


def test_render_job_61_requires_non_empty_c_file(project61, profile61, tmp_path):
    (project61 / "TEST.c02").write_bytes(b"")
    with pytest.raises(ValueError, match="empty; the HEC-RAS 6.1 solver"):
        RasApptainer.render_job(project61, "TEST", 8, profile61, tmp_path / "job1")
    (project61 / "TEST.c02").unlink()
    with pytest.raises(FileNotFoundError, match="TEST.c02"):
        RasApptainer.render_job(project61, "TEST", 8, profile61, tmp_path / "job2")


def test_render_job_rejects_argument_convention_mismatch(project61, profile61, tmp_path):
    modern = RasApptainer.profile_from_dict(_profile_dict(ras_version="6.6"))
    with pytest.raises(ValueError, match="'cfile' arguments; profile ras_version 6.6"):
        RasApptainer.render_job(project61, "TEST", 8, modern, tmp_path / "job1")
    _make_61_tmp_hdf(project61 / "TEST.p08.tmp.hdf", file_version=b"HEC-RAS 6.6 September 2024")
    with pytest.raises(ValueError, match="'tmphdf' arguments; profile ras_version 6.1"):
        RasApptainer.render_job(project61, "TEST", 8, profile61, tmp_path / "job2",
                                check_inputs=False)


def test_render_job_rejects_5x_hdf_on_61_profile(project61, profile61, tmp_path):
    _make_61_tmp_hdf(project61 / "TEST.p08.tmp.hdf", file_version=b"HEC-RAS 5.0.7 March 2019")
    with pytest.raises(ValueError, match="Use ras_version '5.0.7'"):
        RasApptainer.render_job(project61, "TEST", 8, profile61, tmp_path / "job")


# ---- execution (fake solver) -------------------------------------------------------

_FAKE_SOLVER_PY = r'''
import sys, h5py, numpy as np
assert sys.argv[1:] == ["TEST.c02", "b08"], sys.argv
with open("TEST.c02", "rb") as fh:
    assert fh.read() == bytes.fromhex("@CHEX@")
with h5py.File("TEST.p08.tmp.hdf", "r+") as hdf:
    base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
    hdf.create_dataset(base + "/Time Date Stamp",
                       data=np.array([b"02JAN1900 00:00:00", b"03JAN1900 00:00:00"]))
    hdf.create_dataset(base + "/2D Flow Areas/Area1/Water Surface", data=np.ones((2, 2)))
print("Finished Unsteady Flow Simulation")
'''


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


posix_site_profile = pytest.mark.skipif(
    os.name == "nt", reason="Apptainer site profiles require absolute POSIX paths (tmp_path is not)"
)


@posix_site_profile
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_rendered_61_engine_runs_cfile_and_promotes_tmp_hdf(project61, profile61, tmp_path):
    engine_dir = tmp_path / "engine"
    (engine_dir / "libs" / "mkl").mkdir(parents=True)
    (engine_dir / "fake_solver.py").write_text(
        _FAKE_SOLVER_PY.replace("@CHEX@", C_BYTES.hex()), encoding="utf-8")
    ld = f"{engine_dir}/libs:{engine_dir}/libs/mkl"
    _write_executable(engine_dir / "RasUnsteady", (
        "#!/bin/bash\n"
        f'[ "$LD_LIBRARY_PATH" = {shlex.quote(ld)} ] || {{ echo "bad LD_LIBRARY_PATH"; exit 9; }}\n'
        '[ "$OMP_NUM_THREADS" = 4 ] || { echo "bad OMP_NUM_THREADS"; exit 9; }\n'
        '[ -L io.b ] && [ -L io.c02 ] || { echo "missing io links"; exit 9; }\n'
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(engine_dir / "fake_solver.py"))} "$@"\n'
    ))
    prof = replace(profile61, hecras_dir=str(engine_dir),
                   ld_library_path=(f"{engine_dir}/libs", f"{engine_dir}/libs/mkl"),
                   stack_unlimited=False)
    job = RasApptainer.render_job(project61, "TEST", 8, prof, tmp_path / "job")
    work = tmp_path / "work"
    shutil.copytree(job.job_directory / "inputs", work)
    (work / "SHA256SUMS").unlink()
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    script = tmp_path / "engine.local.sh"
    script.write_text(engine.replace("cd /job || exit 1", f"cd {shlex.quote(str(work))} || exit 1"),
                      encoding="utf-8")
    done = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False)
    log = (work / "solver.log").read_text(encoding="utf-8")
    assert done.returncode == 0, (done.stdout, done.stderr, log)
    assert (work / "TEST.p08.hdf").is_file() and not (work / "TEST.p08.tmp.hdf").exists()
    assert not list(work.glob("io.*"))

    dest = tmp_path / "collected"
    (dest / "project").mkdir(parents=True)
    shutil.copy2(work / "TEST.p08.hdf", dest / "project" / "TEST.p08.hdf")
    shutil.copy2(work / "solver.log", dest / "project" / "solver.log")
    assert _validate_collected_solve(dest, job, END_TIME) is None
