from __future__ import annotations

import os
import json
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ras_commander.RasProject import STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM

from scripts.qualification.execution_evidence import live_cancel_worker
from scripts.qualification.execution_evidence import live_supervisor as live
from scripts.qualification.execution_evidence.locks import (
    ExclusiveQualificationLock,
    LockState,
    inspect_lock,
)
from scripts.qualification.execution_evidence.cli import main
from scripts.qualification.execution_evidence.planning import (
    RunContext,
    current_runtime_pins,
    file_sha256,
)
from scripts.qualification.execution_evidence.receipts import (
    read_json_with_digest,
    write_json_with_digest,
)
from scripts.qualification.execution_evidence.snapshots import snapshot_tree
from ._helpers import GIT_HEAD, HASH_A, valid_table_rows


pytestmark = pytest.mark.qualification_harness

_LIVE_INVARIANT_NAMES = {
    "R01": "Read-only inspection",
    "R02": "Engine-owned result family",
    "R03": "No evidence-channel mixing",
    "R04": "Exact deletion allowlist",
    "R06": "Quiescence-gated finalization",
    "R10": "Stable evidence contract",
    "R11": "Source immutability",
    "R12": "Owned-process hygiene",
}


class _StructuredEvidence:
    def __init__(self, **values):
        self.__dict__.update(values)

    def to_dict(self):
        return dict(self.__dict__)


def _empty_inventory() -> live.ProcessInventorySnapshot:
    raw = {
        "observed_at": 1787923200.0,
        "complete": True,
        "processes": [],
        "query_errors": [],
    }
    return live.ProcessInventorySnapshot(records=(), raw=raw)


def _worker_launch_metadata(attempt_dir: Path) -> dict[str, str]:
    return {
        "launch_nonce": str(uuid.uuid4()),
        "intent_path": str(attempt_dir / "worker-launch-intent.json"),
        "binding_path": str(attempt_dir / "worker-launcher.json"),
        "hello_path": str(attempt_dir / "worker-hello.json"),
        "authorization_path": str(attempt_dir / "worker-authorization.json"),
    }


def _direct_worker_identity(process) -> live.AuthorizedWorkerIdentity:
    return live.AuthorizedWorkerIdentity(
        worker_pid=process.pid,
        worker_process_create_time=12345.0,
        launcher_pid=process.pid,
        launcher_process_create_time=12345.0,
        worker_parent_pid=os.getpid(),
        worker_parent_process_create_time=12344.0,
        delegated=False,
        command=(),
    )


def _delegated_worker_identity(process) -> live.AuthorizedWorkerIdentity:
    return live.AuthorizedWorkerIdentity(
        worker_pid=9753,
        worker_process_create_time=12345.1,
        launcher_pid=process.pid,
        launcher_process_create_time=12345.0,
        worker_parent_pid=process.pid,
        worker_parent_process_create_time=12345.0,
        delegated=True,
        command=("python.exe", "-m", "worker"),
    )


def _context(tmp_path: Path, *, lane_ids: tuple[str, ...] = ("lane-live",)) -> RunContext:
    run_root = tmp_path / "archive" / "run-001"
    execution_root = tmp_path / "execution"
    source_root = tmp_path / "source"
    run_root.mkdir(parents=True)
    execution_root.mkdir()
    source_root.mkdir()
    source_project = source_root / "Model.prj"
    source_project.write_text("Proj Title=Live qualification\n", encoding="ascii")
    (source_root / "Model.p01").write_text(
        "Plan Title=Live qualification\nProgram Version=7.00\n",
        encoding="ascii",
    )
    engine_path = tmp_path / "Ras.exe"
    engine_path.write_bytes(b"not-an-executable-test-pin")
    source = snapshot_tree(
        source_root,
        run_id="probe",
        lane_id="probe",
        attempt_id="probe",
        phase="probe",
        root_kind="source",
        data_origin="captured_real",
        known_paths=(
            "Model.p01.hdf",
            "Model.O01",
            "Model.p01.comp_msgs.txt",
            "Model.p01.computeMsgs.txt",
            "Model.bco01",
        ),
    )
    fixture = {
        "fixture_id": "fixture-live",
        "source_kind": "project_file",
        "source_project": str(source_project),
        "source_content_fingerprint_algorithm": source.fingerprint_algorithm,
        "source_content_fingerprint": source.content_fingerprint,
        "source_immutable": True,
        "data_origin": "captured_real",
        "plan_type": "steady_1d",
        "plan_number": "01",
        "plan_title": "Live qualification",
    }
    engine = {
        "engine_id": "engine-live",
        "execution_api": "ras_cmdr",
        "version_requested": "7.0",
        "expected_result_format": "hdf",
        "support_state": "supported",
        "executable": str(engine_path),
        "executable_sha256": file_sha256(engine_path),
    }
    lanes = [
        {
            "lane_id": lane_id,
            "fixture_id": fixture["fixture_id"],
            "engine_id": engine["engine_id"],
            "initial_state": "neither",
            "expected_terminal_category": "passed",
            "required_invariants": list(_LIVE_INVARIANT_NAMES),
            "tags": ["real_ras", "pilot"],
        }
        for lane_id in lane_ids
    ]
    descriptor = {
        "run_id": "run-1",
        "lane_ids": list(lane_ids),
        "execution_run_root": str(execution_root),
        "repository_root": str(Path.cwd()),
        "git_head": GIT_HEAD,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": file_sha256(sys.executable),
        "hec_ras_execution_enabled": False,
        **current_runtime_pins(),
    }
    manifest = {
        "schema_version": 1,
        "manifest_sha256": HASH_A,
        "repository": {
            "root": str(Path.cwd()),
            "required_head": GIT_HEAD,
            "require_clean": True,
            "bind_running_code": True,
        },
        "defaults": {
            "preflight_timeout_seconds": 1800,
            "timeout_seconds": 1,
            "termination_grace_seconds": 1,
            "postflight_timeout_seconds": 1800,
            "real_engine_jobs": 1,
            "hash_files": True,
        },
        "fixtures": [fixture],
        "engines": [engine],
        "lanes": lanes,
    }
    return RunContext(
        run_root=run_root,
        descriptor=descriptor,
        descriptor_sha256="d" * 64,
        manifest=manifest,
        normalized_manifest_sha256="e" * 64,
    )


