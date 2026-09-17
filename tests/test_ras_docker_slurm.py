import importlib
import json
from pathlib import Path
import subprocess
import threading
import time

import pytest

from ras_commander.remote.RasPortableDocker import (
    PortableDockerExecutionResult,
    RasPortableDocker,
)
from ras_commander.RasSlurm import (
    RasSlurm,
    SlurmSubmission,
    SlurmSiteConfig,
    SlurmStatus,
    SlurmTaskAccounting,
    SlurmTransportConfig,
)
from ras_commander.remote.ExecutionContract import (
    RasExecutionReceipt,
    RasExecutionRequest,
    sha256_file,
    validate_execution_receipt,
)


OCI = "registry.example/hecras/steady@sha256:" + "a" * 64
SIF_SHA = "b" * 64


def _request(tmp_path: Path, execution_id: str) -> Path:
    bundle = tmp_path / execution_id
    source = bundle / "input" / "model.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=model\nCurrent Plan=p01\nPlan File=p01\n")
    (source.parent / "model.p01").write_text("Flow File=f01\nGeom File=g01\n")
    request = RasExecutionRequest.create(
        execution_id=execution_id,
        request_directory=bundle,
        source_project_path="input/model.prj",
        plan_number="01",
        output_directory=f"output/{execution_id}",
        ras_executable="/opt/hec-ras/Ras.exe",
        container_identity=OCI,
        timeout_seconds=60,
    )
    return request.write(bundle / "request.json")


def _receipt(
    request_path: Path, *, success=True, runtime_identity=None
) -> RasExecutionReceipt:
    request = RasExecutionRequest.read(request_path)
    _, output = request.resolve_paths(request_path)
    hdf = output / "runtime_project" / "model.p01.hdf"
    if success:
        hdf.parent.mkdir(parents=True, exist_ok=True)
        hdf.write_bytes(b"validated-result")
    return RasExecutionReceipt(
        execution_id=request.execution_id,
        request_sha256=request.digest,
        container_identity=request.container_identity,
        runtime_container_identity=runtime_identity or request.container_identity,
        success=success,
        status="succeeded" if success else "failed",
        started_at="2026-09-13T00:00:00Z",
        finished_at="2026-09-13T00:00:01Z",
        source_tree_sha256_before=request.source_tree_sha256,
        source_tree_sha256_after=request.source_tree_sha256,
        source_unchanged=True,
        solver_verified=success,
        hydraulic_validated=success,
        result_validation={"passed": success, "reason_codes": []},
        result_hdf_path="runtime_project/model.p01.hdf" if success else None,
        result_hdf_sha256=sha256_file(hdf) if success else None,
        compute_diagnostics={"completed": success},
    )


def _site(**kwargs):
    values = dict(
        site_name="clb12",
        apptainer_image="/opt/images/hecras.sif",
        apptainer_image_sha256=SIF_SHA,
        container_identity=OCI,
    )
    values.update(kwargs)
    return SlurmSiteConfig(**values)


def test_slurm_accepts_sif_identity_but_docker_rejects_it(tmp_path):
    sif_identity = "sif:sha256:" + SIF_SHA
    assert _site(container_identity=sif_identity).container_identity == sif_identity

    path = _request(tmp_path, "job-sif")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["container_identity"] = sif_identity
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="requires an immutable OCI reference"):
        RasPortableDocker.build_execute_command(path)


def test_docker_command_is_one_core_shell_free_and_input_readonly(tmp_path):
    request = _request(tmp_path, "job-a")
    command = RasPortableDocker.build_execute_command(request, memory="3g")

    assert command[:3] == ("docker", "run", "--rm")
    assert command[command.index("--cpus") + 1] == "1"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert any("target=/job,readonly" in mount for mount in mounts)
    assert any("target=/job/output/job-a" in mount and "readonly" not in mount for mount in mounts)
    assert command[-2:] == ("execute-request", "/job/request.json")


