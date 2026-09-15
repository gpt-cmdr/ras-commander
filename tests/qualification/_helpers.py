from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.qualification.execution_evidence.fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from scripts.qualification.execution_evidence.receipts import write_json_with_digest


HASH_A = "a" * 64
HASH_B = "b" * 64
GIT_HEAD = "c" * 40
STAMP = "2026-08-28T12:00:00+00:00"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_table_rows(
    *,
    run_id: str = "run-1",
    lane_id: str = "lane-a",
    attempt_id: str = "attempt-1",
) -> dict[str, list[dict]]:
    common = {
        "schema_version": 1,
        "run_id": run_id,
        "lane_id": lane_id,
        "attempt_id": attempt_id,
    }
    lanes = {
        **common,
        "manifest_sha256": HASH_A,
        "git_head": GIT_HEAD,
        "fixture_id": "fixture-a",
        "plan_type": "steady_1d",
        "plan_number": "01",
        "source_kind": "project_file",
        "source_project": "C:/source/Model.prj",
        "source_content_fingerprint_algorithm": (
            QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
        ),
        "source_content_fingerprint": HASH_B,
        "stage_project": "C:/stage/Model.prj",
        "execution_api": "ras_cmdr",
        "engine_id": "ras-7",
        "engine_version_requested": "7.0",
        "engine_executable": "C:/HEC-RAS/7.0/Ras.exe",
        "engine_executable_sha256": HASH_B,
        "controller_version": None,
        "controller_progid": None,
        "compute_mode": None,
        "expected_result_format": "hdf",
        "selected_result_format": "hdf",
        "initial_state": "neither",
        "expected_terminal_category": "passed",
        "terminal_category": "passed",
        "started_at": STAMP,
        "finished_at": "2026-08-28T12:00:01+00:00",
        "wall_seconds": 1.0,
        "worker_exit_code": 0,
        "process_success": True,
        "completion_verified": True,
        "mechanical_completion": True,
        "error_count": 0,
        "warning_count": 0,
        "conflicts": [],
        "final_hdf_exists": True,
        "final_legacy_exists": False,
        "source_immutable": True,
        "all_invariants_passed": True,
        "failure_reason_code": None,
        "detail": None,
    }
    artifacts = {
        **common,
        "snapshot_id": "snapshot-1",
        "phase": "post_evidence_inspection",
        "captured_at": STAMP,
        "root_kind": "stage",
        "root_path": "C:/stage",
        "relative_path": "Model.p01.hdf",
        "artifact_kind": "plan_result",
        "result_family": "hdf",
        "data_origin": "staged_execution_output",
        "exists": True,
        "is_file": True,
        "is_dir": False,
        "size_bytes": 10,
        "mtime_ns": 123,
        "volume_id": "1",
        "file_id": "2",
        "sha256": HASH_A,
        "stable_read": True,
        "fingerprint_algorithm": QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
        "content_fingerprint": HASH_A,
        "metadata_fingerprint": HASH_B,
        "reason_code": "stable_file_hashed",
        "detail": None,
    }
    observations = {
        **common,
        "evidence_id": "evidence-1",
        "observation_name": "mechanical_completion",
        "evidence_inspected_at": STAMP,
        "observation_inspected_at": STAMP,
        "declared_program_version": "7.00",
        "state": "available",
        "channel": "derived",
        "value_type": "bool",
        "value_bool": True,
        "value_int64": None,
        "value_float64": None,
        "value_string": None,
        "value_timestamp": None,
        "source_locator": None,
        "source_sha256": None,
        "observed_program_version": None,
        "reason_code": "derived_from_completion_sources",
        "detail": None,
        "conflicts": [],
    }
    events = {
        **common,
        "sequence": 1,
        "event_at": STAMP,
        "phase": "receipt",
        "event_name": "receipt_committed",
        "status": "passed",
        "severity": "info",
        "api": None,
        "reason_code": None,
        "detail": None,
        "relative_path": "receipt.json",
        "pid": 123,
        "payload_json": None,
    }
    invariants = {
        **common,
        "invariant_id": "R11",
        "name": "Source immutability",
        "evaluated_at": STAMP,
        "status": "pass",
        "expected": '"unchanged"',
        "observed": '"unchanged"',
        "reason_code": "source_immutable",
        "detail": None,
        "supporting_snapshot_ids": ["snapshot-1"],
        "supporting_evidence_ids": [],
    }
    return {
        "lanes": [lanes],
        "artifacts": [artifacts],
        "observations": [observations],
        "events": [events],
        "invariants": [invariants],
    }


def make_attempt(
    run_root: Path,
    *,
    run_id: str = "run-1",
    lane_id: str = "lane-a",
    attempt_id: str = "attempt-1",
    tables: dict[str, list[dict]] | None = None,
    terminal_category: str = "passed",
    worker_exit_code: int = 0,
    supervisor_synthesized: bool = False,
) -> Path:
    attempt = run_root / "attempts" / lane_id / attempt_id
    attempt.mkdir(parents=True)
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "lane_id": lane_id,
        "attempt_id": attempt_id,
        "manifest_sha256": HASH_A,
        "git_head": GIT_HEAD,
        "required_invariants": ["R11"],
        "lane": {
            "lane_id": lane_id,
            "required_invariants": ["R11"],
        },
    }
    request_sha = write_json_with_digest(attempt / "request.json", request)
    receipt = {
        **request,
        "request_sha256": request_sha,
        "receipt_committed_at": STAMP,
        "terminal_category": terminal_category,
        "worker_exit_code": worker_exit_code,
        "supervisor_synthesized": supervisor_synthesized,
        "referenced_artifacts": [],
        "tables": tables or valid_table_rows(
            run_id=run_id,
            lane_id=lane_id,
            attempt_id=attempt_id,
        ),
    }
    write_json_with_digest(attempt / "receipt.json", receipt)
    return attempt