def _publish_passing_worker_record(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    (attempt_dir / "stdout.log").write_bytes(b"worker stdout\n")
    (attempt_dir / "stderr.log").write_bytes(b"")
    rows = valid_table_rows(
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
    )
    invariant_template = rows["invariants"][0]
    rows["invariants"] = []
    for invariant_id, name in _LIVE_INVARIANT_NAMES.items():
        invariant = dict(invariant_template)
        invariant.update(invariant_id=invariant_id, name=name)
        rows["invariants"].append(invariant)
    lane = rows["lanes"][0]
    lane.update(
        manifest_sha256=request["manifest_sha256"],
        git_head=request["git_head"],
        fixture_id=request["fixture"]["fixture_id"],
        plan_type=request["fixture"]["plan_type"],
        plan_number=request["fixture"]["plan_number"],
        source_kind=request["fixture"]["source_kind"],
        source_project=request["source_project"],
        source_content_fingerprint_algorithm=request[
            "source_snapshot_content_fingerprint_algorithm"
        ],
        source_content_fingerprint=request[
            "source_snapshot_content_fingerprint"
        ],
        stage_project=str(
            Path(request["stage_root"]) / Path(request["source_project"]).name
        ),
        execution_api=request["engine"]["execution_api"],
        engine_id=request["engine"]["engine_id"],
        engine_version_requested=request["engine"]["version_requested"],
        engine_executable=request["engine"]["executable"],
        engine_executable_sha256=request["engine"]["executable_sha256"],
        compute_mode="live_ras_cmdr",
    )
    source_project_path = Path(request["source_project"])
    stage_root = Path(request["stage_root"])
    stage_root.mkdir(parents=True, exist_ok=True)
    copied_artifacts = []
    copied_bytes = 0
    for source_path in sorted(source_project_path.parent.iterdir()):
        if not source_path.is_file():
            continue
        destination = stage_root / source_path.name
        destination.write_bytes(source_path.read_bytes())
        copied_bytes += destination.stat().st_size
        copied_artifacts.append(
            {
                "relative_path": source_path.name,
                "provenance": "copied_source",
                "size_bytes": destination.stat().st_size,
                "sha256": file_sha256(destination),
            }
        )
    stage_source_fingerprint = "1" * 64
    stage_published_fingerprint = "2" * 64
    stage_metadata = {
        "schema_version": 1,
        "operation_id": str(uuid.uuid4()),
        "fingerprint_algorithm": STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM,
        "source_project_file": str(source_project_path),
        "destination_project_file": str(stage_root / source_project_path.name),
        "source_fingerprint_before": stage_source_fingerprint,
        "source_fingerprint_after": stage_source_fingerprint,
        "copied_fingerprint": stage_source_fingerprint,
        "copied_file_count": len(copied_artifacts),
        "copied_bytes": copied_bytes,
        "execution_readiness": "ready",
        "created_at": "2026-08-28T12:00:00+00:00",
        "artifacts": copied_artifacts
        + [
            {
                "relative_path": ".ras-commander/stage.json",
                "provenance": "generated_stage_metadata",
            }
        ],
    }
    metadata_path = stage_root / ".ras-commander" / "stage.json"
    metadata_path.parent.mkdir()
    metadata_path.write_text(
        json.dumps(stage_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stage_project = str(
        Path(request["stage_root"]) / Path(request["source_project"]).name
    )
    empty_global = {
        "observed_at": 1787923200.0,
        "complete": True,
        "processes": [],
        "query_errors": [],
    }
    empty_plan = {
        "observed_at": 1787923200.0,
        "complete": True,
        "plan_number": request["fixture"]["plan_number"],
        "project_path": stage_project,
        "plan_path": str(
            Path(stage_project).with_suffix(
                f".p{request['fixture']['plan_number']}"
            )
        ),
        "tmp_hdf_path": str(
            Path(stage_project).with_suffix(
                f".p{request['fixture']['plan_number']}.tmp.hdf"
            )
        ),
        "matched": [],
        "query_errors": [],
    }
    stage_project_path = Path(stage_project).resolve(strict=True)
    stage_plan_path = stage_project_path.with_suffix(
        f".p{request['fixture']['plan_number']}"
    ).resolve(strict=True)
    executable_path = Path(request["engine"]["executable"]).resolve(strict=True)
    logical_argv = [
        str(executable_path),
        "-c",
        str(stage_project_path),
        str(stage_plan_path),
    ]
    raw_command = (
        f'"{logical_argv[0]}" -c "{logical_argv[2]}" "{logical_argv[3]}"'
    )
    launch_details = {
        "plan_number": request["fixture"]["plan_number"],
        "command": raw_command,
        "executable_path": str(executable_path),
        "executable_sha256": request["engine"]["executable_sha256"],
        "project_path": str(stage_project_path),
        "plan_path": str(stage_plan_path),
        "working_directory": str(stage_project_path.parent),
        "launcher_pid": 1234,
        "launcher_create_time": 12345.0,
        "max_runtime_seconds": request["timeout_seconds"],
    }
    launch_payload = {
        "plan_number": request["fixture"]["plan_number"],
        "raw_command": raw_command,
        "logical_argv": logical_argv,
        "executable_path": str(executable_path),
        "executable_sha256": request["engine"]["executable_sha256"],
        "project_path": str(stage_project_path),
        "plan_path": str(stage_plan_path),
        "cwd": str(stage_project_path.parent),
        "launch_method": "direct_subprocess_shell_false_exact_executable",
        "launcher_pid": 1234,
        "launcher_create_time": 12345.0,
        "max_runtime_seconds": request["timeout_seconds"],
    }
    rows["events"][0].update(
        phase="execution",
        event_name="engine_process_launched",
        status="running",
        severity="info",
        api="RasCmdr.compute_plan.on_exec_launched",
        reason_code=None,
        detail=None,
        relative_path=None,
        pid=1234,
        payload_json=json.dumps(
            launch_payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    worker = {
        "schema_version": 1,
        "action": "run",
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "manifest_sha256": request["manifest_sha256"],
        "git_head": request["git_head"],
        "request_sha256": request_sha256,
        "required_invariants": request["required_invariants"],
        "receipt_committed_at": "2026-08-28T12:00:01+00:00",
        "terminal_category": "passed",
        "worker_exit_code": 0,
        "python_executable": request["python_executable"],
        "python_executable_sha256": request["python_executable_sha256"],
        "python_version": request["python_version"],
        "pyarrow_version": request["pyarrow_version"],
        "psutil_version": request["psutil_version"],
        "ras_commander_version": request["ras_commander_version"],
        "ras_commander_import_path": request["ras_commander_import_path"],
        "hec_ras_invoked": True,
        "tcu_status": {
            "accepted": True,
            "version": request["engine"]["executable"],
            "install_dir": str(Path(request["engine"]["executable"]).parent),
            "registry_key": "test-registry/tcu",
            "reason": "accepted",
            "ras_version_argument": request["engine"]["executable"],
        },
        "process_evidence": {
            "pre_stage_global": empty_global,
            "pre_setup_plan": empty_plan,
            "pre_execute_global": empty_global,
            "post_execution_plan": empty_plan,
            "post_execution_global": empty_global,
        },
        "stage_result": {
            "publication_state": "published",
            "execution_readiness": "ready",
            "fingerprint_algorithm": STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM,
            "source_fingerprint_before": stage_source_fingerprint,
            "source_fingerprint_after": stage_source_fingerprint,
            "copied_fingerprint": stage_source_fingerprint,
            "published_fingerprint": stage_published_fingerprint,
            "copied_file_count": len(copied_artifacts),
            "copied_bytes": copied_bytes,
        },
        "execution_result": {
            "result_type": "ComputeResult",
            "success": True,
            "completion_verified": True,
            "message_count": 0,
            "execution_details": {
                "execution_api": "ras_cmdr",
                "engine_kind": "executable",
                "selected_result_format": request["engine"][
                    "expected_result_format"
                ],
                "calculation_attempted": True,
                "solver_quiescence_confirmed": True,
                "result_artifacts_finalized": True,
                "artifact_finalization_failure": None,
                "actual_engine_provenance_confirmed": True,
                "selected_executable_path": request["engine"]["executable"],
                "selected_executable_sha256": request["engine"][
                    "executable_sha256"
                ],
                "launcher_pid": 1234,
                "launcher_create_time": 12345.0,
                "launcher_returncode": 0,
                "max_runtime_seconds": request["timeout_seconds"],
                "launch_details": launch_details,
                "runtime_timed_out": False,
                "failure_stage": None,
                "failure_type": None,
                "failure_detail": None,
                "cancellation_details": None,
            },
        },
        "evidence": {"evidence_id": "evidence-1"},
        "referenced_artifacts": [],
        "tables": rows,
    }
    write_json_with_digest(
        attempt_dir / "execution_result.json", worker["execution_result"]
    )
    write_json_with_digest(attempt_dir / "evidence.json", worker["evidence"])
    (attempt_dir / "events.jsonl").write_bytes(
        b"".join(
            (
                json.dumps(
                    event,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            for event in rows["events"]
        )
    )
    worker["referenced_artifacts"] = [
        live._artifact_reference(attempt_dir, attempt_dir / relative_path)
        for relative_path in (
            "execution_result.json",
            "evidence.json",
            "events.jsonl",
        )
    ]
    write_json_with_digest(attempt_dir / "worker_receipt.json", worker)
    started = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    return live.LiveChildOutcome(
        pid=4321,
        returncode=0,
        started_at=started,
        finished_at=started,
        timed_out=False,
    )


def _publish_safe_failed_worker_record(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    """Publish a modern timeout that the public result proved fully quiescent."""
    outcome = _publish_passing_worker_record(
        attempt_dir,
        request,
        request_sha256,
    )
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    execution = worker["execution_result"]
    details = execution["execution_details"]
    launch = details["launch_details"]
    process_record = {
        "pid": launch["launcher_pid"],
        "create_time": launch["launcher_create_time"],
        "name": "Ras.exe",
        "executable_path": launch["executable_path"],
        "command_line": [launch["command"]],
        "working_directory": launch["working_directory"],
        "tracked": True,
        "session_id": None,
    }
    project = Path(launch["project_path"])
    plan_number = request["fixture"]["plan_number"]
    execution.update(success=False, completion_verified=False)
    details.update(
        launcher_returncode=None,
        runtime_timed_out=True,
        failure_stage="subprocess_wait",
        failure_type="TimeoutError",
        failure_detail="maximum runtime expired",
        cancellation_details={
            "plan_number": plan_number,
            "project_path": launch["project_path"],
            "plan_path": launch["plan_path"],
            "tmp_hdf_path": str(
                project.with_suffix(f".p{plan_number}.tmp.hdf")
            ),
            "cancellation_attempted": True,
            "pre_scan_complete": True,
            "post_scan_complete": True,
            "matched": [process_record],
            "stopped": [process_record],
            "survivors": [],
            "query_errors": [],
            "quiescence_confirmed": True,
            "started_at": 1787923200.0,
            "finished_at": 1787923201.0,
        },
    )
    worker.update(terminal_category="execution_failed", worker_exit_code=20)
    lane = worker["tables"]["lanes"][0]
    lane.update(
        terminal_category="execution_failed",
        worker_exit_code=20,
        process_success=False,
        completion_verified=False,
        final_hdf_exists=False,
        final_legacy_exists=False,
        failure_reason_code="mechanical_execution_not_confirmed",
    )
    write_json_with_digest(
        attempt_dir / "execution_result.json",
        execution,
        replace=True,
    )
    next(
        item
        for item in worker["referenced_artifacts"]
        if item["relative_path"] == "execution_result.json"
    )["sha256"] = live.stable_sha256(
        attempt_dir / "execution_result.json"
    )[0]
    write_json_with_digest(
        attempt_dir / "worker_receipt.json",
        worker,
        replace=True,
    )
    return replace(outcome, returncode=20)


def _rewrite_worker_execution_result(
    attempt_dir: Path,
    worker: dict,
) -> None:
    execution = worker["execution_result"]
    write_json_with_digest(
        attempt_dir / "execution_result.json",
        execution,
        replace=True,
    )
    next(
        item
        for item in worker["referenced_artifacts"]
        if item["relative_path"] == "execution_result.json"
    )["sha256"] = live.stable_sha256(
        attempt_dir / "execution_result.json"
    )[0]
    write_json_with_digest(
        attempt_dir / "worker_receipt.json",
        worker,
        replace=True,
    )


def _publish_safe_finalization_failed_worker_record(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    """Publish solver completion followed by a safely contained refresh failure."""
    outcome = _publish_safe_failed_worker_record(
        attempt_dir,
        request,
        request_sha256,
    )
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    execution = worker["execution_result"]
    execution["completion_verified"] = True
    details = execution["execution_details"]
    details.update(
        launcher_returncode=0,
        runtime_timed_out=False,
        failure_stage="result_artifact_finalization",
        failure_type="OSError",
        failure_detail="result inventory refresh failed",
        result_artifacts_finalized=False,
        artifact_finalization_failure={
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "result inventory refresh failed",
        },
    )
    lane = worker["tables"]["lanes"][0]
    lane.update(
        completion_verified=True,
        final_hdf_exists=True,
        final_legacy_exists=False,
    )
    _rewrite_worker_execution_result(attempt_dir, worker)
    return outcome


def _publish_timeout_with_secondary_finalization_failure(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    """Publish a timeout whose later artifact refresh also failed."""
    outcome = _publish_safe_failed_worker_record(
        attempt_dir,
        request,
        request_sha256,
    )
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    details = worker["execution_result"]["execution_details"]
    details.update(
        result_artifacts_finalized=False,
        artifact_finalization_failure={
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "post-timeout result refresh failed",
        },
    )
    _rewrite_worker_execution_result(attempt_dir, worker)
    return outcome


def _publish_callback_timeout_error_worker_record(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    """Publish a callback TimeoutError that is not an engine deadline."""
    outcome = _publish_safe_failed_worker_record(
        attempt_dir,
        request,
        request_sha256,
    )
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    execution = worker["execution_result"]
    execution["completion_verified"] = True
    details = execution["execution_details"]
    details.update(
        runtime_timed_out=False,
        failure_stage="stream_callback",
        failure_detail="callback raised its own TimeoutError",
    )
    worker["tables"]["lanes"][0]["completion_verified"] = True
    _rewrite_worker_execution_result(attempt_dir, worker)
    return outcome


def _rewrite_worker_inspection_evidence(
    attempt_dir: Path,
    worker: dict,
) -> None:
    write_json_with_digest(
        attempt_dir / "evidence.json",
        worker["evidence"],
        replace=True,
    )
    (attempt_dir / "events.jsonl").write_bytes(
        b"".join(
            (
                json.dumps(
                    event,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            for event in worker["tables"]["events"]
        )
    )
    for relative_path in ("evidence.json", "events.jsonl"):
        next(
            item
            for item in worker["referenced_artifacts"]
            if item["relative_path"] == relative_path
        )["sha256"] = live.stable_sha256(attempt_dir / relative_path)[0]
    write_json_with_digest(
        attempt_dir / "worker_receipt.json",
        worker,
        replace=True,
    )


def _publish_failed_inspection_worker_record(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    """Publish a digest-bound ambiguity diagnostic after safe compute failure."""
    outcome = _publish_safe_finalization_failed_worker_record(
        attempt_dir,
        request,
        request_sha256,
    )
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    stage_project = Path(request["stage_root"]) / Path(request["source_project"]).name
    plan_number = request["fixture"]["plan_number"]
    hdf = stage_project.with_suffix(f".p{plan_number}.hdf")
    legacy = stage_project.with_suffix(f".O{plan_number}")
    hdf.write_bytes(b"modern result")
    legacy.write_bytes(b"legacy result")
    os.utime(hdf, ns=(1787923200000000000, 1787923200000000000))
    os.utime(legacy, ns=(1787923201000000000, 1787923201000000000))
    evidence_id = str(uuid.uuid4())
    worker["evidence"] = {
        "schema_version": 1,
        "evidence_kind": "execution_evidence_inspection_failure",
        "evidence_id": evidence_id,
        "inspection_api": "RasCmdr.inspect_execution_evidence",
        "inspection_state": "failed",
        "inspection_started_at": "2026-08-28T12:00:02+00:00",
        "inspection_failed_at": "2026-08-28T12:00:03+00:00",
        "failure_type": "ResultArtifactAmbiguityError",
        "reason_code": "legacy_output_timestamp_after_hdf",
        "detail": "mixed result families prevent safe inspection",
        "plan_number": plan_number,
        "declared_program_version": "7.00",
        "declared_expected_result_format": "hdf",
        "selected_result_format": "hdf",
        "hdf_path": str(hdf),
        "legacy_output_path": str(legacy),
        "hdf_mtime_ns": hdf.stat().st_mtime_ns,
        "legacy_mtime_ns": legacy.stat().st_mtime_ns,
        "conflicts": ["multiple_result_formats_present"],
        "safe_failed_execution": True,
        "result_artifacts_finalized": False,
        "runtime_timed_out": False,
    }
    worker["tables"]["observations"] = []
    worker["tables"]["lanes"][0].update(
        final_hdf_exists=True,
        final_legacy_exists=True,
        conflicts=["multiple_result_formats_present"],
    )
    event = dict(worker["tables"]["events"][-1])
    event.update(
        sequence=event["sequence"] + 1,
        event_name="execution_evidence_inspection_failed",
        event_at="2026-08-28T12:00:03+00:00",
        phase="inspection",
        status="failed",
        severity="error",
        api="RasCmdr.inspect_execution_evidence",
        reason_code=worker["evidence"]["reason_code"],
        pid=None,
        payload_json=json.dumps(
            {
                "evidence_id": evidence_id,
                "evidence_kind": worker["evidence"]["evidence_kind"],
                "failure_type": worker["evidence"]["failure_type"],
                "reason_code": worker["evidence"]["reason_code"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    worker["tables"]["events"].append(event)
    _rewrite_worker_inspection_evidence(attempt_dir, worker)
    return outcome


def _enable_test_orchestration(
    monkeypatch: pytest.MonkeyPatch,
    context: RunContext,
    host_lock: Path,
) -> None:
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(
        live, "_require_strict_live_api_contracts", lambda *_: None
    )
    monkeypatch.setattr(live, "_host_lock_path", lambda: host_lock)


def test_live_run_refuses_missing_structured_api_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ras_commander import RasCmdr, RasControl

    context = _context(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(RasControl, "inspect_processes", None)
    monkeypatch.setattr(RasCmdr, "inspect_plan_processes", None)
    monkeypatch.setattr(RasCmdr, "cancel_plan_exact", None)

    with pytest.raises(live.LiveSupervisorError, match="structured process/cancellation"):
        live.execute_live_action(
            context.run_root,
            acknowledge_real_ras=True,
        )

    assert not (context.run_root / "run.lock").exists()
    assert not (context.run_root / "attempts").exists()


def test_live_run_preflight_rejects_existing_process_before_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    occupied = live.ProcessInventorySnapshot(
        records=({"pid": 99, "create_time": 1.0},),
        raw={"complete": True, "processes": [{"pid": 99}], "query_errors": []},
    )
    monkeypatch.setattr(live, "_strict_process_inventory", lambda: occupied)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        lambda *_: pytest.fail("worker must not start when preflight is occupied"),
    )

    with pytest.raises(live.LiveSupervisorError, match="existing HEC-RAS process"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert not host_lock.exists()
    assert not any(
        path.is_dir()
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
    )


def _directory_link_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - host policy dependent
        pytest.skip(f"directory links unavailable for confinement test: {exc}")


@pytest.mark.parametrize("redirect_root", ["archive", "execution"])
def test_live_attempt_descendants_reject_link_or_reparse_redirection(
    tmp_path: Path,
    redirect_root: str,
) -> None:
    context = _context(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    if redirect_root == "archive":
        _directory_link_or_skip(context.run_root / "attempts", outside)
    else:
        _directory_link_or_skip(
            Path(context.descriptor["execution_run_root"]) / "lane-live",
            outside,
        )
    lock_path = tmp_path / "real-engine.lock"
    lock_path.write_text("lock proof placeholder\n", encoding="ascii")

    with pytest.raises(live.LiveSupervisorError, match="plain root"):
        live.create_live_attempt_request(
            context,
            lane_id="lane-live",
            attempt_id="attempt-link",
            process_baseline=_empty_inventory(),
            real_engine_lock_path=lock_path,
            real_engine_lock_payload={"token": "token"},
        )

    assert not any(outside.iterdir())


def test_live_v1_rejects_l2_l3_l4_initial_state_campaigns(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context.manifest["lanes"][0]["initial_state"] = "both_expected_newer"

    with pytest.raises(live.LiveSupervisorError, match="L2/L3/L4"):
        live._select_live_lanes(context, lane_ids=None, phase=None)


def test_live_run_parent_terminalizes_worker_receipt_and_closed_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)

    attempts = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
        phase="pilot",
    )

    assert len(attempts) == 1
    verified = attempts[0]
    assert verified.receipt["terminal_category"] == "passed"
    assert verified.receipt["supervisor_synthesized"] is False
    references = {
        item["relative_path"] for item in verified.receipt["referenced_artifacts"]
    }
    assert {"stdout.log", "stderr.log", "worker_receipt.json"}.issubset(references)
    assert "worker_receipt.sha256" not in references
    assert not host_lock.exists()
    request = verified.request
    assert request["hec_ras_execution_enabled"] is True
    assert request["process_baseline"] == []
    assert request["real_engine_lock"]["attempt_id"] == request["attempt_id"]
    assert request["timeout_seconds"] == 1
    assert request["termination_grace_seconds"] == 1
    assert request["preflight_timeout_seconds"] == 1800
    assert request["postflight_timeout_seconds"] == 1800
    assert request["supervisor_receipt_margin_seconds"] == 5.0


def test_passing_worker_source_drift_quarantines_without_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_and_drift(attempt_dir: Path, request: dict, digest: str):
        outcome = _publish_passing_worker_record(attempt_dir, request, digest)
        Path(request["source_project"]).write_text(
            "Proj Title=drifted after passing worker\n",
            encoding="ascii",
        )
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_and_drift)

    with pytest.raises(live.LiveHostQuarantinedError, match="source snapshot drifted"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()
    host_lock.unlink()


def test_uncertain_timeout_publishes_no_terminal_and_retains_host_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def timed_out(attempt_dir: Path, request: dict, request_sha256: str):
        del request, request_sha256
        (attempt_dir / "stdout.log").write_bytes(b"")
        (attempt_dir / "stderr.log").write_bytes(b"deadline\n")
        now = datetime.now(timezone.utc)
        return live.LiveChildOutcome(
            pid=4321,
            returncode=124,
            started_at=now,
            finished_at=now,
            timed_out=True,
            cancellation_safe=False,
            cancellation_reason="cancellation_quiescence_unconfirmed",
        )

    monkeypatch.setattr(live, "_run_live_child", timed_out)
    monkeypatch.setattr(
        live,
        "_artifact_reference",
        lambda *_: pytest.fail("unsafe timeout artifacts must remain mutable/unhashed"),
    )

    with pytest.raises(live.LiveHostQuarantinedError, match="host lock retained"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert (attempt_dir / "request.json").is_file()
    assert not (attempt_dir / "receipt.json").exists()
    assert not (attempt_dir / "receipt.sha256").exists()
    assert not (attempt_dir / "worker_receipt.json").exists()
    assert (attempt_dir / "stdout.log").read_bytes() == b""
    assert (attempt_dir / "stderr.log").read_bytes() == b"deadline\n"
    host_lock.unlink()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(7)])
def test_baseexception_retains_host_lock_when_recovery_is_not_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: BaseException,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def interrupted(*_args, **_kwargs):
        raise interrupt

    monkeypatch.setattr(live, "_run_live_child", interrupted)
    monkeypatch.setattr(
        live,
        "_supervision_recovery_gate",
        lambda *_: live.RecoveryGateOutcome(False, "exact worker still alive"),
    )

    with pytest.raises(live.LiveHostQuarantinedError, match="lock retained"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    host_lock.unlink()


def test_systemexit_releases_host_lock_only_after_same_recovery_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        lambda *_: (_ for _ in ()).throw(SystemExit(9)),
    )
    monkeypatch.setattr(
        live,
        "_supervision_recovery_gate",
        lambda *_: live.RecoveryGateOutcome(
            True,
            "exact worker absent and process hygiene reproved",
            _empty_inventory(),
        ),
    )

    with pytest.raises(SystemExit) as exc:
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert exc.value.code == 9
    assert not host_lock.exists()


def test_interrupt_during_popen_after_launch_intent_quarantines_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def interrupted_popen(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(live.subprocess, "Popen", interrupted_popen)

    with pytest.raises(
        live.LiveHostQuarantinedError,
        match="worker launcher binding publication is incomplete",
    ):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert (attempt_dir / "worker-launch-intent.json").is_file()
    assert not (attempt_dir / "worker-hello.json").exists()
    assert host_lock.is_file()
    host_lock.unlink()


def test_parent_authorization_durably_binds_exact_worker_pid_create_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = ExclusiveQualificationLock(
        tmp_path / "locks" / "real-engine.lock",
        kind="real_engine",
        run_id=context.descriptor["run_id"],
        lane_id="lane-live",
        attempt_id="attempt-auth",
        git_head=context.descriptor["git_head"],
    )
    lock_payload = host_lock.acquire()
    attempt_dir, request, request_sha256 = live.create_live_attempt_request(
        context,
        lane_id="lane-live",
        attempt_id="attempt-auth",
        process_baseline=_empty_inventory(),
        real_engine_lock_path=host_lock.path,
        real_engine_lock_payload=lock_payload,
    )
    intent_sha256 = live._publish_worker_launch_intent(
        attempt_dir, request, request_sha256
    )
    intent, _ = read_json_with_digest(attempt_dir / "worker-launch-intent.json")
    pid = 2468
    create_time = 12345.5
    binding_sha256 = write_json_with_digest(
        request["worker_launch"]["binding_path"],
        {
            "schema_version": 1,
            "action": "bind_live_worker_launcher",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_nonce": request["worker_launch"]["launch_nonce"],
            "run_id": request["run_id"],
            "lane_id": request["lane_id"],
            "attempt_id": request["attempt_id"],
            "real_engine_lock_token": request["real_engine_lock"]["token"],
            "launcher_pid": pid,
            "launcher_process_create_time": create_time,
            "expected_command": live._worker_command(
                request, attempt_dir / "request.json"
            ),
        },
    )
    hello = {
        "schema_version": 1,
        "action": "hello_live_worker",
        "created_at": "2026-08-28T12:00:00+00:00",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": request["worker_launch"]["launch_nonce"],
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "worker_pid": pid,
        "worker_process_create_time": create_time,
        "worker_parent_pid": intent["supervisor_pid"],
        "worker_parent_process_create_time": intent[
            "supervisor_process_create_time"
        ],
    }
    hello_sha256 = write_json_with_digest(
        request["worker_launch"]["hello_path"], hello
    )
    monkeypatch.setattr(
        live,
        "_live_python_child_identity",
        lambda _process: (pid, create_time),
    )
    binding_observations: list[bool] = []

    def bind_before_grant(*_args, **_kwargs):
        binding_observations.append(
            Path(request["worker_launch"]["authorization_path"]).exists()
        )
        return live.AuthorizedWorkerIdentity(
            worker_pid=pid,
            worker_process_create_time=create_time,
            launcher_pid=pid,
            launcher_process_create_time=create_time,
            worker_parent_pid=intent["supervisor_pid"],
            worker_parent_process_create_time=intent[
                "supervisor_process_create_time"
            ],
            delegated=False,
            command=(),
        )

    monkeypatch.setattr(
        live,
        "_bind_launched_worker_identity",
        bind_before_grant,
    )

    identity = live._authorize_live_child(
        SimpleNamespace(pid=pid),
        attempt_dir,
        request,
        request_sha256,
        intent_sha256,
    )

    authorization, _ = read_json_with_digest(
        request["worker_launch"]["authorization_path"]
    )
    assert authorization["worker_pid"] == pid
    assert authorization["worker_process_create_time"] == create_time
    assert authorization["worker_hello_sha256"] == hello_sha256
    assert authorization["request_sha256"] == request_sha256
    assert authorization["real_engine_lock_token"] == lock_payload["token"]
    assert identity.worker_pid == pid
    assert identity.delegated is False
    assert binding_observations == [False, False]
    host_lock.release()


def test_real_python_subprocess_authorization_accepts_exact_windows_venv_child(
    tmp_path: Path,
) -> None:
    """Exercise the actual venv-launcher topology without HEC-RAS or COM."""
    context = _context(tmp_path)
    context.manifest["defaults"]["termination_grace_seconds"] = 10
    host_lock = ExclusiveQualificationLock(
        tmp_path / "locks" / "real-engine.lock",
        kind="real_engine",
        run_id=context.descriptor["run_id"],
        lane_id="lane-live",
        attempt_id="attempt-real-subprocess",
        git_head=context.descriptor["git_head"],
    )
    lock_payload = host_lock.acquire()
    attempt_dir, request, request_sha256 = live.create_live_attempt_request(
        context,
        lane_id="lane-live",
        attempt_id="attempt-real-subprocess",
        process_baseline=_empty_inventory(),
        real_engine_lock_path=host_lock.path,
        real_engine_lock_payload=lock_payload,
    )
    intent_sha256 = live._publish_worker_launch_intent(
        attempt_dir, request, request_sha256
    )
    probe = (
        "import sys,time; from pathlib import Path; "
        "from scripts.qualification.execution_evidence.live_worker import "
        "_register_and_verify_worker_authorization; "
        "_register_and_verify_worker_authorization(Path(sys.argv[1]), sys.argv[2]); "
        "time.sleep(0.5)"
    )
    command = [
        request["python_executable"],
        "-c",
        probe,
        str(attempt_dir / "request.json"),
        request["worker_launch"]["launch_nonce"],
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(request["repository_root"]))
    process = subprocess.Popen(
        command,
        cwd=request["repository_root"],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        live._publish_worker_launcher_binding(
            process,
            attempt_dir,
            request,
            request_sha256,
            intent_sha256,
            command,
        )
        identity = live._authorize_live_child(
            process,
            attempt_dir,
            request,
            request_sha256,
            intent_sha256,
            expected_command=command,
        )
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.wait(timeout=12)
        host_lock.release()

    assert process.returncode == 0, (stdout, stderr)
    assert identity.launcher_pid == process.pid
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        assert identity.delegated is True
        assert identity.worker_pid != identity.launcher_pid
    else:
        assert identity.delegated is False
        assert identity.worker_pid == identity.launcher_pid


def test_real_cancel_subprocess_requires_parent_authorization_before_action(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.manifest["defaults"]["termination_grace_seconds"] = 10
    host_lock = ExclusiveQualificationLock(
        tmp_path / "locks" / "real-engine.lock",
        kind="real_engine",
        run_id=context.descriptor["run_id"],
        lane_id="lane-live",
        attempt_id="attempt-real-cancel",
        git_head=context.descriptor["git_head"],
    )
    lock_payload = host_lock.acquire()
    attempt_dir, request, request_sha256 = live.create_live_attempt_request(
        context,
        lane_id="lane-live",
        attempt_id="attempt-real-cancel",
        process_baseline=_empty_inventory(),
        real_engine_lock_path=host_lock.path,
        real_engine_lock_payload=lock_payload,
    )
    cancel_path = live._create_cancellation_request(
        attempt_dir,
        request,
        request_sha256,
    )
    cancel_request, cancel_sha256 = read_json_with_digest(cancel_path)
    intent_sha256 = live._publish_cancel_launch_intent(
        attempt_dir,
        cancel_request,
        cancel_sha256,
    )
    nonce = cancel_request["cancel_launch"]["launch_nonce"]
    probe = (
        "import sys,time; from pathlib import Path; "
        "from scripts.qualification.execution_evidence.live_cancel_worker import "
        "_register_and_verify_cancel_authorization; "
        "_register_and_verify_cancel_authorization(Path(sys.argv[1]), sys.argv[2]); "
        "time.sleep(0.5)"
    )
    command = [
        cancel_request["python_executable"],
        "-c",
        probe,
        str(cancel_path),
        nonce,
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = request["repository_root"]
    process = subprocess.Popen(
        command,
        cwd=request["repository_root"],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        binding_sha256 = live._publish_cancel_launcher_binding(
            process,
            attempt_dir,
            cancel_request,
            cancel_sha256,
            intent_sha256,
            command,
        )
        identity = live._authorize_cancel_helper(
            process,
            attempt_dir,
            cancel_request,
            cancel_sha256,
            intent_sha256,
            binding_sha256,
            command,
        )
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.wait(timeout=12)
        host_lock.release()

    assert process.returncode == 0, (stdout, stderr)
    assert Path(cancel_request["cancel_launch"]["authorization_path"]).is_file()
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        assert identity.delegated is True
        assert identity.worker_pid != identity.launcher_pid


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher topology only")
def test_windows_launcher_binding_rejects_an_unrelated_direct_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = ["python.exe", "-m", "worker"]

    class ProcessRecord:
        def __init__(self, pid, create_time, *, parent=None, children=()):
            self.pid = pid
            self._create_time = create_time
            self._parent = parent
            self._children = list(children)

        def create_time(self):
            return self._create_time

        def is_running(self):
            return True

        def cmdline(self):
            return command

        def parent(self):
            return self._parent

        def children(self, recursive=False):
            assert recursive is False
            return self._children

    launcher = ProcessRecord(100, 10.0)
    worker = ProcessRecord(101, 10.1, parent=launcher)
    sibling = ProcessRecord(102, 10.2, parent=launcher)
    launcher._children = [worker, sibling]
    records = {record.pid: record for record in (launcher, worker, sibling)}
    monkeypatch.setattr(live.psutil, "Process", records.__getitem__)

    with pytest.raises(
        live.LiveSupervisorError,
        match="does not have one exact worker child",
    ):
        live._bind_launched_worker_identity(
            SimpleNamespace(pid=launcher.pid),
            launcher_pid=launcher.pid,
            launcher_create_time=launcher.create_time(),
            worker_pid=worker.pid,
            worker_create_time=worker.create_time(),
            expected_command=command,
        )


def test_delegated_worker_with_child_is_never_signalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = ("python.exe", "-m", "worker")
    signalled: list[int] = []

    class ProcessRecord:
        def __init__(self, pid, create_time, *, parent=None, children=()):
            self.pid = pid
            self._create_time = create_time
            self._parent = parent
            self._children = list(children)

        def create_time(self):
            return self._create_time

        def is_running(self):
            return True

        def cmdline(self):
            return list(command)

        def parent(self):
            return self._parent

        def children(self, recursive=False):
            assert recursive is False
            return self._children

        def terminate(self):
            signalled.append(self.pid)

    launcher = ProcessRecord(100, 10.0)
    worker = ProcessRecord(101, 10.1, parent=launcher)
    descendant = ProcessRecord(102, 10.2, parent=worker)
    launcher._children = [worker]
    worker._children = [descendant]
    records = {record.pid: record for record in (launcher, worker, descendant)}
    monkeypatch.setattr(live.psutil, "Process", records.__getitem__)
    identity = live.AuthorizedWorkerIdentity(
        worker_pid=worker.pid,
        worker_process_create_time=worker.create_time(),
        launcher_pid=launcher.pid,
        launcher_process_create_time=launcher.create_time(),
        worker_parent_pid=launcher.pid,
        worker_parent_process_create_time=launcher.create_time(),
        delegated=True,
        command=command,
    )

    with pytest.raises(live.LiveSupervisorError, match="changed before signal"):
        live._terminate_authorized_worker(
            SimpleNamespace(pid=launcher.pid),
            identity,
            grace=1.0,
        )

    assert signalled == []


def test_exact_timeout_termination_targets_authorized_worker_not_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    launcher = SimpleNamespace(
        pid=2468,
        wait=lambda timeout: observed.update(launcher_wait=timeout),
    )
    identity = _delegated_worker_identity(launcher)

    class Worker:
        pid = identity.worker_pid

        def children(self, recursive=False):
            assert recursive is False
            return []

        def terminate(self):
            observed["terminated_worker_pid"] = identity.worker_pid
            observed["terminated_object"] = id(self)

        def wait(self, timeout):
            observed["worker_wait"] = timeout

    worker = Worker()
    monkeypatch.setattr(
        live,
        "_verified_authorized_worker_process",
        lambda process, exact_identity, **_kwargs: worker
        if process is launcher and exact_identity == identity
        else pytest.fail("termination lost the authorized worker object"),
    )

    live._terminate_authorized_worker(launcher, identity, grace=2.0)

    assert observed["terminated_worker_pid"] == identity.worker_pid
    assert observed["terminated_object"] == id(worker)
    assert observed["worker_wait"] == 2.0
    assert observed["launcher_wait"] == 2.0


def test_exact_timeout_termination_refuses_changed_worker_without_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = SimpleNamespace(pid=2468)
    identity = _delegated_worker_identity(launcher)

    def refuse_binding(*_args, **_kwargs):
        raise live.LiveSupervisorError("identity changed")

    monkeypatch.setattr(live, "_verified_authorized_worker_process", refuse_binding)
    monkeypatch.setattr(
        live.psutil,
        "Process",
        lambda _pid: pytest.fail("no process may be opened after binding failure"),
    )

    with pytest.raises(live.LiveSupervisorError, match="identity changed"):
        live._terminate_authorized_worker(launcher, identity, grace=2.0)


def test_exact_timeout_kill_reuses_the_verified_process_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {"verifications": []}
    launcher = SimpleNamespace(pid=2468, wait=lambda timeout: 0)
    identity = _delegated_worker_identity(launcher)

    class Worker:
        def __init__(self):
            self.waits = 0

        def terminate(self):
            observed["terminate_object"] = id(self)

        def kill(self):
            observed["kill_object"] = id(self)

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise live.psutil.TimeoutExpired(timeout, pid=identity.worker_pid)
            return 0

    worker = Worker()

    def verify(process, exact_identity, *, worker=None):
        assert process is launcher
        assert exact_identity == identity
        observed["verifications"].append(worker)
        return worker if worker is not None else globals_worker

    globals_worker = worker
    monkeypatch.setattr(live, "_verified_authorized_worker_process", verify)

    live._terminate_authorized_worker(launcher, identity, grace=2.0)

    assert observed["verifications"] == [None, worker]
    assert observed["terminate_object"] == id(worker)
    assert observed["kill_object"] == id(worker)


def test_cancellation_helper_timeout_targets_discovered_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    cancel_request = attempt / "cancel-request.json"
    nonce = str(uuid.uuid4())
    write_json_with_digest(
        cancel_request,
        {
            "python_executable": sys.executable,
            "timeout_seconds": 2.0,
            "cancel_launch": {
                "launch_nonce": nonce,
                "intent_path": str(attempt / "cancel-intent.json"),
                "binding_path": str(attempt / "cancel-launcher.json"),
                "hello_path": str(attempt / "cancel-hello.json"),
                "authorization_path": str(attempt / "cancel-auth.json"),
            },
        },
    )
    request = {
        "python_executable": sys.executable,
        "repository_root": str(repository),
        "termination_grace_seconds": 2.0,
    }
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 2468

        def __init__(self, command, **_kwargs):
            observed["command"] = command

        def wait(self, timeout):
            raise subprocess.TimeoutExpired(observed["command"], timeout)

    identity = _delegated_worker_identity(FakeProcess)
    monkeypatch.setattr(
        live,
        "_create_cancellation_request",
        lambda *_: cancel_request,
    )
    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "_publish_cancel_launch_intent", lambda *_: HASH_A)
    monkeypatch.setattr(live, "_publish_cancel_launcher_binding", lambda *_: HASH_A)
    monkeypatch.setattr(
        live,
        "_authorize_cancel_helper",
        lambda process, *_: identity
        if process.pid == identity.launcher_pid
        else pytest.fail("cancellation helper authorization lost launch identity"),
    )
    monkeypatch.setattr(
        live,
        "_terminate_authorized_worker",
        lambda process, exact_identity, grace: observed.update(
            termination_pid=exact_identity.worker_pid,
            launcher_pid=process.pid,
            grace=grace,
        ),
    )

    safe, detail = live._run_cancellation_helper(attempt, request, HASH_A)

    assert safe is False
    assert detail == "cancellation_helper_timed_out"
    assert observed["termination_pid"] == identity.worker_pid
    assert observed["termination_pid"] != observed["launcher_pid"]


def _publish_duplicate_invariant_worker(
    attempt_dir: Path,
    request: dict,
    request_sha256: str,
) -> live.LiveChildOutcome:
    outcome = _publish_passing_worker_record(attempt_dir, request, request_sha256)
    worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
    worker["tables"]["invariants"][-1]["invariant_id"] = worker["tables"][
        "invariants"
    ][0]["invariant_id"]
    write_json_with_digest(
        attempt_dir / "worker_receipt.json",
        worker,
        replace=True,
    )
    return outcome


@pytest.mark.parametrize(
    ("forgery", "message"),
    [
        ("missing_tcu", "TCU proof"),
        ("truncated_tcu", "TCU proof"),
        ("wrong_tcu_install", "TCU install directory"),
        ("forged_execution", "calculation/provenance/finalization"),
        ("zero_create_time", "executable provenance"),
        ("runtime_timeout", "runtime evidence"),
        ("launch_runtime_mismatch", "launch identity"),
        ("launch_event_mismatch", "launch event disagrees"),
        ("forged_process", "complete-empty worker inventory"),
        ("truncated_global", "complete-empty worker inventory"),
        ("truncated_plan", "complete-empty exact-plan inventory"),
        ("missing_stage", "stage_project proof"),
        ("wrong_stage_algorithm", "stage_project proof"),
        ("broken_stage_chain", "stage_project fingerprint proof"),
        ("malformed_published_fingerprint", "stage_project fingerprint proof"),
        ("boolean_stage_file_count", "stage_project copy totals"),
        ("zero_stage_file_count", "stage_project copy totals"),
        ("negative_stage_bytes", "stage_project copy totals"),
        ("persisted_stage_mismatch", "persisted stage_project proof disagrees"),
    ],
)
def test_parent_rejects_minimal_or_forged_worker_execution_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forgery: str,
    message: str,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_forgery(attempt_dir: Path, request: dict, digest: str):
        outcome = _publish_passing_worker_record(attempt_dir, request, digest)
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        if forgery == "missing_tcu":
            worker.pop("tcu_status")
        elif forgery == "truncated_tcu":
            worker["tcu_status"].pop("reason")
        elif forgery == "wrong_tcu_install":
            worker["tcu_status"]["install_dir"] = str(tmp_path / "source")
        elif forgery == "forged_execution":
            worker["execution_result"]["execution_details"][
                "actual_engine_provenance_confirmed"
            ] = False
            write_json_with_digest(
                attempt_dir / "execution_result.json",
                worker["execution_result"],
                replace=True,
            )
            for item in worker["referenced_artifacts"]:
                if item["relative_path"] == "execution_result.json":
                    item["sha256"] = live.stable_sha256(
                        attempt_dir / "execution_result.json"
                    )[0]
        elif forgery == "zero_create_time":
            worker["execution_result"]["execution_details"][
                "launcher_create_time"
            ] = 0
            write_json_with_digest(
                attempt_dir / "execution_result.json",
                worker["execution_result"],
                replace=True,
            )
            for item in worker["referenced_artifacts"]:
                if item["relative_path"] == "execution_result.json":
                    item["sha256"] = live.stable_sha256(
                        attempt_dir / "execution_result.json"
                    )[0]
        elif forgery == "runtime_timeout":
            worker["execution_result"]["execution_details"][
                "runtime_timed_out"
            ] = True
            write_json_with_digest(
                attempt_dir / "execution_result.json",
                worker["execution_result"],
                replace=True,
            )
            next(
                item
                for item in worker["referenced_artifacts"]
                if item["relative_path"] == "execution_result.json"
            )["sha256"] = live.stable_sha256(
                attempt_dir / "execution_result.json"
            )[0]
        elif forgery == "launch_runtime_mismatch":
            worker["execution_result"]["execution_details"]["launch_details"][
                "max_runtime_seconds"
            ] += 1
            write_json_with_digest(
                attempt_dir / "execution_result.json",
                worker["execution_result"],
                replace=True,
            )
            next(
                item
                for item in worker["referenced_artifacts"]
                if item["relative_path"] == "execution_result.json"
            )["sha256"] = live.stable_sha256(
                attempt_dir / "execution_result.json"
            )[0]
        elif forgery == "launch_event_mismatch":
            launch_event = next(
                event
                for event in worker["tables"]["events"]
                if event["event_name"] == "engine_process_launched"
            )
            payload = json.loads(launch_event["payload_json"])
            payload["launch_method"] = "forged"
            launch_event["payload_json"] = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            (attempt_dir / "events.jsonl").write_bytes(
                b"".join(
                    (
                        json.dumps(
                            event,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                    for event in worker["tables"]["events"]
                )
            )
            next(
                item
                for item in worker["referenced_artifacts"]
                if item["relative_path"] == "events.jsonl"
            )["sha256"] = live.stable_sha256(attempt_dir / "events.jsonl")[0]
        elif forgery == "forged_process":
            worker["process_evidence"]["post_execution_global"]["processes"] = [
                {"pid": 4321}
            ]
        elif forgery == "truncated_global":
            worker["process_evidence"]["post_execution_global"].pop("observed_at")
        elif forgery == "truncated_plan":
            worker["process_evidence"]["post_execution_plan"].pop("plan_path")
        elif forgery == "missing_stage":
            worker.pop("stage_result")
        elif forgery == "wrong_stage_algorithm":
            worker["stage_result"]["fingerprint_algorithm"] = (
                "ras_commander.qualification_snapshot.canonical_json.v1"
            )
        elif forgery == "broken_stage_chain":
            worker["stage_result"]["copied_fingerprint"] = "3" * 64
        elif forgery == "malformed_published_fingerprint":
            worker["stage_result"]["published_fingerprint"] = "not-a-digest"
        elif forgery == "boolean_stage_file_count":
            worker["stage_result"]["copied_file_count"] = True
        elif forgery == "zero_stage_file_count":
            worker["stage_result"]["copied_file_count"] = 0
        elif forgery == "negative_stage_bytes":
            worker["stage_result"]["copied_bytes"] = -1
        else:
            stage_manifest = (
                Path(request["stage_root"]) / ".ras-commander" / "stage.json"
            )
            persisted = json.loads(stage_manifest.read_text(encoding="utf-8"))
            persisted["copied_bytes"] += 1
            stage_manifest.write_text(
                json.dumps(persisted, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        write_json_with_digest(
            attempt_dir / "worker_receipt.json",
            worker,
            replace=True,
        )
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_forgery)

    with pytest.raises(live.LiveSupervisorError, match=message):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert not host_lock.exists()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()


def test_parent_rejects_worker_claim_that_differs_from_execution_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_contradiction(attempt_dir: Path, request: dict, digest: str):
        outcome = _publish_passing_worker_record(attempt_dir, request, digest)
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        worker["execution_result"]["message_count"] = 99
        write_json_with_digest(
            attempt_dir / "worker_receipt.json", worker, replace=True
        )
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_contradiction)

    with pytest.raises(live.LiveSupervisorError, match="artifact differs"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert not host_lock.exists()


def test_parent_controller_proof_requires_exact_binary_identity(
    tmp_path: Path,
) -> None:
    controller = tmp_path / "HEC-RAS" / "Ras.exe"
    controller.parent.mkdir()
    controller.write_bytes(b"controller-binary-pin")
    source_project = tmp_path / "source" / "Model.prj"
    source_project.parent.mkdir()
    source_project.write_text("Proj Title=Controller proof\n", encoding="ascii")
    stage_root = tmp_path / "stage"
    request = {
        "timeout_seconds": 30,
        "stage_root": str(stage_root),
        "source_project": str(source_project),
        "fixture": {"plan_number": "01"},
    }
    engine = {
        "execution_api": "ras_control",
        "version_requested": "4.1.0",
        "expected_result_format": "legacy",
        "controller_version": "4.1.0",
        "resolved_controller_version": "4.1",
        "controller_progid": "RAS41.HECRASController",
        "controller_executable": str(controller),
        "controller_executable_sha256": live.stable_sha256(controller)[0],
        "blocking": False,
    }
    global_inventory = {
        "observed_at": 1787923200.0,
        "complete": True,
        "processes": [],
        "query_errors": [],
    }
    plan_inventory = {
        "observed_at": 1787923200.0,
        "complete": True,
        "plan_number": "01",
        "project_path": str(stage_root / source_project.name),
        "plan_path": str((stage_root / source_project.name).with_suffix(".p01")),
        "tmp_hdf_path": str(
            (stage_root / source_project.name).with_suffix(".p01.tmp.hdf")
        ),
        "matched": [],
        "query_errors": [],
    }
    worker = {
        "tcu_status": {
            "accepted": True,
            "version": "4.1.0",
            "install_dir": str(controller.parent),
            "registry_key": "test-registry/tcu",
            "reason": "accepted",
            "ras_version_argument": "4.1.0",
        },
        "process_evidence": {
            "pre_stage_global": global_inventory,
            "pre_setup_plan": plan_inventory,
            "pre_execute_global": global_inventory,
            "post_execution_plan": plan_inventory,
            "post_execution_global": global_inventory,
        },
        "execution_result": {
            "success": True,
            "completion_verified": None,
            "execution_details": {
                "execution_api": "ras_control",
                "engine_kind": "controller",
                "selected_result_format": "legacy",
                "calculation_attempted": True,
                "solver_quiescence_confirmed": True,
                "result_artifacts_finalized": True,
                "actual_engine_provenance_confirmed": True,
                "requested_controller_version": "4.1.0",
                "resolved_controller_version": "4.1",
                "controller_progid": "RAS41.HECRASController",
                "controller_pid": 1234,
                "controller_create_time": 12345.0,
                "controller_close_safe": True,
                "owned_process_exit_confirmed": True,
                "post_close_plan_processes_quiescent": True,
                "post_close_global_processes_quiescent": True,
                "compute_mode": "poll",
                "watchdog_requested": True,
                "watchdog_started": True,
                "strict_close_requested": True,
                "max_runtime_seconds": 30.0,
                "controller_executable_path": str(controller),
                "controller_executable_sha256": engine[
                    "controller_executable_sha256"
                ],
            },
        },
    }

    live._verify_worker_execution_proof(worker, request, engine)
    worker["execution_result"]["execution_details"][
        "controller_executable_sha256"
    ] = "0" * 64

    with pytest.raises(live.LiveSupervisorError, match="identity/close/watchdog"):
        live._verify_worker_execution_proof(worker, request, engine)


def test_tampered_worker_uses_independent_recovery_gate_before_host_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_duplicate_invariant_worker,
    )

    with pytest.raises(live.LiveSupervisorError, match="invariant IDs"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert not host_lock.exists()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()


def test_tampered_worker_and_source_drift_quarantines_without_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_and_drift(attempt_dir: Path, request: dict, digest: str):
        outcome = _publish_duplicate_invariant_worker(
            attempt_dir,
            request,
            digest,
        )
        Path(request["source_project"]).write_text(
            "Proj Title=drifted after worker\n",
            encoding="ascii",
        )
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_and_drift)

    with pytest.raises(live.LiveHostQuarantinedError, match="source snapshot drifted"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()
    host_lock.unlink()


def test_tampered_worker_and_uncertain_global_inventory_quarantines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    scans = 0

    def inventory_sequence():
        nonlocal scans
        scans += 1
        if scans == 3:
            raise live.LiveSupervisorError("global inventory query uncertainty")
        return _empty_inventory()

    monkeypatch.setattr(live, "_strict_process_inventory", inventory_sequence)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_duplicate_invariant_worker,
    )

    with pytest.raises(live.LiveHostQuarantinedError, match="query uncertainty"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()
    host_lock.unlink()


def test_crashed_worker_source_drift_publishes_no_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def crashed_after_drift(attempt_dir: Path, request: dict, _digest: str):
        (attempt_dir / "stdout.log").write_bytes(b"")
        (attempt_dir / "stderr.log").write_bytes(b"crashed\n")
        Path(request["source_project"]).write_text(
            "Proj Title=crash drift\n",
            encoding="ascii",
        )
        now = datetime.now(timezone.utc)
        return live.LiveChildOutcome(
            pid=6789,
            returncode=30,
            started_at=now,
            finished_at=now,
            timed_out=False,
        )

    monkeypatch.setattr(live, "_run_live_child", crashed_after_drift)

    with pytest.raises(live.LiveHostQuarantinedError, match="source snapshot drifted"):
        live.execute_live_action(context.run_root, acknowledge_real_ras=True)

    assert host_lock.is_file()
    attempt_dir = next(
        path
        for path in (context.run_root / "attempts" / "lane-live").iterdir()
        if path.is_dir()
    )
    assert not (attempt_dir / "receipt.json").exists()
    host_lock.unlink()


def test_outer_timeout_uses_exact_python_helper_and_never_raw_process_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    request = {
        "python_executable": sys.executable,
        "repository_root": str(repository),
        "preflight_timeout_seconds": 0.01,
        "timeout_seconds": 0.01,
        "termination_grace_seconds": 0.01,
        "postflight_timeout_seconds": 0.01,
        "supervisor_receipt_margin_seconds": 5.0,
        "engine": {"execution_api": "ras_cmdr"},
        "worker_launch": _worker_launch_metadata(attempt),
    }
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 2468

        def __init__(self, command, **kwargs):
            observed["command"] = command
            observed["kwargs"] = kwargs
            self.waits = 0

        def wait(self, timeout):
            self.waits += 1
            observed["wait_timeout"] = timeout
            if self.waits == 1:
                raise subprocess.TimeoutExpired(observed["command"], timeout)
            return 0

        def terminate(self):
            observed["terminated"] = True

        def kill(self):
            observed["killed"] = True

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "_publish_worker_launch_intent", lambda *_: HASH_A)
    monkeypatch.setattr(live, "_publish_worker_launcher_binding", lambda *_: HASH_A)
    monkeypatch.setattr(
        live,
        "_authorize_live_child",
        lambda process, *_, **__: _delegated_worker_identity(process),
    )
    monkeypatch.setattr(
        live,
        "_run_cancellation_helper",
        lambda *_: (True, "exact_plan_quiescence_confirmed"),
    )
    monkeypatch.setattr(
        live,
        "_terminate_authorized_worker",
        lambda process, identity, grace: observed.update(
            terminated_worker_pid=identity.worker_pid,
            launcher_pid=process.pid,
            termination_grace=grace,
        ),
    )

    outcome = live._run_live_child(attempt, request, "a" * 64)

    assert outcome.timed_out is True
    assert outcome.cancellation_safe is True
    assert outcome.pid == 9753
    assert observed["terminated_worker_pid"] == 9753
    assert observed["launcher_pid"] == 2468
    assert observed["wait_timeout"] == pytest.approx(35.03)
    command = observed["command"]
    assert command[1:3] == ["-m", "scripts.qualification.execution_evidence.live_worker"]
    assert all("taskkill" not in str(part).casefold() for part in command)


@pytest.mark.parametrize("cancellation_safe", [False, None])
def test_modern_unproven_timeout_leaves_python_child_and_logs_unterminalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancellation_safe: bool | None,
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    request = {
        "python_executable": sys.executable,
        "repository_root": str(repository),
        "preflight_timeout_seconds": 0.01,
        "timeout_seconds": 0.01,
        "termination_grace_seconds": 0.01,
        "postflight_timeout_seconds": 0.01,
        "supervisor_receipt_margin_seconds": 5.0,
        "engine": {"execution_api": "ras_cmdr"},
        "worker_launch": _worker_launch_metadata(attempt),
    }
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 2468

        def __init__(self, command, **kwargs):
            del kwargs
            observed["command"] = command

        def wait(self, timeout):
            observed["wait_timeout"] = timeout
            raise subprocess.TimeoutExpired(observed["command"], timeout)

        def terminate(self):
            observed["terminated"] = True

        def kill(self):
            observed["killed"] = True

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "_publish_worker_launch_intent", lambda *_: HASH_A)
    monkeypatch.setattr(live, "_publish_worker_launcher_binding", lambda *_: HASH_A)
    monkeypatch.setattr(
        live,
        "_authorize_live_child",
        lambda process, *_, **__: _direct_worker_identity(process),
    )
    monkeypatch.setattr(
        live,
        "_run_cancellation_helper",
        lambda *_: (cancellation_safe, "unconfirmed"),
    )

    outcome = live._run_live_child(attempt, request, "a" * 64)

    assert outcome.timed_out is True
    assert outcome.cancellation_safe is cancellation_safe
    assert observed["wait_timeout"] == pytest.approx(35.03)
    assert "terminated" not in observed
    assert "killed" not in observed
    assert (attempt / "stdout.log").is_file()
    assert (attempt / "stderr.log").is_file()
    assert not (attempt / "receipt.json").exists()


def test_controller_timeout_never_terminates_python_without_exact_quiescence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    request = {
        "python_executable": sys.executable,
        "repository_root": str(repository),
        "preflight_timeout_seconds": 0.01,
        "timeout_seconds": 0.01,
        "termination_grace_seconds": 0.01,
        "postflight_timeout_seconds": 0.01,
        "supervisor_receipt_margin_seconds": 5.0,
        "engine": {"execution_api": "ras_control"},
        "worker_launch": _worker_launch_metadata(attempt),
    }
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 1357

        def __init__(self, command, **kwargs):
            del kwargs
            observed["command"] = command

        def wait(self, timeout):
            observed["wait_timeout"] = timeout
            raise subprocess.TimeoutExpired(observed["command"], timeout)

        def terminate(self):
            observed["terminated"] = True

        def kill(self):
            observed["killed"] = True

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "_publish_worker_launch_intent", lambda *_: HASH_A)
    monkeypatch.setattr(live, "_publish_worker_launcher_binding", lambda *_: HASH_A)
    monkeypatch.setattr(
        live,
        "_authorize_live_child",
        lambda process, *_, **__: _direct_worker_identity(process),
    )
    monkeypatch.setattr(
        live,
        "_run_cancellation_helper",
        lambda *_: pytest.fail("Controller timeout has no exact cancellation helper"),
    )

    outcome = live._run_live_child(attempt, request, "a" * 64)

    assert outcome.timed_out is True
    assert outcome.cancellation_safe is False
    assert outcome.cancellation_reason == "controller_outer_deadline_exceeded"
    assert observed["wait_timeout"] == pytest.approx(35.03)
    assert "terminated" not in observed
    assert "killed" not in observed


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("preflight_timeout_seconds", None),
        ("postflight_timeout_seconds", 0),
        ("timeout_seconds", None),
        ("timeout_seconds", True),
        ("timeout_seconds", float("nan")),
        ("termination_grace_seconds", 0),
        ("supervisor_receipt_margin_seconds", 4.0),
    ],
)
def test_outer_worker_deadline_rejects_unbound_or_nonfinite_durations(
    field: str,
    invalid_value: object,
) -> None:
    request = {
        "preflight_timeout_seconds": 10.0,
        "timeout_seconds": 30.0,
        "termination_grace_seconds": 2.0,
        "postflight_timeout_seconds": 10.0,
        "supervisor_receipt_margin_seconds": 5.0,
    }
    request[field] = invalid_value

    with pytest.raises(live.LiveSupervisorError):
        live._outer_worker_deadline_seconds(request)


def test_outer_worker_deadline_reserves_preflight_engine_cancel_and_postflight() -> None:
    request = {
        "preflight_timeout_seconds": 10.0,
        "timeout_seconds": 30.0,
        "termination_grace_seconds": 2.0,
        "postflight_timeout_seconds": 10.0,
        "supervisor_receipt_margin_seconds": 5.0,
    }

    assert live._outer_worker_deadline_seconds(request) == pytest.approx(85.0)


def test_outer_worker_deadline_rejects_nonfinite_sum() -> None:
    request = {
        "preflight_timeout_seconds": 1e308,
        "timeout_seconds": 1e308,
        "termination_grace_seconds": 30.0,
        "postflight_timeout_seconds": 1e308,
        "supervisor_receipt_margin_seconds": 5.0,
    }

    with pytest.raises(live.LiveSupervisorError, match="not finite"):
        live._outer_worker_deadline_seconds(request)


def test_outer_worker_deadline_rejects_unrepresentable_windows_wait() -> None:
    request = {
        "preflight_timeout_seconds": 10.0,
        "timeout_seconds": 4_294_967.0,
        "termination_grace_seconds": 30.0,
        "postflight_timeout_seconds": 10.0,
        "supervisor_receipt_margin_seconds": 5.0,
    }

    with pytest.raises(live.LiveSupervisorError, match="subprocess-wait range"):
        live._outer_worker_deadline_seconds(request)


def test_cancel_helper_refuses_legacy_boolean_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ras_commander import RasCmdr

    monkeypatch.setattr(RasCmdr, "cancel_plan_exact", None, raising=False)
    monkeypatch.setattr(RasCmdr, "inspect_plan_processes", None, raising=False)

    with pytest.raises(
        live_cancel_worker.LiveCancellationError,
        match="structured RasCmdr cancellation APIs are unavailable",
    ):
        live_cancel_worker._cancel_exact_plan(
            "01",
            ras_object=object(),
            timeout_seconds=1,
        )


def test_cancel_helper_requires_structured_quiescence_and_publishes_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    stage_project = stage / "Model.prj"
    stage_project.write_text("Proj Title=cancel test\n", encoding="ascii")
    receipt_path = tmp_path / "cancel-receipt.json"
    request = {
        "run_id": "run-1",
        "lane_id": "lane-live",
        "attempt_id": "attempt-1",
        "manifest_sha256": HASH_A,
        "git_head": GIT_HEAD,
        "live_request_sha256": "b" * 64,
        "cancel_receipt_path": str(receipt_path),
        "stage_project": str(stage_project),
        "plan_number": "01",
        "timeout_seconds": 1,
    }
    live_request = {"engine": {"execution_api": "ras_cmdr"}}

    cancellation = _StructuredEvidence(
        cancellation_attempted=True,
        pre_scan_complete=True,
        post_scan_complete=True,
        matched=[],
        stopped=[],
        survivors=[],
        query_errors=[],
        quiescence_confirmed=True,
    )
    post_inventory = _StructuredEvidence(
        complete=True,
        matched=[],
        query_errors=[],
    )
    monkeypatch.setattr(
        live_cancel_worker,
        "_load_and_verify_request",
        lambda _: (request, "c" * 64, live_request),
    )
    monkeypatch.setattr(
        live_cancel_worker,
        "_initialize_staged_project",
        lambda *_: object(),
    )
    monkeypatch.setattr(
        live_cancel_worker,
        "_cancel_exact_plan",
        lambda *_args, **_kwargs: (cancellation, post_inventory),
    )
    global_inventory = _StructuredEvidence(
        complete=True,
        processes=[],
        query_errors=[],
    )
    monkeypatch.setattr(
        live_cancel_worker,
        "_complete_empty_global_inventory",
        lambda: global_inventory,
    )

    receipt = live_cancel_worker.execute_cancellation(tmp_path / "unused.json")

    verified, _ = read_json_with_digest(receipt_path)
    assert verified == receipt
    assert receipt["safe_to_terminate_child"] is True
    assert receipt["quiescence_confirmed"] is True
    assert receipt["post_global_inventory"] == global_inventory.to_dict()


@pytest.mark.parametrize(
    ("inventory", "message"),
    [
        (
            _StructuredEvidence(complete=False, processes=[], query_errors=[]),
            "incomplete",
        ),
        (
            _StructuredEvidence(
                complete=True,
                processes=[],
                query_errors=[{"pid": 7, "reason_code": "access_denied"}],
            ),
            "query errors",
        ),
        (
            _StructuredEvidence(
                complete=True,
                processes=[{"pid": 77, "create_time": 200.0}],
                query_errors=[],
            ),
            "not empty",
        ),
    ],
)
def test_cancel_helper_final_global_scan_fails_closed_for_partial_or_pid_reuse_shape(
    monkeypatch: pytest.MonkeyPatch,
    inventory: _StructuredEvidence,
    message: str,
) -> None:
    from ras_commander import RasControl

    # A PID/create-time-shaped row is still an extant global process.  The
    # helper never infers that a reused PID is harmless.
    monkeypatch.setattr(RasControl, "inspect_processes", lambda: inventory)

    with pytest.raises(live_cancel_worker.LiveCancellationError, match=message):
        live_cancel_worker._complete_empty_global_inventory()


def test_resume_reuses_verified_terminal_without_capability_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)
    completed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )
    assert len(completed) == 1
    monkeypatch.setattr(
        live,
        "_require_strict_live_api_contracts",
        lambda *_: pytest.fail("no capability probe when every lane is terminal"),
    )

    assert live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
        resume=True,
    ) == ()


def test_safe_modern_timeout_is_terminalized_but_never_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_safe_failed_worker_record,
    )

    failed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )

    assert len(failed) == 1
    failed_receipt = failed[0].receipt
    assert failed_receipt["terminal_category"] == "execution_failed"
    assert failed_receipt["execution_result"]["success"] is False
    assert failed_receipt["execution_result"]["completion_verified"] is False
    assert host_lock.exists() is False
    assert live._lane_has_verified_terminal(context, "lane-live") is False

    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)
    retried = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
        resume=True,
    )

    assert len(retried) == 1
    assert retried[0].receipt["terminal_category"] == "passed"
    assert retried[0].receipt["attempt_id"] != failed_receipt["attempt_id"]


def test_safe_modern_finalization_failure_is_terminalized_but_never_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_safe_finalization_failed_worker_record,
    )

    failed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )

    assert len(failed) == 1
    receipt = failed[0].receipt
    execution = receipt["execution_result"]
    assert receipt["terminal_category"] == "execution_failed"
    assert execution["success"] is False
    assert execution["completion_verified"] is True
    assert execution["execution_details"]["result_artifacts_finalized"] is False
    assert receipt["tables"]["lanes"][0]["completion_verified"] is True
    assert host_lock.exists() is False
    assert live._lane_has_verified_terminal(context, "lane-live") is False

    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)
    retried = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
        resume=True,
    )
    assert len(retried) == 1
    assert retried[0].receipt["terminal_category"] == "passed"
    assert retried[0].receipt["attempt_id"] != receipt["attempt_id"]


def test_parent_preserves_timeout_primary_with_secondary_finalization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_timeout_with_secondary_finalization_failure,
    )

    failed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )

    details = failed[0].receipt["execution_result"]["execution_details"]
    assert details["runtime_timed_out"] is True
    assert details["failure_stage"] == "subprocess_wait"
    assert details["failure_type"] == "TimeoutError"
    assert details["artifact_finalization_failure"]["failure_type"] == "OSError"
    assert live._lane_has_verified_terminal(context, "lane-live") is False


def test_parent_accepts_callback_timeout_error_without_runtime_deadline_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_callback_timeout_error_worker_record,
    )

    failed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )

    execution = failed[0].receipt["execution_result"]
    details = execution["execution_details"]
    assert failed[0].receipt["terminal_category"] == "execution_failed"
    assert execution["completion_verified"] is True
    assert details["runtime_timed_out"] is False
    assert details["failure_type"] == "TimeoutError"
    assert details["failure_stage"] == "stream_callback"
    assert live._lane_has_verified_terminal(context, "lane-live") is False


def test_parent_accepts_digest_bound_failed_inspection_as_nonreusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_run_live_child",
        _publish_failed_inspection_worker_record,
    )

    failed = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
    )

    receipt = failed[0].receipt
    assert receipt["terminal_category"] == "execution_failed"
    assert receipt["evidence"]["evidence_kind"] == (
        "execution_evidence_inspection_failure"
    )
    assert receipt["tables"]["observations"] == []
    assert receipt["tables"]["lanes"][0]["final_hdf_exists"] is True
    assert receipt["tables"]["lanes"][0]["final_legacy_exists"] is True
    assert live._lane_has_verified_terminal(context, "lane-live") is False


@pytest.mark.parametrize(
    "tamper",
    ["reason", "path", "mtime", "order", "version", "event", "observations"],
)
def test_parent_rejects_tampered_failed_inspection_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_forgery(
        attempt_dir: Path,
        request: dict,
        digest: str,
    ) -> live.LiveChildOutcome:
        outcome = _publish_failed_inspection_worker_record(
            attempt_dir,
            request,
            digest,
        )
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        evidence = worker["evidence"]
        if tamper == "reason":
            evidence["reason_code"] = "invented_ambiguity_reason"
        elif tamper == "path":
            evidence["hdf_path"] = evidence["legacy_output_path"]
        elif tamper == "mtime":
            evidence["hdf_mtime_ns"] += 1
        elif tamper == "order":
            hdf = Path(evidence["hdf_path"])
            legacy = Path(evidence["legacy_output_path"])
            os.utime(hdf, ns=(1787923202000000000, 1787923202000000000))
            os.utime(legacy, ns=(1787923201000000000, 1787923201000000000))
            evidence["hdf_mtime_ns"] = hdf.stat().st_mtime_ns
            evidence["legacy_mtime_ns"] = legacy.stat().st_mtime_ns
        elif tamper == "version":
            evidence["declared_program_version"] = "6.6"
        elif tamper == "event":
            next(
                row
                for row in worker["tables"]["events"]
                if row["event_name"] == "execution_evidence_inspection_failed"
            )["status"] = "passed"
        elif tamper == "observations":
            worker["tables"]["observations"] = valid_table_rows(
                run_id=request["run_id"],
                lane_id=request["lane_id"],
                attempt_id=request["attempt_id"],
            )["observations"]
        else:  # pragma: no cover - closed parametrization above
            raise AssertionError(tamper)
        _rewrite_worker_inspection_evidence(attempt_dir, worker)
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_forgery)
    with pytest.raises(live.LiveSupervisorError):
        live.execute_live_action(
            context.run_root,
            acknowledge_real_ras=True,
        )
    assert host_lock.exists() is False


def test_parent_rejects_success_with_secondary_finalization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_forgery(
        attempt_dir: Path,
        request: dict,
        digest: str,
    ) -> live.LiveChildOutcome:
        outcome = _publish_passing_worker_record(attempt_dir, request, digest)
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        worker["execution_result"]["execution_details"][
            "artifact_finalization_failure"
        ] = {
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "forged secondary failure",
        }
        _rewrite_worker_execution_result(attempt_dir, worker)
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_forgery)
    with pytest.raises(live.LiveSupervisorError, match="secondary failure metadata"):
        live.execute_live_action(
            context.run_root,
            acknowledge_real_ras=True,
        )
    assert host_lock.exists() is False


def test_parent_rejects_success_without_observation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_forgery(
        attempt_dir: Path,
        request: dict,
        digest: str,
    ) -> live.LiveChildOutcome:
        outcome = _publish_passing_worker_record(attempt_dir, request, digest)
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        worker["tables"]["observations"] = []
        _rewrite_worker_inspection_evidence(attempt_dir, worker)
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_forgery)
    with pytest.raises(
        live.LiveSupervisorError,
        match="lacks nonempty observation evidence",
    ):
        live.execute_live_action(
            context.run_root,
            acknowledge_real_ras=True,
        )


