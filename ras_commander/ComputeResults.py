"""
ComputeResults - Backward-compatible result dataclasses for compute functions.

These dataclasses wrap execution results with additional results_df data while
preserving backward compatibility with existing code that uses bool, Dict, or Tuple returns.

Classes:
    ComputeResult: Result of compute_plan() - backward compatible with bool
    ComputeParallelResult: Result of compute_parallel/test_mode - backward compatible with Dict[str, bool]
    RasControlResult: Result of RasControl.run_plan() - backward compatible with Tuple[bool, List[str]]
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pandas as pd


def _strict_json_object_copy(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> Dict[str, Any]:
    """Return a detached strict-JSON copy of a result metadata mapping."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must contain only finite JSON-safe values"
        ) from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must serialize to a JSON object")
    return decoded


def _positive_int(value: Any, field_name: str) -> int:
    """Return one exact positive integer without accepting bool coercion."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _positive_finite_number(value: Any, field_name: str) -> float:
    """Return one finite positive float without accepting bool coercion."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{field_name} must be finite and positive")
    return float(value)


def _strict_bool(value: Any, field_name: str) -> bool:
    """Require an actual bool for a safety decision field."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _nonempty_text(value: Any, field_name: str) -> str:
    """Return normalized nonempty text without stringifying arbitrary values."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonempty string")
    return value.strip()


def _optional_nonempty_text(value: Any, field_name: str) -> Optional[str]:
    """Validate optional JSON-safe text fields."""
    if value is None:
        return None
    return _nonempty_text(value, field_name)


def _record_tuple(value: Any, field_name: str) -> Tuple['RasProcessRecord', ...]:
    """Freeze and type-check a public process-record collection."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple")
    records = tuple(value)
    if any(not isinstance(item, RasProcessRecord) for item in records):
        raise ValueError(f"{field_name} must contain only RasProcessRecord values")
    identities = [item.identity for item in records]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{field_name} contains duplicate process identities")
    return records


def _query_error_tuple(
    value: Any,
    field_name: str,
) -> Tuple['RasProcessQueryError', ...]:
    """Freeze and type-check a public query-error collection."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple")
    errors = tuple(value)
    if any(not isinstance(item, RasProcessQueryError) for item in errors):
        raise ValueError(
            f"{field_name} must contain only RasProcessQueryError values"
        )
    return errors


