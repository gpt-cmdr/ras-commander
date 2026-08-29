"""Exact staged-plan cancellation helper for timed-out live workers.

This module is intentionally a separate Python process.  It accepts only a
digest-bound request created by :mod:`live_supervisor` and calls additive,
structured ras-commander APIs.  The legacy boolean ``cancel_plan`` API is not
sufficient evidence and is never used here.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manifest import _preflight_repository
from .offline_records import json_safe
from .planning import current_runtime_pins, file_sha256
from .receipts import read_json_with_digest, write_json_with_digest


class LiveCancellationError(RuntimeError):
    """Exact cancellation could not be proved safe."""


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return json_safe(dict(value))
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        raise LiveCancellationError(
            "structured cancellation evidence must expose explicit to_dict(): "
            f"{type(value).__name__}"
        )
    payload = to_dict()
    if not isinstance(payload, Mapping):
        raise LiveCancellationError("structured cancellation to_dict() did not return a mapping")
    return json_safe(dict(payload))


def _verify_repository(repository_root: Path, git_head: str) -> None:
    _preflight_repository(
        repository_root,
        required_head=git_head,
        require_clean=True,
    )


def _verify_runtime(request: Mapping[str, Any]) -> None:
    executable = Path(str(request.get("python_executable", ""))).resolve(strict=True)
    if not os.path.samefile(executable, Path(sys.executable).resolve(strict=True)):
        raise LiveCancellationError("cancellation request pins a different Python interpreter")
    if file_sha256(executable) != request.get("python_executable_sha256"):
        raise LiveCancellationError("cancellation Python interpreter hash mismatch")
    for field, observed in current_runtime_pins().items():
        if request.get(field) != observed:
            raise LiveCancellationError(f"cancellation runtime pin mismatch for {field}")


def _load_and_verify_request(path: str | Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    request_path = Path(path).resolve(strict=True)
    request, request_sha256 = read_json_with_digest(request_path)
    if request.get("schema_version") != 1 or request.get("action") != "cancel":
        raise LiveCancellationError("cancellation request requires schema_version=1 and action=cancel")
    if request.get("hec_ras_execution_enabled") is not True:
        raise LiveCancellationError("cancellation request lacks explicit live-execution acknowledgement")
    if Path(str(request.get("cancel_receipt_path", ""))).resolve(strict=False) != (
        request_path.parent / "cancel-receipt.json"
    ):
        raise LiveCancellationError("cancellation receipt path escaped its attempt directory")
    live_request_path = Path(str(request.get("live_request_path", ""))).resolve(strict=True)
    if live_request_path != request_path.parent / "request.json":
        raise LiveCancellationError("cancellation request does not bind the attempt request")
    live_request, live_request_sha256 = read_json_with_digest(live_request_path)
    if live_request_sha256 != request.get("live_request_sha256"):
        raise LiveCancellationError("cancellation request pins the wrong live request digest")
    for field in ("run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head"):
        if request.get(field) != live_request.get(field):
            raise LiveCancellationError(f"cancellation/live request mismatch for {field}")
    if live_request.get("action") != "run" or live_request.get(
        "hec_ras_execution_enabled"
    ) is not True:
        raise LiveCancellationError("bound attempt is not an acknowledged live run")
    normalized_path = Path(
        str(live_request.get("normalized_manifest_path", ""))
    ).resolve(strict=True)
    normalized, normalized_sha256 = read_json_with_digest(normalized_path)
    if normalized_sha256 != live_request.get("normalized_manifest_sha256"):
        raise LiveCancellationError("live request pins the wrong normalized manifest digest")
    if normalized.get("manifest_sha256") != live_request.get("manifest_sha256"):
        raise LiveCancellationError("normalized manifest identity disagrees with live request")
    descriptor, descriptor_sha256 = read_json_with_digest(
        normalized_path.parent / "run.json"
    )
    if descriptor_sha256 != live_request.get("run_descriptor_sha256"):
        raise LiveCancellationError("live request pins the wrong run descriptor digest")
    if descriptor.get("hec_ras_execution_enabled") is not False:
        raise LiveCancellationError("planned run descriptor must remain execution-inert")
    for field in ("run_id", "git_head", "repository_root", "python_executable"):
        if descriptor.get(field) != live_request.get(field):
            raise LiveCancellationError(f"run/live request mismatch for {field}")
    for field in (
        "repository_root",
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "pyarrow_version",
        "psutil_version",
        "ras_commander_version",
        "ras_commander_import_path",
        "stage_root",
    ):
        if request.get(field) != live_request.get(field):
            raise LiveCancellationError(f"cancellation/live request mismatch for {field}")
    fixture = live_request.get("fixture")
    engine = live_request.get("engine")
    if not isinstance(fixture, Mapping) or not isinstance(engine, Mapping):
        raise LiveCancellationError("bound live request lacks fixture or engine identity")
    if engine.get("execution_api") != "ras_cmdr":
        raise LiveCancellationError("exact cancellation helper is only valid for RasCmdr lanes")
    if request.get("plan_number") != fixture.get("plan_number"):
        raise LiveCancellationError("cancellation plan number disagrees with the live fixture")
    source_project = Path(str(live_request.get("source_project", "")))
    stage_root = Path(str(request.get("stage_root", ""))).resolve(strict=True)
    stage_project = Path(str(request.get("stage_project", ""))).resolve(strict=True)
    if stage_project != stage_root / source_project.name:
        raise LiveCancellationError("cancellation project is not the exact staged project")
    expected_stage_root = (
        Path(str(descriptor.get("execution_run_root", ""))).resolve(strict=True)
        / str(request["lane_id"])
        / str(request["attempt_id"])
        / "stage"
    )
    if stage_root != expected_stage_root:
        raise LiveCancellationError("cancellation stage escaped the pinned execution run root")
    repository_root = Path(str(request.get("repository_root", ""))).resolve(strict=True)
    _verify_repository(repository_root, str(request.get("git_head", "")))
    _verify_runtime(request)
    executable = Path(str(engine.get("executable", ""))).resolve(strict=True)
    if file_sha256(executable) != engine.get("executable_sha256"):
        raise LiveCancellationError("cancellation engine executable hash mismatch")
    return request, request_sha256, live_request


def _initialize_staged_project(stage_project: Path, engine: Mapping[str, Any]) -> Any:
    from ras_commander import RasPrj

    ras_object = RasPrj()
    ras_object.initialize(
        stage_project.parent,
        engine["executable"],
        prj_file=stage_project,
        suppress_logging=True,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    return ras_object


def _cancel_exact_plan(
    plan_number: str,
    *,
    ras_object: Any,
    timeout_seconds: float,
) -> tuple[Any, Any]:
    from ras_commander import RasCmdr

    cancel = getattr(RasCmdr, "cancel_plan_exact", None)
    inspect = getattr(RasCmdr, "inspect_plan_processes", None)
    if not callable(cancel) or not callable(inspect):
        raise LiveCancellationError(
            "structured RasCmdr cancellation APIs are unavailable; refusing legacy boolean cancellation"
        )
    cancellation = cancel(
        plan_number,
        ras_object=ras_object,
        timeout_seconds=timeout_seconds,
    )
    post_inventory = inspect(plan_number, ras_object=ras_object)
    return cancellation, post_inventory


def _complete_empty_global_inventory() -> Any:
    """Capture the final global process proof immediately before publication."""
    from ras_commander import RasControl

    inspect = getattr(RasControl, "inspect_processes", None)
    if not callable(inspect):
        raise LiveCancellationError(
            "structured RasControl.inspect_processes is unavailable"
        )
    inventory = inspect()
    if _field(inventory, "complete") is not True:
        raise LiveCancellationError("final global process inventory is incomplete")
    errors = _field(inventory, "query_errors")
    if not isinstance(errors, (list, tuple)) or errors:
        raise LiveCancellationError(
            "final global process inventory contains query errors"
        )
    processes = _field(inventory, "processes")
    if not isinstance(processes, (list, tuple)):
        raise LiveCancellationError(
            "final global process inventory has no process sequence"
        )
    if processes:
        raise LiveCancellationError(
            "final global process inventory is not empty"
        )
    return inventory


def execute_cancellation(path: str | Path) -> dict[str, Any]:
    request, request_sha256, live_request = _load_and_verify_request(path)
    stage_project = Path(request["stage_project"]).resolve(strict=True)
    ras_object = _initialize_staged_project(stage_project, live_request["engine"])
    cancellation, post_inventory = _cancel_exact_plan(
        str(request["plan_number"]),
        ras_object=ras_object,
        timeout_seconds=float(request["timeout_seconds"]),
    )
    if _field(cancellation, "quiescence_confirmed") is not True:
        raise LiveCancellationError("exact cancellation did not confirm plan quiescence")
    if (
        _field(cancellation, "pre_scan_complete") is not True
        or _field(cancellation, "post_scan_complete") is not True
    ):
        raise LiveCancellationError("exact cancellation process scans are incomplete")
    survivors = _field(cancellation, "survivors")
    cancel_errors = _field(cancellation, "query_errors")
    if not isinstance(survivors, (list, tuple)) or survivors:
        raise LiveCancellationError("exact cancellation retained plan-process survivors")
    if not isinstance(cancel_errors, (list, tuple)) or cancel_errors:
        raise LiveCancellationError("exact cancellation contains process-query errors")
    if _field(post_inventory, "complete") is not True:
        raise LiveCancellationError("post-cancellation plan inventory is incomplete")
    post_errors = _field(post_inventory, "query_errors")
    if not isinstance(post_errors, (list, tuple)) or post_errors:
        raise LiveCancellationError("post-cancellation plan inventory contains query errors")
    remaining = _field(post_inventory, "matched")
    if not isinstance(remaining, (list, tuple)) or remaining:
        raise LiveCancellationError("post-cancellation plan inventory is not empty")
    # This scan is deliberately last.  A plan-scoped empty scan is not proof
    # against an unaccounted solver, PID reuse, or a different RAS process.
    post_global_inventory = _complete_empty_global_inventory()
    receipt = {
        "schema_version": 1,
        "action": "cancel",
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "manifest_sha256": request["manifest_sha256"],
        "git_head": request["git_head"],
        "request_sha256": request_sha256,
        "live_request_sha256": request["live_request_sha256"],
        "committed_at": datetime.now(timezone.utc).isoformat(),
        "safe_to_terminate_child": True,
        "quiescence_confirmed": True,
        "cancellation": _record(cancellation),
        "post_plan_inventory": _record(post_inventory),
        "post_global_inventory": _record(post_global_inventory),
        "hec_ras_invoked": False,
        "hec_ras_interaction": "exact_cancellation_inspection",
    }
    write_json_with_digest(request["cancel_receipt_path"], receipt)
    return receipt


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="execution-evidence-live-cancel-worker")
    parser.add_argument("--request", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        execute_cancellation(args.request)
    except Exception as exc:
        print(f"live cancellation failed: {exc}", file=sys.stderr)
        return 30
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["LiveCancellationError", "execute_cancellation", "main"]
