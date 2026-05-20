"""
USGS ScienceBase Calibrated HEC-RAS Models

Download and organize publicly available calibrated HEC-RAS models from
USGS ScienceBase for use as example datasets in ras-commander calibration
workflows, validation notebooks, and the USGS metrics module.

Models:
- Kalamazoo River, MI (2D, HEC-RAS 6.6, CC0-1.0) - DOI: 10.5066/P13CPA5B
- St. Joseph River, IN (1D steady, HEC-RAS 4.10) - DOI: 10.5066/F7QZ2836

Generated: 2025-05-05
"""

from pathlib import Path
from typing import Optional, Dict, List, Set, Any
import hashlib
import json
import logging
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone

import requests
from tqdm.auto import tqdm

from ras_commander.Decorators import log_call

logger = logging.getLogger(__name__)

SCIENCEBASE_CATALOG_URL = "https://www.sciencebase.gov/catalog"

_SB_MAX_PER_PAGE = 100
_SB_DEFAULT_FIELDS = (
    "title,id,hasChildren,files,parentId,tags,summary,"
    "identifiers,spatial,dates,contacts,provenance"
)
_SB_REQUEST_DELAY = 0.6
_FIM_SITES_URL = (
    "https://fim.wim.usgs.gov/server/rest/services/"
    "FIMMapper/sites/MapServer/0/query"
)

_RAS_EXTENSIONS = frozenset({
    ".prj", ".g01", ".g02", ".g03", ".g04", ".g05",
    ".p01", ".p02", ".p03", ".p04", ".p05",
    ".f01", ".f02", ".u01", ".u02", ".hdf",
    ".rasmap", ".dss",
})
_HMS_EXTENSIONS = frozenset({
    ".hms", ".basin", ".met", ".gage", ".grid", ".dss",
})
_MODEL_ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".tar.gz"})


