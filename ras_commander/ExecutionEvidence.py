"""Version-aware, read-only evidence for HEC-RAS plan execution artifacts."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from numbers import Number
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic, Literal, Mapping, Optional, TypeVar, Union

import h5py
import numpy as np
import pandas as pd

from .LoggingConfig import get_logger
from .ExecutionArtifacts import (
    normalize_program_version,
    resolve_plan_result_artifact,
)
from .RasPrj import RasPrj, ras
from .RasUtils import RasUtils
from .hdf.HdfUtils import HdfUtils
from .results.ResultsParser import ResultsParser

logger = get_logger(__name__)

T = TypeVar("T")

EvidenceState = Literal[
    "available",
    "not_available_in_version",
    "not_inspected",
    "failed",
]
EvidenceChannel = Literal[
    "derived",
    "filesystem",
    "hdf",
    "stored_message",
    "legacy_output",
    "process",
    "com",
]
ObservationName = Literal[
    "result_artifact_exists",
    "result_artifact_modified_at",
    "result_artifact_modified_after_threshold",
    "result_artifact_structural_state",
    "producer_program_version",
    "completion_attribute",
    "completion_message_hdf",
    "completion_message_stored",
    "message_error_count",
    "message_warning_count",
    "message_first_error",
    "runtime_seconds",
    "simulation_start",
    "simulation_end",
    "process_success",
    "com_completion",
]

EVIDENCE_STATES: tuple[str, ...] = (
    "available",
    "not_available_in_version",
    "not_inspected",
    "failed",
)
EVIDENCE_CHANNELS: tuple[str, ...] = (
    "derived",
    "filesystem",
    "hdf",
    "stored_message",
    "legacy_output",
    "process",
    "com",
)
EXECUTION_OBSERVATION_NAMES: tuple[str, ...] = (
    "result_artifact_exists",
    "result_artifact_modified_at",
    "result_artifact_modified_after_threshold",
    "result_artifact_structural_state",
    "producer_program_version",
    "completion_attribute",
    "completion_message_hdf",
    "completion_message_stored",
    "message_error_count",
    "message_warning_count",
    "message_first_error",
    "runtime_seconds",
    "simulation_start",
    "simulation_end",
    "process_success",
    "com_completion",
)

_OBSERVATION_SPECS: Mapping[str, tuple[tuple[type, ...], frozenset[str]]] = {
    "result_artifact_exists": ((bool,), frozenset({"filesystem"})),
    "result_artifact_modified_at": ((datetime,), frozenset({"filesystem"})),
    "result_artifact_modified_after_threshold": (
        (bool,),
        frozenset({"filesystem"}),
    ),
    "result_artifact_structural_state": (
        (str,),
        frozenset({"hdf", "legacy_output"}),
    ),
    "producer_program_version": (
        (str,),
        frozenset({"hdf", "stored_message", "legacy_output"}),
    ),
    "completion_attribute": ((bool,), frozenset({"hdf"})),
    "completion_message_hdf": ((bool,), frozenset({"hdf"})),
    "completion_message_stored": (
        (bool,),
        frozenset({"stored_message"}),
    ),
    "message_error_count": (
        (int,),
        frozenset({"hdf", "stored_message"}),
    ),
    "message_warning_count": (
        (int,),
        frozenset({"hdf", "stored_message"}),
    ),
    "message_first_error": (
        (str,),
        frozenset({"hdf", "stored_message"}),
    ),
    "runtime_seconds": (
        (int, float),
        frozenset({"hdf", "stored_message"}),
    ),
    "simulation_start": (
        (datetime,),
        frozenset({"hdf", "filesystem"}),
    ),
    "simulation_end": (
        (datetime,),
        frozenset({"hdf", "filesystem"}),
    ),
    "process_success": ((bool,), frozenset({"process"})),
    "com_completion": ((bool,), frozenset({"com"})),
}

_HDF_MESSAGE_PATH = "Results/Summary/Compute Messages (text)"
_PLAN_INFORMATION_PATH = "Plan Data/Plan Information"
_COMPUTE_PROCESSES_PATH = "Results/Summary/Compute Processes"
_COMPLETION_ATTRIBUTE_UNAVAILABLE = {
    "5.0.1",
    "5.0.3",
    "5.0.6",
    "5.0.7",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


@dataclass(frozen=True)
class EvidenceObservation(Generic[T]):
    """One typed execution observation with explicit state and provenance."""

    state: EvidenceState
    value: Optional[T]
    channel: EvidenceChannel
    source_locator: Optional[str]
    source_sha256: Optional[str]
    observed_program_version: Optional[str]
    inspected_at: datetime
    reason_code: Optional[str] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.state not in EVIDENCE_STATES:
            raise ValueError(f"Unsupported evidence state: {self.state!r}")
        if self.channel not in EVIDENCE_CHANNELS:
            raise ValueError(f"Unsupported evidence channel: {self.channel!r}")
        if self.inspected_at.tzinfo is None:
            raise ValueError("inspected_at must be timezone-aware")
        if self.state == "available" and self.value is None:
            raise ValueError("available evidence must contain a value")
        if self.state != "available" and self.value is not None:
            raise ValueError(
                f"{self.state} evidence cannot contain a value"
            )
        if self.state != "available" and not self.reason_code:
            raise ValueError(
                f"{self.state} evidence must include a reason_code"
            )
        if self.source_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.source_sha256
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        if self.detail is not None and len(self.detail) > 1000:
            raise ValueError("detail must not exceed 1000 characters")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable observation record."""
        return {
            "state": self.state,
            "value": _json_value(self.value),
            "channel": self.channel,
            "source_locator": self.source_locator,
            "source_sha256": self.source_sha256,
            "observed_program_version": self.observed_program_version,
            "inspected_at": self.inspected_at.isoformat(),
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ExecutionEvidence:
    """Immutable, version-aware evidence for one HEC-RAS plan result."""

    schema_version: int
    evidence_id: str
    inspected_at: datetime
    project_file: Path
    plan_file: Path
    plan_number: str
    declared_program_version: Optional[str]
    mechanical_completion: EvidenceObservation[bool]
    observations: Mapping[ObservationName, EvidenceObservation[Any]]
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Only execution evidence schema_version=1 is supported")
        if not self.evidence_id:
            raise ValueError("evidence_id must not be empty")
        if self.inspected_at.tzinfo is None:
            raise ValueError("inspected_at must be timezone-aware")
        if not re.fullmatch(r"\d{2}", self.plan_number):
            raise ValueError("plan_number must be a two-digit string")
        if self.mechanical_completion.channel != "derived":
            raise ValueError("mechanical_completion must use the derived channel")
        if (
            self.mechanical_completion.state == "available"
            and not isinstance(self.mechanical_completion.value, bool)
        ):
            raise TypeError("mechanical_completion must contain a bool")

        copied = dict(self.observations)
        actual_names = set(copied)
        expected_names = set(EXECUTION_OBSERVATION_NAMES)
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise ValueError(
                "execution observation registry mismatch: "
                f"missing={missing}, extra={extra}"
            )

        for name in EXECUTION_OBSERVATION_NAMES:
            observation = copied[name]
            if not isinstance(observation, EvidenceObservation):
                raise TypeError(f"Observation {name!r} has an invalid value")
            value_types, channels = _OBSERVATION_SPECS[name]
            if observation.channel not in channels:
                raise ValueError(
                    f"Observation {name!r} cannot use channel "
                    f"{observation.channel!r}"
                )
            value = observation.value
            if observation.state == "available":
                if int in value_types and isinstance(value, bool):
                    raise TypeError(
                        f"Observation {name!r} cannot use bool as an integer"
                    )
                if not isinstance(value, value_types):
                    raise TypeError(
                        f"Observation {name!r} requires "
                        f"{value_types}, got {type(value)}"
                    )

        object.__setattr__(self, "project_file", Path(self.project_file))
        object.__setattr__(self, "plan_file", Path(self.plan_file))
        object.__setattr__(self, "observations", MappingProxyType(copied))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable evidence record without message text."""
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "inspected_at": self.inspected_at.isoformat(),
            "project_file": str(self.project_file),
            "plan_file": str(self.plan_file),
            "plan_number": self.plan_number,
            "declared_program_version": self.declared_program_version,
            "mechanical_completion": self.mechanical_completion.to_dict(),
            "observations": {
                name: self.observations[name].to_dict()
                for name in EXECUTION_OBSERVATION_NAMES
            },
            "conflicts": list(self.conflicts),
        }


def _observation(
    inspected_at: datetime,
    *,
    state: EvidenceState,
    channel: EvidenceChannel,
    value: Any = None,
    source_locator: Optional[str] = None,
    source_sha256: Optional[str] = None,
    observed_program_version: Optional[str] = None,
    reason_code: Optional[str] = None,
    detail: Optional[str] = None,
) -> EvidenceObservation[Any]:
    return EvidenceObservation(
        state=state,
        value=value,
        channel=channel,
        source_locator=source_locator,
        source_sha256=source_sha256,
        observed_program_version=observed_program_version,
        inspected_at=inspected_at,
        reason_code=reason_code,
        detail=detail,
    )


def _stable_sha256(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_identity = (before.st_size, before.st_mtime_ns)
    after_identity = (after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise RuntimeError(f"Source changed while hashing: {path}")
    return digest.hexdigest()


def _attach_source_sha256(
    observations: dict[str, EvidenceObservation[Any]],
    source_path: Path,
    source_sha256: str,
) -> None:
    """Attach a digest after inspection and hashing share a stable window."""
    source_prefix = str(source_path)
    for name, observation in tuple(observations.items()):
        locator = observation.source_locator
        if locator == source_prefix or (
            locator is not None and locator.startswith(f"{source_prefix}::")
        ):
            observations[name] = replace(
                observation,
                source_sha256=source_sha256,
            )


def _decode(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return ""
        return "\n".join(_decode(item) for item in value.flat)
    return str(value).rstrip("\x00")


def _optional_bool(value: Any, *, label: str) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in {0, 1}:
        return bool(value)
    text = _decode(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"Unrecognized boolean metadata for {label}: {text!r}")


def _normalize_version(value: Optional[str]) -> Optional[str]:
    return normalize_program_version(value)


def _major_version(value: Optional[str]) -> Optional[int]:
    normalized = _normalize_version(value)
    if normalized is None:
        return None
    return int(normalized.split(".", 1)[0])


def _message_program_version(messages: str) -> Optional[str]:
    patterns = (
        r"(?:HEC-RAS|Simulation Version)\s+"
        r"(\d+\.\d+(?:\.\d+)?)",
        r"(?:Unsteady|Steady) Flow Simulation Version\s+"
        r"(\d+\.\d+(?:\.\d+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, messages, flags=re.IGNORECASE)
        if match is not None:
            return match.group(1)
    return None


def _parse_plan_datetime(date_text: str, time_text: str) -> Optional[datetime]:
    try:
        parsed = datetime.strptime(date_text.strip().title(), "%d%b%Y")
    except ValueError:
        return None
    normalized_time = time_text.strip().replace(":", "")
    if not re.fullmatch(r"\d{4}", normalized_time):
        return None
    hours = int(normalized_time[:2])
    minutes = int(normalized_time[2:])
    if hours == 24 and minutes == 0:
        return parsed + timedelta(days=1)
    if hours > 23 or minutes > 59:
        return None
    return parsed.replace(hour=hours, minute=minutes)


def _plan_window(value: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    if value is None or pd.isna(value):
        return None, None
    parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 4:
        return None, None
    return (
        _parse_plan_datetime(parts[0], parts[1]),
        _parse_plan_datetime(parts[2], parts[3]),
    )


def _parse_hdf_datetime(value: Any) -> datetime:
    return HdfUtils.parse_ras_datetime(_decode(value).strip())


def _hdf_window(plan_info: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    start_raw = plan_info.attrs.get("Simulation Start Time")
    end_raw = plan_info.attrs.get("Simulation End Time")
    if start_raw is not None and end_raw is not None:
        return _parse_hdf_datetime(start_raw), _parse_hdf_datetime(end_raw)
    time_window = plan_info.attrs.get("Time Window")
    if time_window is None:
        return None, None
    parts = re.split(r"\s+to\s+", _decode(time_window).strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Time Window does not contain a start and end")
    return (
        HdfUtils.parse_ras_datetime(parts[0].strip()),
        HdfUtils.parse_ras_datetime(parts[1].strip()),
    )


def _structured_runtime_seconds(hdf_file: h5py.File) -> Optional[float]:
    processes = hdf_file.get(_COMPUTE_PROCESSES_PATH)
    if processes is None:
        return None
    values: Any = None
    if isinstance(processes, h5py.Group):
        dataset = processes.get("Compute Time (ms)")
        if dataset is not None:
            values = dataset[:]
    elif processes.dtype.names and "Compute Time (ms)" in processes.dtype.names:
        values = processes["Compute Time (ms)"]
    if values is None:
        return None
    numeric = np.asarray(values, dtype=float)
    if numeric.size == 0:
        return None
    if not np.all(np.isfinite(numeric)) or np.any(numeric < 0):
        raise ValueError("Compute Processes contains invalid compute times")
    return float(numeric.sum() / 1000.0)


def _observed_hdf_version(hdf_file: h5py.File) -> Optional[str]:
    candidates = (
        ("", "File Version"),
        ("Results/Unsteady", "Program Version"),
        ("", "Program Version"),
        (_PLAN_INFORMATION_PATH, "Program Version"),
    )
    for group_path, attribute in candidates:
        group = hdf_file if not group_path else hdf_file.get(group_path)
        if group is None:
            continue
        raw = group.attrs.get(attribute)
        if raw is not None and _decode(raw).strip():
            return _decode(raw).strip()
    return None


def _default_observations(
    inspected_at: datetime,
) -> dict[str, EvidenceObservation[Any]]:
    channels: Mapping[str, EvidenceChannel] = {
        "result_artifact_exists": "filesystem",
        "result_artifact_modified_at": "filesystem",
        "result_artifact_modified_after_threshold": "filesystem",
        "result_artifact_structural_state": "hdf",
        "producer_program_version": "hdf",
        "completion_attribute": "hdf",
        "completion_message_hdf": "hdf",
        "completion_message_stored": "stored_message",
        "message_error_count": "stored_message",
        "message_warning_count": "stored_message",
        "message_first_error": "stored_message",
        "runtime_seconds": "stored_message",
        "simulation_start": "filesystem",
        "simulation_end": "filesystem",
        "process_success": "process",
        "com_completion": "com",
    }
    return {
        name: _observation(
            inspected_at,
            state="not_inspected",
            channel=channels[name],
            reason_code="not_inspected",
        )
        for name in EXECUTION_OBSERVATION_NAMES
    }


def _derive_mechanical_completion(
    inspected_at: datetime,
    observations: Mapping[str, EvidenceObservation[Any]],
    *,
    selected_format: Optional[Literal["hdf", "legacy"]],
) -> tuple[EvidenceObservation[bool], tuple[str, ...]]:
    if selected_format == "hdf":
        sources = (
            observations["completion_attribute"],
            observations["completion_message_hdf"],
            observations["completion_message_stored"],
        )
    elif selected_format == "legacy":
        sources = (observations["completion_message_stored"],)
    else:
        sources = ()
    failed = [source for source in sources if source.state == "failed"]
    values = [
        bool(source.value)
        for source in sources
        if source.state == "available"
    ]
    if True in values and False in values:
        return (
            _observation(
                inspected_at,
                state="failed",
                channel="derived",
                reason_code="conflicting_evidence",
                detail="Authoritative completion sources disagree",
            ),
            ("completion_sources_disagree",),
        )
    if failed:
        return (
            _observation(
                inspected_at,
                state="failed",
                channel="derived",
                reason_code="completion_inspection_failed",
                detail="At least one authoritative completion source failed inspection",
            ),
            (),
        )
    if values:
        return (
            _observation(
                inspected_at,
                state="available",
                channel="derived",
                value=values[0],
                reason_code="derived_from_completion_sources",
            ),
            (),
        )
    return (
        _observation(
            inspected_at,
            state="not_inspected",
            channel="derived",
            reason_code="no_usable_completion_evidence",
        ),
        (),
    )


def inspect_execution_evidence(
    plan_number: Union[str, Number, Path],
    *,
    ras_object: Optional[RasPrj] = None,
    result_modified_after: Optional[datetime] = None,
    hash_files: bool = False,
) -> ExecutionEvidence:
    """Inspect existing plan-result evidence without running HEC-RAS or COM."""
    ras_obj = ras_object if ras_object is not None else ras
    ras_obj.check_initialized()
    if not isinstance(hash_files, bool):
        raise TypeError("hash_files must be True or False")
    if result_modified_after is not None and not isinstance(
        result_modified_after, datetime
    ):
        raise TypeError("result_modified_after must be a datetime or None")
    if (
        result_modified_after is not None
        and result_modified_after.tzinfo is None
    ):
        raise ValueError("result_modified_after must be timezone-aware")

    plan_selector: Union[str, Path]
    if isinstance(plan_number, Number):
        plan_selector = RasUtils.normalize_ras_number(plan_number)
    else:
        plan_selector = plan_number
    plan_path = RasUtils.get_plan_path(plan_selector, ras_obj)
    suffix_match = re.search(r"\.p(\d{2})$", plan_path.name, re.IGNORECASE)
    if suffix_match is None:
        raise ValueError(f"Plan file does not end in .p##: {plan_path}")
    normalized_plan = suffix_match.group(1)
    project_file = Path(ras_obj.prj_file)
    expected_plan = (
        Path(ras_obj.project_folder)
        / f"{ras_obj.project_name}.p{normalized_plan}"
    )
    if plan_path.resolve() != expected_plan.resolve():
        raise ValueError(
            "The plan path does not belong to the supplied RasPrj: "
            f"{plan_path}"
        )

    rows = ras_obj.plan_df[
        ras_obj.plan_df["plan_number"].map(RasUtils.normalize_ras_number)
        == normalized_plan
    ]
    if rows.empty:
        raise ValueError(f"Plan {normalized_plan!r} is not present in plan_df")
    plan_row = rows.iloc[0]

    inspected_at = datetime.now(timezone.utc)
    observations = _default_observations(inspected_at)
    conflicts: list[str] = []

    resolution = resolve_plan_result_artifact(
        normalized_plan,
        ras_object=ras_obj,
    )
    declared_version = resolution.declared_program_version
    declared_major = _major_version(declared_version)
    hdf_path = resolution.paths.hdf
    legacy_path = resolution.paths.legacy_output
    result_path = resolution.selected_path
    result_exists = resolution.selected_exists
    conflicts.extend(resolution.conflicts)
    result_hash: Optional[str] = None
    hash_detail: Optional[str] = resolution.detail
    if result_exists and hash_files and result_path != hdf_path:
        assert result_path is not None
        try:
            result_hash = _stable_sha256(result_path)
        except Exception as exc:
            hash_detail = f"Requested result hash failed: {exc}"

    observations["result_artifact_exists"] = _observation(
        inspected_at,
        state="available",
        channel="filesystem",
        value=result_exists,
        source_locator=(str(result_path) if result_path else None),
        source_sha256=result_hash,
        reason_code="filesystem_path_inspected",
        detail=hash_detail,
    )
    if result_exists:
        assert result_path is not None
        result_mtime = datetime.fromtimestamp(
            result_path.stat().st_mtime, timezone.utc
        )
        observations["result_artifact_modified_at"] = _observation(
            inspected_at,
            state="available",
            channel="filesystem",
            value=result_mtime,
            source_locator=(str(result_path) if result_path else None),
            source_sha256=result_hash,
            reason_code="filesystem_metadata_inspected",
        )
        if result_modified_after is None:
            observations[
                "result_artifact_modified_after_threshold"
            ] = _observation(
                inspected_at,
                state="not_inspected",
                channel="filesystem",
                source_locator=(str(result_path) if result_path else None),
                source_sha256=result_hash,
                reason_code="threshold_not_requested",
            )
        else:
            threshold_epoch = result_modified_after.timestamp()
            observations[
                "result_artifact_modified_after_threshold"
            ] = _observation(
                inspected_at,
                state="available",
                channel="filesystem",
                value=result_path.stat().st_mtime >= threshold_epoch,
                source_locator=str(result_path),
                source_sha256=result_hash,
                reason_code="filesystem_threshold_compared",
            )
    else:
        observations["result_artifact_modified_at"] = _observation(
            inspected_at,
            state="not_inspected",
            channel="filesystem",
            source_locator=(str(result_path) if result_path else None),
            reason_code="result_artifact_missing",
        )
        observations[
            "result_artifact_modified_after_threshold"
        ] = _observation(
            inspected_at,
            state="not_inspected",
            channel="filesystem",
            source_locator=(str(result_path) if result_path else None),
            reason_code="result_artifact_missing",
        )

    hdf_message: Optional[str] = None
    hdf_message_locator = f"{hdf_path}::{_HDF_MESSAGE_PATH}"
    observed_hdf_version: Optional[str] = None
    structured_runtime: Optional[float] = None
    structured_runtime_error: Optional[str] = None
    hdf_start: Optional[datetime] = None
    hdf_end: Optional[datetime] = None
    hdf_window_error: Optional[str] = None
    hdf_stable = False

    if resolution.selected_format == "legacy":
        observations["result_artifact_structural_state"] = _observation(
            inspected_at,
            state="not_available_in_version",
            channel="legacy_output",
            source_locator=str(legacy_path),
            source_sha256=result_hash,
            observed_program_version=declared_version,
            reason_code="legacy_output_has_no_plan_hdf_structure",
        )
        # A physically present, nonselected HDF was deliberately not opened;
        # describing it as unavailable would erase that distinction.
        hdf_state: EvidenceState = (
            "not_inspected"
            if hdf_path.is_file()
            else (
                "not_available_in_version"
                if declared_major is not None and declared_major < 5
                else "not_inspected"
            )
        )
        hdf_reason = (
            "plan_hdf_not_available_before_ras_5"
            if hdf_state == "not_available_in_version"
            else "nonselected_result_format_not_inspected"
        )
        for name in ("completion_attribute", "completion_message_hdf"):
            observations[name] = _observation(
                inspected_at,
                state=hdf_state,
                channel="hdf",
                source_locator=str(hdf_path),
                observed_program_version=declared_version,
                reason_code=hdf_reason,
            )
    elif not hdf_path.is_file():
        for name in (
            "result_artifact_structural_state",
            "producer_program_version",
            "completion_attribute",
            "completion_message_hdf",
        ):
            observations[name] = _observation(
                inspected_at,
                state="not_inspected",
                channel="hdf",
                source_locator=str(hdf_path),
                reason_code="result_hdf_missing",
            )
    else:
        before_hdf = hdf_path.stat()
        try:
            with h5py.File(hdf_path, "r") as hdf_file:
                observed_hdf_version = _observed_hdf_version(hdf_file)
                structural = (
                    "plan_information_present"
                    if hdf_file.get(_PLAN_INFORMATION_PATH) is not None
                    else "plan_information_absent"
                )
                observations["result_artifact_structural_state"] = _observation(
                    inspected_at,
                    state="available",
                    channel="hdf",
                    value=structural,
                    source_locator=str(hdf_path),
                    source_sha256=result_hash,
                    observed_program_version=observed_hdf_version,
                    reason_code="plan_information_group_inspected",
                )
                if observed_hdf_version:
                    observations["producer_program_version"] = _observation(
                        inspected_at,
                        state="available",
                        channel="hdf",
                        value=observed_hdf_version,
                        source_locator=str(hdf_path),
                        source_sha256=result_hash,
                        observed_program_version=observed_hdf_version,
                        reason_code="hdf_version_observed",
                    )
                else:
                    observations["producer_program_version"] = _observation(
                        inspected_at,
                        state="not_inspected",
                        channel="hdf",
                        source_locator=str(hdf_path),
                        source_sha256=result_hash,
                        reason_code="producer_version_not_present",
                    )

                event = hdf_file.get("Event Conditions")
                raw_completed = (
                    None
                    if event is None
                    else event.attrs.get("Completed Successfully")
                )
                capability_version = _normalize_version(
                    observed_hdf_version or declared_version
                )
                if raw_completed is None:
                    if capability_version in _COMPLETION_ATTRIBUTE_UNAVAILABLE:
                        attr_state: EvidenceState = "not_available_in_version"
                        attr_reason = "completion_attribute_not_in_version"
                    else:
                        attr_state = "not_inspected"
                        attr_reason = "version_shape_not_established"
                    observations["completion_attribute"] = _observation(
                        inspected_at,
                        state=attr_state,
                        channel="hdf",
                        source_locator=(
                            f"{hdf_path}::Event Conditions/"
                            "@Completed Successfully"
                        ),
                        source_sha256=result_hash,
                        observed_program_version=observed_hdf_version,
                        reason_code=attr_reason,
                    )
                else:
                    try:
                        parsed_completed = _optional_bool(
                            raw_completed,
                            label="Event Conditions/Completed Successfully",
                        )
                    except ValueError as exc:
                        observations["completion_attribute"] = _observation(
                            inspected_at,
                            state="failed",
                            channel="hdf",
                            source_locator=(
                                f"{hdf_path}::Event Conditions/"
                                "@Completed Successfully"
                            ),
                            source_sha256=result_hash,
                            observed_program_version=observed_hdf_version,
                            reason_code="completion_attribute_malformed",
                            detail=str(exc),
                        )
                    else:
                        observations["completion_attribute"] = _observation(
                            inspected_at,
                            state="available",
                            channel="hdf",
                            value=parsed_completed,
                            source_locator=(
                                f"{hdf_path}::Event Conditions/"
                                "@Completed Successfully"
                            ),
                            source_sha256=result_hash,
                            observed_program_version=observed_hdf_version,
                            reason_code="completion_attribute_inspected",
                        )

                message_dataset = hdf_file.get(_HDF_MESSAGE_PATH)
                if message_dataset is None:
                    observations["completion_message_hdf"] = _observation(
                        inspected_at,
                        state="not_inspected",
                        channel="hdf",
                        source_locator=hdf_message_locator,
                        source_sha256=result_hash,
                        observed_program_version=observed_hdf_version,
                        reason_code="hdf_message_dataset_absent",
                    )
                else:
                    hdf_message = _decode(message_dataset[()])
                    if ResultsParser._has_complete_process_record(hdf_message):
                        observations["completion_message_hdf"] = _observation(
                            inspected_at,
                            state="available",
                            channel="hdf",
                            value=True,
                            source_locator=hdf_message_locator,
                            source_sha256=result_hash,
                            observed_program_version=observed_hdf_version,
                            reason_code="completion_marker_observed",
                        )
                    else:
                        observations["completion_message_hdf"] = _observation(
                            inspected_at,
                            state="not_inspected",
                            channel="hdf",
                            source_locator=hdf_message_locator,
                            source_sha256=result_hash,
                            observed_program_version=observed_hdf_version,
                            reason_code="completion_marker_absent",
                        )

                try:
                    structured_runtime = _structured_runtime_seconds(hdf_file)
                except ValueError as exc:
                    structured_runtime_error = str(exc)
                plan_info = hdf_file.get(_PLAN_INFORMATION_PATH)
                if plan_info is not None:
                    try:
                        hdf_start, hdf_end = _hdf_window(plan_info)
                    except Exception as exc:
                        hdf_window_error = str(exc)
            if hash_files:
                result_hash = _stable_sha256(hdf_path)
            after_hdf = hdf_path.stat()
            hdf_stable = (
                before_hdf.st_size,
                before_hdf.st_mtime_ns,
            ) == (
                after_hdf.st_size,
                after_hdf.st_mtime_ns,
            )
            if not hdf_stable:
                raise RuntimeError("Result HDF changed during inspection")
            if result_hash is not None:
                _attach_source_sha256(
                    observations,
                    hdf_path,
                    result_hash,
                )
        except Exception as exc:
            hdf_stable = False
            detail = str(exc)[:1000]
            # A digest produced anywhere in a failed outer stability window
            # is not trustworthy provenance for the observations just read.
            result_hash = None
            if hash_files:
                result_observation = observations["result_artifact_exists"]
                observations["result_artifact_exists"] = replace(
                    result_observation,
                    detail=(
                        "Requested result hash unavailable because HDF "
                        f"inspection or hashing failed: {detail}"
                    )[:1000],
                )
            for name in (
                "result_artifact_structural_state",
                "producer_program_version",
                "completion_attribute",
                "completion_message_hdf",
            ):
                observations[name] = _observation(
                    inspected_at,
                    state="failed",
                    channel="hdf",
                    source_locator=str(hdf_path),
                    source_sha256=result_hash,
                    observed_program_version=observed_hdf_version,
                    reason_code="hdf_inspection_failed",
                    detail=detail,
                )
            hdf_message = None
            structured_runtime = None
            structured_runtime_error = detail
            hdf_start = None
            hdf_end = None

    stored_message: Optional[str] = None
    stored_path: Optional[Path] = None
    stored_hash: Optional[str] = None
    stored_version: Optional[str] = None
    try:
        # Keep the command-line compute surface import-safe without loading the
        # optional COM implementation. Offline inspection imports RasControl
        # only when stored Controller messages are actually inspected.
        from .RasControl import RasControl

        stored = RasControl._read_stored_comp_msgs(
            normalized_plan,
            ras_object=ras_obj,
            hash_file=hash_files,
        )
        if stored is None:
            observations["completion_message_stored"] = _observation(
                inspected_at,
                state="not_inspected",
                channel="stored_message",
                reason_code="stored_message_missing",
            )
        else:
            stored_message, stored_path, stored_hash = stored
            stored_version = _message_program_version(stored_message)
            if ResultsParser._has_complete_process_record(stored_message):
                observations["completion_message_stored"] = _observation(
                    inspected_at,
                    state="available",
                    channel="stored_message",
                    value=True,
                    source_locator=str(stored_path),
                    source_sha256=stored_hash,
                    observed_program_version=stored_version,
                    reason_code="completion_marker_observed",
                )
            else:
                observations["completion_message_stored"] = _observation(
                    inspected_at,
                    state="not_inspected",
                    channel="stored_message",
                    source_locator=str(stored_path),
                    source_sha256=stored_hash,
                    observed_program_version=stored_version,
                    reason_code="completion_marker_absent",
                )
    except Exception as exc:
        observations["completion_message_stored"] = _observation(
            inspected_at,
            state="failed",
            channel="stored_message",
            source_locator=None if stored_path is None else str(stored_path),
            reason_code="stored_message_inspection_failed",
            detail=str(exc)[:1000],
        )

    producer_observation = observations["producer_program_version"]
    if producer_observation.state != "available" and stored_version:
        observations["producer_program_version"] = _observation(
            inspected_at,
            state="available",
            channel="stored_message",
            value=stored_version,
            source_locator=None if stored_path is None else str(stored_path),
            source_sha256=stored_hash,
            observed_program_version=stored_version,
            reason_code="stored_message_version_observed",
        )
    elif producer_observation.state == "available" and stored_version:
        hdf_normalized = _normalize_version(str(producer_observation.value))
        stored_normalized = _normalize_version(stored_version)
        if (
            hdf_normalized is not None
            and stored_normalized is not None
            and hdf_normalized != stored_normalized
        ):
            conflicts.append("producer_version_sources_disagree")

    selected_message: Optional[str] = None
    selected_channel: EvidenceChannel = "stored_message"
    selected_locator: Optional[str] = None
    selected_hash: Optional[str] = None
    selected_version: Optional[str] = None
    if hdf_message is not None and hdf_message.strip() and hdf_stable:
        selected_message = hdf_message
        selected_channel = "hdf"
        selected_locator = hdf_message_locator
        selected_hash = result_hash
        selected_version = observed_hdf_version
    elif stored_message is not None and stored_message.strip():
        selected_message = stored_message
        selected_channel = "stored_message"
        selected_locator = None if stored_path is None else str(stored_path)
        selected_hash = stored_hash
        selected_version = stored_version

    if selected_message is not None:
        parsed = ResultsParser.parse_compute_messages(selected_message)
        observations["message_error_count"] = _observation(
            inspected_at,
            state="available",
            channel=selected_channel,
            value=int(parsed["error_count"]),
            source_locator=selected_locator,
            source_sha256=selected_hash,
            observed_program_version=selected_version,
            reason_code="compute_messages_parsed",
        )
        observations["message_warning_count"] = _observation(
            inspected_at,
            state="available",
            channel=selected_channel,
            value=int(parsed["warning_count"]),
            source_locator=selected_locator,
            source_sha256=selected_hash,
            observed_program_version=selected_version,
            reason_code="compute_messages_parsed",
        )
        observations["message_first_error"] = _observation(
            inspected_at,
            state="available",
            channel=selected_channel,
            value=parsed["first_error_line"] or "",
            source_locator=selected_locator,
            source_sha256=selected_hash,
            observed_program_version=selected_version,
            reason_code="compute_messages_parsed",
        )
    else:
        for name in (
            "message_error_count",
            "message_warning_count",
            "message_first_error",
        ):
            observations[name] = _observation(
                inspected_at,
                state="not_inspected",
                channel="stored_message",
                reason_code="compute_messages_unavailable",
            )

    if (
        resolution.selected_format == "hdf"
        and structured_runtime is not None
        and hdf_stable
    ):
        observations["runtime_seconds"] = _observation(
            inspected_at,
            state="available",
            channel="hdf",
            value=float(structured_runtime),
            source_locator=f"{hdf_path}::{_COMPUTE_PROCESSES_PATH}",
            source_sha256=result_hash,
            observed_program_version=observed_hdf_version,
            reason_code="structured_runtime_summed",
        )
    elif selected_message is not None:
        fallback_runtime = ResultsParser.parse_compute_messages_runtime(
            selected_message
        )["runtime_complete_process_seconds"]
        if fallback_runtime is not None:
            observations["runtime_seconds"] = _observation(
                inspected_at,
                state="available",
                channel=selected_channel,
                value=float(fallback_runtime),
                source_locator=selected_locator,
                source_sha256=selected_hash,
                observed_program_version=selected_version,
                reason_code="message_runtime_parsed",
                detail=(
                    None
                    if structured_runtime_error is None
                    else f"Structured runtime unavailable: {structured_runtime_error}"
                ),
            )
        else:
            observations["runtime_seconds"] = _observation(
                inspected_at,
                state="not_inspected",
                channel=selected_channel,
                source_locator=selected_locator,
                source_sha256=selected_hash,
                observed_program_version=selected_version,
                reason_code="runtime_not_present",
                detail=structured_runtime_error,
            )
    else:
        observations["runtime_seconds"] = _observation(
            inspected_at,
            state="not_inspected",
            channel="stored_message",
            reason_code="runtime_source_unavailable",
        )

    plan_start, plan_end = _plan_window(plan_row.get("Simulation Date"))
    if (
        resolution.selected_format == "hdf"
        and hdf_start is not None
        and hdf_end is not None
        and hdf_stable
    ):
        window_channel: EvidenceChannel = "hdf"
        window_locator = f"{hdf_path}::{_PLAN_INFORMATION_PATH}"
        window_hash = result_hash
        window_version = observed_hdf_version
        window_start, window_end = hdf_start, hdf_end
        window_reason = "hdf_simulation_window_inspected"
        window_detail = None
    elif plan_start is not None and plan_end is not None:
        window_channel = "filesystem"
        window_locator = str(plan_path)
        # The plan window comes from the already-initialized plan dataframe,
        # not from bytes read during this inspection. Do not attach a digest
        # that could falsely imply those cached values came from that exact
        # byte snapshot.
        window_hash = None
        window_version = declared_version
        window_start, window_end = plan_start, plan_end
        window_reason = "declared_plan_window_inspected"
        window_detail = (
            None
            if hdf_window_error is None
            else f"HDF window unavailable: {hdf_window_error}"[:1000]
        )
    else:
        window_channel = "filesystem"
        window_locator = str(plan_path)
        window_hash = None
        window_version = declared_version
        window_start = window_end = None
        window_reason = "simulation_window_unavailable"
        window_detail = hdf_window_error

    for name, value in (
        ("simulation_start", window_start),
        ("simulation_end", window_end),
    ):
        if value is None:
            observations[name] = _observation(
                inspected_at,
                state="not_inspected",
                channel=window_channel,
                source_locator=window_locator,
                source_sha256=window_hash,
                observed_program_version=window_version,
                reason_code=window_reason,
                detail=window_detail,
            )
        else:
            observations[name] = _observation(
                inspected_at,
                state="available",
                channel=window_channel,
                value=value,
                source_locator=window_locator,
                source_sha256=window_hash,
                observed_program_version=window_version,
                reason_code=window_reason,
                detail=window_detail,
            )

    observations["process_success"] = _observation(
        inspected_at,
        state="not_inspected",
        channel="process",
        reason_code="offline_inspection_has_no_process_context",
    )
    observations["com_completion"] = _observation(
        inspected_at,
        state="not_inspected",
        channel="com",
        reason_code="com_not_opened_by_offline_inspection",
    )

    mechanical, derived_conflicts = _derive_mechanical_completion(
        inspected_at,
        observations,
        selected_format=resolution.selected_format,
    )
    conflicts.extend(derived_conflicts)
    unique_conflicts = tuple(dict.fromkeys(conflicts))
    logger.info(
        "Inspected execution evidence for plan %s read-only: completion=%s, "
        "conflicts=%s",
        normalized_plan,
        mechanical.state
        if mechanical.state != "available"
        else mechanical.value,
        len(unique_conflicts),
    )
    return ExecutionEvidence(
        schema_version=1,
        evidence_id=str(uuid.uuid4()),
        inspected_at=inspected_at,
        project_file=project_file,
        plan_file=plan_path,
        plan_number=normalized_plan,
        declared_program_version=declared_version,
        mechanical_completion=mechanical,
        observations=observations,
        conflicts=unique_conflicts,
    )


__all__ = [
    "EvidenceState",
    "EvidenceChannel",
    "ObservationName",
    "EVIDENCE_STATES",
    "EVIDENCE_CHANNELS",
    "EXECUTION_OBSERVATION_NAMES",
    "EvidenceObservation",
    "ExecutionEvidence",
]
