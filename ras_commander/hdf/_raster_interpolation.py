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


def _interpolate_to_grid(points, values, grid_x, grid_y, method, fill_value):
    """Build one SciPy interpolator and fill a float32 raster in blocks.

    The output remains an in-memory array. Query coordinates and interpolation
    temporaries are limited to ``_QUERY_BLOCK_PIXELS`` pixels per evaluation;
    the triangulation or search tree still scales with the input points.
    """
    from scipy.interpolate import (
        CloughTocher2DInterpolator,
        LinearNDInterpolator,
        NearestNDInterpolator,
    )

    if method == "nearest":
        interpolator = NearestNDInterpolator(points, values)
    elif method == "linear":
        interpolator = LinearNDInterpolator(points, values, fill_value=fill_value)
    elif method == "cubic":
        interpolator = CloughTocher2DInterpolator(points, values, fill_value=fill_value)
    else:
        raise ValueError(f"Unknown interpolation method {method!r} for 2 dimensional data")

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
