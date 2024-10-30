from typing import Dict, List, Tuple
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from collections import defaultdict
from rtree import index
from shapely.geometry import LineString, MultiLineString
from tqdm import tqdm

from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils

class HdfFluvialPluvial:
    """
    A class for analyzing and visualizing fluvial-pluvial boundaries in HEC-RAS 2D model results.

    This class provides methods to process and visualize HEC-RAS 2D model outputs,
    specifically focusing on the delineation of fluvial and pluvial flood areas.
    It includes functionality for plotting maximum water surface elevations,
    extracting cell polygons, and calculating fluvial-pluvial boundaries based on
    the timing of maximum water surface elevations.

    Key Features:
    - Plotting maximum water surface elevations and their timing
    - Extracting and visualizing 2D flow area cell polygons
    - Calculating and visualizing fluvial-pluvial boundaries

    Data Requirements:
    1. For plotting maximum water surface:
       - Use HdfResultsMesh.mesh_max_ws(hdf_path) to get max_ws_df
       - Use HdfResultsMesh.mesh_timeseries_output(hdf_path, mesh_name, 'water_surface') 
         to get time series data

    2. For extracting cell polygons:
       - Use HdfMesh.mesh_cell_polygons(geom_hdf_path) to get cell_polygons_df
       - Use HdfUtils.projection(hdf_path) to get the projection

    3. For calculating fluvial-pluvial boundary:
       - Requires cell_polygons_gdf (from step 2)
       - Requires max_ws_df with 'cell_id' and 'max_wsel_time' columns
         (can be derived from HdfResultsMesh.mesh_max_ws(hdf_path))

    Usage:
    To use this class effectively, first initialize a RasPrj object and load the
    necessary HDF files. Then, use the methods provided to analyze and visualize
    the fluvial-pluvial characteristics of your 2D model results.

    Example:
        ras = RasPrj()
        ras = init_ras_project(project_path, ras_version)
        hdf_path = ras.get_plan_value(plan_number, 'Results_Output')
        
        # Get maximum water surface data
        max_ws_df = HdfResultsMesh.mesh_max_ws(hdf_path)
        
        # Plot maximum water surface
        HdfFluvialPluvial.plot_max_water_surface(max_ws_df)
        
        # Extract cell polygons
        cell_polygons_df = HdfMesh.mesh_cell_polygons(hdf_path)
        projection = HdfUtils.projection(hdf_path)
        cell_polygons_gdf = HdfFluvialPluvial.plot_cell_polygons(cell_polygons_df, projection)
        
        # Calculate fluvial-pluvial boundary
        boundary_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(cell_polygons_gdf, max_ws_df)

    Note: Ensure that you have the necessary permissions and have initialized
    the RAS project correctly before attempting to access HDF files.
    """

    @staticmethod
    def plot_max_water_surface(max_ws_df):
        """
        Plots the maximum water surface elevation per cell.

        Parameters:
        - max_ws_df: DataFrame containing merged data with coordinates and max water surface.

        Returns:
        - None
        """
        # Extract x and y coordinates from the geometry column
        max_ws_df['x'] = max_ws_df['geometry'].apply(lambda geom: geom.x if geom is not None else None)
        max_ws_df['y'] = max_ws_df['geometry'].apply(lambda geom: geom.y if geom is not None else None)

        # Check if 'x' and 'y' columns exist in max_ws_df
        if 'x' not in max_ws_df.columns or 'y' not in max_ws_df.columns:
            print("Error: 'x' or 'y' columns not found in the merged dataframe.")
            print("Available columns:", max_ws_df.columns.tolist())
            return

        # Create the plot
        fig, ax = plt.subplots(figsize=(12, 8))
        scatter = ax.scatter(max_ws_df['x'], max_ws_df['y'], c=max_ws_df['maximum_water_surface'], cmap='viridis', s=10)

        # Customize the plot
        ax.set_title('Max Water Surface per Cell')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        plt.colorbar(scatter, label='Max Water Surface (ft)')

        # Add grid lines
        ax.grid(True, linestyle='--', alpha=0.7)

        # Increase font size for better readability
        plt.rcParams.update({'font.size': 12})

        # Adjust layout to prevent cutting off labels
        plt.tight_layout()

        # Show the plot
        plt.show()
    
    
    

    @staticmethod
    def plot_max_wsel_time(max_ws_df: pd.DataFrame) -> None:
        """
        Plots the time of the maximum water surface elevation (WSEL) per cell.

        Parameters:
        - max_ws_df: DataFrame containing merged data with coordinates and max water surface.

        Returns:
        - None
        """
        max_ws_df['max_wsel_time'] = pd.to_datetime(max_ws_df['maximum_water_surface_time'])
        HdfFluvialPluvial._extract_coordinates(max_ws_df)

        if 'x' not in max_ws_df.columns or 'y' not in max_ws_df.columns:
            raise ValueError("x and y coordinates are missing from the DataFrame. Make sure the 'face_point' column exists and contains valid coordinate data.")

        fig, ax = plt.subplots(figsize=(12, 8))

        min_time = max_ws_df['max_wsel_time'].min()
        color_values = (max_ws_df['max_wsel_time'] - min_time).dt.total_seconds() / 3600

        scatter = ax.scatter(max_ws_df['x'], max_ws_df['y'], c=color_values, cmap='viridis', s=10)

        ax.set_title('Time of Maximum Water Surface Elevation per Cell')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')

        cbar = plt.colorbar(scatter)
        cbar.set_label('Hours since simulation start')
        cbar.set_ticks(range(0, int(color_values.max()) + 1, 6))
        cbar.set_ticklabels([f'{h}h' for h in range(0, int(color_values.max()) + 1, 6)])

        ax.grid(True, linestyle='--', alpha=0.7)
        plt.rcParams.update({'font.size': 12})
        plt.tight_layout()
        plt.show()

        HdfFluvialPluvial._print_max_wsel_info(max_ws_df, min_time)

    @staticmethod
    def plot_cell_polygons(cell_polygons_df: pd.DataFrame, projection: str) -> gpd.GeoDataFrame:
        """
        Plots the cell polygons from the provided DataFrame and returns the GeoDataFrame.

        Args:
            cell_polygons_df (pd.DataFrame): DataFrame containing cell polygons.
            projection (str): The coordinate reference system to assign to the GeoDataFrame.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the cell polygons.
        """
        if cell_polygons_df.empty:
            print("No Cell Polygons found.")
            return None

        cell_polygons_gdf = HdfFluvialPluvial._convert_to_geodataframe(cell_polygons_df, projection)

        print("Cell Polygons CRS:", cell_polygons_gdf.crs)
        display(cell_polygons_gdf.head())

        fig, ax = plt.subplots(figsize=(12, 8))
        cell_polygons_gdf.plot(ax=ax, edgecolor='blue', facecolor='none')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        ax.set_title('2D Flow Area Cell Polygons')
        ax.grid(True)
        plt.tight_layout()
        plt.show()

        return cell_polygons_gdf

    @staticmethod
    def calculate_fluvial_pluvial_boundary(cell_polygons_gdf: gpd.GeoDataFrame, max_ws_df: pd.DataFrame, delta_t: float = 12) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary based on cell polygons and maximum water surface elevation times.

        Args:
            cell_polygons_gdf (gpd.GeoDataFrame): GeoDataFrame containing cell polygons with 'cell_id' and 'geometry' columns.
            max_ws_df (pd.DataFrame): DataFrame containing 'cell_id' and 'max_wsel_time' columns.
            delta_t (float): Threshold time difference in hours. Default is 12 hours.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundary as simple LineStrings.
        """
        cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)
        cell_times = max_ws_df.set_index('cell_id')['max_wsel_time'].to_dict()
        boundary_edges = HdfFluvialPluvial._identify_boundary_edges(cell_adjacency, common_edges, cell_times, delta_t)

        # Join adjacent LineStrings into simple LineStrings
        joined_lines = []
        current_line = []

        for edge in boundary_edges:
            if not current_line:
                current_line.append(edge)
            else:
                if current_line[-1].coords[-1] == edge.coords[0]:  # Check if the last point of the current line matches the first point of the new edge
                    current_line.append(edge)
                else:
                    # Create a simple LineString from the current line and reset
                    joined_lines.append(LineString([point for line in current_line for point in line.coords]))
                    current_line = [edge]

        # Add the last collected line if exists
        if current_line:
            joined_lines.append(LineString([point for line in current_line for point in line.coords]))

        boundary_gdf = gpd.GeoDataFrame(geometry=joined_lines, crs=cell_polygons_gdf.crs)
        return boundary_gdf

    @staticmethod
    def _print_max_wsel_info(max_ws_df: pd.DataFrame, min_time: pd.Timestamp) -> None:
        max_wsel_row = max_ws_df.loc[max_ws_df['maximum_water_surface'].idxmax()]
        hours_since_start = (max_wsel_row['max_wsel_time'] - min_time).total_seconds() / 3600
        print(f"\nOverall Maximum WSEL: {max_wsel_row['maximum_water_surface']:.2f} ft")
        print(f"Time of Overall Maximum WSEL: {max_wsel_row['max_wsel_time']}")
        print(f"Hours since simulation start: {hours_since_start:.2f} hours")
        print(f"Location of Overall Maximum WSEL: X={max_wsel_row['x']}, Y={max_wsel_row['y']}")

    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[int, List[int]], Dict[int, Dict[int, LineString]]]:
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
    def _identify_boundary_edges(cell_adjacency: Dict[int, List[int]], common_edges: Dict[int, Dict[int, LineString]], cell_times: Dict[int, pd.Timestamp], delta_t: float) -> List[LineString]:
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

    @staticmethod
    def _extract_coordinates(df: pd.DataFrame) -> None:
        """
        Extract x and y coordinates from the 'face_point' column.

        Parameters:
        - df: DataFrame containing the 'face_point' column.

        Returns:
        - None (modifies the DataFrame in-place)
        """
        if 'face_point' in df.columns:
            df[['x', 'y']] = df['face_point'].str.strip('()').str.split(',', expand=True).astype(float)
        else:
            print("Warning: 'face_point' column not found in the DataFrame.")

    @staticmethod
    def _convert_to_geodataframe(df: pd.DataFrame, projection: str) -> gpd.GeoDataFrame:
        """
        Convert a DataFrame to a GeoDataFrame.

        Parameters:
        - df: DataFrame containing 'geometry' column.
        - projection: The coordinate reference system to assign to the GeoDataFrame.

        Returns:
        - GeoDataFrame with the specified projection.
        """
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs=projection)
        
        return gdf




