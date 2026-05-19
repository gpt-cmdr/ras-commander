"""Shared helpers for HEC-RAS geometry HDF layer associations.

HEC-RAS stores terrain, land-cover, infiltration, and sediment bed-material
links as attributes on the ``/Geometry`` group.  This module keeps the
attribute names, RasProcess argument names, and comparison logic in one place
so the Python-native RasMap workflow and the RasProcess reference validator do
not drift apart.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, Mapping, Optional, Union

import numpy as np

from .RasUtils import RasUtils


PathLike = Union[str, Path]

GEOMETRY_ASSOCIATION_FIELDS: Dict[str, Dict[str, Any]] = {
    "terrain_hdf_path": {
        "cli_arg": "TerrainFilename",
        "command_property": "TerrainFilename",
        "filename_attr": "Terrain Filename",
        "layer_attr": "Terrain Layername",
        "date_attr": "Terrain File Date",
        "date_key": "terrain_file_date",
        "layer_kind": "terrain",
    },
    "landcover_hdf_path": {
        "cli_arg": "NValueFilename",
        "command_property": "NValueFilename",
        "filename_attr": "Land Cover Filename",
        "layer_attr": "Land Cover Layername",
        "date_attr": "Land Cover File Date",
        "date_key": "landcover_file_date",
        "extra_date_attrs": ("Land Cover Date Last Modified",),
        "extra_date_keys": ("landcover_date_last_modified",),
        "layer_kind": "landcover",
    },
    "infiltration_hdf_path": {
        "cli_arg": "InfiltrationFilename",
        "command_property": "InfiltrationFilename",
        "filename_attr": "Infiltration Filename",
        "layer_attr": "Infiltration Layername",
        "date_attr": "Infiltration File Date",
        "date_key": "infiltration_file_date",
        "layer_kind": "infiltration",
    },
    "sediment_soils_hdf_path": {
        "cli_arg": "SedimentSoilsFilename",
        "command_property": "SedimentSoilsFilename",
        "filename_attr": "Sediment Bed Material Filename",
        "layer_attr": "Sediment Bed Material Layername",
        "date_attr": "Sediment Bed Material File Date",
        "date_key": "sediment_soils_file_date",
        "layer_kind": "sediment_soils",
    },
}

FIELD_ORDER = tuple(GEOMETRY_ASSOCIATION_FIELDS)
_WINDOWS_ENV_VAR_PATTERN = re.compile(r"%([^%]+)%")
_PLAN_OR_RESULT_HDF_PATTERN = re.compile(r"\.[pou]\d{2}\.hdf$", re.IGNORECASE)


def safe_resolve_path(path: PathLike) -> Path:
    """Resolve a path without requiring it to exist."""
    return RasUtils.safe_resolve(Path(path))


def decode_hdf_attr(value: Any) -> Optional[str]:
    """Decode an HDF attribute value to a clean string."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except (AttributeError, ValueError, TypeError):
            pass
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = text.strip("\x00").strip()
    return text if text else None


def encode_hdf_attr(value: str) -> np.bytes_:
    """Encode an HDF string attribute in the byte-string style HEC-RAS uses."""
    return np.bytes_(str(value).encode("utf-8"))


def resolve_association_attr_path(hdf_path: PathLike, attr_value: str) -> Path:
    """Resolve a filename attribute relative to the HDF folder."""
    hdf_path = Path(hdf_path)
    attr_text = str(attr_value).strip()
    attr_text = _WINDOWS_ENV_VAR_PATTERN.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)),
        attr_text,
    )

    posix_path = Path(attr_text)
    windows_path = PureWindowsPath(attr_text.replace("/", "\\"))

    if posix_path.is_absolute():
        return safe_resolve_path(posix_path)
    if windows_path.is_absolute():
        return safe_resolve_path(Path(str(windows_path)))

    relative_text = attr_text.replace("/", "\\")
    if relative_text.startswith(".\\") or relative_text.startswith("./"):
        relative_text = relative_text[2:]
    relative_path = Path(*PureWindowsPath(relative_text).parts)
    return safe_resolve_path(hdf_path.parent / relative_path)


