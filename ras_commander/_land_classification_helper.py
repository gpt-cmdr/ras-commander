"""Internal helpers for RasMap land-classification workflows.

This module keeps pythonnet / RasMapperLib interop lazy and private to the
RasMap implementation. It is intentionally not exported from
``ras_commander.__init__``.
"""

from __future__ import annotations

import math
import os
import platform
import re
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Optional, Union

import h5py
import numpy as np
import pandas as pd

from .LoggingConfig import get_logger
from .RasUtils import RasUtils

logger = get_logger(__name__)

_WINDOWS_ENV_VAR_PATTERN = re.compile(r"%([^%]+)%")

_HECRAS_SEARCH_PATHS = [
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5"),
    Path(r"C:\Program Files\HEC\HEC-RAS\6.6"),
]

_DLL_DEPENDENCIES = [
    "Utility.Core",
    "Geospatial.Core",
    "Geospatial.GDALAssist",
    "H5Assist",
    "RasMapperLib",
]

_REQUIRED_CLASSIFICATION_COLUMNS = [
    "source_value",
    "class_id",
    "class_name",
    "mannings_n",
]
_OPTIONAL_CLASSIFICATION_COLUMNS = [
    "percent_impervious",
]

_RESOURCE_DIR = (
    Path(__file__).resolve().parent / "resources" / "land_classification"
)
_LANDCOVER_TEMPLATE_FILENAME = "landcover_template.hdf"
_SOILS_TEMPLATE_FILENAME = "soils_template.hdf"

_LANDCOVER_DEFAULT_RELATIVE_PATH = Path("Land Classification") / "LandCover.hdf"
_SOILS_DEFAULT_RELATIVE_PATH = Path("Soils Data") / "Hydrologic Soil Groups.hdf"
_INFILTRATION_DEFAULT_RELATIVE_PATH = Path("Soils Data") / "Infiltration.hdf"

_DEFAULT_LANDCOVER_NODATA_MANNINGS_N = 0.035
_DEFAULT_LANDCOVER_NODATA_PERCENT_IMPERVIOUS = 0.0
_DEFAULT_SCS_RESET_TIME_HOURS = 24.0
_DEFAULT_SCS_MIN_INFILTRATION_RATE = 0.12
_DEFAULT_DEFICIT_CONSTANT_NO_DATA = {
    "Maximum Deficit": 0.30,
    "Initial Deficit": 0.15,
    "Potential Percolation Rate": 0.10,
}
_DEFAULT_GREEN_AMPT_NO_DATA = {
    "Wetting Front Suction": 7.25,
    "Saturated Hydraulic Conductivity": 0.20,
    "Initial Soil Water Content": 0.22,
    "Saturated Soil Water Content": 0.46,
}

_STANDARD_SOIL_GROUP_ORDER = [
    "A",
    "B",
    "C",
    "D",
    "A-D",
    "B-D",
    "C-D",
]

_dlls_loaded = False

_SCS_CATEGORY_TABLES: dict[str, dict[str, Any]] = {
    "nodata": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 75.0,
            "A": 75.0,
            "B": 75.0,
            "C": 75.0,
            "D": 75.0,
            "A-D": 75.0,
            "B-D": 75.0,
            "C-D": 75.0,
        },
    },
    "water": {
        "abstraction_ratio": 0.0,
        "curve_numbers": {
            "NoData": 100.0,
            "A": 100.0,
            "B": 100.0,
            "C": 100.0,
            "D": 100.0,
            "A-D": 100.0,
            "B-D": 100.0,
            "C-D": 100.0,
        },
    },
    "forest_dense": {
        "abstraction_ratio": 0.2,
        "curve_numbers": {
            "NoData": 79.0,
            "A": 36.0,
            "B": 60.0,
            "C": 73.0,
            "D": 79.0,
            "A-D": 79.0,
            "B-D": 60.0,
            "C-D": 79.0,
        },
    },
    "forest_deciduous": {
        "abstraction_ratio": 0.2,
        "curve_numbers": {
            "NoData": 70.0,
            "A": 45.0,
            "B": 66.0,
            "C": 77.0,
            "D": 83.0,
            "A-D": 77.0,
            "B-D": 66.0,
            "C-D": 77.0,
        },
    },
    "developed": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 84.0,
            "A": 49.0,
            "B": 69.0,
            "C": 79.0,
            "D": 84.0,
            "A-D": 79.0,
            "B-D": 69.0,
            "C-D": 79.0,
        },
    },
    "shrub_grass_pasture": {
        "abstraction_ratio": 0.2,
        "curve_numbers": {
            "NoData": 73.0,
            "A": 73.0,
            "B": 73.0,
            "C": 73.0,
            "D": 73.0,
            "A-D": 73.0,
            "B-D": 73.0,
            "C-D": 73.0,
        },
    },
    "crops": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 91.0,
            "A": 72.0,
            "B": 81.0,
            "C": 88.0,
            "D": 91.0,
            "A-D": 88.0,
            "B-D": 81.0,
            "C-D": 88.0,
        },
    },
    "wetlands_emergent": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 95.0,
            "A": 95.0,
            "B": 95.0,
            "C": 95.0,
            "D": 95.0,
            "A-D": 95.0,
            "B-D": 95.0,
            "C-D": 95.0,
        },
    },
    "wetlands_woody": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 90.0,
            "A": 75.0,
            "B": 80.0,
            "C": 85.0,
            "D": 90.0,
            "A-D": 85.0,
            "B-D": 75.0,
            "C-D": 85.0,
        },
    },
    "barren": {
        "abstraction_ratio": 0.1,
        "curve_numbers": {
            "NoData": 79.0,
            "A": 79.0,
            "B": 79.0,
            "C": 79.0,
            "D": 79.0,
            "A-D": 79.0,
            "B-D": 79.0,
            "C-D": 79.0,
        },
    },
}

_DEFICIT_CONSTANT_DEFAULTS_BY_SOIL_GROUP: dict[str, dict[str, float]] = {
    "A": {
        "Maximum Deficit": 0.45,
        "Initial Deficit": 0.23,
        "Potential Percolation Rate": 0.375,
    },
    "B": {
        "Maximum Deficit": 0.35,
        "Initial Deficit": 0.18,
        "Potential Percolation Rate": 0.225,
    },
    "C": {
        "Maximum Deficit": 0.25,
        "Initial Deficit": 0.13,
        "Potential Percolation Rate": 0.10,
    },
    "D": {
        "Maximum Deficit": 0.15,
        "Initial Deficit": 0.08,
        "Potential Percolation Rate": 0.025,
    },
}

_GREEN_AMPT_DEFAULTS_BY_SOIL_GROUP: dict[str, dict[str, float]] = {
    "A": {
        "Wetting Front Suction": 2.5,
        "Saturated Hydraulic Conductivity": 1.80,
        "Initial Soil Water Content": 0.10,
        "Saturated Soil Water Content": 0.41,
    },
    "B": {
        "Wetting Front Suction": 6.0,
        "Saturated Hydraulic Conductivity": 0.30,
        "Initial Soil Water Content": 0.20,
        "Saturated Soil Water Content": 0.46,
    },
    "C": {
        "Wetting Front Suction": 8.5,
        "Saturated Hydraulic Conductivity": 0.10,
        "Initial Soil Water Content": 0.24,
        "Saturated Soil Water Content": 0.46,
    },
    "D": {
        "Wetting Front Suction": 10.5,
        "Saturated Hydraulic Conductivity": 0.03,
        "Initial Soil Water Content": 0.28,
        "Saturated Soil Water Content": 0.43,
    },
}


@dataclass(frozen=True)
class LandClassificationProjectPaths:
    """Resolved project paths used by land-classification workflows."""

    project_path: Path
    project_folder: Path
    project_name: str
    prj_path: Path
    rasmap_path: Path
    projection_path: Optional[Path]


def empty_rasmap_dataframe() -> pd.DataFrame:
    """Return the default single-row RasMap dataframe shape."""
    return pd.DataFrame(
        {
            "projection_path": [None],
            "profile_lines_path": [[]],
            "soil_layer_path": [[]],
            "infiltration_hdf_path": [[]],
            "landcover_hdf_path": [[]],
            "terrain_hdf_path": [[]],
            "reference_map_layer_names": [[]],
            "reference_map_layer_path": [[]],
            "basemap_layer_names": [[]],
            "basemap_layer_path": [[]],
            "current_settings": [{}],
        }
    )


def _find_hecras_dir() -> Path:
    for candidate in _HECRAS_SEARCH_PATHS:
        if (candidate / "RasMapperLib.dll").exists():
            return candidate
    raise FileNotFoundError(
        "HEC-RAS with RasMapperLib.dll not found. Searched: "
        + ", ".join(str(path) for path in _HECRAS_SEARCH_PATHS)
    )


def _load_dlls(hecras_dir: Optional[Union[str, Path]] = None) -> None:
    """Load RasMapperLib and dependencies lazily via pythonnet."""
    global _dlls_loaded

    if _dlls_loaded:
        return

    if platform.system() != "Windows":
        raise RuntimeError(
            "Land-classification interop requires Windows "
            "(RasMapperLib.dll is Windows-only)."
        )

    try:
        import clr  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "pythonnet is required for RasMap land-classification interop. "
            "Install pythonnet before calling the generation / recompute APIs."
        ) from exc

    hecras_dir = Path(hecras_dir) if hecras_dir is not None else _find_hecras_dir()

    from .geom.GeomMesh import GeomMesh

    GeomMesh.setup_gdal_bridge(hecras_dir=hecras_dir, create_junction=True)

    if str(hecras_dir) not in sys.path:
        sys.path.insert(0, str(hecras_dir))

    for dependency in _DLL_DEPENDENCIES:
        dll_path = hecras_dir / f"{dependency}.dll"
        try:
            clr.AddReference(str(dll_path))
        except Exception as exc:  # pragma: no cover - depends on local install
            if dependency == "RasMapperLib":
                raise RuntimeError(
                    f"Failed to load required HEC-RAS assembly: {dll_path}"
                ) from exc
            logger.warning("Could not load %s: %s", dll_path.name, exc)

    _dlls_loaded = True
    logger.debug("Land-classification RasMapperLib dependencies loaded")


def get_interop_namespace(
    hecras_dir: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    """Return confirmed RasMapperLib / GDALAssist types for future workflows."""
    _load_dlls(hecras_dir)

    from Geospatial.GDALAssist import Projection  # type: ignore
    from RasMapperLib import (  # type: ignore
        Extent,
        LandCoverComputable,
        LandCoverFile,
        LandCoverLayer,
        LandCoverLayerHelper,
        SsurgoLayer,
    )
    from RasMapperLib.Scripting import (  # type: ignore
        CompleteGeometryCommand,
        ComputePropertyTablesCommand,
        SetGeometryAssociationCommand,
    )
    from System.Collections.Generic import Dictionary, List  # type: ignore

    return {
        "Projection": Projection,
        "Extent": Extent,
        "LandCoverComputable": LandCoverComputable,
        "LandCoverFile": LandCoverFile,
        "LandCoverLayer": LandCoverLayer,
        "LandCoverLayerHelper": LandCoverLayerHelper,
        "SsurgoLayer": SsurgoLayer,
        "CompleteGeometryCommand": CompleteGeometryCommand,
        "ComputePropertyTablesCommand": ComputePropertyTablesCommand,
        "SetGeometryAssociationCommand": SetGeometryAssociationCommand,
        "DotNetDictionary": Dictionary,
        "DotNetList": List,
    }


def _find_project_file(project_folder: Path) -> Optional[Path]:
    """Find the HEC-RAS project file and ignore ESRI projection files."""
    for prj_path in sorted(project_folder.glob("*.prj")):
        try:
            first_line = prj_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[0]
        except (IndexError, OSError):
            continue
        if first_line.startswith("Proj Title="):
            return prj_path
    return None


def resolve_rasmap_relative_path(
    project_folder: Union[str, Path],
    filename: Optional[Union[str, Path]],
) -> Optional[Path]:
    """Resolve a filename from .rasmap XML to an absolute filesystem path."""
    if filename in (None, ""):
        return None

    project_folder = RasUtils.safe_resolve(Path(project_folder))
    original_filename_str = str(filename).strip()
    filename_str = _WINDOWS_ENV_VAR_PATTERN.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)),
        original_filename_str,
    ).strip()
    path = PureWindowsPath(filename_str.replace("/", "\\"))

    if path.is_absolute():
        resolved = Path(str(path))
        if os.name == "nt":
            return RasUtils.safe_resolve(resolved)
        return resolved

    if (
        original_filename_str.startswith("%")
        and _WINDOWS_ENV_VAR_PATTERN.search(filename_str)
    ):
        return Path(filename_str)

    relative_str = filename_str.replace("/", "\\")
    if relative_str.startswith(".\\") or relative_str.startswith("./"):
        relative_str = relative_str[2:]

    relative_path = Path(*PureWindowsPath(relative_str).parts)
    return RasUtils.safe_resolve(project_folder / relative_path)


