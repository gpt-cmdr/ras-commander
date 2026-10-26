"""
Class: HdfFluvialPluvial

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfFluvialPluvial:
- calculate_fluvial_pluvial_boundary(): Returns LineStrings representing the boundary.
- generate_fluvial_pluvial_polygons(): Returns dissolved Polygons for fluvial, pluvial, and ambiguous zones.
- _process_cell_adjacencies()
- _seed_classifications()
- _get_boundary_cell_pairs()
- _identify_boundary_edges()
- _native_boundary() / _native_polygons(): optional Rust execution (engine="native"/"auto")

"""

from fractions import Fraction
from typing import Dict, List, Tuple, Set, Optional
from math import isfinite
import math
import pandas as pd
import geopandas as gpd
from collections import defaultdict
from itertools import combinations
import h5py
import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge
import sys
from tqdm import tqdm
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from .HdfResultsMesh import HdfResultsMesh
from ..LoggingConfig import get_logger
from ..fast_hdf import reraise_required
from ..fast_hdf import backend_scope
from pathlib import Path

logger = get_logger(__name__)
CellKey = Tuple[str, int]

_ENGINES = ("auto", "h5py", "native")


class FluvialNativeUnsupportedError(ValueError):
    """The native kernels cannot reproduce the legacy Python result for this request.

    engine="native" raises it instead of returning different scientific
    results; engine="auto" falls back to the reference on this and on any other
    native error.
    """


def _h5py_scoped():
    """Whether the calling context already forces every native read to h5py."""
    from ..fast_hdf import _BACKEND_SCOPE
    return _BACKEND_SCOPE.get() == "python"


def _check_engine(engine):
    if engine not in _ENGINES:
        raise ValueError(f"engine must be one of {_ENGINES}, got {engine!r}")


def _resolve_engine(engine):
    """Map ``engine`` onto the ``RAS_COMMANDER_FAST_HDF`` backend policy.

    Explicit ``"h5py"`` and ``"native"`` override the environment, as they do
    for the ``HdfMesh`` readers. ``"auto"`` follows the environment:
    ``h5py`` (or legacy ``0``/``off``/``false``/``python``) -> ``"h5py"`` (the reference, no
    native attempt); unset/``auto`` -> ``"auto"`` (native when it reproduces the
    reference, else Python); ``native`` (legacy ``required``/``rust``) -> ``"required"`` (native, or
    :class:`~ras_commander.fast_hdf.FastHdfError`; never a silent fallback).
    """
    _check_engine(engine)
    if engine != "auto":
        return engine
    from ..fast_hdf import _mode
    mode = _mode("auto")
    if mode == "python":
        return "h5py"
    if mode == "rust":
        return "required"
    return "auto"


def _native_fallback(engine, effective, exc):
    """Raise ``exc`` (or FastHdfError in native mode), or log the Python fallback."""
    if effective == "native":
        raise exc
    if effective == "required":
        from ..fast_hdf import FastHdfError
        raise FastHdfError(
            f"RAS_COMMANDER_FAST_HDF=native: engine={engine!r} could not use the native "
            f"fluvial engine: {exc}") from exc
    logger.info(f"engine='auto' selected the Python reference: {exc}")


