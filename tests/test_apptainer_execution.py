"""Offline tests for RasApptainer: profile validation, golden script, receipt, mocked SSH.

Staged artifacts here are tiny synthetic stand-ins: these tests qualify rendering,
integrity checks and orchestration only, never the HEC-RAS solver.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
from dataclasses import replace

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
    _gridded_dss_dependency,
    _stage_gridded_dss_dependency,
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


def _configure_gridded_dss(project: Path, reference=r"..\rainfall.dss"):
    """Add a small external gridded-DSS declaration to the synthetic plan HDF."""
    import h5py
    import numpy as np

    source = project.parent / "rainfall.dss"
    source.write_bytes(b"synthetic DSS dependency")
    with h5py.File(project / "TEST.p08.tmp.hdf", "r+") as hdf:
        precipitation = hdf[PRECIP]
        precipitation.attrs["Mode"] = np.array(b"Gridded", dtype="S16")
        precipitation.attrs["Source"] = np.array(b"DSS", dtype="S16")
        precipitation.attrs["DSS Filename"] = np.array(reference.encode(), dtype="S25")
        precipitation.attrs["DSS Pathname"] = np.array(
            b"/SHG/DESIGN/PRECIPITATION/01JAN2000/30MIN/ATLAS14/",
            dtype="S96",
        )
        precipitation.attrs["Ratio"] = np.float32(1.0)
        precipitation.create_dataset("Timestamp", data=[0.0])
    return source


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

def test_render_job_script(project, profile, tmp_path):
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
    script = job.script_path.read_text(encoding="utf-8")
    assert "ulimit" not in engine and "OMP_STACKSIZE=512M" in engine and "KMP_STACKSIZE=1G" in engine
    assert "STACK_LIMIT_FAILED" not in script


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
    assert meta["request"]["gridded_dss_input"] is None


def test_render_stages_external_gridded_dss_and_rebinds_only_staged_hdf(
    project,
    profile,
    tmp_path,
):
    import h5py

    source_dss = _configure_gridded_dss(project)
    source_dss_bytes = source_dss.read_bytes()
    source_hdf = project / "TEST.p08.tmp.hdf"
    with h5py.File(source_hdf, "r") as hdf:
        precipitation = hdf[PRECIP]
        source_reference = precipitation.attrs["DSS Filename"]
        source_pathname = precipitation.attrs["DSS Pathname"]
        source_ratio = precipitation.attrs["Ratio"]
        source_values = precipitation["Values"][...]
        source_timestamps = precipitation["Timestamp"][...]

    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    meta = json.loads((job.job_directory / "job.json").read_text())
    dependency = meta["request"]["gridded_dss_input"]
    staged_dss = job.job_directory / "inputs" / dependency["staged_name"]
    staged_hdf = job.job_directory / "inputs" / "TEST.p08.tmp.hdf"

    assert dependency["source_reference"] == r"..\rainfall.dss"
    assert dependency["source_sha256"] == dependency["staged_sha256"]
    assert source_dss.read_bytes() == source_dss_bytes
    assert staged_dss.read_bytes() == source_dss_bytes
    assert dependency["staged_name"] in meta["request"]["input_hashes"]
    assert dependency["staged_name"] in meta["source_input_sha256"]
    assert dependency["staged_name"] in meta["staged_input_sha256"]
    assert dependency["staged_name"] in (job.job_directory / "inputs" / "SHA256SUMS").read_text()

    with h5py.File(source_hdf, "r") as hdf:
        assert hdf[PRECIP].attrs["DSS Filename"] == source_reference
        assert hdf[PRECIP]["Values"][...].tolist() == source_values.tolist()
        assert hdf[PRECIP]["Timestamp"][...].tolist() == source_timestamps.tolist()
    with h5py.File(staged_hdf, "r") as hdf:
        precipitation = hdf[PRECIP]
        filename_dtype = precipitation.attrs.get_id("DSS Filename").dtype
        filename = precipitation.attrs["DSS Filename"]
        filename = filename.decode() if isinstance(filename, bytes) else str(filename)
        assert filename == dependency["staged_name"]
        assert filename.endswith(".dss")
        assert filename_dtype.kind == "S"
        # Fixed S25 attributes reserve a terminal byte in h5py's modify path.
        assert len(filename.encode("utf-8")) == filename_dtype.itemsize - 1
        assert precipitation.attrs["DSS Pathname"] == source_pathname
        assert precipitation.attrs["Ratio"] == source_ratio
        assert precipitation["Values"][...].tolist() == source_values.tolist()
        assert precipitation["Timestamp"][...].tolist() == source_timestamps.tolist()


def test_render_rebinds_native_nullterm_s25_dss_filename(project, profile, tmp_path):
    """Exercise the fixed-width string storage used by native HEC-RAS HDFs."""
    import h5py
    import numpy as np

    _configure_gridded_dss(project)
    source_hdf = project / "TEST.p08.tmp.hdf"
    with h5py.File(source_hdf, "r+") as hdf:
        precipitation = hdf[PRECIP]
        del precipitation.attrs["DSS Filename"]
        string_type = h5py.h5t.C_S1.copy()
        string_type.set_size(25)
        string_type.set_cset(h5py.h5t.CSET_ASCII)
        string_type.set_strpad(h5py.h5t.STR_NULLTERM)
        scalar = h5py.h5s.create(h5py.h5s.SCALAR)
        attribute = h5py.h5a.create(
            precipitation.id,
            b"DSS Filename",
            string_type,
            scalar,
        )
        attribute.write(np.array(b"..\\rainfall.dss", dtype="S25"))

    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    dependency = json.loads((job.job_directory / "job.json").read_text())["request"][
        "gridded_dss_input"
    ]
    with h5py.File(job.job_directory / "inputs" / "TEST.p08.tmp.hdf", "r") as hdf:
        precipitation = hdf[PRECIP]
        filename = precipitation.attrs["DSS Filename"]
        filename = filename.decode() if isinstance(filename, bytes) else str(filename)
        string_type = precipitation.attrs.get_id("DSS Filename").get_type()
        assert string_type.get_strpad() == h5py.h5t.STR_NULLTERM
        assert filename == dependency["staged_name"]
        assert filename.endswith(".dss")
        assert len(filename.encode("utf-8")) == 24


@pytest.mark.parametrize(
    "reference, create_source, error",
    [
        (r"..\missing.dss", False, "regular existing .dss file"),
        (r"C:\outside.dss", False, "must be relative"),
    ],
)
def test_render_rejects_invalid_gridded_dss_dependency(
    project,
    profile,
    tmp_path,
    reference,
    create_source,
    error,
):
    source = _configure_gridded_dss(project, reference=reference)
    if not create_source:
        source.unlink()

    with pytest.raises((FileNotFoundError, ValueError), match=error):
        RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    assert not (tmp_path / "job").exists()


def test_gridded_dss_dependency_rejects_directory_and_staging_collision(project):
    import h5py

    source = _configure_gridded_dss(project)
    source.unlink()
    source.mkdir()
    with pytest.raises(FileNotFoundError, match="regular existing .dss file"):
        _gridded_dss_dependency(project / "TEST.p08.tmp.hdf")

    source.rmdir()
    source.write_bytes(b"synthetic DSS dependency")
    dependency = _gridded_dss_dependency(project / "TEST.p08.tmp.hdf")
    inputs = project / "inputs"
    inputs.mkdir()
    (inputs / dependency["staged_name"]).write_bytes(b"different")
    staged_hdf = inputs / "TEST.p08.tmp.hdf"
    shutil.copyfile(project / "TEST.p08.tmp.hdf", staged_hdf)
    with pytest.raises(FileExistsError, match="filename collision"):
        _stage_gridded_dss_dependency(
            project / "TEST.p08.tmp.hdf",
            staged_hdf,
            inputs,
            dependency,
        )
    with h5py.File(project / "TEST.p08.tmp.hdf", "r") as hdf:
        source_reference = hdf[PRECIP].attrs["DSS Filename"]
    with h5py.File(staged_hdf, "r") as hdf:
        assert hdf[PRECIP].attrs["DSS Filename"] == source_reference


def test_windows_dss_output_path_is_rewritten_only_in_staged_flow(project, profile, tmp_path):
    source = project / "TEST.b08"
    original = ("Write DSS File        =        T\r\n"
                r"C:\Users\mallory\ras_work\TEST.dss" + "\r\n")
    source.write_bytes(original.encode("utf-8"))
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    staged = (job.job_directory / "inputs" / "TEST.b08").read_text(encoding="utf-8")
    rewrite = json.loads((job.job_directory / "job.json").read_text())["request"]["dss_output_rewrite"]
    assert source.read_bytes() == original.encode("utf-8")
    assert "TEST.dss" in staged and r"C:\Users\mallory" not in staged
    assert rewrite == {
        "input": "TEST.b08", "source_path": r"C:\Users\mallory\ras_work\TEST.dss",
        "staged_path": "TEST.dss",
    }
    assert 'DSS_OUTPUT_REWRITE=' in job.script_path.read_text(encoding="utf-8")


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
        "copy_verified": True, "dss_output_rewrite": None, "detail": "",
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


def test_receipt_schema_accepts_dss_output_rewrite():
    rewrite = {
        "input": "TEST.b08", "source_path": r"C:\Users\mallory\TEST.dss",
        "staged_path": "TEST.dss",
    }
    assert validate_receipt(_receipt(dss_output_rewrite=rewrite))["dss_output_rewrite"] == rewrite


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
@pytest.mark.parametrize("source", [
    r'C:\Users\example\work\a"quoted".dss',
    'line1\nline2\rtab\tend',
    r'\\server\share\rainfall.dss',
])
def test_receipt_json_escapes_windows_dss_name_and_quotes(source):
    start = JOB_SCRIPT_TEMPLATE.index("json_string()")
    end = JOB_SCRIPT_TEMPLATE.index("\n}", start) + 2
    function = JOB_SCRIPT_TEMPLATE[start:end]
    env = {**os.environ, "JSON_ESCAPE_VALUE": source}
    completed = subprocess.run(
        [BASH, "-c", function + '\njson_string "$JSON_ESCAPE_VALUE"'],
        check=True, capture_output=True, text=True, env=env,
    )
    assert json.loads(completed.stdout) == source


@pytest.mark.skipif(BASH is None or os.name == "nt",
                    reason="backslash filenames require a POSIX filesystem and Bash")
def test_receipt_hash_for_backslash_name_has_no_gnu_escape_marker():
    start = JOB_SCRIPT_TEMPLATE.index("sha_of()")
    end = JOB_SCRIPT_TEMPLATE.index("\n\n", start)
    function = JOB_SCRIPT_TEMPLATE[start:end]
    completed = subprocess.run(
        [BASH, "-c", function + """
