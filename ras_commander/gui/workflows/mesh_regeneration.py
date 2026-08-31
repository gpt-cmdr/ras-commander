"""
Mesh Regeneration workflow with iterative error correction.

Regenerates 2D mesh in RASMapper after geometry file changes.
If face perimeter errors occur, simplifies the geometry near
the error and retries with adjusted cell size.

This is the critical workflow for Glenn's ras-agent pipeline.

Workflow (single attempt):
1. Capture the selected geometry's terrain/classification associations
2. Launch the project with its configured HEC-RAS version
3. Transactionally displace only the selected geometry HDF
4. Open RASMapper and save the exact registered geometry from modified .g## text
5. Validate the imported 2D perimeter, close the owned process tree, and restore
   the captured associations before committing the replacement HDF

Iterative workflow (with error correction):
1. Attempt mesh regeneration
2. Check HDF for valid mesh (datasets present, cell count > 0)
3. If invalid: close HEC-RAS, simplify perimeter geometry, adjust cell size
4. Write simplified geometry back to .g## file
5. Retry (up to max_iterations)
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = None
    WIN32_AVAILABLE = False

from ...LoggingConfig import get_logger
from ...Decorators import log_call
from ..win32_primitives import Win32Primitives
from ..hecras_elements import HecRasElements
from ..rasmapper_elements import RasMapperElements
from ..workflow_base import WorkflowStep, WorkflowResult, WorkflowExecutor
from ..constants import Win32Constants

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Geometry file helpers (read/write perimeter from .g## ASCII)
# ---------------------------------------------------------------------------

def _get_2d_area_name(geometry_file: Path) -> Optional[str]:
    """Return the first 2D flow area name in a .g## file, or None.

    Delegates to GeomStorage, which identifies 2D flow areas by the modern
    HEC-RAS 6.x/7.0 ``Storage Area Is2D= -1`` representation. (The legacy
    ``2D Flow Area=`` token this module used historically is not written by
    current HEC-RAS, so the previous regex matched nothing.)
    """
    from ...geom.GeomStorage import GeomStorage
    try:
        df = GeomStorage.get_storage_areas(geometry_file, exclude_2d=False)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read storage areas from {Path(geometry_file).name}: {e}")
        return None
    if df is None or df.empty or "Is2D" not in df.columns:
        return None
    twod = df[df["Is2D"]]
    if twod.empty:
        return None
    return str(twod.iloc[0]["Name"])


def _read_perimeter_coords(geometry_file: Path) -> Optional[List[Tuple[float, float]]]:
    """Read the 2D flow area perimeter ring from a .g## file.

    Delegates to GeomStorage, which parses the ``Storage Area Surface Line=``
    16-char fixed-width XY block of the 2D-flagged storage area.
    """
    from ...geom.GeomStorage import GeomStorage
    try:
        gdf = GeomStorage.get_storage_area_polygons(geometry_file, exclude_2d=False)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read perimeter from {Path(geometry_file).name}: {e}")
        return None
    if gdf is None or len(gdf) == 0:
        return None
    twod = gdf[gdf["is_2d"]] if "is_2d" in gdf.columns else gdf
    if len(twod) == 0:
        return None
    poly = twod.iloc[0].geometry
    if poly is None:
        return None
    return [(float(x), float(y)) for x, y in poly.exterior.coords]


def _read_cell_size(geometry_file: Path) -> Optional[float]:
    """Read the 2D flow area nominal cell size (point-generation dx) from a .g##.

    Delegates to GeomStorage; the value lives in ``Storage Area Point Generation
    Data=dx,dy,,`` rather than the legacy ``2D Flow Area Cell Size=`` token.
    """
    from ...geom.GeomStorage import GeomStorage
    try:
        df = GeomStorage.get_2d_flow_area_settings(geometry_file)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read 2D settings from {Path(geometry_file).name}: {e}")
        return None
    if df is None or df.empty:
        return None
    pgd = df.iloc[0].get("point_generation_data")
    if pgd is None:
        return None
    try:
        first = pgd.split(",")[0] if isinstance(pgd, str) else pgd[0]
        return float(first)
    except (ValueError, IndexError, TypeError):
        return None


def _write_perimeter_and_cell_size(
    geometry_file: Path,
    area_name: str,
    coords: List[Tuple[float, float]],
    cell_size: float,
) -> bool:
    """Write a (simplified) perimeter ring + nominal cell size back to the .g##.

    Delegates to ``GeomStorage.set_2d_flow_area_perimeter``, which writes the
    modern ``Storage Area`` / ``Storage Area Surface Line=`` /
    ``Storage Area Point Generation Data=`` representation, auto-closes the
    polygon, and creates a .bak backup.
    """
    from ...geom.GeomStorage import GeomStorage
    try:
        GeomStorage.set_2d_flow_area_perimeter(
            geom_file=geometry_file,
            flow_area_name=area_name,
            coordinates=[(float(x), float(y)) for x, y in coords],
            point_generation_data=[float(cell_size), float(cell_size)],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"Failed to write perimeter for '{area_name}' in {Path(geometry_file).name}: {e}"
        )
        return False
    logger.info(
        f"Updated {Path(geometry_file).name}: {len(coords)} perimeter points, "
        f"cell size {cell_size:.1f} (via GeomStorage)"
    )
    return True


# ---------------------------------------------------------------------------
# Mesh validation (post-regeneration HDF check)
# ---------------------------------------------------------------------------

def _check_mesh_valid(geom_hdf_path: Path, mesh_name: Optional[str] = None) -> dict:
    """
    Check if the geometry HDF contains a valid 2D mesh.

    Returns dict with:
        valid (bool): True if mesh looks complete
        n_cells (int): Number of mesh cells (0 if missing)
        n_faces (int): Number of mesh faces (0 if missing)
        error (str): Description of issue if invalid
    """
    import h5py

    result = {
        "valid": False,
        "n_cells": 0,
        "n_cell_rows": 0,
        "n_virtual_cells": 0,
        "n_faces": 0,
        "error": "",
    }

    if not geom_hdf_path.exists():
        result["error"] = f"HDF file does not exist: {geom_hdf_path}"
        return result

    try:
        with h5py.File(str(geom_hdf_path), "r") as f:
            base = "Geometry/2D Flow Areas"
            if base not in f:
                result["error"] = "No 2D Flow Areas group in HDF"
                return result

            # Auto-detect mesh name if not provided
            if mesh_name is None:
                if "Attributes" in f[base]:
                    names = [n.decode() if isinstance(n, bytes) else str(n)
                             for n in f[base]["Attributes"][()]["Name"]]
                    if names:
                        mesh_name = names[0]

            if mesh_name is None:
                result["error"] = "No mesh areas found in HDF"
                return result

            mesh_base = f"{base}/{mesh_name}"
            if mesh_base not in f:
                result["error"] = f"Mesh '{mesh_name}' not found in HDF"
                return result

            # Check required datasets
            required = [
                "Cells Center Coordinate",
                "FacePoints Coordinate",
                "Faces FacePoint Indexes",
            ]
            for ds_name in required:
                ds_path = f"{mesh_base}/{ds_name}"
                if ds_path not in f:
                    result["error"] = f"Missing dataset: {ds_name}"
                    return result
                if f[ds_path].shape[0] == 0:
                    result["error"] = f"Empty dataset: {ds_name}"
                    return result

            n_cell_rows = f[f"{mesh_base}/Cells Center Coordinate"].shape[0]
            n_faces = f[f"{mesh_base}/Faces FacePoint Indexes"].shape[0]
            n_cells = n_cell_rows
            attributes = f[base].get("Attributes")
            if attributes is not None:
                data = attributes[()]
                fields = data.dtype.names or ()
                if "Name" in fields and "Cell Count" in fields:
                    for row in data:
                        raw_name = row["Name"]
                        name = (
                            raw_name.decode("utf-8", errors="replace")
                            if isinstance(raw_name, bytes)
                            else str(raw_name)
                        ).rstrip("\x00").strip()
                        if name == mesh_name:
                            n_cells = int(row["Cell Count"])
                            break

            result["n_cells"] = n_cells
            result["n_cell_rows"] = n_cell_rows
            result["n_virtual_cells"] = max(0, n_cell_rows - n_cells)
            result["n_faces"] = n_faces

            if n_cells < 3:
                result["error"] = f"Too few cells: {n_cells}"
                return result
            if n_cells > n_cell_rows:
                result["error"] = (
                    f"Active cell count {n_cells} exceeds coordinate rows {n_cell_rows}"
                )
                return result

            # Check face-cell connectivity (face perimeter connection test)
            if f"{mesh_base}/Faces Cell Indexes" in f:
                face_cells = f[f"{mesh_base}/Faces Cell Indexes"][()]
                # Every face should connect to at least one valid cell (index >= 0)
                max_valid = face_cells.max(axis=1)
                if (max_valid < 0).any():
                    n_bad = int((max_valid < 0).sum())
                    result["error"] = f"{n_bad} faces with no valid cell connection"
                    return result

            result["valid"] = True
            return result

    except Exception as e:
        result["error"] = f"HDF read error: {e}"
        return result


def _current_plan_geometry_number(ras_obj) -> str:
    """Resolve the geometry referenced by the sole ``Current Plan`` record."""
    from ...RasUtils import RasUtils

    matches = re.findall(
        r"^Current Plan=p(\d{2})\s*$",
        ras_obj.prj_file.read_text(encoding="utf-8", errors="replace"),
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError(
            f"Expected one Current Plan in {ras_obj.prj_file.name}; found {len(matches)}"
        )
    plan_number = RasUtils.normalize_ras_number(matches[0])
    plan_df = getattr(ras_obj, "plan_df", None)
    if plan_df is None or "plan_number" not in plan_df:
        raise ValueError("Initialized project has no plan_df plan_number column")
    rows = plan_df[plan_df["plan_number"].astype(str).str.zfill(2) == plan_number]
    if len(rows) != 1:
        raise ValueError(
            f"Current plan p{plan_number} resolved to {len(rows)} plan_df rows"
        )
    row = rows.iloc[0]
    value = row.get("geometry_number")
    if value is None or str(value).strip().casefold() in {"", "nan", "none", "<na>"}:
        value = row.get("Geom File")
    if value is None:
        raise ValueError(f"Current plan p{plan_number} has no geometry reference")
    return RasUtils.normalize_ras_number(str(value).lstrip("gG"))


def _resolve_geometry_target(
    ras_obj,
    *,
    geom_number: Optional[Union[str, int]] = None,
    geometry_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve one registered geometry by number and RASMapper tree identity."""
    from ...RasMap import RasMap
    from ...RasUtils import RasUtils

    ras_obj.check_initialized()
    mapper_geometries = list(RasMap.list_geometries(ras_obj))
    if geom_number is None and geometry_name is not None:
        named = [
            geometry
            for geometry in mapper_geometries
            if str(geometry.get("name", "")).strip().casefold()
            == geometry_name.strip().casefold()
        ]
        if len(named) != 1:
            raise ValueError(
                f"Geometry name {geometry_name!r} resolved to {len(named)} "
                "RASMapper geometry layers; supply geom_number"
            )
        geom_number = named[0].get("geom_number")
    if geom_number is None:
        geom_number = _current_plan_geometry_number(ras_obj)
    geom_num = RasUtils.normalize_ras_number(geom_number)

    geom_df = getattr(ras_obj, "geom_df", None)
    if geom_df is None or "geom_number" not in geom_df:
        raise ValueError("Initialized project has no geom_df geom_number column")
    rows = geom_df[geom_df["geom_number"].astype(str).str.zfill(2) == geom_num]
    if len(rows) != 1:
        raise ValueError(f"Geometry g{geom_num} resolved to {len(rows)} geom_df rows")
    geom_file = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.g{geom_num}"
    if not geom_file.is_file():
        raise FileNotFoundError(f"Geometry text file not found: {geom_file}")

    mapper_matches = [
        geometry
        for geometry in mapper_geometries
        if str(geometry.get("geom_number", "")).zfill(2) == geom_num
    ]
    if len(mapper_matches) != 1:
        raise ValueError(
            f"Geometry g{geom_num} resolved to {len(mapper_matches)} RASMapper layers"
        )
    tree_name = str(mapper_matches[0].get("name", "")).strip()
    if not tree_name:
        raise ValueError(f"RASMapper geometry g{geom_num} has no display name")
    duplicate_tree_names = [
        geometry
        for geometry in mapper_geometries
        if str(geometry.get("name", "")).strip().casefold() == tree_name.casefold()
    ]
    if len(duplicate_tree_names) != 1:
        raise ValueError(
            f"RASMapper tree name {tree_name!r} is not unique; cannot target g{geom_num} safely"
        )
    if geometry_name is not None and tree_name.casefold() != geometry_name.strip().casefold():
        raise ValueError(
            f"Geometry g{geom_num} is named {tree_name!r}, not {geometry_name!r}"
        )

    return {
        "geom_number": geom_num,
        "geometry_name": tree_name,
        "geom_file": geom_file,
        "geom_hdf": Path(f"{geom_file}.hdf"),
    }


