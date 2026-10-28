"""Area-of-interest (AOI) selection on the final FIM output grid.

An AOI selects output pixels on the final (snapped) output grid. It never
changes sample preparation, triangulation, interpolation axes, the wet mask,
terrain sampling, the output grid origin, or the reprojection, so an AOI
product equals the crop of the full-grid product.

Portions adapted from ras2fim-2D (``src/mapping_aoi.py``), Copyright (c) 2026,
The University of Texas at Austin, BSD 3-Clause License. See
``ras_commander/fim/THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union

import numpy as np

from .errors import FimAoiError

AOI_STATUS_OK = "ok"
AOI_STATUS_EMPTY = "empty_aoi"

# Each AOI edge is densified to this many segments of its extent before an
# AOI in another CRS is reprojected into the output-grid CRS.
DENSIFY_SEGMENTS = 1000


@dataclass(frozen=True)
class FimAoi:
    """A validated bounding-box or polygon area of interest.

    Attributes:
        kind: ``"bbox"`` or ``"polygon"``.
        geometry: Shapely box, Polygon, or MultiPolygon in ``crs``. Holes and
            multiple parts are kept.
        crs: :class:`pyproj.CRS` of ``geometry``.
        source: Human-readable origin, recorded in the product manifest.
    """

    kind: str
    geometry: Any
    crs: Any
    source: str

    def describe(self) -> dict:
        """Return a JSON-serializable summary."""
        return {
            "kind": self.kind,
            "source": self.source,
            "crs": self.crs.to_string(),
            "bounds": [float(v) for v in self.geometry.bounds],
        }


@dataclass(frozen=True)
class FimAoiWindow:
    """AOI pixels on one north-up output grid.

    ``mask`` is ``None`` for a bounding box in the grid CRS. Otherwise it is a
    boolean ``(height, width)`` array where True keeps the pixel.
    """

    status: str
    col_off: int
    row_off: int
    width: int
    height: int
    transform: Any
    mask: Optional[np.ndarray] = field(default=None, compare=False)

    @property
    def is_empty(self) -> bool:
        return self.status == AOI_STATUS_EMPTY

    @property
    def window(self) -> list:
        return [self.col_off, self.row_off, self.width, self.height]


def to_crs(value, what: str = "aoi_crs"):
    """Return a :class:`pyproj.CRS`, or None for None."""
    if value is None:
        return None
    from pyproj import CRS

    if isinstance(value, CRS):
        return value
    try:
        return CRS.from_user_input(value)
    except Exception as exc:  # pyproj raises CRSError and others
        raise FimAoiError(f"{what}: unrecognized CRS {value!r}: {exc}") from exc


def parse_bbox(values) -> Tuple[float, float, float, float]:
    """Validate ``(xmin, ymin, xmax, ymax)`` and return floats."""
    if isinstance(values, str):
        values = [v for v in values.replace(",", " ").split() if v]
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise FimAoiError(f"bbox must be four numbers (xmin, ymin, xmax, ymax): {exc}") from exc
    if len(values) != 4:
        raise FimAoiError(f"bbox must have four values (xmin, ymin, xmax, ymax), got {len(values)}")
    if not all(math.isfinite(v) for v in values):
        raise FimAoiError(f"bbox values must be finite, got {values}")
    xmin, ymin, xmax, ymax = values
    if not (xmin < xmax and ymin < ymax):
        raise FimAoiError(f"bbox must satisfy xmin < xmax and ymin < ymax, got {values}")
    return xmin, ymin, xmax, ymax


def validate_polygon(geom, source: str):
    """Return a valid, non-empty Polygon or MultiPolygon, or raise."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.validation import explain_validity

    if geom is None:
        raise FimAoiError(f"{source}: polygon geometry is missing")
    if not isinstance(geom, (Polygon, MultiPolygon)):
        raise FimAoiError(f"{source}: polygon AOI must be a Polygon or MultiPolygon, got {geom.geom_type}")
    if geom.is_empty:
        raise FimAoiError(f"{source}: polygon geometry is empty")
    if not np.all(np.isfinite(shapely.get_coordinates(geom))):
        raise FimAoiError(f"{source}: polygon has non-finite coordinates")
    if not geom.is_valid:
        raise FimAoiError(f"{source}: polygon geometry is invalid ({explain_validity(geom)})")
    return geom


