"""
RasUsgsRealTime - Real-Time USGS Data Integration for ras-commander

Summary:
    Provides static methods for accessing near-real-time USGS gauge data with
    caching, auto-refresh, and change detection capabilities. Enables operational
    flood forecasting workflows by providing the most current gauge readings.

Functions:
    get_latest_value(site_id, parameter='flow'):
        Get the most recent gauge reading (last available value).
    get_recent_data(site_id, parameter='flow', hours=24):
        Get recent time series data (last N hours).
    refresh_data(site_id, parameter='flow', cache_df=None):
        Update cached data with only new records since last update.
    monitor_gauge(site_id, parameter='flow', interval_minutes=15, callback=None, duration_hours=None):
        Continuously monitor gauge with periodic refresh and callback notifications.
    detect_threshold_crossing(data_df, threshold, direction='rising'):
        Detect when gauge readings cross a specified threshold.
    detect_rapid_change(data_df, rate_threshold, window_minutes=60):
        Detect rapid changes in gauge readings (surge/recession).

Real-Time Capabilities:
    - Latest value retrieval (most recent reading)
    - Incremental data refresh (only new records)
    - Automated monitoring with callbacks
    - Threshold crossing alerts
    - Rate-of-change detection

Use Cases:
    - Operational flood forecasting
    - Real-time model boundary conditions
    - Gauge network monitoring
    - Early warning systems
    - Automated model triggering

Dependencies:
    Required external package:
        - dataretrieval: pip install dataretrieval

Lazy Loading:
    The dataretrieval package is only imported when real-time methods are called,
    ensuring minimal overhead for users who don't use this functionality.

Usage:
    from ras_commander.usgs import get_latest_value, monitor_gauge

    # Get most recent flow reading
    latest = get_latest_value("08074500", parameter='flow')
    print(f"Current flow: {latest['value']:.0f} cfs at {latest['datetime']}")

    # Get last 24 hours of data
    recent_df = get_recent_data("08074500", parameter='flow', hours=24)

    # Monitor gauge with callback
    def alert_callback(site_id, latest_value, change_info):
        if change_info['threshold_crossed']:
            print(f"ALERT: Flow exceeded {change_info['threshold']} cfs!")

    monitor_gauge("08074500", interval_minutes=15, callback=alert_callback, duration_hours=6)
"""

import sys
import os
from pathlib import Path
from typing import Optional, Union, Dict, Tuple, List, Callable
import logging
from datetime import datetime, timedelta, timezone
import time

# Standard imports always needed
import pandas as pd
import numpy as np

# Import decorator from parent package
from ..Decorators import log_call

logger = logging.getLogger(__name__)


