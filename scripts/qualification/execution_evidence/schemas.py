"""Exact Arrow contracts for execution-evidence qualification records."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Mapping

try:
    import pyarrow as pa
except ImportError as exc:  # pragma: no cover - environment preflight
    raise ImportError(
        "The execution-evidence qualification harness requires pyarrow>=14"
    ) from exc


QUALIFICATION_SCHEMA_VERSION = 1
_UTC_NS = pa.timestamp("ns", tz="UTC")


def _field(name: str, data_type: pa.DataType, *, nullable: bool = True) -> pa.Field:
    return pa.field(name, data_type, nullable=nullable)


LANES_SCHEMA = pa.schema(
    [
        _field("schema_version", pa.int16(), nullable=False),
        _field("run_id", pa.string(), nullable=False),
        _field("lane_id", pa.string(), nullable=False),
        _field("attempt_id", pa.string(), nullable=False),
        _field("manifest_sha256", pa.string(), nullable=False),
        _field("git_head", pa.string(), nullable=False),
        _field("fixture_id", pa.string(), nullable=False),
        _field("plan_type", pa.string(), nullable=False),
        _field("plan_number", pa.string(), nullable=False),
        _field("source_kind", pa.string(), nullable=False),
        _field("source_project", pa.string(), nullable=False),
        _field("source_content_fingerprint", pa.string(), nullable=False),
        _field("stage_project", pa.string(), nullable=False),
        _field("execution_api", pa.string(), nullable=False),
        _field("engine_id", pa.string(), nullable=False),
        _field("engine_version_requested", pa.string(), nullable=False),
        _field("engine_executable", pa.string()),
        _field("engine_executable_sha256", pa.string()),
        _field("controller_version", pa.string()),
        _field("controller_progid", pa.string()),
        _field("compute_mode", pa.string()),
        _field("expected_result_format", pa.string()),
        _field("selected_result_format", pa.string()),
        _field("initial_state", pa.string(), nullable=False),
        _field("expected_terminal_category", pa.string(), nullable=False),
        _field("terminal_category", pa.string(), nullable=False),
        _field("started_at", _UTC_NS, nullable=False),
        _field("finished_at", _UTC_NS, nullable=False),
        _field("wall_seconds", pa.float64(), nullable=False),
        _field("worker_exit_code", pa.int32()),
        _field("process_success", pa.bool_()),
        _field("completion_verified", pa.bool_()),
        _field("mechanical_completion", pa.bool_()),
        _field("error_count", pa.int64()),
        _field("warning_count", pa.int64()),
        _field("conflicts", pa.list_(pa.string()), nullable=False),
        _field("final_hdf_exists", pa.bool_(), nullable=False),
        _field("final_legacy_exists", pa.bool_(), nullable=False),
        _field("source_immutable", pa.bool_(), nullable=False),
        _field("all_invariants_passed", pa.bool_(), nullable=False),
        _field("failure_reason_code", pa.string()),
        _field("detail", pa.string()),
    ]
)

ARTIFACTS_SCHEMA = pa.schema(
    [
        _field("schema_version", pa.int16(), nullable=False),
        _field("run_id", pa.string(), nullable=False),
        _field("lane_id", pa.string(), nullable=False),
        _field("attempt_id", pa.string(), nullable=False),
        _field("snapshot_id", pa.string(), nullable=False),
        _field("phase", pa.string(), nullable=False),
        _field("captured_at", _UTC_NS, nullable=False),
        _field("root_kind", pa.string(), nullable=False),
        _field("root_path", pa.string(), nullable=False),
        _field("relative_path", pa.string(), nullable=False),
        _field("artifact_kind", pa.string(), nullable=False),
        _field("result_family", pa.string()),
        _field("data_origin", pa.string(), nullable=False),
        _field("exists", pa.bool_(), nullable=False),
        _field("is_file", pa.bool_(), nullable=False),
        _field("is_dir", pa.bool_(), nullable=False),
        _field("size_bytes", pa.int64()),
        _field("mtime_ns", pa.int64()),
        _field("volume_id", pa.string()),
        _field("file_id", pa.string()),
        _field("sha256", pa.string()),
        _field("stable_read", pa.bool_()),
        _field("content_fingerprint", pa.string()),
        _field("metadata_fingerprint", pa.string()),
        _field("reason_code", pa.string()),
        _field("detail", pa.string()),
    ]
)

OBSERVATIONS_SCHEMA = pa.schema(
    [
        _field("schema_version", pa.int16(), nullable=False),
        _field("run_id", pa.string(), nullable=False),
        _field("lane_id", pa.string(), nullable=False),
        _field("attempt_id", pa.string(), nullable=False),
        _field("evidence_id", pa.string(), nullable=False),
        _field("observation_name", pa.string(), nullable=False),
        _field("evidence_inspected_at", _UTC_NS, nullable=False),
        _field("observation_inspected_at", _UTC_NS, nullable=False),
        _field("declared_program_version", pa.string()),
        _field("state", pa.string(), nullable=False),
        _field("channel", pa.string(), nullable=False),
        _field("value_type", pa.string(), nullable=False),
        _field("value_bool", pa.bool_()),
        _field("value_int64", pa.int64()),
        _field("value_float64", pa.float64()),
        _field("value_string", pa.string()),
        _field("value_timestamp", _UTC_NS),
        _field("source_locator", pa.string()),
        _field("source_sha256", pa.string()),
        _field("observed_program_version", pa.string()),
        _field("reason_code", pa.string()),
        _field("detail", pa.string()),
        _field("conflicts", pa.list_(pa.string()), nullable=False),
    ]
)

EVENTS_SCHEMA = pa.schema(
    [
        _field("schema_version", pa.int16(), nullable=False),
        _field("run_id", pa.string(), nullable=False),
        _field("lane_id", pa.string(), nullable=False),
        _field("attempt_id", pa.string(), nullable=False),
        _field("sequence", pa.int64(), nullable=False),
        _field("event_at", _UTC_NS, nullable=False),
        _field("phase", pa.string(), nullable=False),
        _field("event_name", pa.string(), nullable=False),
        _field("status", pa.string(), nullable=False),
        _field("severity", pa.string(), nullable=False),
        _field("api", pa.string()),
        _field("reason_code", pa.string()),
        _field("detail", pa.string()),
        _field("relative_path", pa.string()),
        _field("pid", pa.int64()),
        _field("payload_json", pa.large_string()),
    ]
)

INVARIANTS_SCHEMA = pa.schema(
    [
        _field("schema_version", pa.int16(), nullable=False),
        _field("run_id", pa.string(), nullable=False),
        _field("lane_id", pa.string(), nullable=False),
        _field("attempt_id", pa.string(), nullable=False),
        _field("invariant_id", pa.string(), nullable=False),
        _field("name", pa.string(), nullable=False),
        _field("evaluated_at", _UTC_NS, nullable=False),
        _field("status", pa.string(), nullable=False),
        _field("expected", pa.string()),
        _field("observed", pa.string()),
        _field("reason_code", pa.string()),
        _field("detail", pa.string()),
        _field("supporting_snapshot_ids", pa.list_(pa.string()), nullable=False),
        _field("supporting_evidence_ids", pa.list_(pa.string()), nullable=False),
    ]
)

SCHEMAS: Mapping[str, pa.Schema] = {
    "lanes": LANES_SCHEMA,
    "artifacts": ARTIFACTS_SCHEMA,
    "observations": OBSERVATIONS_SCHEMA,
    "events": EVENTS_SCHEMA,
    "invariants": INVARIANTS_SCHEMA,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")
_VALUE_COLUMNS = (
    "value_bool",
    "value_int64",
    "value_float64",
    "value_string",
    "value_timestamp",
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESULT_FORMATS = {"hdf", "legacy"}
_TERMINAL_CATEGORIES = {
    "passed",
    "expected_failure",
    "failed_invariant",
    "execution_failed",
    "timed_out",
    "worker_crashed",
    "blocked",
    "harness_error",
}
_INITIAL_STATES = {
    "neither",
    "expected_only",
    "opposing_only",
    "both_expected_newer",
    "both_opposing_newer",
    "both_equal_mtime",
    "copied_preserved_times",
    "copied_rewritten_times",
}
_INVARIANT_NAMES = {
    "R01": "Read-only inspection",
    "R02": "Engine-owned result family",
    "R03": "No evidence-channel mixing",
    "R04": "Exact deletion allowlist",
    "R05": "Launch-gated mutation",
    "R06": "Quiescence-gated finalization",
    "R07": "Skipped-run immutability",
    "R08": "Visible uncertainty",
    "R09": "Atomic result promotion",
    "R10": "Stable evidence contract",
    "R11": "Source immutability",
    "R12": "Owned-process hygiene",
}


class SchemaValidationError(ValueError):
    """A qualification record does not satisfy its exact Arrow contract."""


@lru_cache(maxsize=1)
def _execution_evidence_registry() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Load public evidence registries only when observation rows are validated."""
    from ras_commander.ExecutionEvidence import (
        EVIDENCE_CHANNELS,
        EVIDENCE_STATES,
        EXECUTION_OBSERVATION_NAMES,
    )

    return (
        frozenset({"mechanical_completion", *EXECUTION_OBSERVATION_NAMES}),
        frozenset(EVIDENCE_STATES),
        frozenset(EVIDENCE_CHANNELS),
    )


