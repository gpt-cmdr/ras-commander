"""Fail-closed organizer for FEMA eBFE study 12100302 (Medina).

The published ZIP is complete through 407 recoverable files and then ends in
the compressed data for one supplied *result* HDF.  This module deliberately
uses :class:`~ras_commander.sources.federal.ebfe_extract.StreamingZipReader`:
the standard library cannot open the missing central directory, while silently
ignoring the short tail would make a different damaged download look valid.

The delivery contains five HEC-RAS 6.4.1 2D projects.  Four include the exact
modified terrain HDF used by the model.  ``UpperMedinaHeadwaters`` does not;
its RASMapper file references the load-bearing modification group
``UpperMedinaHW_TerrainModifications`` in ``Terrain.hdf``.  Its delivered land
cover, infiltration, and soils inputs are present and are not deficiencies.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ras_commander.LoggingConfig import get_logger, log_call
from ras_commander.sources.federal.ebfe_extract import StreamingZipReader

logger = get_logger(__name__)

SOURCE_URL = "https://ebfedata.s3.amazonaws.com/12100302_Medina/12100302_Models.zip"
SOURCE_SIZE_BYTES = 52_085_665_792
SOURCE_ETAG = "5474dc597ff3a2fb4418a59807a439ff-6210"
SOURCE_NAME = "12100302_Models.zip"
EXPECTED_RECOVERABLE_FILES = 407
ALLOWED_UNRECOVERABLE_MEMBER = (
    "Engineering Models/Hydraulic Models/UpperMedinaHeadwaters/Output/"
    "UpperMedinaHW.p01.hdf"
)

_HYDRAULIC_PREFIX = PurePosixPath("Engineering Models/Hydraulic Models")
_MANIFEST_RELATIVE = Path("agent") / "medina_manifest.json"

# Project folder, project basename, active geometry, active modified terrain.
# ``None`` means the source input is missing, not that terrain is unnecessary.
PROJECTS: Mapping[str, Mapping[str, str | None]] = {
    "Leon1": {
        "basename": "Leon1",
        "plan_number": "01",
        "geometry_number": "01",
        "unsteady_number": "01",
        "geometry_hdf": "Leon1.g01.hdf",
        "terrain_hdf": "Terrain (1).hdf",
        "terrain_modification": "Channels",
    },
    "Leon2": {
        "basename": "Leon2",
        "plan_number": "03",
        "geometry_number": "01",
        "unsteady_number": "01",
        "geometry_hdf": "Leon2.g01.hdf",
        "terrain_hdf": "Terrain (1).hdf",
        "terrain_modification": "Channels",
    },
    "Leon3": {
        "basename": "Leon3",
        "plan_number": "02",
        "geometry_number": "01",
        "unsteady_number": "01",
        "geometry_hdf": "Leon3.g01.hdf",
        "terrain_hdf": "Terrain (1).hdf",
        "terrain_modification": "Channels",
    },
    "MiddleLowerMedina": {
        "basename": "MLM",
        "plan_number": "03",
        "geometry_number": "01",
        "unsteady_number": "01",
        "geometry_hdf": "MLM.g01.hdf",
        "terrain_hdf": "Terrain_Clipped.hdf",
        "terrain_modification": "Channels",
    },
    "UpperMedinaHeadwaters": {
        "basename": "UpperMedinaHW",
        "plan_number": "04",
        "geometry_number": "02",
        "unsteady_number": "04",
        "geometry_hdf": "UpperMedinaHW.g02.hdf",
        "terrain_hdf": None,
        "terrain_modification": "UpperMedinaHW_TerrainModifications",
    },
}

_PROJECTION_REPAIRS = {
    "Leon2": (
        r"..\Shapefiles\Leon_Perimeter.prj",
        r".\Projection\Leon2_Projection.prj",
        "Leon3",
    ),
    "Leon3": (
        r".\Projection\Projection_File.prj",
        r".\Projection\Leon3_Projection.prj",
        "Leon3",
    ),
    "MiddleLowerMedina": (
        r".\Projection\Projection_File.prj",
        r".\Projection\MLM_Projection.prj",
        "MiddleLowerMedina",
    ),
    "UpperMedinaHeadwaters": (
        r".\Projection\UpperMedina_Projection_4204.prj",
        r".\Projection\UpperMedinaHW_Projection.prj",
        "Leon3",
    ),
}

__all__ = [
    "ALLOWED_UNRECOVERABLE_MEMBER",
    "EXPECTED_RECOVERABLE_FILES",
    "PROJECTS",
    "SOURCE_ETAG",
    "SOURCE_NAME",
    "SOURCE_SIZE_BYTES",
    "SOURCE_URL",
    "medina_is_reusable",
    "organize_medina",
]


def _source_sidecar(source: Path) -> Path:
    return Path(f"{source}.ebfe-source.json")


def _validate_source_identity(source: Path, etag: str | None) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"Medina source archive not found: {source}")
    stat = source.stat()
    if stat.st_size != SOURCE_SIZE_BYTES:
        raise RuntimeError(
            "Medina source size mismatch: "
            f"expected {SOURCE_SIZE_BYTES}, found {stat.st_size}."
        )

    sidecar = _source_sidecar(source)
    record: dict[str, Any] = {}
    if sidecar.is_file():
        try:
            record = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"Invalid Medina source sidecar: {sidecar}") from exc
        if record.get("size") != SOURCE_SIZE_BYTES:
            raise RuntimeError(
                "Medina source sidecar size does not match the pinned source."
            )
        if record.get("etag") != SOURCE_ETAG:
            raise RuntimeError(
                "Medina source sidecar ETag does not match the pinned source."
            )
        if record.get("source") != SOURCE_URL:
            raise RuntimeError(
                "Medina source sidecar URL does not match the pinned source."
            )
    elif etag is None:
        raise RuntimeError(
            "Medina source identity requires its .ebfe-source.json sidecar or an "
            "explicit pinned ETag."
        )

    effective_etag = etag if etag is not None else record.get("etag")
    if effective_etag != SOURCE_ETAG:
        raise RuntimeError("Medina source ETag does not match the pinned source.")
    return {
        "name": source.name,
        "url": SOURCE_URL,
        "size_bytes": stat.st_size,
        "etag": effective_etag,
        "mtime_ns": stat.st_mtime_ns,
        "sidecar": str(sidecar) if sidecar.is_file() else None,
    }


def _safe_parts(member_name: str) -> tuple[str, ...]:
    normalized = member_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if member.is_absolute() or not member.parts:
        raise RuntimeError(f"Unsafe Medina archive member: {member_name!r}")
    if any(part in {"", ".", ".."} for part in member.parts):
        raise RuntimeError(f"Unsafe Medina archive member: {member_name!r}")
    if any(":" in part for part in member.parts):
        raise RuntimeError(f"Unsafe Medina archive member: {member_name!r}")
    return tuple(member.parts)


def _member_destination(member_name: str, working: Path) -> Path:
    parts = _safe_parts(member_name)
    prefix = _HYDRAULIC_PREFIX.parts
    if parts[: len(prefix)] != prefix:
        raise RuntimeError(f"Unexpected Medina archive member: {member_name}")
    relative = parts[len(prefix) :]
    if relative == ("2D_Model_Inventory_Medina.xlsx",):
        return working / "Documentation" / relative[0]
    if len(relative) < 3 or relative[0] not in PROJECTS:
        raise RuntimeError(f"Unexpected Medina archive layout: {member_name}")

    project, section, *tail = relative
    if section not in {"Input", "Output", "Terrain", "Land Classification"}:
        raise RuntimeError(f"Unexpected Medina project section: {member_name}")
    if not tail:
        raise RuntimeError(f"Medina archive member has no filename: {member_name}")
    project_root = working / "RAS Model" / project
    if section in {"Input", "Output"}:
        return project_root.joinpath(*tail)
    return project_root / section / Path(*tail)


def _preflight_destinations(survey: Any, working: Path) -> dict[str, Path]:
    destinations: dict[str, Path] = {}
    casefolded: dict[str, str] = {}
    for member in survey.members:
        if member.is_dir:
            continue
        destination = _member_destination(member.name, working)
        key = str(destination.relative_to(working)).replace("\\", "/").casefold()
        previous = casefolded.get(key)
        if previous is not None:
            raise RuntimeError(
                "Medina archive has a case-insensitive destination collision: "
                f"{previous!r} and {member.name!r}."
            )
        casefolded[key] = member.name
        destinations[member.name] = destination
    return destinations


def _replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Medina repair pre-state conflict in {path.name}: expected one "
            f"occurrence of {old!r}, found {count}."
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _path_equivalent(actual: Any, expected: str) -> bool:
    if isinstance(actual, bytes):
        actual = actual.decode("utf-8", errors="strict")
    text = str(actual).strip().replace("/", "\\")
    text = re.sub(r"\\+", r"\\", text)
    while text.startswith(".\\"):
        text = text[2:]
    wanted = expected.replace("/", "\\")
    while wanted.startswith(".\\"):
        wanted = wanted[2:]
    return text.casefold() == wanted.casefold()


def _write_fixed_attribute(group: Any, name: str, value: str) -> bool:
    """Create/normalize one path attribute; reject non-equivalent pre-state."""
    current = group.attrs.get(name)
    if (
        current is not None
        and str(current).strip()
        and not _path_equivalent(current, value)
    ):
        raise RuntimeError(
            f"Medina HDF pre-state conflict at {group.name}@{name}: "
            f"found {current!r}, expected {value!r}."
        )
    encoded = value.encode("utf-8")
    if current is not None:
        try:
            if (
                _path_equivalent(current, value)
                and group.attrs.get_id(name).dtype.kind == "S"
            ):
                return False
        except (KeyError, TypeError, ValueError):
            pass
        del group.attrs[name]
    group.attrs.create(name, encoded, dtype=f"S{len(encoded)}")
    return True


def _repair_geometry_associations(project_root: Path, spec: Mapping[str, Any]) -> int:
    """Repair only the active geometry HDF, not delivered result HDFs."""
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - core dependency
        raise RuntimeError("h5py is required to organize Medina") from exc

    geometry = project_root / str(spec["geometry_hdf"])
    if not geometry.is_file():
        raise RuntimeError(f"Medina active geometry HDF is missing: {geometry}")
    updates = 0
    with h5py.File(geometry, "r+") as hdf:
        if "Geometry" not in hdf or "Geometry/2D Flow Areas" not in hdf:
            raise RuntimeError(f"{geometry.name} lacks its 2D geometry groups.")
        areas = hdf["Geometry/2D Flow Areas"]
        area_groups = [
            value for value in areas.values() if isinstance(value, h5py.Group)
        ]
        if len(area_groups) != 1:
            raise RuntimeError(
                f"{geometry.name} must contain exactly one 2D Flow Area; "
                f"found {len(area_groups)} area group(s)."
            )
        # The parent also contains supporting datasets; only the named child
        # group represents the actual 2D Flow Area.
        area = area_groups[0]
        for group in (hdf["Geometry"], area):
            updates += _write_fixed_attribute(
                group,
                "Infiltration Filename",
                r".\Land Classification\Infiltration.hdf",
            )
            updates += _write_fixed_attribute(
                group,
                "Land Cover Filename",
                r".\Land Classification\LandCover.hdf",
            )
            if spec["terrain_hdf"] is not None:
                updates += _write_fixed_attribute(
                    group,
                    "Terrain Filename",
                    f".\\Terrain\\{spec['terrain_hdf']}",
                )
        if "Infiltration" not in area:
            raise RuntimeError(f"{geometry.name} lacks its Infiltration group.")
        updates += _write_fixed_attribute(
            area["Infiltration"],
            "Infiltration Filename",
            r".\Land Classification\Infiltration.hdf",
        )
    return updates


def _validate_project_assets(project_root: Path, spec: Mapping[str, Any]) -> None:
    basename = str(spec["basename"])
    for relative in (
        f"{basename}.prj",
        f"{basename}.rasmap",
        f"{basename}.p{spec['plan_number']}",
        f"{basename}.g{spec['geometry_number']}",
        f"{basename}.u{spec['unsteady_number']}",
        str(spec["geometry_hdf"]),
        "Land Classification/Infiltration.hdf",
        "Land Classification/Soils.hdf",
        "Land Classification/LandCover.hdf",
    ):
        if not (project_root / relative).is_file():
            raise RuntimeError(
                f"Medina delivered project asset is missing: {project_root / relative}"
            )
    terrain_name = spec["terrain_hdf"]
    if terrain_name is not None:
        terrain = project_root / "Terrain" / str(terrain_name)
        if not terrain.is_file():
            raise RuntimeError(f"Medina compiled terrain is missing: {terrain}")
        try:
            import h5py

            with h5py.File(terrain, "r") as hdf:
                modification = str(spec["terrain_modification"])
                if f"Modifications/{modification}" not in hdf:
                    raise RuntimeError(
                        f"{terrain.name} lacks delivered modification {modification!r}."
                    )
        except OSError as exc:
            raise RuntimeError(f"Unreadable Medina terrain HDF: {terrain}") from exc


def _repair_projects(working: Path) -> dict[str, Any]:
    roots = {name: working / "RAS Model" / name for name in PROJECTS}

    # Reuse only the delivered CRS definition.  Leon3 and MLM include identical
    # Projection_File.prj payloads; the other rasmap paths name the same Texas
    # South Central 4204 projection but point outside the delivery.
    projection_sources = {
        "Leon3": roots["Leon3"] / "Terrain" / "Projection" / "Projection_File.prj",
        "MiddleLowerMedina": (
            roots["MiddleLowerMedina"]
            / "Terrain"
            / "Projection"
            / "Projection_File.prj"
        ),
    }
    if not all(path.is_file() for path in projection_sources.values()):
        raise RuntimeError("Medina delivered projection evidence is incomplete.")
    if (
        projection_sources["Leon3"].read_bytes()
        != projection_sources["MiddleLowerMedina"].read_bytes()
    ):
        raise RuntimeError("Medina delivered projection definitions disagree.")

    for project, (old, new, source_project) in _PROJECTION_REPAIRS.items():
        destination = roots[project] / Path(new.replace(".\\", "").replace("\\", "/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(projection_sources[source_project], destination)
        basename = str(PROJECTS[project]["basename"])
        _replace_exact(roots[project] / f"{basename}.rasmap", old, new)

    _replace_exact(
        roots["Leon1"] / "Leon1.u02",
        r"..\..\..\_HMS_Models_v2\_HMS_Models\Leon1\500YR.dss",
        r".\DSS\500YR.dss",
    )

    project_manifest: dict[str, Any] = {}
    total_hdf_updates = 0
    for project, spec in PROJECTS.items():
        root = roots[project]
        _validate_project_assets(root, spec)
        updates = _repair_geometry_associations(root, spec)
        total_hdf_updates += updates
        terrain_complete = spec["terrain_hdf"] is not None
        project_manifest[project] = {
            "basename": spec["basename"],
            "project_file": str(
                Path("RAS Model") / project / f"{spec['basename']}.prj"
            ).replace("\\", "/"),
            "geometry_hdf": spec["geometry_hdf"],
            "canonical_plan_contract": {
                "plan": spec["plan_number"],
                "geometry": spec["geometry_number"],
                "unsteady": spec["unsteady_number"],
            },
            "terrain_required": True,
            "terrain_source_complete": terrain_complete,
            "terrain_hdf": spec["terrain_hdf"],
            "terrain_modification": spec["terrain_modification"],
            "land_cover_delivered": True,
            "infiltration_delivered": True,
            "soils_delivered": True,
            "required_validation_level": "unsteady_start",
            "validation_status": (
                "pending" if terrain_complete else "blocked_source_gap"
            ),
            "delivery_readiness": (
                "pending_runtime_validation"
                if terrain_complete
                else "critical_source_gap"
            ),
            "hec_ras_executed": False,
            "downstream_usable": False,
            "reproducible": False,
            "geometry_hdf_association_updates": updates,
        }
    return {
        "projects": project_manifest,
        "geometry_hdf_association_updates": total_hdf_updates,
        "projection_repairs": len(_PROJECTION_REPAIRS),
        "dss_repairs": 1,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _association_paths_are_valid(project_root: Path, spec: Mapping[str, Any]) -> bool:
    try:
        import h5py

        geometry = project_root / str(spec["geometry_hdf"])
        with h5py.File(geometry, "r") as hdf:
            areas = hdf["Geometry/2D Flow Areas"]
            area_groups = [
                value for value in areas.values() if isinstance(value, h5py.Group)
            ]
            if len(area_groups) != 1:
                return False
            area = area_groups[0]
            checks = [
                (
                    hdf["Geometry"],
                    "Infiltration Filename",
                    r".\Land Classification\Infiltration.hdf",
                ),
                (
                    hdf["Geometry"],
                    "Land Cover Filename",
                    r".\Land Classification\LandCover.hdf",
                ),
                (
                    area,
                    "Infiltration Filename",
                    r".\Land Classification\Infiltration.hdf",
                ),
                (area, "Land Cover Filename", r".\Land Classification\LandCover.hdf"),
                (
                    area["Infiltration"],
                    "Infiltration Filename",
                    r".\Land Classification\Infiltration.hdf",
                ),
            ]
            if spec["terrain_hdf"] is not None:
                terrain = f".\\Terrain\\{spec['terrain_hdf']}"
                checks.extend(
                    [
                        (hdf["Geometry"], "Terrain Filename", terrain),
                        (area, "Terrain Filename", terrain),
                    ]
                )
            for group, attribute, expected in checks:
                value = group.attrs.get(attribute)
                if value is None or not _path_equivalent(value, expected):
                    return False
                if group.attrs.get_id(attribute).dtype.kind != "S":
                    return False
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


@log_call
def medina_is_reusable(
    output_folder: str | Path,
    source_archive: str | Path | None = None,
) -> bool:
    """Return whether an organized Medina tree still satisfies its contract."""
    output = Path(output_folder)
    manifest_path = output / _MANIFEST_RELATIVE
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != 1
            or manifest.get("study_key") != "12100302"
        ):
            return False
        if set(manifest.get("projects", {})) != set(PROJECTS):
            return False
        if source_archive is not None:
            recorded = manifest.get("source_asset", {})
            identity = _validate_source_identity(
                Path(source_archive), etag=recorded.get("etag")
            )
            if any(
                recorded.get(key) != identity.get(key)
                for key in ("url", "size_bytes", "etag", "mtime_ns")
            ):
                return False
        for project, spec in PROJECTS.items():
            root = output / "RAS Model" / project
            _validate_project_assets(root, spec)
            if not _association_paths_are_valid(root, spec):
                return False
        leon = (output / "RAS Model" / "Leon1" / "Leon1.u02").read_text(
            encoding="utf-8-sig"
        )
        if r".\DSS\500YR.dss" not in leon:
            return False
        for project, (_, new, _) in _PROJECTION_REPAIRS.items():
            basename = str(PROJECTS[project]["basename"])
            text = (output / "RAS Model" / project / f"{basename}.rasmap").read_text(
                encoding="utf-8-sig"
            )
            if new not in text:
                return False
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


@log_call
def organize_medina(
    source_archive: str | Path,
    output_folder: str | Path,
    *,
    etag: str | None = None,
) -> Path:
    """CRC-extract, repair, audit, and atomically stage Medina's five projects.

    The source archive is read-only.  An existing valid output is reused; an
    existing invalid or partial output is refused rather than overwritten.
    Fresh organization never claims a HEC-RAS run occurred.
    """
    source = Path(source_archive).resolve()
    output = Path(output_folder).resolve()
    identity = _validate_source_identity(source, etag)
    source_state = (source.stat().st_size, source.stat().st_mtime_ns)

    if output.exists():
        if medina_is_reusable(output, source_archive=source):
            return output
        raise FileExistsError(
            f"Medina output exists but is not safely reusable: {output}"
        )
    if source == output or output in source.parents:
        raise ValueError("Medina output must not overlap the source archive.")

    output.parent.mkdir(parents=True, exist_ok=True)
    working = output.with_name(f".{output.name}.medina-{uuid.uuid4().hex}.tmp")
    if working.exists():  # practically impossible, but never inherit debris
        raise FileExistsError(f"Medina temporary build already exists: {working}")
    working.mkdir()

    try:
        reader = StreamingZipReader(source)
        survey = reader.probe()
        truncated = {member.name for member in survey.truncated_members}
        if not survey.truncated or truncated != {ALLOWED_UNRECOVERABLE_MEMBER}:
            raise RuntimeError(
                "Medina archive truncation contract changed; expected only "
                f"{ALLOWED_UNRECOVERABLE_MEMBER!r}, found {sorted(truncated)!r}."
            )
        destinations = _preflight_destinations(survey, working)

        def sink_factory(member: Any) -> BinaryIO:
            destination = destinations[member.name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            return destination.open("xb")

        list(reader.walk(sink_factory=sink_factory, survey=survey))
        failures = {(name, kind) for name, kind, _ in reader.stats.failures}
        expected_failures = {(ALLOWED_UNRECOVERABLE_MEMBER, "truncated")}
        if failures != expected_failures:
            raise RuntimeError(
                f"Medina extraction had unapproved failures: {reader.stats.failures!r}."
            )
        if reader.stats.crc_fail or reader.stats.size_mismatch:
            raise RuntimeError("Medina extraction failed CRC/size verification.")
        if reader.stats.extracted != EXPECTED_RECOVERABLE_FILES:
            raise RuntimeError(
                "Medina recoverable member count changed: expected "
                f"{EXPECTED_RECOVERABLE_FILES}, extracted {reader.stats.extracted}."
            )

        repairs = _repair_projects(working)
        manifest = {
            "schema_version": 1,
            "study_key": "12100302",
            "name": "Medina",
            "source_program": "fema_ebfe",
            "source_asset": identity,
            "archive": {
                "reader": "StreamingZipReader",
                "recoverable_files": reader.stats.extracted,
                "crc_verified_files": reader.stats.crc_ok,
                "crc_failures": reader.stats.crc_fail,
                "size_mismatches": reader.stats.size_mismatch,
                "source_truncated": True,
                "overrun_bytes": survey.overrun_bytes,
                "allowed_unrecoverable_members": [ALLOWED_UNRECOVERABLE_MEMBER],
            },
            "project_count": 5,
            "projects": repairs["projects"],
            "repair_summary": {
                "output_assets_relocated_by_projection": 68,
                "projection_paths": repairs["projection_repairs"],
                "dss_paths": repairs["dss_repairs"],
                "active_geometry_hdf_associations": repairs[
                    "geometry_hdf_association_updates"
                ],
                "delivered_result_hdfs_modified": 0,
            },
            "terrain_required": True,
            "terrain_source_complete": False,
            "delivery_readiness": "critical_source_gap",
            "critical_deficiencies": [
                {
                    "project": "UpperMedinaHeadwaters",
                    "asset": r".\Terrain\Terrain.hdf",
                    "reason": (
                        "The RASMapper geometry references the load-bearing "
                        "UpperMedinaHW_TerrainModifications group, but the compiled "
                        "modified Terrain.hdf is not in the public delivery."
                    ),
                }
            ],
            "required_validation_level": "unsteady_start",
            "validation_status": "blocked_source_gap",
            "hec_ras_executed": False,
            "fresh_output_status": "pending",
            "downstream_usable": False,
            "reproducible": False,
            "source_objects_immutable": True,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        _write_json_atomic(working / _MANIFEST_RELATIVE, manifest)
        (working / "agent" / "model_log.md").write_text(
            "# Medina (12100302) organization log\n\n"
            "Five HEC-RAS 6.4.1 2D projects were recovered with member CRC-32 "
            "verification. The publisher-truncated UpperMedinaHW.p01.hdf is a "
            "supplied result and is retained as a source-delivery deficiency. "
            "Land cover, infiltration, and soils are delivered for all five "
            "projects. Leon1, Leon2, Leon3, and MiddleLowerMedina include their "
            "compiled modified terrains and await unsteady-start validation. "
            "UpperMedinaHeadwaters is blocked because its load-bearing modified "
            "Terrain.hdf was not delivered. No HEC-RAS execution is claimed by "
            "this organization receipt.\n",
            encoding="utf-8",
        )

        if (source.stat().st_size, source.stat().st_mtime_ns) != source_state:
            raise RuntimeError("Medina source archive changed during organization.")
        os.rename(working, output)
    except Exception:
        if working.exists():
            shutil.rmtree(working)
        raise
    return output
