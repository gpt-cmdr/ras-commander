"""
Class: HdfXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import LineString, MultiLineString
from typing import List  # Import List to avoid NameError
from .Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .LoggingConfig import get_logger

logger = get_logger(__name__)

class HdfXsec:
    """
    HdfXsec class for handling cross-section related operations on HEC-RAS HDF files.

    This class provides methods to extract and process cross-section data, elevation information,
    and river reach data from HEC-RAS HDF geometry files. It includes functionality to retrieve
    cross-section attributes, elevation profiles, and river reach geometries.

    The class uses static methods, allowing for direct calls without instantiation. It relies on
    utility functions from HdfBase and HdfUtils classes for various operations such as projection
    handling and data conversion.

    Note:
        This class is designed to work with HEC-RAS geometry HDF files and requires them to have
        a specific structure and naming convention for the data groups and attributes.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def cross_sections(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model 1D cross sections.

        This method extracts cross-section data from the HEC-RAS geometry HDF file,
        including attributes and geometry information.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the cross sections with their attributes and geometries.

        Raises
        ------
        KeyError
            If the required datasets are not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                xs_data = hdf_file["Geometry/Cross Sections"]
                
                if "Attributes" not in xs_data:
                    logger.warning(f"No 'Attributes' dataset group in {hdf_path}")
                    return GeoDataFrame()

                # Convert attribute values
                v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                xs_attrs = xs_data["Attributes"][()]
                xs_dict = {"xs_id": range(xs_attrs.shape[0])}
                xs_dict.update(
                    {name: v_conv_val(xs_attrs[name]) for name in xs_attrs.dtype.names}
                )

                xs_df = pd.DataFrame(xs_dict)
                
                # Create geometry from coordinate pairs
                xs_df['geometry'] = xs_df.apply(lambda row: LineString([
                    (row['XS_X_Coord_1'], row['XS_Y_Coord_1']),
                    (row['XS_X_Coord_2'], row['XS_Y_Coord_2'])
                ]), axis=1)
                
                # Convert to GeoDataFrame
                gdf = GeoDataFrame(xs_df, geometry='geometry', crs=HdfUtils.projection(hdf_path))
                
                # Convert datetime columns to strings if requested
                if datetime_to_str:
                    gdf = HdfUtils.df_datetimes_to_str(gdf)
                
                return gdf

        except KeyError as e:
            logger.error(f"Error accessing cross-section data in {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def cross_sections_elevations(hdf_path: Path, round_to: int = 2) -> pd.DataFrame:
        """
        Return the model cross section elevation information.

        This method extracts cross-section elevation data from the HEC-RAS geometry HDF file,
        including station-elevation pairs for each cross-section.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        round_to : int, optional
            Number of decimal places to round to. Default is 2.

        Returns
        -------
        pd.DataFrame
            A DataFrame containing the cross section elevation information.

        Raises
        ------
        KeyError
            If the required datasets are not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                path = "/Geometry/Cross Sections"
                if path not in hdf_file:
                    logger.warning(f"No 'Cross Sections' group found in {hdf_path}")
                    return pd.DataFrame()

                xselev_data = hdf_file[path]
                
                if "Station Elevation Info" not in xselev_data or "Station Elevation Values" not in xselev_data:
                    logger.warning(f"Required datasets not found in Cross Sections group in {hdf_path}")
                    return pd.DataFrame()

                # Get cross-section data
                xs_df = HdfXsec.cross_sections(hdf_path)
                if xs_df.empty:
                    return pd.DataFrame()

                # Extract elevation data
                elevations = []
                for part_start, part_cnt in xselev_data["Station Elevation Info"][()]:
                    xzdata = xselev_data["Station Elevation Values"][()][
                        part_start : part_start + part_cnt
                    ]
                    elevations.append(xzdata)

                # Create DataFrame with elevation info
                xs_elev_df = xs_df[
                    ["xs_id", "River", "Reach", "RS", "Left Bank", "Right Bank"]
                ].copy()
                xs_elev_df["Left Bank"] = xs_elev_df["Left Bank"].round(round_to).astype(str)
                xs_elev_df["Right Bank"] = xs_elev_df["Right Bank"].round(round_to).astype(str)
                xs_elev_df["elevation info"] = elevations

                return xs_elev_df

        except KeyError as e:
            logger.error(f"Error accessing cross-section elevation data in {hdf_path}: {str(e)}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Unexpected error in cross_sections_elevations: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def river_reaches(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model 1D river reach lines.

        This method extracts river reach data from the HEC-RAS geometry HDF file,
        including attributes and geometry information.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the river reaches with their attributes and geometries.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    return GeoDataFrame()

                river_data = hdf_file["Geometry/River Centerlines"]
                v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                river_attrs = river_data["Attributes"][()]
                river_dict = {"river_id": range(river_attrs.shape[0])}
                river_dict.update(
                    {name: v_conv_val(river_attrs[name]) for name in river_attrs.dtype.names}
                )
                
                # Get polylines for river reaches
                geoms = HdfXsec._get_polylines(hdf_path, "Geometry/River Centerlines")
                
                river_gdf = GeoDataFrame(
                    river_dict,
                    geometry=geoms,
                    crs=HdfUtils.projection(hdf_path),
                )
                if datetime_to_str:
                    river_gdf["Last Edited"] = river_gdf["Last Edited"].apply(
                        lambda x: pd.Timestamp.isoformat(x)
                    )
                return river_gdf
        except Exception as e:
            logger.error(f"Error reading river reaches: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    def _get_polylines(hdf_path: Path, path: str, info_name: str = "Polyline Info", parts_name: str = "Polyline Parts", points_name: str = "Polyline Points") -> List[LineString]:
        """
        Helper method to extract polylines from HDF file.

        This method is used internally to extract polyline geometries for various features
        such as river reaches.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        path : str
            Path within the HDF file to the polyline data.
        info_name : str, optional
            Name of the dataset containing polyline info. Default is "Polyline Info".
        parts_name : str, optional
            Name of the dataset containing polyline parts. Default is "Polyline Parts".
        points_name : str, optional
            Name of the dataset containing polyline points. Default is "Polyline Points".

        Returns
        -------
        List[LineString]
            A list of LineString geometries representing the polylines.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                polyline_info_path = f"{path}/{info_name}"
                polyline_parts_path = f"{path}/{parts_name}"
                polyline_points_path = f"{path}/{points_name}"

                polyline_info = hdf_file[polyline_info_path][()]
                polyline_parts = hdf_file[polyline_parts_path][()]
                polyline_points = hdf_file[polyline_points_path][()]

                geoms = []
                for pnt_start, pnt_cnt, part_start, part_cnt in polyline_info:
                    points = polyline_points[pnt_start : pnt_start + pnt_cnt]
                    if part_cnt == 1:
                        geoms.append(LineString(points))
                    else:
                        parts = polyline_parts[part_start : part_start + part_cnt]
                        geoms.append(
                            MultiLineString(
                                list(
                                    points[part_pnt_start : part_pnt_start + part_pnt_cnt]
                                    for part_pnt_start, part_pnt_cnt in parts
                                )
                            )
                        )
                return geoms
        except Exception as e:
            logger.error(f"Error getting polylines: {str(e)}")
            return []
