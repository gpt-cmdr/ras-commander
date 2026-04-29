"""Internal helpers for RASMapper map-layer XML workflows."""

from __future__ import annotations

import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

import pandas as pd

from . import _land_classification_helper as _lch
from .LoggingConfig import get_logger
from .RasUtils import RasUtils

logger = get_logger(__name__)

REFERENCE_MAP_LAYER_TYPES = frozenset(
    {
        "PointFeatureLayer",
        "PolylineFeatureLayer",
        "PolygonFeatureLayer",
    }
)
BASEMAP_LAYER_TYPE = "WMSLayer"

STANDARD_BASEMAP_LAYERS: dict[str, str] = {
    "Google Hybrid": r"%LocalAppData%\HEC\Mapping\5.1\XML\Google Hybrid.xml",
    "Bing Satellite": r"%LocalAppData%\HEC\Mapping\5.1\XML\Bing Satellite.xml",
    "ArcGIS NatGeo World Map": (
        r"%LocalAppData%\HEC\Mapping\5.1\XML\ArcGIS NatGeo World Map.xml"
    ),
    "ArcGIS USA Topo Maps": (
        r"%LocalAppData%\HEC\Mapping\5.1\XML\ArcGIS USA Topo Maps.xml"
    ),
    "Google Terrain Streets Water": (
        r"%LocalAppData%\HEC\Mapping\5.1\XML\Google Terrain Streets Water.xml"
    ),
    "OpenStreetMaps": r"%LocalAppData%\HEC\Mapping\5.1\XML\OpenStreetMaps.xml",
    "USGS Imagery": r"%LocalAppData%\HEC\Mapping\5.1\XML\USGS Imagery.xml",
    "USGS Topo": r"%LocalAppData%\HEC\Mapping\5.1\XML\USGS Topo.xml",
}

MAP_LAYER_COLUMNS = [
    "name",
    "type",
    "category",
    "checked",
    "filename",
    "resolved_path",
    "exists",
    "source_extension",
    "resample_method",
    "position",
    "is_standard_basemap",
    "is_reference_layer",
    "is_geojson",
]


def list_available_basemaps() -> pd.DataFrame:
    """Return the standard HEC-RAS 6.x basemap entries observed in .rasmap XML."""
    return pd.DataFrame(
        [
            {
                "name": name,
                "type": BASEMAP_LAYER_TYPE,
                "filename": filename,
                "resample_method": "near",
            }
            for name, filename in STANDARD_BASEMAP_LAYERS.items()
        ]
    )


