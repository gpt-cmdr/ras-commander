"""
GeomReferenceFeatures: Insert reference lines and reference points into
HEC-RAS plain text geometry files (.g##).

Reference lines act as virtual cross sections in 2D models, enabling
integrated flow extraction for calibration against streamflow gauges.
Reference points provide WSE/depth extraction at specific cell locations.

Format discovered from BayouConway production model (2026-04-08):
  Reference Line: keyword-value pairs + fixed-width coordinate block
  Reference Point: stored as IC Points with "Reference Point" name prefix

All methods are static. Do not instantiate.
"""

import math
import shutil
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import numpy as np

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def _format_coord_line(values: List[float], width: int = 16) -> str:
    """Format coordinate values into fixed-width fields, 4 values per line."""
    parts = []
    for v in values:
        s = f"{v:.10g}"
        parts.append(s.rjust(width))
    return "".join(parts)


def _build_reference_line_block(
    name: str,
    storage_area: str,
    coordinates: np.ndarray,
) -> List[str]:
    """
    Build a reference line plain text block.

    Format (from BayouConway production model):
        Reference Line Name=<name padded to 40>
        Reference Line Storage Area=<SA padded to 16>
        Reference Line Start Position= X , Y
        Reference Line Middle Position= Xmid , Ymid
        Reference Line End Position= X , Y
        Reference Line Arc= N
        <fixed-width coordinates, 2 x,y pairs per line>
        Reference Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308
    """
    coords = np.asarray(coordinates, dtype=np.float64)
    n_pts = len(coords)

    x_start, y_start = coords[0]
    x_end, y_end = coords[-1]
    mid_idx = n_pts // 2
    x_mid, y_mid = coords[mid_idx]

    lines = []
    lines.append(f"Reference Line Name={name:<40s}")
    lines.append(f"Reference Line Storage Area={storage_area:<16s}")
    lines.append(
        f"Reference Line Start Position= {x_start} , {y_start} "
    )
    lines.append(
        f"Reference Line Middle Position= {x_mid} , {y_mid} "
    )
    lines.append(
        f"Reference Line End Position= {x_end} , {y_end} "
    )
    lines.append(f"Reference Line Arc= {n_pts} ")

    # Coordinate block: 4 values per line (x1,y1,x2,y2), 16 chars each
    flat_values = coords.flatten().tolist()
    values_per_line = 4  # 2 x,y pairs
    for i in range(0, len(flat_values), values_per_line):
        chunk = flat_values[i : i + values_per_line]
        lines.append(_format_coord_line(chunk))

    lines.append(
        "Reference Line Text Position="
        " 1.79769313486232E+308 , 1.79769313486232E+308 "
    )

    return lines


def _build_ic_point_block(name: str, x: float, y: float) -> List[str]:
    """
    Build a reference point (IC Point) plain text block.

    Format:
        IC Point Name=<name padded to 40>
        IC Point Position=X,Y
    """
    return [
        f"IC Point Name={name:<40s}",
        f"IC Point Position={x},{y}",
    ]


def _point_xy(point: Any) -> tuple[float, float]:
    """Return x/y from a Shapely point-like object."""
    return (float(point.x), float(point.y))


def _resolve_name_column(frame: Any, name_column: str) -> Optional[str]:
    """Find a usable name column, preferring common RAS/GIS spellings."""
    if not hasattr(frame, "columns"):
        return None

    columns = list(frame.columns)
    if name_column in columns:
        return name_column

    for candidate in ("Name", "name", "profile_name", "line_name", "id"):
        if candidate in columns:
            return candidate

    return None


def _as_linestring(geometry: Any) -> Any:
    """Normalize a supported geometry/coordinate input to one LineString."""
    from shapely.geometry import LineString
    from shapely.ops import linemerge

    geom_type = getattr(geometry, "geom_type", None)
    if geom_type == "LineString":
        return geometry

    if geom_type == "MultiLineString":
        merged = linemerge(geometry)
        if getattr(merged, "geom_type", None) == "LineString":
            return merged
        raise ValueError(
            "MultiLineString inputs must merge to one continuous line"
        )

    coords = np.asarray(geometry, dtype=float)
    if coords.ndim == 2 and coords.shape[1] == 2 and len(coords) >= 2:
        return LineString(coords)

    raise ValueError(
        "Longitudinal line geometry must be a LineString, mergeable "
        "MultiLineString, or (N, 2) coordinate array"
    )


