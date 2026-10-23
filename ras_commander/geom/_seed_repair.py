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
from shapely.geometry import Polygon


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


def _preview(ring, points, ratio, ns, gm):
    seeds = ns["PointMs"]()
    for x, y in points:
        seeds.Add(ns["PointM"](float(x), float(y)))
    perimeter = _native_polygon(ring, ns)
    return gm._compute_mesh(perimeter, seeds, None, ratio, ns), perimeter, seeds


def _repair(ring, points, cell_size, ns, gm):
    """Port research ordering: MaxFaces across three ratios, then perimeter."""
    points = [tuple(map(float, p)) for p in points]
    original_points = list(points)
    ring = np.asarray(ring, dtype=float)
    if np.array_equal(ring[0], ring[-1]):
        ring = ring[:-1]
    original_ring = ring.copy()
    maxfaces, perimeter_rounds = [], []
    for attempt in range(7):
        counts, midpoints = {}, []
        for ratio in (0.0025, 0.05, 0.1):
            mesh, perimeter, seeds = _preview(ring, points, ratio, ns, gm)
            count = sum(
                mesh.CellFacesCount(i) > 8 for i in range(mesh.NonVirtualCellCount)
            )
            counts[str(ratio)] = int(count)
            if count:
                _, _, added = gm._autofix_max_faces(
                    mesh,
                    [seeds[i] for i in range(seeds.Count)],
                    ns,
                    perimeter=perimeter,
                )
                midpoints.extend(
                    (round(float(p.X), 3), round(float(p.Y), 3)) for p in added
                )
        maxfaces.append(
            {"round": attempt, "seeds": len(points), "cells_over_8": counts}
        )
        if not any(counts.values()):
            break
        seen = set(points)
        added = list(dict.fromkeys(p for p in midpoints if p not in seen))
        if not added:
            raise RuntimeError("Supplied-seed MaxFaces repair made no progress")
        points.extend(added)

    for attempt in range(6):
        mesh, _, _ = _preview(ring, points, 0.05, ns, gm)
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

    # The research discards seeds excluded by its repaired perimeter. Record
    # their identities, then require fresh previews on the actual final set.
    polygon = Polygon(ring)
    array = np.asarray(points)
    keep = contains_xy(polygon, array[:, 0], array[:, 1])
    dropped = array[~keep].tolist()
    points = array[keep]
    gm._validated_computation_points(points, polygon)
    final = []
    for ratio in (0.0025, 0.05, 0.1):
        mesh, _, _ = _preview(ring, points, ratio, ns, gm)
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
    original_set = set(original_points)
    final_set = {tuple(p) for p in points}
    return (
        ring,
        points,
        {
            "supplied_points": [list(p) for p in original_points],
            "parent_seed_count": len(original_points),
            "final_seed_count": len(points),
            "added_points": [
                list(p) for p in map(tuple, points) if p not in original_set
            ],
            "dropped_parent_points": [
                list(p) for p in original_points if p not in final_set
            ],
            "excluded_points_after_perimeter_repair": dropped,
            "perimeter_before": original_ring.tolist(),
            "perimeter_after": ring.tolist(),
            "maxfaces_rounds": maxfaces,
            "perimeter_rounds": perimeter_rounds,
            "final_previews": final,
        },
    )


def _runtime_directory(hecras_dir, ras_object):
    if ras_object is None:
        from ..RasPrj import ras

        ras_object = ras if getattr(ras, "initialized", False) else None
    selected = None
    if ras_object is not None:
        executable = Path(ras_object.ras_exe_path).resolve()
        if not executable.is_file() or executable.name.lower() != "ras.exe":
            raise FileNotFoundError("Project must select an existing Ras.exe")
        selected = executable.parent
    if hecras_dir is not None:
        explicit = Path(hecras_dir).resolve()
        if selected is not None and explicit != selected:
            raise ValueError("hecras_dir conflicts with the project's selected Ras.exe")
        selected = explicit
    if selected is None or not (selected / "RasMapperLib.dll").is_file():
        raise FileNotFoundError(
            "Select a project runtime or explicit hecras_dir containing RasMapperLib.dll"
        )
    return selected


def _loaded_runtime_directory(ns):
    """Inspect the assembly actually loaded; CLR cannot switch native runtimes."""
    import clr

    return Path(str(clr.GetClrType(ns["MeshFV2D"]).Assembly.Location)).resolve().parent


def _plan(
    geom_number, computation_points, mesh_name, mesh_index, hecras_dir, ras_object
):
    from .GeomStorage import GeomStorage

    gm = importlib.import_module("ras_commander.geom.GeomMesh")
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
        ring, points, evidence = _repair(
            list(area.geometry.exterior.coords), points, cell_size, ns, gm
        )
        GeomStorage.set_2d_flow_area_perimeter(
            staged, name, geometry=Polygon(ring), create_backup=False
        )
        # Reparse the native text ring; never preview one precision then apply another.
        actual = GeomStorage.get_storage_area_polygons(staged, exclude_2d=False)
        polygon = actual[actual["Name"].eq(name)].geometry.iloc[0]
        native_points = np.asarray(
            [
                [float(gm._format_seed_coordinate(float(v), strict=True)) for v in p]
                for p in points
            ]
        )
        gm._validated_computation_points(native_points, polygon)
        for ratio in (0.0025, 0.05, 0.1):
            mesh, _, _ = _preview(
                list(polygon.exterior.coords), native_points, ratio, ns, gm
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
