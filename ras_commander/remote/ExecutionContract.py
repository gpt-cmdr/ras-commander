"""Portable contracts for one-project, one-core HEC-RAS execution.

The request is deliberately scheduler-neutral.  Paths are relative to the
directory containing the request JSON so the same bundle can run locally,
through Docker, or from a Slurm allocation without rewriting model identity.

An optional ``stored_maps`` block asks the executor to generate RASMapper
steady-profile stored maps after hydraulic validation passes. The block carries
its own schema (``ras-commander-stored-maps-request/v1``). When it is absent,
requests and receipts serialize exactly as the original v1 contract, so
existing request digests and receipts remain valid. Executors that predate the
block reject it as an unknown request field.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Optional, Union

from ..Decorators import log_call
from ..RasUtils import RasUtils

REQUEST_SCHEMA = "ras-commander-execution-request/v1"
RECEIPT_SCHEMA = "ras-commander-execution-receipt/v1"
STORED_MAPS_SCHEMA = "ras-commander-stored-maps-request/v1"
STORED_MAPS_OUTPUT_DIRECTORY = "maps"
STORED_MAPS_STATUSES = frozenset({"passed", "failed", "skipped"})
# Profile-dependent products accepted by
# RasProcess.store_maps_at_steady_profiles(map_types=...).
STEADY_STORED_MAP_TYPES = frozenset(
    {
        "wse",
        "depth",
        "velocity",
        "froude",
        "shear_stress",
        "depth_x_velocity",
        "depth_x_velocity_sq",
        "flow",
    }
)
_STORED_MAPS_RECEIPT_FIELDS = frozenset(
    {
        "requested",
        "status",
        "reason_code",
        "elapsed_seconds",
        "output_directory",
        "products",
        "error",
    }
)
_STORED_MAP_PRODUCT_FIELDS = frozenset(
    {"profile_index", "profile_name", "map_type", "primary_path", "file_count"}
)
_DEFAULTABLE_REQUEST_FIELDS = frozenset(
    {
        "preprocess_policy",
        "timeout_seconds",
        "flow_tolerance_absolute",
        "flow_tolerance_relative",
        "num_cores",
        "schema",
        "stored_maps",
    }
)
_EXECUTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CONTAINER_IDENTITY = re.compile(
    r"(?:sif:sha256:[0-9a-f]{64}|[A-Za-z0-9._-]+(?::[0-9]+)?"
    r"(?:/[A-Za-z0-9._-]+)+@sha256:[0-9a-f]{64})\Z"
)
_RUNTIME_CONTAINER_IDENTITY = _CONTAINER_IDENTITY
_POSIX_RAS_EXECUTABLE = re.compile(r"/[A-Za-z0-9._+/-]+\.exe\Z", re.IGNORECASE)
_WINDOWS_RAS_SEGMENT = r"[A-Za-z0-9_()+-](?:[A-Za-z0-9 ._()+-]*[A-Za-z0-9_()+-])?"
_WINDOWS_RAS_EXECUTABLE = re.compile(
    rf"[A-Za-z]:\\{_WINDOWS_RAS_SEGMENT}(?:\\{_WINDOWS_RAS_SEGMENT})*\.exe\Z",
    re.IGNORECASE,
)


def _is_conservative_ras_executable(value: str) -> bool:
    """Return whether *value* is an absolute trusted-container executable path."""
    if _POSIX_RAS_EXECUTABLE.fullmatch(value):
        return True
    if not _WINDOWS_RAS_EXECUTABLE.fullmatch(value):
        return False
    path = PureWindowsPath(value)
    return path.is_absolute() and ".." not in path.parts


class PreprocessPolicy(str, Enum):
    """Geometry-preprocessing behavior for a prepared project clone."""

    REUSE = "reuse"
    REBUILD = "rebuild"
    FORCE_REBUILD = "force-rebuild"


def sha256_file(path: Union[str, Path]) -> str:
    """Return the SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(folder: Union[str, Path]) -> str:
    """Hash a project tree, including relative names and file contents."""
    tree_digest, _ = _sha256_tree_with_file(folder)
    return tree_digest


