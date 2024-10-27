"""
Class: HdfPlan

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

import h5py
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)


class HdfPlan:
    """
    A class for handling operations on HEC-RAS plan HDF files.

    This class provides methods for extracting and analyzing data from HEC-RAS plan HDF files,
    including simulation times, plan information, and geometry attributes.

    Methods in this class use the @standardize_input decorator to handle different input types
    (e.g., plan number, file path) and the @log_call decorator for logging method calls.

    Attributes:
        None

    Methods:
        get_simulation_start_time: Get the simulation start time.
        get_simulation_end_time: Get the simulation end time.
        get_unsteady_datetimes: Get a list of unsteady datetimes.
        get_plan_info_attrs: Get plan information attributes.
        get_plan_param_attrs: Get plan parameter attributes.
        get_meteorology_precip_attrs: Get precipitation attributes.
        get_geom_attrs: Get geometry attributes.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_simulation_start_time(hdf_path: Path) -> datetime:
        """
        Get the simulation start time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The simulation start time.

        Raises:
            ValueError: If there's an error reading the simulation start time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase._get_simulation_start_time(hdf_file)
        except Exception as e:
            raise ValueError(f"Failed to get simulation start time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_simulation_end_time(hdf_path: Path) -> datetime:
        """
        Get the simulation end time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The simulation end time.

        Raises:
            ValueError: If there's an error reading the simulation end time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_info = hdf_file.get('Plan Data/Plan Information')
                if plan_info is None:
                    raise ValueError("Plan Information not found in HDF file")
                time_str = plan_info.attrs.get('Simulation End Time')
                return datetime.strptime(time_str.decode('utf-8'), "%d%b%Y %H:%M:%S")
        except Exception as e:
            raise ValueError(f"Failed to get simulation end time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_unsteady_datetimes(hdf_path: Path) -> List[datetime]:
        """
        Get the list of unsteady datetimes from the HDF file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            List[datetime]: A list of datetime objects representing the unsteady timestamps.

        Raises:
            ValueError: If there's an error retrieving the unsteady datetimes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase._get_unsteady_datetimes(hdf_file)
        except Exception as e:
            raise ValueError(f"Failed to get unsteady datetimes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_info_attrs(hdf_path: Path) -> Dict:
        """
        Get plan information attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the plan information attributes.

        Raises:
            ValueError: If there's an error retrieving the plan information attributes.
        """
        try:
            return HdfUtils.get_attrs(hdf_path, "Plan Data/Plan Information")
        except Exception as e:
            raise ValueError(f"Failed to get plan information attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_param_attrs(hdf_path: Path) -> Dict:
        """
        Get plan parameter attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the plan parameter attributes.

        Raises:
            ValueError: If there's an error retrieving the plan parameter attributes.
        """
        try:
            return HdfUtils.get_attrs(hdf_path, "Plan Data/Plan Parameters")
        except Exception as e:
            raise ValueError(f"Failed to get plan parameter attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_meteorology_precip_attrs(hdf_path: Path) -> Dict:
        """
        Get precipitation attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the precipitation attributes.

        Raises:
            ValueError: If there's an error retrieving the precipitation attributes.
        """
        try:
            return HdfUtils.get_attrs(hdf_path, "Event Conditions/Meteorology/Precipitation")
        except Exception as e:
            raise ValueError(f"Failed to get precipitation attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_geom_attrs(hdf_path: Path) -> Dict:
        """
        Get geometry attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the geometry attributes.

        Raises:
            ValueError: If there's an error retrieving the geometry attributes.
        """
        try:
            return HdfUtils.get_attrs(hdf_path, "Geometry")
        except Exception as e:
            raise ValueError(f"Failed to get geometry attributes: {str(e)}")





