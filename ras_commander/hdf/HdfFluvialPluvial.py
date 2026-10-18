"""
Class: HdfFluvialPluvial

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfFluvialPluvial:
- calculate_fluvial_pluvial_boundary(): Returns LineStrings representing the boundary.
- generate_fluvial_pluvial_polygons(): Returns dissolved Polygons for fluvial, pluvial, and ambiguous zones.
- _process_cell_adjacencies()
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
from shapely.geometry import LineString, MultiLineString
import sys
from tqdm import tqdm
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from .HdfResultsMesh import HdfResultsMesh
from ..LoggingConfig import get_logger
from pathlib import Path

logger = get_logger(__name__)
CellKey = Tuple[str, int]

_ENGINES = ("python", "native", "auto")


class FluvialNativeUnsupportedError(ValueError):
    """The native kernels cannot reproduce the legacy Python result for this request.

    engine="native" raises it instead of returning different scientific
    results; engine="auto" catches only this error and uses the Python engine.
    """


def _check_engine(engine):
    if engine not in _ENGINES:
        raise ValueError(f"engine must be one of {_ENGINES}, got {engine!r}")


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


def _native_snapshot(hdf_path, retain_faces, composite_meshes=False):
    """Immutable native snapshot built from legacy-compatible inputs, or unsupported.

    With composite_meshes=True (explicit engine="native" only) several meshes
    are analysed in isolation under (mesh_name, cell_id) identities; the face
    graph never connects cells of different meshes.
    """
    try:
        from .HdfFluvialNative import Analysis
    except ImportError as exc:
        raise FluvialNativeUnsupportedError(f"native fluvial extension unavailable: {exc}") from exc
    from pyproj import CRS
    from .HdfBase import HdfBase
    counts = HdfBase.get_2d_flow_area_names_and_counts(hdf_path)
    if len(counts) > 1 and not composite_meshes:
        # Legacy Python keys cells and peak times by local cell_id alone, so
        # repeated IDs across meshes collide. Composite identities would be
        # different science; HdfFluvialNative.Analysis provides them explicitly.
        raise FluvialNativeUnsupportedError(
            f"legacy cell_id-keyed semantics are undefined for {len(counts)} meshes with "
            "repeated local cell IDs; engine='native' analyses each mesh in isolation instead")
    projection = HdfBase.get_projection(hdf_path)
    if not projection or not CRS.from_user_input(projection).is_projected:
        raise FluvialNativeUnsupportedError(f"native engine requires a projected CRS; got {projection!r}")
    # Legacy reads peaks with HdfResultsMesh.get_mesh_max_ws's default "100ms".
    analysis = Analysis.from_hdf(hdf_path, wet_policy="all", peak_round_to="100ms",
                                 retain_faces=retain_faces)
    from .HdfFluvialNative import _native
    invalid = _native("validate_geometry", list(analysis.points), list(analysis.rings))
    if invalid:
        # Python skips invalid cell polygons when building adjacency (yet keeps
        # them in its dissolve); the native graph would include them.
        raise FluvialNativeUnsupportedError(
            f"{len(invalid)} cell(s) have invalid source geometry, which Python drops from "
            f"its adjacency; e.g. vertices {[index for index, _ in invalid[:5]]}")
    return analysis


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
        engine: str = "python",
    ) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary lines based on cell polygons and maximum water surface elevation times.

        This function is useful for visualizing the line of transition between flooding mechanisms.

        Cell identity is scoped by ``(mesh_name, cell_id)``. Adjacency never
        crosses mesh boundaries, even when coordinates or native IDs coincide.
        Processing failures log contextual ERROR with traceback and return an empty
        GeoDataFrame, discarding partial output. A successful analysis with no
        qualifying edges also returns empty. Input/decorator validation can raise.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.
            delta_t (float): Threshold time difference in hours. Cells with time differences
                             greater than this value are considered boundaries. Default is 12 hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).
            engine (str): "python" (default, unchanged reference implementation),
                          "native" (Rust graph and threshold kernels; never falls back, and
                          raises FluvialNativeUnsupportedError or data errors rather than
                          returning different results), or "auto" (native when it reproduces
                          the Python result, otherwise Python; recorded in
                          ``result.attrs["fluvial_engine"]``). Native output holds the same
                          lines and CRS; rows are sorted by cell pair instead of Python's
                          hash-dependent order. Pairs sharing a curved or multi-face
                          boundary are unsupported natively because Python keeps one
                          order-dependent segment for them.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundary lines.
        """
        _check_engine(engine)
        if engine != "python":
            try:
                result = HdfFluvialPluvial._native_boundary(hdf_path, delta_t, min_line_length,
                                                            composite_meshes=engine == "native")
                return _engine_attrs(result, engine, "native")
            except FluvialNativeUnsupportedError as exc:
                if engine == "native":
                    raise
                logger.info(f"engine='auto' selected the Python reference: {exc}")
                result = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
                    hdf_path, delta_t, min_line_length, engine="python")
                return _engine_attrs(result, engine, "python", str(exc))
        stage = "data loading"
        try:
            logger.debug("Getting cell polygons from HDF file...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            if cell_polygons_gdf.empty:
                raise ValueError("No cell polygons found in HDF file")

            logger.debug("Getting maximum water surface data from HDF file...")
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            if max_ws_df.empty:
                raise ValueError("No maximum water surface data found in HDF file")

            logger.debug("Converting maximum water surface timestamps...")
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )

            stage = "adjacency"
            logger.debug("Processing cell adjacencies...")
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)

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
        engine: str = "python",
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
            engine (str): "python" (default, unchanged reference implementation),
                          "native" (Rust graph, classification and polygon assembly; never
                          falls back), or "auto" (native when it reproduces the Python
                          result, otherwise Python; recorded in
                          ``result.attrs["fluvial_engine"]``). For cells seeded both fluvial
                          and pluvial, the native engine replays Python's own tie-break
                          (Python keeps the last write in its pair order). It raises
                          FluvialNativeUnsupportedError for multiple meshes (Python keys by
                          local cell_id), unprojected CRSs, thresholds that are not exact
                          milliseconds, and any min_polygon_area_acres (the legacy class
                          swap keeps attributes that depend on union part order; polygon
                          removal is not a substitute). Native polygons are topologically
                          equal to Python's; part order inside a MultiPolygon may differ.

        Returns:
            gpd.GeoDataFrame: A GeoDataFrame with dissolved polygons for 'fluvial', 'pluvial',
                              and 'ambiguous' zones. Processing failure returns an empty
                              GeoDataFrame; partial geometry is never returned as complete.

        Raises:
            Exception: Existing input/decorator validation errors are not suppressed.
        """
        _check_engine(engine)
        if engine != "python":
            try:
                result = HdfFluvialPluvial._native_polygons(
                    hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                    composite_meshes=engine == "native")
                return _engine_attrs(result, engine, "native")
            except FluvialNativeUnsupportedError as exc:
                if engine == "native":
                    raise
                logger.info(f"engine='auto' selected the Python reference: {exc}")
                result = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
                    hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                    engine="python")
                return _engine_attrs(result, engine, "python", str(exc))
        stage = "data loading"
        try:
            # --- 1. Data Loading and Preparation ---
            logger.debug("Loading mesh and results data...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )
            times = max_ws_df.set_index(['mesh_name', 'cell_id'])['maximum_water_surface_time']
            if not times.index.is_unique:
                raise ValueError("Duplicate mesh/cell identities in maximum water surface data")
            cell_times = times.to_dict()
            
            stage = "adjacency"
            logger.debug("Processing cell adjacencies...")
            cell_adjacency, _ = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)

            stage = "seeding"
            # --- 2. Seeding the Classifications ---
            logger.debug(f"Identifying initial boundary seeds with delta_t = {delta_t} hours...")
            boundary_pairs = HdfFluvialPluvial._get_boundary_cell_pairs(cell_adjacency, cell_times, delta_t)

            cell_index = pd.MultiIndex.from_frame(cell_polygons_gdf[['mesh_name', 'cell_id']])
            if not cell_index.is_unique:
                raise ValueError("Duplicate mesh/cell identities in cell polygons")
            classifications = pd.Series('unclassified', index=cell_index, name='classification')
            
            for cell1, cell2 in boundary_pairs:
                if cell_times.get(cell1) > cell_times.get(cell2):
                    classifications.loc[cell1] = 'fluvial'
                    classifications.loc[cell2] = 'pluvial'
                else:
                    classifications.loc[cell1] = 'pluvial'
                    classifications.loc[cell2] = 'fluvial'
            
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

            logger.debug("Merging classifications with cell polygons...")
            classified_gdf = cell_polygons_gdf.merge(
                classifications.to_frame(), left_on=['mesh_name', 'cell_id'],
                right_index=True, validate='one_to_one',
            )

            logger.debug("Dissolving polygons by classification...")
            final_regions_gdf = classified_gdf.dissolve(by=['mesh_name', 'classification'], aggfunc='first').reset_index()

            stage = "acreage filtering"
            # --- 5. Minimum Polygon Area Filtering and Merging (if requested) ---
            final_regions_gdf = HdfFluvialPluvial._swap_small_polygons(
                final_regions_gdf, min_polygon_area_acres)

            stage = "summary"
            HdfFluvialPluvial._log_polygon_summary(
                final_regions_gdf, delta_t, temporal_tolerance_hours, iteration)
            return final_regions_gdf
            
        except Exception as e:
            logger.error(
                f"Error generating fluvial-pluvial polygons for {hdf_path} "
                f"(delta_t={delta_t} hr, tolerance={temporal_tolerance_hours} hr, "
                f"min_polygon_area_acres={min_polygon_area_acres}, stage={stage}): {str(e)}",
                exc_info=True,
            )
            return gpd.GeoDataFrame()

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
    def _legacy_replay(hdf_path, analysis, delta_t):
        """Python's own adjacency and boundary-pair order, for its tie-breaks only.

        Python resolves two cases by iteration order rather than by data: a
        cell seeded both fluvial and pluvial keeps its last write, and a
        curved shared face keeps one of its segments. The native engine replays
        exactly these Python routines when (and only when) such cases occur,
        after proving that their adjacency and peak times equal the native
        snapshot's, so every other result still comes from the Rust kernels.
        """
        from .HdfFluvialNative import integer_milliseconds
        all_polygons = HdfMesh.get_mesh_cell_polygons(hdf_path)
        all_max_ws = HdfResultsMesh.get_mesh_max_ws(hdf_path)
        all_max_ws['maximum_water_surface_time'] = all_max_ws['maximum_water_surface_time'].apply(
            lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
        )
        # Python keys cells by local cell_id, so each mesh is replayed on its own
        # rows; results are keyed by (mesh index, cell_id). One mesh is unchanged.
        pairs, common_edges, cell_times, legacy_edges = [], {}, {}, set()
        for m, name in enumerate(analysis.meshes):
            if len(analysis.meshes) == 1:
                polygons, max_ws = all_polygons, all_max_ws
            else:
                polygons = all_polygons[all_polygons['mesh_name'] == name]
                max_ws = all_max_ws[all_max_ws['mesh_name'] == name]
            times = max_ws.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            adjacency, edges = HdfFluvialPluvial._process_cell_adjacencies(polygons)
            pairs.extend(((m, int(a)), (m, int(b)))
                         for a, b in HdfFluvialPluvial._get_boundary_cell_pairs(adjacency, times, delta_t))
            common_edges[m] = edges
            cell_times.update({(m, int(c)): t for c, t in times.items()})
            legacy_edges.update((m, min(int(a), int(b)), max(int(a), int(b)))
                                for a, neighbors in adjacency.items() for b in neighbors)
        vertex = {(m, row): i for i, (m, row) in enumerate(analysis.sources)}
        native_edges = set()
        for i in range(len(analysis.keys)):
            for j in analysis.neighbors[analysis.offsets[i]:analysis.offsets[i + 1]]:
                if i < j:
                    (m, a), (n, b) = analysis.sources[i], analysis.sources[j]
                    if m != n:
                        raise ValueError(f"native face graph links meshes {m} and {n}")
                    native_edges.add((m, min(a, b), max(a, b)))
        if legacy_edges != native_edges:
            raise FluvialNativeUnsupportedError(
                f"Python shared-segment adjacency differs from the native face graph "
                f"({len(legacy_edges - native_edges)} Python-only, "
                f"{len(native_edges - legacy_edges)} native-only pairs)")
        for row, i in vertex.items():
            value, present = integer_milliseconds(cell_times.get(row))
            if present != analysis.present[i] or (present and value != analysis.times[i]):
                raise FluvialNativeUnsupportedError(f"Python peak time differs from native for cell {row}")
        return {"pairs": pairs, "common_edges": common_edges, "cell_times": cell_times, "vertex": vertex}

    @staticmethod
    def _native_polygons(hdf_path, delta_t, temporal_tolerance_hours, min_polygon_area_acres,
                         composite_meshes=False):
        """Rust classification and polygon assembly reproducing the Python result.

        Native seeding equals Python's except for cells that receive both a
        fluvial and a pluvial seed, which Python resolves by last write in its
        hash-dependent pair order; those cells take Python's replayed labels
        through native seed overrides. Synchronous growth, ambiguity and NaN-time
        barriers match the Python loop, and unclassified or missing-time cells
        become 'ambiguous' as in Python.
        """
        import time
        from shapely.geometry import MultiPolygon
        if min_polygon_area_acres is not None:
            # The swap's classes and geometry are reproducible, but Python also
            # keeps a 'first' area_acres attribute chosen by GEOS union part order.
            raise FluvialNativeUnsupportedError(
                "min_polygon_area_acres class swapping keeps Python's union-order-dependent "
                "'first' attributes; it is not reproduced natively (polygon removal is not a substitute)")
        delta_ms = _hours_to_ms(delta_t, "delta_t")
        tolerance_ms = _hours_to_ms(temporal_tolerance_hours, "temporal_tolerance_hours")
        if delta_ms == 0:
            raise FluvialNativeUnsupportedError(
                "delta_t=0 seeds equal-time pairs whose Python labels depend on pair order")
        timings = {}
        begin = time.perf_counter()
        analysis = _native_snapshot(hdf_path, retain_faces=False, composite_meshes=composite_meshes)
        timings["snapshot_seconds"] = time.perf_counter() - begin
        labels, diagnostics, timings["classify_kernel_seconds"] = analysis.classify(delta_ms, tolerance_ms)
        overrides = []
        if diagnostics["conflicting_seeds"]:
            begin = time.perf_counter()
            replay = HdfFluvialPluvial._legacy_replay(hdf_path, analysis, delta_t)
            roles, last = defaultdict(set), {}
            for cell1, cell2 in replay["pairs"]:
                # Same comparison and write order as the Python seeding loop.
                if replay["cell_times"].get(cell1) > replay["cell_times"].get(cell2):
                    fluvial, pluvial = cell1, cell2
                else:
                    fluvial, pluvial = cell2, cell1
                for cell, label in ((fluvial, 1), (pluvial, 2)):
                    roles[cell].add(label)
                    last[cell] = label
            overrides = sorted((replay["vertex"][cell], last[cell]) for cell, seen in roles.items() if len(seen) == 2)
            if len(overrides) != diagnostics["conflicting_seeds"]:
                raise ValueError(f"Python has {len(overrides)} conflicting seeds; native has "
                                 f"{diagnostics['conflicting_seeds']}")
            labels, diagnostics, timings["classify_kernel_seconds"] = analysis.classify(
                delta_ms, tolerance_ms, seed_overrides=overrides)
            timings["python_tie_break_replay_seconds"] = time.perf_counter() - begin
        if diagnostics["label_4"] or diagnostics["label_5"]:
            raise ValueError("unexpected invalid/dry labels under strict, all-wet native analysis")
        # Python's finalization: remaining unclassified (incl. missing time) -> ambiguous.
        final = [3 if label in (0, 6) else label for label in labels]
        begin = time.perf_counter()
        regions, geometry = analysis.polygons(final)
        timings["polygon_kernel_and_shapely_seconds"] = time.perf_counter() - begin
        begin = time.perf_counter()
        names = {1: "fluvial", 2: "pluvial", 3: "ambiguous"}
        rows = []
        # One mesh: one row per class, as Python. Several meshes: one row per
        # (mesh, class), each dissolved within its own mesh only.
        for m, mesh_name in enumerate(analysis.meshes):
            for label in sorted({value for i, value in enumerate(final) if analysis.sources[i][0] == m},
                                key=lambda value: names[value]):
                mask = regions["classification"] == names[label]
                if len(analysis.meshes) > 1:
                    mask &= regions["mesh_name"] == mesh_name
                shapes = list(regions.geometry[mask])
                # Python's 'first' aggregation keeps the first cell row of each class.
                first = min(analysis.sources[i][1] for i, value in enumerate(final)
                            if value == label and analysis.sources[i][0] == m)
                rows.append({"classification": names[label],
                             "geometry": shapes[0] if len(shapes) == 1 else MultiPolygon(shapes),
                             "mesh_name": mesh_name, "cell_id": first})
        final_regions_gdf = gpd.GeoDataFrame(rows, columns=["classification", "geometry", "mesh_name", "cell_id"],
                                             geometry="geometry", crs=analysis.crs)
        timings["python_frame_assembly_seconds"] = time.perf_counter() - begin
        HdfFluvialPluvial._log_polygon_summary(
            final_regions_gdf, delta_t, temporal_tolerance_hours, diagnostics["waves"])
        final_regions_gdf.attrs["fluvial_native"] = {
            "classification": dict(diagnostics), "geometry": dict(geometry), "timings": timings,
            "python_seed_tie_breaks": len(overrides),
            "snapshot_setup": {k: v for k, v in analysis.setup.items() if k != "topology_diagnostics"},
        }
        return final_regions_gdf

    @staticmethod
    def _native_boundary(hdf_path, delta_t, min_line_length, composite_meshes=False):
        """Rust face graph and threshold predicate reproducing the Python lines.

        A straight shared face yields Python's rounded two-point segment directly.
        For a curved or multi-face pair Python keeps one order-dependent segment;
        those pairs take Python's replayed segment (see _legacy_replay).
        """
        import time
        delta_ms = _hours_to_ms(delta_t, "delta_t")
        timings = {}
        begin = time.perf_counter()
        analysis = _native_snapshot(hdf_path, retain_faces=True, composite_meshes=composite_meshes)
        timings["snapshot_seconds"] = time.perf_counter() - begin
        begin = time.perf_counter()
        edges = analysis.qualifying_edges(delta_ms)
        timings["edge_kernel_seconds"] = time.perf_counter() - begin

        def key(coord):  # Python's edge_key rounding (precision=8)
            return tuple(round(value, 8) for value in coord)

        lines, curved = [], []
        for i, j in edges:
            (mesh, a), (_, b) = analysis.sources[i], analysis.sources[j]
            faces = analysis.edge_faces[(mesh, min(a, b), max(a, b))]
            if len(faces) != 1 or len(faces[0][1]) != 2:
                curved.append((len(lines), mesh, a, b))
                lines.append(None)
                continue
            start, end = faces[0][1]
            lines.append(LineString(sorted([key(start), key(end)])))
        if curved:
            begin = time.perf_counter()
            replay = HdfFluvialPluvial._legacy_replay(hdf_path, analysis, delta_t)
            for position, mesh, a, b in curved:
                lines[position] = replay["common_edges"][mesh][a][b]
            timings["python_tie_break_replay_seconds"] = time.perf_counter() - begin
        if min_line_length is not None:
            lines = [line for line in lines if line.length >= min_line_length]
        boundary_gdf = gpd.GeoDataFrame(geometry=lines, crs=analysis.crs)
        boundary_gdf.attrs["fluvial_native"] = {"timings": timings, "python_segment_tie_breaks": len(curved),
                                                "qualifying_edges": len(edges)}
        logger.info(f"Fluvial/pluvial boundary (native): {len(boundary_gdf)} line(s), delta_t={delta_t} hr.")
        return boundary_gdf

    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[CellKey, List[CellKey]], Dict[CellKey, Dict[CellKey, LineString]]]:
        """
        Extract shared edges within each mesh using native mesh/cell identities.
        """
        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)
        edge_to_cells = defaultdict(set)

        def edge_key(coords1, coords2, precision=8):
            coords1 = tuple(round(coord, precision) for coord in coords1)
            coords2 = tuple(round(coord, precision) for coord in coords2)
            return tuple(sorted([coords1, coords2]))

        # iterrows finalizes a Series for every cell and deep-copies frame attrs.
        # Mesh diagnostics contain per-cell records, making that O(N**2).
        # Extract columns once; preserve the caller's geometry and metadata.
        mesh_names = cell_polygons_gdf['mesh_name'].to_numpy(copy=False)
        cell_ids = cell_polygons_gdf['cell_id'].to_numpy(copy=False)
        geometries = cell_polygons_gdf.geometry.array
        for mesh_name, raw_cell_id, geom in zip(mesh_names, cell_ids, geometries):
            cell_id = int(raw_cell_id)
            if geom.is_empty or not geom.is_valid:
                continue
            coords = list(geom.exterior.coords)
            for i in range(len(coords) - 1):
                key = (mesh_name, edge_key(coords[i], coords[i + 1]))
                edge_to_cells[key].add(cell_id)

        for (mesh_name, edge), cells in edge_to_cells.items():
            # Keep the original native-integer pair order within each mesh;
            # tuple hashing must not change boundary-seed precedence.
            cell_list = list(cells)
            if len(cell_list) >= 2:
                for i in range(len(cell_list)):
                    for j in range(i + 1, len(cell_list)):
                        cell1 = (mesh_name, cell_list[i])
                        cell2 = (mesh_name, cell_list[j])
                        cell_adjacency[cell1].append(cell2)
                        cell_adjacency[cell2].append(cell1)
                        common_edge = LineString([edge[0], edge[1]])
                        common_edges[cell1][cell2] = common_edge
                        common_edges[cell2][cell1] = common_edge

        return cell_adjacency, common_edges
    
    @staticmethod
    def _get_boundary_cell_pairs(
        cell_adjacency: Dict[CellKey, List[CellKey]],
        cell_times: Dict[CellKey, pd.Timestamp],
        delta_t: float
    ) -> List[Tuple[CellKey, CellKey]]:
        """
        Identifies pairs of adjacent cell IDs that form a boundary.

        A boundary is defined where the difference in max water surface time
        between two adjacent cells is greater than delta_t.
        
        Args:
            cell_adjacency (Dict[CellKey, List[CellKey]]): Dictionary of cell adjacencies.
            cell_times (Dict[CellKey, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.

        Returns:
            List[Tuple[CellKey, CellKey]]: A list of tuples, where each tuple contains a pair of
                                   cell IDs forming a boundary.
        """
        boundary_cell_pairs = []
        processed_pairs = set()
        delta_t_seconds = delta_t * 3600

        for cell_id, neighbors in cell_adjacency.items():
            time1 = cell_times.get(cell_id)
            if not pd.notna(time1):
                continue

            for neighbor_id in neighbors:
                pair = tuple(sorted((cell_id, neighbor_id)))
                if pair in processed_pairs:
                    continue

                time2 = cell_times.get(neighbor_id)
                if not pd.notna(time2):
                    continue
                
                time_diff = abs((time1 - time2).total_seconds())

                if time_diff >= delta_t_seconds:
                    boundary_cell_pairs.append(pair)
                
                processed_pairs.add(pair)
        
        return boundary_cell_pairs

    @staticmethod
    def _identify_boundary_edges(
        cell_adjacency: Dict[CellKey, List[CellKey]],
        common_edges: Dict[CellKey, Dict[CellKey, LineString]],
        cell_times: Dict[CellKey, pd.Timestamp],
        delta_t: float,
        min_line_length: Optional[float] = None
    ) -> List[LineString]:
        """
        Identify boundary edges between cells with significant time differences.
        
        This function now uses the helper `_get_boundary_cell_pairs`.

        Args:
            cell_adjacency (Dict[CellKey, List[CellKey]]): Dictionary of cell adjacencies.
            common_edges (Dict[CellKey, Dict[CellKey, LineString]]): Dictionary of shared edges between cells.
            cell_times (Dict[CellKey, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).

        Returns:
            List[LineString]: List of LineString geometries representing boundaries.
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