def to_rasmap_relative_path(
    project_folder: Union[str, Path],
    target_path: Union[str, Path],
) -> str:
    """Format an absolute path as a RAS Mapper-style relative path when possible."""
    project_folder = RasUtils.safe_resolve(Path(project_folder))
    target_path = RasUtils.safe_resolve(Path(target_path))

    try:
        relative_path = target_path.relative_to(project_folder)
        return ".\\" + str(relative_path).replace("/", "\\")
    except ValueError:
        return str(target_path).replace("/", "\\")


def _extract_projection_path(rasmap_path: Path) -> Optional[Path]:
    if not rasmap_path.exists():
        return None

    try:
        root = ET.parse(rasmap_path).getroot()
    except ET.ParseError:
        return None

    projection_elem = root.find(".//RASProjectionFilename")
    if projection_elem is None:
        return None

    return resolve_rasmap_relative_path(
        rasmap_path.parent,
        projection_elem.attrib.get("Filename"),
    )


def resolve_project_paths(
    ras_project_path: Union[str, Path],
) -> LandClassificationProjectPaths:
    """Resolve project folder, project name, rasmap, and projection paths."""
    project_path = Path(ras_project_path)

    if project_path.is_dir():
        project_folder = RasUtils.safe_resolve(project_path)
        prj_path = _find_project_file(project_folder)
        if prj_path is None:
            raise FileNotFoundError(
                f"No HEC-RAS .prj file found in project folder: {project_folder}"
            )
        project_name = prj_path.stem
        rasmap_path = project_folder / f"{project_name}.rasmap"
    elif project_path.suffix.lower() == ".prj":
        prj_path = RasUtils.safe_resolve(project_path)
        project_folder = prj_path.parent
        project_name = prj_path.stem
        rasmap_path = project_folder / f"{project_name}.rasmap"
    elif project_path.suffix.lower() == ".rasmap":
        rasmap_path = RasUtils.safe_resolve(project_path)
        project_folder = rasmap_path.parent
        project_name = rasmap_path.stem
        prj_path = project_folder / f"{project_name}.prj"
    else:
        raise ValueError(
            "ras_project_path must be a project folder, .prj file, or .rasmap file. "
            f"Received: {project_path}"
        )

    projection_path = _extract_projection_path(rasmap_path)

    return LandClassificationProjectPaths(
        project_path=project_path,
        project_folder=project_folder,
        project_name=project_name,
        prj_path=prj_path,
        rasmap_path=rasmap_path,
        projection_path=projection_path,
    )


def build_default_output_path(
    project_folder: Union[str, Path],
    relative_output_path: Union[str, Path],
) -> Path:
    """Build and create a default output path under the project folder."""
    output_path = Path(project_folder) / Path(relative_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return RasUtils.safe_resolve(output_path)


def require_projection_path(
    project_paths: LandClassificationProjectPaths,
) -> Path:
    """Require a usable projection path from the project .rasmap."""
    if (
        project_paths.projection_path is None
        or not project_paths.projection_path.exists()
    ):
        raise FileNotFoundError(
            "Project .rasmap does not contain a usable projection path. "
            f"Expected from: {project_paths.rasmap_path}"
        )
    return project_paths.projection_path


def normalize_restrict_to_extent(
    restrict_to_extent: Any,
    extent_cls: Any = None,
) -> Any:
    """Normalize restrict_to_extent to bounds tuple or RasMapperLib.Extent."""
    if restrict_to_extent is None:
        return None

    if hasattr(restrict_to_extent, "MinX") and hasattr(restrict_to_extent, "MaxX"):
        return restrict_to_extent

    bounds: Optional[tuple[float, float, float, float]] = None

    if isinstance(restrict_to_extent, dict):
        left = restrict_to_extent.get("left", restrict_to_extent.get("xmin"))
        bottom = restrict_to_extent.get("bottom", restrict_to_extent.get("ymin"))
        right = restrict_to_extent.get("right", restrict_to_extent.get("xmax"))
        top = restrict_to_extent.get("top", restrict_to_extent.get("ymax"))
        bounds = (left, bottom, right, top)
    elif isinstance(restrict_to_extent, (list, tuple)) and len(restrict_to_extent) == 4:
        bounds = tuple(restrict_to_extent)
    else:
        for attrs in (
            ("left", "bottom", "right", "top"),
            ("xmin", "ymin", "xmax", "ymax"),
            ("minx", "miny", "maxx", "maxy"),
        ):
            if all(hasattr(restrict_to_extent, attr) for attr in attrs):
                bounds = tuple(getattr(restrict_to_extent, attr) for attr in attrs)
                break

    if bounds is None:
        raise ValueError(
            "restrict_to_extent must be a 4-tuple/list, a dict with xmin/ymin/xmax/ymax "
            "or left/bottom/right/top, or an object exposing those attributes."
        )

    left, bottom, right, top = (float(value) for value in bounds)
    if extent_cls is None:
        return (left, bottom, right, top)
    return extent_cls(left, bottom, right, top)


def normalize_gssurgo_path(gssurgo_path: Union[str, Path]) -> Path:
    """Normalize GSSURGO input to the directory shape expected by SsurgoLayer."""
    gssurgo_path = Path(gssurgo_path)
    if not gssurgo_path.exists():
        raise FileNotFoundError(f"GSSURGO path not found: {gssurgo_path}")

    if gssurgo_path.suffix.lower() == ".gdb" and gssurgo_path.is_dir():
        return RasUtils.safe_resolve(gssurgo_path)

    if gssurgo_path.is_dir():
        geodatabases = sorted(gssurgo_path.glob("*.gdb"))
        if len(geodatabases) == 1:
            return RasUtils.safe_resolve(geodatabases[0])
        if (gssurgo_path / "spatial").exists() and (gssurgo_path / "tabular").exists():
            return RasUtils.safe_resolve(gssurgo_path)

    return RasUtils.safe_resolve(gssurgo_path)


def normalize_classification_table(
    classification_table: Union[pd.DataFrame, str, Path],
) -> pd.DataFrame:
    """Normalize land-cover classification input to the v1 dataframe contract."""
    if isinstance(classification_table, pd.DataFrame):
        df = classification_table.copy()
    else:
        table_path = Path(classification_table)
        if not table_path.exists():
            raise FileNotFoundError(f"Classification table not found: {table_path}")

        suffix = table_path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(table_path)
        elif suffix in {".tsv", ".txt"}:
            df = pd.read_csv(table_path, sep="\t")
        elif suffix in {".xls", ".xlsx"}:
            df = pd.read_excel(table_path)
        elif suffix == ".json":
            df = pd.read_json(table_path)
        elif suffix == ".parquet":
            df = pd.read_parquet(table_path)
        else:
            raise ValueError(
                "Unsupported classification table format. "
                "Use DataFrame, CSV, TSV, Excel, JSON, or Parquet."
            )

    df.columns = [str(column).strip() for column in df.columns]

    missing_columns = [
        column
        for column in _REQUIRED_CLASSIFICATION_COLUMNS
        if column not in df.columns
    ]
    if missing_columns:
        raise ValueError(
            "Classification table missing required columns: "
            + ", ".join(missing_columns)
        )

    ordered_columns = _REQUIRED_CLASSIFICATION_COLUMNS + [
        column
        for column in _OPTIONAL_CLASSIFICATION_COLUMNS
        if column in df.columns
    ]
    df = df.loc[:, ordered_columns].copy()

    if df["source_value"].isna().any():
        raise ValueError("classification_table.source_value cannot contain null values")
    if df["class_name"].isna().any():
        raise ValueError("classification_table.class_name cannot contain null values")
    if df["source_value"].duplicated().any():
        raise ValueError("classification_table.source_value values must be unique")
    if df["class_id"].duplicated().any():
        raise ValueError("classification_table.class_id values must be unique")
    if df["class_name"].duplicated().any():
        raise ValueError("classification_table.class_name values must be unique")

    df["class_id"] = pd.to_numeric(df["class_id"], errors="raise").astype(int)
    if (df["class_id"] <= 0).any():
        raise ValueError("classification_table.class_id values must be positive integers")
    df["mannings_n"] = pd.to_numeric(df["mannings_n"], errors="raise").astype(float)
    if "percent_impervious" in df.columns:
        df["percent_impervious"] = pd.to_numeric(
            df["percent_impervious"],
            errors="raise",
        ).astype(float)
    else:
        df["percent_impervious"] = 0.0

    return df.reset_index(drop=True)


def resolve_geometry_hdf_path(
    project_paths: LandClassificationProjectPaths,
    geom_file: Union[str, Path],
    ras_object: Any = None,
) -> Path:
    """Resolve a geometry input to the compiled ``.g##.hdf`` path."""
    geom_file = Path(geom_file)

    ras_geom_df = getattr(ras_object, "geom_df", None)
    if ras_geom_df is not None and not ras_geom_df.empty:
        geom_token = str(geom_file).strip().lower()
        for _, row in ras_geom_df.iterrows():
            candidates = {
                str(row.get("geom_number", "")).strip().lower(),
                str(row.get("geom_file", "")).strip().lower(),
                str(Path(str(row.get("full_path", ""))).name).strip().lower(),
                str(Path(str(row.get("hdf_path", ""))).name).strip().lower(),
                str(Path(str(row.get("full_path", "")))).strip().lower(),
                str(Path(str(row.get("hdf_path", "")))).strip().lower(),
            }
            if geom_token in candidates:
                hdf_path = Path(str(row.get("hdf_path", "")))
                if hdf_path.exists():
                    return RasUtils.safe_resolve(hdf_path)

    candidates = []

    if geom_file.is_absolute():
        candidates.append(geom_file)
    else:
        candidates.append(project_paths.project_folder / geom_file)

    geom_name = geom_file.name.lower()
    if re.fullmatch(r"g\d{2}", geom_name):
        candidates.extend(project_paths.project_folder.glob(f"*.{geom_name}"))
        candidates.extend(project_paths.project_folder.glob(f"*.{geom_name}.hdf"))

    expanded_candidates = []
    for candidate in candidates:
        expanded_candidates.append(candidate)
        if candidate.suffix.lower() != ".hdf":
            expanded_candidates.append(Path(str(candidate) + ".hdf"))

    for candidate in expanded_candidates:
        if candidate.exists():
            resolved = RasUtils.safe_resolve(candidate)
            if resolved.suffix.lower() == ".hdf":
                return resolved
            hdf_candidate = Path(str(resolved) + ".hdf")
            if hdf_candidate.exists():
                return RasUtils.safe_resolve(hdf_candidate)

    raise FileNotFoundError(
        f"Could not resolve geometry HDF for '{geom_file}' under {project_paths.project_folder}"
    )


def get_selected_parameter(layer_elem: ET.Element) -> Optional[str]:
    """Extract the selected parameter label from a LandCoverLayer XML element."""
    parameter = layer_elem.attrib.get("SelectedParameterForSurfaceFillLabel")
    if parameter:
        return parameter

    parameter_elem = layer_elem.find("SelectedParameterForSurfaceFillLabel")
    if parameter_elem is not None and parameter_elem.text:
        return parameter_elem.text.strip()

    return None


def infer_land_classification_kind(
    filename: Optional[Union[str, Path]],
    selected_parameter: Optional[str],
) -> str:
    """Classify a RasMapper LandCoverLayer using filename and parameter semantics."""
    filename_str = str(filename or "").replace("\\", "/").lower()
    parameter = str(selected_parameter or "").strip().lower()

    if "infiltration" in filename_str:
        return "infiltration"
    if any(token in filename_str for token in ("soil", "ssurgo", "gssurgo")):
        return "soils"
    if parameter in {"manningsn", "percent impervious"}:
        return "landcover"
    if any(token in filename_str for token in ("landcover", "land classification")):
        return "landcover"
    if parameter == "id":
        return "landcover"
    return "unknown"


def build_land_classification_record(
    layer_elem: ET.Element,
    project_folder: Union[str, Path],
) -> dict[str, Any]:
    """Build a semantic layer record for list_land_classification_layers()."""
    filename = layer_elem.attrib.get("Filename")
    selected_parameter = get_selected_parameter(layer_elem)
    classification_layers = [
        child
        for child in layer_elem.findall("Layer")
        if child.attrib.get("Type") == "LandCoverClassificationLayer"
    ]

    resolved_path = resolve_rasmap_relative_path(project_folder, filename)

    return {
        "name": layer_elem.attrib.get("Name", ""),
        "type": layer_elem.attrib.get("Type", ""),
        "checked": layer_elem.attrib.get("Checked", "True").lower() == "true",
        "filename": filename,
        "resolved_path": str(resolved_path) if resolved_path is not None else None,
        "selected_parameter": selected_parameter,
        "classification_kind": infer_land_classification_kind(
            filename,
            selected_parameter,
        ),
        "classification_layer_count": len(classification_layers),
        "classification_layer_filenames": [
            child.attrib.get("Filename") for child in classification_layers
        ],
        "classification_layer_paths": [
            str(
                resolve_rasmap_relative_path(
                    project_folder,
                    child.attrib.get("Filename"),
                )
            )
            if child.attrib.get("Filename")
            else None
            for child in classification_layers
        ],
    }


def _get_project_crs(project_paths: LandClassificationProjectPaths) -> Any:
    try:
        from pyproj import CRS
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "pyproj is required for land-classification generation. "
            "Install the raster / projection dependencies before calling this API."
        ) from exc

    projection_path = require_projection_path(project_paths)
    projection_wkt = projection_path.read_text(encoding="utf-8", errors="replace").strip()
    if not projection_wkt:
        raise ValueError(f"Projection file is empty: {projection_path}")
    return CRS.from_user_input(projection_wkt)


