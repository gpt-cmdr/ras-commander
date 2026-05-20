"""
Colorado CWCB CHAMP (Colorado Hazard Mapping Program) HEC-RAS model source.

Provides access to hydraulic models published through the CHAMP portal.
This is a small source (~2 actual HEC-RAS models) included for completeness.

API: https://coloradohazardmapping.com/api/hydraulicModels
Download: https://coloradohazardmapping.com/file/{UUID}
"""

import logging
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Union

import requests

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

CHAMP_API_URL = "https://coloradohazardmapping.com/api/hydraulicModels"
CHAMP_FILE_URL = "https://coloradohazardmapping.com/file/{uuid}"
REQUEST_TIMEOUT = 30


class ColoradoChampModels:
    """
    Colorado CWCB CHAMP - Colorado Hazard Mapping Program hydraulic models.

    Queries the CHAMP portal for published HEC-RAS hydraulic models.
    The catalog is very small (~8 entries total, ~2 with actual HEC-RAS files),
    so no pagination is needed. No authentication required.

    Example:
        >>> source = ColoradoChampModels()
        >>> models = source.list_models(location="Boulder")
        >>> result = source.download_model(
        ...     model_id=models[0].source_id,
        ...     output_folder="champ_models"
        ... )
    """

    SOURCE_NAME = "Colorado CHAMP"

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
        Query CHAMP API for HEC-RAS hydraulic models.

        Args:
            location: Filter by county name (case-insensitive substring match)
            model_type: Filter by model type (most CHAMP models are STEADY_1D)
            hecras_version: Filter by HEC-RAS version string
            tags: Filter by tags (AND logic)
            limit: Maximum number of results to return
            **kwargs: Additional filters (unused)

        Returns:
            List of ModelMetadata for matching HEC-RAS models
        """
        try:
            response = requests.get(CHAMP_API_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            items = response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to query CHAMP API: {e}")
            return []
        except ValueError as e:
            logger.error(f"Invalid JSON from CHAMP API: {e}")
            return []

        if not isinstance(items, dict):
            logger.error(f"Unexpected CHAMP API response type: {type(items)}")
            return []

        models: List[ModelMetadata] = []

        for uuid, item in items.items():
            title = item.get("title", "") or ""
            # Skip entries explicitly marked as having no models
            if "(no models)" in title.lower() or "(without models)" in title.lower():
                continue

            metadata = _parse_champ_item(uuid, item)

            if location and location.lower() not in metadata.location.lower():
                continue
            if model_type and metadata.model_type != model_type:
                continue
            if hecras_version and metadata.hecras_version != hecras_version:
                continue
            if tags and not all(tag in metadata.tags for tag in tags):
                continue

            models.append(metadata)

            if limit and len(models) >= limit:
                break

        logger.info(f"Found {len(models)} models in CHAMP catalog")
        return models

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
        Download a model by UUID from CHAMP.

        Args:
            model_id: The UUID string for the model file
            output_folder: Directory to save the downloaded model
            extract: Whether to extract ZIP archives after download
            overwrite: Whether to overwrite existing files
            credentials: Not required (CHAMP is public)

        Returns:
            DownloadResult with download status and path
        """
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        # Fetch catalog to get metadata for this model
        metadata = _find_model_by_uuid(model_id)
        if metadata is None:
            # Build a minimal metadata for the result
            metadata = ModelMetadata(
                source_name="Colorado CHAMP",
                source_id=model_id,
                name=f"CHAMP Model {model_id[:8]}",
                description="",
                location="Colorado",
                model_type=ModelType.UNKNOWN,
            )

        # Build output path
        safe_name = re.sub(r"[^\w\s-]", "", metadata.name).strip().replace(" ", "_")
        if not safe_name:
            safe_name = model_id[:12]
        model_folder = output_folder / safe_name

        if model_folder.exists() and not overwrite:
            if any(model_folder.rglob("*.prj")):
                logger.debug(f"Model folder already exists with content: {model_folder}")
                return DownloadResult(
                    success=True,
                    model_path=model_folder,
                    message="Model already downloaded (use overwrite=True to re-download)",
                    metadata=metadata,
                    extracted=extract,
                )
            logger.warning(
                f"Model folder exists but contains no .prj file (possibly a failed prior download); re-downloading: {model_folder}"
            )

        model_folder.mkdir(parents=True, exist_ok=True)

        # Download file
        download_url = CHAMP_FILE_URL.format(uuid=model_id)
        logger.debug(f"Downloading from {download_url}")

        try:
            response = requests.get(download_url, stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Download failed for {model_id}: {e}")
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"Download failed: {e}",
                metadata=metadata,
            )

        # Determine filename from Content-Disposition header or fallback
        filename = _extract_filename(response) or f"{model_id[:12]}.zip"
        file_path = model_folder / filename

        # Stream to disk with optional progress
        total_size = int(response.headers.get("content-length", 0))
        try:
            from tqdm import tqdm

            progress = tqdm(
                total=total_size or None,
                unit="B",
                unit_scale=True,
                desc=filename,
                disable=total_size == 0,
            )
        except ImportError:
            progress = None

        try:
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    if progress is not None:
                        progress.update(len(chunk))
        finally:
            if progress is not None:
                progress.close()

        logger.debug(f"Downloaded {file_path.name} ({file_path.stat().st_size} bytes)")

        # Extract if ZIP
        extracted = False
        if extract and file_path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(model_folder)
                extracted = True
                logger.debug(f"Extracted {file_path.name} to {model_folder}")
            except zipfile.BadZipFile:
                logger.warning(f"{file_path.name} is not a valid ZIP archive")

        return DownloadResult(
            success=True,
            model_path=model_folder,
            message=f"Successfully downloaded {file_path.name}",
            metadata=metadata,
            extracted=extracted,
        )

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """
        Check if the CHAMP API is reachable.

        Returns:
            SourceStatus.AVAILABLE if the API responds, UNAVAILABLE otherwise
        """
        try:
            response = requests.get(CHAMP_API_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return SourceStatus.AVAILABLE
        except requests.RequestException as e:
            logger.warning(f"CHAMP API unreachable: {e}")
            return SourceStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_champ_item(uuid: str, item: dict) -> ModelMetadata:
    """Parse a CHAMP API entry (UUID + item dict) into ModelMetadata."""
    title = item.get("title", "") or "Unnamed Study"
    desc_obj = item.get("description", {})
    description = desc_obj.get("html", "") if isinstance(desc_obj, dict) else str(desc_obj)
    file_info = item.get("file", {}) or {}
    file_size_bytes = file_info.get("fileSizeBytes", 0) or 0
    file_size_mb = round(file_size_bytes / (1024 * 1024), 1) if file_size_bytes else None

    # Infer model type from title/description
    model_type = ModelType.STEADY_1D
    text = (title + " " + description).lower()
    if "2d" in text or "two-dimensional" in text:
        model_type = ModelType.UNSTEADY_2D
    elif "unsteady" in text:
        model_type = ModelType.UNSTEADY_1D

    # Extract HEC-RAS version if mentioned
    hecras_version = None
    version_match = re.search(r"HEC-RAS\s+(\d+\.?\d*)", text, re.IGNORECASE)
    if version_match:
        hecras_version = version_match.group(1)

    tags: List[str] = ["colorado", "champ", "cwcb"]

    download_url = CHAMP_FILE_URL.format(uuid=uuid)

    return ModelMetadata(
        source_name="Colorado CHAMP",
        source_id=uuid,
        name=title,
        description=description[:200] if description else "CHAMP hydraulic model",
        location="Colorado",
        model_type=model_type,
        hecras_version=hecras_version,
        url=download_url,
        file_size_mb=file_size_mb,
        tags=tags,
    )


def _find_model_by_uuid(uuid: str) -> Optional[ModelMetadata]:
    """Fetch the full catalog and find the entry matching the given UUID."""
    try:
        response = requests.get(CHAMP_API_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        items = response.json()
    except Exception:
        return None

    if not isinstance(items, dict):
        return None

    item = items.get(uuid)
    if item:
        return _parse_champ_item(uuid, item)
    return None


def _extract_filename(response: requests.Response) -> Optional[str]:
    """Extract filename from Content-Disposition header if present."""
    cd = response.headers.get("Content-Disposition", "")
    if not cd:
        return None
    match = re.search(r'filename[*]?=["\']?([^"\';]+)', cd)
    return match.group(1).strip() if match else None
