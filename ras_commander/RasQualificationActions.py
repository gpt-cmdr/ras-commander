"""Real ``ras-commander`` actions for HEC-RAS qualification manifests.

Each function in this module is a worker-process entry point for
``RasQualificationRunner``.  Actions use public ras-commander APIs, inspect the
resulting content, and return evidence in the runner's strict outcome shape.
They intentionally do not turn missing fixture inputs into skips.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import pandas as pd

from .RasPrj import RasPrj
from .RasQualification import RasQualification, _json_value
from .RasUtils import RasUtils


def _project_path(context: Mapping[str, Any], value: Union[str, Path]) -> Path:
    """Resolve a manifest path relative to the staged project."""
    text = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(text)
    if not path.is_absolute():
        path = Path(str(context["project_folder"])) / path
    return RasUtils.safe_resolve(path)


def _required_file(
    context: Mapping[str, Any],
    value: Optional[Union[str, Path]],
    *,
    label: str,
) -> Path:
    if value is None:
        raise ValueError(f"{label} is required")
    path = _project_path(context, value)
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _initialize(context: Mapping[str, Any]) -> RasPrj:
    # Keep the ordinary drive-letter spelling in the receipt/context while
    # using an extended-length path for Python I/O when MAX_PATH is exceeded.
    # HEC-RAS executables still receive normal paths in the operations that
    # launch the vendor product.
    project_folder = RasUtils.windows_extended_path(
        Path(str(context["project_folder"]))
    )
    project_file = RasUtils.windows_extended_path(Path(str(context["project_file"])))
    project = RasPrj()
    project.initialize(
        project_folder=project_folder,
        ras_exe_path=str(context["ras_executable"]),
        prj_file=project_file,
        suppress_logging=True,
        load_results_summary=False,
    )
    return project


def _first_number(project: RasPrj, frame_name: str, column: str) -> str:
    frame = getattr(project, frame_name)
    if frame is None or frame.empty or column not in frame:
        raise RuntimeError(f"Project has no {column} in {frame_name}")
    return RasUtils.normalize_ras_number(frame[column].iloc[0])


def _plan_number(project: RasPrj, value: Optional[Union[str, int]]) -> str:
    return (
        RasUtils.normalize_ras_number(value)
        if value is not None
        else _first_number(project, "plan_df", "plan_number")
    )


def _geometry_text(
    context: Mapping[str, Any],
    project: RasPrj,
    value: Optional[Union[str, Path]],
) -> Path:
    if value is not None:
        path = _project_path(context, value)
        if path.is_file():
            return path
        number = RasUtils.normalize_ras_number(value)
        hit = project.geom_df[project.geom_df["geom_number"] == number]
    else:
        hit = project.geom_df.iloc[:1]
    if hit.empty:
        raise FileNotFoundError(f"Geometry not found: {value}")
    path = RasUtils.safe_resolve(Path(str(hit["full_path"].iloc[0])))
    if not path.is_file():
        raise FileNotFoundError(f"Geometry text file not found: {path}")
    return path


def _geometry_hdf(geometry_text: Path) -> Path:
    path = Path(str(geometry_text) + ".hdf")
    if not path.is_file():
        raise FileNotFoundError(f"Compiled geometry HDF not found: {path}")
    return path


def _object_dict(value: Any) -> Dict[str, Any]:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return _json_value(dict(value))
    attributes = {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_")
        and not callable(getattr(value, name, None))
    }
    return _json_value(attributes)


def _fresh_compute_preflight(
    context: Mapping[str, Any],
    plan_hdf: Path,
    fresh_result_files: Optional[Sequence[Union[str, Path]]],
    *,
    require_results_group_absent: bool,
) -> Dict[str, Any]:
    """Remove only declared stale outputs and prove the result target is fresh."""
    import h5py

    project_root = RasUtils.safe_resolve(Path(str(context["project_folder"])))
    removed: List[Dict[str, Any]] = []
    for value in fresh_result_files or ():
        candidate = _project_path(context, value)
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                f"Fresh-compute output must be inside the staged project: {candidate}"
            ) from exc
        existed = candidate.is_file()
        item: Dict[str, Any] = {
            "path": str(candidate),
            "existed": existed,
            "sha256_before": None,
            "size_before": None,
        }
        if existed:
            item["sha256_before"] = RasQualification.file_sha256(candidate)
            item["size_before"] = int(candidate.stat().st_size)
            candidate.unlink()
        item["absent_after_removal"] = not candidate.exists()
        removed.append(item)

    target_existed = plan_hdf.is_file()
    results_group_present = False
    inspection_error = None
    if target_existed:
        try:
            with h5py.File(plan_hdf, "r") as hdf:
                results_group_present = "/Results" in hdf
        except (OSError, RuntimeError, ValueError) as exc:
            inspection_error = f"{type(exc).__name__}: {exc}"

    fresh_checks = {
        "declared_outputs_absent": all(
            item["absent_after_removal"] for item in removed
        ),
        "result_group_absent": not results_group_present,
        "result_hdf_inspectable_or_absent": not target_existed
        or inspection_error is None,
    }
    if require_results_group_absent and not all(fresh_checks.values()):
        raise RuntimeError(
            "Fresh-compute preflight failed: "
            f"{json.dumps(fresh_checks, sort_keys=True)}"
        )
    return {
        "declared_outputs": removed,
        "plan_hdf": str(plan_hdf),
        "plan_hdf_existed_after_removal": target_existed,
        "results_group_present_after_removal": results_group_present,
        "inspection_error": inspection_error,
        "require_results_group_absent": bool(require_results_group_absent),
        "checks": fresh_checks,
        "passed": all(fresh_checks.values()),
    }


def _result_series_input_receipts(
    context: Mapping[str, Any],
    specifications: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Fingerprint external spatial inputs used to derive comparison series."""
    receipts: Dict[str, Dict[str, Any]] = {}
    for name, specification in specifications.items():
        if not isinstance(specification, Mapping):
            continue
        if str(specification.get("kind", "")).strip().lower() != "profile_line_flow":
            continue
        value = specification.get("profile_lines_path")
        if value is None:
            continue
        path = _project_path(context, value)
        if not path.is_file():
            raise FileNotFoundError(f"Result-series profile lines not found: {path}")
        sha256 = RasQualification.file_sha256(path)
        expected_sha256 = specification.get("profile_lines_sha256")
        matches = expected_sha256 is None or str(expected_sha256).lower() == sha256
        if not matches:
            raise RuntimeError(
                f"Result-series profile line fingerprint mismatch for {name!r}: "
                f"{sha256} != {expected_sha256}"
            )
        receipts[str(name)] = {
            "path": str(path),
            "sha256": sha256,
            "size": int(path.stat().st_size),
            "expected_sha256": expected_sha256,
            "fingerprint_matches": matches,
        }
    return receipts


