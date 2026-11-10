"""
Louisiana Watershed Initiative (LWI) EnDMC model and data source.

The Environmental Data and Model Catalog (EnDMC, https://lwi.endmc.org) is
operated by The Water Institute for the Louisiana Watershed Initiative. It
catalogs HEC-RAS, HEC-HMS, HEC-FIA, and Go-Consequences model applications
and supporting datasets. Every published resource's files sit in the public
S3 bucket ``lwi-model-data`` (us-east-1) under::

    endmc-managed/{model_application|dataset}/{24-hex resource id}/<files>

No account is needed for either half of this source:

* **Catalog** - the public search page loads its results from
  ``GET https://lwi.endmc.org/search`` with ``Accept: application/json``.
  The unauthenticated response lists every published model application,
  dataset, and simulation package with its id, title, description, and
  keywords. Software is resolved with the same endpoint's ``software=<id>``
  filter. A dated snapshot of the public fields ships with the package as an
  offline fallback (``source="snapshot"``).
* **Files** - anonymous S3 ``ListObjectsV2`` and HTTP range ``GET``.

Throughput guidance (measured from a CLB workstation, November 2026): about
60 MB/s on one stream and about 120 MB/s with four parallel streams. Large
design-storm resources exceed 400 GiB, so select components before
downloading. S3 ETags for multipart uploads are not MD5 digests; downloads are
verified by byte length, and optionally by the full-object CRC64NVME checksum
S3 returns when ``x-amz-checksum-mode: ENABLED`` is sent (requires the
optional ``awscrt`` package).

Example:
    >>> from ras_commander.sources.state import LouisianaEndmc
    >>> resources = LouisianaEndmc.list_resources(software="HEC-RAS")
    >>> objects = LouisianaEndmc.list_objects(resources.iloc[0]["resource_id"])
    >>> objects.groupby("component")["size"].sum()
    >>> LouisianaEndmc.download_resource(
    ...     resources.iloc[0]["resource_id"],
    ...     r"H:\\Testing\\endmc\\abbeville",
    ...     components=["ras_project", "geometry_hdf", "terrain", "land_cover"],
    ... )
"""

from __future__ import annotations

import base64
import fnmatch
import html
import json
import os
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union
from urllib.parse import quote

import pandas as pd
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

BUCKET = "lwi-model-data"
BUCKET_REGION = "us-east-1"
S3_ENDPOINT = f"https://{BUCKET}.s3.{BUCKET_REGION}.amazonaws.com"
MANAGED_PREFIX = "endmc-managed"
ENDMC_BASE_URL = "https://lwi.endmc.org"
SEARCH_URL = f"{ENDMC_BASE_URL}/search"

RESOURCE_KINDS: Tuple[str, ...] = ("model_application", "dataset")
CATALOG_KINDS: Tuple[str, ...] = RESOURCE_KINDS + ("simulation_package",)

# Software ids exposed by the public search filter values.
SOFTWARE_IDS: Dict[str, str] = {
    "6349ac1e22ebd4a9959d593c": "HEC-RAS",
    "63cabd42d9e3b6aea518a788": "HEC-HMS",
    "63ec0348e9d34f65583ba8cf": "Go Consequences",
    "6410b3ad4b81a63a147ecd4d": "HEC-FIA",
}

COMPONENTS: Tuple[str, ...] = (
    "ras_project",
    "geometry_hdf",
    "plan_hdf",
    "ras_run_artifact",
    "terrain",
    "land_cover",
    "infiltration",
    "output_depth",
    "output_wse",
    "output_velocity",
    "output_raster_other",
    "hms",
    "dss",
    "gis",
    "docs",
    "metadata",
    "other",
)
OUTPUT_RASTER_COMPONENTS: Tuple[str, ...] = (
    "output_depth",
    "output_wse",
    "output_velocity",
)

REQUEST_TIMEOUT = 60
USER_AGENT = "ras-commander-endmc-source"
DEFAULT_MAX_WORKERS = 4
DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024
DEFAULT_MAX_PATH_LENGTH = 240
DEFAULT_MODEL_MAX_BYTES = 50 * 1024**3
_PARTIAL_SUFFIX = ".part"
_STATE_SUFFIX = ".part.json"
_RECEIPT_SCHEMA = "ras-commander-endmc-download/1"
_SNAPSHOT_RESOURCE = "louisiana_endmc_catalog_snapshot.json"
_S3_NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
_RESOURCE_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_REGION_RE = re.compile(r"\bRegion\s*(\d{1,2})\b|\(R(\d{1,2})\)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_EPSG_RE = re.compile(r"^EPSG:\d+$", re.IGNORECASE)
_WINDOWS_INVALID = set('<>:"|?*')

_RASTER_EXTS = {".tif", ".tiff", ".vrt", ".img", ".flt", ".asc", ".bil", ".grd"}
_RASTER_SIDECARS = (".aux.xml", ".ovr", ".tfw", ".xml", ".hdr", ".prj")
_GIS_EXTS = {
    ".shp", ".shx", ".dbf", ".cpg", ".sbn", ".sbx", ".qix", ".fbn", ".fbx",
    ".ain", ".aih", ".atx", ".spx", ".gdbtable", ".gdbtablx", ".gdbindexes",
    ".freelist", ".horizon", ".geojson", ".gpkg", ".kml", ".kmz", ".lyr",
    ".lyrx", ".mxd", ".aprx", ".dwg", ".dgn", ".las", ".laz", ".lock",
}
_HMS_EXTS = {
    ".hms", ".basin", ".met", ".control", ".gage", ".run", ".pdata", ".dsc",
    ".grid", ".results", ".animation", ".stor", ".sqlite", ".access",
}
_DOC_EXTS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".csv", ".ppt",
    ".pptx", ".md", ".txt", ".rtf", ".htm", ".html", ".png", ".jpg", ".jpeg",
    ".onetoc2", ".one",
}
_RAS_TEXT_RE = re.compile(r"\.(?:[pgufqhs]\d{2}|rasmap)$", re.IGNORECASE)
_RAS_RUN_RE = re.compile(
    r"\.(?:b\d{2}|bco\d{2}|c\d{2}|x\d{2}|o\d{2}|ic\.o\d{2}|r\d{2}|hyd\d{2}|"
    r"rst|snapshot\.hdf|backup\.hdf|dss\.bak|backup|bak|computemsgs\.txt|tmp\.hdf)$",
    re.IGNORECASE,
)
_TERRAIN_DIR_RE = re.compile(r"terrain|bathy|\bdem\b|_dem\b|\bdem_", re.IGNORECASE)
_LAND_DIR_RE = re.compile(
    r"land[ _-]?(?:cover|use|classification)|lulc|nlcd|ccap|manning|roughness",
    re.IGNORECASE,
)
_INFILTRATION_RE = re.compile(r"infiltration|ssurgo|\bsoils?\b|soils?_|hydrologic[ _-]?soil", re.IGNORECASE)
_OUTPUT_DIR_RE = re.compile(r"output|flood|result|max|aep|grids?\b|rasters?", re.IGNORECASE)
_DEPTH_RE = re.compile(r"depth", re.IGNORECASE)
_WSE_RE = re.compile(
    r"(?<![a-z])wse(?![a-z])|wsel|water[ _-]?surface|watersurfaceelevation",
    re.IGNORECASE,
)
_VELOCITY_RE = re.compile(r"velocity|(?<![a-z])vel(?![a-z])", re.IGNORECASE)