def _coerce_longitudinal_line_records(
    longitudinal_lines: Any,
    longitudinal_line_name: Optional[str],
    name_column: str,
) -> List[dict]:
    """Normalize supported line inputs to named LineString records."""
    from shapely.geometry import LineString

    records = []

    if hasattr(longitudinal_lines, "geometry"):
        if len(longitudinal_lines) == 0:
            raise ValueError("longitudinal_lines GeoDataFrame is empty")

        resolved_name_column = _resolve_name_column(longitudinal_lines, name_column)
        rows = longitudinal_lines
        if longitudinal_line_name is not None:
            if resolved_name_column is None:
                raise ValueError(
                    "longitudinal_line_name was provided, but no name column "
                    "was found in longitudinal_lines"
                )
            mask = (
                longitudinal_lines[resolved_name_column]
                .astype(str)
                .eq(str(longitudinal_line_name))
            )
            rows = longitudinal_lines[mask]
            if len(rows) == 0:
                raise ValueError(
                    f"Longitudinal line '{longitudinal_line_name}' not found "
                    f"in column '{resolved_name_column}'"
                )

        for idx, row in rows.iterrows():
            if resolved_name_column is not None:
                raw_name = row.get(resolved_name_column, None)
            else:
                raw_name = longitudinal_line_name or f"Line_{idx + 1}"
            records.append(
                {
                    "name": str(raw_name).strip() or f"Line_{idx + 1}",
                    "geometry": _as_linestring(row.geometry),
                }
            )

        return records

    if getattr(longitudinal_lines, "geom_type", None) in {
        "LineString",
        "MultiLineString",
    }:
        records.append(
            {
                "name": longitudinal_line_name or "Longitudinal_Line",
                "geometry": _as_linestring(longitudinal_lines),
            }
        )
        return records

    if isinstance(longitudinal_lines, dict):
        items = [longitudinal_lines]
    else:
        try:
            coords = np.asarray(longitudinal_lines, dtype=float)
            if coords.ndim == 2 and coords.shape[1] == 2:
                return [
                    {
                        "name": longitudinal_line_name or "Longitudinal_Line",
                        "geometry": LineString(coords),
                    }
                ]
        except (TypeError, ValueError):
            pass
        items = list(longitudinal_lines)

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                "longitudinal_lines list inputs must contain dictionaries "
                "with 'geometry' or 'coordinates'"
            )

        raw_name = (
            item.get(name_column)
            or item.get("Name")
            or item.get("name")
            or item.get("profile_name")
            or item.get("line_name")
            or longitudinal_line_name
            or f"Line_{idx + 1}"
        )
        item_name = str(raw_name).strip()
        if (
            longitudinal_line_name is not None
            and item_name != str(longitudinal_line_name)
        ):
            continue

        geometry = item.get("geometry", item.get("coordinates"))
        if geometry is None:
            raise ValueError(
                f"Longitudinal line '{item_name}' is missing geometry or coordinates"
            )
        records.append({"name": item_name, "geometry": _as_linestring(geometry)})

    if longitudinal_line_name is not None and not records:
        raise ValueError(f"Longitudinal line '{longitudinal_line_name}' not found")

    if not records:
        raise ValueError("No longitudinal lines were provided")

    return records


