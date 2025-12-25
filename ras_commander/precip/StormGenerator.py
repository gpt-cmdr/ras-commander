"""
StormGenerator: Generate design storm hyetographs from NOAA Atlas 14 data.

This module provides utilities to generate design storm hyetographs using the
Alternating Block Method from NOAA Atlas 14 precipitation frequency data.

Two workflows are supported:

**Workflow 1: Direct Download (Recommended)**
Download precipitation data directly from NOAA without manual file downloads:

    >>> from ras_commander.precip import StormGenerator
    >>>
    >>> # Download data for a location (lat, lon)
    >>> gen = StormGenerator.download_from_coordinates(38.9, -77.0)
    >>>
    >>> # Generate hyetograph
    >>> hyetograph = gen.generate_hyetograph(ari=100, duration_hours=24)

**Workflow 2: From CSV File**
Use previously downloaded CSV files from the NOAA PFDS website:

    >>> gen = StormGenerator('PF_Depth_English_Davis_CA.csv')
    >>> hyetograph = gen.generate_hyetograph(ari=100, duration_hours=24)

**Batch Generation:**

    >>> # Generate all combinations and save to files
    >>> files = gen.generate_all(
    ...     aep_events=[10, 50, 100],
    ...     durations=[6, 12, 24],
    ...     output_dir='hyetographs/'
    ... )

References:
    - NOAA Atlas 14: https://hdsc.nws.noaa.gov/pfds/
    - NOAA HDSC API: https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py
    - Alternating Block Method: Chow, Maidment, Mays (1988)
"""