def _get_project_projection_wkt(project_paths: LandClassificationProjectPaths) -> str:
    projection_path = require_projection_path(project_paths)
    projection_wkt = projection_path.read_text(encoding="utf-8", errors="replace").strip()
    if not projection_wkt:
        raise ValueError(f"Projection file is empty: {projection_path}")
    return projection_wkt


def _snap_bounds_to_grid(
    bounds: tuple[float, float, float, float],
    cell_size: float,
) -> tuple[float, float, float, float]:
    left, bottom, right, top = bounds
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if right <= left or top <= bottom:
        raise ValueError(f"Invalid extent bounds: {bounds}")

    snapped_left = math.floor(left / cell_size) * cell_size
    snapped_bottom = math.floor(bottom / cell_size) * cell_size
    snapped_right = math.ceil(right / cell_size) * cell_size
    snapped_top = math.ceil(top / cell_size) * cell_size
    return (
        snapped_left,
        snapped_bottom,
        snapped_right,
        snapped_top,
    )


def _bounds_to_grid(
    bounds: tuple[float, float, float, float],
    cell_size: float,
) -> tuple[Any, int, int]:
    try:
        from rasterio.transform import from_origin
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "rasterio is required for land-classification generation. "
            "Install the raster dependencies before calling this API."
        ) from exc

    left, bottom, right, top = _snap_bounds_to_grid(bounds, cell_size)
    width = max(1, int(round((right - left) / cell_size)))
    height = max(1, int(round((top - bottom) / cell_size)))
    transform = from_origin(left, top, cell_size, cell_size)
    return transform, width, height


def _create_output_raster(
    output_tif_path: Path,
    array: np.ndarray,
    transform: Any,
    crs: Any,
) -> Path:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "rasterio is required for land-classification generation. "
            "Install the raster dependencies before calling this API."
        ) from exc

    output_tif_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_tif_path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=crs,
        transform=transform,
        nodata=0,
        compress="lzw",
    ) as dst:
        dst.write(array, 1)
    return RasUtils.safe_resolve(output_tif_path)


def _build_nodata_mask(array: np.ndarray, nodata_value: Any) -> np.ndarray:
    if nodata_value is None:
        if np.issubdtype(array.dtype, np.floating):
            return np.isnan(array)
        return np.zeros(array.shape, dtype=bool)

    try:
        if np.isnan(nodata_value):
            return np.isnan(array)
    except TypeError:
        pass

    return array == nodata_value


def _coerce_raster_lookup_value(value: Any, array: np.ndarray) -> Any:
    if np.issubdtype(array.dtype, np.integer):
        return int(float(value))
    if np.issubdtype(array.dtype, np.floating):
        return float(value)
    raise ValueError(
        "Raster classification source values must be numeric for raster inputs"
    )


def _rasterize_landcover_source(
    source_path: Path,
    classification_table: pd.DataFrame,
    cell_size: float,
    project_crs: Any,
    restrict_to_extent: Optional[Any],
    source_field: Optional[str],
) -> tuple[np.ndarray, Any, list[tuple[int, str]], list[tuple[str, float, float]]]:
    try:
        import geopandas as gpd
        import rasterio
        from rasterio import features
        from rasterio.warp import Resampling, reproject, transform_bounds
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "rasterio and geopandas are required for land-cover generation. "
            "Install the geospatial dependencies before calling this API."
        ) from exc

    restrict_bounds = normalize_restrict_to_extent(restrict_to_extent)

    raster_map_rows = [(0, "NoData")] + [
        (int(row.class_id), str(row.class_name))
        for row in classification_table.sort_values("class_id").itertuples()
    ]
    variable_rows = [("NoData", _DEFAULT_LANDCOVER_NODATA_MANNINGS_N, 0.0)] + [
        (
            str(row.class_name),
            float(row.mannings_n),
            float(row.percent_impervious),
        )
        for row in classification_table.sort_values("class_id").itertuples()
    ]

    if source_path.suffix.lower() == ".shp":
        if not source_field:
            raise ValueError(
                "source_field is required when add_landcover_layer() uses polygon input"
            )

        gdf = gpd.read_file(source_path)
        if source_field not in gdf.columns:
            raise ValueError(f"source_field not found in polygon source: {source_field}")
        if gdf.crs is None:
            raise ValueError(f"Polygon source has no CRS: {source_path}")

        gdf = gdf.loc[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.empty:
            raise ValueError(f"Polygon source has no valid geometries: {source_path}")

        gdf = gdf.to_crs(project_crs)
        bounds = tuple(gdf.total_bounds.tolist())
        if restrict_bounds is not None:
            bounds = restrict_bounds

        transform, width, height = _bounds_to_grid(bounds, cell_size)
        lookup = {
            str(row.source_value).strip(): int(row.class_id)
            for row in classification_table.itertuples()
        }

        source_values = gdf[source_field].astype(str).str.strip()
        unmatched = sorted(set(source_values.unique()) - set(lookup))
        if unmatched:
            raise ValueError(
                "Polygon source contains values not found in classification_table.source_value: "
                + ", ".join(unmatched[:10])
            )

        gdf["_class_id"] = source_values.map(lookup).astype(int)
        shapes = (
            (geom, int(class_id))
            for geom, class_id in zip(gdf.geometry, gdf["_class_id"], strict=False)
        )
        array = features.rasterize(
            shapes=shapes,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype="int32",
        )
        return array.astype(np.int32), transform, raster_map_rows, variable_rows

    with rasterio.open(source_path) as src:
        if src.crs is None:
            raise ValueError(f"Raster source has no CRS: {source_path}")

        source_bounds = transform_bounds(
            src.crs,
            project_crs,
            *src.bounds,
            densify_pts=21,
        )
        bounds = restrict_bounds if restrict_bounds is not None else source_bounds
        transform, width, height = _bounds_to_grid(bounds, cell_size)

        raw_array = np.full((height, width), -2147483648.0, dtype=np.float64)
        reproject(
            source=rasterio.band(src, 1),
            destination=raw_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=project_crs,
            dst_nodata=-2147483648.0,
            resampling=Resampling.nearest,
        )

        nodata_mask = _build_nodata_mask(raw_array, -2147483648.0)
        valid_values = raw_array[~nodata_mask]
        output_array = np.zeros((height, width), dtype=np.int32)

        mapping: dict[Any, int] = {}
        for row in classification_table.itertuples():
            mapped_value = _coerce_raster_lookup_value(row.source_value, raw_array)
            mapping[mapped_value] = int(row.class_id)
            if np.issubdtype(raw_array.dtype, np.floating):
                output_array[np.isclose(raw_array, mapped_value)] = int(row.class_id)
            else:
                output_array[raw_array == mapped_value] = int(row.class_id)

        if valid_values.size:
            unmatched = []
            for unique_value in np.unique(valid_values):
                matched = False
                for mapped_value in mapping:
                    if np.isclose(unique_value, mapped_value):
                        matched = True
                        break
                if not matched:
                    unmatched.append(unique_value)
            if unmatched:
                preview = ", ".join(str(value) for value in unmatched[:10])
                raise ValueError(
                    "Raster source contains values not found in "
                    f"classification_table.source_value: {preview}"
                )

        return output_array, transform, raster_map_rows, variable_rows


def _normalize_soil_group(value: Any) -> Optional[str]:
    if pd.isna(value):
        return None

    text = str(value).strip().upper()
    if not text:
        return None

    text = text.replace("\\", "-").replace("/", "-").replace(" ", "")
    if text in {"W", "WATER"}:
        return None
    return text


def _load_gssurgo_dataframe(gssurgo_path: Path) -> pd.DataFrame:
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "geopandas is required for soils generation. "
            "Install the geospatial dependencies before calling this API."
        ) from exc

    gssurgo_path = normalize_gssurgo_path(gssurgo_path)

    if gssurgo_path.suffix.lower() == ".gdb":
        layers: dict[str, str]
        try:
            import pyogrio

            layers = {
                str(name).lower(): str(name)
                for name, _ in pyogrio.list_layers(gssurgo_path)
            }
            polygon_layer = layers.get("mupolygon")
            muaggatt_layer = layers.get("muaggatt")
            if polygon_layer is None or muaggatt_layer is None:
                raise ValueError(
                    "GSSURGO geodatabase must contain MUPOLYGON and muaggatt layers"
                )

            polygons = gpd.read_file(
                gssurgo_path,
                layer=polygon_layer,
                engine="pyogrio",
            )
            muaggatt = pyogrio.read_dataframe(
                gssurgo_path,
                layer=muaggatt_layer,
                read_geometry=False,
            )
        except ImportError:
            try:
                import fiona
            except ImportError as exc:  # pragma: no cover - depends on local env
                raise ImportError(
                    "Reading GSSURGO geodatabases requires either pyogrio or fiona."
                ) from exc

            layers = {name.lower(): name for name in fiona.listlayers(gssurgo_path)}
            polygon_layer = layers.get("mupolygon")
            muaggatt_layer = layers.get("muaggatt")
            if polygon_layer is None or muaggatt_layer is None:
                raise ValueError(
                    "GSSURGO geodatabase must contain MUPOLYGON and muaggatt layers"
                )

            polygons = gpd.read_file(gssurgo_path, layer=polygon_layer)
            with fiona.open(gssurgo_path, layer=muaggatt_layer) as src:
                muaggatt = pd.DataFrame.from_records(feature["properties"] for feature in src)
    else:
        spatial_dir = gssurgo_path / "spatial"
        tabular_dir = gssurgo_path / "tabular"
        polygon_candidates = sorted(spatial_dir.glob("soilmu_a*.shp"))
        if not polygon_candidates:
            raise ValueError(
                "SSURGO folder must contain a polygon shapefile matching spatial/soilmu_a*.shp"
            )
        polygons = gpd.read_file(polygon_candidates[0])

        muaggatt_candidates = list(tabular_dir.glob("muaggatt.*"))
        if not muaggatt_candidates:
            raise ValueError("SSURGO folder must contain tabular/muaggatt.txt")
        muaggatt_path = muaggatt_candidates[0]
        if muaggatt_path.suffix.lower() == ".txt":
            muaggatt = pd.read_csv(muaggatt_path, sep="|", dtype=str)
        else:
            muaggatt = pd.read_csv(muaggatt_path, dtype=str)

    polygons.columns = [str(column).lower() for column in polygons.columns]
    if "mukey" not in polygons.columns:
        raise ValueError("GSSURGO polygons are missing the mukey column")

    muaggatt.columns = [str(column).lower() for column in muaggatt.columns]
    if "mukey" not in muaggatt.columns or "hydgrpdcd" not in muaggatt.columns:
        raise ValueError("GSSURGO muaggatt data is missing mukey or hydgrpdcd")

    polygons["mukey"] = polygons["mukey"].astype(str).str.strip()
    muaggatt["mukey"] = muaggatt["mukey"].astype(str).str.strip()
    muaggatt["soil_group"] = muaggatt["hydgrpdcd"].map(_normalize_soil_group)

    merged = polygons.merge(
        muaggatt.loc[:, ["mukey", "soil_group"]],
        on="mukey",
        how="left",
    )
    merged = merged.loc[
        merged.geometry.notna()
        & ~merged.geometry.is_empty
        & merged["soil_group"].notna()
    ].copy()
    if merged.empty:
        raise ValueError("No valid hydrologic soil group polygons were found in GSSURGO")
    return merged


