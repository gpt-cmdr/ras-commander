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
    geometry_bytes: int = 0
    source_transform: Any = None

    @property
    def shape(self):
        return int(self.window.height), int(self.window.width)


@dataclass(frozen=True)
class HorizontalGrid:
    plan: GridPlan
    owner: np.ndarray | None
    ground: np.ndarray


def plan_grid(
    cells, terrain_path: Path, aoi, max_working_mib: int, native: bool = False
) -> GridPlan:
    """Inspect metadata and admit the window before allocating raster arrays."""
    import rasterio
    import shapely
    from rasterio.windows import Window

    if len(cells) >= np.iinfo(np.int32).max:
        raise FimUnsupportedError(
            "horizontal mapping has too many cells for int32 ownership"
        )
    bounds = cells.total_bounds
    if not np.isfinite(bounds).all():
        raise FimUnsupportedError("horizontal cell coordinates must be finite")
    with rasterio.open(terrain_path) as src:
        t = src.transform
        transient = 0
        if native:
            bh, bw = src.block_shapes[0]
            block_bytes = bh * bw * 4
            if block_bytes > 64 << 20:
                raise FimUnsupportedError(
                    "horizontal terrain block exceeds 64 MiB; export tiled terrain"
                )
            transient = (
                block_bytes * 4
                + ((src.width + bw - 1) // bw) * ((src.height + bh - 1) // bh) * 16
            )
        if src.count != 1 or src.dtypes[0] != "float32":
            raise FimUnsupportedError(
                "horizontal mapping requires single-band float32 terrain"
            )
        from rasterio.enums import MaskFlags

        if any(
            MaskFlags.per_dataset in flags or MaskFlags.alpha in flags
            for flags in src.mask_flag_enums
        ):
            raise FimUnsupportedError(
                "horizontal terrain with a dataset/alpha mask is unsupported; export nodata-tagged terrain"
            )
        if src.nodata is None:
            raise FimUnsupportedError(
                "horizontal terrain must declare its nodata value"
            )
        if (
            t.b
            or t.d
            or t.a <= 0
            or t.e >= 0
            or not np.isclose(t.a, -t.e, rtol=1e-12, atol=0)
        ):
            raise FimUnsupportedError(
                "horizontal mapping requires north-up square terrain pixels"
            )
        if src.crs is None or not _prepare.same_crs(cells.crs, src.crs):
            raise FimUnsupportedError("horizontal cells and terrain must share a CRS")
        crs = _aoi.to_crs(src.crs)
        # Preserve the unbounded output extent; an AOI may only remove pixels.
        fc0, fc1 = _aoi.center_index_range(bounds[0], bounds[2], t.c, t.a, src.width)
        fr0, fr1 = _aoi.center_index_range(bounds[1], bounds[3], t.f, t.e, src.height)
        shape = _aoi.geometry_in_crs(aoi, crs) if aoi else None
        if shape is not None:
            ab = shape.bounds
            bounds = (
                max(bounds[0], ab[0]),
                max(bounds[1], ab[1]),
                min(bounds[2], ab[2]),
                min(bounds[3], ab[3]),
            )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            c0 = c1 = r0 = r1 = 0
        elif shape is None:
            c0, c1, r0, r1 = fc0, fc1, fr0, fr1
        else:
            from ._aoi_lattice import index_range
            c0, c1 = index_range(bounds[0], bounds[2], t.c, t.a, src.width)
            r0, r1 = index_range(bounds[1], bounds[3], t.f, t.e, src.height)
            c0, c1 = max(c0, fc0), min(c1, fc1)
            r0, r1 = max(r0, fr0), min(r1, fr1)
        window = Window(c0, r0, max(0, c1 - c0), max(0, r1 - r0))
        transform = src.window_transform(window)
        positions = np.array([], dtype=np.int64)
        if window.width and window.height:
            from rasterio.windows import bounds as window_bounds

            positions = np.sort(
                cells.sindex.query(
                    shapely.box(*window_bounds(window, t)), predicate="intersects"
                )
            )
            if not len(positions):
                window = Window(c0, r0, 0, 0)
    # Ownership, ground, temporary rasterization buffers, float32 WSE/depth
    # arithmetic, float32 products and masks. Raster-library caches and
    # polygonization are not a hard process-RSS limit.
    pixels = int(window.width * window.height)
    planned = (
        pixels * 40 + len(positions) * 64 + (64 << 20) + transient if pixels else 0
    )
    transport = 0
    if native and pixels:
        # Bound framed 2D WKB plus decoded geometry/terrio shape storage before allocation.
        geoms = cells.geometry.iloc[positions].to_numpy()
        transport = (
            int(shapely.get_num_coordinates(geoms).sum()) * 16 + len(geoms) * 128
        )
        transport += int(shapely.get_num_interior_rings(geoms).sum()) * 4
        if shape is not None:
            parts = shapely.get_parts(shape)
            transport += (
                int(shapely.get_num_coordinates(parts).sum()) * 16 + len(parts) * 128
            )
            transport += int(shapely.get_num_interior_rings(parts).sum()) * 4
        planned += transport * 12
    if planned > max_working_mib * (1 << 20):
        raise FimUnsupportedError(
            f"horizontal window planned {planned} bytes exceeds max_working_mib={max_working_mib}; "
            "use a smaller bbox or polygon"
        )
    positions.setflags(write=False)
    return GridPlan(
        window,
        transform,
        crs,
        shape,
        aoi is not None and (aoi.kind != "bbox" or not _prepare.same_crs(aoi.crs, crs)),
        planned,
        positions,
        transport,
        t,
    )


def prepare_grid(
    cells, terrain_path: Path, plan: GridPlan, read_terrain: bool = True
) -> HorizontalGrid:
    """Cache terrain and centre-based cell ownership for one admitted window."""
    import rasterio
    from rasterio.features import rasterize

    if not all(plan.shape):
        return HorizontalGrid(
            plan,
            np.zeros(plan.shape, dtype=np.int32),
            np.zeros(plan.shape, dtype=np.float32),
        )
    cells = cells.iloc[plan.cell_positions]
    import shapely

    geometries = cells.geometry.to_numpy()
    if (
        not np.isin(shapely.get_type_id(geometries), [3]).all()
        or shapely.is_empty(geometries).any()
        or not shapely.is_valid(geometries).all()
    ):
        raise FimUnsupportedError(
            "horizontal mapping requires valid, non-empty cell Polygons"
        )
    # Reject positive-area overlaps: choosing a cell silently would replace
    # one hydraulic value with another. Shared edges are permitted.
    # Query one cell at a time: coincident geometries must not allocate an
    # N-by-N candidate-pair array before the first overlap is rejected.
    index = cells.sindex
    capacity = 4096
    left = np.empty(capacity, dtype=np.intp)
    right = np.empty(capacity, dtype=np.intp)
    used = 0

    def check_pairs(count):
        first = geometries[left[:count]]
        second = geometries[right[:count]]
        interiors = shapely.relate_pattern(first, second, "T********")
        if interiors.any():
            intersections = shapely.intersection(first[interiors], second[interiors])
            if (shapely.area(intersections) > 0).any():
                raise FimUnsupportedError("horizontal cells have overlapping interiors")

    for i, geometry in enumerate(geometries):
        others = index.query(geometry)
        others = others[others > i]
        start = 0
        while start < len(others):
            count = min(capacity - used, len(others) - start)
            left[used : used + count] = i
            right[used : used + count] = others[start : start + count]
            used += count
            start += count
            if used == capacity:
                check_pairs(used)
                used = 0
    if used:
        check_pairs(used)
    if not read_terrain:
        # Rust owns rasterization, AOI masking and terrain for the native path.
        return HorizontalGrid(plan, None, np.empty((0, 0), dtype=np.float32))
    with rasterio.Env(GDAL_CACHEMAX=64 << 20), rasterio.open(terrain_path) as src:
        ground = (
            src.read(1, window=plan.window, masked=True).filled(np.nan)
            if read_terrain
            else np.empty((0, 0), dtype=np.float32)
        )
        if np.isinf(ground).any():
            raise FimUnsupportedError(
                "horizontal terrain contains unmasked infinite values"
            )
        owner = rasterize(
            ((g, i + 1) for i, g in enumerate(cells.geometry)),
            out_shape=plan.shape,
            transform=plan.transform,
            fill=0,
            dtype="int32",
            all_touched=False,
        )
    if plan.mask_geometry:
        from ._aoi_lattice import mask
        keep = mask(plan.geometry, plan.source_transform, plan.window)
        owner[~keep] = 0
    owner.setflags(write=False)
    ground.setflags(write=False)
    return HorizontalGrid(plan, owner, ground)


def render(grid: HorizontalGrid, values: np.ndarray, min_depth: float):
    """Gather each owning cell's WSE and filter both products by pixel depth."""
    if (
        np.isinf(values).any()
        or (np.abs(values[np.isfinite(values)]) > np.finfo(np.float32).max).any()
    ):
        raise FimUnsupportedError(
            "horizontal WSE values must be finite float32-range values or NaN"
        )
    table = np.concatenate(
        (np.array([np.nan], dtype=np.float32), values.astype(np.float32))
    )
    wse = table[grid.owner]
    with np.errstate(over="raise", invalid="ignore"):
        depth = wse - grid.ground
    # Match native binary32 addition/comparison before optional postprocessing.
    # A depth-only 0.001 cutoff is not equivalent at float32 boundaries.
    keep = (
        np.isfinite(grid.ground)
        & np.isfinite(depth)
        & (wse >= np.add(grid.ground, np.float32(0.001), dtype=np.float32))
    )
    if min_depth > 0:
        keep &= depth > np.float32(min_depth)
    depth[~keep] = np.nan
    wse[~keep] = np.nan
    return depth, wse