def test_docker_rejects_image_mismatch_and_ambiguous_mount_path(tmp_path):
    request = _request(tmp_path, "job-a")
    with pytest.raises(ValueError, match="exactly match"):
        RasPortableDocker.build_execute_command(request, image="mutable:latest")

    comma_root = tmp_path / "contains,comma"
    comma_request = _request(comma_root, "job-b")
    with pytest.raises(ValueError, match="commas"):
        RasPortableDocker.build_execute_command(comma_request)


def test_docker_compute_validates_receipt_binding(tmp_path, monkeypatch):
    path = _request(tmp_path, "job-a")

    def run(command, **kwargs):
        if command[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps([OCI]), "")
        request = RasExecutionRequest.read(path)
        _, output = request.resolve_paths(path)
        _receipt(path).write(output / "execution_receipt.json")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    module = importlib.import_module("ras_commander.remote.RasPortableDocker")
    monkeypatch.setattr(module.subprocess, "run", run)
    result = RasPortableDocker.execute_request(path)
    assert result.success
    assert result.receipt.execution_id == "job-a"


def test_docker_rejects_inspected_digest_mismatch(tmp_path, monkeypatch):
    path = _request(tmp_path, "job-a")

    def run(command, **kwargs):
        if command[1:3] == ("image", "inspect"):
            wrong = "registry.example/hecras/steady@sha256:" + "f" * 64
            return subprocess.CompletedProcess(command, 0, json.dumps([wrong]), "")
        raise AssertionError("container must not start")

    module = importlib.import_module("ras_commander.remote.RasPortableDocker")
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="RepoDigests"):
        RasPortableDocker.execute_request(path)


def test_trusted_receipt_validation_rejects_result_hdf_tamper(tmp_path):
    path = _request(tmp_path, "job-a")
    request = RasExecutionRequest.read(path)
    _, output = request.resolve_paths(path)
    receipt_path = _receipt(path).write(output / "execution_receipt.json")
    (output / "runtime_project" / "model.p01.hdf").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="digest does not match bytes"):
        validate_execution_receipt(
            path,
            receipt_path,
            expected_runtime_identity=request.container_identity,
            verify_result_hdf_digest=True,
        )


def test_normal_receipt_validation_does_not_rehash_files(tmp_path, monkeypatch):
    path = _request(tmp_path, "job-a")
    request = RasExecutionRequest.read(path)
    _, output = request.resolve_paths(path)
    receipt_path = _receipt(path).write(output / "execution_receipt.json")
    contract = importlib.import_module("ras_commander.remote.ExecutionContract")

    def unexpected_hash(*args, **kwargs):
        raise AssertionError("normal receipt validation must not rehash payload files")

    monkeypatch.setattr(contract, "sha256_file", unexpected_hash)
    assert validate_execution_receipt(path, receipt_path).success


def test_docker_timeout_forcibly_removes_named_container(tmp_path, monkeypatch):
    path = _request(tmp_path, "job-a")
    calls = []

    def run(command, **kwargs):
        calls.append(tuple(command))
        if command[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps([OCI]), "")
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        if command[1:3] == ("container", "inspect"):
            return subprocess.CompletedProcess(command, 1, "", "not found")
        return subprocess.CompletedProcess(command, 0, "", "")

    module = importlib.import_module("ras_commander.remote.RasPortableDocker")
    monkeypatch.setattr(module.subprocess, "run", run)
    result = RasPortableDocker.execute_request(path)

    assert not result.success
    assert any(call[1:3] == ("rm", "--force") for call in calls)
    assert "cleanup" not in result.error


def test_docker_pool_is_bounded_ordered_and_retains_failures(tmp_path, monkeypatch):
    paths = [_request(tmp_path, f"job-{index}") for index in range(4)]
    active = 0
    peak = 0
    lock = threading.Lock()

    def compute(path, **kwargs):
        nonlocal active, peak
        execution_id = RasExecutionRequest.read(path).execution_id
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return PortableDockerExecutionResult(
            execution_id=execution_id,
            success=execution_id != "job-2",
            returncode=0 if execution_id != "job-2" else 1,
            command=(),
        )

    monkeypatch.setattr(RasPortableDocker, "execute_request", compute)
    result = RasPortableDocker.execute_pool(paths, max_concurrent=2)

    assert list(result.results) == ["job-0", "job-1", "job-2", "job-3"]
    assert peak == 2
    assert not result.success
    assert not result.results["job-2"].success


