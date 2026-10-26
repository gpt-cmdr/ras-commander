"""Single-pass delivery on a caller-supplied pixel lattice; no resampling."""

from pathlib import Path

import numpy as np

from . import _prepare, _products
from .errors import FimUnsupportedError


def template_profile(path, plan):
    """Inspect an aligned float32 template before mapping arrays are loaded."""
    import rasterio

    with rasterio.open(path) as source:
        profile = source.profile.copy()
        if (
            source.count != 1
            or source.dtypes != ("float32",)
            or source.nodata is None
            or not _prepare.same_crs(plan.crs, source.crs)
        ):
            raise FimUnsupportedError(
                "template_raster must be same-CRS single-band float32 with declared nodata"
            )
        a, b = plan.transform, source.transform
        if a.b or a.d or b.b or b.d or b.a <= 0 or b.e >= 0:
            raise FimUnsupportedError(
                "template_raster requires a north-up pixel lattice"
            )
        col = (a.c - b.c) / b.a
        row = (a.f - b.f) / b.e
        rows, cols = plan.shape
        if (
            abs(col - round(col)) >= 1e-6
            or abs(row - round(row)) >= 1e-6
            or abs(cols * a.a / b.a - cols) >= 1e-6
            or abs(rows * a.e / b.e - rows) >= 1e-6
        ):
            raise FimUnsupportedError(
                "template_raster must share terrain pixel centres; resampling is unsupported"
            )
        col, row = int(round(col)), int(round(row))
        if (
            col < 0
            or row < 0
            or col + cols > source.width
            or row + rows > source.height
        ):
            raise FimUnsupportedError(
                "template_raster must contain the complete mapping window"
            )
        profile.update(driver="GTiff", count=1, dtype="float32")
        predictor = source.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR")
        if predictor is not None:
            profile["predictor"] = int(predictor)
        return dict(
            profile=profile,
            col=col,
            row=row,
            stripe_rows=max(1, source.block_shapes[0][0]),
            planned_buffer_bytes=source.width * max(1, source.block_shapes[0][0]) * 12,
        )


def write_array(path, array, layout):
    """Write once, explicitly filling borders with the template's nodata."""
    import rasterio
    from rasterio.windows import Window

    profile = layout["profile"]
    col = layout["col"]
    row = layout["row"]
    height, width = array.shape
    with (
        rasterio.Env(GDAL_NUM_THREADS="1"),
        rasterio.open(path, "w", **profile) as target,
    ):
        for top in range(0, profile["height"], layout["stripe_rows"]):
            bottom = min(top + layout["stripe_rows"], profile["height"])
            values = np.full(
                (bottom - top, profile["width"]), profile["nodata"], dtype="float32"
            )
            first = max(top, row)
            last = min(bottom, row + height)
            if first < last:
                part = values[first - top : last - top, col : col + width]
                part[:] = array[first - row : last - row]
                if np.isfinite(profile["nodata"]) and np.any(part == profile["nodata"]):
                    raise FimUnsupportedError(
                        "template_raster nodata collides with finite mapping values"
                    )
                part[~np.isfinite(part)] = profile["nodata"]
            target.write(
                values, 1, window=Window(0, top, profile["width"], bottom - top)
            )


def write_products(folder, result, crs, write_floodplain, layout):
    """Keep raster layout separate from native interpolation and flood geometry."""
    depth_path, wse_path, floodplain_path = _products.product_paths(
        Path(folder), result.profile
    )
    write_array(depth_path, result.depth, layout)
    write_array(wse_path, result.wse, layout)
    flooded = int(_products.flooded_mask(result.depth).sum())
    floodplain = None
    if write_floodplain and flooded:
        frame = _products.floodplain_frame(result.depth, result.transform, crs)
        frame.to_file(floodplain_path)
        floodplain = str(floodplain_path)
    p = layout["profile"]
    return dict(
        status="complete" if flooded else "no_flooded_pixels",
        depth_tif=str(depth_path),
        wse_tif=str(wse_path),
        floodplain_gpkg=floodplain,
        col_off=0,
        row_off=0,
        width=p["width"],
        height=p["height"],
        transform=tuple(float(v) for v in tuple(p["transform"])[:6]),
        crs=crs.to_string(),
        depth_finite_pixels=int(np.isfinite(result.depth).sum()),
        flooded_pixels=flooded,
        error=None,
    )