def format_hec_relative_path(target_path: PathLike, base_folder: PathLike) -> str:
    """Format a target as a RAS-style Windows path, relative when possible."""
    target = safe_resolve_path(target_path)
    base = safe_resolve_path(base_folder)
    try:
        relative = os.path.relpath(target, base)
    except ValueError:
        return str(target).replace("/", "\\")

    relative = relative.replace("/", "\\")
    if relative == ".":
        return "."
    if relative.startswith("..\\") or relative == "..":
        return relative
    return ".\\" + relative


def format_hec_file_date(path: PathLike) -> str:
    """Format file mtime the way HEC-RAS stores association dates."""
    timestamp = Path(path).stat().st_mtime
    return datetime.fromtimestamp(timestamp).strftime("%d%b%Y %H:%M:%S").upper()


def is_plan_or_result_hdf(path: PathLike) -> bool:
    """Return True for plan/result HDF names such as ``.p01.hdf``."""
    return bool(_PLAN_OR_RESULT_HDF_PATTERN.search(Path(path).name))


def ensure_geometry_group(hdf_path: PathLike) -> None:
    """Validate that an HDF file contains the required ``/Geometry`` group."""
    import h5py

    hdf_path = Path(hdf_path)
    with h5py.File(str(hdf_path), "r") as hdf_file:
        if "Geometry" not in hdf_file:
            raise RuntimeError(f"HDF is missing the /Geometry group: {hdf_path}")


def _field_attr_names() -> tuple[str, ...]:
    attrs = ["SI Units"]
    for field in GEOMETRY_ASSOCIATION_FIELDS.values():
        attrs.extend([field["filename_attr"], field["layer_attr"]])
        if field.get("date_attr"):
            attrs.append(field["date_attr"])
        attrs.extend(field.get("extra_date_attrs", ()))
    return tuple(dict.fromkeys(attrs))


def read_geometry_association(
    hdf_path: PathLike,
    *,
    resolve_paths: bool = True,
    include_2d_area_attrs: bool = False,
) -> dict[str, Any]:
    """Read ``/Geometry`` association attributes from a geometry or result HDF."""
    import h5py

    hdf_path = safe_resolve_path(hdf_path)
    ensure_geometry_group(hdf_path)

    association: dict[str, Any] = {}
    with h5py.File(str(hdf_path), "r") as hdf_file:
        attrs = hdf_file["Geometry"].attrs
        raw_attrs = {}
        for attr_name in _field_attr_names():
            attr_value = decode_hdf_attr(attrs.get(attr_name))
            if attr_value is not None:
                raw_attrs[attr_name] = attr_value

        for key, field in GEOMETRY_ASSOCIATION_FIELDS.items():
            raw_filename = raw_attrs.get(field["filename_attr"])
            raw_key = key.replace("_hdf_path", "_raw_filename")
            layer_key = key.replace("_hdf_path", "_layer_name")

            association[raw_key] = raw_filename
            if raw_filename:
                association[key] = (
                    str(resolve_association_attr_path(hdf_path, raw_filename))
                    if resolve_paths
                    else raw_filename
                )
            else:
                association[key] = None

            association[layer_key] = raw_attrs.get(field["layer_attr"])
            if field.get("date_attr"):
                association[field["date_key"]] = raw_attrs.get(field["date_attr"])
            for attr_name, attr_key in zip(
                field.get("extra_date_attrs", ()),
                field.get("extra_date_keys", ()),
            ):
                association[attr_key] = raw_attrs.get(attr_name)

        association["si_units"] = raw_attrs.get("SI Units")
        association["hdf_attrs"] = raw_attrs

        if include_2d_area_attrs:
            association["two_d_area_terrain_associations"] = (
                _read_two_d_area_terrain_associations(hdf_file, hdf_path, resolve_paths)
            )

    return association