def test_docker_pool_rejects_duplicate_execution_ids(tmp_path):
    path = _request(tmp_path, "job-a")
    with pytest.raises(ValueError, match="unique execution_id"):
        RasPortableDocker.execute_pool([path, path])


def test_docker_pool_rejects_distinct_requests_with_same_output(tmp_path):
    path = _request(tmp_path, "job-a")
    request = RasExecutionRequest.read(path)
    second_payload = request.to_dict()
    second_payload["execution_id"] = "job-b"
    second = RasExecutionRequest.from_dict(second_payload).write(
        path.parent / "request-b.json"
    )
    with pytest.raises(ValueError, match="output directories must be unique"):
        RasPortableDocker.execute_pool([path, second])


def test_slurm_render_stages_portable_relative_bundles(tmp_path):
    requests = [_request(tmp_path / "inputs", f"job-{index}") for index in range(2)]
    submission = RasSlurm.render_submission(
        requests,
        tmp_path / "submission",
        site=_site(slots_per_node=8, modules=("apptainer/1.3",)),
        submission_id="ble-steady",
    )
    payload = json.loads((submission.submission_directory / "slurm_batch.json").read_text())
    script = (submission.submission_directory / "submit.sbatch").read_text()

    assert payload["request_paths"] == [
        "bundles/job-0/request.json",
        "bundles/job-1/request.json",
    ]
    assert str(tmp_path) not in json.dumps(payload)
    assert "#SBATCH --ntasks=8" in script
    assert "#SBATCH --cpus-per-task=1" in script
    assert "#SBATCH --exclusive" in script
    assert "--mem-per-cpu" not in script
    assert "portable_slurm_launcher.py" in script
    # Slurm executes a spool copy of the script, so dirname($0) is not the
    # submission directory. submit() supplies the working directory instead.
    assert "dirname" not in script
    assert payload["launcher"]["version"] == "ras-portable-slurm-launcher/v1"
    assert "module load apptainer/1.3" in script
    assert all(path.is_file() for path in submission.request_paths)
    rehydrated = type(submission).read(
        submission.submission_directory / "slurm_submission.json"
    )
    assert rehydrated == submission


@pytest.mark.parametrize(
    "kwargs",
    [
        {"partition": "normal; rm -rf /"},
        {"modules": ("apptainer;touch /tmp/x",)},
        {"python_executable": "python;false"},
        {"apptainer_image": "/opt/../evil.sif"},
    ],
)
def test_slurm_site_rejects_shell_injection(kwargs):
    with pytest.raises(ValueError):
        _site(**kwargs)


