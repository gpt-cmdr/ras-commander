"""
PrecipAorc - AORC (Analysis of Record for Calibration) data access from AWS.

Provides access to NOAA's Analysis of Record for Calibration dataset
stored in Zarr format on AWS S3 for use in HEC-RAS rain-on-grid models.

The AORC dataset provides:
- Hourly precipitation data at ~800m resolution
- Coverage: CONUS (1979-present), Alaska (1981-present)
- Format: Cloud-optimized Zarr on AWS S3

List of Functions:
-----------------
download()
    Download AORC precipitation data for specified bounds and time range
check_availability()
    Check if AORC data is available for a region and time period
get_info()
    Get metadata about the AORC dataset
get_storm_catalog()
    Analyze AORC data and generate catalog of storm events for HEC-RAS plans
create_storm_plans()
    Create HEC-RAS plan and unsteady files for each storm in a catalog

Example Usage:
    >>> from ras_commander.precip import PrecipAorc
    >>>
    >>> # Download precipitation for a bounding box
    >>> output = PrecipAorc.download(
    ...     bounds=(-77.71, 41.01, -77.25, 41.22),  # west, south, east, north
    ...     start_time="2018-09-01",
    ...     end_time="2018-09-03",
    ...     output_path="precipitation.nc"
    ... )
    >>> print(f"Downloaded to: {output}")
"""

from pathlib import Path
from typing import Tuple, Optional, Union, List
from datetime import datetime
import logging

from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def _check_precip_dependencies():
    """Check that precipitation dependencies are installed."""
    missing = []
    try:
        import xarray
    except ImportError:
        missing.append("xarray")
    try:
        import zarr
    except ImportError:
        missing.append("zarr")
    try:
        import s3fs
    except ImportError:
        missing.append("s3fs")
    try:
        import netCDF4
    except ImportError:
        missing.append("netCDF4")

    if missing:
        raise ImportError(
            f"Missing precipitation dependencies: {', '.join(missing)}. "
            "Install with: pip install ras-commander[precip] "
            "or: pip install xarray zarr s3fs netCDF4"
        )


