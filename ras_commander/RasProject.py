"""Read-only project asset inspection and fail-closed atomic staging.

The helpers in this module are application-neutral.  They do not execute or
preprocess HEC-RAS, mutate the source project, or use the package-global
``ras`` object.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, NoReturn, Optional, Union

import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPrj import RasPrj, init_ras_project
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .schemas import DATAFRAME_SCHEMAS

logger = get_logger(__name__)

InspectionDepth = Literal["project", "current_plan", "all_plans"]
DssInspection = Literal["none", "catalog", "coverage"]
PublicationOutcome = Literal["not_committed", "committed", "unknown"]

_INVENTORY_SCHEMA_VERSION = 1
_INVENTORY_COLUMNS = [
    column["name"]
    for column in DATAFRAME_SCHEMAS["project_asset_inventory"]["columns"]
]

_RASMAP_KINDS = {
    "projection_path": "projection",
    "profile_lines_path": "stored_map",
    "soil_layer_path": "soils",
    "infiltration_hdf_path": "infiltration",
    "landcover_hdf_path": "landcover",
    "terrain_hdf_path": "terrain",
    "reference_map_layer_path": "stored_map",
    "basemap_layer_path": "stored_map",
}

_LOCK_SUFFIXES = {".lck", ".lock"}
_STAGE_METADATA_DIR = ".ras-commander"
_STAGE_MANIFEST = "stage.json"
_TEMP_SENTINEL = ".rascommander-stage-owned"


class ProjectStageError(RuntimeError):
    """Base exception for fail-closed project staging failures."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        publication_outcome: PublicationOutcome = "not_committed",
    ) -> None:
        self.reason_code = reason_code
        self.publication_outcome = publication_outcome
        self.publication_committed = publication_outcome == "committed"
        super().__init__(f"{reason_code}: {message}")


class ProjectPopulationError(ProjectStageError):
    """The source or staged project population is invalid or inconsistent."""


class ProjectPathAmbiguityError(ProjectStageError):
    """A physical path identity or reparse-point invariant cannot be proved."""


class ProjectLockedError(ProjectStageError):
    """An exclusive staging or source access invariant failed."""


class ProjectDriftError(ProjectStageError):
    """The source population changed while it was being staged."""


class ProjectCopyVerificationError(ProjectStageError):
    """The copied population does not exactly match its source snapshot."""


class ProjectPublicationError(ProjectStageError):
    """Durable publication or post-publication verification failed."""


class _InventoryHashCache:
    def __init__(self) -> None:
        self.values: dict[Path, tuple[tuple[int, int, int, int], str]] = {}

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int]:
        info = _io_path(path).stat()
        return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino

    def digest(self, path: Path) -> str:
        identity = self._identity(path)
        cached = self.values.get(path)
        if cached is not None:
            if cached[0] != identity:
                raise RuntimeError(f"Referenced file changed during inventory: {path}")
            return cached[1]
        digest = _sha256_file(path)
        if self._identity(path) != identity:
            raise RuntimeError(f"Referenced file changed while hashing: {path}")
        self.values[path] = (identity, digest)
        return digest

    def verify(self) -> None:
        for path, (identity, _) in self.values.items():
            if self._identity(path) != identity:
                raise RuntimeError(f"Referenced file changed during inventory: {path}")


_ACTIVE_INVENTORY_HASH_CACHE: ContextVar[Optional[_InventoryHashCache]] = ContextVar(
    "ras_project_inventory_hash_cache",
    default=None,
)


@dataclass(frozen=True)
class StageProjectResult:
    """Evidence returned after a project tree is atomically published."""

    source_project_file: Path
    destination_project_file: Path
    destination_root: Path
    source_fingerprint_before: str
    source_fingerprint_after: str
    copied_fingerprint: str
    published_fingerprint: str
    copied_file_count: int
    copied_bytes: int
    publication_state: Literal["published"]
    execution_readiness: Literal["ready", "not_ready", "unknown"]
    assets: pd.DataFrame
    ras_object: RasPrj


@dataclass(frozen=True)
class _FileSnapshot:
    relative_path: str
    size_bytes: int
    mtime_ns: int
    volume_id: str
    file_id: str
    sha256: str


def _io_path(path: Union[str, Path]) -> Path:
    """Return a Windows extended-length path for private filesystem I/O."""
    candidate = Path(path)
    if os.name != "nt":
        return candidate

    raw = os.path.abspath(os.fspath(candidate))
    if raw.startswith("\\\\?\\"):
        return Path(raw)
    if raw.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{raw[2:]}")
    return Path(f"\\\\?\\{raw}")


def _public_path(path: Union[str, Path]) -> Path:
    """Strip a Windows extended-length prefix from a path returned by an API."""
    candidate = Path(path)
    if os.name != "nt":
        return candidate

    raw = os.fspath(candidate)
    if raw.startswith("\\\\?\\UNC\\"):
        return Path(f"\\\\{raw[8:]}")
    if raw.startswith("\\\\?\\"):
        return Path(raw[4:])
    return candidate


def _path_exists(path: Union[str, Path]) -> bool:
    return os.path.exists(_io_path(path))


def _path_lexists(path: Union[str, Path]) -> bool:
    return os.path.lexists(_io_path(path))


def _path_is_file(path: Union[str, Path]) -> bool:
    try:
        return stat.S_ISREG(os.stat(_io_path(path)).st_mode)
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _io_path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    info = _io_path(path).lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & marker)


def _assert_regular_path(path: Path, *, expected_directory: bool = False) -> os.stat_result:
    if _is_reparse_point(path):
        raise ProjectPathAmbiguityError(
            "reparse_point",
            f"Reparse points and symbolic links are not supported: {path}",
        )
    info = _io_path(path).stat()
    if expected_directory and not stat.S_ISDIR(info.st_mode):
        raise ProjectPathAmbiguityError(
            "unexpected_path_type",
            f"Expected a directory: {path}",
        )
    if not expected_directory and not stat.S_ISREG(info.st_mode):
        raise ProjectPathAmbiguityError(
            "unexpected_path_type",
            f"Expected a regular file: {path}",
        )
    return info


def _assert_no_reparse_ancestry(path: Path) -> None:
    """Reject any existing reparse point from ``path`` through its ancestry."""
    for candidate in (path, *path.parents):
        try:
            if _path_lexists(candidate) and _is_reparse_point(candidate):
                raise ProjectPathAmbiguityError(
                    "reparse_point",
                    f"Reparse points and symbolic links are not supported: {candidate}",
                )
        except ProjectPathAmbiguityError:
            raise
        except OSError as exc:
            raise ProjectPathAmbiguityError(
                "path_identity_unavailable",
                f"Could not inspect path ancestry: {candidate}",
            ) from exc


def _valid_project_files(folder: Path) -> list[Path]:
    projects: list[Path] = []
    candidates = [
        folder / entry.name
        for entry in os.scandir(_io_path(folder))
        if Path(entry.name).suffix.lower() == ".prj"
    ]
    for candidate in sorted(candidates, key=lambda item: item.name.casefold()):
        if _is_reparse_point(candidate) or not _path_is_file(candidate):
            continue
        try:
            with _io_path(candidate).open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as stream:
                if any(line.startswith("Proj Title=") for line in stream):
                    projects.append(candidate)
        except OSError:
            continue
    return projects


def _resolve_project_file(project: Union[str, Path]) -> Path:
    path = RasUtils.safe_resolve(Path(project))
    if _path_is_file(path):
        if path.suffix.lower() != ".prj":
            raise ValueError(f"Expected a HEC-RAS .prj file: {path}")
        _assert_regular_path(path)
        projects = _valid_project_files(path.parent)
        if path not in projects:
            raise ValueError(f"File is not a HEC-RAS project (missing Proj Title=): {path}")
        return path
    if not _path_exists(path):
        raise FileNotFoundError(f"Project path does not exist: {path}")
    _assert_regular_path(path, expected_directory=True)
    projects = _valid_project_files(path)
    if not projects:
        raise FileNotFoundError(f"No valid HEC-RAS .prj file found in: {path}")
    if len(projects) != 1:
        names = ", ".join(item.name for item in projects)
        raise ValueError(f"Ambiguous HEC-RAS project directory ({len(projects)} projects): {names}")
    return projects[0]


def _same_file(left: Path, right: Path) -> bool:
    return os.path.samefile(_io_path(left), _io_path(right))


def _source_contains_destination(source_root: Path, destination_parent: Path) -> bool:
    """Prove overlap through existing ancestor identities, including mapped aliases."""
    candidate = destination_parent
    while True:
        if _same_file(source_root, candidate):
            return True
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent


def _explicit_ras(
    project_file: Path,
    ras_object: Optional[RasPrj],
    *,
    load_hdf_metadata: bool = True,
) -> RasPrj:
    if ras_object is None:
        return init_ras_project(
            project_file,
            ras_version=_declared_current_plan_version(project_file),
            ras_object=RasPrj(),
            load_results_summary=False,
            load_hdf_metadata=load_hdf_metadata,
            hide_intro=True,
        )
    if not isinstance(ras_object, RasPrj):
        raise TypeError("ras_object must be an initialized RasPrj instance")
    ras_object.check_initialized()
    object_project = Path(ras_object.prj_file)
    try:
        same_project = _same_file(project_file, object_project)
    except OSError as exc:
        raise ProjectPathAmbiguityError(
            "project_identity_unavailable",
            "Could not prove the physical identity of project and ras_object",
        ) from exc
    if not same_project:
        raise ValueError(
            "ras_object does not identify the same physical project file as project"
        )
    return ras_object


def _read_keys(path: Path, key: str) -> list[str]:
    if not _path_is_file(path):
        return []
    values: list[str] = []
    with _io_path(path).open(
        "r",
        encoding="utf-8",
        errors="replace",
        newline="",
    ) as stream:
        prefix = f"{key}="
        for line in stream:
            if line.startswith(prefix):
                values.append(line[len(prefix):].strip())
    return values


def _read_key(path: Path, key: str) -> Optional[str]:
    values = _read_keys(path, key)
    return values[0] if values else None


def _declared_current_plan_version(project_file: Path) -> Optional[str]:
    current = (_read_key(project_file, "Current Plan") or "").strip()
    if not re.fullmatch(r"[pP]\d{2,3}", current):
        return None
    plan_file = project_file.parent / f"{project_file.stem}.{current.lower()}"
    version = (_read_key(plan_file, "Program Version") or "").strip()
    match = re.fullmatch(r"(\d+)\.(\d)0", version)
    return f"{match.group(1)}.{match.group(2)}" if match else (version or None)


