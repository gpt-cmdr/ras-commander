"""Offline tests for RasApptainer: profile validation, golden script, receipt, mocked SSH.

Staged artifacts here are tiny synthetic stand-ins: these tests qualify rendering,
integrity checks and orchestration only, never the HEC-RAS solver.
"""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ras_commander import RasApptainer
from ras_commander.RasApptainer import (
    ApptainerProfileError,
    ApptainerTransport,
    CommandResult,
    RECEIPT_SCHEMA,
    validate_receipt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "apptainer"
PROFILE = FIXTURES / "site_profile.json"
EXAMPLE = Path(__file__).parents[1] / "examples" / "site_profiles" / "clb-slurm.example.json"
SACCT_DONE = "4242|COMPLETED|0:0|00:10:00|node01\n"


def _profile_dict():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "TEST.p08").write_bytes(b"Plan Title=x\r\nGeom File=g02\r\n")
    (folder / "TEST.p08.tmp.hdf").write_bytes(b"HDFDATA\r\n\x00\x01")
    (folder / "TEST.b08").write_bytes(b"line1\r\nline2\r\n")
    (folder / "TEST.x02").write_bytes(b"xdata\n")
    return folder


@pytest.fixture()
def profile():
    return RasApptainer.load_profile(PROFILE)


# ---- profile -------------------------------------------------------------

def test_fixture_and_example_profiles_load():
    assert RasApptainer.load_profile(PROFILE).num_cores == 4
    example = RasApptainer.load_profile(EXAMPLE)
    assert example.site_name == "clb" and example.partition == "clb"


@pytest.mark.parametrize("change, fragment", [
    ({"surprise": 1}, "unknown field 'surprise'"),
    ({"apptainer_image_sha256": "abc"}, "apptainer_image_sha256"),
    ({"container_identity": "rascommander/hec-ras-linux-unsteady_6.6:v1"}, "mutable tags"),
    ({"image": "relative/path.sif"}, "image must be a safe absolute"),
    ({"scratch_root": "/a/../b"}, "scratch_root"),
    ({"num_cores": 0}, "num_cores"),
    ({"time_limit": "soon"}, "time_limit"),
    ({"slurm_memory": "lots"}, "slurm_memory"),
    ({"partition": "a b; rm -rf /"}, "partition"),
    ({"ras_version": "7.0"}, "ras_version"),
    ({"schema": "other/v9"}, "unsupported schema"),
    ({"environment": {"bad-name": "x"}}, "environment"),
])
def test_profile_validation_errors(change, fragment):
    data = _profile_dict()
    data.update(change)
    with pytest.raises(ApptainerProfileError) as exc:
        RasApptainer.profile_from_dict(data)
    assert fragment in str(exc.value)


def test_profile_missing_required_fields_listed_together():
    data = _profile_dict()
    del data["host"], data["image"]
    with pytest.raises(ApptainerProfileError) as exc:
        RasApptainer.profile_from_dict(data)
    assert "'host'" in str(exc.value) and "'image'" in str(exc.value)


# ---- rendering -----------------------------------------------------------

def test_render_job_golden_script(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    script = job.script_path.read_text(encoding="utf-8")
    assert script == (FIXTURES / "job.sh.golden").read_text(encoding="utf-8")
    for line in (
        "#SBATCH --account=ras", "#SBATCH --partition=compute", "#SBATCH --qos=normal",
        "#SBATCH --cpus-per-task=4", "#SBATCH --mem=14336M", "#SBATCH --time=2-00:00:00",
        "#SBATCH --nodelist=node01",
    ):
        assert line in script
    assert '--bind "$WORK:/job"' in script and "--cleanenv" in script
    assert 'SCRATCH="$NODE_SCRATCH_ROOT/$SLURM_JOB_ID/ras"' in script


def test_render_engine_script_invocation(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", "08", profile, tmp_path / "job")
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert job.geometry_token == "x02"  # x token comes from the plan's geometry, not the plan number
    assert "XTOKEN=x02" in engine and "PLAN=08" in engine
    assert '"$HECRAS/RasUnsteady" "$PROJECT.p$PLAN.tmp.hdf" "$XTOKEN"' in engine
    assert "LD_LIBRARY_PATH=/opt/hecras/libs:/opt/hecras/libs/mkl:/opt/hecras/libs/rhel_8" in engine
    assert "OMP_NUM_THREADS=4" in engine and 'ln -s "$PROJECT.b$PLAN" io.b' in engine
    assert "RasGeomPreprocess" not in engine


def test_geom_preprocess_is_opt_in(project, tmp_path):
    data = _profile_dict()
    data["geom_preprocess"] = True
    prof = RasApptainer.profile_from_dict(data)
    job = RasApptainer.render_job(project, "TEST", 8, prof, tmp_path / "job")
    assert "RasGeomPreprocess" in (job.job_directory / "engine.sh").read_text(encoding="utf-8")


def test_staged_inputs_lf_normalized_and_source_untouched(project, profile, tmp_path):
    before = (project / "TEST.b08").read_bytes()
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    assert (job.job_directory / "inputs" / "TEST.b08").read_bytes() == b"line1\nline2\n"
    assert (job.job_directory / "inputs" / "TEST.p08.tmp.hdf").read_bytes() == b"HDFDATA\r\n\x00\x01"
    assert (project / "TEST.b08").read_bytes() == before
    assert (job.job_directory / "inputs" / "SHA256SUMS").read_text().count("\n") == 3
    meta = json.loads((job.job_directory / "job.json").read_text())
    assert meta["source_input_sha256"]["TEST.b08"] != meta["staged_input_sha256"]["TEST.b08"]


def test_request_hash_is_deterministic_and_input_bound(project, profile, tmp_path):
    a = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "a")
    b = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "b")
    assert a.request_sha256 == b.request_sha256
    (project / "TEST.x02").write_bytes(b"changed\n")
    c = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "c")
    assert c.request_sha256 != a.request_sha256