def list_map_layers(ras_project_path: Union[str, Path]) -> pd.DataFrame:
    """List top-level MapLayers entries from a project .rasmap file."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    if not project_paths.rasmap_path.exists():
        return pd.DataFrame(columns=MAP_LAYER_COLUMNS)

    root = ET.parse(project_paths.rasmap_path).getroot()
    map_layers = root.find("MapLayers")
    if map_layers is None:
        return pd.DataFrame(columns=MAP_LAYER_COLUMNS)

    records = []
    for position, layer in enumerate(map_layers.findall("Layer")):
        records.append(_build_map_layer_record(project_paths, layer, position))

    return pd.DataFrame(records, columns=MAP_LAYER_COLUMNS)


def list_reference_map_layers(ras_project_path: Union[str, Path]) -> pd.DataFrame:
    """List shapefile/GeoJSON-style reference layers in MapLayers."""
    layers = list_map_layers(ras_project_path)
    if layers.empty:
        return layers
    return layers.loc[layers["category"] == "reference"].copy()


def list_basemap_layers(ras_project_path: Union[str, Path]) -> pd.DataFrame:
    """List WMS basemap layers in MapLayers."""
    layers = list_map_layers(ras_project_path)
    if layers.empty:
        return layers
    return layers.loc[layers["category"] == "basemap"].copy()


def set_map_layer_visibility(
    ras_project_path: Union[str, Path],
    *,
    checked: bool,
    layer_name: Optional[Union[str, Sequence[str]]] = None,
    layer_type: Optional[Union[str, Sequence[str]]] = None,
    category: Optional[Union[str, Sequence[str]]] = None,
    exclusive: bool = False,
) -> int:
    """
    Set visibility for top-level RASMapper MapLayers entries.

    When no selector is supplied, all map layers are targeted. Use
    ``exclusive=True`` with ``checked=True`` to hide every non-matching map layer
    and show only the selected references, basemaps, or land-classification
    layers needed for a figure.
    """
    project_paths = _lch.resolve_project_paths(ras_project_path)
    tree, root = _load_rasmap_tree(project_paths.rasmap_path)
    map_layers = root.find("MapLayers")
    if map_layers is None:
        return 0

    names = _normalize_casefold_filter(layer_name)
    types = _normalize_string_filter(layer_type)
    categories = _normalize_string_filter(category)
    has_selector = any((names, types, categories))
    layers = list(map_layers.findall("Layer"))
    matches = [
        layer
        for layer in layers
        if _map_layer_matches(layer, names=names, types=types, categories=categories)
    ]
    if has_selector and not matches:
        return 0

    target_layers = matches if has_selector else layers
    modified = 0

    if exclusive and checked:
        for layer in layers:
            if layer.attrib.get("Checked") != "False":
                layer.set("Checked", "False")
                modified += 1

    target_value = _bool_attr(checked)
    for layer in target_layers:
        if layer.attrib.get("Checked") != target_value:
            layer.set("Checked", target_value)
            modified += 1

    if checked and target_layers:
        if map_layers.attrib.get("Checked") != "True":
            map_layers.set("Checked", "True")
            modified += 1
    elif not checked and not has_selector:
        if map_layers.attrib.get("Checked") != "False":
            map_layers.set("Checked", "False")
            modified += 1

    if modified:
        _write_rasmap_tree(tree, project_paths.rasmap_path)
    return modified


def add_reference_map_layer(
    ras_project_path: Union[str, Path],
    source_path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    layer_type: Optional[str] = None,
    checked: bool = True,
    label_field: Optional[str] = None,
    label_config: Optional[dict[str, Any]] = None,
    symbology: Optional[dict[str, Any]] = None,
    replace_existing: bool = True,
    validate_geojson_wgs84: bool = True,
) -> Path:
    """Add or replace a shapefile/GeoJSON reference layer in a project .rasmap."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    source = _resolve_source_path(project_paths.project_folder, source_path)

    if _is_geojson_path(source) and validate_geojson_wgs84:
        validate_geojson_is_wgs84(source)

    resolved_layer_type = layer_type or infer_reference_layer_type(source)
    if resolved_layer_type not in REFERENCE_MAP_LAYER_TYPES:
        raise ValueError(
            "layer_type must be one of: "
            + ", ".join(sorted(REFERENCE_MAP_LAYER_TYPES))
        )

    tree, root = _load_rasmap_tree(project_paths.rasmap_path)
    map_layers = _ensure_map_layers(root)
    name = layer_name or source.stem

    if replace_existing:
        _remove_existing_layers(
            map_layers,
            name=name,
            layer_types=REFERENCE_MAP_LAYER_TYPES,
        )

    layer_elem = ET.SubElement(
        map_layers,
        "Layer",
        {
            "Name": name,
            "Type": resolved_layer_type,
            "Checked": _bool_attr(checked),
            "Filename": _lch.to_rasmap_relative_path(
                project_paths.project_folder,
                source,
            ),
        },
    )
    _apply_label_config(layer_elem, label_field, label_config)
    _apply_symbology(layer_elem, symbology)

    _write_rasmap_tree(tree, project_paths.rasmap_path)
    logger.info("Added reference map layer '%s' to %s", name, project_paths.rasmap_path)
    return project_paths.rasmap_path