def _select_text_flow_area(geom_file: Path, flow_area_name: Optional[str]):
    """Return one exact 2D flow-area polygon from geometry text."""
    from ...geom.GeomStorage import GeomStorage

    areas = GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
    if areas is None or areas.empty:
        raise ValueError(f"No storage-area polygons found in {geom_file.name}")
    if "is_2d" in areas:
        areas = areas[areas["is_2d"]]
    if flow_area_name is None:
        if len(areas) != 1:
            raise ValueError(
                f"Geometry {geom_file.name} has {len(areas)} 2D flow areas; "
                "supply flow_area_name"
            )
        row = areas.iloc[0]
    else:
        name_column = "name" if "name" in areas else "Name"
        matches = areas[areas[name_column].astype(str) == flow_area_name]
        if len(matches) != 1:
            raise ValueError(
                f"2D flow area {flow_area_name!r} resolved to {len(matches)} text polygons"
            )
        row = matches.iloc[0]
    name_column = "name" if "name" in areas else "Name"
    polygon = row.geometry
    if polygon is None or polygon.is_empty or not polygon.is_valid:
        raise ValueError(f"2D flow area {row[name_column]!r} has an invalid text perimeter")
    return str(row[name_column]), polygon


def _geometry_hdf_stats(ras_obj) -> Dict[str, tuple[int, int]]:
    """Return size/mtime evidence for every registered geometry HDF."""
    stats: Dict[str, tuple[int, int]] = {}
    geom_df = getattr(ras_obj, "geom_df", None)
    if geom_df is None or "geom_number" not in geom_df:
        return stats
    for value in geom_df["geom_number"]:
        number = str(value).zfill(2)
        path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.g{number}.hdf"
        if path.is_file():
            stat = path.stat()
            stats[str(path.resolve())] = (stat.st_size, stat.st_mtime_ns)
    return stats