def test_render_rejects_missing_artifacts_and_nonempty_dir(project, profile, tmp_path):
    (project / "TEST.x02").unlink()
    with pytest.raises(FileNotFoundError, match="x02"):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    (project / "TEST.x02").write_bytes(b"x")
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "f").write_text("x")
    with pytest.raises(FileExistsError):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "busy")


def test_dry_run_never_touches_transport(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    out = RasApptainer.submit(job, dry_run=True)  # no transport at all
    assert out.dry_run and out.slurm_job_id is None and out.state == "RENDERED"


# ---- receipt -------------------------------------------------------------

def _receipt(**over):
    rec = {
        "schema": RECEIPT_SCHEMA, "request_sha256": "a" * 64, "job_name": "j",
        "slurm_job_id": "123", "node": "n1", "container_identity": "sif:sha256:" + "b" * 64,
        "apptainer_image_sha256": "b" * 64, "status": "succeeded", "reason_code": "COMPLETED",
        "exit_code": 0, "started_at": "2026-10-03T10:00:00+00:00",
        "finished_at": "2026-10-03T11:00:00+00:00", "elapsed_seconds": 3600, "num_cores": 4,
        "input_hashes": {"TEST.b08": {"sha256": "c" * 64, "size_bytes": 3}},
        "outputs": {"project/TEST.p08.hdf": {"sha256": "d" * 64, "size_bytes": 9}},
        "copy_verified": True, "detail": "",
    }
    rec.update(over)
    return rec


def test_receipt_schema_accepts_valid():
    assert validate_receipt(_receipt())["status"] == "succeeded"


@pytest.mark.parametrize("change", [
    {"schema": "x"}, {"request_sha256": "zz"}, {"slurm_job_id": "abc"}, {"exit_code": "0"},
    {"status": "maybe"}, {"copy_verified": False}, {"outputs": {}},
    {"reason_code": "COMPUTE_FAILED"}, {"started_at": "2026-10-03T10:00:00"},
    {"outputs": {"../escape": {"sha256": "d" * 64, "size_bytes": 1}}},
    {"outputs": {"a": {"sha256": "d" * 64}}}, {"elapsed_seconds": -1},
])
def test_receipt_schema_rejects(change):
    with pytest.raises(ValueError):
        validate_receipt(_receipt(**change))


def test_receipt_rejects_extra_and_missing_fields():
    extra = _receipt()
    extra["approved"] = True
    with pytest.raises(ValueError):
        validate_receipt(extra)
    missing = _receipt()
    del missing["node"]
    with pytest.raises(ValueError):
        validate_receipt(missing)


def test_failed_receipt_cannot_claim_completed():
    with pytest.raises(ValueError):
        validate_receipt(_receipt(status="failed", exit_code=1))


# ---- mocked SSH ------------------------------------------------------------

class FakeTransport(ApptainerTransport):
    def __init__(self, sacct="", squeue="", sbatch_out="4242\n", sbatch_rc=0):
        self.calls, self.put = [], []
        self.sacct, self.squeue = sacct, squeue
        self.sbatch_out, self.sbatch_rc = sbatch_out, sbatch_rc
        self.remote_out = None

    def run(self, argv, timeout=None):
        self.calls.append(list(argv))
        if argv[0] == "sbatch":
            return CommandResult(self.sbatch_rc, self.sbatch_out, "boom" if self.sbatch_rc else "")
        if argv[0] == "sacct":
            return CommandResult(0, self.sacct)
        if argv[0] == "squeue":
            return CommandResult(0, self.squeue)
        return CommandResult(0)

    def put_tree(self, local_dir, remote_dir):
        self.put.append((Path(local_dir), remote_dir))

    def get_tree(self, remote_dir, local_dir):
        shutil.copytree(self.remote_out, local_dir)


def _submitted(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    return RasApptainer.submit(job, transport=FakeTransport(), profile=profile, dry_run=False)


def test_mock_submit_and_persisted_handle(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    t = FakeTransport()
    sub = RasApptainer.submit(job, transport=t, profile=profile, dry_run=False)
    assert sub.state == "SUBMITTED" and sub.slurm_job_id == "4242"
    assert t.calls[0][:2] == ["mkdir", "-p"] and t.calls[1] == ["mkdir", job.remote_directory]
    assert t.calls[-1] == ["sbatch", "--parsable", f"{job.remote_directory}/job.sh"]
    assert t.put == [(job.job_directory, job.remote_directory)]
    reloaded = RasApptainer.load_job(job.job_directory)
    assert reloaded.slurm_job_id == "4242" and reloaded.state == "SUBMITTED"
    with pytest.raises(RuntimeError, match="refusing to submit again"):
        RasApptainer.submit(reloaded, transport=t, profile=profile, dry_run=False)


def test_ambiguous_sbatch_failure_blocks_resubmission(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    with pytest.raises(RuntimeError, match="SUBMITTING"):
        RasApptainer.submit(job, transport=FakeTransport(sbatch_rc=255), profile=profile, dry_run=False)
    assert RasApptainer.load_job(job.job_directory).state == "SUBMITTING"


def test_mock_status_states(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    st = RasApptainer.status(job, FakeTransport(sacct=SACCT_DONE), profile)
    assert st.state == "COMPLETED" and st.terminal and st.node == "node01"
    cancelled = FakeTransport(sacct="4242|CANCELLED by 1000|0:15|00:00:09|node01\n")
    assert RasApptainer.status(job, cancelled, profile).state == "CANCELLED"
    st = RasApptainer.status(job, FakeTransport(sacct="", squeue="PENDING\n"), profile)
    assert st.state == "PENDING" and not st.terminal
    assert RasApptainer.status(job, FakeTransport(), profile).state == "UNKNOWN"


def _fake_remote_output(folder, job, *, tamper=False, status="succeeded"):
    out = folder / "remote_out"
    (out / "project").mkdir(parents=True)
    data = b"RESULTS"
    (out / "project" / "TEST.p08.hdf").write_bytes(b"TAMPERED" if tamper else data)
    ok = status == "succeeded"
    record = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    rec = _receipt(
        request_sha256=job.request_sha256, slurm_job_id="4242", status=status,
        reason_code="COMPLETED" if ok else "COMPUTE_FAILED", exit_code=0 if ok else 1,
        outputs={"project/TEST.p08.hdf": record},
    )
    (out / "receipt.json").write_text(json.dumps(rec))
    return out


def test_collect_success_and_refuses_existing_destination(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    t = FakeTransport(sacct=SACCT_DONE)
    t.remote_out = _fake_remote_output(tmp_path, job)
    res = RasApptainer.collect(job, t, profile)
    assert res.success and not res.problems
    with pytest.raises(FileExistsError):
        RasApptainer.collect(job, t, profile)


def test_collect_detects_tampered_output(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    t = FakeTransport(sacct=SACCT_DONE)
    t.remote_out = _fake_remote_output(tmp_path, job, tamper=True)
    res = RasApptainer.collect(job, t, profile)
    assert not res.success and any("mismatch" in p for p in res.problems)


def test_collect_requires_terminal_and_keeps_failure_evidence(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    with pytest.raises(RuntimeError, match="not terminal"):
        RasApptainer.collect(job, FakeTransport(sacct="4242|RUNNING|0:0|00:01:00|n\n"), profile)
    failed = FakeTransport(sacct="4242|FAILED|1:0|00:01:00|n\n")
    failed.remote_out = _fake_remote_output(tmp_path, job, status="failed")
    res = RasApptainer.collect(job, failed, profile)
    assert not res.success and res.receipt["status"] == "failed"
