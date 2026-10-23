"""Supplied-seed repair from the retained Salt Draw subdomain authoring recipe.

Native previews reuse GeomMesh's repair helpers. Planning never writes the
caller geometry; application replaces only its text after an identity check.
"""

from __future__ import annotations

import hashlib
import importlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from shapely import contains_xy
from shapely.geometry import LineString, Point, Polygon


@dataclass(frozen=True)
class ComputationPointRepairPlan:
    """Bound text replacement and preview evidence, in geometry CRS/units.

    This is an operation plan, not proof of compiled topology or hydraulic
    equivalence. ``to_dict`` exposes review evidence without the text payload.
    """

    geometry_path: str
    geometry_sha256: str
    mesh_name: str
    geometry_bytes_after: bytes
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible identities, repaired points and diagnostics."""
        return {
            "schema": "ras-computation-point-repair/v1",
            "geometry_path": self.geometry_path,
            "geometry_sha256": self.geometry_sha256,
            "mesh_name": self.mesh_name,
            "geometry_sha256_after": hashlib.sha256(
                self.geometry_bytes_after
            ).hexdigest(),
            **self.evidence,
        }


def _native_polygon(ring, ns):
    points = ns["PointMs"]()
    for x, y in ring:
        points.Add(ns["PointM"](float(x), float(y)))
    return ns["Polygon"](points)


def _preview(ring, points, ratio, ns, gm, constraints=None):
    seeds = ns["PointMs"]()
    for x, y in points:
        seeds.Add(ns["PointM"](float(x), float(y)))
    perimeter = _native_polygon(ring, ns)
    return gm._compute_mesh(perimeter, seeds, constraints, ratio, ns), perimeter, seeds


class _RepairLossError(RuntimeError):
    def __init__(self, evidence):
        self.repair_evidence = evidence
        super().__init__(f"Supplied-seed repair loss limit exceeded: {evidence}")


def _repair(
    ring,
    points,
    cell_size,
    ns,
    gm,
    constraints=None,
    max_parent_seed_loss_fraction=0.001,
    max_area_loss_fraction=0.001,
):
    """Bound midpoint/perimeter repairs, including MaxFaces after every cut."""
    for value in (max_parent_seed_loss_fraction, max_area_loss_fraction):
        if isinstance(value, bool) or not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(
                "repair loss fractions must be finite numbers between zero and one"
            )
    points = [tuple(map(float, p)) for p in points]
    original_points = list(points)
    ring = np.asarray(ring, dtype=float)
    if np.array_equal(ring[0], ring[-1]):
        ring = ring[:-1]
    original_ring = ring.copy()
    original_polygon = Polygon(ring)
    original_set = set(original_points)
    maxfaces, perimeter_rounds, excluded = [], [], []
    repairs_used = 0

    def loss_evidence():
        polygon = Polygon(ring)
        retained = {tuple(p) for p in points}
        dropped = [list(p) for p in original_points if p not in retained]
        area_lost = float(original_polygon.difference(polygon).area)
        evidence = {
            "parent_seed_count": len(original_points),
            "dropped_parent_points": dropped,
            "dropped_parent_fraction": len(dropped) / len(original_points),
            "area_lost": area_lost,
            "area_lost_fraction": area_lost / original_polygon.area,
            "max_parent_seed_loss_fraction": max_parent_seed_loss_fraction,
            "max_area_loss_fraction": max_area_loss_fraction,
        }
        if (
            evidence["dropped_parent_fraction"] > max_parent_seed_loss_fraction
            or evidence["area_lost_fraction"] > max_area_loss_fraction
        ):
            raise _RepairLossError(evidence)
        return evidence

    def repair_maxfaces(phase):
        nonlocal repairs_used
        while True:
            counts, midpoints = {}, []
            for ratio in (0.0025, 0.05, 0.1):
                mesh, perimeter, seeds = _preview(
                    ring, points, ratio, ns, gm, constraints
                )
                count = sum(
                    mesh.CellFacesCount(i) > 8 for i in range(mesh.NonVirtualCellCount)
                )
                counts[str(ratio)] = int(count)
                if count and repairs_used < 7:
                    _, _, added = gm._autofix_max_faces(
                        mesh,
                        [seeds[i] for i in range(seeds.Count)],
                        ns,
                        perimeter=perimeter,
                        midpoint_round_decimals=3,
                    )
                    # The owning helper rounds before its move-inside step.
                    # Preserve that inset coordinate; deduplicate by exact equality.
                    midpoints.extend((float(p.X), float(p.Y)) for p in added)
            maxfaces.append(
                {
                    "phase": phase,
                    "repairs_used": repairs_used,
                    "seeds": len(points),
                    "cells_over_8": counts,
                }
            )
            if not any(counts.values()):
                return
            if repairs_used >= 7:
                raise RuntimeError(
                    "Supplied-seed MaxFaces repair did not converge within seven repairs"
                )
            seen = set(points)
            added = list(dict.fromkeys(p for p in midpoints if p not in seen))
            if not added:
                raise RuntimeError("Supplied-seed MaxFaces repair made no progress")
            points.extend(added)
            repairs_used += 1

    repair_maxfaces("initial")
    for attempt in range(6):
        mesh, _, _ = _preview(ring, points, 0.05, ns, gm, constraints)
        record = {
            "round": attempt,
            "state": str(mesh.MeshCompletionState),
            "vertices": len(ring),
        }
        perimeter_rounds.append(record)
        if int(mesh.MeshCompletionState) != int(
            ns["MeshStatus"].FacePerimeterConnectionError
        ):
            break
        locations = gm._find_error_locations(mesh, cell_size, 0.05)
        indexes = sorted(
            {
                int(np.argmin(np.linalg.norm(ring - location, axis=1)))
                for location in locations
            }
        )
        if not indexes or len(ring) - len(indexes) < 3:
            raise RuntimeError("Supplied-seed perimeter repair made no valid progress")
        record["removed_vertices"] = ring[indexes].tolist()
        ring = np.delete(ring, indexes, axis=0)
        polygon = Polygon(ring)
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
            raise RuntimeError(
                "Supplied-seed perimeter repair produced an invalid polygon"
            )
        array = np.asarray(points)
        keep = contains_xy(polygon, array[:, 0], array[:, 1])
        excluded.extend(array[~keep].tolist())
        points = [tuple(p) for p in array[keep]]
        if not points:
            raise RuntimeError("Supplied-seed perimeter repair excluded all seeds")
        record["loss"] = loss_evidence()
        repair_maxfaces(f"after_perimeter_{attempt}")
    polygon = Polygon(ring)
    gm._validated_computation_points(points, polygon)
    loss = loss_evidence()
    final = []
    for ratio in (0.0025, 0.05, 0.1):
        mesh, _, _ = _preview(ring, points, ratio, ns, gm, constraints)
        count = sum(mesh.CellFacesCount(i) > 8 for i in range(mesh.NonVirtualCellCount))
        final.append(
            {
                "ratio": ratio,
                "state": str(mesh.MeshCompletionState),
                "cells_over_8": int(count),
            }
        )
        if count or int(mesh.MeshCompletionState) != int(ns["MeshStatus"].Complete):
            raise RuntimeError(f"Supplied-seed repair did not converge: {final[-1]}")
    return (
        ring,
        np.asarray(points),
        {
            "supplied_points": [list(p) for p in original_points],
            "parent_seed_count": len(original_points),
            "final_seed_count": len(points),
            "added_points": [list(p) for p in points if p not in original_set],
            **loss,
            "excluded_points_after_perimeter_repair": excluded,
            "perimeter_before": original_ring.tolist(),
            "perimeter_after": ring.tolist(),
            "maxfaces_rounds": maxfaces,
            "perimeter_rounds": perimeter_rounds,
            "final_previews": final,
        },
    )


def _runtime_directory(hecras_dir, ras_object):
    selected = None
    if ras_object is not None:
        raw = str(getattr(ras_object, "ras_exe_path", "") or "")
        if raw and raw.lower() != "ras.exe":
            executable = Path(raw).resolve()
            if not executable.is_file() or executable.name.lower() != "ras.exe":
                raise FileNotFoundError("Project must select an existing Ras.exe")
            selected = executable.parent
    if hecras_dir is not None:
        explicit = Path(hecras_dir).resolve()
        if selected is not None and explicit != selected:
            raise ValueError("hecras_dir conflicts with the project's selected Ras.exe")
        selected = explicit
    if selected is None or any(
        not (selected / filename).is_file()
        for filename in ("Ras.exe", "RasMapperLib.dll")
    ):
        raise FileNotFoundError(
            "Select a project runtime or explicit hecras_dir containing RasMapperLib.dll"
        )
    return selected


def _text_constraints(path, name):
    from .._ras_text import _split_ras_records
    from ._preprocess_contract import _text_features
    from .GeomLateral import GeomLateral

    lines = _split_ras_records(path.read_text(encoding="utf-8"))
    breaklines = [
        feature
        for feature in _text_features(lines, "BreakLine Name=", "BreakLine Polyline=")
        if feature["storage_area"] in (name, "")
    ]
    connections = GeomLateral.get_connection_data(path)
    connections = connections[connections["From"].eq(name) | connections["To"].eq(name)]
    coordinates = [feature["coordinates"] for feature in breaklines]
    for _, row in connections.iterrows():
        coords = row["LineCoordinates"]
        if len(coords) < 2:
            raise ValueError(
                f"Connection {row['Name']} has no verified constraint line"
            )
        coordinates.append(coords[["X", "Y"]].to_numpy())
    return breaklines, coordinates


def _native_constraints(coordinates, ns):
    if not coordinates:
        return None
    layer = ns["PolylineFeatureLayer"]("supplied-seed-constraints")
    for coords in coordinates:
        points = ns["PointMs"]()
        for x, y in coords:
            points.Add(ns["PointM"](float(x), float(y)))
        layer.AddFeature(ns["Polyline"](points))
    return layer.CopyToMultiPartPolyline()


def _audit_text_features(path, name, polygon, allow_extended_connection_support=False):
    from .GeomBcLines import GeomBcLines
    from .GeomLateral import GeomLateral

    breaklines, _ = _text_constraints(path, name)
    checked = []
    for feature in breaklines:
        inside = polygon.covers(LineString(feature["coordinates"]))
        checked.append({"type": "breakline", "name": feature["name"], "inside": inside})
        if not inside:
            raise RuntimeError(
                f"Repaired perimeter excludes kept breakline {feature['name']}"
            )
    for row in GeomBcLines.get_bc_lines(path).to_dict("records"):
        if row["storage_area"] != name:
            continue
        distances = [
            float(polygon.boundary.distance(Point(p)))
            for p in (row["coordinates"][0], row["coordinates"][-1])
        ]
        checked.append(
            {"type": "bc_line", "name": row["name"], "endpoint_distances": distances}
        )
        if max(distances) > 1e-6:
            raise RuntimeError(
                f"BC line {row['name']} endpoints no longer touch the repaired perimeter"
            )
    connections = GeomLateral.classify_connections(
        path, polygon, allow_extended_support=allow_extended_connection_support
    )
    for row in connections.to_dict("records"):
        if row["From"] != name and row["To"] != name:
            continue
        checked.append(
            {
                "type": "connection",
                "name": row["Name"],
                "action": row["action"],
                "reason": row["reason"],
            }
        )
        if row["action"] != "keep":
            raise RuntimeError(
                f"Repaired perimeter fails connection containment for {row['Name']}: {row['reason']}"
            )
    return {"ok": True, "checks": checked, "bc_endpoint_tolerance": 1e-6}


def _loaded_runtime_directory(ns):
    """Inspect the assembly actually loaded; CLR cannot switch native runtimes."""
    import clr

    return Path(str(clr.GetClrType(ns["MeshFV2D"]).Assembly.Location)).resolve().parent


def _plan(
    geom_number,
    computation_points,
    mesh_name,
    mesh_index,
    hecras_dir,
    ras_object,
    max_parent_seed_loss_fraction,
    max_area_loss_fraction,
    allow_extended_connection_support,
):
    from .GeomStorage import GeomStorage

    gm = importlib.import_module("ras_commander.geom.GeomMesh")
    if ras_object is None and (
        not isinstance(geom_number, (str, Path)) or not Path(geom_number).is_file()
    ):
        raise ValueError(
            "Without ras_object, pass an explicit existing geometry text path"
        )
    path = gm._resolve_geom_text_path(geom_number, ras_object).resolve()
    original = path.read_bytes()
    try:
        text, encoding = original.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = original.decode("cp1252"), "cp1252"
    install = _runtime_directory(hecras_dir, ras_object)
    gm._load_dlls(install)
    ns = gm._imports()
    if _loaded_runtime_directory(ns) != install:
        raise RuntimeError(
            "Loaded RasMapperLib conflicts with the selected project runtime; use a fresh worker"
        )
    with tempfile.TemporaryDirectory(
        prefix=".ras-seed-plan-", dir=path.parent
    ) as scratch:
        staged = Path(scratch) / path.name
        staged.write_bytes(text.encode("utf-8"))
        areas = GeomStorage.get_storage_area_polygons(staged, exclude_2d=False)
        areas = areas[areas["is_2d"]] if "is_2d" in areas else areas
        if mesh_name is not None:
            areas = areas[areas["Name"].eq(mesh_name)]
        elif mesh_index >= 0:
            areas = areas.iloc[mesh_index : mesh_index + 1]
        else:
            raise ValueError("mesh_index must be nonnegative")
        if len(areas) != 1:
            raise ValueError("exactly one matching 2D flow area is required")
        area = areas.iloc[0]
        name = str(area["Name"])
        points = gm._validated_computation_points(computation_points, area.geometry)
        cell_size = gm._read_cell_size_from_text(staged, mesh_name=name)
        if cell_size is None or not np.isfinite(cell_size) or cell_size <= 0:
            raise ValueError(
                "positive cell spacing is required for native perimeter diagnostics"
            )
        _, constraint_coordinates = _text_constraints(staged, name)
        constraints = _native_constraints(constraint_coordinates, ns)
        ring, points, evidence = _repair(
            list(area.geometry.exterior.coords),
            points,
            cell_size,
            ns,
            gm,
            constraints,
            max_parent_seed_loss_fraction,
            max_area_loss_fraction,
        )
        GeomStorage.set_2d_flow_area_perimeter(
            staged, name, geometry=Polygon(ring), create_backup=False
        )
        # Reparse the native text ring; never preview one precision then apply another.
        actual = GeomStorage.get_storage_area_polygons(staged, exclude_2d=False)
        polygon = actual[actual["Name"].eq(name)].geometry.iloc[0]
        original_polygon = Polygon(evidence["perimeter_before"])
        evidence["area_lost"] = float(original_polygon.difference(polygon).area)
        evidence["area_lost_fraction"] = evidence["area_lost"] / original_polygon.area
        evidence["native_constraint_count"] = len(constraint_coordinates)
        if evidence["area_lost_fraction"] > max_area_loss_fraction:
            raise _RepairLossError(evidence)
        evidence["feature_audit"] = _audit_text_features(
            staged, name, polygon, allow_extended_connection_support
        )
        constraints = _native_constraints(_text_constraints(staged, name)[1], ns)
        native_points = np.asarray(
            [
                [float(gm._format_seed_coordinate(float(v), strict=True)) for v in p]
                for p in points
            ]
        )
        gm._validated_computation_points(native_points, polygon)
        for ratio in (0.0025, 0.05, 0.1):
            mesh, _, _ = _preview(
                list(polygon.exterior.coords), native_points, ratio, ns, gm, constraints
            )
            if int(mesh.MeshCompletionState) != int(ns["MeshStatus"].Complete) or any(
                mesh.CellFacesCount(i) > 8 for i in range(mesh.NonVirtualCellCount)
            ):
                raise RuntimeError("Serialized supplied-seed mesh fails native preview")
        gm._patch_text_seeds(staged, native_points, mesh_name=name)
        evidence.update(
            runtime_directory=str(install),
            cell_size=float(cell_size),
            serialized_points=native_points.tolist(),
            serialized_perimeter=list(polygon.exterior.coords),
        )
        after = staged.read_bytes().decode("utf-8").encode(encoding)
    if path.read_bytes() != original:
        raise RuntimeError("Geometry changed during supplied-seed repair planning")
    return ComputationPointRepairPlan(
        str(path), hashlib.sha256(original).hexdigest(), name, after, evidence
    )


def _validate(plan):
    if not isinstance(plan, ComputationPointRepairPlan):
        raise TypeError("plan must be a ComputationPointRepairPlan")
    actual = Path(plan.geometry_path).read_bytes()
    if actual != plan.geometry_bytes_after:
        raise RuntimeError(
            "Applied supplied-seed geometry does not match the reviewed plan"
        )
    return {
        "ok": True,
        "geometry_sha256": hashlib.sha256(actual).hexdigest(),
        "final_seed_count": plan.evidence["final_seed_count"],
    }


def _apply(plan):
    from .GeomMeshDataclasses import MeshSeedRepairResult
    from .GeomParser import GeomParser

    if not isinstance(plan, ComputationPointRepairPlan):
        raise TypeError("plan must be a ComputationPointRepairPlan")
    path = Path(plan.geometry_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != plan.geometry_sha256:
        raise RuntimeError("Geometry changed after supplied-seed repair planning")
    with tempfile.TemporaryDirectory(
        prefix=".ras-seed-apply-", dir=path.parent
    ) as scratch:
        staged = Path(scratch) / path.name
        staged.write_bytes(plan.geometry_bytes_after)
        GeomParser.create_backup(path)
        staged.replace(path)
    validation = _validate(plan)
    return MeshSeedRepairResult(
        mesh_name=plan.mesh_name,
        status="complete",
        operation="computation_points",
        cell_count=plan.evidence["final_seed_count"],
        geom_text_path=str(path),
        seed_repair={**plan.to_dict(), "application_validation": validation},
    )
