"""HEC-RAS native-Windows and Windows-under-Wine qualification helpers.

The qualification API is intentionally evidence-first.  Process exit codes are
recorded by the runner, but acceptance is based on executable identity and the
content of HEC-RAS project, geometry, result, and raster artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import h5py
import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPrj import get_ras_exe
from .RasUtils import RasUtils


logger = get_logger(__name__)


class ExecutorProfile(str, Enum):
    """Explicit HEC-RAS execution profiles used by qualification receipts."""

    WINDOWS_NATIVE = "windows_native"
    LINUX_WINE_WINDOWS_RAS = "linux_wine_windows_ras"
    LINUX_NATIVE_EXPERIMENTAL = "linux_native_experimental"


@dataclass(frozen=True)
class NumericTolerance:
    """Acceptance limits for a paired numeric result series."""

    max_abs: float
    rmse: float
    peak_relative: Optional[float] = None


@dataclass(frozen=True)
class RasterTolerance:
    """Acceptance limits for paired RAS Mapper rasters."""

    max_abs: float
    rmse: float
    minimum_wet_overlap: float
    wet_threshold: float = 0.0
    resampling: str = "nearest"
    minimum_valid_overlap: float = 1.0

    def __post_init__(self) -> None:
        """Normalize and fail closed on invalid raster acceptance limits."""
        for field_name in (
            "max_abs",
            "rmse",
            "minimum_wet_overlap",
            "wet_threshold",
            "minimum_valid_overlap",
        ):
            try:
                value = float(getattr(self, field_name))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Raster {field_name} must be a finite number") from exc
            if not math.isfinite(value):
                raise ValueError(f"Raster {field_name} must be a finite number")
            object.__setattr__(self, field_name, value)

        if self.max_abs < 0:
            raise ValueError("Raster max_abs must be non-negative")
        if self.rmse < 0:
            raise ValueError("Raster rmse must be non-negative")
        if self.wet_threshold < 0:
            raise ValueError("Raster wet_threshold must be non-negative")
        if not 0 <= self.minimum_wet_overlap <= 1:
            raise ValueError("Raster minimum_wet_overlap must be between 0 and 1")
        if not 0 <= self.minimum_valid_overlap <= 1:
            raise ValueError("Raster minimum_valid_overlap must be between 0 and 1")

        resampling = str(self.resampling).strip().lower()
        if resampling not in {"nearest", "bilinear"}:
            raise ValueError("Raster resampling must be 'nearest' or 'bilinear'")
        object.__setattr__(self, "resampling", resampling)


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy/HDF values to deterministic strict-JSON values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return _frame_records(value)
    if isinstance(value, pd.Series):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return value


def _frame_records(frame: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


class RasQualification:
    """Static qualification, receipt, fingerprint, and parity helpers."""

    SCHEMA_VERSION = "1.0"
    PROJECT_LOCK_NAME = ".ras-commander-project.lock"

    # Every item is critical for production qualification.  A private runner
    # may mark an operation not_applicable only when the profile map below says
    # it truly does not apply; "skipped" always fails qualification.
    REQUIRED_OPERATIONS: Tuple[str, ...] = (
        "installation.detect",
        "wine_prefix.create",
        "project.open",
        "project.save",
        "project.clone",
        "path.spaces",
        "path.long",
        "projection.select",
        "terrain.import",
        "terrain.build_pyramids",
        "terrain.associate",
        "geometry.2d_area_create",
        "geometry.perimeter_edit",
        "mesh.generate_initial",
        "mesh.regenerate",
        "mesh.refinement_region",
        "mesh.breakline",
        "boundary.associate",
        "boundary.conflict_repair",
        "properties.mannings",
        "properties.infiltration",
        "properties.land_cover",
        "plan.preprocess",
        "plan.compute_unsteady",
        "mapper.result_layers",
        "mapper.export_geotiff",
        "recovery.restart",
        "diagnostics.failed_run",
        "locking.project",
        "concurrency.prefix_isolation",
    )

    # These operations are useful for investigation and backwards-compatible
    # manifests, but they are not production gates.  In particular, RAS Mapper
    # geometry property tables are authoritative only after plan/geometry
    # preprocessing; a direct RasMapperLib call is therefore diagnostic.
    DIAGNOSTIC_OPERATIONS: Tuple[str, ...] = (
        "properties.geometry_tables",
        "results.extract_series",
    )
    KNOWN_OPERATIONS: Tuple[str, ...] = REQUIRED_OPERATIONS + DIAGNOSTIC_OPERATIONS

    _PROFILE_NOT_APPLICABLE: Dict[str, set] = {
        ExecutorProfile.WINDOWS_NATIVE.value: {
            "wine_prefix.create",
            "concurrency.prefix_isolation",
        },
        ExecutorProfile.LINUX_WINE_WINDOWS_RAS.value: set(),
        ExecutorProfile.LINUX_NATIVE_EXPERIMENTAL.value: {
            "wine_prefix.create",
            "concurrency.prefix_isolation",
        },
    }

    _VOLATILE_HDF_ATTRIBUTES = {
        "computation time",
        "created",
        "creation time",
        "file creation",
        "file last-access",
        "file last-write",
        "file time",
        "geometry time",
        "last modified",
        "modified",
        "run time window",
        "time stamp",
    }

    _TERRAIN_STITCH_DATASETS: Tuple[str, ...] = (
        "Stitch TIN Points",
        "Stitch TIN Triangles",
        "Stitches",
    )

    # This is intentionally the same persisted-topology surface inspected by
    # native.mesh_host before a transactional mesh candidate replaces the
    # original geometry HDF.  Keep property tables and unrelated geometry out
    # of this list so native/Wine comparisons isolate mesh persistence.
    _MESH_TOPOLOGY_AREA_DATASETS: Tuple[str, ...] = (
        "Cells Center Coordinate",
        "Cells Face and Orientation Info",
        "Cells Face and Orientation Values",
        "Cells FacePoint Indexes",
        "FacePoints Cell Index Values",
        "FacePoints Cell Info",
        "FacePoints Coordinate",
        "FacePoints Face and Orientation Info",
        "FacePoints Face and Orientation Values",
        "FacePoints Is Perimeter",
        "Faces Cell Indexes",
        "Faces FacePoint Indexes",
        "Faces NormalUnitVector and Length",
        "Faces Perimeter Info",
        "Faces Perimeter Values",
        "Perimeter",
    )
    _MESH_ORDERED_FACE_DATASETS: Tuple[str, ...] = (
        "FacePoints Coordinate",
        "Faces Cell Indexes",
        "Faces FacePoint Indexes",
        "Faces NormalUnitVector and Length",
        "Faces Perimeter Info",
        "Faces Perimeter Values",
    )
    _MESH_FACE_ROW_DATASETS: Tuple[str, ...] = (
        "Faces Cell Indexes",
        "Faces FacePoint Indexes",
        "Faces NormalUnitVector and Length",
        "Faces Perimeter Info",
    )

    @staticmethod
    @log_call
    def create_run_receipt(
        profile: Union[str, ExecutorProfile],
        installation: Mapping[str, Any],
        fixture: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Create a fail-closed receipt scaffold for a real qualification run.

        Every required operation starts as ``not_run``.  This makes a partially
        executed runner fail validation without relying on the runner author to
        remember every qualification requirement.
        """
        if isinstance(profile, ExecutorProfile):
            profile = profile.value
        profile_value = str(profile)
        if profile_value not in {item.value for item in ExecutorProfile}:
            raise ValueError(f"Unknown qualification executor profile: {profile_value}")
        if not fixture.get("id") or not fixture.get("source_fingerprint"):
            raise ValueError("fixture requires stable id and source_fingerprint values")

        operations = []
        not_applicable = RasQualification._PROFILE_NOT_APPLICABLE.get(profile_value, set())
        for operation_id in RasQualification.REQUIRED_OPERATIONS:
            status = "not_applicable" if operation_id in not_applicable else "not_run"
            operations.append({"id": operation_id, "status": status})

        return {
            "schema_version": RasQualification.SCHEMA_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "executor_profile": profile_value,
            "installation": _json_value(dict(installation)),
            "fixture": _json_value(dict(fixture)),
            "operations": operations,
            "artifacts": {},
            "series": {},
        }

    @staticmethod
    @log_call
    def record_operation(
        receipt: Dict[str, Any],
        operation_id: str,
        status: str,
        evidence: Optional[Mapping[str, Any]] = None,
        diagnostics: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record one qualification operation with strict status semantics."""
        if operation_id not in RasQualification.KNOWN_OPERATIONS:
            raise ValueError(f"Unknown qualification operation: {operation_id}")
        status_value = str(status).strip().lower()
        if status_value not in {"passed", "failed", "skipped", "not_applicable"}:
            raise ValueError(f"Unsupported qualification operation status: {status}")
        if status_value == "passed" and not evidence:
            raise ValueError(f"Passed operation {operation_id} requires content evidence")

        profile = str(receipt.get("executor_profile", ""))
        allowed_not_applicable = RasQualification._PROFILE_NOT_APPLICABLE.get(profile, set())
        if status_value == "not_applicable" and operation_id not in allowed_not_applicable:
            raise ValueError(
                f"Operation {operation_id} is required for executor profile {profile}"
            )

        operation: Dict[str, Any] = {"id": operation_id, "status": status_value}
        if evidence:
            operation["evidence"] = _json_value(dict(evidence))
        if diagnostics:
            operation["diagnostics"] = _json_value(dict(diagnostics))

        operations = receipt.setdefault("operations", [])
        for index, existing in enumerate(operations):
            if isinstance(existing, Mapping) and existing.get("id") == operation_id:
                operations[index] = operation
                break
        else:
            operations.append(operation)
        return operation

    @staticmethod
    @log_call
    def file_sha256(file_path: Union[str, Path], chunk_size: int = 1024 * 1024) -> str:
        """Return a streaming SHA-256 for an artifact."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    @log_call
    def project_tree_fingerprint(project_folder: Union[str, Path]) -> str:
        """Hash immutable project content, excluding the transient runner lock."""
        root = Path(project_folder)
        if not root.is_dir():
            raise FileNotFoundError(f"Project folder not found: {root}")
        digest = hashlib.sha256()
        files = (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != RasQualification.PROJECT_LOCK_NAME
        )
        for path in sorted(files, key=lambda p: p.as_posix()):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            with path.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b"\x00")
        return digest.hexdigest()

    @staticmethod
    @log_call
    def acquire_project_lock(
        project_folder: Union[str, Path],
        owner: str,
        lock_name: str = PROJECT_LOCK_NAME,
    ) -> Dict[str, Any]:
        """Atomically acquire an exclusive qualification lock for one project.

        The lock is an on-disk ``O_EXCL`` claim so separate Python processes
        cannot both enter a writable HEC-RAS project.  Existing locks are never
        removed automatically: a retained lock is evidence of an interrupted
        owner and requires an explicit recovery decision.
        """
        root = RasUtils.safe_resolve(Path(project_folder))
        if not root.is_dir():
            raise FileNotFoundError(f"Project folder not found: {root}")
        if not any(root.glob("*.prj")):
            raise ValueError(f"No HEC-RAS .prj file found in project folder: {root}")
        owner_value = str(owner).strip()
        if not owner_value:
            raise ValueError("Project lock owner must be non-empty")
        name = str(lock_name).strip()
        if not name or Path(name).name != name:
            raise ValueError("Project lock_name must be one file name")

        lock_path = root / name
        token = uuid.uuid4().hex
        payload = {
            "schema_version": RasQualification.SCHEMA_VERSION,
            "project_folder": str(root),
            "lock_path": str(lock_path),
            "owner": owner_value,
            "token": token,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except FileExistsError as exc:
            raise FileExistsError(
                f"HEC-RAS project is already locked: {lock_path}"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            lock_path.unlink(missing_ok=True)
            raise

        return {
            **payload,
            "file_sha256": RasQualification.file_sha256(lock_path),
            "acquired": True,
        }

    @staticmethod
    @log_call
    def inspect_project_lock(
        project_folder: Union[str, Path],
        lock_name: str = PROJECT_LOCK_NAME,
    ) -> Optional[Dict[str, Any]]:
        """Read an existing project-lock receipt without changing it."""
        root = RasUtils.safe_resolve(Path(project_folder))
        name = str(lock_name).strip()
        if not name or Path(name).name != name:
            raise ValueError("Project lock_name must be one file name")
        lock_path = root / name
        if not lock_path.is_file():
            return None
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"Invalid project-lock payload: {lock_path}")
        return {
            **dict(payload),
            "lock_path": str(lock_path),
            "file_sha256": RasQualification.file_sha256(lock_path),
        }

    @staticmethod
    @log_call
    def release_project_lock(lock_receipt: Mapping[str, Any]) -> Dict[str, Any]:
        """Release exactly the lock identified by ``lock_receipt`` and its token."""
        lock_path = Path(str(lock_receipt.get("lock_path", "")))
        expected_token = str(lock_receipt.get("token", ""))
        if not expected_token or not lock_path.name:
            raise ValueError("A lock_path and token are required to release a project lock")
        if not lock_path.is_file():
            raise FileNotFoundError(f"Project lock no longer exists: {lock_path}")
        current = json.loads(lock_path.read_text(encoding="utf-8"))
        current_token = str(current.get("token", "")) if isinstance(current, Mapping) else ""
        if current_token != expected_token:
            raise PermissionError(
                f"Refusing to release project lock owned by a different token: {lock_path}"
            )
        before_sha256 = RasQualification.file_sha256(lock_path)
        lock_path.unlink()
        return {
            "lock_path": str(lock_path),
            "token": expected_token,
            "before_sha256": before_sha256,
            "released": True,
            "exists_after_release": lock_path.exists(),
        }

    @staticmethod
    def _round_hdf_attr_floats(value: Any, digits: Optional[int]) -> Any:
        if digits is None:
            return value
        if isinstance(value, float):
            return round(value, digits)
        if isinstance(value, list):
            return [RasQualification._round_hdf_attr_floats(item, digits) for item in value]
        if isinstance(value, dict):
            return {
                key: RasQualification._round_hdf_attr_floats(item, digits)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _hash_hdf_attrs(
        digest: "hashlib._Hash",
        attrs: h5py.AttributeManager,
        *,
        ignored_attributes: Sequence[str] = (),
        float_round_digits: Optional[int] = None,
    ) -> None:
        ignored = {
            str(name).strip().lower()
            for name in ignored_attributes
        } | RasQualification._VOLATILE_HDF_ATTRIBUTES
        for key in sorted(attrs.keys(), key=lambda item: str(item).lower()):
            if str(key).strip().lower() in ignored:
                continue
            digest.update(b"A\x00")
            digest.update(str(key).encode("utf-8"))
            digest.update(b"\x00")
            value = RasQualification._round_hdf_attr_floats(
                _json_value(attrs[key]),
                float_round_digits,
            )
            encoded = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            digest.update(encoded)
            digest.update(b"\x00")

    @staticmethod
    def _hash_hdf_dataset(digest: "hashlib._Hash", dataset: h5py.Dataset) -> None:
        digest.update(str(dataset.dtype).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(json.dumps(list(dataset.shape)).encode("ascii"))
        digest.update(b"\x00")

        if dataset.shape == ():
            values = dataset[()]
            if dataset.dtype.kind == "O":
                digest.update(json.dumps(_json_value(values), sort_keys=True).encode("utf-8"))
            else:
                digest.update(np.ascontiguousarray(values).tobytes())
            return

        row_count = dataset.shape[0]
        trailing_items = int(np.prod(dataset.shape[1:])) if len(dataset.shape) > 1 else 1
        item_size = max(int(dataset.dtype.itemsize), 1)
        rows_per_chunk = max(1, (4 * 1024 * 1024) // max(trailing_items * item_size, 1))
        for start in range(0, row_count, rows_per_chunk):
            values = dataset[start : start + rows_per_chunk]
            if dataset.dtype.kind == "O":
                digest.update(
                    json.dumps(
                        _json_value(values),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
            else:
                digest.update(np.ascontiguousarray(values).tobytes())

    @staticmethod
    def _exact_dtype_descriptor(dtype: np.dtype) -> Dict[str, Any]:
        """Return a JSON-safe dtype identity without native-endian coercion."""
        resolved = np.dtype(dtype)
        return {
            "str": resolved.str,
            "descr": _json_value(resolved.descr),
            "itemsize": int(resolved.itemsize),
        }

    @staticmethod
    def _update_exact_array_content(
        digest: "hashlib._Hash",
        values: Any,
    ) -> None:
        """Hash array values without numeric conversion or float rounding."""
        array = np.asarray(values)
        if array.dtype.hasobject:
            digest.update(
                json.dumps(
                    _json_value(array),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        else:
            digest.update(np.ascontiguousarray(array).tobytes(order="C"))

    @staticmethod
    def _exact_array_evidence(values: Any) -> Dict[str, Any]:
        """Fingerprint one exact array including its dtype and stored shape."""
        array = np.asarray(values)
        dtype = RasQualification._exact_dtype_descriptor(array.dtype)
        shape = [int(value) for value in array.shape]
        digest = hashlib.sha256()
        digest.update(b"ras-commander-exact-hdf-array-v1\x00")
        digest.update(
            json.dumps(
                {"dtype": dtype, "shape": shape},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        digest.update(b"\x00")
        RasQualification._update_exact_array_content(digest, array)
        return {
            "dtype": dtype,
            "shape": shape,
            "fingerprint": digest.hexdigest(),
        }

    @staticmethod
    def _exact_dataset_evidence(dataset: h5py.Dataset) -> Dict[str, Any]:
        """Fingerprint one HDF dataset exactly while bounding read memory."""
        dtype = RasQualification._exact_dtype_descriptor(dataset.dtype)
        shape = [int(value) for value in dataset.shape]
        digest = hashlib.sha256()
        digest.update(b"ras-commander-exact-hdf-array-v1\x00")
        digest.update(
            json.dumps(
                {"dtype": dtype, "shape": shape},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        digest.update(b"\x00")

        if dataset.shape == ():
            RasQualification._update_exact_array_content(digest, dataset[()])
        else:
            row_count = int(dataset.shape[0])
            trailing_items = (
                int(np.prod(dataset.shape[1:])) if len(dataset.shape) > 1 else 1
            )
            row_size = max(trailing_items * max(int(dataset.dtype.itemsize), 1), 1)
            rows_per_chunk = max(1, (4 * 1024 * 1024) // row_size)
            for start in range(0, row_count, rows_per_chunk):
                RasQualification._update_exact_array_content(
                    digest,
                    dataset[start : start + rows_per_chunk],
                )
        return {
            "dtype": dtype,
            "shape": shape,
            "fingerprint": digest.hexdigest(),
        }

    @staticmethod
    def _mesh_component_fingerprint(
        component: str,
        *,
        declared_cell_count: int,
        face_count: int,
        datasets: Mapping[str, Mapping[str, Any]],
    ) -> str:
        """Combine exact dataset hashes into one domain-separated digest."""
        payload = {
            "schema": "ras-commander-mesh-topology-v1",
            "component": component,
            "declared_cell_count": int(declared_cell_count),
            "face_count": int(face_count),
            "datasets": {
                str(name): str(evidence["fingerprint"])
                for name, evidence in sorted(datasets.items())
            },
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _mesh_topology_evidence(
        hdf: h5py.File,
        *,
        mesh_name: str,
        attributes_row: int,
        declared_cell_count: int,
        reported_face_count: int,
    ) -> Dict[str, Any]:
        """Build exact, per-area persisted mesh evidence without property data."""
        root = "Geometry/2D Flow Areas"
        area_root = f"{root}/{mesh_name}"
        missing: List[str] = []
        errors: List[str] = []
        datasets: Dict[str, Dict[str, Any]] = {}

        def record_dataset(
            logical_name: str,
            source_path: str,
            dataset: h5py.Dataset,
        ) -> None:
            evidence = RasQualification._exact_dataset_evidence(dataset)
            evidence["source_path"] = f"/{source_path}"
            datasets[logical_name] = evidence

        attributes_path = f"{root}/Attributes"
        if attributes_path not in hdf:
            missing.append(f"/{attributes_path}")
        else:
            attributes = hdf[attributes_path]
            fields = attributes.dtype.fields or {}
            if (
                attributes.ndim != 1
                or attributes_row >= attributes.shape[0]
                or "Name" not in fields
                or "Cell Count" not in fields
            ):
                errors.append(
                    f"/{attributes_path} cannot select Name and Cell Count for "
                    f"row {attributes_row}"
                )
            else:
                selected_attributes = np.empty(
                    1,
                    dtype=np.dtype(
                        [
                            ("Name", fields["Name"][0]),
                            ("Cell Count", fields["Cell Count"][0]),
                        ]
                    ),
                )
                selected_attributes["Name"] = attributes["Name"][
                    attributes_row : attributes_row + 1
                ]
                selected_attributes["Cell Count"] = attributes["Cell Count"][
                    attributes_row : attributes_row + 1
                ]
                persisted_cell_count = int(selected_attributes["Cell Count"][0])
                if persisted_cell_count != int(declared_cell_count):
                    errors.append(
                        f"persisted cell count {persisted_cell_count} does not match "
                        f"reported cell count {declared_cell_count}"
                    )
                evidence = RasQualification._exact_array_evidence(
                    selected_attributes
                )
                evidence.update(
                    {
                        "source_path": f"/{attributes_path}",
                        "source_selection": [attributes_row, attributes_row + 1],
                        "source_fields": ["Name", "Cell Count"],
                    }
                )
                datasets["Attributes (Name and Cell Count)"] = evidence

        cell_info_path = f"{root}/Cell Info"
        cell_points_path = f"{root}/Cell Points"
        seed_start: Optional[int] = None
        seed_count: Optional[int] = None
        if cell_info_path not in hdf:
            missing.append(f"/{cell_info_path}")
        else:
            cell_info = hdf[cell_info_path]
            if (
                cell_info.ndim != 2
                or cell_info.shape[1] != 2
                or attributes_row >= cell_info.shape[0]
            ):
                errors.append(
                    f"/{cell_info_path} cannot select row {attributes_row} from "
                    f"shape {tuple(cell_info.shape)}"
                )
            else:
                selected_info = np.asarray(
                    cell_info[attributes_row : attributes_row + 1]
                )
                evidence = RasQualification._exact_array_evidence(selected_info)
                evidence.update(
                    {
                        "source_path": f"/{cell_info_path}",
                        "source_selection": [attributes_row, attributes_row + 1],
                    }
                )
                datasets["Cell Info (area row)"] = evidence
                seed_start, seed_count = [int(value) for value in selected_info[0]]

        if cell_points_path not in hdf:
            missing.append(f"/{cell_points_path}")
        elif seed_start is not None and seed_count is not None:
            cell_points = hdf[cell_points_path]
            if (
                cell_points.ndim != 2
                or cell_points.shape[1] != 2
                or seed_start < 0
                or seed_count <= 0
                or seed_start + seed_count > cell_points.shape[0]
            ):
                errors.append(
                    f"/{cell_points_path} cannot select seed range "
                    f"[{seed_start}, {seed_start + seed_count}) from shape "
                    f"{tuple(cell_points.shape)}"
                )
            else:
                selected_points = np.asarray(
                    cell_points[seed_start : seed_start + seed_count]
                )
                evidence = RasQualification._exact_array_evidence(selected_points)
                evidence.update(
                    {
                        "source_path": f"/{cell_points_path}",
                        "source_selection": [seed_start, seed_start + seed_count],
                    }
                )
                datasets["Cell Points (area seed range)"] = evidence

        if area_root not in hdf:
            missing.append(f"/{area_root}")
        else:
            area = hdf[area_root]
            for dataset_name in RasQualification._MESH_TOPOLOGY_AREA_DATASETS:
                dataset_path = f"{area_root}/{dataset_name}"
                if dataset_name not in area:
                    missing.append(f"/{dataset_path}")
                    continue
                record_dataset(dataset_name, dataset_path, area[dataset_name])

        centers_component: Dict[str, Any] = {
            "fingerprint": None,
            "row_count": int(declared_cell_count),
            "dataset": "Cells Center Coordinate[0:declared_cell_count]",
        }
        centers_path = f"{area_root}/Cells Center Coordinate"
        if centers_path in hdf:
            centers = hdf[centers_path]
            if (
                declared_cell_count < 0
                or centers.ndim != 2
                or centers.shape[1] != 2
                or centers.shape[0] < declared_cell_count
            ):
                errors.append(
                    f"/{centers_path} shape {tuple(centers.shape)} cannot supply "
                    f"{declared_cell_count} declared centers"
                )
            else:
                selected_centers = np.asarray(centers[:declared_cell_count])
                center_evidence = RasQualification._exact_array_evidence(selected_centers)
                center_evidence.update(
                    {
                        "source_path": f"/{centers_path}",
                        "source_selection": [0, int(declared_cell_count)],
                    }
                )
                centers_component.update(center_evidence)
                centers_component["fingerprint"] = (
                    RasQualification._mesh_component_fingerprint(
                        "ordered_nonvirtual_centers",
                        declared_cell_count=declared_cell_count,
                        face_count=reported_face_count,
                        datasets={"ordered_nonvirtual_centers": center_evidence},
                    )
                )

        persisted_face_count: Optional[int] = None
        faces_cell_path = f"{area_root}/Faces Cell Indexes"
        if faces_cell_path in hdf:
            faces_cell_indexes = hdf[faces_cell_path]
            if faces_cell_indexes.ndim < 1:
                errors.append(f"/{faces_cell_path} has scalar shape")
            else:
                persisted_face_count = int(faces_cell_indexes.shape[0])
                if persisted_face_count != int(reported_face_count):
                    errors.append(
                        f"persisted face count {persisted_face_count} does not match "
                        f"reported face count {reported_face_count}"
                    )

        face_component_datasets = {
            name: datasets[name]
            for name in RasQualification._MESH_ORDERED_FACE_DATASETS
            if name in datasets
        }
        faces_component: Dict[str, Any] = {
            "fingerprint": None,
            "face_count": (
                persisted_face_count
                if persisted_face_count is not None
                else int(reported_face_count)
            ),
            "datasets": list(RasQualification._MESH_ORDERED_FACE_DATASETS),
        }
        if len(face_component_datasets) == len(
            RasQualification._MESH_ORDERED_FACE_DATASETS
        ):
            inconsistent_face_rows = [
                name
                for name, evidence in face_component_datasets.items()
                if name in RasQualification._MESH_FACE_ROW_DATASETS
                and (
                    not evidence["shape"]
                    or int(evidence["shape"][0]) != int(reported_face_count)
                )
            ]
            if inconsistent_face_rows:
                errors.append(
                    "ordered face datasets do not match face count: "
                    f"{inconsistent_face_rows}"
                )
            else:
                faces_component["fingerprint"] = (
                    RasQualification._mesh_component_fingerprint(
                        "ordered_faces_and_indexes",
                        declared_cell_count=declared_cell_count,
                        face_count=reported_face_count,
                        datasets=face_component_datasets,
                    )
                )

        complete = not missing and not errors
        topology_fingerprint = None
        if complete:
            topology_fingerprint = RasQualification._mesh_component_fingerprint(
                "persisted_topology",
                declared_cell_count=declared_cell_count,
                face_count=reported_face_count,
                datasets=datasets,
            )

        return {
            "complete": complete,
            "fingerprint": topology_fingerprint,
            "declared_cell_count": int(declared_cell_count),
            "face_count": int(reported_face_count),
            "persisted_face_count": persisted_face_count,
            "missing_datasets": sorted(missing),
            "errors": errors,
            "datasets": datasets,
            "components": {
                "ordered_nonvirtual_centers": centers_component,
                "ordered_faces_and_indexes": faces_component,
            },
        }

    @staticmethod
    @log_call
    def canonical_hdf_fingerprint(
        hdf_path: Union[str, Path],
        roots: Sequence[str] = ("/Geometry",),
        *,
        ignored_attributes: Sequence[str] = (),
        float_round_digits: Optional[int] = None,
    ) -> str:
        """Hash selected HDF content while excluding known volatile timestamps."""
        path = Path(hdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"HDF file not found: {path}")

        digest = hashlib.sha256()
        with h5py.File(path, "r") as hdf:
            for root_name in sorted(set(roots)):
                if root_name not in hdf:
                    raise KeyError(f"HDF root not found: {root_name}")
                root = hdf[root_name]
                objects: List[Tuple[str, Union[h5py.Group, h5py.Dataset]]] = [(root.name, root)]
                if isinstance(root, h5py.Group):
                    root.visititems(lambda _name, obj: objects.append((obj.name, obj)))
                for object_name, obj in sorted(objects, key=lambda item: item[0]):
                    digest.update(b"D\x00" if isinstance(obj, h5py.Dataset) else b"G\x00")
                    digest.update(object_name.encode("utf-8"))
                    digest.update(b"\x00")
                    RasQualification._hash_hdf_attrs(
                        digest,
                        obj.attrs,
                        ignored_attributes=ignored_attributes,
                        float_round_digits=float_round_digits,
                    )
                    if isinstance(obj, h5py.Dataset):
                        RasQualification._hash_hdf_dataset(digest, obj)
        return digest.hexdigest()

    @staticmethod
    @log_call
    def terrain_hdf_semantic_fingerprint(
        terrain_hdf: Union[str, Path],
    ) -> str:
        """Hash stable terrain structure/content while excluding run metadata."""
        return RasQualification.canonical_hdf_fingerprint(
            terrain_hdf,
            roots=("/Terrain",),
            ignored_attributes=("guid",),
            float_round_digits=9,
        )

    @staticmethod
    @log_call
    def inspect_installation(
        ras_executable: Optional[Union[str, Path]] = None,
        expected_version: str = "7.0.1",
    ) -> Dict[str, Any]:
        """Inspect the real Ras.exe and required sibling components without running them."""
        expected = RasUtils.normalize_ras_version(expected_version)
        resolved = str(ras_executable) if ras_executable is not None else get_ras_exe(expected)
        executable = Path(resolved)
        if executable.is_dir():
            executable = executable / "Ras.exe"
            resolved = str(executable)
        if resolved.lower() == "ras.exe" or not executable.is_file():
            raise FileNotFoundError(
                f"HEC-RAS {expected} Ras.exe was not resolved to an installed executable: {resolved}"
            )

        version_info = RasUtils.get_executable_version(executable)
        detected = version_info.get("normalized_version")
        if not detected:
            detected = RasUtils.normalize_ras_version(executable.parent.name)

        component_paths = {
            "ras": executable,
            "rasprocess": executable.parent / "RasProcess.exe",
            "rasmapperlib": executable.parent / "RasMapperLib.dll",
            "ras_geom_preprocess": executable.parent / "x64" / "RasGeomPreprocess.exe",
            "ras_unsteady": executable.parent / "x64" / "RasUnsteady.exe",
        }
        components: Dict[str, Dict[str, Any]] = {}
        for name, component in component_paths.items():
            exists = component.is_file()
            components[name] = {
                "path": str(component),
                "exists": exists,
                "sha256": RasQualification.file_sha256(component) if exists else None,
                "pe": RasUtils.get_pe_architecture(component) if exists else None,
            }

        return {
            "expected_version": expected,
            "detected_version": detected,
            "version_matches": detected == expected,
            "version_info": version_info,
            "components": components,
            "required_components_present": all(item["exists"] for item in components.values()),
        }

    @staticmethod
    @log_call
    def create_isolated_wine_prefix(
        base_directory: Union[str, Path],
        task_id: Optional[str] = None,
        wine_executable: Union[str, Path] = "wine",
        initialize: bool = True,
        timeout: int = 600,
        display: Optional[str] = None,
        template_prefix: Optional[Union[str, Path]] = None,
        wineboot_dll_overrides: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a unique 64-bit Wine prefix for one scheduler task.

        The prefix is never reused or removed automatically.  Failed prefixes are
        retained with their metadata so the private runner can preserve diagnostics.
        A cloned, prepared template is usable without rerunning ``wineboot``; callers
        should request initialization only when they intentionally need an update.
        """
        base = Path(base_directory)
        base.mkdir(parents=True, exist_ok=True)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id or "task").strip("-.") or "task"
        prefix = base / f"rasq-{safe_task}-{uuid.uuid4().hex[:10]}"
        template = None
        template_fingerprint = None
        if template_prefix is not None:
            template = RasUtils.safe_resolve(Path(template_prefix))
            if not template.is_dir():
                raise FileNotFoundError(f"Wine prefix template not found: {template}")
            template_fingerprint = RasQualification.project_tree_fingerprint(template)
            shutil.copytree(template, prefix, symlinks=True)
        else:
            prefix.mkdir()

        wine_path = Path(str(wine_executable))
        if wine_path.parent != Path(".") or wine_path.is_absolute():
            sibling = wine_path.with_name("wineboot")
            wineboot = str(sibling) if sibling.exists() else "wineboot"
        else:
            wineboot = shutil.which("wineboot") or "wineboot"

        environment = os.environ.copy()
        environment.update(
            {
                "WINEPREFIX": str(prefix),
                "WINEARCH": "win64",
                "WINEDEBUG": "-all",
            }
        )
        if display is not None:
            environment["DISPLAY"] = display
        if wineboot_dll_overrides:
            environment["WINEDLLOVERRIDES"] = wineboot_dll_overrides

        metadata: Dict[str, Any] = {
            "prefix": str(prefix),
            "task_id": safe_task,
            "wine_executable": str(wine_executable),
            "wineboot_executable": wineboot,
            "wine_arch": "win64",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "template_prefix": str(template) if template is not None else None,
            "template_fingerprint": template_fingerprint,
            "wineboot_dll_overrides": wineboot_dll_overrides,
            "initialization_requested": initialize,
            "initialization_mode": (
                "wineboot_update"
                if initialize and template is not None
                else "wineboot_init"
                if initialize
                else "prepared_template_clone"
                if template is not None
                else "uninitialized"
            ),
            "initialized": bool(template is not None and not initialize),
            "return_code": None,
            "stdout": "",
            "stderr": "",
        }

        if initialize:
            try:
                result = subprocess.run(
                    [wineboot, "--update" if template is not None else "--init"],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=environment,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                metadata["stderr"] = str(exc)
                RasQualification._write_prefix_metadata(prefix, metadata)
                raise RuntimeError(f"Wine prefix initialization failed for {prefix}: {exc}") from exc
            metadata.update(
                {
                    "initialized": result.returncode == 0,
                    "return_code": result.returncode,
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                }
            )
            RasQualification._write_prefix_metadata(prefix, metadata)
            if result.returncode != 0:
                raise RuntimeError(
                    f"wineboot failed for isolated prefix {prefix} with exit code {result.returncode}: "
                    f"{(result.stderr or result.stdout or '').strip()}"
                )
        else:
            RasQualification._write_prefix_metadata(prefix, metadata)

        return metadata

    @staticmethod
    def _write_prefix_metadata(prefix: Path, metadata: Mapping[str, Any]) -> None:
        marker = prefix / ".ras-commander-prefix.json"
        marker.write_text(
            json.dumps(_json_value(metadata), indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )

    @staticmethod
    @log_call
    def inspect_python_packages(
        site_packages: Union[str, Path],
        expected: Mapping[str, str],
    ) -> Dict[str, Any]:
        """Inspect exact package versions from ``*.dist-info/METADATA`` files."""
        root = Path(site_packages)
        if not root.is_dir():
            raise FileNotFoundError(f"Python site-packages directory not found: {root}")
        if not isinstance(expected, Mapping) or not expected:
            raise ValueError("expected Python packages must be a non-empty mapping")

        def normalize(value: Any) -> str:
            return re.sub(r"[-_.]+", "-", str(value)).lower()

        expected_normalized = {
            normalize(name): {"name": str(name), "version": str(version)}
            for name, version in expected.items()
        }
        installed: Dict[str, list[Dict[str, Any]]] = {
            name: [] for name in expected_normalized
        }
        for metadata_path in sorted(root.glob("*.dist-info/METADATA")):
            package_name = None
            package_version = None
            for line in metadata_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("Name: "):
                    package_name = line[6:].strip()
                elif line.startswith("Version: "):
                    package_version = line[9:].strip()
                if package_name is not None and package_version is not None:
                    break
            normalized_name = normalize(package_name or "")
            if normalized_name in installed:
                installed[normalized_name].append(
                    {
                        "name": package_name,
                        "version": package_version,
                        "metadata": str(metadata_path),
                        "metadata_sha256": RasQualification.file_sha256(metadata_path),
                    }
                )

        checks: Dict[str, Any] = {}
        for normalized_name, requirement in expected_normalized.items():
            candidates = installed[normalized_name]
            checks[requirement["name"]] = {
                "expected_version": requirement["version"],
                "installed": candidates,
                "matches": len(candidates) == 1
                and candidates[0]["version"] == requirement["version"],
            }
        return {
            "site_packages": str(root),
            "checks": checks,
            "all_match": all(item["matches"] for item in checks.values()),
        }

    @staticmethod
    @log_call
    def stage_project(
        source_project: Union[str, Path],
        workspace_root: Union[str, Path],
        task_id: Optional[str] = None,
        path_variant: str = "standard",
        minimum_long_path: int = 280,
    ) -> Dict[str, Any]:
        """Copy one immutable fixture into an isolated task workspace."""
        source = RasUtils.safe_resolve(Path(source_project))
        if not source.is_dir():
            raise FileNotFoundError(f"Source project folder not found: {source}")
        project_files = sorted(source.glob("*.prj"))
        if not project_files:
            raise ValueError(f"No HEC-RAS .prj file found in source fixture: {source}")

        variant = path_variant.lower()
        if variant not in {"standard", "spaces", "long"}:
            raise ValueError("path_variant must be 'standard', 'spaces', or 'long'")

        root = RasUtils.safe_resolve(Path(workspace_root))
        root.mkdir(parents=True, exist_ok=True)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id or "task").strip("-.") or "task"
        token = uuid.uuid4().hex[:10]
        if variant == "spaces":
            destination = root / f"RAS qualification {safe_task} {token}" / source.name
        elif variant == "long":
            destination = root / f"rasq-{safe_task}-{token}"
            segment_index = 0
            while len(str(destination / source.name)) < minimum_long_path:
                destination = destination / f"long-path-segment-{segment_index:02d}-qualification"
                segment_index += 1
            destination = destination / source.name
        else:
            destination = root / f"rasq-{safe_task}-{token}" / source.name

        destination_io = RasUtils.windows_extended_path(destination)
        if destination_io.exists():
            raise FileExistsError(f"Isolated project destination already exists: {destination}")

        source_lock_present = (source / RasQualification.PROJECT_LOCK_NAME).is_file()
        source_fingerprint = RasQualification.project_tree_fingerprint(source)
        destination_io.parent.mkdir(parents=True, exist_ok=True)
        def ignore_runtime_files(directory: str, names: List[str]) -> List[str]:
            ignored = set(RasUtils.ignore_windows_reserved(directory, names))
            if RasQualification.PROJECT_LOCK_NAME in names:
                ignored.add(RasQualification.PROJECT_LOCK_NAME)
            return sorted(ignored)

        shutil.copytree(source, destination_io, ignore=ignore_runtime_files)
        writable_paths = [destination_io, *destination_io.rglob("*")]
        writable_file_count = 0
        writable_directory_count = 0
        for copied_path in writable_paths:
            if copied_path.is_symlink():
                continue
            current_mode = copied_path.stat().st_mode
            owner_mode = stat.S_IRUSR | stat.S_IWUSR
            if copied_path.is_dir():
                owner_mode |= stat.S_IXUSR
                writable_directory_count += 1
            else:
                writable_file_count += 1
            copied_path.chmod(current_mode | owner_mode)
        owner_write_verified = all(
            copied_path.is_symlink()
            or bool(copied_path.stat().st_mode & stat.S_IWUSR)
            for copied_path in writable_paths
        )
        if not owner_write_verified:
            raise RuntimeError(
                f"Isolated project clone is not owner-writable: {destination}"
            )
        destination_lock = destination_io / RasQualification.PROJECT_LOCK_NAME
        if destination_lock.exists():
            raise RuntimeError(
                f"Transient project lock was copied into isolated workspace: {destination_lock}"
            )
        destination_fingerprint = RasQualification.project_tree_fingerprint(destination_io)
        if source_fingerprint != destination_fingerprint:
            raise RuntimeError(
                f"Project clone content mismatch: {source_fingerprint} != {destination_fingerprint}"
            )

        return {
            "source": str(source),
            "destination": str(destination),
            "project_file": str(destination / project_files[0].name),
            "path_variant": variant,
            "path_length": len(str(destination)),
            "source_fingerprint": source_fingerprint,
            "destination_fingerprint": destination_fingerprint,
            "content_matches": True,
            "writable_clone": {
                "normalized": True,
                "owner_write_verified": owner_write_verified,
                "directory_count": writable_directory_count,
                "file_count": writable_file_count,
                "source_permissions_unchanged": True,
            },
            "transient_lock": {
                "name": RasQualification.PROJECT_LOCK_NAME,
                "source_present_during_stage": source_lock_present,
                "destination_present": False,
                "excluded": True,
            },
        }

    @staticmethod
    def _distribution(values: Iterable[float]) -> Dict[str, Any]:
        array = np.asarray(list(values), dtype=float)
        array = array[np.isfinite(array)]
        if not len(array):
            return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "mean": None}
        return {
            "count": int(len(array)),
            "min": float(np.min(array)),
            "p50": float(np.percentile(array, 50)),
            "p95": float(np.percentile(array, 95)),
            "max": float(np.max(array)),
            "mean": float(np.mean(array)),
        }

    @staticmethod
    @log_call
    def geometry_receipt(
        geometry_hdf: Union[str, Path],
        include_quality: bool = True,
    ) -> Dict[str, Any]:
        """Inspect mesh counts, assignments, property coverage, quality, and content."""
        from .hdf import HdfBndry, HdfMesh

        path = Path(geometry_hdf)
        if not path.is_file():
            raise FileNotFoundError(f"Geometry HDF not found: {path}")

        mesh_names = HdfMesh.get_mesh_area_names(path)
        cell_points = HdfMesh.get_mesh_cell_points(path)
        faces = HdfMesh.get_mesh_cell_faces(path)
        face_tables = HdfMesh.get_mesh_face_property_tables(path)
        cell_tables = HdfMesh.get_mesh_cell_property_tables(path)
        bc_lines = HdfBndry.get_bc_lines(path)
        breaklines = HdfBndry.get_breaklines(path)
        refinement_regions = HdfBndry.get_refinement_regions(path)

        declared_cell_counts: Dict[str, int] = {}
        attribute_row_indices: Dict[str, int] = {}
        with h5py.File(path, "r") as hdf:
            attributes_key = "Geometry/2D Flow Areas/Attributes"
            if attributes_key in hdf:
                attributes = hdf[attributes_key][:]
                names = attributes.dtype.names or ()
                if "Name" in names:
                    for row_index, row in enumerate(attributes):
                        raw_name = row["Name"]
                        if isinstance(raw_name, bytes):
                            area_name = raw_name.decode("utf-8", errors="replace").strip("\x00 ")
                        else:
                            area_name = str(raw_name).strip()
                        attribute_row_indices[area_name] = row_index
                        if "Cell Count" in names:
                            declared_cell_counts[area_name] = int(row["Cell Count"])

        areas: Dict[str, Dict[str, Any]] = {}
        with h5py.File(path, "r") as topology_hdf:
            for mesh_name in mesh_names:
                cell_storage_rows = (
                    int((cell_points.get("mesh_name") == mesh_name).sum())
                    if not cell_points.empty
                    else 0
                )
                cell_count = declared_cell_counts.get(mesh_name, cell_storage_rows)
                face_count = (
                    int((faces.get("mesh_name") == mesh_name).sum())
                    if not faces.empty
                    else 0
                )
                face_table = face_tables.get(mesh_name, pd.DataFrame())
                cell_table = cell_tables.get(mesh_name, pd.DataFrame())
                face_table_ids = (
                    int(face_table["Face ID"].nunique())
                    if not face_table.empty and "Face ID" in face_table
                    else 0
                )
                cell_table_ids = (
                    int(cell_table["Cell ID"].nunique())
                    if not cell_table.empty and "Cell ID" in cell_table
                    else 0
                )
                areas[mesh_name] = {
                    "cell_count": cell_count,
                    "cell_center_storage_rows": cell_storage_rows,
                    "cell_storage_has_capacity_rows": cell_storage_rows > cell_count,
                    "face_count": face_count,
                    "face_property_table_ids": face_table_ids,
                    "face_property_coverage": face_table_ids / face_count if face_count else 0.0,
                    "face_property_complete": bool(face_count and face_table_ids == face_count),
                    "cell_property_table_ids": cell_table_ids,
                    "cell_property_coverage": cell_table_ids / cell_count if cell_count else 0.0,
                    "cell_property_complete": bool(cell_count and cell_table_ids == cell_count),
                }
                attributes_row = attribute_row_indices.get(mesh_name)
                if attributes_row is None:
                    areas[mesh_name]["mesh_topology"] = {
                        "complete": False,
                        "fingerprint": None,
                        "declared_cell_count": declared_cell_counts.get(mesh_name),
                        "face_count": face_count,
                        "persisted_face_count": None,
                        "missing_datasets": [
                            "/Geometry/2D Flow Areas/Attributes (matching area row)"
                        ],
                        "errors": [],
                        "datasets": {},
                        "components": {
                            "ordered_nonvirtual_centers": {"fingerprint": None},
                            "ordered_faces_and_indexes": {"fingerprint": None},
                        },
                    }
                else:
                    areas[mesh_name]["mesh_topology"] = (
                        RasQualification._mesh_topology_evidence(
                            topology_hdf,
                            mesh_name=mesh_name,
                            attributes_row=attributes_row,
                            declared_cell_count=cell_count,
                            reported_face_count=face_count,
                        )
                    )

        if include_quality:
            cell_polygons = HdfMesh.get_mesh_cell_polygons(path)
            for mesh_name in mesh_names:
                mesh_cells = (
                    cell_polygons[cell_polygons["mesh_name"] == mesh_name]
                    if not cell_polygons.empty and "mesh_name" in cell_polygons
                    else pd.DataFrame()
                )
                mesh_faces = (
                    faces[faces["mesh_name"] == mesh_name]
                    if not faces.empty and "mesh_name" in faces
                    else pd.DataFrame()
                )
                cell_areas: List[float] = []
                aspect_ratios: List[float] = []
                invalid_count = 0
                if not mesh_cells.empty:
                    for geometry in mesh_cells.geometry:
                        if geometry is None or geometry.is_empty or not geometry.is_valid:
                            invalid_count += 1
                            continue
                        cell_areas.append(float(geometry.area))
                        rectangle = geometry.minimum_rotated_rectangle
                        coordinates = list(rectangle.exterior.coords)
                        side_lengths = [
                            math.hypot(
                                coordinates[index + 1][0] - coordinates[index][0],
                                coordinates[index + 1][1] - coordinates[index][1],
                            )
                            for index in range(min(4, len(coordinates) - 1))
                        ]
                        positive = [length for length in side_lengths if length > 0]
                        if positive:
                            aspect_ratios.append(max(positive) / min(positive))
                face_lengths = (
                    [float(geometry.length) for geometry in mesh_faces.geometry if geometry is not None]
                    if not mesh_faces.empty
                    else []
                )
                areas[mesh_name]["quality"] = {
                    "polygon_count": int(len(mesh_cells)),
                    "invalid_cell_count": invalid_count,
                    "cell_area": RasQualification._distribution(cell_areas),
                    "cell_aspect_ratio": RasQualification._distribution(aspect_ratios),
                    "face_length": RasQualification._distribution(face_lengths),
                }

        boundary_assignments: List[Dict[str, Any]] = []
        if bc_lines is not None and not bc_lines.empty:
            for _, row in bc_lines.iterrows():
                boundary_assignments.append(
                    {
                        "name": _json_value(row.get("Name")),
                        "mesh_name": _json_value(row.get("SA-2D")),
                        "type": _json_value(row.get("Type")),
                        "bc_line_id": _json_value(row.get("bc_line_id")),
                    }
                )
        boundary_assignments.sort(
            key=lambda item: (
                str(item.get("mesh_name")),
                str(item.get("name")),
                str(item.get("type")),
                str(item.get("bc_line_id")),
            )
        )

        return {
            "path": str(path.resolve()),
            "file_sha256": RasQualification.file_sha256(path),
            "geometry_fingerprint": RasQualification.canonical_hdf_fingerprint(path, roots=("/Geometry",)),
            "mesh_area_count": len(mesh_names),
            "areas": areas,
            "boundary_assignments": boundary_assignments,
            "breakline_count": int(len(breaklines)) if breaklines is not None else 0,
            "refinement_region_count": int(len(refinement_regions)) if refinement_regions is not None else 0,
        }

    @staticmethod
    @log_call
    def results_receipt(
        plan_hdf: Union[str, Path],
        completion_mode: str = "windows",
    ) -> Dict[str, Any]:
        """Inspect solution status, compute diagnostics, and volume accounting."""
        from .hdf import HdfResultsPlan
        from .results.ResultsParser import ResultsParser

        path = Path(plan_hdf)
        if not path.is_file():
            raise FileNotFoundError(f"Plan HDF not found: {path}")
        mode = str(completion_mode).strip().lower()
        if mode not in {"windows", "native_linux"}:
            raise ValueError(
                "completion_mode must be either 'windows' or 'native_linux'"
            )

        try:
            summary = HdfResultsPlan.get_unsteady_summary(path)
        except (KeyError, RuntimeError, ValueError, OSError) as exc:
            logger.warning(f"Unsteady summary unavailable in {path}: {exc}")
            summary = pd.DataFrame()
        try:
            volume = HdfResultsPlan.get_volume_accounting(path)
        except (KeyError, RuntimeError, ValueError, OSError) as exc:
            logger.warning(f"Volume accounting unavailable in {path}: {exc}")
            volume = pd.DataFrame()
        try:
            compute_messages = HdfResultsPlan.get_compute_messages_hdf_only(path) or ""
        except (KeyError, RuntimeError, ValueError, OSError) as exc:
            logger.warning(f"Compute messages unavailable in {path}: {exc}")
            compute_messages = ""

        summary_records = _frame_records(summary)
        volume_records = _frame_records(volume)
        compute_diagnostics = ResultsParser.parse_compute_messages(compute_messages)
        with h5py.File(path, "r") as hdf:
            structural_checks = {
                "plan_information_present": "/Plan Data/Plan Information" in hdf,
                "unsteady_summary_present": "/Results/Unsteady/Summary" in hdf,
            }
        completion_checks = {
            "complete_process_present": bool(compute_diagnostics["completed"]),
            "no_compute_errors": not bool(compute_diagnostics["has_errors"]),
            **structural_checks,
        }
        completion_checks["accepted_completion_signal"] = bool(
            completion_checks["complete_process_present"]
            or (
                mode == "native_linux"
                and completion_checks["plan_information_present"]
                and completion_checks["unsteady_summary_present"]
            )
        )
        success = bool(
            completion_checks["accepted_completion_signal"]
            and completion_checks["no_compute_errors"]
            and completion_checks["plan_information_present"]
            and completion_checks["unsteady_summary_present"]
        )

        volume_errors = []
        if volume is not None and not volume.empty and "Error Percent" in volume:
            volume_errors = [
                float(value)
                for value in pd.to_numeric(volume["Error Percent"], errors="coerce").dropna()
            ]

        return {
            "path": str(path.resolve()),
            "file_sha256": RasQualification.file_sha256(path),
            "summary": summary_records,
            "volume_accounting": volume_records,
            "volume_error_percent": volume_errors,
            "max_abs_volume_error_percent": (
                max(abs(value) for value in volume_errors) if volume_errors else None
            ),
            "compute_messages_sha256": hashlib.sha256(compute_messages.encode("utf-8")).hexdigest(),
            "compute_messages_length": len(compute_messages),
            "completion_mode": mode,
            "compute_diagnostics": compute_diagnostics,
            "completion_checks": completion_checks,
            "successful": success,
        }

    @staticmethod
    @log_call
    def raster_receipt(raster_path: Union[str, Path]) -> Dict[str, Any]:
        """Inspect GeoTIFF grid metadata, values, validity, and content hashes."""
        try:
            import rasterio
        except ImportError as exc:
            raise ImportError("rasterio is required for raster qualification") from exc

        path = Path(raster_path)
        if not path.is_file():
            raise FileNotFoundError(f"Raster not found: {path}")

        with rasterio.open(path) as source:
            values = source.read(masked=True)
            valid = ~np.ma.getmaskarray(values)
            valid_values = np.asarray(values.data[valid], dtype=float)
            value_digest = hashlib.sha256()
            value_digest.update(np.ascontiguousarray(valid).tobytes())
            value_digest.update(np.ascontiguousarray(values.filled(0)).tobytes())
            stats = RasQualification._distribution(valid_values)
            stats["std"] = float(np.std(valid_values)) if len(valid_values) else None
            return {
                "path": str(path.resolve()),
                "file_sha256": RasQualification.file_sha256(path),
                "data_fingerprint": value_digest.hexdigest(),
                "driver": source.driver,
                "width": source.width,
                "height": source.height,
                "band_count": source.count,
                "dtypes": list(source.dtypes),
                "crs_wkt": source.crs.to_wkt() if source.crs else None,
                "transform": list(source.transform)[:6],
                "bounds": list(source.bounds),
                "nodata": _json_value(source.nodata),
                "valid_value_count": int(valid.sum()),
                "values": stats,
            }

    @staticmethod
    @log_call
    def terrain_receipt(
        terrain_hdf: Union[str, Path],
        source_rasters: Sequence[Union[str, Path]] = (),
    ) -> Dict[str, Any]:
        """Fingerprint HEC-RAS terrain outputs, pyramid content, and inputs.

        The primary raster fields in this receipt describe the GeoTIFFs written
        by HEC-RAS, not the source DEMs supplied to terrain creation.  This is
        important for native-versus-Wine qualification: identical inputs do not
        prove that terrain conversion and pyramid generation produced identical
        artifacts.
        """
        path = Path(terrain_hdf)
        if not path.is_file():
            raise FileNotFoundError(f"Terrain HDF not found: {path}")

        layer_levels: Dict[str, List[int]] = {}
        layer_priorities: Dict[str, Optional[int]] = {}
        raster_inventory: List[Dict[str, Any]] = []
        stitch_datasets: Dict[str, Dict[str, Any]] = {}
        with h5py.File(path, "r") as hdf:
            if "/Terrain" not in hdf:
                raise RuntimeError(f"Terrain group missing from {path}")
            terrain = hdf["/Terrain"]
            for dataset_name in RasQualification._TERRAIN_STITCH_DATASETS:
                item = terrain.get(dataset_name)
                if not isinstance(item, h5py.Dataset):
                    stitch_datasets[dataset_name] = {
                        "present": False,
                        "shape": None,
                        "count": None,
                        "dtype": None,
                        "fingerprint": None,
                    }
                    continue
                dataset_evidence = RasQualification._exact_dataset_evidence(item)
                shape = dataset_evidence["shape"]
                stitch_datasets[dataset_name] = {
                    "present": True,
                    "shape": shape,
                    "count": int(shape[0]) if shape else 1,
                    "dtype": dataset_evidence["dtype"],
                    "fingerprint": dataset_evidence["fingerprint"],
                }

            for layer_name, item in sorted(terrain.items(), key=lambda pair: pair[0]):
                if not isinstance(item, h5py.Group):
                    continue
                levels = sorted(int(key) for key in item.keys() if str(key).isdigit())
                if levels:
                    layer_levels[layer_name] = levels

                raw_priority = item.attrs.get("Priority")
                priority = (
                    int(_json_value(raw_priority))
                    if raw_priority is not None
                    else None
                )
                if levels or item.attrs.get("File") is not None:
                    layer_priorities[layer_name] = priority

                raw_file = _json_value(item.attrs.get("File"))
                if not raw_file:
                    continue
                file_value = str(raw_file)
                file_path = Path(file_value)
                candidates: List[Path] = []
                if file_path.is_absolute():
                    candidates.append(file_path)
                candidates.extend(
                    [
                        path.parent / file_value.replace("\\", os.sep),
                        path.parent / PureWindowsPath(file_value).name,
                    ]
                )
                output_raster = next((candidate for candidate in candidates if candidate.is_file()), None)
                if output_raster is None:
                    raise FileNotFoundError(
                        f"Terrain layer {layer_name!r} references missing output raster "
                        f"{file_value!r} beside {path}"
                    )
                raster_receipt = RasQualification.raster_receipt(output_raster)
                raster_inventory.append(
                    {
                        "layer": layer_name,
                        "priority": priority,
                        "hdf_file_reference": file_value,
                        **raster_receipt,
                    }
                )

        if not raster_inventory:
            raise RuntimeError(f"No HEC-RAS terrain output rasters were referenced by {path}")
        if not layer_levels:
            raise RuntimeError(f"No terrain pyramid levels were found in {path}")

        terrain_hdf_raw_fingerprint = RasQualification.canonical_hdf_fingerprint(
            path,
            roots=("/Terrain",),
        )
        terrain_hdf_fingerprint = RasQualification.terrain_hdf_semantic_fingerprint(path)
        combined = hashlib.sha256()
        combined.update(terrain_hdf_fingerprint.encode("ascii"))
        raw_combined = hashlib.sha256()
        raw_combined.update(terrain_hdf_raw_fingerprint.encode("ascii"))
        for raster in sorted(raster_inventory, key=lambda item: str(item["layer"])):
            combined.update(b"\x00")
            combined.update(str(raster["layer"]).encode("utf-8"))
            combined.update(b"\x00")
            combined.update(str(raster["data_fingerprint"]).encode("ascii"))
            raw_combined.update(b"\x00")
            raw_combined.update(str(raster["layer"]).encode("utf-8"))
            raw_combined.update(b"\x00")
            raw_combined.update(str(raster["data_fingerprint"]).encode("ascii"))

        source_receipts = [
            RasQualification.raster_receipt(source_raster)
            for source_raster in source_rasters
        ]
        primary = raster_inventory[0]
        return {
            "path": str(path.resolve()),
            "terrain_hdf_sha256": RasQualification.file_sha256(path),
            "terrain_hdf_fingerprint": terrain_hdf_fingerprint,
            "terrain_hdf_raw_fingerprint": terrain_hdf_raw_fingerprint,
            "data_fingerprint": combined.hexdigest(),
            "raw_data_fingerprint": raw_combined.hexdigest(),
            "layer_count": len(raster_inventory),
            "layer_priorities": layer_priorities,
            "pyramid_levels": layer_levels,
            "stitch_datasets": stitch_datasets,
            "raster_inventory": raster_inventory,
            "source_rasters": source_receipts,
            "driver": primary["driver"],
            "width": primary["width"],
            "height": primary["height"],
            "band_count": primary["band_count"],
            "dtypes": primary["dtypes"],
            "crs_wkt": primary["crs_wkt"],
            "transform": primary["transform"],
            "bounds": primary["bounds"],
            "nodata": primary["nodata"],
            "valid_value_count": primary["valid_value_count"],
            "values": primary["values"],
        }

    @staticmethod
    @log_call
    def extract_result_series(
        plan_hdf: Union[str, Path],
        specifications: Mapping[str, Mapping[str, Any]],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Extract deterministic hydrograph and mesh result series for parity.

        ``profile_line_flow`` specifications produce an engineering hydrograph
        through the product-backed RAS Mapper profile-line API. ``mesh_cells``
        specifications select explicit cell or face IDs from one plan-HDF time
        series.  Explicit feature IDs are required so a parity run cannot pass
        by silently comparing a different spatial sample.
        """
        from .hdf import HdfResultsMesh

        path = Path(plan_hdf)
        if not path.is_file():
            raise FileNotFoundError(f"Plan HDF not found: {path}")
        if not isinstance(specifications, Mapping) or not specifications:
            raise ValueError("At least one named result-series specification is required")

        extracted: Dict[str, Dict[str, Any]] = {}

        def _apply_time_window(
            frame: pd.DataFrame,
            specification: Mapping[str, Any],
            series_name: str,
        ) -> pd.DataFrame:
            start_value = specification.get("start_time")
            end_value = specification.get("end_time")
            if start_value is None and end_value is None:
                return frame
            if "time" not in frame.columns:
                raise RuntimeError(
                    f"Series {series_name!r} cannot apply a time window without a time column"
                )
            times = pd.to_datetime(frame["time"], errors="coerce")
            if times.isna().any():
                raise RuntimeError(
                    f"Series {series_name!r} contains unparseable timestamps"
                )
            selected = pd.Series(True, index=frame.index)
            if start_value is not None:
                selected &= times >= pd.Timestamp(start_value)
            if end_value is not None:
                selected &= times <= pd.Timestamp(end_value)
            filtered = frame.loc[selected].reset_index(drop=True)
            if filtered.empty:
                raise RuntimeError(
                    f"Series {series_name!r} time window produced no records"
                )
            return filtered

        for series_name, specification in specifications.items():
            if not isinstance(specification, Mapping):
                raise TypeError(f"Series specification {series_name!r} must be a mapping")
            kind = str(specification.get("kind", "")).strip().lower()
            if kind == "profile_line_flow":
                line_name = str(specification.get("line_name", "")).strip()
                if not line_name:
                    raise ValueError(f"Series {series_name!r} requires line_name")
                extraction_backend = str(
                    specification.get("extraction_backend", "rasmapper")
                ).strip().lower()
                profile_arguments = {
                    "line_name": line_name,
                    "mesh_name": specification.get("mesh_name"),
                    "profile_lines_path": specification.get("profile_lines_path"),
                    "direction": str(specification.get("direction", "absolute")),
                    "truncate": bool(specification.get("truncate", False)),
                    "ras_object": ras_object,
                }
                if extraction_backend in {"hdf", "pure_python", "legacy"}:
                    frame = HdfResultsMesh.get_profile_line_flow_timeseries_legacy(
                        path,
                        **profile_arguments,
                    )
                    extraction_backend = "pure_python_hdf"
                elif extraction_backend in {"rasmapper", "product"}:
                    frame = HdfResultsMesh.get_profile_line_flow_timeseries(
                        path,
                        **profile_arguments,
                    )
                    extraction_backend = "rasmapper"
                else:
                    raise ValueError(
                        f"Series {series_name!r} has unsupported extraction_backend "
                        f"{extraction_backend!r}"
                    )
                frame = _apply_time_window(frame, specification, str(series_name))
                if frame.empty or not {"time", "flow"}.issubset(frame.columns):
                    raise RuntimeError(
                        f"Profile-line series {series_name!r} produced no time/flow records"
                    )
                finite_flow = pd.to_numeric(frame["flow"], errors="coerce")
                if not finite_flow.notna().any():
                    raise RuntimeError(
                        f"Profile-line series {series_name!r} contains no numeric flow values"
                    )
                extracted[str(series_name)] = {
                    "kind": kind,
                    "line_name": line_name,
                    "mesh_name": specification.get("mesh_name"),
                    "direction": str(specification.get("direction", "absolute")),
                    "extraction_backend": extraction_backend,
                    "start_time": _json_value(specification.get("start_time")),
                    "end_time": _json_value(specification.get("end_time")),
                    "units": _json_value(frame.attrs.get("units")),
                    "value_columns": ["flow"],
                    "records": _frame_records(frame),
                }
                continue

            if kind == "mesh_cells":
                mesh_name = str(specification.get("mesh_name", "")).strip()
                variable = str(specification.get("variable", "")).strip()
                if not mesh_name or not variable:
                    raise ValueError(
                        f"Series {series_name!r} requires mesh_name and variable"
                    )
                array = HdfResultsMesh.get_mesh_timeseries(
                    path,
                    mesh_name=mesh_name,
                    var=variable,
                    truncate=False,
                )
                entity_dimensions = [dimension for dimension in array.dims if dimension != "time"]
                if len(entity_dimensions) != 1:
                    raise RuntimeError(
                        f"Mesh series {series_name!r} must have time plus one entity dimension; "
                        f"found {list(array.dims)}"
                    )
                entity_dimension = entity_dimensions[0]
                ids_value = specification.get("entity_ids")
                if ids_value is None:
                    ids_value = specification.get(entity_dimension + "s")
                if not isinstance(ids_value, Sequence) or isinstance(ids_value, (str, bytes)):
                    raise ValueError(
                        f"Series {series_name!r} requires explicit {entity_dimension}s"
                    )
                entity_ids = [int(value) for value in ids_value]
                if not entity_ids:
                    raise ValueError(
                        f"Series {series_name!r} requires at least one {entity_dimension}"
                    )
                available_ids = {int(value) for value in array.coords[entity_dimension].values.tolist()}
                missing_ids = [value for value in entity_ids if value not in available_ids]
                if missing_ids:
                    raise ValueError(
                        f"Series {series_name!r} requested missing {entity_dimension}s: {missing_ids}"
                    )
                value_column = str(
                    specification.get(
                        "value_column",
                        "wse" if variable.strip().lower() == "water surface" else "value",
                    )
                ).strip()
                if not value_column:
                    raise ValueError(f"Series {series_name!r} requires a non-empty value_column")
                selected = array.sel({entity_dimension: entity_ids})
                frame = selected.to_dataframe(name=value_column).reset_index()
                frame["mesh_name"] = mesh_name
                frame = _apply_time_window(frame, specification, str(series_name))
                finite_values = pd.to_numeric(frame[value_column], errors="coerce")
                if frame.empty or not finite_values.notna().any():
                    raise RuntimeError(
                        f"Mesh series {series_name!r} contains no numeric {value_column} values"
                    )
                extracted[str(series_name)] = {
                    "kind": kind,
                    "mesh_name": mesh_name,
                    "variable": variable,
                    "entity_dimension": entity_dimension,
                    "entity_ids": entity_ids,
                    "start_time": _json_value(specification.get("start_time")),
                    "end_time": _json_value(specification.get("end_time")),
                    "units": _json_value(array.attrs.get("units")),
                    "value_columns": [value_column],
                    "records": _frame_records(frame),
                }
                continue

            raise ValueError(
                f"Series {series_name!r} has unsupported kind {kind!r}; expected "
                "'profile_line_flow' or 'mesh_cells'"
            )
        return extracted

    @staticmethod
    @log_call
    def compare_numeric_frames(
        native: pd.DataFrame,
        wine: pd.DataFrame,
        key_columns: Sequence[str],
        tolerances: Mapping[str, Union[NumericTolerance, Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        """Compare keyed hydrograph/WSE frames with explicit per-column limits."""
        missing_columns = [
            column
            for column in [*key_columns, *tolerances.keys()]
            if column not in native.columns or column not in wine.columns
        ]
        if missing_columns:
            raise ValueError(f"Comparison columns missing from one or both frames: {sorted(set(missing_columns))}")
        if native.duplicated(list(key_columns)).any() or wine.duplicated(list(key_columns)).any():
            raise ValueError("Numeric parity keys must be unique in both frames")

        native_keys = native[list(key_columns)].copy()
        wine_keys = wine[list(key_columns)].copy()
        native_key_set = {tuple(_json_value(value) for value in row) for row in native_keys.itertuples(index=False, name=None)}
        wine_key_set = {tuple(_json_value(value) for value in row) for row in wine_keys.itertuples(index=False, name=None)}
        keys_match = native_key_set == wine_key_set

        merged = native.merge(wine, on=list(key_columns), how="inner", suffixes=("_native", "_wine"))
        columns: Dict[str, Dict[str, Any]] = {}
        for column, tolerance_value in tolerances.items():
            tolerance = (
                tolerance_value
                if isinstance(tolerance_value, NumericTolerance)
                else NumericTolerance(**dict(tolerance_value))
            )
            left = pd.to_numeric(merged[f"{column}_native"], errors="coerce").to_numpy(dtype=float)
            right = pd.to_numeric(merged[f"{column}_wine"], errors="coerce").to_numpy(dtype=float)
            nan_mismatch = int(np.logical_xor(np.isnan(left), np.isnan(right)).sum())
            valid = np.isfinite(left) & np.isfinite(right)
            difference = right[valid] - left[valid]
            max_abs = float(np.max(np.abs(difference))) if len(difference) else None
            rmse = float(np.sqrt(np.mean(np.square(difference)))) if len(difference) else None
            peak_relative = None
            if len(difference):
                native_peak = float(np.max(np.abs(left[valid])))
                wine_peak = float(np.max(np.abs(right[valid])))
                peak_relative = abs(wine_peak - native_peak) / max(native_peak, np.finfo(float).eps)
            passed = (
                nan_mismatch == 0
                and max_abs is not None
                and rmse is not None
                and max_abs <= tolerance.max_abs
                and rmse <= tolerance.rmse
                and (
                    tolerance.peak_relative is None
                    or (peak_relative is not None and peak_relative <= tolerance.peak_relative)
                )
            )
            columns[column] = {
                "sample_count": int(valid.sum()),
                "nan_mismatch_count": nan_mismatch,
                "max_abs": max_abs,
                "rmse": rmse,
                "peak_relative": peak_relative,
                "tolerance": asdict(tolerance),
                "passed": passed,
            }

        return {
            "keys_match": keys_match,
            "native_key_count": len(native_key_set),
            "wine_key_count": len(wine_key_set),
            "missing_from_wine": sorted(native_key_set - wine_key_set, key=str),
            "missing_from_native": sorted(wine_key_set - native_key_set, key=str),
            "columns": columns,
            "passed": keys_match and bool(columns) and all(item["passed"] for item in columns.values()),
        }

    @staticmethod
    @log_call
    def compare_rasters(
        native_raster: Union[str, Path],
        wine_raster: Union[str, Path],
        tolerance: Union[RasterTolerance, Mapping[str, Any]],
        *,
        require_same_grid: bool = True,
        require_wet_overlap: bool = False,
        exact_short_circuit: bool = True,
        enforce_valid_overlap: bool = True,
    ) -> Dict[str, Any]:
        """Compare all bands of two map rasters, trying exact parity first.

        The production qualification path requires dimensions, CRS, transform,
        and band count to match exactly.  Values that are not bit-for-bit equal
        can still pass the explicit numeric and valid-mask overlap tolerances.
        The compatibility switches are used only by ``compare_depth_rasters``
        to retain its historical reproject-to-native-grid behavior.
        """
        try:
            import rasterio
            from rasterio.enums import Resampling
            from rasterio.warp import reproject
        except ImportError as exc:
            raise ImportError("rasterio is required for raster parity comparison") from exc

        limits = (
            tolerance
            if isinstance(tolerance, RasterTolerance)
            else RasterTolerance(**dict(tolerance))
        )
        resampling_options = {
            "nearest": Resampling.nearest,
            "bilinear": Resampling.bilinear,
        }
        with rasterio.open(native_raster) as native_source, rasterio.open(wine_raster) as wine_source:
            if native_source.crs is None or wine_source.crs is None:
                raise ValueError("Both map rasters must have a CRS")
            native_values = native_source.read(masked=True).astype(np.float64)
            wine_values = wine_source.read(masked=True).astype(np.float64)
            native_array = np.asarray(native_values.filled(np.nan), dtype=float)
            source_wine_array = np.asarray(wine_values.filled(np.nan), dtype=float)
            native_valid = ~np.ma.getmaskarray(native_values)
            source_wine_valid = ~np.ma.getmaskarray(wine_values)

            dimensions_exact = (
                native_source.width,
                native_source.height,
                native_source.count,
            ) == (
                wine_source.width,
                wine_source.height,
                wine_source.count,
            )
            crs_exact = native_source.crs == wine_source.crs
            transform_exact = native_source.transform == wine_source.transform
            dtype_exact = tuple(native_source.dtypes) == tuple(wine_source.dtypes)
            band_count_exact = native_source.count == wine_source.count
            same_grid = dimensions_exact and crs_exact and transform_exact
            if same_grid:
                wine_on_native = source_wine_array
                wine_valid = source_wine_valid
            else:
                native_shape = (
                    native_source.count,
                    native_source.height,
                    native_source.width,
                )
                wine_on_native = np.full(native_shape, np.nan, dtype=np.float64)
                wine_valid = np.zeros(native_shape, dtype=bool)
                for band_index in range(min(native_source.count, wine_source.count)):
                    reproject(
                        source=source_wine_array[band_index],
                        destination=wine_on_native[band_index],
                        src_transform=wine_source.transform,
                        src_crs=wine_source.crs,
                        src_nodata=np.nan,
                        dst_transform=native_source.transform,
                        dst_crs=native_source.crs,
                        dst_nodata=np.nan,
                        resampling=resampling_options[limits.resampling],
                    )
                    wine_valid_uint8 = np.zeros(
                        (native_source.height, native_source.width),
                        dtype=np.uint8,
                    )
                    reproject(
                        source=source_wine_valid[band_index].astype(np.uint8),
                        destination=wine_valid_uint8,
                        src_transform=wine_source.transform,
                        src_crs=wine_source.crs,
                        src_nodata=0,
                        dst_transform=native_source.transform,
                        dst_crs=native_source.crs,
                        dst_nodata=0,
                        resampling=Resampling.nearest,
                    )
                    wine_valid[band_index] = wine_valid_uint8.astype(bool)

            valid_union = native_valid | wine_valid
            valid_intersection = native_valid & wine_valid
            valid_union_count = int(valid_union.sum())
            valid_mask_overlap = (
                float(valid_intersection.sum() / valid_union_count)
                if valid_union_count
                else None
            )
            valid_mask_exact = same_grid and np.array_equal(native_valid, wine_valid)
            values_exact = bool(
                valid_mask_exact
                and np.array_equal(
                    native_array[native_valid],
                    wine_on_native[wine_valid],
                )
            )
            exact_match = bool(
                same_grid
                and dtype_exact
                and valid_mask_exact
                and values_exact
            )

            native_wet = native_valid & (native_array > limits.wet_threshold)
            wine_wet = wine_valid & (wine_on_native > limits.wet_threshold)
            wet_union = native_wet | wine_wet
            wet_intersection = native_wet & wine_wet
            wet_union_count = int(wet_union.sum())
            wet_overlap = (
                float(wet_intersection.sum() / wet_union_count)
                if wet_union_count
                else None
            )

            comparable = native_valid & wine_valid & np.isfinite(native_array) & np.isfinite(wine_on_native)
            differences = wine_on_native[comparable] - native_array[comparable]
            max_abs = float(np.max(np.abs(differences))) if len(differences) else None
            rmse = float(np.sqrt(np.mean(np.square(differences)))) if len(differences) else None
            p95_abs = float(np.percentile(np.abs(differences), 95)) if len(differences) else None
            wet_comparable = comparable & wet_union
            wet_differences = wine_on_native[wet_comparable] - native_array[wet_comparable]
            wet_max_abs = (
                float(np.max(np.abs(wet_differences))) if len(wet_differences) else None
            )
            wet_rmse = (
                float(np.sqrt(np.mean(np.square(wet_differences))))
                if len(wet_differences)
                else None
            )
            wet_p95_abs = (
                float(np.percentile(np.abs(wet_differences), 95))
                if len(wet_differences)
                else None
            )
            wet_comparable_count = int(wet_comparable.sum())
            valid_overlap_passed = bool(
                valid_mask_overlap is not None
                and valid_mask_overlap >= limits.minimum_valid_overlap
            )
            wet_overlap_passed = bool(
                native_wet.any()
                and wine_wet.any()
                and wet_overlap is not None
                and wet_overlap >= limits.minimum_wet_overlap
                and wet_comparable_count == wet_union_count
            )
            tolerance_passed = bool(
                max_abs is not None
                and rmse is not None
                and max_abs <= limits.max_abs
                and rmse <= limits.rmse
                and band_count_exact
                and (same_grid or not require_same_grid)
                and (valid_overlap_passed or not enforce_valid_overlap)
                and (
                    not require_wet_overlap
                    or (
                        wet_overlap_passed
                        and wet_max_abs is not None
                        and wet_rmse is not None
                        and wet_max_abs <= limits.max_abs
                        and wet_rmse <= limits.rmse
                    )
                )
            )
            passed = bool(
                (exact_short_circuit and exact_match)
                or tolerance_passed
            )

            return {
                "native_dimensions": {
                    "width": native_source.width,
                    "height": native_source.height,
                    "band_count": native_source.count,
                },
                "wine_dimensions": {
                    "width": wine_source.width,
                    "height": wine_source.height,
                    "band_count": wine_source.count,
                },
                "native_crs_wkt": native_source.crs.to_wkt(),
                "wine_crs_wkt": wine_source.crs.to_wkt(),
                "native_transform": list(native_source.transform)[:6],
                "wine_transform": list(wine_source.transform)[:6],
                "native_dtypes": list(native_source.dtypes),
                "wine_dtypes": list(wine_source.dtypes),
                "dimensions_exact": dimensions_exact,
                "crs_exact": crs_exact,
                "transform_exact": transform_exact,
                "dtype_exact": dtype_exact,
                "same_grid": same_grid,
                "native_valid_count": int(native_valid.sum()),
                "wine_valid_count_on_native_grid": int(wine_valid.sum()),
                "valid_intersection_count": int(valid_intersection.sum()),
                "valid_union_count": valid_union_count,
                "valid_mask_overlap": valid_mask_overlap,
                "valid_mask_exact": valid_mask_exact,
                "comparable_count": int(comparable.sum()),
                "native_wet_count": int(native_wet.sum()),
                "wine_wet_count": int(wine_wet.sum()),
                "wet_intersection_count": int(wet_intersection.sum()),
                "wet_union_count": wet_union_count,
                "wet_comparable_count": wet_comparable_count,
                "wet_overlap": wet_overlap,
                "max_abs": max_abs,
                "p95_abs": p95_abs,
                "rmse": rmse,
                "wet_max_abs": wet_max_abs,
                "wet_p95_abs": wet_p95_abs,
                "wet_rmse": wet_rmse,
                "values_exact": values_exact,
                "exact_match": exact_match,
                "valid_overlap_passed": valid_overlap_passed,
                "wet_overlap_passed": wet_overlap_passed,
                "tolerance_passed": tolerance_passed,
                "comparison_mode": (
                    "exact"
                    if exact_match
                    else "tolerance"
                    if tolerance_passed
                    else "failed"
                ),
                "tolerance": asdict(limits),
                "passed": passed,
            }

    @staticmethod
    @log_call
    def compare_depth_rasters(
        native_raster: Union[str, Path],
        wine_raster: Union[str, Path],
        tolerance: Union[RasterTolerance, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Compare depth rasters using the historical aligned-grid contract."""
        return RasQualification.compare_rasters(
            native_raster,
            wine_raster,
            tolerance,
            require_same_grid=False,
            require_wet_overlap=True,
            exact_short_circuit=False,
            enforce_valid_overlap=False,
        )

    @staticmethod
    @log_call
    def validate_run_receipt(
        receipt: Mapping[str, Any],
        expected_profile: Optional[Union[str, ExecutorProfile]] = None,
        expected_version: str = "7.0.1",
    ) -> Dict[str, Any]:
        """Fail closed on missing, failed, or skipped critical operations."""
        profile = str(receipt.get("executor_profile", ""))
        if isinstance(expected_profile, ExecutorProfile):
            expected_profile = expected_profile.value
        expected = RasUtils.normalize_ras_version(expected_version)
        installation_value = receipt.get("installation") or {}
        installation = installation_value if isinstance(installation_value, Mapping) else {}
        detected = RasUtils.normalize_ras_version(installation.get("detected_version"))

        operations = {
            str(item.get("id")): item
            for item in receipt.get("operations", [])
            if isinstance(item, Mapping) and item.get("id")
        }
        not_applicable = RasQualification._PROFILE_NOT_APPLICABLE.get(profile, set())
        missing: List[str] = []
        failed: List[str] = []
        skipped: List[str] = []
        evidence_missing: List[str] = []
        invalid_not_applicable: List[str] = []
        diagnostic_failures: List[str] = []

        for operation_id in RasQualification.REQUIRED_OPERATIONS:
            operation = operations.get(operation_id)
            if operation is None:
                missing.append(operation_id)
                continue
            status = str(operation.get("status", "")).lower()
            if status == "skipped":
                skipped.append(operation_id)
            elif status == "not_applicable":
                if operation_id not in not_applicable:
                    invalid_not_applicable.append(operation_id)
            elif status != "passed":
                failed.append(operation_id)
            elif not operation.get("evidence"):
                evidence_missing.append(operation_id)

        for operation_id in RasQualification.DIAGNOSTIC_OPERATIONS:
            operation = operations.get(operation_id)
            if operation is not None and str(operation.get("status", "")).lower() != "passed":
                diagnostic_failures.append(operation_id)

        artifacts_value = receipt.get("artifacts") or {}
        artifacts = artifacts_value if isinstance(artifacts_value, Mapping) else {}
        missing_artifacts = [name for name in ("geometry", "terrain", "results") if not artifacts.get(name)]
        components_value = installation.get("components") or {}
        components = components_value if isinstance(components_value, Mapping) else {}
        required_components = {
            "ras",
            "rasprocess",
            "rasmapperlib",
            "ras_geom_preprocess",
            "ras_unsteady",
        }
        component_identity_present = required_components.issubset(components) and all(
            isinstance(components.get(name), Mapping)
            and bool(components[name].get("exists"))
            and bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(components[name].get("sha256", ""))))
            for name in required_components
        )
        expected_architectures = {
            "ras": "x86",
            "rasprocess": "x86",
            "rasmapperlib": "x86",
            "ras_geom_preprocess": "x64",
            "ras_unsteady": "x64",
        }
        component_architecture_valid = (
            required_components.issubset(components)
            and all(
                isinstance(components.get(name), Mapping)
                and isinstance(components[name].get("pe"), Mapping)
                and components[name]["pe"].get("valid_pe") is True
                and components[name]["pe"].get("architecture") == architecture
                for name, architecture in expected_architectures.items()
            )
        )

        geometry_value = artifacts.get("geometry") or {}
        geometry = geometry_value if isinstance(geometry_value, Mapping) else {}
        areas_value = geometry.get("areas") or {}
        areas = areas_value if isinstance(areas_value, Mapping) else {}
        geometry_content_complete = (
            bool(geometry.get("geometry_fingerprint"))
            and bool(areas)
            and bool(geometry.get("boundary_assignments"))
            and int(geometry.get("breakline_count", 0)) > 0
            and int(geometry.get("refinement_region_count", 0)) > 0
            and all(
                isinstance(area, Mapping)
                and int(area.get("cell_count", 0)) > 0
                and int(area.get("face_count", 0)) > 0
                and bool(area.get("face_property_complete"))
                and bool(area.get("cell_property_complete"))
                and isinstance(area.get("quality"), Mapping)
                and int((area.get("quality") or {}).get("invalid_cell_count", -1)) == 0
                for area in areas.values()
            )
        )
        terrain_value = artifacts.get("terrain") or {}
        terrain = terrain_value if isinstance(terrain_value, Mapping) else {}
        terrain_inventory = terrain.get("raster_inventory") or []
        terrain_pyramids = terrain.get("pyramid_levels") or {}
        terrain_content_complete = (
            bool(terrain.get("data_fingerprint"))
            and bool(terrain.get("terrain_hdf_fingerprint"))
            and int(terrain.get("layer_count", 0)) > 0
            and isinstance(terrain_inventory, Sequence)
            and not isinstance(terrain_inventory, (str, bytes))
            and len(terrain_inventory) == int(terrain.get("layer_count", 0))
            and all(
                isinstance(item, Mapping)
                and bool(item.get("data_fingerprint"))
                and bool(item.get("crs_wkt"))
                and int(item.get("width", 0)) > 0
                and int(item.get("height", 0)) > 0
                for item in terrain_inventory
            )
            and isinstance(terrain_pyramids, Mapping)
            and bool(terrain_pyramids)
            and all(bool(levels) for levels in terrain_pyramids.values())
            and bool(terrain.get("crs_wkt"))
            and int(terrain.get("width", 0)) > 0
            and int(terrain.get("height", 0)) > 0
            and int(terrain.get("band_count", 0)) > 0
        )
        mesh_exact_count_checks: Dict[str, bool] = {}
        for operation_id in (
            "mesh.generate_initial",
            "mesh.regenerate",
            "mesh.refinement_region",
            "mesh.breakline",
        ):
            operation = operations.get(operation_id) or {}
            evidence_value = operation.get("evidence") or {}
            evidence = (
                evidence_value if isinstance(evidence_value, Mapping) else {}
            )
            check_key = (
                "mesh_count_checks"
                if operation_id == "mesh.breakline"
                else "count_checks"
            )
            count_value = evidence.get(check_key) or {}
            count_checks = count_value if isinstance(count_value, Mapping) else {}
            mesh_exact_count_checks[operation_id] = bool(
                evidence.get("expected_cell_count") is not None
                and evidence.get("expected_face_count") is not None
                and count_checks.get("expected_cells") is True
                and count_checks.get("expected_faces") is True
            )
        results_value = artifacts.get("results") or {}
        results = results_value if isinstance(results_value, Mapping) else {}
        series_value = receipt.get("series") or {}
        series = series_value if isinstance(series_value, Mapping) else {}

        def _records_are_complete(item: Any, value_column: str) -> bool:
            if not isinstance(item, Mapping):
                return False
            records = item.get("records") or []
            return bool(records) and all(
                isinstance(record, Mapping)
                and record.get("time") is not None
                and record.get(value_column) is not None
                for record in records
            )

        hydrograph_series = [
            name
            for name, item in series.items()
            if isinstance(item, Mapping)
            and item.get("kind") == "profile_line_flow"
            and _records_are_complete(item, "flow")
        ]
        wse_series = []
        for name, item in series.items():
            if not isinstance(item, Mapping) or item.get("kind") != "mesh_cells":
                continue
            value_columns = item.get("value_columns") or []
            is_wse = str(item.get("variable", "")).strip().lower() == "water surface"
            if is_wse and len(value_columns) == 1 and _records_are_complete(item, str(value_columns[0])):
                wse_series.append(name)
        checks = {
            "schema_matches": receipt.get("schema_version") == RasQualification.SCHEMA_VERSION,
            "profile_matches": expected_profile is None or profile == str(expected_profile),
            "production_profile": profile in {
                ExecutorProfile.WINDOWS_NATIVE.value,
                ExecutorProfile.LINUX_WINE_WINDOWS_RAS.value,
            },
            "version_matches": detected == expected,
            "installation_declares_version_match": installation.get("version_matches") is True,
            "required_components_present": installation.get("required_components_present") is True,
            "component_identity_present": component_identity_present,
            "component_architecture_valid": component_architecture_valid,
            "no_missing_operations": not missing,
            "no_failed_operations": not failed,
            "no_skipped_critical_operations": not skipped,
            "no_missing_operation_evidence": not evidence_missing,
            "not_applicable_is_valid": not invalid_not_applicable,
            "required_artifacts_present": not missing_artifacts,
            "geometry_content_complete": geometry_content_complete,
            "mesh_exact_counts_configured": bool(mesh_exact_count_checks)
            and all(mesh_exact_count_checks.values()),
            "terrain_content_complete": terrain_content_complete,
            "results_successful": results.get("successful") is True,
            "hydrograph_wse_series_present": bool(hydrograph_series) and bool(wse_series),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "profile": profile,
            "expected_version": expected,
            "detected_version": detected,
            "missing_operations": missing,
            "failed_operations": failed,
            "skipped_critical_operations": skipped,
            "missing_operation_evidence": evidence_missing,
            "invalid_not_applicable": invalid_not_applicable,
            "missing_artifacts": missing_artifacts,
            "mesh_exact_count_checks": mesh_exact_count_checks,
            "hydrograph_series": hydrograph_series,
            "wse_series": wse_series,
            "diagnostic_failures": diagnostic_failures,
        }

    @staticmethod
    def _geometry_parity(native: Mapping[str, Any], wine: Mapping[str, Any]) -> Dict[str, Any]:
        native_areas = native.get("areas") or {}
        wine_areas = wine.get("areas") or {}
        exact_area_names = set(native_areas) == set(wine_areas)
        area_checks: Dict[str, Dict[str, Any]] = {}
        for name in sorted(set(native_areas) | set(wine_areas)):
            left = native_areas.get(name) or {}
            right = wine_areas.get(name) or {}
            checks = {
                "cell_count": left.get("cell_count") == right.get("cell_count"),
                "face_count": left.get("face_count") == right.get("face_count"),
                "face_property_table_ids": left.get("face_property_table_ids") == right.get("face_property_table_ids"),
                "cell_property_table_ids": left.get("cell_property_table_ids") == right.get("cell_property_table_ids"),
                "face_property_complete_native": bool(left.get("face_property_complete")),
                "face_property_complete_wine": bool(right.get("face_property_complete")),
                "cell_property_complete_native": bool(left.get("cell_property_complete")),
                "cell_property_complete_wine": bool(right.get("cell_property_complete")),
                "quality_metrics_exact": left.get("quality") == right.get("quality"),
                "native_invalid_cells_zero": int((left.get("quality") or {}).get("invalid_cell_count", -1)) == 0,
                "wine_invalid_cells_zero": int((right.get("quality") or {}).get("invalid_cell_count", -1)) == 0,
            }
            area_checks[name] = {"checks": checks, "passed": all(checks.values())}

        checks = {
            "area_names_exact": exact_area_names,
            "geometry_fingerprint_exact": native.get("geometry_fingerprint") == wine.get("geometry_fingerprint"),
            "boundary_assignments_exact": native.get("boundary_assignments") == wine.get("boundary_assignments"),
            "breakline_count_exact": native.get("breakline_count") == wine.get("breakline_count"),
            "refinement_region_count_exact": native.get("refinement_region_count") == wine.get("refinement_region_count"),
            "area_content_exact": bool(area_checks) and all(item["passed"] for item in area_checks.values()),
        }
        return {"passed": all(checks.values()), "checks": checks, "areas": area_checks}

    @staticmethod
    def _map_rasters_by_type(
        artifacts: Mapping[str, Any],
    ) -> Dict[str, List[Any]]:
        """Normalize keyed map-raster artifacts and the legacy depth alias."""
        keyed_value = artifacts.get("map_rasters_by_type")
        if not isinstance(keyed_value, Mapping):
            # Accept a keyed ``map_rasters`` value from early draft receipts,
            # while retaining the historical flat-list meaning of that field.
            map_rasters_value = artifacts.get("map_rasters")
            keyed_value = (
                map_rasters_value
                if isinstance(map_rasters_value, Mapping)
                else {}
            )

        normalized: Dict[str, List[Any]] = {}
        for raw_map_type, raw_receipts in keyed_value.items():
            map_type = str(raw_map_type).strip().lower()
            if not map_type:
                continue
            if isinstance(raw_receipts, Mapping):
                receipts = [raw_receipts]
            elif isinstance(raw_receipts, Sequence) and not isinstance(
                raw_receipts,
                (str, bytes),
            ):
                receipts = list(raw_receipts)
            else:
                receipts = []
            normalized.setdefault(map_type, []).extend(receipts)

        legacy_depth = artifacts.get("depth_grid")
        if "depth" not in normalized and isinstance(legacy_depth, Mapping):
            normalized["depth"] = [legacy_depth]
        return normalized

    @staticmethod
    def _map_raster_name(receipt: Any) -> Optional[str]:
        """Return a platform-neutral output filename used to pair rasters."""
        if not isinstance(receipt, Mapping) or not receipt.get("path"):
            return None
        parts = re.split(r"[\\/]", str(receipt["path"]))
        name = parts[-1].strip().casefold() if parts else ""
        return name or None

    @staticmethod
    def _map_raster_receipt_complete(receipt: Any, *, strict: bool) -> bool:
        """Require full content evidence for canonical keyed artifacts."""
        if not isinstance(receipt, Mapping) or not receipt.get("path"):
            return False
        if not strict:
            return True
        try:
            return bool(
                receipt.get("driver") == "GTiff"
                and receipt.get("file_sha256")
                and receipt.get("data_fingerprint")
                and receipt.get("crs_wkt")
                and len(receipt.get("transform") or []) == 6
                and int(receipt.get("width", 0)) > 0
                and int(receipt.get("height", 0)) > 0
                and int(receipt.get("band_count", 0)) > 0
                and int(receipt.get("valid_value_count", 0)) > 0
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _map_raster_type_parity(
        map_type: str,
        native_receipts: Sequence[Any],
        wine_receipts: Sequence[Any],
        tolerance: Optional[Union[RasterTolerance, Mapping[str, Any]]],
        *,
        native_strict: bool,
        wine_strict: bool,
    ) -> Dict[str, Any]:
        """Pair and compare every raster receipt for one requested map type."""
        native_index: Dict[str, Mapping[str, Any]] = {}
        wine_index: Dict[str, Mapping[str, Any]] = {}
        native_index_errors: List[str] = []
        wine_index_errors: List[str] = []

        for side_name, receipts, index, errors in (
            ("native", native_receipts, native_index, native_index_errors),
            ("wine", wine_receipts, wine_index, wine_index_errors),
        ):
            for position, receipt in enumerate(receipts):
                name = RasQualification._map_raster_name(receipt)
                if name is None:
                    errors.append(f"{side_name}[{position}] has no raster path")
                    continue
                if name in index:
                    errors.append(
                        f"{side_name} contains duplicate raster filename {name!r}"
                    )
                    continue
                if not isinstance(receipt, Mapping):
                    errors.append(f"{side_name}[{position}] is not a receipt mapping")
                    continue
                index[name] = receipt

        legacy_single_pair = bool(
            not native_strict
            and not wine_strict
            and len(native_receipts) == 1
            and len(wine_receipts) == 1
            and len(native_index) == 1
            and len(wine_index) == 1
            and not native_index_errors
            and not wine_index_errors
        )
        if legacy_single_pair:
            # Historical ``depth_grid`` receipts carried only a path, and
            # callers commonly used side-specific filenames. Pair those sole
            # artifacts positionally; canonical keyed receipts remain strict.
            native_index = {map_type: next(iter(native_index.values()))}
            wine_index = {map_type: next(iter(wine_index.values()))}

        native_names = set(native_index)
        wine_names = set(wine_index)
        names_exact = native_names == wine_names
        comparisons: Dict[str, Dict[str, Any]] = {}
        for name in sorted(native_names & wine_names):
            if tolerance is None:
                comparisons[name] = {
                    "passed": False,
                    "reason": f"No tolerance configured for map type {map_type!r}",
                }
                continue
            try:
                comparisons[name] = RasQualification.compare_rasters(
                    native_index[name]["path"],
                    wine_index[name]["path"],
                    tolerance,
                    require_same_grid=True,
                    require_wet_overlap=map_type == "depth",
                )
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                comparisons[name] = {
                    "passed": False,
                    "reason": str(exc),
                    "error_type": type(exc).__name__,
                }

        checks = {
            "native_receipts_present": bool(native_receipts),
            "wine_receipts_present": bool(wine_receipts),
            "receipt_counts_exact": len(native_receipts) == len(wine_receipts),
            "native_receipts_complete": bool(native_receipts)
            and all(
                RasQualification._map_raster_receipt_complete(
                    item,
                    strict=native_strict,
                )
                for item in native_receipts
            ),
            "wine_receipts_complete": bool(wine_receipts)
            and all(
                RasQualification._map_raster_receipt_complete(
                    item,
                    strict=wine_strict,
                )
                for item in wine_receipts
            ),
            "receipt_names_exact": bool(native_names) and names_exact,
            "receipt_names_unique": not native_index_errors
            and not wine_index_errors,
            "tolerance_configured": tolerance is not None,
            "every_raster_compared": bool(comparisons)
            and len(comparisons) == len(native_receipts) == len(wine_receipts),
            "every_raster_passed": bool(comparisons)
            and all(item.get("passed") is True for item in comparisons.values()),
        }
        return {
            "map_type": map_type,
            "native_raster_names": sorted(native_names),
            "wine_raster_names": sorted(wine_names),
            "native_index_errors": native_index_errors,
            "wine_index_errors": wine_index_errors,
            "checks": checks,
            "rasters": comparisons,
            "passed": all(checks.values()),
        }

    @staticmethod
    @log_call
    def compare_compute_receipts(
        reference_receipt: Mapping[str, Any],
        candidate_receipt: Mapping[str, Any],
        tolerances: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Compare completed solver results without requiring a full mapper run.

        This focused comparison is intended for official native-Linux versus
        Windows/Wine solver qualification after both lanes consume the same
        preprocessed model.  It requires successful result receipts, bounded
        volume accounting, exact series definitions and keys, and explicit
        per-value numeric tolerances.
        """
        reference_artifacts = reference_receipt.get("artifacts") or {}
        candidate_artifacts = candidate_receipt.get("artifacts") or {}
        reference_result = reference_artifacts.get("results") or {}
        candidate_result = candidate_artifacts.get("results") or {}

        volume_limits = tolerances.get("volume_accounting")
        if not isinstance(volume_limits, Mapping):
            raise ValueError("tolerances.volume_accounting is required")
        max_error = float(volume_limits["max_abs_error_percent"])
        max_difference = float(volume_limits["max_abs_difference_percent"])
        reference_volume = reference_result.get("max_abs_volume_error_percent")
        candidate_volume = candidate_result.get("max_abs_volume_error_percent")
        volume_passed = bool(
            reference_volume is not None
            and candidate_volume is not None
            and abs(float(reference_volume)) <= max_error
            and abs(float(candidate_volume)) <= max_error
            and abs(float(reference_volume) - float(candidate_volume))
            <= max_difference
        )
        volume = {
            "reference_abs_error_percent": reference_volume,
            "candidate_abs_error_percent": candidate_volume,
            "abs_difference_percent": (
                abs(float(reference_volume) - float(candidate_volume))
                if reference_volume is not None and candidate_volume is not None
                else None
            ),
            "tolerance": dict(volume_limits),
            "passed": volume_passed,
        }

        series_limits = tolerances.get("series")
        if not isinstance(series_limits, Mapping) or not series_limits:
            raise ValueError("tolerances.series must contain at least one named series")
        reference_series = reference_receipt.get("series") or {}
        candidate_series = candidate_receipt.get("series") or {}
        metadata_fields = (
            "kind",
            "mesh_name",
            "line_name",
            "direction",
            "variable",
            "entity_dimension",
            "entity_ids",
            "units",
            "value_columns",
            "start_time",
            "end_time",
        )
        series_results: Dict[str, Any] = {}
        for name, specification in series_limits.items():
            reference_item = reference_series.get(name)
            candidate_item = candidate_series.get(name)
            if not isinstance(reference_item, Mapping) or not isinstance(
                candidate_item, Mapping
            ):
                series_results[str(name)] = {
                    "passed": False,
                    "reason": "series missing",
                    "reference_present": isinstance(reference_item, Mapping),
                    "candidate_present": isinstance(candidate_item, Mapping),
                }
                continue
            reference_metadata = {
                field: _json_value(reference_item.get(field))
                for field in metadata_fields
            }
            candidate_metadata = {
                field: _json_value(candidate_item.get(field))
                for field in metadata_fields
            }
            metadata_exact = reference_metadata == candidate_metadata
            comparison = RasQualification.compare_numeric_frames(
                pd.DataFrame(reference_item.get("records") or []),
                pd.DataFrame(candidate_item.get("records") or []),
                key_columns=specification.get("key_columns") or [],
                tolerances=specification.get("columns") or {},
            )

            def _records_sha256(item: Mapping[str, Any]) -> str:
                encoded = json.dumps(
                    _json_value(item.get("records") or []),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                return hashlib.sha256(encoded).hexdigest()

            series_results[str(name)] = {
                "reference_metadata": reference_metadata,
                "candidate_metadata": candidate_metadata,
                "metadata_exact": metadata_exact,
                "reference_records_sha256": _records_sha256(reference_item),
                "candidate_records_sha256": _records_sha256(candidate_item),
                "numeric": comparison,
                "passed": metadata_exact and comparison["passed"],
            }

        checks = {
            "reference_results_successful": reference_result.get("successful")
            is True,
            "candidate_results_successful": candidate_result.get("successful")
            is True,
            "volume_accounting": volume_passed,
            "every_series_present_and_within_tolerance": bool(series_results)
            and all(item.get("passed") is True for item in series_results.values()),
        }
        return {
            "reference_result_sha256": reference_result.get("file_sha256"),
            "candidate_result_sha256": candidate_result.get("file_sha256"),
            "checks": checks,
            "volume_accounting": volume,
            "series": series_results,
            "passed": all(checks.values()),
        }

    @staticmethod
    @log_call
    def compare_run_receipts(
        native_receipt: Mapping[str, Any],
        wine_receipt: Mapping[str, Any],
        tolerances: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Compare native-Windows and Wine receipts using explicit tolerances."""
        native_validation = RasQualification.validate_run_receipt(
            native_receipt,
            expected_profile=ExecutorProfile.WINDOWS_NATIVE,
        )
        wine_validation = RasQualification.validate_run_receipt(
            wine_receipt,
            expected_profile=ExecutorProfile.LINUX_WINE_WINDOWS_RAS,
        )
        native_artifacts = native_receipt.get("artifacts") or {}
        wine_artifacts = wine_receipt.get("artifacts") or {}
        native_installation = native_receipt.get("installation") or {}
        wine_installation = wine_receipt.get("installation") or {}
        native_components = native_installation.get("components") or {}
        wine_components = wine_installation.get("components") or {}
        component_names = sorted(set(native_components) | set(wine_components))
        installation_checks = {
            "detected_version_exact": native_installation.get("detected_version")
            == wine_installation.get("detected_version"),
            "component_names_exact": set(native_components) == set(wine_components),
            "component_hashes_exact": bool(component_names)
            and all(
                (native_components.get(name) or {}).get("sha256")
                == (wine_components.get(name) or {}).get("sha256")
                for name in component_names
            ),
            "component_architectures_exact": bool(component_names)
            and all(
                (native_components.get(name) or {}).get("pe")
                == (wine_components.get(name) or {}).get("pe")
                for name in component_names
            ),
        }
        installation = {
            "checks": installation_checks,
            "passed": all(installation_checks.values()),
        }
        geometry = RasQualification._geometry_parity(
            native_artifacts.get("geometry") or {},
            wine_artifacts.get("geometry") or {},
        )

        native_terrain = native_artifacts.get("terrain") or {}
        wine_terrain = wine_artifacts.get("terrain") or {}
        terrain_inventory_fields = (
            "layer",
            "hdf_file_reference",
            "data_fingerprint",
            "driver",
            "width",
            "height",
            "band_count",
            "dtypes",
            "crs_wkt",
            "transform",
            "bounds",
            "nodata",
            "valid_value_count",
            "values",
        )
        native_inventory = [
            {key: item.get(key) for key in terrain_inventory_fields}
            for item in (native_terrain.get("raster_inventory") or [])
            if isinstance(item, Mapping)
        ]
        wine_inventory = [
            {key: item.get(key) for key in terrain_inventory_fields}
            for item in (wine_terrain.get("raster_inventory") or [])
            if isinstance(item, Mapping)
        ]
        terrain_checks = {
            "data_fingerprint_exact": native_terrain.get("data_fingerprint") == wine_terrain.get("data_fingerprint"),
            "terrain_hdf_fingerprint_exact": native_terrain.get("terrain_hdf_fingerprint")
            == wine_terrain.get("terrain_hdf_fingerprint"),
            "raster_inventory_exact": bool(native_inventory)
            and native_inventory == wine_inventory,
            "pyramid_levels_exact": native_terrain.get("pyramid_levels")
            == wine_terrain.get("pyramid_levels"),
            "crs_exact": native_terrain.get("crs_wkt") == wine_terrain.get("crs_wkt"),
            "shape_exact": (
                native_terrain.get("width"),
                native_terrain.get("height"),
                native_terrain.get("band_count"),
            )
            == (
                wine_terrain.get("width"),
                wine_terrain.get("height"),
                wine_terrain.get("band_count"),
            ),
            "transform_exact": native_terrain.get("transform") == wine_terrain.get("transform"),
        }
        terrain = {"checks": terrain_checks, "passed": all(terrain_checks.values())}

        volume_limits = tolerances.get("volume_accounting")
        if not isinstance(volume_limits, Mapping):
            raise ValueError("tolerances.volume_accounting is required")
        max_error = float(volume_limits["max_abs_error_percent"])
        max_difference = float(volume_limits["max_abs_difference_percent"])
        native_volume = (native_artifacts.get("results") or {}).get("max_abs_volume_error_percent")
        wine_volume = (wine_artifacts.get("results") or {}).get("max_abs_volume_error_percent")
        volume_passed = (
            native_volume is not None
            and wine_volume is not None
            and abs(float(native_volume)) <= max_error
            and abs(float(wine_volume)) <= max_error
            and abs(float(native_volume) - float(wine_volume)) <= max_difference
        )
        volume = {
            "native_abs_error_percent": native_volume,
            "wine_abs_error_percent": wine_volume,
            "abs_difference_percent": (
                abs(float(native_volume) - float(wine_volume))
                if native_volume is not None and wine_volume is not None
                else None
            ),
            "tolerance": dict(volume_limits),
            "passed": volume_passed,
        }

        series_results: Dict[str, Any] = {}
        native_series = native_receipt.get("series") or {}
        wine_series = wine_receipt.get("series") or {}
        series_limits = tolerances.get("series") or {}
        for series_name, specification in series_limits.items():
            if series_name not in native_series or series_name not in wine_series:
                series_results[series_name] = {"passed": False, "reason": "series missing"}
                continue
            key_columns = specification.get("key_columns") or []
            column_limits = specification.get("columns") or {}
            series_results[series_name] = RasQualification.compare_numeric_frames(
                pd.DataFrame(native_series[series_name].get("records") or []),
                pd.DataFrame(wine_series[series_name].get("records") or []),
                key_columns=key_columns,
                tolerances=column_limits,
            )
        hydrograph_tolerances = [
            name
            for name in series_limits
            if (native_series.get(name) or {}).get("kind") == "profile_line_flow"
            and (wine_series.get(name) or {}).get("kind") == "profile_line_flow"
        ]
        wse_tolerances = [
            name
            for name in series_limits
            if (native_series.get(name) or {}).get("kind") == "mesh_cells"
            and str((native_series.get(name) or {}).get("variable", "")).strip().lower()
            == "water surface"
            and (wine_series.get(name) or {}).get("kind") == "mesh_cells"
            and str((wine_series.get(name) or {}).get("variable", "")).strip().lower()
            == "water surface"
        ]

        native_map_rasters = RasQualification._map_rasters_by_type(
            native_artifacts
        )
        wine_map_rasters = RasQualification._map_rasters_by_type(wine_artifacts)
        native_has_keyed_rasters = isinstance(
            native_artifacts.get("map_rasters_by_type"),
            Mapping,
        )
        wine_has_keyed_rasters = isinstance(
            wine_artifacts.get("map_rasters_by_type"),
            Mapping,
        )

        raw_map_raster_limits = tolerances.get("map_rasters")
        if raw_map_raster_limits is None:
            raw_map_raster_limits = {}
        if not isinstance(raw_map_raster_limits, Mapping):
            raise ValueError("tolerances.map_rasters must be a mapping")
        map_raster_limits = {
            str(map_type).strip().lower(): limits
            for map_type, limits in raw_map_raster_limits.items()
            if str(map_type).strip()
        }
        # ``depth_raster`` remains a supported alias for existing manifests.
        legacy_depth_limits = tolerances.get("depth_raster")
        if legacy_depth_limits is not None and "depth" not in map_raster_limits:
            map_raster_limits["depth"] = legacy_depth_limits

        native_map_types = set(native_map_rasters)
        wine_map_types = set(wine_map_rasters)
        requested_map_types = sorted(native_map_types | wine_map_types)
        comparison_map_types = sorted(
            native_map_types | wine_map_types | set(map_raster_limits)
        )
        map_raster_results = {
            map_type: RasQualification._map_raster_type_parity(
                map_type,
                native_map_rasters.get(map_type) or [],
                wine_map_rasters.get(map_type) or [],
                map_raster_limits.get(map_type),
                native_strict=native_has_keyed_rasters,
                wine_strict=wine_has_keyed_rasters,
            )
            for map_type in comparison_map_types
        }
        map_raster_checks = {
            "requested_map_types_present": bool(requested_map_types),
            "requested_map_types_exact": native_map_types == wine_map_types,
            "keyed_inventory_mode_exact": native_has_keyed_rasters
            == wine_has_keyed_rasters,
            "tolerances_cover_requested_types_exactly": set(map_raster_limits)
            == (native_map_types | wine_map_types),
            "every_requested_type_passed": bool(map_raster_results)
            and all(
                result.get("passed") is True
                for result in map_raster_results.values()
            ),
        }
        map_raster_parity = {
            "requested_map_types": requested_map_types,
            "configured_tolerance_types": sorted(map_raster_limits),
            "checks": map_raster_checks,
            "types": map_raster_results,
            "passed": all(map_raster_checks.values()),
        }

        depth_result: Optional[Dict[str, Any]] = None
        depth_type_result = map_raster_results.get("depth")
        if depth_type_result is not None:
            depth_comparisons = depth_type_result.get("rasters") or {}
            if len(depth_comparisons) == 1:
                depth_result = dict(next(iter(depth_comparisons.values())))
                depth_result["artifact_checks"] = depth_type_result.get("checks")
                depth_result["passed"] = depth_type_result.get("passed") is True
            else:
                depth_result = depth_type_result
        depth_required = "depth" in (native_map_types | wine_map_types)

        checks = {
            "native_receipt": native_validation["passed"],
            "wine_receipt": wine_validation["passed"],
            "installation_identity": installation["passed"],
            "same_fixture": native_receipt.get("fixture") == wine_receipt.get("fixture"),
            "geometry": geometry["passed"],
            "terrain": terrain["passed"],
            "volume_accounting": volume["passed"],
            "series": bool(series_results) and all(item.get("passed") for item in series_results.values()),
            "hydrograph_wse_tolerances": bool(hydrograph_tolerances)
            and bool(wse_tolerances),
            "map_rasters": map_raster_parity["passed"],
            "depth_raster": not depth_required
            or (
                depth_result is not None
                and bool(depth_result.get("passed"))
            ),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "native_validation": native_validation,
            "wine_validation": wine_validation,
            "installation": installation,
            "geometry": geometry,
            "terrain": terrain,
            "volume_accounting": volume,
            "series": series_results,
            "hydrograph_tolerances": hydrograph_tolerances,
            "wse_tolerances": wse_tolerances,
            "map_rasters": map_raster_parity,
            "depth_raster": depth_result,
        }

    @staticmethod
    @log_call
    def write_receipt(receipt: Mapping[str, Any], output_path: Union[str, Path]) -> Path:
        """Write a strict JSON qualification receipt."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_json_value(receipt), indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        return path

    @staticmethod
    @log_call
    def read_receipt(receipt_path: Union[str, Path]) -> Dict[str, Any]:
        """Read a qualification receipt from JSON."""
        path = Path(receipt_path)
        if not path.is_file():
            raise FileNotFoundError(f"Qualification receipt not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
