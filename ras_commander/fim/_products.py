"""Product writers for the ras2fim-2D FIM method.

Products keep the upstream ras2fim-2D names:

- ``09_<profile>_depth_nudge.tif``: depth, float32, LZW, NaN nodata;
- ``10_<profile>_wsel_nudge.tif``: WSE, same layout;
- ``11_<profile>_floodplain_ar.gpkg``: one (Multi)Polygon of the pixels with
  ``0 < depth <= 10000``, polygonized from product 09.

Portions adapted from ras2fim-2D (``fn_make_floodplain_gdf`` by Andy Carter,
PE), Copyright (c) 2026, The University of Texas at Austin, BSD 3-Clause
License. See ``ras_commander/fim/THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np

# Upstream floodplain depth limits: 0 < depth <= 10000 model units.
FLOODPLAIN_MIN_DEPTH = 0.0
FLOODPLAIN_MAX_DEPTH = 10000.0


def product_paths(output_folder: Path, profile: str) -> Tuple[Path, Path, Path]:
    """Return the 09, 10 and 11 paths for one profile."""
    output_folder = Path(output_folder)
    return (output_folder / f"09_{profile}_depth_nudge.tif",
            output_folder / f"10_{profile}_wsel_nudge.tif",
            output_folder / f"11_{profile}_floodplain_ar.gpkg")


def flooded_mask(depth: np.ndarray) -> np.ndarray:
    """Pixels the upstream floodplain polygon covers."""
    with np.errstate(invalid="ignore"):
        return (depth > FLOODPLAIN_MIN_DEPTH) & (depth <= FLOODPLAIN_MAX_DEPTH)


def write_raster(path: Path, array: np.ndarray, transform, crs) -> None:
    """Write a float32, LZW, NaN-nodata, single-band GeoTIFF (stripped, as upstream)."""
    import rasterio

    height, width = array.shape
    profile = {"driver": "GTiff", "dtype": "float32", "width": width, "height": height, "count": 1,
               "crs": crs, "transform": transform, "nodata": np.nan, "compress": "lzw",
               "tiled": False, "interleave": "band"}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.asarray(array, dtype=np.float32), 1)


def floodplain_frame(depth: np.ndarray, transform, crs):
    """Return a one-row GeoDataFrame of the floodplain, or None when no pixel is flooded."""
    import geopandas as gpd
    import shapely
    from rasterio.features import shapes
    from shapely.geometry import shape

    flooded = flooded_mask(depth)
    if not flooded.any():
        return None
    data = np.where(flooded, 1, 255).astype("uint8")
    geometries = [shape(geom) for geom, _ in shapes(data, mask=data != 255, transform=transform)]
    merged = shapely.union_all(np.asarray(geometries, dtype=object))
    return gpd.GeoDataFrame(geometry=[merged], crs=crs)
