"""Offline tests for RasApptainer: profile validation, golden script, receipt, mocked SSH.

Staged artifacts here are tiny synthetic stand-ins: these tests qualify rendering,
integrity checks and orchestration only, never the HEC-RAS solver.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ras_commander import RasApptainer
from ras_commander.RasApptainer import (
    ApptainerProfileError,
    ApptainerTransport,
    CommandResult,
    DEFAULT_OCI_SOURCE,
    InputCheckError,
    JOB_SCRIPT_TEMPLATE,
    check_solver_ready,
    RECEIPT_SCHEMA,
    validate_receipt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "apptainer"
PROFILE = FIXTURES / "site_profile.json"
EXAMPLE = Path(__file__).parents[1] / "examples" / "site_profiles" / "clb-slurm.example.json"
SACCT_DONE = "4242|COMPLETED|0:0|00:10:00|node01\n"
BASH = next((candidate for candidate in (
    shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe",
) if candidate and Path(candidate).is_file()), None)


def _profile_dict():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "TEST.p08").write_bytes(b"Plan Title=x\r\nGeom File=g02\r\n")
    shutil.copyfile(FIXTURES / "solver_ready.tmp.hdf", folder / "TEST.p08.tmp.hdf")
    _make_solver_ready(folder / "TEST.p08.tmp.hdf")
    (folder / "TEST.b08").write_bytes(b"line1\r\nline2\r\n")
    (folder / "TEST.x02").write_bytes(b"xdata\n")
    return folder


def _make_solver_ready(path):
    """Upgrade the compact legacy fixture to a completed Windows tmp.hdf."""
    import h5py
    import numpy as np

    with h5py.File(path, "r+") as hdf:
        hdf.require_group("Geometry/GeomPreprocess").create_dataset("Complete", data=[1])
        area = hdf["Geometry/2D Flow Areas/Area1"]
        for name in ("Faces Area Elevation Values", "Faces Area Elevation Info",
                     "Cells Volume Elevation Values", "Cells Volume Elevation Info",
                     "Cells Surface Area"):
            if name not in area:
                area.create_dataset(name, data=np.ones((3, 2), dtype="f4"))
        parameters = hdf.require_group("Plan Data/Plan Parameters")
        parameters.attrs["1D Cores"] = 1
        parameters.attrs["2D Cores (per mesh)"] = [1]
        info = hdf.require_group("Plan Data/Plan Information")
        info.attrs["Simulation End Time"] = "01JAN2020 01:00:00"


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


def test_profile_accepts_digest_pinned_oci_source():
    data = _profile_dict()
    data["oci_source"] = "docker://registry.example/hecras@sha256:" + "a" * 64
    assert RasApptainer.profile_from_dict(data).oci_source.endswith("a" * 64)


# ---- rendering -----------------------------------------------------------

def test_render_job_golden_script(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    script = job.script_path.read_text(encoding="utf-8")
    for line in (
        "#SBATCH --account=ras", "#SBATCH --partition=compute", "#SBATCH --qos=normal",
        "#SBATCH --cpus-per-task=4", "#SBATCH --mem=14336M", "#SBATCH --time=2-00:00:00",
        "#SBATCH --nodelist=node01",
    ):
        assert line in script
    assert '--bind "$WORK:/job"' in script and "--cleanenv" in script
    assert 'SCRATCH="$NODE_SCRATCH_ROOT/$SLURM_JOB_ID/ras"' in script
    assert "ulimit -s unlimited || { REASON=STACK_LIMIT_FAILED" in script
    assert "#SBATCH --signal=B:TERM@600" in script


def test_render_engine_script_invocation(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", "08", profile, tmp_path / "job")
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert job.geometry_token == "x02"  # x token comes from the plan's geometry, not the plan number
    assert "XTOKEN=x02" in engine and "PLAN=08" in engine
    assert '"$HECRAS/RasUnsteady" "$PROJECT.p$PLAN.tmp.hdf" "$XTOKEN"' in engine
    assert "HECRAS=/opt/hecras-runtime/engine" in engine
    assert ("LD_LIBRARY_PATH=/opt/hecras-runtime/engine/libs:/opt/hecras-runtime/engine/libs/mkl"
            ":/opt/hecras-runtime/engine/libs/rhel_8") in engine
    assert "ulimit -s unlimited" in engine
    assert "OMP_STACKSIZE=2G" in engine and "KMP_STACKSIZE=2G" in engine
    assert "OMP_NUM_THREADS=4" in engine and 'ln -s "$PROJECT.b$PLAN" io.b' in engine
    assert "RasGeomPreprocess" not in engine


def test_stack_settings_are_configurable(project, tmp_path):
    data = _profile_dict()
    data.update({"stack_unlimited": False, "omp_stacksize": "512M", "kmp_stacksize": "1G"})
    prof = RasApptainer.profile_from_dict(data)
    job = RasApptainer.render_job(project, "TEST", 8, prof, tmp_path / "job")
    engine = (job.job_directory / "engine.sh").read_text(encoding="utf-8")
    assert "ulimit" not in engine and "OMP_STACKSIZE=512M" in engine and "KMP_STACKSIZE=1G" in engine


def test_canonical_image_defaults_and_pull_command():
    assert DEFAULT_OCI_SOURCE == "docker://rascommander/hec-ras-linux-unsteady_6.6:v1"
    example = RasApptainer.load_profile(EXAMPLE)
    assert example.oci_source == DEFAULT_OCI_SOURCE
    assert example.hecras_dir == "/opt/hecras-runtime/engine"
    assert example.image.endswith("rascommander-hec-ras-linux-unsteady_6.6-v1.sif")
    cmd = RasApptainer.pull_command(example)
    assert cmd.startswith("apptainer pull ") and DEFAULT_OCI_SOURCE in cmd and "sha256sum" in cmd


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
    assert (job.job_directory / "inputs" / "TEST.p08.tmp.hdf").read_bytes() != (project / "TEST.p08.tmp.hdf").read_bytes()
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


def test_staged_hdf_core_count_matches_allocation(project, profile, tmp_path):
    import h5py

    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    with h5py.File(job.job_directory / "inputs" / "TEST.p08.tmp.hdf") as hdf:
        attrs = hdf["Plan Data/Plan Parameters"].attrs
        assert attrs["1D Cores"] == profile.num_cores
        assert attrs["2D Cores (per mesh)"][0] == profile.num_cores
    assert json.loads((job.job_directory / "job.json").read_text())["core_evidence"]["effective_cores"] == 4


def test_render_rejects_missing_artifacts_and_nonempty_dir(project, profile, tmp_path):
    (project / "TEST.x02").unlink()
    with pytest.raises(FileNotFoundError, match="x02"):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    (project / "TEST.x02").write_bytes(b"x")
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "f").write_text("x")
    with pytest.raises(FileExistsError):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "busy")


# ---- solver-ready input check -------------------------------------------

PRECIP = "Event Conditions/Meteorology/Precipitation"


def _edit_hdf(path, fn):
    import h5py
    with h5py.File(path, "r+") as hdf:
        fn(hdf)


def test_check_passes_on_solver_ready_fixture(project):
    assert check_solver_ready(project / "TEST.p08.tmp.hdf") == []
    assert RasApptainer.check_solver_ready(project / "TEST.p08.tmp.hdf") == []


def test_check_requires_geompre_unless_the_profile_runs_it(project):
    tmp = project / "TEST.p08.tmp.hdf"
    _edit_hdf(tmp, lambda h: h.__delitem__("Geometry/GeomPreprocess"))
    assert any("GeomPreprocess" in item for item in check_solver_ready(tmp))
    assert check_solver_ready(tmp, geom_preprocess=True) == []


def test_check_all_2d_float_property_tables_for_nan(project):
    tmp = project / "TEST.p08.tmp.hdf"
    _edit_hdf(tmp, lambda h: h["Geometry/2D Flow Areas/Area1/Cells Surface Area"].__setitem__(
        (0, 0), float("nan")
    ))
    assert any("Cells Surface Area" in item for item in check_solver_ready(tmp))


def test_check_accepts_1d_only_completed_hdf(project):
    tmp = project / "TEST.p08.tmp.hdf"
    _edit_hdf(tmp, lambda h: h.__delitem__("Geometry/2D Flow Areas"))
    assert check_solver_ready(tmp) == []


def test_check_flags_missing_precip_interpolation_group(project, profile, tmp_path):
    tmp = project / "TEST.p08.tmp.hdf"
    _edit_hdf(tmp, lambda h: h.__delitem__(f"{PRECIP}/2D Flow Areas"))
    problems = check_solver_ready(tmp)
    assert len(problems) == 1 and "2D Flow Areas/Area1/" in problems[0]
    job_dir = tmp_path / "job"
    with pytest.raises(InputCheckError) as exc:
        RasApptainer.render_job(project, "TEST", 8, profile, job_dir)
    assert "2D Flow Areas folder not found" in str(exc.value)
    assert not job_dir.exists() or not any(job_dir.iterdir())  # failed before staging
    RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "skip", check_inputs=False)


def test_check_flags_empty_precip_dataset(project):
    tmp = project / "TEST.p08.tmp.hdf"

    def empty(h):
        base = f"{PRECIP}/2D Flow Areas/Area1"
        del h[f"{base}/Cell Weights"]
        h.create_dataset(f"{base}/Cell Weights", data=[], dtype="f4")
    _edit_hdf(tmp, empty)
    assert any("Cell Weights" in p for p in check_solver_ready(tmp))


def test_check_without_gridded_precip_does_not_require_group(project):
    tmp = project / "TEST.p08.tmp.hdf"

    def drop(h):
        del h[PRECIP]
    _edit_hdf(tmp, drop)
    assert check_solver_ready(tmp) == []


def test_check_flags_nan_property_table_but_not_cell_min_elevation(project, profile, tmp_path):
    tmp = project / "TEST.p08.tmp.hdf"

    def poison(h):
        h["Geometry/2D Flow Areas/Area1/Faces Minimum Elevation"][1] = float("nan")
    _edit_hdf(tmp, poison)
    problems = check_solver_ready(tmp)
    assert len(problems) == 1 and "Faces Minimum Elevation" in problems[0]  # Cells Minimum Elevation NaN ignored
    with pytest.raises(InputCheckError):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")


def test_check_reports_non_hdf5_file(tmp_path):
    bad = tmp_path / "x.tmp.hdf"
    bad.write_bytes(b"not hdf")
    assert "cannot open as HDF5" in check_solver_ready(bad)[0]


def test_dry_run_never_touches_transport(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    out = RasApptainer.submit(job, dry_run=True)  # no transport at all
    assert out.dry_run and out.slurm_job_id is None and out.state == "RENDERED"


def test_attempts_are_unique_and_retry_reconciles_only_its_attempt(project, profile, tmp_path):
    a = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "a")
    b = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "b")
    assert a.request_sha256 == b.request_sha256 and a.remote_directory != b.remote_directory
    transport = FakeTransport()
    RasApptainer.submit(a, transport=transport, profile=profile, dry_run=False)
    assert a.remote_directory in transport.calls[1][2]


def test_submit_rejects_placeholder_image_digest(project, profile, tmp_path):
    data = _profile_dict()
    data["apptainer_image_sha256"] = "0" * 64
    data["container_identity"] = "sif:sha256:" + "0" * 64
    placeholder = RasApptainer.profile_from_dict(data)
    job = RasApptainer.render_job(project, "TEST", 8, placeholder, tmp_path / "job")
    assert RasApptainer.submit(job, dry_run=True).dry_run
    with pytest.raises(ApptainerProfileError, match="all-zero"):
        RasApptainer.submit(job, FakeTransport(), placeholder, dry_run=False)


def test_fim_only_profile_fields_are_accepted_as_compatibility_noops():
    data = _profile_dict()
    data.update({
        "max_concurrent": 7, "memory_per_task": "3200M", "ras_executable": "C:/Ras.exe",
        "transfer_mode": "scp", "timeout_seconds": 3600, "rsync_executable": "rsync",
        "launcher_python_executable": "python3",
    })
    profile = RasApptainer.profile_from_dict(data)
    assert profile.slurm_memory == "14336M"


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


def test_receipt_schema_accepts_escaped_windows_style_output_name():
    receipt = _receipt(outputs={
        r'project/C:\Users\mallory\a"quoted".dss': {"sha256": "d" * 64, "size_bytes": 9}
    })
    assert validate_receipt(receipt)["outputs"] == receipt["outputs"]


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


@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_receipt_json_escapes_windows_dss_name_and_quotes():
    start = JOB_SCRIPT_TEMPLATE.index("json_string()")
    end = JOB_SCRIPT_TEMPLATE.index("\n}", start) + 2
    function = JOB_SCRIPT_TEMPLATE[start:end]
    source = r'C:\Users\mallory\work\a"quoted".dss'
    env = {**os.environ, "JSON_ESCAPE_VALUE": source}
    completed = subprocess.run(
        [BASH, "-c", function + '\njson_string "$JSON_ESCAPE_VALUE"'],
        check=True, capture_output=True, text=True, env=env,
    )
    assert json.loads(completed.stdout) == source


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
    assert t.calls[0][:2] == ["mkdir", "-p"] and t.calls[1][:2] == ["bash", "-c"]
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


def test_status_tolerates_sacct_error_and_cancel_uses_exact_job(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    broken = FakeTransport()
    original = broken.run

    def run(argv, timeout=None):
        if argv[0] == "sacct":
            return CommandResult(1, "", "accounting disabled")
        return original(argv, timeout)

    broken.run = run
    status = RasApptainer.status(job, broken, profile)
    assert status.state == "UNKNOWN" and "accounting disabled" in status.reason
    RasApptainer.cancel(job, broken, profile)
    assert ["scancel", "4242"] in broken.calls


def _fake_remote_output(folder, job, *, tamper=False, status="succeeded"):
    import h5py

    out = folder / "remote_out"
    (out / "project").mkdir(parents=True)
    hdf_path = out / "project" / "TEST.p08.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        result = hdf.require_group("Results/Unsteady/Output")
        result.create_dataset("Time Date Stamp", data=[b"01JAN2020 01:00:00"])
        result.create_dataset("Water Surface", data=[[1.0]])
    data = hdf_path.read_bytes()
    if tamper:
        hdf_path.write_bytes(b"TAMPERED")
    (out / "project" / "solver.log").write_text("Finished Unsteady Flow Simulation\n")
    ok = status == "succeeded"
    record = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    request = json.loads((job.job_directory / "job.json").read_text())["request"]
    rec = _receipt(
        request_sha256=job.request_sha256, slurm_job_id="4242", status=status,
        reason_code="COMPLETED" if ok else "COMPUTE_FAILED", exit_code=0 if ok else 1,
        apptainer_image_sha256=request["profile"]["apptainer_image_sha256"],
        container_identity=request["profile"]["container_identity"],
        input_hashes={
            name: {"sha256": digest, "size_bytes": (job.job_directory / "inputs" / name).stat().st_size}
            for name, digest in request["input_hashes"].items()
        }, outputs={"project/TEST.p08.hdf": record},
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


@pytest.mark.parametrize("field", ["apptainer_image_sha256", "input_hashes"])
def test_collect_detects_request_integrity_mismatch(project, profile, tmp_path, field):
    job = _submitted(project, profile, tmp_path)
    t = FakeTransport(sacct=SACCT_DONE)
    t.remote_out = _fake_remote_output(tmp_path, job)
    receipt = json.loads((t.remote_out / "receipt.json").read_text())
    if field == "apptainer_image_sha256":
        receipt[field] = "f" * 64
    else:
        receipt[field]["TEST.b08"]["sha256"] = "f" * 64
    (t.remote_out / "receipt.json").write_text(json.dumps(receipt))
    result = RasApptainer.collect(job, t, profile)
    assert not result.success and any("rendered request" in problem for problem in result.problems)


def test_collect_rejects_incomplete_result_hdf(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    t = FakeTransport(sacct=SACCT_DONE)
    t.remote_out = _fake_remote_output(tmp_path, job)
    (t.remote_out / "project" / "TEST.p08.hdf").write_bytes(b"not an hdf")
    receipt = json.loads((t.remote_out / "receipt.json").read_text())
    data = (t.remote_out / "project" / "TEST.p08.hdf").read_bytes()
    receipt["outputs"]["project/TEST.p08.hdf"] = {
        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
    }
    (t.remote_out / "receipt.json").write_text(json.dumps(receipt))
    result = RasApptainer.collect(job, t, profile)
    assert not result.success and any("result validation failed" in problem for problem in result.problems)


def test_collect_requires_terminal_and_keeps_failure_evidence(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    with pytest.raises(RuntimeError, match="not terminal"):
        RasApptainer.collect(job, FakeTransport(sacct="4242|RUNNING|0:0|00:01:00|n\n"), profile)
    failed = FakeTransport(sacct="4242|FAILED|1:0|00:01:00|n\n")
    failed.remote_out = _fake_remote_output(tmp_path, job, status="failed")
    res = RasApptainer.collect(job, failed, profile)
    assert not res.success and res.receipt["status"] == "failed"
