"""One-shot, fail-closed worker for an acknowledged live HEC-RAS attempt.

The parent process owns subprocess supervision, stdout/stderr capture, timeout
cancellation, and terminal receipt publication.  This worker owns only the
attempt's staged project, public ras-commander calls, evidence records, and an
immutable ``worker_receipt.json``.  It never starts or controls a HEC-RAS
process except through the public ``RasCmdr``/``RasControl`` APIs.

The worker intentionally depends on the additive structured process and
execution-detail contracts.  If those contracts are unavailable or incomplete
it refuses the live attempt before staging, or quarantines an already-started
attempt without inspecting possibly active result files.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import math
import os
import platform
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import psutil
import pyarrow

from .fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from .invariants import evaluate_invariants
from .locks import inspect_lock
from .manifest import canonical_sha256, load_and_normalize_manifest
from .offline_records import (
    available_value,
    flatten_evidence,
    json_safe,
    known_result_paths,
    lane_row,
    result_population,
    selected_result_format,
)
from .planning import current_runtime_pins, file_sha256, load_run, select_lane
from .receipts import (
    EventJournal,
    read_event_journal,
    read_json_with_digest,
    write_json_with_digest,
)
from .replay import overlay_replay_artifacts, replay_origin_overrides
from .run_io import write_bytes_with_digest
from .schemas import table_from_rows
from .snapshots import TreeSnapshot, diff_snapshots, snapshot_tree


_WORKER_INVOCATIONS = 0
_NORMAL_LIVE_INVARIANTS = frozenset(
    {"R01", "R02", "R03", "R04", "R06", "R10", "R11", "R12"}
)
_ENGINE_DETAILS_COMMON = (
    "execution_api",
    "engine_kind",
    "calculation_attempted",
    "selected_result_format",
    "solver_quiescence_confirmed",
    "result_artifacts_finalized",
    "artifact_preparation_cleanup",
    "artifact_finalization_cleanup",
    "actual_engine_provenance_confirmed",
)
_WORKER_IDENTITY_TOLERANCE_SECONDS = 0.001
_WORKER_AUTHORIZATION_POLL_SECONDS = 0.02
_SUPERVISOR_RECEIPT_MARGIN_SECONDS = 5.0
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
_RASCMD_RUNTIME_DETAIL_FIELDS = frozenset(
    {
        "artifact_finalization_failure",
        "launcher_returncode",
        "max_runtime_seconds",
        "launch_details",
        "runtime_timed_out",
        "failure_stage",
        "failure_type",
        "failure_detail",
        "cancellation_details",
    }
)
_ARTIFACT_FINALIZATION_FAILURE_FIELDS = frozenset(
    {"failure_stage", "failure_type", "failure_detail"}
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
_FAILED_INSPECTION_EVIDENCE_KIND = "execution_evidence_inspection_failure"
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


class LiveWorkerError(RuntimeError):
    """A signed live request failed a qualification safety contract."""


class LiveCapabilityError(LiveWorkerError):
    """Required structured ras-commander evidence is unavailable."""


class LiveProcessGateError(LiveWorkerError):
    """Process ownership or quiescence could not be proved."""


class LiveAssetGateError(LiveWorkerError):
    """A staged linked asset could escape the disposable execution tree."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.reason_code = reason_code
        self.findings = [dict(item) for item in findings]
        super().__init__(f"{reason_code}: {message}")


class LiveTcuGateError(LiveWorkerError):
    """Exact-engine TCU acceptance was rejected or could not be proved."""


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _valid_process_identity(pid: Any, create_time: Any) -> bool:
    """Return true only for a positive PID plus finite positive creation time."""
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and isinstance(create_time, (int, float))
        and not isinstance(create_time, bool)
        and math.isfinite(float(create_time))
        and float(create_time) > 0
    )


