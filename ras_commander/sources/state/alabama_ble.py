"""Alabama Base Level Engineering (BLE) HEC-RAS model source.

The Alabama Flood Risk Information System publishes model metadata and file
links in separate anonymous ArcGIS FeatureServer layers.  This adapter joins
those layers by the publisher's ``ModelID`` and deliberately downloads only
the public ``WebPath`` supplied by the link table.  Publisher-local ``URL``,
``LocalPath``, and ``RelativePath`` values are never used as source paths.

The public catalog does not expose HUC8 codes.  ``HUC8_NAMES`` therefore binds
qualified watershed names to their WBD HUC8 identities.  All model and link
membership remains dynamically discovered from ArcGIS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import unquote, urljoin, urlparse

import requests

from ras_commander import get_logger
from ras_commander.LoggingConfig import log_call
from ras_commander.sources.base import (
    DownloadResult,
    ModelMetadata,
    ModelType,
    SourceStatus,
)

logger = get_logger(__name__)


class AlabamaBleModels:
    """Discover, download, and organize Alabama BLE model watersheds."""

    SOURCE_NAME = "Alabama BLE"
    _SERVICE_URL = (
        "https://services7.arcgis.com/iH8unQljYvyFM6F1/arcgis/rest/services/"
        "Models/FeatureServer"
    )
    _MODEL_LAYER_ID = 2
    _LINK_LAYER_ID = 3
    _PAGE_SIZE = 2000
    _REQUEST_TIMEOUT = 90
    _DOWNLOAD_TIMEOUT = 300
    _DOWNLOAD_CHUNK_SIZE = 1024 * 1024
    _MANIFEST_NAME = "alabama_ble_source_manifest.json"
    _MANIFEST_SCHEMA_NAME = "ras_commander.watershed_source_manifest"
    _MANIFEST_CONTRACT_VERSION = "1.0.0"
    _SOURCE_POLICY = "ArcGIS layer 2 metadata joined to layer 3 WebPath only"
    _SOURCE_SIDECAR_SUFFIX = ".alabama-ble-source.json"
    _EXTRACTION_RECEIPT = ".ras-commander-extraction.json"
    _PUBLIC_ARCHIVE_HOSTS = frozenset({"files.alabamaflood.com"})
    _REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
    _MAX_REDIRECTS = 5
    _MAX_HECRAS_ACTIVE_PATH = 240

    # The FeatureServer exposes these names, but not their HUC8 codes. Add a
    # crosswalk entry only after the watershed identity is independently known.
    HUC8_NAMES: Dict[str, str] = {
        "03130002": "Middle Chattahoochee-Lake Harding",
    }

    # These values are independently qualified facts, not a blanket
    # classification of every row in the Alabama catalog.
    _KNOWN_QUALIFICATIONS: Dict[str, Dict[str, object]] = {
        "03130002": {
            "model_type": ModelType.STEADY_1D,
            "expected_model_count": 197,
            "expected_basins": {
                "Halawakee Creek": 20,
                "Moores Creek": 13,
                "Osanippa Creek": 42,
                "Oseligee Creek": 46,
                "Stroud Creek": 21,
                "Town Creek": 5,
                "Wacoochee Creek": 15,
                "Wehadkee Creek": 35,
            },
        }
    }

    @property
    def source_name(self) -> str:
        """Human-readable source name used by :class:`ModelCatalog`."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Return the source category used by :class:`ModelCatalog`."""
        return "state"

    @staticmethod
    def normalize_huc8(value: str) -> str:
        """Normalize ``03130002`` or an ``AL03130002`` study key to HUC8."""
        match = re.fullmatch(
            r"(?:AL)?(?P<huc8>\d{8})(?:[_-].*)?",
            str(value).strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                f"Invalid Alabama BLE HUC8/study key: {value!r}. Expected "
                "eight digits or an AL-prefixed eight-digit key."
            )
        return match.group("huc8")

    @classmethod
    def _watershed_name(cls, huc8: str) -> str:
        normalized = cls.normalize_huc8(huc8)
        try:
            return cls.HUC8_NAMES[normalized]
        except KeyError as exc:
            raise KeyError(
                f"HUC8 {normalized} is not in the published Alabama BLE "
                "watershed-name crosswalk."
            ) from exc

    @staticmethod
    def _sql_literal(value: object) -> str:
        return str(value).replace("'", "''")

    @classmethod
    def _validate_public_archive_url(cls, value: object, label: str) -> str:
        """Require an HTTPS Alabama archive URL with no credential or host drift."""
        url = str(value or "").strip()
        parsed = urlparse(url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() not in cls._PUBLIC_ARCHIVE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValueError(
                f"{label} must be an HTTPS archive URL on "
                f"{', '.join(sorted(cls._PUBLIC_ARCHIVE_HOSTS))}: {url!r}"
            )
        return url

    @staticmethod
    def _normalize_etag(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        weak_prefix = normalized[:2].upper() == "W/"
        if weak_prefix:
            normalized = normalized[2:].strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
            normalized = normalized[1:-1]
        if weak_prefix and normalized:
            normalized = f"W/{normalized}"
        return normalized or None

    @classmethod
    def _request_archive(
        cls,
        method: str,
        url: str,
        **kwargs: object,
    ) -> requests.Response:
        """Request an archive while validating each redirect before following it."""
        method = method.upper()
        if method not in {"GET", "HEAD"}:
            raise ValueError(f"Unsupported Alabama archive request method: {method}")
        current_url = cls._validate_public_archive_url(url, "Archive request URL")
        requester = requests.get if method == "GET" else requests.head
        for redirect_count in range(cls._MAX_REDIRECTS + 1):
            response = requester(current_url, allow_redirects=False, **kwargs)
            if response.status_code not in cls._REDIRECT_STATUSES:
                response.raise_for_status()
                cls._validate_public_archive_url(
                    str(response.url or current_url),
                    "Archive response URL",
                )
                return response
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError(
                    f"Alabama archive redirect has no Location header: {current_url}"
                )
            if redirect_count == cls._MAX_REDIRECTS:
                raise RuntimeError(
                    f"Alabama archive exceeded {cls._MAX_REDIRECTS} redirects: {url}"
                )
            current_url = cls._validate_public_archive_url(
                urljoin(current_url, location),
                "Archive redirect URL",
            )
        raise RuntimeError(f"Alabama archive redirect validation failed: {url}")

    @staticmethod
    def _request_json(url: str, params: Dict[str, object]) -> Dict[str, Any]:
        prepared = requests.Request("GET", url, params=params).prepare()
        if len(str(prepared.url)) <= 1900:
            response = requests.get(
                url,
                params=params,
                timeout=AlabamaBleModels._REQUEST_TIMEOUT,
            )
        else:
            # ArcGIS accepts form POSTs for long IN clauses.  This avoids
            # proxy/browser URL limits without widening the query.
            response = requests.post(
                url,
                data=params,
                timeout=AlabamaBleModels._REQUEST_TIMEOUT,
            )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Alabama BLE ArcGIS query failed: {payload['error']}")
        return payload

    @classmethod
    def _query_layer(
        cls,
        layer_id: int,
        where: str,
        out_fields: str,
        order_by: str = "OBJECTID",
    ) -> List[Dict[str, Any]]:
        """Query one ArcGIS layer exactly and paginate until exhausted."""
        endpoint = f"{cls._SERVICE_URL}/{layer_id}/query"
        records: List[Dict[str, Any]] = []
        offset = 0
        while True:
            payload = cls._request_json(
                endpoint,
                {
                    "f": "json",
                    "where": where,
                    "outFields": out_fields,
                    "returnGeometry": "false",
                    "orderByFields": order_by,
                    "resultOffset": offset,
                    "resultRecordCount": cls._PAGE_SIZE,
                },
            )
            features = payload.get("features", [])
            records.extend(features)
            if (
                not payload.get("exceededTransferLimit")
                and len(features) < cls._PAGE_SIZE
            ):
                break
            if not features:
                break
            offset += len(features)
        return records

    @staticmethod
    def _attributes(row: Dict[str, Any]) -> Dict[str, Any]:
        """Accept either an ArcGIS feature envelope or its attributes."""
        attributes = row.get("attributes")
        return attributes if isinstance(attributes, dict) else row

    @classmethod
    def _query_model_rows(cls, huc8: Optional[str] = None) -> List[Dict[str, Any]]:
        where = "Type = 'Base Level Engineering'"
        if huc8 is not None:
            name = cls._watershed_name(huc8)
            where += f" AND HUC8_Name = '{cls._sql_literal(name)}'"
        return cls._query_layer(
            cls._MODEL_LAYER_ID,
            where,
            ("OBJECTID,Type,Zone,Name,HUC8_Name,Basin,County,FIPS,ModelID,GlobalID"),
        )

    @classmethod
    def _query_links_for_ids(
        cls,
        model_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Query public link rows in bounded joins and validate one ZIP per ID."""
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        unique_ids = sorted(set(model_ids))
        for start in range(0, len(unique_ids), 100):
            chunk = unique_ids[start : start + 100]
            literals = ",".join(f"'{cls._sql_literal(model_id)}'" for model_id in chunk)
            rows = cls._query_layer(
                cls._LINK_LAYER_ID,
                f"ModelID IN ({literals})",
                "OBJECTID,ModelID,FileName,FileType,WebPath",
            )
            requested = set(chunk)
            for feature in rows:
                row = cls._attributes(feature)
                model_id = str(row.get("ModelID") or "").strip()
                if model_id in requested:
                    grouped[model_id].append(row)

        links: Dict[str, Dict[str, Any]] = {}
        for model_id in unique_ids:
            usable = []
            for row in grouped.get(model_id, []):
                web_path = str(row.get("WebPath") or "").strip()
                file_name = str(row.get("FileName") or "").strip()
                file_type = str(row.get("FileType") or "").strip().casefold()
                if web_path and (
                    file_type == "zip" or file_name.casefold().endswith(".zip")
                ):
                    try:
                        cls._validate_public_archive_url(web_path, "WebPath")
                    except ValueError:
                        continue
                    usable.append(row)
            distinct = {
                (
                    str(row.get("WebPath") or "").strip(),
                    str(row.get("FileName") or "").strip(),
                ): row
                for row in usable
            }
            if len(distinct) != 1:
                raise ValueError(
                    f"Expected exactly one public ZIP WebPath for ModelID "
                    f"{model_id}, found {len(distinct)}."
                )
            links[model_id] = next(iter(distinct.values()))
        return links

    @classmethod
    def _qualification(cls, huc8: Optional[str]) -> Dict[str, object]:
        if huc8 is None:
            return {}
        return cls._KNOWN_QUALIFICATIONS.get(huc8, {})

    @classmethod
    def _row_to_metadata(
        cls,
        row: Dict[str, Any],
        link: Dict[str, Any],
    ) -> ModelMetadata:
        model_id = str(row.get("ModelID") or "").strip()
        huc_name = str(row.get("HUC8_Name") or "").strip()
        huc8 = next(
            (code for code, name in cls.HUC8_NAMES.items() if name == huc_name),
            None,
        )
        qualification = cls._qualification(huc8)
        basin = str(row.get("Basin") or "").strip()
        model_name = str(row.get("Name") or model_id).strip()
        web_path = str(link.get("WebPath") or "").strip()
        archive_name = str(link.get("FileName") or "").strip()
        if not archive_name:
            archive_name = unquote(Path(urlparse(web_path).path).name)
        description = f"Alabama BLE HEC-RAS model in {basin or huc_name}."
        tags = ["Alabama BLE", "BLE"]
        if huc8:
            tags.extend([huc8, f"AL{huc8}"])
        if basin:
            tags.append(basin)
        model_type = qualification.get("model_type", ModelType.UNKNOWN)
        return ModelMetadata(
            source_name=cls.SOURCE_NAME,
            source_id=model_id,
            name=model_name,
            description=description,
            location=", ".join(item for item in (basin, huc_name) if item),
            model_type=(
                model_type if isinstance(model_type, ModelType) else ModelType.UNKNOWN
            ),
            hecras_version=(
                str(qualification["hecras_version"])
                if qualification.get("hecras_version")
                else None
            ),
            url=web_path,
            tags=tags,
            extra={
                "huc8": huc8,
                "study_key": f"AL{huc8}" if huc8 else None,
                "huc8_name": huc_name,
                "basin": basin,
                "zone": row.get("Zone"),
                "county": row.get("County"),
                "fips": row.get("FIPS"),
                "model_id": model_id,
                "global_id": row.get("GlobalID"),
                "model_object_id": row.get("OBJECTID"),
                "link_object_id": link.get("OBJECTID"),
                "archive_name": archive_name,
                "web_path": web_path,
                # This is a URL namespace prefix, not a browsable directory;
                # the server correctly returns 404 for bare path prefixes.
                "source_prefix": web_path.rsplit("/", 2)[0] + "/",
                "file_name": archive_name,
            },
        )

    @classmethod
    def _metadata_from_rows(
        cls,
        rows: Sequence[Dict[str, Any]],
        expected_huc8: Optional[str] = None,
    ) -> List[ModelMetadata]:
        attributes = [cls._attributes(row) for row in rows]
        model_ids = [str(row.get("ModelID") or "").strip() for row in attributes]
        if not all(model_ids):
            raise RuntimeError("Alabama BLE catalog returned a row without ModelID.")
        duplicates = [key for key, count in Counter(model_ids).items() if count != 1]
        if duplicates:
            raise RuntimeError(f"Duplicate Alabama BLE ModelID values: {duplicates}")
        links = cls._query_links_for_ids(model_ids)
        result = [
            cls._row_to_metadata(row, links[model_id])
            for row, model_id in zip(attributes, model_ids)
        ]
        result.sort(
            key=lambda item: (
                str(item.extra.get("basin") or "").casefold(),
                item.name.casefold(),
                item.source_id,
            )
        )
        if expected_huc8 is not None:
            cls._validate_watershed_membership(expected_huc8, result)
        return result

    @classmethod
    def _validate_watershed_membership(
        cls,
        huc8: str,
        models: Sequence[ModelMetadata],
    ) -> None:
        normalized = cls.normalize_huc8(huc8)
        if any(item.extra.get("huc8") != normalized for item in models):
            raise RuntimeError(
                f"Alabama BLE watershed query returned a record outside HUC8 {normalized}."
            )
        ids = [item.source_id for item in models]
        if len(ids) != len(set(ids)):
            raise RuntimeError(
                f"HUC8 {normalized} contains duplicate ModelID identities."
            )

    @classmethod
    def _validate_qualified_corpus(
        cls,
        huc8: str,
        models: Sequence[Union[ModelMetadata, Dict[str, object]]],
    ) -> None:
        """Apply fixed count evidence only at full-corpus materialization gates."""
        normalized = cls.normalize_huc8(huc8)
        qualification = cls._qualification(normalized)
        expected_count = qualification.get("expected_model_count")
        if expected_count is not None and len(models) != int(expected_count):
            raise RuntimeError(
                f"HUC8 {normalized} expected {expected_count} Alabama BLE models; "
                f"received {len(models)} at the full-corpus validation gate."
            )
        expected_basins = qualification.get("expected_basins")
        if isinstance(expected_basins, dict):
            actual = Counter(
                str(
                    (item.extra if isinstance(item, ModelMetadata) else item).get(
                        "basin"
                    )
                    or ""
                )
                for item in models
            )
            if dict(actual) != expected_basins:
                raise RuntimeError(
                    f"HUC8 {normalized} basin inventory differs from its qualified "
                    f"identity: expected {expected_basins}, received {dict(actual)}."
                )

    @classmethod
    @log_call
    def build_watershed_manifest(cls, huc8: str) -> List[ModelMetadata]:
        """Return the exact, dynamically joined model inventory for one HUC8."""
        normalized = cls.normalize_huc8(huc8)
        models = cls._metadata_from_rows(cls._query_model_rows(normalized))
        cls._validate_watershed_membership(normalized, models)
        return models

    @classmethod
    @log_call
    def list_watershed_models(
        cls,
        huc8: str,
        basin: Optional[str] = None,
    ) -> List[ModelMetadata]:
        """List one complete HUC8 corpus, optionally filtered by source basin."""
        models = cls.build_watershed_manifest(huc8)
        if basin is None:
            return models
        wanted = str(basin).strip().casefold()
        return [
            item
            for item in models
            if str(item.extra.get("basin") or "").casefold() == wanted
        ]

    @classmethod
    @log_call
    def resolve_watershed_directory(
        cls,
        model_id: str,
        huc8: Optional[str] = None,
    ) -> str:
        """Return a model's publisher source prefix.

        Alabama's object-store prefixes are not browsable directory pages; callers
        must continue to enumerate archives through :meth:`list_watershed_models`.
        """
        metadata = cls.get_model_metadata(model_id, huc8=huc8)
        return str(metadata.extra["source_prefix"])

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
        """List Alabama BLE models, optionally narrowed to one exact HUC8."""
        huc8 = kwargs.get("huc8")
        if huc8 is None and location:
            try:
                huc8 = cls.normalize_huc8(location)
            except ValueError:
                reverse = {
                    name.casefold(): code for code, name in cls.HUC8_NAMES.items()
                }
                huc8 = reverse.get(location.strip().casefold())
        if huc8 is not None:
            models = cls.build_watershed_manifest(str(huc8))
        else:
            models = cls._metadata_from_rows(cls._query_model_rows())

        if location and huc8 is None:
            needle = location.casefold()
            models = [item for item in models if needle in item.location.casefold()]
        if model_type is not None:
            models = [item for item in models if item.model_type == model_type]
        if hecras_version is not None:
            models = [item for item in models if item.hecras_version == hecras_version]
        if tags:
            models = [item for item in models if all(tag in item.tags for tag in tags)]
        return models[:limit] if limit is not None else models

    @classmethod
    @log_call
    def get_model_metadata(
        cls,
        model_id: str,
        huc8: Optional[str] = None,
    ) -> ModelMetadata:
        """Return one model by the publisher's exact, opaque ``ModelID``."""
        wanted = str(model_id).strip()
        where = (
            "Type = 'Base Level Engineering' AND ModelID = "
            f"'{cls._sql_literal(wanted)}'"
        )
        if huc8 is not None:
            name = cls._watershed_name(huc8)
            where += f" AND HUC8_Name = '{cls._sql_literal(name)}'"
        rows = cls._query_layer(
            cls._MODEL_LAYER_ID,
            where,
            ("OBJECTID,Type,Zone,Name,HUC8_Name,Basin,County,FIPS,ModelID,GlobalID"),
        )
        if len(rows) != 1:
            raise KeyError(
                f"Expected one Alabama BLE model for ModelID {wanted!r}; "
                f"found {len(rows)}."
            )
        return cls._metadata_from_rows(rows)[0]

    @classmethod
    def _probe_asset(cls, url: str) -> Dict[str, object]:
        """Read the strong HTTP identity required before accepting an archive."""
        url = cls._validate_public_archive_url(url, "Source URL")
        response = cls._request_archive(
            "HEAD",
            url,
            timeout=cls._REQUEST_TIMEOUT,
        )
        try:
            final_url = cls._validate_public_archive_url(
                str(response.url), "Preflight redirect URL"
            )
            size_text = response.headers.get("Content-Length")
            etag = cls._normalize_etag(response.headers.get("ETag"))
            if size_text is None or etag is None or etag.startswith("W/"):
                raise RuntimeError(
                    f"Alabama BLE archive lacks Content-Length and/or strong ETag: {url}"
                )
            try:
                size = int(size_text)
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid Content-Length for {url}: {size_text!r}"
                ) from exc
            return {
                "source_url": url,
                "final_url": final_url,
                "size_bytes": size,
                "etag": etag,
            }
        finally:
            response.close()

    @classmethod
    def _source_sidecar(cls, archive_path: Path) -> Path:
        return archive_path.with_name(archive_path.name + cls._SOURCE_SIDECAR_SUFFIX)

    @staticmethod
    def _windows_extended_path(path: Union[str, Path]) -> str:
        """Return a Windows long-path spelling without remapping drive roots."""
        text = str(Path(path).absolute())
        if os.name != "nt" or text.startswith("\\\\?\\"):
            return text
        if text.startswith("\\\\"):
            return "\\\\?\\UNC\\" + text.lstrip("\\")
        return "\\\\?\\" + text

    @staticmethod
    def _atomic_write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the temporary basename short; archive members can already be
        # close to MAX_PATH before a receipt suffix is added.
        temporary = path.with_name(f".w-{uuid.uuid4().hex[:8]}.tmp")
        try:
            with open(
                AlabamaBleModels._windows_extended_path(temporary),
                "w",
                encoding="utf-8",
            ) as stream:
                stream.write(
                    json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
                )
            os.replace(
                AlabamaBleModels._windows_extended_path(temporary),
                AlabamaBleModels._windows_extended_path(path),
            )
        finally:
            temporary_text = AlabamaBleModels._windows_extended_path(temporary)
            if os.path.isfile(temporary_text):
                os.unlink(temporary_text)

    @staticmethod
    def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
        """Return a payload digest suitable for portable delivery receipts."""
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _validate_cached_archive(
        cls,
        archive_path: Path,
        expected_identity: Dict[str, object],
    ) -> Dict[str, object]:
        sidecar_path = cls._source_sidecar(archive_path)
        if not archive_path.is_file() or not sidecar_path.is_file():
            raise RuntimeError(
                f"Existing archive cache has no verified identity sidecar: {archive_path}"
            )
        recorded = json.loads(sidecar_path.read_text(encoding="utf-8"))
        for key in ("source_url", "final_url", "size_bytes", "etag"):
            if recorded.get(key) != expected_identity.get(key):
                raise RuntimeError(
                    f"Existing archive identity mismatch for {archive_path.name}: {key}."
                )
        if archive_path.stat().st_size != int(expected_identity["size_bytes"]):
            raise RuntimeError(
                f"Existing archive size mismatch for {archive_path.name}."
            )
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad_member = archive.testzip()
            member_count = len(archive.infolist())
        if bad_member:
            raise RuntimeError(
                f"Existing archive CRC failure in {archive_path.name}: {bad_member}"
            )
        return {**recorded, "member_count": member_count, "sidecar": str(sidecar_path)}

    @classmethod
    def _download_file(
        cls,
        url: str,
        destination: Union[str, Path],
        overwrite: bool = False,
        expected_identity: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        """Download one ZIP atomically and bind it to size/strong-ETag identity."""
        destination = Path(destination)
        url = cls._validate_public_archive_url(url, "Source URL")
        expected = expected_identity or cls._probe_asset(url)
        cls._validate_public_archive_url(
            expected.get("source_url"), "Expected source URL"
        )
        cls._validate_public_archive_url(
            expected.get("final_url"), "Expected final URL"
        )
        if expected.get("source_url") != url:
            raise RuntimeError("Preflight identity is bound to a different source URL.")
        if destination.exists() and not overwrite:
            return cls._validate_cached_archive(destination, expected)

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f".{destination.name}.part-{uuid.uuid4().hex}")
        response: Optional[requests.Response] = None
        try:
            response = cls._request_archive(
                "GET",
                url,
                stream=True,
                timeout=cls._DOWNLOAD_TIMEOUT,
            )
            observed_final_url = cls._validate_public_archive_url(
                str(response.url), "Download redirect URL"
            )
            observed = {
                "source_url": url,
                "final_url": observed_final_url,
                "size_bytes": int(response.headers.get("Content-Length", "-1")),
                "etag": cls._normalize_etag(response.headers.get("ETag")),
            }
            for key in ("final_url", "size_bytes", "etag"):
                if observed.get(key) != expected.get(key):
                    raise RuntimeError(
                        f"Alabama BLE GET identity differs from preflight for "
                        f"{destination.name}: {key}."
                    )
            with partial.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=cls._DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        stream.write(chunk)
            if partial.stat().st_size != int(expected["size_bytes"]):
                raise RuntimeError(
                    f"Downloaded byte count differs from Content-Length for {url}."
                )
            with zipfile.ZipFile(partial, "r") as archive:
                bad_member = archive.testzip()
                member_count = len(archive.infolist())
            if bad_member:
                raise RuntimeError(f"Downloaded ZIP CRC failure: {bad_member}")
            os.replace(partial, destination)
            sidecar = {
                **expected,
                "completed_utc": datetime.now(timezone.utc).isoformat(),
                "member_count": member_count,
            }
            cls._atomic_write_json(cls._source_sidecar(destination), sidecar)
            return {
                **sidecar,
                "path": str(destination),
                "sidecar": str(cls._source_sidecar(destination)),
            }
        finally:
            if response is not None:
                response.close()
            if partial.exists():
                partial.unlink()

    @staticmethod
    def _safe_zip_members(
        archive: zipfile.ZipFile,
    ) -> List[Tuple[zipfile.ZipInfo, Path]]:
        windows_devices = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "CONIN$",
            "CONOUT$",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
        }
        members: List[Tuple[zipfile.ZipInfo, Path]] = []
        targets = set()
        for member in archive.infolist():
            source_name = member.filename.replace("\\", "/")
            parsed = PurePosixPath(source_name)
            parts = tuple(part for part in parsed.parts if part not in {"", "."})
            if (
                not parts
                or parsed.is_absolute()
                or any(part == ".." for part in parts)
                or re.match(r"^[A-Za-z]:", parts[0])
            ):
                raise ValueError(f"Unsafe ZIP member path: {member.filename!r}")
            for part in parts:
                device_stem = part.split(".", 1)[0].upper()
                if (
                    ":" in part
                    or part.endswith((".", " "))
                    or device_stem in windows_devices
                ):
                    raise ValueError(
                        f"Unsafe Windows ZIP member component: {member.filename!r}"
                    )
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(
                    f"ZIP symbolic link is not supported: {member.filename!r}"
                )
            relative = Path(*parts)
            # Delivery folders must remain portable to Windows even when an
            # archive is inspected on a case-sensitive host.
            key = relative.as_posix().casefold()
            if key in targets and not member.is_dir():
                raise ValueError(f"Duplicate ZIP target: {member.filename!r}")
            targets.add(key)
            members.append((member, relative))
        return members

    @classmethod
    def _validate_extraction_receipt(
        cls,
        destination: Path,
        archive_path: Path,
    ) -> Dict[str, object]:
        receipt_path = destination / cls._EXTRACTION_RECEIPT
        if not receipt_path.is_file():
            raise RuntimeError(
                f"Existing extraction has no verification receipt: {destination}"
            )
        if receipt_path.is_symlink():
            raise RuntimeError(
                f"Extraction verification receipt must not be a symlink: {receipt_path}"
            )
        try:
            receipt_path.resolve(strict=True).relative_to(destination.resolve())
        except (FileNotFoundError, ValueError) as exc:
            raise RuntimeError(
                f"Extraction verification receipt escapes destination: {receipt_path}"
            ) from exc
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        with zipfile.ZipFile(cls._windows_extended_path(archive_path), "r") as archive:
            members = cls._safe_zip_members(archive)
        expected_files = {
            relative.as_posix(): {
                "size_bytes": member.file_size,
                "crc32": f"{member.CRC:08x}",
            }
            for member, relative in members
            if not member.is_dir()
        }
        receipt_files = {
            str(record.get("path")): {
                "size_bytes": int(record.get("size_bytes", -1)),
                "crc32": str(record.get("crc32") or "").casefold(),
            }
            for record in receipt.get("files", [])
        }
        if (
            receipt.get("schema_version") != 2
            or receipt.get("archive_name") != archive_path.name
            or receipt.get("archive_size_bytes") != archive_path.stat().st_size
            or receipt.get("archive_sha256") != cls._sha256_file(archive_path)
            or receipt.get("member_count") != len(members)
            or receipt.get("file_count") != len(expected_files)
            or receipt_files != expected_files
        ):
            raise RuntimeError(f"Extraction/archive identity mismatch: {destination}")
        destination_resolved = destination.resolve()
        actual_files = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file() and path.name != cls._EXTRACTION_RECEIPT
        }
        if actual_files != set(expected_files):
            raise RuntimeError(
                f"Extraction file inventory differs from archive: {destination}"
            )
        for relative, identity in expected_files.items():
            target = destination / Path(relative)
            if target.is_symlink():
                raise RuntimeError(f"Extraction contains a symbolic link: {target}")
            try:
                target.resolve(strict=True).relative_to(destination_resolved)
            except (FileNotFoundError, ValueError) as exc:
                raise RuntimeError(
                    f"Extraction file escapes its verified destination: {target}"
                ) from exc
            target_text = cls._windows_extended_path(target)
            if not os.path.isfile(target_text) or os.path.getsize(target_text) != int(
                identity["size_bytes"]
            ):
                raise RuntimeError(f"Extraction audit failed for {target}")
            checksum = 0
            with open(target_text, "rb") as stream:
                while chunk := stream.read(cls._DOWNLOAD_CHUNK_SIZE):
                    checksum = zlib.crc32(chunk, checksum)
            if f"{checksum & 0xFFFFFFFF:08x}" != identity["crc32"]:
                raise RuntimeError(f"Extraction CRC32 audit failed for {target}")
        project = cls._find_single_ras_project(destination)
        project_files = [Path(project["prj_file"]).relative_to(destination).as_posix()]
        if receipt.get("project_files") != project_files:
            raise RuntimeError(f"Extraction project identity mismatch: {destination}")
        return receipt

    @staticmethod
    def _find_single_ras_project(root: Path) -> Dict[str, object]:
        """Resolve exactly one true HEC-RAS project below ``root``."""
        from ras_commander.RasUtils import RasUtils

        projects = RasUtils.find_valid_ras_folders(
            root,
            return_project_info=True,
            include_nested_projects=True,
        )
        if len(projects) != 1:
            raise RuntimeError(
                f"Expected exactly one valid HEC-RAS project in {root}; "
                f"found {len(projects)}."
            )
        return dict(projects[0])

    @classmethod
    def _preflight_hecras_active_paths(
        cls,
        destination: Path,
        members: Sequence[Tuple[zipfile.ZipInfo, Path]],
    ) -> int:
        """Fail before extraction when a final HEC-RAS path exceeds 240 chars."""
        destination = Path(destination).absolute()
        maximum = max(
            (len(str(destination / relative)) for _, relative in members),
            default=len(str(destination)),
        )
        if maximum > cls._MAX_HECRAS_ACTIVE_PATH:
            raise ValueError(
                f"Archive would create a {maximum}-character HEC-RAS active path "
                f"under {destination}; the supported maximum is "
                f"{cls._MAX_HECRAS_ACTIVE_PATH}. Choose a shorter workspace/output "
                "root (for example H:\\Testing\\eBFE\\<HUC8>) and retry."
            )
        return maximum

    @classmethod
    def _safe_extract_zip(
        cls,
        zip_path: Union[str, Path],
        destination: Union[str, Path],
        overwrite: bool = False,
        *,
        active_destination: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Extract a ZIP through a verified sibling and atomically promote it."""
        zip_path = Path(zip_path)
        destination = Path(destination)
        # Validate hostile members before inspecting or touching a destination.
        with zipfile.ZipFile(cls._windows_extended_path(zip_path), "r") as archive:
            validated_members = cls._safe_zip_members(archive)
        maximum_active_path = cls._preflight_hecras_active_paths(
            Path(active_destination) if active_destination is not None else destination,
            validated_members,
        )
        if destination.exists() and not overwrite:
            cls._validate_extraction_receipt(destination, zip_path)
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".x-", dir=destination.parent))
        backup: Optional[Path] = None
        try:
            file_records = []
            with zipfile.ZipFile(cls._windows_extended_path(zip_path), "r") as archive:
                members = cls._safe_zip_members(archive)
                for member, relative in members:
                    target = temporary / relative
                    target_text = cls._windows_extended_path(target)
                    if member.is_dir():
                        os.makedirs(target_text, exist_ok=True)
                        continue
                    os.makedirs(
                        cls._windows_extended_path(target.parent), exist_ok=True
                    )
                    checksum = 0
                    size = 0
                    with (
                        archive.open(member, "r") as source,
                        open(target_text, "wb") as sink,
                    ):
                        while chunk := source.read(cls._DOWNLOAD_CHUNK_SIZE):
                            sink.write(chunk)
                            checksum = zipfile.crc32(chunk, checksum)
                            size += len(chunk)
                    checksum &= 0xFFFFFFFF
                    if size != member.file_size or checksum != member.CRC:
                        raise RuntimeError(
                            f"Extraction audit failed for {member.filename!r}"
                        )
                    file_records.append(
                        {
                            "path": relative.as_posix(),
                            "size_bytes": size,
                            "crc32": f"{checksum:08x}",
                        }
                    )
            project = cls._find_single_ras_project(temporary)
            project_files = [
                Path(project["prj_file"]).relative_to(temporary).as_posix()
            ]
            receipt = {
                "schema_version": 2,
                "completed_utc": datetime.now(timezone.utc).isoformat(),
                "archive_name": zip_path.name,
                "archive_size_bytes": zip_path.stat().st_size,
                "archive_sha256": cls._sha256_file(zip_path),
                "member_count": len(members),
                "file_count": len(file_records),
                "project_files": project_files,
                "maximum_active_path_length": maximum_active_path,
                "files": file_records,
            }
            cls._atomic_write_json(temporary / cls._EXTRACTION_RECEIPT, receipt)
            if destination.exists():
                backup = destination.with_name(
                    f".{destination.name}.replaced-{uuid.uuid4().hex}"
                )
                os.replace(
                    cls._windows_extended_path(destination),
                    cls._windows_extended_path(backup),
                )
            os.replace(
                cls._windows_extended_path(temporary),
                cls._windows_extended_path(destination),
            )
            if backup is not None:
                shutil.rmtree(cls._windows_extended_path(backup))
            return destination
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(
                    cls._windows_extended_path(backup),
                    cls._windows_extended_path(destination),
                )
            if temporary.exists():
                shutil.rmtree(cls._windows_extended_path(temporary))
            raise

    @staticmethod
    def _safe_component(value: object) -> str:
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value).strip())
        text = re.sub(r"\s+", "_", text).rstrip(" .")
        if text in {"", ".", ".."}:
            raise ValueError(f"Unsafe empty delivery path component: {value!r}")
        return text

    @staticmethod
    def _metadata_archive_name(metadata: ModelMetadata) -> str:
        value = metadata.extra.get("archive_name") or metadata.extra.get("file_name")
        if value:
            return str(value)
        if metadata.url:
            return unquote(Path(urlparse(metadata.url).path).name)
        raise ValueError(f"Model {metadata.source_id} has no archive filename.")

    @classmethod
    def _read_extraction_receipt(cls, destination: Path) -> Dict[str, object]:
        return json.loads(
            (Path(destination) / cls._EXTRACTION_RECEIPT).read_text(encoding="utf-8")
        )

    @classmethod
    def _delivery_paths(
        cls, output_folder: Union[str, Path], huc8: str
    ) -> Dict[str, Path]:
        root = Path(output_folder) / f"AL{cls.normalize_huc8(huc8)}"
        return {
            "root": root,
            "archives": root / "Source Archives",
            "models": root / "RAS Models",
            "documentation": root / "Documentation",
        }

    @classmethod
    def _delivery_manifest_payload(
        cls,
        huc8: str,
        models: Sequence[ModelMetadata],
        records: Sequence[Dict[str, object]],
        status: str,
        mode: str,
    ) -> Dict[str, object]:
        normalized = cls.normalize_huc8(huc8)
        return {
            "schema_name": cls._MANIFEST_SCHEMA_NAME,
            "contract_version": cls._MANIFEST_CONTRACT_VERSION,
            "schema_version": 1,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source_name": cls.SOURCE_NAME,
            "source_service": cls._SERVICE_URL,
            "source_url": cls._SERVICE_URL,
            "source_policy": cls._SOURCE_POLICY,
            "study_key": f"AL{normalized}",
            "huc8": normalized,
            "watershed_name": cls._watershed_name(normalized),
            "mode": mode,
            "status": status,
            "expected_model_count": len(models),
            "model_count": len(records),
            "basin_count": len({str(item.extra.get("basin") or "") for item in models}),
            "actual_record_count": len(records),
            "basin_counts": dict(
                sorted(
                    Counter(
                        str(item.extra.get("basin") or "") for item in models
                    ).items()
                )
            ),
            "records": list(records),
        }

    @classmethod
    def _write_delivery_manifest(
        cls,
        paths: Dict[str, Path],
        huc8: str,
        models: Sequence[ModelMetadata],
        records: Sequence[Dict[str, object]],
        status: str,
        mode: str,
    ) -> Path:
        manifest_path = paths["documentation"] / cls._MANIFEST_NAME
        cls._atomic_write_json(
            manifest_path,
            cls._delivery_manifest_payload(huc8, models, records, status, mode),
        )
        return manifest_path

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
        """Download one Alabama BLE model and optionally extract it safely."""
        del credentials  # The public source is anonymous.
        try:
            metadata = cls.get_model_metadata(model_id, huc8=kwargs.get("huc8"))
            output = Path(output_folder)
            archive_name = cls._safe_component(cls._metadata_archive_name(metadata))
            archive_path = output / archive_name
            archive_record = cls._download_file(
                str(metadata.url),
                archive_path,
                overwrite=overwrite,
            )
            if isinstance(archive_record, dict):
                identity = {
                    key: archive_record[key]
                    for key in ("source_url", "final_url", "size_bytes", "etag")
                    if key in archive_record
                }
                if identity.get("size_bytes") is not None:
                    metadata.file_size_mb = int(identity["size_bytes"]) / (1024 * 1024)
                metadata.extra["source_identity"] = identity
            if not extract:
                return DownloadResult(
                    True,
                    archive_path,
                    f"Downloaded and verified {archive_name}.",
                    metadata,
                    False,
                )
            extracted_path = output / Path(archive_name).stem
            cls._safe_extract_zip(
                archive_path,
                extracted_path,
                overwrite=overwrite,
            )
            metadata.extra["archive_identity"] = archive_record
            metadata.extra["extraction_receipt"] = cls._read_extraction_receipt(
                extracted_path
            )
            return DownloadResult(
                True,
                extracted_path,
                f"Downloaded and verified {metadata.name}.",
                metadata,
                True,
            )
        except Exception as exc:
            logger.error("Alabama BLE model download failed: %s", exc)
            return DownloadResult(False, None, str(exc), None, False)

    @classmethod
    @log_call
    def download_watershed(
        cls,
        huc8: str,
        output_folder: Union[str, Path],
        extract: bool = True,
        overwrite: bool = False,
        credentials: Optional[dict] = None,
    ) -> DownloadResult:
        """Download one complete Alabama BLE HUC8 delivery grouped by basin."""
        del credentials
        normalized = cls.normalize_huc8(huc8)
        models: List[ModelMetadata] = []
        records: List[Dict[str, object]] = []
        paths = cls._delivery_paths(output_folder, normalized)
        materialization_started = False
        try:
            models = cls.build_watershed_manifest(normalized)
            cls._validate_watershed_membership(normalized, models)
            cls._validate_qualified_corpus(normalized, models)
            for folder in paths.values():
                folder.mkdir(parents=True, exist_ok=True)
            materialization_started = True
            download_cache: Dict[str, Tuple[Path, object]] = {}
            for metadata in models:
                basin = cls._safe_component(metadata.extra["basin"])
                archive_name = cls._safe_component(cls._metadata_archive_name(metadata))
                archive_path = paths["archives"] / basin / archive_name
                source_url = str(metadata.url)
                if source_url in download_cache:
                    cached_path, archive_record = download_cache[source_url]
                    if cached_path != archive_path:
                        archive_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cached_path, archive_path)
                        cached_sidecar = cls._source_sidecar(cached_path)
                        if cached_sidecar.is_file():
                            shutil.copy2(
                                cached_sidecar, cls._source_sidecar(archive_path)
                            )
                else:
                    archive_record = cls._download_file(
                        source_url,
                        archive_path,
                        overwrite=overwrite,
                    )
                    download_cache[source_url] = (archive_path, archive_record)
                if not isinstance(archive_record, dict):
                    raise RuntimeError(
                        f"Downloader returned no verified source identity for {source_url}."
                    )
                archive_details = dict(archive_record)
                identity = {
                    key: archive_details[key]
                    for key in ("source_url", "final_url", "size_bytes", "etag")
                    if key in archive_details
                }
                record: Dict[str, object] = {
                    "study_id": f"AL{normalized}",
                    "model_id": metadata.source_id,
                    "model_key": f"AL{normalized}:{metadata.source_id}",
                    "display_id": cls._safe_component(Path(archive_name).stem),
                    "source_id": metadata.source_id,
                    "name": metadata.name,
                    "basin": metadata.extra["basin"],
                    "archive_name": archive_name,
                    "source_url": metadata.url,
                    "source_identity": identity,
                    "archive": {
                        **archive_details,
                        "path": archive_path.relative_to(paths["root"]).as_posix(),
                        "sidecar": (
                            cls._source_sidecar(archive_path)
                            .relative_to(paths["root"])
                            .as_posix()
                            if cls._source_sidecar(archive_path).is_file()
                            else None
                        ),
                    },
                    "archive_path": archive_path.relative_to(paths["root"]).as_posix(),
                    "archive_sha256": cls._sha256_file(archive_path),
                }
                source_sidecar = cls._source_sidecar(archive_path)
                if not source_sidecar.is_file():
                    raise RuntimeError(
                        f"Verified download sidecar is missing: {source_sidecar}"
                    )
                record["source_sidecar"] = source_sidecar.relative_to(
                    paths["root"]
                ).as_posix()
                if extract:
                    model_folder = cls._safe_component(Path(archive_name).stem)
                    extracted_path = paths["models"] / basin / model_folder
                    cls._safe_extract_zip(
                        archive_path,
                        extracted_path,
                        overwrite=overwrite,
                    )
                    receipt = cls._read_extraction_receipt(extracted_path)
                    record["extraction"] = {
                        "path": extracted_path.relative_to(paths["root"]).as_posix(),
                        "member_count": receipt["member_count"],
                        "file_count": receipt["file_count"],
                        "project_files": receipt["project_files"],
                    }
                records.append(record)
            cls._write_delivery_manifest(
                paths, normalized, models, records, "complete", "download"
            )
            return DownloadResult(
                True,
                paths["root"],
                f"Verified {len(records)} Alabama BLE models in AL{normalized}.",
                None,
                extract,
            )
        except Exception as exc:
            logger.error("Alabama BLE watershed download failed: %s", exc)
            if models and materialization_started:
                cls._write_delivery_manifest(
                    paths, normalized, models, records, "failed", "download"
                )
            return DownloadResult(False, paths["root"], str(exc), None, extract)

    @staticmethod
    def _canonical_identity(value: object) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).casefold())

    @classmethod
    def _index_staged_source(
        cls,
        source_root: Path,
    ) -> Tuple[Dict[str, List[Path]], Dict[str, List[Path]]]:
        source_root = source_root.resolve()
        archives: Dict[str, List[Path]] = defaultdict(list)
        folders: Dict[str, List[Path]] = defaultdict(list)
        for archive in source_root.rglob("*.zip"):
            if archive.is_file():
                cls._validate_staged_path(source_root, archive, "Staged archive")
                archives[cls._canonical_identity(archive.stem)].append(archive)
        # The second return value is retained for compatibility with the
        # original staging-index seam, but extracted folders are intentionally
        # never indexed or trusted as source evidence.
        return archives, folders

    @staticmethod
    def _validate_staged_path(
        source_root: Path,
        candidate: Path,
        label: str,
    ) -> Path:
        """Resolve a retained source artifact and keep it below source_root."""
        resolved_root = Path(source_root).resolve()
        resolved = Path(candidate).resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise RuntimeError(
                f"{label} resolves outside staged source root: {candidate}"
            ) from exc
        return resolved

    @classmethod
    def _staged_sidecar(cls, archive: Path) -> Optional[Path]:
        candidates = (
            archive.with_name(f"{archive.name}.ebfe-source.json"),
            cls._source_sidecar(archive),
        )
        return next((path for path in candidates if path.is_file()), None)

    @classmethod
    def _expected_staged_identity(
        cls,
        metadata: ModelMetadata,
    ) -> Dict[str, object]:
        size = metadata.extra.get("size_bytes")
        etag = cls._normalize_etag(metadata.extra.get("etag"))
        if size is None or etag is None:
            return cls._probe_asset(str(metadata.url))
        source_url = cls._validate_public_archive_url(metadata.url, "Source URL")
        final_url = cls._validate_public_archive_url(
            metadata.extra.get("final_url") or metadata.url,
            "Expected final URL",
        )
        return {
            "source_url": source_url,
            "final_url": final_url,
            "size_bytes": int(size),
            "etag": etag,
        }

    @classmethod
    def _normalize_source_identity_payload(
        cls,
        payload: Dict[str, object],
    ) -> Dict[str, object]:
        """Normalize ras-commander and retained eBFE sidecar field names."""
        source_url = cls._validate_public_archive_url(
            payload.get("source_url", payload.get("source")),
            "Sidecar source URL",
        )
        final_url = cls._validate_public_archive_url(
            payload.get("final_url"),
            "Sidecar final URL",
        )
        etag = cls._normalize_etag(payload.get("etag"))
        if etag is None or etag.startswith("W/"):
            raise RuntimeError("Source sidecar must contain a strong ETag.")
        size = payload.get("size_bytes", payload.get("size"))
        try:
            size_bytes = int(size)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Source sidecar has no valid byte size.") from exc
        return {
            "source_url": source_url,
            "final_url": final_url,
            "size_bytes": size_bytes,
            "etag": etag,
        }

    @classmethod
    def _validate_staged_archive(
        cls,
        archive: Path,
        metadata: ModelMetadata,
        source_root: Optional[Path] = None,
    ) -> Tuple[Dict[str, object], Path]:
        """Bind a staged ZIP and its retained sidecar to current source identity."""
        if source_root is not None:
            cls._validate_staged_path(source_root, archive, "Staged archive")
        sidecar = cls._staged_sidecar(archive)
        if sidecar is None:
            raise RuntimeError(
                f"Staged archive has no source identity sidecar: {archive}"
            )
        if source_root is not None:
            cls._validate_staged_path(source_root, sidecar, "Staged source sidecar")
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        recorded = cls._normalize_source_identity_payload(raw)
        expected = cls._expected_staged_identity(metadata)
        for key in ("source_url", "final_url", "size_bytes", "etag"):
            if recorded.get(key) != expected.get(key):
                raise RuntimeError(
                    f"Staged archive {key} identity mismatch for {archive.name}."
                )
        if archive.stat().st_size != int(expected["size_bytes"]):
            raise RuntimeError(f"Staged archive size mismatch for {archive.name}.")
        with zipfile.ZipFile(archive, "r") as source_zip:
            bad_member = source_zip.testzip()
        if bad_member:
            raise RuntimeError(f"Staged ZIP CRC failure for {archive}: {bad_member}")
        return recorded, sidecar

    @classmethod
    def _select_staged_item(
        cls,
        index: Dict[str, List[Path]],
        identities: Iterable[str],
    ) -> Optional[Path]:
        matches: List[Path] = []
        for identity in identities:
            matches.extend(index.get(cls._canonical_identity(identity), []))
        unique = sorted(set(matches), key=lambda path: (len(path.parts), str(path)))
        if len(unique) > 1 and len(unique[0].parts) == len(unique[1].parts):
            raise RuntimeError(f"Ambiguous staged Alabama BLE source: {unique[:2]}")
        return unique[0] if unique else None

    @classmethod
    @log_call
    def organize_watershed(
        cls,
        huc8: str,
        source_root: Union[str, Path],
        output_folder: Union[str, Path],
        overwrite: bool = False,
    ) -> DownloadResult:
        """Copy a complete staged corpus into one immutable basin-grouped delivery."""
        normalized = cls.normalize_huc8(huc8)
        source_root = Path(source_root).resolve()
        final_paths = cls._delivery_paths(output_folder, normalized)
        final_root = final_paths["root"]
        try:
            if not source_root.is_dir():
                raise FileNotFoundError(
                    f"Staged source root does not exist: {source_root}"
                )
            final_resolved = final_root.resolve()
            if (
                final_resolved == source_root
                or source_root in final_resolved.parents
                or final_resolved in source_root.parents
            ):
                raise ValueError(
                    "The final delivery and staged source roots must not be equal "
                    "or contain one another. Choose separate sibling roots."
                )
            if final_root.exists() and not overwrite:
                raise FileExistsError(
                    f"Delivery already exists: {final_root}. Set overwrite=True to replace it."
                )
            models = cls.build_watershed_manifest(normalized)
            cls._validate_watershed_membership(normalized, models)
            cls._validate_qualified_corpus(normalized, models)
            archive_index, _ = cls._index_staged_source(source_root)
            selections = []
            for metadata in models:
                archive_name = cls._metadata_archive_name(metadata)
                identities = (
                    Path(archive_name).stem,
                    f"{metadata.name} BLE",
                    metadata.name,
                    metadata.source_id,
                )
                archive = cls._select_staged_item(archive_index, identities)
                if archive is None:
                    raise FileNotFoundError(
                        f"No verified staged source archive for {metadata.source_id} "
                        f"({archive_name}); extracted folders alone are not accepted."
                    )
                staged_identity, staged_sidecar = cls._validate_staged_archive(
                    archive,
                    metadata,
                    source_root=source_root,
                )
                selections.append(
                    (
                        metadata,
                        archive,
                        staged_identity,
                        staged_sidecar,
                    )
                )

            output_root = Path(output_folder)
            output_root.mkdir(parents=True, exist_ok=True)
            temporary_root = Path(
                tempfile.mkdtemp(prefix=f".AL{normalized}.organizing-", dir=output_root)
            )
            temporary_paths = {
                "root": temporary_root,
                "archives": temporary_root / "Source Archives",
                "models": temporary_root / "RAS Models",
                "documentation": temporary_root / "Documentation",
            }
            records: List[Dict[str, object]] = []
            for folder in temporary_paths.values():
                folder.mkdir(parents=True, exist_ok=True)
            try:
                for (
                    metadata,
                    source_archive,
                    staged_identity,
                    staged_sidecar,
                ) in selections:
                    basin = cls._safe_component(metadata.extra["basin"])
                    archive_name = cls._safe_component(
                        cls._metadata_archive_name(metadata)
                    )
                    model_name = cls._safe_component(Path(archive_name).stem)
                    record: Dict[str, object] = {
                        "study_id": f"AL{normalized}",
                        "model_id": metadata.source_id,
                        "model_key": f"AL{normalized}:{metadata.source_id}",
                        "display_id": model_name,
                        "source_id": metadata.source_id,
                        "name": metadata.name,
                        "basin": metadata.extra["basin"],
                        "archive_name": archive_name,
                        "source_url": metadata.url,
                        "source_identity": staged_identity,
                        "staged_source": {
                            "verified": True,
                            "archive_present": True,
                            "extraction_present": False,
                            "delivery_derived_from_verified_archive": True,
                            "identity": staged_identity,
                        },
                    }
                    copied_archive = temporary_paths["archives"] / basin / archive_name
                    copied_archive.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_archive, copied_archive)
                    copied_sidecar = copied_archive.with_name(
                        f"{copied_archive.name}.ebfe-source.json"
                    )
                    shutil.copy2(staged_sidecar, copied_sidecar)
                    record["source_sidecar"] = copied_sidecar.relative_to(
                        temporary_root
                    ).as_posix()
                    with zipfile.ZipFile(copied_archive, "r") as archive:
                        bad_member = archive.testzip()
                    if bad_member:
                        raise RuntimeError(
                            f"Staged ZIP CRC failure for {source_archive}: {bad_member}"
                        )
                    record["archive_path"] = copied_archive.relative_to(
                        temporary_root
                    ).as_posix()
                    record["archive_sha256"] = cls._sha256_file(copied_archive)
                    destination = temporary_paths["models"] / basin / model_name
                    cls._safe_extract_zip(
                        copied_archive,
                        destination,
                        active_destination=(final_paths["models"] / basin / model_name),
                    )

                    project_info = cls._find_single_ras_project(destination)
                    receipt = cls._read_extraction_receipt(destination)
                    project_files = [
                        Path(project_info["prj_file"])
                        .relative_to(destination)
                        .as_posix()
                    ]
                    record["extraction"] = {
                        "path": destination.relative_to(temporary_root).as_posix(),
                        "member_count": receipt["member_count"],
                        "file_count": receipt["file_count"],
                        "project_files": project_files,
                    }
                    records.append(record)

                cls._write_delivery_manifest(
                    temporary_paths,
                    normalized,
                    models,
                    records,
                    "complete",
                    "staged-copy",
                )
                backup = None
                if final_root.exists():
                    backup = final_root.with_name(
                        f".{final_root.name}.replaced-{uuid.uuid4().hex}"
                    )
                    os.replace(final_root, backup)
                try:
                    os.replace(temporary_root, final_root)
                except Exception:
                    if (
                        backup is not None
                        and backup.exists()
                        and not final_root.exists()
                    ):
                        os.replace(backup, final_root)
                    raise
                if backup is not None:
                    try:
                        shutil.rmtree(backup)
                    except OSError as exc:
                        logger.warning(
                            "Organized delivery succeeded but retained backup %s: %s",
                            backup,
                            exc,
                        )
            except Exception:
                if temporary_root.exists():
                    shutil.rmtree(temporary_root)
                raise
            return DownloadResult(
                True,
                final_root,
                f"Organized {len(records)} Alabama BLE models in AL{normalized}.",
                None,
                True,
            )
        except Exception as exc:
            logger.error("Alabama BLE watershed organization failed: %s", exc)
            return DownloadResult(False, final_root, str(exc), None, False)

    @classmethod
    @log_call
    def build_watershed_delivery_inventory(
        cls,
        delivery_root: Union[str, Path],
        *,
        ras_version: Optional[str] = None,
        output_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, object]:
        """Inspect one organized corpus and write a portable FIM intake inventory.

        HEC-RAS project, plan, geometry, and flow associations are resolved through
        :class:`RasPrj` DataFrames. All paths written to the inventory are relative
        to ``delivery_root`` so the complete folder can be moved as one unit.
        """
        root = Path(delivery_root).resolve()
        source_manifest_path = (root / "Documentation" / cls._MANIFEST_NAME).resolve()
        try:
            source_manifest_path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                "Alabama BLE delivery manifest escapes delivery_root."
            ) from exc
        if not source_manifest_path.is_file():
            raise FileNotFoundError(
                f"Alabama BLE delivery manifest not found: {source_manifest_path}"
            )
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        if (
            source_manifest.get("schema_name") != cls._MANIFEST_SCHEMA_NAME
            or source_manifest.get("contract_version") != cls._MANIFEST_CONTRACT_VERSION
            or type(source_manifest.get("schema_version")) is not int
            or source_manifest.get("schema_version") != 1
            or source_manifest.get("source_name") != cls.SOURCE_NAME
            or source_manifest.get("source_service") != cls._SERVICE_URL
            or source_manifest.get("source_url") != cls._SERVICE_URL
            or source_manifest.get("source_policy") != cls._SOURCE_POLICY
        ):
            raise RuntimeError("Alabama BLE delivery manifest identity is invalid.")
        if source_manifest.get("status") != "complete":
            raise RuntimeError("Alabama BLE delivery is not marked complete.")
        normalized = cls.normalize_huc8(str(source_manifest.get("huc8") or ""))
        study_id = f"AL{normalized}"
        if source_manifest.get("study_key") != study_id:
            raise RuntimeError("Alabama BLE delivery study identity is invalid.")
        if source_manifest.get("mode") not in {"download", "staged-copy"}:
            raise RuntimeError("Alabama BLE delivery manifest mode is invalid.")
        records = list(source_manifest.get("records") or [])
        if not all(isinstance(record, dict) for record in records):
            raise RuntimeError("Alabama BLE delivery records must be objects.")
        count_fields = (
            source_manifest.get("expected_model_count"),
            source_manifest.get("model_count"),
            source_manifest.get("actual_record_count"),
        )
        if any(type(value) is not int for value in count_fields) or any(
            value != len(records) for value in count_fields
        ):
            raise RuntimeError("Alabama BLE delivery record count is inconsistent.")
        actual_basins = dict(
            sorted(
                Counter(str(record.get("basin") or "") for record in records).items()
            )
        )
        if (
            type(source_manifest.get("basin_count")) is not int
            or source_manifest.get("basin_count") != len(actual_basins)
            or source_manifest.get("basin_counts") != actual_basins
        ):
            raise RuntimeError(
                "Alabama BLE delivery basin declaration is inconsistent."
            )
        cls._validate_qualified_corpus(normalized, records)

        from ras_commander.RasPrj import RasPrj, init_ras_project

        def contained_path(
            base: Path,
            relative_value: object,
            label: str,
        ) -> Path:
            relative = Path(str(relative_value or ""))
            if not str(relative_value or "") or relative.is_absolute():
                raise RuntimeError(f"{label} must be a non-empty relative path.")
            resolved_base = base.resolve()
            resolved = (resolved_base / relative).resolve()
            try:
                resolved.relative_to(resolved_base)
            except ValueError as exc:
                raise RuntimeError(
                    f"{label} escapes its delivery container: {relative_value!r}"
                ) from exc
            return resolved

        def portable_file(path: Path) -> Dict[str, object]:
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(
                    f"Delivery reference escapes the corpus root: {resolved}"
                ) from exc
            if not resolved.is_file():
                raise FileNotFoundError(f"Delivery file not found: {resolved}")
            return {
                "path": relative.as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": cls._sha256_file(resolved),
            }

        model_ids = [str(item.get("model_id") or "") for item in records]
        model_keys = [str(item.get("model_key") or "") for item in records]
        display_ids = [str(item.get("display_id") or "") for item in records]
        if not all(model_ids) or len(set(model_ids)) != len(model_ids):
            raise RuntimeError(
                "Alabama BLE delivery contains missing or duplicate publisher ModelIDs."
            )
        if not all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) for value in model_ids
        ):
            raise RuntimeError(
                "Alabama BLE delivery contains a non-canonical publisher ModelID."
            )
        if not all(model_keys) or len(set(model_keys)) != len(model_keys):
            raise RuntimeError(
                "Alabama BLE delivery contains missing or duplicate model keys."
            )
        if not all(display_ids) or len(set(display_ids)) != len(display_ids):
            raise RuntimeError(
                "Alabama BLE delivery contains missing or duplicate display IDs."
            )
        if not all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) for value in display_ids
        ):
            raise RuntimeError(
                "Alabama BLE delivery contains a non-canonical display ID."
            )

        qualification = cls._qualification(normalized)
        require_steady_1d = qualification.get("model_type") == ModelType.STEADY_1D
        inventory_records: List[Dict[str, object]] = []
        corpus_crs: set[str] = set()
        for source_record in records:
            model_id = str(source_record.get("model_id") or "")
            model_name = str(source_record.get("name") or "").strip()
            source_basin = str(source_record.get("basin") or "").strip()
            if not model_name or not source_basin:
                raise RuntimeError(
                    f"Model {model_id or '<missing>'} must have a name and source basin."
                )
            archive_name = str(source_record.get("archive_name") or "")
            expected_display_id = cls._safe_component(Path(archive_name).stem)
            if (
                source_record.get("study_id") != study_id
                or source_record.get("source_id") != model_id
                or source_record.get("model_key") != f"{study_id}:{model_id}"
                or source_record.get("display_id") != expected_display_id
            ):
                raise RuntimeError(
                    f"Model {model_id or '<missing>'} has non-canonical delivery identity."
                )

            source_url = cls._validate_public_archive_url(
                source_record.get("source_url"), "Manifest source URL"
            )
            source_identity_raw = source_record.get("source_identity")
            if not isinstance(source_identity_raw, dict):
                raise RuntimeError(f"Model {model_id} has no source identity.")
            source_identity = cls._normalize_source_identity_payload(
                source_identity_raw
            )
            if source_identity["source_url"] != source_url:
                raise RuntimeError(
                    f"Model {model_id} source identity does not match URL."
                )

            archive_file = contained_path(
                root,
                source_record.get("archive_path"),
                f"Model {model_id} archive_path",
            )
            sidecar_file = contained_path(
                root,
                source_record.get("source_sidecar"),
                f"Model {model_id} source_sidecar",
            )
            if not sidecar_file.is_file():
                raise FileNotFoundError(
                    f"Model {model_id} source sidecar not found: {sidecar_file}"
                )
            sidecar_payload = json.loads(sidecar_file.read_text(encoding="utf-8"))
            if (
                cls._normalize_source_identity_payload(sidecar_payload)
                != source_identity
            ):
                raise RuntimeError(f"Model {model_id} source sidecar identity differs.")
            if not archive_file.is_file() or archive_file.stat().st_size != int(
                source_identity["size_bytes"]
            ):
                raise RuntimeError(f"Model {model_id} archive byte identity differs.")
            expected_archive_hash = str(source_record.get("archive_sha256") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_archive_hash):
                raise RuntimeError(f"Model {model_id} has no valid archive SHA256.")
            if cls._sha256_file(archive_file) != expected_archive_hash:
                raise RuntimeError(f"Source archive hash changed for {model_id}.")

            extraction = dict(source_record.get("extraction") or {})
            extraction_root = contained_path(
                root,
                extraction.get("path"),
                f"Model {model_id} extraction.path",
            )
            if not extraction_root.is_dir():
                raise FileNotFoundError(
                    f"Model {model_id} extraction not found: {extraction_root}"
                )
            extraction_receipt = cls._validate_extraction_receipt(
                extraction_root,
                archive_file,
            )
            project_files = list(extraction.get("project_files") or [])
            if len(project_files) != 1:
                raise RuntimeError(
                    f"Model {model_id} must contain exactly one "
                    f"HEC-RAS project; found {len(project_files)}."
                )
            if project_files != extraction_receipt.get("project_files"):
                raise RuntimeError(
                    f"Model {model_id} manifest project identity differs from its "
                    "verified extraction receipt."
                )
            project_file = contained_path(
                extraction_root,
                project_files[0],
                f"Model {model_id} project file",
            )
            try:
                project_file.relative_to(root)
            except ValueError as exc:  # defense in depth for future path changes
                raise RuntimeError(
                    f"Model {model_id} project file escapes delivery root."
                ) from exc
            ras_object = RasPrj()
            init_ras_project(
                project_file,
                ras_version=ras_version,
                ras_object=ras_object,
                load_results_summary=False,
                hide_intro=True,
            )
            if len(ras_object.plan_df) != 1:
                raise RuntimeError(
                    f"Model {source_record.get('model_id')} must resolve exactly one "
                    f"registered plan for corpus intake; found {len(ras_object.plan_df)}."
                )
            plan = ras_object.plan_df.iloc[0]
            plan_number = str(plan.get("plan_number") or "").strip()
            geom_number = str(plan["geometry_number"])
            flow_number = str(plan.get("Flow File") or "").strip()
            flow_path_value = str(plan.get("Flow Path") or "").strip()
            if (
                not plan_number
                or plan_number.casefold() in {"none", "nan", "<na>"}
                or not geom_number.strip()
                or geom_number.casefold() in {"none", "nan", "<na>"}
                or not flow_number
                or flow_number.casefold() in {"none", "nan", "<na>"}
                or not flow_path_value
                or flow_path_value.casefold() in {"none", "nan", "<na>"}
            ):
                raise RuntimeError(
                    f"Model {model_id} plan is missing a registered geometry or "
                    "steady-flow association."
                )
            geom_rows = ras_object.geom_df.loc[
                ras_object.geom_df["geom_number"].astype(str) == geom_number
            ]
            if len(geom_rows) != 1:
                raise RuntimeError(
                    f"Model {source_record.get('model_id')} plan {plan['plan_number']} "
                    f"does not resolve exactly one geometry {geom_number}."
                )
            geometry = geom_rows.iloc[0]
            plan_type = str(plan.get("plan_type") or "").strip()
            geometry_type = str(geometry.get("geometry_type") or "").strip()
            geometry_hdf_value = str(geometry.get("hdf_path") or "").strip()
            project_crs = str(ras_object.project_crs or "").strip()
            if not geometry_hdf_value or geometry_hdf_value.casefold() in {
                "none",
                "nan",
                "<na>",
            }:
                raise RuntimeError(
                    f"Model {model_id} has no registered geometry HDF association."
                )
            if require_steady_1d and plan_type.casefold() != "steady_1d":
                raise RuntimeError(
                    f"Qualified AL{normalized} model {model_id} is not steady_1d: "
                    f"{plan_type or '<missing>'}."
                )
            if require_steady_1d and geometry_type.casefold() != "1d":
                raise RuntimeError(
                    f"Qualified AL{normalized} model {model_id} is not 1D geometry: "
                    f"{geometry_type or '<missing>'}."
                )
            if require_steady_1d and not project_crs:
                raise RuntimeError(
                    f"Qualified AL{normalized} model {model_id} has no project CRS."
                )
            if project_crs:
                corpus_crs.add(project_crs)
            plan_file = Path(str(plan["full_path"]))
            geometry_file = Path(str(geometry["full_path"]))
            geometry_hdf = Path(geometry_hdf_value)
            flow_file = Path(flow_path_value)
            for association_label, associated_path in (
                ("plan", plan_file),
                ("geometry", geometry_file),
                ("geometry HDF", geometry_hdf),
                ("steady flow", flow_file),
            ):
                try:
                    associated_path.resolve().relative_to(extraction_root.resolve())
                except ValueError as exc:
                    raise RuntimeError(
                        f"Model {model_id} registered {association_label} association "
                        "escapes its extraction root."
                    ) from exc
            files = {
                "source_archive": portable_file(archive_file),
                "source_sidecar": portable_file(sidecar_file),
                "project": portable_file(project_file),
                "plan": portable_file(plan_file),
                "geometry": portable_file(geometry_file),
                "geometry_hdf": portable_file(geometry_hdf),
                "flow": portable_file(flow_file),
            }
            units_system = str(RasPrj.get_project_units(project_file) or "").strip()
            if not units_system:
                raise RuntimeError(f"Model {model_id} has no project units system.")
            inventory_records.append(
                {
                    "study_id": f"AL{normalized}",
                    "model_id": source_record.get("model_id")
                    or source_record.get("source_id"),
                    "model_key": source_record.get("model_key"),
                    "display_id": source_record.get("display_id"),
                    "model_name": model_name,
                    "source_basin": source_basin,
                    "plan_number": plan_number,
                    "geometry_number": geom_number,
                    "flow_number": flow_number,
                    "plan_type": plan_type,
                    "geometry_type": geometry_type,
                    "cross_section_count": int(geometry["num_cross_sections"]),
                    "project_crs": project_crs,
                    "units_system": units_system,
                    "delivered_ras_version": plan.get("Program Version"),
                    "files": files,
                }
            )

        if require_steady_1d and len(corpus_crs) != 1:
            raise RuntimeError(
                f"Qualified AL{normalized} corpus must use one consistent project "
                f"CRS; found {sorted(corpus_crs)}."
            )

        payload: Dict[str, object] = {
            "schema_name": "ras_commander.watershed_delivery_inventory",
            "contract_version": "1.0.0",
            "schema_version": 1,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "path_policy": "relative_to_delivery_root",
            "study_id": f"AL{normalized}",
            "huc8": normalized,
            "watershed_name": cls._watershed_name(normalized),
            "source_manifest": portable_file(source_manifest_path),
            "model_count": len(inventory_records),
            "project_count": len(inventory_records),
            "plan_count": len(inventory_records),
            "geometry_hdf_count": len(inventory_records),
            "records": inventory_records,
        }
        destination = (
            (
                Path(output_path)
                if Path(output_path).is_absolute()
                else root / Path(output_path)
            )
            if output_path is not None
            else root / "Documentation" / "watershed_delivery_inventory.json"
        )
        try:
            destination.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Inventory output must remain inside delivery_root."
            ) from exc
        cls._atomic_write_json(destination, payload)
        return payload

    @classmethod
    @log_call
    def get_source_status(cls) -> SourceStatus:
        """Return availability after checking both required anonymous layers."""
        try:
            payload = cls._request_json(cls._SERVICE_URL, {"f": "json"})
            layer_ids = {int(item["id"]) for item in payload.get("layers", [])}
            table_ids = {int(item["id"]) for item in payload.get("tables", [])}
            if cls._MODEL_LAYER_ID in layer_ids and cls._LINK_LAYER_ID in table_ids:
                return SourceStatus.AVAILABLE
        except Exception as exc:
            logger.debug("Alabama BLE source status failed: %s", exc)
        return SourceStatus.UNAVAILABLE


__all__ = ["AlabamaBleModels"]