def _hours_to_ms(value, name):
    """Exact integer milliseconds, or unsupported (thresholds are never rounded)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FluvialNativeUnsupportedError(f"{name} must be a finite number for the native engine")
    if value < 0:
        raise FluvialNativeUnsupportedError(f"negative {name} is not supported by the native engine")
    ms = Fraction(value) * 3_600_000
    if ms.denominator != 1 or ms > 2**64 - 1:
        raise FluvialNativeUnsupportedError(
            f"{name}={value!r} hours is not an exact integer number of milliseconds")
    return int(ms)


def _native_snapshot(hdf_path, retain_faces):
    """Immutable native snapshot built from Python-compatible inputs, or unsupported.

    Several meshes are analysed in isolation under (mesh_name, cell_id)
    identities, as the Python reference keys them; the face graph never
    connects cells of different meshes.
    """
    # Same availability and API-version gate (fast_hdf.API 11) as every other native read.
    from .. import fast_hdf
    module, failure, _ = fast_hdf._load_native()
    if module is None:
        raise FluvialNativeUnsupportedError(f"native fluvial extension unavailable: {failure}")
    try:
        from .HdfFluvialNative import Analysis
    except ImportError as exc:
        raise FluvialNativeUnsupportedError(f"native fluvial extension unavailable: {exc}") from exc
    from pyproj import CRS
    from .HdfBase import HdfBase
    # Validates the file before the CRS probe: corrupt input is fatal, never unsupported.
    counts = HdfBase.get_2d_flow_area_names_and_counts(hdf_path)
    projection = HdfBase.get_projection(hdf_path)
    if not projection or not CRS.from_user_input(projection).is_projected:
        raise FluvialNativeUnsupportedError(f"native engine requires a projected CRS; got {projection!r}")
    # The reference takes adjacency from stored Faces Cell Indexes restricted to
    # the cells HdfMesh.get_mesh_cell_polygons returns. The native graph uses
    # the same faces over the physical cells, so require that both cell sets
    # can coincide: a physical cell needs >= 3 faces to be polygonized, and a
    # non-physical (ghost) cell with >= 3 faces could be. Without the dataset,
    # Python uses its ring-segment fallback, which native does not reproduce.
    with h5py.File(hdf_path, "r") as hdf_file:
        for mesh_name, count in counts or ():
            base = f"Geometry/2D Flow Areas/{mesh_name}"
            face_cells = hdf_file.get(f"{base}/Faces Cell Indexes")
            if face_cells is None or face_cells.ndim != 2 or face_cells.shape[1] < 2:
                raise FluvialNativeUnsupportedError(
                    f"mesh {mesh_name!r} has no Faces Cell Indexes; the Python reference uses "
                    f"its shared-ring-segment fallback adjacency")
            info = hdf_file.get(f"{base}/Cells Face and Orientation Info")
            if info is not None and info.ndim == 2 and info.shape[1] >= 2:
                lengths = np.asarray(info[:, 1], dtype=np.int64)
                count = int(count)
                if (lengths[:count] < 3).any() or (lengths[count:] >= 3).any():
                    raise FluvialNativeUnsupportedError(
                        f"mesh {mesh_name!r}: the physical cells differ from the polygonizable "
                        f"cells the Python reference analyses")
    # Legacy reads peaks with HdfResultsMesh.get_mesh_max_ws's default "100ms".
    analysis = Analysis.from_hdf(hdf_path, wet_policy="all", peak_round_to="100ms",
                                 retain_faces=retain_faces)
    from .HdfFluvialNative import _native
    invalid = _native("validate_geometry", list(analysis.points), list(analysis.rings))
    if invalid:
        # Python dissolves invalid cell polygons with GEOS (and, without stored
        # topology, drops them from adjacency); native polygon assembly cannot
        # reproduce either without guessing.
        raise FluvialNativeUnsupportedError(
            f"{len(invalid)} cell(s) have invalid source geometry, which the native engine "
            f"does not reproduce; e.g. vertices {[index for index, _ in invalid[:5]]}")
    return analysis


_PYTHON_POLICY_REASON = "RAS_COMMANDER_FAST_HDF selects the Python backend"


def _native_diagnostics(frame, keep):
    """Keep attrs["fluvial_native"] only when diagnostics were requested."""
    if not keep:
        frame.attrs.pop("fluvial_native", None)
    return frame


def _engine_attrs(frame, requested, used, reason=None):
    frame.attrs["fluvial_engine"] = {"requested": requested, "used": used, "fallback_reason": reason}
    return frame


class HdfFluvialPluvial:
    """
    A class for analyzing and visualizing fluvial-pluvial boundaries in HEC-RAS 2D model results.

    This class provides methods to process and visualize HEC-RAS 2D model outputs,
    specifically focusing on the delineation of fluvial and pluvial flood areas.
    It includes functionality for calculating fluvial-pluvial boundaries based on
    the timing of maximum water surface elevations.

    Key Concepts:
    - Fluvial flooding: Flooding from rivers/streams
    - Pluvial flooding: Flooding from rainfall/surface water
    - delta_t: Time threshold (in hours) used to distinguish between fluvial and pluvial cells.
               Cells with max WSE time differences greater than delta_t are considered boundaries.

    Data Requirements:
    - HEC-RAS plan HDF file containing:
        - 2D mesh cell geometry (accessed via HdfMesh)
        - Maximum water surface elevation times (accessed via HdfResultsMesh)

    Usage Example:
        >>> from ras_commander import HdfFluvialPluvial
        >>> hdf_path = Path("path/to/plan.hdf")
        
        # To get just the boundary lines
        >>> boundary_lines_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
        ...     hdf_path, 
        ...     delta_t=12
        ... )
        
        # To get classified flood polygons
        >>> flood_polygons_gdf = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        ...     hdf_path,
        ...     delta_t=12,
        ...     temporal_tolerance_hours=1.0
        ... )
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def calculate_fluvial_pluvial_boundary(
        hdf_path: Path, 
        delta_t: float = 12,
        min_line_length: Optional[float] = None,
        *,
        engine: str = "auto",
        diagnostics: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary lines based on cell polygons and maximum water surface elevation times.

        This function is useful for visualizing the line of transition between flooding mechanisms.

        Cell identity is scoped by ``(mesh_name, cell_id)``. Adjacency never
        crosses mesh boundaries, even when coordinates or native IDs coincide.
        Processing failures log contextual ERROR with traceback and return an empty
        GeoDataFrame, discarding partial output. A successful analysis with no
        qualifying edges also returns empty. Input/decorator validation can raise.

        The result depends only on the stored mesh and results, never on cell
        polygon row order, ring direction or ring start vertex. Adjacency comes
        from the stored ``Faces Cell Indexes`` topology (with an order-invariant
        shared-ring-segment fallback when that dataset is absent). There is one
        line per boundary cell pair, in sorted ``(mesh_name, cell_id)`` pair
        order. Each line holds every face the two cells share, with the stored
        face coordinates (a MultiLineString if the shared faces are not
        contiguous).

        Behavior change (after v0.106.1): earlier releases kept only the last ring
        segment of a shared face, so a curved face could yield a fragment that
        varied with polygon order, and coordinates were rounded to 8 decimals.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.
            delta_t (float): Threshold time difference in hours. Cells with time differences
                             greater than this value are considered boundaries. Default is 12 hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).
            engine (str): "auto" (default): the native Rust graph and threshold kernels when
                          they reproduce the reference result, otherwise the reference
                          implementation; which one ran is recorded in
                          ``result.attrs["fluvial_engine"]``. "h5py": the reference
                          implementation only (h5py reads, no native attempt). "native":
                          native or an error (FluvialNativeUnsupportedError or data
                          errors), never a different result. Native output holds the same
                          lines, row order (sorted cell pairs) and CRS as the reference.
                          ``engine="auto"`` follows ``RAS_COMMANDER_FAST_HDF`` like every
                          other reader: ``h5py`` runs the reference without trying native;
                          unset/``auto`` tries native and falls back; ``native`` runs native
                          or raises ``FastHdfError``. Explicit ``"h5py"``/``"native"`` ignore
                          the environment. Native is used only when ``fast_hdf.available()``
                          (a compatible extension) is true. With ``engine="h5py"`` under
                          ``RAS_COMMANDER_FAST_HDF=native`` a routed read's ``FastHdfError``
                          is re-raised instead of returning an empty result.
            diagnostics (bool): Attach ``result.attrs["fluvial_native"]`` (native kernel
                          timings and classification/geometry counts) when the native
                          engine produced the result. Default False, so results carry the
                          same attributes whichever engine ran. Ignored by the reference.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundary lines.
        """
        effective = _resolve_engine(engine)
        if engine == "h5py" and not _h5py_scoped():
            # The reference with every nested read on h5py, in any mode.
            with backend_scope("h5py"):
                return HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
                    hdf_path, delta_t, min_line_length, engine="h5py")
        if effective != "h5py":
            try:
                result = HdfFluvialPluvial._native_boundary(hdf_path, delta_t, min_line_length)
                return _engine_attrs(_native_diagnostics(result, diagnostics), engine, "native")
            except Exception as exc:
                # Auto must give the reference outcome (main logs processing failures
                # and returns an empty frame), so any native exception falls back;
                # explicit native/required only treat unsupported inputs specially.
                if effective != "auto" and not isinstance(exc, FluvialNativeUnsupportedError):
                    raise
                _native_fallback(engine, effective, exc)
                result = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
                    hdf_path, delta_t, min_line_length, engine="h5py")
                return _engine_attrs(result, engine, "h5py", str(exc))
        if engine == "auto":
            result = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
                hdf_path, delta_t, min_line_length, engine="h5py")
            return _engine_attrs(result, engine, "h5py", _PYTHON_POLICY_REASON)
        stage = "data loading"
        try:
            logger.debug("Getting cell polygons from HDF file...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            if cell_polygons_gdf.empty:
                raise ValueError("No cell polygons found in HDF file")

            logger.debug("Getting maximum water surface data from HDF file...")
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path, include_geometry=False)
            if max_ws_df.empty:
                raise ValueError("No maximum water surface data found in HDF file")

            logger.debug("Converting maximum water surface timestamps...")
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )

            stage = "adjacency"
            logger.debug("Processing cell adjacencies...")
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(
                cell_polygons_gdf, hdf_path=hdf_path
            )

            stage = "time lookup"
            logger.debug("Extracting cell times from maximum water surface data...")
            times = max_ws_df.set_index(['mesh_name', 'cell_id'])['maximum_water_surface_time']
            if not times.index.is_unique:
                raise ValueError("Duplicate mesh/cell identities in maximum water surface data")
            cell_times = times.to_dict()

            stage = "boundary edges"
            logger.debug("Identifying boundary edges...")
            boundary_edges = HdfFluvialPluvial._identify_boundary_edges(
                cell_adjacency, common_edges, cell_times, delta_t, min_line_length=min_line_length
            )

            stage = "boundary output"
            logger.debug("Creating final GeoDataFrame for boundaries...")
            boundary_gdf = gpd.GeoDataFrame(
                geometry=boundary_edges, 
                crs=cell_polygons_gdf.crs
            )

            filter_text = f", min_line_length={min_line_length}" if min_line_length is not None else ""
            logger.info(
                f"Fluvial/pluvial boundary: {len(boundary_gdf)} line(s), delta_t={delta_t} hr{filter_text}."
            )
            return boundary_gdf

        except Exception as e:
            reraise_required(e)
            logger.error(
                f"Error calculating fluvial-pluvial boundary lines for {hdf_path} "
                f"(delta_t={delta_t} hr, min_line_length={min_line_length}, stage={stage}): {str(e)}",
                exc_info=True,
            )
            return gpd.GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def generate_fluvial_pluvial_polygons(
        hdf_path: Path, 
        delta_t: float = 12, 
        temporal_tolerance_hours: float = 1.0,
        min_polygon_area_acres: Optional[float] = None,
        *,
        engine: str = "auto",
        diagnostics: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Generates dissolved polygons representing fluvial, pluvial, and ambiguous flood zones.

        This function classifies each wetted cell and merges them into three distinct regions
        based on the timing of maximum water surface elevation.

        Times, adjacency and classifications retain ``(mesh_name, cell_id)``
        identity. Dissolved regions remain separate per mesh and classification;
        native cell IDs are not renumbered. Processing failures log contextual ERROR
        with traceback and return an empty GeoDataFrame, discarding partial output.
        Existing input/decorator validation exceptions can still raise.

        Classification depends only on the stored mesh and results, never on
        cell polygon row order, ring direction or ring start vertex:

        - Adjacency comes from the stored ``Faces Cell Indexes`` topology, with
          an order-invariant shared-ring-segment fallback when it is absent.
        - Seeding: for each adjacent pair whose max-WSE times differ by at least
          ``delta_t``, the later-peaking cell is evidence for ``fluvial`` and
          the earlier one for ``pluvial``. A cell with evidence for both (it is
          in several competing pairs) is seeded ``ambiguous`` and does not grow.
          Equal times (possible only when ``delta_t <= 0``) seed nothing.
        - Region growth is simultaneous per iteration; a cell reached by both
          fronts in the same iteration is ``ambiguous``.
        - Cells are dissolved in sorted ``(mesh_name, cell_id)`` order with
          normalized rings, so the ``cell_id`` column (the smallest cell in the
          class) and the geometry are reproducible.

        Behavior change (after v0.106.1): earlier releases seeded pairs in adjacency
        order and let the last pair win, so a cell in competing pairs took an
        arbitrary label. Reordering identical polygons moved up to 55,000 sq ft
        between classes on AustinOyster at ``delta_t=1``. Results now change
        once to the order-invariant rule; see the release notes.

        Optionally, for polygons classified as fluvial or pluvial, if their area is less than
        min_polygon_area_acres, they are reclassified to the opposite type and merged with
        adjacent polygons of that type. Ambiguous polygons are exempt from this logic.
        Acreage uses the projected CRS axis units converted to square meters.
        Missing or geographic CRS skips filtering with a warning. Unresolved
        projected units or other processing failures log a contextual ERROR with
        traceback and return an empty GeoDataFrame; partial geometry is discarded.
        Input validation performed by the input decorator can still raise.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.
            delta_t (float): The time difference (in hours) between adjacent cells that defines
                             the initial boundary between fluvial and pluvial zones. Default is 12.
            temporal_tolerance_hours (float): The maximum time difference (in hours) for a cell
                                              to be considered part of an expanding region. 
                                              Default is 1.0.
            min_polygon_area_acres (float, optional): Minimum polygon area (in acres). For fluvial or pluvial
                                                      polygons smaller than this, reclassify to the opposite
                                                      type and merge with adjacent polygons of that type.
                                                      Ambiguous polygons are not affected.
            engine (str): "auto" (default): the native Rust graph and threshold kernels when
                          they reproduce the reference result, otherwise the reference
                          implementation; which one ran is recorded in
                          ``result.attrs["fluvial_engine"]``. "h5py": the reference
                          implementation only (h5py reads, no native attempt). "native":
                          native or an error (FluvialNativeUnsupportedError or data
                          errors), never a different result. Native output holds the same
                          rows, attributes and CRS as the reference with topologically
                          equal polygons; with ``min_polygon_area_acres`` native classes go
                          through the reference dissolve and swap, so the frame is
                          identical to the reference's.
                          ``engine="auto"`` follows ``RAS_COMMANDER_FAST_HDF`` like every
                          other reader: ``h5py`` runs the reference without trying native;
                          unset/``auto`` tries native and falls back; ``native`` runs native
                          or raises ``FastHdfError``. Explicit ``"h5py"``/``"native"`` ignore
                          the environment. Native is used only when ``fast_hdf.available()``
                          (a compatible extension) is true. With ``engine="h5py"`` under
                          ``RAS_COMMANDER_FAST_HDF=native`` a routed read's ``FastHdfError``
                          is re-raised instead of returning an empty result.
            diagnostics (bool): Attach ``result.attrs["fluvial_native"]`` (native kernel
                          timings and classification/geometry counts) when the native
                          engine produced the result. Default False, so results carry the
                          same attributes whichever engine ran. Ignored by the reference.

        Returns:
            gpd.GeoDataFrame: A GeoDataFrame with dissolved polygons for 'fluvial', 'pluvial',
                              and 'ambiguous' zones. Processing failure returns an empty
                              GeoDataFrame; partial geometry is never returned as complete.

        Raises:
            Exception: Existing input/decorator validation errors are not suppressed.
            FastHdfError: Only under ``RAS_COMMANDER_FAST_HDF=native`` (legacy ``required``; see ``engine``).
        """
        effective = _resolve_engine(engine)
        if engine == "h5py" and not _h5py_scoped():
            # The reference with every nested read on h5py, in any mode.
            with backend_scope("h5py"):
                return HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
                    hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                    engine="h5py")
        if effective != "h5py":
            try:
                result = HdfFluvialPluvial._native_polygons(
                    hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres)
                return _engine_attrs(_native_diagnostics(result, diagnostics), engine, "native")
            except Exception as exc:
                # Auto must give the reference outcome (main logs processing failures
                # and returns an empty frame), so any native exception falls back;
                # explicit native/required only treat unsupported inputs specially.
                if effective != "auto" and not isinstance(exc, FluvialNativeUnsupportedError):
                    raise
                _native_fallback(engine, effective, exc)
                result = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
                    hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                    engine="h5py")
                return _engine_attrs(result, engine, "h5py", str(exc))
        if engine == "auto":
            result = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
                hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                engine="h5py")
            return _engine_attrs(result, engine, "h5py", _PYTHON_POLICY_REASON)
        stage = "data loading"
        try:
            # --- 1. Data Loading and Preparation ---
            logger.debug("Loading mesh and results data...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path, include_geometry=False)
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )
            times = max_ws_df.set_index(['mesh_name', 'cell_id'])['maximum_water_surface_time']
            if not times.index.is_unique:
                raise ValueError("Duplicate mesh/cell identities in maximum water surface data")
            cell_times = times.to_dict()
            
            stage = "adjacency"
            logger.debug("Processing cell adjacencies...")
            cell_adjacency, _ = HdfFluvialPluvial._process_cell_adjacencies(
                cell_polygons_gdf, hdf_path=hdf_path, include_edges=False
            )

            stage = "seeding"
            # --- 2. Seeding the Classifications ---
            logger.debug(f"Identifying initial boundary seeds with delta_t = {delta_t} hours...")
            boundary_pairs = HdfFluvialPluvial._get_boundary_cell_pairs(cell_adjacency, cell_times, delta_t)

            cell_index = pd.MultiIndex.from_frame(cell_polygons_gdf[['mesh_name', 'cell_id']])
            if not cell_index.is_unique:
                raise ValueError("Duplicate mesh/cell identities in cell polygons")
            classifications = pd.Series('unclassified', index=cell_index, name='classification')
            seeds = HdfFluvialPluvial._seed_classifications(boundary_pairs, cell_times)
            if seeds:
                classifications.loc[list(seeds)] = list(seeds.values())
            
            stage = "region growth"
            # --- 3. Iterative Region Growth ---
            logger.debug(f"Starting iterative region growth with tolerance = {temporal_tolerance_hours} hours...")
            fluvial_frontier = set(classifications[classifications == 'fluvial'].index)
            pluvial_frontier = set(classifications[classifications == 'pluvial'].index)
            
            iteration = 0
            show_progress = getattr(sys.stderr, "isatty", lambda: False)()
            with tqdm(
                desc="Region Growing",
                unit="iter",
                leave=False,
                mininterval=1.0,
                disable=not show_progress,
            ) as pbar:
                while fluvial_frontier or pluvial_frontier:
                    iteration += 1
                    
                    next_fluvial_candidates = set()
                    for cell_id in fluvial_frontier:
                        for neighbor_id in cell_adjacency.get(cell_id, []):
                            if classifications.loc[neighbor_id] == 'unclassified' and pd.notna(cell_times.get(neighbor_id)):
                                time_diff_seconds = abs((cell_times[cell_id] - cell_times[neighbor_id]).total_seconds())
                                if time_diff_seconds <= temporal_tolerance_hours * 3600:
                                    next_fluvial_candidates.add(neighbor_id)
                    
                    next_pluvial_candidates = set()
                    for cell_id in pluvial_frontier:
                        for neighbor_id in cell_adjacency.get(cell_id, []):
                            if classifications.loc[neighbor_id] == 'unclassified' and pd.notna(cell_times.get(neighbor_id)):
                                time_diff_seconds = abs((cell_times[cell_id] - cell_times[neighbor_id]).total_seconds())
                                if time_diff_seconds <= temporal_tolerance_hours * 3600:
                                    next_pluvial_candidates.add(neighbor_id)
                    
                    # Resolve conflicts
                    ambiguous_cells = next_fluvial_candidates.intersection(next_pluvial_candidates)
                    if ambiguous_cells:
                        classifications.loc[list(ambiguous_cells)] = 'ambiguous'
                        
                    # Classify non-conflicted cells
                    newly_fluvial = next_fluvial_candidates - ambiguous_cells
                    if newly_fluvial:
                        classifications.loc[list(newly_fluvial)] = 'fluvial'

                    newly_pluvial = next_pluvial_candidates - ambiguous_cells
                    if newly_pluvial:
                        classifications.loc[list(newly_pluvial)] = 'pluvial'
                    
                    # Update frontiers for the next iteration
                    fluvial_frontier = newly_fluvial
                    pluvial_frontier = newly_pluvial
                                        
                    pbar.update(1)
                    pbar.set_postfix({
                        "Fluvial": len(fluvial_frontier), 
                        "Pluvial": len(pluvial_frontier),
                        "Ambiguous": len(ambiguous_cells)
                    })
            
            logger.debug(f"Region growing completed in {iteration} iterations.")
            
            stage = "dissolve"
            # --- 4. Finalization and Dissolving ---
            # Classify any remaining unclassified (likely isolated) cells as ambiguous
            classifications[classifications == 'unclassified'] = 'ambiguous'
            final_regions_gdf = HdfFluvialPluvial._dissolve_classified_cells(
                cell_polygons_gdf, classifications)

            stage = "acreage filtering"
            # --- 5. Minimum Polygon Area Filtering and Merging (if requested) ---
            final_regions_gdf = HdfFluvialPluvial._swap_small_polygons(
                final_regions_gdf, min_polygon_area_acres)

            stage = "summary"
            HdfFluvialPluvial._log_polygon_summary(
                final_regions_gdf, delta_t, temporal_tolerance_hours, iteration)
            return final_regions_gdf
            
        except Exception as e:
            reraise_required(e)
            logger.error(
                f"Error generating fluvial-pluvial polygons for {hdf_path} "
                f"(delta_t={delta_t} hr, tolerance={temporal_tolerance_hours} hr, "
                f"min_polygon_area_acres={min_polygon_area_acres}, stage={stage}): {str(e)}",
                exc_info=True,
            )
            return gpd.GeoDataFrame()

    @staticmethod
    def _dissolve_classified_cells(cell_polygons_gdf, classifications):
        """Per-mesh, per-class dissolve of the cell polygons, shared by every engine.

        ``classifications`` is indexed by ``(mesh_name, cell_id)``. Rows are
        dissolved in a canonical presentation (sorted rows, normalized rings),
        so the output geometry, its GEOS part order and the 'first' cell_id
        do not depend on the input row order or ring presentation.
        """
        logger.debug("Merging classifications with cell polygons...")
        classified_gdf = cell_polygons_gdf.merge(
            classifications.to_frame(), left_on=['mesh_name', 'cell_id'],
            right_index=True, validate='one_to_one',
        )
        classified_gdf = classified_gdf.sort_values(['mesh_name', 'cell_id'], kind='stable')
        classified_gdf = classified_gdf.set_geometry(
            shapely.normalize(classified_gdf.geometry.values), crs=classified_gdf.crs
        )

        logger.debug("Dissolving polygons by classification...")
        return classified_gdf.dissolve(by=['mesh_name', 'classification'], aggfunc='first').reset_index()

    @staticmethod
    def _swap_small_polygons(final_regions_gdf, min_polygon_area_acres):
        """Minimum-area class swap within each mesh, shared unchanged by every engine.

        Acreage uses the projected CRS axis units converted to square meters;
        unresolved projected units raise ValueError.
        """
        if min_polygon_area_acres is not None:
            logger.debug(f"Applying minimum polygon area filter: {min_polygon_area_acres} acres")
            # Calculate area in acres (1 acre = 4046.8564224 m^2)
            # If CRS is not projected, warn and skip area filtering
            if not final_regions_gdf.crs or not final_regions_gdf.crs.is_projected:
                logger.warning(
                    f"CRS is not projected ({final_regions_gdf.crs}); "
                    f"skipped area filter min_polygon_area_acres={min_polygon_area_acres}."
                )
            else:
                axes = final_regions_gdf.crs.axis_info[:2]
                if len(axes) != 2 or any(
                    not axis.unit_name or axis.unit_name.lower() == 'unknown'
                    or axis.unit_conversion_factor is None
                    or not isfinite(axis.unit_conversion_factor)
                    or axis.unit_conversion_factor <= 0
                    for axis in axes
                ):
                    raise ValueError(
                        "Acre filtering requires known projected horizontal CRS units"
                    )
                square_metres_per_native_area = (
                    axes[0].unit_conversion_factor * axes[1].unit_conversion_factor
                )
                # Explode to individual polygons for area filtering
                exploded = final_regions_gdf.explode(index_parts=False, ignore_index=True)
                exploded['area_acres'] = (
                    exploded.geometry.area * square_metres_per_native_area / 4046.8564224
                )

                # Only consider fluvial and pluvial polygons for area filtering
                mask_fluvial = (exploded['classification'] == 'fluvial') & (exploded['area_acres'] < min_polygon_area_acres)
                mask_pluvial = (exploded['classification'] == 'pluvial') & (exploded['area_acres'] < min_polygon_area_acres)

                n_fluvial = mask_fluvial.sum()
                n_pluvial = mask_pluvial.sum()
                logger.debug(f"Found {n_fluvial} small fluvial and {n_pluvial} small pluvial polygons to reclassify.")

                # Reclassify small fluvial polygons as pluvial, and small pluvial polygons as fluvial
                exploded.loc[mask_fluvial, 'classification'] = 'pluvial'
                exploded.loc[mask_pluvial, 'classification'] = 'fluvial'
                # Ambiguous polygons are not changed

                # Redissolve by classification to merge with adjacent polygons of the same type
                final_regions_gdf = exploded.dissolve(by=['mesh_name', 'classification'], aggfunc='first').reset_index()
                logger.debug("Redissolved polygons after reclassification of small areas.")
        return final_regions_gdf

    @staticmethod
    def _log_polygon_summary(final_regions_gdf, delta_t, temporal_tolerance_hours, iteration):
        component_counts = (
            final_regions_gdf.explode(index_parts=False)
            .groupby("classification", sort=True)
            .size()
            .to_dict()
        )
        class_summary = ", ".join(f"{label}: {count}" for label, count in component_counts.items())
        logger.info(
            f"Fluvial/pluvial polygons: {len(final_regions_gdf)} dissolved class(es), "
            f"delta_t={delta_t} hr, tolerance={temporal_tolerance_hours} hr, "
            f"iterations={iteration}, components={class_summary}."
        )

    @staticmethod
    def _native_polygons(hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres):
        """Rust classification and polygon assembly reproducing the Python result.

        The native kernel applies the reference's order-invariant rules
        directly: in each boundary pair the later-peaking cell is fluvial
        evidence and the earlier one pluvial; a cell with both is seeded
        ambiguous and does not grow. Synchronous growth, ambiguity and
        missing-time barriers match the Python loop, and unclassified or
        missing-time cells become 'ambiguous' as in Python. The one rule the
        kernel does not share is equal-time pairs (Python seeds nothing, the
        kernel seeds them ambiguous); they can only qualify when delta_t is 0,
        which is therefore unsupported here.

        With ``min_polygon_area_acres`` the reference's minimum-area swap keeps
        a 'first' ``area_acres`` (and ``cell_id``) chosen by the GEOS part order
        of the reference dissolve, which native ring assembly does not share.
        The native classification is then dissolved by the reference's own
        ``_dissolve_classified_cells`` over the same h5py cell polygons and
        swapped by the reference's ``_swap_small_polygons``, so the frame the
        swap receives, and therefore the result, is identical to the
        reference's. Native polygon assembly is not used in that case.
        """
        import time
        from shapely.geometry import MultiPolygon
        delta_ms = _hours_to_ms(delta_t, "delta_t")
        tolerance_ms = _hours_to_ms(temporal_tolerance_hours, "temporal_tolerance_hours")
        if delta_ms == 0:
            raise FluvialNativeUnsupportedError(
                "delta_t=0 qualifies equal-time pairs, which Python does not seed but the "
                "native kernel seeds ambiguous")
        timings = {}
        begin = time.perf_counter()
        analysis = _native_snapshot(hdf_path, retain_faces=False)
        timings["snapshot_seconds"] = time.perf_counter() - begin
        # No seed overrides: conflicting seeds stay ambiguous, as in the reference.
        labels, diagnostics, timings["classify_kernel_seconds"] = analysis.classify(delta_ms, tolerance_ms)
        if diagnostics["label_4"] or diagnostics["label_5"]:
            raise ValueError("unexpected invalid/dry labels under strict, all-wet native analysis")
        # Python's finalization: remaining unclassified (incl. missing time) -> ambiguous.
        final = [3 if label in (0, 6) else label for label in labels]
        names = {1: "fluvial", 2: "pluvial", 3: "ambiguous"}
        if min_polygon_area_acres is not None:
            return HdfFluvialPluvial._native_swapped_polygons(
                hdf_path, analysis, final, names, diagnostics, timings,
                delta_t, temporal_tolerance_hours, min_polygon_area_acres)
        begin = time.perf_counter()
        regions, geometry = analysis.polygons(final)
        timings["polygon_kernel_and_shapely_seconds"] = time.perf_counter() - begin
        begin = time.perf_counter()
        rows = []
        # One row per (mesh, class), each dissolved within its own mesh only, in
        # Python's dissolve(by=['mesh_name', 'classification']) group order.
        for m, mesh_name in sorted(enumerate(analysis.meshes), key=lambda item: item[1]):
            for label in sorted({value for i, value in enumerate(final) if analysis.sources[i][0] == m},
                                key=lambda value: names[value]):
                mask = (regions["classification"] == names[label]) & (regions["mesh_name"] == mesh_name)
                shapes = list(regions.geometry[mask])
                # Python's 'first' aggregation keeps the first cell row of each class.
                first = min(analysis.sources[i][1] for i, value in enumerate(final)
                            if value == label and analysis.sources[i][0] == m)
                rows.append({"mesh_name": mesh_name, "classification": names[label],
                             "geometry": shapes[0] if len(shapes) == 1 else MultiPolygon(shapes),
                             "cell_id": first})
        final_regions_gdf = gpd.GeoDataFrame(rows, columns=["mesh_name", "classification", "geometry", "cell_id"],
                                             geometry="geometry", crs=analysis.crs)
        timings["python_frame_assembly_seconds"] = time.perf_counter() - begin
        HdfFluvialPluvial._log_polygon_summary(
            final_regions_gdf, delta_t, temporal_tolerance_hours, diagnostics["waves"])
        final_regions_gdf.attrs["fluvial_native"] = {
            "classification": dict(diagnostics), "geometry": dict(geometry), "timings": timings,
            "snapshot_setup": {k: v for k, v in analysis.setup.items() if k != "topology_diagnostics"},
        }
        return final_regions_gdf

    @staticmethod
    def _native_swapped_polygons(hdf_path, analysis, final, names, diagnostics, timings,
                                 delta_t, temporal_tolerance_hours, min_polygon_area_acres):
        """Native classes, then the reference dissolve and minimum-area swap.

        The cell polygons are read exactly as the reference reads them (h5py
        ``HdfMesh.get_mesh_cell_polygons``) and the classification Series is
        indexed by that frame's ``(mesh_name, cell_id)`` rows, as in the
        reference, so ``_dissolve_classified_cells`` and ``_swap_small_polygons``
        receive the same inputs as under ``engine="h5py"``.
        """
        import time
        begin = time.perf_counter()
        with backend_scope("h5py"):
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
        cell_index = pd.MultiIndex.from_frame(cell_polygons_gdf[['mesh_name', 'cell_id']])
        if not cell_index.is_unique:
            raise ValueError("Duplicate mesh/cell identities in cell polygons")
        native = {(analysis.meshes[mesh], int(cell)): names[label]
                  for (mesh, cell), label in zip(analysis.sources, final)}
        if len(native) != len(final) or set(cell_index) != set(native):
            raise FluvialNativeUnsupportedError(
                "the native cells differ from the cell polygons the Python reference dissolves")
        classifications = pd.Series([native[key] for key in cell_index], index=cell_index,
                                    name='classification', dtype=object)
        final_regions_gdf = HdfFluvialPluvial._dissolve_classified_cells(
            cell_polygons_gdf, classifications)
        timings["reference_dissolve_seconds"] = time.perf_counter() - begin
        begin = time.perf_counter()
        final_regions_gdf = HdfFluvialPluvial._swap_small_polygons(
            final_regions_gdf, min_polygon_area_acres)
        timings["reference_swap_seconds"] = time.perf_counter() - begin
        HdfFluvialPluvial._log_polygon_summary(
            final_regions_gdf, delta_t, temporal_tolerance_hours, diagnostics["waves"])
        final_regions_gdf.attrs["fluvial_native"] = {
            "classification": dict(diagnostics),
            "geometry": {"assembly": "reference_dissolve",
                         "reason": "min_polygon_area_acres swap keeps GEOS part-order 'first' attributes"},
            "timings": timings,
            "snapshot_setup": {k: v for k, v in analysis.setup.items() if k != "topology_diagnostics"},
        }
        return final_regions_gdf

    @staticmethod
    def _native_boundary(hdf_path, delta_t, min_line_length):
        """Rust face graph and threshold predicate reproducing the Python lines.

        As in the reference: one line per qualifying cell pair, in sorted
        ``(mesh_name, cell_id)`` pair order, holding every stored face the two
        cells share (unrounded stored coordinates, line-merged by the same
        ``_merge_shared_pieces`` helper, so a MultiLineString when the shared
        faces are not contiguous).
        """
        import time
        delta_ms = _hours_to_ms(delta_t, "delta_t")
        timings = {}
        begin = time.perf_counter()
        analysis = _native_snapshot(hdf_path, retain_faces=True)
        timings["snapshot_seconds"] = time.perf_counter() - begin
        begin = time.perf_counter()
        edges = analysis.qualifying_edges(delta_ms)
        timings["edge_kernel_seconds"] = time.perf_counter() - begin
        pairs = []
        for i, j in edges:
            (mesh, a), (other, b) = analysis.sources[i], analysis.sources[j]
            if mesh != other:
                raise ValueError(f"native face graph links meshes {mesh} and {other}")
            pairs.append((str(analysis.meshes[mesh]), min(a, b), max(a, b), mesh))
        pairs.sort()
        lines, merged = [], 0
        for _, a, b, mesh in pairs:
            faces = analysis.edge_faces[(mesh, a, b)]
            merged += len(faces) > 1
            lines.append(HdfFluvialPluvial._merge_shared_pieces([coords for _, coords in faces]))
        if min_line_length is not None:
            lines = [line for line in lines if line.length >= min_line_length]
        boundary_gdf = gpd.GeoDataFrame(geometry=lines, crs=analysis.crs)
        boundary_gdf.attrs["fluvial_native"] = {"timings": timings, "multi_face_pairs": merged,
                                                "qualifying_edges": len(edges)}
        logger.info(f"Fluvial/pluvial boundary (native): {len(boundary_gdf)} line(s), delta_t={delta_t} hr.")
        return boundary_gdf

    @staticmethod
    def _process_cell_adjacencies(
        cell_polygons_gdf: gpd.GeoDataFrame,
        hdf_path: Optional[Path] = None,
        include_edges: bool = True,
    ) -> Tuple[Dict[CellKey, List[CellKey]], Dict[CellKey, Dict[CellKey, BaseGeometry]]]:
        """
        Build cell adjacency and shared edges within each mesh.

        The result depends only on the stored mesh and on which
        ``(mesh_name, cell_id)`` identities are present in ``cell_polygons_gdf``.
        It never depends on GeoDataFrame row order, ring direction or ring start
        vertex.

        When ``hdf_path`` stores ``Faces Cell Indexes`` for every mesh in the
        frame, adjacency comes from that topology: two present cells are
        neighbors when a stored face joins them, and their shared edge is the
        union of those stored face polylines. Otherwise adjacency falls back to
        exact shared ring segments (rounded to 8 decimals), canonicalised so
        that it is also order-invariant. Neither method crosses meshes.

        Neighbor lists are sorted. A shared edge is the line merge of every
        face (topology) or segment (coordinates) the two cells share, so it is
        a LineString, or a MultiLineString when the shared pieces are not
        contiguous. No shared piece is dropped.
        """
        keys = sorted(
            {(str(mesh), int(cell)) for mesh, cell in zip(
                cell_polygons_gdf['mesh_name'], cell_polygons_gdf['cell_id'])}
        )
        if hdf_path is not None:
            pair_edges = HdfFluvialPluvial._topology_pair_edges(hdf_path, keys, include_edges)
            if pair_edges is None:
                logger.warning(
                    "Faces Cell Indexes unavailable for every mesh in %s; "
                    "using order-invariant shared-ring-segment adjacency.",
                    Path(hdf_path).name,
                )
        else:
            pair_edges = None
        if pair_edges is None:
            pair_edges = HdfFluvialPluvial._coordinate_pair_edges(cell_polygons_gdf)

        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)
        for (cell1, cell2) in sorted(pair_edges):
            cell_adjacency[cell1].append(cell2)
            cell_adjacency[cell2].append(cell1)
            if include_edges:
                common_edge = HdfFluvialPluvial._merge_shared_pieces(pair_edges[(cell1, cell2)])
                common_edges[cell1][cell2] = common_edge
                common_edges[cell2][cell1] = common_edge
        for neighbors in cell_adjacency.values():
            neighbors.sort()
        return cell_adjacency, common_edges

    @staticmethod
    def _merge_shared_pieces(pieces: List[Tuple[Tuple[float, float], ...]]) -> BaseGeometry:
        """Line-merge canonically sorted shared pieces into one geometry."""
        lines = [LineString(piece) for piece in sorted(pieces)]
        if len(lines) == 1:
            return lines[0]
        return linemerge(MultiLineString(lines))

    @staticmethod
    def _coordinate_pair_edges(
        cell_polygons_gdf: gpd.GeoDataFrame,
    ) -> Dict[Tuple[CellKey, CellKey], List[Tuple[Tuple[float, float], ...]]]:
        """Map each sorted cell pair to all exact ring segments it shares."""
        edge_to_cells = defaultdict(set)

        def vertex(coord, precision=8):
            return tuple(round(float(value), precision) for value in coord[:2])

        for mesh_name, cell_id, geom in zip(
            cell_polygons_gdf['mesh_name'], cell_polygons_gdf['cell_id'], cell_polygons_gdf.geometry
        ):
            if geom is None or geom.is_empty or not geom.is_valid:
                continue
            coords = list(geom.exterior.coords)
            key_cell = (str(mesh_name), int(cell_id))
            for a, b in zip(coords, coords[1:]):
                a, b = vertex(a), vertex(b)
                if a == b:
                    continue
                edge_to_cells[(key_cell[0], tuple(sorted((a, b))))].add(key_cell)

        pair_edges = defaultdict(list)
        for (_, segment), cells in edge_to_cells.items():
            for cell1, cell2 in combinations(sorted(cells), 2):
                pair_edges[(cell1, cell2)].append(segment)
        return pair_edges

    @staticmethod
    def _topology_pair_edges(
        hdf_path: Path,
        keys: List[CellKey],
        include_edges: bool,
    ) -> Optional[Dict[Tuple[CellKey, CellKey], List[Tuple[Tuple[float, float], ...]]]]:
        """
        Map each sorted pair of present cells to the stored faces joining them.

        Returns None when any mesh in ``keys`` lacks ``Faces Cell Indexes`` (or,
        when edges are requested, face geometry), so the caller can fall back.
        """
        present = defaultdict(set)
        for mesh_name, cell_id in keys:
            present[mesh_name].add(cell_id)
        if not present:
            return {}

        face_cells_by_mesh = {}
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                for mesh_name in sorted(present):
                    path = f"Geometry/2D Flow Areas/{mesh_name}/Faces Cell Indexes"
                    if path not in hdf_file:
                        return None
                    face_cells = np.asarray(hdf_file[path][()])
                    if face_cells.ndim != 2 or face_cells.shape[1] < 2:
                        return None
                    face_cells_by_mesh[mesh_name] = face_cells[:, :2].astype(np.int64)
        except (OSError, KeyError):
            return None

        face_geoms = {}
        if include_edges:
            faces = HdfMesh.get_mesh_cell_faces(hdf_path)
            if faces.empty:
                return None
            faces = faces[faces['mesh_name'].isin(list(present))]
            face_geoms = {
                (str(mesh), int(face)): geom
                for mesh, face, geom in zip(faces['mesh_name'], faces['face_id'], faces.geometry)
            }

        pair_edges = defaultdict(list)
        for mesh_name in sorted(face_cells_by_mesh):
            cells = present[mesh_name]
            face_cells = face_cells_by_mesh[mesh_name]
            for face_id, (cell_a, cell_b) in enumerate(face_cells.tolist()):
                if cell_a == cell_b or cell_a not in cells or cell_b not in cells:
                    continue
                pair = tuple(sorted(((mesh_name, cell_a), (mesh_name, cell_b))))
                if include_edges:
                    geom = face_geoms.get((mesh_name, face_id))
                    if geom is None:
                        return None
                    pair_edges[pair].append(tuple(tuple(map(float, c[:2])) for c in geom.coords))
                else:
                    pair_edges.setdefault(pair, [])
        return pair_edges

    @staticmethod
    def _seed_classifications(
        boundary_pairs: List[Tuple[CellKey, CellKey]],
        cell_times: Dict[CellKey, pd.Timestamp],
    ) -> Dict[CellKey, str]:
        """
        Seed labels from boundary pairs, independent of pair order.

        In each pair the later-peaking cell is evidence for ``fluvial`` and the
        earlier-peaking cell for ``pluvial``. Equal times (possible only when
        ``delta_t <= 0``) are no evidence and seed nothing. A cell whose pairs
        give both labels is seeded ``ambiguous``, the same label region growth
        gives a cell reached by both fronts. Ambiguous seeds do not grow.
        """
        evidence = defaultdict(set)
        for cell1, cell2 in sorted(boundary_pairs):
            time1, time2 = cell_times[cell1], cell_times[cell2]
            if time1 == time2:
                continue
            later, earlier = (cell1, cell2) if time1 > time2 else (cell2, cell1)
            evidence[later].add('fluvial')
            evidence[earlier].add('pluvial')
        return {
            cell: (labels.pop() if len(labels) == 1 else 'ambiguous')
            for cell, labels in sorted(evidence.items())
        }

    @staticmethod
    def _get_boundary_cell_pairs(
        cell_adjacency: Dict[CellKey, List[CellKey]],
        cell_times: Dict[CellKey, pd.Timestamp],
        delta_t: float
    ) -> List[Tuple[CellKey, CellKey]]:
        """
        Identifies pairs of adjacent cell IDs that form a boundary.

        A boundary is defined where the difference in max water surface time
        between two adjacent cells is at least delta_t.

        Args:
            cell_adjacency (Dict[CellKey, List[CellKey]]): Dictionary of cell adjacencies.
            cell_times (Dict[CellKey, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.

        Returns:
            List[Tuple[CellKey, CellKey]]: Unique ``(mesh_name, cell_id)`` pairs, each
                                   sorted and the list sorted, so the result
                                   does not depend on adjacency order.
        """
        boundary_cell_pairs = set()
        delta_t_seconds = delta_t * 3600

        for cell_id, neighbors in cell_adjacency.items():
            time1 = cell_times.get(cell_id)
            if not pd.notna(time1):
                continue

            for neighbor_id in neighbors:
                pair = tuple(sorted((cell_id, neighbor_id)))
                if pair in boundary_cell_pairs:
                    continue

                time2 = cell_times.get(neighbor_id)
                if not pd.notna(time2):
                    continue

                time_diff = abs((time1 - time2).total_seconds())

                if time_diff >= delta_t_seconds:
                    boundary_cell_pairs.add(pair)

        return sorted(boundary_cell_pairs)

    @staticmethod
    def _identify_boundary_edges(
        cell_adjacency: Dict[CellKey, List[CellKey]],
        common_edges: Dict[CellKey, Dict[CellKey, BaseGeometry]],
        cell_times: Dict[CellKey, pd.Timestamp],
        delta_t: float,
        min_line_length: Optional[float] = None
    ) -> List[BaseGeometry]:
        """
        Identify boundary edges between cells with significant time differences.
        
        This function now uses the helper `_get_boundary_cell_pairs`.

        Args:
            cell_adjacency (Dict[CellKey, List[CellKey]]): Dictionary of cell adjacencies.
            common_edges (Dict[CellKey, Dict[CellKey, BaseGeometry]]): Dictionary of shared edges between cells.
            cell_times (Dict[CellKey, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).

        Returns:
            List[BaseGeometry]: One LineString (or MultiLineString when the shared
            faces are not contiguous) per boundary pair, in sorted pair order.
        """
        boundary_pairs = HdfFluvialPluvial._get_boundary_cell_pairs(cell_adjacency, cell_times, delta_t)
        
        boundary_edges = [common_edges[c1][c2] for c1, c2 in boundary_pairs]
        
        logger.debug(f"Identified {len(boundary_edges)} boundary edges using delta_t of {delta_t} hours.")

        if min_line_length is not None:
            filtered_edges = [edge for edge in boundary_edges if edge.length >= min_line_length]
            num_dropped = len(boundary_edges) - len(filtered_edges)
            if num_dropped > 0:
                logger.debug(f"{num_dropped} boundary line(s) shorter than {min_line_length} units were dropped after filtering.")
            boundary_edges = filtered_edges

        return boundary_edges