class PrecipAorc:
    """
    AORC (Analysis of Record for Calibration) precipitation data access.

    The AORC dataset provides hourly precipitation data at ~800m resolution
    from 1979-present for CONUS and 1981-present for Alaska.

    Data is accessed from AWS S3 in cloud-optimized Zarr format.

    All methods are static and designed for direct use without instantiation.
    """

    # AWS S3 bucket configuration
    BUCKET = "noaa-nws-aorc-v1-1-1km"
    REGION = "us-east-1"

    # AORC variable names
    PRECIP_VAR = "APCP_surface"

    # CONUS bounding box (approximate)
    CONUS_BOUNDS = (-125.0, 25.0, -67.0, 53.0)  # west, south, east, north

    @staticmethod
    def download(
        bounds: Tuple[float, float, float, float],
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        output_path: Union[str, Path],
        variable: str = "APCP_surface",
        target_crs: Optional[str] = "EPSG:5070",
        resolution: Optional[float] = 2000.0
    ) -> Path:
        """
        Download AORC precipitation data for specified bounds and time range.

        Accesses AORC data from AWS S3 Zarr store, subsets spatially and temporally,
        reprojects to HEC-RAS compatible CRS, and exports to NetCDF format.

        Parameters
        ----------
        bounds : Tuple[float, float, float, float]
            Bounding box in WGS84 as (west, south, east, north) in decimal degrees.
            Use HdfProject.get_project_bounds_latlon() to get these from a HEC-RAS model.
        start_time : str or datetime
            Start of time window. String format: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        end_time : str or datetime
            End of time window. Same format as start_time.
        output_path : str or Path
            Output NetCDF file path. Will be created if it doesn't exist.
        variable : str, default "APCP_surface"
            AORC variable name. Default is hourly precipitation (kg/m²).
        target_crs : str, optional, default "EPSG:5070"
            Target coordinate reference system for output. HEC-RAS requires SHG
            (EPSG:5070 - Albers Equal Area Conic) for gridded precipitation import.
            Set to None to keep original WGS84 coordinates.
        resolution : float, optional, default 2000.0
            Grid cell resolution in target CRS units (meters for EPSG:5070).
            Standard HEC SHG resolution is 2000m. Only used if target_crs is set.

        Returns
        -------
        Path
            Path to the output NetCDF file.

        Raises
        ------
        ImportError
            If required dependencies (xarray, zarr, s3fs, rioxarray) are not installed.
        ValueError
            If bounds are outside CONUS coverage or time range is invalid.

        Examples
        --------
        >>> from ras_commander.precip import PrecipAorc
        >>> from ras_commander import HdfProject
        >>>
        >>> # Get project bounds
        >>> bounds = HdfProject.get_project_bounds_latlon("model.g01.hdf")
        >>>
        >>> # Download AORC precipitation (default: reprojected to SHG)
        >>> output = PrecipAorc.download(
        ...     bounds=bounds,
        ...     start_time="2018-09-01",
        ...     end_time="2018-09-03",
        ...     output_path="Precipitation/aorc_sep2018.nc"
        ... )
        >>>
        >>> # Download without reprojection (keep WGS84)
        >>> output = PrecipAorc.download(
        ...     bounds=bounds,
        ...     start_time="2018-09-01",
        ...     end_time="2018-09-03",
        ...     output_path="Precipitation/aorc_wgs84.nc",
        ...     target_crs=None
        ... )

        Notes
        -----
        - Data is downloaded from AWS S3 (no authentication required)
        - Download time depends on spatial extent and time range
        - Large downloads may take several minutes
        - Default output is reprojected to SHG (EPSG:5070) for HEC-RAS compatibility
        - SHG (Standard Hydrologic Grid) is required for HEC-RAS GDAL Raster import
        """
        _check_precip_dependencies()

        import xarray as xr
        import s3fs
        import pandas as pd
        import numpy as np

        output_path = Path(output_path)

        # Parse time inputs
        if isinstance(start_time, str):
            start_dt = pd.to_datetime(start_time)
        else:
            start_dt = pd.Timestamp(start_time)

        if isinstance(end_time, str):
            end_dt = pd.to_datetime(end_time)
        else:
            end_dt = pd.Timestamp(end_time)

        # Extract bounds
        west, south, east, north = bounds

        # Validate bounds
        if west >= east or south >= north:
            raise ValueError(f"Invalid bounds: west must < east and south must < north. Got: {bounds}")

        # Check if within CONUS
        conus_west, conus_south, conus_east, conus_north = PrecipAorc.CONUS_BOUNDS
        if west < conus_west or east > conus_east or south < conus_south or north > conus_north:
            logger.warning(f"Bounds {bounds} may extend outside CONUS coverage {PrecipAorc.CONUS_BOUNDS}")

        logger.info(f"Downloading AORC data:")
        logger.info(f"  Bounds: W={west:.4f}, S={south:.4f}, E={east:.4f}, N={north:.4f}")
        logger.info(f"  Time range: {start_dt} to {end_dt}")
        logger.info(f"  Variable: {variable}")

        # Connect to S3 (anonymous access)
        logger.info("Connecting to AWS S3...")
        s3 = s3fs.S3FileSystem(anon=True)

        # Build Zarr store paths for each year in range
        years = range(start_dt.year, end_dt.year + 1)
        datasets = []

        for year in years:
            store_path = f"s3://{PrecipAorc.BUCKET}/{year}.zarr"
            logger.info(f"  Loading year {year} from {store_path}")

            try:
                store = s3fs.S3Map(root=store_path, s3=s3)
                ds = xr.open_zarr(store)

                # AORC uses latitude/longitude naming
                # Subset spatially - note latitude is typically ordered north to south
                # so we slice from north to south
                lat_dim = 'latitude' if 'latitude' in ds.dims else 'lat'
                lon_dim = 'longitude' if 'longitude' in ds.dims else 'lon'

                # Get the actual dimension names from the variable
                if variable in ds:
                    var_dims = ds[variable].dims
                    lat_candidates = [d for d in var_dims if 'lat' in d.lower()]
                    lon_candidates = [d for d in var_dims if 'lon' in d.lower()]
                    if lat_candidates:
                        lat_dim = lat_candidates[0]
                    if lon_candidates:
                        lon_dim = lon_candidates[0]

                # Subset the variable
                ds_var = ds[variable]

                # Check coordinate ordering for latitude
                lat_coords = ds_var[lat_dim].values
                if lat_coords[0] > lat_coords[-1]:
                    # Latitude is descending (north to south)
                    ds_subset = ds_var.sel(
                        **{lat_dim: slice(north, south)},
                        **{lon_dim: slice(west, east)}
                    )
                else:
                    # Latitude is ascending (south to north)
                    ds_subset = ds_var.sel(
                        **{lat_dim: slice(south, north)},
                        **{lon_dim: slice(west, east)}
                    )

                # Subset temporally - use date-only strings for proper inclusive slicing
                year_start = max(start_dt, pd.Timestamp(f"{year}-01-01"))
                year_end = min(end_dt, pd.Timestamp(f"{year}-12-31 23:59:59"))
                # Use date format YYYY-MM-DD for proper inclusive time slicing
                start_str = year_start.strftime('%Y-%m-%d')
                end_str = year_end.strftime('%Y-%m-%d')
                ds_subset = ds_subset.sel(time=slice(start_str, end_str))

                if ds_subset.size > 0:
                    # Load data from S3 now (force lazy evaluation)
                    ds_subset = ds_subset.load()
                    datasets.append(ds_subset)
                    logger.info(f"    Loaded {ds_subset.sizes}")
                else:
                    logger.warning(f"    No data found for year {year}")

            except Exception as e:
                logger.error(f"Error loading year {year}: {e}")
                raise

        if not datasets:
            raise ValueError("No data found for the specified bounds and time range")

        # Combine all years
        logger.info("Combining datasets...")
        if len(datasets) == 1:
            combined = datasets[0]
        else:
            combined = xr.concat(datasets, dim='time')

        # Sort by time
        combined = combined.sortby('time')

        # Data already loaded per-year, no need for additional compute

        # Add metadata for HEC-RAS
        combined.attrs['title'] = 'AORC Precipitation Data'
        combined.attrs['source'] = f'NOAA NWS AORC v1.1 from s3://{PrecipAorc.BUCKET}'
        combined.attrs['history'] = f'Downloaded by ras-commander on {datetime.now().isoformat()}'
        combined.attrs['units'] = 'kg/m^2'  # AORC precipitation units
        combined.attrs['long_name'] = 'Hourly Total Precipitation'

        # Reproject to target CRS if specified (required for HEC-RAS GDAL import)
        if target_crs is not None:
            try:
                import rioxarray
            except ImportError:
                raise ImportError(
                    "rioxarray is required for CRS reprojection. "
                    "Install with: pip install rioxarray"
                )

            logger.info(f"Reprojecting to {target_crs} at {resolution}m resolution...")

            # Set source CRS and spatial dimensions
            combined = combined.rio.write_crs('EPSG:4326')
            combined = combined.rio.set_spatial_dims(x_dim='longitude', y_dim='latitude')

            # Reproject to target CRS
            combined = combined.rio.reproject(target_crs, resolution=resolution)

            logger.info(f"Reprojected grid shape: {combined.shape}")

        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to NetCDF
        logger.info(f"Writing to NetCDF: {output_path}")
        combined.to_netcdf(output_path)

        file_size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Download complete: {output_path} ({file_size_mb:.1f} MB)")

        return output_path

    @staticmethod
    def check_availability(
        bounds: Tuple[float, float, float, float],
        start_time: Union[str, datetime],
        end_time: Union[str, datetime]
    ) -> dict:
        """
        Check if AORC data is available for the specified region and time.

        Parameters
        ----------
        bounds : Tuple[float, float, float, float]
            Bounding box as (west, south, east, north)
        start_time : str or datetime
            Start of time window
        end_time : str or datetime
            End of time window

        Returns
        -------
        dict
            Dictionary with availability information:
            - available: bool
            - years: list of available years
            - message: str with details
        """
        import pandas as pd

        if isinstance(start_time, str):
            start_dt = pd.to_datetime(start_time)
        else:
            start_dt = pd.Timestamp(start_time)

        if isinstance(end_time, str):
            end_dt = pd.to_datetime(end_time)
        else:
            end_dt = pd.Timestamp(end_time)

        west, south, east, north = bounds

        # Check bounds
        conus_west, conus_south, conus_east, conus_north = PrecipAorc.CONUS_BOUNDS
        in_conus = (west >= conus_west and east <= conus_east and
                   south >= conus_south and north <= conus_north)

        # AORC CONUS data starts in 1979
        years = list(range(start_dt.year, end_dt.year + 1))
        available_years = [y for y in years if y >= 1979]

        result = {
            'available': in_conus and len(available_years) > 0,
            'in_conus': in_conus,
            'years': available_years,
            'bounds': bounds,
            'time_range': (str(start_dt), str(end_dt)),
        }

        if result['available']:
            result['message'] = f"AORC data available for years {available_years}"
        elif not in_conus:
            result['message'] = f"Bounds {bounds} are outside CONUS coverage"
        else:
            result['message'] = f"Years {years} are before AORC coverage (1979+)"

        return result

    @staticmethod
    def get_info() -> dict:
        """
        Get metadata about the AORC dataset.

        Returns
        -------
        dict
            Dataset information including:
            - name: Dataset name
            - source: AWS S3 bucket path
            - coverage: Spatial and temporal coverage
            - resolution: Spatial and temporal resolution
            - variables: Available variables
        """
        return {
            'name': 'Analysis of Record for Calibration (AORC)',
            'version': '1.1',
            'source': f's3://{PrecipAorc.BUCKET}/',
            'coverage': {
                'spatial': 'Continental US (CONUS) and Alaska',
                'temporal': 'CONUS: 1979-present, Alaska: 1981-present',
                'bounds': PrecipAorc.CONUS_BOUNDS,
            },
            'resolution': {
                'spatial': '30 arc-seconds (~800 meters)',
                'temporal': 'Hourly',
            },
            'variables': {
                'APCP_surface': 'Hourly total precipitation (kg/m²)',
                'TMP_2maboveground': 'Air temperature at 2m (K)',
                'SPFH_2maboveground': 'Specific humidity at 2m (g/g)',
                'DLWRF_surface': 'Downward longwave radiation (W/m²)',
                'DSWRF_surface': 'Downward shortwave radiation (W/m²)',
                'PRES_surface': 'Surface air pressure (Pa)',
                'UGRD_10maboveground': 'West-east wind at 10m (m/s)',
                'VGRD_10maboveground': 'South-north wind at 10m (m/s)',
            },
            'format': 'Zarr (cloud-optimized)',
            'access': 'Anonymous (no authentication required)',
        }

    @staticmethod
    def get_storm_catalog(
        bounds: Tuple[float, float, float, float],
        year: int,
        inter_event_hours: float = 8.0,
        min_depth_inches: float = 0.5,
        min_wet_hours: int = 1,
        buffer_hours: int = 48,
        percentile_threshold: Optional[float] = None
    ) -> 'pd.DataFrame':
        """
        Analyze AORC precipitation data and generate a catalog of storm events.

        Identifies discrete precipitation events using inter-event time analysis,
        ranks them by total depth, and returns timing information suitable for
        setting up HEC-RAS simulation plans.

        Parameters
        ----------
        bounds : Tuple[float, float, float, float]
            Bounding box in WGS84 as (west, south, east, north) in decimal degrees.
            Use HdfProject.get_project_bounds_latlon() to get from HEC-RAS model.
        year : int
            Year to analyze (1979+).
        inter_event_hours : float, default 8.0
            Minimum hours of no precipitation between storm events.
            USGS standard is 6-8 hours for CONUS. Default: 8.0
        min_depth_inches : float, default 0.5
            Minimum total precipitation depth (inches) to include event.
            Events below this threshold are filtered out. Default: 0.5
        min_wet_hours : int, default 1
            Minimum hours with measurable precipitation during event.
            Default: 1
        buffer_hours : int, default 48
            Hours to add before and after event for simulation warm-up.
            This provides spin-up time for HEC-RAS hydraulic models. Default: 48
        percentile_threshold : float, optional
            If specified (0-100), only return storms above this percentile
            by total depth. E.g., 95 returns only top 5% storms. Default: None

        Returns
        -------
        pd.DataFrame
            Storm catalog with columns:
            - storm_id: Sequential storm identifier (1-based)
            - start_time: Event start (first hour with precipitation)
            - end_time: Event end (last hour with precipitation)
            - sim_start: Recommended simulation start (start - buffer)
            - sim_end: Recommended simulation end (end + buffer)
            - total_depth_in: Total event precipitation (inches, spatial mean)
            - peak_intensity_in_hr: Maximum hourly rate (inches/hour)
            - duration_hours: Event duration (hours)
            - wet_hours: Hours with measurable precipitation
            - rank: Rank by total depth (1 = largest)

        Examples
        --------
        >>> from ras_commander.precip import PrecipAorc
        >>> from ras_commander import HdfProject
        >>>
        >>> # Get project bounds
        >>> bounds = HdfProject.get_project_bounds_latlon("model.g01.hdf")
        >>>
        >>> # Get all significant storms from 2020
        >>> storms = PrecipAorc.get_storm_catalog(bounds, 2020)
        >>> print(storms[['storm_id', 'sim_start', 'sim_end', 'total_depth_in']])
        >>>
        >>> # Get only top 5% storms
        >>> major_storms = PrecipAorc.get_storm_catalog(
        ...     bounds, 2020, percentile_threshold=95
        ... )
        >>>
        >>> # Use storm for HEC-RAS plan setup
        >>> storm = storms.iloc[0]  # Largest storm
        >>> PrecipAorc.download(
        ...     bounds=bounds,
        ...     start_time=storm['sim_start'],
        ...     end_time=storm['sim_end'],
        ...     output_path="Precipitation/storm_001.nc"
        ... )

        Notes
        -----
        - Uses spatial mean precipitation over the bounding box
        - AORC precipitation units are kg/m² which equals mm depth
        - Conversion: 1 inch = 25.4 mm
        - Inter-event period of 8 hours is USGS standard for storm separation
        - Buffer of 48 hours allows hydraulic model spin-up and recession
        """
        _check_precip_dependencies()

        import xarray as xr
        import s3fs
        import pandas as pd
        import numpy as np

        logger.info(f"Generating storm catalog for {year}")
        logger.info(f"  Bounds: W={bounds[0]:.4f}, S={bounds[1]:.4f}, E={bounds[2]:.4f}, N={bounds[3]:.4f}")
        logger.info(f"  Parameters: inter_event={inter_event_hours}h, min_depth={min_depth_inches}in, buffer={buffer_hours}h")

        west, south, east, north = bounds

        # Connect to S3
        logger.info("Connecting to AWS S3...")
        s3 = s3fs.S3FileSystem(anon=True)

        # Load year's data
        store_path = f"s3://{PrecipAorc.BUCKET}/{year}.zarr"
        logger.info(f"Loading {store_path}...")

        try:
            store = s3fs.S3Map(root=store_path, s3=s3)
            ds = xr.open_zarr(store)

            # Get precipitation variable
            ds_var = ds[PrecipAorc.PRECIP_VAR]

            # Determine dimension names
            lat_dim = 'latitude' if 'latitude' in ds.dims else 'lat'
            lon_dim = 'longitude' if 'longitude' in ds.dims else 'lon'

            # Check coordinate ordering
            lat_coords = ds_var[lat_dim].values
            if lat_coords[0] > lat_coords[-1]:
                # Latitude is descending (north to south)
                ds_subset = ds_var.sel(
                    **{lat_dim: slice(north, south)},
                    **{lon_dim: slice(west, east)}
                )
            else:
                # Latitude is ascending
                ds_subset = ds_var.sel(
                    **{lat_dim: slice(south, north)},
                    **{lon_dim: slice(west, east)}
                )

            logger.info(f"Loading spatial subset...")
            # Compute spatial mean for each timestep (lazy then load)
            precip_mean = ds_subset.mean(dim=[lat_dim, lon_dim])
            precip_mean = precip_mean.load()

            logger.info(f"Loaded {len(precip_mean)} hourly timesteps")

        except Exception as e:
            logger.error(f"Error loading AORC data: {e}")
            raise

        # Convert to pandas Series for easier manipulation
        precip_series = precip_mean.to_series()
        precip_series.name = 'precip_mm'

        # Convert mm to inches (AORC kg/m² = mm)
        precip_inches = precip_series / 25.4

        # Define threshold for "wet" hour (0.01 inches = trace)
        wet_threshold = 0.01
        is_wet = precip_inches > wet_threshold

        # Find dry periods (inter-event gaps)
        # Use rolling sum to find consecutive dry hours
        dry_hours = (~is_wet).astype(int)

        # Identify event boundaries using inter-event gap
        # An event ends when dry period >= inter_event_hours
        events = []
        event_start = None
        dry_count = 0

        for i, (timestamp, wet) in enumerate(is_wet.items()):
            if wet:
                if event_start is None:
                    event_start = timestamp
                dry_count = 0
            else:
                if event_start is not None:
                    dry_count += 1
                    if dry_count >= inter_event_hours:
                        # Event ended
                        # Find actual end (last wet hour)
                        event_end_idx = i - int(dry_count)
                        if event_end_idx >= 0:
                            event_end = is_wet.index[event_end_idx]
                            events.append((event_start, event_end))
                        event_start = None
                        dry_count = 0

        # Handle event still in progress at end of year
        if event_start is not None:
            # Find last wet hour
            last_wet_idx = is_wet[is_wet].index[-1] if is_wet.any() else None
            if last_wet_idx is not None and last_wet_idx >= event_start:
                events.append((event_start, last_wet_idx))

        logger.info(f"Identified {len(events)} raw events")

        # Analyze each event
        storm_records = []
        for start, end in events:
            # Get precipitation for this event
            event_precip = precip_inches[start:end]

            if len(event_precip) == 0:
                continue

            # Calculate event statistics
            total_depth = event_precip.sum()
            peak_intensity = event_precip.max()
            duration = (end - start).total_seconds() / 3600 + 1  # hours (inclusive)
            wet_hours_count = (event_precip > wet_threshold).sum()

            # Apply filters
            if total_depth < min_depth_inches:
                continue
            if wet_hours_count < min_wet_hours:
                continue

            # Calculate simulation window with buffer
            sim_start = start - pd.Timedelta(hours=buffer_hours)
            sim_end = end + pd.Timedelta(hours=buffer_hours)

            storm_records.append({
                'start_time': start,
                'end_time': end,
                'sim_start': sim_start,
                'sim_end': sim_end,
                'total_depth_in': round(total_depth, 3),
                'peak_intensity_in_hr': round(peak_intensity, 3),
                'duration_hours': int(duration),
                'wet_hours': int(wet_hours_count),
            })

        if not storm_records:
            logger.warning("No storms found matching criteria")
            return pd.DataFrame(columns=[
                'storm_id', 'start_time', 'end_time', 'sim_start', 'sim_end',
                'total_depth_in', 'peak_intensity_in_hr', 'duration_hours',
                'wet_hours', 'rank'
            ])

        # Create DataFrame
        df = pd.DataFrame(storm_records)

        # Apply percentile filter if specified
        if percentile_threshold is not None:
            threshold_value = np.percentile(df['total_depth_in'], percentile_threshold)
            df = df[df['total_depth_in'] >= threshold_value]
            logger.info(f"Filtered to {len(df)} storms above {percentile_threshold}th percentile ({threshold_value:.2f} in)")

        # Rank by total depth (1 = largest)
        df['rank'] = df['total_depth_in'].rank(ascending=False, method='min').astype(int)

        # Add storm ID (sorted by date)
        df = df.sort_values('start_time').reset_index(drop=True)
        df['storm_id'] = range(1, len(df) + 1)

        # Reorder columns
        df = df[['storm_id', 'start_time', 'end_time', 'sim_start', 'sim_end',
                 'total_depth_in', 'peak_intensity_in_hr', 'duration_hours',
                 'wet_hours', 'rank']]

        logger.info(f"Storm catalog complete: {len(df)} storms")
        if len(df) > 0:
            logger.info(f"  Total depth range: {df['total_depth_in'].min():.2f} - {df['total_depth_in'].max():.2f} inches")
            logger.info(f"  Largest storm: {df[df['rank']==1]['start_time'].iloc[0]} ({df['total_depth_in'].max():.2f} in)")

        return df

    @staticmethod
    def create_storm_plans(
        storm_catalog: 'pd.DataFrame',
        bounds: Tuple[float, float, float, float],
        template_plan: str,
        precip_folder: Union[str, Path] = "Precipitation",
        ras_object: Optional['RasPrj'] = None,
        download_data: bool = True,
        max_storms: Optional[int] = None,
        enable_timeseries: bool = True
    ) -> 'pd.DataFrame':
        """
        Create HEC-RAS plan and unsteady files for each storm in a catalog.

        For each storm event, this function:
        1. Clones the template plan and unsteady files
        2. Downloads AORC precipitation data (optional)
        3. Configures gridded precipitation in the unsteady file
        4. Updates simulation dates in the plan file
        5. Optionally enables HDF time series output

        Parameters
        ----------
        storm_catalog : pd.DataFrame
            Storm catalog from get_storm_catalog() with columns:
            storm_id, start_time, end_time, sim_start, sim_end, etc.
        bounds : Tuple[float, float, float, float]
            Bounding box in WGS84 as (west, south, east, north).
            Same bounds used for get_storm_catalog().
        template_plan : str
            Plan number to use as template (e.g., "06").
            Must be an unsteady plan with precipitation enabled.
        precip_folder : str or Path, default "Precipitation"
            Folder for precipitation NetCDF files (relative to project folder).
        ras_object : RasPrj, optional
            RAS project object. If None, uses global ras instance.
        download_data : bool, default True
            If True, download AORC data for each storm.
            If False, assumes data already exists (use for testing).
        max_storms : int, optional
            Maximum number of storms to process. If None, process all.
            Useful for testing with a subset.
        enable_timeseries : bool, default True
            If True, enable HDF time series output (HDF Write Time Slices=-1).
            Required for extracting cell-level time series from results.

        Returns
        -------
        pd.DataFrame
            Extended storm catalog with additional columns:
            - plan_number: New plan number (e.g., "07")
            - unsteady_number: New unsteady number (e.g., "05")
            - precip_file: Path to precipitation NetCDF file
            - status: "success" or error message

        Examples
        --------
        >>> from ras_commander import init_ras_project
        >>> from ras_commander.precip import PrecipAorc
        >>>
        >>> # Initialize project
        >>> init_ras_project("/path/to/project", "6.6")
        >>>
        >>> # Get project bounds and storm catalog
        >>> bounds = (-77.71, 41.01, -77.25, 41.22)
        >>> storms = PrecipAorc.get_storm_catalog(bounds, 2020, percentile_threshold=90)
        >>>
        >>> # Create plans for top storms
        >>> results = PrecipAorc.create_storm_plans(
        ...     storm_catalog=storms,
        ...     bounds=bounds,
        ...     template_plan="06",
        ...     max_storms=5
        ... )
        >>> print(results[['storm_id', 'plan_number', 'status']])

        Notes
        -----
        - Template plan must have Met BC Precipitation enabled
        - Creates unique file names based on storm date: storm_YYYYMMDD.nc
        - Plan Short ID format: "Storm_MMDD" (e.g., "Storm_0430")
        - All files are created in the project folder
        """
        import pandas as pd

        # Import RAS modules (avoid circular imports)
        from ..RasPlan import RasPlan
        from ..RasUnsteady import RasUnsteady
        from ..RasPrj import ras

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        precip_folder = Path(precip_folder)
        precip_path = ras_obj.project_folder / precip_folder
        precip_path.mkdir(parents=True, exist_ok=True)

        # Get template plan's unsteady file
        template_plan_path = RasPlan.get_plan_path(template_plan, ras_obj)
        if template_plan_path is None:
            raise ValueError(f"Template plan '{template_plan}' not found")

        # Read template plan to find unsteady file
        with open(template_plan_path, 'r') as f:
            content = f.read()

        import re
        unsteady_match = re.search(r'Flow File=u(\d+)', content)
        if not unsteady_match:
            raise ValueError(f"Template plan '{template_plan}' has no unsteady flow file")
        template_unsteady = unsteady_match.group(1)

        logger.info(f"Creating storm plans from template plan {template_plan} (unsteady {template_unsteady})")
        logger.info(f"  Precipitation folder: {precip_path}")

        # Limit storms if requested
        storms_to_process = storm_catalog
        if max_storms is not None:
            storms_to_process = storm_catalog.head(max_storms)

        logger.info(f"  Processing {len(storms_to_process)} storms")

        # Results tracking
        results = []

        for idx, storm in storms_to_process.iterrows():
            storm_id = storm['storm_id']
            sim_start = storm['sim_start']
            sim_end = storm['sim_end']
            start_date = storm['start_time']

            # Create file names based on storm date
            date_str = start_date.strftime('%Y%m%d')
            short_id = f"Storm_{start_date.strftime('%m%d')}"
            plan_title = f"AORC Storm {start_date.strftime('%b %d, %Y')}"
            unsteady_title = f"AORC {start_date.strftime('%Y-%m-%d')}"
            precip_filename = f"storm_{date_str}.nc"
            precip_file = precip_folder / precip_filename

            result = {
                'storm_id': storm_id,
                'plan_number': None,
                'unsteady_number': None,
                'precip_file': str(precip_file),
                'status': 'pending'
            }

            try:
                logger.info(f"Storm {storm_id}: {start_date.strftime('%Y-%m-%d')} ({storm['total_depth_in']:.2f} in)")

                # 1. Download AORC data
                if download_data:
                    full_precip_path = ras_obj.project_folder / precip_file
                    if not full_precip_path.exists():
                        logger.info(f"  Downloading AORC data...")
                        PrecipAorc.download(
                            bounds=bounds,
                            start_time=sim_start,
                            end_time=sim_end,
                            output_path=full_precip_path
                        )
                    else:
                        logger.info(f"  Precipitation file exists, skipping download")

                # 2. Clone unsteady file
                logger.info(f"  Cloning unsteady file...")
                new_unsteady = RasPlan.clone_unsteady(
                    template_unsteady,
                    new_title=unsteady_title,
                    ras_object=ras_obj
                )
                result['unsteady_number'] = new_unsteady

                # 3. Configure gridded precipitation
                logger.info(f"  Configuring gridded precipitation...")
                RasUnsteady.set_gridded_precipitation(
                    unsteady_file=new_unsteady,
                    netcdf_path=precip_file,
                    ras_object=ras_obj
                )

                # 4. Clone plan file
                logger.info(f"  Cloning plan file...")
                new_plan = RasPlan.clone_plan(
                    template_plan,
                    new_plan_shortid=short_id,
                    new_title=plan_title,
                    ras_object=ras_obj
                )
                result['plan_number'] = new_plan

                # 5. Update plan to use new unsteady file
                RasPlan.set_unsteady(new_plan, new_unsteady, ras_object=ras_obj)

                # 6. Update simulation dates
                RasPlan.update_simulation_date(
                    new_plan,
                    start_date=sim_start.to_pydatetime(),
                    end_date=sim_end.to_pydatetime(),
                    ras_object=ras_obj
                )

                # 7. Enable HDF time series output if requested
                if enable_timeseries:
                    plan_path = RasPlan.get_plan_path(new_plan, ras_obj)
                    with open(plan_path, 'r') as f:
                        plan_content = f.read()
                    # Enable HDF Write Time Slices
                    plan_content = re.sub(
                        r'HDF Write Time Slices=\s*\d+',
                        'HDF Write Time Slices=-1',
                        plan_content
                    )
                    with open(plan_path, 'w') as f:
                        f.write(plan_content)
                    logger.info(f"  Enabled HDF time series output")

                result['status'] = 'success'
                logger.info(f"  Created plan {new_plan} with unsteady {new_unsteady}")

            except Exception as e:
                result['status'] = f'error: {str(e)}'
                logger.error(f"  Error processing storm {storm_id}: {e}")

            results.append(result)

        # Create results DataFrame
        results_df = pd.DataFrame(results)

        # Merge with original storm catalog
        output_df = storms_to_process.copy()
        output_df = output_df.merge(results_df, on='storm_id', how='left')

        success_count = (output_df['status'] == 'success').sum()
        logger.info(f"Storm plan creation complete: {success_count}/{len(output_df)} successful")

        return output_df
