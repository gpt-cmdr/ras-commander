"""
RasUsgsCore - USGS Data Retrieval for ras-commander

Summary:
    Provides static methods for retrieving USGS gauge data via the dataretrieval
    package. Supports flow and stage time series retrieval, gauge metadata extraction,
    and data availability checking.

Functions:
    retrieve_flow_data(site_id, start_datetime, end_datetime, data_type='iv'):
        Retrieve flow time series from USGS NWIS for a site.
    retrieve_stage_data(site_id, start_datetime, end_datetime, data_type='iv'):
        Retrieve stage (water level) time series from USGS NWIS for a site.
    get_gauge_metadata(site_id):
        Get comprehensive metadata for a USGS gauge (location, drainage area, etc.).
    check_data_availability(site_id, start_datetime, end_datetime, parameter='flow'):
        Check if data is available for a site and time period without downloading.

Parameter Codes:
    - Flow (discharge): '00060' (cubic feet per second)
    - Stage (gage height): '00065' (feet)

Data Types:
    - 'iv': Instantaneous values (15-min or hourly intervals)
    - 'dv': Daily values (daily mean)

Dependencies:
    Required external package:
        - dataretrieval: pip install dataretrieval

Lazy Loading:
    The dataretrieval package is only imported when USGS methods are called,
    ensuring minimal overhead for users who don't use this functionality.

Usage:
    from ras_commander.usgs import retrieve_flow_data, get_gauge_metadata

    # Get gauge metadata
    metadata = get_gauge_metadata("08074500")
    print(f"Station: {metadata['station_name']}")
    print(f"Drainage Area: {metadata['drainage_area_sqmi']} sq mi")

    # Retrieve flow data
    flow_df = retrieve_flow_data(
        site_id="08074500",
        start_datetime="2017-08-25",
        end_datetime="2017-09-02",
        data_type='iv'
    )
    print(flow_df.head())
"""

import sys
import os
from pathlib import Path
from typing import Optional, Union, Dict, Tuple, List
import logging

# Standard imports always needed
import pandas as pd
import numpy as np
from datetime import datetime

# Import decorator from parent package
from ..Decorators import log_call

logger = logging.getLogger(__name__)


