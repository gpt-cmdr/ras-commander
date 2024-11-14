"""
Class: HdfFluvialPluvial

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfFluvialPluvial:
- calculate_fluvial_pluvial_boundary()
- _process_cell_adjacencies()
- _identify_boundary_edges()

"""

from typing import Dict, List, Tuple
import pandas as pd
import geopandas as gpd
from collections import defaultdict
from shapely.geometry import LineString, MultiLineString  # Added MultiLineString import
from tqdm import tqdm
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from .Decorators import standardize_input
from .HdfResultsMesh import HdfResultsMesh
from .LoggingConfig import get_logger
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
    - Delta_t: Time threshold (in hours) used to distinguish between fluvial and pluvial cells.
               Cells with max WSE time differences greater than delta_t are considered boundaries.

    Data Requirements:
    - HEC-RAS plan HDF file containing:
        - 2D mesh cell geometry (accessed via HdfMesh)
        - Maximum water surface elevation times (accessed via HdfResultsMesh)

    Usage Example:
        >>> ras = init_ras_project(project_path, ras_version)
        >>> hdf_path = Path("path/to/plan.hdf")
        >>> boundary_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
        ...     hdf_path, 
        ...     delta_t=12
        ... )
    """
    def __init__(self):
        self.logger = get_logger(__name__)  # Initialize logger with module name
    
    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def calculate_fluvial_pluvial_boundary(hdf_path: Path, delta_t: float = 12) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary based on cell polygons and maximum water surface elevation times.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file
            delta_t (float): Threshold time difference in hours. Cells with time differences
                        greater than this value are considered boundaries. Default is 12 hours.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundaries with:
                - geometry: LineString features representing boundaries
                - CRS: Coordinate reference system matching the input HDF file

        Raises:
            ValueError: If no cell polygons or maximum water surface data found in HDF file
            Exception: If there are errors during boundary calculation

        Note:
            The returned boundaries represent locations where the timing of maximum water surface
            elevation changes significantly (> delta_t), indicating potential transitions between
            fluvial and pluvial flooding mechanisms.
        """
        try:
            # Get cell polygons from HdfMesh
            logger.info("Getting cell polygons from HDF file...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            if cell_polygons_gdf.empty:
                raise ValueError("No cell polygons found in HDF file")

            # Get max water surface data from HdfResultsMesh
            logger.info("Getting maximum water surface data from HDF file...")
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            if max_ws_df.empty:
                raise ValueError("No maximum water surface data found in HDF file")

            # Convert timestamps using the renamed utility function
            logger.info("Converting maximum water surface timestamps...")
            if 'maximum_water_surface_time' in max_ws_df.columns:
                max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                    lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
                )

            # Process cell adjacencies
            logger.info("Processing cell adjacencies...")
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)
            
            # Get cell times from max_ws_df
            logger.info("Extracting cell times from maximum water surface data...")
            cell_times = max_ws_df.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            
            # Identify boundary edges
            logger.info("Identifying boundary edges...")
            boundary_edges = HdfFluvialPluvial._identify_boundary_edges(
                cell_adjacency, common_edges, cell_times, delta_t
            )

            # Join adjacent LineStrings into simple LineStrings
            logger.info("Joining adjacent LineStrings into simple LineStrings...")
            joined_lines = []
            
            def get_coords(geom):
                """Helper function to get coordinates from either LineString or MultiLineString"""
                if isinstance(geom, LineString):
                    return list(geom.coords)
                elif isinstance(geom, MultiLineString):
                    return list(geom.geoms[0].coords)
                return None

            # Create a dictionary to store start and end points for each line
            line_endpoints = {}
            for i, edge in enumerate(boundary_edges):
                coords = get_coords(edge)
                if coords:
                    line_endpoints[i] = (coords[0], coords[-1])

            # Process lines in order
            used_indices = set()
            while len(used_indices) < len(boundary_edges):
                current_line = []
                current_points = []
                
                # Find a new starting line if needed
                for i in range(len(boundary_edges)):
                    if i not in used_indices:
                        current_line.append(boundary_edges[i])
                        coords = get_coords(boundary_edges[i])
                        if coords:
                            current_points.extend(coords)
                        used_indices.add(i)
                        break
                
                # Continue adding connected lines
                while True:
                    found_next = False
                    current_end = current_points[-1] if current_points else None
                    
                    # Look for the next connected line
                    for i, (start, end) in line_endpoints.items():
                        if i not in used_indices and current_end:
                            if start == current_end:
                                # Add line in forward direction
                                coords = get_coords(boundary_edges[i])
                                if coords:
                                    current_points.extend(coords[1:])  # Skip first point to avoid duplication
                                current_line.append(boundary_edges[i])
                                used_indices.add(i)
                                found_next = True
                                break
                            elif end == current_end:
                                # Add line in reverse direction
                                coords = get_coords(boundary_edges[i])
                                if coords:
                                    current_points.extend(reversed(coords[:-1]))  # Skip last point to avoid duplication
                                current_line.append(boundary_edges[i])
                                used_indices.add(i)
                                found_next = True
                                break
                    
                    if not found_next:
                        break
                
                # Create a single LineString from the collected points
                if current_points:
                    joined_lines.append(LineString(current_points))

            # Create final GeoDataFrame with CRS from cell_polygons_gdf
            logger.info("Creating final GeoDataFrame for boundaries...")
            boundary_gdf = gpd.GeoDataFrame(
                geometry=joined_lines, 
                crs=cell_polygons_gdf.crs
            )

            # Clean up intermediate dataframes
            logger.info("Cleaning up intermediate dataframes...")
            del cell_polygons_gdf
            del max_ws_df

            logger.info("Fluvial-pluvial boundary calculation completed successfully.")
            return boundary_gdf

        except Exception as e:
            self.logger.error(f"Error calculating fluvial-pluvial boundary: {str(e)}")
            return None
        
        
    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[int, List[int]], Dict[int, Dict[int, LineString]]]:
        """
        Optimized method to process cell adjacencies by extracting shared edges directly.
        
        Args:
            cell_polygons_gdf (gpd.GeoDataFrame): GeoDataFrame containing 2D mesh cell polygons
                                                   with 'cell_id' and 'geometry' columns.

        Returns:
            Tuple containing:
                - Dict[int, List[int]]: Dictionary mapping cell IDs to lists of adjacent cell IDs.
                - Dict[int, Dict[int, LineString]]: Nested dictionary storing common edges between cells,
                                                    where common_edges[cell1][cell2] gives the shared boundary.
        """
        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)

        # Build an edge to cells mapping
        edge_to_cells = defaultdict(set)

        # Function to generate edge keys
        def edge_key(coords1, coords2, precision=8):
            # Round coordinates
            coords1 = tuple(round(coord, precision) for coord in coords1)
            coords2 = tuple(round(coord, precision) for coord in coords2)
            # Create sorted key to handle edge direction
            return tuple(sorted([coords1, coords2]))

        # For each polygon, extract edges
        for idx, row in cell_polygons_gdf.iterrows():
            cell_id = row['cell_id']
            geom = row['geometry']
            if geom.is_empty or not geom.is_valid:
                continue
            # Get exterior coordinates
            coords = list(geom.exterior.coords)
            num_coords = len(coords)
            for i in range(num_coords - 1):
                coord1 = coords[i]
                coord2 = coords[i + 1]
                key = edge_key(coord1, coord2)
                edge_to_cells[key].add(cell_id)

        # Now, process edge_to_cells to build adjacency
        for edge, cells in edge_to_cells.items():
            cells = list(cells)
            if len(cells) >= 2:
                # For all pairs of cells sharing this edge
                for i in range(len(cells)):
                    for j in range(i + 1, len(cells)):
                        cell1 = cells[i]
                        cell2 = cells[j]
                        # Update adjacency
                        if cell2 not in cell_adjacency[cell1]:
                            cell_adjacency[cell1].append(cell2)
                        if cell1 not in cell_adjacency[cell2]:
                            cell_adjacency[cell2].append(cell1)
                        # Store common edge
                        common_edge = LineString([edge[0], edge[1]])
                        common_edges[cell1][cell2] = common_edge
                        common_edges[cell2][cell1] = common_edge

        logger.info("Cell adjacencies processed successfully.")
        return cell_adjacency, common_edges

    @staticmethod
    def _identify_boundary_edges(cell_adjacency: Dict[int, List[int]], 
                               common_edges: Dict[int, Dict[int, LineString]], 
                               cell_times: Dict[int, pd.Timestamp], 
                               delta_t: float) -> List[LineString]:
        """
        Identify boundary edges between cells with significant time differences.

        Args:
            cell_adjacency (Dict[int, List[int]]): Dictionary of cell adjacencies
            common_edges (Dict[int, Dict[int, LineString]]): Dictionary of shared edges between cells
            cell_times (Dict[int, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times
            delta_t (float): Time threshold in hours

        Returns:
            List[LineString]: List of LineString geometries representing boundaries where
                             adjacent cells have time differences greater than delta_t

        Note:
            Boundaries are identified where the absolute time difference between adjacent
            cells exceeds the specified delta_t threshold.
        """
        boundary_edges = []
        with tqdm(total=len(cell_adjacency), desc="Processing cell adjacencies") as pbar:
            for cell_id, neighbors in cell_adjacency.items():
                cell_time = cell_times[cell_id]

                for neighbor_id in neighbors:
                    neighbor_time = cell_times[neighbor_id]
                    time_diff = abs((cell_time - neighbor_time).total_seconds() / 3600)

                    if time_diff >= delta_t:
                        boundary_edges.append(common_edges[cell_id][neighbor_id])

                pbar.update(1)

        return boundary_edges
