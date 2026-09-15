"""Alabama effective and preliminary HEC-RAS model source.

This adapter extends the hardened Alabama BLE downloader with the two remaining
classifications published by the same ArcGIS catalog.  BLE remains available
through :class:`AlabamaBleModels`; the unified catalog registers this provider
for Effective and Preliminary records so searches do not duplicate BLE models.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union
from urllib.parse import unquote, urlparse

from ras_commander.LoggingConfig import log_call
from ras_commander.sources.base import DownloadResult, ModelMetadata, ModelType
from ras_commander.sources.state.alabama_ble import AlabamaBleModels


class AlabamaModelClassification(str, Enum):
    """Model classifications published by the Alabama Flood portal."""

    BLE = "Base Level Engineering"
    EFFECTIVE = "Effective"
    PRELIMINARY = "Preliminary"


_ALIASES = {
    "ble": AlabamaModelClassification.BLE,
    "base level engineering": AlabamaModelClassification.BLE,
    "base-level engineering": AlabamaModelClassification.BLE,
    "effective": AlabamaModelClassification.EFFECTIVE,
    "preliminary": AlabamaModelClassification.PRELIMINARY,
    "prelim": AlabamaModelClassification.PRELIMINARY,
}


class AlabamaFloodModels(AlabamaBleModels):
    """Discover Alabama Effective and Preliminary hydraulic models.

    The default catalog scope is Effective plus Preliminary because BLE is
    already registered through :class:`AlabamaBleModels`. Pass
    ``classification="all"`` when calling this provider directly to query all
    three portal classifications.
    """

    SOURCE_NAME = "Alabama Flood Models"
    _SOURCE_SIDECAR_SUFFIX = ".alabama-flood-source.json"
    DEFAULT_CLASSIFICATIONS = (
        AlabamaModelClassification.EFFECTIVE,
        AlabamaModelClassification.PRELIMINARY,
    )

    @classmethod
    def _normalize_classifications(
        cls,
        value: Optional[
            Union[
                str,
                AlabamaModelClassification,
                Iterable[Union[str, AlabamaModelClassification]],
            ]
        ],
    ) -> tuple[AlabamaModelClassification, ...]:
        if value is None:
            return cls.DEFAULT_CLASSIFICATIONS
        if isinstance(value, str) and value.strip().casefold() == "all":
            return tuple(AlabamaModelClassification)
        values = (
            [value]
            if isinstance(value, (str, AlabamaModelClassification))
            else list(value)
        )
        normalized: list[AlabamaModelClassification] = []
        for item in values:
            if isinstance(item, AlabamaModelClassification):
                classification = item
            else:
                classification = _ALIASES.get(str(item).strip().casefold())
                if classification is None:
                    valid = ", ".join(sorted((*_ALIASES, "all")))
                    raise ValueError(
                        f"Unknown Alabama model classification {item!r}. Use: {valid}"
                    )
            if classification not in normalized:
                normalized.append(classification)
        if not normalized:
            raise ValueError("At least one Alabama model classification is required.")
        return tuple(normalized)

    @classmethod
    def _classification_where(
        cls, classifications: tuple[AlabamaModelClassification, ...]
    ) -> str:
        literals = ",".join(
            f"'{cls._sql_literal(classification.value)}'"
            for classification in classifications
        )
        return f"Type IN ({literals})"

    @classmethod
    def _query_catalog_rows(
        cls,
        classifications: tuple[AlabamaModelClassification, ...],
        *,
        county: Optional[str] = None,
        huc8_name: Optional[str] = None,
        basin: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        clauses = [cls._classification_where(classifications)]
        for field, value in (
            ("County", county),
            ("HUC8_Name", huc8_name),
            ("Basin", basin),
            ("ModelID", model_id),
        ):
            if value is not None:
                clauses.append(f"{field} = '{cls._sql_literal(value)}'")
        return cls._query_layer(
            cls._MODEL_LAYER_ID,
            " AND ".join(clauses),
            "OBJECTID,Type,Zone,Name,HUC8_Name,Basin,County,FIPS,ModelID,GlobalID",
        )

    @classmethod
    def _row_to_metadata(
        cls,
        row: dict[str, Any],
        link: dict[str, Any],
    ) -> ModelMetadata:
        classification = str(row.get("Type") or "").strip()
        model_id = str(row.get("ModelID") or "").strip()
        model_name = str(row.get("Name") or model_id).strip()
        huc_name = str(row.get("HUC8_Name") or "").strip()
        huc8 = next(
            (code for code, name in cls.HUC8_NAMES.items() if name == huc_name),
            None,
        )
        basin = str(row.get("Basin") or "").strip()
        county = str(row.get("County") or "").strip()
        web_path = str(link.get("WebPath") or "").strip()
        archive_name = str(link.get("FileName") or "").strip()
        if not archive_name:
            archive_name = unquote(Path(urlparse(web_path).path).name)

        tag = {
            AlabamaModelClassification.BLE.value: "ble",
            AlabamaModelClassification.EFFECTIVE.value: "effective",
            AlabamaModelClassification.PRELIMINARY.value: "preliminary",
        }.get(classification, classification.casefold())
        tags = ["alabama", "hec-ras", tag]
        description = f"Alabama {classification} HEC-RAS model."
        if classification == AlabamaModelClassification.PRELIMINARY.value:
            tags.extend(["preliminary-data", "non-regulatory"])
            description += " Preliminary data are non-regulatory."
        if huc8:
            tags.extend([huc8, f"AL{huc8}"])
        qualification = (
            cls._qualification(huc8)
            if classification == AlabamaModelClassification.BLE.value
            else {}
        )
        qualified_type = qualification.get("model_type", ModelType.UNKNOWN)

        return ModelMetadata(
            source_name=cls.SOURCE_NAME,
            source_id=model_id,
            name=model_name,
            description=description,
            location=", ".join(
                value for value in (county, huc_name, basin, "Alabama") if value
            ),
            model_type=(
                qualified_type
                if isinstance(qualified_type, ModelType)
                else ModelType.UNKNOWN
            ),
            hecras_version=(
                str(qualification["hecras_version"])
                if qualification.get("hecras_version")
                else None
            ),
            url=web_path,
            tags=tags,
            extra={
                "classification": classification,
                "huc8": huc8,
                "study_key": f"AL{huc8}" if huc8 else None,
                "huc8_name": huc_name,
                "basin": basin,
                "zone": row.get("Zone"),
                "county": county,
                "fips": row.get("FIPS"),
                "model_id": model_id,
                "global_id": row.get("GlobalID"),
                "model_object_id": row.get("OBJECTID"),
                "link_object_id": link.get("OBJECTID"),
                "archive_name": archive_name,
                "file_name": archive_name,
                "web_path": web_path,
                "source_prefix": web_path.rsplit("/", 2)[0] + "/",
            },
        )

    @classmethod
    @log_call
    def list_models(
        cls,
        location: Optional[str] = None,
        model_type: Optional[ModelType] = None,
        hecras_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        **kwargs: Any,
    ) -> List[ModelMetadata]:
        """List Effective/Preliminary models with optional portal filters."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        if model_type is not None and model_type != ModelType.UNKNOWN:
            return []
        if hecras_version is not None:
            return []
        classifications = cls._normalize_classifications(
            kwargs.get("classification")
        )
        rows = cls._query_catalog_rows(
            classifications,
            county=kwargs.get("county"),
            huc8_name=kwargs.get("huc8_name"),
            basin=kwargs.get("basin"),
        )
        models = cls._metadata_from_rows(rows)
        if location:
            needle = location.casefold()
            models = [item for item in models if needle in item.location.casefold()]
        if tags:
            wanted = {tag.casefold() for tag in tags}
            models = [
                item
                for item in models
                if wanted.issubset({tag.casefold() for tag in item.tags})
            ]
        return models[:limit] if limit is not None else models

    @classmethod
    @log_call
    def get_model_metadata(
        cls,
        model_id: str,
        huc8: Optional[str] = None,
        classification: Optional[
            Union[str, AlabamaModelClassification, Iterable[Union[str, AlabamaModelClassification]]]
        ] = None,
    ) -> ModelMetadata:
        """Return one Effective, Preliminary, or explicitly requested BLE model."""
        wanted = str(model_id).strip()
        rows = cls._query_catalog_rows(
            cls._normalize_classifications(
                "all" if classification is None else classification
            ),
            huc8_name=cls._watershed_name(huc8) if huc8 is not None else None,
            model_id=wanted,
        )
        if len(rows) != 1:
            raise KeyError(
                f"Expected one Alabama model for ModelID {wanted!r}; found {len(rows)}."
            )
        return cls._metadata_from_rows(rows)[0]

    @classmethod
    @log_call
    def download_model(
        cls,
        model_id: str,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
        **kwargs: Any,
    ) -> DownloadResult:
        """Download one model into an exact-URL-derived package namespace."""
        try:
            metadata = cls.get_model_metadata(
                model_id,
                classification=kwargs.get("classification"),
            )
        except Exception as exc:
            return DownloadResult(False, None, str(exc), None, False)
        package_id = hashlib.sha256(str(metadata.url).encode("utf-8")).hexdigest()[:20]
        classification = str(metadata.extra.get("classification") or "unknown")
        classification_folder = classification.casefold().replace(" ", "-")
        scoped_output = Path(output_folder) / classification_folder / package_id
        result = super().download_model(
            model_id=model_id,
            output_folder=scoped_output,
            extract=extract,
            overwrite=overwrite,
            credentials=credentials,
            **kwargs,
        )
        if result.metadata is not None:
            result.metadata.extra["package_id"] = package_id
        return result

    @staticmethod
    def _ble_workflow_error() -> NotImplementedError:
        return NotImplementedError(
            "Watershed delivery workflows are BLE-specific; use AlabamaBleModels."
        )

    @classmethod
    @log_call
    def build_watershed_manifest(cls, huc8: str) -> List[ModelMetadata]:
        """Reject BLE-only watershed materialization on this provider."""
        del huc8
        raise cls._ble_workflow_error()

    @classmethod
    @log_call
    def list_watershed_models(
        cls, huc8: str, basin: Optional[str] = None
    ) -> List[ModelMetadata]:
        """Reject BLE-only watershed listing on this provider."""
        del huc8, basin
        raise cls._ble_workflow_error()

    @classmethod
    @log_call
    def resolve_watershed_directory(
        cls, model_id: str, huc8: Optional[str] = None
    ) -> str:
        """Reject BLE-only watershed directory resolution on this provider."""
        del model_id, huc8
        raise cls._ble_workflow_error()

    @classmethod
    @log_call
    def download_watershed(cls, *args: Any, **kwargs: Any) -> DownloadResult:
        """Reject BLE-only watershed downloads on this provider."""
        del args, kwargs
        raise cls._ble_workflow_error()

    @classmethod
    @log_call
    def organize_watershed(cls, *args: Any, **kwargs: Any) -> DownloadResult:
        """Reject BLE-only watershed organization on this provider."""
        del args, kwargs
        raise cls._ble_workflow_error()

    @classmethod
    @log_call
    def build_watershed_delivery_inventory(
        cls, *args: Any, **kwargs: Any
    ) -> dict[str, object]:
        """Reject BLE-only delivery inventories on this provider."""
        del args, kwargs
        raise cls._ble_workflow_error()


__all__ = ["AlabamaFloodModels", "AlabamaModelClassification"]
