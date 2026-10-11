"""Bounded support-point plans for under-resolved retained refinement regions."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


__all__ = ["GeomMeshRepair"]


class GeomMeshRepair:
    """Static geometry repair planning and hash-guarded child edits."""

    @staticmethod
    @log_call
    def plan_refinement_support(
        perimeter: Any,
        regions: list[dict[str, Any]],
        existing_points: Any,
        *,
        attempt: int = 0,
        max_points: int = 8192,
    ) -> dict[str, Any]:
        """Plan local seeds without changing any geometry or spacing control.

        Coordinates, dx and dy use one projected CRS and project length units.
        Each supplied valid, hole-free region retains its complete polygon and
        native spacing. A representative interior point anchors a local grid;
        clipped slivers receive spacing at most one third of its boundary clearance.
        Retry attempts halve that spacing. Surrounding support extends one grid
        interval and remains strictly inside the computational perimeter. Existing
        seeds are preserved. Return added XY coordinates and per-region evidence.
        Fail before mutation if the deterministic candidate budget is exceeded.
        For oversized bounding boxes, intersect grid columns with the support
        polygon and bound the examined sites instead. Record both counts; spacing,
        grid ordering and strictly interior candidate selection are unchanged.
        Native recompilation and engineering QA remain the caller's responsibility.
        """
        import numpy as np
        from scipy.spatial import cKDTree
        from shapely.geometry import LineString, Point

        if (
            perimeter.geom_type != "Polygon"
            or not perimeter.is_valid
            or perimeter.is_empty
            or attempt not in range(3)
            or max_points <= 0
        ):
            raise ValueError("valid perimeter and bounded repair settings required")
        original = np.asarray(existing_points, dtype=float)
        if (
            original.ndim != 2
            or original.shape[1] != 2
            or not np.isfinite(original).all()
        ):
            raise ValueError("finite existing XY points required")
        added: list[tuple[float, float]] = []
        evidence = []
        candidate_count = 0
        examined_count = 0
        used_column_intersections = False
        for record in regions:
            polygon = record["geometry"]
            dx, dy = float(record["spacing_dx"]), float(record["spacing_dy"])
            if (
                polygon.geom_type != "Polygon"
                or not polygon.is_valid
                or polygon.is_empty
                or polygon.interiors
                or not perimeter.covers(polygon)
                or not math.isfinite(dx * dy)
                or min(dx, dy) <= 0
            ):
                raise ValueError(
                    "valid contained refinement and positive source spacing required"
                )
            anchor = polygon.representative_point()
            clearance = anchor.distance(polygon.boundary)
            spacing = min(dx, dy, clearance / 3) / (2**attempt)
            if not math.isfinite(spacing) or spacing <= 1e-4:
                raise ValueError(
                    "refinement support spacing is below serialization resolution"
                )
            support = polygon.buffer(spacing).intersection(perimeter)
            left, bottom, right, top = support.bounds
            ix0, ix1 = (
                math.floor((left - anchor.x) / spacing),
                math.ceil((right - anchor.x) / spacing),
            )
            iy0, iy1 = (
                math.floor((bottom - anchor.y) / spacing),
                math.ceil((top - anchor.y) / spacing),
            )
            count = (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
            candidate_count += count
            candidates = []
            if examined_count + count <= max_points:
                examined_count += count
                sites = (
                    (ix, iy) for ix in range(ix0, ix1 + 1) for iy in range(iy0, iy1 + 1)
                )
            else:
                used_column_intersections = True
                if ix1 - ix0 + 1 > max_points:
                    raise ValueError("bounded refinement candidate budget exceeded")
                bounded_sites = []
                for ix in range(ix0, ix1 + 1):
                    x = anchor.x + ix * spacing
                    section = support.intersection(
                        LineString([(x, bottom - spacing), (x, top + spacing)])
                    )
                    pieces = [section]
                    intervals = []
                    while pieces:
                        piece = pieces.pop()
                        if piece.is_empty:
                            continue
                        if hasattr(piece, "geoms"):
                            pieces.extend(piece.geoms)
                            continue
                        _, low, _, high = piece.bounds
                        # Include neighbors to avoid losing a site through
                        # roundoff at a column intersection endpoint.
                        intervals.append(
                            (
                                max(iy0, math.floor((low - anchor.y) / spacing) - 1),
                                min(iy1, math.ceil((high - anchor.y) / spacing) + 1),
                            )
                        )
                    last = iy0 - 1
                    for low, high in sorted(intervals):
                        low = max(low, last + 1)
                        if high < low:
                            continue
                        examined_count += high - low + 1
                        if examined_count > max_points:
                            raise ValueError(
                                "bounded refinement candidate budget exceeded"
                            )
                        bounded_sites.extend((ix, iy) for iy in range(low, high + 1))
                        last = high
                sites = iter(bounded_sites)
            for ix, iy in sites:
                xy = (anchor.x + ix * spacing, anchor.y + iy * spacing)
                point = Point(xy)
                if support.contains(point) and perimeter.contains(point):
                    candidates.append(xy)
            before = len(added)
            combined = np.vstack([original, np.asarray(added).reshape(-1, 2)])
            if len(combined):
                distances = cKDTree(combined).query(candidates)[0] if candidates else []
                candidates = [
                    p
                    for p, distance in zip(candidates, distances, strict=True)
                    if distance > spacing / 4
                ]
            added.extend(candidates)
            evidence.append(
                {
                    "name": record["name"],
                    "source_spacing": [dx, dy],
                    "support_spacing": spacing,
                    "interior_clearance": clearance,
                    "anchor_xy": [anchor.x, anchor.y],
                    "region_wkb": polygon.wkb_hex,
                    "added_point_count": len(added) - before,
                }
            )
        result = {
            "method": "interior_anchored_refinement_support_grid",
            "attempt": attempt,
            "max_points": max_points,
            "candidate_count": candidate_count,
            "added_points": [list(p) for p in added],
            "regions": evidence,
            "perimeter_changed": False,
            "features_changed": False,
            "source_spacing_changed": False,
            "existing_points_removed": 0,
        }
        if used_column_intersections:
            result.update(
                candidate_generation="bounded_support_column_intersections",
                examined_candidate_count=examined_count,
            )
        return result

    @staticmethod
    @log_call
    def apply_refinement_support(
        geometry: str | Path,
        mesh_name: str,
        existing_points: Any,
        plan: dict[str, Any],
        *,
        expected_geometry_sha256: str,
    ) -> dict[str, Any]:
        """Apply a support plan to hash-guarded attempt-owned geometry text.

        Inputs use the text's projected CRS/project units. The caller must provide
        the serialized existing XY seeds from the same inspected geometry hash.
        Preserve their ordering, append finite unique interior planned points, and
        replace only the selected area's point block through the existing writer.
        Return before/after hashes and the full plan. Never use on source projects.
        Recompile natively and verify perimeter, controls, points and all QA gates.
        """
        import numpy as np
        from shapely.geometry import Point, Polygon

        from ras_commander.geom.GeomMesh import _patch_text_seeds
        from ras_commander.geom.GeomParser import GeomParser
        from ras_commander.geom.GeomStorage import GeomStorage

        path = Path(geometry)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != expected_geometry_sha256:
            raise ValueError("geometry changed since refinement inspection")
        original = np.asarray(existing_points, dtype=float).reshape(-1, 2)
        added = np.asarray(plan["added_points"], dtype=float).reshape(-1, 2)
        block = GeomStorage._find_storage_area_block(
            path.read_text(encoding="utf-8").splitlines(keepends=True), mesh_name
        )
        if block is None:
            raise ValueError("named child area missing from inspected geometry")
        info = GeomStorage._inspect_storage_area_block(block[2])
        index = info["points_idx"]
        if index is None or not info["is_2d"]:
            raise ValueError("serialized 2D child seeds required")
        count = int(block[2][index].split("=", 1)[1])
        values = [
            v
            for line in block[2][index + 1 : info["points_end"]]
            for v in GeomParser.parse_fixed_width(line, column_width=16)
        ]
        serialized = np.asarray(values, dtype=float).reshape(-1, 2)
        if count != len(serialized) or not np.array_equal(original, serialized):
            raise ValueError(
                "support plan existing points differ from serialized geometry"
            )
        perimeter = Polygon(GeomStorage._parse_surface_line_coords(block[2], info))
        if not perimeter.is_valid or not all(
            perimeter.contains(Point(p)) for p in added
        ):
            raise ValueError(
                "support points must be strictly inside serialized perimeter"
            )
        combined = np.vstack([original, added])
        if (
            not len(added)
            or not np.isfinite(combined).all()
            or len(np.unique(combined, axis=0)) != len(combined)
        ):
            raise ValueError("refinement support requires finite unique added points")
        _patch_text_seeds(path, combined, mesh_name=mesh_name)
        return {
            **plan,
            "geometry_before_sha256": before,
            "geometry_after_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "added_point_count": len(added),
        }

    @staticmethod
    @log_call
    def plan_compiled_polygon_seed_removal(
        existing_points: Any,
        compiled_centers: Any,
        diagnostics: list[dict[str, Any]],
        *,
        max_removals: int = 32,
    ) -> dict[str, Any]:
        """Plan removal of seeds whose compiled physical cells lack one polygon.

        Inputs are native-index-ordered physical centers and serialized XY seeds
        in one projected CRS/project unit system, plus public HdfMesh polygon
        diagnostics. Require equal counts and every indexed coordinate within
        1e-6 units. Only no_polygon/multiple_polygons authorize a bounded removal;
        ghost cells and unrelated diagnostics never do. Return complete evidence,
        mutate nothing. Native recompilation, exhaustive polygon reconstruction,
        feature checks and engineering review remain required.
        """
        import numpy as np

        original = np.asarray(existing_points, dtype=float)
        compiled = np.asarray(compiled_centers, dtype=float)
        if (
            original.ndim != 2
            or original.shape[1] != 2
            or original.shape != compiled.shape
            or not len(original)
            or not np.isfinite(original).all()
            or not np.isfinite(compiled).all()
            or isinstance(max_removals, bool)
            or max_removals not in range(1, 33)
        ):
            raise ValueError(
                "finite equal-count physical/serialized XY arrays required"
            )
        error = float(np.linalg.norm(original - compiled, axis=1).max())
        if error > 1e-6:
            raise ValueError(
                "compiled physical centers differ from indexed serialized seeds"
            )
        selected = {}
        for row in diagnostics:
            index = row.get("cell_id")
            if index is None or row.get("reason_code") not in {
                "no_polygon",
                "multiple_polygons",
            }:
                continue
            if (
                isinstance(index, bool)
                or not math.isfinite(float(index))
                or int(index) != index
            ):
                raise ValueError("native polygon diagnostic cell ID must be integral")
            index = int(index)
            if not 0 <= index < len(original):
                continue
            faces, polygons = row.get("face_count"), row.get("polygon_count")
            if (
                faces is None
                or polygons is None
                or not math.isfinite(float(faces))
                or int(faces) != faces
                or faces < 3
                or not math.isfinite(float(polygons))
                or int(polygons) != polygons
                or (
                    row["reason_code"] == "no_polygon"
                    and (polygons != 0 or row.get("status") != "omitted")
                )
                or (
                    row["reason_code"] == "multiple_polygons"
                    and (polygons < 2 or row.get("status") != "ambiguous")
                )
            ):
                raise ValueError("compiled physical polygon diagnostic is inconsistent")
            if index in selected:
                raise ValueError("native polygon diagnostic cell ID is duplicated")
            selected[index] = {**row, "cell_id": index}
        if len(selected) > max_removals or len(selected) == len(original):
            raise ValueError(
                "compiled polygon repair exceeds bounded seed-removal budget"
            )
        return {
            "schema": "ras-compiled-polygon-seed-repair/v1",
            "method": "compiled_polygon_omission_seed_removal",
            "max_removals": max_removals,
            "physical_cell_count": len(original),
            "maximum_index_matched_displacement": error,
            "removed_points": [
                {
                    "generated_point_index": i,
                    "x": float(original[i, 0]),
                    "y": float(original[i, 1]),
                    "polygon_diagnostic": selected[i],
                }
                for i in sorted(selected)
            ],
            "perimeter_changed": False,
            "features_changed": False,
        }

    @staticmethod
    @log_call
    def plan_native_seed_removal(mesh: Any, seeds: Any) -> dict[str, Any]:
        """Identify generated seeds implicated by specific native topology errors.

        Read only native MeshFV2D and PointMs in their projected project units.
        For FacePerimeterConnectionError require native BadIndexes; for
        CellMinFaceError require fewer than three faces. In either case, prove
        that each cell's native point matches the same indexed serialized seed
        within 1e-6 project units. Return an explicit removal plan; change nothing.
        Perimeter vertices and unrelated native errors never authorize removals.
        """
        state = str(mesh.MeshCompletionState)
        if state == "FacePerimeterConnectionError":
            from ras_commander.geom.GeomMesh import _bad_seed_indexes

            candidates = _bad_seed_indexes(mesh, seeds.Count)
        elif state == "CellMinFaceError":
            candidates = {
                i
                for i in range(int(mesh.NonVirtualCellCount))
                if mesh.CellFacesCount(i) < 3
            }
        else:
            candidates = set()
        removals = []
        for index in sorted(candidates):
            if not 0 <= index < seeds.Count:
                continue
            point, seed = mesh.Cell(index).Point, seeds[index]
            if (
                math.hypot(
                    float(point.X) - float(seed.X), float(point.Y) - float(seed.Y)
                )
                <= 1e-6
            ):
                removals.append(
                    {
                        "generated_point_index": index,
                        "x": float(seed.X),
                        "y": float(seed.Y),
                    }
                )
        return {
            "method": "native_identified_generated_seed_removal",
            "native_state": state,
            "removed_points": removals,
            "perimeter_changed": False,
            "features_changed": False,
        }

    @staticmethod
    @log_call
    def repair_refinement_polygon(polygon: Any) -> tuple[Any, dict[str, Any]]:
        """Return GEOS-valid polygon coverage and complete source-repair evidence.

        Read only a delivered polygon in its projected CRS/project units. Preserve
        every positive-area GEOS make_valid component; keep holes as holes. Record
        non-polygon remnants, area and WKB identities without mutating the input.
        Degenerate zero-area records return empty polygon coverage, with evidence.
        """
        from .GeomMesh import _repair_refinement_polygon

        return _repair_refinement_polygon(polygon)
