"""
RasGeometryCompute - In-process, headless RASMapper geometry completion.

GUI-free equivalent of RASMapper's "Compute Geometry" action and its
"Validate Geometry" diagnostics, driven in-process through pythonnet against
RasMapperLib's ``RASGeometry`` object (no ``RasProcess.exe`` subprocess). This
authors HEC-RAS's own geometry-derived layers directly into the geometry HDF:

- River Edge Lines           ("Create Edge Lines at XS Limits")
- XS Interpolation Surface   ("Compute XS Interpolation Surface")
- River Flow Paths           ("Create Flow Paths from XS Layout")

Read the results back with the pure-h5py readers in ``HdfXsec``:
``get_river_edge_lines()``, ``get_xs_interpolation_surface()``,
``get_river_flow_paths()``.

Platform:
    Windows only (requires HEC-RAS 6.6+ and pythonnet). There is no Linux/Wine
    path for the in-process CLR bridge. For Linux geometry completion, use
    ``RasProcess.compute_geometry()`` (RasProcess.exe subprocess + Wine).

All methods are static; do not instantiate this class.
"""

from __future__ import annotations

import math
import platform
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Union

import h5py

if TYPE_CHECKING:
    import geopandas as gpd

from .LoggingConfig import get_logger
from .Decorators import log_call
from .ComputeResults import (
    FlowPathPolicyResult,
    GeometryCompleteResult,
    GeometryLayerResult,
)

logger = get_logger(__name__)

# Serialize pythonnet/RasMapperLib calls: the CLR bridge and RASGeometry save
# path are not designed for concurrent use from multiple threads.
_LOCK = threading.RLock()

# Native HDF group names for each generated layer.
_GROUP_EDGE_LINES = "Geometry/River Edge Lines"
_GROUP_INTERP_SURFACE = "Geometry/Cross Section Interpolation Surfaces"
_GROUP_FLOW_PATHS = "Geometry/River Flow Paths"


