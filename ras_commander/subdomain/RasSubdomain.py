"""Hydraulic subdomains of a 2D parent model: normal-depth split lines and nested footprints.

A large 2D (often rain-on-grid) parent is divided into breakout subdomains whose
boundaries sit where normal depth holds. Placing a model boundary where normal
depth can be assumed is standard practice; here the locations are found
numerically from the parent's own plan HDF (native ``Face Flow`` and cell
stage) along terrain-derived (TauDEM) stream links, and each subdomain's extent
is traced from the parent's own cell-to-cell flow.

Workflow::

    streams + catchments  = RasTauDem.delineate(dem, folder)
    search    = RasSubdomain.find_split_lines(plan_hdf_paths, streams, catchments)
    partition = RasSubdomain.build_subdomains(search)

Labels are information, not gates; nothing here is hydraulic approval.

Ported from fim-commander ``fim_commander.methods.pic.split_lines`` and
``fim_commander.step.rog_split_lines`` (same owner), with TauDEM pour points and
contributing areas in place of the NextGen hydrofabric.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from ..LoggingConfig import get_logger, log_call
from . import _split_lines as sl
from ._parent import (EventReader, face_tables, mesh_names, read_geometry, require_face_flow,
                      require_feet, same_geometry, sha256_file)

logger = get_logger(__name__)

__all__ = ["RasSubdomain", "SplitLineCriteria", "SplitLineSearch", "SubdomainPartition"]

SQFT_PER_SQMI = 5280.0 ** 2
REMAINDER_ID = "remainder"
SPLIT_LINE_LABELS = ("SHARED_LINE", "CONTRIBUTING_AREA_EXTENDS_PAST_MESH")
SUBDOMAIN_LABELS = ("CLOSED_EDGE_LEAKAGE", "FOOTPRINT_OVERLAP", "FOOTPRINT_PARTS_DROPPED",
                    "MULTIPART", "STRUCTURE_ON_SPLIT_LINE", "INTERIOR_SUBDOMAIN", "HOLES")


@dataclass(frozen=True)
class SplitLineCriteria:
    """Thresholds of the split-line search. Defaults are the project-engineer values of 2026-10-14.

    Distances are feet; slopes and fractions are dimensionless.
    """

    step_spacing_ft: float = 150.0
    walk_length_ft: float = 3000.0
    seed_radius_ft: float = 300.0
    max_angle_deg: float = 60.0
    wet_depth_ft: float = 0.1
    edge_fraction: float = 0.01
    max_half_line_ft: float = 8000.0
    max_reverse_fraction: float = 0.05
    max_fit_error_ft: float = 0.5
    slope_ratio_bounds: Tuple[float, float] = (1.0 / 3.0, 3.0)
    outflow_share_bounds: Tuple[float, float] = (0.80, 1.20)
    fit_flow_fraction: float = 0.10
    stage_step_ft: float = 0.02
    stage_span_ft: float = 40.0
    min_contributing_area_sqmi: float = 1.0
    nested_fraction: float = 0.95
    max_leak_fraction: float = 0.05
    min_inside_fraction: float = 0.99

    def __post_init__(self):
        for name, value in asdict(self).items():
            values = value if isinstance(value, tuple) else (value,)
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values):
                raise ValueError(f"SplitLineCriteria.{name} must be finite and non-negative")
        for name in ("slope_ratio_bounds", "outflow_share_bounds"):
            low, high = getattr(self, name)
            if not low < high:
                raise ValueError(f"SplitLineCriteria.{name} must be (low, high) with low < high")


@dataclass(frozen=True)
class SplitLineSearch:
    """Result of :meth:`RasSubdomain.find_split_lines`.

    Attributes:
        split_lines: One row per accepted split line (schema ``subdomain_split_lines``).
        candidates: Every scored walk-up step and event (schema ``subdomain_split_candidates``).
        criteria: The thresholds used.
        mesh_name: Parent 2D flow area.
        events: Event labels, in ``plan_hdf_paths`` order.
        plan_hdf_paths: Parent plan HDFs.
        plan_hdf_sha256: SHA-256 of each plan HDF, in the same order.
        growth_event: The event the lines grew on.
    """

    split_lines: Any
    candidates: Any
    criteria: SplitLineCriteria
    mesh_name: str
    events: Tuple[str, ...]
    plan_hdf_paths: Tuple[Path, ...]
    plan_hdf_sha256: Tuple[str, ...]
    growth_event: str
    schema: str = "ras-subdomain-split-line-search/1"
    _context: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready summary (frames summarized by row count)."""
        return {
            "schema": self.schema,
            "mesh_name": self.mesh_name,
            "events": list(self.events),
            "growth_event": self.growth_event,
            "plan_hdf_paths": [str(p) for p in self.plan_hdf_paths],
            "plan_hdf_sha256": list(self.plan_hdf_sha256),
            "criteria": asdict(self.criteria),
            "split_line_count": int(len(self.split_lines)),
            "candidate_rows": int(len(self.candidates)),
        }