@dataclass(frozen=True)
class RasProcessRecord:
    """Immutable identity and command metadata for one HEC-RAS process.

    ``pid`` alone is not a stable process identity because operating systems
    reuse process identifiers.  Callers that retain a record must use the
    ``(pid, create_time)`` pair exposed by :attr:`identity`. ``create_time`` is
    a Unix epoch timestamp in seconds, matching ``psutil``.
    """

    pid: int
    create_time: float
    name: str
    executable_path: Optional[str] = None
    command_line: Tuple[str, ...] = ()
    working_directory: Optional[str] = None
    tracked: bool = False
    session_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize public constructor inputs to immutable JSON-safe values."""
        object.__setattr__(self, "pid", _positive_int(self.pid, "pid"))
        object.__setattr__(
            self,
            "create_time",
            _positive_finite_number(self.create_time, "create_time"),
        )
        object.__setattr__(self, "name", _nonempty_text(self.name, "name"))
        object.__setattr__(
            self,
            "executable_path",
            _optional_nonempty_text(self.executable_path, "executable_path"),
        )
        if not isinstance(self.command_line, (list, tuple)) or any(
            not isinstance(token, str) for token in self.command_line
        ):
            raise ValueError("command_line must be a list or tuple of strings")
        object.__setattr__(
            self,
            "command_line",
            tuple(self.command_line),
        )
        object.__setattr__(
            self,
            "working_directory",
            _optional_nonempty_text(
                self.working_directory,
                "working_directory",
            ),
        )
        object.__setattr__(self, "tracked", _strict_bool(self.tracked, "tracked"))
        object.__setattr__(
            self,
            "session_id",
            _optional_nonempty_text(self.session_id, "session_id"),
        )

    @property
    def identity(self) -> Tuple[int, float]:
        """Return the non-reusable identity captured for this process."""
        return (self.pid, self.create_time)

    def __bool__(self) -> bool:
        raise TypeError(
            "RasProcessRecord has no truth-value contract; inspect its fields"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "pid": self.pid,
            "create_time": self.create_time,
            "name": self.name,
            "executable_path": self.executable_path,
            "command_line": list(self.command_line),
            "working_directory": self.working_directory,
            "tracked": self.tracked,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class RasProcessQueryError:
    """A process field that could not be queried during strict inspection."""

    pid: Optional[int]
    operation: str
    reason_code: str
    exception_type: str
    detail: str

    def __post_init__(self) -> None:
        """Normalize public constructor inputs to JSON-safe values."""
        object.__setattr__(
            self,
            "pid",
            None if self.pid is None else _positive_int(self.pid, "pid"),
        )
        object.__setattr__(
            self,
            "operation",
            _nonempty_text(self.operation, "operation"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _nonempty_text(self.reason_code, "reason_code"),
        )
        object.__setattr__(
            self,
            "exception_type",
            _nonempty_text(self.exception_type, "exception_type"),
        )
        if not isinstance(self.detail, str):
            raise ValueError("detail must be a string")

    def __bool__(self) -> bool:
        raise TypeError(
            "RasProcessQueryError has no truth-value contract; inspect its fields"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "pid": self.pid,
            "operation": self.operation,
            "reason_code": self.reason_code,
            "exception_type": self.exception_type,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RasProcessInventory:
    """Strict host inventory of HEC-RAS compute processes.

    ``complete`` is false whenever a process could not be classified or any
    required field of a matching launcher, solver, sediment/water-quality
    engine, or geometry preprocessor could not be read. Consumers that make
    safety decisions must fail closed when it is false. ``observed_at`` is a
    Unix epoch timestamp in seconds.
    """

    observed_at: float
    complete: bool = True
    processes: Tuple[RasProcessRecord, ...] = ()
    query_errors: Tuple[RasProcessQueryError, ...] = ()

    def __post_init__(self) -> None:
        """Freeze collections supplied through the public constructor."""
        object.__setattr__(
            self,
            "observed_at",
            _positive_finite_number(self.observed_at, "observed_at"),
        )
        object.__setattr__(
            self,
            "complete",
            _strict_bool(self.complete, "complete"),
        )
        object.__setattr__(
            self,
            "processes",
            _record_tuple(self.processes, "processes"),
        )
        object.__setattr__(
            self,
            "query_errors",
            _query_error_tuple(self.query_errors, "query_errors"),
        )
        if self.complete and self.query_errors:
            raise ValueError("complete inventory cannot contain query_errors")
        if not self.complete and not self.query_errors:
            raise ValueError("incomplete inventory requires query_errors")

    def __bool__(self) -> bool:
        raise TypeError(
            "RasProcessInventory has explicit completeness; inspect '.complete'"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "observed_at": self.observed_at,
            "complete": self.complete,
            "processes": [item.to_dict() for item in self.processes],
            "query_errors": [item.to_dict() for item in self.query_errors],
        }


@dataclass(frozen=True)
class PlanProcessInventory:
    """Strict process inventory narrowed to one project and plan.

    ``observed_at`` is a Unix epoch timestamp in seconds.
    """

    observed_at: float
    plan_number: str
    project_path: str
    plan_path: str
    tmp_hdf_path: Optional[str]
    complete: bool
    matched: Tuple[RasProcessRecord, ...] = ()
    query_errors: Tuple[RasProcessQueryError, ...] = ()

    def __post_init__(self) -> None:
        """Normalize paths and freeze collections supplied by callers."""
        object.__setattr__(
            self,
            "observed_at",
            _positive_finite_number(self.observed_at, "observed_at"),
        )
        object.__setattr__(
            self,
            "plan_number",
            _nonempty_text(self.plan_number, "plan_number"),
        )
        object.__setattr__(
            self,
            "project_path",
            _nonempty_text(self.project_path, "project_path"),
        )
        object.__setattr__(
            self,
            "plan_path",
            _nonempty_text(self.plan_path, "plan_path"),
        )
        object.__setattr__(
            self,
            "tmp_hdf_path",
            _optional_nonempty_text(self.tmp_hdf_path, "tmp_hdf_path"),
        )
        object.__setattr__(
            self,
            "complete",
            _strict_bool(self.complete, "complete"),
        )
        object.__setattr__(
            self,
            "matched",
            _record_tuple(self.matched, "matched"),
        )
        object.__setattr__(
            self,
            "query_errors",
            _query_error_tuple(self.query_errors, "query_errors"),
        )
        if self.complete and self.query_errors:
            raise ValueError("complete plan inventory cannot contain query_errors")
        if not self.complete and not self.query_errors:
            raise ValueError("incomplete plan inventory requires query_errors")

    def __bool__(self) -> bool:
        raise TypeError(
            "PlanProcessInventory has explicit completeness; inspect '.complete'"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "observed_at": self.observed_at,
            "plan_number": self.plan_number,
            "project_path": self.project_path,
            "plan_path": self.plan_path,
            "tmp_hdf_path": self.tmp_hdf_path,
            "complete": self.complete,
            "matched": [item.to_dict() for item in self.matched],
            "query_errors": [item.to_dict() for item in self.query_errors],
        }


@dataclass(frozen=True)
class PlanCancellationResult:
    """Structured outcome from exact plan process-tree cancellation.

    This type deliberately rejects truth-value testing.  Callers must inspect
    :attr:`quiescence_confirmed` because ``False`` (known survivor) and
    ``None`` (query uncertainty) require different recovery decisions.
    ``cancellation_attempted`` becomes true only when a terminate or kill call
    was actually attempted; :attr:`matched_count` separately reports the
    number of processes selected by the initial exact-plan scan. Optional
    ``started_at`` and ``finished_at`` values are Unix epoch timestamps in
    seconds.
    """

    plan_number: str
    project_path: str
    plan_path: str
    tmp_hdf_path: Optional[str]
    cancellation_attempted: bool
    pre_scan_complete: bool
    post_scan_complete: bool
    matched: Tuple[RasProcessRecord, ...] = ()
    stopped: Tuple[RasProcessRecord, ...] = ()
    survivors: Tuple[RasProcessRecord, ...] = ()
    query_errors: Tuple[RasProcessQueryError, ...] = ()
    quiescence_confirmed: Optional[bool] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def __post_init__(self) -> None:
        """Normalize paths and freeze collections supplied by callers."""
        object.__setattr__(
            self,
            "plan_number",
            _nonempty_text(self.plan_number, "plan_number"),
        )
        object.__setattr__(
            self,
            "project_path",
            _nonempty_text(self.project_path, "project_path"),
        )
        object.__setattr__(
            self,
            "plan_path",
            _nonempty_text(self.plan_path, "plan_path"),
        )
        object.__setattr__(
            self,
            "tmp_hdf_path",
            _optional_nonempty_text(self.tmp_hdf_path, "tmp_hdf_path"),
        )
        object.__setattr__(
            self,
            "cancellation_attempted",
            _strict_bool(self.cancellation_attempted, "cancellation_attempted"),
        )
        object.__setattr__(
            self,
            "pre_scan_complete",
            _strict_bool(self.pre_scan_complete, "pre_scan_complete"),
        )
        object.__setattr__(
            self,
            "post_scan_complete",
            _strict_bool(self.post_scan_complete, "post_scan_complete"),
        )
        object.__setattr__(
            self,
            "matched",
            _record_tuple(self.matched, "matched"),
        )
        object.__setattr__(
            self,
            "stopped",
            _record_tuple(self.stopped, "stopped"),
        )
        object.__setattr__(
            self,
            "survivors",
            _record_tuple(self.survivors, "survivors"),
        )
        object.__setattr__(
            self,
            "query_errors",
            _query_error_tuple(self.query_errors, "query_errors"),
        )
        if self.quiescence_confirmed is not None and not isinstance(
            self.quiescence_confirmed,
            bool,
        ):
            raise ValueError("quiescence_confirmed must be a boolean or null")
        if (
            not self.pre_scan_complete or not self.post_scan_complete
        ) and not self.query_errors:
            raise ValueError(
                "incomplete cancellation scans require query_errors"
            )
        if (self.started_at is None) != (self.finished_at is None):
            raise ValueError("started_at and finished_at must both be set or null")
        if self.started_at is not None and self.finished_at is not None:
            object.__setattr__(
                self,
                "started_at",
                _positive_finite_number(self.started_at, "started_at"),
            )
            object.__setattr__(
                self,
                "finished_at",
                _positive_finite_number(self.finished_at, "finished_at"),
            )
            if self.finished_at < self.started_at:
                raise ValueError("finished_at cannot precede started_at")

        matched_identities = {item.identity for item in self.matched}
        stopped_identities = {item.identity for item in self.stopped}
        survivor_identities = {item.identity for item in self.survivors}
        if self.cancellation_attempted and not self.matched:
            raise ValueError(
                "cancellation_attempted requires at least one initial match"
            )
        if stopped_identities & survivor_identities:
            raise ValueError("stopped and survivors cannot share a process identity")
        if self.quiescence_confirmed is True:
            if (
                not self.pre_scan_complete
                or not self.post_scan_complete
                or self.query_errors
                or self.survivors
                or not matched_identities.issubset(stopped_identities)
            ):
                raise ValueError(
                    "confirmed quiescence requires complete scans, no query "
                    "uncertainty or survivors, and every initial match stopped"
                )
        elif self.quiescence_confirmed is False:
            if not self.survivors:
                raise ValueError("known non-quiescence requires at least one survivor")
        elif self.survivors or (
            self.pre_scan_complete
            and self.post_scan_complete
            and not self.query_errors
        ):
            raise ValueError(
                "indeterminate quiescence requires uncertainty and no known survivor"
            )

    @property
    def matched_count(self) -> int:
        """Return the number of exact launcher/solver matches found initially."""
        return len(self.matched)

    def __bool__(self) -> bool:
        raise TypeError(
            "PlanCancellationResult has tri-state semantics; inspect "
            "'.quiescence_confirmed' explicitly"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "plan_number": self.plan_number,
            "project_path": self.project_path,
            "plan_path": self.plan_path,
            "tmp_hdf_path": self.tmp_hdf_path,
            "cancellation_attempted": self.cancellation_attempted,
            "pre_scan_complete": self.pre_scan_complete,
            "post_scan_complete": self.post_scan_complete,
            "matched": [item.to_dict() for item in self.matched],
            "stopped": [item.to_dict() for item in self.stopped],
            "survivors": [item.to_dict() for item in self.survivors],
            "query_errors": [item.to_dict() for item in self.query_errors],
            "quiescence_confirmed": self.quiescence_confirmed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class ComputeResult:
    """
    Result of RasCmdr.compute_plan().

    Backward compatible with bool via __bool__. Existing code like
    ``if RasCmdr.compute_plan("01"):`` continues to work unchanged.

    Attributes:
        success: Whether the execution succeeded.
        results_df_row: Single row from results_df for the executed plan,
            or None if unavailable (e.g., failed execution, dest_folder used,
            or results_df extraction error).
        completion_verified: ``True`` or ``False`` when ``verify=True`` checked
            HEC-RAS completion; ``None`` when completion verification was not
            requested.
        execution_details: JSON-safe execution-engine identity and terminal
            safety gates reported by ``RasCmdr.compute_plan()``. The field is
            additive and defaults to an empty dictionary for callers that
            construct ``ComputeResult`` directly.
    Examples:
        # Old usage (still works):
        if RasCmdr.compute_plan("01"):
            print("done")

        # New usage:
        result = RasCmdr.compute_plan("01")
        if result:
            print(result.results_df_row['runtime_complete_process_hours'])
    """
    success: bool
    results_df_row: Optional[pd.Series] = None
    completion_verified: Optional[bool] = None
    execution_details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Detach and validate execution metadata as strict JSON data."""
        self.execution_details = _strict_json_object_copy(
            self.execution_details,
            field_name="ComputeResult.execution_details",
        )

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        has_row = self.results_df_row is not None
        verification = (
            "unverified"
            if self.completion_verified is None
            else f"completion_verified={self.completion_verified}"
        )
        return (
            f"ComputeResult({status}, {verification}, "
            f"results_df_row={'available' if has_row else 'None'})"
        )


