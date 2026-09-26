"""
STOFS-3D Coastal Boundary Integration.

Downloads NOAA STOFS-3D-Atlantic storm surge forecasts and generates
HEC-RAS stage boundary conditions from coastal water surface elevation data.

STOFS-3D (Surge and Tide Operational Forecast System, 3D) provides
operational surge and tide forecasts for the Atlantic coast.

Data source: https://nomads.ncep.noaa.gov/pub/data/nccf/com/stofs/prod/

Example:
    >>> from ras_commander.boundaries import CoastalBoundary
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
from datetime import datetime, timedelta, timezone
import warnings

from ..LoggingConfig import get_logger, log_call

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
    - **Resolution**: Variable unstructured mesh; see NOAA configuration
    - **Forecast Horizon**: Up to 96 hours, plus 24 hours of nowcast
    - **Update Frequency**: Daily at 12 UTC
    - **Format**: NetCDF (field output), GRIB2 (surface fields)
    - **Datum**: Product/version dependent; inspect source metadata. Since
      August 17, 2026, station NetCDF uses LMSL, grids xGEOID20b, SHEF MLLW.
    - **Variables**: Water surface elevation, currents, temperature, salinity

    All methods are static - do not instantiate this class.

    Example:
        >>> from ras_commander.boundaries import CoastalBoundary
        >>> wse = CoastalBoundary.extract_wse_at_point(
        ...     "stofs_data", lat=29.35, lon=-94.77
        ... )
    """

    # NOAA NOMADS base URL for STOFS-3D production data
    BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/stofs/prod"

    # STOFS-3D-Atlantic operational cycle (not the four STOFS-2D cycles).
    VALID_CYCLES = [12]

    # Forecast duration in hours
    FORECAST_HOURS = 96

    # Meters to feet conversion factor
    METERS_TO_FEET = 1.0 / 0.3048

    # STOFS-3D field output file patterns (try in order)
    # NOAA renamed files circa 2026 — try current names first, then legacy
    FIELD_PATTERNS = [
        "stofs_3d_atl.t{cycle:02d}z.fields.cwl.maxele.nc",
        "stofs_3d_atl.t{cycle:02d}z.fields.cwl.nc",
    ]
    FIELD_PATTERN = FIELD_PATTERNS[0]

    # Point output file patterns (try in order)
    POINT_PATTERNS = [
        "stofs_3d_atl.t{cycle:02d}z.points.cwl.temp.salt.vel.nc",
        "stofs_3d_atl.t{cycle:02d}z.points.cwl.nc",
    ]
    POINT_PATTERN = POINT_PATTERNS[0]

    @staticmethod
    def _validate_units(units: str) -> None:
        if units not in {'feet', 'meters'}:
            raise ValueError("units must be 'feet' or 'meters'")

    @staticmethod
    def _normalize_label(value, name):
        """Normalize optional caller labels without accepting empty evidence."""
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")
        return value.strip()

    @staticmethod
    def _source_datum(dataset, variable, supplied):
        """Read datum evidence without assuming the date/product defines it."""
        import re

        supplied = CoastalBoundary._normalize_label(supplied, 'source_datum')
        evidence = {
            f'{scope}.{key}': str(attrs[key])
            for scope, attrs in [('variable', variable.attrs), ('global', dataset.attrs)]
            for key in ('vertical_datum', 'datum', 'geospatial_vertical_datum', 'long_name', 'standard_name')
            if key in attrs
        }
        text = ' '.join(evidence.values()).lower()
        recognized = []
        for label, pattern in {
            'NAVD88': r'navd[ _-]?88',
            'LMSL': r'lmsl|local[ _]mean[ _]sea[ _]level',
            'MLLW': r'mllw|mean[ _]lower[ _]low[ _]water',
            'xGEOID20b': r'xgeoid20b',
        }.items():
            if re.search(pattern, text):
                recognized.append(label)
        if len(recognized) > 1:
            raise ValueError(f"Conflicting source datum metadata: {recognized}")
        detected = recognized[0] if recognized else None
        if supplied and detected and supplied.casefold() != detected.casefold():
            raise ValueError(f"source_datum={supplied!r} conflicts with file metadata ({detected})")
        if supplied:
            evidence['caller.source_datum'] = supplied
        datum = detected or supplied or 'unknown'
        if datum == 'unknown':
            warnings.warn("Source vertical datum is unknown; inspect the product/version and supply a verified source_datum", UserWarning, stacklevel=3)
        return datum, evidence

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
            cycle: Forecast cycle (12 UTC). Defaults to latest available.
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

        # Resolve cycle (try previous dates if today's data isn't posted yet)
        if cycle is None:
            cycle, date_str = CoastalBoundary._detect_latest_cycle_with_fallback(
                forecast_date, max_days_back=3
            )
            logger.info(f"Auto-detected latest available: {date_str} cycle {cycle:02d}z")

        if cycle not in CoastalBoundary.VALID_CYCLES:
            raise ValueError(
                f"Invalid cycle {cycle}. Must be one of {CoastalBoundary.VALID_CYCLES}."
            )

        # Determine file patterns to try (current name first, then legacy)
        if file_type == "points":
            patterns = CoastalBoundary.POINT_PATTERNS
        elif file_type == "fields":
            patterns = CoastalBoundary.FIELD_PATTERNS
        else:
            raise ValueError(
                f"Invalid file_type '{file_type}'. Must be 'points' or 'fields'."
            )

        # Find which pattern is available on NOMADS
        filename = None
        url = None
        for pattern in patterns:
            candidate = pattern.format(cycle=cycle)
            candidate_url = (
                f"{CoastalBoundary.BASE_URL}/stofs_3d_atl.{date_str}/"
                f"{candidate}"
            )
            try:
                head = requests.head(candidate_url, timeout=15, allow_redirects=True)
                if head.status_code == 200:
                    filename = candidate
                    url = candidate_url
                    break
            except requests.exceptions.RequestException:
                continue

        if filename is None:
            filename = patterns[0].format(cycle=cycle)
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
        *,
        source_datum: Optional[str] = None,
    ):
        """
        Extract water surface elevation time series at a coastal point.

        Reads STOFS-3D NetCDF output and extracts the WSE time series at
        the station/node nearest to the specified latitude/longitude. Unit
        conversion does not change the vertical datum. Peak-only maxele fields
        are not time series and cannot be used by this method.

        Args:
            stofs_dir: Directory containing STOFS-3D NetCDF files, or
                      path to a specific NetCDF file.
            lat: Latitude in decimal degrees (positive north).
            lon: Longitude in decimal degrees (negative west).
            date: Retained for compatibility; filenames do not encode dates.
                Select an exact file path and inspect its timestamps instead.
            cycle: Optional cycle to filter files (12 UTC).
            units: Preferred units, 'feet' or 'meters'. Both columns are
                retained for compatibility; the preference is stored in attrs.
            source_datum: Optional caller-verified datum label if metadata is
                absent. Must agree with any recognized source-file datum.

        Returns:
            pandas.DataFrame: Time series with columns:
                - 'datetime': Timestamp (UTC)
                - 'wse_m': Water surface elevation in meters, source datum
                - 'wse_ft': Water surface elevation in feet, source datum

            ``attrs`` retains source_file, source_variable, source_units,
            source_datum (or 'unknown'), datum_evidence, and nearest coordinates.
            No vertical datum transformation is performed.

        Raises:
            ImportError: If xarray or netCDF4 not installed.
            FileNotFoundError: If no STOFS-3D files found.
            ValueError: If coordinates are outside model domain.

        Example:
            >>> wse = CoastalBoundary.extract_wse_at_point(
            ...     "stofs_data",
            ...     lat=29.35, lon=-94.77  # Galveston Bay entrance
            ... )
            >>> print(f"Max WSE: {wse['wse_ft'].max():.2f} ft ({wse.attrs['source_datum']})")
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

        CoastalBoundary._validate_units(units)
        stofs_path = Path(stofs_dir)

        # Find the NetCDF file
        if stofs_path.is_file():
            nc_files = [stofs_path]
        else:
            nc_files = sorted(stofs_path.glob("stofs_3d_atl.*.nc"))
            if cycle is not None:
                pattern = f"stofs_3d_atl.t{cycle:02d}z.*.nc"
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

        try:
            # Find nearest point using available coordinate or data variables
            # STOFS-3D uses unstructured mesh - find nearest node
            # Check both coords and data_vars (newer files store x/y as data vars)
            all_vars = set(ds.coords.keys()) | set(ds.data_vars.keys())
            if 'x' in all_vars and 'y' in all_vars:
                x_var, y_var = 'x', 'y'
            elif 'lon' in all_vars and 'lat' in all_vars:
                x_var, y_var = 'lon', 'lat'
            elif 'longitude' in all_vars and 'latitude' in all_vars:
                x_var, y_var = 'longitude', 'latitude'
            else:
                raise ValueError(
                    f"Could not identify coordinate variables in STOFS-3D file. "
                    f"Available coords: {list(ds.coords.keys())}, "
                    f"data_vars: {list(ds.data_vars.keys())}"
                )

            # Handle negative west longitude
            x_vals = ds[x_var].values
            y_vals = ds[y_var].values

            if lon < 0 and x_vals.min() >= 0:
                lon_query = lon + 360
            else:
                lon_query = lon

            # Find nearest point -- try both orientations because some STOFS-3D
            # point files have swapped x/y for certain stations
            dist_normal = np.sqrt(
                (x_vals - lon_query) ** 2 + (y_vals - lat) ** 2
            )
            dist_swapped = np.sqrt(
                (y_vals - lon_query) ** 2 + (x_vals - lat) ** 2
            )

            min_normal = float(dist_normal.min())
            min_swapped = float(dist_swapped.min())

            if min_normal <= min_swapped:
                dist = dist_normal
            else:
                dist = dist_swapped
                logger.info("Using swapped x/y orientation (NOAA data quirk)")

            nearest_idx = int(np.argmin(dist))
            min_dist = float(dist[nearest_idx])

            if min_dist > 2.0:
                raise ValueError(
                    f"Nearest STOFS-3D point is {min_dist:.2f} degrees away from "
                    f"({lat}, {lon}). Point may be outside model domain. "
                    f"STOFS-3D covers the US Atlantic and Gulf coasts."
                )

            if min_normal <= min_swapped:
                nearest_lat = float(y_vals[nearest_idx])
                nearest_lon = float(x_vals[nearest_idx])
            else:
                nearest_lat = float(x_vals[nearest_idx])
                nearest_lon = float(y_vals[nearest_idx])

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

            if 'time' not in wse_ts.dims or wse_ts.ndim != 1:
                raise ValueError("Source must contain a WSE time series; maxele is a peak-only product")

            source_units = str(wse_data.attrs.get('units', '')).strip().lower()
            if source_units not in {'m', 'meter', 'meters', 'metre', 'metres'}:
                raise ValueError(f"Unsupported or missing source WSE units: {source_units!r}; expected meters")
            datum, evidence = CoastalBoundary._source_datum(ds, wse_data, source_datum)

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
            df.attrs.update({
                'source_file': str(nc_file.resolve()),
                'source_variable': wse_var,
                'source_units': source_units,
                'source_datum': datum,
                'datum_evidence': evidence,
                'preferred_units': units,
                'nearest_lat': nearest_lat,
                'nearest_lon': nearest_lon,
            })


        finally:
            ds.close()

        # Report stats
        valid = df['wse_m'].notna()
        if valid.sum() > 0:
            logger.info(
                f"Extracted {valid.sum()} valid WSE values. "
                f"Range: {df.loc[valid, 'wse_ft'].min():.2f} to "
                f"{df.loc[valid, 'wse_ft'].max():.2f} ft ({datum})"
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
        *,
        source_datum: Optional[str] = None,
        target_datum: Optional[str] = None,
        datum_adjustment_source: Optional[str] = None,
    ) -> None:
        """
        Write a stage boundary condition to a HEC-RAS unsteady flow file.

        Takes a WSE time series (from extract_wse_at_point) and writes it
        as a stage hydrograph boundary condition in a HEC-RAS .u## file.

        Experimental file authoring: writing a table is not hydraulic validation.
        No geodetic transformation is performed. Work on a copy and verify the
        model's datum, units, time window and boundary selection before compute.

        Args:
            wse_timeseries: DataFrame with 'datetime' and 'wse_ft' (or 'wse_m')
                           columns, as returned by extract_wse_at_point().
            unsteady_file: Path to HEC-RAS unsteady flow file (.u##).
            bc_location: Exact 2D boundary-line name (e.g., "Downstream"), or
                exact 1D river-station text when the boundary has no 2D line.
                River, reach and 2D-area names are not selectors. Surrounding
                whitespace is stripped; multiple matching boundaries raise.
            units: Unit system - 'feet' or 'meters'. Default 'feet'.
            datum_adjustment_ft: Additional datum offset in feet (e.g., for
                local datum corrections), always added to source elevations.
                Converted to meters when units='meters'. Default 0.0.
            source_datum: Caller-verified source label, or inherited from
                wse_timeseries.attrs['source_datum'].
            target_datum: Verified model datum. If omitted, legacy calls are
                allowed with a warning; the output datum remains unverified.
            datum_adjustment_source: Citation/description of the independently
                established local offset. Required for different known datums,
                including an explicitly verified zero offset. Logged as caller
                provenance; the library cannot validate its accuracy.

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

        CoastalBoundary._validate_units(units)
        bc_location = CoastalBoundary._normalize_label(bc_location, 'bc_location')
        if bc_location is None:
            raise ValueError("bc_location must be a nonempty string")
        source_datum = CoastalBoundary._normalize_label(source_datum, 'source_datum')
        target_datum = CoastalBoundary._normalize_label(target_datum, 'target_datum')
        datum_adjustment_source = CoastalBoundary._normalize_label(
            datum_adjustment_source, 'datum_adjustment_source'
        )
        if target_datum is not None and target_datum.casefold() == 'unknown':
            raise ValueError("target_datum must identify a known datum")
        if not np.isfinite(datum_adjustment_ft):
            raise ValueError("datum_adjustment_ft must be finite")
        unsteady_file = Path(unsteady_file)
        if not unsteady_file.exists():
            raise FileNotFoundError(
                f"Unsteady flow file not found: {unsteady_file}"
            )

        # Validate DataFrame
        if not isinstance(wse_timeseries, pd.DataFrame):
            raise TypeError("wse_timeseries must be a pandas DataFrame")

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

        # Never silently compress a time series by dropping missing samples.
        df = wse_timeseries.copy()

        if len(df) == 0:
            raise ValueError("No valid WSE values in time series")

        inherited_datum = CoastalBoundary._normalize_label(
            wse_timeseries.attrs.get('source_datum'), "wse_timeseries.attrs['source_datum']"
        ) or 'unknown'
        if source_datum and inherited_datum.casefold() != 'unknown' and source_datum.casefold() != inherited_datum.casefold():
            raise ValueError("source_datum conflicts with time-series metadata")
        resolved_source = source_datum or inherited_datum
        if target_datum:
            if resolved_source.casefold() == 'unknown':
                raise ValueError("A known source_datum is required when target_datum is specified")
            if target_datum.casefold() != resolved_source.casefold() and not datum_adjustment_source:
                raise ValueError("Different source/target datums require datum_adjustment_source for a verified local offset")
        else:
            warnings.warn("Target vertical datum is unverified; supply target_datum before using this boundary in a model", UserWarning, stacklevel=2)

        # The public offset is ALWAYS feet, regardless of output units.
        offset = datum_adjustment_ft if units == 'feet' else datum_adjustment_ft / CoastalBoundary.METERS_TO_FEET
        wse_values = df[wse_col].to_numpy(dtype=float) + offset
        datetimes = pd.to_datetime(df['datetime'].values)
        if not np.isfinite(wse_values).all():
            raise ValueError("WSE values must be finite; missing samples require explicit treatment")
        stage_block = CoastalBoundary._format_stage_hydrograph(datetimes, wse_values)

        # Preserve native bytes and newline style. RAS files may use UTF-8 or
        # legacy Windows cp1252; latin-1 is a lossless fallback for other bytes.
        raw_content = unsteady_file.read_bytes()
        for encoding in ('utf-8', 'cp1252', 'latin-1'):
            try:
                content = raw_content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        newline = '\r\n' if '\r\n' in content else '\n'
        lines = content.splitlines()

        # Find the boundary condition location
        bc_found = False
        bc_line_idx = None

        matches = []
        for i, line in enumerate(lines):
            if not line.startswith('Boundary Location='):
                continue
            fields = [field.strip() for field in line.split('=', 1)[1].split(',')]
            # Native positions: 2D BC line is field 7; 1D RS is field 2.
            # Never match blank fields, river/reach names, or the 2D area.
            if len(fields) > 7 and fields[7]:
                selector = fields[7]
            elif len(fields) > 2 and fields[0] and fields[1] and fields[2]:
                selector = fields[2]
            else:
                continue
            if bc_location == selector:
                matches.append(i)
        if len(matches) > 1:
            raise ValueError(f"Boundary location {bc_location!r} is ambiguous")
        if matches:
            bc_found, bc_line_idx = True, matches[0]

        if not bc_found:
            raise ValueError(
                f"Boundary condition location '{bc_location}' not found "
                f"in {unsteady_file.name}. Check geometry file for valid "
                f"boundary location names."
            )

        # Find the stage hydrograph section for this BC
        # Look for "Stage Hydrograph=" after the BC location line
        stage_start = None
        bc_end = next((i for i in range(bc_line_idx + 1, len(lines))
                       if lines[i].startswith('Boundary Location=')), len(lines))
        for i in range(bc_line_idx, bc_end):
            if 'Stage Hydrograph=' in lines[i]:
                stage_start = i
                break

        if any(line.strip() == 'Use DSS=True' for line in lines[bc_line_idx:bc_end]):
            raise ValueError("Target uses DSS; configure an inline stage boundary with RasUnsteady first")
        if stage_start is None:
            raise ValueError("Target boundary must already contain a Stage Hydrograph; use RasUnsteady to configure its type first")
        else:
            # Replace existing stage hydrograph data
            logger.info(
                f"Updating existing Stage Hydrograph for '{bc_location}'"
            )

            # Include the Interval= line BEFORE Stage Hydrograph= in
            # the replacement range so we don't leave a stale one behind.
            replace_start = stage_start
            if (stage_start > 0
                    and lines[stage_start - 1].strip().startswith('Interval=')):
                replace_start = stage_start - 1

            # Find where data ends: skip any Interval= line that follows
            # Stage Hydrograph= (legacy format), then skip numeric value
            # lines; stop at the next keyword line or end of file.
            data_end = stage_start + 1
            # Skip Interval= line immediately after Stage Hydrograph= header
            if (data_end < len(lines)
                    and lines[data_end].strip().startswith('Interval=')):
                data_end += 1
            # Skip numeric value lines (start with digit, space, '-', or '.')
            while data_end < bc_end:
                stripped = lines[data_end].strip()
                if stripped and stripped[0].isalpha():
                    break  # next keyword line ends this section
                data_end += 1

            # Build replacement stage data
            stage_block = CoastalBoundary._format_stage_hydrograph(
                datetimes, wse_values
            )

            # Replace existing lines (including preceding Interval=)
            lines[replace_start:data_end] = stage_block.splitlines()

        # Preserve the original LF/CRLF style and terminal-newline state.
        trailing_newline = newline if content.endswith('\n') else ''
        unsteady_file.write_bytes((newline.join(lines) + trailing_newline).encode(encoding))

        logger.info(
            f"Wrote stage BC for '{bc_location}' to {unsteady_file.name}: "
            f"{len(wse_values)} values, "
            f"range {wse_values.min():.2f} to {wse_values.max():.2f} "
            f"{'ft' if units == 'feet' else 'm'} (target datum: {target_datum or 'unverified'})"
        )
        logger.info(
            f"Source datum: {resolved_source}; additive offset: {datum_adjustment_ft} ft; "
            f"offset evidence: {datum_adjustment_source or 'not supplied'}"
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

        # Inline tables require a strictly regular, positive whole-minute interval.
        if len(datetimes) >= 2:
            import pandas as pd
            dt = pd.to_datetime(datetimes)
            intervals = np.diff(dt.to_numpy(dtype='datetime64[ns]').astype('int64'))
            minute_ns = 60 * 1_000_000_000
            if dt.isna().any() or intervals[0] <= 0 or not np.all(intervals == intervals[0]) or intervals[0] % minute_ns:
                raise ValueError("Times must be valid, increasing, regular, whole-minute timestamps")
            interval_minutes = int(intervals[0] // minute_ns)

            if interval_minutes % 1440 == 0:
                interval_str = f"{interval_minutes // 1440}DAY"
            elif interval_minutes % 60 == 0:
                interval_str = f"{interval_minutes // 60}HOUR"
            else:
                interval_str = f"{interval_minutes}MIN"
        else:
            raise ValueError("At least two timestamps are required to determine the interval")

        interval_line = f"Interval={interval_str}"

        # Format values (8.2f, 10 values per line - HEC-RAS convention)
        value_lines = []
        for i in range(0, num_values, 10):
            chunk = wse_values[i:i + 10]
            fields = [f'{v:8.2f}' for v in chunk]
            if any(len(field) != 8 for field in fields):
                raise ValueError("WSE value exceeds the native 8.2f field width after rounding")
            formatted = ''.join(fields)
            value_lines.append(formatted)

        # Combine: Interval= BEFORE Stage Hydrograph= (HEC-RAS format)
        parts = [interval_line, header] + value_lines
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
            "spatial_resolution": "Variable unstructured mesh; see NOAA configuration",
            "temporal_resolution": "6-minute station output; hourly gridded snapshots",
            "coverage": "US Atlantic and Gulf coasts",
            "forecast_horizon": f"{CoastalBoundary.FORECAST_HOURS} hours",
            "nowcast_horizon": "24 hours",
            "update_frequency": "Daily at 12 UTC",
            "format": "NetCDF (field output), GRIB2 (surface fields)",
            "datum": "Product/version dependent; inspect source metadata",
            "current_datums": {"station_netcdf": "LMSL", "grids": "xGEOID20b", "station_shef": "MLLW"},
            "datum_effective_from": "2026-08-17T12:00:00Z (STOFS v3.1)",
            "stage_authoring_status": "experimental; no automatic vertical datum transformation",
            "variables": [
                "Water surface elevation (zeta/cwl)",
                "Currents (u, v)",
                "Temperature",
                "Salinity",
            ],
            "base_url": CoastalBoundary.BASE_URL,
            "documentation": (
                "https://polar.ncep.noaa.gov/estofs/atl.htm"
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
            cycle: Cycle hour (12 UTC). Defaults to latest available within three days.

        Returns:
            bool: True if forecast data is available.

        Example:
            >>> if CoastalBoundary.check_availability("2024-07-15", 12):
            ...     print("12z cycle available")
        """
        _check_coastal_dependencies()
        import requests

        if cycle is not None and cycle not in CoastalBoundary.VALID_CYCLES:
            raise ValueError(f"Invalid cycle {cycle}; STOFS-3D-Atlantic runs at 12 UTC")
        if cycle is None:
            start = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now(timezone.utc)
            try:
                CoastalBoundary._detect_latest_cycle_with_fallback(start, max_days_back=0 if date else 3)
                return True
            except RuntimeError:
                return False
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
    def _detect_latest_cycle_with_fallback(
        forecast_date: datetime, max_days_back: int = 3
    ) -> tuple:
        """
        Detect the latest available STOFS-3D cycle, falling back to
        previous dates if today's data isn't posted yet.

        NOMADS retains only ~2 days of STOFS-3D data. When auto-detecting,
        try today first, then yesterday, etc.

        Args:
            forecast_date: Starting date to search from.
            max_days_back: Maximum number of days to search backward.

        Returns:
            tuple: (cycle_hour, date_str) for the latest available data.

        Raises:
            RuntimeError: If no cycle found within the search window.
        """
        import requests

        for days_back in range(max_days_back + 1):
            check_date = forecast_date - timedelta(days=days_back)
            date_str = check_date.strftime("%Y%m%d")

            cycles_to_try = sorted(CoastalBoundary.VALID_CYCLES, reverse=True)

            for cycle in cycles_to_try:
                for pattern in CoastalBoundary.POINT_PATTERNS:
                    filename = pattern.format(cycle=cycle)
                    url = (
                        f"{CoastalBoundary.BASE_URL}/stofs_3d_atl.{date_str}/"
                        f"{filename}"
                    )

                    try:
                        response = requests.head(url, timeout=15, allow_redirects=True)
                        if response.status_code == 200:
                            if days_back > 0:
                                logger.info(
                                    f"No data for {forecast_date.strftime('%Y%m%d')}, "
                                    f"using {date_str} instead"
                                )
                            return cycle, date_str
                    except requests.exceptions.RequestException:
                        continue

        raise RuntimeError(
            f"No available STOFS-3D cycle found within {max_days_back} days of "
            f"{forecast_date.strftime('%Y-%m-%d')}. NOMADS may be unavailable."
        )

    @staticmethod
    def _detect_latest_cycle(date_str: str) -> int:
        """
        Detect the latest available STOFS-3D cycle for a given date.

        Args:
            date_str: Date in YYYYMMDD format.

        Returns:
            int: Latest available cycle hour (12 UTC).

        Raises:
            RuntimeError: If no cycle found for the given date.
        """
        import requests

        cycles_to_try = sorted(CoastalBoundary.VALID_CYCLES, reverse=True)

        for cycle in cycles_to_try:
            for pattern in CoastalBoundary.POINT_PATTERNS:
                filename = pattern.format(cycle=cycle)
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
