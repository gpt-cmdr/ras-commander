"""
Indiana DNR H&H Model Library - HEC-RAS model source.

Provides access to ~11,400 HEC-RAS floodplain analysis models from the
Indiana Department of Natural Resources Hydrology & Hydraulics Model Library.

Programs represented: APPROX_ZoneA (5797), PERMIT (2616), FARA (1434),
FIS (1231), APPROX (889), LOMR (40), OTHER (16), HYDRO (3).

API: ArcGIS REST (gisdata.in.gov) with three-step download workflow:
  1. Query model metadata from HydromodelView_RO/FeatureServer/20
  2. Look up download link ID from HydroModelLibrary/FeatureServer/0
  3. Download ZIP from dowunity.dnr.in.gov

No authentication required.

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
3. Obtain the logger using: logger = get_logger(__name__)

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in IndianaDnrModels:
- list_models()
- download_model()
- get_source_status()
- list_counties()
- _get_download_link()
- _parse_hecras_version()
- _infer_model_type()
- _build_where_clause()
- _query_feature_server()
"""

import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import requests
from tqdm.auto import tqdm

import logging
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


class IndianaDnrModels:
    """
    Indiana DNR H&H Model Library - Floodplain analysis HEC-RAS models.

    Provides unified search and download access to ~11,400 HEC-RAS models
    published by the Indiana Department of Natural Resources. Models span
    multiple floodplain analysis programs including FEMA FIS studies,
    Approximate Zone A studies, FARA, permits, and LOMRs.

    All methods are static -- no instantiation required.

    Three-step download workflow:
      1. Query metadata via ArcGIS REST (HydromodelView_RO FeatureServer layer 20)
      2. Look up iimagelinkid via HydroModelLibrary FeatureServer layer 0
      3. Download ZIP from dowunity.dnr.in.gov/AppFileInfo/download

    Example:
        >>> from ras_commander.sources.state.in_dnr import IndianaDnrModels
        >>>
        >>> # List models in Marion County
        >>> models = IndianaDnrModels.list_models(location="MARION", limit=10)
        >>> for m in models:
        ...     print(f"{m.source_id}: {m.name} ({m.hecras_version})")
        >>>
        >>> # Download a specific model
        >>> result = IndianaDnrModels.download_model(
        ...     model_id=models[0].source_id,
        ...     output_folder="indiana_models"
        ... )
        >>> if result.success:
        ...     print(f"Downloaded to: {result.model_path}")
        >>>
        >>> # List all counties with model counts
        >>> counties = IndianaDnrModels.list_counties()
        >>> print(counties[:5])  # Top counties by name
    """

    SOURCE_NAME: str = "Indiana DNR"

    # ArcGIS REST endpoints (gisdata.in.gov -- maps.indiana.edu is dead)
    _METADATA_URL: str = (
        "https://gisdata.in.gov/server/rest/services/Hosted/"
        "HydromodelView_RO/FeatureServer/20/query"
    )
    _DOWNLOAD_LINK_URL: str = (
        "https://gisdata.in.gov/server/rest/services/Hosted/"
        "HydroModelLibrary/FeatureServer/0/query"
    )
    _DOWNLOAD_BASE_URL: str = (
        "https://dowunity.dnr.in.gov/AppFileInfo/download"
    )

    # Pagination settings
    _PAGE_SIZE: int = 1000

    # Known programs for reference / validation
    PROGRAMS: Tuple[str, ...] = (
        "APPROX_ZoneA", "PERMIT", "FARA", "FIS",
        "APPROX", "LOMR", "OTHER", "HYDRO",
    )

    @property
    def source_name(self) -> str:
        """Human-readable source name."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Source category."""
        return "state"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        Query ArcGIS REST for HEC-RAS models in the Indiana DNR library.

        Args:
            location: Filter by county name (scountyname), case-insensitive
                substring match. E.g. "MARION", "Hamilton", "Allen".
            model_type: Filter by ModelType enum. Most Indiana models are
                STEADY_1D; a few HEC-RAS 5.x models may be UNSTEADY_1D.
            hecras_version: Filter by exact HEC-RAS version string
                (e.g. "4.1.0", "5.0.7").
            tags: Filter by tags (AND logic). Matched against the program
                field (e.g. ["FIS"], ["PERMIT"]).
            limit: Maximum number of results to return. None returns all
                matching records (may be thousands -- use with caution).
            **kwargs: Additional filters:
                - river (str): Filter by water body name (swaterbodyname),
                  case-insensitive substring.
                - program (str): Filter by program name exactly
                  (e.g. "FIS", "PERMIT", "FARA").

        Returns:
            List of ModelMetadata objects matching all specified filters.

        Example:
            >>> # Models in Allen County
            >>> models = IndianaDnrModels.list_models(location="Allen", limit=5)
            >>>
            >>> # FIS models on specific river
            >>> models = IndianaDnrModels.list_models(
            ...     river="White River", program="FIS"
            ... )
        """
        river: Optional[str] = kwargs.get("river")
        program: Optional[str] = kwargs.get("program")

        where_clause = IndianaDnrModels._build_where_clause(
            location=location,
            river=river,
            program=program,
        )

        out_fields = (
            "hydromodelid,sitemmeta,swaterbodyname,scountyname,"
            "program,strhydromodelinfo,dtmhydromodeldate"
        )

        # Paginate through all results
        all_features: List[Dict] = []
        offset = 0

        while True:
            params: Dict = {
                "where": where_clause,
                "outFields": out_fields,
                "f": "json",
                "resultRecordCount": IndianaDnrModels._PAGE_SIZE,
                "resultOffset": offset,
                "returnGeometry": "false",
            }

            try:
                data = IndianaDnrModels._query_feature_server(
                    IndianaDnrModels._METADATA_URL, params
                )
            except Exception as exc:
                logger.error(f"Failed to query IN DNR metadata API: {exc}")
                return []

            features = data.get("features", [])
            if not features:
                break

            all_features.extend(features)
            logger.debug(
                f"Fetched {len(features)} records (offset={offset}, "
                f"total so far={len(all_features)})"
            )

            # If we got fewer than PAGE_SIZE, we've reached the end
            if len(features) < IndianaDnrModels._PAGE_SIZE:
                break

            offset += IndianaDnrModels._PAGE_SIZE

            # Early exit if we already have enough for the limit
            if limit and len(all_features) >= limit:
                break

        logger.debug(f"Retrieved {len(all_features)} total records from IN DNR API")

        # Convert features to ModelMetadata and apply post-query filters
        results: List[ModelMetadata] = []

        for feature in all_features:
            attrs = feature.get("attributes", {})
            metadata = IndianaDnrModels._parse_feature(attrs)

            # Post-query filter: model_type
            if model_type is not None and metadata.model_type != model_type:
                continue

            # Post-query filter: hecras_version (exact match)
            if hecras_version is not None and metadata.hecras_version != hecras_version:
                continue

            # Post-query filter: tags (AND logic)
            if tags:
                if not all(
                    any(t.lower() == meta_tag.lower() for meta_tag in metadata.tags)
                    for t in tags
                ):
                    continue

            results.append(metadata)

            if limit and len(results) >= limit:
                break

        logger.debug(
            f"Returning {len(results)} models after filtering "
            f"(from {len(all_features)} raw records)"
        )
        return results

    @staticmethod
    @log_call
    def download_model(
        model_id: Union[str, int],
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[Dict] = None,
    ) -> DownloadResult:
        """
        Download a HEC-RAS model from the Indiana DNR library.

        Three-step process:
          1. Look up iimagelinkid from the hydromodelid
          2. Download the ZIP archive from dowunity.dnr.in.gov
          3. Optionally extract the ZIP

        Args:
            model_id: The hydromodelid (from ModelMetadata.source_id).
                Can be string or int.
            output_folder: Directory where the model will be saved.
                A subfolder named after the model_id will be created.
            extract: If True, extract the downloaded ZIP archive.
            overwrite: If True, overwrite existing files.
            credentials: Not required (Indiana DNR is public access).

        Returns:
            DownloadResult with success status, model path, and metadata.

        Example:
            >>> result = IndianaDnrModels.download_model(
            ...     model_id="12345",
            ...     output_folder="my_models",
            ...     extract=True
            ... )
            >>> if result.success:
            ...     print(f"Model at: {result.model_path}")
        """
        model_id_str = str(model_id)
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        model_folder = output_folder / f"IN_DNR_{model_id_str}"

        # Check if already exists
        if model_folder.exists() and not overwrite:
            logger.debug(
                f"Model folder already exists: {model_folder}. "
                "Use overwrite=True to re-download."
            )
            return DownloadResult(
                success=True,
                model_path=model_folder,
                message="Model already downloaded (use overwrite=True to re-download)",
                metadata=None,
                extracted=extract,
            )

        # Step 1: Fetch model metadata for the DownloadResult
        metadata = IndianaDnrModels._fetch_single_model_metadata(model_id_str)

        # Step 2: Get download link ID
        try:
            image_link_id = IndianaDnrModels._get_download_link(model_id_str)
        except Exception as exc:
            logger.error(f"Failed to get download link for model {model_id_str}: {exc}")
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"Failed to get download link: {exc}",
                metadata=metadata,
            )

        if not image_link_id:
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"No download link found for hydromodelid={model_id_str}",
                metadata=metadata,
            )

        # Step 3: Download the ZIP
        download_url = (
            f"{IndianaDnrModels._DOWNLOAD_BASE_URL}?fileID={image_link_id}"
        )

        model_folder.mkdir(parents=True, exist_ok=True)
        zip_path = model_folder / f"IN_DNR_{model_id_str}.zip"

        logger.debug(f"Downloading model {model_id_str} from {download_url}")

        try:
            response = requests.get(download_url, stream=True, timeout=300)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            with open(zip_path, "wb") as f:
                if total_size > 0:
                    with tqdm(
                        desc=f"IN DNR model {model_id_str}",
                        total=total_size,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                        mininterval=2.0,
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            written = f.write(chunk)
                            pbar.update(written)
                else:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

            logger.debug(f"Downloaded ZIP to {zip_path}")

        except requests.exceptions.RequestException as exc:
            logger.error(f"Download failed for model {model_id_str}: {exc}")
            # Clean up partial download
            if zip_path.exists():
                zip_path.unlink()
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"Download failed: {exc}",
                metadata=metadata,
            )

        # Step 4: Extract if requested
        extracted = False
        if extract:
            try:
                logger.debug(f"Extracting {zip_path} to {model_folder}")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(model_folder)
                extracted = True
                logger.debug(f"Extraction complete for model {model_id_str}")

                # Remove ZIP after successful extraction
                zip_path.unlink()
                logger.debug(f"Removed temporary ZIP: {zip_path}")

            except (zipfile.BadZipFile, Exception) as exc:
                logger.warning(
                    f"Extraction failed for model {model_id_str}: {exc}. "
                    "ZIP file retained."
                )

        return DownloadResult(
            success=True,
            model_path=model_folder,
            message=(
                f"Successfully downloaded and {'extracted' if extracted else 'saved'} "
                f"model {model_id_str}"
            ),
            metadata=metadata,
            extracted=extracted,
        )

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """
        Check if the Indiana DNR ArcGIS REST API is reachable.

        Returns:
            SourceStatus.AVAILABLE if the API responds, UNAVAILABLE otherwise.

        Example:
            >>> status = IndianaDnrModels.get_source_status()
            >>> print(status)  # SourceStatus.AVAILABLE
        """
        try:
            params = {
                "where": "1=1",
                "outFields": "hydromodelid",
                "f": "json",
                "resultRecordCount": 1,
                "returnGeometry": "false",
            }
            response = requests.get(
                IndianaDnrModels._METADATA_URL,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            if "features" in data:
                logger.debug("Indiana DNR API is available")
                return SourceStatus.AVAILABLE
            else:
                logger.warning("Indiana DNR API returned unexpected response")
                return SourceStatus.UNAVAILABLE

        except Exception as exc:
            logger.warning(f"Indiana DNR API health check failed: {exc}")
            return SourceStatus.UNAVAILABLE

    @staticmethod
    @log_call
    def list_counties() -> List[str]:
        """
        Get distinct county names that have HEC-RAS models in the library.

        Returns:
            Sorted list of county name strings.
            Top counties include: Marion (477), Hamilton (421),
            Allen (419), Lake (359).

        Example:
            >>> counties = IndianaDnrModels.list_counties()
            >>> print(f"{len(counties)} counties with models")
            >>> print(counties[:10])
        """
        params = {
            "where": "sitemmeta LIKE '%HEC-RAS%'",
            "outFields": "scountyname",
            "returnDistinctValues": "true",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 200,
        }

        try:
            data = IndianaDnrModels._query_feature_server(
                IndianaDnrModels._METADATA_URL, params
            )
        except Exception as exc:
            logger.error(f"Failed to query counties: {exc}")
            return []

        counties: List[str] = []
        for feature in data.get("features", []):
            county = feature.get("attributes", {}).get("scountyname")
            if county and county.strip():
                counties.append(county.strip())

        counties = sorted(set(counties))
        logger.debug(f"Found {len(counties)} counties with HEC-RAS models")
        return counties

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def _get_download_link(hydromodelid: Union[str, int]) -> Optional[str]:
        """
        Step 2: Look up the iimagelinkid for a given hydromodelid.

        This queries the HydroModelLibrary FeatureServer to retrieve the
        file ID needed to construct the download URL.

        Args:
            hydromodelid: The model's unique hydromodelid.

        Returns:
            The iimagelinkid string, or None if not found.

        Raises:
            requests.exceptions.RequestException: On network errors.
        """
        params = {
            "where": f"lnghydromodelid={hydromodelid}",
            "outFields": "iimagelinkid",
            "f": "json",
            "returnGeometry": "false",
        }

        data = IndianaDnrModels._query_feature_server(
            IndianaDnrModels._DOWNLOAD_LINK_URL, params
        )

        features = data.get("features", [])
        if not features:
            logger.warning(
                f"No download link found for hydromodelid={hydromodelid}"
            )
            return None

        image_link_id = features[0].get("attributes", {}).get("iimagelinkid")
        if image_link_id is not None:
            image_link_id = str(image_link_id)
            logger.debug(
                f"Found iimagelinkid={image_link_id} for "
                f"hydromodelid={hydromodelid}"
            )

        return image_link_id

    @staticmethod
    def _query_feature_server(url: str, params: Dict) -> Dict:
        """
        Execute a query against an ArcGIS REST FeatureServer endpoint.

        Args:
            url: The full query URL for the FeatureServer layer.
            params: Query parameters dict.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            requests.exceptions.RequestException: On HTTP errors.
            ValueError: If response is not valid JSON or contains an error.
        """
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        # ArcGIS REST returns errors in the JSON body, not via HTTP status
        if "error" in data:
            error_info = data["error"]
            code = error_info.get("code", "unknown")
            message = error_info.get("message", "Unknown ArcGIS error")
            raise ValueError(
                f"ArcGIS REST error (code={code}): {message}"
            )

        return data

    @staticmethod
    def _build_where_clause(
        location: Optional[str] = None,
        river: Optional[str] = None,
        program: Optional[str] = None,
    ) -> str:
        """
        Build a SQL WHERE clause for the ArcGIS REST query.

        Always includes the base filter for HEC-RAS models. Additional
        filters are appended with AND.

        Args:
            location: County name substring filter (scountyname).
            river: Water body name substring filter (swaterbodyname).
            program: Exact program name filter (program).

        Returns:
            SQL WHERE clause string.
        """
        clauses: List[str] = ["sitemmeta LIKE '%HEC-RAS%'"]

        if location:
            # Case-insensitive LIKE for county
            safe_location = location.replace("'", "''")
            clauses.append(f"UPPER(scountyname) LIKE '%{safe_location.upper()}%'")

        if river:
            safe_river = river.replace("'", "''")
            clauses.append(f"UPPER(swaterbodyname) LIKE '%{safe_river.upper()}%'")

        if program:
            safe_program = program.replace("'", "''")
            clauses.append(f"program = '{safe_program}'")

        return " AND ".join(clauses)

    @staticmethod
    def _parse_feature(attrs: Dict) -> ModelMetadata:
        """
        Parse a single ArcGIS feature's attributes into a ModelMetadata.

        Args:
            attrs: The 'attributes' dict from a feature JSON object.

        Returns:
            A ModelMetadata instance populated from the feature attributes.
        """
        hydromodelid = str(attrs.get("hydromodelid", ""))
        sitemmeta = attrs.get("sitemmeta") or ""
        water_body = attrs.get("swaterbodyname") or "Unknown"
        county = attrs.get("scountyname") or "Unknown"
        program = attrs.get("program") or ""
        description = attrs.get("strhydromodelinfo") or ""
        model_date_raw = attrs.get("dtmhydromodeldate")

        # Parse HEC-RAS version from sitemmeta
        hecras_version = IndianaDnrModels._parse_hecras_version(sitemmeta)

        # Infer model type
        model_type = IndianaDnrModels._infer_model_type(sitemmeta, hecras_version)

        # Build location string
        location = f"{county} County, Indiana"
        if water_body and water_body != "Unknown":
            location = f"{water_body}, {location}"

        # Build human-readable name
        name_parts: List[str] = []
        if water_body and water_body != "Unknown":
            name_parts.append(water_body)
        if county and county != "Unknown":
            name_parts.append(f"{county} Co")
        if program:
            name_parts.append(f"({program})")
        name = " - ".join(name_parts) if name_parts else f"IN DNR Model {hydromodelid}"

        # Parse model date (ArcGIS returns epoch milliseconds or ISO string)
        study_date: Optional[str] = None
        last_modified: Optional[datetime] = None
        if model_date_raw is not None:
            try:
                if isinstance(model_date_raw, (int, float)) and model_date_raw > 0:
                    # Epoch milliseconds
                    dt = datetime.utcfromtimestamp(model_date_raw / 1000.0)
                    study_date = dt.strftime("%Y-%m-%d")
                    last_modified = dt
                elif isinstance(model_date_raw, str) and model_date_raw.strip():
                    dt = datetime.fromisoformat(
                        model_date_raw.replace("Z", "+00:00")
                    )
                    study_date = dt.strftime("%Y-%m-%d")
                    last_modified = dt
            except (ValueError, OSError, OverflowError):
                logger.debug(
                    f"Could not parse date '{model_date_raw}' for "
                    f"hydromodelid={hydromodelid}"
                )

        # Build tags from program and software info
        tags: List[str] = ["Indiana", "DNR", "floodplain"]
        if program:
            tags.append(program)
        if hecras_version:
            tags.append(f"HEC-RAS {hecras_version}")

        return ModelMetadata(
            source_name="Indiana DNR",
            source_id=hydromodelid,
            name=name,
            description=description if description else f"Indiana DNR {program} model",
            location=location,
            model_type=model_type,
            hecras_version=hecras_version,
            url=None,  # URL requires two-step lookup, set on download
            tags=tags,
            study_date=study_date,
            last_modified=last_modified,
        )

    @staticmethod
    def _parse_hecras_version(sitemmeta: str) -> Optional[str]:
        """
        Extract HEC-RAS version from the sitemmeta field.

        The sitemmeta field typically contains strings like:
          "HEC-RAS 4.1.0", "HEC-RAS 5.0.7", "HEC-RAS 3.1.3"

        Args:
            sitemmeta: Raw software metadata string from the API.

        Returns:
            Version string (e.g. "4.1.0", "5.0.7") or None if not found.

        Example:
            >>> IndianaDnrModels._parse_hecras_version("HEC-RAS 4.1.0")
            '4.1.0'
            >>> IndianaDnrModels._parse_hecras_version("HEC-RAS")
            None
        """
        if not sitemmeta:
            return None

        match = re.search(r"HEC-RAS\s+([\d]+(?:\.[\d]+)*)", sitemmeta, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _infer_model_type(
        sitemmeta: str, hecras_version: Optional[str]
    ) -> ModelType:
        """
        Infer the model type from software metadata and version.

        The vast majority of Indiana DNR models are 1D steady-state.
        Some HEC-RAS 5.x models may include unsteady plans. No 2D or
        rain-on-grid models are known in this library.

        Args:
            sitemmeta: Raw software metadata string.
            hecras_version: Parsed HEC-RAS version (e.g. "5.0.7").

        Returns:
            ModelType enum value.
        """
        text = (sitemmeta or "").lower()

        if "unsteady" in text:
            return ModelType.UNSTEADY_1D

        if "2d" in text or "two-dimensional" in text:
            return ModelType.UNSTEADY_2D

        if "dam breach" in text or "dam break" in text:
            return ModelType.DAM_BREACH

        if "sediment" in text:
            return ModelType.SEDIMENT

        # Default: the vast majority are 1D steady
        return ModelType.STEADY_1D

    @staticmethod
    def _fetch_single_model_metadata(
        hydromodelid: Union[str, int],
    ) -> Optional[ModelMetadata]:
        """
        Fetch metadata for a single model by its hydromodelid.

        Args:
            hydromodelid: The model's unique identifier.

        Returns:
            ModelMetadata if found, None otherwise.
        """
        params = {
            "where": f"hydromodelid={hydromodelid}",
            "outFields": (
                "hydromodelid,sitemmeta,swaterbodyname,scountyname,"
                "program,strhydromodelinfo,dtmhydromodeldate"
            ),
            "f": "json",
            "resultRecordCount": 1,
            "returnGeometry": "false",
        }

        try:
            data = IndianaDnrModels._query_feature_server(
                IndianaDnrModels._METADATA_URL, params
            )
            features = data.get("features", [])
            if features:
                return IndianaDnrModels._parse_feature(
                    features[0].get("attributes", {})
                )
        except Exception as exc:
            logger.warning(
                f"Could not fetch metadata for hydromodelid={hydromodelid}: {exc}"
            )

        return None
