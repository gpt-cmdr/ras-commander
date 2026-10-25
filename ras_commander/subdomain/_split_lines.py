"""Normal-depth split lines and nested footprints on a native 2D mesh (pure arrays).

The numerical core of :mod:`ras_commander.subdomain`. Functions take arrays and
return arrays or plain records; nothing here reads or writes files. Distances
are in the parent's horizontal foot unit, elevations in its vertical unit, flow
in ft3/s and volumes in ft3.

Ported from fim-commander ``fim_commander.methods.pic.split_lines`` (same owner),
the method the project engineer directed on 2026-10-14. Thresholds come from a
:class:`~ras_commander.subdomain.RasSubdomain.SplitLineCriteria` instead of
module constants.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Best-slope search grid of the normal-depth fit (dimensionless).
SLOPE_GRID = tuple(float(v) for v in np.logspace(-5, -1, 81))

#: Gate failure codes of one scored line in one event.
GATES = (
    "LINE_OPEN",
    "REVERSE_FLOW",
    "NORMAL_DEPTH_RMSE",
    "NORMAL_DEPTH_PEAK",
    "NORMAL_DEPTH_LOOP",
    "SLOPE_RATIO",
    "OUTFLOW_SHARE",
    "NO_FLOW",
)


@dataclass(frozen=True)
class Mesh:
    """Native face topology of one 2D flow area.

    ``cell_0``/``cell_1`` are the face's cells (a negative id, or one at or above
    ``cell_count``, is outside the mesh); ``normal`` is the stored unit face
    normal (HEC-RAS face flow is positive from ``cell_0`` to ``cell_1``);
    ``points`` holds each face's two face-point ids into ``point_xy``.
    """

    cell_count: int
    cell_0: Any
    cell_1: Any
    normal: Any
    length: Any
    points: Any
    point_xy: Any
    midpoint: Any
    incident: Any
    incident_start: Any
    incident_stop: Any

    def faces_at(self, point: int) -> Any:
        """Faces sharing face point ``point``."""
        return self.incident[self.incident_start[point]: self.incident_stop[point]]


def mesh_from_topology(cell_count: int, face_cells: Any, normal: Any, length: Any,
                       face_points: Any, point_xy: Any) -> Mesh:
    """Build :class:`Mesh` from the native face tables of one 2D flow area."""
    face_cells = np.asarray(face_cells, np.int64)
    points = np.asarray(face_points, np.int64)
    point_xy = np.asarray(point_xy, float)
    n = len(points)
    flat = np.concatenate([points[:, 0], points[:, 1]])
    order = np.argsort(flat, kind="stable")
    incident = np.concatenate([np.arange(n), np.arange(n)])[order]
    ordered = flat[order]
    ids = np.arange(len(point_xy))
    return Mesh(
        cell_count=int(cell_count),
        cell_0=face_cells[:, 0],
        cell_1=face_cells[:, 1],
        normal=np.asarray(normal, float),
        length=np.asarray(length, float),
        points=points,
        point_xy=point_xy,
        midpoint=(point_xy[points[:, 0]] + point_xy[points[:, 1]]) / 2.0,
        incident=incident,
        incident_start=np.searchsorted(ordered, ids),
        incident_stop=np.searchsorted(ordered, ids, side="right"),
    )


def trapezoid_weights(time_s: Sequence[float]) -> Any:
    """Weights ``w`` with ``sum(w * q)`` the trapezoid integral of ``q`` over ``time_s``."""
    t = np.asarray(time_s, float)
    if t.ndim != 1 or len(t) < 2 or np.any(np.diff(t) <= 0):
        raise ValueError("the time axis must increase with at least two steps")
    w = np.zeros_like(t)
    dt = np.diff(t)
    w[:-1] += dt / 2.0
    w[1:] += dt / 2.0
    return w


def _real(mesh: Mesh, cells: Any) -> Any:
    return (cells >= 0) & (cells < mesh.cell_count)


def cells_upstream_of(mesh: Mesh, face: int, downstream: Any) -> int:
    """The cell on the upstream side of ``face`` for the unit downstream direction."""
    return int(mesh.cell_0[face] if mesh.normal[face] @ downstream > 0 else mesh.cell_1[face])


def seed_face(mesh: Mesh, stream: Any, point: Any, downstream: Any, radius: float) -> int | None:
    """The face the stream crosses nearest ``point``, most nearly perpendicular to it.

    ``stream`` is a shapely line; faces whose midpoint is within ``radius`` are
    candidates and those crossing the stream are preferred.
    """
    import shapely

    xy = np.array([point.x, point.y])
    near = np.flatnonzero(np.hypot(*(mesh.midpoint - xy).T) <= radius)
    if not near.size:
        return None
    segments = shapely.linestrings(
        np.stack([mesh.point_xy[mesh.points[near, 0]], mesh.point_xy[mesh.points[near, 1]]], 1)
    )
    crossing = near[shapely.intersects(segments, stream)]
    candidates = crossing if crossing.size else near
    score = np.abs(mesh.normal[candidates] @ downstream) - (
        np.hypot(*(mesh.midpoint[candidates] - xy).T) / 1000.0
    )
    return int(candidates[np.argmax(score)])


def grow_line(mesh: Mesh, seed: int, downstream: Any, depth: Any, volume: Any, *,
              max_angle_deg: float, wet_depth: float, edge_fraction: float,
              max_half_length: float) -> tuple[Any, Any, bool]:
    """Grow a normal-depth line across the valley from ``seed``.

    From each end, take the face sharing the end face point that is within
    ``max_angle_deg`` of perpendicular to the stream, moves outward and carries
    the largest downstream event ``volume``. Stop where both of its cells are
    under ``wet_depth`` peak ``depth`` or it carries under ``edge_fraction`` of
    the seed face's volume (a closed bank), or after ``max_half_length``.
    Returns the faces ordered bank to bank, their signs (+1 when the face normal
    points downstream) and whether both banks closed.
    """
    t = np.asarray(downstream, float)
    across = np.array([-t[1], t[0]])
    cos_max = math.cos(math.radians(max_angle_deg))
    sign = {seed: 1.0 if mesh.normal[seed] @ t > 0 else -1.0}
    seed_volume = abs(float(volume[seed]))
    center = mesh.midpoint[seed]
    a, b = mesh.points[seed]
    plus, minus = (a, b) if (mesh.point_xy[a] - center) @ across >= 0 else (b, a)
    sides: dict[int, list[int]] = {1: [], -1: []}
    closed = {}
    for side, end in ((1, plus), (-1, minus)):
        grown, closed[side] = 0.0, False
        while grown < max_half_length:
            best, best_volume, best_sign, best_other = None, 0.0, 0.0, -1
            reach = side * ((mesh.point_xy[end] - center) @ across)
            for face in mesh.faces_at(end):
                face = int(face)
                if face in sign or abs(mesh.normal[face] @ t) < cos_max:
                    continue
                p0, p1 = mesh.points[face]
                other = int(p1 if p0 == end else p0)
                if side * ((mesh.point_xy[other] - center) @ across) <= reach:
                    continue
                s = 1.0 if mesh.normal[face] @ t > 0 else -1.0
                v = s * float(volume[face])
                if v > best_volume:
                    best, best_volume, best_sign, best_other = face, v, s, other
            if best is None:
                closed[side] = True
                break
            cells = [c for c in (mesh.cell_0[best], mesh.cell_1[best]) if 0 <= c < len(depth)]
            if max((depth[c] for c in cells), default=0.0) < wet_depth or (
                best_volume < edge_fraction * seed_volume
            ):
                closed[side] = True
                break
            sides[side].append(best)
            sign[best] = best_sign
            grown += float(mesh.length[best])
            end = best_other
    ordered = [*sides[1][::-1], seed, *sides[-1]]
    return (
        np.array(ordered, np.int64),
        np.array([sign[f] for f in ordered]),
        closed[1] and closed[-1],
    )


def conveyance(tables: Mapping[int, Any], faces: Sequence[int], stages: Any, lengths: Any) -> Any:
    """``K(z) = sum (1.486/n) A R^(2/3)`` over ``faces`` at each stage (ft3/s per sqrt slope).

    ``tables[face]`` is an array of rows ``(elevation, area, wetted perimeter, n)``.
    Below a table the face is dry; above it the area grows by ``(z - top) x face length``.
    """
    k = np.zeros_like(stages, dtype=float)
    for face in faces:
        table = tables.get(int(face))
        if table is None or not len(table):
            continue
        z, area, perimeter, n = (table[:, i] for i in range(4))
        a = np.interp(stages, z, area, left=0.0, right=area[-1])
        p = np.interp(stages, z, perimeter, left=0.0, right=perimeter[-1])
        above = stages > z[-1]
        a[above] += (stages[above] - z[-1]) * float(lengths[int(face)])
        rough = np.interp(stages, z, n)
        ok = (a > 0) & (p > 0) & (rough > 0)
        k[ok] += 1.486 / rough[ok] * a[ok] * (a[ok] / p[ok]) ** (2.0 / 3.0)
    return k


def stage_grid(bed: float, stages_k: Callable[[Any], Any], *, step: float, span: float) -> tuple[Any, Any]:
    """The stage grid of a line (``bed`` up ``span`` by ``step``) and its conveyance there."""
    grid = np.arange(bed, bed + span, step)
    return grid, stages_k(grid)


def fit_window(q: Any, fraction: float) -> Any:
    """Time steps scored: flow at or above ``fraction`` of the peak."""
    q = np.asarray(q, float)
    return q >= fraction * q[int(np.argmax(q))]


def normal_depth_stage(q: Any, grid: Any, k: Any, slope: float) -> Any:
    """Normal-depth stage of flow ``q`` on the rating ``Q = K(z) sqrt(slope)``."""
    return np.interp(np.clip(np.asarray(q, float), 0, None), k * math.sqrt(slope), grid)


def score_line(flow: Any, signs: Any, weights: Any, stage: Any, bed: float,
               stages_k: Callable[[Any], Any], bed_slope: float, *, fit_fraction: float,
               stage_step: float, stage_span: float) -> dict[str, Any]:
    """Normal-depth score of one line in one event.

    ``flow`` is ``(time, face)`` native face flow, ``signs`` orients it downstream,
    ``weights`` integrate over time, ``stage`` is the WSE series of the cell above
    the seed face and ``bed`` its minimum elevation. ``stages_k(z)`` is the line's
    conveyance. Returns ``peak_flow``, ``line_volume``, ``reverse_fraction``,
    ``best_slope``, ``rmse_ft``, ``peak_error_ft``, ``loop_ft`` and ``rmse_bed_slope_ft``.
    """
    oriented = np.asarray(flow, float) * np.asarray(signs, float)
    q = oriented.sum(axis=1)
    forward = float(weights @ np.clip(oriented, 0, None).sum(axis=1))
    reverse = float(weights @ np.clip(-oriented, 0, None).sum(axis=1))
    peak = int(np.argmax(q))
    record: dict[str, Any] = {
        "peak_flow": float(q[peak]),
        "line_volume": forward - reverse,
        "reverse_fraction": reverse / (forward + reverse) if forward + reverse > 0 else None,
        "best_slope": None,
        "rmse_ft": None,
        "peak_error_ft": None,
        "loop_ft": None,
        "rmse_bed_slope_ft": None,
    }
    stage = np.asarray(stage, float)
    grid, k = stage_grid(bed, stages_k, step=stage_step, span=stage_span)
    if q[peak] <= 1.0 or not k[-1] > 0 or not np.all(np.isfinite(stage)):
        return record
    window = fit_window(q, fit_fraction)

    def rmse(error: Any) -> float:
        return float(np.sqrt(np.mean(error[window] ** 2)))

    errors = [rmse(normal_depth_stage(q, grid, k, s) - stage) for s in SLOPE_GRID]
    best = int(np.argmin(errors))
    error = normal_depth_stage(q, grid, k, SLOPE_GRID[best]) - stage
    index = np.arange(len(q))
    rise, fall = window & (index <= peak), window & (index > peak)
    record.update(
        best_slope=SLOPE_GRID[best],
        rmse_ft=errors[best],
        peak_error_ft=float(error[peak]),
        loop_ft=float(abs(error[rise].mean() - error[fall].mean())) if rise.any() and fall.any() else None,
    )
    if bed_slope > 0:
        record["rmse_bed_slope_ft"] = rmse(normal_depth_stage(q, grid, k, bed_slope) - stage)
    return record


def failed_gates(score: Mapping[str, Any], closed: bool, share: float | None, bed_slope: float, *,
                 max_reverse_fraction: float, max_fit_error_ft: float,
                 slope_ratio_bounds: tuple[float, float],
                 share_bounds: tuple[float, float]) -> list[str]:
    """Gate codes (:data:`GATES`) one scored line fails in one event; empty means it passes."""
    if score.get("best_slope") is None:
        return ["NO_FLOW"] + ([] if closed else ["LINE_OPEN"])
    failed = [] if closed else ["LINE_OPEN"]
    reverse = score.get("reverse_fraction")
    if reverse is None or reverse > max_reverse_fraction:
        failed.append("REVERSE_FLOW")
    if score["rmse_ft"] > max_fit_error_ft:
        failed.append("NORMAL_DEPTH_RMSE")
    if abs(score["peak_error_ft"]) > max_fit_error_ft:
        failed.append("NORMAL_DEPTH_PEAK")
    loop = score.get("loop_ft")
    if loop is not None and loop > max_fit_error_ft:
        failed.append("NORMAL_DEPTH_LOOP")
    low, high = slope_ratio_bounds
    if not bed_slope > 0 or not low <= score["best_slope"] / bed_slope <= high:
        failed.append("SLOPE_RATIO")
    if share is None or not share_bounds[0] <= share <= share_bounds[1]:
        failed.append("OUTFLOW_SHARE")
    return failed


def stable_step(passing: Mapping[int, bool], rmse: Mapping[int, float]) -> int | None:
    """The step passing in every event whose neighbour also passes; lowest RMSE wins."""
    stable = [
        step for step, ok in passing.items()
        if ok and (passing.get(step - 1, False) or passing.get(step + 1, False))
    ]
    if not stable:
        return None
    return min(stable, key=lambda step: (rmse[step], step))


def receivers(mesh: Mesh, volume: Any) -> Any:
    """Each cell's drainage receiver: the neighbour taking most of its event volume, or -1."""
    real = _real(mesh, mesh.cell_0) & _real(mesh, mesh.cell_1)
    faces = np.flatnonzero(real & (volume != 0))
    v = volume[faces]
    source = np.where(v > 0, mesh.cell_0[faces], mesh.cell_1[faces])
    target = np.where(v > 0, mesh.cell_1[faces], mesh.cell_0[faces])
    order = np.lexsort((-np.abs(v), source))
    source, target = source[order], target[order]
    first = np.ones(len(source), bool)
    first[1:] = source[1:] != source[:-1]
    out = np.full(mesh.cell_count, -1, np.int64)
    out[source[first]] = target[first]
    return out