def test_slurm_ssh_stage_submit_status_cancel_and_collect(tmp_path, monkeypatch):
    original = _request(tmp_path / "inputs", "job-a")
    rendered = RasSlurm.render_submission(
        [original], tmp_path / "submission", site=_site(), submission_id="test-run"
    )
    transport = SlurmTransportConfig(
        mode="ssh",
        hostname="clb12",
        username="runner",
        remote_scratch="/scratch/ras-commander",
        port=2222,
        identity_file="C:/keys/worker_ed25519",
    )
    calls = []
    step_name = json.loads(
        (rendered.submission_directory / "slurm_batch.json").read_text()
    )["steps"][0]["step_name"]

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        executable = command[0]
        if executable == "ssh" and "sbatch" in command:
            return subprocess.CompletedProcess(command, 0, "9876;cluster\n", "")
        if executable == "ssh" and "sacct" in command:
            output = (
                "9876|test-run|COMPLETED|0:0||00:01:23\n"
                f"9876.0|{step_name}|COMPLETED|0:0|1750M|00:00:20\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if executable == "rsync" and command[1] == "--archive":
            staged_path = rendered.request_paths[0]
            request = RasExecutionRequest.read(staged_path)
            _, output = request.resolve_paths(staged_path)
            if "output/job-a" in " ".join(command):
                _receipt(
                    staged_path, runtime_identity=f"sif:sha256:{SIF_SHA}"
                ).write(output / "execution_receipt.json")
        return subprocess.CompletedProcess(command, 0, "", "")

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)
    staged = RasSlurm.stage(rendered, transport)
    submitted = RasSlurm.submit(staged)
    status = RasSlurm.status(submitted)
    assert RasSlurm.cancel(submitted)
    collection = RasSlurm.collect(submitted)

    assert submitted.job_id == "9876"
    assert submitted.remote_directory == "/scratch/ras-commander/test-run"
    assert status.allocation_state == "COMPLETED"
    assert status.records[1].max_rss == "1750M"
    assert collection.success
    assert collection.accounting.records[1].exit_code == "0:0"
    assert all(kwargs.get("shell") is False for _, kwargs in calls)
    assert any(command[0] == "rsync" for command, _ in calls)
    mkdir_call = next(command for command, _ in calls if "mkdir" in command)
    assert mkdir_call[-2:] == ("mkdir", "/scratch/ras-commander/test-run")
    assert all("--delete" not in command for command, _ in calls)
    submit_call = next(command for command, _ in calls if "sbatch" in command)
    assert str(tmp_path) not in " ".join(submit_call)


def test_slurm_scp_stage_copies_finite_rendered_entries(tmp_path, monkeypatch):
    original = _request(tmp_path / "inputs", "job-a")
    rendered = RasSlurm.render_submission(
        [original], tmp_path / "submission", site=_site(), submission_id="scp-run"
    )
    transport = SlurmTransportConfig(
        mode="ssh",
        transfer_mode="scp",
        hostname="clb12",
        username="runner",
        remote_scratch="/scratch/ras-commander",
        port=2222,
        identity_file="C:/keys/worker_ed25519",
        scp_executable="scp.exe",
    )
    calls = []

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)

    staged = RasSlurm.stage(rendered, transport)

    scp = next(command for command, _ in calls if command[0] == "scp.exe")
    assert scp[:7] == (
        "scp.exe",
        "-r",
        "-P",
        "2222",
        "-i",
        "C:/keys/worker_ed25519",
        str(rendered.submission_directory / "bundles"),
    )
    assert str(rendered.submission_directory / "portable_slurm_launcher.py") in scp
    assert str(rendered.submission_directory / "slurm_batch.json") in scp
    assert str(rendered.submission_directory / "submit.sbatch") in scp
    assert all("slurm_submission.json" not in argument for argument in scp)
    assert scp[-1] == "runner@clb12:/scratch/ras-commander/scp-run/"
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    rehydrated = SlurmSubmission.read(
        staged.submission_directory / "slurm_submission.json"
    )
    assert rehydrated.transport.transfer_mode == "scp"
    assert rehydrated.transport.scp_executable == "scp.exe"


def test_slurm_scp_stage_fails_closed_on_transfer_error(tmp_path, monkeypatch):
    original = _request(tmp_path / "inputs", "job-a")
    rendered = RasSlurm.render_submission(
        [original], tmp_path / "submission", site=_site(), submission_id="scp-fail"
    )
    transport = SlurmTransportConfig(
        mode="ssh",
        transfer_mode="scp",
        hostname="clb12",
        username="runner",
        remote_scratch="/scratch/ras-commander",
    )

    def run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1 if command[0] == "scp" else 0, "", "copy rejected"
        )

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="scp staging failed: copy rejected"):
        RasSlurm.stage(rendered, transport)