class RasGeometryCompute:
    """Headless RASMapper geometry completion via pythonnet (Windows only)."""

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _require_windows() -> None:
        """Raise on non-Windows before any pythonnet/RasMapperLib import."""
        if platform.system() != "Windows":
            raise RuntimeError(
                "RasGeometryCompute requires Windows (RasMapperLib is "
                "Windows-only). On Linux, use RasProcess.compute_geometry() "
                "(subprocess + Wine)."
            )

    @staticmethod
    def _ensure_clr(hecras_version: Optional[str] = None) -> None:
        """Load the RasMapperLib CLR references (call _require_windows first)."""
        RasGeometryCompute._require_windows()
        from .dotnet.clr_bootstrap import find_hecras_install, load_clr

        hecras_dir = find_hecras_install(version=hecras_version) if hecras_version else None
        load_clr(hecras_dir)

    @staticmethod
    def _release_geometry(geom) -> None:
        """Release a .NET RASGeometry object and its underlying HDF file handles.

        Runs the .NET finalizers so file handles are freed before the HDF is
        reopened or copied; without this, handles accumulate across many
        in-process calls and later reads/writes hit
        ``System.UnauthorizedAccessException`` on the locked file.
        """
        if geom is not None:
            for method in ("Dispose", "Close"):
                try:
                    getattr(geom, method)()
                except Exception:
                    pass
        try:
            from System import GC as _GC  # type: ignore
            _GC.Collect()
            _GC.WaitForPendingFinalizers()
            _GC.Collect()
        except Exception:
            import gc
            gc.collect()

    @staticmethod
    def _resolve_rasmap(rasmap_path, geom_hdf_path: Path, ras_object):
        """Best-effort resolution of the .rasmap for spatial reference."""
        if rasmap_path is not None:
            return Path(rasmap_path)
        try:
            from .RasMap import RasMap
            resolved = RasMap.get_rasmap_path(ras_object)
            if resolved is not None:
                return Path(resolved)
        except Exception as exc:
            logger.debug(f"Could not auto-resolve .rasmap: {exc}")
        return None

    @staticmethod
    def _load_geometry(geom_hdf_path: Path, rasmap_path: Optional[Path]):
        """Construct a RasMapperLib RASGeometry from the geometry HDF path.

        Geometry-layer generation operates in the geometry's own coordinate
        space and does not require a spatial reference; when a ``.rasmap`` is
        available its projection is applied best-effort for parity with
        RASMapper, but its absence is not fatal.
        """
        from RasMapperLib import RASGeometry  # type: ignore

        if rasmap_path is not None and Path(rasmap_path).exists():
            try:
                from Geospatial import SharedData  # type: ignore
                if getattr(SharedData, "SRSProjection", None) is None:
                    from RasMapperLib import RASMapperCom  # type: ignore
                    SharedData.SRSFilename = RASMapperCom.GetSRSFromRasmapDoc(str(rasmap_path))
            except Exception as exc:
                logger.debug(f"Spatial reference not applied (non-fatal): {exc}")

        return RASGeometry(str(geom_hdf_path))

    @staticmethod
    def _layer_exists(geom_hdf_path: Path, group: str) -> bool:
        # Inspection errors propagate so a locked/unreadable HDF fails closed and
        # is never mistaken for "layer absent" by the overwrite guard.
        with h5py.File(geom_hdf_path, "r") as hdf:
            return group in hdf

    @staticmethod
    def _backup_layer(geom_hdf_path: Path, tag: str,
                      reader: Callable[[Path], "object"]) -> Optional[Path]:
        """Export an existing layer to a dated GeoJSON sidecar before overwrite.

        Returns the backup path, or None when the existing layer reads as empty.
        Because a group known to exist should never read empty, callers treat
        None as a failed backup and refuse to overwrite. Write errors propagate.
        """
        gdf = reader(geom_hdf_path)
        if gdf is None or getattr(gdf, "empty", True):
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = geom_hdf_path.with_name(f"{geom_hdf_path.stem}.{tag}.{ts}.geojson.bak")
        gdf.to_file(backup, driver="GeoJSON")
        logger.info(f"Backed up existing {tag} to {backup.name}")
        return backup

    @staticmethod
    def _generate_layer(geom_hdf_path, rasmap_path, overwrite, backup,
                        ras_object, hecras_version, *,
                        group: str, layer_name: str, tag: str,
                        reader: Callable, compute: Callable) -> GeometryLayerResult:
        """Shared body for the three single-layer generators."""
        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")
        RasGeometryCompute._require_windows()

        start = time.perf_counter()
        backup_path = None
        geom = None

        def _fail(msg):
            return GeometryLayerResult(
                success=False, layer=layer_name, geom_hdf_path=geom_hdf_path,
                backup_path=backup_path, elapsed_seconds=time.perf_counter() - start,
                error=msg,
            )

        # Hold the lock across check -> backup -> compute -> verify so the
        # overwrite guard cannot race a concurrent generation on the same geometry.
        with _LOCK:
            try:
                exists = RasGeometryCompute._layer_exists(geom_hdf_path, group)
            except Exception as exc:
                logger.error(f"Could not inspect {geom_hdf_path.name} for {layer_name}: {exc}")
                return _fail(f"Could not inspect geometry HDF: {exc}")

            if exists and not overwrite:
                logger.info(f"{layer_name} already present; skipping (overwrite=False)")
                return GeometryLayerResult(
                    success=True, layer=layer_name, geom_hdf_path=geom_hdf_path,
                    skipped=True, elapsed_seconds=time.perf_counter() - start,
                )

            # Never destroy an existing layer without a successful backup, unless
            # the caller explicitly opts out with backup=False.
            if exists and overwrite and backup:
                try:
                    backup_path = RasGeometryCompute._backup_layer(geom_hdf_path, tag, reader)
                except Exception as exc:
                    return _fail(f"Refusing to overwrite {layer_name}: backup failed: {exc}")
                if backup_path is None:
                    return _fail(
                        f"Refusing to overwrite {layer_name}: the existing layer "
                        f"produced no backup (possible read anomaly). Pass "
                        f"backup=False to override."
                    )

            try:
                RasGeometryCompute._ensure_clr(hecras_version)
                rasmap = RasGeometryCompute._resolve_rasmap(rasmap_path, geom_hdf_path, ras_object)
                geom = RasGeometryCompute._load_geometry(geom_hdf_path, rasmap)
                ok = bool(compute(geom))
                written = RasGeometryCompute._layer_exists(geom_hdf_path, group)
            except Exception as exc:
                logger.error(f"{layer_name} generation failed: {exc}")
                return _fail(str(exc))
            finally:
                RasGeometryCompute._release_geometry(geom)

        if not (ok and written):
            logger.warning(f"{layer_name} generation did not produce the layer")
        return GeometryLayerResult(
            success=ok and written, layer=layer_name, geom_hdf_path=geom_hdf_path,
            backup_path=backup_path, elapsed_seconds=time.perf_counter() - start,
        )

    # ------------------------------------------------------------------ #
    #  Public generators
    # ------------------------------------------------------------------ #

    @staticmethod
    @log_call
    def generate_edge_lines(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        backup: bool = True,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> GeometryLayerResult:
        """
        Generate HEC-RAS river edge lines into ``Geometry/River Edge Lines``.

        RASMapper's *Create Edge Lines at XS Limits*, run in-process. Unlike
        ``HdfXsec.generate_river_edge_lines()`` (a pure-Python XS-endpoint
        approximation used by ``get_1d_footprint()``), this produces HEC-RAS's
        own bank-line-anchored offset-curve edge lines and writes the group-level
        ``Source Data Hash`` so HEC-RAS treats them as authoritative. Read the
        result with ``HdfXsec.get_river_edge_lines()``.

        Parameters
        ----------
        geom_hdf_path : str or Path
            Geometry HDF (``.g##.hdf``), mutated in place.
        rasmap_path : str or Path, optional
            ``.rasmap`` for spatial reference; auto-resolved from ``ras_object``
            when omitted. Not required (geometry operations are coordinate-space).
        overwrite : bool, default False
            When False and the layer already exists, skip without recomputing.
        backup : bool, default True
            When overwriting an existing layer, first export it to a dated
            ``.geojson.bak`` sidecar.
        ras_object : RasPrj, optional
            Used only to auto-resolve the ``.rasmap``.
        hecras_version : str, optional
            Specific HEC-RAS version to bind the CLR to (e.g. ``"6.6"``).

        Returns
        -------
        GeometryLayerResult
        """
        return RasGeometryCompute._generate_layer(
            geom_hdf_path, rasmap_path, overwrite, backup, ras_object, hecras_version,
            group=_GROUP_EDGE_LINES, layer_name="River Edge Lines", tag="edge_lines",
            reader=RasGeometryCompute._read_edge_lines,
            compute=lambda geom: geom.EdgeLines.ComputeEdgeLines(True),
        )

    @staticmethod
    @log_call
    def generate_interpolation_surface(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        backup: bool = True,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> GeometryLayerResult:
        """
        Generate the XS interpolation surface into
        ``Geometry/Cross Section Interpolation Surfaces``.

        RASMapper's *Compute XS Interpolation Surface*, run in-process. HEC-RAS
        self-ensures bank lines and edge lines first, so those layers are also
        (re)generated as a side effect when out of date. Read the result with
        ``HdfXsec.get_xs_interpolation_surface()``.

        Parameters and returns mirror ``generate_edge_lines()``.
        """
        return RasGeometryCompute._generate_layer(
            geom_hdf_path, rasmap_path, overwrite, backup, ras_object, hecras_version,
            group=_GROUP_INTERP_SURFACE, layer_name="Cross Section Interpolation Surfaces",
            tag="interpolation_surface",
            reader=RasGeometryCompute._read_interp_surface,
            compute=lambda geom: geom.XSInterpolationSurface.ComputeInterpolationSurface(True),
        )

    @staticmethod
    @log_call
    def generate_flow_paths(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        backup: bool = True,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> GeometryLayerResult:
        """
        Generate river flow paths into ``Geometry/River Flow Paths``.

        RASMapper's *Create Flow Paths from XS Layout*, run in-process. Read the
        result with ``HdfXsec.get_river_flow_paths()``.

        **Manually defined or corrected flow paths must not be overwritten.**
        HEC-RAS keeps no cache hash for flow paths, so any regeneration
        unconditionally replaces them. This method therefore defaults to
        ``overwrite=False`` (skip when flow paths already exist). Set
        ``overwrite=True`` to regenerate; with ``backup=True`` (default) the
        existing flow paths are first exported to a dated ``.geojson.bak``
        sidecar. Use ``HdfXsec.get_river_flow_paths()`` to check for existing
        flow paths before deciding.

        Parameters and returns mirror ``generate_edge_lines()``.
        """
        return RasGeometryCompute._generate_layer(
            geom_hdf_path, rasmap_path, overwrite, backup, ras_object, hecras_version,
            group=_GROUP_FLOW_PATHS, layer_name="River Flow Paths", tag="flow_paths",
            reader=RasGeometryCompute._read_flow_paths,
            compute=lambda geom: geom.FlowPathLines.ComputeFlowPathLines(),
        )

    @staticmethod
    @log_call
    def compute_geometry(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        backup: bool = True,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> GeometryCompleteResult:
        """
        Run the full RASMapper geometry-completion pipeline, in-process.

        In-process equivalent of ``RasProcess.compute_geometry()`` and RASMapper's
        "Compute Geometry" action (RasMapperLib ``RASGeometry.CompleteForComputations``).
        Generates bank lines, ineffective areas, blocked obstructions, edge lines,
        the XS interpolation surface, storage-area / structure connectivity, and
        2D property tables. **Flow paths are not part of this pipeline** (HEC-RAS
        does not compute them during geometry completion); use
        ``generate_flow_paths()`` for those.

        Mutates the geometry HDF in place. No subprocess; Windows only (on Linux,
        use ``RasProcess.compute_geometry()``).

        Parameters
        ----------
        geom_hdf_path, rasmap_path, ras_object, hecras_version
            As in ``generate_edge_lines()``.
        overwrite : bool, default False
            When False and edge lines already exist, skip the whole pipeline.
        backup : bool, default True
            Back up existing edge lines to a dated ``.geojson.bak`` before an
            overwrite.

        Returns
        -------
        GeometryCompleteResult
        """
        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")
        RasGeometryCompute._require_windows()

        start = time.perf_counter()
        backup_path = None
        geom = None

        def _fail(msg):
            return GeometryCompleteResult(
                success=False, geom_hdf_path=geom_hdf_path, backup_path=backup_path,
                elapsed_seconds=time.perf_counter() - start, error=msg,
            )

        with _LOCK:
            try:
                edge_exists = RasGeometryCompute._layer_exists(geom_hdf_path, _GROUP_EDGE_LINES)
                interp_exists = RasGeometryCompute._layer_exists(geom_hdf_path, _GROUP_INTERP_SURFACE)
            except Exception as exc:
                logger.error(f"Could not inspect {geom_hdf_path.name}: {exc}")
                return _fail(f"Could not inspect geometry HDF: {exc}")

            # Skip only when the completion artifacts are BOTH present (edge lines
            # alone do not prove the pipeline ran to completion).
            if edge_exists and interp_exists and not overwrite:
                logger.info("Geometry already completed (edge lines + interpolation "
                            "surface present); skipping")
                return GeometryCompleteResult(
                    success=True, geom_hdf_path=geom_hdf_path,
                    edge_lines_written=True, interpolation_surface_written=True,
                    flow_paths_written=RasGeometryCompute._layer_exists(
                        geom_hdf_path, _GROUP_FLOW_PATHS),
                    elapsed_seconds=time.perf_counter() - start,
                )

            if edge_exists and overwrite and backup:
                try:
                    backup_path = RasGeometryCompute._backup_layer(
                        geom_hdf_path, "edge_lines", RasGeometryCompute._read_edge_lines)
                except Exception as exc:
                    return _fail(f"Refusing to overwrite: edge-line backup failed: {exc}")
                if backup_path is None:
                    return _fail(
                        "Refusing to overwrite: existing edge lines produced no backup "
                        "(possible read anomaly). Pass backup=False to override."
                    )

            try:
                RasGeometryCompute._ensure_clr(hecras_version)
                rasmap = RasGeometryCompute._resolve_rasmap(rasmap_path, geom_hdf_path, ras_object)
                geom = RasGeometryCompute._load_geometry(geom_hdf_path, rasmap)
                ok = bool(geom.CompleteForComputations(False, None))
                edge_written = RasGeometryCompute._layer_exists(geom_hdf_path, _GROUP_EDGE_LINES)
                interp_written = RasGeometryCompute._layer_exists(geom_hdf_path, _GROUP_INTERP_SURFACE)
                flow_written = RasGeometryCompute._layer_exists(geom_hdf_path, _GROUP_FLOW_PATHS)
            except Exception as exc:
                logger.error(f"compute_geometry failed: {exc}")
                return _fail(str(exc))
            finally:
                RasGeometryCompute._release_geometry(geom)

        success = ok and edge_written and interp_written
        if not success:
            logger.warning("compute_geometry did not produce all required artifacts "
                           f"(ok={ok}, edge={edge_written}, interp={interp_written})")
        return GeometryCompleteResult(
            success=success,
            geom_hdf_path=geom_hdf_path,
            edge_lines_written=edge_written,
            interpolation_surface_written=interp_written,
            flow_paths_written=flow_written,
            backup_path=backup_path,
            elapsed_seconds=time.perf_counter() - start,
        )

    # ------------------------------------------------------------------ #
    #  Diagnostics
    # ------------------------------------------------------------------ #

    @staticmethod
    @log_call
    def validate_geometry(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> "object":
        """
        Run HEC-RAS geometry validation and return the diagnostics.

        RASMapper's *Validate Geometry* (RasMapperLib
        ``RASGeometry.ValidateGeometry`` + ``RASGeometry.Errors``), run
        in-process. Surfaces per-feature construction problems such as
        self-intersecting edge lines, overlapping cross-section cut lines,
        XS profile/polyline length mismatches, and bankline/flow-path
        intersections — the issues that block edge-line and interpolation-surface
        generation. One row per individual error.

        Not to be confused with ``RasProcess.validate_geometry_association_cli()``,
        which validates terrain/land-cover association attributes, not per-feature
        geometry construction.

        Returns
        -------
        GeoDataFrame
            Columns: ``severity`` (INFO/WARNING/ERROR), ``level`` (raw RASMapper
            level), ``layer``, ``River``, ``Reach``, ``RS`` (parsed from the
            feature name when it matches ``River, Reach (RS)``; else None),
            ``feature`` (raw feature name), ``process``, ``message``, ``geometry``
            (currently None; reserved for the offending feature geometry). Empty
            GeoDataFrame when no problems are found.
        """
        import geopandas as gpd

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")
        RasGeometryCompute._require_windows()

        geom = None
        with _LOCK:
            try:
                RasGeometryCompute._ensure_clr(hecras_version)
                rasmap = RasGeometryCompute._resolve_rasmap(rasmap_path, geom_hdf_path, ras_object)
                geom = RasGeometryCompute._load_geometry(geom_hdf_path, rasmap)
                rows = RasGeometryCompute._harvest_errors(geom)
            finally:
                RasGeometryCompute._release_geometry(geom)

        if not rows:
            return gpd.GeoDataFrame(
                columns=["severity", "level", "layer", "River", "Reach", "RS",
                         "feature", "process", "message", "geometry"],
                geometry="geometry",
            )
        return gpd.GeoDataFrame(rows, geometry="geometry")

    @staticmethod
    @log_call
    def is_valid_geometry(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> bool:
        """
        Return True when ``validate_geometry()`` reports no ERROR-level problems.

        Convenience wrapper matching the ``is_valid_*`` validation-framework
        naming. WARNING/INFO diagnostics do not fail the check.
        """
        report = RasGeometryCompute.validate_geometry(
            geom_hdf_path, rasmap_path=rasmap_path, ras_object=ras_object,
            hecras_version=hecras_version,
        )
        if report is None or report.empty:
            return True
        return not (report["severity"] == "ERROR").any()

    # ------------------------------------------------------------------ #
    #  Reach-length audit
    # ------------------------------------------------------------------ #

    @staticmethod
    @log_call
    def audit_reach_lengths(
        geom_hdf_path: Union[str, Path],
        flow_paths: str = "existing_or_generate",
        tolerance: float = 0.5,
        keep_working_copy: bool = False,
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> "object":
        """
        Audit XS reach (flow) lengths against the current cut lines and flow paths.

        A 1D unsteady model requires LOB / channel / ROB reach lengths on every
        cross section; HEC-RAS measures those along the flow paths, so they go
        stale when cut lines move. This copies the **whole project** to a
        temporary location (the original is never modified), recomputes the reach
        lengths from the flow paths on the copy (RASMapper's "Update Reach Lengths
        on XSs"), and returns a per-XS before/after comparison so you can see which
        lengths have drifted.

        The project (not just the geometry HDF) is copied because RASGeometry
        needs the full project context to build the XS / river / flow-path
        intersections that reach-length measurement depends on. For large projects
        this copies the project directory; pass ``keep_working_copy=True`` to keep
        the recomputed copy for inspection instead of deleting it.

        Parameters
        ----------
        geom_hdf_path : str or Path
            Geometry HDF to audit (must sit in its HEC-RAS project folder).
            **Not** modified.
        flow_paths : {'existing_or_generate', 'regenerate', 'existing'}
            How to obtain flow paths on the copy before measuring lengths.
            'existing_or_generate' (default) leaves existing flow paths untouched
            (protecting manual edits) and generates them only when absent;
            'regenerate' always regenerates them on the copy; 'existing' requires
            them and raises if absent.
        tolerance : float, default 0.5
            Absolute length change (project units) above which a length is flagged
            as ``changed``.
        keep_working_copy : bool, default False
            Keep the temporary project copy (with recomputed lengths) instead of
            deleting it. The copied geometry HDF path is returned in
            ``report.attrs['working_copy']``.
        rasmap_path, ras_object, hecras_version
            As in the generators.

        Returns
        -------
        GeoDataFrame
            One row per cross section: ``River``, ``Reach``, ``RS``,
            ``len_{left,channel,right}_stored`` / ``_recomputed``,
            ``delta_{left,channel,right}``, ``reach_end`` (bool; the
            downstream-most XS of a reach whose recomputed lengths are undefined),
            ``changed`` (bool), and ``geometry`` (the XS cut line). ``.attrs``
            carries a summary (``changed_count``, ``used_existing_flow_paths``,
            ``working_copy``).

        Raises
        ------
        ValueError
            If ``flow_paths`` is unrecognized, ``flow_paths='existing'`` but the
            geometry has none, or the geometry has no cross sections.
        """
        if flow_paths not in ("existing_or_generate", "regenerate", "existing"):
            raise ValueError(
                "flow_paths must be 'existing_or_generate', 'regenerate', or "
                f"'existing', got {flow_paths!r}"
            )
        import numpy as np
        if not isinstance(tolerance, (int, float)) or np.isnan(tolerance) or tolerance < 0:
            raise ValueError(f"tolerance must be a non-negative number, got {tolerance!r}")

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")
        RasGeometryCompute._require_windows()

        from .hdf.HdfXsec import HdfXsec
        from .RasUtils import RasUtils

        # The geometry HDF must live in its HEC-RAS project folder (RASGeometry
        # needs the full project context, resolved relative to the .prj).
        project_folder = geom_hdf_path.parent
        if not any(project_folder.glob("*.prj")):
            raise ValueError(
                f"{geom_hdf_path.name} is not in a HEC-RAS project folder (no .prj "
                f"found in {project_folder}); audit_reach_lengths needs the project "
                f"context to compute reach lengths.")

        tmp_root = Path(tempfile.mkdtemp(prefix="reach_audit_"))
        work_project = tmp_root / project_folder.name
        used_existing_flow_paths = False
        audit_completed = False
        try:
            geom = None
            # Serialize the whole snapshot+compute so the copy is consistent with
            # (and not racing) any concurrent in-process geometry writer.
            with _LOCK:
                try:
                    shutil.copytree(project_folder, work_project,
                                    ignore=RasUtils.ignore_windows_reserved)
                    work = work_project / geom_hdf_path.name

                    stored = HdfXsec.get_cross_sections(work, ras_object=ras_object)
                    if stored is None or stored.empty:
                        raise ValueError("No cross sections found; cannot audit reach lengths")

                    RasGeometryCompute._ensure_clr(hecras_version)
                    rasmap = RasGeometryCompute._resolve_rasmap(rasmap_path, work, ras_object)
                    geom = RasGeometryCompute._load_geometry(work, rasmap)

                    fp_exists = RasGeometryCompute._layer_exists(work, _GROUP_FLOW_PATHS)
                    if flow_paths == "existing":
                        if not fp_exists:
                            raise ValueError(
                                "flow_paths='existing' but the geometry has no flow paths")
                        used_existing_flow_paths = True
                    elif flow_paths == "regenerate" or not fp_exists:
                        geom.FlowPathLines.ComputeFlowPathLines()
                    else:  # existing_or_generate and flow paths already present
                        used_existing_flow_paths = True

                    from System.Collections.Generic import List  # type: ignore
                    from System import Int32  # type: ignore
                    xsids = List[Int32]()
                    for i in range(int(geom.XS.FeatureCount())):
                        xsids.Add(i)
                    # ref RiverMap defaults to null -> HEC-RAS builds it internally.
                    geom.ComputeReachLengthsForXSs(xsids, None)
                    geom.Save()
                finally:
                    RasGeometryCompute._release_geometry(geom)

            recomputed = HdfXsec.get_cross_sections(work, ras_object=ras_object)

            # No-op guard: a real recompute writes NaN to the downstream-most XS of
            # every reach (no downstream XS). Zero NaNs means the recompute silently
            # did nothing (e.g. missing project context or flow paths).
            len_cols = ["Len Left", "Len Channel", "Len Right"]
            if not recomputed[len_cols].isna().to_numpy().any():
                raise RuntimeError(
                    "Reach-length recompute produced no reach-end NaN values; it "
                    "likely no-op'd (missing project context or flow paths). No "
                    "reliable audit could be produced.")

            report = RasGeometryCompute._reach_length_diff(stored, recomputed, tolerance)
            report.attrs["changed_count"] = int(report["changed"].sum())
            report.attrs["invalid_recompute_count"] = int(report["invalid_recompute"].sum())
            report.attrs["used_existing_flow_paths"] = used_existing_flow_paths
            report.attrs["working_copy"] = str(work) if keep_working_copy else None
            audit_completed = True
            return report
        finally:
            if not keep_working_copy or not audit_completed:
                shutil.rmtree(tmp_root, ignore_errors=True)

    @staticmethod
    @log_call
    def assess_flow_path_policy(
        geom_hdf_path: Union[str, Path],
        tolerance_fraction: float = 0.01,
        *,
        join_upstream_xs: Optional[tuple[str, str, Union[str, float, int]]] = None,
        join_downstream_xs: Optional[tuple[str, str, Union[str, float, int]]] = None,
        review_segments_path: Optional[Union[str, Path]] = None,
        keep_working_copy: bool = False,
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        hecras_version: Optional[str] = None,
    ) -> FlowPathPolicyResult:
        """Recommend how a 1D join should handle overbank flow paths.

        The original project is never modified.  This method copies the whole
        project, regenerates RAS Mapper flow paths on the copy, recomputes every
        XS LOB/channel/ROB reach length, and compares the regenerated values to
        the stored source values.

        ``regenerate_and_recompute`` is recommended only when every usable LOB
        and ROB interval agrees with its stored value within
        ``tolerance_fraction``.  Otherwise the conservative recommendation is
        ``preserve_and_recompute_only_at_join_boundary``. The conservative policy is
        also selected when the source has no flow-path layer but stored LOB or
        ROB lengths differ from the stored channel length.

        Pass both ``join_upstream_xs`` and ``join_downstream_xs`` as
        ``(river, reach, river_station)`` tuples after a provisional joined
        geometry exists.  The regenerated left/right flow paths are then clipped
        between those adjacent cross sections and returned in
        ``join_segments_gdf``.  The segments are review evidence for updating
        only the new join interval; they do not modify the source or destination.

        ``review_segments_path`` optionally writes those two segments as
        GeoParquet.  Existing files are never overwritten.
        """
        tolerance_fraction = RasGeometryCompute._validate_tolerance_fraction(
            tolerance_fraction
        )
        if (join_upstream_xs is None) != (join_downstream_xs is None):
            raise ValueError(
                "join_upstream_xs and join_downstream_xs must be supplied together"
            )
        if review_segments_path is not None and join_upstream_xs is None:
            raise ValueError(
                "review_segments_path requires join_upstream_xs and "
                "join_downstream_xs"
            )

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")

        from .hdf.HdfXsec import HdfXsec

        source_flow_paths = HdfXsec.get_river_flow_paths(geom_hdf_path)
        audit = RasGeometryCompute.audit_reach_lengths(
            geom_hdf_path,
            flow_paths="regenerate",
            tolerance=0.0,
            keep_working_copy=True,
            rasmap_path=rasmap_path,
            ras_object=ras_object,
            hecras_version=hecras_version,
        )
        working_value = audit.attrs.get("working_copy")
        if not working_value:
            raise RuntimeError("Reach-length audit did not retain its working copy")
        working_copy = Path(str(working_value))
        cleanup_root = working_copy.parent.parent

        try:
            regenerated_flow_paths = HdfXsec.get_river_flow_paths(working_copy)
            if regenerated_flow_paths.empty:
                raise RuntimeError(
                    "RAS Mapper regenerated no flow paths on the working copy"
                )

            xs_metrics = RasGeometryCompute._augment_reach_length_metrics(
                audit, tolerance_fraction
            )
            source_flow_path_counts = (
                RasGeometryCompute._count_flow_paths_by_reach(
                    source_flow_paths, xs_metrics
                )
            )
            reach_metrics = RasGeometryCompute._summarize_flow_path_policy(
                xs_metrics,
                tolerance_fraction=tolerance_fraction,
                source_flow_path_counts=source_flow_path_counts,
            )
            if reach_metrics.empty:
                raise RuntimeError("No usable river/reach policy evidence was produced")
            preserve_policy = "preserve_and_recompute_only_at_join_boundary"
            recommended_policy = (
                preserve_policy
                if (reach_metrics["recommended_policy"] == preserve_policy).any()
                else "regenerate_and_recompute"
            )

            join_segments = RasGeometryCompute._empty_join_segments(
                getattr(regenerated_flow_paths, "crs", None)
            )
            if join_upstream_xs is not None and join_downstream_xs is not None:
                joined_xs = HdfXsec.get_cross_sections(working_copy)
                centerlines = HdfXsec.get_river_centerlines(working_copy)
                join_segments = RasGeometryCompute._clip_join_flow_path_segments(
                    regenerated_flow_paths,
                    joined_xs,
                    centerlines,
                    join_upstream_xs,
                    join_downstream_xs,
                )

            saved_review_path = None
            if review_segments_path is not None:
                review_path = Path(review_segments_path)
                if review_path.suffix.lower() not in {".parquet", ".geoparquet"}:
                    raise ValueError(
                        "review_segments_path must use .parquet or .geoparquet"
                    )
                if review_path.exists():
                    raise FileExistsError(review_path)
                review_path.parent.mkdir(parents=True, exist_ok=True)
                join_segments.to_parquet(review_path, index=False)
                saved_review_path = review_path

            retained_copy = working_copy if keep_working_copy else None
            return FlowPathPolicyResult(
                geom_hdf_path=geom_hdf_path,
                recommended_policy=recommended_policy,
                tolerance_fraction=tolerance_fraction,
                xs_metrics_df=xs_metrics,
                reach_metrics_df=reach_metrics,
                source_flow_paths_gdf=source_flow_paths,
                regenerated_flow_paths_gdf=regenerated_flow_paths,
                join_segments_gdf=join_segments,
                review_segments_path=saved_review_path,
                working_copy=retained_copy,
            )
        finally:
            if not keep_working_copy:
                RasGeometryCompute._remove_reach_audit_copy(cleanup_root)

    @staticmethod
    @log_call
    def audit_main_channel_lengths(
        geom_path: Union[str, Path],
        tolerance_fraction: float = 0.01,
        *,
        ras_object=None,
    ) -> "gpd.GeoDataFrame":
        """Compare stored channel lengths to distances along the river line.

        Accepts a plain-text ``.g##`` geometry or compiled ``.g##.hdf`` and does
        not modify or clone it.  This is an informative, cross-platform QA
        check. ``main_channel_flagged`` is true for a non-terminal XS whose
        stored and centerline-measured channel lengths differ by more than the
        relative tolerance, or whose river-line intersection is invalid.
        """
        tolerance_fraction = RasGeometryCompute._validate_tolerance_fraction(
            tolerance_fraction
        )
        geom_path = Path(geom_path)
        if not geom_path.is_file():
            raise FileNotFoundError(geom_path)

        if geom_path.name.lower().endswith(".hdf"):
            from .hdf.HdfXsec import HdfXsec

            xs = HdfXsec.get_cross_sections(geom_path, ras_object=ras_object)
            centerlines = HdfXsec.get_river_centerlines(geom_path)
            xs = xs.rename(columns={"Len Channel": "Length_Channel"})
            centerlines = centerlines.rename(
                columns={"River Name": "River", "Reach Name": "Reach"}
            )
        else:
            from .geom.GeomCrossSection import GeomCrossSection
            from .geom.GeomParser import GeomParser

            xs = GeomCrossSection.get_cross_sections(geom_path)
            cut_lines = GeomParser.get_xs_cut_lines(geom_path).rename(
                columns={"river": "River", "reach": "Reach", "station": "RS"}
            )
            xs = xs.loc[xs["Type"] == 1].merge(
                cut_lines[["River", "Reach", "RS", "geometry"]],
                on=["River", "Reach", "RS"],
                how="left",
                validate="one_to_one",
            )
            centerlines = GeomParser.get_river_centerlines(geom_path).rename(
                columns={"river": "River", "reach": "Reach"}
            )

        result = RasGeometryCompute._measure_main_channel_lengths(
            xs, centerlines, tolerance_fraction
        )
        result.attrs["tolerance_fraction"] = tolerance_fraction
        result.attrs["flagged_count"] = int(result["main_channel_flagged"].sum())
        result.attrs["source_geometry"] = str(geom_path)
        return result

    @staticmethod
    def _measure_main_channel_lengths(xs, centerlines, tolerance_fraction: float):
        """Measure adjacent XS spacing along each matching river centerline."""
        import re

        import geopandas as gpd

        required_xs = {"River", "Reach", "RS", "Length_Channel", "geometry"}
        required_centerline = {"River", "Reach", "geometry"}
        if not required_xs.issubset(xs.columns):
            raise ValueError(
                f"Cross-section data is missing {sorted(required_xs - set(xs.columns))}"
            )
        if not required_centerline.issubset(centerlines.columns):
            raise ValueError(
                "Centerline data is missing "
                f"{sorted(required_centerline - set(centerlines.columns))}"
            )
        if xs.empty:
            raise ValueError("Cross-section data is empty")
        if centerlines.empty:
            raise ValueError("River-centerline data is empty")

        def station_number(value):
            match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value))
            if match is None:
                raise ValueError(f"River station is not numeric: {value!r}")
            return float(match.group(0))

        def intersection_points(first, second):
            from shapely.geometry import Point

            intersection = first.intersection(second)
            if isinstance(intersection, Point):
                return [intersection]
            if hasattr(intersection, "geoms"):
                return [geom for geom in intersection.geoms if isinstance(geom, Point)]
            return []

        rows = []
        for (river, reach), group in xs.groupby(
            ["River", "Reach"], sort=False, dropna=False
        ):
            matches = centerlines.loc[
                (centerlines["River"].astype(str) == str(river))
                & (centerlines["Reach"].astype(str) == str(reach))
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Centerline {river}/{reach} resolved {len(matches)} times"
                )
            centerline = RasGeometryCompute._line_geometry(
                matches.iloc[0].geometry, f"centerline {river}/{reach}"
            )
            ordered = group.copy()
            ordered["_station_number"] = ordered["RS"].map(station_number)
            ordered = ordered.sort_values("_station_number", ascending=False)
            if ordered["_station_number"].duplicated().any():
                raise ValueError(f"Duplicate numeric river stations in {river}/{reach}")

            records = []
            for item in ordered.itertuples(index=False):
                cut_line = RasGeometryCompute._line_geometry(
                    item.geometry, f"cross section {river}/{reach}/{item.RS}"
                )
                points = intersection_points(cut_line, centerline)
                records.append((item, cut_line, points))

            for index, (item, cut_line, points) in enumerate(records):
                reach_end = index == len(records) - 1
                recomputed = float("nan")
                if not reach_end and len(points) == 1 and len(records[index + 1][2]) == 1:
                    recomputed = abs(
                        centerline.project(points[0])
                        - centerline.project(records[index + 1][2][0])
                    )
                stored = float(item.Length_Channel)
                relative_error = RasGeometryCompute._relative_length_error(
                    stored, recomputed
                )
                within = bool(
                    not reach_end
                    and math.isfinite(relative_error)
                    and relative_error <= tolerance_fraction
                )
                flagged = bool(
                    not reach_end
                    and (
                        not math.isfinite(relative_error)
                        or relative_error > tolerance_fraction
                    )
                )
                rows.append(
                    {
                        "River": str(river),
                        "Reach": str(reach),
                        "RS": str(item.RS),
                        "len_channel_stored": stored,
                        "len_channel_recomputed": recomputed,
                        "delta_channel": (
                            recomputed - stored
                            if math.isfinite(recomputed)
                            else float("nan")
                        ),
                        "relative_error_channel": relative_error,
                        "channel_within_tolerance": within,
                        "reach_end": reach_end,
                        "intersection_count": len(points),
                        "intersection_valid": len(points) == 1,
                        "main_channel_flagged": flagged,
                        "geometry": cut_line,
                    }
                )

        return gpd.GeoDataFrame(
            rows,
            geometry="geometry",
            crs=getattr(xs, "crs", None) or getattr(centerlines, "crs", None),
        )

    @staticmethod
    def _validate_tolerance_fraction(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("tolerance_fraction must be a finite number")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError("tolerance_fraction must be finite")
        if not 0 <= normalized <= 1:
            raise ValueError("tolerance_fraction must be between 0 and 1")
        return normalized

    @staticmethod
    def _relative_length_error(stored: float, recomputed: float) -> float:
        import numpy as np

        if np.isnan(stored) or np.isnan(recomputed):
            return float("nan")
        if stored == 0.0:
            return 0.0 if recomputed == 0.0 else float("inf")
        return abs(recomputed - stored) / abs(stored)

    @staticmethod
    def _augment_reach_length_metrics(audit, tolerance_fraction: float):
        """Add relative overbank-policy and main-channel QA evidence."""
        import numpy as np

        result = audit.copy()
        for side in ("left", "channel", "right"):
            result[f"relative_error_{side}"] = [
                RasGeometryCompute._relative_length_error(stored, recomputed)
                for stored, recomputed in zip(
                    result[f"len_{side}_stored"].astype(float),
                    result[f"len_{side}_recomputed"].astype(float),
                )
            ]
            result[f"{side}_within_tolerance"] = (
                result[f"relative_error_{side}"] <= tolerance_fraction
            ) & ~result["reach_end"]

        for side in ("left", "right"):
            result[f"stored_{side}_vs_channel_relative_difference"] = [
                RasGeometryCompute._relative_length_error(channel, overbank)
                for channel, overbank in zip(
                    result["len_channel_stored"].astype(float),
                    result[f"len_{side}_stored"].astype(float),
                )
            ]

        usable = ~result["reach_end"]
        result["stored_overbanks_differ_from_channel"] = usable & (
            (
                result["stored_left_vs_channel_relative_difference"]
                > tolerance_fraction
            )
            | (
                result["stored_right_vs_channel_relative_difference"]
                > tolerance_fraction
            )
        )
        result["overbank_lengths_within_tolerance"] = usable & (
            result["left_within_tolerance"] & result["right_within_tolerance"]
        )
        result["main_channel_flagged"] = usable & (
            result["relative_error_channel"].isna()
            | np.isinf(result["relative_error_channel"])
            | (result["relative_error_channel"] > tolerance_fraction)
        )
        result.attrs.update(getattr(audit, "attrs", {}))
        result.attrs["tolerance_fraction"] = tolerance_fraction
        return result

    @staticmethod
    def _summarize_flow_path_policy(
        xs_metrics,
        *,
        tolerance_fraction: float,
        source_flow_path_counts: dict[tuple[str, str], int],
    ):
        """Return one conservative policy decision per source river/reach."""
        import pandas as pd

        rows = []
        preserve_policy = "preserve_and_recompute_only_at_join_boundary"
        for (river, reach), group in xs_metrics.groupby(
            ["River", "Reach"], sort=False, dropna=False
        ):
            source_flow_path_count = int(
                source_flow_path_counts.get((str(river), str(reach)), 0)
            )
            source_has_flow_paths = source_flow_path_count >= 2
            usable = group.loc[~group["reach_end"]]
            reasons: list[str] = []
            if usable.empty:
                reasons.append("NO_USABLE_REACH_INTERVALS")
            if bool(usable.get("invalid_recompute", pd.Series(dtype=bool)).any()):
                reasons.append("INVALID_REGENERATED_REACH_LENGTH")
            overbank_match = bool(
                not usable.empty
                and usable["overbank_lengths_within_tolerance"].all()
            )
            if not overbank_match:
                reasons.append("REGENERATED_OVERBANK_LENGTH_MISMATCH")
            stored_overbanks_differ = bool(
                not usable.empty
                and usable["stored_overbanks_differ_from_channel"].any()
            )
            if not source_has_flow_paths and stored_overbanks_differ:
                reasons.append(
                    "MISSING_SOURCE_FLOW_PATHS_WITH_DISTINCT_OVERBANK_LENGTHS"
                )
            recommended = preserve_policy if reasons else "regenerate_and_recompute"

            rows.append(
                {
                    "River": river,
                    "Reach": reach,
                    "source_flow_paths_present": source_has_flow_paths,
                    "source_flow_path_count": int(source_flow_path_count),
                    "interval_count": int(len(usable)),
                    "overbank_match_count": int(
                        usable["overbank_lengths_within_tolerance"].sum()
                    ),
                    "overbank_match_fraction": (
                        float(usable["overbank_lengths_within_tolerance"].mean())
                        if not usable.empty
                        else float("nan")
                    ),
                    "max_relative_error_left": (
                        float(usable["relative_error_left"].max())
                        if not usable.empty
                        else float("nan")
                    ),
                    "max_relative_error_right": (
                        float(usable["relative_error_right"].max())
                        if not usable.empty
                        else float("nan")
                    ),
                    "stored_overbanks_differ_from_channel": (
                        stored_overbanks_differ
                    ),
                    "main_channel_flagged_count": int(
                        usable["main_channel_flagged"].sum()
                    ),
                    "max_relative_error_channel": (
                        float(usable["relative_error_channel"].max())
                        if not usable.empty
                        else float("nan")
                    ),
                    "recommended_policy": recommended,
                    "reason_codes": tuple(dict.fromkeys(reasons)),
                    "tolerance_fraction": tolerance_fraction,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _count_flow_paths_by_reach(flow_paths, xs_metrics) -> dict[tuple[str, str], int]:
        """Associate attribute-free HDF flow paths to reaches spatially."""
        counts: dict[tuple[str, str], int] = {}
        for (river, reach), group in xs_metrics.groupby(
            ["River", "Reach"], sort=False, dropna=False
        ):
            count = 0
            cut_lines = list(group.geometry)
            for path in flow_paths.geometry if not flow_paths.empty else ():
                intersections = sum(path.intersects(cut_line) for cut_line in cut_lines)
                if intersections >= 2:
                    count += 1
            counts[(str(river), str(reach))] = count
        return counts

    @staticmethod
    def _normalize_xs_key(
        value: tuple[str, str, Union[str, float, int]], name: str
    ) -> tuple[str, str, str]:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise TypeError(f"{name} must be a (river, reach, river_station) tuple")
        river, reach, station = value
        return str(river), str(reach), str(station)

    @staticmethod
    def _select_xs_by_key(xs_gdf, key, name: str):
        import re

        river, reach, station = RasGeometryCompute._normalize_xs_key(key, name)
        candidates = xs_gdf.loc[
            (xs_gdf["River"].astype(str) == river)
            & (xs_gdf["Reach"].astype(str) == reach)
        ]
        exact = candidates.loc[candidates["RS"].astype(str) == station]
        if len(exact) == 1:
            return exact.iloc[0]

        def number(value):
            match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value))
            return float(match.group(0)) if match else float("nan")

        target = number(station)
        numeric = candidates.loc[
            candidates["RS"].map(number).map(
                lambda item: math.isfinite(item)
                and math.isfinite(target)
                and abs(item - target) <= 1e-6
            )
        ]
        if len(numeric) == 1:
            return numeric.iloc[0]

        def serialized_match(value):
            """Match a full-precision text RS to HDF's displayed precision."""
            text = str(value).strip()
            match = re.search(
                r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?",
                text,
            )
            if match is None or not math.isfinite(target):
                return False
            token = match.group(0)
            mantissa = re.split(r"[Ee]", token, maxsplit=1)[0]
            if "." not in mantissa:
                return False
            precision = len(mantissa.rsplit(".", 1)[1])
            if precision <= 0:
                return False
            serialized = float(token)
            # Compiled geometry HDF attributes can truncate text-geometry river
            # stations to their displayed decimal precision.  Accept at most
            # one display unit, then retain the exact-one fail-closed rule.
            tolerance = 10.0 ** (-precision) + 1e-12
            return abs(serialized - target) <= tolerance

        serialized = candidates.loc[candidates["RS"].map(serialized_match)]
        if len(serialized) != 1:
            raise ValueError(
                f"{name} {river}/{reach}/{station} resolved "
                f"{len(serialized)} times"
            )
        return serialized.iloc[0]

    @staticmethod
    def _single_intersection_point(first, second, label: str):
        from shapely.geometry import Point

        intersection = first.intersection(second)
        if isinstance(intersection, Point):
            return intersection
        points = []
        if hasattr(intersection, "geoms"):
            points = [geom for geom in intersection.geoms if isinstance(geom, Point)]
        if len(points) != 1:
            raise ValueError(
                f"{label} must have exactly one point intersection; found "
                f"{intersection.geom_type} with {len(points)} point(s)"
            )
        return points[0]

    @staticmethod
    def _line_geometry(geometry, label: str):
        from shapely.geometry import LineString
        from shapely.ops import linemerge

        if isinstance(geometry, LineString):
            return geometry
        merged = linemerge(geometry)
        if not isinstance(merged, LineString):
            raise ValueError(f"{label} must resolve to one continuous LineString")
        return merged

    @staticmethod
    def _empty_join_segments(crs=None):
        import geopandas as gpd

        return gpd.GeoDataFrame(
            columns=[
                "River",
                "Reach",
                "upstream_rs",
                "downstream_rs",
                "side",
                "flow_path_id",
                "length",
                "geometry",
            ],
            geometry="geometry",
            crs=crs,
        )

    @staticmethod
    def _clip_join_flow_path_segments(
        flow_paths,
        xs_gdf,
        centerlines_gdf,
        upstream_key,
        downstream_key,
    ):
        """Clip regenerated LOB/ROB flow paths between adjacent join XSs."""
        import geopandas as gpd
        from shapely.ops import substring

        upstream_key = RasGeometryCompute._normalize_xs_key(
            upstream_key, "join_upstream_xs"
        )
        downstream_key = RasGeometryCompute._normalize_xs_key(
            downstream_key, "join_downstream_xs"
        )
        if upstream_key[:2] != downstream_key[:2]:
            raise ValueError("Join-adjacent cross sections must share river and reach")
        river, reach = upstream_key[:2]
        upstream = RasGeometryCompute._select_xs_by_key(
            xs_gdf, upstream_key, "join_upstream_xs"
        )
        downstream = RasGeometryCompute._select_xs_by_key(
            xs_gdf, downstream_key, "join_downstream_xs"
        )
        centerlines = centerlines_gdf.loc[
            (centerlines_gdf["River Name"].astype(str) == river)
            & (centerlines_gdf["Reach Name"].astype(str) == reach)
        ]
        if len(centerlines) != 1:
            raise ValueError(
                f"Join centerline {river}/{reach} resolved {len(centerlines)} times"
            )
        centerline = RasGeometryCompute._line_geometry(
            centerlines.iloc[0].geometry, "join centerline"
        )
        upstream_cut = RasGeometryCompute._line_geometry(
            upstream.geometry, "upstream join cross section"
        )
        downstream_cut = RasGeometryCompute._line_geometry(
            downstream.geometry, "downstream join cross section"
        )
        upstream_center = RasGeometryCompute._single_intersection_point(
            upstream_cut, centerline, "upstream XS/river"
        )
        downstream_center = RasGeometryCompute._single_intersection_point(
            downstream_cut, centerline, "downstream XS/river"
        )
        upstream_center_measure = upstream_cut.project(upstream_center)
        downstream_center_measure = downstream_cut.project(downstream_center)

        rows = []
        for flow_path in flow_paths.itertuples(index=False):
            path = RasGeometryCompute._line_geometry(
                flow_path.geometry, f"flow path {flow_path.flow_path_id}"
            )
            if not path.intersects(upstream_cut) or not path.intersects(downstream_cut):
                continue
            try:
                upstream_point = RasGeometryCompute._single_intersection_point(
                    path, upstream_cut, f"flow path {flow_path.flow_path_id}/upstream XS"
                )
                downstream_point = RasGeometryCompute._single_intersection_point(
                    path,
                    downstream_cut,
                    f"flow path {flow_path.flow_path_id}/downstream XS",
                )
            except ValueError:
                continue
            upstream_side_measure = upstream_cut.project(upstream_point)
            downstream_side_measure = downstream_cut.project(downstream_point)
            upstream_side = (
                "left"
                if upstream_side_measure < upstream_center_measure
                else "right"
                if upstream_side_measure > upstream_center_measure
                else "center"
            )
            downstream_side = (
                "left"
                if downstream_side_measure < downstream_center_measure
                else "right"
                if downstream_side_measure > downstream_center_measure
                else "center"
            )
            if upstream_side not in {"left", "right"} or upstream_side != downstream_side:
                continue
            start = path.project(upstream_point)
            end = path.project(downstream_point)
            segment = substring(path, min(start, end), max(start, end))
            rows.append(
                {
                    "River": river,
                    "Reach": reach,
                    "upstream_rs": upstream_key[2],
                    "downstream_rs": downstream_key[2],
                    "side": upstream_side,
                    "flow_path_id": int(flow_path.flow_path_id),
                    "length": float(segment.length),
                    "geometry": segment,
                }
            )

        result = gpd.GeoDataFrame(
            rows,
            geometry="geometry",
            crs=getattr(flow_paths, "crs", None),
        )
        counts = result["side"].value_counts().to_dict() if not result.empty else {}
        if counts != {"left": 1, "right": 1}:
            raise ValueError(
                "Regenerated join flow paths must resolve exactly one left and one "
                f"right segment; found {counts}"
            )
        return result.sort_values("side").reset_index(drop=True)

    @staticmethod
    def _remove_reach_audit_copy(path: Path) -> None:
        """Remove only a verified audit directory created by ``mkdtemp``."""
        path = Path(path).resolve(strict=False)
        temp_dir = Path(tempfile.gettempdir()).resolve(strict=False)
        if path.parent != temp_dir or not path.name.startswith("reach_audit_"):
            raise RuntimeError(f"Refusing to remove unverified audit directory: {path}")
        shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _reach_length_diff(stored, recomputed, tolerance: float):
        """Per-XS before/after reach-length comparison as a GeoDataFrame.

        ``stored`` and ``recomputed`` are two reads of the SAME cross-section set
        (recompute changes only the length values), so rows are aligned by
        position rather than an unvalidated key merge; identity and order are
        asserted to catch any mismatch instead of silently dropping/duplicating.
        """
        import numpy as np
        import geopandas as gpd

        if len(stored) != len(recomputed):
            raise ValueError(
                f"Reach-length audit: stored ({len(stored)}) and recomputed "
                f"({len(recomputed)}) cross-section counts differ; cannot align")

        sides = [("left", "Len Left"), ("channel", "Len Channel"), ("right", "Len Right")]
        s = stored.reset_index(drop=True)
        r = recomputed.reset_index(drop=True)
        for col in ("River", "Reach", "RS"):
            if not (s[col].astype(str).values == r[col].astype(str).values).all():
                raise ValueError(
                    "Reach-length audit: cross-section identity/order differs between "
                    "the stored and recomputed reads; cannot align")

        rows = []
        for i in range(len(s)):
            srow, rrow = s.iloc[i], r.iloc[i]
            rec = {"River": srow["River"], "Reach": srow["Reach"], "RS": srow["RS"]}
            changed_any = False
            nan_sides = 0
            for name, col in sides:
                sv = float(srow[col])
                rv = float(rrow[col])
                rec[f"len_{name}_stored"] = sv
                rec[f"len_{name}_recomputed"] = rv
                if np.isnan(rv):
                    nan_sides += 1
                if np.isnan(sv) or np.isnan(rv):
                    rec[f"delta_{name}"] = float("nan")
                else:
                    delta = rv - sv
                    rec[f"delta_{name}"] = delta
                    if abs(delta) > tolerance:
                        changed_any = True
            # All recomputed sides NaN => the downstream-most XS of a reach
            # (no downstream XS); a *partial* NaN means the flow-path intersection
            # failed for that XS and is flagged as an invalid recompute.
            rec["reach_end"] = bool(nan_sides == 3)
            rec["invalid_recompute"] = bool(0 < nan_sides < 3)
            rec["changed"] = bool(changed_any or rec["invalid_recompute"])
            rec["geometry"] = srow["geometry"]
            rows.append(rec)

        return gpd.GeoDataFrame(rows, geometry="geometry",
                                crs=getattr(stored, "crs", None))

    # ------------------------------------------------------------------ #
    #  Diagnostics marshalling
    # ------------------------------------------------------------------ #

    _LEVEL_TO_SEVERITY = {"info": "INFO", "warning": "WARNING", "fatal": "ERROR"}

    @staticmethod
    def _parse_feature_name(name: str):
        """Parse 'River, Reach (RS)' into (River, Reach, RS); else (None, None, None)."""
        import re
        if not name:
            return None, None, None
        m = re.match(r"^\s*(.*?)\s*,\s*(.*?)\s*\(([^)]*)\)\s*$", name)
        if m:
            return m.group(1) or None, m.group(2) or None, m.group(3) or None
        return None, None, None

    @staticmethod
    def _harvest_errors(geom) -> list:
        """Marshal RASGeometry.ValidateGeometry(False) + .Errors into row dicts."""
        rows = []
        try:
            geom.ValidateGeometry(False)
            errors = geom.Errors
            count = int(errors.FeatureCount())
        except Exception as exc:
            logger.error(f"ValidateGeometry failed: {exc}")
            # Fail closed: surface the validator failure as an ERROR row so
            # is_valid_geometry() cannot silently approve the geometry.
            return [{
                "severity": "ERROR", "level": "Fatal", "layer": "<validation>",
                "River": None, "Reach": None, "RS": None, "feature": None,
                "process": "ValidateGeometry",
                "message": f"Geometry validation could not be completed: {exc}",
                "geometry": None,
            }]

        for i in range(count):
            try:
                layer = str(errors.GetLayerName(i))
            except Exception:
                layer = None
            try:
                feature = str(errors.GetFeatureName(i))
            except Exception:
                feature = None
            river, reach, rs = RasGeometryCompute._parse_feature_name(feature or "")

            per_error = []
            try:
                coll = errors.GetErrors(i)
                for err in coll.Errors:
                    per_error.append((str(err.Message), str(err.Process), str(err.Level)))
            except Exception:
                per_error = []

            if not per_error:
                # Fall back to the comma-joined description as a single row.
                try:
                    desc = str(errors.GetDescription(i))
                except Exception:
                    desc = ""
                per_error = [(desc, "", "Fatal")]

            for message, process, level in per_error:
                severity = RasGeometryCompute._LEVEL_TO_SEVERITY.get(level.lower(), "WARNING")
                rows.append({
                    "severity": severity,
                    "level": level,
                    "layer": layer,
                    "River": river,
                    "Reach": reach,
                    "RS": rs,
                    "feature": feature,
                    "process": process,
                    "message": message,
                    "geometry": None,
                })
        return rows

    # ------------------------------------------------------------------ #
    #  Reader shims (used for backups; keep HdfXsec as the public readers)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_edge_lines(geom_hdf_path: Path):
        from .hdf.HdfXsec import HdfXsec
        return HdfXsec.get_river_edge_lines(geom_hdf_path)

    @staticmethod
    def _read_interp_surface(geom_hdf_path: Path):
        from .hdf.HdfXsec import HdfXsec
        return HdfXsec.get_xs_interpolation_surface(geom_hdf_path)

    @staticmethod
    def _read_flow_paths(geom_hdf_path: Path):
        from .hdf.HdfXsec import HdfXsec
        return HdfXsec.get_river_flow_paths(geom_hdf_path)
