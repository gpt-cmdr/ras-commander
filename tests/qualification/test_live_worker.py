from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

import pandas as pd
import psutil
import pyarrow
import pytest

import ras_commander
from ras_commander.ExecutionArtifacts import (
    PlanExecutionCleanup,
    PlanResultArtifactPaths,
    ResultArtifactAmbiguityError,
)
from ras_commander.ExecutionEvidence import (
    EXECUTION_OBSERVATION_NAMES,
    EvidenceObservation,
    ExecutionEvidence,
)
from scripts.qualification.execution_evidence import live_worker, receipts
from scripts.qualification.execution_evidence.locks import ExclusiveQualificationLock
from scripts.qualification.execution_evidence.planning import file_sha256
from scripts.qualification.execution_evidence.receipts import (
    read_event_journal,
    read_json_with_digest,
    write_json_with_digest,
)
from scripts.qualification.execution_evidence.snapshots import snapshot_tree


HASH_A = "a" * 64
GIT_HEAD = "c" * 40
REQUIRED = ["R01", "R02", "R03", "R04", "R06", "R10", "R11", "R12"]


@dataclass(frozen=True)
class _PublicRecord:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class _FakeRasPrj:
    pass


def _launch_details(
    request: dict[str, Any],
    project: Path,
    *,
    launcher_pid: int = 2468,
    launcher_create_time: float = 12345.0,
) -> dict[str, Any]:
    executable = str(Path(request["engine"]["executable"]).resolve(strict=True))
    project = project.resolve(strict=True)
    plan_number = request["fixture"]["plan_number"]
    plan = project.with_suffix(f".p{plan_number}").resolve(strict=True)
    logical_argv = [executable, "-c", str(project), str(plan)]
    raw_command = (
        f'"{logical_argv[0]}" -c "{logical_argv[2]}" "{logical_argv[3]}"'
    )
    return {
        "plan_number": plan_number,
        "command": raw_command,
        "executable_path": executable,
        "executable_sha256": request["engine"]["executable_sha256"],
        "project_path": str(project),
        "plan_path": str(plan),
        "working_directory": str(project.parent),
        "launcher_pid": launcher_pid,
        "launcher_create_time": launcher_create_time,
        "max_runtime_seconds": request["timeout_seconds"],
    }