def _sha256_tree_with_file(
    folder: Union[str, Path], selected_file: Optional[Union[str, Path]] = None
) -> tuple[str, Optional[str]]:
    """Hash a tree and, in the same read pass, optionally hash one member."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError(f"Project folder does not exist: {root}")
    digest = hashlib.sha256()
    selected = Path(selected_file).resolve() if selected_file is not None else None
    selected_digest = hashlib.sha256() if selected is not None else None
    selected_seen = False
    links = [item for item in root.rglob("*") if item.is_symlink()]
    if links:
        raise ValueError(f"Project trees cannot contain symbolic links: {links[0]}")
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        is_selected = selected is not None and path.resolve() == selected
        if is_selected:
            selected_seen = True
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                if selected_digest is not None and is_selected:
                    selected_digest.update(block)
        digest.update(b"\0")
    if selected is not None and not selected_seen:
        raise ValueError(f"Selected file is not a regular member of project tree: {selected}")
    return digest.hexdigest(), (
        selected_digest.hexdigest() if selected_digest is not None else None
    )


def _relative_bundle_path(value: Union[str, Path], field_name: str) -> str:
    text = Path(value).as_posix()
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"{field_name} must be a non-empty bundle-relative path without '..'"
        )
    if any(character in text for character in (",", ":")):
        raise ValueError(
            f"{field_name} cannot contain Docker/Apptainer mount delimiters ',' or ':'"
        )
    return text


def _single_line(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(character in value for character in ("\n", "\r", "\x00"))
    )


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _relative_product_path(value: Any) -> str:
    """Validate a receipt product path relative to the request output root."""
    if not _single_line(value) or "\\" in value or ":" in value:
        raise ValueError("Stored-map product path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or PureWindowsPath(value).drive:
        raise ValueError("Stored-map product path must stay inside the output directory")
    return value


@dataclass(frozen=True)
class StoredMapsRequest:
    """Optional steady-profile stored-map products for one execution request.

    Maps are generated by
    :meth:`ras_commander.RasProcess.store_maps_at_steady_profiles` on the
    isolated runtime copy, only after the steady results pass hydraulic
    validation, into ``<output_directory>/maps``.

    Attributes:
        terrain_name: Registered RASMapper terrain layer to map against.
        profiles: ``None`` for every steady profile, or exact profile names
            and zero-based profile indexes in the order to generate.
        map_types: Profile-dependent products; defaults to ``("depth",)``.
        inundation_boundary: Also generate one boundary polygon for the final
            selected profile. Defaults to ``False``.
        timeout_seconds: Aggregate StoreAllMaps helper timeout.
        mode: Only ``"steady_profiles"`` is supported.
        schema: ``ras-commander-stored-maps-request/v1``.
    """

    terrain_name: str
    profiles: Optional[tuple[Union[str, int], ...]] = None
    map_types: tuple[str, ...] = ("depth",)
    inundation_boundary: bool = False
    timeout_seconds: int = 1800
    mode: str = "steady_profiles"
    schema: str = STORED_MAPS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != STORED_MAPS_SCHEMA:
            raise ValueError(f"Unsupported stored_maps schema: {self.schema}")
        if self.mode != "steady_profiles":
            raise ValueError("stored_maps mode must be 'steady_profiles'")
        if not _single_line(self.terrain_name):
            raise ValueError("stored_maps terrain_name must be a non-empty single line")
        if self.profiles is not None:
            if isinstance(self.profiles, (str, bytes, Mapping)):
                raise ValueError("stored_maps profiles must be null or a list")
            profiles = tuple(self.profiles)
            if not profiles:
                raise ValueError("stored_maps profiles must be null or non-empty")
            for item in profiles:
                if isinstance(item, bool) or not (
                    (isinstance(item, int) and item >= 0) or _single_line(item)
                ):
                    raise ValueError(
                        "stored_maps profiles must be exact names or "
                        "non-negative zero-based indexes"
                    )
            if len(set(profiles)) != len(profiles):
                raise ValueError("stored_maps profiles contain duplicates")
            object.__setattr__(self, "profiles", profiles)
        if isinstance(self.map_types, (str, bytes, Mapping)):
            raise ValueError("stored_maps map_types must be a list")
        map_types = tuple(self.map_types)
        if not map_types:
            raise ValueError("stored_maps map_types must be non-empty")
        unknown = sorted(
            str(item) for item in map_types if item not in STEADY_STORED_MAP_TYPES
        )
        if unknown:
            raise ValueError(
                "Unsupported stored_maps map_types: " + ", ".join(unknown)
            )
        if len(set(map_types)) != len(map_types):
            raise ValueError("stored_maps map_types contain duplicates")
        object.__setattr__(self, "map_types", map_types)
        if not isinstance(self.inundation_boundary, bool):
            raise ValueError("stored_maps inundation_boundary must be a boolean")
        if not _is_positive_int(self.timeout_seconds):
            raise ValueError("stored_maps timeout_seconds must be a positive integer")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StoredMapsRequest":
        """Validate a ``stored_maps`` mapping, rejecting unknown fields."""
        if not isinstance(payload, Mapping):
            raise ValueError("stored_maps must be an object")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise ValueError(f"stored_maps fields do not match the contract: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible block."""
        return {
            "inundation_boundary": self.inundation_boundary,
            "map_types": list(self.map_types),
            "mode": self.mode,
            "profiles": None if self.profiles is None else list(self.profiles),
            "schema": self.schema,
            "terrain_name": self.terrain_name,
            "timeout_seconds": self.timeout_seconds,
        }