def schema_metadata(
    table_name: str,
    *,
    manifest_sha256: str,
    git_head: str,
    created_at: datetime,
) -> Mapping[bytes, bytes]:
    if table_name not in SCHEMAS:
        raise KeyError(table_name)
    if not _SHA256_RE.fullmatch(manifest_sha256):
        raise SchemaValidationError("manifest_sha256 must be lowercase SHA-256")
    if not _GIT_RE.fullmatch(git_head):
        raise SchemaValidationError("git_head must be a lowercase 40-hex commit")
    if created_at.tzinfo is None:
        raise SchemaValidationError("created_at must be timezone-aware")
    return {
        b"qualification_schema_version": str(QUALIFICATION_SCHEMA_VERSION).encode(),
        b"table_name": table_name.encode(),
        b"manifest_sha256": manifest_sha256.encode(),
        b"git_head": git_head.encode(),
        b"pyarrow_version": pa.__version__.encode(),
        b"created_at": created_at.astimezone(timezone.utc).isoformat().encode(),
    }


def _validate_nonnull(table: pa.Table, schema: pa.Schema) -> None:
    for field in schema:
        if not field.nullable and table.column(field.name).null_count:
            raise SchemaValidationError(f"{field.name} contains null values")


def _validate_hash(value: Any, label: str, *, allow_none: bool = True) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise SchemaValidationError(f"{label} must be lowercase SHA-256")


