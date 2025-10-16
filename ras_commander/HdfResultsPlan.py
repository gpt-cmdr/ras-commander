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
from .RasPrj import ras

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