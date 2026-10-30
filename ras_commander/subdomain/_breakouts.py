"""Breakout authoring, execution and comparison for hydraulic subdomains.

Builds on :class:`RasBreakout2D` (clone and exact cell-subset cut),
:meth:`GeomBcLines.replace_bc_lines` (BC lines with their forcing), and
:meth:`RasCmdr.compute_parallel`. The parent project is never modified: every
child is a cloned plan, geometry and unsteady file inside one staged working
copy of the parent.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..LoggingConfig import get_logger
from ..fast_hdf import release_native_sessions

logger = get_logger(__name__)

#: BC line role names (written into the BC line name prefix).
OUTLET, INFLOW, PERIMETER, CLOSED_EDGE = "outlet", "inflow", "perimeter", "closed_edge_outflow"
_NAME = {OUTLET: "Out_ND", INFLOW: "In", PERIMETER: "Edge_ND", CLOSED_EDGE: "Edge_Out"}
#: Default friction slope of optional closed-edge outflow lines: a conservative minimum
#: that keeps the boundary stable while letting water leave across the subdomain divide.
CLOSED_EDGE_FRICTION_SLOPE = 0.00033
#: Labels :meth:`RasSubdomain.plan_breakouts` cannot build in this release.
BLOCKING_LABELS = ("HOLES", "MULTIPART", "STRUCTURE_ON_SPLIT_LINE")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(16 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _check(rows: List[dict], subdomain: str, check: str, passed: bool, detail: str, blocking: bool = True):
    rows.append({"subdomain_id": subdomain, "check": check, "passed": bool(passed),
                 "blocking": bool(blocking and not passed), "detail": detail})


@dataclass(frozen=True)
class SubdomainBreakout:
    """One planned breakout: the parent cells it keeps and the BC lines it gets."""

    subdomain_id: str
    tier: int
    parent_cell_ids: Tuple[int, ...]
    child_boundary: Any  # shapely Polygon in the parent CRS
    bc_lines: Tuple[Dict[str, Any], ...]
    upstream_subdomain_ids: Tuple[str, ...]
    outlet_split_line_id: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subdomain_id": self.subdomain_id, "tier": self.tier,
            "parent_cell_count": len(self.parent_cell_ids),
            "upstream_subdomain_ids": list(self.upstream_subdomain_ids),
            "outlet_split_line_id": self.outlet_split_line_id,
            "bc_lines": [{k: v for k, v in b.items() if k not in ("coordinates", "hydrograph_df")}
                         for b in self.bc_lines],
        }


@dataclass(frozen=True)
class SubdomainBreakoutPlan:
    """Read-only plan of :meth:`RasSubdomain.plan_breakouts`.

    ``checks`` uses the ``ras_breakout_2d_checks`` columns plus ``subdomain_id``.
    ``is_ready`` is False while any blocking check fails for a planned subdomain.
    """

    breakouts: Tuple[SubdomainBreakout, ...]
    checks: Any
    plan_number: str
    mesh_name: str
    project_folder: Path
    parent_identities: Dict[str, str]
    perimeter_friction_slope: float
    partition: Any = field(repr=False)
    ras_object: Any = field(default=None, repr=False)
    closed_edge_outflow: bool = False
    closed_edge_friction_slope: float = CLOSED_EDGE_FRICTION_SLOPE
    boundary_gap_cells: int = 2
    schema: str = "ras-subdomain-breakout-plan/1"

    @property
    def is_ready(self) -> bool:
        return not bool(self.checks["blocking"].any()) if len(self.checks) else True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "plan_number": self.plan_number, "mesh_name": self.mesh_name,
            "project_folder": str(self.project_folder), "is_ready": self.is_ready,
            "parent_identities": dict(self.parent_identities),
            "perimeter_friction_slope": self.perimeter_friction_slope,
            "closed_edge_outflow": self.closed_edge_outflow,
            "closed_edge_friction_slope": self.closed_edge_friction_slope,
            "boundary_gap_cells": self.boundary_gap_cells,
            "breakouts": [b.to_dict() for b in self.breakouts],
            "checks": self.checks.to_dict("records"),
        }


@dataclass(frozen=True)
class SubdomainBreakoutSet:
    """Authored breakouts in one staged working project (:meth:`RasSubdomain.apply_breakouts`).

    ``children`` has one row per subdomain: ``subdomain_id``, ``tier``,
    ``plan_number``, ``geometry_number``, ``unsteady_number``, ``geometry_path``,
    ``unsteady_path``, ``plan_path``.
    """

    plan: SubdomainBreakoutPlan
    project_folder: Path
    children: Any
    ras_object: Any = field(repr=False)
    preparation: Dict[str, Any] = field(default_factory=dict, repr=False)
    schema: str = "ras-subdomain-breakout-set/1"

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": self.schema, "project_folder": str(self.project_folder),
                "children": self.children.astype(str).to_dict("records"),
                "plan": self.plan.to_dict()}


# --- planning ------------------------------------------------------------------------------


#: Cell polygons along the parent perimeter differ from it by float noise (~1e-9 ft).
_CONTAINMENT_TOL = 1e-3
#: Vertices within this distance of the parent perimeter lie on it (horizontal units).
_ON_PERIMETER_TOL = 0.01


def _perimeter_stretches(child, parent_area) -> List[Any]:
    """Contiguous stretches of the child's exterior that run along the parent perimeter."""
    import shapely
    from shapely.geometry import LineString

    ring = np.asarray(child.exterior.coords)[:-1]
    boundary = parent_area.exterior
    on = shapely.distance(shapely.points(ring), boundary) < _ON_PERIMETER_TOL
    nxt = np.roll(ring, -1, axis=0)
    mid = shapely.distance(shapely.points((ring + nxt) / 2.0), boundary) < _ON_PERIMETER_TOL
    seg = on & np.roll(on, -1) & mid  # segment i runs from vertex i to vertex i+1
    if seg.all():
        return [LineString(np.vstack([ring, ring[:1]]))]
    if not seg.any():
        return []
    start = int(np.flatnonzero(~seg)[0]) + 1  # begin just after an off-perimeter segment
    order = [(start + k) % len(ring) for k in range(len(ring))]
    stretches, current = [], []
    for i in order:
        if seg[i]:
            if not current:
                current = [ring[i]]
            current.append(nxt[i])
        elif current:
            stretches.append(LineString(current))
            current = []
    if current:
        stretches.append(LineString(current))
    return [g for g in stretches if g.length > 0]




