"""
GeomMesh - Headless 2D mesh generation, repair, and BC conflict resolution.

Provides headless (no-GUI) mesh generation via RasMapperLib.dll + pythonnet.
Replaces the need for RAS Mapper or RasProcess.exe for mesh operations.

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
from pathlib import Path
from typing import List, Optional, Tuple

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
            "pythonnet is required for mesh operations: pip install pythonnet\n"
            "Also run GeomMesh.setup_gdal_bridge() once to create the GDAL junction."
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


def _autofix_max_faces(mesh, seeds_as_list: list, ns: dict) -> Tuple[list, int]:
    """Tier 2: add midpoints of longest 2 faces per cell exceeding MAX_FACES."""
    new_pts = list(seeds_as_list)
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
                seen.add(fidx)
                n_added += 1
                added_this_cell += 1
            except Exception:
                pass

    return new_pts, n_added


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


def _seeds_from_multipoint(d2fa, ns: dict):
    """Read existing seeds from Geometry.MeshPoints."""
    pts = []
    try:
        for mp in d2fa.Geometry.MeshPoints.Points():
            count = mp.Count
            for i in range(count):
                pts.append(mp.PointM(i))
    except Exception:
        pass
    return pts


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
    """Tier 4 localized DP within error zones only."""
    try:
        from shapely.geometry import Polygon as ShapelyPolygon, Point as ShapelyPoint

        n = perim.Count
        coords = [(float(perim.PointM(i).X), float(perim.PointM(i).Y))
                  for i in range(n)]
        if not coords or coords[0] != coords[-1]:
            coords.append(coords[0])

        buf = cell_size * buf_multiplier
        error_points = [ShapelyPoint(x, y) for x, y in error_midpoints]

        simplified_coords = []
        for i, (x, y) in enumerate(coords):
            pt = ShapelyPoint(x, y)
            near_error = any(pt.distance(ep) < buf for ep in error_points)
            if near_error:
                continue  # skip points near error zones (simplified out)
            simplified_coords.append((x, y))

        if len(simplified_coords) < 3:
            return _douglas_peucker_polygon(perim, tol, ns)

        if simplified_coords[0] != simplified_coords[-1]:
            simplified_coords.append(simplified_coords[0])

        sp = ShapelyPolygon(simplified_coords)
        simplified = sp.simplify(tol, preserve_topology=True)
        new_coords = list(simplified.exterior.coords)

        from RasMapperLib import PointMs as _PointMs, Polygon as _Polygon  # type: ignore
        from RasMapperLib import PointM as _PointM  # type: ignore

        pt_list = _PointMs()
        for x, y in new_coords:
            pt_list.Add(_PointM(float(x), float(y)))
        return _Polygon(pt_list)
    except Exception as exc:
        logger.warning(f"Localized DP failed, falling back to global: {exc}")
        return _douglas_peucker_polygon(perim, tol, ns)


def _set_breakline_spacing_impl(
    geom_text_path: Path, near: Optional[float], far: Optional[float]
) -> Path:
    """Edit BreakLine CellSize Min/Max in .g## text file."""
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


def _set_point_generation_data(geom_text_path: Path, cell_size: float) -> None:
    """Update Storage Area Point Generation Data in .g## text file."""
    text = geom_text_path.read_text(encoding="utf-8", errors="replace")
    prefix = "Storage Area Point Generation Data="
    new_line = f"{prefix},,{cell_size:.6f},{cell_size:.6f}\n"
    lines = text.splitlines(keepends=True)
    modified = []
    for line in lines:
        if line.startswith(prefix):
            modified.append(new_line)
        else:
            modified.append(line)
    geom_text_path.write_text("".join(modified), encoding="utf-8")


def _patch_text_seeds(geom_text_path: Path, cell_centers) -> None:
    """Replace 'Storage Area 2D Points= N' block with generated cell centers."""
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
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("Storage Area 2D Points="):
            modified.append(f"Storage Area 2D Points= {n} \n")
            idx += 1
            while idx < len(lines) and lines[idx] and lines[idx][0].isdigit():
                idx += 1
            modified.extend(coord_lines)
        else:
            modified.append(line)
            idx += 1

    geom_text_path.write_text("".join(modified), encoding="utf-8")
    logger.info(f"Text seeds patched → {n} points in {geom_text_path.name}")


