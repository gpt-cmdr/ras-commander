"""Polyline profile extraction through RasMapperLib renderers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import h5py
import numpy as np

from ..LoggingConfig import get_logger
from .clr_bootstrap import load_clr

logger = get_logger(__name__)

MISSING_LIMIT = 1.0e30
MISSING_SENTINELS = (-9999.0,)
DEFAULT_SAMPLE_SPACING = 50.0


@dataclass
class MapPointsContext:
    """Shared RAS Mapper profile-line setup reused by renderer calls."""

    plan_hdf_path: Path
    geometry_hdf_path: Path | None
    terrain_hdf_path: Path | None
    results: Any
    geometry: Any
    terrain: Any
    polyline: Any
    map_points: Any
    intersections: Any
    terrain_values: Any
    station: np.ndarray
    x: np.ndarray
    y: np.ndarray
    mesh_name: np.ndarray
    face_id: np.ndarray


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


def _build_map_points(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> MapPointsContext:
    """Build shared RAS Mapper profile-line objects and sample metadata."""
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

    polyline = Polyline(_point_ms_from_xy(xy))
    map_points, intersections = _map_profile_points(
        geometry,
        terrain,
        polyline,
        spacing,
    )
    sample_points = _point_ms_from_intersections(intersections)
    terrain_values = terrain.ComputePointElevations(sample_points)

    sample_count = min(
        int(intersections.Count),
        len(terrain_values),
    )
    if sample_count <= 0:
        raise RuntimeError("RAS Mapper returned no profile rows")

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

    return MapPointsContext(
        plan_hdf_path=plan_hdf_path,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
        results=results,
        geometry=geometry,
        terrain=terrain,
        polyline=polyline,
        map_points=map_points,
        intersections=intersections,
        terrain_values=terrain_values,
        station=station,
        x=x,
        y=y,
        mesh_name=mesh_name,
        face_id=face_id,
    )


def _base_profile_data(
    context: MapPointsContext,
    sample_count: int | None = None,
) -> dict[str, np.ndarray]:
    count = len(context.station) if sample_count is None else min(sample_count, len(context.station))
    return {
        "station": context.station[:count],
        "x": context.x[:count],
        "y": context.y[:count],
        "mesh_name": context.mesh_name[:count],
        "face_id": context.face_id[:count],
        "terrain_elev": _clean_float_array(context.terrain_values, count),
    }


def _single_ref_array(computed: Any) -> Any:
    if isinstance(computed, tuple):
        if not computed:
            raise RuntimeError("Renderer.Compute returned an empty tuple")
        return computed[0]
    return computed


def _compute_wse_array(
    results: Any,
    profile_index: int,
    map_points: Any,
    terrain_values: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import WaterSurfaceRenderer  # type: ignore

    return _single_ref_array(
        WaterSurfaceRenderer.Compute(
            results,
            profile_index,
            map_points,
            None,
            terrain_values,
            CacheCollection(),
            True,
        )
    )


def _compute_flow_array(
    results: Any,
    profile_index: int,
    map_points: Any,
    terrain_values: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import FlowRenderer  # type: ignore

    return _single_ref_array(
        FlowRenderer.Compute(
            results,
            profile_index,
            map_points,
            terrain_values,
            None,
            CacheCollection(),
        )
    )


def _compute_velocity_timeseries_arrays(
    results: Any,
    map_points: Any,
    terrain_values: Any,
) -> tuple[Any, Any, Any, Any]:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import VelocityTimeSeries  # type: ignore

    computed = VelocityTimeSeries.Compute(
        results,
        map_points,
        terrain_values,
        None,
        None,
        None,
        CacheCollection(),
        None,
        None,
    )
    if not isinstance(computed, tuple) or len(computed) != 4:
        raise RuntimeError(
            "Unexpected VelocityTimeSeries.Compute return value; expected four arrays"
        )
    velocity_mag_raw, velocity_x_raw, velocity_y_raw, depth_raw = computed
    return velocity_x_raw, velocity_y_raw, velocity_mag_raw, depth_raw


def _compute_wse_timeseries_array(
    results: Any,
    map_points: Any,
    terrain_values: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import WaterSurfaceTimeSeries  # type: ignore

    return _single_ref_array(
        WaterSurfaceTimeSeries.Compute(
            results,
            map_points,
            None,
            CacheCollection(),
            terrain_values,
            None,
        )
    )


def _compute_pipe_velocity_array(
    results: Any,
    profile_index: int,
    map_points: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import VelocityRendererPipe  # type: ignore

    return _single_ref_array(
        VelocityRendererPipe.Compute(
            results,
            profile_index,
            map_points,
            None,
            CacheCollection(),
            True,
        )
    )


def _compute_pipe_flow_array(
    results: Any,
    profile_index: int,
    map_points: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import FlowRendererPipe  # type: ignore

    return _single_ref_array(
        FlowRendererPipe.Compute(
            results,
            profile_index,
            map_points,
            None,
            CacheCollection(),
            True,
        )
    )


def _compute_pipe_velocity_timeseries_arrays(
    results: Any,
    map_points: Any,
) -> tuple[Any, Any]:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import VelocityPipeTimeSeries  # type: ignore

    computed = VelocityPipeTimeSeries.Compute(
        results,
        map_points,
        None,
        CacheCollection(),
        None,
        None,
    )
    if not isinstance(computed, tuple) or len(computed) != 2:
        raise RuntimeError(
            "Unexpected VelocityPipeTimeSeries.Compute return value; expected two arrays"
        )
    velocity_raw, depth_raw = computed
    return velocity_raw, depth_raw


def _compute_pipe_flow_timeseries_arrays(
    results: Any,
    map_points: Any,
) -> tuple[Any, Any]:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import FlowPipeTimeSeries  # type: ignore

    computed = FlowPipeTimeSeries.Compute(
        results,
        map_points,
        None,
        CacheCollection(),
        None,
        None,
    )
    if not isinstance(computed, tuple) or len(computed) != 2:
        raise RuntimeError(
            "Unexpected FlowPipeTimeSeries.Compute return value; expected two arrays"
        )
    flow_raw, depth_raw = computed
    return flow_raw, depth_raw


def _compute_wse_difference_array(
    base_results: Any,
    compare_results: Any,
    profile_index: int,
    map_points: Any,
    terrain_values: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import WaterSurfaceDifferenceRenderer  # type: ignore

    return _single_ref_array(
        WaterSurfaceDifferenceRenderer.Compute(
            base_results,
            compare_results,
            profile_index,
            map_points,
            None,
            terrain_values,
            CacheCollection(),
        )
    )


def _compute_velocity_difference_array(
    base_results: Any,
    compare_results: Any,
    profile_index: int,
    map_points: Any,
    terrain_values: Any,
) -> Any:
    from H5Assist.Caching import CacheCollection  # type: ignore
    from RasMapperLib.Render import VelocityDifferenceRenderer  # type: ignore

    return _single_ref_array(
        VelocityDifferenceRenderer.Compute(
            base_results,
            compare_results,
            profile_index,
            map_points,
            None,
            terrain_values,
            CacheCollection(),
        )
    )


def _depth_from_wse(wse: np.ndarray, terrain_elev: np.ndarray) -> np.ndarray:
    depth = np.full(len(wse), np.nan, dtype=float)
    valid = np.isfinite(wse) & np.isfinite(terrain_elev)
    depth[valid] = np.maximum(wse[valid] - terrain_elev[valid], 0.0)
    return depth


def _profile_count(results: Any) -> int:
    count = int(results.ProfileCount)
    if count <= 0:
        raise RuntimeError("RASResults did not expose any result profiles")
    return count


def _normalize_time_range(
    results: Any,
    time_range: tuple[int, int] | None,
) -> list[int]:
    count = _profile_count(results)
    if time_range is None:
        start, stop = 0, count
    else:
        if len(time_range) != 2:
            raise ValueError("time_range must be a (start, stop) tuple")
        start, stop = int(time_range[0]), int(time_range[1])
        if start < 0:
            start += count
        if stop < 0:
            stop += count
    if start < 0 or stop < 0 or start > stop or stop > count:
        raise IndexError(
            f"time_range ({start}, {stop}) is outside available profiles 0..{count}"
        )
    return list(range(start, stop))


def _decode_time_value(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def _profile_times(context: MapPointsContext) -> np.ndarray:
    time_path = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Unsteady Time Series/Time Date Stamp (ms)"
    )
    try:
        with h5py.File(context.plan_hdf_path, "r") as hdf_file:
            if time_path in hdf_file:
                return np.asarray(
                    [_decode_time_value(value) for value in hdf_file[time_path][()]],
                    dtype=object,
                )
    except Exception:
        pass

    values = []
    for idx in range(_profile_count(context.results)):
        try:
            values.append(str(context.results.ProfileName(idx)).strip())
        except Exception:
            values.append(str(idx))
    return np.asarray(values, dtype=object)


def _timeseries_base_data(
    context: MapPointsContext,
    profile_indexes: Sequence[int],
    sample_count: int | None = None,
) -> dict[str, np.ndarray]:
    base = _base_profile_data(context, sample_count)
    n_times = len(profile_indexes)
    n_samples = len(base["station"])
    times = _profile_times(context)
    safe_times = np.asarray(
        [
            times[idx] if 0 <= idx < len(times) else str(idx)
            for idx in profile_indexes
        ],
        dtype=object,
    )
    return {
        "time_index": np.repeat(np.asarray(profile_indexes, dtype=int), n_samples),
        "time": np.repeat(safe_times, n_samples),
        "station": np.tile(base["station"], n_times),
        "x": np.tile(base["x"], n_times),
        "y": np.tile(base["y"], n_times),
        "mesh_name": np.tile(base["mesh_name"], n_times),
        "face_id": np.tile(base["face_id"], n_times),
        "terrain_elev": np.tile(base["terrain_elev"], n_times),
    }


def _flatten_timeseries(values: list[np.ndarray]) -> np.ndarray:
    if not values:
        return np.asarray([], dtype=float)
    return np.vstack(values).reshape(-1)


def _flatten_sample_major_timeseries(
    values: Any,
    profile_indexes: Sequence[int],
    sample_count: int,
) -> np.ndarray:
    """Return time-major flattened values from RAS Mapper sample-major output."""
    matrix = np.full((len(profile_indexes), sample_count), np.nan, dtype=float)
    if sample_count <= 0:
        return matrix.reshape(-1)
    if len(values) < sample_count:
        raise RuntimeError(
            "TimeSeries.Compute returned fewer profile samples than MapPixels"
        )

    for sample_idx in range(sample_count):
        sample_values = values[sample_idx]
        for time_pos, profile_index in enumerate(profile_indexes):
            if profile_index >= len(sample_values):
                raise RuntimeError(
                    "TimeSeries.Compute returned fewer timesteps than RASResults.ProfileCount"
                )
            value = sample_values[profile_index]
            if not _is_missing(value):
                matrix[time_pos, sample_idx] = float(value)
    return matrix.reshape(-1)


def _ensure_pipe_network_results(plan_hdf_path: Path) -> None:
    pipe_paths = (
        "Geometry/Pipe Networks",
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Pipe Networks",
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Pipe Network",
    )
    with h5py.File(plan_hdf_path, "r") as hdf_file:
        if any(path in hdf_file for path in pipe_paths):
            return
    raise NotImplementedError(
        "Pipe-network profile extraction requires a plan HDF with pipe network "
        "geometry/results. This plan does not expose pipe network groups."
    )


def _load_compare_results(
    compare_hdf_path: Path,
    context: MapPointsContext,
) -> Any:
    compare_results, _, _ = _load_results_geometry_terrain(
        Path(compare_hdf_path),
        context.geometry_hdf_path,
        context.terrain_hdf_path,
    )
    return compare_results


def query_polyline_velocity(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper velocity profile along a polyline."""
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(context.results, time_index)
    vx_raw, vy_raw, vmag_raw, depth_raw = _compute_velocity_arrays(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )

    sample_count = min(
        len(context.station),
        len(vx_raw),
        len(vy_raw),
        len(vmag_raw),
        len(depth_raw),
        len(context.terrain_values),
    )
    if sample_count <= 0:
        raise RuntimeError("VelocityRenderer returned no profile rows")

    result = _base_profile_data(context, sample_count)
    result.update(
        {
            "velocity_x": _clean_float_array(vx_raw, sample_count),
            "velocity_y": _clean_float_array(vy_raw, sample_count),
            "velocity_mag": _clean_float_array(vmag_raw, sample_count),
            "depth": _clean_float_array(depth_raw, sample_count),
        }
    )
    return result


