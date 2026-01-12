"""
HdfResultsPlan: A module for extracting and analyzing HEC-RAS plan HDF file results.

Attribution:
    Substantial code sourced/derived from https://github.com/fema-ffrd/rashdf
    Copyright (c) 2024 fema-ffrd, MIT license

Description:
    Provides static methods for extracting both unsteady and steady flow results,
    volume accounting, and reference data from HEC-RAS plan HDF files.

Available Functions:
    Unsteady Flow:
        - get_unsteady_info: Extract unsteady attributes
        - get_unsteady_summary: Extract unsteady summary data
        - get_volume_accounting: Extract volume accounting data
        - get_runtime_data: Extract runtime and compute time data
        - get_reference_timeseries: Extract reference line/point timeseries
        - get_reference_summary: Extract reference line/point summary

    Steady Flow:
        - is_steady_plan: Check if HDF contains steady state results
        - get_steady_profile_names: Extract steady state profile names
        - get_steady_wse: Extract WSE data for steady state profiles
        - get_steady_info: Extract steady flow attributes and metadata

    Computation Messages:
        - get_compute_messages: Extract computation messages from HDF (with .txt fallback)

Note:
    All methods are static and designed to be used without class instantiation.
"""

from typing import Dict, List, Union, Optional
from pathlib import Path
import h5py
import pandas as pd
import xarray as xr
from ..Decorators import standardize_input, log_call
from .HdfUtils import HdfUtils
from .HdfResultsXsec import HdfResultsXsec
from ..LoggingConfig import get_logger
import numpy as np
from datetime import datetime
from ..RasPrj import ras

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
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: A DataFrame containing the decoded unsteady attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady" not in hdf_file:
                    raise KeyError("Results/Unsteady group not found in the HDF file.")
                
                # Create dictionary from attributes and decode byte strings
                attrs_dict = {}
                for key, value in dict(hdf_file["Results/Unsteady"].attrs).items():
                    if isinstance(value, bytes):
                        attrs_dict[key] = value.decode('utf-8')
                    else:
                        attrs_dict[key] = value
                
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
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: A DataFrame containing the decoded results unsteady summary attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady/Summary" group is not found in the HDF file.
        """
        try:           
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary" not in hdf_file:
                    raise KeyError("Results/Unsteady/Summary group not found in the HDF file.")
                
                # Create dictionary from attributes and decode byte strings
                attrs_dict = {}
                for key, value in dict(hdf_file["Results/Unsteady/Summary"].attrs).items():
                    if isinstance(value, bytes):
                        attrs_dict[key] = value.decode('utf-8')
                    else:
                        attrs_dict[key] = value
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])
                
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading unsteady summary attributes: {str(e)}")
        
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_volume_accounting(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Get volume accounting attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing the decoded volume accounting attributes,
                                  or None if the group is not found.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary/Volume Accounting" not in hdf_file:
                    return None
                
                # Get attributes and decode byte strings
                attrs_dict = {}
                for key, value in dict(hdf_file["Results/Unsteady/Summary/Volume Accounting"].attrs).items():
                    if isinstance(value, bytes):
                        attrs_dict[key] = value.decode('utf-8')
                    else:
                        attrs_dict[key] = value
                
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
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing runtime statistics or None if data cannot be extracted

        Notes:
            - Times are reported in multiple units (ms, s, hours)
            - Compute speeds are calculated as simulation-time/compute-time ratios
            - Process times include: geometry, preprocessing, event conditions, 
              and unsteady flow computations
        """
        try:
            if hdf_path is None:
                logger.error(f"Could not find HDF file for input")
                return None

            with h5py.File(hdf_path, 'r') as hdf_file:
                logger.info(f"Extracting Plan Information from: {Path(hdf_file.filename).name}")
                plan_info = hdf_file.get('/Plan Data/Plan Information')
                if plan_info is None:
                    logger.warning("Group '/Plan Data/Plan Information' not found.")
                    return None

                # Extract plan information
                plan_name = HdfUtils.convert_ras_string(plan_info.attrs.get('Plan Name', 'Unknown'))
                start_time_str = HdfUtils.convert_ras_string(plan_info.attrs.get('Simulation Start Time', 'Unknown'))
                end_time_str = HdfUtils.convert_ras_string(plan_info.attrs.get('Simulation End Time', 'Unknown'))

                try:
                    # Check if times are already datetime objects
                    if isinstance(start_time_str, datetime):
                        start_time = start_time_str
                    else:
                        start_time = datetime.strptime(start_time_str, "%d%b%Y %H:%M:%S")
                        
                    if isinstance(end_time_str, datetime):
                        end_time = end_time_str
                    else:
                        end_time = datetime.strptime(end_time_str, "%d%b%Y %H:%M:%S")
                        
                    simulation_duration = end_time - start_time
                    simulation_hours = simulation_duration.total_seconds() / 3600
                except ValueError as e:
                    logger.error(f"Error parsing simulation times: {e}")
                    return None

                logger.info(f"Plan Name: {plan_name}")
                logger.info(f"Simulation Duration (hours): {simulation_hours}")

                # Extract compute processes data
                compute_processes = hdf_file.get('/Results/Summary/Compute Processes')
                if compute_processes is None:
                    logger.warning("Dataset '/Results/Summary/Compute Processes' not found.")
                    return None

                # Process compute times
                process_names = [HdfUtils.convert_ras_string(name) for name in compute_processes['Process'][:]]
                filenames = [HdfUtils.convert_ras_string(filename) for filename in compute_processes['Filename'][:]]
                completion_times = compute_processes['Compute Time (ms)'][:]

                compute_processes_df = pd.DataFrame({
                    'Process': process_names,
                    'Filename': filenames,
                    'Compute Time (ms)': completion_times,
                    'Compute Time (s)': completion_times / 1000,
                    'Compute Time (hours)': completion_times / (1000 * 3600)
                })

                # Create summary DataFrame
                compute_processes_summary = {
                    'Plan Name': [plan_name],
                    'File Name': [Path(hdf_file.filename).name],
                    'Simulation Start Time': [start_time_str],
                    'Simulation End Time': [end_time_str],
                    'Simulation Duration (s)': [simulation_duration.total_seconds()],
                    'Simulation Time (hr)': [simulation_hours]
                }

                # Add process-specific times
                process_types = {
                    'Completing Geometry': 'Completing Geometry (hr)',
                    'Preprocessing Geometry': 'Preprocessing Geometry (hr)',
                    'Completing Event Conditions': 'Completing Event Conditions (hr)',
                    'Unsteady Flow Computations': 'Unsteady Flow Computations (hr)'
                }

                for process, column in process_types.items():
                    time_value = compute_processes_df[
                        compute_processes_df['Process'] == process
                    ]['Compute Time (hours)'].values[0] if process in process_names else 'N/A'
                    compute_processes_summary[column] = [time_value]

                # Add total process time
                total_time = compute_processes_df['Compute Time (hours)'].sum()
                compute_processes_summary['Complete Process (hr)'] = [total_time]

                # Calculate speeds
                if compute_processes_summary['Unsteady Flow Computations (hr)'][0] != 'N/A':
                    compute_processes_summary['Unsteady Flow Speed (hr/hr)'] = [
                        simulation_hours / compute_processes_summary['Unsteady Flow Computations (hr)'][0]
                    ]
                else:
                    compute_processes_summary['Unsteady Flow Speed (hr/hr)'] = ['N/A']

                compute_processes_summary['Complete Process Speed (hr/hr)'] = [
                    simulation_hours / total_time
                ]

                return pd.DataFrame(compute_processes_summary)

        except Exception as e:
            logger.error(f"Error in get_runtime_data: {str(e)}")
            return None

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_reference_timeseries(hdf_path: Path, reftype: str) -> pd.DataFrame:
        """
        Get reference line or point timeseries output from HDF file.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            reftype (str): Type of reference data ('lines' or 'points')
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame containing reference timeseries data
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                ref_path = f"{base_path}/Reference {reftype.capitalize()}"
                
                if ref_path not in hdf_file:
                    logger.warning(f"Reference {reftype} data not found in HDF file")
                    return pd.DataFrame()

                ref_group = hdf_file[ref_path]
                time_data = hdf_file[f"{base_path}/Time"][:]
                
                dfs = []
                for ref_name in ref_group.keys():
                    ref_data = ref_group[ref_name][:]
                    df = pd.DataFrame(ref_data, columns=[ref_name])
                    df['Time'] = time_data
                    dfs.append(df)

                if not dfs:
                    return pd.DataFrame()

                return pd.concat(dfs, axis=1)

        except Exception as e:
            logger.error(f"Error reading reference {reftype} timeseries: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_reference_summary(hdf_path: Path, reftype: str) -> pd.DataFrame:
        """
        Get reference line or point summary output from HDF file.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            reftype (str): Type of reference data ('lines' or 'points')
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame containing reference summary data
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output"
                ref_path = f"{base_path}/Reference {reftype.capitalize()}"
                
                if ref_path not in hdf_file:
                    logger.warning(f"Reference {reftype} summary data not found in HDF file")
                    return pd.DataFrame()

                ref_group = hdf_file[ref_path]
                dfs = []
                
                for ref_name in ref_group.keys():
                    ref_data = ref_group[ref_name][:]
                    if ref_data.ndim == 2:
                        df = pd.DataFrame(ref_data.T, columns=['Value', 'Time'])
                    else:
                        df = pd.DataFrame({'Value': ref_data})
                    df['Reference'] = ref_name
                    dfs.append(df)

                if not dfs:
                    return pd.DataFrame()

                return pd.concat(dfs, ignore_index=True)

        except Exception as e:
            logger.error(f"Error reading reference {reftype} summary: {str(e)}")
            return pd.DataFrame()

    # ==================== STEADY STATE METHODS ====================

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def is_steady_plan(hdf_path: Path) -> bool:
        """
        Check if HDF file contains steady state results.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            bool: True if the HDF contains steady state results, False otherwise

        Notes:
            - Checks for existence of Results/Steady group
            - Does not guarantee results are complete or valid
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return "Results/Steady" in hdf_file
        except Exception as e:
            logger.error(f"Error checking if plan is steady: {str(e)}")
            return False

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_steady_profile_names(hdf_path: Path) -> List[str]:
        """
        Extract profile names from steady state results.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            List[str]: List of profile names (e.g., ['50Pct', '10Pct', '1Pct'])

        Raises:
            FileNotFoundError: If the specified HDF file is not found
            KeyError: If steady state results or profile names are not found
            ValueError: If the plan is not a steady state plan

        Example:
            >>> from ras_commander import HdfResultsPlan, init_ras_project
            >>> init_ras_project(Path('/path/to/project'), '6.6')
            >>> profiles = HdfResultsPlan.get_steady_profile_names('01')
            >>> print(profiles)
            ['50Pct', '20Pct', '10Pct', '4Pct', '2Pct', '1Pct', '0.2Pct']
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check if this is a steady state plan
                if "Results/Steady" not in hdf_file:
                    raise ValueError(f"HDF file does not contain steady state results: {hdf_path.name}")

                # Path to profile names
                profile_names_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names"

                if profile_names_path not in hdf_file:
                    raise KeyError(f"Profile names not found at: {profile_names_path}")

                # Read profile names dataset
                profile_names_ds = hdf_file[profile_names_path]
                profile_names_raw = profile_names_ds[()]

                # Decode byte strings to regular strings
                profile_names = []
                for name in profile_names_raw:
                    if isinstance(name, bytes):
                        profile_names.append(name.decode('utf-8').strip())
                    else:
                        profile_names.append(str(name).strip())

                logger.info(f"Found {len(profile_names)} steady state profiles: {profile_names}")
                return profile_names

        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except KeyError as e:
            raise KeyError(f"Error accessing steady state profile names: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Error reading steady state profile names: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_steady_wse(
        hdf_path: Path,
        profile_index: Optional[int] = None,
        profile_name: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Extract water surface elevation (WSE) data for steady state profiles.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            profile_index (int, optional): Index of profile to extract (0-based). If None, extracts all profiles.
            profile_name (str, optional): Name of profile to extract (e.g., '1Pct'). If specified, overrides profile_index.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame containing WSE data with columns:
                - River: River name
                - Reach: Reach name
                - Station: Cross section river station
                - Profile: Profile name (if multiple profiles)
                - WSE: Water surface elevation (ft)

        Raises:
            FileNotFoundError: If the specified HDF file is not found
            KeyError: If steady state results or WSE data are not found
            ValueError: If profile_index or profile_name is invalid

        Example:
            >>> # Extract single profile by index
            >>> wse_df = HdfResultsPlan.get_steady_wse('01', profile_index=5)  # 100-year profile

            >>> # Extract single profile by name
            >>> wse_df = HdfResultsPlan.get_steady_wse('01', profile_name='1Pct')

            >>> # Extract all profiles
            >>> wse_df = HdfResultsPlan.get_steady_wse('01')
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check if this is a steady state plan
                if "Results/Steady" not in hdf_file:
                    raise ValueError(f"HDF file does not contain steady state results: {hdf_path.name}")

                # Paths to data
                wse_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Water Surface"
                xs_attrs_path = "Results/Steady/Output/Geometry Info/Cross Section Attributes"
                profile_names_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names"

                # Check required paths exist
                if wse_path not in hdf_file:
                    raise KeyError(f"WSE data not found at: {wse_path}")
                if xs_attrs_path not in hdf_file:
                    raise KeyError(f"Cross section attributes not found at: {xs_attrs_path}")

                # Get WSE dataset (shape: num_profiles × num_cross_sections)
                wse_ds = hdf_file[wse_path]
                wse_data = wse_ds[()]
                num_profiles, num_xs = wse_data.shape

                # Get profile names
                if profile_names_path in hdf_file:
                    profile_names_raw = hdf_file[profile_names_path][()]
                    profile_names = [
                        name.decode('utf-8').strip() if isinstance(name, bytes) else str(name).strip()
                        for name in profile_names_raw
                    ]
                else:
                    # Fallback to numbered profiles
                    profile_names = [f"Profile_{i+1}" for i in range(num_profiles)]

                # Get cross section attributes
                xs_attrs = hdf_file[xs_attrs_path][()]

                # Determine which profiles to extract
                if profile_name is not None:
                    # Find profile by name
                    try:
                        profile_idx = profile_names.index(profile_name)
                    except ValueError:
                        raise ValueError(
                            f"Profile name '{profile_name}' not found. "
                            f"Available profiles: {profile_names}"
                        )
                    profiles_to_extract = [(profile_idx, profile_name)]

                elif profile_index is not None:
                    # Validate profile index
                    if profile_index < 0 or profile_index >= num_profiles:
                        raise ValueError(
                            f"Profile index {profile_index} out of range. "
                            f"Valid range: 0 to {num_profiles-1}"
                        )
                    profiles_to_extract = [(profile_index, profile_names[profile_index])]

                else:
                    # Extract all profiles
                    profiles_to_extract = list(enumerate(profile_names))

                # Build DataFrame
                rows = []
                for prof_idx, prof_name in profiles_to_extract:
                    wse_values = wse_data[prof_idx, :]

                    for xs_idx in range(num_xs):
                        river = xs_attrs[xs_idx]['River']
                        reach = xs_attrs[xs_idx]['Reach']
                        station = xs_attrs[xs_idx]['Station']

                        # Decode byte strings
                        river = river.decode('utf-8') if isinstance(river, bytes) else str(river)
                        reach = reach.decode('utf-8') if isinstance(reach, bytes) else str(reach)
                        station = station.decode('utf-8') if isinstance(station, bytes) else str(station)

                        row = {
                            'River': river.strip(),
                            'Reach': reach.strip(),
                            'Station': station.strip(),
                            'WSE': float(wse_values[xs_idx])
                        }

                        # Only add Profile column if extracting multiple profiles
                        if len(profiles_to_extract) > 1:
                            row['Profile'] = prof_name

                        rows.append(row)

                df = pd.DataFrame(rows)

                # Reorder columns
                if 'Profile' in df.columns:
                    df = df[['River', 'Reach', 'Station', 'Profile', 'WSE']]
                else:
                    df = df[['River', 'Reach', 'Station', 'WSE']]

                logger.info(
                    f"Extracted WSE data for {len(profiles_to_extract)} profile(s), "
                    f"{num_xs} cross sections"
                )

                return df

        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except KeyError as e:
            raise KeyError(f"Error accessing steady state WSE data: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Error reading steady state WSE data: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_steady_info(hdf_path: Path) -> pd.DataFrame:
        """
        Get steady flow attributes and metadata from HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to HEC-RAS plan HDF file
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame containing steady flow attributes including:
                - Program Name
                - Program Version
                - Type of Run
                - Run Time Window
                - Solution status
                - And other metadata attributes

        Raises:
            FileNotFoundError: If the specified HDF file is not found
            KeyError: If steady state results are not found
            ValueError: If the plan is not a steady state plan

        Example:
            >>> info_df = HdfResultsPlan.get_steady_info('01')
            >>> print(info_df['Solution'].values[0])
            'Steady Finished Successfully'
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check if this is a steady state plan
                if "Results/Steady" not in hdf_file:
                    raise ValueError(f"HDF file does not contain steady state results: {hdf_path.name}")

                attrs_dict = {}

                # Get attributes from Results/Steady/Output
                output_path = "Results/Steady/Output"
                if output_path in hdf_file:
                    output_group = hdf_file[output_path]
                    for key, value in output_group.attrs.items():
                        if isinstance(value, bytes):
                            attrs_dict[key] = value.decode('utf-8')
                        else:
                            attrs_dict[key] = value

                # Get attributes from Results/Steady/Summary
                summary_path = "Results/Steady/Summary"
                if summary_path in hdf_file:
                    summary_group = hdf_file[summary_path]
                    for key, value in summary_group.attrs.items():
                        if isinstance(value, bytes):
                            attrs_dict[key] = value.decode('utf-8')
                        else:
                            attrs_dict[key] = value

                # Add flow file information from Plan Data
                plan_info_path = "Plan Data/Plan Information"
                if plan_info_path in hdf_file:
                    plan_info = hdf_file[plan_info_path]
                    for key in ['Flow Filename', 'Flow Title']:
                        if key in plan_info.attrs:
                            value = plan_info.attrs[key]
                            if isinstance(value, bytes):
                                attrs_dict[key] = value.decode('utf-8')
                            else:
                                attrs_dict[key] = value

                if not attrs_dict:
                    logger.warning("No steady state attributes found in HDF file")
                    return pd.DataFrame()

                logger.info(f"Extracted {len(attrs_dict)} steady state attributes")
                return pd.DataFrame(attrs_dict, index=[0])

        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except KeyError as e:
            raise KeyError(f"Error accessing steady state info: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Error reading steady state info: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_compute_messages(hdf_path: Path) -> str:
        """
        Read computation messages from HDF file with fallback to .txt file.

        Extracts computation messages from the HDF Results/Summary structure.
        This includes detailed information about the computation process,
        warnings, errors, convergence information, and performance metrics.

        If HDF path not found, falls back to .txt file extraction using RasControl.

        Args:
            hdf_path: Path to plan HDF file (or plan number string if using
                     standardize_input decorator, which resolves to HDF path)

        Returns:
            String containing computation messages, or empty string if unavailable

        Example:
            >>> from ras_commander import init_ras_project, HdfResultsPlan
            >>> init_ras_project(r"/path/to/project", "6.5")
            >>> msgs = HdfResultsPlan.get_compute_messages("01")
            >>> print(msgs)

        Note:
            Modern HEC-RAS versions (6.x+) store computation messages in HDF:
            /Results/Summary/Compute Messages (text)

            Older versions (pre-6.x) use .txt files which are accessed via
            fallback to RasControl.get_comp_msgs()

            Function naming follows HDF structure conventions (get_compute_messages)
            vs RasControl legacy naming (get_comp_msgs) to reflect technological lineage.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Define HDF path for compute messages
                compute_msgs_path = "Results/Summary/Compute Messages (text)"

                # Check if path exists in HDF
                if compute_msgs_path not in hdf_file:
                    logger.warning(
                        f"Compute Messages not found in HDF at '{compute_msgs_path}', "
                        f"falling back to .txt file extraction"
                    )

                    # Fallback to .txt file using RasControl
                    try:
                        # Late import to avoid circular dependency
                        from ..RasControl import RasControl

                        # Extract plan info from HDF path
                        # e.g., "C:/path/BaldEagle.p10.hdf" -> use path for RasControl
                        txt_contents = RasControl.get_comp_msgs(hdf_path)
                        if txt_contents:
                            logger.info(f"Successfully retrieved {len(txt_contents)} characters from .txt file")
                            return txt_contents
                    except Exception as e:
                        logger.debug(f".txt file fallback failed: {e}")

                    # Both methods failed
                    logger.debug(
                        f"No computation messages found in HDF or .txt sources for {hdf_path.name}"
                    )
                    return ""

                # Read dataset from HDF
                logger.info(f"Reading computation messages from HDF: {hdf_path.name}")
                dataset = hdf_file[compute_msgs_path]
                data = dataset[()]

                # Decode byte string to UTF-8
                if isinstance(data, bytes):
                    contents = data.decode('utf-8', errors='ignore')
                elif isinstance(data, np.ndarray) and len(data) > 0:
                    # Handle array of byte strings
                    if isinstance(data[0], bytes):
                        contents = data[0].decode('utf-8', errors='ignore')
                    else:
                        contents = str(data[0])
                else:
                    contents = str(data)

                logger.info(f"Successfully extracted {len(contents)} characters from HDF")
                return contents

        except FileNotFoundError:
            logger.debug(f"HDF file not found: {hdf_path}")

            # Try .txt fallback
            try:
                from ..RasControl import RasControl
                txt_contents = RasControl.get_comp_msgs(hdf_path)
                if txt_contents:
                    logger.warning(
                        f"HDF file not found, successfully retrieved computation messages from .txt file"
                    )
                    return txt_contents
            except Exception as e:
                logger.debug(f".txt file fallback failed: {e}")

            logger.debug(f"No computation messages found for {hdf_path.name}")
            return ""

        except Exception as e:
            logger.debug(f"Error reading computation messages from HDF: {str(e)}")

            # Try .txt fallback on any HDF error
            try:
                from ..RasControl import RasControl
                txt_contents = RasControl.get_comp_msgs(hdf_path)
                if txt_contents:
                    logger.warning(
                        f"HDF extraction failed, successfully retrieved computation messages from .txt file"
                    )
                    return txt_contents
            except Exception as fallback_error:
                logger.debug(f".txt file fallback failed: {fallback_error}")

            logger.debug(f"No computation messages found for {hdf_path.name}")
            return ""

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_compute_messages_hdf_only(hdf_path: Path) -> str:
        """
        Extract compute messages from HDF file or .txt files (no RasControl fallback).

        This method reads computation messages without using RasControl/COM interface,
        making it suitable for automated workflows where COM locking is problematic.

        Args:
            hdf_path: Path to plan HDF file (or plan number string if using
                     standardize_input decorator, which resolves to HDF path)

        Returns:
            str: Compute messages text, or empty string if unavailable

        Example:
            >>> from ras_commander import init_ras_project, HdfResultsPlan
            >>> init_ras_project(r"/path/to/project", "6.5")
            >>> msgs = HdfResultsPlan.get_compute_messages_hdf_only("01")
            >>> print(msgs)

        Note:
            Falls back to .txt files on disk but NEVER uses RasControl.
            Order of attempts:
            1. HDF Results/Summary/Compute Messages (text)
            2. {plan_file}.computeMsgs.txt (HEC-RAS 6.x+)
            3. {plan_file}.comp_msgs.txt (HEC-RAS 5.x)
        """
        # Attempt 1: Read from HDF file
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                compute_msgs_path = "Results/Summary/Compute Messages (text)"

                if compute_msgs_path in hdf_file:
                    logger.info(f"Reading computation messages from HDF: {hdf_path.name}")
                    dataset = hdf_file[compute_msgs_path]
                    data = dataset[()]

                    # Decode byte string to UTF-8
                    if isinstance(data, bytes):
                        contents = data.decode('utf-8', errors='ignore')
                    elif isinstance(data, np.ndarray) and len(data) > 0:
                        # Handle array of byte strings
                        if isinstance(data[0], bytes):
                            contents = data[0].decode('utf-8', errors='ignore')
                        else:
                            contents = str(data[0])
                    else:
                        contents = str(data)

                    logger.info(f"Successfully extracted {len(contents)} characters from HDF")
                    return contents
                else:
                    logger.debug(
                        f"Compute Messages not found in HDF at '{compute_msgs_path}', "
                        f"trying .txt file fallbacks"
                    )
        except FileNotFoundError:
            logger.debug(f"HDF file not found: {hdf_path}")
        except Exception as e:
            logger.debug(f"Error reading computation messages from HDF: {str(e)}")

        # Attempt 2: Read .computeMsgs.txt file (HEC-RAS 6.x+)
        try:
            # Convert HDF path to .computeMsgs.txt path
            # e.g., "plan.p01.hdf" -> "plan.p01.computeMsgs.txt"
            txt_path_6x = Path(str(hdf_path).replace('.hdf', '.computeMsgs.txt'))
            if txt_path_6x.exists():
                contents = txt_path_6x.read_text(encoding='utf-8', errors='ignore')
                logger.info(f"Successfully read {len(contents)} characters from {txt_path_6x.name}")
                return contents
            else:
                logger.debug(f".computeMsgs.txt file not found: {txt_path_6x}")
        except Exception as e:
            logger.debug(f"Error reading .computeMsgs.txt file: {str(e)}")

        # Attempt 3: Read .comp_msgs.txt file (HEC-RAS 5.x)
        try:
            # Convert HDF path to .comp_msgs.txt path
            # e.g., "plan.p01.hdf" -> "plan.p01.comp_msgs.txt"
            txt_path_5x = Path(str(hdf_path).replace('.hdf', '.comp_msgs.txt'))
            if txt_path_5x.exists():
                contents = txt_path_5x.read_text(encoding='utf-8', errors='ignore')
                logger.info(f"Successfully read {len(contents)} characters from {txt_path_5x.name}")
                return contents
            else:
                logger.debug(f".comp_msgs.txt file not found: {txt_path_5x}")
        except Exception as e:
            logger.debug(f"Error reading .comp_msgs.txt file: {str(e)}")

        # All methods failed - return empty string (no RasControl fallback)
        logger.debug(f"No computation messages found for {hdf_path.name} (HDF-only mode)")
        return ""

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_steady_results(hdf_path: Path) -> pd.DataFrame:
        """
        Extract steady state profile results from HEC-RAS HDF file.

        This function extracts all key hydraulic results for steady state
        profiles in a single call, matching the schema of RasControl.get_steady_results()
        for consistency between COM and HDF-based workflows.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file (.p##.hdf)

        Returns
        -------
        pd.DataFrame
            Steady state results with one row per cross-section per profile.

            **Schema:**

            +----------------+----------+---------------------------------------+
            | Column         | Type     | Description                           |
            +================+==========+=======================================+
            | river          | str      | River name                            |
            +----------------+----------+---------------------------------------+
            | reach          | str      | Reach name                            |
            +----------------+----------+---------------------------------------+
            | node_id        | str      | Cross section river station           |
            +----------------+----------+---------------------------------------+
            | profile        | str      | Profile name (e.g., "PF 1", "1Pct")   |
            +----------------+----------+---------------------------------------+
            | wsel           | float    | Water surface elevation (ft or m)     |
            +----------------+----------+---------------------------------------+
            | velocity       | float    | Channel velocity (ft/s or m/s)        |
            +----------------+----------+---------------------------------------+
            | flow           | float    | Total flow (cfs or cms)               |
            +----------------+----------+---------------------------------------+
            | froude         | float    | Channel Froude number (dimensionless) |
            +----------------+----------+---------------------------------------+
            | energy         | float    | Energy grade elevation (ft or m)      |
            +----------------+----------+---------------------------------------+
            | max_depth      | float    | Maximum channel depth (ft or m)       |
            +----------------+----------+---------------------------------------+
            | min_ch_el      | float    | Minimum channel elevation (ft or m)   |
            +----------------+----------+---------------------------------------+
            | top_width      | float    | Total top width (ft or m)             |
            +----------------+----------+---------------------------------------+
            | area           | float    | Total flow area (sq ft or sq m)       |
            +----------------+----------+---------------------------------------+
            | eg_slope       | float    | Energy grade slope (ft/ft or m/m)     |
            +----------------+----------+---------------------------------------+
            | friction_slope | float    | Friction slope (ft/ft or m/m)         |
            +----------------+----------+---------------------------------------+

        Raises
        ------
        ValueError
            If the HDF file does not contain steady state results.

        Notes
        -----
        **Comparison with RasControl.get_steady_results():**

        This HDF-based method provides the same schema as the COM-based
        RasControl.get_steady_results(), plus additional hydraulic variables
        (top_width, area, eg_slope, friction_slope) that are readily
        available in the HDF file.

        **Performance:**

        This method is significantly faster than COM-based extraction
        since it reads directly from the HDF file without opening HEC-RAS.

        Examples
        --------
        Extract all steady results:

        >>> from ras_commander import init_ras_project, HdfResultsPlan
        >>> init_ras_project("/path/to/project", "6.6")
        >>> df = HdfResultsPlan.get_steady_results("01")
        >>> df.to_csv('steady_results.csv', index=False)

        Filter by profile:

        >>> profile_1 = df[df['profile'] == 'PF 1']

        Plot water surface profile:

        >>> import matplotlib.pyplot as plt
        >>> plt.plot(profile_1['node_id'].astype(float), profile_1['wsel'])
        >>> plt.xlabel('Station')
        >>> plt.ylabel('Water Surface Elevation (ft)')

        See Also
        --------
        RasControl.get_steady_results : COM-based steady results extraction
        is_steady_plan : Check if plan contains steady results
        get_steady_profile_names : Get list of profile names
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Steady" not in hdf_file:
                    raise ValueError(
                        f"HDF file does not contain steady state results: {hdf_path.name}\n"
                        "Ensure this is a steady flow plan that has been computed."
                    )

                # Paths
                base_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
                xs_path = f"{base_path}/Cross Sections"
                add_vars_path = f"{xs_path}/Additional Variables"
                xs_attrs_path = "Results/Steady/Output/Geometry Info/Cross Section Attributes"
                profile_names_path = f"{base_path}/Profile Names"

                # Get profile names
                if profile_names_path in hdf_file:
                    profile_names_raw = hdf_file[profile_names_path][()]
                    profile_names = [
                        name.decode('utf-8').strip() if isinstance(name, bytes) else str(name).strip()
                        for name in profile_names_raw
                    ]
                else:
                    raise ValueError("Profile names not found in HDF file")

                # Get XS attributes
                xs_attrs = hdf_file[xs_attrs_path][()]
                num_xs = len(xs_attrs)
                num_profiles = len(profile_names)

                # Get main variables (WSE, Flow)
                wse_data = hdf_file[f"{xs_path}/Water Surface"][()]
                flow_data = hdf_file[f"{xs_path}/Flow"][()]

                # Get additional variables (with graceful fallback for missing)
                def get_additional_var(var_name, default=np.nan):
                    path = f"{add_vars_path}/{var_name}"
                    if path in hdf_file:
                        return hdf_file[path][()]
                    return np.full((num_profiles, num_xs), default)

                velocity_data = get_additional_var('Velocity Channel')
                energy_data = get_additional_var('Energy Grade')
                froude_data = get_additional_var('Froude # Channel')
                max_depth_data = get_additional_var('Hydraulic Depth Channel')
                min_ch_el_data = get_additional_var('Min Ch El')
                top_width_data = get_additional_var('Top Width Total')
                area_data = get_additional_var('Area Flow Total')
                eg_slope_data = get_additional_var('EG Slope')
                friction_slope_data = get_additional_var('Friction Slope')

                # Build results DataFrame
                rows = []
                for prof_idx, prof_name in enumerate(profile_names):
                    for xs_idx in range(num_xs):
                        river = xs_attrs[xs_idx]['River']
                        reach = xs_attrs[xs_idx]['Reach']
                        station = xs_attrs[xs_idx]['Station']

                        # Decode byte strings
                        river = river.decode('utf-8').strip() if isinstance(river, bytes) else str(river).strip()
                        reach = reach.decode('utf-8').strip() if isinstance(reach, bytes) else str(reach).strip()
                        station = station.decode('utf-8').strip() if isinstance(station, bytes) else str(station).strip()

                        rows.append({
                            'river': river,
                            'reach': reach,
                            'node_id': station,
                            'profile': prof_name,
                            'wsel': float(wse_data[prof_idx, xs_idx]),
                            'velocity': float(velocity_data[prof_idx, xs_idx]),
                            'flow': float(flow_data[prof_idx, xs_idx]),
                            'froude': float(froude_data[prof_idx, xs_idx]),
                            'energy': float(energy_data[prof_idx, xs_idx]),
                            'max_depth': float(max_depth_data[prof_idx, xs_idx]),
                            'min_ch_el': float(min_ch_el_data[prof_idx, xs_idx]),
                            'top_width': float(top_width_data[prof_idx, xs_idx]),
                            'area': float(area_data[prof_idx, xs_idx]),
                            'eg_slope': float(eg_slope_data[prof_idx, xs_idx]),
                            'friction_slope': float(friction_slope_data[prof_idx, xs_idx]),
                        })

                df = pd.DataFrame(rows)
                logger.info(f"Extracted steady results: {len(df)} rows "
                           f"({num_profiles} profiles x {num_xs} cross sections)")
                return df

        except Exception as e:
            logger.error(f"Error reading steady results: {str(e)}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def list_steady_variables(hdf_path: Path) -> Dict[str, List[str]]:
        """
        List all available steady state variables in the HDF file.

        This is a diagnostic function useful for exploring what data
        is available in a particular steady state results file.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file

        Returns
        -------
        Dict[str, List[str]]
            Dictionary with keys:
            - 'cross_sections': Variables in Cross Sections group
            - 'additional': Variables in Additional Variables group
            - 'structures': Variables in Structures group (if present)

        Example
        -------
        >>> vars = HdfResultsPlan.list_steady_variables('01')
        >>> print(vars['additional'])
        ['Area Flow Channel', 'Velocity Channel', 'Top Width Total', ...]
        """
        try:
            result = {
                'cross_sections': [],
                'additional': [],
                'structures': []
            }

            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Steady" not in hdf_file:
                    logger.warning("No steady state results in this file")
                    return result

                base_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"

                # Cross Sections variables
                xs_path = f"{base_path}/Cross Sections"
                if xs_path in hdf_file:
                    xs_group = hdf_file[xs_path]
                    for key in xs_group.keys():
                        if isinstance(xs_group[key], h5py.Dataset):
                            result['cross_sections'].append(key)

                # Additional Variables
                add_path = f"{xs_path}/Additional Variables"
                if add_path in hdf_file:
                    add_group = hdf_file[add_path]
                    for key in add_group.keys():
                        if isinstance(add_group[key], h5py.Dataset):
                            result['additional'].append(key)

                # Structures
                struct_path = f"{base_path}/Structures"
                if struct_path in hdf_file:
                    struct_group = hdf_file[struct_path]
                    for key in struct_group.keys():
                        if isinstance(struct_group[key], h5py.Dataset):
                            result['structures'].append(key)

                logger.info(f"Found {len(result['cross_sections'])} XS vars, "
                           f"{len(result['additional'])} additional vars, "
                           f"{len(result['structures'])} structure vars")

                return result

        except Exception as e:
            logger.error(f"Error listing steady variables: {str(e)}")
            return {'cross_sections': [], 'additional': [], 'structures': []}
