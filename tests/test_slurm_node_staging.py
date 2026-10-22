"""Filesystem-only staging contract; no Slurm, container, or HEC-RAS runtime."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "standalone_staging_launcher",
    Path(__file__).resolve().parents[1]
    / "ras_commander/remote/portable_slurm_launcher.py",
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def bundle(tmp_path):
    source = tmp_path / "shared/bundles/job-a"
    (source / "input").mkdir(parents=True)
    (source / "input/model.prj").write_bytes(b"original model input")
    payload = {"execution_id": "job-a", "output_directory": "output"}
    (source / "request.json").write_text(json.dumps(payload))
    (source / "output").mkdir()
    return source, payload


def test_verified_copy_and_publish_preserve_model_input(bundle, tmp_path):
    source, _ = bundle
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged, output = launcher._stage_bundle(source, Path("output"), scratch)
    assert (staged / "input/model.prj").read_bytes() == b"original model input"
    assert not list(output.iterdir())
    (output / "result.hdf").write_bytes(b"result bytes")
    launcher._publish_staged_output(output, source / "output")
    assert (source / "output/result.hdf").read_bytes() == b"result bytes"
    assert (source / "input/model.prj").read_bytes() == b"original model input"


def test_stage_rejects_nonempty_output(bundle, tmp_path):
    source, _ = bundle
    (source / "output/existing").touch()
    with pytest.raises(ValueError, match="empty output"):
        launcher._stage_bundle(source, Path("output"), tmp_path / "scratch")


def test_copy_hash_mismatch_is_rejected(bundle, tmp_path, monkeypatch):
    source, _ = bundle
    real_copy = shutil.copytree

    def corrupt(src, dst, *args, **kwargs):
        result = real_copy(src, dst, *args, **kwargs)
        if (Path(dst) / "input/model.prj").is_file():
            (Path(dst) / "input/model.prj").write_bytes(b"corrupted")
        return result

    monkeypatch.setattr(launcher.shutil, "copytree", corrupt)
    with pytest.raises(ValueError, match="hashes"):
        launcher._stage_bundle(source, Path("output"), tmp_path / "scratch")
    assert (source / "input/model.prj").read_bytes() == b"original model input"


def test_copyback_failure_preserves_partial_delivery_and_results(
    bundle, tmp_path, monkeypatch
):
    source, _ = bundle
    result = tmp_path / "result"
    result.mkdir()
    (result / "result.hdf").write_bytes(b"recoverable")

    def no_space(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(launcher.shutil, "copytree", no_space)
    with pytest.raises(RuntimeError, match="delivery retained"):
        launcher._publish_staged_output(result, source / "output")
    assert (result / "result.hdf").read_bytes() == b"recoverable"
    assert list(source.glob(".output.copyback-*"))
    assert not list((source / "output").iterdir())


def test_publication_refuses_output_changed_during_execution(bundle, tmp_path):
    source, _ = bundle
    result = tmp_path / "result"
    result.mkdir()
    (result / "new").write_bytes(b"new result")
    (source / "output/other").write_bytes(b"concurrent writer")
    with pytest.raises(RuntimeError, match="Output changed"):
        launcher._publish_staged_output(result, source / "output")
    assert (source / "output/other").read_bytes() == b"concurrent writer"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and Slurm paths")
def test_stage_does_not_follow_source_links(bundle, tmp_path):
    source, _ = bundle
    secret = tmp_path / "outside"
    secret.write_bytes(b"outside source")
    (source / "input/link").symlink_to(secret)
    with pytest.raises(ValueError, match="symbolic link"):
        launcher._stage_bundle(source, Path("output"), tmp_path / "scratch")


@pytest.mark.skipif(os.name == "nt", reason="Actual POSIX launcher scratch ownership")
@pytest.mark.parametrize(
    "mode", ["success", "engine_failure", "timeout", "copyback_failure", "default"]
)
def test_launcher_stages_binds_publishes_and_retains_failures(
    bundle, tmp_path, monkeypatch, mode
):
    source, payload = bundle
    scratch_root = tmp_path / "node-local"
    scratch_root.mkdir()
    monkeypatch.setenv("SLURM_JOB_ID", "42")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    step = {
        "execution_id": "job-a",
        "request_path": "bundles/job-a/request.json",
        "request_sha256": hashlib.sha256(canonical).hexdigest(),
        "output_directory": "output",
        "step_name": "rc-a",
        "timeout_seconds": 10,
    }
    site = {
        "node_scratch_root": str(scratch_root),
        "srun_executable": "srun",
        "apptainer_executable": "apptainer",
        "python_executable": "python",
        "apptainer_image_sha256": "b" * 64,
        "apptainer_image": "/images/test.sif",
    }
    if mode != "default":
        site["stage_bundles_to_node_scratch"] = True
    observed = {}

    def execute(command, *, bundle, output, timeout_seconds):
        observed["bundle"] = bundle
        observed["output"] = output
        binds = [command[i + 1] for i, v in enumerate(command) if v == "--bind"]
        assert binds[0] == f"{bundle}:/job:ro"
        assert binds[1] == f"{output}:/job/output:rw"
        assert not list(output.iterdir())
        if mode != "default":
            assert bundle.is_relative_to(scratch_root)
            tmp_bind = Path(binds[2].split(":")[0])
            assert tmp_bind.name == "tmp" and not bundle.is_relative_to(tmp_bind)
        else:
            assert bundle == source
        (output / "runtime_project").mkdir()
        (output / "runtime_project/result.hdf").write_bytes(b"results")
        (output / "execution_receipt.json").write_text('{"success": true}')
        (output / "slurm_step.stdout.log").write_text("diagnostic")
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, timeout_seconds)
        return subprocess.CompletedProcess(
            command, 1 if mode == "engine_failure" else 0
        )

    monkeypatch.setattr(launcher, "_run_step_process", execute)
    if mode == "copyback_failure":

        def broken(*args):
            raise OSError("copyback unavailable")

        monkeypatch.setattr(launcher, "_publish_staged_output", broken)
    succeeded = launcher._run_step(source.parents[1], site, step)
    assert succeeded is (mode in ("success", "default"))
    if mode == "copyback_failure":
        failure = json.loads((source / "output/launcher_failure.json").read_text())
        assert failure["reason_code"] == "SLURM_STEP_COPYBACK_FAILED"
        assert "scratch=" in failure["detail"]
        assert observed["output"].is_dir()
    else:
        assert (source / "output/runtime_project/result.hdf").read_bytes() == b"results"
        assert (source / "output/slurm_step.stdout.log").read_text() == "diagnostic"
        if mode != "default":
            receipt = json.loads((source / "output/slurm_staging.json").read_text())
            assert receipt["execution_location"] == "node_scratch"
            assert receipt["scratch_retained"] is (mode == "timeout")
        assert observed["bundle"].exists() is (mode in ("timeout", "default"))
    assert (source / "input/model.prj").read_bytes() == b"original model input"
