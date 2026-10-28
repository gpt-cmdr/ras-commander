"""Evaluate mesh interpolators with bounded query-coordinate arrays."""

import numpy as np


_QUERY_BLOCK_PIXELS = 262_144


def _grid_query_blocks(grid_x, grid_y):
    """Yield flat output offsets and at most one block of x/y coordinates."""
    cols = len(grid_x)
    for start in range(0, cols * len(grid_y), _QUERY_BLOCK_PIXELS):
        stop = min(start + _QUERY_BLOCK_PIXELS, cols * len(grid_y))
        indices = np.arange(start, stop)
        yield start, stop, np.column_stack(
            (grid_x[indices % cols], grid_y[indices // cols])
        )


def _build_interpolator(points, values, method, fill_value, *, triangulation=None):
    """Build a value-dependent interpolator, optionally sharing geometry."""
    from scipy.interpolate import (
        CloughTocher2DInterpolator,
        LinearNDInterpolator,
        NearestNDInterpolator,
    )

    geometry = triangulation if triangulation is not None else points
    if method == "nearest":
        interpolator = NearestNDInterpolator(points, values)
    elif method == "linear":
        interpolator = LinearNDInterpolator(geometry, values, fill_value=fill_value)
    elif method == "cubic":
        interpolator = CloughTocher2DInterpolator(geometry, values, fill_value=fill_value)
    else:
        raise ValueError(f"Unknown interpolation method {method!r} for 2 dimensional data")

    return interpolator


def _interpolate_to_grid(
    points, values, grid_x, grid_y, method, fill_value, *, triangulation=None,
):
    """Build one SciPy interpolator and fill a float32 raster in blocks.

    The output remains an in-memory array. Query coordinates and interpolation
    temporaries are limited to ``_QUERY_BLOCK_PIXELS`` pixels per evaluation;
    the triangulation or search tree still scales with the input points. A
    caller may supply a triangulation for exactly these points; values and
    value-dependent cubic gradients are rebuilt on every call.
    """
    interpolator = _build_interpolator(
        points, values, method, fill_value, triangulation=triangulation,
    )

    result = np.empty((len(grid_y), len(grid_x)), dtype=np.float32)
    flat = result.ravel()
    for start, stop, query in _grid_query_blocks(grid_x, grid_y):
        block = interpolator(query).astype(np.float32)
        block[np.isnan(block)] = fill_value
        flat[start:stop] = block
    return result


def _nearest_grid_indices(points, grid_x, grid_y):
    """Build reusable nearest-cell indices without whole-grid coordinates."""
    from scipy.spatial import cKDTree

    tree = cKDTree(points)
    result = np.empty(len(grid_x) * len(grid_y), dtype=np.intp)
    for start, stop, query in _grid_query_blocks(grid_x, grid_y):
        _, result[start:stop] = tree.query(query)
    return result


def _grid_windows(rows, cols):
    """Yield rectangular windows bounded by the query-pixel budget."""
    width = min(cols, _QUERY_BLOCK_PIXELS)
    height = max(1, _QUERY_BLOCK_PIXELS // width)
    for row in range(0, rows, height):
        for col in range(0, cols, width):
            yield row, col, min(height, rows - row), min(width, cols - col)


def _write_interpolated_raster(
    dst, grid_x, grid_y, interpolator, fill_value, *, mesh_mask=None,
    nearest_values=None, nearest_indices=None,
):
    """Write float32 windows without allocating a full output-value raster.

    The caller retains the mesh mask and any reusable nearest-cell indices.
    Rasterio/GDAL may retain additional write and compression buffers.
    """
    shape = (len(grid_y), len(grid_x))
    indices = nearest_indices.reshape(shape) if nearest_indices is not None else None
    for row, col, height, width in _grid_windows(*shape):
        slices = (slice(row, row + height), slice(col, col + width))
        if interpolator is None:
            block = nearest_values[indices[slices]]
        else:
            query = np.empty((height, width, 2), dtype=np.float64)
            query[:, :, 0] = grid_x[col:col + width]
            query[:, :, 1] = grid_y[row:row + height, None]
            block = interpolator(query).astype(np.float32)
            block[np.isnan(block)] = fill_value
        if mesh_mask is not None:
            block[~mesh_mask[slices]] = fill_value
        dst.write(block, 1, window=((row, row + height), (col, col + width)))