def _closed_edge_stretches(child, parent_area, split_lines: Sequence[Any], gap_cells: int) -> List[Any]:
    """Stretches of the child's exterior that are neither parent perimeter nor a split line.

    These are the faces a cut turns into walls (the divide with a neighbouring
    subdomain). Each stretch is shortened by ``gap_cells`` exterior segments (one
    segment is one cell face) at both ends, so it keeps that many cells away along
    the perimeter from the outlet, inflow and perimeter lines it meets and no
    two BC lines can claim the same face.
    """
    import shapely
    from shapely.geometry import LineString

    ring = np.asarray(child.exterior.coords)[:-1]
    nxt = np.roll(ring, -1, axis=0)
    mid = shapely.points((ring + nxt) / 2.0)
    boundary = parent_area.exterior
    on_parent = (shapely.distance(shapely.points(ring), boundary) < _ON_PERIMETER_TOL)         & (shapely.distance(shapely.points(nxt), boundary) < _ON_PERIMETER_TOL)         & (shapely.distance(mid, boundary) < _ON_PERIMETER_TOL)
    on_split = np.zeros(len(ring), bool)
    for line in split_lines:
        on_split |= shapely.distance(mid, line) < _ON_PERIMETER_TOL
    closed = ~on_parent & ~on_split
    if closed.all() or not closed.any():
        return []
    start = int(np.flatnonzero(~closed)[0]) + 1
    runs, current = [], []
    for k in range(len(ring)):
        i = (start + k) % len(ring)
        if closed[i]:
            current.append(i)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    stretches = []
    for run in runs:
        kept = run[gap_cells: len(run) - gap_cells] if gap_cells else run
        if kept:
            coords = [ring[kept[0]]] + [nxt[i] for i in kept]
            stretches.append(LineString(coords))
    return [g for g in stretches if g.length > 0]


def _merge_faces(mesh, faces: Sequence[int]):
    """Merged LineString(s) along the given parent faces."""
    import shapely

    segs = [mesh.point_xy[mesh.points[int(f)]] for f in faces]
    merged = shapely.line_merge(shapely.MultiLineString(segs))
    return list(getattr(merged, "geoms", [merged]))


def _plan_event(search, plan_row, project_name: str) -> Optional[str]:
    """The search event that is the parent run of ``plan_row``, or None.

    The plan's own results HDF counts if the search used it. Otherwise an event
    matches when its plan HDF was forced by the plan's unsteady flow file.
    """
    import h5py

    plan_hdf = plan_row.get("HDF_Results_Path")
    if isinstance(plan_hdf, (str, Path)) and str(plan_hdf) and Path(plan_hdf).is_file():
        resolved = Path(plan_hdf).resolve()
        if resolved in search.plan_hdf_paths:
            return search.events[search.plan_hdf_paths.index(resolved)]
    unsteady = plan_row.get("unsteady_number")
    if unsteady is None or (isinstance(unsteady, float) and math.isnan(unsteady)):
        return None
    flow_file = f"{project_name}.u{str(unsteady).zfill(2)}".lower()
    matches = []
    for event, path in zip(search.events, search.plan_hdf_paths):
        with h5py.File(path, "r") as f:
            info = f.get("Plan Data/Plan Information")
            name = info.attrs.get("Flow Filename", b"") if info is not None else b""
        name = name.decode() if isinstance(name, bytes) else str(name)
        if Path(name).name.lower() == flow_file:
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


def _parent_hydrograph(search, faces: Sequence[int], signs: Sequence[float], event: str):
    """Parent's signed flow across ``faces`` in ``event`` as an ``hour``/``value`` frame."""
    import pandas as pd

    from ._parent import EventReader

    path = search.plan_hdf_paths[search.events.index(event)]
    reader = EventReader(path, search.mesh_name)
    ids, flow = reader.series("Face Flow", faces)
    col = {int(f): i for i, f in enumerate(ids)}
    q = (flow[:, [col[int(f)] for f in faces]] * np.asarray(signs, float)).sum(axis=1)
    hours = reader.seconds() / 3600.0
    return pd.DataFrame({"hour": hours, "value": np.clip(q, 0.0, None)})


