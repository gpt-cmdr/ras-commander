"""Offline tests for the HEC-RAS 5.0.7 ``bin_ras`` native layout in RasApptainer.

The 5.0.7 tmp.hdf here is a small synthetic stand-in shaped like a Windows 5.0.7
preprocessing output (File Version 'HEC-RAS 5.0.7 March 2019', no Completed
Successfully, no /Geometry/GeomPreprocess). The solver is a fake ``rasUnsteady64``;
these tests qualify rendering, staging and orchestration only, never HEC-RAS itself.
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
    DEFAULT_LD_LIBRARY_PATH,
    InputCheckError,
    _validate_collected_solve,
    check_solver_ready,
)

FIXTURES = Path(__file__).parent / "fixtures" / "apptainer"
PROFILE = FIXTURES / "site_profile.json"
BASH = shutil.which("bash")
END_TIME = "03Jan1900 00:00:00"
# Binary computed geometry: CRLF and NUL bytes must survive staging untouched.
C_BYTES = b"\x00\x01CGEOM\r\n\x00\xff\r\n\x1a binary \r\n" * 16


def _profile_dict(**over):
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    data["ras_version"] = "5.0.7"
    data.update(over)
    return data


def _make_507_tmp_hdf(path: Path, *, nan_table: bool = True) -> None:
    import h5py
    import numpy as np

    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = np.bytes_(b"HEC-RAS 5.0.7 March 2019")
        hdf.create_group("Event Conditions")  # 5.x never writes Completed Successfully
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation End Time"] = np.bytes_(END_TIME.encode())
        params = hdf.create_group("Plan Data/Plan Parameters")
        params.attrs["1D Cores"] = np.int32(0)
        params.attrs["2D Cores"] = np.int32(0)
        area = hdf.create_group("Geometry/2D Flow Areas/Area1")
        area.create_dataset("Cells Minimum Elevation", data=np.array([1.0, np.nan], dtype="f4"))
        if nan_table:
            # In 5.0.7 the real property tables are in the .c file; HDF placeholders are not checked.
            area.create_dataset("Cells Volume Elevation Values",
                                data=np.full((2, 2), np.nan, dtype="f4"))
        attrs = np.zeros(1, dtype=[("Name", "S16")])
        attrs["Name"] = b"Area1"
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)


@pytest.fixture()
def project507(tmp_path):
    folder = tmp_path / "proj507"
    folder.mkdir()
    (folder / "TEST.p08").write_bytes(b"Plan Title=x\r\nGeom File=g02\r\n")
    _make_507_tmp_hdf(folder / "TEST.p08.tmp.hdf")
    (folder / "TEST.b08").write_bytes(b"line1\r\nline2\r\n")
    (folder / "TEST.x02").write_bytes(b"xdata\r\n")
    (folder / "TEST.c02").write_bytes(C_BYTES)
    return folder


@pytest.fixture()
def profile507():
    return RasApptainer.profile_from_dict(_profile_dict())


# ---- profile ---------------------------------------------------------------

def test_profile_accepts_507_and_derives_bin_ras_layout(profile507):
    assert profile507.ras_version == "5.0.7"
    assert profile507.native_layout is None and profile507.layout == "bin_ras"
    assert profile507.hecras_dir == "/opt/hecras-runtime/engine/bin_ras"
    assert profile507.ld_library_path == ("/opt/hecras-runtime/engine/bin_ras",)
    assert "native_layout" not in profile507.to_dict()
    explicit = RasApptainer.profile_from_dict(_profile_dict(native_layout="bin_ras"))
    assert explicit.layout == "bin_ras" and explicit.to_dict()["native_layout"] == "bin_ras"
    moved = RasApptainer.profile_from_dict(_profile_dict(hecras_dir="/opt/ras507/bin_ras"))
    assert moved.ld_library_path == ("/opt/ras507/bin_ras",)
    custom = RasApptainer.profile_from_dict(_profile_dict(ld_library_path=["/opt/x", "/opt/y"]))
    assert custom.ld_library_path == ("/opt/x", "/opt/y")


def test_canonical_profile_defaults_unchanged():
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    prof = RasApptainer.profile_from_dict(data)
    assert prof.layout == "canonical" and prof.ld_library_path == DEFAULT_LD_LIBRARY_PATH
    assert "native_layout" not in prof.to_dict()
    assert RasApptainer.profile_from_dict({**data, "native_layout": "canonical"}).layout == "canonical"


@pytest.mark.parametrize("over, fragment", [
    ({"geom_preprocess": True}, "no RasGeomPreprocess"),
    ({"native_layout": "bin_ras", "geom_preprocess": True}, "no RasGeomPreprocess"),
    ({"native_layout": "canonical"}, "ships only the 'bin_ras'"),
    ({"native_layout": "weird"}, "native_layout must be"),
    ({"ras_version": "6.6", "native_layout": "bin_ras"}, "uses 'canonical'"),
    ({"ras_version": "5.0.6"}, "no HEC Linux engine"),
])
def test_profile_rejects_invalid_bin_ras_combinations(over, fragment):
    with pytest.raises(ApptainerProfileError, match=fragment):
        RasApptainer.profile_from_dict(_profile_dict(**over))


# ---- input check -------------------------------------------------------------

def test_check_solver_ready_is_5x_aware(project507):
    problems = check_solver_ready(project507 / "TEST.p08.tmp.hdf")
    assert problems == []
    assert not any("GeomPreprocess" in p or "Completed" in p or "NaN" in p for p in problems)


def test_check_solver_ready_still_strict_for_6x(project507):
    import h5py
    import numpy as np

    path = project507 / "TEST.p08.tmp.hdf"
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["File Version"] = np.bytes_(b"HEC-RAS 6.6 September 2024")
    problems = check_solver_ready(path)
    assert any("Completed Successfully" in p for p in problems)
    assert any("GeomPreprocess" in p for p in problems)
    assert any("NaN in Geometry/2D Flow Areas/Area1/Cells Volume Elevation Values" in p
               for p in problems)


# ---- rendering -----------------------------------------------------------------

def test_render_job_stages_c_file_verbatim_and_bin_ras_engine(project507, profile507, tmp_path):
    source_hdf = (project507 / "TEST.p08.tmp.hdf").read_bytes()
    job = RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "job")
    inputs = job.job_directory / "inputs"
    assert (inputs / "TEST.c02").read_bytes() == C_BYTES  # binary: never LF-converted
    assert (inputs / "TEST.b08").read_bytes() == b"line1\nline2\n"
    assert (inputs / "TEST.x02").read_bytes() == b"xdata\n"
    # Core attributes are not rewritten for 5.0.7: staged tmp.hdf is byte-identical.
    assert (inputs / "TEST.p08.tmp.hdf").read_bytes() == source_hdf
    manifest = (inputs / "SHA256SUMS").read_text(encoding="utf-8")
    assert f"{hashlib.sha256(C_BYTES).hexdigest()}  TEST.c02" in manifest

    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert "XTOKEN=x02\nCTOKEN=c02\n" in engine
    assert '"$HECRAS/rasUnsteady64" "$PROJECT.$CTOKEN" "b$PLAN" > solver.log 2>&1 &' in engine
    assert '[ -x "$HECRAS/rasUnsteady64" ]' in engine
    assert "HECRAS=/opt/hecras-runtime/engine/bin_ras\nexport LD_LIBRARY_PATH=/opt/hecras-runtime/engine/bin_ras\n" in engine
    assert '"$HECRAS/RasUnsteady"' not in engine and "RasGeomPreprocess" not in engine
    assert "Finished Unsteady Flow Simulation" in engine
    assert 'mv "$PROJECT.p$PLAN.tmp.hdf" "$PROJECT.p$PLAN.hdf"' in engine

    meta = json.loads((job.job_directory / "job.json").read_text(encoding="utf-8"))
    request = meta["request"]
    assert request["native_layout"] == "bin_ras" and request["ctoken"] == "c02"
    assert request["expected_simulation_end"] == END_TIME
    assert "TEST.c02" in request["input_hashes"]
    assert meta["core_evidence"]["skipped"].startswith("bin_ras")
    assert (project507 / "TEST.c02").read_bytes() == C_BYTES  # source untouched


def test_render_job_requires_non_empty_c_file(project507, profile507, tmp_path):
    (project507 / "TEST.c02").write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "job1")
    (project507 / "TEST.c02").unlink()
    with pytest.raises(FileNotFoundError, match="TEST.c02"):
        RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "job2")


def test_render_job_rejects_layout_and_hdf_version_mismatch(project507, profile507, tmp_path):
    canonical = RasApptainer.profile_from_dict(json.loads(PROFILE.read_text(encoding="utf-8")))
    with pytest.raises(ValueError, match="HEC-RAS 5.x"):
        RasApptainer.render_job(project507, "TEST", 8, canonical, tmp_path / "job1")
    import h5py
    import numpy as np
    with h5py.File(project507 / "TEST.p08.tmp.hdf", "r+") as hdf:
        hdf.attrs["File Version"] = np.bytes_(b"HEC-RAS 6.6 September 2024")
    with pytest.raises(ValueError, match="does not identify HEC-RAS 5.x"):
        RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "job2",
                                check_inputs=False)


def test_render_job_input_check_still_applies_to_507(project507, profile507, tmp_path):
    import h5py
    with h5py.File(project507 / "TEST.p08.tmp.hdf", "r+") as hdf:
        del hdf["Event Conditions"]
    with pytest.raises(InputCheckError, match="Event Conditions"):
        RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "job")


# ---- execution (fake solver, fake apptainer) ----------------------------------------

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


def _fake_engine_dir(root: Path) -> Path:
    engine = root / "engine"
    engine.mkdir()
    (engine / "fake_solver.py").write_text(
        _FAKE_SOLVER_PY.replace("@CHEX@", C_BYTES.hex()), encoding="utf-8")
    _write_executable(engine / "rasUnsteady64", (
        "#!/bin/bash\n"
        f'[ "$LD_LIBRARY_PATH" = {shlex.quote(str(engine))} ] || {{ echo "bad LD_LIBRARY_PATH=$LD_LIBRARY_PATH"; exit 9; }}\n'
        '[ "$OMP_NUM_THREADS" = 4 ] || { echo "bad OMP_NUM_THREADS"; exit 9; }\n'
        '[ -L io.b ] && [ -L io.c02 ] || { echo "missing io links"; exit 9; }\n'
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(engine / "fake_solver.py"))} "$@"\n'
    ))
    return engine


# Stand-in for ``apptainer exec``: runs engine.sh with /job mapped to the bound work dir.
_FAKE_APPTAINER = r'''#!/bin/bash
work=""; control=""
while [ $# -gt 0 ]; do
  case "$1" in
    exec|--cleanenv) shift ;;
    --pwd) shift 2 ;;
    --bind) case "$2" in *:/job) work=${2%:/job} ;; *:/control:ro) control=${2%:/control:ro} ;; esac; shift 2 ;;
    *) break ;;
  esac
done
shift  # image
[ "$1 $2" = "bash /control/engine.sh" ] || { echo "unexpected exec: $*" >&2; exit 97; }
sed "s#^cd /job #cd \"$work\" #" "$control/engine.sh" > "$control/../engine.local.sh"
exec bash "$control/../engine.local.sh"
'''


posix_site_profile = pytest.mark.skipif(
    os.name == "nt", reason="Apptainer site profiles require absolute POSIX paths (tmp_path is not)"
)


@posix_site_profile
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_rendered_bin_ras_engine_runs_and_promotes_tmp_hdf(project507, profile507, tmp_path):
    engine_dir = _fake_engine_dir(tmp_path)
    prof = replace(profile507, hecras_dir=str(engine_dir), ld_library_path=(str(engine_dir),),
                   stack_unlimited=False)
    job = RasApptainer.render_job(project507, "TEST", 8, prof, tmp_path / "job")
    work = tmp_path / "work"
    shutil.copytree(job.job_directory / "inputs", work)
    (work / "SHA256SUMS").unlink()
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert "cd /job || exit 1" in engine
    script = tmp_path / "engine.local.sh"
    script.write_text(engine.replace("cd /job || exit 1", f"cd {shlex.quote(str(work))} || exit 1"),
                      encoding="utf-8")
    done = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False)
    log = (work / "solver.log").read_text(encoding="utf-8")
    assert done.returncode == 0, (done.stdout, done.stderr, log)
    assert (work / "TEST.p08.hdf").is_file() and not (work / "TEST.p08.tmp.hdf").exists()
    assert not list(work.glob("io.*"))
    assert (work / "TEST.c02").read_bytes() == C_BYTES

    # The 5.0.7 result HDF passes the same collection validation as 6.x.
    dest = tmp_path / "collected"
    (dest / "project").mkdir(parents=True)
    shutil.copy2(work / "TEST.p08.hdf", dest / "project" / "TEST.p08.hdf")
    shutil.copy2(work / "solver.log", dest / "project" / "solver.log")
    assert _validate_collected_solve(dest, job, END_TIME) is None


@posix_site_profile
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_bin_ras_engine_fails_clearly_without_executable_solver(project507, profile507, tmp_path):
    engine_dir = tmp_path / "empty-engine"
    engine_dir.mkdir()
    prof = replace(profile507, hecras_dir=str(engine_dir), ld_library_path=(str(engine_dir),),
                   stack_unlimited=False)
    job = RasApptainer.render_job(project507, "TEST", 8, prof, tmp_path / "job")
    work = tmp_path / "work"
    shutil.copytree(job.job_directory / "inputs", work)
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    script = tmp_path / "engine.local.sh"
    script.write_text(engine.replace("cd /job || exit 1", f"cd {shlex.quote(str(work))} || exit 1"),
                      encoding="utf-8")
    done = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False)
    assert done.returncode == 6
    assert "rasUnsteady64 is missing or not executable" in done.stderr


@posix_site_profile
@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_bin_ras_job_end_to_end_with_fake_apptainer_and_collect(project507, profile507, tmp_path):
    from test_apptainer_execution import FakeTransport, SACCT_DONE

    root = tmp_path / "site"
    root.mkdir()
    engine_dir = _fake_engine_dir(root)
    image = root / "image.sif"
    image.write_bytes(b"fake 5.0.7 native image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    apptainer = root / "apptainer"
    _write_executable(apptainer, _FAKE_APPTAINER)
    prof = replace(
        profile507, scratch_root=str(root / "remote"), node_scratch_root=str(root / "node"),
        image=str(image), apptainer_image_sha256=digest, container_identity=f"sif:sha256:{digest}",
        apptainer_executable=str(apptainer), hecras_dir=str(engine_dir),
        ld_library_path=(str(engine_dir),), stack_unlimited=False,
    )
    job = RasApptainer.render_job(project507, "TEST", 8, prof, tmp_path / "job")
    remote = Path(job.remote_directory)
    remote.mkdir(parents=True)
    shutil.copytree(job.job_directory, remote, dirs_exist_ok=True)
    done = subprocess.run([BASH, str(remote / "job.sh")], env={**os.environ, "SLURM_JOB_ID": "4242"},
                          capture_output=True, text=True, check=False)
    out = remote / "out" / "4242"
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    engine_log = (out / "logs" / "engine.log")
    assert done.returncode == 0, (receipt, engine_log.read_text() if engine_log.exists() else None)
    assert receipt["status"] == "succeeded" and receipt["reason_code"] == "COMPLETED"
    assert "project/TEST.p08.hdf" in receipt["outputs"]
    assert "TEST.c02" in receipt["input_hashes"]

    transport = FakeTransport(sacct=SACCT_DONE)
    transport.remote_out = out
    submitted = replace(job, state="SUBMITTED", slurm_job_id="4242")
    collection = RasApptainer.collect(submitted, transport, prof, destination=tmp_path / "collected")
    assert collection.success, collection.problems