def _native_solver_log_receipt(log_path: Path) -> Dict[str, Any]:
    """Inspect the official Linux solver log for terminal content signals."""
    if not log_path.is_file():
        raise FileNotFoundError(f"Native Linux compute log not found: {log_path}")
    text_value = log_path.read_text(encoding="utf-8", errors="replace")
    lower = text_value.lower()
    fatal_patterns = (
        "error with program:",
        "segmentation fault",
        "forrtl: severe",
        "traceback (most recent call last)",
    )
    detected = [pattern for pattern in fatal_patterns if pattern in lower]
    completion_signal = "Finished Unsteady Flow Simulation"
    date_matches = re.findall(r"^\s*ABSDATE=\s*(.+?)\s*$", text_value, re.MULTILINE)
    time_matches = re.findall(r"^\s*ABSTIME=\s*(.+?)\s*$", text_value, re.MULTILINE)
    volume_matches = re.findall(
        r"Overall Volume Accounting Error as percentage:\s*([-+0-9.Ee]+)",
        text_value,
    )
    checks = {
        "completion_signal_present": completion_signal in text_value,
        "no_fatal_signature": not detected,
        "final_date_present": bool(date_matches),
        "final_time_present": bool(time_matches),
        "volume_accounting_present": bool(volume_matches),
    }
    return {
        "path": str(log_path),
        "sha256": RasQualification.file_sha256(log_path),
        "size": int(log_path.stat().st_size),
        "completion_signal": completion_signal,
        "fatal_signatures": detected,
        "final_date": date_matches[-1] if date_matches else None,
        "final_time": time_matches[-1] if time_matches else None,
        "volume_error_percent": (
            float(volume_matches[-1]) if volume_matches else None
        ),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _selected_mesh_topology_evidence(
    geometry_receipt: Mapping[str, Any],
    mesh_name: Optional[str],
) -> Dict[str, Any]:
    """Project one selected area's exact persisted-mesh qualification evidence."""
    raw_areas = geometry_receipt.get("areas", {})
    areas = raw_areas if isinstance(raw_areas, Mapping) else {}
    selected_name = str(mesh_name) if mesh_name is not None else None
    if selected_name is None and len(areas) == 1:
        selected_name = str(next(iter(areas)))
    raw_selected = areas.get(selected_name) if selected_name is not None else None
    selected = raw_selected if isinstance(raw_selected, Mapping) else None

    raw_topology = selected.get("mesh_topology") if selected is not None else None
    topology = raw_topology if isinstance(raw_topology, Mapping) else None
    raw_components = topology.get("components", {}) if topology is not None else {}
    components = raw_components if isinstance(raw_components, Mapping) else {}
    raw_centers = components.get("ordered_nonvirtual_centers", {})
    centers = raw_centers if isinstance(raw_centers, Mapping) else {}
    raw_faces = components.get("ordered_faces_and_indexes", {})
    faces = raw_faces if isinstance(raw_faces, Mapping) else {}

    raw_assignments = geometry_receipt.get("boundary_assignments")
    assignments_available = isinstance(raw_assignments, list)
    assignments = list(raw_assignments) if assignments_available else []
    selected_assignments = [
        assignment
        for assignment in assignments
        if isinstance(assignment, Mapping)
        and str(assignment.get("mesh_name")) == selected_name
    ]

    return {
        "mesh_name": selected_name,
        "selected_area_present": selected is not None,
        "cell_count": selected.get("cell_count") if selected is not None else None,
        "face_count": selected.get("face_count") if selected is not None else None,
        "quality_metrics": selected.get("quality") if selected is not None else None,
        "boundary_assignments_available": assignments_available,
        "boundary_assignments": assignments,
        "selected_area_boundary_assignments": selected_assignments,
        "topology_complete": bool(topology and topology.get("complete")),
        "topology_fingerprint": (
            topology.get("fingerprint") if topology is not None else None
        ),
        "ordered_center_fingerprint": centers.get("fingerprint"),
        "ordered_face_index_fingerprint": faces.get("fingerprint"),
        "topology_declared_cell_count": (
            topology.get("declared_cell_count") if topology is not None else None
        ),
        "topology_face_count": (
            topology.get("face_count") if topology is not None else None
        ),
        "topology_persisted_face_count": (
            topology.get("persisted_face_count") if topology is not None else None
        ),
        "topology_missing_datasets": (
            topology.get("missing_datasets") if topology is not None else None
        ),
        "topology_errors": topology.get("errors") if topology is not None else None,
    }


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _transactional_mesh_topology_checks(
    evidence: Mapping[str, Any],
    *,
    expected_cell_count: int,
    expected_face_count: int,
) -> Dict[str, bool]:
    """Fail-closed checks for the final HDF selected by a transaction."""

    def exact_int(key: str, expected: int) -> bool:
        try:
            return int(evidence.get(key)) == int(expected)
        except (TypeError, ValueError):
            return False

    return {
        "final_selected_area_present": bool(evidence.get("selected_area_present")),
        "final_topology_complete": bool(evidence.get("topology_complete")),
        "final_topology_fingerprint_present": _is_sha256(
            evidence.get("topology_fingerprint")
        ),
        "final_ordered_centers_fingerprint_present": _is_sha256(
            evidence.get("ordered_center_fingerprint")
        ),
        "final_ordered_faces_indexes_fingerprint_present": _is_sha256(
            evidence.get("ordered_face_index_fingerprint")
        ),
        "final_selected_area_cells_exact": exact_int(
            "cell_count", expected_cell_count
        ),
        "final_selected_area_faces_exact": exact_int(
            "face_count", expected_face_count
        ),
        "final_topology_declared_cells_exact": exact_int(
            "topology_declared_cell_count", expected_cell_count
        ),
        "final_topology_faces_exact": exact_int(
            "topology_face_count", expected_face_count
        ),
        "final_topology_persisted_faces_exact": exact_int(
            "topology_persisted_face_count", expected_face_count
        ),
        "final_quality_metrics_present": isinstance(
            evidence.get("quality_metrics"), Mapping
        ),
        "final_boundary_assignments_available": bool(
            evidence.get("boundary_assignments_available")
        ),
    }


def _file_record(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": RasQualification.file_sha256(path),
    }


def _project_inventory(project: RasPrj) -> Dict[str, Any]:
    return {
        "project_name": project.project_name,
        "project_file": str(project.prj_file),
        "plan_count": int(len(project.plan_df)),
        "geometry_count": int(len(project.geom_df)),
        "unsteady_count": int(len(project.unsteady_df)),
        "steady_count": int(len(project.flow_df)),
        "boundary_count": int(len(project.boundaries_df)),
        "rasmap_loaded": bool(getattr(project, "rasmap_df", None) is not None),
        "project_crs": str(project.project_crs) if project.project_crs else None,
    }


def project_open(context: Mapping[str, Any], **_: Any) -> Dict[str, Any]:
    """Open the staged project and prove that its model inventory was parsed."""
    project = _initialize(context)
    evidence = _project_inventory(project)
    evidence["project_fingerprint"] = RasQualification.project_tree_fingerprint(
        context["project_folder"]
    )
    evidence["project_file_sha256"] = RasQualification.file_sha256(project.prj_file)
    return {"passed": evidence["plan_count"] > 0, "evidence": evidence}


def project_save(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    marker: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Round-trip a plan description, reopen it, and verify persisted content."""
    from .RasPlan import RasPlan

    project = _initialize(context)
    number = _plan_number(project, plan_number)
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Plan {number} not found")
    plan_path = Path(plan_path)
    before_sha = RasQualification.file_sha256(plan_path)
    old_description = RasPlan.read_plan_description(plan_path, ras_object=project)
    save_marker = marker or f"RAS qualification save {uuid.uuid4().hex}"
    if not RasPlan.update_plan_description(number, save_marker, ras_object=project):
        raise RuntimeError(f"Plan description writer returned false for {plan_path}")

    reopened = _initialize(context)
    persisted = RasPlan.read_plan_description(plan_path, ras_object=reopened)
    after_sha = RasQualification.file_sha256(plan_path)
    passed = persisted == save_marker and after_sha != before_sha
    evidence = {
        "plan_number": number,
        "plan_path": str(plan_path),
        "old_description_sha256": hashlib.sha256(
            old_description.encode("utf-8")
        ).hexdigest(),
        "marker_sha256": hashlib.sha256(save_marker.encode("utf-8")).hexdigest(),
        "persisted_exactly": persisted == save_marker,
        "file_changed": after_sha != before_sha,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "reopened_inventory": _project_inventory(reopened),
    }
    return {"passed": passed, "evidence": evidence}


def path_variant_open(
    context: Mapping[str, Any],
    variant: Optional[str] = None,
    minimum_long_path: int = 280,
    **_: Any,
) -> Dict[str, Any]:
    """Clone and open the staged fixture under spaces or a long path."""
    operation_id = str(context.get("operation_id", ""))
    requested = variant or ({"path.spaces": "spaces", "path.long": "long"}.get(operation_id))
    if requested not in {"spaces", "long"}:
        raise ValueError("variant must be spaces or long")
    stage = RasQualification.stage_project(
        context["project_folder"],
        context["workspace_root"],
        task_id=f"{context['fixture']['id']}-{operation_id}",
        path_variant=requested,
        minimum_long_path=int(minimum_long_path),
    )
    variant_context = dict(context)
    variant_context.update(
        {"project_folder": stage["destination"], "project_file": stage["project_file"]}
    )
    opened = _initialize(variant_context)
    evidence = dict(stage)
    evidence["inventory"] = _project_inventory(opened)
    evidence["drive_preserved"] = (
        Path(stage["destination"]).drive == Path(str(context["workspace_root"])).drive
    )
    passed = bool(
        stage["content_matches"]
        and evidence["inventory"]["plan_count"] > 0
        and (requested != "spaces" or " " in stage["destination"])
        and (requested != "long" or stage["path_length"] >= minimum_long_path)
    )
    return {"passed": passed, "evidence": evidence}


def wine_prefix_create(
    context: Mapping[str, Any],
    wine_binary: str = "wine",
    timeout: int = 300,
    template_prefix: Optional[Union[str, Path]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Create a unique 64-bit Wine prefix for this lane run."""
    receipt = RasQualification.create_isolated_wine_prefix(
        Path(str(context["run_directory"])) / "wine-prefixes",
        task_id=f"{context['fixture']['id']}-{uuid.uuid4().hex[:10]}",
        wine_executable=wine_binary,
        timeout=timeout,
        template_prefix=template_prefix,
    )
    marker = Path(receipt["prefix"]) / ".ras-commander-prefix.json"
    receipt["marker"] = str(marker)
    receipt["marker_sha256"] = RasQualification.file_sha256(marker)
    return {
        "passed": bool(receipt.get("initialized") and receipt.get("marker_sha256")),
        "evidence": receipt,
        "context_updates": {"wine_prefix": receipt["prefix"]},
    }


def projection_select(
    context: Mapping[str, Any],
    projection_prj: Union[str, Path],
    terrain_hdf: Union[str, Path],
    layer_name: str = "Qualification Terrain",
    expected_projection_sha256: Optional[str] = None,
    expected_epsg: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Persist and optionally qualify an exact RAS Mapper projection."""
    from .RasMap import RasMap

    projection_path = _required_file(context, projection_prj, label="projection PRJ")
    terrain_path = _required_file(context, terrain_hdf, label="terrain HDF")
    project = _initialize(context)
    rasmap_path = Path(project.project_folder) / f"{project.project_name}.rasmap"
    RasMap.add_terrain_layer(
        terrain_hdf=terrain_path,
        rasmap_path=rasmap_path,
        layer_name=layer_name,
        projection_prj=projection_path,
        ras_object=project,
    )
    reopened = _initialize(context)
    selected = None
    if reopened.rasmap_df is not None and not reopened.rasmap_df.empty:
        selected = reopened.rasmap_df["projection_path"].iloc[0]
    selected_path = RasUtils.safe_resolve(Path(str(selected))) if selected else None

    projection_record = _file_record(projection_path)
    normalized_expected_sha256 = (
        str(expected_projection_sha256).strip().lower()
        if expected_projection_sha256 is not None
        else None
    )
    projection_sha256_exact = bool(
        normalized_expected_sha256 is None
        or projection_record["sha256"].lower() == normalized_expected_sha256
    )

    normalized_expected_epsg = (
        int(expected_epsg) if expected_epsg is not None else None
    )
    normalized_crs = None
    project_crs_epsg = None
    project_crs_authority = None
    project_crs_normalization_error = None
    epsg_min_confidence = 25
    if reopened.project_crs is not None:
        try:
            from pyproj import CRS
            from pyproj.exceptions import CRSError
        except ImportError as exc:
            project_crs_normalization_error = f"{type(exc).__name__}: {exc}"
        else:
            try:
                normalized_crs = CRS.from_user_input(reopened.project_crs)
                project_crs_epsg = normalized_crs.to_epsg(
                    min_confidence=epsg_min_confidence
                )
                authority = normalized_crs.to_authority(
                    min_confidence=epsg_min_confidence
                )
                if authority is not None:
                    project_crs_authority = {
                        "name": str(authority[0]),
                        "code": str(authority[1]),
                    }
                    if (
                        project_crs_epsg is None
                        and str(authority[0]).strip().upper() == "EPSG"
                    ):
                        project_crs_epsg = int(authority[1])
            except (CRSError, TypeError, ValueError) as exc:
                project_crs_normalization_error = f"{type(exc).__name__}: {exc}"
    elif normalized_expected_epsg is not None:
        project_crs_normalization_error = "project CRS was not available"

    epsg_exact = bool(
        normalized_expected_epsg is None
        or project_crs_epsg == normalized_expected_epsg
    )
    evidence = {
        "projection": projection_record,
        "selected_projection": str(selected_path) if selected_path else None,
        "selected_exactly": selected_path == projection_path,
        "rasmap": _file_record(rasmap_path),
        "project_crs": str(reopened.project_crs) if reopened.project_crs else None,
        "project_crs_normalized_wkt": (
            normalized_crs.to_wkt() if normalized_crs is not None else None
        ),
        "project_crs_authority": project_crs_authority,
        "project_crs_epsg": project_crs_epsg,
        "project_crs_normalization_error": project_crs_normalization_error,
        "expected_projection_sha256": normalized_expected_sha256,
        "projection_sha256_exact": projection_sha256_exact,
        "expected_epsg": normalized_expected_epsg,
        "epsg_min_confidence": epsg_min_confidence,
        "epsg_exact": epsg_exact,
    }
    return {
        "passed": bool(
            evidence["selected_exactly"]
            and projection_sha256_exact
            and epsg_exact
        ),
        "evidence": evidence,
    }


def _terrain_hdf_receipt(
    terrain_hdf: Path,
    source_rasters: Sequence[Path],
) -> Dict[str, Any]:
    return RasQualification.terrain_receipt(terrain_hdf, source_rasters)


def _terrain_acceptance(
    receipt: Mapping[str, Any],
    *,
    minimum_levels: int,
    expected_layer_priorities: Optional[Mapping[str, int]] = None,
    expected_pyramid_levels: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_shapes: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_counts: Optional[Mapping[str, int]] = None,
    expected_terrain_hdf_fingerprint: Optional[str] = None,
    expected_terrain_data_fingerprint: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate terrain artifacts using exact persisted-content expectations."""
    minimum = int(minimum_levels)
    if minimum < 0:
        raise ValueError("minimum_levels must be non-negative")

    actual_levels = {
        str(name): [int(level) for level in levels]
        for name, levels in (receipt.get("pyramid_levels") or {}).items()
    }
    level_checks = {
        name: len(levels) >= minimum
        for name, levels in actual_levels.items()
    }

    normalized_priorities: Optional[Dict[str, int]] = None
    if expected_layer_priorities is not None:
        if not isinstance(expected_layer_priorities, Mapping):
            raise TypeError("expected_layer_priorities must be a mapping")
        normalized_priorities = {
            str(name): int(priority)
            for name, priority in expected_layer_priorities.items()
        }
    actual_priorities = {
        str(name): (None if priority is None else int(priority))
        for name, priority in (receipt.get("layer_priorities") or {}).items()
    }
    priorities_exact = bool(
        normalized_priorities is None
        or actual_priorities == normalized_priorities
    )

    normalized_levels: Optional[Dict[str, list[int]]] = None
    if expected_pyramid_levels is not None:
        if not isinstance(expected_pyramid_levels, Mapping):
            raise TypeError("expected_pyramid_levels must be a mapping")
        normalized_levels = {}
        for name, levels in expected_pyramid_levels.items():
            if isinstance(levels, (str, bytes)) or not isinstance(levels, Sequence):
                raise TypeError(
                    f"expected_pyramid_levels[{name!r}] must be a sequence"
                )
            normalized_levels[str(name)] = sorted(int(level) for level in levels)
    pyramid_levels_exact = bool(
        normalized_levels is None
        or actual_levels == normalized_levels
    )

    stitch_datasets_value = receipt.get("stitch_datasets") or {}
    stitch_datasets = (
        stitch_datasets_value
        if isinstance(stitch_datasets_value, Mapping)
        else {}
    )
    supported_stitch_datasets = set(RasQualification._TERRAIN_STITCH_DATASETS)

    normalized_shapes: Optional[Dict[str, list[int]]] = None
    if expected_stitch_dataset_shapes is not None:
        if not isinstance(expected_stitch_dataset_shapes, Mapping):
            raise TypeError("expected_stitch_dataset_shapes must be a mapping")
        normalized_shapes = {}
        for name, shape in expected_stitch_dataset_shapes.items():
            dataset_name = str(name)
            if dataset_name not in supported_stitch_datasets:
                raise ValueError(f"Unknown terrain stitch dataset: {dataset_name}")
            if isinstance(shape, (str, bytes)) or not isinstance(shape, Sequence):
                raise TypeError(
                    f"expected_stitch_dataset_shapes[{dataset_name!r}] must be a sequence"
                )
            normalized_shapes[dataset_name] = [int(value) for value in shape]
    stitch_shape_checks = {
        name: bool(
            isinstance(stitch_datasets.get(name), Mapping)
            and stitch_datasets[name].get("present") is True
            and stitch_datasets[name].get("shape") == shape
        )
        for name, shape in (normalized_shapes or {}).items()
    }

    normalized_counts: Optional[Dict[str, int]] = None
    if expected_stitch_dataset_counts is not None:
        if not isinstance(expected_stitch_dataset_counts, Mapping):
            raise TypeError("expected_stitch_dataset_counts must be a mapping")
        normalized_counts = {}
        for name, count in expected_stitch_dataset_counts.items():
            dataset_name = str(name)
            if dataset_name not in supported_stitch_datasets:
                raise ValueError(f"Unknown terrain stitch dataset: {dataset_name}")
            normalized_counts[dataset_name] = int(count)
    stitch_count_checks = {
        name: bool(
            isinstance(stitch_datasets.get(name), Mapping)
            and stitch_datasets[name].get("present") is True
            and int(stitch_datasets[name].get("count", -1)) == count
        )
        for name, count in (normalized_counts or {}).items()
    }

    semantic_fingerprint_exact = bool(
        expected_terrain_hdf_fingerprint is None
        or receipt.get("terrain_hdf_fingerprint")
        == str(expected_terrain_hdf_fingerprint)
    )
    content_fingerprint_exact = bool(
        expected_terrain_data_fingerprint is None
        or receipt.get("data_fingerprint")
        == str(expected_terrain_data_fingerprint)
    )

    checks = {
        "minimum_levels_present": bool(level_checks and all(level_checks.values())),
        "layer_priorities_exact": priorities_exact,
        "pyramid_levels_exact": pyramid_levels_exact,
        "stitch_dataset_shapes_exact": bool(
            normalized_shapes is None
            or stitch_shape_checks
            and all(stitch_shape_checks.values())
        ),
        "stitch_dataset_counts_exact": bool(
            normalized_counts is None
            or stitch_count_checks
            and all(stitch_count_checks.values())
        ),
        "semantic_fingerprint_exact": semantic_fingerprint_exact,
        "content_fingerprint_exact": content_fingerprint_exact,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "level_checks": level_checks,
        "layer_priorities": actual_priorities,
        "expected_layer_priorities": normalized_priorities,
        "expected_pyramid_levels": normalized_levels,
        "stitch_datasets": stitch_datasets,
        "expected_stitch_dataset_shapes": normalized_shapes,
        "stitch_shape_checks": stitch_shape_checks,
        "expected_stitch_dataset_counts": normalized_counts,
        "stitch_count_checks": stitch_count_checks,
        "expected_terrain_hdf_fingerprint": expected_terrain_hdf_fingerprint,
        "expected_terrain_data_fingerprint": expected_terrain_data_fingerprint,
    }


def _process_affinity_receipt() -> Dict[str, Any]:
    """Return the CPU affinity visible to the current qualification worker."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessAffinityMask.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
        if not kernel32.GetProcessAffinityMask(
            kernel32.GetCurrentProcess(),
            ctypes.byref(process_mask),
            ctypes.byref(system_mask),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        mask = int(process_mask.value)
        system = int(system_mask.value)
    elif hasattr(os, "sched_getaffinity"):
        cpu_ids = sorted(int(cpu) for cpu in os.sched_getaffinity(0))
        return {
            "cpu_count": len(cpu_ids),
            "cpu_ids": cpu_ids,
            "process_mask_hex": None,
            "system_mask_hex": None,
        }
    else:
        count = int(os.cpu_count() or 0)
        return {
            "cpu_count": count,
            "cpu_ids": list(range(count)),
            "process_mask_hex": None,
            "system_mask_hex": None,
        }

    cpu_ids = [bit for bit in range(mask.bit_length()) if mask & (1 << bit)]
    return {
        "cpu_count": len(cpu_ids),
        "cpu_ids": cpu_ids,
        "process_mask_hex": hex(mask),
        "system_mask_hex": hex(system),
    }


def terrain_import(
    context: Mapping[str, Any],
    input_rasters: Sequence[Union[str, Path]],
    output_folder: Union[str, Path] = "Qualification Terrain",
    terrain_name: str = "QualificationTerrain",
    units: str = "Feet",
    stitch: bool = True,
    minimum_levels: int = 2,
    expected_layer_count: Optional[int] = None,
    expected_layer_priorities: Optional[Mapping[str, int]] = None,
    expected_pyramid_levels: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_shapes: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_counts: Optional[Mapping[str, int]] = None,
    expected_terrain_hdf_fingerprint: Optional[str] = None,
    expected_terrain_data_fingerprint: Optional[str] = None,
    rasprocess_timeout_seconds: int = 600,
    expected_process_cpu_count: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Build a HEC-RAS terrain from source rasters with the installed product."""
    from .terrain import RasTerrain

    affinity = _process_affinity_receipt()
    cpu_count_exact = bool(
        expected_process_cpu_count is None
        or int(affinity["cpu_count"]) == int(expected_process_cpu_count)
    )
    sources = [_required_file(context, item, label="terrain source raster") for item in input_rasters]
    output = _project_path(context, output_folder)
    terrain_hdf = RasTerrain.create_terrain_from_rasters(
        input_rasters=sources,
        output_folder=output,
        terrain_name=terrain_name,
        units=units,
        stitch=bool(stitch),
        hecras_version=str(context["expected_version"]),
        generate_prj=True,
        timeout_seconds=int(rasprocess_timeout_seconds),
    )
    terrain_hdf = Path(terrain_hdf)
    receipt = _terrain_hdf_receipt(terrain_hdf, sources)
    acceptance = _terrain_acceptance(
        receipt,
        minimum_levels=minimum_levels,
        expected_layer_priorities=expected_layer_priorities,
        expected_pyramid_levels=expected_pyramid_levels,
        expected_stitch_dataset_shapes=expected_stitch_dataset_shapes,
        expected_stitch_dataset_counts=expected_stitch_dataset_counts,
        expected_terrain_hdf_fingerprint=expected_terrain_hdf_fingerprint,
        expected_terrain_data_fingerprint=expected_terrain_data_fingerprint,
    )
    layer_count_exact = bool(
        expected_layer_count is None
        or int(receipt["layer_count"]) == int(expected_layer_count)
    )
    evidence = {
        "terrain_hdf": _file_record(terrain_hdf),
        "source_raster_count": len(sources),
        "source_rasters": receipt["source_rasters"],
        "layer_count": receipt["layer_count"],
        "expected_layer_count": expected_layer_count,
        "layer_count_exact": layer_count_exact,
        "pyramid_levels": receipt["pyramid_levels"],
        "minimum_levels": int(minimum_levels),
        "level_checks": acceptance["level_checks"],
        "layer_priorities": acceptance["layer_priorities"],
        "expected_layer_priorities": acceptance["expected_layer_priorities"],
        "expected_pyramid_levels": acceptance["expected_pyramid_levels"],
        "stitch_datasets": acceptance["stitch_datasets"],
        "expected_stitch_dataset_shapes": acceptance[
            "expected_stitch_dataset_shapes"
        ],
        "stitch_shape_checks": acceptance["stitch_shape_checks"],
        "expected_stitch_dataset_counts": acceptance[
            "expected_stitch_dataset_counts"
        ],
        "stitch_count_checks": acceptance["stitch_count_checks"],
        "expected_terrain_hdf_fingerprint": acceptance[
            "expected_terrain_hdf_fingerprint"
        ],
        "expected_terrain_data_fingerprint": acceptance[
            "expected_terrain_data_fingerprint"
        ],
        "content_checks": acceptance["checks"],
        "terrain_hdf_fingerprint": receipt["terrain_hdf_fingerprint"],
        "terrain_data_fingerprint": receipt["data_fingerprint"],
        "terrain_hdf_raw_fingerprint": receipt["terrain_hdf_raw_fingerprint"],
        "terrain_raw_data_fingerprint": receipt["raw_data_fingerprint"],
        "process_cpu_affinity": affinity,
        "expected_process_cpu_count": expected_process_cpu_count,
        "process_cpu_count_exact": cpu_count_exact,
    }
    return {
        "passed": bool(
            acceptance["passed"]
            and layer_count_exact
            and int(receipt["layer_count"]) == len(sources)
            and cpu_count_exact
        ),
        "evidence": evidence,
        "artifacts": {"terrain": receipt},
        "context_updates": {
            "qualification_terrain_hdf": str(terrain_hdf),
            "qualification_terrain_sources": [str(path) for path in sources],
            "qualification_projection_prj": str(output / "Projection.prj"),
        },
    }


def terrain_build_pyramids(
    context: Mapping[str, Any],
    terrain_hdf: Optional[Union[str, Path]] = None,
    source_rasters: Optional[Sequence[Union[str, Path]]] = None,
    minimum_levels: int = 2,
    expected_layer_priorities: Optional[Mapping[str, int]] = None,
    expected_pyramid_levels: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_shapes: Optional[Mapping[str, Sequence[int]]] = None,
    expected_stitch_dataset_counts: Optional[Mapping[str, int]] = None,
    expected_terrain_hdf_fingerprint: Optional[str] = None,
    expected_terrain_data_fingerprint: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Inspect HEC-RAS terrain pyramid content produced by the prior build."""
    hdf_value = terrain_hdf or context.get("qualification_terrain_hdf")
    hdf_path = _required_file(context, hdf_value, label="terrain HDF")
    raster_values = source_rasters or context.get("qualification_terrain_sources") or []
    rasters = [_required_file(context, item, label="terrain source raster") for item in raster_values]
    receipt = _terrain_hdf_receipt(hdf_path, rasters)
    acceptance = _terrain_acceptance(
        receipt,
        minimum_levels=minimum_levels,
        expected_layer_priorities=expected_layer_priorities,
        expected_pyramid_levels=expected_pyramid_levels,
        expected_stitch_dataset_shapes=expected_stitch_dataset_shapes,
        expected_stitch_dataset_counts=expected_stitch_dataset_counts,
        expected_terrain_hdf_fingerprint=expected_terrain_hdf_fingerprint,
        expected_terrain_data_fingerprint=expected_terrain_data_fingerprint,
    )
    evidence = {
        "terrain_hdf": _file_record(hdf_path),
        "pyramid_levels": receipt["pyramid_levels"],
        "minimum_levels": int(minimum_levels),
        "level_checks": acceptance["level_checks"],
        "layer_priorities": acceptance["layer_priorities"],
        "expected_layer_priorities": acceptance["expected_layer_priorities"],
        "expected_pyramid_levels": acceptance["expected_pyramid_levels"],
        "stitch_datasets": acceptance["stitch_datasets"],
        "expected_stitch_dataset_shapes": acceptance[
            "expected_stitch_dataset_shapes"
        ],
        "stitch_shape_checks": acceptance["stitch_shape_checks"],
        "expected_stitch_dataset_counts": acceptance[
            "expected_stitch_dataset_counts"
        ],
        "stitch_count_checks": acceptance["stitch_count_checks"],
        "expected_terrain_hdf_fingerprint": acceptance[
            "expected_terrain_hdf_fingerprint"
        ],
        "expected_terrain_data_fingerprint": acceptance[
            "expected_terrain_data_fingerprint"
        ],
        "content_checks": acceptance["checks"],
        "terrain_hdf_fingerprint": receipt["terrain_hdf_fingerprint"],
        "terrain_data_fingerprint": receipt["data_fingerprint"],
        "terrain_hdf_raw_fingerprint": receipt["terrain_hdf_raw_fingerprint"],
        "terrain_raw_data_fingerprint": receipt["raw_data_fingerprint"],
    }
    return {
        "passed": bool(acceptance["passed"]),
        "evidence": evidence,
        "artifacts": {"terrain": receipt},
    }


def terrain_associate(
    context: Mapping[str, Any],
    geometry: Optional[Union[str, Path]] = None,
    terrain_hdf: Optional[Union[str, Path]] = None,
    source_rasters: Optional[Sequence[Union[str, Path]]] = None,
    mesh_name: Optional[str] = None,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    expected_topology_fingerprint: Optional[str] = None,
    expected_terrain_hdf_fingerprint: Optional[str] = None,
    expected_terrain_data_fingerprint: Optional[str] = None,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 300.0,
    managed_host_max_attempts: int = 3,
    **_: Any,
) -> Dict[str, Any]:
    """Associate terrain using RasMapperLib and verify persisted HDF attributes."""
    from .geom import GeomMesh

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    geom_hdf_path = _geometry_hdf(geom_path)
    geometry_before = RasQualification.geometry_receipt(geom_hdf_path)
    terrain_value = terrain_hdf or context.get("qualification_terrain_hdf")
    terrain_path = _required_file(context, terrain_value, label="terrain HDF")
    managed_host_evidence: Dict[str, Any] = {}
    GeomMesh.set_geometry_association(
        geom_path,
        terrain_hdf_path=terrain_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        validate=True,
        interop_backend=interop_backend,
        timeout_seconds=float(managed_host_timeout_seconds),
        max_attempts=int(managed_host_max_attempts),
        managed_host_evidence=managed_host_evidence,
    )
    association = GeomMesh.get_geometry_association(
        geom_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        resolve_paths=True,
    )
    associated = association.get("terrain_hdf_path")
    associated_path = RasUtils.safe_resolve(Path(str(associated))) if associated else None
    raster_values = source_rasters or context.get("qualification_terrain_sources") or []
    rasters = [_required_file(context, item, label="terrain source raster") for item in raster_values]
    terrain_receipt = _terrain_hdf_receipt(terrain_path, rasters)
    geometry_receipt = RasQualification.geometry_receipt(geom_hdf_path)
    before_areas = geometry_before.get("areas") or {}
    after_areas = geometry_receipt.get("areas") or {}
    selected_mesh = mesh_name
    if selected_mesh is None and len(after_areas) == 1:
        selected_mesh = next(iter(after_areas))
    before_area = before_areas.get(selected_mesh) if selected_mesh else None
    after_area = after_areas.get(selected_mesh) if selected_mesh else None
    before_topology = (
        before_area.get("mesh_topology")
        if isinstance(before_area, Mapping)
        else None
    )
    after_topology = (
        after_area.get("mesh_topology")
        if isinstance(after_area, Mapping)
        else None
    )
    checks = {
        "associated_exactly": associated_path == terrain_path,
        "selected_mesh_present_before": isinstance(before_area, Mapping),
        "selected_mesh_present_after": isinstance(after_area, Mapping),
        "mesh_topology_complete": bool(
            isinstance(after_topology, Mapping)
            and after_topology.get("complete") is True
        ),
        "mesh_topology_preserved": bool(
            isinstance(before_topology, Mapping)
            and isinstance(after_topology, Mapping)
            and before_topology.get("fingerprint")
            == after_topology.get("fingerprint")
        ),
        "cell_count_exact": bool(
            expected_cell_count is None
            or (
                isinstance(after_area, Mapping)
                and int(after_area.get("cell_count", -1))
                == int(expected_cell_count)
            )
        ),
        "face_count_exact": bool(
            expected_face_count is None
            or (
                isinstance(after_area, Mapping)
                and int(after_area.get("face_count", -1))
                == int(expected_face_count)
            )
        ),
        "topology_fingerprint_exact": bool(
            expected_topology_fingerprint is None
            or (
                isinstance(after_topology, Mapping)
                and after_topology.get("fingerprint")
                == str(expected_topology_fingerprint).lower()
            )
        ),
        "terrain_hdf_fingerprint_exact": bool(
            expected_terrain_hdf_fingerprint is None
            or terrain_receipt.get("terrain_hdf_fingerprint")
            == str(expected_terrain_hdf_fingerprint).lower()
        ),
        "terrain_data_fingerprint_exact": bool(
            expected_terrain_data_fingerprint is None
            or terrain_receipt.get("data_fingerprint")
            == str(expected_terrain_data_fingerprint).lower()
        ),
    }
    evidence = {
        "association": association,
        "associated_exactly": checks["associated_exactly"],
        "interop_backend": interop_backend,
        "managed_host": managed_host_evidence or None,
        "selected_mesh_name": selected_mesh,
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "expected_topology_fingerprint": expected_topology_fingerprint,
        "expected_terrain_hdf_fingerprint": expected_terrain_hdf_fingerprint,
        "expected_terrain_data_fingerprint": expected_terrain_data_fingerprint,
        "before_geometry_fingerprint": geometry_before["geometry_fingerprint"],
        "before_mesh_topology": before_topology,
        "geometry_fingerprint": geometry_receipt["geometry_fingerprint"],
        "mesh_topology": after_topology,
        "terrain_hdf_sha256": terrain_receipt["terrain_hdf_sha256"],
        "terrain_hdf_fingerprint": terrain_receipt.get(
            "terrain_hdf_fingerprint"
        ),
        "terrain_data_fingerprint": terrain_receipt.get("data_fingerprint"),
        "content_checks": checks,
    }
    return {
        "passed": all(checks.values()),
        "evidence": evidence,
        "artifacts": {"terrain": terrain_receipt, "geometry": geometry_receipt},
    }


def _compiled_2d_area_feature_receipt(
    geometry_hdf: Path,
    flow_area_name: str,
    text_polygon: Any,
) -> Dict[str, Any]:
    """Inspect the zero-mesh RAS Mapper feature compiled by full HEC-RAS.

    HEC-RAS stores 2D-area names in a fixed 16-byte field.  A freshly authored
    perimeter is expected to appear in the global feature/point tables before
    Mapper seed generation creates the per-area mesh group.
    """
    import h5py
    import numpy as np
    from shapely.geometry import Polygon as ShapelyPolygon

    base = "Geometry/2D Flow Areas"
    required = {
        "attributes": f"{base}/Attributes",
        "cell_info": f"{base}/Cell Info",
        "polygon_info": f"{base}/Polygon Info",
        "polygon_parts": f"{base}/Polygon Parts",
        "polygon_points": f"{base}/Polygon Points",
    }
    missing: List[str] = []
    with h5py.File(geometry_hdf, "r") as hdf:
        missing = [path for path in required.values() if path not in hdf]
        if missing:
            return {
                "passed": False,
                "geometry_hdf": str(geometry_hdf),
                "flow_area_name": flow_area_name,
                "missing_datasets": missing,
            }

        attributes = np.asarray(hdf[required["attributes"]][:])
        names = [
            (
                bytes(value).decode("utf-8", errors="replace").rstrip("\x00 ")
                if isinstance(value, (bytes, np.bytes_))
                else str(value).rstrip("\x00 ")
            )
            for value in attributes["Name"]
        ]
        matches = [index for index, name in enumerate(names) if name == flow_area_name]
        if len(matches) != 1:
            return {
                "passed": False,
                "geometry_hdf": str(geometry_hdf),
                "flow_area_name": flow_area_name,
                "compiled_names": names,
                "exact_name_match_count": len(matches),
                "missing_datasets": [],
            }

        index = matches[0]
        polygon_info = np.asarray(hdf[required["polygon_info"]][index])
        polygon_parts = np.asarray(hdf[required["polygon_parts"]][:])
        polygon_points = np.asarray(hdf[required["polygon_points"]][:])
        point_start = int(polygon_info[0])
        point_count = int(polygon_info[1])
        part_start = int(polygon_info[2])
        part_count = int(polygon_info[3])
        points = np.asarray(
            polygon_points[point_start : point_start + point_count],
            dtype=np.float64,
        )
        parts = np.asarray(
            polygon_parts[part_start : part_start + part_count],
            dtype=np.int64,
        )
        compiled_polygon = (
            ShapelyPolygon(points)
            if part_count == 1 and point_count >= 3
            else None
        )
        polygon_valid = bool(
            compiled_polygon is not None
            and not compiled_polygon.is_empty
            and compiled_polygon.is_valid
            and compiled_polygon.area > 0
        )
        polygon_matches_text = bool(
            polygon_valid
            and text_polygon is not None
            and compiled_polygon.equals(text_polygon)
        )
        cell_count = int(attributes["Cell Count"][index])
        cell_info = np.asarray(hdf[required["cell_info"]][index], dtype=np.int64)
        row = attributes[index]

    return {
        "passed": bool(
            len(matches) == 1
            and polygon_valid
            and polygon_matches_text
            and point_count >= 4
            and part_count == 1
            and cell_info.size == 2
        ),
        "geometry_hdf": str(geometry_hdf),
        "flow_area_name": flow_area_name,
        "compiled_names": names,
        "exact_name_match_count": len(matches),
        "feature_index": index,
        "cell_count": cell_count,
        "cell_info": cell_info.tolist(),
        "spacing_dx": float(row["Spacing dx"]),
        "spacing_dy": float(row["Spacing dy"]),
        "point_start": point_start,
        "point_count": point_count,
        "part_start": part_start,
        "part_count": part_count,
        "parts": parts.tolist(),
        "polygon_valid": polygon_valid,
        "polygon_matches_text": polygon_matches_text,
        "polygon_bounds": (
            list(compiled_polygon.bounds) if compiled_polygon is not None else None
        ),
        "polygon_points": points.tolist(),
        "polygon_points_sha256": hashlib.sha256(
            points.tobytes(order="C")
        ).hexdigest(),
        "feature_row_sha256": hashlib.sha256(row.tobytes()).hexdigest(),
        "missing_datasets": missing,
    }


def geometry_area_or_perimeter(
    context: Mapping[str, Any],
    flow_area_name: str,
    coordinates: Sequence[Sequence[float]],
    geometry: Optional[Union[str, Path]] = None,
    point_generation_data: Optional[Union[str, Sequence[Optional[float]]]] = None,
    compile_with_mapper: bool = True,
    preprocess_plan_number: Optional[Union[str, int]] = None,
    preprocess_max_wait: int = 600,
    expected_compiled_cell_count: Optional[int] = 0,
    **_: Any,
) -> Dict[str, Any]:
    """Create/edit a 2D perimeter and compile it into RAS Mapper geometry.

    Full HEC-RAS plan preprocessing is the supported bridge from ``.g##`` text
    to the global RAS Mapper 2D-area feature tables. Initial mesh generation is
    intentionally a separate qualification action.
    """
    from .geom import GeomStorage

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    before_sha = RasQualification.file_sha256(geom_path)
    before_areas = GeomStorage.get_storage_areas(geom_path, exclude_2d=False)
    before_names = (
        sorted(str(value) for value in before_areas["Name"].tolist())
        if not before_areas.empty and "Name" in before_areas
        else []
    )
    output = GeomStorage.set_2d_flow_area_perimeter(
        geom_path,
        flow_area_name=flow_area_name,
        coordinates=coordinates,
        point_generation_data=point_generation_data,
        recompute_centroid=True,
    )
    after_areas = GeomStorage.get_storage_areas(geom_path, exclude_2d=False)
    area_columns = [
        column
        for column in ("Storage Area", "Name", "storage_area_name")
        if column in after_areas
    ]
    names = (
        sorted(str(value) for value in after_areas[area_columns[0]].tolist())
        if area_columns
        else []
    )
    after_sha = RasQualification.file_sha256(geom_path)
    operation_id = str(context.get("operation_id", ""))
    existed_before = flow_area_name in before_names
    semantic_match = (
        (operation_id == "geometry.2d_area_create" and not existed_before)
        or (operation_id == "geometry.perimeter_edit" and existed_before)
        or operation_id not in {"geometry.2d_area_create", "geometry.perimeter_edit"}
    )
    polygons = GeomStorage.get_storage_area_polygons(
        geom_path,
        exclude_2d=False,
    )
    polygon_rows = polygons[polygons["Name"].astype(str) == str(flow_area_name)]
    text_polygon = polygon_rows.geometry.iloc[0] if len(polygon_rows) == 1 else None
    text_polygon_valid = bool(
        text_polygon is not None
        and not text_polygon.is_empty
        and text_polygon.is_valid
        and text_polygon.area > 0
    )

    preprocess_result = None
    preprocess_record = None
    compiled_feature = None
    timestamp_sync = None
    geometry_receipt = None
    selected_area = None
    plan_geometry_matches = not compile_with_mapper
    compiled_cell_count_matches = not compile_with_mapper
    mapper_reopen_passed = not compile_with_mapper
    if compile_with_mapper:
        from .RasPreprocess import RasPreprocess
        from .geom.GeomMesh import _synchronize_persisted_hdf_mtime

        requested_plan = preprocess_plan_number or context.get(
            "qualification_plan_number"
        )
        if requested_plan is None:
            raise ValueError(
                "preprocess_plan_number is required when "
                "compile_with_mapper=True"
            )
        plan_number = _plan_number(project, requested_plan)
        plan_rows = project.plan_df[
            project.plan_df["plan_number"].astype(str).str.zfill(2)
            == str(plan_number).zfill(2)
        ]
        plan_geometry_reference = (
            str(plan_rows.iloc[0].get("Geom File", ""))
            if len(plan_rows) == 1
            else ""
        )
        geometry_number = geom_path.suffix.lower().removeprefix(".g")
        plan_geometry_match = re.search(r"(\d+)\s*$", plan_geometry_reference)
        plan_geometry_matches = bool(
            len(plan_rows) == 1
            and plan_geometry_match is not None
            and int(plan_geometry_match.group(1)) == int(geometry_number)
        )
        if not plan_geometry_matches:
            raise ValueError(
                f"plan p{plan_number} does not reference {geom_path.name}"
            )
        preprocess_result = RasPreprocess.preprocess_plan(
            plan_number,
            ras_object=project,
            max_wait=int(preprocess_max_wait),
            clear_existing=True,
            fix_line_endings=False,
        )
        preprocess_record = _object_dict(preprocess_result)
        hdf_path = _geometry_hdf(geom_path)
        if bool(preprocess_result) and hdf_path.is_file():
            compiled_feature = _compiled_2d_area_feature_receipt(
                hdf_path,
                flow_area_name,
                text_polygon,
            )
            compiled_cell_count_matches = bool(
                expected_compiled_cell_count is None
                or compiled_feature.get("cell_count")
                == int(expected_compiled_cell_count)
            )
            if compiled_feature.get("passed") is True:
                timestamp_sync = _synchronize_persisted_hdf_mtime(
                    geom_path,
                    hdf_path,
                )
                geometry_receipt = RasQualification.geometry_receipt(hdf_path)
                selected_area = geometry_receipt["areas"].get(
                    str(flow_area_name)
                )
        mapper_reopen_passed = bool(
            preprocess_result
            and compiled_feature is not None
            and compiled_feature.get("passed") is True
            and compiled_cell_count_matches
            and timestamp_sync is not None
            and timestamp_sync.get("verified") is True
        )
    evidence = {
        "geometry": str(geom_path),
        "flow_area_name": flow_area_name,
        "coordinate_count": len(coordinates),
        "existed_before": existed_before,
        "area_names_after": names,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "geometry_changed": before_sha != after_sha,
        "backup": str(output),
        "text_polygon_valid": text_polygon_valid,
        "text_perimeter_bounds": (
            list(text_polygon.bounds) if text_polygon is not None else None
        ),
        "compile_with_mapper": bool(compile_with_mapper),
        "preprocess_plan_number": (
            str(preprocess_plan_number).zfill(2)
            if preprocess_plan_number is not None
            else None
        ),
        "preprocess_result": preprocess_record,
        "plan_geometry_matches": plan_geometry_matches,
        "compiled_feature": compiled_feature,
        "expected_compiled_cell_count": expected_compiled_cell_count,
        "compiled_cell_count_matches": compiled_cell_count_matches,
        "timestamp_sync": timestamp_sync,
        "mapper_reopen_passed": mapper_reopen_passed,
        "selected_area": selected_area,
        "mesh_generation_owned_by_separate_action": True,
    }
    returned = {
        "passed": bool(
            semantic_match
            and flow_area_name in names
            and len(coordinates) >= 3
            and before_sha != after_sha
            and text_polygon_valid
            and mapper_reopen_passed
        ),
        "evidence": evidence,
    }
    if geometry_receipt is not None:
        returned["artifacts"] = {"geometry": geometry_receipt}
    if compile_with_mapper and mapper_reopen_passed:
        returned["context_updates"] = {
            "qualification_geometry_text": str(geom_path),
            "qualification_geometry_hdf": str(_geometry_hdf(geom_path)),
            "qualification_plan_number": str(plan_number).zfill(2),
        }
    return returned


def _geometry_text_seed_receipt(
    geom_path: Path,
    mesh_name: str,
) -> Dict[str, Any]:
    """Inspect one packed ``Storage Area 2D Points`` text block."""
    lines = geom_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    current_area: Optional[str] = None
    for index, line in enumerate(lines):
        if line.startswith("Storage Area="):
            current_area = line.split("=", 1)[1].split(",", 1)[0].strip()
            continue
        if not (
            line.startswith("Storage Area 2D Points=")
            and current_area == mesh_name
        ):
            continue
        try:
            declared_count = int(line.split("=", 1)[1].strip())
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"Invalid Storage Area 2D Points header for {mesh_name}"
            ) from exc
        packed_lines = lines[index + 1 : index + 1 + (declared_count + 1) // 2]
        values: list[float] = []
        invalid_chunks = 0
        for packed_line in packed_lines:
            raw = packed_line.rstrip("\r\n")
            for offset in range(0, len(raw), 16):
                chunk = raw[offset : offset + 16].strip()
                if not chunk:
                    continue
                try:
                    values.append(float(chunk))
                except ValueError:
                    invalid_chunks += 1
        block = line + "".join(packed_lines)
        return {
            "mesh_name": mesh_name,
            "declared_count": declared_count,
            "coordinate_count": len(values) // 2,
            "packed_line_count": len(packed_lines),
            "invalid_chunks": invalid_chunks,
            "block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
            "coordinate_values_sha256": hashlib.sha256(
                json.dumps(
                    values,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        }
    raise ValueError(
        f"Storage Area 2D Points block not found for {mesh_name}: {geom_path}"
    )


def mesh_generate(
    context: Mapping[str, Any],
    geometry: Optional[Union[str, Path]] = None,
    mesh_name: Optional[str] = None,
    mesh_index: int = 0,
    cell_size: Optional[float] = None,
    breakline_near: Optional[float] = None,
    breakline_far: Optional[float] = None,
    near_repeats: Optional[int] = None,
    protection_radius: Optional[int] = None,
    min_face_length_ratio: float = 0.05,
    max_iterations: int = 8,
    seed_generation_mode: str = "regenerate_then_fallback",
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 600.0,
    managed_host_max_attempts: int = 3,
    managed_host_attempt_timeout_seconds: Optional[float] = None,
    managed_host_persistence_mode: str = "auto",
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    expected_topology_fingerprint: Optional[str] = None,
    expected_ordered_center_fingerprint: Optional[str] = None,
    expected_ordered_face_fingerprint: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Generate or regenerate a mesh through RasMapperLib and inspect its HDF."""
    from .geom import GeomMesh

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    result = GeomMesh.generate(
        geom_path,
        mesh_name=mesh_name,
        mesh_index=int(mesh_index),
        cell_size=cell_size,
        bl_spacing_near=breakline_near,
        bl_spacing_far=breakline_far,
        near_repeats=near_repeats,
        protection_radius=protection_radius,
        min_face_length_ratio=float(min_face_length_ratio),
        max_iterations=int(max_iterations),
        seed_generation_mode=seed_generation_mode,
        interop_backend=interop_backend,
        managed_host_timeout_seconds=float(managed_host_timeout_seconds),
        managed_host_max_attempts=int(managed_host_max_attempts),
        managed_host_attempt_timeout_seconds=(
            float(managed_host_attempt_timeout_seconds)
            if managed_host_attempt_timeout_seconds is not None
            else None
        ),
        managed_host_persistence_mode=managed_host_persistence_mode,
        managed_host_expected_cell_count=expected_cell_count,
        managed_host_expected_face_count=expected_face_count,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
    )
    result_record = _object_dict(result)
    if not bool(result):
        return {
            "passed": False,
            "evidence": {"mesh_result": result_record},
            "diagnostics": {"mesh_result": result_record},
        }

    geom_receipt = RasQualification.geometry_receipt(_geometry_hdf(geom_path))
    selected_name = str(result.mesh_name)
    selected = geom_receipt["areas"].get(selected_name)
    managed_backend = result.interop_backend == "managed_host"
    managed_text_persistence = managed_backend and not result.hdf_persisted
    text_seed_receipt = (
        _geometry_text_seed_receipt(geom_path, selected_name)
        if managed_backend
        else None
    )
    if managed_text_persistence:
        count_checks = {
            "result_matches_text_seed_count": (
                text_seed_receipt["declared_count"] == int(result.cell_count)
            ),
            "text_seed_block_complete": (
                text_seed_receipt["coordinate_count"] == int(result.cell_count)
            ),
            "hdf_persistence_deferred_to_preprocess": True,
            "expected_cells": expected_cell_count is None
            or int(result.cell_count) == int(expected_cell_count),
            "expected_faces": expected_face_count is None
            or int(result.face_count) == int(expected_face_count),
        }
        if any(
            value is not None
            for value in (
                expected_topology_fingerprint,
                expected_ordered_center_fingerprint,
                expected_ordered_face_fingerprint,
            )
        ):
            # Text seed persistence proves the generated center count, but it
            # cannot prove the persisted face topology or semantic HDF
            # fingerprints.  Those expectations must never pass merely because
            # preprocessing was deferred; a later plan.preprocess action can
            # qualify the materialized HDF content instead.
            count_checks.update(
                {
                    "mesh_topology_complete": False,
                    "topology_fingerprint_exact": (
                        expected_topology_fingerprint is None
                    ),
                    "ordered_center_fingerprint_exact": (
                        expected_ordered_center_fingerprint is None
                    ),
                    "ordered_face_fingerprint_exact": (
                        expected_ordered_face_fingerprint is None
                    ),
                    "mesh_quality_complete": False,
                }
            )
    else:
        count_checks = {
            "result_matches_hdf_cells": bool(
                selected and selected["cell_count"] == int(result.cell_count)
            ),
            "result_matches_hdf_faces": bool(
                selected and selected["face_count"] == int(result.face_count)
            ),
            "expected_cells": expected_cell_count is None
            or int(result.cell_count) == int(expected_cell_count),
            "expected_faces": expected_face_count is None
            or int(result.face_count) == int(expected_face_count),
        }
        if managed_backend:
            count_checks["managed_hdf_persisted"] = bool(result.hdf_persisted)
            # The transactional helper explicitly reopens and validates its
            # candidate before replacement. The vendor legacy Save() path does
            # not emit separate reopened counts; its persisted content is
            # independently checked by geometry_receipt above.
            if result.hdf_persistence_mode == "transactional_direct":
                count_checks.update(
                    {
                        "managed_reopened_cells_exact": (
                            int(result.persisted_cell_count)
                            == int(result.cell_count)
                        ),
                        "managed_reopened_faces_exact": (
                            int(result.persisted_face_count)
                            == int(result.face_count)
                        ),
                    }
                )
        if any(
            value is not None
            for value in (
                expected_topology_fingerprint,
                expected_ordered_center_fingerprint,
                expected_ordered_face_fingerprint,
            )
        ):
            topology = selected.get("mesh_topology") if selected else None
            quality = selected.get("quality") if selected else None
            components = topology.get("components") if isinstance(topology, Mapping) else {}
            count_checks.update(
                {
                    "mesh_topology_complete": bool(
                        isinstance(topology, Mapping)
                        and topology.get("complete") is True
                    ),
                    "topology_fingerprint_exact": bool(
                        expected_topology_fingerprint is None
                        or isinstance(topology, Mapping)
                        and topology.get("fingerprint")
                        == str(expected_topology_fingerprint).lower()
                    ),
                    "ordered_center_fingerprint_exact": bool(
                        expected_ordered_center_fingerprint is None
                        or (
                            components.get("ordered_nonvirtual_centers") or {}
                        ).get("fingerprint")
                        == str(expected_ordered_center_fingerprint).lower()
                    ),
                    "ordered_face_fingerprint_exact": bool(
                        expected_ordered_face_fingerprint is None
                        or (
                            components.get("ordered_faces_and_indexes") or {}
                        ).get("fingerprint")
                        == str(expected_ordered_face_fingerprint).lower()
                    ),
                    "mesh_quality_complete": bool(
                        isinstance(quality, Mapping)
                        and int(quality.get("invalid_cell_count", -1)) == 0
                        and int((quality.get("cell_area") or {}).get("count", -1))
                        == int(result.cell_count)
                        and int(
                            (quality.get("cell_aspect_ratio") or {}).get(
                                "count", -1
                            )
                        )
                        == int(result.cell_count)
                        and int((quality.get("face_length") or {}).get("count", -1))
                        == int(result.face_count)
                    ),
                }
            )
    evidence = {
        "mesh_result": result_record,
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "expected_topology_fingerprint": expected_topology_fingerprint,
        "expected_ordered_center_fingerprint": (
            expected_ordered_center_fingerprint
        ),
        "expected_ordered_face_fingerprint": expected_ordered_face_fingerprint,
        "count_checks": count_checks,
        "persistence_mode": (
            "geometry_text_then_preprocess"
            if managed_text_persistence
            else "transactional_rasmapper_hdf"
            if managed_backend and result.hdf_persisted
            else "rasmapper_hdf"
        ),
        "text_seed_receipt": text_seed_receipt,
        "hdf_count_observation": {
            "cell_count": selected.get("cell_count") if selected else None,
            "face_count": selected.get("face_count") if selected else None,
            "matches_generated_mesh": bool(
                selected
                and selected.get("cell_count") == int(result.cell_count)
                and selected.get("face_count") == int(result.face_count)
            ),
        },
        "geometry_fingerprint": geom_receipt["geometry_fingerprint"],
        "geometry_file_sha256": geom_receipt["file_sha256"],
        "selected_area": selected,
        "boundary_assignments": geom_receipt["boundary_assignments"],
        "breakline_count": geom_receipt["breakline_count"],
        "refinement_region_count": geom_receipt["refinement_region_count"],
    }
    return {
        "passed": bool(all(count_checks.values())),
        "evidence": evidence,
        "artifacts": {"geometry": geom_receipt},
        "context_updates": {
            "qualification_geometry_text": str(geom_path),
            "qualification_geometry_hdf": str(_geometry_hdf(geom_path)),
        },
    }


def mesh_refinement_region(
    context: Mapping[str, Any],
    polygon: Sequence[Sequence[float]],
    spacing_dx: float,
    spacing_dy: Optional[float] = None,
    name: str = "Qualification refinement",
    geometry: Optional[Union[str, Path]] = None,
    regenerate: bool = True,
    mesh_name: Optional[str] = None,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    minimum_cell_count_delta: int = 1,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 600.0,
    managed_host_max_attempts: int = 3,
    managed_host_attempt_timeout_seconds: Optional[float] = None,
    managed_host_persistence_mode: str = "auto",
    baseline_expected_cell_count: Optional[int] = None,
    baseline_expected_face_count: Optional[int] = None,
    **mesh_parameters: Any,
) -> Dict[str, Any]:
    """Add a product-readable region and verify its exact mesh effect.

    Native Windows persists and reloads the region through ``MeshRegions``.
    Under Wine the complete HDF schema is written first, then the isolated
    managed host must reload the exact record through RasMapperLib and use it
    during seed generation. This avoids the non-returning Wine feature-layer
    save path without accepting raw HDF structure as qualification evidence.
    """
    from .geom import GeomMesh
    from .native.mesh_host import is_wine_runtime

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    geom_hdf = _geometry_hdf(geom_path)
    hecras_dir = Path(str(context["ras_executable"])).parent
    backend = str(interop_backend).strip().lower()
    if backend not in {"auto", "pythonnet", "managed_host"}:
        raise ValueError(
            "interop_backend must be 'auto', 'pythonnet', or 'managed_host'"
        )
    managed_backend = backend == "managed_host" or (
        backend == "auto" and is_wine_runtime()
    )
    persistence_mode = str(managed_host_persistence_mode).strip().lower()
    transactional_direct = persistence_mode == "transactional_direct"
    if managed_backend and not regenerate:
        raise ValueError(
            "Wine refinement-region qualification requires regenerate=True "
            "so RasMapperLib can reload and exercise the persisted region."
        )
    if transactional_direct:
        if not managed_backend:
            raise ValueError(
                "transactional_direct refinement qualification requires the "
                "managed_host backend"
            )
        exact_counts = {
            "baseline_expected_cell_count": baseline_expected_cell_count,
            "baseline_expected_face_count": baseline_expected_face_count,
            "expected_cell_count": expected_cell_count,
            "expected_face_count": expected_face_count,
        }
        missing = [name for name, value in exact_counts.items() if value is None]
        if missing:
            raise ValueError(
                "transactional_direct refinement qualification requires exact "
                f"baseline and final counts; missing {', '.join(missing)}"
            )
        nonpositive = [
            name for name, value in exact_counts.items() if int(value) <= 0
        ]
        if nonpositive:
            raise ValueError(
                "transactional_direct refinement counts must be positive; "
                f"invalid {', '.join(nonpositive)}"
            )

    before = GeomMesh.get_refinement_regions(
        geom_path, hecras_dir=hecras_dir, ras_object=project
    )
    mapper_before = (
        None
        if managed_backend
        else GeomMesh.get_refinement_regions_mapper(
            geom_path, hecras_dir=hecras_dir, ras_object=project
        )
    )
    prechange_receipt = RasQualification.geometry_receipt(geom_hdf)
    prechange_text_sha256 = RasQualification.file_sha256(geom_path)
    prechange_text_seed_receipt = None
    if managed_backend and mesh_name is not None:
        try:
            prechange_text_seed_receipt = _geometry_text_seed_receipt(
                geom_path, str(mesh_name)
            )
        except ValueError:
            prechange_text_seed_receipt = None

    hdf_backup = geom_hdf.with_name(
        f".{geom_hdf.name}.rasq-refinement-{uuid.uuid4().hex}.bak"
    )
    text_backup = geom_path.with_name(
        f".{geom_path.name}.rasq-refinement-{uuid.uuid4().hex}.bak"
    )
    shutil.copy2(geom_hdf, hdf_backup)
    shutil.copy2(geom_path, text_backup)
    rolled_back = False
    attempted_receipt = None
    generated = None
    baseline_generated = None
    baseline_receipt = None
    baseline_text_seed_receipt = None
    fid = -1
    after = before
    mapper_after = mapper_before
    count_checks: Dict[str, bool] = {}
    cell_delta = None
    text_seed_receipt = None

    def restore_prechange_files() -> None:
        nonlocal rolled_back
        shutil.copy2(hdf_backup, geom_hdf)
        shutil.copy2(text_backup, geom_path)
        rolled_back = True

    generation_parameters = {
        key: value
        for key, value in mesh_parameters.items()
        if key
        in {
            "cell_size",
            "min_face_length_ratio",
            "max_iterations",
            "near_repeats",
            "protection_radius",
            "seed_generation_mode",
        }
    }

    def generate_current_mesh(
        *,
        transactional_expected_cell_count: Optional[int] = None,
        transactional_expected_face_count: Optional[int] = None,
    ):
        generate_kwargs = {
            "interop_backend": backend,
            "managed_host_timeout_seconds": float(managed_host_timeout_seconds),
            "managed_host_max_attempts": int(managed_host_max_attempts),
            "managed_host_attempt_timeout_seconds": (
                float(managed_host_attempt_timeout_seconds)
                if managed_host_attempt_timeout_seconds is not None
                else None
            ),
            "managed_host_persistence_mode": persistence_mode,
        }
        if transactional_direct:
            generate_kwargs.update(
                {
                    "managed_host_expected_cell_count": (
                        transactional_expected_cell_count
                    ),
                    "managed_host_expected_face_count": (
                        transactional_expected_face_count
                    ),
                }
            )
        return GeomMesh.generate(
            geom_path,
            mesh_name=mesh_name,
            hecras_dir=hecras_dir,
            ras_object=project,
            **generation_parameters,
            **generate_kwargs,
        )

    try:
        if managed_backend:
            baseline_generated = generate_current_mesh(
                transactional_expected_cell_count=baseline_expected_cell_count,
                transactional_expected_face_count=baseline_expected_face_count,
            )
            if not bool(baseline_generated):
                raise RuntimeError(
                    "Managed RasMapper host could not establish the baseline "
                    f"mesh: {baseline_generated.error_message}"
                )
            if transactional_direct:
                baseline_receipt = RasQualification.geometry_receipt(geom_hdf)
            baseline_text_seed_receipt = _geometry_text_seed_receipt(
                geom_path, str(baseline_generated.mesh_name)
            )
        fid = GeomMesh.add_refinement_region(
            geom_path,
            polygon=polygon,
            spacing_dx=float(spacing_dx),
            spacing_dy=float(spacing_dy) if spacing_dy is not None else None,
            name=name,
            mesh_name=mesh_name,
            hecras_dir=hecras_dir,
            ras_object=project,
            use_rasmapper=not managed_backend,
            _require_current_hdf=not managed_backend,
        )
        after = GeomMesh.get_refinement_regions(
            geom_path, hecras_dir=hecras_dir, ras_object=project
        )
        if not managed_backend:
            mapper_after = GeomMesh.get_refinement_regions_mapper(
                geom_path, hecras_dir=hecras_dir, ras_object=project
            )
        if regenerate:
            generated = generate_current_mesh(
                transactional_expected_cell_count=expected_cell_count,
                transactional_expected_face_count=expected_face_count,
            )
        if managed_backend:
            mapper_after = (
                list(generated.product_refinement_regions)
                if generated is not None
                else []
            )
        attempted_receipt = RasQualification.geometry_receipt(geom_hdf)
        selected_name = (
            str(generated.mesh_name)
            if generated is not None and hasattr(generated, "mesh_name")
            else mesh_name
        )
        before_area = (
            (baseline_receipt or prechange_receipt)["areas"].get(selected_name)
            if selected_name is not None
            else None
        )
        after_area = (
            attempted_receipt["areas"].get(selected_name)
            if selected_name is not None
            else None
        )
        if managed_backend and generated is not None:
            baseline_cell_count = (
                int(baseline_generated.cell_count)
                if baseline_generated is not None
                else int(prechange_text_seed_receipt["declared_count"])
                if prechange_text_seed_receipt is not None
                else int(before_area["cell_count"])
                if before_area is not None
                else None
            )
            cell_delta = (
                int(generated.cell_count) - baseline_cell_count
                if baseline_cell_count is not None
                else None
            )
            text_seed_receipt = _geometry_text_seed_receipt(
                geom_path, str(generated.mesh_name)
            )
        else:
            cell_delta = (
                int(after_area["cell_count"]) - int(before_area["cell_count"])
                if before_area is not None and after_area is not None
                else None
            )

        product_regions = list(mapper_after or [])
        transactional_managed = managed_backend and transactional_direct
        if transactional_managed:
            expected_cells_match = bool(
                generated is not None
                and after_area is not None
                and int(generated.cell_count) == int(expected_cell_count)
                and int(after_area["cell_count"]) == int(expected_cell_count)
            )
            expected_faces_match = bool(
                generated is not None
                and after_area is not None
                and int(generated.face_count) == int(expected_face_count)
                and int(after_area["face_count"]) == int(expected_face_count)
            )
        else:
            expected_cells_match = bool(
                expected_cell_count is None
                or managed_backend
                and generated is not None
                and int(generated.cell_count) == int(expected_cell_count)
                or not managed_backend
                and after_area is not None
                and int(after_area["cell_count"]) == int(expected_cell_count)
            )
            expected_faces_match = bool(
                expected_face_count is None
                or managed_backend
                and generated is not None
                and int(generated.face_count) == int(expected_face_count)
                or not managed_backend
                and after_area is not None
                and int(after_area["face_count"]) == int(expected_face_count)
            )
        count_checks = {
            "hdf_region_added": len(after) == len(before) + 1,
            "rasmapper_region_added": (
                len(product_regions) == len(before) + 1
                if managed_backend
                else len(product_regions) == len(mapper_before or []) + 1
            ),
            "hdf_and_rasmapper_region_counts_match": (
                len(after) == len(product_regions)
            ),
            "rasmapper_region_content_matches": any(
                item["fid"] == fid
                and item["name"] == name
                and math.isclose(
                    item["spacing_dx"], float(spacing_dx), abs_tol=1e-5
                )
                and math.isclose(
                    item["spacing_dy"],
                    float(spacing_dy if spacing_dy is not None else spacing_dx),
                    abs_tol=1e-5,
                )
                and item["point_count"] >= 4
                for item in product_regions
            ),
            "mesh_regenerated": not regenerate or bool(generated),
            "minimum_cell_count_delta": (
                not regenerate
                or cell_delta is not None
                and cell_delta >= int(minimum_cell_count_delta)
            ),
            "expected_cells": expected_cells_match,
            "expected_faces": expected_faces_match,
        }
        if managed_backend:
            if transactional_managed:
                count_checks.update(
                    {
                        "baseline_persistence_mode_exact": bool(
                            baseline_generated is not None
                            and baseline_generated.hdf_persistence_mode
                            == "transactional_direct"
                        ),
                        "baseline_hdf_persisted": bool(
                            baseline_generated is not None
                            and baseline_generated.hdf_persisted
                        ),
                        "baseline_reopened_cells_exact": bool(
                            baseline_generated is not None
                            and int(baseline_generated.persisted_cell_count)
                            == int(baseline_generated.cell_count)
                        ),
                        "baseline_reopened_faces_exact": bool(
                            baseline_generated is not None
                            and int(baseline_generated.persisted_face_count)
                            == int(baseline_generated.face_count)
                        ),
                        "baseline_expected_cells": bool(
                            baseline_generated is not None
                            and int(baseline_generated.cell_count)
                            == int(baseline_expected_cell_count)
                        ),
                        "baseline_expected_faces": bool(
                            baseline_generated is not None
                            and int(baseline_generated.face_count)
                            == int(baseline_expected_face_count)
                        ),
                        "baseline_matches_prechange_hdf_cells": bool(
                            baseline_generated is not None
                            and before_area is not None
                            and int(before_area["cell_count"])
                            == int(baseline_generated.cell_count)
                        ),
                        "baseline_matches_prechange_hdf_faces": bool(
                            baseline_generated is not None
                            and before_area is not None
                            and int(before_area["face_count"])
                            == int(baseline_generated.face_count)
                        ),
                        "managed_persistence_mode_exact": bool(
                            generated is not None
                            and generated.hdf_persistence_mode
                            == "transactional_direct"
                        ),
                        "managed_hdf_persisted": bool(
                            generated is not None and generated.hdf_persisted
                        ),
                        "managed_reopened_cells_exact": bool(
                            generated is not None
                            and int(generated.persisted_cell_count)
                            == int(generated.cell_count)
                        ),
                        "managed_reopened_faces_exact": bool(
                            generated is not None
                            and int(generated.persisted_face_count)
                            == int(generated.face_count)
                        ),
                        "result_matches_hdf_cells": bool(
                            generated is not None
                            and after_area is not None
                            and int(after_area["cell_count"])
                            == int(generated.cell_count)
                        ),
                        "result_matches_hdf_faces": bool(
                            generated is not None
                            and after_area is not None
                            and int(after_area["face_count"])
                            == int(generated.face_count)
                        ),
                    }
                )
                final_topology = _selected_mesh_topology_evidence(
                    attempted_receipt,
                    selected_name,
                )
                count_checks.update(
                    _transactional_mesh_topology_checks(
                        final_topology,
                        expected_cell_count=int(expected_cell_count),
                        expected_face_count=int(expected_face_count),
                    )
                )
            else:
                count_checks.update(
                    {
                        "result_matches_text_seed_count": bool(
                            generated is not None
                            and text_seed_receipt is not None
                            and text_seed_receipt["declared_count"]
                            == int(generated.cell_count)
                        ),
                        "text_seed_block_complete": bool(
                            generated is not None
                            and text_seed_receipt is not None
                            and text_seed_receipt["coordinate_count"]
                            == int(generated.cell_count)
                        ),
                        "mesh_hdf_persistence_deferred_to_preprocess": True,
                    }
                )
        if not all(count_checks.values()):
            restore_prechange_files()
    except Exception:
        restore_prechange_files()
        raise
    finally:
        hdf_backup.unlink(missing_ok=True)
        text_backup.unlink(missing_ok=True)

    receipt = RasQualification.geometry_receipt(geom_hdf)
    selected_name = (
        str(generated.mesh_name)
        if generated is not None and hasattr(generated, "mesh_name")
        else mesh_name
    )
    final_mesh_topology = _selected_mesh_topology_evidence(receipt, selected_name)
    baseline_mesh_topology = (
        _selected_mesh_topology_evidence(
            baseline_receipt,
            str(baseline_generated.mesh_name),
        )
        if baseline_receipt is not None and baseline_generated is not None
        else None
    )
    evidence = {
        "new_region_fid": int(fid),
        "regions_before": before,
        "regions_after": after,
        "rasmapper_regions_before": mapper_before,
        "rasmapper_regions_after": mapper_after,
        "mesh_result": _object_dict(generated) if generated is not None else None,
        "baseline_mesh_result": (
            _object_dict(baseline_generated)
            if baseline_generated is not None
            else None
        ),
        "persistence_mode": (
            "transactional_rasmapper_hdf"
            if managed_backend and transactional_direct
            else
            "complete_hdf_region_schema_product_reloaded_and_text_mesh"
            if managed_backend
            else "rasmapper_hdf"
        ),
        "prechange_text_seed_receipt": prechange_text_seed_receipt,
        "baseline_text_seed_receipt": baseline_text_seed_receipt,
        "text_seed_receipt": text_seed_receipt,
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "baseline_expected_cell_count": baseline_expected_cell_count,
        "baseline_expected_face_count": baseline_expected_face_count,
        "minimum_cell_count_delta_required": int(minimum_cell_count_delta),
        "count_checks": count_checks,
        "cell_count_delta": cell_delta,
        "final_mesh_topology": final_mesh_topology,
        "baseline_mesh_topology": baseline_mesh_topology,
        "geometry_fingerprint": receipt["geometry_fingerprint"],
        "refinement_region_count": receipt["refinement_region_count"],
        "prechange_geometry_fingerprint": prechange_receipt["geometry_fingerprint"],
        "attempted_geometry_fingerprint": (
            attempted_receipt["geometry_fingerprint"] if attempted_receipt else None
        ),
        "rolled_back_after_mapper_rejection": rolled_back,
        "rollback_restored_exact_geometry": bool(
            not rolled_back
            or receipt["file_sha256"] == prechange_receipt["file_sha256"]
        ),
        "rollback_restored_exact_text": bool(
            not rolled_back
            or RasQualification.file_sha256(geom_path) == prechange_text_sha256
        ),
    }
    return {
        "passed": bool(not rolled_back and count_checks and all(count_checks.values())),
        "evidence": evidence,
        "artifacts": {"geometry": receipt},
    }


def _mesh_breakline_create(
    context: Mapping[str, Any],
    *,
    geometry: Optional[Union[str, Path]],
    polyline: Sequence[Sequence[float]],
    name: str,
    near: float,
    far: float,
    near_repeats: int,
    protection_radius: int,
    mesh_name: Optional[str],
    expected_cell_count: Optional[int],
    expected_face_count: Optional[int],
    expected_ordered_center_fingerprint: Optional[str],
    expected_ordered_face_fingerprint: Optional[str],
    baseline_expected_cell_count: Optional[int],
    baseline_expected_face_count: Optional[int],
    minimum_cell_count_delta: int,
    interop_backend: str,
    managed_host_timeout_seconds: float,
    managed_host_max_attempts: int,
    managed_host_attempt_timeout_seconds: Optional[float],
    managed_host_persistence_mode: str,
    mesh_parameters: Mapping[str, Any],
) -> Dict[str, Any]:
    """Create, product-reload, and exercise one breakline transactionally."""
    from .geom import GeomMesh

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    geom_hdf = _geometry_hdf(geom_path)
    persistence_mode = str(managed_host_persistence_mode).strip().lower()
    transactional_direct = persistence_mode == "transactional_direct"
    if transactional_direct:
        exact_counts = {
            "baseline_expected_cell_count": baseline_expected_cell_count,
            "baseline_expected_face_count": baseline_expected_face_count,
            "expected_cell_count": expected_cell_count,
            "expected_face_count": expected_face_count,
        }
        missing = [key for key, value in exact_counts.items() if value is None]
        if missing:
            raise ValueError(
                "transactional_direct breakline creation requires exact "
                f"baseline and final counts; missing {', '.join(missing)}"
            )
        invalid = [key for key, value in exact_counts.items() if int(value) <= 0]
        if invalid:
            raise ValueError(
                "transactional_direct breakline counts must be positive; "
                f"invalid {', '.join(invalid)}"
            )

    before_spacing = GeomMesh.get_breakline_spacing(geom_path, ras_object=project)
    prechange_receipt = RasQualification.geometry_receipt(geom_hdf)
    prechange_text_sha256 = RasQualification.file_sha256(geom_path)
    text_snapshot = geom_path.with_name(
        f".{geom_path.name}.rasq-breakline-create-{uuid.uuid4().hex}.bak"
    )
    hdf_snapshot = geom_hdf.with_name(
        f".{geom_hdf.name}.rasq-breakline-create-{uuid.uuid4().hex}.bak"
    )
    shutil.copy2(geom_path, text_snapshot)
    shutil.copy2(geom_hdf, hdf_snapshot)
    rolled_back = False
    baseline_generated = None
    generated = None
    attempted_receipt = None
    new_fid = -1
    checks: Dict[str, bool] = {}
    cell_delta = None

    def restore() -> None:
        nonlocal rolled_back
        shutil.copy2(text_snapshot, geom_path)
        shutil.copy2(hdf_snapshot, geom_hdf)
        rolled_back = True

    generation_parameters = {
        key: value
        for key, value in mesh_parameters.items()
        if key
        in {
            "cell_size",
            "min_face_length_ratio",
            "max_iterations",
            "seed_generation_mode",
        }
    }

    def generate(
        expected_cells: Optional[int], expected_faces: Optional[int]
    ):
        kwargs = {
            "interop_backend": interop_backend,
            "managed_host_timeout_seconds": float(managed_host_timeout_seconds),
            "managed_host_max_attempts": int(managed_host_max_attempts),
            "managed_host_attempt_timeout_seconds": (
                float(managed_host_attempt_timeout_seconds)
                if managed_host_attempt_timeout_seconds is not None
                else None
            ),
            "managed_host_persistence_mode": persistence_mode,
        }
        if transactional_direct:
            kwargs.update(
                {
                    "managed_host_expected_cell_count": expected_cells,
                    "managed_host_expected_face_count": expected_faces,
                }
            )
        return GeomMesh.generate(
            geom_path,
            mesh_name=mesh_name,
            hecras_dir=Path(str(context["ras_executable"])).parent,
            ras_object=project,
            **generation_parameters,
            **kwargs,
        )

    try:
        baseline_generated = generate(
            baseline_expected_cell_count,
            baseline_expected_face_count,
        )
        if not bool(baseline_generated):
            raise RuntimeError(
                "Managed RAS Mapper host could not establish the baseline "
                f"mesh: {baseline_generated.error_message}"
            )
        if baseline_generated.interop_backend != "managed_host":
            raise RuntimeError(
                "Breakline creation qualification requires the managed host "
                "so product-layer constraint evidence is available."
            )
        baseline_constraints = int(
            baseline_generated.managed_host_receipt.get("constraint_count", -1)
        )
        new_fid = GeomMesh.add_breakline(
            geom_path,
            polyline,
            name=name,
            near=float(near),
            far=float(far),
            near_repeats=int(near_repeats),
            protection_radius=int(protection_radius),
            mesh_name=mesh_name,
            hecras_dir=Path(str(context["ras_executable"])).parent,
            ras_object=project,
            _require_current_hdf=transactional_direct,
        )
        generated = generate(expected_cell_count, expected_face_count)
        if not bool(generated):
            raise RuntimeError(
                "Managed RAS Mapper host could not regenerate with the new "
                f"breakline: {generated.error_message}"
            )
        attempted_receipt = RasQualification.geometry_receipt(geom_hdf)
        selected_area = attempted_receipt["areas"].get(str(generated.mesh_name))
        after_spacing = GeomMesh.get_breakline_spacing(
            geom_path, ras_object=project
        )
        selected_spacing = [
            item for item in after_spacing if int(item[0]) == int(new_fid)
        ]
        final_constraints = int(
            generated.managed_host_receipt.get("constraint_count", -1)
        )
        cell_delta = int(generated.cell_count) - int(
            baseline_generated.cell_count
        )
        checks = {
            "breakline_fid_appended": int(new_fid) == len(before_spacing),
            "breakline_count_incremented": int(
                attempted_receipt["breakline_count"]
            )
            == int(prechange_receipt["breakline_count"]) + 1,
            "text_breakline_content_exact": bool(
                len(selected_spacing) == 1
                and selected_spacing[0][1:] == (
                    str(name),
                    float(near),
                    float(far),
                    int(near_repeats),
                    int(protection_radius),
                )
            ),
            "rasmapper_constraint_count_incremented": (
                baseline_constraints >= 0
                and final_constraints == baseline_constraints + 1
            ),
            "mesh_regenerated": True,
            "minimum_cell_count_delta": (
                cell_delta >= int(minimum_cell_count_delta)
            ),
            "expected_cells": (
                expected_cell_count is None
                or int(generated.cell_count) == int(expected_cell_count)
            ),
            "expected_faces": (
                expected_face_count is None
                or int(generated.face_count) == int(expected_face_count)
            ),
        }
        if transactional_direct:
            checks.update(
                {
                    "baseline_expected_cells": int(
                        baseline_generated.cell_count
                    )
                    == int(baseline_expected_cell_count),
                    "baseline_expected_faces": int(
                        baseline_generated.face_count
                    )
                    == int(baseline_expected_face_count),
                    "baseline_hdf_persisted": bool(
                        baseline_generated.hdf_persisted
                    ),
                    "managed_hdf_persisted": bool(generated.hdf_persisted),
                    "result_matches_hdf_cells": bool(
                        selected_area is not None
                        and int(selected_area["cell_count"])
                        == int(generated.cell_count)
                    ),
                    "result_matches_hdf_faces": bool(
                        selected_area is not None
                        and int(selected_area["face_count"])
                        == int(generated.face_count)
                    ),
                }
            )
            topology = _selected_mesh_topology_evidence(
                attempted_receipt,
                str(generated.mesh_name),
            )
            checks.update(
                _transactional_mesh_topology_checks(
                    topology,
                    expected_cell_count=int(expected_cell_count),
                    expected_face_count=int(expected_face_count),
                )
            )
            checks.update(
                {
                    "ordered_center_fingerprint_exact": bool(
                        expected_ordered_center_fingerprint is None
                        or topology.get("ordered_center_fingerprint")
                        == str(expected_ordered_center_fingerprint).lower()
                    ),
                    "ordered_face_fingerprint_exact": bool(
                        expected_ordered_face_fingerprint is None
                        or topology.get("ordered_face_index_fingerprint")
                        == str(expected_ordered_face_fingerprint).lower()
                    ),
                }
            )
        else:
            seed_receipt = _geometry_text_seed_receipt(
                geom_path, str(generated.mesh_name)
            )
            checks.update(
                {
                    "result_matches_text_seed_count": (
                        int(seed_receipt["declared_count"])
                        == int(generated.cell_count)
                    ),
                    "text_seed_block_complete": (
                        int(seed_receipt["coordinate_count"])
                        == int(generated.cell_count)
                    ),
                    "hdf_persistence_deferred_to_preprocess": True,
                }
            )
        if not all(checks.values()):
            restore()
    except Exception:
        restore()
        raise
    finally:
        text_snapshot.unlink(missing_ok=True)
        hdf_snapshot.unlink(missing_ok=True)

    receipt = RasQualification.geometry_receipt(geom_hdf)
    evidence = {
        "created": True,
        "breakline_fid": int(new_fid),
        "breakline_name": str(name),
        "spacing_before": before_spacing,
        "spacing_after": GeomMesh.get_breakline_spacing(
            geom_path, ras_object=project
        ),
        "baseline_mesh_result": _object_dict(baseline_generated),
        "mesh_result": _object_dict(generated),
        "minimum_cell_count_delta_required": int(minimum_cell_count_delta),
        "expected_ordered_center_fingerprint": (
            str(expected_ordered_center_fingerprint)
            if expected_ordered_center_fingerprint is not None
            else None
        ),
        "expected_ordered_face_fingerprint": (
            str(expected_ordered_face_fingerprint)
            if expected_ordered_face_fingerprint is not None
            else None
        ),
        "cell_count_delta": cell_delta,
        "count_checks": checks,
        "geometry_fingerprint": receipt["geometry_fingerprint"],
        "prechange_geometry_fingerprint": prechange_receipt[
            "geometry_fingerprint"
        ],
        "prechange_text_sha256": prechange_text_sha256,
        "breakline_count": receipt["breakline_count"],
        "rolled_back_after_mapper_rejection": rolled_back,
        "rollback_restored_exact_geometry": bool(
            not rolled_back
            or receipt["file_sha256"] == prechange_receipt["file_sha256"]
        ),
        "rollback_restored_exact_text": bool(
            not rolled_back
            or RasQualification.file_sha256(geom_path)
            == prechange_text_sha256
        ),
    }
    return {
        "passed": bool(not rolled_back and checks and all(checks.values())),
        "evidence": evidence,
        "artifacts": {"geometry": receipt},
    }


def mesh_breakline(
    context: Mapping[str, Any],
    geometry: Optional[Union[str, Path]] = None,
    breakline_fid: int = 0,
    polyline: Optional[Sequence[Sequence[float]]] = None,
    name: str = "Qualification breakline",
    near: Optional[float] = None,
    far: Optional[float] = None,
    near_repeats: Optional[int] = None,
    protection_radius: Optional[int] = None,
    regenerate: bool = True,
    mesh_name: Optional[str] = None,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    expected_ordered_center_fingerprint: Optional[str] = None,
    expected_ordered_face_fingerprint: Optional[str] = None,
    baseline_expected_cell_count: Optional[int] = None,
    baseline_expected_face_count: Optional[int] = None,
    minimum_cell_count_delta: int = 0,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 600.0,
    managed_host_max_attempts: int = 3,
    managed_host_attempt_timeout_seconds: Optional[float] = None,
    managed_host_persistence_mode: str = "auto",
    **mesh_parameters: Any,
) -> Dict[str, Any]:
    """Edit one breakline's RAS Mapper spacing and optionally regenerate."""
    from .geom import GeomMesh

    if polyline is not None:
        if not regenerate:
            raise ValueError(
                "Breakline creation qualification requires regenerate=True."
            )
        if near is None or far is None:
            raise ValueError(
                "Breakline creation requires positive near and far spacing."
            )
        return _mesh_breakline_create(
            context,
            geometry=geometry,
            polyline=polyline,
            name=name,
            near=float(near),
            far=float(far),
            near_repeats=int(near_repeats or 0),
            protection_radius=int(protection_radius or 0),
            mesh_name=mesh_name,
            expected_cell_count=expected_cell_count,
            expected_face_count=expected_face_count,
            expected_ordered_center_fingerprint=(
                expected_ordered_center_fingerprint
            ),
            expected_ordered_face_fingerprint=(
                expected_ordered_face_fingerprint
            ),
            baseline_expected_cell_count=baseline_expected_cell_count,
            baseline_expected_face_count=baseline_expected_face_count,
            minimum_cell_count_delta=int(minimum_cell_count_delta),
            interop_backend=interop_backend,
            managed_host_timeout_seconds=float(managed_host_timeout_seconds),
            managed_host_max_attempts=int(managed_host_max_attempts),
            managed_host_attempt_timeout_seconds=(
                float(managed_host_attempt_timeout_seconds)
                if managed_host_attempt_timeout_seconds is not None
                else None
            ),
            managed_host_persistence_mode=managed_host_persistence_mode,
            mesh_parameters=mesh_parameters,
        )

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    geom_hdf = _geometry_hdf(geom_path)
    persistence_mode = str(managed_host_persistence_mode).strip().lower()
    transactional_direct = persistence_mode == "transactional_direct"
    if transactional_direct:
        if not regenerate:
            raise ValueError(
                "transactional_direct breakline qualification requires "
                "regenerate=True"
            )
        exact_counts = {
            "expected_cell_count": expected_cell_count,
            "expected_face_count": expected_face_count,
        }
        missing = [name for name, value in exact_counts.items() if value is None]
        if missing:
            raise ValueError(
                "transactional_direct breakline qualification requires exact "
                f"final counts; missing {', '.join(missing)}"
            )
        nonpositive = [
            name for name, value in exact_counts.items() if int(value) <= 0
        ]
        if nonpositive:
            raise ValueError(
                "transactional_direct breakline counts must be positive; "
                f"invalid {', '.join(nonpositive)}"
            )
    before = GeomMesh.get_breakline_spacing(geom_path, ras_object=project)
    if not any(int(item[0]) == int(breakline_fid) for item in before):
        raise ValueError(f"Breakline FID {breakline_fid} not found")
    prechange_receipt = RasQualification.geometry_receipt(geom_hdf)
    prechange_text_sha256 = RasQualification.file_sha256(geom_path)
    backup = None
    generated = None
    attempted_receipt = None
    attempted_text_sha256 = None
    rolled_back = False
    mesh_count_checks = {
        "mesh_regenerated": not regenerate,
        "expected_cells": expected_cell_count is None,
        "expected_faces": expected_face_count is None,
    }
    if regenerate:
        # GeomMesh.generate must validate the current compiled HDF before it
        # edits text and synchronizes the new spacing back to HDF. Calling
        # set_breakline_spacing first makes the text newer and correctly trips
        # the stale-HDF guard.
        text_snapshot = geom_path.with_name(
            f".{geom_path.name}.rasq-breakline-{uuid.uuid4().hex}.bak"
        )
        hdf_snapshot = geom_hdf.with_name(
            f".{geom_hdf.name}.rasq-breakline-{uuid.uuid4().hex}.bak"
        )
        api_backup = geom_path.with_suffix(geom_path.suffix + ".bak")
        api_backup_existed = api_backup.is_file()
        api_backup_snapshot = geom_path.with_name(
            f".{api_backup.name}.rasq-breakline-{uuid.uuid4().hex}.bak"
        )
        shutil.copy2(geom_path, text_snapshot)
        shutil.copy2(geom_hdf, hdf_snapshot)
        if api_backup_existed:
            shutil.copy2(api_backup, api_backup_snapshot)

        def restore_prechange_files() -> None:
            nonlocal rolled_back
            shutil.copy2(text_snapshot, geom_path)
            shutil.copy2(hdf_snapshot, geom_hdf)
            if api_backup_existed:
                shutil.copy2(api_backup_snapshot, api_backup)
            else:
                api_backup.unlink(missing_ok=True)
            rolled_back = True

        try:
            generate_kwargs = {
                "interop_backend": interop_backend,
                "managed_host_timeout_seconds": float(
                    managed_host_timeout_seconds
                ),
                "managed_host_max_attempts": int(managed_host_max_attempts),
                "managed_host_attempt_timeout_seconds": (
                    float(managed_host_attempt_timeout_seconds)
                    if managed_host_attempt_timeout_seconds is not None
                    else None
                ),
                "managed_host_persistence_mode": persistence_mode,
            }
            if transactional_direct:
                generate_kwargs.update(
                    {
                        "managed_host_expected_cell_count": expected_cell_count,
                        "managed_host_expected_face_count": expected_face_count,
                    }
                )
            generated = GeomMesh.generate(
                geom_path,
                mesh_name=mesh_name,
                bl_spacing_near=near,
                bl_spacing_far=far,
                near_repeats=near_repeats,
                protection_radius=protection_radius,
                breakline_fid=int(breakline_fid),
                hecras_dir=Path(str(context["ras_executable"])).parent,
                ras_object=project,
                **generate_kwargs,
                **{
                    key: value
                    for key, value in mesh_parameters.items()
                    if key
                    in {
                        "cell_size",
                        "min_face_length_ratio",
                        "max_iterations",
                        "seed_generation_mode",
                    }
                },
            )
            after = GeomMesh.get_breakline_spacing(geom_path, ras_object=project)
            attempted_receipt = RasQualification.geometry_receipt(geom_hdf)
            attempted_text_sha256 = RasQualification.file_sha256(geom_path)
            selected_area = (
                attempted_receipt.get("areas", {}).get(str(generated.mesh_name))
                if generated is not None
                else None
            )
            managed_result = bool(
                generated is not None
                and generated.interop_backend == "managed_host"
            )
            managed_text_persistence = bool(
                managed_result and not transactional_direct
            )
            if transactional_direct:
                text_seed_receipt = None
                final_topology = _selected_mesh_topology_evidence(
                    attempted_receipt,
                    str(generated.mesh_name) if generated is not None else mesh_name,
                )
                mesh_count_checks = {
                    "mesh_regenerated": bool(generated),
                    "managed_backend_used": managed_result,
                    "managed_persistence_mode_exact": bool(
                        generated is not None
                        and generated.hdf_persistence_mode
                        == "transactional_direct"
                    ),
                    "managed_hdf_persisted": bool(
                        generated is not None and generated.hdf_persisted
                    ),
                    "managed_reopened_cells_exact": bool(
                        generated is not None
                        and int(generated.persisted_cell_count)
                        == int(generated.cell_count)
                    ),
                    "managed_reopened_faces_exact": bool(
                        generated is not None
                        and int(generated.persisted_face_count)
                        == int(generated.face_count)
                    ),
                    "result_matches_hdf_cells": bool(
                        generated is not None
                        and selected_area is not None
                        and int(selected_area["cell_count"])
                        == int(generated.cell_count)
                    ),
                    "result_matches_hdf_faces": bool(
                        generated is not None
                        and selected_area is not None
                        and int(selected_area["face_count"])
                        == int(generated.face_count)
                    ),
                    "expected_cells": bool(
                        generated is not None
                        and selected_area is not None
                        and int(generated.cell_count) == int(expected_cell_count)
                        and int(selected_area["cell_count"])
                        == int(expected_cell_count)
                    ),
                    "expected_faces": bool(
                        generated is not None
                        and selected_area is not None
                        and int(generated.face_count) == int(expected_face_count)
                        and int(selected_area["face_count"])
                        == int(expected_face_count)
                    ),
                }
                mesh_count_checks.update(
                    _transactional_mesh_topology_checks(
                        final_topology,
                        expected_cell_count=int(expected_cell_count),
                        expected_face_count=int(expected_face_count),
                    )
                )
            elif managed_text_persistence:
                text_seed_receipt = _geometry_text_seed_receipt(
                    geom_path,
                    str(generated.mesh_name),
                )
                mesh_count_checks = {
                    "mesh_regenerated": True,
                    "result_matches_text_seed_count": (
                        text_seed_receipt["declared_count"]
                        == int(generated.cell_count)
                    ),
                    "text_seed_block_complete": (
                        text_seed_receipt["coordinate_count"]
                        == int(generated.cell_count)
                    ),
                    "hdf_persistence_deferred_to_preprocess": True,
                    "expected_cells": (
                        expected_cell_count is None
                        or int(generated.cell_count) == int(expected_cell_count)
                    ),
                    "expected_faces": (
                        expected_face_count is None
                        or int(generated.face_count) == int(expected_face_count)
                    ),
                }
            else:
                text_seed_receipt = None
                mesh_count_checks = {
                    "mesh_regenerated": bool(generated),
                    "expected_cells": (
                        expected_cell_count is None
                        or selected_area is not None
                        and int(selected_area["cell_count"])
                        == int(expected_cell_count)
                    ),
                    "expected_faces": (
                        expected_face_count is None
                        or selected_area is not None
                        and int(selected_area["face_count"])
                        == int(expected_face_count)
                    ),
                }
            if not all(mesh_count_checks.values()):
                restore_prechange_files()
        except Exception:
            restore_prechange_files()
            raise
        finally:
            text_snapshot.unlink(missing_ok=True)
            hdf_snapshot.unlink(missing_ok=True)
            api_backup_snapshot.unlink(missing_ok=True)
    else:
        backup = GeomMesh.set_breakline_spacing(
            geom_path,
            near=near,
            far=far,
            near_repeats=near_repeats,
            protection_radius=protection_radius,
            breakline_fid=int(breakline_fid),
            ras_object=project,
        )
        after = GeomMesh.get_breakline_spacing(geom_path, ras_object=project)
    selected = next(item for item in after if int(item[0]) == int(breakline_fid))
    expected = {
        "near": near is None or float(selected[2]) == float(near),
        "far": far is None or float(selected[3]) == float(far),
        "near_repeats": near_repeats is None
        or int(selected[4]) == int(near_repeats),
        "protection_radius": protection_radius is None
        or int(selected[5]) == int(protection_radius),
    }
    receipt = RasQualification.geometry_receipt(geom_hdf)
    selected_mesh_name = (
        str(generated.mesh_name)
        if generated is not None and hasattr(generated, "mesh_name")
        else mesh_name
    )
    final_mesh_topology = _selected_mesh_topology_evidence(
        receipt,
        selected_mesh_name,
    )
    evidence = {
        "breakline_fid": int(breakline_fid),
        "spacing_before": before,
        "spacing_after": after,
        "spacing_checks": expected,
        "mesh_count_checks": mesh_count_checks,
        "backup": str(backup) if backup is not None else None,
        "mesh_result": _object_dict(generated) if generated is not None else None,
        "persistence_mode": (
            "transactional_rasmapper_hdf"
            if transactional_direct
            and generated is not None
            and generated.interop_backend == "managed_host"
            and generated.hdf_persisted
            else "transactional_rasmapper_hdf_rejected"
            if transactional_direct
            else "geometry_text_then_preprocess"
            if generated is not None
            and generated.interop_backend == "managed_host"
            else "rasmapper_hdf"
        ),
        "text_seed_receipt": (
            _geometry_text_seed_receipt(geom_path, str(generated.mesh_name))
            if generated is not None
            and bool(generated)
            and generated.interop_backend == "managed_host"
            and not transactional_direct
            else None
        ),
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "final_mesh_topology": final_mesh_topology,
        "geometry_fingerprint": receipt["geometry_fingerprint"],
        "breakline_count": receipt["breakline_count"],
        "prechange_geometry_fingerprint": prechange_receipt["geometry_fingerprint"],
        "prechange_text_sha256": prechange_text_sha256,
        "attempted_geometry_fingerprint": (
            attempted_receipt["geometry_fingerprint"] if attempted_receipt else None
        ),
        "attempted_text_sha256": attempted_text_sha256,
        "rolled_back_after_mapper_rejection": rolled_back,
        "rollback_restored_exact_geometry": bool(
            not rolled_back
            or receipt["file_sha256"] == prechange_receipt["file_sha256"]
        ),
        "rollback_restored_exact_text": bool(
            not rolled_back
            or RasQualification.file_sha256(geom_path) == prechange_text_sha256
        ),
    }
    return {
        "passed": bool(
            not rolled_back
            and all(expected.values())
            and all(mesh_count_checks.values())
        ),
        "evidence": evidence,
        "artifacts": {"geometry": receipt},
    }


def boundary_associate(
    context: Mapping[str, Any],
    line: Mapping[str, Any],
    unsteady: Optional[Union[str, Path]] = None,
    boundary_type: str = "normal_depth",
    friction_slope: Optional[float] = None,
    geometry: Optional[Union[str, Path]] = None,
    coordinate_abs_tolerance: float = 0.005,
    **_: Any,
) -> Dict[str, Any]:
    """Author a 2D BC line and attach an unsteady boundary condition."""
    from .RasUnsteady import RasUnsteady
    from .geom import GeomBcLines

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    line_spec = dict(line)
    write_result = GeomBcLines.add_bc_lines(
        geom_path, [line_spec], replace_existing=True
    )
    if unsteady is None:
        unsteady_number = _first_number(project, "unsteady_df", "unsteady_number")
        hit = project.unsteady_df[
            project.unsteady_df["unsteady_number"] == unsteady_number
        ]
        unsteady_path = Path(str(hit["full_path"].iloc[0]))
    else:
        unsteady_path = _required_file(context, unsteady, label="unsteady file")
    kind = boundary_type.strip().lower()
    if kind != "normal_depth":
        raise ValueError(
            "boundary_associate currently requires boundary_type='normal_depth'; "
            "use a fixture-specific handler for hydrograph authoring"
        )
    if friction_slope is None or float(friction_slope) <= 0:
        raise ValueError("positive friction_slope is required for normal depth")
    location = RasUnsteady.ensure_2d_boundary_location(
        unsteady_path,
        area_2d=str(line_spec["storage_area"]),
        bc_line=str(line_spec["name"]),
        geometry_file=geom_path,
        ras_object=project,
    )
    attached = RasUnsteady.set_normal_depth_boundary(
        unsteady_path,
        friction_slope=float(friction_slope),
        area_2d=str(line_spec["storage_area"]),
        bc_line=str(line_spec["name"]),
        ras_object=project,
    )
    authored = [
        item
        for item in GeomBcLines.get_bc_lines(geom_path)
        if str(item.get("name")) == str(line_spec["name"])
    ]
    expected_coordinates = [
        (float(point[0]), float(point[1]))
        for point in line_spec["coordinates"]
    ]
    coordinate_tolerance = float(coordinate_abs_tolerance)
    if not math.isfinite(coordinate_tolerance) or coordinate_tolerance < 0:
        raise ValueError("coordinate_abs_tolerance must be finite and non-negative")
    persisted_coordinates = (
        list(authored[0].get("coordinates") or []) if len(authored) == 1 else []
    )
    coordinate_errors = [
        max(abs(float(actual[0]) - expected[0]), abs(float(actual[1]) - expected[1]))
        for actual, expected in zip(persisted_coordinates, expected_coordinates)
    ]
    line_content_exact = bool(
        len(authored) == 1
        and str(authored[0].get("storage_area")) == str(line_spec["storage_area"])
        and len(persisted_coordinates) == len(expected_coordinates)
        and all(error <= coordinate_tolerance for error in coordinate_errors)
    )
    reopened = _initialize(context)
    matches = reopened.boundaries_df
    selected = matches[
        (matches["area_2d"].astype(str) == str(line_spec["storage_area"]))
        & (matches["bc_line_name"].astype(str) == str(line_spec["name"]))
    ]
    boundary_type_exact = bool(
        len(selected) == 1
        and str(selected.iloc[0].get("bc_type")) == "Normal Depth"
    )
    selected_slope = (
        selected.iloc[0].get("friction_slope_value")
        if len(selected) == 1
        else None
    )
    friction_slope_exact = bool(
        selected_slope is not None
        and math.isclose(
            float(selected_slope),
            float(friction_slope),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    evidence = {
        "geometry_write": write_result,
        "authored_line": authored,
        "line_content_exact": line_content_exact,
        "coordinate_abs_tolerance": coordinate_tolerance,
        "coordinate_max_abs_error": max(coordinate_errors) if coordinate_errors else None,
        "boundary_location": _json_value(location),
        "unsteady_file": _file_record(unsteady_path),
        "setter_result": _json_value(attached),
        "matched_boundaries": _json_value(selected.to_dict(orient="records")),
        "boundary_type_exact": boundary_type_exact,
        "friction_slope_exact": friction_slope_exact,
    }
    return {
        "passed": bool(
            location
            and attached
            and line_content_exact
            and len(selected) == 1
            and boundary_type_exact
            and friction_slope_exact
        ),
        "evidence": evidence,
    }


def boundary_conflict_repair(
    context: Mapping[str, Any],
    cell_size: float,
    conflict_detection_cell_size: Optional[float] = None,
    coordinate_abs_tolerance: float = 0.005,
    geometry: Optional[Union[str, Path]] = None,
    geometry_hdf: Optional[Union[str, Path]] = None,
    require_conflict: bool = True,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    expected_topology_fingerprint: Optional[str] = None,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 600.0,
    managed_host_max_attempts: int = 3,
    managed_host_attempt_timeout_seconds: Optional[float] = None,
    managed_host_persistence_mode: str = "auto",
    **mesh_parameters: Any,
) -> Dict[str, Any]:
    """Repair BC conflicts in text, regenerate, and verify a fresh HDF."""
    from .geom import GeomMesh
    from .geom import GeomBcLines
    from .hdf import HdfBndry

    project = _initialize(context)
    normal_depth_names = {
        str(row.get("bc_line_name"))
        for _, row in project.boundaries_df.iterrows()
        if str(row.get("bc_type", "")).strip().lower() == "normal depth"
    }
    if geometry is not None or context.get("qualification_geometry_text"):
        geom_path = _geometry_text(
            context,
            project,
            geometry or context.get("qualification_geometry_text"),
        )
    else:
        hdf_value = geometry_hdf or context.get("qualification_geometry_hdf")
        hdf_path_value = _required_file(
            context,
            hdf_value,
            label="geometry HDF",
        )
        if not str(hdf_path_value).lower().endswith(".hdf"):
            raise ValueError("geometry_hdf must end in .hdf")
        geom_path = Path(str(hdf_path_value)[:-4])
        if not geom_path.is_file():
            raise FileNotFoundError(
                "durable BC repair requires the authoritative geometry text: "
                f"{geom_path}"
            )
    hdf_path = _required_file(
        context,
        geometry_hdf or _geometry_hdf(geom_path),
        label="geometry HDF",
    )
    if hdf_path != _geometry_hdf(geom_path):
        raise ValueError(
            "geometry_hdf must be the compiled sibling of the authoritative "
            "geometry text"
        )
    if expected_cell_count is None or expected_face_count is None:
        raise ValueError(
            "exact expected cell and face counts are required for durable BC repair"
        )
    conflict_scale = float(
        conflict_detection_cell_size
        if conflict_detection_cell_size is not None
        else cell_size
    )
    if not math.isfinite(conflict_scale) or conflict_scale <= 0:
        raise ValueError("conflict_detection_cell_size must be finite and positive")
    coordinate_tolerance = float(coordinate_abs_tolerance)
    if not math.isfinite(coordinate_tolerance) or coordinate_tolerance < 0:
        raise ValueError("coordinate_abs_tolerance must be finite and non-negative")

    def hdf_lines(path: Path) -> Dict[tuple[str, str], List[tuple[float, float]]]:
        frame = HdfBndry.get_bc_lines(path)
        records: Dict[tuple[str, str], List[tuple[float, float]]] = {}
        if frame is None or frame.empty:
            return records
        for _, row in frame.iterrows():
            line = row.get("geometry")
            records[(str(row.get("SA-2D")), str(row.get("Name")))] = (
                [(float(x), float(y)) for x, y in line.coords]
                if line is not None and not line.is_empty
                else []
            )
        return records

    def text_lines(path: Path) -> Dict[tuple[str, str], List[tuple[float, float]]]:
        return {
            (str(item["storage_area"]), str(item["name"])): [
                (float(x), float(y)) for x, y in item["coordinates"]
            ]
            for item in GeomBcLines.get_bc_lines(path)
        }

    def coordinates_match(
        left: Optional[Sequence[Sequence[float]]],
        right: Optional[Sequence[Sequence[float]]],
    ) -> bool:
        return bool(
            left is not None
            and right is not None
            and len(left) == len(right)
            and all(
                math.isclose(
                    float(a[0]),
                    float(b[0]),
                    rel_tol=0.0,
                    abs_tol=coordinate_tolerance,
                )
                and math.isclose(
                    float(a[1]),
                    float(b[1]),
                    rel_tol=0.0,
                    abs_tol=coordinate_tolerance,
                )
                for a, b in zip(left, right)
            )
        )

    text_before_sha = RasQualification.file_sha256(geom_path)
    hdf_before_sha = RasQualification.file_sha256(hdf_path)
    receipt_before = RasQualification.geometry_receipt(hdf_path)
    before = GeomMesh.detect_bc_conflicts(
        hdf_path,
        conflict_scale,
        normal_depth_names=sorted(normal_depth_names),
    )
    backup_root = Path(str(context.get("run_directory") or geom_path.parent))
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_token = uuid.uuid4().hex[:10]
    text_backup = backup_root / f"{geom_path.name}.bc-repair-{backup_token}.bak"
    hdf_backup = backup_root / f"{hdf_path.name}.bc-repair-{backup_token}.bak"
    shutil.copy2(geom_path, text_backup)
    shutil.copy2(hdf_path, hdf_backup)

    result = None
    mapper_outcome = None
    after: List[Any] = []
    receipt = None
    write_result = None
    repaired_lines: Dict[tuple[str, str], List[tuple[float, float]]] = {}
    text_matches_repair = False
    hdf_matches_repair = False
    rolled_back = False
    failure_reason = None
    try:
        result = GeomMesh.fix_bc_conflicts(
            hdf_path,
            conflict_scale,
            dry_run=False,
            normal_depth_names=sorted(normal_depth_names),
        )
        repaired_hdf_lines = hdf_lines(hdf_path)
        affected = {
            tuple(str(value).rsplit("/", 1))
            for value, _description in result.trims
            if "/" in str(value)
        }
        repaired_lines = {
            key: repaired_hdf_lines[key]
            for key in sorted(affected)
            if key in repaired_hdf_lines
        }
        if repaired_lines:
            write_result = GeomBcLines.add_bc_lines(
                geom_path,
                [
                    {
                        "storage_area": area_name,
                        "name": line_name,
                        "coordinates": coordinates,
                    }
                    for (area_name, line_name), coordinates in repaired_lines.items()
                ],
                replace_existing=True,
            )
        persisted_text_lines = text_lines(geom_path)
        text_matches_repair = bool(
            repaired_lines
            and all(
                coordinates_match(persisted_text_lines.get(key), coordinates)
                for key, coordinates in repaired_lines.items()
            )
        )
        mapper_outcome = mesh_generate(
            context,
            geometry=geom_path,
            mesh_name=(
                next(iter(repaired_lines))[0]
                if repaired_lines
                else next(iter(receipt_before["areas"]))
            ),
            cell_size=float(cell_size),
            expected_cell_count=int(expected_cell_count),
            expected_face_count=int(expected_face_count),
            interop_backend=interop_backend,
            managed_host_timeout_seconds=float(managed_host_timeout_seconds),
            managed_host_max_attempts=int(managed_host_max_attempts),
            managed_host_attempt_timeout_seconds=(
                float(managed_host_attempt_timeout_seconds)
                if managed_host_attempt_timeout_seconds is not None
                else None
            ),
            managed_host_persistence_mode=managed_host_persistence_mode,
            **mesh_parameters,
        )
        after = GeomMesh.detect_bc_conflicts(
            hdf_path,
            conflict_scale,
            normal_depth_names=sorted(normal_depth_names),
        )
        receipt = RasQualification.geometry_receipt(hdf_path)
        reopened_hdf_lines = hdf_lines(hdf_path)
        hdf_matches_repair = bool(
            repaired_lines
            and all(
                coordinates_match(reopened_hdf_lines.get(key), coordinates)
                for key, coordinates in repaired_lines.items()
            )
        )
    except Exception as exc:
        failure_reason = f"{type(exc).__name__}: {exc}"

    before_topologies = {
        name: (area.get("mesh_topology") or {}).get("fingerprint")
        for name, area in receipt_before["areas"].items()
    }
    after_topologies = {
        name: (area.get("mesh_topology") or {}).get("fingerprint")
        for name, area in (receipt or {}).get("areas", {}).items()
    }
    topology_preserved = bool(
        receipt is not None
        and before_topologies == after_topologies
        and (
            expected_topology_fingerprint is None
            or expected_topology_fingerprint in after_topologies.values()
        )
    )
    passed = bool(
        failure_reason is None
        and (not require_conflict or len(before) > 0)
        and result is not None
        and result.conflicts_fixed == len(before)
        and not result.unresolvable
        and repaired_lines
        and text_matches_repair
        and mapper_outcome is not None
        and mapper_outcome.get("passed") is True
        and len(after) == 0
        and hdf_matches_repair
        and topology_preserved
        and receipt is not None
        and receipt["boundary_assignments"]
        == receipt_before["boundary_assignments"]
    )
    if not passed:
        shutil.copy2(text_backup, geom_path)
        shutil.copy2(hdf_backup, hdf_path)
        rolled_back = True

    evidence = {
        "conflicts_before": [_object_dict(item) for item in before],
        "repair": _object_dict(result) if result is not None else None,
        "conflicts_after": [_object_dict(item) for item in after],
        "geometry_fingerprint": (
            receipt["geometry_fingerprint"] if receipt is not None else None
        ),
        "boundary_assignments": (
            receipt["boundary_assignments"] if receipt is not None else None
        ),
        "text_write": write_result,
        "repaired_lines": [
            {
                "storage_area": key[0],
                "name": key[1],
                "coordinates": coordinates,
            }
            for key, coordinates in sorted(repaired_lines.items())
        ],
        "text_matches_repair": text_matches_repair,
        "mapper_outcome": mapper_outcome,
        "hdf_matches_repair_after_mapper_reopen": hdf_matches_repair,
        "topology_before": before_topologies,
        "topology_after": after_topologies,
        "topology_preserved": topology_preserved,
        "expected_topology_fingerprint": expected_topology_fingerprint,
        "text_before_sha256": text_before_sha,
        "hdf_before_sha256": hdf_before_sha,
        "text_after_sha256": RasQualification.file_sha256(geom_path),
        "hdf_after_sha256": RasQualification.file_sha256(hdf_path),
        "rolled_back": rolled_back,
        "rollback_restored_text": bool(
            not rolled_back
            or RasQualification.file_sha256(geom_path) == text_before_sha
        ),
        "rollback_restored_hdf": bool(
            not rolled_back
            or RasQualification.file_sha256(hdf_path) == hdf_before_sha
        ),
        "failure_reason": failure_reason,
        "mesh_cell_size": float(cell_size),
        "conflict_detection_cell_size": conflict_scale,
        "coordinate_abs_tolerance": coordinate_tolerance,
    }
    returned = {
        "passed": passed,
        "evidence": evidence,
        "context_updates": {
            "qualification_boundary_repair": {
                "geometry_text": str(geom_path),
                "geometry_hdf": str(hdf_path),
                "cell_size": float(cell_size),
                "conflict_detection_cell_size": conflict_scale,
                "coordinate_abs_tolerance": coordinate_tolerance,
                "repaired_lines": evidence["repaired_lines"],
            }
        }
        if passed
        else {},
    }
    if passed and receipt is not None:
        returned["artifacts"] = {"geometry": receipt}
    else:
        returned["diagnostics"] = {
            "failure_reason": failure_reason or "durable repair checks failed",
            "rolled_back": rolled_back,
        }
    return returned


def mannings_roundtrip(
    context: Mapping[str, Any],
    geometry: Optional[Union[str, Path]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Read and rewrite the authoritative geometry Manning's n table exactly."""
    from .geom import GeomLandCover

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    table = GeomLandCover.get_base_mannings_n(geom_path)
    if table.empty:
        raise RuntimeError(f"No LCMann table found in {geom_path}")
    before_values = _json_value(table.to_dict(orient="records"))
    written = GeomLandCover.set_base_mannings_n(geom_path, table.copy())
    reread = GeomLandCover.get_base_mannings_n(geom_path)
    after_values = _json_value(reread.to_dict(orient="records"))
    evidence = {
        "geometry": str(geom_path),
        "row_count": int(len(table)),
        "values_before": before_values,
        "values_after": after_values,
        "file": _file_record(geom_path),
    }
    return {"passed": bool(written and before_values == after_values), "evidence": evidence}


def land_cover_properties(
    context: Mapping[str, Any],
    layer_hdf: Optional[Union[str, Path]] = None,
    geometry: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
    classification_table: Optional[Union[str, Path]] = None,
    cell_size: Optional[float] = None,
    output_hdf_path: Union[str, Path] = "Land Classification/QualificationLandCover.hdf",
    layer_name: str = "Qualification Land Cover",
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 300.0,
    managed_host_max_attempts: int = 3,
    **_: Any,
) -> Dict[str, Any]:
    """Create or inspect a land-cover layer and require a nonempty class map."""
    from .RasMap import RasMap
    from .geom import GeomMesh
    from .hdf import HdfLandCover

    project = _initialize(context)
    if source_path is not None:
        if classification_table is None or cell_size is None:
            raise ValueError(
                "classification_table and cell_size are required with source_path"
            )
        source = _required_file(context, source_path, label="land-cover source")
        table = _required_file(
            context, classification_table, label="land-cover classification table"
        )
        hdf_path = Path(
            RasMap.add_landcover_layer(
                ras_project_path=project.project_folder,
                source_path=source,
                classification_table=table,
                cell_size=float(cell_size),
                output_hdf_path=_project_path(context, output_hdf_path),
                layer_name=layer_name,
                ras_object=project,
            )
        )
    else:
        hdf_path = _required_file(context, layer_hdf, label="land-cover HDF")
    geom_path = _geometry_text(context, project, geometry)
    managed_host_evidence: Dict[str, Any] = {}
    GeomMesh.set_geometry_association(
        geom_path,
        landcover_hdf_path=hdf_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        validate=True,
        interop_backend=interop_backend,
        timeout_seconds=float(managed_host_timeout_seconds),
        max_attempts=int(managed_host_max_attempts),
        managed_host_evidence=managed_host_evidence,
    )
    association = GeomMesh.get_geometry_association(
        geom_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        resolve_paths=True,
    )
    associated_value = association.get("landcover_hdf_path")
    associated_path = (
        RasUtils.safe_resolve(Path(str(associated_value))) if associated_value else None
    )
    raster_map = HdfLandCover.get_landcover_raster_map(hdf_path)
    layers = RasMap.list_landcover_layers(project.project_folder, ras_object=project)
    registered_paths = {
        RasUtils.safe_resolve(Path(str(value)))
        for value in layers.get("resolved_path", pd.Series(dtype=object)).dropna()
    }
    registered_exactly = hdf_path in registered_paths
    records = _json_value(raster_map.to_dict(orient="records"))
    evidence = {
        "landcover_hdf": _file_record(hdf_path),
        "class_count": int(len(raster_map)),
        "raster_map": records,
        "registered_layers": _json_value(layers.to_dict(orient="records")),
        "registered_exactly": registered_exactly,
        "geometry_association": association,
        "associated_exactly": associated_path == hdf_path,
        "interop_backend": interop_backend,
        "managed_host": managed_host_evidence or None,
    }
    return {
        "passed": bool(
            not raster_map.empty
            and registered_exactly
            and associated_path == hdf_path
        ),
        "evidence": evidence,
        "context_updates": {"qualification_landcover_hdf": str(hdf_path)},
    }


def infiltration_properties(
    context: Mapping[str, Any],
    layer_hdf: Optional[Union[str, Path]] = None,
    geometry: Optional[Union[str, Path]] = None,
    method: str = "scs_curve_number",
    landcover_hdf: Optional[Union[str, Path]] = None,
    soils_layer: Optional[Union[str, Path]] = None,
    output_hdf_path: Union[str, Path] = "Soils Data/QualificationInfiltration.hdf",
    create: bool = False,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 300.0,
    managed_host_max_attempts: int = 3,
    **_: Any,
) -> Dict[str, Any]:
    """Create or inspect an infiltration layer and require parameter content."""
    from .RasMap import RasMap
    from .geom import GeomMesh
    from .hdf import HdfInfiltration

    project = _initialize(context)
    if create:
        landcover_value = landcover_hdf or context.get("qualification_landcover_hdf")
        landcover_path = (
            _required_file(context, landcover_value, label="land-cover HDF")
            if landcover_value is not None
            else None
        )
        soils_path = (
            _required_file(context, soils_layer, label="soils layer")
            if soils_layer is not None
            else None
        )
        hdf_path = Path(
            RasMap.add_infiltration_layer(
                ras_project_path=project.project_folder,
                infiltration_method=method,
                landcover_hdf_path=landcover_path,
                soil_layer_path=soils_path,
                output_hdf_path=_project_path(context, output_hdf_path),
                ras_object=project,
            )
        )
    else:
        hdf_path = _required_file(context, layer_hdf, label="infiltration HDF")
    geom_path = _geometry_text(context, project, geometry)
    managed_host_evidence: Dict[str, Any] = {}
    GeomMesh.set_geometry_association(
        geom_path,
        infiltration_hdf_path=hdf_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        validate=True,
        interop_backend=interop_backend,
        timeout_seconds=float(managed_host_timeout_seconds),
        max_attempts=int(managed_host_max_attempts),
        managed_host_evidence=managed_host_evidence,
    )
    association = GeomMesh.get_geometry_association(
        geom_path,
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        resolve_paths=True,
    )
    associated_value = association.get("infiltration_hdf_path")
    associated_path = (
        RasUtils.safe_resolve(Path(str(associated_value))) if associated_value else None
    )
    data = HdfInfiltration.get_infiltration_layer_data(hdf_path)
    overrides = HdfInfiltration.get_infiltration_baseoverrides(hdf_path)
    layers = RasMap.list_infiltration_layers(project.project_folder, ras_object=project)
    registered_paths = {
        RasUtils.safe_resolve(Path(str(value)))
        for value in layers.get("resolved_path", pd.Series(dtype=object)).dropna()
    }
    registered_exactly = hdf_path in registered_paths
    evidence = {
        "infiltration_hdf": _file_record(hdf_path),
        "parameter_row_count": int(len(data)) if data is not None else 0,
        "parameters": _json_value(data.to_dict(orient="records")) if data is not None else [],
        "base_overrides": (
            _json_value(overrides.to_dict(orient="records"))
            if overrides is not None
            else []
        ),
        "registered_layers": _json_value(layers.to_dict(orient="records")),
        "registered_exactly": registered_exactly,
        "geometry_association": association,
        "associated_exactly": associated_path == hdf_path,
        "interop_backend": interop_backend,
        "managed_host": managed_host_evidence or None,
    }
    return {
        "passed": bool(
            data is not None
            and not data.empty
            and registered_exactly
            and associated_path == hdf_path
        ),
        "evidence": evidence,
        "context_updates": {"qualification_infiltration_hdf": str(hdf_path)},
    }


def geometry_property_tables(
    context: Mapping[str, Any],
    geometry: Optional[Union[str, Path]] = None,
    mesh_name: Optional[str] = None,
    force: bool = True,
    complete_geometry: bool = True,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    interop_backend: str = "auto",
    managed_host_timeout_seconds: float = 1800.0,
    managed_host_max_attempts: int = 3,
    **_: Any,
) -> Dict[str, Any]:
    """Compute RAS Mapper property tables and enforce complete cell/face coverage."""
    from .geom import GeomMesh

    project = _initialize(context)
    geom_path = _geometry_text(context, project, geometry)
    managed_host_evidence: Dict[str, Any] = {}
    computed = GeomMesh.compute_property_tables(
        geom_path,
        mesh_name=mesh_name,
        force=bool(force),
        complete_geometry=bool(complete_geometry),
        hecras_dir=Path(str(context["ras_executable"])).parent,
        ras_object=project,
        interop_backend=interop_backend,
        timeout_seconds=float(managed_host_timeout_seconds),
        max_attempts=int(managed_host_max_attempts),
        managed_host_evidence=managed_host_evidence,
    )
    receipt = RasQualification.geometry_receipt(_geometry_hdf(geom_path))
    complete = bool(
        receipt["areas"]
        and all(
            area["face_property_complete"] and area["cell_property_complete"]
            for area in receipt["areas"].values()
        )
    )
    selected_area = receipt["areas"].get(str(mesh_name)) if mesh_name else None
    count_checks = {
        "cell_count_exact": bool(
            expected_cell_count is None
            or (
                selected_area is not None
                and int(selected_area["cell_count"]) == int(expected_cell_count)
            )
        ),
        "face_count_exact": bool(
            expected_face_count is None
            or (
                selected_area is not None
                and int(selected_area["face_count"]) == int(expected_face_count)
            )
        ),
    }
    evidence = {
        "compute_returned": bool(computed),
        "complete_geometry_requested": bool(complete_geometry),
        "interop_backend": interop_backend,
        "managed_host": managed_host_evidence or None,
        "property_tables_complete": complete,
        "expected_cell_count": expected_cell_count,
        "expected_face_count": expected_face_count,
        "count_checks": count_checks,
        "areas": receipt["areas"],
        "geometry_fingerprint": receipt["geometry_fingerprint"],
    }
    return {
        "passed": bool(computed and complete and all(count_checks.values())),
        "evidence": evidence,
        "artifacts": {"geometry": receipt},
    }


def plan_preprocess(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    max_wait: int = 600,
    geometry_preprocessor_timeout: int = 300,
    require_preprocessor_hdf_change: bool = True,
    geometry: Optional[Union[str, Path]] = None,
    mesh_name: Optional[str] = None,
    expected_cell_count: Optional[int] = None,
    expected_face_count: Optional[int] = None,
    expected_ordered_center_fingerprint: Optional[str] = None,
    expected_ordered_face_fingerprint: Optional[str] = None,
    require_property_table_transition: bool = False,
    require_topology_preserved: bool = True,
    force_text_geometry_recompile: bool = False,
    require_fixed_width_area_names: bool = True,
    **_: Any,
) -> Dict[str, Any]:
    """Run preprocessing and inspect authoritative compiled geometry content.

    Property-table generation is qualified here rather than by a standalone
    RasMapperLib call.  Fresh-mesh fixtures may require an observed transition
    from incomplete tables before preprocessing to complete tables afterward.
    """
    from .RasPreprocess import RasPreprocess

    project = _initialize(context)
    number = _plan_number(project, plan_number)
    geom_path = (
        _geometry_text(context, project, geometry)
        if geometry is not None
        else None
    )
    text_seed_before = (
        _geometry_text_seed_receipt(geom_path, str(mesh_name))
        if geom_path is not None and mesh_name is not None
        else None
    )
    geometry_receipt_before = None
    selected_area_before = None
    if geom_path is not None and _geometry_hdf(geom_path).is_file():
        geometry_receipt_before = RasQualification.geometry_receipt(
            _geometry_hdf(geom_path)
        )
        if mesh_name is not None:
            selected_area_before = geometry_receipt_before["areas"].get(
                str(mesh_name)
            )
    text_recompile = {
        "requested": bool(force_text_geometry_recompile),
        "applied": False,
        "canonicalized": False,
        "content_sha256_before": None,
        "content_sha256_after_canonicalization": None,
        "content_changed_by_canonicalization": None,
        "mesh_seed_coordinates_preserved": None,
        "geometry_text_mtime_ns_before": None,
        "geometry_text_mtime_ns_after": None,
        "geometry_hdf_mtime_ns": None,
        "text_newer_than_hdf": None,
    }
    if force_text_geometry_recompile:
        if geom_path is None:
            raise ValueError(
                "geometry is required when force_text_geometry_recompile=True"
            )
        geom_hdf_path = _geometry_hdf(geom_path)
        if not geom_hdf_path.is_file():
            raise FileNotFoundError(
                "Compiled geometry HDF is required before forcing a text "
                f"geometry recompile: {geom_hdf_path}"
            )
        if mesh_name is None:
            raise ValueError(
                "mesh_name is required when force_text_geometry_recompile=True"
            )
        from .geom import GeomStorage

        content_sha256 = RasQualification.file_sha256(geom_path)
        polygons = GeomStorage.get_storage_area_polygons(
            geom_path,
            exclude_2d=False,
        )
        polygon_rows = polygons[
            polygons["Name"].astype(str) == str(mesh_name)
        ]
        if len(polygon_rows) != 1:
            raise ValueError(
                "Expected exactly one text-geometry polygon for "
                f"{mesh_name}, found {len(polygon_rows)}"
            )
        settings = GeomStorage.get_2d_flow_area_settings(geom_path)
        settings_rows = settings[
            settings["name"].astype(str) == str(mesh_name)
        ]
        if len(settings_rows) != 1:
            raise ValueError(
                "Expected exactly one text-geometry settings row for "
                f"{mesh_name}, found {len(settings_rows)}"
            )
        raw_point_generation = str(
            settings_rows.iloc[0]["point_generation_data"]
        )
        point_generation_values = [
            None if not value.strip() else float(value.strip())
            for value in raw_point_generation.split(",")
        ]
        GeomStorage.set_2d_flow_area_perimeter(
            geom_path,
            flow_area_name=str(mesh_name),
            geometry=polygon_rows.geometry.iloc[0],
            point_generation_data=point_generation_values,
            recompute_centroid=False,
            create_backup=False,
        )
        canonical_content_sha256 = RasQualification.file_sha256(geom_path)
        canonical_seed_receipt = _geometry_text_seed_receipt(
            geom_path,
            str(mesh_name),
        )
        mesh_seed_coordinates_preserved = bool(
            text_seed_before is not None
            and canonical_seed_receipt["declared_count"]
            == text_seed_before["declared_count"]
            and canonical_seed_receipt["coordinate_count"]
            == text_seed_before["coordinate_count"]
            and canonical_seed_receipt["invalid_chunks"] == 0
            and canonical_seed_receipt["coordinate_values_sha256"]
            == text_seed_before["coordinate_values_sha256"]
        )
        before_stat = geom_path.stat()
        hdf_stat = geom_hdf_path.stat()
        geom_path.touch()
        after_stat = geom_path.stat()
        if after_stat.st_mtime_ns <= hdf_stat.st_mtime_ns:
            authoritative_mtime_ns = max(
                time.time_ns(),
                hdf_stat.st_mtime_ns + 2_000_000_000,
            )
            os.utime(
                geom_path,
                ns=(after_stat.st_atime_ns, authoritative_mtime_ns),
            )
            after_stat = geom_path.stat()
        text_recompile = {
            "requested": True,
            "applied": True,
            "canonicalized": True,
            "content_sha256_before": content_sha256,
            "content_sha256_after_canonicalization": (
                canonical_content_sha256
            ),
            "content_changed_by_canonicalization": (
                canonical_content_sha256 != content_sha256
            ),
            "mesh_seed_coordinates_preserved": (
                mesh_seed_coordinates_preserved
            ),
            "point_generation_data_before": raw_point_generation,
            "point_generation_data_after": GeomStorage.get_2d_flow_area_settings(
                geom_path
            ).loc[
                lambda frame: frame["name"].astype(str) == str(mesh_name),
                "point_generation_data",
            ].iloc[0],
            "geometry_text_mtime_ns_before": before_stat.st_mtime_ns,
            "geometry_text_mtime_ns_after": after_stat.st_mtime_ns,
            "geometry_hdf_mtime_ns": hdf_stat.st_mtime_ns,
            "text_newer_than_hdf": (
                after_stat.st_mtime_ns > hdf_stat.st_mtime_ns
            ),
        }
    result = RasPreprocess.preprocess_plan(
        number,
        ras_object=project,
        max_wait=int(max_wait),
        clear_existing=True,
        fix_line_endings=False,
    )
    record = _object_dict(result)
    vendor_result = None
    if result:
        vendor_result = RasPreprocess.run_ras_geom_preprocess(
            number,
            ras_object=project,
            input_hdf_path=getattr(result, "tmp_hdf_path", None),
            x_file_path=getattr(result, "x_file_path", None),
            timeout=int(geometry_preprocessor_timeout),
            require_hdf_change=bool(require_preprocessor_hdf_change),
        )
    vendor_record = _object_dict(vendor_result) if vendor_result is not None else None
    files = {}
    for name in ("tmp_hdf_path", "b_file_path", "x_file_path"):
        value = getattr(result, name, None)
        if value is not None and Path(value).is_file():
            path = Path(value)
            files[name] = {
                **_file_record(path),
                "sha256": RasQualification.file_sha256(path),
            }

    geometry_receipt = None
    plan_geometry_receipt = None
    selected_area = None
    plan_selected_area = None
    text_seed_after = None
    tmp_hdf_path = getattr(result, "tmp_hdf_path", None)
    if tmp_hdf_path is not None and Path(tmp_hdf_path).is_file():
        plan_geometry_receipt = RasQualification.geometry_receipt(tmp_hdf_path)
        if mesh_name is not None:
            plan_selected_area = plan_geometry_receipt["areas"].get(str(mesh_name))
    if geom_path is not None:
        geometry_receipt = RasQualification.geometry_receipt(
            _geometry_hdf(geom_path)
        )
        if mesh_name is not None:
            selected_area = geometry_receipt["areas"].get(str(mesh_name))
            text_seed_after = _geometry_text_seed_receipt(
                geom_path, str(mesh_name)
            )

    def topology_fingerprint(area: Optional[Mapping[str, Any]]) -> Optional[str]:
        topology = (area or {}).get("mesh_topology") or {}
        return (
            str(topology.get("fingerprint"))
            if topology.get("complete") is True and topology.get("fingerprint")
            else None
        )

    def semantic_topology(
        area: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, str]]:
        topology = (area or {}).get("mesh_topology") or {}
        components = topology.get("components") or {}
        centers = components.get("ordered_nonvirtual_centers") or {}
        faces = components.get("ordered_faces_and_indexes") or {}
        center_fingerprint = centers.get("fingerprint")
        face_fingerprint = faces.get("fingerprint")
        if (
            topology.get("complete") is not True
            or not center_fingerprint
            or not face_fingerprint
        ):
            return None
        return {
            "ordered_nonvirtual_centers": str(center_fingerprint),
            "ordered_faces_and_indexes": str(face_fingerprint),
        }

    def attributes_name_width(area: Optional[Mapping[str, Any]]) -> Optional[int]:
        topology = (area or {}).get("mesh_topology") or {}
        datasets = topology.get("datasets") or {}
        attributes = datasets.get("Attributes (Name and Cell Count)") or {}
        dtype = attributes.get("dtype") or {}
        for field in dtype.get("descr") or []:
            if not isinstance(field, (list, tuple)) or len(field) < 2:
                continue
            if str(field[0]) != "Name":
                continue
            descriptor = field[1]
            if isinstance(descriptor, (list, tuple)) and descriptor:
                descriptor = descriptor[0]
            match = re.search(r"S(\d+)$", str(descriptor))
            return int(match.group(1)) if match else None
        return None

    before_topology = topology_fingerprint(selected_area_before)
    geometry_topology = topology_fingerprint(selected_area)
    plan_topology = topology_fingerprint(plan_selected_area)
    before_semantic_topology = semantic_topology(selected_area_before)
    geometry_semantic_topology = semantic_topology(selected_area)
    plan_semantic_topology = semantic_topology(plan_selected_area)
    semantic_preservation_available = bool(
        before_semantic_topology is not None
        and geometry_semantic_topology is not None
    )
    semantic_plan_comparison_available = bool(
        geometry_semantic_topology is not None
        and plan_semantic_topology is not None
    )
    geometry_topology_preserved = bool(
        selected_area_before is not None
        and selected_area is not None
        and int(selected_area_before["cell_count"])
        == int(selected_area["cell_count"])
        and int(selected_area_before["face_count"])
        == int(selected_area["face_count"])
        and (
            before_semantic_topology == geometry_semantic_topology
            if semantic_preservation_available
            else before_topology is not None
            and before_topology == geometry_topology
        )
    )
    plan_topology_matches_geometry = bool(
        (
            geometry_semantic_topology == plan_semantic_topology
            if semantic_plan_comparison_available
            else geometry_topology is not None
            and geometry_topology == plan_topology
        )
    )
    geometry_name_width = attributes_name_width(selected_area)
    plan_name_width = attributes_name_width(plan_selected_area)
    before_tables_complete = bool(
        selected_area_before
        and selected_area_before.get("cell_property_complete")
        and selected_area_before.get("face_property_complete")
    )
    geometry_tables_complete = bool(
        selected_area
        and selected_area.get("cell_property_complete")
        and selected_area.get("face_property_complete")
    )
    boundary_repair_value = context.get("qualification_boundary_repair") or {}
    boundary_repair = (
        boundary_repair_value
        if isinstance(boundary_repair_value, Mapping)
        else {}
    )
    boundary_conflicts_after_preprocess: List[Any] = []
    boundary_lines_after_preprocess: List[Dict[str, Any]] = []
    boundary_repair_persisted = not boundary_repair
    if boundary_repair and geom_path is not None:
        from .geom import GeomMesh
        from .hdf import HdfBndry

        boundary_conflicts_after_preprocess = GeomMesh.detect_bc_conflicts(
            _geometry_hdf(geom_path),
            float(
                boundary_repair.get(
                    "conflict_detection_cell_size",
                    boundary_repair["cell_size"],
                )
            ),
        )
        frame = HdfBndry.get_bc_lines(_geometry_hdf(geom_path))
        actual_lines = {}
        if frame is not None and not frame.empty:
            for _, row in frame.iterrows():
                line = row.get("geometry")
                actual_lines[(str(row.get("SA-2D")), str(row.get("Name")))] = (
                    [(float(x), float(y)) for x, y in line.coords]
                    if line is not None and not line.is_empty
                    else []
                )
        boundary_lines_after_preprocess = list(
            boundary_repair.get("repaired_lines") or []
        )

        def repaired_line_matches(item: Mapping[str, Any]) -> bool:
            expected = item.get("coordinates") or []
            actual = actual_lines.get(
                (str(item.get("storage_area")), str(item.get("name")))
            )
            tolerance = float(
                boundary_repair.get("coordinate_abs_tolerance", 0.005)
            )
            return bool(
                actual is not None
                and len(actual) == len(expected)
                and all(
                    math.isclose(
                        float(left[0]),
                        float(right[0]),
                        rel_tol=0.0,
                        abs_tol=tolerance,
                    )
                    and math.isclose(
                        float(left[1]),
                        float(right[1]),
                        rel_tol=0.0,
                        abs_tol=tolerance,
                    )
                    for left, right in zip(actual, expected)
                )
            )

        boundary_repair_persisted = bool(
            not boundary_conflicts_after_preprocess
            and boundary_lines_after_preprocess
            and all(
                repaired_line_matches(item)
                for item in boundary_lines_after_preprocess
            )
        )

    count_checks = {
        "preprocess_succeeded": bool(result),
        "vendor_geometry_preprocessor_succeeded": bool(vendor_result),
        "all_prerequisites_present": len(files) == 3,
        "expected_cells": (
            expected_cell_count is None
            or selected_area is not None
            and int(selected_area["cell_count"]) == int(expected_cell_count)
        ),
        "expected_faces": (
            expected_face_count is None
            or selected_area is not None
            and int(selected_area["face_count"]) == int(expected_face_count)
        ),
        "plan_hdf_expected_cells": (
            mesh_name is None
            or expected_cell_count is None
            or plan_selected_area is not None
            and int(plan_selected_area["cell_count"]) == int(expected_cell_count)
        ),
        "plan_hdf_expected_faces": (
            mesh_name is None
            or expected_face_count is None
            or plan_selected_area is not None
            and int(plan_selected_area["face_count"]) == int(expected_face_count)
        ),
        "geometry_property_tables_complete": (
            mesh_name is None
            or selected_area is not None
            and bool(selected_area.get("cell_property_complete"))
            and bool(selected_area.get("face_property_complete"))
            and int((selected_area.get("quality") or {}).get("invalid_cell_count", -1)) == 0
        ),
        "geometry_topology_complete": (
            mesh_name is None or geometry_topology is not None
        ),
        "plan_hdf_topology_complete": (
            mesh_name is None or plan_topology is not None
        ),
        "geometry_attributes_name_width_16": (
            not require_fixed_width_area_names
            or mesh_name is None
            or geometry_name_width == 16
        ),
        "plan_hdf_attributes_name_width_16": (
            not require_fixed_width_area_names
            or mesh_name is None
            or plan_name_width == 16
        ),
        "plan_hdf_property_tables_complete": (
            mesh_name is None
            or plan_selected_area is not None
            and bool(plan_selected_area.get("cell_property_complete"))
            and bool(plan_selected_area.get("face_property_complete"))
            and int(
                (plan_selected_area.get("quality") or {}).get(
                    "invalid_cell_count", -1
                )
            ) == 0
        ),
        "geometry_hdf_matches_text_seed_count": (
            mesh_name is None
            or selected_area is not None
            and text_seed_after is not None
            and int(selected_area["cell_count"])
            == int(text_seed_after["declared_count"])
                == int(text_seed_after["coordinate_count"])
        ),
        "property_table_transition_observed": (
            not require_property_table_transition
            or selected_area_before is not None
            and not before_tables_complete
            and geometry_tables_complete
        ),
        "geometry_topology_preserved": (
            mesh_name is None
            or not require_topology_preserved
            or geometry_topology_preserved
        ),
        "plan_hdf_topology_matches_geometry": (
            mesh_name is None
            or plan_topology_matches_geometry
        ),
        "geometry_expected_ordered_center_fingerprint": (
            expected_ordered_center_fingerprint is None
            or geometry_semantic_topology is not None
            and geometry_semantic_topology["ordered_nonvirtual_centers"]
            == str(expected_ordered_center_fingerprint)
        ),
        "geometry_expected_ordered_face_fingerprint": (
            expected_ordered_face_fingerprint is None
            or geometry_semantic_topology is not None
            and geometry_semantic_topology["ordered_faces_and_indexes"]
            == str(expected_ordered_face_fingerprint)
        ),
        "plan_hdf_expected_ordered_center_fingerprint": (
            expected_ordered_center_fingerprint is None
            or plan_semantic_topology is not None
            and plan_semantic_topology["ordered_nonvirtual_centers"]
            == str(expected_ordered_center_fingerprint)
        ),
        "plan_hdf_expected_ordered_face_fingerprint": (
            expected_ordered_face_fingerprint is None
            or plan_semantic_topology is not None
            and plan_semantic_topology["ordered_faces_and_indexes"]
            == str(expected_ordered_face_fingerprint)
        ),
        "text_geometry_recompile_applied": (
            not force_text_geometry_recompile
            or text_recompile["applied"]
            and text_recompile["canonicalized"]
            and text_recompile["mesh_seed_coordinates_preserved"]
            and text_recompile["text_newer_than_hdf"]
        ),
        "boundary_repair_survived_preprocess": boundary_repair_persisted,
    }
    evidence = {
        "preprocess_result": record,
        "vendor_geometry_preprocessor": vendor_record,
        "files": files,
        "count_checks": count_checks,
        "selected_area": selected_area,
        "selected_area_before": selected_area_before,
        "plan_selected_area": plan_selected_area,
        "text_seed_before": text_seed_before,
        "text_seed_after": text_seed_after,
        "geometry_fingerprint": (
            geometry_receipt["geometry_fingerprint"]
            if geometry_receipt is not None
            else None
        ),
        "geometry_fingerprint_before": (
            geometry_receipt_before["geometry_fingerprint"]
            if geometry_receipt_before is not None
            else None
        ),
        "property_table_generation_owned_by_preprocess": True,
        "property_table_transition_required": bool(
            require_property_table_transition
        ),
        "topology_preservation_required": bool(require_topology_preserved),
        "topology_comparison": {
            "mode": (
                "semantic_components"
                if semantic_preservation_available
                else "storage_fingerprint_fallback"
            ),
            "before_storage_fingerprint": before_topology,
            "geometry_storage_fingerprint": geometry_topology,
            "plan_storage_fingerprint": plan_topology,
            "before_semantic_components": before_semantic_topology,
            "geometry_semantic_components": geometry_semantic_topology,
            "plan_semantic_components": plan_semantic_topology,
            "geometry_preserved": geometry_topology_preserved,
            "plan_matches_geometry": plan_topology_matches_geometry,
        },
        "expected_ordered_center_fingerprint": (
            str(expected_ordered_center_fingerprint)
            if expected_ordered_center_fingerprint is not None
            else None
        ),
        "expected_ordered_face_fingerprint": (
            str(expected_ordered_face_fingerprint)
            if expected_ordered_face_fingerprint is not None
            else None
        ),
        "fixed_width_area_names_required": bool(
            require_fixed_width_area_names
        ),
        "geometry_attributes_name_width": geometry_name_width,
        "plan_hdf_attributes_name_width": plan_name_width,
        "text_geometry_recompile": text_recompile,
        "boundary_repair_rechecked": bool(boundary_repair),
        "boundary_conflicts_after_preprocess": [
            _object_dict(item) for item in boundary_conflicts_after_preprocess
        ],
        "boundary_lines_expected_after_preprocess": (
            boundary_lines_after_preprocess
        ),
    }
    returned = {
        "passed": bool(all(count_checks.values())),
        "evidence": evidence,
    }
    if geometry_receipt is not None:
        returned["artifacts"] = {"geometry": geometry_receipt}
    if plan_geometry_receipt is not None:
        returned.setdefault("artifacts", {})[
            "preprocessed_plan_geometry"
        ] = plan_geometry_receipt
    return returned


def plan_compute_unsteady(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    num_cores: Optional[int] = None,
    timeout_sec: int = 3600,
    series: Optional[Mapping[str, Mapping[str, Any]]] = None,
    fresh_result_files: Optional[Sequence[Union[str, Path]]] = None,
    require_results_group_absent_before_compute: bool = False,
    execution_backend: str = "windows",
    ras_exe_dir: Optional[Union[str, Path]] = None,
    dos2unix: bool = True,
    retry: bool = False,
    retry_delay_sec: int = 30,
    compute_environment: Optional[Mapping[str, Any]] = None,
    require_volume_accounting: bool = True,
    defer_series_extraction: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Compute an unsteady plan and attach content-level HDF evidence."""
    from .RasCmdr import RasCmdr
    from .RasPlan import RasPlan

    backend = str(execution_backend).strip().lower()
    if backend in {"linux", "linux_native", "native_linux"}:
        if ras_exe_dir is None:
            raise ValueError("ras_exe_dir is required for native Linux compute")
        return plan_compute_unsteady_linux(
            context,
            ras_exe_dir=ras_exe_dir,
            plan_number=plan_number,
            num_cores=num_cores,
            timeout_sec=timeout_sec,
            dos2unix=dos2unix,
            retry=retry,
            retry_delay_sec=retry_delay_sec,
            compute_environment=compute_environment,
            require_volume_accounting=require_volume_accounting,
            defer_series_extraction=defer_series_extraction,
            series=series,
            fresh_result_files=fresh_result_files,
            require_results_group_absent_before_compute=(
                require_results_group_absent_before_compute
            ),
        )
    if backend not in {"windows", "windows_ras"}:
        raise ValueError(f"Unsupported unsteady execution backend: {execution_backend!r}")

    project = _initialize(context)
    number = _plan_number(project, plan_number)
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Plan {number} not found before compute")
    hdf_path = Path(str(plan_path) + ".hdf")
    if not series:
        raise ValueError(
            "plan.compute_unsteady requires hydrograph and WSE series specifications"
        )
    series_inputs = _result_series_input_receipts(context, series)
    freshness = _fresh_compute_preflight(
        context,
        hdf_path,
        fresh_result_files,
        require_results_group_absent=bool(
            require_results_group_absent_before_compute
        ),
    )
    result = RasCmdr.compute_plan(
        number,
        ras_object=project,
        force_rerun=True,
        verify=True,
        num_cores=num_cores,
        timeout_sec=int(timeout_sec),
        process_environment=compute_environment,
    )
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Plan {number} not found after compute")
    hdf_path = Path(str(plan_path) + ".hdf")
    result_receipt = RasQualification.results_receipt(hdf_path)
    volume_present = result_receipt["max_abs_volume_error_percent"] is not None
    if not result or not result_receipt["successful"]:
        return {
            "passed": False,
            "evidence": {
                "compute_result": _object_dict(result),
                "results_successful": result_receipt["successful"],
                "max_abs_volume_error_percent": result_receipt[
                    "max_abs_volume_error_percent"
                ],
                "volume_accounting_present": volume_present,
                "results_sha256": result_receipt["file_sha256"],
                "fresh_compute": freshness,
                "series_inputs": series_inputs,
                "compute_environment": _json_value(compute_environment or {}),
                "completion_checks": result_receipt.get("completion_checks"),
                "compute_diagnostics": result_receipt.get("compute_diagnostics"),
            },
            "diagnostics": {
                "reason": "HEC-RAS unsteady computation did not produce complete results"
            },
            "artifacts": {"results": result_receipt},
        }
    if defer_series_extraction:
        evidence = {
            "compute_result": _object_dict(result),
            "results_successful": result_receipt["successful"],
            "max_abs_volume_error_percent": result_receipt[
                "max_abs_volume_error_percent"
            ],
            "volume_accounting_present": volume_present,
            "results_sha256": result_receipt["file_sha256"],
            "fresh_compute": freshness,
            "series_inputs": series_inputs,
            "compute_environment": _json_value(compute_environment or {}),
            "series_extraction_deferred": True,
        }
        return {
            "passed": bool(
                result
                and result_receipt["successful"]
                and native_log["passed"]
                and (not require_volume_accounting or volume_present)
                and (
                    not require_results_group_absent_before_compute
                    or freshness["passed"]
                )
            ),
            "evidence": evidence,
            "artifacts": {"results": result_receipt},
            "context_updates": {
                "qualification_plan_number": number,
                "qualification_plan_hdf": str(hdf_path),
                "qualification_series_specifications": _json_value(series),
            },
        }
    result_series = RasQualification.extract_result_series(
        hdf_path,
        series,
        ras_object=project,
    )
    evidence = {
        "compute_result": _object_dict(result),
        "results_successful": result_receipt["successful"],
        "max_abs_volume_error_percent": result_receipt[
            "max_abs_volume_error_percent"
        ],
        "results_sha256": result_receipt["file_sha256"],
        "fresh_compute": freshness,
        "series_inputs": series_inputs,
        "compute_environment": _json_value(compute_environment or {}),
        "volume_accounting_present": volume_present,
        "series": {
            name: {
                "kind": item["kind"],
                "record_count": len(item["records"]),
                "value_columns": item["value_columns"],
            }
            for name, item in result_series.items()
        },
    }
    return {
        "passed": bool(
            result
            and result_receipt["successful"]
            and (not require_volume_accounting or volume_present)
            and (
                not require_results_group_absent_before_compute
                or freshness["passed"]
            )
        ),
        "evidence": evidence,
        "artifacts": {"results": result_receipt},
        "series": result_series,
        "context_updates": {
            "qualification_plan_number": number,
            "qualification_plan_hdf": str(hdf_path),
            "qualification_series_specifications": _json_value(series),
        },
    }


def plan_compute_unsteady_linux(
    context: Mapping[str, Any],
    ras_exe_dir: Union[str, Path],
    plan_number: Optional[Union[str, int]] = None,
    num_cores: Optional[int] = None,
    timeout_sec: int = 14400,
    dos2unix: bool = True,
    retry: bool = False,
    retry_delay_sec: int = 30,
    compute_environment: Optional[Mapping[str, Any]] = None,
    require_volume_accounting: bool = True,
    defer_series_extraction: bool = False,
    series: Optional[Mapping[str, Mapping[str, Any]]] = None,
    fresh_result_files: Optional[Sequence[Union[str, Path]]] = None,
    require_results_group_absent_before_compute: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Run the supported native Linux unsteady engine on Windows-preprocessed inputs."""
    from .RasCmdr import RasCmdr
    from .RasPlan import RasPlan

    project = _initialize(context)
    number = _plan_number(project, plan_number)
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Plan {number} not found before Linux compute")
    hdf_path = Path(str(plan_path) + ".hdf")
    if not series:
        raise ValueError(
            "plan.compute_unsteady_linux requires hydrograph and WSE series specifications"
        )
    series_inputs = _result_series_input_receipts(context, series)
    freshness = _fresh_compute_preflight(
        context,
        hdf_path,
        fresh_result_files,
        require_results_group_absent=bool(
            require_results_group_absent_before_compute
        ),
    )

    engine_root = RasUtils.safe_resolve(Path(str(ras_exe_dir)))
    engine = engine_root / "RasUnsteady"
    if not engine.is_file():
        raise FileNotFoundError(f"Native Linux RasUnsteady not found: {engine}")
    engine_receipt = {
        "path": str(engine),
        "sha256": RasQualification.file_sha256(engine),
        "size": int(engine.stat().st_size),
        "executable": os.access(engine, os.X_OK),
    }
    if not engine_receipt["executable"]:
        raise PermissionError(f"Native Linux RasUnsteady is not executable: {engine}")

    project_folder = Path(str(project.project_folder))
    project_name = str(project.project_name)
    tmp_hdf = project_folder / f"{project_name}.p{number}.tmp.hdf"
    boundary_file = project_folder / f"{project_name}.b{number}"
    plan_row = project.plan_df[project.plan_df["plan_number"] == number]
    if plan_row.empty:
        raise FileNotFoundError(f"Plan metadata {number} not found")
    geom_reference = str(plan_row.iloc[0].get("Geom File", ""))
    geometry_number = RasUtils.normalize_ras_number(geom_reference)
    x_file = project_folder / f"{project_name}.x{geometry_number}"
    prerequisite_paths = {
        "plan_tmp_hdf": tmp_hdf,
        "boundary": boundary_file,
        "geometry_preprocessor": x_file,
    }
    prerequisites = {}
    for name, path in prerequisite_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Linux compute prerequisite missing: {path}")
        prerequisites[name] = {
            "path": str(path),
            "sha256_before": RasQualification.file_sha256(path),
            "size_before": int(path.stat().st_size),
        }

    result = RasCmdr.compute_plan_linux(
        number,
        ras_exe_dir=engine_root,
        ras_object=project,
        timeout_sec=int(timeout_sec),
        dos2unix=bool(dos2unix),
        num_cores=num_cores,
        retry=bool(retry),
        retry_delay_sec=int(retry_delay_sec),
        process_environment=compute_environment,
    )
    native_log = _native_solver_log_receipt(
        project_folder / f"compute_linux_{number}.log"
    )
    result_receipt = RasQualification.results_receipt(
        hdf_path,
        completion_mode="native_linux",
    )
    volume_present = result_receipt["max_abs_volume_error_percent"] is not None
    if not result or not result_receipt["successful"] or not native_log["passed"]:
        return {
            "passed": False,
            "evidence": {
                "compute_result": _object_dict(result),
                "engine": engine_receipt,
                "prerequisites": prerequisites,
                "fresh_compute": freshness,
                "series_inputs": series_inputs,
                "compute_environment": _json_value(compute_environment or {}),
                "results_successful": result_receipt["successful"],
                "max_abs_volume_error_percent": result_receipt[
                    "max_abs_volume_error_percent"
                ],
                "volume_accounting_present": volume_present,
                "results_sha256": result_receipt["file_sha256"],
                "completion_checks": result_receipt.get("completion_checks"),
                "compute_diagnostics": result_receipt.get("compute_diagnostics"),
                "native_solver_log": native_log,
            },
            "diagnostics": {
                "reason": "Native Linux unsteady computation did not produce complete results"
            },
            "artifacts": {"results": result_receipt},
        }
    if defer_series_extraction:
        return {
            "passed": bool(
                result
                and result_receipt["successful"]
                and (not require_volume_accounting or volume_present)
                and (
                    not require_results_group_absent_before_compute
                    or freshness["passed"]
                )
            ),
            "evidence": {
                "compute_result": _object_dict(result),
                "engine": engine_receipt,
                "native_solver_log": native_log,
                "prerequisites": prerequisites,
                "fresh_compute": freshness,
                "series_inputs": series_inputs,
                "compute_environment": _json_value(compute_environment or {}),
                "results_successful": result_receipt["successful"],
                "max_abs_volume_error_percent": result_receipt[
                    "max_abs_volume_error_percent"
                ],
                "volume_accounting_present": volume_present,
                "results_sha256": result_receipt["file_sha256"],
                "series_extraction_deferred": True,
            },
            "artifacts": {"results": result_receipt},
            "context_updates": {
                "qualification_plan_number": number,
                "qualification_plan_hdf": str(hdf_path),
                "qualification_series_specifications": _json_value(series),
                "qualification_linux_engine": engine_receipt,
            },
        }
    result_series = RasQualification.extract_result_series(
        hdf_path,
        series,
        ras_object=project,
    )
    for name, path in prerequisite_paths.items():
        prerequisites[name]["exists_after"] = path.is_file()
        prerequisites[name]["sha256_after"] = (
            RasQualification.file_sha256(path) if path.is_file() else None
        )

    evidence = {
        "compute_result": _object_dict(result),
        "engine": engine_receipt,
        "native_solver_log": native_log,
        "prerequisites": prerequisites,
        "fresh_compute": freshness,
        "series_inputs": series_inputs,
        "compute_environment": _json_value(compute_environment or {}),
        "volume_accounting_present": volume_present,
        "results_successful": result_receipt["successful"],
        "max_abs_volume_error_percent": result_receipt[
            "max_abs_volume_error_percent"
        ],
        "results_sha256": result_receipt["file_sha256"],
        "series": {
            name: {
                "kind": item["kind"],
                "record_count": len(item["records"]),
                "value_columns": item["value_columns"],
            }
            for name, item in result_series.items()
        },
    }
    return {
        "passed": bool(
            result
            and result_receipt["successful"]
            and native_log["passed"]
            and (not require_volume_accounting or volume_present)
            and (
                not require_results_group_absent_before_compute
                or freshness["passed"]
            )
        ),
        "evidence": evidence,
        "artifacts": {"results": result_receipt},
        "series": result_series,
        "context_updates": {
            "qualification_plan_number": number,
            "qualification_plan_hdf": str(hdf_path),
            "qualification_series_specifications": _json_value(series),
            "qualification_linux_engine": engine_receipt,
        },
    }


def results_extract_series(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    series: Optional[Mapping[str, Mapping[str, Any]]] = None,
    expected_results_sha256: Optional[str] = None,
    require_volume_accounting: bool = True,
    completion_mode: str = "windows",
    native_compute_log: Optional[Union[str, Path]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Inspect an existing completed result and extract parity series natively."""
    from .RasPlan import RasPlan

    project = _initialize(context)
    number = _plan_number(
        project,
        plan_number or context.get("qualification_plan_number"),
    )
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Plan {number} not found for result extraction")
    hdf_path = Path(str(plan_path) + ".hdf")
    result_receipt = RasQualification.results_receipt(
        hdf_path,
        completion_mode=completion_mode,
    )
    native_log = None
    if str(completion_mode).strip().lower() == "native_linux":
        log_value = native_compute_log or f"compute_linux_{number}.log"
        native_log = _native_solver_log_receipt(_project_path(context, log_value))
    if expected_results_sha256 is not None and (
        result_receipt["file_sha256"] != str(expected_results_sha256).lower()
    ):
        raise RuntimeError(
            "Existing result fingerprint does not match the qualified compute artifact: "
            f"{result_receipt['file_sha256']} != {expected_results_sha256}"
        )
    series_specs = series or context.get("qualification_series_specifications")
    if not isinstance(series_specs, Mapping) or not series_specs:
        raise ValueError("results.extract_series requires named series specifications")
    series_inputs = _result_series_input_receipts(context, series_specs)
    result_series = RasQualification.extract_result_series(
        hdf_path,
        series_specs,
        ras_object=project,
    )
    volume_present = result_receipt["max_abs_volume_error_percent"] is not None
    series_checks = {
        str(name): bool(
            isinstance(item, Mapping)
            and item.get("records")
            and item.get("value_columns")
        )
        for name, item in result_series.items()
    }
    evidence = {
        "plan_number": number,
        "results_sha256": result_receipt["file_sha256"],
        "expected_results_sha256": expected_results_sha256,
        "results_fingerprint_matches": expected_results_sha256 is None
        or result_receipt["file_sha256"] == str(expected_results_sha256).lower(),
        "results_successful": result_receipt["successful"],
        "max_abs_volume_error_percent": result_receipt[
            "max_abs_volume_error_percent"
        ],
        "volume_accounting_present": volume_present,
        "completion_mode": str(completion_mode).strip().lower(),
        "native_solver_log": native_log,
        "series_inputs": series_inputs,
        "series_checks": series_checks,
        "series": {
            name: {
                "kind": item["kind"],
                "extraction_backend": item.get("extraction_backend"),
                "record_count": len(item["records"]),
                "value_columns": item["value_columns"],
            }
            for name, item in result_series.items()
        },
    }
    return {
        "passed": bool(
            result_receipt["successful"]
            and (native_log is None or native_log["passed"])
            and (not require_volume_accounting or volume_present)
            and series_checks
            and all(series_checks.values())
        ),
        "evidence": evidence,
        "artifacts": {"results": result_receipt},
        "series": result_series,
        "context_updates": {
            "qualification_plan_number": number,
            "qualification_plan_hdf": str(hdf_path),
            "qualification_series_specifications": _json_value(series_specs),
        },
    }


def mapper_result_layers(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    profile: str = "Max",
    profile_index: int = 2147483647,
    terrain_name: Optional[str] = None,
    wse: bool = True,
    depth: bool = True,
    velocity: bool = False,
    froude: bool = False,
    shear_stress: bool = False,
    depth_x_velocity: bool = False,
    depth_x_velocity_sq: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Register and verify dynamic RAS Mapper result-map child layers."""
    from .RasMap import RasMap
    from .RasProcess import RasProcess

    project = _initialize(context)
    number = _plan_number(project, plan_number or context.get("qualification_plan_number"))
    ensured = RasMap.ensure_results_plan_layer(number, ras_object=project)
    requested_flags = {
        "wse": bool(wse),
        "depth": bool(depth),
        "velocity": bool(velocity),
        "froude": bool(froude),
        "shear_stress": bool(shear_stress),
        "depth_x_velocity": bool(depth_x_velocity),
        "depth_x_velocity_sq": bool(depth_x_velocity_sq),
    }
    requested = [key for key, enabled in requested_flags.items() if enabled]
    if not requested:
        raise ValueError("mapper.result_layers requires at least one result map type")

    created = {}
    for key in requested:
        xml_name, display_name, _ = RasProcess.MAP_TYPES[key]
        created[key] = RasMap.add_results_map_layer(
            host_plan_name=str(ensured["name"]),
            layer_name=display_name,
            map_type=xml_name,
            terrain_name=terrain_name,
            profile_index=int(profile_index),
            profile_name=str(profile),
            checked=True,
            replace_existing=True,
            ras_object=project,
        )

    layers = RasMap.list_results_plans(ras_object=project)
    child_layers = RasMap.list_results_map_layers(ras_object=project)
    expected_filename = Path(str(ensured["filename"])).name.lower()
    matched_plans = [
        item
        for item in layers
        if Path(str(item["filename"])).name.lower() == expected_filename
    ]
    child_checks = {}
    matched_children = {}
    for key in requested:
        xml_name, display_name, _ = RasProcess.MAP_TYPES[key]
        candidates = [
            item
            for item in child_layers
            if item.get("parent_plan") == ensured["name"]
            and item.get("name") == display_name
        ]
        matched_children[key] = candidates
        child_checks[key] = bool(
            len(candidates) == 1
            and candidates[0].get("checked") is True
            and candidates[0].get("map_parameters", {}).get("MapType") == xml_name
            and candidates[0].get("map_parameters", {}).get("ProfileName")
            == str(profile)
            and candidates[0].get("map_parameters", {}).get("ProfileIndex")
            == str(int(profile_index))
            and (
                terrain_name is None
                or candidates[0].get("map_parameters", {}).get("Terrain")
                == terrain_name
            )
        )
    rasmap_path = Path(str(ensured["rasmap_path"]))
    evidence = {
        "ensured": _json_value(ensured),
        "created": _json_value(created),
        "requested_map_types": requested,
        "result_plans": layers,
        "matched_plans": matched_plans,
        "result_map_layers": child_layers,
        "matched_children": matched_children,
        "child_checks": child_checks,
        "rasmap": _file_record(rasmap_path),
    }
    return {
        "passed": bool(
            len(matched_plans) == 1
            and child_checks
            and all(child_checks.values())
        ),
        "evidence": evidence,
        "artifacts": {"rasmap": evidence["rasmap"]},
    }


def mapper_export_geotiff(
    context: Mapping[str, Any],
    plan_number: Optional[Union[str, int]] = None,
    profile: str = "Max",
    output_path: Union[str, Path] = "qualification-maps",
    timeout: int = 1800,
    **map_flags: Any,
) -> Dict[str, Any]:
    """Export stored RAS Mapper maps and inspect the resulting GeoTIFF content."""
    from .RasProcess import RasProcess

    project = _initialize(context)
    number = _plan_number(project, plan_number or context.get("qualification_plan_number"))
    default_flags = {"wse": True, "depth": True, "velocity": True}
    flag_names = (
        "wse",
        "depth",
        "velocity",
        "froude",
        "shear_stress",
        "depth_x_velocity",
        "depth_x_velocity_sq",
        "inundation_boundary",
    )
    flags = {
        key: bool(map_flags.get(key, default_flags.get(key, False)))
        for key in flag_names
    }
    maps = RasProcess.store_maps(
        number,
        output_path=_project_path(context, output_path),
        profile=profile,
        ras_object=project,
        timeout=int(timeout),
        **flags,
    )
    requested = [key for key, enabled in flags.items() if enabled]
    requested_raster_maps = [
        key for key in requested if key != "inundation_boundary"
    ]
    raster_paths_by_type: Dict[str, List[Path]] = {}
    rasters_by_type: Dict[str, List[Dict[str, Any]]] = {}
    raster_receipt_errors: Dict[str, List[Dict[str, str]]] = {}
    for map_type in requested_raster_maps:
        values = maps.get(map_type) or []
        raster_paths = sorted(
            {
                Path(path)
                for path in values
                if str(path).lower().endswith((".tif", ".tiff"))
            },
            key=lambda item: str(item),
        )
        raster_paths_by_type[map_type] = raster_paths
        type_receipts: List[Dict[str, Any]] = []
        type_errors: List[Dict[str, str]] = []
        for raster_path in raster_paths:
            try:
                type_receipts.append(
                    RasQualification.raster_receipt(raster_path)
                )
            except Exception as exc:
                # Qualification is evidence-first: retain which requested
                # artifact was unreadable, then fail the action closed.
                type_errors.append(
                    {
                        "path": str(raster_path),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        rasters_by_type[map_type] = type_receipts
        if type_errors:
            raster_receipt_errors[map_type] = type_errors

    receipts_by_path = {
        str(item["path"]): item
        for type_receipts in rasters_by_type.values()
        for item in type_receipts
    }
    receipts = [receipts_by_path[path] for path in sorted(receipts_by_path)]
    depth_receipts = rasters_by_type.get("depth") or []
    depth = depth_receipts[0] if depth_receipts else None

    requested_map_receipt_checks: Dict[str, Dict[str, Any]] = {}
    for map_type in requested_raster_maps:
        paths = raster_paths_by_type[map_type]
        type_receipts = rasters_by_type[map_type]
        checks = {
            "inventory_present": map_type in maps,
            "geotiff_present": bool(paths),
            "every_geotiff_receipted": len(type_receipts) == len(paths),
            "every_raster_georeferenced": bool(type_receipts)
            and all(
                item.get("driver") == "GTiff"
                and bool(item.get("crs_wkt"))
                and len(item.get("transform") or []) == 6
                and int(item.get("width", 0)) > 0
                and int(item.get("height", 0)) > 0
                and int(item.get("band_count", 0)) > 0
                for item in type_receipts
            ),
            "every_raster_has_valid_values": bool(type_receipts)
            and all(
                int(item.get("valid_value_count", 0)) > 0
                for item in type_receipts
            ),
            "no_receipt_errors": map_type not in raster_receipt_errors,
        }
        requested_map_receipt_checks[map_type] = {
            "listed_output_count": len(maps.get(map_type) or []),
            "geotiff_count": len(paths),
            "raster_receipt_count": len(type_receipts),
            "checks": checks,
            "passed": all(checks.values()),
        }

    evidence = {
        "map_inventory": _json_value(maps),
        "requested_maps": requested,
        "requested_raster_maps": requested_raster_maps,
        "raster_count": len(receipts),
        "rasters": receipts,
        "rasters_by_type": rasters_by_type,
        "raster_receipt_errors": raster_receipt_errors,
        "requested_map_receipt_checks": requested_map_receipt_checks,
    }
    requested_map_checks = {
        key: bool(item["passed"])
        for key, item in requested_map_receipt_checks.items()
    }
    if "inundation_boundary" in requested:
        boundary_paths = [
            Path(path)
            for path in (maps.get("inundation_boundary") or [])
        ]
        requested_map_checks["inundation_boundary"] = bool(boundary_paths) and all(
            path.is_file() and path.suffix.lower() == ".shp"
            for path in boundary_paths
        )
    raster_content_complete = bool(requested_map_receipt_checks) and all(
        item["passed"] for item in requested_map_receipt_checks.values()
    )
    evidence["requested_map_checks"] = requested_map_checks
    evidence["raster_content_complete"] = raster_content_complete
    artifacts: Dict[str, Any] = {
        # Preserve the original flat inventory for existing receipt consumers.
        "map_rasters": receipts,
        # This keyed inventory is the canonical parity-comparison surface.
        "map_rasters_by_type": rasters_by_type,
    }
    if depth is not None:
        artifacts["depth_grid"] = depth
    return {
        "passed": bool(
            requested_map_checks
            and all(requested_map_checks.values())
            and raster_content_complete
            and (not flags["depth"] or depth is not None)
        ),
        "evidence": evidence,
        "artifacts": artifacts,
    }


def restart_recovery(
    context: Mapping[str, Any],
    restart_plan_number: Union[str, int],
    restart_filename: Union[str, Path],
    baseline_plan_number: Optional[Union[str, int]] = None,
    series: Optional[Mapping[str, Mapping[str, Any]]] = None,
    series_tolerances: Optional[Mapping[str, Mapping[str, Any]]] = None,
    max_volume_error_difference_percent: Optional[float] = None,
    timeout_sec: int = 3600,
    num_cores: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Run a fixture restart plan from a real prior-run restart file."""
    from .RasCmdr import RasCmdr
    from .RasPlan import RasPlan
    from .RasUnsteady import RasUnsteady

    project = _initialize(context)
    number = _plan_number(project, restart_plan_number)
    baseline_number = _plan_number(
        project,
        baseline_plan_number or context.get("qualification_plan_number"),
    )
    if baseline_number == number:
        raise ValueError("baseline_plan_number must differ from restart_plan_number")
    series_specs = series or context.get("qualification_series_specifications")
    if not isinstance(series_specs, Mapping) or not series_specs:
        raise ValueError("restart recovery requires hydrograph and WSE series specifications")
    kinds = {
        str(specification.get("kind", "")).strip().lower()
        for specification in series_specs.values()
        if isinstance(specification, Mapping)
    }
    if "profile_line_flow" not in kinds or not any(
        isinstance(specification, Mapping)
        and str(specification.get("kind", "")).strip().lower() == "mesh_cells"
        and str(specification.get("variable", "")).strip().lower() == "water surface"
        for specification in series_specs.values()
    ):
        raise ValueError("restart recovery requires profile-line flow and mesh-cell WSE series")
    if not isinstance(series_tolerances, Mapping) or set(series_tolerances) != set(series_specs):
        raise ValueError(
            "series_tolerances must cover every restart recovery series exactly"
        )
    if max_volume_error_difference_percent is None:
        raise ValueError("max_volume_error_difference_percent is required")
    volume_limit = float(max_volume_error_difference_percent)
    if not math.isfinite(volume_limit) or volume_limit < 0:
        raise ValueError("max_volume_error_difference_percent must be finite and non-negative")

    baseline_plan_path = RasPlan.get_plan_path(baseline_number, ras_object=project)
    if baseline_plan_path is None:
        raise FileNotFoundError(f"Baseline plan {baseline_number} not found")
    baseline_hdf = Path(str(baseline_plan_path) + ".hdf")
    baseline_results = RasQualification.results_receipt(baseline_hdf)
    baseline_series = RasQualification.extract_result_series(
        baseline_hdf,
        series_specs,
        ras_object=project,
    )
    plan_row = project.plan_df[project.plan_df["plan_number"] == number]
    if plan_row.empty:
        raise FileNotFoundError(f"Restart plan {number} not found")
    unsteady_number = str(plan_row["unsteady_number"].iloc[0]).zfill(2)
    unsteady_path = RasPlan.get_unsteady_path(unsteady_number, project)
    if unsteady_path is None:
        raise FileNotFoundError(f"Unsteady file {unsteady_number} not found")
    restart_path = _required_file(context, restart_filename, label="restart file")
    RasUnsteady.set_restart_settings(
        unsteady_path,
        use_restart=True,
        restart_filename=str(restart_path),
        ras_object=project,
    )
    settings = RasUnsteady.get_restart_settings(unsteady_path, ras_object=project)
    result = RasCmdr.compute_plan(
        number,
        ras_object=project,
        force_rerun=True,
        verify=True,
        num_cores=num_cores,
        timeout_sec=int(timeout_sec),
    )
    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Restart plan {number} disappeared")
    results = RasQualification.results_receipt(Path(str(plan_path) + ".hdf"))
    restart_series = RasQualification.extract_result_series(
        Path(str(plan_path) + ".hdf"),
        series_specs,
        ras_object=project,
    )
    series_comparisons: Dict[str, Any] = {}
    for series_name, tolerance in series_tolerances.items():
        if not isinstance(tolerance, Mapping):
            raise TypeError(f"Restart series tolerance {series_name!r} must be a mapping")
        series_comparisons[str(series_name)] = RasQualification.compare_numeric_frames(
            pd.DataFrame(baseline_series[series_name]["records"]),
            pd.DataFrame(restart_series[series_name]["records"]),
            key_columns=tolerance.get("key_columns") or [],
            tolerances=tolerance.get("columns") or {},
        )
    baseline_volume = baseline_results.get("max_abs_volume_error_percent")
    restart_volume = results.get("max_abs_volume_error_percent")
    volume_difference = (
        abs(float(baseline_volume) - float(restart_volume))
        if baseline_volume is not None and restart_volume is not None
        else None
    )
    volume_matches = volume_difference is not None and volume_difference <= volume_limit
    evidence = {
        "restart_plan_number": number,
        "baseline_plan_number": baseline_number,
        "restart_file": _file_record(restart_path),
        "restart_settings": settings,
        "compute_result": _object_dict(result),
        "results_successful": results["successful"],
        "results_sha256": results["file_sha256"],
        "baseline_results_sha256": baseline_results["file_sha256"],
        "series_comparisons": series_comparisons,
        "volume_error_difference_percent": volume_difference,
        "max_volume_error_difference_percent": volume_limit,
        "volume_error_matches": volume_matches,
    }
    return {
        "passed": bool(
            result
            and settings["use_restart"]
            and baseline_results["successful"]
            and results["successful"]
            and series_comparisons
            and all(item["passed"] for item in series_comparisons.values())
            and volume_matches
        ),
        "evidence": evidence,
        "artifacts": {
            "restart_baseline_results": baseline_results,
            "restart_results": results,
        },
    }


def failed_run_diagnostics(
    context: Mapping[str, Any],
    failing_plan_number: Union[str, int],
    expected_patterns: Sequence[str],
    timeout_sec: int = 900,
    **_: Any,
) -> Dict[str, Any]:
    """Execute an intentionally invalid fixture plan and retain its diagnostics."""
    import re

    from .RasCmdr import RasCmdr
    from .RasPlan import RasPlan
    from .hdf import HdfResultsPlan
    from .results import ResultsParser

    if not expected_patterns:
        raise ValueError("expected_patterns must name at least one approved failure signature")
    project = _initialize(context)
    number = _plan_number(project, failing_plan_number)
    caught = None
    result = None
    try:
        result = RasCmdr.compute_plan(
            number,
            ras_object=project,
            force_rerun=True,
            verify=True,
            timeout_sec=int(timeout_sec),
        )
    except Exception as exc:  # expected-failure fixture; preserve type and text
        caught = {"type": type(exc).__name__, "message": str(exc)}

    plan_path = RasPlan.get_plan_path(number, ras_object=project)
    if plan_path is None:
        raise FileNotFoundError(f"Failing plan {number} not found")
    plan_path = Path(plan_path)
    hdf_path = Path(str(plan_path) + ".hdf")
    messages = ""
    if hdf_path.is_file():
        messages = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path) or ""
    message_files = []
    for candidate in sorted(plan_path.parent.glob(f"{plan_path.stem}*")):
        lower = candidate.name.lower()
        if candidate.is_file() and (
            lower.endswith((".computemsgs.txt", ".comp_msgs.txt"))
            or ".bco" in lower
        ):
            text = candidate.read_text(encoding="utf-8", errors="replace")
            messages += "\n" + text
            message_files.append(_file_record(candidate))
    matches = {
        pattern: bool(re.search(pattern, messages, flags=re.IGNORECASE | re.MULTILINE))
        for pattern in expected_patterns
    }
    parsed = ResultsParser.parse_compute_messages(messages)
    evidence = {
        "failing_plan_number": number,
        "compute_result": _object_dict(result) if result is not None else None,
        "caught_exception": caught,
        "message_length": len(messages),
        "message_sha256": hashlib.sha256(messages.encode("utf-8")).hexdigest(),
        "message_files": message_files,
        "expected_pattern_matches": matches,
        "parsed_diagnostics": _json_value(parsed),
        "workspace_retained": str(context["project_folder"]),
    }
    computation_failed = caught is not None or not bool(result)
    return {
        "passed": bool(computation_failed and messages and all(matches.values())),
        "evidence": evidence,
        "diagnostics": evidence,
    }


def project_locking(
    context: Mapping[str, Any],
    lock_name: str = ".ras-commander-project.lock",
    **_: Any,
) -> Dict[str, Any]:
    """Prove cross-process project-lock contention, release, and recovery."""
    project_folder = RasUtils.safe_resolve(Path(str(context["project_folder"])))
    before_fingerprint = RasQualification.project_tree_fingerprint(project_folder)

    contender_code = (
        "import json,sys\n"
        "from ras_commander.RasQualification import RasQualification\n"
        "project,lock_name,owner=sys.argv[1:4]\n"
        "try:\n"
        "    receipt=RasQualification.acquire_project_lock(project,owner,lock_name)\n"
        "except FileExistsError as exc:\n"
        "    print(json.dumps({'status':'blocked','error_type':type(exc).__name__,'message':str(exc)}))\n"
        "    raise SystemExit(23)\n"
        "release=RasQualification.release_project_lock(receipt)\n"
        "print(json.dumps({'status':'acquired_released','token':receipt['token'],'released':release['released']}))\n"
    )

    def run_contender(owner: str) -> Dict[str, Any]:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                contender_code,
                str(project_folder),
                lock_name,
                owner,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output_lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        payload = json.loads(output_lines[-1]) if output_lines else {}
        return {
            "return_code": result.returncode,
            "stdout_sha256": hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256((result.stderr or "").encode("utf-8")).hexdigest(),
            "payload": payload,
        }

    holder = RasQualification.acquire_project_lock(
        project_folder,
        owner=f"qualification-holder:{context['fixture']['id']}",
        lock_name=lock_name,
    )
    observed = RasQualification.inspect_project_lock(project_folder, lock_name=lock_name)
    contention = run_contender(
        owner=f"qualification-contender:{context['fixture']['id']}"
    )

    release = RasQualification.release_project_lock(holder)
    absent_after_release = (
        RasQualification.inspect_project_lock(project_folder, lock_name=lock_name) is None
    )
    recovery = run_contender(
        owner=f"qualification-recovery:{context['fixture']['id']}"
    )
    after_fingerprint = RasQualification.project_tree_fingerprint(project_folder)
    checks = {
        "holder_acquired": holder.get("acquired") is True,
        "holder_observed_exactly": bool(
            observed
            and observed.get("token") == holder.get("token")
            and observed.get("file_sha256") == holder.get("file_sha256")
        ),
        "cross_process_contender_blocked": bool(
            contention.get("return_code") == 23
            and (contention.get("payload") or {}).get("status") == "blocked"
            and (contention.get("payload") or {}).get("error_type") == "FileExistsError"
        ),
        "released": release.get("released") is True,
        "absent_after_release": absent_after_release,
        "cross_process_reacquired_with_new_token": bool(
            recovery.get("return_code") == 0
            and (recovery.get("payload") or {}).get("status") == "acquired_released"
            and (recovery.get("payload") or {}).get("released") is True
            and (recovery.get("payload") or {}).get("token") != holder.get("token")
        ),
        "recovery_released": (
            (recovery.get("payload") or {}).get("released") is True
        ),
        "project_content_restored": before_fingerprint == after_fingerprint,
    }
    evidence = {
        "lock_name": lock_name,
        "checks": checks,
        "holder": holder,
        "observed_holder": observed,
        "contention": contention,
        "release": release,
        "recovery_process": recovery,
        "project_fingerprint_before": before_fingerprint,
        "project_fingerprint_after": after_fingerprint,
    }
    return {"passed": bool(all(checks.values())), "evidence": evidence}


def concurrency_prefix_isolation(
    context: Mapping[str, Any],
    task_count: int = 2,
    wine_binary: str = "wine",
    timeout: int = 300,
    template_prefix: Optional[Union[str, Path]] = None,
    initialize_prefixes: bool = False,
    display: Optional[str] = None,
    python_site_packages: Optional[Union[str, Path]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Create concurrent prefixes/project copies and prove identity and disjoint writes."""
    from concurrent.futures import ThreadPoolExecutor

    count = int(task_count)
    if count < 2:
        raise ValueError("task_count must be at least 2")
    root = Path(str(context["run_directory"])) / "concurrency-isolation"
    template_value = template_prefix or (
        (context.get("wine_prefix_receipt") or {}).get("template_prefix")
    )
    if template_value is None:
        raise ValueError("concurrency.prefix_isolation requires a prepared template_prefix")
    template_path = RasUtils.safe_resolve(Path(str(template_value)))
    source_path = RasUtils.safe_resolve(Path(str(context["source_project"])))
    template_before = RasQualification.project_tree_fingerprint(template_path)
    source_before = RasQualification.project_tree_fingerprint(source_path)
    wine_receipt = dict(context.get("wine_prefix_receipt") or {})
    reference_installation = wine_receipt.get("isolated_installation")
    reference_prefix = Path(str(wine_receipt.get("prefix") or context.get("wine_prefix") or ""))
    reference_ras = Path(str(wine_receipt.get("isolated_ras_executable") or ""))
    ras_relative = None
    if reference_prefix and reference_ras:
        try:
            ras_relative = reference_ras.relative_to(reference_prefix)
        except ValueError:
            pass

    reference_packages = dict(wine_receipt.get("runtime_packages") or {})
    package_relative = None
    if python_site_packages is not None:
        package_relative = Path(str(python_site_packages))
    elif reference_packages.get("site_packages") and reference_prefix:
        try:
            package_relative = Path(str(reference_packages["site_packages"])).relative_to(
                reference_prefix
            )
        except ValueError:
            pass
    expected_packages = {
        str(name): str(item.get("expected_version"))
        for name, item in dict(reference_packages.get("checks") or {}).items()
        if isinstance(item, Mapping) and item.get("expected_version")
    }
    overrides = wine_receipt.get("wineboot_dll_overrides")

    def create(index: int) -> Dict[str, Any]:
        prefix = RasQualification.create_isolated_wine_prefix(
            root / "prefixes",
            task_id=f"{context['fixture']['id']}-{index}",
            wine_executable=wine_binary,
            initialize=bool(initialize_prefixes),
            timeout=int(timeout),
            display=display,
            template_prefix=template_value,
            wineboot_dll_overrides=str(overrides) if overrides else None,
        )
        stage = RasQualification.stage_project(
            context["source_project"],
            root / "projects",
            task_id=f"{context['fixture']['id']}-{index}",
        )
        marker = Path(prefix["prefix"]) / ".ras-commander-prefix.json"
        prefix["marker_sha256"] = RasQualification.file_sha256(marker)
        task_marker = Path(stage["destination"]) / ".ras-qualification-task-write.json"
        task_marker.write_text(
            json.dumps(
                {
                    "fixture_id": str(context["fixture"]["id"]),
                    "task_index": index,
                    "prefix": str(prefix["prefix"]),
                    "project": str(stage["destination"]),
                },
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        identity: Dict[str, Any] = {
            "installation_checked": False,
            "installation_matches": False,
            "runtime_packages_checked": False,
            "runtime_packages_match": False,
        }
        if reference_installation and ras_relative is not None:
            installation = RasQualification.inspect_installation(
                Path(prefix["prefix"]) / ras_relative,
                expected_version=str(context.get("expected_version", "7.0.1")),
            )
            reference_components = dict(reference_installation.get("components") or {})
            component_matches = {
                name: bool(
                    name in installation.get("components", {})
                    and component.get("sha256")
                    == installation["components"][name].get("sha256")
                    and (component.get("pe") or {}).get("architecture")
                    == (installation["components"][name].get("pe") or {}).get("architecture")
                )
                for name, component in reference_components.items()
            }
            identity.update(
                {
                    "installation_checked": True,
                    "installation_matches": bool(
                        installation.get("version_matches")
                        and installation.get("required_components_present")
                        and component_matches
                        and all(component_matches.values())
                    ),
                    "installation": installation,
                    "component_matches": component_matches,
                }
            )
        if package_relative is not None and expected_packages:
            packages = RasQualification.inspect_python_packages(
                Path(prefix["prefix"]) / package_relative,
                expected_packages,
            )
            identity.update(
                {
                    "runtime_packages_checked": True,
                    "runtime_packages_match": packages.get("all_match") is True,
                    "runtime_packages": packages,
                }
            )
        return {
            "task_index": index,
            "prefix": prefix,
            "project": stage,
            "project_task_marker": _file_record(task_marker),
            "project_fingerprint_after_task_write": (
                RasQualification.project_tree_fingerprint(stage["destination"])
            ),
            "identity": identity,
        }

    with ThreadPoolExecutor(max_workers=count) as executor:
        tasks = list(executor.map(create, range(count)))
    prefixes = [item["prefix"]["prefix"] for item in tasks]
    projects = [item["project"]["destination"] for item in tasks]
    source_fingerprints = {
        item["project"]["source_fingerprint"] for item in tasks
    }
    destination_fingerprints = {
        item["project"]["destination_fingerprint"] for item in tasks
    }
    template_after = RasQualification.project_tree_fingerprint(template_path)
    source_after = RasQualification.project_tree_fingerprint(source_path)
    production_wine = (
        str(context.get("executor_profile")) == "linux_wine_windows_ras"
    )
    checks = {
        "prefixes_unique": len(set(prefixes)) == count,
        "projects_unique": len(set(projects)) == count,
        "single_source_fingerprint": len(source_fingerprints) == 1,
        "destinations_match_source": destination_fingerprints == source_fingerprints,
        "all_prefixes_initialized": all(item["prefix"]["initialized"] for item in tasks),
        "prepared_clones_skip_wineboot": all(
            item["prefix"].get("initialization_mode") == "prepared_template_clone"
            for item in tasks
        ) if not initialize_prefixes else True,
        "template_immutable": template_before == template_after,
        "source_project_immutable": source_before == source_after,
        "template_fingerprint_matches_clones": all(
            item["prefix"].get("template_fingerprint") == template_before
            for item in tasks
        ),
        "task_writes_are_disjoint": all(
            Path(item["project_task_marker"]["path"]).parent
            == Path(item["project"]["destination"])
            and json.loads(
                Path(item["project_task_marker"]["path"]).read_text(encoding="utf-8")
            )["task_index"]
            == item["task_index"]
            for item in tasks
        ),
        "installation_identity_matches": all(
            item["identity"]["installation_checked"]
            and item["identity"]["installation_matches"]
            for item in tasks
        ) if production_wine else True,
        "runtime_packages_match": all(
            item["identity"]["runtime_packages_checked"]
            and item["identity"]["runtime_packages_match"]
            for item in tasks
        ) if production_wine else True,
    }
    return {
        "passed": bool(all(checks.values())),
        "evidence": {
            "task_count": count,
            "checks": checks,
            "template_fingerprint_before": template_before,
            "template_fingerprint_after": template_after,
            "source_fingerprint_before": source_before,
            "source_fingerprint_after": source_after,
            "tasks": tasks,
        },
    }


def inspect_artifact(
    context: Mapping[str, Any],
    artifact_type: str,
    path: Union[str, Path],
    require_change: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Content validator for fixture-specific GUI/command actions.

    This handler performs no product action by itself and therefore is suitable
    only after an earlier operation in the same manifest created or changed the
    artifact.  It is deliberately explicit about that limitation in evidence.
    """
    resolved = _required_file(context, path, label=f"{artifact_type} artifact")
    kind = artifact_type.strip().lower()
    if kind == "geometry":
        receipt = RasQualification.geometry_receipt(resolved)
    elif kind == "results":
        receipt = RasQualification.results_receipt(resolved)
    elif kind in {"raster", "terrain", "depth_grid"}:
        receipt = RasQualification.raster_receipt(resolved)
    else:
        receipt = _file_record(resolved)
    before = context.get(f"{kind}_fingerprint_before")
    current = receipt.get("geometry_fingerprint") or receipt.get("data_fingerprint") or receipt.get("sha256")
    changed = before is None or current != before
    evidence = {
        "validator_only": True,
        "artifact_type": kind,
        "receipt": receipt,
        "change_required": bool(require_change),
        "changed": changed,
    }
    return {
        "passed": bool(receipt and (not require_change or (before is not None and changed))),
        "evidence": evidence,
        "artifacts": {kind: receipt},
    }


ACTION_HANDLERS = {
    "wine_prefix.create": wine_prefix_create,
    "project.open": project_open,
    "project.save": project_save,
    "path.spaces": path_variant_open,
    "path.long": path_variant_open,
    "projection.select": projection_select,
    "terrain.import": terrain_import,
    "terrain.build_pyramids": terrain_build_pyramids,
    "terrain.associate": terrain_associate,
    "geometry.2d_area_create": geometry_area_or_perimeter,
    "geometry.perimeter_edit": geometry_area_or_perimeter,
    "mesh.generate_initial": mesh_generate,
    "mesh.regenerate": mesh_generate,
    "mesh.refinement_region": mesh_refinement_region,
    "mesh.breakline": mesh_breakline,
    "boundary.associate": boundary_associate,
    "boundary.conflict_repair": boundary_conflict_repair,
    "properties.mannings": mannings_roundtrip,
    "properties.infiltration": infiltration_properties,
    "properties.land_cover": land_cover_properties,
    "properties.geometry_tables": geometry_property_tables,
    "plan.preprocess": plan_preprocess,
    "plan.compute_unsteady": plan_compute_unsteady,
    "mapper.result_layers": mapper_result_layers,
    "mapper.export_geotiff": mapper_export_geotiff,
    "recovery.restart": restart_recovery,
    "diagnostics.failed_run": failed_run_diagnostics,
    "locking.project": project_locking,
    "concurrency.prefix_isolation": concurrency_prefix_isolation,
    "results.extract_series": results_extract_series,
}


def execute(context: Mapping[str, Any], **parameters: Any) -> Dict[str, Any]:
    """Dispatch the current required operation to its built-in real action."""
    operation_id = str(context.get("operation_id", ""))
    handler = ACTION_HANDLERS.get(operation_id)
    if handler is None:
        raise NotImplementedError(
            f"No built-in real action for {operation_id}; configure a "
            "fixture-specific handler that performs and validates this operation"
        )
    return handler(context, **parameters)


__all__ = [
    "ACTION_HANDLERS",
    "execute",
    "project_open",
    "project_save",
    "path_variant_open",
    "wine_prefix_create",
    "projection_select",
    "terrain_import",
    "terrain_build_pyramids",
    "terrain_associate",
    "geometry_area_or_perimeter",
    "mesh_generate",
    "mesh_refinement_region",
    "mesh_breakline",
    "boundary_associate",
    "boundary_conflict_repair",
    "mannings_roundtrip",
    "land_cover_properties",
    "infiltration_properties",
    "geometry_property_tables",
    "plan_preprocess",
    "plan_compute_unsteady",
    "plan_compute_unsteady_linux",
    "results_extract_series",
    "mapper_result_layers",
    "mapper_export_geotiff",
    "restart_recovery",
    "failed_run_diagnostics",
    "project_locking",
    "concurrency_prefix_isolation",
    "inspect_artifact",
]
