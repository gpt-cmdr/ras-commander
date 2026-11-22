"""Keyhole perimeter rings for 2D flow areas with excluded areas (holes).

HEC-RAS stores one ``Storage Area Surface Line`` ring per 2D flow area. An
excluded area inside it is encoded as a keyhole: the ring runs along a cut
from the outer boundary to the hole, around the hole in the opposite
direction, and back out along the same cut. Each cut edge therefore appears
twice, once in each direction, and shapely reports the ring as an invalid
polygon. ``shapely.build_area(shapely.node(ring))`` recovers the domain, which
is how the geometry completion contract reads native rings.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

Point = tuple[float, float]


def _open_ring(coords: Sequence[Sequence[float]]) -> list[Point]:
    points = [(float(p[0]), float(p[1])) for p in coords]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in points):
        raise ValueError("Keyhole ring coordinates must be finite")
    return points


def _signed_area(points: Sequence[Point]) -> float:
    return 0.5 * sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(points, list(points[1:]) + [points[0]])
    )


def validate_keyhole_ring(coords: Sequence[Sequence[float]], tolerance: float = 1e-9):
    """Return the domain polygon of a proper keyhole ring, or raise ValueError.

    A proper keyhole ring is a closed ring whose only non-simple parts are cut
    edges that appear exactly twice, once in each direction. The remaining
    edges must form the boundary of one polygon with holes, without crossings
    or overlaps. Every cut edge must lie inside that polygon. The cuts must
    form one connecting path per hole, ending on boundary vertices, so a
    dangling spur, a cut that splits the domain, or a cut outside it is rejected.
    """
    import shapely
    from shapely.geometry import LineString, MultiLineString
    from shapely.geometry import Point as ShapelyPoint

    points = _open_ring(coords)
    n = len(points)
    if n < 3:
        raise ValueError("Keyhole ring needs at least three vertices")
    segments = [(points[i], points[(i + 1) % n]) for i in range(n)]
    if any(a == b for a, b in segments):
        raise ValueError("Keyhole ring has a zero-length edge")

    directions: dict[frozenset, list[tuple[Point, Point]]] = defaultdict(list)
    for a, b in segments:
        directions[frozenset((a, b))].append((a, b))
    cuts, boundary = [], []
    for uses in directions.values():
        if len(uses) == 1:
            boundary.append(uses[0])
        elif len(uses) == 2 and uses[0] == (uses[1][1], uses[1][0]):
            cuts.append(uses[0])
        else:
            raise ValueError(
                "Keyhole ring repeats an edge other than as a cut traversed once "
                "in each direction"
            )
    if not cuts:
        raise ValueError("Ring has no doubled cut edge; it is not a keyhole ring")

    unique = MultiLineString([list(s) for s in boundary + cuts])
    noded = shapely.get_num_geometries(shapely.node(unique))
    if noded != len(boundary) + len(cuts):
        raise ValueError("Keyhole ring edges cross or overlap")

    domain = shapely.build_area(MultiLineString([list(s) for s in boundary]))
    if domain.geom_type != "Polygon" or domain.is_empty or not domain.is_valid:
        raise ValueError("Keyhole ring boundary edges do not form one valid polygon")
    if len(domain.interiors) == 0:
        raise ValueError("Keyhole ring encloses no excluded area")
    leftover = MultiLineString([list(s) for s in boundary]).difference(domain.boundary)
    if leftover.length > tolerance:
        raise ValueError("Keyhole ring has boundary edges outside the domain boundary")

    for a, b in cuts:
        if not domain.contains(LineString([a, b]).interpolate(0.5, normalized=True)):
            raise ValueError("Keyhole cut edge lies outside the 2D flow area")

    boundary_vertices = {p for s in boundary for p in s}
    adjacency: dict[Point, set] = defaultdict(set)
    for a, b in cuts:
        adjacency[a].add(b)
        adjacency[b].add(a)
    seen, components = set(), 0
    for start in adjacency:
        if start in seen:
            continue
        components += 1
        stack = [start]
        while stack:
            vertex = stack.pop()
            if vertex in seen:
                continue
            seen.add(vertex)
            stack.extend(adjacency[vertex] - seen)
    for vertex, neighbours in adjacency.items():
        if len(neighbours) == 1 and vertex not in boundary_vertices:
            raise ValueError("Keyhole ring has a dangling cut that reaches no hole")
    if components != len(domain.interiors):
        raise ValueError(
            f"Keyhole ring has {components} cut path(s) for "
            f"{len(domain.interiors)} excluded area(s)"
        )
    native = shapely.build_area(shapely.node(LineString(points + [points[0]])))
    if not native.equals(domain):
        raise ValueError("Keyhole ring domain is ambiguous")
    if not ShapelyPoint(points[0]).within(domain.exterior.buffer(tolerance)):
        # Start on the outer boundary so a reader that takes the first vertex
        # as an exterior point does not start inside a hole.
        raise ValueError("Keyhole ring must start on the outer boundary")
    return domain


def build_keyhole_ring(
    outer: Sequence[Sequence[float]], holes: Sequence[Sequence[Sequence[float]]]
) -> list[Point]:
    """Build a closed keyhole ring from an outer ring and hole rings.

    Each hole is joined by one straight cut between the nearest vertex pair
    whose segment stays inside the domain and crosses no boundary or earlier
    cut. Holes run opposite to the outer ring, so the ring's signed area is the
    domain area. The ring starts at the first outer vertex.
    """
    import shapely
    from shapely.geometry import LineString, Polygon

    outer_points = _open_ring(outer)
    hole_points = [_open_ring(hole) for hole in holes]
    if not hole_points:
        raise ValueError("At least one hole ring is required")
    domain = Polygon(outer_points, hole_points)
    if not domain.is_valid:
        raise ValueError(
            "Outer and hole rings do not form a valid polygon: "
            + shapely.is_valid_reason(domain)
        )
    outer_sign = math.copysign(1.0, _signed_area(outer_points))
    oriented = []
    for hole in hole_points:
        if math.copysign(1.0, _signed_area(hole)) == outer_sign:
            hole = list(reversed(hole))
        oriented.append(hole)

    ring = list(outer_points)
    cuts: list[LineString] = []
    boundary = shapely.union_all([domain.boundary])
    shapely.prepare(domain)
    remaining = list(range(len(oriented)))
    while remaining:
        best = None
        counts: dict[Point, int] = defaultdict(int)
        for p in ring:
            counts[p] += 1
        anchors = [i for i, p in enumerate(ring) if counts[p] == 1 and i != 0]
        for h in remaining:
            hole = oriented[h]
            for i in anchors:
                a = ring[i]
                for j, b in enumerate(hole):
                    d = math.dist(a, b)
                    if best is not None and d >= best[0]:
                        continue
                    cut = LineString([a, b])
                    if not domain.covers(cut):
                        continue
                    touches = cut.intersection(boundary)
                    if not touches.equals(shapely.multipoints([a, b])):
                        continue
                    if any(cut.crosses(c) or cut.overlaps(c) for c in cuts):
                        continue
                    best = (d, h, i, j)
        if best is None:
            raise ValueError("No straight cut joins a hole to the boundary inside the area")
        _, h, i, j = best
        hole = oriented[h]
        loop = hole[j:] + hole[:j] + [hole[j]]
        ring = ring[: i + 1] + loop + [ring[i]] + ring[i + 1 :]
        cuts.append(LineString([ring[i], hole[j]]))
        remaining.remove(h)
    validate_keyhole_ring(ring)
    return ring + [ring[0]]
