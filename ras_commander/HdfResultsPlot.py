"""
Class: HdfResultsPlot

A collection of static methods for visualizing HEC-RAS results data from HDF files using matplotlib.

Public Functions:
    plot_results_mesh_variable(variable_df, variable_name, colormap='viridis', point_size=10):
        Generic plotting function for any mesh variable with customizable styling.
        
    plot_results_max_wsel(max_ws_df):
        Visualizes the maximum water surface elevation distribution across mesh cells.
        
    plot_results_max_wsel_time(max_ws_df):
        Displays the timing of maximum water surface elevation for each cell,
        including statistics about the temporal distribution.

Requirements:
    - matplotlib
    - pandas
    - geopandas (for geometry handling)

Input DataFrames must contain:
    - 'geometry' column with Point objects containing x,y coordinates
    - Variable data columns as specified in individual function docstrings
"""

import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict
from .Decorators import log_call
from .HdfMesh import HdfMesh

class HdfResultsPlot:
    """
    A class containing static methods for plotting HEC-RAS results data.
    
    This class provides visualization methods for various types of HEC-RAS results,
    including maximum water surface elevations and timing information.
    """

    @staticmethod
    @log_call
    def plot_results_max_wsel(max_ws_df: pd.DataFrame) -> None:
        """
        Plots the maximum water surface elevation per cell.

        Args:
            max_ws_df (pd.DataFrame): DataFrame containing merged data with coordinates 
                                    and max water surface elevations.
        """
        # Extract x and y coordinates from the geometry column
        max_ws_df['x'] = max_ws_df['geometry'].apply(lambda geom: geom.x if geom is not None else None)
        max_ws_df['y'] = max_ws_df['geometry'].apply(lambda geom: geom.y if geom is not None else None)

        if 'x' not in max_ws_df.columns or 'y' not in max_ws_df.columns:
            print("Error: 'x' or 'y' columns not found in the merged dataframe.")
            print("Available columns:", max_ws_df.columns.tolist())
            return

        fig, ax = plt.subplots(figsize=(12, 8))
        scatter = ax.scatter(max_ws_df['x'], max_ws_df['y'], 
                           c=max_ws_df['maximum_water_surface'], 
                           cmap='viridis', s=10)

        ax.set_title('Max Water Surface per Cell')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        plt.colorbar(scatter, label='Max Water Surface (ft)')

        ax.grid(True, linestyle='--', alpha=0.7)
        plt.rcParams.update({'font.size': 12})
        plt.tight_layout()
        plt.show()

    @staticmethod
    @log_call
    def plot_results_max_wsel_time(max_ws_df: pd.DataFrame) -> None:
        """
        Plots the time of the maximum water surface elevation (WSEL) per cell.

        Args:
            max_ws_df (pd.DataFrame): DataFrame containing merged data with coordinates 
                                    and max water surface timing information.
        """
        # Convert datetime strings using the renamed utility function
        max_ws_df['max_wsel_time'] = pd.to_datetime(max_ws_df['maximum_water_surface_time'])
        
        # Extract coordinates
        max_ws_df['x'] = max_ws_df['geometry'].apply(lambda geom: geom.x if geom is not None else None)
        max_ws_df['y'] = max_ws_df['geometry'].apply(lambda geom: geom.y if geom is not None else None)

        if 'x' not in max_ws_df.columns or 'y' not in max_ws_df.columns:
            raise ValueError("x and y coordinates are missing from the DataFrame. Make sure the 'geometry' column exists and contains valid coordinate data.")

        fig, ax = plt.subplots(figsize=(12, 8))

        min_time = max_ws_df['max_wsel_time'].min()
        color_values = (max_ws_df['max_wsel_time'] - min_time).dt.total_seconds() / 3600

        scatter = ax.scatter(max_ws_df['x'], max_ws_df['y'], 
                           c=color_values, cmap='viridis', s=10)

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

        # Print timing information
        print(f"\nSimulation Start Time: {min_time}")
        print(f"Time Range: {color_values.max():.1f} hours")
        print("\nTiming Statistics (hours since start):")
        print(color_values.describe()) 

    @staticmethod
    @log_call
    def plot_results_mesh_variable(variable_df: pd.DataFrame, variable_name: str, colormap: str = 'viridis', point_size: int = 10) -> None:
        """
        Plot any mesh variable with consistent styling.
        
        Args:
            variable_df (pd.DataFrame): DataFrame containing the variable data
            variable_name (str): Name of the variable (for labels)
            colormap (str): Matplotlib colormap to use. Default: 'viridis'
            point_size (int): Size of the scatter points. Default: 10

        Returns:
            None

        Raises:
            ImportError: If matplotlib is not installed
            ValueError: If required columns are missing from variable_df
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            logger.error("matplotlib is required for plotting. Please install it with 'pip install matplotlib'")
            raise ImportError("matplotlib is required for plotting")

        # Get cell coordinates if not in variable_df
        if 'geometry' not in variable_df.columns:
            cell_coords = HdfMesh.mesh_cell_points(plan_hdf_path)
            merged_df = pd.merge(variable_df, cell_coords, on=['mesh_name', 'cell_id'])
        else:
            merged_df = variable_df
            
        # Extract coordinates, handling None values
        merged_df = merged_df.dropna(subset=['geometry'])
        merged_df['x'] = merged_df['geometry'].apply(lambda geom: geom.x if geom is not None else None)
        merged_df['y'] = merged_df['geometry'].apply(lambda geom: geom.y if geom is not None else None)
        
        # Drop any rows with None coordinates
        merged_df = merged_df.dropna(subset=['x', 'y'])
        
        if len(merged_df) == 0:
            logger.error("No valid coordinates found for plotting")
            raise ValueError("No valid coordinates found for plotting")
            
        # Create plot
        fig, ax = plt.subplots(figsize=(12, 8))
        scatter = ax.scatter(merged_df['x'], merged_df['y'], 
                           c=merged_df[variable_name], 
                           cmap=colormap, 
                           s=point_size)
        
        # Customize plot
        ax.set_title(f'{variable_name} per Cell')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        plt.colorbar(scatter, label=variable_name)
        ax.grid(True, linestyle='--', alpha=0.7)
        plt.rcParams.update({'font.size': 12})
        plt.tight_layout()
        plt.show()
