"""
Minnesota DNR Hydraulic Model Download - FEMA floodplain HEC-RAS models.

This module provides access to the Minnesota Department of Natural Resources
Hydraulic Model Download portal, which hosts ~2,384 HEC-RAS models covering
FEMA-effective floodplain studies across Minnesota counties.

All models in this portal are 1D steady-state HEC-RAS models.

Data source: MN DNR Hydraulic Model Download application
API: ArcGIS REST MapServer (Table layer ID 1, "Models")
Download: Azure Function endpoint (no authentication required)

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

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in MinnesotaDnrModels:
- list_models()
- download_model()
- get_source_status()
- list_counties()
"""

import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import requests
from tqdm.auto import tqdm

from ras_commander import get_logger
from ras_commander.LoggingConfig import log_call
from ras_commander.sources.base import (
    DownloadResult,
    ModelMetadata,
    ModelSource,
    ModelType,
    SourceStatus,
)

logger = get_logger(__name__)


class MinnesotaDnrModels:
    """
    Minnesota DNR Hydraulic Model Download - FEMA floodplain HEC-RAS models.

    Provides discovery and download of ~2,384 HEC-RAS models from the Minnesota
    DNR Hydraulic Model Download portal. All models are 1D steady-state and
    represent FEMA-effective floodplain studies.

    All methods are static/class methods, so no initialization is required.

    Example:
        # List all models
        models = MinnesotaDnrModels.list_models()

        # Filter by county
        models = MinnesotaDnrModels.list_models(location="Hennepin")

        # List available counties
        counties = MinnesotaDnrModels.list_counties()

        # Download a model
        result = MinnesotaDnrModels.download_model(
            "Hennepin/Some_Model",
            output_folder="mn_models"
        )

        # Check API status
        status = MinnesotaDnrModels.get_source_status()
    """

    SOURCE_NAME: str = "Minnesota DNR"

    # ArcGIS REST MapServer endpoint (Table layer ID 1 = "Models")
    _CATALOG_URL: str = (
        "https://gis.dnr.state.mn.us/appserver/rest/services/"
        "ewr/app_hydraulic_model_download/MapServer/1/query"
    )

    # Azure Function download endpoint
    _DOWNLOAD_BASE_URL: str = (
        "https://r29p-hydradownload-func-001-gqefa2d2hbh3gtbk."
        "centralus-01.azurewebsites.net/fileget"
    )

    # ArcGIS REST pagination limit
    _PAGE_SIZE: int = 2000

    # HTTP request timeout in seconds
    _REQUEST_TIMEOUT: int = 60

    # Download chunk size in bytes
    _DOWNLOAD_CHUNK_SIZE: int = 8192

    # For ModelSource protocol
    @property
    def source_name(self) -> str:
        """Human-readable source name."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Source category."""
        return "state"

    @staticmethod
    @log_call
    def list_models(
        location: Optional[str] = None,
        model_type: Optional[ModelType] = None,
        hecras_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[ModelMetadata]:
        """
        Query MN DNR ArcGIS REST API for HEC-RAS models.

        Queries the Models table (layer ID 1) of the MN DNR Hydraulic Model
        Download MapServer. Handles pagination automatically since the API
        returns a maximum of 2000 records per request.

        Args:
            location: Filter by county name (case-insensitive substring match).
            model_type: Ignored -- all MN DNR models are STEADY_1D.
            hecras_version: Filter by HEC-RAS version string (substring match).
            tags: Ignored -- MN DNR catalog does not provide tags.
            limit: Maximum number of results to return. None returns all.
            **kwargs: Additional keyword arguments (reserved for future use).

        Returns:
            List of ModelMetadata objects matching the query criteria.

        Raises:
            requests.exceptions.RequestException: If the API is unreachable.

        Example:
            >>> models = MinnesotaDnrModels.list_models(location="Hennepin")
            >>> print(f"Found {len(models)} models in Hennepin County")
            >>> for m in models[:5]:
            ...     print(f"  {m.name} ({m.source_id})")
        """
        # All MN DNR models are 1D steady; if caller asks for another type, return empty
        if model_type is not None and model_type != ModelType.STEADY_1D:
            logger.debug(
                f"MN DNR only has STEADY_1D models; requested {model_type.value}, "
                "returning empty list"
            )
            return []

        # Build the WHERE clause for the ArcGIS query
        where_clauses: List[str] = ["hydraulic_model_used LIKE '%HEC-RAS%'"]
        if location:
            safe_location = location.replace("'", "''")
            where_clauses.append(f"county LIKE '%{safe_location}%'")
        if hecras_version:
            safe_version = hecras_version.replace("'", "''")
            where_clauses.append(
                f"hydraulic_model_used LIKE '%{safe_version}%'"
            )

        where = " AND ".join(where_clauses)

        # Paginate through all results
        all_features: List[Dict] = []
        offset = 0
        total_fetched = 0

        logger.debug(f"Querying MN DNR catalog: WHERE {where}")

        while True:
            params = {
                "where": where,
                "outFields": "*",
                "f": "json",
                "resultRecordCount": MinnesotaDnrModels._PAGE_SIZE,
                "resultOffset": offset,
            }

            try:
                response = requests.get(
                    MinnesotaDnrModels._CATALOG_URL,
                    params=params,
                    timeout=MinnesotaDnrModels._REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to query MN DNR catalog: {e}")
                raise

            features = data.get("features", [])
            if not features:
                break

            all_features.extend(features)
            total_fetched += len(features)

            logger.debug(
                f"Fetched {len(features)} records (offset={offset}, "
                f"total={total_fetched})"
            )

            # If we got fewer than the page size, we have all records
            if len(features) < MinnesotaDnrModels._PAGE_SIZE:
                break

            # Check if limit is already satisfied
            if limit is not None and total_fetched >= limit:
                break

            offset += MinnesotaDnrModels._PAGE_SIZE

        logger.debug(f"Retrieved {total_fetched} total records from MN DNR")

        # Convert features to ModelMetadata
        results: List[ModelMetadata] = []
        for feature in all_features:
            attrs = feature.get("attributes", {})
            metadata = MinnesotaDnrModels._feature_to_metadata(attrs)
            if metadata is not None:
                results.append(metadata)

            if limit is not None and len(results) >= limit:
                break

        logger.debug(
            f"Returning {len(results)} models"
            + (f" (limit={limit})" if limit else "")
        )
        return results

    @staticmethod
    @log_call
    def download_model(
        model_id: str,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
    ) -> DownloadResult:
        """
        Download a model ZIP from MN DNR.

        The model_id must be in the format "CountyName/model_name" (matching
        the source_id stored in ModelMetadata). The download is served by an
        Azure Function endpoint and requires no authentication.

        Args:
            model_id: Model identifier in "County/ModelName" format. This
                corresponds to the source_id field of ModelMetadata objects
                returned by list_models().
            output_folder: Directory where the downloaded (and optionally
                extracted) model will be placed.
            extract: If True, extract the ZIP archive after download and
                remove the ZIP file. If False, keep the ZIP only.
            overwrite: If True, overwrite existing files. If False and the
                output already exists, skip the download.
            credentials: Ignored -- MN DNR downloads are public.

        Returns:
            DownloadResult with success status, output path, and message.

        Example:
            >>> result = MinnesotaDnrModels.download_model(
            ...     "Hennepin/Example_Model",
            ...     output_folder="mn_models",
            ...     extract=True,
            ... )
            >>> if result.success:
            ...     print(f"Downloaded to: {result.model_path}")
        """
        # Validate model_id format
        if "/" not in model_id:
            msg = (
                f"Invalid model_id '{model_id}'. Expected format: "
                "'CountyName/model_name' (as returned in ModelMetadata.source_id)"
            )
            logger.error(msg)
            return DownloadResult(
                success=False, model_path=None, message=msg
            )

        county, model_name = model_id.split("/", 1)

        output_path = Path(output_folder)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.mkdir(parents=True, exist_ok=True)

        zip_filename = f"{model_name}.zip"
        zip_path = output_path / zip_filename
        extract_dir = output_path / model_name

        # Check if already downloaded
        if not overwrite:
            if extract and extract_dir.exists():
                msg = (
                    f"Model already extracted at {extract_dir}. "
                    "Use overwrite=True to re-download."
                )
                logger.debug(msg)
                return DownloadResult(
                    success=True,
                    model_path=extract_dir,
                    message=msg,
                    extracted=True,
                )
            if not extract and zip_path.exists():
                msg = (
                    f"Model ZIP already exists at {zip_path}. "
                    "Use overwrite=True to re-download."
                )
                logger.debug(msg)
                return DownloadResult(
                    success=True,
                    model_path=zip_path,
                    message=msg,
                    extracted=False,
                )

        # Build download URL
        download_url = (
            f"{MinnesotaDnrModels._DOWNLOAD_BASE_URL}"
            f"?filename={county}/{model_name}.zip"
        )

        logger.debug(f"Downloading MN DNR model: {model_id}")
        logger.debug(f"URL: {download_url}")

        # Download with progress bar
        try:
            response = requests.get(
                download_url, stream=True, timeout=300
            )
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            with open(zip_path, "wb") as f:
                if total_size > 0:
                    with tqdm(
                        desc=f"Downloading {model_name}",
                        total=total_size,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                        mininterval=2.0,
                    ) as progress_bar:
                        for chunk in response.iter_content(
                            chunk_size=MinnesotaDnrModels._DOWNLOAD_CHUNK_SIZE
                        ):
                            size = f.write(chunk)
                            progress_bar.update(size)
                else:
                    for chunk in response.iter_content(
                        chunk_size=MinnesotaDnrModels._DOWNLOAD_CHUNK_SIZE
                    ):
                        f.write(chunk)

            logger.debug(f"Downloaded to {zip_path}")

        except requests.exceptions.RequestException as e:
            msg = f"Failed to download model '{model_id}': {e}"
            logger.error(msg)
            if zip_path.exists():
                zip_path.unlink()
            return DownloadResult(
                success=False, model_path=None, message=msg
            )

        # Extract if requested
        if extract:
            logger.debug(f"Extracting to {extract_dir}...")
            try:
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
                logger.debug(
                    f"Successfully extracted model '{model_id}' to {extract_dir}"
                )
            except (zipfile.BadZipFile, Exception) as e:
                msg = f"Failed to extract model '{model_id}': {e}"
                logger.error(msg)
                return DownloadResult(
                    success=False,
                    model_path=zip_path,
                    message=msg,
                    extracted=False,
                )
            finally:
                # Clean up ZIP after successful extraction
                if extract_dir.exists() and any(extract_dir.iterdir()):
                    if zip_path.exists():
                        zip_path.unlink()
                        logger.debug(f"Removed temporary zip: {zip_path}")

            return DownloadResult(
                success=True,
                model_path=extract_dir,
                message=f"Model '{model_id}' downloaded and extracted to {extract_dir}",
                extracted=True,
            )

        return DownloadResult(
            success=True,
            model_path=zip_path,
            message=f"Model '{model_id}' downloaded to {zip_path}",
            extracted=False,
        )

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """
        Check if the MN DNR Hydraulic Model Download API is reachable.

        Performs a lightweight query (1 record) against the MapServer endpoint
        to verify connectivity and service availability.

        Returns:
            SourceStatus.AVAILABLE if the API responds successfully,
            SourceStatus.UNAVAILABLE otherwise.

        Example:
            >>> status = MinnesotaDnrModels.get_source_status()
            >>> if status == SourceStatus.AVAILABLE:
            ...     print("MN DNR API is online")
        """
        params = {
            "where": "1=1",
            "outFields": "objectid",
            "f": "json",
            "resultRecordCount": 1,
        }

        try:
            response = requests.get(
                MinnesotaDnrModels._CATALOG_URL,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            if "features" in data and len(data["features"]) > 0:
                logger.debug("MN DNR API is available")
                return SourceStatus.AVAILABLE
            elif "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                logger.warning(f"MN DNR API returned error: {error_msg}")
                return SourceStatus.UNAVAILABLE
            else:
                logger.warning("MN DNR API returned unexpected response")
                return SourceStatus.UNAVAILABLE

        except requests.exceptions.RequestException as e:
            logger.warning(f"MN DNR API is unreachable: {e}")
            return SourceStatus.UNAVAILABLE

    @staticmethod
    @log_call
    def list_counties() -> List[str]:
        """
        Get distinct county names from the MN DNR catalog.

        Paginates through all HEC-RAS records and deduplicates county names
        client-side (the MapServer table does not support returnDistinctValues).

        Returns:
            Sorted list of county name strings.
        """
        counties: set = set()
        offset = 0

        while True:
            params = {
                "where": "hydraulic_model_used LIKE '%HEC-RAS%'",
                "outFields": "county",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": MinnesotaDnrModels._PAGE_SIZE,
                "resultOffset": offset,
            }
            try:
                response = requests.get(
                    MinnesotaDnrModels._CATALOG_URL,
                    params=params,
                    timeout=MinnesotaDnrModels._REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to query MN DNR for counties: {e}")
                raise

            features = data.get("features", [])
            if not features:
                break

            for feature in features:
                county = (feature.get("attributes", {}).get("county") or "").strip()
                if county:
                    counties.add(county)

            if len(features) < MinnesotaDnrModels._PAGE_SIZE:
                break
            offset += MinnesotaDnrModels._PAGE_SIZE

        result = sorted(counties)
        logger.debug(f"Found {len(result)} counties with HEC-RAS models")
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _feature_to_metadata(attrs: Dict) -> Optional[ModelMetadata]:
        """
        Convert a single ArcGIS feature attributes dict to ModelMetadata.

        Args:
            attrs: Dictionary of attribute values from an ArcGIS REST feature.

        Returns:
            ModelMetadata if the feature has enough data, None otherwise.
        """
        # Extract fields — actual API field names from MapServer/1
        model_name: str = (
            attrs.get("hydraulic_model_name") or ""
        ).strip()
        county: str = (
            attrs.get("county") or ""
        ).strip()
        water_name: str = (
            attrs.get("water_name") or ""
        ).strip()
        hydraulic_model: str = (
            attrs.get("hydraulic_model_used") or ""
        ).strip()
        flood_zone: str = (
            attrs.get("flood_zone") or ""
        ).strip()
        download_url_raw: str = (
            attrs.get("url") or ""
        ).strip()
        objectid = attrs.get("objectid")

        if not model_name:
            return None

        # Build source_id as County/ModelName for download URL construction
        source_id = f"{county}/{model_name}" if county else model_name

        # Build description from available fields
        description_parts: List[str] = []
        if water_name:
            description_parts.append(water_name)
        if flood_zone:
            description_parts.append(f"Zone {flood_zone}")
        if hydraulic_model:
            description_parts.append(hydraulic_model)
        description = "; ".join(description_parts) if description_parts else (
            f"FEMA floodplain HEC-RAS model in {county} County, MN"
            if county
            else "FEMA floodplain HEC-RAS model from MN DNR"
        )

        # Build location string
        location = f"{county} County, Minnesota" if county else "Minnesota"

        # Extract HEC-RAS version from hydraulic_model_used if possible
        hecras_version = MinnesotaDnrModels._parse_hecras_version(
            hydraulic_model
        )

        # Use the URL field from the API directly, or construct it
        download_url = download_url_raw or None
        if not download_url and county and model_name:
            download_url = (
                f"{MinnesotaDnrModels._DOWNLOAD_BASE_URL}"
                f"?filename={county}/{model_name}.zip"
            )

        # Build tags
        tags: List[str] = ["FEMA", "floodplain", "Minnesota", "1D", "steady"]
        if county:
            tags.append(county)
        if water_name:
            tags.append(water_name)

        return ModelMetadata(
            source_name=MinnesotaDnrModels.SOURCE_NAME,
            source_id=source_id,
            name=model_name,
            description=description,
            location=location,
            model_type=ModelType.STEADY_1D,
            hecras_version=hecras_version,
            doi=None,
            url=download_url,
            file_size_mb=None,
            last_modified=None,
            projection=None,
            tags=tags,
            spatial_extent=None,
            study_date=None,
            effective_date=None,
        )

    @staticmethod
    def _parse_hecras_version(hydraulic_model_str: str) -> Optional[str]:
        """
        Attempt to extract a HEC-RAS version number from the
        hydraulic_model_used field.

        Args:
            hydraulic_model_str: Raw string like "HEC-RAS 5.0.7" or
                "HEC-RAS Version 4.1".

        Returns:
            Version string (e.g., "5.0.7") if found, None otherwise.
        """
        if not hydraulic_model_str:
            return None

        import re

        # Match patterns like "HEC-RAS 5.0.7", "HEC-RAS Version 4.1",
        # "HEC-RAS v6.0"
        match = re.search(
            r"HEC-RAS\s*(?:Version\s*|v)?(\d+(?:\.\d+)*)",
            hydraulic_model_str,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        return None
