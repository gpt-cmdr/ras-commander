"""Offline tests for the Wine prepare stage of RasApptainer.

The rendered prepare ``job.sh`` is executed with Bash against a fake
``apptainer`` that stands in for Wine preprocessing, so staging, hash checks,
copy-back, and ``SHA256SUMS`` are exercised for real. No HEC-RAS, Wine,
Apptainer, or Slurm is required.
"""

from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ras_commander import RasApptainer
from ras_commander.RasApptainer import (
    PREPARE_JOB_SCHEMA,
    ApptainerProfileError,
    ApptainerTransport,
    CommandResult,
)
from ras_commander.remote import apptainer_prepare

FIXTURES = Path(__file__).parent / "fixtures" / "apptainer"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs POSIX bash")

FAKE_APPTAINER = r"""#!/bin/bash
# Fake 'apptainer exec': emulate Wine preprocessing inside the bound /job.
set -eu
WORK=""; REQUEST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bind) case "$2" in *:/job) WORK=${2%:/job} ;; esac; shift 2 ;;
    --request-sha256) REQUEST=$2; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "${FAKE_PREPARE_FAIL:-}" ] && { echo "wine failed" >&2; exit 1; }
cd "$WORK"
rm -f TEST.c99  # stale geometry preprocessing removed by the preparation
printf 'compiled' > TEST.p08.tmp.hdf
printf 'b-file\n' > TEST.b08
printf 'x-file\n' > TEST.x02
printf 'Plan Title=x\nGeom File=g02\nUNET D2 Cores= 4\n' > TEST.p08
sha() { sha256sum "$1" | cut -d' ' -f1; }
cat > .prepare_receipt.json <<JSON
{"schema": "ras-commander-apptainer-prepare-receipt/v1", "request_sha256": "$REQUEST",
 "status": "succeeded", "reason_code": "COMPLETED", "detail": "",
 "outputs": {"TEST.p08.tmp.hdf": {"sha256": "$(sha TEST.p08.tmp.hdf)", "size_bytes": 8},
             "TEST.b08": {"sha256": "$(sha TEST.b08)", "size_bytes": 7},
             "TEST.x02": {"sha256": "$(sha TEST.x02)", "size_bytes": 7}}}
JSON
"""


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "proj"
    (folder / "Terrain").mkdir(parents=True)
    (folder / "TEST.prj").write_text("Proj Title=test\n")
    (folder / "TEST.p08").write_bytes(b"Plan Title=x\r\nGeom File=g02\r\n")
    (folder / "TEST.g02").write_text("Geom Title=g\n")
    (folder / "Terrain" / "Terrain 1m.hdf").write_bytes(b"terrain")
    return folder


