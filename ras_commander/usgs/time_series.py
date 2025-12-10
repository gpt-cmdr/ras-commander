"""
Time series processing and alignment for USGS gauge data.

This module provides functions for resampling, aligning, and quality checking
time series data from USGS gauges for use in HEC-RAS model validation and
boundary condition generation.

Functions:
- resample_to_hecras_interval() - Resample USGS data to HEC-RAS time intervals
- align_timeseries() - Align modeled and observed time series
- check_data_gaps() - Detect gaps in time series data
- fill_data_gaps() - Fill small gaps using interpolation
"""

from pathlib import Path
from typing import Union, Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from ..LoggingConfig import get_logger
from ..Decorators import log_call


logger = get_logger(__name__)


class TimeSeriesProcessor:
    """
    Static class for time series processing operations on USGS gauge data.

    All methods are static and designed to be used without instantiation.

    Typical workflow:
        1. Resample USGS data to HEC-RAS interval
        2. Check for data gaps
        3. Fill small gaps if needed
        4. Align with model results for comparison
    """

    # Mapping of HEC-RAS interval strings to pandas frequency codes
    HECRAS_INTERVALS = {
        '1MIN': '1min',
        '5MIN': '5min',
        '10MIN': '10min',
        '15MIN': '15min',
        '30MIN': '30min',
        '1HOUR': '1h',
        '2HOUR': '2h',
        '3HOUR': '3h',
        '4HOUR': '4h',
        '6HOUR': '6h',
        '8HOUR': '8h',
        '12HOUR': '12h',
        '1DAY': '1D'
    }

    @staticmethod
    @log_call
    def resample_to_hecras_interval(
        df: pd.DataFrame,
        target_interval: str,
        value_column: str = 'value',
        time_column: str = 'time',
        method: str = 'linear'
    ) -> pd.DataFrame:
        """
        Resample USGS time series data to HEC-RAS computation interval.

        USGS data often comes at different intervals (15-minute, hourly, daily)
        than what HEC-RAS models use. This function resamples the data to match
        the HEC-RAS interval using interpolation.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing USGS time series data
        target_interval : str
            HEC-RAS interval string (e.g., '1HOUR', '15MIN', '1DAY')
            Supported intervals: '1MIN', '5MIN', '10MIN', '15MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'
        value_column : str, default 'value'
            Name of column containing values to resample
        time_column : str, default 'time'
            Name of column containing datetime values
        method : str, default 'linear'
            Interpolation method: 'linear', 'nearest', 'zero', 'slinear',
            'quadratic', 'cubic', 'polynomial'

        Returns
        -------
        pd.DataFrame
            Resampled DataFrame with columns [time_column, value_column]

        Raises
        ------
        ValueError
            If target_interval is not a valid HEC-RAS interval
        KeyError
            If specified columns don't exist in DataFrame

        Examples
        --------
        >>> # USGS data at 15-minute interval, resample to hourly
        >>> usgs_df = pd.DataFrame({
        ...     'time': pd.date_range('2023-01-01', periods=96, freq='15min'),
        ...     'value': np.random.uniform(100, 1000, 96)
        ... })
        >>> hourly_df = TimeSeriesProcessor.resample_to_hecras_interval(
        ...     usgs_df, '1HOUR'
        ... )
        >>> len(hourly_df)
        24

        >>> # USGS hourly data, resample to 6-hour interval
        >>> flow_df = pd.DataFrame({
        ...     'datetime': pd.date_range('2023-01-01', periods=168, freq='1h'),
        ...     'flow_cfs': np.random.uniform(500, 2000, 168)
        ... })
        >>> six_hour_df = TimeSeriesProcessor.resample_to_hecras_interval(
        ...     flow_df, '6HOUR', value_column='flow_cfs', time_column='datetime'
        ... )

        Notes
        -----
        - Timestamps are preserved as-is (no timezone conversion)
        - If resampling to a longer interval (e.g., 15min → 1hour), values are interpolated
        - If resampling to a shorter interval (e.g., daily → hourly), gaps are filled by interpolation
        - For more control over gap filling, use check_data_gaps() and fill_data_gaps() first
        """
        # Validate target interval
        if target_interval not in TimeSeriesProcessor.HECRAS_INTERVALS:
            valid_intervals = ', '.join(TimeSeriesProcessor.HECRAS_INTERVALS.keys())
            raise ValueError(
                f"Invalid target_interval: '{target_interval}'. "
                f"Must be one of: {valid_intervals}"
            )

        # Validate columns exist
        if time_column not in df.columns:
            raise KeyError(f"time_column '{time_column}' not found in DataFrame columns: {df.columns.tolist()}")
        if value_column not in df.columns:
            raise KeyError(f"value_column '{value_column}' not found in DataFrame columns: {df.columns.tolist()}")

        # Make a copy to avoid modifying original
        df_copy = df.copy()

        # Ensure time column is datetime
        if not pd.api.types.is_datetime64_any_dtype(df_copy[time_column]):
            df_copy[time_column] = pd.to_datetime(df_copy[time_column])
            logger.debug(f"Converted {time_column} to datetime")

        # Set time as index for resampling
        df_copy = df_copy.set_index(time_column)

        # Get pandas frequency code
        pandas_freq = TimeSeriesProcessor.HECRAS_INTERVALS[target_interval]

        # Resample using interpolation
        # First resample to create the time grid, then interpolate
        df_resampled = df_copy[[value_column]].resample(pandas_freq).asfreq()

        # Interpolate missing values
        df_resampled[value_column] = df_resampled[value_column].interpolate(method=method)

        # Reset index to make time a column again
        df_resampled = df_resampled.reset_index()

        logger.info(
            f"Resampled from {len(df_copy)} to {len(df_resampled)} points "
            f"at {target_interval} interval using {method} interpolation"
        )

        return df_resampled

    @staticmethod
    @log_call
    def align_timeseries(
        modeled_df: pd.DataFrame,
        observed_df: pd.DataFrame,
        time_column: str = 'datetime',
        value_column: str = 'value'
    ) -> pd.DataFrame:
        """
        Align modeled and observed time series to common time period.

        Aligns HEC-RAS model results with USGS observed data by:
        1. Finding the overlapping time period
        2. Interpolating observed data to match model timestamps
        3. Returning aligned DataFrame for metrics calculation

        Parameters
        ----------
        modeled_df : pd.DataFrame
            DataFrame with model results, must have time_column and value_column
        observed_df : pd.DataFrame
            DataFrame with USGS observed data, must have time_column and value_column
        time_column : str, default 'datetime'
            Name of column containing datetime values in both DataFrames
        value_column : str, default 'value'
            Name of column containing values in both DataFrames

        Returns
        -------
        pd.DataFrame
            Aligned DataFrame with columns: [time_column, 'modeled', 'observed']
            Only includes timestamps where both datasets have values

        Raises
        ------
        ValueError
            If no overlapping time period exists
        KeyError
            If specified columns don't exist in DataFrames

        Examples
        --------
        >>> # Model results at hourly interval
        >>> model_df = pd.DataFrame({
        ...     'datetime': pd.date_range('2023-01-01', periods=168, freq='1h'),
        ...     'value': np.random.uniform(500, 2000, 168)
        ... })
        >>>
        >>> # USGS data at 15-minute interval
        >>> usgs_df = pd.DataFrame({
        ...     'datetime': pd.date_range('2023-01-01 12:00', periods=240, freq='15min'),
        ...     'value': np.random.uniform(500, 2000, 240)
        ... })
        >>>
        >>> # Align for comparison
        >>> aligned = TimeSeriesProcessor.align_timeseries(model_df, usgs_df)
        >>> aligned.columns
        Index(['datetime', 'modeled', 'observed'], dtype='object')

        >>> # Calculate metrics on aligned data
        >>> from ras_commander import RasUtils
        >>> metrics = RasUtils.calculate_error_metrics(
        ...     aligned['observed'].values,
        ...     aligned['modeled'].values
        ... )

        Notes
        -----
        - Observed data is interpolated to match model timestamps
        - If observed data is at finer resolution than model, it's downsampled
        - If observed data is at coarser resolution, it's upsampled with interpolation
        - Timestamps outside the overlapping period are excluded
        """
        # Validate columns exist
        for df, name in [(modeled_df, 'modeled_df'), (observed_df, 'observed_df')]:
            if time_column not in df.columns:
                raise KeyError(
                    f"time_column '{time_column}' not found in {name} columns: {df.columns.tolist()}"
                )
            if value_column not in df.columns:
                raise KeyError(
                    f"value_column '{value_column}' not found in {name} columns: {df.columns.tolist()}"
                )

        # Make copies and ensure datetime type
        model_copy = modeled_df.copy()
        obs_copy = observed_df.copy()

        for df in [model_copy, obs_copy]:
            if not pd.api.types.is_datetime64_any_dtype(df[time_column]):
                df[time_column] = pd.to_datetime(df[time_column])

        # Find overlapping time period
        model_start = model_copy[time_column].min()
        model_end = model_copy[time_column].max()
        obs_start = obs_copy[time_column].min()
        obs_end = obs_copy[time_column].max()

        overlap_start = max(model_start, obs_start)
        overlap_end = min(model_end, obs_end)

        if overlap_start >= overlap_end:
            raise ValueError(
                f"No overlapping time period. "
                f"Model: {model_start} to {model_end}, "
                f"Observed: {obs_start} to {obs_end}"
            )

        # Filter to overlapping period
        model_overlap = model_copy[
            (model_copy[time_column] >= overlap_start) &
            (model_copy[time_column] <= overlap_end)
        ].copy()

        obs_overlap = obs_copy[
            (obs_copy[time_column] >= overlap_start) &
            (obs_copy[time_column] <= overlap_end)
        ].copy()

        # Set index for merging
        model_overlap = model_overlap.set_index(time_column)
        obs_overlap = obs_overlap.set_index(time_column)

        # Create result DataFrame with model timestamps
        result = pd.DataFrame(index=model_overlap.index)
        result['modeled'] = model_overlap[value_column]

        # Interpolate observed to model timestamps
        # Use reindex with method='nearest' then interpolate
        obs_reindexed = obs_overlap[value_column].reindex(
            result.index,
            method=None  # Don't use nearest, use interpolate instead
        )

        # Interpolate to fill NaN values
        obs_reindexed = obs_reindexed.interpolate(method='time')
        result['observed'] = obs_reindexed

        # Drop any remaining NaN values (edges of time period)
        result = result.dropna()

        # Reset index to make time a column
        result = result.reset_index()
        result = result.rename(columns={'index': time_column})

        logger.info(
            f"Aligned {len(result)} timestamps from "
            f"{overlap_start} to {overlap_end}"
        )

        return result

    @staticmethod
    @log_call
    def check_data_gaps(
        df: pd.DataFrame,
        expected_interval: str,
        time_column: str = 'time',
        max_gap_intervals: int = 2
    ) -> Dict[str, Any]:
        """
        Detect gaps in USGS time series data.

        Analyzes time series for missing data by comparing actual time steps
        to expected interval. Reports gap locations, sizes, and data coverage.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing time series data
        expected_interval : str
            Expected HEC-RAS interval string (e.g., '1HOUR', '15MIN')
        time_column : str, default 'time'
            Name of column containing datetime values
        max_gap_intervals : int, default 2
            Number of missing intervals to consider significant
            (gaps <= this are minor, gaps > this are major)

        Returns
        -------
        dict
            Dictionary containing gap analysis:
            - 'has_gaps' : bool - Whether any gaps exist
            - 'gap_count' : int - Number of gaps found
            - 'gap_locations' : list of tuples - [(start_time, end_time, n_missing), ...]
            - 'max_gap_size' : int - Maximum number of consecutive missing intervals
            - 'data_coverage' : float - Fraction of expected data points present (0-1)
            - 'minor_gaps' : int - Number of gaps <= max_gap_intervals
            - 'major_gaps' : int - Number of gaps > max_gap_intervals

        Raises
        ------
        ValueError
            If expected_interval is not valid
        KeyError
            If time_column doesn't exist in DataFrame

        Examples
        --------
        >>> # Perfect hourly data
        >>> df = pd.DataFrame({
        ...     'time': pd.date_range('2023-01-01', periods=24, freq='1h'),
        ...     'value': np.random.uniform(100, 1000, 24)
        ... })
        >>> gaps = TimeSeriesProcessor.check_data_gaps(df, '1HOUR')
        >>> gaps['has_gaps']
        False
        >>> gaps['data_coverage']
        1.0

        >>> # Data with gaps
        >>> times = pd.date_range('2023-01-01', periods=24, freq='1h')
        >>> times = times.delete([5, 6, 7, 15])  # Remove some hours
        >>> df = pd.DataFrame({
        ...     'time': times,
        ...     'value': np.random.uniform(100, 1000, 20)
        ... })
        >>> gaps = TimeSeriesProcessor.check_data_gaps(df, '1HOUR')
        >>> gaps['has_gaps']
        True
        >>> gaps['gap_count']
        2
        >>> gaps['max_gap_size']
        3

        Notes
        -----
        - Gap size is measured in number of missing intervals, not duration
        - Minor gaps (≤ max_gap_intervals) can often be safely interpolated
        - Major gaps may require different treatment (exclude or flag)
        - Data coverage of < 0.9 (90%) may indicate poor data quality
        """
        # Validate interval
        if expected_interval not in TimeSeriesProcessor.HECRAS_INTERVALS:
            valid_intervals = ', '.join(TimeSeriesProcessor.HECRAS_INTERVALS.keys())
            raise ValueError(
                f"Invalid expected_interval: '{expected_interval}'. "
                f"Must be one of: {valid_intervals}"
            )

        # Validate column
        if time_column not in df.columns:
            raise KeyError(
                f"time_column '{time_column}' not found in DataFrame columns: {df.columns.tolist()}"
            )

        # Make copy and ensure datetime
        df_copy = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_copy[time_column]):
            df_copy[time_column] = pd.to_datetime(df_copy[time_column])

        # Sort by time
        df_copy = df_copy.sort_values(time_column)

        # Get pandas frequency and timedelta
        pandas_freq = TimeSeriesProcessor.HECRAS_INTERVALS[expected_interval]

        # Calculate expected interval as timedelta
        # Parse the frequency string to get timedelta
        freq_to_timedelta = {
            '1min': timedelta(minutes=1),
            '5min': timedelta(minutes=5),
            '10min': timedelta(minutes=10),
            '15min': timedelta(minutes=15),
            '30min': timedelta(minutes=30),
            '1h': timedelta(hours=1),
            '2h': timedelta(hours=2),
            '3h': timedelta(hours=3),
            '4h': timedelta(hours=4),
            '6h': timedelta(hours=6),
            '8h': timedelta(hours=8),
            '12h': timedelta(hours=12),
            '1D': timedelta(days=1)
        }
        interval_td = freq_to_timedelta[pandas_freq]

        # Calculate time differences
        times = df_copy[time_column].values
        time_diffs = pd.Series(times[1:]) - pd.Series(times[:-1])

        # Find gaps (where diff > expected interval)
        gap_mask = time_diffs > interval_td
        gap_indices = np.where(gap_mask)[0]

        gap_locations = []
        minor_gaps = 0
        major_gaps = 0
        max_gap_size = 0

        for idx in gap_indices:
            start_time = times[idx]
            end_time = times[idx + 1]

            # Calculate number of missing intervals
            gap_duration = pd.Timedelta(end_time - start_time)
            n_missing = int(gap_duration / interval_td) - 1

            gap_locations.append((start_time, end_time, n_missing))

            if n_missing > max_gap_size:
                max_gap_size = n_missing

            if n_missing <= max_gap_intervals:
                minor_gaps += 1
            else:
                major_gaps += 1

        # Calculate data coverage
        start_time = times[0]
        end_time = times[-1]
        total_duration = pd.Timedelta(end_time - start_time)
        expected_points = int(total_duration / interval_td) + 1
        actual_points = len(times)
        data_coverage = actual_points / expected_points if expected_points > 0 else 0.0

        result = {
            'has_gaps': len(gap_locations) > 0,
            'gap_count': len(gap_locations),
            'gap_locations': gap_locations,
            'max_gap_size': max_gap_size,
            'data_coverage': data_coverage,
            'minor_gaps': minor_gaps,
            'major_gaps': major_gaps
        }

        if result['has_gaps']:
            logger.info(
                f"Found {result['gap_count']} gaps "
                f"({minor_gaps} minor, {major_gaps} major). "
                f"Data coverage: {data_coverage:.1%}"
            )
        else:
            logger.info(f"No gaps detected. Data coverage: {data_coverage:.1%}")

        return result

    @staticmethod
    @log_call
    def fill_data_gaps(
        df: pd.DataFrame,
        method: str = 'linear',
        max_gap_intervals: int = 6,
        time_column: str = 'time',
        value_column: str = 'value'
    ) -> pd.DataFrame:
        """
        Fill small gaps in USGS time series data using interpolation.

        Fills missing data points in time series using interpolation methods.
        Large gaps (> max_gap_intervals) are left unfilled and should be
        handled separately (excluded or flagged).

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing time series data with gaps
        method : str, default 'linear'
            Interpolation method: 'linear', 'time', 'nearest', 'zero',
            'slinear', 'quadratic', 'cubic', 'polynomial'
        max_gap_intervals : int, default 6
            Maximum number of consecutive intervals to fill
            Gaps larger than this are left unfilled
        time_column : str, default 'time'
            Name of column containing datetime values
        value_column : str, default 'value'
            Name of column containing values to interpolate

        Returns
        -------
        pd.DataFrame
            DataFrame with small gaps filled, large gaps still missing
            Includes additional column 'filled' (bool) indicating filled values

        Raises
        ------
        KeyError
            If specified columns don't exist in DataFrame

        Examples
        --------
        >>> # Create data with gaps
        >>> times = pd.date_range('2023-01-01', periods=24, freq='1h')
        >>> times = times.delete([5, 6, 15])  # Remove 2 hours, then 1 hour
        >>> df = pd.DataFrame({
        ...     'time': times,
        ...     'value': [100, 110, 120, 130, 140, 160, 170, 180, 190, 200,
        ...               210, 220, 230, 250, 260, 270, 280, 290, 300, 310, 320]
        ... })
        >>>
        >>> # Fill gaps up to 6 intervals
        >>> filled_df = TimeSeriesProcessor.fill_data_gaps(df, max_gap_intervals=6)
        >>> filled_df['filled'].sum()
        3
        >>>
        >>> # Check which values were filled
        >>> filled_df[filled_df['filled']]

        >>> # Fill using time-aware interpolation
        >>> filled_df = TimeSeriesProcessor.fill_data_gaps(
        ...     df, method='time', max_gap_intervals=3
        ... )

        Notes
        -----
        - 'linear' interpolation: Simple linear between points
        - 'time' interpolation: Time-aware linear (accounts for irregular spacing)
        - 'cubic' interpolation: Smooth cubic spline (requires scipy)
        - Filled values are marked with filled=True column
        - Large gaps (> max_gap_intervals) remain as NaN
        - Use check_data_gaps() first to assess gap sizes

        Warnings
        --------
        - Interpolation assumes smooth changes between points
        - For flashy hydrographs, large gaps may not interpolate well
        - Consider excluding periods with large gaps from validation
        """
        # Validate columns
        if time_column not in df.columns:
            raise KeyError(
                f"time_column '{time_column}' not found in DataFrame columns: {df.columns.tolist()}"
            )
        if value_column not in df.columns:
            raise KeyError(
                f"value_column '{value_column}' not found in DataFrame columns: {df.columns.tolist()}"
            )

        # Make copy and ensure datetime
        df_copy = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_copy[time_column]):
            df_copy[time_column] = pd.to_datetime(df_copy[time_column])

        # Sort by time
        df_copy = df_copy.sort_values(time_column)

        # Create full time range at the inferred frequency
        # Infer frequency from the most common time difference
        time_diffs = df_copy[time_column].diff()
        most_common_diff = time_diffs.mode()[0]

        # Create complete time range
        full_time_range = pd.date_range(
            start=df_copy[time_column].min(),
            end=df_copy[time_column].max(),
            freq=most_common_diff
        )

        # Create DataFrame with full time range
        df_full = pd.DataFrame({time_column: full_time_range})

        # Merge with original data
        df_merged = df_full.merge(df_copy, on=time_column, how='left')

        # Mark which values are original vs filled
        df_merged['filled'] = df_merged[value_column].isna()

        # Identify gap sizes
        is_missing = df_merged[value_column].isna()
        gap_groups = (is_missing != is_missing.shift()).cumsum()
        gap_sizes = is_missing.groupby(gap_groups).transform('sum')

        # Only fill gaps <= max_gap_intervals
        fillable = is_missing & (gap_sizes <= max_gap_intervals)

        # Create a temporary series for interpolation
        values_to_interp = df_merged[value_column].copy()

        # Temporarily fill all NaN for interpolation
        if method == 'time':
            # Time-aware interpolation
            values_interpolated = df_merged.set_index(time_column)[value_column].interpolate(
                method='time'
            )
        else:
            values_interpolated = values_to_interp.interpolate(method=method)

        # Only keep interpolated values for fillable gaps
        df_merged.loc[fillable, value_column] = values_interpolated[fillable]

        # Update filled flag (only where we actually filled)
        df_merged['filled'] = df_merged['filled'] & fillable

        # Drop rows where gaps were too large (still NaN)
        df_result = df_merged.dropna(subset=[value_column])

        n_filled = df_result['filled'].sum()
        n_remaining_gaps = len(df_full) - len(df_result)

        logger.info(
            f"Filled {n_filled} gaps using {method} interpolation. "
            f"{n_remaining_gaps} large gaps remain unfilled."
        )

        return df_result