def _execution_cleanup_details(
    request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_root = Path(request["stage_root"])
    project = stage_root / Path(request["source_project"]).name
    plan_number = request["fixture"]["plan_number"]
    expected = request["engine"]["expected_result_format"]
    opposing_format = "legacy" if expected == "hdf" else "hdf"
    opposing = (
        project.with_suffix(f".O{plan_number}")
        if opposing_format == "legacy"
        else project.with_suffix(f".p{plan_number}.hdf")
    )
    sidecars = [
        project.with_suffix(f".p{plan_number}.comp_msgs.txt"),
        project.with_suffix(f".p{plan_number}.computeMsgs.txt"),
        project.with_suffix(f".bco{plan_number}"),
    ]
    preparation = {
        "plan_number": plan_number,
        "result_format": opposing_format,
        "include_message_sidecars": True,
        "removed_paths": [],
        "missing_paths": [str(opposing), *(str(path) for path in sidecars)],
    }
    finalization = {
        "plan_number": plan_number,
        "result_format": opposing_format,
        "include_message_sidecars": False,
        "removed_paths": [],
        "missing_paths": [str(opposing)],
    }
    return preparation, finalization


def _modern_execution_details(
    request: dict[str, Any],
    launch_details: dict[str, Any],
) -> dict[str, Any]:
    preparation, finalization = _execution_cleanup_details(request)
    return {
        "execution_api": "ras_cmdr",
        "calculation_attempted": True,
        "selected_result_format": "hdf",
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "artifact_finalization_failure": None,
        "engine_kind": "executable",
        "selected_executable_path": request["engine"]["executable"],
        "selected_executable_sha256": request["engine"]["executable_sha256"],
        "launcher_pid": launch_details["launcher_pid"],
        "launcher_create_time": launch_details["launcher_create_time"],
        "launcher_returncode": 0,
        "actual_engine_provenance_confirmed": True,
        "compute_mode": "subprocess",
        "max_runtime_seconds": request["timeout_seconds"],
        "launch_details": launch_details,
        "runtime_timed_out": False,
        "failure_stage": None,
        "failure_type": None,
        "failure_detail": None,
        "cancellation_details": None,
        "artifact_preparation_cleanup": preparation,
        "artifact_finalization_cleanup": finalization,
    }


def _controller_execution_details(
    request: dict[str, Any],
    *,
    controller_executable_path: str | None = None,
) -> dict[str, Any]:
    preparation, finalization = _execution_cleanup_details(request)
    engine = request["engine"]
    legacy_controller = engine["resolved_controller_version"] in {"4.0", "4.1"}
    return {
        "execution_api": "ras_control",
        "calculation_attempted": True,
        "selected_result_format": engine["expected_result_format"],
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "artifact_preparation_cleanup": preparation,
        "artifact_finalization_cleanup": finalization,
        "engine_kind": "controller",
        "requested_controller_version": engine["controller_version"],
        "controller_progid": engine["controller_progid"],
        "resolved_controller_version": engine["resolved_controller_version"],
        "controller_executable_path": (
            controller_executable_path or engine["controller_executable"]
        ),
        "controller_executable_sha256": engine["controller_executable_sha256"],
        "controller_pid": 2468,
        "controller_create_time": 12345.0,
        "compute_mode": "blocking" if engine["blocking"] else "poll",
        "completion_method": (
            "Compute_IsStillComputing"
            if legacy_controller
            else (
                "Compute_CurrentPlan_blocking_return"
                if engine["blocking"]
                else "Compute_Complete"
            )
        ),
        "controller_quit_supported": not legacy_controller,
        "controller_close_method": (
            "owned_process_cleanup" if legacy_controller else "quit_ras"
        ),
        "watchdog_requested": True,
        "watchdog_started": True,
        "strict_close_requested": True,
        "max_runtime_seconds": request["timeout_seconds"],
        "controller_close_safe": True,
        "owned_process_exit_confirmed": True,
        "post_close_plan_processes_quiescent": True,
        "post_close_global_processes_quiescent": True,
        "actual_engine_provenance_confirmed": True,
    }


def _configure_modern_controller_request(
    request: dict[str, Any],
    *,
    blocking: bool,
) -> None:
    request["engine"].update(
        version_requested="5.0.7",
        expected_result_format="hdf",
        controller_version="5.0.7",
        resolved_controller_version="5.0.7",
        controller_progid="RAS507.HECRASController",
        blocking=blocking,
    )


def _safe_timeout_execution_details(
    request: dict[str, Any],
    launch_details: dict[str, Any],
) -> dict[str, Any]:
    details = _modern_execution_details(request, launch_details)
    process_record = {
        "pid": launch_details["launcher_pid"],
        "create_time": launch_details["launcher_create_time"],
        "name": "Ras.exe",
        "executable_path": launch_details["executable_path"],
        "command_line": [launch_details["command"]],
        "working_directory": launch_details["working_directory"],
        "tracked": True,
        "session_id": None,
    }
    project = Path(launch_details["project_path"])
    plan_number = request["fixture"]["plan_number"]
    details.update(
        launcher_returncode=None,
        runtime_timed_out=True,
        failure_stage="subprocess_wait",
        failure_type="TimeoutError",
        failure_detail="maximum runtime expired",
        cancellation_details={
            "plan_number": plan_number,
            "project_path": launch_details["project_path"],
            "plan_path": launch_details["plan_path"],
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
    return details


def _safe_finalization_failure_execution_details(
    request: dict[str, Any],
    launch_details: dict[str, Any],
) -> dict[str, Any]:
    details = _safe_timeout_execution_details(request, launch_details)
    cancellation = details["cancellation_details"]
    cancellation.update(
        cancellation_attempted=False,
        matched=[],
        stopped=[],
    )
    details.update(
        launcher_returncode=0,
        runtime_timed_out=False,
        failure_stage="result_artifact_finalization",
        failure_type="OSError",
        failure_detail="result inventory refresh failed",
        result_artifacts_finalized=False,
        artifact_finalization_cleanup=None,
        artifact_finalization_failure={
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "result inventory refresh failed",
        },
    )
    return details


def _project(root: Path) -> Path:
    root.mkdir()
    project = root / "Model.prj"
    project.write_text(
        "Proj Title=Live Qualification\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        "Plan Title=Base\n"
        "Program Version=7.00\n"
        "Short Identifier=Base\n"
        "Simulation Date=01JAN2020,0000,02JAN2020,2400\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.g01").write_text("Geom Title=Geometry\n", encoding="ascii")
    (root / "Model.f01").write_text("Flow Title=Flow\n", encoding="ascii")
    return project


def _request(
    tmp_path: Path,
    *,
    execution_api: str = "ras_cmdr",
) -> tuple[dict[str, Any], Any, Path]:
    run_root = tmp_path / "archive" / "run-1"
    attempt_dir = run_root / "attempts" / "lane-1" / "attempt-1"
    attempt_dir.mkdir(parents=True)
    execution_root = tmp_path / "execution" / "run-1"
    (execution_root / "lane-1" / "attempt-1").mkdir(parents=True)
    source_project = _project(tmp_path / "source")
    source_snapshot = snapshot_tree(
        source_project.parent,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="request_source",
        root_kind="source",
        data_origin="captured_real",
        known_paths=("Model.p01.hdf", "Model.O01"),
    )
    engine_file = tmp_path / "engine" / "Ras.exe"
    engine_file.parent.mkdir()
    engine_file.write_bytes(b"never executed by this test")
    if execution_api == "ras_cmdr":
        engine = {
            "engine_id": "ras-7",
            "execution_api": "ras_cmdr",
            "version_requested": "7.0",
            "expected_result_format": "hdf",
            "support_state": "supported",
            "executable": str(engine_file),
            "executable_sha256": file_sha256(engine_file),
        }
    else:
        engine = {
            "engine_id": "ras-4",
            "execution_api": "ras_control",
            "version_requested": "4.1.0",
            "expected_result_format": "legacy",
            "support_state": "supported",
            "controller_version": "4.1.0",
            "resolved_controller_version": "4.1",
            "controller_progid": "RAS41.HECRASController",
            "controller_executable": str(engine_file),
            "controller_executable_sha256": file_sha256(engine_file),
            "blocking": False,
        }
    fixture = {
        "fixture_id": "fixture-1",
        "source_kind": "project_file",
        "source_project": str(source_project),
        "source_immutable": True,
        "source_content_fingerprint_algorithm": (
            source_snapshot.fingerprint_algorithm
        ),
        "source_content_fingerprint": source_snapshot.content_fingerprint,
        "data_origin": "captured_real",
        "plan_number": "01",
        "plan_title": "Base",
        "plan_type": "steady_1d",
    }
    lane = {
        "lane_id": "lane-1",
        "fixture_id": "fixture-1",
        "engine_id": engine["engine_id"],
        "initial_state": "neither",
        "expected_terminal_category": "passed",
        "required_invariants": REQUIRED,
        "tags": ["real_ras"],
    }
    context = SimpleNamespace(
        run_root=run_root,
        descriptor={"execution_run_root": str(execution_root)},
    )
    lock = ExclusiveQualificationLock(
        tmp_path / "real-engine.lock",
        kind="real_engine",
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        git_head=GIT_HEAD,
    )
    lock_payload = lock.acquire()
    request = {
        "schema_version": 1,
        "action": "run",
        "run_id": "run-1",
        "lane_id": "lane-1",
        "attempt_id": "attempt-1",
        "manifest_sha256": HASH_A,
        "git_head": GIT_HEAD,
        "repository_root": str(Path(__file__).resolve().parents[2]),
        "python_executable": str(Path(__import__("sys").executable).resolve()),
        "python_executable_sha256": file_sha256(__import__("sys").executable),
        "python_version": platform.python_version(),
        "pyarrow_version": pyarrow.__version__,
        "psutil_version": psutil.__version__,
        "ras_commander_version": str(ras_commander.__version__),
        "ras_commander_import_path": str(Path(ras_commander.__file__).resolve()),
        "run_descriptor_sha256": "b" * 64,
        "normalized_manifest_path": str(run_root / "manifest.normalized.json"),
        "normalized_manifest_sha256": "d" * 64,
        "lane": lane,
        "fixture": fixture,
        "engine": engine,
        "required_invariants": REQUIRED,
        "source_project": str(source_project),
        "source_snapshot_content_fingerprint_algorithm": (
            source_snapshot.fingerprint_algorithm
        ),
        "source_snapshot_content_fingerprint": source_snapshot.content_fingerprint,
        "source_snapshot_metadata_fingerprint": source_snapshot.metadata_fingerprint,
        "stage_root": str(execution_root / "lane-1" / "attempt-1" / "stage"),
        "preflight_timeout_seconds": 1800,
        "timeout_seconds": 30,
        "termination_grace_seconds": 0.01,
        "postflight_timeout_seconds": 1800,
        "supervisor_receipt_margin_seconds": 5.0,
        "hash_files": True,
        "process_baseline": [],
        "process_baseline_evidence": {
            "observed_at": 1.0,
            "complete": True,
            "processes": [],
            "query_errors": [],
        },
        "real_engine_lock": {
            "path": str(lock.path),
            "token": lock_payload["token"],
            "run_id": "run-1",
            "lane_id": "lane-1",
            "attempt_id": "attempt-1",
        },
        "worker_launch": {
            "launch_nonce": str(uuid.uuid4()),
            "intent_path": str(attempt_dir / "worker-launch-intent.json"),
            "binding_path": str(attempt_dir / "worker-launcher.json"),
            "hello_path": str(attempt_dir / "worker-hello.json"),
            "authorization_path": str(
                attempt_dir / "worker-authorization.json"
            ),
        },
        "hec_ras_execution_enabled": True,
    }
    return request, context, lock


def _plan_18_snapshot(root: Path, *, selected_result: str | None = None):
    root.mkdir()
    project = root / "Model.prj"
    project.write_text("Proj Title=Plan 18 scope\n", encoding="ascii")
    (root / "Model.p06.hdf").write_bytes(b"other plan hdf")
    (root / "Model.IC.O06").write_bytes(b"other plan initial condition")
    if selected_result is not None:
        (root / selected_result).write_bytes(b"selected plan result")
    snapshot = snapshot_tree(
        root,
        run_id="run-1",
        lane_id="plan-18",
        attempt_id="attempt-1",
        phase="selected_plan_scope",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=("Model.p18.hdf", "Model.O18"),
    )
    return project, snapshot


def test_live_initial_state_ignores_other_plan_and_ic_result_artifacts(
    tmp_path: Path,
) -> None:
    project, snapshot = _plan_18_snapshot(tmp_path / "stage")
    assert live_worker.result_population(snapshot.rows) == (True, True)
    assert live_worker.result_population(
        snapshot.rows,
        project_file=project,
        plan_number="18",
    ) == (False, False)

    request = {
        "source_project": str(project),
        "fixture": {"plan_number": "18"},
        "engine": {"expected_result_format": "hdf"},
        "lane": {"initial_state": "neither"},
    }
    live_worker._validate_pre_execution_state(
        request,
        stage_published=snapshot,
        pre_execution=snapshot,
    )


@pytest.mark.parametrize(
    ("selected_result", "expected_population"),
    [
        ("Model.p18.hdf", (True, False)),
        ("Model.O18", (False, True)),
    ],
)
def test_live_result_population_detects_only_exact_selected_plan_artifacts(
    tmp_path: Path,
    selected_result: str,
    expected_population: tuple[bool, bool],
) -> None:
    project, snapshot = _plan_18_snapshot(
        tmp_path / selected_result.replace(".", "_"),
        selected_result=selected_result,
    )
    assert live_worker.result_population(
        snapshot.rows,
        project_file=project,
        plan_number="18",
    ) == expected_population


def test_post_execution_origins_mark_new_and_modified_files_as_generated(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    plan = stage_root / "Model.p01"
    plan.write_bytes(b"captured plan")
    geometry = stage_root / "Model.g01"
    geometry.write_bytes(b"captured geometry")
    known_paths = ("Model.p01.hdf", "Model.O01")
    request = {"fixture": {}}
    before = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="pre_execution",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
    )

    generated = stage_root / "Model.P01.hdf"
    generated.write_bytes(b"generated by HEC-RAS")
    (stage_root / "Model.g01.hdf").write_bytes(b"generated geometry HDF")
    (stage_root / "_compute_p01.log").write_bytes(b"")
    plan.write_bytes(b"captured plan\ngenerated setting")
    after = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="post_evidence_inspection",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
    )

    origins = live_worker._post_execution_origins(
        request,
        before=before,
        after=after,
        known_paths=known_paths,
    )
    snapshot = live_worker._with_origin_overrides(
        after,
        origins,
    )

    rows = {row["relative_path"].casefold(): row for row in snapshot.rows}
    assert rows["model.p01.hdf"]["relative_path"] == "Model.P01.hdf"
    assert rows["model.p01.hdf"]["data_origin"] == "staged_execution_output"
    assert rows["model.g01.hdf"]["data_origin"] == "staged_execution_output"
    assert rows["_compute_p01.log"]["data_origin"] == "staged_execution_output"
    assert rows["model.p01"]["data_origin"] == "staged_execution_output"
    assert rows["model.g01"]["data_origin"] == "captured_real"
    assert rows["model.o01"]["exists"] is False
    assert rows["model.o01"]["data_origin"] == "captured_real"


def test_post_execution_origin_preserves_case_insensitive_pinned_replay_path(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    replayed = stage_root / "Model.P01.hdf"
    replayed.write_bytes(b"pinned captured replay")
    info = replayed.stat()
    known_paths = ("Model.p01.hdf", "Model.O01")
    request = {
        "fixture": {
            "replay_artifacts": {
                "data_origin": "generated_edge_case",
                "files": [
                    {
                        "relative_path": "Model.p01.hdf",
                        "sha256": file_sha256(replayed),
                        "size_bytes": info.st_size,
                        "mtime_ns": info.st_mtime_ns,
                    }
                ],
            }
        }
    }
    before = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="pre_execution",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
        origin_overrides={"model.p01.hdf": "generated_edge_case"},
    )
    after = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="post_evidence_inspection",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
    )

    origins = live_worker._post_execution_origins(
        request,
        before=before,
        after=after,
        known_paths=known_paths,
    )
    snapshot = live_worker._with_origin_overrides(
        after,
        origins,
    )

    result = next(
        row
        for row in snapshot.rows
        if row["relative_path"].casefold() == "model.p01.hdf"
    )
    assert result["relative_path"] == "Model.P01.hdf"
    assert result["exists"] is True
    assert result["data_origin"] == "generated_edge_case"


@pytest.mark.parametrize("mutation", ["modified", "removed"])
def test_post_execution_origin_rejects_changed_or_removed_replay_pin(
    tmp_path: Path,
    mutation: str,
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    replayed = stage_root / "Model.P01.hdf"
    replayed.write_bytes(b"pinned captured replay")
    info = replayed.stat()
    known_paths = ("Model.p01.hdf", "Model.O01")
    request = {
        "fixture": {
            "replay_artifacts": {
                "data_origin": "generated_edge_case",
                "files": [
                    {
                        "relative_path": "Model.p01.hdf",
                        "sha256": file_sha256(replayed),
                        "size_bytes": info.st_size,
                        "mtime_ns": info.st_mtime_ns,
                    }
                ],
            }
        }
    }
    before = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="pre_execution",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
        origin_overrides={"model.p01.hdf": "generated_edge_case"},
    )
    if mutation == "modified":
        replayed.write_bytes(b"new execution output")
    else:
        replayed.unlink()
    after = snapshot_tree(
        stage_root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="post_evidence_inspection",
        root_kind="stage",
        data_origin="captured_real",
        known_paths=known_paths,
    )

    snapshot = live_worker._with_origin_overrides(
        after,
        live_worker._post_execution_origins(
            request,
            before=before,
            after=after,
            known_paths=known_paths,
        ),
    )

    result = next(
        row
        for row in snapshot.rows
        if row["relative_path"].casefold() == "model.p01.hdf"
    )
    assert result["exists"] is (mutation == "modified")
    assert result["data_origin"] == "staged_execution_output"


def _inventory(*, plan: bool, project: Path | None = None) -> _PublicRecord:
    payload: dict[str, Any] = {
        "observed_at": 1.0,
        "complete": True,
        "query_errors": [],
    }
    if plan:
        assert project is not None
        payload.update(
            {
                "plan_number": "01",
                "project_path": str(project),
                "plan_path": str(project.parent / "Model.p01"),
                "tmp_hdf_path": None,
                "matched": [],
            }
        )
    else:
        payload["processes"] = []
    return _PublicRecord(payload)


def _observation(
    *,
    channel: str,
    value: Any = None,
    locator: str | None = None,
    reason: str = "not_available_in_test_fixture",
) -> EvidenceObservation[Any]:
    now = datetime.now(timezone.utc)
    if value is None:
        return EvidenceObservation(
            state="not_available_in_version",
            value=None,
            channel=channel,
            source_locator=locator,
            source_sha256=None,
            observed_program_version=None,
            inspected_at=now,
            reason_code=reason,
        )
    return EvidenceObservation(
        state="available",
        value=value,
        channel=channel,
        source_locator=locator,
        source_sha256=None,
        observed_program_version=None,
        inspected_at=now,
    )


def _evidence(project: Path, *, result_format: str) -> ExecutionEvidence:
    now = datetime.now(timezone.utc)
    result = (
        project.parent / "Model.p01.hdf"
        if result_format == "hdf"
        else project.parent / "Model.O01"
    )
    message_channel = "hdf" if result_format == "hdf" else "stored_message"
    structural_channel = "hdf" if result_format == "hdf" else "legacy_output"
    channels = {
        "result_artifact_exists": "filesystem",
        "result_artifact_modified_at": "filesystem",
        "result_artifact_modified_after_threshold": "filesystem",
        "result_artifact_structural_state": structural_channel,
        "producer_program_version": message_channel,
        "completion_attribute": "hdf",
        "completion_message_hdf": "hdf",
        "completion_message_stored": "stored_message",
        "message_error_count": message_channel,
        "message_warning_count": message_channel,
        "message_first_error": message_channel,
        "runtime_seconds": message_channel,
        "simulation_start": "filesystem",
        "simulation_end": "filesystem",
        "process_success": "process",
        "com_completion": "com",
    }
    values: dict[str, Any] = {
        "result_artifact_exists": True,
        "result_artifact_modified_at": now,
        "result_artifact_modified_after_threshold": True,
        "result_artifact_structural_state": "readable",
        "producer_program_version": "7.0" if result_format == "hdf" else "4.1",
        "message_error_count": 0,
        "message_warning_count": 0,
        "runtime_seconds": 1.0,
        "simulation_start": datetime(2020, 1, 1),
        "simulation_end": datetime(2020, 1, 3),
        "process_success": True,
    }
    if result_format == "hdf":
        values["completion_attribute"] = True
        values["completion_message_hdf"] = True
    else:
        values["completion_message_stored"] = True
        values["com_completion"] = True
    observations = {
        name: _observation(
            channel=channels[name],
            value=values.get(name),
            locator=str(result) if name == "result_artifact_exists" else None,
        )
        for name in EXECUTION_OBSERVATION_NAMES
    }
    mechanical = _observation(channel="derived", value=True)
    return ExecutionEvidence(
        schema_version=1,
        evidence_id="evidence-1",
        inspected_at=now,
        project_file=project,
        plan_file=project.parent / "Model.p01",
        plan_number="01",
        declared_program_version="7.00" if result_format == "hdf" else "4.10",
        mechanical_completion=mechanical,
        observations=observations,
        conflicts=(),
    )


def _install_public_api_fakes(
    monkeypatch: pytest.MonkeyPatch,
    request: dict[str, Any],
    *,
    invalid_details: bool = False,
) -> dict[str, Any]:
    calls: dict[str, Any] = {
        "compute": [],
        "control": [],
        "cleanup": [],
        "inspection": 0,
        "global_inventory": 0,
        "plan_inventory": 0,
        "tcu_status": [],
        "launch_event_before_wait": False,
    }

    def tcu_status(*, ras_version: str) -> Any:
        calls["tcu_status"].append(ras_version)
        executable = request["engine"].get("executable") or request["engine"].get(
            "controller_executable"
        )
        install_dir = (
            str(Path(executable).parent)
            if executable
            else None
        )
        return SimpleNamespace(
            accepted=True,
            version=ras_version,
            install_dir=install_dir,
            registry_key=f"test-registry/{install_dir}",
            reason="accepted",
        )

    def forbidden_tcu_mutation(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the live worker must never mutate TCU acceptance")

    def fake_init(project_file: str | Path, **kwargs: Any) -> Any:
        project = Path(project_file)
        assert isinstance(kwargs["ras_object"], _FakeRasPrj)
        assert kwargs["load_results_summary"] is False
        assert kwargs["load_hdf_metadata"] is False
        assert kwargs["hide_intro"] is True
        return SimpleNamespace(
            prj_file=project,
            project_folder=project.parent,
            project_name=project.stem,
            ras_version=request["engine"]["version_requested"],
            ras_exe_path=request["engine"].get("executable"),
        )

    def inspect_global() -> _PublicRecord:
        calls["global_inventory"] += 1
        return _inventory(plan=False)

    def inspect_plan(plan_number: str, *, ras_object: Any) -> _PublicRecord:
        calls["plan_inventory"] += 1
        assert plan_number == "01"
        return _inventory(plan=True, project=ras_object.prj_file)

    def cleanup(plan_number: str, **kwargs: Any) -> PlanExecutionCleanup:
        calls["cleanup"].append((plan_number, kwargs))
        root = kwargs["ras_object"].project_folder
        requested = kwargs["result_format"]
        candidates = []
        if requested in {"hdf", "both"}:
            candidates.append(root / "Model.p01.hdf")
        if requested in {"legacy", "both"}:
            candidates.append(root / "Model.O01")
        if kwargs["include_message_sidecars"]:
            candidates.extend(
                [
                    root / "Model.p01.comp_msgs.txt",
                    root / "Model.p01.computeMsgs.txt",
                    root / "Model.bco01",
                ]
            )
        return PlanExecutionCleanup(
            plan_number="01",
            result_format=requested,
            include_message_sidecars=kwargs["include_message_sidecars"],
            removed_paths=(),
            missing_paths=tuple(candidates),
        )

    def inspect_evidence(plan_number: str, *, ras_object: Any, hash_files: bool) -> Any:
        calls["inspection"] += 1
        assert plan_number == "01"
        assert hash_files is True
        return _evidence(
            ras_object.prj_file,
            result_format=request["engine"]["expected_result_format"],
        )

    def compute(plan_number: str, **kwargs: Any) -> Any:
        calls["compute"].append((plan_number, kwargs))
        project = kwargs["ras_object"].prj_file
        launch = _launch_details(request, project)
        kwargs["stream_callback"].on_exec_launched(plan_number, launch)
        attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
        persisted = read_event_journal(attempt_dir / "events.jsonl")[-1]
        calls["launch_event_before_wait"] = (
            persisted["event_name"] == "engine_process_launched"
            and persisted["pid"] == launch["launcher_pid"]
        )
        (project.parent / "Model.p01.hdf").write_bytes(b"fake modern result")
        transient_legacy = project.parent / "Model.O01"
        transient_legacy.write_bytes(b"transient legacy result")
        transient_legacy.unlink()
        details = _modern_execution_details(request, launch)
        details["artifact_finalization_cleanup"].update(
            removed_paths=[str(transient_legacy)],
            missing_paths=[],
        )
        if invalid_details:
            details.pop("solver_quiescence_confirmed")
        return SimpleNamespace(
            success=True,
            completion_verified=True,
            execution_details=details,
        )

    def run_control(plan_number: str, **kwargs: Any) -> Any:
        calls["control"].append((plan_number, kwargs))
        project = kwargs["ras_object"].prj_file
        (project.parent / "Model.O01").write_bytes(b"fake legacy result")
        return SimpleNamespace(
            success=True,
            messages=["Complete Process", "No errors"],
            execution_details=_controller_execution_details(request),
        )

    monkeypatch.setattr(ras_commander, "RasPrj", _FakeRasPrj)
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "status",
        staticmethod(tcu_status),
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "accept",
        staticmethod(forbidden_tcu_mutation),
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "open_gui",
        staticmethod(forbidden_tcu_mutation),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "open_gui_to_accept",
        staticmethod(forbidden_tcu_mutation),
    )
    monkeypatch.setattr(ras_commander, "init_ras_project", fake_init)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        staticmethod(inspect_global),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_plan_processes",
        staticmethod(inspect_plan),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "cancel_plan_exact",
        staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("not called"))),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "remove_plan_execution_artifacts",
        staticmethod(cleanup),
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_execution_evidence",
        staticmethod(inspect_evidence),
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "compute_plan",
        staticmethod(compute),
    )
    monkeypatch.setattr(
        ras_commander.RasControl,
        "run_plan",
        staticmethod(run_control),
    )
    return calls