def add_basemap_layer(
    ras_project_path: Union[str, Path],
    basemap_name: str,
    *,
    checked: bool = True,
    replace_existing: bool = True,
    filename: Optional[str] = None,
) -> Path:
    """Add or replace one of the standard HEC-RAS 6.x basemap layers."""
    project_paths = _lch.resolve_project_paths(ras_project_path)
    canonical_name = _normalize_basemap_name(basemap_name)
    layer_filename = filename or STANDARD_BASEMAP_LAYERS[canonical_name]

    tree, root = _load_rasmap_tree(project_paths.rasmap_path)
    map_layers = _ensure_map_layers(root)

    if replace_existing:
        _remove_existing_layers(
            map_layers,
            name=canonical_name,
            layer_types={BASEMAP_LAYER_TYPE},
        )

    layer_elem = ET.SubElement(
        map_layers,
        "Layer",
        {
            "Name": canonical_name,
            "Type": BASEMAP_LAYER_TYPE,
            "Checked": _bool_attr(checked),
            "Filename": layer_filename,
        },
    )
    ET.SubElement(layer_elem, "ResampleMethod").text = "near"

    _write_rasmap_tree(tree, project_paths.rasmap_path)
    logger.info("Added basemap layer '%s' to %s", canonical_name, project_paths.rasmap_path)
    return project_paths.rasmap_path


def validate_geojson_is_wgs84(source_path: Union[str, Path]) -> dict[str, Any]:
    """
    Validate that a GeoJSON source is usable by RASMapper.

    RASMapper expects GeoJSON coordinates in WGS84 longitude/latitude. Many valid
    GeoJSON files omit an explicit CRS, so this accepts missing CRS metadata only
    when the coordinate bounds are compatible with lon/lat values.
    """
    source = RasUtils.safe_resolve(Path(source_path))
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid GeoJSON file: {source}") from exc

    bounds = _geojson_bounds(data)
    if bounds is None:
        raise ValueError(
            f"GeoJSON source must contain coordinates that can be validated as "
            f"WGS84/EPSG:4326 for RASMapper: {source}"
        )

    min_x, min_y, max_x, max_y = bounds
    if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
        raise ValueError(
            f"GeoJSON source must be WGS84/EPSG:4326 for RASMapper: {source}. "
            f"Coordinate bounds look projected, not lon/lat: {bounds}"
        )

    crs_name = _extract_geojson_crs_name(data)
    if crs_name:
        if _crs_name_is_wgs84(crs_name):
            return {
                "path": str(source),
                "passed": True,
                "crs": crs_name,
                "bounds": bounds,
                "inferred_from_bounds": False,
            }
        raise ValueError(
            f"GeoJSON source must be WGS84/EPSG:4326 for RASMapper: {source}. "
            f"Detected CRS: {crs_name}"
        )

    return {
        "path": str(source),
        "passed": True,
        "crs": None,
        "bounds": bounds,
        "inferred_from_bounds": True,
    }


def infer_reference_layer_type(source_path: Union[str, Path]) -> str:
    """Infer the RASMapper feature layer type for a vector source."""
    source = Path(source_path)
    suffix = source.suffix.lower()

    if suffix in {".geojson", ".json"}:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            geometry_type = _first_geojson_geometry_type(data)
        except (OSError, json.JSONDecodeError):
            geometry_type = None
        if geometry_type is not None:
            return _geometry_type_to_layer_type(geometry_type)

    if suffix == ".shp":
        shape_type = _read_shapefile_shape_type(source)
        if shape_type is not None:
            return _shapefile_shape_type_to_layer_type(shape_type)

    return "PolylineFeatureLayer"


def _build_map_layer_record(
    project_paths: Any,
    layer: ET.Element,
    position: int,
) -> dict[str, Any]:
    layer_type = layer.attrib.get("Type", "")
    filename = layer.attrib.get("Filename", "")
    resolved_path = _lch.resolve_rasmap_relative_path(
        project_paths.project_folder,
        filename,
    )
    category = _classify_map_layer(layer)
    source_extension = Path(str(filename)).suffix.lower() if filename else ""
    exists = False
    if resolved_path is not None:
        try:
            exists = resolved_path.exists()
        except OSError:
            exists = False

    name = layer.attrib.get("Name", "")
    return {
        "name": name,
        "type": layer_type,
        "category": category,
        "checked": layer.attrib.get("Checked", "False").lower() == "true",
        "filename": filename,
        "resolved_path": str(resolved_path) if resolved_path is not None else None,
        "exists": exists,
        "source_extension": source_extension,
        "resample_method": layer.findtext("ResampleMethod"),
        "position": position,
        "is_standard_basemap": (
            layer_type == BASEMAP_LAYER_TYPE
            and name in STANDARD_BASEMAP_LAYERS
            and filename == STANDARD_BASEMAP_LAYERS[name]
        ),
        "is_reference_layer": layer_type in REFERENCE_MAP_LAYER_TYPES,
        "is_geojson": source_extension in {".geojson", ".json"},
    }


