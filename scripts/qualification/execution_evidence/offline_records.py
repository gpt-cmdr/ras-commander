"""Receipt-row adapters for stage and read-only evidence workers."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("receipt datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def known_result_paths(project_file: str | Path, plan_number: str) -> tuple[str, ...]:
    stem = Path(project_file).stem
    return (
        f"{stem}.p{plan_number}.hdf",
        f"{stem}.O{plan_number}",
        f"{stem}.p{plan_number}.comp_msgs.txt",
        f"{stem}.p{plan_number}.computeMsgs.txt",
        f"{stem}.bco{plan_number}",
    )


def result_population(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, bool]:
    hdf = False
    legacy = False
    for row in rows:
        if not row.get("exists"):
            continue
        if row.get("result_family") == "hdf":
            hdf = True
        elif row.get("result_family") == "legacy":
            legacy = True
    return hdf, legacy


def selected_result_format(evidence: Any) -> str | None:
    observation = evidence.observations["result_artifact_exists"]
    locator = observation.source_locator
    if not locator:
        return None
    name = Path(locator).name
    if name.casefold().endswith(".hdf"):
        return "hdf"
    if re.search(r"\.o\d{2}$", name, re.IGNORECASE):
        return "legacy"
    return None


def _typed_value(value: Any) -> tuple[str, dict[str, Any]]:
    columns = {
        "value_bool": None,
        "value_int64": None,
        "value_float64": None,
        "value_string": None,
        "value_timestamp": None,
    }
    if value is None:
        return "null", columns
    if isinstance(value, bool):
        columns["value_bool"] = value
        return "bool", columns
    if isinstance(value, int):
        columns["value_int64"] = value
        return "int64", columns
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("evidence float values must be finite")
        columns["value_float64"] = value
        return "float64", columns
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            # HEC-RAS simulation windows are modeled wall-clock values.  RAS
            # does not attach a timezone, so preserve the exact ISO local
            # datetime rather than inventing UTC chronology.
            columns["value_string"] = value.isoformat()
            return "local_datetime", columns
        columns["value_timestamp"] = value
        return "timestamp", columns
    if isinstance(value, str):
        columns["value_string"] = value
        return "string", columns
    raise TypeError(f"unsupported execution-evidence scalar: {type(value).__name__}")


def flatten_evidence(
    evidence: Any,
    *,
    run_id: str,
    lane_id: str,
    attempt_id: str,
) -> list[dict[str, Any]]:
    """Flatten the immutable public evidence registry into its exact Arrow rows."""
    observations = [("mechanical_completion", evidence.mechanical_completion)]
    observations.extend(evidence.observations.items())
    rows: list[dict[str, Any]] = []
    for name, observation in observations:
        value_type, value_columns = _typed_value(observation.value)
        rows.append(
            {
                "schema_version": 1,
                "run_id": run_id,
                "lane_id": lane_id,
                "attempt_id": attempt_id,
                "evidence_id": evidence.evidence_id,
                "observation_name": name,
                "evidence_inspected_at": evidence.inspected_at,
                "observation_inspected_at": observation.inspected_at,
                "declared_program_version": evidence.declared_program_version,
                "state": observation.state,
                "channel": observation.channel,
                "value_type": value_type,
                **value_columns,
                "source_locator": observation.source_locator,
                "source_sha256": observation.source_sha256,
                "observed_program_version": observation.observed_program_version,
                "reason_code": observation.reason_code,
                "detail": observation.detail,
                "conflicts": list(evidence.conflicts),
            }
        )
    return rows


def lane_row(
    request: Mapping[str, Any],
    *,
    started_at: datetime,
    finished_at: datetime,
    worker_exit_code: int,
    terminal_category: str,
    stage_project_file: str,
    selected_format: str | None,
    final_hdf_exists: bool,
    final_legacy_exists: bool,
    source_immutable: bool,
    all_invariants_passed: bool,
    mechanical_completion: bool | None = None,
    error_count: int | None = None,
    warning_count: int | None = None,
    conflicts: Iterable[str] = (),
    failure_reason_code: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    lane = request["lane"]
    fixture = request["fixture"]
    engine = request["engine"]
    return {
        "schema_version": 1,
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "manifest_sha256": request["manifest_sha256"],
        "git_head": request["git_head"],
        "fixture_id": fixture["fixture_id"],
        "plan_type": fixture["plan_type"],
        "plan_number": fixture["plan_number"],
        "source_kind": fixture["source_kind"],
        "source_project": request["source_project"],
        "source_content_fingerprint_algorithm": request[
            "source_snapshot_content_fingerprint_algorithm"
        ],
        "source_content_fingerprint": request["source_snapshot_content_fingerprint"],
        "stage_project": stage_project_file,
        "execution_api": engine["execution_api"],
        "engine_id": engine["engine_id"],
        "engine_version_requested": engine["version_requested"],
        "engine_executable": engine.get("executable"),
        "engine_executable_sha256": engine.get("executable_sha256"),
        "controller_version": engine.get("controller_version"),
        "controller_progid": engine.get("controller_progid"),
        "compute_mode": f"offline_{request['action']}",
        "expected_result_format": engine.get("expected_result_format"),
        "selected_result_format": selected_format,
        "initial_state": lane["initial_state"],
        "expected_terminal_category": lane["expected_terminal_category"],
        "terminal_category": terminal_category,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_seconds": max((finished_at - started_at).total_seconds(), 0.0),
        "worker_exit_code": worker_exit_code,
        "process_success": None,
        "completion_verified": mechanical_completion,
        "mechanical_completion": mechanical_completion,
        "error_count": error_count,
        "warning_count": warning_count,
        "conflicts": list(conflicts),
        "final_hdf_exists": final_hdf_exists,
        "final_legacy_exists": final_legacy_exists,
        "source_immutable": source_immutable,
        "all_invariants_passed": all_invariants_passed,
        "failure_reason_code": failure_reason_code,
        "detail": None if detail is None else detail[:1000],
    }


def available_value(evidence: Any, name: str) -> Any:
    observation = evidence.observations[name]
    return observation.value if observation.state == "available" else None


__all__ = [
    "available_value",
    "flatten_evidence",
    "known_result_paths",
    "json_safe",
    "lane_row",
    "result_population",
    "selected_result_format",
]
