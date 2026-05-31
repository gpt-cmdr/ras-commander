"""
GeomMesh - Headless 2D mesh generation, repair, and BC conflict resolution.

Provides headless (no-GUI) mesh generation via RasMapperLib.dll + pythonnet.
Replaces the need for RAS Mapper or RasProcess.exe for mesh operations.

Architecture: Text-First, Existing-HDF Workspace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The .g## plain text file is the sole persistent output and source of truth.
HEC-RAS preprocessing reads "Storage Area 2D Points= N" plus the XY seed
coordinates from text and regenerates the mesh — overriding any HDF content.

The HDF (.g##.hdf) is used only as a *temporary workspace*:
  - .NET RASGeometry loads geometry from HDF (perimeter, breaklines)
  - geom.Save() writes cell centers to HDF so we can bulk-read via h5py
  - ras-commander does not generate .g##.hdf from .g## text; that remains
    a full HEC-RAS/Ras.exe responsibility

Production Workflow (generate)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Breakline spacing** — Read per-breakline CellSize Min/Max from .g01 text.
   Only overwrite if the caller explicitly passes bl_spacing_near/bl_spacing_far.
2. **Existing HDF validation** — Require a current .g##.hdf compiled by
   HEC-RAS/Ras.exe before any mesh-generation work begins.
3. **Text → HDF sync** — Sync per-breakline spacing from text into the HDF so
   RegenerateMeshPoints (which reads HDF, not text) uses correct values.
4. **Load .NET geometry** — RASGeometry(hdf_path) → D2FlowArea → perimeter,
   breaklines (merged BreakLines + Regions + Structures via _build_breaklines).
5. **Generate seeds** — Primary: RegenerateMeshPoints (private .NET method via
   reflection) produces breakline-aware seeds. Fallback: PointGenerator.
   GeneratePoints(perim, cell_size) for base-grid seeds.
6. **Fix loop** (matches TryAutoFix tier ordering):
   - Tier 0: Pre-flight removal of short perimeter segments
   - Tier 1: DuplicatePoints → remove duplicate seed points
   - Tier 2 first: MaxFacesPerCellExceeded → add midpoint seeds
   - Tier 3: FacePerimeterConnectionError → remove bad perimeter vertices
   - Tier 4: Ratio escalation [0.05 → 0.10 → 0.15 → 0.25]
   - Tier 5: Douglas-Peucker perimeter simplification (last resort)
7. **Extract cell centers** — geom.Save() + h5py read (fast), or .NET Cell(i)
   iteration (slow fallback).
8. **Write .g01 text** — _patch_text_seeds() writes cell centers as the sole
   persistent output. _set_point_generation_data() updates the seed count header.

Requires:
    - Windows (HEC-RAS / RasMapperLib is Windows-only)
    - pythonnet >= 3.0.5: pip install pythonnet
    - HEC-RAS 6.6 installed (provides RasMapperLib.dll + GDAL)
    - HEC-RAS GDAL runtime, configured automatically before RasMapperLib loads

All methods are static — no instantiation needed.

Ported from G:\\GH\\RASDecomp\\headless_mesh\\mesh_fix.py and mesh_bc_fix.py.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from numbers import Number
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from ..Decorators import log_call
from .._gdal_runtime import (
    configure_hecras_gdal_runtime,
    configure_rasmapper_gdal_bridge,
)
from .._geometry_association import (
    GEOMETRY_ASSOCIATION_FIELDS,
    compare_geometry_association_paths,
    decode_hdf_attr as _shared_decode_hdf_attr,
    ensure_geometry_group,
    read_geometry_association,
    resolve_association_attr_path as _shared_resolve_association_attr_path,
)
from ..LoggingConfig import get_logger
from .GeomMeshDataclasses import BCConflict, BCFixResult, MeshResult

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_HECRAS_SEARCH_PATHS = [
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\7.0"),
    Path(r"C:\Program Files\HEC\HEC-RAS\7.0"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5"),
    Path(r"C:\Program Files\HEC\HEC-RAS\6.6"),
]

_DEPS = ["Utility.Core", "Geospatial.Core", "H5Assist", "RasMapperLib"]

MAX_FACES_PER_CELL = 8
PERIMETER_NEAR_DUPLICATE_TOL = 1e-6
_RATIO_LADDER = [0.05, 0.10, 0.15, 0.25]
_GEOMETRY_ASSOCIATION_FIELDS = GEOMETRY_ASSOCIATION_FIELDS

# ── Module-level state ────────────────────────────────────────────────────────

_dlls_loaded = False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _find_hecras_dir() -> Path:
    for p in _HECRAS_SEARCH_PATHS:
        if (p / "RasMapperLib.dll").exists():
            return p
    raise FileNotFoundError(
        "HEC-RAS 6.6 not found. Searched: "
        + ", ".join(str(p) for p in _HECRAS_SEARCH_PATHS)
    )


def _load_dlls(hecras_dir: Optional[str | Path] = None) -> None:
    global _dlls_loaded
    if _dlls_loaded:
        return
    if platform.system() != "Windows":
        raise RuntimeError("GeomMesh requires Windows (RasMapperLib is Windows-only)")

    try:
        import clr  # noqa: F401
    except ImportError:
        raise ImportError(
            "pythonnet is required for mesh operations: pip install pythonnet"
        )

    if hecras_dir is None:
        hecras_dir = _find_hecras_dir()
    hecras_dir = str(hecras_dir)

    if not GeomMesh.setup_gdal_bridge(hecras_dir=hecras_dir, create_junction=True):
        raise RuntimeError(
            "Cannot load RasMapperLib.dll because the HEC-RAS GDAL bridge "
            "could not be initialized."
        )

    if hecras_dir not in sys.path:
        sys.path.insert(0, hecras_dir)

    for dep in _DEPS:
        dll = os.path.join(hecras_dir, f"{dep}.dll")
        try:
            clr.AddReference(dll)
        except Exception as exc:
            if dep == "RasMapperLib":
                raise RuntimeError(f"Cannot load RasMapperLib.dll: {exc}") from exc
            logger.warning(f"Could not load {dep}.dll: {exc}")

    _dlls_loaded = True
    logger.debug("RasMapperLib DLLs loaded")


def _imports():
    """Return namespace dict with .NET types (deferred until DLLs loaded)."""
    from RasMapperLib import (  # type: ignore
        RASGeometry,
        MeshFV2D,
        PolylineFeatureLayer,
        Polyline,
        Polygon,
        Point2D,
        PointMs,
    )
    from RasMapperLib.Mesh import MeshStatus  # type: ignore
    from RasMapperLib.EditLayers import PointGenerator  # type: ignore
    from System.Collections.Generic import List  # type: ignore
    import System  # type: ignore

    return dict(
        RASGeometry=RASGeometry,
        MeshFV2D=MeshFV2D,
        PolylineFeatureLayer=PolylineFeatureLayer,
        Polyline=Polyline,
        Polygon=Polygon,
        Point2D=Point2D,
        PointMs=PointMs,
        MeshStatus=MeshStatus,
        PointGenerator=PointGenerator,
        List=List,
        System=System,
    )


def _polygon_centroid(perim) -> Tuple[float, float]:
    """Compute centroid of a .NET Polygon (mean of all vertices)."""
    n = perim.Count
    sx, sy = 0.0, 0.0
    for i in range(n):
        sx += float(perim.PointM(i).X)
        sy += float(perim.PointM(i).Y)
    return (sx / n, sy / n) if n > 0 else (0.0, 0.0)


def _shift_polygon(perim, dx: float, dy: float, ns: dict):
    """Create a new .NET Polygon shifted by (dx, dy)."""
    from RasMapperLib import PointMs as _PointMs, Polygon as _Polygon  # type: ignore
    from RasMapperLib import PointM as _PointM  # type: ignore
    n = perim.Count
    pt_list = _PointMs()
    for i in range(n):
        pt_list.Add(_PointM(float(perim.PointM(i).X) + dx, float(perim.PointM(i).Y) + dy))
    return _Polygon(pt_list)


def _shift_seeds(seeds_pm, dx: float, dy: float, ns: dict):
    """Create new PointMs collection shifted by (dx, dy)."""
    from RasMapperLib import PointMs as _PointMs  # type: ignore
    from RasMapperLib import PointM as _PointM  # type: ignore
    out = _PointMs()
    for i in range(seeds_pm.Count):
        p = seeds_pm[i]
        out.Add(_PointM(float(p.X) + dx, float(p.Y) + dy))
    return out


def _generate_seeds_safe(perim, cell_size: float, ns: dict):
    """PointGenerator.GeneratePoints with float32-safe coordinate shifting.

    RasMapperLib uses System.Single internally; large projected coordinates
    (EPSG:5070 x~500K, y~1.8M) overflow. Shift to local origin, generate,
    shift back.
    """
    PointGenerator = ns["PointGenerator"]
    cx, cy = _polygon_centroid(perim)
    if abs(cx) > 50000 or abs(cy) > 50000:
        local_perim = _shift_polygon(perim, -cx, -cy, ns)
        local_seeds = PointGenerator.GeneratePoints(local_perim, float(cell_size))
        return _shift_seeds(local_seeds, cx, cy, ns)
    return PointGenerator.GeneratePoints(perim, float(cell_size))


def _generate_seeds_via_net(geom_hdf_path: str, ns: dict, fid: int = 0) -> "PointMs":
    """Generate breakline-aware seeds using RasMapperLib.PointGenerator.

    Calls the private RegenerateMeshPoints instance method via reflection,
    which internally runs the full EnforceBreaklines 5-step pipeline.

    Replicates the GUI's SA2DLinesAsBreakLines behavior: SA2D structures
    (internal dams, weirs) are temporarily added as breaklines with their
    spacing parameters (Near Repeats, Protection Radius) so that
    EnforceBreaklines generates the correct corridor seeds.

    Args:
        geom_hdf_path: Path to compiled .g##.hdf file.
        ns: .NET type namespace from _imports().
        fid: 0-based flow area feature index for MeshPoints lookup.

    Returns PointMs collection of seed points.
    """
    from System.Reflection import BindingFlags  # type: ignore
    from System.Collections.Generic import List as NetList  # type: ignore
    import System  # type: ignore

    geom = ns["RASGeometry"](str(geom_hdf_path))
    d2fa = geom.D2FlowArea
    bl = geom.BreakLines

    # --- Replicate SA2DLinesAsBreakLines ---
    # The GUI temporarily adds SA2D structures as breaklines and copies
    # their spacing parameters (Near Repeats, Protection Radius).
    # The try/finally wraps both insertion AND usage so temp breaklines
    # are always cleaned up, even if spacing column copy fails.
    sa2d = geom.SA2DStructures
    struct_bl_fids: list[int] = []
    sa2d_count = sa2d.FeatureCount() if sa2d else 0

    try:
        if sa2d_count > 0:
            spacing_cols = [
                "Near Spacing", "Far Spacing",
                "Near Repeats", "Enforce 1 Cell Protection Radius",
            ]
            for sa2d_fid in sa2d.FilteredFIDS():
                sa2d_fid = int(sa2d_fid)
                bl.AddFeature(sa2d.Feature(sa2d_fid))
                new_fid = bl.FeatureCount() - 1
                struct_bl_fids.append(new_fid)
                sa2d_row = sa2d.FeatureRow(sa2d_fid)
                bl_row = bl.FeatureRow(new_fid)
                for col in spacing_cols:
                    bl_row[col] = sa2d_row[col]
            logger.debug(
                f"Added {len(struct_bl_fids)} SA2D structure(s) as temp breaklines"
            )

        bl_count = bl.FeatureCount()
        perim_count = d2fa.FeatureCount()

        bl_idx = NetList[System.Int32]()
        for i in range(bl_count):
            bl_idx.Add(i)
        perim_idx = NetList[System.Int32]()
        for i in range(perim_count):
            perim_idx.Add(i)
        region_idx = NetList[System.Int32]()

        pg = ns["PointGenerator"](geom)
        pg_type = pg.GetType()
        method = pg_type.GetMethod(
            "RegenerateMeshPoints",
            BindingFlags.Instance | BindingFlags.NonPublic,
        )
        if method is None:
            raise RuntimeError(
                "Cannot find private RegenerateMeshPoints on PointGenerator"
            )

        method.Invoke(
            pg,
            System.Array[System.Object](
                [bl_idx, region_idx, perim_idx, perim_idx, None, None, False]
            ),
        )

        mp = d2fa.Geometry.MeshPoints[fid]
        seeds_pm = ns["PointMs"]()
        for i in range(mp.PointMCount()):
            seeds_pm.Add(mp.PointM(i))

        logger.info(
            f"Seeds via .NET RegenerateMeshPoints: {seeds_pm.Count} "
            f"({bl_count} breaklines incl {len(struct_bl_fids)} struct, "
            f"{perim_count} perimeters)"
        )
        return seeds_pm
    finally:
        for rm_fid in sorted(struct_bl_fids, reverse=True):
            try:
                bl.DeleteFeature(rm_fid)
            except Exception:
                logger.warning(f"Failed to remove temp breakline FID {rm_fid}")


def _build_breaklines(d2fa, ns: dict):
    """Merge BreakLines + MeshRegions + Structures into multipart Polyline."""
    Polyline = ns["Polyline"]
    PolylineFeatureLayer = ns["PolylineFeatureLayer"]

    combined = PolylineFeatureLayer("bl")
    n = 0
    try:
        for bl in d2fa.Geometry.BreakLines.Polylines():
            if Polyline.IsValidPolyline(bl):
                combined.AddFeature(bl)
                n += 1
    except Exception:
        pass
    try:
        for rgn in d2fa.Geometry.MeshRegions.Polygons():
            if Polyline.IsValidPolyline(rgn):
                combined.AddFeature(rgn)
                n += 1
    except Exception:
        pass
    try:
        for struc in d2fa.Geometry.Structures.Polylines():
            if Polyline.IsValidPolyline(struc):
                combined.AddFeature(struc)
                n += 1
    except Exception:
        pass

    if n == 0:
        return None
    return combined.CopyToMultiPartPolyline()


def _compute_mesh(perim, seeds, breaklines, ratio: float, ns: dict):
    """Create and return a MeshFV2D."""
    return ns["MeshFV2D"](perim, seeds, breaklines, None, float(ratio))


def _safe_non_virtual_cell_count(mesh) -> Optional[int]:
    """Return NonVirtualCellCount when RasMapper has a valid cell collection."""
    try:
        return int(mesh.NonVirtualCellCount)
    except Exception as exc:
        logger.debug("Could not read NonVirtualCellCount: %s", exc)
        return None


def _safe_face_count(mesh) -> Optional[int]:
    """Return FaceCount when RasMapper has a valid face collection."""
    try:
        return int(mesh.FaceCount)
    except Exception as exc:
        logger.debug("Could not read FaceCount: %s", exc)
        return None


def _dedupe_seed_points(seeds_pm, ns: dict, tolerance: float = 1e-6):
    """Remove duplicate seed points while preserving the original order."""
    out = ns["PointMs"]()
    seen: set[tuple[int, int]] = set()
    removed = 0
    tolerance = max(float(tolerance), 1e-12)

    for i in range(seeds_pm.Count):
        point = seeds_pm[i]
        key = (
            round(float(point.X) / tolerance),
            round(float(point.Y) / tolerance),
        )
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        out.Add(point)

    return out, removed


def _bad_seed_indexes(mesh, seed_count: int) -> set[int]:
    """Return RasMapper BadIndexes that refer to generated seed points."""
    try:
        bad = mesh.BadIndexes
        count = bad.Count if hasattr(bad, "Count") else len(bad)
    except Exception as exc:
        logger.debug("Could not read mesh BadIndexes: %s", exc)
        return set()

    indexes: set[int] = set()
    for i in range(count):
        try:
            idx = int(bad[i])
        except Exception:
            continue
        if 0 <= idx < seed_count:
            indexes.add(idx)
    return indexes


def _remove_seed_indexes(seeds_pm, indexes: set[int], ns: dict):
    """Remove seed points by zero-based index while preserving original order."""
    out = ns["PointMs"]()
    removed = 0
    for i in range(seeds_pm.Count):
        if i in indexes:
            removed += 1
            continue
        out.Add(seeds_pm[i])
    return out, removed





def _autofix_max_faces(mesh, seeds_as_list: list, ns: dict) -> Tuple[list, int, list]:
    """Add midpoints of longest 2 faces (with no internal points) per cell exceeding MAX_FACES.

    Matches C# TryAutoFix (ilspy_meshfv2d.txt:4803-4804): filters by
    InternalPoints.IsNullOrEmpty() only — does NOT exclude perimeter faces
    and does NOT perform containment checks.

    Returns (combined_seeds, n_added, new_midpoints_only).
    """
    new_pts = list(seeds_as_list)
    midpoints_only = []
    seen = set()
    n_added = 0

    for cidx in range(mesh.NonVirtualCellCount):
        if mesh.CellFacesCount(cidx) <= MAX_FACES_PER_CELL:
            continue

        faces = list(mesh.CellFaces(cidx))

        def face_key(fidx):
            try:
                return mesh.FaceSimpleLength(fidx)
            except Exception:
                return 0.0

        def has_no_internal_pts(fidx):
            try:
                return mesh.PointsOnFace(fidx).Count <= 2
            except Exception:
                return True

        eligible = [f for f in faces if has_no_internal_pts(f)]
        eligible.sort(key=face_key, reverse=True)

        added_this_cell = 0
        for fidx in eligible:
            if added_this_cell >= 2:
                break
            if fidx in seen:
                continue
            try:
                seg = mesh.FaceSegment(fidx)
                mid = seg.MidPoint()
                new_pts.append(mid)
                midpoints_only.append(mid)
                seen.add(fidx)
                n_added += 1
                added_this_cell += 1
            except Exception:
                pass

    return new_pts, n_added, midpoints_only


def _autofix_perimeter(perim, ns: dict) -> list:
    """Tier 3: find consecutive near-duplicate perimeter point indices."""
    try:
        return list(perim.ConsecutiveNearbyPointsIndices(PERIMETER_NEAR_DUPLICATE_TOL))
    except Exception:
        return []


def _remove_perimeter_points(perim, bad_indices: list, ns: dict):
    """Remove specified point indices from Polygon, return new Polygon."""
    if not bad_indices:
        return perim
    bad_set = set(bad_indices)
    try:
        n = perim.Count
        good_indices = [i for i in range(n) if i not in bad_set]
        if len(good_indices) < 3:
            return perim
        from RasMapperLib import PointMs as _PointMs, Polygon as _Polygon  # type: ignore
        pt_list = _PointMs()
        for i in good_indices:
            pt_list.Add(perim.PointM(i))
        return _Polygon(pt_list)
    except Exception as exc:
        logger.warning(f"_remove_perimeter_points failed: {exc}")
        return perim


def _remove_short_perimeter_segments(perim, min_length: float, ns: dict):
    """Tier 0: greedy forward pass removing vertices closer than min_length.

    Keeps a vertex only if it is at least min_length from the last kept vertex.
    Runs multiple passes until stable (handles cascading short segments).
    """
    try:
        n = perim.Count
        if n < 4 or min_length <= 0:
            return perim

        coords = [(float(perim.PointM(i).X), float(perim.PointM(i).Y))
                  for i in range(n)]

        min_sq = min_length * min_length

        def _one_pass(pts):
            kept = [pts[0]]
            for pt in pts[1:]:
                dx = pt[0] - kept[-1][0]
                dy = pt[1] - kept[-1][1]
                if dx * dx + dy * dy >= min_sq:
                    kept.append(pt)
            if len(kept) > 1:
                dx = kept[0][0] - kept[-1][0]
                dy = kept[0][1] - kept[-1][1]
                if dx * dx + dy * dy < min_sq:
                    kept.pop()
            return kept

        new_coords = coords
        for _ in range(20):
            filtered = _one_pass(new_coords)
            if len(filtered) == len(new_coords):
                break
            if len(filtered) < 3:
                return perim
            new_coords = filtered

        if len(new_coords) == n:
            return perim

        from RasMapperLib import PointMs as _PointMs, Polygon as _Polygon  # type: ignore
        from RasMapperLib import PointM as _PointM  # type: ignore
        pt_list = _PointMs()
        for x, y in new_coords:
            pt_list.Add(_PointM(float(x), float(y)))
        return _Polygon(pt_list)
    except Exception as exc:
        logger.warning(f"_remove_short_perimeter_segments failed: {exc}")
        return perim


def _seeds_from_pointms_list(pts_list: list, ns: dict):
    """Convert Python list of PointM objects into PointMs collection."""
    pm = ns["PointMs"]()
    for p in pts_list:
        pm.Add(p)
    return pm


def _save_mesh(geom, d2fa, fid: int, mesh, ns: dict) -> None:
    """Persist MeshFV2D to geometry HDF."""
    d2fa.SetMeshHasBeenRecomputed(fid, True)
    d2fa.SetFeature(fid, mesh)
    d2fa.SetMeshUpToDate(fid, True)
    geom.Save()


def _douglas_peucker_polygon(perim, tolerance: float, ns: dict):
    """Tier 4: apply Douglas-Peucker simplification to perimeter."""
    try:
        from shapely.geometry import Polygon as ShapelyPolygon

        n = perim.Count
        coords = [(float(perim.PointM(i).X), float(perim.PointM(i).Y))
                  for i in range(n)]
        if not coords or coords[0] != coords[-1]:
            coords.append(coords[0])

        sp = ShapelyPolygon(coords)
        simplified = sp.simplify(tolerance, preserve_topology=True)
        new_coords = list(simplified.exterior.coords)

        from RasMapperLib import PointMs as _PointMs, Polygon as _Polygon  # type: ignore
        from RasMapperLib import PointM as _PointM  # type: ignore

        pt_list = _PointMs()
        for x, y in new_coords:
            pt_list.Add(_PointM(float(x), float(y)))
        return _Polygon(pt_list)
    except Exception as exc:
        logger.warning(f"Douglas-Peucker simplification failed: {exc}")
        return perim


def _find_error_locations(mesh, cell_size: float, min_ratio: float) -> list:
    """Return (x, y) locations of FacePerimeterConnectionError problem zones.

    Primary: mesh.BadIndexes cell centers.
    Fallback: midpoints of shortest perimeter faces (bottom 5%).
    """
    pts: list = []

    try:
        bad = mesh.BadIndexes
        n_bad = bad.Count if hasattr(bad, 'Count') else len(bad)
        for i in range(n_bad):
            idx = int(bad[i])
            if idx < 0:
                continue
            cell = mesh.Cell(idx)
            pts.append((float(cell.Point.X), float(cell.Point.Y)))
    except Exception:
        pass

    if pts:
        return pts

    try:
        threshold = cell_size * min_ratio
        perim_faces = []
        for f in range(int(mesh.FaceCount)):
            if mesh.FaceIsPerimeter(f):
                length = float(mesh.FaceSegment(f).Length)
                perim_faces.append((length, f))
        if not perim_faces:
            return []
        short_faces = [(ln, f) for ln, f in perim_faces if ln < threshold]
        if not short_faces:
            sorted_faces = sorted(perim_faces)
            n_fallback = max(1, len(sorted_faces) // 20)
            short_faces = sorted_faces[:n_fallback]
        for _length, f in short_faces:
            mp = mesh.FaceSegment(f).MidPoint()
            pts.append((float(mp.X), float(mp.Y)))
    except Exception:
        pass

    return pts


def _iter_bc_flow_area_groups(hf):
    """Yield 2D flow-area groups that contain the BC conflict datasets."""
    root_key = "Geometry/2D Flow Areas"
    if root_key not in hf:
        return

    required = {
        "BC Lines",
        "FacePoints Coordinate",
        "Faces FacePoint Indexes",
        "Faces Perimeter Info",
    }
    for key in hf[root_key].keys():
        candidate = hf[f"{root_key}/{key}"]
        if not hasattr(candidate, "keys"):
            continue
        if required.issubset(set(candidate.keys())):
            yield candidate


def _read_bc_features(area_group, shapely_line_cls) -> list[dict]:
    """Read BC geometries for one 2D flow area."""
    bcs = []
    for bc_name in area_group["BC Lines"].keys():
        bc_feature = area_group["BC Lines"][bc_name]
        if not hasattr(bc_feature, "keys") or "Coordinates" not in bc_feature:
            continue
        coords = bc_feature["Coordinates"][:]
        bc_type_raw = bc_feature.attrs.get("Type", "")
        if hasattr(bc_type_raw, "decode"):
            bc_type = bc_type_raw.decode("utf-8", errors="replace").strip("\x00").strip()
        else:
            bc_type = str(bc_type_raw)
        geom = shapely_line_cls(coords[:, :2]) if len(coords) >= 2 else None
        bcs.append(
            {
                "name": bc_name,
                "type": bc_type,
                "geom": geom,
            }
        )
    return bcs


def _read_bc_face_segments(area_group, shapely_line_cls) -> List[tuple]:
    """Read perimeter faces for one 2D flow area."""
    face_segments: List[tuple] = []
    fp_coords = area_group["FacePoints Coordinate"][:]
    face_fp_idx = area_group["Faces FacePoint Indexes"][:]
    perim_info = area_group["Faces Perimeter Info"][:]

    for fid in range(len(face_fp_idx)):
        row = perim_info[fid]
        if hasattr(row, "__len__"):
            if int(row[0]) == 0 and int(row[1]) == 0:
                continue
        elif not row:
            continue
        fp_a, fp_b = int(face_fp_idx[fid][0]), int(face_fp_idx[fid][1])
        a = fp_coords[fp_a]
        b = fp_coords[fp_b]
        face_segments.append((fid, shapely_line_cls([a, b])))

    return face_segments


def _localized_douglas_peucker(perim, error_midpoints, cell_size, tol, ns, buf_multiplier=3.0):
    """Tier 4: simplify perimeter only within buffer zones around error locations.

    Vertices outside error zones are preserved exactly. Contiguous in-zone
    runs are simplified via LineString.simplify() with the flanking
    out-of-zone vertices as anchors so endpoints stay pinned.
    """
    try:
        from shapely.geometry import LineString

        from RasMapperLib import PointM as _PointM    # type: ignore
        from RasMapperLib import PointMs as _PointMs   # type: ignore
        from RasMapperLib import Polygon as _Polygon   # type: ignore

        buf_sq = (cell_size * buf_multiplier) ** 2

        n = perim.Count
        coords = [(float(perim.PointM(i).X), float(perim.PointM(i).Y))
                  for i in range(n)]
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        n = len(coords)

        if n < 3:
            return perim

        in_zone = [False] * n
        for i, (vx, vy) in enumerate(coords):
            for (ex, ey) in error_midpoints:
                dx = vx - ex
                dy = vy - ey
                if dx * dx + dy * dy <= buf_sq:
                    in_zone[i] = True
                    break

        if not any(in_zone):
            return perim

        if all(in_zone):
            return _douglas_peucker_polygon(perim, tol, ns)

        start = next(i for i in range(n) if not in_zone[i])
        coords = coords[start:] + coords[:start]
        in_zone = in_zone[start:] + in_zone[:start]

        result_coords: list = []
        i = 0
        while i < n:
            if not in_zone[i]:
                result_coords.append(coords[i])
                i += 1
            else:
                run_start = i
                while i < n and in_zone[i]:
                    i += 1
                run_end = i

                anchor_before = coords[run_start - 1]
                anchor_after = coords[run_end % n]

                run_pts = [anchor_before] + coords[run_start:run_end] + [anchor_after]

                if len(run_pts) > 3:
                    simplified_pts = list(
                        LineString(run_pts).simplify(tol, preserve_topology=False).coords
                    )
                    inner = simplified_pts[1:-1]
                else:
                    inner = coords[run_start:run_end]

                result_coords.extend(inner)

        if len(result_coords) < 3:
            return perim

        result_coords.append(result_coords[0])

        pt_list = _PointMs()
        for x, y in result_coords:
            pt_list.Add(_PointM(float(x), float(y)))

        return _Polygon(pt_list)

    except ImportError:
        logger.warning("Shapely not available for localized Douglas-Peucker")
        return perim
    except Exception as exc:
        logger.warning(f"Localized Douglas-Peucker failed: {exc}")
        return perim


def _normalize_positive_value(
    value: Optional[float],
    field_name: str,
    *,
    allow_none: bool = False,
) -> Optional[float]:
    """Normalize numeric inputs that must be strictly positive."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must be provided")

    normalized = float(value)
    if normalized <= 0.0:
        raise ValueError(f"{field_name} must be greater than 0.0")
    return normalized


