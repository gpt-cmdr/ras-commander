"""
M3Model - Manage and download HCFCD M3 hydraulic models

This module is part of the ras-commander library and provides access to Harris County
Flood Control District (HCFCD) M3 Models - Current FEMA effective HEC-RAS models.

This module follows the centralized logging configuration from ras-commander.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).
3. Obtain the logger using: logger = logging.getLogger(__name__)

Example:
    @log_call
    def my_function():
        logger = logging.getLogger(__name__)
        logger.debug("Additional debug information")
        # Function logic here


-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in M3Model:
- list_models()
- get_model_info()
- extract_model()
- list_channels()
- get_model_by_channel()
- query_arcgis_channels()
- is_model_extracted()
- clean_models_directory()

"""
import os
import requests
import zipfile
import pandas as pd
from pathlib import Path
import shutil
from typing import Union, List, Dict, Optional
from datetime import datetime
import logging
from tqdm import tqdm
from ras_commander import get_logger
from ras_commander.LoggingConfig import log_call

logger = get_logger(__name__)

class M3Model:
    """
    A class for downloading and managing HCFCD M3 Models (Current FEMA effective models).
    All methods are class methods, so no initialization is required.

    These models are Harris County Flood Control District's hydraulic and hydrologic (H&H)
    models representing Current FEMA effective models for major bayous and watersheds in
    the Houston, Texas region.

    Example:
        # List all available models
        models = M3Model.list_models()

        # Extract a specific model
        path = M3Model.extract_model("A")  # Clear Creek

        # Find model by channel name
        model_id = M3Model.get_model_by_channel("BRAYS BAYOU")
        path = M3Model.extract_model(model_id)
    """

    # Base URL for M3 Model downloads
    base_url = 'https://files.m3models.org/modellibrary/'

    # ArcGIS REST API for channel information
    arcgis_url = 'https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD/Channels/MapServer/0'

    # Base directory for model storage
    base_dir = Path.cwd()
    models_dir = base_dir / 'm3_models'

    # Model metadata - hardcoded since no API is available
    # Format: {model_id: {name, short_name, effective_date, size_gb, description}}
    MODELS = {
        'A': {
            'name': 'Clear Creek',
            'short_name': 'Clear',
            'effective_date': '2022-05-05',
            'size_gb': 0.03,
            'description': 'Clear Creek H&H Models',
            'primary_channels': ['CLEAR CREEK']
        },
        'B': {
            'name': 'Armand Bayou',
            'short_name': 'Armand',
            'effective_date': '2022-05-05',
            'size_gb': 0.04,
            'description': 'Armand Bayou H&H Models',
            'primary_channels': ['ARMAND BAYOU']
        },
        'C': {
            'name': 'Sims Bayou',
            'short_name': 'Sims',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Sims Bayou H&H Models',
            'primary_channels': ['SIMS BAYOU']
        },
        'D': {
            'name': 'Brays Bayou',
            'short_name': 'Brays',
            'effective_date': '2022-05-05',
            'size_gb': 0.03,
            'description': 'Brays Bayou H&H Models',
            'primary_channels': ['BRAYS BAYOU']
        },
        'E': {
            'name': 'White Oak Bayou',
            'short_name': 'WhiteOak',
            'effective_date': '2023-01-30',
            'size_gb': 0.02,
            'description': 'White Oak Bayou H&H Models',
            'primary_channels': ['WHITE OAK BAYOU']
        },
        'F': {
            'name': 'San Jacinto/Galveston Bay',
            'short_name': 'GalvBay',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'San Jacinto/Galveston Bay H&H Models',
            'primary_channels': ['BAYPORT CHANNEL', 'SHIP CHANNEL']
        },
        'G': {
            'name': 'San Jacinto River',
            'short_name': 'SanJac',
            'effective_date': '2022-05-05',
            'size_gb': 0.09,
            'description': 'San Jacinto River H&H Models',
            'primary_channels': ['SAN JACINTO RIVER', 'EAST FORK SAN JACINTO RIVER']
        },
        'H': {
            'name': 'Hunting Bayou',
            'short_name': 'Hunting',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Hunting Bayou H&H Models',
            'primary_channels': ['HUNTING BAYOU']
        },
        'I': {
            'name': 'Vince Bayou',
            'short_name': 'Vince',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Vince Bayou H&H Models',
            'primary_channels': ['VINCE BAYOU', 'LITTLE VINCE BAYOU']
        },
        'J': {
            'name': 'Spring Creek',
            'short_name': 'Spring',
            'effective_date': '2022-05-05',
            'size_gb': 0.06,
            'description': 'Spring Creek H&H Models',
            'primary_channels': ['SPRING CREEK', 'SPRING BRANCH']
        },
        'K': {
            'name': 'Cypress Creek',
            'short_name': 'Cypress',
            'effective_date': '2022-05-05',
            'size_gb': 0.04,
            'description': 'Cypress Creek H&H Models',
            'primary_channels': ['CYPRESS CREEK']
        },
        'L': {
            'name': 'Little Cypress Creek',
            'short_name': 'LttlCyp',
            'effective_date': '2022-05-05',
            'size_gb': 0.03,
            'description': 'Little Cypress Creek H&H Models',
            'primary_channels': ['LITTLE CYPRESS CREEK']
        },
        'M': {
            'name': 'Willow Creek',
            'short_name': 'Willow',
            'effective_date': '2023-01-30',
            'size_gb': 0.05,
            'description': 'Willow Creek H&H Models',
            'primary_channels': ['WILLOW CREEK', 'WILLOW WATER HOLE']
        },
        'N': {
            'name': 'Carpenters Bayou',
            'short_name': 'Carpenters',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Carpenters Bayou H&H Models',
            'primary_channels': ['CARPENTERS BAYOU']
        },
        'O': {
            'name': 'Spring Gully and Goose Creek',
            'short_name': 'SprgGully',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Spring Gully and Goose Creek H&H Models',
            'primary_channels': ['SPRING GULLY', 'GOOSE CREEK', 'E. FORK GOOSE CREEK', 'W. FORK GOOSE CREEK']
        },
        'P': {
            'name': 'Greens Bayou',
            'short_name': 'Greens',
            'effective_date': '2024-03-04',
            'size_gb': 0.02,
            'description': 'Greens Bayou H&H Models',
            'primary_channels': ['GREENS BAYOU', 'HALLS BAYOU', 'GARNERS BAYOU']
        },
        'Q': {
            'name': 'Cedar Bayou',
            'short_name': 'Cedar',
            'effective_date': '2022-05-05',
            'size_gb': 0.02,
            'description': 'Cedar Bayou H&H Models',
            'primary_channels': ['CEDAR BAYOU', 'LITTLE CEDAR BAYOU']
        },
        'R': {
            'name': 'Jackson Bayou',
            'short_name': 'Jackson',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Jackson Bayou H&H Models',
            'primary_channels': ['JACKSON BAYOU']
        },
        'S': {
            'name': 'Luce Bayou',
            'short_name': 'Luce',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Luce Bayou H&H Models',
            'primary_channels': ['LUCE BAYOU']
        },
        'T': {
            'name': 'Barker',
            'short_name': 'Barker',
            'effective_date': '2022-05-05',
            'size_gb': 0.01,
            'description': 'Barker H&H models',
            'primary_channels': ['BARKER DITCH']
        },
        'U': {
            'name': 'Addicks',
            'short_name': 'Addicks',
            'effective_date': '2022-05-05',
            'size_gb': 0.08,
            'description': 'Addicks H&H Models',
            'primary_channels': []  # Reservoir, not a specific channel
        },
        'W': {
            'name': 'Buffalo Bayou',
            'short_name': 'Buffalo',
            'effective_date': '2022-05-05',
            'size_gb': 0.03,
            'description': 'Buffalo Bayou H&H Models',
            'primary_channels': ['BUFFALO BAYOU', 'UPPER BUFFALO BAYOU/CANE']
        }
    }

    # Cache for channel data
    _channel_df = None

    @classmethod
    @log_call
    def list_models(cls, as_dataframe: bool = True) -> Union[pd.DataFrame, List[Dict]]:
        """
        List all available M3 Models.

        Args:
            as_dataframe: If True, returns a pandas DataFrame. If False, returns a list of dicts.

        Returns:
            DataFrame or list of model information dictionaries

        Example:
            >>> models_df = M3Model.list_models()
            >>> print(models_df)
            >>>
            >>> models_list = M3Model.list_models(as_dataframe=False)
            >>> for model in models_list:
            ...     print(f"{model['id']}: {model['name']}")
        """
        models_list = []
        for model_id, info in cls.MODELS.items():
            model_dict = {
                'id': model_id,
                'name': info['name'],
                'description': info['description'],
                'effective_date': info['effective_date'],
                'size_gb': info['size_gb'],
                'primary_channels': ', '.join(info['primary_channels'])
            }
            models_list.append(model_dict)

        if as_dataframe:
            df = pd.DataFrame(models_list)
            logger.info(f"Listed {len(df)} M3 Models")
            return df
        else:
            logger.info(f"Listed {len(models_list)} M3 Models")
            return models_list

    @classmethod
    @log_call
    def get_model_info(cls, model_id: str) -> Dict:
        """
        Get detailed information about a specific model.

        Args:
            model_id: Single letter model identifier (e.g., 'A', 'B', 'C')

        Returns:
            Dictionary containing model metadata

        Raises:
            ValueError: If model_id is not found

        Example:
            >>> info = M3Model.get_model_info('D')
            >>> print(f"Model: {info['name']}")
            >>> print(f"Size: {info['size_gb']} GB")
        """
        model_id = model_id.upper()

        if model_id not in cls.MODELS:
            available = ', '.join(sorted(cls.MODELS.keys()))
            error_msg = f"Model '{model_id}' not found. Available models: {available}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        info = cls.MODELS[model_id].copy()
        info['id'] = model_id
        info['download_url'] = cls._get_download_url(model_id)
        info['filename'] = cls._get_filename(model_id)

        logger.info(f"Retrieved info for model '{model_id}': {info['name']}")
        return info

    @classmethod
    def _get_filename(cls, model_id: str) -> str:
        """Generate the zip filename for a model."""
        info = cls.MODELS[model_id.upper()]
        return f"{model_id.upper()}_{info['short_name']}_FEMA_Effective.zip"

    @classmethod
    def _get_download_url(cls, model_id: str) -> str:
        """Generate the full download URL for a model."""
        info = cls.MODELS[model_id.upper()]
        filename = cls._get_filename(model_id)
        # Format effective date for URL (YYYY-MM-DD HH:MM)
        effective_date = info['effective_date'] + ' 05:00'
        return f"{cls.base_url}{filename}?effectivedate={effective_date.replace(' ', '%20')}"

    @classmethod
    @log_call
    def extract_model(cls, model_id: str, output_path: Union[str, Path] = None,
                     overwrite: bool = False) -> Path:
        """
        Download and extract a specific M3 Model.

        Args:
            model_id: Single letter model identifier (e.g., 'A', 'B', 'C')
            output_path: Optional path where the model will be extracted.
                        If None, uses default 'm3_models' folder.
            overwrite: If True, overwrites existing model directory

        Returns:
            Path to the extracted model directory

        Raises:
            ValueError: If model_id is not found

        Example:
            >>> # Extract to default location
            >>> path = M3Model.extract_model('A')
            >>>
            >>> # Extract to custom location
            >>> path = M3Model.extract_model('D', output_path='my_models')
        """
        model_id = model_id.upper()

        # Validate model ID
        if model_id not in cls.MODELS:
            available = ', '.join(sorted(cls.MODELS.keys()))
            error_msg = f"Model '{model_id}' not found. Available models: {available}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Determine output directory
        if output_path is None:
            base_output_path = cls.models_dir
        else:
            base_output_path = Path(output_path)
            if not base_output_path.is_absolute():
                base_output_path = Path.cwd() / base_output_path

        base_output_path.mkdir(parents=True, exist_ok=True)

        model_info = cls.MODELS[model_id]
        model_name = model_info['name']
        model_folder = base_output_path / model_name

        logger.info("----- M3Model Extracting Model -----")
        logger.info(f"Extracting model '{model_id}' - {model_name}")

        # Check if model already exists
        if model_folder.exists():
            if not overwrite:
                logger.info(f"Model '{model_name}' already exists at {model_folder}")
                logger.info("Use overwrite=True to re-download")
                return model_folder
            else:
                logger.info(f"Removing existing model '{model_name}'...")
                try:
                    shutil.rmtree(model_folder)
                    logger.info(f"Existing folder deleted")
                except Exception as e:
                    logger.error(f"Failed to delete existing folder: {e}")
                    raise

        # Download the zip file
        zip_path = base_output_path / cls._get_filename(model_id)
        url = cls._get_download_url(model_id)

        logger.info(f"Downloading from: {url}")
        logger.info(f"Size: {model_info['size_gb']} GB")

        try:
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            # Get file size
            total_size = int(response.headers.get('content-length', 0))

            # Download with progress bar
            with open(zip_path, 'wb') as file:
                if total_size > 0:
                    with tqdm(
                        desc=f"Downloading {model_id}",
                        total=total_size,
                        unit='iB',
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as progress_bar:
                        for chunk in response.iter_content(chunk_size=8192):
                            size = file.write(chunk)
                            progress_bar.update(size)
                else:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)

            logger.info(f"Downloaded to {zip_path}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download model '{model_id}': {e}")
            if zip_path.exists():
                zip_path.unlink()
            raise

        # Extract the zip file
        logger.info(f"Extracting to {model_folder}...")
        try:
            model_folder.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(model_folder)

            logger.info(f"Successfully extracted model '{model_id}' to {model_folder}")

        except Exception as e:
            logger.error(f"Failed to extract model '{model_id}': {e}")
            if model_folder.exists():
                shutil.rmtree(model_folder)
            raise
        finally:
            # Clean up zip file
            if zip_path.exists():
                zip_path.unlink()
                logger.debug(f"Removed temporary zip file: {zip_path}")

        return model_folder

    @classmethod
    @log_call
    def list_channels(cls, refresh: bool = False) -> pd.DataFrame:
        """
        List all channels from the HCFCD ArcGIS REST API.

        Args:
            refresh: If True, forces a refresh of channel data from the API

        Returns:
            DataFrame containing channel names and associated model IDs

        Example:
            >>> channels_df = M3Model.list_channels()
            >>> print(channels_df[channels_df['model_id'].notna()])
        """
        if cls._channel_df is None or refresh:
            cls._channel_df = cls.query_arcgis_channels()

        logger.info(f"Listed {len(cls._channel_df)} channels")
        return cls._channel_df.copy()

    @classmethod
    @log_call
    def query_arcgis_channels(cls) -> pd.DataFrame:
        """
        Query the HCFCD ArcGIS REST API for channel information.

        Returns:
            DataFrame containing channel names and their associated model IDs

        Note:
            This method queries the ArcGIS REST API to get unique channel names
            and attempts to match them to M3 Models based on the primary_channels
            defined in the MODELS dictionary.
        """
        logger.info("Querying HCFCD ArcGIS REST API for channel data...")

        query_url = f"{cls.arcgis_url}/query"
        params = {
            'where': '1=1',
            'outFields': 'CHAN_NAME',
            'returnDistinctValues': 'true',
            'returnGeometry': 'false',
            'f': 'json'
        }

        try:
            response = requests.get(query_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Extract channel names
            channels = []
            for feature in data.get('features', []):
                chan_name = feature.get('attributes', {}).get('CHAN_NAME', '').strip()
                if chan_name and chan_name != ' ':
                    channels.append(chan_name)

            # Create DataFrame
            df = pd.DataFrame({'channel_name': sorted(set(channels))})

            # Add model_id column by matching with MODELS
            df['model_id'] = df['channel_name'].apply(cls._match_channel_to_model)

            logger.info(f"Retrieved {len(df)} unique channels from ArcGIS API")
            logger.info(f"Matched {df['model_id'].notna().sum()} channels to M3 Models")

            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to query ArcGIS REST API: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing ArcGIS data: {e}")
            raise

    @classmethod
    def _match_channel_to_model(cls, channel_name: str) -> Optional[str]:
        """
        Match a channel name to a model ID based on primary_channels.

        Args:
            channel_name: Name of the channel to match

        Returns:
            Model ID if matched, None otherwise
        """
        channel_upper = channel_name.upper()

        for model_id, info in cls.MODELS.items():
            for primary_channel in info['primary_channels']:
                if channel_upper == primary_channel.upper():
                    return model_id

        return None

    @classmethod
    @log_call
    def get_model_by_channel(cls, channel_name: str) -> Optional[str]:
        """
        Find the M3 Model ID for a given channel name.

        Args:
            channel_name: Name of the channel (e.g., 'BRAYS BAYOU', 'BUFFALO BAYOU')

        Returns:
            Model ID if found, None otherwise

        Example:
            >>> model_id = M3Model.get_model_by_channel('BRAYS BAYOU')
            >>> print(f"Model ID: {model_id}")  # Output: Model ID: D
            >>>
            >>> # Extract the model
            >>> if model_id:
            ...     path = M3Model.extract_model(model_id)
        """
        model_id = cls._match_channel_to_model(channel_name)

        if model_id:
            logger.info(f"Channel '{channel_name}' matches model '{model_id}' - {cls.MODELS[model_id]['name']}")
        else:
            logger.warning(f"No model found for channel '{channel_name}'")

        return model_id

    @classmethod
    @log_call
    def is_model_extracted(cls, model_id: str, output_path: Union[str, Path] = None) -> bool:
        """
        Check if a model is already extracted.

        Args:
            model_id: Single letter model identifier
            output_path: Optional path to check. If None, uses default 'm3_models' folder.

        Returns:
            True if model directory exists, False otherwise

        Example:
            >>> if not M3Model.is_model_extracted('A'):
            ...     M3Model.extract_model('A')
        """
        model_id = model_id.upper()

        if model_id not in cls.MODELS:
            logger.warning(f"Model '{model_id}' not found")
            return False

        if output_path is None:
            base_output_path = cls.models_dir
        else:
            base_output_path = Path(output_path)
            if not base_output_path.is_absolute():
                base_output_path = Path.cwd() / base_output_path

        model_name = cls.MODELS[model_id]['name']
        model_folder = base_output_path / model_name

        is_extracted = model_folder.exists()
        logger.info(f"Model '{model_id}' extracted: {is_extracted}")
        return is_extracted

    @classmethod
    @log_call
    def clean_models_directory(cls, output_path: Union[str, Path] = None):
        """
        Remove all extracted models from the models directory.

        Args:
            output_path: Optional path to clean. If None, uses default 'm3_models' folder.

        Example:
            >>> M3Model.clean_models_directory()
        """
        if output_path is None:
            target_dir = cls.models_dir
        else:
            target_dir = Path(output_path)
            if not target_dir.is_absolute():
                target_dir = Path.cwd() / target_dir

        logger.info(f"Cleaning models directory: {target_dir}")

        if target_dir.exists():
            try:
                shutil.rmtree(target_dir)
                logger.info("All models have been removed.")
            except Exception as e:
                logger.error(f"Failed to remove models directory: {e}")
                raise
        else:
            logger.warning("Models directory does not exist.")

        target_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Models directory cleaned and recreated.")
