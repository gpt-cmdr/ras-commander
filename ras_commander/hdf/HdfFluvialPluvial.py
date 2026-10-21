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

"""

from typing import Dict, List, Tuple, Set, Optional
from math import isfinite
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
from pathlib import Path

logger = get_logger(__name__)
CellKey = Tuple[str, int]

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
        min_line_length: Optional[float] = None
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

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundary lines.
        """
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
        min_polygon_area_acres: Optional[float] = None
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

        Returns:
            gpd.GeoDataFrame: A GeoDataFrame with dissolved polygons for 'fluvial', 'pluvial',
                              and 'ambiguous' zones. Processing failure returns an empty
                              GeoDataFrame; partial geometry is never returned as complete.

        Raises:
            Exception: Existing input/decorator validation errors are not suppressed.
        """
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

            logger.debug("Merging classifications with cell polygons...")
            classified_gdf = cell_polygons_gdf.merge(
                classifications.to_frame(), left_on=['mesh_name', 'cell_id'],
                right_index=True, validate='one_to_one',
            )
            # Dissolve a canonical presentation (sorted rows, normalized rings) so
            # the output geometry and the 'first' cell_id do not depend on input order.
            classified_gdf = classified_gdf.sort_values(['mesh_name', 'cell_id'], kind='stable')
            classified_gdf = classified_gdf.set_geometry(
                shapely.normalize(classified_gdf.geometry.values), crs=classified_gdf.crs
            )

            logger.debug("Dissolving polygons by classification...")
            final_regions_gdf = classified_gdf.dissolve(by=['mesh_name', 'classification'], aggfunc='first').reset_index()

            stage = "acreage filtering"
            # --- 5. Minimum Polygon Area Filtering and Merging (if requested) ---
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

            stage = "summary"
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
