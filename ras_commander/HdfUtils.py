"""
HdfUtils Class
-------------

A utility class providing static methods for working with HEC-RAS HDF files.

Attribution:
    A substantial amount of code in this file is sourced or derived from the 
    https://github.com/fema-ffrd/rashdf library, released under MIT license 
    and Copyright (c) 2024 fema-ffrd. The file has been forked and modified 
    for use in RAS Commander.

Key Features:
- HDF file data conversion and parsing
- DateTime handling for RAS-specific formats
- Spatial operations using KDTree
- HDF attribute management

Main Method Categories:

1. Data Conversion
    - convert_ras_string: Convert RAS HDF strings to Python objects
    - convert_ras_hdf_value: Convert general HDF values to Python objects
    - convert_df_datetimes_to_str: Convert DataFrame datetime columns to strings
    - convert_hdf5_attrs_to_dict: Convert HDF5 attributes to dictionary
    - convert_timesteps_to_datetimes: Convert timesteps to datetime objects

2. Spatial Operations
    - perform_kdtree_query: KDTree search between datasets
    - find_nearest_neighbors: Find nearest neighbors within dataset

3. DateTime Parsing
    - parse_ras_datetime: Parse standard RAS datetime format (ddMMMYYYY HH:MM:SS)
    - parse_ras_window_datetime: Parse simulation window datetime (ddMMMYYYY HHMM)
    - parse_duration: Parse duration strings (HH:MM:SS)
    - parse_ras_datetime_ms: Parse datetime with milliseconds
    - parse_run_time_window: Parse time window strings

Usage Notes:
- All methods are static and can be called without class instantiation
- Methods handle both raw HDF data and converted Python objects
- Includes comprehensive error handling for RAS-specific data formats
- Supports various RAS datetime formats and conversions
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
from shapely.geometry import LineString  # Import LineString to avoid NameError

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




# RENAME TO convert_ras_string and make public

    @staticmethod
    def convert_ras_string(value: Union[str, bytes]) -> Union[bool, datetime, List[datetime], timedelta, str]:
        """
        Convert a string value from an HEC-RAS HDF file into a Python object.

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
                    HdfUtils.parse_ras_datetime(split[0]),
                    HdfUtils.parse_ras_datetime(split[1]),
                ]
            return HdfUtils.parse_ras_datetime(s)
        elif re.match(rf"^{ras_datetime_format2_re}", s):
            if re.match(rf"^{ras_datetime_format2_re} to {ras_datetime_format2_re}$", s):
                split = s.split(" to ")
                return [
                    HdfUtils.parse_ras_window_datetime(split[0]),
                    HdfUtils.parse_ras_window_datetime(split[1]),
                ]
            return HdfUtils.parse_ras_window_datetime(s)
        elif re.match(rf"^{ras_duration_format_re}$", s):
            return HdfUtils.parse_ras_duration(s)
        return s





    @staticmethod
    def convert_ras_hdf_value(value: Any) -> Union[None, bool, str, List[str], int, float, List[int], List[float]]:
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
                return [HdfUtils.convert_ras_hdf_value(v) for v in value]
            else:
                return HdfUtils.convert_ras_hdf_value(value[0])
        else:
            return str(value)










# RENAME TO convert_df_datetimes_to_str 

    @staticmethod
    def convert_df_datetimes_to_str(df: pd.DataFrame) -> pd.DataFrame:
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


# KDTree Methods: 


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




# Datetime Parsing Methods: 

    @staticmethod
    @log_call
    def parse_ras_datetime_ms(datetime_str: str) -> datetime:
        """
        Public method to parse a datetime string with milliseconds from a RAS file.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        milliseconds = int(datetime_str[-3:])
        microseconds = milliseconds * 1000
        parsed_dt = HdfUtils.parse_ras_datetime(datetime_str[:-4]).replace(microsecond=microseconds)
        return parsed_dt
    
# Rename to convert_timesteps_to_datetimes and make public
    @staticmethod
    def convert_timesteps_to_datetimes(timesteps: np.ndarray, start_time: datetime, time_unit: str = "days", round_to: str = "100ms") -> pd.DatetimeIndex:
        """
        Convert RAS timesteps to datetime objects.

        Args:
            timesteps (np.ndarray): Array of timesteps.
            start_time (datetime): Start time of the simulation.
            time_unit (str): Unit of the timesteps. Default is "days".
            round_to (str): Frequency string to round the times to. Default is "100ms" (100 milliseconds).

        Returns:
            pd.DatetimeIndex: DatetimeIndex of converted and rounded datetimes.
        """
        if time_unit == "days":
            datetimes = start_time + pd.to_timedelta(timesteps, unit='D')
        elif time_unit == "hours":
            datetimes = start_time + pd.to_timedelta(timesteps, unit='H')
        else:
            raise ValueError(f"Unsupported time unit: {time_unit}")

        return pd.DatetimeIndex(datetimes).round(round_to)
    
# rename to convert_hdf5_attrs_to_dict and make public

    @staticmethod
    def convert_hdf5_attrs_to_dict(attrs: Union[h5py.AttributeManager, Dict], prefix: Optional[str] = None) -> Dict:
        """
        Convert HDF5 attributes to a Python dictionary.

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
                result[key] = [HdfUtils.convert_ras_hdf_value(v) for v in value]
            else:
                result[key] = HdfUtils.convert_ras_hdf_value(value)
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
        begin = HdfUtils._parse_ras_datetime(split[0])
        end = HdfUtils._parse_ras_datetime(split[1])
        return begin, end

    


                
                
                
                
                
                
                
                
                
                
                
                
## MOVED FROM HdfBase to HdfUtils:
# _parse_ras_datetime   
# _parse_ras_simulation_window_datetime
# _parse_duration
# _parse_ras_datetime_ms
# _convert_ras_hdf_string

# Which were renamed and made public as: 
# parse_ras_datetime
# parse_ras_window_datetime
# parse_ras_datetime_ms
# parse_ras_duration
# parse_ras_time_window


# Rename to parse_ras_datetime and make public

    @staticmethod
    def parse_ras_datetime(datetime_str: str) -> datetime:
        """
        Parse a RAS datetime string into a datetime object.

        Args:
            datetime_str (str): The datetime string in format "ddMMMYYYY HH:MM:SS"

        Returns:
            datetime: The parsed datetime object.
        """
        return datetime.strptime(datetime_str, "%d%b%Y %H:%M:%S")

# Rename to parse_ras_window_datetime and make public

    @staticmethod
    def parse_ras_window_datetime(datetime_str: str) -> datetime:
        """
        Parse a datetime string from a RAS simulation window into a datetime object.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        return datetime.strptime(datetime_str, "%d%b%Y %H%M")


# Rename to parse_duration and make public


    @staticmethod
    def parse_duration(duration_str: str) -> timedelta:
        """
        Parse a duration string into a timedelta object.

        Args:
            duration_str (str): The duration string to parse.

        Returns:
            timedelta: The parsed duration as a timedelta object.
        """
        hours, minutes, seconds = map(int, duration_str.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    
    
# Rename to parse_ras_datetime_ms and make public
    
    @staticmethod
    def parse_ras_datetime_ms(datetime_str: str) -> datetime:
        """
        Parse a datetime string with milliseconds from a RAS file.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        milliseconds = int(datetime_str[-3:])
        microseconds = milliseconds * 1000
        parsed_dt = HdfUtils.parse_ras_datetime(datetime_str[:-4]).replace(microsecond=microseconds)
        return parsed_dt
    
    