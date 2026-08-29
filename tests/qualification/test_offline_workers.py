from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence.receipts import (
    read_json_with_digest,
    verify_attempt_receipt,
)
from scripts.qualification.execution_evidence.snapshots import snapshot_tree

from .offline_helpers import (
    last_json_line,
    make_captured_legacy_project,
    make_captured_legacy_replay,
    make_clean_runtime_repo,
    make_offline_manifest,
    make_unresolved_mixed_project,
    pinned_replay_files,
    run_offline_cli,
    runtime_environment,
)


pytestmark = [pytest.mark.qualification_harness, pytest.mark.offline_evidence]


@pytest.fixture(scope="module")
def completed_offline_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("offline-workers")
    runtime_repo, head = make_clean_runtime_repo(root)
    source_project = make_captured_legacy_project(root / "source")
    replay_root = make_captured_legacy_replay(root / "replay")
    manifest = make_offline_manifest(
        root,
        runtime_repo=runtime_repo,
        head=head,
        source_project=source_project,
        replay_root=replay_root,
    )
    run_root = root / "archive" / "run-001"
    planned = run_offline_cli(
        runtime_repo,
        "plan",
        "--manifest",
        str(manifest),
        "--run-root",
        str(run_root),
    )
    assert planned.returncode == 0, planned.stderr
    plan_output = last_json_line(planned.stdout)

    stage_one = run_offline_cli(runtime_repo, "stage", "--run-root", str(run_root))
    assert stage_one.returncode == 0, stage_one.stderr
    stage_two = run_offline_cli(runtime_repo, "stage", "--run-root", str(run_root))
    assert stage_two.returncode == 0, stage_two.stderr
    inspected = run_offline_cli(
        runtime_repo,
        "inspect",
        "--run-root",
        str(run_root),
        "--lane",
        "captured-legacy-41",
    )
    assert inspected.returncode == 0, inspected.stderr
    return {
        "root": root,
        "runtime_repo": runtime_repo,
        "source_project": source_project,
        "replay_root": replay_root,
        "manifest": manifest,
        "run_root": run_root,
        "plan_output": plan_output,
        "stage_outputs": [last_json_line(stage_one.stdout)[0], last_json_line(stage_two.stdout)[0]],
        "inspect_output": last_json_line(inspected.stdout)[0],
    }


def _attempt(run: dict, output: dict):
    path = (
        run["run_root"]
        / "attempts"
        / output["lane_id"]
        / output["attempt_id"]
    )
    return verify_attempt_receipt(path)


def test_plan_uses_distinct_archive_and_execution_roots_with_runtime_pins(
    completed_offline_run: dict,
) -> None:
    run = completed_offline_run
    descriptor, _ = read_json_with_digest(run["run_root"] / "run.json")
    source_manifest, source_sha = read_json_with_digest(
        run["run_root"] / "manifest.source.json"
    )
    normalized, normalized_sha = read_json_with_digest(
        run["run_root"] / "manifest.normalized.json"
    )

    assert descriptor["source_manifest_sha256"] == source_sha
    assert descriptor["normalized_manifest_sha256"] == normalized_sha
    assert descriptor["manifest_sha256"] == normalized["manifest_sha256"]
    assert source_manifest["repository"]["bind_running_code"] is True
    assert descriptor["bind_running_code"] is True
    assert descriptor["hec_ras_execution_enabled"] is False
    assert Path(descriptor["archive_run_root"]) == run["run_root"]
    execution_root = Path(descriptor["execution_run_root"])
    assert execution_root.parent == run["root"] / "execution"
    assert execution_root != run["run_root"]
    for field in (
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "pyarrow_version",
        "psutil_version",
        "ras_commander_version",
        "ras_commander_import_path",
    ):
        assert descriptor[field]


@pytest.mark.parametrize("field", ["bind_running_code", "require_clean"])
def test_plan_rejects_missing_mandatory_runtime_binding(
    completed_offline_run: dict,
    field: str,
) -> None:
    manifest = completed_offline_run["root"] / f"invalid-{field}.json"
    payload = json.loads(
        completed_offline_run["manifest"].read_text(encoding="utf-8")
    )
    payload["repository"][field] = False
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = run_offline_cli(
        completed_offline_run["runtime_repo"],
        "plan",
        "--manifest",
        str(manifest),
        "--run-root",
        str(completed_offline_run["root"] / "archive" / f"invalid-{field}"),
    )
    assert result.returncode != 0
    assert field in result.stderr


