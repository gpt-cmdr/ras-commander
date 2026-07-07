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


_PUMP_RESULTS_ACTION = (
    "Compute the plan with pump station output available, then retry."
)


def _format_available_items(items: List[str], max_items: int = 12) -> str:
    if not items:
        return "none"

    shown = items[:max_items]
    suffix = f", ... ({len(items) - max_items} more)" if len(items) > max_items else ""
    return ", ".join(shown) + suffix


def _available_group_names(hdf: h5py.File, group_path: str) -> List[str]:
    if group_path not in hdf:
        return []
    return sorted(str(name) for name in hdf[group_path].keys())


def _missing_hdf_object_message(context: str, hdf_path: str, action: str) -> str:
    return f"{context} requires HDF object '{hdf_path}', but it was not found. {action}"


def _empty_pump_stations_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"station_id": []}, geometry=[], crs=None)


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
                - Additional attributes from the HDF file. Returns an empty
                  GeoDataFrame when the HDF file contains no pump station group.

        Raises:
            KeyError: If the pump station group exists but required datasets are missing.
        """
        with h5py.File(hdf_path, 'r') as hdf:
            pump_stations_path = "/Geometry/Pump Stations"
            if pump_stations_path not in hdf:
                logger.debug("No pump station geometry group found in HDF file")
                return _empty_pump_stations_gdf()

            group = hdf[pump_stations_path]
            for dataset_name in ["Attributes", "Points"]:
                if dataset_name not in group:
                    raise KeyError(_missing_hdf_object_message(
                        "Pump station geometry extraction",
                        f"{pump_stations_path}/{dataset_name}",
                        "Verify the HDF was written with pump station geometry data.",
                    ))

            attributes = group['Attributes'][()]
            points = group['Points'][()]

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
                - Additional attributes from the HDF file. Returns an empty
                  DataFrame when the HDF file contains no pump station group.

        Raises:
            KeyError: If the pump group exists but required datasets are missing.
        """
        with h5py.File(hdf_path, 'r') as hdf:
            pump_groups_path = "/Geometry/Pump Stations/Pump Groups"
            if pump_groups_path not in hdf:
                logger.debug("No pump station pump-group geometry found in HDF file")
                return pd.DataFrame()

            group = hdf[pump_groups_path]
            required_datasets = [
                "Attributes",
                "Efficiency Curves Info",
                "Efficiency Curves Values",
            ]
            missing_datasets = [
                f"{pump_groups_path}/{dataset_name}"
                for dataset_name in required_datasets
                if dataset_name not in group
            ]
            if missing_datasets:
                raise KeyError(
                    "Pump group extraction found an incomplete pump group geometry. "
                    f"Missing: {_format_available_items(missing_datasets)}. "
                    "Verify the HDF was written with pump group geometry data."
                )

            attributes = group['Attributes'][()]
            efficiency_curves_info = group['Efficiency Curves Info'][()]
            efficiency_curves_values = group['Efficiency Curves Values'][()]

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
        """
        with h5py.File(hdf_path, 'r') as hdf:
            pumping_stations_path = (
                "/Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/"
                "Unsteady Time Series/Pumping Stations"
            )
            if pumping_stations_path not in hdf:
                raise KeyError(_missing_hdf_object_message(
                    "Pump station timeseries extraction",
                    pumping_stations_path,
                    _PUMP_RESULTS_ACTION,
                ))

            available_stations = _available_group_names(hdf, pumping_stations_path)
            if pump_station not in hdf[pumping_stations_path]:
                raise ValueError(
                    f"Pump station '{pump_station}' was not found in HDF group "
                    f"'{pumping_stations_path}'. Available pump stations: "
                    f"{_format_available_items(available_stations)}."
                )

            data_path = f"{pumping_stations_path}/{pump_station}/Structure Variables"
            if data_path not in hdf:
                raise KeyError(_missing_hdf_object_message(
                    f"Pump station timeseries extraction for '{pump_station}'",
                    data_path,
                    _PUMP_RESULTS_ACTION,
                ))

            data = hdf[data_path][()]

            # Extract time information - try DSS-specific timestamps first
            dss_time_path = "/Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Time Date Stamp (ms)"

            if dss_time_path in hdf:
                # Use DSS Hydrograph Output timestamps
                raw_datetimes = hdf[dss_time_path][:]
                time = [HdfUtils.parse_ras_datetime_ms(x.decode("utf-8")) for x in raw_datetimes]
            else:
                # Fallback to Base Output timestamps
                time = HdfBase.get_unsteady_timestamps(hdf)

            # Verify time dimension matches data, use index if mismatch
            if len(time) != data.shape[0]:
                logger.warning(
                    "Pump station timeseries timestamp mismatch for '%s' at '%s': "
                    "timestamps=%d rows=%d; using numeric time index",
                    pump_station,
                    data_path,
                    len(time),
                    data.shape[0],
                )
                time = list(range(data.shape[0]))

            variable_units = hdf[data_path].attrs.get('Variable_Unit', None)
            variable_names, unit_by_variable = HdfPump._pump_variable_columns(
                variable_units,
                data.shape[1],
            )

            # Create DataArray
            da = xr.DataArray(
                data=data,
                dims=['time', 'variable'],
                coords={'time': time, 'variable': variable_names},
                name=pump_station
            )

            # Add attributes and decode byte strings
            da.attrs['units'] = variable_units
            da.attrs['unit_by_variable'] = unit_by_variable
            da.attrs['pump_station'] = pump_station

            return da

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

        Notes:
            Missing pump station summary output returns an empty DataFrame.
        """
        with h5py.File(hdf_path, 'r') as hdf:
            # Extract summary data
            summary_path = "/Results/Unsteady/Summary/Pump Station"
            if summary_path not in hdf:
                logger.debug("Pump station summary data not found in HDF file")
                return pd.DataFrame()

            summary_data = hdf[summary_path][()]

            # Create DataFrame and decode byte strings
            df = pd.DataFrame(summary_data)
            string_columns = df.select_dtypes([object]).columns
            for col in string_columns:
                df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

            return df

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
        """
        with h5py.File(hdf_path, 'r') as hdf:
            pump_stations_path = (
                "/Results/Unsteady/Output/Output Blocks/DSS Profile Output/"
                "Unsteady Time Series/Pumping Stations"
            )
            if pump_stations_path not in hdf:
                raise KeyError(_missing_hdf_object_message(
                    "Pump station operation extraction",
                    pump_stations_path,
                    _PUMP_RESULTS_ACTION,
                ))

            available_stations = _available_group_names(hdf, pump_stations_path)
            if pump_station not in hdf[pump_stations_path]:
                raise ValueError(
                    f"Pump station '{pump_station}' was not found in HDF group "
                    f"'{pump_stations_path}'. Available pump stations: "
                    f"{_format_available_items(available_stations)}."
                )

            # Extract pump operation data
            data_path = f"{pump_stations_path}/{pump_station}/Structure Variables"
            if data_path not in hdf:
                raise KeyError(_missing_hdf_object_message(
                    f"Pump station operation extraction for '{pump_station}'",
                    data_path,
                    _PUMP_RESULTS_ACTION,
                ))

            data = hdf[data_path][()]

            # Extract time information - Updated to use new method name
            time = HdfBase.get_unsteady_timestamps(hdf)

            variable_units = hdf[data_path].attrs.get('Variable_Unit', None)
            variable_names, unit_by_variable = HdfPump._pump_variable_columns(
                variable_units,
                data.shape[1],
            )

            # Create DataFrame and decode byte strings
            df = pd.DataFrame(data, columns=variable_names)
            string_columns = df.select_dtypes([object]).columns
            for col in string_columns:
                df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

            df['Time'] = time
            df.attrs['unit_by_variable'] = unit_by_variable

            return df

    @staticmethod
    def _pump_variable_columns(variable_units: Any, column_count: int) -> tuple[List[str], Dict[str, str]]:
        """
        Build unique pump result column names from the HEC-RAS Variable_Unit attr.

        HEC-RAS writes five columns for simple pump stations and additional
        flow/on columns for each pump group. Older ras-commander releases
        assumed exactly five columns, which fails for multi-group stations.
        """
        fallback_names = ['Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on']
        if variable_units is None:
            names = fallback_names[:column_count]
            names.extend([f"Variable {idx + 1}" for idx in range(len(names), column_count)])
            return names, {name: "" for name in names}

        rows = np.asarray(variable_units)
        if rows.ndim != 2 or rows.shape[1] < 2:
            names = fallback_names[:column_count]
            names.extend([f"Variable {idx + 1}" for idx in range(len(names), column_count)])
            return names, {name: "" for name in names}

        decoded_rows = [
            (
                HdfPump._decode_hdf_text(row[0]),
                HdfPump._decode_hdf_text(row[1]),
            )
            for row in rows[:column_count]
        ]

        if column_count == 5 and len(decoded_rows) >= 5:
            names = fallback_names.copy()
        else:
            names = []
            for label, unit in decoded_rows:
                unit_lower = unit.lower()
                if label in {'Flow', 'Stage HW', 'Stage TW'}:
                    column_name = label
                elif unit_lower == 'pumps on':
                    column_name = f"{label} Pumps on"
                elif unit_lower == 'cfs':
                    column_name = f"{label} Flow"
                elif unit:
                    column_name = f"{label} ({unit})"
                else:
                    column_name = label
                names.append(column_name)

        if len(names) < column_count:
            names.extend([f"Variable {idx + 1}" for idx in range(len(names), column_count)])

        names = HdfPump._dedupe_names(names[:column_count])
        unit_by_variable = {
            name: decoded_rows[idx][1] if idx < len(decoded_rows) else ""
            for idx, name in enumerate(names)
        }
        return names, unit_by_variable

    @staticmethod
    def _decode_hdf_text(value: Any) -> str:
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode('utf-8').strip()
        return str(value).strip()

    @staticmethod
    def _dedupe_names(names: List[str]) -> List[str]:
        counts: Dict[str, int] = {}
        result: List[str] = []
        for name in names:
            counts[name] = counts.get(name, 0) + 1
            if counts[name] == 1:
                result.append(name)
            else:
                result.append(f"{name} {counts[name]}")
        return result
