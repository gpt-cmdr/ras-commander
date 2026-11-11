"""Engine-written final delivery GeoTIFFs for sloping Depth/WSE products.

``final_format`` asks a capable engine to write each product once as a tiled
DEFLATE GeoTIFF with a numeric nodata value, optional placement on a larger
grid of the terrain lattice and optional average overviews. Nothing here
encodes pixels: this module validates the option, checks the engine
capability, builds the wire block and verifies what the engine delivered.
There is no Rasterio fallback.
"""

import math

import numpy as np

from .errors import FimEngineError, FimUnsupportedError

CAPABILITY = "native_final_format"
KEYS = ("nodata", "block_size", "zlevel", "overviews", "grid")
# The engine reports a valid value that would be lost to the nodata mask so.
NODATA_REFUSAL = "reads as the nodata value"


def _integer(value, label, low, high):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"final_format {label} must be an integer")
    value = int(value)
    if not low <= value <= high:
        raise ValueError(f"final_format {label} must be from {low} through {high}")
    return value


def normalize(final_format):
    """Validate the caller option; return a plain dict with every key, or ``None``."""
    if final_format is None:
        return None
    if not isinstance(final_format, dict):
        raise ValueError("final_format must be a dict or None")
    unknown = sorted(set(final_format) - set(KEYS), key=str)
    if unknown:
        raise ValueError(f"final_format has unknown keys {unknown}; accepted: {list(KEYS)}")
    if "nodata" not in final_format:
        raise ValueError("final_format requires nodata")
    nodata = final_format["nodata"]
    if isinstance(nodata, (bool, np.bool_)) or not isinstance(
        nodata, (int, float, np.integer, np.floating)
    ):
        raise ValueError("final_format nodata must be a number")
    nodata = float(nodata)
    with np.errstate(over="ignore"):
        exact = math.isfinite(nodata) and float(np.float32(nodata)) == nodata
    if not exact:
        raise ValueError("final_format nodata must be finite and exactly representable as float32")
    block = _integer(final_format.get("block_size", 256), "block_size", 16, 4096)
    if block % 16:
        raise ValueError("final_format block_size must be a multiple of 16")
    zlevel = _integer(final_format.get("zlevel", 6), "zlevel", 1, 9)
    overviews = final_format.get("overviews", ())
    if isinstance(overviews, (str, bytes)) or not isinstance(overviews, (list, tuple)):
        raise ValueError("final_format overviews must be a list such as [2, 4]")
    overviews = [_integer(v, "overviews", 2, 1 << 16) for v in overviews]
    if len(overviews) > 16 or overviews != [2 << i for i in range(len(overviews))]:
        raise ValueError("final_format overviews must be consecutive powers of two from 2")
    grid = final_format.get("grid", "window")
    if isinstance(grid, (list, tuple)):
        if len(grid) != 4:
            raise ValueError("final_format grid must be window, terrain or [col, row, width, height]")
        grid = [_integer(v, "grid", 0, (1 << 32) - 1) for v in grid]
        if not grid[2] or not grid[3]:
            raise ValueError("final_format grid width and height must be positive")
    elif grid not in ("window", "terrain"):
        raise ValueError("final_format grid must be window, terrain or [col, row, width, height]")
    return dict(nodata=nodata, block_size=block, zlevel=zlevel, overviews=overviews, grid=grid)


def require_engine(method, options, row_stream_rows=0):
    """Refuse unless the engine advertises this exact final-format contract."""
    capability = method.get(CAPABILITY)
    block = capability.get("block_size") if isinstance(capability, dict) else None
    zlevel = capability.get("zlevel") if isinstance(capability, dict) else None

    def spans(limits, value):
        return (
            isinstance(limits, dict)
            and all(type(limits.get(k)) is int for k in ("min", "max"))
            and limits["min"] <= value <= limits["max"]
        )

    if (
        not method.get("native_geotiff_outputs")
        or not isinstance(capability, dict)
        or capability.get("control") != "final_format"
        or capability.get("compression") != "DEFLATE"
        or capability.get("layout") != "tiled"
        or not spans(block, options["block_size"])
        or type(block.get("multiple_of")) is not int
        or block["multiple_of"] < 1
        or options["block_size"] % block["multiple_of"]
        or not spans(zlevel, options["zlevel"])
        or (options["grid"] != "window" and capability.get("full_grid") is not True)
        or (row_stream_rows and capability.get("row_stream_rows") is not True)
        or (options["overviews"] and "average" not in (capability.get("overview_resampling") or ()))
    ):
        raise FimUnsupportedError(
            "final_format requires an engine advertising a compatible native_final_format "
            "capability; there is no Rasterio fallback for this delivery"
        )


