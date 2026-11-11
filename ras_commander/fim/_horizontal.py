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
    # Positive-area overlaps accepted as roundoff residue for this plan's
    # pixel centres. A validation that relied on any is specific to the plan.
    tolerated_overlaps: int = 0


def plan_grid(
    cells, terrain_path: Path, aoi, max_working_mib: int, native: bool = False,
    storage_areas=None,
) -> GridPlan:
    """Inspect metadata and admit the window before allocating raster arrays.

    ``storage_areas`` (optional array of storage-area polygons in the cells'
    CRS) widens the window to the cells and storage areas together, with one
    pixel of margin around the storage areas, and admits the engine's
    storage-area arrays.
    """
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
    storage = None
    if storage_areas is not None and len(storage_areas):
        storage = np.asarray(storage_areas, dtype=object)
        extent = shapely.total_bounds(storage)
        if not np.isfinite(extent).all():
            raise FimUnsupportedError("storage-area coordinates must be finite")
    with rasterio.open(terrain_path) as src:
        t = src.transform
        if storage is not None:
            # One pixel of margin keeps every storage-area pixel centre inside.
            pad = abs(t.a)
            bounds = np.array([
                min(bounds[0], extent[0] - pad),
                min(bounds[1], extent[1] - pad),
                max(bounds[2], extent[2] + pad),
                max(bounds[3], extent[3] + pad),
            ])
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

            box = shapely.box(*window_bounds(window, t))
            positions = np.sort(cells.sindex.query(box, predicate="intersects"))
            if not len(positions):
                if storage is not None and shapely.intersects(storage, box).any():
                    raise FimUnsupportedError(
                        "the output window holds storage areas but no 2D cells; "
                        "storage-area-only windows are not supported"
                    )
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
    if storage is not None and pixels:
        # Engine storage-area burns, AOI mask and sparse pixel lists.
        planned += pixels * 28
        if native:
            storage_transport = (
                int(shapely.get_num_coordinates(storage).sum()) * 16 + len(storage) * 128
                + int(shapely.get_num_interior_rings(storage).sum()) * 4
            )
            transport += storage_transport
            planned += storage_transport * 12
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


def _numerical_overlap_without_sample(intersection, plan):
    """Recognize coordinate-roundoff residue that owns no output pixel centre.

    The area must fit an eight-ULP boundary-error envelope at the coordinates'
    scale. Even then, an interior terrain pixel centre keeps the rejection.
    This changes neither ownership polygons nor the native hydraulic topology.
    """
    import math
    import shapely

    bounds = shapely.bounds(intersection)
    scale = max(1.0, float(np.max(np.abs(bounds))))
    envelope = 8 * abs(float(np.spacing(scale))) * max(1.0, float(intersection.length))
    if not np.isfinite(envelope) or intersection.area > envelope:
        return False
    t = plan.transform
    xmin, ymin, xmax, ymax = bounds
    c0 = max(0, math.ceil((xmin - t.c) / t.a - 0.5) - 1)
    c1 = min(plan.shape[1] - 1, math.floor((xmax - t.c) / t.a - 0.5) + 1)
    r0 = max(0, math.ceil((ymax - t.f) / t.e - 0.5) - 1)
    r1 = min(plan.shape[0] - 1, math.floor((ymin - t.f) / t.e - 0.5) + 1)
    if c1 < c0 or r1 < r0:
        return True
    if (c1 - c0 + 1) * (r1 - r0 + 1) > 4096:
        return False  # Conservative bound; never allocate an unbounded check.
    cols, rows = np.meshgrid(np.arange(c0, c1 + 1), np.arange(r0, r1 + 1))
    points = shapely.points(t.c + (cols.ravel() + 0.5) * t.a,
                            t.f + (rows.ravel() + 0.5) * t.e)
    if shapely.contains(intersection, points).any():
        return False
    # Native sloping uses the global terrain lattice, whereas the Python
    # horizontal writer evaluates the cropped transform. Check both arithmetic
    # orders: their last bits can differ at the scale of the residue itself.
    source = getattr(plan, "source_transform", None)
    if source is not None:
        points = shapely.points(
            source.c + (cols.ravel() + plan.window.col_off + 0.5) * source.a,
            source.f + (rows.ravel() + plan.window.row_off + 0.5) * source.e,
        )
        if shapely.contains(intersection, points).any():
            return False
    return True


# Candidate pairs admitted by one bulk spatial-index query (16 bytes each).
_PAIR_QUERY_BUDGET = 1 << 22
_PAIR_BATCH = 4096