def test_slurm_scp_collects_remote_output_contents_and_validates(
    tmp_path, monkeypatch
):
    original = _request(tmp_path / "inputs", "job-a")
    rendered = RasSlurm.render_submission(
        [original], tmp_path / "submission", site=_site(), submission_id="scp-collect"
    )
    transport = SlurmTransportConfig(
        mode="ssh",
        transfer_mode="scp",
        hostname="clb12",
        username="runner",
        remote_scratch="/scratch/ras-commander",
        port=2222,
        identity_file="C:/keys/worker_ed25519",
    )
    remote = SlurmSubmission(
        submission_id=rendered.submission_id,
        submission_directory=rendered.submission_directory,
        request_paths=rendered.request_paths,
        site=rendered.site,
        batch_sha256=rendered.batch_sha256,
        launcher_sha256=rendered.launcher_sha256,
        submit_sha256=rendered.submit_sha256,
        launcher_version=rendered.launcher_version,
        transport=transport,
        remote_directory="/scratch/ras-commander/scp-collect",
    )
    calls = []

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        request_path = rendered.request_paths[0]
        _, output = RasExecutionRequest.read(request_path).resolve_paths(request_path)
        _receipt(
            request_path, runtime_identity=f"sif:sha256:{SIF_SHA}"
        ).write(output / "execution_receipt.json")
        return subprocess.CompletedProcess(command, 0, "", "")

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)

    collection = RasSlurm.collect(remote)

    request = RasExecutionRequest.read(rendered.request_paths[0])
    _, output = request.resolve_paths(rendered.request_paths[0])
    command, kwargs = calls[0]
    assert collection.success
    assert command[:6] == (
        "scp",
        "-r",
        "-P",
        "2222",
        "-i",
        "C:/keys/worker_ed25519",
    )
    assert command[-2] == (
        "runner@clb12:/scratch/ras-commander/scp-collect/"
        "bundles/job-a/output/job-a/."
    )
    assert command[-1] == str(output)
    assert kwargs["shell"] is False


def test_slurm_remote_collect_is_best_effort_per_request(tmp_path, monkeypatch):
    originals = [_request(tmp_path / "inputs", f"job-{index}") for index in range(2)]
    rendered = RasSlurm.render_submission(
        originals, tmp_path / "submission", site=_site(), submission_id="collect"
    )
    transport = SlurmTransportConfig(
        mode="ssh",
        hostname="clb12",
        username="runner",
        remote_scratch="/scratch/ras",
    )
    remote = SlurmSubmission(
        submission_id=rendered.submission_id,
        submission_directory=rendered.submission_directory,
        request_paths=rendered.request_paths,
        site=rendered.site,
        batch_sha256=rendered.batch_sha256,
        launcher_sha256=rendered.launcher_sha256,
        submit_sha256=rendered.submit_sha256,
        launcher_version=rendered.launcher_version,
        transport=transport,
        remote_directory="/scratch/ras/collect",
    )

    def run(command, **kwargs):
        text = " ".join(command)
        if "bundles/job-0/output/job-0" in text:
            return subprocess.CompletedProcess(command, 23, "", "missing")
        if "bundles/job-1/output/job-1" in text:
            path = rendered.request_paths[1]
            _, output = RasExecutionRequest.read(path).resolve_paths(path)
            _receipt(path, runtime_identity=f"sif:sha256:{SIF_SHA}").write(
                output / "execution_receipt.json"
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)

    collection = RasSlurm.collect(remote)

    assert collection.receipts["job-0"] is None
    assert collection.receipts["job-1"].success
    assert "rsync" in collection.errors["job-0"]


def test_slurm_transport_rejects_remote_shell_metacharacters():
    with pytest.raises(ValueError):
        SlurmTransportConfig(transfer_mode="sftp")
    with pytest.raises(ValueError):
        SlurmTransportConfig(scp_executable="scp;false")
    with pytest.raises(ValueError):
        SlurmTransportConfig(
            mode="ssh",
            hostname="host;false",
            username="runner",
            remote_scratch="/scratch/jobs",
        )
    with pytest.raises(ValueError):
        SlurmTransportConfig(
            mode="ssh",
            hostname="host",
            username="runner",
            remote_scratch="/scratch/jobs;false",
        )
    with pytest.raises(ValueError):
        SlurmTransportConfig(
            mode="ssh",
            hostname="host",
            username="runner",
            remote_scratch="/scratch/../jobs",
        )
    with pytest.raises(ValueError):
        SlurmTransportConfig(
            mode="ssh",
            hostname="host",
            username="runner",
            remote_scratch="/scratch/jobs:alternate",
        )