@dataclass
class ComputeParallelResult:
    """
    Result of RasCmdr.compute_parallel() and compute_test_mode().

    Backward compatible with Dict[str, bool] via __getitem__, items(), keys(), values().
    Existing code like ``for plan, ok in results.items():`` continues to work unchanged.

    Attributes:
        execution_results: Dict mapping plan numbers to success booleans.
        results_df: DataFrame containing results_df rows for executed plans only.
            May be empty if no results could be extracted.
        execution_details_by_plan: JSON-safe execution details keyed by plan
            number. A plan maps to an empty dictionary when no structured
            details were available for that outcome.

    Examples:
        # Old usage (still works):
        results = RasCmdr.compute_parallel(["01", "02"])
        for plan, ok in results.items():
            print(f"{plan}: {ok}")

        # New usage:
        results = RasCmdr.compute_parallel(["01", "02"])
        print(results.results_df[['plan_number', 'completed', 'vol_error_percent']])

    Note:
        __bool__ returns True if execution_results has any entries,
        False if empty (whether due to error or no plans to execute).
    """
    execution_results: Dict[str, bool] = field(default_factory=dict)
    results_df: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    execution_details_by_plan: Dict[str, Dict[str, Any]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Detach and validate per-plan evidence as strict JSON objects."""
        if not isinstance(self.execution_details_by_plan, Mapping):
            raise TypeError(
                "ComputeParallelResult.execution_details_by_plan must be a "
                "mapping"
            )
        normalized: Dict[str, Dict[str, Any]] = {}
        for plan_number, details in self.execution_details_by_plan.items():
            if not isinstance(plan_number, str):
                raise ValueError(
                    "ComputeParallelResult.execution_details_by_plan keys "
                    "must be strings"
                )
            normalized[plan_number] = _strict_json_object_copy(
                details,
                field_name=(
                    "ComputeParallelResult.execution_details_by_plan"
                    f"[{plan_number!r}]"
                ),
            )
        self.execution_details_by_plan = normalized

    def __getitem__(self, key: str) -> bool:
        return self.execution_results[key]

    def __contains__(self, key: str) -> bool:
        return key in self.execution_results

    def __iter__(self) -> Iterator[str]:
        return iter(self.execution_results)

    def __len__(self) -> int:
        return len(self.execution_results)

    def __bool__(self) -> bool:
        return bool(self.execution_results)

    def items(self):
        return self.execution_results.items()

    def keys(self):
        return self.execution_results.keys()

    def values(self):
        return self.execution_results.values()

    def get(self, key: str, default: Any = None) -> Any:
        return self.execution_results.get(key, default)

    def __repr__(self) -> str:
        n_success = sum(1 for v in self.execution_results.values() if v)
        n_total = len(self.execution_results)
        return f"ComputeParallelResult({n_success}/{n_total} succeeded, results_df={len(self.results_df)} rows)"


@dataclass
class RasControlResult:
    """
    Result of RasControl.run_plan().

    Backward compatible with Tuple[bool, List[str]] via __iter__.
    Existing code like ``success, msgs = RasControl.run_plan("01")`` continues to work.

    Attributes:
        success: Whether the execution succeeded.
        messages: List of computation messages from HEC-RAS COM interface.
        results_df_row: Single row from results_df for the executed plan,
            or None if unavailable.
        execution_details: JSON-safe Controller identity, compute mode,
            watchdog status, message counts, and timing provenance reported by
            ``RasControl.run_plan()``. Mode-specific keys are additive.

    Examples:
        # Old usage (still works):
        success, msgs = RasControl.run_plan("01")

        # New usage - access results_df_row (requires attribute access):
        result = RasControl.run_plan("01")
        if result.results_df_row is not None:
            print(result.results_df_row['runtime_complete_process_hours'])

    Note:
        results_df_row is only accessible via attribute access, not tuple
        unpacking. Tuple unpacking (``success, msgs = ...``) only yields
        success and messages via __iter__.
    """
    success: bool
    messages: List[str] = field(default_factory=list)
    results_df_row: Optional[pd.Series] = None
    execution_details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Detach and validate execution metadata as strict JSON data."""
        self.execution_details = _strict_json_object_copy(
            self.execution_details,
            field_name="RasControlResult.execution_details",
        )

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self) -> Iterator:
        return iter((self.success, self.messages))

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        n_msgs = len(self.messages)
        has_row = self.results_df_row is not None
        return f"RasControlResult({status}, {n_msgs} messages, results_df_row={'available' if has_row else 'None'})"


