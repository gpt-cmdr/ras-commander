"""Velocity profile extraction through RasMapperLib.Render.VelocityRenderer."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

import h5py
import numpy as np

from ..LoggingConfig import get_logger
from .clr_bootstrap import load_clr

logger = get_logger(__name__)

MISSING_LIMIT = 1.0e30
MISSING_SENTINELS = (-9999.0,)
DEFAULT_SAMPLE_SPACING = 50.0


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return True
    return (
        math.isnan(as_float)
        or math.isinf(as_float)
        or abs(as_float) >= MISSING_LIMIT
        or any(abs(as_float - sentinel) <= 1.0e-6 for sentinel in MISSING_SENTINELS)
    )


def _clean_float_array(values: Any, count: int) -> np.ndarray:
    cleaned = np.full(count, np.nan, dtype=float)
    for idx, value in enumerate(list(values)[:count]):
        if not _is_missing(value):
            cleaned[idx] = float(value)
    return cleaned


def _point_ms_from_xy(polyline_xy: np.ndarray) -> Any:
    from RasMapperLib import PointMs  # type: ignore

    points = PointMs(len(polyline_xy))
    for x, y in polyline_xy:
        points.Add(float(x), float(y))
    return points


def _point_ms_from_intersections(intersections: Any) -> Any:
    from RasMapperLib import PointMs  # type: ignore

    points = PointMs(intersections.Count)
    for pop in intersections:
        point = pop.PointM
        points.Add(float(point.X), float(point.Y))
    return points


def _station_from_pop(polyline: Any, pop: Any) -> float:
    try:
        return float(polyline.DistanceAlong(pop))
    except Exception:
        point = pop.PointM
        try:
            return float(point.M)
        except Exception:
            return 0.0


def _resolve_existing_path(path_value: Any, bases: list[Path]) -> Optional[Path]:
    if path_value is None:
        return None
    path_text = str(path_value).strip()
    if not path_text:
        return None
    candidate = Path(path_text)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    for base in bases:
        resolved = base / candidate
        if resolved.exists():
            return resolved
    return candidate if candidate.exists() else None


def _load_results_geometry_terrain(
    plan_hdf_path: Path,
    geometry_hdf_path: Path | None,
    terrain_hdf_path: Path | None,
) -> tuple[Any, Any, Any]:
    from RasMapperLib import RASGeometry, RASResults, TerrainLayer  # type: ignore

    results = RASResults(str(plan_hdf_path))
    if not bool(results.LoadedSuccessfully) or int(results.ProfileCount) <= 0:
        raise RuntimeError(
            "RASResults did not load a computed result profile from "
            f"{plan_hdf_path}. Pass a computed plan HDF such as *.p##.hdf."
        )

    if geometry_hdf_path is not None:
        if not geometry_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF does not exist: {geometry_hdf_path}")
        geometry = RASGeometry(str(geometry_hdf_path))
        results.Geometry = geometry
        geometry.Results = results
    else:
        geometry = results.Geometry
        if geometry is None:
            geometry = RASGeometry(results)
            results.Geometry = geometry

    if geometry is None:
        raise RuntimeError(f"Could not resolve geometry for {plan_hdf_path}")

    terrain = None
    if terrain_hdf_path is not None:
        if not terrain_hdf_path.exists():
            raise FileNotFoundError(f"Terrain HDF does not exist: {terrain_hdf_path}")
        terrain = TerrainLayer(terrain_hdf_path.stem, str(terrain_hdf_path), False)
    else:
        terrain = geometry.Terrain
        terrain_filename = str(getattr(geometry, "TerrainFilename", "") or "")
        terrain_path = _resolve_existing_path(
            terrain_filename,
            [
                plan_hdf_path.parent,
                geometry_hdf_path.parent if geometry_hdf_path is not None else plan_hdf_path.parent,
            ],
        )
        if terrain is None and terrain_path is not None:
            terrain = TerrainLayer(terrain_path.stem, str(terrain_path), False)

    if terrain is None:
        raise RuntimeError(
            "Could not resolve terrain for velocity profile extraction. "
            "Pass terrain_hdf_path or use a plan/geometry with an associated terrain."
        )

    return results, geometry, terrain


def _resolve_profile_index(results: Any, time_index: int | str) -> int:
    profile_count = int(results.ProfileCount)
    if isinstance(time_index, str):
        if time_index.strip().lower() == "max":
            raise ValueError("time_index='max' is not supported by VelocityRenderer.Compute")
        for idx in range(profile_count):
            try:
                if str(results.ProfileName(idx)).strip() == time_index.strip():
                    return idx
            except Exception:
                continue
        raise ValueError(f"profile name not found in RAS results: {time_index!r}")

    profile_index = int(time_index)
    if profile_index < 0:
        profile_index += profile_count
    if profile_index < 0 or profile_index >= profile_count:
        raise IndexError(
            f"time_index {time_index} is outside available profiles "
            f"0..{profile_count - 1}"
        )
    return profile_index


def _map_profile_points(
    geometry: Any,
    terrain: Any,
    polyline: Any,
    sample_spacing: float,
) -> tuple[Any, Any]:
    from RasMapperLib import PointOnPolyline  # type: ignore
    from System.Collections.Generic import List  # type: ignore

    intersections = List[PointOnPolyline]()
    try:
        result = geometry.MapPixels(polyline, terrain, intersections, float(sample_spacing))
    except TypeError:
        result = geometry.MapPixels(polyline, intersections, float(sample_spacing))

    if isinstance(result, tuple):
        map_points = result[0]
        if len(result) > 1:
            intersections = result[1]
    else:
        map_points = result

    if map_points is None or int(map_points.InputCount) == 0:
        raise RuntimeError("RAS Mapper did not produce profile sample points")
    if intersections is None or int(intersections.Count) == 0:
        raise RuntimeError("RAS Mapper did not return profile-line intersections")
    return map_points, intersections


def _compute_velocity_arrays(
    results: Any,
    profile_index: int,
    map_points: Any,
    terrain_values: Any,
) -> tuple[Any, Any, Any, Any]:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import VelocityRenderer  # type: ignore

    cache = CacheCollection()
    try:
        computed = VelocityRenderer.Compute(
            results,
            profile_index,
            map_points,
            terrain_values,
            None,
            None,
            None,
            cache,
            None,
            True,
        )
    except TypeError:
        renderer = VelocityRenderer(results, cache, True)
        computed = renderer.Compute(
            profile_index,
            map_points,
            terrain_values,
            None,
            None,
            None,
            None,
        )

    if not isinstance(computed, tuple) or len(computed) != 4:
        raise RuntimeError(
            "Unexpected VelocityRenderer.Compute return value; expected four arrays"
        )
    return computed


def _decode_hdf_name(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def _mesh_names_from_hdf(geometry_hdf_path: Path | None) -> list[str]:
    if geometry_hdf_path is None or not geometry_hdf_path.exists():
        return []

    with h5py.File(geometry_hdf_path, "r") as hdf_file:
        attrs_path = "Geometry/2D Flow Areas/Attributes"
        if attrs_path not in hdf_file:
            return []
        attrs = hdf_file[attrs_path][()]
        if getattr(attrs, "dtype", None) is not None and attrs.dtype.names:
            name_field = "Name" if "Name" in attrs.dtype.names else attrs.dtype.names[0]
            return [_decode_hdf_name(row[name_field]) for row in attrs]
    return []


def _iter_mesh_map_points(mesh_map: Any) -> list[int]:
    indexes: list[int] = []
    cells = getattr(mesh_map, "Cells", None)
    if cells is None:
        return indexes
    for cell in cells:
        points = getattr(cell, "MapPoints", None)
        if points is None:
            continue
        for point in points:
            try:
                indexes.append(int(point.Index))
            except Exception:
                continue
    return indexes


def _mesh_names_from_map_points(
    map_points: Any,
    sample_count: int,
    mesh_names: list[str],
) -> np.ndarray:
    names = np.full(sample_count, None, dtype=object)

    for accessor in ("FlatMapped2DAreas", "SlopingMapped2DAreas"):
        try:
            mesh_maps = getattr(map_points, accessor)()
        except Exception:
            continue
        for mesh_map in mesh_maps:
            try:
                mesh_index = int(mesh_map.MeshIndex)
            except Exception:
                mesh_index = -1
            mesh_name = (
                mesh_names[mesh_index]
                if 0 <= mesh_index < len(mesh_names)
                else str(mesh_index)
            )
            for idx in _iter_mesh_map_points(mesh_map):
                if 0 <= idx < sample_count:
                    names[idx] = mesh_name

    return names


def _point_segment_distance_sq(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> np.ndarray:
    segment = end - start
    denom = np.sum(segment * segment, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.sum((point - start) * segment, axis=1) / denom
    t = np.clip(np.nan_to_num(t, nan=0.0, posinf=0.0, neginf=0.0), 0.0, 1.0)
    projection = start + segment * t[:, None]
    delta = projection - point
    return np.sum(delta * delta, axis=1)


def _nearest_face_ids(
    geometry_hdf_path: Path | None,
    x: np.ndarray,
    y: np.ndarray,
    mesh_name: np.ndarray,
) -> np.ndarray:
    face_ids = np.full(len(x), -1, dtype=int)
    if geometry_hdf_path is None or not geometry_hdf_path.exists():
        return face_ids

    with h5py.File(geometry_hdf_path, "r") as hdf_file:
        for name in sorted({str(value) for value in mesh_name if value is not None}):
            mesh_path = f"Geometry/2D Flow Areas/{name}"
            fp_path = f"{mesh_path}/FacePoints Coordinate"
            face_path = f"{mesh_path}/Faces FacePoint Indexes"
            if fp_path not in hdf_file or face_path not in hdf_file:
                continue

            face_points = np.asarray(hdf_file[fp_path][()], dtype=float)
            face_indexes = np.asarray(hdf_file[face_path][()], dtype=int)
            valid_faces = (
                (face_indexes[:, 0] >= 0)
                & (face_indexes[:, 1] >= 0)
                & (face_indexes[:, 0] < len(face_points))
                & (face_indexes[:, 1] < len(face_points))
            )
            if not np.any(valid_faces):
                continue

            valid_ids = np.flatnonzero(valid_faces)
            start = face_points[face_indexes[valid_faces, 0], :2]
            end = face_points[face_indexes[valid_faces, 1], :2]

            sample_indexes = np.flatnonzero(mesh_name == name)
            for sample_idx in sample_indexes:
                point = np.array([x[sample_idx], y[sample_idx]], dtype=float)
                distances = _point_segment_distance_sq(point, start, end)
                face_ids[sample_idx] = int(valid_ids[int(np.nanargmin(distances))])

    return face_ids


def query_polyline_velocity(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper velocity profile along a polyline."""
    load_clr()

    from RasMapperLib import Polyline  # type: ignore

    plan_hdf_path = Path(plan_hdf_path)
    geometry_hdf_path = Path(geometry_hdf_path) if geometry_hdf_path else None
    terrain_hdf_path = Path(terrain_hdf_path) if terrain_hdf_path else None

    xy = np.asarray(polyline_xy, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or xy.shape[0] < 2:
        raise ValueError("polyline_xy must have shape (N, 2) with at least two rows")

    spacing = DEFAULT_SAMPLE_SPACING if sample_spacing is None else float(sample_spacing)
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("sample_spacing must be a positive finite value")

    results, geometry, terrain = _load_results_geometry_terrain(
        plan_hdf_path,
        geometry_hdf_path,
        terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(results, time_index)

    polyline = Polyline(_point_ms_from_xy(xy))
    map_points, intersections = _map_profile_points(
        geometry,
        terrain,
        polyline,
        spacing,
    )
    sample_points = _point_ms_from_intersections(intersections)
    terrain_values = terrain.ComputePointElevations(sample_points)
    vx_raw, vy_raw, vmag_raw, depth_raw = _compute_velocity_arrays(
        results,
        profile_index,
        map_points,
        terrain_values,
    )

    sample_count = min(
        int(intersections.Count),
        len(vx_raw),
        len(vy_raw),
        len(vmag_raw),
        len(depth_raw),
        len(terrain_values),
    )
    if sample_count <= 0:
        raise RuntimeError("VelocityRenderer returned no profile rows")

    station = np.zeros(sample_count, dtype=float)
    x = np.zeros(sample_count, dtype=float)
    y = np.zeros(sample_count, dtype=float)
    for idx in range(sample_count):
        pop = intersections[idx]
        point = pop.PointM
        station[idx] = _station_from_pop(polyline, pop)
        x[idx] = float(point.X)
        y[idx] = float(point.Y)

    mesh_names = _mesh_names_from_hdf(geometry_hdf_path)
    mesh_name = _mesh_names_from_map_points(map_points, sample_count, mesh_names)
    face_id = _nearest_face_ids(geometry_hdf_path, x, y, mesh_name)

    return {
        "station": station,
        "x": x,
        "y": y,
        "mesh_name": mesh_name,
        "face_id": face_id,
        "velocity_x": _clean_float_array(vx_raw, sample_count),
        "velocity_y": _clean_float_array(vy_raw, sample_count),
        "velocity_mag": _clean_float_array(vmag_raw, sample_count),
        "depth": _clean_float_array(depth_raw, sample_count),
        "terrain_elev": _clean_float_array(terrain_values, sample_count),
    }
