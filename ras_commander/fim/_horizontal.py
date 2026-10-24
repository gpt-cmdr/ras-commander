"""Cell-constant WSE on a reusable terrain-lattice ownership grid.

This is an explicit alternative to the ras2fim triangulated recipe. The
definition follows horizontal cell filling; no reconstructed vendor code is
used. Terrain and cell ownership are prepared once per mapping call.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import _aoi, _prepare
from .errors import FimUnsupportedError


@dataclass(frozen=True)
class GridPlan:
    window: Any
    transform: Any
    crs: Any
    geometry: Any
    mask_geometry: bool
    planned_bytes: int
    cell_positions: np.ndarray

    @property
    def shape(self):
        return int(self.window.height), int(self.window.width)


@dataclass(frozen=True)
class HorizontalGrid:
    plan: GridPlan
    owner: np.ndarray
    ground: np.ndarray


def plan_grid(cells, terrain_path: Path, aoi, max_working_mib: int) -> GridPlan:
    """Inspect metadata and admit the window before allocating raster arrays."""
    import rasterio
    import shapely
    from rasterio.windows import Window

    if len(cells) >= np.iinfo(np.int32).max:
        raise FimUnsupportedError("horizontal mapping has too many cells for int32 ownership")
    bounds = cells.total_bounds
    if not np.isfinite(bounds).all():
        raise FimUnsupportedError("horizontal cell coordinates must be finite")
    with rasterio.open(terrain_path) as src:
        t = src.transform
        if src.count != 1 or src.dtypes[0] != "float32":
            raise FimUnsupportedError("horizontal mapping requires single-band float32 terrain")
        if src.nodata is None:
            raise FimUnsupportedError("horizontal terrain must declare its nodata value")
        if t.b or t.d or t.a <= 0 or t.e >= 0 or not np.isclose(t.a, -t.e, rtol=1e-12, atol=0):
            raise FimUnsupportedError("horizontal mapping requires north-up square terrain pixels")
        if src.crs is None or not _prepare.same_crs(cells.crs, src.crs):
            raise FimUnsupportedError("horizontal cells and terrain must share a CRS")
        crs = _aoi.to_crs(src.crs)
        shape = _aoi.geometry_in_crs(aoi, crs) if aoi else None
        if shape is not None:
            ab = shape.bounds
            bounds = (max(bounds[0], ab[0]), max(bounds[1], ab[1]),
                      min(bounds[2], ab[2]), min(bounds[3], ab[3]))
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            c0 = c1 = r0 = r1 = 0
        else:
            c0, c1 = _aoi.center_index_range(bounds[0], bounds[2], t.c, t.a, src.width)
            r0, r1 = _aoi.center_index_range(bounds[1], bounds[3], t.f, t.e, src.height)
        window = Window(c0, r0, max(0, c1-c0), max(0, r1-r0))
        transform = src.window_transform(window)
        positions = np.array([], dtype=np.int64)
        if window.width and window.height:
            from rasterio.windows import bounds as window_bounds
            positions = np.sort(cells.sindex.query(shapely.box(*window_bounds(window, t)), predicate="intersects"))
            if not len(positions):
                window = Window(c0, r0, 0, 0)
    # Ownership, ground, temporary rasterization buffers, float32 WSE/depth
    # arithmetic, float32 products and masks. Raster-library caches and
    # polygonization are not a hard process-RSS limit.
    pixels = int(window.width * window.height)
    planned = pixels * 32 + len(positions) * 64 + (64 << 20) if pixels else 0
    if planned > max_working_mib * (1 << 20):
        raise FimUnsupportedError(
            f"horizontal window planned {planned} bytes exceeds max_working_mib={max_working_mib}; "
            "use a smaller bbox or polygon")
    positions.setflags(write=False)
    return GridPlan(window, transform, crs, shape,
                    aoi is not None and (aoi.kind != "bbox" or not _prepare.same_crs(aoi.crs, crs)),
                    planned, positions)


def prepare_grid(cells, terrain_path: Path, plan: GridPlan) -> HorizontalGrid:
    """Cache terrain and centre-based cell ownership for one admitted window."""
    import rasterio
    from rasterio.features import geometry_mask, rasterize

    if not all(plan.shape):
        return HorizontalGrid(plan, np.zeros(plan.shape, dtype=np.int32),
                              np.zeros(plan.shape, dtype=np.float32))
    cells = cells.iloc[plan.cell_positions]
    import shapely
    geometries = cells.geometry.to_numpy()
    if (not np.isin(shapely.get_type_id(geometries), [3]).all()
            or shapely.is_empty(geometries).any() or not shapely.is_valid(geometries).all()):
        raise FimUnsupportedError("horizontal mapping requires valid, non-empty cell Polygons")
    # Reject positive-area overlaps: choosing a cell silently would replace
    # one hydraulic value with another. Shared edges are permitted.
    # Query one cell at a time: coincident geometries must not allocate an
    # N-by-N candidate-pair array before the first overlap is rejected.
    index = cells.sindex
    for i, geometry in enumerate(geometries):
        others = index.query(geometry, predicate="intersects")
        others = others[others > i]
        for start in range(0, len(others), 512):
            intersections = shapely.intersection(geometry, geometries[others[start:start+512]])
            if (shapely.area(intersections) > 0).any():
                raise FimUnsupportedError("horizontal cells have overlapping interiors")
    with rasterio.Env(GDAL_CACHEMAX=64 << 20), rasterio.open(terrain_path) as src:
        ground = src.read(1, window=plan.window, masked=True).filled(np.nan)
        if np.isinf(ground).any():
            raise FimUnsupportedError("horizontal terrain contains unmasked infinite values")
        owner = rasterize(((g, i+1) for i, g in enumerate(cells.geometry)),
                          out_shape=plan.shape, transform=plan.transform,
                          fill=0, dtype="int32", all_touched=False)
    if plan.mask_geometry:
        keep = geometry_mask([plan.geometry], out_shape=plan.shape,
                             transform=plan.transform, invert=True, all_touched=False)
        owner[~keep] = 0
    owner.setflags(write=False)
    ground.setflags(write=False)
    return HorizontalGrid(plan, owner, ground)


def render(grid: HorizontalGrid, values: np.ndarray, min_depth: float):
    """Gather each owning cell's WSE and filter both products by pixel depth."""
    if np.isinf(values).any() or (np.abs(values[np.isfinite(values)]) > np.finfo(np.float32).max).any():
        raise FimUnsupportedError("horizontal WSE values must be finite float32-range values or NaN")
    table = np.concatenate((np.array([np.nan], dtype=np.float32), values.astype(np.float32)))
    wse = table[grid.owner]
    with np.errstate(over="raise", invalid="ignore"):
        depth = wse - grid.ground
    keep = np.isfinite(grid.ground) & np.isfinite(depth) & (depth > min_depth)
    depth[~keep] = np.nan
    wse[~keep] = np.nan
    return depth, wse