class UsgsScienceBase:
    """
    Download and organize USGS ScienceBase calibrated HEC-RAS models.

    Implements the ModelSource protocol for catalog integration while
    maintaining backward compatibility with the original slug-based API.

    Example:
        >>> from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase
        >>> from pathlib import Path
        >>>
        >>> # Download Kalamazoo River model
        >>> model_dir = UsgsScienceBase.download_kalamazoo(Path("H:/Testing/USGS Sciencebase Models"))
        >>>
        >>> # Use with ras-commander
        >>> from ras_commander import init_ras_project
        >>> ras = init_ras_project(model_dir / "hec_ras_model", ras_version="6.6")
    """

    SOURCE_NAME = "USGS ScienceBase"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    @property
    def source_type(self) -> str:
        return "federal"

    @staticmethod
    def get_source_status():
        """Check if ScienceBase API is reachable."""
        from ras_commander.sources.base import SourceStatus
        try:
            resp = requests.get(
                f"{SCIENCEBASE_CATALOG_URL}/item/4f4e4760e4b07f02db47df9c",
                params={"format": "json", "fields": "title"},
                timeout=15,
            )
            resp.raise_for_status()
            return SourceStatus.AVAILABLE
        except Exception:
            return SourceStatus.UNAVAILABLE

    @staticmethod
    def list_catalog_models(**kwargs):
        """Return ModelMetadata list for catalog integration."""
        from ras_commander.sources.base import ModelMetadata, ModelType
        results = []
        _type_map = {
            "2D unsteady": ModelType.UNSTEADY_2D,
            "1D steady": ModelType.STEADY_1D,
            "1D unsteady": ModelType.UNSTEADY_1D,
        }
        for slug, info in UsgsScienceBase._MODEL_REGISTRY.items():
            mt = _type_map.get(info.get("model_type", ""), ModelType.UNKNOWN)
            results.append(ModelMetadata(
                source_name="USGS ScienceBase",
                source_id=slug,
                name=info["name"],
                description=info.get("notes", ""),
                location=info["name"],
                model_type=mt,
                hecras_version=info.get("ras_version"),
                doi=info.get("doi"),
                url=f"{SCIENCEBASE_CATALOG_URL}/item/{info['sciencebase_id']}",
                tags=["USGS", "ScienceBase", "calibrated"],
            ))
        return results

    _MODEL_REGISTRY = {
        "kalamazoo": {
            "name": "Kalamazoo River, MI",
            "sciencebase_id": "67a38201d34ee33d441d2f22",
            "doi": "10.5066/P13CPA5B",
            "ras_version": "6.6",
            "model_type": "2D unsteady",
            "license": "CC0-1.0",
            "crs": "EPSG:6499",
            "calibration_data": True,
            "hdf_results": True,
            "dss_file": True,
            "files": {
                "hec_ras_model.zip": {"size_mb": 2977, "required": True},
                "calibration_data.zip": {"size_mb": 38, "required": True},
                "quasi_steady_raster_outputs.zip": {"size_mb": 317, "required": False},
                "miscellaneous.zip": {"size_mb": 27, "required": False},
                "substrate.zip": {"size_mb": 0.02, "required": False},
                "readme.md": {"size_mb": 0.01, "required": True},
            },
            "project_file": "hec_ras_model/kalamazoo_trowbridg.prj",
            "notes": (
                "2D hydraulic model of Kalamazoo River between Trowbridge Dam "
                "and Allegan City Dam. 21 plans with HDF outputs, dedicated "
                "calibration_data/ with ADCP velocity and WSE measurements from "
                "June 2024 and April 2025 campaigns. 602 MB DSS file included."
            ),
        },
        "st-joseph": {
            "name": "St. Joseph River, Elkhart, IN",
            "sciencebase_id": "584197dfe4b04fc80e518b6b",
            "doi": "10.5066/F7QZ2836",
            "ras_version": "4.10",
            "model_type": "1D steady",
            "license": "USGS federal data release",
            "crs": None,
            "calibration_data": True,
            "hdf_results": False,
            "dss_file": False,
            "files": {
                "model.zip": {"size_mb": 5, "required": True},
                "calibration_table_4_from_report.xlsx": {"size_mb": 0.04, "required": True},
                "model_output_table.csv": {"size_mb": 0.05, "required": True},
                "field_data.zip": {"size_mb": 129, "required": False},
                "dem_clip.zip": {"size_mb": 26, "required": False},
                "modelversion.docx": {"size_mb": 0.14, "required": False},
                "README_Contents_Directory.docx": {"size_mb": 0.01, "required": False},
            },
            "project_file": "model/model/St_Joe_Elkhart_FIM.prj",
            "notes": (
                "1D steady-state flood inundation model for 6.6-mile reach. "
                "24 plans (only p24 in archive), calibrated to USGS 04101000. "
                "Excel calibration table + CSV model output for easy comparison."
            ),
        },
    }

    _MODEL_ALIASES = {
        "kalamazoo": "kalamazoo",
        "kalamazoo-river": "kalamazoo",
        "kzoo": "kalamazoo",
        "trowbridge": "kalamazoo",
        "P13CPA5B": "kalamazoo",
        "st-joseph": "st-joseph",
        "st-joseph-river": "st-joseph",
        "stjoseph": "st-joseph",
        "elkhart": "st-joseph",
        "F7QZ2836": "st-joseph",
    }

    @staticmethod
    def normalize_model_key(model_key: str) -> str:
        """Return the canonical model slug for a name or alias."""
        key = str(model_key).strip().lower().replace("_", "-").replace(" ", "-")
        normalized = UsgsScienceBase._MODEL_ALIASES.get(key)
        if normalized is None:
            valid = ", ".join(sorted(UsgsScienceBase._MODEL_REGISTRY))
            raise ValueError(
                f"Unknown ScienceBase model '{model_key}'. Known models: {valid}"
            )
        return normalized

    @staticmethod
    def get_model_info(model_key: str) -> dict:
        """Return registry metadata for a model."""
        slug = UsgsScienceBase.normalize_model_key(model_key)
        return UsgsScienceBase._MODEL_REGISTRY[slug].copy()

    @staticmethod
    def list_models() -> list[str]:
        """Return list of available model slugs."""
        return list(UsgsScienceBase._MODEL_REGISTRY.keys())

    @staticmethod
    def _download_file(url: str, dest: Path, desc: str = "") -> Path:
        """Download a file with progress bar."""
        resp = requests.get(url, stream=True)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=desc or dest.name,
            mininterval=2.0,
        ) as pbar:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                pbar.update(len(chunk))
        return dest

    @staticmethod
    def _get_file_url(sciencebase_id: str, filename: str) -> str:
        """Build the ScienceBase catalog file download URL."""
        return f"{SCIENCEBASE_CATALOG_URL}/file/get/{sciencebase_id}?name={filename}"

    @staticmethod
    @log_call
    def download_model(
        model_key: str,
        output_dir: Path,
        required_only: bool = False,
        extract: bool = True,
    ) -> Path:
        """
        Download a USGS ScienceBase model to output_dir.

        Args:
            model_key: Model slug, alias, or DOI suffix
            output_dir: Parent directory for the model folder
            required_only: If True, skip optional files (rasters, field data, DEM)
            extract: If True, extract ZIP files after download

        Returns:
            Path to the model directory
        """
        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        sb_id = info["sciencebase_id"]

        model_dir = Path(output_dir) / slug
        model_dir.mkdir(parents=True, exist_ok=True)

        for filename, file_info in info["files"].items():
            if required_only and not file_info["required"]:
                logger.debug(f"Skipping optional file: {filename}")
                continue

            dest = model_dir / filename
            if dest.exists() and dest.stat().st_size > 1000:
                logger.debug(f"Already downloaded: {filename}")
                continue

            url = UsgsScienceBase._get_file_url(sb_id, filename)
            logger.debug(f"Downloading {filename} ({file_info['size_mb']} MB)...")
            UsgsScienceBase._download_file(url, dest, desc=filename)

        if extract:
            for filename in info["files"]:
                if filename.endswith(".zip"):
                    zip_path = model_dir / filename
                    if zip_path.exists():
                        extract_dir = model_dir / filename.replace(".zip", "")
                        if not extract_dir.exists():
                            logger.debug(f"Extracting {filename}...")
                            zipfile.ZipFile(zip_path).extractall(model_dir)

        return model_dir

    @staticmethod
    def get_project_path(model_key: str, base_dir: Path) -> Path:
        """Return the path to the .prj file for a downloaded model."""
        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        return Path(base_dir) / slug / info["project_file"]

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sb_request(
        url: str,
        params: Optional[dict] = None,
        request_delay: float = _SB_REQUEST_DELAY,
        max_retries: int = 3,
    ) -> Optional[dict]:
        """Make a ScienceBase API request with retry and rate limiting."""
        for attempt in range(max_retries):
            try:
                time.sleep(request_delay)
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = min(60, request_delay * (2 ** (attempt + 1)))
                    logger.warning("Rate limited by ScienceBase, waiting %.0fs", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code >= 500:
                    logger.warning("ScienceBase server error %s, retry %d/%d",
                                   exc.response.status_code, attempt + 1, max_retries)
                    time.sleep(request_delay * 2)
                    continue
                logger.error("ScienceBase request failed: %s", exc)
                return None
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                logger.warning("ScienceBase connection issue (%s), retry %d/%d",
                               type(exc).__name__, attempt + 1, max_retries)
                time.sleep(request_delay * 2)
                continue
        logger.error("ScienceBase request failed after %d retries: %s", max_retries, url)
        return None

    @staticmethod
    def _search_sciencebase(
        query: str,
        max_results: int = 500,
        fields: str = _SB_DEFAULT_FIELDS,
        request_delay: float = _SB_REQUEST_DELAY,
    ) -> List[dict]:
        """Paginated search of ScienceBase catalog. Returns raw item dicts."""
        all_items: List[dict] = []
        start = 0
        total = None
        while True:
            params = {
                "q": query,
                "max": _SB_MAX_PER_PAGE,
                "start": start,
                "fields": fields,
                "format": "json",
            }
            data = UsgsScienceBase._sb_request(
                f"{SCIENCEBASE_CATALOG_URL}/items",
                params=params,
                request_delay=request_delay,
            )
            if data is None:
                break
            items = data.get("items", [])
            if not items:
                break
            if total is None:
                total = data.get("total", 0)
            all_items.extend(items)
            start += len(items)
            if start >= min(max_results, total or start + 1):
                break
        return all_items

    @staticmethod
    def _get_item_detail(
        item_id: str,
        request_delay: float = _SB_REQUEST_DELAY,
    ) -> Optional[dict]:
        """Fetch full metadata for a single ScienceBase item."""
        return UsgsScienceBase._sb_request(
            f"{SCIENCEBASE_CATALOG_URL}/item/{item_id}",
            params={"format": "json"},
            request_delay=request_delay,
        )

    @staticmethod
    def _detect_model_files(
        files: List[dict],
    ) -> tuple:
        """Detect HEC-RAS/HMS files from a ScienceBase file list.

        Returns (ras_files, hms_files, model_type_guess).
        """
        ras_files: List[str] = []
        hms_files: List[str] = []
        for f in files:
            name = f.get("name", "")
            suffix = Path(name).suffix.lower()
            if suffix in _RAS_EXTENSIONS:
                ras_files.append(name)
            if suffix in _HMS_EXTENSIONS:
                hms_files.append(name)
            if suffix in _MODEL_ARCHIVE_EXTENSIONS:
                lower = name.lower()
                if any(kw in lower for kw in ("ras", "hydraulic", "model", "hec")):
                    ras_files.append(name)
                if "hms" in lower:
                    hms_files.append(name)
        if ras_files and hms_files:
            guess = "HEC-RAS+HMS"
        elif ras_files:
            guess = "HEC-RAS"
        elif hms_files:
            guess = "HEC-HMS"
        else:
            guess = "unknown"
        return ras_files, hms_files, guess

    @staticmethod
    def _extract_version(text: str) -> Optional[str]:
        """Try to extract a HEC-RAS or HEC-HMS version from text."""
        m = re.search(r"HEC-RAS\s+(?:version\s+)?(\d+\.?\d*\.?\d*)", text, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"HEC-HMS\s+(?:version\s+)?(\d+\.?\d*\.?\d*)", text, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_doi(item: dict) -> Optional[str]:
        """Extract DOI from ScienceBase item identifiers."""
        for ident in item.get("identifiers", []):
            if ident.get("type", "").upper() == "DOI":
                return ident.get("key")
            scheme = ident.get("scheme", "")
            if "doi" in scheme.lower():
                return ident.get("key")
        return None

    @staticmethod
    def _extract_state(item: dict) -> Optional[str]:
        """Extract US state from spatial or tags."""
        for tag in item.get("tags", []):
            if tag.get("type") == "Place":
                return tag.get("name")
        spatial = item.get("spatial", {})
        rep_point = spatial.get("representativePoint")
        if rep_point:
            return f"{rep_point.get('latitude', '')},{rep_point.get('longitude', '')}"
        return None

    @staticmethod
    def _classify_sciencebase_item(
        item: dict,
        discovery_source: str,
        discovery_query: str,
        fim_site_no: Optional[str] = None,
    ) -> dict:
        """Transform a raw ScienceBase item into a candidate model dict."""
        files = item.get("files", []) or []
        ras_files, hms_files, model_type = UsgsScienceBase._detect_model_files(files)

        title = item.get("title", "")
        summary = item.get("summary", "")
        combined_text = f"{title} {summary}"
        version = UsgsScienceBase._extract_version(combined_text)

        total_size = sum(f.get("size", 0) for f in files) / (1024 * 1024)

        has_prj = any(Path(f.get("name", "")).suffix.lower() == ".prj" for f in files)
        has_geo = any(Path(f.get("name", "")).suffix.lower().startswith(".g0") for f in files)
        title_mentions_model = bool(re.search(
            r"HEC-RAS|HEC-HMS|hydraulic model|flood.inundation.*model",
            title, re.IGNORECASE
        ))

        if has_prj or has_geo:
            confidence = "high"
        elif ras_files or hms_files or title_mentions_model:
            confidence = "medium"
        else:
            confidence = "low"

        tags = [t.get("name", "") for t in item.get("tags", []) if t.get("name")]

        sb_id = item.get("id", "")
        candidate = {
            "sciencebase_id": sb_id,
            "title": title,
            "url": f"{SCIENCEBASE_CATALOG_URL}/item/{sb_id}",
            "doi": UsgsScienceBase._extract_doi(item),
            "discovery_source": discovery_source,
            "discovery_query": discovery_query,
            "has_children": item.get("hasChildren", False),
            "parent_id": item.get("parentId"),
            "files": [{"name": f.get("name"), "size": f.get("size", 0),
                        "content_type": f.get("contentType")}
                       for f in files],
            "ras_files_detected": ras_files,
            "hms_files_detected": hms_files,
            "model_type_guess": model_type,
            "ras_version_guess": version,
            "state": UsgsScienceBase._extract_state(item),
            "tags": tags,
            "total_size_mb": round(total_size, 2),
            "confidence": confidence,
        }
        if fim_site_no:
            candidate["fim_site_no"] = fim_site_no
        return candidate

    # ------------------------------------------------------------------
    # Discovery cache
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key_hash(key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()[:12]

    @staticmethod
    def _load_cache(cache_dir: Path, cache_key: str) -> Optional[Any]:
        if cache_dir is None:
            return None
        path = cache_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("payload")
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _save_cache(cache_dir: Path, cache_key: str, payload: Any) -> None:
        if cache_dir is None:
            return
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{cache_key}.json"
        data = {
            "_cached_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ------------------------------------------------------------------
    # Strategy 1: Paginated keyword search (CLB-547)
    # ------------------------------------------------------------------

    _DEFAULT_KEYWORD_QUERIES = [
        '"HEC-RAS"',
        '"HEC-RAS" model',
        '"hydraulic model" "HEC-RAS"',
    ]

    @staticmethod
    def _discover_keyword_search(
        queries: Optional[List[str]] = None,
        max_results_per_query: int = 500,
        cache_dir: Optional[Path] = None,
        request_delay: float = _SB_REQUEST_DELAY,
        seen_ids: Optional[Set[str]] = None,
    ) -> Dict[str, dict]:
        """Search ScienceBase with paginated keyword queries."""
        if queries is None:
            queries = UsgsScienceBase._DEFAULT_KEYWORD_QUERIES
        if seen_ids is None:
            seen_ids = set()
        results: Dict[str, dict] = {}

        for query in tqdm(queries, desc="Keyword search", unit="query"):
            cache_key = f"search_{UsgsScienceBase._cache_key_hash(query)}"
            cached = UsgsScienceBase._load_cache(cache_dir, cache_key) if cache_dir else None
            if cached is not None:
                items = cached
            else:
                items = UsgsScienceBase._search_sciencebase(
                    query, max_results=max_results_per_query,
                    request_delay=request_delay,
                )
                UsgsScienceBase._save_cache(cache_dir, cache_key, items)

            for item in items:
                sb_id = item.get("id", "")
                if sb_id in seen_ids or sb_id in results:
                    continue
                candidate = UsgsScienceBase._classify_sciencebase_item(
                    item, discovery_source="keyword", discovery_query=query,
                )
                results[sb_id] = candidate
                seen_ids.add(sb_id)

        return results

    # ------------------------------------------------------------------
    # Strategy 2: FIM program crawler (CLB-546)
    # ------------------------------------------------------------------

    @staticmethod
    def _query_fim_sites(
        request_delay: float = _SB_REQUEST_DELAY,
    ) -> List[dict]:
        """Query the USGS Flood Inundation Mapping ArcGIS REST endpoint."""
        sites: List[dict] = []
        offset = 0
        page_size = 50
        while True:
            params = {
                "where": "1=1",
                "outFields": "SITE_NO,COMMUNITY,STATE,DATA_LINK,SHORT_NAME",
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json",
            }
            data = UsgsScienceBase._sb_request(
                _FIM_SITES_URL, params=params, request_delay=request_delay,
            )
            if data is None:
                break
            features = data.get("features", [])
            if not features:
                break
            for feat in features:
                attrs = feat.get("attributes", {})
                sites.append({
                    "site_no": str(attrs.get("SITE_NO", "")),
                    "community": attrs.get("COMMUNITY", ""),
                    "state": attrs.get("STATE", ""),
                    "data_link": attrs.get("DATA_LINK", ""),
                    "short_name": attrs.get("SHORT_NAME", ""),
                })
            if len(features) < page_size:
                break
            offset += page_size
        return sites

    @staticmethod
    def _discover_fim_sites(
        cache_dir: Optional[Path] = None,
        request_delay: float = _SB_REQUEST_DELAY,
        seen_ids: Optional[Set[str]] = None,
    ) -> Dict[str, dict]:
        """Cross-reference FIM sites with ScienceBase to find model archives."""
        if seen_ids is None:
            seen_ids = set()
        results: Dict[str, dict] = {}

        cached_sites = UsgsScienceBase._load_cache(cache_dir, "fim_sites") if cache_dir else None
        if cached_sites is not None:
            fim_sites = cached_sites
        else:
            fim_sites = UsgsScienceBase._query_fim_sites(request_delay=request_delay)
            UsgsScienceBase._save_cache(cache_dir, "fim_sites", fim_sites)

        if not fim_sites:
            logger.warning("No FIM sites retrieved")
            return results

        by_state: Dict[str, List[dict]] = {}
        for site in fim_sites:
            st = site.get("state", "unknown")
            by_state.setdefault(st, []).append(site)

        for state, state_sites in tqdm(by_state.items(), desc="FIM cross-ref", unit="state"):
            cache_key = f"fim_state_{UsgsScienceBase._cache_key_hash(state)}"
            cached = UsgsScienceBase._load_cache(cache_dir, cache_key) if cache_dir else None
            if cached is not None:
                items = cached
            else:
                query = f'"flood-inundation" "{state}"'
                items = UsgsScienceBase._search_sciencebase(
                    query, max_results=200, request_delay=request_delay,
                )
                UsgsScienceBase._save_cache(cache_dir, cache_key, items)

            site_numbers = {s["site_no"] for s in state_sites if s.get("site_no")}
            community_names = {s["community"].lower() for s in state_sites if s.get("community")}

            for item in items:
                sb_id = item.get("id", "")
                if sb_id in seen_ids or sb_id in results:
                    continue
                title_lower = item.get("title", "").lower()
                summary_lower = item.get("summary", "").lower()
                combined = f"{title_lower} {summary_lower}"
                matched_site = None
                for sno in site_numbers:
                    if sno in combined:
                        matched_site = sno
                        break
                if matched_site is None:
                    for cname in community_names:
                        if cname and cname in combined:
                            for s in state_sites:
                                if s["community"].lower() == cname:
                                    matched_site = s["site_no"]
                                    break
                            break

                candidate = UsgsScienceBase._classify_sciencebase_item(
                    item, discovery_source="fim",
                    discovery_query=f"FIM {state}",
                    fim_site_no=matched_site,
                )
                results[sb_id] = candidate
                seen_ids.add(sb_id)

        return results

    # ------------------------------------------------------------------
    # Strategy 3: Alternate keyword search (CLB-549)
    # ------------------------------------------------------------------

    _ALTERNATE_KEYWORD_QUERIES = [
        '"hydraulic model archive"',
        '"flood-inundation study"',
        '"streamflow simulation" model',
        '"dam breach" "HEC-RAS"',
        '"sediment transport" "HEC-RAS"',
        '"HEC-HMS"',
        '"HEC-HMS" "HEC-RAS"',
        '"step-backwater"',
        '"rain on grid" "HEC-RAS"',
        '"levee breach" model',
    ]

    @staticmethod
    def _discover_alternate_keywords(
        max_results_per_query: int = 500,
        cache_dir: Optional[Path] = None,
        request_delay: float = _SB_REQUEST_DELAY,
        seen_ids: Optional[Set[str]] = None,
    ) -> Dict[str, dict]:
        """Search ScienceBase with alternate/expanded keyword queries."""
        return UsgsScienceBase._discover_keyword_search(
            queries=UsgsScienceBase._ALTERNATE_KEYWORD_QUERIES,
            max_results_per_query=max_results_per_query,
            cache_dir=cache_dir,
            request_delay=request_delay,
            seen_ids=seen_ids,
        )

    # ------------------------------------------------------------------
    # Strategy 4: Child item traversal (CLB-548)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_item_children(
        parent_id: str,
        request_delay: float = _SB_REQUEST_DELAY,
        max_depth: int = 2,
        _current_depth: int = 0,
    ) -> List[dict]:
        """Recursively fetch child items of a ScienceBase parent."""
        if _current_depth >= max_depth:
            return []
        params = {
            "parentId": parent_id,
            "max": _SB_MAX_PER_PAGE,
            "fields": _SB_DEFAULT_FIELDS,
            "format": "json",
        }
        data = UsgsScienceBase._sb_request(
            f"{SCIENCEBASE_CATALOG_URL}/items",
            params=params,
            request_delay=request_delay,
        )
        if data is None:
            return []
        children = data.get("items", [])
        all_children = list(children)
        for child in children:
            if child.get("hasChildren"):
                grandchildren = UsgsScienceBase._get_item_children(
                    child["id"],
                    request_delay=request_delay,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                all_children.extend(grandchildren)
        return all_children

    @staticmethod
    def _discover_children(
        parent_candidates: Dict[str, dict],
        cache_dir: Optional[Path] = None,
        request_delay: float = _SB_REQUEST_DELAY,
        seen_ids: Optional[Set[str]] = None,
    ) -> Dict[str, dict]:
        """For items with children, traverse child items for model files."""
        if seen_ids is None:
            seen_ids = set()
        results: Dict[str, dict] = {}

        parents_with_children = {
            k: v for k, v in parent_candidates.items()
            if v.get("has_children")
        }
        if not parents_with_children:
            return results

        for sb_id, parent in tqdm(parents_with_children.items(),
                                   desc="Child traversal", unit="parent"):
            cache_key = f"children_{sb_id[:12]}"
            cached = UsgsScienceBase._load_cache(cache_dir, cache_key) if cache_dir else None
            if cached is not None:
                children = cached
            else:
                children = UsgsScienceBase._get_item_children(
                    sb_id, request_delay=request_delay,
                )
                UsgsScienceBase._save_cache(cache_dir, cache_key, children)

            for child in children:
                child_id = child.get("id", "")
                if child_id in seen_ids or child_id in results:
                    continue
                candidate = UsgsScienceBase._classify_sciencebase_item(
                    child,
                    discovery_source="children",
                    discovery_query=f"child of {parent.get('title', sb_id)[:60]}",
                )
                if candidate["model_type_guess"] != "unknown":
                    results[child_id] = candidate
                    seen_ids.add(child_id)

        return results

    # ------------------------------------------------------------------
    # Version filter
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_version_tuple(version_str: str) -> tuple:
        """Parse '6.0' or '4.3.1' into a comparable tuple of ints."""
        parts = []
        for p in version_str.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                break
        return tuple(parts) if parts else (0,)

    @staticmethod
    def _version_filter(
        candidates: Dict[str, dict],
        min_ras_version: Optional[str],
        min_hms_version: Optional[str],
    ) -> Dict[str, dict]:
        """Filter candidates by detected version. Keeps items with no detected version."""
        if not min_ras_version and not min_hms_version:
            return candidates
        filtered: Dict[str, dict] = {}
        min_ras = UsgsScienceBase._parse_version_tuple(min_ras_version) if min_ras_version else None
        min_hms = UsgsScienceBase._parse_version_tuple(min_hms_version) if min_hms_version else None

        for sb_id, c in candidates.items():
            v = c.get("ras_version_guess")
            if v is None:
                filtered[sb_id] = c
                continue
            v_tuple = UsgsScienceBase._parse_version_tuple(v)
            mtype = c.get("model_type_guess", "")
            if "HMS" in mtype and min_hms:
                if v_tuple >= min_hms:
                    filtered[sb_id] = c
            elif min_ras:
                if v_tuple >= min_ras:
                    filtered[sb_id] = c
            else:
                filtered[sb_id] = c
        return filtered

    # ------------------------------------------------------------------
    # Main orchestrator
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def discover_models(
        cache_dir: Optional[Path] = None,
        strategies: Optional[List[str]] = None,
        min_ras_version: Optional[str] = "6.0",
        min_hms_version: Optional[str] = "4.3",
        include_hms: bool = True,
        max_results_per_query: int = 500,
        request_delay: float = _SB_REQUEST_DELAY,
        export_json: Optional[Path] = None,
        verbose: bool = False,
    ) -> Dict[str, dict]:
        """Systematically discover HEC-RAS/HMS models on USGS ScienceBase.

        Runs multiple discovery strategies (keyword search, FIM cross-reference,
        alternate keywords, child item traversal) and returns deduplicated
        candidate model entries.

        Args:
            cache_dir: Directory for caching intermediate API results.
            strategies: Subset of ["keyword", "fim", "alternate", "children"].
                        Defaults to all four.
            min_ras_version: Minimum HEC-RAS version (e.g. "6.0"). None = no filter.
            min_hms_version: Minimum HEC-HMS version. None = no filter.
            include_hms: If False, exclude HEC-HMS-only results.
            max_results_per_query: Max items per search query.
            request_delay: Seconds between API requests.
            export_json: Path to write final results as JSON.
            verbose: If True, print summary statistics.

        Returns:
            Dict keyed by sciencebase_id, each value a candidate model dict.
        """
        all_strategies = ["keyword", "fim", "alternate", "children"]
        active = strategies if strategies else all_strategies
        seen_ids: Set[str] = set()
        all_candidates: Dict[str, dict] = {}
        errors: List[str] = []

        strategy_bar = tqdm(active, desc="Discovery strategies", unit="strategy")

        for strategy in strategy_bar:
            strategy_bar.set_postfix(current=strategy, found=len(all_candidates))
            try:
                if strategy == "keyword":
                    found = UsgsScienceBase._discover_keyword_search(
                        max_results_per_query=max_results_per_query,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                    )
                elif strategy == "fim":
                    found = UsgsScienceBase._discover_fim_sites(
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                    )
                elif strategy == "alternate":
                    found = UsgsScienceBase._discover_alternate_keywords(
                        max_results_per_query=max_results_per_query,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                    )
                elif strategy == "children":
                    found = UsgsScienceBase._discover_children(
                        parent_candidates=all_candidates,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                    )
                else:
                    logger.warning("Unknown strategy: %s", strategy)
                    continue
                all_candidates.update(found)
            except Exception as exc:
                msg = f"Strategy '{strategy}' failed: {exc}"
                logger.error(msg)
                errors.append(msg)

        if not include_hms:
            all_candidates = {
                k: v for k, v in all_candidates.items()
                if v.get("model_type_guess") != "HEC-HMS"
            }

        all_candidates = UsgsScienceBase._version_filter(
            all_candidates, min_ras_version, min_hms_version,
        )

        if verbose:
            by_type: Dict[str, int] = {}
            by_conf: Dict[str, int] = {}
            for c in all_candidates.values():
                by_type[c["model_type_guess"]] = by_type.get(c["model_type_guess"], 0) + 1
                by_conf[c["confidence"]] = by_conf.get(c["confidence"], 0) + 1
            print(f"\nDiscovered {len(all_candidates)} candidate models")
            print(f"  By type: {by_type}")
            print(f"  By confidence: {by_conf}")
            if errors:
                print(f"  Errors: {len(errors)}")

        if export_json:
            export_json.parent.mkdir(parents=True, exist_ok=True)
            output = {
                "_discovery_meta": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "strategies": active,
                    "min_ras_version": min_ras_version,
                    "min_hms_version": min_hms_version,
                    "total_candidates": len(all_candidates),
                    "errors": errors,
                },
                "candidates": all_candidates,
            }
            export_json.write_text(
                json.dumps(output, indent=2, default=str), encoding="utf-8",
            )
            logger.debug("Exported %d candidates to %s", len(all_candidates), export_json)

        return all_candidates
