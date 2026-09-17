"""Alabama Flood model catalog and downloader.

The Alabama Office of Water Resources publishes downloadable HEC-RAS model
packages through an ArcGIS Feature Service. This adapter exposes the three
catalog classifications (Base Level Engineering, Effective, and Preliminary)
as one state-level source. It preserves each named model record while shared
package downloads naturally converge on the same exact ``WebPath``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import unquote, urlparse

import requests

from ras_commander.Decorators import log_call
from ras_commander.LoggingConfig import get_logger
from ras_commander.sources.base import (
    DownloadResult,
    ModelMetadata,
    ModelType,
    SourceStatus,
)

logger = get_logger(__name__)

ALABAMA_FLOOD_SERVICE_URL = (
    "https://services7.arcgis.com/iH8unQljYvyFM6F1/arcgis/rest/services/"
    "Models/FeatureServer"
)
ALABAMA_FLOOD_PORTAL_URL = (
    "https://experience.arcgis.com/experience/7a6e5f19fdcc43ed8070892368d8c1a8"
)
ALABAMA_FLOOD_ITEM_ID = "94f397bb1cd24fe1bc8dc147d4dd48b1"
_DEFAULT_PAGE_SIZE = 2_000
_REQUEST_TIMEOUT = (15, 60)
_DOWNLOAD_HOST = "files.alabamaflood.com"


class AlabamaModelClassification(str, Enum):
    """Model classifications published by the Alabama Flood portal."""

    BLE = "Base Level Engineering"
    EFFECTIVE = "Effective"
    PRELIMINARY = "Preliminary"


_CLASSIFICATION_ALIASES = {
    "ble": AlabamaModelClassification.BLE,
    "base level engineering": AlabamaModelClassification.BLE,
    "base-level engineering": AlabamaModelClassification.BLE,
    "effective": AlabamaModelClassification.EFFECTIVE,
    "preliminary": AlabamaModelClassification.PRELIMINARY,
    "prelim": AlabamaModelClassification.PRELIMINARY,
}


class AlabamaFloodModels:
    """Discover and download Alabama Flood HEC-RAS model packages.

    ``list_models`` returns one :class:`ModelMetadata` per ArcGIS ``ModelID``.
    Multiple models may point to the same ZIP; those entries share a download
    path, avoiding duplicate transfers without erasing catalog identity.

    Examples:
        >>> from ras_commander.sources.state import AlabamaFloodModels
        >>> effective = AlabamaFloodModels.list_models(
        ...     classification="effective", limit=10
        ... )
        >>> result = AlabamaFloodModels.download_model(
        ...     effective[0].source_id, "alabama_models", extract=False
        ... )
    """

    SOURCE_NAME = "Alabama Flood Models"

    @property
    def source_name(self) -> str:
        """Human-readable source name used by :class:`ModelCatalog`."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Return the unified catalog source category."""
        return "state"

    _catalog_cache: Optional[List[dict]] = None
    _metadata_by_id: Dict[str, ModelMetadata] = {}

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """Return whether the public Alabama ArcGIS service is reachable."""
        try:
            _discover_catalog_layers()
            return SourceStatus.AVAILABLE
        except (requests.RequestException, RuntimeError, ValueError):
            return SourceStatus.UNAVAILABLE

    @staticmethod
    @log_call
    def list_models(
        location: Optional[str] = None,
        model_type: Optional[ModelType] = None,
        hecras_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        classification: Optional[
            Union[str, AlabamaModelClassification, Iterable[Union[str, AlabamaModelClassification]]]
        ] = None,
        county: Optional[str] = None,
        huc8_name: Optional[str] = None,
        basin: Optional[str] = None,
        refresh: bool = False,
        **kwargs,
    ) -> List[ModelMetadata]:
        """Return one catalog entry per Alabama Flood model record.

        Args:
            location: Case-insensitive match across county, HUC8, basin, and name.
            model_type: Alabama does not publish a reliable dimensionality field;
                consequently only ``ModelType.UNKNOWN`` can match this filter.
            hecras_version: No version field is published, so a supplied filter
                produces no matches.
            tags: Required tags using case-insensitive AND matching.
            limit: Maximum number of model records to return.
            classification: One or more of ``ble``, ``effective``, or
                ``preliminary`` (full portal labels are also accepted).
            county: Case-insensitive county substring.
            huc8_name: Case-insensitive HUC8-name substring.
            basin: Case-insensitive basin substring.
            refresh: Discard the in-process ArcGIS catalog cache.
        """
        del kwargs
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        if model_type is not None and model_type != ModelType.UNKNOWN:
            return []
        if hecras_version is not None:
            return []

        selected = _normalize_classifications(classification)
        catalog_rows = AlabamaFloodModels._load_catalog(refresh=refresh)
        results: List[ModelMetadata] = []
        required_tags = {str(tag).casefold() for tag in (tags or [])}

        for catalog_row in catalog_rows:
            classification_value = catalog_row["classification"]
            if selected and classification_value not in selected:
                continue
            if county and not _contains([catalog_row["county"]], county):
                continue
            if huc8_name and not _contains([catalog_row["huc8_name"]], huc8_name):
                continue
            if basin and not _contains([catalog_row["basin"]], basin):
                continue

            metadata = _catalog_row_to_metadata(catalog_row)
            searchable_location = " | ".join(
                [metadata.name, metadata.location]
                + [catalog_row["fips"]]
            )
            if location and location.casefold() not in searchable_location.casefold():
                continue
            if required_tags and not required_tags.issubset(
                {tag.casefold() for tag in metadata.tags}
            ):
                continue

            results.append(metadata)
            AlabamaFloodModels._metadata_by_id[metadata.source_id] = metadata
            if limit is not None and len(results) >= limit:
                break

        return results

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
        """Download a catalog package, with resumable partial-file support.

        Download paths preserve the package's path below ``/Models/`` so that
        same-named archives from different programs or watersheds cannot collide.
        ZIP extraction rejects absolute paths, traversal, and symbolic links.
        """
        del credentials
        chunk_size = int(kwargs.pop("chunk_size", 1024 * 1024))
        refresh = bool(kwargs.pop("refresh", False))
        if kwargs:
            logger.debug("Ignoring unsupported download options: %s", sorted(kwargs))
        if chunk_size <= 0:
            return DownloadResult(False, None, "chunk_size must be positive")

        metadata: Optional[ModelMetadata] = None
        try:
            metadata = AlabamaFloodModels._find_metadata(model_id, refresh=refresh)
            if metadata is None or not metadata.url:
                return DownloadResult(False, None, f"Unknown Alabama model '{model_id}'")

            relative_path = _download_relative_path(metadata.url)
            archive_path = Path(output_folder) / relative_path
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            extracted_path = archive_path.with_suffix("")

            if extract and extracted_path.exists() and not overwrite:
                _validate_extracted_model(extracted_path)
                return DownloadResult(
                    True,
                    extracted_path,
                    f"Using existing extracted model {extracted_path}",
                    metadata,
                    extracted=True,
                )

            if archive_path.exists() and not overwrite:
                _validate_model_archive(archive_path)
                metadata.extra.update(_file_provenance(archive_path))
                if extract and archive_path.suffix.casefold() == ".zip":
                    extracted_path = _extract_zip(archive_path, overwrite=False)
                    return DownloadResult(
                        True,
                        extracted_path,
                        f"Using existing archive {archive_path}",
                        metadata,
                        extracted=True,
                    )
                return DownloadResult(
                    True,
                    archive_path,
                    f"Using existing archive {archive_path}",
                    metadata,
                    extracted=False,
                )

            response_provenance = _download_file(
                metadata.url,
                archive_path,
                overwrite=overwrite,
                chunk_size=chunk_size,
            )
            metadata.extra.update(response_provenance)
            metadata.extra.update(_file_provenance(archive_path))

            if extract and archive_path.suffix.casefold() == ".zip":
                model_path = _extract_zip(archive_path, overwrite=overwrite)
                extracted = True
            else:
                model_path = archive_path
                extracted = False

            return DownloadResult(
                True,
                model_path,
                f"Downloaded {metadata.name} to {model_path}",
                metadata,
                extracted=extracted,
            )
        except Exception as exc:
            logger.error("Alabama model download failed for %s: %s", model_id, exc)
            return DownloadResult(False, None, str(exc), metadata=metadata)

    @staticmethod
    def _find_metadata(model_id: str, refresh: bool = False) -> Optional[ModelMetadata]:
        if not refresh and model_id in AlabamaFloodModels._metadata_by_id:
            return AlabamaFloodModels._metadata_by_id[model_id]
        AlabamaFloodModels.list_models(refresh=refresh)
        return AlabamaFloodModels._metadata_by_id.get(model_id)

    @staticmethod
    def _load_catalog(refresh: bool = False) -> List[dict]:
        if AlabamaFloodModels._catalog_cache is not None and not refresh:
            return AlabamaFloodModels._catalog_cache

        model_layer, link_table = _discover_catalog_layers()
        models = _query_all(
            model_layer,
            "OBJECTID,ModelID,Type,Zone,Name,HUC8_Name,Basin,County,FIPS",
        )
        links = _query_all(
            link_table,
            "OBJECTID,ModelID,FileName,FileType,RelativePath,WebPath",
        )
        catalog_rows = _join_catalog(models, links)
        AlabamaFloodModels._catalog_cache = catalog_rows
        AlabamaFloodModels._metadata_by_id = {
            metadata.source_id: metadata
            for metadata in (_catalog_row_to_metadata(item) for item in catalog_rows)
        }
        return catalog_rows