def drained_cells(mesh: Mesh, receiver: Any, line: Sequence[int], downstream: Any) -> set[int]:
    """Cells whose drainage path crosses ``line`` downstream (one event's footprint)."""
    t = np.asarray(downstream, float)
    outlets = set()
    for face in set(int(f) for f in line):
        up = cells_upstream_of(mesh, face, t)
        down = int(mesh.cell_1[face] if mesh.normal[face] @ t > 0 else mesh.cell_0[face])
        if 0 <= up < mesh.cell_count and receiver[up] == down:
            outlets.add(up)
    order = np.argsort(receiver, kind="stable")
    sorted_targets = receiver[order]
    members, stack = set(outlets), list(outlets)
    while stack:
        cell = stack.pop()
        lo, hi = np.searchsorted(sorted_targets, [cell, cell + 1])
        for child in order[lo:hi]:
            child = int(child)
            if child not in members:
                members.add(child)
                stack.append(child)
    return members


def nest(footprints: Mapping[Any, set[int]], nested_fraction: float) -> dict[Any, dict[str, Any]]:
    """Nest footprints into subdomains.

    Each cell goes to the smallest footprint holding it. Footprint B is upstream
    of A when A holds at least ``nested_fraction`` of B's cells and no third
    footprint lies between them. Returns per id ``cells`` (owned), ``upstream``
    (immediate), ``tier`` and ``overlaps`` (ids sharing cells without nesting).
    """
    ids = sorted(footprints, key=lambda i: (len(footprints[i]), str(i)))
    owner: dict[int, Any] = {}
    for sid in ids:
        for cell in footprints[sid]:
            owner.setdefault(cell, sid)
    contains: dict[Any, set] = {sid: set() for sid in ids}
    overlaps: dict[Any, set] = {sid: set() for sid in ids}
    for i, small in enumerate(ids):
        for big in ids[i + 1:]:
            shared = len(footprints[small] & footprints[big])
            if not shared:
                continue
            if shared >= nested_fraction * len(footprints[small]):
                contains[big].add(small)
            else:
                overlaps[small].add(big)
                overlaps[big].add(small)
    upstream = {
        big: {s for s in inner if not any(s in contains[m] for m in inner - {s})}
        for big, inner in contains.items()
    }
    tiers: dict[Any, int] = {}
    for sid in ids:  # smaller footprints first, so upstream tiers are known
        tiers[sid] = 1 + max((tiers[u] for u in upstream[sid]), default=0)
    cells: dict[Any, set[int]] = {sid: set() for sid in ids}
    for cell, sid in owner.items():
        cells[sid].add(cell)
    return {
        sid: {"cells": cells[sid], "upstream": sorted(upstream[sid], key=str), "tier": tiers[sid],
              "overlaps": sorted(overlaps[sid], key=str)}
        for sid in ids
    }