def _read_hdf_flow_area_polygon(geom_hdf: Path, flow_area_name: str):
    """Read a registered 2D-area polygon before or after mesh compilation.

    A newly rebuilt RAS Mapper geometry HDF contains the collection-level
    ``Polygon *`` datasets before it contains the per-area ``Perimeter`` and
    mesh datasets.  Reading the collection therefore validates the important
    text-to-HDF import boundary without requiring a mesh to exist yet.
    """
    import h5py
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    group_path = "Geometry/2D Flow Areas"
    with h5py.File(geom_hdf, "r") as hdf:
        if group_path not in hdf:
            raise ValueError("Geometry HDF has no 2D flow-area collection")
        group = hdf[group_path]
        required = {"Attributes", "Polygon Info", "Polygon Parts", "Polygon Points"}
        missing = sorted(required.difference(group.keys()))
        if missing:
            raise ValueError(
                "Geometry HDF 2D flow-area collection is missing: "
                + ", ".join(missing)
            )

        attributes = group["Attributes"][()]
        if attributes.dtype.names is None or "Name" not in attributes.dtype.names:
            raise ValueError("Geometry HDF 2D flow-area Attributes has no Name field")

        def decode(value) -> str:
            if isinstance(value, (bytes, np.bytes_)):
                return bytes(value).decode("utf-8", errors="replace").rstrip("\x00").strip()
            return str(value).rstrip("\x00").strip()

        names = [decode(value) for value in attributes["Name"]]
        matches = [index for index, name in enumerate(names) if name == flow_area_name]
        if len(matches) != 1:
            raise ValueError(
                f"2D flow area {flow_area_name!r} resolved to {len(matches)} "
                "collection polygons"
            )
        row_index = matches[0]

        polygon_info = np.asarray(group["Polygon Info"][()])
        polygon_parts = np.asarray(group["Polygon Parts"][()])
        polygon_points = np.asarray(group["Polygon Points"][()], dtype=float)
        if polygon_info.ndim != 2 or polygon_info.shape[1] < 4:
            raise ValueError("Geometry HDF Polygon Info must be an Nx4 dataset")
        if row_index >= polygon_info.shape[0]:
            raise ValueError("Geometry HDF polygon row count does not match Attributes")

        point_start, point_count, part_start, part_count = (
            int(value) for value in polygon_info[row_index, :4]
        )
        if point_count < 3 or part_count < 1:
            raise ValueError(f"2D flow area {flow_area_name!r} has no polygon ring")
        area_points = polygon_points[point_start : point_start + point_count]
        if area_points.shape != (point_count, 2):
            raise ValueError(f"2D flow area {flow_area_name!r} has truncated points")

        rings = []
        for raw_start, raw_count in polygon_parts[part_start : part_start + part_count, :2]:
            ring_start, ring_count = int(raw_start), int(raw_count)
            # HEC-RAS files in the field use absolute point indexes. Accept a
            # relative index only when the absolute range is outside this row.
            if not (point_start <= ring_start < point_start + point_count):
                ring_start += point_start
            ring = polygon_points[ring_start : ring_start + ring_count]
            if ring.shape[0] >= 3:
                rings.append(ring)
        if not rings:
            rings = [area_points]

        shell = Polygon(rings[0])
        if len(rings) == 1:
            polygon = shell
        else:
            holes = [ring for ring in rings[1:] if shell.covers(Polygon(ring))]
            islands = [Polygon(ring) for ring in rings[1:] if not shell.covers(Polygon(ring))]
            polygon = Polygon(rings[0], holes)
            if islands:
                polygon = unary_union([polygon, *islands])
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"2D flow area {flow_area_name!r} has an invalid polygon")
        return polygon


