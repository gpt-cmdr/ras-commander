"""
Class: HdfPlan

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.


- get_plan_start_time()
- get_plan_end_time()
- get_plan_timestamps_list()     
- get_plan_information()
- get_plan_parameters()
- get_plan_met_precip()
- get_geometry_information()






"""

import h5py
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re
import numpy as np

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)


class HdfPlan:
    """
    A class for handling HEC-RAS plan HDF files.

    Provides static methods for extracting data from HEC-RAS plan HDF files including 
    simulation times, plan information, and geometry attributes. All methods use 
    @standardize_input for handling different input types and @log_call for logging.

    Note: This code is partially derived from the rashdf library (https://github.com/fema-ffrd/rashdf)
    under MIT license.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_start_time(hdf_path: Path) -> datetime:
        """
        Get the plan start time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The plan start time in UTC format.

        Raises:
            ValueError: If there's an error reading the plan start time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase.get_simulation_start_time(hdf_file)
        except Exception as e:
            raise ValueError(f"Failed to get plan start time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_end_time(hdf_path: Path) -> datetime:
        """
        Get the plan end time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The plan end time.

        Raises:
            ValueError: If there's an error reading the plan end time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_info = hdf_file.get('Plan Data/Plan Information')
                if plan_info is None:
                    raise ValueError("Plan Information not found in HDF file")
                time_str = plan_info.attrs.get('Simulation End Time')
                return HdfUtils.parse_ras_datetime(time_str.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Failed to get plan end time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_timestamps_list(hdf_path: Path) -> List[datetime]:
        """
        Get the list of output timestamps from the plan simulation.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            List[datetime]: Chronological list of simulation output timestamps in UTC.

        Raises:
            ValueError: If there's an error retrieving the plan timestamps.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase.get_unsteady_timestamps(hdf_file)
        except Exception as e:
            raise ValueError(f"Failed to get plan timestamps: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_information(hdf_path: Path) -> Dict:
        """
        Get plan information from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: Plan information including simulation times, flow regime, 
                computation settings, etc.

        Raises:
            ValueError: If there's an error retrieving the plan information.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_info_path = "Plan Data/Plan Information"
                if plan_info_path not in hdf_file:
                    raise ValueError(f"Plan Information not found in {hdf_path}")
                
                attrs = {}
                for key in hdf_file[plan_info_path].attrs.keys():
                    value = hdf_file[plan_info_path].attrs[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
            raise ValueError(f"Failed to get plan information attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_parameters(hdf_path: Path) -> pd.DataFrame:
        """
        Get plan parameter attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: A DataFrame containing the plan parameters with columns:
                - Parameter: Name of the parameter
                - Value: Value of the parameter (decoded if byte string)
                - Plan: Plan number (01-99) extracted from the filename (ProjectName.pXX.hdf)

        Raises:
            ValueError: If there's an error retrieving the plan parameter attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_params_path = "Plan Data/Plan Parameters"
                if plan_params_path not in hdf_file:
                    raise ValueError(f"Plan Parameters not found in {hdf_path}")
                
                # Extract parameters
                params_dict = {}
                for key in hdf_file[plan_params_path].attrs.keys():
                    value = hdf_file[plan_params_path].attrs[key]
                    
                    # Handle different types of values
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    elif isinstance(value, np.ndarray):
                        # Handle array values
                        if value.dtype.kind in {'S', 'a'}:  # Array of byte strings
                            value = [v.decode('utf-8') if isinstance(v, bytes) else v for v in value]
                        else:
                            value = value.tolist()  # Convert numpy array to list
                        
                        # If it's a single-item list, extract the value
                        if len(value) == 1:
                            value = value[0]
                    
                    params_dict[key] = value
                
                # Create DataFrame from parameters
                df = pd.DataFrame.from_dict(params_dict, orient='index', columns=['Value'])
                df.index.name = 'Parameter'
                df = df.reset_index()
                
                # Extract plan number from filename
                filename = Path(hdf_path).name
                plan_match = re.search(r'\.p(\d{2})\.', filename)
                if plan_match:
                    plan_num = plan_match.group(1)
                else:
                    plan_num = "00"  # Default if no match found
                    logger.warning(f"Could not extract plan number from filename: {filename}")
                
                df['Plan'] = plan_num
                
                # Reorder columns to put Plan first
                df = df[['Plan', 'Parameter', 'Value']]
                
                return df

        except Exception as e:
            raise ValueError(f"Failed to get plan parameter attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_met_precip(hdf_path: Path) -> Dict:
        """
        Get precipitation attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: Precipitation attributes including method, time series data,
                and spatial distribution if available. Returns empty dict if
                no precipitation data exists.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                precip_path = "Event Conditions/Meteorology/Precipitation"
                if precip_path not in hdf_file:
                    logger.error(f"Precipitation data not found in {hdf_path}")
                    return {}
                
                attrs = {}
                for key in hdf_file[precip_path].attrs.keys():
                    value = hdf_file[precip_path].attrs[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
            logger.error(f"Failed to get precipitation attributes: {str(e)}")
            return {}
        
    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_geometry_information(hdf_path: Path) -> pd.DataFrame:
        """
        Get root level geometry attributes from the HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: DataFrame with geometry attributes including Creation Date/Time,
                        Version, Units, and Projection information.

        Raises:
            ValueError: If Geometry group is missing or there's an error reading attributes.
        """
        logger.info(f"Getting geometry attributes from {hdf_path}")
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                geom_attrs_path = "Geometry"
                logger.info(f"Checking for Geometry group in {hdf_path}")
                if geom_attrs_path not in hdf_file:
                    logger.error(f"Geometry group not found in {hdf_path}")
                    raise ValueError(f"Geometry group not found in {hdf_path}")

                attrs = {}
                geom_group = hdf_file[geom_attrs_path]
                logger.info("Getting root level geometry attributes")
                # Get root level geometry attributes only
                for key, value in geom_group.attrs.items():
                    if isinstance(value, bytes):
                        try:
                            value = HdfUtils.convert_ras_string(value)
                        except UnicodeDecodeError:
                            logger.warning(f"Failed to decode byte string for root attribute {key}")
                            continue
                    attrs[key] = value
                    logger.debug(f"Geometry attribute: {key} = {value}")

                logger.info(f"Successfully extracted {len(attrs)} root level geometry attributes")
                return pd.DataFrame.from_dict(attrs, orient='index', columns=['Value'])

        except (OSError, RuntimeError) as e:
            logger.error(f"Failed to read HDF file {hdf_path}: {str(e)}")
            raise ValueError(f"Failed to read HDF file {hdf_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to get geometry attributes: {str(e)}")
            raise ValueError(f"Failed to get geometry attributes: {str(e)}")


