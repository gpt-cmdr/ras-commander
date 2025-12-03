"""
Class: HdfStruc

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfStruc:
- get_structures()
- get_geom_structures_attrs()
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
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfStruc:
    """
    Handles 2D structure geometry data extraction from HEC-RAS HDF files.

    This class provides static methods for extracting and analyzing structure geometries
    and their attributes from HEC-RAS geometry HDF files. All methods are designed to work
    without class instantiation.

    Notes
    -----
    - 1D Structure data should be accessed via the HdfResultsXsec class
    - All methods use @standardize_input for consistent file handling
    - All methods use @log_call for operation logging
    - Returns GeoDataFrames with both geometric and attribute data
    """
    
    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_structures(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extracts structure data from a HEC-RAS geometry HDF5 file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF5 file
        datetime_to_str : bool, optional
            If True, converts datetime objects to ISO format strings, by default False

        Returns
        -------
        GeoDataFrame
            Structure data with columns:
            - Structure ID: unique identifier
            - Geometry: LineString of structure centerline
            - Various attribute columns from the HDF file
            - Profile_Data: list of station/elevation dictionaries
            - Bridge coefficient attributes (if present)
            - Table info attributes (if present)

        Notes
        -----
        - Group-level attributes are stored in GeoDataFrame.attrs['group_attributes']
        - Invalid geometries are dropped with warning
        - All byte strings are decoded to UTF-8
        - CRS is preserved from the source file
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if "Geometry/Structures" not in hdf:
                    logger.error(f"No Structures Found in the HDF, Empty Geodataframe Returned: {hdf_path}")
                    return GeoDataFrame()
                
                # Check if required datasets exist
                required_datasets = [
                    "Geometry/Structures/Centerline Info",
                    "Geometry/Structures/Centerline Points"
                ]
                
                for dataset in required_datasets:
                    if dataset not in hdf:
                        logger.error(f"No Structures Found in the HDF, Empty Geodataframe Returned: {hdf_path}")
                        return GeoDataFrame()

                def get_dataset_df(path: str) -> pd.DataFrame:
                    """
                    Converts an HDF5 dataset to a pandas DataFrame.

                    Parameters
                    ----------
                    path : str
                        Dataset path within the HDF5 file

                    Returns
                    -------
                    pd.DataFrame
                        DataFrame containing the dataset values.
                        - For compound datasets, column names match field names
                        - For simple datasets, generic column names (Value_0, Value_1, etc.)
                        - Empty DataFrame if dataset not found

                    Notes
                    -----
                    Automatically decodes byte strings to UTF-8 with error handling.
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
                group_attrs = HdfBase.get_attrs(hdf, "Geometry/Structures")
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
                    crs=HdfBase.get_projection(hdf_path)
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
                
                # Add group attributes to the GeoDataFrame's attrs['group_attributes']
                struct_gdf.attrs['group_attributes'] = group_attrs
                
                logger.info("Successfully extracted structures GeoDataFrame with attributes.")
                
                return struct_gdf

        except Exception as e:
            logger.error(f"Error reading structures from {hdf_path}: {str(e)}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_geom_structures_attrs(hdf_path: Path) -> pd.DataFrame:
        """
        Extracts structure attributes from a HEC-RAS geometry HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file

        Returns
        -------
        pd.DataFrame
            DataFrame containing structure attributes from the Geometry/Structures group.
            Returns empty DataFrame if no structures are found.

        Notes
        -----
        Attributes are extracted from the HDF5 group 'Geometry/Structures'.
        All byte strings in attributes are automatically decoded to UTF-8.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/Structures" not in hdf_file:
                    logger.info(f"No structures found in the geometry file: {hdf_path}")
                    return pd.DataFrame()
                
                # Get attributes and decode byte strings
                attrs_dict = {}
                for key, value in dict(hdf_file["Geometry/Structures"].attrs).items():
                    if isinstance(value, bytes):
                        attrs_dict[key] = value.decode('utf-8')
                    else:
                        attrs_dict[key] = value
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])

        except Exception as e:
            logger.error(f"Error reading geometry structures attributes: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def list_sa2d_connections(hdf_path: Path, *, ras_object=None) -> List[str]:
        """
        List all SA/2D Area Connection structures in HDF results file.

        This includes both breach structures and regular SA/2D connections with
        time series results.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        List[str]
            Names of all SA/2D Area Connection structures with time series results.
            Returns empty list if no SA/2D connections found.

        Examples
        --------
        >>> structures = HdfStruc.list_sa2d_connections("02")
        >>> print(structures)
        ['Laxton_Dam', 'PineCreek#1_Dam', 'US_2DArea_Res2']

        Notes
        -----
        - Not all structures returned have breach capability
        - Use get_sa2d_breach_info() to determine which have "Breaching Variables"
        - Empty list returned if no SA/2D connections in results
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA 2D Area Conn"

                if base_path not in hdf_file:
                    logger.warning(f"No SA 2D Area Conn data found in {hdf_path.name}")
                    return []

                # List all groups (structure names) under SA 2D Area Conn
                structures = list(hdf_file[base_path].keys())
                logger.info(f"Found {len(structures)} SA/2D connection structures: {structures}")
                return structures

        except Exception as e:
            logger.error(f"Error listing SA/2D connection structures: {e}")
            return []

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_sa2d_breach_info(hdf_path: Path, *, ras_object=None) -> pd.DataFrame:
        """
        Get information about which SA/2D connection structures have breach capability.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - structure: Structure name
            - has_breach: Boolean, True if "Breaching Variables" dataset exists
            - breach_at_time: Time of breach initiation (if available)
            - breach_at_date: Date/time of breach (if available)
            - centerline_breach: Centerline station for breach (if available)

        Examples
        --------
        >>> info = HdfStruc.get_sa2d_breach_info("02")
        >>> breach_dams = info[info['has_breach']]['structure'].tolist()
        >>> print(f"Breach structures: {breach_dams}")

        Notes
        -----
        - Returns empty DataFrame if no SA/2D connections found
        - Only structures with "Breaching Variables" have has_breach=True
        - Use in conjunction with RasBreach for reading/modifying breach parameters
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                structures = HdfStruc.list_sa2d_connections(hdf_path, ras_object=ras_object)

                if not structures:
                    return pd.DataFrame()

                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA 2D Area Conn"

                info_list = []
                for struct_name in structures:
                    struct_path = f"{base_path}/{struct_name}"
                    breach_var_path = f"{struct_path}/Breaching Variables"

                    info = {'structure': struct_name}

                    # Check if breach variables exist
                    if breach_var_path in hdf_file:
                        info['has_breach'] = True

                        # Extract breach metadata from attributes
                        breach_dataset = hdf_file[breach_var_path]
                        if 'Breach at' in breach_dataset.attrs:
                            breach_at = breach_dataset.attrs['Breach at']
                            info['breach_at_date'] = breach_at.decode('utf-8') if isinstance(breach_at, bytes) else breach_at
                        else:
                            info['breach_at_date'] = None

                        if 'Breach at Time (Days)' in breach_dataset.attrs:
                            info['breach_at_time'] = float(breach_dataset.attrs['Breach at Time (Days)'])
                        else:
                            info['breach_at_time'] = None

                        if 'Centerline Breach' in breach_dataset.attrs:
                            info['centerline_breach'] = float(breach_dataset.attrs['Centerline Breach'])
                        else:
                            info['centerline_breach'] = None
                    else:
                        info['has_breach'] = False
                        info['breach_at_date'] = None
                        info['breach_at_time'] = None
                        info['centerline_breach'] = None

                    info_list.append(info)

                return pd.DataFrame(info_list)

        except Exception as e:
            logger.error(f"Error getting SA/2D breach info: {e}")
            raise
