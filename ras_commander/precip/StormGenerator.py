"""
StormGenerator: Generate design storm hyetographs using the Alternating Block Method.

This module provides utilities to generate design storm hyetographs using the
Alternating Block Method (Chow, Maidment, Mays 1988). The user specifies the
total precipitation depth (from Atlas 14 or other source) and the temporal
pattern is derived from DDF data.

**Key Features:**
- Flexible peak positioning (0-100%)
- User-specified total depth (NOT interpolated from DDF tables)
- Alternating Block temporal distribution
- Static class pattern (no instantiation required)

**Basic Workflow (v0.88.0+):**

    >>> from ras_commander.precip import StormGenerator
    >>>
    >>> # Download DDF data for temporal pattern (returns DataFrame)
    >>> ddf_data = StormGenerator.download_from_coordinates(29.76, -95.37)
    >>>
    >>> # Generate hyetograph with Atlas 14 total depth
    >>> hyetograph = StormGenerator.generate_hyetograph(
    ...     ddf_data=ddf_data,
    ...     total_depth_inches=17.0,  # Atlas 14 value for Houston 100-yr 24-hr
    ...     duration_hours=24,
    ...     position_percent=50  # Peak at 50% (centered)
    ... )
    >>> print(f"Total: {hyetograph['cumulative_depth'].iloc[-1]:.6f} inches")
    Total: 17.000000 inches

**Batch Generation:**

    >>> ddf_data = StormGenerator.download_from_coordinates(29.76, -95.37)
    >>> events = {
    ...     '100yr_24hr': {'total_depth_inches': 17.0, 'duration_hours': 24},
    ...     '500yr_24hr': {'total_depth_inches': 21.5, 'duration_hours': 24},
    ... }
    >>> storms = StormGenerator.generate_all(ddf_data, events, output_dir='hyetographs/')

**Note:** This method is NOT HMS-equivalent. For HMS-equivalent hyetographs,
use Atlas14Storm, FrequencyStorm, or ScsTypeStorm from hms-commander.

**Deprecation Notice:** Instance-based usage (e.g., gen = StormGenerator(...)) is
deprecated as of v0.88.0 and will be removed in v0.89.0. Use static methods instead.

References:
    - NOAA Atlas 14: https://hdsc.nws.noaa.gov/pfds/
    - Alternating Block Method: Chow, Maidment, Mays (1988), Applied Hydrology, Section 14.4
"""

import ast
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


