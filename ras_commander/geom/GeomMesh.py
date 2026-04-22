"""
GeomMesh - Headless 2D mesh generation, repair, and BC conflict resolution.

Provides headless (no-GUI) mesh generation via RasMapperLib.dll + pythonnet.
Replaces the need for RAS Mapper or RasProcess.exe for mesh operations.

Architecture: Text-First
~~~~~~~~~~~~~~~~~~~~~~~~~
The .g## plain text file is the sole persistent output and source of truth.
HEC-RAS preprocessing reads "Storage Area 2D Points= N" plus the XY seed
coordinates from text and regenerates the mesh — overriding any HDF content.

The HDF (.g##.hdf) is used only as a *temporary workspace*:
  - .NET RASGeometry loads geometry from HDF (perimeter, breaklines)
  - geom.Save() writes cell centers to HDF so we can bulk-read via h5py
  - The HDF is NEVER the deliverable — HEC-RAS will recompile it from text

Production Workflow (generate)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Breakline spacing** — Read per-breakline CellSize Min/Max from .g01 text.
   Only overwrite if the caller explicitly passes bl_spacing_near/bl_spacing_far.
2. **Text → HDF sync** — Sync per-breakline spacing from text into the HDF so
   RegenerateMeshPoints (which reads HDF, not text) uses correct values.
3. **Load .NET geometry** — RASGeometry(hdf_path) → D2FlowArea → perimeter,
   breaklines (merged BreakLines + Regions + Structures via _build_breaklines).
4. **Generate seeds** — Primary: RegenerateMeshPoints (private .NET method via
   reflection) produces breakline-aware seeds. Fallback: PointGenerator.
   GeneratePoints(perim, cell_size) for base-grid seeds.
5. **Fix loop** (matches TryAutoFix tier ordering):
   - Tier 0: Pre-flight removal of short perimeter segments
   - Tier 2 first: MaxFacesPerCellExceeded → add midpoint seeds
   - Tier 3: FacePerimeterConnectionError → remove bad perimeter vertices
   - Tier 1: Ratio escalation [0.05 → 0.10 → 0.15 → 0.25]
   - Tier 4: Douglas-Peucker perimeter simplification (last resort)
6. **Extract cell centers** — geom.Save() + h5py read (fast), or .NET Cell(i)
   iteration (slow fallback).
7. **Write .g01 text** — _patch_text_seeds() writes cell centers as the sole
   persistent output. _set_point_generation_data() updates the seed count header.

Requires:
    - Windows (HEC-RAS / RasMapperLib is Windows-only)
    - pythonnet >= 3.0.5: pip install pythonnet
    - HEC-RAS 6.6 installed (provides RasMapperLib.dll + GDAL)
    - GDAL junction: call GeomMesh.setup_gdal_bridge() once per environment

All methods are static — no instantiation needed.

Ported from G:\\GH\\RASDecomp\\headless_mesh\\mesh_fix.py and mesh_bc_fix.py.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from numbers import Number
from pathlib import Path
from typing import List, Optional, Tuple, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .GeomMeshDataclasses import BCConflict, BCFixResult, MeshResult

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_HECRAS_SEARCH_PATHS = [
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5"),
    Path(r"C:\Program Files\HEC\HEC-RAS\6.6"),
]

_DEPS = ["Utility.Core", "Geospatial.Core", "H5Assist", "RasMapperLib"]

MAX_FACES_PER_CELL = 8
PERIMETER_NEAR_DUPLICATE_TOL = 1e-6
_RATIO_LADDER = [0.05, 0.10, 0.15, 0.25]

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

    GeomMesh.setup_gdal_bridge(hecras_dir=hecras_dir)


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
    Requires a compiled .g##.hdf file (RASGeometry needs HDF to populate
    D2FlowArea layers).

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
    pg = ns["PointGenerator"](geom)
    d2fa = geom.D2FlowArea

    bl_count = geom.BreakLines.FeatureCount() if geom.BreakLines else 0
    perim_count = d2fa.FeatureCount()

    bl_idx = NetList[System.Int32]()
    for i in range(bl_count):
        bl_idx.Add(i)
    perim_idx = NetList[System.Int32]()
    for i in range(perim_count):
        perim_idx.Add(i)
    region_idx = NetList[System.Int32]()

    pg_type = pg.GetType()
    method = pg_type.GetMethod(
        "RegenerateMeshPoints",
        BindingFlags.Instance | BindingFlags.NonPublic,
    )
    if method is None:
        raise RuntimeError("Cannot find private RegenerateMeshPoints on PointGenerator")

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
        f"({bl_count} breaklines, {perim_count} perimeters)"
    )
    return seeds_pm


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
    geom_text_path: Path, near: Optional[float], far: Optional[float]
) -> Path:
    """Edit BreakLine CellSize Min/Max in .g## text file."""
    near = _normalize_positive_value(near, "near", allow_none=True)
    far = _normalize_positive_value(far, "far", allow_none=True)
    lines = geom_text_path.read_text(encoding="utf-8", errors="replace").splitlines(
        keepends=True
    )
    modified = []
    for line in lines:
        if line.startswith("BreakLine CellSize Min="):
            line = (
                f"BreakLine CellSize Min={near:.6f}\n"
                if near else "BreakLine CellSize Min=\n"
            )
        elif line.startswith("BreakLine CellSize Max="):
            line = (
                f"BreakLine CellSize Max={far:.6f}\n"
                if far else "BreakLine CellSize Max=\n"
            )
        modified.append(line)

    backup = geom_text_path.with_suffix(geom_text_path.suffix + ".bak")
    shutil.copy2(geom_text_path, backup)
    tmp = geom_text_path.with_suffix(geom_text_path.suffix + ".tmp")
    tmp.write_text("".join(modified), encoding="utf-8")
    tmp.replace(geom_text_path)
    logger.info(f"Breakline spacing: near={near}, far={far} → {geom_text_path.name}")
    return backup


