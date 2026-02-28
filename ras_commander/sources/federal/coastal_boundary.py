"""
STOFS-3D Coastal Boundary Integration.

Downloads NOAA STOFS-3D-Atlantic storm surge forecasts and generates
HEC-RAS stage boundary conditions from coastal water surface elevation data.

STOFS-3D (Surge and Tide Operational Forecast System, 3D) provides
operational surge and tide forecasts for the Atlantic coast.

Data source: https://nomads.ncep.noaa.gov/pub/data/nccf/com/stofs/prod/

Example:
    >>> from ras_commander.sources.federal import CoastalBoundary
    >>>
    >>> # Download latest STOFS-3D forecast
    >>> files = CoastalBoundary.download_stofs3d("stofs_data")
    >>>
    >>> # Extract WSE at a coastal point
    >>> wse = CoastalBoundary.extract_wse_at_point(
    ...     "stofs_data",
    ...     lat=29.35, lon=-94.77  # Galveston Bay entrance
    ... )
    >>>
    >>> # Generate HEC-RAS stage boundary condition
    >>> CoastalBoundary.generate_stage_bc(
    ...     wse_timeseries=wse,
    ...     unsteady_file="project.u01",
    ...     bc_location="Downstream"
    ... )
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta

from ...LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


def _check_coastal_dependencies():
    """Check that coastal boundary dependencies are installed."""
    missing = []
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    if missing:
        raise ImportError(
            f"Missing required packages for coastal boundary: {', '.join(missing)}. "
            f"Install with: pip install {' '.join(missing)}"
        )


class CoastalBoundary:
    """
    Download STOFS-3D coastal forecasts and generate HEC-RAS stage boundaries.

    STOFS-3D-Atlantic is NOAA's operational storm surge and tide forecast system
    providing water surface elevation predictions along the US Atlantic and Gulf
    coasts.

    Key characteristics:
    - **Coverage**: US Atlantic and Gulf coasts
    - **Resolution**: Variable (unstructured mesh, 80m nearshore to 50km offshore)
    - **Forecast Horizon**: 48 hours (nowcast + forecast)
    - **Update Frequency**: Every 6 hours (00z, 06z, 12z, 18z)
    - **Format**: NetCDF (field output), GRIB2 (surface fields)
    - **Datum**: NAVD88 meters
    - **Variables**: Water surface elevation, currents, temperature, salinity

    All methods are static - do not instantiate this class.

    Example:
        >>> from ras_commander.sources.federal import CoastalBoundary
        >>> wse = CoastalBoundary.extract_wse_at_point(
        ...     "stofs_data", lat=29.35, lon=-94.77
        ... )
    """

    # NOAA NOMADS base URL for STOFS-3D production data
    BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/stofs/prod"

    # Valid forecast cycles
    VALID_CYCLES = [0, 6, 12, 18]

    # Forecast duration in hours
    FORECAST_HOURS = 48

    # Meters to feet conversion factor
    METERS_TO_FEET = 3.28084

    # STOFS-3D field output file pattern
    # stofs_3d_atl.t{cycle}z.fields.cwl.nc (combined water level)
    FIELD_PATTERN = "stofs_3d_atl.t{cycle:02d}z.fields.cwl.nc"

    # Point output file pattern (station time series)
    POINT_PATTERN = "stofs_3d_atl.t{cycle:02d}z.points.cwl.nc"

    @staticmethod
    @log_call
    def download_stofs3d(
        output_dir: Union[str, Path],
        date: Optional[str] = None,
        cycle: Optional[int] = None,
        file_type: str = "points",
        overwrite: bool = False,
    ) -> List[Path]:
        """
        Download STOFS-3D-Atlantic forecast files from NOAA NOMADS.

        Downloads combined water level (CWL) output files containing
        water surface elevation predictions. Supports both field (gridded)
        and point (station) output formats.

        Args:
            output_dir: Directory to save downloaded files.
            date: Forecast date as 'YYYY-MM-DD'. Defaults to today (UTC).
            cycle: Forecast cycle (0, 6, 12, or 18). Defaults to latest available.
            file_type: Output type - 'points' for station data (smaller) or
                      'fields' for gridded data (larger). Default 'points'.
            overwrite: If True, re-download existing files. Default False.

        Returns:
            List[Path]: Paths to downloaded NetCDF files.

        Raises:
            ImportError: If required packages not installed.
            ValueError: If invalid cycle or file_type specified.
            ConnectionError: If NOMADS server is unreachable.

        Example:
            >>> files = CoastalBoundary.download_stofs3d(
            ...     "stofs_data",
            ...     date="2024-07-15",
            ...     cycle=12,
            ...     file_type="points"
            ... )
        """
        _check_coastal_dependencies()
        import requests

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve date
        if date is None:
            forecast_date = datetime.utcnow()
        else:
            forecast_date = datetime.strptime(date, "%Y-%m-%d")

        date_str = forecast_date.strftime("%Y%m%d")

        # Resolve cycle
        if cycle is None:
            cycle = CoastalBoundary._detect_latest_cycle(date_str)
            logger.info(f"Auto-detected latest available cycle: {cycle:02d}z")

        if cycle not in CoastalBoundary.VALID_CYCLES:
            raise ValueError(
                f"Invalid cycle {cycle}. Must be one of {CoastalBoundary.VALID_CYCLES}."
            )

        # Determine file pattern
        if file_type == "points":
            filename = CoastalBoundary.POINT_PATTERN.format(cycle=cycle)
        elif file_type == "fields":
            filename = CoastalBoundary.FIELD_PATTERN.format(cycle=cycle)
        else:
            raise ValueError(
                f"Invalid file_type '{file_type}'. Must be 'points' or 'fields'."
            )

        url = (
            f"{CoastalBoundary.BASE_URL}/stofs_3d_atl.{date_str}/"
            f"{filename}"
        )
        local_path = output_dir / filename

        downloaded_files = []

        if local_path.exists() and not overwrite:
            logger.info(f"Using existing file: {filename}")
            downloaded_files.append(local_path)
            return downloaded_files

        logger.info(f"Downloading STOFS-3D: {filename}")

        try:
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size_mb = local_path.stat().st_size / (1024 * 1024)
            logger.info(f"Downloaded {filename} ({file_size_mb:.1f} MB)")
            downloaded_files.append(local_path)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(
                    f"STOFS-3D file not found: {filename}. "
                    f"Cycle may not be available yet."
                )
            else:
                raise ConnectionError(
                    f"HTTP error downloading STOFS-3D: {e}"
                ) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"Cannot reach NOMADS server. Check internet connection. "
                f"Error: {e}"
            ) from e

        return downloaded_files

    @staticmethod
    @log_call
    def extract_wse_at_point(
        stofs_dir: Union[str, Path],
        lat: float,
        lon: float,
        date: Optional[str] = None,
        cycle: Optional[int] = None,
        units: str = "feet",
    ):
        """
        Extract water surface elevation time series at a coastal point.

        Reads STOFS-3D NetCDF output and extracts the WSE time series at
        the grid cell nearest to the specified latitude/longitude. Converts
        from NAVD88 meters (native) to feet if requested.

        Args:
            stofs_dir: Directory containing STOFS-3D NetCDF files, or
                      path to a specific NetCDF file.
            lat: Latitude in decimal degrees (positive north).
            lon: Longitude in decimal degrees (negative west).
            date: Optional date to filter files. Format 'YYYY-MM-DD'.
            cycle: Optional cycle to filter files (0, 6, 12, 18).
            units: Output units - 'feet' or 'meters'. Default 'feet'.

        Returns:
            pandas.DataFrame: Time series with columns:
                - 'datetime': Timestamp (UTC)
                - 'wse_m': Water surface elevation in meters NAVD88
                - 'wse_ft': Water surface elevation in feet NAVD88

        Raises:
            ImportError: If xarray or netCDF4 not installed.
            FileNotFoundError: If no STOFS-3D files found.
            ValueError: If coordinates are outside model domain.

        Example:
            >>> wse = CoastalBoundary.extract_wse_at_point(
            ...     "stofs_data",
            ...     lat=29.35, lon=-94.77  # Galveston Bay entrance
            ... )
            >>> print(f"Max surge: {wse['wse_ft'].max():.2f} ft NAVD88")
        """
        try:
            import xarray as xr
            import numpy as np
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                f"Missing packages for WSE extraction: {e}. "
                "Install with: pip install xarray netCDF4 numpy pandas"
            )

        stofs_path = Path(stofs_dir)

        # Find the NetCDF file
        if stofs_path.is_file():
            nc_files = [stofs_path]
        else:
            nc_files = sorted(stofs_path.glob("stofs_3d_atl.*.nc"))
            if date and cycle is not None:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                date_str = date_obj.strftime("%Y%m%d")
                pattern = f"stofs_3d_atl.t{cycle:02d}z.*.cwl.nc"
                nc_files = sorted(stofs_path.glob(pattern))

        if not nc_files:
            raise FileNotFoundError(
                f"No STOFS-3D NetCDF files found in {stofs_path}. "
                f"Download first with CoastalBoundary.download_stofs3d()"
            )

        logger.info(
            f"Extracting WSE at ({lat:.4f}, {lon:.4f}) from "
            f"{len(nc_files)} file(s)"
        )

        # Open the most recent file
        nc_file = nc_files[-1]

        try:
            ds = xr.open_dataset(nc_file)
        except Exception as e:
            raise ValueError(
                f"Could not open STOFS-3D file {nc_file.name}: {e}"
            )

        # Find nearest point using available coordinate variables
        # STOFS-3D uses unstructured mesh - find nearest node
        if 'x' in ds.coords and 'y' in ds.coords:
            x_var, y_var = 'x', 'y'
        elif 'lon' in ds.coords and 'lat' in ds.coords:
            x_var, y_var = 'lon', 'lat'
        elif 'longitude' in ds.coords and 'latitude' in ds.coords:
            x_var, y_var = 'longitude', 'latitude'
        else:
            # Try dimension variables
            coord_names = list(ds.coords.keys()) + list(ds.dims.keys())
            raise ValueError(
                f"Could not identify coordinate variables in STOFS-3D file. "
                f"Available: {coord_names}"
            )

        # Handle negative west longitude
        model_lons = ds[x_var].values
        if lon < 0 and model_lons.min() >= 0:
            lon_query = lon + 360  # Convert to 0-360
        else:
            lon_query = lon

        # Find nearest grid point
        dist = np.sqrt(
            (ds[x_var].values - lon_query) ** 2 +
            (ds[y_var].values - lat) ** 2
        )
        nearest_idx = int(np.argmin(dist))
        min_dist = float(dist[nearest_idx])

        # Sanity check: nearest point should be within ~0.5 degrees
        if min_dist > 0.5:
            raise ValueError(
                f"Nearest STOFS-3D point is {min_dist:.2f} degrees away from "
                f"({lat}, {lon}). Point may be outside model domain. "
                f"STOFS-3D covers the US Atlantic and Gulf coasts."
            )

        nearest_lat = float(ds[y_var].values[nearest_idx])
        nearest_lon = float(ds[x_var].values[nearest_idx])

        logger.info(
            f"Nearest grid point: ({nearest_lat:.4f}, {nearest_lon:.4f}), "
            f"distance: {min_dist:.4f} degrees"
        )

        # Extract WSE time series at nearest point
        # Variable name depends on file type
        wse_var = None
        for var_name in ['zeta', 'surge', 'cwl', 'ssh', 'elevation']:
            if var_name in ds.data_vars:
                wse_var = var_name
                break

        if wse_var is None:
            available = list(ds.data_vars.keys())
            raise ValueError(
                f"Could not find WSE variable in STOFS-3D file. "
                f"Available variables: {available}"
            )

        # Extract time series
        wse_data = ds[wse_var]

        # Handle different dimensionality
        if 'node' in wse_data.dims:
            wse_ts = wse_data.isel(node=nearest_idx)
        elif 'nSCHISM_hgrid_node' in wse_data.dims:
            wse_ts = wse_data.isel(nSCHISM_hgrid_node=nearest_idx)
        else:
            # Try the last spatial dimension
            spatial_dims = [d for d in wse_data.dims if d != 'time']
            if spatial_dims:
                wse_ts = wse_data.isel({spatial_dims[0]: nearest_idx})
            else:
                raise ValueError(
                    f"Cannot extract point data from {wse_var} "
                    f"(dims: {wse_data.dims})"
                )

        # Build DataFrame
        times = pd.to_datetime(ds['time'].values)
        wse_values_m = wse_ts.values.astype(float)

        # Filter NaN/fill values
        fill_value = -99999.0
        wse_values_m[wse_values_m < fill_value] = np.nan

        df = pd.DataFrame({
            'datetime': times,
            'wse_m': wse_values_m,
            'wse_ft': wse_values_m * CoastalBoundary.METERS_TO_FEET,
        })

        ds.close()

        # Report stats
        valid = df['wse_m'].notna()
        if valid.sum() > 0:
            logger.info(
                f"Extracted {valid.sum()} valid WSE values. "
                f"Range: {df.loc[valid, 'wse_ft'].min():.2f} to "
                f"{df.loc[valid, 'wse_ft'].max():.2f} ft NAVD88"
            )
        else:
            logger.warning("No valid WSE values extracted at this location")

        return df

    @staticmethod
    @log_call
    def generate_stage_bc(
        wse_timeseries,
        unsteady_file: Union[str, Path],
        bc_location: str,
        units: str = "feet",
        datum_adjustment_ft: float = 0.0,
    ) -> None:
        """
        Write a stage boundary condition to a HEC-RAS unsteady flow file.

        Takes a WSE time series (from extract_wse_at_point) and writes it
        as a stage hydrograph boundary condition in a HEC-RAS .u## file.

        Args:
            wse_timeseries: DataFrame with 'datetime' and 'wse_ft' (or 'wse_m')
                           columns, as returned by extract_wse_at_point().
            unsteady_file: Path to HEC-RAS unsteady flow file (.u##).
            bc_location: Boundary condition location name as defined in
                        the HEC-RAS geometry file (e.g., "Downstream").
            units: Unit system - 'feet' or 'meters'. Default 'feet'.
            datum_adjustment_ft: Additional datum offset in feet (e.g., for
                               local datum corrections). Default 0.0.

        Raises:
            FileNotFoundError: If unsteady file not found.
            ValueError: If wse_timeseries has invalid format or bc_location
                       not found in unsteady file.

        Example:
            >>> wse = CoastalBoundary.extract_wse_at_point(
            ...     "stofs_data", lat=29.35, lon=-94.77
            ... )
            >>> CoastalBoundary.generate_stage_bc(
            ...     wse_timeseries=wse,
            ...     unsteady_file="project.u01",
            ...     bc_location="Downstream",
            ...     datum_adjustment_ft=0.0
            ... )
        """
        import pandas as pd
        import numpy as np

        unsteady_file = Path(unsteady_file)
        if not unsteady_file.exists():
            raise FileNotFoundError(
                f"Unsteady flow file not found: {unsteady_file}"
            )

        # Validate DataFrame
        if not isinstance(wse_timeseries, pd.DataFrame):
            raise TypeError("wse_timeseries must be a pandas DataFrame")

        required_cols = ['datetime']
        wse_col = 'wse_ft' if units == 'feet' else 'wse_m'

        if wse_col not in wse_timeseries.columns:
            raise ValueError(
                f"wse_timeseries must have '{wse_col}' column. "
                f"Available: {list(wse_timeseries.columns)}"
            )

        if 'datetime' not in wse_timeseries.columns:
            raise ValueError(
                "wse_timeseries must have 'datetime' column"
            )

        # Get clean WSE values
        df = wse_timeseries.dropna(subset=[wse_col]).copy()

        if len(df) == 0:
            raise ValueError("No valid WSE values in time series")

        # Apply datum adjustment
        wse_values = df[wse_col].values + datum_adjustment_ft
        datetimes = pd.to_datetime(df['datetime'].values)

        # Read unsteady file
        content = unsteady_file.read_text()
        lines = content.split('\n')

        # Find the boundary condition location
        bc_found = False
        bc_line_idx = None

        for i, line in enumerate(lines):
            if f'Boundary Location=' in line and bc_location in line:
                bc_found = True
                bc_line_idx = i
                break

        if not bc_found:
            raise ValueError(
                f"Boundary condition location '{bc_location}' not found "
                f"in {unsteady_file.name}. Check geometry file for valid "
                f"boundary location names."
            )

        # Find the stage hydrograph section for this BC
        # Look for "Stage Hydrograph=" after the BC location line
        stage_start = None
        for i in range(bc_line_idx, min(bc_line_idx + 50, len(lines))):
            if 'Stage Hydrograph=' in lines[i]:
                stage_start = i
                break

        if stage_start is None:
            # Need to create stage hydrograph section
            logger.info(
                f"Creating new Stage Hydrograph section for '{bc_location}'"
            )
            # Build stage hydrograph block
            stage_block = CoastalBoundary._format_stage_hydrograph(
                datetimes, wse_values
            )

            # Insert after BC location line (after its properties block)
            insert_idx = bc_line_idx + 1
            while insert_idx < len(lines):
                if lines[insert_idx].strip() == '' or '=' in lines[insert_idx]:
                    insert_idx += 1
                else:
                    break

            lines.insert(insert_idx, stage_block)
        else:
            # Replace existing stage hydrograph data
            logger.info(
                f"Updating existing Stage Hydrograph for '{bc_location}'"
            )

            # Find the end of the existing stage data
            # Count of values is on the Stage Hydrograph= line
            num_values_line = lines[stage_start]

            # Find where data ends (next section header or blank line)
            data_end = stage_start + 1
            while data_end < len(lines):
                stripped = lines[data_end].strip()
                if (stripped == '' or
                    ('=' in stripped and not stripped[0].isdigit() and
                     not stripped.startswith('-'))):
                    break
                data_end += 1

            # Build replacement stage data
            stage_block = CoastalBoundary._format_stage_hydrograph(
                datetimes, wse_values
            )

            # Replace existing lines
            lines[stage_start:data_end] = [stage_block]

        # Write updated file
        unsteady_file.write_text('\n'.join(lines))

        logger.info(
            f"Wrote stage BC for '{bc_location}' to {unsteady_file.name}: "
            f"{len(wse_values)} values, "
            f"range {wse_values.min():.2f} to {wse_values.max():.2f} "
            f"{'ft' if units == 'feet' else 'm'} NAVD88"
        )

    @staticmethod
    def _format_stage_hydrograph(
        datetimes,
        wse_values,
    ) -> str:
        """
        Format WSE time series as HEC-RAS stage hydrograph text block.

        Args:
            datetimes: Array of datetime values.
            wse_values: Array of WSE values (feet or meters).

        Returns:
            str: Formatted text block for insertion into .u## file.
        """
        import numpy as np

        num_values = len(wse_values)

        # Format header line
        header = f"Stage Hydrograph= {num_values}"

        # Calculate interval from time series
        if len(datetimes) >= 2:
            import pandas as pd
            dt = pd.to_datetime(datetimes)
            interval_minutes = int((dt[1] - dt[0]).total_seconds() / 60)

            if interval_minutes >= 1440:
                interval_str = f"{interval_minutes // 1440}DAY"
            elif interval_minutes >= 60:
                interval_str = f"{interval_minutes // 60}HOUR"
            else:
                interval_str = f"{interval_minutes}MIN"
        else:
            interval_str = "1HOUR"

        interval_line = f"Interval={interval_str}"

        # Format values (8.2f, 10 values per line - HEC-RAS convention)
        value_lines = []
        for i in range(0, num_values, 10):
            chunk = wse_values[i:i + 10]
            formatted = ''.join(f'{v:8.2f}' for v in chunk)
            value_lines.append(formatted)

        # Combine
        parts = [header, interval_line] + value_lines
        return '\n'.join(parts)

    @staticmethod
    def get_info() -> Dict:
        """
        Return metadata about the STOFS-3D dataset.

        Returns:
            Dict: Dataset metadata including coverage, resolution,
                  update frequency, and data source URLs.

        Example:
            >>> info = CoastalBoundary.get_info()
            >>> print(f"Forecast horizon: {info['forecast_horizon']}")
        """
        return {
            "name": "STOFS-3D-Atlantic (Surge and Tide Operational Forecast System)",
            "provider": "NOAA / NOS / CO-OPS",
            "spatial_resolution": "Variable (80m nearshore to 50km offshore)",
            "temporal_resolution": "Hourly output",
            "coverage": "US Atlantic and Gulf coasts",
            "forecast_horizon": f"{CoastalBoundary.FORECAST_HOURS} hours",
            "update_frequency": "Every 6 hours (00z, 06z, 12z, 18z)",
            "format": "NetCDF (field output), GRIB2 (surface fields)",
            "datum": "NAVD88 (meters)",
            "variables": [
                "Water surface elevation (zeta/cwl)",
                "Currents (u, v)",
                "Temperature",
                "Salinity",
            ],
            "base_url": CoastalBoundary.BASE_URL,
            "documentation": (
                "https://tidesandcurrents.noaa.gov/ofs/stofs3d/stofs3d.html"
            ),
        }

    @staticmethod
    @log_call
    def check_availability(
        date: Optional[str] = None,
        cycle: Optional[int] = None,
    ) -> bool:
        """
        Check if a specific STOFS-3D forecast cycle is available on NOMADS.

        Args:
            date: Date as 'YYYY-MM-DD'. Defaults to today (UTC).
            cycle: Cycle hour (0, 6, 12, or 18). Defaults to most recent.

        Returns:
            bool: True if forecast data is available.

        Example:
            >>> if CoastalBoundary.check_availability("2024-07-15", 12):
            ...     print("12z cycle available")
        """
        _check_coastal_dependencies()
        import requests

        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        if cycle is None:
            now_utc = datetime.utcnow()
            # Latest cycle considering ~6 hour latency
            candidate = now_utc - timedelta(hours=6)
            cycle = (candidate.hour // 6) * 6

        forecast_date = datetime.strptime(date, "%Y-%m-%d")
        date_str = forecast_date.strftime("%Y%m%d")

        filename = CoastalBoundary.POINT_PATTERN.format(cycle=cycle)
        url = f"{CoastalBoundary.BASE_URL}/stofs_3d_atl.{date_str}/{filename}"

        try:
            response = requests.head(url, timeout=30, allow_redirects=True)
            available = response.status_code == 200

            if available:
                logger.debug(f"STOFS-3D {date_str} {cycle:02d}z is available")
            else:
                logger.debug(
                    f"STOFS-3D {date_str} {cycle:02d}z not available "
                    f"(HTTP {response.status_code})"
                )

            return available

        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not check STOFS-3D availability: {e}")
            return False

    @staticmethod
    def _detect_latest_cycle(date_str: str) -> int:
        """
        Detect the latest available STOFS-3D cycle for a given date.

        Args:
            date_str: Date in YYYYMMDD format.

        Returns:
            int: Latest available cycle hour (0, 6, 12, or 18).

        Raises:
            RuntimeError: If no cycle found for the given date.
        """
        import requests

        now_utc = datetime.utcnow()
        current_date_str = now_utc.strftime("%Y%m%d")

        # Try cycles from most recent to oldest
        if date_str == current_date_str:
            # Account for ~6 hour latency
            candidate = now_utc - timedelta(hours=6)
            start_cycle_idx = (candidate.hour // 6)
        else:
            start_cycle_idx = 3  # Start from 18z for past dates

        cycles_to_try = [
            CoastalBoundary.VALID_CYCLES[i % 4]
            for i in range(start_cycle_idx, start_cycle_idx - 4, -1)
        ]

        for cycle in cycles_to_try:
            filename = CoastalBoundary.POINT_PATTERN.format(cycle=cycle)
            url = (
                f"{CoastalBoundary.BASE_URL}/stofs_3d_atl.{date_str}/"
                f"{filename}"
            )

            try:
                response = requests.head(url, timeout=15, allow_redirects=True)
                if response.status_code == 200:
                    return cycle
            except requests.exceptions.RequestException:
                continue

        raise RuntimeError(
            f"No available STOFS-3D cycle found for {date_str}. "
            f"Data may not be available for this date."
        )
