"""Host Docker transport tests; real solver qualification is a separate step.

The subprocess boundary is replaced here so argument, receipt and cleanup
behavior can be checked without running Docker or HEC-RAS.
"""

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ras_commander.RasDocker import ContainerResult, RasDocker


module = importlib.import_module("ras_commander.RasDocker")


@pytest.fixture(autouse=True)
def transport_boundary(monkeypatch):
    # Keep these argument/receipt tests independent of process I/O. The real
    # streaming helper is exercised with live subprocesses in its own suite.
    def transport(command, timeout, on_line):
        return module.subprocess.run(command, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace",
                                     shell=False, timeout=timeout)
    monkeypatch.setattr(module, "run_streaming", transport)


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "model folder with spaces"
    folder.mkdir()
    prj = folder / "Example Model.prj"
    prj.write_text("Proj Title=Transport fixture\n", encoding="utf-8")
    return prj


def _receipt(project_file, arguments, **changes):
    run_id = arguments[arguments.index("--run-id") + 1]
    stage = arguments[arguments.index("--project") - 1]
    plan = arguments[arguments.index("--plan") + 1]
    suffixes = (
        (f".p{plan}.tmp.hdf", f".b{plan}", f".x{plan}")
        if stage == "prepare"
        else (f".p{plan}.hdf",)
    )
    artifacts = []
    for suffix in suffixes:
        artifact = project_file.with_suffix(suffix)
        artifact.write_bytes(f"{stage}:{suffix}".encode())
        artifacts.append({
            "path": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        })
    receipt = {
        "schema": "ras-commander-job/v1", "run_id": run_id, "command": stage,
        "project": project_file.name, "plan": plan, "status": "succeeded",
        "geometry": plan,
        "runtime": {
            "kind": "wine" if stage == "prepare" else "native",
            "hec_ras_version": "6.5",
        },
        "result": (
            {"timed_out": False, "full_result_copied": False}
            if stage == "prepare"
            else {"success": True, "completion_verified": True}
        ),
        "artifacts": artifacts,
    }
    changes = dict(changes)
    runtime_change = changes.get("runtime")
    if isinstance(runtime_change, dict) and set(runtime_change) == {"hec_ras_version"}:
        receipt["runtime"].update(changes.pop("runtime"))
    receipt.update(changes)
    path = project_file.parent / ".ras-commander" / "runs" / run_id / f"{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def _fake_run(monkeypatch, project, *, changes=None, returncode=0, mutate=None):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        receipt = _receipt(project, command, **(changes or {}))
        if mutate is not None:
            mutate(receipt, project)
        return subprocess.CompletedProcess(command, returncode, "container output", "diagnostic output")

    monkeypatch.setattr(module.subprocess, "run", run)
    return calls


def test_prepare_command_preserves_spaces_and_readonly_sibling_mounts(monkeypatch, project):
    terrain = project.parent.parent / "source terrain"
    projection = project.parent.parent / "projection"
    terrain.mkdir()
    projection.mkdir()
    calls = _fake_run(monkeypatch, project)
    result = RasDocker.preprocess_plan(
        project, 1, mounts={"/source_terrain": terrain, "/projection": projection},
        pull="always", run_id="prepare-space-path", num_cores=4,
    )
    assert result and isinstance(result, ContainerResult)
    command, kwargs = calls[0]
    assert command[:5] == ["docker", "run", "--rm", "--pull", "always"]
    assert f"type=bind,src={project.parent},dst=/job" in command
    assert f"type=bind,src={terrain},dst=/source_terrain,readonly" in command
    assert f"type=bind,src={projection},dst=/projection,readonly" in command
    assert "rascommander/hec-ras-wine-precompute_6.5:v4" in command
    assert command[command.index("--project") + 1] == "/job/Example Model.prj"
    assert command[command.index("--plan") + 1] == "01"
    assert command[command.index("--num-cores") + 1] == "4"
    assert command[command.index("--cpus") + 1] == "4"
    assert "--replace-generated" not in command
    assert kwargs["shell"] is False and kwargs["timeout"] == 1020
    assert result.stage == "prepare" and result.plan_number == "01"
    assert result.receipt_path.name == "prepare.json"
    assert result.stdout == "container output"
    assert result.stderr == "diagnostic output"


