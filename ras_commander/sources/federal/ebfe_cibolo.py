"""Strict organizer for FEMA eBFE Cibolo delivery 12100304.

The public delivery is an outer ZIP containing ``Hydraulic_Models/_Final.zip``.
This module verifies the pinned outer object, CRC-extracts both archive levels,
replays only the audited active-model path corrections, and promotes the result
atomically.  It intentionally does not execute HEC-RAS; fresh organizations are
always recorded as pending runtime qualification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ras_commander.LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

__all__ = ["cibolo_output_is_reusable", "organize_cibolo_delivery"]

SOURCE_URL = (
    "https://ebfedata.s3.amazonaws.com/12100304_Cibolo/"
    "12100304_Models.zip"
)
SOURCE_NAME = "12100304_Models.zip"
SOURCE_SIZE_BYTES = 38_827_758_483
SOURCE_ETAG = "7d88e8a2b047780c8df9fd486c7bb34d-4629"
SOURCE_SIDECAR_SUFFIX = ".ebfe-source.json"

# One directory record plus the inventory and nested final ZIP.
OUTER_MEMBER_COUNT = 3
# The nested ZIP contains 258 files and 16 directory entries.
NESTED_MEMBER_COUNT = 274
NESTED_ARCHIVE_MEMBER = "Hydraulic_Models/_Final.zip"
INVENTORY_MEMBER = "Hydraulic_Models/2D_Model_Inventory_Cibolo.xlsx"

PROJECT_NAME = "Cibolo"
PROJECT_RELATIVE = Path("RAS Model") / "Cibolo" / "HECRAS_507"
TERRAIN_RELATIVE = Path("RAS Model") / "Cibolo" / "Terrain_LandUse"
MANIFEST_RELATIVE = Path("agent") / "cibolo_manifest.json"
MODEL_LOG_RELATIVE = Path("agent") / "model_log.md"

CANONICAL_PLAN = "14"
CANONICAL_GEOMETRY = "05"
CANONICAL_UNSTEADY = "02"
PLAN_NUMBERS = ("05", "06", "07", "08", "09", "10", "14")

_DSS_REPAIRS: Mapping[str, tuple[str, str]] = {
    "01": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\10__ACE.dss",
        r".\Hydrology\10__ACE.dss",
    ),
    "02": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\01__ACE.dss",
        r".\Hydrology\01__ACE.dss",
    ),
    "03": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\04__ACE.dss",
        r".\Hydrology\04__ACE.dss",
    ),
    "04": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\02__ACE.dss",
        r".\Hydrology\02__ACE.dss",
    ),
    "05": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\01__PLUS.dss",
        r".\Hydrology\01__PLUS.dss",
    ),
    "06": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\01__MINUS.dss",
        r".\Hydrology\01__MINUS.dss",
    ),
    "07": (
        r"..\..\..\..\HEC-HMS_v43\Cibolo\Cibolo\002__ACE.dss",
        r".\Hydrology\002__ACE.dss",
    ),
}

_PROJECTION_FROM = r"..\Projections\Cibolo_Projection.prj"
_PROJECTION_TO = r".\Projection\Cibolo_Projection.prj"

_NONBLOCKING_GAPS = (
    {
        "file": "Backup.p01",
        "reference": "g01",
        "classification": "backup_only",
    },
    {
        "file": "Backup.u01",
        "reference": r"..\..\..\..\HEC-HMS_v43\Cibolo\Upper_Cibolo\100YR.dss",
        "classification": "backup_only",
    },
    {
        "file": "Cibolo.rasmap",
        "reference": r".\Features\Profile Lines(2).shp",
        "classification": "display_only",
    },
    {
        "file": "Cibolo.rasmap",
        "reference": r"%LocalAppData%\HEC\Mapping\506\XML\Google Satellite.xml",
        "classification": "host_basemap",
    },
    {
        "file": "Cibolo.rasmap",
        "reference": r"%LocalAppData%\HEC\Mapping\506\XML\Google Map.xml",
        "classification": "host_basemap",
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sidecar_path(archive: Path) -> Path:
    return archive.with_name(archive.name + SOURCE_SIDECAR_SUFFIX)


def _resolve_archive(source: str | Path) -> Path:
    source_path = Path(source).resolve()
    archive = source_path if source_path.is_file() else source_path / SOURCE_NAME
    if not archive.is_file():
        raise FileNotFoundError(f"Cibolo source archive not found: {archive}")
    return archive


def _validate_source_identity(archive: Path) -> dict[str, Any]:
    """Validate exact size, retained multipart ETag, and source URL."""
    sidecar = _sidecar_path(archive)
    if not sidecar.is_file():
        raise RuntimeError(f"Cibolo source identity sidecar is missing: {sidecar}")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cibolo source sidecar is unreadable: {sidecar}") from exc
    size = archive.stat().st_size
    if size != SOURCE_SIZE_BYTES:
        raise RuntimeError(
            f"Cibolo source size mismatch: expected {SOURCE_SIZE_BYTES}, found {size}."
        )
    if payload.get("size") != SOURCE_SIZE_BYTES:
        raise RuntimeError("Cibolo source sidecar size does not match the pinned asset.")
    etag = str(payload.get("etag", "")).strip().strip('"')
    if etag != SOURCE_ETAG:
        raise RuntimeError(
            f"Cibolo source ETag mismatch: expected {SOURCE_ETAG}, found {etag!r}."
        )
    if payload.get("source") != SOURCE_URL:
        raise RuntimeError("Cibolo source sidecar URL does not match the FEMA source.")
    final_url = payload.get("final_url")
    if final_url not in (None, SOURCE_URL):
        raise RuntimeError("Cibolo source sidecar final URL is not the FEMA source.")
    return {
        "path": str(archive),
        "sidecar": str(sidecar),
        "source_url": SOURCE_URL,
        "size_bytes": size,
        "etag": etag,
        "archive_identity_verified": True,
    }


def _source_snapshot(archive: Path) -> dict[str, tuple[int, int]]:
    paths = (archive, _sidecar_path(archive))
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths
    }


def _safe_member_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or any(part in ("", ".", "..") for part in pure.parts)
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise ValueError(f"Unsafe ZIP member: {name!r}")
    return Path(*pure.parts)


def _validated_members(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, Path]]:
    members: list[tuple[zipfile.ZipInfo, Path]] = []
    targets: dict[str, str] = {}
    for info in archive.infolist():
        relative = _safe_member_path(info.filename.rstrip("/"))
        key = relative.as_posix().casefold()
        previous = targets.get(key)
        if previous is not None:
            raise ValueError(
                "Duplicate ZIP extraction target (case-insensitive): "
                f"{previous!r} and {info.filename!r}"
            )
        targets[key] = info.filename
        unix_mode = info.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise ValueError(f"ZIP symlink members are not supported: {info.filename!r}")
        members.append((info, relative))
    return members


def _extract_zip_verified(
    archive_path: Path,
    destination: Path,
    *,
    expected_members: int,
) -> dict[str, Any]:
    """Extract one ZIP with traversal/collision checks and CRC-verified reads."""
    if destination.exists():
        raise RuntimeError(f"Extraction destination already exists: {destination}")
    destination.mkdir(parents=True)
    files = 0
    directories = 0
    bytes_written = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as stream:
            members = _validated_members(stream)
            if len(members) != expected_members:
                raise RuntimeError(
                    f"{archive_path.name} member contract mismatch: expected "
                    f"{expected_members}, found {len(members)}."
                )
            for info, relative in members:
                target = destination / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    directories += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                copied = 0
                with stream.open(info, "r") as reader, target.open("xb") as writer:
                    while True:
                        chunk = reader.read(4 << 20)
                        if not chunk:
                            break
                        writer.write(chunk)
                        copied += len(chunk)
                if copied != info.file_size:
                    raise RuntimeError(
                        f"ZIP size mismatch for {info.filename!r}: "
                        f"expected {info.file_size}, wrote {copied}."
                    )
                files += 1
                bytes_written += copied
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {
        "archive": archive_path.name,
        "members": expected_members,
        "files": files,
        "directories": directories,
        "bytes_written": bytes_written,
        "crc_verified": True,
    }


def _replace_exact(path: Path, old: str, new: str, label: str) -> int:
    text = path.read_text(encoding="utf-8", errors="strict")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return 1
    if old_count == 0 and new_count == 1:
        return 0
    raise RuntimeError(
        f"Cibolo {label} pre-state conflict in {path.name}: "
        f"old_count={old_count}, new_count={new_count}."
    )


def _apply_repairs(project_root: Path) -> dict[str, Any]:
    projection_updates = _replace_exact(
        project_root / "Cibolo.rasmap",
        _PROJECTION_FROM,
        _PROJECTION_TO,
        "projection",
    )
    dss_updates = 0
    for number, (old, new) in _DSS_REPAIRS.items():
        dss_updates += _replace_exact(
            project_root / f"Cibolo.u{number}", old, new, f"u{number} DSS"
        )
    return {
        "recipe_rows": 16,
        "recursive_extraction_rows": 1,
        "asset_relocation_rows": 8,
        "dss_path_updates": dss_updates,
        "rasmap_projection_updates": projection_updates,
        "content_updates": dss_updates + projection_updates,
    }


def _contains_assignment(text: str, key: str, value: str) -> bool:
    return re.search(
        rf"(?mi)^\s*{re.escape(key)}\s*=\s*{re.escape(value)}\s*$", text
    ) is not None


def _require_files(root: Path, relative_paths: Iterable[Path]) -> None:
    missing = [str(path) for path in relative_paths if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f"Cibolo active file contract is incomplete: {missing}")


def _audit_workspace(output_root: Path) -> dict[str, Any]:
    project = output_root / PROJECT_RELATIVE
    terrain = output_root / TERRAIN_RELATIVE
    required = [Path("Cibolo.prj"), Path("Cibolo.g05"), Path("Cibolo.g05.hdf")]
    required.extend(Path(f"Cibolo.p{number}") for number in PLAN_NUMBERS)
    required.extend(Path(f"Cibolo.u{number}") for number in _DSS_REPAIRS)
    required.extend(
        [
            Path("Cibolo.rasmap"),
            Path("Projection/Cibolo_Projection.prj"),
            *(
                Path("Hydrology") / PureWindowsPath(repair[1]).name
                for repair in _DSS_REPAIRS.values()
            ),
        ]
    )
    _require_files(project, required)

    project_text = (project / "Cibolo.prj").read_text(
        encoding="utf-8", errors="replace"
    )
    plan_text = (project / "Cibolo.p14").read_text(
        encoding="utf-8", errors="replace"
    )
    errors: list[str] = []
    if not _contains_assignment(project_text, "Current Plan", "p14"):
        errors.append("Cibolo.prj does not select p14")
    if not _contains_assignment(plan_text, "Geom File", "g05"):
        errors.append("Cibolo.p14 does not bind g05")
    if not _contains_assignment(plan_text, "Flow File", "u02"):
        errors.append("Cibolo.p14 does not bind u02")

    for number, (old, new) in _DSS_REPAIRS.items():
        text = (project / f"Cibolo.u{number}").read_text(
            encoding="utf-8", errors="strict"
        )
        if old in text or text.count(new) != 1:
            errors.append(f"Cibolo.u{number} active DSS reference is not exact")

    rasmap = (project / "Cibolo.rasmap").read_text(
        encoding="utf-8", errors="strict"
    )
    if _PROJECTION_FROM in rasmap or rasmap.count(_PROJECTION_TO) != 1:
        errors.append("Cibolo.rasmap projection reference is not exact")

    terrain_names = {path.name.casefold() for path in terrain.rglob("*") if path.is_file()}
    expected_terrain = {
        "cibolo_terrain_burn.hdf",
        "cibolo_terrain_burn.vrt",
        "cibolo_terrain_burn.cib10_terrain.tif",
        "cibolo_terrain_burn.cibolo_burn10.tif",
        "manningsn_widened2d.hdf",
        "manningsn_widened2d.tif",
    }
    missing_terrain = sorted(expected_terrain - terrain_names)
    if missing_terrain:
        errors.append(f"delivered terrain/land-cover assets missing: {missing_terrain}")

    return {
        "active_hydraulic_reference_closure": not errors,
        "project_count": 1,
        "canonical_plan": "14",
        "canonical_geometry": "05",
        "canonical_unsteady": "02",
        "plans_checked": len(PLAN_NUMBERS),
        "active_dss_references_checked": len(_DSS_REPAIRS),
        "terrain_land_cover_assets_checked": len(expected_terrain),
        "terrain_source_complete": not missing_terrain,
        "errors": errors,
    }


def _inventory(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in (output_root / "RAS Model", output_root / "Documentation"):
        if not scope.is_dir():
            continue
        for path in sorted(item for item in scope.rglob("*") if item.is_file()):
            rows.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "size_bytes": path.stat().st_size,
                }
            )
    return rows


def _inventory_matches(output_root: Path, expected: Sequence[Mapping[str, Any]]) -> bool:
    try:
        return _inventory(output_root) == list(expected)
    except OSError:
        return False


def _promote_atomic(working: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}.replaced-{os.getpid()}")
    if backup.exists():
        raise RuntimeError(f"Cibolo atomic-promotion backup already exists: {backup}")
    moved_old = False
    try:
        if destination.exists():
            os.replace(destination, backup)
            moved_old = True
        os.replace(working, destination)
    except Exception:
        if moved_old and not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


@log_call
def cibolo_output_is_reusable(
    output_folder: str | Path, source: str | Path
) -> bool:
    """Return whether an organized Cibolo tree still satisfies its sealed contract."""
    output = Path(output_folder).resolve()
    if not output.is_dir():
        return False
    try:
        archive = _resolve_archive(source)
        identity = _validate_source_identity(archive)
        manifest = json.loads((output / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
        recorded = manifest["source_identity"]
        for key in ("path", "source_url", "size_bytes", "etag"):
            if recorded.get(key) != identity[key]:
                return False
        if manifest.get("schema_version") != 1:
            return False
        if manifest.get("repair_summary", {}).get("recipe_rows") != 16:
            return False
        if manifest.get("terrain_source_complete") is not True:
            return False
        if not _inventory_matches(output, manifest.get("organized_inventory", [])):
            return False
        return bool(_audit_workspace(output)["active_hydraulic_reference_closure"])
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return False


@log_call
def organize_cibolo_delivery(
    downloaded_folder: str | Path, output_folder: str | Path
) -> Path:
    """Organize the pinned Cibolo eBFE archive into a runnable project tree.

    The function is deliberately execution-free.  It verifies source identity,
    nested ZIP CRCs, active references, delivered terrain and land cover, and
    then records runtime qualification as pending.
    """
    archive = _resolve_archive(downloaded_folder)
    output = Path(output_folder).resolve()
    if cibolo_output_is_reusable(output, archive):
        return output

    identity = _validate_source_identity(archive)
    before = _source_snapshot(archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    working = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.assembling-", dir=output.parent)
    )
    outer = working / ".outer-extraction"
    nested = working / ".nested-extraction"
    try:
        outer_audit = _extract_zip_verified(
            archive, outer, expected_members=OUTER_MEMBER_COUNT
        )
        nested_archive = outer / Path(*PurePosixPath(NESTED_ARCHIVE_MEMBER).parts)
        inventory_source = outer / Path(*PurePosixPath(INVENTORY_MEMBER).parts)
        if not nested_archive.is_file() or not inventory_source.is_file():
            raise RuntimeError(
                "Cibolo outer archive does not contain its exact nested ZIP and inventory."
            )
        nested_audit = _extract_zip_verified(
            nested_archive, nested, expected_members=NESTED_MEMBER_COUNT
        )
        delivered = nested / "_Final"
        project_source = delivered / "HECRAS_507"
        terrain_source = delivered / "Terrain_LandUse"
        projection_source = delivered / "Projections"
        if (
            not project_source.is_dir()
            or not terrain_source.is_dir()
            or not projection_source.is_dir()
        ):
            raise RuntimeError(
                "Cibolo nested archive is missing HECRAS_507, Terrain_LandUse, "
                "or Projections."
            )

        project_destination = working / PROJECT_RELATIVE
        project_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(project_source), str(project_destination))
        shutil.move(str(projection_source), str(project_destination / "Projection"))
        shutil.move(str(terrain_source), str(working / TERRAIN_RELATIVE))
        documentation = working / "Documentation"
        documentation.mkdir()
        shutil.copy2(inventory_source, documentation / inventory_source.name)
        (working / "agent").mkdir()

        repairs = _apply_repairs(project_destination)
        audit = _audit_workspace(working)
        if not audit["active_hydraulic_reference_closure"]:
            raise RuntimeError(
                f"Cibolo active hydraulic reference closure failed: {audit['errors']}"
            )
        too_long = [
            str(output / path.relative_to(working))
            for path in working.rglob("*")
            if path.is_file() and len(str(output / path.relative_to(working))) > 240
        ]
        if too_long:
            raise RuntimeError(
                "Cibolo organized workspace exceeds the 240-character path "
                f"contract: {too_long[:3]}"
            )

        shutil.rmtree(outer)
        shutil.rmtree(nested)
        (working / MODEL_LOG_RELATIVE).write_text(
            "# Cibolo (12100304) organization log\n\n"
            "The FEMA outer ZIP and nested `_Final.zip` were CRC-extracted. "
            "Seven active DSS references and the RASMapper projection reference "
            "were corrected to delivered assets. Terrain and land cover are "
            "delivered and were not rebuilt. Backup-only and display-only gaps "
            "remain documented. Fresh HEC-RAS 5.0.7 p14 unsteady-start "
            "qualification is pending.\n",
            encoding="utf-8",
        )
        organized_inventory = _inventory(working)
        manifest = {
            "schema_version": 1,
            "study": "Cibolo",
            "huc8": "12100304",
            "source_program": "fema_ebfe",
            "lane_kind": "integrated_2d",
            "delivered_ras_version": "5.0.7",
            "source_identity": identity,
            "archive_extraction": {"outer": outer_audit, "nested": nested_audit},
            "project_count": 1,
            "project_relative_path": PROJECT_RELATIVE.as_posix(),
            "plans": list(PLAN_NUMBERS),
            "canonical_plan": CANONICAL_PLAN,
            "canonical_geometry": CANONICAL_GEOMETRY,
            "canonical_unsteady": CANONICAL_UNSTEADY,
            "repair_summary": repairs,
            "reference_audit": audit,
            "terrain_required": True,
            "terrain_source_complete": True,
            "terrain_modification_layers": [],
            "land_cover_source_complete": True,
            "nonblocking_unresolved_references": list(_NONBLOCKING_GAPS),
            "required_validation_level": "unsteady_start",
            "validation_status": "pending",
            "fresh_output_status": "pending",
            "hec_ras_executed": False,
            "downstream_usable": False,
            "reproducible": False,
            "source_objects_immutable": True,
            "organized_inventory": organized_inventory,
            "completed_utc": _utc_now(),
        }
        (working / MANIFEST_RELATIVE).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if before != _source_snapshot(archive):
            raise RuntimeError("Cibolo source objects changed during organization.")
        _promote_atomic(working, output)
    except Exception:
        if working.exists():
            shutil.rmtree(working, ignore_errors=True)
        raise
    return output
