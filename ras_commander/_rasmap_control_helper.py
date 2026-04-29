"""Internal helpers for RASMapper view, geometry-layer, and window control."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, Union

import h5py
import numpy as np
import pandas as pd

from . import _land_classification_helper as _lch
from . import _rasmap_layer_helper as _mlh
from .LoggingConfig import get_logger
from .RasUtils import RasUtils

logger = get_logger(__name__)

CURRENT_VIEW_KEYS = ("MinX", "MaxX", "MinY", "MaxY")
DEFAULT_LAYER_PADDING_FRACTION = 0.05
DEFAULT_FEATURE_PADDING_FRACTION = 0.25

GEOMETRY_LAYER_COLUMNS = [
    "layer_id",
    "category",
    "geometry_name",
    "geometry_number",
    "geometry_filename",
    "geometry_hdf_path",
    "geometry_hdf_exists",
    "layer_name",
    "layer_type",
    "checked",
    "expanded",
    "geometry_index",
    "layer_index",
    "parent_identifiers",
]

GEOMETRY_FEATURE_COLUMNS = [
    "feature_id",
    "layer_type",
    "feature_index",
    "feature_name",
    "feature_type",
    "river",
    "reach",
    "station",
    "geometry_hdf_path",
    "coordinate_dataset_path",
    "info_dataset_path",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
    "width",
    "height",
    "point_count",
    "has_bounds",
]

RESULT_LAYER_COLUMNS = [
    "layer_id",
    "category",
    "plan_name",
    "plan_filename",
    "layer_name",
    "layer_type",
    "checked",
    "expanded",
    "result_index",
    "layer_index",
    "depth",
    "layer_path",
    "filename",
    "parent_identifiers",
    "profile_index",
]

GEOMETRY_LAYER_DATASET_ALIASES: dict[str, tuple[str, ...]] = {
    "RASRiver": ("Geometry/River Centerlines/Polyline Points",),
    "RASXS": ("Geometry/Cross Sections/Polyline Points",),
    "RASD2FlowArea": (
        "Geometry/2D Flow Areas/Polygon Points",
        "Geometry/2D Flow Areas/*/Perimeter",
        "Geometry/2D Flow Areas/*/FacePoints Coordinate",
    ),
    "MeshPerimeterLayer": (
        "Geometry/2D Flow Areas/Polygon Points",
        "Geometry/2D Flow Areas/*/Perimeter",
    ),
    "RASD2BreakLine": ("Geometry/2D Flow Area Break Lines/Polyline Points",),
    "RAS2DBreakLines": ("Geometry/2D Flow Area Break Lines/Polyline Points",),
    "RASBreakLines": ("Geometry/2D Flow Area Break Lines/Polyline Points",),
    "BreakLineLayer": ("Geometry/2D Flow Area Break Lines/Polyline Points",),
    "SA2DStructureLayer": ("Geometry/Structures/Centerline Points",),
    "StructureLayer": ("Geometry/Structures/Centerline Points",),
    "LateralStructureLayer": ("Geometry/Structures/Centerline Points",),
    "InlineStructureLayer": ("Geometry/Structures/Centerline Points",),
    "RASBankLines": (),
    "RASEdgeLines": (),
}

_GEOMETRY_NUMBER_PATTERN = re.compile(r"\.g(\d+)\.hdf", re.IGNORECASE)


def get_current_view(ras_project_path: Union[str, Path]) -> dict[str, Any]:
    """Return the RASMapper current view bounds in project coordinates."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    root = _parse_existing_rasmap(project_paths.rasmap_path)
    view = root.find("CurrentView")
    if view is None:
        return _empty_view(project_paths)

    values: dict[str, Optional[float]] = {}
    for key in CURRENT_VIEW_KEYS:
        text = view.findtext(key)
        values[key] = _coerce_float(text)

    result = _empty_view(project_paths)
    result.update(
        {
            "min_x": values["MinX"],
            "max_x": values["MaxX"],
            "min_y": values["MinY"],
            "max_y": values["MaxY"],
            "width": _range_or_none(values["MinX"], values["MaxX"]),
            "height": _range_or_none(values["MinY"], values["MaxY"]),
            "has_current_view": all(values[key] is not None for key in CURRENT_VIEW_KEYS),
        }
    )
    return result