def test_modern_live_attempt_uses_only_public_apis_and_publishes_worker_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 0
    assert calls["compute"]
    assert calls["control"] == []
    _, kwargs = calls["compute"][0]
    assert kwargs["ras_object"] is not None
    assert kwargs["force_rerun"] is True
    assert kwargs["skip_existing"] is False
    assert kwargs["verify"] is True
    assert kwargs["dialog_watchdog"] is True
    assert kwargs["max_runtime"] == request["timeout_seconds"]
    assert isinstance(kwargs["stream_callback"], live_worker._LiveLaunchRecorder)
    assert calls["launch_event_before_wait"] is True
    assert calls["global_inventory"] == 3
    assert calls["plan_inventory"] == 2
    assert calls["cleanup"][0][1]["result_format"] == "both"
    assert calls["tcu_status"] == [request["engine"]["executable"]]
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert not (attempt / "receipt.json").exists()
    assert receipt["hec_ras_invoked"] is True
    assert receipt["terminal_category"] == "passed"
    assert receipt["worker_exit_code"] == 0
    assert {row["invariant_id"] for row in receipt["tables"]["invariants"]} == set(
        REQUIRED
    )
    assert all(row["status"] == "pass" for row in receipt["tables"]["invariants"])
    r04 = next(
        row
        for row in receipt["tables"]["invariants"]
        if row["invariant_id"] == "R04"
    )
    assert json.loads(r04["observed"]) == ["Model.O01"]
    assert all(
        item["relative_path"] not in {"stdout.log", "stderr.log"}
        for item in receipt["referenced_artifacts"]
    )
    assert receipt["tcu_status"] == {
        "accepted": True,
        "install_dir": str(Path(request["engine"]["executable"]).parent),
        "ras_version_argument": request["engine"]["executable"],
        "reason": "accepted",
        "registry_key": (
            "test-registry/" + str(Path(request["engine"]["executable"]).parent)
        ),
        "version": request["engine"]["executable"],
    }
    tcu_events = [
        row
        for row in receipt["tables"]["events"]
        if row["event_name"] == "tcu_acceptance_preflight_passed"
    ]
    assert len(tcu_events) == 1
    assert json.loads(tcu_events[0]["payload_json"])["tcu_status"]["accepted"] is True
    launch_events = [
        row
        for row in receipt["tables"]["events"]
        if row["event_name"] == "engine_process_launched"
    ]
    assert len(launch_events) == 1
    launch_payload = json.loads(launch_events[0]["payload_json"])
    assert launch_payload["raw_command"] == receipt["execution_result"][
        "execution_details"
    ]["launch_details"]["command"]
    assert launch_payload["logical_argv"][0] == request["engine"]["executable"]
    assert launch_payload["launch_method"] == (
        "direct_subprocess_shell_false_exact_executable"
    )
    assert launch_payload["max_runtime_seconds"] == request["timeout_seconds"]
    final_hdf = [
        row
        for row in receipt["tables"]["artifacts"]
        if row["phase"] == "post_evidence_inspection"
        and row["relative_path"] == "Model.p01.hdf"
    ][0]
    assert final_hdf["data_origin"] == "staged_execution_output"


