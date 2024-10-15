"""
Class: HdfUtils

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""
import logging
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Union, Optional, Dict, List, Tuple, Any
from scipy.spatial import KDTree
import re

from .Decorators import standardize_input, log_call 
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfUtils:
    """
    Utility class for working with HEC-RAS HDF files.

    This class provides general utility functions for HDF file operations,
    including attribute extraction, data conversion, and common HDF queries.
    It also includes spatial operations and helper methods for working with
    HEC-RAS specific data structures.

    Note:
    - Use this class for general HDF utility functions that are not specific to plan or geometry files.
    - All methods in this class are static and can be called without instantiating the class.
    """

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_hdf_filename(hdf_input: Union[str, Path, h5py.File], ras_object=None) -> Optional[Path]:
        """
        Get the HDF filename from various input types.

        Args:
            hdf_input (Union[str, Path, h5py.File]): The plan number, full path to the HDF file, or an open HDF file object.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[Path]: Path to the HDF file, or None if not found.
        """
        if isinstance(hdf_input, h5py.File):
            return Path(hdf_input.filename)

        if isinstance(hdf_input, str):
            hdf_input = Path(hdf_input)

        if isinstance(hdf_input, Path) and hdf_input.is_file():
            return hdf_input

        if ras_object is None:
            logger.critical("RAS object is not provided. It is required when hdf_input is not a direct file path.")
            return None

        plan_info = ras_object.plan_df[ras_object.plan_df['plan_number'] == str(hdf_input)]
        if plan_info.empty:
            logger.critical(f"No HDF file found for plan number {hdf_input}")
            return None

        hdf_filename = plan_info.iloc[0]['HDF_Results_Path']
        if hdf_filename is None:
            logger.critical(f"HDF_Results_Path is None for plan number {hdf_input}")
            return None

        hdf_path = Path(hdf_filename)
        if not hdf_path.is_file():
            logger.critical(f"HDF file not found: {hdf_path}")
            return None

        return hdf_path

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_root_attrs(hdf_path: Path) -> dict:
        """
        Return attributes at root level of HEC-RAS HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            dict: Dictionary filled with HEC-RAS HDF root attributes.
        """
        with h5py.File(hdf_path, 'r') as hdf_file:
            return HdfUtils.get_attrs(hdf_file, "/")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_attrs(hdf_path: Path, attr_path: str) -> dict:
        """
        Get attributes from a HEC-RAS HDF file for a given attribute path.

        Args:
            hdf_path (Path): The path to the HDF file.
            attr_path (str): The path to the attributes within the HDF file.

        Returns:
            dict: A dictionary of attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                attr_object = hdf_file.get(attr_path)
                if attr_object is None:
                    logger.warning(f"Attribute path '{attr_path}' not found in HDF file.")
                    return {}
                return HdfUtils._hdf5_attrs_to_dict(attr_object.attrs)
        except Exception as e:
            logger.error(f"Error getting attributes from '{attr_path}': {str(e)}")
            return {}

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_hdf_paths_with_properties(hdf_path: Path) -> pd.DataFrame:
        """
        Get all paths in the HDF file with their properties.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing paths and their properties.
        """
        def get_item_properties(item):
            return {
                'name': item.name,
                'type': type(item).__name__,
                'shape': item.shape if hasattr(item, 'shape') else None,
                'dtype': item.dtype if hasattr(item, 'dtype') else None
            }

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                items = []
                hdf_file.visititems(lambda name, item: items.append(get_item_properties(item)))

            return pd.DataFrame(items)
        except Exception as e:
            logger.error(f"Error reading HDF file: {e}")
            return pd.DataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_group_attributes_as_df(hdf_path: Path, group_path: str) -> pd.DataFrame:
        """
        Get attributes of a group in the HDF file as a DataFrame.

        Args:
            hdf_path (Path): Path to the HDF file.
            group_path (str): Path to the group within the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing the group's attributes.
        """
        with h5py.File(hdf_path, 'r') as hdf_file:
            group = hdf_file[group_path]
            attributes = {key: group.attrs[key] for key in group.attrs.keys()}
            return pd.DataFrame([attributes])


    @staticmethod
    def convert_ras_hdf_string(value: Union[str, bytes]) -> Union[bool, datetime, List[datetime], timedelta, str]:
        """
        Convert a string value from an HEC-RAS HDF file into a Python object.

        Args:
            value (Union[str, bytes]): The value to convert.

        Returns:
            Union[bool, datetime, List[datetime], timedelta, str]: The converted value.
        """
        return HdfUtils._convert_ras_hdf_string(value)

    @staticmethod
    def df_datetimes_to_str(df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert any datetime64 columns in a DataFrame to strings.

        Args:
            df (pd.DataFrame): The DataFrame to convert.

        Returns:
            pd.DataFrame: The DataFrame with datetime columns converted to strings.
        """
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        return df

    @staticmethod
    def perform_kdtree_query(
        reference_points: np.ndarray,
        query_points: np.ndarray,
        max_distance: float = 2.0
    ) -> np.ndarray:
        """
        Performs a KDTree query between two datasets and returns indices with distances exceeding max_distance set to -1.

        Args:
            reference_points (np.ndarray): The reference dataset for KDTree.
            query_points (np.ndarray): The query dataset to search against KDTree of reference_points.
            max_distance (float, optional): The maximum distance threshold. Indices with distances greater than this are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices from reference_points that are nearest to each point in query_points. 
                        Indices with distances > max_distance are set to -1.

        Example:
            >>> ref_points = np.array([[0, 0], [1, 1], [2, 2]])
            >>> query_points = np.array([[0.5, 0.5], [3, 3]])
            >>> result = HdfUtils.perform_kdtree_query(ref_points, query_points)
            >>> print(result)
            array([ 0, -1])
        """
        dist, snap = KDTree(reference_points).query(query_points, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        return snap

    @staticmethod
    def find_nearest_neighbors(points: np.ndarray, max_distance: float = 2.0) -> np.ndarray:
        """
        Creates a self KDTree for dataset points and finds nearest neighbors excluding self, 
        with distances above max_distance set to -1.

        Args:
            points (np.ndarray): The dataset to build the KDTree from and query against itself.
            max_distance (float, optional): The maximum distance threshold. Indices with distances 
                                            greater than max_distance are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices representing the nearest neighbor in points for each point in points. 
                        Indices with distances > max_distance or self-matches are set to -1.

        Example:
            >>> points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
            >>> result = HdfUtils.find_nearest_neighbors(points)
            >>> print(result)
            array([1, 0, 1, -1])
        """
        dist, snap = KDTree(points).query(points, k=2, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        
        snp = pd.DataFrame(snap, index=np.arange(len(snap)))
        snp = snp.replace(-1, np.nan)
        snp.loc[snp[0] == snp.index, 0] = np.nan
        snp.loc[snp[1] == snp.index, 1] = np.nan
        filled = snp[0].fillna(snp[1])
        snapped = filled.fillna(-1).astype(np.int64).to_numpy()
        return snapped

    @staticmethod
    def _convert_ras_hdf_string(value: Union[str, bytes]) -> Union[bool, datetime, List[datetime], timedelta, str]:
        """
        Private method to convert a string value from an HEC-RAS HDF file into a Python object.

        Args:
            value (Union[str, bytes]): The value to convert.

        Returns:
            Union[bool, datetime, List[datetime], timedelta, str]: The converted value.
        """
        if isinstance(value, bytes):
            s = value.decode("utf-8")
        else:
            s = value

        if s == "True":
            return True
        elif s == "False":
            return False
        
        ras_datetime_format1_re = r"\d{2}\w{3}\d{4} \d{2}:\d{2}:\d{2}"
        ras_datetime_format2_re = r"\d{2}\w{3}\d{4} \d{2}\d{2}"
        ras_duration_format_re = r"\d{2}:\d{2}:\d{2}"

        if re.match(rf"^{ras_datetime_format1_re}", s):
            if re.match(rf"^{ras_datetime_format1_re} to {ras_datetime_format1_re}$", s):
                split = s.split(" to ")
                return [
                    HdfBase._parse_ras_datetime(split[0]),
                    HdfBase._parse_ras_datetime(split[1]),
                ]
            return HdfBase._parse_ras_datetime(s)
        elif re.match(rf"^{ras_datetime_format2_re}", s):
            if re.match(rf"^{ras_datetime_format2_re} to {ras_datetime_format2_re}$", s):
                split = s.split(" to ")
                return [
                    HdfBase._parse_ras_simulation_window_datetime(split[0]),
                    HdfBase._parse_ras_simulation_window_datetime(split[1]),
                ]
            return HdfBase._parse_ras_simulation_window_datetime(s)
        elif re.match(rf"^{ras_duration_format_re}$", s):
            return HdfBase._parse_duration(s)
        return s

    @staticmethod
    def _convert_ras_hdf_value(value: Any) -> Union[None, bool, str, List[str], int, float, List[int], List[float]]:
        """
        Convert a value from a HEC-RAS HDF file into a Python object.

        Args:
            value (Any): The value to convert.

        Returns:
            Union[None, bool, str, List[str], int, float, List[int], List[float]]: The converted value.
        """
        if isinstance(value, np.floating) and np.isnan(value):
            return None
        elif isinstance(value, (bytes, np.bytes_)):
            return value.decode('utf-8')
        elif isinstance(value, np.integer):
            return int(value)
        elif isinstance(value, np.floating):
            return float(value)
        elif isinstance(value, (int, float)):
            return value
        elif isinstance(value, (list, tuple, np.ndarray)):
            if len(value) > 1:
                return [HdfUtils._convert_ras_hdf_value(v) for v in value]
            else:
                return HdfUtils._convert_ras_hdf_value(value[0])
        else:
            return str(value)

    @staticmethod
    def _parse_ras_datetime_ms(datetime_str: str) -> datetime:
        """
        Private method to parse a datetime string with milliseconds from a RAS file.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        milliseconds = int(datetime_str[-3:])
        microseconds = milliseconds * 1000
        parsed_dt = HdfBase._parse_ras_datetime(datetime_str[:-4]).replace(microsecond=microseconds)
        return parsed_dt

    @staticmethod
    def _ras_timesteps_to_datetimes(timesteps: np.ndarray, start_time: datetime, time_unit: str, round_to: str = "0.1 s") -> List[datetime]:
        """
        Convert an array of RAS timesteps into a list of datetime objects.

        Args:
            timesteps (np.ndarray): An array of RAS timesteps.
            start_time (datetime): The start time of the simulation.
            time_unit (str): The time unit of the timesteps.
            round_to (str): The time unit to round the datetimes to. Default is "0.1 s".

        Returns:
            List[datetime]: A list of datetime objects corresponding to the timesteps.

        Note:
            The `round_to` parameter uses Pandas time string notation. For example:
            - "0.1 s" means round to the nearest 0.1 seconds
            - "1 s" means round to the nearest second
            - "1 min" means round to the nearest minute
            For more options, see Pandas documentation on time string notation.
        """
        return [
            start_time + pd.Timedelta(timestep, unit=time_unit).round(round_to)
            for timestep in timesteps.astype(np.float64)
        ]

    @staticmethod
    def _hdf5_attrs_to_dict(attrs: Union[h5py.AttributeManager, Dict], prefix: Optional[str] = None) -> Dict:
        """
        Private method to convert HDF5 attributes to a Python dictionary.

        Args:
            attrs (Union[h5py.AttributeManager, Dict]): The attributes to convert.
            prefix (Optional[str]): A prefix to add to the attribute keys.

        Returns:
            Dict: A dictionary of converted attributes.
        """
        result = {}
        for key, value in attrs.items():
            if prefix:
                key = f"{prefix}/{key}"
            if isinstance(value, (np.ndarray, list)):
                result[key] = [HdfUtils._convert_ras_hdf_value(v) for v in value]
            else:
                result[key] = HdfUtils._convert_ras_hdf_value(value)
        return result

    @staticmethod
    def parse_run_time_window(window: str) -> Tuple[datetime, datetime]:
        """
        Parse a run time window string into a tuple of datetime objects.

        Args:
            window (str): The run time window string to be parsed.

        Returns:
            Tuple[datetime, datetime]: A tuple containing two datetime objects representing the start and end of the run
            time window.
        """
        split = window.split(" to ")
        begin = HdfBase._parse_ras_datetime(split[0])
        end = HdfBase._parse_ras_datetime(split[1])
        return begin, end

    

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
                names = [HdfUtils._convert_ras_hdf_string(name) for name in attributes["Name"]]
                
                cell_info = hdf_file[f"{flow_area_2d_path}/Cell Info"][()]
                cell_counts = [info[1] for info in cell_info]
                
                return list(zip(names, cell_counts))
        except Exception as e:
            logger.error(f"Error reading 2D flow area names and counts from {hdf_path}: {str(e)}")
            raise ValueError(f"Failed to get 2D flow area names and counts: {str(e)}")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def projection(hdf_path: Path) -> Optional[str]:
        """
        Get the projection information from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            Optional[str]: The projection information as a string, or None if not found.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                proj_wkt = hdf_file.attrs.get("Projection")
                if proj_wkt is None:
                    return None
                if isinstance(proj_wkt, bytes) or isinstance(proj_wkt, np.bytes_):
                    proj_wkt = proj_wkt.decode("utf-8")
                return proj_wkt
        except Exception as e:
            logger.error(f"Error reading projection from {hdf_path}: {str(e)}")
            return None