@pytest.mark.parametrize(
    "forgery",
    [
        "completion_not_boolean",
        "timeout_type_mismatch",
        "missing_finalization_failure",
        "invalid_finalization_failure",
        "missing_cancellation",
        "unconfirmed_cancellation",
        "known_survivor",
        "initial_match_not_stopped",
    ],
)
def test_parent_rejects_incoherent_modern_failure_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forgery: str,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    def publish_forgery(
        attempt_dir: Path,
        request: dict,
        digest: str,
    ) -> live.LiveChildOutcome:
        outcome = _publish_safe_failed_worker_record(attempt_dir, request, digest)
        worker, _ = read_json_with_digest(attempt_dir / "worker_receipt.json")
        execution = worker["execution_result"]
        details = execution["execution_details"]
        if forgery == "completion_not_boolean":
            execution["completion_verified"] = None
        elif forgery == "timeout_type_mismatch":
            details["failure_type"] = "RuntimeError"
        elif forgery == "missing_finalization_failure":
            details["result_artifacts_finalized"] = False
            details["artifact_finalization_failure"] = None
        elif forgery == "invalid_finalization_failure":
            details["result_artifacts_finalized"] = False
            details["artifact_finalization_failure"] = {
                "failure_stage": "solver_quiescence",
                "failure_type": "OSError",
                "failure_detail": "wrong stage",
            }
        elif forgery == "missing_cancellation":
            details["cancellation_details"] = None
        elif forgery == "unconfirmed_cancellation":
            details["cancellation_details"]["quiescence_confirmed"] = None
        elif forgery == "known_survivor":
            details["cancellation_details"]["survivors"] = list(
                details["cancellation_details"]["matched"]
            )
        elif forgery == "initial_match_not_stopped":
            details["cancellation_details"]["stopped"] = []
        else:  # pragma: no cover - closed parametrization above
            raise AssertionError(forgery)
        write_json_with_digest(
            attempt_dir / "execution_result.json",
            execution,
            replace=True,
        )
        next(
            item
            for item in worker["referenced_artifacts"]
            if item["relative_path"] == "execution_result.json"
        )["sha256"] = live.stable_sha256(
            attempt_dir / "execution_result.json"
        )[0]
        write_json_with_digest(
            attempt_dir / "worker_receipt.json",
            worker,
            replace=True,
        )
        return outcome

    monkeypatch.setattr(live, "_run_live_child", publish_forgery)

    with pytest.raises(live.LiveSupervisorError):
        live.execute_live_action(
            context.run_root,
            acknowledge_real_ras=True,
        )
    assert host_lock.exists() is False