@pytest.fixture()
def site(tmp_path):
    root = tmp_path / "cluster"
    image = root / "images" / "wine.sif"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"wine executor sif")
    (root / "node").mkdir()
    bin_dir = root / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "apptainer"
    fake.write_text(FAKE_APPTAINER)
    fake.chmod(0o755)
    data = json.loads((FIXTURES / "site_profile.json").read_text())
    data.update({
        "scratch_root": str(root / "jobs"),
        "node_scratch_root": str(root / "node"),
        "apptainer_executable": str(fake),
        "prepare_image": str(image),
        "prepare_image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    })
    return RasApptainer.profile_from_dict(data)


class ClusterTransport(ApptainerTransport):
    """Run the staged prepare job locally and report it COMPLETED to sacct."""

    def __init__(self, env=None):
        self.env = env or {}
        self.job_rc = None

    def run(self, argv, timeout=None):
        argv = list(argv)
        if argv[0] == "sbatch":
            env = dict(os.environ, SLURM_JOB_ID="4242", **self.env)
            done = subprocess.run([BASH, argv[-1]], env=env, capture_output=True, text=True)
            self.job_rc = done.returncode
            return CommandResult(0, "4242\n")
        if argv[0] == "sacct":
            state = "COMPLETED" if self.job_rc == 0 else "FAILED"
            return CommandResult(0, f"4242|{state}|{self.job_rc}:0|00:01:00|node01\n")
        if argv[:2] == ["bash", "-c"]:
            done = subprocess.run([BASH, "-c", argv[2]], capture_output=True, text=True)
            return CommandResult(done.returncode, done.stdout, done.stderr)
        if argv[0] == "mkdir":
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        return CommandResult(0)

    def put_tree(self, local_dir, remote_dir):
        shutil.copytree(local_dir, remote_dir, dirs_exist_ok=True)

    def get_tree(self, remote_dir, local_dir):
        shutil.copytree(remote_dir, local_dir)


def test_render_prepare_job_stages_the_complete_project(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")

    assert job.kind == "prepare" and job.geometry_token == "x02"
    sums = (job.job_directory / "inputs" / "SHA256SUMS").read_text()
    assert "  Terrain/Terrain 1m.hdf\n" in sums
    request = json.loads((job.job_directory / "job.json").read_text())["request"]
    assert request["schema"] == PREPARE_JOB_SCHEMA
    assert request["ras_executable"] == r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe"
    script = job.script_path.read_text()
    assert "exec --contain --cleanenv" in script
    assert '--bind "$SCRATCH/tmp:/tmp"' in script
    assert "-m ras_commander.remote.apptainer_prepare prepare" in script
    assert f"REQUEST_SHA256={job.request_sha256}" in script
    assert subprocess.run([BASH, "-n", str(job.script_path)]).returncode == 0


def test_render_prepare_job_requires_prepare_image(project, site, tmp_path):
    plain = replace(site, prepare_image=None, prepare_image_sha256=None)
    with pytest.raises(ApptainerProfileError, match="prepare_image"):
        RasApptainer.render_prepare_job(project, "TEST", 8, plain, tmp_path / "job")


def test_render_prepare_job_rejects_unsafe_project_paths(project, site, tmp_path):
    (project / "bad\\name.txt").write_text("x")
    with pytest.raises(ValueError, match="Unsupported project path"):
        RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")


def test_prepare_job_runs_and_collects_a_prepared_project(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    transport = ClusterTransport()
    job = RasApptainer.submit(job, transport, site, dry_run=False)
    assert transport.job_rc == 0

    prepared = tmp_path / "prepared"
    result = RasApptainer.collect_prepare(job, transport, site, prepared)

    assert result.success, result.problems
    assert result.project_folder == prepared
    assert (prepared / "TEST.p08.tmp.hdf").read_bytes() == b"compiled"
    assert (prepared / "TEST.x02").is_file() and (prepared / "TEST.b08").is_file()
    assert "UNET D2 Cores" in (prepared / "TEST.p08").read_text()
    assert (prepared / "Terrain" / "Terrain 1m.hdf").read_bytes() == b"terrain"
    assert not (prepared / "SHA256SUMS").exists()
    # Unchanged inputs are not copied back from the cluster.
    assert not (result.directory / "project" / "TEST.g02").exists()
    # Source project is never modified.
    assert (project / "TEST.p08").read_bytes() == b"Plan Title=x\r\nGeom File=g02\r\n"
    assert not (Path(site.node_scratch_root) / "4242" / "ras-prepare").exists()


def test_failed_prepare_is_collected_without_a_prepared_project(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    transport = ClusterTransport(env={"FAKE_PREPARE_FAIL": "1"})
    job = RasApptainer.submit(job, transport, site, dry_run=False)
    assert transport.job_rc == 1

    result = RasApptainer.collect_prepare(job, transport, site, tmp_path / "prepared")

    assert not result.success and result.project_folder is None
    assert any("PREPARE_FAILED" in problem for problem in result.problems)
    assert (result.directory / "logs" / "prepare.log").read_text().strip() == "wine failed"
    # Failed scratch is retained for diagnosis.
    assert (Path(site.node_scratch_root) / "4242" / "ras-prepare").is_dir()


def test_collect_prepare_detects_tampered_artifact(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    transport = ClusterTransport()
    job = RasApptainer.submit(job, transport, site, dry_run=False)
    remote = Path(f"{job.remote_directory}/out/4242")
    (remote / "project" / "TEST.b08").write_text("tampered")

    result = RasApptainer.collect_prepare(job, transport, site, tmp_path / "prepared")

    assert not result.success and result.project_folder is None
    assert any("TEST.b08" in problem for problem in result.problems)


def test_collect_and_collect_prepare_reject_the_other_job_kind(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    transport = ClusterTransport()
    job = RasApptainer.submit(job, transport, site, dry_run=False)
    with pytest.raises(ValueError, match="collect_prepare"):
        RasApptainer.collect(job, transport, site)
    with pytest.raises(ValueError, match="render_prepare_job"):
        RasApptainer.collect_prepare(replace(job, kind="solve"), transport, site, tmp_path / "p")


# ---- in-container prepare module ----------------------------------------

def _fake_wine_tools(tmp_path, monkeypatch, worker_payload, artifacts=True):
    seed = tmp_path / "seed" / "prefix"
    (seed / "dosdevices").mkdir(parents=True)
    os.symlink("/", seed / "dosdevices" / "z:")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", r"C:\Python311\python.exe")
    monkeypatch.delenv("RAS_COMMANDER_WINE_CPU_SHIM", raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(apptainer_prepare.tempfile, "gettempdir", lambda: str(runtime))
    wine = importlib.import_module("ras_commander.remote.execute_request")
    monkeypatch.setattr(wine.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs.get("env", {})))
        if command[0].endswith("xvfb-run"):
            result = Path("/" + command[command.index("--result") + 1][3:].replace("\\", "/"))
            result.write_text(json.dumps(worker_payload))
            if artifacts:
                folder = tmp_path / "job"
                (folder / "TEST.p08.tmp.hdf").write_bytes(b"compiled")
                (folder / "TEST.b08").write_text("b")
                (folder / "TEST.x02").write_text("x")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(apptainer_prepare.subprocess, "run", run)
    monkeypatch.setattr(wine.subprocess, "run", run)
    monkeypatch.setattr(
        sys.modules["ras_commander.RasApptainer"], "check_solver_ready", lambda path: []
    )
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "TEST.prj").write_text("Proj Title=test\n")
    (folder / "TEST.p08").write_text("Plan Title=x\nGeom File=g02\n")
    return folder / "TEST.prj", runtime, calls


def _prepare(project_file, tmp_path):
    receipt = tmp_path / "receipt.json"
    code = apptainer_prepare.main([
        "prepare", "--project", str(project_file), "--plan", "08", "--num-cores", "4",
        "--timeout", "600", "--ras-executable", r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
        "--request-sha256", "a" * 64, "--receipt", str(receipt),
    ])
    return code, json.loads(receipt.read_text())


def test_prepare_module_runs_windows_worker_in_private_prefix(tmp_path, monkeypatch):
    project_file, runtime, calls = _fake_wine_tools(tmp_path, monkeypatch, {"success": True})

    code, receipt = _prepare(project_file, tmp_path)

    assert code == 0, receipt
    assert receipt["status"] == "succeeded" and receipt["request_sha256"] == "a" * 64
    assert set(receipt["outputs"]) == {"TEST.p08.tmp.hdf", "TEST.b08", "TEST.x02"}
    command, env = calls[0]
    assert command[:2] == ["/usr/bin/xvfb-run", "-n"] and command[2].isdigit()
    assert command[3:5] == ["/usr/bin/wine", r"C:\Python311\python.exe"]
    assert command[command.index("--project") + 1].startswith("Z:\\")
    assert command[command.index("--num-cores") + 1] == "4"
    assert env["WINEPREFIX"].startswith(str(runtime)) and "winedbg.exe=d" in env["WINEDLLOVERRIDES"]
    assert list(runtime.iterdir()) == []  # private prefix removed


def test_prepare_module_records_worker_failure(tmp_path, monkeypatch):
    project_file, _, _ = _fake_wine_tools(
        tmp_path, monkeypatch, {"success": False, "error": "RasProcess.exe crashed"}, artifacts=False
    )

    code, receipt = _prepare(project_file, tmp_path)

    assert code == 1
    assert receipt["status"] == "failed" and receipt["detail"] == "RasProcess.exe crashed"


def test_prepare_module_rejects_missing_wine_environment(tmp_path, monkeypatch):
    project_file, _, calls = _fake_wine_tools(tmp_path, monkeypatch, {"success": True})
    monkeypatch.delenv("RAS_COMMANDER_WINE_PREFIX_SEED")

    code, receipt = _prepare(project_file, tmp_path)

    assert code == 1 and calls == []
    assert "RAS_COMMANDER_WINE_PREFIX_SEED" in receipt["detail"]


def test_prepare_returns_unchanged_artifacts_drops_deleted_and_keeps_nested_manifests(
    project, site, tmp_path
):
    # A re-prepared project already holds byte-identical artifacts and a stale file.
    (project / "TEST.x02").write_text("x-file\n")
    (project / "TEST.c99").write_text("stale")
    (project / "Terrain" / "SHA256SUMS").write_text("vendor manifest\n")
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    transport = ClusterTransport()
    job = RasApptainer.submit(job, transport, site, dry_run=False)

    result = RasApptainer.collect_prepare(job, transport, site, tmp_path / "prepared")

    assert result.success, result.problems
    assert (result.directory / "project" / "TEST.x02").is_file()
    assert (result.directory / "deleted_inputs.txt").read_text() == "TEST.c99\n"
    assert not (tmp_path / "prepared" / "TEST.c99").exists()
    assert (tmp_path / "prepared" / "Terrain" / "SHA256SUMS").read_text() == "vendor manifest\n"
    assert (project / "TEST.c99").exists()


def test_prepare_submit_rejects_placeholder_prepare_digest(project, site, tmp_path):
    placeholder = replace(site, prepare_image_sha256="0" * 64)
    job = RasApptainer.render_prepare_job(project, "TEST", 8, placeholder, tmp_path / "job")
    with pytest.raises(ApptainerProfileError, match="all-zero"):
        RasApptainer.submit(job, ClusterTransport(), placeholder, dry_run=False)


def test_cfile_release_prepare_returns_and_binds_computed_geometry(project, site, tmp_path):
    site507 = replace(site, ras_version="5.0.7", hecras_dir=None, ld_library_path=None)
    (project / "TEST.c02").write_bytes(b"computed\r\ngeometry\x00")
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site507, tmp_path / "job")
    script = job.script_path.read_text()
    assert "--require-computed-geometry" in script
    assert "TEST.c02" in script.split("ARTIFACTS=(", 1)[1].split(")", 1)[0]
    transport = ClusterTransport()
    job = RasApptainer.submit(job, transport, site507, dry_run=False)
    remote = Path(f"{job.remote_directory}/out/4242")
    # The unchanged .c02 is still returned because it is a solver artifact.
    assert (remote / "project" / "TEST.c02").read_bytes() == b"computed\r\ngeometry\x00"

    result = RasApptainer.collect_prepare(job, transport, site507, tmp_path / "prepared")
    # The fake worker's receipt does not list TEST.c02, so it is not bound.
    assert not result.success
    assert any("TEST.c02" in problem for problem in result.problems)


def test_tmphdf_release_prepare_does_not_require_computed_geometry(project, site, tmp_path):
    job = RasApptainer.render_prepare_job(project, "TEST", 8, site, tmp_path / "job")
    assert "--require-computed-geometry" not in job.script_path.read_text()