def test_standalone_launcher_uses_sif_digest_as_attestation(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    batch_path = rendered.submission_directory / "slurm_batch.json"
    payload = json.loads(batch_path.read_text())
    sif = tmp_path / "image.sif"
    sif.write_bytes(b"image")
    payload["site"]["apptainer_image"] = str(sif)
    # The qualification digest intentionally differs from these local bytes.
    # The launcher validates a regular non-symlink path without rescanning it.
    payload["site"]["apptainer_image_sha256"] = "f" * 64
    payload["steps"][0]["execution_id"] = "../../escape"
    batch_path.write_text(json.dumps(payload))
    launcher = importlib.import_module(
        "ras_commander.remote.portable_slurm_launcher"
    )

    with pytest.raises(ValueError, match="Unsafe execution_id"):
        launcher.run(batch_path)

    failure = json.loads(
        (rendered.submission_directory / "launcher_failure.json").read_text()
    )
    assert failure["reason_code"] == "SLURM_BATCH_STEP_INVALID"
    assert not (tmp_path / "escape").exists()


def test_standalone_launcher_starts_process_with_empty_output(tmp_path, monkeypatch):
    launcher = importlib.import_module(
        "ras_commander.remote.portable_slurm_launcher"
    )
    bundle = tmp_path / "bundle"
    output = bundle / "results"
    output.mkdir(parents=True)

    def run(command, **kwargs):
        assert not tuple(output.iterdir())
        (output / "execution_receipt.json").write_text("{}")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(launcher.subprocess, "run", run)

    completed = launcher._run_step_process(
        ["srun"], bundle=bundle, output=output, timeout_seconds=30
    )
    assert completed.returncode == 0
    assert (output / "slurm_step.stdout.log").is_file()
    assert (output / "slurm_step.stderr.log").is_file()


def test_slurm_memory_flags_are_site_optional(tmp_path):
    path = _request(tmp_path, "job-a")
    submission = RasSlurm.render_submission(
        [path],
        tmp_path / "submission",
        site=_site(slurm_memory="3G"),
    )
    script = (submission.submission_directory / "submit.sbatch").read_text()
    assert "#SBATCH --mem=24G" in script
    assert "--mem-per-cpu" not in script


def test_slurm_single_slot_retry_reserves_only_one_task_budget(tmp_path):
    path = _request(tmp_path, "job-a")
    submission = RasSlurm.render_submission(
        [path],
        tmp_path / "submission",
        site=_site(slots_per_node=1, slurm_memory="3200M"),
    )

    script = (submission.submission_directory / "submit.sbatch").read_text()
    batch = json.loads((submission.submission_directory / "slurm_batch.json").read_text())

    assert "#SBATCH --ntasks=1" in script
    assert "#SBATCH --exclusive" in script
    assert "#SBATCH --mem=3200M" in script
    assert batch["site"]["slurm_memory"] == "3200M"


def test_slurm_submission_handle_rejects_noncanonical_state(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    payload = rendered.to_dict()
    payload["job_id"] = "42;false"
    with pytest.raises(ValueError, match="digits only"):
        SlurmSubmission.from_dict(payload)

    payload = rendered.to_dict()
    payload["transport"] = {
        **payload["transport"],
        "mode": "ssh",
        "hostname": "host",
        "username": "runner",
        "remote_scratch": "/scratch/jobs",
    }
    payload["remote_directory"] = "/scratch/jobs/wrong"
    with pytest.raises(ValueError, match="not canonical"):
        SlurmSubmission.from_dict(payload)

    payload = rendered.to_dict()
    payload["request_paths"] = [str(tmp_path / "outside" / "request.json")]
    with pytest.raises(ValueError, match="outside submission"):
        SlurmSubmission.from_dict(payload)


def test_slurm_lifecycle_rejects_tampered_batch(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    batch = rendered.submission_directory / "slurm_batch.json"
    batch.write_text(batch.read_text() + " ")

    with pytest.raises(ValueError, match="batch manifest digest"):
        RasSlurm.stage(rendered, SlurmTransportConfig())


def test_slurm_lifecycle_rejects_tampered_submit_script(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    script = rendered.submission_directory / "submit.sbatch"
    script.write_text(script.read_text() + "# tampered\n")

    with pytest.raises(ValueError, match="submit script digest"):
        RasSlurm.stage(rendered, SlurmTransportConfig())


def test_slurm_lifecycle_binds_full_request_digest(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    staged = rendered.request_paths[0]
    payload = json.loads(staged.read_text())
    payload["timeout_seconds"] += 1
    staged.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="request digest or contract"):
        RasSlurm.stage(rendered, SlurmTransportConfig())


def test_local_slurm_rejects_apptainer_bind_delimiter(tmp_path):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission,comma", site=_site()
    )

    with pytest.raises(ValueError, match="bind host paths"):
        RasSlurm.stage(rendered, SlurmTransportConfig())


def test_slurm_status_uses_squeue_for_active_job(tmp_path, monkeypatch):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    submission = type(rendered)(
        submission_id=rendered.submission_id,
        submission_directory=rendered.submission_directory,
        request_paths=rendered.request_paths,
        site=rendered.site,
        batch_sha256=rendered.batch_sha256,
        launcher_sha256=rendered.launcher_sha256,
        submit_sha256=rendered.submit_sha256,
        launcher_version=rendered.launcher_version,
        transport=rendered.transport,
        job_id="42",
    )

    def run(command, **kwargs):
        if command[0] == "sacct":
            return subprocess.CompletedProcess(command, 1, "", "not in accounting")
        if command[0] == "squeue":
            return subprocess.CompletedProcess(command, 0, "PENDING\n", "")
        raise AssertionError(command)

    module = importlib.import_module("ras_commander.RasSlurm")
    monkeypatch.setattr(module.subprocess, "run", run)

    assert RasSlurm.status(submission).allocation_state == "PENDING"


def test_slurm_collect_rejects_duplicate_correlated_step_records(
    tmp_path, monkeypatch
):
    path = _request(tmp_path, "job-a")
    rendered = RasSlurm.render_submission(
        [path], tmp_path / "submission", site=_site()
    )
    request_path = rendered.request_paths[0]
    _, output = RasExecutionRequest.read(request_path).resolve_paths(request_path)
    _receipt(request_path, runtime_identity=f"sif:sha256:{SIF_SHA}").write(
        output / "execution_receipt.json"
    )
    step_name = json.loads(
        (rendered.submission_directory / "slurm_batch.json").read_text()
    )["steps"][0]["step_name"]
    submitted = SlurmSubmission(
        submission_id=rendered.submission_id,
        submission_directory=rendered.submission_directory,
        request_paths=rendered.request_paths,
        site=rendered.site,
        batch_sha256=rendered.batch_sha256,
        launcher_sha256=rendered.launcher_sha256,
        submit_sha256=rendered.submit_sha256,
        launcher_version=rendered.launcher_version,
        transport=rendered.transport,
        job_id="42",
    )
    duplicate = SlurmTaskAccounting(
        "42.1", step_name, "COMPLETED", "0:0", "1G", "00:01:00"
    )
    monkeypatch.setattr(
        RasSlurm,
        "status",
        lambda submission: SlurmStatus("COMPLETED", (duplicate, duplicate)),
    )

    collection = RasSlurm.collect(submitted)

    assert not collection.success
    assert collection.receipts["job-a"] is None
    assert "exactly one" in collection.errors["job-a"]