class StormGenerator:
    """
    Generate AEP hyetographs from NOAA Atlas 14 precipitation frequency data.

    This class provides static methods to:
    - Download NOAA Atlas 14 precipitation frequency data from the HDSC API
    - Load NOAA Atlas 14 precipitation frequency CSV files
    - Interpolate depths for arbitrary durations using log-log interpolation
    - Generate hyetographs using the Alternating Block Method
    - Save hyetographs in formats compatible with HEC-RAS

    **Static Class Pattern (v0.88.0+):**
    All methods are static - call directly without instantiation.

    Example (New Static Pattern):
        >>> ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
        >>> hyeto = StormGenerator.generate_hyetograph(ddf, 17.0, 24, position_percent=50)
        >>> hyeto.to_csv('100yr_24hr_hyetograph.csv', index=False)

    Example (Deprecated Instance Pattern - will be removed in v0.89.0):
        >>> gen = StormGenerator.download_from_coordinates(29.76, -95.37)  # Returns DataFrame now
        >>> # OLD: hyeto = gen.generate_hyetograph(...)  # Instance method
        >>> # NEW: hyeto = StormGenerator.generate_hyetograph(ddf, ...)  # Static method
    """

    # Duration parsing patterns for NOAA Atlas 14 format
    DURATION_PATTERNS = [
        (re.compile(r'^(\d+)-min'), lambda x: float(x) / 60),
        (re.compile(r'^(\d+)-hr'), lambda x: float(x)),
        (re.compile(r'^(\d+)-day'), lambda x: float(x) * 24),
    ]

    # NOAA HDSC API endpoint for precipitation frequency data
    NOAA_API_URL = "https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py"

    # NOAA API Response Structure Metadata
    # The API returns unlabeled quantile arrays. These constants define the
    # row (duration) and column (return period) mappings per the NOAA Atlas 14
    # API specification. These are NOT arbitrary - they match the official
    # NOAA Atlas 14 output structure.
    #
    # Source: NOAA HDSC API documentation
    # https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py

    # Duration mapping (rows in quantiles array)
    # API returns 19 durations in this exact order:
    # 5min, 10min, 15min, 30min, 60min, 2hr, 3hr, 6hr, 12hr, 24hr, 2day, 3day, 4day, 7day, 10day, 20day, 30day, 45day, 60day
    STANDARD_DURATIONS_HOURS = [
        5/60, 10/60, 15/60, 30/60, 1, 2, 3, 6, 12, 24,
        48, 72, 96, 168, 240, 480, 720, 1080, 1440
    ]

    # Return period mapping (columns in quantiles array)
    # CRITICAL: PDS and AMS series have DIFFERENT column structures!
    # - PDS (Partial Duration Series): 10 columns, includes 2-year (AEP 50%)
    # - AMS (Annual Maximum Series): 9 columns, starts at 5-year (AEP 20%), NO 2-year!
    #
    # PDS AEP: 50%, 20%, 10%, 4%, 2%, 1%, 0.5%, 0.2%, 0.1%, 0.05%
    # PDS ARI: 2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000 years
    #
    # AMS AEP: 20%, 10%, 4%, 2%, 1%, 0.5%, 0.2%, 0.1%, 0.05%
    # AMS ARI: 5, 10, 25, 50, 100, 200, 500, 1000, 2000 years (NO 2-year!)
    STANDARD_ARI_VALUES_PDS = ['2', '5', '10', '25', '50', '100', '200', '500', '1000', '2000']
    STANDARD_ARI_VALUES_AMS = ['5', '10', '25', '50', '100', '200', '500', '1000', '2000']

    # Legacy alias for backwards compatibility (assumes PDS)
    STANDARD_ARI_VALUES = STANDARD_ARI_VALUES_PDS

    def __init__(self, csv_file: Optional[Union[str, Path]] = None):
        """
        DEPRECATED: StormGenerator is now static (v0.88.0).

        Instance-based usage will be removed in v0.89.0. Use static methods instead:

        OLD (deprecated):
            gen = StormGenerator.download_from_coordinates(lat, lon)
            hyeto = gen.generate_hyetograph(total_depth_inches=17.0, ...)

        NEW (v0.88.0+):
            ddf = StormGenerator.download_from_coordinates(lat, lon)
            hyeto = StormGenerator.generate_hyetograph(ddf_data=ddf, total_depth_inches=17.0, ...)

        Args:
            csv_file: Optional path to NOAA Atlas 14 CSV file (deprecated).
        """
        import warnings
        warnings.warn(
            "StormGenerator instance-based usage is deprecated and will be removed "
            "in v0.89.0. Use static methods instead:\n"
            "  OLD: gen = StormGenerator.download_from_coordinates(lat, lon)\n"
            "       hyeto = gen.generate_hyetograph(total_depth_inches=17.0, ...)\n"
            "  NEW: ddf = StormGenerator.download_from_coordinates(lat, lon)\n"
            "       hyeto = StormGenerator.generate_hyetograph(ddf_data=ddf, "
            "total_depth_inches=17.0, ...)",
            DeprecationWarning,
            stacklevel=2
        )
        # Support legacy usage during deprecation period
        self.data: Optional[pd.DataFrame] = None
        self.durations_hours: Optional[np.ndarray] = None
        self.ari_columns: List[str] = []
        self._api_metadata: Dict = {}

        if csv_file:
            # Load using static method
            self.data = StormGenerator.load_csv(csv_file)
            self.durations_hours = self.data['duration_hours'].values
            self.ari_columns = [c for c in self.data.columns if c != 'duration_hours']

    @staticmethod
    @log_call
    def download_from_coordinates(
        lat: float,
        lon: float,
        data: str = 'depth',
        units: str = 'english',
        series: str = 'ams',
        timeout: int = 30,
        project_folder: Optional[Union[str, Path]] = None
    ) -> pd.DataFrame:
        """
        Download NOAA Atlas 14 precipitation frequency data for a location.

        This method downloads data directly from the NOAA Hydrometeorological
        Design Studies Center (HDSC) API, eliminating the need to manually
        download CSV files from the PFDS website.

        **LLM Forward Caching Pattern**: When `project_folder` is provided, the raw
        NOAA API response is cached to `{project_folder}/NOAA_Atlas_14/` for:
        - **Verifiability**: Raw NOAA data preserved for engineering review
        - **Reproducibility**: Same data used across all analyses
        - **Speed**: Subsequent calls load from cache (no API request)
        - **Offline**: Works without internet after initial download

        Args:
            lat: Latitude in decimal degrees (positive for Northern Hemisphere)
            lon: Longitude in decimal degrees (negative for Western Hemisphere)
            data: Data type - 'depth' (inches/mm) or 'intensity' (in/hr or mm/hr)
            units: Unit system - 'english' or 'metric'
            series: Time series type - 'ams' (annual maximum, default) or 'pds' (partial duration).
                   AMS is the standard for engineering design and matches typical Atlas 14 tables.
                   PDS values are lower for the same return period (especially < 10-year events).
            timeout: Request timeout in seconds
            project_folder: Optional path to project folder for caching. If provided,
                          data is cached to {project_folder}/NOAA_Atlas_14/

        Returns:
            pd.DataFrame: DDF data with 'duration_hours' column and ARI columns.
                         DataFrame has .attrs['metadata'] containing API response metadata.

        Raises:
            ValueError: If coordinates are outside NOAA Atlas 14 coverage
            ConnectionError: If unable to connect to NOAA API
            TimeoutError: If request times out

        Example:
            >>> # Download data for Washington, DC (no caching)
            >>> ddf = StormGenerator.download_from_coordinates(38.9, -77.0)
            >>> hyeto = StormGenerator.generate_hyetograph(ddf, total_depth_inches=10.0, duration_hours=24)
            >>>
            >>> # Download with caching (LLM Forward pattern)
            >>> ddf = StormGenerator.download_from_coordinates(
            ...     lat=38.9, lon=-77.0,
            ...     project_folder="/path/to/project"
            ... )
            >>> # Data cached to /path/to/project/NOAA_Atlas_14/lat38.9_lon-77.0_depth_english_ams.json

        Note:
            NOAA Atlas 14 coverage includes most of the contiguous United States,
            but some areas (notably parts of the Western US) may not have data.
            Check https://hdsc.nws.noaa.gov/pfds/ for coverage maps.
        """
        import urllib.request
        import urllib.error
        import json

        # Check for cached data if project_folder provided
        cache_file = None
        if project_folder is not None:
            project_folder = Path(project_folder)
            cache_dir = project_folder / "NOAA_Atlas_14"
            cache_file = cache_dir / f"lat{lat}_lon{lon}_{data}_{units}_{series}.json"

            if cache_file.exists():
                logger.info(f"Loaded cached Atlas 14 data from: {cache_file}")
                try:
                    with open(cache_file, 'r') as f:
                        data_dict = json.load(f)

                    logger.info(f"Using cached Atlas 14 data for ({lat}, {lon})")

                    # Convert to DataFrame format
                    df = StormGenerator._api_data_to_dataframe(data_dict, units)

                    region = data_dict.get('region', 'Unknown')
                    logger.info(f"Downloaded Atlas 14 data for region: {region}")

                    return df
                except Exception as e:
                    logger.warning(f"Failed to load cache file, downloading fresh: {e}")

        # Build request URL
        params = {
            'lat': lat,
            'lon': lon,
            'type': 'pf',
            'data': data,
            'units': units,
            'series': series
        }
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        url = f"{StormGenerator.NOAA_API_URL}?{query_string}"

        logger.info(f"Downloading Atlas 14 data for ({lat}, {lon})...")

        try:
            # Make request
            request = urllib.request.Request(url)
            request.add_header('User-Agent', 'ras-commander/1.0')

            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read().decode('utf-8')

        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to NOAA API: {e}")
        except TimeoutError:
            raise TimeoutError(f"Request timed out after {timeout} seconds")

        # Parse the Python dict response
        try:
            # The response is Python code with variable assignments
            # We need to extract the data safely
            data_dict = StormGenerator._parse_noaa_response(content)
        except Exception as e:
            raise ValueError(f"Failed to parse NOAA API response: {e}")

        # Check for valid data
        if 'quantiles' not in data_dict:
            raise ValueError(
                f"No precipitation data available for coordinates ({lat}, {lon}). "
                "This location may be outside NOAA Atlas 14 coverage."
            )

        # Cache the data if project_folder provided
        if cache_file is not None:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, 'w') as f:
                    json.dump(data_dict, f, indent=2)
                logger.info(f"Cached Atlas 14 data to: {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to cache Atlas 14 data: {e}")

        # Convert to DataFrame format
        df = StormGenerator._api_data_to_dataframe(data_dict, units)

        region = data_dict.get('region', 'Unknown')
        logger.info(f"Downloaded Atlas 14 data for region: {region}")

        return df

    @staticmethod
    def _parse_noaa_response(content: str) -> Dict:
        """
        Parse the NOAA API response into a dictionary.

        The API returns JavaScript-style code with variable assignments
        (semicolon-terminated). We safely parse this without using eval().

        Args:
            content: Raw response content from NOAA API

        Returns:
            Dictionary containing parsed data
        """
        result = {}

        # Parse line by line to extract variable assignments
        for line in content.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                try:
                    # Split on first '=' only
                    var_name, value_str = line.split('=', 1)
                    var_name = var_name.strip()
                    value_str = value_str.strip()

                    # Remove trailing semicolon (JavaScript-style syntax from NOAA API)
                    if value_str.endswith(';'):
                        value_str = value_str[:-1].strip()

                    # Use ast.literal_eval for safe parsing
                    try:
                        value = ast.literal_eval(value_str)
                    except (ValueError, SyntaxError):
                        # Keep as string if can't parse
                        value = value_str.strip('"\'')

                    result[var_name] = value
                except Exception:
                    continue

        return result

    @staticmethod
    def _api_data_to_dataframe(data_dict: Dict, units: str) -> pd.DataFrame:
        """
        Convert parsed API response to DataFrame.

        Args:
            data_dict: Parsed dictionary from NOAA API
            units: Unit system used in request

        Returns:
            pd.DataFrame: DDF data with 'duration_hours' column and ARI columns.
                         DataFrame has .attrs['metadata'] containing API response metadata.

        Note:
            The NOAA API returns unlabeled quantile arrays. Row/column mappings
            come from STANDARD_DURATIONS_HOURS and STANDARD_ARI_VALUES_PDS/AMS,
            which match the official NOAA Atlas 14 API structure specification.

            CRITICAL: PDS and AMS series have DIFFERENT column structures!
            - PDS: 10 columns [2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000] year
            - AMS: 9 columns [5, 10, 25, 50, 100, 200, 500, 1000, 2000] year (NO 2-year!)
        """
        quantiles = data_dict.get('quantiles', [])

        if not quantiles or len(quantiles) == 0:
            raise ValueError("No quantile data in API response")

        # Build DataFrame from quantiles array
        # Rows are durations (19 standard), columns are return periods
        num_durations = len(quantiles)
        num_aris = len(quantiles[0]) if quantiles else 0

        # Use standard durations (may be fewer rows if API returns subset)
        durations = StormGenerator.STANDARD_DURATIONS_HOURS[:num_durations]

        # CRITICAL: Select correct ARI column mapping based on series type
        # The API response includes 'ser' field ('pds' or 'ams')
        series = data_dict.get('ser', 'pds').lower()

        if series == 'ams':
            # AMS has 9 columns: 5, 10, 25, 50, 100, 200, 500, 1000, 2000 year (NO 2-year!)
            ari_cols = StormGenerator.STANDARD_ARI_VALUES_AMS[:num_aris]
            logger.debug(f"Using AMS ARI mapping (9 columns, no 2-year): {ari_cols}")
        else:
            # PDS has 10 columns: 2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000 year
            ari_cols = StormGenerator.STANDARD_ARI_VALUES_PDS[:num_aris]
            logger.debug(f"Using PDS ARI mapping (10 columns): {ari_cols}")

        # Create DataFrame
        df_data = {'duration_hours': durations}
        for i, ari in enumerate(ari_cols):
            # Convert string values to float (cached JSON has strings)
            values = []
            for row in quantiles:
                if i < len(row):
                    val = row[i]
                    # Convert string to float if needed
                    if isinstance(val, str):
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            val = np.nan
                    values.append(val)
                else:
                    values.append(np.nan)
            df_data[ari] = values

        df = pd.DataFrame(df_data)

        # Store metadata in DataFrame attrs (Pandas 1.0+ feature)
        df.attrs['metadata'] = {
            'lat': data_dict.get('lat'),
            'lon': data_dict.get('lon'),
            'region': data_dict.get('region'),
            'units': units,
            'series': series,  # 'pds' or 'ams'
            'upper': data_dict.get('upper'),
            'lower': data_dict.get('lower'),
            'durations_hours': list(durations),
            'ari_columns': ari_cols,
        }

        logger.debug(f"Loaded {num_durations} durations x {num_aris} ARIs from API")

        return df

    def _load_from_api_data(self, data_dict: Dict, units: str) -> None:
        """
        Load precipitation data from parsed API response.

        Args:
            data_dict: Parsed dictionary from NOAA API
            units: Unit system used in request

        Note:
            The NOAA API returns unlabeled quantile arrays. Row/column mappings
            come from STANDARD_DURATIONS_HOURS and STANDARD_ARI_VALUES_PDS/AMS,
            which match the official NOAA Atlas 14 API structure specification.

            CRITICAL: PDS and AMS series have DIFFERENT column structures!
            - PDS: 10 columns [2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000] year
            - AMS: 9 columns [5, 10, 25, 50, 100, 200, 500, 1000, 2000] year (NO 2-year!)
        """
        quantiles = data_dict.get('quantiles', [])

        if not quantiles or len(quantiles) == 0:
            raise ValueError("No quantile data in API response")

        # Build DataFrame from quantiles array
        # Rows are durations (19 standard), columns are return periods
        num_durations = len(quantiles)
        num_aris = len(quantiles[0]) if quantiles else 0

        # Use standard durations (may be fewer rows if API returns subset)
        durations = self.STANDARD_DURATIONS_HOURS[:num_durations]

        # CRITICAL: Select correct ARI column mapping based on series type
        # The API response includes 'ser' field ('pds' or 'ams')
        series = data_dict.get('ser', 'pds').lower()

        if series == 'ams':
            # AMS has 9 columns: 5, 10, 25, 50, 100, 200, 500, 1000, 2000 year (NO 2-year!)
            ari_cols = self.STANDARD_ARI_VALUES_AMS[:num_aris]
            logger.debug(f"Using AMS ARI mapping (9 columns, no 2-year): {ari_cols}")
        else:
            # PDS has 10 columns: 2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000 year
            ari_cols = self.STANDARD_ARI_VALUES_PDS[:num_aris]
            logger.debug(f"Using PDS ARI mapping (10 columns): {ari_cols}")

        # Create DataFrame
        df_data = {'duration_hours': durations}
        for i, ari in enumerate(ari_cols):
            # Convert string values to float (cached JSON has strings)
            values = []
            for row in quantiles:
                if i < len(row):
                    val = row[i]
                    # Convert string to float if needed
                    if isinstance(val, str):
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            val = np.nan
                    values.append(val)
                else:
                    values.append(np.nan)
            df_data[ari] = values

        self.data = pd.DataFrame(df_data)
        self.durations_hours = np.array(durations)
        self.ari_columns = ari_cols

        # Store metadata (including series type for debugging)
        self._api_metadata = {
            'lat': data_dict.get('lat'),
            'lon': data_dict.get('lon'),
            'region': data_dict.get('region'),
            'units': units,
            'series': series,  # 'pds' or 'ams'
            'upper': data_dict.get('upper'),
            'lower': data_dict.get('lower'),
        }

        logger.debug(f"Loaded {num_durations} durations x {num_aris} ARIs from API")

    @staticmethod
    def parse_duration(duration_str: str) -> float:
        """
        Parse a duration string and convert to hours.

        Supports formats: "5-min", "15-min", "1-hr", "2-hr", "1-day", "2-day", etc.

        Args:
            duration_str: Duration string from NOAA Atlas 14 format

        Returns:
            Duration in hours

        Raises:
            ValueError: If duration format is not recognized

        Example:
            >>> StormGenerator.parse_duration("5-min")
            0.0833...
            >>> StormGenerator.parse_duration("2-hr")
            2.0
            >>> StormGenerator.parse_duration("1-day")
            24.0
        """
        for pattern, converter in StormGenerator.DURATION_PATTERNS:
            match = pattern.match(duration_str.strip())
            if match:
                return converter(match.group(1))

        raise ValueError(f"Unrecognized duration format: '{duration_str}'")

    @staticmethod
    @log_call
    def load_csv(csv_file: Union[str, Path]) -> pd.DataFrame:
        """
        Load NOAA Atlas 14 precipitation frequency CSV file.

        The CSV should have:
        - First column: Duration (e.g., "5-min", "1-hr", "24-hr")
        - Subsequent columns: Depths for each ARI (e.g., "1", "2", "5", "10", "25", "50", "100")

        Args:
            csv_file: Path to the NOAA Atlas 14 CSV file

        Returns:
            pd.DataFrame: DDF data with 'duration_hours' column and ARI columns.
                         DataFrame has .attrs['metadata'] containing file metadata.

        Example:
            >>> ddf = StormGenerator.load_csv('PF_Depth_English.csv')
            >>> print(ddf.columns.tolist())
            ['duration_hours', '1', '2', '5', '10', '25', '50', '100', ...]
            >>> hyeto = StormGenerator.generate_hyetograph(ddf, 17.0, 24)
        """
        csv_path = Path(csv_file)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Read CSV - NOAA format typically has header row
        df = pd.read_csv(csv_path)

        # First column should be duration
        duration_col = df.columns[0]

        # Parse durations
        df['duration_hours'] = df[duration_col].apply(StormGenerator.parse_duration)

        # Identify ARI columns (numeric column names)
        ari_columns = []
        for col in df.columns[1:]:
            if col != 'duration_hours':
                try:
                    # Try to parse as number (ARI value)
                    int(col)
                    ari_columns.append(col)
                except ValueError:
                    continue

        # Convert ARI columns to numeric, handling any text
        for col in ari_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Sort by duration
        df = df.sort_values('duration_hours').reset_index(drop=True)

        # Store metadata in DataFrame attrs
        df.attrs['metadata'] = {
            'source': 'csv',
            'file': str(csv_path),
            'durations_hours': df['duration_hours'].values.tolist(),
            'ari_columns': ari_columns,
        }

        logger.info(f"Loaded precipitation data: {len(df)} durations, ARIs: {ari_columns}")

        return df

    @staticmethod
    def _get_time_increment(total_duration_hours: float) -> float:
        """
        Determine appropriate time increment based on storm duration.

        Args:
            total_duration_hours: Total storm duration in hours

        Returns:
            Time increment in hours
        """
        if total_duration_hours <= 1:
            return 5.0 / 60.0  # 5 minutes
        elif total_duration_hours <= 6:
            return 5.0 / 60.0  # 5 minutes
        elif total_duration_hours <= 24:
            return 1.0  # 1 hour
        else:
            return 1.0  # 1 hour for longer storms

    @staticmethod
    def interpolate_depths(
        ddf_data: pd.DataFrame,
        ari: int,
        total_duration_hours: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Interpolate precipitation depths on a log-log scale.

        Uses log-log interpolation to estimate depths at time increments
        up to the total storm duration.

        Args:
            ddf_data: DDF DataFrame from download_from_coordinates() or load_csv()
            ari: Annual Recurrence Interval (e.g., 2, 10, 100)
            total_duration_hours: Total storm duration in hours

        Returns:
            Tuple of (cumulative_depths, time_hours) arrays

        Raises:
            ValueError: If data not loaded or ARI not available
        """
        if ddf_data is None or ddf_data.empty:
            raise ValueError("No data provided. Pass DDF DataFrame from download_from_coordinates() or load_csv().")

        ari_str = str(ari)
        ari_columns = [c for c in ddf_data.columns if c != 'duration_hours']
        if ari_str not in ari_columns:
            raise ValueError(f"ARI {ari} not available. Available: {ari_columns}")

        # Get time increment
        dt = StormGenerator._get_time_increment(total_duration_hours)
        t_hours = np.arange(dt, total_duration_hours + dt, dt)

        # Get source data
        source_durations = ddf_data['duration_hours'].values
        source_depths = ddf_data[ari_str].values

        # Remove any NaN values
        valid_mask = ~np.isnan(source_depths)
        source_durations = source_durations[valid_mask]
        source_depths = source_depths[valid_mask]

        # Log-log interpolation
        log_durations = np.log(source_durations)
        log_depths = np.log(source_depths)

        # Interpolate in log space
        log_t = np.log(t_hours)
        log_D = np.interp(log_t, log_durations, log_depths)

        # Convert back
        D = np.exp(log_D)

        return D, t_hours

    @staticmethod
    def compute_incremental_depths(
        cumulative_depths: np.ndarray,
        time_hours: np.ndarray
    ) -> np.ndarray:
        """
        Compute incremental precipitation depths from cumulative depths.

        Args:
            cumulative_depths: Array of cumulative depths
            time_hours: Array of corresponding times

        Returns:
            Array of incremental depths for each time interval
        """
        incremental = np.zeros(len(cumulative_depths))
        incremental[0] = cumulative_depths[0]

        for i in range(1, len(cumulative_depths)):
            incremental[i] = cumulative_depths[i] - cumulative_depths[i - 1]

        return incremental

    @staticmethod
    def _assign_alternating_block(
        sorted_depths: np.ndarray,
        max_depth: float,
        central_index: int,
        num_intervals: int
    ) -> np.ndarray:
        """
        Assign incremental depths using the Alternating Block Method.

        Places the maximum depth at the central position, then alternates
        placing the next largest depths LEFT first (odd indices), then RIGHT
        (even indices). This matches the HEC-HMS validated implementation.

        Args:
            sorted_depths: Depths sorted in descending order
            max_depth: Maximum incremental depth
            central_index: Index for peak position
            num_intervals: Total number of time intervals

        Returns:
            Hyetograph array with depths assigned to positions

        Reference:
            Chow, V.T., Maidment, D.R., Mays, L.W. (1988). Applied Hydrology.
            McGraw-Hill. Section 14.4 "Design Storms".

        Note:
            Validated against HEC-HMS 4.11 frequency storm output (Dec 2024).
            Pattern: LEFT first (odd), RIGHT (even) - matches HMS exactly.
        """
        hyetograph = np.zeros(num_intervals)
        hyetograph[central_index] = max_depth

        left_index = central_index - 1
        right_index = central_index + 1

        # Alternate placing depths: odd indices go LEFT, even indices go RIGHT
        # This matches HEC-HMS validated implementation exactly
        for i in range(len(sorted_depths)):
            depth_value = sorted_depths[i]

            if i % 2 == 0:  # Even - go left first
                if left_index >= 0:
                    hyetograph[left_index] = depth_value
                    left_index -= 1
                elif right_index < num_intervals:
                    hyetograph[right_index] = depth_value
                    right_index += 1
            else:  # Odd - go right
                if right_index < num_intervals:
                    hyetograph[right_index] = depth_value
                    right_index += 1
                elif left_index >= 0:
                    hyetograph[left_index] = depth_value
                    left_index -= 1

        return hyetograph

    @staticmethod
    @log_call
    def generate_hyetograph(
        ddf_data: pd.DataFrame,
        total_depth_inches: float,
        duration_hours: float,
        position_percent: float = 50.0,
        method: str = 'alternating_block'
    ) -> pd.DataFrame:
        """
        Generate a design storm hyetograph using the Alternating Block Method.

        The temporal pattern is derived from the DDF data, then scaled to match
        the user-specified total depth. This allows using Atlas 14 depths while
        applying the Alternating Block temporal distribution.

        Args:
            ddf_data: DDF DataFrame from download_from_coordinates() or load_csv()
            total_depth_inches: Total precipitation depth in inches. This should
                              be the Atlas 14 value for the desired AEP and duration.
            duration_hours: Storm duration in hours
            position_percent: Peak position as percentage (0-100).
                            0 = early peak, 50 = centered, 100 = late peak
            method: Hyetograph generation method. Currently only
                   'alternating_block' is supported.

        Returns:
            DataFrame with columns:
            - hour: Time in hours from storm start
            - incremental_depth: Precipitation depth for this interval (inches)
            - cumulative_depth: Cumulative precipitation depth (inches)

        Example:
            >>> ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
            >>> # Use Atlas 14 depth (17.0 inches for Houston 100-yr 24-hr)
            >>> hyeto = StormGenerator.generate_hyetograph(
            ...     ddf_data=ddf,
            ...     total_depth_inches=17.0,
            ...     duration_hours=24,
            ...     position_percent=50
            ... )
            >>> print(f"Total: {hyeto['cumulative_depth'].iloc[-1]:.6f} inches")
            Total: 17.000000 inches

        Note:
            The DDF data is used only for the temporal pattern (shape).
            The actual depths are scaled to match total_depth_inches exactly.
        """
        if ddf_data is None or ddf_data.empty:
            raise ValueError("No data provided. Pass DDF DataFrame from download_from_coordinates() or load_csv().")

        if method != 'alternating_block':
            raise ValueError(f"Unknown method: {method}. Only 'alternating_block' is supported.")

        if total_depth_inches <= 0:
            raise ValueError(f"total_depth_inches must be positive, got {total_depth_inches}")

        # Use the first available ARI column to get the temporal pattern
        # The pattern shape is similar across ARIs, we just need the relative distribution
        ari_columns = [c for c in ddf_data.columns if c != 'duration_hours']
        if not ari_columns:
            raise ValueError("No ARI columns available in data")

        pattern_ari = int(ari_columns[0])

        # Interpolate depths to get temporal pattern
        D, t_hours = StormGenerator.interpolate_depths(ddf_data, pattern_ari, duration_hours)

        # Compute incremental depths (this gives us the pattern)
        incremental = StormGenerator.compute_incremental_depths(D, t_hours)

        # Get sorted depths (descending, excluding max)
        max_depth = incremental.max()
        max_idx = incremental.argmax()
        sorted_depths = np.sort(np.delete(incremental, max_idx))[::-1]

        # Calculate central index based on position_percent
        num_intervals = len(t_hours)
        central_index = int((position_percent / 100.0) * num_intervals)
        central_index = max(0, min(central_index, num_intervals - 1))

        # Assign using alternating block
        hyetograph = StormGenerator._assign_alternating_block(
            sorted_depths, max_depth, central_index, num_intervals
        )

        # Scale the hyetograph to match total_depth_inches exactly
        pattern_total = hyetograph.sum()
        if pattern_total > 0:
            scale_factor = total_depth_inches / pattern_total
            hyetograph = hyetograph * scale_factor

        # Create DataFrame
        result = pd.DataFrame({
            'hour': t_hours,
            'incremental_depth': hyetograph,
            'cumulative_depth': np.cumsum(hyetograph)
        })

        logger.info(f"Generated {duration_hours}-hour hyetograph "
                   f"(peak at {position_percent}%, total depth: {result['cumulative_depth'].iloc[-1]:.6f} inches)")

        return result

    @staticmethod
    @log_call
    def validate_hyetograph(
        hyetograph: pd.DataFrame,
        expected_total_depth: float,
        tolerance: float = 1e-6
    ) -> bool:
        """
        Validate that hyetograph total depth matches expected value.

        Args:
            hyetograph: Hyetograph DataFrame from generate_hyetograph()
            expected_total_depth: Expected total precipitation depth in inches
            tolerance: Allowable absolute error in inches (default 1e-6)

        Returns:
            True if validation passes

        Raises:
            ValueError: If validation fails (error exceeds tolerance)

        Example:
            >>> ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
            >>> hyeto = StormGenerator.generate_hyetograph(ddf, total_depth_inches=17.0, duration_hours=24)
            >>> StormGenerator.validate_hyetograph(hyeto, expected_total_depth=17.0)
            True
        """
        if hyetograph.empty:
            raise ValueError("Empty hyetograph DataFrame")

        # Get final cumulative depth from hyetograph
        final_depth = hyetograph['cumulative_depth'].iloc[-1]

        # Calculate absolute error
        abs_error = abs(final_depth - expected_total_depth)

        if abs_error > tolerance:
            raise ValueError(
                f"Hyetograph validation failed: generated depth {final_depth:.6f} differs from "
                f"expected {expected_total_depth:.6f} by {abs_error:.9f} inches "
                f"(tolerance: {tolerance:.9f})"
            )

        logger.info(f"Validation passed: {final_depth:.6f} vs {expected_total_depth:.6f} "
                   f"(error: {abs_error:.9f} inches)")

        return True

    @staticmethod
    @log_call
    def generate_all(
        ddf_data: pd.DataFrame,
        events: Dict[str, Dict[str, float]],
        position_percent: float = 50.0,
        output_dir: Optional[Union[str, Path]] = None
    ) -> Dict[str, Union[pd.DataFrame, Path]]:
        """
        Generate hyetographs for multiple events.

        Args:
            ddf_data: DDF DataFrame from download_from_coordinates() or load_csv()
            events: Dictionary mapping event names to their parameters.
                   Each event must have 'total_depth_inches' and 'duration_hours'.
                   Example: {
                       '100yr_24hr': {'total_depth_inches': 17.0, 'duration_hours': 24},
                       '500yr_24hr': {'total_depth_inches': 21.5, 'duration_hours': 24},
                   }
            position_percent: Peak position for all storms (0-100)
            output_dir: If provided, save CSVs and return paths.
                       If None, return DataFrames.

        Returns:
            Dict mapping event names to DataFrames or Paths

        Example:
            >>> ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
            >>> events = {
            ...     '100yr_24hr': {'total_depth_inches': 17.0, 'duration_hours': 24},
            ...     '500yr_24hr': {'total_depth_inches': 21.5, 'duration_hours': 24},
            ... }
            >>> storms = StormGenerator.generate_all(ddf, events)
            >>> df_100yr = storms['100yr_24hr']
        """
        results = {}

        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

        for event_name, params in events.items():
            try:
                total_depth = params.get('total_depth_inches')
                duration = params.get('duration_hours')

                if total_depth is None or duration is None:
                    raise ValueError(f"Event '{event_name}' missing 'total_depth_inches' or 'duration_hours'")

                hyeto = StormGenerator.generate_hyetograph(
                    ddf_data=ddf_data,
                    total_depth_inches=total_depth,
                    duration_hours=duration,
                    position_percent=position_percent
                )

                if output_dir:
                    filename = f"hyetograph_{event_name}.csv"
                    filepath = output_path / filename
                    hyeto.to_csv(filepath, index=False)
                    results[event_name] = filepath
                    logger.info(f"Saved: {filepath}")
                else:
                    results[event_name] = hyeto

            except Exception as e:
                logger.error(f"Failed to generate {event_name}: {e}")
                results[event_name] = None

        return results

    @staticmethod
    @log_call
    def save_hyetograph(
        hyetograph: pd.DataFrame,
        output_path: Union[str, Path],
        format: str = 'csv'
    ) -> Path:
        """
        Save a hyetograph to file.

        Args:
            hyetograph: Hyetograph DataFrame from generate_hyetograph()
            output_path: Output file path
            format: Output format ('csv' or 'hecras')

        Returns:
            Path to saved file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == 'csv':
            hyetograph.to_csv(output_path, index=False)
        elif format == 'hecras':
            # HEC-RAS format: two columns, time and cumulative depth
            hecras_df = hyetograph[['hour', 'cumulative_depth']].copy()
            hecras_df.columns = ['Time (hr)', 'Cumulative Depth']
            hecras_df.to_csv(output_path, index=False)
        else:
            raise ValueError(f"Unknown format: {format}")

        logger.info(f"Saved hyetograph to: {output_path}")
        return output_path

    @staticmethod
    @log_call
    def plot_hyetographs(
        ddf_data: pd.DataFrame,
        events: Dict[str, Dict[str, float]],
        position_percent: float = 50.0,
        show_cumulative: bool = True,
        figsize: Tuple[float, float] = (12, 6)
    ):
        """
        Plot hyetographs for multiple events.

        Args:
            ddf_data: DDF DataFrame from download_from_coordinates() or load_csv()
            events: Dictionary mapping event names to their parameters.
                   Each event must have 'total_depth_inches' and 'duration_hours'.
                   Example: {
                       '100yr_24hr': {'total_depth_inches': 17.0, 'duration_hours': 24},
                       '500yr_24hr': {'total_depth_inches': 21.5, 'duration_hours': 24},
                   }
            position_percent: Peak position for all storms (0-100)
            show_cumulative: Include cumulative depth on secondary axis
            figsize: Figure dimensions

        Returns:
            matplotlib Figure
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for plotting. Install with: pip install matplotlib")

        fig, ax1 = plt.subplots(figsize=figsize)

        colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(events)))

        for (event_name, params), color in zip(events.items(), colors):
            total_depth = params.get('total_depth_inches')
            duration = params.get('duration_hours')

            hyeto = StormGenerator.generate_hyetograph(
                ddf_data=ddf_data,
                total_depth_inches=total_depth,
                duration_hours=duration,
                position_percent=position_percent
            )

            ax1.bar(
                hyeto['hour'],
                hyeto['incremental_depth'],
                width=hyeto['hour'].iloc[1] - hyeto['hour'].iloc[0] if len(hyeto) > 1 else 1,
                alpha=0.6,
                label=event_name,
                color=color
            )

        ax1.set_xlabel('Time (hours)')
        ax1.set_ylabel('Incremental Depth (inches)')
        ax1.set_title('Design Storm Hyetographs')
        ax1.legend(loc='upper left')

        if show_cumulative:
            ax2 = ax1.twinx()
            for (event_name, params), color in zip(events.items(), colors):
                total_depth = params.get('total_depth_inches')
                duration = params.get('duration_hours')

                hyeto = StormGenerator.generate_hyetograph(
                    ddf_data=ddf_data,
                    total_depth_inches=total_depth,
                    duration_hours=duration,
                    position_percent=position_percent
                )
                ax2.plot(
                    hyeto['hour'],
                    hyeto['cumulative_depth'],
                    '--',
                    color=color,
                    alpha=0.8
                )
            ax2.set_ylabel('Cumulative Depth (inches)')

        plt.tight_layout()
        return fig
