"""Out-of-process RasMapperLib mesh host for native Windows and Wine."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from ..LoggingConfig import get_logger
from .._gdal_runtime import configure_rasmapper_gdal_bridge

logger = get_logger(__name__)

_SOURCE_NAME = "RasMapperMeshHelper.cs"
_EXECUTABLE_NAME = "RasMapperMeshHelper.exe"
_GEOMETRY_HDF_NAME = re.compile(
    r"^(?P<project>.+)(?P<geometry>\.g\d+\.(?:hdf|h5))$",
    re.IGNORECASE,
)
_CENTER_ABSOLUTE_TOLERANCE = 1e-8
_LOCK_SCOPE = (
    "Cooperative ras-commander transaction lock only; non-cooperating external "
    "writers are not excluded. Use one node-local project copy per task."
)


def is_wine_runtime() -> bool:
    """Return whether the process is hosted by or controlling a Wine prefix."""
    return bool(
        os.environ.get("WINEPREFIX")
        or os.environ.get("WINELOADERNOEXEC")
        or os.environ.get("WINEARCH")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream_tail(value: str, limit: int = 4000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[-limit:]


def _transactional_hdf_path(path: Path) -> Path:
    """Return a same-folder temp name that retains the ``.g##.hdf`` suffix."""
    match = _GEOMETRY_HDF_NAME.match(path.name)
    if match is None:
        raise ValueError(
            "transactional_direct persistence requires a geometry HDF named "
            "like '<project>.g##.hdf'"
        )
    return path.with_name(
        f"{match.group('project')}.rascommander-mesh-{uuid.uuid4().hex}"
        f"{match.group('geometry')}"
    )


def _transaction_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.rascommander-mesh.lock")


def _transaction_lock_owned(path: Path, token: str) -> bool:
    try:
        observed = json.loads(
            _transaction_lock_path(path).read_text(encoding="utf-8")
        )
    except Exception:
        return False
    return isinstance(observed, dict) and observed.get("token") == token


@contextmanager
def _transaction_lock(path: Path, mesh_name: str) -> Iterator[dict[str, Any]]:
    """Hold a cooperative same-directory O_EXCL lock for one HDF transaction."""
    lock_path = _transaction_lock_path(path)
    token = uuid.uuid4().hex
    metadata = {
        "schema_version": 1,
        "token": token,
        "process_id": os.getpid(),
        "mesh_name": str(mesh_name),
        "source_name": path.name,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "scope": _LOCK_SCOPE,
        "released_by_owner": False,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        try:
            owner = json.loads(lock_path.read_text(encoding="utf-8"))
            owner_summary = {
                key: owner.get(key)
                for key in ("process_id", "mesh_name", "started_utc")
            }
        except Exception:
            owner_summary = {"metadata": "unreadable"}
        raise RuntimeError(
            "Geometry HDF transactional mesh lock is already held; refusing "
            f"to proceed: {json.dumps(owner_summary, sort_keys=True)}"
        ) from exc

    try:
        payload = json.dumps(metadata, sort_keys=True).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)

    try:
        yield metadata
    finally:
        try:
            observed = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            observed = None
        if isinstance(observed, dict) and observed.get("token") == token:
            lock_path.unlink(missing_ok=True)
            metadata["released_by_owner"] = True


