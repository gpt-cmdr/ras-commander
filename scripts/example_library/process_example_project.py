#!/usr/bin/env python
"""Inspect, extract, and package one configured Example Library project.

The processor is intentionally bounded to one explicit project root. It never
searches parent folders, publishes artifacts, or runs a HEC-RAS computation.
Extraction and packaging are delegated to ``ras2cng`` with argument vectors.

Minimal JSON configuration::

    {
      "schema": "rascommander.example-project-processor/v1",
      "source": {"id": "hec-ras-7.0-examples", "version": "7.0"},
      "project": {
        "id": "muncie",
        "title": "Muncie",
        "project_file": "Muncie.prj",
        "primary_geometry": "g04"
      },
      "output_root": "working/example-library/muncie"
    }

Paths in the configuration are resolved relative to the configuration file,
except project files and geometry HDF overrides, which are resolved beneath
``--project-root``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping, MutableMapping, Sequence
from urllib.parse import urlsplit


CONFIG_SCHEMA = "rascommander.example-project-processor/v1"
STATUS_SCHEMA = "rascommander.example-project-processor-status/v1"
PROJECT_SCHEMA = "rascommander.example-project/v1"
MODES = ("inspect", "extract", "package", "all")
ALLOWED_RAS2CNG_COMMANDS = {
    "inspect",
    "archive",
    "map",
    "maplibre",
    "maplibre-import-stored-maps",
    "maplibre-terrain",
}
LOCAL_ONLY_MANIFEST_KEYS = {
    "archive_path",
    "hdf_path",
    "project_dir",
    "project_root",
    "rasmap_path",
    "source_path",
}
PUBLIC_SOURCE_KEYS = {
    "id",
    "title",
    "version",
    "url",
    "license",
    "license_url",
    "publisher",
}
DEFAULT_MAP_TYPES = (
    "wse",
    "depth",
    "velocity",
    "froude",
    "shear_stress",
    "depth_x_velocity",
    "depth_x_velocity_sq",
    "inundation_boundary",
    "arrival_time",
    "duration",
    "percent_inundated",
)
MAP_TYPE_FLAGS = {
    "froude": "--froude",
    "shear_stress": "--shear-stress",
    "depth_x_velocity": "--dv",
    "depth_x_velocity_sq": "--dv-sq",
    "inundation_boundary": "--inundation-boundary",
    "arrival_time": "--arrival-time",
    "duration": "--duration",
    "percent_inundated": "--percent-inundated",
}


class ProcessorError(RuntimeError):
    """Raised when a project cannot be processed without violating policy."""


@dataclass(frozen=True)
class ProjectContext:
    config_path: Path
    config: dict[str, Any]
    project_root: Path
    project_file: Path
    output_root: Path
    archive_dir: Path
    maps_dir: Path
    viewer_dir: Path
    status_path: Path
    ras2cng: str


Runner = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], str]


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Write JSON through a same-directory temporary file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProcessorError(f"Could not read {label} JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProcessorError(f"{label} must contain a JSON object: {path}")
    return value


def load_config(path: Path) -> dict[str, Any]:
    """Load and minimally validate a processor configuration."""

    config = _read_json_object(path, label="configuration")
    schema = config.get("schema")
    if schema is not None and schema != CONFIG_SCHEMA:
        raise ProcessorError(f"Unsupported configuration schema: {schema!r}")
    for key in ("source", "project"):
        if not isinstance(config.get(key), dict):
            raise ProcessorError(f"Configuration field {key!r} must be an object")
    if not str(config["source"].get("id") or "").strip():
        raise ProcessorError("Configuration source.id is required")
    if not str(config["project"].get("id") or "").strip():
        raise ProcessorError("Configuration project.id is required")
    if not config.get("output_root"):
        raise ProcessorError("Configuration output_root is required")
    return config


def _resolve_config_path(config_path: Path, raw_path: str | os.PathLike[str]) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _resolve_project_file(project_root: Path, project: Mapping[str, Any]) -> Path:
    """Resolve one project file using only the explicit root's direct children."""

    root = project_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ProcessorError(f"Project root is not a directory: {root}")

    configured = project.get("project_file")
    if configured:
        candidate = (root / Path(str(configured))).resolve(strict=False)
        if candidate.parent != root:
            raise ProcessorError("project.project_file must be a direct child of --project-root")
        candidates = [candidate]
    else:
        candidates = sorted(path.resolve() for path in root.glob("*.prj") if path.is_file())

    if len(candidates) != 1:
        raise ProcessorError(
            f"Expected exactly one explicit HEC-RAS project beneath {root}; "
            f"found {len(candidates)}. Set project.project_file."
        )
    project_file = candidates[0]
    if project_file.suffix.lower() != ".prj" or not project_file.is_file():
        raise ProcessorError(f"HEC-RAS project file does not exist: {project_file}")
    return project_file