def domain_outflow(mesh: Mesh, member: Any, volume: Any) -> float:
    """Outward event volume of a contributing area: positive net volume across its edge faces.

    ``member`` is a boolean per cell; mesh-edge faces count as edge faces.
    """
    member = np.asarray(member, bool)

    def inside(c: Any) -> Any:
        return np.where(_real(mesh, c), member[np.clip(c, 0, mesh.cell_count - 1)], False)

    a, b = inside(mesh.cell_0), inside(mesh.cell_1)
    edge = np.flatnonzero(a ^ b)
    out = volume[edge] * np.where(a[edge], 1.0, -1.0)
    return float(np.clip(out, 0, None).sum())


def edge_exchange(mesh: Mesh, cells: set[int], volume: Any, outlet: Sequence[int],
                  inlets: Sequence[int] = ()) -> dict[str, float]:
    """Event volume across a subdomain's edge, positive leaving it.

    ``outlet`` faces carry its split line, ``inlets`` the split lines of the
    subdomains upstream. Returns ``outlet_out`` (net), ``inlet_in`` (net), and
    the gross ``edge_out`` and ``edge_in`` across every other edge face, mesh
    edge included.
    """
    member = np.zeros(mesh.cell_count + 1, bool)
    member[list(cells)] = True

    def inside(c: Any) -> Any:
        return np.where(_real(mesh, c), member[np.clip(c, 0, mesh.cell_count)], False)

    a, b = inside(mesh.cell_0), inside(mesh.cell_1)
    edge = np.flatnonzero(a ^ b)
    out = volume[edge] * np.where(a[edge], 1.0, -1.0)
    is_outlet = np.isin(edge, np.asarray(list(outlet), np.int64))
    is_inlet = np.isin(edge, np.asarray(list(inlets), np.int64))
    other = ~(is_outlet | is_inlet)
    return {
        "outlet_out": float(out[is_outlet].sum()),
        "inlet_in": float(-out[is_inlet].sum()),
        "edge_out": float(np.clip(out[other], 0, None).sum()),
        "edge_in": float(np.clip(-out[other], 0, None).sum()),
    }