def test_stage_workers_are_fresh_and_byte_preserving(completed_offline_run: dict) -> None:
    run = completed_offline_run
    attempts = [_attempt(run, output) for output in run["stage_outputs"]]
    first, second = [attempt.receipt for attempt in attempts]

    assert first["worker_pid"] != second["worker_pid"]
    assert first["worker_instance_id"] != second["worker_instance_id"]
    assert first["worker_invocation_index"] == second["worker_invocation_index"] == 1
    assert first["hec_ras_invoked"] is second["hec_ras_invoked"] is False
    assert first["stage_result"]["publication_state"] == "published"
    assert second["stage_result"]["publication_state"] == "published"
    assert first["stage_result"]["source_fingerprint_before"] == first["stage_result"]["source_fingerprint_after"]
    assert {
        item["relative_path"] for item in first["replay_artifacts"]
    } == {"Model.O01", "Model.p01.comp_msgs.txt"}
    assert all(
        item["data_origin"] == "staged_execution_output"
        and item["source_sha256_before"] == item["source_sha256_after"]
        and item["sha256"] == item["source_sha256_before"]
        for item in first["replay_artifacts"]
    )
    first_request = attempts[0].request
    second_request = attempts[1].request
    assert first_request["required_invariants"] == ["R11"]
    assert second_request["required_invariants"] == ["R11"]
    assert first["required_invariants"] == ["R11"]
    assert first_request["stage_root"] != second_request["stage_root"]
    for request in (first_request, second_request):
        staged = Path(request["stage_root"]) / "Model.O01"
        assert staged.read_bytes() == (run["replay_root"] / "Model.O01").read_bytes()
    stage_origins = {
        row["data_origin"]
        for row in first["tables"]["artifacts"]
        if row["root_kind"] == "stage" and row["relative_path"] == "Model.O01"
    }
    source_origins = {
        row["data_origin"]
        for row in first["tables"]["artifacts"]
        if row["root_kind"] == "source" and row["relative_path"] == "Model.O01"
    }
    assert stage_origins == {"staged_execution_output"}
    assert source_origins == {"captured_real"}
    stage_project_origins = {
        row["data_origin"]
        for row in first["tables"]["artifacts"]
        if row["root_kind"] == "stage" and row["relative_path"] == "Model.prj"
    }
    stage_metadata_origins = {
        row["data_origin"]
        for row in first["tables"]["artifacts"]
        if row["root_kind"] == "stage"
        and row["relative_path"] == ".ras-commander/stage.json"
    }
    assert stage_project_origins == {"captured_real"}
    assert stage_metadata_origins == {"generated_harness_receipt"}


def test_offline_inspect_uses_public_evidence_api_and_is_read_only(
    completed_offline_run: dict,
) -> None:
    attempt = _attempt(completed_offline_run, completed_offline_run["inspect_output"])
    receipt = attempt.receipt
    assert receipt["action"] == "inspect"
    assert receipt["hec_ras_invoked"] is False
    assert attempt.request["required_invariants"] == ["R01", "R03", "R11"]
    assert receipt["evidence"]["mechanical_completion"]["value"] is True
    assert receipt["evidence"]["observations"]["completion_message_stored"]["value"] is True
    assert len(receipt["tables"]["observations"]) == 17
    invariant_status = {
        row["invariant_id"]: row["status"] for row in receipt["tables"]["invariants"]
    }
    assert invariant_status == {"R01": "pass", "R03": "pass", "R11": "pass"}
    lane_row = receipt["tables"]["lanes"][0]
    assert lane_row["compute_mode"] == "offline_inspect"
    event_apis = {row["api"] for row in receipt["tables"]["events"]}
    assert "stage_project" in event_apis
    assert "RasCmdr.inspect_execution_evidence" in event_apis
    references = {item["relative_path"] for item in receipt["referenced_artifacts"]}
    assert {"stdout.log", "stderr.log", "events.jsonl", "evidence.json"}.issubset(references)


def test_source_project_remains_immutable_across_all_workers(
    completed_offline_run: dict,
) -> None:
    run = completed_offline_run
    request = _attempt(run, run["stage_outputs"][0]).request
    snapshot = snapshot_tree(
        run["source_project"].parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="test_final",
        root_kind="source",
        data_origin="captured_real",
    )
    assert snapshot.content_fingerprint == request["source_snapshot_content_fingerprint"]
    assert snapshot.metadata_fingerprint == request["source_snapshot_metadata_fingerprint"]


