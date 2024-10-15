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

    GEOM_STRUCTURES_PATH = "Geometry/Structures"

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def structures(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model structures.

        This method extracts structure data from the HDF file, including geometry
        and attributes, and returns it as a GeoDataFrame.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the structures, with columns for attributes
            and geometry.

        Raises
        ------
        Exception
            If there's an error reading the structures data from the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check if the structures path exists in the HDF file
                if HdfStruc.GEOM_STRUCTURES_PATH not in hdf_file:
                    logger.info(f"No structures found in the geometry file: {hdf_path}")
                    return GeoDataFrame()
                
                struct_data = hdf_file[HdfStruc.GEOM_STRUCTURES_PATH]
                v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                sd_attrs = struct_data["Attributes"][()]
                
                # Create a dictionary to store structure data
                struct_dict = {"struct_id": range(sd_attrs.shape[0])}
                struct_dict.update(
                    {name: v_conv_val(sd_attrs[name]) for name in sd_attrs.dtype.names}
                )
                
                # Get structure geometries
                geoms = HdfXsec._get_polylines(
                    hdf_path,
                    HdfStruc.GEOM_STRUCTURES_PATH,
                    info_name="Centerline Info",
                    parts_name="Centerline Parts",
                    points_name="Centerline Points"
                )
                
                # Create GeoDataFrame
                struct_gdf = GeoDataFrame(
                    struct_dict,
                    geometry=geoms,
                    crs=HdfUtils.projection(hdf_path),
                )
                
                # Convert datetime to string if requested
                if datetime_to_str:
                    struct_gdf["Last Edited"] = struct_gdf["Last Edited"].apply(
                        lambda x: pd.Timestamp.isoformat(x) if pd.notnull(x) else None
                    )
                
                return struct_gdf
        except Exception as e:
            logger.error(f"Error reading structures: {str(e)}")
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
                if HdfStruc.GEOM_STRUCTURES_PATH not in hdf_file:
                    logger.info(f"No structures found in the geometry file: {hdf_path}")
                    return {}
                return HdfUtils.get_attrs(hdf_file, HdfStruc.GEOM_STRUCTURES_PATH)
        except Exception as e:
            logger.error(f"Error reading geometry structures attributes: {str(e)}")
            return {}
