"""
Class: HdfPump

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfPump:
- get_pump_stations()
- get_pump_groups()
- get_pump_station_timeseries()
- get_pump_station_summary()
- get_pump_operation_timeseries()


"""


import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from pathlib import Path
from shapely.geometry import Point
from typing import List, Dict, Any, Optional, Union
from .HdfUtils import HdfUtils
from .HdfBase import HdfBase
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

class HdfPump:
    """
    A class for handling pump station related data from HEC-RAS HDF files.

    This class provides static methods to extract and process pump station data, including:
    - Pump station locations and attributes
    - Pump group configurations and efficiency curves
    - Time series results for pump operations
    - Summary statistics for pump stations

    All methods are static and designed to work with HEC-RAS HDF files containing pump data.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_stations(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Extract pump station data from the HDF file.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing pump station data with columns:
                - geometry: Point geometry of pump station location
                - station_id: Unique identifier for each pump station
                - Additional attributes from the HDF file

        Raises:
            KeyError: If pump station datasets are not found in the HDF file.
            Exception: If there are errors processing the pump station data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract pump station data
                attributes = hdf['/Geometry/Pump Stations/Attributes'][()]
                points = hdf['/Geometry/Pump Stations/Points'][()]

                # Create geometries
                geometries = [Point(x, y) for x, y in points]

                # Create GeoDataFrame
                gdf = gpd.GeoDataFrame(geometry=geometries)
                gdf['station_id'] = range(len(gdf))

                # Add attributes and decode byte strings
                attr_df = pd.DataFrame(attributes)
                string_columns = attr_df.select_dtypes([object]).columns
                for col in string_columns:
                    attr_df[col] = attr_df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                
                for col in attr_df.columns:
                    gdf[col] = attr_df[col]

                # Set CRS if available
                crs = HdfBase.get_projection(hdf_path)
                if crs:
                    gdf.set_crs(crs, inplace=True)

                return gdf

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pump station data: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_groups(hdf_path: Path) -> pd.DataFrame:
        """
        Extract pump group data from the HDF file.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pump group data with columns:
                - efficiency_curve_start: Starting index of efficiency curve data
                - efficiency_curve_count: Number of points in efficiency curve
                - efficiency_curve: List of efficiency curve values
                - Additional attributes from the HDF file

        Raises:
            KeyError: If pump group datasets are not found in the HDF file.
            Exception: If there are errors processing the pump group data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract pump group data
                attributes = hdf['/Geometry/Pump Stations/Pump Groups/Attributes'][()]
                efficiency_curves_info = hdf['/Geometry/Pump Stations/Pump Groups/Efficiency Curves Info'][()]
                efficiency_curves_values = hdf['/Geometry/Pump Stations/Pump Groups/Efficiency Curves Values'][()]

                # Create DataFrame and decode byte strings
                df = pd.DataFrame(attributes)
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

                # Add efficiency curve data
                df['efficiency_curve_start'] = efficiency_curves_info[:, 0]
                df['efficiency_curve_count'] = efficiency_curves_info[:, 1]

                # Process efficiency curves
                def get_efficiency_curve(start, count):
                    return efficiency_curves_values[start:start+count].tolist()

                df['efficiency_curve'] = df.apply(lambda row: get_efficiency_curve(row['efficiency_curve_start'], row['efficiency_curve_count']), axis=1)

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pump group data: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_station_timeseries(hdf_path: Path, pump_station: str) -> xr.DataArray:
        """
        Extract timeseries results data for a specific pump station.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.
            pump_station (str): Name or identifier of the pump station.

        Returns:
            xr.DataArray: DataArray containing the timeseries data with dimensions:
                - time: Timestamps of simulation
                - variable: Variables including ['Flow', 'Stage HW', 'Stage TW', 
                           'Pump Station', 'Pumps on']
            Attributes include units and pump station name.

        Raises:
            KeyError: If required datasets are not found in the HDF file.
            ValueError: If the specified pump station name is not found.
            Exception: If there are errors processing the timeseries data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Check if the pump station exists
                pumping_stations_path = "/Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Pumping Stations"
                if pump_station not in hdf[pumping_stations_path]:
                    raise ValueError(f"Pump station '{pump_station}' not found in HDF file")

                # Extract timeseries data
                data_path = f"{pumping_stations_path}/{pump_station}/Structure Variables"
                data = hdf[data_path][()]

                # Extract time information - Updated to use new method name
                time = HdfBase.get_unsteady_timestamps(hdf)

                # Create DataArray
                da = xr.DataArray(
                    data=data,
                    dims=['time', 'variable'],
                    coords={'time': time, 'variable': ['Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on']},
                    name=pump_station
                )

                # Add attributes and decode byte strings
                units = hdf[data_path].attrs.get('Variable_Unit', b'')
                da.attrs['units'] = units.decode('utf-8') if isinstance(units, bytes) else units
                da.attrs['pump_station'] = pump_station

                return da

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except ValueError as e:
            logger.error(str(e))
            raise
        except Exception as e:
            logger.error(f"Error extracting pump station timeseries data: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_station_summary(hdf_path: Path) -> pd.DataFrame:
        """
        Extract summary statistics and performance data for all pump stations.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pump station summary data including
                operational statistics and performance metrics. Returns empty DataFrame
                if no summary data is found.

        Raises:
            KeyError: If the summary dataset is not found in the HDF file.
            Exception: If there are errors processing the summary data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract summary data
                summary_path = "/Results/Unsteady/Summary/Pump Station"
                if summary_path not in hdf:
                    logger.warning("Pump Station summary data not found in HDF file")
                    return pd.DataFrame()

                summary_data = hdf[summary_path][()]
                
                # Create DataFrame and decode byte strings
                df = pd.DataFrame(summary_data)
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pump station summary data: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_operation_timeseries(hdf_path: Path, pump_station: str) -> pd.DataFrame:
        """
        Extract detailed pump operation results data for a specific pump station.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.
            pump_station (str): Name or identifier of the pump station.

        Returns:
            pd.DataFrame: DataFrame containing pump operation data with columns:
                - Time: Simulation timestamps
                - Flow: Pump flow rate
                - Stage HW: Headwater stage
                - Stage TW: Tailwater stage
                - Pump Station: Station identifier
                - Pumps on: Number of active pumps

        Raises:
            KeyError: If required datasets are not found in the HDF file.
            ValueError: If the specified pump station name is not found.
            Exception: If there are errors processing the operation data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Check if the pump station exists
                pump_stations_path = "/Results/Unsteady/Output/Output Blocks/DSS Profile Output/Unsteady Time Series/Pumping Stations"
                if pump_station not in hdf[pump_stations_path]:
                    raise ValueError(f"Pump station '{pump_station}' not found in HDF file")

                # Extract pump operation data
                data_path = f"{pump_stations_path}/{pump_station}/Structure Variables"
                data = hdf[data_path][()]

                # Extract time information - Updated to use new method name
                time = HdfBase.get_unsteady_timestamps(hdf)

                # Create DataFrame and decode byte strings
                df = pd.DataFrame(data, columns=['Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on'])
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                    
                df['Time'] = time

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except ValueError as e:
            logger.error(str(e))
            raise
        except Exception as e:
            logger.error(f"Error extracting pump operation data: {e}")
            raise