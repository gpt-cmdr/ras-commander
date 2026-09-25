"""Hardened organizer for the Pedernales (12090206) eBFE delivery.

The FEMA archive contains 530 independent HEC-RAS 4.1 steady-flow projects.
Eight result/preprocessed-geometry files were delivered under the wrong model
folders.  They are copied to the folders that reference them while the
delivered source locations and the immutable archive remain unchanged.

This module only assembles and statically audits the corpus.  It never starts
HEC-RAS; execution evidence belongs to the separate qualification workflow.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ras_commander.LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

__all__ = ["organize_pedernales", "pedernales_is_reusable"]

HUC8 = "12090206"
STUDY_NAME = "Pedernales"
SOURCE_ARCHIVE_NAME = "12090206_Models.zip"
SOURCE_URL = "https://ebfedata.s3.amazonaws.com/12090206_Pedernales/12090206_Models.zip"
SOURCE_SIZE_BYTES = 138_116_094
SOURCE_ETAG = "b73ad7fff398baa8132d40296a0e30ee-9"
ARCHIVE_FILE_COUNT = 5_109
ARCHIVE_DIRECTORY_COUNT = 1_066
ARCHIVE_EXPANDED_BYTES = 570_955_840
PROJECT_COUNT = 530
MANIFEST_NAME = "pedernales_manifest.json"
EXTRACTION_RECEIPT_NAME = ".ras-commander-extraction.json"

# Paths are relative to the organized delivery root.  Copying, rather than
# moving, is intentional: every source folder is itself one of the 530 valid
# projects in the delivered corpus.
ASSET_COPY_REPAIRS: tuple[tuple[str, str], ...] = (
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.g01.hdf"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.g01.hdf"
        ),
    ),
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.p01.computeMsgs.txt"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.p01.computeMsgs.txt"
        ),
    ),
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.p01.hdf"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/MIDDLE CREEK/"
            "MIDDLE CREEK.p01.hdf"
        ),
    ),
    (
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "EAST FORK ROCKY CREEK/EAST FORK ROCKY CREEK.g01.hdf"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "MIDDLE FORK WILLIAMS CREEK/EAST FORK ROCKY CREEK/"
            "EAST FORK ROCKY CREEK.g01.hdf"
        ),
    ),
    (
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "EAST FORK ROCKY CREEK/EAST FORK ROCKY CREEK.p01.computeMsgs.txt"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "MIDDLE FORK WILLIAMS CREEK/EAST FORK ROCKY CREEK/"
            "EAST FORK ROCKY CREEK.p01.computeMsgs.txt"
        ),
    ),
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/WHITE OAK CREEK/"
            "WHITE OAK CREEK.g01.hdf"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "WHITE OAK CREEK/WHITE OAK CREEK.g01.hdf"
        ),
    ),
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/WHITE OAK CREEK/"
            "WHITE OAK CREEK.p01.computeMsgs.txt"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "WHITE OAK CREEK/WHITE OAK CREEK.p01.computeMsgs.txt"
        ),
    ),
    (
        (
            "RAS Model/Model/Headwaters- Pedernales River/WHITE OAK CREEK/"
            "WHITE OAK CREEK.p01.hdf"
        ),
        (
            "RAS Model/Model/North Grape Creek - Pedernales River/"
            "WHITE OAK CREEK/WHITE OAK CREEK.p01.hdf"
        ),
    ),
)

_REFERENCE_PATTERN = re.compile(
    r"^(?P<key>Current Plan|Plan File|Geom File|Flow File)\s*=\s*(?P<value>[^\r\n]+)",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _extended_path(path: str | Path) -> str:
    """Return a Windows extended-length path without resolving mapped drives."""
    text = str(Path(path).absolute())
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text.lstrip("\\")
    return "\\\\?\\" + text


def _source_sidecar_path(archive: Path) -> Path:
    return archive.parent / f"{archive.name}.ebfe-source.json"


def _normalize_etag(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().strip('"').strip("'")
    return normalized or None


def _resolve_archive(downloaded_folder: str | Path | None) -> Path:
    source = Path(
        downloaded_folder or f"./ebfe_downloads/{HUC8}_{STUDY_NAME}"
    ).resolve()
    archive = (
        source if source.suffix.casefold() == ".zip" else source / SOURCE_ARCHIVE_NAME
    )
    if archive.is_file():
        return archive

    # Use the existing identity-bound, resumable downloader.  The import is
    # intentionally local so ebfe_models can expose this organizer without a
    # module-import cycle.
    archive.parent.mkdir(parents=True, exist_ok=True)
    from ras_commander.sources.federal.ebfe_models import RasEbfeModels

    RasEbfeModels._download_file(
        SOURCE_URL,
        archive,
        description="Pedernales models (138 MB)",
        expected_size_bytes=SOURCE_SIZE_BYTES,
        expected_etag=SOURCE_ETAG,
    )
    return archive


def _validate_source_identity(archive: Path) -> dict[str, Any]:
    if not archive.is_file():
        raise FileNotFoundError(f"Pedernales source archive not found: {archive}")
    actual_size = archive.stat().st_size
    if actual_size != SOURCE_SIZE_BYTES:
        raise RuntimeError(
            f"Pedernales source size mismatch: expected {SOURCE_SIZE_BYTES}, "
            f"found {actual_size}."
        )
    sidecar_path = _source_sidecar_path(archive)
    if not sidecar_path.is_file():
        raise RuntimeError(
            "Pedernales source ETag and URL cannot be verified: the "
            ".ebfe-source.json sidecar is missing."
        )
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid Pedernales source sidecar: {sidecar_path}"
        ) from exc
    if sidecar.get("source") != SOURCE_URL:
        raise RuntimeError(
            "Pedernales source sidecar URL does not match the catalogued FEMA source."
        )
    if int(sidecar.get("size", -1)) != actual_size:
        raise RuntimeError("Pedernales source sidecar size does not match the archive.")
    recorded_etag = _normalize_etag(sidecar.get("etag"))
    if recorded_etag != SOURCE_ETAG:
        raise RuntimeError(
            f"Pedernales source ETag mismatch: expected {SOURCE_ETAG}, "
            f"recorded {recorded_etag}."
        )
    return {
        "path": str(archive),
        "source_url": SOURCE_URL,
        "size_bytes": actual_size,
        "size_verified": True,
        "etag": recorded_etag,
        "etag_verified": True,
        "sidecar": str(sidecar_path),
    }


def _member_relative_path(member: zipfile.ZipInfo) -> Path:
    archive_path = PurePosixPath(member.filename.replace("\\", "/"))
    parts = tuple(part for part in archive_path.parts if part not in {"", "."})
    if (
        not parts
        or archive_path.is_absolute()
        or any(part == ".." for part in parts)
        or parts[0].endswith(":")
    ):
        raise ValueError(f"Unsafe ZIP member path: {member.filename!r}")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
    for part in parts:
        if (
            ":" in part
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in reserved
        ):
            raise ValueError(f"Invalid portable ZIP member path: {member.filename!r}")
    unix_mode = member.external_attr >> 16
    if unix_mode & 0o170000 == 0o120000:
        raise ValueError(f"ZIP symbolic links are not supported: {member.filename!r}")
    return Path(*parts)


def _validated_members(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, Path]]:
    members: list[tuple[zipfile.ZipInfo, Path]] = []
    targets: set[str] = set()
    for member in archive.infolist():
        relative = _member_relative_path(member)
        target_key = relative.as_posix().casefold()
        if target_key in targets and not member.is_dir():
            raise ValueError(f"Duplicate ZIP extraction target: {member.filename!r}")
        targets.add(target_key)
        members.append((member, relative))
    files = [member for member, _ in members if not member.is_dir()]
    directories = len(members) - len(files)
    expanded_bytes = sum(member.file_size for member in files)
    if (
        len(files) != ARCHIVE_FILE_COUNT
        or directories != ARCHIVE_DIRECTORY_COUNT
        or expanded_bytes != ARCHIVE_EXPANDED_BYTES
    ):
        raise RuntimeError(
            "Pedernales archive contract mismatch: expected "
            f"{ARCHIVE_FILE_COUNT} files, {ARCHIVE_DIRECTORY_COUNT} directories, "
            f"and {ARCHIVE_EXPANDED_BYTES} expanded bytes; found {len(files)} files, "
            f"{directories} directories, and {expanded_bytes} bytes."
        )
    nested = [
        relative.as_posix()
        for member, relative in members
        if not member.is_dir() and relative.suffix.casefold() == ".zip"
    ]
    if nested:
        raise RuntimeError(
            f"Pedernales archive unexpectedly contains nested ZIPs: {nested[:3]}"
        )
    return members


def _zip_member_timestamp(member: zipfile.ZipInfo) -> float:
    offset = 0
    extra = member.extra or b""
    while offset + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, offset)
        data_start = offset + 4
        data = extra[data_start : data_start + field_size]
        offset = data_start + field_size
        if field_id == 0x5455 and len(data) >= 5 and data[0] & 1:
            utc_value = datetime.fromtimestamp(
                struct.unpack_from("<I", data, 1)[0], timezone.utc
            )
            return utc_value.replace(tzinfo=None).timestamp()
    return datetime(*member.date_time, tzinfo=timezone.utc).timestamp()


def _extract_verified(
    archive_path: Path,
    destination: Path,
) -> dict[str, Any]:
    """Extract once while consuming every member through its CRC boundary."""
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = _validated_members(archive)
        file_count = 0
        verified_bytes = 0
        maximum_path_length = len(str(destination))
        for member, relative in members:
            target = destination / relative
            maximum_path_length = max(maximum_path_length, len(str(target)))
            if member.is_dir():
                os.makedirs(_extended_path(target), exist_ok=True)
                continue
            os.makedirs(_extended_path(target.parent), exist_ok=True)
            checksum = 0
            written = 0
            with (
                archive.open(member, "r") as source_stream,
                open(_extended_path(target), "wb") as target_stream,
            ):
                while chunk := source_stream.read(1024 * 1024):
                    target_stream.write(chunk)
                    checksum = zlib.crc32(chunk, checksum)
                    written += len(chunk)
            checksum &= 0xFFFFFFFF
            if written != member.file_size or checksum != member.CRC:
                raise RuntimeError(
                    f"Pedernales extraction integrity failure: {relative.as_posix()}"
                )
            timestamp = _zip_member_timestamp(member)
            os.utime(_extended_path(target), (timestamp, timestamp))
            file_count += 1
            verified_bytes += written
    receipt = {
        "schema_version": 1,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "archive_name": archive_path.name,
        "archive_size": archive_path.stat().st_size,
        "file_count": file_count,
        "directory_count": ARCHIVE_DIRECTORY_COUNT,
        "verified_bytes": verified_bytes,
        "crc32_verified": True,
        "maximum_expanded_path_length": maximum_path_length,
    }
    (destination / EXTRACTION_RECEIPT_NAME).write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def _file_crc32(path: Path) -> int:
    checksum = 0
    with open(_extended_path(path), "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum = zlib.crc32(chunk, checksum)
    return checksum & 0xFFFFFFFF


def _is_file(path: Path) -> bool:
    return os.path.isfile(_extended_path(path))


def _is_dir(path: Path) -> bool:
    return os.path.isdir(_extended_path(path))


def _path_exists(path: Path) -> bool:
    return os.path.exists(_extended_path(path))


def _file_size(path: Path) -> int:
    return os.path.getsize(_extended_path(path))


def _apply_asset_copy_repairs(organized_root: Path) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for source_relative, destination_relative in ASSET_COPY_REPAIRS:
        source = organized_root / Path(source_relative)
        destination = organized_root / Path(destination_relative)
        if not _is_file(source):
            raise RuntimeError(
                f"Pedernales audited repair source is missing: {source_relative}"
            )
        if _path_exists(destination):
            raise RuntimeError(
                "Pedernales repair destination unexpectedly exists before repair: "
                f"{destination_relative}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_extended_path(source), _extended_path(destination))
        if _file_size(source) != _file_size(destination) or _file_crc32(
            source
        ) != _file_crc32(destination):
            raise RuntimeError(
                f"Pedernales repair copy verification failed: {destination_relative}"
            )
        applied.append(
            {
                "action": "copy",
                "source": source_relative,
                "destination": destination_relative,
                "size_bytes": _file_size(destination),
                "crc32": f"{_file_crc32(destination):08x}",
            }
        )
    return applied


def _read_references(path: Path) -> dict[str, str]:
    text = path.read_bytes().decode("latin-1")
    return {
        match.group("key").casefold(): match.group("value").strip()
        for match in _REFERENCE_PATTERN.finditer(text)
    }


def _referenced_component(project_file: Path, value: str) -> Path:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z]\d{2}", value):
        raise RuntimeError(
            f"Unsupported Pedernales component reference {value!r} in {project_file}"
        )
    return project_file.with_suffix(f".{value}")


def _audit_workspace(organized_root: Path) -> dict[str, Any]:
    model_root = organized_root / "RAS Model" / "Model"
    errors: list[str] = []
    if not _is_dir(model_root):
        return {
            "active_hydraulic_reference_closure": False,
            "project_count": 0,
            "errors": ["RAS Model/Model is missing"],
        }
    scan_root = Path(_extended_path(model_root))
    project_files = []
    for candidate in scan_root.rglob("*.prj"):
        try:
            references = _read_references(candidate)
        except OSError:
            continue
        if "current plan" in references:
            project_files.append((candidate, references))
    if len(project_files) != PROJECT_COUNT:
        errors.append(
            f"expected {PROJECT_COUNT} RAS projects, found {len(project_files)}"
        )
    parents = [project.parent for project, _ in project_files]
    if len({str(parent).casefold() for parent in parents}) != len(parents):
        errors.append("multiple RAS project files share a project folder")

    for project, project_refs in project_files:
        relative = project.relative_to(scan_root).as_posix()
        # A project file registers every available component. Two delivered
        # projects intentionally retain non-current artifacts titled
        # ``Delete`` (one p02 and one g02), so the last repeated Plan/Geom File
        # line is not an active-model association. Only Current Plan belongs to
        # the project-level gate; geometry and flow are resolved from p01.
        if project_refs.get("current plan", "").casefold() != "p01":
            errors.append(f"{relative}: current plan is not p01")
        try:
            plan = _referenced_component(project, project_refs.get("current plan", ""))
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        if not _is_file(plan):
            errors.append(f"{relative}: selected plan is missing")
            continue
        plan_refs = _read_references(plan)
        for key, expected in (("geom file", "g01"), ("flow file", "f01")):
            value = plan_refs.get(key, "")
            if value.casefold() != expected:
                errors.append(f"{relative}: plan {key} is not {expected}")
                continue
            try:
                component = _referenced_component(project, value)
            except RuntimeError as exc:
                errors.append(str(exc))
                continue
            if not _is_file(component):
                errors.append(f"{relative}: referenced {key} is missing")

    repair_errors = []
    for source_relative, destination_relative in ASSET_COPY_REPAIRS:
        source = organized_root / Path(source_relative)
        destination = organized_root / Path(destination_relative)
        if (
            not _is_file(source)
            or not _is_file(destination)
            or (
                _file_size(source) != _file_size(destination)
                or _file_crc32(source) != _file_crc32(destination)
            )
        ):
            repair_errors.append(destination_relative)
    errors.extend(f"repair copy invalid: {path}" for path in repair_errors)
    return {
        "active_hydraulic_reference_closure": not errors,
        "project_count": len(project_files),
        "selected_plan": "p01",
        "geometry": "g01",
        "steady_flow": "f01",
        "repair_copy_count": len(ASSET_COPY_REPAIRS) - len(repair_errors),
        "terrain_applicability": "not_applicable_1d_steady",
        "errors": errors,
    }


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(_extended_path(path))


def _promote_atomically(working: Path, output_folder: Path) -> Path | None:
    backup = None
    if output_folder.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = output_folder.parent / f"{output_folder.name}.interrupted-{timestamp}"
        os.replace(_extended_path(output_folder), _extended_path(backup))
    try:
        os.replace(_extended_path(working), _extended_path(output_folder))
    except Exception:
        if backup is not None and backup.exists() and not output_folder.exists():
            os.replace(_extended_path(backup), _extended_path(output_folder))
        raise
    return backup


@log_call
def pedernales_is_reusable(
    output_folder: str | Path,
    downloaded_folder: str | Path | None = None,
) -> bool:
    """Return whether an organized Pedernales corpus still meets its contract."""
    output_folder = Path(output_folder).resolve()
    manifest_path = output_folder / "agent" / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("huc8") != HUC8
            or manifest.get("project_count") != PROJECT_COUNT
            or manifest.get("validation_status") != "pending"
            or manifest.get("hec_ras_executed") is not False
            or manifest.get("terrain_applicability") != "not_applicable_1d_steady"
            or manifest.get("terrain_required") is not False
            or manifest.get("asset_copy_repairs", {}).get("applied")
            != len(ASSET_COPY_REPAIRS)
        ):
            return False
        if downloaded_folder is None:
            archive = Path(manifest["source_identity"]["path"])
        else:
            source = Path(downloaded_folder).resolve()
            archive = (
                source
                if source.suffix.casefold() == ".zip"
                else source / SOURCE_ARCHIVE_NAME
            )
        _validate_source_identity(archive)
        audit = _audit_workspace(output_folder)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(audit["active_hydraulic_reference_closure"])


@log_call
def organize_pedernales(
    downloaded_folder: str | Path | None = None,
    output_folder: str | Path | None = None,
) -> Path:
    """Download if needed, then organize the 530-project Pedernales corpus.

    The archive identity is bound to FEMA's exact URL, size, and multipart
    ETag.  Extraction rejects traversal, Windows path collisions, symlinks,
    and unexpected members; every extracted file is checked by size and CRC32.
    A fresh organization is always marked pending and unexecuted.
    """
    output_folder = Path(
        output_folder or f"./ebfe_organized/{STUDY_NAME}_{HUC8}"
    ).resolve()
    archive = _resolve_archive(downloaded_folder)
    if pedernales_is_reusable(output_folder, archive):
        return output_folder

    source_identity = _validate_source_identity(archive)
    sidecar = _source_sidecar_path(archive)
    source_state = {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (archive, sidecar)
    }
    output_folder.parent.mkdir(parents=True, exist_ok=True)
    working = Path(
        tempfile.mkdtemp(
            prefix=f".{output_folder.name}.assembling-",
            dir=output_folder.parent,
        )
    )
    try:
        ras_root = working / "RAS Model"
        extraction = _extract_verified(archive, ras_root)
        repairs = _apply_asset_copy_repairs(working)
        audit = _audit_workspace(working)
        if not audit["active_hydraulic_reference_closure"]:
            raise RuntimeError(
                "Pedernales active hydraulic reference closure failed: "
                f"{audit['errors'][:10]}"
            )
        (working / "agent").mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "study": STUDY_NAME,
            "huc8": HUC8,
            "source_program": "fema_ebfe",
            "model_type": "1d_steady",
            "delivered_ras_version": "4.1.0",
            "target_validation_ras_version": "6.6",
            "source_identity": source_identity,
            "archive_extraction": extraction,
            "project_count": PROJECT_COUNT,
            "canonical_plan": "p01",
            "asset_copy_repairs": {
                "expected": len(ASSET_COPY_REPAIRS),
                "applied": len(repairs),
                "items": repairs,
            },
            "reference_audit": audit,
            "terrain_applicability": "not_applicable_1d_steady",
            "terrain_required": False,
            "terrain_source_complete": None,
            "delivery_readiness": "repairable_from_delivery",
            "required_validation_level": "steady_plan_completion",
            "validation_status": "pending",
            "fresh_output_status": "pending",
            "hec_ras_executed": False,
            "downstream_usable": False,
            "reproducible": False,
            "source_objects_immutable": True,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        (working / "agent" / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (working / "agent" / "model_log.md").write_text(
            "# Pedernales (12090206) organization log\n\n"
            "The FEMA HEC-RAS 4.1 delivery contains 530 independent 1D "
            "steady-flow projects. Eight misplaced delivered assets were copied "
            "to their referenced project folders and verified by CRC32; source "
            "copies were retained. Terrain is not applicable to this 1D steady "
            "corpus. Fresh selected-plan execution of all 530 projects is "
            "pending.\n",
            encoding="utf-8",
        )
        final_state = {
            str(path): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in (archive, sidecar)
        }
        if source_state != final_state:
            raise RuntimeError("Pedernales source objects changed during organization.")
        _promote_atomically(working, output_folder)
    except Exception:
        _remove_tree(working)
        raise
    return output_folder
