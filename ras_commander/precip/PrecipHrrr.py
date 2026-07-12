"""
HRRR (High-Resolution Rapid Refresh) forecast precipitation download.

Downloads HRRR GRIB2 forecast files from NOAA NOMADS for use in
HEC-RAS rain-on-grid models and HEC-HMS precipitation forcing.

HRRR provides hourly/subhourly forecasts out to 18 hours (or 48 hours
for 00z/12z extended runs) at 3-km resolution over CONUS.

Data source: https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/

Example:
    >>> from ras_commander.precip import PrecipHrrr
    >>>
    >>> # Download latest available HRRR forecast
    >>> files = PrecipHrrr.get_latest_forecast(output_dir="hrrr_data")
    >>>
    >>> # Download specific cycle
    >>> files = PrecipHrrr.download_forecast(
    ...     output_dir="hrrr_data",
    ...     date="2024-07-15",
    ...     cycle=12,
    ...     hours=18
    ... )
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
import logging

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


def _check_hrrr_dependencies():
    """Check that HRRR download dependencies are installed."""
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        raise ImportError(
            f"Missing required packages for HRRR downloads: {', '.join(missing)}. "
            f"Install with: pip install {' '.join(missing)}"
        )


class PrecipHrrr:
    """
    Download HRRR forecast precipitation data from NOAA NOMADS.

    HRRR (High-Resolution Rapid Refresh) is NOAA's operational convection-allowing
    forecast model providing hourly updates at 3-km resolution over CONUS.

    Key characteristics:
    - **Spatial Resolution**: 3 km
    - **Temporal Resolution**: Hourly forecasts (subhourly available)
    - **Forecast Horizon**: 18 hours (standard), 48 hours (00z/12z extended)
    - **Update Frequency**: Every hour (cycles 00z-23z)
    - **Coverage**: CONUS
    - **Format**: GRIB2
    - **Latency**: ~2 hours after cycle time

    All methods are static - do not instantiate this class.

    Example:
        >>> from ras_commander.precip import PrecipHrrr
        >>> files = PrecipHrrr.download_forecast("hrrr_data", hours=18)
    """

    # NOAA NOMADS base URL for HRRR production data
    BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod"

    # Valid HRRR cycles (every hour)
    VALID_CYCLES = list(range(24))  # 00z through 23z

    # Extended forecast cycles (48-hour horizon instead of 18)
    EXTENDED_CYCLES = [0, 6, 12, 18]

    # Maximum forecast hours by cycle type
    MAX_HOURS_STANDARD = 18
    MAX_HOURS_EXTENDED = 48

    # CONUS bounds (approximate)
    CONUS_BOUNDS = (-134.1, 21.1, -60.9, 52.6)

    # Precipitation variable in HRRR GRIB2 files
    PRECIP_VARIABLE = "APCP"  # Accumulated precipitation

    @staticmethod
    @log_call
    def download_forecast(
        output_dir: Union[str, Path],
        date: Optional[str] = None,
        cycle: Optional[int] = None,
        hours: int = 18,
        variables: Optional[List[str]] = None,
        bounds: Optional[Tuple[float, float, float, float]] = None,
        overwrite: bool = False,
    ) -> List[Path]:
        """
        Download HRRR forecast GRIB2 files from NOAA NOMADS.

        Downloads subhourly (wrfsubhf) GRIB2 files for the specified forecast
        cycle and hour range. Files are saved to the output directory with
        original NOMADS naming conventions.

        Args:
            output_dir: Directory to save downloaded GRIB2 files.
            date: Forecast date as 'YYYY-MM-DD'. Defaults to today (UTC).
            cycle: Forecast cycle hour (0-23). Defaults to latest available.
            hours: Number of forecast hours to download (1-48). Default 18.
            variables: GRIB2 variables to filter (future use). Default None (all).
            bounds: Optional (west, south, east, north) to subset. Future use.
            overwrite: If True, re-download existing files. Default False.

        Returns:
            List[Path]: Paths to downloaded GRIB2 files, sorted by forecast hour.

        Raises:
            ImportError: If required packages not installed.
            ValueError: If invalid date, cycle, or hours specified.
            ConnectionError: If NOMADS server is unreachable.

        Example:
            >>> files = PrecipHrrr.download_forecast(
            ...     output_dir="hrrr_data",
            ...     date="2024-07-15",
            ...     cycle=12,
            ...     hours=18
            ... )
            >>> print(f"Downloaded {len(files)} forecast files")
        """
        _check_hrrr_dependencies()
        import requests

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve date
        if date is None:
            forecast_date = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            forecast_date = datetime.strptime(date, "%Y-%m-%d")

        date_str = forecast_date.strftime("%Y%m%d")

        # Resolve cycle
        if cycle is None:
            cycle = PrecipHrrr._detect_latest_cycle(date_str)
            logger.info(f"Auto-detected latest available cycle: {cycle:02d}z")

        if cycle not in PrecipHrrr.VALID_CYCLES:
            raise ValueError(
                f"Invalid cycle {cycle}. Must be 0-23."
            )

        # Validate hours
        max_hours = (
            PrecipHrrr.MAX_HOURS_EXTENDED
            if cycle in PrecipHrrr.EXTENDED_CYCLES
            else PrecipHrrr.MAX_HOURS_STANDARD
        )
        if hours > max_hours:
            logger.warning(
                f"Requested {hours} hours but cycle {cycle:02d}z max is {max_hours}. "
                f"Clamping to {max_hours} hours."
            )
            hours = max_hours

        if hours < 1:
            raise ValueError("hours must be >= 1")

        # Build URLs and download
        downloaded_files = []

        for fhr in range(1, hours + 1):
            filename = f"hrrr.t{cycle:02d}z.wrfsubhf{fhr:02d}.grib2"
            url = f"{PrecipHrrr.BASE_URL}/hrrr.{date_str}/conus/{filename}"
            local_path = output_dir / filename

            tmp_path = local_path.with_suffix(local_path.suffix + '.tmp')

            if local_path.exists() and not overwrite:
                # Clean up stale .tmp files left by failed previous downloads
                if tmp_path.exists():
                    tmp_path.unlink()
                logger.debug(f"Skipping existing file: {filename}")
                downloaded_files.append(local_path)
                continue

            logger.info(f"Downloading: {filename} (hour {fhr}/{hours})")

            try:
                response = requests.get(url, stream=True, timeout=120)
                response.raise_for_status()

                with open(tmp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Atomic rename: only promote to final path on full success
                tmp_path.rename(local_path)

                file_size_mb = local_path.stat().st_size / (1024 * 1024)
                logger.debug(f"Downloaded {filename} ({file_size_mb:.1f} MB)")
                downloaded_files.append(local_path)

            except requests.exceptions.HTTPError as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                if e.response.status_code == 404:
                    logger.warning(
                        f"File not found (may not be available yet): {filename}"
                    )
                    break
                else:
                    raise ConnectionError(
                        f"HTTP error downloading {filename}: {e}"
                    ) from e
            except requests.exceptions.ConnectionError as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise ConnectionError(
                    f"Cannot reach NOMADS server. Check internet connection. "
                    f"Error: {e}"
                ) from e
            except Exception:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

        logger.info(
            f"Downloaded {len(downloaded_files)} HRRR files for "
            f"{date_str} {cycle:02d}z (hours 1-{hours})"
        )

        return sorted(downloaded_files)

    @staticmethod
    @log_call
    def get_latest_forecast(
        output_dir: Union[str, Path],
        hours: int = 18,
        max_lookback_hours: int = 6,
        overwrite: bool = False,
    ) -> List[Path]:
        """
        Download the latest available HRRR forecast cycle.

        Automatically detects the most recent available cycle by checking
        NOMADS for the latest data, accounting for the ~2 hour processing
        latency. Looks back up to max_lookback_hours if the most recent
        cycle is not yet available.

        Args:
            output_dir: Directory to save downloaded GRIB2 files.
            hours: Number of forecast hours to download. Default 18.
            max_lookback_hours: Maximum hours to look back for available data. Default 6.
            overwrite: If True, re-download existing files. Default False.

        Returns:
            List[Path]: Paths to downloaded GRIB2 files.

        Raises:
            RuntimeError: If no available cycle found within lookback window.

        Example:
            >>> files = PrecipHrrr.get_latest_forecast("hrrr_data")
            >>> print(f"Latest forecast: {len(files)} files")
        """
        _check_hrrr_dependencies()
        import requests

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # Try cycles from most recent to max_lookback_hours ago
        # Account for ~2 hour processing latency
        candidate_time = now_utc - timedelta(hours=2)

        for lookback in range(max_lookback_hours + 1):
            check_time = candidate_time - timedelta(hours=lookback)
            date_str = check_time.strftime("%Y-%m-%d")
            cycle = check_time.hour

            logger.debug(
                f"Checking availability: {date_str} {cycle:02d}z"
            )

            if PrecipHrrr.check_availability(date_str, cycle):
                logger.info(
                    f"Found available cycle: {date_str} {cycle:02d}z"
                )
                return PrecipHrrr.download_forecast(
                    output_dir=output_dir,
                    date=date_str,
                    cycle=cycle,
                    hours=hours,
                    overwrite=overwrite,
                )

        raise RuntimeError(
            f"No available HRRR cycle found in the last {max_lookback_hours} hours. "
            f"NOMADS may be experiencing delays or outages."
        )

    @staticmethod
    @log_call
    def check_availability(
        date: Optional[str] = None,
        cycle: Optional[int] = None,
    ) -> bool:
        """
        Check if a specific HRRR forecast cycle is available on NOMADS.

        Performs a lightweight HEAD request for the first forecast hour
        file to determine availability without downloading data.

        Args:
            date: Date as 'YYYY-MM-DD'. Defaults to today (UTC).
            cycle: Cycle hour (0-23). Defaults to most recent.

        Returns:
            bool: True if forecast data is available on NOMADS.

        Example:
            >>> if PrecipHrrr.check_availability("2024-07-15", 12):
            ...     print("12z cycle available")
        """
        _check_hrrr_dependencies()
        import requests

        if date is None:
            date = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")

        if cycle is None:
            cycle = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)).hour

        forecast_date = datetime.strptime(date, "%Y-%m-%d")
        date_str = forecast_date.strftime("%Y%m%d")

        filename = f"hrrr.t{cycle:02d}z.wrfsubhf01.grib2"
        url = f"{PrecipHrrr.BASE_URL}/hrrr.{date_str}/conus/{filename}"

        try:
            response = requests.head(url, timeout=30, allow_redirects=True)
            available = response.status_code == 200

            if available:
                logger.debug(f"HRRR {date_str} {cycle:02d}z is available")
            else:
                logger.debug(
                    f"HRRR {date_str} {cycle:02d}z not available "
                    f"(HTTP {response.status_code})"
                )

            return available

        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not check HRRR availability: {e}")
            return False

    @staticmethod
    @log_call
    def get_info() -> Dict:
        """
        Return metadata about the HRRR dataset.

        Returns:
            Dict: Dataset metadata including coverage, resolution,
                  update frequency, and data source URLs.

        Example:
            >>> info = PrecipHrrr.get_info()
            >>> print(f"Resolution: {info['spatial_resolution']}")
        """
        return {
            "name": "HRRR (High-Resolution Rapid Refresh)",
            "provider": "NOAA / NCEP",
            "spatial_resolution": "3 km",
            "temporal_resolution": "Hourly forecasts",
            "coverage": "CONUS",
            "bounds": PrecipHrrr.CONUS_BOUNDS,
            "forecast_horizon_standard": "18 hours",
            "forecast_horizon_extended": "48 hours (00z, 06z, 12z, 18z cycles)",
            "update_frequency": "Hourly (every cycle)",
            "format": "GRIB2",
            "latency": "~2 hours after cycle time",
            "base_url": PrecipHrrr.BASE_URL,
            "precipitation_variable": PrecipHrrr.PRECIP_VARIABLE,
            "documentation": "https://rapidrefresh.noaa.gov/hrrr/",
        }

    @staticmethod
    def _detect_latest_cycle(date_str: str) -> int:
        """
        Detect the latest available cycle for a given date.

        Checks NOMADS starting from the most recent cycle and works
        backward until an available cycle is found.

        Args:
            date_str: Date in YYYYMMDD format.

        Returns:
            int: Latest available cycle hour (0-23).

        Raises:
            RuntimeError: If no cycle found for the given date.
        """
        import requests

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        current_date_str = now_utc.strftime("%Y%m%d")

        # If checking today, start from ~2 hours ago (latency)
        if date_str == current_date_str:
            start_cycle = max(0, now_utc.hour - 2)
        else:
            start_cycle = 23

        for cycle in range(start_cycle, -1, -1):
            filename = f"hrrr.t{cycle:02d}z.wrfsubhf01.grib2"
            url = f"{PrecipHrrr.BASE_URL}/hrrr.{date_str}/conus/{filename}"

            try:
                response = requests.head(url, timeout=15, allow_redirects=True)
                if response.status_code == 200:
                    return cycle
            except requests.exceptions.RequestException:
                continue

        raise RuntimeError(
            f"No available HRRR cycle found for {date_str}. "
            f"Data may not be available for this date."
        )

    @staticmethod
    @log_call
    def extract_precipitation(
        grib_files: List[Union[str, Path]],
        bounds: Optional[Tuple[float, float, float, float]] = None,
    ):
        """
        Extract precipitation data from downloaded HRRR GRIB2 files.

        Reads GRIB2 files and extracts accumulated precipitation (APCP),
        optionally clipping to specified bounds. Requires cfgrib and xarray.

        Args:
            grib_files: List of paths to HRRR GRIB2 files.
            bounds: Optional (west, south, east, north) in decimal degrees
                    to clip the data spatially.

        Returns:
            xarray.Dataset: Precipitation data with lat/lon coordinates
                           and time dimension.

        Raises:
            ImportError: If cfgrib or xarray not installed.

        Example:
            >>> files = PrecipHrrr.download_forecast("hrrr_data", hours=6)
            >>> precip = PrecipHrrr.extract_precipitation(files)
            >>> print(f"Shape: {precip['tp'].shape}")
        """
        try:
            import xarray as xr
        except ImportError:
            raise ImportError(
                "xarray is required for HRRR precipitation extraction. "
                "Install with: pip install xarray cfgrib"
            )

        try:
            import cfgrib  # noqa: F401
        except ImportError:
            raise ImportError(
                "cfgrib is required for reading HRRR GRIB2 files. "
                "Install with: pip install cfgrib"
            )

        grib_paths = [Path(f) for f in grib_files]

        # Validate files exist
        for grib_path in grib_paths:
            if not grib_path.exists():
                raise FileNotFoundError(f"GRIB2 file not found: {grib_path}")

        logger.info(f"Reading {len(grib_paths)} HRRR GRIB2 files")

        datasets = []
        for grib_path in sorted(grib_paths):
            try:
                ds = xr.open_dataset(
                    grib_path,
                    engine="cfgrib",
                    backend_kwargs={
                        "filter_by_keys": {"shortName": "tp"}
                    },
                )
                datasets.append(ds)
            except Exception as e:
                logger.warning(f"Could not read {grib_path.name}: {e}")
                continue

        if not datasets:
            raise ValueError("No valid precipitation data found in GRIB2 files")

        # Concatenate along time dimension
        combined = xr.concat(datasets, dim="step")

        # Clip to bounds if specified
        if bounds is not None:
            west, south, east, north = bounds
            lons = xr.where(
                combined['longitude'] > 180,
                combined['longitude'] - 360,
                combined['longitude'],
            )
            mask = (
                (combined['latitude'] >= south)
                & (combined['latitude'] <= north)
                & (lons >= west)
                & (lons <= east)
            )
            if not mask.any().item():
                raise ValueError(
                    f"Bounds do not intersect HRRR grid: "
                    f"({west}, {south}, {east}, {north})"
                )
            combined = combined.where(mask, drop=True)
            logger.info(
                f"Clipped to bounds: ({west}, {south}, {east}, {north})"
            )

        logger.info(
            f"Extracted precipitation from {len(datasets)} files"
        )

        return combined

    @staticmethod
    @log_call
    def get_basin_average(
        grib_files: List[Union[str, Path]],
        geometry,
    ):
        """
        Calculate basin-average precipitation from HRRR forecast files.

        Clips the HRRR precipitation grid to a watershed boundary polygon and
        calculates the spatial average for each forecast record.

        Args:
            grib_files: List of HRRR GRIB2 file paths.
            geometry: Shapely polygon or GeoDataFrame defining watershed boundary.
                     Must be in EPSG:4326 (WGS84).

        Returns:
            pandas.DataFrame: Time series with ``forecast_hour`` (legacy
            1-based record index), ``precip_mm``, ``precip_inches``,
            ``cumulative_mm``, ``cumulative_inches``, ``valid_time`` (UTC),
            and ``forecast_lead_hours``. Lead hours may be fractional for
            subhourly products.

        Raises:
            ImportError: If required packages not installed.
            ValueError: If HRRR temporal coordinates are missing, invalid, or
                inconsistent with the precipitation records.

        Example:
            >>> import geopandas as gpd
            >>> watershed = gpd.read_file("watershed.shp")
            >>> files = PrecipHrrr.download_forecast("hrrr_data", hours=18)
            >>> basin_avg = PrecipHrrr.get_basin_average(files, watershed)
        """
        try:
            import numpy as np
            import pandas as pd
            import xarray as xr
            import rasterio.features  # noqa: F401
        except ImportError as e:
            raise ImportError(
                f"Missing packages for basin averaging: {e}. "
                "Install with: pip install xarray cfgrib rasterio numpy pandas"
            )

        # Get geometry bounds for initial clip
        if hasattr(geometry, 'total_bounds'):
            west, south, east, north = geometry.total_bounds
            if hasattr(geometry, 'geometry'):
                geometry_source = geometry.geometry
            else:
                geometry_source = geometry
            if hasattr(geometry_source, 'union_all'):
                basin_geometry = geometry_source.union_all()
            else:
                basin_geometry = geometry_source.unary_union
        elif hasattr(geometry, 'bounds') and hasattr(geometry, '__geo_interface__'):
            west, south, east, north = geometry.bounds
            basin_geometry = geometry
        else:
            raise TypeError(
                "geometry must be a Shapely polygon or GeoDataFrame"
            )

        if basin_geometry is None or getattr(basin_geometry, 'is_empty', False):
            raise ValueError("geometry must contain at least one non-empty shape")

        # Extract full precipitation grid
        precip_ds = PrecipHrrr.extract_precipitation(grib_files)

        record_count = precip_ds.sizes.get('step', 0)
        if record_count == 0:
            raise ValueError("HRRR precipitation data contains no forecast records")

        step_values = np.asarray(precip_ds['step'].values).reshape(-1)
        if step_values.size != record_count:
            raise ValueError(
                "HRRR step coordinate does not match the precipitation record count"
            )
        if (
            np.issubdtype(step_values.dtype, np.number)
            and not np.issubdtype(step_values.dtype, np.timedelta64)
        ):
            raise ValueError(
                "HRRR step coordinate must contain forecast lead timedeltas"
            )

        try:
            step_deltas = pd.to_timedelta(step_values)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Could not interpret the HRRR step coordinate as forecast leads"
            ) from exc
        if step_deltas.isna().any():
            raise ValueError("HRRR step coordinate contains missing forecast leads")

        forecast_lead_hours = step_deltas.total_seconds() / 3600.0
        if np.any(forecast_lead_hours < 0):
            raise ValueError("HRRR forecast leads must be nonnegative")
        if record_count > 1 and np.any(np.diff(forecast_lead_hours) <= 0):
            raise ValueError("HRRR forecast leads must be strictly increasing")

        if 'valid_time' in precip_ds.coords:
            valid_time_values = np.asarray(
                precip_ds['valid_time'].values
            ).reshape(-1)
            if valid_time_values.size != record_count:
                raise ValueError(
                    "HRRR valid_time coordinate does not match the precipitation "
                    "record count"
                )
            valid_times = pd.DatetimeIndex(pd.to_datetime(valid_time_values))
            if valid_times.isna().any():
                raise ValueError(
                    "HRRR valid_time coordinate contains missing timestamps"
                )
            if not valid_times.is_unique:
                raise ValueError(
                    "HRRR valid_time coordinate contains duplicate timestamps"
                )
            if not valid_times.is_monotonic_increasing:
                raise ValueError(
                    "HRRR valid_time coordinate must be chronological"
                )
        else:
            valid_times = None

        forecast_reference_time = None
        if 'time' in precip_ds.coords:
            cycle_time_values = np.asarray(precip_ds['time'].values).reshape(-1)
            if cycle_time_values.size == 1:
                cycle_times = pd.DatetimeIndex(pd.to_datetime(cycle_time_values))
            elif cycle_time_values.size == record_count:
                cycle_times = pd.DatetimeIndex(
                    pd.to_datetime(cycle_time_values)
                )
            else:
                raise ValueError(
                    "HRRR time coordinate cannot be aligned with forecast records"
                )
            if cycle_times.isna().any():
                raise ValueError("HRRR time coordinate contains missing cycle times")
            unique_cycle_times = cycle_times.unique()
            if len(unique_cycle_times) != 1:
                raise ValueError(
                    "HRRR precipitation records must come from one forecast cycle"
                )
            forecast_reference_time = unique_cycle_times[0]

        if valid_times is None and forecast_reference_time is None:
            raise ValueError(
                "HRRR precipitation data must include valid_time or time metadata"
            )

        if valid_times is None:
            valid_times = pd.DatetimeIndex(
                [forecast_reference_time] * record_count
            ) + step_deltas
        elif forecast_reference_time is None:
            derived_reference_times = valid_times - step_deltas
            unique_reference_times = derived_reference_times.unique()
            if len(unique_reference_times) != 1:
                raise ValueError(
                    "HRRR valid times and forecast leads imply multiple forecast cycles"
                )
            forecast_reference_time = unique_reference_times[0]
        else:
            expected_valid_times = pd.DatetimeIndex(
                [forecast_reference_time] * record_count
            ) + step_deltas
            if not valid_times.equals(expected_valid_times):
                raise ValueError(
                    "HRRR valid_time must equal the forecast cycle time plus step"
                )

        logger.info("Calculating basin-average precipitation")

        _tp0 = precip_ds['tp'].isel(step=0)
        _precip_shape = tuple(_tp0.shape)
        _lons = np.asarray(_tp0.coords['longitude'].values)
        _lats = np.asarray(_tp0.coords['latitude'].values)

        # HRRR uses 0-360 longitude convention; convert to -180/180.
        _lons = np.where(_lons > 180, _lons - 360, _lons)
        if _lons.ndim == 1 and _lats.ndim == 1:
            _lon_grid, _lat_grid = np.meshgrid(_lons, _lats)
        else:
            _lon_grid, _lat_grid = _lons, _lats

        _ny, _nx = _precip_shape
        _res_x = (float(_lon_grid.max()) - float(_lon_grid.min())) / max(_nx - 1, 1)
        _res_y = (float(_lat_grid.max()) - float(_lat_grid.min())) / max(_ny - 1, 1)
        _row0_lat = float(_lat_grid[0, 0])
        _rowN_lat = float(_lat_grid[-1, 0])
        _south_up = _row0_lat < _rowN_lat

        _bbox_mask = (
            (_lon_grid >= west)
            & (_lon_grid <= east)
            & (_lat_grid >= south)
            & (_lat_grid <= north)
        )
        if _south_up:
            _bbox_mask = _bbox_mask[::-1, :]
        if not np.any(_bbox_mask):
            raise ValueError("geometry does not intersect extracted HRRR grid")

        _grid_transform = None
        try:
            from affine import Affine as _AffineTransform

            # Build north-up affine: west edge, north edge, positive dx, negative dy
            _grid_transform = _AffineTransform(
                _res_x, 0.0, float(_lon_grid.min()) - _res_x / 2,
                0.0, -_res_y, float(_lat_grid.max()) + _res_y / 2,
            )
        except ImportError:
            logger.warning(
                "affine package not available; exact basin masking is disabled "
                "and zonal_stats will use pixel coordinates "
                "(install with: pip install affine)"
            )

        _exact_mask = None
        if _grid_transform is not None:
            try:
                _exact_mask = rasterio.features.geometry_mask(
                    [basin_geometry.__geo_interface__],
                    out_shape=_precip_shape,
                    transform=_grid_transform,
                    invert=True,
                )
                if not np.any(_exact_mask):
                    _exact_mask = None
            except Exception as exc:
                logger.warning(
                    "Could not build exact basin mask; falling back to "
                    "watershed bounding box average: %s",
                    exc,
                )

        # Calculate basin-average using rasterstats if available
        try:
            from rasterstats import zonal_stats

            results = []
            for step_idx in range(len(precip_ds.step)):
                precip_slice = precip_ds['tp'].isel(step=step_idx).values
                # Flip to north-up orientation if grid is stored south-up
                if _south_up:
                    precip_slice = precip_slice[::-1, :]

                stats = zonal_stats(
                    [basin_geometry.__geo_interface__],
                    precip_slice,
                    affine=_grid_transform,
                    stats=['mean'],
                    nodata=np.nan,
                )

                mean_precip = stats[0]['mean'] if stats[0]['mean'] is not None else 0.0
                results.append(mean_precip)

        except ImportError:
            if _exact_mask is not None:
                logger.warning(
                    "rasterstats not available - using rasterio geometry mask "
                    "fallback for exact basin average"
                )
                _fallback_mask = _exact_mask
            else:
                logger.warning(
                    "rasterstats not available - using watershed bounding box "
                    "average instead of exact basin boundary"
                )
                _fallback_mask = _bbox_mask

            results = []
            for step_idx in range(len(precip_ds.step)):
                precip_slice = np.asarray(
                    precip_ds['tp'].isel(step=step_idx).values,
                    dtype=float,
                )
                if _south_up:
                    precip_slice = precip_slice[::-1, :]
                selected_values = precip_slice[_fallback_mask]
                finite_values = selected_values[np.isfinite(selected_values)]
                mean_val = float(finite_values.mean()) if finite_values.size else 0.0
                results.append(mean_val)

        if len(results) != record_count:
            raise ValueError(
                "Basin-average results do not match the HRRR record count"
            )

        df = pd.DataFrame({
            'forecast_hour': range(1, record_count + 1),
            'precip_mm': results,
        })

        # Add unit conversions
        df['precip_inches'] = df['precip_mm'] / 25.4
        df['cumulative_mm'] = df['precip_mm'].cumsum()
        df['cumulative_inches'] = df['precip_inches'].cumsum()
        df['valid_time'] = valid_times
        df['forecast_lead_hours'] = forecast_lead_hours

        if record_count == 1:
            spacing_summary = "single valid time"
        else:
            spacing_minutes = (
                pd.Series(valid_times)
                .diff()
                .dropna()
                .dt.total_seconds()
                .to_numpy()
                / 60.0
            )
            unique_spacing = np.unique(np.round(spacing_minutes, decimals=9))
            if unique_spacing.size == 1:
                minutes = float(unique_spacing[0])
                if minutes == 60.0:
                    spacing_summary = "1-hour valid-time spacing"
                elif minutes.is_integer():
                    spacing_summary = f"{int(minutes)}-minute valid-time spacing"
                else:
                    spacing_summary = f"{minutes:g}-minute valid-time spacing"
            else:
                spacing_summary = "mixed valid-time spacing"

        logger.info(
            "Basin average: %.2f in across %d records (%s; lead %.2f-%.2f h)",
            df['cumulative_inches'].iloc[-1],
            record_count,
            spacing_summary,
            float(forecast_lead_hours[0]),
            float(forecast_lead_hours[-1]),
        )

        return df