def _rasterize_soils_source(
    gssurgo_path: Path,
    cell_size: float,
    project_crs: Any,
    restrict_to_extent: Optional[Any],
) -> tuple[np.ndarray, Any, list[tuple[int, str]]]:
    try:
        import geopandas as gpd
        from rasterio import features
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "geopandas and rasterio are required for soils generation. "
            "Install the geospatial dependencies before calling this API."
        ) from exc

    gdf = _load_gssurgo_dataframe(gssurgo_path)
    if gdf.crs is None:
        raise ValueError(f"GSSURGO polygons have no CRS: {gssurgo_path}")

    gdf = gdf.to_crs(project_crs)
    bounds = tuple(gdf.total_bounds.tolist())
    restrict_bounds = normalize_restrict_to_extent(restrict_to_extent)
    if restrict_bounds is not None:
        bounds = restrict_bounds

    encountered_groups = [
        soil_group
        for soil_group in _STANDARD_SOIL_GROUP_ORDER
        if soil_group in set(gdf["soil_group"].dropna().unique())
    ]
    encountered_groups.extend(
        sorted(
            set(gdf["soil_group"].dropna().unique()) - set(encountered_groups),
        )
    )
    soil_id_lookup = {
        soil_group: index + 1
        for index, soil_group in enumerate(encountered_groups)
    }

    transform, width, height = _bounds_to_grid(bounds, cell_size)
    gdf["_class_id"] = gdf["soil_group"].map(soil_id_lookup).astype(int)
    shapes = (
        (geom, int(class_id))
        for geom, class_id in zip(gdf.geometry, gdf["_class_id"], strict=False)
    )
    array = features.rasterize(
        shapes=shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="int32",
    )

    raster_map_rows = [(0, "NoData")] + [
        (class_id, soil_group)
        for soil_group, class_id in soil_id_lookup.items()
    ]
    return array.astype(np.int32), transform, raster_map_rows


def _resource_template_path(filename: str) -> Path:
    template_path = _RESOURCE_DIR / filename
    if not template_path.exists():
        raise FileNotFoundError(f"Missing packaged land-classification resource: {template_path}")
    return template_path


def _set_hdf_string_attr(hdf_file: h5py.File, key: str, value: str) -> None:
    payload = np.bytes_(value)
    if key in hdf_file.attrs:
        del hdf_file.attrs[key]
    hdf_file.attrs[key] = payload


def _decode_hdf_string(value: Any) -> str:
    """Decode RAS fixed-width HDF strings to normal Python text."""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip("\x00").strip()


def _read_hdf_string_attr(hdf_file: h5py.File, key: str) -> Optional[str]:
    if key not in hdf_file.attrs:
        return None
    return _decode_hdf_string(hdf_file.attrs[key])


def _build_raster_map_array(rows: list[tuple[int, str]]) -> np.ndarray:
    max_name_len = max(len(str(name).encode("utf-8")) for _, name in rows)
    dtype = np.dtype(
        [
            ("ID", "<i4"),
            ("Name", f"S{max_name_len}"),
        ]
    )
    data = np.zeros(len(rows), dtype=dtype)
    for index, (class_id, class_name) in enumerate(rows):
        data[index]["ID"] = int(class_id)
        data[index]["Name"] = str(class_name).encode("utf-8")
    return data


def _build_landcover_variables_array(
    rows: list[tuple[str, float, float]],
) -> np.ndarray:
    max_name_len = max(len(str(name).encode("utf-8")) for name, _, _ in rows)
    dtype = np.dtype(
        [
            ("Name", f"S{max_name_len}"),
            ("ManningsN", "<f4"),
            ("Percent Impervious", "<f4"),
        ]
    )
    data = np.zeros(len(rows), dtype=dtype)
    for index, (class_name, mannings_n, percent_impervious) in enumerate(rows):
        data[index]["Name"] = str(class_name).encode("utf-8")
        data[index]["ManningsN"] = np.float32(mannings_n)
        data[index]["Percent Impervious"] = np.float32(percent_impervious)
    return data


def _rewrite_landcover_sidecar(
    output_hdf_path: Path,
    raster_map_rows: list[tuple[int, str]],
    variable_rows: list[tuple[str, float, float]],
    projection_wkt: str,
) -> Path:
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_resource_template_path(_LANDCOVER_TEMPLATE_FILENAME), output_hdf_path)

    with h5py.File(output_hdf_path, "a") as hdf_file:
        for key in ("Raster Map", "Variables", "Classification Polygons"):
            if key in hdf_file:
                del hdf_file[key]

        hdf_file.create_dataset(
            "Raster Map",
            data=_build_raster_map_array(raster_map_rows),
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )
        hdf_file.create_dataset(
            "Variables",
            data=_build_landcover_variables_array(variable_rows),
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )

        _set_hdf_string_attr(hdf_file, "File Type", "HEC Land Cover")
        _set_hdf_string_attr(hdf_file, "GUID", str(uuid.uuid4()))
        _set_hdf_string_attr(hdf_file, "LC Type", "LandCover")
        _set_hdf_string_attr(hdf_file, "Projection", projection_wkt)
        _set_hdf_string_attr(hdf_file, "Version", "2.0")

    return RasUtils.safe_resolve(output_hdf_path)


def _rewrite_soils_sidecar(
    output_hdf_path: Path,
    raster_map_rows: list[tuple[int, str]],
    projection_wkt: str,
) -> Path:
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_resource_template_path(_SOILS_TEMPLATE_FILENAME), output_hdf_path)

    with h5py.File(output_hdf_path, "a") as hdf_file:
        for key in ("Raster Map", "Variables", "Classification Polygons"):
            if key in hdf_file:
                del hdf_file[key]

        hdf_file.create_dataset(
            "Raster Map",
            data=_build_raster_map_array(raster_map_rows),
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )

        _set_hdf_string_attr(hdf_file, "File Type", "HEC Land Cover")
        _set_hdf_string_attr(hdf_file, "GUID", str(uuid.uuid4()))
        _set_hdf_string_attr(hdf_file, "LC Type", "Soils")
        _set_hdf_string_attr(hdf_file, "Projection", projection_wkt)
        _set_hdf_string_attr(hdf_file, "Version", "2.0")

    return RasUtils.safe_resolve(output_hdf_path)


def _read_raster_map_rows(hdf_path: Union[str, Path]) -> list[tuple[int, str]]:
    hdf_path = Path(hdf_path)
    with h5py.File(hdf_path, "r") as hdf_file:
        dataset = hdf_file["Raster Map"][()]
        rows = []
        for row in dataset:
            rows.append(
                (
                    int(row["ID"]),
                    row["Name"].decode("utf-8").strip(),
                )
            )
        return rows


def _read_layer_ids_for_symbology(hdf_path: Union[str, Path]) -> list[int]:
    hdf_path = Path(hdf_path)
    with h5py.File(hdf_path, "r") as hdf_file:
        if "Raster Map" in hdf_file:
            return [class_id for class_id, _ in _read_raster_map_rows(hdf_path)]
        if "Variables" in hdf_file:
            return list(range(len(hdf_file["Variables"])))
    return []


def _read_landcover_variable_lookup(hdf_path: Union[str, Path]) -> dict[str, dict[str, float]]:
    hdf_path = Path(hdf_path)
    with h5py.File(hdf_path, "r") as hdf_file:
        if "Variables" not in hdf_file:
            return {}
        dataset = hdf_file["Variables"][()]
        lookup: dict[str, dict[str, float]] = {}
        for row in dataset:
            class_name = row["Name"].decode("utf-8").strip()
            lookup[class_name] = {
                "mannings_n": float(row["ManningsN"]) if "ManningsN" in dataset.dtype.names else np.nan,
                "percent_impervious": (
                    float(row["Percent Impervious"])
                    if "Percent Impervious" in dataset.dtype.names
                    else 0.0
                ),
            }
        return lookup


def _coerce_polygon_geometry(polygon: Any) -> Any:
    """Normalize a polygon-like object to a shapely Polygon or MultiPolygon."""
    try:
        from shapely.geometry import MultiPolygon, Polygon, shape
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "shapely is required for classification polygon authoring."
        ) from exc

    if isinstance(polygon, (Polygon, MultiPolygon)):
        geometry = polygon
    elif isinstance(polygon, dict):
        geometry = shape(polygon)
    elif hasattr(polygon, "__geo_interface__"):
        geometry = shape(polygon.__geo_interface__)
    elif isinstance(polygon, (list, tuple)):
        geometry = Polygon(polygon)
    else:
        raise TypeError(
            "polygon must be a shapely Polygon/MultiPolygon, GeoJSON-like "
            "mapping, object with __geo_interface__, or coordinate sequence"
        )

    if geometry.is_empty:
        raise ValueError("classification polygon geometry cannot be empty")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            "classification polygon geometry must be Polygon or MultiPolygon"
        )
    if not geometry.is_valid:
        raise ValueError("classification polygon geometry is not valid")
    return geometry


def _closed_xy_array(coords: Any) -> np.ndarray:
    points = [(float(x), float(y)) for x, y, *_ in coords]
    if len(points) < 3:
        raise ValueError("classification polygon rings need at least three points")
    if points[0] != points[-1]:
        points.append(points[0])
    if len(points) < 4:
        raise ValueError("classification polygon rings need at least four closed points")
    return np.asarray(points, dtype=np.float64)