def _set_breakline_spacing_impl(
    geom_text_path: Path,
    near: Optional[float],
    far: Optional[float],
    near_repeats: Optional[int] = None,
    protection_radius: Optional[int] = None,
    breakline_name: Optional[str] = None,
    breakline_fid: Optional[int] = None,
    all_breaklines: bool = False,
) -> Path:
    """Edit BreakLine spacing properties in .g## text file.

    Target selection (exactly one):
    - *breakline_name*: match by name
    - *breakline_fid*: match by 0-based index in file order
    - *all_breaklines*: every breakline
    """
    near = _normalize_positive_value(near, "near", allow_none=True)
    far = _normalize_positive_value(far, "far", allow_none=True)
    lines = geom_text_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )

    if breakline_name is not None:
        matches = [
            i for i, l in enumerate(lines)
            if l.startswith("BreakLine Name=")
            and l.split("=", 1)[1].strip() == breakline_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple breaklines named '{breakline_name}' "
                f"(count={len(matches)}). Use breakline_fid for "
                f"disambiguation — call get_breakline_names() to "
                f"inspect FID-to-name mapping."
            )

    in_target_block = all_breaklines
    found_target = False
    bl_index = -1
    modified = []
    for line in lines:
        if line.startswith("BreakLine Name="):
            bl_index += 1
            name = line.split("=", 1)[1].strip()
            if all_breaklines:
                in_target_block = True
            elif breakline_fid is not None:
                in_target_block = bl_index == breakline_fid
                if in_target_block:
                    found_target = True
            elif breakline_name is not None:
                in_target_block = name == breakline_name
                if in_target_block:
                    found_target = True
            else:
                in_target_block = False

        if in_target_block:
            if near is not None and line.startswith("BreakLine CellSize Min="):
                line = f"BreakLine CellSize Min={near:.6f}\n"
            elif far is not None and line.startswith("BreakLine CellSize Max="):
                line = f"BreakLine CellSize Max={far:.6f}\n"
            elif near_repeats is not None and line.startswith("BreakLine Near Repeats="):
                line = f"BreakLine Near Repeats={int(near_repeats)}\n"
            elif protection_radius is not None and line.startswith("BreakLine Protection Radius="):
                line = f"BreakLine Protection Radius={int(protection_radius)}\n"
        modified.append(line)

    if not all_breaklines and not found_target:
        target_desc = (
            f"FID {breakline_fid}" if breakline_fid is not None
            else f"'{breakline_name}'"
        )
        raise ValueError(
            f"Breakline {target_desc} not found in {geom_text_path.name}"
        )

    backup = geom_text_path.with_suffix(geom_text_path.suffix + ".bak")
    shutil.copy2(geom_text_path, backup)
    tmp = geom_text_path.with_suffix(geom_text_path.suffix + ".tmp")
    tmp.write_text("".join(modified), encoding="utf-8")
    tmp.replace(geom_text_path)
    target = (
        f"FID {breakline_fid}" if breakline_fid is not None
        else breakline_name or "ALL"
    )
    logger.info(
        f"Breakline spacing [{target}]: near={near}, far={far} "
        f"→ {geom_text_path.name}"
    )
    return backup