@dataclass
class PreprocessResult:
    """
    Result of RasPreprocess.preprocess_plan().

    Backward compatible with bool via __bool__. Existing code like
    ``if RasPreprocess.preprocess_plan("01"):`` works unchanged.

    Attributes:
        success: Whether preprocessing succeeded.
        plan_number: Plan number that was preprocessed (e.g., "01").
        geometry_number: Geometry number extracted from plan file (e.g., "04").
        tmp_hdf_path: Path to the generated .tmp.hdf file, or None on failure.
        b_file_path: Path to the generated .b## file, or None on failure.
        x_file_path: Path to the generated .x## file, or None on failure.
        elapsed_seconds: Wall-clock time for preprocessing.
        signal_source: ``bco``, ``owned_process_artifacts``,
            ``natural_completion``, ``full_result_copy``, ``timeout``, or a
            blocking-condition identifier.
        full_result_copied: Whether a naturally completed ``p##.hdf`` supplied
            the temporary HDF fallback.
        timed_out: Whether preprocessing exceeded its bounded wait.
        error: Error message if preprocessing failed, None on success.

    Examples:
        # Simple usage (bool-compatible):
        if RasPreprocess.preprocess_plan("01"):
            print("Ready for Linux execution")

        # Rich usage:
        result = RasPreprocess.preprocess_plan("01")
        if result:
            print(f"Completed in {result.elapsed_seconds:.1f}s")
            print(f"  tmp.hdf: {result.tmp_hdf_path}")
            print(f"  .b file: {result.b_file_path}")
            print(f"  .x file: {result.x_file_path}")
    """
    success: bool
    plan_number: str = ""
    geometry_number: Optional[str] = None
    tmp_hdf_path: Optional[Path] = None
    b_file_path: Optional[Path] = None
    x_file_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    signal_source: Optional[str] = None
    full_result_copied: bool = False
    timed_out: bool = False
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return f"PreprocessResult({status}, plan={self.plan_number}, geom={self.geometry_number}, time={time_str})"


