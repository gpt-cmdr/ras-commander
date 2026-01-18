"""
Class: HdfFluvialPluvial

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfFluvialPluvial:
- calculate_fluvial_pluvial_boundary(): Returns LineStrings representing the boundary.
- generate_fluvial_pluvial_polygons(): Returns dissolved Polygons for fluvial, pluvial, and ambiguous zones.
- _process_cell_adjacencies()
- _get_boundary_cell_pairs()
- _identify_boundary_edges()

"""

from typing import Dict, List, Tuple, Set, Optional
import pandas as pd
import geopandas as gpd
from collections import defaultdict
from shapely.geometry import LineString, MultiLineString
from tqdm import tqdm
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input
from .HdfResultsMesh import HdfResultsMesh
from ..LoggingConfig import get_logger
from pathlib import Path

logger = get_logger(__name__)

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
    @standardize_input(file_type='plan_hdf')
    def calculate_fluvial_pluvial_boundary(
        hdf_path: Path, 
        delta_t: float = 12,
        min_line_length: Optional[float] = None
    ) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary lines based on cell polygons and maximum water surface elevation times.

        This function is useful for visualizing the line of transition between flooding mechanisms.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.
            delta_t (float): Threshold time difference in hours. Cells with time differences
                             greater than this value are considered boundaries. Default is 12 hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundary lines.
        """
        try:
            logger.info("Getting cell polygons from HDF file...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            if cell_polygons_gdf.empty:
                raise ValueError("No cell polygons found in HDF file")

            logger.info("Getting maximum water surface data from HDF file...")
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            if max_ws_df.empty:
                raise ValueError("No maximum water surface data found in HDF file")

            logger.info("Converting maximum water surface timestamps...")
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )

            logger.info("Processing cell adjacencies...")
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)
            
            logger.info("Extracting cell times from maximum water surface data...")
            cell_times = max_ws_df.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            
            logger.info("Identifying boundary edges...")
            boundary_edges = HdfFluvialPluvial._identify_boundary_edges(
                cell_adjacency, common_edges, cell_times, delta_t, min_line_length=min_line_length
            )

            logger.info("Creating final GeoDataFrame for boundaries...")
            boundary_gdf = gpd.GeoDataFrame(
                geometry=boundary_edges, 
                crs=cell_polygons_gdf.crs
            )

            logger.info("Boundary line calculation completed successfully.")
            return boundary_gdf

        except Exception as e:
            logger.error(f"Error calculating fluvial-pluvial boundary lines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
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

        Optionally, for polygons classified as fluvial or pluvial, if their area is less than
        min_polygon_area_acres, they are reclassified to the opposite type and merged with
        adjacent polygons of that type. Ambiguous polygons are exempt from this logic.

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
                              and 'ambiguous' zones.
        """
        try:
            # --- 1. Data Loading and Preparation ---
            logger.info("Loading mesh and results data...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
            )
            cell_times = max_ws_df.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            
            logger.info("Processing cell adjacencies...")
            cell_adjacency, _ = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)

            # --- 2. Seeding the Classifications ---
            logger.info(f"Identifying initial boundary seeds with delta_t = {delta_t} hours...")
            boundary_pairs = HdfFluvialPluvial._get_boundary_cell_pairs(cell_adjacency, cell_times, delta_t)

            classifications = pd.Series('unclassified', index=cell_polygons_gdf['cell_id'], name='classification')
            
            for cell1, cell2 in boundary_pairs:
                if cell_times.get(cell1) > cell_times.get(cell2):
                    classifications.loc[cell1] = 'fluvial'
                    classifications.loc[cell2] = 'pluvial'
                else:
                    classifications.loc[cell1] = 'pluvial'
                    classifications.loc[cell2] = 'fluvial'
            
            # --- 3. Iterative Region Growth ---
            logger.info(f"Starting iterative region growth with tolerance = {temporal_tolerance_hours} hours...")
            fluvial_frontier = set(classifications[classifications == 'fluvial'].index)
            pluvial_frontier = set(classifications[classifications == 'pluvial'].index)
            
            iteration = 0
            with tqdm(desc="Region Growing", unit="iter") as pbar:
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
            
            logger.info(f"Region growing completed in {iteration} iterations.")
            
            # --- 4. Finalization and Dissolving ---
            # Classify any remaining unclassified (likely isolated) cells as ambiguous
            classifications[classifications == 'unclassified'] = 'ambiguous'

            logger.info("Merging classifications with cell polygons...")
            classified_gdf = cell_polygons_gdf.merge(classifications.to_frame(), left_on='cell_id', right_index=True)
            
            logger.info("Dissolving polygons by classification...")
            final_regions_gdf = classified_gdf.dissolve(by='classification', aggfunc='first').reset_index()

            # --- 5. Minimum Polygon Area Filtering and Merging (if requested) ---
            if min_polygon_area_acres is not None:
                logger.info(f"Applying minimum polygon area filter: {min_polygon_area_acres} acres")
                # Calculate area in acres (1 acre = 4046.8564224 m^2)
                # If CRS is not projected, warn and skip area filtering
                if not final_regions_gdf.crs or not final_regions_gdf.crs.is_projected:
                    logger.warning("CRS is not projected. Area-based filtering skipped.")
                else:
                    # Explode to individual polygons for area filtering
                    exploded = final_regions_gdf.explode(index_parts=False, ignore_index=True)
                    exploded['area_acres'] = exploded.geometry.area / 4046.8564224

                    # Only consider fluvial and pluvial polygons for area filtering
                    mask_fluvial = (exploded['classification'] == 'fluvial') & (exploded['area_acres'] < min_polygon_area_acres)
                    mask_pluvial = (exploded['classification'] == 'pluvial') & (exploded['area_acres'] < min_polygon_area_acres)

                    n_fluvial = mask_fluvial.sum()
                    n_pluvial = mask_pluvial.sum()
                    logger.info(f"Found {n_fluvial} small fluvial and {n_pluvial} small pluvial polygons to reclassify.")

                    # Reclassify small fluvial polygons as pluvial, and small pluvial polygons as fluvial
                    exploded.loc[mask_fluvial, 'classification'] = 'pluvial'
                    exploded.loc[mask_pluvial, 'classification'] = 'fluvial'
                    # Ambiguous polygons are not changed

                    # Redissolve by classification to merge with adjacent polygons of the same type
                    final_regions_gdf = exploded.dissolve(by='classification', aggfunc='first').reset_index()
                    logger.info("Redissolved polygons after reclassification of small areas.")

            logger.info("Polygon generation completed successfully.")
            return final_regions_gdf
            
        except Exception as e:
            logger.error(f"Error generating fluvial-pluvial polygons: {str(e)}", exc_info=True)
            return gpd.GeoDataFrame()
        
        
    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[int, List[int]], Dict[int, Dict[int, LineString]]]:
        """
        Optimized method to process cell adjacencies by extracting shared edges directly.
        """
        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)
        edge_to_cells = defaultdict(set)

        def edge_key(coords1, coords2, precision=8):
            coords1 = tuple(round(coord, precision) for coord in coords1)
            coords2 = tuple(round(coord, precision) for coord in coords2)
            return tuple(sorted([coords1, coords2]))

        for _, row in cell_polygons_gdf.iterrows():
            cell_id = row['cell_id']
            geom = row['geometry']
            if geom.is_empty or not geom.is_valid:
                continue
            coords = list(geom.exterior.coords)
            for i in range(len(coords) - 1):
                key = edge_key(coords[i], coords[i + 1])
                edge_to_cells[key].add(cell_id)

        for edge, cells in edge_to_cells.items():
            cell_list = list(cells)
            if len(cell_list) >= 2:
                for i in range(len(cell_list)):
                    for j in range(i + 1, len(cell_list)):
                        cell1, cell2 = cell_list[i], cell_list[j]
                        cell_adjacency[cell1].append(cell2)
                        cell_adjacency[cell2].append(cell1)
                        common_edge = LineString([edge[0], edge[1]])
                        common_edges[cell1][cell2] = common_edge
                        common_edges[cell2][cell1] = common_edge

        return cell_adjacency, common_edges
    
    @staticmethod
    def _get_boundary_cell_pairs(
        cell_adjacency: Dict[int, List[int]], 
        cell_times: Dict[int, pd.Timestamp], 
        delta_t: float
    ) -> List[Tuple[int, int]]:
        """
        Identifies pairs of adjacent cell IDs that form a boundary.

        A boundary is defined where the difference in max water surface time
        between two adjacent cells is greater than delta_t.
        
        Args:
            cell_adjacency (Dict[int, List[int]]): Dictionary of cell adjacencies.
            cell_times (Dict[int, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.

        Returns:
            List[Tuple[int, int]]: A list of tuples, where each tuple contains a pair of
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
        cell_adjacency: Dict[int, List[int]], 
        common_edges: Dict[int, Dict[int, LineString]], 
        cell_times: Dict[int, pd.Timestamp], 
        delta_t: float,
        min_line_length: Optional[float] = None
    ) -> List[LineString]:
        """
        Identify boundary edges between cells with significant time differences.
        
        This function now uses the helper `_get_boundary_cell_pairs`.

        Args:
            cell_adjacency (Dict[int, List[int]]): Dictionary of cell adjacencies.
            common_edges (Dict[int, Dict[int, LineString]]): Dictionary of shared edges between cells.
            cell_times (Dict[int, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times.
            delta_t (float): Time threshold in hours.
            min_line_length (float, optional): Minimum length (in CRS units) for boundary lines to be included.
                                               Lines shorter than this will be dropped. Default is None (no filtering).

        Returns:
            List[LineString]: List of LineString geometries representing boundaries.
        """
        boundary_pairs = HdfFluvialPluvial._get_boundary_cell_pairs(cell_adjacency, cell_times, delta_t)
        
        boundary_edges = [common_edges[c1][c2] for c1, c2 in boundary_pairs]
        
        logger.info(f"Identified {len(boundary_edges)} boundary edges using delta_t of {delta_t} hours.")

        if min_line_length is not None:
            filtered_edges = [edge for edge in boundary_edges if edge.length >= min_line_length]
            num_dropped = len(boundary_edges) - len(filtered_edges)
            if num_dropped > 0:
                logger.info(f"{num_dropped} boundary line(s) shorter than {min_line_length} units were dropped after filtering.")
            boundary_edges = filtered_edges

        return boundary_edges
