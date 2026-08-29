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
from .manifest import _preflight_repository
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


@dataclass(frozen=True)
class WorkerIdentityState:
    alive: bool | None
    reason_code: str
    pid: int
    process_create_time: float


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
        "timeout_seconds": context.manifest["defaults"]["timeout_seconds"],
        "termination_grace_seconds": context.manifest["defaults"][
            "termination_grace_seconds"
        ],
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


def _terminate_exact_python_child(process: subprocess.Popen[Any], grace: float) -> None:
    """Terminate only the exact Python child handle, never a HEC process name."""
    process.terminate()
    try:
        process.wait(timeout=max(0.1, min(grace, 10.0)))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


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


def _publish_worker_launch_intent(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> str:
    nonce, intent_path, _, _ = _worker_launch_paths(attempt_dir, request)
    lock = request["real_engine_lock"]
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
        "supervisor_pid": os.getpid(),
    }
    return write_json_with_digest(intent_path, json_safe(intent))


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
) -> None:
    """Bind exact parent-observed PID/create-time before worker execution."""
    pid, create_time = _live_python_child_identity(process)
    nonce, _, hello_path, authorization_path = _worker_launch_paths(
        attempt_dir, request
    )
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
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "worker_pid": pid,
    }
    for field, value in expected.items():
        if hello.get(field) != value:
            raise LiveSupervisorError(f"worker hello identity mismatch for {field}")
    hello_create_time = hello.get("worker_process_create_time")
    if (
        not isinstance(hello_create_time, (int, float))
        or isinstance(hello_create_time, bool)
        or abs(float(hello_create_time) - create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveSupervisorError("worker hello create-time identity mismatch")
    authorization = {
        "schema_version": 1,
        "action": "authorize_live_worker",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "worker_hello_sha256": hello_sha256,
        "launch_nonce": nonce,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "worker_pid": pid,
        "worker_process_create_time": create_time,
        "supervisor_pid": os.getpid(),
    }
    write_json_with_digest(authorization_path, json_safe(authorization))
    state = _inspect_exact_worker_identity(pid, create_time)
    if state.alive is not True:
        raise LiveSupervisorError(
            "live Python child identity changed while authorization was published: "
            f"{state.reason_code}"
        )


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
        "cancel_receipt_path": str(attempt_dir / "cancel-receipt.json"),
        "stage_project": str(stage_project),
        "plan_number": request["fixture"]["plan_number"],
        "timeout_seconds": request["termination_grace_seconds"],
        "hec_ras_execution_enabled": True,
    }
    path = attempt_dir / "cancel-request.json"
    write_json_with_digest(path, cancellation)
    return path


def _run_cancellation_helper(
    attempt_dir: Path,
    request: Mapping[str, Any],
    request_sha256: str,
) -> tuple[bool, str]:
    cancel_request_path = _create_cancellation_request(
        attempt_dir, request, request_sha256
    )
    command = [
        str(request["python_executable"]),
        "-m",
        "scripts.qualification.execution_evidence.live_cancel_worker",
        "--request",
        str(cancel_request_path),
    ]
    environment = os.environ.copy()
    repository_root = Path(str(request["repository_root"])).resolve(strict=True)
    environment["PYTHONPATH"] = str(repository_root) + (
        os.pathsep + environment["PYTHONPATH"]
        if environment.get("PYTHONPATH")
        else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
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
        try:
            returncode = process.wait(
                timeout=float(request["termination_grace_seconds"])
            )
        except subprocess.TimeoutExpired:
            _terminate_exact_python_child(
                process, float(request["termination_grace_seconds"])
            )
            return False, "cancellation_helper_timed_out"
    if returncode != 0:
        return False, f"cancellation_helper_exit_{returncode}"
    try:
        cancel_request, cancel_request_sha256 = read_json_with_digest(
            cancel_request_path
        )
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
        process = subprocess.Popen(
            _worker_command(request, attempt_dir / "request.json"),
            cwd=repository_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
        )
        _authorize_live_child(
            process,
            attempt_dir,
            request,
            request_sha256,
            intent_sha256,
        )
        try:
            outer_deadline = float(request["timeout_seconds"])
            if request["engine"]["execution_api"] == "ras_control":
                outer_deadline += float(request["termination_grace_seconds"])
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
                    _terminate_exact_python_child(
                        process, float(request["termination_grace_seconds"])
                    )
                except Exception as exc:
                    cancellation_safe = False
                    cancellation_reason = (
                        f"{cancellation_reason};python_child_termination_error:"
                        f"{type(exc).__name__}:{exc}"
                    )
            return LiveChildOutcome(
                pid=process.pid,
                returncode=124,
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                timed_out=True,
                cancellation_safe=cancellation_safe,
                cancellation_reason=cancellation_reason,
            )
    return LiveChildOutcome(
        pid=process.pid,
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


def _verify_worker_execution_proof(
    worker: Mapping[str, Any],
    request: Mapping[str, Any],
    engine: Mapping[str, Any],
) -> None:
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

    execution = worker.get("execution_result")
    if not isinstance(execution, Mapping) or execution.get("success") is not True:
        raise LiveSupervisorError("live terminal lacks a successful execution result")
    details = execution.get("execution_details")
    if not isinstance(details, Mapping):
        raise LiveSupervisorError("live terminal lacks structured execution details")
    common = {
        "execution_api": engine["execution_api"],
        "selected_result_format": engine["expected_result_format"],
        "calculation_attempted": True,
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "actual_engine_provenance_confirmed": True,
    }
    if any(details.get(field) != value for field, value in common.items()):
        raise LiveSupervisorError(
            "live terminal execution details fail calculation/provenance/finalization gates"
        )
    if engine["execution_api"] == "ras_cmdr":
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
        if execution.get("completion_verified") is not True:
            raise LiveSupervisorError("live RasCmdr completion was not verified")
        return

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
    """Prove that a receipt is a reusable successful live terminal."""
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
    if receipt.get("terminal_category") != "passed":
        raise LiveSupervisorError("live terminal is not passed")
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
    _verify_stage_project_proof(
        worker,
        source_project=source_project,
        expected_stage_root=expected_stage_root,
    )
    _verify_worker_execution_proof(worker, request, engine)
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
        or any(row.get("status") != "pass" for row in invariants)
    ):
        raise LiveSupervisorError("live terminal invariants are not exact unique passes")
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
        "terminal_category": "passed",
    }
    if any(lane_row_record.get(key) != value for key, value in lane_identity.items()):
        raise LiveSupervisorError("live terminal lane identity or stage binding is stale")
    expected_format = engine.get("expected_result_format")
    if (
        lane_row_record.get("expected_result_format") != expected_format
        or lane_row_record.get("selected_result_format") != expected_format
    ):
        raise LiveSupervisorError("live terminal selected the wrong result family")
    expected_flags = (True, False) if expected_format == "hdf" else (False, True)
    observed_flags = (
        lane_row_record.get("final_hdf_exists"),
        lane_row_record.get("final_legacy_exists"),
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
) -> tuple[bool, str]:
    """Prove the exact authorized Python worker is absent or never launched."""
    try:
        nonce, intent_path, hello_path, authorization_path = _worker_launch_paths(
            attempt_dir, request
        )
    except Exception as exc:
        return False, f"worker launch metadata is unverifiable: {type(exc).__name__}: {exc}"
    record_paths = (intent_path, hello_path, authorization_path)
    digest_paths = tuple(path.with_suffix(".sha256") for path in record_paths)
    if not any(path.exists() for path in (*record_paths, *digest_paths)):
        return True, "worker launch was never initiated"
    if intent_path.exists() is not True or intent_path.with_suffix(".sha256").exists() is not True:
        return False, "worker launch intent publication is incomplete"
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
        "launch_nonce": nonce,
        "run_id": request.get("run_id"),
        "lane_id": request.get("lane_id"),
        "attempt_id": request.get("attempt_id"),
    }
    if any(hello.get(field) != value for field, value in hello_expected.items()):
        return False, "worker hello identity is unverifiable"
    pid = hello.get("worker_pid")
    create_time = hello.get("worker_process_create_time")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(create_time, (int, float))
        or isinstance(create_time, bool)
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
            "worker_hello_sha256": hello_sha256,
            "launch_nonce": nonce,
            "run_id": request.get("run_id"),
            "lane_id": request.get("lane_id"),
            "attempt_id": request.get("attempt_id"),
            "real_engine_lock_token": request.get("real_engine_lock", {}).get("token"),
            "worker_pid": pid,
            "worker_process_create_time": create_time,
        }
        if any(
            authorization.get(field) != value
            for field, value in authorization_expected.items()
        ):
            return False, "worker authorization identity is unverifiable"
    state = _inspect_exact_worker_identity(pid, float(create_time))
    if state.alive is True:
        return False, "exact authorized Python worker is still alive"
    if state.alive is None:
        return False, f"exact Python worker identity is unverifiable: {state.reason_code}"
    return True, f"exact Python worker is absent: {state.reason_code}"


