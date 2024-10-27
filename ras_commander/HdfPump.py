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
from .Decorators import standardize_input, log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

class HdfPump:
    """
    A class for handling pump station related data from HEC-RAS HDF files.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_stations(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Extract pump station data from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing pump station data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
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
                crs = HdfUtils.projection(hdf_path)
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
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pump group data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
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
        Extract timeseries data for a specific pump station.

        Args:
            hdf_path (Path): Path to the HDF file.
            pump_station (str): Name of the pump station.

        Returns:
            xr.DataArray: DataArray containing the timeseries data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
            ValueError: If the specified pump station is not found.
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

                # Extract time information
                time = HdfBase._get_unsteady_datetimes(hdf)

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
    def get_pump_operation_data(hdf_path: Path, pump_station: str) -> pd.DataFrame:
        """
        Extract pump operation data for a specific pump station.

        Args:
            hdf_path (Path): Path to the HDF file.
            pump_station (str): Name of the pump station.

        Returns:
            pd.DataFrame: DataFrame containing pump operation data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
            ValueError: If the specified pump station is not found.
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

                # Extract time information
                time = HdfBase._get_unsteady_datetimes(hdf)

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