def _check_pairs(geometries, first, second, plan):
    """Refuse a real overlap; return how many roundoff residues were accepted."""
    import shapely

    first = geometries[first]
    second = geometries[second]
    interiors = shapely.relate_pattern(first, second, "T********")
    tolerated = 0
    if interiors.any():
        intersections = shapely.intersection(first[interiors], second[interiors])
        for intersection in intersections[shapely.area(intersections) > 0]:
            if not _numerical_overlap_without_sample(intersection, plan):
                raise FimUnsupportedError("horizontal cells have overlapping interiors")
            tolerated += 1
    return tolerated


def _warn_tolerated(count):
    import warnings

    for _ in range(count):
        warnings.warn(
            "Numerical cell-overlap residue has no interior terrain pixel centre; "
            "ownership polygons and hydraulic topology are unchanged",
            RuntimeWarning, stacklevel=3,
        )


def _candidate_batches(geometries, index):
    """Yield bounded (left, right) candidate pairs whose interiors could meet."""
    import shapely

    bounds = shapely.bounds(geometries)
    total = len(geometries)
    # Coincident geometries must not allocate an N-by-N candidate-pair array
    # before the first overlap is rejected: a query of ``step`` cells returns
    # at most ``step * N`` pairs.
    step = max(1, min(_PAIR_BATCH, _PAIR_QUERY_BUDGET // max(total, 1)))
    held_left = np.empty(0, dtype=np.intp)
    held_right = np.empty(0, dtype=np.intp)
    for start in range(0, total, step):
        pairs = index.query(geometries[start : start + step])
        left = pairs[0] + start
        right = pairs[1]
        later = right > left
        left, right = left[later], right[later]
        # A polygon interior lies inside the open interior of its envelope, so
        # envelopes that only touch (or have no extent) cannot hold a shared
        # interior point. Comparisons only: no rounding can change the answer,
        # and an unordered (NaN) envelope keeps its pair.
        possible = ~(
            (np.maximum(bounds[left, 0], bounds[right, 0])
             >= np.minimum(bounds[left, 2], bounds[right, 2]))
            | (np.maximum(bounds[left, 1], bounds[right, 1])
               >= np.minimum(bounds[left, 3], bounds[right, 3]))
        )
        held_left = np.concatenate((held_left, left[possible]))
        held_right = np.concatenate((held_right, right[possible]))
        offset = 0
        while len(held_left) - offset >= _PAIR_BATCH:
            yield held_left[offset : offset + _PAIR_BATCH], held_right[offset : offset + _PAIR_BATCH]
            offset += _PAIR_BATCH
        held_left, held_right = held_left[offset:], held_right[offset:]
    if len(held_left):
        yield held_left, held_right


def prepare_grid(
    cells, terrain_path: Path, plan: GridPlan, read_terrain: bool = True, *, threads: int = 1
) -> HorizontalGrid:
    """Cache terrain and centre-based cell ownership for one admitted window.

    ``threads`` bounds the workers used for the overlap predicates; it never
    changes which cell sets are accepted or refused.
    """
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
    workers = max(1, min(int(threads), 64))
    pool = None
    if workers > 1 and len(geometries) > _PAIR_BATCH:
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(workers, thread_name_prefix="fim-cell-validation")
    try:
        if not np.isin(shapely.get_type_id(geometries), [3]).all() or shapely.is_empty(
            geometries
        ).any():
            valid = False
        else:
            # Calling thread only: shapely.is_valid enters warnings.catch_warnings,
            # which swaps process-wide warning state and is not thread-safe.
            valid = bool(shapely.is_valid(geometries).all())
        if not valid:
            raise FimUnsupportedError(
                "horizontal mapping requires valid, non-empty cell Polygons"
            )
        # Reject positive-area overlaps: choosing a cell silently would replace
        # one hydraulic value with another. Shared edges and coordinate-roundoff
        # residue with no interior output pixel centre are permitted.
        tolerated = 0
        batches = _candidate_batches(geometries, cells.sindex)
        if pool is None:
            for first, second in batches:
                found = _check_pairs(geometries, first, second, plan)
                _warn_tolerated(found)
                tolerated += found
        else:
            from collections import deque

            pending = deque()
            for first, second in batches:
                pending.append(pool.submit(_check_pairs, geometries, first, second, plan))
                if len(pending) >= workers * 2:
                    found = pending.popleft().result()
                    _warn_tolerated(found)
                    tolerated += found
            while pending:
                found = pending.popleft().result()
                _warn_tolerated(found)
                tolerated += found
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    if not read_terrain:
        # Rust owns rasterization, AOI masking and terrain for the native path.
        return HorizontalGrid(plan, None, np.empty((0, 0), dtype=np.float32), tolerated)
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
    return HorizontalGrid(plan, owner, ground, tolerated)


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
