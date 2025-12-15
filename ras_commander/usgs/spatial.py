"""
Spatial query functions for USGS gauge discovery within HEC-RAS project bounds.

This module provides functions to discover USGS stream gauges within or near
HEC-RAS project extents using the USGS Water Services API through the
dataretrieval package.

Functions:
    find_gauges_in_project():
        Query USGS gauges within HEC-RAS project bounds with buffering
    get_project_gauges_with_data():
        Find gauges with data availability for a specific time period

Example Usage:
    >>> from ras_commander import init_ras_project
    >>> from ras_commander.usgs import find_gauges_in_project
    >>>
    >>> # Initialize project and get geometry HDF
    >>> init_ras_project("C:/models/project", "6.5")
    >>> geom_hdf = "C:/models/project/project.g01.hdf"
    >>>
    >>> # Find all stream gauges within project bounds (50% buffer)
    >>> gauges = find_gauges_in_project(geom_hdf, buffer_percent=50.0)
    >>> print(f"Found {len(gauges)} gauges")
    >>> print(gauges[['site_no', 'station_nm', 'dec_lat_va', 'dec_long_va']])
    >>>
    >>> # Find gauges with flow data for specific period
    >>> gauges = get_project_gauges_with_data(
    ...     geom_hdf,
    ...     start_datetime='2024-08-01',
    ...     end_datetime='2024-08-15',
    ...     parameter='flow'
    ... )
    >>> print(f"Gauges with data: {len(gauges)}")
"""

from pathlib import Path
from typing import Union, Optional, List, Tuple, TYPE_CHECKING
import pandas as pd

from ..hdf import HdfProject
from ..Decorators import log_call
from ..LoggingConfig import get_logger

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)


# USGS parameter codes
PARAMETER_CODES = {
    'flow': '00060',      # Discharge (cfs)
    'stage': '00065',     # Gage height (ft)
    'velocity': '00055',  # Stream velocity (ft/s)
    'discharge': '00060'  # Alias for flow
}