def _read_breakline_names_from_text(
    geom_text_path: Path,
) -> list[tuple[int, str]]:
    """Return (fid, name) for every breakline in .g## text, in file order."""
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    result = []
    bl_index = -1
    for line in text.splitlines():
        if line.startswith("BreakLine Name="):
            bl_index += 1
            name = line.split("=", 1)[1].strip()
            result.append((bl_index, name))
    return result


def _set_breakline_name_impl(
    geom_text_path: Path,
    new_name: str,
    breakline_fid: Optional[int] = None,
    old_name: Optional[str] = None,
) -> Path:
    """Rename a breakline in .g## text by FID or current name."""
    lines = geom_text_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    bl_index = -1
    found = False
    modified = []
    for line in lines:
        if line.startswith("BreakLine Name="):
            bl_index += 1
            name = line.split("=", 1)[1].strip()
            match = False
            if breakline_fid is not None:
                match = bl_index == breakline_fid
            elif old_name is not None:
                match = name == old_name
            if match:
                if found:
                    raise ValueError(
                        f"Multiple breaklines match {repr(old_name)}; "
                        f"use breakline_fid for disambiguation."
                    )
                found = True
                line = f"BreakLine Name={new_name}\n"
        modified.append(line)

    if not found:
        target = (
            f"FID {breakline_fid}" if breakline_fid is not None
            else repr(old_name)
        )
        raise ValueError(
            f"Breakline {target} not found in {geom_text_path.name}"
        )

    backup = geom_text_path.with_suffix(geom_text_path.suffix + ".bak")
    shutil.copy2(geom_text_path, backup)
    tmp = geom_text_path.with_suffix(geom_text_path.suffix + ".tmp")
    tmp.write_text("".join(modified), encoding="utf-8")
    tmp.replace(geom_text_path)
    logger.info(f"Renamed breakline → '{new_name}' in {geom_text_path.name}")
    return backup


