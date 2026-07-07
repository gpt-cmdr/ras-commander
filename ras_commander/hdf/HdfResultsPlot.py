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

import warnings
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt
import pandas as pd
from ..Decorators import log_call

class HdfResultsPlot:
    """
    A class containing static methods for plotting HEC-RAS results data.
    
    This class provides visualization methods for various types of HEC-RAS results,
    including maximum water surface elevations and timing information.
    """

    @staticmethod
    def _prepare_xy_dataframe(
        df: pd.DataFrame,
        required_columns: list[str],
        plot_name: str,
    ) -> pd.DataFrame:
        """Validate required columns and add x/y columns from point geometry."""
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(
                f"Cannot plot {plot_name}; missing column(s): {missing_columns}. "
                f"Available columns: {list(df.columns)}"
            )

        plot_df = df.copy()

        def get_coord(geom, attr: str):
            if geom is None or not hasattr(geom, attr):
                return None
            return getattr(geom, attr)

        plot_df['x'] = plot_df['geometry'].apply(lambda geom: get_coord(geom, 'x'))
        plot_df['y'] = plot_df['geometry'].apply(lambda geom: get_coord(geom, 'y'))
        plot_df = plot_df.dropna(subset=['x', 'y'])

        if plot_df.empty:
            raise ValueError(
                f"Cannot plot {plot_name}; no valid point geometries were found "
                "in the 'geometry' column."
            )

        return plot_df

    @staticmethod
    @log_call
    def plot_results_max_wsel(max_ws_df: pd.DataFrame) -> None:
        """
        Plots the maximum water surface elevation per cell.

        Args:
            max_ws_df (pd.DataFrame): DataFrame containing merged data with coordinates 
                                    and max water surface elevations.
        """
        plot_df = HdfResultsPlot._prepare_xy_dataframe(
            max_ws_df,
            ['geometry', 'maximum_water_surface'],
            'maximum water surface',
        )

        fig, ax = plt.subplots(figsize=(12, 8))
        scatter = ax.scatter(plot_df['x'], plot_df['y'],
                           c=plot_df['maximum_water_surface'],
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
    def plot_results_max_wsel_time(
        max_ws_df: pd.DataFrame,
        show_stats: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Plots the time of the maximum water surface elevation (WSEL) per cell.

        Args:
            max_ws_df (pd.DataFrame): DataFrame containing merged data with coordinates 
                                    and max water surface timing information.
            show_stats (bool): If True, return concise timing statistics.
        """
        plot_df = HdfResultsPlot._prepare_xy_dataframe(
            max_ws_df,
            ['geometry', 'maximum_water_surface_time'],
            'maximum water surface timing',
        )
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Could not infer format",
                    category=UserWarning,
                )
                parsed_times = pd.to_datetime(
                    plot_df['maximum_water_surface_time'],
                    errors='coerce',
                )
        except Exception as exc:
            raise ValueError(
                "Cannot plot maximum water surface timing; "
                "'maximum_water_surface_time' could not be parsed as datetimes."
            ) from exc
        invalid_count = int(parsed_times.isna().sum())
        if invalid_count:
            raise ValueError(
                "Cannot plot maximum water surface timing; "
                "'maximum_water_surface_time' could not be parsed as datetimes "
                f"for {invalid_count} row(s)."
            )
        plot_df['max_wsel_time'] = parsed_times

        fig, ax = plt.subplots(figsize=(12, 8))

        min_time = plot_df['max_wsel_time'].min()
        color_values = (plot_df['max_wsel_time'] - min_time).dt.total_seconds() / 3600

        scatter = ax.scatter(plot_df['x'], plot_df['y'],
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

        if show_stats:
            stats = color_values.describe()
            return {
                'simulation_start_time': min_time,
                'time_range_hours': float(color_values.max()),
                'count': int(stats['count']),
                'mean_hours': float(stats['mean']),
                'min_hours': float(stats['min']),
                'max_hours': float(stats['max']),
            }

        return None

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
        merged_df = HdfResultsPlot._prepare_xy_dataframe(
            variable_df,
            ['geometry', variable_name],
            variable_name,
        )

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