@dataclass(frozen=True)
class SubdomainPartition:
    """Result of :meth:`RasSubdomain.build_subdomains`.

    Attributes:
        subdomains: One row per subdomain plus the remainder (schema ``subdomain_partition``).
        cell_owner: ``cell_id`` to ``subdomain_id``, every physical parent cell once.
        remainder_id: ``subdomain_id`` of the cells no split line drains.
        run_order: Subdomain ids by tier, upstream first; the remainder runs last.
        search: The split-line search this partition was built from.
    """

    subdomains: Any
    cell_owner: Any
    remainder_id: str
    run_order: Tuple[Tuple[str, ...], ...]
    search: SplitLineSearch = field(repr=False)
    schema: str = "ras-subdomain-partition/1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "remainder_id": self.remainder_id,
            "run_order": [list(t) for t in self.run_order],
            "subdomain_count": int(len(self.subdomains)),
            "search": self.search.to_dict(),
        }


def _event_label(path: Path) -> str:
    import h5py

    try:
        with h5py.File(path, "r") as f:
            info = f["Plan Data/Plan Information"].attrs
            value = info.get("Plan ShortID") or info.get("Plan Name")
            if value is not None:
                text = value.decode() if isinstance(value, bytes) else str(value)
                if text.strip():
                    return text.strip()
    except (KeyError, OSError):
        pass
    return path.name.split(".hdf")[0]


def _stream_paths(streams) -> Dict[int, Any]:
    """Each link with its larger upstream chain, as one downstream-to-upstream line.

    TauDEM StreamNet writes each link from its outlet upstream.
    """
    from shapely.geometry import LineString

    table = streams.set_index("LINKNO")
    geometry = {}
    for link, g in zip(table.index, table.geometry):
        if g is None or g.is_empty:
            continue
        g = max(g.geoms, key=lambda x: x.length) if g.geom_type == "MultiLineString" else g
        geometry[int(link)] = g
    area = table["DSContArea"].astype(float).to_dict()
    paths = {}
    for link in geometry:
        coords, current, seen = [], link, set()
        while current is not None and current not in seen and len(coords) < 100_000:
            seen.add(current)
            part = list(geometry[current].coords)
            coords += part if not coords else part[1:]
            ups = [int(table.at[current, c]) for c in ("USLINKNO1", "USLINKNO2")]
            ups = [u for u in ups if u in geometry]
            current = max(ups, key=lambda u: area[u]) if ups else None
        if len(coords) >= 2:
            paths[link] = LineString(coords)
    return paths


def _upstream_closure(streams) -> Dict[int, set]:
    up = {int(r.LINKNO): [int(u) for u in (r.USLINKNO1, r.USLINKNO2) if int(u) >= 0]
          for r in streams.itertuples()}
    memo: Dict[int, set] = {}
    for link in up:
        if link in memo:
            continue
        stack, order = [link], []
        while stack:
            x = stack.pop()
            if x in memo or x in order:
                continue
            order.append(x)
            stack.extend(u for u in up.get(x, []) if u not in memo)
        for x in reversed(order):
            members = {x}
            for u in up.get(x, []):
                members |= memo.get(u, {u})
            memo[x] = members
    return memo


def _union(polygons):
    import shapely
    from shapely.errors import GEOSException

    try:
        return shapely.coverage_union_all(polygons)
    except GEOSException:
        return shapely.union_all(shapely.make_valid(polygons))