def _polygon_geometry_to_rings(polygon: Any) -> list[np.ndarray]:
    """Convert shapely Polygon/MultiPolygon to HEC-RAS polygon ring arrays."""
    try:
        from shapely.geometry import MultiPolygon, Polygon
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "shapely is required for classification polygon authoring."
        ) from exc

    geometry = _coerce_polygon_geometry(polygon)
    polygons = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    rings: list[np.ndarray] = []
    for part in polygons:
        if not isinstance(part, Polygon):
            continue
        rings.append(_closed_xy_array(part.exterior.coords))
        rings.extend(_closed_xy_array(interior.coords) for interior in part.interiors)
    if not rings:
        raise ValueError("classification polygon has no writable rings")
    return rings


def _classification_sidecar_crs(hdf_path: Union[str, Path]) -> Optional[Any]:
    try:
        from pyproj import CRS
    except ImportError:
        return None

    with h5py.File(hdf_path, "r") as hdf_file:
        projection = _read_hdf_string_attr(hdf_file, "Projection")
    if not projection:
        return None
    try:
        return CRS.from_user_input(projection)
    except Exception as exc:
        logger.warning(
            "Could not parse classification sidecar projection from %s: %s",
            hdf_path,
            exc,
        )
        return None


def read_land_classification_polygon_records(
    layer_hdf_path: Union[str, Path],
) -> list[dict[str, Any]]:
    """Read RAS Mapper classification polygons from a land-classification HDF."""
    try:
        from shapely.geometry import Polygon
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "shapely is required for classification polygon extraction."
        ) from exc

    layer_hdf_path = Path(layer_hdf_path)
    records: list[dict[str, Any]] = []
    with h5py.File(layer_hdf_path, "r") as hdf_file:
        group_name = "Classification Polygons"
        if group_name not in hdf_file:
            return records
        group = hdf_file[group_name]
        required = {"Attributes", "Polygon Info", "Polygon Points"}
        if not required.issubset(set(group.keys())):
            return records

        attributes = group["Attributes"][()]
        attr_fields = attributes.dtype.names or ()
        class_field = "Classification" if "Classification" in attr_fields else "Name"
        if class_field not in attr_fields:
            raise ValueError(
                f"{layer_hdf_path} Classification Polygons/Attributes is missing "
                "a Classification or Name field"
            )

        polygon_info = group["Polygon Info"][()]
        polygon_points = group["Polygon Points"][()]
        polygon_parts = (
            group["Polygon Parts"][()]
            if "Polygon Parts" in group
            else np.zeros((0, 2), dtype=np.int32)
        )

        for polygon_index, info_row in enumerate(polygon_info):
            point_start, point_count, part_start, part_count = (
                int(value) for value in info_row
            )
            class_name = _decode_hdf_string(attributes[class_field][polygon_index])

            if part_count <= 1 or len(polygon_parts) == 0:
                ring = polygon_points[point_start : point_start + point_count]
                geometry = Polygon(ring)
            else:
                rings = []
                for part_row in polygon_parts[part_start : part_start + part_count]:
                    part_point_start, part_point_count = (int(value) for value in part_row)
                    rings.append(
                        polygon_points[
                            part_point_start : part_point_start + part_point_count
                        ]
                    )
                geometry = Polygon(rings[0], rings[1:])

            records.append(
                {
                    "polygon_index": polygon_index,
                    "class_name": class_name,
                    "geometry": geometry,
                }
            )
    return records


def _write_land_classification_polygon_records(
    layer_hdf_path: Union[str, Path],
    records: list[dict[str, Any]],
) -> None:
    layer_hdf_path = Path(layer_hdf_path)
    with h5py.File(layer_hdf_path, "a") as hdf_file:
        if "Classification Polygons" in hdf_file:
            del hdf_file["Classification Polygons"]

        if not records:
            return

        group = hdf_file.create_group("Classification Polygons")
        max_class_name_len = max(
            1,
            max(len(str(record["class_name"]).encode("utf-8")) for record in records),
        )
        attributes = np.zeros(
            len(records),
            dtype=np.dtype([("Classification", f"S{max_class_name_len}")]),
        )

        all_points: list[np.ndarray] = []
        polygon_parts: list[tuple[int, int]] = []
        polygon_info: list[tuple[int, int, int, int]] = []
        point_start = 0
        part_start = 0

        for index, record in enumerate(records):
            class_name = str(record["class_name"]).strip()
            attributes[index]["Classification"] = class_name.encode("utf-8")
            rings = _polygon_geometry_to_rings(record["geometry"])

            feature_point_start = point_start
            feature_part_start = part_start
            feature_point_count = 0
            for ring in rings:
                all_points.append(ring)
                ring_count = int(ring.shape[0])
                polygon_parts.append((point_start, ring_count))
                point_start += ring_count
                feature_point_count += ring_count
                part_start += 1

            polygon_info.append(
                (
                    feature_point_start,
                    feature_point_count,
                    feature_part_start,
                    len(rings),
                )
            )

        points_array = np.vstack(all_points).astype(np.float64)
        info_dataset = group.create_dataset(
            "Polygon Info",
            data=np.asarray(polygon_info, dtype=np.int32),
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )
        info_dataset.attrs["Column"] = np.asarray(
            [
                "Point Starting Index",
                "Point Count",
                "Part Starting Index",
                "Part Count",
            ],
            dtype="S20",
        )
        info_dataset.attrs["Feature Type"] = np.bytes_("Polygon")
        info_dataset.attrs["Row"] = np.bytes_("Feature")

        parts_dataset = group.create_dataset(
            "Polygon Parts",
            data=np.asarray(polygon_parts, dtype=np.int32),
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )
        parts_dataset.attrs["Column"] = np.asarray(
            ["Point Starting Index", "Point Count"],
            dtype="S20",
        )
        parts_dataset.attrs["Row"] = np.bytes_("Part")

        points_dataset = group.create_dataset(
            "Polygon Points",
            data=points_array,
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )
        points_dataset.attrs["Column"] = np.asarray(["X", "Y"], dtype="S1")
        points_dataset.attrs["Row"] = np.bytes_("Points")

        group.create_dataset(
            "Attributes",
            data=attributes,
            compression="gzip",
            compression_opts=1,
            chunks=True,
        )


def _structured_dataset_to_rows(dataset: h5py.Dataset) -> list[dict[str, Any]]:
    data = dataset[()]
    fields = data.dtype.names or ()
    rows: list[dict[str, Any]] = []
    for row in data:
        row_dict: dict[str, Any] = {}
        for field_name in fields:
            value = row[field_name]
            if data.dtype[field_name].kind == "S":
                value = _decode_hdf_string(value)
            elif isinstance(value, np.generic):
                value = value.item()
            row_dict[field_name] = value
        rows.append(row_dict)
    return rows


def _build_structured_dataset_array(
    rows: list[dict[str, Any]],
    dtype: np.dtype,
) -> np.ndarray:
    fields = dtype.names or ()
    output_dtype = []
    for field_name in fields:
        field_dtype = dtype[field_name]
        if field_dtype.kind == "S":
            max_len = max(
                int(field_dtype.itemsize),
                1,
                max(
                    (
                        len(str(row.get(field_name, "")).encode("utf-8"))
                        for row in rows
                    ),
                    default=1,
                ),
            )
            output_dtype.append((field_name, f"S{max_len}"))
        else:
            output_dtype.append((field_name, field_dtype))

    data = np.zeros(len(rows), dtype=np.dtype(output_dtype))
    for index, row in enumerate(rows):
        for field_name in fields:
            if data.dtype[field_name].kind == "S":
                data[index][field_name] = str(row.get(field_name, "")).encode("utf-8")
            else:
                data[index][field_name] = row.get(field_name, 0)
    return data


def _replace_structured_dataset(
    hdf_file: h5py.File,
    dataset_name: str,
    rows: list[dict[str, Any]],
    dtype: np.dtype,
) -> None:
    if dataset_name in hdf_file:
        del hdf_file[dataset_name]
    hdf_file.create_dataset(
        dataset_name,
        data=_build_structured_dataset_array(rows, dtype),
        compression="gzip",
        compression_opts=1,
        chunks=True,
    )


_VARIABLE_VALUE_ALIASES = {
    "mannings_n": "ManningsN",
    "manning_n": "ManningsN",
    "manningsn": "ManningsN",
    "percent_impervious": "Percent Impervious",
    "curve_number": "Curve Number",
    "abstraction_ratio": "Abstraction Ratio",
    "minimum_infiltration_rate": "Minimum Infiltration Rate",
    "maximum_deficit": "Maximum Deficit",
    "initial_deficit": "Initial Deficit",
    "potential_percolation_rate": "Potential Percolation Rate",
    "wetting_front_suction": "Wetting Front Suction",
    "saturated_hydraulic_conductivity": "Saturated Hydraulic Conductivity",
    "initial_soil_water_content": "Initial Soil Water Content",
    "saturated_soil_water_content": "Saturated Soil Water Content",
}


def _normalize_variable_values(
    variable_values: Optional[dict[str, Any]],
) -> dict[str, float]:
    if not variable_values:
        return {}
    normalized: dict[str, float] = {}
    for key, value in variable_values.items():
        lookup_key = str(key).strip()
        canonical_key = _VARIABLE_VALUE_ALIASES.get(
            lookup_key.lower().replace(" ", "_"),
            lookup_key,
        )
        normalized[canonical_key] = float(value)
    return normalized


def _infer_land_classification_hdf_kind(hdf_file: h5py.File) -> str:
    lc_type = (_read_hdf_string_attr(hdf_file, "LC Type") or "").lower()
    if "infiltration" in lc_type:
        return "infiltration"
    if "soil" in lc_type:
        return "soils"
    if "landcover" in lc_type or "land cover" in lc_type:
        return "landcover"
    if "Variables" in hdf_file:
        fields = set(hdf_file["Variables"].dtype.names or ())
        if "ManningsN" in fields:
            return "landcover"
        if fields & {
            "Curve Number",
            "Maximum Deficit",
            "Wetting Front Suction",
        }:
            return "infiltration"
    if "Raster Map" in hdf_file:
        return "soils"
    return "unknown"


def _upsert_raster_map_class(
    hdf_file: h5py.File,
    class_name: str,
    class_id: Optional[int],
) -> Optional[int]:
    if "Raster Map" not in hdf_file:
        return class_id

    dataset = hdf_file["Raster Map"]
    rows = _structured_dataset_to_rows(dataset)
    dtype = dataset.dtype
    fields = dtype.names or ()
    if "ID" not in fields or "Name" not in fields:
        raise ValueError("Raster Map dataset must contain ID and Name fields")

    resolved_class_id = int(class_id) if class_id is not None else None
    name_to_index = {
        str(row["Name"]).strip(): index
        for index, row in enumerate(rows)
    }
    id_to_name = {int(row["ID"]): str(row["Name"]).strip() for row in rows}

    if resolved_class_id is not None:
        duplicate_name = id_to_name.get(resolved_class_id)
        if duplicate_name is not None and duplicate_name != class_name:
            raise ValueError(
                f"class_id {resolved_class_id} already maps to {duplicate_name!r}"
            )

    if class_name in name_to_index:
        index = name_to_index[class_name]
        if resolved_class_id is None:
            resolved_class_id = int(rows[index]["ID"])
        rows[index]["ID"] = resolved_class_id
    else:
        if resolved_class_id is None:
            positive_ids = [int(row["ID"]) for row in rows if int(row["ID"]) > 0]
            resolved_class_id = (max(positive_ids) + 1) if positive_ids else 1
        rows.append({"ID": resolved_class_id, "Name": class_name})

    rows = sorted(rows, key=lambda row: int(row["ID"]))
    _replace_structured_dataset(hdf_file, "Raster Map", rows, dtype)
    return resolved_class_id