def _decode_hdf_name(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    return str(value).strip()


def _center_fingerprint(values: Any) -> str:
    import numpy as np

    canonical = np.ascontiguousarray(values, dtype=np.dtype("<f8"))
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


def _inspect_transactional_candidate(
    path: Path,
    mesh_name: str,
    expected_cell_count: int,
    expected_face_count: int,
    generated_cell_centers: Optional[Any] = None,
    center_absolute_tolerance: float = _CENTER_ABSOLUTE_TOLERANCE,
    require_generated_center_match: bool = False,
) -> dict[str, Any]:
    """Validate the candidate's persisted HDF topology before replacement."""
    import h5py
    import numpy as np

    root = "Geometry/2D Flow Areas"
    area_path = f"{root}/{mesh_name}"
    required = (
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
    with h5py.File(path, "r") as hdf:
        attributes_path = f"{root}/Attributes"
        cell_info_path = f"{root}/Cell Info"
        cell_points_path = f"{root}/Cell Points"
        if attributes_path not in hdf:
            raise KeyError(f"Missing {attributes_path}")
        attributes = hdf[attributes_path][()]
        field_names = attributes.dtype.names or ()
        if "Name" not in field_names or "Cell Count" not in field_names:
            raise KeyError(
                "2D Flow Areas/Attributes lacks Name or Cell Count fields"
            )
        name_dtype = attributes.dtype.fields["Name"][0]
        attributes_name_width = (
            int(name_dtype.itemsize) if name_dtype.kind == "S" else 0
        )
        matching_rows = [
            index
            for index, row in enumerate(attributes)
            if _decode_hdf_name(row["Name"]) == mesh_name
        ]
        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected one Attributes row for {mesh_name!r}, found "
                f"{len(matching_rows)}"
            )
        row_index = matching_rows[0]
        declared_cell_count = int(attributes[row_index]["Cell Count"])

        if cell_info_path not in hdf or cell_points_path not in hdf:
            raise KeyError("Missing global Cell Info or Cell Points dataset")
        cell_info = np.asarray(hdf[cell_info_path][()])
        cell_points = np.asarray(hdf[cell_points_path][()])
        if cell_info.ndim != 2 or cell_info.shape[1] != 2:
            raise ValueError(f"Invalid Cell Info shape: {cell_info.shape}")
        if cell_points.ndim != 2 or cell_points.shape[1] != 2:
            raise ValueError(f"Invalid Cell Points shape: {cell_points.shape}")
        if row_index >= cell_info.shape[0]:
            raise ValueError("Attributes row has no corresponding Cell Info row")
        seed_start, seed_count = [int(value) for value in cell_info[row_index]]

        if area_path not in hdf:
            raise KeyError(f"Missing persisted mesh group {area_path}")
        area = hdf[area_path]
        missing = [name for name in required if name not in area]
        if missing:
            raise KeyError(
                f"Missing persisted topology datasets for {mesh_name!r}: "
                f"{missing}"
            )
        arrays = {name: np.asarray(area[name][()]) for name in required}

    centers = arrays["Cells Center Coordinate"]
    cell_face_info = arrays["Cells Face and Orientation Info"]
    cell_face_values = arrays["Cells Face and Orientation Values"]
    cell_facepoints = arrays["Cells FacePoint Indexes"]
    facepoint_cell_values = arrays["FacePoints Cell Index Values"]
    facepoint_cell_info = arrays["FacePoints Cell Info"]
    facepoints = arrays["FacePoints Coordinate"]
    facepoint_face_info = arrays["FacePoints Face and Orientation Info"]
    facepoint_face_values = arrays["FacePoints Face and Orientation Values"]
    facepoint_is_perimeter = arrays["FacePoints Is Perimeter"]
    face_cells = arrays["Faces Cell Indexes"]
    face_facepoints = arrays["Faces FacePoint Indexes"]
    face_normals = arrays["Faces NormalUnitVector and Length"]
    face_perimeter_info = arrays["Faces Perimeter Info"]
    face_perimeter_values = arrays["Faces Perimeter Values"]
    perimeter = arrays["Perimeter"]
    face_perimeter_empty_encoding = bool(
        face_perimeter_values.ndim == 2
        and face_perimeter_values.shape == (0, 0)
    )

    center_capacity = int(centers.shape[0]) if centers.ndim == 2 else 0
    facepoint_count = int(facepoints.shape[0]) if facepoints.ndim == 2 else 0
    candidate_expected_centers = (
        centers[:expected_cell_count]
        if centers.ndim == 2 and center_capacity >= expected_cell_count
        else np.empty((0, 2), dtype=np.float64)
    )
    generated_centers = None
    center_max_abs_error = None
    generated_center_fingerprint = None
    candidate_center_fingerprint = (
        _center_fingerprint(candidate_expected_centers)
        if candidate_expected_centers.shape == (expected_cell_count, 2)
        else None
    )
    if generated_cell_centers is not None or require_generated_center_match:
        generated_centers = np.asarray(
            generated_cell_centers if generated_cell_centers is not None else [],
            dtype=np.float64,
        )
        if (
            generated_centers.shape == (expected_cell_count, 2)
            and candidate_expected_centers.shape == (expected_cell_count, 2)
            and np.isfinite(generated_centers).all()
            and np.isfinite(candidate_expected_centers).all()
        ):
            center_max_abs_error = float(
                np.max(np.abs(generated_centers - candidate_expected_centers))
            )
            generated_center_fingerprint = _center_fingerprint(generated_centers)

    def _csr_valid(info: Any, values: Any, used_rows: Optional[int] = None) -> bool:
        if info.ndim != 2 or info.shape[1] != 2 or values.ndim < 1:
            return False
        selected = info if used_rows is None else info[:used_rows]
        if not len(selected):
            return False
        starts = selected[:, 0].astype(np.int64, copy=False)
        counts = selected[:, 1].astype(np.int64, copy=False)
        return bool(
            np.all(starts >= 0)
            and np.all(counts >= 0)
            and np.all(starts + counts <= len(values))
        )

    def _csr_exact(info: Any, values: Any) -> bool:
        if info.ndim != 2 or info.shape[1] != 2 or values.ndim < 1:
            return False
        if not len(info):
            return False
        starts = info[:, 0].astype(np.int64, copy=False)
        counts = info[:, 1].astype(np.int64, copy=False)
        ends = starts + counts
        return bool(
            np.all(starts >= 0)
            and np.all(counts >= 0)
            and starts[0] == 0
            and np.array_equal(starts[1:], ends[:-1])
            and ends[-1] == len(values)
        )

    def _face_incidence_checks(
        info: Any,
        values: Any,
        face_entities: Any,
        entity_count: int,
        first_entity_orientation: int,
    ) -> dict[str, bool]:
        result = {
            "coverage_exact": False,
            "twice_with_opposite_orientations": False,
            "cross_references_face_entities": False,
        }
        if (
            not _csr_exact(info, values)
            or values.ndim != 2
            or values.shape[1] != 2
            or face_entities.shape != (expected_face_count, 2)
        ):
            return result
        counts = info[:, 1].astype(np.int64, copy=False)
        entity_ids = np.repeat(np.arange(entity_count, dtype=np.int64), counts)
        face_ids = values[:, 0].astype(np.int64, copy=False)
        orientations = values[:, 1].astype(np.int64, copy=False)
        if (
            len(entity_ids) != len(values)
            or np.any(face_ids < 0)
            or np.any(face_ids >= expected_face_count)
        ):
            return result
        incidence_counts = np.bincount(
            face_ids,
            minlength=expected_face_count,
        )
        positive_counts = np.bincount(
            face_ids[orientations == 1],
            minlength=expected_face_count,
        )
        negative_counts = np.bincount(
            face_ids[orientations == -1],
            minlength=expected_face_count,
        )
        exact_twice = bool(np.all(incidence_counts == 2))
        result["coverage_exact"] = exact_twice
        result["twice_with_opposite_orientations"] = bool(
            exact_twice
            and np.all(positive_counts == 1)
            and np.all(negative_counts == 1)
        )
        if not exact_twice:
            return result
        positive_entities = np.full(expected_face_count, -1, dtype=np.int64)
        negative_entities = np.full(expected_face_count, -1, dtype=np.int64)
        positive_entities[face_ids[orientations == 1]] = entity_ids[
            orientations == 1
        ]
        negative_entities[face_ids[orientations == -1]] = entity_ids[
            orientations == -1
        ]
        expected_positive_column = 0 if first_entity_orientation == 1 else 1
        expected_negative_column = 0 if first_entity_orientation == -1 else 1
        result["cross_references_face_entities"] = bool(
            np.array_equal(
                positive_entities,
                face_entities[:, expected_positive_column].astype(
                    np.int64,
                    copy=False,
                ),
            )
            and np.array_equal(
                negative_entities,
                face_entities[:, expected_negative_column].astype(
                    np.int64,
                    copy=False,
                ),
            )
        )
        return result

    cell_incidence = _face_incidence_checks(
        cell_face_info,
        cell_face_values,
        face_cells,
        center_capacity,
        1,
    )
    facepoint_incidence = _face_incidence_checks(
        facepoint_face_info,
        facepoint_face_values,
        face_facepoints,
        facepoint_count,
        -1,
    )

    checks = {
        "hdf_attributes_name_width_supported": (
            0 < attributes_name_width <= 16
        ),
        "hdf_attributes_cell_count_exact": (
            declared_cell_count == expected_cell_count
        ),
        "hdf_global_cell_info_shape": (
            cell_info.ndim == 2
            and cell_info.shape == (len(attributes), 2)
        ),
        "hdf_global_cell_points_shape": (
            cell_points.ndim == 2
            and cell_points.shape[1] == 2
            and cell_points.shape[0] > 0
        ),
        "hdf_global_seed_range_valid": (
            seed_start >= 0
            and seed_count > 0
            and seed_start + seed_count <= cell_points.shape[0]
        ),
        "hdf_global_cell_points_finite": (
            cell_points.ndim == 2 and np.isfinite(cell_points).all()
        ),
        "hdf_global_cell_info_contiguous_exact": (
            _csr_exact(cell_info, cell_points)
        ),
        "hdf_center_capacity_sufficient": (
            centers.ndim == 2
            and centers.shape[1] == 2
            and center_capacity >= expected_cell_count
        ),
        "hdf_all_allocated_centers_finite": (
            centers.ndim == 2
            and center_capacity >= expected_cell_count
            and np.isfinite(centers).all()
        ),
        "hdf_cell_face_info_capacity": (
            cell_face_info.ndim == 2
            and cell_face_info.shape == (center_capacity, 2)
        ),
        "hdf_cell_face_csr_valid": _csr_valid(
            cell_face_info,
            cell_face_values,
        ),
        "hdf_cell_face_csr_contiguous_exact": _csr_exact(
            cell_face_info,
            cell_face_values,
        ),
        "hdf_cell_face_values_twice_per_face": (
            len(cell_face_values) == 2 * expected_face_count
            and cell_incidence["coverage_exact"]
        ),
        "hdf_cell_face_orientations_opposite": cell_incidence[
            "twice_with_opposite_orientations"
        ],
        "hdf_cell_face_cross_references_faces": cell_incidence[
            "cross_references_face_entities"
        ],
        "hdf_cell_face_values_bounded": (
            cell_face_values.ndim == 2
            and cell_face_values.shape[1] == 2
            and len(cell_face_values) > 0
            and int(np.min(cell_face_values[:, 0])) >= 0
            and int(np.max(cell_face_values[:, 0])) < expected_face_count
            and np.isin(cell_face_values[:, 1], (-1, 1)).all()
        ),
        "hdf_cell_facepoint_capacity": (
            cell_facepoints.ndim == 2
            and cell_facepoints.shape[0] == center_capacity
        ),
        "hdf_face_rows_exact": (
            face_cells.ndim == 2
            and face_cells.shape == (expected_face_count, 2)
            and face_facepoints.shape == (expected_face_count, 2)
            and face_normals.shape == (expected_face_count, 3)
            and face_perimeter_info.shape == (expected_face_count, 2)
        ),
        "hdf_face_cell_indexes_bounded": (
            face_cells.size > 0
            and int(np.min(face_cells)) >= 0
            and int(np.max(face_cells)) < center_capacity
        ),
        "hdf_face_cell_indexes_distinct": (
            face_cells.shape == (expected_face_count, 2)
            and np.all(face_cells[:, 0] != face_cells[:, 1])
        ),
        "hdf_facepoint_rows_consistent": (
            facepoints.ndim == 2
            and facepoints.shape[1] == 2
            and facepoint_count > 0
            and facepoint_cell_info.shape == (facepoint_count, 2)
            and facepoint_face_info.shape == (facepoint_count, 2)
            and facepoint_is_perimeter.shape == (facepoint_count,)
        ),
        "hdf_facepoint_coordinates_finite": (
            facepoints.ndim == 2 and np.isfinite(facepoints).all()
        ),
        "hdf_face_facepoint_indexes_bounded": (
            face_facepoints.size > 0
            and int(np.min(face_facepoints)) >= 0
            and int(np.max(face_facepoints)) < facepoint_count
        ),
        "hdf_face_facepoint_indexes_distinct": (
            face_facepoints.shape == (expected_face_count, 2)
            and np.all(face_facepoints[:, 0] != face_facepoints[:, 1])
        ),
        "hdf_cell_facepoint_indexes_bounded": (
            cell_facepoints.ndim == 2
            and cell_facepoints.shape[0] == center_capacity
            and np.all(cell_facepoints >= -1)
            and np.all(
                cell_facepoints[cell_facepoints >= 0] < facepoint_count
            )
        ),
        "hdf_facepoint_cell_csr_valid": _csr_valid(
            facepoint_cell_info,
            facepoint_cell_values,
        ),
        "hdf_facepoint_cell_csr_contiguous_exact": _csr_exact(
            facepoint_cell_info,
            facepoint_cell_values,
        ),
        "hdf_facepoint_cell_values_bounded": (
            facepoint_cell_values.ndim == 1
            and len(facepoint_cell_values) > 0
            and int(np.min(facepoint_cell_values)) >= 0
            and int(np.max(facepoint_cell_values)) < center_capacity
        ),
        "hdf_facepoint_face_csr_valid": _csr_valid(
            facepoint_face_info,
            facepoint_face_values,
        ),
        "hdf_facepoint_face_csr_contiguous_exact": _csr_exact(
            facepoint_face_info,
            facepoint_face_values,
        ),
        "hdf_facepoint_face_values_twice_per_face": (
            len(facepoint_face_values) == 2 * expected_face_count
            and facepoint_incidence["coverage_exact"]
        ),
        "hdf_facepoint_face_orientations_opposite": facepoint_incidence[
            "twice_with_opposite_orientations"
        ],
        "hdf_facepoint_face_cross_references_faces": facepoint_incidence[
            "cross_references_face_entities"
        ],
        "hdf_facepoint_face_values_bounded": (
            facepoint_face_values.ndim == 2
            and facepoint_face_values.shape[1] == 2
            and len(facepoint_face_values) > 0
            and int(np.min(facepoint_face_values[:, 0])) >= 0
            and int(np.max(facepoint_face_values[:, 0])) < expected_face_count
            and np.isin(facepoint_face_values[:, 1], (-1, 1)).all()
        ),
        "hdf_face_normals_finite_positive_length": (
            face_normals.shape == (expected_face_count, 3)
            and np.isfinite(face_normals).all()
            and np.all(face_normals[:, 2] > 0)
        ),
        "hdf_face_normal_xy_unit_length": (
            face_normals.shape == (expected_face_count, 3)
            and np.isfinite(face_normals).all()
            and np.all(
                np.abs(np.linalg.norm(face_normals[:, :2], axis=1) - 1.0)
                <= 1e-6
            )
        ),
        "hdf_perimeter_valid": (
            perimeter.ndim == 2
            and perimeter.shape[0] >= 3
            and perimeter.shape[1] == 2
            and np.isfinite(perimeter).all()
        ),
        "hdf_perimeter_closed": (
            perimeter.ndim == 2
            and perimeter.shape[0] >= 3
            and np.allclose(perimeter[0], perimeter[-1], rtol=0.0, atol=1e-9)
        ),
        "hdf_face_perimeter_values_shape": (
            face_perimeter_values.ndim == 2
            and (
                face_perimeter_values.shape[1] == 2
                or face_perimeter_empty_encoding
            )
        ),
        "hdf_face_perimeter_empty_encoding_consistent": (
            not face_perimeter_empty_encoding
            or (
                face_perimeter_info.shape == (expected_face_count, 2)
                and np.all(face_perimeter_info[:, 1] == 0)
            )
        ),
        "hdf_face_perimeter_csr_contiguous_exact": _csr_exact(
            face_perimeter_info,
            face_perimeter_values,
        ),
    }
    if generated_centers is not None:
        checks.update(
            {
                "hdf_generated_centers_shape_exact": (
                    generated_centers.shape == (expected_cell_count, 2)
                ),
                "hdf_generated_centers_finite": (
                    generated_centers.shape == (expected_cell_count, 2)
                    and np.isfinite(generated_centers).all()
                ),
                "hdf_generated_centers_match_candidate_ordered": (
                    center_max_abs_error is not None
                    and center_max_abs_error <= center_absolute_tolerance
                ),
            }
        )
    checks = {name: bool(value) for name, value in checks.items()}
    return {
        "mesh_name": mesh_name,
        "declared_cell_count": declared_cell_count,
        "global_cell_info_shape": list(cell_info.shape),
        "global_cell_points_shape": list(cell_points.shape),
        "global_seed_start": seed_start,
        "global_seed_count": seed_count,
        "attributes_name_width": attributes_name_width,
        "center_storage_rows": center_capacity,
        "face_rows": int(face_cells.shape[0]) if face_cells.ndim else 0,
        "facepoint_rows": facepoint_count,
        "center_absolute_tolerance": float(center_absolute_tolerance),
        "center_max_abs_error": center_max_abs_error,
        "generated_center_fingerprint": generated_center_fingerprint,
        "candidate_center_fingerprint": candidate_center_fingerprint,
        "dataset_shapes": {
            name: list(value.shape) for name, value in arrays.items()
        },
        "checks": checks,
    }


def _native_wine_controller() -> bool:
    return platform.system() != "Windows" and bool(os.environ.get("WINEPREFIX"))


def _wine_executable() -> str:
    return os.environ.get("RAS_COMMANDER_WINE_EXECUTABLE", "wine")


def _winepath_executable() -> str:
    configured = os.environ.get("RAS_COMMANDER_WINEPATH_EXECUTABLE")
    if configured:
        return configured
    wine = Path(_wine_executable())
    if wine.is_absolute():
        candidate = wine.with_name("winepath")
        if candidate.is_file():
            return str(candidate)
    return "winepath"


def _to_windows_path(path: Path) -> str:
    completed = subprocess.run(
        [_winepath_executable(), "-w", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        env=os.environ.copy(),
    )
    value = (completed.stdout or "").strip()
    if completed.returncode != 0 or not value:
        raise RuntimeError(
            f"winepath could not translate {path}: "
            f"{_stream_tail(completed.stderr or completed.stdout)}"
        )
    return value


def _bounded_run(
    command: list[str],
    *,
    timeout: float,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    if not _native_wine_controller():
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate(timeout=30)
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _reset_wineserver(environment: dict[str, str]) -> None:
    if not _native_wine_controller():
        return
    wine = Path(_wine_executable())
    wineserver = wine.with_name("wineserver") if wine.is_absolute() else Path("wineserver")
    subprocess.run(
        [str(wineserver), "-k"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=environment,
    )


def _compiler_path() -> Path:
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = (
        windows_dir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
        windows_dir
        / "Microsoft.NET"
        / "Framework64"
        / "v4.0.30319"
        / "csc.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        ".NET Framework csc.exe was not found; the managed mesh host requires "
        "the qualified .NET Framework 4.x Wine/Windows runtime."
    )


def ensure_managed_mesh_host(
    hecras_dir: Union[str, Path],
) -> Path:
    """Compile the packaged x86 C# host in Windows or an isolated Wine prefix."""
    native_wine = _native_wine_controller()
    if platform.system() != "Windows" and not native_wine:
        raise RuntimeError(
            "The managed RasMapper mesh host requires Windows or a native "
            "controller process with WINEPREFIX configured."
        )

    hecras_dir = Path(hecras_dir)
    if native_wine:
        prefix = Path(os.environ["WINEPREFIX"])
        python_candidates = sorted((prefix / "drive_c").glob("Python3*"))
        python_dir = next(
            (candidate for candidate in python_candidates if candidate.is_dir()),
            None,
        )
        if python_dir is None:
            raise FileNotFoundError(
                f"No Windows Python installation was found in Wine prefix {prefix}"
            )
        if not (
            (python_dir / "GDAL" / "bin64").is_dir()
            and (python_dir / "GDAL" / "common" / "data").is_dir()
        ):
            raise RuntimeError(
                "The native Wine controller requires the qualified GDAL link "
                f"beside Windows Python: {python_dir / 'GDAL'}"
            )
        framework = prefix / "drive_c" / "windows" / "Microsoft.NET" / "Framework"
        compiler = framework / "v4.0.30319" / "csc.exe"
        if not compiler.is_file():
            raise FileNotFoundError(
                f".NET Framework csc.exe was not found in Wine prefix: {compiler}"
            )
        host_dir = python_dir
    else:
        compiler = _compiler_path()
        host_dir = Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(Path.home() / ".cache"),
            )
        ) / "ras_commander" / "managed_host"
        host_dir.mkdir(parents=True, exist_ok=True)
        configure_rasmapper_gdal_bridge(hecras_dir, python_dir=host_dir)

    source = Path(__file__).with_name(_SOURCE_NAME)
    if not source.is_file():
        raise FileNotFoundError(f"Packaged managed mesh host source is missing: {source}")

    executable = host_dir / _EXECUTABLE_NAME
    marker = executable.with_suffix(executable.suffix + ".source-sha256")
    source_hash = _sha256(source)
    if executable.is_file() and marker.is_file():
        if marker.read_text(encoding="ascii").strip() == source_hash:
            return executable

    environment = os.environ.copy()
    if is_wine_runtime():
        environment.setdefault("COMPlus_ZapDisable", "1")
    command = (
        [
            _wine_executable(),
            _to_windows_path(compiler),
            "/nologo",
            "/platform:x86",
            f"/out:{_to_windows_path(executable)}",
            _to_windows_path(source),
        ]
        if native_wine
        else [
            str(compiler),
            "/nologo",
            "/platform:x86",
            f"/out:{executable}",
            str(source),
        ]
    )
    completed = _bounded_run(command, timeout=120, environment=environment)
    if completed.returncode != 0 or not executable.is_file():
        detail = _stream_tail(completed.stderr or completed.stdout)
        raise RuntimeError(
            "Failed to compile the managed RasMapper mesh host "
            f"(exit {completed.returncode}): {detail}"
        )
    marker.write_text(source_hash, encoding="ascii")
    _reset_wineserver(environment)
    logger.info("Compiled managed RasMapper mesh host: %s", executable)
    return executable


def _run_managed_mesh_host_without_transaction_lock(
    geom_hdf_path: Union[str, Path],
    mesh_name: str,
    hecras_dir: Union[str, Path],
    *,
    min_face_length_ratio: float = 0.05,
    timeout_seconds: float = 600.0,
    max_attempts: int = 3,
    attempt_timeout_seconds: Optional[float] = None,
    persistence_mode: str = "auto",
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    cell_size: Optional[float] = None,
    seed_generation_mode: str = "regenerate_then_fallback",
    transaction_lock_token: Optional[str] = None,
) -> dict[str, Any]:
    """Generate one mesh; the caller holds the direct-write lock when needed.

    ``persistence_mode="auto"`` preserves the established behavior: Wine skips
    the non-returning ``RASD2FlowArea.Save()`` call and native Windows uses it.
    The opt-in ``"transactional_direct"`` experiment writes only a same-folder
    HDF copy, requires exact generated/reopened/caller topology agreement, and
    atomically replaces the original only after all checks pass.
    """
    geom_hdf_path = Path(geom_hdf_path)
    hecras_dir = Path(hecras_dir)
    if int(max_attempts) < 1:
        raise ValueError("max_attempts must be at least 1")
    max_attempts = int(max_attempts)
    executable = ensure_managed_mesh_host(hecras_dir)
    environment = os.environ.copy()
    seed_generation_mode = str(seed_generation_mode).strip().lower()
    if seed_generation_mode not in {
        "regenerate_then_fallback",
        "point_generator",
    }:
        raise ValueError(
            "seed_generation_mode must be 'regenerate_then_fallback' or "
            "'point_generator'"
        )
    environment["RAS_MESH_SEED_GENERATION_MODE"] = seed_generation_mode
    wine_runtime = is_wine_runtime()
    native_wine = _native_wine_controller()
    persistence_mode = str(persistence_mode).strip().lower()
    if persistence_mode == "auto":
        helper_persistence_mode = "skip" if wine_runtime else "legacy_save"
    elif persistence_mode in {"skip", "legacy_save", "transactional_direct"}:
        helper_persistence_mode = persistence_mode
    else:
        raise ValueError(
            "persistence_mode must be 'auto', 'skip', 'legacy_save', or "
            "'transactional_direct'"
        )
    transactional_direct = helper_persistence_mode == "transactional_direct"
    if transactional_direct:
        if expected_cell_count is None or expected_face_count is None:
            raise ValueError(
                "transactional_direct persistence requires expected_cell_count "
                "and expected_face_count"
            )
        expected_cell_count = int(expected_cell_count)
        expected_face_count = int(expected_face_count)
        if expected_cell_count <= 0 or expected_face_count <= 0:
            raise ValueError(
                "expected_cell_count and expected_face_count must be positive"
            )
        original_sha256 = _sha256(geom_hdf_path)
    else:
        original_sha256 = ""
    if wine_runtime:
        environment.setdefault("COMPlus_ZapDisable", "1")

    started = time.monotonic()
    attempt_timeout = max(1.0, float(timeout_seconds) / max_attempts)
    if attempt_timeout_seconds is not None:
        if float(attempt_timeout_seconds) <= 0:
            raise ValueError("attempt_timeout_seconds must be positive")
        attempt_timeout = min(attempt_timeout, float(attempt_timeout_seconds))
    failed_attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        attempt_hdf_path = geom_hdf_path
        transactional_hdf_path: Optional[Path] = None
        if transactional_direct:
            if _sha256(geom_hdf_path) != original_sha256:
                raise RuntimeError(
                    "Geometry HDF changed while preparing the transactional "
                    "mesh attempt; refusing to overwrite it."
                )
            transactional_hdf_path = _transactional_hdf_path(geom_hdf_path)
            shutil.copy2(geom_hdf_path, transactional_hdf_path)
            attempt_hdf_path = transactional_hdf_path
        receipt_path = executable.with_name(
            f".{geom_hdf_path.name}.managed-mesh-{uuid.uuid4().hex}.json"
        )
        progress_path = receipt_path.with_name(receipt_path.name + ".progress")
        helper_arguments = [
            _to_windows_path(executable) if native_wine else str(executable),
            _to_windows_path(hecras_dir) if native_wine else str(hecras_dir),
            _to_windows_path(attempt_hdf_path)
            if native_wine
            else str(attempt_hdf_path),
            str(mesh_name),
            format(float(min_face_length_ratio), ".17g"),
            format(float(cell_size or 0.0), ".17g"),
            _to_windows_path(receipt_path) if native_wine else str(receipt_path),
            helper_persistence_mode,
        ]
        command = (
            [_wine_executable(), *helper_arguments]
            if native_wine
            else helper_arguments
        )
        attempt_started = time.monotonic()
        completed = None
        timed_out = False
        if native_wine:
            _reset_wineserver(environment)
        try:
            completed = _bounded_run(
                command,
                timeout=attempt_timeout,
                environment=environment,
            )
        except subprocess.TimeoutExpired:
            timed_out = True

        progress = (
            progress_path.read_text(encoding="utf-8", errors="replace")
            if progress_path.is_file()
            else ""
        )
        progress_path.unlink(missing_ok=True)
        stage_trace = [line for line in progress.splitlines() if line.strip()]
        duration = time.monotonic() - attempt_started

        checkpoint_file_available = bool(
            transactional_direct
            and transactional_hdf_path is not None
            and transactional_hdf_path.is_file()
            and receipt_path.is_file()
        )
        if timed_out and not checkpoint_file_available:
            receipt_path.unlink(missing_ok=True)
            if transactional_hdf_path is not None:
                transactional_hdf_path.unlink(missing_ok=True)
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": True,
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                }
            )
            continue

        return_code = int(completed.returncode) if completed is not None else -9
        completed_stdout = completed.stdout if completed is not None else ""
        completed_stderr = completed.stderr if completed is not None else ""
        if not receipt_path.is_file():
            if transactional_hdf_path is not None:
                transactional_hdf_path.unlink(missing_ok=True)
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": False,
                    "return_code": return_code,
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                    "stderr_tail": _stream_tail(
                        completed_stderr or completed_stdout
                    ),
                }
            )
            continue

        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception:
            if transactional_hdf_path is not None:
                transactional_hdf_path.unlink(missing_ok=True)
            raise
        finally:
            receipt_path.unlink(missing_ok=True)
        transient_error = str(receipt.get("error") or "")
        validation_checkpoint_emitted = any(
            stage.endswith("validation-checkpoint-written")
            for stage in stage_trace
        )
        retryable_managed_error = any(
            transient_error.startswith(prefix)
            for prefix in (
                "System.AccessViolationException:",
                "System.ArrayTypeMismatchException:",
                "System.EntryPointNotFoundException:",
                "System.NullReferenceException:",
                "System.ArgumentOutOfRangeException:",
                "System.IndexOutOfRangeException:",
            )
        ) or bool(
            is_wine_runtime()
            and receipt.get("status") == "error"
            and transient_error
            and not validation_checkpoint_emitted
        )
        if (
            retryable_managed_error
            and receipt.get("status") != "persisted-awaiting-validation"
            and attempt < max_attempts
        ):
            if transactional_hdf_path is not None:
                transactional_hdf_path.unlink(missing_ok=True)
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": False,
                    "return_code": return_code,
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                    "managed_error": transient_error,
                    "stderr_tail": _stream_tail(completed_stderr),
                }
            )
            continue
        receipt.update(
            {
                "return_code": return_code,
                "process_duration_seconds": duration,
                "total_duration_seconds": time.monotonic() - started,
                "attempt_count": attempt,
                "failed_attempts": failed_attempts,
                "stdout_tail": _stream_tail(completed_stdout),
                "stderr_tail": _stream_tail(completed_stderr),
                "stage_trace": stage_trace,
            }
        )
        # A fatal CLR callback can overwrite the helper's receipt status after
        # the durable validation checkpoint is written. Treat the stage trace
        # as the checkpoint marker; promotion still requires every independent
        # candidate-HDF topology and ordered-center check below to pass.
        post_save_checkpoint_recovery = bool(
            transactional_direct
            and receipt.get("mesh_saved") is True
            and transactional_hdf_path is not None
            and transactional_hdf_path.is_file()
            and validation_checkpoint_emitted
            and any(
                stage.endswith("validation-reopen-started")
                for stage in stage_trace
            )
        )
        save_interruption_recovery = bool(
            transactional_direct
            and receipt.get("status") == "generated-awaiting-persistence"
            and transactional_hdf_path is not None
            and transactional_hdf_path.is_file()
            and (timed_out or return_code != 0)
            and any(
                stage.endswith("persistence-attempt-checkpoint-written")
                for stage in stage_trace
            )
            and any(
                stage.endswith("mesh-save-overload-5")
                for stage in stage_trace
            )
        )
        checkpoint_recovery = bool(
            post_save_checkpoint_recovery or save_interruption_recovery
        )
        receipt["checkpoint_recovery_attempted"] = checkpoint_recovery
        receipt["post_save_checkpoint_recovery_attempted"] = (
            post_save_checkpoint_recovery
        )
        receipt["save_interruption_recovery_attempted"] = (
            save_interruption_recovery
        )
        if return_code != 0 and not receipt.get("error") and not checkpoint_recovery:
            receipt["error"] = (
                f"Managed RasMapper mesh host exited {return_code}: "
                f"{receipt['stderr_tail'] or receipt['stdout_tail']}"
            )
        if transactional_direct:
            assert transactional_hdf_path is not None
            topology_checks = {
                "helper_status_complete": (
                    receipt.get("status") == "complete" or checkpoint_recovery
                ),
                "helper_return_code_zero": (
                    return_code == 0 or checkpoint_recovery
                ),
                "mesh_saved": (
                    receipt.get("mesh_saved") is True
                    or save_interruption_recovery
                ),
                "feature_table_written": (
                    receipt.get("feature_table_written") is True
                ),
                "mesh_points_set_feature_retained": (
                    receipt.get(
                        "mesh_points_set_feature_row_reference_matches_generated"
                    )
                    is True
                ),
                "mesh_points_feature_table_written": (
                    receipt.get("mesh_points_feature_table_written") is True
                ),
                "feature_table_restored_after_mesh_points": (
                    receipt.get("feature_table_restored_after_mesh_points")
                    is True
                ),
                "generated_centers_payload_complete": (
                    receipt.get("cell_centers_extracted") is True
                    and isinstance(receipt.get("cell_centers"), list)
                    and len(receipt.get("cell_centers")) == expected_cell_count
                ),
                "reopened_topology_validated": (
                    receipt.get("reopened_topology_validated") is True
                    or checkpoint_recovery
                ),
                "reopened_centers_validated": (
                    receipt.get("reopened_centers_validated") is True
                    or checkpoint_recovery
                ),
                "reopened_center_error_within_tolerance": (
                    float(receipt.get("reopened_center_max_abs_error") or 0.0)
                    <= _CENTER_ABSOLUTE_TOLERANCE
                ),
                "generated_cell_count_exact": (
                    int(receipt.get("cell_count") or 0) == expected_cell_count
                ),
                "generated_face_count_exact": (
                    int(receipt.get("face_count") or 0) == expected_face_count
                ),
                "reopened_cell_count_exact": (
                    int(receipt.get("reopened_cell_count") or 0)
                    == expected_cell_count
                    or checkpoint_recovery
                ),
                "reopened_face_count_exact": (
                    int(receipt.get("reopened_face_count") or 0)
                    == expected_face_count
                    or checkpoint_recovery
                ),
            }
            receipt["transactional_topology_checks"] = topology_checks
            receipt["transactional_temp_same_directory"] = (
                transactional_hdf_path.parent == geom_hdf_path.parent
            )
            receipt["transactional_replace_completed"] = False
            receipt["original_sha256_before"] = original_sha256
            candidate_exists = transactional_hdf_path.is_file()
            topology_checks["candidate_exists"] = candidate_exists
            if candidate_exists:
                try:
                    hdf_inspection = _inspect_transactional_candidate(
                        transactional_hdf_path,
                        mesh_name,
                        expected_cell_count,
                        expected_face_count,
                        generated_cell_centers=receipt.get("cell_centers"),
                        require_generated_center_match=True,
                    )
                except Exception as exc:
                    hdf_inspection = {
                        "mesh_name": mesh_name,
                        "checks": {"hdf_structure_readable": False},
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                receipt["transactional_hdf_inspection"] = hdf_inspection
                topology_checks.update(hdf_inspection["checks"])
                if checkpoint_recovery:
                    checkpoint_candidate_exact = all(
                        hdf_inspection["checks"].values()
                    )
                    topology_checks["checkpoint_recovery_candidate_exact"] = (
                        checkpoint_candidate_exact
                    )
            receipt["candidate_sha256"] = (
                _sha256(transactional_hdf_path) if candidate_exists else ""
            )
            if not all(topology_checks.values()):
                transactional_hdf_path.unlink(missing_ok=True)
                failed_names = [
                    name for name, passed in topology_checks.items()
                    if not passed
                ]
                if save_interruption_recovery and attempt < max_attempts:
                    failed_attempts.append(
                        {
                            "attempt": attempt,
                            "timed_out": timed_out,
                            "return_code": return_code,
                            "duration_seconds": duration,
                            "stage_trace": stage_trace,
                            "save_interruption_candidate_failed_checks": (
                                failed_names
                            ),
                            "stderr_tail": _stream_tail(completed_stderr),
                        }
                    )
                    continue
                receipt["status"] = "error"
                if not receipt.get("error"):
                    receipt["error"] = (
                        "Transactional direct mesh persistence failed exact "
                        "topology checks: " + ", ".join(failed_names)
                    )
                receipt["original_sha256_after"] = _sha256(geom_hdf_path)
                return receipt
            if _sha256(geom_hdf_path) != original_sha256:
                transactional_hdf_path.unlink(missing_ok=True)
                receipt["status"] = "error"
                receipt["error"] = (
                    "Geometry HDF changed during transactional mesh generation; "
                    "the candidate was discarded."
                )
                receipt["original_sha256_after"] = _sha256(geom_hdf_path)
                return receipt
            if (
                transaction_lock_token is None
                or not _transaction_lock_owned(
                    geom_hdf_path,
                    transaction_lock_token,
                )
            ):
                transactional_hdf_path.unlink(missing_ok=True)
                receipt["status"] = "error"
                receipt["error"] = (
                    "Transactional mesh lock ownership changed before replace; "
                    "the candidate was discarded."
                )
                receipt["original_sha256_after"] = _sha256(geom_hdf_path)
                return receipt
            try:
                os.replace(transactional_hdf_path, geom_hdf_path)
            except Exception:
                transactional_hdf_path.unlink(missing_ok=True)
                raise
            receipt["transactional_replace_completed"] = True
            receipt["original_sha256_after"] = _sha256(geom_hdf_path)
            if checkpoint_recovery:
                receipt["checkpoint_recovery_completed"] = True
                receipt["post_save_checkpoint_recovery_completed"] = (
                    post_save_checkpoint_recovery
                )
                receipt["save_interruption_recovery_completed"] = (
                    save_interruption_recovery
                )
                receipt["status"] = "complete"
                receipt["error"] = ""
                receipt["mesh_saved"] = True
                receipt["reopened_topology_validated"] = True
                receipt["reopened_centers_validated"] = True
                receipt["reopened_cell_count"] = expected_cell_count
                receipt["reopened_face_count"] = expected_face_count
        return receipt

    raise RuntimeError(
        "Managed RasMapper mesh host exhausted "
        f"{max_attempts} isolated attempts for '{mesh_name}': "
        f"{json.dumps(failed_attempts, sort_keys=True)}"
    )


def run_managed_mesh_host(
    geom_hdf_path: Union[str, Path],
    mesh_name: str,
    hecras_dir: Union[str, Path],
    *,
    min_face_length_ratio: float = 0.05,
    timeout_seconds: float = 600.0,
    max_attempts: int = 3,
    attempt_timeout_seconds: Optional[float] = None,
    persistence_mode: str = "auto",
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    cell_size: Optional[float] = None,
    seed_generation_mode: str = "regenerate_then_fallback",
) -> dict[str, Any]:
    """Generate one RAS Mapper mesh in an isolated CLR process.

    ``persistence_mode="auto"`` preserves the established behavior. The
    opt-in ``"transactional_direct"`` path holds a cooperative same-directory
    O_EXCL lock from before the source hash/copy through final hash/replace.
    This lock coordinates ras-commander writers only; a node-local project copy
    per task remains required to isolate non-cooperating product processes.
    """
    requested_mode = str(persistence_mode).strip().lower()
    arguments = {
        "min_face_length_ratio": min_face_length_ratio,
        "timeout_seconds": timeout_seconds,
        "max_attempts": max_attempts,
        "attempt_timeout_seconds": attempt_timeout_seconds,
        "persistence_mode": requested_mode,
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "cell_size": cell_size,
        "seed_generation_mode": seed_generation_mode,
    }
    if requested_mode != "transactional_direct":
        return _run_managed_mesh_host_without_transaction_lock(
            geom_hdf_path,
            mesh_name,
            hecras_dir,
            **arguments,
        )

    if expected_cell_count is None or expected_face_count is None:
        raise ValueError(
            "transactional_direct persistence requires expected_cell_count "
            "and expected_face_count"
        )
    geom_hdf_path = Path(geom_hdf_path)
    lock_path = _transaction_lock_path(geom_hdf_path)
    with _transaction_lock(geom_hdf_path, mesh_name) as owner:
        receipt = _run_managed_mesh_host_without_transaction_lock(
            geom_hdf_path,
            mesh_name,
            hecras_dir,
            transaction_lock_token=owner["token"],
            **arguments,
        )
        receipt["transaction_lock"] = {
            "acquired": True,
            "cooperative_only": True,
            "scope": _LOCK_SCOPE,
            "lock_file_name": lock_path.name,
            "owner_process_id": owner["process_id"],
        }
    receipt["transaction_lock"]["released"] = bool(
        owner.get("released_by_owner")
    )
    return receipt