_live_cache: Dict[str, Any] = {}
_live_cache_lock = threading.Lock()


class LouisianaEndmc:
    """
    Louisiana Watershed Initiative EnDMC catalog and public S3 file access.

    All methods are static. Network reads are anonymous: the public
    ``/search`` JSON endpoint for the catalog and the public
    ``lwi-model-data`` bucket for files. Credentials are never accepted,
    stored, or required.

    Example:
        >>> from ras_commander.sources.state import LouisianaEndmc
        >>> df = LouisianaEndmc.list_resources(region="Region 5")
        >>> rasters = LouisianaEndmc.get_raster_urls("685d772c2ecdbd05b0cb03d1")
        >>> rasters[["component", "vsicurl"]].head()
    """

    SOURCE_NAME = "Louisiana LWI EnDMC"

    @property
    def source_name(self) -> str:
        """Human-readable source name."""
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        """Source category."""
        return "state"

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def list_resources(
        kinds: Optional[Sequence[str]] = None,
        search: Optional[str] = None,
        software: Optional[str] = None,
        region: Optional[Union[str, int]] = None,
        source: str = "auto",
        refresh: bool = False,
        timeout: float = REQUEST_TIMEOUT,
    ) -> pd.DataFrame:
        """
        Return the EnDMC catalog as a DataFrame without logging in.

        Args:
            kinds: Resource kinds to return. Defaults to the downloadable
                kinds ``("model_application", "dataset")``. Add
                ``"simulation_package"`` to include package records, which
                group resources but have no bucket prefix.
            search: Full-text query passed to the site's ``search`` parameter
                (live source only). Snapshot rows are filtered by a
                case-insensitive substring match on title and keywords.
            software: ``"HEC-RAS"``, ``"HEC-HMS"``, ``"HEC-FIA"``, or
                ``"Go Consequences"`` (case-insensitive).
            region: LWI region number or label, for example ``5`` or
                ``"Region 5"``. Region is derived from titles and keywords
                and is ``None`` where no region is stated.
            source: ``"auto"`` (live, falling back to the bundled snapshot),
                ``"live"``, or ``"snapshot"``.
            refresh: Bypass the in-process live catalog cache.
            timeout: HTTP timeout in seconds.

        Returns:
            DataFrame with columns ``resource_id``, ``kind``, ``title``,
            ``region``, ``software``, ``date``, ``keywords``, ``description``,
            ``url``, ``s3_prefix``, and ``catalog_source``. ``date`` is the
            record date from the bundled snapshot (None for resources newer
            than the snapshot; use :meth:`get_resource_metadata` for those).
        """
        kinds = _normalize_kinds(kinds)
        if source not in {"auto", "live", "snapshot"}:
            raise ValueError("source must be 'auto', 'live', or 'snapshot'")

        snapshot = _load_snapshot()
        rows: Optional[List[Dict[str, Any]]] = None
        if source in {"auto", "live"}:
            try:
                rows = _live_catalog_rows(search=search, refresh=refresh, timeout=timeout)
            except (requests.RequestException, ValueError) as exc:
                if source == "live":
                    raise
                logger.warning(
                    "EnDMC live catalog unavailable (%s); using bundled snapshot captured %s",
                    exc,
                    snapshot.get("captured"),
                )
        if rows is None:
            rows = _snapshot_rows(snapshot, search=search)

        snapshot_by_id = {r["resource_id"]: r for r in snapshot.get("resources", [])}
        records = []
        for row in rows:
            if row["kind"] not in kinds:
                continue
            snap = snapshot_by_id.get(row["resource_id"], {})
            row_software = row.get("software") or snap.get("software")
            keywords = list(row.get("keywords") or snap.get("keywords") or [])
            title = row.get("title") or snap.get("title") or ""
            records.append(
                {
                    "resource_id": row["resource_id"],
                    "kind": row["kind"],
                    "title": title,
                    "region": derive_region(title, keywords),
                    "software": row_software,
                    "date": snap.get("date"),
                    "keywords": keywords,
                    "description": row.get("description"),
                    "url": f"{ENDMC_BASE_URL}/view/{row['kind']}/{row['resource_id']}",
                    "s3_prefix": (
                        _resource_prefix(row["kind"], row["resource_id"])
                        if row["kind"] in RESOURCE_KINDS
                        else None
                    ),
                    "catalog_source": row["catalog_source"],
                }
            )

        df = pd.DataFrame.from_records(
            records,
            columns=[
                "resource_id", "kind", "title", "region", "software", "date",
                "keywords", "description", "url", "s3_prefix", "catalog_source",
            ],
        )
        if software:
            wanted = software.strip().casefold()
            df = df[df["software"].fillna("").str.casefold() == wanted]
        if region is not None:
            wanted_region = _normalize_region(region)
            df = df[df["region"] == wanted_region]
        df = df.sort_values(["kind", "title"], kind="stable").reset_index(drop=True)
        df.attrs["snapshot_captured"] = snapshot.get("captured")
        return df

    @staticmethod
    @log_call
    def list_s3_resource_ids(
        kinds: Optional[Sequence[str]] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> pd.DataFrame:
        """
        Inventory resource ids directly from the public bucket.

        The bucket can hold prefixes that are absent from the public catalog
        (for example unpublished or withdrawn records). Compare this result
        with :meth:`list_resources` to find them.

        Returns:
            DataFrame with ``resource_id``, ``kind``, and ``s3_prefix``.
        """
        rows = []
        for kind in _normalize_kinds(kinds, allowed=RESOURCE_KINDS):
            prefix = f"{MANAGED_PREFIX}/{kind}/"
            for common in _list_common_prefixes(prefix, timeout=timeout):
                resource_id = common[len(prefix):].strip("/")
                if _RESOURCE_ID_RE.match(resource_id):
                    rows.append(
                        {"resource_id": resource_id, "kind": kind, "s3_prefix": common}
                    )
        return pd.DataFrame(rows, columns=["resource_id", "kind", "s3_prefix"])

    @staticmethod
    @log_call
    def get_resource_metadata(
        resource_id: str,
        kind: Optional[str] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        Read the public metadata page for one resource.

        Parses ``https://lwi.endmc.org/view/<kind>/<id>``, which is served
        without login. Returns the labelled metadata fields (for example
        ``Application date``, ``Coordinate system``, ``Common software
        version``), containing packages, and associated simulations. Author
        and owner contact fields are omitted. Parsing is best effort and
        follows the page markup observed in November 2026.

        Returns:
            Dict with ``resource_id``, ``kind``, ``url``, ``title``,
            ``fields``, ``access_level``, ``containing_packages``, and
            ``associated_resources``.
        """
        kind = _resolve_kind(resource_id, kind, timeout=timeout)
        url = f"{ENDMC_BASE_URL}/view/{kind}/{resource_id}"
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=timeout,
        )
        response.raise_for_status()
        parsed = parse_resource_page(response.text)
        parsed.update({"resource_id": resource_id, "kind": kind, "url": url})
        return parsed

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def list_objects(
        resource_id: str,
        kind: Optional[str] = None,
        components: Optional[Sequence[str]] = None,
        patterns: Optional[Sequence[str]] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> pd.DataFrame:
        """
        List a resource's S3 objects with component classification.

        Args:
            resource_id: 24-character hexadecimal EnDMC id.
            kind: ``"model_application"`` or ``"dataset"``; resolved
                automatically when omitted.
            components: Keep only these components (see ``COMPONENTS``).
            patterns: Keep only relative paths matching any of these
                case-insensitive glob patterns (``fnmatch`` syntax, ``*``
                matches across folders).
            timeout: HTTP timeout in seconds.

        Returns:
            DataFrame with ``key``, ``relative_path``, ``size``,
            ``last_modified``, ``etag``, ``checksum_algorithm``,
            ``checksum_type``, ``storage_class``, ``component``, and ``url``.
        """
        kind = _resolve_kind(resource_id, kind, timeout=timeout)
        prefix = _resource_prefix(kind, resource_id)
        objects = list(_list_objects(prefix, timeout=timeout))
        df = objects_dataframe(objects, prefix)
        df = filter_objects(df, components=components, patterns=patterns)
        df.attrs.update({"resource_id": resource_id, "kind": kind, "s3_prefix": prefix})
        return df

    @staticmethod
    def classify_object(relative_path: str, sibling_stems: Optional[Set[str]] = None) -> str:
        """Classify one relative object path into a ``COMPONENTS`` value."""
        return classify_object(relative_path, sibling_stems)

    @staticmethod
    def object_url(key: str) -> str:
        """Return the anonymous HTTPS URL for a bucket key."""
        return f"{S3_ENDPOINT}/{quote(key, safe='/~')}"

    @staticmethod
    def vsicurl_path(key: str) -> str:
        """Return a GDAL ``/vsicurl/`` path for range-reading a bucket object."""
        return "/vsicurl/" + LouisianaEndmc.object_url(key)

    @staticmethod
    @log_call
    def get_raster_urls(
        resource_id: str,
        kind: Optional[str] = None,
        components: Sequence[str] = OUTPUT_RASTER_COMPONENTS,
        timeout: float = REQUEST_TIMEOUT,
    ) -> pd.DataFrame:
        """
        Return HTTPS and ``/vsicurl/`` paths for a resource's rasters.

        GDAL-based readers (rasterio, GDAL, ras2cng) can open the
        ``vsicurl`` column directly and read windows or overviews by HTTP
        range without downloading the file. Raster sidecars are excluded.

        Returns:
            DataFrame with ``relative_path``, ``component``, ``size``,
            ``url``, and ``vsicurl``.
        """
        df = LouisianaEndmc.list_objects(
            resource_id, kind=kind, components=components, timeout=timeout
        )
        mask = df["relative_path"].map(
            lambda p: PurePosixPath(p).suffix.lower() in _RASTER_EXTS
        )
        out = df.loc[mask, ["key", "relative_path", "component", "size", "url"]].copy()
        out["vsicurl"] = "/vsicurl/" + out["url"]
        return out.reset_index(drop=True)

    @staticmethod
    @log_call
    def read_range(
        key: str,
        start: int,
        length: int,
        timeout: float = REQUEST_TIMEOUT,
    ) -> bytes:
        """Read ``length`` bytes from ``start`` of a bucket object by HTTP range."""
        if start < 0 or length <= 0:
            raise ValueError("start must be >= 0 and length must be > 0")
        response = requests.get(
            LouisianaEndmc.object_url(key),
            headers={"Range": f"bytes={start}-{start + length - 1}", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        if response.status_code != 206:
            raise RuntimeError(f"Server did not honor the byte range for {key}")
        return response.content

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def download_resource(
        resource_id: str,
        output_folder: Union[str, Path],
        kind: Optional[str] = None,
        components: Optional[Sequence[str]] = None,
        patterns: Optional[Sequence[str]] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overwrite: bool = False,
        verify: str = "size",
        max_path_length: Optional[int] = DEFAULT_MAX_PATH_LENGTH,
        max_bytes: Optional[int] = None,
        dry_run: bool = False,
        timeout: float = REQUEST_TIMEOUT,
    ) -> pd.DataFrame:
        """
        Download selected objects from one resource with resumable ranges.

        Files are written below ``output_folder`` at their path relative to
        the resource prefix. Each file is assembled in ``<name>.part``;
        files larger than ``chunk_size`` are fetched as parallel byte ranges
        and record completed ranges in ``<name>.part.json`` so an
        interrupted download resumes where it stopped. Ranges are requested
        with ``If-Match`` on the listed ETag, so an object replaced on the
        server restarts instead of mixing versions. A receipt named
        ``_endmc_<resource_id>.json`` records every selected object.

        Args:
            resource_id: 24-character hexadecimal EnDMC id.
            output_folder: Destination root. Keep it short: resource paths
                are already long, and the default ``max_path_length`` (240)
                keeps HEC-RAS-active paths below ``MAX_PATH`` with headroom.
            kind: ``"model_application"`` or ``"dataset"`` (auto-resolved).
            components: Components to download (see ``COMPONENTS``); all
                when omitted.
            patterns: Case-insensitive relative-path globs; combined with
                ``components`` as an AND filter.
            max_workers: Parallel HTTP streams (default 4).
            chunk_size: Range size in bytes (default 64 MiB).
            overwrite: Re-download files that already exist with the
                expected size.
            verify: ``"size"`` (default) or ``"crc64nvme"``. The checksum
                mode compares S3's full-object CRC64NVME with the local file
                and requires the optional ``awscrt`` package.
            max_path_length: Refuse the download when any destination path
                (plus the partial-file suffix) exceeds this length. ``None``
                disables the check.
            max_bytes: Refuse when the selected total exceeds this size.
            dry_run: Return the plan without downloading.
            timeout: HTTP timeout per request in seconds.

        Returns:
            DataFrame with ``relative_path``, ``key``, ``component``,
            ``size``, ``local_path``, ``status`` (``planned``, ``present``,
            ``downloaded``, or ``failed``), ``verified``, and ``error``.
            ``attrs`` hold ``receipt_path``, ``total_bytes``, and counts.

        Raises:
            ValueError: Unsafe object paths, path length or size limits.
            ImportError: ``verify="crc64nvme"`` without ``awscrt``.
        """
        if verify not in {"size", "crc64nvme"}:
            raise ValueError("verify must be 'size' or 'crc64nvme'")
        if verify == "crc64nvme":
            _require_awscrt()
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if chunk_size < 1024 * 1024:
            raise ValueError("chunk_size must be at least 1 MiB")

        objects = LouisianaEndmc.list_objects(
            resource_id, kind=kind, components=components, patterns=patterns, timeout=timeout
        )
        kind = objects.attrs["kind"]
        root = Path(output_folder).absolute()
        objects = objects[~objects["key"].str.endswith("/")]

        plan = []
        too_long = []
        for row in objects.itertuples(index=False):
            target = safe_destination(root, row.relative_path)
            if max_path_length is not None and len(str(target)) + len(_STATE_SUFFIX) > max_path_length:
                too_long.append(str(target))
            plan.append((row, target))
        if too_long:
            longest = max(too_long, key=len)
            raise ValueError(
                f"{len(too_long)} destination path(s) exceed max_path_length="
                f"{max_path_length} (including the '{_STATE_SUFFIX}' partial suffix). "
                f"Longest ({len(longest)} chars): {longest}. Choose a shorter "
                "output_folder, narrow the selection, or pass max_path_length=None "
                "for archive-only copies."
            )

        total_bytes = int(sum(int(row.size) for row, _ in plan))
        if max_bytes is not None and total_bytes > max_bytes:
            raise ValueError(
                f"Selected objects total {total_bytes:,} bytes, above max_bytes="
                f"{max_bytes:,}. Narrow components/patterns or raise max_bytes."
            )
        logger.info(
            "EnDMC %s: %d objects, %.2f GiB selected",
            resource_id,
            len(plan),
            total_bytes / 1024**3,
        )

        results: Dict[str, Dict[str, Any]] = {}
        jobs: List[_FileJob] = []
        for row, target in plan:
            result = {
                "relative_path": row.relative_path,
                "key": row.key,
                "component": row.component,
                "size": int(row.size),
                "etag": row.etag,
                "last_modified": row.last_modified,
                "local_path": str(target),
                "status": "planned",
                "verified": None,
                "error": None,
            }
            results[row.key] = result
            if dry_run:
                continue
            if not overwrite and _existing_size(target) == int(row.size):
                result["status"] = "present"
                continue
            jobs.append(_FileJob(row.key, target, int(row.size), row.etag, result))

        if jobs:
            _run_jobs(jobs, max_workers=max_workers, chunk_size=chunk_size, verify=verify, timeout=timeout)

        df = pd.DataFrame(
            list(results.values()),
            columns=[
                "relative_path", "key", "component", "size", "local_path",
                "status", "verified", "error", "etag", "last_modified",
            ],
        )
        df.attrs.update(
            {
                "resource_id": resource_id,
                "kind": kind,
                "total_bytes": total_bytes,
                "counts": df["status"].value_counts().to_dict(),
            }
        )
        if not dry_run:
            receipt = _write_receipt(
                root, resource_id, kind, list(results.values()), components, patterns, verify
            )
            df.attrs["receipt_path"] = str(receipt)
            failed = int((df["status"] == "failed").sum())
            if failed:
                logger.error("EnDMC %s: %d file(s) failed; rerun to resume", resource_id, failed)
        return df

    # ------------------------------------------------------------------
    # ModelSource protocol
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def list_models(
        location: Optional[str] = None,
        model_type: Optional[ModelType] = None,
        hecras_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        software: Optional[str] = "HEC-RAS",
        **kwargs,
    ) -> List[ModelMetadata]:
        """
        List EnDMC model applications as ``ModelMetadata`` for ``ModelCatalog``.

        Args:
            location: Case-insensitive substring of the location, title, or
                region (for example ``"Region 2"`` or ``"Dugdemona"``).
            model_type: Applied when given; EnDMC metadata does not state
                steady/unsteady, so entries are ``ModelType.UNKNOWN``.
            hecras_version: Version keyword such as ``"6.4.1"``.
            tags: Required tags (AND logic).
            limit: Maximum results.
            software: Software filter; defaults to ``"HEC-RAS"``. ``None``
                returns every model application.
        """
        df = LouisianaEndmc.list_resources(
            kinds=("model_application",), software=software, source=kwargs.get("source", "auto")
        )
        models: List[ModelMetadata] = []
        for row in df.itertuples(index=False):
            metadata = _row_to_metadata(row)
            haystack = f"{metadata.location} {metadata.name}".lower()
            if location and location.lower() not in haystack:
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
        return models

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
        Download a resource for ``ModelCatalog``.

        ``credentials`` is ignored; EnDMC files are public. Keyword arguments
        are passed to :meth:`download_resource`. ``max_bytes`` defaults to
        50 GiB here so an unfiltered catalog download cannot silently pull a
        400 GiB design-storm resource; pass ``components`` or
        ``max_bytes=None`` deliberately. ``extract`` is ignored (EnDMC serves
        individual files, not archives).
        """
        kwargs.setdefault("max_bytes", DEFAULT_MODEL_MAX_BYTES)
        try:
            df = LouisianaEndmc.download_resource(
                model_id, output_folder, overwrite=overwrite, **kwargs
            )
        except (ValueError, requests.RequestException) as exc:
            return DownloadResult(success=False, model_path=None, message=str(exc))
        failed = int((df["status"] == "failed").sum())
        return DownloadResult(
            success=failed == 0,
            model_path=Path(output_folder),
            message=(
                f"{len(df)} objects, {df.attrs.get('total_bytes', 0):,} bytes; "
                f"status counts {df.attrs.get('counts')}"
            ),
            extracted=False,
        )

    @staticmethod
    @log_call
    def get_source_status() -> SourceStatus:
        """Return AVAILABLE when the public bucket answers an anonymous listing."""
        try:
            response = requests.get(
                f"{S3_ENDPOINT}/",
                params={"list-type": "2", "prefix": f"{MANAGED_PREFIX}/", "max-keys": "1"},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return SourceStatus.AVAILABLE
        except requests.RequestException as exc:
            logger.warning("EnDMC bucket unreachable: %s", exc)
            return SourceStatus.UNAVAILABLE


# ----------------------------------------------------------------------
# Catalog helpers
# ----------------------------------------------------------------------


def derive_region(title: str, keywords: Iterable[str] = ()) -> Optional[str]:
    """Return ``"Region N"`` from a title or keywords, or ``None``."""
    for text in [title, *keywords]:
        match = _REGION_RE.search(text or "")
        if match:
            return f"Region {int(match.group(1) or match.group(2))}"
    return None


def _normalize_region(region: Union[str, int]) -> str:
    text = str(region).strip()
    if text.isdigit():
        return f"Region {int(text)}"
    derived = derive_region(text)
    if derived is None:
        raise ValueError(f"Unrecognized region: {region!r}")
    return derived


def _normalize_kinds(
    kinds: Optional[Sequence[str]], allowed: Tuple[str, ...] = CATALOG_KINDS
) -> Tuple[str, ...]:
    if kinds is None:
        return RESOURCE_KINDS
    if isinstance(kinds, str):
        kinds = (kinds,)
    unknown = [k for k in kinds if k not in allowed]
    if unknown:
        raise ValueError(f"Unknown kind(s) {unknown}; expected {allowed}")
    return tuple(kinds)


def _load_snapshot() -> Dict[str, Any]:
    from importlib.resources import files

    text = files("ras_commander.resources").joinpath(_SNAPSHOT_RESOURCE).read_text(encoding="utf-8")
    return json.loads(text)


def _snapshot_rows(snapshot: Dict[str, Any], search: Optional[str]) -> List[Dict[str, Any]]:
    needle = (search or "").casefold()
    rows = []
    for row in snapshot.get("resources", []):
        if needle:
            haystack = " ".join([row.get("title") or "", *row.get("keywords", [])]).casefold()
            if needle not in haystack:
                continue
        rows.append({**row, "description": None, "catalog_source": "snapshot"})
    return rows


def _search_json(params: Dict[str, str], timeout: float) -> Dict[str, Any]:
    response = requests.get(
        SEARCH_URL,
        params=params,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), dict):
        raise ValueError("EnDMC /search returned an unexpected payload")
    return payload


def parse_search_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a public ``/search`` JSON payload into catalog rows."""
    rows = []
    for kind in CATALOG_KINDS:
        for item in payload.get("results", {}).get(kind, []) or []:
            resource_id = str(item.get("_id", ""))
            if not _RESOURCE_ID_RE.match(resource_id):
                continue
            rows.append(
                {
                    "resource_id": resource_id,
                    "kind": kind,
                    "title": (item.get("title") or "").strip(),
                    "description": item.get("description"),
                    "keywords": [
                        k.strip() for k in item.get("keywords_agg") or [] if k and k.strip()
                    ],
                    "software": None,
                    "catalog_source": "live",
                }
            )
    return rows


def _live_catalog_rows(
    search: Optional[str], refresh: bool, timeout: float
) -> List[Dict[str, Any]]:
    cache_key = search or ""
    with _live_cache_lock:
        cached = _live_cache.get(cache_key)
    if cached is not None and not refresh:
        return [dict(r) for r in cached]

    params = {"search": search} if search else {}
    rows = parse_search_payload(_search_json(params, timeout))
    software_by_id: Dict[str, str] = {}
    for software_id, name in SOFTWARE_IDS.items():
        payload = _search_json({**params, "software": software_id}, timeout)
        for item in payload["results"].get("model_application", []) or []:
            software_by_id[str(item.get("_id"))] = name
    for row in rows:
        row["software"] = software_by_id.get(row["resource_id"])
    with _live_cache_lock:
        _live_cache[cache_key] = rows
    return [dict(r) for r in rows]


def _row_to_metadata(row: Any) -> ModelMetadata:
    keywords = list(row.keywords or [])
    version = next((k for k in keywords if _VERSION_RE.match(k)), None)
    projection = next((k.upper() for k in keywords if _EPSG_RE.match(k)), None)
    location = "Louisiana" + (f", {row.region}" if row.region else "")
    tags = ["louisiana", "lwi", "endmc"]
    if row.software:
        tags.append(str(row.software).lower())
    if row.region:
        tags.append(str(row.region).lower())
    return ModelMetadata(
        source_name=LouisianaEndmc.SOURCE_NAME,
        source_id=row.resource_id,
        name=row.title,
        description=(row.description or "")[:500],
        location=location,
        model_type=ModelType.UNKNOWN,
        hecras_version=version if row.software == "HEC-RAS" else None,
        url=row.url,
        study_date=row.date,
        projection=projection,
        tags=tags,
        extra={"kind": row.kind, "software": row.software, "s3_prefix": row.s3_prefix},
    )


_FIELD_RE = re.compile(
    r'metadata-field-label[^"]*"[^>]*>(.*?)</div>\s*<div class="metadata-field-value">(.*?)</div>\s*</div>',
    re.DOTALL,
)
_ROW_RE = re.compile(r'<th scope="row">(.*?)</th>\s*<td>(.*?)</td>', re.DOTALL)
_PROPS_RE = re.compile(r'="(\{[^"]*&#34;resourceId&#34;[^"]*\})"')
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_OMITTED_FIELDS = {"authors", "author", "created by", "current owner", "owner", "contact"}


def _text(fragment: str) -> str:
    fragment = re.sub(r"<script.*?</script>", " ", fragment, flags=re.DOTALL)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+,", ",", text)
    return _EMAIL_RE.sub("[email omitted]", text)


def parse_resource_page(page: str) -> Dict[str, Any]:
    """Parse labelled fields and resource links from a public EnDMC view page."""
    fields: Dict[str, str] = {}
    for label, value in [*_FIELD_RE.findall(page), *_ROW_RE.findall(page)]:
        name = _text(label)
        if not name or name.casefold() in _OMITTED_FIELDS:
            continue
        fields.setdefault(name, _text(value))
    props: Dict[str, Any] = {}
    match = _PROPS_RE.search(page)
    if match:
        try:
            props = json.loads(html.unescape(match.group(1)))
        except ValueError:
            props = {}

    def links(items: Any) -> List[Dict[str, str]]:
        return [
            {"id": i.get("id"), "title": i.get("title"), "url": ENDMC_BASE_URL + (i.get("url") or "")}
            for i in items or []
            if isinstance(i, dict)
        ]

    title_match = _TITLE_RE.search(page)
    return {
        "title": _text(title_match.group(1)) if title_match else None,
        "fields": fields,
        "access_level": props.get("initialAccessLevel"),
        "containing_packages": links(props.get("containingPackages")),
        "associated_resources": links(props.get("associatedResources")),
    }


# ----------------------------------------------------------------------
# S3 helpers
# ----------------------------------------------------------------------


def _resource_prefix(kind: str, resource_id: str) -> str:
    if not _RESOURCE_ID_RE.match(resource_id or ""):
        raise ValueError(f"Invalid EnDMC resource id: {resource_id!r}")
    if kind not in RESOURCE_KINDS:
        raise ValueError(f"Invalid EnDMC resource kind: {kind!r}")
    return f"{MANAGED_PREFIX}/{kind}/{resource_id}/"


def _resolve_kind(resource_id: str, kind: Optional[str], timeout: float) -> str:
    if not _RESOURCE_ID_RE.match(resource_id or ""):
        raise ValueError(f"Invalid EnDMC resource id: {resource_id!r}")
    if kind is not None:
        if kind not in CATALOG_KINDS:
            raise ValueError(f"Invalid EnDMC resource kind: {kind!r}")
        return kind
    for row in _load_snapshot().get("resources", []):
        if row["resource_id"] == resource_id:
            return row["kind"]
    for candidate in RESOURCE_KINDS:
        response = _s3_list({"prefix": _resource_prefix(candidate, resource_id), "max-keys": "1"}, timeout)
        if response.findall("s:Contents", _S3_NS):
            return candidate
    raise ValueError(f"EnDMC resource {resource_id} not found in the public bucket")


def _s3_list(params: Dict[str, str], timeout: float) -> ET.Element:
    query = {"list-type": "2", **params}
    last_error: Optional[Exception] = None
    for attempt in range(4):
        try:
            response = requests.get(
                f"{S3_ENDPOINT}/", params=query, headers={"User-Agent": USER_AGENT}, timeout=timeout
            )
            if response.status_code >= 500:
                raise requests.HTTPError(f"S3 {response.status_code}", response=response)
            response.raise_for_status()
            return ET.fromstring(response.content)
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code < 500:
                raise
            time.sleep(min(2**attempt, 8))
    raise requests.ConnectionError(f"S3 listing failed after retries: {last_error}")


def parse_list_objects(root: ET.Element) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Parse one ListObjectsV2 XML page into object dicts and the next token."""
    objects = []
    for item in root.findall("s:Contents", _S3_NS):
        objects.append(
            {
                "key": item.findtext("s:Key", namespaces=_S3_NS),
                "size": int(item.findtext("s:Size", default="0", namespaces=_S3_NS)),
                "last_modified": item.findtext("s:LastModified", namespaces=_S3_NS),
                "etag": (item.findtext("s:ETag", default="", namespaces=_S3_NS) or "").strip('"'),
                "checksum_algorithm": item.findtext("s:ChecksumAlgorithm", namespaces=_S3_NS),
                "checksum_type": item.findtext("s:ChecksumType", namespaces=_S3_NS),
                "storage_class": item.findtext("s:StorageClass", namespaces=_S3_NS),
            }
        )
    token = None
    if root.findtext("s:IsTruncated", namespaces=_S3_NS) == "true":
        token = root.findtext("s:NextContinuationToken", namespaces=_S3_NS)
    return objects, token


def _list_objects(prefix: str, timeout: float) -> Iterable[Dict[str, Any]]:
    token: Optional[str] = None
    while True:
        params = {"prefix": prefix}
        if token:
            params["continuation-token"] = token
        objects, token = parse_list_objects(_s3_list(params, timeout))
        yield from objects
        if not token:
            return


def _list_common_prefixes(prefix: str, timeout: float) -> List[str]:
    prefixes: List[str] = []
    token: Optional[str] = None
    while True:
        params = {"prefix": prefix, "delimiter": "/"}
        if token:
            params["continuation-token"] = token
        root = _s3_list(params, timeout)
        prefixes.extend(
            p.findtext("s:Prefix", namespaces=_S3_NS) for p in root.findall("s:CommonPrefixes", _S3_NS)
        )
        if root.findtext("s:IsTruncated", namespaces=_S3_NS) != "true":
            return prefixes
        token = root.findtext("s:NextContinuationToken", namespaces=_S3_NS)


def objects_dataframe(objects: List[Dict[str, Any]], prefix: str) -> pd.DataFrame:
    """Build the classified object DataFrame for one resource prefix."""
    rel_paths = [o["key"][len(prefix):] if o["key"].startswith(prefix) else o["key"] for o in objects]
    stems: Set[str] = set()
    for rel in rel_paths:
        path = PurePosixPath(rel)
        if path.suffix.lower() in _GIS_EXTS | _RASTER_EXTS:
            stems.add(str(path.with_suffix("")).casefold())
    rows = []
    for obj, rel in zip(objects, rel_paths):
        rows.append(
            {
                **obj,
                "relative_path": rel,
                "component": classify_object(rel, stems),
                "url": LouisianaEndmc.object_url(obj["key"]),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "key", "relative_path", "size", "last_modified", "etag",
            "checksum_algorithm", "checksum_type", "storage_class", "component", "url",
        ],
    )


def filter_objects(
    df: pd.DataFrame,
    components: Optional[Sequence[str]] = None,
    patterns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Filter an object DataFrame by component and relative-path glob."""
    if components is not None:
        if isinstance(components, str):
            components = [components]
        unknown = sorted(set(components) - set(COMPONENTS))
        if unknown:
            raise ValueError(f"Unknown component(s) {unknown}; expected {COMPONENTS}")
        df = df[df["component"].isin(components)]
    if patterns:
        if isinstance(patterns, str):
            patterns = [patterns]
        lowered = [p.casefold() for p in patterns]
        df = df[
            df["relative_path"].map(
                lambda rel: any(fnmatch.fnmatchcase(rel.casefold(), p) for p in lowered)
            )
        ]
    return df.reset_index(drop=True)


def _strip_sidecar(name: str) -> Tuple[str, bool]:
    lowered = name.lower()
    for suffix in _RASTER_SIDECARS:
        if lowered.endswith(suffix):
            base = name[: -len(suffix)]
            if PurePosixPath(base).suffix.lower() in _RASTER_EXTS:
                return base, True
    return name, False


def classify_object(relative_path: str, sibling_stems: Optional[Set[str]] = None) -> str:
    """
    Classify a resource-relative object path into a component.

    Rules are path heuristics tuned to the EnDMC deliveries: terrain and
    land-cover folders win over output-raster name tokens, and raster
    sidecars (``.aux.xml``, ``.ovr``, ``.tfw``, ``.tif.xml``) follow their
    raster. Review ``other`` rows before relying on a component filter for
    completeness.
    """
    path = PurePosixPath(relative_path)
    name = path.name
    lowered = name.lower()
    dirs = "/".join(path.parts[:-1])
    if not name or relative_path.endswith("/"):
        return "metadata"
    if lowered in {"file_listing.json", ".endmc_public"}:
        return "metadata"

    base, _ = _strip_sidecar(name)
    base_lower = base.lower()
    suffix = PurePosixPath(base_lower).suffix

    if re.search(r"\.g\d{2}\.hdf$", base_lower):
        return "ras_run_artifact" if re.search(r"(^|/)backups?(/|$)", dirs, re.IGNORECASE) else "geometry_hdf"
    if re.search(r"\.p\d{2}\.hdf$", base_lower):
        return "plan_hdf"
    if re.search(r"\.u\d{2}\.hdf$", base_lower):
        return "ras_project"
    if _RAS_RUN_RE.search(base_lower):
        return "ras_run_artifact"
    if re.search(r"(^|/)backups?(/|$)", dirs, re.IGNORECASE) and _RAS_TEXT_RE.search(base_lower):
        return "ras_run_artifact"

    in_terrain = bool(_TERRAIN_DIR_RE.search(dirs))
    in_land = bool(_LAND_DIR_RE.search(dirs))
    in_infiltration = bool(_INFILTRATION_RE.search(dirs))

    if suffix == ".hdf":
        # RAS Mapper map-layer sidecars named for their content.
        if _INFILTRATION_RE.search(base) or (in_infiltration and not in_terrain):
            return "infiltration"
        if _LAND_DIR_RE.search(base) or re.search(r"landcover|impervious", base, re.IGNORECASE):
            return "land_cover"
    if suffix in _RASTER_EXTS or (suffix == ".hdf" and (in_terrain or in_land)):
        if in_terrain:
            return "terrain"
        if in_land:
            return "land_cover"
        if in_infiltration:
            return "infiltration"
        product_text = f"{dirs}/{base}"
        if _DEPTH_RE.search(product_text):
            return "output_depth"
        if _WSE_RE.search(product_text):
            return "output_wse"
        if _VELOCITY_RE.search(product_text):
            return "output_velocity"
        if _TERRAIN_DIR_RE.search(base):
            return "terrain"
        if _LAND_DIR_RE.search(base):
            return "land_cover"
        if _OUTPUT_DIR_RE.search(dirs):
            return "output_raster_other"
        return "gis" if suffix != ".hdf" else "other"

    if suffix == ".prj":
        stem = str(PurePosixPath(relative_path).with_suffix("")).casefold()
        if (sibling_stems and stem in sibling_stems) or "projection" in relative_path.lower():
            return "gis"
        return "ras_project"
    if _RAS_TEXT_RE.search(base_lower):
        return "ras_project"
    if suffix == ".dss":
        return "dss"
    if suffix in _HMS_EXTS:
        return "hms"
    if suffix in _GIS_EXTS or (suffix == ".xml" and PurePosixPath(base_lower[:-4]).suffix in _GIS_EXTS):
        return "gis"
    if suffix in _DOC_EXTS:
        return "docs"
    if suffix in {".hdf", ".h5"}:
        return "other"
    return "other"


# ----------------------------------------------------------------------
# Download helpers
# ----------------------------------------------------------------------


def safe_destination(root: Path, relative_path: str) -> Path:
    """Map an untrusted object path below ``root`` or raise ``ValueError``."""
    parts = relative_path.split("/")
    if not relative_path or relative_path.startswith("/") or any(
        p in {"", ".", ".."} for p in parts
    ):
        raise ValueError(f"Unsafe object path: {relative_path!r}")
    for part in parts:
        if any(ch in _WINDOWS_INVALID or ord(ch) < 32 for ch in part) or part.endswith((" ", ".")):
            raise ValueError(f"Object path is not representable on Windows: {relative_path!r}")
    target = root.joinpath(*parts)
    if root != target and root not in target.parents:
        raise ValueError(f"Object path escapes destination: {relative_path!r}")
    return target


def _io_path(path: Union[str, Path]) -> str:
    """Return a Windows extended-length spelling for file I/O."""
    text = str(Path(path).absolute())
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text.lstrip("\\")
    return "\\\\?\\" + text


def _existing_size(path: Path) -> Optional[int]:
    try:
        return os.stat(_io_path(path)).st_size
    except OSError:
        return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    os.makedirs(_io_path(path.parent), exist_ok=True)
    temporary = path.with_name(f".w-{uuid.uuid4().hex[:8]}.tmp")
    with open(_io_path(temporary), "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n")
    os.replace(_io_path(temporary), _io_path(path))


def _require_awscrt():
    try:
        from awscrt import checksums  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "verify='crc64nvme' requires the optional 'awscrt' package: pip install awscrt"
        ) from exc
    return checksums


def crc64nvme_file(path: Union[str, Path], block_size: int = 8 * 1024 * 1024) -> str:
    """Return the base64 CRC64NVME of a file, matching S3's checksum header."""
    checksums = _require_awscrt()
    crc = 0
    with open(_io_path(path), "rb") as stream:
        while True:
            block = stream.read(block_size)
            if not block:
                break
            crc = checksums.crc64nvme(block, crc)
    return base64.b64encode(crc.to_bytes(8, "big")).decode("ascii")


@dataclass
class _FileJob:
    key: str
    target: Path
    size: int
    etag: str
    result: Dict[str, Any]
    chunks: List[Tuple[int, int]] = field(default_factory=list)
    done: Set[int] = field(default_factory=set)
    remaining: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    failed: bool = False

    @property
    def part(self) -> Path:
        return self.target.with_name(self.target.name + _PARTIAL_SUFFIX)

    @property
    def state(self) -> Path:
        return self.target.with_name(self.target.name + _STATE_SUFFIX)


def _prepare_job(job: _FileJob, chunk_size: int) -> None:
    os.makedirs(_io_path(job.target.parent), exist_ok=True)
    if job.size <= chunk_size:
        job.chunks = [(0, max(job.size - 1, 0))]
        job.done = set()
    else:
        job.chunks = [
            (start, min(start + chunk_size, job.size) - 1)
            for start in range(0, job.size, chunk_size)
        ]
        state: Dict[str, Any] = {}
        try:
            with open(_io_path(job.state), encoding="utf-8") as stream:
                state = json.load(stream)
        except (OSError, ValueError):
            state = {}
        resumable = (
            state.get("etag") == job.etag
            and state.get("size") == job.size
            and state.get("chunk_size") == chunk_size
            and _existing_size(job.part) == job.size
        )
        job.done = set(state.get("done", [])) if resumable else set()
        if not resumable:
            with open(_io_path(job.part), "wb") as stream:
                stream.truncate(job.size)
        elif job.done:
            logger.info("Resuming %s (%d/%d ranges complete)", job.target.name, len(job.done), len(job.chunks))
    job.remaining = len(job.chunks) - len(job.done)


def _fetch_range(job: _FileJob, index: int, timeout: float) -> None:
    start, end = job.chunks[index]
    url = LouisianaEndmc.object_url(job.key)
    single = len(job.chunks) == 1
    headers = {"User-Agent": USER_AGENT}
    if job.etag:
        headers["If-Match"] = f'"{job.etag}"'
    if not single:
        headers["Range"] = f"bytes={start}-{end}"
    last_error: Optional[Exception] = None
    for attempt in range(4):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout) as response:
                if response.status_code == 412:
                    raise RuntimeError("object changed on the server (ETag mismatch); rerun to restart")
                response.raise_for_status()
                if not single and response.status_code != 206:
                    raise RuntimeError("server ignored the byte range")
                if single:
                    with open(_io_path(job.part), "wb") as stream:
                        for block in response.iter_content(1024 * 1024):
                            stream.write(block)
                    written = _existing_size(job.part)
                    if written != job.size:
                        raise IOError(f"received {written} of {job.size} bytes")
                else:
                    expected = end - start + 1
                    received = 0
                    with open(_io_path(job.part), "r+b") as stream:
                        stream.seek(start)
                        for block in response.iter_content(1024 * 1024):
                            stream.write(block)
                            received += len(block)
                    if received != expected:
                        raise IOError(f"range {start}-{end}: received {received} of {expected} bytes")
            return
        except RuntimeError:
            raise
        except (requests.RequestException, IOError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500:
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"{job.key}: {last_error}")


def _finalize(job: _FileJob, verify: str, timeout: float) -> None:
    size = _existing_size(job.part)
    if size != job.size:
        raise IOError(f"size mismatch: local {size}, listed {job.size}")
    verified = "size"
    if verify == "crc64nvme":
        head = requests.head(
            LouisianaEndmc.object_url(job.key),
            headers={"x-amz-checksum-mode": "ENABLED", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
        head.raise_for_status()
        expected = head.headers.get("x-amz-checksum-crc64nvme")
        if expected:
            actual = crc64nvme_file(job.part)
            if actual != expected:
                raise IOError(f"CRC64NVME mismatch: local {actual}, S3 {expected}")
            job.result["crc64nvme"] = expected
            verified = "crc64nvme"
        else:
            logger.warning("%s: S3 returned no CRC64NVME; verified by size only", job.key)
    os.replace(_io_path(job.part), _io_path(job.target))
    try:
        os.remove(_io_path(job.state))
    except OSError:
        pass
    job.result["status"] = "downloaded"
    job.result["verified"] = verified


def _run_jobs(
    jobs: List[_FileJob], max_workers: int, chunk_size: int, verify: str, timeout: float
) -> None:
    tasks: List[Tuple[_FileJob, int]] = []
    for job in jobs:
        try:
            _prepare_job(job, chunk_size)
        except OSError as exc:
            job.failed = True
            job.result.update({"status": "failed", "error": str(exc)})
            continue
        if job.remaining == 0:
            _safe_finalize(job, verify, timeout)
            continue
        tasks.extend((job, i) for i in range(len(job.chunks)) if i not in job.done)

    def work(job: _FileJob, index: int) -> None:
        if job.failed:
            return
        try:
            _fetch_range(job, index, timeout)
        except Exception as exc:  # recorded per file; other files continue
            with job.lock:
                job.failed = True
                job.result.update({"status": "failed", "error": str(exc)})
            return
        with job.lock:
            job.done.add(index)
            job.remaining -= 1
            finished = job.remaining == 0
            if len(job.chunks) > 1 and not finished:
                _atomic_write_json(
                    job.state,
                    {"etag": job.etag, "size": job.size, "chunk_size": chunk_size, "done": sorted(job.done)},
                )
        if finished:
            _safe_finalize(job, verify, timeout)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="endmc") as pool:
        futures = [pool.submit(work, job, index) for job, index in tasks]
        for future in as_completed(futures):
            future.result()


def _safe_finalize(job: _FileJob, verify: str, timeout: float) -> None:
    try:
        _finalize(job, verify, timeout)
    except Exception as exc:
        job.failed = True
        job.result.update({"status": "failed", "error": str(exc)})


def _write_receipt(
    root: Path,
    resource_id: str,
    kind: str,
    results: List[Dict[str, Any]],
    components: Optional[Sequence[str]],
    patterns: Optional[Sequence[str]],
    verify: str,
) -> Path:
    path = root / f"_endmc_{resource_id}.json"
    previous: Dict[str, Any] = {}
    try:
        with open(_io_path(path), encoding="utf-8") as stream:
            previous = json.load(stream)
    except (OSError, ValueError):
        previous = {}
    files = dict(previous.get("files", {}))
    for result in results:
        entry = {
            k: result.get(k)
            for k in ("key", "component", "size", "etag", "last_modified", "status", "verified", "error", "crc64nvme")
            if result.get(k) is not None
        }
        files[result["relative_path"]] = entry
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "schema": _RECEIPT_SCHEMA,
        "resource_id": resource_id,
        "kind": kind,
        "bucket": BUCKET,
        "s3_prefix": _resource_prefix(kind, resource_id),
        "resource_url": f"{ENDMC_BASE_URL}/view/{kind}/{resource_id}",
        "created": previous.get("created", now),
        "updated": now,
        "last_selection": {
            "components": list(components) if components else None,
            "patterns": list(patterns) if patterns else None,
            "verify": verify,
        },
        "files": files,
    }
    _atomic_write_json(path, payload)
    return path


__all__ = [
    "COMPONENTS",
    "LouisianaEndmc",
    "OUTPUT_RASTER_COMPONENTS",
    "classify_object",
    "crc64nvme_file",
    "derive_region",
    "filter_objects",
    "objects_dataframe",
    "parse_list_objects",
    "parse_resource_page",
    "parse_search_payload",
    "safe_destination",
]
