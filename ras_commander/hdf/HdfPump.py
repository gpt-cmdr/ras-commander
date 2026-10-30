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

from __future__ import annotations



import h5py
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from .._optional_deps import optional_module, require_module
from .HdfUtils import HdfUtils
from .HdfBase import HdfBase
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from ..fast_hdf import read_attr, read_typed

gpd = optional_module("geopandas", "Returning GeoDataFrame results from HdfPump")
xr = optional_module("xarray", "Returning xarray results from HdfPump")

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
    def get_pump_stations(
        hdf_path: Path,
        *,
        include_geometry: bool = True,
    ) -> Union[gpd.GeoDataFrame, pd.DataFrame]:
        """
        Extract pump station data from the HDF file.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.
            include_geometry (bool): Keyword-only. Pump stations are point
                features, so the default True returns the GeoDataFrame below.
                False is a table-only convenience without GeoPandas/Shapely or
                a CRS lookup: ``station_id`` (``int64``), the Attributes
                fields (text as pandas ``str``/``string``, numbers in their stored
                dtypes), then the stored ``x``/``y`` coordinates.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing pump station data with columns:
                - geometry: Point geometry of pump station location
                - station_id: Unique identifier for each pump station
                - Additional attributes from the HDF file. Returns an empty
                  GeoDataFrame when the HDF file contains no pump station group.

        Raises:
            KeyError: If the pump station group exists but required datasets are missing.
        """
        if include_geometry:
            shapely_geometry = require_module("shapely.geometry", "Returning GeoDataFrame results from HdfPump")
            Point = shapely_geometry.Point

        with h5py.File(hdf_path, 'r') as hdf:
            pump_stations_path = "/Geometry/Pump Stations"
            if pump_stations_path not in hdf:
                logger.debug("No pump station geometry group found in HDF file")
                if not include_geometry:
                    return pd.DataFrame({
                        "station_id": pd.Series(dtype="int64"),
                        "x": pd.Series(dtype="float64"),
                        "y": pd.Series(dtype="float64"),
                    })
                return _empty_pump_stations_gdf()

            group = hdf[pump_stations_path]
            for dataset_name in ["Attributes", "Points"]:
                if dataset_name not in group:
                    raise KeyError(_missing_hdf_object_message(
                        "Pump station geometry extraction",
                        f"{pump_stations_path}/{dataset_name}",
                        "Verify the HDF was written with pump station geometry data.",
                    ))

            attributes = read_typed(group['Attributes'])
            points = read_typed(group['Points'])

            if not include_geometry:
                table = pd.DataFrame({"station_id": np.arange(len(points), dtype=np.int64)})
                attr_df = pd.DataFrame(attributes)
                for col in attr_df.columns:
                    values = attr_df[col]
                    if values.dtype == object:
                        values = values.apply(
                            lambda x: x.decode('utf-8') if isinstance(x, bytes) else x
                        ).astype(HdfUtils._TEXT_DTYPE)
                    table[col] = values
                table["x"] = points[:, 0]
                table["y"] = points[:, 1]
                return table

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

            attributes = read_typed(group['Attributes'])
            efficiency_curves_info = read_typed(group['Efficiency Curves Info'])
            efficiency_curves_values = read_typed(group['Efficiency Curves Values'])

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

        Time comes only from DSS Hydrograph Output: stored timestamps, or its
        numeric Time in days when timestamps are absent (time.units='days').
        Missing or malformed axes raise; Base Output and integer row indexes
        are never substituted. DSS timestamp text may have seconds or milliseconds.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.
            pump_station (str): Name or identifier of the pump station.

        Returns:
            xr.DataArray: DataArray containing the timeseries data with dimensions:
                - time: Stored simulation timestamps, or elapsed days if absent
                - variable: Variables including ['Flow', 'Stage HW', 'Stage TW', 
                           'Pump Station', 'Pumps on']
            Attributes include units and pump station name.

        Raises:
            KeyError: If required datasets are not found in the HDF file.
            ValueError: If the station is absent or its block-local time axis
                is malformed or has a different row count from the results.
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

            data = read_typed(hdf[data_path])

            time, time_units = HdfPump._pump_block_time(hdf, data_path, data.shape)

            variable_units = read_attr(hdf[data_path], 'Variable_Unit', None)
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
            if time_units:
                da.coords['time'].attrs['units'] = time_units

            return da

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_station_summary(hdf_path: Path) -> pd.DataFrame:
        """
        Summarize each pump station's stored DSS Hydrograph Output results.

        HEC-RAS (verified 6.6 and 7.0.1) writes no pump station summary table:
        ``/Results/Unsteady/Summary`` holds only run and volume-accounting data,
        and ``Base Output/Summary Output`` has no pump station group. Pump
        results are stored only as time series in each output block under
        ``Unsteady Time Series/Pumping Stations/<station>/Structure Variables``
        (columns named by its ``Variable_Unit`` attribute). This method derives
        the summary from the ``DSS Hydrograph Output`` block, the same block
        and time axis :meth:`get_pump_station_timeseries` returns.

        Every statistic is derived exactly from the stored samples (no
        interpolation): the maximum/minimum is the largest/smallest stored
        finite value, and its time is the stored time of its first
        occurrence. Only output-interval samples are stored, so a peak
        between samples is not represented. Non-finite samples are ignored; a
        variable with no finite sample gets NaN values and times.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.

        Returns:
            pd.DataFrame: One row per pump station (stored group order) with:
                - Pump Station: station name (the result group name)
                - Output Block: always ``'DSS Hydrograph Output'``
                - Time Steps: number of stored samples
                - Start Time / End Time: first and last stored times
                - Max Flow, Max Flow Time, Min Flow, Min Flow Time
                - Max Stage HW, Max Stage HW Time, Min Stage HW, Min Stage HW Time
                - Max Stage TW, Max Stage TW Time, Min Stage TW, Min Stage TW Time
                - Max Pumps On, Max Pumps On Time: largest per-step sum of the
                  stored pump-group ``Pumps on`` columns (NaN when the station
                  stores no such column)
                - Highest Elev Pump Line: the station group's stored attribute,
                  NaN when HEC-RAS did not write it (e.g. Davis, OrleansEx)

            Times are timestamps parsed from the block's stored
            ``Time Date Stamp`` text, or elapsed days from its numeric ``Time``
            dataset when no timestamps are stored (then
            ``attrs['time_units'] = 'days'``). ``attrs['units']`` maps each
            summarized variable to its stored unit. HEC-RAS does not store
            pumped volume, pump run time or energy, so they are not reported.
            Returns an empty DataFrame (with a debug log) when the file has no
            DSS Hydrograph Output pump station results.

        Raises:
            ValueError: If a station's stored layout is not the proven one
                (2-D float data whose ``Variable_Unit`` labels begin with Flow,
                Stage HW, Stage TW) or its block time axis is malformed.
            KeyError: If a station has no Structure Variables dataset or the
                block stores no time axis.
        """
        stations_path = (
            "/Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/"
            "Unsteady Time Series/Pumping Stations"
        )
        with h5py.File(hdf_path, 'r') as hdf:
            group = hdf.get(stations_path)
            if not isinstance(group, h5py.Group) or len(group) == 0:
                logger.debug(
                    "Pump station summary data not found in HDF file: no stations in '%s'",
                    stations_path,
                )
                return pd.DataFrame()

            rows = []
            units: Dict[str, str] = {}
            time_units = None
            for station in group.keys():
                data_path = f"{stations_path}/{station}/Structure Variables"
                dataset = hdf.get(data_path)
                if not isinstance(dataset, h5py.Dataset):
                    raise KeyError(_missing_hdf_object_message(
                        f"Pump station summary for '{station}'",
                        data_path,
                        _PUMP_RESULTS_ACTION,
                    ))
                if len(dataset.shape) != 2 or dataset.dtype.kind != 'f':
                    raise ValueError(
                        f"Pump results at '{data_path}' must be 2-D floating point; "
                        f"found shape {dataset.shape} dtype {dataset.dtype}"
                    )
                labels = HdfPump._summary_labels(
                    read_attr(dataset, 'Variable_Unit', None),
                    dataset.shape[1],
                    data_path,
                )
                data = read_typed(dataset)
                time, time_units = HdfPump._pump_block_time(hdf, data_path, data.shape)
                time = pd.to_datetime(time) if time_units is None else np.asarray(time)
                time = np.asarray(time)

                row: Dict[str, Any] = {
                    'Pump Station': str(station),
                    'Output Block': 'DSS Hydrograph Output',
                    'Time Steps': int(data.shape[0]),
                    'Start Time': time[0] if len(time) else np.nan,
                    'End Time': time[-1] if len(time) else np.nan,
                }
                for idx, name in enumerate(('Flow', 'Stage HW', 'Stage TW')):
                    units[name] = labels[idx][1]
                    HdfPump._add_extremes(row, name, data[:, idx], time)
                pump_columns = [
                    idx for idx, (_, unit) in enumerate(labels)
                    if idx >= 3 and unit.lower() == 'pumps on'
                ]
                if pump_columns:
                    pumps_on = data[:, pump_columns].astype(np.float64).sum(axis=1)
                    HdfPump._add_extremes(row, 'Pumps On', pumps_on, time, minimum=False)
                else:
                    row['Max Pumps On'] = np.nan
                    row['Max Pumps On Time'] = np.nan
                units['Pumps On'] = 'Pumps on'
                highest = read_attr(
                    hdf[f"{stations_path}/{station}"], 'Highest Elev Pump Line', None
                )
                row['Highest Elev Pump Line'] = (
                    float(np.asarray(highest).reshape(-1)[0]) if highest is not None else np.nan
                )
                rows.append(row)

        df = pd.DataFrame(rows)
        df['Time Steps'] = df['Time Steps'].astype('int64')
        for column in df.columns:
            if column.startswith(('Max ', 'Min ')) and not column.endswith(' Time'):
                df[column] = df[column].astype('float64')
        df['Highest Elev Pump Line'] = df['Highest Elev Pump Line'].astype('float64')
        df.attrs['units'] = units
        if time_units:
            df.attrs['time_units'] = time_units
        return df

    @staticmethod
    def _summary_labels(variable_units: Any, column_count: int, data_path: str) -> List[tuple]:
        """Decode Variable_Unit rows; refuse layouts not starting Flow/Stage HW/Stage TW."""
        rows = np.asarray(variable_units) if variable_units is not None else None
        if rows is None or rows.ndim != 2 or rows.shape[1] < 2 or rows.shape[0] != column_count:
            raise ValueError(
                f"Pump results at '{data_path}' need a Variable_Unit attribute with one "
                f"(label, unit) row per column; cannot identify the stored columns"
            )
        labels = [
            (HdfPump._decode_hdf_text(row[0]), HdfPump._decode_hdf_text(row[1]))
            for row in rows
        ]
        first = [label for label, _ in labels[:3]]
        if first != ['Flow', 'Stage HW', 'Stage TW']:
            raise ValueError(
                f"Pump results at '{data_path}' do not begin with Flow, Stage HW, "
                f"Stage TW (found {first}); layout not recognized"
            )
        return labels

    @staticmethod
    def _add_extremes(row: Dict[str, Any], name: str, values: np.ndarray,
                      time: np.ndarray, minimum: bool = True) -> None:
        """Add the stored max (and min) of ``values`` and the time of first occurrence."""
        values = np.asarray(values, dtype=np.float64)
        finite = np.isfinite(values)
        kinds = [('Max', np.argmax, -np.inf)]
        if minimum:
            kinds.append(('Min', np.argmin, np.inf))
        for label, pick, fill in kinds:
            if not finite.any():
                row[f'{label} {name}'] = np.nan
                row[f'{label} {name} Time'] = np.nan
                continue
            idx = int(pick(np.where(finite, values, fill)))
            row[f'{label} {name}'] = values[idx]
            row[f'{label} {name} Time'] = time[idx]

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pump_operation_timeseries(hdf_path: Path, pump_station: str) -> pd.DataFrame:
        """
        Extract detailed pump operation results data for a specific pump station.

        Time comes only from DSS Profile Output: stored timestamps, or its
        numeric Time in days when timestamps are absent (attrs['time_units']='days').
        Missing or malformed axes raise; Base Output and integer row indexes
        are never substituted. DSS timestamp text may have seconds or milliseconds.

        Args:
            hdf_path (Path): Path to the HEC-RAS HDF file.
            pump_station (str): Name or identifier of the pump station.

        Returns:
            pd.DataFrame: DataFrame containing pump operation data with columns:
                - Time: Stored simulation timestamps, or elapsed days if absent
                - Flow: Pump flow rate
                - Stage HW: Headwater stage
                - Stage TW: Tailwater stage
                - Pump Station: Station identifier
                - Pumps on: Number of active pumps

        Raises:
            KeyError: If required datasets are not found in the HDF file.
            ValueError: If the station is absent or its block-local time axis
                is malformed or has a different row count from the results.
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

            data = read_typed(hdf[data_path])

            time, time_units = HdfPump._pump_block_time(hdf, data_path, data.shape)

            variable_units = read_attr(hdf[data_path], 'Variable_Unit', None)
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
            if time_units:
                df.attrs['time_units'] = time_units

            return df

    @staticmethod
    def _pump_block_time(hdf: h5py.File, data_path: str, data_shape: tuple):
        """Read and validate only the owning block's stored time axis."""
        if len(data_shape) != 2:
            raise ValueError(f"Pump results at '{data_path}' must have time/variable axes")
        block_path = data_path.split('/Pumping Stations/', 1)[0]
        for name in ('Time Date Stamp (ms)', 'Time Date Stamp', 'Time'):
            path = f"{block_path}/{name}"
            if path not in hdf:
                continue
            dataset = hdf[path]
            if dataset.shape != (data_shape[0],):
                raise ValueError(
                    f"Pump time axis '{path}' has shape {dataset.shape}; "
                    f"expected ({data_shape[0]},) for '{data_path}'"
                )
            values = read_typed(dataset)
            if name == 'Time':
                units = HdfPump._decode_hdf_text(read_attr(dataset, 'Time', ''))
                if (values.dtype.kind != 'f' or units.lower() != 'days'
                        or not np.all(np.isfinite(values)) or np.any(np.diff(values) < 0)):
                    raise ValueError(f"Pump time axis '{path}' requires finite nondecreasing days")
                return values, 'days'
            times = []
            for value in values:
                text = HdfPump._decode_hdf_text(value)
                try:
                    # DSS may store second-resolution text even in the (ms) dataset.
                    if text.count(':') == 3:
                        parsed = HdfUtils.parse_ras_datetime_ms(text)
                    else:
                        parsed = HdfUtils.parse_ras_datetime(text)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid pump timestamp {text!r} at '{path}'") from exc
                times.append(parsed)
            if any(right < left for left, right in zip(times, times[1:])):
                raise ValueError(f"Pump timestamps at '{path}' must be nondecreasing")
            return times, None
        raise KeyError(
            f"Pump results at '{data_path}' require a stored timestamp or Time axis "
            f"in '{block_path}'; another output block cannot supply it"
        )

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
