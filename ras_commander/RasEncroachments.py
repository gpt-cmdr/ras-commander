"""
RasEncroachments - 2D floodway encroachment authoring helpers.

This module writes the same plan companion GIS HDF layout used by RASMapper for
2D encroachment regions and zones. The editable authoring data lives beside the
plan file as ``<project>.p##.GIS.hdf`` under ``Plan Data/Encroachments``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import h5py
import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPlan import RasPlan
from .RasPrj import ras
from .RasUtils import RasUtils
from . import _land_classification_helper as _lch

logger = get_logger(__name__)


_PLAN_FILE_RE = re.compile(r"\.p\d{2,3}$", re.IGNORECASE)
_ENCROACHMENTS_GROUP = "Plan Data/Encroachments"
_REGIONS_GROUP = f"{_ENCROACHMENTS_GROUP}/Regions"
_ZONES_GROUP = f"{_ENCROACHMENTS_GROUP}/Zones"
_POLYGON_INFO_ATTRS = {
    "Column": np.array(
        [
            b"Point Starting Index",
            b"Point Count",
            b"Part Starting Index",
            b"Part Count",
        ]
    ),
    "Feature Type": np.bytes_("Polygon"),
    "Row": np.bytes_("Feature"),
}
_POLYGON_PARTS_ATTRS = {
    "Column": np.array([b"Point Starting Index", b"Point Count"]),
    "Row": np.bytes_("Part"),
}
_POLYGON_POINTS_ATTRS = {
    "Column": np.array([b"X", b"Y"]),
    "Row": np.bytes_("Points"),
}


class RasEncroachments:
    """Static helpers for 2D floodway encroachment authoring."""

    @staticmethod
    @log_call
    def set_2d_encroachment_regions(
        plan_number_or_path: Union[str, int, float, Path],
        regions: Union[pd.DataFrame, Sequence[Dict[str, Any]]],
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Replace the 2D encroachment regions for a plan.

        Each region entry accepts ``name``, ``polygon`` or ``parts``,
        ``fill_slope``, and ``additional_fill_rise``. Polygons may be a single
        ring ``[(x, y), ...]`` or multipart ``[[(x, y), ...], ...]``.
        """
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        normalized = [
            _normalize_region_record(record, idx)
            for idx, record in enumerate(_records_from_input(regions))
        ]
        hdf_path = _plan_gis_hdf_path(plan_path)
        _write_feature_table(hdf_path, _REGIONS_GROUP, normalized, "regions")
        logger.info("Wrote %s 2D encroachment region(s) to %s", len(normalized), hdf_path)
        return RasEncroachments.list_2d_encroachment_regions(plan_path)

    @staticmethod
    @log_call
    def list_2d_encroachment_regions(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        ras_object=None,
        prefer_results_hdf: bool = False,
    ) -> pd.DataFrame:
        """Read 2D encroachment regions from a plan GIS HDF or result HDF."""
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        hdf_path = _select_encroachment_hdf(plan_path, prefer_results_hdf)
        records = _read_feature_table(hdf_path, _REGIONS_GROUP, "regions")
        columns = [
            "fid",
            "name",
            "fill_slope",
            "additional_fill_rise",
            "polygon",
            "parts",
            "point_count",
            "part_count",
            "source_hdf",
        ]
        return pd.DataFrame(records, columns=columns)

    @staticmethod
    @log_call
    def set_2d_encroachment_zones(
        plan_number_or_path: Union[str, int, float, Path],
        zones: Union[pd.DataFrame, Sequence[Dict[str, Any]]],
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Replace the 2D encroachment zones for a plan.

        Each zone entry accepts ``name``, ``polygon`` or ``parts``, and
        ``value``. The ``value`` column is the RASMapper zone contour override.
        """
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        normalized = [
            _normalize_zone_record(record, idx)
            for idx, record in enumerate(_records_from_input(zones))
        ]
        hdf_path = _plan_gis_hdf_path(plan_path)
        _write_feature_table(hdf_path, _ZONES_GROUP, normalized, "zones")
        logger.info("Wrote %s 2D encroachment zone(s) to %s", len(normalized), hdf_path)
        return RasEncroachments.list_2d_encroachment_zones(plan_path)

    @staticmethod
    @log_call
    def list_2d_encroachment_zones(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        ras_object=None,
        prefer_results_hdf: bool = False,
    ) -> pd.DataFrame:
        """Read 2D encroachment zones from a plan GIS HDF or result HDF."""
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        hdf_path = _select_encroachment_hdf(plan_path, prefer_results_hdf)
        records = _read_feature_table(hdf_path, _ZONES_GROUP, "zones")
        columns = [
            "fid",
            "name",
            "value",
            "polygon",
            "parts",
            "point_count",
            "part_count",
            "source_hdf",
        ]
        return pd.DataFrame(records, columns=columns)

    @staticmethod
    @log_call
    def set_2d_encroachment_plan_settings(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        base_plan: Optional[Union[str, int, float, Path]] = None,
        target_rise: Optional[float] = None,
        fill_slope: Optional[float] = None,
        additional_fill: Optional[float] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Set unsteady 2D encroachment plan metadata.

        HEC-RAS reads the base plan filename and maximum target rise from
        ``Plan Data/Encroachments``. Fill slope and additional fill are stored
        with the same plan metadata and can also be applied as region defaults
        through :meth:`setup_2d_floodway_encroachment_plan`.
        """
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        hdf_path = _plan_gis_hdf_path(plan_path)

        with _open_gis_hdf_for_update(hdf_path) as hdf:
            group = _require_group(hdf, _ENCROACHMENTS_GROUP)
            if base_plan is not None:
                group.attrs["Base Plan Filename"] = _base_plan_filename_attr(
                    base_plan,
                    plan_path=plan_path,
                    ras_object=ras_object,
                )
            if target_rise is not None:
                group.attrs["Maximum Target Rise"] = np.float32(target_rise)
            if fill_slope is not None:
                group.attrs["Fill Slope"] = np.float32(fill_slope)
            if additional_fill is not None:
                group.attrs["Additional Fill"] = np.float32(additional_fill)

        logger.info("Updated 2D encroachment plan settings in %s", hdf_path)
        return RasEncroachments.get_2d_encroachment_plan_settings(plan_path)

    @staticmethod
    @log_call
    def get_2d_encroachment_plan_settings(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        ras_object=None,
        prefer_results_hdf: bool = False,
    ) -> Dict[str, Any]:
        """Read unsteady 2D encroachment plan metadata."""
        plan_path = _resolve_plan_path(plan_number_or_path, ras_object=ras_object)
        hdf_path = _select_encroachment_hdf(plan_path, prefer_results_hdf)
        settings = {
            "base_plan_filename": None,
            "maximum_target_rise": None,
            "fill_slope": None,
            "additional_fill": None,
            "source_hdf": str(hdf_path) if hdf_path and hdf_path.exists() else None,
        }
        if hdf_path is None or not hdf_path.exists():
            return settings

        with h5py.File(hdf_path, "r") as hdf:
            if _ENCROACHMENTS_GROUP not in hdf:
                return settings
            group = hdf[_ENCROACHMENTS_GROUP]
            if "Base Plan Filename" in group.attrs:
                settings["base_plan_filename"] = _decode_hdf_string(
                    group.attrs["Base Plan Filename"]
                )
            if "Maximum Target Rise" in group.attrs:
                settings["maximum_target_rise"] = float(group.attrs["Maximum Target Rise"])
            if "Fill Slope" in group.attrs:
                settings["fill_slope"] = float(group.attrs["Fill Slope"])
            if "Additional Fill" in group.attrs:
                settings["additional_fill"] = float(group.attrs["Additional Fill"])
        return settings

    @staticmethod
    @log_call
    def ensure_2d_encroachment_plan_layers(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        geom_hdf_path: Optional[Union[str, Path]] = None,
        checked: bool = True,
        ras_object=None,
    ) -> Path:
        """
        Ensure the RASMapper ``Plans`` tree has Encroachments, Zones, and Regions.
        """
        from .RasMap import RasMap

        return RasMap.ensure_2d_encroachment_plan_layers(
            plan_number_or_path,
            geom_hdf_path=geom_hdf_path,
            checked=checked,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def setup_2d_floodway_encroachment_plan(
        template_plan: Union[str, int, float, Path],
        *,
        base_plan: Optional[Union[str, int, float, Path]] = None,
        new_plan_shortid: Optional[str] = None,
        new_title: Optional[str] = None,
        target_rise: Optional[float] = None,
        regions: Optional[Union[pd.DataFrame, Sequence[Dict[str, Any]]]] = None,
        zones: Optional[Union[pd.DataFrame, Sequence[Dict[str, Any]]]] = None,
        default_fill_slope: Optional[float] = None,
        default_additional_fill: Optional[float] = None,
        zone_contour_overrides: Optional[Dict[str, float]] = None,
        add_rasmap_layers: bool = True,
        add_depth_velocity_map: bool = False,
        depth_velocity_plan_name: Optional[str] = None,
        terrain_name: Optional[str] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Create or configure a 2D floodway encroachment plan from structured input.

        When ``new_plan_shortid`` or ``new_title`` is supplied, ``template_plan``
        is cloned with :meth:`RasPlan.clone_plan` before authoring the companion
        GIS HDF. Otherwise the template plan itself is updated.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if new_plan_shortid is not None or new_title is not None:
            plan_number = RasPlan.clone_plan(
                template_plan,
                new_plan_shortid=new_plan_shortid,
                new_title=new_title,
                ras_object=ras_obj,
            )
        else:
            plan_path = _resolve_plan_path(template_plan, ras_object=ras_obj)
            plan_number = _plan_number_from_path(plan_path)

        plan_path = _resolve_plan_path(plan_number, ras_object=ras_obj)

        if (
            base_plan is not None
            or target_rise is not None
            or default_fill_slope is not None
            or default_additional_fill is not None
        ):
            RasEncroachments.set_2d_encroachment_plan_settings(
                plan_path,
                base_plan=base_plan,
                target_rise=target_rise,
                fill_slope=default_fill_slope,
                additional_fill=default_additional_fill,
                ras_object=ras_obj,
            )

        regions_df = pd.DataFrame()
        if regions is not None:
            regions_df = RasEncroachments.set_2d_encroachment_regions(
                plan_path,
                _apply_region_defaults(
                    _records_from_input(regions),
                    default_fill_slope=default_fill_slope,
                    default_additional_fill=default_additional_fill,
                ),
                ras_object=ras_obj,
            )

        zones_df = pd.DataFrame()
        if zones is not None:
            zones_df = RasEncroachments.set_2d_encroachment_zones(
                plan_path,
                _apply_zone_overrides(
                    _records_from_input(zones),
                    zone_contour_overrides=zone_contour_overrides,
                ),
                ras_object=ras_obj,
            )
        elif zone_contour_overrides:
            raise ValueError("zone_contour_overrides requires zones input to match by name")

        rasmap_path = None
        if add_rasmap_layers:
            rasmap_path = RasEncroachments.ensure_2d_encroachment_plan_layers(
                plan_path,
                ras_object=ras_obj,
            )

        depth_velocity_layer = None
        if add_depth_velocity_map:
            from .RasMap import RasMap

            host_plan_name = depth_velocity_plan_name or _plan_display_name(plan_path)
            depth_velocity_layer = RasMap.add_results_map_layer(
                host_plan_name=host_plan_name,
                layer_name="Depth * Velocity",
                map_type="depth and velocity",
                terrain_name=terrain_name,
                ras_object=ras_obj,
            )

        return {
            "plan_number": plan_number,
            "plan_path": plan_path,
            "gis_hdf_path": _plan_gis_hdf_path(plan_path),
            "settings": RasEncroachments.get_2d_encroachment_plan_settings(plan_path),
            "regions": regions_df,
            "zones": zones_df,
            "rasmap_path": rasmap_path,
            "depth_velocity_layer": depth_velocity_layer,
        }


def _resolve_plan_path(
    plan_number_or_path: Union[str, int, float, Path],
    *,
    ras_object=None,
) -> Path:
    candidate = Path(str(plan_number_or_path))
    if candidate.exists() and _PLAN_FILE_RE.search(candidate.name):
        return RasUtils.safe_resolve(candidate)

    if _PLAN_FILE_RE.search(candidate.name) and candidate.parent.exists():
        raise FileNotFoundError(f"Plan file not found: {candidate}")

    ras_obj = ras_object or ras
    ras_obj.check_initialized()
    plan_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
    if plan_path is None or not Path(plan_path).exists():
        raise FileNotFoundError(f"Plan file not found for plan: {plan_number_or_path}")
    return RasUtils.safe_resolve(Path(plan_path))


def _plan_number_from_path(plan_path: Path) -> str:
    match = re.search(r"\.p(\d{2,3})$", plan_path.name, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not determine plan number from {plan_path}")
    return RasUtils.normalize_ras_number(match.group(1))


def _plan_gis_hdf_path(plan_path: Path) -> Path:
    return Path(str(plan_path) + ".GIS.hdf")


def _plan_results_hdf_path(plan_path: Path) -> Path:
    return Path(str(plan_path) + ".hdf")


def _select_encroachment_hdf(plan_path: Path, prefer_results_hdf: bool) -> Optional[Path]:
    gis_hdf = _plan_gis_hdf_path(plan_path)
    results_hdf = _plan_results_hdf_path(plan_path)
    if prefer_results_hdf and results_hdf.exists():
        return results_hdf
    if gis_hdf.exists():
        return gis_hdf
    if results_hdf.exists():
        return results_hdf
    return gis_hdf


def _open_gis_hdf_for_update(hdf_path: Path) -> h5py.File:
    hdf_path.parent.mkdir(parents=True, exist_ok=True)
    return h5py.File(hdf_path, "a")


def _require_group(hdf: h5py.File, group_path: str) -> h5py.Group:
    group = hdf
    for part in group_path.split("/"):
        group = group.require_group(part)
    return group


def _records_from_input(data: Union[pd.DataFrame, Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")
    if data is None:
        return []
    return [dict(record) for record in data]


def _normalize_region_record(record: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "name": str(record.get("name") or record.get("Name") or f"Region {idx + 1}"),
        "parts": _normalize_polygon_parts(_extract_polygon(record)),
        "fill_slope": _as_float32_or_nan(
            _first_present(record, ("fill_slope", "Fill Slope", "fillSlope"))
        ),
        "additional_fill_rise": _as_float32_or_nan(
            _first_present(
                record,
                (
                    "additional_fill_rise",
                    "additional_fill",
                    "Additional Fill Rise",
                    "additionalRise",
                ),
            )
        ),
    }


def _normalize_zone_record(record: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "name": str(record.get("name") or record.get("Name") or f"Zone {idx + 1}"),
        "parts": _normalize_polygon_parts(_extract_polygon(record)),
        "value": _as_float32_or_nan(
            _first_present(record, ("value", "Value", "contour_value", "contourValue"))
        ),
    }


def _extract_polygon(record: Dict[str, Any]) -> Any:
    for key in ("polygon", "parts", "rings", "coordinates", "geometry"):
        if key in record and record[key] is not None:
            return record[key]
    raise ValueError(f"Missing polygon/parts geometry in record: {record}")


def _first_present(record: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _as_float32_or_nan(value: Any) -> np.float32:
    if value is None or value == "":
        return np.float32(np.nan)
    return np.float32(value)


def _normalize_polygon_parts(polygon: Any) -> List[List[List[float]]]:
    if isinstance(polygon, dict):
        geometry_type = str(polygon.get("type", "")).lower()
        coordinates = polygon.get("coordinates")
        if geometry_type == "polygon":
            polygon = coordinates
        elif geometry_type == "multipolygon":
            polygon = [ring for poly in coordinates for ring in poly]
        else:
            raise ValueError(f"Unsupported geometry type for encroachment polygon: {geometry_type}")

    if not isinstance(polygon, Sequence) or isinstance(polygon, (str, bytes)):
        raise ValueError("Polygon geometry must be a point sequence or multipart sequence")

    if len(polygon) == 0:
        raise ValueError("Polygon geometry must contain at least one part")

    if _is_point(polygon[0]):
        raw_parts = [polygon]
    else:
        raw_parts = polygon

    parts: List[List[List[float]]] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, Sequence) or isinstance(raw_part, (str, bytes)):
            raise ValueError("Each polygon part must be a point sequence")
        points = [_normalize_point(point) for point in raw_part]
        if len(points) < 3:
            raise ValueError("Each polygon part must contain at least three points")
        if points[0] != points[-1]:
            points.append(points[0].copy())
        if len(points) < 4:
            raise ValueError("Each polygon part must contain at least four closed-ring points")
        parts.append(points)
    return parts


def _is_point(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    if len(value) < 2:
        return False
    try:
        float(value[0])
        float(value[1])
    except (TypeError, ValueError):
        return False
    return True


def _normalize_point(point: Sequence[Any]) -> List[float]:
    if not _is_point(point):
        raise ValueError(f"Invalid polygon point: {point}")
    return [float(point[0]), float(point[1])]


def _write_feature_table(
    hdf_path: Path,
    group_path: str,
    records: Sequence[Dict[str, Any]],
    feature_kind: str,
) -> None:
    with _open_gis_hdf_for_update(hdf_path) as hdf:
        _require_group(hdf, _ENCROACHMENTS_GROUP)
        if group_path in hdf:
            del hdf[group_path]
        group = _require_group(hdf, group_path)

        polygon_info, polygon_parts, polygon_points = _build_polygon_arrays(records)
        _create_dataset_with_attrs(group, "Polygon Info", polygon_info, _POLYGON_INFO_ATTRS)
        _create_dataset_with_attrs(group, "Polygon Parts", polygon_parts, _POLYGON_PARTS_ATTRS)
        _create_dataset_with_attrs(group, "Polygon Points", polygon_points, _POLYGON_POINTS_ATTRS)
        group.create_dataset("Attributes", data=_build_attribute_array(records, feature_kind))


def _create_dataset_with_attrs(
    group: h5py.Group,
    name: str,
    data: np.ndarray,
    attrs: Dict[str, Any],
) -> None:
    dataset = group.create_dataset(name, data=data)
    for key, value in attrs.items():
        dataset.attrs[key] = value


def _build_polygon_arrays(
    records: Sequence[Dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    info_rows = []
    part_rows = []
    point_rows = []

    for record in records:
        point_start = len(point_rows)
        part_start = len(part_rows)
        for part in record["parts"]:
            part_point_start = len(point_rows)
            point_rows.extend(part)
            part_rows.append([part_point_start, len(part)])
        info_rows.append(
            [
                point_start,
                len(point_rows) - point_start,
                part_start,
                len(record["parts"]),
            ]
        )

    return (
        np.asarray(info_rows, dtype=np.int32).reshape((-1, 4)),
        np.asarray(part_rows, dtype=np.int32).reshape((-1, 2)),
        np.asarray(point_rows, dtype=np.float64).reshape((-1, 2)),
    )


def _build_attribute_array(records: Sequence[Dict[str, Any]], feature_kind: str) -> np.ndarray:
    name_width = max([1] + [len(record["name"].encode("utf-8")) for record in records])
    if feature_kind == "regions":
        dtype = np.dtype(
            [
                ("Name", f"S{name_width}"),
                ("Fill Slope", "<f4"),
                ("Additional Fill Rise", "<f4"),
            ]
        )
        return np.asarray(
            [
                (
                    record["name"].encode("utf-8"),
                    record["fill_slope"],
                    record["additional_fill_rise"],
                )
                for record in records
            ],
            dtype=dtype,
        )

    if feature_kind == "zones":
        dtype = np.dtype([("Name", f"S{name_width}"), ("Value", "<f4")])
        return np.asarray(
            [
                (
                    record["name"].encode("utf-8"),
                    record["value"],
                )
                for record in records
            ],
            dtype=dtype,
        )

    raise ValueError(f"Unsupported feature kind: {feature_kind}")


def _read_feature_table(
    hdf_path: Optional[Path],
    group_path: str,
    feature_kind: str,
) -> List[Dict[str, Any]]:
    if hdf_path is None or not hdf_path.exists():
        return []

    with h5py.File(hdf_path, "r") as hdf:
        if group_path not in hdf:
            return []
        group = hdf[group_path]
        if not all(name in group for name in ("Attributes", "Polygon Info", "Polygon Parts", "Polygon Points")):
            return []

        attrs = group["Attributes"][:]
        polygon_info = group["Polygon Info"][:]
        polygon_parts = group["Polygon Parts"][:]
        polygon_points = group["Polygon Points"][:]

        records = []
        for fid, row in enumerate(attrs):
            info = polygon_info[fid]
            point_start, point_count, part_start, part_count = [int(value) for value in info]
            del point_start, point_count
            parts = []
            for part_row in polygon_parts[part_start : part_start + part_count]:
                part_point_start, part_point_count = [int(value) for value in part_row]
                parts.append(
                    polygon_points[
                        part_point_start : part_point_start + part_point_count
                    ].astype(float).tolist()
                )

            record = {
                "fid": fid,
                "name": _decode_hdf_string(row["Name"]),
                "polygon": parts[0] if len(parts) == 1 else parts,
                "parts": parts,
                "point_count": sum(len(part) for part in parts),
                "part_count": len(parts),
                "source_hdf": str(hdf_path),
            }
            if feature_kind == "regions":
                record["fill_slope"] = _float_or_nan(row["Fill Slope"])
                record["additional_fill_rise"] = _float_or_nan(row["Additional Fill Rise"])
            elif feature_kind == "zones":
                record["value"] = _float_or_nan(row["Value"])
            records.append(record)
        return records


def _float_or_nan(value: Any) -> float:
    value = float(value)
    return math.nan if math.isnan(value) else value


def _decode_hdf_string(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8").rstrip("\x00")
    if isinstance(value, np.ndarray) and value.shape == ():
        return _decode_hdf_string(value.item())
    return str(value)


def _base_plan_filename_attr(
    base_plan: Union[str, int, float, Path],
    *,
    plan_path: Path,
    ras_object=None,
) -> str:
    try:
        base_plan_path = _resolve_plan_path(base_plan, ras_object=ras_object)
    except Exception:
        return str(base_plan)
    return _lch.to_rasmap_relative_path(plan_path.parent, base_plan_path)


def _apply_region_defaults(
    records: Sequence[Dict[str, Any]],
    *,
    default_fill_slope: Optional[float],
    default_additional_fill: Optional[float],
) -> List[Dict[str, Any]]:
    updated = []
    for record in records:
        item = dict(record)
        if default_fill_slope is not None and not any(
            key in item for key in ("fill_slope", "Fill Slope", "fillSlope")
        ):
            item["fill_slope"] = default_fill_slope
        if default_additional_fill is not None and not any(
            key in item
            for key in (
                "additional_fill_rise",
                "additional_fill",
                "Additional Fill Rise",
                "additionalRise",
            )
        ):
            item["additional_fill_rise"] = default_additional_fill
        updated.append(item)
    return updated


def _apply_zone_overrides(
    records: Sequence[Dict[str, Any]],
    *,
    zone_contour_overrides: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    if not zone_contour_overrides:
        return [dict(record) for record in records]

    unmatched = set(zone_contour_overrides)
    updated = []
    for record in records:
        item = dict(record)
        name = str(item.get("name") or item.get("Name") or "")
        if name in zone_contour_overrides:
            item["value"] = zone_contour_overrides[name]
            unmatched.discard(name)
        updated.append(item)

    if unmatched:
        raise ValueError(
            "zone_contour_overrides contains names not present in zones: "
            + ", ".join(sorted(unmatched))
        )
    return updated


def _plan_display_name(plan_path: Path) -> str:
    short_id = _read_plan_text_value(plan_path, "Short Identifier")
    if short_id:
        return short_id
    title = _read_plan_text_value(plan_path, "Plan Title")
    if title:
        return title
    return plan_path.stem


def _read_plan_text_value(plan_path: Path, key: str) -> str:
    if not plan_path.exists():
        return ""
    for line in plan_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""