def _validate_current_plan(project_file: Path, ras_object: RasPrj) -> str:
    current = (_read_key(project_file, "Current Plan") or "").strip()
    if not re.fullmatch(r"[pP]\d{2,3}", current):
        raise ProjectPopulationError(
            "current_plan_invalid",
            "Project Current Plan must be an exact p## or p### declaration",
        )
    number = current[1:]
    matches = ras_object.plan_df.loc[
        ras_object.plan_df["plan_number"].astype(str) == number
    ]
    if len(matches) != 1:
        raise ProjectPopulationError(
            "current_plan_undeclared",
            f"Current Plan {current.lower()} does not resolve to one declared plan",
        )
    expected_path = project_file.parent / f"{project_file.stem}.p{number}"
    if not _path_is_file(expected_path):
        raise ProjectPopulationError(
            "current_plan_missing",
            f"Current Plan file is unavailable: {expected_path.name}",
        )
    actual_path = Path(str(matches.iloc[0].get("full_path")))
    try:
        same_plan = _same_file(expected_path, actual_path)
    except OSError as exc:
        raise ProjectPathAmbiguityError(
            "current_plan_identity_unavailable",
            "Could not prove Current Plan physical file identity",
        ) from exc
    if not same_plan:
        raise ProjectPopulationError(
            "current_plan_mismatch",
            "Current Plan metadata resolves to a different physical file",
        )
    return number