class RasUsgsRealTime:
    """
    Static class for real-time USGS data operations.

    Provides methods for accessing near-real-time gauge data with caching,
    refresh logic, and monitoring capabilities for operational forecasting.

    All methods are static and designed to be used without instantiation.

    Example:
        from ras_commander.usgs import RasUsgsRealTime

        # Get latest reading
        latest = RasUsgsRealTime.get_latest_value("08074500")
        print(f"Flow: {latest['value']} cfs at {latest['datetime']}")
    """

    # Parameter codes (same as RasUsgsCore)
    PARAM_FLOW = '00060'  # Discharge, cubic feet per second
    PARAM_STAGE = '00065'  # Gage height, feet

    _dataretrieval_loaded = False
    _nwis = None

    @staticmethod
    def _ensure_dataretrieval():
        """Ensure dataretrieval package is loaded (lazy loading)."""
        if RasUsgsRealTime._dataretrieval_loaded:
            return RasUsgsRealTime._nwis

        try:
            from dataretrieval import nwis
            RasUsgsRealTime._nwis = nwis
            RasUsgsRealTime._dataretrieval_loaded = True
            logger.info("dataretrieval package loaded for real-time operations")
            return RasUsgsRealTime._nwis
        except ImportError:
            raise ImportError(
                "dataretrieval is required for real-time USGS data operations.\n"
                "Install with: pip install dataretrieval"
            )

    @staticmethod
    @log_call
    def get_latest_value(
        site_id: str,
        parameter: str = 'flow'
    ) -> Dict[str, any]:
        """
        Get the most recent gauge reading for a site.

        This method retrieves the latest available value from USGS real-time
        data services, typically updated every 15 minutes to 1 hour.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        parameter : str, optional
            Parameter to retrieve: 'flow' or 'stage', default 'flow'

        Returns
        -------
        dict
            Dictionary containing:
                - site_id: USGS site number
                - parameter: Parameter name ('flow' or 'stage')
                - value: Most recent reading (float)
                - units: Units ('cfs' or 'feet')
                - datetime: Timestamp of reading (datetime object)
                - age_minutes: Age of reading in minutes (float)
                - qualifiers: Data quality codes (list)

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If no data available or invalid parameter

        Examples
        --------
        >>> latest = RasUsgsRealTime.get_latest_value("08074500", parameter='flow')
        >>> print(f"Flow: {latest['value']:.0f} cfs")
        >>> print(f"Time: {latest['datetime']}")
        >>> print(f"Age: {latest['age_minutes']:.1f} minutes old")

        >>> # Check if data is fresh (< 2 hours old)
        >>> if latest['age_minutes'] < 120:
        ...     print("Data is current")

        Notes
        -----
        - Real-time data is typically updated hourly but can be delayed
        - Always check age_minutes to verify data freshness
        - Data may be provisional and subject to revision
        """
        nwis = RasUsgsRealTime._ensure_dataretrieval()

        # Get parameter code
        if parameter.lower() == 'flow':
            param_code = RasUsgsRealTime.PARAM_FLOW
            units = 'cfs'
        elif parameter.lower() == 'stage':
            param_code = RasUsgsRealTime.PARAM_STAGE
            units = 'feet'
        else:
            raise ValueError(f"Invalid parameter '{parameter}'. Must be 'flow' or 'stage'.")

        logger.info(f"Retrieving latest {parameter} value for site {site_id}")

        try:
            # Get last 7 days of data to ensure we get recent values
            # (real-time endpoint sometimes doesn't respond well to very short periods)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            data_df, metadata = nwis.get_iv(
                sites=site_id,
                parameterCd=param_code,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d")
            )

            if data_df.empty:
                raise ValueError(f"No real-time {parameter} data available for site {site_id}")

            # Find the value column
            value_col = [col for col in data_df.columns if param_code in col and '_cd' not in col][0]

            # Get qualifier columns if they exist
            qual_cols = [col for col in data_df.columns if '_cd' in col]

            # Get most recent record
            latest_datetime = data_df.index[-1]
            latest_value = data_df[value_col].iloc[-1]

            # Get qualifiers if available
            qualifiers = []
            if qual_cols:
                for col in qual_cols:
                    qual_val = data_df[col].iloc[-1]
                    if pd.notna(qual_val):
                        qualifiers.append(qual_val)

            # Calculate age of data (use timezone-aware datetime for comparison)
            age_minutes = (datetime.now(timezone.utc) - latest_datetime).total_seconds() / 60

            result = {
                'site_id': site_id,
                'parameter': parameter,
                'value': float(latest_value),
                'units': units,
                'datetime': latest_datetime,
                'age_minutes': age_minutes,
                'qualifiers': qualifiers,
                'provisional': 'P' in qualifiers or 'p' in qualifiers,  # Provisional flag
            }

            logger.info(
                f"Latest {parameter} for {site_id}: {latest_value:.2f} {units} "
                f"at {latest_datetime} ({age_minutes:.1f} min old)"
            )

            return result

        except Exception as e:
            logger.error(f"Error retrieving latest {parameter} for site {site_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def get_recent_data(
        site_id: str,
        parameter: str = 'flow',
        hours: int = 24
    ) -> pd.DataFrame:
        """
        Get recent time series data for a gauge (last N hours).

        Retrieves instantaneous values for the specified lookback period,
        useful for understanding recent trends and current conditions.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        parameter : str, optional
            Parameter to retrieve: 'flow' or 'stage', default 'flow'
        hours : int, optional
            Number of hours to look back, default 24

        Returns
        -------
        pd.DataFrame
            DataFrame with 'datetime' index and 'value' column.
            Includes metadata in attrs dict.

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If no data available

        Examples
        --------
        >>> # Get last 24 hours
        >>> recent_df = RasUsgsRealTime.get_recent_data("08074500", hours=24)
        >>> print(f"Records: {len(recent_df)}")
        >>> print(f"Peak flow: {recent_df['value'].max():.0f} cfs")

        >>> # Get last 6 hours for rapid assessment
        >>> recent_6h = RasUsgsRealTime.get_recent_data("08074500", hours=6)

        >>> # Check trend
        >>> if recent_df['value'].iloc[-1] > recent_df['value'].iloc[0]:
        ...     print("Flow is rising")

        Notes
        -----
        - Returns instantaneous values (typically 15-min intervals)
        - Data is near-real-time, updated approximately hourly
        - Useful for operational decision-making
        """
        nwis = RasUsgsRealTime._ensure_dataretrieval()

        # Get parameter code
        if parameter.lower() == 'flow':
            param_code = RasUsgsRealTime.PARAM_FLOW
            units = 'cfs'
        elif parameter.lower() == 'stage':
            param_code = RasUsgsRealTime.PARAM_STAGE
            units = 'feet'
        else:
            raise ValueError(f"Invalid parameter '{parameter}'. Must be 'flow' or 'stage'.")

        logger.info(f"Retrieving last {hours} hours of {parameter} data for site {site_id}")

        try:
            # Calculate time window
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)

            # Retrieve data
            # Note: Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS) for USGS API compatibility
            data_df, metadata = nwis.get_iv(
                sites=site_id,
                parameterCd=param_code,
                start=start_date.strftime("%Y-%m-%dT%H:%M:%S"),
                end=end_date.strftime("%Y-%m-%dT%H:%M:%S")
            )

            if data_df.empty:
                logger.warning(f"No recent {parameter} data available for site {site_id}")
                return pd.DataFrame(columns=['datetime', 'value'])

            # Standardize column names
            value_col = [col for col in data_df.columns if param_code in col and '_cd' not in col][0]

            # Create standardized output
            result_df = pd.DataFrame({
                'datetime': data_df.index,
                'value': data_df[value_col].values
            })

            # Store metadata as dataframe attributes
            result_df.attrs['site_id'] = site_id
            result_df.attrs['parameter'] = parameter
            result_df.attrs['parameter_code'] = param_code
            result_df.attrs['units'] = units
            result_df.attrs['hours'] = hours
            result_df.attrs['retrieved_at'] = datetime.now()
            result_df.attrs['metadata'] = metadata

            logger.info(f"Retrieved {len(result_df)} recent {parameter} records for site {site_id}")

            return result_df

        except Exception as e:
            logger.error(f"Error retrieving recent {parameter} data for site {site_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def refresh_data(
        site_id: str,
        parameter: str = 'flow',
        cached_df: Optional[pd.DataFrame] = None,
        max_age_hours: int = 168  # 7 days default
    ) -> pd.DataFrame:
        """
        Refresh cached data with only new records since last update.

        This method performs incremental updates, retrieving only data newer than
        the last timestamp in the cached DataFrame. Useful for maintaining up-to-date
        local caches without re-downloading entire datasets.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        parameter : str, optional
            Parameter to retrieve: 'flow' or 'stage', default 'flow'
        cached_df : pd.DataFrame, optional
            Existing cached data to update. If None, retrieves last max_age_hours.
        max_age_hours : int, optional
            Maximum age of data to keep in hours, default 168 (7 days)

        Returns
        -------
        pd.DataFrame
            Updated DataFrame with new records appended.
            Duplicates are removed, keeping most recent values.

        Raises
        ------
        ImportError
            If dataretrieval package is not installed

        Examples
        --------
        >>> # Initial download
        >>> cache_df = RasUsgsRealTime.get_recent_data("08074500", hours=48)
        >>> print(f"Initial records: {len(cache_df)}")

        >>> # Later, refresh with only new data
        >>> import time
        >>> time.sleep(3600)  # Wait 1 hour
        >>> cache_df = RasUsgsRealTime.refresh_data("08074500", cached_df=cache_df)
        >>> print(f"Updated records: {len(cache_df)}")

        >>> # Automatic cache management (keep last 7 days)
        >>> cache_df = RasUsgsRealTime.refresh_data("08074500", cached_df=cache_df, max_age_hours=168)

        Notes
        -----
        - Only downloads data newer than cached_df's latest timestamp
        - Automatically removes duplicates
        - Trims old data based on max_age_hours
        - Returns empty DataFrame if no cached data and API fails
        """
        nwis = RasUsgsRealTime._ensure_dataretrieval()

        # Get parameter code
        if parameter.lower() == 'flow':
            param_code = RasUsgsRealTime.PARAM_FLOW
            units = 'cfs'
        elif parameter.lower() == 'stage':
            param_code = RasUsgsRealTime.PARAM_STAGE
            units = 'feet'
        else:
            raise ValueError(f"Invalid parameter '{parameter}'. Must be 'flow' or 'stage'.")

        try:
            # Determine start time for refresh
            if cached_df is not None and not cached_df.empty:
                # Get last timestamp from cache
                last_cached = cached_df['datetime'].max()
                start_date = last_cached
                logger.info(f"Refreshing {parameter} data since {last_cached}")
            else:
                # No cache, get last max_age_hours
                start_date = datetime.now() - timedelta(hours=max_age_hours)
                logger.info(f"No cache, retrieving last {max_age_hours} hours")

            end_date = datetime.now()

            # Retrieve new data
            # Note: Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS) for USGS API compatibility
            new_data_df, metadata = nwis.get_iv(
                sites=site_id,
                parameterCd=param_code,
                start=start_date.strftime("%Y-%m-%dT%H:%M:%S"),
                end=end_date.strftime("%Y-%m-%dT%H:%M:%S")
            )

            # Standardize new data
            if not new_data_df.empty:
                value_col = [col for col in new_data_df.columns if param_code in col and '_cd' not in col][0]
                new_df = pd.DataFrame({
                    'datetime': new_data_df.index,
                    'value': new_data_df[value_col].values
                })
            else:
                new_df = pd.DataFrame(columns=['datetime', 'value'])
                logger.info("No new data available")

            # Combine with cache if it exists
            if cached_df is not None and not cached_df.empty:
                combined_df = pd.concat([cached_df, new_df], ignore_index=True)
            else:
                combined_df = new_df

            # Remove duplicates (keep last)
            if not combined_df.empty:
                combined_df = combined_df.drop_duplicates(subset=['datetime'], keep='last')
                combined_df = combined_df.sort_values('datetime').reset_index(drop=True)

                # Trim old data based on max_age_hours
                cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
                combined_df = combined_df[combined_df['datetime'] >= cutoff_time].reset_index(drop=True)

                # Update metadata
                combined_df.attrs['site_id'] = site_id
                combined_df.attrs['parameter'] = parameter
                combined_df.attrs['parameter_code'] = param_code
                combined_df.attrs['units'] = units
                combined_df.attrs['last_refresh'] = datetime.now()
                combined_df.attrs['max_age_hours'] = max_age_hours

                new_count = len(new_df) if not new_df.empty else 0
                logger.info(
                    f"Refresh complete: {new_count} new records, "
                    f"{len(combined_df)} total records in cache"
                )
            else:
                combined_df = pd.DataFrame(columns=['datetime', 'value'])

            return combined_df

        except Exception as e:
            logger.error(f"Error refreshing {parameter} data for site {site_id}: {str(e)}")
            # Return existing cache if refresh fails
            if cached_df is not None:
                logger.warning("Returning existing cache due to refresh error")
                return cached_df
            else:
                return pd.DataFrame(columns=['datetime', 'value'])

    @staticmethod
    def detect_threshold_crossing(
        data_df: pd.DataFrame,
        threshold: float,
        direction: str = 'rising'
    ) -> Dict[str, any]:
        """
        Detect when gauge readings cross a specified threshold.

        Identifies threshold crossings and provides details about the event,
        useful for flood warning systems and automated alerts.

        Parameters
        ----------
        data_df : pd.DataFrame
            Time series data with 'datetime' and 'value' columns
        threshold : float
            Threshold value to detect crossings
        direction : str, optional
            Direction to detect: 'rising', 'falling', or 'both', default 'rising'

        Returns
        -------
        dict
            Dictionary containing:
                - crossed: bool, True if threshold was crossed
                - direction: str, Direction of last crossing
                - crossing_time: datetime, When threshold was crossed (or None)
                - crossing_value: float, Value at crossing (or None)
                - current_value: float, Most recent value
                - above_threshold: bool, True if currently above threshold

        Examples
        --------
        >>> recent_df = RasUsgsRealTime.get_recent_data("08074500", hours=24)
        >>> result = RasUsgsRealTime.detect_threshold_crossing(recent_df, threshold=5000, direction='rising')
        >>> if result['crossed']:
        ...     print(f"Threshold crossed at {result['crossing_time']}")

        Notes
        -----
        - Detects crossings between consecutive data points
        - Use 'rising' for flood thresholds, 'falling' for recession
        """
        if data_df.empty or len(data_df) < 2:
            return {
                'crossed': False,
                'direction': None,
                'crossing_time': None,
                'crossing_value': None,
                'current_value': None,
                'above_threshold': False
            }

        # Sort by datetime
        data_df = data_df.sort_values('datetime').reset_index(drop=True)

        # Get current value
        current_value = data_df['value'].iloc[-1]
        above_threshold = current_value > threshold

        # Detect crossings
        crossings = []
        for i in range(1, len(data_df)):
            prev_val = data_df['value'].iloc[i-1]
            curr_val = data_df['value'].iloc[i]

            # Rising crossing
            if prev_val <= threshold < curr_val:
                crossings.append({
                    'direction': 'rising',
                    'time': data_df['datetime'].iloc[i],
                    'value': curr_val,
                    'index': i
                })

            # Falling crossing
            elif prev_val > threshold >= curr_val:
                crossings.append({
                    'direction': 'falling',
                    'time': data_df['datetime'].iloc[i],
                    'value': curr_val,
                    'index': i
                })

        # Filter by direction
        if direction.lower() == 'rising':
            crossings = [c for c in crossings if c['direction'] == 'rising']
        elif direction.lower() == 'falling':
            crossings = [c for c in crossings if c['direction'] == 'falling']
        # 'both' keeps all crossings

        # Get most recent crossing
        if crossings:
            latest_crossing = crossings[-1]
            return {
                'crossed': True,
                'direction': latest_crossing['direction'],
                'crossing_time': latest_crossing['time'],
                'crossing_value': latest_crossing['value'],
                'current_value': current_value,
                'above_threshold': above_threshold,
                'crossing_count': len(crossings)
            }
        else:
            return {
                'crossed': False,
                'direction': None,
                'crossing_time': None,
                'crossing_value': None,
                'current_value': current_value,
                'above_threshold': above_threshold,
                'crossing_count': 0
            }

    @staticmethod
    def detect_rapid_change(
        data_df: pd.DataFrame,
        rate_threshold: float,
        window_minutes: int = 60
    ) -> Dict[str, any]:
        """
        Detect rapid changes in gauge readings (surge or recession).

        Calculates rate of change over a moving window and identifies periods
        where the rate exceeds a threshold. Useful for flash flood detection.

        Parameters
        ----------
        data_df : pd.DataFrame
            Time series data with 'datetime' and 'value' columns
        rate_threshold : float
            Rate of change threshold (units per hour)
        window_minutes : int, optional
            Time window for rate calculation in minutes, default 60

        Returns
        -------
        dict
            Dictionary containing:
                - rapid_change_detected: bool
                - max_rate: float, Maximum rate of change (units/hour)
                - max_rate_time: datetime, When max rate occurred
                - current_rate: float, Most recent rate of change
                - direction: str, 'rising' or 'falling'

        Examples
        --------
        >>> recent_df = RasUsgsRealTime.get_recent_data("08074500", hours=24)
        >>> # Detect if flow is rising faster than 1000 cfs/hour
        >>> result = RasUsgsRealTime.detect_rapid_change(recent_df, rate_threshold=1000, window_minutes=60)
        >>> if result['rapid_change_detected']:
        ...     print(f"Flash flood warning: {result['max_rate']:.0f} cfs/hour")

        Notes
        -----
        - Rate is calculated as (value_change / time_delta) * 60 minutes/hour
        - Positive rates indicate rising, negative indicate falling
        - Use shorter window_minutes for faster detection
        """
        if data_df.empty or len(data_df) < 2:
            return {
                'rapid_change_detected': False,
                'max_rate': 0.0,
                'max_rate_time': None,
                'current_rate': 0.0,
                'direction': None
            }

        # Sort by datetime
        data_df = data_df.sort_values('datetime').reset_index(drop=True)

        # Calculate rates for each point
        rates = []
        for i in range(1, len(data_df)):
            time_delta = (data_df['datetime'].iloc[i] - data_df['datetime'].iloc[i-1]).total_seconds() / 60  # minutes
            value_delta = data_df['value'].iloc[i] - data_df['value'].iloc[i-1]

            # Limit to specified window
            if time_delta <= window_minutes and time_delta > 0:
                # Rate in units per hour
                rate = (value_delta / time_delta) * 60
                rates.append({
                    'time': data_df['datetime'].iloc[i],
                    'rate': rate,
                    'index': i
                })

        if not rates:
            return {
                'rapid_change_detected': False,
                'max_rate': 0.0,
                'max_rate_time': None,
                'current_rate': 0.0,
                'direction': None
            }

        # Find maximum rate by absolute value
        max_rate_entry = max(rates, key=lambda x: abs(x['rate']))
        current_rate = rates[-1]['rate']

        # Detect if any rate exceeds threshold
        rapid_change = any(abs(r['rate']) > abs(rate_threshold) for r in rates)

        # Determine direction
        if max_rate_entry['rate'] > 0:
            direction = 'rising'
        elif max_rate_entry['rate'] < 0:
            direction = 'falling'
        else:
            direction = 'steady'

        return {
            'rapid_change_detected': rapid_change,
            'max_rate': max_rate_entry['rate'],
            'max_rate_time': max_rate_entry['time'],
            'current_rate': current_rate,
            'direction': direction,
            'rate_threshold': rate_threshold,
            'window_minutes': window_minutes
        }

    @staticmethod
    @log_call
    def monitor_gauge(
        site_id: str,
        parameter: str = 'flow',
        interval_minutes: int = 15,
        callback: Optional[Callable] = None,
        duration_hours: Optional[float] = None,
        threshold: Optional[float] = None,
        rate_threshold: Optional[float] = None
    ) -> pd.DataFrame:
        """
        Continuously monitor a gauge with periodic refresh and callback notifications.

        Polls USGS real-time data at specified intervals and invokes callback function
        when new data is available. Optionally stops after specified duration.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        parameter : str, optional
            Parameter to monitor: 'flow' or 'stage', default 'flow'
        interval_minutes : int, optional
            Refresh interval in minutes, default 15
        callback : Callable, optional
            Function to call when new data arrives.
            Signature: callback(site_id, latest_value, change_info, data_df)
        duration_hours : float, optional
            Duration to monitor in hours. If None, runs indefinitely (Ctrl+C to stop)
        threshold : float, optional
            Value threshold for crossing detection
        rate_threshold : float, optional
            Rate threshold for rapid change detection (units/hour)

        Returns
        -------
        pd.DataFrame
            Complete time series data collected during monitoring session

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        KeyboardInterrupt
            If user stops monitoring with Ctrl+C

        Examples
        --------
        >>> # Simple monitoring with console output
        >>> def my_callback(site_id, latest, change_info, data_df):
        ...     print(f"{latest['datetime']}: {latest['value']:.0f} {latest['units']}")
        ...     if change_info.get('threshold_crossed'):
        ...         print(f"ALERT: Threshold crossed!")
        >>>
        >>> data = RasUsgsRealTime.monitor_gauge(
        ...     site_id="08074500",
        ...     interval_minutes=15,
        ...     callback=my_callback,
        ...     duration_hours=2,
        ...     threshold=5000
        ... )

        >>> # Monitor until Ctrl+C
        >>> data = RasUsgsRealTime.monitor_gauge("08074500", interval_minutes=30)

        Notes
        -----
        - Callback receives 4 arguments: site_id, latest_value, change_info, data_df
        - change_info dict contains threshold and rate change detection results
        - Press Ctrl+C to stop infinite monitoring
        - Returns accumulated data from entire monitoring session
        """
        logger.info(
            f"Starting gauge monitoring for {site_id} ({parameter}), "
            f"interval={interval_minutes} min, duration={duration_hours} hours"
        )

        # Initialize cache
        cache_df = None
        start_time = datetime.now()

        try:
            iteration = 0
            while True:
                iteration += 1

                # Check if duration exceeded
                if duration_hours is not None:
                    elapsed_hours = (datetime.now() - start_time).total_seconds() / 3600
                    if elapsed_hours >= duration_hours:
                        logger.info(f"Monitoring duration ({duration_hours} hours) reached, stopping")
                        break

                logger.debug(f"Monitoring iteration {iteration} at {datetime.now()}")

                try:
                    # Refresh data
                    cache_df = RasUsgsRealTime.refresh_data(
                        site_id=site_id,
                        parameter=parameter,
                        cached_df=cache_df,
                        max_age_hours=24  # Keep last 24 hours
                    )

                    if cache_df.empty:
                        logger.warning(f"No data retrieved for {site_id}, will retry")
                        time.sleep(interval_minutes * 60)
                        continue

                    # Get latest value
                    latest_value = {
                        'site_id': site_id,
                        'parameter': parameter,
                        'value': cache_df['value'].iloc[-1],
                        'datetime': cache_df['datetime'].iloc[-1],
                        'units': cache_df.attrs.get('units', 'unknown')
                    }

                    # Build change_info dict
                    change_info = {}

                    # Threshold detection if specified
                    if threshold is not None:
                        threshold_result = RasUsgsRealTime.detect_threshold_crossing(
                            cache_df,
                            threshold=threshold,
                            direction='both'
                        )
                        change_info['threshold_crossed'] = threshold_result['crossed']
                        change_info['threshold_info'] = threshold_result

                    # Rate detection if specified
                    if rate_threshold is not None:
                        rate_result = RasUsgsRealTime.detect_rapid_change(
                            cache_df,
                            rate_threshold=rate_threshold,
                            window_minutes=60
                        )
                        change_info['rapid_change_detected'] = rate_result['rapid_change_detected']
                        change_info['rate_info'] = rate_result

                    # Invoke callback if provided
                    if callback is not None:
                        try:
                            callback(site_id, latest_value, change_info, cache_df)
                        except Exception as e:
                            logger.error(f"Error in callback function: {str(e)}")

                except Exception as e:
                    logger.error(f"Error during monitoring iteration: {str(e)}")

                # Wait for next interval
                logger.debug(f"Sleeping for {interval_minutes} minutes")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Monitoring stopped due to error: {str(e)}")
            raise
        finally:
            logger.info(
                f"Monitoring session ended. Collected {len(cache_df) if cache_df is not None else 0} records"
            )

        return cache_df if cache_df is not None else pd.DataFrame(columns=['datetime', 'value'])