def plan_breakouts(partition, plan_number, *, ras_object, perimeter_friction_slope: float = 0.01,
                   subdomain_ids: Optional[Sequence[str]] = None, closed_edge_outflow: bool = False,
                   closed_edge_friction_slope: float = CLOSED_EDGE_FRICTION_SLOPE,
                   boundary_gap_cells: int = 2) -> SubdomainBreakoutPlan:
    import pandas as pd
    import shapely

    from ..RasBreakout2D import Breakout2DSpec, RasBreakout2D
    from ..RasUtils import RasUtils

    if not (math.isfinite(perimeter_friction_slope) and perimeter_friction_slope > 0):
        raise ValueError("perimeter_friction_slope must be a finite positive slope")
    if not (math.isfinite(closed_edge_friction_slope) and closed_edge_friction_slope > 0):
        raise ValueError("closed_edge_friction_slope must be a finite positive slope")
    if isinstance(boundary_gap_cells, bool) or not isinstance(boundary_gap_cells, int) or boundary_gap_cells < 1:
        raise ValueError("boundary_gap_cells must be a positive integer")
    ras_object.check_initialized()
    plan_number = RasUtils.normalize_ras_number(plan_number)
    search = partition.search
    ctx = search._context
    mesh, geometry = ctx["mesh"], ctx["geometry"]
    lines = ctx["lines"]
    subs = partition.subdomains.set_index("subdomain_id")
    wanted = list(subs.index) if subdomain_ids is None else [str(s) for s in subdomain_ids]
    unknown = set(wanted) - set(subs.index)
    if unknown:
        raise ValueError(f"unknown subdomain_ids {sorted(unknown)}")
    owner = partition.cell_owner
    rows: List[dict] = []
    plan_row = ras_object.plan_df[ras_object.plan_df["plan_number"].astype(str) == plan_number]
    if len(plan_row) != 1:
        raise ValueError(f"plan {plan_number} not found in the project")
    plan_hdf = plan_row.iloc[0].get("HDF_Results_Path")
    identities = {}
    # plan_df holds NaN (not None) when the plan has no results file.
    if isinstance(plan_hdf, (str, Path)) and str(plan_hdf) and Path(plan_hdf).is_file():
        same = Path(plan_hdf).resolve() in set(search.plan_hdf_paths)
        identities["plan_hdf_is_search_event"] = str(same)
    geom_number = str(plan_row.iloc[0]["geometry_number"]).zfill(2)
    geom_row = ras_object.geom_df[ras_object.geom_df["geom_number"].astype(str).str.zfill(2) == geom_number]
    geom_hdf = Path(str(geom_row.iloc[0]["hdf_path"])) if len(geom_row) else None
    if geom_hdf is not None and geom_hdf.is_file():
        from ._parent import read_geometry, same_geometry

        identities["geometry_hdf_sha256"] = _sha(geom_hdf)
        matches = same_geometry(geometry, read_geometry(geom_hdf, search.mesh_name))
        _check(rows, "*", "parent_geometry_matches_search", matches,
               f"{geom_hdf.name} {'matches' if matches else 'differs from'} the searched mesh")
    else:
        _check(rows, "*", "parent_geometry_matches_search", False, f"geometry HDF for g{geom_number} not found")
    for p, h in zip(search.plan_hdf_paths, search.plan_hdf_sha256):
        identities[f"search_event:{p.name}"] = h
    # Inflow lines carry the parent's hydrograph from the run of this same plan.
    forcing_event = _plan_event(search, plan_row.iloc[0], ras_object.project_name)
    needs_inflow = [s for s in wanted if len(subs.loc[s, "upstream_subdomain_ids"])]
    if needs_inflow:
        _check(rows, "*", "inflow_event_matches_plan", forcing_event is not None,
               f"inflow hydrographs from search event {forcing_event}" if forcing_event is not None else
               f"no search event was forced by plan {plan_number}'s unsteady file; inflow lines need "
               f"the parent run of plan {plan_number} among the search's plan HDFs")

    from ..hdf.HdfMesh import HdfMesh

    areas = HdfMesh.get_mesh_areas(search.plan_hdf_paths[0])
    parent_area = areas[areas["mesh_name"].astype(str) == search.mesh_name].geometry.iloc[0]
    # Parent perimeter faces: one side is a ghost cell.
    a, b = mesh.cell_0, mesh.cell_1
    real_a = (a >= 0) & (a < mesh.cell_count)
    real_b = (b >= 0) & (b < mesh.cell_count)
    breakouts = []
    for sid in wanted:
        sub = subs.loc[sid]
        labels = list(sub["labels"])
        cells = owner.loc[owner["subdomain_id"] == sid, "cell_id"].to_numpy(int)
        member = np.zeros(mesh.cell_count + 1, bool)
        member[cells] = True
        in_a = real_a & member[np.clip(a, 0, mesh.cell_count)]
        in_b = real_b & member[np.clip(b, 0, mesh.cell_count)]
        edge = np.flatnonzero(in_a ^ in_b)
        on_parent_perimeter = edge[~(real_a[edge] & real_b[edge])]
        for label in BLOCKING_LABELS:
            if label in labels:
                _check(rows, sid, f"label:{label}", False,
                       f"{label}: cannot be cut as one exact-cell child in this release")
        geom = sub.geometry
        poly = geom if geom.geom_type == "Polygon" else None
        _check(rows, sid, "single_polygon_boundary", poly is not None and not poly.interiors,
               f"child boundary is {geom.geom_type} with "
               f"{sum(len(p.interiors) for p in getattr(geom, 'geoms', [geom]))} holes")

        bc: List[Dict[str, Any]] = []
        outlet_id = sub["split_line_id"] if sid != partition.remainder_id else None
        outlet_id = None if outlet_id is None or (isinstance(outlet_id, float) and math.isnan(outlet_id)) else int(outlet_id)
        if outlet_id is not None:
            s = lines[outlet_id]
            slope = float(np.mean([v for k, v in partition.search.split_lines.set_index("split_line_id")
                                   .loc[outlet_id].items() if k.startswith("best_slope_") and v]))
            for i, g in enumerate(_merge_faces(mesh, s["faces"])):
                bc.append({"role": OUTLET, "name": f"{_NAME[OUTLET]}_{sid}"[:32] + (f"_{i}" if i else ""),
                           "bc_type": "Normal Depth", "friction_slope": slope,
                           "coordinates": np.asarray(g.coords), "split_line_id": outlet_id})
        for up in sub["upstream_subdomain_ids"] if forcing_event is not None else ():
            up_line = int(subs.loc[up, "split_line_id"])
            s = lines[up_line]
            hydro = _parent_hydrograph(search, s["faces"], s["signs"], forcing_event)
            for i, g in enumerate(_merge_faces(mesh, s["faces"])):
                bc.append({"role": INFLOW, "name": f"{_NAME[INFLOW]}_{up}"[:32] + (f"_{i}" if i else ""),
                           "bc_type": "Flow Hydrograph", "friction_slope": perimeter_friction_slope,
                           "hydrograph_df": hydro, "coordinates": np.asarray(g.coords),
                           "upstream_subdomain_id": up, "split_line_id": up_line,
                           "hydrograph_source": "parent", "hydrograph_event": forcing_event})
        if len(on_parent_perimeter) and poly is not None:
            pieces = _perimeter_stretches(poly, parent_area)
            for i, g in enumerate(sorted(pieces, key=lambda g: -g.length)):
                bc.append({"role": PERIMETER, "name": f"{_NAME[PERIMETER]}_{i + 1}",
                           "bc_type": "Normal Depth", "friction_slope": perimeter_friction_slope,
                           "coordinates": np.asarray(g.coords)})
        if closed_edge_outflow and poly is not None:
            split = [shapely.LineString(np.asarray(x["coordinates"])) for x in bc if x["role"] in (OUTLET, INFLOW)]
            for i, g in enumerate(sorted(_closed_edge_stretches(poly, parent_area, split, boundary_gap_cells),
                                         key=lambda g: -g.length)):
                bc.append({"role": CLOSED_EDGE, "name": f"{_NAME[CLOSED_EDGE]}_{i + 1}",
                           "bc_type": "Normal Depth", "friction_slope": closed_edge_friction_slope,
                           "coordinates": np.asarray(g.coords)})
        _check(rows, sid, "has_outflow_boundary", any(x["role"] in (OUTLET, PERIMETER) for x in bc),
               f"{sum(x['role'] == OUTLET for x in bc)} outlet and "
               f"{sum(x['role'] == PERIMETER for x in bc)} perimeter and "
               f"{sum(x['role'] == CLOSED_EDGE for x in bc)} closed-edge outflow normal-depth lines")
        if poly is not None:
            spec = Breakout2DSpec(source_plan=plan_number, source_2d_area=search.mesh_name,
                                  child_boundary=poly, breakout_id=f"sd_{sid}"[:32],
                                  child_boundary_crs=search.split_lines.crs,
                                  containment_tolerance=_CONTAINMENT_TOL)
            try:
                pre = RasBreakout2D.preflight(spec, ras_object=ras_object)
                _check(rows, sid, "breakout_preflight", pre.is_ready, "; ".join(pre.blocking_issues) or "ready")
            except Exception as exc:  # report, do not raise: the plan collects every refusal
                _check(rows, sid, "breakout_preflight", False, f"{type(exc).__name__}: {exc}")
        breakouts.append(SubdomainBreakout(
            subdomain_id=sid, tier=int(sub["tier"]), parent_cell_ids=tuple(int(c) for c in cells),
            child_boundary=geom, bc_lines=tuple(bc),
            upstream_subdomain_ids=tuple(str(u) for u in sub["upstream_subdomain_ids"]),
            outlet_split_line_id=outlet_id))
    checks = pd.DataFrame(rows, columns=["subdomain_id", "check", "passed", "blocking", "detail"])
    return SubdomainBreakoutPlan(
        breakouts=tuple(breakouts), checks=checks, plan_number=plan_number,
        mesh_name=search.mesh_name, project_folder=Path(ras_object.project_folder),
        parent_identities=identities, perimeter_friction_slope=float(perimeter_friction_slope),
        partition=partition, ras_object=ras_object, closed_edge_outflow=bool(closed_edge_outflow),
        closed_edge_friction_slope=float(closed_edge_friction_slope), boundary_gap_cells=int(boundary_gap_cells))


