"""
Class: HdfPlot

A collection of static methods for plotting general HDF data from HEC-RAS models.

Lazy Loading:
    matplotlib and geopandas are imported inside methods that use them,
    not at module level. This reduces import overhead for users who
    don't use plotting functionality.
"""

import pandas as pd
from typing import Optional, Union, Tuple, TYPE_CHECKING
from ..Decorators import log_call, standardize_input
from .HdfUtils import HdfUtils

# Type hints only - not imported at runtime
if TYPE_CHECKING:
    import geopandas as gpd


class HdfPlot:
    """
    A class containing static methods for plotting general HDF data from HEC-RAS models.

    This class provides plotting functionality for HDF data, focusing on
    geometric elements like cell polygons and time series data.

    Note:
        matplotlib and geopandas are lazy-loaded when plotting methods are called.
    """

    @staticmethod
    @log_call
    def plot_mesh_cells(
        cell_polygons_df: pd.DataFrame,
        projection: str,
        title: str = '2D Flow Area Mesh Cells',
        figsize: Tuple[int, int] = (12, 8)
    ) -> Optional['gpd.GeoDataFrame']:
        """
        Plots the mesh cells from the provided DataFrame and returns the GeoDataFrame.

        Args:
            cell_polygons_df (pd.DataFrame): DataFrame containing cell polygons.
            projection (str): The coordinate reference system to assign to the GeoDataFrame.
            title (str, optional): Plot title. Defaults to '2D Flow Area Mesh Cells'.
            figsize (Tuple[int, int], optional): Figure size. Defaults to (12, 8).

        Returns:
            Optional[gpd.GeoDataFrame]: GeoDataFrame containing the mesh cells, or None if no cells found.
        """
        # Lazy imports for heavy dependencies
        import matplotlib.pyplot as plt
        import geopandas as gpd

        if cell_polygons_df.empty:
            print("No Cell Polygons found.")
            return None

        # Convert any datetime columns to strings using HdfUtils
        cell_polygons_df = HdfUtils.convert_df_datetimes_to_str(cell_polygons_df)

        cell_polygons_gdf = gpd.GeoDataFrame(cell_polygons_df, crs=projection)

        print("Cell Polygons CRS:", cell_polygons_gdf.crs)
        try:
            display(cell_polygons_gdf.head())
        except NameError:
            # display() not available outside Jupyter
            print(cell_polygons_gdf.head())

        fig, ax = plt.subplots(figsize=figsize)
        cell_polygons_gdf.plot(ax=ax, edgecolor='blue', facecolor='none')
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        ax.set_title(title)
        ax.grid(True)
        plt.tight_layout()
        plt.show()

        return cell_polygons_gdf

    @staticmethod
    @log_call
    def plot_time_series(
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str = None,
        figsize: Tuple[int, int] = (12, 6)
    ) -> None:
        """
        Plots time series data from HDF results.

        Args:
            df (pd.DataFrame): DataFrame containing the time series data
            x_col (str): Name of the column containing x-axis data (usually time)
            y_col (str): Name of the column containing y-axis data
            title (str, optional): Plot title. Defaults to None.
            figsize (Tuple[int, int], optional): Figure size. Defaults to (12, 6).
        """
        # Lazy import for heavy dependency
        import matplotlib.pyplot as plt

        # Convert any datetime columns to strings
        df = HdfUtils.convert_df_datetimes_to_str(df)

        fig, ax = plt.subplots(figsize=figsize)
        df.plot(x=x_col, y=y_col, ax=ax)

        if title:
            ax.set_title(title)
        ax.grid(True)
        plt.tight_layout()
        plt.show()