# ── Public API ────────────────────────────────────────────────────────────────


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
        >>> result = GeomMesh.generate("project.g01.hdf", cell_size=500.0)
        >>> if result.ok:
        ...     print(f"Mesh: {result.cell_count} cells")
    """

    @staticmethod
    def setup_gdal_bridge(
        hecras_dir: Optional[str | Path] = None,
        python_dir: Optional[str | Path] = None,
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
    def set_breakline_spacing(
        geom_text_path: str | Path,
        near: Optional[float] = None,
        far: Optional[float] = None,
    ) -> Path:
        """
        Edit BreakLine CellSize Min/Max in a .g## text file.

        Args:
            geom_text_path: Path to .g## plain text file (NOT .hdf).
            near: BreakLine near-spacing (ft/m). None clears field.
            far: BreakLine far-spacing (ft/m). None clears field.

        Returns:
            Path to .bak backup file created before writing.
        """
        geom_text_path = Path(geom_text_path)
        if not geom_text_path.exists():
            raise FileNotFoundError(f"Geometry text file not found: {geom_text_path}")
        return _set_breakline_spacing_impl(geom_text_path, near, far)

    @classmethod
    def generate(
        cls,
        hdf_path: str | Path,
        mesh_name: Optional[str] = None,
        mesh_index: int = 0,
        cell_size: Optional[float] = None,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[str | Path] = None,
    ) -> MeshResult:
        """
        Generate or regenerate a 2D mesh headlessly with auto-fix.

        Implements a 5-tier fix pipeline:
            Tier 0: Pre-flight removal of short perimeter segments
            Tier 1: Escalate MinFaceLengthRatio [0.05, 0.10, 0.15, 0.25]
            Tier 2: Add midpoints for MaxFacesPerCell violations
            Tier 3: Remove near-duplicate perimeter vertices
            Tier 4: Douglas-Peucker perimeter simplification

        Args:
            hdf_path: Path to .g## text file OR .g##.hdf compiled file.
                      Pass text path when breakline spacing was just edited.
            mesh_name: Name of 2D flow area (None = use mesh_index).
            mesh_index: 0-based index if mesh_name not provided.
            cell_size: Grid spacing for seed generation. None = reuse existing.
            min_face_length_ratio: Initial ratio (0.05-0.25).
            max_iterations: Maximum fix-and-retry attempts.
            hecras_dir: Override HEC-RAS installation directory.

        Returns:
            MeshResult with status, cell_count, face_count, fixes_applied.
        """
        _load_dlls(hecras_dir)
        ns = _imports()
        geom_path = str(hdf_path)

        actual_hdf_path = (
            geom_path if geom_path.lower().endswith(".hdf")
            else geom_path + ".hdf"
        )

        result = MeshResult(
            mesh_name=mesh_name or f"<index {mesh_index}>",
            status="error",
            geom_hdf_path=actual_hdf_path,
        )

        try:
            geom = ns["RASGeometry"](geom_path)
            d2fa = geom.D2FlowArea

            if mesh_name is not None:
                fid = d2fa.GetFeatureByName(mesh_name)
                if fid < 0:
                    fid = mesh_index
            else:
                fid = mesh_index
                mesh_name = d2fa.GetFeatureName(fid)
            result.mesh_name = mesh_name

            perim = d2fa.Geometry.MeshPerimeters.Polygon(fid)
            if perim is None:
                result.error_message = "MeshPerimeters.Polygon returned None"
                return result

            breaklines = _build_breaklines(d2fa, ns)

            if cell_size is not None:
                PointGenerator = ns["PointGenerator"]
                seeds_pm = PointGenerator.GeneratePoints(perim, float(cell_size))
                logger.info(f"[{mesh_name}] Generated {seeds_pm.Count} seeds at {cell_size:.0f}")
            else:
                seeds_list = _seeds_from_multipoint(d2fa, ns)
                if not seeds_list:
                    result.error_message = "No seeds and cell_size not specified"
                    return result
                seeds_pm = _seeds_from_pointms_list(seeds_list, ns)
                logger.info(f"[{mesh_name}] Using {seeds_pm.Count} existing seeds")

            ratios = [r for r in _RATIO_LADDER if r >= min_face_length_ratio]
            if not ratios:
                ratios = _RATIO_LADDER[:]

            current_perim = perim
            current_seeds_pm = seeds_pm

            # Tier 0: Pre-simplify — use cell_size * 0.5 as minimum segment length.
            # Natural watershed boundaries have many short segments that cause
            # FacePerimeterConnectionError; aggressive removal prevents this.
            if cell_size is not None:
                pre_n = current_perim.Count
                current_perim = _remove_short_perimeter_segments(
                    current_perim, cell_size * 0.5, ns
                )
                post_n = current_perim.Count
                if post_n < pre_n:
                    result.fixes_applied.append(
                        f"Tier0:short_seg_removal(-{pre_n - post_n})"
                    )
                    current_seeds_pm = PointGenerator.GeneratePoints(
                        current_perim, float(cell_size)
                    )

            tier4_count = 0
            MeshStatus = ns["MeshStatus"]
            complete_val = int(MeshStatus.Complete)
            max_faces_val = int(MeshStatus.MaxFacesPerCellExceeded)
            face_perim_val = int(MeshStatus.FacePerimeterConnectionError)
            perim_poly_val = int(MeshStatus.PerimeterPolygonError)

            for iteration in range(max_iterations):
                ratio = ratios[min(iteration, len(ratios) - 1)]
                mesh = _compute_mesh(current_perim, current_seeds_pm, breaklines, ratio, ns)
                state_val = int(mesh.MeshCompletionState)
                state_name = str(mesh.MeshCompletionState)
                result.iterations = iteration + 1

                if state_val == complete_val:
                    _save_mesh(geom, d2fa, fid, mesh, ns)
                    # Patch HDF and text seeds
                    try:
                        import h5py as _h5
                        import numpy as _np
                        _nv = mesh.NonVirtualCellCount
                        _text_path = (
                            Path(geom_path[:-4])
                            if geom_path.lower().endswith(".hdf") else None
                        )
                        with _h5.File(geom_path, "r+") as _hf:
                            _cc = _hf[
                                f"Geometry/2D Flow Areas/{mesh_name}/"
                                f"Cells Center Coordinate"
                            ][:]
                            _new_seeds = _cc[:_nv]
                            del _hf["Geometry/2D Flow Areas/Cell Points"]
                            _hf.create_dataset(
                                "Geometry/2D Flow Areas/Cell Points",
                                data=_new_seeds, dtype="float64",
                            )
                            _hf["Geometry/2D Flow Areas/Cell Info"][0] = [0, _nv]
                            _attrs_ds = _hf["Geometry/2D Flow Areas/Attributes"]
                            _attrs = _attrs_ds[:]
                            _attrs["Cell Count"][fid] = _nv
                            if cell_size is not None:
                                _attrs["Spacing dx"][fid] = float(cell_size)
                                _attrs["Spacing dy"][fid] = float(cell_size)
                            _attrs_ds[:] = _attrs

                        if _text_path is not None:
                            if cell_size is not None:
                                _set_point_generation_data(_text_path, float(cell_size))
                            _patch_text_seeds(_text_path, _new_seeds)
                    except Exception as _pe:
                        logger.warning(f"[{mesh_name}] Seed patch failed: {_pe}")

                    result.status = "complete"
                    result.mesh_state = state_name
                    result.cell_count = mesh.NonVirtualCellCount
                    result.face_count = mesh.FaceCount
                    return result

                # Tier 1: ratio escalation
                if iteration < len(ratios) - 1:
                    result.fixes_applied.append(
                        f"Tier1:ratio({ratio:.2f}->{ratios[iteration+1]:.2f})"
                    )
                    continue

                # Tier 2: MaxFacesPerCell
                if state_val == max_faces_val:
                    seeds_list = [current_seeds_pm[i] for i in range(current_seeds_pm.Count)]
                    new_list, n_added = _autofix_max_faces(mesh, seeds_list, ns)
                    if n_added == 0:
                        result.error_message = "MaxFacesPerCell: no midpoints added"
                        break
                    current_seeds_pm = _seeds_from_pointms_list(new_list, ns)
                    result.fixes_applied.append(f"Tier2:max_faces(+{n_added}pts)")
                    continue

                # Tier 3: FacePerimeterConnection
                if state_val in (face_perim_val, perim_poly_val):
                    bad_indices = _autofix_perimeter(current_perim, ns)
                    if bad_indices:
                        current_perim = _remove_perimeter_points(current_perim, bad_indices, ns)
                        result.fixes_applied.append(f"Tier3:perim_pts(-{len(bad_indices)})")
                        if cell_size is not None:
                            current_seeds_pm = ns["PointGenerator"].GeneratePoints(
                                current_perim, float(cell_size)
                            )
                        continue

                # Tier 4: Douglas-Peucker
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
                        result.fixes_applied.append(f"Tier4:local_dp({len(error_pts)}zones)")
                    else:
                        current_perim = _douglas_peucker_polygon(current_perim, tol, ns)
                        result.fixes_applied.append(f"Tier4:global_dp(tol={tol:.1f})")
                    if cell_size is not None:
                        current_seeds_pm = ns["PointGenerator"].GeneratePoints(
                            current_perim, float(cell_size)
                        )
                except Exception as exc:
                    result.error_message = f"Tier 4 failed: {exc}"
                    break
            else:
                result.error_message = f"Max iterations ({max_iterations}) reached"

            result.status = "error"
            result.mesh_state = state_name
            return result

        except Exception as exc:
            result.status = "exception"
            result.error_message = str(exc)
            logger.error(f"[{result.mesh_name}] Exception: {exc}")
            return result

    @classmethod
    def generate_all(
        cls,
        hdf_path: str | Path,
        cell_size: Optional[float] = None,
        min_face_length_ratio: float = 0.05,
        max_iterations: int = 8,
        hecras_dir: Optional[str | Path] = None,
    ) -> List[MeshResult]:
        """Generate/repair all 2D mesh areas in a geometry file."""
        _load_dlls(hecras_dir)
        ns = _imports()
        geom = ns["RASGeometry"](str(hdf_path))
        d2fa = geom.D2FlowArea
        count = d2fa.FeatureCount()
        results = []
        for i in range(count):
            name = d2fa.GetFeatureName(i)
            r = cls.generate(
                hdf_path=hdf_path,
                mesh_name=name,
                cell_size=cell_size,
                min_face_length_ratio=min_face_length_ratio,
                max_iterations=max_iterations,
                hecras_dir=hecras_dir,
            )
            results.append(r)
        return results

    @staticmethod
    def detect_bc_conflicts(
        geom_hdf_path: str | Path,
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
                bc_type = hf[f"{bc_group}/{bc_name}"].attrs.get("Type", b"").decode()
                bc_types.append(bc_type)

            # Read perimeter faces
            face_coords = hf[f"{fa_group}/FacePoints Coordinate"][:]
            face_info = hf[f"{fa_group}/Faces FacePoint Indexes"][:]
            is_perim = hf[f"{fa_group}/Faces Perimeter Info"][:]

            for face_id in range(len(face_info)):
                if not is_perim[face_id]:
                    continue
                fp_start, fp_count = face_info[face_id]
                pts = face_coords[fp_start:fp_start + fp_count]
                face_line = ShapelyLine(pts)

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

    @classmethod
    def fix_bc_conflicts(
        cls,
        geom_hdf_path: str | Path,
        cell_size: float,
        dry_run: bool = False,
    ) -> BCFixResult:
        """
        Detect and fix BC conflicts by trimming overlapping BC endpoints.

        Prefers trimming Normal Depth BCs (least sensitive to endpoint placement).

        Args:
            geom_hdf_path: Path to compiled .g##.hdf file.
            cell_size: Mesh cell size for buffer scaling.
            dry_run: If True, detect only — do not modify HDF.

        Returns:
            BCFixResult with conflicts_found, conflicts_fixed, unresolveable.
        """
        conflicts = cls.detect_bc_conflicts(geom_hdf_path, cell_size)
        result = BCFixResult(conflicts_found=len(conflicts))

        if not conflicts or dry_run:
            result.unresolveable = conflicts if dry_run else []
            return result

        # TODO: implement trim logic (port from mesh_bc_fix.py)
        # For now, report conflicts as unresolveable
        result.unresolveable = conflicts
        logger.warning(
            f"BC conflict fix not yet implemented — {len(conflicts)} conflicts reported"
        )
        return result