def _parse_ras_time(value: str) -> Optional[datetime]:
    match = re.fullmatch(r"(\d{1,2}[A-Za-z]{3}\d{4}),(\d{4})", value.strip())
    if not match:
        return None
    date_text, time_text = match.groups()
    hours, minutes = int(time_text[:2]), int(time_text[2:])
    try:
        parsed = datetime.strptime(date_text.title(), "%d%b%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if hours == 24 and minutes == 0:
        return parsed + timedelta(days=1)
    if hours > 23 or minutes > 59:
        return None
    return parsed.replace(hour=hours, minute=minutes)


def _plan_window(plan_path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    raw = _read_key(plan_path, "Simulation Date")
    if not raw:
        return None, None
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        return None, None
    return _parse_ras_time(",".join(parts[:2])), _parse_ras_time(",".join(parts[2:]))


def _resolve_reference(owner: Path, raw: str) -> Path:
    expanded = os.path.expandvars(raw.strip().strip('"'))
    if os.name == "nt":
        expanded = expanded.replace("/", "\\")
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = owner.parent / candidate
    return RasUtils.safe_resolve(candidate)


def _path_scope(project_root: Path, path: Path) -> tuple[str, Optional[bool]]:
    try:
        root_real = os.path.normcase(os.path.realpath(_io_path(project_root)))
        path_real = os.path.normcase(os.path.realpath(_io_path(path)))
        if os.path.commonpath([root_real, path_real]) == root_real:
            return "internal", True
        return "external", False
    except (OSError, ValueError):
        return "ambiguous", None


def _asset_id(*parts: Any) -> str:
    encoded = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(encoded.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]


def _path_facts(path: Optional[Path], *, hash_file: bool) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "exists": None,
        "is_file": None,
        "is_dir": None,
        "volume_id": None,
        "file_id": None,
        "size_bytes": None,
        "mtime_ns": None,
        "sha256": None,
        "access_error": None,
    }
    if path is None:
        return facts
    try:
        info = _io_path(path).stat()
        is_file = stat.S_ISREG(info.st_mode)
        is_dir = stat.S_ISDIR(info.st_mode)
        facts.update(
            exists=True,
            is_file=is_file,
            is_dir=is_dir,
            volume_id=str(info.st_dev),
            file_id=str(info.st_ino),
            size_bytes=info.st_size if is_file else None,
            mtime_ns=info.st_mtime_ns,
        )
        if hash_file and is_file:
            cache = _ACTIVE_INVENTORY_HASH_CACHE.get()
            facts["sha256"] = cache.digest(path) if cache is not None else _sha256_file(path)
    except FileNotFoundError:
        facts.update(exists=False, is_file=False, is_dir=False)
    except OSError as exc:
        facts["access_error"] = str(exc)[:500]
    return facts


def _add_asset(
    rows: list[dict[str, Any]],
    *,
    inventory_id: str,
    depth: InspectionDepth,
    project_root: Path,
    kind: str,
    role: str,
    owner: Optional[Path],
    raw: Optional[str],
    path: Optional[Path],
    required: Optional[bool],
    source_api: str,
    hash_files: bool,
    plan_number: Optional[str] = None,
    unsteady_number: Optional[str] = None,
    parent_asset_id: Optional[str] = None,
    dataset_name: Optional[str] = None,
    expected_start: Optional[datetime] = None,
    expected_end: Optional[datetime] = None,
    state: Optional[str] = None,
    readiness: Optional[str] = None,
    reason_code: Optional[str] = None,
    detail: Optional[str] = None,
    occurrence: int = 0,
    id_discriminator: Optional[str] = None,
) -> str:
    facts = _path_facts(path, hash_file=hash_files)
    scope, portable = (
        ("ambiguous", None)
        if path is None or facts["access_error"] is not None
        else _path_scope(project_root, path)
    )
    if state is None:
        if facts["access_error"] is not None:
            state = "ambiguous"
            reason_code = reason_code or "path_access_failed"
            detail = detail or facts["access_error"]
        else:
            state = "available" if facts["exists"] else "missing"
    if readiness is None:
        if required is False:
            readiness = "not_required"
        elif state == "available":
            readiness = "ready" if required is True else "unknown"
        elif state == "missing":
            readiness = "not_ready" if required is True else "unknown"
        else:
            readiness = "unknown"
    if reason_code is None and state == "missing":
        reason_code = "path_missing"
    owner_hash = None
    if hash_files and owner is not None and _path_is_file(owner):
        cache = _ACTIVE_INVENTORY_HASH_CACHE.get()
        owner_hash = cache.digest(owner) if cache is not None else _sha256_file(owner)
    owner_identity: Any = owner
    if owner is not None:
        try:
            owner_identity = owner.relative_to(project_root).as_posix()
        except ValueError:
            owner_identity = str(owner)
    identifier = _asset_id(
        kind,
        role,
        plan_number,
        unsteady_number,
        owner_identity,
        raw,
        dataset_name,
        occurrence,
        id_discriminator,
    )
    row = {column: None for column in _INVENTORY_COLUMNS}
    row.update(
        inventory_schema_version=_INVENTORY_SCHEMA_VERSION,
        inventory_id=inventory_id,
        inspection_depth=depth,
        asset_id=identifier,
        parent_asset_id=parent_asset_id,
        asset_kind=kind,
        asset_role=role,
        plan_number=plan_number,
        unsteady_number=unsteady_number,
        required=required,
        owner_file=str(owner) if owner is not None else None,
        owner_sha256=owner_hash,
        reference_raw=raw,
        resolved_path=str(path) if path is not None else None,
        path_scope=scope,
        portable=portable,
        dataset_name=dataset_name,
        expected_start=expected_start,
        expected_end=expected_end,
        inspection_state=state,
        readiness=readiness,
        reason_code=reason_code,
        detail=detail,
        source_api=source_api,
        **{key: value for key, value in facts.items() if key != "access_error"},
    )
    rows.append(row)
    return identifier


def _as_values(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None and str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalized_optional_bool(value: Any) -> Optional[bool]:
    """Normalize mixed bool/string project fields without guessing other values."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _optional_text(value: Any) -> str:
    """Return stripped scalar text while preserving null as an empty value."""
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _add_implied_vector_sidecars(
    rows: list[dict[str, Any]],
    *,
    inventory_id: str,
    depth: InspectionDepth,
    project_root: Path,
    owner: Path,
    vector_path: Path,
    parent_asset_id: str,
    required: Optional[bool],
    hash_files: bool,
    plan_number: Optional[str] = None,
    occurrence: int = 0,
) -> list[Path]:
    """Inventory mechanically required ESRI Shapefile sidecars."""
    if vector_path.suffix.casefold() != ".shp":
        return []
    sidecars: list[Path] = []
    for sidecar_occurrence, suffix in enumerate((".shx", ".dbf")):
        sidecar = vector_path.with_suffix(suffix)
        _add_asset(
            rows,
            inventory_id=inventory_id,
            depth=depth,
            project_root=project_root,
            kind="unknown_reference",
            role="declared_input",
            owner=owner,
            raw=sidecar.name,
            path=sidecar,
            required=required,
            source_api="implied ESRI Shapefile sidecar",
            hash_files=hash_files,
            plan_number=plan_number,
            parent_asset_id=parent_asset_id,
            occurrence=(occurrence * 10) + sidecar_occurrence,
        )
        sidecars.append(sidecar)
    return sidecars


def _to_arrow_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=_INVENTORY_COLUMNS)
    integer_columns = {"inventory_schema_version", "size_bytes", "mtime_ns"}
    boolean_columns = {"required", "portable", "exists", "is_file", "is_dir"}
    timestamp_columns = {
        "expected_start",
        "expected_end",
        "available_start",
        "available_end",
    }
    for column in _INVENTORY_COLUMNS:
        if column in integer_columns:
            frame[column] = pd.array(frame[column], dtype="int64[pyarrow]")
        elif column in boolean_columns:
            frame[column] = pd.array(frame[column], dtype="bool[pyarrow]")
        elif column not in timestamp_columns:
            frame[column] = pd.array(frame[column], dtype="string[pyarrow]")
    for column in ("expected_start", "expected_end", "available_start", "available_end"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return frame.convert_dtypes(dtype_backend="pyarrow")


def _rebase_value(value: Any, old_root: Path, new_root: Path) -> Any:
    """Replace one staged-root prefix without touching unrelated values."""
    if isinstance(value, Path):
        public_value = _public_path(value)
        try:
            return new_root / public_value.relative_to(old_root)
        except ValueError:
            return value
    if isinstance(value, str):
        old_text = str(old_root)
        public_value = (
            str(_public_path(value))
            if os.name == "nt" and value.startswith("\\\\?\\")
            else value
        )
        normalized_value = os.path.normcase(public_value)
        normalized_old = os.path.normcase(old_text)
        if normalized_value == normalized_old:
            return str(new_root)
        for separator in ("\\", "/"):
            prefix = normalized_old.rstrip("\\/") + separator
            if normalized_value.startswith(prefix):
                return str(new_root) + public_value[len(old_text):]
        return value
    if isinstance(value, list):
        return [_rebase_value(item, old_root, new_root) for item in value]
    if isinstance(value, tuple):
        return tuple(_rebase_value(item, old_root, new_root) for item in value)
    if isinstance(value, set):
        return {_rebase_value(item, old_root, new_root) for item in value}
    if isinstance(value, dict):
        return {
            _rebase_value(key, old_root, new_root): _rebase_value(
                item,
                old_root,
                new_root,
            )
            for key, item in value.items()
        }
    return value


def _rebase_frame(frame: pd.DataFrame, old_root: Path, new_root: Path) -> pd.DataFrame:
    rebased = frame.copy(deep=True)
    for column in rebased.columns:
        if pd.api.types.is_object_dtype(rebased[column].dtype):
            rebased[column] = rebased[column].map(
                lambda value: _rebase_value(value, old_root, new_root)
            )
        elif pd.api.types.is_string_dtype(rebased[column].dtype):
            rebased[column] = pd.array(
                [
                    _rebase_value(value, old_root, new_root)
                    for value in rebased[column].tolist()
                ],
                dtype=rebased[column].dtype,
            )
    return rebased


def _rebase_ras_object(ras_object: RasPrj, old_root: Path, new_root: Path) -> RasPrj:
    """Rebase a validated explicit RasPrj before its tree is atomically renamed."""
    for attribute, value in vars(ras_object).items():
        if isinstance(value, pd.DataFrame):
            rebased = _rebase_frame(value, old_root, new_root)
        else:
            rebased = _rebase_value(value, old_root, new_root)
        setattr(ras_object, attribute, rebased)
    return ras_object


def _inspect_project_assets_impl(
    project: Union[str, Path],
    *,
    ras_object: Optional[RasPrj] = None,
    depth: InspectionDepth = "all_plans",
    hash_files: bool = False,
    dss_inspection: DssInspection = "none",
) -> pd.DataFrame:
    """Return a read-only, DataFrame-first inventory of linked project assets.

    DSS file references are inventoried, but DSS containers are not opened by
    this implementation.  Requests for ``catalog`` or ``coverage`` therefore
    remain explicit ``not_inspected`` dataset rows until the underlying reader
    has a proven source-immutable open contract.
    """
    if depth not in {"project", "current_plan", "all_plans"}:
        raise ValueError(f"Unsupported inspection depth: {depth}")
    if dss_inspection not in {"none", "catalog", "coverage"}:
        raise ValueError(f"Unsupported DSS inspection mode: {dss_inspection}")

    project_file = _resolve_project_file(project)
    project_root = project_file.parent
    ras_obj = _explicit_ras(
        project_file,
        ras_object,
        load_hdf_metadata=depth != "project",
    )
    if depth == "current_plan":
        _validate_current_plan(project_file, ras_obj)
    inventory_id = str(uuid.uuid4())
    rows: list[dict[str, Any]] = []

    project_id = _add_asset(
        rows,
        inventory_id=inventory_id,
        depth=depth,
        project_root=project_root,
        kind="project",
        role="declared_input",
        owner=project_file,
        raw=project_file.name,
        path=project_file,
        required=True,
        source_api="RasPrj",
        hash_files=hash_files,
    )

    current_plan = (_read_key(project_file, "Current Plan") or "").lower()
    current_number = current_plan[1:] if re.fullmatch(r"p\d{2,3}", current_plan) else None
    plans = ras_obj.plan_df.copy()
    if depth == "current_plan":
        plans = plans.loc[plans["plan_number"].astype(str) == str(current_number)]

    selected_unsteady_numbers = {
        str(value)
        for value in plans.get("unsteady_number", pd.Series(dtype=str)).dropna().tolist()
    }

    if depth == "project":
        component_plans = ras_obj.plan_df
        selected_unsteady_numbers = set()
    else:
        component_plans = plans

    referenced_geometries: set[str] = set()
    referenced_flows: set[tuple[str, str]] = set()
    project_scoped_components: dict[
        tuple[str, str],
        tuple[str, Optional[Path], str],
    ] = {}
    plan_asset_ids: dict[str, str] = {}
    filter_components = depth != "project"
    for occurrence, (_, plan) in enumerate(component_plans.iterrows()):
        plan_number = str(plan.get("plan_number"))
        plan_path = Path(str(plan.get("full_path")))
        plan_id = _add_asset(
            rows,
            inventory_id=inventory_id,
            depth=depth,
            project_root=project_root,
            kind="plan",
            role="declared_input",
            owner=project_file,
            raw=f"p{plan_number}",
            path=plan_path,
            required=True,
            source_api="RasPrj.plan_df",
            hash_files=hash_files,
            plan_number=plan_number,
            parent_asset_id=project_id,
            occurrence=occurrence,
        )
        plan_asset_ids[plan_number] = plan_id
        geometry_number = plan.get("geometry_number")
        if pd.notna(geometry_number):
            referenced_geometries.add(str(geometry_number))
        flow_number = plan.get("Flow File")
        if pd.notna(flow_number):
            flow_type = _optional_text(plan.get("flow_type")).casefold()
            if pd.notna(plan.get("unsteady_number")):
                flow_kind = "unsteady_flow"
            elif flow_type == "quasi-unsteady":
                flow_kind = "quasi_unsteady_flow"
            else:
                flow_kind = "steady_flow"
            if flow_kind == "quasi_unsteady_flow":
                quasi_reference = f"q{flow_number}"
                flow_path_raw = _optional_text(plan.get("Flow Path"))
                flow_path = Path(flow_path_raw) if flow_path_raw else None
                if depth == "project":
                    project_scoped_components.setdefault(
                        (flow_kind, quasi_reference.casefold()),
                        (quasi_reference, flow_path, "RasPrj.plan_df"),
                    )
                else:
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind=flow_kind,
                        role="declared_input",
                        owner=plan_path,
                        raw=quasi_reference,
                        path=flow_path,
                        required=True,
                        source_api="RasPrj.plan_df",
                        hash_files=hash_files,
                        plan_number=plan_number,
                        parent_asset_id=plan_id,
                        occurrence=occurrence,
                        state="ambiguous" if flow_path is None else None,
                        readiness="not_ready" if flow_path is None else None,
                        reason_code="missing_flow_path" if flow_path is None else None,
                    )
            else:
                referenced_flows.add((flow_kind, str(flow_number)))

        sediment_reference = _read_key(plan_path, "Sediment File")
        if sediment_reference:
            normalized_sediment = sediment_reference.strip()
            sediment_match = re.fullmatch(r"[sS](\d{2,3})", normalized_sediment)
            sediment_path = (
                project_root / f"{project_file.stem}.s{sediment_match.group(1)}"
                if sediment_match
                else None
            )
            if depth == "project":
                project_scoped_components.setdefault(
                    ("sediment", normalized_sediment.casefold()),
                    (
                        normalized_sediment,
                        sediment_path,
                        "RasPlan.Sediment File",
                    ),
                )
            else:
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="sediment",
                    role="declared_input",
                    owner=plan_path,
                    raw=normalized_sediment,
                    path=sediment_path,
                    required=True,
                    source_api="RasPlan.Sediment File",
                    hash_files=hash_files,
                    plan_number=plan_number,
                    parent_asset_id=plan_id,
                    occurrence=occurrence,
                    state="ambiguous" if sediment_path is None else None,
                    readiness="not_ready" if sediment_path is None else None,
                    reason_code=(
                        "invalid_component_reference"
                        if sediment_path is None
                        else None
                    ),
                )

        if depth != "project":
            expected_start, expected_end = _plan_window(plan_path)
            version = (_read_key(plan_path, "Program Version") or "").strip()
            try:
                major_version = int(version.split(".", 1)[0])
            except (TypeError, ValueError):
                major_version = None
            plan_hdf = Path(str(plan_path) + ".hdf")
            _add_asset(
                rows,
                inventory_id=inventory_id,
                depth=depth,
                project_root=project_root,
                kind="plan_hdf",
                role="existing_result",
                owner=plan_path,
                raw=plan_hdf.name,
                path=plan_hdf,
                required=False,
                source_api="RasPrj.plan_df.HDF_Results_Path",
                hash_files=hash_files,
                plan_number=plan_number,
                parent_asset_id=plan_id,
                expected_start=expected_start,
                expected_end=expected_end,
            )
            geom_path_raw = plan.get("Geom Path")
            if pd.notna(geom_path_raw):
                geom_hdf = Path(str(geom_path_raw) + ".hdf")
                flow_type = str(plan.get("flow_type") or "").casefold()
                required_hdf = not (
                    (major_version is not None and major_version < 5)
                    or flow_type in {"steady", "quasi-unsteady"}
                )
                hdf_state = None if required_hdf else "not_applicable"
                if major_version is not None and major_version < 5:
                    hdf_reason = "not_used_before_hec_ras_5"
                elif flow_type == "steady":
                    hdf_reason = "not_required_for_steady_plan"
                elif flow_type == "quasi-unsteady":
                    hdf_reason = "not_required_for_quasi_unsteady_plan"
                else:
                    hdf_reason = None
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="geometry_hdf",
                    role="derived_prerequisite",
                    owner=plan_path,
                    raw=geom_hdf.name,
                    path=geom_hdf,
                    required=required_hdf,
                    source_api="RasPrj.plan_df.Geom Path",
                    hash_files=hash_files,
                    plan_number=plan_number,
                    parent_asset_id=plan_id,
                    state=hdf_state,
                    readiness="not_required" if hdf_state else None,
                    reason_code=hdf_reason,
                )
            unsteady_number = plan.get("unsteady_number")
            if pd.notna(unsteady_number):
                unsteady_path = Path(str(plan.get("Flow Path")))
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="unsteady_hdf",
                    role="derived_prerequisite",
                    owner=unsteady_path,
                    raw=f"{unsteady_path.name}.hdf",
                    path=Path(str(unsteady_path) + ".hdf"),
                    required=None,
                    source_api="RasPrj.plan_df.Flow Path",
                    hash_files=hash_files,
                    plan_number=plan_number,
                    unsteady_number=str(unsteady_number),
                    parent_asset_id=plan_id,
                )

    if depth == "project":
        declared_components = (
            ("QuasiSteady File", "quasi_unsteady_flow", "q"),
            ("Sediment File", "sediment", "s"),
        )
        for key, kind, prefix in declared_components:
            for raw in _read_keys(project_file, key):
                normalized = raw.strip()
                match = re.fullmatch(rf"[{prefix}{prefix.upper()}](\d{{2,3}})", normalized)
                canonical = f"{prefix}{match.group(1)}" if match else normalized
                path = (
                    project_root / f"{project_file.stem}.{canonical}"
                    if match
                    else None
                )
                project_scoped_components.setdefault(
                    (kind, canonical.casefold()),
                    (canonical, path, f"RasPrj.project_file.{key}"),
                )
        for occurrence, ((kind, _), component) in enumerate(
            sorted(project_scoped_components.items())
        ):
            raw, path, source_api = component
            _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind=kind,
                    role="declared_input",
                    owner=project_file,
                    raw=raw,
                    path=path,
                    required=True,
                    source_api=source_api,
                    hash_files=hash_files,
                    parent_asset_id=project_id,
                    occurrence=occurrence,
                    state="ambiguous" if path is None else None,
                    readiness="not_ready" if path is None else None,
                    reason_code=(
                        "invalid_component_reference" if path is None else None
                    ),
                )

    for occurrence, (_, geometry) in enumerate(ras_obj.geom_df.iterrows()):
        number = str(geometry.get("geom_number"))
        if filter_components and number not in referenced_geometries:
            continue
        path = Path(str(geometry.get("full_path")))
        plan_numbers: list[Optional[str]] = [None]
        if depth != "project":
            plan_numbers = [
                str(plan.get("plan_number"))
                for _, plan in plans.iterrows()
                if str(plan.get("geometry_number")) == number
            ]
        for scope_index, plan_number in enumerate(plan_numbers):
            _add_asset(
                rows,
                inventory_id=inventory_id,
                depth=depth,
                project_root=project_root,
                kind="geometry",
                role="declared_input",
                owner=project_file,
                raw=f"g{number}",
                path=path,
                required=True,
                source_api="RasPrj.geom_df",
                hash_files=hash_files,
                plan_number=plan_number,
                parent_asset_id=plan_asset_ids.get(plan_number, project_id),
                occurrence=occurrence * max(len(plan_numbers), 1) + scope_index,
            )

    flow_frames = (("steady_flow", ras_obj.flow_df), ("unsteady_flow", ras_obj.unsteady_df))
    for kind, frame in flow_frames:
        for occurrence, (_, flow) in enumerate(frame.iterrows()):
            number_key = "flow_number" if kind == "steady_flow" else "unsteady_number"
            number = str(flow.get(number_key))
            if filter_components and (kind, number) not in referenced_flows:
                continue
            path = Path(str(flow.get("full_path")))
            plan_numbers = [None]
            if depth != "project":
                plan_numbers = [
                    str(plan.get("plan_number"))
                    for _, plan in plans.iterrows()
                    if (
                        (
                            kind == "unsteady_flow"
                            and str(plan.get("unsteady_number")) == number
                        )
                        or (
                            kind == "steady_flow"
                            and pd.isna(plan.get("unsteady_number"))
                            and str(plan.get("Flow File")) == number
                        )
                    )
                ]
            for scope_index, plan_number in enumerate(plan_numbers):
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind=kind,
                    role="declared_input",
                    owner=project_file,
                    raw=("f" if kind == "steady_flow" else "u") + number,
                    path=path,
                    required=True,
                    source_api=(
                        "RasPrj.flow_df"
                        if kind == "steady_flow"
                        else "RasPrj.unsteady_df"
                    ),
                    hash_files=hash_files,
                    plan_number=plan_number,
                    unsteady_number=number if kind == "unsteady_flow" else None,
                    parent_asset_id=plan_asset_ids.get(plan_number, project_id),
                    occurrence=occurrence * max(len(plan_numbers), 1) + scope_index,
                )

    rasmap_path = project_root / f"{project_file.stem}.rasmap"
    rasmap_id: Optional[str] = None
    if _path_exists(rasmap_path) or getattr(
        ras_obj,
        "rasmap_df",
        pd.DataFrame(),
    ).shape[0]:
        rasmap_id = _add_asset(
            rows,
            inventory_id=inventory_id,
            depth=depth,
            project_root=project_root,
            kind="rasmap",
            role="declared_input",
            owner=project_file,
            raw=rasmap_path.name,
            path=rasmap_path,
            required=False,
            source_api="RasMap.initialize_rasmap_df",
            hash_files=hash_files,
            parent_asset_id=project_id,
        )

    rasmap_df = getattr(ras_obj, "rasmap_df", pd.DataFrame())
    seen_map_paths: set[str] = set()
    if _path_is_file(rasmap_path) and rasmap_df.empty:
        _add_asset(
            rows,
            inventory_id=inventory_id,
            depth=depth,
            project_root=project_root,
            kind="unknown_reference",
            role="unknown",
            owner=rasmap_path,
            raw=None,
            path=None,
            required=None,
            source_api="RasMap.initialize_rasmap_df",
            hash_files=hash_files,
            parent_asset_id=rasmap_id,
            state="not_inspected",
            readiness="unknown",
            reason_code="rasmap_structured_inventory_empty",
            detail=(
                "RASMapper exists but the structured parser returned no rows; "
                "raw XML references are inventoried separately"
            ),
            id_discriminator="rasmap_structured_inventory_empty",
        )
    if not rasmap_df.empty:
        for column, kind in _RASMAP_KINDS.items():
            if column not in rasmap_df.columns:
                continue
            for occurrence, raw_path in enumerate(_as_values(rasmap_df.iloc[0].get(column))):
                path = RasUtils.safe_resolve(Path(raw_path))
                seen_map_paths.add(os.path.normcase(str(path)))
                map_required = False if kind in {"stored_map", "projection"} else None
                map_reason = (
                    "rasmap_reference_not_plan_associated"
                    if map_required is None
                    else None
                )
                map_asset_id = _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind=kind,
                    role="display_reference" if kind == "stored_map" else "declared_input",
                    owner=rasmap_path,
                    raw=raw_path,
                    path=path,
                    required=map_required,
                    source_api=f"RasPrj.rasmap_df.{column}",
                    hash_files=hash_files,
                    parent_asset_id=rasmap_id,
                    reason_code=map_reason,
                    occurrence=occurrence,
                )
                for sidecar in _add_implied_vector_sidecars(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    owner=rasmap_path,
                    vector_path=path,
                    parent_asset_id=map_asset_id,
                    required=map_required,
                    hash_files=hash_files,
                    occurrence=occurrence,
                ):
                    seen_map_paths.add(os.path.normcase(str(sidecar)))

    if _path_is_file(rasmap_path):
        try:
            root = ET.parse(_io_path(rasmap_path)).getroot()
            occurrence = 0
            for element in root.iter():
                for attribute, raw in element.attrib.items():
                    normalized_attribute = attribute.casefold()
                    if normalized_attribute not in {"filename", "path", "folder"}:
                        continue
                    if not raw:
                        continue
                    path = _resolve_reference(rasmap_path, raw)
                    if os.path.normcase(str(path)) in seen_map_paths:
                        continue
                    kind = (
                        "directory"
                        if normalized_attribute == "folder"
                        or raw.rstrip().endswith(("\\", "/"))
                        else "unknown_reference"
                    )
                    map_asset_id = _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind=kind,
                        role="unknown",
                        owner=rasmap_path,
                        raw=raw,
                        path=path,
                        required=None,
                        source_api=f"RasMap XML {attribute} attribute",
                        hash_files=hash_files,
                        parent_asset_id=rasmap_id,
                        occurrence=occurrence,
                    )
                    seen_map_paths.add(os.path.normcase(str(path)))
                    for sidecar in _add_implied_vector_sidecars(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        owner=rasmap_path,
                        vector_path=path,
                        parent_asset_id=map_asset_id,
                        required=None,
                        hash_files=hash_files,
                        occurrence=occurrence,
                    ):
                        seen_map_paths.add(os.path.normcase(str(sidecar)))
                    occurrence += 1
        except (ET.ParseError, OSError) as exc:
            _add_asset(
                rows,
                inventory_id=inventory_id,
                depth=depth,
                project_root=project_root,
                kind="unknown_reference",
                role="unknown",
                owner=rasmap_path,
                raw=None,
                path=None,
                required=None,
                source_api="RasMap XML filename/path/folder attribute",
                hash_files=hash_files,
                parent_asset_id=rasmap_id,
                state="failed",
                readiness="unknown",
                reason_code="rasmap_parse_failed",
                detail=str(exc)[:500],
                id_discriminator="rasmap_parse_failed",
            )

    if depth != "project":
        for unsteady_number in sorted(selected_unsteady_numbers):
            matches = ras_obj.unsteady_df.loc[
                ras_obj.unsteady_df["unsteady_number"].astype(str) == unsteady_number
            ]
            if matches.empty:
                continue
            unsteady_path = Path(str(matches.iloc[0]["full_path"]))
            plan_matches = plans.loc[plans["unsteady_number"].astype(str) == unsteady_number]
            plan_scopes = [str(value) for value in plan_matches["plan_number"].tolist()]
            first_plan = plan_scopes[0] if len(plan_scopes) == 1 else None
            window = (None, None)
            if len(plan_scopes) == 1:
                window = _plan_window(Path(str(plan_matches.iloc[0]["full_path"])))

            structured_boundaries = getattr(
                ras_obj,
                "boundaries_df",
                pd.DataFrame(),
            )
            if not structured_boundaries.empty:
                structured_boundaries = structured_boundaries.loc[
                    structured_boundaries["unsteady_number"].astype(str)
                    == unsteady_number
                ]
            try:
                with _io_path(unsteady_path).open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                    newline="",
                ) as stream:
                    boundary_lines = stream.readlines()
                raw_boundaries = RasUnsteady._find_boundary_blocks(boundary_lines)
            except (OSError, UnicodeError, ValueError) as exc:
                raw_boundaries = []
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="boundary",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=None,
                    path=None,
                    required=None,
                    source_api="RasPrj.boundaries_df + RasUnsteady raw block inventory",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    state="failed",
                    readiness="unknown",
                    reason_code="boundary_parse_failed",
                    detail=str(exc)[:500],
                    id_discriminator="boundary_parse_failed",
                )

            if len(raw_boundaries) != len(structured_boundaries):
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="boundary",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=None,
                    path=None,
                    required=None,
                    source_api="RasPrj.boundaries_df + RasUnsteady raw block inventory",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    state="failed",
                    readiness="unknown",
                    reason_code="boundary_inventory_mismatch",
                    detail=(
                        f"structured={len(structured_boundaries)} "
                        f"raw={len(raw_boundaries)}"
                    ),
                    id_discriminator="boundary_inventory_mismatch_count",
                )

            structured_by_number = {
                int(boundary.get("boundary_condition_number")): boundary
                for _, boundary in structured_boundaries.iterrows()
                if pd.notna(boundary.get("boundary_condition_number"))
            }
            for occurrence, boundary_block in enumerate(raw_boundaries):
                boundary = structured_by_number.get(occurrence + 1)
                boundary_type = (
                    _optional_text(boundary.get("bc_type"))
                    if boundary is not None
                    else ""
                ) or _optional_text(boundary_block.get("bc_type")) or "Unknown"
                raw_boundary_type = (
                    _optional_text(boundary_block.get("bc_type")) or "Unknown"
                )
                boundary_id = _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="boundary",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=f"Boundary Location={boundary_block['location']}",
                    path=None,
                    required=None,
                    source_api="RasPrj.boundaries_df + RasUnsteady raw block inventory",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    dataset_name=boundary_type,
                    state="available",
                    readiness="unknown",
                    reason_code="inline_or_structured_boundary",
                    occurrence=occurrence,
                )
                structured_type = (
                    _optional_text(boundary.get("bc_type"))
                    if boundary is not None
                    else ""
                )
                if boundary is None or (
                    structured_type
                    and structured_type.casefold() != "unknown"
                    and raw_boundary_type.casefold() != "unknown"
                    and structured_type.casefold() != raw_boundary_type.casefold()
                ):
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="boundary",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=f"Boundary Location={boundary_block['location']}",
                        path=None,
                        required=None,
                        source_api=(
                            "RasPrj.boundaries_df + RasUnsteady raw block inventory"
                        ),
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        parent_asset_id=boundary_id,
                        dataset_name=raw_boundary_type,
                        state="failed",
                        readiness="unknown",
                        reason_code="boundary_inventory_mismatch",
                        detail=(
                            f"ordinal={occurrence + 1} "
                            f"structured_type={structured_type or '<missing>'!r} "
                            f"raw_type={raw_boundary_type!r}"
                        ),
                        occurrence=occurrence,
                        id_discriminator="boundary_inventory_mismatch_type",
                    )
                use_dss = (
                    _normalized_optional_bool(boundary.get("Use DSS"))
                    if boundary is not None
                    else None
                )
                raw_use_dss = (
                    _optional_text(boundary.get("Use DSS"))
                    if boundary is not None
                    else ""
                )
                if raw_use_dss and use_dss is None:
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="boundary",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=raw_use_dss,
                        path=None,
                        required=None,
                        source_api="RasPrj.boundaries_df.Use DSS",
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        parent_asset_id=boundary_id,
                        state="failed",
                        readiness="unknown",
                        reason_code="boundary_use_dss_unrecognized",
                        detail=f"Unrecognized Use DSS value: {raw_use_dss!r}",
                        occurrence=occurrence,
                        id_discriminator="boundary_use_dss_unrecognized",
                    )
                if use_dss is not True:
                    continue
                raw_file = _optional_text(boundary.get("DSS File"))
                dss_path = _resolve_reference(unsteady_path, raw_file) if raw_file else None
                file_id = _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="dss_file",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=raw_file,
                    path=dss_path,
                    required=True,
                    source_api="RasPrj.boundaries_df",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    expected_start=window[0],
                    expected_end=window[1],
                    parent_asset_id=boundary_id,
                    occurrence=occurrence,
                    reason_code="reference_missing" if not raw_file else None,
                )
                raw_pathname = _optional_text(boundary.get("DSS Path"))
                if raw_pathname:
                    pathname_state = "not_inspected"
                    pathname_readiness = "unknown"
                    pathname_reason = (
                        "dss_inspection_not_requested"
                        if dss_inspection == "none"
                        else "reader_not_source_immutable"
                    )
                else:
                    pathname_state = "missing"
                    pathname_readiness = "not_ready"
                    pathname_reason = "reference_missing"
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="dss_pathname",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=raw_pathname,
                    path=dss_path,
                    required=True,
                    source_api="RasPrj.boundaries_df",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    parent_asset_id=file_id,
                    dataset_name=raw_pathname or None,
                    expected_start=window[0],
                    expected_end=window[1],
                    state=pathname_state,
                    readiness=pathname_readiness,
                    reason_code=pathname_reason,
                    occurrence=occurrence,
                )

            try:
                restart = RasUnsteady.get_restart_settings(unsteady_path, ras_object=ras_obj)
                if restart.get("use_restart"):
                    raw_restart = str(restart.get("restart_filename") or "").strip()
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="restart",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=raw_restart,
                        path=_resolve_reference(unsteady_path, raw_restart) if raw_restart else None,
                        required=True,
                        source_api="RasUnsteady.get_restart_settings",
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        reason_code="reference_missing" if not raw_restart else None,
                    )
            except (OSError, ValueError) as exc:
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="restart",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=None,
                    path=None,
                    required=None,
                    source_api="RasUnsteady.get_restart_settings",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    state="failed",
                    readiness="unknown",
                    reason_code="restart_parse_failed",
                    detail=str(exc)[:500],
                    id_discriminator="restart_parse_failed",
                )

            prior_ws = _read_key(unsteady_path, "Prior WS Filename")
            if prior_ws:
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="prior_ws",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=prior_ws,
                    path=_resolve_reference(unsteady_path, prior_ws),
                    required=True,
                    source_api="RasUnsteady.get_initial_flow_method",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                )

            try:
                precipitation = RasUnsteady.get_met_precipitation_config(
                    unsteady_path,
                    ras_object=ras_obj,
                )
            except (OSError, ValueError) as exc:
                precipitation = {}
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="gridded_dataset",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=None,
                    path=None,
                    required=None,
                    source_api="RasUnsteady.get_met_precipitation_config",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    state="failed",
                    readiness="unknown",
                    reason_code="precipitation_parse_failed",
                    detail=str(exc)[:500],
                    id_discriminator="precipitation_parse_failed",
                )
            if precipitation.get("enabled") and precipitation.get("mode") == "Gridded":
                source = precipitation.get("source")
                if source == "DSS":
                    raw_file = str(precipitation.get("dss_filename") or "").strip()
                    path = _resolve_reference(unsteady_path, raw_file) if raw_file else None
                    file_id = _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="dss_file",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=raw_file,
                        path=path,
                        required=True,
                        source_api="RasUnsteady.get_met_precipitation_config",
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        reason_code="reference_missing" if not raw_file else None,
                    )
                    pathname = str(precipitation.get("dss_pathname") or "").strip()
                    if pathname:
                        dataset_state = "not_inspected"
                        dataset_readiness = "unknown"
                        dataset_reason = (
                            "dss_inspection_not_requested"
                            if dss_inspection == "none"
                            else "reader_not_source_immutable"
                        )
                    else:
                        dataset_state = "missing"
                        dataset_readiness = "not_ready"
                        dataset_reason = "reference_missing"
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="gridded_dataset",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=pathname,
                        path=path,
                        required=True,
                        source_api="RasUnsteady.get_met_precipitation_config",
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        parent_asset_id=file_id,
                        dataset_name=pathname or None,
                        expected_start=window[0],
                        expected_end=window[1],
                        state=dataset_state,
                        readiness=dataset_readiness,
                        reason_code=dataset_reason,
                    )
                elif source == "GDAL Raster File(s)":
                    raw_config = precipitation.get("raw")
                    if not isinstance(raw_config, dict):
                        raw_config = {}
                    raw_file = _optional_text(
                        raw_config.get("Gridded GDAL Filename")
                    ) or _optional_text(precipitation.get("gdal_filename"))
                    raw_folder = _optional_text(
                        raw_config.get("Gridded GDAL Folder")
                    ) or _optional_text(precipitation.get("gdal_folder"))
                    raw_group = _optional_text(
                        raw_config.get("Gridded GDAL Group")
                    )
                    raw_datasetname = _optional_text(
                        raw_config.get("Gridded GDAL Datasetname")
                    )
                    if not raw_group and not raw_datasetname:
                        raw_group = _optional_text(precipitation.get("gdal_group"))
                    raw_filter = _optional_text(
                        raw_config.get("Gridded GDAL Filter")
                    ) or _optional_text(precipitation.get("gdal_filter"))
                    primary_path: Optional[Path] = None
                    primary_id: Optional[str] = None
                    if raw_file:
                        primary_path = _resolve_reference(unsteady_path, raw_file)
                        primary_id = _add_asset(
                            rows,
                            inventory_id=inventory_id,
                            depth=depth,
                            project_root=project_root,
                            kind="gridded_dataset",
                            role="declared_input",
                            owner=unsteady_path,
                            raw=raw_file,
                            path=primary_path,
                            required=True,
                            source_api=(
                                "RasUnsteady.get_met_precipitation_config.gdal_filename"
                            ),
                            hash_files=hash_files,
                            plan_number=first_plan,
                            unsteady_number=unsteady_number,
                        )
                    if raw_folder:
                        folder_path = _resolve_reference(unsteady_path, raw_folder)
                        folder_id = _add_asset(
                            rows,
                            inventory_id=inventory_id,
                            depth=depth,
                            project_root=project_root,
                            kind="directory",
                            role="declared_input",
                            owner=unsteady_path,
                            raw=raw_folder,
                            path=folder_path,
                            required=True,
                            source_api=(
                                "RasUnsteady.get_met_precipitation_config.gdal_folder"
                            ),
                            hash_files=hash_files,
                            plan_number=first_plan,
                            unsteady_number=unsteady_number,
                        )
                        if primary_path is None:
                            primary_path = folder_path
                            primary_id = folder_id
                    if not raw_file and not raw_folder:
                        _add_asset(
                            rows,
                            inventory_id=inventory_id,
                            depth=depth,
                            project_root=project_root,
                            kind="gridded_dataset",
                            role="declared_input",
                            owner=unsteady_path,
                            raw=None,
                            path=None,
                            required=True,
                            source_api="RasUnsteady.get_met_precipitation_config",
                            hash_files=hash_files,
                            plan_number=first_plan,
                            unsteady_number=unsteady_number,
                            state="missing",
                            readiness="not_ready",
                            reason_code="reference_missing",
                        )
                    for dataset_occurrence, (
                        dataset_field,
                        dataset_value,
                    ) in enumerate(
                        (
                            ("gdal_group", raw_group),
                            ("gdal_datasetname", raw_datasetname),
                        )
                    ):
                        if not dataset_value:
                            continue
                        _add_asset(
                            rows,
                            inventory_id=inventory_id,
                            depth=depth,
                            project_root=project_root,
                            kind="gridded_dataset",
                            role="declared_input",
                            owner=unsteady_path,
                            raw=dataset_value,
                            path=primary_path,
                            required=True,
                            source_api=(
                                "RasUnsteady.get_met_precipitation_config."
                                f"{dataset_field}"
                            ),
                            hash_files=hash_files,
                            plan_number=first_plan,
                            unsteady_number=unsteady_number,
                            parent_asset_id=primary_id,
                            dataset_name=dataset_value,
                            state="not_inspected",
                            readiness="unknown",
                            reason_code="gdal_dataset_not_inspected",
                            occurrence=dataset_occurrence,
                        )
                    if raw_filter:
                        _add_asset(
                            rows,
                            inventory_id=inventory_id,
                            depth=depth,
                            project_root=project_root,
                            kind="unknown_reference",
                            role="declared_input",
                            owner=unsteady_path,
                            raw=raw_filter,
                            path=None,
                            required=True,
                            source_api=(
                                "RasUnsteady.get_met_precipitation_config.gdal_filter"
                            ),
                            hash_files=hash_files,
                            plan_number=first_plan,
                            unsteady_number=unsteady_number,
                            parent_asset_id=primary_id,
                            state="available",
                            readiness="ready",
                            reason_code="gdal_filter_declared",
                        )

    rows = _scope_unsteady_dependencies(rows, plans)
    return _to_arrow_frame(rows)


def _scope_unsteady_dependencies(
    rows: list[dict[str, Any]],
    plans: pd.DataFrame,
) -> list[dict[str, Any]]:
    dependency_kinds = {
        "dss_file",
        "dss_pathname",
        "gridded_dataset",
        "restart",
        "prior_ws",
        "unknown_reference",
        "boundary",
        "directory",
    }
    scope: dict[str, list[tuple[str, Optional[datetime], Optional[datetime]]]] = {}
    for _, plan in plans.iterrows():
        unsteady = plan.get("unsteady_number")
        if pd.isna(unsteady):
            continue
        plan_number = str(plan.get("plan_number"))
        start, end = _plan_window(Path(str(plan.get("full_path"))))
        scope.setdefault(str(unsteady), []).append((plan_number, start, end))

    unsteady_parent_ids = {
        (str(row.get("unsteady_number")), str(row.get("plan_number"))): str(
            row["asset_id"]
        )
        for row in rows
        if row.get("asset_kind") == "unsteady_flow"
        and row.get("unsteady_number") is not None
        and row.get("plan_number") is not None
    }
    expanded: list[dict[str, Any]] = []
    parent_ids: dict[tuple[str, str], str] = {}
    for row in rows:
        unsteady = row.get("unsteady_number")
        plan_scopes = scope.get(str(unsteady), []) if unsteady is not None else []
        if (
            row.get("asset_kind") not in dependency_kinds
            or row.get("plan_number") is not None
            or len(plan_scopes) < 2
        ):
            if (
                row.get("asset_kind") in dependency_kinds
                and row.get("parent_asset_id") is None
                and row.get("unsteady_number") is not None
                and row.get("plan_number") is not None
            ):
                row = dict(row)
                row["parent_asset_id"] = unsteady_parent_ids.get(
                    (str(row["unsteady_number"]), str(row["plan_number"]))
                )
            expanded.append(row)
            continue
        for plan_number, start, end in plan_scopes:
            scoped = dict(row)
            old_id = str(row["asset_id"])
            scoped["plan_number"] = plan_number
            scoped["asset_id"] = _asset_id(old_id, plan_number)
            if row.get("parent_asset_id") is not None:
                scoped["parent_asset_id"] = parent_ids.get(
                    (str(row["parent_asset_id"]), plan_number),
                    row["parent_asset_id"],
                )
            else:
                scoped["parent_asset_id"] = unsteady_parent_ids.get(
                    (str(unsteady), plan_number)
                )
            if row.get("asset_kind") in {"dss_file", "dss_pathname", "gridded_dataset"}:
                scoped["expected_start"] = start
                scoped["expected_end"] = end
            parent_ids[(old_id, plan_number)] = str(scoped["asset_id"])
            expanded.append(scoped)
    return expanded


@log_call
def inspect_project_assets(
    project: Union[str, Path],
    *,
    ras_object: Optional[RasPrj] = None,
    depth: InspectionDepth = "all_plans",
    hash_files: bool = False,
    dss_inspection: DssInspection = "none",
) -> pd.DataFrame:
    """Return a read-only, DataFrame-first inventory of linked project assets.

    DSS file references are inventoried, but DSS containers are not opened by
    this implementation. Requests for ``catalog`` or ``coverage`` therefore
    remain explicit ``not_inspected`` dataset rows until the underlying reader
    has a proven source-immutable open contract.
    """
    cache = _InventoryHashCache() if hash_files else None
    token = _ACTIVE_INVENTORY_HASH_CACHE.set(cache)
    try:
        frame = _inspect_project_assets_impl(
            project,
            ras_object=ras_object,
            depth=depth,
            hash_files=hash_files,
            dss_inspection=dss_inspection,
        )
        if cache is not None:
            cache.verify()
        return frame
    finally:
        _ACTIVE_INVENTORY_HASH_CACHE.reset(token)


def _tree_snapshot(root: Path) -> tuple[dict[str, _FileSnapshot], str, int]:
    snapshots: dict[str, _FileSnapshot] = {}
    directories: set[str] = set()
    total_bytes = 0

    def raise_traversal_error(exc: OSError) -> NoReturn:
        raise ProjectPathAmbiguityError(
            "tree_traversal_failed",
            f"Could not traverse project tree: {root}",
        ) from exc

    io_root = _io_path(root)
    for directory, directory_names, file_names in os.walk(
        io_root,
        topdown=True,
        onerror=raise_traversal_error,
        followlinks=False,
    ):
        relative_directory = Path(directory).relative_to(io_root)
        current = root / relative_directory
        _assert_regular_path(current, expected_directory=True)
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        for name in directory_names:
            child = current / name
            _assert_regular_path(child, expected_directory=True)
            if child.suffix.lower() in _LOCK_SUFFIXES:
                raise ProjectLockedError(
                    "source_lock_present",
                    f"Active or ambiguous lock directory present: {child}",
                )
            directories.add(child.relative_to(root).as_posix())
        for name in file_names:
            path = current / name
            info = _assert_regular_path(path)
            if path.suffix.lower() in _LOCK_SUFFIXES:
                raise ProjectLockedError(
                    "source_lock_present",
                    f"Active or ambiguous lock file present: {path}",
                )
            relative = path.relative_to(root).as_posix()
            digest = _sha256_file(path)
            snapshots[relative] = _FileSnapshot(
                relative_path=relative,
                size_bytes=info.st_size,
                mtime_ns=info.st_mtime_ns,
                volume_id=str(info.st_dev),
                file_id=str(info.st_ino),
                sha256=digest,
            )
            total_bytes += info.st_size
    tree_digest = hashlib.sha256()
    for relative in sorted(directories, key=str.casefold):
        for value in ("directory", relative, "0", ""):
            encoded = value.encode("utf-8", errors="surrogatepass")
            tree_digest.update(len(encoded).to_bytes(8, "big"))
            tree_digest.update(encoded)
    for relative, item in sorted(snapshots.items(), key=lambda pair: pair[0].casefold()):
        for value in ("file", relative, str(item.size_bytes), item.sha256):
            encoded = value.encode("utf-8", errors="surrogatepass")
            tree_digest.update(len(encoded).to_bytes(8, "big"))
            tree_digest.update(encoded)
    return snapshots, tree_digest.hexdigest(), total_bytes


def _directory_population(root: Path) -> set[str]:
    directories: set[str] = set()

    def raise_traversal_error(exc: OSError) -> NoReturn:
        raise ProjectPathAmbiguityError(
            "tree_traversal_failed",
            f"Could not traverse project directories: {root}",
        ) from exc

    io_root = _io_path(root)
    for directory, directory_names, _ in os.walk(
        io_root,
        topdown=True,
        onerror=raise_traversal_error,
        followlinks=False,
    ):
        relative_directory = Path(directory).relative_to(io_root)
        current = root / relative_directory
        _assert_regular_path(current, expected_directory=True)
        directory_names.sort(key=str.casefold)
        for name in directory_names:
            child = current / name
            _assert_regular_path(child, expected_directory=True)
            if child.suffix.lower() in _LOCK_SUFFIXES:
                raise ProjectLockedError(
                    "source_lock_present",
                    f"Active or ambiguous lock directory present: {child}",
                )
            directories.add(child.relative_to(root).as_posix())
    return directories


def _assert_copy_equal(
    source: dict[str, _FileSnapshot],
    copied: dict[str, _FileSnapshot],
) -> None:
    if set(source) != set(copied):
        missing = sorted(set(source) - set(copied))[:5]
        extra = sorted(set(copied) - set(source))[:5]
        raise ProjectCopyVerificationError(
            "copy_population_mismatch",
            f"Copied tree population differs (missing={missing}, extra={extra})",
        )
    for relative, source_item in source.items():
        copied_item = copied[relative]
        if (
            source_item.size_bytes != copied_item.size_bytes
            or source_item.sha256 != copied_item.sha256
        ):
            raise ProjectCopyVerificationError(
                "copy_content_mismatch",
                f"Copied file content differs: {relative}",
            )


def _copy_snapshot(
    source_root: Path,
    destination_root: Path,
    files: dict[str, _FileSnapshot],
    directories: set[str],
) -> None:
    for relative in sorted(
        directories,
        key=lambda item: (len(Path(item).parts), item.casefold()),
    ):
        _io_path(destination_root / Path(relative)).mkdir(
            parents=True,
            exist_ok=False,
        )
    for relative in sorted(files, key=str.casefold):
        source = source_root / Path(relative)
        target = destination_root / Path(relative)
        _assert_regular_path(source)
        shutil.copy2(
            _io_path(source),
            _io_path(target),
            follow_symlinks=False,
        )


def _stage_readiness(assets: pd.DataFrame) -> Literal["ready", "not_ready", "unknown"]:
    required = assets.loc[assets["required"] == True]  # noqa: E712
    if required.empty:
        return "unknown"
    if (required["readiness"] == "not_ready").any():
        return "not_ready"
    if (required["readiness"] != "ready").any():
        return "unknown"
    return "ready"


def _validate_project_population(assets: pd.DataFrame) -> None:
    intentionally_uninspected_dataset = (
        assets["asset_kind"].isin({"dss_pathname", "gridded_dataset"})
        & (assets["inspection_state"] == "not_inspected")
        & (assets["readiness"] == "unknown")
    )
    invalid = assets.loc[
        (assets["required"] == True)  # noqa: E712
        & (assets["inspection_state"] != "available")
        & ~intentionally_uninspected_dataset
    ]
    if invalid.empty:
        return
    sample = ", ".join(
        f"{row.asset_kind}:{row.reference_raw}"
        for row in invalid.head(5).itertuples(index=False)
    )
    raise ProjectPopulationError(
        "required_component_unavailable",
        f"Invalid staged project population; required files unavailable: {sample}",
    )


def _safe_remove_owned_temp(
    temp_root: Optional[Path],
    destination_parent: Path,
    operation_id: str,
) -> bool:
    if temp_root is None or not _path_lexists(temp_root):
        return True
    try:
        parent_matches = _same_file(temp_root.parent, destination_parent)
    except OSError:
        parent_matches = False
    sentinel = temp_root / _TEMP_SENTINEL
    manifest = temp_root / _STAGE_METADATA_DIR / _STAGE_MANIFEST
    sentinel_matches = False
    manifest_matches = False
    try:
        sentinel_matches = _path_is_file(sentinel) and _io_path(sentinel).read_text(
            encoding="ascii"
        ) == operation_id
    except OSError:
        pass
    try:
        manifest_matches = _path_is_file(manifest) and json.loads(
            _io_path(manifest).read_text(encoding="utf-8")
        ).get("operation_id") == operation_id
    except (OSError, ValueError, TypeError):
        pass
    if not parent_matches or not (sentinel_matches or manifest_matches):
        logger.error("Refusing cleanup of unverified staging directory: %s", temp_root)
        return False
    shutil.rmtree(_io_path(temp_root))
    return True


def _safe_remove_owned_lock(
    lock_path: Path,
    lock_identity: Optional[tuple[int, int]],
    lock_token: bytes,
) -> None:
    """Remove only the lock file created by this staging invocation."""
    if lock_identity is None:
        return
    try:
        if _is_reparse_point(lock_path):
            raise RuntimeError("lock path became a reparse point")
        info = _io_path(lock_path).stat()
        if (info.st_dev, info.st_ino) != lock_identity:
            raise RuntimeError("lock file identity changed")
        if _io_path(lock_path).read_bytes() != lock_token:
            raise RuntimeError("lock file token changed")
        _io_path(lock_path).unlink()
    except FileNotFoundError:
        return
    except (OSError, RuntimeError) as exc:
        logger.error("Refusing cleanup of unverified staging lock %s: %s", lock_path, exc)


def _fsync_path(
    path: Path,
    *,
    directory: bool = False,
    raise_on_error: bool = True,
) -> None:
    """Flush one path when the host filesystem exposes a usable primitive."""
    flags = os.O_RDONLY
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(_io_path(path), flags)
        os.fsync(descriptor)
    except OSError as exc:
        unsupported = exc.errno in {
            errno.EACCES,
            errno.EBADF,
            errno.EINVAL,
            errno.ENOTSUP,
        } or getattr(exc, "winerror", None) in {5, 6, 50, 87}
        if not unsupported and raise_on_error:
            raise ProjectPublicationError(
                "fsync_failed",
                f"Could not durably flush staging path: {path}",
            ) from exc
        if not unsupported:
            logger.warning("Post-publication directory flush failed: %s", path)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    def raise_traversal_error(exc: OSError) -> NoReturn:
        raise ProjectPublicationError(
            "fsync_traversal_failed",
            f"Could not traverse the prepared staging tree: {root}",
        ) from exc

    io_root = _io_path(root)
    for directory, directory_names, file_names in os.walk(
        io_root,
        topdown=False,
        onerror=raise_traversal_error,
        followlinks=False,
    ):
        relative_directory = Path(directory).relative_to(io_root)
        current = root / relative_directory
        for name in sorted(file_names, key=str.casefold):
            path = current / name
            _assert_regular_path(path)
            _fsync_path(path)
        for name in sorted(directory_names, key=str.casefold):
            child = current / name
            _assert_regular_path(child, expected_directory=True)
            _fsync_path(child, directory=True)
        _fsync_path(current, directory=True)


def _directory_identity(path: Path) -> tuple[int, int]:
    info = _assert_regular_path(path, expected_directory=True)
    return info.st_dev, info.st_ino


def _path_has_directory_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        if _is_reparse_point(path):
            return False
        info = _io_path(path).stat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == identity


def _native_rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename one directory without replacing a destination."""
    if os.name == "nt":
        # Windows directory rename already fails when the destination exists.
        os.rename(_io_path(source), _io_path(destination))
        return

    import ctypes
    import sys

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    result: int
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOSYS, "renameat2 is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,  # AT_FDCWD
            source_bytes,
            -100,
            destination_bytes,
            1,  # RENAME_NOREPLACE
        )
    elif sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise OSError(errno.ENOSYS, "renamex_np is unavailable")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(
            source_bytes,
            destination_bytes,
            0x00000004,  # RENAME_EXCL
        )
    else:
        raise OSError(errno.ENOSYS, "Atomic no-replace rename is unavailable")

    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            os.strerror(error_number),
            str(destination),
        )