def _read_two_d_area_terrain_associations(hdf_file, hdf_path: Path, resolve_paths: bool):
    area_records = []
    flow_areas = hdf_file.get("Geometry/2D Flow Areas")
    if flow_areas is None:
        return area_records

    for area_name, area_group in flow_areas.items():
        raw_filename = decode_hdf_attr(area_group.attrs.get("Terrain Filename"))
        record = {
            "flow_area": area_name,
            "terrain_raw_filename": raw_filename,
            "terrain_layer_name": decode_hdf_attr(
                area_group.attrs.get("Terrain Layername")
            ),
            "terrain_file_date": decode_hdf_attr(
                area_group.attrs.get("Terrain File Date")
            ),
        }
        if raw_filename:
            record["terrain_hdf_path"] = (
                str(resolve_association_attr_path(hdf_path, raw_filename))
                if resolve_paths
                else raw_filename
            )
        else:
            record["terrain_hdf_path"] = None
        area_records.append(record)
    return area_records


def list_registered_rasmap_layers(
    project_folder: PathLike,
    rasmap_path: Optional[PathLike] = None,
) -> list[dict[str, Any]]:
    """List terrain and land-classification layer names registered in .rasmap."""
    project_folder = safe_resolve_path(project_folder)
    rasmap_path = Path(rasmap_path) if rasmap_path is not None else None
    if rasmap_path is None:
        candidates = sorted(project_folder.glob("*.rasmap"))
        rasmap_path = candidates[0] if candidates else None
    if rasmap_path is None or not Path(rasmap_path).exists():
        return []

    root = ET.parse(rasmap_path).getroot()
    records: list[dict[str, Any]] = []

    for layer in root.findall(".//Terrains/Layer"):
        filename = layer.attrib.get("Filename")
        resolved_path = _resolve_rasmap_filename(project_folder, filename)
        records.append(
            {
                "name": layer.attrib.get("Name", ""),
                "type": layer.attrib.get("Type", ""),
                "filename": filename,
                "resolved_path": str(resolved_path) if resolved_path else None,
                "layer_kind": "terrain",
            }
        )

    map_layers = root.find("MapLayers")
    if map_layers is not None:
        for layer in map_layers.findall("Layer"):
            if layer.attrib.get("Type") != "LandCoverLayer":
                continue
            filename = layer.attrib.get("Filename")
            resolved_path = _resolve_rasmap_filename(project_folder, filename)
            records.append(
                {
                    "name": layer.attrib.get("Name", ""),
                    "type": layer.attrib.get("Type", ""),
                    "filename": filename,
                    "resolved_path": str(resolved_path) if resolved_path else None,
                    "layer_kind": _infer_land_classification_kind(
                        filename,
                        _get_selected_parameter(layer),
                    ),
                }
            )

    return records


def resolve_registered_layer_name(
    target_path: PathLike,
    layer_kind: str,
    *,
    project_folder: Optional[PathLike] = None,
    rasmap_path: Optional[PathLike] = None,
) -> str:
    """Resolve the RASMapper layer name for a path, falling back to its stem."""
    target = safe_resolve_path(target_path)
    if project_folder is not None or rasmap_path is not None:
        project = safe_resolve_path(project_folder or Path(rasmap_path).parent)
        for record in list_registered_rasmap_layers(project, rasmap_path):
            resolved = record.get("resolved_path")
            if not resolved:
                continue
            if not _paths_equivalent(resolved, target):
                continue
            if record.get("layer_kind") == layer_kind:
                return record.get("name") or target.stem

        for record in list_registered_rasmap_layers(project, rasmap_path):
            resolved = record.get("resolved_path")
            if resolved and _paths_equivalent(resolved, target):
                return record.get("name") or target.stem
    return target.stem