def _strict_positive_seconds(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveCapabilityError(f"{label} must be a positive finite number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise LiveCapabilityError(
            f"{label} must be a positive finite number"
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise LiveCapabilityError(f"{label} must be a positive finite number")
    return normalized


def _cleanup_removed_relative_paths(
    request: Mapping[str, Any],
    cleanup: Any,
    *,
    label: str,
    expected_result_format: str | None = None,
    expected_include_message_sidecars: bool | None = None,
) -> list[str]:
    if not isinstance(cleanup, Mapping) or set(cleanup) != _ARTIFACT_CLEANUP_FIELDS:
        raise LiveCapabilityError(f"{label} is not a complete cleanup record")
    plan_number = request["fixture"]["plan_number"]
    if cleanup["plan_number"] != plan_number:
        raise LiveCapabilityError(f"{label} plan number mismatch")
    result_format = cleanup["result_format"]
    if result_format not in {"hdf", "legacy", "both"}:
        raise LiveCapabilityError(f"{label} result format is invalid")
    if (
        expected_result_format is not None
        and result_format != expected_result_format
    ):
        raise LiveCapabilityError(f"{label} result format mismatch")
    include_sidecars = cleanup["include_message_sidecars"]
    if not isinstance(include_sidecars, bool):
        raise LiveCapabilityError(f"{label} sidecar flag is not boolean")
    if (
        expected_include_message_sidecars is not None
        and include_sidecars is not expected_include_message_sidecars
    ):
        raise LiveCapabilityError(f"{label} sidecar flag mismatch")

    stage_root = Path(request["stage_root"]).resolve(strict=False)
    stage_project = stage_root / Path(request["source_project"]).name
    known_paths = known_result_paths(stage_project, plan_number)
    allowed = {relative.casefold(): relative for relative in known_paths}
    expected_targets = []
    if result_format in {"hdf", "both"}:
        expected_targets.append(known_paths[0])
    if result_format in {"legacy", "both"}:
        expected_targets.append(known_paths[1])
    if include_sidecars:
        expected_targets.extend(known_paths[2:])
    normalized: dict[str, list[str]] = {}
    for field in ("removed_paths", "missing_paths"):
        raw_paths = cleanup[field]
        if not isinstance(raw_paths, list) or any(
            not isinstance(raw, str) or not raw for raw in raw_paths
        ):
            raise LiveCapabilityError(f"{label} {field} is not a path array")
        relative_paths = []
        for raw in raw_paths:
            if not _path_is_within(stage_root, raw):
                raise LiveCapabilityError(f"{label} path escaped the stage: {raw}")
            relative = Path(
                os.path.relpath(
                    os.path.realpath(raw),
                    os.path.realpath(stage_root),
                )
            ).as_posix()
            canonical = allowed.get(relative.casefold())
            if canonical is None:
                raise LiveCapabilityError(
                    f"{label} path is outside the exact cleanup allowlist: {relative}"
                )
            relative_paths.append(canonical)
        keys = [relative.casefold() for relative in relative_paths]
        if len(keys) != len(set(keys)):
            raise LiveCapabilityError(f"{label} {field} contains duplicates")
        normalized[field] = relative_paths
    if {
        path.casefold() for path in normalized["removed_paths"]
    } & {
        path.casefold() for path in normalized["missing_paths"]
    }:
        raise LiveCapabilityError(f"{label} reports a path as removed and missing")
    observed_targets = {
        path.casefold()
        for field in ("removed_paths", "missing_paths")
        for path in normalized[field]
    }
    if observed_targets != {path.casefold() for path in expected_targets}:
        raise LiveCapabilityError(f"{label} target set mismatch")
    return normalized["removed_paths"]


def _execution_cleanup_removed_relative_paths(
    request: Mapping[str, Any],
    details: Mapping[str, Any],
) -> list[str]:
    expected = request["engine"]["expected_result_format"]
    opposing = "legacy" if expected == "hdf" else "hdf"
    removed = _cleanup_removed_relative_paths(
        request,
        details.get("artifact_preparation_cleanup"),
        label="artifact preparation cleanup",
        expected_result_format=opposing,
        expected_include_message_sidecars=True,
    )
    finalization = details.get("artifact_finalization_cleanup")
    if details.get("result_artifacts_finalized") is True:
        removed.extend(
            _cleanup_removed_relative_paths(
                request,
                finalization,
                label="artifact finalization cleanup",
                expected_result_format=opposing,
                expected_include_message_sidecars=False,
            )
        )
    elif finalization is not None:
        raise LiveCapabilityError(
            "unfinalized result artifacts contain a finalization cleanup record"
        )
    return removed


def _validate_artifact_finalization_evidence(details: Mapping[str, Any]) -> bool:
    """Validate the independent RasCmdr result-artifact finalization claim."""
    finalized = details.get("result_artifacts_finalized")
    if not isinstance(finalized, bool):
        raise LiveCapabilityError(
            "RasCmdr result_artifacts_finalized is not boolean"
        )
    if "artifact_finalization_failure" not in details:
        raise LiveCapabilityError(
            "RasCmdr execution_details lacks artifact_finalization_failure"
        )
    failure = details["artifact_finalization_failure"]
    if finalized:
        if failure is not None:
            raise LiveCapabilityError(
                "finalized RasCmdr artifacts contain secondary failure metadata"
            )
        return True
    if (
        not isinstance(failure, Mapping)
        or set(failure) != _ARTIFACT_FINALIZATION_FAILURE_FIELDS
        or failure.get("failure_stage") != "result_artifact_finalization"
        or any(
            not isinstance(failure.get(field), str)
            or not failure[field].strip()
            for field in _ARTIFACT_FINALIZATION_FAILURE_FIELDS
        )
    ):
        raise LiveCapabilityError(
            "unfinalized RasCmdr artifacts lack complete secondary failure metadata"
        )
    return False


def _failed_inspection_evidence(
    details: Mapping[str, Any],
    exc: BaseException,
    *,
    started_at: datetime,
    failed_at: datetime,
) -> dict[str, Any]:
    """Serialize one narrowly scoped post-failure ambiguity diagnostic."""
    return json_safe({
        "schema_version": 1,
        "evidence_kind": _FAILED_INSPECTION_EVIDENCE_KIND,
        "evidence_id": str(uuid.uuid4()),
        "inspection_api": "RasCmdr.inspect_execution_evidence",
        "inspection_state": "failed",
        "inspection_started_at": started_at,
        "inspection_failed_at": failed_at,
        "failure_type": type(exc).__name__,
        "reason_code": getattr(exc, "reason_code", None),
        "detail": str(exc),
        "plan_number": getattr(exc, "plan_number", None),
        "declared_program_version": getattr(
            exc, "declared_program_version", None
        ),
        "declared_expected_result_format": getattr(exc, "expected_format", None),
        "selected_result_format": details["selected_result_format"],
        "hdf_path": str(getattr(exc, "hdf_path", "")),
        "legacy_output_path": str(getattr(exc, "legacy_output_path", "")),
        "hdf_mtime_ns": getattr(exc, "hdf_mtime_ns", None),
        "legacy_mtime_ns": getattr(exc, "legacy_mtime_ns", None),
        "conflicts": ["multiple_result_formats_present"],
        "safe_failed_execution": True,
        "result_artifacts_finalized": details["result_artifacts_finalized"],
        "runtime_timed_out": details["runtime_timed_out"],
    })


def _validated_process_identities(
    value: Any,
    *,
    label: str,
) -> set[tuple[int, float]]:
    """Validate one JSON-safe ``RasProcessRecord.to_dict()`` collection."""
    if not isinstance(value, list):
        raise LiveCapabilityError(f"{label} is not an array")
    identities: list[tuple[int, float]] = []
    for record in value:
        if not isinstance(record, Mapping) or set(record) != _PROCESS_RECORD_FIELDS:
            raise LiveCapabilityError(f"{label} contains a malformed process record")
        pid = record["pid"]
        create_time = record["create_time"]
        name = record["name"]
        command_line = record["command_line"]
        if (
            not _valid_process_identity(pid, create_time)
            or not isinstance(name, str)
            or not name
            or not isinstance(command_line, list)
            or any(not isinstance(token, str) for token in command_line)
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
            raise LiveCapabilityError(f"{label} contains a malformed process record")
        identities.append((pid, float(create_time)))
    if len(identities) != len(set(identities)):
        raise LiveCapabilityError(f"{label} contains duplicate process identities")
    return set(identities)


def _validate_safe_rascmd_failure(
    request: Mapping[str, Any],
    details: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> None:
    """Require a closed, exact cancellation receipt for a failed modern run."""
    runtime_timed_out = details["runtime_timed_out"]
    failure_stage = details["failure_stage"]
    failure_type = details["failure_type"]
    failure_detail = details["failure_detail"]
    if not isinstance(runtime_timed_out, bool):
        raise LiveCapabilityError("RasCmdr runtime_timed_out is not boolean")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (failure_stage, failure_type, failure_detail)
    ):
        raise LiveCapabilityError(
            "RasCmdr failed result lacks complete failure metadata"
        )
    if runtime_timed_out and failure_type != "TimeoutError":
        raise LiveCapabilityError(
            "RasCmdr timeout flag and failure type are inconsistent"
        )

    cancellation = details["cancellation_details"]
    if (
        not isinstance(cancellation, Mapping)
        or set(cancellation) != _CANCELLATION_DETAIL_FIELDS
    ):
        raise LiveCapabilityError(
            "RasCmdr failed result lacks a complete exact-cancellation receipt"
        )
    if (
        not isinstance(cancellation["cancellation_attempted"], bool)
        or cancellation["pre_scan_complete"] is not True
        or cancellation["post_scan_complete"] is not True
        or cancellation["quiescence_confirmed"] is not True
        or cancellation["survivors"] != []
        or cancellation["query_errors"] != []
    ):
        raise LiveProcessGateError(
            "RasCmdr failed result did not prove exact cancellation and quiescence"
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
        raise LiveCapabilityError(
            "RasCmdr exact-cancellation timestamps are invalid"
        )
    matched = _validated_process_identities(
        cancellation["matched"], label="RasCmdr cancellation matched"
    )
    stopped = _validated_process_identities(
        cancellation["stopped"], label="RasCmdr cancellation stopped"
    )
    if not matched.issubset(stopped):
        raise LiveProcessGateError(
            "RasCmdr exact cancellation did not stop every initial match"
        )
    if cancellation["cancellation_attempted"] and not matched:
        raise LiveCapabilityError(
            "RasCmdr exact cancellation claims signalling without a match"
        )

    expected_project = Path(str(launch["project_path"])).resolve(strict=True)
    expected_plan = Path(str(launch["plan_path"])).resolve(strict=True)
    expected_tmp_hdf = expected_project.with_suffix(
        f".p{request['fixture']['plan_number']}.tmp.hdf"
    ).resolve(strict=False)
    try:
        observed_project = Path(str(cancellation["project_path"])).resolve(
            strict=True
        )
        observed_plan = Path(str(cancellation["plan_path"])).resolve(strict=True)
        observed_tmp_hdf = Path(str(cancellation["tmp_hdf_path"])).resolve(
            strict=False
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise LiveCapabilityError(
            "RasCmdr exact-cancellation paths are unverifiable"
        ) from exc
    if (
        cancellation["plan_number"] != request["fixture"]["plan_number"]
        or not _same_file(observed_project, expected_project)
        or not _same_file(observed_plan, expected_plan)
        or observed_tmp_hdf != expected_tmp_hdf
    ):
        raise LiveCapabilityError(
            "RasCmdr exact-cancellation identity disagrees with the launch"
        )


def _normalize_rascmd_launch_details(
    request: Mapping[str, Any],
    launch_details: Any,
    *,
    stage_project: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the post-Popen callback and build its durable event payload."""
    if not isinstance(launch_details, Mapping):
        raise LiveCapabilityError("RasCmdr launch callback did not provide a mapping")
    details = json_safe(dict(launch_details))
    if set(details) != _RASCMD_LAUNCH_DETAIL_FIELDS:
        raise LiveCapabilityError("RasCmdr launch callback field set is incomplete")

    plan_number = request["fixture"]["plan_number"]
    if details["plan_number"] != plan_number:
        raise LiveCapabilityError("RasCmdr launch callback plan number mismatch")
    expected_executable = Path(request["engine"]["executable"]).resolve(strict=True)
    expected_project = stage_project.resolve(strict=True)
    expected_plan = expected_project.with_suffix(f".p{plan_number}").resolve(strict=True)
    expected_working_directory = expected_project.parent.resolve(strict=True)
    try:
        callback_executable = Path(details["executable_path"]).resolve(strict=True)
        callback_project = Path(details["project_path"]).resolve(strict=True)
        callback_plan = Path(details["plan_path"]).resolve(strict=True)
        callback_working_directory = Path(details["working_directory"]).resolve(
            strict=True
        )
    except (OSError, TypeError, ValueError) as exc:
        raise LiveCapabilityError(
            "RasCmdr launch callback paths were not proved"
        ) from exc
    for observed, expected, label in (
        (callback_executable, expected_executable, "executable"),
        (callback_project, expected_project, "project"),
        (callback_plan, expected_plan, "plan"),
        (
            callback_working_directory,
            expected_working_directory,
            "working directory",
        ),
    ):
        if not _same_file(observed, expected):
            raise LiveCapabilityError(f"RasCmdr launch callback {label} mismatch")
    if details["executable_sha256"] != request["engine"]["executable_sha256"]:
        raise LiveCapabilityError("RasCmdr launch callback executable hash mismatch")
    if not _valid_process_identity(
        details["launcher_pid"], details["launcher_create_time"]
    ):
        raise LiveCapabilityError(
            "RasCmdr launch callback PID/create-time identity was not proved"
        )
    max_runtime = _strict_positive_seconds(
        details["max_runtime_seconds"],
        label="RasCmdr launch callback max_runtime_seconds",
    )
    if max_runtime != float(request["timeout_seconds"]):
        raise LiveCapabilityError("RasCmdr launch callback max-runtime mismatch")

    logical_argv = [
        str(expected_executable),
        "-c",
        str(expected_project),
        str(expected_plan),
    ]
    if any('"' in token for token in logical_argv):
        raise LiveCapabilityError("RasCmdr launch callback path contains a quote")
    expected_raw_command = (
        f'"{logical_argv[0]}" -c "{logical_argv[2]}" "{logical_argv[3]}"'
    )
    if details["command"] != expected_raw_command:
        raise LiveCapabilityError("RasCmdr launch callback raw command mismatch")
    event_payload = {
        "plan_number": plan_number,
        "raw_command": expected_raw_command,
        "logical_argv": logical_argv,
        "executable_path": str(expected_executable),
        "executable_sha256": request["engine"]["executable_sha256"],
        "project_path": str(expected_project),
        "plan_path": str(expected_plan),
        "cwd": str(expected_working_directory),
        "launch_method": "direct_subprocess_shell_false_exact_executable",
        "launcher_pid": details["launcher_pid"],
        "launcher_create_time": float(details["launcher_create_time"]),
        "max_runtime_seconds": max_runtime,
    }
    return details, event_payload


class _LiveLaunchRecorder:
    """Duck-typed callback that durably records exact modern launch evidence."""

    def __init__(
        self,
        *,
        events: EventJournal,
        request: Mapping[str, Any],
        stage_project: Path,
    ) -> None:
        self._events = events
        self._request = request
        self._stage_project = stage_project
        self.launch_details: dict[str, Any] | None = None
        self.event: dict[str, Any] | None = None

    def on_exec_launched(self, plan_number: str, launch_details: Any) -> None:
        if self.launch_details is not None:
            raise LiveCapabilityError("RasCmdr published more than one launch callback")
        if plan_number != self._request["fixture"]["plan_number"]:
            raise LiveCapabilityError("RasCmdr launch callback argument mismatch")
        details, payload = _normalize_rascmd_launch_details(
            self._request,
            launch_details,
            stage_project=self._stage_project,
        )
        event = self._events.append(
            phase="execution",
            event_name="engine_process_launched",
            status="running",
            api="RasCmdr.compute_plan.on_exec_launched",
            pid=details["launcher_pid"],
            payload=payload,
        )
        self.launch_details = details
        self.event = event


def _artifact_reference(attempt_dir: Path, path: Path) -> dict[str, str]:
    return {
        "relative_path": path.relative_to(attempt_dir).as_posix(),
        "sha256": file_sha256(path),
    }


def _revalidate_environment(request: Mapping[str, Any], context: Any) -> Any:
    """Re-prove immutable run, repository, runtime, source, and engine pins."""
    refreshed = load_run(context.run_root)
    if refreshed.descriptor_sha256 != request.get("run_descriptor_sha256"):
        raise LiveWorkerError("live request run descriptor pin mismatch")
    source_manifest = context.run_root / "manifest.source.json"
    revalidated = load_and_normalize_manifest(source_manifest)
    if revalidated != refreshed.manifest:
        raise LiveWorkerError("live manifest revalidation disagrees with the archived run")
    for field, observed in current_runtime_pins().items():
        if request.get(field) != observed:
            raise LiveWorkerError(f"live worker runtime pin mismatch for {field}")
    executable = Path(str(request.get("python_executable", ""))).resolve(strict=True)
    if not _same_file(executable, Path(sys.executable).resolve(strict=True)):
        raise LiveWorkerError("live worker interpreter path does not match request pin")
    if file_sha256(executable) != request.get("python_executable_sha256"):
        raise LiveWorkerError("live worker interpreter hash does not match request pin")
    return refreshed


def _verify_real_engine_lock(request: Mapping[str, Any]) -> dict[str, Any]:
    expected = request.get("real_engine_lock")
    if not isinstance(expected, Mapping):
        raise LiveWorkerError("live request lacks a real_engine_lock identity")
    required = ("path", "token", "run_id", "lane_id", "attempt_id")
    if any(not isinstance(expected.get(field), str) or not expected[field] for field in required):
        raise LiveWorkerError("live request real_engine_lock identity is incomplete")
    state = inspect_lock(expected["path"])
    if state.owner_alive is not True or state.reason_code != "lock_owner_alive":
        raise LiveWorkerError(
            f"real-engine lock ownership is not live: {state.reason_code}"
        )
    payload = state.payload
    checks = {
        "kind": "real_engine",
        "token": expected["token"],
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
    }
    for field, value in checks.items():
        if payload.get(field) != value or expected.get(field, value) != value:
            raise LiveWorkerError(f"real-engine lock identity mismatch for {field}")
    return json_safe(payload)


def _worker_launch_paths(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> tuple[str, Path, Path, Path]:
    launch = request.get("worker_launch")
    if not isinstance(launch, Mapping):
        raise LiveWorkerError("live request lacks worker launch handshake metadata")
    nonce = launch.get("launch_nonce")
    if not isinstance(nonce, str):
        raise LiveWorkerError("worker launch nonce is missing")
    try:
        uuid.UUID(nonce)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveWorkerError("worker launch nonce is invalid") from exc
    expected = (
        attempt_dir / "worker-launch-intent.json",
        attempt_dir / "worker-hello.json",
        attempt_dir / "worker-authorization.json",
    )
    claimed = tuple(
        Path(str(launch.get(field, ""))).resolve(strict=False)
        for field in ("intent_path", "hello_path", "authorization_path")
    )
    if claimed != tuple(path.resolve(strict=False) for path in expected):
        raise LiveWorkerError("worker launch handshake paths escaped the attempt")
    return nonce, *expected


def _worker_launcher_path(
    attempt_dir: Path,
    request: Mapping[str, Any],
) -> Path:
    launch = request.get("worker_launch")
    if not isinstance(launch, Mapping):
        raise LiveWorkerError("live request lacks worker launch handshake metadata")
    expected = (attempt_dir / "worker-launcher.json").resolve(strict=False)
    claimed = Path(str(launch.get("binding_path", ""))).resolve(strict=False)
    if claimed != expected:
        raise LiveWorkerError("worker launcher binding path escaped the attempt")
    return expected


def _current_worker_identity() -> tuple[int, float]:
    pid = os.getpid()
    try:
        process = psutil.Process(pid)
        create_time = float(process.create_time())
        running = process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError) as exc:
        raise LiveWorkerError("worker process identity could not be proved") from exc
    if not running or not math.isfinite(create_time):
        raise LiveWorkerError("worker process identity is not running and stable")
    return pid, create_time


def _current_worker_parent_identity() -> tuple[int, float]:
    try:
        parent = psutil.Process(os.getpid()).parent()
        if parent is None:
            raise LiveWorkerError("worker parent process identity is unavailable")
        pid = parent.pid
        create_time = float(parent.create_time())
        running = parent.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError) as exc:
        raise LiveWorkerError("worker parent process identity could not be proved") from exc
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not running
        or not math.isfinite(create_time)
        or create_time <= 0
    ):
        raise LiveWorkerError("worker parent process identity is not stable")
    return pid, create_time


def _register_and_verify_worker_authorization(
    request_path: Path,
    launch_nonce: str | None,
) -> None:
    """Publish the child identity, then wait for exact parent authorization."""
    request, request_sha256 = read_json_with_digest(request_path)
    attempt_dir = request_path.parent.resolve(strict=True)
    nonce, intent_path, hello_path, authorization_path = _worker_launch_paths(
        attempt_dir, request
    )
    if launch_nonce != nonce:
        raise LiveWorkerError("worker launch command nonce disagrees with request")
    intent, intent_sha256 = read_json_with_digest(intent_path)
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
    for field, value in intent_expected.items():
        if intent.get(field) != value:
            raise LiveWorkerError(f"worker launch intent mismatch for {field}")
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
        raise LiveWorkerError("worker launch intent lacks supervisor identity")
    binding, binding_sha256 = read_json_with_digest(
        _worker_launcher_path(attempt_dir, request)
    )
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
    }
    for field, value in binding_expected.items():
        if binding.get(field) != value:
            raise LiveWorkerError(f"worker launcher binding mismatch for {field}")
    pid, create_time = _current_worker_identity()
    parent_pid, parent_create_time = _current_worker_parent_identity()
    hello = {
        "schema_version": 1,
        "action": "hello_live_worker",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_sha256,
        "launch_intent_sha256": intent_sha256,
        "launch_binding_sha256": binding_sha256,
        "launch_nonce": nonce,
        "run_id": request.get("run_id"),
        "lane_id": request.get("lane_id"),
        "attempt_id": request.get("attempt_id"),
        "worker_pid": pid,
        "worker_process_create_time": create_time,
        "worker_parent_pid": parent_pid,
        "worker_parent_process_create_time": parent_create_time,
    }
    hello_sha256 = write_json_with_digest(hello_path, json_safe(hello))
    timeout = min(
        60.0,
        max(0.1, float(request.get("termination_grace_seconds", 0.0))),
    )
    deadline = time.monotonic() + timeout
    digest_path = authorization_path.with_suffix(".sha256")
    while not (authorization_path.exists() and digest_path.exists()):
        if time.monotonic() >= deadline:
            raise LiveWorkerError("parent did not authorize this exact worker identity")
        time.sleep(_WORKER_AUTHORIZATION_POLL_SECONDS)
    authorization, _ = read_json_with_digest(authorization_path)
    expected = {
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
    for field, value in expected.items():
        if authorization.get(field) != value:
            raise LiveWorkerError(f"worker authorization mismatch for {field}")
    authorized_create_time = authorization.get("worker_process_create_time")
    if (
        not isinstance(authorized_create_time, (int, float))
        or isinstance(authorized_create_time, bool)
        or not math.isfinite(float(authorized_create_time))
        or float(authorized_create_time) <= 0
        or abs(float(authorized_create_time) - create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveWorkerError("worker authorization create-time identity mismatch")
    authorized_parent_create_time = authorization.get(
        "worker_parent_process_create_time"
    )
    if (
        not isinstance(authorized_parent_create_time, (int, float))
        or isinstance(authorized_parent_create_time, bool)
        or not math.isfinite(float(authorized_parent_create_time))
        or float(authorized_parent_create_time) <= 0
        or abs(float(authorized_parent_create_time) - parent_create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveWorkerError("worker authorization parent create-time identity mismatch")
    authorized_supervisor_create_time = authorization.get(
        "supervisor_process_create_time"
    )
    if (
        not isinstance(authorized_supervisor_create_time, (int, float))
        or isinstance(authorized_supervisor_create_time, bool)
        or not math.isfinite(float(authorized_supervisor_create_time))
        or float(authorized_supervisor_create_time) <= 0
        or abs(float(authorized_supervisor_create_time) - float(supervisor_create_time))
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveWorkerError(
            "worker authorization supervisor create-time identity mismatch"
        )
    launcher_pid = authorization.get("launcher_pid")
    launcher_create_time = authorization.get("launcher_process_create_time")
    launcher_delegated = authorization.get("launcher_delegated")
    bound_launcher_pid = binding.get("launcher_pid")
    bound_launcher_create_time = binding.get("launcher_process_create_time")
    if (
        not isinstance(launcher_pid, int)
        or isinstance(launcher_pid, bool)
        or launcher_pid <= 0
        or not isinstance(launcher_create_time, (int, float))
        or isinstance(launcher_create_time, bool)
        or not math.isfinite(float(launcher_create_time))
        or float(launcher_create_time) <= 0
        or not isinstance(launcher_delegated, bool)
        or launcher_pid != bound_launcher_pid
        or not isinstance(bound_launcher_create_time, (int, float))
        or isinstance(bound_launcher_create_time, bool)
        or not math.isfinite(float(bound_launcher_create_time))
        or float(bound_launcher_create_time) <= 0
        or abs(float(launcher_create_time) - float(bound_launcher_create_time))
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
        or (
            launcher_delegated
            and (
                launcher_pid != parent_pid
                or abs(float(launcher_create_time) - parent_create_time)
                > _WORKER_IDENTITY_TOLERANCE_SECONDS
            )
        )
        or (
            not launcher_delegated
            and (
                launcher_pid != pid
                or abs(float(launcher_create_time) - create_time)
                > _WORKER_IDENTITY_TOLERANCE_SECONDS
            )
        )
    ):
        raise LiveWorkerError("worker authorization launcher identity mismatch")
    current_pid, current_create_time = _current_worker_identity()
    if (
        current_pid != pid
        or abs(current_create_time - create_time)
        > _WORKER_IDENTITY_TOLERANCE_SECONDS
    ):
        raise LiveWorkerError("worker identity changed after parent authorization")


def _verify_request(request_path: Path) -> tuple[dict[str, Any], str, Any]:
    request, request_sha256 = read_json_with_digest(request_path)
    if request.get("schema_version") != 1 or request.get("action") != "run":
        raise LiveWorkerError("live request requires schema_version=1 and action='run'")
    if request.get("hec_ras_execution_enabled") is not True:
        raise LiveWorkerError("live request lacks explicit HEC-RAS execution acknowledgement")
    attempt_dir = request_path.parent.resolve(strict=True)
    if request.get("lane_id") != attempt_dir.parent.name:
        raise LiveWorkerError("request lane_id disagrees with attempt path")
    if request.get("attempt_id") != attempt_dir.name:
        raise LiveWorkerError("request attempt_id disagrees with attempt path")
    context = load_run(attempt_dir.parents[2])
    if context.descriptor.get("hec_ras_execution_enabled") is not False:
        raise LiveWorkerError("live attempts must originate from an inert run descriptor")
    context = _revalidate_environment(request, context)

    repository_root = Path(str(request.get("repository_root", ""))).resolve(strict=True)
    if not _same_file(repository_root, Path(context.descriptor["repository_root"])):
        raise LiveWorkerError("live worker repository root does not match run pin")
    if request.get("git_head") != context.descriptor["git_head"]:
        raise LiveWorkerError("live worker git HEAD does not match run pin")
    manifest_path = Path(str(request.get("normalized_manifest_path", ""))).resolve(
        strict=True
    )
    if manifest_path != context.run_root / "manifest.normalized.json":
        raise LiveWorkerError("live request normalized manifest path mismatch")
    manifest, manifest_file_sha256 = read_json_with_digest(manifest_path)
    if manifest_file_sha256 != request.get("normalized_manifest_sha256"):
        raise LiveWorkerError("live normalized manifest file digest mismatch")
    claimed_manifest_hash = manifest.pop("manifest_sha256", None)
    if canonical_sha256(manifest) != claimed_manifest_hash:
        raise LiveWorkerError("live normalized manifest canonical hash mismatch")
    manifest["manifest_sha256"] = claimed_manifest_hash
    if claimed_manifest_hash != request.get("manifest_sha256"):
        raise LiveWorkerError("live request manifest identity mismatch")

    lane, fixture, engine = select_lane(context, request["lane_id"])
    if (
        lane != request.get("lane")
        or fixture != request.get("fixture")
        or engine != request.get("engine")
    ):
        raise LiveWorkerError("live request lane expansion disagrees with manifest")
    preflight_timeout_seconds = _strict_positive_seconds(
        request.get("preflight_timeout_seconds"),
        label="live request preflight_timeout_seconds",
    )
    timeout_seconds = _strict_positive_seconds(
        request.get("timeout_seconds"),
        label="live request timeout_seconds",
    )
    termination_grace_seconds = _strict_positive_seconds(
        request.get("termination_grace_seconds"),
        label="live request termination_grace_seconds",
    )
    postflight_timeout_seconds = _strict_positive_seconds(
        request.get("postflight_timeout_seconds"),
        label="live request postflight_timeout_seconds",
    )
    receipt_margin_seconds = _strict_positive_seconds(
        request.get("supervisor_receipt_margin_seconds"),
        label="live request supervisor_receipt_margin_seconds",
    )
    if (
        preflight_timeout_seconds
        != float(context.manifest["defaults"]["preflight_timeout_seconds"])
        or timeout_seconds
        != float(context.manifest["defaults"]["timeout_seconds"])
        or termination_grace_seconds
        != float(context.manifest["defaults"]["termination_grace_seconds"])
        or postflight_timeout_seconds
        != float(context.manifest["defaults"]["postflight_timeout_seconds"])
        or receipt_margin_seconds != _SUPERVISOR_RECEIPT_MARGIN_SECONDS
    ):
        raise LiveWorkerError("live request timeout contract disagrees with manifest")
    if fixture.get("source_kind") != "project_file":
        raise LiveWorkerError("live worker currently requires source_kind=project_file")
    if engine.get("support_state") != "supported":
        raise LiveWorkerError("live worker refuses a non-supported engine lane")
    if lane.get("expected_terminal_category") != "passed":
        raise LiveWorkerError("live worker currently accepts normal passing lanes only")
    required = request.get("required_invariants")
    if required != lane.get("required_invariants") or set(required or ()) != _NORMAL_LIVE_INVARIANTS:
        raise LiveWorkerError(
            "normal live request requires exactly R01,R02,R03,R04,R06,R10,R11,R12"
        )
    baseline = request.get("process_baseline")
    if not isinstance(baseline, list) or baseline:
        raise LiveWorkerError("live process baseline must be a proved-empty array")
    baseline_evidence = request.get("process_baseline_evidence")
    if not isinstance(baseline_evidence, Mapping):
        raise LiveWorkerError("live request lacks structured process baseline evidence")
    if (
        baseline_evidence.get("complete") is not True
        or baseline_evidence.get("processes") != baseline
        or baseline_evidence.get("query_errors") != []
    ):
        raise LiveWorkerError("live process baseline evidence is incomplete or nonempty")

    source_project = Path(str(request.get("source_project", ""))).resolve(strict=True)
    if not _same_file(source_project, Path(fixture["source_project"])):
        raise LiveWorkerError("live request source project disagrees with fixture")
    expected_stage_root = (
        Path(context.descriptor["execution_run_root"])
        / request["lane_id"]
        / request["attempt_id"]
        / "stage"
    ).resolve(strict=False)
    if Path(str(request.get("stage_root", ""))).resolve(strict=False) != expected_stage_root:
        raise LiveWorkerError("live request stage root escaped its attempt path")
    if expected_stage_root.exists():
        raise LiveWorkerError("live request stage root already exists")
    _verify_real_engine_lock(request)
    return request, request_sha256, context


def _record_payload(value: Any, *, label: str) -> dict[str, Any]:
    serializer = getattr(value, "to_dict", None)
    if not callable(serializer):
        raise LiveCapabilityError(f"{label} lacks the required JSON-safe to_dict()")
    payload = serializer()
    if not isinstance(payload, Mapping):
        raise LiveCapabilityError(f"{label}.to_dict() did not return an object")
    safe = json_safe(dict(payload))
    try:
        json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LiveCapabilityError(f"{label} is not strict JSON data") from exc
    return safe


def _read_tcu_status(RasTcu: Any, engine: Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate TCU status for the request's exact engine pin."""
    status_method = getattr(RasTcu, "status", None)
    if not callable(status_method):
        raise LiveCapabilityError("RasTcu.status is unavailable")
    ras_version = engine.get("executable") or engine.get("version_requested")
    if not isinstance(ras_version, str) or not ras_version:
        raise LiveCapabilityError("live engine lacks an exact TCU version/path pin")
    try:
        status = status_method(ras_version=ras_version)
    except Exception as exc:
        raise LiveTcuGateError(
            f"RasTcu.status failed for exact engine pin {ras_version!r}"
        ) from exc

    missing = [
        field
        for field in ("accepted", "version", "install_dir", "registry_key", "reason")
        if not hasattr(status, field)
    ]
    if missing:
        raise LiveCapabilityError(
            "RasTcu.status result is missing fields: " + ", ".join(missing)
        )
    accepted = status.accepted
    if accepted is not True and accepted is not False and accepted is not None:
        raise LiveCapabilityError("RasTcu.status accepted must be true, false, or null")
    reason = status.reason
    if not isinstance(reason, str) or not reason:
        raise LiveCapabilityError("RasTcu.status reason must be a nonempty string")
    for field in ("version", "install_dir", "registry_key"):
        value = getattr(status, field)
        if value is not None and not isinstance(value, str):
            raise LiveCapabilityError(f"RasTcu.status {field} must be a string or null")
    if status.version != ras_version:
        raise LiveTcuGateError(
            "RasTcu.status did not preserve the exact requested engine version/path"
        )
    executable = engine.get("executable") or engine.get("controller_executable")
    if isinstance(executable, str) and executable:
        install_dir = status.install_dir
        if not isinstance(install_dir, str) or not _same_file(
            Path(install_dir), Path(executable).resolve(strict=True).parent
        ):
            raise LiveTcuGateError(
                "RasTcu.status install directory does not match the pinned executable"
            )

    payload = json_safe(
        {
            "accepted": accepted,
            "version": status.version,
            "install_dir": status.install_dir,
            "registry_key": status.registry_key,
            "reason": reason,
            "ras_version_argument": ras_version,
        }
    )
    try:
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LiveCapabilityError("RasTcu.status is not strict JSON data") from exc
    return payload


_LIVE_ASSET_GATE_COLUMNS = {
    "asset_kind": pyarrow.string(),
    "asset_role": pyarrow.string(),
    "required": pyarrow.bool_(),
    "reference_raw": pyarrow.string(),
    "resolved_path": pyarrow.string(),
    "path_scope": pyarrow.string(),
    "portable": pyarrow.bool_(),
    "inspection_state": pyarrow.string(),
    "readiness": pyarrow.string(),
    "reason_code": pyarrow.string(),
}
_EXECUTION_ASSET_ROLES = frozenset(
    {"declared_input", "derived_prerequisite", "unknown"}
)


def _asset_finding(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "asset_kind",
        "asset_role",
        "required",
        "reference_raw",
        "resolved_path",
        "path_scope",
        "portable",
        "inspection_state",
        "readiness",
        "reason_code",
    )
    finding: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        finding[field] = None if pd.isna(value) else value
    return json_safe(finding)


def _path_is_within(root: Path, raw_path: Any) -> bool:
    if raw_path is None or pd.isna(raw_path):
        return False
    try:
        root_real = os.path.normcase(os.path.realpath(root))
        path_real = os.path.normcase(os.path.realpath(str(raw_path)))
        return os.path.commonpath([root_real, path_real]) == root_real
    except (OSError, TypeError, ValueError):
        return False


def _require_live_stage_assets_safe(
    assets: Any,
    *,
    stage_root: Path,
) -> dict[str, Any]:
    """Prove that execution-relevant assets are contained by the stage.

    ``stage_project`` currently copies the project directory but deliberately
    preserves references to assets outside that directory.  The live harness
    snapshots only the source project directory, so it cannot prove external
    asset immutability or guarantee that execution will not mutate/read an
    unpinned dependency.  Until external assets can be pinned, copied, and
    references rewritten, this gate rejects every required or potentially
    required execution dependency whose containment is not proved internal.
    """
    if not isinstance(assets, pd.DataFrame) or assets.empty:
        raise LiveCapabilityError(
            "stage_project.assets must be a nonempty pandas DataFrame"
        )
    missing = sorted(set(_LIVE_ASSET_GATE_COLUMNS) - set(assets.columns))
    if missing:
        raise LiveCapabilityError(
            "stage_project.assets is missing live-gate columns: "
            + ", ".join(missing)
        )
    wrong_dtypes = []
    for column, expected in _LIVE_ASSET_GATE_COLUMNS.items():
        dtype = assets[column].dtype
        if not isinstance(dtype, pd.ArrowDtype) or dtype.pyarrow_dtype != expected:
            wrong_dtypes.append(f"{column}={dtype}")
    if wrong_dtypes:
        raise LiveCapabilityError(
            "stage_project.assets must preserve PyArrow-backed gate dtypes: "
            + ", ".join(wrong_dtypes)
        )

    required = assets["required"].eq(True).fillna(False)  # noqa: E712
    explicitly_optional = assets["required"].eq(False).fillna(False)  # noqa: E712
    execution_role = assets["asset_role"].isin(_EXECUTION_ASSET_ROLES).fillna(False)
    execution_candidate = required | (~explicitly_optional & execution_role)
    external = assets["path_scope"].eq("external").fillna(False)
    internal = assets["path_scope"].eq("internal").fillna(False)

    external_rows = assets.loc[execution_candidate & external]
    if not external_rows.empty:
        findings = [
            _asset_finding(row)
            for row in external_rows.head(20).to_dict(orient="records")
        ]
        raise LiveAssetGateError(
            "external_execution_asset",
            "live execution would be able to access an external linked asset "
            "that was not copied into the disposable stage",
            findings=findings,
        )

    unproved_scope_rows = assets.loc[execution_candidate & ~internal]
    if not unproved_scope_rows.empty:
        findings = [
            _asset_finding(row)
            for row in unproved_scope_rows.head(20).to_dict(orient="records")
        ]
        raise LiveAssetGateError(
            "execution_asset_scope_unproved",
            "an execution-relevant asset was not proved internal to the "
            "disposable stage",
            findings=findings,
        )

    containment_mismatch = execution_candidate & ~assets["resolved_path"].map(
        lambda value: _path_is_within(stage_root, value)
    )
    containment_rows = assets.loc[containment_mismatch]
    if not containment_rows.empty:
        findings = [
            _asset_finding(row)
            for row in containment_rows.head(20).to_dict(orient="records")
        ]
        raise LiveAssetGateError(
            "execution_asset_containment_mismatch",
            "an execution-relevant asset path was not physically contained by "
            "the disposable stage despite its inventory scope",
            findings=findings,
        )

    required_unready = required & (
        ~assets["inspection_state"].eq("available").fillna(False)
        | ~assets["readiness"].eq("ready").fillna(False)
        | ~assets["portable"].eq(True).fillna(False)  # noqa: E712
    )
    unready_rows = assets.loc[required_unready]
    if not unready_rows.empty:
        findings = [
            _asset_finding(row)
            for row in unready_rows.head(20).to_dict(orient="records")
        ]
        raise LiveAssetGateError(
            "required_execution_asset_unready",
            "a required asset was not proved available, ready, portable, and "
            "internal to the disposable stage",
            findings=findings,
        )

    return {
        "asset_count": len(assets),
        "required_asset_count": int(required.sum()),
        "execution_candidate_count": int(execution_candidate.sum()),
        "external_execution_asset_count": 0,
    }


def _require_capabilities(RasCmdr: Any, RasControl: Any) -> None:
    required = (
        (RasControl, "inspect_processes"),
        (RasCmdr, "inspect_plan_processes"),
        (RasCmdr, "cancel_plan_exact"),
    )
    missing = [name for owner, name in required if not callable(getattr(owner, name, None))]
    if missing:
        raise LiveCapabilityError(
            "structured live-process capabilities are unavailable: "
            + ", ".join(sorted(missing))
        )


def _require_inventory_empty(
    inventory: Any,
    *,
    label: str,
    collection_field: str,
) -> dict[str, Any]:
    payload = _record_payload(inventory, label=label)
    if payload.get("complete") is not True:
        raise LiveProcessGateError(f"{label} is incomplete")
    query_errors = payload.get("query_errors")
    if not isinstance(query_errors, list) or query_errors:
        raise LiveProcessGateError(f"{label} contains unresolved process-query errors")
    processes = payload.get(collection_field)
    if not isinstance(processes, list):
        raise LiveCapabilityError(f"{label}.{collection_field} is not an array")
    if processes:
        raise LiveProcessGateError(f"{label} found {len(processes)} process record(s)")
    return payload


def _require_plan_inventory_identity(
    payload: Mapping[str, Any],
    *,
    plan_number: str,
    project_file: Path,
) -> None:
    if payload.get("plan_number") != plan_number:
        raise LiveProcessGateError("plan process inventory returned the wrong plan number")
    observed_project = Path(str(payload.get("project_path", ""))).resolve(strict=True)
    if not _same_file(observed_project, project_file.resolve(strict=True)):
        raise LiveProcessGateError("plan process inventory returned the wrong project")
    expected_plan = project_file.parent / f"{project_file.stem}.p{plan_number}"
    observed_plan = Path(str(payload.get("plan_path", ""))).resolve(strict=True)
    if not _same_file(observed_plan, expected_plan.resolve(strict=True)):
        raise LiveProcessGateError("plan process inventory returned the wrong plan file")


def _cleanup_payload(cleanup: Any) -> dict[str, Any]:
    return {
        "plan_number": cleanup.plan_number,
        "result_format": cleanup.result_format,
        "include_message_sidecars": cleanup.include_message_sidecars,
        "removed_paths": [str(path) for path in cleanup.removed_paths],
        "missing_paths": [str(path) for path in cleanup.missing_paths],
    }


def _prepare_initial_state(
    request: Mapping[str, Any],
    *,
    RasCmdr: Any,
    ras_object: Any,
) -> list[dict[str, Any]]:
    plan_number = request["fixture"]["plan_number"]
    expected = request["engine"]["expected_result_format"]
    initial_state = request["lane"]["initial_state"]
    calls: list[tuple[str, bool]] = []
    if initial_state == "neither":
        calls.append(("both", True))
    elif initial_state == "expected_only":
        calls.append(("legacy" if expected == "hdf" else "hdf", False))
    elif initial_state == "opposing_only":
        calls.append((expected, False))
    elif initial_state not in {
        "both_expected_newer",
        "both_opposing_newer",
        "both_equal_mtime",
        "copied_preserved_times",
        "copied_rewritten_times",
    }:
        raise LiveWorkerError(f"unsupported live initial state: {initial_state}")
    records = []
    for result_format, include_sidecars in calls:
        cleanup = RasCmdr.remove_plan_execution_artifacts(
            plan_number,
            result_format=result_format,
            include_message_sidecars=include_sidecars,
            ras_object=ras_object,
        )
        records.append(_cleanup_payload(cleanup))
    return records


def _result_row(
    snapshot: Any,
    family: str,
    *,
    project_file: str | Path,
    plan_number: str,
) -> Mapping[str, Any] | None:
    known_paths = known_result_paths(project_file, plan_number)
    selected_path = known_paths[0 if family == "hdf" else 1].casefold()
    return next(
        (
            row
            for row in snapshot.rows
            if row.get("exists")
            and row.get("result_family") == family
            and isinstance(row.get("relative_path"), str)
            and row["relative_path"].casefold() == selected_path
        ),
        None,
    )


def _validate_pre_execution_state(
    request: Mapping[str, Any],
    *,
    stage_published: Any,
    pre_execution: Any,
) -> None:
    expected = request["engine"]["expected_result_format"]
    opposing = "legacy" if expected == "hdf" else "hdf"
    initial_state = request["lane"]["initial_state"]
    project_file = request["source_project"]
    plan_number = request["fixture"]["plan_number"]
    hdf_exists, legacy_exists = result_population(
        pre_execution.rows,
        project_file=project_file,
        plan_number=plan_number,
    )
    population = {"hdf": hdf_exists, "legacy": legacy_exists}
    expected_population = {
        "neither": {"hdf": False, "legacy": False},
        "expected_only": {expected: True, opposing: False},
        "opposing_only": {expected: False, opposing: True},
        "both_expected_newer": {"hdf": True, "legacy": True},
        "both_opposing_newer": {"hdf": True, "legacy": True},
        "both_equal_mtime": {"hdf": True, "legacy": True},
    }.get(initial_state)
    if expected_population is not None and population != expected_population:
        raise LiveWorkerError(
            f"prepared {initial_state} population mismatch: {population}"
        )
    if initial_state.startswith("both_"):
        expected_row = _result_row(
            stage_published,
            expected,
            project_file=project_file,
            plan_number=plan_number,
        )
        opposing_row = _result_row(
            stage_published,
            opposing,
            project_file=project_file,
            plan_number=plan_number,
        )
        if expected_row is None or opposing_row is None:
            raise LiveWorkerError(f"{initial_state} requires both result families")
        expected_mtime = expected_row["mtime_ns"]
        opposing_mtime = opposing_row["mtime_ns"]
        valid = {
            "both_expected_newer": expected_mtime > opposing_mtime,
            "both_opposing_newer": opposing_mtime > expected_mtime,
            "both_equal_mtime": opposing_mtime == expected_mtime,
        }[initial_state]
        if not valid:
            raise LiveWorkerError(f"{initial_state} timestamp ordering is not present")


def _post_execution_origins(
    request: Mapping[str, Any],
    *,
    before: TreeSnapshot,
    after: TreeSnapshot,
    known_paths: Sequence[str],
) -> dict[str, str]:
    # ``snapshot_tree`` inventories the spelling preserved by the filesystem,
    # while HEC-RAS may capitalize generated plan artifacts differently from
    # the canonical known paths (for example ``EX1.P01.hdf`` versus
    # ``EX1.p01.hdf``).  Store override keys in the same case-folded namespace
    # used by the snapshot inventory so provenance follows path identity on
    # Windows instead of the producer's incidental casing.
    overrides = {".ras-commander/stage.json".casefold(): "generated_harness_receipt"}
    replay = request["fixture"].get("replay_artifacts")
    pinned = {
        item["relative_path"].casefold(): item
        for item in (replay or {}).get("files", [])
    }
    known = {Path(relative).as_posix().casefold() for relative in known_paths}
    before_rows = {
        row["relative_path"].casefold(): row
        for row in before.rows
    }
    identity_fields = (
        "exists",
        "is_file",
        "size_bytes",
        "mtime_ns",
        "volume_id",
        "file_id",
        "sha256",
    )
    for row in after.rows:
        key = row["relative_path"].casefold()
        if key == ".ras-commander/stage.json":
            continue
        pin = pinned.get(key)
        prior = before_rows.get(key)
        exact_replay = (
            key in known
            and pin is not None
            and row["exists"] is True
            and row["sha256"] == pin["sha256"]
            and row["size_bytes"] == pin["size_bytes"]
            and row["mtime_ns"] == pin["mtime_ns"]
        )
        unchanged = prior is not None and all(
            prior[field] == row[field] for field in identity_fields
        )
        if exact_replay:
            overrides[key] = replay["data_origin"]
        elif unchanged:
            overrides[key] = prior["data_origin"]
        else:
            overrides[key] = "staged_execution_output"
    return overrides


def _with_origin_overrides(
    snapshot: TreeSnapshot,
    overrides: Mapping[str, str],
) -> TreeSnapshot:
    rows = []
    for row in snapshot.rows:
        updated = dict(row)
        key = row["relative_path"].casefold()
        updated["data_origin"] = overrides.get(
            row["relative_path"],
            overrides.get(key, row["data_origin"]),
        )
        rows.append(updated)
    return replace(snapshot, rows=tuple(rows))


def _write_messages(
    attempt_dir: Path,
    messages: Any,
) -> tuple[int, dict[str, str] | None]:
    if messages is None:
        return 0, None
    if not isinstance(messages, (list, tuple)) or any(
        not isinstance(item, str) for item in messages
    ):
        raise LiveCapabilityError("Controller messages must be an array of strings")
    if not messages:
        return 0, None
    body = "".join(
        f"===== Controller message {index} =====\n{message}\n"
        for index, message in enumerate(messages, start=1)
    ).encode("utf-8")
    path = attempt_dir / "messages.txt"
    write_bytes_with_digest(path, body)
    return len(messages), _artifact_reference(attempt_dir, path)


def _validate_execution_result(
    request: Mapping[str, Any],
    result: Any,
    *,
    expected_launch_details: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], bool, bool | None, int, list[dict[str, str]]]:
    success = getattr(result, "success", None)
    if not isinstance(success, bool):
        raise LiveCapabilityError("execution result lacks an explicit boolean success field")
    details = getattr(result, "execution_details", None)
    if not isinstance(details, Mapping):
        raise LiveCapabilityError("execution result lacks structured execution_details")
    details = json_safe(dict(details))
    missing = [field for field in _ENGINE_DETAILS_COMMON if field not in details]
    if missing:
        raise LiveCapabilityError(
            "execution_details is missing required fields: " + ", ".join(missing)
        )
    expected_format = request["engine"]["expected_result_format"]
    common_checks = {
        "calculation_attempted": details["calculation_attempted"] is True,
        "selected_result_format": details["selected_result_format"] == expected_format,
        "solver_quiescence_confirmed": details["solver_quiescence_confirmed"] is True,
    }
    failed = [field for field, passed in common_checks.items() if not passed]
    if failed:
        raise LiveProcessGateError(
            "execution result did not prove safe finalization: " + ", ".join(failed)
        )
    _execution_cleanup_removed_relative_paths(request, details)
    if details.get("actual_engine_provenance_confirmed") is not True:
        raise LiveCapabilityError("actual execution-engine provenance was not confirmed")
    engine = request["engine"]
    if details.get("execution_api") != engine["execution_api"]:
        raise LiveCapabilityError("execution_details API identity mismatch")
    if engine["execution_api"] == "ras_cmdr":
        missing_runtime = [
            field for field in _RASCMD_RUNTIME_DETAIL_FIELDS if field not in details
        ]
        if missing_runtime:
            raise LiveCapabilityError(
                "RasCmdr execution_details is missing runtime fields: "
                + ", ".join(sorted(missing_runtime))
            )
        artifacts_finalized = _validate_artifact_finalization_evidence(details)
        max_runtime = _strict_positive_seconds(
            details["max_runtime_seconds"],
            label="RasCmdr execution_details max_runtime_seconds",
        )
        if max_runtime != float(request["timeout_seconds"]):
            raise LiveCapabilityError("RasCmdr max-runtime evidence mismatch")
        if expected_launch_details is None:
            raise LiveCapabilityError(
                "RasCmdr returned without a durable post-launch callback"
            )
        if details["launch_details"] != json_safe(dict(expected_launch_details)):
            raise LiveCapabilityError(
                "RasCmdr returned launch details disagree with the durable callback"
            )
        launcher_returncode = details["launcher_returncode"]
        if launcher_returncode is not None and (
            isinstance(launcher_returncode, bool)
            or not isinstance(launcher_returncode, int)
        ):
            raise LiveCapabilityError(
                "RasCmdr launcher return code is not an integer or null"
            )
        executable = Path(engine["executable"]).resolve(strict=True)
        detail_path = Path(str(details.get("selected_executable_path", ""))).resolve(
            strict=True
        )
        if details.get("engine_kind") != "executable":
            raise LiveCapabilityError("RasCmdr execution_details engine_kind mismatch")
        if not _same_file(executable, detail_path):
            raise LiveCapabilityError("RasCmdr selected executable path mismatch")
        if details.get("selected_executable_sha256") != engine["executable_sha256"]:
            raise LiveCapabilityError("RasCmdr selected executable hash mismatch")
        if not _valid_process_identity(
            details.get("launcher_pid"),
            details.get("launcher_create_time"),
        ):
            raise LiveCapabilityError(
                "RasCmdr launcher PID/create-time identity was not proved"
            )
        if (
            details["launcher_pid"] != expected_launch_details["launcher_pid"]
            or float(details["launcher_create_time"])
            != float(expected_launch_details["launcher_create_time"])
        ):
            raise LiveCapabilityError(
                "RasCmdr returned launcher identity disagrees with launch callback"
            )
        completion_verified = getattr(result, "completion_verified", None)
        if success:
            if not artifacts_finalized:
                raise LiveCapabilityError(
                    "successful RasCmdr result did not finalize result artifacts"
                )
            if launcher_returncode is None:
                raise LiveCapabilityError(
                    "RasCmdr successful result lacks a launcher return code"
                )
            if details["runtime_timed_out"] is not False:
                raise LiveProcessGateError(
                    "RasCmdr successful result claims a runtime timeout"
                )
            failure_values = {
                field: details[field]
                for field in ("failure_stage", "failure_type", "failure_detail")
            }
            if any(value is not None for value in failure_values.values()):
                raise LiveCapabilityError(
                    "RasCmdr successful result contains failure metadata"
                )
            if details["cancellation_details"] is not None:
                raise LiveCapabilityError(
                    "RasCmdr successful result contains cancellation metadata"
                )
            if completion_verified is not True:
                raise LiveCapabilityError(
                    "RasCmdr verify=True did not confirm completion"
                )
        else:
            if not isinstance(completion_verified, bool):
                raise LiveCapabilityError(
                    "RasCmdr failed result lacks a boolean completion claim"
                )
            _validate_safe_rascmd_failure(
                request,
                details,
                expected_launch_details,
            )
    else:
        if details["result_artifacts_finalized"] is not True:
            raise LiveProcessGateError(
                "RasControl execution did not prove safe result finalization"
            )
        if details.get("engine_kind") != "controller":
            raise LiveCapabilityError("RasControl execution_details engine_kind mismatch")
        if details.get("requested_controller_version") != engine["controller_version"]:
            raise LiveCapabilityError(
                "RasControl requested Controller version was not preserved exactly"
            )
        if details.get("controller_progid") != engine["controller_progid"]:
            raise LiveCapabilityError("RasControl Controller ProgID mismatch")
        if details.get("resolved_controller_version") != engine["resolved_controller_version"]:
            raise LiveCapabilityError("RasControl resolved Controller version mismatch")
        expected_controller_executable = Path(
            engine["controller_executable"]
        ).resolve(strict=True)
        try:
            observed_controller_executable = Path(
                str(details.get("controller_executable_path", ""))
            ).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise LiveCapabilityError(
                "RasControl Controller executable path was not proved"
            ) from exc
        if not _same_file(
            expected_controller_executable,
            observed_controller_executable,
        ):
            raise LiveCapabilityError(
                "RasControl Controller executable path mismatch"
            )
        if (
            details.get("controller_executable_sha256")
            != engine["controller_executable_sha256"]
        ):
            raise LiveCapabilityError(
                "RasControl Controller executable hash mismatch"
            )
        if not _valid_process_identity(
            details.get("controller_pid"),
            details.get("controller_create_time"),
        ):
            raise LiveCapabilityError(
                "RasControl Controller PID/create-time identity was not proved"
            )
        expected_mode = "blocking" if engine["blocking"] else "poll"
        if details.get("compute_mode") != expected_mode:
            raise LiveCapabilityError("RasControl blocking mode evidence mismatch")
        if details.get("watchdog_requested") is not True:
            raise LiveCapabilityError("RasControl watchdog request was not recorded")
        if details.get("watchdog_started") is not True:
            raise LiveProcessGateError("RasControl watchdog start was not confirmed")
        if details.get("strict_close_requested") is not True:
            raise LiveCapabilityError("RasControl strict-close request was not recorded")
        max_runtime = details.get("max_runtime_seconds")
        if (
            isinstance(max_runtime, bool)
            or not isinstance(max_runtime, (int, float))
            or float(max_runtime) != float(request["timeout_seconds"])
        ):
            raise LiveCapabilityError("RasControl max-runtime evidence mismatch")
        if details.get("controller_close_safe") is not True:
            raise LiveProcessGateError("RasControl did not prove a safe Controller close")
        if details.get("owned_process_exit_confirmed") is not True:
            raise LiveProcessGateError("RasControl did not prove owned-process exit")
        if details.get("post_close_plan_processes_quiescent") is not True:
            raise LiveProcessGateError(
                "RasControl did not prove post-close plan-process quiescence"
            )
        if details.get("post_close_global_processes_quiescent") is not True:
            raise LiveProcessGateError(
                "RasControl did not prove post-close host-process quiescence"
            )
        completion_verified = None
    messages = getattr(result, "messages", None)
    message_count = 0 if messages is None else len(messages)
    return details, success, completion_verified, message_count, []


def _authoritative_channels(evidence: Any) -> list[str]:
    completion_names = {
        "completion_attribute",
        "completion_message_hdf",
        "completion_message_stored",
        "message_error_count",
        "message_warning_count",
        "message_first_error",
        "runtime_seconds",
        "process_success",
        "com_completion",
    }
    channels = [evidence.mechanical_completion.channel]
    channels.extend(
        observation.channel
        for name, observation in evidence.observations.items()
        if name in completion_names and observation.state == "available"
    )
    return channels


def _perform(request: dict[str, Any], request_sha256: str, context: Any) -> int:
    global _WORKER_INVOCATIONS
    _WORKER_INVOCATIONS += 1
    started_at = datetime.now(timezone.utc)
    attempt_dir = context.run_root / "attempts" / request["lane_id"] / request["attempt_id"]
    events_path = attempt_dir / "events.jsonl"
    events = EventJournal(
        events_path,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
    )
    events.append(
        phase="request",
        event_name="live_request_verified",
        status="passed",
        api="live_worker",
        pid=os.getpid(),
    )

    from ras_commander import (
        RasCmdr,
        RasControl,
        RasPrj,
        RasTcu,
        ResultArtifactAmbiguityError,
        STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM,
        init_ras_project,
        stage_project,
    )

    _require_capabilities(RasCmdr, RasControl)
    lock_payload = _verify_real_engine_lock(request)
    pre_stage_global = _require_inventory_empty(
        RasControl.inspect_processes(),
        label="pre-stage global process inventory",
        collection_field="processes",
    )
    events.append(
        phase="process_gate",
        event_name="pre_stage_process_gate_passed",
        status="passed",
        api="RasControl.inspect_processes",
        payload={"inventory": pre_stage_global},
    )

    tcu_status = _read_tcu_status(RasTcu, request["engine"])
    tcu_accepted = tcu_status["accepted"] is True
    events.append(
        phase="tcu_gate",
        event_name=(
            "tcu_acceptance_preflight_passed"
            if tcu_accepted
            else "tcu_acceptance_preflight_rejected"
        ),
        status="passed" if tcu_accepted else "failed",
        severity="info" if tcu_accepted else "error",
        api="RasTcu.status",
        reason_code=None if tcu_accepted else "tcu_acceptance_not_confirmed",
        detail=(
            None
            if tcu_accepted
            else "exact-engine TCU acceptance must be explicitly true before staging"
        ),
        payload={"tcu_status": tcu_status},
    )
    if not tcu_accepted:
        raise LiveTcuGateError(
            "exact-engine TCU acceptance was not confirmed: "
            f"accepted={tcu_status['accepted']!r}, reason={tcu_status['reason']!r}"
        )

    source_project = Path(request["source_project"])
    plan_number = request["fixture"]["plan_number"]
    source_known_paths = known_result_paths(source_project, plan_number)
    source_before = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_before_stage",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=source_known_paths,
    )
    if (
        source_before.fingerprint_algorithm
        != request["source_snapshot_content_fingerprint_algorithm"]
        or source_before.fingerprint_algorithm
        != request["fixture"]["source_content_fingerprint_algorithm"]
        or source_before.fingerprint_algorithm
        != QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
        or source_before.content_fingerprint
        != request["source_snapshot_content_fingerprint"]
        or source_before.content_fingerprint
        != request["fixture"]["source_content_fingerprint"]
        or source_before.metadata_fingerprint
        != request["source_snapshot_metadata_fingerprint"]
    ):
        raise LiveWorkerError(
            "qualification source fingerprint gate failed before staging"
        )

    stage_root = Path(request["stage_root"])
    stage_result = stage_project(source_project, stage_root)
    expected_source = request["fixture"]["source_content_fingerprint"]
    stage_source_valid = (
        stage_result.publication_state == "published"
        and stage_result.fingerprint_algorithm
        == STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM
        and stage_result.source_fingerprint_before
        == stage_result.source_fingerprint_after
        == stage_result.copied_fingerprint
    )
    if not stage_source_valid:
        raise LiveWorkerError("public stage_project source/readiness gate failed")
    try:
        asset_gate = _require_live_stage_assets_safe(
            stage_result.assets,
            stage_root=stage_result.destination_root,
        )
        if stage_result.execution_readiness != "ready":
            raise LiveAssetGateError(
                "stage_execution_readiness_unproved",
                "stage_project did not prove the complete staged project ready "
                "for execution",
            )
    except (LiveAssetGateError, LiveCapabilityError) as exc:
        payload: dict[str, Any] = {}
        findings = getattr(exc, "findings", None)
        if findings:
            payload["findings"] = findings
        events.append(
            phase="stage_asset_gate",
            event_name="stage_asset_gate_rejected",
            status="failed",
            severity="error",
            api="stage_project.assets",
            reason_code=getattr(exc, "reason_code", "asset_inventory_invalid"),
            detail=str(exc),
            payload=payload or None,
        )
        raise
    events.append(
        phase="stage_asset_gate",
        event_name="stage_asset_gate_passed",
        status="passed",
        api="stage_project.assets",
        payload=asset_gate,
    )
    replay = request["fixture"].get("replay_artifacts")
    replay_records = overlay_replay_artifacts(stage_result.destination_root, replay)
    stage_relative = stage_result.destination_project_file.relative_to(
        stage_result.destination_root
    ).as_posix()
    events.append(
        phase="stage",
        event_name="stage_published",
        status="passed",
        api="stage_project",
        relative_path=stage_relative,
        payload={"replay_file_count": len(replay_records)},
    )
    stage_known_paths = known_result_paths(
        stage_result.destination_project_file, plan_number
    )
    stage_origins = replay_origin_overrides(replay)
    stage_origins[".ras-commander/stage.json"] = "generated_harness_receipt"
    stage_published = snapshot_tree(
        stage_result.destination_root,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="stage_published",
        root_kind="stage",
        data_origin=request["fixture"]["data_origin"],
        known_paths=stage_known_paths,
        origin_overrides=stage_origins,
    )

    explicit_ras = init_ras_project(
        stage_result.destination_project_file,
        ras_version=request["engine"].get("executable")
        or request["engine"]["version_requested"],
        ras_object=RasPrj(),
        load_results_summary=False,
        load_hdf_metadata=False,
        hide_intro=True,
    )
    pre_plan = _require_inventory_empty(
        RasCmdr.inspect_plan_processes(plan_number, ras_object=explicit_ras),
        label="pre-setup plan process inventory",
        collection_field="matched",
    )
    _require_plan_inventory_identity(
        pre_plan,
        plan_number=plan_number,
        project_file=stage_result.destination_project_file,
    )
    cleanup_records = _prepare_initial_state(
        request,
        RasCmdr=RasCmdr,
        ras_object=explicit_ras,
    )
    pre_execution = snapshot_tree(
        stage_result.destination_root,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="pre_execution",
        root_kind="stage",
        data_origin=request["fixture"]["data_origin"],
        known_paths=stage_known_paths,
        origin_overrides=stage_origins,
    )
    _validate_pre_execution_state(
        request,
        stage_published=stage_published,
        pre_execution=pre_execution,
    )
    events.append(
        phase="initial_state",
        event_name="initial_state_prepared",
        status="passed",
        api="RasCmdr.remove_plan_execution_artifacts",
        payload={
            "initial_state": request["lane"]["initial_state"],
            "cleanup": cleanup_records,
        },
    )

    _verify_real_engine_lock(request)
    pre_execute_global = _require_inventory_empty(
        RasControl.inspect_processes(),
        label="pre-execute global process inventory",
        collection_field="processes",
    )
    events.append(
        phase="execution",
        event_name="execution_starting",
        status="running",
        api=(
            "RasCmdr.compute_plan"
            if request["engine"]["execution_api"] == "ras_cmdr"
            else "RasControl.run_plan"
        ),
        payload={"pre_execute_inventory": pre_execute_global},
    )

    hec_ras_invoked = True
    launch_recorder: _LiveLaunchRecorder | None = None
    if request["engine"]["execution_api"] == "ras_cmdr":
        launch_recorder = _LiveLaunchRecorder(
            events=events,
            request=request,
            stage_project=stage_result.destination_project_file,
        )
        result = RasCmdr.compute_plan(
            plan_number,
            ras_object=explicit_ras,
            force_rerun=True,
            skip_existing=False,
            verify=True,
            dialog_watchdog=True,
            max_runtime=request["timeout_seconds"],
            stream_callback=launch_recorder,
        )
    else:
        result = RasControl.run_plan(
            plan_number,
            ras_object=explicit_ras,
            force_recompute=True,
            use_watchdog=True,
            max_runtime=request["timeout_seconds"],
            refresh_results=False,
            blocking=request["engine"]["blocking"],
            controller_version=request["engine"]["controller_version"],
            strict_close=True,
        )
    details, process_success, completion_verified, _, _ = _validate_execution_result(
        request,
        result,
        expected_launch_details=(
            None if launch_recorder is None else launch_recorder.launch_details
        ),
    )
    message_count, message_reference = _write_messages(
        attempt_dir, getattr(result, "messages", None)
    )
    execution_record = {
        "result_type": type(result).__name__,
        "success": process_success,
        "completion_verified": completion_verified,
        "message_count": message_count,
        "execution_details": details,
    }
    execution_path = attempt_dir / "execution_result.json"
    write_json_with_digest(execution_path, execution_record)
    events.append(
        phase="execution",
        event_name="execution_returned",
        status="passed" if process_success else "failed",
        api=(
            "RasCmdr.compute_plan"
            if request["engine"]["execution_api"] == "ras_cmdr"
            else "RasControl.run_plan"
        ),
        payload={"execution_result": execution_record},
    )

    post_plan = _require_inventory_empty(
        RasCmdr.inspect_plan_processes(plan_number, ras_object=explicit_ras),
        label="post-execution plan process inventory",
        collection_field="matched",
    )
    _require_plan_inventory_identity(
        post_plan,
        plan_number=plan_number,
        project_file=stage_result.destination_project_file,
    )
    post_global = _require_inventory_empty(
        RasControl.inspect_processes(),
        label="post-execution global process inventory",
        collection_field="processes",
    )
    events.append(
        phase="process_hygiene",
        event_name="post_execution_process_gate_passed",
        status="passed",
        api="RasCmdr.inspect_plan_processes,RasControl.inspect_processes",
        payload={"plan": post_plan, "global": post_global},
    )

    post_api = snapshot_tree(
        stage_result.destination_root,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="post_process_hygiene",
        root_kind="stage",
        data_origin=request["fixture"]["data_origin"],
        known_paths=stage_known_paths,
    )
    post_api = _with_origin_overrides(
        post_api,
        _post_execution_origins(
            request,
            before=pre_execution,
            after=post_api,
            known_paths=stage_known_paths,
        ),
    )
    inspection_started_at = datetime.now(timezone.utc)
    evidence = None
    inspection_failure = None
    try:
        evidence = RasCmdr.inspect_execution_evidence(
            plan_number,
            ras_object=explicit_ras,
            hash_files=request["hash_files"],
        )
    except ResultArtifactAmbiguityError as exc:
        if process_success or details["result_artifacts_finalized"] is not False:
            raise
        inspection_failure = exc
        evidence_payload = _failed_inspection_evidence(
            details,
            exc,
            started_at=inspection_started_at,
            failed_at=datetime.now(timezone.utc),
        )
        evidence_rows = []
    else:
        evidence_payload = evidence.to_dict()
        evidence_rows = flatten_evidence(
            evidence,
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
        )
    table_from_rows("observations", evidence_rows)
    evidence_path = attempt_dir / "evidence.json"
    evidence_sha256 = write_json_with_digest(evidence_path, evidence_payload)
    stored_evidence, stored_evidence_sha256 = read_json_with_digest(evidence_path)
    evidence_frozen = bool(
        evidence is not None
        and getattr(type(evidence), "__dataclass_params__", None)
        and type(evidence).__dataclass_params__.frozen
    )
    evidence_contract = {
        "immutable": evidence_frozen,
        "json_safe": json_safe(evidence_payload) == stored_evidence,
        "schema_valid": True,
        "stable_hashes": evidence_sha256 == stored_evidence_sha256,
    }
    post_evidence = snapshot_tree(
        stage_result.destination_root,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="post_evidence_inspection",
        root_kind="stage",
        data_origin=request["fixture"]["data_origin"],
        known_paths=stage_known_paths,
    )
    post_evidence = _with_origin_overrides(
        post_evidence,
        _post_execution_origins(
            request,
            before=pre_execution,
            after=post_evidence,
            known_paths=stage_known_paths,
        ),
    )
    if inspection_failure is None:
        events.append(
            phase="inspection",
            event_name="execution_evidence_inspected",
            status="passed",
            api="RasCmdr.inspect_execution_evidence",
            relative_path=stage_relative,
            payload={"evidence_id": evidence.evidence_id},
        )
    else:
        events.append(
            phase="inspection",
            event_name="execution_evidence_inspection_failed",
            status="failed",
            severity="error",
            api="RasCmdr.inspect_execution_evidence",
            reason_code=evidence_payload["reason_code"],
            relative_path=stage_relative,
            payload={
                "evidence_id": evidence_payload["evidence_id"],
                "evidence_kind": evidence_payload["evidence_kind"],
                "failure_type": evidence_payload["failure_type"],
                "reason_code": evidence_payload["reason_code"],
            },
        )

    source_final = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_final",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=source_known_paths,
    )
    source_immutable = (
        source_before.fingerprint_algorithm
        == source_final.fingerprint_algorithm
        == request["fixture"]["source_content_fingerprint_algorithm"]
        and source_before.content_fingerprint == source_final.content_fingerprint
        and source_before.content_fingerprint == expected_source
        and source_before.metadata_fingerprint == source_final.metadata_fingerprint
    )
    selected_format = (
        details["selected_result_format"]
        if inspection_failure is not None
        else selected_result_format(evidence)
    )
    final_hdf, final_legacy = result_population(
        post_evidence.rows,
        project_file=stage_result.destination_project_file,
        plan_number=plan_number,
    )
    final_family_valid = (
        (selected_format == "hdf" and final_hdf and not final_legacy)
        or (selected_format == "legacy" and final_legacy and not final_hdf)
    )
    stage_diff = diff_snapshots(stage_published, post_api)
    cleanup_deleted = []
    for index, cleanup in enumerate(cleanup_records):
        cleanup_deleted.extend(
            _cleanup_removed_relative_paths(
                request,
                cleanup,
                label=f"initial-state cleanup {index}",
            )
        )
    cleanup_deleted.extend(
        _execution_cleanup_removed_relative_paths(request, details)
    )
    deleted_paths = {
        path.casefold(): path
        for path in (*stage_diff.removed, *cleanup_deleted)
    }
    snapshot_ids = [
        source_before.snapshot_id,
        stage_published.snapshot_id,
        pre_execution.snapshot_id,
        post_api.snapshot_id,
        post_evidence.snapshot_id,
        source_final.snapshot_id,
    ]
    facts = {
        "snapshot_ids": snapshot_ids,
        "evidence_ids": [evidence_payload["evidence_id"]],
        "inspection_fingerprints": {
            "before_content": post_api.content_fingerprint,
            "after_content": post_evidence.content_fingerprint,
            "before_metadata": post_api.metadata_fingerprint,
            "after_metadata": post_evidence.metadata_fingerprint,
        },
        "execution_attempted": details["calculation_attempted"] is True,
        "selected_result_format": selected_format,
        "cleanup_output_format": request["engine"]["expected_result_format"],
        "authoritative_evidence_channels": (
            [] if inspection_failure is not None else _authoritative_channels(evidence)
        ),
        "deleted_relative_paths": [
            deleted_paths[key] for key in sorted(deleted_paths)
        ],
        "allowed_deleted_relative_paths": list(stage_known_paths),
        "finalization_attempted": (
            details["result_artifacts_finalized"] is True
            or details.get("artifact_finalization_failure") is not None
        ),
        "quiescence_confirmed": details["solver_quiescence_confirmed"] is True,
        "evidence_contract": evidence_contract,
        "source_fingerprints": {
            "fingerprint_algorithm": source_before.fingerprint_algorithm,
            "before_content": source_before.content_fingerprint,
            "after_content": source_final.content_fingerprint,
            "before_metadata": source_before.metadata_fingerprint,
            "after_metadata": source_final.metadata_fingerprint,
        },
        "expected_source_fingerprint_algorithm": request["fixture"][
            "source_content_fingerprint_algorithm"
        ],
        "expected_source_content_fingerprint": expected_source,
        "stage_fingerprint_algorithm": stage_result.fingerprint_algorithm,
        "stage_source_fingerprint_before": stage_result.source_fingerprint_before,
        "stage_source_fingerprint_after": stage_result.source_fingerprint_after,
        "stage_copied_fingerprint": stage_result.copied_fingerprint,
        "remaining_owned_processes": [*post_plan["matched"], *post_global["processes"]],
        "process_state": "inactive",
        "conflicting_artifacts_visible": not final_family_valid,
        "lane_failed": not final_family_valid,
    }
    invariant_results = evaluate_invariants(
        facts, required=request["required_invariants"]
    )
    invariant_rows = [
        result.to_row(
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
        )
        for result in invariant_results
    ]
    all_invariants_passed = (
        {row["invariant_id"] for row in invariant_rows}
        == set(request["required_invariants"])
        and all(row["status"] == "pass" for row in invariant_rows)
        and final_family_valid
    )
    mechanical = (
        None
        if inspection_failure is not None
        else (
            evidence.mechanical_completion.value
            if evidence.mechanical_completion.state == "available"
            else None
        )
    )
    execution_passed = process_success and mechanical is True
    if not execution_passed:
        terminal_category = "execution_failed"
        worker_exit_code = 20
        failure_reason = "mechanical_execution_not_confirmed"
    elif not all_invariants_passed:
        terminal_category = "failed_invariant"
        worker_exit_code = 20
        failure_reason = "qualification_invariant_failed"
    else:
        terminal_category = "passed"
        worker_exit_code = 0
        failure_reason = None
    finished_at = datetime.now(timezone.utc)
    lane = lane_row(
        request,
        started_at=started_at,
        finished_at=finished_at,
        worker_exit_code=worker_exit_code,
        terminal_category=terminal_category,
        stage_project_file=str(stage_result.destination_project_file),
        selected_format=selected_format,
        final_hdf_exists=final_hdf,
        final_legacy_exists=final_legacy,
        source_immutable=source_immutable,
        all_invariants_passed=all_invariants_passed,
        mechanical_completion=mechanical,
        error_count=(
            None
            if inspection_failure is not None
            else available_value(evidence, "message_error_count")
        ),
        warning_count=(
            None
            if inspection_failure is not None
            else available_value(evidence, "message_warning_count")
        ),
        conflicts=(
            evidence_payload["conflicts"]
            if inspection_failure is not None
            else evidence.conflicts
        ),
        failure_reason_code=failure_reason,
        detail="live disposable-stage execution through ras-commander APIs",
    )
    lane["compute_mode"] = details.get("compute_mode")
    lane["process_success"] = process_success
    lane["completion_verified"] = (
        completion_verified
        if request["engine"]["execution_api"] == "ras_cmdr"
        else mechanical
    )

    events.append(
        phase="invariants",
        event_name="invariants_evaluated",
        status="passed" if all_invariants_passed else "failed",
        api="evaluate_invariants",
        payload={
            "required": request["required_invariants"],
            "statuses": {
                row["invariant_id"]: row["status"] for row in invariant_rows
            },
        },
    )
    events.append(
        phase="receipt",
        event_name="worker_receipt_prepared",
        status=terminal_category,
        api="live_worker",
    )
    referenced_artifacts = [
        _artifact_reference(attempt_dir, events_path),
        _artifact_reference(attempt_dir, evidence_path),
        _artifact_reference(attempt_dir, execution_path),
    ]
    if message_reference is not None:
        referenced_artifacts.append(message_reference)
    tables = {
        "lanes": [lane],
        "artifacts": [
            *source_before.rows,
            *stage_published.rows,
            *pre_execution.rows,
            *post_api.rows,
            *post_evidence.rows,
            *source_final.rows,
        ],
        "observations": evidence_rows,
        "events": read_event_journal(events_path),
        "invariants": invariant_rows,
    }
    for table_name, rows in tables.items():
        table_from_rows(table_name, rows)

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
        "terminal_category": terminal_category,
        "worker_exit_code": worker_exit_code,
        "worker_pid": os.getpid(),
        "worker_instance_id": str(uuid.uuid4()),
        "worker_invocation_index": _WORKER_INVOCATIONS,
        "python_executable": sys.executable,
        "python_executable_sha256": request["python_executable_sha256"],
        "python_version": platform.python_version(),
        "pyarrow_version": pyarrow.__version__,
        "psutil_version": request["psutil_version"],
        "ras_commander_version": request["ras_commander_version"],
        "ras_commander_import_path": request["ras_commander_import_path"],
        "package_root": request["repository_root"],
        "root_logger_handler_count": len(logging.getLogger().handlers),
        "supervisor_synthesized": False,
        "hec_ras_invoked": hec_ras_invoked,
        "real_engine_lock": lock_payload,
        "tcu_status": tcu_status,
        "process_evidence": {
            "pre_stage_global": pre_stage_global,
            "pre_setup_plan": pre_plan,
            "pre_execute_global": pre_execute_global,
            "post_execution_plan": post_plan,
            "post_execution_global": post_global,
        },
        "stage_result": {
            "publication_state": stage_result.publication_state,
            "execution_readiness": stage_result.execution_readiness,
            "fingerprint_algorithm": stage_result.fingerprint_algorithm,
            "source_fingerprint_before": stage_result.source_fingerprint_before,
            "source_fingerprint_after": stage_result.source_fingerprint_after,
            "copied_fingerprint": stage_result.copied_fingerprint,
            "published_fingerprint": stage_result.published_fingerprint,
            "copied_file_count": stage_result.copied_file_count,
            "copied_bytes": stage_result.copied_bytes,
        },
        "initial_state_cleanup": cleanup_records,
        "replay_artifacts": list(replay_records),
        "execution_result": execution_record,
        "evidence": evidence_payload,
        "referenced_artifacts": referenced_artifacts,
        "tables": tables,
    }
    write_json_with_digest(
        attempt_dir / "worker_receipt.json", json_safe(receipt)
    )
    return worker_exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="execution-evidence-live-worker")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--launch-nonce")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        request_path = args.request.resolve(strict=True)
        _register_and_verify_worker_authorization(
            request_path,
            args.launch_nonce,
        )
        request, request_sha256, context = _verify_request(
            request_path
        )
    except Exception:
        traceback.print_exc()
        return 31
    try:
        return _perform(request, request_sha256, context)
    except Exception:
        traceback.print_exc()
        return 30


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LiveCapabilityError",
    "LiveProcessGateError",
    "LiveTcuGateError",
    "LiveWorkerError",
    "main",
]