def _station_values(
    line_length: float,
    spacing: float,
    start_station: float,
    end_station: Optional[float],
    include_end: bool,
) -> List[float]:
    """Return station locations along a line."""
    if spacing <= 0:
        raise ValueError(f"spacing must be positive, got {spacing}")
    if line_length <= 0:
        raise ValueError("Longitudinal line length must be positive")

    start = float(start_station)
    if start < 0:
        raise ValueError("start_station must be non-negative")

    end = line_length if end_station is None else float(end_station)
    if end < start:
        raise ValueError("end_station must be greater than or equal to start_station")
    if end > line_length:
        raise ValueError(
            f"end_station ({end}) exceeds line length ({line_length})"
        )

    stations = []
    station = start
    tolerance = max(abs(spacing) * 1.0e-9, 1.0e-9)
    while station <= end + tolerance:
        stations.append(min(station, end))
        station += spacing

    if include_end and (
        not stations or abs(stations[-1] - end) > tolerance
    ):
        stations.append(end)

    return stations


def _tangent_angle_degrees(
    line: Any,
    station: float,
    sample_distance: float,
) -> float:
    """Return local tangent angle in degrees at a station along a line."""
    line_length = float(line.length)
    delta = min(max(float(sample_distance), 1.0e-9), line_length)
    start = max(0.0, float(station) - delta)
    end = min(line_length, float(station) + delta)

    if end <= start:
        if station <= 0:
            end = min(line_length, delta)
        else:
            start = max(0.0, line_length - delta)

    p0 = line.interpolate(start)
    p1 = line.interpolate(end)
    dx = float(p1.x - p0.x)
    dy = float(p1.y - p0.y)
    if abs(dx) <= 1.0e-12 and abs(dy) <= 1.0e-12:
        coords = list(line.coords)
        dx = float(coords[-1][0] - coords[0][0])
        dy = float(coords[-1][1] - coords[0][1])

    if abs(dx) <= 1.0e-12 and abs(dy) <= 1.0e-12:
        raise ValueError("Cannot determine tangent for zero-length line")

    return math.degrees(math.atan2(dy, dx))


def _line_coordinates_from_angle(
    x: float,
    y: float,
    angle_degrees: float,
    total_length: float,
) -> List[tuple[float, float]]:
    """Build two-point line coordinates centered at x/y."""
    half_length = float(total_length) / 2.0
    theta = math.radians(float(angle_degrees))
    dx = math.cos(theta) * half_length
    dy = math.sin(theta) * half_length
    return [(x - dx, y - dy), (x + dx, y + dy)]


