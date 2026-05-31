"""Shared model-source types used by ras-commander source catalogs."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union


class ModelType(str, Enum):
    """Supported HEC-RAS model categories."""

    STEADY_1D = "1D steady"
    UNSTEADY_1D = "1D unsteady"
    STEADY_2D = "2D steady"
    UNSTEADY_2D = "2D unsteady"
    HYBRID_1D_2D = "1D/2D hybrid"
    UNKNOWN = "unknown"


class SourceStatus(str, Enum):
    """Availability status for a model source."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEPRECATED = "deprecated"
    REQUIRES_AUTH = "requires_auth"


@dataclass
class ModelMetadata:
    """Metadata describing one discoverable HEC-RAS model."""

    source_name: str
    source_id: str
    name: str
    description: str = ""
    location: str = ""
    model_type: ModelType = ModelType.UNKNOWN
    hecras_version: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    file_size_mb: Optional[float] = None
    study_date: Optional[str] = None
    last_modified: Optional[Any] = None
    projection: Optional[str] = None
    spatial_extent: Optional[Any] = None
    effective_date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, object] = field(default_factory=dict)


@dataclass
class DownloadResult:
    """Result from downloading or organizing a model source."""

    success: bool
    model_path: Optional[Union[str, Path]]
    message: str
    metadata: Optional[ModelMetadata] = None
    extracted: bool = False


@dataclass
class ModelFilter:
    """Reusable filter for catalog search results."""

    location: Optional[str] = None
    model_type: Optional[ModelType] = None
    hecras_version: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def matches(self, metadata: ModelMetadata) -> bool:
        """Return True when metadata satisfies all configured filters."""
        if self.location and self.location.lower() not in metadata.location.lower():
            return False
        if self.model_type and metadata.model_type != self.model_type:
            return False
        if self.hecras_version and metadata.hecras_version != self.hecras_version:
            return False
        if self.tags and not all(tag in metadata.tags for tag in self.tags):
            return False
        return True


class ModelSource(Protocol):
    """Protocol implemented by model-source adapters."""

    @property
    def source_name(self) -> str:
        ...

    @property
    def source_type(self) -> str:
        ...

    def get_source_status(self) -> SourceStatus:
        ...

    def list_models(self, **kwargs) -> List[ModelMetadata]:
        ...

    def download_model(
        self,
        model_id: str,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
        **kwargs,
    ) -> DownloadResult:
        ...


__all__ = [
    "DownloadResult",
    "ModelFilter",
    "ModelMetadata",
    "ModelSource",
    "ModelType",
    "SourceStatus",
]
