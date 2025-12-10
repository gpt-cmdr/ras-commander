"""
RasUsgsFileIo - File I/O operations for USGS gauge data management.

This module provides file management utilities for caching USGS gauge data,
validation results, and metadata within HEC-RAS project structures.

Folder Structure:
    project_root/
        gauge_data/
            raw/        - Raw USGS data downloads
            processed/  - Validation results and processed data
            metadata/   - Site metadata and configuration

Functions:
    get_gauge_data_dir():
        Creates and returns path to gauge_data directory structure.
    cache_gauge_data():
        Save retrieved USGS data to standardized CSV format.
    load_cached_gauge_data():
        Load previously cached USGS data from CSV.
    get_cache_filename():
        Generate standardized filename for cached data.
    save_validation_results():
        Save validation metrics and aligned data references.

Example:
    >>> from ras_commander.usgs import get_gauge_data_dir, cache_gauge_data
    >>>
    >>> # Get/create gauge data directory
    >>> gauge_dir = get_gauge_data_dir("C:/models/my_project")
    >>> print(f"Gauge data: {gauge_dir}")
    >>>
    >>> # Cache retrieved data
    >>> path = cache_gauge_data(df, "01234567", "2024-01-01", "2024-12-31",
    ...                          "flow", "C:/models/my_project")
    >>> print(f"Cached to: {path}")
"""

