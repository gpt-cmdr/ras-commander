"""
Class: HdfStruc

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""
from typing import Dict, Any, List, Union
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon, Point, GeometryCollection
from .HdfUtils import HdfUtils
from .HdfXsec import HdfXsec
from .HdfBase import HdfBase
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfStruc:
    """
    HEC-RAS HDF Structures class for handling operations related to structures in HDF files.

    This class provides methods for extracting and analyzing data about structures
    from HEC-RAS HDF files. It includes functionality to retrieve structure geometries
    and attributes.

    Methods in this class use the @standardize_input decorator to handle different
    input types (file path, etc.) and the @log_call decorator for logging method calls.

    Attributes:
        GEOM_STRUCTURES_PATH (str): Constant for the HDF path to structures data.

    Note: This class contains static methods and does not require instantiation.
    """
    
    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def structures(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extracts structure data from a HEC-RAS geometry HDF5 file and returns it as a GeoDataFrame.

        This function excludes Property Tables, Pier and Abutment Data/Attributes, and Gate Groups.
        It includes Table Info, Centerlines as LineStrings, Structures Attributes, Bridge Coefficient Attributes,
        and Profile Data (as a list of station and elevation values for each structure).

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF5 file.
        datetime_to_str : bool, optional
            Convert datetime objects to strings, by default False.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing all relevant structure data with geometries and attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if "Geometry/Structures" not in hdf:
                    logger.info(f"No structures found in: {hdf_path}")
                    return GeoDataFrame()

                def get_dataset_df(path: str) -> pd.DataFrame:
                    """
                    Helper function to convert an HDF5 dataset to a pandas DataFrame.

                    Parameters
                    ----------
                    path : str
                        The path to the dataset within the HDF5 file.

                    Returns
                    -------
                    pd.DataFrame
                        DataFrame representation of the dataset.
                    """
                    if path not in hdf:
                        logger.warning(f"Dataset not found: {path}")
                        return pd.DataFrame()

                    data = hdf[path][()]
                    
                    if data.dtype.names:
                        df = pd.DataFrame(data)
                        # Decode byte strings to UTF-8
                        for col in df.columns:
                            if df[col].dtype.kind in {'S', 'a'}:  # Byte strings
                                df[col] = df[col].str.decode('utf-8', errors='ignore')
                        return df
                    else:
                        # If no named fields, assign generic column names
                        return pd.DataFrame(data, columns=[f'Value_{i}' for i in range(data.shape[1])])

                # Extract relevant datasets
                struct_attrs = get_dataset_df("Geometry/Structures/Attributes")
                bridge_coef = get_dataset_df("Geometry/Structures/Bridge Coefficient Attributes")
                table_info = get_dataset_df("Geometry/Structures/Table Info")
                profile_data = get_dataset_df("Geometry/Structures/Profile Data")

                # Assign 'Structure ID' based on index (starting from 1)
                struct_attrs.reset_index(drop=True, inplace=True)
                struct_attrs['Structure ID'] = range(1, len(struct_attrs) + 1)
                logger.debug(f"Assigned Structure IDs: {struct_attrs['Structure ID'].tolist()}")

                # Check if 'Structure ID' was successfully assigned
                if 'Structure ID' not in struct_attrs.columns:
                    logger.error("'Structure ID' column could not be assigned to Structures/Attributes.")
                    return GeoDataFrame()

                # Get centerline geometry
                centerline_info = hdf["Geometry/Structures/Centerline Info"][()]
                centerline_points = hdf["Geometry/Structures/Centerline Points"][()]
                
                # Create LineString geometries for each structure
                geoms = []
                for i in range(len(centerline_info)):
                    start_idx = centerline_info[i][0]  # Point Starting Index
                    point_count = centerline_info[i][1]  # Point Count
                    points = centerline_points[start_idx:start_idx + point_count]
                    if len(points) >= 2:
                        geoms.append(LineString(points))
                    else:
                        logger.warning(f"Insufficient points for LineString in structure index {i}.")
                        geoms.append(None)

                # Create base GeoDataFrame with Structures Attributes and geometries
                struct_gdf = GeoDataFrame(
                    struct_attrs,
                    geometry=geoms,
                    crs=HdfUtils.projection(hdf_path)
                )

                # Drop entries with invalid geometries
                initial_count = len(struct_gdf)
                struct_gdf = struct_gdf.dropna(subset=['geometry']).reset_index(drop=True)
                final_count = len(struct_gdf)
                if final_count < initial_count:
                    logger.warning(f"Dropped {initial_count - final_count} structures due to invalid geometries.")

                # Merge Bridge Coefficient Attributes on 'Structure ID'
                if not bridge_coef.empty and 'Structure ID' in bridge_coef.columns:
                    struct_gdf = struct_gdf.merge(
                        bridge_coef,
                        on='Structure ID',
                        how='left',
                        suffixes=('', '_bridge_coef')
                    )
                    logger.debug("Merged Bridge Coefficient Attributes successfully.")
                else:
                    logger.warning("Bridge Coefficient Attributes missing or 'Structure ID' not present.")

                # Merge Table Info based on the DataFrame index (one-to-one correspondence)
                if not table_info.empty:
                    if len(table_info) != len(struct_gdf):
                        logger.warning("Table Info count does not match Structures count. Skipping merge.")
                    else:
                        struct_gdf = pd.concat([struct_gdf, table_info.reset_index(drop=True)], axis=1)
                        logger.debug("Merged Table Info successfully.")
                else:
                    logger.warning("Table Info dataset is empty or missing.")

                # Process Profile Data based on Table Info
                if not profile_data.empty and not table_info.empty:
                    # Assuming 'Centerline Profile (Index)' and 'Centerline Profile (Count)' are in 'Table Info'
                    if ('Centerline Profile (Index)' in table_info.columns and
                        'Centerline Profile (Count)' in table_info.columns):
                        struct_gdf['Profile_Data'] = struct_gdf.apply(
                            lambda row: [
                                {'Station': float(profile_data.iloc[i, 0]),
                                 'Elevation': float(profile_data.iloc[i, 1])}
                                for i in range(
                                    int(row['Centerline Profile (Index)']),
                                    int(row['Centerline Profile (Index)']) + int(row['Centerline Profile (Count)'])
                                )
                            ],
                            axis=1
                        )
                        logger.debug("Processed Profile Data successfully.")
                    else:
                        logger.warning("Required columns for Profile Data not found in Table Info.")
                else:
                    logger.warning("Profile Data dataset is empty or Table Info is missing.")

                # Convert datetime columns to string if requested
                if datetime_to_str:
                    datetime_cols = struct_gdf.select_dtypes(include=['datetime64']).columns
                    for col in datetime_cols:
                        struct_gdf[col] = struct_gdf[col].dt.isoformat()
                        logger.debug(f"Converted datetime column '{col}' to string.")

                # Ensure all byte strings are decoded (if any remain)
                for col in struct_gdf.columns:
                    if struct_gdf[col].dtype == object:
                        struct_gdf[col] = struct_gdf[col].apply(
                            lambda x: x.decode('utf-8', errors='ignore') if isinstance(x, bytes) else x
                        )

                # Final GeoDataFrame
                logger.info("Successfully extracted structures GeoDataFrame.")
                return struct_gdf

        except Exception as e:
            logger.error(f"Error reading structures from {hdf_path}: {str(e)}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_geom_structures_attrs(hdf_path: Path) -> Dict[str, Any]:
        """
        Return geometry structures attributes from a HEC-RAS HDF file.

        This method extracts attributes related to geometry structures from the HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        Dict[str, Any]
            A dictionary containing the geometry structures attributes.

        Notes
        -----
        If no structures are found in the geometry file, an empty dictionary is returned.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/Structures" not in hdf_file:
                    logger.info(f"No structures found in the geometry file: {hdf_path}")
                    return {}
                return HdfUtils.get_attrs(hdf_file, "Geometry/Structures")
        except Exception as e:
            logger.error(f"Error reading geometry structures attributes: {str(e)}")
            return {}