def _perimeter_validation(
    geom_hdf: Path,
    flow_area_name: str,
    expected_polygon,
    *,
    coordinate_tolerance: Optional[float] = None,
) -> dict:
    """Compare an exact text perimeter with its compiled HDF polygon."""
    result = {
        "valid": False,
        "flow_area_name": flow_area_name,
        "coordinate_tolerance": coordinate_tolerance,
        "hausdorff_distance": None,
        "symmetric_difference_area": None,
        "text_area": float(expected_polygon.area),
        "hdf_area": None,
        "error": "",
    }
    if not geom_hdf.is_file():
        result["error"] = f"Geometry HDF does not exist: {geom_hdf.name}"
        return result
    try:
        actual_polygon = _read_hdf_flow_area_polygon(geom_hdf, flow_area_name)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result["error"] = str(exc)
        return result

    min_x, min_y, max_x, max_y = expected_polygon.bounds
    scale = max(max_x - min_x, max_y - min_y, 1.0)
    tolerance = (
        float(coordinate_tolerance)
        if coordinate_tolerance is not None
        else max(1e-6, scale * 1e-9)
    )
    if tolerance < 0:
        raise ValueError("coordinate_tolerance must be non-negative")
    hausdorff = float(expected_polygon.boundary.hausdorff_distance(actual_polygon.boundary))
    symmetric_area = float(expected_polygon.symmetric_difference(actual_polygon).area)
    area_tolerance = max(
        tolerance * tolerance,
        float(expected_polygon.length) * tolerance,
        float(expected_polygon.area) * 1e-10,
    )
    result.update(
        {
            "coordinate_tolerance": tolerance,
            "hausdorff_distance": hausdorff,
            "symmetric_difference_area": symmetric_area,
            "area_tolerance": area_tolerance,
            "hdf_area": float(actual_polygon.area),
        }
    )
    if hausdorff > tolerance or symmetric_area > area_tolerance:
        result["error"] = (
            "Compiled HDF perimeter does not match geometry text: "
            f"Hausdorff={hausdorff:g} (limit {tolerance:g}), "
            f"symmetric area={symmetric_area:g} (limit {area_tolerance:g})"
        )
        return result
    result["valid"] = True
    return result


def _prepare_geometry_refresh_context(
    ras_obj,
    *,
    geom_number: Optional[Union[str, int]],
    geometry_name: Optional[str],
    flow_area_name: Optional[str],
    coordinate_tolerance: Optional[float],
) -> Dict[str, Any]:
    """Resolve all identities and semantic expectations before GUI work."""
    target = _resolve_geometry_target(
        ras_obj,
        geom_number=geom_number,
        geometry_name=geometry_name,
    )
    area_name, expected_polygon = _select_text_flow_area(
        target["geom_file"], flow_area_name
    )
    # ``Edit Geometry`` is a context-menu action on the registered geometry
    # root, not on its ``2D Flow Areas`` child. The flow area remains an
    # independent semantic selector for post-save validation.
    target_path = [target["geometry_name"]]
    pre_stats = _geometry_hdf_stats(ras_obj)
    pre_association_paths = _capture_geometry_association_paths(target["geom_hdf"])
    pre_perimeter = _perimeter_validation(
        target["geom_hdf"],
        area_name,
        expected_polygon,
        coordinate_tolerance=coordinate_tolerance,
    )
    return {
        **target,
        "flow_area_name": area_name,
        "expected_polygon": expected_polygon,
        "target_path": target_path,
        "coordinate_tolerance": coordinate_tolerance,
        "pre_hdf_stats": pre_stats,
        "pre_perimeter_validation": pre_perimeter,
        "pre_geometry_association_paths": pre_association_paths,
    }


def _capture_geometry_association_paths(geom_hdf: Path) -> dict[str, Path]:
    """Capture all existing, resolvable layer associations before HDF import."""
    target = Path(geom_hdf)
    if not target.is_file():
        return {}
    from ...geom.GeomMesh import GeomMesh

    association = GeomMesh.get_geometry_association(target)
    paths: dict[str, Path] = {}
    for key in (
        "terrain_hdf_path",
        "landcover_hdf_path",
        "infiltration_hdf_path",
        "sediment_soils_hdf_path",
    ):
        value = association.get(key)
        if not value:
            continue
        resolved = Path(value)
        if not resolved.is_file():
            raise FileNotFoundError(
                f"Cannot preserve {key}; associated artifact is missing: {resolved}"
            )
        paths[key] = resolved
    return paths


def _restore_geometry_association(context: dict) -> dict:
    """Restore captured layer associations on the rebuilt exact geometry HDF."""
    expected = dict(context.get("pre_geometry_association_paths") or {})
    evidence = {
        "restored": False,
        "expected_paths": {key: str(value) for key, value in expected.items()},
        "observed": {},
    }
    if not expected:
        return evidence

    from ...geom.GeomMesh import GeomMesh

    target = Path(context["geom_hdf"])
    GeomMesh.set_geometry_association(
        target,
        ras_object=context.get("ras_object"),
        validate=True,
        **expected,
    )
    observed = GeomMesh.get_geometry_association(target)
    evidence["restored"] = True
    evidence["observed"] = {
        key: observed.get(key)
        for key in expected
    }
    return evidence


def _validate_geometry_import(context: dict) -> dict:
    """Validate the exact text-to-HDF import without requiring a mesh yet."""
    target_hdf = Path(context["geom_hdf"])
    perimeter = _perimeter_validation(
        target_hdf,
        context["flow_area_name"],
        context["expected_polygon"],
        coordinate_tolerance=context.get("coordinate_tolerance"),
    )
    if not perimeter["valid"]:
        raise RuntimeError(perimeter["error"])

    ras_obj = context["ras_object"]
    before_stats = context["pre_hdf_stats"]
    after_stats = _geometry_hdf_stats(ras_obj)
    target_key = str(target_hdf.resolve())
    other_changes = []
    for path in sorted(set(before_stats) | set(after_stats)):
        if path == target_key:
            continue
        if before_stats.get(path) != after_stats.get(path):
            other_changes.append(path)
    if other_changes:
        raise RuntimeError(
            "RASMapper changed non-target geometry HDFs: "
            + ", ".join(Path(path).name for path in other_changes)
        )

    target_before = before_stats.get(target_key)
    target_after = after_stats.get(target_key)
    pre_perimeter = context["pre_perimeter_validation"]
    if not pre_perimeter["valid"] and target_before == target_after:
        raise RuntimeError(
            f"Target geometry {target_hdf.name} matched after save but its file evidence "
            "did not change from the known-stale precondition"
        )

    return {
        "geom_number": context["geom_number"],
        "geometry_name": context["geometry_name"],
        "geom_file": str(context["geom_file"]),
        "geom_hdf": str(target_hdf),
        "flow_area_name": context["flow_area_name"],
        "pre_perimeter": pre_perimeter,
        "post_perimeter": perimeter,
        "other_geometry_hdfs_unchanged": True,
    }