@pytest.mark.skipif(os.name != "nt", reason="Mapped-drive behavior is Windows-specific")
def test_mapped_drive_form_survives_mount_receipt_result_and_batch_display(monkeypatch, project):
    dependency = project.parent.parent / "mapped dependency"
    dependency.mkdir()
    expected_project = project.absolute()
    expected_dependency = dependency.absolute()
    real_resolve = Path.resolve

    def resolve_to_unc(path, strict=False):
        resolved = real_resolve(path, strict=strict)
        if resolved.drive and not str(resolved).startswith("\\\\"):
            return Path(r"\\server\mapped") / Path(*resolved.parts[1:])
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve_to_unc)
    captured_identity = {}

    def miss_resume(_project, _plan, _stage, identity):
        captured_identity.update(identity)
        return None

    monkeypatch.setattr(module, "find_resume", miss_resume)
    monkeypatch.setattr(module, "record_resume", lambda *_args: None)
    calls = _fake_run(monkeypatch, project)
    batch = RasDocker.run_batch([{
        "project_path": project,
        "plan_number": 1,
        "mounts": {"/dependency": dependency},
        "run_id": "mapped-drive",
    }], stage="prepare", resume=True)

    prepared, computed = batch.results[0]
    assert prepared and computed is None
    assert prepared.project_path == expected_project
    assert prepared.receipt_path.drive == expected_project.drive
    assert not str(prepared.receipt_path).startswith("\\\\")
    command = calls[0][0]
    assert f"type=bind,src={expected_project.parent},dst=/job" in command
    assert f"type=bind,src={expected_dependency},dst=/dependency,readonly" in command
    assert captured_identity["mounts"]["/dependency"] == str(expected_dependency)
    row = batch.summary_df.iloc[0]
    assert row.project_path == str(expected_project)
    assert Path(row.prepare_receipt).drive == expected_project.drive
    assert not row.prepare_receipt.startswith("\\\\")


def test_compute_passes_cores_and_explicit_preparation_receipt(monkeypatch, project):
    preparation = project.parent / ".ras-commander" / "runs" / "prior" / "prepare.json"
    preparation.parent.mkdir(parents=True)
    preparation.write_text("{}", encoding="utf-8")
    calls = _fake_run(monkeypatch, project, changes={"runtime": {"hec_ras_version": "6.6"}})
    result = RasDocker.compute_plan(
        project, "02", version="6.6", num_cores=3, timeout=60,
        replace_generated=True, prepare_receipt=preparation, user="1000:1000",
        docker_executable="C:/Program Files/Docker/docker.exe", pull="never",
    )
    assert result
    command, kwargs = calls[0]
    assert command[0] == "C:/Program Files/Docker/docker.exe"
    assert "rascommander/hec-ras-linux-unsteady_6.6:v1" in command
    assert command[command.index("--num-cores") + 1] == "3"
    assert command[command.index("--cpus") + 1] == "3"
    assert command[command.index("--prepare-receipt") + 1] == "/job/.ras-commander/runs/prior/prepare.json"
    assert command[command.index("--user") + 1] == "1000:1000"
    assert command[-1] == "--replace-generated"
    assert kwargs["timeout"] == 180


@pytest.mark.parametrize("kwargs", [
    {"version": "7.0"}, {"timeout": 0}, {"timeout": True}, {"timeout": 1.5},
    {"num_cores": 0}, {"num_cores": True}, {"num_cores": 9}, {"num_cores": 2.5},
    {"resume": "yes"}, {"pull": "sometimes"},
    {"replace_generated": "yes"}, {"run_id": "../escape"}, {"run_id": ".hidden"},
    {"run_id": "a" * 65}, {"image": "--privileged"}, {"image": "image extra"},
    {"image": "rascommander/hec-ras-wine-precompute_6.6:v4"},
    {"image": "rascommander/hec-ras-linux-unsteady_6.5:v1"},
    {"docker_executable": ""}, {"user": "root\nother"},
])
def test_invalid_configuration_fails_before_docker(monkeypatch, project, kwargs):
    calls = _fake_run(monkeypatch, project)
    with pytest.raises((ValueError, TypeError)):
        RasDocker.preprocess_plan(project, "01", **kwargs)
    assert calls == []
    assert not (project.parent / ".ras-commander").exists()