def _polygon_from_frame(gdf, source: str, aoi_crs):
    import shapely

    if len(gdf) == 0:
        raise FimAoiError(f"{source}: no features")
    crs_arg = to_crs(aoi_crs)
    crs_frame = to_crs(gdf.crs, f"{source} CRS") if gdf.crs is not None else None
    if crs_frame is None and crs_arg is None:
        raise FimAoiError(f"{source}: no CRS; pass aoi_crs")
    if crs_frame is not None and crs_arg is not None and crs_frame != crs_arg:
        raise FimAoiError(
            f"{source}: CRS {crs_frame.to_string()} conflicts with aoi_crs {crs_arg.to_string()}"
        )
    for index, geom in enumerate(gdf.geometry):
        validate_polygon(geom, f"{source} feature {index}")
    union = shapely.union_all(np.asarray(gdf.geometry.values))
    union = validate_polygon(union, f"{source} (union of features)")
    return FimAoi("polygon", union, crs_frame if crs_frame is not None else crs_arg, source)


def _polygon_from_file(path: Union[str, Path], layer: Optional[str], aoi_crs):
    import geopandas as gpd

    path = Path(os.fspath(path))
    if not path.is_file():
        raise FimAoiError(f"polygon AOI file not found: {path}")
    try:
        layers = list(gpd.list_layers(path)["name"])
    except Exception as exc:
        raise FimAoiError(f"cannot read polygon AOI file {path}: {exc}") from exc
    if layer is None:
        if len(layers) != 1:
            raise FimAoiError(f"{path.name} has {len(layers)} layers {layers}; choose one with polygon_layer")
    elif layer not in layers:
        raise FimAoiError(f"layer {layer!r} not in {path.name} (layers: {layers})")
    gdf = gpd.read_file(path, layer=layer)
    source = path.name + (f" layer {layer}" if layer else "")
    return _polygon_from_frame(gdf, source, aoi_crs)


def resolve_aoi(bbox=None, polygon=None, polygon_layer=None, aoi_crs=None, default_crs=None) -> Optional[FimAoi]:
    """Build an AOI from user options, or return None when none is requested."""
    from shapely.geometry.base import BaseGeometry

    has_bbox = bbox is not None
    has_polygon = polygon is not None
    if has_bbox and has_polygon:
        raise FimAoiError("bbox and polygon are mutually exclusive")
    if polygon_layer is not None and not has_polygon:
        raise FimAoiError("polygon_layer was given without polygon")
    if not has_bbox and not has_polygon:
        if aoi_crs is not None:
            raise FimAoiError("aoi_crs was given without bbox or polygon")
        return None
    if has_bbox:
        if isinstance(bbox, FimAoi):
            raise FimAoiError("pass a FimAoi through the aoi argument, not bbox")
        from shapely.geometry import box

        values = parse_bbox(bbox)
        crs = to_crs(aoi_crs if aoi_crs is not None else default_crs)
        if crs is None:
            raise FimAoiError("bbox needs aoi_crs (no default output CRS is available)")
        return FimAoi("bbox", box(*values), crs, f"bbox {list(values)}")
    if isinstance(polygon, BaseGeometry):
        if polygon_layer is not None:
            raise FimAoiError("polygon_layer applies only to a polygon file")
        crs = to_crs(aoi_crs)
        if crs is None:
            raise FimAoiError("a Shapely polygon has no CRS; pass aoi_crs")
        geom = validate_polygon(polygon, "polygon AOI")
        return FimAoi("polygon", geom, crs, f"shapely {geom.geom_type}")
    if hasattr(polygon, "geometry") and hasattr(polygon, "crs"):
        if polygon_layer is not None:
            raise FimAoiError("polygon_layer applies only to a polygon file")
        return _polygon_from_frame(polygon, "polygon GeoDataFrame", aoi_crs)
    if isinstance(polygon, (str, os.PathLike)):
        return _polygon_from_file(polygon, polygon_layer, aoi_crs)
    raise FimAoiError(
        "polygon must be a file path, a Shapely Polygon/MultiPolygon, or a GeoDataFrame; "
        f"got {type(polygon).__name__}"
    )