def _validate_geometry_refresh(context: dict) -> dict:
    """Fail closed unless the exact geometry import and mesh are current."""
    result = _validate_geometry_import(context)
    target_hdf = Path(context["geom_hdf"])
    mesh = _check_mesh_valid(target_hdf, mesh_name=context["flow_area_name"])
    if not mesh["valid"]:
        raise RuntimeError(f"Compiled target mesh is invalid: {mesh['error']}")
    result["mesh"] = mesh
    return result


def _begin_geometry_hdf_transaction(context: dict) -> None:
    """Temporarily remove the exact HDF so HEC-RAS imports geometry text."""
    target = Path(context["geom_hdf"])
    temporary_backup = target.with_name(
        f".{target.name}.rascommander-{uuid4().hex}.bak"
    )
    had_original = target.is_file()
    if had_original:
        os.replace(target, temporary_backup)
    context["hdf_transaction"] = {
        "target": target,
        "temporary_backup": temporary_backup,
        "had_original": had_original,
    }


def _finish_geometry_hdf_transaction(
    context: dict,
    *,
    success: bool,
    keep_backup: bool,
) -> dict:
    """Commit a validated HDF or restore the exact target on failure."""
    transaction = context["hdf_transaction"]
    target = Path(transaction["target"])
    temporary_backup = Path(transaction["temporary_backup"])
    had_original = bool(transaction["had_original"])
    evidence = {
        "target": str(target),
        "had_original": had_original,
        "rolled_back": False,
        "backup": None,
    }

    if not success:
        if target.exists():
            target.unlink()
        if had_original and temporary_backup.exists():
            os.replace(temporary_backup, target)
        evidence["rolled_back"] = True
        return evidence

    if not target.is_file():
        if had_original and temporary_backup.exists():
            os.replace(temporary_backup, target)
        evidence["rolled_back"] = True
        raise RuntimeError(f"HEC-RAS did not rebuild geometry HDF: {target}")

    if had_original and temporary_backup.exists():
        if keep_backup:
            committed_backup = target.with_name(f"{target.name}.pre-rasmapper.bak")
            counter = 1
            while committed_backup.exists():
                committed_backup = target.with_name(
                    f"{target.name}.pre-rasmapper.bak{counter}"
                )
                counter += 1
            os.replace(temporary_backup, committed_backup)
            evidence["backup"] = str(committed_backup)
        else:
            temporary_backup.unlink()
    return evidence


def _capture_owned_process_tree(process) -> list:
    """Capture only the process tree rooted at the workflow's Ras.exe."""
    if process is None:
        return []
    try:
        import psutil

        root = psutil.Process(int(process.pid))
        return [root, *root.children(recursive=True)]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not capture owned HEC-RAS process tree: %s", exc)
        return []


def _supervise_owned_process_exit(process, owned_processes: list) -> dict:
    """Gracefully wait, then terminate/kill only captured owned processes."""
    evidence = {
        "root_pid": int(process.pid) if process is not None else None,
        "observed_pids": sorted({int(proc.pid) for proc in owned_processes}),
        "terminated_pids": [],
        "killed_pids": [],
        "survivor_pids": [],
    }
    if process is None:
        return evidence

    try:
        process.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass

    try:
        import psutil
    except ImportError:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:  # noqa: BLE001
                process.kill()
                process.wait(timeout=3)
        return evidence

    if not owned_processes:
        try:
            owned_processes = [psutil.Process(int(process.pid))]
            evidence["observed_pids"] = [int(process.pid)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            owned_processes = []

    alive = []
    for owned in owned_processes:
        try:
            if owned.is_running() and owned.status() != psutil.STATUS_ZOMBIE:
                alive.append(owned)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for owned in reversed(alive):
        try:
            evidence["terminated_pids"].append(int(owned.pid))
            owned.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone, alive = psutil.wait_procs(alive, timeout=3)
    for owned in alive:
        try:
            evidence["killed_pids"].append(int(owned.pid))
            owned.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone, survivors = psutil.wait_procs(alive, timeout=3)
    evidence["survivor_pids"] = sorted(int(owned.pid) for owned in survivors)
    return evidence


# ---------------------------------------------------------------------------
# Perimeter simplification
# ---------------------------------------------------------------------------

def _simplify_perimeter(
    coords: List[Tuple[float, float]],
    tolerance: float,
) -> List[Tuple[float, float]]:
    """
    Simplify perimeter polygon using Douglas-Peucker algorithm.

    Also removes acute angles (< 20 degrees) that cause face perimeter errors.

    Args:
        coords: List of (x, y) tuples (may or may not be closed).
        tolerance: Simplification tolerance in coordinate units.

    Returns:
        Simplified coordinate list.
    """
    try:
        from shapely.geometry import Polygon

        # Ensure closed
        pts = list(coords)
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)  # Fix self-intersections

        simplified = poly.simplify(tolerance, preserve_topology=True)

        # Extract exterior coords (remove closing point — _write adds it back)
        result = list(simplified.exterior.coords[:-1])

        logger.info(
            f"Simplified perimeter: {len(pts)} → {len(result)} points "
            f"(tolerance={tolerance:.1f})"
        )
        return result

    except ImportError:
        logger.warning("Shapely not available — skipping perimeter simplification")
        return coords


# ---------------------------------------------------------------------------
# Main workflow class
# ---------------------------------------------------------------------------