def test_modern_launch_callback_fsyncs_event_before_fake_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    journal = receipts.EventJournal(
        attempt_dir / "events.jsonl",
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
    )
    recorder = live_worker._LiveLaunchRecorder(
        events=journal,
        request=request,
        stage_project=Path(request["source_project"]),
    )
    fsync_calls: list[int] = []
    monkeypatch.setattr(receipts.os, "fsync", fsync_calls.append)
    try:
        recorder.on_exec_launched(
            request["fixture"]["plan_number"],
            _launch_details(request, Path(request["source_project"])),
        )

        def fake_wait() -> None:
            assert fsync_calls
            persisted = read_event_journal(journal.path)
            assert persisted[-1]["event_name"] == "engine_process_launched"

        fake_wait()
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("command", "Ras.exe -c forged"),
        ("executable_sha256", "0" * 64),
        ("launcher_pid", 0),
        ("max_runtime_seconds", 31),
    ],
)
def test_modern_launch_callback_rejects_unproved_identity_before_event(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    journal = receipts.EventJournal(
        attempt_dir / "events.jsonl",
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
    )
    recorder = live_worker._LiveLaunchRecorder(
        events=journal,
        request=request,
        stage_project=Path(request["source_project"]),
    )
    launch = _launch_details(request, Path(request["source_project"]))
    launch[field] = invalid_value
    try:
        with pytest.raises(live_worker.LiveCapabilityError):
            recorder.on_exec_launched(request["fixture"]["plan_number"], launch)
    finally:
        lock.release()

    assert not journal.path.exists()


@pytest.mark.parametrize("asset_kind", ["dss_file", "gridded_dataset", "terrain"])
def test_required_external_linked_asset_stops_before_cleanup_or_compute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    asset_kind: str,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    public_stage_project = ras_commander.stage_project

    def stage_with_external_asset(*args: Any, **kwargs: Any) -> Any:
        result = public_stage_project(*args, **kwargs)
        assets = result.assets.copy()
        row_index = assets.index[assets["required"].eq(True)][0]  # noqa: E712
        external_path = tmp_path / "external-library" / f"{asset_kind}.dat"
        assets.loc[row_index, "asset_kind"] = asset_kind
        assets.loc[row_index, "reference_raw"] = str(external_path)
        assets.loc[row_index, "resolved_path"] = str(external_path)
        assets.loc[row_index, "path_scope"] = "external"
        assets.loc[row_index, "portable"] = False
        assert str(assets["required"].dtype) == "bool[pyarrow]"
        assert str(assets["path_scope"].dtype) == "string[pyarrow]"
        return replace(result, assets=assets)

    monkeypatch.setattr(ras_commander, "stage_project", stage_with_external_asset)
    try:
        with pytest.raises(
            live_worker.LiveAssetGateError,
            match="external_execution_asset",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert calls["inspection"] == 0
    events_path = (
        context.run_root
        / "attempts"
        / "lane-1"
        / "attempt-1"
        / "events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    rejection = [
        event
        for event in events
        if event["event_name"] == "stage_asset_gate_rejected"
    ]
    assert len(rejection) == 1
    assert rejection[0]["reason_code"] == "external_execution_asset"
    assert rejection[0]["severity"] == "error"
    payload = json.loads(rejection[0]["payload_json"])
    assert payload["findings"][0]["asset_kind"] == asset_kind


def test_internal_pyarrow_asset_inventory_passes_live_gate(tmp_path: Path) -> None:
    source_project = _project(tmp_path / "source")
    staged = ras_commander.stage_project(source_project, tmp_path / "stage")

    result = live_worker._require_live_stage_assets_safe(
        staged.assets,
        stage_root=staged.destination_root,
    )

    assert result["asset_count"] == len(staged.assets)
    assert result["required_asset_count"] == 4
    assert result["external_execution_asset_count"] == 0
    assert all(
        isinstance(staged.assets[column].dtype, pd.ArrowDtype)
        for column in live_worker._LIVE_ASSET_GATE_COLUMNS
    )


def test_non_pyarrow_stage_asset_gate_dtype_stops_before_compute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    public_stage_project = ras_commander.stage_project

    def stage_with_object_dtype(*args: Any, **kwargs: Any) -> Any:
        result = public_stage_project(*args, **kwargs)
        assets = result.assets.copy()
        assets["path_scope"] = assets["path_scope"].astype("object")
        return replace(result, assets=assets)

    monkeypatch.setattr(ras_commander, "stage_project", stage_with_object_dtype)
    try:
        with pytest.raises(live_worker.LiveCapabilityError, match="PyArrow-backed"):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []


def test_controller_live_attempt_uses_exact_controller_route_and_externalizes_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path, execution_api="ras_control")
    calls = _install_public_api_fakes(monkeypatch, request)
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 0
    assert calls["compute"] == []
    assert len(calls["control"]) == 1
    _, kwargs = calls["control"][0]
    assert kwargs["force_recompute"] is True
    assert kwargs["use_watchdog"] is True
    assert kwargs["max_runtime"] == 30
    assert kwargs["refresh_results"] is False
    assert kwargs["blocking"] is False
    assert kwargs["controller_version"] == "4.1.0"
    assert kwargs["strict_close"] is True
    assert calls["tcu_status"] == ["4.1.0"]
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert (attempt / "messages.txt").read_text(encoding="utf-8").find(
        "Complete Process"
    ) >= 0
    assert "Complete Process" not in json.dumps(receipt)
    assert receipt["execution_result"]["message_count"] == 2
    assert receipt["tables"]["lanes"][0]["controller_progid"] == (
        "RAS41.HECRASController"
    )


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        (False, "no-vb6-subtree"),
        (None, "version-unresolved"),
    ],
)
def test_tcu_acceptance_not_confirmed_stops_before_staging_or_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool | None,
    reason: str,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    stage_called = False

    def status(*, ras_version: str) -> Any:
        calls["tcu_status"].append(ras_version)
        return SimpleNamespace(
            accepted=accepted,
            version=ras_version,
            install_dir=str(Path(request["engine"]["executable"]).parent),
            registry_key="test-registry/tcu",
            reason=reason,
        )

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander.RasTcu, "status", staticmethod(status))
    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    try:
        with pytest.raises(
            live_worker.LiveTcuGateError,
            match="TCU acceptance was not confirmed",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["tcu_status"] == [request["engine"]["executable"]]
    assert stage_called is False
    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert not Path(request["stage_root"]).exists()
    events_path = (
        context.run_root
        / "attempts"
        / "lane-1"
        / "attempt-1"
        / "events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    rejected = [
        event
        for event in events
        if event["event_name"] == "tcu_acceptance_preflight_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "tcu_acceptance_not_confirmed"
    payload = json.loads(rejected[0]["payload_json"])["tcu_status"]
    assert payload["accepted"] is accepted
    assert payload["reason"] == reason
    assert payload["ras_version_argument"] == request["engine"]["executable"]


def test_qualification_manifest_pin_mismatch_stops_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    request["fixture"]["source_content_fingerprint"] = "0" * 64
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="qualification source fingerprint gate failed before staging",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert not Path(request["stage_root"]).exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("execution_api", "ras_cmdr"),
        ("calculation_attempted", 1),
        ("solver_quiescence_confirmed", 1),
        ("actual_engine_provenance_confirmed", False),
        ("requested_controller_version", "4.0"),
        ("compute_mode", "blocking"),
        ("watchdog_requested", False),
        ("watchdog_requested", 1),
        ("watchdog_started", False),
        ("watchdog_started", 1),
        ("strict_close_requested", False),
        ("strict_close_requested", 1),
        ("max_runtime_seconds", 31),
        ("controller_executable_sha256", "0" * 64),
        ("controller_pid", None),
        ("controller_create_time", 0),
        ("completion_method", "Compute_Complete"),
        ("controller_quit_supported", True),
        ("controller_quit_supported", 0),
        ("controller_close_method", "QuitRas"),
        ("controller_close_safe", 1),
        ("owned_process_exit_confirmed", 1),
        ("post_close_plan_processes_quiescent", False),
        ("post_close_plan_processes_quiescent", 1),
        ("post_close_global_processes_quiescent", False),
        ("post_close_global_processes_quiescent", 1),
    ],
)
def test_controller_live_result_requires_exact_execution_contract(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    details = _controller_execution_details(request)
    details[field] = invalid_value
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(live_worker.LiveWorkerError):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("completion_method", "Compute_IsStillComputing"),
        ("controller_quit_supported", False),
        ("controller_quit_supported", 1),
        ("controller_close_method", "owned_process_cleanup"),
    ],
)
def test_modern_controller_live_result_requires_exact_capability_evidence(
    tmp_path: Path,
    blocking: bool,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    _configure_modern_controller_request(request, blocking=blocking)
    details = _controller_execution_details(request)
    valid_result = SimpleNamespace(
        success=True,
        messages=[],
        execution_details=dict(details),
    )
    try:
        live_worker._validate_execution_result(request, valid_result)
        details[field] = invalid_value
        result = SimpleNamespace(success=True, messages=[], execution_details=details)
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="Controller capability evidence is invalid",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize(
    "missing_field",
    [
        "completion_method",
        "controller_quit_supported",
        "controller_close_method",
    ],
)
def test_modern_controller_live_result_requires_complete_capability_evidence(
    tmp_path: Path,
    blocking: bool,
    missing_field: str,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    _configure_modern_controller_request(request, blocking=blocking)
    details = _controller_execution_details(request)
    details.pop(missing_field)
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="Controller capability evidence is missing",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("resolved_version", "missing_field"),
    [
        (resolved_version, missing_field)
        for resolved_version in ("4.0", "4.1")
        for missing_field in (
            "completion_method",
            "controller_quit_supported",
            "controller_close_method",
        )
    ],
)
def test_controller_live_result_requires_legacy_capability_evidence(
    tmp_path: Path,
    resolved_version: str,
    missing_field: str,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    request["engine"]["resolved_controller_version"] = resolved_version
    details = _controller_execution_details(request)
    details.pop(missing_field)
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="Controller capability evidence is missing",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


def test_controller_live_result_rejects_forged_executable_path(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    forged = tmp_path / "forged" / "Ras.exe"
    forged.parent.mkdir()
    forged.write_bytes(b"different Controller image")
    details = _controller_execution_details(
        request,
        controller_executable_path=str(forged),
    )
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="executable path mismatch",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("launcher_pid", None),
        ("launcher_pid", True),
        ("launcher_create_time", 0),
        ("launcher_create_time", float("nan")),
    ],
)
def test_modern_live_result_requires_exact_launcher_identity(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    details[field] = invalid_value
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="launcher PID/create-time",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("max_runtime_seconds", None),
        ("max_runtime_seconds", 31),
        ("runtime_timed_out", True),
        ("failure_stage", "wait"),
        ("failure_type", "TimeoutError"),
        ("failure_detail", "timed out"),
        ("cancellation_details", {"quiescence_confirmed": True}),
        (
            "artifact_finalization_failure",
            {
                "failure_stage": "result_artifact_finalization",
                "failure_type": "OSError",
                "failure_detail": "unexpected secondary failure",
            },
        ),
    ],
)
def test_modern_live_result_requires_coherent_runtime_contract(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    details[field] = invalid_value
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(live_worker.LiveWorkerError):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


@pytest.mark.parametrize(
    "cleanup_field",
    ["artifact_preparation_cleanup", "artifact_finalization_cleanup"],
)
def test_modern_live_result_requires_complete_cleanup_target_partition(
    tmp_path: Path,
    cleanup_field: str,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    details[cleanup_field]["missing_paths"] = []
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="target set mismatch",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


def test_modern_cleanup_partition_rejects_wrong_result_family_path(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    stage_project = Path(request["stage_root"]) / Path(
        request["source_project"]
    ).name
    details["artifact_preparation_cleanup"]["missing_paths"][0] = str(
        stage_project.with_suffix(".p01.hdf")
    )
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="target set mismatch",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


def test_modern_live_result_requires_callback_returned_launch_agreement(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    forged = dict(launch)
    forged["launcher_pid"] = 9753
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="disagree with the durable callback",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=forged,
            )
    finally:
        lock.release()


@pytest.mark.parametrize(
    "forgery",
    [
        "completion_not_boolean",
        "timeout_type_mismatch",
        "missing_failure_detail",
        "missing_cancellation",
        "unconfirmed_quiescence",
        "known_survivor",
        "initial_match_not_stopped",
    ],
)
def test_modern_failed_result_requires_safe_exact_cancellation_contract(
    tmp_path: Path,
    forgery: str,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _safe_timeout_execution_details(request, launch)
    completion_verified = False
    if forgery == "completion_not_boolean":
        completion_verified = None
    elif forgery == "timeout_type_mismatch":
        details["failure_type"] = "RuntimeError"
    elif forgery == "missing_failure_detail":
        details["failure_detail"] = ""
    elif forgery == "missing_cancellation":
        details["cancellation_details"] = None
    elif forgery == "unconfirmed_quiescence":
        details["cancellation_details"]["quiescence_confirmed"] = None
    elif forgery == "known_survivor":
        details["cancellation_details"]["survivors"] = list(
            details["cancellation_details"]["matched"]
        )
    elif forgery == "initial_match_not_stopped":
        details["cancellation_details"]["stopped"] = []
    else:  # pragma: no cover - closed parametrization above
        raise AssertionError(forgery)
    result = SimpleNamespace(
        success=False,
        completion_verified=completion_verified,
        execution_details=details,
    )
    try:
        with pytest.raises(live_worker.LiveWorkerError):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


def test_modern_finalization_failure_preserves_completion_evidence(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _safe_finalization_failure_execution_details(request, launch)
    result = SimpleNamespace(
        success=False,
        completion_verified=True,
        execution_details=details,
    )
    try:
        validated, success, completion, _, _ = live_worker._validate_execution_result(
            request,
            result,
            expected_launch_details=launch,
        )
    finally:
        lock.release()

    assert success is False
    assert completion is True
    assert validated["result_artifacts_finalized"] is False
    assert validated["artifact_finalization_failure"]["failure_type"] == "OSError"


def test_modern_timeout_preserves_primary_failure_with_secondary_finalization(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _safe_timeout_execution_details(request, launch)
    details.update(
        result_artifacts_finalized=False,
        artifact_finalization_cleanup=None,
        artifact_finalization_failure={
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "post-timeout result refresh failed",
        },
    )
    result = SimpleNamespace(
        success=False,
        completion_verified=False,
        execution_details=details,
    )
    try:
        validated, success, completion, _, _ = live_worker._validate_execution_result(
            request,
            result,
            expected_launch_details=launch,
        )
    finally:
        lock.release()

    assert success is False
    assert completion is False
    assert validated["runtime_timed_out"] is True
    assert validated["failure_stage"] == "subprocess_wait"
    assert validated["failure_type"] == "TimeoutError"
    assert validated["artifact_finalization_failure"]["failure_type"] == "OSError"


def test_modern_callback_timeout_error_does_not_claim_runtime_deadline(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _safe_timeout_execution_details(request, launch)
    details.update(
        runtime_timed_out=False,
        failure_stage="stream_callback",
        failure_detail="callback raised its own TimeoutError",
    )
    result = SimpleNamespace(
        success=False,
        completion_verified=True,
        execution_details=details,
    )
    try:
        validated, success, completion, _, _ = live_worker._validate_execution_result(
            request,
            result,
            expected_launch_details=launch,
        )
    finally:
        lock.release()

    assert success is False
    assert completion is True
    assert validated["runtime_timed_out"] is False
    assert validated["failure_type"] == "TimeoutError"
    assert validated["failure_stage"] == "stream_callback"


def test_modern_success_rejects_secondary_finalization_failure(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _modern_execution_details(request, launch)
    details["artifact_finalization_failure"] = {
        "failure_stage": "result_artifact_finalization",
        "failure_type": "OSError",
        "failure_detail": "forged secondary failure",
    }
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="secondary failure metadata",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


@pytest.mark.parametrize(
    "failure",
    [
        None,
        {},
        {
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
        },
        {
            "failure_stage": "solver_quiescence",
            "failure_type": "OSError",
            "failure_detail": "wrong stage",
        },
        {
            "failure_stage": "result_artifact_finalization",
            "failure_type": "OSError",
            "failure_detail": "",
        },
    ],
)
def test_modern_unfinalized_result_rejects_invalid_secondary_failure(
    tmp_path: Path,
    failure: Any,
) -> None:
    request, _, lock = _request(tmp_path)
    launch = _launch_details(request, Path(request["source_project"]))
    details = _safe_finalization_failure_execution_details(request, launch)
    details["artifact_finalization_failure"] = failure
    result = SimpleNamespace(
        success=False,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="complete secondary failure metadata",
        ):
            live_worker._validate_execution_result(
                request,
                result,
                expected_launch_details=launch,
            )
    finally:
        lock.release()


def test_missing_structured_process_capability_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        None,
        raising=False,
    )
    try:
        with pytest.raises(live_worker.LiveCapabilityError):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert not Path(request["stage_root"]).exists()
    assert not (
        context.run_root / "attempts" / "lane-1" / "attempt-1" / "worker_receipt.json"
    ).exists()


def test_incomplete_global_inventory_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        staticmethod(
            lambda: _PublicRecord(
                {
                    "observed_at": 1.0,
                    "complete": False,
                    "processes": [],
                    "query_errors": [
                        {
                            "pid": None,
                            "operation": "enumerate_processes",
                            "reason_code": "access_denied",
                            "exception_type": "AccessDenied",
                            "detail": "test uncertainty",
                        }
                    ],
                }
            )
        ),
    )
    try:
        with pytest.raises(live_worker.LiveProcessGateError, match="incomplete"):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert not Path(request["stage_root"]).exists()


def test_incomplete_execution_details_quarantine_before_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request, invalid_details=True)
    try:
        with pytest.raises(live_worker.LiveCapabilityError):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert len(calls["compute"]) == 1
    assert calls["inspection"] == 0
    assert not (
        context.run_root / "attempts" / "lane-1" / "attempt-1" / "worker_receipt.json"
    ).exists()


def test_required_invariant_failure_publishes_coherent_nonzero_worker_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)

    def conflicting_evidence(
        plan_number: str,
        *,
        ras_object: Any,
        hash_files: bool,
    ) -> ExecutionEvidence:
        assert plan_number == "01"
        assert hash_files is True
        return _evidence(ras_object.prj_file, result_format="legacy")

    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_execution_evidence",
        staticmethod(conflicting_evidence),
    )
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 20
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert receipt["terminal_category"] == "failed_invariant"
    assert receipt["worker_exit_code"] == 20
    rows = {row["invariant_id"]: row for row in receipt["tables"]["invariants"]}
    assert rows["R02"]["status"] == "fail"
    assert receipt["tables"]["lanes"][0]["all_invariants_passed"] is False


def test_unsuccessful_calculation_cannot_publish_a_passing_live_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)

    def unsuccessful_compute(plan_number: str, **kwargs: Any) -> Any:
        assert plan_number == "01"
        project = kwargs["ras_object"].prj_file
        launch = _launch_details(request, project)
        kwargs["stream_callback"].on_exec_launched(plan_number, launch)
        (project.parent / "Model.p01.hdf").write_bytes(b"failed calculation result")
        return SimpleNamespace(
            success=False,
            completion_verified=False,
            execution_details=_safe_timeout_execution_details(request, launch),
        )

    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "compute_plan",
        staticmethod(unsuccessful_compute),
    )
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 20
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert receipt["terminal_category"] == "execution_failed"
    assert receipt["tables"]["lanes"][0]["process_success"] is False
    assert receipt["tables"]["lanes"][0]["completion_verified"] is False
    assert receipt["execution_result"]["execution_details"][
        "runtime_timed_out"
    ] is True


def test_failed_finalization_with_ambiguous_results_publishes_diagnostic_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)

    def failed_compute(plan_number: str, **kwargs: Any) -> Any:
        project = kwargs["ras_object"].prj_file
        launch = _launch_details(request, project)
        kwargs["stream_callback"].on_exec_launched(plan_number, launch)
        hdf = project.with_suffix(f".p{plan_number}.hdf")
        legacy = project.with_suffix(f".O{plan_number}")
        hdf.write_bytes(b"modern result")
        legacy.write_bytes(b"legacy result")
        os.utime(hdf, ns=(1787923200000000000, 1787923200000000000))
        os.utime(legacy, ns=(1787923201000000000, 1787923201000000000))
        return SimpleNamespace(
            success=False,
            completion_verified=True,
            execution_details=_safe_finalization_failure_execution_details(
                request,
                launch,
            ),
        )

    def ambiguous_inspection(
        plan_number: str,
        *,
        ras_object: Any,
        hash_files: bool,
    ) -> Any:
        assert hash_files is True
        project = ras_object.prj_file
        hdf = project.with_suffix(f".p{plan_number}.hdf")
        legacy = project.with_suffix(f".O{plan_number}")
        raise ResultArtifactAmbiguityError(
            paths=PlanResultArtifactPaths(
                plan_number=plan_number,
                plan_file=project.with_suffix(f".p{plan_number}"),
                hdf=hdf,
                legacy_output=legacy,
                message_sidecars=(),
            ),
            declared_program_version="6.6",
            expected_format="hdf",
            reason_code="legacy_output_timestamp_after_hdf",
            hdf_mtime_ns=hdf.stat().st_mtime_ns,
            legacy_mtime_ns=legacy.stat().st_mtime_ns,
            detail="mixed result families prevent safe inspection",
        )

    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "compute_plan",
        staticmethod(failed_compute),
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_execution_evidence",
        staticmethod(ambiguous_inspection),
    )
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 20
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    evidence, evidence_sha256 = read_json_with_digest(attempt / "evidence.json")
    assert receipt["terminal_category"] == "execution_failed"
    assert receipt["execution_result"]["completion_verified"] is True
    assert receipt["tables"]["lanes"][0]["final_hdf_exists"] is True
    assert receipt["tables"]["lanes"][0]["final_legacy_exists"] is True
    assert receipt["tables"]["observations"] == []
    assert evidence == receipt["evidence"]
    assert evidence["evidence_kind"] == "execution_evidence_inspection_failure"
    assert evidence["failure_type"] == "ResultArtifactAmbiguityError"
    assert evidence["reason_code"] == "legacy_output_timestamp_after_hdf"
    invariant_rows = {
        row["invariant_id"]: row for row in receipt["tables"]["invariants"]
    }
    assert invariant_rows["R06"]["status"] == "pass"
    assert next(
        item
        for item in receipt["referenced_artifacts"]
        if item["relative_path"] == "evidence.json"
    )["sha256"] == evidence_sha256
    failed_events = [
        row
        for row in receipt["tables"]["events"]
        if row["event_name"] == "execution_evidence_inspection_failed"
    ]
    assert len(failed_events) == 1