def _default_variable_row(
    rows: list[dict[str, Any]],
    dtype: np.dtype,
    class_name: str,
    layer_kind: str,
) -> dict[str, Any]:
    fields = dtype.names or ()
    source_row = next(
        (
            row
            for row in rows
            if str(row.get("Name", "")).strip().lower() == "nodata"
        ),
        rows[0].copy() if rows else {},
    )
    row = {}
    for field_name in fields:
        if field_name == "Name":
            row[field_name] = class_name
        elif field_name in source_row:
            row[field_name] = source_row[field_name]
        elif dtype[field_name].kind == "S":
            row[field_name] = ""
        else:
            row[field_name] = -9999.0

    if layer_kind == "landcover":
        if "ManningsN" in fields:
            row["ManningsN"] = _DEFAULT_LANDCOVER_NODATA_MANNINGS_N
        if "Percent Impervious" in fields:
            row["Percent Impervious"] = _DEFAULT_LANDCOVER_NODATA_PERCENT_IMPERVIOUS
    return row


def _upsert_variable_class(
    hdf_file: h5py.File,
    class_name: str,
    variable_values: dict[str, float],
    layer_kind: str,
) -> bool:
    if "Variables" not in hdf_file:
        return False

    dataset = hdf_file["Variables"]
    dtype = dataset.dtype
    fields = dtype.names or ()
    if "Name" not in fields:
        raise ValueError("Variables dataset must contain a Name field")

    rows = _structured_dataset_to_rows(dataset)
    name_to_index = {
        str(row["Name"]).strip(): index
        for index, row in enumerate(rows)
    }
    if class_name in name_to_index:
        row = rows[name_to_index[class_name]]
    else:
        row = _default_variable_row(rows, dtype, class_name, layer_kind)
        rows.append(row)

    for field_name, value in variable_values.items():
        if field_name not in fields:
            raise ValueError(
                f"Variables dataset does not contain field {field_name!r}"
            )
        if field_name == "Name":
            continue
        row[field_name] = value

    _replace_structured_dataset(hdf_file, "Variables", rows, dtype)
    return True


def _remove_class_from_sidecar_tables(
    hdf_file: h5py.File,
    class_name: str,
) -> None:
    for dataset_name in ("Raster Map", "Variables"):
        if dataset_name not in hdf_file:
            continue
        dataset = hdf_file[dataset_name]
        fields = dataset.dtype.names or ()
        name_field = "Name"
        if name_field not in fields:
            continue
        rows = [
            row
            for row in _structured_dataset_to_rows(dataset)
            if str(row.get(name_field, "")).strip() != class_name
        ]
        _replace_structured_dataset(hdf_file, dataset_name, rows, dataset.dtype)


def _update_sidecar_classification_tables(
    layer_hdf_path: Union[str, Path],
    class_name: str,
    class_id: Optional[int],
    variable_values: Optional[dict[str, Any]],
) -> dict[str, Any]:
    normalized_variables = _normalize_variable_values(variable_values)
    with h5py.File(layer_hdf_path, "a") as hdf_file:
        layer_kind = _infer_land_classification_hdf_kind(hdf_file)
        resolved_class_id = _upsert_raster_map_class(
            hdf_file,
            class_name,
            class_id,
        )
        variables_updated = _upsert_variable_class(
            hdf_file,
            class_name,
            normalized_variables,
            layer_kind,
        )

    return {
        "class_name": class_name,
        "class_id": resolved_class_id,
        "variables_updated": variables_updated,
        "variable_values": normalized_variables,
    }


def _backup_hdf_file(layer_hdf_path: Union[str, Path]) -> Path:
    layer_hdf_path = Path(layer_hdf_path)
    backup_path = Path(str(layer_hdf_path) + ".bak")
    shutil.copy2(layer_hdf_path, backup_path)
    return backup_path