class MeshRegenerationWorkflow:
    """
    Regenerate 2D mesh in RASMapper with iterative error correction.

    Single attempt:
        regenerate_mesh() — open RASMapper, save, check HDF, close

    Iterative (recommended for automated pipelines):
        regenerate_mesh_iterative() — retry with perimeter simplification
        and cell size adjustment until mesh is valid or max attempts reached.

    All methods are static and decorated with @log_call.
    """

    # ------------------------------------------------------------------
    # Exact text-to-HDF import
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def refresh_geometry_hdf_from_text(
        geometry_name: Optional[str] = None,
        flow_area_name: Optional[str] = None,
        ras_object=None,
        timeout: int = 600,
        *,
        geom_number: Optional[Union[str, int]] = None,
        coordinate_tolerance: Optional[float] = None,
        keep_backup: bool = True,
    ) -> WorkflowResult:
        """Rebuild one exact geometry HDF from its current ``.g##`` text.

        HEC-RAS/RAS Mapper treats an existing geometry HDF as authoritative
        during editing, so merely opening and saving does not import external
        text changes. This operation transactionally displaces only the exact
        selected HDF, opens the task-local project through its configured
        HEC-RAS version, saves the exact registered geometry, and validates the
        collection-level 2D perimeter before committing the replacement.

        The geometry defaults to the sole current plan's geometry. Supplying
        both ``geom_number`` and ``geometry_name`` makes them an identity
        cross-check. Other registered geometry HDF files must remain unchanged.
        A failed import restores the original target HDF. Existing terrain,
        land-cover, infiltration, and sediment associations are captured before
        import and restored on the rebuilt HDF; a missing associated artifact or
        failed association validation aborts and rolls back the transaction.

        This method compiles geometry features but does not create computation
        cells. Call :meth:`GeomMesh.generate` after applying HDF-only feature
        edits such as refinement-region replacement.
        """
        from ...RasPrj import ras

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        context = _prepare_geometry_refresh_context(
            ras_obj,
            geom_number=geom_number,
            geometry_name=geometry_name,
            flow_area_name=flow_area_name,
            coordinate_tolerance=coordinate_tolerance,
        )
        context.update(
            {
                "ras_object": ras_obj,
                "timeout": timeout,
                "close_after": True,
                "force_text_import": True,
            }
        )
        _begin_geometry_hdf_transaction(context)

        result = WorkflowExecutor.execute(
            MeshRegenerationWorkflow._build_single_attempt_steps(
                context,
                require_mesh=False,
            ),
            context,
            workflow_name=f"GeometryTextImport[g{context['geom_number']}]",
        )
        cleanup_error = None
        if not context.get("closed"):
            try:
                MeshRegenerationWorkflow._step_close(context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Geometry text import cleanup failed: %s", exc)
                cleanup_error = exc
        if cleanup_error is not None:
            result.success = False
            result.error = cleanup_error
            result.steps_failed.append("Close owned HEC-RAS process tree")

        if result.success:
            try:
                association = _restore_geometry_association(context)
            except Exception as exc:  # noqa: BLE001
                result.success = False
                result.error = exc
                result.steps_failed.append("Restore geometry associations")
                association = {
                    "restored": False,
                    "error": str(exc),
                }
            result.step_results["Restore geometry associations"] = association

        try:
            transaction = _finish_geometry_hdf_transaction(
                context,
                success=result.success,
                keep_backup=keep_backup,
            )
        except Exception as exc:  # noqa: BLE001
            result.success = False
            result.error = exc
            result.steps_failed.append("Commit geometry HDF transaction")
            transaction = {
                "target": str(context["geom_hdf"]),
                "rolled_back": True,
                "backup": None,
            }
        result.step_results["Geometry HDF transaction"] = transaction
        return result

    # ------------------------------------------------------------------
    # Single-attempt mesh regeneration
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def regenerate_mesh(
        geometry_name: Optional[str] = None,
        flow_area_name: Optional[str] = None,
        ras_object=None,
        timeout: int = 600,
        close_after: bool = True,
        *,
        geom_number: Optional[Union[str, int]] = None,
        coordinate_tolerance: Optional[float] = None,
    ) -> WorkflowResult:
        """
        Single mesh regeneration attempt.

        Opens RASMapper (which re-reads the modified .g## file),
        saves (triggering HDF regeneration), and checks the result.

        Args:
            geometry_name: Exact RASMapper geometry-layer name. When supplied
                with ``geom_number``, both identities must agree.
            flow_area_name: Name of the 2D flow area. Auto-detected if None.
            ras_object: Optional RasPrj object instance.
            timeout: Max seconds to wait for mesh generation. Default 600.
            close_after: If True, close RASMapper and HEC-RAS when done.
            geom_number: Exact geometry number, such as ``"03"``. When both
                geometry selectors are omitted, resolve the geometry referenced
                by the sole current plan; never fall back to the first ``Geom
                File=`` registration.
            coordinate_tolerance: Optional project-unit limit for comparing the
                text perimeter with the compiled HDF perimeter.

        Returns:
            WorkflowResult. ``step_results['Validate exact geometry HDF']``
            contains target identity, perimeter, mesh, and non-target-file
            validation evidence.
        """
        from ...RasPrj import ras

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        context = _prepare_geometry_refresh_context(
            ras_obj,
            geom_number=geom_number,
            geometry_name=geometry_name,
            flow_area_name=flow_area_name,
            coordinate_tolerance=coordinate_tolerance,
        )
        context.update(
            {
                "ras_object": ras_obj,
                "timeout": timeout,
                "close_after": close_after,
            }
        )

        steps = MeshRegenerationWorkflow._build_single_attempt_steps(context)
        result = WorkflowExecutor.execute(
            steps,
            context,
            workflow_name=f"MeshRegeneration[g{context['geom_number']}]",
        )
        if close_after and not context.get("closed"):
            try:
                MeshRegenerationWorkflow._step_close(context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Mesh regeneration cleanup failed: %s", exc)
                result.success = False
                result.error = exc
                result.steps_failed.append("Close owned HEC-RAS process tree")
        return result

    # ------------------------------------------------------------------
    # Iterative mesh regeneration with error correction
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def regenerate_mesh_iterative(
        ras_object=None,
        timeout: int = 600,
        max_iterations: int = 5,
        initial_cell_size: Optional[float] = None,
        cell_size_increase_factor: float = 1.3,
        simplify_tolerance_factor: float = 0.25,
        *,
        geom_number: Optional[Union[str, int]] = None,
        geometry_name: Optional[str] = None,
        flow_area_name: Optional[str] = None,
        coordinate_tolerance: Optional[float] = None,
    ) -> WorkflowResult:
        """
        Iterative mesh regeneration with face perimeter error correction.

        On each iteration:
        1. Open RASMapper → save → check HDF for valid mesh
        2. If valid: done
        3. If invalid: close HEC-RAS, simplify perimeter, increase cell size, retry

        Simplification strategy:
        - tolerance = cell_size * simplify_tolerance_factor
        - Each iteration increases cell size by cell_size_increase_factor
        - Perimeter is simplified more aggressively each round

        Args:
            ras_object: Optional RasPrj object instance.
            timeout: Max seconds per attempt for RASMapper operations.
            max_iterations: Maximum attempts before giving up. Default 5.
            initial_cell_size: Starting cell size. Read from .g## if None.
            cell_size_increase_factor: Multiply cell size by this on each retry. Default 1.3.
            simplify_tolerance_factor: simplify_tolerance = cell_size * this. Default 0.25.
            geom_number: Exact geometry number. Defaults to the current plan's
                geometry, never the first project geometry registration.
            geometry_name: Optional exact RASMapper name cross-check.
            flow_area_name: Exact 2D flow-area name when geometry has more than one.
            coordinate_tolerance: Optional text/HDF perimeter comparison limit.

        Returns:
            WorkflowResult with:
                success: True if a valid mesh was generated
                step_results['mesh_check']: Final mesh validation dict
                step_results['iterations']: Number of attempts taken
                step_results['final_cell_size']: Cell size that worked (or last tried)
                step_results['final_n_cells']: Cell count of successful mesh
        """
        from ...RasPrj import ras
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        target = _resolve_geometry_target(
            ras_obj,
            geom_number=geom_number,
            geometry_name=geometry_name,
        )
        geom_file = target["geom_file"]
        geom_hdf = target["geom_hdf"]
        area_name, area_polygon = _select_text_flow_area(geom_file, flow_area_name)

        # Read initial state
        cell_size = initial_cell_size or _read_cell_size(geom_file) or 500.0
        original_coords = [
            (float(x_coord), float(y_coord))
            for x_coord, y_coord in area_polygon.exterior.coords
        ]
        current_coords = list(original_coords) if original_coords else None

        if current_coords is None:
            return WorkflowResult(
                success=False,
                error=RuntimeError(f"No perimeter coordinates in {geom_file.name}"),
            )

        result = WorkflowResult(success=False)
        result.step_results['iterations'] = 0
        result.step_results['final_cell_size'] = cell_size

        for iteration in range(1, max_iterations + 1):
            logger.info(
                f"--- Mesh attempt {iteration}/{max_iterations} "
                f"(cell_size={cell_size:.1f}, perimeter_pts={len(current_coords)}) ---"
            )
            result.step_results['iterations'] = iteration

            # Step 1: Open RASMapper, save, close
            attempt = MeshRegenerationWorkflow.regenerate_mesh(
                geometry_name=target["geometry_name"],
                flow_area_name=area_name,
                ras_object=ras_obj,
                timeout=timeout,
                close_after=True,
                geom_number=target["geom_number"],
                coordinate_tolerance=coordinate_tolerance,
            )

            if not attempt.success:
                logger.warning(f"Attempt {iteration} failed at GUI level")
                logger.debug("Mesh regeneration GUI attempt %s failure: %s", iteration, attempt.error)
                result.steps_failed.append(f"attempt_{iteration}_gui")
                # Continue to try simplification anyway
            else:
                result.steps_completed.append(f"attempt_{iteration}_gui")

            # Step 2: Check HDF for valid mesh
            time.sleep(1)  # Let file system settle
            mesh_check = _check_mesh_valid(geom_hdf)
            result.step_results['mesh_check'] = mesh_check

            if mesh_check['valid']:
                logger.info(
                    f"Mesh is valid! {mesh_check['n_cells']} cells, "
                    f"{mesh_check['n_faces']} faces (attempt {iteration})"
                )
                result.success = True
                result.step_results['final_cell_size'] = cell_size
                result.step_results['final_n_cells'] = mesh_check['n_cells']
                result.steps_completed.append(f"attempt_{iteration}_valid")
                return result

            # Step 3: Mesh invalid — log the issue and prepare fix
            logger.warning(f"Attempt {iteration}: mesh invalid")
            logger.debug("Mesh validation failure on attempt %s: %s", iteration, mesh_check['error'])
            result.steps_failed.append(f"attempt_{iteration}_mesh: {mesh_check['error']}")

            if iteration >= max_iterations:
                logger.error(f"Max iterations ({max_iterations}) reached — mesh still invalid")
                break

            # Step 4: Simplify perimeter and increase cell size
            cell_size *= cell_size_increase_factor
            simplify_tolerance = cell_size * simplify_tolerance_factor

            logger.info(
                f"Adjusting: cell_size → {cell_size:.1f}, "
                f"simplify_tolerance → {simplify_tolerance:.1f}"
            )

            current_coords = _simplify_perimeter(current_coords, simplify_tolerance)

            # Step 5: Write modified geometry
            success = _write_perimeter_and_cell_size(
                geom_file, area_name, current_coords, cell_size
            )
            if not success:
                logger.error("Failed to write modified geometry")
                break

            result.step_results['final_cell_size'] = cell_size

        result.error = RuntimeError(
            f"Mesh generation failed after {result.step_results['iterations']} iterations. "
            f"Last error: {result.step_results.get('mesh_check', {}).get('error', 'unknown')}"
        )
        return result

    # ------------------------------------------------------------------
    # Step implementations for single attempt
    # ------------------------------------------------------------------

    @staticmethod
    def _build_single_attempt_steps(
        context: dict,
        *,
        require_mesh: bool = True,
    ) -> list:
        """Build step sequence for a single regeneration attempt."""
        steps = [
            WorkflowStep(
                name="Verify HEC-RAS is closed",
                action=MeshRegenerationWorkflow._step_verify_hecras_closed,
                max_retries=1,
            ),
            WorkflowStep(
                name="Launch HEC-RAS",
                action=MeshRegenerationWorkflow._step_launch_hecras,
                max_retries=2,
                retry_delay=3.0,
            ),
            WorkflowStep(
                name="Open RASMapper",
                action=MeshRegenerationWorkflow._step_open_rasmapper,
                max_retries=2,
                retry_delay=2.0,
            ),
            WorkflowStep(
                name="Wait for RASMapper",
                action=MeshRegenerationWorkflow._step_wait_for_rasmapper,
                max_retries=1,
                timeout=context.get('timeout', 600),
            ),
            WorkflowStep(
                name="Select exact geometry for editing",
                action=MeshRegenerationWorkflow._step_select_geometry,
                max_retries=2,
                retry_delay=2.0,
            ),
            WorkflowStep(
                name="Save geometry (trigger HDF regeneration)",
                action=MeshRegenerationWorkflow._step_save_geometry,
                max_retries=2,
                retry_delay=1.0,
            ),
            WorkflowStep(
                name="Wait for save to complete",
                action=MeshRegenerationWorkflow._step_wait_for_save,
                max_retries=1,
                timeout=context.get('timeout', 600),
            ),
            WorkflowStep(
                name=(
                    "Validate exact geometry HDF"
                    if require_mesh
                    else "Validate exact geometry import"
                ),
                action=(
                    MeshRegenerationWorkflow._step_validate_geometry
                    if require_mesh
                    else MeshRegenerationWorkflow._step_validate_geometry_import
                ),
                max_retries=1,
            ),
        ]

        if context.get('close_after', True):
            steps.append(WorkflowStep(
                name="Close RASMapper and HEC-RAS",
                action=MeshRegenerationWorkflow._step_close,
                max_retries=2,
                retry_delay=1.0,
                required=True,
            ))

        return steps

    @staticmethod
    def _step_verify_hecras_closed(context: dict) -> None:
        """Refuse to attach the one-shot operation to an unrelated GUI session."""
        from .xsec_update import RasMapperLayerCommandWorkflow

        RasMapperLayerCommandWorkflow._step_verify_hecras_closed(context)

    @staticmethod
    def _step_launch_hecras(context: dict) -> None:
        """Launch HEC-RAS and store process/hwnd in context."""
        process, hwnd = HecRasElements.launch_and_wait(
            ras_object=context.get('ras_object'),
            timeout=30,
        )
        if not hwnd:
            raise RuntimeError("Failed to launch HEC-RAS")
        context['hecras_process'] = process
        context['hecras_hwnd'] = hwnd

    @staticmethod
    def _step_open_rasmapper(context: dict) -> None:
        """Open RASMapper via GIS Tools menu."""
        hwnd = context['hecras_hwnd']

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        if not HecRasElements.click_menu_by_path(hwnd, ["&GIS Tools", "RAS &Mapper"]):
            logger.debug("Trying keyboard shortcut Alt+G, M...")
            Win32Primitives.send_keyboard_shortcut(hwnd, Win32Constants.VK_MENU, ord('G'))
            time.sleep(0.3)
            win32api.keybd_event(ord('M'), 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(ord('M'), 0, Win32Constants.KEYEVENTF_KEYUP, 0)

    @staticmethod
    def _step_wait_for_rasmapper(context: dict) -> None:
        """Wait for RASMapper to become responsive."""
        timeout = context.get('timeout', 600)
        result = RasMapperElements.wait_for_rasmapper(timeout=timeout)
        if not result:
            raise RuntimeError("RASMapper did not become responsive")
        context['rasmapper_hwnd'] = result[0]
        context['rasmapper_title'] = result[1]

    @staticmethod
    def _step_select_geometry(context: dict) -> None:
        """Enter edit mode through the exact geometry's 2D Flow Areas node."""
        from .xsec_update import RasMapperLayerCommandWorkflow

        RasMapperLayerCommandWorkflow._step_start_geometry_editing(context)

    @staticmethod
    def _step_save_geometry(context: dict) -> None:
        """Save geometry in RASMapper via Ctrl+S, triggering HDF regeneration."""
        rasmapper_hwnd = context['rasmapper_hwnd']

        try:
            win32gui.SetForegroundWindow(rasmapper_hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        # Ctrl+S
        win32api.keybd_event(0x11, 0, 0, 0)  # Ctrl down
        time.sleep(0.05)
        win32api.keybd_event(ord('S'), 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(ord('S'), 0, Win32Constants.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x11, 0, Win32Constants.KEYEVENTF_KEYUP, 0)

        logger.debug("Sent Ctrl+S to RASMapper")

    @staticmethod
    def _step_wait_for_save(context: dict) -> None:
        """Wait for RASMapper to finish saving / HDF regeneration."""
        rasmapper_hwnd = context['rasmapper_hwnd']
        timeout = context.get('timeout', 600)

        time.sleep(2)

        if not RasMapperElements.wait_for_rasmapper_idle(rasmapper_hwnd, timeout=timeout):
            logger.warning("RASMapper may still be processing, but continuing...")

    @staticmethod
    def _step_validate_geometry(context: dict) -> dict:
        """Validate target identity, perimeter, mesh, and non-target isolation."""
        return _validate_geometry_refresh(context)

    @staticmethod
    def _step_validate_geometry_import(context: dict) -> dict:
        """Validate exact text import before computation-cell generation."""
        return _validate_geometry_import(context)

    @staticmethod
    def _step_close(context: dict) -> None:
        """Close RASMapper and HEC-RAS."""
        rasmapper_hwnd = context.get('rasmapper_hwnd')
        hecras_hwnd = context.get('hecras_hwnd')
        hecras_process = context.get('hecras_process')
        owned_processes = _capture_owned_process_tree(hecras_process)

        if rasmapper_hwnd:
            Win32Primitives.close_window(rasmapper_hwnd)
            time.sleep(2)

        HecRasElements.dismiss_save_prompt(timeout=3)

        if hecras_hwnd:
            Win32Primitives.close_window(hecras_hwnd)

        cleanup = _supervise_owned_process_exit(hecras_process, owned_processes)
        context["owned_process_cleanup"] = cleanup
        if cleanup["survivor_pids"]:
            raise RuntimeError(
                "Owned HEC-RAS processes survived cleanup: "
                + ", ".join(str(pid) for pid in cleanup["survivor_pids"])
            )

        context["closed"] = True
        logger.debug("RASMapper and HEC-RAS closed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_geometry_file(
    ras_obj,
    geom_number: Optional[Union[str, int]] = None,
    geometry_name: Optional[str] = None,
) -> Optional[Path]:
    """Resolve an exact or current-plan geometry without first-entry fallback."""
    try:
        return _resolve_geometry_target(
            ras_obj,
            geom_number=geom_number,
            geometry_name=geometry_name,
        )["geom_file"]
    except Exception as e:
        logger.warning("Could not resolve exact geometry file")
        logger.debug("Geometry file discovery failure: %s", e)
        return None
