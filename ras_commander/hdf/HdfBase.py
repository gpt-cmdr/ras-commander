"""
HdfBase: Core HDF File Operations for HEC-RAS

This module provides fundamental methods for interacting with HEC-RAS HDF files.
It serves as a foundation for more specialized HDF classes.

Attribution:
    Derived from the rashdf library (https://github.com/fema-ffrd/rashdf)
    Copyright (c) 2024 fema-ffrd - MIT License

Features:
    - Time parsing and conversion utilities
    - HDF attribute and dataset access
    - Geometric data extraction
    - 2D flow area information retrieval

Classes:
    HdfBase: Base class containing static methods for HDF operations

Key Methods:
    Time Operations:
        - get_simulation_start_time(): Get simulation start datetime
        - get_unsteady_timestamps(): Get unsteady output timestamps
        - parse_ras_datetime(): Parse RAS datetime strings
    
    Data Access:
        - get_2d_flow_area_names_and_counts(): Get 2D flow area info
        - get_projection(): Get spatial projection
        - get_attrs(): Access HDF attributes
        - get_dataset_info(): Explore HDF structure
        - get_polylines_from_parts(): Extract geometric polylines

Example:
    ```python
    from ras_commander import HdfBase
    
    with h5py.File('model.hdf', 'r') as hdf:
        start_time = HdfBase.get_simulation_start_time(hdf)
        timestamps = HdfBase.get_unsteady_timestamps(hdf)
    ```
"""
import re
from datetime import datetime, timedelta
import h5py
import numpy as np
import pandas as pd
import xarray as xr
from typing import List, Tuple, Union, Optional, Dict, Any
from pathlib import Path
import logging
from shapely.geometry import LineString, MultiLineString