def _read_breakline_spacing_from_text(
    geom_text_path: Path,
) -> list[tuple[int, str, float, float, int, int]]:
    """Read per-breakline spacing properties from .g## text file.

    Returns list of (fid, name, near, far, near_repeats, protection_radius)
    tuples in file order.  *fid* is the 0-based index.
    """
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    result = []
    in_block = False
    current_name = ""
    near_val = 0.0
    far_val = 0.0
    nr_val = 0
    pr_val = 0
    bl_index = -1
    for line in lines:
        if line.startswith("BreakLine Name="):
            if in_block:
                result.append((bl_index, current_name, near_val, far_val, nr_val, pr_val))
            bl_index += 1
            in_block = True
            current_name = line.split("=", 1)[1].strip()
            near_val = 0.0
            far_val = 0.0
            nr_val = 0
            pr_val = 0
        elif line.startswith("BreakLine CellSize Min="):
            try:
                near_val = float(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.startswith("BreakLine CellSize Max="):
            try:
                far_val = float(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.startswith("BreakLine Near Repeats="):
            try:
                nr_val = int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.startswith("BreakLine Protection Radius="):
            try:
                pr_val = int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
    if in_block:
        result.append((bl_index, current_name, near_val, far_val, nr_val, pr_val))
    return result


def _sync_breakline_spacing_text_to_hdf(
    text_path: Path, hdf_path: Path
) -> None:
    """Sync breakline spacing from .g01 text (source of truth) into HDF.

    RegenerateMeshPoints reads spacing from the HDF, not from text.
    The existing HDF workspace may not yet reflect current run parameters.
    """
    try:
        import h5py
        bl_spacings = _read_breakline_spacing_from_text(text_path)
        if not bl_spacings:
            return
        bl_key = "Geometry/2D Flow Area Break Lines/Attributes"
        with h5py.File(str(hdf_path), "r+") as hf:
            if bl_key not in hf:
                return
            data = hf[bl_key][:]
            if "Cell Spacing Near" not in data.dtype.names:
                return
            changed = False
            has_nr = "Near Repeats" in data.dtype.names
            has_pr = "Protection Radius" in data.dtype.names
            for fid, _name, t_near, t_far, t_nr, t_pr in bl_spacings:
                if fid >= len(data):
                    break
                # 0.0 means "not set in text" for spacing; skip to preserve HDF value
                if t_near > 0 and abs(float(data["Cell Spacing Near"][fid]) - t_near) > 0.001:
                    data["Cell Spacing Near"][fid] = t_near
                    changed = True
                if t_far > 0 and abs(float(data["Cell Spacing Far"][fid]) - t_far) > 0.001:
                    data["Cell Spacing Far"][fid] = t_far
                    changed = True
                # Negative means "not set in text"; HDF uses uint8 so skip to avoid overflow
                if has_nr and t_nr >= 0 and int(data["Near Repeats"][fid]) != t_nr:
                    data["Near Repeats"][fid] = t_nr
                    changed = True
                if has_pr and t_pr >= 0 and int(data["Protection Radius"][fid]) != t_pr:
                    data["Protection Radius"][fid] = t_pr
                    changed = True
            if changed:
                hf[bl_key][:] = data
                logger.info(
                    f"Synced {len(bl_spacings)} breakline spacings "
                    f"from text → HDF"
                )
    except Exception as exc:
        logger.warning(
            f"Could not sync breakline spacing to HDF: {exc}"
        )


def _parse_optional_float(value: str | None) -> float | None:
    """Parse a geometry numeric field, returning None for blanks."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _decode_hdf_text(value: Any) -> str:
    """Decode an HDF scalar/string value to text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if hasattr(value, "decode"):
        try:
            return value.decode("utf-8", errors="replace").strip()
        except Exception:
            pass
    return str(value).strip()


def _read_mesh_metadata_from_text(
    geom_text_path: Path,
) -> dict[str, dict[str, float | int | None]]:
    """Read per-2D-area mesh seed count and spacing from geometry text."""
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    metadata: dict[str, dict[str, float | int | None]] = {}
    current_area: str | None = None

    for line in text.splitlines():
        if line.startswith("Storage Area="):
            current_area = line.split("=", 1)[1].split(",", 1)[0].strip()
            metadata.setdefault(
                current_area,
                {
                    "seed_count": None,
                    "spacing_dx": None,
                    "spacing_dy": None,
                },
            )
            continue

        if current_area is None:
            continue

        if line.startswith("Storage Area Point Generation Data="):
            parts = line.split("=", 1)[1].split(",")
            spacing_dx = _parse_optional_float(parts[2] if len(parts) > 2 else None)
            spacing_dy = _parse_optional_float(parts[3] if len(parts) > 3 else None)
            metadata[current_area]["spacing_dx"] = spacing_dx
            metadata[current_area]["spacing_dy"] = spacing_dy
            continue

        if line.startswith("Storage Area 2D Points="):
            try:
                metadata[current_area]["seed_count"] = int(
                    line.split("=", 1)[1].strip()
                )
            except (IndexError, ValueError):
                metadata[current_area]["seed_count"] = None

    return metadata


def _read_mesh_metadata_from_hdf(
    hdf_path: Path,
) -> dict[str, dict[str, float | int | str | None]]:
    """Read per-2D-area mesh cell count and spacing from compiled geometry HDF."""
    import h5py

    metadata: dict[str, dict[str, float | int | str | None]] = {}
    attrs_key = "Geometry/2D Flow Areas/Attributes"
    flow_areas_key = "Geometry/2D Flow Areas"

    with h5py.File(str(hdf_path), "r") as hf:
        if attrs_key in hf:
            data = hf[attrs_key][:]
            dtype_names = data.dtype.names or ()
            for i in range(len(data)):
                if "Name" in dtype_names:
                    area_name = _decode_hdf_text(data["Name"][i])
                else:
                    area_name = f"<index {i}>"
                if not area_name:
                    continue

                row = metadata.setdefault(
                    area_name,
                    {
                        "cell_count": None,
                        "cell_count_source": None,
                        "spacing_dx": None,
                        "spacing_dy": None,
                    },
                )
                if "Cell Count" in dtype_names:
                    try:
                        row["cell_count"] = int(data["Cell Count"][i])
                        row["cell_count_source"] = "Attributes/Cell Count"
                    except (TypeError, ValueError):
                        pass
                if "Spacing dx" in dtype_names:
                    try:
                        row["spacing_dx"] = float(data["Spacing dx"][i])
                    except (TypeError, ValueError):
                        pass
                if "Spacing dy" in dtype_names:
                    try:
                        row["spacing_dy"] = float(data["Spacing dy"][i])
                    except (TypeError, ValueError):
                        pass

        if flow_areas_key in hf:
            for area_name in hf[flow_areas_key].keys():
                if area_name == "Attributes":
                    continue
                row = metadata.setdefault(
                    area_name,
                    {
                        "cell_count": None,
                        "cell_count_source": None,
                        "spacing_dx": None,
                        "spacing_dy": None,
                    },
                )
                if row.get("cell_count") is None:
                    cells_key = f"{flow_areas_key}/{area_name}/Cells Center Coordinate"
                    if cells_key in hf:
                        row["cell_count"] = int(hf[cells_key].shape[0])
                        row["cell_count_source"] = "Cells Center Coordinate"

    return metadata


def _read_cell_size_from_text(
    geom_text_path: Path,
    mesh_name: str | None = None,
    mesh_index: int = 0,
) -> float | None:
    """Read base mesh cell size from geometry text point-generation data."""
    metadata = _read_mesh_metadata_from_text(geom_text_path)
    if mesh_name is not None:
        area = metadata.get(mesh_name)
        if area is None:
            return None
        dx = area.get("spacing_dx")
        return float(dx) if isinstance(dx, (int, float)) and dx > 0 else None

    areas = list(metadata.values())
    if 0 <= mesh_index < len(areas):
        dx = areas[mesh_index].get("spacing_dx")
        if isinstance(dx, (int, float)) and dx > 0:
            return float(dx)

    for area in areas:
        dx = area.get("spacing_dx")
        if isinstance(dx, (int, float)) and dx > 0:
            return float(dx)
    return None


def _read_cell_size_from_hdf(
    hdf_path: Path, mesh_name: str | None = None
) -> float:
    """Read cell size from HDF Attributes ``Spacing dx``.

    Returns the stored spacing for the matching mesh, or 100.0 if the
    attribute is missing, zero, or unreadable.
    """
    fallback = 100.0
    try:
        import h5py
        attrs_key = "Geometry/2D Flow Areas/Attributes"
        with h5py.File(str(hdf_path), "r") as hf:
            if attrs_key not in hf:
                return fallback
            data = hf[attrs_key][:]
            if "Spacing dx" not in data.dtype.names:
                return fallback
            for i in range(len(data)):
                if mesh_name is not None and "Name" in data.dtype.names:
                    row_name = data["Name"][i].decode().strip()
                    if row_name != mesh_name:
                        continue
                dx = float(data["Spacing dx"][i])
                if dx > 0:
                    return dx
    except Exception:
        pass
    return fallback


def _sync_cell_size_to_hdf(
    hdf_path: Path, cell_size: float, mesh_name: str | None = None
) -> None:
    """Sync cell size into HDF Attributes so RegenerateMeshPoints uses it.

    When mesh_name is given, only the matching row is updated (multi-area safe).
    """
    try:
        import h5py
        attrs_key = "Geometry/2D Flow Areas/Attributes"
        with h5py.File(str(hdf_path), "r+") as hf:
            if attrs_key not in hf:
                return
            data = hf[attrs_key][:]
            if "Spacing dx" not in data.dtype.names:
                return
            changed = False
            for i in range(len(data)):
                if mesh_name is not None and "Name" in data.dtype.names:
                    row_name = data["Name"][i].decode().strip()
                    if row_name != mesh_name:
                        continue
                if abs(float(data["Spacing dx"][i]) - cell_size) > 0.001:
                    data["Spacing dx"][i] = cell_size
                    changed = True
                if abs(float(data["Spacing dy"][i]) - cell_size) > 0.001:
                    data["Spacing dy"][i] = cell_size
                    changed = True
            if changed:
                hf[attrs_key][:] = data
                logger.info(f"Synced cell size {cell_size} → HDF Spacing dx/dy")
    except Exception as exc:
        logger.warning(f"Could not sync cell size to HDF: {exc}")


def _patch_text_perimeter(
    geom_text_path: Path, perim_polygon, mesh_name: str | None = None
) -> None:
    """Write a .NET Polygon's vertices to the Storage Area Surface Line block.

    When mesh_name is given, only the block under the matching ``Storage Area=``
    header is replaced (multi-area safe).
    """
    n = perim_polygon.Count
    if n < 3:
        raise ValueError(f"Polygon must have >= 3 vertices, got {n}")

    def _fmt(v: float) -> str:
        int_digits = max(1, len(str(int(abs(v)))))
        n_dec = max(0, 16 - int_digits - 1)
        s = f"{v:.{n_dec}f}"
        if len(s) > 16 and n_dec > 0:
            s = f"{v:.{n_dec - 1}f}"
        return s[:16].ljust(16)

    coord_lines: list[str] = []
    for i in range(n):
        pt = perim_polygon.PointM(i)
        coord_lines.append(_fmt(float(pt.X)) + _fmt(float(pt.Y)) + "\n")

    lines = geom_text_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    modified: list[str] = []
    current_area: str | None = None
    idx = 0
    replaced = False
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("Storage Area="):
            current_area = line.split("=", 1)[1].split(",")[0].strip()
            modified.append(line)
            idx += 1
            continue
        if line.startswith("Storage Area Surface Line="):
            target = mesh_name is None or current_area == mesh_name
            if target:
                modified.append(f"Storage Area Surface Line= {n} \n")
                replaced = True
            else:
                modified.append(line)
            old_count = None
            try:
                old_count = int(line.split("=", 1)[1].strip())
            except (IndexError, ValueError):
                pass
            idx += 1
            if old_count is not None:
                skip = old_count
                while skip > 0 and idx < len(lines):
                    idx += 1
                    skip -= 1
            if target:
                modified.extend(coord_lines)
        else:
            modified.append(line)
            idx += 1

    if not replaced:
        logger.warning(f"Storage Area Surface Line block not found in {geom_text_path.name}")
        return

    geom_text_path.write_text("".join(modified), encoding="utf-8")
    logger.info(f"Patched perimeter → {n} vertices in {geom_text_path.name}")


def _reseed_after_perimeter_fix(
    text_path: Path,
    hdf_path: Path,
    current_perim,
    cell_size: float,
    fid: int,
    mesh_name: str | None,
    ns: dict,
    hecras_dir=None,
) -> "PointMs":
    """Reject perimeter fixes that require text-to-HDF regeneration."""
    raise RuntimeError(
        "Perimeter repair would require regenerating the compiled geometry HDF "
        f"from {text_path.name}. ras-commander cannot generate .g##.hdf from "
        ".g## text with RasMapperLib; create or refresh the geometry HDF through "
        "full HEC-RAS/Ras.exe behavior, then retry."
    )


def _set_point_generation_data(
    geom_text_path: Path, cell_size: float, mesh_name: str | None = None
) -> None:
    """Update Storage Area Point Generation Data in .g## text file.

    When mesh_name is given, only the block under the matching ``Storage Area=``
    header is modified (multi-area safe).
    """
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    prefix = "Storage Area Point Generation Data="
    new_line = f"{prefix},,{cell_size:.6f},{cell_size:.6f}\n"
    lines = text.splitlines(keepends=True)
    modified = []
    current_area: str | None = None
    for line in lines:
        if line.startswith("Storage Area="):
            current_area = line.split("=", 1)[1].split(",")[0].strip()
        if line.startswith(prefix):
            if mesh_name is None or current_area == mesh_name:
                modified.append(new_line)
            else:
                modified.append(line)
        else:
            modified.append(line)
    geom_text_path.write_text("".join(modified), encoding="utf-8")


def _looks_like_storage_area_seed_line(line: str) -> bool:
    """Return True when a line matches the packed seed-coordinate layout."""
    stripped = line.strip()
    if not stripped:
        return False

    parts = stripped.split()
    if len(parts) not in {2, 4}:
        return False

    try:
        for part in parts:
            float(part)
    except ValueError:
        return False

    return True


def _patch_text_seeds(
    geom_text_path: Path, cell_centers, mesh_name: str | None = None
) -> None:
    """Replace 'Storage Area 2D Points= N' block with generated cell centers.

    When mesh_name is given, only the block under the matching ``Storage Area=``
    header is replaced (multi-area safe).
    """
    import numpy as _np

    lines = geom_text_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    n = len(cell_centers)

    def _fmt(v: float) -> str:
        int_digits = max(1, len(str(int(abs(v)))))
        n_dec = max(0, 16 - int_digits - 1)
        s = f"{v:.{n_dec}f}"
        if len(s) > 16 and n_dec > 0:
            s = f"{v:.{n_dec - 1}f}"
        return s[:16].ljust(16)

    coord_lines: list[str] = []
    for i in range(0, n, 2):
        if i + 1 < n:
            coord_lines.append(
                _fmt(cell_centers[i, 0]) + _fmt(cell_centers[i, 1])
                + _fmt(cell_centers[i + 1, 0]) + _fmt(cell_centers[i + 1, 1]) + "\n"
            )
        else:
            coord_lines.append(_fmt(cell_centers[i, 0]) + _fmt(cell_centers[i, 1]) + "\n")

    modified: list[str] = []
    found_block = False
    current_area: str | None = None
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("Storage Area="):
            current_area = line.split("=", 1)[1].split(",")[0].strip()
            modified.append(line)
            idx += 1
            continue
        if line.startswith("Storage Area 2D Points="):
            target = mesh_name is None or current_area == mesh_name
            if target:
                found_block = True
                modified.append(f"Storage Area 2D Points= {n} \n")
            else:
                modified.append(line)
            old_point_count = None
            try:
                old_point_count = int(line.split("=", 1)[1].strip())
            except (IndexError, ValueError):
                old_point_count = None
            idx += 1

            lines_to_skip = (
                (old_point_count + 1) // 2
                if old_point_count is not None and old_point_count >= 0
                else None
            )
            skipped = 0
            while idx < len(lines):
                if lines_to_skip is not None:
                    if skipped >= lines_to_skip:
                        break
                    idx += 1
                    if not target:
                        modified.append(lines[idx - 1])
                    skipped += 1
                    continue
                if _looks_like_storage_area_seed_line(lines[idx]):
                    idx += 1
                    if not target:
                        modified.append(lines[idx - 1])
                    skipped += 1
                    continue
                break
            if target:
                modified.extend(coord_lines)
        else:
            modified.append(line)
            idx += 1

    if not found_block:
        raise ValueError(
            f"Storage Area 2D Points block not found in geometry text: {geom_text_path}"
        )

    geom_text_path.write_text("".join(modified), encoding="utf-8")
    logger.info(f"Text seeds patched → {n} points in {geom_text_path.name}")


# ── Public API ────────────────────────────────────────────────────────────────


def _resolve_geom_text_path(
    geom_number: Union[str, Number, Path],
    ras_object=None,
) -> Path:
    """Resolve a geometry number or path to a .g## text file Path."""
    if isinstance(geom_number, Path):
        candidate = geom_number
    elif isinstance(geom_number, str):
        candidate = Path(geom_number)
    else:
        candidate = None

    if candidate is not None and candidate.is_file():
        return candidate

    try:
        from ..RasPlan import RasPlan
        resolved = RasPlan.get_geom_path(geom_number, ras_object)
        if resolved is not None and Path(resolved).is_file():
            return Path(resolved)
    except Exception as exc:
        logger.debug(f"Could not resolve geom_number via RasPlan: {exc}")

    raise FileNotFoundError(
        f"Geometry file not found for: {geom_number}"
    )


def _geometry_hdf_unavailable_message(
    geom_text_path: Path,
    hdf_path: Path,
    reason: str,
) -> str:
    return (
        f"Compiled geometry HDF is {reason}: {hdf_path}. "
        "ras-commander cannot generate .g##.hdf from .g## text with "
        "RasMapperLib; CompleteGeometryCommand completes existing HDF files "
        "and is not a text-geometry compiler. Refresh the geometry through "
        "full HEC-RAS/Ras.exe behavior, then retry."
    )


def _normalize_component_number(value: Any) -> str | None:
    """Normalize a RAS component number, accepting values like g09 or 9.0."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "none"}:
        return None
    if raw[0].lower() in {"g", "p", "f", "u", "c"}:
        raw = raw[1:]
    try:
        from ..RasUtils import RasUtils
        return RasUtils.normalize_ras_number(raw)
    except Exception:
        digits = raw.split(".", 1)[0]
        return digits.zfill(2) if digits.isdigit() else None


def _geometry_number_from_path(
    geom_text_path: Path,
    ras_object=None,
) -> str | None:
    """Resolve a geometry number from a geometry text path and project metadata."""
    suffix = geom_text_path.suffix
    if len(suffix) > 2 and suffix[1].lower() == "g":
        normalized = _normalize_component_number(suffix[2:])
        if normalized is not None:
            return normalized

    ras_obj = ras_object
    if ras_obj is not None and getattr(ras_obj, "geom_df", None) is not None:
        try:
            for _, row in ras_obj.geom_df.iterrows():
                row_path = row.get("full_path")
                if row_path is not None and _paths_equivalent(row_path, geom_text_path):
                    return _normalize_component_number(row.get("geom_number"))
        except Exception:
            pass
    return None


def _find_plan_for_geometry(
    geom_text_path: Path,
    ras_object=None,
) -> str:
    """Find a plan number that references a geometry text file."""
    if ras_object is None:
        from ..RasPrj import ras as ras_object

    try:
        ras_object.check_initialized()
    except Exception as exc:
        raise RuntimeError(
            "recompile_via_rasexe=True requires an initialized RasPrj object "
            "so ras-commander can find a plan that references the geometry."
        ) from exc

    geom_number = _geometry_number_from_path(geom_text_path, ras_object=ras_object)
    try:
        plan_df = ras_object.get_plan_entries()
    except Exception as exc:
        raise RuntimeError(
            "Could not read plan entries needed for geometry HDF recompilation."
        ) from exc

    for _, row in plan_df.iterrows():
        plan_number = _normalize_component_number(row.get("plan_number"))
        if plan_number is None:
            continue

        geom_path = row.get("Geom Path")
        if geom_path is not None and _paths_equivalent(geom_path, geom_text_path):
            return plan_number

        for column_name in ("geometry_number", "geom_number", "Geom File"):
            if column_name not in row:
                continue
            row_geom_number = _normalize_component_number(row.get(column_name))
            if (
                geom_number is not None
                and row_geom_number is not None
                and row_geom_number == geom_number
            ):
                return plan_number

    raise RuntimeError(
        "recompile_via_rasexe=True could not find a plan referencing "
        f"{geom_text_path.name}. Clone or assign a plan to this geometry before "
        "requesting Ras.exe recompilation."
    )


def _recompile_geometry_hdf_via_rasexe(
    geom_text_path: Path,
    hdf_path: Path,
    *,
    ras_object=None,
) -> Path:
    """Refresh a compiled geometry HDF from text through HEC-RAS/Ras.exe."""
    plan_number = _find_plan_for_geometry(geom_text_path, ras_object=ras_object)
    from .GeomPreprocessor import GeomPreprocessor

    logger.info(
        f"Refreshing compiled geometry HDF for {geom_text_path.name} "
        f"through Ras.exe using plan p{plan_number}"
    )
    preprocess_result = GeomPreprocessor.run_geometry_preprocessor(
        plan_number,
        ras_object=ras_object,
        clear_geompre=True,
        force=True,
        geometry_only=True,
    )
    if not preprocess_result.success:
        raise RuntimeError(
            "Ras.exe geometry preprocessing failed while refreshing "
            f"{hdf_path.name}: {preprocess_result.error or preprocess_result.first_error_line}"
        )
    if not hdf_path.exists():
        raise RuntimeError(
            "Ras.exe geometry preprocessing completed but did not create "
            f"{hdf_path}"
        )
    return hdf_path


def _mesh_metadata_is_meaningful(
    area: dict[str, float | int | None],
) -> bool:
    seed_count = area.get("seed_count")
    spacing_dx = area.get("spacing_dx")
    spacing_dy = area.get("spacing_dy")
    return (
        (isinstance(seed_count, int) and seed_count > 0)
        or (isinstance(spacing_dx, (int, float)) and spacing_dx > 0)
        or (isinstance(spacing_dy, (int, float)) and spacing_dy > 0)
    )


def _mesh_hdf_consistency_issues(
    geom_text_path: Path,
    hdf_path: Path,
    *,
    mesh_name: str | None = None,
) -> list[str]:
    """Return content mismatches between geometry text seeds and HDF metadata."""
    text_metadata = _read_mesh_metadata_from_text(geom_text_path)
    if mesh_name is not None:
        text_metadata = {
            name: area
            for name, area in text_metadata.items()
            if name == mesh_name
        }
    if not text_metadata:
        return []

    hdf_metadata = _read_mesh_metadata_from_hdf(hdf_path)
    issues: list[str] = []

    for area_name, text_area in text_metadata.items():
        if not _mesh_metadata_is_meaningful(text_area):
            continue

        hdf_area = hdf_metadata.get(area_name)
        if hdf_area is None:
            issues.append(f"{area_name}: missing from compiled HDF")
            continue

        text_seed_count = text_area.get("seed_count")
        hdf_cell_count = hdf_area.get("cell_count")
        hdf_count_source = hdf_area.get("cell_count_source")
        if (
            isinstance(text_seed_count, int)
            and isinstance(hdf_cell_count, int)
            and hdf_count_source == "Attributes/Cell Count"
            and text_seed_count != hdf_cell_count
        ):
            issues.append(
                f"{area_name}: text Storage Area 2D Points={text_seed_count} "
                f"but HDF Cell Count={hdf_cell_count}"
            )

        for axis in ("dx", "dy"):
            text_spacing = text_area.get(f"spacing_{axis}")
            hdf_spacing = hdf_area.get(f"spacing_{axis}")
            if not isinstance(text_spacing, (int, float)) or text_spacing <= 0:
                continue
            if not isinstance(hdf_spacing, (int, float)) or hdf_spacing <= 0:
                issues.append(
                    f"{area_name}: text Spacing {axis}={text_spacing:g} "
                    "but HDF spacing is missing"
                )
                continue
            if abs(float(text_spacing) - float(hdf_spacing)) > 0.001:
                issues.append(
                    f"{area_name}: text Spacing {axis}={text_spacing:g} "
                    f"but HDF Spacing {axis}={float(hdf_spacing):g}"
                )

    return issues


def _ensure_hdf(
    geom_text_path: Path,
    hecras_dir=None,
    *,
    require_current: bool = True,
    ras_object=None,
    mesh_name: str | None = None,
    recompile_via_rasexe: bool = False,
) -> Path:
    """Return an existing compiled HDF for *geom_text_path*.

    This helper intentionally does not call ``compile_geometry()``. True
    .g## text -> .g##.hdf generation is unavailable here unless HEC-RAS/Ras.exe
    drives it.
    """
    hdf_path = geom_text_path.with_suffix(geom_text_path.suffix + ".hdf")
    if not hdf_path.exists():
        if recompile_via_rasexe:
            _recompile_geometry_hdf_via_rasexe(
                geom_text_path,
                hdf_path,
                ras_object=ras_object,
            )
            if hdf_path.exists():
                return hdf_path
        raise RuntimeError(
            _geometry_hdf_unavailable_message(geom_text_path, hdf_path, "missing")
        )

    try:
        consistency_issues = _mesh_hdf_consistency_issues(
            geom_text_path,
            hdf_path,
            mesh_name=mesh_name,
        )
    except Exception as exc:
        consistency_issues = [f"unreadable; {exc}"]

    if consistency_issues:
        reason = "stale; " + "; ".join(consistency_issues)
        if recompile_via_rasexe:
            _recompile_geometry_hdf_via_rasexe(
                geom_text_path,
                hdf_path,
                ras_object=ras_object,
            )
            consistency_issues = _mesh_hdf_consistency_issues(
                geom_text_path,
                hdf_path,
                mesh_name=mesh_name,
            )
            if not consistency_issues:
                return hdf_path
            reason = "stale after Ras.exe refresh; " + "; ".join(consistency_issues)

        message = _geometry_hdf_unavailable_message(
            geom_text_path,
            hdf_path,
            reason,
        )
        if require_current:
            raise RuntimeError(message)
        logger.warning(message)
    return hdf_path


def _safe_resolve_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _paths_equivalent(left: Union[str, Path], right: Union[str, Path]) -> bool:
    left_norm = os.path.normcase(os.path.normpath(str(left)))
    right_norm = os.path.normcase(os.path.normpath(str(right)))
    return left_norm == right_norm


def _resolve_geom_hdf_path(
    geom_number: Union[str, Number, Path],
    hecras_dir=None,
    ras_object=None,
    *,
    require_current: bool = True,
) -> Path:
    """Resolve a geometry number, .g## text path, or .g##.hdf path to HDF."""
    candidate = None
    if isinstance(geom_number, Path):
        candidate = geom_number
    elif isinstance(geom_number, str):
        candidate = Path(geom_number)

    if candidate is not None and candidate.suffix.lower() in {".hdf", ".h5"}:
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Geometry HDF not found: {candidate}")

    geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
    return _ensure_hdf(
        geom_text_path,
        hecras_dir=hecras_dir,
        require_current=require_current,
        ras_object=ras_object,
    )


def _decode_hdf_attr(value) -> Optional[str]:
    return _shared_decode_hdf_attr(value)


def _resolve_association_attr_path(geom_hdf_path: Path, attr_value: str) -> Path:
    return _shared_resolve_association_attr_path(geom_hdf_path, attr_value)


def _validate_geometry_hdf_path(hdf_path: Path) -> None:
    ensure_geometry_group(hdf_path)


def _read_geometry_association(
    hdf_path: Path,
    *,
    resolve_paths: bool = True,
) -> dict:
    return read_geometry_association(hdf_path, resolve_paths=resolve_paths)


def _validate_geometry_association(
    hdf_path: Path,
    expected_paths: dict[str, Path],
) -> None:
    observed = _read_geometry_association(hdf_path, resolve_paths=True)
    mismatches = compare_geometry_association_paths(observed, expected_paths)
    if mismatches:
        mismatch = mismatches[0]
        field = _GEOMETRY_ASSOCIATION_FIELDS[mismatch["key"]]["filename_attr"]
        raise RuntimeError(
            f"SetGeometryAssociationCommand did not persist {field} on "
            f"{hdf_path}. Expected {mismatch['expected']}, "
            f"observed {mismatch['observed']!r}."
        )


def _normalise_polygon_coords(polygon) -> "numpy.ndarray":
    """Convert a polygon argument to an (N, 2) float64 NumPy array.

    Accepts: list/tuple of (x, y), NumPy (N, 2) array, or Shapely Polygon.
    """
    import numpy as np

    if hasattr(polygon, "exterior"):
        coords = np.array(polygon.exterior.coords, dtype=np.float64)
    else:
        coords = np.asarray(polygon, dtype=np.float64)

    if coords.ndim != 2 or coords.shape[1] != 2:
        raise ValueError(
            f"Polygon must be (N, 2) coordinates, got shape {coords.shape}."
        )
    return coords


def _create_hdf_dataset(hf, key: str, data: "numpy.ndarray") -> None:
    """Create an HDF5 dataset matching HEC-RAS conventions.

    Uses gzip compression and sets chunk shape equal to the data shape
    (single-chunk layout), consistent with HEC-RAS compiled geometry.
    """
    hf.create_dataset(
        key,
        data=data,
        compression="gzip",
        compression_opts=1,
        chunks=data.shape,
    )


class GeomMesh:
    """
    Headless 2D mesh generation, repair, and BC conflict resolution.

    Uses RasMapperLib.dll via pythonnet to generate finite volume meshes
    without the RAS Mapper GUI. Includes a 5-tier auto-fix pipeline that
    mirrors TryAutoFix behavior from the GUI.

    All methods are static — no instantiation needed.

    Example:
        >>> from ras_commander.geom import GeomMesh
        >>> GeomMesh.setup_gdal_bridge()  # optional explicit preflight
        >>> result = GeomMesh.generate("01")  # by geometry number
        >>> result = GeomMesh.generate("project.g01")  # or by file path
        >>> if result:
        ...     print(f"Mesh: {result.cell_count} cells")
    """

    @staticmethod
    @log_call
    def setup_gdal_bridge(
        hecras_dir: Optional[Union[str, Path]] = None,
        python_dir: Optional[Union[str, Path]] = None,
        create_junction: bool = True,
    ) -> bool:
        """
        Configure HEC-RAS GDAL runtime for RasMapperLib.

        The default path points GDAL environment variables and DLL search paths
        at the GDAL runtime bundled with HEC-RAS, then verifies the legacy
        ``python.exe`` sibling GDAL bridge before RasMapperLib is loaded.

        Returns True if the process runtime was configured successfully.
        """
        if platform.system() != "Windows":
            logger.warning("setup_gdal_bridge() is Windows-only")
            return False

        if hecras_dir is None:
            hecras_dir = _find_hecras_dir()

        try:
            configure_hecras_gdal_runtime(hecras_dir)
        except FileNotFoundError as exc:
            logger.error(str(exc))
            return False

        if create_junction:
            try:
                configure_rasmapper_gdal_bridge(hecras_dir, python_dir)
            except (FileNotFoundError, RuntimeError) as exc:
                logger.error(str(exc))
                return False

        return True

    @staticmethod
    @log_call
    def set_breakline_spacing(
        geom_number: Union[str, Number, Path],
        near: Optional[float] = None,
        far: Optional[float] = None,
        near_repeats: Optional[int] = None,
        protection_radius: Optional[int] = None,
        breakline_name: Optional[str] = None,
        breakline_fid: Optional[int] = None,
        all_breaklines: bool = False,
        ras_object=None,
    ) -> Path:
        """
        Edit BreakLine spacing properties in a .g## text file.

        Target a single breakline by *breakline_name* or *breakline_fid*
        (0-based index in file order).  Set ``all_breaklines=True`` for
        bulk changes (model building, sensitivity analysis).

        HEC-RAS allows duplicate breakline names (including empty names).
        When duplicates exist, *breakline_name* matches the **first**
        occurrence.  Use *breakline_fid* for reliable targeting — call
        ``get_breakline_names()`` to inspect the FID-to-name mapping and
        check for duplicates before editing by name.

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            near: BreakLine near-spacing in project units. None keeps existing.
            far: BreakLine far-spacing in project units. None keeps existing.
            near_repeats: Number of offset seed rows on each side of breaklines.
                None keeps existing value.
            protection_radius: Enable 1-cell protection radius (0 or 1).
                None keeps existing value.
            breakline_name: Name of the breakline to modify.
            breakline_fid: 0-based index of the breakline in file order.
                Most reliable selector — breaklines can be unnamed or
                have duplicate names.
            all_breaklines: If True, apply spacing to every breakline.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            Path to .bak backup file created before writing.

        Raises:
            ValueError: If no target is specified, or if the target is
                not found in the file.
        """
        if not all_breaklines and breakline_name is None and breakline_fid is None:
            raise ValueError(
                "Provide breakline_name or breakline_fid for single-breakline "
                "edits, or set all_breaklines=True for bulk changes."
            )
        if all_breaklines and (breakline_name is not None or breakline_fid is not None):
            raise ValueError(
                "all_breaklines=True cannot be combined with "
                "breakline_name or breakline_fid."
            )
        if breakline_name is not None and breakline_fid is not None:
            raise ValueError(
                "Provide breakline_name or breakline_fid, not both."
            )
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        return _set_breakline_spacing_impl(
            geom_text_path, near, far,
            near_repeats=near_repeats,
            protection_radius=protection_radius,
            breakline_name=breakline_name,
            breakline_fid=breakline_fid,
            all_breaklines=all_breaklines,
        )

    @staticmethod
    @log_call
    def get_breakline_names(
        geom_number: Union[str, Number, Path],
        ras_object=None,
    ) -> list[tuple[int, str]]:
        """
        Read breakline names from a .g## text file.

        HEC-RAS allows duplicate and empty breakline names.  Use this
        method to inspect the FID-to-name mapping before calling
        ``set_breakline_spacing()`` or ``set_breakline_name()`` by name.
        When duplicates exist, targeting by *breakline_fid* is the most
        reliable approach.

        Returns:
            List of (fid, name) tuples in file order.  *fid* is the
            0-based index.  Unnamed breaklines have ``name=""``.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        return _read_breakline_names_from_text(geom_text_path)

    @staticmethod
    @log_call
    def set_breakline_name(
        geom_number: Union[str, Number, Path],
        new_name: str,
        breakline_fid: Optional[int] = None,
        old_name: Optional[str] = None,
        ras_object=None,
    ) -> Path:
        """
        Rename a breakline in a .g## text file.

        HEC-RAS allows duplicate and empty breakline names.
        *breakline_fid* (0-based index in file order) is the most
        reliable selector.  When using *old_name*, this method raises
        ``ValueError`` if multiple breaklines share that name — use
        ``get_breakline_names()`` to inspect duplicates first, then
        target by FID or assign unique descriptive names.

        Args:
            geom_number: Geometry number or path to .g## text file.
            new_name: New name to assign.
            breakline_fid: 0-based index of the breakline in file order.
                Most reliable selector — breaklines can be unnamed or
                have duplicate names.
            old_name: Current name of the breakline.  Raises if
                multiple breaklines share this name.
            ras_object: Optional RasPrj instance.

        Returns:
            Path to .bak backup file created before writing.

        Raises:
            ValueError: If neither selector is given, both are given,
                the target is not found, or *old_name* matches multiple
                breaklines.
        """
        if breakline_fid is None and old_name is None:
            raise ValueError("Provide breakline_fid or old_name.")
        if breakline_fid is not None and old_name is not None:
            raise ValueError("Provide breakline_fid or old_name, not both.")
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        return _set_breakline_name_impl(
            geom_text_path, new_name,
            breakline_fid=breakline_fid,
            old_name=old_name,
        )

    @staticmethod
    @log_call
    def get_breakline_spacing(
        geom_number: Union[str, Number, Path],
        ras_object=None,
    ) -> list[tuple[int, str, float, float, int, int]]:
        """
        Read per-breakline spacing from a .g## text file.

        HEC-RAS allows duplicate and empty breakline names.  The *fid*
        in each tuple is the most reliable identifier — use it with
        ``set_breakline_spacing(breakline_fid=...)`` when names are
        ambiguous.

        Returns:
            List of (fid, name, near, far, near_repeats, protection_radius)
            tuples in file order.  *fid* is the 0-based index.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        return _read_breakline_spacing_from_text(geom_text_path)

    @staticmethod
    @log_call
    def get_refinement_region_names(
        geom_number: Union[str, Number, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> list[tuple[int, str]]:
        """
        Read refinement region names from the compiled HDF.

        HEC-RAS allows duplicate and empty refinement region names.
        Use this method to inspect the FID-to-name mapping before
        calling ``set_refinement_region_spacing()`` or
        ``set_refinement_region_name()`` by name.  When duplicates
        exist, targeting by *region_fid* is the most reliable approach.

        Refinement regions are stored in HDF, not .g## text.  The compiled
        HDF must already exist.

        Returns:
            List of (fid, name) tuples in HDF order.  *fid* is the
            0-based index.
        """
        import h5py

        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        rr_key = "Geometry/2D Flow Area Refinement Regions/Attributes"
        result = []
        with h5py.File(str(hdf_path), "r") as hf:
            if rr_key not in hf:
                return result
            data = hf[rr_key][:]
            for i, row in enumerate(data):
                name = row["Name"].decode("utf-8", errors="replace").strip()
                result.append((i, name))
        return result

    @staticmethod
    @log_call
    def set_refinement_region_name(
        geom_number: Union[str, Number, Path],
        new_name: str,
        region_fid: Optional[int] = None,
        old_name: Optional[str] = None,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> None:
        """
        Rename a refinement region in the compiled HDF.

        HEC-RAS allows duplicate and empty refinement region names.
        *region_fid* (0-based index in HDF order) is the most reliable
        selector.  When using *old_name*, this method raises
        ``ValueError`` if multiple regions share that name — use
        ``get_refinement_region_names()`` to inspect duplicates first,
        then target by FID or assign unique descriptive names.

        Args:
            geom_number: Geometry number or path to .g## text file.
            new_name: New name to assign.
            region_fid: 0-based index of the region in HDF order.
                Most reliable selector — regions can be unnamed or
                have duplicate names.
            old_name: Current name of the region.  Raises if multiple
                regions share this name.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance.

        Raises:
            ValueError: If neither selector is given, both are given,
                the target is not found, or *old_name* matches multiple
                regions.
        """
        import h5py

        if region_fid is None and old_name is None:
            raise ValueError("Provide region_fid or old_name.")
        if region_fid is not None and old_name is not None:
            raise ValueError("Provide region_fid or old_name, not both.")

        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        rr_key = "Geometry/2D Flow Area Refinement Regions/Attributes"
        with h5py.File(str(hdf_path), "r+") as hf:
            if rr_key not in hf:
                raise ValueError("No refinement regions in geometry HDF.")
            data = hf[rr_key][:]

            found_idx = None
            for i in range(len(data)):
                name = data["Name"][i].decode("utf-8", errors="replace").strip()
                match = False
                if region_fid is not None:
                    match = i == region_fid
                elif old_name is not None:
                    match = name == old_name
                if match:
                    if found_idx is not None:
                        raise ValueError(
                            f"Multiple refinement regions match {repr(old_name)}; "
                            f"use region_fid for disambiguation."
                        )
                    found_idx = i

            if found_idx is None:
                target = (
                    f"FID {region_fid}" if region_fid is not None
                    else repr(old_name)
                )
                raise ValueError(
                    f"Refinement region {target} not found in HDF."
                )

            name_len = data.dtype["Name"].itemsize
            encoded = new_name.encode("utf-8")
            if len(encoded) > name_len:
                encoded = new_name.encode("utf-8")[:name_len]
                encoded = encoded.decode("utf-8", errors="ignore").encode("utf-8")
            data["Name"][found_idx] = encoded
            hf[rr_key][:] = data

        logger.info(
            f"Renamed refinement region FID {found_idx} → '{new_name}' "
            f"in {hdf_path.name}"
        )

    @staticmethod
    @log_call
    def get_refinement_regions(
        geom_number: Union[str, Number, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> list[dict]:
        """
        Read refinement region names and spacing from the compiled HDF.

        HEC-RAS allows duplicate and empty refinement region names.
        The *fid* in each dict is the most reliable identifier — use it
        with ``set_refinement_region_spacing(region_fid=...)`` or
        ``set_refinement_region_name(region_fid=...)`` when names are
        ambiguous.

        Refinement regions are stored in HDF, not .g## text.  The compiled
        HDF must already exist.

        Returns:
            List of dicts with keys: fid, name, spacing_dx, spacing_dy.
            Empty list if no refinement regions exist.
        """
        import h5py

        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        rr_key = "Geometry/2D Flow Area Refinement Regions/Attributes"
        result = []
        with h5py.File(str(hdf_path), "r") as hf:
            if rr_key not in hf:
                return result
            data = hf[rr_key][:]
            has_dx = "Spacing dx" in data.dtype.names
            has_dy = "Spacing dy" in data.dtype.names
            for i, row in enumerate(data):
                name = row["Name"].decode("utf-8", errors="replace").strip()
                dx = float(row["Spacing dx"]) if has_dx else 0.0
                dy = float(row["Spacing dy"]) if has_dy else 0.0
                result.append({
                    "fid": i, "name": name,
                    "spacing_dx": dx, "spacing_dy": dy,
                })
        return result

    @staticmethod
    @log_call
    def set_refinement_region_spacing(
        geom_number: Union[str, Number, Path],
        spacing_dx: Optional[float] = None,
        spacing_dy: Optional[float] = None,
        region_name: Optional[str] = None,
        region_fid: Optional[int] = None,
        all_regions: bool = False,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> None:
        """
        Set refinement region cell spacing in the compiled HDF.

        Refinement regions override the base cell size within their
        polygon boundaries.  Target a single region by *region_name*
        or *region_fid* (0-based index in HDF order).  Set
        ``all_regions=True`` for bulk changes.

        HEC-RAS allows duplicate and empty refinement region names.
        When duplicates exist, *region_name* matches the **first**
        occurrence.  Use *region_fid* for reliable targeting — call
        ``get_refinement_region_names()`` to inspect the FID-to-name
        mapping and check for duplicates before editing by name.

        Args:
            geom_number: Geometry number or path to .g## text file.
            spacing_dx: Cell spacing in the X direction (project units).
                None keeps existing value.
            spacing_dy: Cell spacing in the Y direction (project units).
                None keeps existing value.  Defaults to spacing_dx if
                spacing_dx is provided and spacing_dy is None.
            region_name: Name of the refinement region to modify.
            region_fid: 0-based index of the region in HDF order.
                Most reliable selector — regions can be unnamed or
                have duplicate names.
            all_regions: If True, apply spacing to every region.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance.

        Raises:
            ValueError: If no target is specified, or if the target is
                not found.
        """
        import h5py

        if not all_regions and region_name is None and region_fid is None:
            raise ValueError(
                "Provide region_name or region_fid for single-region edits, "
                "or set all_regions=True for bulk changes."
            )
        if all_regions and (region_name is not None or region_fid is not None):
            raise ValueError(
                "all_regions=True cannot be combined with "
                "region_name or region_fid."
            )
        if region_name is not None and region_fid is not None:
            raise ValueError(
                "Provide region_name or region_fid, not both."
            )
        if spacing_dx is not None and spacing_dy is None:
            spacing_dy = spacing_dx

        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        rr_key = "Geometry/2D Flow Area Refinement Regions/Attributes"
        with h5py.File(str(hdf_path), "r+") as hf:
            if rr_key not in hf:
                raise ValueError("No refinement regions in geometry HDF.")
            data = hf[rr_key][:]
            has_dx = "Spacing dx" in data.dtype.names
            has_dy = "Spacing dy" in data.dtype.names
            if not has_dx or not has_dy:
                raise ValueError(
                    "HDF refinement regions missing Spacing columns."
                )

            if region_name is not None:
                has_name_col = "Name" in data.dtype.names
                if not has_name_col:
                    raise ValueError(
                        "HDF refinement regions missing Name column — "
                        "use region_fid instead."
                    )
                matches = [
                    i for i in range(len(data))
                    if data["Name"][i].decode("utf-8", errors="replace").strip()
                    == region_name
                ]
                if len(matches) > 1:
                    raise ValueError(
                        f"Multiple refinement regions named '{region_name}' "
                        f"(count={len(matches)}). Use region_fid for "
                        f"disambiguation — call get_refinement_region_names() "
                        f"to inspect FID-to-name mapping."
                    )

            found = False
            for i in range(len(data)):
                if all_regions:
                    target_match = True
                elif region_fid is not None:
                    target_match = i == region_fid
                else:
                    name = data["Name"][i].decode("utf-8", errors="replace").strip()
                    target_match = name == region_name
                if not target_match:
                    continue
                found = True
                if spacing_dx is not None:
                    data["Spacing dx"][i] = spacing_dx
                if spacing_dy is not None:
                    data["Spacing dy"][i] = spacing_dy

            if not all_regions and not found:
                target_desc = (
                    f"FID {region_fid}" if region_fid is not None
                    else f"'{region_name}'"
                )
                raise ValueError(
                    f"Refinement region {target_desc} not found in HDF."
                )
            hf[rr_key][:] = data

        target = (
            f"FID {region_fid}" if region_fid is not None
            else region_name or "ALL"
        )
        logger.info(
            f"Refinement region [{target}]: dx={spacing_dx}, dy={spacing_dy} "
            f"→ {hdf_path.name}"
        )

    @staticmethod
    @log_call
    def add_refinement_region(
        geom_number: Union[str, Number, Path],
        polygon,
        spacing_dx: float,
        spacing_dy: Optional[float] = None,
        name: str = "",
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> int:
        """
        Create a new refinement region in the compiled geometry HDF.

        Refinement regions override the base cell size within their
        polygon boundaries during mesh generation.  They are stored
        exclusively in HDF — there is no .g## text representation.

        The polygon, spacing, and name are written into four HDF
        datasets under ``Geometry/2D Flow Area Refinement Regions/``
        using the exact schema HEC-RAS expects: gzip-compressed
        datasets with ``int32`` index arrays, ``float64`` coordinates,
        and ``float32`` attribute values.

        Args:
            geom_number: Geometry number or path to .g## text file.
            polygon: Region boundary as a list of (x, y) tuples,
                a Shapely Polygon, or any object whose
                ``exterior.coords`` yields (x, y) pairs.
                The ring is closed automatically if needed.
            spacing_dx: Cell spacing in the X direction (project
                units, e.g. feet or metres).
            spacing_dy: Cell spacing in the Y direction.  Defaults
                to *spacing_dx* when ``None``.
            name: Region name stored in the HDF ``Name`` field
                (max 32 bytes UTF-8).  Empty string is valid.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance.

        Returns:
            The 0-based FID of the newly created region.

        Raises:
            ValueError: If *polygon* has fewer than 3 vertices or
                *spacing_dx* is not positive.
        """
        import h5py
        import numpy as np

        if spacing_dy is None:
            spacing_dy = spacing_dx
        if spacing_dx <= 0 or spacing_dy <= 0:
            raise ValueError(
                f"Spacing must be positive (got dx={spacing_dx}, dy={spacing_dy})."
            )

        # ── Normalise polygon to (N, 2) float64 array ──────────────
        coords = _normalise_polygon_coords(polygon)
        if len(coords) < 3:
            raise ValueError(
                f"Polygon must have at least 3 vertices (got {len(coords)})."
            )
        # Close the ring if caller didn't
        if not np.allclose(coords[0], coords[-1]):
            coords = np.vstack([coords, coords[:1]])

        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        rr_group_key = "Geometry/2D Flow Area Refinement Regions"
        attr_key = f"{rr_group_key}/Attributes"
        info_key = f"{rr_group_key}/Polygon Info"
        parts_key = f"{rr_group_key}/Polygon Parts"
        points_key = f"{rr_group_key}/Polygon Points"

        # ── Encode name ─────────────────────────────────────────────
        name_bytes = name.encode("utf-8")[:32]
        # Ensure valid UTF-8 after byte truncation
        name_bytes = name_bytes.decode("utf-8", errors="ignore").encode("utf-8")

        # ── Attributes dtype matches HEC-RAS convention ─────────────
        attr_dtype = np.dtype([
            ("Name", "S32"),
            ("Spacing dx", "<f4"),
            ("Spacing dy", "<f4"),
        ])

        n_pts = len(coords)
        new_attr_row = np.array(
            [(name_bytes, np.float32(spacing_dx), np.float32(spacing_dy))],
            dtype=attr_dtype,
        )

        with h5py.File(str(hdf_path), "a") as hf:
            # ── Read existing data (if any) ─────────────────────────
            if attr_key in hf:
                old_attrs = hf[attr_key][:]
                old_info = hf[info_key][:]
                old_parts = hf[parts_key][:] if parts_key in hf else np.empty((0, 2), dtype=np.int32)
                old_points = hf[points_key][:]

                # Coerce existing Attributes to canonical dtype if needed
                if old_attrs.dtype != attr_dtype:
                    coerced = np.empty(len(old_attrs), dtype=attr_dtype)
                    for fname in attr_dtype.names:
                        if fname in old_attrs.dtype.names:
                            coerced[fname] = old_attrs[fname]
                    old_attrs = coerced

                existing_n = len(old_attrs)
                total_old_pts = len(old_points)
                total_old_parts = len(old_parts)
            else:
                old_attrs = np.empty(0, dtype=attr_dtype)
                old_info = np.empty((0, 4), dtype=np.int32)
                old_parts = np.empty((0, 2), dtype=np.int32)
                old_points = np.empty((0, 2), dtype=np.float64)
                existing_n = 0
                total_old_pts = 0
                total_old_parts = 0

            new_fid = existing_n

            # ── Build expanded arrays ───────────────────────────────
            merged_attrs = np.concatenate([old_attrs, new_attr_row])

            new_info_row = np.array(
                [[total_old_pts, n_pts, total_old_parts, 1]],
                dtype=np.int32,
            )
            merged_info = np.vstack([old_info, new_info_row]) if existing_n > 0 else new_info_row

            new_parts_row = np.array([[0, n_pts]], dtype=np.int32)
            merged_parts = np.vstack([old_parts, new_parts_row]) if total_old_parts > 0 else new_parts_row

            merged_points = np.vstack([old_points, coords]) if total_old_pts > 0 else coords

            # ── Delete-and-recreate (matches RASDecomp pattern) ─────
            for key in (attr_key, info_key, parts_key, points_key):
                if key in hf:
                    del hf[key]

            _create_hdf_dataset(hf, attr_key, merged_attrs)
            _create_hdf_dataset(hf, info_key, merged_info)
            _create_hdf_dataset(hf, parts_key, merged_parts)
            _create_hdf_dataset(hf, points_key, merged_points)

        logger.info(
            f"Added refinement region FID {new_fid} "
            f"(name='{name}', dx={spacing_dx}, dy={spacing_dy}, "
            f"vertices={n_pts}) → {hdf_path.name}"
        )
        return new_fid

    @staticmethod
    @log_call
    def compile_geometry(
        geom_number: Union[str, Number, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> Path:
        """
        Disabled compatibility shim for .g## text -> .g##.hdf generation.

        ras-commander cannot compile a plain-text geometry file into its
        compiled HDF representation without full HEC-RAS/Ras.exe behavior.
        RasMapperLib's CompleteGeometryCommand only completes existing HDF
        files; it is not a text geometry compiler.

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            Never returns successfully.

        Raises:
            FileNotFoundError: If geometry file cannot be resolved.
            RuntimeError: Always, because this path is unavailable.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        hdf_path = geom_text_path.with_suffix(geom_text_path.suffix + ".hdf")
        raise RuntimeError(
            _geometry_hdf_unavailable_message(
                geom_text_path,
                hdf_path,
                "not generated by ras-commander",
            )
        )

    @staticmethod
    @log_call
    def get_geometry_association(
        geom_number: Union[str, Number, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
        resolve_paths: bool = True,
    ) -> dict:
        """
        Read terrain and classification associations from a geometry HDF.

        Args:
            geom_number: Geometry number, .g## text path, or .g##.hdf path.
                Text inputs require an existing current .g##.hdf.
            hecras_dir: Kept for API symmetry; no DLLs are loaded here.
            ras_object: Optional RasPrj instance for geometry-number lookup.
            resolve_paths: If True, return absolute paths resolved relative to
                the geometry HDF. If False, return the raw HDF attribute text.

        Returns:
            Dict with keys ``terrain_hdf_path``, ``landcover_hdf_path``,
            ``infiltration_hdf_path``, ``sediment_soils_hdf_path``, matching
            ``*_layer_name`` keys, and ``si_units``.
        """
        hdf_path = _resolve_geom_hdf_path(
            geom_number,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )
        hdf_path = _safe_resolve_path(hdf_path)
        return _read_geometry_association(hdf_path, resolve_paths=resolve_paths)

    @staticmethod
    @log_call
    def set_geometry_association(
        geom_number: Union[str, Number, Path],
        terrain_hdf_path: Optional[Union[str, Path]] = None,
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        infiltration_hdf_path: Optional[Union[str, Path]] = None,
        sediment_soils_hdf_path: Optional[Union[str, Path]] = None,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
        validate: bool = True,
    ) -> Path:
        """
        Associate terrain / classification layers to an existing geometry HDF.

        This wraps RasMapperLib's ``SetGeometryAssociationCommand`` and writes
        attributes under ``/Geometry`` in the compiled ``.g##.hdf``. It does
        not create or refresh a missing geometry HDF.

        Args:
            geom_number: Geometry number, .g## text path, or .g##.hdf path.
                Text inputs require an existing current .g##.hdf.
            terrain_hdf_path: Terrain HDF to associate.
            landcover_hdf_path: Land-cover / Manning's n HDF.
            infiltration_hdf_path: Infiltration HDF.
            sediment_soils_hdf_path: Sediment bed-material soils HDF. This is
                the HEC-RAS ``SedimentSoilsFilename`` slot, not the hydrologic
                soils layer used to build infiltration data.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for geometry-number lookup.
            validate: Re-read ``/Geometry`` attributes after execution and
                verify supplied paths were persisted.

        Returns:
            Path to the existing geometry HDF that was updated.

        Raises:
            ValueError: If no association paths are supplied.
            FileNotFoundError: If any supplied artifact is missing.
            RuntimeError: If the HDF is missing /Geometry, execution fails, or
                validation does not find the expected attributes.
        """
        supplied = {
            "terrain_hdf_path": terrain_hdf_path,
            "landcover_hdf_path": landcover_hdf_path,
            "infiltration_hdf_path": infiltration_hdf_path,
            "sediment_soils_hdf_path": sediment_soils_hdf_path,
        }
        if all(path is None for path in supplied.values()):
            raise ValueError("Provide at least one geometry association path.")

        hdf_path = _resolve_geom_hdf_path(
            geom_number,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )
        hdf_path = _safe_resolve_path(hdf_path)
        _validate_geometry_hdf_path(hdf_path)

        resolved_paths = {}
        for key, path_value in supplied.items():
            if path_value is None:
                continue
            resolved_path = _safe_resolve_path(Path(path_value))
            if not resolved_path.exists():
                raise FileNotFoundError(
                    f"Association artifact not found for {key}: {resolved_path}"
                )
            resolved_paths[key] = resolved_path

        _load_dlls(hecras_dir)
        from RasMapperLib.Scripting import SetGeometryAssociationCommand  # type: ignore

        cmd = SetGeometryAssociationCommand()
        cmd.GeometryFilename = str(hdf_path)
        for key, resolved_path in resolved_paths.items():
            command_property = _GEOMETRY_ASSOCIATION_FIELDS[key]["command_property"]
            setattr(cmd, command_property, str(resolved_path))

        try:
            cmd.Execute(None)
        except Exception as exc:
            raise RuntimeError(
                f"SetGeometryAssociationCommand failed for {hdf_path.name}: {exc}"
            ) from exc

        if validate:
            _validate_geometry_association(hdf_path, resolved_paths)

        logger.info(
            "Updated geometry associations on %s: %s",
            hdf_path.name,
            ", ".join(sorted(resolved_paths)),
        )
        return hdf_path

    @staticmethod
    @log_call
    def compute_property_tables(
        geom_number: Union[str, Number, Path],
        mesh_name: Optional[str] = None,
        mesh_index: int = 0,
        force: bool = True,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> bool:
        """
        Compute 2D hydraulic property tables for a geometry.

        Triggers RAS Mapper's property table computation: face profiles,
        Manning's n assignment, face hydraulic tables, and cell properties.
        Requires a terrain layer associated with the geometry.

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            mesh_name: 2D flow area name. Auto-detected if only one exists.
            mesh_index: Index of the 2D flow area (default 0).
            force: Force recomputation even if tables are up-to-date.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            True if property tables were computed successfully.

        Raises:
            FileNotFoundError: If geometry file cannot be resolved.
            RuntimeError: If terrain is missing or computation fails.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)

        _load_dlls(hecras_dir)

        hdf_path = _ensure_hdf(
            geom_text_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
        )

        ns = _imports()
        geom = ns["RASGeometry"](str(hdf_path))
        d2fa = geom.D2FlowArea

        if d2fa.FeatureCount() == 0:
            raise RuntimeError(f"No 2D flow areas in {geom_text_path.name}")

        if mesh_name is not None:
            fid = d2fa.GetFeatureByName(mesh_name)
            if fid == -1:
                raise RuntimeError(
                    f"2D flow area '{mesh_name}' not found in "
                    f"{geom_text_path.name}"
                )
        else:
            fid = mesh_index
            mesh_name = d2fa.GetFeatureName(fid)

        terrain = geom.Terrain
        if terrain is None:
            raise RuntimeError(
                f"No terrain associated with {geom_text_path.name}. "
                f"Associate a terrain in RAS Mapper before computing "
                f"property tables."
            )

        if force:
            result = d2fa.CreatePropertyTables(fid, None, False, None)
        else:
            result = d2fa.EnsurePropertyTables(False, True, False, None)

        if result:
            logger.info(
                f"Property tables computed for '{mesh_name}' "
                f"in {geom_text_path.name}"
            )
        else:
            logger.warning(
                f"Property table computation returned False for "
                f"'{mesh_name}' in {geom_text_path.name}"
            )

        return bool(result)

    @staticmethod
    @log_call
    def generate(
        geom_number: Union[str, Number, Path],
        mesh_name: Optional[str] = None,
        mesh_index: int = 0,
        cell_size: Optional[float] = None,
        bl_spacing: Optional[float] = None,
        near_repeats: Optional[int] = None,
        protection_radius: Optional[int] = None,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[Union[str, Path]] = None,
        bl_spacing_near: Optional[float] = None,
        bl_spacing_far: Optional[float] = None,
        ras_object=None,
        recompile_via_rasexe: bool = False,
        _require_current_hdf: bool = True,
    ) -> MeshResult:
        """
        Generate or regenerate a 2D mesh headlessly via text-first workflow.

        The .g01 text file is the sole persistent output. The HDF is used only
        as an existing temporary workspace for .NET geometry loading and cell
        center extraction. ras-commander does not generate .g##.hdf from text.

        Workflow:
            1. Validate an existing content-current compiled .g##.hdf
               workspace, optionally refreshing it through HEC-RAS/Ras.exe.
            2. Read per-breakline spacing from .g01 text (preserve existing)
            3. Sync text spacing -> HDF (RegenerateMeshPoints reads HDF)
            4. Load .NET geometry -> perimeter, breaklines
            5. Generate seeds: RegenerateMeshPoints (primary) or GeneratePoints
            6. Fix loop (matches TryAutoFix tier ordering):
               - Tier 0: Remove short perimeter segments (pre-flight)
               - Tier 1: DuplicatePoints -> remove duplicate seed points
               - Tier 2: MaxFaces -> add midpoint seeds (before ratio escalation)
               - Tier 3: Perimeter errors -> remove bad vertices
               - Tier 4: Escalate MinFaceLengthRatio [0.05 -> 0.25]
               - Tier 5: Douglas-Peucker perimeter simplification (last resort)
            7. Extract cell centers via geom.Save() + h5py read
            8. Write cell centers to .g01 text - sole persistent output

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            mesh_name: Name of 2D flow area (None = use mesh_index).
            mesh_index: 0-based index if mesh_name not provided.
            cell_size: Base grid spacing in project units.  When ``None``
                (default), the value is read from geometry text
                ``Storage Area Point Generation Data`` first, then from the
                compiled HDF (``Spacing dx``) only as a fallback.  This avoids
                trusting byte-copied stale HDF metadata after geometry clones.
            bl_spacing: Legacy alias that applies the same positive value to both
                near and far breakline spacing when explicit values are omitted.
            near_repeats: Number of offset seed rows on each side of breaklines.
                None preserves existing values from the .g01 text.
            protection_radius: Enable 1-cell protection radius (0 or 1).
                None preserves existing values from the .g01 text.
            min_face_length_ratio: Initial ratio (0.05-0.25).
            max_iterations: Maximum fix-and-retry attempts.
            hecras_dir: Override HEC-RAS installation directory.
            bl_spacing_near: Optional override for near spacing in project units.
                If omitted, existing per-breakline values in the .g01 text
                are preserved (read from geometry, not defaulted).
            bl_spacing_far: Optional override for far spacing in project units.
                If omitted, existing per-breakline values are preserved.
            ras_object: Optional RasPrj instance for multi-project support.
            recompile_via_rasexe: If True, refresh a missing or content-stale
                compiled geometry HDF through ``GeomPreprocessor``/Ras.exe.
                The geometry must be referenced by a plan in *ras_object*.

        Returns:
            MeshResult with status, cell_count, face_count, fixes_applied, and
            the compiled geometry HDF path on success.
        """
        _load_dlls(hecras_dir)
        ns = _imports()
        geom_path = _resolve_geom_text_path(geom_number, ras_object)

        result = MeshResult(
            mesh_name=mesh_name or f"<index {mesh_index}>",
            status="error",
            geom_text_path=str(geom_path),
        )

        cell_size_provided = cell_size is not None
        if cell_size_provided:
            cell_size = _normalize_positive_value(cell_size, "cell_size")
        legacy_bl_spacing = _normalize_positive_value(
            bl_spacing, "bl_spacing", allow_none=True
        )
        bl_spacing_near = _normalize_positive_value(
            bl_spacing_near, "bl_spacing_near", allow_none=True
        )
        bl_spacing_far = _normalize_positive_value(
            bl_spacing_far, "bl_spacing_far", allow_none=True
        )


        if legacy_bl_spacing is not None:
            if bl_spacing_near is None:
                bl_spacing_near = legacy_bl_spacing
            if bl_spacing_far is None:
                bl_spacing_far = legacy_bl_spacing

        try:
            text_path = geom_path

            # ── Step 1: Validate existing compiled HDF workspace ─────
            # True .g## text -> .g##.hdf generation is a full HEC-RAS/Ras.exe
            # responsibility. This method only works against an existing
            # compiled geometry HDF.
            hdf_path = _ensure_hdf(
                text_path,
                hecras_dir=hecras_dir,
                require_current=_require_current_hdf,
                ras_object=ras_object,
                mesh_name=mesh_name,
                recompile_via_rasexe=recompile_via_rasexe,
            )

            # ── Step 1a: Auto-detect cell size from text if not provided ──
            if not cell_size_provided:
                cell_size = _read_cell_size_from_text(
                    text_path,
                    mesh_name=mesh_name,
                    mesh_index=mesh_index,
                )
                if cell_size is not None:
                    logger.info(
                        f"Auto-detected cell size {cell_size} from geometry text"
                    )
                else:
                    cell_size = _read_cell_size_from_hdf(hdf_path, mesh_name)
                    logger.info(
                        f"Auto-detected cell size {cell_size} from HDF Spacing dx"
                    )

            # Only modify .g01 text breakline properties if explicitly provided.
            # Otherwise the geometry's existing per-breakline values are
            # the source of truth — don't overwrite them with defaults.
            has_spacing = bl_spacing_near is not None or bl_spacing_far is not None
            has_bl_params = has_spacing or near_repeats is not None or protection_radius is not None
            if has_bl_params:
                _set_breakline_spacing_impl(
                    text_path,
                    bl_spacing_near if bl_spacing_near is not None else (cell_size if has_spacing else None),
                    bl_spacing_far if bl_spacing_far is not None else (cell_size if has_spacing else None),
                    near_repeats=near_repeats,
                    protection_radius=protection_radius,
                    all_breaklines=True,
                )

            # ── Step 1b: Sync text → HDF ────────────────────────────────
            # RegenerateMeshPoints reads spacing from the HDF, not from
            # .g01 text. Sync current cell size and per-breakline values from
            # text into the existing HDF workspace.
            _sync_cell_size_to_hdf(hdf_path, cell_size, mesh_name=mesh_name)
            _sync_breakline_spacing_text_to_hdf(text_path, hdf_path)

            # ── Step 2: Load geometry from .NET (same as RASDecomp) ──────
            geom = ns["RASGeometry"](str(hdf_path))
            d2fa = geom.D2FlowArea

            # Resolve mesh name / index
            fid = mesh_index
            if mesh_name is not None:
                resolved_fid = d2fa.GetFeatureByName(mesh_name)
                if resolved_fid >= 0:
                    fid = resolved_fid
                else:
                    logger.debug(
                        f"GetFeatureByName('{mesh_name}') returned -1; "
                        f"using index={mesh_index}"
                    )
            else:
                try:
                    mesh_name = d2fa.GetFeatureName(fid)
                except Exception:
                    mesh_name = f"<index {fid}>"
            result.mesh_name = mesh_name

            # ── Step 3: Perimeter and breaklines from .NET ───────────────
            perim = d2fa.Geometry.MeshPerimeters.Polygon(fid)
            if perim is None or perim.Count == 0:
                result.error_message = "MeshPerimeters.Polygon returned None/empty"
                return result
            logger.info(
                f"[{mesh_name}] {perim.Count}-point perimeter from .NET"
            )

            breaklines = _build_breaklines(d2fa, ns)

            # ── Step 4: Generate seeds via .NET ──────────────────────────
            # Always try RegenerateMeshPoints first — it uses the correct
            # grid origin from the HDF regardless of whether breaklines exist.
            PointGenerator = ns["PointGenerator"]
            net_seeds_ok = False
            try:
                seeds_pm = _generate_seeds_via_net(str(hdf_path), ns, fid=fid)
                net_seeds_ok = True
                logger.info(
                    f"[{mesh_name}] {seeds_pm.Count} seeds via "
                    f".NET RegenerateMeshPoints"
                )
            except Exception as exc:
                logger.warning(
                    f"[{mesh_name}] RegenerateMeshPoints failed: {exc}"
                )

            if not net_seeds_ok:
                seeds_pm = _generate_seeds_safe(perim, cell_size, ns)
                logger.info(
                    f"[{mesh_name}] {seeds_pm.Count} seeds via "
                    f"PointGenerator.GeneratePoints"
                )

            # ── Fix loop setup (same tier structure as RASDecomp) ────────
            ratios = [r for r in _RATIO_LADDER if r >= min_face_length_ratio]
            if not ratios:
                ratios = _RATIO_LADDER[:]

            current_perim = perim
            current_seeds_pm = seeds_pm

            # Tier 0: Pre-simplify short perimeter segments
            pre_n = current_perim.Count
            current_perim = _remove_short_perimeter_segments(
                current_perim, cell_size * min_face_length_ratio, ns
            )
            post_n = current_perim.Count
            if post_n < pre_n:
                fix_msg = f"Tier0:short_seg_removal(-{pre_n - post_n})"
                result.fixes_applied.append(fix_msg)
                logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                current_seeds_pm = _reseed_after_perimeter_fix(
                    text_path, hdf_path, current_perim,
                    cell_size, fid, mesh_name, ns, hecras_dir,
                )

            ratio_idx = 0
            tier4_count = 0
            midpoint_attempts = 0
            MAX_MIDPOINT_ATTEMPTS = 5
            duplicate_tolerances = [
                max(cell_size * 1e-8, 1e-6),
                max(cell_size * 1e-6, 1e-4),
                max(cell_size * 1e-5, 1e-3),
                max(cell_size * 1e-4, 1e-2),
            ]
            duplicate_tolerance_idx = 0
            MeshStatus = ns["MeshStatus"]
            complete_val = int(MeshStatus.Complete)
            max_faces_val = int(MeshStatus.MaxFacesPerCellExceeded)
            face_perim_val = int(MeshStatus.FacePerimeterConnectionError)
            perim_poly_val = int(MeshStatus.PerimeterPolygonError)
            try:
                duplicate_points_val = int(MeshStatus.DuplicatePoints)
            except AttributeError:
                duplicate_points_val = None

            for iteration in range(max_iterations):
                ratio = ratios[min(ratio_idx, len(ratios) - 1)]
                logger.debug(
                    f"[{mesh_name}] Iteration {iteration + 1}: "
                    f"{current_seeds_pm.Count} seeds, ratio={ratio:.2f}"
                )

                mesh = _compute_mesh(
                    current_perim, current_seeds_pm, breaklines, ratio, ns
                )
                state_val = int(mesh.MeshCompletionState)
                state_name = str(mesh.MeshCompletionState)
                result.iterations = iteration + 1

                logger.debug(
                    f"[{mesh_name}] Iteration {iteration + 1} result: "
                    f"{state_name} "
                    f"({_safe_non_virtual_cell_count(mesh) or 'unknown'} cells)"
                )

                if state_val == complete_val:
                    # ── Success: extract cell centers → patch .g01 text ──
                    # The .g01 text is the sole deliverable. HEC-RAS
                    # preprocessing reads "Storage Area 2D Points= N"
                    # and regenerates the mesh from those XY seeds,
                    # overriding any HDF content.
                    #
                    # geom.Save() is used only to bulk-write cell centers
                    # to HDF so we can read them back via h5py (fast).
                    # The HDF is a temporary workspace created by
                    # HEC-RAS/Ras.exe, not a deliverable generated here.

                    import numpy as _np
                    _nv = _safe_non_virtual_cell_count(mesh)
                    if _nv is None:
                        result.status = "error"
                        result.mesh_state = state_name
                        result.error_message = (
                            "Mesh reported Complete but RasMapper did not expose "
                            "NonVirtualCellCount."
                        )
                        return result

                    # Fast path: geom.Save() → h5py bulk read
                    _new_seeds = None
                    try:
                        _save_mesh(geom, d2fa, fid, mesh, ns)
                        import h5py as _h5
                        with _h5.File(str(hdf_path), "r") as _hf:
                            _cc_path = (
                                f"Geometry/2D Flow Areas/{mesh_name}/"
                                f"Cells Center Coordinate"
                            )
                            _new_seeds = _hf[_cc_path][:_nv].astype(
                                _np.float64
                            )
                        logger.debug(
                            f"[{mesh_name}] Read {_nv} cell centers from HDF"
                        )
                    except Exception as _se:
                        logger.warning(
                            f"[{mesh_name}] geom.Save/h5py read failed: "
                            f"{_se}; falling back to .NET cell iteration"
                        )

                    # Slow path: iterate .NET mesh cells directly
                    if _new_seeds is None:
                        _new_seeds = _np.empty((_nv, 2), dtype=_np.float64)
                        for ci in range(_nv):
                            cell = mesh.Cell(ci)
                            _new_seeds[ci, 0] = float(cell.Point.X)
                            _new_seeds[ci, 1] = float(cell.Point.Y)
                        logger.debug(
                            f"[{mesh_name}] Extracted {_nv} cell centers "
                            f"via .NET iteration"
                        )

                    # Write to .g01 text — the only persistent output
                    _set_point_generation_data(text_path, float(cell_size), mesh_name=mesh_name)
                    _patch_text_seeds(text_path, _new_seeds, mesh_name=mesh_name)

                    result.status = "complete"
                    result.mesh_state = state_name
                    result.cell_count = _nv
                    result.face_count = _safe_face_count(mesh) or 0
                    result.geom_hdf_path = str(hdf_path)
                    fixes_str = (
                        f", fixes: {result.fixes_applied}"
                        if result.fixes_applied else ""
                    )
                    logger.info(
                        f"[{mesh_name}] Mesh complete: "
                        f"{_nv} cells, {result.face_count} faces "
                        f"in {iteration + 1} iteration(s){fixes_str}"
                    )
                    return result

                # ── Try specific error fixes FIRST (matches TryAutoFix) ──

                # DuplicatePoints → remove duplicate seed coordinates at current ratio.
                if duplicate_points_val is not None and state_val == duplicate_points_val:
                    bad_indexes = _bad_seed_indexes(mesh, current_seeds_pm.Count)
                    if bad_indexes:
                        current_seeds_pm, n_removed = _remove_seed_indexes(
                            current_seeds_pm,
                            bad_indexes,
                            ns,
                        )
                        if n_removed > 0:
                            fix_msg = (
                                "DuplicatePoints:bad-index-removal"
                                f"(-{n_removed}pts)"
                            )
                            result.fixes_applied.append(fix_msg)
                            logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                            continue

                    n_removed = 0
                    while duplicate_tolerance_idx < len(duplicate_tolerances):
                        tolerance = duplicate_tolerances[duplicate_tolerance_idx]
                        duplicate_tolerance_idx += 1
                        current_seeds_pm, n_removed = _dedupe_seed_points(
                            current_seeds_pm,
                            ns,
                            tolerance=tolerance,
                        )
                        if n_removed > 0:
                            fix_msg = (
                                "DuplicatePoints:dedupe"
                                f"(-{n_removed}pts,tol={tolerance:g})"
                            )
                            result.fixes_applied.append(fix_msg)
                            logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                            break
                    if n_removed > 0:
                        continue
                    result.error_message = (
                        "Mesh reported DuplicatePoints, but no duplicate seed "
                        "coordinates were found within the configured tolerances."
                    )
                    break

                # MaxFaces → add midpoint seeds at current ratio
                if (
                    state_val == max_faces_val
                    and midpoint_attempts < MAX_MIDPOINT_ATTEMPTS
                ):
                    seeds_list = [
                        current_seeds_pm[i]
                        for i in range(current_seeds_pm.Count)
                    ]
                    new_list, n_added, _ = _autofix_max_faces(
                        mesh, seeds_list, ns
                    )
                    if n_added > 0:
                        current_seeds_pm = _seeds_from_pointms_list(
                            new_list, ns
                        )
                        midpoint_attempts += 1
                        fix_msg = f"MaxFaces:midpoints(+{n_added}pts)"
                        result.fixes_applied.append(fix_msg)
                        logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                        continue

                # Perimeter errors → remove bad vertices
                if state_val in (face_perim_val, perim_poly_val):
                    bad_indices = _autofix_perimeter(current_perim, ns)
                    if bad_indices:
                        current_perim = _remove_perimeter_points(
                            current_perim, bad_indices, ns
                        )
                        fix_msg = f"Perim:remove(-{len(bad_indices)}pts)"
                        result.fixes_applied.append(fix_msg)
                        logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                        current_seeds_pm = _reseed_after_perimeter_fix(
                            text_path, hdf_path, current_perim,
                            cell_size, fid, mesh_name, ns, hecras_dir,
                        )
                        continue

                # ── Ratio escalation (when specific fix didn't apply) ────
                if ratio_idx < len(ratios) - 1:
                    old_r = ratios[ratio_idx]
                    ratio_idx += 1
                    fix_msg = f"Ratio:{old_r:.2f}->{ratios[ratio_idx]:.2f}"
                    result.fixes_applied.append(fix_msg)
                    logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                    continue

                # ── Douglas-Peucker (last resort) ────────────────────────
                cs = cell_size or 200.0
                tol = cs * min(0.10 * (tier4_count + 1), 0.50)
                buf_mult = 3.0 + float(tier4_count)
                tier4_count += 1
                try:
                    error_pts = _find_error_locations(mesh, cs, ratio)
                    if error_pts:
                        current_perim = _localized_douglas_peucker(
                            current_perim, error_pts, cs, tol, ns, buf_mult
                        )
                        fix_msg = f"DP:local({len(error_pts)}zones)"
                        result.fixes_applied.append(fix_msg)
                        logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                    else:
                        current_perim = _douglas_peucker_polygon(
                            current_perim, tol, ns
                        )
                        fix_msg = f"DP:global(tol={tol:.1f})"
                        result.fixes_applied.append(fix_msg)
                        logger.info(f"[{mesh_name}] Fix applied: {fix_msg}")
                    current_seeds_pm = _reseed_after_perimeter_fix(
                        text_path, hdf_path, current_perim,
                        cell_size, fid, mesh_name, ns, hecras_dir,
                    )
                except Exception as exc:
                    result.error_message = f"Douglas-Peucker failed: {exc}"
                    break
            else:
                result.error_message = (
                    f"Max iterations ({max_iterations}) reached"
                )

            result.status = "error"
            result.mesh_state = state_name
            return result

        except Exception as exc:
            result.status = "exception"
            result.error_message = str(exc)
            logger.error(f"[{result.mesh_name}] Exception: {exc}")
            return result

    @staticmethod
    @log_call
    def generate_all(
        geom_number: Union[str, Number, Path],
        cell_size: Optional[float] = None,
        bl_spacing: Optional[float] = None,
        bl_spacing_near: Optional[float] = None,
        bl_spacing_far: Optional[float] = None,
        near_repeats: Optional[int] = None,
        protection_radius: Optional[int] = None,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object: Optional['RasPrj'] = None,
        recompile_via_rasexe: bool = False,
    ) -> List[MeshResult]:
        """Generate/repair all 2D mesh areas in a geometry file.

        Discovers every 2D flow area in the geometry and calls
        ``generate()`` for each one.

        Args:
            geom_number: Geometry number (e.g. ``"01"`` or ``1``),
                or a direct path to a ``.g##`` text file.
            cell_size: Default mesh cell size.  When ``None`` (default),
                each mesh area reads its spacing from geometry text first,
                then from the compiled HDF as a fallback.
            bl_spacing: Shorthand — sets both near and far breakline spacing.
            bl_spacing_near: Breakline near-spacing override.
            bl_spacing_far: Breakline far-spacing override.
            near_repeats: Number of offset seed rows along breaklines.
            protection_radius: Enable 1-cell protection radius (0 or 1).
            min_face_length_ratio: Minimum face-length ratio for mesh quality.
            max_iterations: Maximum fix-loop iterations per mesh area.
            hecras_dir: Override path to the HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for multi-project support.
            recompile_via_rasexe: If True, refresh a missing or content-stale
                compiled geometry HDF through ``GeomPreprocessor``/Ras.exe.

        Returns:
            List of MeshResult, one per 2D flow area.
        """
        text_path = _resolve_geom_text_path(geom_number, ras_object=ras_object)
        _load_dlls(hecras_dir)
        ns = _imports()
        hdf_path = _ensure_hdf(
            text_path,
            hecras_dir=hecras_dir,
            require_current=True,
            ras_object=ras_object,
            recompile_via_rasexe=recompile_via_rasexe,
        )
        geom = ns["RASGeometry"](str(hdf_path))
        d2fa = geom.D2FlowArea
        count = d2fa.FeatureCount()
        results = []
        for i in range(count):
            name = d2fa.GetFeatureName(i)
            r = GeomMesh.generate(
                geom_number=text_path,
                mesh_name=name,
                cell_size=cell_size,
                bl_spacing=bl_spacing,
                bl_spacing_near=bl_spacing_near,
                bl_spacing_far=bl_spacing_far,
                near_repeats=near_repeats,
                protection_radius=protection_radius,
                min_face_length_ratio=min_face_length_ratio,
                max_iterations=max_iterations,
                hecras_dir=hecras_dir,
                ras_object=ras_object,
                recompile_via_rasexe=recompile_via_rasexe,
                _require_current_hdf=False,
            )
            results.append(r)
        return results

    @staticmethod
    @log_call
    def detect_bc_conflicts(
        geom_hdf_path: Union[str, Path],
        cell_size: float,
    ) -> List[BCConflict]:
        """
        Detect perimeter faces covered by 2+ BC lines.

        Args:
            geom_hdf_path: Path to compiled .g##.hdf file.
            cell_size: Mesh cell size for intersection buffer scaling.

        Returns:
            List of BCConflict (one per conflicting face).
        """
        import h5py
        from shapely.geometry import LineString as ShapelyLine

        conflicts = []
        buf = 0.01 * cell_size

        with h5py.File(str(geom_hdf_path), "r") as hf:
            for area_group in _iter_bc_flow_area_groups(hf):
                flow_area_name = area_group.name.rsplit("/", 1)[-1]
                bcs = _read_bc_features(area_group, ShapelyLine)
                if not bcs:
                    continue

                for face_id, face_line in _read_bc_face_segments(area_group, ShapelyLine):
                    hitting = []
                    hitting_types = []
                    for bc in bcs:
                        if bc["geom"] is not None and face_line.distance(bc["geom"]) < buf:
                            hitting.append(bc["name"])
                            hitting_types.append(bc["type"])

                    if len(hitting) >= 2:
                        nd_bc = next(
                            (n for n, t in zip(hitting, hitting_types)
                             if "normal" in t.lower()),
                            None,
                        )
                        conflicts.append(BCConflict(
                            face_id=face_id,
                            flow_area_name=flow_area_name,
                            bc_names=hitting,
                            bc_types=hitting_types,
                            normal_depth_bc=nd_bc,
                        ))

        return conflicts

    @staticmethod
    @log_call
    def fix_bc_conflicts(
        geom_hdf_path: Union[str, Path],
        cell_size: float,
        dry_run: bool = False,
    ) -> BCFixResult:
        """
        Detect and fix BC conflicts by trimming overlapping BC endpoints.

        Prefers trimming Normal Depth BCs (least sensitive to endpoint placement).
        Falls back to trimming the longer BC when no Normal Depth BC is involved.

        Trim is vertex-by-vertex from the endpoint nearest the conflicting face,
        stopping once the BC no longer intersects that face. If vertex-walking
        exhausts all vertices, interpolates a new endpoint.

        Args:
            geom_hdf_path: Path to compiled .g##.hdf file.
            cell_size: Mesh cell size for buffer scaling.
            dry_run: If True, detect only — do not modify HDF.

        Returns:
            BCFixResult with conflicts_found, conflicts_fixed, unresolvable.
        """
        import h5py
        from math import hypot
        from shapely.geometry import LineString as ShapelyLine, Point as ShapelyPoint

        import numpy as np

        cell_size = _normalize_positive_value(cell_size, "cell_size")
        geom_hdf_path = str(geom_hdf_path)
        area_results = []
        with h5py.File(geom_hdf_path, "r") as hf:
            for area_group in _iter_bc_flow_area_groups(hf):
                bcs = _read_bc_features(area_group, ShapelyLine)
                if not bcs:
                    continue
                face_segments = _read_bc_face_segments(area_group, ShapelyLine)
                if not face_segments:
                    continue
                area_results.append(
                    {
                        "flow_area_name": area_group.name.rsplit("/", 1)[-1],
                        "area_group_path": area_group.name,
                        "bcs": bcs,
                        "face_segments": face_segments,
                    }
                )

        if not area_results:
            return BCFixResult()

        buf = max(0.1, cell_size * 0.01)
        result = BCFixResult()
        for area_result in area_results:
            conflicts = []
            for fid, face_geom in area_result["face_segments"]:
                face_buf = face_geom.buffer(buf)
                hitting = [
                    (b["name"], b["type"])
                    for b in area_result["bcs"]
                    if b["geom"] is not None and face_buf.intersects(b["geom"])
                ]
                if len(hitting) >= 2:
                    nd_bc = next((n for n, t in hitting if "normal" in t.lower()), None)
                    conflicts.append(BCConflict(
                        face_id=fid,
                        flow_area_name=area_result["flow_area_name"],
                        bc_names=[n for n, _ in hitting],
                        bc_types=[t for _, t in hitting],
                        normal_depth_bc=nd_bc,
                    ))
            area_result["conflicts"] = conflicts
            result.conflicts_found += len(conflicts)

        if result.conflicts_found == 0 or dry_run:
            if dry_run:
                for area_result in area_results:
                    result.unresolvable.extend(area_result["conflicts"])
            return result

        for area_result in area_results:
            conflicts = area_result["conflicts"]
            if not conflicts:
                continue

            bc_coords = {
                b["name"]: list(b["geom"].coords) if b["geom"] else []
                for b in area_result["bcs"]
            }
            face_mids = {
                fid: ((g.coords[0][0] + g.coords[1][0]) / 2,
                      (g.coords[0][1] + g.coords[1][1]) / 2)
                for fid, g in area_result["face_segments"]
            }
            face_geoms = {fid: g for fid, g in area_result["face_segments"]}

            for conflict in conflicts:
                if conflict.normal_depth_bc is not None:
                    trim_name = conflict.normal_depth_bc
                else:
                    lengths = {}
                    for name in conflict.bc_names:
                        c = bc_coords.get(name, [])
                        if len(c) >= 2:
                            lengths[name] = ShapelyLine(c).length
                    if not lengths:
                        result.unresolvable.append(conflict)
                        continue
                    trim_name = max(lengths, key=lengths.get)

                coords = bc_coords.get(trim_name, [])
                if len(coords) < 2:
                    result.unresolvable.append(conflict)
                    continue

                face_geom = face_geoms[conflict.face_id]
                face_mid = face_mids[conflict.face_id]

                start_dist = hypot(coords[0][0] - face_mid[0], coords[0][1] - face_mid[1])
                end_dist = hypot(coords[-1][0] - face_mid[0], coords[-1][1] - face_mid[1])
                trim_from_start = start_dist <= end_dist

                trimmed = list(coords)
                trimmed_count = 0
                while len(trimmed) >= 2:
                    if face_geom.buffer(buf).intersects(ShapelyLine(trimmed)):
                        trimmed = trimmed[1:] if trim_from_start else trimmed[:-1]
                        trimmed_count += 1
                        continue
                    ep = trimmed[0] if trim_from_start else trimmed[-1]
                    ep_to_conflict = hypot(ep[0] - face_mid[0], ep[1] - face_mid[1])
                    nearest_other = min(
                        (hypot(ep[0] - mid[0], ep[1] - mid[1])
                         for fid, mid in face_mids.items() if fid != conflict.face_id),
                        default=float("inf"),
                    )
                    if ep_to_conflict <= nearest_other:
                        trimmed = trimmed[1:] if trim_from_start else trimmed[:-1]
                        trimmed_count += 1
                        continue
                    break

                if len(trimmed) < 2:
                    line_geom = ShapelyLine(coords)
                    face_mid_pt = ShapelyPoint(*face_mid)
                    proj = line_geom.project(face_mid_pt)
                    pullback = face_geom.length + buf * 2
                    if trim_from_start:
                        new_dist = proj + pullback
                        if new_dist >= line_geom.length:
                            result.unresolvable.append(conflict)
                            continue
                        new_pt = line_geom.interpolate(new_dist)
                        remaining = [c for c in coords
                                     if line_geom.project(ShapelyPoint(*c)) >= new_dist]
                        trimmed = [(new_pt.x, new_pt.y)] + remaining
                    else:
                        new_dist = proj - pullback
                        if new_dist <= 0:
                            result.unresolvable.append(conflict)
                            continue
                        new_pt = line_geom.interpolate(new_dist)
                        remaining = [c for c in coords
                                     if line_geom.project(ShapelyPoint(*c)) <= new_dist]
                        trimmed = remaining + [(new_pt.x, new_pt.y)]
                    if len(trimmed) < 2 or face_geom.buffer(buf).intersects(ShapelyLine(trimmed)):
                        result.unresolvable.append(conflict)
                        continue

                trimmed_line = ShapelyLine(trimmed)
                covers_other = any(
                    fid != conflict.face_id and g.buffer(buf).intersects(trimmed_line)
                    for fid, g in face_geoms.items()
                )
                if not covers_other:
                    result.unresolvable.append(conflict)
                    continue

                bc_coords[trim_name] = trimmed
                direction = "start" if trim_from_start else "end"
                result.trims.append(
                    (
                        f"{area_result['flow_area_name']}/{trim_name}",
                        f"trimmed {trimmed_count} pts from {direction}",
                    )
                )
                result.conflicts_fixed += 1

            area_result["bc_coords"] = bc_coords

        if result.conflicts_fixed == 0:
            return result

        with h5py.File(geom_hdf_path, "r+") as hf:
            for area_result in area_results:
                if "bc_coords" not in area_result:
                    continue
                for b in area_result["bcs"]:
                    bc_feature_path = f"{area_result['area_group_path']}/BC Lines/{b['name']}"
                    if bc_feature_path not in hf:
                        continue
                    bc_feature = hf[bc_feature_path]
                    if "Coordinates" in bc_feature:
                        del bc_feature["Coordinates"]
                    bc_feature.create_dataset(
                        "Coordinates",
                        data=np.array(area_result["bc_coords"].get(b["name"], []), dtype=np.float64),
                    )

        result.modified_hdf = True
        logger.info(
            f"BC conflicts fixed: {result.conflicts_fixed}/{result.conflicts_found} "
            f"(trims: {result.trims})"
        )
        return result
