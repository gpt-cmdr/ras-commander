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
from typing import Any, Literal, Optional, Union

import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPrj import RasPrj, init_ras_project
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils

logger = get_logger(__name__)

InspectionDepth = Literal["project", "current_plan", "all_plans"]
DssInspection = Literal["none", "catalog", "coverage"]

_INVENTORY_SCHEMA_VERSION = 1
_INVENTORY_COLUMNS = [
    "inventory_schema_version",
    "inventory_id",
    "inspection_depth",
    "asset_id",
    "parent_asset_id",
    "asset_kind",
    "asset_role",
    "plan_number",
    "unsteady_number",
    "required",
    "owner_file",
    "owner_sha256",
    "reference_raw",
    "resolved_path",
    "path_scope",
    "portable",
    "exists",
    "is_file",
    "is_dir",
    "volume_id",
    "file_id",
    "size_bytes",
    "mtime_ns",
    "sha256",
    "dataset_name",
    "expected_start",
    "expected_end",
    "available_start",
    "available_end",
    "inspection_state",
    "readiness",
    "reason_code",
    "detail",
    "source_api",
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

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
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
        info = path.stat()
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & marker)


def _assert_regular_path(path: Path, *, expected_directory: bool = False) -> os.stat_result:
    if _is_reparse_point(path):
        raise ProjectPathAmbiguityError(
            "reparse_point",
            f"Reparse points and symbolic links are not supported: {path}",
        )
    info = path.stat()
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
            if candidate.exists() and _is_reparse_point(candidate):
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
    for candidate in sorted(folder.glob("*.prj"), key=lambda item: item.name.casefold()):
        if _is_reparse_point(candidate) or not candidate.is_file():
            continue
        try:
            with candidate.open("r", encoding="utf-8", errors="replace") as stream:
                if any(line.startswith("Proj Title=") for line in stream):
                    projects.append(candidate)
        except OSError:
            continue
    return projects


def _resolve_project_file(project: Union[str, Path]) -> Path:
    path = RasUtils.safe_resolve(Path(project))
    if path.is_file():
        if path.suffix.lower() != ".prj":
            raise ValueError(f"Expected a HEC-RAS .prj file: {path}")
        _assert_regular_path(path)
        projects = _valid_project_files(path.parent)
        if path not in projects:
            raise ValueError(f"File is not a HEC-RAS project (missing Proj Title=): {path}")
        return path
    if not path.exists():
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
    try:
        return os.path.samefile(left, right)
    except OSError:
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _source_contains_destination(source_root: Path, destination_parent: Path) -> bool:
    """Prove overlap through existing ancestor identities, including mapped aliases."""
    candidate = destination_parent
    while True:
        if _same_file(source_root, candidate):
            return True
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent


def _explicit_ras(project_file: Path, ras_object: Optional[RasPrj]) -> RasPrj:
    if ras_object is None:
        return init_ras_project(
            project_file,
            ras_version=_declared_current_plan_version(project_file),
            ras_object=RasPrj(),
            load_results_summary=False,
            hide_intro=True,
        )
    if not isinstance(ras_object, RasPrj):
        raise TypeError("ras_object must be an initialized RasPrj instance")
    ras_object.check_initialized()
    object_project = Path(ras_object.prj_file)
    if not _same_file(project_file, object_project):
        raise ValueError(
            "ras_object does not identify the same physical project file as project"
        )
    return ras_object


def _read_key(path: Path, key: str) -> Optional[str]:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        prefix = f"{key}="
        for line in stream:
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    return None