def resolve(options, plan, terrain_width, terrain_height):
    """Place the planned window on the delivery grid.

    Returns ``(wire, grid)``: the engine ``final_format`` block and the grid as
    delivered (terrain offsets, shape and affine transform).
    """
    from rasterio.windows import Window

    col, row = int(plan.window.col_off), int(plan.window.row_off)
    height, width = plan.shape
    selection = options["grid"]
    if selection == "window":
        grid = [col, row, width, height]
    elif selection == "terrain":
        grid = [0, 0, int(terrain_width), int(terrain_height)]
    else:
        grid = list(selection)
    if (
        grid[0] + grid[2] > terrain_width
        or grid[1] + grid[3] > terrain_height
        or col < grid[0]
        or row < grid[1]
        or col + width > grid[0] + grid[2]
        or row + height > grid[1] + grid[3]
    ):
        raise FimUnsupportedError(
            f"final_format grid {grid} must lie on the terrain and contain the mapped "
            f"window {[col, row, width, height]}"
        )
    source = plan.source_transform
    transform = source * source.translation(grid[0], grid[1])
    wire = dict(
        nodata=options["nodata"],
        block_size=options["block_size"],
        zlevel=options["zlevel"],
        overview_factors=list(options["overviews"]),
        overview_resampling="average",
    )
    if selection != "window":
        wire["full_grid"] = dict(
            width=grid[2],
            height=grid[3],
            row_offset=row - grid[1],
            col_offset=col - grid[0],
            transform=[float(v) for v in transform.to_gdal()],
        )
    return wire, dict(
        col_off=grid[0], row_off=grid[1], width=grid[2], height=grid[3], transform=transform,
        window=Window(col - grid[0], row - grid[1], width, height),
    )


def report_error(out_dir):
    """Best-effort error text of an aborted engine report."""
    import json
    from pathlib import Path

    try:
        report = json.loads((Path(out_dir) / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return ""
    error = report.get("error") if isinstance(report, dict) else None
    return error if isinstance(error, str) else ""


def check_header(header, wire):
    """Require the completion record to echo the requested format; return its counts."""
    echoed = header.get("final_format")
    expected = dict(wire)
    if not isinstance(echoed, dict) or header.get("compression") != "DEFLATE":
        raise FimEngineError("Native completion record lacks the requested final_format")
    if "full_grid" not in expected and echoed.get("full_grid") is None:
        echoed = {k: v for k, v in echoed.items() if k != "full_grid"}
    if echoed != expected:
        raise FimEngineError("Native completion record final_format differs from the request")
    counts = {}
    for name in ("depth_final", "wse_final"):
        value = header.get(name)
        if value is None:
            continue  # bounded row delivery reports no per-file counts
        if not isinstance(value, dict) or any(
            type(value.get(k)) is not int or value[k] < 0
            for k in ("valid_pixels", "tiles", "shared_nodata_tiles", "file_bytes")
        ):
            raise FimEngineError(f"Invalid native {name} completion counts")
        counts[name] = {k: value[k] for k in ("valid_pixels", "tiles", "shared_nodata_tiles", "file_bytes")}
    finite = header.get("depth_finite_pixels")
    if "depth_final" in counts and counts["depth_final"]["valid_pixels"] != finite:
        raise FimEngineError(
            "Native completion record final depth valid-pixel count differs from the product"
        )
    return counts


def check_file(image, wire, grid, crs):
    """Require the delivered file to carry exactly the requested format."""
    import rasterio

    block = wire["block_size"]
    factors = wire["overview_factors"]
    problems = []
    if image.shape != (grid["height"], grid["width"]):
        problems.append("shape")
    if image.transform != grid["transform"]:
        problems.append("transform")
    if image.crs != crs:
        problems.append("CRS")
    if image.count != 1 or image.dtypes != ("float32",):
        problems.append("band type")
    if image.nodata is None or float(image.nodata) != wire["nodata"]:
        problems.append("nodata")
    if image.compression != rasterio.enums.Compression.deflate:
        problems.append("compression")
    if image.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR", "1") != "1":
        problems.append("predictor")
    if image.block_shapes != [(block, block)]:
        problems.append("tiling")
    if image.overviews(1) != factors:
        problems.append("overviews")
    if factors and image.tags(ns="rio_overview").get("resampling") != "average":
        problems.append("overview resampling tag")
    if problems:
        raise FimEngineError(
            "Native final-format GeoTIFF differs from the request: " + ", ".join(problems)
        )


def describe(options, wire, grid):
    """Receipt block: what was asked and where the window sits on the delivered grid."""
    window = grid["window"]
    return dict(
        schema="fim-final-format/1",
        writer="native",
        compression="DEFLATE",
        predictor=1,
        layout="tiled",
        nodata=wire["nodata"],
        block_size=wire["block_size"],
        zlevel=wire["zlevel"],
        overviews=list(wire["overview_factors"]),
        overview_resampling="average" if wire["overview_factors"] else None,
        grid=options["grid"],
        grid_on_terrain=[grid["col_off"], grid["row_off"], grid["width"], grid["height"]],
        window_on_grid=[int(window.col_off), int(window.row_off), int(window.width), int(window.height)],
        arrays_streamed=False,
        rasterio_write=False,
    )