def build_expected_geometry_association_attrs(
    hdf_path: PathLike,
    supplied_paths: Mapping[str, Optional[PathLike]],
    *,
    project_folder: Optional[PathLike] = None,
    rasmap_path: Optional[PathLike] = None,
    layer_names: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Build the expected ``/Geometry`` attrs for supplied association paths."""
    hdf_path = safe_resolve_path(hdf_path)
    base_folder = safe_resolve_path(project_folder or hdf_path.parent)
    layer_names = layer_names or {}
    expected: dict[str, str] = {}

    for key in FIELD_ORDER:
        path_value = supplied_paths.get(key)
        if path_value is None:
            continue
        field = GEOMETRY_ASSOCIATION_FIELDS[key]
        resolved_path = safe_resolve_path(path_value)
        layer_name = layer_names.get(key) or resolve_registered_layer_name(
            resolved_path,
            field["layer_kind"],
            project_folder=project_folder,
            rasmap_path=rasmap_path,
        )
        file_date = format_hec_file_date(resolved_path)

        expected[field["filename_attr"]] = format_hec_relative_path(
            resolved_path,
            base_folder,
        )
        expected[field["layer_attr"]] = layer_name
        if field.get("date_attr"):
            expected[field["date_attr"]] = file_date
        for attr_name in field.get("extra_date_attrs", ()):
            expected[attr_name] = file_date

    return expected


def write_geometry_association(
    hdf_path: PathLike,
    *,
    terrain_hdf_path: Optional[PathLike] = None,
    landcover_hdf_path: Optional[PathLike] = None,
    infiltration_hdf_path: Optional[PathLike] = None,
    sediment_soils_hdf_path: Optional[PathLike] = None,
    project_folder: Optional[PathLike] = None,
    rasmap_path: Optional[PathLike] = None,
    layer_names: Optional[Mapping[str, str]] = None,
    validate: bool = True,
    allow_plan_result_hdf: bool = False,
) -> Path:
    """Write HEC-RAS geometry association attrs with h5py."""
    import h5py

    hdf_path = safe_resolve_path(hdf_path)
    if not hdf_path.exists():
        raise FileNotFoundError(f"Geometry HDF not found: {hdf_path}")
    if is_plan_or_result_hdf(hdf_path) and not allow_plan_result_hdf:
        raise RuntimeError(
            "Refusing to mutate a plan/result HDF. Geometry association writes "
            f"are only supported for geometry HDFs: {hdf_path}"
        )

    supplied = {
        "terrain_hdf_path": terrain_hdf_path,
        "landcover_hdf_path": landcover_hdf_path,
        "infiltration_hdf_path": infiltration_hdf_path,
        "sediment_soils_hdf_path": sediment_soils_hdf_path,
    }
    if all(path is None for path in supplied.values()):
        raise ValueError("Provide at least one geometry association path.")

    resolved_paths: dict[str, Path] = {}
    for key, path_value in supplied.items():
        if path_value is None:
            continue
        resolved_path = safe_resolve_path(path_value)
        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Association artifact not found for {key}: {resolved_path}"
            )
        resolved_paths[key] = resolved_path

    ensure_geometry_group(hdf_path)
    expected_attrs = build_expected_geometry_association_attrs(
        hdf_path,
        resolved_paths,
        project_folder=project_folder,
        rasmap_path=rasmap_path,
        layer_names=layer_names,
    )

    with h5py.File(str(hdf_path), "a") as hdf_file:
        geometry_attrs = hdf_file["Geometry"].attrs
        for attr_name, attr_value in expected_attrs.items():
            geometry_attrs[attr_name] = encode_hdf_attr(attr_value)

    if validate:
        observed = read_geometry_association(hdf_path, resolve_paths=True)
        mismatches = compare_expected_geometry_association_attrs(
            hdf_path,
            observed,
            expected_attrs,
        )
        if mismatches:
            raise RuntimeError(
                "Geometry association attributes did not persist: "
                + "; ".join(
                    f"{item['attribute']} expected {item['expected']!r}, "
                    f"observed {item['observed']!r}"
                    for item in mismatches
                )
            )

    return hdf_path


def build_set_geometry_association_args(
    hdf_path: PathLike,
    supplied_paths: Mapping[str, Optional[PathLike]],
    *,
    path_formatter: Optional[Callable[[Path], str]] = None,
) -> list[str]:
    """Build RasProcess.exe ``SetGeometryAssociation`` command arguments."""
    formatter = path_formatter or (lambda value: str(value))
    hdf_path = safe_resolve_path(hdf_path)
    args = [
        "SetGeometryAssociation",
        f"GeometryFilename={formatter(hdf_path)}",
    ]
    for key in FIELD_ORDER:
        path_value = supplied_paths.get(key)
        if path_value is None:
            continue
        field = GEOMETRY_ASSOCIATION_FIELDS[key]
        args.append(f"{field['cli_arg']}={formatter(safe_resolve_path(path_value))}")
    return args


def compare_expected_geometry_association_attrs(
    hdf_path: PathLike,
    observed_association: Mapping[str, Any],
    expected_attrs: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Compare observed association attrs to expected HEC-RAS attrs."""
    hdf_path = safe_resolve_path(hdf_path)
    observed_attrs = observed_association.get("hdf_attrs", {})
    mismatches: list[dict[str, Any]] = []
    filename_attrs = {
        field["filename_attr"] for field in GEOMETRY_ASSOCIATION_FIELDS.values()
    }

    for attr_name, expected in expected_attrs.items():
        observed = observed_attrs.get(attr_name)
        if attr_name in filename_attrs:
            if not observed or not _paths_equivalent(
                resolve_association_attr_path(hdf_path, observed),
                resolve_association_attr_path(hdf_path, expected),
            ):
                mismatches.append(
                    {
                        "attribute": attr_name,
                        "expected": expected,
                        "observed": observed,
                    }
                )
            continue

        if observed != expected:
            mismatches.append(
                {
                    "attribute": attr_name,
                    "expected": expected,
                    "observed": observed,
                }
            )

    return mismatches


def compare_geometry_association_paths(
    observed_association: Mapping[str, Any],
    expected_paths: Mapping[str, PathLike],
) -> list[dict[str, Any]]:
    """Compare normalized association path keys in a read-association dict."""
    mismatches: list[dict[str, Any]] = []
    for key, expected_path in expected_paths.items():
        observed_path = observed_association.get(key)
        if not observed_path or not _paths_equivalent(observed_path, expected_path):
            mismatches.append(
                {
                    "key": key,
                    "expected": str(safe_resolve_path(expected_path)),
                    "observed": observed_path,
                }
            )
    return mismatches


def _resolve_rasmap_filename(
    project_folder: Path,
    filename: Optional[Union[str, Path]],
) -> Optional[Path]:
    if filename in (None, ""):
        return None
    filename_text = _WINDOWS_ENV_VAR_PATTERN.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)),
        str(filename).strip(),
    )
    posix_path = Path(filename_text)
    windows_path = PureWindowsPath(filename_text.replace("/", "\\"))
    if posix_path.is_absolute():
        return safe_resolve_path(posix_path)
    if windows_path.is_absolute():
        return safe_resolve_path(Path(str(windows_path)))
    relative_text = filename_text.replace("/", "\\")
    if relative_text.startswith(".\\") or relative_text.startswith("./"):
        relative_text = relative_text[2:]
    return safe_resolve_path(project_folder / Path(*PureWindowsPath(relative_text).parts))


def _get_selected_parameter(layer_elem: ET.Element) -> Optional[str]:
    for child in layer_elem.iter():
        if child.tag == "Selected Parameter":
            text = (child.text or "").strip()
            return text or child.attrib.get("Name")
    return None


def _infer_land_classification_kind(
    filename: Optional[Union[str, Path]],
    selected_parameter: Optional[str],
) -> str:
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


def _paths_equivalent(first: PathLike, second: PathLike) -> bool:
    try:
        return safe_resolve_path(first) == safe_resolve_path(second)
    except (OSError, RuntimeError, TypeError, ValueError):
        return os.path.normcase(str(first)) == os.path.normcase(str(second))