@dataclass
class GeometryPreprocessResult:
    """
    Result of a HEC-RAS geometry-preprocessing operation.

    This result supports both delivery/assembly validation through
    ``GeomPreprocessor`` and the standalone vendor ``RasGeomPreprocess`` action
    used after Linux/Wine plan materialization. The optional executable and HDF
    provenance fields are populated by the standalone action.
    """
    success: bool
    plan_number: str = ""
    geometry_number: Optional[str] = None
    flow_type: str = "Unknown"
    elapsed_seconds: float = 0.0
    command: str = ""
    return_code: Optional[int] = None
    executable_path: Optional[Path] = None
    executable_sha256: Optional[str] = None
    input_hdf_path: Optional[Path] = None
    x_file_path: Optional[Path] = None
    input_hdf_sha256_before: Optional[str] = None
    input_hdf_sha256_after: Optional[str] = None
    output_changed: bool = False
    hdf_readable: bool = False
    geometry_group_present: bool = False
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    signal_detected: Optional[str] = None
    compute_message_paths: List[Path] = field(default_factory=list)
    artifact_paths: List[Path] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    first_error_line: Optional[str] = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return (
            "GeometryPreprocessResult("
            f"{status}, plan={self.plan_number}, geom={self.geometry_number}, "
            f"flow_type={self.flow_type}, time={time_str})"
        )