def _discover_catalog_layers() -> Tuple[int, int]:
    response = requests.get(
        ALABAMA_FLOOD_SERVICE_URL,
        params={"f": "json"},
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"ArcGIS service discovery failed: {payload['error']}")

    entries = list(payload.get("layers", [])) + list(payload.get("tables", []))
    by_name = {str(item.get("name", "")).casefold(): item.get("id") for item in entries}
    model_layer = by_name.get("hydraulic models")
    link_table = by_name.get("model_links")
    if model_layer is None or link_table is None:
        raise RuntimeError("Alabama ArcGIS service is missing its model catalog layers")
    return int(model_layer), int(link_table)


def _query_all(layer_id: int, out_fields: str) -> List[dict]:
    query_url = f"{ALABAMA_FLOOD_SERVICE_URL}/{layer_id}/query"
    id_response = requests.get(
        query_url,
        params={"f": "json", "where": "1=1", "returnIdsOnly": "true"},
        timeout=_REQUEST_TIMEOUT,
    )
    id_response.raise_for_status()
    id_payload = id_response.json()
    if "error" in id_payload:
        raise RuntimeError(f"ArcGIS ID query failed: {id_payload['error']}")
    object_ids = sorted(int(value) for value in id_payload.get("objectIds", []))

    rows: List[dict] = []
    for offset in range(0, len(object_ids), _DEFAULT_PAGE_SIZE):
        batch_ids = object_ids[offset : offset + _DEFAULT_PAGE_SIZE]
        response = requests.post(
            query_url,
            data={
                "f": "json",
                "objectIds": ",".join(str(value) for value in batch_ids),
                "outFields": out_fields,
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS catalog query failed: {payload['error']}")
        rows.extend(item.get("attributes", {}) for item in payload.get("features", []))
    return rows


def _join_catalog(models: List[dict], links: List[dict]) -> List[dict]:
    links_by_model: Dict[str, List[dict]] = defaultdict(list)
    url_reference_counts: Dict[str, int] = defaultdict(int)
    url_model_ids: Dict[str, set[str]] = defaultdict(set)
    for link in links:
        url = str(link.get("WebPath") or "").strip()
        if not url:
            continue
        try:
            _validate_download_url(url)
        except ValueError as exc:
            logger.warning("Skipping invalid Alabama model URL: %s", exc)
            continue
        url_reference_counts[url] += 1
        model_id = link.get("ModelID")
        if model_id is None or not str(model_id).strip():
            continue
        links_by_model[str(model_id)].append(link)
        url_model_ids[url].add(str(model_id))

    catalog_rows: List[dict] = []
    for model in models:
        model_id = str(model.get("ModelID") or "").strip()
        if not model_id:
            continue
        model_links = links_by_model.get(model_id, [])
        if not model_links:
            logger.warning("Alabama model %s has no public WebPath", model_id)
            continue
        link = model_links[0]
        distinct_urls = {
            str(candidate.get("WebPath") or "").strip() for candidate in model_links
        }
        if len(distinct_urls) != 1:
            raise RuntimeError(
                f"Alabama model {model_id} has multiple distinct download URLs"
            )
        url = str(link["WebPath"]).strip()
        catalog_rows.append(
            {
                "model_id": model_id,
                "model_objectid": model.get("OBJECTID"),
                "classification": str(model.get("Type") or "").strip(),
                "zone": str(model.get("Zone") or "").strip(),
                "name": str(model.get("Name") or "").strip(),
                "huc8_name": str(model.get("HUC8_Name") or "").strip(),
                "basin": str(model.get("Basin") or "").strip(),
                "county": str(model.get("County") or "").strip(),
                "fips": str(model.get("FIPS") or "").strip(),
                "url": url,
                "filename": link.get("FileName") or Path(unquote(urlparse(url).path)).name,
                "file_type": str(link.get("FileType") or "").strip(),
                "relative_path": str(link.get("RelativePath") or "").strip(),
                "link_objectid": link.get("OBJECTID"),
                "catalog_reference_count": url_reference_counts[url],
                "linked_model_count": len(url_model_ids[url]),
            }
        )
    catalog_rows.sort(key=lambda item: item["model_id"])
    return catalog_rows


def _catalog_row_to_metadata(catalog_row: dict) -> ModelMetadata:
    classification = catalog_row["classification"]
    location_parts = [
        item
        for item in (
            catalog_row["county"],
            catalog_row["huc8_name"],
            catalog_row["basin"],
        )
        if item
    ]
    location = "Alabama" + (" | " + " | ".join(location_parts) if location_parts else "")
    display_name = catalog_row["name"] or str(catalog_row["filename"] or "Alabama model")
    tags = list(dict.fromkeys(["alabama", "hec-ras", _classification_tag(classification)]))
    if classification == "Preliminary":
        tags.extend(["preliminary-data", "non-regulatory"])
    description = (
        "Downloadable Alabama Flood hydraulic model. Classification: "
        + (classification or "unspecified")
    )
    if classification == "Preliminary":
        description += ". Preliminary data are non-regulatory"

    return ModelMetadata(
        source_name=AlabamaFloodModels.SOURCE_NAME,
        source_id=catalog_row["model_id"],
        name=display_name,
        description=description,
        location=location,
        model_type=ModelType.UNKNOWN,
        hecras_version=None,
        url=catalog_row["url"],
        tags=tags,
        extra={
            "portal_url": ALABAMA_FLOOD_PORTAL_URL,
            "arcgis_item_id": ALABAMA_FLOOD_ITEM_ID,
            "service_url": ALABAMA_FLOOD_SERVICE_URL,
            "model_layer_name": "Hydraulic Models",
            "link_table_name": "Model_Links",
            "classification": classification,
            "zone": catalog_row["zone"],
            "county": catalog_row["county"],
            "fips": catalog_row["fips"],
            "huc8_name": catalog_row["huc8_name"],
            "basin": catalog_row["basin"],
            "filename": catalog_row["filename"],
            "model_objectid": catalog_row["model_objectid"],
            "link_objectid": catalog_row["link_objectid"],
            "catalog_reference_count": catalog_row["catalog_reference_count"],
            "linked_model_count": catalog_row["linked_model_count"],
            "package_id": "alabama-package-"
            + hashlib.sha256(catalog_row["url"].encode("utf-8")).hexdigest()[:20],
            "file_type": catalog_row["file_type"],
            "relative_path": catalog_row["relative_path"],
        },
    )


def _normalize_classifications(
    value: Optional[
        Union[str, AlabamaModelClassification, Iterable[Union[str, AlabamaModelClassification]]]
    ],
) -> set[str]:
    if value is None:
        return set()
    values = [value] if isinstance(value, (str, AlabamaModelClassification)) else list(value)
    normalized = set()
    for item in values:
        if isinstance(item, AlabamaModelClassification):
            normalized.add(item.value)
            continue
        key = str(item).strip().casefold()
        classification = _CLASSIFICATION_ALIASES.get(key)
        if classification is None:
            valid = ", ".join(sorted(_CLASSIFICATION_ALIASES))
            raise ValueError(f"Unknown Alabama model classification '{item}'. Use: {valid}")
        normalized.add(classification.value)
    return normalized


def _classification_tag(value: str) -> str:
    classification = _CLASSIFICATION_ALIASES.get(value.casefold())
    return classification.name.casefold() if classification else value.casefold().replace(" ", "-")


def _contains(values: List[str], needle: str) -> bool:
    folded = needle.casefold()
    return any(folded in value.casefold() for value in values)


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != _DOWNLOAD_HOST:
        raise ValueError(f"Unsupported Alabama model download URL: {url}")
    if not unquote(parsed.path).casefold().startswith("/models/"):
        raise ValueError(f"Alabama model URL is outside /Models/: {url}")


def _download_relative_path(url: str) -> Path:
    _validate_download_url(url)
    decoded = unquote(urlparse(url).path)
    relative = PurePosixPath(decoded).relative_to("/Models")
    windows = PureWindowsPath(str(relative))
    if (
        not relative.parts
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in relative.parts
        or ".." in windows.parts
    ):
        raise ValueError(f"Unsafe Alabama model path: {url}")
    return Path(*relative.parts)


def _download_file(url: str, target: Path, overwrite: bool, chunk_size: int) -> dict:
    part_path = target.with_name(target.name + ".part")
    validator_path = target.with_name(target.name + ".part.json")
    if overwrite:
        part_path.unlink(missing_ok=True)
        validator_path.unlink(missing_ok=True)

    validator = _load_partial_validator(validator_path, url)
    if part_path.exists() and validator is None:
        part_path.unlink()

    for attempt in range(2):
        offset = part_path.stat().st_size if part_path.exists() else 0
        headers = {}
        if offset and validator:
            headers = {
                "Range": f"bytes={offset}-",
                "If-Range": validator["value"],
            }
        response = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        )
        _validate_download_url(response.url or url)

        if response.status_code == 416 and offset:
            total_match = re.fullmatch(
                r"bytes \*/(\d+)", response.headers.get("Content-Range", "")
            )
            current_validator = _response_validator(response)
            if (
                total_match
                and int(total_match.group(1)) == offset
                and current_validator == validator
            ):
                response.close()
                try:
                    _validate_model_archive(part_path)
                except Exception:
                    part_path.unlink(missing_ok=True)
                    validator_path.unlink(missing_ok=True)
                    raise
                part_path.replace(target)
                validator_path.unlink(missing_ok=True)
                return _response_provenance(response, url)
            response.close()
            part_path.unlink(missing_ok=True)
            validator_path.unlink(missing_ok=True)
            validator = None
            continue

        response.raise_for_status()
        content_range = response.headers.get("Content-Range", "")
        range_match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
        if offset == 0 and response.status_code == 206:
            response.close()
            raise RuntimeError(f"Unexpected partial response for {target.name}")
        append = offset > 0 and response.status_code == 206
        if append and (range_match is None or int(range_match.group(1)) != offset):
            response.close()
            raise RuntimeError(
                f"Invalid resume response for {target.name}: {content_range!r}"
            )
        if append and validator:
            header_name = "ETag" if validator["kind"] == "etag" else "Last-Modified"
            returned_validator = response.headers.get(header_name)
            if returned_validator and returned_validator != validator["value"]:
                response.close()
                part_path.unlink(missing_ok=True)
                validator_path.unlink(missing_ok=True)
                validator = None
                continue

        current_validator = _response_validator(response)
        if current_validator:
            validator_path.write_text(
                json.dumps({"url": url, **current_validator}), encoding="utf-8"
            )
        mode = "ab" if append else "wb"
        try:
            with part_path.open(mode) as stream:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        stream.write(chunk)
            expected_size = None
            if append and range_match and range_match.group(3) != "*":
                expected_size = int(range_match.group(3))
            elif not append and response.headers.get("Content-Length"):
                expected_size = int(response.headers["Content-Length"])
            if expected_size is not None and part_path.stat().st_size != expected_size:
                raise RuntimeError(
                    f"Incomplete download for {target.name}: "
                    f"expected {expected_size} bytes, got {part_path.stat().st_size}"
                )
            try:
                _validate_model_archive(part_path)
            except Exception:
                part_path.unlink(missing_ok=True)
                validator_path.unlink(missing_ok=True)
                raise
            provenance = _response_provenance(response, url)
            part_path.replace(target)
            validator_path.unlink(missing_ok=True)
            return provenance
        finally:
            response.close()
    raise RuntimeError(f"Unable to resume or restart download for {target.name}")


def _load_partial_validator(path: Path, url: str) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("url") != url or payload.get("kind") not in {"etag", "last_modified"}:
        return None
    if not payload.get("value"):
        return None
    return {"kind": payload["kind"], "value": payload["value"]}


def _response_validator(response: requests.Response) -> Optional[dict]:
    etag = response.headers.get("ETag")
    if etag and not str(etag).strip().startswith("W/"):
        return {"kind": "etag", "value": etag}
    modified = response.headers.get("Last-Modified")
    if modified:
        return {"kind": "last_modified", "value": modified}
    return None


def _response_provenance(response: requests.Response, url: str) -> dict:
    return {
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "download_url": response.url or url,
    }


def _extract_zip(archive_path: Path, overwrite: bool) -> Path:
    _validate_model_archive(archive_path)
    destination = archive_path.with_suffix("")
    if destination.exists() and not overwrite:
        _validate_extracted_model(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            posix = PurePosixPath(info.filename)
            windows = PureWindowsPath(info.filename)
            is_symlink = ((info.external_attr >> 16) & 0o170000) == 0o120000
            if (
                posix.is_absolute()
                or windows.is_absolute()
                or windows.drive
                or ".." in posix.parts
                or ".." in windows.parts
                or is_symlink
            ):
                raise ValueError(f"Unsafe ZIP member: {info.filename}")

        with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}-extract-", dir=destination.parent
        ) as temp_name:
            temp_root = Path(temp_name)
            archive.extractall(temp_root)
            if destination.exists():
                shutil.rmtree(destination)
            _validate_extracted_model(temp_root)
            temp_root.replace(destination)
    return destination


def _validate_model_archive(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise zipfile.BadZipFile(f"Invalid ZIP archive: {path}")
    has_project = False
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            posix = PurePosixPath(info.filename)
            windows = PureWindowsPath(info.filename)
            is_symlink = ((info.external_attr >> 16) & 0o170000) == 0o120000
            if (
                posix.is_absolute()
                or windows.is_absolute()
                or windows.drive
                or ".." in posix.parts
                or ".." in windows.parts
                or is_symlink
            ):
                raise ValueError(f"Unsafe ZIP member: {info.filename}")
            if not info.is_dir() and posix.suffix.casefold() == ".prj":
                has_project = True
    if not has_project:
        raise ValueError(f"ZIP package contains no HEC-RAS .prj file: {path}")


def _validate_extracted_model(path: Path) -> None:
    if not any(candidate.is_file() for candidate in path.rglob("*.prj")):
        raise ValueError(f"Extracted package contains no HEC-RAS .prj file: {path}")


def _file_provenance(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "download_size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["AlabamaFloodModels", "AlabamaModelClassification"]
