"""Global sample preparation and grid derivation for the ras2fim-2D FIM method.

These functions reproduce the ras2fim-2D Step 05 preparation that precedes
interpolation:

1. wet cells are the rows whose profile WSE is not NaN;
2. samples are the wet cell centres (sorted ``cell_idx`` order), followed by
   the wet-cell polygon vertices that lie outside the convex hull of those
   centres, with coincident vertices (rounded to 0.01 model units) merged
   with their mean WSE;
3. the query axes are ``np.arange(xmin, xmax, res)`` and
   ``np.arange(ymin, ymax, res)`` over the wet-union bounds, where ``res`` is
   the terrain pixel width;
4. the final grid is ``calculate_default_transform`` to the output CRS with
   its origin snapped to a multiple of the output resolution.

Preparation is always global. An area of interest never subsets these
inputs.

Portions adapted from ras2fim-2D (``src/generate_depth_wsel_rasters_mp_05.py``
by Andy Carter, PE, and ``src/rust_mapping.py``), Copyright (c) 2026, The
University of Texas at Austin, BSD 3-Clause License. See
``ras_commander/fim/THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd

from .errors import FimUnsupportedError

INPUTS_SCHEMA = "ras2fim-step05-inputs/1"

# Upstream merges hull-exterior vertices whose coordinates round to the same
# hundredth of a model unit.
MERGE_DECIMALS = 2


@dataclass
class FimPreparedProfile:
    """Global interpolation inputs for one WSE profile.

    Attributes:
        profile: Profile (column) name.
        x, y, z: Sample coordinates and WSE in upstream order (wet centres,
            then merged hull-exterior vertices).
        x_axis, y_axis: Exact ``np.arange`` query axes. The effective step
            can differ from ``res`` in the last bits.
        xmin, ymin, res: Raster-01 origin and pixel size.
        wet_union: Shapely union of the wet cell polygons.
        crs: CRS of the hydraulic results (and of all coordinates above).
        wet_cell_count: Number of wet cells (centres) used.
    """

    profile: str
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    xmin: float
    ymin: float
    res: float
    wet_union: Any
    crs: Any
    wet_cell_count: int

    @property
    def sample_count(self) -> int:
        return int(len(self.x))

    @property
    def shape(self) -> Tuple[int, int]:
        """``(rows, cols)`` of the raster-01 grid."""
        return int(len(self.y_axis)), int(len(self.x_axis))


@dataclass
class FimGrids:
    """Grids derived from the upstream recipe for one profile."""

    rows: int
    cols: int
    raster_affine: Any
    wet_mask: Optional[np.ndarray]
    dest_transform: Any
    dest_width: int
    dest_height: int
    dest_crs: Any


def _merge_points(gdf, profile: str):
    """Upstream ``fn_merge_points_within_threshold`` (rounded-XY grouping)."""
    import geopandas as gpd
    from shapely.geometry import Point

    merged = []
    grouped = gdf.groupby(
        gdf.geometry.apply(lambda p: (round(p.x, MERGE_DECIMALS), round(p.y, MERGE_DECIMALS)))
    )
    for _, group in grouped:
        if len(group) > 1:
            merged.append({
                "geometry": Point(group.geometry.x.mean(), group.geometry.y.mean()),
                profile: group[profile].mean(),
            })
        else:
            merged.append({"geometry": group.iloc[0].geometry, profile: group.iloc[0][profile]})
    return gpd.GeoDataFrame(merged)


def prepare_profile(cells, centers, profile: str, pixel_size: float) -> FimPreparedProfile:
    """Prepare the global samples and query axes for one profile.

    ``cells`` has ``cell_idx``, polygon ``geometry``, and the profile column
    (NaN = dry). ``centers`` has ``cell_idx`` and point ``geometry`` in the
    same CRS, ordered by ascending ``cell_idx``. Neither frame is modified.
    """
    import geopandas as gpd
    import shapely
    from scipy.spatial import ConvexHull
    from shapely.geometry import Point, Polygon

    if profile not in cells.columns:
        raise KeyError(f"profile column {profile!r} not in cells")
    values = cells[profile].to_numpy(dtype=np.float64)
    if np.isinf(values).any():
        raise FimUnsupportedError(f"{profile}: infinite WSE values are not supported")
    if not np.isfinite(values).any():
        raise FimUnsupportedError(f"{profile}: no wet cells")

    # Wet centres: left join keeps the centre order (sorted cell_idx).
    df_wse = cells[["cell_idx", profile]]
    gdf_pnt = pd.merge(centers[["cell_idx", "geometry"]], df_wse, on="cell_idx", how="left")
    gdf_pnt = gdf_pnt.dropna(subset=[profile]).copy()
    gdf_ar = cells.dropna(subset=[profile]).copy()
    if len(gdf_pnt) != len(gdf_ar):
        raise FimUnsupportedError(
            f"{profile}: {len(gdf_ar)} wet cells but {len(gdf_pnt)} matching centres; "
            "cell_idx values must be unique and present in the centres"
        )
    gdf_ar.loc[:, "val"] = 1
    gdf_dissolved = gdf_ar.dissolve(by="val")
    wet_union = gdf_dissolved.geometry.iloc[0]

    # Convex hull of the wet centres. The upstream per-vertex test
    # Polygon(hull).contains(Point(v)) is evaluated with contains_xy, which
    # is the same predicate.
    centre_xy = [(p.x, p.y) for p in gdf_pnt.geometry]
    hull = ConvexHull(centre_xy)
    hull_polygon = Polygon([centre_xy[v] for v in hull.vertices])
    shapely.prepare(hull_polygon)

    created = []
    created_wse = []
    profile_values = gdf_ar[profile].to_numpy()
    for geom, wse in zip(gdf_ar.geometry, profile_values):
        if geom is None or geom.geom_type != "Polygon":
            raise FimUnsupportedError(f"{profile}: wet cell geometry must be a Polygon")
        coords = np.asarray(geom.exterior.coords)
        outside = ~shapely.contains_xy(hull_polygon, coords[:, 0], coords[:, 1])
        for x, y in coords[outside]:
            created.append(Point(x, y))
            created_wse.append(wse)

    gdf_extra = gpd.GeoDataFrame(geometry=created)
    gdf_extra[profile] = created_wse
    gdf_extra = _merge_points(gdf_extra, profile) if len(gdf_extra) else gdf_extra
    if len(gdf_extra):
        gdf_extra = gdf_extra.set_crs(cells.crs, allow_override=True)

    points1 = gdf_pnt[["geometry", profile]].copy()
    if len(gdf_extra) > 0:
        points = pd.concat([points1, gdf_extra[["geometry", profile]].copy()], axis=0)
    else:
        points = points1
    points = gpd.GeoDataFrame(points, geometry="geometry")

    xmin, ymin, xmax, ymax = gdf_dissolved.total_bounds
    res = pixel_size
    return FimPreparedProfile(
        profile=profile,
        x=points.geometry.x.values,
        y=points.geometry.y.values,
        z=points[profile].values,
        x_axis=np.arange(xmin, xmax, res),
        y_axis=np.arange(ymin, ymax, res),
        xmin=xmin,
        ymin=ymin,
        res=res,
        wet_union=wet_union,
        crs=cells.crs,
        wet_cell_count=int(len(gdf_pnt)),
    )


def derive_grids(prep: FimPreparedProfile, terrain_bounds, output_crs, output_resolution: float) -> FimGrids:
    """Reproduce the upstream raster grid decisions without writing rasters.

    Raster 02 is the wet-union crop of raster 01, raster 03 is the crop of 02
    to the terrain bounds, and the 09/10 grid is ``calculate_default_transform``
    of the 07 grid followed by the origin snap. The engine works on the 01
    grid, so a crop that would change it is unsupported.
    """
    import rasterio.mask
    from affine import Affine
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from rasterio.warp import calculate_default_transform
    from shapely.geometry import box, mapping

    rows, cols = prep.shape
    affine_01 = Affine.translation(prep.xmin, prep.ymin) @ Affine.scale(prep.res, prep.res)
    profile = dict(driver="GTiff", width=cols, height=rows, count=1, dtype="float32",
                   crs=prep.crs, transform=affine_01, nodata=np.nan)
    with MemoryFile() as memfile:
        with memfile.open(**profile):
            pass
        with memfile.open() as ds:
            outside_02, transform_02, window_02 = rasterio.mask.raster_geometry_mask(
                ds, [mapping(prep.wet_union)], crop=True)
            if (int(window_02.col_off), int(window_02.row_off), int(window_02.width),
                    int(window_02.height)) != (0, 0, cols, rows) or tuple(transform_02) != tuple(affine_01):
                raise FimUnsupportedError(f"{prep.profile}: the wet-union crop changes the raster-01 grid")
            outside_03, _, window_03 = rasterio.mask.raster_geometry_mask(
                ds, [box(*terrain_bounds)], crop=True)
            if (int(window_03.col_off), int(window_03.row_off), int(window_03.width),
                    int(window_03.height)) != (0, 0, cols, rows) or outside_03.any():
                raise FimUnsupportedError(f"{prep.profile}: the raster-01 grid extends beyond the terrain")
            crs_07 = ds.crs
            bounds_07 = tuple(ds.bounds)

    res = float(output_resolution)
    transform, width, height = calculate_default_transform(crs_07, output_crs, cols, rows, *bounds_07)
    dest = from_origin(round(transform.c / res) * res, round(transform.f / res) * res, res, res)
    return FimGrids(rows, cols, affine_01, ~outside_02, dest, int(width), int(height), output_crs)


def _write_array(path: Path, arr, dtype) -> dict:
    arr = np.ascontiguousarray(arr, dtype=dtype)
    arr.tofile(path)
    return {"file": path.name, "dtype": np.dtype(dtype).str, "shape": list(arr.shape)}


def write_profile_inputs(directory: Path, prep: FimPreparedProfile, grids: FimGrids) -> dict:
    """Write one profile's engine inputs (``ras2fim-step05-inputs/1``).

    The SciPy ``Delaunay`` object is built from the exact samples, as
    ``griddata(method='linear')`` builds it. Returns the ``inputs.json`` record.
    """
    import scipy
    from scipy.spatial import Delaunay

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    samples = np.column_stack([np.asarray(prep.x, dtype=np.float64),
                               np.asarray(prep.y, dtype=np.float64),
                               np.asarray(prep.z, dtype=np.float64)])
    tri = Delaunay(np.ascontiguousarray(samples[:, :2]))
    if len(tri.coplanar):
        raise FimUnsupportedError(
            f"{prep.profile}: {len(tri.coplanar)} coplanar or duplicate samples are not supported"
        )
    files = {
        "samples": _write_array(directory / "samples.f64", samples, "<f8"),
        "simplices": _write_array(directory / "simplices.u32", tri.simplices, "<u4"),
        "transform": _write_array(directory / "transform.f64", tri.transform, "<f8"),
        "neighbors": _write_array(directory / "neighbors.i32", tri.neighbors, "<i4"),
        "equations": _write_array(directory / "equations.f64", tri.equations, "<f8"),
        "x_axis": _write_array(directory / "x_axis.f64", prep.x_axis, "<f8"),
        "y_axis": _write_array(directory / "y_axis.f64", prep.y_axis, "<f8"),
        "wet_mask": _write_array(directory / "wet_mask.u8", grids.wet_mask, "u1"),
    }
    a = grids.raster_affine
    record = {
        "schema": INPUTS_SCHEMA,
        "column": prep.profile,
        "rows": grids.rows,
        "cols": grids.cols,
        "raster_affine": {"x0": a.c, "y0": a.f, "res_x": a.a, "res_y": a.e},
        "delaunay": {
            "paraboloid_scale": float(tri.paraboloid_scale),
            "paraboloid_shift": float(tri.paraboloid_shift),
            "min_bound": tri.min_bound.tolist(),
            "max_bound": tri.max_bound.tolist(),
            "nsimplex": int(tri.nsimplex),
        },
        "provenance": {"scipy": scipy.__version__, "numpy": np.__version__,
                       "samples": "ras_commander.fim prepare_profile (upstream order)"},
        "files": files,
    }
    with open(directory / "inputs.json", "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1)
    return record