@pytest.mark.parametrize(
    "omitted_gate",
    [
        "hec_ras_invoked",
        "supervisor_synthesized",
        "worker_binding",
        "required_invariants",
        "invariant_pass",
        "lane_all_passed",
        "result_family",
        "final_inventory",
        "fixture_identity",
        "engine_identity",
        "source_identity",
        "current_source_metadata",
        "stage_identity",
        "runtime_identity",
        "manifest_identity",
        "git_identity",
    ],
)
def test_resume_rejects_terminal_when_any_semantic_live_gate_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    omitted_gate: str,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)
    completed = live.execute_live_action(context.run_root, acknowledge_real_ras=True)
    attempt_dir = completed[0].attempt_dir
    receipt, _ = read_json_with_digest(attempt_dir / "receipt.json")

    if omitted_gate == "hec_ras_invoked":
        receipt["hec_ras_invoked"] = False
    elif omitted_gate == "supervisor_synthesized":
        receipt["supervisor_synthesized"] = True
    elif omitted_gate == "worker_binding":
        receipt["worker_receipt_sha256"] = "f" * 64
    elif omitted_gate == "required_invariants":
        receipt["required_invariants"] = receipt["required_invariants"][:-1]
    elif omitted_gate == "invariant_pass":
        receipt["tables"]["invariants"][0]["status"] = "fail"
    elif omitted_gate == "lane_all_passed":
        receipt["tables"]["lanes"][0]["all_invariants_passed"] = False
    elif omitted_gate == "result_family":
        receipt["tables"]["lanes"][0]["selected_result_format"] = "legacy"
    elif omitted_gate == "final_inventory":
        receipt["supervisor_post_inventory"]["processes"] = [
            {"pid": 9, "create_time": 10.0}
        ]
    elif omitted_gate == "fixture_identity":
        receipt["tables"]["lanes"][0]["fixture_id"] = "stale-fixture"
    elif omitted_gate == "engine_identity":
        receipt["tables"]["lanes"][0]["engine_id"] = "stale-engine"
    elif omitted_gate == "source_identity":
        receipt["tables"]["lanes"][0]["source_content_fingerprint"] = "0" * 64
    elif omitted_gate == "current_source_metadata":
        source = Path(context.manifest["fixtures"][0]["source_project"])
        info = source.stat()
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    elif omitted_gate == "stage_identity":
        receipt["tables"]["lanes"][0]["stage_project"] = str(
            tmp_path / "redirected" / "Model.prj"
        )
    elif omitted_gate == "runtime_identity":
        receipt["python_version"] = "stale-runtime"
    elif omitted_gate == "manifest_identity":
        context.manifest["manifest_sha256"] = "1" * 64
    elif omitted_gate == "git_identity":
        context.descriptor["git_head"] = "2" * 40
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(omitted_gate)

    if omitted_gate not in {
        "current_source_metadata",
        "manifest_identity",
        "git_identity",
    }:
        write_json_with_digest(
            attempt_dir / "receipt.json",
            receipt,
            replace=True,
        )
    assert live._lane_has_verified_terminal(context, "lane-live") is False