def _read_breakline_spacing_from_text(
    geom_text_path: Path,
) -> list[tuple[str, float, float]]:
    """Read per-breakline CellSize Min/Max from .g## text file.

    Returns list of (name, near, far) tuples in file order.
    """
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    result = []
    current_name = ""
    near_val = 0.0
    far_val = 0.0
    for line in lines:
        if line.startswith("BreakLine Name="):
            if current_name:
                result.append((current_name, near_val, far_val))
            current_name = line.split("=", 1)[1].strip()
            near_val = 0.0
            far_val = 0.0
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
    if current_name:
        result.append((current_name, near_val, far_val))
    return result


def _sync_breakline_spacing_text_to_hdf(
    text_path: Path, hdf_path: Path
) -> None:
    """Sync breakline spacing from .g01 text (source of truth) into HDF.

    RegenerateMeshPoints reads spacing from the HDF, not from text.
    When the HDF is pre-compiled or stale, its spacing may differ.
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
            hdf_names = [n.decode("utf-8", errors="replace").strip()
                         for n in data["Name"]]
            text_map = {name.strip(): (near, far)
                        for name, near, far in bl_spacings}
            for i, hdf_name in enumerate(hdf_names):
                if hdf_name in text_map:
                    t_near, t_far = text_map[hdf_name]
                    if abs(float(data["Cell Spacing Near"][i]) - t_near) > 0.001:
                        data["Cell Spacing Near"][i] = t_near
                        changed = True
                    if abs(float(data["Cell Spacing Far"][i]) - t_far) > 0.001:
                        data["Cell Spacing Far"][i] = t_far
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


class GeomMesh:
    """
    Headless 2D mesh generation, repair, and BC conflict resolution.

    Uses RasMapperLib.dll via pythonnet to generate finite volume meshes
    without the RAS Mapper GUI. Includes a 5-tier auto-fix pipeline that
    mirrors TryAutoFix behavior from the GUI.

    All methods are static — no instantiation needed.

    Example:
        >>> from ras_commander.geom import GeomMesh
        >>> GeomMesh.setup_gdal_bridge()  # once per environment
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
    ) -> bool:
        """
        Create GDAL directory junction for RasMapperLib.

        RasMapperLib requires a GDAL/ folder next to the Python executable.
        This creates a junction from {python_dir}/GDAL → HEC-RAS GDAL.
        Only needs to be called once per Python environment.

        Returns True if junction exists or was created successfully.
        """
        if platform.system() != "Windows":
            logger.warning("setup_gdal_bridge() is Windows-only")
            return False

        if python_dir is None:
            python_dir = Path(sys.executable).parent
        else:
            python_dir = Path(python_dir)

        gdal_junc = python_dir / "GDAL"

        if gdal_junc.exists() and (gdal_junc / "bin64").exists():
            return True

        if hecras_dir is None:
            hecras_dir = _find_hecras_dir()
        gdal_src = Path(hecras_dir) / "GDAL"

        if not gdal_src.exists():
            logger.error(f"GDAL not found in HEC-RAS: {gdal_src}")
            return False

        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f'New-Item -ItemType Junction -Path "{gdal_junc}" '
                 f'-Target "{gdal_src}" -Force'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                logger.info(f"Created GDAL junction: {gdal_junc} -> {gdal_src}")
                return True
            logger.error(f"Junction creation failed: {result.stderr.strip()}")
            return False
        except Exception as exc:
            logger.error(f"setup_gdal_bridge error: {exc}")
            return False

    @staticmethod
    @log_call
    def set_breakline_spacing(
        geom_number: Union[str, Number, Path],
        near: Optional[float] = None,
        far: Optional[float] = None,
        ras_object=None,
    ) -> Path:
        """
        Edit BreakLine CellSize Min/Max in a .g## text file.

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            near: BreakLine near-spacing in project units. None clears field.
            far: BreakLine far-spacing in project units. None clears field.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            Path to .bak backup file created before writing.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)
        return _set_breakline_spacing_impl(geom_text_path, near, far)

    @staticmethod
    @log_call
    def compile_geometry(
        geom_number: Union[str, Number, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> Path:
        """
        Compile a .g## text file into .g##.hdf without Ras.exe.

        Uses RasMapperLib's CompleteGeometryCommand to convert the plain-text
        geometry file into its compiled HDF representation, bypassing Ras.exe.

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            hecras_dir: Override HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            Path to the compiled .g##.hdf file.

        Raises:
            FileNotFoundError: If geometry file cannot be resolved.
            RuntimeError: If compilation fails.
        """
        geom_text_path = _resolve_geom_text_path(geom_number, ras_object)

        _load_dlls(hecras_dir)

        from RasMapperLib.Scripting import CompleteGeometryCommand  # type: ignore

        cmd = CompleteGeometryCommand()
        cmd.GeometryFilename = str(geom_text_path)

        try:
            cmd.ExecuteOutOfProcess(True)
        except Exception as exc:
            raise RuntimeError(
                f"CompleteGeometryCommand failed for {geom_text_path.name}: {exc}"
            ) from exc

        hdf_path = geom_text_path.with_suffix(geom_text_path.suffix + ".hdf")
        if not hdf_path.exists():
            raise RuntimeError(
                f"CompleteGeometryCommand did not produce {hdf_path.name}"
            )
        logger.info(f"Compiled geometry: {geom_text_path.name} -> {hdf_path.name}")
        return hdf_path

    @staticmethod
    @log_call
    def generate(
        geom_number: Union[str, Number, Path],
        mesh_name: Optional[str] = None,
        mesh_index: int = 0,
        cell_size: float = 100.0,
        bl_spacing: Optional[float] = None,
        near_repeats: int = 1,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[Union[str, Path]] = None,
        bl_spacing_near: Optional[float] = None,
        bl_spacing_far: Optional[float] = None,
        ras_object=None,
    ) -> MeshResult:
        """
        Generate or regenerate a 2D mesh headlessly via text-first workflow.

        The .g01 text file is the sole persistent output. The HDF is used only
        as a temporary workspace for .NET geometry loading and cell center
        extraction. HEC-RAS will recompile the HDF from text on project open.

        Workflow:
            1. Read per-breakline spacing from .g01 text (preserve existing)
            2. Sync text spacing → HDF (RegenerateMeshPoints reads HDF)
            3. Load .NET geometry → perimeter, breaklines
            4. Generate seeds: RegenerateMeshPoints (primary) or GeneratePoints
            5. Fix loop (matches TryAutoFix tier ordering):
               - Tier 0: Remove short perimeter segments (pre-flight)
               - Tier 2: MaxFaces → add midpoint seeds (before ratio escalation)
               - Tier 3: Perimeter errors → remove bad vertices
               - Tier 1: Escalate MinFaceLengthRatio [0.05 → 0.25]
               - Tier 4: Douglas-Peucker perimeter simplification (last resort)
            6. Extract cell centers via geom.Save() + h5py read
            7. Write cell centers to .g01 text — sole persistent output

        Args:
            geom_number: Geometry number ("01", 1) or path to .g## text file.
            mesh_name: Name of 2D flow area (None = use mesh_index).
            mesh_index: 0-based index if mesh_name not provided.
            cell_size: Base grid spacing in project units. Defaults to 100.0.
            bl_spacing: Legacy alias that applies the same positive value to both
                near and far breakline spacing when explicit values are omitted.
            near_repeats: Number of offset seed rows on each side of breaklines.
                Must be >= 1. Defaults to 1.
            min_face_length_ratio: Initial ratio (0.05-0.25).
            max_iterations: Maximum fix-and-retry attempts.
            hecras_dir: Override HEC-RAS installation directory.
            bl_spacing_near: Optional override for near spacing in project units.
                If omitted, existing per-breakline values in the .g01 text
                are preserved (read from geometry, not defaulted).
            bl_spacing_far: Optional override for far spacing in project units.
                If omitted, existing per-breakline values are preserved.
            ras_object: Optional RasPrj instance for multi-project support.

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
        if near_repeats < 1:
            raise ValueError("near_repeats must be at least 1")

        if legacy_bl_spacing is not None:
            if bl_spacing_near is None:
                bl_spacing_near = legacy_bl_spacing
            if bl_spacing_far is None:
                bl_spacing_far = legacy_bl_spacing

        try:
            text_path = geom_path

            # Only modify .g01 text breakline spacing if explicitly provided.
            # Otherwise the geometry's existing per-breakline values are
            # the source of truth — don't overwrite them with defaults.
            if bl_spacing_near is not None or bl_spacing_far is not None:
                _set_breakline_spacing_impl(
                    text_path,
                    bl_spacing_near if bl_spacing_near is not None else cell_size,
                    bl_spacing_far if bl_spacing_far is not None else cell_size,
                )

            # ── Step 1: Compile .g01 text → HDF if needed ────────────────
            hdf_path = text_path.with_suffix(text_path.suffix + ".hdf")
            if not hdf_path.exists():
                logger.info(f"Compiling {text_path.name} → HDF for .NET loading")
                hdf_path = GeomMesh.compile_geometry(text_path, hecras_dir=hecras_dir)

            # ── Step 1b: Sync text → HDF ────────────────────────────────
            # RegenerateMeshPoints reads spacing from the HDF, not from
            # .g01 text.  The HDF may be pre-compiled or stale, so sync
            # cell size and per-breakline values from text into HDF.
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
            PointGenerator = ns["PointGenerator"]
            net_seeds_ok = False
            if breaklines is not None:
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
                current_seeds_pm = _generate_seeds_safe(
                    current_perim, cell_size, ns
                )

            ratio_idx = 0
            tier4_count = 0
            midpoint_attempts = 0
            MAX_MIDPOINT_ATTEMPTS = 5
            MeshStatus = ns["MeshStatus"]
            complete_val = int(MeshStatus.Complete)
            max_faces_val = int(MeshStatus.MaxFacesPerCellExceeded)
            face_perim_val = int(MeshStatus.FacePerimeterConnectionError)
            perim_poly_val = int(MeshStatus.PerimeterPolygonError)

            for iteration in range(max_iterations):
                ratio = ratios[min(ratio_idx, len(ratios) - 1)]
                logger.info(
                    f"[{mesh_name}] Iteration {iteration + 1}: "
                    f"{current_seeds_pm.Count} seeds, ratio={ratio:.2f}"
                )

                mesh = _compute_mesh(
                    current_perim, current_seeds_pm, breaklines, ratio, ns
                )
                state_val = int(mesh.MeshCompletionState)
                state_name = str(mesh.MeshCompletionState)
                result.iterations = iteration + 1

                logger.info(
                    f"[{mesh_name}] Iteration {iteration + 1} result: "
                    f"{state_name} ({mesh.NonVirtualCellCount} cells)"
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
                    # The HDF is NOT patched further — it's a temporary
                    # workspace that HEC-RAS will recompile from text.

                    import numpy as _np
                    _nv = mesh.NonVirtualCellCount

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
                        logger.info(
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
                        logger.info(
                            f"[{mesh_name}] Extracted {_nv} cell centers "
                            f"via .NET iteration"
                        )

                    # Write to .g01 text — the only persistent output
                    _set_point_generation_data(text_path, float(cell_size), mesh_name=mesh_name)
                    _patch_text_seeds(text_path, _new_seeds, mesh_name=mesh_name)

                    result.status = "complete"
                    result.mesh_state = state_name
                    result.cell_count = _nv
                    result.face_count = mesh.FaceCount
                    result.geom_hdf_path = str(hdf_path)
                    fixes_str = (
                        f", fixes: {result.fixes_applied}"
                        if result.fixes_applied else ""
                    )
                    logger.info(
                        f"[{mesh_name}] Mesh complete: "
                        f"{_nv} cells, {mesh.FaceCount} faces "
                        f"in {iteration + 1} iteration(s){fixes_str}"
                    )
                    return result

                # ── Try specific error fixes FIRST (matches TryAutoFix) ──

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
                        current_seeds_pm = _generate_seeds_safe(
                            current_perim, cell_size, ns
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
                    current_seeds_pm = _generate_seeds_safe(
                        current_perim, cell_size, ns
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
        cell_size: float = 100.0,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object: Optional['RasPrj'] = None,
    ) -> List[MeshResult]:
        """Generate/repair all 2D mesh areas in a geometry file.

        Discovers every 2D flow area in the geometry and calls
        ``generate()`` for each one.

        Args:
            geom_number: Geometry number (e.g. ``"01"`` or ``1``),
                or a direct path to a ``.g##`` text file.
            cell_size: Default mesh cell size (metres).
            min_face_length_ratio: Minimum face-length ratio for mesh quality.
            max_iterations: Maximum fix-loop iterations per mesh area.
            hecras_dir: Override path to the HEC-RAS installation directory.
            ras_object: Optional RasPrj instance for multi-project support.

        Returns:
            List of MeshResult, one per 2D flow area.
        """
        text_path = _resolve_geom_text_path(geom_number, ras_object=ras_object)
        _load_dlls(hecras_dir)
        ns = _imports()
        hdf_path = text_path.with_suffix(text_path.suffix + ".hdf")
        if not hdf_path.exists():
            hdf_path = GeomMesh.compile_geometry(text_path, hecras_dir=hecras_dir)
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
                min_face_length_ratio=min_face_length_ratio,
                max_iterations=max_iterations,
                hecras_dir=hecras_dir,
                ras_object=ras_object,
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
            fa_group = None
            for key in hf["Geometry/2D Flow Areas"].keys():
                if "Face" in str(hf[f"Geometry/2D Flow Areas/{key}"].keys()):
                    fa_group = f"Geometry/2D Flow Areas/{key}"
                    break
            if fa_group is None:
                return conflicts

            # Read BC line geometries
            bc_group = f"{fa_group}/BC Lines"
            if bc_group not in hf:
                return conflicts

            bc_names = []
            bc_lines = []
            bc_types = []
            for bc_name in hf[bc_group].keys():
                coords = hf[f"{bc_group}/{bc_name}/Coordinates"][:]
                line = ShapelyLine(coords)
                bc_names.append(bc_name)
                bc_lines.append(line)
                bc_type_raw = hf[f"{bc_group}/{bc_name}"].attrs.get("Type", "")
                bc_type = bc_type_raw.decode() if isinstance(bc_type_raw, bytes) else str(bc_type_raw)
                bc_types.append(bc_type)

            # Read perimeter faces
            face_coords = hf[f"{fa_group}/FacePoints Coordinate"][:]
            face_fp_idx = hf[f"{fa_group}/Faces FacePoint Indexes"][:]
            perim_info = hf[f"{fa_group}/Faces Perimeter Info"][:]

            for face_id in range(len(face_fp_idx)):
                row = perim_info[face_id]
                if hasattr(row, '__len__'):
                    if int(row[0]) == 0 and int(row[1]) == 0:
                        continue
                elif not row:
                    continue
                fp_a, fp_b = int(face_fp_idx[face_id][0]), int(face_fp_idx[face_id][1])
                a = face_coords[fp_a]
                b = face_coords[fp_b]
                face_line = ShapelyLine([a, b])

                hitting = []
                hitting_types = []
                for i, bc_line in enumerate(bc_lines):
                    if face_line.distance(bc_line) < buf:
                        hitting.append(bc_names[i])
                        hitting_types.append(bc_types[i])

                if len(hitting) >= 2:
                    nd_bc = next(
                        (n for n, t in zip(hitting, hitting_types)
                         if "normal" in t.lower()),
                        None,
                    )
                    conflicts.append(BCConflict(
                        face_id=face_id,
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
        area_group_path = None

        # Read the first 7.0-style 2D flow area that has both faces and BC lines.
        bcs = []
        with h5py.File(geom_hdf_path, "r") as hf:
            if "Geometry/2D Flow Areas" not in hf:
                return BCFixResult()

            fa_root = hf["Geometry/2D Flow Areas"]
            area_group = None
            for key in fa_root.keys():
                candidate = fa_root[key]
                if not isinstance(candidate, h5py.Group):
                    continue
                if (
                    "BC Lines" in candidate
                    and "FacePoints Coordinate" in candidate
                    and "Faces FacePoint Indexes" in candidate
                    and "Faces Perimeter Info" in candidate
                ):
                    area_group = candidate
                    area_group_path = candidate.name
                    break

            if area_group is None:
                return BCFixResult()

            bc_group = area_group["BC Lines"]
            for bc_name in bc_group.keys():
                bc_feature = bc_group[bc_name]
                if not isinstance(bc_feature, h5py.Group) or "Coordinates" not in bc_feature:
                    continue
                coords = bc_feature["Coordinates"][:]
                bc_type_raw = bc_feature.attrs.get("Type", "")
                if isinstance(bc_type_raw, (bytes, np.bytes_)):
                    bc_type = bc_type_raw.decode("utf-8", errors="replace").strip(
                        "\x00"
                    ).strip()
                else:
                    bc_type = str(bc_type_raw)
                geom = ShapelyLine(coords[:, :2]) if len(coords) >= 2 else None
                bcs.append(
                    {
                        "name": bc_name,
                        "type": bc_type,
                        "geom": geom,
                    }
                )

        if not bcs:
            return BCFixResult()

        # Read perimeter face geometry from the mesh area group
        face_segments: List[tuple] = []  # (face_id, ShapelyLine)
        with h5py.File(geom_hdf_path, "r") as hf:
            if area_group_path is None:
                return BCFixResult()

            area_group = hf[area_group_path]
            fp_coords = area_group["FacePoints Coordinate"][:]
            face_fp_idx = area_group["Faces FacePoint Indexes"][:]
            perim_info = area_group["Faces Perimeter Info"][:]

            for fid in range(len(face_fp_idx)):
                if int(perim_info[fid][0]) == 0 and int(perim_info[fid][1]) == 0:
                    continue
                fp_a, fp_b = int(face_fp_idx[fid][0]), int(face_fp_idx[fid][1])
                a = fp_coords[fp_a]
                b = fp_coords[fp_b]
                face_segments.append((fid, ShapelyLine([a, b])))

        if not face_segments:
            return BCFixResult()

        # Detect conflicts
        buf = max(0.1, cell_size * 0.01)
        conflicts = []
        for fid, face_geom in face_segments:
            face_buf = face_geom.buffer(buf)
            hitting = [(b["name"], b["type"]) for b in bcs
                       if b["geom"] is not None and face_buf.intersects(b["geom"])]
            if len(hitting) >= 2:
                nd_bc = next((n for n, t in hitting if "normal" in t.lower()), None)
                conflicts.append(BCConflict(
                    face_id=fid,
                    bc_names=[n for n, _ in hitting],
                    bc_types=[t for _, t in hitting],
                    normal_depth_bc=nd_bc,
                ))

        result = BCFixResult(conflicts_found=len(conflicts))
        if not conflicts or dry_run:
            if dry_run:
                result.unresolvable = conflicts
            return result

        # Build working coords dict
        bc_coords = {
            b["name"]: list(b["geom"].coords) if b["geom"] else []
            for b in bcs
        }

        # Face midpoints for assignment check
        face_mids = {
            fid: ((g.coords[0][0] + g.coords[1][0]) / 2,
                  (g.coords[0][1] + g.coords[1][1]) / 2)
            for fid, g in face_segments
        }
        face_geoms = {fid: g for fid, g in face_segments}

        for conflict in conflicts:
            # Select which BC to trim
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

            # Which endpoint is nearest the conflicting face?
            start_dist = hypot(coords[0][0] - face_mid[0],
                               coords[0][1] - face_mid[1])
            end_dist = hypot(coords[-1][0] - face_mid[0],
                             coords[-1][1] - face_mid[1])
            trim_from_start = start_dist <= end_dist

            # Walk inward vertex-by-vertex
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
                # Fallback: interpolate endpoint
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

            # Minimum coverage: must still cover at least 1 other face
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
            result.trims.append((trim_name, f"trimmed {trimmed_count} pts from {direction}"))
            result.conflicts_fixed += 1

        if result.conflicts_fixed == 0:
            return result

        # Write trimmed coords back to the per-area 7.0 BC layout.
        with h5py.File(geom_hdf_path, "r+") as hf:
            if area_group_path is None:
                return result
            for b in bcs:
                bc_feature_path = f"{area_group_path}/BC Lines/{b['name']}"
                if bc_feature_path not in hf:
                    continue
                bc_feature = hf[bc_feature_path]
                if "Coordinates" in bc_feature:
                    del bc_feature["Coordinates"]
                bc_feature.create_dataset(
                    "Coordinates",
                    data=np.array(bc_coords.get(b["name"], []), dtype=np.float64),
                )

        result.modified_hdf = True
        logger.info(
            f"BC conflicts fixed: {result.conflicts_fixed}/{result.conflicts_found} "
            f"(trims: {result.trims})"
        )
        return result