def build_context(config_path: Path, project_root: Path, status_override: Path | None = None) -> ProjectContext:
    """Build validated local paths for one processing run."""

    config_path = config_path.expanduser().resolve(strict=True)
    config = load_config(config_path)
    resolved_root = project_root.expanduser().resolve(strict=True)
    project_file = _resolve_project_file(resolved_root, config["project"])
    output_root = _resolve_config_path(config_path, config["output_root"])
    status_value = status_override or config.get("status_path") or (output_root / "processor-status.json")
    status_path = Path(status_value).expanduser()
    if not status_path.is_absolute():
        status_path = config_path.parent / status_path
    ras2cng = str(config.get("ras2cng") or "ras2cng")
    return ProjectContext(
        config_path=config_path,
        config=config,
        project_root=resolved_root,
        project_file=project_file,
        output_root=output_root,
        archive_dir=output_root / "archive",
        maps_dir=output_root / "maps",
        viewer_dir=output_root / "viewer",
        status_path=status_path.resolve(),
        ras2cng=ras2cng,
    )


def _identity(context: ProjectContext) -> tuple[dict[str, Any], dict[str, Any]]:
    source = copy.deepcopy(context.config["source"])
    project_config = context.config["project"]
    project = {
        "id": project_config["id"],
        "title": project_config.get("title") or context.project_file.stem,
        "projectFile": context.project_file.name,
        "projectRoot": str(context.project_root),
        "primaryGeometry": project_config.get("primary_geometry"),
    }
    return source, project


def _new_status(context: ProjectContext, mode: str, clock: Clock) -> dict[str, Any]:
    source, project = _identity(context)
    phases = ["inspect"]
    if mode in {"extract", "all"}:
        phases.append("extract")
    if mode in {"package", "all"}:
        phases.append("package")
    return {
        "schema": STATUS_SCHEMA,
        "mode": mode,
        "state": "running",
        "startedAt": clock(),
        "finishedAt": None,
        "source": source,
        "project": project,
        "phases": {
            name: {
                "state": "pending",
                "startedAt": None,
                "finishedAt": None,
                "commands": [],
                "outputs": [],
                "errors": [],
            }
            for name in phases
        },
        "errors": [],
    }


def _validate_ras2cng_argv(argv: Sequence[str]) -> None:
    if len(argv) < 2 or argv[1] not in ALLOWED_RAS2CNG_COMMANDS:
        raise ProcessorError(f"Disallowed processor command: {list(argv)!r}")


