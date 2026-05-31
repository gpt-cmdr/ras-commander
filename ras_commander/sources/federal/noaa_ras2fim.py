"""NOAA OWP ras2fim model-source catalog adapter.

The public notebook examples use this source as a lightweight catalog entry for
ras2fim HEC-RAS-derived flood-inundation products. The source data are stored in
the NOAA/ESIP S3 bucket and typically require AWS credentials, so this adapter
keeps a small built-in registry available without making boto3 a package
dependency or attempting large downloads implicitly.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union

from ras_commander.LoggingConfig import log_call
from ras_commander.sources.base import (
    DownloadResult,
    ModelMetadata,
    ModelType,
    SourceStatus,
)

NOAA_RAS2FIM_BUCKET = "noaa-nws-owp-fim"
NOAA_RAS2FIM_PREFIX = "ras2fim"


class NoaaRas2fimModels:
    """Catalog-only adapter for NOAA OWP ras2fim model products."""

    SOURCE_NAME = "NOAA ras2fim"
    SOURCE_TYPE = "federal"

    _MODEL_REGISTRY: Dict[str, Dict[str, object]] = {
        "03100204": {
            "name": "NOAA ras2fim HUC 03100204",
            "location": "03100204",
            "description": (
                "NOAA OWP ras2fim flood-inundation model products for HUC8 "
                "03100204."
            ),
            "tags": ["noaa", "owp", "ras2fim", "fim", "huc8"],
        },
        "12090301": {
            "name": "NOAA ras2fim HUC 12090301",
            "location": "12090301",
            "description": (
                "NOAA OWP ras2fim flood-inundation model products for HUC8 "
                "12090301."
            ),
            "tags": ["noaa", "owp", "ras2fim", "fim", "huc8"],
        },
        "12040102": {
            "name": "NOAA ras2fim HUC 12040102",
            "location": "12040102",
            "description": (
                "NOAA OWP ras2fim flood-inundation model products for HUC8 "
                "12040102."
            ),
            "tags": ["noaa", "owp", "ras2fim", "fim", "huc8"],
        },
        "08070202": {
            "name": "NOAA ras2fim HUC 08070202",
            "location": "08070202",
            "description": (
                "NOAA OWP ras2fim flood-inundation model products for HUC8 "
                "08070202."
            ),
            "tags": ["noaa", "owp", "ras2fim", "fim", "huc8"],
        },
        "11010011": {
            "name": "NOAA ras2fim HUC 11010011",
            "location": "11010011",
            "description": (
                "NOAA OWP ras2fim flood-inundation model products for HUC8 "
                "11010011."
            ),
            "tags": ["noaa", "owp", "ras2fim", "fim", "huc8"],
        },
    }

    @property
    def source_name(self) -> str:
        """Human-readable source name."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Source category."""
        return self.SOURCE_TYPE

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """
        Return source availability.

        ras2fim products are generally stored behind the ESIP credentialed S3
        workflow, but the built-in catalog is available without credentials.
        """
        return SourceStatus.REQUIRES_AUTH

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
        """Return built-in NOAA ras2fim catalog metadata."""
        results: List[ModelMetadata] = []
        for huc8, info in NoaaRas2fimModels._MODEL_REGISTRY.items():
            metadata = NoaaRas2fimModels._metadata_from_registry(huc8, info)

            if location and location.lower() not in metadata.location.lower():
                continue
            if model_type and metadata.model_type != model_type:
                continue
            if hecras_version and metadata.hecras_version != hecras_version:
                continue
            if tags and not all(tag in metadata.tags for tag in tags):
                continue

            results.append(metadata)
            if limit and len(results) >= limit:
                break

        return results

    @staticmethod
    @log_call
    def list_catalog_models(**kwargs) -> List[ModelMetadata]:
        """Return catalog metadata for ModelCatalog integration."""
        return NoaaRas2fimModels.list_models(**kwargs)

    @staticmethod
    @log_call
    def download_model(
        model_id: str,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
        **kwargs,
    ) -> DownloadResult:
        """
        Report that NOAA ras2fim download is credentialed and not automatic.

        The source is intentionally catalog-only in ras-commander examples to
        avoid accidental large S3 transfers from the ras2fim archive.
        """
        metadata = NoaaRas2fimModels._find_metadata(model_id)
        return DownloadResult(
            success=False,
            model_path=None,
            message=(
                "NOAA ras2fim downloads require the ESIP/AWS credentialed S3 "
                "workflow and are not performed automatically by this catalog "
                "adapter."
            ),
            metadata=metadata,
            extracted=False,
        )

    @staticmethod
    def _metadata_from_registry(
        huc8: str,
        info: Dict[str, object],
    ) -> ModelMetadata:
        s3_prefix = f"{NOAA_RAS2FIM_PREFIX}/{huc8}/"
        return ModelMetadata(
            source_name=NoaaRas2fimModels.SOURCE_NAME,
            source_id=huc8,
            name=str(info["name"]),
            description=str(info.get("description", "")),
            location=str(info.get("location", huc8)),
            model_type=ModelType.STEADY_1D,
            url=f"s3://{NOAA_RAS2FIM_BUCKET}/{s3_prefix}",
            tags=list(info.get("tags", [])),
            extra={
                "bucket": NOAA_RAS2FIM_BUCKET,
                "s3_prefix": s3_prefix,
                "catalog_only": True,
            },
        )

    @staticmethod
    def _find_metadata(model_id: str) -> Optional[ModelMetadata]:
        key = str(model_id).strip()
        info = NoaaRas2fimModels._MODEL_REGISTRY.get(key)
        if info is None:
            return None
        return NoaaRas2fimModels._metadata_from_registry(key, info)


__all__ = ["NoaaRas2fimModels"]
