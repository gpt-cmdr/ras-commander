"""
HdfResultsPlan: A module for extracting and analyzing HEC-RAS plan HDF file results.

Attribution:
    Substantial code sourced/derived from https://github.com/fema-ffrd/rashdf
    Copyright (c) 2024 fema-ffrd, MIT license

Description:
    Provides static methods for extracting unsteady flow results, volume accounting,
    and reference data from HEC-RAS plan HDF files.

Available Functions:
    - get_unsteady_info: Extract unsteady attributes
    - get_unsteady_summary: Extract unsteady summary data
    - get_volume_accounting: Extract volume accounting data
    - get_runtime_data: Extract runtime and compute time data

Note:
    All methods are static and designed to be used without class instantiation.
"""

from typing import Dict, List, Union, Optional
from pathlib import Path
import h5py
import pandas as pd
import xarray as xr
from .Decorators import standardize_input, log_call
from .HdfUtils import HdfUtils
from .HdfResultsXsec import HdfResultsXsec
from .LoggingConfig import get_logger
import numpy as np
from datetime import datetime

logger = get_logger(__name__)


class HdfResultsPlan:
    """
    Handles extraction of results data from HEC-RAS plan HDF files.

    This class provides static methods for accessing and analyzing:
        - Unsteady flow results
        - Volume accounting data
        - Runtime statistics
        - Reference line/point time series outputs

    All methods use:
        - @standardize_input decorator for consistent file path handling
        - @log_call decorator for operation logging
        - HdfUtils class for common HDF operations

    Note:
        No instantiation required - all methods are static.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_unsteady_info(hdf_path: Path) -> pd.DataFrame:
        """
        Get unsteady attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: A DataFrame containing the unsteady attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady" not in hdf_file:
                    raise KeyError("Results/Unsteady group not found in the HDF file.")
                
                # Create dictionary from attributes
                attrs_dict = dict(hdf_file["Results/Unsteady"].attrs)
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])
                
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading unsteady attributes: {str(e)}")
        
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_unsteady_summary(hdf_path: Path) -> pd.DataFrame:
        """
        Get results unsteady summary attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: A DataFrame containing the results unsteady summary attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady/Summary" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary" not in hdf_file:
                    raise KeyError("Results/Unsteady/Summary group not found in the HDF file.")
                
                # Create dictionary from attributes
                attrs_dict = dict(hdf_file["Results/Unsteady/Summary"].attrs)
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])
                
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading unsteady summary attributes: {str(e)}")
        
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_volume_accounting(hdf_path: Path) -> pd.DataFrame:
        """
        Get volume accounting attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: A DataFrame containing the volume accounting attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady/Summary/Volume Accounting" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary/Volume Accounting" not in hdf_file:
                    raise KeyError("Results/Unsteady/Summary/Volume Accounting group not found in the HDF file.")
                
                # Get attributes and create dictionary
                attrs_dict = dict(hdf_file["Results/Unsteady/Summary/Volume Accounting"].attrs)
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])
                
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading volume accounting attributes: {str(e)}")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_runtime_data(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Extract detailed runtime and computational performance metrics from HDF file.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file

        Returns:
            Optional[pd.DataFrame]: DataFrame containing:
                - Plan identification (name, file)
                - Simulation timing (start, end, duration)
                - Process-specific compute times
                - Performance metrics (simulation speeds)
                Returns None if required data cannot be extracted

        Notes:
            - Times are reported in multiple units (ms, s, hours)
            - Compute speeds are calculated as simulation-time/compute-time ratios
            - Process times include: geometry, preprocessing, event conditions, 
            and unsteady flow computations

        Example:
            >>> runtime_stats = HdfResultsPlan.get_runtime_data('path/to/plan.hdf')
            >>> if runtime_stats is not None:
            >>>     print(f"Total compute time: {runtime_stats['Complete Process (hr)'][0]:.2f} hours")
        """
        if hdf_path is None:
            logger.error(f"Could not find HDF file for input")
            return None

        with h5py.File(hdf_path, 'r') as hdf_file:
            logger.info(f"Extracting Plan Information from: {Path(hdf_file.filename).name}")
            plan_info = hdf_file.get('/Plan Data/Plan Information')
            if plan_info is None:
                logger.warning("Group '/Plan Data/Plan Information' not found.")
                return None

            plan_name = plan_info.attrs.get('Plan Name', 'Unknown')
            plan_name = plan_name.decode('utf-8') if isinstance(plan_name, bytes) else plan_name
            logger.info(f"Plan Name: {plan_name}")

            start_time_str = plan_info.attrs.get('Simulation Start Time', 'Unknown')
            end_time_str = plan_info.attrs.get('Simulation End Time', 'Unknown')
            start_time_str = start_time_str.decode('utf-8') if isinstance(start_time_str, bytes) else start_time_str
            end_time_str = end_time_str.decode('utf-8') if isinstance(end_time_str, bytes) else end_time_str

            start_time = datetime.strptime(start_time_str, "%d%b%Y %H:%M:%S")
            end_time = datetime.strptime(end_time_str, "%d%b%Y %H:%M:%S")
            simulation_duration = end_time - start_time
            simulation_hours = simulation_duration.total_seconds() / 3600

            logger.info(f"Simulation Start Time: {start_time_str}")
            logger.info(f"Simulation End Time: {end_time_str}")
            logger.info(f"Simulation Duration (hours): {simulation_hours}")

            compute_processes = hdf_file.get('/Results/Summary/Compute Processes')
            if compute_processes is None:
                logger.warning("Dataset '/Results/Summary/Compute Processes' not found.")
                return None

            process_names = [name.decode('utf-8') for name in compute_processes['Process'][:]]
            filenames = [filename.decode('utf-8') for filename in compute_processes['Filename'][:]]
            completion_times = compute_processes['Compute Time (ms)'][:]

            compute_processes_df = pd.DataFrame({
                'Process': process_names,
                'Filename': filenames,
                'Compute Time (ms)': completion_times,
                'Compute Time (s)': completion_times / 1000,
                'Compute Time (hours)': completion_times / (1000 * 3600)
            })

            logger.debug("Compute processes DataFrame:")
            logger.debug(compute_processes_df)

            compute_processes_summary = {
                'Plan Name': [plan_name],
                'File Name': [Path(hdf_file.filename).name],
                'Simulation Start Time': [start_time_str],
                'Simulation End Time': [end_time_str],
                'Simulation Duration (s)': [simulation_duration.total_seconds()],
                'Simulation Time (hr)': [simulation_hours],
                'Completing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Geometry']['Compute Time (hours)'].values[0] if 'Completing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Preprocessing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Preprocessing Geometry']['Compute Time (hours)'].values[0] if 'Preprocessing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Completing Event Conditions (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Event Conditions']['Compute Time (hours)'].values[0] if 'Completing Event Conditions' in compute_processes_df['Process'].values else 'N/A'],
                'Unsteady Flow Computations (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Unsteady Flow Computations']['Compute Time (hours)'].values[0] if 'Unsteady Flow Computations' in compute_processes_df['Process'].values else 'N/A'],
                'Complete Process (hr)': [compute_processes_df['Compute Time (hours)'].sum()]
            }

            compute_processes_summary['Unsteady Flow Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Unsteady Flow Computations (hr)'][0] if compute_processes_summary['Unsteady Flow Computations (hr)'][0] != 'N/A' else 'N/A']
            compute_processes_summary['Complete Process Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Complete Process (hr)'][0] if compute_processes_summary['Complete Process (hr)'][0] != 'N/A' else 'N/A']

            compute_summary_df = pd.DataFrame(compute_processes_summary)
            logger.debug("Compute summary DataFrame:")
            logger.debug(compute_summary_df)

            return compute_summary_df

        