@pytest.mark.parametrize("plan", [True, 1.5, "00", "100", "p01", "1 --privileged"])
def test_invalid_plan_rejected(monkeypatch, project, plan):
    calls = _fake_run(monkeypatch, project)
    with pytest.raises(ValueError):
        RasDocker.preprocess_plan(project, plan)
    assert not calls


@pytest.mark.parametrize("destination", ["/", "/job", "/job/nested", "/runtime/wine-seed", "/usr/local", "relative", "/data/../job", "//host", "/data\\job", "/data,readonly=false"])
def test_mount_destination_cannot_override_runtime_or_project(monkeypatch, project, destination):
    calls = _fake_run(monkeypatch, project)
    with pytest.raises(ValueError):
        RasDocker.preprocess_plan(project, "01", mounts={destination: project.parent})
    assert not calls


def test_overlapping_mounts_and_csv_delimiters_rejected(monkeypatch, project):
    calls = _fake_run(monkeypatch, project)
    with pytest.raises(ValueError, match="Overlapping"):
        RasDocker.preprocess_plan(project, 1, mounts={"/data": project.parent, "/data/nested": project.parent})
    source = project.parent.parent / "data,with-comma"
    source.mkdir()
    with pytest.raises(ValueError, match="commas"):
        RasDocker.preprocess_plan(project, 1, mounts={"/data": source})
    assert not calls


def test_missing_mount_and_non_project_input_rejected(monkeypatch, project):
    calls = _fake_run(monkeypatch, project)
    with pytest.raises(FileNotFoundError):
        RasDocker.preprocess_plan(project, 1, mounts={"/terrain": project.parent / "missing"})
    with pytest.raises(ValueError, match=".prj"):
        RasDocker.preprocess_plan(project.parent, 1)
    assert not calls


@pytest.mark.parametrize("changes, error", [
    ({"run_id": "old-run"}, "run_id"), ({"plan": "02"}, "plan"),
    ({"project": "Another.prj"}, "project"), ({"command": "compute"}, "command"),
    ({"runtime": {"hec_ras_version": "6.6"}}, "version"),
    ({"hec_ras_version": "7.0.1"}, "version"),
    ({"status": "failed", "error": {"message": "Missing terrain"}}, "does not report success"),
])
def test_receipt_identity_and_failure_status_are_not_success(monkeypatch, project, changes, error):
    _fake_run(monkeypatch, project, changes=changes)
    result = RasDocker.preprocess_plan(project, 1)
    assert not result and error in result.error
    assert result.receipt_path.is_file()
    for key, value in changes.items():
        if isinstance(value, dict):
            assert all(result.receipt[key][name] == item for name, item in value.items())
        else:
            assert result.receipt[key] == value


@pytest.mark.parametrize("changes, error", [
    ({"schema": "custom-job/v1"}, "schema"),
    ({"runtime": {"kind": "wine"}}, "version"),
    ({"runtime": {"kind": "native", "hec_ras_version": "6.5"}}, "runtime kind"),
    ({"result": None}, "stage result"),
    ({"result": {"timed_out": True, "full_result_copied": False}}, "incomplete"),
    ({"result": {"timed_out": False, "full_result_copied": True}}, "fallback"),
    ({"artifacts": []}, "artifact inventory"),
    ({"artifacts": [{"path": "Example.p01.tmp.hdf"}]}, "malformed artifact"),
])
def test_prepare_receipt_requires_complete_success_contract(monkeypatch, project, changes, error):
    _fake_run(monkeypatch, project, changes=changes)
    result = RasDocker.preprocess_plan(project, 1, image="custom-preparer:local")
    assert not result and error in result.error


def test_matching_custom_receipt_without_worker_evidence_is_not_success(monkeypatch, project):
    _fake_run(monkeypatch, project, changes={
        "schema": None,
        "runtime": {"kind": "custom", "hec_ras_version": "6.5"},
        "result": {},
        "artifacts": [],
    })
    result = RasDocker.preprocess_plan(project, 1, image="custom-preparer:local")
    assert not result
    assert "schema" in result.error
    assert "runtime kind" in result.error
    assert "incomplete" in result.error
    assert "artifact inventory" in result.error


