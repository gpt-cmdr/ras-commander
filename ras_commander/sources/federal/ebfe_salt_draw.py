"""Bounded organizer for FEMA eBFE study 13070004 (Salt Draw).

The public delivery is one ZIP (about 67 GB) containing a single HEC-RAS 6.4.1
2D rain-on-grid project, ``SLDR_004``, plus its HEC-HMS model.  Seven plans
share geometry ``g02``; each plan has a delivered result HDF of about 9 GB.
The organizer therefore extracts only the result HDFs the caller selects
(``output_plans``, default ``p01`` and ``p02``, the 1% and 0.2% AEP events).
Plan text files for all seven events are always kept.

The delivered ``RAS_Submittal`` layout is kept as-is.  The project's RASMapper
file and geometry HDF name terrain and land cover as ``..\\Terrain`` and
``..\\Landcover`` relative to ``Input``, and the unsteady files name DSS
inputs under ``.\\Hydrology``.  All of these resolve inside the delivery, so
the organizer makes no text or HDF repairs.

The source may be the pinned public ZIP (identity checked by size and retained
multipart ETag, members CRC-verified) or an already-extracted delivery tree.
An extracted tree is copied without archive identity; the manifest records
that difference.  Organization does not execute HEC-RAS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ras_commander.LoggingConfig import get_logger, log_call
from ras_commander.fast_hdf import release_native_sessions

logger = get_logger(__name__)

__all__ = [
    "DEFAULT_OUTPUT_PLANS",
    "PLAN_EVENTS",
    "SOURCE_ETAG",
    "SOURCE_NAME",
    "SOURCE_SIZE_BYTES",
    "SOURCE_URL",
    "organize_salt_draw",
    "salt_draw_is_reusable",
    "select_salt_draw_members",
]

SOURCE_URL = (
    "https://ebfedata.s3.amazonaws.com/13070004_SaltDraw/13070004_Models.zip"
)
SOURCE_NAME = "13070004_Models.zip"
SOURCE_SIZE_BYTES = 66_982_389_960
SOURCE_ETAG = "4a242424595c638af489fd1b41c94b0d-7985"

DELIVERY_ROOT = "13070004_Models_20250416"
RAS_PREFIX = "Hydraulic Models/RAS_Submittal"
HMS_PREFIX = "Hydrologic Models/HMS Models"
DOCUMENTATION_MEMBERS: Mapping[str, str] = {
    "ReadMe.txt": "ReadMe.txt",
    "Hydraulic Models/ReadMe.txt": "Hydraulic_Models_ReadMe.txt",
    "Hydrologic Models/ReadMe.txt": "Hydrologic_Models_ReadMe.txt",
}

PROJECT_BASENAME = "SLDR_004"
GEOMETRY_NUMBER = "02"
PROJECT_RELATIVE = Path("RAS Model") / "RAS_Submittal" / "Input"
MANIFEST_RELATIVE = Path("agent") / "salt_draw_manifest.json"
MODEL_LOG_RELATIVE = Path("agent") / "model_log.md"
MAX_ORGANIZED_PATH = 240

# Plan number -> delivered plan title, unsteady file, and event.  Verified
# from the delivered SLDR_004.p01..p07 and .u01..u07 text files.
PLAN_EVENTS: Mapping[str, Mapping[str, str]] = {
    "p01": {"title": "SLDR_004_1pct", "flow": "u01", "event": "1% AEP"},
    "p02": {"title": "SLDR_004_0_2pct", "flow": "u02", "event": "0.2% AEP"},
    "p03": {"title": "SLDR_004_10pct", "flow": "u03", "event": "10% AEP"},
    "p04": {"title": "SLDR_004_4pct", "flow": "u04", "event": "4% AEP"},
    "p05": {"title": "SLDR_004_2pct", "flow": "u05", "event": "2% AEP"},
    "p06": {
        "title": "SLDR_004_1plu",
        "flow": "u06",
        "event": "1% AEP plus (upper confidence)",
    },
    "p07": {
        "title": "SLDR_004_1min",
        "flow": "u07",
        "event": "1% AEP minus (lower confidence)",
    },
}
DEFAULT_OUTPUT_PLANS: tuple[str, ...] = ("p01", "p02")

_REQUIRED_RAS_FILES: tuple[str, ...] = (
    "Input/SLDR_004.prj",
    "Input/SLDR_004.rasmap",
    "Input/SLDR_004.g02",
    "Input/SLDR_004.g02.hdf",
    "Input/Projection.prj",
    "Input/Hydrology/LPLWR_001.dss",
    "Input/Hydrology/SLDR_03070004.dss",
    *(f"Input/SLDR_004.{plan}" for plan in PLAN_EVENTS),
    *(f"Input/SLDR_004.{spec['flow']}" for spec in PLAN_EVENTS.values()),
    *(f"Input/SLDR_004.{spec['flow']}.hdf" for spec in PLAN_EVENTS.values()),
    "Terrain/Terrain.hdf",
    "Terrain/Terrain.vrt",
    "Terrain/Terrain.Hydroenforced.hdf",
    "Terrain/Terrain.Hydroenforced.vrt",
    "Terrain/Terrain.salt_draw_mosaic_max.tif",
    "Landcover/LandCover.hdf",
    "Landcover/Mannings.hdf",
    "Landcover/Infiltration.hdf",
    "Landcover/Soils.hdf",
)

# Delivered RASMapper references that point outside the delivery.  None is a
# hydraulic input: two are host basemaps, one is a profile-line display layer,
# and one is a stale event-condition layer for an author-local u01.hdf (the
# delivered .\SLDR_004.u01.hdf is the active one).
NONBLOCKING_RASMAP_REFERENCES: Mapping[str, str] = {
    r"%LocalAppData%\HEC\Mapping\5.1\XML\Google Map.xml": "host_basemap",
    r"%LocalAppData%\HEC\Mapping\5.1\XML\Google Satellite.xml": "host_basemap",
    r"..\..\..\..\..\HECRAS\Features\Profile Lines.shp": "display_only",
    r"..\..\..\..\..\HECRAS\SLDR_004.u01.hdf": "stale_display_layer",
}

KNOWN_NOTES: tuple[str, ...] = (
    (
        "Delivered plan and geometry HDFs were written by HEC-RAS 6.4.1 "
        "(File Version 'HEC-RAS 6.4.1 June 2023')."
    ),
    (
        "Single 2D flow area SLDR_004 (794,234 cells), rain-on-grid. Delivered "
        "results contain water surface and face velocity; Face Flow is not "
        "written."
    ),
    (
        "HEC-RAS 6.6 cannot regenerate the delivered mesh as-is: 48 cells have "
        "more than eight sides. Use GeomMesh.plan_computation_point_repair / "
        "apply_computation_point_repair before regenerating the mesh in 6.6. "
        "The organizer does not modify the mesh."
    ),
    "SLDR_004.prj delivers Current Plan=p07; the organizer leaves it unchanged.",
    (
        "RASMapper result layers for plans whose HDFs were not extracted remain "
        "in SLDR_004.rasmap and resolve only after those HDFs are added."
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_output_plans(output_plans: Iterable[str] | None) -> list[str]:
    """Return sorted canonical plan ids (``pNN``) for result-HDF selection."""
    if output_plans is None:
        return list(DEFAULT_OUTPUT_PLANS)
    if isinstance(output_plans, str):
        output_plans = [output_plans]
    plans: set[str] = set()
    for value in output_plans:
        text = str(value).strip().lower()
        if text.isdigit():
            text = f"p{int(text):02d}"
        if text not in PLAN_EVENTS:
            valid = ", ".join(PLAN_EVENTS)
            raise ValueError(
                f"Unknown Salt Draw plan {value!r}; valid plans: {valid}."
            )
        plans.add(text)
    return sorted(plans)


def _destination_for(relative: str, *, include_hms: bool) -> Path | None:
    """Map a delivery-relative POSIX path to its organized relative path."""
    if relative in DOCUMENTATION_MEMBERS:
        return Path("Documentation") / DOCUMENTATION_MEMBERS[relative]
    ras = RAS_PREFIX + "/"
    if relative.startswith(ras):
        return Path("RAS Model") / "RAS_Submittal" / Path(
            *PurePosixPath(relative[len(ras):]).parts
        )
    hms = HMS_PREFIX + "/"
    if relative.startswith(hms):
        if not include_hms:
            return None
        return Path("HMS Model") / Path(*PurePosixPath(relative[len(hms):]).parts)
    return None


def _plan_hdf_number(relative: str) -> str | None:
    match = re.fullmatch(
        rf"{re.escape(RAS_PREFIX)}/Input/{PROJECT_BASENAME}\.(p\d\d)\.hdf",
        relative,
        flags=re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


@log_call
def select_salt_draw_members(
    member_names: Iterable[str],
    output_plans: Iterable[str] | None = None,
    *,
    include_hms: bool = True,
) -> dict[str, Path]:
    """Select delivery files and map them to organized relative paths.

    Args:
        member_names: File paths from the archive (prefixed with the
            ``13070004_Models_20250416/`` delivery folder) or from an
            extracted tree relative to that folder. Directory entries are
            ignored.
        output_plans: Plan result HDFs to keep (``"p01"``, ``"1"``, ...).
            ``None`` keeps ``DEFAULT_OUTPUT_PLANS``.
        include_hms: Keep the delivered HEC-HMS project.

    Returns:
        Mapping of source name to organized relative destination.
    """
    plans = set(normalize_output_plans(output_plans))
    selected: dict[str, Path] = {}
    for name in member_names:
        normalized = str(name).replace("\\", "/")
        if normalized.endswith("/"):
            continue
        relative = normalized.removeprefix(DELIVERY_ROOT + "/")
        plan = _plan_hdf_number(relative)
        if plan is not None and plan not in plans:
            continue
        destination = _destination_for(relative, include_hms=include_hms)
        if destination is not None:
            selected[str(name)] = destination
    return selected


def _resolve_source(source: Path) -> tuple[str, Path]:
    """Return ``("archive", zip)`` or ``("tree", delivery_root)``."""
    if source.is_file():
        if source.suffix.lower() != ".zip":
            raise ValueError(f"Salt Draw source is not a ZIP archive: {source}")
        return "archive", source
    archive = source / SOURCE_NAME
    if archive.is_file():
        return "archive", archive
    for candidate in (source / DELIVERY_ROOT, source):
        if (candidate / RAS_PREFIX / "Input" / f"{PROJECT_BASENAME}.prj").is_file():
            return "tree", candidate
    raise FileNotFoundError(
        f"Salt Draw source not found under {source}: expected {SOURCE_NAME} "
        f"or an extracted {DELIVERY_ROOT} tree."
    )


def _validate_archive_identity(archive: Path) -> dict[str, Any]:
    from ras_commander.sources.federal.ebfe_models import RasEbfeModels

    identity = RasEbfeModels._validate_source_asset_identity(
        archive,
        expected_size_bytes=SOURCE_SIZE_BYTES,
        expected_etag=SOURCE_ETAG,
    )
    sidecar = RasEbfeModels._source_sidecar_path(archive)
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    if recorded.get("source") not in (None, SOURCE_URL):
        raise RuntimeError(
            "Salt Draw source sidecar URL does not match the FEMA source: "
            f"{recorded.get('source')!r}."
        )
    identity.update({"source_url": SOURCE_URL, "archive_identity_verified": True})
    return identity


def _stage_from_archive(
    archive: Path,
    working: Path,
    plans: Sequence[str],
    include_hms: bool,
) -> dict[str, Any]:
    import zipfile

    from ras_commander.sources.federal.ebfe_models import RasEbfeModels

    with zipfile.ZipFile(archive) as stream:
        names = [info.filename for info in stream.infolist()]
    selection = select_salt_draw_members(names, plans, include_hms=include_hms)
    extraction = working / ".extract"
    audit = RasEbfeModels._extract_zip_verified(
        archive,
        extraction,
        "Salt Draw source archive",
        include_relative_paths=set(selection),
    )
    receipt_path = extraction / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for name, destination in selection.items():
        target = working / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(
            RasEbfeModels._windows_extended_path(
                extraction / Path(*PurePosixPath(name).parts)
            ),
            RasEbfeModels._windows_extended_path(target),
        )
    _keep_empty_directories(names, working, include_hms)
    shutil.rmtree(RasEbfeModels._windows_extended_path(extraction))
    archive_receipt = dict(receipt.get("archive", {}))
    archive_receipt.pop("selected_relative_paths", None)
    return {
        "mode": "archive",
        "crc32_verified": True,
        "selected_files": len(selection),
        "verified_bytes": audit.get("verified_bytes"),
        "archive": archive_receipt,
    }


def _directory_destination(relative: str, *, include_hms: bool) -> Path | None:
    """Map a delivery-relative directory to its organized directory, if kept."""
    child = _destination_for(relative.rstrip("/") + "/_", include_hms=include_hms)
    return None if child is None else child.parent


def _keep_empty_directories(
    names: Iterable[str], working: Path, include_hms: bool
) -> None:
    """Recreate delivered empty HMS/RAS directories (for example basinStates)."""
    for name in names:
        if not name.endswith("/"):
            continue
        relative = name.removeprefix(DELIVERY_ROOT + "/")
        destination = _directory_destination(relative, include_hms=include_hms)
        if destination is not None:
            (working / destination).mkdir(parents=True, exist_ok=True)


def _stage_from_tree(
    root: Path, working: Path, plans: Sequence[str], include_hms: bool
) -> dict[str, Any]:
    names = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    ]
    selection = select_salt_draw_members(names, plans, include_hms=include_hms)
    missing = [
        plan
        for plan in plans
        if f"{RAS_PREFIX}/Input/{PROJECT_BASENAME}.{plan}.hdf" not in selection
    ]
    if missing:
        raise FileNotFoundError(
            "Salt Draw extracted tree lacks the requested result HDF(s) "
            f"{missing}; choose output_plans from the HDFs present or use the "
            f"public {SOURCE_NAME}."
        )
    copied = 0
    for name, destination in selection.items():
        target = working / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / Path(*PurePosixPath(name).parts), target)
        copied += 1
    for directory in root.rglob("*"):
        if directory.is_dir():
            relative = directory.relative_to(root).as_posix()
            destination = _directory_destination(relative, include_hms=include_hms)
            if destination is not None:
                (working / destination).mkdir(parents=True, exist_ok=True)
    return {
        "mode": "pre_extracted_tree",
        "crc32_verified": False,
        "selected_files": copied,
        "path": str(root),
    }


def _assignments(text: str, key: str) -> list[str]:
    """Return every ``key=value`` value from HEC-RAS text, in file order."""
    values = []
    wanted = key.casefold()
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip().casefold() == wanted:
            values.append(value.strip())
    return values


def _assignment(text: str, key: str) -> str | None:
    values = _assignments(text, key)
    return values[0] if values else None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _audit_workspace(output_root: Path, plans: Sequence[str]) -> dict[str, Any]:
    """Check the active hydraulic file set and every RAS-side reference."""
    submittal = output_root / "RAS Model" / "RAS_Submittal"
    project = submittal / "Input"
    errors: list[str] = []
    missing = [rel for rel in _REQUIRED_RAS_FILES if not (submittal / rel).is_file()]
    missing.extend(
        f"Input/{PROJECT_BASENAME}.{plan}.hdf"
        for plan in plans
        if not (project / f"{PROJECT_BASENAME}.{plan}.hdf").is_file()
    )
    if missing:
        errors.append(f"missing delivered files: {missing}")
        return {"active_hydraulic_reference_closure": False, "errors": errors}

    for plan, spec in PLAN_EVENTS.items():
        text = _read_text(project / f"{PROJECT_BASENAME}.{plan}")
        if _assignment(text, "Plan Title") != spec["title"]:
            errors.append(f"{plan} title is not {spec['title']}")
        if _assignment(text, "Geom File") != f"g{GEOMETRY_NUMBER}":
            errors.append(f"{plan} does not bind g{GEOMETRY_NUMBER}")
        if _assignment(text, "Flow File") != spec["flow"]:
            errors.append(f"{plan} does not bind {spec['flow']}")

    dss_checked = 0
    for spec in PLAN_EVENTS.values():
        text = _read_text(project / f"{PROJECT_BASENAME}.{spec['flow']}")
        values = _assignments(text, "DSS File") + [
            line.rsplit("=", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("Met BC=") and "|TS DSS Filename=" in line
        ]
        for value in values:
            if not value or value.casefold() == "dss":
                continue
            dss_checked += 1
            target = project / PureWindowsPath(value)
            if not target.is_file():
                errors.append(f"{spec['flow']} DSS reference unresolved: {value}")

    rasmap = _read_text(project / f"{PROJECT_BASENAME}.rasmap")
    references = sorted(
        set(re.findall(r'(?:Filename|GeometryHDF)="([^"]+)"', rasmap))
    )
    unresolved: list[dict[str, str]] = []
    not_extracted: list[str] = []
    excluded = {
        f".\\{PROJECT_BASENAME}.{plan}.hdf".casefold()
        for plan in PLAN_EVENTS
        if plan not in plans
    }
    for value in references:
        if value in NONBLOCKING_RASMAP_REFERENCES:
            unresolved.append(
                {
                    "reference": value,
                    "classification": NONBLOCKING_RASMAP_REFERENCES[value],
                }
            )
            continue
        if value.casefold() in excluded:
            not_extracted.append(value)
            continue
        if not (project / PureWindowsPath(value)).is_file():
            errors.append(f"RASMapper reference unresolved: {value}")

    too_long = [
        str(path)
        for path in output_root.rglob("*")
        if path.is_file() and len(str(path)) > MAX_ORGANIZED_PATH
    ]
    if too_long:
        errors.append(
            f"organized paths exceed {MAX_ORGANIZED_PATH} characters: {too_long[:3]}"
        )
    return {
        "active_hydraulic_reference_closure": not errors,
        "plans_checked": len(PLAN_EVENTS),
        "dss_references_checked": dss_checked,
        "rasmap_references_checked": len(references),
        "nonblocking_unresolved_references": unresolved,
        "result_layers_not_extracted": sorted(set(not_extracted)),
        "errors": errors,
    }


def _inventory(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in ("RAS Model", "HMS Model", "Documentation"):
        folder = output_root / scope
        if not folder.is_dir():
            continue
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            rows.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "size_bytes": path.stat().st_size,
                }
            )
    return rows


@log_call
def salt_draw_is_reusable(
    output_folder: str | Path,
    output_plans: Iterable[str] | None = None,
) -> bool:
    """Return whether an organized Salt Draw tree still matches its manifest.

    ``output_plans=None`` accepts any recorded plan selection; otherwise the
    recorded selection must match exactly.
    """
    output = Path(output_folder)
    try:
        manifest = json.loads((output / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or manifest.get("huc8") != "13070004":
            return False
        recorded = list(manifest.get("output_plans", []))
        if output_plans is not None and recorded != normalize_output_plans(
            output_plans
        ):
            return False
        if _inventory(output) != manifest.get("organized_inventory"):
            return False
        audit = _audit_workspace(output, recorded)
        return bool(audit["active_hydraulic_reference_closure"])
    except (KeyError, OSError, TypeError, ValueError):
        return False


@log_call
def organize_salt_draw(
    source: str | Path,
    output_folder: str | Path,
    *,
    output_plans: Iterable[str] | None = None,
    include_hms: bool = True,
) -> Path:
    """Organize the Salt Draw delivery into a HEC-RAS-openable project tree.

    Args:
        source: The public ``13070004_Models.zip``, a folder containing it,
            or an already-extracted delivery (the ``13070004_Models_20250416``
            folder or its parent).
        output_folder: Organized destination. It must not exist unless it is
            a reusable organization with the same ``output_plans``.
        output_plans: Plan result HDFs to extract; see ``PLAN_EVENTS``.
            Defaults to ``("p01", "p02")``.
        include_hms: Copy the delivered HEC-HMS project to ``HMS Model``.

    Returns:
        The organized folder. The HEC-RAS project is
        ``RAS Model/RAS_Submittal/Input/SLDR_004.prj``.
    """
    plans = normalize_output_plans(output_plans)
    mode, resolved = _resolve_source(Path(source).resolve())
    output = Path(output_folder).resolve()
    if output.exists():
        if salt_draw_is_reusable(output, plans):
            return output
        raise FileExistsError(
            f"Salt Draw output exists but is not reusable with output_plans="
            f"{plans}: {output}. Preserve it for audit or choose another folder."
        )
    if output == resolved or resolved in output.parents:
        raise ValueError("Salt Draw output must not be inside the source delivery.")

    identity: dict[str, Any]
    if mode == "archive":
        identity = _validate_archive_identity(resolved)
        snapshot = (resolved.stat().st_size, resolved.stat().st_mtime_ns)
    else:
        identity = {
            "path": str(resolved),
            "mode": "pre_extracted_tree",
            "archive_identity_verified": False,
        }
        snapshot = None

    output.parent.mkdir(parents=True, exist_ok=True)
    working = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.assembling-", dir=output.parent)
    )
    try:
        if mode == "archive":
            staging = _stage_from_archive(resolved, working, plans, include_hms)
        else:
            staging = _stage_from_tree(resolved, working, plans, include_hms)
        (working / "agent").mkdir(exist_ok=True)
        (working / "Documentation").mkdir(exist_ok=True)
        (working / "Spatial Data").mkdir(exist_ok=True)

        audit = _audit_workspace(working, plans)
        if not audit["active_hydraulic_reference_closure"]:
            raise RuntimeError(
                f"Salt Draw reference audit failed: {audit['errors']}"
            )
        manifest = {
            "schema_version": 1,
            "study": "Salt Draw",
            "huc8": "13070004",
            "source_program": "fema_ebfe",
            "lane_kind": "integrated_2d",
            "delivered_ras_version": "6.4.1",
            "source_identity": identity,
            "staging": staging,
            "project_count": 1,
            "project_file": (PROJECT_RELATIVE / f"{PROJECT_BASENAME}.prj").as_posix(),
            "geometry": f"g{GEOMETRY_NUMBER}",
            "plan_events": {plan: dict(spec) for plan, spec in PLAN_EVENTS.items()},
            "output_plans": plans,
            "include_hms": include_hms,
            "repair_summary": {
                "text_updates": 0,
                "hdf_updates": 0,
                "layout": "delivered RAS_Submittal layout preserved",
            },
            "reference_audit": audit,
            "terrain_required": True,
            "terrain_source_complete": True,
            "land_cover_source_complete": True,
            "notes": list(KNOWN_NOTES),
            "required_validation_level": "unsteady_start",
            "validation_status": "pending",
            "hec_ras_executed": False,
            "source_objects_immutable": True,
            "completed_utc": _utc_now(),
        }
        plan_lines = "\n".join(
            f"- `{plan}` {spec['title']} ({spec['event']}, {spec['flow']})"
            + (" - result HDF extracted" if plan in plans else "")
            for plan, spec in PLAN_EVENTS.items()
        )
        (working / MODEL_LOG_RELATIVE).write_text(
            "# Salt Draw (13070004) organization log\n\n"
            f"Source: {identity.get('path')} ({staging['mode']}).\n\n"
            "One HEC-RAS 6.4.1 2D project, `RAS Model/RAS_Submittal/Input/"
            "SLDR_004.prj`, geometry `g02`. The delivered RAS_Submittal "
            "layout is preserved, so terrain, land cover, and DSS references "
            "resolve without repair.\n\n"
            f"Plans:\n{plan_lines}\n\n"
            + "\n".join(f"- {note}" for note in KNOWN_NOTES)
            + "\n\nNo HEC-RAS execution is claimed by this organization.\n",
            encoding="utf-8",
        )
        manifest["organized_inventory"] = _inventory(working)
        (working / MANIFEST_RELATIVE).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if snapshot is not None and snapshot != (
            resolved.stat().st_size,
            resolved.stat().st_mtime_ns,
        ):
            raise RuntimeError("Salt Draw source archive changed during organization.")
        release_native_sessions(working, output)
        os.replace(working, output)
    except Exception:
        if working.exists():
            release_native_sessions(working)
            shutil.rmtree(working, ignore_errors=True)
        raise
    return output