def test_main_rejects_tampered_digest_before_live_imports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    write_json_with_digest(request_path, {"schema_version": 1, "action": "run"})
    request_path.write_text('{"schema_version":1,"action":"run","tampered":true}\n')

    assert live_worker.main(["--request", str(request_path)]) == 31
    assert "digest mismatch" in capsys.readouterr().err


def _write_worker_launch_intent(
    request: dict[str, Any],
    request_sha256: str,
) -> str:
    launch = request["worker_launch"]
    intent = {
        "schema_version": 1,
        "action": "launch_live_worker",
        "created_at": "2026-08-28T12:00:00+00:00",
        "request_sha256": request_sha256,
        "launch_nonce": launch["launch_nonce"],
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "supervisor_pid": os.getpid(),
        "supervisor_process_create_time": psutil.Process(os.getpid()).create_time(),
    }
    intent_sha256 = write_json_with_digest(launch["intent_path"], intent)
    process = psutil.Process(os.getpid())
    write_json_with_digest(
        launch["binding_path"],
        {
            "schema_version": 1,
            "action": "bind_live_worker_launcher",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_nonce": launch["launch_nonce"],
            "run_id": request["run_id"],
            "lane_id": request["lane_id"],
            "attempt_id": request["attempt_id"],
            "real_engine_lock_token": request["real_engine_lock"]["token"],
            "launcher_pid": os.getpid(),
            "launcher_process_create_time": process.create_time(),
            "expected_command": [sys.executable, "-m", "test-worker"],
        },
    )
    return intent_sha256