@dataclass
class GeometryLayerResult:
    """
    Result of a single RasGeometryCompute layer-generation call.

    Returned by RasGeometryCompute.generate_edge_lines() /
    generate_interpolation_surface() / generate_flow_paths(). Backward compatible
    with bool via __bool__.

    Attributes:
        success: Whether the layer was generated (or already present when skipped).
        layer: Native HDF group written, e.g. "River Edge Lines".
        geom_hdf_path: Geometry HDF that was operated on.
        skipped: True when the layer already existed and overwrite=False.
        backup_path: Path to the dated GeoJSON backup of pre-existing features,
            when one was written before overwriting.
        elapsed_seconds: Wall-clock time for the generation call.
        error: Error message on failure, else None.
    """
    success: bool
    layer: str
    geom_hdf_path: Path
    skipped: bool = False
    backup_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        if self.skipped:
            status = 'SKIPPED'
        elif self.success:
            status = 'SUCCESS'
        else:
            status = 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return f"GeometryLayerResult({status}, layer={self.layer!r}, time={time_str})"


@dataclass
class GeometryCompleteResult:
    """
    Result of RasGeometryCompute.compute_geometry() (RASGeometry.CompleteForComputations).

    Backward compatible with bool via __bool__. Distinct from
    GeometryPreprocessResult, which wraps HEC-RAS's numerical geometry
    preprocessor (a different pipeline).

    Attributes:
        success: Whether the geometry-completion pipeline succeeded.
        geom_hdf_path: Geometry HDF that was completed.
        edge_lines_written: River Edge Lines present after the run.
        interpolation_surface_written: XS Interpolation Surfaces present after the run.
        flow_paths_written: River Flow Paths present after the run.
        backup_path: Path to a dated GeoJSON backup written before overwriting, if any.
        elapsed_seconds: Wall-clock time for the call.
        error: Error message on failure, else None.
    """
    success: bool
    geom_hdf_path: Path
    edge_lines_written: bool = False
    interpolation_surface_written: bool = False
    flow_paths_written: bool = False
    backup_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return (
            f"GeometryCompleteResult({status}, "
            f"edge_lines={self.edge_lines_written}, "
            f"interp_surface={self.interpolation_surface_written}, "
            f"flow_paths={self.flow_paths_written}, time={time_str})"
        )
