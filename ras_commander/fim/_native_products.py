"""Validate and deliver native lossless TIFF products without array transfers."""

import math

from . import _products
from .errors import FimEngineError, FimUnsupportedError


def validate_controls(products=None, compression=None, *, writer="native", method=None):
    explicit = products is not None or compression is not None
    selected = ["depth", "wse"] if products is None else products
    if isinstance(selected, (str, bytes)) or not isinstance(selected, (list, tuple)):
        raise TypeError("products must be a sequence of depth/wse names")
    if (
        not selected
        or any(p not in ("depth", "wse") for p in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("products must be unique depth/wse names")
    codec = "LZW" if compression is None else compression
    if codec not in ("NONE", "LZW"):
        raise ValueError("compression must be NONE or LZW")
    if explicit and writer != "native":
        raise FimUnsupportedError(
            "products/compression controls require product_writer='native'"
        )
    if (
        explicit
        and method is not None
        and (
            not set(selected).issubset(method.get("native_output_products", []))
            or codec not in method.get("native_output_compression", [])
        )
    ):
        raise FimUnsupportedError(
            "Engine does not advertise native product/compression controls"
        )
    return list(selected), codec, explicit


def deliver(source, folder, name, header, plan, *, products=None, compression=None):
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
    selected, codec, explicit = validate_controls(products, compression)
    if explicit and (
        header.get("selected_products") != selected
        or header.get("compression") != codec
    ):
        raise FimEngineError(
            "Native completion does not match requested products/compression"
        )
    destinations = _products.product_paths(folder, name)
    paths = [source / f"{product}.tif" for product in selected]
    targets = [destinations[0 if product == "depth" else 1] for product in selected]
    if any(
        (source / f"{product}.tif").exists()
        for product in ("depth", "wse")
        if product not in selected
    ):
        raise FimEngineError("Engine emitted an unrequested native product")
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
                or image.compression
                != (rasterio.enums.Compression.lzw if codec == "LZW" else None)
            ):
                raise FimEngineError(
                    "Native GeoTIFF metadata differs from requested grid"
                )
    for path, destination in zip(paths, targets, strict=True):
        path.replace(destination)
    return dict(
        status="complete" if flooded else "no_flooded_pixels",
        depth_tif=str(destinations[0]) if "depth" in selected else None,
        wse_tif=str(destinations[1]) if "wse" in selected else None,
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