def _supervision_recovery_gate(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> RecoveryGateOutcome:
    """Independently reprove source immutability and global quiescence.

    This is the sole parent-owned host-safety proof before terminalization or
    host-lock release.  It never publishes a terminal receipt.
    """
    worker_safe, worker_detail = _worker_launch_recovery_gate(attempt_dir, request)
    if not worker_safe:
        return RecoveryGateOutcome(False, worker_detail)
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
            return RecoveryGateOutcome(False, "source snapshot drifted")
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
            )
    except Exception as exc:
        return RecoveryGateOutcome(
            False,
            f"recovery proof failed: {type(exc).__name__}: {exc}",
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
        )
    return RecoveryGateOutcome(
        True,
        f"{worker_detail}; source and global process hygiene reproved",
        inventory,
        source_proof,
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
    if resume:
        selected = [
            lane_id
            for lane_id in selected
            if not _lane_has_verified_terminal(context, lane_id)
        ]
        if not selected:
            return ()
    _bind_live_context(context)
    _require_strict_live_api_contracts(context, selected)
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
) -> dict[str, Any]:
    """Recover one retained real-engine lock after exact fail-closed proofs."""
    if not acknowledge_recovery:
        raise LiveSupervisorError(
            "real-engine lock recovery requires explicit acknowledgement"
        )
    context = load_run(run_root)
    _bind_live_context(context)
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
    recovery_gate = _supervision_recovery_gate(attempt_dir, request)
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
        "lock_path": str(lock_path),
        "lock_payload": payload,
        "lock_file_identity": list(state.file_identity),
        "recovery_gate_proof": recovery_gate.detail,
        "source_snapshot": recovery_gate.source_snapshot,
        "global_inventory": inventory.raw,
        "hec_ras_invoked": False,
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
    final_recovery_gate = _supervision_recovery_gate(attempt_dir, request)
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
    """Return run/attempt/lock state without creating files or inspecting HEC-RAS."""
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
                attempts.append(
                    {
                        "lane_id": lane_dir.name,
                        "attempt_id": attempt_dir.name,
                        "state": state,
                        "terminal_category": terminal,
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
    return {
        "run_id": context.descriptor["run_id"],
        "run_root": str(context.run_root),
        "manifest_sha256": context.manifest["manifest_sha256"],
        "git_head": context.descriptor["git_head"],
        "attempts": attempts,
        "locks": locks,
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