def query_polyline_wse(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper water-surface profile along a polyline."""
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(context.results, time_index)
    wse_raw = _compute_wse_array(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    sample_count = min(len(context.station), len(wse_raw), len(context.terrain_values))
    if sample_count <= 0:
        raise RuntimeError("WaterSurfaceRenderer returned no profile rows")

    result = _base_profile_data(context, sample_count)
    wse = _clean_float_array(wse_raw, sample_count)
    result.update({"wse": wse, "depth": _depth_from_wse(wse, result["terrain_elev"])})
    return result


def query_polyline_flow(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper flow profile along a polyline."""
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(context.results, time_index)
    flow_raw = _compute_flow_array(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    wse_raw = _compute_wse_array(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    sample_count = min(
        len(context.station),
        len(flow_raw),
        len(wse_raw),
        len(context.terrain_values),
    )
    if sample_count <= 0:
        raise RuntimeError("FlowRenderer returned no profile rows")

    result = _base_profile_data(context, sample_count)
    wse = _clean_float_array(wse_raw, sample_count)
    result.update(
        {
            "flow": _clean_float_array(flow_raw, sample_count),
            "depth": _depth_from_wse(wse, result["terrain_elev"]),
        }
    )
    return result


def query_polyline_velocity_timeseries(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_range: tuple[int, int] | None = None,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract velocity time series with RAS Mapper VelocityTimeSeries.Compute."""
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_indexes = _normalize_time_range(context.results, time_range)
    vx_raw, vy_raw, vmag_raw, depth_raw = _compute_velocity_timeseries_arrays(
        context.results,
        context.map_points,
        context.terrain_values,
    )
    n_samples = min(len(context.station), len(vx_raw), len(vy_raw), len(vmag_raw), len(depth_raw))
    result = _timeseries_base_data(context, profile_indexes, sample_count=n_samples)
    result.update(
        {
            "velocity_x": _flatten_sample_major_timeseries(
                vx_raw,
                profile_indexes,
                n_samples,
            ),
            "velocity_y": _flatten_sample_major_timeseries(
                vy_raw,
                profile_indexes,
                n_samples,
            ),
            "velocity_mag": _flatten_sample_major_timeseries(
                vmag_raw,
                profile_indexes,
                n_samples,
            ),
            "depth": _flatten_sample_major_timeseries(
                depth_raw,
                profile_indexes,
                n_samples,
            ),
        }
    )
    return result


def query_polyline_wse_timeseries(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_range: tuple[int, int] | None = None,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract water-surface time series with WaterSurfaceTimeSeries.Compute."""
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_indexes = _normalize_time_range(context.results, time_range)
    wse_raw = _compute_wse_timeseries_array(
        context.results,
        context.map_points,
        context.terrain_values,
    )
    n_samples = min(len(context.station), len(wse_raw))
    wse = _flatten_sample_major_timeseries(wse_raw, profile_indexes, n_samples)
    terrain = np.tile(
        _clean_float_array(context.terrain_values, n_samples),
        len(profile_indexes),
    )
    result = _timeseries_base_data(context, profile_indexes, sample_count=n_samples)
    result.update(
        {
            "wse": wse,
            "depth": _depth_from_wse(wse, terrain),
        }
    )
    return result


def query_polyline_flow_timeseries(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_range: tuple[int, int] | None = None,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """
    Extract flow time series with native FlowRenderer.Compute calls.

    HEC-RAS 7.0 exposes no 2D ``RasMapperLib.Render.FlowTimeSeries`` class.
    RAS Mapper uses the single-profile flow renderer for profile animations,
    so this method loops the literal native ``FlowRenderer.Compute`` call.
    """
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_indexes = _normalize_time_range(context.results, time_range)
    n_samples = len(context.station)
    flow_values: list[np.ndarray] = []
    depth_values: list[np.ndarray] = []
    terrain = _clean_float_array(context.terrain_values, n_samples)
    for profile_index in profile_indexes:
        flow_raw = _compute_flow_array(
            context.results,
            profile_index,
            context.map_points,
            context.terrain_values,
        )
        wse_raw = _compute_wse_array(
            context.results,
            profile_index,
            context.map_points,
            context.terrain_values,
        )
        count = min(n_samples, len(flow_raw), len(wse_raw))
        if count != n_samples:
            raise RuntimeError(
                "FlowRenderer returned inconsistent profile lengths across timesteps"
            )
        wse = _clean_float_array(wse_raw, n_samples)
        flow_values.append(_clean_float_array(flow_raw, n_samples))
        depth_values.append(_depth_from_wse(wse, terrain))

    result = _timeseries_base_data(context, profile_indexes)
    result.update(
        {
            "flow": _flatten_timeseries(flow_values),
            "depth": _flatten_timeseries(depth_values),
        }
    )
    return result


def query_polyline_pipe_velocity(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper pipe velocity profile along a polyline."""
    plan_hdf_path = Path(plan_hdf_path)
    _ensure_pipe_network_results(plan_hdf_path)
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(context.results, time_index)
    velocity_raw = _compute_pipe_velocity_array(
        context.results,
        profile_index,
        context.map_points,
    )
    sample_count = min(len(context.station), len(velocity_raw))
    result = _base_profile_data(context, sample_count)
    result.update(
        {
            "velocity_mag": _clean_float_array(velocity_raw, sample_count),
            "depth": np.full(sample_count, np.nan, dtype=float),
        }
    )
    return result


def query_polyline_pipe_flow(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract a RAS Mapper pipe flow profile along a polyline."""
    plan_hdf_path = Path(plan_hdf_path)
    _ensure_pipe_network_results(plan_hdf_path)
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_index = _resolve_profile_index(context.results, time_index)
    flow_raw = _compute_pipe_flow_array(context.results, profile_index, context.map_points)
    sample_count = min(len(context.station), len(flow_raw))
    result = _base_profile_data(context, sample_count)
    result.update(
        {
            "flow": _clean_float_array(flow_raw, sample_count),
            "depth": np.full(sample_count, np.nan, dtype=float),
        }
    )
    return result


def query_polyline_pipe_velocity_timeseries(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_range: tuple[int, int] | None = None,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract pipe velocity time series with VelocityPipeTimeSeries.Compute."""
    plan_hdf_path = Path(plan_hdf_path)
    _ensure_pipe_network_results(plan_hdf_path)
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_indexes = _normalize_time_range(context.results, time_range)
    velocity_raw, depth_raw = _compute_pipe_velocity_timeseries_arrays(
        context.results,
        context.map_points,
    )
    n_samples = min(len(context.station), len(velocity_raw), len(depth_raw))
    result = _timeseries_base_data(context, profile_indexes, sample_count=n_samples)
    result.update(
        {
            "velocity_mag": _flatten_sample_major_timeseries(
                velocity_raw,
                profile_indexes,
                n_samples,
            ),
            "depth": _flatten_sample_major_timeseries(
                depth_raw,
                profile_indexes,
                n_samples,
            ),
        }
    )
    return result


def query_polyline_pipe_flow_timeseries(
    plan_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_range: tuple[int, int] | None = None,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract pipe flow time series with FlowPipeTimeSeries.Compute."""
    plan_hdf_path = Path(plan_hdf_path)
    _ensure_pipe_network_results(plan_hdf_path)
    context = _build_map_points(
        plan_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    profile_indexes = _normalize_time_range(context.results, time_range)
    flow_raw, depth_raw = _compute_pipe_flow_timeseries_arrays(
        context.results,
        context.map_points,
    )
    n_samples = min(len(context.station), len(flow_raw), len(depth_raw))
    result = _timeseries_base_data(context, profile_indexes, sample_count=n_samples)
    result.update(
        {
            "flow": _flatten_sample_major_timeseries(
                flow_raw,
                profile_indexes,
                n_samples,
            ),
            "depth": _flatten_sample_major_timeseries(
                depth_raw,
                profile_indexes,
                n_samples,
            ),
        }
    )
    return result


def query_polyline_wse_difference(
    base_hdf_path: Path,
    compare_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract RAS Mapper water-surface differences along a polyline."""
    context = _build_map_points(
        base_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    compare_results = _load_compare_results(compare_hdf_path, context)
    profile_index = _resolve_profile_index(context.results, time_index)
    wse_base_raw = _compute_wse_array(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    wse_compare_raw = _compute_wse_array(
        compare_results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    wse_delta_raw = _compute_wse_difference_array(
        context.results,
        compare_results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    sample_count = min(
        len(context.station),
        len(wse_base_raw),
        len(wse_compare_raw),
        len(wse_delta_raw),
    )
    result = _base_profile_data(context, sample_count)
    result.update(
        {
            "wse_base": _clean_float_array(wse_base_raw, sample_count),
            "wse_compare": _clean_float_array(wse_compare_raw, sample_count),
            "wse_delta": _clean_float_array(wse_delta_raw, sample_count),
        }
    )
    return result


def query_polyline_velocity_difference(
    base_hdf_path: Path,
    compare_hdf_path: Path,
    polyline_xy: np.ndarray,
    time_index: int,
    sample_spacing: float | None = None,
    geometry_hdf_path: Path | None = None,
    terrain_hdf_path: Path | None = None,
) -> dict[str, np.ndarray]:
    """Extract RAS Mapper velocity differences along a polyline."""
    context = _build_map_points(
        base_hdf_path,
        polyline_xy,
        sample_spacing=sample_spacing,
        geometry_hdf_path=geometry_hdf_path,
        terrain_hdf_path=terrain_hdf_path,
    )
    compare_results = _load_compare_results(compare_hdf_path, context)
    profile_index = _resolve_profile_index(context.results, time_index)
    base_vx_raw, base_vy_raw, base_vmag_raw, _ = _compute_velocity_arrays(
        context.results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    compare_vx_raw, compare_vy_raw, compare_vmag_raw, _ = _compute_velocity_arrays(
        compare_results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    vmag_delta_raw = _compute_velocity_difference_array(
        context.results,
        compare_results,
        profile_index,
        context.map_points,
        context.terrain_values,
    )
    sample_count = min(
        len(context.station),
        len(base_vx_raw),
        len(base_vy_raw),
        len(base_vmag_raw),
        len(compare_vx_raw),
        len(compare_vy_raw),
        len(compare_vmag_raw),
        len(vmag_delta_raw),
    )
    velocity_x_base = _clean_float_array(base_vx_raw, sample_count)
    velocity_y_base = _clean_float_array(base_vy_raw, sample_count)
    velocity_x_compare = _clean_float_array(compare_vx_raw, sample_count)
    velocity_y_compare = _clean_float_array(compare_vy_raw, sample_count)
    result = _base_profile_data(context, sample_count)
    result.update(
        {
            "velocity_x_base": velocity_x_base,
            "velocity_y_base": velocity_y_base,
            "velocity_mag_base": _clean_float_array(base_vmag_raw, sample_count),
            "velocity_x_compare": velocity_x_compare,
            "velocity_y_compare": velocity_y_compare,
            "velocity_mag_compare": _clean_float_array(compare_vmag_raw, sample_count),
            "velocity_x_delta": velocity_x_compare - velocity_x_base,
            "velocity_y_delta": velocity_y_compare - velocity_y_base,
            "velocity_mag_delta": _clean_float_array(vmag_delta_raw, sample_count),
        }
    )
    return result