import pandas as pd
from pathlib import Path
from typing import Union, Optional, Dict, Any
from datetime import datetime

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class RasUsgsFileIo:
    """
    Static class for USGS gauge data file management.

    Handles caching, loading, and organization of gauge data files
    within HEC-RAS project directory structures.

    All methods are static and follow ras-commander conventions.
    """

    @staticmethod
    @log_call
    def get_gauge_data_dir(
        project_root: Union[str, Path],
        create: bool = True
    ) -> Path:
        """
        Get or create the gauge_data directory structure within a project.

        Creates the following structure:
            project_root/gauge_data/raw/
            project_root/gauge_data/processed/
            project_root/gauge_data/metadata/

        Parameters
        ----------
        project_root : Union[str, Path]
            Path to HEC-RAS project root directory
        create : bool, optional
            Create directory structure if it doesn't exist (default True)

        Returns
        -------
        Path
            Path to gauge_data directory

        Raises
        ------
        FileNotFoundError
            If project_root does not exist

        Example
        -------
        >>> gauge_dir = RasUsgsFileIo.get_gauge_data_dir("C:/models/project")
        >>> print(f"Raw data: {gauge_dir / 'raw'}")
        """
        project_root = Path(project_root)

        if not project_root.exists():
            raise FileNotFoundError(f"Project root does not exist: {project_root}")

        gauge_data_dir = project_root / "gauge_data"

        if create:
            # Create main directory
            gauge_data_dir.mkdir(exist_ok=True)

            # Create subdirectories
            (gauge_data_dir / "raw").mkdir(exist_ok=True)
            (gauge_data_dir / "processed").mkdir(exist_ok=True)
            (gauge_data_dir / "metadata").mkdir(exist_ok=True)

            logger.info(f"Created gauge_data structure at: {gauge_data_dir}")

        return gauge_data_dir

    @staticmethod
    @log_call
    def get_cache_filename(
        site_id: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        parameter: str
    ) -> str:
        """
        Generate standardized filename for cached gauge data.

        Format: USGS-{site_id}_{start_YYYYMMDD}_{end_YYYYMMDD}_{parameter}.csv

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "01234567")
        start_date : Union[str, datetime]
            Start date (YYYY-MM-DD string or datetime object)
        end_date : Union[str, datetime]
            End date (YYYY-MM-DD string or datetime object)
        parameter : str
            Parameter name (e.g., "flow", "stage", "discharge")

        Returns
        -------
        str
            Standardized filename

        Example
        -------
        >>> filename = RasUsgsFileIo.get_cache_filename(
        ...     "01234567", "2024-01-01", "2024-12-31", "flow"
        ... )
        >>> print(filename)
        USGS-01234567_20240101_20241231_flow.csv
        """
        # Convert dates to YYYYMMDD format
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d")

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        # Clean parameter name (lowercase, alphanumeric only)
        param_clean = ''.join(c for c in parameter.lower() if c.isalnum())

        filename = f"USGS-{site_id}_{start_str}_{end_str}_{param_clean}.csv"

        return filename

    @staticmethod
    @log_call
    def cache_gauge_data(
        df: pd.DataFrame,
        site_id: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        parameter: str,
        project_root: Union[str, Path]
    ) -> Path:
        """
        Save retrieved USGS gauge data to cache.

        Saves data to: project_root/gauge_data/raw/{filename}.csv

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing USGS time series data
        site_id : str
            USGS site number (e.g., "01234567")
        start_date : Union[str, datetime]
            Start date of data
        end_date : Union[str, datetime]
            End date of data
        parameter : str
            Parameter name (e.g., "flow", "stage")
        project_root : Union[str, Path]
            Path to HEC-RAS project root

        Returns
        -------
        Path
            Path to saved CSV file

        Example
        -------
        >>> df = pd.DataFrame({
        ...     'datetime': ['2024-01-01', '2024-01-02'],
        ...     'value': [100.0, 150.0]
        ... })
        >>> path = RasUsgsFileIo.cache_gauge_data(
        ...     df, "01234567", "2024-01-01", "2024-12-31",
        ...     "flow", "C:/models/project"
        ... )
        >>> print(f"Saved to: {path}")
        """
        # Get or create gauge_data directory
        gauge_dir = RasUsgsFileIo.get_gauge_data_dir(project_root, create=True)
        raw_dir = gauge_dir / "raw"

        # Generate filename
        filename = RasUsgsFileIo.get_cache_filename(
            site_id, start_date, end_date, parameter
        )

        # Full path
        file_path = raw_dir / filename

        # Save to CSV
        df.to_csv(file_path, index=False)

        logger.info(f"Cached gauge data: {file_path}")
        logger.debug(f"  Site: {site_id}, Records: {len(df)}, Parameter: {parameter}")

        return file_path

    @staticmethod
    @log_call
    def load_cached_gauge_data(
        site_id: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        parameter: str,
        project_root: Union[str, Path]
    ) -> Optional[pd.DataFrame]:
        """
        Load previously cached USGS gauge data.

        Looks for data in: project_root/gauge_data/raw/{filename}.csv

        Parameters
        ----------
        site_id : str
            USGS site number (e.g., "01234567")
        start_date : Union[str, datetime]
            Start date of data
        end_date : Union[str, datetime]
            End date of data
        parameter : str
            Parameter name (e.g., "flow", "stage")
        project_root : Union[str, Path]
            Path to HEC-RAS project root

        Returns
        -------
        Optional[pd.DataFrame]
            DataFrame if cached file exists, None otherwise

        Example
        -------
        >>> df = RasUsgsFileIo.load_cached_gauge_data(
        ...     "01234567", "2024-01-01", "2024-12-31",
        ...     "flow", "C:/models/project"
        ... )
        >>> if df is not None:
        ...     print(f"Loaded {len(df)} records")
        ... else:
        ...     print("No cached data found")
        """
        # Get gauge_data directory (don't create if doesn't exist)
        gauge_dir = RasUsgsFileIo.get_gauge_data_dir(project_root, create=False)
        raw_dir = gauge_dir / "raw"

        # Generate filename
        filename = RasUsgsFileIo.get_cache_filename(
            site_id, start_date, end_date, parameter
        )

        # Full path
        file_path = raw_dir / filename

        # Check if file exists
        if not file_path.exists():
            logger.debug(f"No cached data found: {file_path}")
            return None

        # Load CSV
        try:
            df = pd.read_csv(file_path)
            logger.info(f"Loaded cached data: {file_path}")
            logger.debug(f"  Records: {len(df)}, Columns: {list(df.columns)}")
            return df
        except Exception as e:
            logger.error(f"Error loading cached data from {file_path}: {e}")
            return None

    @staticmethod
    @log_call
    def save_validation_results(
        results_dict: Dict[str, Any],
        event_name: str,
        project_root: Union[str, Path]
    ) -> Path:
        """
        Save validation results to processed data folder.

        Saves validation metrics, aligned data references, and summary statistics
        to: project_root/gauge_data/processed/{event_name}_validation.csv

        Parameters
        ----------
        results_dict : Dict[str, Any]
            Dictionary containing validation results with keys:
                - metrics: Dict of metric name to value
                - site_id: USGS site number
                - n_points: Number of comparison points
                - start_date: Validation period start
                - end_date: Validation period end
                - aligned_data_path: Optional path to aligned CSV
        event_name : str
            Name of validation event (e.g., "hurricane_harvey", "2024_flood")
        project_root : Union[str, Path]
            Path to HEC-RAS project root

        Returns
        -------
        Path
            Path to saved validation results file

        Example
        -------
        >>> results = {
        ...     'metrics': {'NSE': 0.85, 'RMSE': 1.23, 'PBIAS': 5.2},
        ...     'site_id': '01234567',
        ...     'n_points': 240,
        ...     'start_date': '2024-01-01',
        ...     'end_date': '2024-12-31'
        ... }
        >>> path = RasUsgsFileIo.save_validation_results(
        ...     results, "2024_calibration", "C:/models/project"
        ... )
        >>> print(f"Saved validation results: {path}")
        """
        # Get or create gauge_data directory
        gauge_dir = RasUsgsFileIo.get_gauge_data_dir(project_root, create=True)
        processed_dir = gauge_dir / "processed"

        # Clean event name for filename
        event_clean = ''.join(c if c.isalnum() or c in '_-' else '_'
                              for c in event_name.lower())

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{event_clean}_validation_{timestamp}.csv"
        file_path = processed_dir / filename

        # Flatten results dictionary into rows
        rows = []

        # Add metrics
        if 'metrics' in results_dict:
            for metric_name, metric_value in results_dict['metrics'].items():
                rows.append({
                    'category': 'metric',
                    'name': metric_name,
                    'value': metric_value
                })

        # Add metadata
        for key in ['site_id', 'n_points', 'start_date', 'end_date',
                    'aligned_data_path']:
            if key in results_dict:
                rows.append({
                    'category': 'metadata',
                    'name': key,
                    'value': results_dict[key]
                })

        # Create DataFrame and save
        df_results = pd.DataFrame(rows)
        df_results.to_csv(file_path, index=False)

        logger.info(f"Saved validation results: {file_path}")
        logger.debug(f"  Event: {event_name}, Metrics: {len(results_dict.get('metrics', {}))}")

        return file_path