import ast
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class StormGenerator:
    """
    Generate AEP hyetographs from NOAA Atlas 14 precipitation frequency data.

    This class provides methods to:
    - Load NOAA Atlas 14 precipitation frequency CSV files
    - Interpolate depths for arbitrary durations using log-log interpolation
    - Generate hyetographs using the Alternating Block Method
    - Save hyetographs in formats compatible with HEC-RAS

    Attributes:
        data (pd.DataFrame): The loaded precipitation frequency data
        durations_hours (np.ndarray): Available durations in hours
        ari_columns (List[str]): Available ARI column names

    Example:
        >>> gen = StormGenerator('Atlas14_data.csv')
        >>> hyeto = gen.generate_hyetograph(100, 24, position_percent=50)
        >>> hyeto.to_csv('100yr_24hr_hyetograph.csv', index=False)
    """

    # Duration parsing patterns for NOAA Atlas 14 format
    DURATION_PATTERNS = [
        (re.compile(r'^(\d+)-min'), lambda x: float(x) / 60),
        (re.compile(r'^(\d+)-hr'), lambda x: float(x)),
        (re.compile(r'^(\d+)-day'), lambda x: float(x) * 24),
    ]

    # NOAA HDSC API endpoint for precipitation frequency data
    NOAA_API_URL = "https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py"

    # Standard durations in hours (matching NOAA Atlas 14 output order)
    # 5min, 10min, 15min, 30min, 60min, 2hr, 3hr, 6hr, 12hr, 24hr, 2day, 3day, 4day, 7day, 10day, 20day, 30day, 45day, 60day
    STANDARD_DURATIONS_HOURS = [
        5/60, 10/60, 15/60, 30/60, 1, 2, 3, 6, 12, 24,
        48, 72, 96, 168, 240, 480, 720, 1080, 1440
    ]

    # Standard ARI values (return periods in years)
    # NOAA Atlas 14 columns are ordered by AEP (50%, 20%, 10%, 4%, 2%, 1%, 0.5%, 0.2%, 0.1%, 0.05%)
    # Standard AEP-to-ARI conversion: ARI = 1/AEP
    # So columns correspond to: 2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000 year return periods
    STANDARD_ARI_VALUES = ['2', '5', '10', '25', '50', '100', '200', '500', '1000', '2000']

    def __init__(self, csv_file: Optional[Union[str, Path]] = None):
        """
        Initialize StormGenerator.

        Args:
            csv_file: Optional path to NOAA Atlas 14 CSV file.
                     If provided, loads the data immediately.
        """
        self.data: Optional[pd.DataFrame] = None
        self.durations_hours: Optional[np.ndarray] = None
        self.ari_columns: List[str] = []

        if csv_file:
            self.load_csv(csv_file)

    @classmethod
    def download_from_coordinates(
        cls,
        lat: float,
        lon: float,
        data: str = 'depth',
        units: str = 'english',
        series: str = 'pds',
        timeout: int = 30,
        project_folder: Optional[Union[str, Path]] = None
    ) -> 'StormGenerator':
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
            series: Time series type - 'pds' (partial duration) or 'ams' (annual maximum)
            timeout: Request timeout in seconds
            project_folder: Optional path to project folder for caching. If provided,
                          data is cached to {project_folder}/NOAA_Atlas_14/

        Returns:
            StormGenerator instance with data loaded and ready for hyetograph generation

        Raises:
            ValueError: If coordinates are outside NOAA Atlas 14 coverage
            ConnectionError: If unable to connect to NOAA API
            TimeoutError: If request times out

        Example:
            >>> # Download data for Washington, DC (no caching)
            >>> gen = StormGenerator.download_from_coordinates(38.9, -77.0)
            >>> hyeto = gen.generate_hyetograph(ari=100, duration_hours=24)
            >>>
            >>> # Download with caching (LLM Forward pattern)
            >>> gen = StormGenerator.download_from_coordinates(
            ...     lat=38.9, lon=-77.0,
            ...     project_folder="/path/to/project"
            ... )
            >>> # Data cached to /path/to/project/NOAA_Atlas_14/lat38.9_lon-77.0_depth_english_pds.json

        Note:
            NOAA Atlas 14 coverage includes most of the contiguous United States,
            but some areas (notably parts of the Western US) may not have data.
            Check https://hdsc.nws.noaa.gov/pfds/ for coverage maps.
        """
        import urllib.request
        import urllib.error
        import ast
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
                    instance = cls()
                    instance._load_from_api_data(data_dict, units)

                    region = data_dict.get('region', 'Unknown')
                    logger.info(f"Downloaded Atlas 14 data for region: {region}")

                    return instance
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
        url = f"{cls.NOAA_API_URL}?{query_string}"

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
            data_dict = cls._parse_noaa_response(content)
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
        instance = cls()
        instance._load_from_api_data(data_dict, units)

        region = data_dict.get('region', 'Unknown')
        logger.info(f"Downloaded Atlas 14 data for region: {region}")

        return instance

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

    def _load_from_api_data(self, data_dict: Dict, units: str) -> None:
        """
        Load precipitation data from parsed API response.

        Args:
            data_dict: Parsed dictionary from NOAA API
            units: Unit system used in request
        """
        quantiles = data_dict.get('quantiles', [])

        if not quantiles or len(quantiles) == 0:
            raise ValueError("No quantile data in API response")

        # Build DataFrame from quantiles array
        # Rows are durations (19 standard), columns are return periods (10 standard)
        num_durations = len(quantiles)
        num_aris = len(quantiles[0]) if quantiles else 0

        # Use standard durations (may be fewer rows if API returns subset)
        durations = self.STANDARD_DURATIONS_HOURS[:num_durations]
        ari_cols = self.STANDARD_ARI_VALUES[:num_aris]

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

        # Store metadata
        self._api_metadata = {
            'lat': data_dict.get('lat'),
            'lon': data_dict.get('lon'),
            'region': data_dict.get('region'),
            'units': units,
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

    def load_csv(self, csv_file: Union[str, Path]) -> pd.DataFrame:
        """
        Load NOAA Atlas 14 precipitation frequency CSV file.

        The CSV should have:
        - First column: Duration (e.g., "5-min", "1-hr", "24-hr")
        - Subsequent columns: Depths for each ARI (e.g., "1", "2", "5", "10", "25", "50", "100")

        Args:
            csv_file: Path to the NOAA Atlas 14 CSV file

        Returns:
            DataFrame with parsed precipitation data

        Example:
            >>> gen = StormGenerator()
            >>> data = gen.load_csv('PF_Depth_English.csv')
            >>> print(data.columns.tolist())
            ['duration_hours', '1', '2', '5', '10', '25', '50', '100', ...]
        """
        csv_path = Path(csv_file)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Read CSV - NOAA format typically has header row
        df = pd.read_csv(csv_path)

        # First column should be duration
        duration_col = df.columns[0]

        # Parse durations
        df['duration_hours'] = df[duration_col].apply(self.parse_duration)

        # Identify ARI columns (numeric column names)
        self.ari_columns = []
        for col in df.columns[1:]:
            if col != 'duration_hours':
                try:
                    # Try to parse as number (ARI value)
                    int(col)
                    self.ari_columns.append(col)
                except ValueError:
                    continue

        # Convert ARI columns to numeric, handling any text
        for col in self.ari_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Sort by duration
        df = df.sort_values('duration_hours').reset_index(drop=True)

        self.data = df
        self.durations_hours = df['duration_hours'].values

        logger.info(f"Loaded precipitation data: {len(df)} durations, ARIs: {self.ari_columns}")

        return df

    def _get_time_increment(self, total_duration_hours: float) -> float:
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

    def interpolate_depths(
        self,
        ari: int,
        total_duration_hours: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Interpolate precipitation depths on a log-log scale.

        Uses log-log interpolation to estimate depths at time increments
        up to the total storm duration.

        Args:
            ari: Annual Recurrence Interval (e.g., 2, 10, 100)
            total_duration_hours: Total storm duration in hours

        Returns:
            Tuple of (cumulative_depths, time_hours) arrays

        Raises:
            ValueError: If data not loaded or ARI not available
        """
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        ari_str = str(ari)
        if ari_str not in self.ari_columns:
            raise ValueError(f"ARI {ari} not available. Available: {self.ari_columns}")

        # Get time increment
        dt = self._get_time_increment(total_duration_hours)
        t_hours = np.arange(dt, total_duration_hours + dt, dt)

        # Get source data
        source_durations = self.durations_hours
        source_depths = self.data[ari_str].values

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

    def compute_incremental_depths(
        self,
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

    def _assign_alternating_block(
        self,
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

    def generate_hyetograph(
        self,
        ari: int,
        duration_hours: float,
        position_percent: float = 50.0,
        method: str = 'alternating_block'
    ) -> pd.DataFrame:
        """
        Generate a design storm hyetograph.

        Uses the Alternating Block Method to create a hyetograph from
        precipitation frequency data.

        Args:
            ari: Annual Recurrence Interval in years (e.g., 2, 10, 100)
            duration_hours: Storm duration in hours
            position_percent: Peak position as percentage (0-100).
                            0 = early peak, 50 = centered, 100 = late peak
            method: Hyetograph generation method. Currently only
                   'alternating_block' is supported.

        Returns:
            DataFrame with columns:
            - hour: Time in hours from storm start
            - incremental_depth: Precipitation depth for this interval
            - cumulative_depth: Cumulative precipitation depth

        Example:
            >>> gen = StormGenerator('Atlas14.csv')
            >>> hyeto = gen.generate_hyetograph(100, 24, position_percent=50)
            >>> print(hyeto.head())
               hour  incremental_depth  cumulative_depth
            0   1.0              0.123             0.123
            1   2.0              0.156             0.279
            ...
        """
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        if method != 'alternating_block':
            raise ValueError(f"Unknown method: {method}. Only 'alternating_block' is supported.")

        # Interpolate depths
        D, t_hours = self.interpolate_depths(ari, duration_hours)

        # Compute incremental depths
        incremental = self.compute_incremental_depths(D, t_hours)

        # Get sorted depths (descending, excluding max)
        max_depth = incremental.max()
        max_idx = incremental.argmax()
        sorted_depths = np.sort(np.delete(incremental, max_idx))[::-1]

        # Calculate central index based on position_percent
        # This matches HEC-HMS validated implementation: peak_index = int((peak_position/100) * num_intervals)
        num_intervals = len(t_hours)
        central_index = int((position_percent / 100.0) * num_intervals)
        central_index = max(0, min(central_index, num_intervals - 1))

        # Assign using alternating block
        hyetograph = self._assign_alternating_block(
            sorted_depths, max_depth, central_index, num_intervals
        )

        # Create DataFrame
        result = pd.DataFrame({
            'hour': t_hours,
            'incremental_depth': hyetograph,
            'cumulative_depth': np.cumsum(hyetograph)
        })

        logger.info(f"Generated {ari}-year, {duration_hours}-hour hyetograph "
                   f"(peak at {position_percent}%, total depth: {result['cumulative_depth'].iloc[-1]:.3f})")

        return result

    def validate_hyetograph(
        self,
        hyetograph: pd.DataFrame,
        ari: int,
        duration_hours: float,
        tolerance: float = 0.01
    ) -> bool:
        """
        Validate generated hyetograph against Atlas 14 total depth.

        The final cumulative depth should match the Atlas 14 total depth
        for the storm duration within the specified tolerance.

        This validation method matches the HEC-HMS verified implementation
        to ensure hyetographs are generated correctly.

        Args:
            hyetograph: Hyetograph DataFrame from generate_hyetograph()
            ari: Annual Recurrence Interval in years (e.g., 100)
            duration_hours: Storm duration in hours (e.g., 24)
            tolerance: Allowable relative error (default 1%)

        Returns:
            True if validation passes

        Raises:
            ValueError: If validation fails (relative error exceeds tolerance)

        Example:
            >>> gen = StormGenerator.download_from_coordinates(38.9, -77.0)
            >>> hyeto = gen.generate_hyetograph(100, 24)
            >>> gen.validate_hyetograph(hyeto, 100, 24)
            True

        Note:
            Validated against HEC-HMS 4.11 frequency storm output (Dec 2024).
        """
        if hyetograph.empty:
            raise ValueError("Empty hyetograph DataFrame")

        # Get final cumulative depth from hyetograph
        final_depth = hyetograph['cumulative_depth'].iloc[-1]

        # Get expected Atlas 14 depth for this ARI and duration
        ari_str = str(ari)
        if ari_str not in self.ari_columns:
            raise ValueError(f"ARI {ari} not available for validation. Available: {self.ari_columns}")

        # Interpolate expected depth for exact duration
        expected_depths, _ = self.interpolate_depths(ari, duration_hours)
        expected_depth = expected_depths[-1]  # Final cumulative depth from Atlas 14

        # Calculate relative error
        relative_error = abs(final_depth - expected_depth) / expected_depth

        if relative_error > tolerance:
            raise ValueError(
                f"Hyetograph validation failed: generated depth {final_depth:.3f} differs from "
                f"Atlas 14 total {expected_depth:.3f} by {relative_error*100:.2f}% "
                f"(tolerance: {tolerance*100:.1f}%)"
            )

        logger.info(f"Validation passed: {final_depth:.3f} vs {expected_depth:.3f} "
                   f"({relative_error*100:.2f}% error, tolerance: {tolerance*100:.1f}%)")

        return True

    def generate_all(
        self,
        aep_events: List[int],
        durations: List[float],
        position_percent: float = 50.0,
        output_dir: Optional[Union[str, Path]] = None
    ) -> Dict[int, Dict[float, Union[pd.DataFrame, Path]]]:
        """
        Generate hyetographs for all ARI/duration combinations.

        Args:
            aep_events: List of ARIs (e.g., [2, 5, 10, 25, 50, 100])
            durations: List of durations in hours (e.g., [6, 12, 24])
            position_percent: Peak position for all storms
            output_dir: If provided, save CSVs and return paths.
                       If None, return DataFrames.

        Returns:
            Nested dict: {ari: {duration: DataFrame or Path}}

        Example:
            >>> gen = StormGenerator('Atlas14.csv')
            >>> # Get DataFrames
            >>> storms = gen.generate_all([10, 100], [24])
            >>> df_100yr = storms[100][24]
            >>>
            >>> # Save to files
            >>> files = gen.generate_all([10, 100], [24], output_dir='storms/')
            >>> print(files[100][24])  # Path to saved file
        """
        results = {}

        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

        for ari in aep_events:
            results[ari] = {}
            for duration in durations:
                try:
                    hyeto = self.generate_hyetograph(
                        ari=ari,
                        duration_hours=duration,
                        position_percent=position_percent
                    )

                    if output_dir:
                        filename = f"hyetograph_{ari}yr_{int(duration)}hr.csv"
                        filepath = output_path / filename
                        hyeto.to_csv(filepath, index=False)
                        results[ari][duration] = filepath
                        logger.info(f"Saved: {filepath}")
                    else:
                        results[ari][duration] = hyeto

                except Exception as e:
                    logger.error(f"Failed to generate {ari}-year, {duration}-hour: {e}")
                    results[ari][duration] = None

        return results

    def save_hyetograph(
        self,
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

    def plot_hyetographs(
        self,
        aep_events: List[int],
        duration_hours: float,
        position_percent: float = 50.0,
        show_cumulative: bool = True,
        figsize: Tuple[float, float] = (12, 6)
    ):
        """
        Plot hyetographs for multiple AEP events.

        Args:
            aep_events: List of ARIs to plot
            duration_hours: Storm duration for all events
            position_percent: Peak position
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

        colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(aep_events)))

        for ari, color in zip(aep_events, colors):
            hyeto = self.generate_hyetograph(ari, duration_hours, position_percent)

            ax1.bar(
                hyeto['hour'],
                hyeto['incremental_depth'],
                width=hyeto['hour'].iloc[1] - hyeto['hour'].iloc[0] if len(hyeto) > 1 else 1,
                alpha=0.6,
                label=f'{ari}-year',
                color=color
            )

        ax1.set_xlabel('Time (hours)')
        ax1.set_ylabel('Incremental Depth')
        ax1.set_title(f'{duration_hours}-hour Design Storm Hyetographs')
        ax1.legend(loc='upper left')

        if show_cumulative:
            ax2 = ax1.twinx()
            for ari, color in zip(aep_events, colors):
                hyeto = self.generate_hyetograph(ari, duration_hours, position_percent)
                ax2.plot(
                    hyeto['hour'],
                    hyeto['cumulative_depth'],
                    '--',
                    color=color,
                    alpha=0.8
                )
            ax2.set_ylabel('Cumulative Depth')

        plt.tight_layout()
        return fig