@pytest.mark.parametrize("stage_result", [
    None,
    {"success": False, "completion_verified": True},
    {"success": True, "completion_verified": False},
])
def test_compute_receipt_requires_verified_success(monkeypatch, project, stage_result):
    _fake_run(monkeypatch, project, changes={"result": stage_result})
    result = RasDocker.compute_plan(project, 1, image="custom-compute:local")
    assert not result and ("stage result" in result.error or "successful completion" in result.error)


@pytest.mark.parametrize("failure", ["missing", "size", "sha256", "escape"])
def test_receipt_artifacts_must_match_confined_regular_files(monkeypatch, project, failure):
    outside = project.parent.parent / "outside.tmp.hdf"
    outside.write_bytes(b"outside")

    def mutate(receipt_path, project_file):
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact = payload["artifacts"][0]
        target = project_file.parent / artifact["path"]
        if failure == "missing":
            target.unlink()
        elif failure == "size":
            artifact["size_bytes"] += 1
        elif failure == "sha256":
            artifact["sha256"] = "0" * 64
        else:
            artifact["path"] = "../outside.tmp.hdf"
        receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    _fake_run(monkeypatch, project, mutate=mutate)
    result = RasDocker.preprocess_plan(project, 1, image="custom-preparer:local")
    assert not result
    if failure == "missing":
        assert "cannot find" in result.error.lower() or "no such file" in result.error.lower()
    elif failure == "size":
        assert "size does not match" in result.error
    elif failure == "sha256":
        assert "SHA-256 does not match" in result.error
    else:
        assert "malformed artifact inventory" in result.error


def test_receipt_actual_artifacts_are_accepted(monkeypatch, project):
    _fake_run(monkeypatch, project)
    result = RasDocker.preprocess_plan(project, 1, image="custom-preparer:local")
    assert result
    assert len(result.receipt["artifacts"]) == 3


def test_nonzero_docker_exit_rejects_successful_receipt(monkeypatch, project):
    _fake_run(monkeypatch, project, returncode=125)
    result = RasDocker.preprocess_plan(project, 1)
    assert not result and result.returncode == 125
    assert result.receipt["status"] == "succeeded"
    assert "125" in result.error


@pytest.mark.parametrize("payload", [None, "not json", "[]"])
def test_missing_or_malformed_receipt_rejected(monkeypatch, project, payload):
    def run(command, **kwargs):
        if payload is not None:
            path = _receipt(project, command)
            path.write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"success": true}', "")
    monkeypatch.setattr(module.subprocess, "run", run)
    result = RasDocker.preprocess_plan(project, 1)
    assert not result and "receipt" in result.error
    assert result.receipt == {}


def test_existing_run_id_and_failed_launch_claim_cannot_be_reused(monkeypatch, project):
    old = project.parent / ".ras-commander" / "runs" / "old"
    old.mkdir(parents=True)
    (old / "prepare.json").write_text('{"status":"succeeded"}', encoding="utf-8")
    calls = []

    def missing_docker(command, **kwargs):
        calls.append(command)
        raise FileNotFoundError("Docker not installed")

    monkeypatch.setattr(module.subprocess, "run", missing_docker)
    with pytest.raises(FileExistsError):
        RasDocker.preprocess_plan(project, 1, run_id="old")
    failed = RasDocker.preprocess_plan(project, 1, run_id="failed-launch")
    assert not failed and "Could not launch Docker" in failed.error
    with pytest.raises(FileExistsError):
        RasDocker.preprocess_plan(project, 1, run_id="failed-launch")
    assert len(calls) == 1


