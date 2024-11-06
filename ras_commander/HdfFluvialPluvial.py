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
from shapely.geometry import LineString
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
            if 'maximum_water_surface_time' in max_ws_df.columns:
                max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                    lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
                )

            # Process cell adjacencies
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)
            
            # Get cell times from max_ws_df
            cell_times = max_ws_df.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            
            # Identify boundary edges
            boundary_edges = HdfFluvialPluvial._identify_boundary_edges(
                cell_adjacency, common_edges, cell_times, delta_t
            )

            # Join adjacent LineStrings into simple LineStrings
            joined_lines = []
            current_line = []

            for edge in boundary_edges:
                if not current_line:
                    current_line.append(edge)
                else:
                    if current_line[-1].coords[-1] == edge.coords[0]:
                        current_line.append(edge)
                    else:
                        joined_lines.append(LineString([point for line in current_line for point in line.coords]))
                        current_line = [edge]

            if current_line:
                joined_lines.append(LineString([point for line in current_line for point in line.coords]))

            # Create final GeoDataFrame with CRS from cell_polygons_gdf
            boundary_gdf = gpd.GeoDataFrame(
                geometry=joined_lines, 
                crs=cell_polygons_gdf.crs
            )

            # Clean up intermediate dataframes
            del cell_polygons_gdf
            del max_ws_df

            return boundary_gdf

        except Exception as e:
            logger.error(f"Error calculating fluvial-pluvial boundary: {str(e)}")
            raise

    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[int, List[int]], Dict[int, Dict[int, LineString]]]:
        """
        Process cell adjacencies and common edges using R-tree spatial indexing for efficiency.

        Args:
            cell_polygons_gdf (gpd.GeoDataFrame): GeoDataFrame containing 2D mesh cell polygons
                                                 with 'cell_id' and 'geometry' columns

        Returns:
            Tuple containing:
                - Dict[int, List[int]]: Dictionary mapping cell IDs to lists of adjacent cell IDs
                - Dict[int, Dict[int, LineString]]: Nested dictionary storing common edges between cells,
                                                   where common_edges[cell1][cell2] gives the shared boundary

        Note:
            Uses R-tree spatial indexing to efficiently identify potential neighboring cells
            before performing more detailed geometric operations.
        """
        from rtree import index
        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)
        idx = index.Index()

        for i, geom in enumerate(cell_polygons_gdf.geometry):
            idx.insert(i, geom.bounds)

        with tqdm(total=len(cell_polygons_gdf), desc="Processing cell adjacencies") as pbar:
            for idx1, row1 in cell_polygons_gdf.iterrows():
                cell_id1 = row1['cell_id']
                poly1 = row1['geometry']
                potential_neighbors = list(idx.intersection(poly1.bounds))

                for idx2 in potential_neighbors:
                    if idx1 >= idx2:
                        continue

                    row2 = cell_polygons_gdf.iloc[idx2]
                    cell_id2 = row2['cell_id']
                    poly2 = row2['geometry']

                    if poly1.touches(poly2):
                        intersection = poly1.intersection(poly2)
                        if isinstance(intersection, LineString):
                            cell_adjacency[cell_id1].append(cell_id2)
                            cell_adjacency[cell_id2].append(cell_id1)
                            common_edges[cell_id1][cell_id2] = intersection
                            common_edges[cell_id2][cell_id1] = intersection

                pbar.update(1)

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