def test_resume_retries_verified_timeout_with_fresh_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    old_attempt_id = "old-timeout"
    old_attempt = context.run_root / "attempts" / "lane-live" / old_attempt_id
    old_attempt.mkdir(parents=True)
    request = {
        "schema_version": 1,
        "action": "run",
        "run_id": context.descriptor["run_id"],
        "lane_id": "lane-live",
        "attempt_id": old_attempt_id,
        "manifest_sha256": context.manifest["manifest_sha256"],
        "git_head": context.descriptor["git_head"],
        "required_invariants": list(_LIVE_INVARIANT_NAMES),
        **{
            field: context.descriptor[field]
            for field in (
                "python_executable",
                "python_executable_sha256",
                "python_version",
                "pyarrow_version",
                "psutil_version",
                "ras_commander_version",
                "ras_commander_import_path",
            )
        },
    }
    request_sha256 = write_json_with_digest(old_attempt / "request.json", request)
    receipt = {
        **request,
        "request_sha256": request_sha256,
        "receipt_committed_at": "2026-08-28T12:00:00+00:00",
        "terminal_category": "timed_out",
        "worker_exit_code": 124,
        "referenced_artifacts": [],
    }
    write_json_with_digest(old_attempt / "receipt.json", receipt)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    _enable_test_orchestration(monkeypatch, context, host_lock)
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(live, "_run_live_child", _publish_passing_worker_record)

    attempts = live.execute_live_action(
        context.run_root,
        acknowledge_real_ras=True,
        resume=True,
    )

    assert len(attempts) == 1
    assert attempts[0].receipt["attempt_id"] != old_attempt_id
    assert old_attempt.is_dir()