@pytest.mark.parametrize("ownership_matches", [True, False])
def test_timeout_removes_only_owned_container_and_keeps_partial_output(monkeypatch, project, ownership_matches):
    calls = []
    owner = None
    container_id = "a" * 64

    def run(command, **kwargs):
        nonlocal owner
        calls.append(command)
        if command[1] == "run":
            owner = command[command.index("--label") + 1].split("=", 1)[1]
            Path(command[command.index("--cidfile") + 1]).write_text(container_id)
            _receipt(project, command)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial output", stderr=b"partial error")
        if command[1] == "inspect":
            labels = {module._OWNER_LABEL: owner if ownership_matches else "someone-else"}
            return subprocess.CompletedProcess(command, 0, json.dumps(labels), "")
        assert command == ["docker", "rm", "--force", container_id]
        return subprocess.CompletedProcess(command, 0, container_id, "")

    monkeypatch.setattr(module.subprocess, "run", run)
    result = RasDocker.preprocess_plan(project, 1, timeout=1)
    assert not result and "121s host timeout" in result.error
    assert result.returncode is None
    assert result.stdout == "partial output" and result.stderr == "partial error"
    assert result.receipt["status"] == "succeeded"  # A late receipt cannot override timeout.
    assert any(call[1] == "rm" for call in calls) is ownership_matches
    if not ownership_matches:
        assert "ownership-label mismatch" in result.error


def test_run_plan_stops_after_failed_preparation(monkeypatch, project):
    calls = _fake_run(monkeypatch, project, changes={"status": "failed"}, returncode=1)
    preparation, computation = RasDocker.run_plan(project, 1, run_id="pipeline")
    assert not preparation and computation is None
    assert len(calls) == 1


def test_run_plan_chains_explicit_receipt_and_separate_ids(monkeypatch, project):
    calls = _fake_run(monkeypatch, project)
    preparation, computation = RasDocker.run_plan(project, 1, run_id="pipeline", num_cores=4)
    assert preparation and computation
    assert [call[0][call[0].index("--run-id") + 1] for call in calls] == ["pipeline-prepare", "pipeline-compute"]
    assert "/job/.ras-commander/runs/pipeline-prepare/prepare.json" in calls[1][0]
    assert calls[1][0][calls[1][0].index("--num-cores") + 1] == "4"


def test_explicit_preparation_receipt_must_be_inside_project(monkeypatch, project):
    outside = project.parent.parent / "prepare.json"
    outside.write_text("{}", encoding="utf-8")
    calls = _fake_run(monkeypatch, project)
    with pytest.raises(ValueError, match="inside"):
        RasDocker.compute_plan(project, 1, prepare_receipt=outside)
    assert not calls


def test_version_evidence_is_checked_for_custom_image(monkeypatch, project):
    _fake_run(monkeypatch, project, changes={"runtime": {"hec_ras_version": "6.6"}})
    result = RasDocker.preprocess_plan(project, 1, image="local-test-image:custom")
    assert not result and "version" in result.error


@pytest.mark.parametrize("version", ["6.5", "6.6", "7.0.1"])
def test_run_plan_selects_matching_published_version_images(monkeypatch, project, version):
    calls = _fake_run(monkeypatch, project, changes={"runtime": {"hec_ras_version": version}})
    prepared, computed = RasDocker.run_plan(project, 1, version=version)
    assert prepared and computed
    assert f"rascommander/hec-ras-wine-precompute_{version}:v4" in calls[0][0]
    assert f"rascommander/hec-ras-linux-unsteady_{version}:v1" in calls[1][0]
    assert prepared.receipt["runtime"]["hec_ras_version"] == version
    assert computed.receipt["runtime"]["hec_ras_version"] == version


@pytest.mark.parametrize("requested, actual", [
    ("7.0.1", "6.5"), ("7.0.1", "6.6"), ("6.5", "7.0.1"), ("6.6", "7.0.1"),
])
@pytest.mark.parametrize("stage", ["prepare", "compute"])
def test_701_cannot_use_a_different_version_image_or_receipt(monkeypatch, project, requested, actual, stage):
    calls = _fake_run(monkeypatch, project, changes={"runtime": {"hec_ras_version": actual}})
    method = RasDocker.preprocess_plan if stage == "prepare" else RasDocker.compute_plan
    family, tag = ("wine-precompute", "v4") if stage == "prepare" else ("linux-unsteady", "v1")
    with pytest.raises(ValueError, match="stage/version"):
        method(project, 1, version=requested, image=f"rascommander/hec-ras-{family}_{actual}:{tag}")
    assert not calls
    result = method(project, 1, version=requested, image="local-qualification:custom")
    assert not result and "version does not match" in result.error
