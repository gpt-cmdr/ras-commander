"""
USGS ScienceBase HEC-RAS Model Archives

Catalog, download, validate, and organize reviewed public HEC-RAS archives from
USGS ScienceBase. Archives for other engines and derived inundation products are
out of scope for ``RasExamples``.

Models:
- Kalamazoo River, MI (2D, HEC-RAS 6.6, CC0-1.0) - DOI: 10.5066/P13CPA5B
- St. Joseph River, IN (1D steady, HEC-RAS 4.1) - DOI: 10.5066/F7QZ2836
- Fox River Chain of Lakes, IL (2D, HEC-RAS 6.5) - DOI: 10.5066/P16H3TDH
- Silver Creek / Scott AFB, IL (HEC-HMS 4.9 + 2D HEC-RAS 6.5) - DOI: 10.5066/P9GBYP2K

An archive is promoted to ``RasExamples`` after portable-path inspection and
either a fresh verified RAS Commander compute or explicit curator acceptance
with the incomplete-compute evidence preserved in the registry.
"""

from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Dict, List, Set, Any
from urllib.parse import urlencode, urljoin, urlparse
import zipfile

import requests
from tqdm.auto import tqdm

from ras_commander import get_logger, log_call

logger = get_logger(__name__)

SCIENCEBASE_CATALOG_URL = "https://www.sciencebase.gov/catalog"
SCIENCEBASE_PUBLIC_URL = "https://www.sciencebase.gov"

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


class ScienceBaseInteractiveDownloadRequired(RuntimeError):
    """Raised when a public large-file attachment needs a human CAPTCHA."""

    def __init__(
        self,
        filename: str,
        request_url: str,
        destination: Path,
    ) -> None:
        self.filename = filename
        self.request_url = request_url
        self.destination = Path(destination)
        super().__init__(
            f"ScienceBase serves '{filename}' as a public large-file cloud "
            "attachment. A ScienceBase account is not required, but ScienceBase "
            "requires an interactive CAPTCHA before issuing a temporary download "
            f"URL. Open {request_url}, complete the CAPTCHA, and save the archive "
            f"at {self.destination}. Then call download_model() again, or pass the "
            "temporary URL with signed_download_urls={filename: url}."
        )