def test_status_is_read_only_and_does_not_probe_hec_ras(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    host_lock = tmp_path / "locks" / "real-engine.lock"
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_host_lock_path", lambda: host_lock)
    monkeypatch.setattr(
        live,
        "_strict_process_inventory",
        lambda: pytest.fail("status must not inspect HEC-RAS"),
    )
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    status = live.live_status(context.run_root)

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before
    assert status["attempts"] == []
    assert status["hec_ras_invoked"] is False
    assert all(item["reason_code"] == "lock_missing" for item in status["locks"])


def _retained_lock_fixture(
    tmp_path: Path,
) -> tuple[RunContext, Path, ExclusiveQualificationLock, LockState]:
    context = _context(tmp_path)
    lock_path = tmp_path / "locks" / "real-engine.lock"
    lock = ExclusiveQualificationLock(
        lock_path,
        kind="real_engine",
        run_id=context.descriptor["run_id"],
        lane_id="lane-live",
        attempt_id="retained-attempt",
        git_head=context.descriptor["git_head"],
    )
    payload = lock.acquire()
    live.create_live_attempt_request(
        context,
        lane_id="lane-live",
        attempt_id="retained-attempt",
        process_baseline=_empty_inventory(),
        real_engine_lock_path=lock_path,
        real_engine_lock_payload=payload,
    )
    return context, lock_path, lock, inspect_lock(lock_path)


def _publish_worker_lease(
    context: RunContext,
    *,
    pid: int,
    process_create_time: float,
    authorize: bool = True,
    delegated_launcher: tuple[int, float] | None = None,
) -> None:
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    request, request_sha256 = read_json_with_digest(attempt_dir / "request.json")
    intent_sha256 = live._publish_worker_launch_intent(
        attempt_dir, request, request_sha256
    )
    intent, _ = read_json_with_digest(attempt_dir / "worker-launch-intent.json")
    parent_pid, parent_create_time = delegated_launcher or (
        intent["supervisor_pid"],
        intent["supervisor_process_create_time"],
    )
    launcher_pid, launcher_create_time = delegated_launcher or (
        pid,
        process_create_time,
    )
    binding_sha256 = write_json_with_digest(
        request["worker_launch"]["binding_path"],
        {
            "schema_version": 1,
            "action": "bind_live_worker_launcher",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_nonce": request["worker_launch"]["launch_nonce"],
            "run_id": request["run_id"],
            "lane_id": request["lane_id"],
            "attempt_id": request["attempt_id"],
            "real_engine_lock_token": request["real_engine_lock"]["token"],
            "launcher_pid": launcher_pid,
            "launcher_process_create_time": launcher_create_time,
            "expected_command": live._worker_command(
                request, attempt_dir / "request.json"
            ),
        },
    )
    hello = {
        "schema_version": 1,
        "action": "hello_live_worker",
        "created_at": "2026-08-28T12:00:00+00:00",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": request["worker_launch"]["launch_nonce"],
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "worker_pid": pid,
        "worker_process_create_time": process_create_time,
        "worker_parent_pid": parent_pid,
        "worker_parent_process_create_time": parent_create_time,
    }
    hello_sha256 = write_json_with_digest(
        request["worker_launch"]["hello_path"], hello
    )
    if authorize:
        authorization = {
            "schema_version": 1,
            "action": "authorize_live_worker",
            "authorized_at": "2026-08-28T12:00:01+00:00",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_binding_sha256": binding_sha256,
            "worker_hello_sha256": hello_sha256,
            "launch_nonce": request["worker_launch"]["launch_nonce"],
            "run_id": request["run_id"],
            "lane_id": request["lane_id"],
            "attempt_id": request["attempt_id"],
            "real_engine_lock_token": request["real_engine_lock"]["token"],
            "worker_pid": pid,
            "worker_process_create_time": process_create_time,
            "worker_parent_pid": parent_pid,
            "worker_parent_process_create_time": parent_create_time,
            "launcher_pid": parent_pid if delegated_launcher else pid,
            "launcher_process_create_time": (
                parent_create_time if delegated_launcher else process_create_time
            ),
            "launcher_delegated": delegated_launcher is not None,
            "supervisor_pid": intent["supervisor_pid"],
            "supervisor_process_create_time": intent[
                "supervisor_process_create_time"
            ],
        }
        write_json_with_digest(
            request["worker_launch"]["authorization_path"], authorization
        )


def _publish_cancel_lease(
    context: RunContext,
    *,
    publish_hello: bool,
    worker_pid: int = 9876,
    worker_create_time: float = 123.0,
    launcher_pid: int = 8765,
    launcher_create_time: float = 122.0,
) -> tuple[Path, dict]:
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    live_request, live_sha256 = read_json_with_digest(attempt_dir / "request.json")
    cancel_path = live._create_cancellation_request(
        attempt_dir,
        live_request,
        live_sha256,
    )
    request, request_sha256 = read_json_with_digest(cancel_path)
    intent_sha256 = live._publish_cancel_launch_intent(
        attempt_dir,
        request,
        request_sha256,
    )
    nonce = request["cancel_launch"]["launch_nonce"]
    binding_sha256 = write_json_with_digest(
        request["cancel_launch"]["binding_path"],
        {
            "schema_version": 1,
            "action": "bind_cancel_helper_launcher",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_nonce": nonce,
            "run_id": request["run_id"],
            "lane_id": request["lane_id"],
            "attempt_id": request["attempt_id"],
            "real_engine_lock_token": request["real_engine_lock"]["token"],
            "launcher_pid": launcher_pid,
            "launcher_process_create_time": launcher_create_time,
            "expected_command": live._cancel_worker_command(request, cancel_path),
        },
    )
    if publish_hello:
        write_json_with_digest(
            request["cancel_launch"]["hello_path"],
            {
                "schema_version": 1,
                "action": "hello_cancel_helper",
                "request_sha256": request_sha256,
                "launch_intent_sha256": intent_sha256,
                "launch_binding_sha256": binding_sha256,
                "launch_nonce": nonce,
                "run_id": request["run_id"],
                "lane_id": request["lane_id"],
                "attempt_id": request["attempt_id"],
                "real_engine_lock_token": request["real_engine_lock"]["token"],
                "worker_pid": worker_pid,
                "worker_process_create_time": worker_create_time,
                "worker_parent_pid": launcher_pid,
                "worker_parent_process_create_time": launcher_create_time,
            },
        )
    return attempt_dir, live_request


def test_cancel_recovery_fails_closed_after_launcher_binding_without_hello(
    tmp_path: Path,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    attempt_dir, live_request = _publish_cancel_lease(
        context,
        publish_hello=False,
    )

    safe, detail = live._cancel_launch_recovery_gate(attempt_dir, live_request)

    assert safe is False
    assert "hello publication is incomplete" in detail
    lock.release()


def test_cancel_worker_refuses_action_without_exact_launch_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    attempt_dir, _live_request = _publish_cancel_lease(
        context,
        publish_hello=False,
    )
    cancel_path = attempt_dir / "cancel-request.json"
    cancel_request, _ = read_json_with_digest(cancel_path)
    monkeypatch.setattr(
        live_cancel_worker,
        "execute_cancellation",
        lambda *_: pytest.fail("cancellation action ran before authorization"),
    )

    returncode = live_cancel_worker.main(
        [
            "--request",
            str(cancel_path),
            "--launch-nonce",
            cancel_request["cancel_launch"]["launch_nonce"],
        ]
    )

    assert returncode == 30
    lock.release()


def test_cancel_recovery_requires_exact_delegated_launcher_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    attempt_dir, live_request = _publish_cancel_lease(
        context,
        publish_hello=True,
    )

    def inspect(pid, create_time):
        alive = pid == 8765
        return live.WorkerIdentityState(
            alive,
            "worker_alive" if alive else "worker_absent",
            pid,
            create_time,
        )

    monkeypatch.setattr(live, "_inspect_exact_worker_identity", inspect)

    safe, detail = live._cancel_launch_recovery_gate(attempt_dir, live_request)

    assert safe is False
    assert "cancellation launcher is alive" in detail
    lock.release()


def test_recovery_without_authorization_requires_delegated_launcher_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(
        context,
        pid=9876,
        process_create_time=123.0,
        authorize=False,
        delegated_launcher=(8765, 122.0),
    )
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    request, _ = read_json_with_digest(attempt_dir / "request.json")

    def inspect(pid, create_time):
        if pid == 9876:
            return live.WorkerIdentityState(False, "worker_absent", pid, create_time)
        return live.WorkerIdentityState(True, "worker_alive", pid, create_time)

    monkeypatch.setattr(live, "_inspect_exact_worker_identity", inspect)

    safe, detail = live._worker_launch_recovery_gate(attempt_dir, request)

    assert safe is False
    assert "delegated Python launcher is still alive" in detail
    lock.release()


def test_recovery_rejects_unbound_non_supervisor_parent_before_authorization(
    tmp_path: Path,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(
        context,
        pid=9876,
        process_create_time=123.0,
        authorize=False,
        delegated_launcher=(8765, 122.0),
    )
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    request, _ = read_json_with_digest(attempt_dir / "request.json")
    hello_path = Path(request["worker_launch"]["hello_path"])
    hello, _ = read_json_with_digest(hello_path)
    hello["worker_parent_pid"] = 7654
    write_json_with_digest(hello_path, hello, replace=True)

    safe, detail = live._worker_launch_recovery_gate(attempt_dir, request)

    assert safe is False
    assert "relationship is unverifiable" in detail
    lock.release()


def test_recovery_without_authorization_accepts_absent_worker_and_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(
        context,
        pid=9876,
        process_create_time=123.0,
        authorize=False,
        delegated_launcher=(8765, 122.0),
    )
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    request, _ = read_json_with_digest(attempt_dir / "request.json")
    monkeypatch.setattr(
        live,
        "_inspect_exact_worker_identity",
        lambda pid, create_time: live.WorkerIdentityState(
            False, "worker_absent", pid, create_time
        ),
    )

    safe, detail = live._worker_launch_recovery_gate(attempt_dir, request)

    assert safe is True
    assert "worker and delegated launcher are absent" in detail
    lock.release()


def test_recovery_uses_digest_bound_delegated_launcher_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(
        context,
        pid=9876,
        process_create_time=123.0,
        authorize=True,
        delegated_launcher=(8765, 122.0),
    )
    attempt_dir = (
        context.run_root / "attempts" / "lane-live" / "retained-attempt"
    )
    request, _ = read_json_with_digest(attempt_dir / "request.json")

    def inspect(pid, create_time):
        alive = pid == 8765
        return live.WorkerIdentityState(
            alive,
            "worker_alive" if alive else "worker_absent",
            pid,
            create_time,
        )

    monkeypatch.setattr(live, "_inspect_exact_worker_identity", inspect)

    safe, detail = live._worker_launch_recovery_gate(attempt_dir, request)

    assert safe is False
    assert "delegated Python launcher is still alive" in detail
    lock.release()


@pytest.mark.parametrize(
    ("alive", "reason_code", "expected_message"),
    [
        (True, "worker_alive", "still alive"),
        (None, "worker_identity_unverifiable", "unverifiable"),
    ],
)
def test_recovery_refuses_live_or_unverifiable_exact_worker_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alive: bool | None,
    reason_code: str,
    expected_message: str,
) -> None:
    context, lock_path, lock, state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(context, pid=9876, process_create_time=123.0)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_owner_absent",
        ),
    )
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_inspect_exact_worker_identity",
        lambda pid, create_time: live.WorkerIdentityState(
            alive, reason_code, pid, create_time
        ),
    )

    with pytest.raises(live.LiveSupervisorError, match=expected_message):
        live.recover_live_host_lock(
            context.run_root,
            acknowledge_recovery=True,
        )

    assert lock_path.exists()
    lock.release()


