"""
USGS Gauge Data Catalog Generation

This module provides a static class for generating and managing standardized USGS gauge data
catalogs for HEC-RAS projects. Creates a "USGS Gauge Data" folder structure similar to the
precipitation module's storm catalog pattern.

Key Class:
    UsgsGaugeCatalog - Static methods for gauge catalog operations:
        - generate_gauge_catalog: Create complete gauge catalog with metadata and historical data
        - load_gauge_catalog: Load gauge catalog from standard location
        - load_gauge_data: Load historical data for specific gauge
        - get_gauge_folder: Get path to gauge folder in standard location
        - update_gauge_catalog: Refresh existing catalog with latest data

Example:
    >>> from ras_commander import init_ras_project
    >>> from ras_commander.usgs.catalog import UsgsGaugeCatalog
    >>>
    >>> init_ras_project("C:/models/bald_eagle", "6.6")
    >>> summary = UsgsGaugeCatalog.generate_gauge_catalog()
    >>> print(f"Found {summary['gauge_count']} gauges")
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

# Lazy import check for optional dependencies
try:
    import geopandas as gpd
    from shapely.geometry import Point
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# Import ras-commander components
from ..RasPrj import RasPrj, ras
from ..LoggingConfig import get_logger
from ..Decorators import log_call

# Import existing USGS functions
from .spatial import UsgsGaugeSpatial
from .core import RasUsgsCore
from .rate_limiter import UsgsRateLimiter, check_api_key

# Initialize logger
logger = get_logger(__name__)


class UsgsGaugeCatalog:
    """
    USGS Gauge Data Catalog Management.

    Static methods for generating, loading, and managing standardized USGS gauge data
    catalogs for HEC-RAS projects. Creates a "USGS Gauge Data" folder structure with
    master catalog, individual gauge folders, and historical data.

    All methods are static - do not instantiate this class.
    """

    @staticmethod
    @log_call
    def generate_gauge_catalog(
        ras_object: RasPrj = None,
        buffer_percent: float = 50.0,
        include_historical: bool = True,
        historical_years: int = 10,
        output_folder: Optional[Union[str, Path]] = None,
        parameters: List[str] = None,
        rate_limit_rps: float = 5.0,
        project_crs: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate standardized USGS gauge data catalog for project.

        Creates "USGS Gauge Data" folder with:
        - Master gauge catalog (CSV)
        - Spatial data (GeoJSON)
        - Individual gauge folders with metadata and historical data

        Parameters
        ----------
        ras_object : RasPrj, optional
            RAS project object (default: global ras)
        buffer_percent : float, default 50.0
            Buffer percentage for spatial query
        include_historical : bool, default True
            Download historical data for each gauge
        historical_years : int, default 10
            Years of historical data to retrieve
        output_folder : str or Path, optional
            Custom output location (default: project_folder/USGS Gauge Data)
        parameters : list, default ['flow', 'stage']
            Parameters to retrieve for each gauge
        rate_limit_rps : float, default 5.0
            Rate limit in requests per second (5.0 = conservative, 10.0 = moderate)
            Set to 0 to disable rate limiting. USGS recommends 5-10 req/sec sustained.
        project_crs : str, optional
            Override CRS for projects without embedded projection. Use EPSG codes
            like "EPSG:26918" (UTM Zone 18N). Required for Bald Eagle Creek and
            other HEC-RAS example projects that don't have embedded CRS.
        api_key : str, optional
            USGS API key for higher rate limits (default: None).
            Without API key: 5 req/sec recommended (default rate_limit_rps=5.0)
            With API key: 10 req/sec recommended (set rate_limit_rps=10.0)
            Get free key at: https://api.waterdata.usgs.gov/signup/
            Use test_api_key() to validate before use.

        Returns
        -------
        dict
            Summary with gauge count, data ranges, storage location
            Keys: gauge_count, gauges_processed, gauges_failed, output_folder,
                  data_size_mb, processing_time_sec

        Raises
        ------
        ImportError
            If dataretrieval package is not installed
        ValueError
            If project not initialized or no gauges found

        Example
        -------
        >>> from ras_commander import init_ras_project
        >>> from ras_commander.usgs.catalog import UsgsGaugeCatalog
        >>>
        >>> init_ras_project("C:/models/bald_eagle", "6.6")
        >>> # For projects without CRS, specify project_crs:
        >>> summary = UsgsGaugeCatalog.generate_gauge_catalog(
        ...     buffer_percent=50.0,
        ...     historical_years=10,
        ...     parameters=['flow', 'stage'],
        ...     project_crs="EPSG:26918"  # UTM Zone 18N for Bald Eagle Creek
        ... )
        >>> print(f"Found {summary['gauge_count']} gauges")
        >>> print(f"Location: {summary['output_folder']}")
        """
        start_time = datetime.now()

        # Check for dataretrieval
        try:
            import dataretrieval.nwis as nwis
        except ImportError:
            raise ImportError(
                "The 'dataretrieval' package is required for gauge catalog generation. "
                "Install it with: pip install dataretrieval"
            )

        # Temporarily set API key if provided (restores original state at end)
        # TODO: Refactor RasUsgsCore methods to accept api_key parameter instead
        original_api_key = os.environ.get("API_USGS_PAT")
        if api_key is not None:
            os.environ["API_USGS_PAT"] = api_key
            logger.info("Using provided API key for USGS requests")
        elif original_api_key:
            logger.info("Using API key from environment for USGS requests")
        else:
            logger.info(f"No API key provided - using {rate_limit_rps} req/sec rate limit")

        # Use global ras object if not provided
        if ras_object is None:
            ras_object = ras

        # Check project initialized
        if not hasattr(ras_object, 'prj_file') or ras_object.prj_file is None:
            raise ValueError(
                "HEC-RAS project not initialized. Call init_ras_project() first."
            )

        # Get project folder from prj_file
        project_folder = Path(ras_object.prj_file).parent

        # Get geometry HDF path
        if ras_object.geom_df is None or len(ras_object.geom_df) == 0:
            raise ValueError(
                "No geometry files found in project. Project must have at least one geometry file."
            )

        geom_hdf_path = ras_object.geom_df['hdf_path'].iloc[0]  # Use first geometry

        # Set default parameters
        if parameters is None:
            parameters = ['flow', 'stage']

        # Determine output folder
        if output_folder is None:
            output_folder = project_folder / "USGS Gauge Data"
        else:
            output_folder = Path(output_folder)

        logger.info(f"Generating USGS gauge catalog for project: {project_folder}")
        logger.info(f"Output folder: {output_folder}")
        logger.info(f"Buffer: {buffer_percent}%, Historical years: {historical_years}")

        # Create output folder
        output_folder.mkdir(parents=True, exist_ok=True)

        # Step 1: Find gauges in project
        logger.info("Step 1/7: Finding gauges in project extent...")
        gauges_df = UsgsGaugeSpatial.find_gauges_in_project(
            hdf_path=geom_hdf_path,
            buffer_percent=buffer_percent,
            project_crs=project_crs
        )

        if gauges_df is None or len(gauges_df) == 0:
            raise ValueError(
                f"No USGS gauges found within {buffer_percent}% buffer of project extent. "
                "Try increasing buffer_percent parameter."
            )

        gauge_count = len(gauges_df)
        logger.info(f"Found {gauge_count} gauges in project extent")

        # Initialize counters
        gauges_processed = 0
        gauges_failed = 0
        catalog_records = []
        geojson_features = []

        # Initialize rate limiter
        rate_limiter = None
        if rate_limit_rps > 0:
            rate_limiter = UsgsRateLimiter(
                requests_per_second=rate_limit_rps,
                burst_size=max(40, int(rate_limit_rps * 8))  # Allow 8 seconds of burst
            )
            logger.info(f"Rate limiting enabled: {rate_limit_rps} requests/sec")

            # Check for API key
            if not check_api_key():
                logger.warning(
                    "No USGS API key configured. Rate limits are lower without a key. "
                    "Register for free at: https://api.waterdata.usgs.gov/signup/ "
                    "Then use: configure_api_key('your_key') or set API_USGS_PAT environment variable"
                )
        else:
            logger.info("Rate limiting disabled")

        # Progress bar setup
        if TQDM_AVAILABLE:
            gauge_iterator = tqdm(gauges_df.iterrows(), total=gauge_count, desc="Processing gauges")
        else:
            gauge_iterator = gauges_df.iterrows()
            logger.info("Progress: tqdm not installed, progress bars disabled")

        # Determine site_no column name (handle API version differences)
        site_id_col = None
        for col_name in ['site_no', 'monitoring_location_number', 'monitoring_location_id', 
                         'id', 'monitoringLocationIdentifier', 'identifier', 'siteNumber']:
            if col_name in gauges_df.columns:
                site_id_col = col_name
                logger.debug(f"Using '{col_name}' column for site identification")
                break

        if site_id_col is None:
            logger.error(f"Cannot find site ID column. Available columns: {list(gauges_df.columns)}")
            raise ValueError(f"Cannot find site ID column in gauge data. Available: {list(gauges_df.columns)}")

        # Step 2-6: Process each gauge
        for idx, gauge in gauge_iterator:
            # Get site_id from the detected column and clean it
            site_id = str(gauge[site_id_col])
            # Remove common prefixes like "USGS-"
            if site_id.startswith('USGS-'):
                site_id = site_id[5:]

            try:
                # Create gauge folder
                gauge_folder = output_folder / f"USGS-{site_id}"
                gauge_folder.mkdir(exist_ok=True)

                # Rate limit: metadata request
                if rate_limiter:
                    rate_limiter.wait_if_needed()

                # Get metadata
                logger.info(f"Processing gauge {site_id}: Getting metadata...")
                metadata = None
                try:
                    metadata = RasUsgsCore.get_gauge_metadata(site_id)
                except Exception as metadata_err:
                    logger.warning(f"Gauge {site_id}: Metadata retrieval failed: {metadata_err}")

                # Fallback: use data from gauge DataFrame if metadata retrieval failed
                if metadata is None:
                    logger.info(f"Gauge {site_id}: Using data from spatial query as fallback")
                    # Build metadata from available gauge DataFrame columns
                    metadata = {
                        'site_id': site_id,
                        'station_name': str(gauge.get('station_nm', gauge.get('monitoring_location_name', 'Unknown'))),
                        'latitude': float(gauge.get('dec_lat_va', gauge.get('_lat', 0.0))),
                        'longitude': float(gauge.get('dec_long_va', gauge.get('_lon', 0.0))),
                        'drainage_area_sqmi': float(gauge.get('drain_area_va', gauge.get('drainage_area', 0.0))) if pd.notna(gauge.get('drain_area_va', gauge.get('drainage_area'))) else None,
                        'gage_datum_ft': float(gauge.get('altitude', 0.0)) if pd.notna(gauge.get('altitude')) else None,
                        'state': str(gauge.get('state_cd', gauge.get('state_code', gauge.get('state_name', '')))),
                        'county': str(gauge.get('county_nm', gauge.get('county_name', ''))),
                        'huc_cd': str(gauge.get('huc_cd', gauge.get('hydrologic_unit_code', ''))),
                        'site_type': str(gauge.get('site_tp_cd', gauge.get('site_type_code', gauge.get('site_type', '')))),
                    }

                # Save metadata.json
                metadata_file = gauge_folder / "metadata.json"
                _save_metadata_json(metadata, metadata_file)

                # Initialize data availability dict
                data_availability = {}

                # Process each parameter
                for param in parameters:
                    logger.debug(f"Gauge {site_id}: Processing {param} data...")

                    try:
                        # Rate limit: data availability check
                        if rate_limiter:
                            rate_limiter.wait_if_needed()

                        # Calculate time range for data check
                        end_datetime = datetime.now()
                        start_datetime = end_datetime - timedelta(days=365 * historical_years)
                
                        # Check data availability
                        availability = RasUsgsCore.check_data_availability(
                            site_id,
                            start_datetime=start_datetime,
                            end_datetime=end_datetime,
                            parameter=param
                        )

                        if not availability['available']:
                            logger.debug(f"Gauge {site_id}: {param} data not available")
                            data_availability[param] = {
                                'available': False,
                                'start_date': None,
                                'end_date': None,
                                'record_count': 0,
                                'gaps': [],
                                'completeness': 0.0
                            }
                            continue

                        # Download historical data if requested
                        if include_historical:
                            logger.debug(f"Gauge {site_id}: Downloading {historical_years} years of {param} data...")

                            # Rate limit: historical data retrieval
                            if rate_limiter:
                                rate_limiter.wait_if_needed()

                            if param == 'flow':
                                data_df = RasUsgsCore.retrieve_flow_data(
                                    site_id,
                                    start_datetime=start_datetime,
                                    end_datetime=end_datetime
                                )
                            elif param == 'stage':
                                data_df = RasUsgsCore.retrieve_stage_data(
                                    site_id,
                                    start_datetime=start_datetime,
                                    end_datetime=end_datetime
                                )
                            else:
                                logger.warning(f"Gauge {site_id}: Unknown parameter '{param}', skipping")
                                continue

                            if data_df is not None and len(data_df) > 0:
                                # Save data to CSV
                                data_file = gauge_folder / f"historical_{param}.csv"
                                data_df.to_csv(data_file, index=False)
                                logger.debug(f"Gauge {site_id}: Saved {len(data_df)} {param} records")

                                # Calculate completeness
                                completeness = _calculate_completeness(data_df, start_date, end_date)
                                gaps = _detect_gaps(data_df)

                                data_availability[param] = {
                                    'available': True,
                                    'start_date': data_df['datetime'].min().strftime('%Y-%m-%d'),
                                    'end_date': data_df['datetime'].max().strftime('%Y-%m-%d'),
                                    'record_count': len(data_df),
                                    'gaps': gaps,
                                    'completeness': completeness
                                }
                            else:
                                logger.warning(f"Gauge {site_id}: {param} data retrieval failed")
                                data_availability[param] = {
                                    'available': False,
                                    'start_date': None,
                                    'end_date': None,
                                    'record_count': 0,
                                    'gaps': [],
                                    'completeness': 0.0
                                }
                        else:
                            # Just record availability without downloading
                            data_availability[param] = {
                                'available': True,
                                'start_date': availability.get('start_date'),
                                'end_date': availability.get('end_date'),
                                'record_count': 0,
                                'gaps': [],
                                'completeness': 0.0
                            }

                    except Exception as e:
                        logger.warning(f"Gauge {site_id}: Error processing {param}: {e}")
                        data_availability[param] = {
                            'available': False,
                            'start_date': None,
                            'end_date': None,
                            'record_count': 0,
                            'gaps': [],
                            'completeness': 0.0
                        }

                # Save data availability
                availability_file = gauge_folder / "data_availability.json"
                with open(availability_file, 'w') as f:
                    json.dump(data_availability, f, indent=4)

                # Add to catalog
                catalog_record = _create_catalog_record(
                    gauge, metadata, data_availability, gauge_folder.name
                )
                catalog_records.append(catalog_record)

                # Add to GeoJSON
                if GEOPANDAS_AVAILABLE:
                    geojson_feature = _create_geojson_feature(gauge, metadata, data_availability)
                    geojson_features.append(geojson_feature)

                gauges_processed += 1

            except Exception as e:
                logger.error(f"Gauge {site_id}: Failed to process: {e}")
                gauges_failed += 1

        # Step 7: Create output files
        logger.info("Step 7/7: Creating catalog files...")

        # Save catalog CSV
        catalog_df = pd.DataFrame(catalog_records)
        catalog_file = output_folder / "gauge_catalog.csv"
        catalog_df.to_csv(catalog_file, index=False)
        logger.info(f"Saved catalog: {catalog_file}")

        # Save GeoJSON
        if GEOPANDAS_AVAILABLE and len(geojson_features) > 0:
            geojson_file = output_folder / "gauge_locations.geojson"
            _save_geojson(geojson_features, geojson_file)
            logger.info(f"Saved spatial data: {geojson_file}")
        else:
            if not GEOPANDAS_AVAILABLE:
                logger.warning("GeoPandas not available, skipping GeoJSON creation")

        # Create README
        readme_file = output_folder / "README.md"
        _create_readme(
            readme_file,
            ras_object,
            catalog_df,
            buffer_percent,
            historical_years,
            parameters
        )
        logger.info(f"Saved README: {readme_file}")

        # Calculate total data size
        data_size_mb = _calculate_folder_size(output_folder)

        # Processing time
        processing_time = (datetime.now() - start_time).total_seconds()

        # Summary
        summary = {
            'gauge_count': gauge_count,
            'gauges_processed': gauges_processed,
            'gauges_failed': gauges_failed,
            'output_folder': str(output_folder),
            'data_size_mb': data_size_mb,
            'processing_time_sec': processing_time
        }

        logger.info("=" * 60)
        logger.info("USGS Gauge Catalog Generation Complete")
        logger.info(f"Gauges found: {gauge_count}")
        logger.info(f"Successfully processed: {gauges_processed}")
        logger.info(f"Failed: {gauges_failed}")
        logger.info(f"Output folder: {output_folder}")
        logger.info(f"Data size: {data_size_mb:.2f} MB")
        logger.info(f"Processing time: {processing_time:.1f} seconds")
        logger.info("=" * 60)

        # Restore original API key state
        if original_api_key is not None:
            os.environ["API_USGS_PAT"] = original_api_key
        elif "API_USGS_PAT" in os.environ:
            del os.environ["API_USGS_PAT"]

        return summary

    @staticmethod
    @log_call
    def load_gauge_catalog(ras_object: RasPrj = None, catalog_folder: Optional[Union[str, Path]] = None) -> pd.DataFrame:
        """
        Load gauge catalog from standard location.

        Parameters
        ----------
        ras_object : RasPrj, optional
            RAS project object (default: global ras)
        catalog_folder : str or Path, optional
            Custom catalog location (default: project_folder/USGS Gauge Data)

        Returns
        -------
        pd.DataFrame
            Gauge catalog with columns: site_id, station_name, latitude, longitude,
            drainage_area_sqmi, state, county, active, data_start, data_end,
            parameters_available, distance_to_project_km, upstream_downstream, folder_path

        Raises
        ------
        FileNotFoundError
            If catalog file does not exist
        ValueError
            If project not initialized

        Example
        -------
        >>> catalog = UsgsGaugeCatalog.load_gauge_catalog()
        >>> print(catalog[['site_id', 'station_name', 'drainage_area_sqmi']])
        """
        # Use global ras object if not provided
        if ras_object is None:
            ras_object = ras

        # Determine catalog folder
        if catalog_folder is None:
            if not hasattr(ras_object, 'prj_file') or ras_object.prj_file is None:
                raise ValueError(
                    "HEC-RAS project not initialized. Call init_ras_project() first or provide catalog_folder parameter."
                )
            project_folder = Path(ras_object.prj_file).parent
            catalog_folder = project_folder / "USGS Gauge Data"
        else:
            catalog_folder = Path(catalog_folder)

        # Load catalog
        catalog_file = catalog_folder / "gauge_catalog.csv"

        if not catalog_file.exists():
            raise FileNotFoundError(
                f"Gauge catalog not found: {catalog_file}\n"
                "Generate catalog first with: UsgsGaugeCatalog.generate_gauge_catalog()"
            )

        # Ensure site_id is read as string to preserve leading zeros (e.g., '01545680')
        catalog_df = pd.read_csv(catalog_file, dtype={'site_id': str})
        logger.info(f"Loaded gauge catalog: {len(catalog_df)} gauges from {catalog_file}")

        return catalog_df

    @staticmethod
    @log_call
    def load_gauge_data(
        site_id: str,
        parameter: str = 'flow',
        ras_object: RasPrj = None,
        catalog_folder: Optional[Union[str, Path]] = None
    ) -> pd.DataFrame:
        """
        Load historical data for specific gauge.

        Parameters
        ----------
        site_id : str
            USGS site ID (e.g., '01547200')
        parameter : str, default 'flow'
            Parameter to load ('flow' or 'stage')
        ras_object : RasPrj, optional
            RAS project object (default: global ras)
        catalog_folder : str or Path, optional
            Custom catalog location (default: project_folder/USGS Gauge Data)

        Returns
        -------
        pd.DataFrame
            Historical data with columns: datetime, value, units, qualifiers

        Raises
        ------
        FileNotFoundError
            If gauge data file does not exist
        ValueError
            If project not initialized or invalid parameter

        Example
        -------
        >>> flow_data = UsgsGaugeCatalog.load_gauge_data('01547200', parameter='flow')
        >>> print(f"Loaded {len(flow_data)} flow records")
        """
        # Use global ras object if not provided
        if ras_object is None:
            ras_object = ras

        # Determine catalog folder
        if catalog_folder is None:
            if not hasattr(ras_object, 'prj_file') or ras_object.prj_file is None:
                raise ValueError(
                    "HEC-RAS project not initialized. Call init_ras_project() first or provide catalog_folder parameter."
                )
            project_folder = Path(ras_object.prj_file).parent
            catalog_folder = project_folder / "USGS Gauge Data"
        else:
            catalog_folder = Path(catalog_folder)

        # Validate parameter
        if parameter not in ['flow', 'stage']:
            raise ValueError(f"Invalid parameter '{parameter}'. Must be 'flow' or 'stage'.")

        # Load data
        gauge_folder = catalog_folder / f"USGS-{site_id}"
        data_file = gauge_folder / f"historical_{parameter}.csv"

        if not data_file.exists():
            raise FileNotFoundError(
                f"Gauge data not found: {data_file}\n"
                f"Ensure gauge {site_id} was processed with '{parameter}' parameter."
            )

        data_df = pd.read_csv(data_file, parse_dates=['datetime'])
        logger.info(f"Loaded {len(data_df)} {parameter} records for gauge {site_id}")

        return data_df

    @staticmethod
    @log_call
    def get_gauge_folder(
        site_id: str,
        ras_object: RasPrj = None,
        catalog_folder: Optional[Union[str, Path]] = None
    ) -> Path:
        """
        Get path to gauge folder in standard location.

        Parameters
        ----------
        site_id : str
            USGS site ID (e.g., '01547200')
        ras_object : RasPrj, optional
            RAS project object (default: global ras)
        catalog_folder : str or Path, optional
            Custom catalog location (default: project_folder/USGS Gauge Data)

        Returns
        -------
        Path
            Path to gauge folder

        Raises
        ------
        ValueError
            If project not initialized

        Example
        -------
        >>> folder = UsgsGaugeCatalog.get_gauge_folder('01547200')
        >>> metadata_file = folder / 'metadata.json'
        """
        # Use global ras object if not provided
        if ras_object is None:
            ras_object = ras

        # Determine catalog folder
        if catalog_folder is None:
            if not hasattr(ras_object, 'prj_file') or ras_object.prj_file is None:
                raise ValueError(
                    "HEC-RAS project not initialized. Call init_ras_project() first or provide catalog_folder parameter."
                )
            project_folder = Path(ras_object.prj_file).parent
            catalog_folder = project_folder / "USGS Gauge Data"
        else:
            catalog_folder = Path(catalog_folder)

        return catalog_folder / f"USGS-{site_id}"

    @staticmethod
    @log_call
    def update_gauge_catalog(
        ras_object: RasPrj = None,
        catalog_folder: Optional[Union[str, Path]] = None,
        parameters: List[str] = None,
        rate_limit_rps: float = 5.0
    ) -> Dict[str, Any]:
        """
        Refresh existing catalog with latest data.

        Updates data_availability.json and downloads new data for existing gauges.
        Does not add new gauges (use generate_gauge_catalog for that).

        Parameters
        ----------
        ras_object : RasPrj, optional
            RAS project object (default: global ras)
        catalog_folder : str or Path, optional
            Custom catalog location (default: project_folder/USGS Gauge Data)
        parameters : list, optional
            Parameters to update (default: update all existing parameters)
        rate_limit_rps : float, default 5.0
            Rate limit in requests per second (5.0 = conservative, 10.0 = moderate)
            Set to 0 to disable rate limiting. USGS recommends 5-10 req/sec sustained.

        Returns
        -------
        dict
            Summary with update statistics
            Keys: gauges_updated, gauges_failed, processing_time_sec

        Raises
        ------
        FileNotFoundError
            If catalog does not exist
        ValueError
            If project not initialized

        Example
        -------
        >>> summary = UsgsGaugeCatalog.update_gauge_catalog()
        >>> print(f"Updated {summary['gauges_updated']} gauges")
        """
        start_time = datetime.now()

        # Load existing catalog
        catalog_df = UsgsGaugeCatalog.load_gauge_catalog(ras_object=ras_object, catalog_folder=catalog_folder)

        # Use global ras object if not provided
        if ras_object is None:
            ras_object = ras

        # Determine catalog folder
        if catalog_folder is None:
            if hasattr(ras_object, 'prj_file') and ras_object.prj_file is not None:
                project_folder = Path(ras_object.prj_file).parent
                catalog_folder = project_folder / "USGS Gauge Data"
            else:
                raise ValueError(
                    "HEC-RAS project not initialized. Call init_ras_project() first or provide catalog_folder parameter."
                )
        else:
            catalog_folder = Path(catalog_folder)

        logger.info(f"Updating gauge catalog: {len(catalog_df)} gauges")

        gauges_updated = 0
        gauges_failed = 0

        # Initialize rate limiter
        rate_limiter = None
        if rate_limit_rps > 0:
            rate_limiter = UsgsRateLimiter(
                requests_per_second=rate_limit_rps,
                burst_size=max(40, int(rate_limit_rps * 8))
            )
            logger.info(f"Rate limiting enabled: {rate_limit_rps} requests/sec")

            # Check for API key
            if not check_api_key():
                logger.warning(
                    "No USGS API key configured. Register at: https://api.waterdata.usgs.gov/signup/"
                )
        else:
            logger.info("Rate limiting disabled")

        # Progress bar
        if TQDM_AVAILABLE:
            gauge_iterator = tqdm(catalog_df.iterrows(), total=len(catalog_df), desc="Updating gauges")
        else:
            gauge_iterator = catalog_df.iterrows()

        for idx, gauge in gauge_iterator:
            site_id = gauge['site_id']
            gauge_folder = catalog_folder / gauge['folder_path']

            try:
                # Load existing availability
                availability_file = gauge_folder / "data_availability.json"
                if availability_file.exists():
                    with open(availability_file, 'r') as f:
                        data_availability = json.load(f)
                else:
                    logger.warning(f"Gauge {site_id}: No data_availability.json found, skipping")
                    gauges_failed += 1
                    continue

                # Update each parameter
                params_to_update = parameters if parameters else list(data_availability.keys())

                for param in params_to_update:
                    if param not in data_availability:
                        continue

                    if not data_availability[param]['available']:
                        continue

                    try:
                        # Rate limit: data retrieval
                        if rate_limiter:
                            rate_limiter.wait_if_needed()

                        # Get latest data (last 30 days)
                        end_datetime = datetime.now()
                        start_datetime = end_datetime - timedelta(days=30)

                        if param == 'flow':
                            new_data = RasUsgsCore.retrieve_flow_data(
                                site_id,
                                start_datetime=start_datetime,
                                end_datetime=end_datetime
                            )
                        elif param == 'stage':
                            new_data = RasUsgsCore.retrieve_stage_data(
                                site_id,
                                start_datetime=start_datetime,
                                end_datetime=end_datetime
                            )
                        else:
                            continue

                        if new_data is not None and len(new_data) > 0:
                            # Load existing data
                            data_file = gauge_folder / f"historical_{param}.csv"
                            if data_file.exists():
                                existing_data = pd.read_csv(data_file, parse_dates=['datetime'])
                                # Append new data (removing duplicates)
                                combined = pd.concat([existing_data, new_data])
                                combined = combined.drop_duplicates(subset=['datetime'])
                                combined = combined.sort_values('datetime')
                                combined.to_csv(data_file, index=False)

                                # Update availability
                                data_availability[param]['end_date'] = combined['datetime'].max().strftime('%Y-%m-%d')
                                data_availability[param]['record_count'] = len(combined)

                                logger.debug(f"Gauge {site_id}: Updated {param} data")

                    except Exception as e:
                        logger.warning(f"Gauge {site_id}: Failed to update {param}: {e}")

                # Save updated availability
                with open(availability_file, 'w') as f:
                    json.dump(data_availability, f, indent=4)

                gauges_updated += 1

            except Exception as e:
                logger.error(f"Gauge {site_id}: Update failed: {e}")
                gauges_failed += 1

        processing_time = (datetime.now() - start_time).total_seconds()

        summary = {
            'gauges_updated': gauges_updated,
            'gauges_failed': gauges_failed,
            'processing_time_sec': processing_time
        }

        logger.info(f"Catalog update complete: {gauges_updated} updated, {gauges_failed} failed")

        return summary


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _convert_to_native(obj):
    """Convert numpy types to native Python types for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.intc, np.intp, np.int8, np.int16, np.int32, np.int64,
                        np.uint8, np.uint16, np.uint32, np.uint64)):
        return int(obj)
    elif isinstance(obj, (np.float16, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    return obj


def _save_metadata_json(metadata: Dict, output_file: Path) -> None:
    """Save gauge metadata to JSON file."""
    metadata_dict = {
        'site_id': _convert_to_native(metadata.get('site_id')),
        'station_name': _convert_to_native(metadata.get('station_name')),
        'location': {
            'latitude': _convert_to_native(metadata.get('latitude')),
            'longitude': _convert_to_native(metadata.get('longitude')),
            'state': _convert_to_native(metadata.get('state')),
            'county': _convert_to_native(metadata.get('county')),
            'huc_cd': _convert_to_native(metadata.get('huc_cd'))
        },
        'drainage_area_sqmi': _convert_to_native(metadata.get('drainage_area_sqmi')),
        'gage_datum_ft': _convert_to_native(metadata.get('gage_datum_ft')),
        'active': _convert_to_native(metadata.get('active', True)),
        'available_parameters': metadata.get('available_parameters', []),
        'period_of_record': {
            'start': _convert_to_native(metadata.get('begin_date')),
            'end': _convert_to_native(metadata.get('end_date')),
            'years': _convert_to_native(metadata.get('count_nu'))
        },
        'last_updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    }

    with open(output_file, 'w') as f:
        json.dump(metadata_dict, f, indent=4)


def _calculate_completeness(data_df: pd.DataFrame, start_date: datetime, end_date: datetime) -> float:
    """Calculate data completeness as fraction of expected records."""
    if data_df is None or len(data_df) == 0:
        return 0.0

    # Calculate expected number of records (assuming hourly data)
    expected_hours = (end_date - start_date).total_seconds() / 3600
    actual_records = len(data_df)

    completeness = min(actual_records / expected_hours, 1.0) if expected_hours > 0 else 0.0

    return round(completeness, 3)


def _detect_gaps(data_df: pd.DataFrame, gap_threshold_hours: int = 24) -> List[Dict]:
    """Detect gaps in time series data."""
    if data_df is None or len(data_df) < 2:
        return []

    gaps = []

    # Sort by datetime
    data_sorted = data_df.sort_values('datetime')

    # Calculate time differences
    time_diffs = data_sorted['datetime'].diff()

    # Find gaps larger than threshold
    gap_mask = time_diffs > timedelta(hours=gap_threshold_hours)

    for idx in data_sorted[gap_mask].index:
        gap_start = data_sorted.loc[idx - 1, 'datetime']
        gap_end = data_sorted.loc[idx, 'datetime']
        gap_days = (gap_end - gap_start).days

        gaps.append({
            'start': gap_start.strftime('%Y-%m-%d'),
            'end': gap_end.strftime('%Y-%m-%d'),
            'days': gap_days
        })

    return gaps[:10]  # Limit to first 10 gaps


def _create_catalog_record(
    gauge: pd.Series,
    metadata: Dict,
    data_availability: Dict,
    folder_name: str
) -> Dict:
    """Create catalog record for a single gauge."""
    # Extract available parameters
    params_available = [p for p, avail in data_availability.items() if avail['available']]
    params_str = ';'.join(params_available)

    # Get date range
    all_starts = [avail['start_date'] for avail in data_availability.values() if avail.get('start_date')]
    all_ends = [avail['end_date'] for avail in data_availability.values() if avail.get('end_date')]

    data_start = min(all_starts) if all_starts else None
    data_end = max(all_ends) if all_ends else None

    return {
        'site_id': gauge.get('site_no', metadata.get('site_id')),
        'station_name': metadata.get('station_name', gauge.get('station_nm', '')),
        'latitude': metadata.get('latitude', gauge.get('dec_lat_va')),
        'longitude': metadata.get('longitude', gauge.get('dec_long_va')),
        'drainage_area_sqmi': metadata.get('drainage_area_sqmi', gauge.get('drain_area_va')),
        'state': metadata.get('state', gauge.get('state_cd', '')),
        'county': metadata.get('county', gauge.get('county_cd', '')),
        'active': metadata.get('active', True),
        'data_start': data_start,
        'data_end': data_end,
        'parameters_available': params_str,
        'distance_to_project_km': gauge.get('distance_km', 0.0),
        'upstream_downstream': gauge.get('position', 'unknown'),
        'folder_path': folder_name
    }


def _create_geojson_feature(gauge: pd.Series, metadata: Dict, data_availability: Dict) -> Dict:
    """Create GeoJSON feature for a single gauge."""
    params_available = [p for p, avail in data_availability.items() if avail['available']]

    return {
        'type': 'Feature',
        'geometry': {
            'type': 'Point',
            'coordinates': [
                metadata.get('longitude', gauge.get('dec_long_va')),
                metadata.get('latitude', gauge.get('dec_lat_va'))
            ]
        },
        'properties': {
            'site_id': gauge.get('site_no', metadata.get('site_id')),
            'name': metadata.get('station_name', gauge.get('station_nm', '')),
            'drainage_sqmi': metadata.get('drainage_area_sqmi', gauge.get('drain_area_va')),
            'active': metadata.get('active', True),
            'parameters': ', '.join(params_available)
        }
    }


def _save_geojson(features: List[Dict], output_file: Path) -> None:
    """Save GeoJSON file with features."""
    geojson = {
        'type': 'FeatureCollection',
        'crs': {
            'type': 'name',
            'properties': {'name': 'EPSG:4326'}
        },
        'features': features
    }

    with open(output_file, 'w') as f:
        json.dump(geojson, f, indent=2)


def _create_readme(
    output_file: Path,
    ras_object: RasPrj,
    catalog_df: pd.DataFrame,
    buffer_percent: float,
    historical_years: int,
    parameters: List[str]
) -> None:
    """Create README.md file for catalog."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    project_name = Path(ras_object.project_path).name

    # Count active gauges
    active_count = len(catalog_df)

    readme_content = f"""# USGS Gauge Data Catalog

Generated: {now}

## Project Information
- Project: {project_name}
- Location: {ras_object.project_path}
- Gauges Found: {active_count} active
- Buffer: {buffer_percent}%
- Historical Data: {historical_years} years
- Parameters: {', '.join(parameters)}

## Gauges Included

"""

    # Add gauge entries
    for idx, gauge in catalog_df.iterrows():
        site_id = gauge['site_id']
        name = gauge['station_name']
        drainage = gauge['drainage_area_sqmi']
        position = gauge.get('upstream_downstream', 'unknown')
        distance = gauge.get('distance_to_project_km', 0.0)
        params = gauge.get('parameters_available', '')
        data_start = gauge.get('data_start', 'N/A')
        data_end = gauge.get('data_end', 'N/A')

        # Calculate years
        if data_start != 'N/A' and data_end != 'N/A':
            try:
                start_year = int(data_start.split('-')[0])
                end_year = int(data_end.split('-')[0])
                years = end_year - start_year
            except:
                years = 0
        else:
            years = 0

        readme_content += f"""### USGS-{site_id}: {name}
- **Location:** {position.title()} ({distance:.1f} km from project)
- **Drainage:** {drainage} sq mi
- **Active:** Yes
- **Data:** {data_start} to {data_end} ({years} years)
- **Parameters:** {params.replace(';', ', ')}

"""

    # Add usage section
    readme_content += """
## Usage

### Load Catalog
```python
import pandas as pd
catalog = pd.read_csv('gauge_catalog.csv')
```

### Load Gauge Data
```python
flow_data = pd.read_csv('USGS-01547200/historical_flow.csv')
```

### Load Metadata
```python
import json
with open('USGS-01547200/metadata.json') as f:
    metadata = json.load(f)
```

### Use with ras-commander
```python
from ras_commander.usgs import load_gauge_catalog, load_gauge_data

# Load catalog
catalog = load_gauge_catalog()

# Load gauge data
flow = load_gauge_data('01547200', parameter='flow')
```

## Files Structure

- **gauge_catalog.csv** - Master catalog of all gauges
- **gauge_locations.geojson** - Spatial data for mapping
- **USGS-{site_id}/** - Individual gauge folders containing:
  - metadata.json - Gauge metadata
  - historical_flow.csv - Flow time series data
  - historical_stage.csv - Stage time series data
  - data_availability.json - Data completeness information
"""

    # Write file
    with open(output_file, 'w') as f:
        f.write(readme_content)


def _calculate_folder_size(folder: Path) -> float:
    """Calculate total size of folder in MB."""
    total_size = 0

    for file in folder.rglob('*'):
        if file.is_file():
            total_size += file.stat().st_size

    return total_size / (1024 * 1024)  # Convert to MB
