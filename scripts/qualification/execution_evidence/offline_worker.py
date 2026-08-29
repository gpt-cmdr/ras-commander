"""One-shot worker for public staging and read-only execution-evidence APIs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import psutil
import pyarrow

from .manifest import canonical_sha256
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
from .snapshots import snapshot_tree
from .replay import overlay_replay_artifacts, replay_origin_overrides


_WORKER_INVOCATIONS = 0


class OfflineWorkerError(RuntimeError):
    """A signed offline request failed a pin or read-only API contract."""


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _git_read(repository_root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository_root}",
            "-C",
            str(repository_root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=environment,
    )
    if result.returncode:
        raise OfflineWorkerError(
            result.stderr.strip() or "repository pin inspection failed"
        )
    return result.stdout.strip()


def _verify_request(request_path: Path) -> tuple[dict[str, Any], str, Any]:
    request, request_sha256 = read_json_with_digest(request_path)
    if request.get("schema_version") != 1:
        raise OfflineWorkerError("request requires schema_version=1")
    if request.get("action") not in {"stage", "inspect"}:
        raise OfflineWorkerError("request action is not an offline worker action")
    if request.get("hec_ras_execution_enabled") is not False:
        raise OfflineWorkerError("offline request unexpectedly enables HEC-RAS execution")
    attempt_dir = request_path.parent.resolve(strict=True)
    if request.get("lane_id") != attempt_dir.parent.name:
        raise OfflineWorkerError("request lane_id disagrees with attempt path")
    if request.get("attempt_id") != attempt_dir.name:
        raise OfflineWorkerError("request attempt_id disagrees with attempt path")
    run_root = attempt_dir.parents[2]
    context = load_run(run_root)
    if request.get("run_descriptor_sha256") != context.descriptor_sha256:
        raise OfflineWorkerError("request run descriptor pin mismatch")

    executable = Path(str(request.get("python_executable", ""))).resolve(strict=True)
    if not _same_file(executable, Path(sys.executable).resolve(strict=True)):
        raise OfflineWorkerError("worker interpreter path does not match request pin")
    if file_sha256(executable) != request.get("python_executable_sha256"):
        raise OfflineWorkerError("worker interpreter hash does not match request pin")
    repository_root = Path(str(request.get("repository_root", ""))).resolve(strict=True)
    if not _same_file(repository_root, Path(context.descriptor["repository_root"])):
        raise OfflineWorkerError("worker repository root does not match run pin")
    actual_head = _git_read(repository_root, "rev-parse", "--verify", "HEAD").casefold()
    if actual_head != request.get("git_head"):
        raise OfflineWorkerError("worker repository HEAD does not match request pin")
    if context.manifest["repository"]["require_clean"]:
        dirty = _git_read(
            repository_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if dirty:
            raise OfflineWorkerError("worker repository is dirty but require_clean=true")

    import ras_commander

    package_root = Path(ras_commander.__file__).resolve(strict=True).parent.parent
    if not _same_file(package_root, repository_root):
        raise OfflineWorkerError("ras_commander was imported from outside the pinned repository")
    runtime_pins = current_runtime_pins()
    for field, observed in runtime_pins.items():
        if request.get(field) != observed:
            raise OfflineWorkerError(f"worker runtime pin mismatch for {field}")
    manifest_path = Path(request["normalized_manifest_path"]).resolve(strict=True)
    manifest, manifest_file_sha256 = read_json_with_digest(manifest_path)
    if manifest_file_sha256 != request.get("normalized_manifest_sha256"):
        raise OfflineWorkerError("normalized manifest file digest mismatch")
    claimed_manifest_hash = manifest.pop("manifest_sha256", None)
    if canonical_sha256(manifest) != claimed_manifest_hash:
        raise OfflineWorkerError("normalized manifest canonical hash mismatch")
    manifest["manifest_sha256"] = claimed_manifest_hash
    if claimed_manifest_hash != request.get("manifest_sha256"):
        raise OfflineWorkerError("request manifest identity mismatch")
    lane, fixture, engine = select_lane(context, request["lane_id"])
    if lane != request.get("lane") or fixture != request.get("fixture") or engine != request.get("engine"):
        raise OfflineWorkerError("request lane expansion disagrees with normalized manifest")
    expected_invariants = (
        ["R11"]
        if request["action"] == "stage"
        else list(lane["required_invariants"])
    )
    if request.get("required_invariants") != expected_invariants:
        raise OfflineWorkerError("request required invariants disagree with action and lane")
    unsupported = set(expected_invariants) - {"R01", "R03", "R11"}
    if unsupported:
        raise OfflineWorkerError(
            f"offline action cannot evaluate required invariants: {sorted(unsupported)}"
        )
    source_project = Path(request["source_project"]).resolve(strict=True)
    if not _same_file(source_project, Path(fixture["source_project"])):
        raise OfflineWorkerError("request source project disagrees with manifest fixture")
    expected_stage_root = (
        Path(context.descriptor["execution_run_root"])
        / request["lane_id"]
        / request["attempt_id"]
        / "stage"
    ).resolve(strict=False)
    if Path(request["stage_root"]).resolve(strict=False) != expected_stage_root:
        raise OfflineWorkerError("request stage root escaped its unique attempt path")
    if expected_stage_root.exists():
        raise OfflineWorkerError("request stage root already exists")
    return request, request_sha256, context


def _invariant_row(
    request: Mapping[str, Any],
    *,
    invariant_id: str,
    name: str,
    passed: bool,
    applicable: bool = True,
    expected: Any,
    observed: Any,
    reason_code: str,
    snapshot_ids: Sequence[str],
    evidence_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "invariant_id": invariant_id,
        "name": name,
        "evaluated_at": datetime.now(timezone.utc),
        "status": "not_applicable" if not applicable else ("pass" if passed else "fail"),
        "expected": json.dumps(expected, sort_keys=True, separators=(",", ":")),
        "observed": json.dumps(observed, sort_keys=True, separators=(",", ":")),
        "reason_code": reason_code,
        "detail": None,
        "supporting_snapshot_ids": list(snapshot_ids),
        "supporting_evidence_ids": list(evidence_ids),
    }


def _artifact_reference(attempt_dir: Path, path: Path) -> dict[str, str]:
    return {
        "relative_path": path.relative_to(attempt_dir).as_posix(),
        "sha256": file_sha256(path),
    }


def _perform(request: dict[str, Any], request_sha256: str, context: Any) -> int:
    global _WORKER_INVOCATIONS
    _WORKER_INVOCATIONS += 1
    started_at = datetime.now(timezone.utc)
    attempt_dir = context.run_root / "attempts" / request["lane_id"] / request["attempt_id"]
    events = EventJournal(
        attempt_dir / "events.jsonl",
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
    )
    events.append(
        phase="request",
        event_name="request_verified",
        status="passed",
        api="offline_worker",
        pid=os.getpid(),
    )
    source_project = Path(request["source_project"])
    known_paths = known_result_paths(source_project, request["fixture"]["plan_number"])
    source_before = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_before_stage",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=known_paths,
    )
    if (
        source_before.content_fingerprint
        != request["source_snapshot_content_fingerprint"]
        or source_before.metadata_fingerprint
        != request["source_snapshot_metadata_fingerprint"]
    ):
        raise OfflineWorkerError("source changed after request publication")
    events.append(
        phase="source",
        event_name="source_verified",
        status="passed",
        api="snapshot_tree",
    )

    from ras_commander import (
        RasCmdr,
        RasPrj,
        ResultArtifactAmbiguityError,
        init_ras_project,
        stage_project,
    )

    stage_root = Path(request["stage_root"])
    stage_result = stage_project(source_project, stage_root)
    stage_project_relative = stage_result.destination_project_file.relative_to(
        stage_result.destination_root
    ).as_posix()
    expected_stage_fingerprint = request["fixture"].get("source_content_fingerprint")
    stage_source_valid = (
        stage_result.source_fingerprint_before
        == stage_result.source_fingerprint_after
        and (
            expected_stage_fingerprint is None
            or stage_result.source_fingerprint_before == expected_stage_fingerprint
        )
    )
    if not stage_source_valid:
        raise OfflineWorkerError("public stage_project source fingerprint gate failed")
    events.append(
        phase="stage",
        event_name="stage_published",
        status="passed",
        api="stage_project",
        relative_path=stage_project_relative,
    )
    replay = request["fixture"].get("replay_artifacts")
    replay_records = overlay_replay_artifacts(stage_result.destination_root, replay)
    if replay_records:
        events.append(
            phase="stage",
            event_name="replay_artifacts_published",
            status="passed",
            api="overlay_replay_artifacts",
            payload={
                "data_origin": replay["data_origin"],
                "files": [item["relative_path"] for item in replay_records],
            },
        )
    stage_origin_overrides = replay_origin_overrides(replay)
    stage_origin_overrides[".ras-commander/stage.json"] = (
        "generated_harness_receipt"
    )
    stage_before = snapshot_tree(
        stage_result.destination_root,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="stage_published",
        root_kind="stage",
        data_origin=request["fixture"]["data_origin"],
        known_paths=known_paths,
        origin_overrides=stage_origin_overrides,
    )
    evidence = None
    expected_failure = None
    evidence_rows: list[dict[str, Any]] = []
    referenced_artifacts: list[dict[str, str]] = []
    stage_after = stage_before
    if request["action"] == "inspect":
        explicit_ras = init_ras_project(
            stage_result.destination_project_file,
            ras_version=request["engine"].get("executable")
            or request["engine"]["version_requested"],
            ras_object=RasPrj(),
            load_results_summary=False,
            load_hdf_metadata=False,
            hide_intro=True,
        )
        try:
            evidence = RasCmdr.inspect_execution_evidence(
                request["fixture"]["plan_number"],
                ras_object=explicit_ras,
                hash_files=request["hash_files"],
            )
        except ResultArtifactAmbiguityError as exc:
            expected_reason = request["lane"].get(
                "expected_failure_reason_code"
            )
            if (
                request["lane"]["expected_terminal_category"]
                != "expected_failure"
                or exc.reason_code != expected_reason
            ):
                raise
            caught_at = datetime.now(timezone.utc).isoformat()
            expected_failure = {
                "exception_type": type(exc).__name__,
                "reason_code": exc.reason_code,
                "caught_at": caught_at,
                "declared_program_version": exc.declared_program_version,
                "expected_format": exc.expected_format,
                "plan_number": exc.plan_number,
                "plan_file": str(exc.plan_file),
                "hdf_path": str(exc.hdf_path),
                "legacy_output_path": str(exc.legacy_output_path),
                "hdf_mtime_ns": exc.hdf_mtime_ns,
                "legacy_mtime_ns": exc.legacy_mtime_ns,
                "detail": exc.detail,
            }
            events.append(
                phase="inspection",
                event_name="expected_result_artifact_ambiguity",
                status="expected_failure",
                severity="warning",
                api="RasCmdr.inspect_execution_evidence",
                reason_code=exc.reason_code,
                detail=str(exc),
                relative_path=stage_project_relative,
                payload=expected_failure,
            )
        if evidence is not None:
            if (
                request["lane"]["expected_terminal_category"]
                == "expected_failure"
            ):
                raise OfflineWorkerError(
                    "inspection returned evidence but the lane required an exact expected failure"
                )
            evidence_rows = flatten_evidence(
                evidence,
                run_id=request["run_id"],
                lane_id=request["lane_id"],
                attempt_id=request["attempt_id"],
            )
            evidence_path = attempt_dir / "evidence.json"
            write_json_with_digest(evidence_path, evidence.to_dict())
            referenced_artifacts.append(
                _artifact_reference(attempt_dir, evidence_path)
            )
            events.append(
                phase="inspection",
                event_name="execution_evidence_inspected",
                status="passed",
                api="RasCmdr.inspect_execution_evidence",
                relative_path=stage_project_relative,
            )
        stage_after = snapshot_tree(
            stage_result.destination_root,
            run_id=request["run_id"],
            lane_id=request["lane_id"],
            attempt_id=request["attempt_id"],
            phase="post_evidence_inspection",
            root_kind="stage",
            data_origin=request["fixture"]["data_origin"],
            known_paths=known_paths,
            origin_overrides=stage_origin_overrides,
        )
    source_final = snapshot_tree(
        source_project.parent,
        run_id=request["run_id"],
        lane_id=request["lane_id"],
        attempt_id=request["attempt_id"],
        phase="source_final",
        root_kind="source",
        data_origin=request["fixture"]["data_origin"],
        known_paths=known_paths,
    )
    source_immutable = (
        source_before.content_fingerprint == source_final.content_fingerprint
        and source_before.metadata_fingerprint == source_final.metadata_fingerprint
    )
    inspect_read_only = (
        stage_before.content_fingerprint == stage_after.content_fingerprint
        and stage_before.metadata_fingerprint == stage_after.metadata_fingerprint
    )
    snapshot_ids = [
        source_before.snapshot_id,
        stage_before.snapshot_id,
        stage_after.snapshot_id,
        source_final.snapshot_id,
    ]
    mechanical = None
    error_count = None
    warning_count = None
    conflicts: Sequence[str] = ()
    selected_format = None
    if evidence is not None:
        mechanical = (
            evidence.mechanical_completion.value
            if evidence.mechanical_completion.state == "available"
            else None
        )
        error_count = available_value(evidence, "message_error_count")
        warning_count = available_value(evidence, "message_warning_count")
        conflicts = evidence.conflicts
        selected_format = selected_result_format(evidence)
    invariants = [
        _invariant_row(
            request,
            invariant_id="R11",
            name="Source immutability",
            passed=source_immutable and stage_source_valid,
            expected={
                "source_snapshot": "unchanged",
                "stage_project_source_fingerprint": expected_stage_fingerprint,
            },
            observed={
                "source_before": source_before.content_fingerprint,
                "source_after": source_final.content_fingerprint,
                "stage_source_before": stage_result.source_fingerprint_before,
                "stage_source_after": stage_result.source_fingerprint_after,
            },
            reason_code=("source_immutable" if source_immutable and stage_source_valid else "source_drift"),
            snapshot_ids=snapshot_ids,
        )
    ]
    if request["action"] == "inspect":
        authoritative_channels = {
            name: observation.channel
            for name, observation in (
                evidence.observations.items() if evidence is not None else ()
            )
            if observation.state == "available"
        }
        invariants.insert(
            0,
            _invariant_row(
                request,
                invariant_id="R01",
                name="Read-only inspection",
                passed=inspect_read_only,
                expected="stage content and metadata unchanged",
                observed={
                    "before_content": stage_before.content_fingerprint,
                    "after_content": stage_after.content_fingerprint,
                    "before_metadata": stage_before.metadata_fingerprint,
                    "after_metadata": stage_after.metadata_fingerprint,
                },
                reason_code=("inspection_read_only" if inspect_read_only else "inspection_changed_files"),
                snapshot_ids=[stage_before.snapshot_id, stage_after.snapshot_id],
                evidence_ids=([evidence.evidence_id] if evidence is not None else []),
            ),
        )
        if evidence is not None:
            opposing_channel = (
                "hdf" if selected_format == "legacy" else "legacy_output"
            )
            channels_separate = (
                opposing_channel not in authoritative_channels.values()
            )
            invariants.insert(
                1,
                _invariant_row(
                    request,
                    invariant_id="R03",
                    name="No evidence-channel mixing",
                    passed=channels_separate,
                    expected={"opposing_channel_absent": opposing_channel},
                    observed=authoritative_channels,
                    reason_code=(
                        "evidence_channels_separate"
                        if channels_separate
                        else "evidence_channels_mixed"
                    ),
                    snapshot_ids=[stage_after.snapshot_id],
                    evidence_ids=[evidence.evidence_id],
                ),
            )
    invariant_status = {
        row["invariant_id"]: row["status"] for row in invariants
    }
    all_invariants_passed = all(
        row["status"] == "pass" for row in invariants
    ) and all(
        invariant_status.get(invariant_id) == "pass"
        for invariant_id in request["required_invariants"]
    )
    final_hdf, final_legacy = result_population(stage_after.rows)
    finished_at = datetime.now(timezone.utc)
    if not all_invariants_passed:
        terminal_category = "failed_invariant"
        worker_exit_code = 20
    elif expected_failure is not None:
        terminal_category = "expected_failure"
        worker_exit_code = 10
    else:
        terminal_category = "passed"
        worker_exit_code = 0
    failure_reason_code = (
        expected_failure["reason_code"]
        if expected_failure is not None
        else (
            "qualification_invariant_failed"
            if not all_invariants_passed
            else None
        )
    )
    detail = (
        f"offline action={request['action']}; no HEC-RAS execution"
        if expected_failure is None
        else (
            "offline inspection matched pinned expected failure "
            f"{expected_failure['reason_code']}; no HEC-RAS execution"
        )
    )
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
        error_count=error_count,
        warning_count=warning_count,
        conflicts=conflicts,
        failure_reason_code=failure_reason_code,
        detail=detail,
    )
    events.append(
        phase="receipt",
        event_name="receipt_prepared",
        status=terminal_category,
        api="offline_worker",
    )
    events_path = attempt_dir / "events.jsonl"
    referenced_artifacts.append(_artifact_reference(attempt_dir, events_path))
    referenced_artifacts.extend(
        [
            _artifact_reference(attempt_dir, attempt_dir / "stdout.log"),
            _artifact_reference(attempt_dir, attempt_dir / "stderr.log"),
        ]
    )
    receipt = {
        **{
            field: request[field]
            for field in ("schema_version", "run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head")
        },
        "action": request["action"],
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
        "psutil_version": psutil.__version__,
        "ras_commander_version": request["ras_commander_version"],
        "ras_commander_import_path": request["ras_commander_import_path"],
        "package_root": request["repository_root"],
        "root_logger_handler_count": len(logging.getLogger().handlers),
        "supervisor_synthesized": False,
        "hec_ras_invoked": False,
        "stage_result": {
            "publication_state": stage_result.publication_state,
            "execution_readiness": stage_result.execution_readiness,
            "source_fingerprint_before": stage_result.source_fingerprint_before,
            "source_fingerprint_after": stage_result.source_fingerprint_after,
            "copied_fingerprint": stage_result.copied_fingerprint,
            "published_fingerprint": stage_result.published_fingerprint,
            "copied_file_count": stage_result.copied_file_count,
            "copied_bytes": stage_result.copied_bytes,
        },
        "replay_artifacts": list(replay_records),
        "expected_failure": expected_failure,
        "evidence": None if evidence is None else evidence.to_dict(),
        "referenced_artifacts": referenced_artifacts,
        "tables": {
            "lanes": [lane],
            "artifacts": [
                *source_before.rows,
                *stage_before.rows,
                *([] if stage_after is stage_before else stage_after.rows),
                *source_final.rows,
            ],
            "observations": evidence_rows,
            "events": read_event_journal(events_path),
            "invariants": invariants,
        },
    }
    write_json_with_digest(attempt_dir / "receipt.json", json_safe(receipt))
    return worker_exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        request, request_sha256, context = _verify_request(args.request.resolve(strict=True))
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


__all__ = ["OfflineWorkerError", "main"]