def list_land_classification_polygons(
    layer_hdf_path: Union[str, Path],
) -> Any:
    """Return classification polygon overrides from a sidecar HDF as a GeoDataFrame."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ImportError(
            "geopandas is required to return classification polygons."
        ) from exc

    layer_hdf_path = Path(layer_hdf_path)
    records = read_land_classification_polygon_records(layer_hdf_path)
    columns = ["polygon_index", "class_name", "geometry"]
    crs = _classification_sidecar_crs(layer_hdf_path)
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(records, columns=columns, geometry="geometry", crs=crs)


def add_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon: Any,
    class_name: str,
    class_id: Optional[int] = None,
    variable_values: Optional[dict[str, Any]] = None,
    backup: bool = True,
) -> Any:
    """Add one classification polygon to a land-cover, soils, or infiltration HDF."""
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    class_name = str(class_name).strip()
    if not class_name:
        raise ValueError("class_name cannot be blank")

    geometry = _coerce_polygon_geometry(polygon)
    backup_path = _backup_hdf_file(layer_hdf_path) if backup else None
    table_update = _update_sidecar_classification_tables(
        layer_hdf_path,
        class_name=class_name,
        class_id=class_id,
        variable_values=variable_values,
    )
    records = read_land_classification_polygon_records(layer_hdf_path)
    records.append(
        {
            "polygon_index": len(records),
            "class_name": class_name,
            "geometry": geometry,
        }
    )
    _write_land_classification_polygon_records(layer_hdf_path, records)

    result = list_land_classification_polygons(layer_hdf_path)
    result.attrs.update(
        {
            "classification_hdf_path": str(layer_hdf_path),
            "backup_path": str(backup_path) if backup_path is not None else None,
            "class_update": table_update,
            "recompute_required": True,
        }
    )
    return result


def update_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon_index: int,
    polygon: Optional[Any] = None,
    class_name: Optional[str] = None,
    class_id: Optional[int] = None,
    variable_values: Optional[dict[str, Any]] = None,
    backup: bool = True,
) -> Any:
    """Update a classification polygon geometry and/or class assignment."""
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    records = read_land_classification_polygon_records(layer_hdf_path)
    if polygon_index < 0 or polygon_index >= len(records):
        raise IndexError(f"polygon_index out of range: {polygon_index}")

    backup_path = _backup_hdf_file(layer_hdf_path) if backup else None
    current = records[polygon_index]
    updated_class_name = (
        str(class_name).strip() if class_name is not None else current["class_name"]
    )
    if not updated_class_name:
        raise ValueError("class_name cannot be blank")
    updated_geometry = (
        _coerce_polygon_geometry(polygon)
        if polygon is not None
        else current["geometry"]
    )
    records[polygon_index] = {
        "polygon_index": polygon_index,
        "class_name": updated_class_name,
        "geometry": updated_geometry,
    }
    table_update = _update_sidecar_classification_tables(
        layer_hdf_path,
        class_name=updated_class_name,
        class_id=class_id,
        variable_values=variable_values,
    )
    _write_land_classification_polygon_records(layer_hdf_path, records)

    result = list_land_classification_polygons(layer_hdf_path)
    result.attrs.update(
        {
            "classification_hdf_path": str(layer_hdf_path),
            "backup_path": str(backup_path) if backup_path is not None else None,
            "class_update": table_update,
            "recompute_required": True,
        }
    )
    return result


def delete_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon_index: Optional[int] = None,
    class_name: Optional[str] = None,
    remove_unused_class: bool = False,
    backup: bool = True,
) -> Any:
    """Delete classification polygons by index or class name."""
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    if polygon_index is None and class_name is None:
        raise ValueError("Provide polygon_index or class_name")
    if polygon_index is not None and class_name is not None:
        raise ValueError("Provide only one of polygon_index or class_name")

    records = read_land_classification_polygon_records(layer_hdf_path)
    backup_path = _backup_hdf_file(layer_hdf_path) if backup else None

    removed_class_names: set[str] = set()
    if polygon_index is not None:
        if polygon_index < 0 or polygon_index >= len(records):
            raise IndexError(f"polygon_index out of range: {polygon_index}")
        removed = records.pop(polygon_index)
        removed_class_names.add(str(removed["class_name"]))
    else:
        target_class_name = str(class_name).strip()
        remaining = []
        for record in records:
            if str(record["class_name"]).strip() == target_class_name:
                removed_class_names.add(target_class_name)
            else:
                remaining.append(record)
        if len(remaining) == len(records):
            raise ValueError(
                f"No classification polygons found for class_name={target_class_name!r}"
            )
        records = remaining

    for new_index, record in enumerate(records):
        record["polygon_index"] = new_index

    if remove_unused_class:
        remaining_class_names = {str(record["class_name"]) for record in records}
        with h5py.File(layer_hdf_path, "a") as hdf_file:
            for removed_class_name in removed_class_names - remaining_class_names:
                _remove_class_from_sidecar_tables(hdf_file, removed_class_name)

    _write_land_classification_polygon_records(layer_hdf_path, records)
    result = list_land_classification_polygons(layer_hdf_path)
    result.attrs.update(
        {
            "classification_hdf_path": str(layer_hdf_path),
            "backup_path": str(backup_path) if backup_path is not None else None,
            "removed_class_names": sorted(removed_class_names),
            "recompute_required": True,
        }
    )
    return result


def _signed_argb(color: tuple[int, int, int], alpha: int = 160) -> int:
    red, green, blue = color
    value = (alpha << 24) | (red << 16) | (green << 8) | blue
    if value >= 2**31:
        value -= 2**32
    return value


def _generate_color_map(ids: list[int], alpha: int) -> tuple[str, str]:
    import colorsys

    positive_ids = [value for value in ids if value > 0]
    if not positive_ids:
        return "", ""

    colors = []
    count = len(positive_ids)
    for index, _ in enumerate(positive_ids):
        hue = index / max(count, 1)
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.65, 0.9)
        colors.append(
            _signed_argb(
                (
                    int(round(red * 255)),
                    int(round(green * 255)),
                    int(round(blue * 255)),
                ),
                alpha=alpha,
            )
        )

    values_string = ",".join(str(value) for value in positive_ids)
    colors_string = ",".join(str(value) for value in colors)
    return values_string, colors_string


def _load_rasmap_tree(
    project_paths: LandClassificationProjectPaths,
) -> tuple[ET.ElementTree, ET.Element]:
    if project_paths.rasmap_path.exists():
        try:
            tree = ET.parse(project_paths.rasmap_path)
            root = tree.getroot()
        except ET.ParseError as exc:
            raise ValueError(f"Invalid .rasmap XML: {project_paths.rasmap_path}") from exc
    else:
        root = ET.Element("RASMapper")
        ET.SubElement(root, "MapLayers")
        tree = ET.ElementTree(root)

    projection_path = project_paths.projection_path
    if projection_path is not None:
        projection_elem = root.find(".//RASProjectionFilename")
        if projection_elem is None:
            projection_elem = ET.Element("RASProjectionFilename")
            root.insert(0, projection_elem)
        projection_elem.set(
            "Filename",
            to_rasmap_relative_path(project_paths.project_folder, projection_path),
        )

    return tree, root


def _ensure_map_layers(root: ET.Element) -> ET.Element:
    map_layers = root.find("MapLayers")
    if map_layers is None:
        map_layers = ET.SubElement(root, "MapLayers")
    return map_layers


def _remove_existing_landcover_layers(
    map_layers: ET.Element,
    project_folder: Path,
    target_path: Path,
) -> None:
    target_path = RasUtils.safe_resolve(target_path)
    for layer in list(map_layers.findall("Layer")):
        if layer.attrib.get("Type") != "LandCoverLayer":
            continue
        resolved = resolve_rasmap_relative_path(
            project_folder,
            layer.attrib.get("Filename"),
        )
        if resolved is not None and RasUtils.safe_resolve(resolved) == target_path:
            map_layers.remove(layer)


def upsert_land_classification_layer(
    project_paths: LandClassificationProjectPaths,
    layer_path: Union[str, Path],
    layer_name: str,
    selected_parameter: str,
    alpha: int,
) -> Path:
    """Register or replace a land-classification layer entry in the project .rasmap."""
    layer_path = RasUtils.safe_resolve(Path(layer_path))
    tree, root = _load_rasmap_tree(project_paths)
    map_layers = _ensure_map_layers(root)
    _remove_existing_landcover_layers(map_layers, project_paths.project_folder, layer_path)

    ids = _read_layer_ids_for_symbology(layer_path)
    values_string, colors_string = _generate_color_map(ids, alpha=alpha)
    relative_filename = to_rasmap_relative_path(project_paths.project_folder, layer_path)

    layer_elem = ET.SubElement(
        map_layers,
        "Layer",
        {
            "Name": layer_name,
            "Type": "LandCoverLayer",
            "Filename": relative_filename,
            "SelectedParameterForSurfaceFillLabel": selected_parameter,
        },
    )

    if values_string and colors_string:
        symbology = ET.SubElement(layer_elem, "Symbology")
        ET.SubElement(
            symbology,
            "ColorByteMap",
            {
                "Type": "System.Int32",
                "Alpha": str(alpha),
                "Values": values_string,
                "Colors": colors_string,
                "ValuesExcludeLegend": "0",
            },
        )
        ET.SubElement(
            layer_elem,
            "ColorByteMap",
            {
                "Type": "System.Int32",
                "Alpha": str(alpha),
                "Values": values_string,
                "Colors": colors_string,
                "ValuesExcludeLegend": "0",
            },
        )

    ET.SubElement(
        layer_elem,
        "Layer",
        {
            "Name": "Classification Polygons",
            "Type": "LandCoverClassificationLayer",
            "Checked": "True",
            "Filename": relative_filename,
        },
    )

    tree.write(project_paths.rasmap_path, encoding="utf-8", xml_declaration=False)
    return layer_path


def _list_land_classification_records(
    project_paths: LandClassificationProjectPaths,
) -> pd.DataFrame:
    columns = [
        "name",
        "type",
        "checked",
        "filename",
        "resolved_path",
        "selected_parameter",
        "classification_kind",
        "classification_layer_count",
        "classification_layer_filenames",
        "classification_layer_paths",
    ]
    if not project_paths.rasmap_path.exists():
        return pd.DataFrame(columns=columns)

    root = ET.parse(project_paths.rasmap_path).getroot()
    map_layers = root.find("MapLayers")
    if map_layers is None:
        return pd.DataFrame(columns=columns)

    records = []
    for layer in map_layers.findall("Layer"):
        if layer.attrib.get("Type") != "LandCoverLayer":
            continue
        records.append(
            build_land_classification_record(
                layer,
                project_paths.project_folder,
            )
        )

    return pd.DataFrame(records, columns=columns) if records else pd.DataFrame(columns=columns)


def resolve_registered_land_classification_path(
    project_paths: LandClassificationProjectPaths,
    classification_kind: str,
) -> Optional[Path]:
    records = _list_land_classification_records(project_paths)
    if records.empty:
        return None

    matches = records.loc[
        records["classification_kind"] == classification_kind,
        "resolved_path",
    ].dropna()
    if matches.empty:
        return None
    return RasUtils.safe_resolve(Path(matches.iloc[0]))


def _remove_output_artifacts(output_hdf_path: Path) -> None:
    output_hdf_path.unlink(missing_ok=True)
    output_hdf_path.with_suffix(".tif").unlink(missing_ok=True)


def _classify_landcover_for_scs(
    class_name: str,
    percent_impervious: Optional[float],
) -> str:
    normalized_name = str(class_name or "").strip().lower()
    percent_impervious = (
        float(percent_impervious) if percent_impervious is not None else 0.0
    )

    if normalized_name in {"nodata", ""}:
        return "nodata"
    if "open water" in normalized_name or "main channel" in normalized_name:
        return "water"
    if "woody wetland" in normalized_name:
        return "wetlands_woody"
    if "emergent" in normalized_name or "wetland" in normalized_name:
        return "wetlands_emergent"
    if "deciduous forest" in normalized_name:
        return "forest_deciduous"
    if "mixed forest" in normalized_name or "evergreen forest" in normalized_name:
        return "forest_dense"
    if "forest" in normalized_name:
        return "forest_dense"
    if "developed" in normalized_name or percent_impervious >= 15.0:
        return "developed"
    if "cultivated" in normalized_name or "crop" in normalized_name:
        return "crops"
    if (
        "pasture" in normalized_name
        or "grassland" in normalized_name
        or "herbaceous" in normalized_name
        or "shrub" in normalized_name
        or "grass" in normalized_name
    ):
        return "shrub_grass_pasture"
    if "barren" in normalized_name or "rock" in normalized_name or "sand" in normalized_name:
        return "barren"
    if percent_impervious >= 98.0:
        return "water"
    return "shrub_grass_pasture"


def _resolve_scs_curve_number(
    category: str,
    soil_group: str,
    percent_impervious: float,
) -> tuple[float, float, float]:
    table = _SCS_CATEGORY_TABLES[category]
    soil_group = soil_group if soil_group in table["curve_numbers"] else "NoData"
    curve_number = float(table["curve_numbers"].get(soil_group, table["curve_numbers"]["NoData"]))
    abstraction_ratio = float(table["abstraction_ratio"])

    if category == "shrub_grass_pasture" and percent_impervious > 0:
        impervious_fraction = min(max(percent_impervious / 100.0, 0.0), 1.0)
        curve_number = round(curve_number * (1.0 - impervious_fraction) + 98.0 * impervious_fraction, 1)
        abstraction_ratio = 0.1

    return (
        curve_number,
        abstraction_ratio,
        _DEFAULT_SCS_MIN_INFILTRATION_RATE,
    )


def _blend_parameter_profiles(
    left: dict[str, float],
    right: dict[str, float],
) -> dict[str, float]:
    return {
        key: round((float(left[key]) + float(right[key])) / 2.0, 4)
        for key in left.keys() & right.keys()
    }


def _resolve_soil_group_parameter_profile(
    soil_group: Optional[str],
    table: dict[str, dict[str, float]],
    fallback: dict[str, float],
) -> dict[str, float]:
    if not soil_group or soil_group == "NoData":
        return dict(fallback)

    if soil_group in table:
        return dict(table[soil_group])

    if "-" in soil_group:
        parts = [part.strip() for part in soil_group.split("-") if part.strip()]
        if len(parts) == 2 and all(part in table for part in parts):
            return _blend_parameter_profiles(table[parts[0]], table[parts[1]])

    return dict(fallback)


def _split_infiltration_class_name(
    class_name: str,
    has_landcover: bool,
    has_soils: bool,
) -> tuple[str, str]:
    if " : " in class_name:
        left, right = class_name.split(" : ", 1)
        return left, right
    if has_landcover and not has_soils:
        return class_name, "NoData"
    if has_soils and not has_landcover:
        return "NoData", class_name
    return class_name, "NoData"


def _create_infiltration_shell(
    infiltration_method: str,
    output_hdf_path: Path,
    landcover_hdf_path: Optional[Path],
    soil_layer_path: Optional[Path],
    scs_reset_time_hours: Optional[float],
) -> Any:
    ns = get_interop_namespace()
    landcover_layer_cls = ns["LandCoverLayer"]
    dotnet_dictionary_cls = ns["DotNetDictionary"]

    from System import Single  # type: ignore

    properties = dotnet_dictionary_cls[str, Single]()
    if infiltration_method == "scs_curve_number":
        reset_time = (
            float(scs_reset_time_hours)
            if scs_reset_time_hours is not None
            else _DEFAULT_SCS_RESET_TIME_HOURS
        )
        properties["SCS Initial Loss Reset Time"] = Single(reset_time)

    type_lookup = {
        "scs_curve_number": landcover_layer_cls.LandCoverType.InfiltrationSCSCurveNumber,
        "deficit_constant": landcover_layer_cls.LandCoverType.InfiltrationDeficitConstantLoss,
        "green_ampt": landcover_layer_cls.LandCoverType.InfiltrationGreenAmpt,
    }
    infiltration_type = type_lookup[infiltration_method]

    if landcover_hdf_path is not None and soil_layer_path is not None:
        input_a = landcover_layer_cls(str(landcover_hdf_path))
        input_b = landcover_layer_cls(str(soil_layer_path))
        return landcover_layer_cls.CreateMerged(
            input_a,
            input_b,
            str(output_hdf_path),
            infiltration_type,
            properties,
        )
    if landcover_hdf_path is not None:
        input_a = landcover_layer_cls(str(landcover_hdf_path))
        return landcover_layer_cls.CreateCopy(
            input_a,
            str(output_hdf_path),
            infiltration_type,
            properties,
        )
    if soil_layer_path is not None:
        input_a = landcover_layer_cls(str(soil_layer_path))
        return landcover_layer_cls.CreateCopy(
            input_a,
            str(output_hdf_path),
            infiltration_type,
            properties,
        )

    raise ValueError(
        "At least one of landcover_hdf_path or soil_layer_path is required to create an infiltration layer"
    )


def _populate_scs_infiltration_defaults(
    infiltration_hdf_path: Path,
    landcover_hdf_path: Optional[Path],
    soil_layer_path: Optional[Path],
) -> pd.DataFrame:
    from .hdf.HdfInfiltration import HdfInfiltration

    ns = get_interop_namespace()
    landcover_layer_cls = ns["LandCoverLayer"]
    shell_layer = landcover_layer_cls(str(infiltration_hdf_path))
    ids = [int(value) for value in shell_layer.GetIDs()]
    names = [str(value) for value in shell_layer.GetNames()]

    landcover_lookup = (
        _read_landcover_variable_lookup(landcover_hdf_path)
        if landcover_hdf_path is not None
        else {}
    )

    rows = []
    for class_id, combined_name in zip(ids, names, strict=False):
        landcover_name, soil_group = _split_infiltration_class_name(
            combined_name,
            has_landcover=landcover_hdf_path is not None,
            has_soils=soil_layer_path is not None,
        )
        soil_group = _normalize_soil_group(soil_group) or "NoData"
        percent_impervious = landcover_lookup.get(landcover_name, {}).get(
            "percent_impervious",
            0.0,
        )
        category = _classify_landcover_for_scs(landcover_name, percent_impervious)
        curve_number, abstraction_ratio, minimum_infiltration_rate = _resolve_scs_curve_number(
            category,
            soil_group,
            percent_impervious,
        )
        rows.append(
            {
                "ID": class_id,
                "Name": combined_name,
                "Curve Number": curve_number,
                "Abstraction Ratio": abstraction_ratio,
                "Minimum Infiltration Rate": minimum_infiltration_rate,
            }
        )

    infiltration_df = pd.DataFrame(rows).drop(columns=["ID"])
    result = HdfInfiltration.set_infiltration_layer_data(
        infiltration_hdf_path,
        infiltration_df,
    )
    if result is None:
        raise RuntimeError(f"Failed to populate SCS infiltration variables: {infiltration_hdf_path}")
    return infiltration_df


def _read_infiltration_variable_rows(
    infiltration_hdf_path: Path,
) -> tuple[np.ndarray, list[str]]:
    with h5py.File(infiltration_hdf_path, "r") as hdf_file:
        if "Variables" not in hdf_file:
            raise KeyError(f"No Variables dataset found in {infiltration_hdf_path}")
        dataset = hdf_file["Variables"]
        data = dataset[()]
        names = [row["Name"].decode("utf-8").strip() for row in data]
    return data, names


def _write_infiltration_variable_rows(
    infiltration_hdf_path: Path,
    data: np.ndarray,
) -> None:
    with h5py.File(infiltration_hdf_path, "a") as hdf_file:
        if "Variables" not in hdf_file:
            raise KeyError(f"No Variables dataset found in {infiltration_hdf_path}")
        hdf_file["Variables"][...] = data


def _populate_deficit_constant_defaults(
    infiltration_hdf_path: Path,
    landcover_hdf_path: Optional[Path],
    soil_layer_path: Optional[Path],
) -> pd.DataFrame:
    data, names = _read_infiltration_variable_rows(infiltration_hdf_path)

    rows = []
    for index, combined_name in enumerate(names):
        _, soil_group = _split_infiltration_class_name(
            combined_name,
            has_landcover=landcover_hdf_path is not None,
            has_soils=soil_layer_path is not None,
        )
        soil_group = _normalize_soil_group(soil_group) or "NoData"
        defaults = _resolve_soil_group_parameter_profile(
            soil_group,
            _DEFICIT_CONSTANT_DEFAULTS_BY_SOIL_GROUP,
            _DEFAULT_DEFICIT_CONSTANT_NO_DATA,
        )
        for field_name, value in defaults.items():
            if field_name in data.dtype.names:
                data[field_name][index] = float(value)
        rows.append(
            {
                "Name": combined_name,
                **defaults,
            }
        )

    _write_infiltration_variable_rows(infiltration_hdf_path, data)
    return pd.DataFrame(rows)


def _populate_green_ampt_defaults(
    infiltration_hdf_path: Path,
    landcover_hdf_path: Optional[Path],
    soil_layer_path: Optional[Path],
) -> pd.DataFrame:
    data, names = _read_infiltration_variable_rows(infiltration_hdf_path)

    rows = []
    for index, combined_name in enumerate(names):
        _, soil_group = _split_infiltration_class_name(
            combined_name,
            has_landcover=landcover_hdf_path is not None,
            has_soils=soil_layer_path is not None,
        )
        soil_group = _normalize_soil_group(soil_group) or "NoData"
        defaults = _resolve_soil_group_parameter_profile(
            soil_group,
            _GREEN_AMPT_DEFAULTS_BY_SOIL_GROUP,
            _DEFAULT_GREEN_AMPT_NO_DATA,
        )
        for field_name, value in defaults.items():
            if field_name in data.dtype.names:
                data[field_name][index] = float(value)
        rows.append(
            {
                "Name": combined_name,
                **defaults,
            }
        )

    _write_infiltration_variable_rows(infiltration_hdf_path, data)
    return pd.DataFrame(rows)


def add_landcover_layer(
    ras_project_path: Union[str, Path],
    source_path: Union[str, Path],
    classification_table: Union[pd.DataFrame, str, Path],
    cell_size: float,
    source_field: Optional[str] = None,
    output_hdf_path: Optional[Union[str, Path]] = None,
    restrict_to_extent: Optional[Any] = None,
    layer_name: str = "LandCover",
) -> Path:
    """Create and register a land-cover classification layer."""
    project_paths = resolve_project_paths(ras_project_path)
    source_path = RasUtils.safe_resolve(Path(source_path))
    if not source_path.exists():
        raise FileNotFoundError(f"Land-cover source not found: {source_path}")

    classification_df = normalize_classification_table(classification_table)
    project_crs = _get_project_crs(project_paths)
    projection_wkt = _get_project_projection_wkt(project_paths)

    output_hdf_path = (
        RasUtils.safe_resolve(Path(output_hdf_path))
        if output_hdf_path is not None
        else build_default_output_path(
            project_paths.project_folder,
            _LANDCOVER_DEFAULT_RELATIVE_PATH,
        )
    )
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_output_artifacts(output_hdf_path)

    raster_array, transform, raster_map_rows, variable_rows = _rasterize_landcover_source(
        source_path=source_path,
        classification_table=classification_df,
        cell_size=float(cell_size),
        project_crs=project_crs,
        restrict_to_extent=restrict_to_extent,
        source_field=source_field,
    )

    _create_output_raster(
        output_hdf_path.with_suffix(".tif"),
        raster_array,
        transform,
        project_crs,
    )
    _rewrite_landcover_sidecar(
        output_hdf_path,
        raster_map_rows,
        variable_rows,
        projection_wkt,
    )
    upsert_land_classification_layer(
        project_paths,
        output_hdf_path,
        layer_name=layer_name,
        selected_parameter="ManningsN",
        alpha=128,
    )
    return output_hdf_path


def add_soils_layer(
    ras_project_path: Union[str, Path],
    gssurgo_path: Union[str, Path],
    cell_size: float,
    output_hdf_path: Optional[Union[str, Path]] = None,
    restrict_to_extent: Optional[Any] = None,
) -> Path:
    """Create and register a hydrologic soil group layer from direct GSSURGO input."""
    project_paths = resolve_project_paths(ras_project_path)
    gssurgo_path = normalize_gssurgo_path(gssurgo_path)

    project_crs = _get_project_crs(project_paths)
    projection_wkt = _get_project_projection_wkt(project_paths)

    output_hdf_path = (
        RasUtils.safe_resolve(Path(output_hdf_path))
        if output_hdf_path is not None
        else build_default_output_path(
            project_paths.project_folder,
            _SOILS_DEFAULT_RELATIVE_PATH,
        )
    )
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_output_artifacts(output_hdf_path)

    raster_array, transform, raster_map_rows = _rasterize_soils_source(
        gssurgo_path=gssurgo_path,
        cell_size=float(cell_size),
        project_crs=project_crs,
        restrict_to_extent=restrict_to_extent,
    )

    _create_output_raster(
        output_hdf_path.with_suffix(".tif"),
        raster_array,
        transform,
        project_crs,
    )
    _rewrite_soils_sidecar(
        output_hdf_path,
        raster_map_rows,
        projection_wkt,
    )
    upsert_land_classification_layer(
        project_paths,
        output_hdf_path,
        layer_name="Hydrologic Soil Groups",
        selected_parameter="ID",
        alpha=145,
    )
    return output_hdf_path


def add_infiltration_layer(
    ras_project_path: Union[str, Path],
    infiltration_method: str = "scs_curve_number",
    landcover_hdf_path: Optional[Union[str, Path]] = None,
    soil_layer_path: Optional[Union[str, Path]] = None,
    output_hdf_path: Optional[Union[str, Path]] = None,
    scs_reset_time_hours: Optional[float] = None,
) -> Path:
    """Create and register an infiltration layer, with provisional starter defaults populated."""
    valid_methods = {
        "scs_curve_number",
        "deficit_constant",
        "green_ampt",
    }
    if infiltration_method not in valid_methods:
        raise ValueError(
            "infiltration_method must be one of: "
            + ", ".join(sorted(valid_methods))
        )

    project_paths = resolve_project_paths(ras_project_path)
    require_projection_path(project_paths)

    resolved_landcover_path = (
        RasUtils.safe_resolve(Path(landcover_hdf_path))
        if landcover_hdf_path is not None
        else resolve_registered_land_classification_path(project_paths, "landcover")
    )
    resolved_soil_path = (
        RasUtils.safe_resolve(Path(soil_layer_path))
        if soil_layer_path is not None
        else resolve_registered_land_classification_path(project_paths, "soils")
    )

    if resolved_landcover_path is None and resolved_soil_path is None:
        raise FileNotFoundError(
            "No land cover or soils layer was provided and none could be resolved from the project .rasmap"
        )

    output_hdf_path = (
        RasUtils.safe_resolve(Path(output_hdf_path))
        if output_hdf_path is not None
        else build_default_output_path(
            project_paths.project_folder,
            _INFILTRATION_DEFAULT_RELATIVE_PATH,
        )
    )
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_output_artifacts(output_hdf_path)

    _create_infiltration_shell(
        infiltration_method=infiltration_method,
        output_hdf_path=output_hdf_path,
        landcover_hdf_path=resolved_landcover_path,
        soil_layer_path=resolved_soil_path,
        scs_reset_time_hours=scs_reset_time_hours,
    )

    if infiltration_method == "scs_curve_number":
        _populate_scs_infiltration_defaults(
            output_hdf_path,
            resolved_landcover_path,
            resolved_soil_path,
        )
    elif infiltration_method == "deficit_constant":
        _populate_deficit_constant_defaults(
            output_hdf_path,
            resolved_landcover_path,
            resolved_soil_path,
        )
    else:
        _populate_green_ampt_defaults(
            output_hdf_path,
            resolved_landcover_path,
            resolved_soil_path,
        )

    if infiltration_method in {"deficit_constant", "green_ampt"}:
        logger.info(
            "Populated provisional %s starter values at %s. These values are intended "
            "for BLE model startup and should be refined later through overrides, "
            "calibration regions, and validation.",
            infiltration_method,
            output_hdf_path,
        )

    upsert_land_classification_layer(
        project_paths,
        output_hdf_path,
        layer_name="Infiltration",
        selected_parameter="ID",
        alpha=135,
    )
    return output_hdf_path


def associate_geometry_layers(
    ras_project_path: Union[str, Path],
    geom_file: Union[str, Path],
    landcover_hdf_path: Optional[Union[str, Path]] = None,
    soil_layer_path: Optional[Union[str, Path]] = None,
    infiltration_hdf_path: Optional[Union[str, Path]] = None,
    terrain_hdf_path: Optional[Union[str, Path]] = None,
    sediment_soils_hdf_path: Optional[Union[str, Path]] = None,
    ras_object: Any = None,
) -> Path:
    """Associate project terrain / classification layers to a geometry HDF."""
    project_paths = resolve_project_paths(ras_project_path)
    geom_hdf_path = resolve_geometry_hdf_path(
        project_paths,
        geom_file,
        ras_object=ras_object,
    )

    resolved_landcover_path = (
        RasUtils.safe_resolve(Path(landcover_hdf_path))
        if landcover_hdf_path is not None
        else resolve_registered_land_classification_path(project_paths, "landcover")
    )
    resolved_soil_path = (
        RasUtils.safe_resolve(Path(soil_layer_path))
        if soil_layer_path is not None
        else resolve_registered_land_classification_path(project_paths, "soils")
    )
    resolved_infiltration_path = (
        RasUtils.safe_resolve(Path(infiltration_hdf_path))
        if infiltration_hdf_path is not None
        else resolve_registered_land_classification_path(project_paths, "infiltration")
    )
    resolved_terrain_path = (
        RasUtils.safe_resolve(Path(terrain_hdf_path))
        if terrain_hdf_path is not None
        else None
    )
    resolved_sediment_soils_path = (
        RasUtils.safe_resolve(Path(sediment_soils_hdf_path))
        if sediment_soils_hdf_path is not None
        else None
    )

    if resolved_soil_path is not None:
        logger.debug(
            "Hydrologic soils layer resolved for association but not passed to "
            "SedimentSoilsFilename because that geometry attribute is for sediment "
            "bed material, not infiltration soils. Use sediment_soils_hdf_path "
            "to write the SedimentSoilsFilename association explicitly."
        )

    from ._geometry_association import write_geometry_association

    return write_geometry_association(
        geom_hdf_path,
        terrain_hdf_path=resolved_terrain_path,
        landcover_hdf_path=resolved_landcover_path,
        infiltration_hdf_path=resolved_infiltration_path,
        sediment_soils_hdf_path=resolved_sediment_soils_path,
        project_folder=project_paths.project_folder,
        rasmap_path=project_paths.rasmap_path,
    )


def recompute_property_tables(
    ras_project_path: Union[str, Path],
    geom_file: Union[str, Path],
    ras_object: Any = None,
) -> Path:
    """Run CompleteGeometry + ComputePropertyTables for a compiled geometry HDF."""
    project_paths = resolve_project_paths(ras_project_path)
    geom_hdf_path = resolve_geometry_hdf_path(
        project_paths,
        geom_file,
        ras_object=ras_object,
    )

    ns = get_interop_namespace()
    complete_geometry_command = ns["CompleteGeometryCommand"]()
    complete_geometry_command.GeometryFilename = str(geom_hdf_path)
    complete_geometry_command.RasmapFilename = str(project_paths.rasmap_path)
    complete_geometry_command.Execute(None)

    compute_property_tables_command = ns["ComputePropertyTablesCommand"]()
    compute_property_tables_command.Geometry = str(geom_hdf_path)
    compute_property_tables_command.Execute(None)

    return geom_hdf_path