def test_recovery_accepts_reused_pid_as_exact_worker_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, _lock, state = _retained_lock_fixture(tmp_path)
    _publish_worker_lease(context, pid=9876, process_create_time=123.0)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_pid_reused",
        ),
    )
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    monkeypatch.setattr(
        live,
        "_inspect_exact_worker_identity",
        lambda pid, create_time: live.WorkerIdentityState(
            False, "worker_pid_reused", pid, create_time
        ),
    )

    receipt = live.recover_live_host_lock(
        context.run_root,
        acknowledge_recovery=True,
    )

    assert receipt["retirement_state"] == "atomically_retired"
    assert "worker_pid_reused" in receipt["final_recovery_gate_proof"]
    assert receipt["source_snapshot"] == receipt["final_source_snapshot"]
    assert not lock_path.exists()


@pytest.mark.parametrize("reason", ["lock_owner_absent", "lock_pid_reused"])
def test_acknowledged_recovery_atomically_retires_proved_stale_real_engine_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    context, lock_path, _lock, state = _retained_lock_fixture(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(state, owner_alive=False, reason_code=reason),
    )
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    receipt = live.recover_live_host_lock(
        context.run_root,
        acknowledge_recovery=True,
    )

    assert receipt["retirement_state"] == "atomically_retired"
    assert receipt["global_inventory"]["processes"] == []
    assert receipt["source_snapshot"] == receipt["final_source_snapshot"]
    assert not lock_path.exists()
    recovery_receipts = list(
        (context.run_root / "recoveries").glob("*/recovery-receipt.json")
    )
    assert len(recovery_receipts) == 1
    verified, _ = read_json_with_digest(recovery_receipts[0])
    assert verified == receipt