def _publish_directory_noreplace(source: Path, destination: Path) -> None:
    """Publish once, reconciling remote-filesystem errors by directory identity."""
    source_identity = _directory_identity(source)
    try:
        _native_rename_noreplace(source, destination)
    except OSError as exc:
        source_same = _path_has_directory_identity(source, source_identity)
        destination_same = _path_has_directory_identity(destination, source_identity)
        if destination_same and not _path_lexists(source):
            # Some remote filesystems can report an error after committing rename.
            return
        if source_same and not destination_same:
            if _path_lexists(destination):
                raise ProjectPublicationError(
                    "destination_race",
                    f"Destination appeared during staging: {destination}",
                ) from exc
            unsupported_errors = {
                errno.ENOSYS,
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }
            if exc.errno in unsupported_errors:
                raise ProjectPublicationError(
                    "atomic_noreplace_unavailable",
                    "The filesystem does not support atomic no-replace publication",
                ) from exc
            raise ProjectPublicationError(
                "atomic_rename_failed",
                f"Could not publish the verified staging directory: {destination}",
            ) from exc
        raise ProjectPublicationError(
            "publication_outcome_unknown",
            "The filesystem did not expose whether directory publication committed",
            publication_outcome="unknown",
        ) from exc
    if (
        _path_has_directory_identity(destination, source_identity)
        and not _path_lexists(source)
    ):
        return
    raise ProjectPublicationError(
        "publication_outcome_unknown",
        "The rename primitive returned without a provable committed publication",
        publication_outcome="unknown",
    )


