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

import platform
import threading
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Union

import h5py

from .LoggingConfig import get_logger
from .Decorators import log_call
from .ComputeResults import GeometryLayerResult, GeometryCompleteResult

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
        """Best-effort deterministic release of a .NET RASGeometry object."""
        if geom is None:
            return
        for method in ("Dispose", "Close"):
            try:
                getattr(geom, method)()
            except Exception:
                pass

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