from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfBase:
    """
    Base class for HEC-RAS HDF file operations.

    This class provides static methods for fundamental HDF file operations,
    including time parsing, attribute access, and geometric data extraction.
    All methods are designed to work with h5py.File objects or pathlib.Path
    inputs.

    Note:
        This class is not meant to be instantiated. All methods are static
        and should be called directly from the class.
    """

    @staticmethod
    def get_simulation_start_time(hdf_file: h5py.File) -> datetime:
        """
        Extract the simulation start time from the HDF file.

        Args:
            hdf_file: Open HDF file object containing RAS simulation data.

        Returns:
            datetime: Simulation start time as a datetime object.

        Raises:
            ValueError: If Plan Information is not found or start time cannot be parsed.
        
        Note:
            Expects 'Plan Data/Plan Information' group with 'Simulation Start Time' attribute.
        """
        plan_info = hdf_file.get("Plan Data/Plan Information")
        if plan_info is None:
            raise ValueError("Plan Information not found in HDF file")
        time_str = plan_info.attrs.get('Simulation Start Time')
        return HdfUtils.parse_ras_datetime(time_str.decode('utf-8'))

    @staticmethod
    def get_unsteady_timestamps(hdf_file: h5py.File) -> List[datetime]:
        """
        Extract the list of unsteady timestamps from the HDF file.

        Args:
            hdf_file (h5py.File): Open HDF file object.

        Returns:
            List[datetime]: A list of datetime objects representing the unsteady timestamps.
        """
        group_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp (ms)"
        raw_datetimes = hdf_file[group_path][:]
        return [HdfUtils.parse_ras_datetime_ms(x.decode("utf-8")) for x in raw_datetimes]

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_2d_flow_area_names_and_counts(hdf_path: Path) -> List[Tuple[str, int]]:
        """
        Get the names and cell counts of 2D flow areas from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            List[Tuple[str, int]]: A list of tuples containing the name and cell count of each 2D flow area.

        Raises:
            ValueError: If there's an error reading the HDF file or accessing the required data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                flow_area_2d_path = "Geometry/2D Flow Areas"
                if flow_area_2d_path not in hdf_file:
                    return []
                
                attributes = hdf_file[f"{flow_area_2d_path}/Attributes"][()]
                names = [HdfUtils.convert_ras_string(name) for name in attributes["Name"]]
                
                cell_info = hdf_file[f"{flow_area_2d_path}/Cell Info"][()]
                cell_counts = [info[1] for info in cell_info]
                
                return list(zip(names, cell_counts))
        except Exception as e:
            logger.error(f"Error reading 2D flow area names and counts from {hdf_path}: {str(e)}")
            raise ValueError(f"Failed to get 2D flow area names and counts: {str(e)}")


    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_projection(hdf_path: Path) -> Optional[str]:
        """
        Get projection information from HDF file or RASMapper project file.
        Converts WKT projection to EPSG code for GeoDataFrame compatibility.
        
        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            Optional[str]: The projection as EPSG code (e.g. "EPSG:6556"), WKT string if no 
                          EPSG match found, or None if no projection found.
        """
        from pyproj import CRS

        def wkt_to_crs_string(wkt_string: str, source: str) -> str:
            """Convert WKT to EPSG code if possible, otherwise return WKT."""
            try:
                crs = CRS.from_wkt(wkt_string)
                # Try to get EPSG code
                epsg = crs.to_epsg()
                if epsg:
                    epsg_str = f"EPSG:{epsg}"
                    logger.info(f"Converted WKT to {epsg_str} from {source}")
                    return epsg_str
                else:
                    # No EPSG match - return WKT (pyproj/geopandas can still use it)
                    logger.debug(f"No EPSG match for CRS '{crs.name}' from {source}, using WKT")
                    return wkt_string
            except Exception as e:
                logger.warning(f"Could not parse WKT from {source}: {e}. Returning raw WKT.")
                return wkt_string

        project_folder = hdf_path.parent
        wkt = None
        proj_file = None  # Initialize proj_file variable
        
        # Try HDF file
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                proj_wkt = hdf_file.attrs.get("Projection")
                if proj_wkt is not None:
                    if isinstance(proj_wkt, (bytes, np.bytes_)):
                        wkt = proj_wkt.decode("utf-8")
                        logger.info(f"Found projection in HDF file: {hdf_path}")
                        return wkt_to_crs_string(wkt, f"HDF file {hdf_path.name}")
        except Exception as e:
            logger.error(f"Error reading projection from HDF file {hdf_path}: {str(e)}")

        # Try RASMapper file if no HDF projection
        if not wkt:
            try:
                rasmap_files = list(project_folder.glob("*.rasmap"))
                if rasmap_files:
                    with open(rasmap_files[0], 'r') as f:
                        content = f.read()
                        
                    proj_match = re.search(r'<RASProjectionFilename Filename="(.*?)"', content)
                    if proj_match:
                        proj_file = project_folder / proj_match.group(1).replace('.\\', '')
                        if proj_file.exists():
                            with open(proj_file, 'r') as f:
                                wkt = f.read().strip()
                                logger.info(f"Found projection in RASMapper file: {proj_file}")
                                return wkt_to_crs_string(wkt, f"RASMapper file {proj_file.name}")
            except Exception as e:
                logger.error(f"Error reading RASMapper projection file: {str(e)}")
        
        # Customize error message based on whether proj_file was found
        if proj_file:
            error_msg = (
                "No valid projection found. Checked:\n"
                f"1. HDF file projection attribute: {hdf_path}\n"
                f"2. RASMapper projection file {proj_file} found in RASMapper file, but was invalid"
            )
        else:
            error_msg = (
                "No valid projection found. Checked:\n"
                f"1. HDF file projection attribute: {hdf_path}\n was checked and no projection attribute found"
                "2. No RASMapper projection file found"
            )

        error_msg += (
            "\nTo fix this:\n"
            "1. Open RASMapper\n"
            "2. Click Map > Set Projection\n" 
            "3. Select an appropriate projection file or coordinate system\n"
            "4. Save the RASMapper project"
        )
        
        logger.critical(error_msg)
        return None

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_attrs(hdf_file: h5py.File, attr_path: str) -> Dict[str, Any]:
        """
        Get attributes from an HDF file at a specified path.

        Args:
            hdf_file (h5py.File): The opened HDF file.
            attr_path (str): Path to the attributes in the HDF file.

        Returns:
            Dict[str, Any]: Dictionary of attributes.
        """
        try:
            if attr_path not in hdf_file:
                logger.warning(f"Path {attr_path} not found in HDF file")
                return {}
            
            return HdfUtils.convert_hdf5_attrs_to_dict(hdf_file[attr_path].attrs)
        except Exception as e:
            logger.error(f"Error getting attributes from {attr_path}: {str(e)}")
            return {}

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_dataset_info(file_path: Path, group_path: str = '/') -> None:
        """
        Recursively explore and print the structure of an HDF5 file.

        Displays detailed information about groups, datasets, and their attributes
        in a hierarchical format.

        Args:
            file_path: Path to the HDF5 file.
            group_path: Starting group path to explore (default: root '/').

        Prints:
            - Group and dataset names with hierarchical indentation
            - Dataset shapes and data types
            - All attributes for groups and datasets
        """
        def recurse(name, obj, indent=0):
            spacer = "    " * indent
            if isinstance(obj, h5py.Group):
                print(f"{spacer}Group: {name}")
                HdfBase.print_attrs(name, obj)
                for key in obj:
                    recurse(f"{name}/{key}", obj[key], indent+1)
            elif isinstance(obj, h5py.Dataset):
                print(f"{spacer}Dataset: {name}")
                print(f"{spacer}    Shape: {obj.shape}")
                print(f"{spacer}    Dtype: {obj.dtype}")
                HdfBase.print_attrs(name, obj)
            else:
                print(f"{spacer}Unknown object: {name}")

        try:
            with h5py.File(file_path, 'r') as hdf_file:
                if group_path in hdf_file:
                    print("")
                    print(f"Exploring group: {group_path}\n")
                    group = hdf_file[group_path]
                    for key in group:
                        print("")
                        recurse(f"{group_path}/{key}", group[key], indent=1)
                else:
                    print(f"Group path '{group_path}' not found in the HDF5 file.")
        except Exception as e:
            print(f"Error exploring HDF5 file: {e}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_polylines_from_parts(hdf_path: Path, path: str, info_name: str = "Polyline Info", 
                              parts_name: str = "Polyline Parts", 
                              points_name: str = "Polyline Points") -> List[LineString]:
        """
        Extract polylines from HDF file parts data.

        Args:
            hdf_path: Path to the HDF file.
            path: Internal HDF path to polyline data.
            info_name: Name of polyline info dataset.
            parts_name: Name of polyline parts dataset.
            points_name: Name of polyline points dataset.

        Returns:
            List of Shapely LineString/MultiLineString geometries.

        Note:
            Expects HDF datasets containing:
            - Polyline information (start points and counts)
            - Parts information for multi-part lines
            - Point coordinates
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

    @staticmethod
    def print_attrs(name: str, obj: Union[h5py.Dataset, h5py.Group]) -> None:
        """
        Print the attributes of an HDF5 object (Dataset or Group).

        Args:
            name (str): Name of the object
            obj (Union[h5py.Dataset, h5py.Group]): HDF5 object whose attributes are to be printed
        """
        if len(obj.attrs) > 0:
            print(f"    Attributes for {name}:")
            for key, value in obj.attrs.items():
                print(f"        {key}: {value}")