def _classify_map_layer(layer: ET.Element) -> str:
    layer_type = layer.attrib.get("Type", "")
    if layer_type == BASEMAP_LAYER_TYPE:
        return "basemap"
    if layer_type in REFERENCE_MAP_LAYER_TYPES:
        return "reference"
    if layer_type == "LandCoverLayer":
        return "land_classification"
    return "other"


def _map_layer_matches(
    layer: ET.Element,
    *,
    names: Optional[set[str]],
    types: Optional[set[str]],
    categories: Optional[set[str]],
) -> bool:
    if names is not None and layer.attrib.get("Name", "").casefold() not in names:
        return False
    if types is not None and layer.attrib.get("Type", "") not in types:
        return False
    if categories is not None and _classify_map_layer(layer) not in categories:
        return False
    return True


def _load_rasmap_tree(rasmap_path: Path) -> tuple[ET.ElementTree, ET.Element]:
    if rasmap_path.exists():
        tree = ET.parse(rasmap_path)
        return tree, tree.getroot()

    root = ET.Element("RASMapper")
    tree = ET.ElementTree(root)
    return tree, root


def _ensure_map_layers(root: ET.Element) -> ET.Element:
    map_layers = root.find("MapLayers")
    if map_layers is not None:
        return map_layers

    map_layers = ET.Element("MapLayers", {"Checked": "True", "Expanded": "True"})
    results = root.find("Results")
    if results is not None:
        root.insert(list(root).index(results) + 1, map_layers)
    else:
        root.append(map_layers)
    return map_layers


def _write_rasmap_tree(tree: ET.ElementTree, rasmap_path: Path) -> None:
    tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)


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


def _remove_existing_layers(
    map_layers: ET.Element,
    *,
    name: str,
    layer_types: Iterable[str],
) -> None:
    layer_type_set = set(layer_types)
    for layer in list(map_layers.findall("Layer")):
        if layer.attrib.get("Name") == name and layer.attrib.get("Type") in layer_type_set:
            map_layers.remove(layer)


def _resolve_source_path(project_folder: Path, source_path: Union[str, Path]) -> Path:
    source = Path(source_path)
    if not source.is_absolute():
        source = project_folder / source
    source = RasUtils.safe_resolve(source)
    if not source.exists():
        raise ValueError(f"Layer file not found: {source}")
    return source


def _bool_attr(value: bool) -> str:
    return "True" if value else "False"


def _normalize_basemap_name(basemap_name: str) -> str:
    normalized = basemap_name.strip().casefold()
    lookup = {name.casefold(): name for name in STANDARD_BASEMAP_LAYERS}
    if normalized in lookup:
        return lookup[normalized]
    valid_names = ", ".join(STANDARD_BASEMAP_LAYERS)
    raise ValueError(f"Unknown basemap layer '{basemap_name}'. Valid names: {valid_names}")


def _apply_label_config(
    layer_elem: ET.Element,
    label_field: Optional[str],
    label_config: Optional[dict[str, Any]],
) -> None:
    if not label_field:
        return

    config = label_config or {}
    label_elem = ET.SubElement(layer_elem, "LabelFeatures")
    label_elem.set("Checked", "True")
    label_elem.set("PercentPosition", "0")
    label_elem.set("rows", "1")
    label_elem.set("cols", "1")
    label_elem.set("r0c0", label_field)
    label_elem.set("Position", str(config.get("position", 0)))
    label_elem.set("Color", str(config.get("color", -16777216)))
    label_elem.set("FontSize", str(config.get("font_size", 8.25)))