def _run_command(
    argv: Sequence[str],
    *,
    phase: MutableMapping[str, Any],
    runner: Runner,
    dry_run: bool,
    clock: Clock,
) -> subprocess.CompletedProcess[str]:
    """Run one argv list, retaining command and output evidence in status."""

    command = [str(item) for item in argv]
    _validate_ras2cng_argv(command)
    phase["commands"].append(command)
    started_at = clock()
    if dry_run:
        completed = subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return_code: int | None = None
    else:
        try:
            completed = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError as error:
            completed = subprocess.CompletedProcess(command, 127, stdout="", stderr=str(error))
        return_code = completed.returncode
    phase["outputs"].append(
        {
            "commandIndex": len(phase["commands"]) - 1,
            "startedAt": started_at,
            "finishedAt": clock(),
            "returnCode": return_code,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "dryRun": dry_run,
        }
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no output").strip()
        raise ProcessorError(
            f"ras2cng {command[1]} failed with exit code {completed.returncode}: {detail}"
        )
    return completed


def _parse_json_output(output: str) -> dict[str, Any]:
    """Parse JSON even if a console wrapper added surrounding text."""

    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start < 0 or end < start:
            raise ProcessorError("ras2cng inspect did not produce JSON") from None
        try:
            value = json.loads(output[start : end + 1])
        except json.JSONDecodeError as error:
            raise ProcessorError(f"ras2cng inspect produced invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProcessorError("ras2cng inspect JSON must be an object")
    return value


def _normalize_id(value: Any, prefix: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith(prefix):
        raw = raw[len(prefix) :]
    if not raw.isdigit():
        raise ProcessorError(f"Invalid {prefix} identifier: {value!r}")
    return f"{prefix}{raw.zfill(2)}"


def _fallback_inspection(context: ProjectContext) -> dict[str, Any]:
    """Create dry-run metadata using only bounded direct-child checks."""

    project = context.config["project"]
    extract = context.config.get("extract")
    extract = extract if isinstance(extract, dict) else {}
    configured_hdfs = project.get("geometry_hdfs") or {}
    geometry_ids: set[str] = set()
    if isinstance(configured_hdfs, dict):
        geometry_ids.update(_normalize_id(key, "g") for key in configured_hdfs)
    geometry_ids.update(
        _normalize_id(path.name.split(".g", 1)[1].split(".", 1)[0], "g")
        for path in context.project_root.glob("*.g??.hdf")
        if path.is_file() and ".g" in path.name.lower()
    )
    configured_plans = project.get("plans") or extract.get("plans") or []
    plan_ids = {_normalize_id(value, "p") for value in configured_plans}
    plan_ids.update(
        _normalize_id(path.name.split(".p", 1)[1].split(".", 1)[0], "p")
        for path in context.project_root.glob("*.p??.hdf")
        if path.is_file() and ".p" in path.name.lower()
    )
    terrain_names = project.get("terrain_names") or []
    return {
        "project": {
            "name": context.project_file.stem,
            "prj_file": str(context.project_file),
            "crs": project.get("crs"),
            "units": project.get("units", "Unknown"),
            "ras_version": project.get("ras_version"),
        },
        "geometry_files": [
            {"geom_id": geom_id, "hdf_exists": True} for geom_id in sorted(geometry_ids)
        ],
        "plan_files": [
            {"plan_id": plan_id, "hdf_exists": True, "completed": None}
            for plan_id in sorted(plan_ids)
        ],
        "terrain_files": [],
        "terrain_details": [{"name": name, "tif_count": 1} for name in terrain_names],
    }


def inspect_project(
    context: ProjectContext,
    *,
    phase: MutableMapping[str, Any],
    runner: Runner,
    dry_run: bool,
    clock: Clock,
) -> dict[str, Any]:
    """Inspect exactly one project and return ras2cng's structured metadata."""

    configured = context.config.get("inspection")
    command = [context.ras2cng, "inspect", str(context.project_file), "--json"]
    completed = _run_command(command, phase=phase, runner=runner, dry_run=dry_run, clock=clock)
    if isinstance(configured, dict):
        inspection = copy.deepcopy(configured)
    elif dry_run:
        inspection = _fallback_inspection(context)
    else:
        inspection = _parse_json_output(completed.stdout)

    inspected_project = inspection.get("project")
    if not isinstance(inspected_project, dict):
        raise ProcessorError("ras2cng inspect JSON is missing project metadata")
    inspected_name = str(inspected_project.get("name") or "")
    expected_name = str(context.config["project"].get("name") or context.project_file.stem)
    if inspected_name and inspected_name.casefold() != expected_name.casefold():
        raise ProcessorError(
            f"Inspected project identity {inspected_name!r} does not match {expected_name!r}"
        )
    phase["inspection"] = inspection
    return inspection


def _completed_plan_ids(config: Mapping[str, Any], inspection: Mapping[str, Any]) -> list[str]:
    extract = config.get("extract") if isinstance(config.get("extract"), dict) else {}
    plan_files = inspection.get("plan_files") or []
    indexed = {
        _normalize_id(item.get("plan_id"), "p"): item
        for item in plan_files
        if isinstance(item, dict) and item.get("plan_id")
    }
    configured = extract.get("plans") or config["project"].get("plans")
    if configured:
        selected = [_normalize_id(value, "p") for value in configured]
        missing = [plan_id for plan_id in selected if plan_id not in indexed]
        if missing:
            raise ProcessorError(f"Configured plan(s) were not inspected: {', '.join(missing)}")
        unavailable = [plan_id for plan_id in selected if not indexed[plan_id].get("hdf_exists")]
        if unavailable:
            raise ProcessorError(f"Configured plan HDF(s) are missing: {', '.join(unavailable)}")
        failed = [plan_id for plan_id in selected if indexed[plan_id].get("completed") is False]
        if failed and not extract.get("allow_incomplete_plans", False):
            raise ProcessorError(f"Configured plan(s) did not complete successfully: {', '.join(failed)}")
        return selected

    completion_known = any(item.get("completed") is not None for item in indexed.values())
    return sorted(
        plan_id
        for plan_id, item in indexed.items()
        if item.get("hdf_exists") and (item.get("completed") is True or not completion_known)
    )


def _terrain_policy(config: Mapping[str, Any], inspection: Mapping[str, Any]) -> tuple[bool, bool, list[str]]:
    extract = config.get("extract") if isinstance(config.get("extract"), dict) else {}
    details = [item for item in inspection.get("terrain_details") or [] if isinstance(item, dict)]
    names = [str(item.get("name") or "").strip() for item in details if item.get("name")]
    has_terrain = bool(names or inspection.get("terrain_files"))
    include_setting = extract.get("include_terrain", "auto")
    include = has_terrain if include_setting == "auto" else bool(include_setting)
    consolidate_setting = extract.get("consolidate_terrain", "auto")
    if consolidate_setting == "auto":
        consolidate = include and len(set(names)) == 1
    else:
        consolidate = bool(consolidate_setting)
    if consolidate and len(set(names)) > 1:
        raise ProcessorError(
            "Terrain consolidation would merge distinct named terrains: "
            + ", ".join(sorted(set(names)))
        )
    if consolidate and not include:
        raise ProcessorError("consolidate_terrain requires terrain inclusion")
    return include, consolidate, names


def build_extract_commands(
    context: ProjectContext, inspection: Mapping[str, Any]
) -> tuple[list[list[str]], dict[str, Any]]:
    """Build archive and Stored Map commands using inspection-aware defaults."""

    extract = context.config.get("extract")
    extract = extract if isinstance(extract, dict) else {}
    plan_ids = _completed_plan_ids(context.config, inspection)
    require_results = bool(extract.get("require_results", True))
    if require_results and not plan_ids:
        raise ProcessorError("No successfully completed plan HDF is available for result extraction")

    include_terrain, consolidate_terrain, terrain_names = _terrain_policy(
        context.config, inspection
    )
    archive = [context.ras2cng, "archive", str(context.project_file), str(context.archive_dir)]
    if plan_ids:
        archive.extend(
            [
                "--results",
                "--plans",
                ",".join(plan_ids),
                "--results-layout",
                "variable",
                "--results-geometry",
                "none",
                "--auxiliary-results",
            ]
        )
    if include_terrain:
        archive.append("--terrain")
    if consolidate_terrain:
        archive.append("--consolidate-terrain")
    crs = context.config["project"].get("crs") or inspection.get("project", {}).get("crs")
    if crs:
        archive.extend(["--crs", str(crs)])

    commands = [archive]
    map_results = bool(extract.get("map_results", True))
    if map_results and plan_ids:
        map_types = extract.get("map_types", DEFAULT_MAP_TYPES)
        if not isinstance(map_types, (list, tuple)) or not map_types:
            raise ProcessorError("extract.map_types must be a non-empty list")
        normalized_types = {str(value).strip().lower().replace("-", "_") for value in map_types}
        unknown = normalized_types - {"wse", "depth", "velocity"} - set(MAP_TYPE_FLAGS)
        if unknown:
            raise ProcessorError(f"Unsupported Stored Map type(s): {', '.join(sorted(unknown))}")
        map_command = [
            context.ras2cng,
            "map",
            str(context.project_file),
            str(context.maps_dir),
            "--plans",
            ",".join(plan_ids),
            "--profile",
            str(extract.get("profile", "Max")),
            "--cog",
            "--arrival-depth",
            str(float(extract.get("arrival_depth", 0.1))),
            "--skip-errors",
        ]
        for default_name, disable_flag in (
            ("wse", "--no-wse"),
            ("depth", "--no-depth"),
            ("velocity", "--no-velocity"),
        ):
            if default_name not in normalized_types:
                map_command.append(disable_flag)
        map_command.extend(
            flag for name, flag in MAP_TYPE_FLAGS.items() if name in normalized_types
        )
        map_terrain = extract.get("map_terrain")
        if map_terrain:
            if terrain_names and str(map_terrain) not in terrain_names:
                raise ProcessorError(f"Configured map terrain was not inspected: {map_terrain}")
            map_command.extend(["--terrain", str(map_terrain)])
        ras_version = context.config["project"].get("ras_version") or inspection.get("project", {}).get("ras_version")
        if ras_version:
            map_command.extend(["--ras-version", str(ras_version)])
        if extract.get("render_mode"):
            map_command.extend(["--render-mode", str(extract["render_mode"])])
        if extract.get("timeout") is not None:
            map_command.extend(["--timeout", str(int(extract["timeout"]))])
        commands.append(map_command)

    return commands, {
        "plans": plan_ids,
        "resultsRequired": require_results,
        "terrainIncluded": include_terrain,
        "terrainConsolidated": consolidate_terrain,
        "terrainNames": terrain_names,
        "storedMapsRequested": map_results and bool(plan_ids),
    }


def _geometry_hdf_bindings(
    context: ProjectContext, inspection: Mapping[str, Any], *, require_files: bool
) -> dict[str, Path]:
    project = context.config["project"]
    configured = project.get("geometry_hdfs") or {}
    if not isinstance(configured, dict):
        raise ProcessorError("project.geometry_hdfs must be an object of geometry ID to path")
    bindings: dict[str, Path] = {}
    for key, raw_path in configured.items():
        geom_id = _normalize_id(key, "g")
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = context.project_root / path
        path = path.resolve()
        if not path.is_relative_to(context.project_root):
            raise ProcessorError(f"Geometry HDF override escapes --project-root: {raw_path}")
        bindings[geom_id] = path

    for item in inspection.get("geometry_files") or []:
        if not isinstance(item, dict) or not item.get("geom_id"):
            continue
        geom_id = _normalize_id(item["geom_id"], "g")
        if not item.get("hdf_exists") and geom_id not in bindings:
            raise ProcessorError(f"Geometry {geom_id} has no HDF required for its model footprint")
        bindings.setdefault(
            geom_id,
            context.project_root / f"{context.project_file.stem}.{geom_id}.hdf",
        )
    if not bindings:
        raise ProcessorError("No geometry HDF bindings are available for MapLibre packaging")
    if require_files:
        missing = [f"{geom_id}={path}" for geom_id, path in bindings.items() if not path.is_file()]
        if missing:
            raise ProcessorError("Geometry HDF binding(s) do not exist: " + ", ".join(missing))
    return dict(sorted(bindings.items()))


def build_package_command(
    context: ProjectContext,
    inspection: Mapping[str, Any],
    *,
    require_files: bool,
) -> tuple[list[str], dict[str, Path]]:
    """Build the MapLibre argv with complete geometry-footprint bindings."""

    package = context.config.get("package")
    package = package if isinstance(package, dict) else {}
    project = context.config["project"]
    primary = _normalize_id(project.get("primary_geometry"), "g")
    bindings = _geometry_hdf_bindings(context, inspection, require_files=require_files)
    if primary not in bindings:
        raise ProcessorError(f"Primary geometry {primary} has no geometry HDF binding")

    command = [context.ras2cng, "maplibre", str(context.archive_dir), str(context.viewer_dir)]
    for geom_id, hdf_path in bindings.items():
        command.extend(["--geometry-hdf", f"{geom_id}={hdf_path}"])
    command.extend(["--vector-results", "--primary-geometry", primary])
    if bool(package.get("all_primary_geometry", project.get("all_primary_geometry", False))):
        command.append("--all-primary-geometry")
    source_project = str(package.get("source_project") or "../project.json")
    if _looks_like_local_path(
        source_project,
        [context.project_root, context.output_root, context.config_path.parent],
    ):
        raise ProcessorError(f"package.source_project must be a public URL or relative path: {source_project}")
    command.extend(
        [
            "--title",
            str(project.get("title") or context.project_file.stem),
            "--source-project",
            source_project,
        ]
    )
    crs = project.get("crs") or inspection.get("project", {}).get("crs")
    if crs:
        command.extend(["--crs", str(crs)])
    if package.get("scratch_dir"):
        command.extend(
            ["--scratch-dir", str(_resolve_config_path(context.config_path, package["scratch_dir"]))]
        )
    if package.get("min_zoom") is not None:
        command.extend(["--min-zoom", str(int(package["min_zoom"]))])
    if package.get("max_zoom") is not None:
        command.extend(["--max-zoom", str(int(package["max_zoom"]))])
    return command, bindings


def _public_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in source.items() if key in PUBLIC_SOURCE_KEYS}


def _looks_like_local_path(value: str, local_roots: Sequence[Path]) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if PureWindowsPath(stripped).is_absolute() or stripped.startswith("\\\\"):
        return True
    parsed = urlsplit(stripped)
    if parsed.scheme and parsed.scheme.lower() not in {"file"}:
        return False
    if parsed.scheme.lower() == "file":
        return True
    lowered = stripped.casefold().replace("/", "\\")
    for root in local_roots:
        root_text = str(root).casefold().replace("/", "\\").rstrip("\\")
        if root_text and root_text in lowered:
            return True
    if stripped.startswith("/") and not stripped.startswith(("/data/", "/ras-raster/")):
        return True
    return False


def _sanitize_manifest_value(
    value: Any,
    *,
    local_roots: Sequence[Path],
    pointer: str = "$",
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text in LOCAL_ONLY_MANIFEST_KEYS:
                continue
            if key_text == "prj_file" and isinstance(child, str):
                child = PureWindowsPath(child).name
            sanitized[key_text] = _sanitize_manifest_value(
                child,
                local_roots=local_roots,
                pointer=f"{pointer}.{key_text}",
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_manifest_value(child, local_roots=local_roots, pointer=f"{pointer}[{index}]")
            for index, child in enumerate(value)
        ]
    if isinstance(value, str) and _looks_like_local_path(value, local_roots):
        raise ProcessorError(f"Published manifest contains a local path at {pointer}: {value!r}")
    return value


def sanitize_public_manifest(path: Path, *, local_roots: Sequence[Path]) -> dict[str, Any]:
    """Remove known operational paths and reject every remaining local path."""

    manifest = _read_json_object(path, label="manifest")
    sanitized = _sanitize_manifest_value(manifest, local_roots=local_roots)
    _atomic_write_json(path, sanitized)
    return sanitized


def write_project_manifest(
    context: ProjectContext, inspection: Mapping[str, Any]
) -> dict[str, Any]:
    """Write the public project identity without operational filesystem paths."""

    project = context.config["project"]
    manifest = {
        "schema": PROJECT_SCHEMA,
        "id": project["id"],
        "title": project.get("title") or context.project_file.stem,
        "source": _public_source(context.config["source"]),
        "crs": project.get("crs") or inspection.get("project", {}).get("crs"),
        "units": project.get("units") or inspection.get("project", {}).get("units"),
        "primaryGeometry": _normalize_id(project.get("primary_geometry"), "g"),
    }
    sanitized = _sanitize_manifest_value(
        manifest,
        local_roots=[context.project_root, context.output_root, context.config_path.parent],
    )
    _atomic_write_json(context.output_root / "project.json", sanitized)
    return sanitized


def _stored_map_type(filename: str) -> tuple[str, str] | None:
    normalized = filename.casefold().replace("_", " ")
    checks = (
        ("percent time inundated", "percent-inundated", "Percent Time Inundated"),
        ("arrival time", "arrival-time", "Arrival Time"),
        ("depth x velocity", "depth-x-velocity", "Depth x Velocity"),
        ("water surface", "wse", "Water Surface Elevation"),
        ("wse", "wse", "Water Surface Elevation"),
        ("velocity", "velocity", "Velocity"),
        ("duration", "duration", "Duration"),
        ("depth", "depth", "Depth"),
    )
    for needle, slug, title in checks:
        if normalized.startswith(needle):
            return slug, title
    return None


def _stored_map_candidates(maps_dir: Path) -> list[tuple[str, Path]]:
    """Discover only COGs one level beneath the processor's own maps root."""

    if not maps_dir.is_dir():
        return []
    candidates: list[tuple[str, Path]] = []
    for plan_dir in sorted(path for path in maps_dir.iterdir() if path.is_dir()):
        if not re.fullmatch(r"p\d+", plan_dir.name, flags=re.IGNORECASE):
            continue
        plan_id = _normalize_id(plan_dir.name, "p")
        candidates.extend(
            (plan_id, path)
            for path in sorted(plan_dir.glob("*_cog.tif"))
            if path.is_file() and _stored_map_type(path.name)
        )
    return candidates


def _package_scratch_dir(context: ProjectContext, child: str) -> Path | None:
    package = context.config.get("package")
    package = package if isinstance(package, dict) else {}
    if not package.get("scratch_dir"):
        return None
    return _resolve_config_path(context.config_path, package["scratch_dir"]) / child


def import_terrain(
    context: ProjectContext,
    *,
    phase: MutableMapping[str, Any],
    runner: Runner,
    dry_run: bool,
    clock: Clock,
) -> list[dict[str, Any]]:
    """Publish the archived terrain COG through the semantic terrain command."""

    if dry_run:
        return []
    archive = _read_json_object(context.archive_dir / "manifest.json", label="archive manifest")
    terrain_entries = [item for item in archive.get("terrain") or [] if isinstance(item, dict)]
    if len(terrain_entries) > 1:
        raise ProcessorError(
            "Multiple archived terrain entries require explicit viewer layer IDs; "
            "the one-project processor will not overwrite one terrain with another"
        )

    imported: list[dict[str, Any]] = []
    for item in terrain_entries:
        cog_file = item.get("cog_file")
        if not cog_file:
            continue
        cog_path = context.archive_dir / Path(str(cog_file))
        if not cog_path.is_file():
            raise ProcessorError(f"Archived terrain COG does not exist: {cog_path}")
        command = [
            context.ras2cng,
            "maplibre-terrain",
            str(cog_path),
            str(context.viewer_dir),
            "--name",
            str(item.get("terrain_name") or "Terrain"),
            "--source-cog",
            f"../archive/{Path(str(cog_file)).as_posix()}",
            "--units",
            str(context.config["project"].get("terrain_units") or "ft"),
        ]
        scratch = _package_scratch_dir(context, "terrain")
        if scratch is not None:
            command.extend(["--scratch-dir", str(scratch)])
        _run_command(
            command,
            phase=phase,
            runner=runner,
            dry_run=False,
            clock=clock,
        )
        imported.append(item)
    return imported


def import_stored_maps(
    context: ProjectContext,
    inspection: Mapping[str, Any],
    *,
    phase: MutableMapping[str, Any],
    runner: Runner,
    dry_run: bool,
    clock: Clock,
) -> list[dict[str, Any]]:
    """Import generated Stored Maps through ras2cng's semantic importer."""

    package = context.config.get("package")
    package = package if isinstance(package, dict) else {}
    if not bool(package.get("import_stored_maps", True)):
        return []
    candidates = _stored_map_candidates(context.maps_dir)
    if not candidates:
        return []

    command = [
        context.ras2cng,
        "maplibre-import-stored-maps",
        str(context.maps_dir),
        str(context.archive_dir),
        str(context.viewer_dir),
    ]
    scratch = _package_scratch_dir(context, "stored-maps")
    if scratch is not None:
        command.extend(["--scratch-dir", str(scratch)])
    if bool(package.get("require_all_stored_maps", False)):
        command.append("--require-all")
    else:
        command.append("--allow-partial")
    command.append("--overwrite")
    _run_command(
        command,
        phase=phase,
        runner=runner,
        dry_run=dry_run,
        clock=clock,
    )
    if dry_run:
        return [
            {"id": f"result-{plan_id}-{_stored_map_type(path.name)[0]}"}
            for plan_id, path in candidates
            if _stored_map_type(path.name)
        ]

    manifest = _read_json_object(
        context.viewer_dir / "manifest.json", label="MapLibre viewer manifest"
    )
    layers = manifest.get("layers") or {}
    if not isinstance(layers, dict):
        raise ProcessorError("MapLibre viewer manifest layers must be an object")
    return [
        {"id": layer_id, **entry}
        for layer_id, entry in layers.items()
        if isinstance(entry, dict) and entry.get("sourceKind") == "stored-map"
    ]


def _start_phase(status: MutableMapping[str, Any], name: str, clock: Clock) -> MutableMapping[str, Any]:
    phase = status["phases"][name]
    phase["state"] = "running"
    phase["startedAt"] = clock()
    return phase


def _finish_phase(
    phase: MutableMapping[str, Any], *, dry_run: bool, clock: Clock
) -> None:
    phase["state"] = "planned" if dry_run else "completed"
    phase["finishedAt"] = clock()


def process_project(
    *,
    config_path: Path,
    project_root: Path,
    mode: str,
    status_path: Path | None = None,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
    clock: Clock = utc_now,
) -> dict[str, Any]:
    """Process one explicit project and return the final operational status."""

    if mode not in MODES:
        raise ProcessorError(f"Unsupported mode: {mode!r}")
    context = build_context(config_path, project_root, status_path)
    status = _new_status(context, mode, clock)
    active_phase = "inspect"
    _atomic_write_json(context.status_path, status)

    try:
        inspect_phase = _start_phase(status, "inspect", clock)
        _atomic_write_json(context.status_path, status)
        inspection = inspect_project(
            context,
            phase=inspect_phase,
            runner=runner,
            dry_run=dry_run,
            clock=clock,
        )
        _finish_phase(inspect_phase, dry_run=dry_run, clock=clock)
        _atomic_write_json(context.status_path, status)

        if mode in {"extract", "all"}:
            active_phase = "extract"
            extract_phase = _start_phase(status, "extract", clock)
            commands, policy = build_extract_commands(context, inspection)
            extract_phase["policy"] = policy
            _atomic_write_json(context.status_path, status)
            for command in commands:
                _run_command(
                    command,
                    phase=extract_phase,
                    runner=runner,
                    dry_run=dry_run,
                    clock=clock,
                )
                if not dry_run and command[1] == "archive":
                    sanitize_public_manifest(
                        context.archive_dir / "manifest.json",
                        local_roots=[
                            context.project_root,
                            context.output_root,
                            context.config_path.parent,
                        ],
                    )
                _atomic_write_json(context.status_path, status)
            _finish_phase(extract_phase, dry_run=dry_run, clock=clock)
            _atomic_write_json(context.status_path, status)

        if mode in {"package", "all"}:
            active_phase = "package"
            package_phase = _start_phase(status, "package", clock)
            if not dry_run:
                sanitize_public_manifest(
                    context.archive_dir / "manifest.json",
                    local_roots=[context.project_root, context.output_root, context.config_path.parent],
                )
            command, bindings = build_package_command(
                context,
                inspection,
                require_files=not dry_run,
            )
            package_phase["geometryHdfIds"] = list(bindings)
            _atomic_write_json(context.status_path, status)
            _run_command(
                command,
                phase=package_phase,
                runner=runner,
                dry_run=dry_run,
                clock=clock,
            )
            if not dry_run:
                sanitize_public_manifest(
                    context.viewer_dir / "manifest.json",
                    local_roots=[context.project_root, context.output_root, context.config_path.parent],
                )
            terrain = import_terrain(
                context,
                phase=package_phase,
                runner=runner,
                dry_run=dry_run,
                clock=clock,
            )
            package_phase["terrainImported"] = [
                str(entry.get("terrain_name") or "Terrain") for entry in terrain
            ]
            imported = import_stored_maps(
                context,
                inspection,
                phase=package_phase,
                runner=runner,
                dry_run=dry_run,
                clock=clock,
            )
            package_phase["storedMapsImported"] = [entry["id"] for entry in imported]
            if not dry_run:
                write_project_manifest(context, inspection)
                sanitize_public_manifest(
                    context.viewer_dir / "manifest.json",
                    local_roots=[context.project_root, context.output_root, context.config_path.parent],
                )
            _finish_phase(package_phase, dry_run=dry_run, clock=clock)
            _atomic_write_json(context.status_path, status)

        status["state"] = "dry-run" if dry_run else "completed"
        status["finishedAt"] = clock()
        _atomic_write_json(context.status_path, status)
        return status
    except Exception as error:
        phase = status["phases"].get(active_phase)
        error_record = {"type": type(error).__name__, "message": str(error), "at": clock()}
        if isinstance(phase, dict):
            phase["state"] = "failed"
            phase["finishedAt"] = clock()
            phase["errors"].append(error_record)
        status["state"] = "failed"
        status["finishedAt"] = clock()
        status["errors"].append({"phase": active_phase, **error_record})
        _atomic_write_json(context.status_path, status)
        if isinstance(error, ProcessorError):
            raise
        raise ProcessorError(str(error)) from error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="One explicit HEC-RAS project directory; it is never searched recursively.",
    )
    parser.add_argument("--status", type=Path, default=None, help="Override the status JSON path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and record command vectors without invoking ras2cng.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        status = process_project(
            config_path=args.config,
            project_root=args.project_root,
            mode=args.mode,
            status_path=args.status,
            dry_run=args.dry_run,
        )
    except ProcessorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"state": status["state"], "status": str(args.status or "configured path")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