class RasUsgsCore:
    """
    Static class for USGS data retrieval operations.

    Uses the dataretrieval package (lazy-loaded on first use) to access
    USGS National Water Information System (NWIS) web services.

    All methods are static and designed to be used without instantiation.

    Example:
        from ras_commander.usgs import RasUsgsCore

        # Retrieve flow data
        df = RasUsgsCore.retrieve_flow_data("08074500", "2017-08-25", "2017-09-02")
    """

    # Parameter codes for USGS NWIS
    PARAM_FLOW = '00060'  # Discharge, cubic feet per second
    PARAM_STAGE = '00065'  # Gage height, feet

    _dataretrieval_loaded = False
    _waterdata = None

    @staticmethod
    def _ensure_dataretrieval():
        """Ensure dataretrieval package is loaded (lazy loading)."""
        if RasUsgsCore._dataretrieval_loaded:
            return RasUsgsCore._waterdata

        try:
            from dataretrieval import nwis
            RasUsgsCore._waterdata = nwis
            RasUsgsCore._dataretrieval_loaded = True
            logger.info("dataretrieval package loaded successfully")
            return RasUsgsCore._waterdata
        except ImportError:
            raise ImportError(
                "dataretrieval is required for USGS data operations.\n"
                "Install with: pip install dataretrieval"
            )

    @staticmethod
    @log_call
    def retrieve_flow_data(
        site_id: str,
        start_datetime: Union[str, datetime],
        end_datetime: Union[str, datetime],
        data_type: str = 'iv'
    ) -> pd.DataFrame:
        """
        Retrieve flow (discharge) time series from USGS NWIS.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500" for Buffalo Bayou at Houston)
        start_datetime : str or datetime
            Start date/time in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        end_datetime : str or datetime
            End date/time in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        data_type : str, optional
            Data type to retrieve:
                - 'iv': Instantaneous values (15-min or hourly), default
                - 'dv': Daily values (daily mean)

        Returns
        -------
        pd.DataFrame
            DataFrame with 'datetime' index and 'value' column containing flow in cfs.
            Additional columns may include qualifiers and data quality codes.

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If invalid data_type specified or no data available

        Examples
        --------
        >>> # Get instantaneous flow data for Hurricane Harvey
        >>> flow_df = RasUsgsCore.retrieve_flow_data(
        ...     site_id="08074500",
        ...     start_datetime="2017-08-25",
        ...     end_datetime="2017-09-02",
        ...     data_type='iv'
        ... )
        >>> print(f"Peak flow: {flow_df['value'].max():.0f} cfs")

        >>> # Get daily mean flow
        >>> daily_flow = RasUsgsCore.retrieve_flow_data(
        ...     site_id="08074500",
        ...     start_datetime="2017-08-01",
        ...     end_datetime="2017-09-30",
        ...     data_type='dv'
        ... )

        Notes
        -----
        - Flow units are always cubic feet per second (cfs)
        - Instantaneous data typically has 15-minute or 1-hour intervals
        - Not all sites have instantaneous data; use check_data_availability() first
        - DateTime returned is in UTC; may need timezone conversion for local time
        """
        nwis = RasUsgsCore._ensure_dataretrieval()

        logger.info(f"Retrieving flow data for site {site_id}, {start_datetime} to {end_datetime}")

        # Convert datetime objects to strings if needed
        if isinstance(start_datetime, datetime):
            start_datetime = start_datetime.strftime("%Y-%m-%d")
        if isinstance(end_datetime, datetime):
            end_datetime = end_datetime.strftime("%Y-%m-%d")

        try:
            if data_type.lower() == 'iv':
                # Instantaneous values
                data_df, metadata = nwis.get_iv(
                    sites=site_id,
                    parameterCd=RasUsgsCore.PARAM_FLOW,
                    start=start_datetime,
                    end=end_datetime
                )
            elif data_type.lower() == 'dv':
                # Daily values
                data_df, metadata = nwis.get_dv(
                    sites=site_id,
                    parameterCd=RasUsgsCore.PARAM_FLOW,
                    start=start_datetime,
                    end=end_datetime
                )
            else:
                raise ValueError(
                    f"Invalid data_type '{data_type}'. Must be 'iv' (instantaneous) or 'dv' (daily)."
                )

            if data_df.empty:
                logger.warning(f"No flow data available for site {site_id} in specified period")
                return pd.DataFrame(columns=['datetime', 'value'])

            # Standardize column names
            # dataretrieval returns columns like '00060_Mean' or '00060'
            value_col = [col for col in data_df.columns if RasUsgsCore.PARAM_FLOW in col][0]

            # Create standardized output
            result_df = pd.DataFrame({
                'datetime': data_df.index,
                'value': data_df[value_col].values
            })

            # Store metadata as dataframe attributes
            result_df.attrs['site_id'] = site_id
            result_df.attrs['parameter'] = 'flow'
            result_df.attrs['parameter_code'] = RasUsgsCore.PARAM_FLOW
            result_df.attrs['units'] = 'cfs'
            result_df.attrs['data_type'] = data_type
            result_df.attrs['metadata'] = metadata

            logger.info(f"Retrieved {len(result_df)} flow records for site {site_id}")

            return result_df

        except Exception as e:
            logger.error(f"Error retrieving flow data for site {site_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def retrieve_stage_data(
        site_id: str,
        start_datetime: Union[str, datetime],
        end_datetime: Union[str, datetime],
        data_type: str = 'iv'
    ) -> pd.DataFrame:
        """
        Retrieve stage (gage height) time series from USGS NWIS.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        start_datetime : str or datetime
            Start date/time in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        end_datetime : str or datetime
            End date/time in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        data_type : str, optional
            Data type to retrieve:
                - 'iv': Instantaneous values (15-min or hourly), default
                - 'dv': Daily values (daily mean)

        Returns
        -------
        pd.DataFrame
            DataFrame with 'datetime' index and 'value' column containing stage in feet.
            Additional columns may include qualifiers and data quality codes.

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If invalid data_type specified or no data available

        Examples
        --------
        >>> # Get instantaneous stage data
        >>> stage_df = RasUsgsCore.retrieve_stage_data(
        ...     site_id="08074500",
        ...     start_datetime="2017-08-25",
        ...     end_datetime="2017-09-02",
        ...     data_type='iv'
        ... )
        >>> print(f"Peak stage: {stage_df['value'].max():.2f} ft")

        Notes
        -----
        - Stage units are always feet above gage datum
        - Stage is relative to an arbitrary datum at each gauge
        - Not all flow gauges have stage data; check availability first
        - DateTime returned is in UTC; may need timezone conversion
        """
        nwis = RasUsgsCore._ensure_dataretrieval()

        logger.info(f"Retrieving stage data for site {site_id}, {start_datetime} to {end_datetime}")

        # Convert datetime objects to strings if needed
        if isinstance(start_datetime, datetime):
            start_datetime = start_datetime.strftime("%Y-%m-%d")
        if isinstance(end_datetime, datetime):
            end_datetime = end_datetime.strftime("%Y-%m-%d")

        try:
            if data_type.lower() == 'iv':
                # Instantaneous values
                data_df, metadata = nwis.get_iv(
                    sites=site_id,
                    parameterCd=RasUsgsCore.PARAM_STAGE,
                    start=start_datetime,
                    end=end_datetime
                )
            elif data_type.lower() == 'dv':
                # Daily values
                data_df, metadata = nwis.get_dv(
                    sites=site_id,
                    parameterCd=RasUsgsCore.PARAM_STAGE,
                    start=start_datetime,
                    end=end_datetime
                )
            else:
                raise ValueError(
                    f"Invalid data_type '{data_type}'. Must be 'iv' (instantaneous) or 'dv' (daily)."
                )

            if data_df.empty:
                logger.warning(f"No stage data available for site {site_id} in specified period")
                return pd.DataFrame(columns=['datetime', 'value'])

            # Standardize column names
            value_col = [col for col in data_df.columns if RasUsgsCore.PARAM_STAGE in col][0]

            # Create standardized output
            result_df = pd.DataFrame({
                'datetime': data_df.index,
                'value': data_df[value_col].values
            })

            # Store metadata as dataframe attributes
            result_df.attrs['site_id'] = site_id
            result_df.attrs['parameter'] = 'stage'
            result_df.attrs['parameter_code'] = RasUsgsCore.PARAM_STAGE
            result_df.attrs['units'] = 'feet'
            result_df.attrs['data_type'] = data_type
            result_df.attrs['metadata'] = metadata

            logger.info(f"Retrieved {len(result_df)} stage records for site {site_id}")

            return result_df

        except Exception as e:
            logger.error(f"Error retrieving stage data for site {site_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def get_gauge_metadata(site_id: str) -> Dict[str, any]:
        """
        Get comprehensive metadata for a USGS gauge station.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")

        Returns
        -------
        dict
            Dictionary containing gauge metadata with keys:
                - site_id: USGS site number
                - station_name: Official station name
                - latitude: Latitude in decimal degrees (WGS84)
                - longitude: Longitude in decimal degrees (WGS84)
                - drainage_area_sqmi: Drainage area in square miles (if available)
                - gage_datum_ft: Gage datum elevation in feet (if available)
                - state: State code (e.g., "TX")
                - county: County name
                - huc_cd: Hydrologic Unit Code
                - available_parameters: List of available parameter codes

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If site_id is invalid or site not found

        Examples
        --------
        >>> metadata = RasUsgsCore.get_gauge_metadata("08074500")
        >>> print(f"Station: {metadata['station_name']}")
        >>> print(f"Location: ({metadata['latitude']}, {metadata['longitude']})")
        >>> print(f"Drainage Area: {metadata['drainage_area_sqmi']} sq mi")
        >>> print(f"Available Parameters: {metadata['available_parameters']}")

        Notes
        -----
        - Returns WGS84 coordinates suitable for use with HEC-RAS project matching
        - Drainage area is useful for comparing gauge representativeness
        - Not all fields may be available for all gauges
        """
        nwis = RasUsgsCore._ensure_dataretrieval()

        logger.info(f"Retrieving metadata for site {site_id}")

        try:
            # Get site information
            # Note: dataretrieval 1.1.0+ returns tuple (DataFrame, metadata_dict)
            result = nwis.get_info(sites=site_id)
            if isinstance(result, tuple):
                site_info, _ = result  # Unpack tuple for newer versions
            else:
                site_info = result  # Handle older versions

            if site_info is None or site_info.empty:
                raise ValueError(f"Site {site_id} not found or invalid")

            # Extract first row (should only be one site)
            site = site_info.iloc[0]

            # Build standardized metadata dictionary
            metadata = {
                'site_id': site_id,
                'station_name': site.get('station_nm', 'Unknown'),
                'latitude': float(site.get('dec_lat_va', 0.0)),
                'longitude': float(site.get('dec_long_va', 0.0)),
                'drainage_area_sqmi': float(site.get('drain_area_va', 0.0)) if pd.notna(site.get('drain_area_va')) else None,
                'gage_datum_ft': float(site.get('alt_va', 0.0)) if pd.notna(site.get('alt_va')) else None,
                'state': site.get('state_cd', ''),
                'county': site.get('county_nm', ''),
                'huc_cd': site.get('huc_cd', ''),
                'site_type': site.get('site_tp_cd', ''),
            }

            # Get available parameters by querying data availability
            try:
                # Query what data is available (without downloading full dataset)
                availability = nwis.what_sites(
                    sites=site_id,
                    service='iv'  # Check instantaneous value availability
                )
                if not availability.empty and 'parm_cd' in availability.columns:
                    metadata['available_parameters'] = list(availability['parm_cd'].unique())
                else:
                    metadata['available_parameters'] = []
            except:
                metadata['available_parameters'] = []

            logger.info(f"Retrieved metadata for {metadata['station_name']} (drainage area: {metadata['drainage_area_sqmi']} sq mi)")

            return metadata

        except Exception as e:
            logger.error(f"Error retrieving metadata for site {site_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def check_data_availability(
        site_id: str,
        start_datetime: Union[str, datetime],
        end_datetime: Union[str, datetime],
        parameter: str = 'flow'
    ) -> Dict[str, any]:
        """
        Check if data is available for a site and time period without downloading full dataset.

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "08074500")
        start_datetime : str or datetime
            Start date/time in format "YYYY-MM-DD"
        end_datetime : str or datetime
            End date/time in format "YYYY-MM-DD"
        parameter : str, optional
            Parameter to check: 'flow' or 'stage', default 'flow'

        Returns
        -------
        dict
            Dictionary with availability information:
                - available: bool, True if data exists in period
                - site_id: USGS site number
                - parameter: Parameter checked ('flow' or 'stage')
                - parameter_code: USGS parameter code
                - start_date: Start of available data (may differ from request)
                - end_date: End of available data (may differ from request)
                - record_count: Approximate number of records (if available)
                - message: Human-readable status message

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If invalid parameter specified

        Examples
        --------
        >>> availability = RasUsgsCore.check_data_availability(
        ...     site_id="08074500",
        ...     start_datetime="2017-08-25",
        ...     end_datetime="2017-09-02",
        ...     parameter='flow'
        ... )
        >>> if availability['available']:
        ...     print(f"Data available: {availability['message']}")
        >>> else:
        ...     print("No data available for this period")

        Notes
        -----
        - This method performs a lightweight query to check availability
        - Use this before calling retrieve_flow_data() or retrieve_stage_data()
        - Does not guarantee data quality, only presence
        """
        nwis = RasUsgsCore._ensure_dataretrieval()

        # Get parameter code
        if parameter.lower() == 'flow':
            param_code = RasUsgsCore.PARAM_FLOW
        elif parameter.lower() == 'stage':
            param_code = RasUsgsCore.PARAM_STAGE
        else:
            raise ValueError(f"Invalid parameter '{parameter}'. Must be 'flow' or 'stage'.")

        logger.info(f"Checking {parameter} data availability for site {site_id}")

        # Convert datetime objects to strings if needed
        if isinstance(start_datetime, datetime):
            start_datetime = start_datetime.strftime("%Y-%m-%d")
        if isinstance(end_datetime, datetime):
            end_datetime = end_datetime.strftime("%Y-%m-%d")

        try:
            # Try to get a small sample of data to verify availability
            # Get just first day to minimize data transfer
            test_df, metadata = nwis.get_iv(
                sites=site_id,
                parameterCd=param_code,
                start=start_datetime,
                end=start_datetime  # Just check first day
            )

            result = {
                'available': not test_df.empty,
                'site_id': site_id,
                'parameter': parameter,
                'parameter_code': param_code,
                'start_date': start_datetime,
                'end_date': end_datetime,
                'record_count': None,  # Can't determine without full download
            }

            if result['available']:
                result['message'] = f"{parameter.capitalize()} data available for site {site_id}"
                logger.info(result['message'])
            else:
                result['message'] = f"No {parameter} data available for site {site_id} in specified period"
                logger.warning(result['message'])

            return result

        except Exception as e:
            logger.error(f"Error checking availability for site {site_id}: {str(e)}")
            return {
                'available': False,
                'site_id': site_id,
                'parameter': parameter,
                'parameter_code': param_code,
                'start_date': start_datetime,
                'end_date': end_datetime,
                'record_count': None,
                'message': f"Error checking availability: {str(e)}"
            }
