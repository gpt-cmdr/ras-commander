"""Explicit AOI edge rule on the source terrain lattice, without an epsilon.

Coordinates use pixel units with y increasing northward. Centers are
``(col + .5, -row - .5)``. Even-odd scanlines include lower-y/exclude upper-y
endpoints and fill left-inclusive/right-exclusive spans. Crop offsets affect
only which samples are emitted, never edge-intersection arithmetic.
"""
import math
import numpy as np

METHOD = "global-terrain-lattice/1"


def index_range(lo, hi, origin, step, count):
    lower, upper = (lo - origin) / abs(step), (hi - origin) / abs(step)
    if step > 0:
        start, stop = math.ceil(lower - .5), math.ceil(upper - .5)
    else:
        start, stop = math.floor(-upper - .5) + 1, math.floor(-lower - .5) + 1
    return max(0, min(count, start)), max(0, min(count, stop))


def mask(geometry, transform, window):
    """NumPy reference for the native global-terrain-lattice/1 mask."""
    import shapely
    coords, indices = shapely.get_coordinates(shapely.get_rings(shapely.get_parts(geometry)), return_index=True)
    coords[:, 0] = (coords[:, 0] - transform.c) / transform.a
    coords[:, 1] = (coords[:, 1] - transform.f) / -transform.e
    if not np.isfinite(coords).all() or (np.abs(coords) > 2**52).any():
        raise ValueError("AOI exceeds exact pixel-index range")
    edges = []
    for label in np.unique(indices):
        ring = coords[indices == label]
        for a, b in zip(ring[:-1], ring[1:]):
            if a[1] != b[1]:
                edges.append((a, b) if a[1] < b[1] else (b, a))
    col, row, width, height = map(int, window.flatten())
    result = np.zeros((height, width), dtype=bool)
    if not edges:
        return result
    a, b = np.asarray(edges).transpose(1, 0, 2)
    for r in range(height):
        y = -(row + r + .5)
        active = (a[:, 1] <= y) & (y < b[:, 1])
        p, q = a[active], b[active]
        crosses = np.sort(p[:, 0] + ((y - p[:, 1]) / (q[:, 1] - p[:, 1])) * (q[:, 0] - p[:, 0]))
        for left, right in crosses.reshape(-1, 2):
            first = max(col, min(col + width, math.ceil(left - .5))) - col
            last = max(col, min(col + width, math.ceil(right - .5))) - col
            result[r, first:last] = True
    return result