def test_action_scoped_receipts_rebuild_and_verify_aggregates(
    completed_offline_run: dict,
) -> None:
    runtime_repo = completed_offline_run["runtime_repo"]
    run_root = completed_offline_run["run_root"]
    aggregated = run_offline_cli(
        runtime_repo,
        "aggregate",
        "--run-root",
        str(run_root),
    )
    assert aggregated.returncode == 0, aggregated.stderr
    counts = last_json_line(aggregated.stdout)
    assert counts["lanes"] >= 3
    assert counts["invariants"] >= 5
    verified = run_offline_cli(
        runtime_repo,
        "verify",
        "--run-root",
        str(run_root),
    )
    assert verified.returncode == 0, verified.stderr
    verified_counts = last_json_line(verified.stdout)
    assert verified_counts["lanes"] == counts["lanes"]
    assert verified_counts["invariants"] == counts["invariants"]


def test_exact_public_ambiguity_is_a_verified_expected_failure(
    tmp_path: Path,
) -> None:
    runtime_repo, head = make_clean_runtime_repo(tmp_path)
    source_project, replay_root = make_unresolved_mixed_project(
        tmp_path / "mixed-source"
    )
    manifest = make_offline_manifest(
        tmp_path,
        runtime_repo=runtime_repo,
        head=head,
        source_project=source_project,
        replay_root=replay_root,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    fixture = payload["fixtures"][0]
    fixture.update(
        {
            "fixture_id": "captured-mixed",
            "plan_title": "Mixed",
            "replay_artifacts": {
                "source_root": str(replay_root),
                "data_origin": "staged_execution_output",
                "files": pinned_replay_files(replay_root),
            },
        }
    )
    lane = payload["lanes"][0]
    lane.update(
        {
            "lane_id": "captured-mixed-unresolved",
            "fixture_id": "captured-mixed",
            "expected_terminal_category": "expected_failure",
            "expected_failure_reason_code": (
                "program_version_unresolved_multiple_formats"
            ),
            "required_invariants": ["R01", "R11"],
        }
    )
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_root = tmp_path / "archive" / "mixed-run"
    planned = run_offline_cli(
        runtime_repo,
        "plan",
        "--manifest",
        str(manifest),
        "--run-root",
        str(run_root),
    )
    assert planned.returncode == 0, planned.stderr
    inspected = run_offline_cli(
        runtime_repo,
        "inspect",
        "--run-root",
        str(run_root),
        "--lane",
        "captured-mixed-unresolved",
    )
    assert inspected.returncode == 0, inspected.stderr
    output = last_json_line(inspected.stdout)[0]
    attempt_dir = (
        run_root
        / "attempts"
        / output["lane_id"]
        / output["attempt_id"]
    )
    receipt = verify_attempt_receipt(attempt_dir).receipt

    assert receipt["terminal_category"] == "expected_failure"
    assert receipt["worker_exit_code"] == 10
    assert receipt["evidence"] is None
    assert receipt["tables"]["observations"] == []
    assert receipt["expected_failure"]["exception_type"] == (
        "ResultArtifactAmbiguityError"
    )
    assert receipt["expected_failure"]["reason_code"] == (
        "program_version_unresolved_multiple_formats"
    )
    assert receipt["expected_failure"]["hdf_mtime_ns"] is not None
    assert receipt["expected_failure"]["legacy_mtime_ns"] is not None
    invariant_status = {
        row["invariant_id"]: row["status"]
        for row in receipt["tables"]["invariants"]
    }
    assert invariant_status == {"R01": "pass", "R11": "pass"}
    assert receipt["tables"]["lanes"][0]["failure_reason_code"] == (
        "program_version_unresolved_multiple_formats"
    )
    expected_events = [
        row
        for row in receipt["tables"]["events"]
        if row["event_name"] == "expected_result_artifact_ambiguity"
    ]
    assert len(expected_events) == 1
    assert expected_events[0]["reason_code"] == (
        "program_version_unresolved_multiple_formats"
    )
    aggregated = run_offline_cli(
        runtime_repo,
        "aggregate",
        "--run-root",
        str(run_root),
    )
    assert aggregated.returncode == 0, aggregated.stderr
    assert last_json_line(aggregated.stdout)["lanes"] == 1
    verified = run_offline_cli(
        runtime_repo,
        "verify",
        "--run-root",
        str(run_root),
    )
    assert verified.returncode == 0, verified.stderr


def _run_probe(runtime_repo: Path, run_root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    code = r'''
import json, sys
from dataclasses import replace
from scripts.qualification.execution_evidence import offline_supervisor as supervisor
from scripts.qualification.execution_evidence.planning import load_run

run_root, mode = sys.argv[1], sys.argv[2]
context = load_run(run_root)
attempt, request, request_sha = supervisor.create_attempt_request(
    context, lane_id="captured-legacy-41", action="stage"
)
if mode == "crash":
    supervisor._worker_command = lambda request, path: [request["python_executable"], "-c", "import os; os._exit(7)"]
    verified = supervisor.supervise_request(attempt, request, request_sha, timeout_seconds=10)
    print(json.dumps({"terminal": verified.receipt["terminal_category"], "exit": verified.receipt["worker_exit_code"], "refs": verified.receipt["referenced_artifacts"]}))
elif mode == "timeout":
    supervisor._worker_command = lambda request, path: [request["python_executable"], "-c", "import time; time.sleep(60)"]
    verified = supervisor.supervise_request(attempt, request, request_sha, timeout_seconds=0.2)
    print(json.dumps({"terminal": verified.receipt["terminal_category"], "exit": verified.receipt["worker_exit_code"], "refs": verified.receipt["referenced_artifacts"]}))
elif mode == "exit_mismatch":
    original = supervisor._run_child
    def mismatched(*args, **kwargs):
        return replace(original(*args, **kwargs), returncode=7)
    supervisor._run_child = mismatched
    try:
        supervisor.supervise_request(attempt, request, request_sha, timeout_seconds=30)
    except supervisor.OfflineSupervisorError as exc:
        print(json.dumps({"rejected": True, "detail": str(exc)}))
    else:
        print(json.dumps({"rejected": False}))
elif mode == "runtime_pin":
    from scripts.qualification.execution_evidence.receipts import write_json_with_digest
    request["python_version"] = "0.0-invalid"
    request_sha = write_json_with_digest(
        attempt / "request.json", request, replace=True
    )
    verified = supervisor.supervise_request(
        attempt, request, request_sha, timeout_seconds=30
    )
    print(json.dumps({"terminal": verified.receipt["terminal_category"], "exit": verified.receipt["worker_exit_code"], "stderr": (attempt / "stderr.log").read_text(encoding="utf-8", errors="replace")}))
'''
    return subprocess.run(
        [sys.executable, "-c", code, str(run_root), mode],
        cwd=runtime_repo,
        env=runtime_environment(runtime_repo),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


@pytest.mark.failure_injection
@pytest.mark.parametrize(
    ("mode", "terminal", "exit_code"),
    [("crash", "worker_crashed", 7), ("timeout", "timed_out", 124)],
)
def test_crash_and_timeout_are_distinct_digest_bound_receipts(
    completed_offline_run: dict,
    mode: str,
    terminal: str,
    exit_code: int,
) -> None:
    result = _run_probe(
        completed_offline_run["runtime_repo"], completed_offline_run["run_root"], mode
    )
    assert result.returncode == 0, result.stderr
    payload = last_json_line(result.stdout)
    assert payload["terminal"] == terminal
    assert payload["exit"] == exit_code
    references = {item["relative_path"] for item in payload["refs"]}
    assert {"stdout.log", "stderr.log"}.issubset(references)


@pytest.mark.failure_injection
def test_verified_receipt_is_rejected_when_child_exit_disagrees(
    completed_offline_run: dict,
) -> None:
    result = _run_probe(
        completed_offline_run["runtime_repo"],
        completed_offline_run["run_root"],
        "exit_mismatch",
    )
    assert result.returncode == 0, result.stderr
    payload = last_json_line(result.stdout)
    assert payload["rejected"] is True
    assert "returncode" in payload["detail"]


@pytest.mark.failure_injection
def test_worker_reproves_runtime_pins_before_staging(
    completed_offline_run: dict,
) -> None:
    result = _run_probe(
        completed_offline_run["runtime_repo"],
        completed_offline_run["run_root"],
        "runtime_pin",
    )
    assert result.returncode == 0, result.stderr
    payload = last_json_line(result.stdout)
    assert payload["terminal"] == "worker_crashed"
    assert payload["exit"] == 31
    assert "runtime pin mismatch for python_version" in payload["stderr"]


def test_load_run_rejects_missing_or_tampered_archived_source_manifest(
    completed_offline_run: dict,
) -> None:
    run_root = completed_offline_run["run_root"]
    source = run_root / "manifest.source.json"
    digest = run_root / "manifest.source.sha256"
    original_source = source.read_bytes()
    original_digest = digest.read_bytes()
    try:
        source.write_bytes(original_source + b" ")
        result = run_offline_cli(
            completed_offline_run["runtime_repo"],
            "stage",
            "--run-root",
            str(run_root),
        )
        assert result.returncode != 0
        assert "digest mismatch" in result.stderr
        source.write_bytes(original_source)
        digest.unlink()
        result = run_offline_cli(
            completed_offline_run["runtime_repo"],
            "stage",
            "--run-root",
            str(run_root),
        )
        assert result.returncode != 0
        assert "record or digest is missing" in result.stderr
    finally:
        source.write_bytes(original_source)
        digest.write_bytes(original_digest)