class UsgsGaugeSpatial:
    """
    Static class for spatial queries of USGS gauge locations.

    Provides methods to discover USGS stream gauges within HEC-RAS project
    extents using the USGS Water Services API.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def find_gauges_in_project(
        hdf_path: Union[str, Path],
        buffer_percent: float = 50.0,
        site_type: str = 'ST',
        parameter_codes: Optional[Union[str, List[str]]] = None,
        active_only: bool = True,
        project_crs: Optional[str] = None
    ) -> 'gpd.GeoDataFrame':
        """
        Query USGS gauges within HEC-RAS project bounds.

        Uses the project's geographic extent (from all 1D/2D elements) to query
        the USGS Water Services API for monitoring locations. Results are returned
        as a GeoDataFrame with gauge locations and metadata.

        Parameters
        ----------
        hdf_path : Union[str, Path]
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        buffer_percent : float, default 50.0
            Buffer percentage to expand project bounds. Recommended values:
            - 50% captures gauges near project boundaries
            - 100% includes upstream contributing areas
            Default 50% balances coverage and query performance.
        site_type : str, default 'ST'
            USGS site type code. Common values:
            - 'ST' : Stream (most common for HEC-RAS validation)
            - 'LK' : Lake
            - 'ES' : Estuary
            - 'GW' : Groundwater
        parameter_codes : str or List[str], optional
            Filter gauges by available parameter(s). Options:
            - None : Return all gauges regardless of data type
            - 'flow' or '00060' : Discharge measurements
            - 'stage' or '00065' : Gage height
            - ['flow', 'stage'] : Multiple parameters
        active_only : bool, default True
            If True, only return currently active gauges. If False,
            include inactive/historical gauges.
        project_crs : str, optional
            Override CRS for projects without embedded projection. Use EPSG codes
            like "EPSG:26918" (UTM Zone 18N) or "EPSG:2271" (PA State Plane North).
            Required for Bald Eagle Creek and other example projects without CRS.

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame with gauge locations (WGS84) and metadata columns:
            - site_no : USGS site number (e.g., '01646500')
            - station_nm : Station name
            - dec_lat_va : Latitude (decimal degrees)
            - dec_long_va : Longitude (decimal degrees)
            - geometry : Point geometry in WGS84
            - Additional columns from USGS API (drainage area, etc.)

            Returns empty GeoDataFrame if no gauges found.

        Raises
        ------
        ImportError
            If dataretrieval or geopandas packages are not installed
        ValueError
            If HDF file does not contain valid project geometry
        FileNotFoundError
            If hdf_path does not exist

        Examples
        --------
        >>> # Basic usage - find all stream gauges in project
        >>> gauges = UsgsGaugeSpatial.find_gauges_in_project(
        ...     "BaldEagle.g01.hdf",
        ...     buffer_percent=50.0
        ... )
        >>> print(f"Found {len(gauges)} gauges")
        >>> print(gauges[['site_no', 'station_nm']])

        >>> # Find only gauges with flow data
        >>> flow_gauges = UsgsGaugeSpatial.find_gauges_in_project(
        ...     "project.g01.hdf",
        ...     parameter_codes='flow',
        ...     buffer_percent=100.0
        ... )

        >>> # Find gauges with both flow and stage
        >>> multi_gauges = UsgsGaugeSpatial.find_gauges_in_project(
        ...     "project.g01.hdf",
        ...     parameter_codes=['flow', 'stage']
        ... )

        >>> # Include historical gauges
        >>> all_gauges = UsgsGaugeSpatial.find_gauges_in_project(
        ...     "project.g01.hdf",
        ...     active_only=False
        ... )

        Notes
        -----
        - Requires `pip install dataretrieval` for USGS API access
        - Returns gauges in WGS84 (EPSG:4326) coordinate system
        - Query may take several seconds for large geographic extents
        - USGS API rate limits apply (typically generous for normal use)
        - Project bounds are calculated from all available model elements
          (2D areas, cross sections, river centerlines)

        See Also
        --------
        get_project_gauges_with_data : Filter by data availability
        HdfProject.get_project_bounds_latlon : Get project bounds
        """
        try:
            from dataretrieval import waterdata
            import geopandas as gpd
            from shapely.geometry import Point
        except ImportError as e:
            raise ImportError(
                f"Required package not found: {e}. "
                "Install with: pip install dataretrieval geopandas shapely"
            )

        hdf_path = Path(hdf_path)
        if not hdf_path.exists():
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")

        # Get project bounds in WGS84 (lat/lon)
        logger.info(f"Retrieving project bounds from: {hdf_path}")
        west, south, east, north = HdfProject.get_project_bounds_latlon(
            hdf_path,
            buffer_percent=buffer_percent,
            project_crs=project_crs
        )

        if west == 0.0 and south == 0.0 and east == 0.0 and north == 0.0:
            logger.warning("No valid project geometry found")
            return gpd.GeoDataFrame()

        logger.info(f"Querying USGS gauges in bounds: "
                   f"W={west:.6f}, S={south:.6f}, E={east:.6f}, N={north:.6f}")

        # Convert parameter codes if provided
        param_codes = None
        if parameter_codes is not None:
            if isinstance(parameter_codes, str):
                parameter_codes = [parameter_codes]
            # Convert parameter names to codes
            param_codes = []
            for param in parameter_codes:
                if param in PARAMETER_CODES:
                    param_codes.append(PARAMETER_CODES[param])
                else:
                    param_codes.append(param)  # Assume it's already a code
            param_codes = ','.join(param_codes)
            logger.debug(f"Parameter codes: {param_codes}")

        # Query USGS Water Services API
        try:
            kwargs = {
                'bbox': [west, south, east, north],  # List of floats, not string
            }

            # Add parameter code filter if specified
            if param_codes is not None:
                kwargs['parameterCd'] = param_codes

            # Note: site_type and active_only filtering happens on returned data
            # The API doesn't reliably filter by these parameters

            logger.debug(f"USGS query parameters: {kwargs}")

            # Query monitoring locations
            df, md = waterdata.get_monitoring_locations(**kwargs)

        except Exception as e:
            logger.error(f"USGS API query failed: {e}")
            return gpd.GeoDataFrame()

        # Check if results are empty
        if df is None or df.empty:
            logger.info("No gauges found in project bounds")
            return gpd.GeoDataFrame()

        logger.info(f"Found {len(df)} USGS gauges")
        logger.debug(f"API response columns: {list(df.columns)}")

        # Create geometry column - handle different API response formats
        try:
            # Try different column name conventions (API format changed over time)
            lon_col = None
            lat_col = None
            
            # Check for common longitude column names
            for col in ['dec_long_va', 'longitude', 'long', 'lng', 'x']:
                if col in df.columns:
                    lon_col = col
                    break
            
            # Check for common latitude column names
            for col in ['dec_lat_va', 'latitude', 'lat', 'y']:
                if col in df.columns:
                    lat_col = col
                    break
            
            # If still not found, check for geometry column from GeoJSON response
            if lon_col is None or lat_col is None:
                if 'geometry' in df.columns:
                    # Extract coordinates from geometry column
                    logger.debug("Extracting coordinates from geometry column")
                    df['_lon'] = df['geometry'].apply(lambda g: g.x if hasattr(g, 'x') else g['coordinates'][0] if isinstance(g, dict) else None)
                    df['_lat'] = df['geometry'].apply(lambda g: g.y if hasattr(g, 'y') else g['coordinates'][1] if isinstance(g, dict) else None)
                    lon_col = '_lon'
                    lat_col = '_lat'
            
            if lon_col is None or lat_col is None:
                logger.error(f"Could not find longitude/latitude columns. Available columns: {list(df.columns)}")
                return gpd.GeoDataFrame()
            
            logger.debug(f"Using columns: lon={lon_col}, lat={lat_col}")
            
            geometry = [Point(float(lon), float(lat))
                       for lon, lat in zip(df[lon_col], df[lat_col])]

            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(
                df,
                geometry=geometry,
                crs='EPSG:4326'
            )

            logger.debug(f"Created GeoDataFrame with {len(gdf)} gauges")
            logger.debug(f"Columns: {list(gdf.columns)}")
            
            # Normalize column names to expected format (handle API version differences)
            # Map new OGC API names to legacy names expected by downstream code
            column_mapping = {
                # Site identification (new OGC API format)
                'monitoring_location_number': 'site_no',
                'monitoring_location_id': 'site_no',
                'id': 'site_no',
                'monitoringLocationIdentifier': 'site_no',
                'identifier': 'site_no',
                'siteNumber': 'site_no',
                # Station name
                'monitoring_location_name': 'station_nm',
                'name': 'station_nm',
                'monitoringLocationName': 'station_nm', 
                'stationName': 'station_nm',
                'siteName': 'station_nm',
                # Site type (new API already uses site_type_code)
                'site_type': 'site_type_code',
                'monitoringLocationType': 'site_type_code',
                'siteType': 'site_type_code',
                'type': 'site_type_code',
                # Status
                'activityStatus': 'site_status',
                'status': 'site_status',
                # Drainage area
                'drainage_area': 'drain_area_va',
                'drainageArea': 'drain_area_va',
                'contributing_drainage_area': 'contrib_drain_area_va',
                'contributingDrainageArea': 'contrib_drain_area_va',
                # Coordinates (already handled above, but add for completeness)
                'latitude': 'dec_lat_va',
                'longitude': 'dec_long_va',
            }
            
            # Apply column mapping
            for old_name, new_name in column_mapping.items():
                if old_name in gdf.columns and new_name not in gdf.columns:
                    gdf[new_name] = gdf[old_name]
                    logger.debug(f"Mapped column '{old_name}' -> '{new_name}'")
            
            # Special handling for site_no - strip common prefixes
            if 'site_no' in gdf.columns:
                # Remove 'USGS-' prefix if present (new API format)
                gdf['site_no'] = gdf['site_no'].astype(str).str.replace('USGS-', '', regex=False)
                logger.debug(f"Cleaned site_no values, sample: {gdf['site_no'].iloc[0] if len(gdf) > 0 else 'N/A'}")
            
            # Log final columns for debugging
            logger.debug(f"Final GeoDataFrame columns: {list(gdf.columns)}")
            if 'site_no' not in gdf.columns:
                logger.warning(f"'site_no' column not found! Available columns: {list(gdf.columns)}")

            # Filter by site type if specified
            if site_type and 'site_type_code' in gdf.columns:
                initial_count = len(gdf)
                gdf = gdf[gdf['site_type_code'] == site_type].copy()
                filtered_count = initial_count - len(gdf)
                if filtered_count > 0:
                    logger.info(f"Filtered out {filtered_count} non-{site_type} sites ({len(gdf)} {site_type} sites remaining)")

            # Filter for active sites if requested
            if active_only and 'site_status' in gdf.columns:
                initial_count = len(gdf)
                gdf = gdf[gdf['site_status'] == 'Active'].copy()
                filtered_count = initial_count - len(gdf)
                if filtered_count > 0:
                    logger.info(f"Filtered out {filtered_count} inactive sites ({len(gdf)} active remaining)")

            return gdf

        except Exception as e:
            logger.error(f"Failed to create GeoDataFrame: {e}")
            logger.debug(f"DataFrame columns: {list(df.columns)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @log_call
    def get_project_gauges_with_data(
        hdf_path: Union[str, Path],
        start_datetime: str,
        end_datetime: str,
        parameter: str = 'flow',
        buffer_percent: float = 50.0,
        site_type: str = 'ST'
    ) -> 'gpd.GeoDataFrame':
        """
        Find USGS gauges with data availability for a specific time period.

        Queries gauges within project bounds and filters to only those with
        data available for the specified parameter and time period. This is
        useful for identifying gauges suitable for model validation or
        boundary condition generation.

        Parameters
        ----------
        hdf_path : Union[str, Path]
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        start_datetime : str
            Start date/time in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'
        end_datetime : str
            End date/time in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'
        parameter : str, default 'flow'
            Parameter type: 'flow', 'stage', 'velocity', or USGS code
        buffer_percent : float, default 50.0
            Buffer percentage to expand project bounds
        site_type : str, default 'ST'
            USGS site type code (e.g., 'ST' for stream)

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame with gauges that have data in the period.
            Includes column 'data_count' with number of available records.
            Returns empty GeoDataFrame if no gauges found or none have data.

        Examples
        --------
        >>> # Find gauges with flow data for Hurricane Harvey
        >>> gauges = UsgsGaugeSpatial.get_project_gauges_with_data(
        ...     "Houston.g01.hdf",
        ...     start_datetime='2017-08-25',
        ...     end_datetime='2017-09-05',
        ...     parameter='flow',
        ...     buffer_percent=100.0
        ... )
        >>> print(f"Gauges with data: {len(gauges)}")
        >>> print(gauges[['site_no', 'station_nm', 'data_count']])

        >>> # Find gauges with stage data for validation period
        >>> stage_gauges = UsgsGaugeSpatial.get_project_gauges_with_data(
        ...     "model.g01.hdf",
        ...     start_datetime='2024-01-01',
        ...     end_datetime='2024-12-31',
        ...     parameter='stage'
        ... )

        Notes
        -----
        - This function performs N+1 queries: one for gauge locations,
          then one per gauge to check data availability
        - May be slow for large numbers of gauges
        - Only returns gauges with at least one data point in the period
        - Does not retrieve the actual data, only checks availability

        See Also
        --------
        find_gauges_in_project : Find all gauges in project bounds
        """
        try:
            from dataretrieval import waterdata
            import geopandas as gpd
        except ImportError as e:
            raise ImportError(
                f"Required package not found: {e}. "
                "Install with: pip install dataretrieval geopandas"
            )

        # Convert parameter name to code
        param_code = PARAMETER_CODES.get(parameter, parameter)

        # Find all gauges in project
        logger.info(f"Searching for gauges with {parameter} data "
                   f"from {start_datetime} to {end_datetime}")

        gauges = UsgsGaugeSpatial.find_gauges_in_project(
            hdf_path,
            buffer_percent=buffer_percent,
            site_type=site_type,
            parameter_codes=param_code
        )

        if gauges.empty:
            logger.info("No gauges found in project bounds")
            return gpd.GeoDataFrame()

        logger.info(f"Checking data availability for {len(gauges)} gauges")

        # Check data availability for each gauge
        gauges_with_data = []
        data_counts = []

        for idx, row in gauges.iterrows():
            site_no = row['site_no']
            try:
                # Query data for this gauge
                df, md = waterdata.get_continuous(
                    sites=site_no,
                    parameterCd=param_code,
                    start=start_datetime,
                    end=end_datetime
                )

                # Check if data exists
                if df is not None and not df.empty:
                    gauges_with_data.append(row)
                    data_counts.append(len(df))
                    logger.debug(f"Gauge {site_no}: {len(df)} records")
                else:
                    logger.debug(f"Gauge {site_no}: No data")

            except Exception as e:
                logger.debug(f"Gauge {site_no}: Query failed - {e}")
                continue

        # Create result GeoDataFrame
        if not gauges_with_data:
            logger.info("No gauges with data found for the specified period")
            return gpd.GeoDataFrame()

        result = gpd.GeoDataFrame(gauges_with_data, crs=gauges.crs)
        result['data_count'] = data_counts

        logger.info(f"Found {len(result)} gauges with {parameter} data")

        return result


# Convenience functions for direct import
def find_gauges_in_project(
    hdf_path: Union[str, Path],
    buffer_percent: float = 50.0,
    site_type: str = 'ST',
    parameter_codes: Optional[Union[str, List[str]]] = None,
    active_only: bool = True,
    project_crs: Optional[str] = None
) -> 'gpd.GeoDataFrame':
    """
    Query USGS gauges within HEC-RAS project bounds.

    Convenience function that calls UsgsGaugeSpatial.find_gauges_in_project().
    See UsgsGaugeSpatial.find_gauges_in_project for full documentation.
    
    Parameters
    ----------
    project_crs : str, optional
        Override CRS for projects without embedded projection (e.g., "EPSG:26918").
    """
    return UsgsGaugeSpatial.find_gauges_in_project(
        hdf_path, buffer_percent, site_type, parameter_codes, active_only, project_crs
    )


def get_project_gauges_with_data(
    hdf_path: Union[str, Path],
    start_datetime: str,
    end_datetime: str,
    parameter: str = 'flow',
    buffer_percent: float = 50.0,
    site_type: str = 'ST'
) -> 'gpd.GeoDataFrame':
    """
    Find USGS gauges with data availability for a specific time period.

    Convenience function that calls UsgsGaugeSpatial.get_project_gauges_with_data().
    See UsgsGaugeSpatial.get_project_gauges_with_data for full documentation.
    """
    return UsgsGaugeSpatial.get_project_gauges_with_data(
        hdf_path, start_datetime, end_datetime, parameter, buffer_percent, site_type
    )