dir=$(mktemp -d)
file="$dir/a\\b.dss"
printf payload > "$file"
sha_of "$file"
"""],
        check=True, capture_output=True, text=True,
    )
    assert completed.stdout.strip() == hashlib.sha256(b"payload").hexdigest()


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


class LocalBashTransport(ApptainerTransport):
    """Test transport that executes generated bash argv against a local Bash filesystem."""

    def __init__(self):
        self.calls, self.executed = [], []

    def run(self, argv, timeout=None):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "sbatch":
            return CommandResult(0, "4242\n")
        if argv[:2] == ["bash", "-c"]:
            command = [BASH, "-c", argv[2]]
            self.executed.append(argv)
        else:
            command = [BASH, "-c", shlex.join(argv)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return CommandResult(done.returncode, done.stdout, done.stderr)

    def put_tree(self, local_dir, remote_dir):
        done = subprocess.run(
            [BASH, "-c", f"mkdir -p {shlex.quote(remote_dir)} && cp -a "
             f"{shlex.quote(str(local_dir))}/. {shlex.quote(remote_dir)}/"],
            capture_output=True, text=True, check=False,
        )
        if done.returncode:
            raise RuntimeError(done.stderr)

    def get_tree(self, remote_dir, local_dir):
        raise NotImplementedError


def _bash_tempdir():
    return subprocess.run([BASH, "-c", "mktemp -d"], check=True, capture_output=True,
                          text=True).stdout.strip()


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


@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_submit_executes_remote_input_check_under_bash(project, profile, tmp_path):
    root = _bash_tempdir()
    try:
        local_profile = replace(profile, scratch_root=f"{root}/remote")
        job = RasApptainer.render_job(project, "TEST", 8, local_profile, tmp_path / "job")
        transport = LocalBashTransport()
        submitted = RasApptainer.submit(job, transport=transport, profile=local_profile, dry_run=False)
        assert submitted.state == "SUBMITTED"
        assert any(argv[:2] == ["bash", "-c"] for argv in transport.executed)
    finally:
        subprocess.run([BASH, "-c", f"rm -rf -- {shlex.quote(root)}"], check=False)


@pytest.mark.skipif(BASH is None, reason="bash is unavailable")
def test_pre_stage_failure_retains_scheduler_stdout_and_logs_directory(project, profile, tmp_path):
    root = _bash_tempdir()
    try:
        local_profile = replace(
            profile, scratch_root=f"{root}/remote", node_scratch_root=f"{root}/node",
            image=f"{root}/image.sif",
        )
        job = RasApptainer.render_job(project, "TEST", 8, local_profile, tmp_path / "job")
        setup = (f"mkdir -p {shlex.quote(job.remote_directory)} && cp -a "
                 f"{shlex.quote(str(job.job_directory))}/. {shlex.quote(job.remote_directory)}/ && "
                 f"printf wrong-image > {shlex.quote(local_profile.image)} && "
                 f"printf scheduler-output > {shlex.quote(job.remote_directory)}/slurm-902.out")
        subprocess.run([BASH, "-c", setup], check=True, capture_output=True, text=True)
        completed = subprocess.run(
            [BASH, str(job.script_path)], env={**os.environ, "SLURM_JOB_ID": "902"},
            check=False, capture_output=True, text=True,
        )
        receipt = json.loads(subprocess.run(
            [BASH, "-c", f"cat {shlex.quote(job.remote_directory)}/out/902/receipt.json"],
            check=True, capture_output=True, text=True,
        ).stdout)
        assert completed.returncode != 0
        assert receipt["status"] == "failed" and receipt["reason_code"] == "IMAGE_MISMATCH"
        assert "logs/slurm-902.out" in receipt["outputs"]
    finally:
        subprocess.run([BASH, "-c", f"rm -rf -- {shlex.quote(root)}"], check=False)


def test_stale_rendered_handle_never_reconciles_or_resubmits(project, profile, tmp_path):
    job = RasApptainer.render_job(project, "TEST", 8, profile, tmp_path / "job")
    transport = FakeTransport()
    RasApptainer.submit(job, transport=transport, profile=profile, dry_run=False)
    before = list(transport.calls)
    with pytest.raises(RuntimeError, match="SUBMITTED"):
        RasApptainer.submit(job, transport=transport, profile=profile, dry_run=False)
    assert transport.calls == before
    assert sum(call[0] == "sbatch" for call in transport.calls) == 1
    assert sum(call[:2] == ["bash", "-c"] and "rm -rf" in call[2] for call in transport.calls) == 1


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


def _fake_remote_output(folder, job, *, tamper=False, status="succeeded", end_stamp="01JAN2020 01:00:00"):
    import h5py

    out = folder / "remote_out"
    (out / "project").mkdir(parents=True)
    hdf_path = out / "project" / "TEST.p08.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        result = hdf.require_group("Results/Unsteady/Output")
        result.create_dataset("Time Date Stamp", data=[end_stamp.encode("ascii")])
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


def test_collect_accepts_hec_ras_2400_end_time(project, profile, tmp_path):
    _edit_hdf(project / "TEST.p08.tmp.hdf", lambda h: h["Plan Data/Plan Information"].attrs.__setitem__(
        "Simulation End Time", "01JAN2020 2400"
    ))
    job = _submitted(project, profile, tmp_path)
    transport = FakeTransport(sacct=SACCT_DONE)
    transport.remote_out = _fake_remote_output(tmp_path, job, end_stamp="02JAN2020 0000")
    assert RasApptainer.collect(job, transport, profile).success


def test_collect_requires_terminal_and_keeps_failure_evidence(project, profile, tmp_path):
    job = _submitted(project, profile, tmp_path)
    with pytest.raises(RuntimeError, match="not terminal"):
        RasApptainer.collect(job, FakeTransport(sacct="4242|RUNNING|0:0|00:01:00|n\n"), profile)
    failed = FakeTransport(sacct="4242|FAILED|1:0|00:01:00|n\n")
    failed.remote_out = _fake_remote_output(tmp_path, job, status="failed")
    res = RasApptainer.collect(job, failed, profile)
    assert not res.success and res.receipt["status"] == "failed"
