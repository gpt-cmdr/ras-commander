"""Fail-closed parent orchestration for acknowledged real-engine attempts.

The current public ``list_processes``/``cancel_plan`` APIs are intentionally not
used as safety evidence.  Live execution remains unavailable until the
additive structured APIs named in :func:`_require_strict_live_api_contracts`
exist.  Deterministic tests replace those seams and never start HEC-RAS or COM.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import psutil

from ras_commander.RasProject import STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM

from .locks import (
    ExclusiveQualificationLock,
    QualificationLockError,
    _read_lock_payload,
    _retire_verified_lock,
    inspect_lock,
)
from .manifest import (
    ManifestError,
    _MAX_WINDOWS_SUBPROCESS_WAIT_SECONDS,
    _MIN_INTERNAL_CANCELLATION_ALLOWANCE_SECONDS,
    _SUPERVISOR_RECEIPT_MARGIN_SECONDS,
    _git_read,
    _preflight_repository,
    canonical_json_bytes,
)
from .offline_records import json_safe, known_result_paths, lane_row, result_population
from .planning import RunContext, load_run, select_lane
from .receipts import (
    VerifiedAttempt,
    read_event_journal,
    read_json_with_digest,
    verify_attempt_receipt,
    write_json_with_digest,
)
from .schemas import SCHEMAS, table_from_rows
from .snapshots import (
    SnapshotError,
    assert_plain_ancestry,
    lexical_absolute_path,
    resolve_plain_path,
    snapshot_tree,
    stable_sha256,
)


class LiveSupervisorError(RuntimeError):
    """A live attempt was not safe to start or terminalize."""


class LiveHostQuarantinedError(LiveSupervisorError):
    """Process hygiene is uncertain and the host lock was intentionally retained."""


@dataclass(frozen=True)
class ProcessInventorySnapshot:
    records: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class LiveChildOutcome:
    pid: int
    returncode: int
    started_at: datetime
    finished_at: datetime
    timed_out: bool
    cancellation_safe: bool | None = None
    cancellation_reason: str | None = None


@dataclass(frozen=True)
class SupervisedAttempt:
    verified: VerifiedAttempt | None
    hygiene_safe: bool
    detail: str | None = None


@dataclass(frozen=True)
class RecoveryGateOutcome:
    safe_to_release: bool
    detail: str
    inventory: ProcessInventorySnapshot | None = None
    source_snapshot: dict[str, Any] | None = None
    worker_command_inventory: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkerIdentityState:
    alive: bool | None
    reason_code: str
    pid: int
    process_create_time: float


@dataclass(frozen=True)
class AuthorizedWorkerIdentity:
    """Exact worker identity bound to the process launched by the supervisor."""

    worker_pid: int
    worker_process_create_time: float
    launcher_pid: int
    launcher_process_create_time: float
    worker_parent_pid: int
    worker_parent_process_create_time: float
    delegated: bool
    command: tuple[str, ...]


_WORKER_TERMINALS = {
    "passed": 0,
    "expected_failure": 10,
    "failed_invariant": 20,
    "execution_failed": 20,
    "harness_error": 30,
}
_SUPPORTED_LIVE_INVARIANTS = {
    "R01",
    "R02",
    "R03",
    "R04",
    "R06",
    "R10",
    "R11",
    "R12",
}
_WORKER_IDENTITY_TOLERANCE_SECONDS = 0.001
_WORKER_AUTHORIZATION_POLL_SECONDS = 0.02
_MAX_QUALIFICATION_RECORD_PATH_CHARS = 259
_RASCMD_LAUNCH_DETAIL_FIELDS = frozenset(
    {
        "plan_number",
        "command",
        "executable_path",
        "executable_sha256",
        "project_path",
        "plan_path",
        "working_directory",
        "launcher_pid",
        "launcher_create_time",
        "max_runtime_seconds",
    }
)
_CANCELLATION_DETAIL_FIELDS = frozenset(
    {
        "plan_number",
        "project_path",
        "plan_path",
        "tmp_hdf_path",
        "cancellation_attempted",
        "pre_scan_complete",
        "post_scan_complete",
        "matched",
        "stopped",
        "survivors",
        "query_errors",
        "quiescence_confirmed",
        "started_at",
        "finished_at",
    }
)
_ARTIFACT_CLEANUP_FIELDS = frozenset(
    {
        "plan_number",
        "result_format",
        "include_message_sidecars",
        "removed_paths",
        "missing_paths",
    }
)
_ARTIFACT_IDENTITY_FIELDS = (
    "exists",
    "is_file",
    "size_bytes",
    "mtime_ns",
    "volume_id",
    "file_id",
    "sha256",
)
_PROCESS_RECORD_FIELDS = frozenset(
    {
        "pid",
        "create_time",
        "name",
        "executable_path",
        "command_line",
        "working_directory",
        "tracked",
        "session_id",
    }
)
_FAILED_INSPECTION_EVIDENCE_KIND = "execution_evidence_inspection_failure"
_FAILED_INSPECTION_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_kind",
        "evidence_id",
        "inspection_api",
        "inspection_state",
        "inspection_started_at",
        "inspection_failed_at",
        "failure_type",
        "reason_code",
        "detail",
        "plan_number",
        "declared_program_version",
        "declared_expected_result_format",
        "selected_result_format",
        "hdf_path",
        "legacy_output_path",
        "hdf_mtime_ns",
        "legacy_mtime_ns",
        "conflicts",
        "safe_failed_execution",
        "result_artifacts_finalized",
        "runtime_timed_out",
    }
)
_RESULT_ARTIFACT_AMBIGUITY_REASONS = frozenset(
    {
        "hdf_timestamp_after_legacy_output",
        "legacy_output_timestamp_after_hdf",
        "program_version_unresolved_multiple_formats",
        "result_artifact_timestamp_unavailable",
    }
)
_PARTIAL_WORKER_INTENT_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "created_at",
        "request_sha256",
        "launch_nonce",
        "run_id",
        "lane_id",
        "attempt_id",
        "real_engine_lock_token",
        "supervisor_pid",
        "supervisor_process_create_time",
    }
)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _structured_record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = dict(value)
    else:
        to_dict = getattr(value, "to_dict", None)
        if not callable(to_dict):
            raise LiveSupervisorError(
                "structured process evidence must expose explicit to_dict(): "
                f"{type(value).__name__}"
            )
        payload = to_dict()
        if not isinstance(payload, Mapping):
            raise LiveSupervisorError("structured process to_dict() did not return a mapping")
        payload = dict(payload)
    safe = json_safe(payload)
    try:
        json.dumps(safe, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LiveSupervisorError("structured process evidence is not JSON-safe") from exc
    return safe


def _require_strict_live_api_contracts(
    context: RunContext,
    lane_ids: Sequence[str],
) -> None:
    """Require additive structured APIs; never fall back to legacy booleans."""
    from ras_commander import RasCmdr, RasControl

    missing: list[str] = []
    if not callable(getattr(RasControl, "inspect_processes", None)):
        missing.append("RasControl.inspect_processes")
    if not callable(getattr(RasCmdr, "inspect_plan_processes", None)):
        missing.append("RasCmdr.inspect_plan_processes")
    modern = any(
        select_lane(context, lane_id)[2]["execution_api"] == "ras_cmdr"
        for lane_id in lane_ids
    )
    if modern:
        if not callable(getattr(RasCmdr, "cancel_plan_exact", None)):
            missing.append("RasCmdr.cancel_plan_exact")
    if missing:
        raise LiveSupervisorError(
            "live execution is unavailable until structured process/cancellation "
            f"evidence APIs are installed: {', '.join(missing)}"
        )


def _strict_process_inventory() -> ProcessInventorySnapshot:
    from ras_commander import RasControl

    inspect = getattr(RasControl, "inspect_processes", None)
    if not callable(inspect):
        raise LiveSupervisorError(
            "RasControl.inspect_processes is unavailable; legacy list_processes is not safety evidence"
        )
    inventory = inspect()
    if _field(inventory, "complete") is not True:
        raise LiveSupervisorError("HEC-RAS process inventory is incomplete")
    query_errors = _field(inventory, "query_errors")
    if not isinstance(query_errors, (list, tuple)) or query_errors:
        raise LiveSupervisorError("HEC-RAS process inventory contains query errors")
    processes = _field(inventory, "processes")
    if not isinstance(processes, (list, tuple)):
        raise LiveSupervisorError("structured process inventory has no process sequence")
    records = tuple(_structured_record(process) for process in processes)
    raw = _structured_record(inventory)
    return ProcessInventorySnapshot(records=records, raw=raw)


def _bind_live_context(context: RunContext) -> None:
    repository_root = Path(context.descriptor["repository_root"]).resolve(strict=True)
    observed = _preflight_repository(
        repository_root,
        required_head=context.descriptor["git_head"],
        require_clean=True,
    )
    if observed.get("observed_clean") is not True:
        raise LiveSupervisorError("live execution requires a clean pinned repository")
    if observed.get("observed_head") != context.descriptor["git_head"]:
        raise LiveSupervisorError("live execution repository HEAD changed after planning")
    if context.manifest["repository"].get("require_clean") is not True:
        raise LiveSupervisorError("live execution requires repository.require_clean=true")
    if context.manifest["defaults"].get("real_engine_jobs") != 1:
        raise LiveSupervisorError("live execution requires defaults.real_engine_jobs=1")


def _bind_recovery_context(
    context: RunContext,
    *,
    acknowledge_code_upgrade: bool,
) -> str:
    """Bind recovery to the archived head or a clean descendant commit."""
    archived_head = str(context.descriptor["git_head"]).casefold()
    try:
        _bind_live_context(context)
    except ManifestError as exact_error:
        repository_root = Path(context.descriptor["repository_root"]).resolve(
            strict=True
        )
        current_head = _git_read(
            repository_root,
            "rev-parse",
            "--verify",
            "HEAD",
        ).casefold()
        if current_head == archived_head:
            raise exact_error
        if not acknowledge_code_upgrade:
            raise LiveSupervisorError(
                "cross-head recovery requires explicit code-upgrade acknowledgement"
            ) from exact_error
        _preflight_repository(
            repository_root,
            required_head=current_head,
            require_clean=True,
        )
        command = [
            "git",
            "-c",
            f"safe.directory={repository_root}",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            archived_head,
            current_head,
        ]
        try:
            ancestry = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveSupervisorError(
                "could not prove recovery-code ancestry"
            ) from exc
        if ancestry.returncode != 0:
            raise LiveSupervisorError(
                "recovery code must be the archived head or a clean descendant"
            ) from exact_error
        return current_head
    return archived_head


def _host_lock_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise LiveSupervisorError("LOCALAPPDATA is required for the host real-engine lock")
    return (
        Path(local_app_data)
        / "ras-commander"
        / "qualification-locks"
        / "real-engine.lock"
    )


def _create_plain_descendant(root: str | Path, relative: Path) -> Path:
    """Create and prove one plain descendant without following redirections."""
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise LiveSupervisorError("descendant path must be non-empty and relative")
    try:
        boundary = resolve_plain_path(root, kind="directory")
        candidate = assert_plain_ancestry(boundary / relative, stop=boundary)
        candidate.mkdir(parents=True, exist_ok=False)
        candidate = assert_plain_ancestry(candidate, stop=boundary)
        resolved = resolve_plain_path(candidate, kind="directory")
        resolved.relative_to(boundary)
    except (OSError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError(
            f"qualification descendant is not confined to a plain root: {relative}"
        ) from exc
    return resolved


def _validate_live_attempt_path_budget(run_root: Path, lane_id: str) -> None:
    """Reject an attempt whose immutable records exceed the tested Win32 limit."""
    placeholder_attempt = "0" * 36
    attempt = lexical_absolute_path(
        run_root / "attempts" / lane_id / placeholder_attempt
    )
    record_names = (
        "request.sha256",
        "worker-launch-intent.sha256",
        "worker-launcher.sha256",
        "worker-hello.sha256",
        "worker-authorization.sha256",
        "worker_receipt.sha256",
        "receipt.sha256",
    )
    longest = max((attempt / name for name in record_names), key=lambda path: len(str(path)))
    if len(str(longest)) > _MAX_QUALIFICATION_RECORD_PATH_CHARS:
        raise LiveSupervisorError(
            "live attempt archive path exceeds the tested 259-character "
            f"record boundary: {longest}"
        )


def _select_live_lanes(
    context: RunContext,
    *,
    lane_ids: Iterable[str] | None,
    phase: str | None,
) -> list[str]:
    requested = list(lane_ids or context.descriptor["lane_ids"])
    if not requested or len(requested) != len(set(requested)):
        raise LiveSupervisorError("live run requires unique selected lanes")
    selected: list[str] = []
    for lane_id in requested:
        lane, fixture, engine = select_lane(context, lane_id)
        if phase is not None and phase not in lane.get("tags", []):
            continue
        if "real_ras" not in lane.get("tags", []):
            raise LiveSupervisorError(
                f"lane is not explicitly tagged real_ras: {lane_id}"
            )
        if fixture.get("source_kind") != "project_file":
            raise LiveSupervisorError(
                f"live lane requires source_kind=project_file: {lane_id}"
            )
        if fixture.get("replay_artifacts") is not None:
            raise LiveSupervisorError(
                f"captured replay artifacts cannot be used by a live lane: {lane_id}"
            )
        if engine.get("support_state") != "supported":
            raise LiveSupervisorError(f"live lane engine is not supported: {lane_id}")
        if lane.get("expected_terminal_category") != "passed":
            raise LiveSupervisorError(
                f"live v1 supports only expected_terminal_category=passed: {lane_id}"
            )
        if lane.get("initial_state") != "neither":
            raise LiveSupervisorError(
                "live v1 enables only L0/L1 lanes with initial_state=neither; "
                f"L2/L3/L4 campaigns remain held: {lane_id}"
            )
        if set(lane.get("required_invariants", [])) != _SUPPORTED_LIVE_INVARIANTS:
            raise LiveSupervisorError(
                "live v1 requires its complete supported invariant set for lane "
                f"{lane_id}: {sorted(_SUPPORTED_LIVE_INVARIANTS)}"
            )
        selected.append(lane_id)
    if not selected:
        raise LiveSupervisorError("live lane selection is empty")
    return selected


def _source_snapshot(
    context: RunContext,
    *,
    lane_id: str,
    attempt_id: str,
    source_project: Path,
) -> Any:
    fixture = select_lane(context, lane_id)[1]
    snapshot = snapshot_tree(
        source_project.parent,
        run_id=context.descriptor["run_id"],
        lane_id=lane_id,
        attempt_id=attempt_id,
        phase="live_request_source_pin",
        root_kind="source",
        data_origin=fixture["data_origin"],
        known_paths=known_result_paths(source_project, fixture["plan_number"]),
    )
    if snapshot.content_fingerprint != fixture["source_content_fingerprint"]:
        raise LiveSupervisorError(
            f"source content fingerprint changed before live lane {lane_id}"
        )
    if (
        snapshot.fingerprint_algorithm
        != fixture["source_content_fingerprint_algorithm"]
    ):
        raise LiveSupervisorError(
            f"source fingerprint algorithm changed before live lane {lane_id}"
        )
    return snapshot


def create_live_attempt_request(
    context: RunContext,
    *,
    lane_id: str,
    attempt_id: str,
    process_baseline: ProcessInventorySnapshot,
    real_engine_lock_path: Path,
    real_engine_lock_payload: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], str]:
    lane, fixture, engine = select_lane(context, lane_id)
    source_project = Path(fixture["source_project"]).resolve(strict=True)
    attempt_dir = _create_plain_descendant(
        context.run_root,
        Path("attempts") / lane_id / attempt_id,
    )
    execution_root = resolve_plain_path(
        context.descriptor["execution_run_root"], kind="directory"
    )
    stage_parent = _create_plain_descendant(
        execution_root,
        Path(lane_id) / attempt_id,
    )
    stage_root = assert_plain_ancestry(stage_parent / "stage", stop=execution_root)
    source = _source_snapshot(
        context,
        lane_id=lane_id,
        attempt_id=attempt_id,
        source_project=source_project,
    )
    source_hdf, source_legacy = result_population(
        source.rows,
        project_file=source_project,
        plan_number=fixture["plan_number"],
    )
    lock_proof = {
        "path": str(real_engine_lock_path.resolve(strict=True)),
        "token": real_engine_lock_payload["token"],
        "run_id": context.descriptor["run_id"],
        "lane_id": lane_id,
        "attempt_id": attempt_id,
    }
    worker_launch = {
        "launch_nonce": str(uuid.uuid4()),
        "intent_path": str(attempt_dir / "worker-launch-intent.json"),
        "binding_path": str(attempt_dir / "worker-launcher.json"),
        "hello_path": str(attempt_dir / "worker-hello.json"),
        "authorization_path": str(attempt_dir / "worker-authorization.json"),
    }
    request = {
        "schema_version": 1,
        "action": "run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": context.descriptor["run_id"],
        "lane_id": lane_id,
        "attempt_id": attempt_id,
        "manifest_sha256": context.manifest["manifest_sha256"],
        "normalized_manifest_path": str(context.run_root / "manifest.normalized.json"),
        "normalized_manifest_sha256": context.normalized_manifest_sha256,
        "run_descriptor_sha256": context.descriptor_sha256,
        "repository_root": context.descriptor["repository_root"],
        "git_head": context.descriptor["git_head"],
        "python_executable": context.descriptor["python_executable"],
        "python_executable_sha256": context.descriptor["python_executable_sha256"],
        "python_version": context.descriptor["python_version"],
        "pyarrow_version": context.descriptor["pyarrow_version"],
        "psutil_version": context.descriptor["psutil_version"],
        "ras_commander_version": context.descriptor["ras_commander_version"],
        "ras_commander_import_path": context.descriptor["ras_commander_import_path"],
        "lane": lane,
        "fixture": fixture,
        "engine": engine,
        "required_invariants": list(lane["required_invariants"]),
        "source_project": str(source_project),
        "source_snapshot_content_fingerprint_algorithm": (
            source.fingerprint_algorithm
        ),
        "source_snapshot_content_fingerprint": source.content_fingerprint,
        "source_snapshot_metadata_fingerprint": source.metadata_fingerprint,
        "source_hdf_exists": source_hdf,
        "source_legacy_exists": source_legacy,
        "stage_root": str(stage_root),
        "preflight_timeout_seconds": context.manifest["defaults"][
            "preflight_timeout_seconds"
        ],
        "timeout_seconds": context.manifest["defaults"]["timeout_seconds"],
        "termination_grace_seconds": context.manifest["defaults"][
            "termination_grace_seconds"
        ],
        "postflight_timeout_seconds": context.manifest["defaults"][
            "postflight_timeout_seconds"
        ],
        "supervisor_receipt_margin_seconds": _SUPERVISOR_RECEIPT_MARGIN_SECONDS,
        "hash_files": context.manifest["defaults"]["hash_files"],
        "process_baseline": list(process_baseline.records),
        "process_baseline_evidence": process_baseline.raw,
        "real_engine_lock": lock_proof,
        "worker_launch": worker_launch,
        "hec_ras_execution_enabled": True,
    }
    request_sha256 = write_json_with_digest(attempt_dir / "request.json", request)
    return attempt_dir, request, request_sha256


def _worker_command(request: Mapping[str, Any], request_path: Path) -> list[str]:
    return [
        str(request["python_executable"]),
        "-m",
        "scripts.qualification.execution_evidence.live_worker",
        "--request",
        str(request_path),
        "--launch-nonce",
        str(request["worker_launch"]["launch_nonce"]),
    ]


def _worker_launch_paths(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> tuple[str, Path, Path, Path]:
    launch = request.get("worker_launch")
    if not isinstance(launch, Mapping):
        raise LiveSupervisorError("live request lacks worker launch handshake metadata")
    nonce = launch.get("launch_nonce")
    if not isinstance(nonce, str):
        raise LiveSupervisorError("worker launch nonce is missing")
    try:
        uuid.UUID(nonce)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveSupervisorError("worker launch nonce is invalid") from exc
    expected = (
        attempt_dir / "worker-launch-intent.json",
        attempt_dir / "worker-hello.json",
        attempt_dir / "worker-authorization.json",
    )
    claimed = tuple(
        lexical_absolute_path(str(launch.get(field, "")))
        for field in ("intent_path", "hello_path", "authorization_path")
    )
    if claimed != tuple(lexical_absolute_path(path) for path in expected):
        raise LiveSupervisorError("worker launch handshake paths escaped the attempt")
    return nonce, *expected


def _worker_launcher_path(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> Path:
    launch = request.get("worker_launch")
    if not isinstance(launch, Mapping):
        raise LiveSupervisorError("live request lacks worker launch handshake metadata")
    expected = lexical_absolute_path(attempt_dir / "worker-launcher.json")
    claimed = lexical_absolute_path(str(launch.get("binding_path", "")))
    if claimed != expected:
        raise LiveSupervisorError("worker launcher binding path escaped the attempt")
    return expected


def _cancel_launch_paths(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> tuple[str, Path, Path, Path, Path]:
    launch = request.get("cancel_launch")
    if not isinstance(launch, Mapping):
        raise LiveSupervisorError("cancellation request lacks launch handshake metadata")
    nonce = launch.get("launch_nonce")
    try:
        uuid.UUID(str(nonce))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveSupervisorError("cancellation launch nonce is invalid") from exc
    expected = tuple(
        lexical_absolute_path(attempt_dir / name)
        for name in (
            "cancel-intent.json",
            "cancel-launcher.json",
            "cancel-hello.json",
            "cancel-auth.json",
        )
    )
    claimed = tuple(
        lexical_absolute_path(str(launch.get(field, "")))
        for field in (
            "intent_path",
            "binding_path",
            "hello_path",
            "authorization_path",
        )
    )
    if claimed != expected:
        raise LiveSupervisorError("cancellation launch paths escaped the attempt")
    return str(nonce), *expected


def _inspect_exact_worker_identity(
    pid: int,
    process_create_time: float,
) -> WorkerIdentityState:
    """Inspect one exact Python identity without making a name-based claim."""
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(process_create_time, (int, float))
        or isinstance(process_create_time, bool)
        or not math.isfinite(float(process_create_time))
    ):
        return WorkerIdentityState(
            None,
            "worker_identity_invalid",
            int(pid) if isinstance(pid, int) and not isinstance(pid, bool) else -1,
            float(process_create_time)
            if isinstance(process_create_time, (int, float))
            and not isinstance(process_create_time, bool)
            else math.nan,
        )
    expected = float(process_create_time)
    try:
        process = psutil.Process(pid)
        observed = float(process.create_time())
        running = process.is_running()
    except psutil.NoSuchProcess:
        return WorkerIdentityState(False, "worker_absent", pid, expected)
    except (psutil.AccessDenied, psutil.ZombieProcess, OSError, ValueError):
        return WorkerIdentityState(None, "worker_identity_unverifiable", pid, expected)
    if not math.isfinite(observed):
        return WorkerIdentityState(None, "worker_identity_unverifiable", pid, expected)
    if abs(observed - expected) > _WORKER_IDENTITY_TOLERANCE_SECONDS:
        return WorkerIdentityState(False, "worker_pid_reused", pid, expected)
    if not running:
        return WorkerIdentityState(False, "worker_absent", pid, expected)
    return WorkerIdentityState(True, "worker_alive", pid, expected)


def _worker_command_recovery_gate(
    expected_command: Sequence[str],
) -> tuple[bool, str, dict[str, Any]]:
    """Prove no Python process has the exact archived worker command."""
    expected = [str(part) for part in expected_command]
    candidate_name = Path(expected[0]).name.casefold()
    query_errors: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    observed_at = time.time()
    try:
        processes = psutil.process_iter(["pid", "name"])
        for process in processes:
            try:
                pid = process.info.get("pid")
                name_value = process.info.get("name")
                # Windows reserves PID 0 for the System Idle Process. It can
                # expose no name through psutil, but it cannot be the positive-
                # PID Python worker launched by this harness.
                if os.name == "nt" and pid == 0:
                    continue
                if (
                    not isinstance(pid, int)
                    or isinstance(pid, bool)
                    or pid <= 0
                    or not isinstance(name_value, str)
                    or not name_value.strip()
                ):
                    query_errors.append(
                        {
                            "pid": pid if isinstance(pid, int) else None,
                            "reason_code": "process_name_unavailable",
                            "detail": "could not classify process as a Python candidate",
                        }
                    )
                    continue
                name = name_value.casefold()
                if name != candidate_name:
                    continue
                command = process.cmdline()
                create_time = float(process.create_time())
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError, ValueError) as exc:
                query_errors.append(
                    {
                        "pid": process.pid,
                        "reason_code": "candidate_query_failed",
                        "detail": type(exc).__name__,
                    }
                )
                continue
            if (
                not isinstance(command, list)
                or any(not isinstance(part, str) for part in command)
                or not math.isfinite(create_time)
                or create_time <= 0
            ):
                query_errors.append(
                    {
                        "pid": process.pid,
                        "reason_code": "candidate_identity_invalid",
                        "detail": "command line or create time is invalid",
                    }
                )
                continue
            if command == expected:
                matched.append(
                    {
                        "pid": process.pid,
                        "create_time": create_time,
                        "name": name_value,
                        "command_line": command,
                    }
                )
    except (psutil.AccessDenied, psutil.ZombieProcess, OSError, ValueError) as exc:
        query_errors.append(
            {
                "pid": None,
                "reason_code": "process_iteration_failed",
                "detail": type(exc).__name__,
            }
        )
    inventory = {
        "observed_at": observed_at,
        "complete": not query_errors,
        "expected_command": expected,
        "matches": matched,
        "query_errors": query_errors,
    }
    if query_errors:
        return False, "worker command inventory contains query errors", inventory
    if matched:
        return False, "exact archived worker command is still active", inventory
    return True, "exact archived worker command is absent", inventory


def _live_python_child_identity(process: subprocess.Popen[Any]) -> tuple[int, float]:
    pid = process.pid
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise LiveSupervisorError("live Python child returned an invalid PID")
    try:
        child = psutil.Process(pid)
        create_time = float(child.create_time())
        running = child.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError) as exc:
        raise LiveSupervisorError(
            "live Python child identity could not be proved after launch"
        ) from exc
    if not running or not math.isfinite(create_time):
        raise LiveSupervisorError("live Python child identity is not running and stable")
    return pid, create_time


def _bind_launched_worker_identity(
    process: subprocess.Popen[Any],
    *,
    launcher_pid: int,
    launcher_create_time: float,
    worker_pid: Any,
    worker_create_time: Any,
    expected_command: Sequence[str],
) -> AuthorizedWorkerIdentity:
    """Bind a worker hello to the exact process tree created by ``Popen``.

    A Windows virtual-environment ``python.exe`` can be the standard Python
    launcher. In that case ``Popen.pid`` identifies the launcher, which starts
    one base-interpreter child and waits for it. Accept only that one-hop shape:
    the hello process must be the launcher's sole direct child and both process
    command lines must exactly equal the command supplied to ``Popen``.
    """
    if (
        not isinstance(worker_pid, int)
        or isinstance(worker_pid, bool)
        or worker_pid <= 0
        or not isinstance(worker_create_time, (int, float))
        or isinstance(worker_create_time, bool)
        or not math.isfinite(float(worker_create_time))
        or float(worker_create_time) <= 0
    ):
        raise LiveSupervisorError("worker hello lacks a valid PID/create-time identity")
    if process.pid != launcher_pid:
        raise LiveSupervisorError("live Python launcher PID changed during authorization")
    expected = [str(part) for part in expected_command]
    try:
        launcher = psutil.Process(launcher_pid)
        observed_launcher_create_time = float(launcher.create_time())
        launcher_running = launcher.is_running()
        launcher_command = launcher.cmdline()
        launcher_children = launcher.children(recursive=False)
        worker = psutil.Process(worker_pid)
        observed_worker_create_time = float(worker.create_time())
        worker_running = worker.is_running()
        worker_command = worker.cmdline()
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError(
            "live Python worker process-tree identity could not be proved"
        ) from exc
    if (
        not launcher_running
        or not math.isfinite(observed_launcher_create_time)
        or abs(observed_launcher_create_time - launcher_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError("live Python launcher identity changed before authorization")
    if launcher_command != expected:
        raise LiveSupervisorError("live Python launcher command line changed before authorization")
    expected_worker_create_time = float(worker_create_time)
    if (
        not worker_running
        or not math.isfinite(observed_worker_create_time)
        or abs(observed_worker_create_time - expected_worker_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError("worker hello create-time identity mismatch")
    if worker_command != expected:
        raise LiveSupervisorError("live Python worker command line is not the launched command")
    try:
        parent = worker.parent()
        if parent is None:
            raise LiveSupervisorError("live Python worker parent identity is unavailable")
        worker_parent_pid = parent.pid
        worker_parent_create_time = float(parent.create_time())
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError(
            "live Python worker parent identity could not be proved"
        ) from exc
    if (
        not isinstance(worker_parent_pid, int)
        or isinstance(worker_parent_pid, bool)
        or worker_parent_pid <= 0
        or not math.isfinite(worker_parent_create_time)
        or worker_parent_create_time <= 0
    ):
        raise LiveSupervisorError("live Python worker parent identity is invalid")
    if worker_pid == launcher_pid:
        if (
            abs(expected_worker_create_time - launcher_create_time)
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
        ):
            raise LiveSupervisorError("worker hello create-time identity mismatch")
        return AuthorizedWorkerIdentity(
            worker_pid=worker_pid,
            worker_process_create_time=expected_worker_create_time,
            launcher_pid=launcher_pid,
            launcher_process_create_time=launcher_create_time,
            worker_parent_pid=worker_parent_pid,
            worker_parent_process_create_time=worker_parent_create_time,
            delegated=False,
            command=tuple(expected),
        )
    if os.name != "nt":
        raise LiveSupervisorError(
            "worker hello PID is not the exact launched Python process"
        )
    try:
        child_identities = [
            (child.pid, float(child.create_time())) for child in launcher_children
        ]
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError(
            "Windows Python launcher child identity could not be proved"
        ) from exc
    if worker_parent_pid != launcher_pid:
        raise LiveSupervisorError(
            "worker hello PID is not a direct child of the launched Python process"
        )
    if (
        abs(worker_parent_create_time - launcher_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or len(child_identities) != 1
        or child_identities[0][0] != worker_pid
        or abs(child_identities[0][1] - expected_worker_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or expected_worker_create_time
        < launcher_create_time - _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError(
            "Windows Python launcher does not have one exact worker child"
        )
    return AuthorizedWorkerIdentity(
        worker_pid=worker_pid,
        worker_process_create_time=expected_worker_create_time,
        launcher_pid=launcher_pid,
        launcher_process_create_time=launcher_create_time,
        worker_parent_pid=worker_parent_pid,
        worker_parent_process_create_time=worker_parent_create_time,
        delegated=True,
        command=tuple(expected),
    )


def _terminate_authorized_worker(
    process: subprocess.Popen[Any],
    identity: AuthorizedWorkerIdentity,
    grace: float,
) -> None:
    """Terminate only a revalidated worker identity, not its launcher wrapper."""
    worker = _verified_authorized_worker_process(process, identity)
    timeout = max(0.1, min(grace, 10.0))
    try:
        worker.terminate()
        try:
            worker.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            _verified_authorized_worker_process(
                process,
                identity,
                worker=worker,
            )
            worker.kill()
            worker.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass
    except (
        psutil.AccessDenied,
        psutil.ZombieProcess,
        psutil.TimeoutExpired,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError(
            "authorized Python worker could not be terminated exactly"
        ) from exc
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LiveSupervisorError(
            "Python launcher remained alive after exact worker termination"
        ) from exc


def _verified_authorized_worker_process(
    process: subprocess.Popen[Any],
    identity: AuthorizedWorkerIdentity,
    *,
    worker: psutil.Process | None = None,
) -> psutil.Process:
    """Return the same process object whose exact identity is verified for signal."""
    if process.pid != identity.launcher_pid:
        raise LiveSupervisorError("authorized Python launcher PID changed")
    try:
        launcher = psutil.Process(identity.launcher_pid)
        if worker is None:
            worker = psutil.Process(identity.worker_pid)
        launcher_create_time = float(launcher.create_time())
        worker_create_time = float(worker.create_time())
        parent = worker.parent()
        launcher_children = launcher.children(recursive=False)
        worker_children = worker.children(recursive=False)
        launcher_command = launcher.cmdline()
        worker_command = worker.cmdline()
        launcher_running = launcher.is_running()
        worker_running = worker.is_running()
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError(
            "authorized Python worker signal identity is unverifiable"
        ) from exc
    if parent is None:
        raise LiveSupervisorError("authorized Python worker parent is unavailable")
    parent_create_time = float(parent.create_time())
    if (
        not launcher_running
        or not worker_running
        or worker.pid != identity.worker_pid
        or abs(launcher_create_time - identity.launcher_process_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or abs(worker_create_time - identity.worker_process_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or parent.pid != identity.worker_parent_pid
        or abs(parent_create_time - identity.worker_parent_process_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or launcher_command != list(identity.command)
        or worker_command != list(identity.command)
        or worker_children
    ):
        raise LiveSupervisorError("authorized Python worker changed before signal")
    if identity.delegated:
        if (
            identity.worker_parent_pid != identity.launcher_pid
            or len(launcher_children) != 1
            or launcher_children[0].pid != identity.worker_pid
            or abs(
                float(launcher_children[0].create_time())
                - identity.worker_process_create_time
            )
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
        ):
            raise LiveSupervisorError("delegated Python worker tree changed before signal")
    elif launcher_children:
        raise LiveSupervisorError("direct Python worker has a child before signal")
    return worker


def _current_supervisor_identity() -> tuple[int, float]:
    pid = os.getpid()
    try:
        process = psutil.Process(pid)
        create_time = float(process.create_time())
        running = process.is_running()
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        OSError,
        ValueError,
    ) as exc:
        raise LiveSupervisorError("supervisor process identity could not be proved") from exc
    if not running or not math.isfinite(create_time) or create_time <= 0:
        raise LiveSupervisorError("supervisor process identity is not stable")
    return pid, create_time


def _publish_worker_launch_intent(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> str:
    nonce, intent_path, _, _ = _worker_launch_paths(attempt_dir, request)
    lock = request["real_engine_lock"]
    supervisor_pid, supervisor_create_time = _current_supervisor_identity()
    intent = {
        "schema_version": 1,
        "action": "launch_live_worker",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": lock["token"],
        "supervisor_pid": supervisor_pid,
        "supervisor_process_create_time": supervisor_create_time,
    }
    return write_json_with_digest(intent_path, json_safe(intent))


def _publish_worker_launcher_binding(
    process: subprocess.Popen[Any],
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    intent_sha256: str,
    command: Sequence[str],
) -> str:
    """Durably record the exact Popen identity before awaiting child hello."""
    nonce, _, _, _ = _worker_launch_paths(attempt_dir, request)
    binding_path = _worker_launcher_path(attempt_dir, request)
    launcher_pid, launcher_create_time = _live_python_child_identity(process)
    binding = {
        "schema_version": 1,
        "action": "bind_live_worker_launcher",
        "bound_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "launcher_pid": launcher_pid,
        "launcher_process_create_time": launcher_create_time,
        "expected_command": [str(part) for part in command],
    }
    return write_json_with_digest(binding_path, json_safe(binding))


def _wait_for_worker_hello(
    hello_path: Path,
    *,
    timeout_seconds: float,
) -> tuple[dict[str, Any], str]:
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    digest_path = hello_path.with_suffix(".sha256")
    while True:
        if hello_path.exists() and digest_path.exists():
            return read_json_with_digest(hello_path)
        if time.monotonic() >= deadline:
            raise LiveSupervisorError(
                "live Python child did not publish a worker identity hello"
            )
        time.sleep(_WORKER_AUTHORIZATION_POLL_SECONDS)


def _authorize_live_child(
    process: subprocess.Popen[Any],
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    intent_sha256: str,
    *,
    expected_command: Sequence[str] | None = None,
) -> AuthorizedWorkerIdentity:
    """Bind exact parent-observed PID/create-time before worker execution."""
    nonce, intent_path, hello_path, authorization_path = _worker_launch_paths(
        attempt_dir, request
    )
    command = (
        list(expected_command)
        if expected_command is not None
        else _worker_command(request, attempt_dir / "request.json")
    )
    intent, observed_intent_sha256 = read_json_with_digest(intent_path)
    if observed_intent_sha256 != intent_sha256:
        raise LiveSupervisorError("worker launch intent digest changed before authorization")
    supervisor_pid = intent.get("supervisor_pid")
    supervisor_create_time = intent.get("supervisor_process_create_time")
    if (
        not isinstance(supervisor_pid, int)
        or isinstance(supervisor_pid, bool)
        or supervisor_pid <= 0
        or not isinstance(supervisor_create_time, (int, float))
        or isinstance(supervisor_create_time, bool)
        or not math.isfinite(float(supervisor_create_time))
        or float(supervisor_create_time) <= 0
    ):
        raise LiveSupervisorError("worker launch intent lacks supervisor identity")
    binding, binding_sha256 = read_json_with_digest(
        _worker_launcher_path(attempt_dir, request)
    )
    binding_expected = {
        "schema_version": 1,
        "action": "bind_live_worker_launcher",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "expected_command": [str(part) for part in command],
    }
    if any(binding.get(field) != value for field, value in binding_expected.items()):
        raise LiveSupervisorError("worker launcher binding identity is unverifiable")
    launcher_pid = binding.get("launcher_pid")
    launcher_create_time = binding.get("launcher_process_create_time")
    if not _valid_pid_create_time(launcher_pid, launcher_create_time):
        raise LiveSupervisorError("worker launcher binding lacks exact process identity")
    hello, hello_sha256 = _wait_for_worker_hello(
        hello_path,
        timeout_seconds=min(
            60.0,
            max(0.1, float(request["termination_grace_seconds"])),
        ),
    )
    expected = {
        "schema_version": 1,
        "action": "hello_live_worker",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
    }
    for field, value in expected.items():
        if hello.get(field) != value:
            raise LiveSupervisorError(f"worker hello identity mismatch for {field}")
    identity = _bind_launched_worker_identity(
        process,
        launcher_pid=launcher_pid,
        launcher_create_time=launcher_create_time,
        worker_pid=hello.get("worker_pid"),
        worker_create_time=hello.get("worker_process_create_time"),
        expected_command=command,
    )
    hello_parent_pid = hello.get("worker_parent_pid")
    hello_parent_create_time = hello.get("worker_parent_process_create_time")
    if (
        hello_parent_pid != identity.worker_parent_pid
        or not isinstance(hello_parent_create_time, (int, float))
        or isinstance(hello_parent_create_time, bool)
        or not math.isfinite(float(hello_parent_create_time))
        or float(hello_parent_create_time) <= 0
        or abs(
            float(hello_parent_create_time)
            - identity.worker_parent_process_create_time
        )
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError("worker hello parent identity mismatch")
    if (
        identity.delegated is False
        and (
            identity.worker_parent_pid != supervisor_pid
            or abs(
                identity.worker_parent_process_create_time
                - float(supervisor_create_time)
            )
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
        )
    ):
        raise LiveSupervisorError("direct worker is not a child of the supervisor")
    authorization = {
        "schema_version": 1,
        "action": "authorize_live_worker",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "worker_hello_sha256": hello_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "worker_pid": identity.worker_pid,
        "worker_process_create_time": identity.worker_process_create_time,
        "worker_parent_pid": identity.worker_parent_pid,
        "worker_parent_process_create_time": (
            identity.worker_parent_process_create_time
        ),
        "launcher_pid": identity.launcher_pid,
        "launcher_process_create_time": identity.launcher_process_create_time,
        "launcher_delegated": identity.delegated,
        "supervisor_pid": supervisor_pid,
        "supervisor_process_create_time": float(supervisor_create_time),
    }
    revalidated = _bind_launched_worker_identity(
        process,
        launcher_pid=launcher_pid,
        launcher_create_time=launcher_create_time,
        worker_pid=identity.worker_pid,
        worker_create_time=identity.worker_process_create_time,
        expected_command=command,
    )
    if revalidated != identity:
        raise LiveSupervisorError(
            "live Python worker identity changed before authorization"
        )
    # This atomic publication is the final grant action. The child may act as
    # soon as both files exist, so no post-publication safety check is meaningful.
    write_json_with_digest(authorization_path, json_safe(authorization))
    return identity


def _create_cancellation_request(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> Path:
    source_project = Path(str(request["source_project"]))
    stage_project = Path(str(request["stage_root"])) / source_project.name
    cancellation = {
        "schema_version": 1,
        "action": "cancel",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **{
            field: request[field]
            for field in (
                "run_id",
                "lane_id",
                "attempt_id",
                "manifest_sha256",
                "git_head",
                "repository_root",
                "python_executable",
                "python_executable_sha256",
                "python_version",
                "pyarrow_version",
                "psutil_version",
                "ras_commander_version",
                "ras_commander_import_path",
                "stage_root",
            )
        },
        "live_request_path": str(attempt_dir / "request.json"),
        "live_request_sha256": request_sha256,
        "real_engine_lock": request["real_engine_lock"],
        "cancel_receipt_path": str(attempt_dir / "cancel-receipt.json"),
        "stage_project": str(stage_project),
        "plan_number": request["fixture"]["plan_number"],
        "timeout_seconds": request["termination_grace_seconds"],
        "hec_ras_execution_enabled": True,
        "cancel_launch": {
            "launch_nonce": str(uuid.uuid4()),
            "intent_path": str(attempt_dir / "cancel-intent.json"),
            "binding_path": str(attempt_dir / "cancel-launcher.json"),
            "hello_path": str(attempt_dir / "cancel-hello.json"),
            "authorization_path": str(attempt_dir / "cancel-auth.json"),
        },
    }
    path = attempt_dir / "cancel-request.json"
    write_json_with_digest(path, cancellation)
    return path


def _publish_cancel_launch_intent(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> str:
    nonce, intent_path, _, _, _ = _cancel_launch_paths(attempt_dir, request)
    supervisor_pid, supervisor_create_time = _current_supervisor_identity()
    intent = {
        "schema_version": 1,
        "action": "launch_cancel_helper",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "supervisor_pid": supervisor_pid,
        "supervisor_process_create_time": supervisor_create_time,
    }
    return write_json_with_digest(intent_path, json_safe(intent))


def _publish_cancel_launcher_binding(
    process: subprocess.Popen[Any],
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    intent_sha256: str,
    command: Sequence[str],
) -> str:
    nonce, _, binding_path, _, _ = _cancel_launch_paths(attempt_dir, request)
    launcher_pid, launcher_create_time = _live_python_child_identity(process)
    binding = {
        "schema_version": 1,
        "action": "bind_cancel_helper_launcher",
        "bound_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "launcher_pid": launcher_pid,
        "launcher_process_create_time": launcher_create_time,
        "expected_command": [str(part) for part in command],
    }
    return write_json_with_digest(binding_path, json_safe(binding))


def _authorize_cancel_helper(
    process: subprocess.Popen[Any],
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    intent_sha256: str,
    binding_sha256: str,
    command: Sequence[str],
) -> AuthorizedWorkerIdentity:
    nonce, intent_path, binding_path, hello_path, authorization_path = (
        _cancel_launch_paths(attempt_dir, request)
    )
    intent, observed_intent_sha256 = read_json_with_digest(intent_path)
    binding, observed_binding_sha256 = read_json_with_digest(binding_path)
    if (
        observed_intent_sha256 != intent_sha256
        or observed_binding_sha256 != binding_sha256
    ):
        raise LiveSupervisorError("cancellation helper launch evidence changed")
    expected_binding = {
        "schema_version": 1,
        "action": "bind_cancel_helper_launcher",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "expected_command": [str(part) for part in command],
    }
    if any(binding.get(field) != value for field, value in expected_binding.items()):
        raise LiveSupervisorError("cancellation helper launcher binding is invalid")
    launcher_pid = binding.get("launcher_pid")
    launcher_create_time = binding.get("launcher_process_create_time")
    if not _valid_pid_create_time(launcher_pid, launcher_create_time):
        raise LiveSupervisorError("cancellation helper launcher identity is invalid")
    hello, hello_sha256 = _wait_for_worker_hello(
        hello_path,
        timeout_seconds=min(
            60.0,
            max(0.1, float(request["timeout_seconds"])),
        ),
    )
    expected_hello = {
        "schema_version": 1,
        "action": "hello_cancel_helper",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
    }
    if any(hello.get(field) != value for field, value in expected_hello.items()):
        raise LiveSupervisorError("cancellation helper hello identity is invalid")
    identity = _bind_launched_worker_identity(
        process,
        launcher_pid=launcher_pid,
        launcher_create_time=launcher_create_time,
        worker_pid=hello.get("worker_pid"),
        worker_create_time=hello.get("worker_process_create_time"),
        expected_command=command,
    )
    if (
        hello.get("worker_parent_pid") != identity.worker_parent_pid
        or not isinstance(hello.get("worker_parent_process_create_time"), (int, float))
        or isinstance(hello.get("worker_parent_process_create_time"), bool)
        or abs(
            float(hello["worker_parent_process_create_time"])
            - identity.worker_parent_process_create_time
        )
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError("cancellation helper parent identity is invalid")
    supervisor_pid = intent.get("supervisor_pid")
    supervisor_create_time = intent.get("supervisor_process_create_time")
    if not _valid_pid_create_time(supervisor_pid, supervisor_create_time):
        raise LiveSupervisorError("cancellation helper supervisor identity is invalid")
    if (
        not identity.delegated
        and (
            identity.worker_parent_pid != supervisor_pid
            or abs(
                identity.worker_parent_process_create_time
                - float(supervisor_create_time)
            )
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
        )
    ):
        raise LiveSupervisorError("direct cancellation helper parent is invalid")
    revalidated = _bind_launched_worker_identity(
        process,
        launcher_pid=identity.launcher_pid,
        launcher_create_time=identity.launcher_process_create_time,
        worker_pid=identity.worker_pid,
        worker_create_time=identity.worker_process_create_time,
        expected_command=command,
    )
    if revalidated != identity:
        raise LiveSupervisorError("cancellation helper changed before authorization")
    authorization = {
        "schema_version": 1,
        "action": "authorize_cancel_helper",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "worker_hello_sha256": hello_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "worker_pid": identity.worker_pid,
        "worker_process_create_time": identity.worker_process_create_time,
        "worker_parent_pid": identity.worker_parent_pid,
        "worker_parent_process_create_time": (
            identity.worker_parent_process_create_time
        ),
        "launcher_pid": identity.launcher_pid,
        "launcher_process_create_time": identity.launcher_process_create_time,
        "launcher_delegated": identity.delegated,
        "supervisor_pid": supervisor_pid,
        "supervisor_process_create_time": float(supervisor_create_time),
    }
    write_json_with_digest(authorization_path, json_safe(authorization))
    return identity


def _cancel_worker_command(
    request: Mapping[str, Any],
    request_path: Path,
) -> list[str]:
    nonce, _, _, _, _ = _cancel_launch_paths(request_path.parent, request)
    return [
        str(request["python_executable"]),
        "-m",
        "scripts.qualification.execution_evidence.live_cancel_worker",
        "--request",
        str(request_path),
        "--launch-nonce",
        nonce,
    ]


def _run_cancellation_helper(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> tuple[bool, str]:
    cancel_request_path = _create_cancellation_request(
        attempt_dir, request, request_sha256
    )
    cancel_request, cancel_request_sha256 = read_json_with_digest(
        cancel_request_path
    )
    command = _cancel_worker_command(cancel_request, cancel_request_path)
    environment = os.environ.copy()
    repository_root = Path(str(request["repository_root"])).resolve(strict=True)
    environment["PYTHONPATH"] = str(repository_root) + (
        os.pathsep + environment["PYTHONPATH"]
        if environment.get("PYTHONPATH")
        else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    intent_sha256 = _publish_cancel_launch_intent(
        attempt_dir,
        cancel_request,
        cancel_request_sha256,
    )
    with (attempt_dir / "cancel.stdout.log").open("xb") as stdout, (
        attempt_dir / "cancel.stderr.log"
    ).open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
        )
        binding_sha256 = _publish_cancel_launcher_binding(
            process,
            attempt_dir,
            cancel_request,
            cancel_request_sha256,
            intent_sha256,
            command,
        )
        helper_identity = _authorize_cancel_helper(
            process,
            attempt_dir,
            cancel_request,
            cancel_request_sha256,
            intent_sha256,
            binding_sha256,
            command,
        )
        try:
            returncode = process.wait(
                timeout=float(request["termination_grace_seconds"])
            )
        except subprocess.TimeoutExpired:
            _terminate_authorized_worker(
                process,
                helper_identity,
                float(request["termination_grace_seconds"]),
            )
            return False, "cancellation_helper_timed_out"
    if returncode != 0:
        return False, f"cancellation_helper_exit_{returncode}"
    try:
        receipt, _ = read_json_with_digest(attempt_dir / "cancel-receipt.json")
    except Exception as exc:
        return False, f"cancellation_receipt_unverifiable:{type(exc).__name__}"
    for field in ("run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head"):
        if receipt.get(field) != request.get(field):
            return False, f"cancellation_receipt_identity_mismatch:{field}"
    if receipt.get("request_sha256") != cancel_request_sha256:
        return False, "cancellation_receipt_request_digest_mismatch"
    if receipt.get("live_request_sha256") != request_sha256:
        return False, "cancellation_receipt_live_digest_mismatch"
    if cancel_request.get("live_request_sha256") != request_sha256:
        return False, "cancellation_request_live_digest_mismatch"
    if (
        receipt.get("safe_to_terminate_child") is not True
        or receipt.get("quiescence_confirmed") is not True
    ):
        return False, "cancellation_quiescence_unconfirmed"
    if not _inventory_record_is_complete_empty(
        receipt.get("post_global_inventory")
    ):
        return False, "cancellation_global_inventory_unconfirmed"
    return True, "exact_plan_quiescence_confirmed"


def _positive_finite_seconds(value: Any, *, label: str) -> float:
    """Return a strict positive finite duration used by live supervision."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveSupervisorError(f"{label} must be a positive finite number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise LiveSupervisorError(
            f"{label} must be a positive finite number"
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise LiveSupervisorError(f"{label} must be a positive finite number")
    return normalized


def _outer_worker_deadline_seconds(request: Mapping[str, Any]) -> float:
    """Keep the parent deadline strictly outside the engine timeout window.

    The parent reserves independent allowances for staging/preflight and
    postflight evidence work around the engine's finite ``max_runtime``.  Its
    cancellation allowance is never shorter than the core exact-cancellation
    worst case, even if a diagnostic manifest requests a smaller worker-close
    grace.  A final publication margin covers the last atomic receipt write.
    """
    preflight = _positive_finite_seconds(
        request.get("preflight_timeout_seconds"),
        label="request.preflight_timeout_seconds",
    )
    engine_max_runtime = _positive_finite_seconds(
        request.get("timeout_seconds"),
        label="request.timeout_seconds",
    )
    termination_grace = _positive_finite_seconds(
        request.get("termination_grace_seconds"),
        label="request.termination_grace_seconds",
    )
    cancellation_allowance = max(
        termination_grace,
        _MIN_INTERNAL_CANCELLATION_ALLOWANCE_SECONDS,
    )
    postflight = _positive_finite_seconds(
        request.get("postflight_timeout_seconds"),
        label="request.postflight_timeout_seconds",
    )
    receipt_margin = _positive_finite_seconds(
        request.get("supervisor_receipt_margin_seconds"),
        label="request.supervisor_receipt_margin_seconds",
    )
    if receipt_margin != _SUPERVISOR_RECEIPT_MARGIN_SECONDS:
        raise LiveSupervisorError(
            "request supervisor receipt margin disagrees with the harness contract"
        )
    try:
        outer = math.fsum(
            (
                preflight,
                engine_max_runtime,
                cancellation_allowance,
                postflight,
                receipt_margin,
            )
        )
    except OverflowError as exc:
        raise LiveSupervisorError(
            "live worker outer deadline is not finite"
        ) from exc
    if not math.isfinite(outer):
        raise LiveSupervisorError(
            "live worker outer deadline is not finite"
        )
    if outer > _MAX_WINDOWS_SUBPROCESS_WAIT_SECONDS:
        raise LiveSupervisorError(
            "live worker outer deadline exceeds the Windows subprocess-wait range"
        )
    return outer


def _run_live_child(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> LiveChildOutcome:
    """Run one live worker under a strict outer deadline.

    On a timeout, the exact Python child is terminated only after structured
    plan quiescence is positively confirmed.  Otherwise this function returns
    while leaving the child alive.  Exiting the parent ``with`` block closes
    only the parent's log handles; the child may retain its inherited handles
    and continue writing, so callers must not hash or terminalize those logs.
    """
    repository_root = Path(str(request["repository_root"])).resolve(strict=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root) + (
        os.pathsep + environment["PYTHONPATH"]
        if environment.get("PYTHONPATH")
        else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = datetime.now(timezone.utc)
    intent_sha256 = _publish_worker_launch_intent(
        attempt_dir,
        request,
        request_sha256,
    )
    with (attempt_dir / "stdout.log").open("xb") as stdout, (
        attempt_dir / "stderr.log"
    ).open("xb") as stderr:
        command = _worker_command(request, attempt_dir / "request.json")
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
        )
        _publish_worker_launcher_binding(
            process,
            attempt_dir,
            request,
            request_sha256,
            intent_sha256,
            command,
        )
        worker_identity = _authorize_live_child(
            process,
            attempt_dir,
            request,
            request_sha256,
            intent_sha256,
            expected_command=command,
        )
        try:
            outer_deadline = _outer_worker_deadline_seconds(request)
            returncode = process.wait(
                timeout=outer_deadline
            )
        except subprocess.TimeoutExpired:
            cancellation_safe = False
            cancellation_reason = "controller_outer_deadline_exceeded"
            if request["engine"]["execution_api"] == "ras_cmdr":
                try:
                    cancellation_safe, cancellation_reason = (
                        _run_cancellation_helper(
                            attempt_dir,
                            request,
                            request_sha256,
                        )
                    )
                except Exception as exc:
                    cancellation_reason = (
                        "cancellation_helper_error:"
                        f"{type(exc).__name__}:{exc}"
                    )
            if cancellation_safe is True:
                try:
                    _terminate_authorized_worker(
                        process,
                        worker_identity,
                        float(request["termination_grace_seconds"]),
                    )
                except Exception as exc:
                    cancellation_safe = False
                    cancellation_reason = (
                        f"{cancellation_reason};python_child_termination_error:"
                        f"{type(exc).__name__}:{exc}"
                    )
            return LiveChildOutcome(
                pid=worker_identity.worker_pid,
                returncode=124,
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                timed_out=True,
                cancellation_safe=cancellation_safe,
                cancellation_reason=cancellation_reason,
            )
    return LiveChildOutcome(
        pid=worker_identity.worker_pid,
        returncode=returncode,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        timed_out=False,
    )


def _artifact_reference(attempt_dir: Path, path: Path) -> dict[str, str]:
    digest, _ = stable_sha256(path)
    return {
        "relative_path": path.relative_to(attempt_dir).as_posix(),
        "sha256": digest,
    }


def _inventory_record_is_complete_empty(value: Any) -> bool:
    expected_fields = {
        "observed_at",
        "complete",
        "processes",
        "query_errors",
    }
    return (
        isinstance(value, Mapping)
        and set(value) == expected_fields
        and _valid_observed_at(value.get("observed_at"))
        and value.get("complete") is True
        and value.get("query_errors") == []
        and value.get("processes") == []
    )


def _plan_inventory_record_is_complete_empty(
    value: Any,
    *,
    request: Mapping[str, Any],
) -> bool:
    expected_fields = {
        "observed_at",
        "plan_number",
        "project_path",
        "plan_path",
        "tmp_hdf_path",
        "complete",
        "matched",
        "query_errors",
    }
    if not (
        isinstance(value, Mapping)
        and set(value) == expected_fields
        and _valid_observed_at(value.get("observed_at"))
        and value.get("complete") is True
        and value.get("query_errors") == []
        and value.get("matched") == []
        and value.get("plan_number") == request["fixture"]["plan_number"]
    ):
        return False
    expected_project = Path(request["stage_root"]) / Path(
        request["source_project"]
    ).name
    plan_number = request["fixture"]["plan_number"]
    expected_plan = expected_project.with_suffix(f".p{plan_number}")
    expected_tmp_hdf = expected_project.with_suffix(f".p{plan_number}.tmp.hdf")
    try:
        observed_project = lexical_absolute_path(value.get("project_path", ""))
        observed_plan = lexical_absolute_path(value.get("plan_path", ""))
        observed_tmp_hdf = lexical_absolute_path(value.get("tmp_hdf_path", ""))
    except (OSError, ValueError, TypeError):
        return False
    return (
        observed_project == lexical_absolute_path(expected_project)
        and observed_plan == lexical_absolute_path(expected_plan)
        and observed_tmp_hdf == lexical_absolute_path(expected_tmp_hdf)
    )


def _valid_observed_at(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _valid_pid_create_time(pid: Any, create_time: Any) -> bool:
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and isinstance(create_time, (int, float))
        and not isinstance(create_time, bool)
        and math.isfinite(float(create_time))
        and float(create_time) > 0
    )


def _verify_artifact_finalization_evidence(details: Mapping[str, Any]) -> bool:
    """Independently validate serialized RasCmdr finalization evidence."""
    finalized = details.get("result_artifacts_finalized")
    if not isinstance(finalized, bool):
        raise LiveSupervisorError(
            "live RasCmdr result_artifacts_finalized is not boolean"
        )
    if "artifact_finalization_failure" not in details:
        raise LiveSupervisorError(
            "live RasCmdr execution lacks artifact finalization evidence"
        )
    failure = details["artifact_finalization_failure"]
    expected_fields = {"failure_stage", "failure_type", "failure_detail"}
    if finalized:
        if failure is not None:
            raise LiveSupervisorError(
                "finalized live RasCmdr artifacts contain secondary failure metadata"
            )
        return True
    if (
        not isinstance(failure, Mapping)
        or set(failure) != expected_fields
        or failure.get("failure_stage") != "result_artifact_finalization"
        or any(
            not isinstance(failure.get(field), str)
            or not failure[field].strip()
            for field in expected_fields
        )
    ):
        raise LiveSupervisorError(
            "unfinalized live RasCmdr artifacts lack complete secondary failure metadata"
        )
    return False


def _verify_cleanup_record(
    request: Mapping[str, Any],
    cleanup: Any,
    *,
    label: str,
    expected_result_format: str,
    expected_include_message_sidecars: bool,
) -> tuple[str, ...]:
    """Validate one complete exact-target cleanup partition independently."""
    if not isinstance(cleanup, Mapping) or set(cleanup) != _ARTIFACT_CLEANUP_FIELDS:
        raise LiveSupervisorError(f"{label} is not a complete cleanup record")
    plan_number = request["fixture"]["plan_number"]
    if cleanup.get("plan_number") != plan_number:
        raise LiveSupervisorError(f"{label} plan number mismatch")
    if cleanup.get("result_format") != expected_result_format:
        raise LiveSupervisorError(f"{label} result format mismatch")
    if (
        cleanup.get("include_message_sidecars")
        is not expected_include_message_sidecars
    ):
        raise LiveSupervisorError(f"{label} sidecar flag mismatch")

    stage_root = lexical_absolute_path(request["stage_root"])
    stage_project = stage_root / Path(request["source_project"]).name
    known_paths = known_result_paths(stage_project, plan_number)
    allowed = {relative.casefold(): relative for relative in known_paths}
    expected_targets = []
    if expected_result_format in {"hdf", "both"}:
        expected_targets.append(known_paths[0])
    if expected_result_format in {"legacy", "both"}:
        expected_targets.append(known_paths[1])
    if expected_include_message_sidecars:
        expected_targets.extend(known_paths[2:])

    normalized: dict[str, list[str]] = {}
    for field in ("removed_paths", "missing_paths"):
        raw_paths = cleanup.get(field)
        if not isinstance(raw_paths, list) or any(
            not isinstance(raw, str) or not raw for raw in raw_paths
        ):
            raise LiveSupervisorError(f"{label} {field} is not a path array")
        relatives = []
        for raw in raw_paths:
            try:
                candidate = assert_plain_ancestry(raw, stop=stage_root)
                relative = candidate.relative_to(stage_root).as_posix()
            except (OSError, TypeError, ValueError, SnapshotError) as exc:
                raise LiveSupervisorError(
                    f"{label} path escaped the stage: {raw}"
                ) from exc
            canonical = allowed.get(relative.casefold())
            if canonical is None:
                raise LiveSupervisorError(
                    f"{label} path is outside the exact cleanup allowlist: "
                    f"{relative}"
                )
            relatives.append(canonical)
        keys = [relative.casefold() for relative in relatives]
        if len(keys) != len(set(keys)):
            raise LiveSupervisorError(f"{label} {field} contains duplicates")
        normalized[field] = relatives

    removed = {path.casefold() for path in normalized["removed_paths"]}
    missing = {path.casefold() for path in normalized["missing_paths"]}
    if removed & missing:
        raise LiveSupervisorError(
            f"{label} reports a path as both removed and missing"
        )
    if removed | missing != {
        path.casefold() for path in expected_targets
    }:
        raise LiveSupervisorError(f"{label} target set mismatch")
    return tuple(normalized["removed_paths"])


def _verify_execution_cleanup_records(
    request: Mapping[str, Any],
    details: Mapping[str, Any],
) -> tuple[str, ...]:
    expected = request["engine"]["expected_result_format"]
    opposing = "legacy" if expected == "hdf" else "hdf"
    removed = list(
        _verify_cleanup_record(
            request,
            details.get("artifact_preparation_cleanup"),
            label="live artifact preparation cleanup",
            expected_result_format=opposing,
            expected_include_message_sidecars=True,
        )
    )
    finalization = details.get("artifact_finalization_cleanup")
    if details.get("result_artifacts_finalized") is True:
        removed.extend(
            _verify_cleanup_record(
                request,
                finalization,
                label="live artifact finalization cleanup",
                expected_result_format=opposing,
                expected_include_message_sidecars=False,
            )
        )
    elif finalization is not None:
        raise LiveSupervisorError(
            "unfinalized live artifacts contain a finalization cleanup record"
        )
    return tuple(removed)


def _stage_artifact_rows(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    phase: str,
) -> dict[str, Mapping[str, Any]]:
    tables = worker.get("tables")
    artifacts = tables.get("artifacts") if isinstance(tables, Mapping) else None
    stage_root = lexical_absolute_path(request["stage_root"])
    rows = [
        row
        for row in artifacts or []
        if isinstance(row, Mapping)
        and row.get("root_kind") == "stage"
        and row.get("phase") == phase
        and lexical_absolute_path(row.get("root_path", "")) == stage_root
    ]
    snapshot_ids = {row.get("snapshot_id") for row in rows}
    if not rows or len(snapshot_ids) != 1 or None in snapshot_ids:
        raise LiveSupervisorError(
            f"live terminal lacks one complete stage snapshot for {phase}"
        )
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        relative = row.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise LiveSupervisorError(
                f"live terminal {phase} artifact path is invalid"
            )
        key = relative.casefold()
        if key in indexed:
            raise LiveSupervisorError(
                f"live terminal {phase} contains case-colliding artifact rows"
            )
        indexed[key] = row
    return indexed


def _verify_post_execution_artifact_origins(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
) -> None:
    """Reject stale receipts that misclassify generated or changed stage files."""
    before = _stage_artifact_rows(worker, request, "pre_execution")
    replay = request["fixture"].get("replay_artifacts")
    replay_origin = (replay or {}).get("data_origin")
    replay_pins = {
        item["relative_path"].casefold(): item
        for item in (replay or {}).get("files", [])
    }
    stage_metadata = ".ras-commander/stage.json"
    known = {
        path.casefold()
        for path in known_result_paths(
            request["source_project"],
            request["fixture"]["plan_number"],
        )
    }
    required = known | {stage_metadata.casefold()}
    if not required.issubset(before):
        raise LiveSupervisorError(
            "live terminal pre-execution snapshot omits known artifact paths"
        )
    source_origin = request["fixture"]["data_origin"]
    for key, row in before.items():
        if key == stage_metadata.casefold():
            expected_origin = "generated_harness_receipt"
        elif key in replay_pins:
            expected_origin = replay_origin
        else:
            expected_origin = source_origin
        if row.get("data_origin") != expected_origin:
            raise LiveSupervisorError(
                "live terminal pre-execution artifact provenance is invalid: "
                f"{row.get('relative_path')}"
            )
    for phase in ("post_process_hygiene", "post_evidence_inspection"):
        after = _stage_artifact_rows(worker, request, phase)
        if not required.issubset(after):
            raise LiveSupervisorError(
                f"live terminal {phase} snapshot omits known artifact paths"
            )
        for key, row in after.items():
            prior = before.get(key)
            pin = replay_pins.get(key)
            exact_replay = (
                pin is not None
                and row.get("exists") is True
                and row.get("sha256") == pin.get("sha256")
                and row.get("size_bytes") == pin.get("size_bytes")
                and row.get("mtime_ns") == pin.get("mtime_ns")
            )
            unchanged = prior is not None and all(
                prior.get(field) == row.get(field)
                for field in _ARTIFACT_IDENTITY_FIELDS
            )
            if key == stage_metadata.casefold():
                expected_origin = "generated_harness_receipt"
            elif exact_replay:
                expected_origin = replay_origin
            elif unchanged:
                expected_origin = prior.get("data_origin")
            else:
                expected_origin = "staged_execution_output"
            if (
                not isinstance(expected_origin, str)
                or row.get("data_origin") != expected_origin
            ):
                raise LiveSupervisorError(
                    "live terminal post-execution artifact provenance is invalid: "
                    f"{phase}/{row.get('relative_path')}"
                )


def _verify_initial_cleanup_records(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
) -> tuple[str, ...]:
    records = worker.get("initial_state_cleanup")
    if not isinstance(records, list):
        raise LiveSupervisorError(
            "live terminal initial-state cleanup records are unavailable"
        )
    initial_state = request["lane"]["initial_state"]
    selected = request["engine"]["expected_result_format"]
    expected_calls: list[tuple[str, bool]] = []
    if initial_state == "neither":
        expected_calls.append(("both", True))
    elif initial_state == "expected_only":
        expected_calls.append(("legacy" if selected == "hdf" else "hdf", False))
    elif initial_state == "opposing_only":
        expected_calls.append((selected, False))
    if len(records) != len(expected_calls):
        raise LiveSupervisorError(
            "live terminal initial-state cleanup record count is invalid"
        )
    removed = []
    for index, (record, (result_format, include_sidecars)) in enumerate(
        zip(records, expected_calls)
    ):
        removed.extend(
            _verify_cleanup_record(
                request,
                record,
                label=f"live initial-state cleanup {index}",
                expected_result_format=result_format,
                expected_include_message_sidecars=include_sidecars,
            )
        )
    return tuple(removed)


def _verify_r04_cleanup_evidence(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    execution_removed: Sequence[str],
) -> None:
    """Recompute R04 from snapshots and structured cleanup records."""
    initial_removed = _verify_initial_cleanup_records(worker, request)
    published = _stage_artifact_rows(worker, request, "stage_published")
    post = _stage_artifact_rows(worker, request, "post_process_hygiene")
    snapshot_removed = [
        row["relative_path"]
        for key, row in published.items()
        if row.get("exists") is True
        and (key not in post or post[key].get("exists") is not True)
    ]
    plan_number = request["fixture"]["plan_number"]
    known_paths = known_result_paths(request["source_project"], plan_number)
    canonical = {path.casefold(): path for path in known_paths}
    observed_removed = {
        path.casefold(): canonical.get(path.casefold(), path)
        for path in (*snapshot_removed, *initial_removed, *execution_removed)
    }
    invariant_rows = worker.get("tables", {}).get("invariants", [])
    r04_rows = [
        row
        for row in invariant_rows
        if isinstance(row, Mapping) and row.get("invariant_id") == "R04"
    ]
    if len(r04_rows) != 1:
        raise LiveSupervisorError("live terminal requires exactly one R04 row")
    try:
        claimed_expected = json.loads(r04_rows[0].get("expected"))
        claimed_observed = json.loads(r04_rows[0].get("observed"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LiveSupervisorError("live terminal R04 payload is invalid") from exc
    expected_keys = (
        [path.casefold() for path in claimed_expected]
        if isinstance(claimed_expected, list)
        and all(isinstance(path, str) and path for path in claimed_expected)
        else None
    )
    observed_keys = (
        [path.casefold() for path in claimed_observed]
        if isinstance(claimed_observed, list)
        and all(isinstance(path, str) and path for path in claimed_observed)
        else None
    )
    if (
        r04_rows[0].get("status") != "pass"
        or expected_keys is None
        or observed_keys is None
        or len(expected_keys) != len(set(expected_keys))
        or len(observed_keys) != len(set(observed_keys))
        or set(expected_keys)
        != {path.casefold() for path in known_paths}
        or set(observed_keys) != set(observed_removed)
        or any(path.casefold() not in canonical for path in observed_removed.values())
    ):
        raise LiveSupervisorError(
            "live terminal R04 cleanup evidence disagrees with structured proof"
        )


def _verify_failed_inspection_evidence(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    engine: Mapping[str, Any],
    details: Mapping[str, Any],
    *,
    execution_succeeded: bool,
) -> None:
    """Validate the exact diagnostic used when failed-result inspection aborts."""
    evidence = worker.get("evidence")
    tables = worker.get("tables")
    observations = tables.get("observations") if isinstance(tables, Mapping) else None
    diagnostic_claimed = (
        isinstance(evidence, Mapping)
        and evidence.get("evidence_kind") == _FAILED_INSPECTION_EVIDENCE_KIND
    )
    if execution_succeeded and (
        not isinstance(observations, list) or not observations
    ):
        raise LiveSupervisorError(
            "successful live execution lacks nonempty observation evidence"
        )
    if not diagnostic_claimed and observations != []:
        return
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != _FAILED_INSPECTION_EVIDENCE_FIELDS
        or evidence.get("schema_version") != 1
        or evidence.get("evidence_kind") != _FAILED_INSPECTION_EVIDENCE_KIND
        or evidence.get("inspection_api") != "RasCmdr.inspect_execution_evidence"
        or evidence.get("inspection_state") != "failed"
        or evidence.get("failure_type") != "ResultArtifactAmbiguityError"
        or evidence.get("reason_code") not in _RESULT_ARTIFACT_AMBIGUITY_REASONS
        or not isinstance(evidence.get("detail"), str)
        or not evidence["detail"].strip()
        or evidence.get("plan_number") != request["fixture"]["plan_number"]
        or evidence.get("selected_result_format")
        != engine["expected_result_format"]
        or evidence.get("declared_expected_result_format")
        not in {None, "hdf", "legacy"}
        or evidence.get("conflicts") != ["multiple_result_formats_present"]
        or evidence.get("safe_failed_execution") is not True
        or evidence.get("result_artifacts_finalized") is not False
        or evidence.get("runtime_timed_out") is not details.get("runtime_timed_out")
        or observations != []
        or execution_succeeded
        or details.get("result_artifacts_finalized") is not False
    ):
        raise LiveSupervisorError(
            "live failed-inspection evidence contract is invalid"
        )
    try:
        uuid.UUID(str(evidence["evidence_id"]))
        started_at = datetime.fromisoformat(str(evidence["inspection_started_at"]))
        failed_at = datetime.fromisoformat(str(evidence["inspection_failed_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveSupervisorError(
            "live failed-inspection identity or timestamps are invalid"
        ) from exc
    if (
        started_at.tzinfo is None
        or started_at.utcoffset() != timezone.utc.utcoffset(started_at)
        or failed_at.tzinfo is None
        or failed_at.utcoffset() != timezone.utc.utcoffset(failed_at)
        or failed_at < started_at
    ):
        raise LiveSupervisorError(
            "live failed-inspection timestamps are invalid"
        )
    declared_program_version = evidence.get("declared_program_version")
    if declared_program_version is not None and (
        not isinstance(declared_program_version, str)
        or not declared_program_version.strip()
    ):
        raise LiveSupervisorError(
            "live failed-inspection declared version is invalid"
        )
    for field in ("hdf_mtime_ns", "legacy_mtime_ns"):
        value = evidence.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise LiveSupervisorError(
                "live failed-inspection artifact timestamp is invalid"
            )
    stage_project = lexical_absolute_path(
        Path(request["stage_root"]) / Path(request["source_project"]).name
    )
    expected_hdf = lexical_absolute_path(
        stage_project.with_suffix(f".p{request['fixture']['plan_number']}.hdf")
    )
    expected_legacy = lexical_absolute_path(
        stage_project.with_suffix(f".O{request['fixture']['plan_number']}")
    )
    expected_plan = lexical_absolute_path(
        stage_project.with_suffix(f".p{request['fixture']['plan_number']}")
    )
    try:
        plan_bytes = resolve_plain_path(expected_plan, kind="file").read_bytes()
        observed_hdf = resolve_plain_path(evidence.get("hdf_path", ""), kind="file")
        observed_legacy = resolve_plain_path(
            evidence.get("legacy_output_path", ""), kind="file"
        )
        exact_hdf = resolve_plain_path(expected_hdf, kind="file")
        exact_legacy = resolve_plain_path(expected_legacy, kind="file")
        current_hdf_mtime = exact_hdf.stat().st_mtime_ns
        current_legacy_mtime = exact_legacy.stat().st_mtime_ns
    except (OSError, TypeError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError(
            "live failed-inspection exact artifacts are unavailable"
        ) from exc
    if plan_bytes.startswith(b"\xef\xbb\xbf"):
        plan_text = plan_bytes.decode("utf-8-sig", errors="replace")
    else:
        try:
            plan_text = plan_bytes.decode("utf-8")
        except UnicodeDecodeError:
            plan_text = plan_bytes.decode("cp1252")
    staged_program_version = None
    for line in plan_text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "Program Version":
            staged_program_version = value.strip() or None
            break
    if declared_program_version != staged_program_version:
        raise LiveSupervisorError(
            "live failed-inspection declared version disagrees with the staged plan"
        )
    if observed_hdf != exact_hdf or observed_legacy != exact_legacy:
        raise LiveSupervisorError(
            "live failed-inspection artifact paths are invalid"
        )
    hdf_mtime = evidence.get("hdf_mtime_ns")
    legacy_mtime = evidence.get("legacy_mtime_ns")
    reason = evidence["reason_code"]
    if reason == "result_artifact_timestamp_unavailable":
        if hdf_mtime is not None or legacy_mtime is not None:
            raise LiveSupervisorError(
                "timestamp-unavailable ambiguity contains artifact timestamps"
            )
    elif (
        hdf_mtime != current_hdf_mtime
        or legacy_mtime != current_legacy_mtime
    ):
        raise LiveSupervisorError(
            "live failed-inspection artifact timestamps are stale"
        )
    if (
        reason == "legacy_output_timestamp_after_hdf"
        and not legacy_mtime > hdf_mtime
        or reason == "hdf_timestamp_after_legacy_output"
        and not hdf_mtime > legacy_mtime
    ):
        raise LiveSupervisorError(
            "live failed-inspection timestamp ordering contradicts its reason"
        )
    if (
        reason == "legacy_output_timestamp_after_hdf"
        and evidence.get("declared_expected_result_format") != "hdf"
        or reason == "hdf_timestamp_after_legacy_output"
        and evidence.get("declared_expected_result_format") != "legacy"
        or reason == "program_version_unresolved_multiple_formats"
        and evidence.get("declared_expected_result_format") is not None
    ):
        raise LiveSupervisorError(
            "live failed-inspection declared format contradicts its reason"
        )
    failed_events = [
        event
        for event in tables.get("events", [])
        if isinstance(event, Mapping)
        and event.get("event_name") == "execution_evidence_inspection_failed"
    ]
    if len(failed_events) != 1:
        raise LiveSupervisorError(
            "live failed-inspection event proof is not exact"
        )
    event = failed_events[0]
    try:
        event_payload = json.loads(event.get("payload_json"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LiveSupervisorError(
            "live failed-inspection event payload is invalid"
        ) from exc
    if (
        event.get("phase") != "inspection"
        or event.get("status") != "failed"
        or event.get("severity") != "error"
        or event.get("api") != "RasCmdr.inspect_execution_evidence"
        or event.get("reason_code") != evidence["reason_code"]
        or event_payload
        != {
            "evidence_id": evidence["evidence_id"],
            "evidence_kind": evidence["evidence_kind"],
            "failure_type": evidence["failure_type"],
            "reason_code": evidence["reason_code"],
        }
    ):
        raise LiveSupervisorError(
            "live failed-inspection event disagrees with its evidence record"
        )


def _serialized_process_identities(
    value: Any,
    *,
    label: str,
) -> set[tuple[int, float]]:
    """Independently validate serialized public process identities."""
    if not isinstance(value, list):
        raise LiveSupervisorError(f"{label} is not an array")
    identities: list[tuple[int, float]] = []
    for record in value:
        if not isinstance(record, Mapping) or set(record) != _PROCESS_RECORD_FIELDS:
            raise LiveSupervisorError(f"{label} contains a malformed process record")
        pid = record["pid"]
        create_time = record["create_time"]
        if (
            not _valid_pid_create_time(pid, create_time)
            or not isinstance(record["name"], str)
            or not record["name"]
            or not isinstance(record["command_line"], list)
            or any(not isinstance(token, str) for token in record["command_line"])
            or not isinstance(record["tracked"], bool)
            or any(
                optional is not None
                and (not isinstance(optional, str) or not optional)
                for optional in (
                    record["executable_path"],
                    record["working_directory"],
                    record["session_id"],
                )
            )
        ):
            raise LiveSupervisorError(f"{label} contains a malformed process record")
        identities.append((pid, float(create_time)))
    if len(identities) != len(set(identities)):
        raise LiveSupervisorError(f"{label} contains duplicate process identities")
    return set(identities)


def _verify_safe_rascmd_failure(
    request: Mapping[str, Any],
    details: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> None:
    """Verify that a failed modern compute is terminal and process-safe."""
    runtime_timed_out = details.get("runtime_timed_out")
    failure_stage = details.get("failure_stage")
    failure_type = details.get("failure_type")
    failure_detail = details.get("failure_detail")
    if not isinstance(runtime_timed_out, bool) or any(
        not isinstance(value, str) or not value.strip()
        for value in (failure_stage, failure_type, failure_detail)
    ):
        raise LiveSupervisorError(
            "live RasCmdr failure metadata is incomplete"
        )
    if runtime_timed_out and failure_type != "TimeoutError":
        raise LiveSupervisorError(
            "live RasCmdr timeout flag and failure type are inconsistent"
        )

    cancellation = details.get("cancellation_details")
    if (
        not isinstance(cancellation, Mapping)
        or set(cancellation) != _CANCELLATION_DETAIL_FIELDS
        or not isinstance(cancellation.get("cancellation_attempted"), bool)
        or cancellation.get("pre_scan_complete") is not True
        or cancellation.get("post_scan_complete") is not True
        or cancellation.get("quiescence_confirmed") is not True
        or cancellation.get("survivors") != []
        or cancellation.get("query_errors") != []
    ):
        raise LiveSupervisorError(
            "live RasCmdr failure lacks safe exact-cancellation proof"
        )
    started_at = cancellation["started_at"]
    finished_at = cancellation["finished_at"]
    if (
        isinstance(started_at, bool)
        or not isinstance(started_at, (int, float))
        or not math.isfinite(float(started_at))
        or float(started_at) <= 0
        or isinstance(finished_at, bool)
        or not isinstance(finished_at, (int, float))
        or not math.isfinite(float(finished_at))
        or float(finished_at) < float(started_at)
    ):
        raise LiveSupervisorError(
            "live RasCmdr exact-cancellation timestamps are invalid"
        )
    matched = _serialized_process_identities(
        cancellation["matched"], label="live RasCmdr cancellation matched"
    )
    stopped = _serialized_process_identities(
        cancellation["stopped"], label="live RasCmdr cancellation stopped"
    )
    if not matched.issubset(stopped):
        raise LiveSupervisorError(
            "live RasCmdr exact cancellation left an initial match unproved"
        )
    if cancellation["cancellation_attempted"] and not matched:
        raise LiveSupervisorError(
            "live RasCmdr exact cancellation claims signalling without a match"
        )

    expected_project = resolve_plain_path(launch["project_path"], kind="file")
    expected_plan = resolve_plain_path(launch["plan_path"], kind="file")
    expected_tmp_hdf = lexical_absolute_path(
        expected_project.with_suffix(
            f".p{request['fixture']['plan_number']}.tmp.hdf"
        )
    )
    try:
        observed_project = resolve_plain_path(
            cancellation["project_path"], kind="file"
        )
        observed_plan = resolve_plain_path(cancellation["plan_path"], kind="file")
        observed_tmp_hdf = lexical_absolute_path(cancellation["tmp_hdf_path"])
    except (KeyError, OSError, TypeError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError(
            "live RasCmdr exact-cancellation paths are unverifiable"
        ) from exc
    if (
        cancellation["plan_number"] != request["fixture"]["plan_number"]
        or observed_project != expected_project
        or observed_plan != expected_plan
        or observed_tmp_hdf != expected_tmp_hdf
    ):
        raise LiveSupervisorError(
            "live RasCmdr exact-cancellation identity disagrees with the launch"
        )


def _verify_modern_launch_proof(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    details: Mapping[str, Any],
    *,
    execution_succeeded: bool,
) -> None:
    """Reconcile returned modern launch details with the fsynced event."""
    max_runtime = details.get("max_runtime_seconds")
    launch = details.get("launch_details")
    launcher_returncode = details.get("launcher_returncode")
    if (
        isinstance(max_runtime, bool)
        or not isinstance(max_runtime, (int, float))
        or not math.isfinite(float(max_runtime))
        or float(max_runtime) != float(request["timeout_seconds"])
    ):
        raise LiveSupervisorError("live RasCmdr runtime evidence is inconsistent")
    if launcher_returncode is not None and (
        isinstance(launcher_returncode, bool)
        or not isinstance(launcher_returncode, int)
    ):
        raise LiveSupervisorError("live RasCmdr launcher return code is invalid")
    if execution_succeeded and launcher_returncode is None:
        raise LiveSupervisorError(
            "successful live RasCmdr execution lacks a launcher return code"
        )
    if not isinstance(launch, Mapping) or set(launch) != _RASCMD_LAUNCH_DETAIL_FIELDS:
        raise LiveSupervisorError("live RasCmdr launch detail set is incomplete")
    launch_max_runtime = launch.get("max_runtime_seconds")
    if (
        isinstance(launch_max_runtime, bool)
        or not isinstance(launch_max_runtime, (int, float))
        or not math.isfinite(float(launch_max_runtime))
        or float(launch_max_runtime) <= 0
    ):
        raise LiveSupervisorError("live RasCmdr launch runtime is invalid")

    expected_executable = resolve_plain_path(
        request["engine"]["executable"], kind="file"
    )
    expected_project = resolve_plain_path(
        Path(request["stage_root"]) / Path(request["source_project"]).name,
        kind="file",
    )
    plan_number = request["fixture"]["plan_number"]
    expected_plan = resolve_plain_path(
        expected_project.with_suffix(f".p{plan_number}"), kind="file"
    )
    expected_working_directory = resolve_plain_path(
        expected_project.parent, kind="directory"
    )
    try:
        observed_executable = resolve_plain_path(launch["executable_path"], kind="file")
        observed_project = resolve_plain_path(launch["project_path"], kind="file")
        observed_plan = resolve_plain_path(launch["plan_path"], kind="file")
        observed_working_directory = resolve_plain_path(
            launch["working_directory"], kind="directory"
        )
    except (KeyError, OSError, TypeError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError("live RasCmdr launch paths are unverifiable") from exc
    if (
        launch.get("plan_number") != plan_number
        or observed_executable != expected_executable
        or observed_project != expected_project
        or observed_plan != expected_plan
        or observed_working_directory != expected_working_directory
        or launch.get("executable_sha256")
        != request["engine"]["executable_sha256"]
        or not _valid_pid_create_time(
            launch.get("launcher_pid"), launch.get("launcher_create_time")
        )
        or launch.get("launcher_pid") != details.get("launcher_pid")
        or float(launch.get("launcher_create_time"))
        != float(details.get("launcher_create_time"))
        or float(launch_max_runtime) != float(max_runtime)
    ):
        raise LiveSupervisorError("live RasCmdr launch identity is inconsistent")
    logical_argv = [
        str(expected_executable),
        "-c",
        str(expected_project),
        str(expected_plan),
    ]
    if any('"' in token for token in logical_argv):
        raise LiveSupervisorError("live RasCmdr launch path contains a quote")
    raw_command = (
        f'"{logical_argv[0]}" -c "{logical_argv[2]}" "{logical_argv[3]}"'
    )
    if launch.get("command") != raw_command:
        raise LiveSupervisorError("live RasCmdr raw launch command is invalid")

    events = worker.get("tables", {}).get("events")
    launch_events = [
        event
        for event in events or []
        if isinstance(event, Mapping)
        and event.get("event_name") == "engine_process_launched"
    ]
    if len(launch_events) != 1:
        raise LiveSupervisorError("live terminal requires one durable launch event")
    event = launch_events[0]
    try:
        event_at = datetime.fromisoformat(str(event.get("event_at")))
        payload = json.loads(event.get("payload_json"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LiveSupervisorError("live RasCmdr launch event is invalid") from exc
    if event_at.tzinfo is None or event_at.utcoffset() != timezone.utc.utcoffset(event_at):
        raise LiveSupervisorError("live RasCmdr launch event timestamp is not UTC")
    expected_payload = {
        "plan_number": plan_number,
        "raw_command": raw_command,
        "logical_argv": logical_argv,
        "executable_path": str(expected_executable),
        "executable_sha256": request["engine"]["executable_sha256"],
        "project_path": str(expected_project),
        "plan_path": str(expected_plan),
        "cwd": str(expected_working_directory),
        "launch_method": "direct_subprocess_shell_false_exact_executable",
        "launcher_pid": launch["launcher_pid"],
        "launcher_create_time": float(launch["launcher_create_time"]),
        "max_runtime_seconds": float(max_runtime),
    }
    if (
        event.get("phase") != "execution"
        or event.get("status") != "running"
        or event.get("api") != "RasCmdr.compute_plan.on_exec_launched"
        or event.get("pid") != launch["launcher_pid"]
        or payload != expected_payload
    ):
        raise LiveSupervisorError(
            "live RasCmdr launch event disagrees with returned execution details"
        )
    if execution_succeeded:
        if (
            details.get("runtime_timed_out") is not False
            or details.get("failure_stage") is not None
            or details.get("failure_type") is not None
            or details.get("failure_detail") is not None
            or details.get("cancellation_details") is not None
        ):
            raise LiveSupervisorError("live RasCmdr runtime evidence is inconsistent")
    else:
        _verify_safe_rascmd_failure(request, details, launch)


def _verify_worker_execution_proof(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    engine: Mapping[str, Any],
) -> tuple[str, ...]:
    """Revalidate the worker's underlying preflight and execution records."""
    tcu = worker.get("tcu_status")
    ras_version_argument = engine.get("executable") or engine.get(
        "version_requested"
    )
    expected_tcu_fields = {
        "accepted",
        "version",
        "install_dir",
        "registry_key",
        "reason",
        "ras_version_argument",
    }
    if not isinstance(tcu, Mapping) or set(tcu) != expected_tcu_fields or any(
        (
            tcu.get("accepted") is not True,
            tcu.get("version") != ras_version_argument,
            tcu.get("ras_version_argument") != ras_version_argument,
            not isinstance(tcu.get("reason"), str),
            not bool(tcu.get("reason")),
            tcu.get("registry_key") is not None
            and not isinstance(tcu.get("registry_key"), str),
        )
    ):
        raise LiveSupervisorError("live terminal lacks exact successful TCU proof")
    expected_engine_image = engine.get("executable") or engine.get(
        "controller_executable"
    )
    try:
        observed_install_dir = resolve_plain_path(tcu.get("install_dir", ""), kind="directory")
        expected_install_dir = resolve_plain_path(
            Path(expected_engine_image).parent,
            kind="directory",
        )
    except (OSError, TypeError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError(
            "live terminal TCU install directory is unverifiable"
        ) from exc
    if observed_install_dir != expected_install_dir:
        raise LiveSupervisorError("live terminal TCU install directory is invalid")

    process_evidence = worker.get("process_evidence")
    expected_process_fields = {
        "pre_stage_global",
        "pre_setup_plan",
        "pre_execute_global",
        "post_execution_plan",
        "post_execution_global",
    }
    if not isinstance(process_evidence, Mapping) or set(process_evidence) != expected_process_fields:
        raise LiveSupervisorError("live terminal process evidence set is incomplete")
    for field in (
        "pre_stage_global",
        "pre_execute_global",
        "post_execution_global",
    ):
        if not _inventory_record_is_complete_empty(process_evidence[field]):
            raise LiveSupervisorError(
                f"live terminal lacks complete-empty worker inventory: {field}"
            )
    for field in ("pre_setup_plan", "post_execution_plan"):
        if not _plan_inventory_record_is_complete_empty(
            process_evidence[field], request=request
        ):
            raise LiveSupervisorError(
                f"live terminal lacks complete-empty exact-plan inventory: {field}"
            )

    # Direct proof-unit callers predate the enclosing receipt category; the
    # persisted worker path has already validated that field independently.
    terminal = worker.get("terminal_category", "passed")
    if terminal not in {"passed", "execution_failed"}:
        raise LiveSupervisorError(
            "live terminal has no independently verifiable execution semantics"
        )
    execution_succeeded = terminal == "passed"
    execution = worker.get("execution_result")
    if (
        not isinstance(execution, Mapping)
        or execution.get("success") is not execution_succeeded
    ):
        raise LiveSupervisorError(
            "live terminal execution success disagrees with its category"
        )
    details = execution.get("execution_details")
    if not isinstance(details, Mapping):
        raise LiveSupervisorError("live terminal lacks structured execution details")
    common = {
        "execution_api": engine["execution_api"],
        "selected_result_format": engine["expected_result_format"],
        "calculation_attempted": True,
        "solver_quiescence_confirmed": True,
        "actual_engine_provenance_confirmed": True,
    }
    if any(details.get(field) != value for field, value in common.items()):
        raise LiveSupervisorError(
            "live terminal execution details fail calculation/provenance/finalization gates"
        )
    execution_removed = _verify_execution_cleanup_records(request, details)
    if engine["execution_api"] == "ras_cmdr":
        artifacts_finalized = _verify_artifact_finalization_evidence(details)
        _verify_failed_inspection_evidence(
            worker,
            request,
            engine,
            details,
            execution_succeeded=execution_succeeded,
        )
        if execution_succeeded and not artifacts_finalized:
            raise LiveSupervisorError(
                "successful live RasCmdr execution did not finalize result artifacts"
            )
        if details.get("engine_kind") != "executable":
            raise LiveSupervisorError("live RasCmdr engine kind is invalid")
        try:
            selected = resolve_plain_path(
                details.get("selected_executable_path", ""), kind="file"
            )
            expected = resolve_plain_path(engine["executable"], kind="file")
        except (OSError, ValueError, SnapshotError) as exc:
            raise LiveSupervisorError(
                "live RasCmdr executable identity is unverifiable"
            ) from exc
        if (
            selected != expected
            or details.get("selected_executable_sha256")
            != engine.get("executable_sha256")
            or not _valid_pid_create_time(
                details.get("launcher_pid"), details.get("launcher_create_time")
            )
        ):
            raise LiveSupervisorError("live RasCmdr executable provenance is invalid")
        _verify_modern_launch_proof(
            worker,
            request,
            details,
            execution_succeeded=execution_succeeded,
        )
        completion_verified = execution.get("completion_verified")
        if (
            execution_succeeded
            and completion_verified is not True
            or not execution_succeeded
            and not isinstance(completion_verified, bool)
        ):
            raise LiveSupervisorError(
                "live RasCmdr completion claim disagrees with its category"
            )
        return execution_removed

    if details.get("result_artifacts_finalized") is not True:
        raise LiveSupervisorError(
            "live Controller execution did not finalize result artifacts"
        )
    if not execution_succeeded:
        raise LiveSupervisorError(
            "Controller execution failures lack the modern exact-cancellation receipt"
        )

    controller_common = {
        "engine_kind": "controller",
        "requested_controller_version": engine.get("controller_version"),
        "resolved_controller_version": engine.get("resolved_controller_version"),
        "controller_progid": engine.get("controller_progid"),
        "compute_mode": "blocking" if engine.get("blocking") else "poll",
        "watchdog_requested": True,
        "watchdog_started": True,
        "strict_close_requested": True,
        "controller_close_safe": True,
        "owned_process_exit_confirmed": True,
        "post_close_plan_processes_quiescent": True,
        "post_close_global_processes_quiescent": True,
        "controller_executable_sha256": engine.get(
            "controller_executable_sha256"
        ),
    }
    if any(details.get(field) != value for field, value in controller_common.items()):
        raise LiveSupervisorError("live Controller identity/close/watchdog proof is invalid")
    max_runtime = details.get("max_runtime_seconds")
    if (
        isinstance(max_runtime, bool)
        or not isinstance(max_runtime, (int, float))
        or float(max_runtime) != float(request["timeout_seconds"])
        or not _valid_pid_create_time(
            details.get("controller_pid"), details.get("controller_create_time")
        )
    ):
        raise LiveSupervisorError("live Controller timeout/process identity is invalid")
    try:
        selected = resolve_plain_path(
            details.get("controller_executable_path", ""), kind="file"
        )
        expected = resolve_plain_path(engine["controller_executable"], kind="file")
    except (KeyError, OSError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError(
            "live Controller executable identity is unverifiable"
        ) from exc
    if selected != expected:
        raise LiveSupervisorError("live Controller executable path is invalid")
    return execution_removed


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _verify_stage_project_proof(
    worker: Mapping[str, Any],
    *,
    source_project: Path,
    expected_stage_root: Path,
) -> None:
    """Validate the public stage receipt against its persisted stage metadata."""
    stage = worker.get("stage_result")
    expected_fields = {
        "publication_state",
        "execution_readiness",
        "fingerprint_algorithm",
        "source_fingerprint_before",
        "source_fingerprint_after",
        "copied_fingerprint",
        "published_fingerprint",
        "copied_file_count",
        "copied_bytes",
    }
    if not isinstance(stage, Mapping) or set(stage) != expected_fields:
        raise LiveSupervisorError("live terminal stage_project proof is incomplete")
    if (
        stage.get("publication_state") != "published"
        or stage.get("execution_readiness") != "ready"
        or stage.get("fingerprint_algorithm")
        != STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM
    ):
        raise LiveSupervisorError("live terminal stage_project proof is invalid")
    source_before = stage.get("source_fingerprint_before")
    source_after = stage.get("source_fingerprint_after")
    copied = stage.get("copied_fingerprint")
    published = stage.get("published_fingerprint")
    if (
        not all(_valid_sha256(value) for value in (source_before, source_after, copied, published))
        or source_before != source_after
        or source_before != copied
    ):
        raise LiveSupervisorError("live terminal stage_project fingerprint proof is invalid")
    copied_file_count = stage.get("copied_file_count")
    copied_bytes = stage.get("copied_bytes")
    if (
        isinstance(copied_file_count, bool)
        or not isinstance(copied_file_count, int)
        or copied_file_count <= 0
        or isinstance(copied_bytes, bool)
        or not isinstance(copied_bytes, int)
        or copied_bytes < 0
    ):
        raise LiveSupervisorError("live terminal stage_project copy totals are invalid")

    stage_project = expected_stage_root / source_project.name
    try:
        persisted_path = resolve_plain_path(
            expected_stage_root / ".ras-commander" / "stage.json",
            kind="file",
        )
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        json.dumps(persisted, allow_nan=False)
        persisted_source = resolve_plain_path(
            persisted.get("source_project_file", ""),
            kind="file",
        )
        persisted_destination = resolve_plain_path(
            persisted.get("destination_project_file", ""),
            kind="file",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, SnapshotError) as exc:
        raise LiveSupervisorError(
            "live terminal persisted stage_project proof is unreadable"
        ) from exc
    persisted_claims = {
        "schema_version": 1,
        "fingerprint_algorithm": stage["fingerprint_algorithm"],
        "source_fingerprint_before": source_before,
        "source_fingerprint_after": source_after,
        "copied_fingerprint": copied,
        "copied_file_count": copied_file_count,
        "copied_bytes": copied_bytes,
        "execution_readiness": "ready",
    }
    if (
        not isinstance(persisted, Mapping)
        or any(persisted.get(key) != value for key, value in persisted_claims.items())
        or persisted_source != source_project
        or persisted_destination != stage_project
    ):
        raise LiveSupervisorError(
            "live terminal persisted stage_project proof disagrees with the worker"
        )
    artifacts = persisted.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != copied_file_count + 1:
        raise LiveSupervisorError(
            "live terminal persisted stage_project artifact inventory is invalid"
        )
    generated = [
        item
        for item in artifacts
        if isinstance(item, Mapping)
        and item.get("provenance") == "generated_stage_metadata"
    ]
    copied_rows = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and item.get("provenance") == "copied_source"
    ]
    if (
        generated
        != [
            {
                "provenance": "generated_stage_metadata",
                "relative_path": ".ras-commander/stage.json",
            }
        ]
        or len(copied_rows) != copied_file_count
        or any(
            not isinstance(item.get("relative_path"), str)
            or not item["relative_path"]
            or Path(item["relative_path"]).is_absolute()
            or ".." in Path(item["relative_path"]).parts
            or isinstance(item.get("size_bytes"), bool)
            or not isinstance(item.get("size_bytes"), int)
            or item["size_bytes"] < 0
            or not _valid_sha256(item.get("sha256"))
            for item in copied_rows
        )
    ):
        raise LiveSupervisorError(
            "live terminal persisted stage_project artifact inventory is invalid"
        )


def _verify_live_terminal_semantics(
    attempt_dir: Path,
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    lane: Mapping[str, Any],
    fixture: Mapping[str, Any],
    engine: Mapping[str, Any],
    expected_stage_root: Path,
) -> None:
    """Prove a safe worker-authored success or non-reusable execution failure."""
    expected_stage_root = lexical_absolute_path(expected_stage_root)
    source_project = resolve_plain_path(fixture["source_project"], kind="file")
    stage_project = expected_stage_root / source_project.name
    identity = {
        "run_id": request["run_id"],
        "lane_id": lane["lane_id"],
        "attempt_id": request["attempt_id"],
        "manifest_sha256": request["manifest_sha256"],
        "git_head": request["git_head"],
    }
    runtime_fields = (
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "pyarrow_version",
        "psutil_version",
        "ras_commander_version",
        "ras_commander_import_path",
    )
    if request.get("action") != "run" or receipt.get("action") != "run":
        raise LiveSupervisorError("live terminal action is not run")
    if request.get("lane") != dict(lane):
        raise LiveSupervisorError("live request lane identity is stale")
    if request.get("fixture") != dict(fixture):
        raise LiveSupervisorError("live request fixture identity is stale")
    if request.get("engine") != dict(engine):
        raise LiveSupervisorError("live request engine identity is stale")
    for field, expected in identity.items():
        if receipt.get(field) != expected:
            raise LiveSupervisorError(f"live terminal identity mismatch for {field}")
    for field in runtime_fields:
        if receipt.get(field) != request.get(field):
            raise LiveSupervisorError(f"live terminal runtime mismatch for {field}")
    if Path(str(request.get("source_project", ""))) != source_project:
        raise LiveSupervisorError("live terminal source project identity is stale")
    if (
        request.get("source_snapshot_content_fingerprint")
        != fixture.get("source_content_fingerprint")
    ):
        raise LiveSupervisorError("live terminal source content identity is stale")
    if (
        request.get("source_snapshot_content_fingerprint_algorithm")
        != fixture.get("source_content_fingerprint_algorithm")
    ):
        raise LiveSupervisorError("live terminal source algorithm identity is stale")
    if lexical_absolute_path(request.get("stage_root", "")) != expected_stage_root:
        raise LiveSupervisorError("live terminal stage root identity is stale")
    terminal = receipt.get("terminal_category")
    if terminal not in {"passed", "execution_failed"}:
        raise LiveSupervisorError("live terminal category is not verifiable")
    execution_succeeded = terminal == "passed"
    if not execution_succeeded and engine.get("execution_api") != "ras_cmdr":
        raise LiveSupervisorError(
            "only modern exact-cancellation failures can be terminalized"
        )
    if receipt.get("hec_ras_invoked") is not True:
        raise LiveSupervisorError("live terminal lacks real HEC-RAS invocation evidence")
    if receipt.get("supervisor_synthesized") is not False:
        raise LiveSupervisorError("synthetic supervisor terminals are not reusable")
    worker, worker_sha256 = read_json_with_digest(attempt_dir / "worker_receipt.json")
    if receipt.get("worker_receipt_sha256") != worker_sha256:
        raise LiveSupervisorError("live terminal does not bind the worker receipt")
    if worker.get("request_sha256") != receipt.get("request_sha256"):
        raise LiveSupervisorError("worker/live request digest binding is stale")
    if worker.get("tables") != receipt.get("tables"):
        raise LiveSupervisorError("supervisor terminal tables differ from worker tables")
    if worker.get("execution_result") != receipt.get("execution_result"):
        raise LiveSupervisorError(
            "supervisor terminal execution result differs from worker proof"
        )
    _verify_stage_project_proof(
        worker,
        source_project=source_project,
        expected_stage_root=expected_stage_root,
    )
    execution_removed = _verify_worker_execution_proof(worker, request, engine)
    _verify_post_execution_artifact_origins(worker, request)
    _verify_r04_cleanup_evidence(
        worker,
        request,
        execution_removed,
    )
    required = request.get("required_invariants")
    if (
        not isinstance(required, list)
        or len(required) != len(set(required))
        or required != list(lane.get("required_invariants", []))
        or set(required) != _SUPPORTED_LIVE_INVARIANTS
        or receipt.get("required_invariants") != required
    ):
        raise LiveSupervisorError("live terminal required invariant identity is invalid")
    tables = receipt.get("tables")
    if not isinstance(tables, Mapping):
        raise LiveSupervisorError("live terminal has no table mapping")
    invariants = tables.get("invariants")
    if not isinstance(invariants, list) or len(invariants) != len(required):
        raise LiveSupervisorError("live terminal invariant row count is not exact")
    invariant_ids = [row.get("invariant_id") for row in invariants]
    if (
        len(invariant_ids) != len(set(invariant_ids))
        or set(invariant_ids) != set(required)
    ):
        raise LiveSupervisorError("live terminal invariant identities are not exact")
    if execution_succeeded and any(
        row.get("status") != "pass" for row in invariants
    ):
        raise LiveSupervisorError("passing live terminal invariants are not all passes")
    lane_rows = tables.get("lanes")
    if not isinstance(lane_rows, list) or len(lane_rows) != 1:
        raise LiveSupervisorError("live terminal requires exactly one lane row")
    lane_row_record = lane_rows[0]
    lane_identity = {
        "fixture_id": fixture["fixture_id"],
        "plan_type": fixture["plan_type"],
        "plan_number": fixture["plan_number"],
        "source_kind": fixture["source_kind"],
        "source_project": str(source_project),
        "source_content_fingerprint_algorithm": fixture[
            "source_content_fingerprint_algorithm"
        ],
        "source_content_fingerprint": fixture["source_content_fingerprint"],
        "stage_project": str(stage_project),
        "execution_api": engine["execution_api"],
        "engine_id": engine["engine_id"],
        "engine_version_requested": engine["version_requested"],
        "engine_executable": engine.get("executable"),
        "engine_executable_sha256": engine.get("executable_sha256"),
        "initial_state": "neither",
        "expected_terminal_category": "passed",
        "terminal_category": terminal,
    }
    if any(lane_row_record.get(key) != value for key, value in lane_identity.items()):
        raise LiveSupervisorError("live terminal lane identity or stage binding is stale")
    expected_format = engine.get("expected_result_format")
    if (
        lane_row_record.get("expected_result_format") != expected_format
        or lane_row_record.get("selected_result_format") != expected_format
    ):
        raise LiveSupervisorError("live terminal selected the wrong result family")
    observed_flags = (
        lane_row_record.get("final_hdf_exists"),
        lane_row_record.get("final_legacy_exists"),
    )
    if execution_succeeded:
        expected_flags = (
            (True, False) if expected_format == "hdf" else (False, True)
        )
        if observed_flags != expected_flags:
            raise LiveSupervisorError("live terminal final result-family gate failed")
        for field in (
            "all_invariants_passed",
            "source_immutable",
            "process_success",
            "completion_verified",
            "mechanical_completion",
        ):
            if lane_row_record.get(field) is not True:
                raise LiveSupervisorError(f"live terminal lane gate failed: {field}")
    else:
        execution = worker["execution_result"]
        execution_completion = execution.get("completion_verified")
        if not isinstance(execution_completion, bool):
            raise LiveSupervisorError(
                "failed live terminal lacks a boolean API completion claim"
            )
        details = execution["execution_details"]
        failed_inspection = (
            isinstance(worker.get("evidence"), Mapping)
            and worker["evidence"].get("evidence_kind")
            == _FAILED_INSPECTION_EVIDENCE_KIND
        )
        if failed_inspection and observed_flags != (True, True):
            raise LiveSupervisorError(
                "failed-inspection terminal does not expose both result families"
            )
        if details.get("result_artifacts_finalized") is False:
            if any(not isinstance(flag, bool) for flag in observed_flags):
                raise LiveSupervisorError(
                    "unfinalized live terminal has non-boolean result-family evidence"
                )
        else:
            opposing_exists = (
                lane_row_record.get("final_legacy_exists")
                if expected_format == "hdf"
                else lane_row_record.get("final_hdf_exists")
            )
            if opposing_exists is not False:
                raise LiveSupervisorError(
                    "failed live terminal retained an opposing result family"
                )
        if lane_row_record.get("source_immutable") is not True:
            raise LiveSupervisorError(
                "failed live terminal did not preserve its source"
            )
        if lane_row_record.get("process_success") is not False:
            raise LiveSupervisorError(
                "failed live terminal does not explicitly deny process success"
            )
        if lane_row_record.get("completion_verified") is not execution_completion:
            raise LiveSupervisorError(
                "failed live terminal lane disagrees with API completion evidence"
            )
    if not _inventory_record_is_complete_empty(
        receipt.get("supervisor_post_inventory")
    ):
        raise LiveSupervisorError(
            "live terminal lacks complete-empty final supervisor inventory"
        )


def _validate_worker_record(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    outcome: LiveChildOutcome,
) -> tuple[dict[str, Any], str]:
    record_path = attempt_dir / "worker_receipt.json"
    worker, worker_sha256 = read_json_with_digest(record_path)
    if worker.get("schema_version") != 1:
        raise LiveSupervisorError("worker receipt requires schema_version=1")
    for field in ("run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head"):
        if worker.get(field) != request.get(field):
            raise LiveSupervisorError(f"worker receipt identity mismatch for {field}")
    if worker.get("request_sha256") != request_sha256:
        raise LiveSupervisorError("worker receipt does not bind the live request digest")
    terminal = worker.get("terminal_category")
    if terminal not in _WORKER_TERMINALS:
        raise LiveSupervisorError(f"worker claimed unsupported terminal: {terminal!r}")
    claimed_exit = worker.get("worker_exit_code")
    if claimed_exit != _WORKER_TERMINALS[terminal] or claimed_exit != outcome.returncode:
        raise LiveSupervisorError("worker terminal/exit claim disagrees with observed child exit")
    if terminal == "passed" and worker.get("hec_ras_invoked") is not True:
        raise LiveSupervisorError("passing live worker did not affirm real HEC-RAS invocation")
    tables = worker.get("tables")
    if not isinstance(tables, Mapping) or set(tables) != set(SCHEMAS):
        raise LiveSupervisorError("worker receipt tables do not match the closed schema set")
    required = request.get("required_invariants")
    invariant_rows = tables.get("invariants")
    if not isinstance(required, list) or not isinstance(invariant_rows, list):
        raise LiveSupervisorError("worker invariant IDs require array records")
    invariant_ids = [
        row.get("invariant_id") if isinstance(row, Mapping) else None
        for row in invariant_rows
    ]
    if (
        len(required) != len(set(required))
        or len(invariant_ids) != len(set(invariant_ids))
        or set(invariant_ids) != set(required)
        or len(invariant_ids) != len(required)
    ):
        raise LiveSupervisorError(
            "worker invariant IDs must exactly and uniquely match the request"
        )
    for table_name in SCHEMAS:
        rows = tables[table_name]
        if not isinstance(rows, list):
            raise LiveSupervisorError(f"worker {table_name} table is not an array")
        if table_name == "lanes" and len(rows) != 1:
            raise LiveSupervisorError("worker receipt requires exactly one lane row")
        for row in rows:
            if not isinstance(row, Mapping):
                raise LiveSupervisorError(f"worker {table_name} row is not an object")
            for field in ("run_id", "lane_id", "attempt_id"):
                if row.get(field) != request.get(field):
                    raise LiveSupervisorError(
                        f"worker {table_name} identity mismatch for {field}"
                    )
        table_from_rows(table_name, rows)
    lane = tables["lanes"][0]
    for field, expected in (
        ("manifest_sha256", request["manifest_sha256"]),
        ("git_head", request["git_head"]),
        ("terminal_category", terminal),
        ("worker_exit_code", outcome.returncode),
    ):
        if lane.get(field) != expected:
            raise LiveSupervisorError(f"worker lane row mismatch for {field}")
    invariant_status = {
        row["invariant_id"]: row["status"] for row in invariant_rows
    }
    all_rows_pass = bool(invariant_status) and all(
        status == "pass" for status in invariant_status.values()
    )
    required_pass = all(invariant_status.get(item) == "pass" for item in required)
    derived_all_passed = all_rows_pass and required_pass
    if lane.get("all_invariants_passed") is not derived_all_passed:
        raise LiveSupervisorError(
            "worker lane invariant gate disagrees with recorded invariant rows"
        )
    if terminal == "passed" and not derived_all_passed:
        raise LiveSupervisorError("passing worker lacks complete required invariant evidence")
    references = worker.get("referenced_artifacts")
    if not isinstance(references, list):
        raise LiveSupervisorError("worker referenced_artifacts must be an array")
    forbidden = {
        "stdout.log",
        "stderr.log",
        "worker_receipt.json",
        "receipt.json",
        "request.json",
    }
    seen: set[str] = set()
    for item in references:
        if not isinstance(item, Mapping):
            raise LiveSupervisorError("worker artifact reference is not an object")
        relative = item.get("relative_path")
        if (
            not isinstance(relative, str)
            or Path(relative).as_posix().casefold() in forbidden
        ):
            raise LiveSupervisorError("worker referenced a parent-owned or invalid artifact")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise LiveSupervisorError("worker artifact reference escaped the attempt")
        key = candidate.as_posix().casefold()
        if key in seen:
            raise LiveSupervisorError("worker artifact references contain duplicates")
        seen.add(key)
        path = assert_plain_ancestry(attempt_dir / candidate, stop=attempt_dir)
        observed, _ = stable_sha256(path)
        if item.get("sha256") != observed:
            raise LiveSupervisorError("worker artifact reference digest mismatch")
    required_proof_artifacts = {
        "execution_result.json",
        "evidence.json",
        "events.jsonl",
    }
    if not required_proof_artifacts.issubset(seen):
        missing = sorted(required_proof_artifacts - seen)
        raise LiveSupervisorError(
            "worker receipt omits underlying proof artifacts: " + ", ".join(missing)
        )
    execution_record, _ = read_json_with_digest(
        attempt_dir / "execution_result.json"
    )
    if execution_record != worker.get("execution_result"):
        raise LiveSupervisorError(
            "worker execution_result artifact differs from embedded proof"
        )
    evidence_record, _ = read_json_with_digest(attempt_dir / "evidence.json")
    if evidence_record != worker.get("evidence"):
        raise LiveSupervisorError(
            "worker evidence artifact differs from embedded proof"
        )
    event_records = read_event_journal(attempt_dir / "events.jsonl")
    if event_records != tables.get("events"):
        raise LiveSupervisorError(
            "worker event journal differs from embedded event table"
        )
    return worker, worker_sha256


def _finalize_worker_receipt(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    outcome: LiveChildOutcome,
    post_inventory: ProcessInventorySnapshot,
) -> VerifiedAttempt:
    worker, worker_sha256 = _validate_worker_record(
        attempt_dir, request, request_sha256, outcome
    )
    references = list(worker["referenced_artifacts"])
    references.extend(
        _artifact_reference(attempt_dir, attempt_dir / name)
        for name in ("stdout.log", "stderr.log", "worker_receipt.json")
    )
    receipt = {
        **worker,
        "request_sha256": request_sha256,
        "worker_receipt_sha256": worker_sha256,
        "receipt_committed_at": datetime.now(timezone.utc).isoformat(),
        "worker_pid": outcome.pid,
        "worker_exit_code": outcome.returncode,
        "supervisor_synthesized": False,
        "supervisor_post_inventory": post_inventory.raw,
        "referenced_artifacts": references,
    }
    _verify_live_terminal_semantics(
        attempt_dir,
        request,
        receipt,
        lane=request["lane"],
        fixture=request["fixture"],
        engine=request["engine"],
        expected_stage_root=Path(str(request["stage_root"])),
    )
    write_json_with_digest(attempt_dir / "receipt.json", json_safe(receipt))
    return verify_attempt_receipt(attempt_dir)


def _synthesize_failure_receipt(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    outcome: LiveChildOutcome,
    *,
    hygiene_safe: bool,
    post_inventory: ProcessInventorySnapshot | None,
    inventory_error: str | None,
) -> VerifiedAttempt:
    terminal = "timed_out" if outcome.timed_out else "worker_crashed"
    source_project = Path(str(request["source_project"]))
    known_paths = known_result_paths(source_project, request["fixture"]["plan_number"])
    source_after = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_after_failed_live_worker",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=known_paths,
    )
    source_immutable = (
        source_after.fingerprint_algorithm
        == request["source_snapshot_content_fingerprint_algorithm"]
        and source_after.content_fingerprint
        == request["source_snapshot_content_fingerprint"]
        and source_after.metadata_fingerprint
        == request["source_snapshot_metadata_fingerprint"]
    )
    artifact_rows = list(source_after.rows)
    stage_root = Path(str(request["stage_root"]))
    final_hdf = False
    final_legacy = False
    if hygiene_safe and stage_root.is_dir():
        stage_after = snapshot_tree(
            stage_root,
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
            phase="stage_after_failed_live_worker",
            root_kind="stage",
            data_origin="archived_failed_execution",
            known_paths=known_paths,
        )
        artifact_rows.extend(stage_after.rows)
        final_hdf, final_legacy = result_population(
            stage_after.rows,
            project_file=request["source_project"],
            plan_number=request["fixture"]["plan_number"],
        )
    detail = (
        "Live Python worker did not publish a terminal worker receipt; "
        f"process_hygiene={'confirmed' if hygiene_safe else 'uncertain'}"
    )
    event = {
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
        "api": "live_worker",
        "reason_code": terminal,
        "detail": detail,
        "relative_path": None,
        "pid": outcome.pid,
        "payload_json": json.dumps(
            {
                "cancellation_reason": outcome.cancellation_reason,
                "inventory_error": inventory_error,
                "process_hygiene_safe": hygiene_safe,
                "returncode": outcome.returncode,
            },
            sort_keys=True,
            separators=(",", ":"),
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
        detail=detail,
    )
    lane["compute_mode"] = f"live_{request['engine']['execution_api']}"
    references = [
        _artifact_reference(attempt_dir, attempt_dir / "stdout.log"),
        _artifact_reference(attempt_dir, attempt_dir / "stderr.log"),
    ]
    for name in (
        "events.jsonl",
        "cancel-request.json",
        "cancel-receipt.json",
        "cancel.stdout.log",
        "cancel.stderr.log",
    ):
        path = attempt_dir / name
        if path.is_file():
            references.append(_artifact_reference(attempt_dir, path))
    receipt = {
        **{
            field: request[field]
            for field in (
                "schema_version",
                "run_id",
                "lane_id",
                "attempt_id",
                "manifest_sha256",
                "git_head",
            )
        },
        "action": "run",
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
        "hec_ras_invoked": None,
        "hec_ras_invocation_state": "unknown_after_worker_failure",
        "process_hygiene_safe": hygiene_safe,
        "supervisor_post_inventory": None if post_inventory is None else post_inventory.raw,
        "referenced_artifacts": references,
        "tables": {
            "lanes": [lane],
            "artifacts": artifact_rows,
            "observations": [],
            "events": [event],
            "invariants": [],
        },
    }
    write_json_with_digest(attempt_dir / "receipt.json", json_safe(receipt))
    return verify_attempt_receipt(attempt_dir)


def _worker_launch_recovery_gate(
    attempt_dir: Path,
    request: Mapping[str, Any],
    *,
    command_inventories: list[dict[str, Any]] | None = None,
    expected_supervisor_identity: tuple[int, float] | None = None,
) -> tuple[bool, str]:
    """Prove the exact authorized Python worker is absent or never launched."""
    try:
        nonce, intent_path, hello_path, authorization_path = _worker_launch_paths(
            attempt_dir, request
        )
    except Exception as exc:
        return False, f"worker launch metadata is unverifiable: {type(exc).__name__}: {exc}"
    try:
        binding_path = _worker_launcher_path(attempt_dir, request)
    except Exception as exc:
        return False, f"worker launcher metadata is unverifiable: {type(exc).__name__}: {exc}"
    record_paths = (intent_path, binding_path, hello_path, authorization_path)
    digest_paths = tuple(path.with_suffix(".sha256") for path in record_paths)
    if not any(path.exists() for path in (*record_paths, *digest_paths)):
        return True, "worker launch was never initiated"
    intent_digest_path = intent_path.with_suffix(".sha256")
    if intent_path.exists() is not True or intent_digest_path.exists() is not True:
        later_records = (*record_paths[1:], *digest_paths[1:])
        if (
            intent_path.exists() is not True
            or intent_digest_path.exists()
            or any(path.exists() for path in later_records)
        ):
            return False, "worker launch intent publication is incomplete"
        allowed_partial_names = {
            "request.json",
            "request.sha256",
            "worker-launch-intent.json",
        }
        try:
            actual_entries = list(attempt_dir.iterdir())
        except OSError as exc:
            return False, f"partial attempt inventory is unavailable: {exc}"
        if (
            {path.name for path in actual_entries} != allowed_partial_names
            or any(not path.is_file() for path in actual_entries)
        ):
            return False, "partial worker launch attempt contains unexpected records"
        try:
            stage_root = assert_plain_ancestry(Path(str(request["stage_root"])))
            if stage_root.exists() and (
                not stage_root.is_dir() or any(stage_root.iterdir())
            ):
                return False, "partial worker launch attempt has a populated stage"
        except (KeyError, OSError, SnapshotError) as exc:
            return False, f"partial worker launch stage is unverifiable: {exc}"
        try:
            candidate = resolve_plain_path(intent_path, kind="file")
            before = candidate.stat()
            raw_intent = candidate.read_bytes()
            after = candidate.stat()
            partial_intent = json.loads(raw_intent)
        except (OSError, TypeError, ValueError, json.JSONDecodeError, SnapshotError) as exc:
            return False, (
                "partial worker launch intent is unverifiable: "
                f"{type(exc).__name__}: {exc}"
            )
        if (
            (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino)
            != (after.st_size, after.st_mtime_ns, after.st_dev, after.st_ino)
            or not isinstance(partial_intent, Mapping)
            or canonical_json_bytes(dict(partial_intent)) != raw_intent
        ):
            return False, "partial worker launch intent identity is unstable"
        try:
            created_at = datetime.fromisoformat(
                str(partial_intent.get("created_at", ""))
            )
        except ValueError:
            return False, "partial worker launch intent timestamp is invalid"
        if (
            set(partial_intent) != _PARTIAL_WORKER_INTENT_FIELDS
            or created_at.tzinfo is None
            or created_at.utcoffset() != timezone.utc.utcoffset(created_at)
        ):
            return False, "partial worker launch intent schema is invalid"
        try:
            archived_request, request_sha256 = read_json_with_digest(
                attempt_dir / "request.json"
            )
        except Exception as exc:
            return False, (
                "worker launch request is unverifiable: "
                f"{type(exc).__name__}: {exc}"
            )
        partial_expected = {
            "schema_version": 1,
            "action": "launch_live_worker",
            "request_sha256": request_sha256,
            "launch_nonce": nonce,
            "run_id": request.get("run_id"),
            "lane_id": request.get("lane_id"),
            "attempt_id": request.get("attempt_id"),
            "real_engine_lock_token": request.get("real_engine_lock", {}).get(
                "token"
            ),
        }
        if archived_request != request or any(
            partial_intent.get(field) != value
            for field, value in partial_expected.items()
        ):
            return False, "partial worker launch intent identity is unverifiable"
        supervisor_pid = partial_intent.get("supervisor_pid")
        supervisor_create_time = partial_intent.get(
            "supervisor_process_create_time"
        )
        if (
            expected_supervisor_identity is None
            or supervisor_pid != expected_supervisor_identity[0]
            or not isinstance(supervisor_create_time, (int, float))
            or isinstance(supervisor_create_time, bool)
            or abs(
                float(supervisor_create_time)
                - float(expected_supervisor_identity[1])
            )
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
        ):
            return False, "partial intent supervisor does not match the retained lock owner"
        supervisor_state = _inspect_exact_worker_identity(
            supervisor_pid,
            supervisor_create_time,
        )
        if supervisor_state.alive is not False:
            return False, "partial-intent supervisor is alive or unverifiable"
        command_safe, command_detail, command_inventory = _worker_command_recovery_gate(
            _worker_command(request, attempt_dir / "request.json")
        )
        command_inventory["partial_intent_supervisor_identity"] = {
            "pid": supervisor_pid,
            "create_time": float(supervisor_create_time),
        }
        command_inventory["retained_lock_owner_identity"] = {
            "pid": expected_supervisor_identity[0],
            "create_time": float(expected_supervisor_identity[1]),
        }
        command_inventory["supervisor_lock_identity_match"] = True
        if command_inventories is not None:
            command_inventories.append(command_inventory)
        if not command_safe:
            return False, command_detail
        return (
            True,
            "partial worker launch intent publication observed; exact "
            f"supervisor and worker command are currently absent: {command_detail}",
        )
    try:
        archived_request, request_sha256 = read_json_with_digest(
            attempt_dir / "request.json"
        )
        if archived_request != request:
            return False, "worker launch request identity changed"
        intent, intent_sha256 = read_json_with_digest(intent_path)
    except Exception as exc:
        return False, f"worker launch intent is unverifiable: {type(exc).__name__}: {exc}"
    intent_expected = {
        "schema_version": 1,
        "action": "launch_live_worker",
        "request_sha256": request_sha256,
        "launch_nonce": nonce,
        "run_id": request.get("run_id"),
        "lane_id": request.get("lane_id"),
        "attempt_id": request.get("attempt_id"),
        "real_engine_lock_token": request.get("real_engine_lock", {}).get("token"),
    }
    if any(intent.get(field) != value for field, value in intent_expected.items()):
        return False, "worker launch intent identity is unverifiable"
    supervisor_pid = intent.get("supervisor_pid")
    supervisor_create_time = intent.get("supervisor_process_create_time")
    if not _valid_pid_create_time(supervisor_pid, supervisor_create_time):
        return False, "worker launch intent supervisor identity is unverifiable"
    if not binding_path.exists() or not binding_path.with_suffix(".sha256").exists():
        return False, "worker launcher binding publication is incomplete"
    try:
        binding, binding_sha256 = read_json_with_digest(binding_path)
    except Exception as exc:
        return False, f"worker launcher binding is unverifiable: {type(exc).__name__}: {exc}"
    binding_expected = {
        "schema_version": 1,
        "action": "bind_live_worker_launcher",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_nonce": nonce,
        "run_id": request.get("run_id"),
        "lane_id": request.get("lane_id"),
        "attempt_id": request.get("attempt_id"),
        "real_engine_lock_token": request.get("real_engine_lock", {}).get("token"),
        "expected_command": _worker_command(request, attempt_dir / "request.json"),
    }
    if any(binding.get(field) != value for field, value in binding_expected.items()):
        return False, "worker launcher binding identity is unverifiable"
    bound_launcher_pid = binding.get("launcher_pid")
    bound_launcher_create_time = binding.get("launcher_process_create_time")
    if not _valid_pid_create_time(
        bound_launcher_pid, bound_launcher_create_time
    ):
        return False, "worker launcher binding lacks exact process identity"
    if hello_path.exists() is not True or hello_path.with_suffix(".sha256").exists() is not True:
        return False, "worker launch began but exact worker identity is unverifiable"
    try:
        hello, hello_sha256 = read_json_with_digest(hello_path)
    except Exception as exc:
        return False, f"worker hello is unverifiable: {type(exc).__name__}: {exc}"
    hello_expected = {
        "schema_version": 1,
        "action": "hello_live_worker",
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": nonce,
        "run_id": request.get("run_id"),
        "lane_id": request.get("lane_id"),
        "attempt_id": request.get("attempt_id"),
    }
    if any(hello.get(field) != value for field, value in hello_expected.items()):
        return False, "worker hello identity is unverifiable"
    pid = hello.get("worker_pid")
    create_time = hello.get("worker_process_create_time")
    parent_pid = hello.get("worker_parent_pid")
    parent_create_time = hello.get("worker_parent_process_create_time")
    if not _valid_pid_create_time(pid, create_time) or not _valid_pid_create_time(
        parent_pid, parent_create_time
    ):
        return False, "worker hello lacks an exact PID/create-time identity"
    authorization_present = authorization_path.exists() or authorization_path.with_suffix(
        ".sha256"
    ).exists()
    if authorization_present:
        if not (
            authorization_path.exists()
            and authorization_path.with_suffix(".sha256").exists()
        ):
            return False, "worker authorization publication is incomplete"
        try:
            authorization, _ = read_json_with_digest(authorization_path)
        except Exception as exc:
            return False, f"worker authorization is unverifiable: {type(exc).__name__}: {exc}"
        authorization_expected = {
            "schema_version": 1,
            "action": "authorize_live_worker",
            "request_sha256": request_sha256,
            "launch_intent_sha256": intent_sha256,
            "launch_binding_sha256": binding_sha256,
            "worker_hello_sha256": hello_sha256,
            "launch_nonce": nonce,
            "run_id": request.get("run_id"),
            "lane_id": request.get("lane_id"),
            "attempt_id": request.get("attempt_id"),
            "real_engine_lock_token": request.get("real_engine_lock", {}).get("token"),
            "worker_pid": pid,
            "worker_parent_pid": parent_pid,
            "supervisor_pid": supervisor_pid,
        }
        if any(
            authorization.get(field) != value
            for field, value in authorization_expected.items()
        ):
            return False, "worker authorization identity is unverifiable"
        float_identity_fields = {
            "worker_process_create_time": create_time,
            "worker_parent_process_create_time": parent_create_time,
            "supervisor_process_create_time": supervisor_create_time,
        }
        if any(
            not isinstance(authorization.get(field), (int, float))
            or isinstance(authorization.get(field), bool)
            or abs(float(authorization[field]) - float(value))
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
            for field, value in float_identity_fields.items()
        ):
            return False, "worker authorization process times are unverifiable"
        launcher_pid = authorization.get("launcher_pid")
        launcher_create_time = authorization.get("launcher_process_create_time")
        launcher_delegated = authorization.get("launcher_delegated")
        if (
            not _valid_pid_create_time(launcher_pid, launcher_create_time)
            or not isinstance(launcher_delegated, bool)
            or launcher_pid != bound_launcher_pid
            or abs(
                float(launcher_create_time) - float(bound_launcher_create_time)
            )
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
            or (
                launcher_delegated
                and (
                    launcher_pid != parent_pid
                    or abs(float(launcher_create_time) - float(parent_create_time))
                    > _WORKER_IDENTITY_TOLERANCE_SECONDS
                )
            )
            or (
                not launcher_delegated
                and (
                    launcher_pid != pid
                    or abs(float(launcher_create_time) - float(create_time))
                    > _WORKER_IDENTITY_TOLERANCE_SECONDS
                    or parent_pid != supervisor_pid
                    or abs(float(parent_create_time) - float(supervisor_create_time))
                    > _WORKER_IDENTITY_TOLERANCE_SECONDS
                )
            )
        ):
            return False, "worker authorization launcher identity is unverifiable"
    else:
        worker_is_bound_launcher = (
            pid == bound_launcher_pid
            and abs(float(create_time) - float(bound_launcher_create_time))
            <= _WORKER_IDENTITY_TOLERANCE_SECONDS
        )
        parent_is_bound_launcher = (
            parent_pid == bound_launcher_pid
            and abs(float(parent_create_time) - float(bound_launcher_create_time))
            <= _WORKER_IDENTITY_TOLERANCE_SECONDS
        )
        parent_is_supervisor = (
            parent_pid == supervisor_pid
            and abs(float(parent_create_time) - float(supervisor_create_time))
            <= _WORKER_IDENTITY_TOLERANCE_SECONDS
        )
        if worker_is_bound_launcher and parent_is_supervisor:
            launcher_delegated = False
        elif parent_is_bound_launcher and not worker_is_bound_launcher:
            launcher_delegated = True
        else:
            return False, "pre-authorization worker/launcher relationship is unverifiable"
        launcher_pid = bound_launcher_pid
        launcher_create_time = bound_launcher_create_time
    state = _inspect_exact_worker_identity(pid, float(create_time))
    if state.alive is True:
        return False, "exact authorized Python worker is still alive"
    if state.alive is None:
        return False, f"exact Python worker identity is unverifiable: {state.reason_code}"
    if launcher_delegated:
        launcher_state = _inspect_exact_worker_identity(
            launcher_pid, float(launcher_create_time)
        )
        if launcher_state.alive is True:
            return False, "exact delegated Python launcher is still alive"
        if launcher_state.alive is None:
            return (
                False,
                "exact delegated Python launcher identity is unverifiable: "
                f"{launcher_state.reason_code}",
            )
        return (
            True,
            "exact Python worker and delegated launcher are absent: "
            f"{state.reason_code};{launcher_state.reason_code}",
        )
    return True, f"exact direct Python worker is absent: {state.reason_code}"


def _cancel_launch_recovery_gate(
    attempt_dir: Path,
    live_request: Mapping[str, Any],
) -> tuple[bool, str]:
    """Prove an exact cancellation helper and its launcher are absent."""
    cancel_request_path = attempt_dir / "cancel-request.json"
    names = (
        "cancel-intent.json",
        "cancel-launcher.json",
        "cancel-hello.json",
        "cancel-auth.json",
    )
    paths = tuple(attempt_dir / name for name in names)
    digests = tuple(path.with_suffix(".sha256") for path in paths)
    if not any(path.exists() for path in (*paths, *digests)):
        return True, "cancellation helper launch was never initiated"
    try:
        cancel_request, cancel_request_sha256 = read_json_with_digest(
            cancel_request_path
        )
        nonce, intent_path, binding_path, hello_path, authorization_path = (
            _cancel_launch_paths(attempt_dir, cancel_request)
        )
    except Exception as exc:
        return False, f"cancellation launch metadata is unverifiable: {type(exc).__name__}: {exc}"
    if cancel_request.get("live_request_sha256") != stable_sha256(
        attempt_dir / "request.json"
    )[0]:
        return False, "cancellation helper does not bind the live request"
    if any(
        cancel_request.get(field) != live_request.get(field)
        for field in ("run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head")
    ):
        return False, "cancellation helper request identity is unverifiable"
    for path, label in (
        (intent_path, "intent"),
        (binding_path, "launcher binding"),
        (hello_path, "hello"),
    ):
        if not path.exists() or not path.with_suffix(".sha256").exists():
            return False, f"cancellation helper {label} publication is incomplete"
    try:
        intent, intent_sha256 = read_json_with_digest(intent_path)
        binding, binding_sha256 = read_json_with_digest(binding_path)
        hello, hello_sha256 = read_json_with_digest(hello_path)
    except Exception as exc:
        return False, f"cancellation helper launch evidence is unverifiable: {type(exc).__name__}: {exc}"
    common = {
        "request_sha256": cancel_request_sha256,
        "launch_nonce": nonce,
        "run_id": live_request.get("run_id"),
        "lane_id": live_request.get("lane_id"),
        "attempt_id": live_request.get("attempt_id"),
        "real_engine_lock_token": live_request.get("real_engine_lock", {}).get("token"),
    }
    for record, expected in (
        (intent, {"schema_version": 1, "action": "launch_cancel_helper", **common}),
        (
            binding,
            {
                "schema_version": 1,
                "action": "bind_cancel_helper_launcher",
                "launch_intent_sha256": intent_sha256,
                **common,
            },
        ),
        (
            hello,
            {
                "schema_version": 1,
                "action": "hello_cancel_helper",
                "launch_intent_sha256": intent_sha256,
                "launch_binding_sha256": binding_sha256,
                **common,
            },
        ),
    ):
        if any(record.get(field) != value for field, value in expected.items()):
            return False, "cancellation helper launch identity is unverifiable"
    if binding.get("expected_command") != _cancel_worker_command(
        cancel_request,
        cancel_request_path,
    ):
        return False, "cancellation helper expected command is unverifiable"
    supervisor_pid = intent.get("supervisor_pid")
    supervisor_create_time = intent.get("supervisor_process_create_time")
    launcher_pid = binding.get("launcher_pid")
    launcher_create_time = binding.get("launcher_process_create_time")
    worker_pid = hello.get("worker_pid")
    worker_create_time = hello.get("worker_process_create_time")
    parent_pid = hello.get("worker_parent_pid")
    parent_create_time = hello.get("worker_parent_process_create_time")
    if not all(
        _valid_pid_create_time(pid, create_time)
        for pid, create_time in (
            (supervisor_pid, supervisor_create_time),
            (launcher_pid, launcher_create_time),
            (worker_pid, worker_create_time),
            (parent_pid, parent_create_time),
        )
    ):
        return False, "cancellation helper process identities are unverifiable"
    direct = (
        worker_pid == launcher_pid
        and abs(float(worker_create_time) - float(launcher_create_time))
        <= _WORKER_IDENTITY_TOLERANCE_SECONDS
        and parent_pid == supervisor_pid
        and abs(float(parent_create_time) - float(supervisor_create_time))
        <= _WORKER_IDENTITY_TOLERANCE_SECONDS
    )
    delegated = (
        worker_pid != launcher_pid
        and parent_pid == launcher_pid
        and abs(float(parent_create_time) - float(launcher_create_time))
        <= _WORKER_IDENTITY_TOLERANCE_SECONDS
    )
    if not direct and not delegated:
        return False, "cancellation helper/launcher relationship is unverifiable"
    authorization_present = authorization_path.exists() or authorization_path.with_suffix(
        ".sha256"
    ).exists()
    if authorization_present:
        if not authorization_path.exists() or not authorization_path.with_suffix(
            ".sha256"
        ).exists():
            return False, "cancellation authorization publication is incomplete"
        try:
            authorization, _ = read_json_with_digest(authorization_path)
        except Exception as exc:
            return False, f"cancellation authorization is unverifiable: {type(exc).__name__}: {exc}"
        expected = {
            "schema_version": 1,
            "action": "authorize_cancel_helper",
            "launch_intent_sha256": intent_sha256,
            "launch_binding_sha256": binding_sha256,
            "worker_hello_sha256": hello_sha256,
            **common,
            "worker_pid": worker_pid,
            "worker_parent_pid": parent_pid,
            "launcher_pid": launcher_pid,
            "supervisor_pid": supervisor_pid,
        }
        if any(authorization.get(field) != value for field, value in expected.items()):
            return False, "cancellation authorization identity is unverifiable"
        if authorization.get("launcher_delegated") is not delegated:
            return False, "cancellation authorization delegation is unverifiable"
        float_fields = {
            "worker_process_create_time": worker_create_time,
            "worker_parent_process_create_time": parent_create_time,
            "launcher_process_create_time": launcher_create_time,
            "supervisor_process_create_time": supervisor_create_time,
        }
        if any(
            not isinstance(authorization.get(field), (int, float))
            or isinstance(authorization.get(field), bool)
            or abs(float(authorization[field]) - float(value))
            > _WORKER_IDENTITY_TOLERANCE_SECONDS
            for field, value in float_fields.items()
        ):
            return False, "cancellation authorization process times are unverifiable"
    worker_state = _inspect_exact_worker_identity(worker_pid, float(worker_create_time))
    if worker_state.alive is not False:
        return False, "exact cancellation helper is alive or unverifiable"
    if delegated:
        launcher_state = _inspect_exact_worker_identity(
            launcher_pid, float(launcher_create_time)
        )
        if launcher_state.alive is not False:
            return False, "exact cancellation launcher is alive or unverifiable"
    return True, "exact cancellation helper and launcher are absent"


def _supervision_recovery_gate(
    attempt_dir: Path,
    request: Mapping[str, Any],
    *,
    expected_supervisor_identity: tuple[int, float] | None = None,
) -> RecoveryGateOutcome:
    """Independently reprove source immutability and global quiescence.

    This is the sole parent-owned host-safety proof before terminalization or
    host-lock release.  It never publishes a terminal receipt.
    """
    command_inventories: list[dict[str, Any]] = []
    worker_safe, worker_detail = _worker_launch_recovery_gate(
        attempt_dir,
        request,
        command_inventories=command_inventories,
        expected_supervisor_identity=expected_supervisor_identity,
    )
    worker_command_inventory = (
        command_inventories[0] if command_inventories else None
    )
    if not worker_safe:
        return RecoveryGateOutcome(
            False,
            worker_detail,
            worker_command_inventory=worker_command_inventory,
        )
    cancel_safe, cancel_detail = _cancel_launch_recovery_gate(attempt_dir, request)
    if not cancel_safe:
        return RecoveryGateOutcome(
            False,
            cancel_detail,
            worker_command_inventory=worker_command_inventory,
        )
    try:
        source_project = resolve_plain_path(request["source_project"], kind="file")
        source_after = snapshot_tree(
            source_project.parent,
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
            phase="source_after_supervision",
            root_kind="source",
            data_origin=request["fixture"]["data_origin"],
            known_paths=known_result_paths(
                source_project, request["fixture"]["plan_number"]
            ),
        )
        if (
            source_after.fingerprint_algorithm
            != request["source_snapshot_content_fingerprint_algorithm"]
            or source_after.content_fingerprint
            != request["source_snapshot_content_fingerprint"]
            or source_after.metadata_fingerprint
            != request["source_snapshot_metadata_fingerprint"]
        ):
            return RecoveryGateOutcome(
                False,
                "source snapshot drifted",
                worker_command_inventory=worker_command_inventory,
            )
        source_proof = {
            "fingerprint_algorithm": source_after.fingerprint_algorithm,
            "content_fingerprint": source_after.content_fingerprint,
            "metadata_fingerprint": source_after.metadata_fingerprint,
            "expected_content_fingerprint": request[
                "source_snapshot_content_fingerprint"
            ],
            "expected_fingerprint_algorithm": request[
                "source_snapshot_content_fingerprint_algorithm"
            ],
            "expected_metadata_fingerprint": request[
                "source_snapshot_metadata_fingerprint"
            ],
        }
        inventory = _strict_process_inventory()
        if inventory.records:
            return RecoveryGateOutcome(
                False,
                "global HEC-RAS process inventory is not empty",
                inventory,
                worker_command_inventory=worker_command_inventory,
            )
    except Exception as exc:
        return RecoveryGateOutcome(
            False,
            f"recovery proof failed: {type(exc).__name__}: {exc}",
            worker_command_inventory=worker_command_inventory,
        )
    # A failed supervisor must not have committed a terminal.  An unexpected
    # receipt is itself tampering/uncertainty and therefore retains the lock.
    if (attempt_dir / "receipt.json").exists() or (
        attempt_dir / "receipt.sha256"
    ).exists():
        return RecoveryGateOutcome(
            False,
            "unexpected terminal receipt exists after supervision failure",
            inventory,
            worker_command_inventory=worker_command_inventory,
        )
    return RecoveryGateOutcome(
        True,
        f"{worker_detail}; source and global process hygiene reproved",
        inventory,
        source_proof,
        worker_command_inventory,
    )


def supervise_live_request(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> SupervisedAttempt:
    outcome = _run_live_child(attempt_dir, request, request_sha256)
    if outcome.timed_out and outcome.cancellation_safe is not True:
        return SupervisedAttempt(
            verified=None,
            hygiene_safe=False,
            detail=outcome.cancellation_reason or "timeout quiescence is unconfirmed",
        )
    post_inventory: ProcessInventorySnapshot | None = None
    inventory_error: str | None = None
    try:
        post_inventory = _strict_process_inventory()
        post_empty = not post_inventory.records
    except Exception as exc:
        post_empty = False
        inventory_error = f"{type(exc).__name__}: {exc}"
    hygiene_safe = post_empty and (
        not outcome.timed_out or outcome.cancellation_safe is True
    )
    worker_record_exists = (attempt_dir / "worker_receipt.json").is_file() or (
        attempt_dir / "worker_receipt.sha256"
    ).is_file()
    if worker_record_exists and not outcome.timed_out:
        if not hygiene_safe or post_inventory is None:
            return SupervisedAttempt(
                verified=None,
                hygiene_safe=False,
                detail=inventory_error or "post-worker process inventory is not empty",
            )
        recovery = _supervision_recovery_gate(attempt_dir, request)
        if not recovery.safe_to_release or recovery.inventory is None:
            return SupervisedAttempt(
                verified=None,
                hygiene_safe=False,
                detail=recovery.detail,
            )
        verified = _finalize_worker_receipt(
            attempt_dir,
            request,
            request_sha256,
            outcome,
            recovery.inventory,
        )
        return SupervisedAttempt(verified=verified, hygiene_safe=True)
    if not hygiene_safe or post_inventory is None:
        return SupervisedAttempt(
            verified=None,
            hygiene_safe=False,
            detail=inventory_error or "post-worker process inventory is not empty",
        )
    recovery = _supervision_recovery_gate(attempt_dir, request)
    if not recovery.safe_to_release or recovery.inventory is None:
        return SupervisedAttempt(
            verified=None,
            hygiene_safe=False,
            detail=recovery.detail,
        )
    verified = _synthesize_failure_receipt(
        attempt_dir,
        request,
        request_sha256,
        outcome,
        hygiene_safe=True,
        post_inventory=recovery.inventory,
        inventory_error=inventory_error,
    )
    return SupervisedAttempt(
        verified=verified,
        hygiene_safe=True,
    )


def _lane_has_verified_terminal(context: RunContext, lane_id: str) -> bool:
    lane, fixture, engine = select_lane(context, lane_id)
    lexical_lane_root = context.run_root / "attempts" / lane_id
    if not lexical_lane_root.is_dir():
        return False
    try:
        run_root = resolve_plain_path(context.run_root, kind="directory")
        lane_root = resolve_plain_path(lexical_lane_root, kind="directory")
        lane_root.relative_to(run_root)
    except (OSError, ValueError, SnapshotError):
        return False
    for child in sorted(lane_root.iterdir(), key=lambda path: path.name.casefold()):
        if not child.is_dir():
            continue
        try:
            child = resolve_plain_path(child, kind="directory")
            child.relative_to(lane_root)
        except (OSError, ValueError, SnapshotError):
            continue
        try:
            verified = verify_attempt_receipt(child)
        except Exception:
            continue
        if verified.receipt.get("terminal_category") != "passed":
            # A safely terminalized execution failure is audit evidence, not a
            # reusable qualification success. Resume must always retry it.
            continue
        request = verified.request
        current_request_identity = {
            "run_id": context.descriptor["run_id"],
            "lane_id": lane_id,
            "manifest_sha256": context.manifest["manifest_sha256"],
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
        }
        if any(
            request.get(field) != expected
            for field, expected in current_request_identity.items()
        ):
            continue
        try:
            current_source = _source_snapshot(
                context,
                lane_id=lane_id,
                attempt_id=request["attempt_id"],
                source_project=resolve_plain_path(
                    fixture["source_project"], kind="file"
                ),
            )
        except Exception:
            continue
        if (
            current_source.fingerprint_algorithm
            != request.get("source_snapshot_content_fingerprint_algorithm")
            or current_source.content_fingerprint
            != request.get("source_snapshot_content_fingerprint")
            or current_source.metadata_fingerprint
            != request.get("source_snapshot_metadata_fingerprint")
        ):
            continue
        expected_stage_root = (
            Path(context.descriptor["execution_run_root"])
            / lane_id
            / request["attempt_id"]
            / "stage"
        )
        try:
            _verify_live_terminal_semantics(
                child,
                request,
                verified.receipt,
                lane=lane,
                fixture=fixture,
                engine=engine,
                expected_stage_root=expected_stage_root,
            )
        except Exception:
            continue
        else:
            return True
    return False


def execute_live_action(
    run_root: str | Path,
    *,
    acknowledge_real_ras: bool,
    lane_ids: Iterable[str] | None = None,
    phase: str | None = None,
    resume: bool = False,
) -> tuple[VerifiedAttempt, ...]:
    if not acknowledge_real_ras:
        raise LiveSupervisorError("live execution requires --ack-real-ras")
    context = load_run(run_root)
    selected = _select_live_lanes(
        context,
        lane_ids=lane_ids,
        phase=phase,
    )
    # Repository/runtime binding is a prerequisite for trusting historical
    # receipts.  A resume no-op must not bypass the clean-HEAD gate.
    _bind_live_context(context)
    if resume:
        selected = [
            lane_id
            for lane_id in selected
            if not _lane_has_verified_terminal(context, lane_id)
        ]
        if not selected:
            return ()
    _require_strict_live_api_contracts(context, selected)
    for lane_id in selected:
        _validate_live_attempt_path_budget(context.run_root, lane_id)
    results: list[VerifiedAttempt] = []
    with ExclusiveQualificationLock(
        context.run_root / "run.lock",
        kind="run",
        run_id=context.descriptor["run_id"],
        git_head=context.descriptor["git_head"],
    ):
        for lane_id in selected:
            lane_root = context.run_root / "attempts" / lane_id
            with ExclusiveQualificationLock(
                lane_root / "lane.lock",
                kind="lane",
                run_id=context.descriptor["run_id"],
                lane_id=lane_id,
                git_head=context.descriptor["git_head"],
            ):
                attempt_id = str(uuid.uuid4())
                host_lock = ExclusiveQualificationLock(
                    _host_lock_path(),
                    kind="real_engine",
                    run_id=context.descriptor["run_id"],
                    lane_id=lane_id,
                    attempt_id=attempt_id,
                    git_head=context.descriptor["git_head"],
                )
                host_payload = host_lock.acquire()
                release_host = True
                try:
                    baseline = _strict_process_inventory()
                    if baseline.records:
                        raise LiveSupervisorError(
                            "preflight found an existing HEC-RAS process; refusing live execution"
                        )
                    attempt_dir, request, request_sha256 = create_live_attempt_request(
                        context,
                        lane_id=lane_id,
                        attempt_id=attempt_id,
                        process_baseline=baseline,
                        real_engine_lock_path=host_lock.path,
                        real_engine_lock_payload=host_payload,
                    )
                    # From this point onward a Python worker may be launched.
                    # The lock is retained unless the normal path or the same
                    # independent recovery gate explicitly proves release safe.
                    release_host = False
                    try:
                        supervised = supervise_live_request(
                            attempt_dir,
                            request,
                            request_sha256,
                        )
                    except BaseException as exc:
                        try:
                            recovery = _supervision_recovery_gate(
                                attempt_dir,
                                request,
                            )
                        except BaseException as recovery_exc:
                            raise LiveHostQuarantinedError(
                                "live supervision was interrupted and recovery safety "
                                "could not be completed; host lock retained"
                            ) from recovery_exc
                        release_host = recovery.safe_to_release
                        if not release_host:
                            raise LiveHostQuarantinedError(
                                "live supervision failed and recovery safety could not "
                                f"be reproved; host lock retained: {recovery.detail}"
                            ) from exc
                        raise
                    if not supervised.hygiene_safe:
                        release_host = False
                        raise LiveHostQuarantinedError(
                            "live process hygiene is uncertain; host lock retained: "
                            f"{supervised.detail or attempt_dir}"
                        )
                    if supervised.verified is None:
                        raise LiveHostQuarantinedError(
                            "worker could not be terminalized; host lock retained"
                        )
                    results.append(supervised.verified)
                    release_host = True
                finally:
                    if release_host:
                        host_lock.release()
    return tuple(results)


def recover_live_host_lock(
    run_root: str | Path,
    *,
    acknowledge_recovery: bool,
    acknowledge_code_upgrade: bool = False,
) -> dict[str, Any]:
    """Recover one retained real-engine lock after exact fail-closed proofs."""
    if not acknowledge_recovery:
        raise LiveSupervisorError(
            "real-engine lock recovery requires explicit acknowledgement"
        )
    context = load_run(run_root)
    recovery_git_head = _bind_recovery_context(
        context,
        acknowledge_code_upgrade=acknowledge_code_upgrade,
    )
    lock_path = _host_lock_path()
    state = inspect_lock(lock_path)
    if state.payload.get("kind") != "real_engine":
        raise LiveSupervisorError("retained lock is not a real-engine lock")
    if state.owner_alive is not False or state.reason_code not in {
        "lock_owner_absent",
        "lock_pid_reused",
    }:
        raise LiveSupervisorError(
            f"real-engine lock owner absence is not proved: {state.reason_code}"
        )
    if state.file_identity is None:
        raise LiveSupervisorError("retained lock has no stable file identity")
    payload = state.payload
    pid = payload.get("pid")
    process_create_time = payload.get("process_create_time")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(process_create_time, (int, float))
        or isinstance(process_create_time, bool)
        or not math.isfinite(float(process_create_time))
    ):
        raise LiveSupervisorError(
            "retained lock lacks a valid PID/create-time owner identity"
        )
    if (
        payload.get("run_id") != context.descriptor["run_id"]
        or payload.get("git_head") != context.descriptor["git_head"]
    ):
        raise LiveSupervisorError("retained lock does not match the current run/git identity")
    lane_id = payload.get("lane_id")
    attempt_id = payload.get("attempt_id")
    if not isinstance(lane_id, str) or not isinstance(attempt_id, str):
        raise LiveSupervisorError("retained lock lacks lane/attempt identity")
    try:
        attempt_dir = resolve_plain_path(
            context.run_root / "attempts" / lane_id / attempt_id,
            kind="directory",
        )
        attempt_dir.relative_to(resolve_plain_path(context.run_root, kind="directory"))
        request, request_sha256 = read_json_with_digest(attempt_dir / "request.json")
    except (OSError, ValueError, SnapshotError) as exc:
        raise LiveSupervisorError("retained lock attempt archive is not confined") from exc
    request_identity = {
        "run_id": context.descriptor["run_id"],
        "lane_id": lane_id,
        "attempt_id": attempt_id,
        "manifest_sha256": context.manifest["manifest_sha256"],
        "normalized_manifest_sha256": context.normalized_manifest_sha256,
        "run_descriptor_sha256": context.descriptor_sha256,
        "git_head": context.descriptor["git_head"],
    }
    if any(request.get(key) != value for key, value in request_identity.items()):
        raise LiveSupervisorError("retained lock attempt is stale for the current run")
    lock_proof = request.get("real_engine_lock")
    if not isinstance(lock_proof, Mapping) or any(
        lock_proof.get(key) != value
        for key, value in {
            "path": str(resolve_plain_path(lock_path, kind="file")),
            "token": payload.get("token"),
            "run_id": payload.get("run_id"),
            "lane_id": lane_id,
            "attempt_id": attempt_id,
        }.items()
    ):
        raise LiveSupervisorError("attempt does not bind the exact retained lock")
    retained_owner_identity = (pid, float(process_create_time))
    recovery_gate = _supervision_recovery_gate(
        attempt_dir,
        request,
        expected_supervisor_identity=retained_owner_identity,
    )
    if not recovery_gate.safe_to_release or recovery_gate.inventory is None:
        raise LiveSupervisorError(
            "worker/source/process recovery proof failed; refusing lock recovery: "
            f"{recovery_gate.detail}"
        )
    inventory = recovery_gate.inventory
    try:
        current_payload, current_identity = _read_lock_payload(lock_path)
    except QualificationLockError as exc:
        raise LiveSupervisorError("retained lock changed during recovery") from exc
    if current_identity != state.file_identity or current_payload != payload:
        raise LiveSupervisorError("retained lock identity/token changed during recovery")
    recovery_id = str(uuid.uuid4())
    recovery_dir = _create_plain_descendant(
        context.run_root,
        Path("recoveries") / recovery_id,
    )
    intent = {
        "schema_version": 1,
        "action": "recover_real_engine_lock",
        "recovery_id": recovery_id,
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        **request_identity,
        "request_sha256": request_sha256,
        "recovery_git_head": recovery_git_head,
        "recovery_code_upgrade_acknowledged": acknowledge_code_upgrade,
        "lock_path": str(lock_path),
        "lock_payload": payload,
        "lock_file_identity": list(state.file_identity),
        "recovery_gate_proof": recovery_gate.detail,
        "worker_command_inventory": recovery_gate.worker_command_inventory,
        "source_snapshot": recovery_gate.source_snapshot,
        "global_inventory": inventory.raw,
        "hec_ras_invoked": False,
        "hec_ras_invocation_scope": "recovery_action_only",
        "retained_attempt_hec_ras_invocation_state": "unknown",
    }
    intent_sha256 = write_json_with_digest(
        recovery_dir / "recovery-intent.json",
        json_safe(intent),
    )
    # Reverify after durable authorization and immediately before retirement.
    current_payload, current_identity = _read_lock_payload(lock_path)
    if current_identity != state.file_identity or current_payload != payload:
        raise LiveSupervisorError(
            "retained lock changed after recovery authorization; refusing retirement"
        )
    final_recovery_gate = _supervision_recovery_gate(
        attempt_dir,
        request,
        expected_supervisor_identity=retained_owner_identity,
    )
    if (
        not final_recovery_gate.safe_to_release
        or final_recovery_gate.inventory is None
    ):
        raise LiveSupervisorError(
            "worker/source/process proof changed before retirement: "
            f"{final_recovery_gate.detail}"
        )
    final_inventory = final_recovery_gate.inventory
    _retire_verified_lock(
        lock_path,
        expected_identity=current_identity,
        expected_token=str(payload["token"]),
    )
    receipt = {
        **intent,
        "intent_sha256": intent_sha256,
        "recovered_at": datetime.now(timezone.utc).isoformat(),
        "final_recovery_gate_proof": final_recovery_gate.detail,
        "final_worker_command_inventory": (
            final_recovery_gate.worker_command_inventory
        ),
        "final_source_snapshot": final_recovery_gate.source_snapshot,
        "final_global_inventory": final_inventory.raw,
        "retirement_state": "atomically_retired",
    }
    write_json_with_digest(
        recovery_dir / "recovery-receipt.json",
        json_safe(receipt),
    )
    return receipt


def live_status(run_root: str | Path) -> dict[str, Any]:
    """Return run/attempt/lock state without creating files or inspecting HEC-RAS.

    The legacy top-level ``hec_ras_invoked`` field describes this read-only
    status action.  Historical execution is reported separately per verified
    attempt and in ``any_verified_attempt_hec_ras_invoked``.
    """
    context = load_run(run_root)
    attempts: list[dict[str, Any]] = []
    attempt_root = context.run_root / "attempts"
    if attempt_root.is_dir():
        root = resolve_plain_path(attempt_root, kind="directory")
        for lane_dir in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            assert_plain_ancestry(lane_dir, stop=root)
            if not lane_dir.is_dir():
                continue
            for attempt_dir in sorted(
                (path for path in lane_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            ):
                assert_plain_ancestry(attempt_dir, stop=lane_dir)
                state = "incomplete"
                terminal = None
                attempt_hec_ras_invoked = None
                try:
                    verified = verify_attempt_receipt(attempt_dir)
                except Exception:
                    if (attempt_dir / "worker_receipt.json").exists():
                        state = "worker_receipt_only"
                    elif (attempt_dir / "request.json").exists():
                        state = "request_only"
                else:
                    state = "verified_terminal"
                    terminal = verified.receipt["terminal_category"]
                    invocation_claim = verified.receipt.get("hec_ras_invoked")
                    attempt_hec_ras_invoked = (
                        invocation_claim
                        if isinstance(invocation_claim, bool)
                        else None
                    )
                attempts.append(
                    {
                        "lane_id": lane_dir.name,
                        "attempt_id": attempt_dir.name,
                        "state": state,
                        "terminal_category": terminal,
                        "hec_ras_invoked": attempt_hec_ras_invoked,
                    }
                )
    lock_paths = [context.run_root / "run.lock", _host_lock_path()]
    lock_paths.extend(
        context.run_root / "attempts" / lane_id / "lane.lock"
        for lane_id in context.descriptor["lane_ids"]
    )
    locks = []
    for path in lock_paths:
        state = inspect_lock(path)
        locks.append(
            {
                "path": str(state.path),
                "kind": state.payload.get("kind"),
                "owner_alive": state.owner_alive,
                "reason_code": state.reason_code,
                "run_id": state.payload.get("run_id"),
                "lane_id": state.payload.get("lane_id"),
                "attempt_id": state.payload.get("attempt_id"),
            }
        )
    verified_invocations = [
        attempt["hec_ras_invoked"]
        for attempt in attempts
        if attempt["state"] == "verified_terminal"
    ]
    if any(value is True for value in verified_invocations):
        any_verified_invocation = True
    elif verified_invocations and all(
        value is False for value in verified_invocations
    ):
        any_verified_invocation = False
    else:
        any_verified_invocation = None
    return {
        "run_id": context.descriptor["run_id"],
        "run_root": str(context.run_root),
        "manifest_sha256": context.manifest["manifest_sha256"],
        "git_head": context.descriptor["git_head"],
        "attempts": attempts,
        "locks": locks,
        "status_action_hec_ras_invoked": False,
        "any_verified_attempt_hec_ras_invoked": any_verified_invocation,
        # Backward-compatible action-local field.  Prefer the explicit fields above.
        "hec_ras_invoked": False,
    }


__all__ = [
    "LiveChildOutcome",
    "LiveHostQuarantinedError",
    "LiveSupervisorError",
    "ProcessInventorySnapshot",
    "RecoveryGateOutcome",
    "SupervisedAttempt",
    "create_live_attempt_request",
    "execute_live_action",
    "live_status",
    "recover_live_host_lock",
    "supervise_live_request",
]