def _require_complete_products(
    requested: StoredMapsRequest, products: Any
) -> None:
    """Require one row for every requested profile/product and nothing extra."""
    keys = [(row["profile_index"], row["map_type"]) for row in products]
    if len(set(keys)) != len(keys):
        raise ValueError("Stored-map products contain duplicate profile/product rows")
    raster_rows = [row for row in products if row["map_type"] != "inundation_boundary"]
    boundary_rows = [row for row in products if row["map_type"] == "inundation_boundary"]
    if len(boundary_rows) != (1 if requested.inundation_boundary else 0):
        raise ValueError("Stored-map inundation boundary rows do not match the request")
    if {row["map_type"] for row in raster_rows} != set(requested.map_types):
        raise ValueError("Stored-map product types do not match the request")
    profile_sets = {
        map_type: {
            (row["profile_index"], row["profile_name"])
            for row in raster_rows
            if row["map_type"] == map_type
        }
        for map_type in requested.map_types
    }
    selected = next(iter(profile_sets.values()))
    if any(profiles != selected for profiles in profile_sets.values()):
        raise ValueError("Stored-map product types cover different profiles")
    if requested.profiles is not None:
        indexes = {index for index, _ in selected}
        names = {name for _, name in selected}
        for selector in requested.profiles:
            if selector not in (indexes if isinstance(selector, int) else names):
                raise ValueError(
                    f"Stored-map products are missing requested profile {selector!r}"
                )
        if len(selected) > len(requested.profiles):
            raise ValueError("Stored-map products include unrequested profiles")


def _validate_stored_maps_receipt(section: Any) -> None:
    """Validate the structure of a receipt ``stored_maps`` section."""
    if not isinstance(section, Mapping) or set(section) != _STORED_MAPS_RECEIPT_FIELDS:
        raise ValueError("Receipt stored_maps fields do not match the contract")
    StoredMapsRequest.from_dict(section["requested"])
    if section["status"] not in STORED_MAPS_STATUSES:
        raise ValueError("Receipt stored_maps status must be passed, failed, or skipped")
    if not _single_line(section["reason_code"]):
        raise ValueError("Receipt stored_maps reason_code is required")
    if section["output_directory"] != STORED_MAPS_OUTPUT_DIRECTORY:
        raise ValueError("Receipt stored_maps output_directory is not canonical")
    elapsed = section["elapsed_seconds"]
    if elapsed is not None and (
        isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0
    ):
        raise ValueError("Receipt stored_maps elapsed_seconds is invalid")
    products = section["products"]
    if not isinstance(products, (list, tuple)):
        raise ValueError("Receipt stored_maps products must be a list")
    for row in products:
        if not isinstance(row, Mapping) or set(row) != _STORED_MAP_PRODUCT_FIELDS:
            raise ValueError("Receipt stored_maps product fields do not match")
        _relative_product_path(row["primary_path"])
        if not (
            isinstance(row["profile_index"], int)
            and not isinstance(row["profile_index"], bool)
            and row["profile_index"] >= 0
            and isinstance(row["profile_name"], str)
            and row["map_type"] in STEADY_STORED_MAP_TYPES | {"inundation_boundary"}
            and _is_positive_int(row["file_count"])
        ):
            raise ValueError("Receipt stored_maps product row is invalid")
    if section["status"] == "passed":
        if not products or section["error"] is not None:
            raise ValueError("Passed stored_maps requires products and no error")
        _require_complete_products(StoredMapsRequest.from_dict(section["requested"]), products)
        if any(
            PurePosixPath(row["primary_path"]).parts[0] != STORED_MAPS_OUTPUT_DIRECTORY
            for row in products
        ):
            raise ValueError("Stored-map products must be under the maps directory")