class UsgsScienceBase:
    """
    Download and organize reviewed USGS ScienceBase HEC-RAS archives.

    Implements the ModelSource protocol for catalog integration while
    maintaining backward compatibility with the original HEC-RAS slug-based
    API. Registry entries include promotion evidence so an unvalidated archive
    cannot be presented as a runnable ``RasExamples`` project.

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
        """Return reviewed ScienceBase archives as ``ModelMetadata`` objects.

        Args:
            validated_only: Return only archives explicitly promoted as
                runnable. Defaults to True. Curator-accepted long-running models
                retain any incomplete-compute caveat in their metadata.
        """
        from ras_commander.sources.base import ModelMetadata, ModelType

        validated_only = bool(kwargs.get("validated_only", True))
        results = []
        _type_map = {
            "2D unsteady": ModelType.UNSTEADY_2D,
            "1D steady": ModelType.STEADY_1D,
            "1D unsteady": ModelType.UNSTEADY_1D,
        }
        for slug, info in UsgsScienceBase._MODEL_REGISTRY.items():
            validation = info.get("validation", {})
            if validated_only and not info.get("runnable", False):
                continue

            mt = _type_map.get(info.get("model_type", ""), ModelType.UNKNOWN)
            software = list(info.get("software", []))
            tags = ["USGS", "ScienceBase", "reviewed", *software]
            if info.get("calibration_data"):
                tags.append("calibrated")
            if info.get("ras_compatible", True):
                tags.append("HEC-RAS")

            total_size_bytes = sum(
                file_info.get(
                    "size_bytes",
                    round(file_info.get("size_mb", 0.0) * 1_000_000),
                )
                for file_info in info.get("files", {}).values()
            )
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
                file_size_mb=round(total_size_bytes / 1_000_000, 2),
                tags=tags,
                extra={
                    "software": software,
                    "runnable": bool(info.get("runnable", False)),
                    "ras_compatible": True,
                    "validation": deepcopy(validation),
                    "archive_access": info.get("archive_access", "catalog"),
                    "total_size_bytes": total_size_bytes,
                    "license": info.get("license"),
                },
            ))
        return results

    _MODEL_REGISTRY = {
        "kalamazoo": {
            "name": "Kalamazoo River, MI",
            "sciencebase_id": "67a38201d34ee33d441d2f22",
            "doi": "10.5066/P13CPA5B",
            "ras_version": "6.6",
            "model_type": "2D unsteady",
            "software": ["HEC-RAS 6.6"],
            "runnable": True,
            "ras_compatible": True,
            "validation": {
                "status": "validated",
                "paths_validated": True,
                "compute_verified": True,
                "validated_plan": "44",
                "validated_at": "2026-07-17",
                "validated_hecras_version": "6.6",
                "component_counts": {
                    "plan": 21,
                    "geometry": 5,
                    "steady_flow": 0,
                    "unsteady_flow": 7,
                },
                "compute_message_lines": 49,
                "compute_error_count": 0,
                "compute_warning_count": 0,
                "complete_process_hours": 0.141684,
                "evidence": (
                    "Fresh RasCmdr.compute_plan('44', force_rerun=True, "
                    "verify=True) against the public archive. All DataFrame and "
                    "RASMapper dependencies were present and project-relative."
                ),
                "blockers": [],
            },
            "license": "CC0-1.0",
            "crs": "EPSG:6499",
            "calibration_data": True,
            "hdf_results": True,
            "dss_file": True,
            "files": {
                "hec_ras_model.zip": {
                    "size_mb": 3121.33,
                    "size_bytes": 3_121_325_101,
                    "required": True,
                    "access": "public_cloud_captcha",
                    "file_id": "cmapqyjt60j780vo9gz7gan9e",
                    "cloud_object_url": (
                        "https://prod-is-usgs-sb-prod-content.s3.amazonaws.com/"
                        "67a38201d34ee33d441d2f22/hec_ras_model.zip"
                    ),
                },
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
            "ras_version": "4.1",
            "model_type": "1D steady",
            "software": ["HEC-RAS 4.1"],
            "runnable": True,
            "ras_compatible": True,
            "validation": {
                "status": "validated",
                "paths_validated": True,
                "compute_verified": True,
                "validated_plan": "24",
                "validated_at": "2026-07-17",
                "validated_hecras_version": "4.1",
                "component_counts": {
                    "plan": 1,
                    "geometry": 1,
                    "steady_flow": 1,
                    "unsteady_flow": 0,
                },
                "compute_message_lines": 6,
                "compute_error_count": 0,
                "compute_warning_count": 0,
                "complete_process_seconds": 3.09,
                "result_row_count": 588,
                "profile_count": 7,
                "location_count": 84,
                "evidence": (
                    "The release's surviving plan 24 is internally complete with "
                    "geometry 18 and steady-flow file 01. A deterministic repair "
                    "removed only 42 stale project-index entries, after which a "
                    "forced HEC-RAS 4.1 RasControl run completed successfully."
                ),
                "blockers": [],
            },
            "repair": {
                "type": "prune_missing_project_entries",
                "keep_plan": "24",
                "expected_missing": {
                    "Plan": [f"{number:02d}" for number in range(1, 24)],
                    "Geom": [
                        f"{number:02d}"
                        for number in range(1, 21)
                        if number != 18
                    ],
                    "Flow": [],
                    "Unsteady": [],
                },
            },
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
                "The release contains its final plan 24, geometry 18, and flow "
                "file 01 but retains stale project references to omitted historical "
                "alternatives. The download workflow removes those references from "
                "the extracted working copy while retaining the original ZIP."
            ),
        },
        "squannacook": {
            "name": "Squannacook River Stream Crossings, MA",
            "sciencebase_id": "62c73389d34eeb1417bb1320",
            "doi": None,
            "ras_version": "6.x",
            "model_type": "1D steady",
            "software": ["HEC-RAS 6.x"],
            "runnable": False,
            "ras_compatible": True,
            "validation": {
                "status": "pending",
                "paths_validated": False,
                "compute_verified": False,
                "validated_plan": None,
                "validated_at": None,
                "evidence": None,
                "blockers": [],
            },
            "license": "USGS data release",
            "crs": None,
            "calibration_data": False,
            "hdf_results": False,
            "dss_file": False,
            "files": {
                "HECRAS_model_files.zip": {"size_mb": 9, "required": True},
            },
            "project_file": "Squannacook.prj",
            "notes": (
                "Georeferenced 1D steady HEC-RAS models for 16 stream crossings "
                "in the Squannacook/Nissitissit basin (MA). Each crossing has "
                "design alternatives comparing culvert shapes (pipe, arch, box) "
                "and survey vs lidar cross sections. Used by the culvert GIS "
                "reconstruction and hydraulic-validity example."
            ),
        },
        "fox-chain-of-lakes": {
            "name": "Fox River Chain of Lakes near McHenry, IL",
            "sciencebase_id": "661e9565d34e7eb9eb7e3ce4",
            "doi": "10.5066/P16H3TDH",
            "ras_version": "6.5",
            "model_type": "2D unsteady",
            "software": ["HEC-RAS 6.5"],
            "runnable": True,
            "ras_compatible": True,
            "validation": {
                "status": "solver_ready",
                "paths_validated": True,
                "compute_verified": False,
                "validated_plan": None,
                "validated_at": "2026-07-18",
                "evidence": {
                    "archive_bytes": 11_959_830_006,
                    "archive_members": 143,
                    "uncompressed_bytes": 12_605_305_446,
                    "project_count": 1,
                    "plan_count": 6,
                    "geometry_count": 3,
                    "unsteady_count": 6,
                    "path_issue_count": 0,
                    "repaired_reference_count": 3,
                    "bundled_complete_plans": ["02", "03", "04"],
                    "readiness_run": {
                        "plan_number": "01",
                        "ras_version": "6.6",
                        "elapsed_seconds": 5877.91,
                        "dss_records_read": 6,
                        "error_count": 0,
                        "warning_count": 0,
                        "terminated_by_curator": True,
                        "completed": False,
                    },
                },
                "blockers": [],
                "caveats": [
                    "A complete fresh HEC-RAS 6.5 compute is not recorded; "
                    "the repeat was explicitly waived for catalog promotion."
                ],
                "public_acceptance": {
                    "accepted_at": "2026-07-19",
                    "full_compute_waived": True,
                    "basis": (
                        "All project paths pass inspection and plan 01 loaded "
                        "every DSS boundary while remaining error-free for "
                        "97.97 minutes. The curator confirmed the model runs "
                        "and waived another multi-hour completion test."
                    ),
                },
            },
            "repair": {
                "type": "replace_unsteady_dependency",
                "unsteady_number": "01",
                "old_text": (
                    "DSS File=.\\Hydrology\\"
                    "Fox_River_ILUSGS_Data_Request_2019_2022_part3.dss"
                ),
                "new_text": (
                    "DSS File=.\\Hydrology\\Fox_River_USGS_Data_Request.dss"
                ),
                "new_dependency": (
                    ".\\Hydrology\\Fox_River_USGS_Data_Request.dss"
                ),
                "expected_occurrences": 3,
            },
            "license": "CC0-1.0",
            "crs": None,
            "calibration_data": True,
            "hdf_results": True,
            "dss_file": True,
            "archive_access": "public_cloud_captcha",
            "files": {
                "model_archive.zip": {
                    "size_mb": 11959.83,
                    "size_bytes": 11_959_830_006,
                    "required": True,
                    "access": "public_cloud_captcha",
                    "file_id": "clwjrpzj2006014pj6gcwhhom",
                    "cloud_object_url": (
                        "https://prod-is-usgs-sb-prod-content.s3.amazonaws.com/"
                        "661e9565d34e7eb9eb7e3ce4/model_archive.zip"
                    ),
                },
                "Fox_River_Chain_of_Lakes_model_archive.xml": {
                    "size_mb": 0.06,
                    "required": False,
                },
            },
            "project_file": (
                "Fox_River_Chain_of_Lakes_hydraulic_model/model_run_files/"
                "Chain_of_Lakes_RAS2D/Fox_River_Chain_of_Lakes.prj"
            ),
            "notes": (
                "Calibrated 2D unsteady HEC-RAS model of the 18.5-mile Chain "
                "of Lakes system and 1.7 miles below Stratton Dam. The archive "
                "contains calibration, validation, and July 2017 flood-event "
                "runs. A deterministic working-copy repair redirects three stale "
                "unsteady-flow references to the delivered USGS DSS file; the "
                "published ZIP remains unchanged. All project dependencies then "
                "pass inspection. A 97.97-minute HEC-RAS 6.6 readiness run loaded "
                "all DSS boundaries and remained error-free until intentionally "
                "stopped. The curator accepted that evidence for public catalog "
                "promotion without another multi-hour completion test; the "
                "incomplete-compute status remains explicit in metadata."
            ),
        },
        "silver-creek-safb": {
            "name": "Silver Creek Basin and Scott Air Force Base, IL",
            "sciencebase_id": "644c1526d34e45f6ddcd4a3a",
            "doi": "10.5066/P9GBYP2K",
            "ras_version": "6.6",
            "model_type": "2D unsteady",
            "software": ["HEC-HMS 4.9", "HEC-RAS 6.5"],
            "runnable": True,
            "ras_compatible": True,
            "validation": {
                "status": "validated",
                "paths_validated": True,
                "compute_verified": True,
                "validated_plan": "10",
                "validated_at": "2026-07-19",
                "validated_hecras_version": "6.6",
                "component_counts": {
                    "plan": 35,
                    "geometry": 8,
                    "steady_flow": 0,
                    "unsteady_flow": 38,
                },
                "evidence": {
                    "archive_bytes": 68_546_574_746,
                    "selected_archive_members": 883,
                    "selected_uncompressed_bytes": 17_093_244_335,
                    "project_count": 1,
                    "path_issue_count": 0,
                    "repaired_reference_count": 2,
                    "pruned_unsteady_count": 3,
                    "dss_preflight": {
                        "plan_number": "10",
                        "required_series": 29,
                        "series_read": 29,
                        "series_failed": 0,
                        "start": "2022-07-25 12:00:00",
                        "end": "2022-07-31 18:00:00",
                    },
                    "validation_run": {
                        "plan_number": "10",
                        "plan_title": "July2022_calibration",
                        "ras_version": "6.6",
                        "solver_cores": 8,
                        "simulation_hours": 66.0,
                        "unsteady_compute_hours": 1.7870877777777778,
                        "complete_process_hours": 1.903706388888889,
                        "complete_process_speed": 34.66921179926351,
                        "result_hdf_bytes": 82_893_073,
                        "volume_error_acre_feet": 0.32734280824661255,
                        "volume_error_percent": 0.0014949932228773832,
                        "error_count": 0,
                        "warning_count": 0,
                        "completed": True,
                    },
                },
                "blockers": [],
            },
            "repair": {
                "type": "replace_dependencies_and_prune_unsteady",
                "replacements": [
                    {
                        "unsteady_number": "04",
                        "old_text": (
                            "DSS File=.\\Hydrology\\March23_2023_v1_9_22_23\\"
                            "March23_2023__Spl.dss"
                        ),
                        "new_text": (
                            "DSS File=.\\Hydrology\\March_23_2023_v1_3_1_24\\"
                            "March23_2023__Spl.dss"
                        ),
                        "new_dependency": (
                            ".\\Hydrology\\March_23_2023_v1_3_1_24\\"
                            "March23_2023__Spl.dss"
                        ),
                        "expected_occurrences": 2,
                        "expected_existing_new_occurrences": 25,
                        "validated_pathnames": [
                            (
                                "//SUBBASIN-27/FLOW/23MAR2023/5MIN/"
                                "RUN:MARCH23_2023 -SPL/"
                            ),
                            (
                                "//SUBBASIN-30/FLOW/23MAR2023/5MIN/"
                                "RUN:MARCH23_2023 -SPL/"
                            ),
                        ],
                    }
                ],
                "prune_unsteady_numbers": ["05", "08", "09"],
                "expected_plan_numbers_by_unsteady": {
                    "04": ["07"],
                    "05": [],
                    "08": [],
                    "09": [],
                },
            },
            "license": "CC0-1.0",
            "crs": None,
            "calibration_data": True,
            "hdf_results": True,
            "dss_file": True,
            "archive_access": "public_cloud_captcha",
            "archive_prefixes": ["model_run_files/HEC-RAS_model"],
            "files": {
                "SilverCreek-SAFB_model_archive.7z": {
                    "size_mb": 68546.57,
                    "size_bytes": 68_546_574_746,
                    "required": True,
                    "access": "public_cloud_captcha",
                    "file_id": "cm334qwm0001a0upjfl63emai",
                    "cloud_object_url": (
                        "https://prod-is-usgs-sb-prod-content.s3.amazonaws.com/"
                        "644c1526d34e45f6ddcd4a3a/"
                        "SilverCreek-SAFB_model_archive.7z"
                    ),
                },
                "Silver_Creek_ScottAFB_model_archive.xml": {
                    "size_mb": 0.07,
                    "required": False,
                },
            },
            "project_file": "model_run_files/HEC-RAS_model/SAFB_RAS2D.prj",
            "notes": (
                "Coupled HEC-HMS and 2D unsteady HEC-RAS archive with 52 "
                "hydrologic/hydraulic scenarios, calibration data, detention "
                "alternatives, land-cover conditions, and projected 2050 "
                "precipitation. The working-copy repair redirects the retained "
                "March 23 calibration plan to the delivered updated DSS and "
                "removes three unreferenced unsteady-flow index entries whose "
                "older DSS files are absent; source files and the 7z remain "
                "unchanged. All 35 retained plans then pass portable-path "
                "inspection. A fresh HEC-RAS 6.6 plan 10 run read all 29 DSS "
                "series and completed its 66-hour simulation with zero errors "
                "or warnings and 0.001495 percent volume error. ScienceBase "
                "serves the archive through its "
                "public cloud-download form, which requires a CAPTCHA but no "
                "account."
            ),
        },
    }

    _MODEL_ALIASES = {
        "kalamazoo": "kalamazoo",
        "kalamazoo-river": "kalamazoo",
        "kzoo": "kalamazoo",
        "trowbridge": "kalamazoo",
        "p13cpa5b": "kalamazoo",
        "st-joseph": "st-joseph",
        "st-joseph-river": "st-joseph",
        "stjoseph": "st-joseph",
        "elkhart": "st-joseph",
        "f7qz2836": "st-joseph",
        "squannacook": "squannacook",
        "squannacook-river": "squannacook",
        "squannacook-crossings": "squannacook",
        "fox-chain-of-lakes": "fox-chain-of-lakes",
        "fox-river": "fox-chain-of-lakes",
        "chain-of-lakes": "fox-chain-of-lakes",
        "mchenry": "fox-chain-of-lakes",
        "p16h3tdh": "fox-chain-of-lakes",
        "silver-creek-safb": "silver-creek-safb",
        "silver-creek": "silver-creek-safb",
        "scott-afb": "silver-creek-safb",
        "safb": "silver-creek-safb",
        "p9gbyp2k": "silver-creek-safb",
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
        return deepcopy(UsgsScienceBase._MODEL_REGISTRY[slug])

    @staticmethod
    def list_models(validated_only: bool = True) -> list[str]:
        """Return HEC-RAS model slugs, optionally including candidates."""
        if not validated_only:
            return list(UsgsScienceBase._MODEL_REGISTRY.keys())
        return [
            slug
            for slug, info in UsgsScienceBase._MODEL_REGISTRY.items()
            if info.get("runnable", False)
        ]

    @staticmethod
    def _progress(*args, show_progress: bool = False, **kwargs):
        """Return a tqdm wrapper that is quiet unless explicitly requested."""
        kwargs.setdefault("disable", not show_progress)
        return tqdm(*args, **kwargs)

    @staticmethod
    def _get_public_item_files(sciencebase_id: str) -> Dict[str, dict]:
        """Return attachment metadata from the public ScienceBase item JSON."""
        response = requests.get(
            f"{SCIENCEBASE_CATALOG_URL}/item/{sciencebase_id}",
            params={"format": "json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        files: Dict[str, dict] = {}
        for record in payload.get("files", []):
            name = str(record.get("name", "")).strip()
            if not name:
                continue
            if name in files:
                raise RuntimeError(
                    f"ScienceBase item {sciencebase_id} contains duplicate "
                    f"attachment names: {name}"
                )
            files[name] = record
        return files

    @staticmethod
    def _parse_cloud_download_forms(
        item_html: str,
        sciencebase_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Parse public CAPTCHA request URLs for large cloud attachments."""
        forms: Dict[str, str] = {}
        for match in re.finditer(
            r"<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>",
            str(item_html),
            flags=re.IGNORECASE | re.DOTALL,
        ):
            attrs = match.group("attrs")
            if "sb-s3file-download-form" not in attrs:
                continue
            action_match = re.search(
                r"\baction\s*=\s*['\"](?P<action>[^'\"]+)['\"]",
                attrs,
                flags=re.IGNORECASE,
            )
            button_match = re.search(
                r"<button\b[^>]*>(?P<label>.*?)</button>",
                match.group("body"),
                flags=re.IGNORECASE | re.DOTALL,
            )
            if action_match is None or button_match is None:
                continue
            filename = unescape(
                re.sub(r"<[^>]+>", "", button_match.group("label"))
            ).strip()
            request_url = urljoin(
                SCIENCEBASE_PUBLIC_URL,
                unescape(action_match.group("action")),
            )
            parsed = urlparse(request_url)
            expected_prefix = "/catalog/item/managerRequestDownload/"
            if (
                parsed.scheme != "https"
                or parsed.netloc.lower() != "www.sciencebase.gov"
                or not parsed.path.startswith(expected_prefix)
                or (sciencebase_id and not parsed.path.endswith(f"/{sciencebase_id}"))
            ):
                raise RuntimeError(
                    "ScienceBase returned an unexpected cloud-download form "
                    f"action for {filename!r}: {request_url}"
                )
            forms[filename] = request_url
        return forms

    @staticmethod
    def _build_public_cloud_request_url(
        sciencebase_id: str,
        cloud_object_url: str,
    ) -> str:
        """Build the public ScienceBase CAPTCHA URL for one cloud object."""
        return (
            f"{SCIENCEBASE_CATALOG_URL}/item/managerRequestDownload/"
            f"{sciencebase_id}?{urlencode({'filePath': cloud_object_url})}"
        )

    @staticmethod
    def _get_public_cloud_download_url(
        sciencebase_id: str,
        filename: str,
        file_info: Optional[dict] = None,
    ) -> str:
        """Resolve the official public CAPTCHA page for a large attachment."""
        try:
            response = requests.get(
                f"{SCIENCEBASE_CATALOG_URL}/item/{sciencebase_id}",
                timeout=60,
            )
            response.raise_for_status()
            forms = UsgsScienceBase._parse_cloud_download_forms(
                response.text,
                sciencebase_id=sciencebase_id,
            )
            if filename in forms:
                return forms[filename]
        except requests.RequestException as exc:
            logger.warning(
                "Could not refresh the public ScienceBase cloud-download form "
                "for %s: %s",
                filename,
                exc,
            )

        file_info = file_info or {}
        request_url = file_info.get("request_url")
        if request_url:
            return str(request_url)
        cloud_object_url = file_info.get("cloud_object_url")
        if cloud_object_url:
            return UsgsScienceBase._build_public_cloud_request_url(
                sciencebase_id,
                str(cloud_object_url),
            )
        raise RuntimeError(
            f"ScienceBase did not publish a public cloud-download form for "
            f"{filename!r} on item {sciencebase_id}."
        )

    @staticmethod
    @log_call
    def get_download_manifest(model_key: str, output_dir: Path) -> List[dict]:
        """Return live direct or CAPTCHA-gated attachment download metadata."""
        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        sciencebase_id = info["sciencebase_id"]
        try:
            public_files = UsgsScienceBase._get_public_item_files(sciencebase_id)
        except requests.RequestException as exc:
            logger.warning(
                "Could not refresh ScienceBase item JSON for %s: %s",
                slug,
                exc,
            )
            public_files = {}

        model_dir = Path(output_dir) / slug
        manifest: List[dict] = []
        for filename, registry_file in info["files"].items():
            live_file = public_files.get(filename, {})
            merged = {**registry_file, **live_file}
            live_url = str(
                live_file.get("downloadUri")
                or live_file.get("url")
                or ""
            )
            is_cloud = (
                merged.get("access") == "public_cloud_captcha"
                or "/manager/" in live_url
            )
            expected_size = merged.get("size") or merged.get("size_bytes")
            record = {
                "filename": filename,
                "required": bool(registry_file.get("required")),
                "size_bytes": int(expected_size) if expected_size else None,
                "destination": str(model_dir / filename),
                "access": "public_cloud_captcha" if is_cloud else "direct",
                "download_url": None,
                "request_url": None,
            }
            if is_cloud:
                registered_cloud_url = registry_file.get("cloud_object_url")
                if registered_cloud_url:
                    # The CAPTCHA endpoint itself is deterministic. Avoid an
                    # extra item-HTML request here; repeated form refreshes can
                    # contribute to ScienceBase throttling without improving
                    # the authoritative object URL already in the registry.
                    record["request_url"] = (
                        UsgsScienceBase._build_public_cloud_request_url(
                            sciencebase_id,
                            str(registered_cloud_url),
                        )
                    )
                else:
                    record["request_url"] = (
                        UsgsScienceBase._get_public_cloud_download_url(
                            sciencebase_id,
                            filename,
                            merged,
                        )
                    )
            else:
                record["download_url"] = UsgsScienceBase._get_file_url(
                    sciencebase_id,
                    filename,
                    merged,
                )
            manifest.append(record)
        return manifest

    @staticmethod
    def _download_file(
        url: str,
        dest: Path,
        desc: str = "",
        show_progress: bool = False,
        expected_size: Optional[int] = None,
    ) -> Path:
        """Download with the proven eBFE resumable ``.part`` helper."""
        from ras_commander.sources.federal.ebfe_models import RasEbfeModels

        with RasEbfeModels._output_options(
            verbose=show_progress,
            show_progress=show_progress,
        ):
            result = RasEbfeModels._download_file(url, dest, desc)
        if expected_size is not None and result.stat().st_size != int(expected_size):
            raise RuntimeError(
                f"Downloaded byte count for '{dest.name}' does not match "
                f"ScienceBase metadata: expected {int(expected_size):,}, got "
                f"{result.stat().st_size:,}."
            )
        return result

    @staticmethod
    def _get_file_url(
        sciencebase_id: str,
        filename: str,
        file_info: Optional[dict] = None,
    ) -> str:
        """Build the ScienceBase catalog file download URL."""
        if file_info:
            for field in ("download_url", "downloadUri", "url"):
                if file_info.get(field) and "/manager/" not in str(file_info[field]):
                    return str(file_info[field])
        return f"{SCIENCEBASE_CATALOG_URL}/file/get/{sciencebase_id}?name={filename}"

    @staticmethod
    def _validated_archive_targets(
        member_names: List[str],
        destination: Path,
    ) -> Dict[str, Path]:
        """Resolve archive members below ``destination`` or reject the archive."""
        # ``Path.resolve(strict=False)`` still probes the filesystem on Windows.
        # Resolving every member of a large archive can therefore take tens of
        # minutes on a mapped/network destination even though this check only
        # needs lexical path normalization. ``abspath`` preserves the traversal
        # guard without touching each target on disk.
        destination = Path(os.path.abspath(destination))
        targets: Dict[str, Path] = {}
        for member_name in member_names:
            member_name = str(member_name).strip()
            if not member_name or member_name in {".", "./", ".\\"}:
                continue
            member = PureWindowsPath(member_name)
            if member.is_absolute() or member.drive or ".." in member.parts:
                raise RuntimeError(
                    f"Unsafe archive member path rejected: {member_name!r}"
                )
            target = Path(os.path.abspath(destination.joinpath(*member.parts)))
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise RuntimeError(
                    f"Archive member escapes extraction directory: {member_name!r}"
                ) from exc
            targets[member_name] = target
        return targets

    @staticmethod
    def _find_7zip() -> Path:
        """Return an installed 7-Zip command suitable for large archives."""
        candidates = [
            shutil.which("7z"),
            shutil.which("7zz"),
            shutil.which("7za"),
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        raise RuntimeError(
            "Extracting a ScienceBase .7z archive requires 7-Zip. Install "
            "7-Zip or extract the archive manually with its directory structure "
            "preserved."
        )

    @staticmethod
    def _parse_7z_listing(output: str) -> List[Dict[str, str]]:
        """Parse member records from ``7z l -slt`` output."""
        records: List[Dict[str, str]] = []
        record: Dict[str, str] = {}
        in_members = False
        for raw_line in output.splitlines():
            line = raw_line.strip()
            # 7-Zip emits a short ``--`` before archive-level metadata and a
            # longer separator before actual member records. Ignore the former.
            if len(line) >= 10 and set(line) == {"-"}:
                in_members = True
                record = {}
                continue
            if not in_members:
                continue
            if not line:
                if record.get("Path"):
                    records.append(record)
                record = {}
                continue
            if " = " in line:
                key, value = line.split(" = ", 1)
                record[key] = value
        if record.get("Path"):
            records.append(record)
        return records

    @staticmethod
    def _list_7z_members(archive_path: Path) -> List[Dict[str, str]]:
        """List a 7-Zip archive without extracting its large payload."""
        seven_zip = UsgsScienceBase._find_7zip()
        result = subprocess.run(
            [str(seven_zip), "l", "-slt", str(archive_path)],
            check=False,
            capture_output=True,
            text=True,
            # A cold scan of the 68.5 GB Silver Creek solid archive can take
            # longer than ten minutes on Windows (including antivirus I/O).
            # Keep the operation bounded without rejecting a healthy archive.
            timeout=3600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"7-Zip could not list '{archive_path.name}' "
                f"(exit {result.returncode}): {detail[-2000:]}"
            )
        records = UsgsScienceBase._parse_7z_listing(result.stdout)
        if not records:
            raise RuntimeError(f"7-Zip reported no members in '{archive_path}'.")
        return records

    @staticmethod
    def _filter_7z_records(
        records: List[Dict[str, str]],
        include_prefixes: List[str],
    ) -> List[Dict[str, str]]:
        """Return file records at or below reviewed archive path prefixes."""
        if not include_prefixes:
            raise ValueError("include_prefixes must contain at least one path.")

        prefixes = []
        for prefix in include_prefixes:
            parts = tuple(
                part.casefold()
                for part in PureWindowsPath(str(prefix).strip()).parts
                if part not in {"", "."}
            )
            if not parts or ".." in parts:
                raise ValueError(f"Invalid archive include prefix: {prefix!r}")
            prefixes.append(parts)

        selected: List[Dict[str, str]] = []
        for record in records:
            is_directory = (
                record.get("Folder") == "+"
                or record.get("Attributes", "").startswith("D")
            )
            if is_directory:
                continue
            parts = tuple(
                part.casefold() for part in PureWindowsPath(record["Path"]).parts
            )
            if any(parts[: len(prefix)] == prefix for prefix in prefixes):
                selected.append(record)

        if not selected:
            requested = ", ".join(repr(prefix) for prefix in include_prefixes)
            raise RuntimeError(
                f"No archive files matched the reviewed prefixes: {requested}"
            )
        return selected

    @staticmethod
    def _7z_members_are_extracted(
        records: List[Dict[str, str]],
        destination: Path,
    ) -> bool:
        """Return whether every listed member exists with its archived size."""
        targets = UsgsScienceBase._validated_archive_targets(
            [record["Path"] for record in records],
            destination,
        )
        for record in records:
            member_name = record["Path"]
            target = targets.get(member_name)
            if target is None:
                continue
            is_directory = (
                record.get("Folder") == "+"
                or record.get("Attributes", "").startswith("D")
            )
            if is_directory:
                if not target.is_dir():
                    return False
                continue
            if not target.is_file():
                return False
            try:
                expected_size = int(record.get("Size", "0"))
            except ValueError:
                return False
            if target.stat().st_size != expected_size:
                return False
        return True

    @staticmethod
    def _extract_7z_archive(
        archive_path: Path,
        destination: Path,
        *,
        include_prefixes: Optional[List[str]] = None,
    ) -> None:
        """Safely extract or resume a large 7-Zip ScienceBase archive.

        ``include_prefixes`` supports reviewed, RAS-only extraction from a
        mixed-engine archive. Selected members are passed to 7-Zip through a
        UTF-8 list file so command-line length limits cannot drop dependencies.
        """
        records = UsgsScienceBase._list_7z_members(archive_path)
        UsgsScienceBase._validated_archive_targets(
            [record["Path"] for record in records],
            destination,
        )
        selected_records = (
            UsgsScienceBase._filter_7z_records(records, include_prefixes)
            if include_prefixes is not None
            else records
        )
        if UsgsScienceBase._7z_members_are_extracted(
            selected_records,
            destination,
        ):
            logger.debug("Archive already extracted completely: %s", archive_path.name)
            return

        seven_zip = UsgsScienceBase._find_7zip()
        logger.info("Extracting %s with 7-Zip...", archive_path.name)
        list_path: Optional[Path] = None
        command = [
            str(seven_zip),
            "x",
            str(archive_path),
            f"-o{destination}",
            "-y",
            "-bso0",
            "-bsp0",
            "-bse1",
        ]
        if include_prefixes is not None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".txt",
                delete=False,
            ) as list_file:
                for record in selected_records:
                    list_file.write(f"{record['Path']}\n")
                list_path = Path(list_file.name)
            command.extend(["-scsUTF-8", f"@{list_path}"])

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        finally:
            if list_path is not None:
                list_path.unlink(missing_ok=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"7-Zip could not extract '{archive_path.name}' "
                f"(exit {result.returncode}): {detail[-2000:]}"
            )
        if not UsgsScienceBase._7z_members_are_extracted(
            selected_records,
            destination,
        ):
            raise RuntimeError(
                f"7-Zip returned success but '{archive_path.name}' is not fully "
                "extracted with the archived member sizes."
            )

    @staticmethod
    def _extract_zip_archive(archive_path: Path, destination: Path) -> None:
        """Safely extract a ZIP archive and skip complete existing members."""
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            targets = UsgsScienceBase._validated_archive_targets(
                [member.filename for member in members],
                destination,
            )
            complete = all(
                (
                    targets[member.filename].is_dir()
                    if member.is_dir()
                    else targets[member.filename].is_file()
                    and targets[member.filename].stat().st_size == member.file_size
                )
                for member in members
                if member.filename in targets
            )
            if complete:
                logger.debug("Archive already extracted completely: %s", archive_path.name)
                return
            logger.info("Extracting %s...", archive_path.name)
            archive.extractall(destination)

    @staticmethod
    @log_call
    def extract_local_model(
        model_key: str,
        base_dir: Path,
        *,
        organize: bool = True,
        archive_dir: Optional[Path] = None,
        archive_prefixes: Optional[List[str]] = None,
    ) -> Path:
        """Safely process an already-downloaded ScienceBase archive offline.

        This is the preferred continuation after a browser CAPTCHA download has
        been placed at the destination reported by :meth:`get_download_manifest`.
        ``archive_dir`` may point to a verified staging folder when copying a
        very large archive beside its extracted tree would be wasteful.
        ``archive_prefixes`` optionally limits a 7-Zip archive to reviewed paths,
        such as the runnable RAS tree and its external DSS dependencies. It
        performs no ScienceBase requests. Required archives must exist and match
        any authoritative byte count registered for the attachment before ZIP
        or 7-Zip extraction begins.
        """
        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        model_dir = Path(base_dir) / slug
        if not model_dir.is_dir():
            raise FileNotFoundError(
                f"ScienceBase model folder does not exist: {model_dir}"
            )
        archive_root = Path(archive_dir) if archive_dir is not None else model_dir

        archive_found = False
        for filename, file_info in info["files"].items():
            lower_name = filename.lower()
            if not lower_name.endswith((".zip", ".7z")):
                continue
            archive_path = archive_root / filename
            if not archive_path.is_file():
                if file_info["required"]:
                    raise FileNotFoundError(
                        f"Required ScienceBase archive is missing: {archive_path}"
                    )
                continue

            archive_found = True
            expected_size = file_info.get("size_bytes")
            if (
                expected_size is not None
                and archive_path.stat().st_size != int(expected_size)
            ):
                raise RuntimeError(
                    f"Local byte count for '{filename}' does not match "
                    f"ScienceBase metadata: expected {int(expected_size):,}, "
                    f"got {archive_path.stat().st_size:,}."
                )

            if lower_name.endswith(".zip"):
                if archive_prefixes is not None:
                    raise ValueError(
                        "archive_prefixes is currently supported only for 7-Zip "
                        "ScienceBase archives."
                    )
                UsgsScienceBase._extract_zip_archive(archive_path, model_dir)
            else:
                UsgsScienceBase._extract_7z_archive(
                    archive_path,
                    model_dir,
                    include_prefixes=archive_prefixes,
                )

        if not archive_found:
            raise FileNotFoundError(
                f"No ScienceBase ZIP or 7-Zip archive found below {model_dir}."
            )
        if info.get("repair"):
            UsgsScienceBase.repair_local_model(slug, base_dir)
        if organize:
            UsgsScienceBase.organize_model(
                slug,
                base_dir,
                archive_dir=archive_dir,
            )
        return model_dir

    @staticmethod
    @log_call
    def download_model(
        model_key: str,
        output_dir: Path,
        required_only: bool = False,
        extract: bool = True,
        show_progress: bool = False,
        signed_download_urls: Optional[Dict[str, str]] = None,
        organize: bool = True,
    ) -> Path:
        """
        Download a USGS ScienceBase model to output_dir.

        Args:
            model_key: Model slug, alias, or DOI suffix
            output_dir: Parent directory for the model folder
            required_only: If True, skip optional files (rasters, field data, DEM)
            extract: If True, safely extract ZIP and 7-Zip files after download
            show_progress: If True, show download progress bars.
            signed_download_urls: Optional mapping of attachment filename to a
                temporary URL issued after completing ScienceBase's public
                large-file CAPTCHA. Direct catalog attachments do not need it.
            organize: If True, preserve the extracted source hierarchy and write
                eBFE-style manifest, model log, and path-audit artifacts.

        Returns:
            Path to the model directory
        """
        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]

        model_dir = Path(output_dir) / slug
        model_dir.mkdir(parents=True, exist_ok=True)
        signed_download_urls = signed_download_urls or {}
        download_manifest = {
            record["filename"]: record
            for record in UsgsScienceBase.get_download_manifest(slug, output_dir)
        }

        # Fetch ordinary catalog attachments before stopping at an interactive
        # large-file gate. This preserves useful metadata locally even when the
        # user has not completed the public CAPTCHA yet.
        ordered_files = sorted(
            info["files"].items(),
            key=lambda item: (
                download_manifest[item[0]]["access"]
                == "public_cloud_captcha",
            ),
        )
        for filename, file_info in ordered_files:
            if required_only and not file_info["required"]:
                logger.debug(f"Skipping optional file: {filename}")
                continue

            dest = model_dir / filename
            download_record = download_manifest[filename]
            expected_size = download_record.get("size_bytes")
            if dest.exists():
                size_matches = (
                    dest.stat().st_size == int(expected_size)
                    if expected_size is not None
                    else dest.stat().st_size > 1000
                )
                if size_matches:
                    logger.debug(f"Already downloaded: {filename}")
                    continue

                part_path = dest.parent / f"{dest.name}.part"
                if part_path.exists():
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    quarantine_path = dest.parent / (
                        f"{dest.name}.unexpected-size-{timestamp}"
                    )
                    dest.replace(quarantine_path)
                    logger.warning(
                        "Preserved unexpected-size download as %s",
                        quarantine_path.name,
                    )
                else:
                    dest.replace(part_path)
                    logger.info(
                        "Staged incomplete %s download for HTTP resume (%s bytes).",
                        filename,
                        part_path.stat().st_size,
                    )

            if download_record["access"] == "public_cloud_captcha":
                url = signed_download_urls.get(filename)
                if not url:
                    raise ScienceBaseInteractiveDownloadRequired(
                        filename,
                        str(download_record["request_url"]),
                        dest,
                    )
            else:
                url = str(download_record["download_url"])
            logger.debug(f"Downloading {filename} ({file_info['size_mb']} MB)...")
            UsgsScienceBase._download_file(
                url,
                dest,
                desc=filename,
                show_progress=show_progress,
                expected_size=expected_size,
            )

        if extract:
            UsgsScienceBase.extract_local_model(
                slug,
                output_dir,
                organize=organize,
                archive_prefixes=info.get("archive_prefixes"),
            )

        return model_dir

    @staticmethod
    def get_project_path(model_key: str, base_dir: Path) -> Path:
        """Return the path to the .prj file for a downloaded model."""
        from ras_commander.RasUtils import RasUtils

        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        model_dir = Path(base_dir) / slug
        project_file = info.get("project_file")
        if project_file:
            registered_path = model_dir / project_file
            if registered_path.is_file():
                return registered_path

        discovered = RasUtils.find_valid_ras_folders(
            model_dir,
            max_depth=15,
            return_project_info=True,
        )
        project_files = sorted(
            {Path(project["prj_file"]) for project in discovered},
            key=lambda path: str(path).lower(),
        )
        if not project_files and model_dir.exists():
            # Permit discovery in a manually staged, not-yet-complete model
            # folder while still excluding Esri projection files.
            for candidate in model_dir.rglob("*.prj"):
                try:
                    with candidate.open(
                        "r", encoding="utf-8", errors="replace"
                    ) as stream:
                        first_line = stream.readline()
                except OSError:
                    continue
                if first_line.strip().startswith("Proj Title="):
                    project_files.append(candidate)
            project_files.sort(key=lambda path: str(path).lower())
        if len(project_files) == 1:
            return project_files[0]
        if not project_files:
            raise FileNotFoundError(
                f"No HEC-RAS .prj file found below {model_dir}. Download and "
                "extract the ScienceBase archive first."
            )
        raise RuntimeError(
            f"Multiple HEC-RAS project files found below {model_dir}; select "
            "the intended project explicitly: "
            + ", ".join(str(path) for path in project_files)
        )

    @staticmethod
    @log_call
    def repair_local_model(model_key: str, base_dir: Path) -> dict:
        """Apply a registered, deterministic repair to an extracted model.

        Repairs are limited to exact, pre-reviewed project-index or dependency
        substitutions. The method refuses to proceed if the extracted release
        differs from the registered repair profile.
        """
        from ras_commander import RasPrj, init_ras_project
        from ras_commander.RasUtils import RasUtils
        from ras_commander.sources.federal.sciencebase_validation import (
            ScienceBaseValidation,
        )

        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        repair = info.get("repair")
        if not repair:
            raise ValueError(f"No registered repair is defined for '{slug}'.")
        repair_type = repair.get("type")
        supported_repairs = {
            "prune_missing_project_entries",
            "replace_unsteady_dependency",
            "replace_dependencies_and_prune_unsteady",
        }
        if repair_type not in supported_repairs:
            raise ValueError(
                f"Unsupported ScienceBase repair type: {repair_type!r}"
            )

        base_dir = Path(base_dir)
        model_dir = base_dir / slug
        project_file = UsgsScienceBase.get_project_path(slug, base_dir)

        def persist_repair_report(report: dict) -> dict:
            repair_path = model_dir / "agent" / "repair_report.json"
            report["repair_artifact"] = str(repair_path)
            UsgsScienceBase._write_text_atomic(
                repair_path,
                json.dumps(report, indent=2, default=str),
            )
            return report

        ras_obj = RasPrj()
        init_ras_project(
            project_file,
            info["ras_version"],
            ras_object=ras_obj,
            load_results_summary=False,
            hide_intro=True,
        )

        if repair_type == "replace_dependencies_and_prune_unsteady":
            from ras_commander import RasDss

            expected_usage = {
                str(number).zfill(2): sorted(
                    str(plan_number).zfill(2) for plan_number in plan_numbers
                )
                for number, plan_numbers in repair[
                    "expected_plan_numbers_by_unsteady"
                ].items()
            }
            for unsteady_number, expected_plans in expected_usage.items():
                actual_plans = sorted(
                    str(value).zfill(2)
                    for value in ras_obj.plan_df.loc[
                        ras_obj.plan_df["unsteady_number"].astype(str).str.zfill(2)
                        == unsteady_number,
                        "plan_number",
                    ].tolist()
                )
                if actual_plans != expected_plans:
                    raise RuntimeError(
                        "ScienceBase archive does not match the registered plan "
                        f"usage for unsteady file {unsteady_number}: expected "
                        f"{expected_plans}, found {actual_plans}."
                    )

            applied_any = False
            replacement_reports = []
            validated_pathnames = []
            for replacement in repair["replacements"]:
                unsteady_number = str(replacement["unsteady_number"]).zfill(2)
                matching = ras_obj.unsteady_df.loc[
                    ras_obj.unsteady_df["unsteady_number"].astype(str).str.zfill(2)
                    == unsteady_number
                ]
                if len(matching) != 1:
                    raise RuntimeError(
                        "Registered ScienceBase dependency repair expected exactly "
                        f"one unsteady-flow file {unsteady_number}, found "
                        f"{len(matching)}."
                    )

                target_file = Path(matching.iloc[0]["full_path"])
                dependency_path = project_file.parent / str(
                    replacement["new_dependency"]
                )
                if not dependency_path.is_file():
                    raise RuntimeError(
                        "Registered ScienceBase dependency replacement is absent: "
                        f"{dependency_path}"
                    )

                old_bytes = str(replacement["old_text"]).encode("ascii")
                new_bytes = str(replacement["new_text"]).encode("ascii")
                expected_count = int(replacement["expected_occurrences"])
                expected_existing_new = int(
                    replacement.get("expected_existing_new_occurrences", 0)
                )
                expected_final_new = expected_existing_new + expected_count
                payload = target_file.read_bytes()
                old_count = payload.count(old_bytes)
                new_count = payload.count(new_bytes)
                if (
                    old_count == expected_count
                    and new_count == expected_existing_new
                ):
                    updated = payload.replace(old_bytes, new_bytes)
                    temporary = target_file.parent / f".{target_file.name}.repair.tmp"
                    temporary.write_bytes(updated)
                    temporary.replace(target_file)
                    replacement_status = "applied"
                    applied_any = True
                elif old_count == 0 and new_count == expected_final_new:
                    replacement_status = "already_applied"
                else:
                    raise RuntimeError(
                        "ScienceBase archive does not match the registered dependency "
                        f"repair profile for '{slug}' unsteady file "
                        f"{unsteady_number}: expected {expected_count} old plus "
                        f"{expected_existing_new} already-current references, or "
                        f"{expected_final_new} repaired references, found {old_count} "
                        f"old and {new_count} current."
                    )

                for pathname in replacement.get("validated_pathnames", []):
                    pathname_report = RasDss.check_pathname(
                        dependency_path,
                        pathname,
                    )
                    if not pathname_report.is_valid:
                        raise RuntimeError(
                            "Registered replacement DSS does not contain a valid "
                            f"boundary pathname: {pathname}"
                        )
                    validated_pathnames.append(
                        {
                            "dss_file": str(dependency_path),
                            "pathname": pathname,
                            "summary": pathname_report.summary,
                        }
                    )

                replacement_reports.append(
                    {
                        "unsteady_number": unsteady_number,
                        "old": replacement["old_text"],
                        "new": replacement["new_text"],
                        "occurrences": expected_count,
                        "existing_current_occurrences": expected_existing_new,
                        "final_current_occurrences": expected_final_new,
                        "status": replacement_status,
                    }
                )

            present_unsteady = {
                str(value).zfill(2)
                for value in ras_obj.unsteady_df["unsteady_number"].tolist()
            }
            removed_unsteady = []
            for number in repair["prune_unsteady_numbers"]:
                unsteady_number = str(number).zfill(2)
                if unsteady_number not in present_unsteady:
                    continue
                RasUtils.remove_prj_entry(
                    project_file,
                    "Unsteady",
                    unsteady_number,
                    ras_object=ras_obj,
                )
                removed_unsteady.append(unsteady_number)
                applied_any = True

            report = ScienceBaseValidation.inspect_project(
                project_file,
                info["ras_version"],
                model_slug=slug,
                archive_root=model_dir,
            )
            if not report["paths_validated"]:
                raise RuntimeError(
                    f"Registered repair for '{slug}' did not produce a portable "
                    f"project: {report['issues']}"
                )
            report["repair_status"] = (
                "applied" if applied_any else "already_applied"
            )
            report["replaced_dependencies"] = replacement_reports
            report["removed_entries"] = {"Unsteady": removed_unsteady}
            report["registered_pruned_unsteady"] = [
                str(number).zfill(2)
                for number in repair["prune_unsteady_numbers"]
            ]
            report["validated_dss_pathnames"] = validated_pathnames
            return persist_repair_report(report)

        if repair_type == "replace_unsteady_dependency":
            unsteady_number = str(repair["unsteady_number"]).zfill(2)
            matching = ras_obj.unsteady_df.loc[
                ras_obj.unsteady_df["unsteady_number"] == unsteady_number
            ]
            if len(matching) != 1:
                raise RuntimeError(
                    "Registered ScienceBase dependency repair expected exactly "
                    f"one unsteady-flow file {unsteady_number}, found {len(matching)}."
                )

            target_file = Path(matching.iloc[0]["full_path"])
            old_bytes = str(repair["old_text"]).encode("ascii")
            new_bytes = str(repair["new_text"]).encode("ascii")
            expected_count = int(repair["expected_occurrences"])
            payload = target_file.read_bytes()
            old_count = payload.count(old_bytes)
            new_count = payload.count(new_bytes)

            if old_count == expected_count and new_count == 0:
                replacement_path = project_file.parent / str(
                    repair["new_dependency"]
                )
                if not replacement_path.is_file():
                    raise RuntimeError(
                        "Registered ScienceBase dependency replacement is absent: "
                        f"{replacement_path}"
                    )
                updated = payload.replace(old_bytes, new_bytes)
                temporary = target_file.parent / f".{target_file.name}.repair.tmp"
                temporary.write_bytes(updated)
                temporary.replace(target_file)
                repair_status = "applied"
            elif old_count == 0 and new_count == expected_count:
                repair_status = "already_applied"
            else:
                raise RuntimeError(
                    "ScienceBase archive does not match the registered dependency "
                    f"repair profile for '{slug}': expected {expected_count} old "
                    f"references or {expected_count} repaired references, found "
                    f"{old_count} old and {new_count} repaired."
                )

            report = ScienceBaseValidation.inspect_project(
                project_file,
                info["ras_version"],
                model_slug=slug,
                archive_root=model_dir,
            )
            if not report["paths_validated"]:
                raise RuntimeError(
                    f"Registered repair for '{slug}' did not produce a portable "
                    f"project: {report['issues']}"
                )
            report["repair_status"] = repair_status
            report["replaced_dependency"] = {
                "unsteady_number": unsteady_number,
                "old": repair["old_text"],
                "new": repair["new_text"],
                "occurrences": expected_count,
            }
            return persist_repair_report(report)

        keep_plan = str(repair["keep_plan"]).zfill(2)
        keep_rows = ras_obj.plan_df.loc[ras_obj.plan_df["plan_number"] == keep_plan]
        if keep_rows.empty:
            raise RuntimeError(
                f"Registered retained plan {keep_plan} is absent from '{slug}'."
            )
        keep_row = keep_rows.iloc[0]
        for column in ("full_path", "Geom Path", "Flow Path"):
            path_value = keep_row.get(column)
            if (
                ScienceBaseValidation._has_value(path_value)
                and not Path(path_value).exists()
            ):
                raise RuntimeError(
                    f"Retained plan {keep_plan} has a missing {column}: {path_value}"
                )

        component_frames = {
            "Plan": (ras_obj.plan_df, "plan_number"),
            "Geom": (ras_obj.geom_df, "geom_number"),
            "Flow": (ras_obj.flow_df, "flow_number"),
            "Unsteady": (ras_obj.unsteady_df, "unsteady_number"),
        }
        discovered_missing = {
            file_type: sorted(
                str(row[number_column]).zfill(2)
                for _, row in frame.iterrows()
                if not Path(row["full_path"]).exists()
            )
            for file_type, (frame, number_column) in component_frames.items()
        }
        expected_missing = {
            file_type: sorted(str(number).zfill(2) for number in numbers)
            for file_type, numbers in repair["expected_missing"].items()
        }

        if not any(discovered_missing.values()):
            repair_status = "already_applied"
        else:
            if discovered_missing != expected_missing:
                raise RuntimeError(
                    "ScienceBase archive does not match the registered repair "
                    f"profile for '{slug}': expected {expected_missing}, found "
                    f"{discovered_missing}"
                )
            for file_type, numbers in discovered_missing.items():
                for number in numbers:
                    RasUtils.remove_prj_entry(
                        project_file,
                        file_type,
                        number,
                        ras_object=ras_obj,
                    )
            ras_obj.set_current_plan(keep_plan)
            repair_status = "applied"

        report = ScienceBaseValidation.inspect_project(
            project_file,
            info["ras_version"],
            model_slug=slug,
            archive_root=model_dir,
        )
        if not report["paths_validated"]:
            raise RuntimeError(
                f"Registered repair for '{slug}' did not produce a portable project: "
                f"{report['issues']}"
            )
        report["repair_status"] = repair_status
        report["removed_entries"] = discovered_missing
        return persist_repair_report(report)

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        """Write a small delivery artifact without leaving a partial file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.tmp"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    @log_call
    def organize_model(
        model_key: str,
        base_dir: Path,
        *,
        strict: bool = False,
        archive_dir: Optional[Path] = None,
    ) -> dict:
        """Audit a ScienceBase extraction and create eBFE-style handoff artifacts.

        ScienceBase releases normally arrive with a coherent source hierarchy,
        so this workflow preserves that hierarchy instead of copying tens of
        gigabytes into a second standardized tree. The immutable source archive
        may remain beside the extracted tree or in the verified ``archive_dir``
        staging folder. ``MANIFEST.md`` and ``agent/`` reports document every
        discovered HEC-RAS project and all portable-path findings.
        """
        from ras_commander.sources.federal.sciencebase_validation import (
            ScienceBaseValidation,
        )

        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        model_dir = Path(base_dir) / slug
        if not model_dir.is_dir():
            raise FileNotFoundError(
                f"ScienceBase model folder does not exist: {model_dir}"
            )
        archive_root = Path(archive_dir) if archive_dir is not None else model_dir
        external_archive_staging = archive_dir is not None

        agent_dir = model_dir / "agent"
        repair_report_path = agent_dir / "repair_report.json"
        report_path = agent_dir / "sciencebase_archive_validation.json"
        report = ScienceBaseValidation.inspect_archive(
            model_dir,
            info["ras_version"],
            model_slug=slug,
            report_path=report_path,
        )

        def display_path(value: str) -> str:
            path = Path(value)
            try:
                return path.relative_to(model_dir).as_posix()
            except ValueError:
                return str(path)

        archive_rows = []
        for filename, file_info in info["files"].items():
            path = archive_root / filename
            expected = file_info.get("size_bytes")
            actual = path.stat().st_size if path.is_file() else None
            if expected is None:
                size_status = "present" if actual is not None else "not present"
            elif actual is None:
                size_status = f"missing (expected {int(expected):,} bytes)"
            elif actual == int(expected):
                location = " external staging" if external_archive_staging else ""
                size_status = f"verified{location} ({actual:,} bytes)"
            else:
                size_status = (
                    f"size mismatch ({actual:,} of {int(expected):,} bytes)"
                )
            archive_rows.append(
                (filename, "required" if file_info["required"] else "optional", size_status)
            )

        project_rows = []
        for project in report["projects"]:
            counts = project["component_counts"]
            project_rows.append(
                (
                    display_path(project["project_file"]),
                    str(counts.get("plan", 0)),
                    str(counts.get("geometry", 0)),
                    str(len(project.get("runnable_plans", []))),
                    "passed" if project["paths_validated"] else "failed",
                )
            )

        audit_artifacts = [
            "- `agent/model_log.md`",
            "- `agent/validation_report.md`",
            "- `agent/sciencebase_archive_validation.json`",
        ]
        if repair_report_path.is_file():
            audit_artifacts.append("- `agent/repair_report.json`")

        manifest_lines = [
            f"# {info['name']} — ScienceBase Delivery Manifest",
            "",
            f"- ScienceBase item: https://www.sciencebase.gov/catalog/item/{info['sciencebase_id']}",
            f"- DOI: {info.get('doi') or 'not listed'}",
            f"- HEC-RAS version: {info['ras_version']}",
            "- Organization mode: source hierarchy preserved in place",
            "- Source archives: retained unchanged in "
            + (
                "verified external staging"
                if external_archive_staging
                else "the extracted working tree"
            ),
            f"- Path-audit status: {report['status']}",
            f"- HEC-RAS projects discovered: {report['project_count']}",
            "",
            "## ScienceBase Attachments",
            "",
            "| Attachment | Role | Local status |",
            "|---|---:|---|",
            *[f"| `{name}` | {role} | {status} |" for name, role, status in archive_rows],
            "",
            "## HEC-RAS Projects",
            "",
            "| Project | Plans | Geometries | Runnable plans | Path audit |",
            "|---|---:|---:|---:|---|",
        ]
        if project_rows:
            manifest_lines.extend(
                f"| `{project}` | {plans} | {geometries} | {runnable} | {status} |"
                for project, plans, geometries, runnable, status in project_rows
            )
        else:
            manifest_lines.append("| _No HEC-RAS projects discovered_ | 0 | 0 | 0 | failed |")
        manifest_lines.extend(
            [
                "",
            "## Audit Artifacts",
            "",
            *audit_artifacts,
            "",
        ]
        )

        validation_lines = [
            f"# Path Validation — {info['name']}",
            "",
            f"- Status: **{report['status']}**",
            f"- Projects: {report['project_count']}",
            f"- Issues: {report['issue_count']}",
            f"- Inspected: {report['inspected_at']}",
            "",
        ]
        if report["issues"]:
            validation_lines.extend(["## Issues", ""])
            validation_lines.extend(
                "- `{code}` `{kind}` in `{project}`: `{path}`".format(
                    code=issue["code"],
                    kind=issue["kind"],
                    project=display_path(issue["project_file"]),
                    path=issue.get("path", ""),
                )
                for issue in report["issues"]
            )
        else:
            validation_lines.extend(
                [
                    "All plan, geometry, flow, DSS, restart, gridded meteorology, "
                    "terrain, land-classification, and projection references "
                    "resolved within the ScienceBase delivery.",
                    "",
                ]
            )

        repair_log_line = (
            "- Repairs: none applied by organization; any later repair must be "
            "recorded here and performed only in the extracted working tree."
        )
        if repair_report_path.is_file():
            try:
                repair_report = json.loads(
                    repair_report_path.read_text(encoding="utf-8")
                )
                repair_log_line = (
                    "- Registered repair: "
                    f"`{repair_report.get('repair_status', 'unknown')}`; evidence "
                    "is recorded in `agent/repair_report.json`."
                )
            except (OSError, json.JSONDecodeError):
                repair_log_line = (
                    "- Registered repair artifact exists but could not be parsed: "
                    "`agent/repair_report.json`."
                )

        log_lines = [
            f"# Model Log — {info['name']}",
            "",
            f"- Source: USGS ScienceBase item `{info['sciencebase_id']}`",
            f"- DOI: `{info.get('doi') or 'not listed'}`",
            f"- Working folder: `{model_dir}`",
            "- Organization decision: preserve the published source hierarchy; "
            "do not duplicate the large delivery into a second folder tree.",
            "- Immutable evidence: downloaded archives remain unchanged.",
            "- Validation method: initialize every project independently with "
            "`RasPrj` and audit RAS Commander DataFrames plus RasMap and "
            "RasUnsteady dependencies.",
            f"- Current path-audit status: `{report['status']}`.",
            repair_log_line,
            "",
        ]

        UsgsScienceBase._write_text_atomic(
            model_dir / "MANIFEST.md",
            "\n".join(manifest_lines),
        )
        UsgsScienceBase._write_text_atomic(
            agent_dir / "validation_report.md",
            "\n".join(validation_lines),
        )
        UsgsScienceBase._write_text_atomic(
            agent_dir / "model_log.md",
            "\n".join(log_lines),
        )
        report["artifacts"] = {
            "manifest": str(model_dir / "MANIFEST.md"),
            "model_log": str(agent_dir / "model_log.md"),
            "validation_report": str(agent_dir / "validation_report.md"),
            "validation_json": str(report_path),
        }
        if repair_report_path.is_file():
            report["artifacts"]["repair_report"] = str(repair_report_path)
        # ``inspect_archive`` writes the initial JSON before the human-readable
        # handoff files exist. Rewrite it once so the machine-readable report
        # contains the same complete artifact inventory returned to callers.
        UsgsScienceBase._write_text_atomic(
            report_path,
            json.dumps(report, indent=2, default=str),
        )
        if strict and not report["paths_validated"]:
            raise RuntimeError(
                f"ScienceBase delivery '{slug}' failed path validation; see "
                f"{agent_dir / 'validation_report.md'}"
            )
        return report

    @staticmethod
    @log_call
    def inspect_local_model(
        model_key: str,
        base_dir: Path,
        *,
        project_file: Optional[Path] = None,
        ras_version: Optional[str] = None,
    ) -> dict:
        """Inspect a local candidate archive for missing or nonportable paths."""
        from ras_commander.sources.federal.sciencebase_validation import (
            ScienceBaseValidation,
        )

        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        version = ras_version or info.get("ras_version")
        if not version:
            raise ValueError(f"No HEC-RAS version is registered for '{slug}'.")
        if project_file is None:
            return ScienceBaseValidation.inspect_archive(
                Path(base_dir) / slug,
                version,
                model_slug=slug,
            )
        return ScienceBaseValidation.inspect_project(
            Path(project_file),
            version,
            model_slug=slug,
            archive_root=Path(base_dir) / slug,
        )

    @staticmethod
    @log_call
    def run_validation_plan(
        model_key: str,
        base_dir: Path,
        plan_number: str,
        output_dir: Path,
        *,
        project_file: Optional[Path] = None,
        ras_version: Optional[str] = None,
        num_cores: int = 4,
    ) -> dict:
        """Run a fresh representative plan after portable-path inspection."""
        from ras_commander.sources.federal.sciencebase_validation import (
            ScienceBaseValidation,
        )

        slug = UsgsScienceBase.normalize_model_key(model_key)
        info = UsgsScienceBase._MODEL_REGISTRY[slug]
        project_file = (
            Path(project_file)
            if project_file is not None
            else UsgsScienceBase.get_project_path(slug, base_dir)
        )
        version = ras_version or info.get("ras_version")
        if not version:
            raise ValueError(f"No HEC-RAS version is registered for '{slug}'.")
        return ScienceBaseValidation.run_verified_compute(
            project_file,
            version,
            plan_number,
            output_dir,
            model_slug=slug,
            archive_root=Path(base_dir) / slug,
            num_cores=num_cores,
        )

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
        show_progress: bool = False,
    ) -> Dict[str, dict]:
        """Search ScienceBase with paginated keyword queries."""
        if queries is None:
            queries = UsgsScienceBase._DEFAULT_KEYWORD_QUERIES
        if seen_ids is None:
            seen_ids = set()
        results: Dict[str, dict] = {}

        for query in UsgsScienceBase._progress(
            queries, desc="Keyword search", unit="query", show_progress=show_progress,
        ):
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
        show_progress: bool = False,
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

        for state, state_sites in UsgsScienceBase._progress(
            by_state.items(), desc="FIM cross-ref", unit="state",
            show_progress=show_progress,
        ):
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
            show_progress=False,
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
        show_progress: bool = False,
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

        for sb_id, parent in UsgsScienceBase._progress(
            parents_with_children.items(), desc="Child traversal", unit="parent",
            show_progress=show_progress,
        ):
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
        show_progress: bool = False,
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
            verbose: If True, log summary statistics at INFO.
            show_progress: If True, show discovery progress bars.

        Returns:
            Dict keyed by sciencebase_id, each value a candidate model dict.
        """
        all_strategies = ["keyword", "fim", "alternate", "children"]
        active = strategies if strategies else all_strategies
        seen_ids: Set[str] = set()
        all_candidates: Dict[str, dict] = {}
        errors: List[str] = []

        strategy_bar = UsgsScienceBase._progress(
            active, desc="Discovery strategies", unit="strategy",
            show_progress=show_progress,
        )

        for strategy in strategy_bar:
            strategy_bar.set_postfix(current=strategy, found=len(all_candidates))
            try:
                if strategy == "keyword":
                    found = UsgsScienceBase._discover_keyword_search(
                        max_results_per_query=max_results_per_query,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                        show_progress=show_progress,
                    )
                elif strategy == "fim":
                    found = UsgsScienceBase._discover_fim_sites(
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                        show_progress=show_progress,
                    )
                elif strategy == "alternate":
                    found = UsgsScienceBase._discover_keyword_search(
                        queries=UsgsScienceBase._ALTERNATE_KEYWORD_QUERIES,
                        max_results_per_query=max_results_per_query,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                        show_progress=show_progress,
                    )
                elif strategy == "children":
                    found = UsgsScienceBase._discover_children(
                        parent_candidates=all_candidates,
                        cache_dir=cache_dir,
                        request_delay=request_delay,
                        seen_ids=seen_ids,
                        show_progress=show_progress,
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
            logger.info(
                "Discovered %d candidate ScienceBase models by type=%s, confidence=%s",
                len(all_candidates), by_type, by_conf,
            )
            if errors:
                logger.info("ScienceBase discovery completed with %d error(s)", len(errors))

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