# --- applying ------------------------------------------------------------------------------


def _bc_dicts(breakout: SubdomainBreakout) -> List[Dict[str, Any]]:
    out = []
    for b in breakout.bc_lines:
        d = {"name": b["name"], "coordinates": [tuple(map(float, xy[:2])) for xy in b["coordinates"]],
             "bc_type": b["bc_type"], "friction_slope": float(b["friction_slope"])}
        if "hydrograph_df" in b:
            d["hydrograph_df"] = b["hydrograph_df"]
        out.append(d)
    return out


#: BC line placement variants, tried in order until HEC-RAS attaches each line to
#: the intended perimeter faces (ported from the Salt Draw authoring loop).
_PLACEMENTS = ("on perimeter", "offset 1 ft, ends trimmed 10 ft", "offset 1 ft, extended 50 ft",
               "along perimeter +200 ft", "along perimeter +400 ft", "along perimeter +800 ft")
_BC_MESSAGE = re.compile(r"BC Line '([^']+)' appears to be")


def _placement_variants(coords, child, perimeter_ring) -> List[Tuple[str, Any]]:
    from shapely.geometry import LineString, Point
    from shapely.ops import substring

    c = np.asarray(coords, float)

    def outward(pts, d=1.0):
        line = LineString(pts)
        for side in (d, -d):
            off = line.offset_curve(side)
            if off.is_empty or off.geom_type != "LineString":
                continue
            if not child.contains(off.interpolate(0.5, normalized=True)):
                return np.asarray(off.coords)
        return pts

    def trimmed(pts, t):
        line = LineString(pts)
        return np.asarray(substring(line, t, line.length - t).coords) if line.length > 4 * t else pts

    def extended(pts, e):
        d0 = (pts[0] - pts[1]) / np.linalg.norm(pts[0] - pts[1])
        d1 = (pts[-1] - pts[-2]) / np.linalg.norm(pts[-1] - pts[-2])
        return np.vstack([pts[0] + d0 * e, pts, pts[-1] + d1 * e])

    def along(pts, e):
        length = perimeter_ring.length
        a = perimeter_ring.project(Point(*pts[0]))
        b = perimeter_ring.project(Point(*pts[-1]))
        a, b = sorted((a, b))
        if b - a > length / 2:
            a, b = b, a + length
        ss = np.linspace(a - e, b + e, max(int((b - a + 2 * e) / 5.0), 2) + 1)
        return outward(np.asarray([perimeter_ring.interpolate(v % length).coords[0] for v in ss]))

    return [("on perimeter", c), ("offset 1 ft, ends trimmed 10 ft", trimmed(outward(c), 10.0)),
            ("offset 1 ft, extended 50 ft", extended(outward(c), 50.0)),
            *[(f"along perimeter +{e:g} ft", along(c, e)) for e in (200.0, 400.0, 800.0)]]