def _declared_current_plan_version(project_file: Path) -> Optional[str]:
    current = (_read_key(project_file, "Current Plan") or "").strip()
    if not re.fullmatch(r"[pP]\d{2,3}", current):
        return None
    plan_file = project_file.parent / f"{project_file.stem}.{current.lower()}"
    version = (_read_key(plan_file, "Program Version") or "").strip()
    match = re.fullmatch(r"(\d+)\.(\d)0", version)
    return f"{match.group(1)}.{match.group(2)}" if match else (version or None)


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
        root_real = os.path.normcase(os.path.realpath(project_root))
        path_real = os.path.normcase(os.path.realpath(path))
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
    }
    if path is None:
        return facts
    try:
        exists = path.exists()
        facts["exists"] = exists
        if not exists:
            facts["is_file"] = False
            facts["is_dir"] = False
            return facts
        info = path.stat()
        facts.update(
            is_file=path.is_file(),
            is_dir=path.is_dir(),
            volume_id=str(info.st_dev),
            file_id=str(info.st_ino),
            size_bytes=info.st_size if path.is_file() else None,
            mtime_ns=info.st_mtime_ns,
        )
        if hash_file and path.is_file():
            cache = _ACTIVE_INVENTORY_HASH_CACHE.get()
            facts["sha256"] = cache.digest(path) if cache is not None else _sha256_file(path)
    except OSError:
        pass
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
) -> str:
    facts = _path_facts(path, hash_file=hash_files)
    scope, portable = ("ambiguous", None) if path is None else _path_scope(project_root, path)
    if state is None:
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
    if hash_files and owner is not None and owner.is_file():
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
        **facts,
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
    ras_obj = _explicit_ras(project_file, ras_object)
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
        geometry_number = plan.get("geometry_number")
        if pd.notna(geometry_number):
            referenced_geometries.add(str(geometry_number))
        flow_number = plan.get("Flow File")
        if pd.notna(flow_number):
            flow_kind = "unsteady_flow" if pd.notna(plan.get("unsteady_number")) else "steady_flow"
            referenced_flows.add((flow_kind, str(flow_number)))

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
                    or flow_type == "steady"
                )
                hdf_state = None if required_hdf else "not_applicable"
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
                    reason_code="not_used_before_hec_ras_5" if hdf_state else None,
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

    for occurrence, (_, geometry) in enumerate(ras_obj.geom_df.iterrows()):
        number = str(geometry.get("geom_number"))
        if filter_components and number not in referenced_geometries:
            continue
        path = Path(str(geometry.get("full_path")))
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
            parent_asset_id=project_id,
            occurrence=occurrence,
        )

    flow_frames = (("steady_flow", ras_obj.flow_df), ("unsteady_flow", ras_obj.unsteady_df))
    for kind, frame in flow_frames:
        for occurrence, (_, flow) in enumerate(frame.iterrows()):
            number_key = "flow_number" if kind == "steady_flow" else "unsteady_number"
            number = str(flow.get(number_key))
            if filter_components and (kind, number) not in referenced_flows:
                continue
            path = Path(str(flow.get("full_path")))
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
                source_api=f"RasPrj.{('flow_df' if kind == 'steady_flow' else 'unsteady_df')}",
                hash_files=hash_files,
                unsteady_number=number if kind == "unsteady_flow" else None,
                parent_asset_id=project_id,
                occurrence=occurrence,
            )

    rasmap_path = project_root / f"{project_file.stem}.rasmap"
    rasmap_id: Optional[str] = None
    if rasmap_path.exists() or getattr(ras_obj, "rasmap_df", pd.DataFrame()).shape[0]:
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
    if not rasmap_df.empty:
        for column, kind in _RASMAP_KINDS.items():
            if column not in rasmap_df.columns:
                continue
            for occurrence, raw_path in enumerate(_as_values(rasmap_df.iloc[0].get(column))):
                path = RasUtils.safe_resolve(Path(raw_path))
                seen_map_paths.add(os.path.normcase(str(path)))
                map_required = (
                    True
                    if kind in {
                        "terrain",
                        "landcover",
                        "infiltration",
                        "soils",
                        "projection",
                    }
                    else False
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

    if rasmap_path.is_file():
        try:
            root = ET.parse(rasmap_path).getroot()
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

            try:
                dss_boundaries = RasUnsteady.get_dss_boundaries(
                    unsteady_path,
                    ras_object=ras_obj,
                )
            except Exception as exc:
                dss_boundaries = pd.DataFrame()
                _add_asset(
                    rows,
                    inventory_id=inventory_id,
                    depth=depth,
                    project_root=project_root,
                    kind="dss_pathname",
                    role="declared_input",
                    owner=unsteady_path,
                    raw=None,
                    path=None,
                    required=None,
                    source_api="RasUnsteady.get_dss_boundaries",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    state="failed",
                    readiness="unknown",
                    reason_code="boundary_parse_failed",
                    detail=str(exc)[:500],
                )
            for occurrence, (_, boundary) in enumerate(dss_boundaries.iterrows()):
                raw_file = str(boundary.get("dss_file") or "").strip()
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
                    source_api="RasUnsteady.get_dss_boundaries",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    expected_start=window[0],
                    expected_end=window[1],
                    occurrence=occurrence,
                    reason_code="reference_missing" if not raw_file else None,
                )
                raw_pathname = str(boundary.get("dss_path") or "").strip()
                requested_reason = (
                    "dss_inspection_not_requested"
                    if dss_inspection == "none"
                    else "reader_not_source_immutable"
                )
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
                    source_api="RasUnsteady.get_dss_boundaries",
                    hash_files=hash_files,
                    plan_number=first_plan,
                    unsteady_number=unsteady_number,
                    parent_asset_id=file_id,
                    dataset_name=raw_pathname or None,
                    expected_start=window[0],
                    expected_end=window[1],
                    state="not_inspected",
                    readiness="unknown",
                    reason_code=requested_reason,
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
            except (OSError, ValueError):
                pass

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
            except (OSError, ValueError):
                precipitation = {}
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
                        state="not_inspected",
                        readiness="unknown",
                        reason_code=(
                            "dss_inspection_not_requested"
                            if dss_inspection == "none"
                            else "reader_not_source_immutable"
                        ),
                    )
                elif source == "GDAL Raster File(s)":
                    raw_file = str(precipitation.get("gdal_filename") or "").strip()
                    raw_folder = str(precipitation.get("gdal_folder") or "").strip()
                    raw = raw_file or raw_folder
                    path = _resolve_reference(unsteady_path, raw) if raw else None
                    _add_asset(
                        rows,
                        inventory_id=inventory_id,
                        depth=depth,
                        project_root=project_root,
                        kind="gridded_dataset",
                        role="declared_input",
                        owner=unsteady_path,
                        raw=raw,
                        path=path,
                        required=True,
                        source_api="RasUnsteady.get_met_precipitation_config",
                        hash_files=hash_files,
                        plan_number=first_plan,
                        unsteady_number=unsteady_number,
                        dataset_name=str(precipitation.get("gdal_group") or "") or None,
                        reason_code="reference_missing" if not raw else None,
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
    }
    scope: dict[str, list[tuple[str, Optional[datetime], Optional[datetime]]]] = {}
    for _, plan in plans.iterrows():
        unsteady = plan.get("unsteady_number")
        if pd.isna(unsteady):
            continue
        plan_number = str(plan.get("plan_number"))
        start, end = _plan_window(Path(str(plan.get("full_path"))))
        scope.setdefault(str(unsteady), []).append((plan_number, start, end))

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
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
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
    for directory, directory_names, _ in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
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
        (destination_root / Path(relative)).mkdir(parents=True, exist_ok=False)
    for relative in sorted(files, key=str.casefold):
        source = source_root / Path(relative)
        target = destination_root / Path(relative)
        _assert_regular_path(source)
        shutil.copy2(source, target, follow_symlinks=False)


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
    core_kinds = {"project", "plan", "geometry", "steady_flow", "unsteady_flow"}
    invalid = assets.loc[
        assets["asset_kind"].isin(core_kinds)
        & (assets["required"] == True)  # noqa: E712
        & (assets["inspection_state"] != "available")
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
    if temp_root is None or not temp_root.exists():
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
        sentinel_matches = sentinel.is_file() and sentinel.read_text(
            encoding="ascii"
        ) == operation_id
    except OSError:
        pass
    try:
        manifest_matches = manifest.is_file() and json.loads(
            manifest.read_text(encoding="utf-8")
        ).get("operation_id") == operation_id
    except (OSError, ValueError, TypeError):
        pass
    if not parent_matches or not (sentinel_matches or manifest_matches):
        logger.error("Refusing cleanup of unverified staging directory: %s", temp_root)
        return False
    shutil.rmtree(temp_root)
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
        info = lock_path.stat()
        if (info.st_dev, info.st_ino) != lock_identity:
            raise RuntimeError("lock file identity changed")
        if lock_path.read_bytes() != lock_token:
            raise RuntimeError("lock file token changed")
        lock_path.unlink()
    except FileNotFoundError:
        return
    except (OSError, RuntimeError) as exc:
        logger.error("Refusing cleanup of unverified staging lock %s: %s", lock_path, exc)


def _fsync_path(path: Path, *, directory: bool = False) -> None:
    """Flush one path when the host filesystem exposes a usable primitive."""
    flags = os.O_RDONLY
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as exc:
        unsupported = exc.errno in {
            errno.EACCES,
            errno.EBADF,
            errno.EINVAL,
            errno.ENOTSUP,
        } or getattr(exc, "winerror", None) in {5, 6, 50, 87}
        if not unsupported:
            raise ProjectPublicationError(
                "fsync_failed",
                f"Could not durably flush staging path: {path}",
            ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    for directory, directory_names, file_names in os.walk(
        root,
        topdown=False,
        followlinks=False,
    ):
        current = Path(directory)
        for name in sorted(file_names, key=str.casefold):
            path = current / name
            _assert_regular_path(path)
            _fsync_path(path)
        for name in sorted(directory_names, key=str.casefold):
            child = current / name
            _assert_regular_path(child, expected_directory=True)
            _fsync_path(child, directory=True)
        _fsync_path(current, directory=True)


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
    if os.path.lexists(destination_root):
        raise FileExistsError(f"Destination already exists: {destination_root}")
    destination_parent = destination_root.parent
    if not destination_parent.exists():
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

    source_real = os.path.normcase(os.path.realpath(source_root))
    destination_real = os.path.normcase(os.path.realpath(destination_root))
    try:
        overlap = os.path.commonpath([source_real, destination_real]) in {
            source_real,
            destination_real,
        }
    except ValueError:
        overlap = False
    if overlap or _source_contains_destination(source_root, destination_parent):
        raise ProjectPathAmbiguityError(
            "path_overlap",
            "Source and destination project trees must not overlap",
        )
    if (source_root / _STAGE_METADATA_DIR).exists():
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
            lock_handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
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
        temp_root = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_root.name}.ras-stage-",
                dir=destination_parent,
            )
        )
        sentinel = temp_root / _TEMP_SENTINEL
        sentinel.write_text(operation_id, encoding="ascii")
        _copy_snapshot(
            source_root,
            temp_root,
            source_files_before,
            source_directories_before,
        )

        sentinel.unlink()
        try:
            copied_files, copied_fingerprint, copied_total = _tree_snapshot(temp_root)
            copied_directories = _directory_population(temp_root)
        finally:
            if temp_root.exists() and not sentinel.exists():
                sentinel.write_text(operation_id, encoding="ascii")
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

        temp_project = temp_root / source_project.relative_to(source_root)
        try:
            staged_ras = init_ras_project(
                temp_project,
                ras_version=_declared_current_plan_version(temp_project),
                ras_object=RasPrj(),
                load_results_summary=False,
                hide_intro=True,
            )
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

        metadata_dir = temp_root / _STAGE_METADATA_DIR
        metadata_dir.mkdir(exist_ok=False)
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
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")

        sentinel.unlink()
        _, published_fingerprint, _ = _tree_snapshot(temp_root)
        _fsync_tree(temp_root)
        if os.path.lexists(destination_root):
            raise ProjectPublicationError(
                "destination_race",
                f"Destination appeared during staging: {destination_root}",
            )
        try:
            os.rename(temp_root, destination_root)
        except OSError as exc:
            raise ProjectPublicationError(
                "atomic_rename_failed",
                f"Could not publish the verified staging directory: {destination_root}",
            ) from exc
        published = True
        temp_root = None
        _fsync_path(destination_parent, directory=True)

        destination_project = destination_root / source_project.name
        try:
            final_ras = init_ras_project(
                destination_project,
                ras_version=_declared_current_plan_version(destination_project),
                ras_object=RasPrj(),
                load_results_summary=False,
                hide_intro=True,
            )
            final_assets = inspect_project_assets(
                destination_project,
                ras_object=final_ras,
                depth="all_plans",
                hash_files=True,
                dss_inspection="none",
            )
        except Exception as exc:
            raise ProjectPublicationError(
                "post_publication_verification_failed",
                f"Published project could not be reverified: {destination_project}",
            ) from exc
        state_counts = final_assets["inspection_state"].value_counts().to_dict()
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
        if not published:
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
        raise
    finally:
        if lock_handle is not None:
            os.close(lock_handle)
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