@log_call
def stage_project(
    source: Union[str, Path],
    destination: Union[str, Path],
    *,
    ras_object: Optional[RasPrj] = None,
) -> StageProjectResult:
    """Copy, verify, initialize, and atomically publish a HEC-RAS project tree.

    ``destination`` is a new project directory.  Existing destinations,
    overlapping paths, reparse points, lock artifacts, source drift, copy
    drift, and publication races fail without replacing an existing tree.
    """
    operation_id = str(uuid.uuid4())
    source_input = Path(source).absolute()
    _assert_no_reparse_ancestry(source_input)
    try:
        source_project = _resolve_project_file(source)
    except ProjectStageError:
        raise
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        raise ProjectPopulationError("invalid_source_project", str(exc)) from exc
    source_root = source_project.parent
    _assert_no_reparse_ancestry(source_root)
    if ras_object is not None:
        try:
            _explicit_ras(source_project, ras_object)
        except (OSError, TypeError, ValueError) as exc:
            raise ProjectPopulationError("ras_object_mismatch", str(exc)) from exc

    destination_root = Path(destination).absolute()
    if _path_lexists(destination_root):
        raise FileExistsError(f"Destination already exists: {destination_root}")
    destination_parent = destination_root.parent
    if not _path_exists(destination_parent):
        raise ProjectPathAmbiguityError(
            "destination_parent_missing",
            f"Destination parent must already exist: {destination_parent}",
        )
    _assert_no_reparse_ancestry(destination_parent)
    try:
        _assert_regular_path(destination_parent, expected_directory=True)
    except (OSError, ValueError) as exc:
        raise ProjectPathAmbiguityError(
            "destination_parent_invalid",
            f"Destination parent is not an ordinary directory: {destination_parent}",
        ) from exc

    source_real = os.path.normcase(os.path.realpath(_io_path(source_root)))
    destination_real = os.path.normcase(os.path.realpath(_io_path(destination_root)))
    try:
        overlap = os.path.commonpath([source_real, destination_real]) in {
            source_real,
            destination_real,
        }
    except ValueError:
        overlap = False
    try:
        identity_overlap = _source_contains_destination(
            source_root,
            destination_parent,
        )
    except OSError as exc:
        raise ProjectPathAmbiguityError(
            "path_identity_unavailable",
            "Could not prove source/destination physical separation",
        ) from exc
    if overlap or identity_overlap:
        raise ProjectPathAmbiguityError(
            "path_overlap",
            "Source and destination project trees must not overlap",
        )
    if _path_lexists(source_root / _STAGE_METADATA_DIR):
        raise ProjectPopulationError(
            "reserved_metadata_present",
            f"Source contains reserved staging metadata directory: {_STAGE_METADATA_DIR}",
        )

    lock_path = destination_parent / f".{destination_root.name}.rascommander-stage.lock"
    lock_handle: Optional[int] = None
    lock_identity: Optional[tuple[int, int]] = None
    lock_token = f"pid={os.getpid()};token={uuid.uuid4()}".encode("ascii")
    temp_root: Optional[Path] = None
    published = False
    try:
        try:
            lock_handle = os.open(
                _io_path(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise ProjectLockedError(
                "staging_lock_exists",
                f"Another staging operation owns the destination lock: {lock_path.name}",
            ) from exc
        lock_info = os.fstat(lock_handle)
        lock_identity = lock_info.st_dev, lock_info.st_ino
        if os.write(lock_handle, lock_token) != len(lock_token):
            raise ProjectLockedError(
                "staging_lock_write_failed",
                "Could not write the complete staging lock identity",
            )

        source_files_before, source_before, copied_bytes = _tree_snapshot(source_root)
        source_directories_before = _directory_population(source_root)
        temp_root = _public_path(
            os.path.realpath(
                _io_path(
                    tempfile.mkdtemp(
                        prefix=f".{destination_root.name}.ras-stage-",
                        dir=_io_path(destination_parent),
                    )
                )
            )
        )
        sentinel = temp_root / _TEMP_SENTINEL
        _io_path(sentinel).write_text(operation_id, encoding="ascii")
        _copy_snapshot(
            source_root,
            temp_root,
            source_files_before,
            source_directories_before,
        )

        _io_path(sentinel).unlink()
        try:
            copied_files, copied_fingerprint, copied_total = _tree_snapshot(temp_root)
            copied_directories = _directory_population(temp_root)
        finally:
            if _path_exists(temp_root) and not _path_lexists(sentinel):
                _io_path(sentinel).write_text(operation_id, encoding="ascii")
        _assert_copy_equal(source_files_before, copied_files)
        if copied_directories != source_directories_before:
            raise ProjectCopyVerificationError(
                "copy_directory_population_mismatch",
                "Copied directory population differs from source snapshot",
            )
        if copied_total != copied_bytes:
            raise ProjectCopyVerificationError(
                "copy_size_mismatch",
                "Copied byte count differs from source snapshot",
            )
        temp_project = temp_root / source_project.relative_to(source_root)
        try:
            staged_ras = init_ras_project(
                _io_path(temp_project),
                ras_version=_declared_current_plan_version(temp_project),
                ras_object=RasPrj(),
                load_results_summary=False,
                hide_intro=True,
            )
            _validate_current_plan(temp_project, staged_ras)
            assets = inspect_project_assets(
                temp_project,
                ras_object=staged_ras,
                depth="all_plans",
                hash_files=True,
                dss_inspection="none",
            )
        except ProjectStageError:
            raise
        except Exception as exc:
            raise ProjectPopulationError(
                "staged_initialization_failed",
                "The verified copy could not be initialized and inventoried",
            ) from exc
        _validate_project_population(assets)
        readiness = _stage_readiness(assets)

        _io_path(sentinel).unlink()
        try:
            verified_files, verified_fingerprint, verified_total = _tree_snapshot(
                temp_root
            )
            verified_directories = _directory_population(temp_root)
        finally:
            if _path_exists(temp_root) and not _path_lexists(sentinel):
                _io_path(sentinel).write_text(operation_id, encoding="ascii")
        _assert_copy_equal(source_files_before, verified_files)
        if verified_fingerprint != copied_fingerprint:
            raise ProjectCopyVerificationError(
                "copy_fingerprint_drift",
                "Verified copied-tree fingerprint changed during staged inspection",
            )
        if verified_directories != source_directories_before:
            raise ProjectCopyVerificationError(
                "copy_directory_drift",
                "Copied directory population changed during staged inspection",
            )
        if verified_total != copied_bytes:
            raise ProjectCopyVerificationError(
                "copy_size_drift",
                "Copied byte count changed during staged inspection",
            )

        source_files_after, source_after, _ = _tree_snapshot(source_root)
        source_directories_after = _directory_population(source_root)
        if (
            source_files_after != source_files_before
            or source_directories_after != source_directories_before
            or source_after != source_before
        ):
            raise ProjectDriftError(
                "source_changed",
                "Source project changed while staging",
            )

        destination_project = destination_root / source_project.name
        final_assets = _rebase_frame(assets, temp_root, destination_root)
        final_ras = _rebase_ras_object(staged_ras, temp_root, destination_root)
        state_counts = final_assets["inspection_state"].value_counts().to_dict()

        metadata_dir = temp_root / _STAGE_METADATA_DIR
        _io_path(metadata_dir).mkdir(exist_ok=False)
        manifest_path = metadata_dir / _STAGE_MANIFEST
        manifest = {
            "schema_version": 1,
            "operation_id": operation_id,
            "source_project_file": str(source_project),
            "destination_project_file": str(destination_root / source_project.name),
            "source_fingerprint_before": source_before,
            "source_fingerprint_after": source_after,
            "copied_fingerprint": copied_fingerprint,
            "copied_file_count": len(source_files_before),
            "copied_bytes": copied_bytes,
            "execution_readiness": readiness,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": [
                {
                    "relative_path": item.relative_path,
                    "provenance": "copied_source",
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for _, item in sorted(
                    source_files_before.items(),
                    key=lambda pair: pair[0].casefold(),
                )
            ]
            + [
                {
                    "relative_path": f"{_STAGE_METADATA_DIR}/{_STAGE_MANIFEST}",
                    "provenance": "generated_stage_metadata",
                }
            ],
        }
        with _io_path(manifest_path).open(
            "x",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")

        _io_path(sentinel).unlink()
        _fsync_tree(temp_root)
        _fsync_path(destination_parent, directory=True)

        source_files_final, source_after, _ = _tree_snapshot(source_root)
        source_directories_final = _directory_population(source_root)
        if (
            source_files_final != source_files_before
            or source_directories_final != source_directories_before
            or source_after != source_before
        ):
            raise ProjectDriftError(
                "source_changed_before_publish",
                "Source project changed before publication",
            )

        final_files, prepared_fingerprint, prepared_total = _tree_snapshot(temp_root)
        final_directories = _directory_population(temp_root)
        metadata_prefix = f"{_STAGE_METADATA_DIR}/"
        final_copied_files = {
            relative: snapshot
            for relative, snapshot in final_files.items()
            if not relative.startswith(metadata_prefix)
        }
        metadata_files = {
            relative
            for relative in final_files
            if relative.startswith(metadata_prefix)
        }
        expected_metadata_files = {
            f"{_STAGE_METADATA_DIR}/{_STAGE_MANIFEST}",
        }
        if metadata_files != expected_metadata_files:
            raise ProjectCopyVerificationError(
                "generated_metadata_population_drift",
                "Generated staging metadata population changed before publication",
            )
        final_copied_directories = {
            relative
            for relative in final_directories
            if relative != _STAGE_METADATA_DIR
            and not relative.startswith(metadata_prefix)
        }
        metadata_directories = {
            relative
            for relative in final_directories
            if relative == _STAGE_METADATA_DIR
            or relative.startswith(metadata_prefix)
        }
        if metadata_directories != {_STAGE_METADATA_DIR}:
            raise ProjectCopyVerificationError(
                "generated_metadata_directory_drift",
                "Generated staging metadata directories changed before publication",
            )
        _assert_copy_equal(source_files_before, final_copied_files)
        if final_copied_directories != source_directories_before:
            raise ProjectCopyVerificationError(
                "copy_directory_drift_before_publish",
                "Copied directory population changed before publication",
            )

        if _path_lexists(destination_root):
            raise ProjectPublicationError(
                "destination_race",
                f"Destination appeared during staging: {destination_root}",
            )
        _publish_directory_noreplace(temp_root, destination_root)
        published = True
        temp_root = None
        try:
            published_files, published_fingerprint, published_total = _tree_snapshot(
                destination_root
            )
            published_directories = _directory_population(destination_root)
            if (
                published_files != final_files
                or published_fingerprint != prepared_fingerprint
                or published_total != prepared_total
                or published_directories != final_directories
            ):
                raise ProjectPublicationError(
                    "published_fingerprint_mismatch",
                    "Published project differs from the verified pre-publication tree",
                    publication_outcome="committed",
                )
        except ProjectPublicationError:
            raise
        except Exception as exc:
            raise ProjectPublicationError(
                "published_verification_failed",
                "Project publication committed but post-publication verification failed",
                publication_outcome="committed",
            ) from exc
        try:
            _fsync_path(
                destination_parent,
                directory=True,
                raise_on_error=False,
            )
            logger.info(
                "Project stage %s published %s: files=%d bytes=%d source=%s copy=%s "
                "readiness=%s states=%s",
                operation_id,
                source_project.name,
                len(source_files_before),
                copied_bytes,
                source_before[:12],
                copied_fingerprint[:12],
                readiness,
                state_counts,
            )
        except Exception:
            logger.exception(
                "Project stage %s published but post-publication logging failed",
                operation_id,
            )
        return StageProjectResult(
            source_project_file=source_project,
            destination_project_file=destination_project,
            destination_root=destination_root,
            source_fingerprint_before=source_before,
            source_fingerprint_after=source_after,
            copied_fingerprint=copied_fingerprint,
            published_fingerprint=published_fingerprint,
            copied_file_count=len(source_files_before),
            copied_bytes=copied_bytes,
            publication_state="published",
            execution_readiness=readiness,
            assets=final_assets,
            ras_object=final_ras,
        )
    except Exception as stage_error:
        publication_outcome = getattr(
            stage_error,
            "publication_outcome",
            "not_committed",
        )
        if not published and publication_outcome != "unknown":
            try:
                removed = _safe_remove_owned_temp(
                    temp_root,
                    destination_parent,
                    operation_id,
                )
            except Exception as cleanup_error:
                raise ProjectStageError(
                    "owned_temp_cleanup_failed",
                    f"Staging failed and cleanup could not remove: {temp_root}",
                ) from cleanup_error
            if not removed:
                raise ProjectStageError(
                    "owned_temp_cleanup_refused",
                    f"Staging failed and the unverified temporary path was retained: {temp_root}",
                ) from stage_error
        if isinstance(stage_error, ProjectStageError):
            raise
        if isinstance(stage_error, OSError):
            if published:
                raise ProjectPublicationError(
                    "published_filesystem_error",
                    "Project publication committed before a filesystem operation failed",
                    publication_outcome="committed",
                ) from stage_error
            raise ProjectStageError(
                "staging_filesystem_error",
                "A filesystem operation failed before project publication",
            ) from stage_error
        raise
    finally:
        if lock_handle is not None:
            try:
                os.close(lock_handle)
            except OSError:
                logger.exception("Could not close staging lock handle")
        _safe_remove_owned_lock(lock_path, lock_identity, lock_token)


__all__ = [
    "ProjectCopyVerificationError",
    "ProjectDriftError",
    "ProjectLockedError",
    "ProjectPathAmbiguityError",
    "ProjectPopulationError",
    "ProjectPublicationError",
    "ProjectStageError",
    "StageProjectResult",
    "inspect_project_assets",
    "stage_project",
]