def _compiled_line_faces(tmp_hdf: Path) -> Tuple[Dict[str, int], set]:
    """External faces per BC line in a preprocessed plan HDF, and lines that share a face."""
    import h5py

    if not tmp_hdf.is_file():
        return {}, set()
    with h5py.File(tmp_hdf, "r") as f:
        if "Geometry/Boundary Condition Lines/External Faces" not in f:
            return {}, set()
    from ..hdf.HdfBndry import HdfBndry

    faces = HdfBndry.get_bc_external_faces(tmp_hdf, on_duplicate_ownership="report")
    if not len(faces):
        return {}, set()
    shared = set(faces.loc[faces["duplicate_ownership"].astype(bool), "bc_line_name"].astype(str))         if "duplicate_ownership" in faces.columns else set()
    return faces.groupby("bc_line_name").size().to_dict(), shared


def _compute_messages(plan_hdf: Path) -> str:
    import h5py

    if not plan_hdf.is_file():
        return ""
    with h5py.File(plan_hdf, "r") as f:
        d = f.get("Results/Summary/Compute Messages (text)")
        if d is None:
            return ""
        raw = d[()]
        raw = raw[0] if hasattr(raw, "__len__") and not isinstance(raw, (bytes, str)) else raw
        return raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)


def _place_bc_lines(breakout: SubdomainBreakout, clone, mesh_name: str, ras, *, max_wait: int,
                    max_passes: int = 12) -> Dict[str, Any]:
    """Write the BC lines, preprocess, and move any line HEC-RAS rejects to its next placement.

    A line passes when HEC-RAS attaches it to at least one external face and to
    fewer than all of them (a short line can be assigned the whole perimeter).
    """
    from ..RasPreprocess import RasPreprocess
    from ..geom.GeomBcLines import GeomBcLines
    from ..geom.GeomStorage import GeomStorage

    polys = GeomStorage.get_storage_area_polygons(clone.geometry_path, exclude_2d=False)
    child = polys[polys["Name"].astype(str).str.strip() == mesh_name].geometry.iloc[0]
    variants = {b["name"]: _placement_variants(b["coordinates"], child, child.exterior)
                for b in breakout.bc_lines}
    state = {name: 0 for name in variants}
    project = Path(clone.plan_path).name.rsplit(".p", 1)[0]
    plan = str(clone.plan_number).zfill(2)
    tmp_hdf = Path(clone.plan_path).with_name(f"{project}.p{plan}.tmp.hdf")
    plan_hdf = Path(clone.plan_path).with_name(f"{project}.p{plan}.hdf")
    attempts, replaced = [], None
    for attempt in range(1, max_passes + 1):
        lines = []
        for b in breakout.bc_lines:
            d = {"name": b["name"], "bc_type": b["bc_type"], "friction_slope": float(b["friction_slope"]),
                 "coordinates": [tuple(map(float, xy[:2])) for xy in variants[b["name"]][state[b["name"]]][1]]}
            if "hydrograph_df" in b:
                d["hydrograph_df"] = b["hydrograph_df"]
            lines.append(d)
        replaced = GeomBcLines.replace_bc_lines(clone.geometry_path, [clone.unsteady_path], area_2d=mesh_name,
                                                lines=lines, ras_object=ras)
        result = RasPreprocess.preprocess_plan(plan, ras_object=ras, max_wait=max_wait)
        counts, shared = _compiled_line_faces(tmp_hdf)
        total = sum(counts.values())
        named = set(_BC_MESSAGE.findall(_compute_messages(plan_hdf))) & set(variants)
        failing = [n for n in variants
                   if n in named or n in shared or not counts
                   or not (0 < counts.get(n, 0) < max(total, 2) or len(variants) == 1)]
        attempts.append({"attempt": attempt, "preprocess_success": bool(result.success),
                         "placements": {n: variants[n][state[n]][0] for n in variants},
                         "external_faces": counts, "shared_faces": sorted(shared), "failing": failing,
                         "named_in_messages": sorted(named)})
        if not failing:
            return {"passed": True, "attempts": attempts, "replaced": replaced}
        exhausted = True
        for n in failing:
            if state[n] + 1 < len(variants[n]):
                state[n] += 1
                exhausted = False
        if exhausted:
            break
    return {"passed": False, "attempts": attempts, "replaced": replaced}



_INTERVAL = re.compile(r"^\s*([0-9.]+)\s*(SEC|MIN|HOUR)\s*$", re.IGNORECASE)
_UNIT_S = {"SEC": 1.0, "MIN": 60.0, "HOUR": 3600.0}


