"""Fresh-process supervision for staging and read-only evidence inspection."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .locks import ExclusiveQualificationLock
from .offline_records import json_safe, known_result_paths, lane_row, result_population
from .planning import RunContext, load_run, select_lane
from .receipts import VerifiedAttempt, verify_attempt_receipt, write_json_with_digest
from .replay import replay_origin_overrides
from .snapshots import snapshot_tree


class OfflineSupervisorError(RuntimeError):
    """An offline child could not produce one verified terminal receipt."""


@dataclass(frozen=True)
class ChildOutcome:
    pid: int
    returncode: int
    started_at: datetime
    finished_at: datetime
    timed_out: bool


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _worker_command(request: dict[str, Any], request_path: Path) -> list[str]:
    return [
        request["python_executable"],
        "-m",
        "scripts.qualification.execution_evidence.offline_worker",
        "--request",
        str(request_path),
    ]


def _run_child(
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    environment: dict[str, str],
) -> ChildOutcome:
    """Run one Python child; this helper never constructs a HEC-RAS command."""
    started = datetime.now(timezone.utc)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
        )
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            returncode = 124
    return ChildOutcome(
        pid=process.pid,
        returncode=returncode,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        timed_out=timed_out,
    )


def _request_source_snapshot(
    context: RunContext,
    *,
    lane_id: str,
    attempt_id: str,
    source_project: Path,
) -> Any:
    fixture = select_lane(context, lane_id)[1]
    return snapshot_tree(
        source_project.parent,
        run_id=context.descriptor["run_id"],
        lane_id=lane_id,
        attempt_id=attempt_id,
        phase="request_source_pin",
        root_kind="source",
        data_origin=fixture["data_origin"],
        known_paths=known_result_paths(source_project, fixture["plan_number"]),
    )


def create_attempt_request(
    context: RunContext,
    *,
    lane_id: str,
    action: str,
) -> tuple[Path, dict[str, Any], str]:
    """Publish one digest-bound stage/inspect request and unique stage path."""
    if action not in {"stage", "inspect"}:
        raise ValueError("offline action must be 'stage' or 'inspect'")
    lane, fixture, engine = select_lane(context, lane_id)
    if fixture["source_kind"] != "project_file":
        raise OfflineSupervisorError(
            f"offline phase currently requires source_kind=project_file, got {fixture['source_kind']}"
        )
    source_project = Path(fixture["source_project"]).resolve(strict=True)
    attempt_id = str(uuid.uuid4())
    attempt_dir = context.run_root / "attempts" / lane_id / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    stage_parent = (
        Path(context.descriptor["execution_run_root"]) / lane_id / attempt_id
    )
    stage_parent.mkdir(parents=True, exist_ok=False)
    stage_root = stage_parent / "stage"
    source_snapshot = _request_source_snapshot(
        context,
        lane_id=lane_id,
        attempt_id=attempt_id,
        source_project=source_project,
    )
    source_hdf, source_legacy = result_population(source_snapshot.rows)
    required_invariants = (
        ["R11"] if action == "stage" else list(lane["required_invariants"])
    )
    supported = {"R11"} if action == "stage" else {"R01", "R03", "R11"}
    unsupported = set(required_invariants) - supported
    if unsupported:
        raise OfflineSupervisorError(
            f"offline {action} cannot evaluate required invariants: {sorted(unsupported)}"
        )
    if (
        action == "inspect"
        and lane["expected_terminal_category"] == "expected_failure"
        and set(required_invariants) != {"R01", "R11"}
    ):
        raise OfflineSupervisorError(
            "offline expected-failure inspection requires exactly R01 and R11"
        )
    request = {
        "schema_version": 1,
        "action": action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": context.descriptor["run_id"],
        "lane_id": lane_id,
        "attempt_id": attempt_id,
        "manifest_sha256": context.manifest["manifest_sha256"],
        "normalized_manifest_path": str(
            context.run_root / "manifest.normalized.json"
        ),
        "normalized_manifest_sha256": context.normalized_manifest_sha256,
        "run_descriptor_sha256": context.descriptor_sha256,
        "repository_root": context.descriptor["repository_root"],
        "git_head": context.descriptor["git_head"],
        "python_executable": context.descriptor["python_executable"],
        "python_executable_sha256": context.descriptor[
            "python_executable_sha256"
        ],
        "python_version": context.descriptor["python_version"],
        "pyarrow_version": context.descriptor["pyarrow_version"],
        "psutil_version": context.descriptor["psutil_version"],
        "ras_commander_version": context.descriptor["ras_commander_version"],
        "ras_commander_import_path": context.descriptor[
            "ras_commander_import_path"
        ],
        "lane": lane,
        "fixture": fixture,
        "engine": engine,
        "required_invariants": required_invariants,
        "source_project": str(source_project),
        "source_snapshot_content_fingerprint": source_snapshot.content_fingerprint,
        "source_snapshot_metadata_fingerprint": source_snapshot.metadata_fingerprint,
        "source_hdf_exists": source_hdf,
        "source_legacy_exists": source_legacy,
        "stage_root": str(stage_root),
        "timeout_seconds": context.manifest["defaults"]["timeout_seconds"],
        "hash_files": context.manifest["defaults"]["hash_files"],
        "hec_ras_execution_enabled": False,
    }
    request_sha256 = write_json_with_digest(attempt_dir / "request.json", request)
    return attempt_dir, request, request_sha256


def _artifact_reference(attempt_dir: Path, path: Path) -> dict[str, str]:
    return {
        "relative_path": path.relative_to(attempt_dir).as_posix(),
        "sha256": _file_hash(path),
    }


def _synthesize_failure_receipt(
    attempt_dir: Path,
    request: dict[str, Any],
    request_sha256: str,
    outcome: ChildOutcome,
) -> VerifiedAttempt:
    terminal = "timed_out" if outcome.timed_out else "worker_crashed"
    source_project = Path(request["source_project"])
    known_paths = known_result_paths(
        source_project,
        request["fixture"]["plan_number"],
    )
    source_after = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_after_failed_worker",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=known_paths,
    )
    source_immutable = (
        source_after.content_fingerprint
        == request["source_snapshot_content_fingerprint"]
        and source_after.metadata_fingerprint
        == request["source_snapshot_metadata_fingerprint"]
    )
    artifact_rows = list(source_after.rows)
    stage_root = Path(request["stage_root"])
    final_hdf = False
    final_legacy = False
    if stage_root.is_dir():
        origin_overrides = replay_origin_overrides(
            request["fixture"].get("replay_artifacts")
        )
        origin_overrides[".ras-commander/stage.json"] = "generated_harness_receipt"
        stage_after = snapshot_tree(
            stage_root,
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
            phase="stage_after_failed_worker",
            root_kind="stage",
            data_origin=request["fixture"]["data_origin"],
            known_paths=known_paths,
            origin_overrides=origin_overrides,
        )
        artifact_rows.extend(stage_after.rows)
        final_hdf, final_legacy = result_population(stage_after.rows)
    event_row = {
        "schema_version": 1,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "sequence": 1,
        "event_at": outcome.finished_at,
        "phase": "supervision",
        "event_name": terminal,
        "status": "failed",
        "severity": "error",
        "api": "offline_worker",
        "reason_code": terminal,
        "detail": "Offline Python worker did not publish a verified terminal receipt",
        "relative_path": None,
        "pid": outcome.pid,
        "payload_json": json.dumps(
            {"returncode": outcome.returncode}, sort_keys=True, separators=(",", ":")
        ),
    }
    lane = lane_row(
        request,
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        worker_exit_code=outcome.returncode,
        terminal_category=terminal,
        stage_project_file=str(stage_root / source_project.name),
        selected_format=None,
        final_hdf_exists=final_hdf,
        final_legacy_exists=final_legacy,
        source_immutable=source_immutable,
        all_invariants_passed=False,
        failure_reason_code=terminal,
        detail=event_row["detail"],
    )
    references = [
        _artifact_reference(attempt_dir, attempt_dir / "stdout.log"),
        _artifact_reference(attempt_dir, attempt_dir / "stderr.log"),
    ]
    events_path = attempt_dir / "events.jsonl"
    if events_path.is_file():
        references.append(_artifact_reference(attempt_dir, events_path))
    receipt = {
        **{
            field: request[field]
            for field in ("schema_version", "run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head")
        },
        "action": request["action"],
        "required_invariants": request["required_invariants"],
        "request_sha256": request_sha256,
        "receipt_committed_at": datetime.now(timezone.utc).isoformat(),
        "terminal_category": terminal,
        "worker_exit_code": outcome.returncode,
        "worker_pid": outcome.pid,
        "python_executable": request["python_executable"],
        "python_executable_sha256": request["python_executable_sha256"],
        "python_version": request["python_version"],
        "pyarrow_version": request["pyarrow_version"],
        "psutil_version": request["psutil_version"],
        "ras_commander_version": request["ras_commander_version"],
        "ras_commander_import_path": request["ras_commander_import_path"],
        "package_root": request["repository_root"],
        "supervisor_synthesized": True,
        "hec_ras_invoked": False,
        "referenced_artifacts": references,
        "tables": {
            "lanes": [lane],
            "artifacts": artifact_rows,
            "observations": [],
            "events": [event_row],
            "invariants": [],
        },
    }
    write_json_with_digest(attempt_dir / "receipt.json", json_safe(receipt))
    return verify_attempt_receipt(attempt_dir)


def supervise_request(
    attempt_dir: Path,
    request: dict[str, Any],
    request_sha256: str,
    *,
    timeout_seconds: float | None = None,
) -> VerifiedAttempt:
    """Spawn exactly one fresh offline worker and verify or synthesize its receipt."""
    stdout_path = attempt_dir / "stdout.log"
    stderr_path = attempt_dir / "stderr.log"
    repository_root = Path(request["repository_root"]).resolve(strict=True)
    environment = os.environ.copy()
    prior_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(repository_root) + (
        os.pathsep + prior_pythonpath if prior_pythonpath else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = _worker_command(request, attempt_dir / "request.json")
    outcome = _run_child(
        command,
        cwd=repository_root,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=(
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(request["timeout_seconds"])
        ),
        environment=environment,
    )
    receipt_path = attempt_dir / "receipt.json"
    digest_path = attempt_dir / "receipt.sha256"
    if receipt_path.exists() or digest_path.exists():
        try:
            verified = verify_attempt_receipt(attempt_dir)
        except Exception as exc:
            raise OfflineSupervisorError(
                f"worker published an unverifiable receipt: {attempt_dir}"
            ) from exc
        receipt_exit = verified.receipt.get("worker_exit_code")
        receipt_terminal = verified.receipt.get("terminal_category")
        if receipt_exit != outcome.returncode:
            raise OfflineSupervisorError(
                "verified receipt worker_exit_code disagrees with observed child returncode"
            )
        if outcome.timed_out and (
            receipt_terminal != "timed_out" or receipt_exit != 124
        ):
            raise OfflineSupervisorError(
                "timed-out child published a non-timeout terminal receipt"
            )
        if not outcome.timed_out and receipt_terminal == "timed_out":
            raise OfflineSupervisorError(
                "non-timeout child published a timed_out receipt"
            )
        referenced = {
            item.get("relative_path")
            for item in verified.receipt.get("referenced_artifacts", [])
        }
        if not {"stdout.log", "stderr.log"}.issubset(referenced):
            raise OfflineSupervisorError(
                "terminal receipt does not reference both stdout.log and stderr.log"
            )
        return verified
    return _synthesize_failure_receipt(
        attempt_dir,
        request,
        request_sha256,
        outcome,
    )


def execute_offline_action(
    run_root: str | Path,
    *,
    action: str,
    lane_ids: Iterable[str] | None = None,
) -> tuple[VerifiedAttempt, ...]:
    """Serialize and execute fresh stage/inspect workers for selected lanes."""
    context = load_run(run_root)
    selected = list(lane_ids or context.descriptor["lane_ids"])
    if not selected:
        raise OfflineSupervisorError("at least one lane must be selected")
    results: list[VerifiedAttempt] = []
    with ExclusiveQualificationLock(
        context.run_root / "run.lock",
        kind="run",
        run_id=context.descriptor["run_id"],
        git_head=context.descriptor["git_head"],
    ):
        for lane_id in selected:
            attempt_dir, request, request_sha256 = create_attempt_request(
                context,
                lane_id=lane_id,
                action=action,
            )
            results.append(
                supervise_request(attempt_dir, request, request_sha256)
            )
    return tuple(results)


__all__ = [
    "ChildOutcome",
    "OfflineSupervisorError",
    "create_attempt_request",
    "execute_offline_action",
    "supervise_request",
]