def geometry_in_crs(aoi: FimAoi, crs_grid):
    """Return the AOI geometry in ``crs_grid`` (edges densified before reprojection)."""
    import shapely
    from pyproj import Transformer

    crs_grid = to_crs(crs_grid, "grid CRS")
    if aoi.crs == crs_grid:
        return aoi.geometry
    xmin, ymin, xmax, ymax = aoi.geometry.bounds
    step = max(xmax - xmin, ymax - ymin) / DENSIFY_SEGMENTS
    geom = shapely.segmentize(aoi.geometry, step) if step > 0 else aoi.geometry
    transformer = Transformer.from_crs(aoi.crs, crs_grid, always_xy=True)

    def _xy(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    out = shapely.transform(geom, _xy)
    if not np.all(np.isfinite(shapely.get_coordinates(out))):
        raise FimAoiError(
            f"AOI cannot be transformed from {aoi.crs.to_string()} to {crs_grid.to_string()}"
        )
    return validate_polygon(out, f"AOI reprojected to {crs_grid.to_string()}")


def center_index_range(lo: float, hi: float, origin: float, step: float, count: int) -> Tuple[int, int]:
    """Return ``(start, stop)`` of indices whose centre ``origin + (i + 0.5) * step`` is in ``[lo, hi)``.

    ``step`` may be negative. ``stop`` is exclusive; ``start == stop`` when empty.
    """

    def inside(i):
        c = origin + (i + 0.5) * step
        return lo <= c < hi

    a = (lo - origin) / step - 0.5
    b = (hi - origin) / step - 0.5
    i_lo = max(0, min(count, int(math.floor(min(a, b))) - 1))
    i_hi = max(0, min(count, int(math.ceil(max(a, b))) + 2))
    start = next((i for i in range(i_lo, min(i_lo + 4, i_hi)) if inside(i)), None)
    if start is None:
        return 0, 0
    last = next(i for i in range(i_hi - 1, start - 1, -1) if inside(i))
    return start, last + 1


def aoi_window(aoi: FimAoi, transform, width: int, height: int, crs_grid) -> FimAoiWindow:
    """Select AOI pixels on a north-up grid.

    The window holds the pixels whose centre lies in ``[xmin, xmax) x
    [ymin, ymax)`` of the AOI bounds in the grid CRS. A bbox already in the
    grid CRS is exactly that window. Any other AOI (a polygon, or a bbox in
    another CRS, reprojected as a densified polygon) also masks window pixels
    whose centre is outside the polygon (``all_touched=False``); holes are
    excluded.
    """
    from affine import Affine

    transform = Affine(*list(transform)[:6])
    if not (transform.b == 0 and transform.d == 0 and transform.a > 0 and transform.e < 0):
        raise FimAoiError(f"AOI selection needs a north-up output grid, got {tuple(transform)[:6]}")
    crs_grid = to_crs(crs_grid, "grid CRS")
    rectangular = aoi.kind == "bbox" and aoi.crs == crs_grid
    geom = aoi.geometry if rectangular else geometry_in_crs(aoi, crs_grid)

    xmin, ymin, xmax, ymax = geom.bounds
    col0, col1 = center_index_range(xmin, xmax, transform.c, transform.a, width)
    row0, row1 = center_index_range(ymin, ymax, transform.f, transform.e, height)
    w, h = col1 - col0, row1 - row0
    win_transform = transform @ Affine.translation(col0, row0)
    if w <= 0 or h <= 0:
        return FimAoiWindow(AOI_STATUS_EMPTY, col0, row0, max(w, 0), max(h, 0), win_transform)
    if rectangular:
        return FimAoiWindow(AOI_STATUS_OK, col0, row0, w, h, win_transform)

    from rasterio.features import geometry_mask

    keep = geometry_mask([geom], out_shape=(h, w), transform=win_transform, all_touched=False, invert=True)
    if not keep.any():
        return FimAoiWindow(AOI_STATUS_EMPTY, col0, row0, w, h, win_transform)
    return FimAoiWindow(AOI_STATUS_OK, col0, row0, w, h, win_transform, keep)
