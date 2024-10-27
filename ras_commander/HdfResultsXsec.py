"""
Class: HdfResultsXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Tuple

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

class HdfResultsXsec:
    """
    A class for handling cross-section results from HEC-RAS HDF files.

    This class provides methods to extract and process steady flow simulation results
    for cross-sections, including water surface elevations, flow rates, energy grades,
    and additional parameters such as encroachment stations and velocities.

    The class relies on the HdfBase and HdfUtils classes for core HDF file operations
    and utility functions.

    Attributes:
        None

    
    """












    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_station_profile_output(hdf_path: Path) -> pd.DataFrame:
        """
        Extract pump station profile output data from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pump station profile output data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract profile output data
                profile_path = "/Results/Unsteady/Output/Output Blocks/DSS Profile Output/Unsteady Time Series/Pumping Stations"
                if profile_path not in hdf:
                    logger.warning("Pump Station profile output data not found in HDF file")
                    return pd.DataFrame()

                # Initialize an empty list to store data from all pump stations
                all_data = []

                # Iterate through all pump stations
                for station in hdf[profile_path].keys():
                    station_path = f"{profile_path}/{station}/Structure Variables"
                    
                    data = hdf[station_path][()]
                    
                    # Create a DataFrame for this pump station
                    df = pd.DataFrame(data, columns=['Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on'])
                    df['Station'] = station
                    
                    all_data.append(df)

                # Concatenate all DataFrames
                result_df = pd.concat(all_data, ignore_index=True)

                # Add time information
                time = HdfBase._get_unsteady_datetimes(hdf)
                result_df['Time'] = [time[i] for i in result_df.index]

                return result_df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pump station profile output data: {e}")
            raise

















    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_station_summary(hdf_path: Path) -> pd.DataFrame:
        """
        Extract summary data for pump stations from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pump station summary data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract summary data
                summary_path = "/Results/Unsteady/Summary/Pump Station"
                if summary_path not in hdf:
                    logger.warning("Pump Station summary data not found in HDF file")
                    return pd.DataFrame()

                summary_data = hdf[summary_path][()]
                
                # Create DataFrame
                df = pd.DataFrame(summary_data)

                # Convert column names
                df.columns = [col.decode('utf-8') if isinstance(col, bytes) else col for col in df.columns]

                # Convert byte string values to regular strings
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pump station summary data: {e}")
            raise




# Tested functions from AWS webinar where the code was developed
# Need to add examples


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def extract_cross_section_results(hdf_path: Path) -> xr.Dataset:
        """
        Extract Water Surface, Velocity Total, Velocity Channel, Flow Lateral, and Flow data from HEC-RAS HDF file.
        Includes Cross Section Only and Cross Section Attributes as coordinates in the xarray.Dataset.
        Also calculates maximum values for key parameters.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file

        Returns:
        --------
        xr.Dataset
            Xarray Dataset containing the extracted cross-section results with appropriate coordinates and attributes.
            Includes maximum values for Water Surface, Flow, Channel Velocity, Total Velocity, and Lateral Flow.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Define base paths
                base_output_path = "/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/"
                time_stamp_path = "/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp (ms)"
                
                # Extract Cross Section Attributes
                attrs_dataset = hdf_file[f"{base_output_path}Cross Section Attributes"][:]
                rivers = [attr['River'].decode('utf-8').strip() for attr in attrs_dataset]
                reaches = [attr['Reach'].decode('utf-8').strip() for attr in attrs_dataset]
                stations = [attr['Station'].decode('utf-8').strip() for attr in attrs_dataset]
                names = [attr['Name'].decode('utf-8').strip() for attr in attrs_dataset]
                
                # Extract Cross Section Only (Unique Names)
                cross_section_only_dataset = hdf_file[f"{base_output_path}Cross Section Only"][:]
                cross_section_names = [cs.decode('utf-8').strip() for cs in cross_section_only_dataset]
                
                # Extract Time Stamps and convert to datetime
                time_stamps = hdf_file[time_stamp_path][:]
                if any(isinstance(ts, bytes) for ts in time_stamps):
                    time_stamps = [ts.decode('utf-8') for ts in time_stamps]
                # Convert RAS format timestamps to datetime
                times = pd.to_datetime(time_stamps, format='%d%b%Y %H:%M:%S:%f')
                
                # Extract Required Datasets
                water_surface = hdf_file[f"{base_output_path}Water Surface"][:]
                velocity_total = hdf_file[f"{base_output_path}Velocity Total"][:]
                velocity_channel = hdf_file[f"{base_output_path}Velocity Channel"][:]
                flow_lateral = hdf_file[f"{base_output_path}Flow Lateral"][:]
                flow = hdf_file[f"{base_output_path}Flow"][:]
                
                # Calculate maximum values along time axis
                max_water_surface = np.max(water_surface, axis=0)
                max_flow = np.max(flow, axis=0)
                max_velocity_channel = np.max(velocity_channel, axis=0)
                max_velocity_total = np.max(velocity_total, axis=0)
                max_flow_lateral = np.max(flow_lateral, axis=0)
                
                # Create Xarray Dataset
                ds = xr.Dataset(
                    {
                        'Water_Surface': (['time', 'cross_section'], water_surface),
                        'Velocity_Total': (['time', 'cross_section'], velocity_total),
                        'Velocity_Channel': (['time', 'cross_section'], velocity_channel),
                        'Flow_Lateral': (['time', 'cross_section'], flow_lateral),
                        'Flow': (['time', 'cross_section'], flow),
                    },
                    coords={
                        'time': times,
                        'cross_section': cross_section_names,
                        'River': ('cross_section', rivers),
                        'Reach': ('cross_section', reaches),
                        'Station': ('cross_section', stations),
                        'Name': ('cross_section', names),
                        'Maximum_Water_Surface': ('cross_section', max_water_surface),
                        'Maximum_Flow': ('cross_section', max_flow),
                        'Maximum_Channel_Velocity': ('cross_section', max_velocity_channel),
                        'Maximum_Velocity_Total': ('cross_section', max_velocity_total),
                        'Maximum_Flow_Lateral': ('cross_section', max_flow_lateral)
                    },
                    attrs={
                        'description': 'Cross-section results extracted from HEC-RAS HDF file',
                        'source_file': str(hdf_path)
                    }
                )
                
                return ds

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting cross section results: {e}")
            raise