def _resolve_confined(base: Path, relative: str) -> Path:
    resolved = (base / relative).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Bundle path escapes request directory: {relative}") from exc
    return resolved


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def atomic_write_json(path: Union[str, Path], payload: Mapping[str, Any]) -> Path:
    """Atomically write canonical, human-readable JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


@dataclass(frozen=True)
class RasExecutionRequest:
    """Immutable request for one steady or unsteady plan using one CPU core.

    ``source_project_path`` and ``output_directory`` are relative to the JSON
    request's directory. The request records source identities for one
    pre-execution validation pass. The output directory must be outside that
    source tree.
    """

    execution_id: str
    source_project_path: str
    source_project_sha256: str
    source_tree_sha256: str
    plan_number: str
    output_directory: str
    ras_executable: str
    container_identity: str
    preprocess_policy: str = PreprocessPolicy.REBUILD.value
    timeout_seconds: int = 3600
    flow_tolerance_absolute: float = 0.01
    flow_tolerance_relative: float = 1e-6
    num_cores: int = 1
    schema: str = REQUEST_SCHEMA
    stored_maps: Optional[StoredMapsRequest] = None

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise ValueError(f"Unsupported request schema: {self.schema}")
        if self.stored_maps is not None and not isinstance(
            self.stored_maps, StoredMapsRequest
        ):
            object.__setattr__(
                self, "stored_maps", StoredMapsRequest.from_dict(self.stored_maps)
            )
        if not isinstance(self.execution_id, str) or not _EXECUTION_ID.fullmatch(
            self.execution_id
        ):
            raise ValueError("execution_id must be 1-128 safe identifier characters")
        object.__setattr__(
            self,
            "source_project_path",
            _relative_bundle_path(self.source_project_path, "source_project_path"),
        )
        object.__setattr__(
            self,
            "output_directory",
            _relative_bundle_path(self.output_directory, "output_directory"),
        )
        object.__setattr__(
            self, "plan_number", RasUtils.normalize_ras_number(self.plan_number)
        )
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_project_sha256):
            raise ValueError("source_project_sha256 must be a lowercase SHA-256 digest")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_tree_sha256):
            raise ValueError("source_tree_sha256 must be a lowercase SHA-256 digest")
        if self.num_cores != 1:
            raise ValueError("Portable execution requires num_cores=1")
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")
        if self.flow_tolerance_absolute < 0 or self.flow_tolerance_relative < 0:
            raise ValueError("Flow tolerances must be non-negative")
        try:
            PreprocessPolicy(self.preprocess_policy)
        except ValueError as exc:
            choices = ", ".join(item.value for item in PreprocessPolicy)
            raise ValueError(f"preprocess_policy must be one of: {choices}") from exc
        if not _is_conservative_ras_executable(str(self.ras_executable)):
            raise ValueError(
                "ras_executable must be a conservative absolute POSIX or Windows "
                ".exe path inside the trusted container"
            )
        if not _CONTAINER_IDENTITY.fullmatch(str(self.container_identity)):
            raise ValueError(
                "container_identity must be an immutable "
                "'sif:sha256:<64 hex>' or OCI "
                "'<registry>/<repository>@sha256:<64 hex>' reference"
            )

    @classmethod
    def create(
        cls,
        *,
        execution_id: str,
        request_directory: Union[str, Path],
        source_project_path: Union[str, Path],
        plan_number: Union[str, int],
        output_directory: Union[str, Path],
        ras_executable: str,
        container_identity: str,
        preprocess_policy: Union[str, PreprocessPolicy] = PreprocessPolicy.REBUILD,
        timeout_seconds: int = 3600,
        flow_tolerance_absolute: float = 0.01,
        flow_tolerance_relative: float = 1e-6,
        stored_maps: Optional[Union[StoredMapsRequest, Mapping[str, Any]]] = None,
    ) -> "RasExecutionRequest":
        """Create a request and bind it to the current immutable input tree.

        ``stored_maps`` optionally requests steady-profile stored maps after
        hydraulic validation (see :class:`StoredMapsRequest`). Omitting it
        produces a request identical to the original v1 contract.
        """
        request_root = Path(request_directory).resolve()
        source_relative = _relative_bundle_path(
            source_project_path, "source_project_path"
        )
        output_relative = _relative_bundle_path(output_directory, "output_directory")
        source_project = _resolve_confined(request_root, source_relative)
        if not source_project.is_file() or source_project.suffix.lower() != ".prj":
            raise ValueError(f"source_project_path must identify a .prj file: {source_project}")
        output = _resolve_confined(request_root, output_relative)
        try:
            output.relative_to(source_project.parent.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("output_directory cannot be inside the source project tree")
        policy = (
            preprocess_policy.value
            if isinstance(preprocess_policy, PreprocessPolicy)
            else str(preprocess_policy)
        )
        tree_digest, project_digest = _sha256_tree_with_file(
            source_project.parent, source_project
        )
        return cls(
            execution_id=execution_id,
            source_project_path=source_relative,
            source_project_sha256=str(project_digest),
            source_tree_sha256=tree_digest,
            plan_number=str(plan_number),
            output_directory=output_relative,
            ras_executable=str(ras_executable),
            container_identity=container_identity,
            preprocess_policy=policy,
            timeout_seconds=timeout_seconds,
            flow_tolerance_absolute=flow_tolerance_absolute,
            flow_tolerance_relative=flow_tolerance_relative,
            stored_maps=stored_maps,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RasExecutionRequest":
        """Validate and retain a request mapping, rejecting unknown fields.

        The retained mapping remains the authoritative payload for request
        identity.  Validation may supply dataclass defaults for omitted
        optional fields, but those defaults must not silently change the
        request digest recorded by an execution receipt.
        """
        values = dict(payload)
        if "stored_maps" in values and values["stored_maps"] is None:
            # Absence is the only v1 spelling; null would not round-trip.
            raise ValueError("stored_maps must be omitted rather than null")
        request = cls(**values)
        # Preserve which optional top-level fields the retained request omitted,
        # while emitting every supplied value in its validated wire spelling.
        # This keeps paths, plan numbers, and nested extension objects portable.
        retained_values = request._normalized_dict()
        for field_name in _DEFAULTABLE_REQUEST_FIELDS - values.keys():
            retained_values.pop(field_name, None)
        retained = json.loads(_canonical_json(retained_values).decode("utf-8"))
        object.__setattr__(request, "_retained_payload", retained)
        return request

    @classmethod
    def read(cls, path: Union[str, Path]) -> "RasExecutionRequest":
        """Read and validate a request JSON file."""
        with Path(path).open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("Execution request JSON must contain an object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the retained serializable request.

        ``stored_maps`` is omitted when unset so v1 request bytes and digests
        are unchanged. Requests loaded from JSON also preserve omission of
        other optional fields; use :attr:`specification_sha256` when a
        normalized semantic identity is required.
        """
        retained = getattr(self, "_retained_payload", None)
        if retained is not None:
            return json.loads(_canonical_json(retained).decode("utf-8"))
        return self._normalized_dict()

    def _normalized_dict(self) -> dict[str, Any]:
        """Return every normalized contract field, omitting absent extensions."""
        payload = asdict(self)
        payload["flow_tolerance_absolute"] = float(self.flow_tolerance_absolute)
        payload["flow_tolerance_relative"] = float(self.flow_tolerance_relative)
        if self.stored_maps is None:
            payload.pop("stored_maps")
        else:
            payload["stored_maps"] = self.stored_maps.to_dict()
        return payload

    @property
    def execution_timeout_seconds(self) -> int:
        """Solver timeout plus the stored-map timeout when maps are requested."""
        if self.stored_maps is None:
            return self.timeout_seconds
        return self.timeout_seconds + self.stored_maps.timeout_seconds

    def write(self, path: Union[str, Path]) -> Path:
        """Write the request atomically."""
        return atomic_write_json(path, self.to_dict())

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical retained request payload."""
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    @property
    def payload_sha256(self) -> str:
        """SHA-256 binding the receipt to the retained request payload."""
        return self.digest

    @property
    def specification_sha256(self) -> str:
        """SHA-256 of the normalized semantic execution specification.

        Unlike :attr:`payload_sha256`, this digest is unchanged when a caller
        omits an optional field whose value equals the contract default.  It
        is suitable for cache keys and governed retry comparisons; receipts
        continue to bind the exact retained payload through ``request_sha256``.
        """
        return hashlib.sha256(_canonical_json(self._normalized_dict())).hexdigest()

    @property
    def _legacy_v1_sha256(self) -> str:
        """Return the normalized digest emitted by executors before payload identity."""
        payload = asdict(self)
        if self.stored_maps is None:
            payload.pop("stored_maps")
        else:
            payload["stored_maps"] = self.stored_maps.to_dict()
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    def resolve_paths(self, request_path: Union[str, Path]) -> tuple[Path, Path]:
        """Resolve and confine input/output paths relative to one request file."""
        root = Path(request_path).resolve().parent
        source = _resolve_confined(root, self.source_project_path)
        output = _resolve_confined(root, self.output_directory)
        try:
            output.relative_to(source.parent.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("output_directory cannot be inside the source project tree")
        return source, output


@dataclass(frozen=True)
class RasExecutionReceipt:
    """Durable execution outcome tied to one request and isolated runtime copy."""

    execution_id: str
    request_sha256: str
    container_identity: str
    runtime_container_identity: str
    success: bool
    status: str
    started_at: str
    finished_at: str
    source_tree_sha256_before: str
    source_tree_sha256_after: str
    source_unchanged: bool
    solver_verified: bool
    hydraulic_validated: bool
    result_validation: Mapping[str, Any]
    runtime_project_path: Optional[str] = None
    result_hdf_path: Optional[str] = None
    result_hdf_sha256: Optional[str] = None
    compute_messages_sha256: Optional[str] = None
    compute_messages_length: int = 0
    compute_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    schema: str = RECEIPT_SCHEMA
    stored_maps: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise ValueError(f"Unsupported receipt schema: {self.schema}")
        if self.stored_maps is not None:
            _validate_stored_maps_receipt(self.stored_maps)
            if self.success and self.stored_maps["status"] != "passed":
                raise ValueError("Successful receipt requires passed stored_maps")
            hydraulic_success = bool(self.solver_verified and self.hydraulic_validated)
            if (self.stored_maps["status"] == "skipped") == hydraulic_success:
                raise ValueError(
                    "stored_maps must be skipped exactly when hydraulic validation "
                    "did not pass"
                )
        if not _EXECUTION_ID.fullmatch(self.execution_id):
            raise ValueError("Invalid receipt execution_id")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("Receipt status must be 'succeeded' or 'failed'")
        if self.success != (self.status == "succeeded"):
            raise ValueError("Receipt success and status disagree")
        if not _CONTAINER_IDENTITY.fullmatch(str(self.container_identity)):
            raise ValueError("Receipt source container_identity is not immutable")
        if not _RUNTIME_CONTAINER_IDENTITY.fullmatch(
            str(self.runtime_container_identity)
        ):
            raise ValueError("Receipt runtime_container_identity is not immutable")
        if self.success:
            if not (
                self.solver_verified
                and self.hydraulic_validated
                and self.source_unchanged
                and self.source_tree_sha256_before == self.source_tree_sha256_after
                and self.result_hdf_path
                and self.result_hdf_sha256
                and self.result_validation.get("passed") is True
            ):
                raise ValueError(
                    "Successful receipt requires solver, hydraulic, source, HDF, "
                    "and result-validation evidence"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", str(self.result_hdf_sha256)):
                raise ValueError("Successful receipt result HDF digest is invalid")
            _relative_bundle_path(str(self.result_hdf_path), "result_hdf_path")

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical serializable receipt.

        ``stored_maps`` is omitted when the request did not ask for maps.
        """
        payload = asdict(self)
        if self.stored_maps is None:
            payload.pop("stored_maps")
        return payload

    def write(self, path: Union[str, Path]) -> Path:
        """Write the receipt atomically."""
        return atomic_write_json(path, self.to_dict())

    @classmethod
    def read(cls, path: Union[str, Path]) -> "RasExecutionReceipt":
        """Read and validate a receipt JSON file."""
        with Path(path).open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("Execution receipt JSON must contain an object")
        return cls(**payload)


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@log_call
def validate_execution_receipt(
    request_path: Union[str, Path],
    receipt_path: Union[str, Path],
    *,
    expected_runtime_identity: Optional[str] = None,
    verify_result_hdf_digest: bool = False,
) -> RasExecutionReceipt:
    """Validate receipt identity and output placement.

    Source bytes are not re-read: execution already validated them once before
    copying to its isolated runtime directory.  Result bytes are rehashed only
    when ``verify_result_hdf_digest`` is requested at a real transfer boundary.

    Args:
        request_path (Union[str, Path]): The request JSON the receipt answers.
        receipt_path (Union[str, Path]): Must be the canonical
            ``<output_directory>/execution_receipt.json`` for that request.
        expected_runtime_identity (Optional[str]): Container identity the
            executor is known to have run (for example ``sif:sha256:<digest>``).
        verify_result_hdf_digest (bool): Rehash the result HDF bytes.

    Returns:
        RasExecutionReceipt: The validated receipt.

    Raises:
        ValueError: If the receipt path is not canonical, or its execution ID,
            request digest, container identities, source-tree evidence,
            result HDF placement/digest, or requested stored-map section and
            product files do not match.

    Examples:
        >>> receipt = validate_execution_receipt(  # doctest: +SKIP
        ...     "bundle/request.json", "bundle/results/execution_receipt.json"
        ... )
    """
    request_file = Path(request_path).resolve()
    request = RasExecutionRequest.read(request_file)
    _, output = request.resolve_paths(request_file)
    expected_receipt = output / "execution_receipt.json"
    supplied_receipt = Path(receipt_path)
    if supplied_receipt.is_symlink() or supplied_receipt.resolve() != expected_receipt.resolve():
        raise ValueError("Receipt path is not the canonical output receipt")
    if not supplied_receipt.is_file():
        raise ValueError("Execution receipt is missing or not a regular file")
    receipt = RasExecutionReceipt.read(supplied_receipt)
    if receipt.execution_id != request.execution_id:
        raise ValueError("Receipt execution_id does not match request")
    if receipt.request_sha256 not in {
        request.payload_sha256,
        request.specification_sha256,
        request._legacy_v1_sha256,
    }:
        raise ValueError("Receipt request digest does not match request")
    if receipt.container_identity != request.container_identity:
        raise ValueError("Receipt container identity does not match request")
    if (
        expected_runtime_identity is not None
        and receipt.runtime_container_identity != expected_runtime_identity
    ):
        raise ValueError("Receipt runtime container identity does not match executor")
    if not (
        receipt.source_unchanged
        and receipt.source_tree_sha256_before == request.source_tree_sha256
        and receipt.source_tree_sha256_after == request.source_tree_sha256
    ):
        raise ValueError("Receipt source-tree evidence does not match request")
    if request.stored_maps is None:
        if receipt.stored_maps is not None:
            raise ValueError("Receipt has stored_maps but the request did not ask for maps")
    else:
        if receipt.stored_maps is None:
            raise ValueError("Receipt is missing the requested stored_maps section")
        if dict(receipt.stored_maps["requested"]) != request.stored_maps.to_dict():
            raise ValueError("Receipt stored_maps request does not match request")
        if receipt.stored_maps["status"] == "passed":
            for row in receipt.stored_maps["products"]:
                lexical = output / row["primary_path"]
                product = lexical.resolve()
                try:
                    product.relative_to(output.resolve())
                except ValueError as exc:
                    raise ValueError("Stored-map product escapes output directory") from exc
                if any(
                    item.is_symlink()
                    for item in (lexical, *lexical.parents)
                    if item != output.parent
                ):
                    raise ValueError("Stored-map product path traverses a symbolic link")
                if not product.is_file():
                    raise ValueError(
                        f"Stored-map product is missing: {row['primary_path']}"
                    )
    if bool(receipt.result_hdf_path) != bool(receipt.result_hdf_sha256):
        raise ValueError("Receipt result HDF path and digest must appear together")
    if receipt.result_hdf_path:
        relative = _relative_bundle_path(receipt.result_hdf_path, "result_hdf_path")
        result_hdf = (output / relative).resolve()
        try:
            result_hdf.relative_to(output.resolve())
        except ValueError as exc:
            raise ValueError("Receipt result HDF escapes output directory") from exc
        lexical = output / relative
        if any(
            item.is_symlink()
            for item in (lexical, *lexical.parents)
            if item != output.parent
        ):
            raise ValueError("Receipt result HDF path traverses a symbolic link")
        if not result_hdf.is_file() or result_hdf.stat().st_size <= 0:
            raise ValueError("Receipt result HDF is missing, empty, or not regular")
        if (
            verify_result_hdf_digest
            and sha256_file(result_hdf) != receipt.result_hdf_sha256
        ):
            raise ValueError("Receipt result HDF digest does not match bytes")
    return receipt
