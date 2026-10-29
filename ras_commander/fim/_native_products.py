"""Validate and deliver native lossless TIFF products without array transfers."""

import math

from . import _products
from .errors import FimEngineError


def deliver(source, folder, name, header, plan):
    import rasterio

    pixels = plan.shape[0] * plan.shape[1]
    finite, flooded = header.get("depth_finite_pixels"), header.get("flooded_pixels")
    seconds = header.get("write_seconds")
    if (
        header.get("products") != "native-geotiff/1"
        or type(finite) is not int
        or type(flooded) is not int
        or not 0 <= flooded <= finite <= pixels
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise FimEngineError("Invalid native product completion record")
    destinations = _products.product_paths(folder, name)
    paths = [source / "depth.tif", source / "wse.tif"]
    # Check both before moving either; the caller cleans delivered files on failure.
    for path in paths:
        with rasterio.open(path) as image:
            if (
                image.shape != plan.shape
                or image.transform != plan.transform
                or image.crs != plan.crs
                or image.count != 1
                or image.dtypes != ("float32",)
                or image.nodata is None
                or not math.isnan(image.nodata)
                or image.compression != rasterio.enums.Compression.lzw
            ):
                raise FimEngineError(
                    "Native GeoTIFF metadata differs from requested grid"
                )
    for path, destination in zip(paths, destinations[:2], strict=True):
        path.replace(destination)
    return dict(
        status="complete" if flooded else "no_flooded_pixels",
        depth_tif=str(destinations[0]),
        wse_tif=str(destinations[1]),
        floodplain_gpkg=None,
        col_off=int(plan.window.col_off),
        row_off=int(plan.window.row_off),
        width=plan.shape[1],
        height=plan.shape[0],
        transform=tuple(float(v) for v in tuple(plan.transform)[:6]),
        crs=plan.crs.to_string(),
        depth_finite_pixels=finite,
        flooded_pixels=flooded,
        error=None,
    )