def _validate_rows(table_name: str, rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        prefix = f"{table_name}[{index}]"
        if row.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
            raise SchemaValidationError(f"{prefix} has an unsupported schema_version")
        for identity_name in ("run_id", "lane_id", "attempt_id"):
            identity = row.get(identity_name)
            if (
                not isinstance(identity, str)
                or not _SAFE_ID_RE.fullmatch(identity)
                or identity in {".", ".."}
            ):
                raise SchemaValidationError(
                    f"{prefix}.{identity_name} must be a path-safe identifier"
                )
        if table_name == "lanes":
            _validate_hash(row.get("manifest_sha256"), f"{prefix}.manifest_sha256", allow_none=False)
            if not isinstance(row.get("git_head"), str) or not _GIT_RE.fullmatch(row["git_head"]):
                raise SchemaValidationError(f"{prefix}.git_head must be lowercase 40-hex")
            _validate_hash(
                row.get("source_content_fingerprint"),
                f"{prefix}.source_content_fingerprint",
                allow_none=False,
            )
            _validate_hash(
                row.get("engine_executable_sha256"),
                f"{prefix}.engine_executable_sha256",
            )
            duration = row.get("wall_seconds")
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration < 0:
                raise SchemaValidationError(f"{prefix}.wall_seconds must be finite and nonnegative")
            if not re.fullmatch(r"[0-9]{2}", str(row.get("plan_number", ""))):
                raise SchemaValidationError(f"{prefix}.plan_number must contain two digits")
            if row.get("execution_api") not in {"ras_cmdr", "ras_control"}:
                raise SchemaValidationError(f"{prefix}.execution_api is invalid")
            if row.get("expected_result_format") not in _RESULT_FORMATS:
                raise SchemaValidationError(
                    f"{prefix}.expected_result_format is invalid"
                )
            if (
                row.get("selected_result_format") is not None
                and row.get("selected_result_format") not in _RESULT_FORMATS
            ):
                raise SchemaValidationError(
                    f"{prefix}.selected_result_format is invalid"
                )
            if row.get("initial_state") not in _INITIAL_STATES:
                raise SchemaValidationError(f"{prefix}.initial_state is invalid")
            for terminal_field in (
                "expected_terminal_category",
                "terminal_category",
            ):
                if row.get(terminal_field) not in _TERMINAL_CATEGORIES:
                    raise SchemaValidationError(f"{prefix}.{terminal_field} is invalid")
            if row["finished_at"] < row["started_at"]:
                raise SchemaValidationError(
                    f"{prefix}.finished_at precedes started_at"
                )
            for count_name in ("error_count", "warning_count"):
                count = row.get(count_name)
                if count is not None and (
                    not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    raise SchemaValidationError(
                        f"{prefix}.{count_name} must be nonnegative"
                    )
            if row["execution_api"] == "ras_cmdr":
                if not row.get("engine_executable") or row.get(
                    "engine_executable_sha256"
                ) is None:
                    raise SchemaValidationError(
                        f"{prefix} ras_cmdr lane requires executable identity"
                    )
                if row.get("controller_version") or row.get("controller_progid"):
                    raise SchemaValidationError(
                        f"{prefix} ras_cmdr lane cannot claim Controller identity"
                    )
            else:
                if not row.get("controller_version") or not row.get(
                    "controller_progid"
                ):
                    raise SchemaValidationError(
                        f"{prefix} ras_control lane requires Controller identity"
                    )
                if row.get("engine_executable") or row.get(
                    "engine_executable_sha256"
                ):
                    raise SchemaValidationError(
                        f"{prefix} ras_control lane cannot claim executable identity"
                    )
        elif table_name == "artifacts":
            _validate_hash(row.get("sha256"), f"{prefix}.sha256")
            _validate_hash(row.get("content_fingerprint"), f"{prefix}.content_fingerprint")
            _validate_hash(row.get("metadata_fingerprint"), f"{prefix}.metadata_fingerprint")
            relative = row.get("relative_path")
            if (
                not isinstance(relative, str)
                or not relative
                or relative.startswith(("/", "\\"))
                or "\\" in relative
                or ".." in relative.split("/")
            ):
                raise SchemaValidationError(
                    f"{prefix}.relative_path must be a safe POSIX-relative path"
                )
            if row.get("result_family") not in {None, *_RESULT_FORMATS}:
                raise SchemaValidationError(f"{prefix}.result_family is invalid")
            size = row.get("size_bytes")
            if size is not None and (
                not isinstance(size, int) or isinstance(size, bool) or size < 0
            ):
                raise SchemaValidationError(
                    f"{prefix}.size_bytes must be nonnegative"
                )
            if row.get("exists") is False and (
                row.get("is_file")
                or row.get("is_dir")
                or any(
                    row.get(name) is not None
                    for name in ("size_bytes", "mtime_ns", "sha256", "stable_read")
                )
            ):
                raise SchemaValidationError(
                    f"{prefix} absent artifact retains existence metadata"
                )
            if row.get("is_file") and (
                row.get("stable_read") is not True or row.get("sha256") is None
            ):
                raise SchemaValidationError(
                    f"{prefix} file artifact lacks a stable content hash"
                )
        elif table_name == "observations":
            observation_names, evidence_states, evidence_channels = (
                _execution_evidence_registry()
            )
            observation_name = row.get("observation_name")
            if observation_name not in observation_names:
                raise SchemaValidationError(f"{prefix}.observation_name is not registered")
            if row.get("state") not in evidence_states:
                raise SchemaValidationError(f"{prefix}.state is invalid")
            if row.get("channel") not in evidence_channels:
                raise SchemaValidationError(f"{prefix}.channel is invalid")
            populated = [name for name in _VALUE_COLUMNS if row.get(name) is not None]
            state = row.get("state")
            value_type = row.get("value_type")
            if state == "available":
                if len(populated) != 1:
                    raise SchemaValidationError(f"{prefix} available observation must have exactly one value")
                expected_column = {
                    "bool": "value_bool",
                    "int64": "value_int64",
                    "float64": "value_float64",
                    "string": "value_string",
                    "timestamp": "value_timestamp",
                }.get(value_type)
                if expected_column != populated[0]:
                    raise SchemaValidationError(f"{prefix} value_type does not match populated value column")
            elif populated or value_type != "null":
                raise SchemaValidationError(f"{prefix} unavailable observation must use value_type='null'")
            _validate_hash(row.get("source_sha256"), f"{prefix}.source_sha256")
            float_value = row.get("value_float64")
            if float_value is not None and not math.isfinite(float_value):
                raise SchemaValidationError(
                    f"{prefix}.value_float64 must be finite"
                )
        elif table_name == "events":
            sequence = row.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise SchemaValidationError(f"{prefix}.sequence must be positive")
            relative = row.get("relative_path")
            if relative is not None and (
                not isinstance(relative, str)
                or relative.startswith(("/", "\\"))
                or "\\" in relative
                or ".." in relative.split("/")
            ):
                raise SchemaValidationError(
                    f"{prefix}.relative_path must be a safe POSIX-relative path"
                )
        elif table_name == "invariants":
            if row.get("status") not in {"pass", "fail", "not_applicable"}:
                raise SchemaValidationError(f"{prefix}.status is invalid")
            invariant_id = row.get("invariant_id")
            if invariant_id not in _INVARIANT_NAMES:
                raise SchemaValidationError(f"{prefix}.invariant_id is invalid")
            if row.get("name") != _INVARIANT_NAMES[invariant_id]:
                raise SchemaValidationError(
                    f"{prefix}.name disagrees with invariant_id"
                )


def validate_table(table_name: str, table: pa.Table) -> None:
    """Validate exact columns, types, nullability, and semantic row rules."""
    expected = SCHEMAS.get(table_name)
    if expected is None:
        raise KeyError(table_name)
    if table.schema.remove_metadata() != expected:
        raise SchemaValidationError(
            f"{table_name} schema mismatch:\nexpected={expected}\nactual={table.schema.remove_metadata()}"
        )
    _validate_nonnull(table, expected)
    _validate_rows(table_name, table.to_pylist())


def table_from_rows(
    table_name: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    metadata: Mapping[bytes, bytes] | None = None,
) -> pa.Table:
    """Build and validate a table without Pandas dtype inference."""
    schema = SCHEMAS.get(table_name)
    if schema is None:
        raise KeyError(table_name)
    materialized = [dict(row) for row in rows]
    expected_names = set(schema.names)
    for index, row in enumerate(materialized):
        extras = set(row) - expected_names
        missing = expected_names - set(row)
        if extras or missing:
            raise SchemaValidationError(
                f"{table_name}[{index}] fields mismatch: missing={sorted(missing)}, extra={sorted(extras)}"
            )
        for field in schema:
            if not pa.types.is_timestamp(field.type) or row[field.name] is None:
                continue
            value = row[field.name]
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise SchemaValidationError(
                        f"{table_name}[{index}].{field.name} is not an ISO timestamp"
                    ) from exc
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise SchemaValidationError(
                    f"{table_name}[{index}].{field.name} must be timezone-aware"
                )
            row[field.name] = value
    table = pa.Table.from_pylist(materialized, schema=schema)
    validate_table(table_name, table)
    return table.replace_schema_metadata(metadata) if metadata else table


__all__ = [
    "ARTIFACTS_SCHEMA",
    "EVENTS_SCHEMA",
    "INVARIANTS_SCHEMA",
    "LANES_SCHEMA",
    "OBSERVATIONS_SCHEMA",
    "QUALIFICATION_SCHEMA_VERSION",
    "SCHEMAS",
    "SchemaValidationError",
    "schema_metadata",
    "table_from_rows",
    "validate_table",
]