def test_worker_missing_parent_authorization_stops_before_staging(
    tmp_path: Path,
) -> None:
    request, _context_value, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    request_path = attempt_dir / "request.json"
    request_sha256 = write_json_with_digest(request_path, request)
    _write_worker_launch_intent(request, request_sha256)
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="did not authorize this exact worker identity",
        ):
            live_worker._register_and_verify_worker_authorization(
                request_path,
                request["worker_launch"]["launch_nonce"],
            )
    finally:
        lock.release()

    assert Path(request["worker_launch"]["hello_path"]).is_file()
    assert not Path(request["stage_root"]).exists()
    assert not (attempt_dir / "worker_receipt.json").exists()


def test_worker_tampered_parent_authorization_stops_before_staging(
    tmp_path: Path,
) -> None:
    request, _context_value, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    request_path = attempt_dir / "request.json"
    request_sha256 = write_json_with_digest(request_path, request)
    _write_worker_launch_intent(request, request_sha256)
    write_json_with_digest(
        request["worker_launch"]["authorization_path"],
        {
            "schema_version": 1,
            "action": "authorize_live_worker",
            "request_sha256": "0" * 64,
        },
    )
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="authorization mismatch for request_sha256",
        ):
            live_worker._register_and_verify_worker_authorization(
                request_path,
                request["worker_launch"]["launch_nonce"],
            )
    finally:
        lock.release()

    assert not Path(request["stage_root"]).exists()
    assert not (attempt_dir / "worker_receipt.json").exists()


def test_live_worker_contains_no_raw_process_or_filesystem_deletion_escape_hatch() -> None:
    source = Path(live_worker.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "psutil.process_iter" not in source
    assert ".terminate(" not in source
    assert ".kill(" not in source
    assert ".unlink(" not in source
    assert "taskkill" not in source.casefold()
    assert "stop-process" not in source.casefold()
    assert "Popen(" not in source
