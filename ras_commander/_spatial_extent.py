"""Shared normalization for authoritative spatial extent inputs.

The helpers in this module keep polygon validation and multipart behavior
consistent before raster, terrain, and precipitation workflows reduce an
authoritative area of interest to lower-level bounds.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, Optional


def _coerce_buffer_distance(buffer_distance: float, parameter_name: str) -> float:
    """Return a finite buffer distance in the input extent's CRS units."""
    try:
        distance = float(buffer_distance)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"buffer_distance for {parameter_name} must be a finite number"
        ) from exc

    if not math.isfinite(distance):
        raise ValueError(
            f"buffer_distance for {parameter_name} must be a finite number"
        )
    return distance


def _extract_bounds(
    extent: Any,
    parameter_name: str,
) -> Optional[tuple[float, float, float, float]]:
    """Extract a legacy bounds-shaped input without treating geometry as bounds."""
    values: Optional[Iterable[Any]] = None

    if isinstance(extent, Mapping):
        normalized = {
            str(key).lower(): value
            for key, value in extent.items()
        }
        for keys in (
            ("left", "bottom", "right", "top"),
            ("xmin", "ymin", "xmax", "ymax"),
            ("minx", "miny", "maxx", "maxy"),
        ):
            if all(key in normalized for key in keys):
                values = (normalized[key] for key in keys)
                break
    elif isinstance(extent, (list, tuple)):
        if len(extent) == 4:
            values = extent
    else:
        for attributes in (
            ("left", "bottom", "right", "top"),
            ("xmin", "ymin", "xmax", "ymax"),
            ("minx", "miny", "maxx", "maxy"),
            ("MinX", "MinY", "MaxX", "MaxY"),
        ):
            if all(hasattr(extent, attribute) for attribute in attributes):
                values = (getattr(extent, attribute) for attribute in attributes)
                break

    if values is None:
        return None

    try:
        bounds = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{parameter_name} bounds must contain four finite numeric values"
        ) from exc

    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ValueError(
            f"{parameter_name} bounds must contain four finite numeric values"
        )

    left, bottom, right, top = bounds
    if left >= right or bottom >= top:
        raise ValueError(
            f"{parameter_name} bounds must satisfy minx < maxx and miny < maxy; "
            f"got {bounds}"
        )
    return bounds


def _geopandas_geometry_values(extent: Any) -> Optional[list[Any]]:
    """Return geometries from a GeoSeries/GeoDataFrame without a hard dependency."""
    try:
        import geopandas as gpd
    except ImportError:  # pragma: no cover - geopandas is an optional runtime extra
        return None

    if isinstance(extent, gpd.GeoDataFrame):
        return list(extent.geometry)
    if isinstance(extent, gpd.GeoSeries):
        return list(extent)
    return None


def _single_polygon(
    geometry_values: Iterable[Any],
    parameter_name: str,
) -> Any:
    """Validate and collapse geometry input to exactly one non-empty Polygon."""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.validation import explain_validity

    polygon_parts: list[Any] = []
    saw_geometry = False

    for geometry in geometry_values:
        if geometry is None:
            continue
        saw_geometry = True
        if geometry.is_empty:
            continue
        if not geometry.is_valid:
            raise ValueError(
                f"{parameter_name} geometry is invalid: "
                f"{explain_validity(geometry)}"
            )
        if isinstance(geometry, Polygon):
            polygon_parts.append(geometry)
            continue
        if isinstance(geometry, MultiPolygon):
            polygon_parts.extend(part for part in geometry.geoms if not part.is_empty)
            continue
        raise ValueError(
            f"{parameter_name} must be a Polygon or a single-effective-part "
            f"MultiPolygon; got {geometry.geom_type}"
        )

    if not polygon_parts:
        detail = "contains no geometry" if not saw_geometry else "is empty"
        raise ValueError(
            f"{parameter_name} geometry {detail}; expected one non-empty Polygon"
        )
    if len(polygon_parts) != 1:
        raise ValueError(
            f"{parameter_name} geometry is ambiguous: expected exactly one "
            f"non-empty polygonal part, found {len(polygon_parts)}"
        )
    return polygon_parts[0]


def _normalize_extent_geometry(
    extent: Any,
    *,
    buffer_distance: float = 0.0,
    parameter_name: str = "extent",
) -> Any:
    """Normalize an extent input to one valid Shapely ``Polygon``.

    Accepted inputs are a Shapely ``Polygon``, a single-effective-part
    ``MultiPolygon``, a one-effective-geometry GeoSeries/GeoDataFrame, legacy
    four-value bounds, bounds dictionaries/objects, and RasMapper-style
    ``Extent`` objects exposing ``MinX``, ``MinY``, ``MaxX``, and ``MaxY``.
    """
    from shapely.geometry import box
    from shapely.geometry.base import BaseGeometry

    distance = _coerce_buffer_distance(buffer_distance, parameter_name)

    if isinstance(extent, BaseGeometry):
        polygon = _single_polygon([extent], parameter_name)
    else:
        bounds = _extract_bounds(extent, parameter_name)
        if bounds is not None:
            polygon = box(*bounds)
        else:
            geometry_values = _geopandas_geometry_values(extent)
            if geometry_values is None:
                raise ValueError(
                    f"{parameter_name} must be a Polygon, a single-effective-part "
                    "MultiPolygon, a one-effective-geometry GeoSeries/GeoDataFrame, "
                    "a 4-tuple/list, a bounds dict/object, or a RasMapperLib.Extent"
                )
            polygon = _single_polygon(geometry_values, parameter_name)

    if distance == 0.0:
        return polygon

    buffered = polygon.buffer(distance)
    try:
        return _single_polygon([buffered], parameter_name)
    except ValueError as exc:
        raise ValueError(
            f"buffer_distance={distance} produced an unusable {parameter_name} "
            f"geometry: {exc}"
        ) from exc


def _normalize_extent_bounds(
    extent: Any,
    *,
    buffer_distance: float = 0.0,
    extent_cls: Any = None,
    parameter_name: str = "extent",
) -> Any:
    """Normalize an authoritative extent to bounds or a requested Extent class."""
    polygon = _normalize_extent_geometry(
        extent,
        buffer_distance=buffer_distance,
        parameter_name=parameter_name,
    )
    bounds = tuple(float(value) for value in polygon.bounds)
    if extent_cls is None:
        return bounds
    return extent_cls(*bounds)