class GeomReferenceFeatures:
    """Insert reference lines and reference points into .g## geometry files."""

    @staticmethod
    @log_call
    def generate_reference_lines_from_longitudinal_line(
        longitudinal_lines: Any,
        spacing: float,
        line_length: float,
        *,
        longitudinal_line_name: Optional[str] = None,
        name_column: str = "Name",
        name_template: str = "{source_name}_Ref_{index:03d}",
        start_station: float = 0.0,
        end_station: Optional[float] = None,
        include_end: bool = False,
        tangent_sample_distance: Optional[float] = None,
        extend_by: float = 0.0,
        orientation: str = "normal",
        orientation_plan_hdf: Optional[Union[str, Path]] = None,
        orientation_time_index: Union[int, str] = -1,
        orientation_query_method: str = "nearest",
        orientation_angle_callback: Optional[Callable[[dict], Optional[float]]] = None,
        orientation_fallback: str = "normal",
        velocity_min: float = 1.0e-6,
        depth_min: float = 0.0,
        ras_object: Optional[Any] = None,
        storage_area: Optional[str] = None,
    ) -> List[dict]:
        """
        Generate transverse reference lines along longitudinal/profile lines.

        This creates the same ``{"name", "coordinates"}`` dictionaries accepted
        by :meth:`add_reference_lines`, so callers can review the generated
        transects before writing them to a HEC-RAS plain text geometry file.

        Args:
            longitudinal_lines: A Shapely LineString, GeoDataFrame, coordinate
                array, dict with ``geometry``/``coordinates``, or list of those
                dicts. GeoDataFrame rows can be selected by name.
            spacing: Station interval along each longitudinal line, in model
                units.
            line_length: Generated transverse reference-line length, in model
                units.
            longitudinal_line_name: Optional name of the source line to select
                from GeoDataFrame/list inputs.
            name_column: Preferred source-name column for GeoDataFrame inputs.
            name_template: Format string for generated line names. Available
                fields are ``source_name``, ``index``, ``global_index``,
                ``station``, and ``station_int``.
            start_station: First station along the source line.
            end_station: Last station along the source line. Defaults to the
                source line length.
            include_end: Include ``end_station`` even when it is not on the
                regular spacing interval.
            tangent_sample_distance: Half-window used to compute the local
                tangent direction. Defaults to half the spacing.
            extend_by: Extra length added to each side of the generated line.
            orientation: ``"normal"`` for perpendicular to source line,
                ``"velocity"`` for perpendicular to sampled velocity vector,
                or ``"depth_velocity"`` for velocity orientation only where
                sampled depth exceeds ``depth_min``.
            orientation_plan_hdf: Plan/result HDF used when ``orientation`` is
                ``"velocity"`` or ``"depth_velocity"``.
            orientation_time_index: Time index passed to ``HdfResultsQuery``.
            orientation_query_method: Query method passed to ``HdfResultsQuery``.
            orientation_angle_callback: Optional callable receiving a context
                dict and returning a reference-line angle in degrees. Returning
                ``None`` keeps the normal or velocity-derived angle.
            orientation_fallback: ``"normal"`` or ``"raise"`` when sampled
                velocity/depth data are unavailable at a station.
            velocity_min: Minimum sampled velocity magnitude for velocity-based
                orientation.
            depth_min: Minimum sampled depth for ``"depth_velocity"``.
            ras_object: Optional ``RasPrj`` object for HDF result queries.
            storage_area: Optional 2D flow area name included in returned
                metadata for review.

        Returns:
            List of reference-line dictionaries. Each dictionary includes
            ``name`` and ``coordinates`` for writing, plus station/orientation
            metadata for review.

        Example:
            >>> ref_lines = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
            ...     centerlines_gdf,
            ...     longitudinal_line_name="Main River",
            ...     spacing=500,
            ...     line_length=1500,
            ... )
            >>> GeomReferenceFeatures.add_reference_lines("model.g01", ref_lines, "Perimeter 1")
        """
        if line_length <= 0:
            raise ValueError(f"line_length must be positive, got {line_length}")
        if extend_by < 0:
            raise ValueError("extend_by must be non-negative")

        normalized_orientation = str(orientation).strip().lower()
        valid_orientations = {"normal", "velocity", "depth_velocity"}
        if normalized_orientation not in valid_orientations:
            raise ValueError(
                f"orientation must be one of {sorted(valid_orientations)}, "
                f"got '{orientation}'"
            )

        normalized_fallback = str(orientation_fallback).strip().lower()
        if normalized_fallback not in {"normal", "raise"}:
            raise ValueError("orientation_fallback must be 'normal' or 'raise'")

        if (
            normalized_orientation in {"velocity", "depth_velocity"}
            and orientation_plan_hdf is None
        ):
            raise ValueError(
                "orientation_plan_hdf is required for velocity-based orientation"
            )

        records = _coerce_longitudinal_line_records(
            longitudinal_lines,
            longitudinal_line_name,
            name_column,
        )

        generated_lines = []
        global_index = 1
        total_length = float(line_length) + 2.0 * float(extend_by)

        for record in records:
            source_name = str(record["name"])
            source_line = record["geometry"]
            source_length = float(source_line.length)
            stations = _station_values(
                source_length,
                float(spacing),
                float(start_station),
                end_station,
                bool(include_end),
            )
            if not stations:
                continue

            sample_distance = (
                float(tangent_sample_distance)
                if tangent_sample_distance is not None
                else max(float(spacing) / 2.0, source_length * 1.0e-6)
            )

            station_points = [
                source_line.interpolate(station) for station in stations
            ]
            velocity_samples = GeomReferenceFeatures._sample_velocity_orientation(
                station_points,
                orientation=normalized_orientation,
                orientation_plan_hdf=orientation_plan_hdf,
                orientation_time_index=orientation_time_index,
                orientation_query_method=orientation_query_method,
                orientation_fallback=normalized_fallback,
                velocity_min=velocity_min,
                depth_min=depth_min,
                ras_object=ras_object,
            )

            for line_index, (station, point) in enumerate(
                zip(stations, station_points),
                start=1,
            ):
                x, y = _point_xy(point)
                tangent_angle = _tangent_angle_degrees(
                    source_line,
                    station,
                    sample_distance,
                )
                normal_angle = tangent_angle + 90.0
                selected_angle = normal_angle
                orientation_method = "normal"

                velocity_sample = velocity_samples[line_index - 1]
                velocity_angle = velocity_sample.get("orientation_angle")
                if velocity_angle is not None and np.isfinite(velocity_angle):
                    selected_angle = float(velocity_angle)
                    orientation_method = normalized_orientation
                elif normalized_orientation in {"velocity", "depth_velocity"}:
                    if normalized_fallback == "raise":
                        raise ValueError(
                            "Velocity-based orientation was unavailable at "
                            f"station {station:g} on '{source_name}'"
                        )
                    orientation_method = "normal_fallback"

                context = {
                    "source_name": source_name,
                    "source_geometry": source_line,
                    "index": line_index,
                    "global_index": global_index,
                    "station": float(station),
                    "point": point,
                    "x": x,
                    "y": y,
                    "tangent_angle": float(tangent_angle),
                    "normal_angle": float(normal_angle),
                    "orientation_angle": float(selected_angle),
                    "orientation_method": orientation_method,
                    "velocity_sample": velocity_sample,
                }
                if orientation_angle_callback is not None:
                    callback_angle = orientation_angle_callback(context)
                    if callback_angle is not None:
                        selected_angle = float(callback_angle)
                        orientation_method = "callback"
                        context["orientation_angle"] = selected_angle
                        context["orientation_method"] = orientation_method

                name = name_template.format(
                    source_name=source_name,
                    index=line_index,
                    global_index=global_index,
                    station=float(station),
                    station_int=int(round(float(station))),
                )
                coords = _line_coordinates_from_angle(
                    x,
                    y,
                    selected_angle,
                    total_length,
                )
                generated_lines.append(
                    {
                        "name": str(name),
                        "coordinates": coords,
                        "storage_area": storage_area,
                        "source_name": source_name,
                        "station": float(station),
                        "line_length": float(total_length),
                        "orientation": orientation_method,
                        "orientation_angle": float(selected_angle),
                        "tangent_angle": float(tangent_angle),
                        "center": (x, y),
                        "velocity_sample": velocity_sample,
                    }
                )
                global_index += 1

        if not generated_lines:
            raise ValueError("No reference lines were generated")

        logger.debug(
            f"Generated {len(generated_lines)} transverse reference line(s) "
            f"from {len(records)} longitudinal line(s)"
        )
        return generated_lines

    @staticmethod
    @log_call
    def add_reference_lines_from_longitudinal_line(
        geom_file: Union[str, Path],
        longitudinal_lines: Any,
        storage_area: str,
        spacing: float,
        line_length: float,
        **kwargs: Any,
    ) -> int:
        """
        Generate and insert transverse reference lines into a geometry file.

        This is a convenience wrapper around
        :meth:`generate_reference_lines_from_longitudinal_line` and
        :meth:`add_reference_lines`. Use the generator directly when manual
        review of the proposed coordinates is needed before writing.

        Args:
            geom_file: Path to geometry file (.g##).
            longitudinal_lines: Source line input accepted by
                ``generate_reference_lines_from_longitudinal_line``.
            storage_area: Name of the 2D flow area receiving the reference
                lines.
            spacing: Station interval along each source line.
            line_length: Generated transverse reference-line length.
            **kwargs: Additional generator options such as
                ``longitudinal_line_name``, ``orientation_plan_hdf``, and
                ``name_template``.

        Returns:
            int: Number of reference lines inserted.
        """
        generated_lines = (
            GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
                longitudinal_lines,
                spacing,
                line_length,
                storage_area=storage_area,
                **kwargs,
            )
        )
        return GeomReferenceFeatures.add_reference_lines(
            geom_file,
            generated_lines,
            storage_area,
        )

    @staticmethod
    def _sample_velocity_orientation(
        station_points: List[Any],
        *,
        orientation: str,
        orientation_plan_hdf: Optional[Union[str, Path]],
        orientation_time_index: Union[int, str],
        orientation_query_method: str,
        orientation_fallback: str,
        velocity_min: float,
        depth_min: float,
        ras_object: Optional[Any],
    ) -> List[dict]:
        """Sample optional velocity/depth orientation metadata for points."""
        empty_samples = [
            {
                "orientation_angle": None,
                "velocity_x": np.nan,
                "velocity_y": np.nan,
                "velocity": np.nan,
                "depth": np.nan,
                "mesh_name": None,
                "cell_id": None,
                "distance": np.nan,
            }
            for _ in station_points
        ]

        if orientation == "normal":
            return empty_samples

        coords = np.array([_point_xy(point) for point in station_points], dtype=float)
        try:
            from ..hdf.HdfResultsQuery import HdfResultsQuery

            vx_df = HdfResultsQuery.query_points(
                orientation_plan_hdf,
                coords,
                variable="velocity_x",
                time_index=orientation_time_index,
                method=orientation_query_method,
                ras_object=ras_object,
            )
            vy_df = HdfResultsQuery.query_points(
                orientation_plan_hdf,
                coords,
                variable="velocity_y",
                time_index=orientation_time_index,
                method=orientation_query_method,
                ras_object=ras_object,
            )
            depth_df = None
            if orientation == "depth_velocity":
                depth_df = HdfResultsQuery.query_points(
                    orientation_plan_hdf,
                    coords,
                    variable="depth",
                    time_index=orientation_time_index,
                    method=orientation_query_method,
                    ras_object=ras_object,
                )
        except Exception as exc:
            if orientation_fallback == "raise":
                raise
            logger.warning(
                "Velocity-based reference-line orientation unavailable; "
                f"falling back to line-normal orientation. Reason: {exc}"
            )
            return empty_samples

        samples = []
        for idx in range(len(station_points)):
            vx = float(vx_df.iloc[idx]["value"])
            vy = float(vy_df.iloc[idx]["value"])
            velocity = float(math.hypot(vx, vy))
            depth = (
                float(depth_df.iloc[idx]["value"])
                if depth_df is not None
                else np.nan
            )

            valid_velocity = np.isfinite(velocity) and velocity >= velocity_min
            valid_depth = (
                orientation != "depth_velocity"
                or (np.isfinite(depth) and depth >= depth_min)
            )
            if valid_velocity and valid_depth:
                orientation_angle = math.degrees(math.atan2(vy, vx)) + 90.0
            else:
                orientation_angle = None

            samples.append(
                {
                    "orientation_angle": orientation_angle,
                    "velocity_x": vx,
                    "velocity_y": vy,
                    "velocity": velocity,
                    "depth": depth,
                    "mesh_name": str(vx_df.iloc[idx]["mesh_name"]),
                    "cell_id": int(vx_df.iloc[idx]["cell_id"]),
                    "distance": float(vx_df.iloc[idx]["distance"]),
                }
            )

        return samples

    @staticmethod
    @log_call
    def add_reference_lines(
        geom_file: Union[str, Path],
        lines: List[dict],
        storage_area: str,
    ) -> int:
        """
        Insert reference lines into a plain text geometry file.

        Reference lines are inserted after BC Lines and before IC Points
        or LCMann sections. They persist through HEC-RAS recomputation
        because HEC-RAS reads them from the plain text file during
        geometry preprocessing.

        Args:
            geom_file: Path to geometry file (.g##)
            lines: List of dicts with:
                - 'name': str -- unique reference line name
                - 'coordinates': list of (x,y) tuples or array (N,2)
            storage_area: Name of the 2D flow area (e.g., 'BaldEagleCr')

        Returns:
            int: Number of reference lines inserted

        Example:
            >>> GeomReferenceFeatures.add_reference_lines(
            ...     "model.g01",
            ...     lines=[
            ...         {"name": "Gauge_01", "coordinates": [(1000, 2000), (1100, 2000)]},
            ...     ],
            ...     storage_area="MyMesh",
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not lines:
            raise ValueError("lines must contain at least one reference line")

        # Create backup
        backup_path = Path(str(geom_file) + ".bak")
        shutil.copy2(geom_file, backup_path)
        logger.info(f"Created backup: {backup_path.name}")

        # Read file with CRLF preservation
        with open(geom_file, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        # Build reference line blocks
        new_blocks = []
        for item in lines:
            name = str(item["name"]).strip()
            coords = np.asarray(item["coordinates"], dtype=np.float64)
            if coords.ndim != 2 or coords.shape[1] != 2 or len(coords) < 2:
                raise ValueError(
                    f"Reference line '{name}' needs at least 2 points as (N,2) array"
                )
            block = _build_reference_line_block(name, storage_area, coords)
            new_blocks.extend(block)

        # Find insertion point: after last BC Line block, before IC Points or LCMann
        insert_idx = len(file_lines)  # default: end of file

        last_bc_line_idx = -1
        first_ic_point_idx = -1
        first_lcmann_idx = -1
        first_existing_refline_idx = -1

        for i, line in enumerate(file_lines):
            stripped = line.rstrip("\r\n")
            if stripped.startswith("BC Line Text Position="):
                last_bc_line_idx = i
            if stripped.startswith("IC Point Name=") and first_ic_point_idx == -1:
                first_ic_point_idx = i
            if stripped.startswith("LCMann ") and first_lcmann_idx == -1:
                first_lcmann_idx = i
            if stripped.startswith("Reference Line Name=") and first_existing_refline_idx == -1:
                first_existing_refline_idx = i

        # Priority: insert at existing ref line location, or after BC lines,
        # or before IC points, or before LCMann
        if first_existing_refline_idx >= 0:
            insert_idx = first_existing_refline_idx
        elif last_bc_line_idx >= 0:
            insert_idx = last_bc_line_idx + 1
        elif first_ic_point_idx >= 0:
            insert_idx = first_ic_point_idx
        elif first_lcmann_idx >= 0:
            insert_idx = first_lcmann_idx

        # Detect line ending from file
        line_ending = "\r\n" if file_lines and "\r\n" in file_lines[0] else "\n"

        # Insert
        insert_lines = [block_line + line_ending for block_line in new_blocks]
        file_lines[insert_idx:insert_idx] = insert_lines

        # Write back
        with open(geom_file, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.debug(
            f"Inserted {len(lines)} reference line(s) into {geom_file.name} "
            f"(storage area: {storage_area}) at line {insert_idx + 1}"
        )
        return len(lines)

    @staticmethod
    @log_call
    def add_reference_points(
        geom_file: Union[str, Path],
        points: List[dict],
    ) -> int:
        """
        Insert reference points into a plain text geometry file.

        Reference points are stored as IC Points with names starting with
        "Reference Point". They are inserted in the IC Point section.

        Args:
            geom_file: Path to geometry file (.g##)
            points: List of dicts with:
                - 'name': str -- unique name (will be prefixed with
                  "Reference Point " if not already)
                - 'x': float -- X coordinate
                - 'y': float -- Y coordinate

        Returns:
            int: Number of reference points inserted

        Example:
            >>> GeomReferenceFeatures.add_reference_points(
            ...     "model.g01",
            ...     points=[
            ...         {"name": "Gauge_01", "x": 1685000, "y": 145000},
            ...     ],
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not points:
            raise ValueError("points must contain at least one reference point")

        # Create backup
        backup_path = Path(str(geom_file) + ".bak")
        if not backup_path.exists():
            shutil.copy2(geom_file, backup_path)
            logger.info(f"Created backup: {backup_path.name}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        # Build IC Point blocks
        new_blocks = []
        for item in points:
            name = str(item["name"]).strip()
            if not name.startswith("Reference Point"):
                name = f"Reference Point {name}"
            x = float(item["x"])
            y = float(item["y"])
            block = _build_ic_point_block(name, x, y)
            new_blocks.extend(block)

        # Find insertion point: at existing IC Points or before LCMann
        insert_idx = len(file_lines)
        first_ic_point_idx = -1
        first_lcmann_idx = -1

        for i, line in enumerate(file_lines):
            stripped = line.rstrip("\r\n")
            if stripped.startswith("IC Point Name=") and first_ic_point_idx == -1:
                first_ic_point_idx = i
            if stripped.startswith("LCMann ") and first_lcmann_idx == -1:
                first_lcmann_idx = i

        if first_ic_point_idx >= 0:
            insert_idx = first_ic_point_idx
        elif first_lcmann_idx >= 0:
            insert_idx = first_lcmann_idx

        line_ending = "\r\n" if file_lines and "\r\n" in file_lines[0] else "\n"
        insert_lines = [block_line + line_ending for block_line in new_blocks]
        file_lines[insert_idx:insert_idx] = insert_lines

        with open(geom_file, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.debug(
            f"Inserted {len(points)} reference point(s) into {geom_file.name} "
            f"at line {insert_idx + 1}"
        )
        return len(points)

    @staticmethod
    @log_call
    def get_reference_lines(
        geom_file: Union[str, Path],
    ) -> List[dict]:
        """
        Read reference lines from a plain text geometry file.

        Returns:
            List of dicts with 'name', 'storage_area', 'coordinates' keys.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore") as f:
            file_lines = f.readlines()

        results = []
        i = 0
        while i < len(file_lines):
            line = file_lines[i].rstrip("\r\n")
            if line.startswith("Reference Line Name="):
                name = line.split("=", 1)[1].strip()
                storage_area = ""
                n_pts = 0

                # Read subsequent keywords
                j = i + 1
                while j < len(file_lines):
                    sub = file_lines[j].rstrip("\r\n")
                    if sub.startswith("Reference Line Storage Area="):
                        storage_area = sub.split("=", 1)[1].strip()
                    elif sub.startswith("Reference Line Arc="):
                        n_pts = int(sub.split("=", 1)[1].strip())
                        break
                    j += 1

                # Read coordinate block
                coords = []
                k = j + 1
                while len(coords) < n_pts and k < len(file_lines):
                    coord_line = file_lines[k].rstrip("\r\n")
                    if coord_line.startswith("Reference Line"):
                        break
                    # Parse 16-char fixed-width fields
                    vals = []
                    for start in range(0, len(coord_line), 16):
                        chunk = coord_line[start : start + 16].strip()
                        if chunk:
                            try:
                                vals.append(float(chunk))
                            except ValueError:
                                break
                    for vi in range(0, len(vals) - 1, 2):
                        coords.append((vals[vi], vals[vi + 1]))
                    k += 1

                results.append({
                    "name": name,
                    "storage_area": storage_area,
                    "coordinates": coords,
                })
                i = k
            else:
                i += 1

        return results

    @staticmethod
    @log_call
    def get_reference_points(
        geom_file: Union[str, Path],
    ) -> List[dict]:
        """
        Read reference points (IC Points with "Reference Point" names)
        from a plain text geometry file.

        Returns:
            List of dicts with 'name', 'x', 'y' keys.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore") as f:
            file_lines = f.readlines()

        results = []
        i = 0
        while i < len(file_lines):
            line = file_lines[i].rstrip("\r\n")
            if line.startswith("IC Point Name=") and "Reference Point" in line:
                name = line.split("=", 1)[1].strip()
                if i + 1 < len(file_lines):
                    pos_line = file_lines[i + 1].rstrip("\r\n")
                    if pos_line.startswith("IC Point Position="):
                        xy = pos_line.split("=", 1)[1]
                        parts = xy.split(",")
                        if len(parts) >= 2:
                            results.append({
                                "name": name,
                                "x": float(parts[0]),
                                "y": float(parts[1]),
                            })
                i += 2
            else:
                i += 1

        return results