class RasSubdomain:
    """Static methods for finding and building hydraulic subdomains of a 2D parent model."""

    @staticmethod
    @log_call
    def find_split_lines(plan_hdf_paths: Union[str, Path, Sequence[Union[str, Path]]],
                         streams: Any,
                         catchments: Any,
                         *,
                         mesh_name: Optional[str] = None,
                         growth_plan_hdf_path: Union[str, Path, None] = None,
                         criteria: Optional[SplitLineCriteria] = None,
                         link_ids: Optional[Sequence[int]] = None) -> SplitLineSearch:
        """Find normal-depth split lines in a parent's native face flow.

        Pour points are the downstream ends (outlets) of the TauDEM stream links
        inside the mesh whose contributing area is at least
        ``criteria.min_contributing_area_sqmi``. A pour point's contributing area
        ``U`` is the union of the catchments of its link and every link upstream.
        From each pour point the search walks up the link (and its larger upstream
        link) in ``step_spacing_ft`` steps to ``walk_length_ft``. At each step a
        line grows across the valley from the face the channel crosses, along
        the faces carrying the most downstream volume in the growth event, to the
        edge of the ``wet_depth_ft`` wet extent. Each line is then scored in every
        event as a normal-depth boundary: native ``Q(t)`` across it against the
        stage of the cell above the seed face, through the conveyance ``K(z)`` of
        the line's face property tables, at the best single slope.

        A line passes in an event when both banks close; reverse flow is at most
        ``max_reverse_fraction``; RMSE, peak error and loop width are each at most
        ``max_fit_error_ft``; the best slope is within ``slope_ratio_bounds`` of
        the link slope; and the line carries ``outflow_share_bounds`` of ``U``'s
        outflow. A split line passes in every event at its step and at a
        neighbouring step; the lowest mean RMSE wins.

        Args:
            plan_hdf_paths: One or more plan HDFs (events) of one geometry, each
                with native ``Face Flow`` output. Two events of different
                magnitude are recommended; a line must pass in every event.
            streams: TauDEM links (``RasTauDem.delineate(...).streams``, schema
                ``taudem_streams``), any CRS.
            catchments: TauDEM catchments (schema ``taudem_catchments``), any CRS.
            mesh_name: 2D flow area; required when the plan has more than one.
            growth_plan_hdf_path: Event the lines grow on; default the event with
                the largest total face volume (widest wet extent).
            criteria: Thresholds; default :class:`SplitLineCriteria`.
            link_ids: Limit pour points to these TauDEM ``LINKNO`` values.

        Returns:
            SplitLineSearch

        Raises:
            ValueError: Missing Face Flow, differing geometries, or no 2D area.
            NotImplementedError: SI-unit parent.
        """
        import geopandas as gpd
        import pandas as pd
        import shapely

        from ..hdf.HdfMesh import HdfMesh

        c = criteria or SplitLineCriteria()
        if isinstance(plan_hdf_paths, (str, Path)):
            plan_hdf_paths = [plan_hdf_paths]
        paths = tuple(Path(p).resolve() for p in plan_hdf_paths)
        if not paths:
            raise ValueError("plan_hdf_paths is empty")
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(f"plan HDF not found: {p}")
        if mesh_name is None:
            names = mesh_names(paths[0])
            if len(names) != 1:
                raise ValueError(f"mesh_name is required; {paths[0].name} has 2D areas {names}")
            mesh_name = names[0]
        for p in paths:
            require_feet(p)
            require_face_flow(p, mesh_name)
        missing = {"LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2", "DSContArea", "Slope"} - set(streams.columns)
        if missing:
            raise ValueError(f"streams lack columns {sorted(missing)}")
        if "LINKNO" not in catchments.columns:
            raise ValueError("catchments lack column 'LINKNO'")

        geometry = read_geometry(paths[0], mesh_name)
        for p in paths[1:]:
            if not same_geometry(geometry, read_geometry(p, mesh_name)):
                raise ValueError(f"{p.name} describes a different mesh than {paths[0].name}")
        crs = geometry.crs_wkt
        if not crs:
            raise ValueError(f"{paths[0].name} has no projection")
        events = []
        for p in paths:
            label = _event_label(p)
            while label in events:
                label += "_"
            events.append(label)
        mesh = sl.mesh_from_topology(geometry.cell_count, geometry.face_cells,
                                     geometry.face_normal, geometry.face_length,
                                     geometry.face_points, geometry.point_xy)
        readers = {e: EventReader(p, mesh_name) for e, p in zip(events, paths)}
        weights = {e: sl.trapezoid_weights(r.seconds()) for e, r in readers.items()}
        logger.info("Integrating event face volumes (%d events, %d faces)", len(events), len(geometry.face_cells))
        volume = {e: r.face_volumes(weights[e]) for e, r in readers.items()}
        depth = {e: r.max_depth(geometry) for e, r in readers.items()}
        if growth_plan_hdf_path is not None:
            gp = Path(growth_plan_hdf_path).resolve()
            if gp not in paths:
                raise ValueError("growth_plan_hdf_path must be one of plan_hdf_paths")
            growth = events[paths.index(gp)]
        else:
            growth = max(events, key=lambda e: float(np.abs(volume[e]).sum()))

        cells = HdfMesh.get_mesh_cell_polygons(paths[0])
        cells = cells[cells["mesh_name"] == mesh_name].set_index("cell_id")
        cells = cells[cells.index < geometry.cell_count]
        area = np.zeros(geometry.cell_count)
        area[cells.index.to_numpy(int)] = cells.geometry.area.to_numpy(float)
        hull = _union(cells.geometry.to_numpy())
        centers = gpd.GeoDataFrame({"cell_id": np.arange(geometry.cell_count)},
                                   geometry=gpd.points_from_xy(*geometry.cell_center.T), crs=crs)

        streams = streams.to_crs(crs)
        catchments = catchments.to_crs(crs)
        joined = gpd.sjoin(centers, catchments[["LINKNO", "geometry"]], how="inner", predicate="within")
        joined = joined.sort_values("LINKNO").drop_duplicates("cell_id")
        cell_link = np.full(geometry.cell_count, -1, np.int64)
        cell_link[joined["cell_id"].to_numpy(int)] = joined["LINKNO"].to_numpy(int)
        catch_area = catchments.assign(_a=catchments.geometry.area).groupby("LINKNO")["_a"].sum().to_dict()
        closure = _upstream_closure(streams)
        stream_paths = _stream_paths(streams)
        slope = dict(zip(streams["LINKNO"].astype(int), streams["Slope"].astype(float)))
        from pyproj import CRS

        unit_ft = CRS.from_user_input(crs).axis_info[0].unit_conversion_factor / 0.3048
        # DSContArea is in the DEM's units squared, which may differ from the mesh CRS.
        if "contributing_area_sqmi" in streams.columns:
            contributing_sqmi = dict(zip(streams["LINKNO"].astype(int),
                                         streams["contributing_area_sqmi"].astype(float)))
        else:
            contributing_sqmi = dict(zip(streams["LINKNO"].astype(int),
                                         streams["DSContArea"].astype(float) * unit_ft ** 2 / SQFT_PER_SQMI))

        wanted = None if link_ids is None else {int(x) for x in link_ids}
        domains: Dict[int, Dict[str, Any]] = {}
        steps: List[Dict[str, Any]] = []
        for link, path in stream_paths.items():
            if wanted is not None and link not in wanted:
                continue
            if contributing_sqmi.get(link, 0.0) < c.min_contributing_area_sqmi:
                continue
            pour = shapely.Point(path.coords[0])
            if not hull.contains(pour):
                continue
            members = closure.get(link, {link})
            mask = np.isin(cell_link, list(members))
            u_area = float(sum(catch_area.get(m, 0.0) for m in members)) * unit_ft ** 2
            domains[link] = {
                "u_area_sqft": u_area,
                "inside_fraction": float(area[mask].sum() * unit_ft ** 2 / u_area) if u_area > 0 else 0.0,
                "outflow": {e: sl.domain_outflow(mesh, mask, volume[e]) for e in events},
            }
            step_len = c.step_spacing_ft / unit_ft
            for k in range(int(c.walk_length_ft // c.step_spacing_ft) + 1):
                s = k * step_len
                if s >= path.length - 1.0:
                    break
                p = path.interpolate(s)
                a = path.interpolate(max(s - 100.0 / unit_ft, 0.0))
                b = path.interpolate(min(s + 100.0 / unit_ft, path.length))
                t = np.array([a.x - b.x, a.y - b.y])
                t = t / (np.hypot(*t) or 1.0)
                seed = sl.seed_face(mesh, path, p, t, c.seed_radius_ft / unit_ft)
                if seed is None:
                    continue
                faces, signs, closed = sl.grow_line(
                    mesh, seed, t, depth[growth], volume[growth], max_angle_deg=c.max_angle_deg,
                    wet_depth=c.wet_depth_ft, edge_fraction=c.edge_fraction,
                    max_half_length=c.max_half_line_ft / unit_ft)
                steps.append({"link": link, "step": k, "distance_up_ft": s * unit_ft, "seed": seed,
                              "downstream": t, "faces": faces, "signs": signs, "closed": closed,
                              "stage_cell": sl.cells_upstream_of(mesh, seed, t)})
        logger.info("%d pour points, %d walk-up steps", len(domains), len(steps))

        line_faces = sorted({int(f) for s in steps for f in s["faces"]})
        stage_cells = sorted({s["stage_cell"] for s in steps if 0 <= s["stage_cell"] < geometry.cell_count})
        tables = face_tables(paths[0], mesh_name, line_faces) if line_faces else {}
        bed = geometry.cell_min_elevation
        rows: List[Dict[str, Any]] = []
        for event, reader in readers.items():
            if not steps:
                break
            fids, flow = reader.series("Face Flow", line_faces)
            cids, wse = reader.series("Water Surface", stage_cells)
            fcol = {int(f): i for i, f in enumerate(fids)}
            ccol = {int(x): i for i, x in enumerate(cids)}
            for s in steps:
                cell = s["stage_cell"]
                stage = wse[:, ccol[cell]] if cell in ccol else np.full(len(wse), np.nan)
                lf = s["faces"]
                score = sl.score_line(
                    flow[:, [fcol[int(f)] for f in lf]], s["signs"], weights[event], stage,
                    float(bed[cell]) if 0 <= cell < geometry.cell_count else float("nan"),
                    lambda z, lf=lf: sl.conveyance(tables, lf, z, mesh.length),
                    slope.get(s["link"], 0.0), fit_fraction=c.fit_flow_fraction,
                    stage_step=c.stage_step_ft, stage_span=c.stage_span_ft)
                outflow = domains[s["link"]]["outflow"][event]
                share = score["line_volume"] / outflow if outflow > 0 else None
                gates = sl.failed_gates(score, s["closed"], share, slope.get(s["link"], 0.0),
                                        max_reverse_fraction=c.max_reverse_fraction,
                                        max_fit_error_ft=c.max_fit_error_ft,
                                        slope_ratio_bounds=c.slope_ratio_bounds,
                                        share_bounds=c.outflow_share_bounds)
                rows.append({
                    "split_line_id": s["link"], "event": event, "walk_step": s["step"],
                    "distance_up_ft": s["distance_up_ft"], "seed_face_id": s["seed"],
                    "face_count": len(lf), "line_length_ft": float(mesh.length[lf].sum() * unit_ft),
                    "closed": s["closed"], "link_slope": slope.get(s["link"], 0.0), **score,
                    "contributing_outflow": outflow, "outflow_share": share,
                    "failed_criteria": gates, "passes": not gates,
                })

        by_link: Dict[int, Dict[int, Dict[str, dict]]] = {}
        for row in rows:
            by_link.setdefault(row["split_line_id"], {}).setdefault(row["walk_step"], {})[row["event"]] = row
        chosen: Dict[int, Dict[str, Any]] = {}
        for link, by_step in by_link.items():
            passing = {k: all(v.get(e, {}).get("passes", False) for e in events) for k, v in by_step.items()}
            rmse = {k: float(np.mean([(v.get(e, {}).get("rmse_ft") or 0.0) for e in events]))
                    for k, v in by_step.items()}
            k = sl.stable_step(passing, rmse)
            if k is not None:
                chosen[link] = next(s for s in steps if s["link"] == link and s["step"] == k)
        lines: Dict[int, Dict[str, Any]] = {}
        shared: Dict[int, List[int]] = {}
        for link in sorted(chosen):
            key = tuple(sorted(int(f) for f in chosen[link]["faces"]))
            first = next((e for e, s in lines.items() if s["key"] == key), None)
            if first is not None:
                shared[first].append(link)
                continue
            lines[link] = {**chosen[link], "key": key}
            shared[link] = []
        for row in rows:
            row["chosen"] = row["split_line_id"] in lines and row["walk_step"] == lines[row["split_line_id"]]["step"]

        records = []
        for link, s in lines.items():
            scored = by_link[link][s["step"]]
            labels = []
            if shared[link]:
                labels.append("SHARED_LINE")
            if domains[link]["inside_fraction"] < c.min_inside_fraction:
                labels.append("CONTRIBUTING_AREA_EXTENDS_PAST_MESH")
            rec = {
                "split_line_id": link, "also_link_ids": shared[link], "walk_step": s["step"],
                "distance_up_ft": s["distance_up_ft"], "seed_face_id": s["seed"],
                "face_ids": [int(f) for f in s["faces"]], "face_signs": [float(x) for x in s["signs"]],
                "line_length_ft": float(mesh.length[s["faces"]].sum() * unit_ft),
                "downstream_x": float(s["downstream"][0]), "downstream_y": float(s["downstream"][1]),
                "link_slope": slope.get(link, 0.0),
                "normal_depth_slope": float(np.mean([scored[e]["best_slope"] for e in events])),
                "contributing_area_sqmi": domains[link]["u_area_sqft"] / SQFT_PER_SQMI,
                "contributing_inside_fraction": domains[link]["inside_fraction"],
                "labels": labels,
            }
            for e in events:
                for name in ("best_slope", "peak_flow", "line_volume", "rmse_ft", "peak_error_ft",
                             "loop_ft", "reverse_fraction", "outflow_share"):
                    rec[f"{name}_{e}"] = scored[e][name]
            rec["geometry"] = shapely.line_merge(shapely.MultiLineString(
                [mesh.point_xy[mesh.points[int(f)]] for f in s["faces"]]))
            records.append(rec)
        split_lines = gpd.GeoDataFrame(records, geometry="geometry", crs=crs) if records else \
            gpd.GeoDataFrame({"split_line_id": pd.Series(dtype="int64")}, geometry=[], crs=crs)
        candidates = pd.DataFrame(rows)
        logger.info("%d split lines from %d scored rows", len(split_lines), len(candidates))
        context = {"mesh": mesh, "geometry": geometry, "volume": volume, "cells": cells,
                   "area": area, "lines": lines, "unit_ft": unit_ft}
        return SplitLineSearch(
            split_lines=split_lines, candidates=candidates, criteria=c, mesh_name=mesh_name,
            events=tuple(events), plan_hdf_paths=paths,
            plan_hdf_sha256=tuple(sha256_file(p) for p in paths), growth_event=growth,
            _context=context,
        )

    @staticmethod
    @log_call
    def build_subdomains(search: SplitLineSearch, *,
                         split_line_ids: Optional[Sequence[int]] = None) -> SubdomainPartition:
        """Trace each split line's footprint and nest the footprints into subdomains.

        The footprint of a split line is every cell whose drainage path (each
        cell to the neighbour receiving most of its event volume) crosses the
        line in any event, with holes filled. Footprints nest; each cell goes to
        the smallest footprint holding it, so a subdomain is its footprint less
        the subdomains upstream of it. Tier 1 has nothing upstream. Cells no
        line drains form the remainder.

        Args:
            search: From :meth:`find_split_lines` (same session; the parent
                arrays it read are reused).
            split_line_ids: Keep only these split lines (default: all).

        Returns:
            SubdomainPartition. Labels (information only): ``CLOSED_EDGE_LEAKAGE``,
            ``FOOTPRINT_OVERLAP``, ``FOOTPRINT_PARTS_DROPPED``, ``MULTIPART``,
            ``STRUCTURE_ON_SPLIT_LINE``, ``INTERIOR_SUBDOMAIN`` (touches no
            parent perimeter face) and ``HOLES``.
        """
        import geopandas as gpd
        import pandas as pd
        import shapely

        ctx = search._context
        if not ctx:
            raise ValueError("search has no parent context; call find_split_lines in this session")
        c = search.criteria
        mesh, geometry, volume, cells = ctx["mesh"], ctx["geometry"], ctx["volume"], ctx["cells"]
        unit_ft, lines = ctx["unit_ft"], ctx["lines"]
        crs = search.split_lines.crs
        if split_line_ids is not None:
            unknown = set(int(x) for x in split_line_ids) - set(lines)
            if unknown:
                raise ValueError(f"unknown split_line_ids {sorted(unknown)}")
            lines = {k: v for k, v in lines.items() if k in {int(x) for x in split_line_ids}}
        events = search.events
        physical_ids = cells.index.to_numpy(int)
        cx, cy = geometry.cell_center[physical_ids].T
        receiver = {e: sl.receivers(mesh, volume[e]) for e in events}
        footprints: Dict[int, set] = {}
        dropped: Dict[int, float] = {}
        for link, s in lines.items():
            drained = set()
            for e in events:
                drained |= sl.drained_cells(mesh, receiver[e], s["faces"], s["downstream"])
            drained &= set(physical_ids.tolist())
            if not drained:
                continue
            shape = _union(cells.geometry.loc[sorted(drained)].to_numpy())
            parts = list(getattr(shape, "geoms", [shape]))
            main = max(parts, key=lambda g: g.area)
            dropped[link] = float(sum(g.area for g in parts if g is not main) * unit_ft ** 2 / SQFT_PER_SQMI)
            inside = shapely.contains_xy(shapely.Polygon(main.exterior), cx, cy)
            footprints[link] = set(physical_ids[inside].tolist())
        nested = sl.nest(footprints, c.nested_fraction)

        a, b = mesh.cell_0, mesh.cell_1
        ghost_a = (a < 0) | (a >= mesh.cell_count)
        ghost_b = (b < 0) | (b >= mesh.cell_count)
        perimeter_cells = set(np.where(ghost_a & ~ghost_b, b, -1).tolist()) | \
            set(np.where(ghost_b & ~ghost_a, a, -1).tolist())
        perimeter_cells.discard(-1)
        try:
            from ..hdf.HdfStruc import HdfStruc

            structures = HdfStruc.get_structures(search.plan_hdf_paths[0])
            structures = structures.to_crs(crs) if len(structures) and structures.crs else structures
        except Exception:  # structures are optional context; missing tables are normal
            structures = gpd.GeoDataFrame(geometry=[], crs=crs)

        rows, owner_rows, owned = [], [], set()
        for link, info in nested.items():
            s = lines[link]
            inlets = [int(f) for u in info["upstream"] for f in lines[u]["faces"]]
            exchange = {e: sl.edge_exchange(mesh, info["cells"], volume[e], s["faces"], inlets) for e in events}
            leak = {e: (x["edge_out"] + x["edge_in"]) / x["outlet_out"] if x["outlet_out"] > 0 else None
                    for e, x in exchange.items()}
            geom = _union(cells.geometry.loc[sorted(info["cells"])].to_numpy())
            labels = []
            if any(v is None or v > c.max_leak_fraction for v in leak.values()):
                labels.append("CLOSED_EDGE_LEAKAGE")
            if info["overlaps"]:
                labels.append("FOOTPRINT_OVERLAP")
            if dropped.get(link, 0.0) > 0:
                labels.append("FOOTPRINT_PARTS_DROPPED")
            if geom.geom_type == "MultiPolygon":
                labels.append("MULTIPART")
            if any(len(p.interiors) for p in getattr(geom, "geoms", [geom])):
                labels.append("HOLES")
            if not (info["cells"] & perimeter_cells):
                labels.append("INTERIOR_SUBDOMAIN")
            line_geom = shapely.line_merge(shapely.MultiLineString(
                [mesh.point_xy[mesh.points[int(f)]] for f in s["faces"]]))
            if len(structures) and structures.geometry.intersects(line_geom).any():
                labels.append("STRUCTURE_ON_SPLIT_LINE")
            row = {"subdomain_id": str(link), "split_line_id": link, "tier": info["tier"],
                   "role": "downstream" if info["upstream"] else "headwater",
                   "upstream_subdomain_ids": [str(u) for u in info["upstream"]],
                   "cell_count": len(info["cells"]),
                   "area_sqmi": float(geom.area * unit_ft ** 2 / SQFT_PER_SQMI),
                   "footprint_cell_count": len(footprints[link]),
                   "dropped_area_sqmi": dropped.get(link, 0.0), "labels": sorted(set(labels))}
            for e in events:
                for name, value in exchange[e].items():
                    row[f"{name}_{e}"] = value
                row[f"leak_fraction_{e}"] = leak[e]
            row["geometry"] = geom
            rows.append(row)
            owned |= info["cells"]
            owner_rows += [(cell, str(link)) for cell in sorted(info["cells"])]
        remainder = sorted(set(physical_ids.tolist()) - owned)
        if remainder:
            geom = _union(cells.geometry.loc[remainder].to_numpy())
            labels = []
            if any(len(p.interiors) for p in getattr(geom, "geoms", [geom])):
                labels.append("HOLES")
            if geom.geom_type == "MultiPolygon":
                labels.append("MULTIPART")
            tops = [str(k) for k, v in nested.items()
                    if not any(k in o["upstream"] for o in nested.values())]
            rows.append({"subdomain_id": REMAINDER_ID, "split_line_id": None,
                         "tier": 1 + max((r["tier"] for r in rows), default=0), "role": "remainder",
                         "upstream_subdomain_ids": tops, "cell_count": len(remainder),
                         "area_sqmi": float(geom.area * unit_ft ** 2 / SQFT_PER_SQMI),
                         "footprint_cell_count": len(remainder), "dropped_area_sqmi": 0.0,
                         "labels": labels, "geometry": geom})
            owner_rows += [(cell, REMAINDER_ID) for cell in remainder]
        subdomains = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
        cell_owner = pd.DataFrame(owner_rows, columns=["cell_id", "subdomain_id"]).sort_values("cell_id",
                                                                                              ignore_index=True)
        tiers = sorted({r["tier"] for r in rows})
        run_order = tuple(tuple(r["subdomain_id"] for r in rows if r["tier"] == t) for t in tiers)
        return SubdomainPartition(subdomains=subdomains, cell_owner=cell_owner,
                                  remainder_id=REMAINDER_ID, run_order=run_order, search=search)

    @staticmethod
    @log_call
    def plan_breakouts(partition: SubdomainPartition, plan_number: Union[str, int], *, ras_object: Any,
                       perimeter_friction_slope: float = 0.01,
                       subdomain_ids: Optional[Sequence[str]] = None):
        """Plan one exact-cell breakout per subdomain; nothing is written.

        For each subdomain (default: all, including the remainder) this records
        the parent cell ids to keep and the BC lines to author, and runs the
        read-only :meth:`RasBreakout2D.preflight` against ``ras_object``:

        - the outlet split line as Normal Depth at the fitted slope;
        - one Flow Hydrograph line per upstream subdomain, carrying the parent's
          own flow across that split line until the upstream child has run;
        - Normal Depth at ``perimeter_friction_slope`` along each stretch of the
          parent perimeter.

        Every other edge is a closed wall, as in the parent. Labels this release
        cannot cut (``HOLES``, ``MULTIPART``, ``STRUCTURE_ON_SPLIT_LINE``) become
        blocking checks.

        Args:
            partition: From :meth:`build_subdomains` (same session).
            plan_number: Parent plan whose geometry the cells come from. Its
                geometry HDF must be the compiled geometry of the searched events.
            ras_object: Initialized parent project (read only).
            perimeter_friction_slope: Normal-depth slope on parent-perimeter stretches.
            subdomain_ids: Plan only these subdomains.

        Returns:
            SubdomainBreakoutPlan; ``is_ready`` is False while a blocking check fails.
        """
        from ._breakouts import plan_breakouts

        return plan_breakouts(partition, plan_number, ras_object=ras_object,
                              perimeter_friction_slope=perimeter_friction_slope,
                              subdomain_ids=subdomain_ids)

    @staticmethod
    @log_call
    def apply_breakouts(breakout_plan, dest_folder: Union[str, Path], *, overwrite_dest: bool = False,
                        hecras_version: Optional[str] = None, time_step: str = "parent_minimum",
                        timeout: int = 1800):
        """Author every planned breakout in one staged working copy of the parent.

        ``RasProject.stage_project`` copies the parent project to ``dest_folder``.
        In that copy each subdomain becomes a cloned plan, geometry and unsteady
        file (:meth:`RasBreakout2D.clone_plan_components`), cut to its exact parent
        cells (``prepare_cloned_geometry(parent_cell_ids=...)``, HEC-RAS 6.6), with
        its BC lines and forcing written by :meth:`GeomBcLines.replace_bc_lines`.
        Meteorology, initial conditions and solver settings are inherited from
        the parent plan. The parent is never modified.

        Every BC line is checked against its compiled external faces after a full
        preprocess; a line HEC-RAS rejects, attaches to no face, shares faces with
        another line, or spreads over the whole perimeter moves to its next
        placement (on the perimeter; offset 1 ft outward with ends trimmed;
        extended; following the perimeter 200, 400 or 800 ft past each end).

        Args:
            breakout_plan: From :meth:`plan_breakouts`, with ``is_ready`` True.
            dest_folder: New folder for the working copy. The copied root is the
                smallest folder holding the project and its RAS Mapper assets;
                parent result HDFs are not copied.
            overwrite_dest: Replace an existing ``dest_folder``.
            hecras_version: Version for the working project (default the parent's).
            time_step: ``"parent_minimum"`` (default) fixes each child at the
                shortest step the parent can take (its base interval halved
                ``Max Halving`` times) with the Courant-adaptive step off. A child
                must not out-step the parent: on Salt Draw headwater 2568 the
                inherited adaptive step gave maximum-WSE differences up to 3.1 ft
                (p95 0.67 ft); the parent minimum, 15 s, gave 0.26 ft (p95 0.018 ft).
                ``"inherit"`` keeps the cloned plan's settings.
            timeout: Seconds allowed per native step.

        Returns:
            SubdomainBreakoutSet
        """
        from ._breakouts import apply_breakouts

        return apply_breakouts(breakout_plan, dest_folder, overwrite_dest=overwrite_dest,
                               hecras_version=hecras_version, time_step=time_step, timeout=timeout)

    @staticmethod
    @log_call
    def validate_breakouts(breakout_set, *, max_wait: int = 3600):
        """Preprocess every child and check each BC line against its compiled external faces.

        A BC line HEC-RAS attaches to no face, or spreads over the whole
        perimeter, fails. Returns a checks DataFrame (``subdomain_id``, ``check``,
        ``passed``, ``blocking``, ``detail``).
        """
        from ._breakouts import validate_breakouts

        return validate_breakouts(breakout_set, max_wait=max_wait)

    @staticmethod
    @log_call
    def compute_subdomains(breakout_set, *, max_workers: int = 2, num_cores: int = 2):
        """Run the children tier by tier, handing each outlet hydrograph downstream.

        Each tier is one :meth:`RasCmdr.compute_parallel` call in the working
        project. Before a tier runs, the summed flow of each upstream child's
        outlet BC line is written as the inline hydrograph of the matching inflow
        line (:meth:`RasUnsteady.set_boundary_inline_hydrograph`). Returns one row
        per subdomain: ``subdomain_id``, ``tier``, ``plan_number``, ``success``,
        ``tier_wall_clock_s``, ``plan_hdf_path``.
        """
        from ._breakouts import compute_subdomains

        return compute_subdomains(breakout_set, max_workers=max_workers, num_cores=num_cores)

    @staticmethod
    @log_call
    def compare_to_parent(breakout_set, parent_plan_hdf_path: Union[str, Path], *,
                          depth_threshold_ft: float = 0.1):
        """Compare each computed child with the parent on the same cells and outlet.

        Child cells are the parent's own cells, matched by centre. Per subdomain:
        maximum-WSE difference (p50, p95, p99, max, mean) over cells wet above
        ``depth_threshold_ft`` in both, wet-extent IoU, and the outlet hydrograph's
        peak, peak time, volume and NSE against the parent's native flow across
        the same split line. No pass/fail: the table reports.
        """
        from ._breakouts import compare_to_parent

        return compare_to_parent(breakout_set, parent_plan_hdf_path, depth_threshold_ft=depth_threshold_ft)