def _apply_symbology(
    layer_elem: ET.Element,
    symbology: Optional[dict[str, Any]],
) -> None:
    if not symbology:
        return

    sym_elem = ET.SubElement(layer_elem, "Symbology")
    if "line_color" in symbology:
        r, g, b, a = symbology["line_color"]
        pen_elem = ET.SubElement(sym_elem, "Pen")
        pen_elem.set("R", str(r))
        pen_elem.set("G", str(g))
        pen_elem.set("B", str(b))
        pen_elem.set("A", str(a))
        pen_elem.set("Dash", "0")
        pen_elem.set("Width", str(symbology.get("line_width", 2)))
    if "fill_color" in symbology:
        r, g, b, a = symbology["fill_color"]
        brush_elem = ET.SubElement(sym_elem, "Brush")
        brush_elem.set("Type", "SolidBrush")
        brush_elem.set("R", str(r))
        brush_elem.set("G", str(g))
        brush_elem.set("B", str(b))
        brush_elem.set("A", str(a))
        brush_elem.set("Name", "PolygonFill")


def _is_geojson_path(source_path: Path) -> bool:
    return source_path.suffix.lower() in {".geojson", ".json"}


def _extract_geojson_crs_name(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    crs = data.get("crs")
    if not isinstance(crs, dict):
        return None

    properties = crs.get("properties")
    if isinstance(properties, dict):
        name = properties.get("name") or properties.get("href")
        if name:
            return str(name)
    name = crs.get("name")
    return str(name) if name else None


def _crs_name_is_wgs84(crs_name: str) -> bool:
    crs_upper = crs_name.upper()
    if "CRS84" in crs_upper:
        return True
    if "EPSG" in crs_upper and "4326" in crs_upper:
        return True

    try:
        from pyproj import CRS

        crs = CRS.from_user_input(crs_name)
        return crs.to_epsg() == 4326
    except Exception:
        return False


def _geojson_bounds(data: Any) -> Optional[tuple[float, float, float, float]]:
    coords = list(_iter_geojson_positions(data))
    if not coords:
        return None
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _iter_geojson_positions(data: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(data, dict):
        return

    geojson_type = data.get("type")
    if geojson_type == "FeatureCollection":
        for feature in data.get("features", []):
            yield from _iter_geojson_positions(feature)
        return
    if geojson_type == "Feature":
        yield from _iter_geojson_positions(data.get("geometry"))
        return
    if geojson_type == "GeometryCollection":
        for geometry in data.get("geometries", []):
            yield from _iter_geojson_positions(geometry)
        return

    coordinates = data.get("coordinates")
    if coordinates is not None:
        yield from _walk_coordinate_values(coordinates)


def _walk_coordinate_values(value: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(value, list):
        return
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    for child in value:
        yield from _walk_coordinate_values(child)


def _first_geojson_geometry_type(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    geojson_type = data.get("type")
    if geojson_type == "FeatureCollection":
        for feature in data.get("features", []):
            geometry_type = _first_geojson_geometry_type(feature)
            if geometry_type is not None:
                return geometry_type
        return None
    if geojson_type == "Feature":
        return _first_geojson_geometry_type(data.get("geometry"))
    if geojson_type == "GeometryCollection":
        for geometry in data.get("geometries", []):
            geometry_type = _first_geojson_geometry_type(geometry)
            if geometry_type is not None:
                return geometry_type
        return None
    return str(geojson_type) if geojson_type else None


def _geometry_type_to_layer_type(geometry_type: str) -> str:
    normalized = geometry_type.lower()
    if normalized in {"point", "multipoint"}:
        return "PointFeatureLayer"
    if normalized in {"linestring", "multilinestring"}:
        return "PolylineFeatureLayer"
    if normalized in {"polygon", "multipolygon"}:
        return "PolygonFeatureLayer"
    return "PolylineFeatureLayer"


def _read_shapefile_shape_type(source_path: Path) -> Optional[int]:
    try:
        with source_path.open("rb") as shp_file:
            header = shp_file.read(36)
        if len(header) < 36:
            return None
        return struct.unpack("<i", header[32:36])[0]
    except OSError:
        return None


def _shapefile_shape_type_to_layer_type(shape_type: int) -> str:
    if shape_type in {1, 8, 11, 18, 21, 28}:
        return "PointFeatureLayer"
    if shape_type in {3, 13, 23}:
        return "PolylineFeatureLayer"
    if shape_type in {5, 15, 25, 31}:
        return "PolygonFeatureLayer"
    return "PolylineFeatureLayer"