def _plan_value(plan_path: Path, key: str) -> Optional[str]:
    for line in Path(plan_path).read_text(errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def parent_minimum_interval(plan_path: Path) -> str:
    """The shortest step the parent plan's solver can take: base interval halved
    ``Max Halving`` times when the Courant-adaptive step is on, else the base."""
    base = _plan_value(plan_path, "Computation Interval")
    m = _INTERVAL.match(base or "")
    if not m:
        raise ValueError(f"cannot read Computation Interval from {plan_path.name}: {base!r}")
    seconds = float(m.group(1)) * _UNIT_S[m.group(2).upper()]
    courant = (_plan_value(plan_path, "Computation Time Step Use Courant") or "0").strip()
    halving = int(float(_plan_value(plan_path, "Computation Time Step Max Halving") or 0))
    if courant not in ("0", "", "False", "false"):
        seconds /= 2 ** max(halving, 0)
    if seconds < 60 or seconds % 60:
        return f"{seconds:g}SEC"
    return f"{seconds / 60:g}MIN" if seconds < 3600 else f"{seconds / 3600:g}HOUR"


def _remove_area_bc_lines(geom_file, mesh_name: str) -> List[str]:
    """Remove every BC line block of one 2D area from geometry text in one write.

    Same block rule as :meth:`GeomBcLines.delete_bc_line`, which rewrites (and backs
    up) the whole file per line; a delivered parent can carry dozens of lines.
    """
    from ..geom.GeomBcLines import GeomBcLines, _find_bc_line_block
    from ..geom.GeomParser import GeomParser

    path = Path(geom_file)
    lines = GeomBcLines.get_bc_lines(path)
    names = [str(n) for n in lines.loc[lines["storage_area"].astype(str) == mesh_name, "name"]]
    if not names:
        return []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as handle:
        text = handle.readlines()
    for name in names:
        hit = _find_bc_line_block(text, name)
        if hit is None:
            raise ValueError(f"BC line {name!r} not found in {path.name}")
        del text[hit[0]:hit[1]]
    GeomParser.safe_write_geometry(path, text, create_backup=True)
    remaining = GeomBcLines.get_bc_lines(path)
    if (remaining["storage_area"].astype(str) == mesh_name).any():
        raise RuntimeError(f"BC lines of {mesh_name} remain in {path.name}")
    logger.info("Removed %d inherited BC lines of %s from %s", len(names), mesh_name, path.name)
    return names


def apply_breakouts(breakout_plan: SubdomainBreakoutPlan, dest_folder, *, overwrite_dest: bool = False,
                    hecras_version: Optional[str] = None, time_step: str = "parent_minimum",
                    timeout: int = 1800) -> SubdomainBreakoutSet:
    import pandas as pd

    from ..RasBreakout2D import Breakout2DSpec, RasBreakout2D
    from ..RasPlan import RasPlan
    from ..RasPrj import RasPrj, init_ras_project
    from ..geom.GeomBcLines import GeomBcLines

    if time_step not in ("parent_minimum", "inherit"):
        raise ValueError("time_step must be 'parent_minimum' or 'inherit'")

    if not breakout_plan.is_ready:
        failed = breakout_plan.checks[breakout_plan.checks["blocking"]]
        raise ValueError("breakout plan has blocking checks: "
                         + "; ".join(f"{r.subdomain_id}:{r.check}" for r in failed.itertuples()))
    dest = Path(dest_folder).absolute()
    if dest.exists():
        if not overwrite_dest:
            raise FileExistsError(f"dest_folder exists: {dest} (pass overwrite_dest=True)")
        import shutil

        release_native_sessions(dest)
        shutil.rmtree(dest)
    working_prj, copy_record = _stage_working_copy(breakout_plan.ras_object, dest)
    working = RasPrj()
    init_ras_project(working_prj, hecras_version or str(breakout_plan.ras_object.ras_version or "6.6"),
                     ras_object=working, load_results_summary=False)
    rows, prep = [], {}
    search = breakout_plan.partition.search
    for bo in sorted(breakout_plan.breakouts, key=lambda b: (b.tier, b.subdomain_id)):
        spec = Breakout2DSpec(source_plan=breakout_plan.plan_number, source_2d_area=breakout_plan.mesh_name,
                              child_boundary=bo.child_boundary, breakout_id=f"sd_{bo.subdomain_id}"[:32],
                              child_boundary_crs=search.split_lines.crs,
                              containment_tolerance=_CONTAINMENT_TOL)
        # Preflight qualifies the parent's files; the clone then goes into the
        # working copy, which clone_plan_components checks byte for byte.
        pre = RasBreakout2D.preflight(spec, ras_object=breakout_plan.ras_object)
        if not pre.is_ready:
            raise ValueError(f"{bo.subdomain_id}: preflight failed: " + "; ".join(pre.blocking_issues))
        clone = RasBreakout2D.clone_plan_components(
            pre, ras_object=working, plan_title=f"Subdomain {bo.subdomain_id}"[:80],
            plan_short_id=f"sd{bo.subdomain_id}"[:24], geometry_title=f"Subdomain {bo.subdomain_id}"[:32],
            set_current_plan=False)
        # The clone inherits the parent's perimeter BC lines; on the cut child they
        # would overlap on edge faces and stop the native refresh. Remove them from
        # the geometry text only (the cloned unsteady file must stay byte-identical
        # until preparation ends); replace_bc_lines then writes the child's lines
        # and forcing, dropping the parent's orphaned blocks.
        _remove_area_bc_lines(clone.geometry_path, breakout_plan.mesh_name)
        prepared = RasBreakout2D.prepare_cloned_geometry(
            pre, clone, ras_object=working, refresh_hdf=True, refresh_method="rasexe", remesh=False,
            parent_cell_ids=list(bo.parent_cell_ids), timeout=timeout)
        step = None
        if time_step == "parent_minimum":
            # A child must not out-step its parent: the parent's adaptive step is set
            # by its most restrictive cells anywhere in the domain, so hold the child
            # at the shortest step the parent can take (fixed, no Courant doubling).
            step = parent_minimum_interval(pre.source_plan_path)
            if not RasPlan.set_2d_flow_options(clone.plan_number, computation_interval=step,
                                               time_step_use_courant=False, ras_object=working):
                raise RuntimeError(f"{bo.subdomain_id}: could not set the computation interval to {step}")
        placement = _place_bc_lines(bo, clone, breakout_plan.mesh_name, working, max_wait=timeout)
        prep[bo.subdomain_id] = {"clone": clone, "preparation": prepared, "bc_lines": placement["replaced"],
                                 "bc_placement": placement, "computation_interval": step}
        rows.append({"subdomain_id": bo.subdomain_id, "tier": bo.tier, "plan_number": clone.plan_number,
                     "geometry_number": clone.geometry_number, "unsteady_number": clone.unsteady_number,
                     "plan_path": clone.plan_path, "geometry_path": clone.geometry_path,
                     "unsteady_path": clone.unsteady_path})
        logger.info("Authored subdomain %s as plan %s", bo.subdomain_id, clone.plan_number)
    prep["_working_copy"] = copy_record
    return SubdomainBreakoutSet(plan=breakout_plan, project_folder=dest, children=pd.DataFrame(rows),
                                ras_object=working, preparation=prep)


_RESULT_HDF = re.compile(r"\.p\d{2}(\.tmp)?\.hdf$", re.IGNORECASE)
_ASSET_COLUMNS = ("terrain_hdf_path", "landcover_hdf_path", "infiltration_hdf_path", "soil_layer_path",
                  "projection_path")


def _stage_working_copy(ras_object, dest: Path) -> Tuple[Path, Dict[str, Any]]:
    """Copy the parent project and its RAS Mapper assets to ``dest``; return the copied .prj.

    The copied root is the smallest folder holding the project file and every
    existing terrain, land cover, infiltration, soils and projection file the
    project's ``.rasmap`` references, so relative references keep resolving.
    Parent plan result HDFs (``*.p##.hdf``) are not copied: children do not
    need them. ``RasProject.stage_project`` copies only the .prj folder, which
    would break eBFE layouts that keep Terrain/ beside Input/.
    """
    import os
    import shutil

    prj = Path(ras_object.prj_file).resolve()
    paths = [prj.parent]
    df = getattr(ras_object, "rasmap_df", None)
    if df is not None and len(df):
        for col in _ASSET_COLUMNS:
            if col not in df.columns:
                continue
            values = df.iloc[0][col]
            for v in (values if isinstance(values, (list, tuple)) else [values]):
                if v and Path(str(v)).exists():
                    paths.append(Path(str(v)).resolve().parent)
    root = Path(os.path.commonpath([str(p) for p in paths]))
    if dest.resolve().is_relative_to(root):
        raise ValueError(f"dest_folder must be outside the parent project tree {root}")
    skipped = []

    def ignore(folder, names):
        out = [n for n in names if _RESULT_HDF.search(n)]
        skipped.extend(str(Path(folder) / n) for n in out)
        return out

    shutil.copytree(root, dest, ignore=ignore)
    working_prj = dest / prj.relative_to(root)
    return working_prj, {"source_root": str(root), "working_project_file": str(working_prj),
                         "skipped_result_hdfs": skipped}


# --- validating ----------------------------------------------------------------------------


def validate_breakouts(breakout_set: SubdomainBreakoutSet, *, max_wait: int = 3600):
    import pandas as pd

    from ..RasPreprocess import RasPreprocess

    ras = breakout_set.ras_object
    rows: List[dict] = []
    by_id = {b.subdomain_id: b for b in breakout_set.plan.breakouts}
    for child in breakout_set.children.itertuples():
        sid = child.subdomain_id
        placement = breakout_set.preparation.get(sid, {}).get("bc_placement", {})
        _check(rows, sid, "bc_line_placement", bool(placement.get("passed")),
               f"{len(placement.get('attempts', []))} placement pass(es)")
        plan = str(child.plan_number).zfill(2)
        plan_path = Path(child.plan_path)
        project = plan_path.name.rsplit(".p", 1)[0]
        tmp_hdf = plan_path.with_name(f"{project}.p{plan}.tmp.hdf")
        result = RasPreprocess.preprocess_plan(plan, ras_object=ras, max_wait=max_wait)
        counts, shared = _compiled_line_faces(tmp_hdf)
        messages = _compute_messages(plan_path.with_name(f"{project}.p{plan}.hdf"))
        # A small child can finish before process ownership is established; judge
        # completion from HEC-RAS's own output, not the process signal.
        complete = bool(counts) and "Error Processing Geometry" not in messages
        _check(rows, sid, "preprocess", complete,
               "geometry and event conditions written" if complete
               else (result.error or messages.strip().splitlines()[-1:] or ["no external faces written"])[0])
        total = sum(counts.values())
        lines = by_id[sid].bc_lines
        for line in lines:
            n = int(counts.get(line["name"], 0))
            _check(rows, sid, f"bc_line:{line['name']}",
                   (0 < n < max(total, 2) or len(lines) == 1) and line["name"] not in shared,
                   f"{n} of {total} external faces" + ("; shares faces with another line" if line["name"] in shared else ""))
    return pd.DataFrame(rows, columns=["subdomain_id", "check", "passed", "blocking", "detail"])


# --- computing -----------------------------------------------------------------------------


def _bc_flow(plan_hdf: Path, bc_names: Sequence[str]):
    """Summed flow of the named BC lines in a child plan HDF, as hours and values."""
    from ..hdf.HdfResultsMesh import HdfResultsMesh

    ds = HdfResultsMesh.get_boundary_conditions_timeseries(plan_hdf)
    names = [n for n in ds["bc_name"].values.tolist() if any(str(n).endswith(b) or str(n) == b for b in bc_names)]
    if not names:
        raise ValueError(f"{plan_hdf.name}: no BC output for {list(bc_names)}")
    q = np.abs(ds["flow"].sel(bc_name=names).values).sum(axis=1)
    t = ds["time"].values.astype("datetime64[ns]")
    hours = (t - t[0]).astype("timedelta64[ns]").astype(np.int64) / 3.6e12
    return hours, q


def compute_subdomains(breakout_set: SubdomainBreakoutSet, *, max_workers: int = 2, num_cores: int = 2):
    import time

    import pandas as pd

    from ..RasCmdr import RasCmdr
    from ..RasUnsteady import RasUnsteady

    ras = breakout_set.ras_object
    children = breakout_set.children
    by_id = {b.subdomain_id: b for b in breakout_set.plan.breakouts}
    plan_of = dict(zip(children["subdomain_id"], children["plan_number"]))
    rows = []
    for tier in sorted(children["tier"].unique()):
        ids = list(children.loc[children["tier"] == tier, "subdomain_id"])
        for sid in ids:  # hand-off from upstream tiers already computed
            for line in by_id[sid].bc_lines:
                up = line.get("upstream_subdomain_id")
                if not up or up not in plan_of:
                    continue
                hdf = Path(ras.plan_df.set_index("plan_number").loc[plan_of[up], "HDF_Results_Path"])
                hours, q = _bc_flow(hdf, [b["name"] for b in by_id[up].bc_lines if b["role"] == OUTLET])
                unsteady = children.set_index("subdomain_id").loc[sid, "unsteady_path"]
                ok = RasUnsteady.set_boundary_inline_hydrograph(
                    unsteady, pd.DataFrame({"hour": hours, "value": q}), area_2d=breakout_set.plan.mesh_name,
                    bc_line=line["name"], ras_object=ras)
                if not ok:
                    raise RuntimeError(f"{sid}: could not write the inflow from {up} to {line['name']}")
        start = time.time()
        result = RasCmdr.compute_parallel(plan_number=[plan_of[s] for s in ids], max_workers=max_workers,
                                          num_cores=num_cores, ras_object=ras, force_rerun=True)
        wall = time.time() - start
        ras.plan_df = ras.get_plan_entries()
        for sid in ids:
            ok = bool(getattr(result, "execution_results", {}).get(plan_of[sid], False)) \
                if hasattr(result, "execution_results") else bool(result)
            hdf = ras.plan_df.set_index("plan_number").loc[plan_of[sid], "HDF_Results_Path"]
            rows.append({"subdomain_id": sid, "tier": int(tier), "plan_number": plan_of[sid],
                         "success": ok, "tier_wall_clock_s": wall, "plan_hdf_path": hdf})
    return pd.DataFrame(rows)


# --- comparing -----------------------------------------------------------------------------


def compare_to_parent(breakout_set: SubdomainBreakoutSet, parent_plan_hdf_path, *, depth_threshold_ft: float = 0.1):
    import pandas as pd
    from scipy.spatial import cKDTree

    from ..hdf.HdfResultsMesh import HdfResultsMesh
    from ._parent import EventReader, read_geometry

    parent_path = Path(parent_plan_hdf_path)
    mesh_name = breakout_set.plan.mesh_name
    pg = read_geometry(parent_path, mesh_name)
    pwse = HdfResultsMesh.get_mesh_summary_values(parent_path, "Maximum Water Surface")
    pwse = pwse[pwse["mesh_name"] == mesh_name].set_index("cell_id")["maximum_water_surface"]
    tree = cKDTree(pg.cell_center)
    ras = breakout_set.ras_object
    plan_hdf = ras.plan_df.set_index("plan_number")["HDF_Results_Path"]
    lines = breakout_set.plan.partition.search._context["lines"]
    rows = []
    for child in breakout_set.children.itertuples():
        hdf = plan_hdf.get(child.plan_number)
        if not hdf or not Path(hdf).is_file():
            rows.append({"subdomain_id": child.subdomain_id, "status": "no results"})
            continue
        hdf = Path(hdf)
        cg = read_geometry(hdf, mesh_name)
        dist, idx = tree.query(cg.cell_center)
        cwse = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")
        cwse = cwse[cwse["mesh_name"] == mesh_name].set_index("cell_id")["maximum_water_surface"]
        child_ids = np.arange(cg.cell_count)
        matched = dist < 0.01
        c_w = cwse.reindex(child_ids).to_numpy(float)
        p_w = pwse.reindex(idx).to_numpy(float)
        c_d = c_w - cg.cell_min_elevation
        p_d = p_w - pg.cell_min_elevation[idx]
        wet_c, wet_p = c_d > depth_threshold_ft, p_d > depth_threshold_ft
        both = matched & wet_c & wet_p
        diff = (c_w - p_w)[both]
        union = (matched & (wet_c | wet_p)).sum()
        row = {"subdomain_id": child.subdomain_id, "status": "compared",
               "cells": int(cg.cell_count), "cells_matched_to_parent": int(matched.sum()),
               "wet_cells_compared": int(both.sum()),
               "wse_diff_p50_ft": float(np.percentile(np.abs(diff), 50)) if diff.size else None,
               "wse_diff_p95_ft": float(np.percentile(np.abs(diff), 95)) if diff.size else None,
               "wse_diff_p99_ft": float(np.percentile(np.abs(diff), 99)) if diff.size else None,
               "wse_diff_max_ft": float(np.abs(diff).max()) if diff.size else None,
               "wse_diff_mean_ft": float(diff.mean()) if diff.size else None,
               "wet_extent_iou": float(both.sum() / union) if union else None}
        bo = next(b for b in breakout_set.plan.breakouts if b.subdomain_id == child.subdomain_id)
        if bo.outlet_split_line_id is not None:
            s = lines[bo.outlet_split_line_id]
            reader = EventReader(parent_path, mesh_name)
            ids, flow = reader.series("Face Flow", s["faces"])
            col = {int(f): i for i, f in enumerate(ids)}
            pq = (flow[:, [col[int(f)] for f in s["faces"]]] * np.asarray(s["signs"])).sum(axis=1)
            ph = reader.seconds() / 3600.0
            ch, cq = _bc_flow(hdf, [b["name"] for b in bo.bc_lines if b["role"] == OUTLET])
            cq_on_p = np.interp(ph, ch, cq)
            pv, cv = np.trapezoid(pq, ph * 3600.0), np.trapezoid(cq_on_p, ph * 3600.0)
            nse = 1.0 - np.sum((cq_on_p - pq) ** 2) / np.sum((pq - pq.mean()) ** 2)
            row.update({"outlet_peak_parent_cfs": float(pq.max()), "outlet_peak_child_cfs": float(cq.max()),
                        "outlet_peak_diff_pct": float(100 * (cq.max() - pq.max()) / pq.max()) if pq.max() else None,
                        "outlet_peak_time_diff_h": float(ch[int(np.argmax(cq))] - ph[int(np.argmax(pq))]),
                        "outlet_volume_diff_pct": float(100 * (cv - pv) / pv) if pv else None,
                        "outlet_nse": float(nse)})
        rows.append(row)
    return pd.DataFrame(rows)
