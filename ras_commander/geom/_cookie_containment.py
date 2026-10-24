"""Bounded perimeter preparation for native cookie faces crossing concavities."""

from __future__ import annotations

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union


def _plan_face_containment_perimeter(perimeter, faces, cell_size):
    """Contain complete face polylines by adding bounded local wedges.

    Inputs and returned coordinates retain the projected source CRS/units.
    Planning is read-only. This changes the construction, never the native
    completion predicate. Material protrusions or lost domain remain errors.
    """
    if (
        perimeter.geom_type != "Polygon"
        or perimeter.interiors
        or not perimeter.is_valid
    ):
        raise ValueError(
            "Cookie face preparation requires one valid hole-free perimeter"
        )
    if not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError(
            "Cookie face preparation requires positive finite cell spacing"
        )
    xy = np.asarray(perimeter.exterior.coords)
    origin = xy[0]
    guard = 8 * np.spacing(max(1.0, float(np.max(np.abs(xy)))))
    local = affinity.translate(perimeter, -origin[0], -origin[1])
    shifted = local.buffer(guard)
    local_faces = [affinity.translate(line, -origin[0], -origin[1]) for line in faces]
    bad = [line for line in local_faces if not shifted.covers(line)]
    if not bad:
        raise ValueError("No compiled face containment failure was reproduced")
    limit = min(1.0, float(cell_size) * 0.005)
    revised = local
    for line in bad:
        support = local.intersection(line.buffer(limit / 2, cap_style=2, join_style=2))
        patch = unary_union([support, line]).convex_hull
        candidate = revised.union(patch)
        if candidate.geom_type != "Polygon" or not candidate.is_valid:
            raise ValueError("Cookie face preparation would split the domain")
        # A chord can bridge a small re-entrant wedge. Fill only the holes this
        # preparation introduces; the input contract excludes existing holes.
        revised = Polygon(candidate.exterior)
    lost = float(local.difference(revised).area)
    gain = float(revised.difference(local).area)
    if lost or gain / local.area > 0.001 or not local.buffer(limit).covers(revised):
        raise ValueError(
            "Cookie face perimeter preparation exceeds its displacement/area bounds"
        )
    if not all(revised.covers(line) for line in bad):
        raise ValueError("Prepared perimeter does not cover every offending full face")
    global_revised = affinity.translate(revised, origin[0], origin[1])
    return global_revised, {
        "schema": "ras-cookie-face-perimeter-preparation/v1",
        "reason_code": "COOKIE_FACE_CONCAVITY_WEDGE_PREPARATION",
        "offending_face_count": len(bad),
        "maximum_displacement": limit,
        "maximum_area_gain_fraction": 0.001,
        "area_gained": gain,
        "area_gained_fraction": gain / local.area,
        "area_lost": lost,
        "coordinate_roundtrip_area_lost": float(
            perimeter.difference(global_revised).area
        ),
        "coordinate_origin": origin.tolist(),
        "horizontal_units": "source_horizontal_units",
        "native_completion_check_unchanged": True,
    }
