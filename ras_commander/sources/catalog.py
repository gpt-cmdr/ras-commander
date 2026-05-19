"""
Unified catalog for discovering HEC-RAS models across all sources.

The ModelCatalog provides a single interface for searching and downloading
models from federal, state, county, and academic sources.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from ras_commander.LoggingConfig import log_call
from ras_commander.sources.base import (
    DownloadResult,
    ModelFilter,
    ModelMetadata,
    ModelSource,
    ModelType,
    SourceStatus,
)

logger = logging.getLogger(__name__)


class ModelCatalog:
    """
    Unified catalog for discovering HEC-RAS models across all sources.

    Example:
        >>> catalog = get_catalog()
        >>> models = catalog.search_models(location="Minnesota")
        >>> result = catalog.download_model(models[0], output_folder="models")
    """

    def __init__(self):
        self._sources: Dict[str, ModelSource] = {}
        self._source_status: Dict[str, SourceStatus] = {}

    @log_call
    def register_source(self, source: ModelSource) -> None:
        """Register a model source with the catalog."""
        name = source.source_name
        self._sources[name] = source
        try:
            status = source.get_source_status()
            self._source_status[name] = status
            logger.debug(f"Registered source '{name}' with status: {status.value}")
        except Exception as e:
            logger.warning(f"Could not check status for '{name}': {e}")
            self._source_status[name] = SourceStatus.UNAVAILABLE

    @log_call
    def list_sources(self, include_unavailable: bool = False) -> List[str]:
        """List all registered source names."""
        if include_unavailable:
            return list(self._sources.keys())
        return [
            name for name, status in self._source_status.items()
            if status not in (SourceStatus.UNAVAILABLE, SourceStatus.DEPRECATED)
        ]

    def get_source(self, source_name: str) -> Optional[ModelSource]:
        """Get a registered source by name."""
        return self._sources.get(source_name)

    @log_call
    def search_models(
        self,
        location: Optional[str] = None,
        model_type: Optional[ModelType] = None,
        hecras_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        limit_per_source: Optional[int] = None,
        model_filter: Optional[ModelFilter] = None,
    ) -> List[ModelMetadata]:
        """Search for models across all registered sources."""
        if sources:
            source_names = [s for s in sources if s in self._sources]
        else:
            source_names = self.list_sources(include_unavailable=False)

        if not source_names:
            logger.warning("No available sources to search")
            return []

        all_results = []
        for source_name in source_names:
            source = self._sources[source_name]
            try:
                # Prefer list_catalog_models (returns ModelMetadata) over
                # legacy list_models (may return slugs for older sources)
                list_fn = getattr(source, "list_catalog_models", None)
                if list_fn and callable(list_fn):
                    results = list_fn(
                        location=location,
                        model_type=model_type,
                        hecras_version=hecras_version,
                        tags=tags,
                        limit=limit_per_source,
                    )
                else:
                    results = source.list_models(
                        location=location,
                        model_type=model_type,
                        hecras_version=hecras_version,
                        tags=tags,
                        limit=limit_per_source,
                    )
                if model_filter:
                    results = [m for m in results if model_filter.matches(m)]
                logger.info(f"Found {len(results)} models from {source_name}")
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Error querying {source_name}: {e}")
                continue

        return all_results

    @log_call
    def download_model(
        self,
        metadata: ModelMetadata,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
    ) -> DownloadResult:
        """Download a model using its metadata."""
        source = self._sources.get(metadata.source_name)
        if source is None:
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"Source not registered: {metadata.source_name}",
                metadata=metadata,
            )

        try:
            return source.download_model(
                model_id=metadata.source_id,
                output_folder=output_folder,
                extract=extract,
                overwrite=overwrite,
                credentials=credentials,
            )
        except Exception as e:
            logger.error(f"Error downloading model {metadata.name}: {e}")
            return DownloadResult(
                success=False,
                model_path=None,
                message=f"Download failed: {e}",
                metadata=metadata,
            )

    @log_call
    def refresh_source_status(self) -> None:
        """Refresh availability status for all registered sources."""
        for name, source in self._sources.items():
            try:
                status = source.get_source_status()
                self._source_status[name] = status
            except Exception as e:
                logger.warning(f"Could not check status for '{name}': {e}")
                self._source_status[name] = SourceStatus.UNAVAILABLE


_catalog: Optional[ModelCatalog] = None


def get_catalog(auto_register: bool = True) -> ModelCatalog:
    """Get the global model catalog instance (singleton)."""
    global _catalog

    if _catalog is None:
        _catalog = ModelCatalog()

        if auto_register:
            try:
                from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase
                _catalog.register_source(UsgsScienceBase())
            except (ImportError, Exception):
                logger.debug("UsgsScienceBase not available")

            try:
                from ras_commander.sources.state.mn_dnr import MinnesotaDnrModels
                _catalog.register_source(MinnesotaDnrModels())
            except (ImportError, Exception):
                logger.debug("MinnesotaDnrModels not available")

            try:
                from ras_commander.sources.state.in_dnr import IndianaDnrModels
                _catalog.register_source(IndianaDnrModels())
            except (ImportError, Exception):
                logger.debug("IndianaDnrModels not available")

            try:
                from ras_commander.sources.state.co_champ import ColoradoChampModels
                _catalog.register_source(ColoradoChampModels())
            except (ImportError, Exception):
                logger.debug("ColoradoChampModels not available")

            try:
                from ras_commander.sources.federal.noaa_ras2fim import NoaaRas2fimModels
                _catalog.register_source(NoaaRas2fimModels())
            except (ImportError, Exception):
                logger.debug("NoaaRas2fimModels not available")

            try:
                from ras_commander.sources.federal.ebfe_models import RasEbfeModels
                _catalog.register_source(RasEbfeModels())
            except (ImportError, Exception):
                logger.debug("RasEbfeModels not available")

    return _catalog