def test_recovery_refuses_live_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, lock, _state = _retained_lock_fixture(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)

    with pytest.raises(live.LiveSupervisorError, match="owner absence"):
        live.recover_live_host_lock(context.run_root, acknowledge_recovery=True)

    assert lock_path.exists()
    lock.release()


def test_recovery_refuses_source_snapshot_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, lock, state = _retained_lock_fixture(tmp_path)
    source_project = Path(context.manifest["fixtures"][0]["source_project"])
    source_project.write_text(
        "Proj Title=Live qualification changed\n",
        encoding="ascii",
    )
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_owner_absent",
        ),
    )
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)

    with pytest.raises(live.LiveSupervisorError, match="source snapshot drifted"):
        live.recover_live_host_lock(
            context.run_root,
            acknowledge_recovery=True,
        )

    assert lock_path.exists()
    lock.release()


def test_recovery_reproves_source_immediately_before_lock_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, lock, state = _retained_lock_fixture(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_owner_absent",
        ),
    )
    calls = 0

    def changing_recovery_gate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return live.RecoveryGateOutcome(
                True,
                "initial source/process proof",
                _empty_inventory(),
                {
                    "content_fingerprint": "a" * 64,
                    "metadata_fingerprint": "b" * 64,
                },
            )
        return live.RecoveryGateOutcome(False, "source snapshot drifted")

    monkeypatch.setattr(live, "_supervision_recovery_gate", changing_recovery_gate)

    with pytest.raises(live.LiveSupervisorError, match="source snapshot drifted"):
        live.recover_live_host_lock(
            context.run_root,
            acknowledge_recovery=True,
        )

    assert calls == 2
    assert lock_path.exists()
    assert len(list((context.run_root / "recoveries").glob("*/recovery-intent.json"))) == 1
    lock.release()


def test_recovery_refuses_incomplete_global_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, lock, state = _retained_lock_fixture(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_owner_absent",
        ),
    )
    monkeypatch.setattr(
        live,
        "_strict_process_inventory",
        lambda: (_ for _ in ()).throw(
            live.LiveSupervisorError("HEC-RAS process inventory contains query errors")
        ),
    )

    with pytest.raises(live.LiveSupervisorError, match="query errors"):
        live.recover_live_host_lock(context.run_root, acknowledge_recovery=True)

    assert lock_path.exists()
    lock.release()


def test_recovery_refuses_lock_token_or_file_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, lock_path, lock, state = _retained_lock_fixture(tmp_path)
    monkeypatch.setattr(live, "load_run", lambda _: context)
    monkeypatch.setattr(live, "_bind_live_context", lambda _: None)
    monkeypatch.setattr(live, "_host_lock_path", lambda: lock_path)
    monkeypatch.setattr(
        live,
        "inspect_lock",
        lambda _: replace(
            state,
            owner_alive=False,
            reason_code="lock_owner_absent",
        ),
    )
    monkeypatch.setattr(live, "_strict_process_inventory", _empty_inventory)
    original_read = live._read_lock_payload
    calls = 0

    def changed_token(path: Path):
        nonlocal calls
        calls += 1
        payload, identity = original_read(path)
        if calls == 1:
            payload = {**payload, "token": "changed-after-inspection"}
        return payload, identity

    monkeypatch.setattr(live, "_read_lock_payload", changed_token)

    with pytest.raises(live.LiveSupervisorError, match="identity/token changed"):
        live.recover_live_host_lock(context.run_root, acknowledge_recovery=True)

    assert lock_path.exists()
    lock.release()


def test_public_cli_requires_explicit_real_ras_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        live,
        "execute_live_action",
        lambda *_args, **_kwargs: pytest.fail("CLI must reject before dispatch"),
    )
    with pytest.raises(SystemExit) as exc:
        main(["run", "--run-root", "unused"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as recovery_exc:
        main(["recover", "--run-root", "unused"])
    assert recovery_exc.value.code == 2