def set_current_view(
    ras_project_path: Union[str, Path],
    *,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> dict[str, Any]:
    """Write the RASMapper current view bounds in project coordinates."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_existing_rasmap_tree(project_paths.rasmap_path)
    normalized = _normalize_bounds((min_x, min_y, max_x, max_y))

    view = root.find("CurrentView")
    if view is None:
        view = ET.Element("CurrentView")
        _insert_current_view(root, view)

    values = {
        "MaxX": normalized[2],
        "MinX": normalized[0],
        "MaxY": normalized[3],
        "MinY": normalized[1],
    }
    for key, value in values.items():
        elem = view.find(key)
        if elem is None:
            elem = ET.SubElement(view, key)
        elem.text = _format_float(value)

    _write_rasmap_tree(tree, project_paths.rasmap_path)
    return get_current_view(project_paths.rasmap_path)


def set_terrain_layer_visibility(
    ras_project_path: Union[str, Path],
    *,
    terrain_name: Optional[str] = None,
    checked: bool = True,
    exclusive: bool = False,
    surface_on: bool = True,
) -> int:
    """Set visibility for terrain layers in .rasmap XML."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_existing_rasmap_tree(project_paths.rasmap_path)
    terrains_elem = root.find("Terrains")
    if terrains_elem is None:
        return 0

    modified = 0
    if checked and terrains_elem.attrib.get("Checked") != "True":
        terrains_elem.set("Checked", "True")
        modified += 1

    for layer in terrains_elem.findall("Layer"):
        if layer.attrib.get("Type") != "TerrainLayer":
            continue

        matches = terrain_name is None or (
            layer.attrib.get("Name", "").casefold() == terrain_name.casefold()
        )
        target_checked: Optional[bool] = None
        if matches:
            target_checked = checked
        elif exclusive:
            target_checked = False

        if target_checked is None:
            continue

        target_value = _bool_attr(target_checked)
        if layer.attrib.get("Checked") != target_value:
            layer.set("Checked", target_value)
            modified += 1

        if surface_on:
            surface = layer.find("Surface")
            if surface is None:
                surface = ET.SubElement(layer, "Surface")
                modified += 1
            if surface.attrib.get("On") != target_value:
                surface.set("On", target_value)
                modified += 1

    if modified:
        _write_rasmap_tree(tree, project_paths.rasmap_path)
    return modified


def set_update_legend_with_view(
    ras_project_path: Union[str, Path],
    *,
    checked: bool = True,
    include_results: bool = True,
    include_terrain: bool = True,
    include_geometry: bool = False,
    include_map_layers: bool = False,
) -> int:
    """
    Set RASMapper ``Update Legend with View`` on selected surface-fill layers.

    RASMapper persists that checkbox as ``RegenerateForScreen`` on
    ``SurfaceFill`` XML elements.
    """
    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_existing_rasmap_tree(project_paths.rasmap_path)
    section_names: list[str] = []
    if include_results:
        section_names.append("Results")
    if include_terrain:
        section_names.append("Terrains")
    if include_geometry:
        section_names.append("Geometries")
    if include_map_layers:
        section_names.append("MapLayers")

    target_value = _bool_attr(checked)
    modified = 0
    for section_name in section_names:
        section = root.find(section_name)
        if section is None:
            continue
        for surface_fill in section.iter("SurfaceFill"):
            if surface_fill.attrib.get("RegenerateForScreen") != target_value:
                surface_fill.set("RegenerateForScreen", target_value)
                modified += 1

    if modified:
        _write_rasmap_tree(tree, project_paths.rasmap_path)
    return modified


def list_geometry_layers(ras_project_path: Union[str, Path]) -> pd.DataFrame:
    """List top-level geometries and child geometry elements from .rasmap XML."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    if not project_paths.rasmap_path.exists():
        return pd.DataFrame(columns=GEOMETRY_LAYER_COLUMNS)

    root = ET.parse(project_paths.rasmap_path).getroot()
    geometries_elem = root.find("Geometries")
    if geometries_elem is None:
        return pd.DataFrame(columns=GEOMETRY_LAYER_COLUMNS)

    records: list[dict[str, Any]] = []
    for geometry_index, geometry_layer in enumerate(geometries_elem.findall("Layer")):
        geometry_record = _geometry_record(
            project_paths,
            geometry_layer,
            geometry_index,
            layer_index=None,
        )
        records.append(geometry_record)

        for layer_index, child_layer in enumerate(geometry_layer.findall("Layer")):
            child_record = _geometry_record(
                project_paths,
                geometry_layer,
                geometry_index,
                layer_index=layer_index,
                child_layer=child_layer,
            )
            records.append(child_record)

    return pd.DataFrame(records, columns=GEOMETRY_LAYER_COLUMNS)


def set_geometry_layer_visibility(
    ras_project_path: Union[str, Path],
    *,
    checked: bool,
    layer_id: Optional[str] = None,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
    layer_name: Optional[str] = None,
    geometry_name: Optional[str] = None,
    geometry_number: Optional[str] = None,
    exclusive: bool = False,
) -> int:
    """Set visibility for matching child geometry elements in .rasmap XML."""
    layer_types = _normalize_string_filter(layer_type)
    if not any([layer_id, layer_types, layer_name]):
        raise ValueError("Provide layer_id, layer_type, or layer_name to select a layer.")

    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_existing_rasmap_tree(project_paths.rasmap_path)
    geometries_elem = root.find("Geometries")
    if geometries_elem is None:
        return 0

    matches: list[tuple[ET.Element, ET.Element, dict[str, Any]]] = []
    for geometry_index, geometry_layer in enumerate(geometries_elem.findall("Layer")):
        if not _geometry_matches(geometry_layer, geometry_name, geometry_number):
            continue

        for layer_index, child_layer in enumerate(geometry_layer.findall("Layer")):
            record = _geometry_record(
                project_paths,
                geometry_layer,
                geometry_index,
                layer_index=layer_index,
                child_layer=child_layer,
            )
            if _child_layer_matches(record, layer_id, layer_types, layer_name):
                matches.append((geometry_layer, child_layer, record))

    if not matches:
        return 0

    modified = 0
    if exclusive:
        if geometries_elem.attrib.get("Checked") != "False":
            geometries_elem.set("Checked", "False")
            modified += 1
        for geometry_layer in geometries_elem.findall("Layer"):
            if geometry_layer.attrib.get("Checked") != "False":
                geometry_layer.set("Checked", "False")
                modified += 1
            for child_layer in geometry_layer.findall("Layer"):
                if child_layer.attrib.get("Checked") != "False":
                    child_layer.set("Checked", "False")
                    modified += 1

    for geometry_layer, child_layer, _record in matches:
        if checked and geometries_elem.attrib.get("Checked") != "True":
            geometries_elem.set("Checked", "True")
            modified += 1
        if geometry_layer.attrib.get("Checked") != "True":
            geometry_layer.set("Checked", "True")
            modified += 1
        target_value = _bool_attr(checked)
        if child_layer.attrib.get("Checked") != target_value:
            child_layer.set("Checked", target_value)
            modified += 1

    _write_rasmap_tree(tree, project_paths.rasmap_path)
    return modified


def list_result_layers(ras_project_path: Union[str, Path]) -> pd.DataFrame:
    """List RASMapper Results tree entries from .rasmap XML."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    if not project_paths.rasmap_path.exists():
        return pd.DataFrame(columns=RESULT_LAYER_COLUMNS)

    root = ET.parse(project_paths.rasmap_path).getroot()
    results_elem = root.find("Results")
    if results_elem is None:
        return pd.DataFrame(columns=RESULT_LAYER_COLUMNS)

    records: list[dict[str, Any]] = []
    for result_index, result_layer in enumerate(results_elem.findall("Layer")):
        records.extend(
            _result_layer_records(
                result_layer,
                result_index=result_index,
                index_path=(),
                ancestor_names=(),
            )
        )
    return pd.DataFrame(records, columns=RESULT_LAYER_COLUMNS)


def set_result_layer_visibility(
    ras_project_path: Union[str, Path],
    *,
    checked: bool,
    layer_id: Optional[str] = None,
    plan_name: Optional[Union[str, Sequence[str]]] = None,
    layer_name: Optional[Union[str, Sequence[str]]] = None,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
    exclusive: bool = False,
) -> int:
    """
    Set visibility for RASMapper Results tree entries.

    When no selector is supplied, all result layers are targeted. Use
    ``exclusive=True`` with ``checked=True`` to hide every non-matching result
    layer and show only the selected plan or raster/result child layer needed
    for a figure.
    """
    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_existing_rasmap_tree(project_paths.rasmap_path)
    results_elem = root.find("Results")
    if results_elem is None:
        return 0

    plan_names = _normalize_casefold_filter(plan_name)
    layer_names = _normalize_casefold_filter(layer_name)
    layer_types = _normalize_string_filter(layer_type)
    has_selector = any((layer_id, plan_names, layer_names, layer_types))

    refs: list[tuple[ET.Element, tuple[ET.Element, ...], dict[str, Any]]] = []
    for result_index, result_layer in enumerate(results_elem.findall("Layer")):
        refs.extend(
            _result_layer_refs(
                result_layer,
                result_index=result_index,
                index_path=(),
                ancestors=(),
                ancestor_names=(),
            )
        )

    matches = [
        ref
        for ref in refs
        if _result_layer_matches(
            ref[2],
            layer_id=layer_id,
            plan_names=plan_names,
            layer_names=layer_names,
            layer_types=layer_types,
        )
    ]
    if has_selector and not matches:
        return 0

    target_refs = matches if has_selector else refs
    modified = 0

    if exclusive and checked:
        for layer, _ancestors, _record in refs:
            if layer.attrib.get("Checked") != "False":
                layer.set("Checked", "False")
                modified += 1
        if results_elem.attrib.get("Checked") != "False":
            results_elem.set("Checked", "False")
            modified += 1

    target_value = _bool_attr(checked)
    for layer, ancestors, _record in target_refs:
        if checked:
            if results_elem.attrib.get("Checked") != "True":
                results_elem.set("Checked", "True")
                modified += 1
            for ancestor in ancestors:
                if ancestor.attrib.get("Checked") != "True":
                    ancestor.set("Checked", "True")
                    modified += 1
        if layer.attrib.get("Checked") != target_value:
            layer.set("Checked", target_value)
            modified += 1

    if not checked and not has_selector:
        if results_elem.attrib.get("Checked") != "False":
            results_elem.set("Checked", "False")
            modified += 1

    if modified:
        _write_rasmap_tree(tree, project_paths.rasmap_path)
    return modified


def geometry_layer_bounds(
    geometry_hdf_path: Union[str, Path],
    *,
    layer_type: Optional[str] = None,
) -> dict[str, Any]:
    """Read project-coordinate bounds for a geometry element from a geometry HDF."""
    hdf_path = RasUtils.safe_resolve(Path(geometry_hdf_path))
    if not hdf_path.exists():
        raise FileNotFoundError(f"Geometry HDF not found: {hdf_path}")

    with h5py.File(hdf_path, "r") as hdf_file:
        if layer_type:
            dataset_paths = _resolve_layer_dataset_paths(hdf_file, layer_type)
        else:
            dataset_paths = _all_coordinate_dataset_paths(hdf_file)

        bounds = _bounds_from_datasets(hdf_file, dataset_paths, layer_type=layer_type)

    result = {
        "geometry_hdf_path": str(hdf_path),
        "layer_type": layer_type,
        "dataset_paths": dataset_paths,
        "min_x": None,
        "min_y": None,
        "max_x": None,
        "max_y": None,
        "width": None,
        "height": None,
        "point_count": 0,
        "has_bounds": False,
    }
    if bounds is not None:
        min_x, min_y, max_x, max_y, point_count = bounds
        result.update(
            {
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
                "point_count": point_count,
                "has_bounds": True,
            }
        )
    return result


def list_geometry_features(
    geometry_hdf_path: Union[str, Path],
    *,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
) -> pd.DataFrame:
    """List HDF geometry features for supported RASMapper layer types."""
    hdf_path = RasUtils.safe_resolve(Path(geometry_hdf_path))
    if not hdf_path.exists():
        raise FileNotFoundError(f"Geometry HDF not found: {hdf_path}")

    layer_types = _normalize_string_filter(layer_type)
    records: list[dict[str, Any]] = []
    with h5py.File(hdf_path, "r") as hdf_file:
        target_types = layer_types or {
            "RASD2FlowArea",
            "LateralStructureLayer",
            "StructureLayer",
            "RASD2BreakLine",
            "RASBreakLines",
            "SA2DStructureLayer",
            "RASXS",
        }
        for target_type in target_types:
            records.extend(_feature_records_for_layer(hdf_file, hdf_path, target_type))

    return pd.DataFrame(records, columns=GEOMETRY_FEATURE_COLUMNS)


def geometry_feature_bounds(
    geometry_hdf_path: Union[str, Path],
    *,
    layer_type: str,
    feature_id: Optional[str] = None,
    feature_name: Optional[str] = None,
    feature_index: Optional[int] = None,
) -> dict[str, Any]:
    """Read project-coordinate bounds for one or more selected HDF features."""
    features = list_geometry_features(geometry_hdf_path, layer_type=layer_type)
    selected = _select_feature_rows(
        features,
        feature_id=feature_id,
        feature_name=feature_name,
        feature_index=feature_index,
    )
    if selected.empty:
        raise ValueError("No geometry feature matched the supplied selector.")

    valid = selected.loc[selected["has_bounds"] == True]
    result = {
        "geometry_hdf_path": str(RasUtils.safe_resolve(Path(geometry_hdf_path))),
        "layer_type": layer_type,
        "feature_id": feature_id,
        "feature_name": feature_name,
        "feature_index": feature_index,
        "matched_features": selected.to_dict(orient="records"),
        "min_x": None,
        "min_y": None,
        "max_x": None,
        "max_y": None,
        "width": None,
        "height": None,
        "point_count": 0,
        "has_bounds": False,
    }
    if valid.empty:
        return result

    min_x = float(valid["min_x"].min())
    min_y = float(valid["min_y"].min())
    max_x = float(valid["max_x"].max())
    max_y = float(valid["max_y"].max())
    result.update(
        {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
            "point_count": int(valid["point_count"].sum()),
            "has_bounds": True,
        }
    )
    return result


def zoom_to_geometry_layer(
    ras_project_path: Union[str, Path],
    *,
    layer_id: Optional[str] = None,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
    layer_name: Optional[str] = None,
    geometry_name: Optional[str] = None,
    geometry_number: Optional[str] = None,
    feature_id: Optional[str] = None,
    feature_name: Optional[str] = None,
    feature_index: Optional[int] = None,
    padding_fraction: Optional[float] = None,
    min_padding: float = 0.0,
) -> dict[str, Any]:
    """Set CurrentView to the HDF-derived extent of matching geometry elements."""
    layers = list_geometry_layers(ras_project_path)
    if layers.empty:
        raise ValueError("No geometry layers were found in the project .rasmap.")

    selected = layers.loc[layers["category"] == "geometry_element"].copy()
    if layer_id is not None:
        selected = selected.loc[selected["layer_id"] == layer_id]
    if layer_type is not None:
        layer_types = _normalize_string_filter(layer_type) or set()
        selected = selected.loc[selected["layer_type"].isin(layer_types)]
    if layer_name is not None:
        selected = selected.loc[
            selected["layer_name"].fillna("").str.casefold() == layer_name.casefold()
        ]
    if geometry_name is not None:
        selected = selected.loc[
            selected["geometry_name"].fillna("").str.casefold()
            == geometry_name.casefold()
        ]
    if geometry_number is not None:
        selected = selected.loc[
            selected["geometry_number"].fillna("").map(_normalize_geometry_number)
            == _normalize_geometry_number(geometry_number)
        ]

    if selected.empty:
        raise ValueError("No geometry element matched the supplied selector.")

    use_feature_bounds = _has_feature_selector(
        feature_id=feature_id,
        feature_name=feature_name,
        feature_index=feature_index,
    )
    bounds_records: list[dict[str, Any]] = []
    for record in selected.to_dict(orient="records"):
        hdf_path = record.get("geometry_hdf_path")
        if not hdf_path:
            continue
        if use_feature_bounds:
            try:
                bounds = geometry_feature_bounds(
                    hdf_path,
                    layer_type=record.get("layer_type") or "",
                    feature_id=feature_id,
                    feature_name=feature_name,
                    feature_index=feature_index,
                )
            except ValueError:
                continue
        else:
            bounds = geometry_layer_bounds(
                hdf_path,
                layer_type=record.get("layer_type") or None,
            )
        if bounds["has_bounds"]:
            bounds["layer_id"] = record["layer_id"]
            bounds_records.append(bounds)

    if not bounds_records:
        layer_types_text = ", ".join(sorted(set(selected["layer_type"].dropna())))
        raise ValueError(
            "No HDF coordinate datasets were available for the selected "
            f"geometry layer(s): {layer_types_text}"
        )

    combined = _combine_bounds(bounds_records)
    effective_padding_fraction = _resolve_view_padding_fraction(
        use_feature_bounds=use_feature_bounds,
        padding_fraction=padding_fraction,
    )
    padded = _pad_bounds(combined, effective_padding_fraction, min_padding)
    view = set_current_view(
        ras_project_path,
        min_x=padded[0],
        min_y=padded[1],
        max_x=padded[2],
        max_y=padded[3],
    )
    return {
        "view": view,
        "bounds": {
            "min_x": combined[0],
            "min_y": combined[1],
            "max_x": combined[2],
            "max_y": combined[3],
        },
        "padded_bounds": {
            "min_x": padded[0],
            "min_y": padded[1],
            "max_x": padded[2],
            "max_y": padded[3],
        },
        "uses_feature_bounds": use_feature_bounds,
        "requested_padding_fraction": padding_fraction,
        "padding_fraction": effective_padding_fraction,
        "view_expansion_fraction": effective_padding_fraction * 2.0,
        "matched_layers": selected.to_dict(orient="records"),
        "bounds_records": bounds_records,
    }


def open_rasmapper(
    ras_project_path: Union[str, Path],
    *,
    rasmapper_exe_path: Optional[Union[str, Path]] = None,
    ras_version: Optional[str] = None,
    ras_object=None,
    wait: bool = False,
) -> subprocess.Popen:
    """Launch standalone RasMapper.exe with a project .rasmap file."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    if not project_paths.rasmap_path.exists():
        raise FileNotFoundError(f"RASMapper file not found: {project_paths.rasmap_path}")

    exe_path = resolve_rasmapper_exe(
        rasmapper_exe_path=rasmapper_exe_path,
        ras_version=ras_version,
        ras_object=ras_object,
    )
    process = subprocess.Popen([str(exe_path), str(project_paths.rasmap_path)])
    if wait:
        process.wait()
    return process


def capture_rasmapper_snapshot(
    *,
    pid: Optional[int] = None,
    output_path: Optional[Union[str, Path]] = None,
    delay_seconds: float = 1.0,
    timeout_seconds: float = 1800.0,
    poll_interval_seconds: float = 0.5,
) -> Optional[Path]:
    """Capture a visible RASMapper window using the existing Win32 screenshot helper."""
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    hwnd = wait_for_rasmapper_window(
        pid=pid,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    if hwnd is None:
        logger.warning("No visible RASMapper window found for screenshot capture")
        return None

    from .RasScreenshot import RasScreenshot

    return RasScreenshot.capture_window(
        hwnd,
        Path(output_path) if output_path is not None else None,
    )


def close_rasmapper(*, pid: Optional[int] = None) -> int:
    """Send WM_CLOSE to visible RASMapper windows and return the count closed."""
    try:
        import win32con
        import win32gui
    except ImportError:
        logger.error("pywin32 is required to close RASMapper windows by handle")
        return 0

    windows = _find_rasmapper_windows(pid=pid)
    for hwnd in windows:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return len(windows)


def create_spatial_review_package(
    ras_project_path: Union[str, Path],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    geometry_number: Optional[str] = None,
    geometry_name: Optional[str] = None,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
    layer_name: Optional[str] = None,
    feature_id: Optional[str] = None,
    feature_name: Optional[str] = None,
    feature_index: Optional[int] = None,
    terrain_name: Optional[str] = None,
    result_plan_name: Optional[Union[str, Sequence[str]]] = None,
    result_layer_name: Optional[Union[str, Sequence[str]]] = None,
    result_layer_type: Optional[Union[str, Sequence[str]]] = None,
    map_layer_name: Optional[Union[str, Sequence[str]]] = None,
    map_layer_type: Optional[Union[str, Sequence[str]]] = None,
    map_layer_category: Optional[Union[str, Sequence[str]]] = None,
    include_terrain: bool = True,
    include_results: bool = False,
    include_map_layers: bool = False,
    exclusive_geometry: bool = True,
    exclusive_terrain: bool = True,
    exclusive_results: bool = True,
    exclusive_map_layers: bool = True,
    update_legend_with_view: bool = True,
    zoom_to_layer: bool = True,
    padding_fraction: Optional[float] = None,
    min_padding: float = 0.0,
    capture_snapshot: bool = False,
    snapshot_filename: str = "rasmapper_spatial_review.png",
    delay_seconds: float = 5.0,
    snapshot_timeout_seconds: float = 1800.0,
    snapshot_poll_interval_seconds: float = 0.5,
    close_after_capture: bool = True,
    rasmapper_exe_path: Optional[Union[str, Path]] = None,
    ras_version: Optional[str] = None,
    ras_object=None,
    strict_preflight: bool = True,
    require_snapshot: bool = False,
) -> dict[str, Any]:
    """
    Create a deterministic RASMapper spatial-review evidence bundle.

    The default path is headless and writes audit artifacts without launching
    RASMapper. Pass ``capture_snapshot=True`` on a Windows review machine to add
    a live RASMapper screenshot.
    """
    project_paths = _lch.resolve_project_paths(ras_project_path)
    package_dir = _review_package_dir(project_paths, output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    uses_feature_selector = _has_feature_selector(
        feature_id=feature_id,
        feature_name=feature_name,
        feature_index=feature_index,
    )
    effective_padding_fraction = _resolve_view_padding_fraction(
        use_feature_bounds=uses_feature_selector,
        padding_fraction=padding_fraction,
    )

    artifacts: dict[str, Optional[str]] = {
        "rasmap_before": str(package_dir / "rasmap_before.xml"),
        "rasmap_after": str(package_dir / "rasmap_after.xml"),
        "geometry_layers": str(package_dir / "geometry_layers.csv"),
        "result_layers": str(package_dir / "result_layers.csv"),
        "geometry_features": str(package_dir / "geometry_features.csv"),
        "selected_features": str(package_dir / "selected_features.csv"),
        "selected_result_layers": str(package_dir / "selected_result_layers.csv"),
        "selected_map_layers": str(package_dir / "selected_map_layers.csv"),
        "map_layers": str(package_dir / "map_layers.csv"),
        "layers": str(package_dir / "layers.csv"),
        "review_state": str(package_dir / "review_state.json"),
        "findings_template": str(package_dir / "findings.md"),
        "snapshot": None,
    }
    shutil.copy2(project_paths.rasmap_path, artifacts["rasmap_before"])

    view_spec = {
        "geometry_number": geometry_number,
        "geometry_name": geometry_name,
        "layer_type": sorted(_normalize_string_filter(layer_type) or []),
        "layer_name": layer_name,
        "feature_id": feature_id,
        "feature_name": feature_name,
        "feature_index": feature_index,
        "terrain_name": terrain_name,
        "result_plan_name": sorted(_normalize_string_filter(result_plan_name) or []),
        "result_layer_name": sorted(_normalize_string_filter(result_layer_name) or []),
        "result_layer_type": sorted(_normalize_string_filter(result_layer_type) or []),
        "map_layer_name": sorted(_normalize_string_filter(map_layer_name) or []),
        "map_layer_type": sorted(_normalize_string_filter(map_layer_type) or []),
        "map_layer_category": sorted(_normalize_string_filter(map_layer_category) or []),
        "include_terrain": include_terrain,
        "include_results": include_results,
        "include_map_layers": include_map_layers,
        "exclusive_geometry": exclusive_geometry,
        "exclusive_terrain": exclusive_terrain,
        "exclusive_results": exclusive_results,
        "exclusive_map_layers": exclusive_map_layers,
        "update_legend_with_view": update_legend_with_view,
        "zoom_to_layer": zoom_to_layer,
        "uses_feature_selector": uses_feature_selector,
        "requested_padding_fraction": padding_fraction,
        "padding_fraction": effective_padding_fraction,
        "view_expansion_fraction": effective_padding_fraction * 2.0,
        "min_padding": min_padding,
        "capture_snapshot": capture_snapshot,
        "snapshot_filename": snapshot_filename,
        "delay_seconds": delay_seconds,
        "snapshot_timeout_seconds": snapshot_timeout_seconds,
        "snapshot_poll_interval_seconds": snapshot_poll_interval_seconds,
    }

    geometry_layers_before = list_geometry_layers(project_paths.rasmap_path)
    result_layers_before = list_result_layers(project_paths.rasmap_path)
    map_layers_before = _mlh.list_map_layers(project_paths.rasmap_path)
    preflight = _spatial_review_preflight(
        project_paths,
        geometry_layers_before,
        result_layers_before,
        map_layers_before,
        view_spec,
    )

    state: dict[str, Any] = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "project_folder": str(project_paths.project_folder),
        "project_name": project_paths.project_name,
        "rasmap_path": str(project_paths.rasmap_path),
        "output_dir": str(package_dir),
        "view_spec": view_spec,
        "preflight": preflight,
        "artifacts": artifacts,
        "modifications": {},
        "zoom": None,
        "current_view_before": get_current_view(project_paths.rasmap_path),
        "current_view_after": None,
        "snapshot": {
            "requested": capture_snapshot,
            "path": None,
            "created": False,
            "error": None,
            "process_id": None,
            "closed_windows": 0,
        },
        "passed": False,
    }
    _write_review_state(state, artifacts["review_state"])

    if strict_preflight:
        failed = [check for check in preflight if not check["passed"]]
        if failed:
            raise ValueError(
                "Spatial review preflight failed: "
                + "; ".join(check["message"] for check in failed)
            )

    if layer_type is not None or layer_name is not None:
        state["modifications"]["geometry_visibility"] = set_geometry_layer_visibility(
            project_paths.rasmap_path,
            geometry_number=geometry_number,
            geometry_name=geometry_name,
            layer_type=layer_type,
            layer_name=layer_name,
            checked=True,
            exclusive=exclusive_geometry,
        )

    if include_terrain:
        state["modifications"]["terrain_visibility"] = set_terrain_layer_visibility(
            project_paths.rasmap_path,
            terrain_name=terrain_name,
            checked=True,
            exclusive=exclusive_terrain,
        )

    result_selector = _has_result_selector(view_spec)
    state["modifications"]["result_visibility"] = set_result_layer_visibility(
        project_paths.rasmap_path,
        plan_name=result_plan_name,
        layer_name=result_layer_name,
        layer_type=result_layer_type,
        checked=include_results or result_selector,
        exclusive=exclusive_results if include_results or result_selector else False,
    )

    map_selector = _has_map_selector(view_spec)
    state["modifications"]["map_layer_visibility"] = _mlh.set_map_layer_visibility(
        project_paths.rasmap_path,
        layer_name=map_layer_name,
        layer_type=map_layer_type,
        category=map_layer_category,
        checked=include_map_layers or map_selector,
        exclusive=exclusive_map_layers if include_map_layers or map_selector else False,
    )

    if update_legend_with_view:
        state["modifications"]["update_legend_with_view"] = set_update_legend_with_view(
            project_paths.rasmap_path,
        )

    if zoom_to_layer and (layer_type is not None or layer_name is not None):
        state["zoom"] = zoom_to_geometry_layer(
            project_paths.rasmap_path,
            geometry_number=geometry_number,
            geometry_name=geometry_name,
            layer_type=layer_type,
            layer_name=layer_name,
            feature_id=feature_id,
            feature_name=feature_name,
            feature_index=feature_index,
            padding_fraction=effective_padding_fraction,
            min_padding=min_padding,
        )

    state["current_view_after"] = get_current_view(project_paths.rasmap_path)
    shutil.copy2(project_paths.rasmap_path, artifacts["rasmap_after"])

    geometry_layers_after = list_geometry_layers(project_paths.rasmap_path)
    result_layers_after = list_result_layers(project_paths.rasmap_path)
    map_layers_after = _mlh.list_map_layers(project_paths.rasmap_path)
    geometry_features_after = _features_for_selected_layers(geometry_layers_after)
    selected_geometry_layers_after = _select_geometry_rows(geometry_layers_after, view_spec)
    selected_result_layers_after = _select_result_rows(result_layers_after, view_spec)
    selected_map_layers_after = _select_map_rows(map_layers_after, view_spec)
    selected_features_after = _select_features_from_catalog(
        _features_for_selected_layers(selected_geometry_layers_after),
        feature_id=feature_id,
        feature_name=feature_name,
        feature_index=feature_index,
    )
    state["selected_features"] = selected_features_after.to_dict(orient="records")
    state["selected_result_layers"] = selected_result_layers_after.to_dict(
        orient="records",
    )
    state["selected_map_layers"] = selected_map_layers_after.to_dict(orient="records")
    _write_dataframe(geometry_layers_after, artifacts["geometry_layers"])
    _write_dataframe(result_layers_after, artifacts["result_layers"])
    _write_dataframe(geometry_features_after, artifacts["geometry_features"])
    _write_dataframe(selected_features_after, artifacts["selected_features"])
    _write_dataframe(selected_result_layers_after, artifacts["selected_result_layers"])
    _write_dataframe(selected_map_layers_after, artifacts["selected_map_layers"])
    _write_dataframe(map_layers_after, artifacts["map_layers"])
    _write_dataframe(
        _combined_layer_catalog(geometry_layers_after, result_layers_after, map_layers_after),
        artifacts["layers"],
    )

    if capture_snapshot:
        process: Optional[subprocess.Popen] = None
        try:
            process = open_rasmapper(
                project_paths.rasmap_path,
                rasmapper_exe_path=rasmapper_exe_path,
                ras_version=ras_version,
                ras_object=ras_object,
            )
            state["snapshot"]["process_id"] = process.pid
            snapshot_path = package_dir / snapshot_filename
            captured = capture_rasmapper_snapshot(
                pid=process.pid,
                output_path=snapshot_path,
                delay_seconds=delay_seconds,
                timeout_seconds=snapshot_timeout_seconds,
                poll_interval_seconds=snapshot_poll_interval_seconds,
            )
            if captured is not None:
                artifacts["snapshot"] = str(captured)
                state["snapshot"]["path"] = str(captured)
                state["snapshot"]["created"] = captured.exists()
                state["snapshot"].update(_snapshot_summary(captured))
        except Exception as exc:
            state["snapshot"]["error"] = str(exc)
            if require_snapshot:
                raise
        finally:
            if close_after_capture and process is not None:
                state["snapshot"]["closed_windows"] = close_rasmapper(pid=process.pid)

    if require_snapshot and not state["snapshot"]["created"]:
        raise RuntimeError("RASMapper snapshot was required but was not created.")

    state["passed"] = (
        all(check["passed"] for check in preflight)
        and (not require_snapshot or state["snapshot"]["created"])
    )
    _write_findings_template(state, artifacts["findings_template"])
    _write_review_state(state, artifacts["review_state"])
    return state


def resolve_rasmapper_exe(
    *,
    rasmapper_exe_path: Optional[Union[str, Path]] = None,
    ras_version: Optional[str] = None,
    ras_object=None,
) -> Path:
    """Resolve RasMapper.exe from an explicit path, RAS version, or RAS object."""
    candidates: list[Path] = []
    if rasmapper_exe_path is not None:
        candidates.append(Path(rasmapper_exe_path))

    ras_exe_path = getattr(ras_object, "ras_exe_path", None)
    if ras_exe_path:
        candidates.append(Path(ras_exe_path).parent / "RasMapper.exe")

    if ras_version is not None:
        from .RasPrj import get_ras_exe

        ras_exe = Path(get_ras_exe(ras_version))
        if ras_exe.name.lower() == "ras.exe":
            candidates.append(ras_exe.parent / "RasMapper.exe")

    from .RasPrj import ras

    global_ras_exe = getattr(ras, "ras_exe_path", None)
    if global_ras_exe:
        candidates.append(Path(global_ras_exe).parent / "RasMapper.exe")

    resolved = _first_existing_path(candidates)
    if resolved is not None:
        return resolved

    try:
        discovered = RasUtils.discover_ras_versions()
        for ras_exe in discovered.values():
            candidates.append(Path(ras_exe).parent / "RasMapper.exe")
    except Exception as exc:
        logger.debug("HEC-RAS version discovery failed while locating RasMapper: %s", exc)

    which_path = shutil.which("RasMapper.exe")
    if which_path:
        candidates.append(Path(which_path))

    resolved = _first_existing_path(candidates)
    if resolved is not None:
        return resolved

    searched = ", ".join(str(candidate) for candidate in candidates) or "PATH"
    raise FileNotFoundError(f"RasMapper.exe not found. Searched: {searched}")


def find_rasmapper_window(*, pid: Optional[int] = None) -> Optional[int]:
    """Return the first visible RASMapper window handle."""
    windows = _find_rasmapper_windows(pid=pid)
    return windows[0] if windows else None


def wait_for_rasmapper_window(
    *,
    pid: Optional[int] = None,
    timeout_seconds: float = 1800.0,
    poll_interval_seconds: float = 0.5,
) -> Optional[int]:
    """Wait for a visible RASMapper window and return its handle."""
    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
    interval = max(float(poll_interval_seconds), 0.1)
    while True:
        hwnd = find_rasmapper_window(pid=pid)
        if hwnd is not None:
            return hwnd
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def _first_existing_path(candidates: Sequence[Path]) -> Optional[Path]:
    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_file():
            return RasUtils.safe_resolve(candidate)
    return None


def _review_package_dir(project_paths: Any, output_dir: Optional[Union[str, Path]]) -> Path:
    if output_dir is not None:
        return RasUtils.safe_resolve(Path(output_dir))
    return RasUtils.safe_resolve(project_paths.project_folder / "RASMapper Screenshots")


def _spatial_review_preflight(
    project_paths: Any,
    geometry_layers: pd.DataFrame,
    result_layers: pd.DataFrame,
    map_layers: pd.DataFrame,
    view_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(code: str, passed: bool, message: str, severity: str = "error") -> None:
        checks.append(
            {
                "code": code,
                "passed": bool(passed),
                "severity": severity,
                "message": message,
            }
        )

    add(
        "rasmap_exists",
        project_paths.rasmap_path.exists(),
        f"RASMapper file exists: {project_paths.rasmap_path}",
    )

    add(
        "geometry_layers_found",
        not geometry_layers.empty,
        "Geometry layers were found in the .rasmap.",
    )

    selected = _select_geometry_rows(geometry_layers, view_spec)
    if view_spec.get("layer_type") or view_spec.get("layer_name"):
        add(
            "selected_geometry_layers_found",
            not selected.empty,
            "Selected geometry layer(s) were found.",
        )
        if not selected.empty:
            missing_hdf = selected.loc[selected["geometry_hdf_exists"] != True]
            add(
                "selected_geometry_hdf_exists",
                missing_hdf.empty,
                "Selected geometry layer HDF files exist.",
            )
            if any(
                view_spec.get(key) is not None
                for key in ("feature_id", "feature_name", "feature_index")
            ):
                selected_features = _features_for_selected_layers(selected)
                selected_features = _select_features_from_catalog(
                    selected_features,
                    feature_id=view_spec.get("feature_id"),
                    feature_name=view_spec.get("feature_name"),
                    feature_index=view_spec.get("feature_index"),
                )
                add(
                    "selected_geometry_features_found",
                    not selected_features.empty,
                    "Selected geometry feature(s) were found.",
                )

    if _has_result_selector(view_spec):
        selected_results = _select_result_rows(result_layers, view_spec)
        add(
            "selected_result_layers_found",
            not selected_results.empty,
            "Selected result layer(s) were found.",
        )

    if _has_map_selector(view_spec):
        selected_maps = _select_map_rows(map_layers, view_spec)
        add(
            "selected_map_layers_found",
            not selected_maps.empty,
            "Selected map layer(s) were found.",
        )

    terrain_name = view_spec.get("terrain_name")
    if view_spec.get("include_terrain") and terrain_name:
        root = _parse_existing_rasmap(project_paths.rasmap_path)
        terrain_names = [
            layer.attrib.get("Name", "")
            for layer in root.findall("./Terrains/Layer")
            if layer.attrib.get("Type") == "TerrainLayer"
        ]
        add(
            "selected_terrain_found",
            terrain_name in terrain_names,
            f"Selected terrain layer exists: {terrain_name}",
        )

    if not map_layers.empty and "is_geojson" in map_layers:
        geojson_layers = map_layers.loc[map_layers["is_geojson"] == True]
        for row in geojson_layers.to_dict(orient="records"):
            resolved_path = row.get("resolved_path")
            if not resolved_path:
                add(
                    "geojson_wgs84",
                    False,
                    f"GeoJSON layer has no resolved path: {row.get('name')}",
                )
                continue
            try:
                _mlh.validate_geojson_is_wgs84(resolved_path)
                add(
                    "geojson_wgs84",
                    True,
                    f"GeoJSON layer is WGS84-compatible: {row.get('name')}",
                    severity="info",
                )
            except Exception as exc:
                add(
                    "geojson_wgs84",
                    False,
                    f"GeoJSON layer is not WGS84-compatible: {row.get('name')} ({exc})",
                )

    return checks


def _select_geometry_rows(
    geometry_layers: pd.DataFrame,
    view_spec: dict[str, Any],
) -> pd.DataFrame:
    if geometry_layers.empty:
        return geometry_layers
    selected = geometry_layers.loc[geometry_layers["category"] == "geometry_element"].copy()
    layer_types = set(view_spec.get("layer_type") or [])
    if layer_types:
        selected = selected.loc[selected["layer_type"].isin(layer_types)]
    layer_name = view_spec.get("layer_name")
    if layer_name:
        selected = selected.loc[
            selected["layer_name"].fillna("").str.casefold() == layer_name.casefold()
        ]
    geometry_name = view_spec.get("geometry_name")
    if geometry_name:
        selected = selected.loc[
            selected["geometry_name"].fillna("").str.casefold()
            == geometry_name.casefold()
        ]
    geometry_number = view_spec.get("geometry_number")
    if geometry_number:
        selected = selected.loc[
            selected["geometry_number"].fillna("").map(_normalize_geometry_number)
            == _normalize_geometry_number(geometry_number)
        ]
    return selected


def _select_result_rows(
    result_layers: pd.DataFrame,
    view_spec: dict[str, Any],
) -> pd.DataFrame:
    if result_layers.empty:
        return result_layers
    selected = result_layers.copy()
    plan_names = {str(value).casefold() for value in view_spec.get("result_plan_name") or []}
    layer_names = {str(value).casefold() for value in view_spec.get("result_layer_name") or []}
    layer_types = set(view_spec.get("result_layer_type") or [])
    has_selector = bool(plan_names or layer_names or layer_types)
    if not has_selector and not view_spec.get("include_results"):
        return selected.iloc[0:0].copy()
    if plan_names:
        selected = selected.loc[
            selected["plan_name"].fillna("").str.casefold().isin(plan_names)
        ]
    if layer_names:
        selected = selected.loc[
            selected["layer_name"].fillna("").str.casefold().isin(layer_names)
        ]
    if layer_types:
        selected = selected.loc[selected["layer_type"].isin(layer_types)]
    return selected


def _select_map_rows(
    map_layers: pd.DataFrame,
    view_spec: dict[str, Any],
) -> pd.DataFrame:
    if map_layers.empty:
        return map_layers
    selected = map_layers.copy()
    names = {str(value).casefold() for value in view_spec.get("map_layer_name") or []}
    types = set(view_spec.get("map_layer_type") or [])
    categories = set(view_spec.get("map_layer_category") or [])
    has_selector = bool(names or types or categories)
    if not has_selector and not view_spec.get("include_map_layers"):
        return selected.iloc[0:0].copy()
    if names:
        selected = selected.loc[selected["name"].fillna("").str.casefold().isin(names)]
    if types:
        selected = selected.loc[selected["type"].isin(types)]
    if categories:
        selected = selected.loc[selected["category"].isin(categories)]
    return selected


def _features_for_selected_layers(geometry_layers: pd.DataFrame) -> pd.DataFrame:
    if geometry_layers.empty:
        return pd.DataFrame(columns=GEOMETRY_FEATURE_COLUMNS)
    frames: list[pd.DataFrame] = []
    elements = geometry_layers.loc[geometry_layers["category"] == "geometry_element"]
    for record in elements.to_dict(orient="records"):
        hdf_path = record.get("geometry_hdf_path")
        layer_type = record.get("layer_type")
        if not hdf_path or not layer_type:
            continue
        try:
            features = list_geometry_features(hdf_path, layer_type=layer_type)
        except Exception as exc:
            logger.debug(
                "Could not list geometry features for %s %s: %s",
                hdf_path,
                layer_type,
                exc,
            )
            continue
        if not features.empty:
            features["layer_id"] = record.get("layer_id")
            features["geometry_name"] = record.get("geometry_name")
            features["geometry_number"] = record.get("geometry_number")
            frames.append(features)
    if not frames:
        columns = GEOMETRY_FEATURE_COLUMNS + [
            "layer_id",
            "geometry_name",
            "geometry_number",
        ]
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _has_feature_selector(
    *,
    feature_id: Optional[str],
    feature_name: Optional[str],
    feature_index: Optional[int],
) -> bool:
    return any(value is not None for value in (feature_id, feature_name, feature_index))


def _has_result_selector(view_spec: dict[str, Any]) -> bool:
    return any(
        view_spec.get(key)
        for key in ("result_plan_name", "result_layer_name", "result_layer_type")
    )


def _has_map_selector(view_spec: dict[str, Any]) -> bool:
    return any(
        view_spec.get(key)
        for key in ("map_layer_name", "map_layer_type", "map_layer_category")
    )


def _select_features_from_catalog(
    features: pd.DataFrame,
    *,
    feature_id: Optional[str],
    feature_name: Optional[str],
    feature_index: Optional[int],
) -> pd.DataFrame:
    if features.empty:
        return features
    if not any(value is not None for value in (feature_id, feature_name, feature_index)):
        return features.iloc[0:0].copy()
    return _select_feature_rows(
        features,
        feature_id=feature_id,
        feature_name=feature_name,
        feature_index=feature_index,
    )


def _combined_layer_catalog(
    geometry_layers: pd.DataFrame,
    result_layers: pd.DataFrame,
    map_layers: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in geometry_layers.to_dict(orient="records"):
        records.append(
            {
                "source": "geometry",
                "category": row.get("category"),
                "name": row.get("layer_name") or row.get("geometry_name"),
                "type": row.get("layer_type"),
                "checked": row.get("checked"),
                "path": row.get("geometry_hdf_path"),
            }
        )
    for row in result_layers.to_dict(orient="records"):
        records.append(
            {
                "source": "result",
                "category": row.get("category"),
                "name": row.get("layer_name") or row.get("plan_name"),
                "type": row.get("layer_type"),
                "checked": row.get("checked"),
                "path": row.get("filename") or row.get("plan_filename"),
            }
        )
    for row in map_layers.to_dict(orient="records"):
        records.append(
            {
                "source": "map",
                "category": row.get("category"),
                "name": row.get("name"),
                "type": row.get("type"),
                "checked": row.get("checked"),
                "path": row.get("resolved_path") or row.get("filename"),
            }
        )
    return pd.DataFrame(
        records,
        columns=["source", "category", "name", "type", "checked", "path"],
    )


def _write_dataframe(df: pd.DataFrame, output_path: Union[str, Path]) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)


def _write_review_state(state: dict[str, Any], output_path: Union[str, Path]) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(_json_ready(state), indent=2),
        encoding="utf-8",
    )


def _write_findings_template(state: dict[str, Any], output_path: Union[str, Path]) -> None:
    lines = [
        f"# RASMapper Spatial Review: {state['project_name']}",
        "",
        "## Snapshot Setup",
        f"- Project: {state['project_folder']}",
        f"- RASMapper file: {state['rasmap_path']}",
        f"- Geometry number: {state['view_spec'].get('geometry_number')}",
        f"- Geometry name: {state['view_spec'].get('geometry_name')}",
        f"- Layers: {', '.join(state['view_spec'].get('layer_type') or [])}",
        f"- Feature id: {state['view_spec'].get('feature_id')}",
        f"- Feature name: {state['view_spec'].get('feature_name')}",
        f"- Feature index: {state['view_spec'].get('feature_index')}",
        f"- Terrain: {state['view_spec'].get('terrain_name')}",
        f"- Result plans: {', '.join(state['view_spec'].get('result_plan_name') or [])}",
        f"- Result layers: {', '.join(state['view_spec'].get('result_layer_name') or [])}",
        f"- Map layers: {', '.join(state['view_spec'].get('map_layer_name') or [])}",
        f"- Map categories: {', '.join(state['view_spec'].get('map_layer_category') or [])}",
        f"- Update legend with view: {state['view_spec'].get('update_legend_with_view')}",
        f"- View bounds: {state.get('current_view_after')}",
        f"- Snapshot: {state['snapshot'].get('path')}",
        "",
        "## Preflight",
    ]
    for check in state.get("preflight", []):
        marker = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {marker} {check.get('code')}: {check.get('message')}")

    lines.extend(
        [
            "",
            "## Findings",
            "- [Confirmed/Likely/Uncertain] Add spatial QA findings here.",
            "",
            "## Follow-Up Checks",
            "- Add numerical checks needed to confirm visual issues.",
            "",
            "## Artifacts",
        ]
    )
    for name, path in state.get("artifacts", {}).items():
        lines.append(f"- {name}: {path}")
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot_summary(snapshot_path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "file_size": snapshot_path.stat().st_size if snapshot_path.exists() else 0,
        "width": None,
        "height": None,
        "probably_blank": None,
    }
    try:
        from PIL import Image

        with Image.open(snapshot_path) as image:
            summary["width"], summary["height"] = image.size
            extrema = image.convert("L").getextrema()
            if extrema is not None:
                summary["luminance_min"] = int(extrema[0])
                summary["luminance_max"] = int(extrema[1])
                summary["probably_blank"] = (extrema[1] - extrema[0]) < 5
    except Exception as exc:
        summary["diagnostic_error"] = str(exc)
    return summary


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if value is pd.NA:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _empty_view(project_paths: Any) -> dict[str, Any]:
    return {
        "rasmap_path": str(project_paths.rasmap_path),
        "projection_path": (
            str(project_paths.projection_path)
            if project_paths.projection_path is not None
            else None
        ),
        "min_x": None,
        "max_x": None,
        "min_y": None,
        "max_y": None,
        "width": None,
        "height": None,
        "has_current_view": False,
    }


def _parse_existing_rasmap(rasmap_path: Path) -> ET.Element:
    if not rasmap_path.exists():
        raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")
    return ET.parse(rasmap_path).getroot()


def _load_existing_rasmap_tree(rasmap_path: Path) -> tuple[ET.ElementTree, ET.Element]:
    if not rasmap_path.exists():
        raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")
    tree = ET.parse(rasmap_path)
    return tree, tree.getroot()


def _write_rasmap_tree(tree: ET.ElementTree, rasmap_path: Path) -> None:
    tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)


def _insert_current_view(root: ET.Element, view: ET.Element) -> None:
    velocity_settings = root.find("VelocitySettings")
    if velocity_settings is not None:
        root.insert(list(root).index(velocity_settings), view)
        return
    root.append(view)


def _geometry_record(
    project_paths: Any,
    geometry_layer: ET.Element,
    geometry_index: int,
    *,
    layer_index: Optional[int],
    child_layer: Optional[ET.Element] = None,
) -> dict[str, Any]:
    geometry_filename = geometry_layer.attrib.get("Filename", "")
    geometry_path = _lch.resolve_rasmap_relative_path(
        project_paths.project_folder,
        geometry_filename,
    )
    geometry_number = _geometry_number_from_filename(geometry_filename)
    geometry_name = geometry_layer.attrib.get("Name", "")

    if child_layer is None:
        layer_type = geometry_layer.attrib.get("Type", "")
        layer_name = geometry_name
        category = "geometry"
        checked = _bool_or_none(geometry_layer.attrib.get("Checked"))
        expanded = _bool_or_none(geometry_layer.attrib.get("Expanded"))
        parent_identifiers = ""
        layer_id = f"geometry:{geometry_index}"
    else:
        layer_type = child_layer.attrib.get("Type", "")
        layer_name = child_layer.attrib.get("Name", "")
        category = "geometry_element"
        checked = _bool_or_none(child_layer.attrib.get("Checked"))
        expanded = _bool_or_none(child_layer.attrib.get("Expanded"))
        parent_identifiers = child_layer.attrib.get("ParentIdentifiers", "")
        layer_id = f"geometry:{geometry_index}:layer:{layer_index}:{layer_type}"
        if layer_name:
            layer_id += f":{layer_name}"

    return {
        "layer_id": layer_id,
        "category": category,
        "geometry_name": geometry_name,
        "geometry_number": geometry_number,
        "geometry_filename": geometry_filename,
        "geometry_hdf_path": str(geometry_path) if geometry_path is not None else None,
        "geometry_hdf_exists": bool(geometry_path and geometry_path.exists()),
        "layer_name": layer_name,
        "layer_type": layer_type,
        "checked": checked,
        "expanded": expanded,
        "geometry_index": geometry_index,
        "layer_index": layer_index,
        "parent_identifiers": parent_identifiers,
    }


def _result_layer_records(
    layer: ET.Element,
    *,
    result_index: int,
    index_path: tuple[int, ...],
    ancestor_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    record = _result_layer_record(
        layer,
        result_index=result_index,
        index_path=index_path,
        ancestor_names=ancestor_names,
    )
    records = [record]
    child_ancestor_names = ancestor_names + (layer.attrib.get("Name", ""),)
    for child_index, child_layer in enumerate(layer.findall("Layer")):
        records.extend(
            _result_layer_records(
                child_layer,
                result_index=result_index,
                index_path=index_path + (child_index,),
                ancestor_names=child_ancestor_names,
            )
        )
    return records


def _result_layer_refs(
    layer: ET.Element,
    *,
    result_index: int,
    index_path: tuple[int, ...],
    ancestors: tuple[ET.Element, ...],
    ancestor_names: tuple[str, ...],
) -> list[tuple[ET.Element, tuple[ET.Element, ...], dict[str, Any]]]:
    record = _result_layer_record(
        layer,
        result_index=result_index,
        index_path=index_path,
        ancestor_names=ancestor_names,
    )
    refs = [(layer, ancestors, record)]
    child_ancestor_names = ancestor_names + (layer.attrib.get("Name", ""),)
    for child_index, child_layer in enumerate(layer.findall("Layer")):
        refs.extend(
            _result_layer_refs(
                child_layer,
                result_index=result_index,
                index_path=index_path + (child_index,),
                ancestors=ancestors + (layer,),
                ancestor_names=child_ancestor_names,
            )
        )
    return refs


def _result_layer_record(
    layer: ET.Element,
    *,
    result_index: int,
    index_path: tuple[int, ...],
    ancestor_names: tuple[str, ...],
) -> dict[str, Any]:
    layer_name = layer.attrib.get("Name", "")
    layer_type = layer.attrib.get("Type", "")
    plan_name = ancestor_names[0] if ancestor_names else layer_name
    plan_filename = layer.attrib.get("Filename", "") if not ancestor_names else ""
    category = "result_plan" if not index_path else "result_layer"
    layer_index = ".".join(str(index) for index in index_path)
    layer_id = f"result:{result_index}"
    if index_path:
        layer_id += f":layer:{layer_index}:{layer_type}"
        if layer_name:
            layer_id += f":{layer_name}"
    return {
        "layer_id": layer_id,
        "category": category,
        "plan_name": plan_name,
        "plan_filename": plan_filename,
        "layer_name": layer_name,
        "layer_type": layer_type,
        "checked": _bool_or_none(layer.attrib.get("Checked")),
        "expanded": _bool_or_none(layer.attrib.get("Expanded")),
        "result_index": result_index,
        "layer_index": layer_index,
        "depth": len(index_path),
        "layer_path": "/".join((*ancestor_names, layer_name)),
        "filename": layer.attrib.get("Filename", ""),
        "parent_identifiers": layer.attrib.get("ParentIdentifiers", ""),
        "profile_index": layer.attrib.get("ProfileIndex", ""),
    }


def _result_layer_matches(
    record: dict[str, Any],
    *,
    layer_id: Optional[str],
    plan_names: Optional[set[str]],
    layer_names: Optional[set[str]],
    layer_types: Optional[set[str]],
) -> bool:
    if layer_id is not None and record["layer_id"] != layer_id:
        return False
    if plan_names is not None and str(record.get("plan_name") or "").casefold() not in plan_names:
        return False
    if layer_names is not None and str(record.get("layer_name") or "").casefold() not in layer_names:
        return False
    if layer_types is not None and record.get("layer_type") not in layer_types:
        return False
    return True


def _geometry_number_from_filename(filename: str) -> str:
    match = _GEOMETRY_NUMBER_PATTERN.search(filename or "")
    return match.group(1) if match else ""


def _geometry_matches(
    geometry_layer: ET.Element,
    geometry_name: Optional[str],
    geometry_number: Optional[str],
) -> bool:
    if geometry_name is not None:
        if geometry_layer.attrib.get("Name", "").casefold() != geometry_name.casefold():
            return False
    if geometry_number is not None:
        filename = geometry_layer.attrib.get("Filename", "")
        if _normalize_geometry_number(_geometry_number_from_filename(filename)) != (
            _normalize_geometry_number(geometry_number)
        ):
            return False
    return True


def _child_layer_matches(
    record: dict[str, Any],
    layer_id: Optional[str],
    layer_types: Optional[set[str]],
    layer_name: Optional[str],
) -> bool:
    if layer_id is not None and record["layer_id"] != layer_id:
        return False
    if layer_types is not None and record["layer_type"] not in layer_types:
        return False
    if layer_name is not None:
        if str(record.get("layer_name") or "").casefold() != layer_name.casefold():
            return False
    return True


def _normalize_string_filter(
    value: Optional[Union[str, Sequence[str]]],
) -> Optional[set[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _normalize_casefold_filter(
    value: Optional[Union[str, Sequence[str]]],
) -> Optional[set[str]]:
    values = _normalize_string_filter(value)
    if values is None:
        return None
    return {item.casefold() for item in values}


def _normalize_geometry_number(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    if text.startswith("g"):
        text = text[1:]
    return text.zfill(2) if text.isdigit() else text


def _resolve_layer_dataset_paths(hdf_file: h5py.File, layer_type: str) -> list[str]:
    patterns = GEOMETRY_LAYER_DATASET_ALIASES.get(layer_type, ())
    paths: list[str] = []
    for pattern in patterns:
        paths.extend(_expand_dataset_pattern(hdf_file, pattern))
    return paths


def _expand_dataset_pattern(hdf_file: h5py.File, pattern: str) -> list[str]:
    if "*" not in pattern:
        return [pattern] if pattern in hdf_file else []

    prefix, suffix = pattern.split("*", 1)
    matches: list[str] = []

    def visit(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Dataset):
            return
        full_name = "/" + name if pattern.startswith("/") else name
        comparable = full_name.lstrip("/")
        if comparable.startswith(prefix) and comparable.endswith(suffix):
            matches.append(comparable)

    hdf_file.visititems(visit)
    return matches


def _all_coordinate_dataset_paths(hdf_file: h5py.File) -> list[str]:
    paths: list[str] = []

    def visit(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Dataset):
            return
        lowered = name.casefold()
        if not name.startswith("Geometry/"):
            return
        if any(
            token in lowered
            for token in (
                "points",
                "coordinate",
                "perimeter",
                "centerline",
            )
        ):
            if len(obj.shape) == 2 and obj.shape[1] >= 2 and np.issubdtype(obj.dtype, np.number):
                paths.append(name)

    hdf_file.visititems(visit)
    return paths


def _bounds_from_datasets(
    hdf_file: h5py.File,
    dataset_paths: Sequence[str],
    *,
    layer_type: Optional[str],
) -> Optional[tuple[float, float, float, float, int]]:
    arrays: list[np.ndarray] = []
    for path in dataset_paths:
        if path not in hdf_file:
            continue
        data = np.asarray(hdf_file[path])
        if data.ndim != 2 or data.shape[1] < 2 or data.size == 0:
            continue
        if not np.issubdtype(data.dtype, np.number):
            continue
        if layer_type == "LateralStructureLayer" and path == "Geometry/Structures/Centerline Points":
            data = _lateral_structure_centerline_points(hdf_file)
            if data.size == 0:
                continue
        arrays.append(data[:, :2].astype(float))

    if not arrays:
        return None

    points = np.vstack(arrays)
    finite_mask = np.isfinite(points[:, 0]) & np.isfinite(points[:, 1])
    points = points[finite_mask]
    if points.size == 0:
        return None

    return (
        float(np.min(points[:, 0])),
        float(np.min(points[:, 1])),
        float(np.max(points[:, 0])),
        float(np.max(points[:, 1])),
        int(points.shape[0]),
    )


def _feature_records_for_layer(
    hdf_file: h5py.File,
    hdf_path: Path,
    layer_type: str,
) -> list[dict[str, Any]]:
    if layer_type == "RASD2FlowArea":
        return _flow_area_feature_records(hdf_file, hdf_path, layer_type)
    if layer_type in {
        "RASD2BreakLine",
        "RAS2DBreakLines",
        "RASBreakLines",
        "BreakLineLayer",
    }:
        return _polyline_feature_records(
            hdf_file,
            hdf_path,
            layer_type,
            group_path="Geometry/2D Flow Area Break Lines",
            name_fields=("Name",),
        )
    if layer_type == "RASXS":
        return _polyline_feature_records(
            hdf_file,
            hdf_path,
            layer_type,
            group_path="Geometry/Cross Sections",
            name_fields=("River", "Reach", "RS"),
            station_field="RS",
        )
    if layer_type in {
        "StructureLayer",
        "SA2DStructureLayer",
        "LateralStructureLayer",
        "InlineStructureLayer",
    }:
        return _structure_feature_records(hdf_file, hdf_path, layer_type)
    return []


def _flow_area_feature_records(
    hdf_file: h5py.File,
    hdf_path: Path,
    layer_type: str,
) -> list[dict[str, Any]]:
    group_path = "Geometry/2D Flow Areas"
    return _polyline_feature_records(
        hdf_file,
        hdf_path,
        layer_type,
        group_path=group_path,
        info_name="Polygon Info",
        points_name="Polygon Points",
        name_fields=("Name",),
    )


def _structure_feature_records(
    hdf_file: h5py.File,
    hdf_path: Path,
    layer_type: str,
) -> list[dict[str, Any]]:
    group_path = "Geometry/Structures"
    attr_path = f"{group_path}/Attributes"
    info_path = f"{group_path}/Centerline Info"
    points_path = f"{group_path}/Centerline Points"
    if not all(path in hdf_file for path in (attr_path, info_path, points_path)):
        return []

    attrs = hdf_file[attr_path][:]
    info = np.asarray(hdf_file[info_path])
    points = np.asarray(hdf_file[points_path])
    records: list[dict[str, Any]] = []
    for index, info_row in enumerate(info):
        row = attrs[index] if index < len(attrs) else None
        feature_type = _attribute_value(row, "Type")
        if layer_type == "LateralStructureLayer":
            if not feature_type.casefold().startswith("lateral"):
                continue
        elif layer_type == "InlineStructureLayer":
            if not feature_type.casefold().startswith("inline"):
                continue

        feature_points = _points_from_info_row(points, info_row)
        records.append(
            _feature_record(
                hdf_path,
                layer_type,
                index,
                feature_points,
                coordinate_dataset_path=points_path,
                info_dataset_path=info_path,
                feature_name=_structure_feature_name(row, feature_type, index),
                feature_type=feature_type,
                river=_attribute_value(row, "River"),
                reach=_attribute_value(row, "Reach"),
                station=_attribute_value(row, "RS"),
            )
        )
    return records


def _polyline_feature_records(
    hdf_file: h5py.File,
    hdf_path: Path,
    layer_type: str,
    *,
    group_path: str,
    info_name: str = "Polyline Info",
    points_name: str = "Polyline Points",
    name_fields: Sequence[str] = ("Name",),
    station_field: Optional[str] = None,
) -> list[dict[str, Any]]:
    attr_path = f"{group_path}/Attributes"
    info_path = f"{group_path}/{info_name}"
    points_path = f"{group_path}/{points_name}"
    if not all(path in hdf_file for path in (info_path, points_path)):
        return []

    attrs = hdf_file[attr_path][:] if attr_path in hdf_file else None
    info = np.asarray(hdf_file[info_path])
    points = np.asarray(hdf_file[points_path])
    records: list[dict[str, Any]] = []
    for index, info_row in enumerate(info):
        row = attrs[index] if attrs is not None and index < len(attrs) else None
        feature_points = _points_from_info_row(points, info_row)
        records.append(
            _feature_record(
                hdf_path,
                layer_type,
                index,
                feature_points,
                coordinate_dataset_path=points_path,
                info_dataset_path=info_path,
                feature_name=_feature_name_from_fields(row, name_fields, index),
                feature_type=_attribute_value(row, "Type"),
                river=_attribute_value(row, "River"),
                reach=_attribute_value(row, "Reach"),
                station=_attribute_value(row, station_field),
            )
        )
    return records


def _feature_record(
    hdf_path: Path,
    layer_type: str,
    feature_index: int,
    points: np.ndarray,
    *,
    coordinate_dataset_path: str,
    info_dataset_path: str,
    feature_name: str,
    feature_type: str = "",
    river: str = "",
    reach: str = "",
    station: str = "",
) -> dict[str, Any]:
    bounds = _points_bounds(points)
    base = {
        "feature_id": f"{layer_type}:{feature_index}:{feature_name}",
        "layer_type": layer_type,
        "feature_index": feature_index,
        "feature_name": feature_name,
        "feature_type": feature_type,
        "river": river,
        "reach": reach,
        "station": station,
        "geometry_hdf_path": str(hdf_path),
        "coordinate_dataset_path": coordinate_dataset_path,
        "info_dataset_path": info_dataset_path,
        "min_x": None,
        "min_y": None,
        "max_x": None,
        "max_y": None,
        "width": None,
        "height": None,
        "point_count": 0,
        "has_bounds": False,
    }
    if bounds is None:
        return base

    min_x, min_y, max_x, max_y, point_count = bounds
    base.update(
        {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
            "point_count": point_count,
            "has_bounds": True,
        }
    )
    return base


def _points_from_info_row(points: np.ndarray, info_row: np.ndarray) -> np.ndarray:
    if len(info_row) < 2:
        return np.empty((0, 2), dtype=float)
    start = int(info_row[0])
    count = int(info_row[1])
    if count <= 0:
        return np.empty((0, 2), dtype=float)
    return np.asarray(points[start : start + count, :2], dtype=float)


def _points_bounds(points: np.ndarray) -> Optional[tuple[float, float, float, float, int]]:
    if points.size == 0 or points.ndim != 2 or points.shape[1] < 2:
        return None
    finite_mask = np.isfinite(points[:, 0]) & np.isfinite(points[:, 1])
    points = points[finite_mask]
    if points.size == 0:
        return None
    return (
        float(np.min(points[:, 0])),
        float(np.min(points[:, 1])),
        float(np.max(points[:, 0])),
        float(np.max(points[:, 1])),
        int(points.shape[0]),
    )


def _feature_name_from_fields(
    row: Any,
    fields: Sequence[str],
    index: int,
) -> str:
    values = [_attribute_value(row, field) for field in fields]
    text = " ".join(value for value in values if value).strip()
    return text or f"feature_{index}"


def _structure_feature_name(row: Any, feature_type: str, index: int) -> str:
    for fields in (
        ("Connection",),
        ("Node Name",),
        ("Groupname",),
        ("River", "Reach", "RS"),
        ("Description",),
    ):
        text = _feature_name_from_fields(row, fields, index)
        if text != f"feature_{index}":
            return text
    return f"{feature_type or 'Structure'} {index}".strip()


def _attribute_value(row: Any, field: Optional[str]) -> str:
    if row is None or field is None:
        return ""
    names = getattr(row.dtype, "names", None)
    if not names or field not in names:
        return ""
    return _decode_hdf_string(row[field])


def _select_feature_rows(
    features: pd.DataFrame,
    *,
    feature_id: Optional[str],
    feature_name: Optional[str],
    feature_index: Optional[int],
) -> pd.DataFrame:
    selected = features.copy()
    if feature_id is not None:
        selected = selected.loc[selected["feature_id"] == feature_id]
    if feature_name is not None:
        selected = selected.loc[
            selected["feature_name"].fillna("").str.casefold()
            == feature_name.casefold()
        ]
    if feature_index is not None:
        selected = selected.loc[selected["feature_index"] == int(feature_index)]
    return selected


def _lateral_structure_centerline_points(hdf_file: h5py.File) -> np.ndarray:
    required = (
        "Geometry/Structures/Attributes",
        "Geometry/Structures/Centerline Info",
        "Geometry/Structures/Centerline Points",
    )
    if not all(path in hdf_file for path in required):
        return np.empty((0, 2), dtype=float)

    attrs = hdf_file["Geometry/Structures/Attributes"][:]
    info = np.asarray(hdf_file["Geometry/Structures/Centerline Info"])
    points = np.asarray(hdf_file["Geometry/Structures/Centerline Points"])
    if "Type" not in attrs.dtype.names:
        return points[:, :2]

    selected: list[np.ndarray] = []
    for index, row in enumerate(attrs):
        type_value = _decode_hdf_string(row["Type"]).casefold()
        if not type_value.startswith("lateral"):
            continue
        if index >= len(info):
            continue
        start = int(info[index][0])
        count = int(info[index][1])
        selected.append(points[start : start + count, :2])

    if not selected:
        return np.empty((0, 2), dtype=float)
    return np.vstack(selected)


def _decode_hdf_string(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore").strip("\x00 ")
    if hasattr(value, "decode"):
        return value.decode("utf-8", "ignore").strip("\x00 ")
    return str(value).strip("\x00 ")


def _combine_bounds(records: Sequence[dict[str, Any]]) -> tuple[float, float, float, float]:
    return (
        min(float(record["min_x"]) for record in records),
        min(float(record["min_y"]) for record in records),
        max(float(record["max_x"]) for record in records),
        max(float(record["max_y"]) for record in records),
    )


def _pad_bounds(
    bounds: tuple[float, float, float, float],
    padding_fraction: float,
    min_padding: float,
) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = _normalize_bounds(bounds)
    width = max(max_x - min_x, 0.0)
    height = max(max_y - min_y, 0.0)
    pad_x = max(width * padding_fraction, min_padding)
    pad_y = max(height * padding_fraction, min_padding)
    if width == 0:
        pad_x = max(pad_x, 1.0)
    if height == 0:
        pad_y = max(pad_y, 1.0)
    return min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y


def _resolve_view_padding_fraction(
    *,
    use_feature_bounds: bool,
    padding_fraction: Optional[float],
) -> float:
    if padding_fraction is not None:
        return float(padding_fraction)
    if use_feature_bounds:
        return DEFAULT_FEATURE_PADDING_FRACTION
    return DEFAULT_LAYER_PADDING_FRACTION


def _normalize_bounds(
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = [float(value) for value in bounds]
    return min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y)


def _find_rasmapper_windows(*, pid: Optional[int] = None) -> list[int]:
    try:
        import win32gui
        import win32process
    except ImportError:
        logger.error("pywin32 is required to locate RASMapper windows")
        return []

    matches: list[int] = []

    def callback(hwnd: int, _extra: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if "ras mapper" not in title.casefold():
            return
        if pid is not None:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid != pid:
                return
        matches.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return matches


def _bool_attr(value: bool) -> str:
    return "True" if value else "False"


def _bool_or_none(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().casefold() == "true"


def _coerce_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _range_or_none(min_value: Optional[float], max_value: Optional[float]) -> Optional[float]:
    if min_value is None or max_value is None:
        return None
    return max_value - min_value


def _format_float(value: float) -> str:
    return f"{float(value):.15g}"
