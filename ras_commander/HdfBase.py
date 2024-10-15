"""
Class: HdfBase

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""
import re
from datetime import datetime, timedelta
import h5py
import numpy as np
import pandas as pd
import xarray as xr  # Added import for xarray
from typing import List, Tuple, Union, Optional, Dict
from pathlib import Path
import logging
import dask.array as da

from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfBase:
    """
    Base class for HEC-RAS HDF file operations.

    This class provides fundamental methods for interacting with HEC-RAS HDF files,
    including time-related operations and mesh data retrieval. It serves as a foundation
    for more specialized HDF classes.

    The methods in this class are designed to work with both plan and geometry HDF files,
    providing low-level access to file structure and content.

    Note:
    - All methods in this class are static, allowing for use without instantiation.
    - This class is not meant to be used directly in most cases, but rather as a base
      for more specialized HDF classes.
    """

    @staticmethod
    def _get_simulation_start_time(hdf_file: h5py.File) -> datetime:
        """
        Get the simulation start time from the HDF file.

        Args:
            hdf_file (h5py.File): Open HDF file object.

        Returns:
            datetime: The simulation start time.

        Raises:
            ValueError: If Plan Information is not found in the HDF file.
        """
        plan_info = hdf_file.get("Plan Data/Plan Information")
        if plan_info is None:
            raise ValueError("Plan Information not found in HDF file")
        time_str = plan_info.attrs.get('Simulation Start Time')
        return datetime.strptime(time_str.decode('utf-8'), "%d%b%Y %H:%M:%S")

    @staticmethod
    def _get_unsteady_datetimes(hdf_file: h5py.File) -> List[datetime]:
        """
        Get the list of unsteady datetimes from the HDF file.

        Args:
            hdf_file (h5py.File): Open HDF file object.

        Returns:
            List[datetime]: A list of datetime objects representing the unsteady timestamps.
        """
        group_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp (ms)"
        raw_datetimes = hdf_file[group_path][:]
        return [HdfBase._parse_ras_datetime_ms(x.decode("utf-8")) for x in raw_datetimes]
    

    @staticmethod
    def _get_2d_flow_area_names_and_counts(hdf_file: h5py.File) -> List[Tuple[str, int]]:
        """
        Get the names and cell counts of 2D flow areas from the HDF file.

        Args:
            hdf_file (h5py.File): Open HDF file object.

        Returns:
            List[Tuple[str, int]]: A list of tuples containing the name and cell count of each 2D flow area.
        """
        d2_flow_areas = hdf_file.get("Geometry/2D Flow Areas/Attributes")
        if d2_flow_areas is None:
            return []
        return [(HdfBase._convert_ras_hdf_string(d2_flow_area[0]), d2_flow_area[-1]) for d2_flow_area in d2_flow_areas[:]]

    @staticmethod
    def _parse_ras_datetime(datetime_str: str) -> datetime:
        """
        Parse a datetime string from a RAS file into a datetime object.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        return datetime.strptime(datetime_str, "%d%b%Y %H:%M:%S")

    @staticmethod
    def _parse_ras_simulation_window_datetime(datetime_str: str) -> datetime:
        """
        Parse a datetime string from a RAS simulation window into a datetime object.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        return datetime.strptime(datetime_str, "%d%b%Y %H%M")

    @staticmethod
    def _parse_duration(duration_str: str) -> timedelta:
        """
        Parse a duration string into a timedelta object.

        Args:
            duration_str (str): The duration string to parse.

        Returns:
            timedelta: The parsed duration as a timedelta object.
        """
        hours, minutes, seconds = map(int, duration_str.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)

    @staticmethod
    def _parse_ras_datetime_ms(datetime_str: str) -> datetime:
        """
        Parse a datetime string with milliseconds from a RAS file.

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
    def _convert_ras_hdf_string(value: Union[str, bytes]) -> Union[bool, datetime, List[datetime], timedelta, str]:
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



